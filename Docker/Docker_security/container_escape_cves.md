# CVE побегов из контейнеров (Container Escape)

**Актуально для:** Docker Engine 29.x, runc 1.2.8+, containerd 1.7.x/2.x, BuildKit 0.33.x. Каталог охватывает уязвимости 2019–2026 годов; все перечисленные исправления содержатся в актуальных версиях.

Данный файл описывает наиболее значимые CVE, позволяющие побег из контейнера (container escape) или эскалацию привилегий в Docker-окружении: механику эксплуатации, затронутые версии, проверку защищённости хоста и детекцию. Это практический справочник для SRE: что именно проверять при аудите хоста и что спрашивают на собеседованиях.

## Определения

**Container Escape (побег из контейнера)** — эксплуатация уязвимости в рантайме, ядре или инструментах Docker, позволяющая процессу внутри контейнера выйти за границы изоляции и выполнить код или получить доступ к файловой системе хоста.

**runc** — низкоуровневая OCI-среда выполнения, непосредственно создающая namespaces и запускающая процессы контейнера. Docker, containerd, CRI-O и Podman используют runc как общий компонент — уязвимость в runc затрагивает все эти платформы.

**containerd-shim** — процесс-посредник между containerd и контейнером, держит stdio и API-сокет контейнера. Абстрактный Unix-сокет shim'а — исторический вектор атаки (CVE-2020-15257).

**BuildKit frontend** — образ, определяющий логику сборки (LLB). Dockerfile транслируется во встроенный frontend `dockerfile/frontend`. Загрузка стороннего frontend'а (`--frontend`) — отдельный вектор атаки на этапе сборки.

**CVSS / EPSS** — CVSS оценивает тяжесть уязвимости по вектору атаки; EPSS (Exploit Prediction Scoring System) оценивает вероятность эксплуатации в ближайшие 30 дней. Для приоритизации патчинга EPSS информативнее CVSS: CVE-2019-5736 имеет EPSS ≈ 0.98, то есть эксплуатируется в реальности.

## Базовые концепции

### Классы атак побега

Побеги из контейнеров группируются по компоненту, в котором находится дефект:

| Класс | Компонент | Типичный вектор | Примеры |
| :--- | :--- | :--- | :--- |
| **Рантайм (runc)** | runc | Утечка fd, обработка `/proc/self/exe`, `process.cwd`, procfs write redirects | CVE-2019-5736, CVE-2024-21626, CVE-2025-31133, CVE-2025-52881 |
| **Инструменты Docker** | `docker cp`, CLI | Динамическая загрузка библиотек внутри chroot | CVE-2019-14271 |
| **Рантайм (containerd)** | containerd-shim | Абстрактный сокет shim'а в host-сети | CVE-2020-15257 |
| **Ядро Linux** | kernel | Pipe buffer, cgroups, eBPF | CVE-2022-0847 (Dirty Pipe) |
| **Сборка (BuildKit)** | BuildKit | Race condition, очистка mountpoint'ов, frontend, control API, cache poisoning | CVE-2024-23651/23652/23653, CVE-2026-61711/15792/61712/75593/93318 |
| **Сеть** | Docker DNS/RA | Эксфильтрация через DNS, spoofing RA | CVE-2024-29018, CVE-2020-13401 |

### Почему побег возможен даже с `--cap-drop=ALL`

Механизмы изоляции (namespaces, capabilities, seccomp) ограничивают **контейнер**, но не защищают от дефектов в коде, который работает **от имени хоста** (runc, shim, dockerd). Процесс runc выполняется на хосте с правами root: если он по ошибке передаёт контейнеру дескриптор хостовой ФС или позволяет перезаписать свой бинарник, никакие capabilities внутри контейнера не помогут — атака идёт извне изоляции. Поэтому патчинг рантайма и минимизация привилегий — независимые, а не взаимозаменяемые меры.

## Практические сценарии

### Сценарий 1: CVE-2024-21626 (Leaky Vessels) — runc

Наиболее свежий и релевантный побег. Обнаружен Snyk Labs, раскрыт 31.01.2024.

**Механика:** runc ≤ 1.1.11 утекает внутренние файловые дескрипторы в `runc init`, включая дескриптор хостового `/sys/fs/cgroup` (утечка появилась в v1.0.0-rc93). Если `process.cwd` контейнера установлен в `/proc/self/fd/7/` (номер fd зависит от порядка открытия файлов), PID 1 получает рабочую директорию в **хостовом** mount namespace — процесс видит всю ФС хоста. runc не проверял, что итоговый `cwd` остался внутри контейнера после `chdir(2)`.

**Четыре атаки:**

| Атака | Вектор | Что даёт |
| :--- | :--- | :--- |
| **1** | Зловредный образ (`process.cwd` → `/proc/self/fd/7/`) при `docker run` | Доступ к ФС хоста; требует, чтобы пользователь запустил зловредный образ |
| **2** | То же, но изнутри контейнера через `docker exec` | Побег из скомпрометированного контейнера без участия оператора |
| **3a** | `process.args` = `/proc/self/fd/7/../../../bin/bash` + перезапись через `/proc/$pid/exe` | Перезапись хостового бинарника (как в CVE-2019-5736) |
| **3b** | То же, но контейнер подменяет все бинарники, которые может выполнить `docker exec` | Полный побег; **практического обхода нет, кроме отказа от `docker exec`** |

**Затронутые версии и исправления:**

| Компонент | Уязвим | Исправлен |
| :--- | :--- | :--- |
| runc | ≥ 1.0.0-rc93, ≤ 1.1.11 | 1.1.12 |
| Moby (Docker Engine) | ≤ 25.0.1, ≤ 24.0.8 | ≥ 25.0.2, ≥ 24.0.9 |
| containerd | < 1.6.28; 1.7.0–1.7.12 | 1.6.28, 1.7.13 |
| BuildKit (сопутствующие CVE) | ≤ 0.12.4 | 0.12.5 |

**Проверка хоста:**

```bash
# Версия runc, которым работает демон
docker version --format '{{range .Server.Components}}{{if eq .Name "runc"}}{{.Version}}{{end}}{{end}}'
# → 1.2.4 (>= 1.1.12 — защищён)

# Версия containerd
containerd --version
# → containerd v1.7.25 (>= 1.7.13 — защищён)
```

**Обходы (workarounds) при невозможности патча:**
- Атаки 1 и 2: разрешать контейнерам и `docker exec` только `process.cwd` = `/` (корень нельзя подменить symlink'ом — путь резолвится внутри mount namespace контейнера).
- Атаки 1 и 3a: запускать только доверенные образы.
- Атака 3b: не использовать `docker exec` (непрактично для production — аргумент в пользу патчинга).

### Сценарий 2: CVE-2019-5736 — перезапись бинарника runc

**Механика:** runc ≤ 1.0-rc6 (Docker < 18.09.2) некорректно обрабатывал файловые дескрипторы, связанные с `/proc/self/exe`. Процесс внутри контейнера мог перезаписать хостовый бинарник runc через `/proc/self/exe`; при следующем `docker exec` код выполнялся на хосте с правами root.

**Параметры:** CVSS 8.6 (HIGH), EPSS ≈ 0.98 — один из наиболее эксплуатируемых CVE в экосистеме контейнеров.

**Исправление:** runc копирует `/proc/self/exe` в sealed `memfd` и переисполняется из него при каждом `runc create`/`runc exec` (commit 0a8e4117). Docker 18.09.2, runc 1.0-rc6+.

**Митигации без патча (исторически):** SELinux в enforcing-режиме (RHEL/OpenShift — неуязвимы), read-only `/usr` (RHEL Atomic Host).

**Детекция эксплуатации:** аудит выполнения бинарников рантайма:

```bash
sudo auditctl -w /usr/bin/runc -p x -k runc_exec
sudo auditctl -w /usr/sbin/runc -p x -k runc_exec
# Поиск: sudo ausearch -k runc_exec -i
```

### Сценарий 3: CVE-2019-14271 — побег через `docker cp`

**Механика:** Docker 19.03.0, слинкованный с glibc: при `docker cp` механизм `nsswitch` динамически загружал библиотеку внутри chroot, содержащего содержимое контейнера. Скомпрометированный контейнер (или зловредный образ) мог подложить библиотеку, которая выполнится на хосте с правами root при копировании файлов. Первый полный побег после CVE-2019-5736.

**Параметры:** CVSS 9.8 (CRITICAL, CVSS 3.x). Затронут только 19.03.0; исправлен в 19.03.1.

**Практический вывод:** `docker cp` из недоверенного контейнера — операция с правами root на хосте. В современных версиях дефект исправлен, но принцип остаётся: не копируйте файлы из контейнеров, происхождение которых не проверено.

### Сценарий 4: CVE-2020-15257 — сокет containerd-shim в host-сети

**Механика:** containerd < 1.3.9 и 1.4.0–1.4.2: контроль доступа к API-сокету shim'а проверял только effective UID 0, но не ограничивал доступ к абстрактному Unix-сокету. Зловредный контейнер в **host-сетевом namespace** с UID 0 (но иными сниженными привилегиями) мог запускать процессы с повышенными правами.

**Ключевой факт:** уязвимы только конфигурации, где недоверенные пользователи могут запускать контейнеры с `--network=host` и UID 0. Контейнеры без host-сети не уязвимы.

**Исправление:** containerd 1.3.9 / 1.4.3 (Docker 19.03.14+). **Важно:** контейнеры, запущенные старым shim'ом, остаются уязвимыми после апгрейда — их нужно остановить и пересоздать.

**Обход (workaround):** запрет абстрактных сокетов через AppArmor — строка `deny unix addr=@**` в политике.

### Сценарий 5: CVE-2022-0847 (Dirty Pipe) — эскалация через ядро

**Механика:** ядра Linux 5.8–5.16.10, 5.15.x < 5.15.25, 5.10.x < 5.10.102: перезапись флагов pipe-буфера через `splice()` позволяет записывать данные в файлы, открытые только для чтения (например, внедрить пользователя в `/etc/passwd`). В контейнере — путь к эскалации при уязвимом ядре хоста.

**Детекция:** мониторинг системного вызова `splice()` от непривилегированных пользователей (правила Wazuh и auditd — см. [Детекция Dirty Pipe](../../Security/Tools/Wazuh/kernel_monitoring.md#настройка-детекции-dirty-pipe-cve-2022-0847)). Эксплуатация и PoC — в [traitor](../../Security/Tools/traitor.md).

**Проверка ядра:**

```bash
uname -r
# → 6.8.0-45-generic (не в диапазоне 5.8–5.16.10 — защищён)
```

### Сценарий 6: BuildKit — CVE-2024/23651/23652/23653 и CVE-2026/61711/15792/61712/75593/93318

Три уязвимости BuildKit ≤ 0.12.4 (исправлены в 0.12.5), раскрыты вместе с Leaky Vessels 31.01.2024:

| CVE | Механика | CVSS | Обход |
| :--- | :--- | :--- | :--- |
| **CVE-2024-23651** | Race condition: два зловредных шага сборки, разделяющие cache-mount'ы с subpath'ами → файлы хоста доступны контейнеру сборки | 7.4 (High) | Не использовать недоверенные frontend'ы и недоверенные Dockerfile с `--mount=type=cache,source=...` |
| **CVE-2024-23652** | Зловредный frontend/Dockerfile с `RUN --mount` обманывает очистку пустых mountpoint'ов → удаление файлов **на хосте** (path traversal) | 10.0 (GitHub CNA) / 8.7 | Не использовать недоверенные frontend'ы и недоверенные Dockerfile с `RUN --mount` |
| **CVE-2024-23653** | Эскалация привилегий через зловредный BuildKit frontend | 7.7 (High) | Не использовать недоверенные frontend'ы |

Уязвимости 2026 года:

| CVE | Механика | CVSS | Фикс |
| :--- | :--- | :--- | :--- |
| **CVE-2026-61711** | Кастомный frontend (`#syntax` или `--frontend`) отключает Seccomp/AppArmor для build-контейнера | 5.3 (Medium) | BuildKit ≥ 0.31.1 |
| **CVE-2026-15792** | Зловредный client/frontend вызывает panic buildkitd через некорректные параметры запроса | — | BuildKit ≥ 0.31.2 |
| **CVE-2026-61712** | DoS: unbounded group parsing при создании контейнера из зловредного образа → OOM-kill buildkitd | 2.3 (Low) | BuildKit ≥ 0.31.1 |
| **CVE-2026-75593** | Path traversal через control API upload: аутентифицированный client выходит за пределы state directory → модификация/удаление файлов хоста | 6.5 (Medium) | BuildKit ≥ 0.31.2 |
| **CVE-2026-93318** | Cache poisoning: зловредный образ рекламирует DiffIDs другого образа; BuildKit подменяет кэш → последующие сборки выполняют код на хосте или читают секреты | 7.5 (High) | BuildKit ≥ 0.33.1 |

**Практический вывод:** сборка недоверенного Dockerfile с BuildKit — выполнение кода с правами демона сборки. Патч: BuildKit ≥ 0.33.1. Проверка:

```bash
docker buildx version
# → github.com/docker/buildx v0.37.x (BuildKit 0.33.x — защищён)
```

### Сценарий 7: проверка хоста целиком

Комплексная проверка защищённости хоста от перечисленных CVE:

```bash
# 1. Версии компонентов
docker version --format '{{.Server.Version}}'
# → 29.8.1 (>= 25.0.2 защищён от Leaky Vessels)
docker version --format '{{range .Server.Components}}{{.Name}} {{.Version}}{{"\n"}}{{end}}'
# → containerd 1.7.36 (>= 1.7.13 защищён от Leaky Vessels / CVE-2026-47262)
# → runc 1.2.8 (>= 1.2.8 защищён от CVE-2025-31133/52881/52565)
# → docker-init 0.19.0
# → buildkit 0.33.1 (>= 0.33.1 защищён от CVE-2026-93318)

# 2. Ядро (Dirty Pipe диапазон: 5.8–5.16.10, 5.15<5.15.25, 5.10<5.10.102)
uname -r

# 3. BuildKit
docker buildx version

# 4. Сканирование образа на известные CVE (включая CVE рантайма в базовых образах)
trivy image --severity CRITICAL,HIGH --ignore-unfixed my-app:latest
```

### Сценарий 8: CVE-2025-31133 / CVE-2025-52881 / CVE-2025-52565 — runc procfs write redirects

Набор из трёх связанных уязвимостей в runc, раскрытых в ноябре 2025 года. В Docker частично митигируются ro-слоем верхнего уровня, но остаются риск для non-Docker сред и потенциальный bypass LSMs.

**Механика (CVE-2025-31133):** runc ≤ 1.2.7 (и 1.3.0-rc.1–1.3.1, 1.4.0-rc.1–rc.2) недостаточно проверяет inode `/dev/null` при bind-mount'е. Через race condition с shared mounts (включая `docker buildx build`) злоумышленник может:
- заменить `/dev/null` на symlink → произвольный mount gadget → container escape через `/proc/sys/kernel/core_pattern` (kernel upcalls не namespaced, выполняется на хосте с root)
- DoS хоста через запись в `/proc/sysrq-trigger`
- обойти `maskedPaths` (sensitive `/proc` файлы становятся доступны)

**CVE-2025-52881:** аналогичный race в bind-mount `/dev/pts/$n` → `/dev/console` (до `maskedPaths`). Даёт запись в `/proc/sysrq-trigger` и `/proc/sys/kernel/core_pattern`.

**CVE-2025-52565:** часть того же патчсета, затрагивает sysctl-записи.

**Затронутые версии и исправления:**

| Компонент | Уязвим | Исправлен |
| :--- | :--- | :--- |
| runc | ≤ 1.2.7, 1.3.0-rc.1–1.3.1, 1.4.0-rc.1–rc.2 | 1.2.8, 1.3.3, 1.4.0-rc.3 |
| Docker Engine | < 29.3.1 (AuthZ bypass CVE-2026-34040 — отдельный, но в том же окне обновлений) | ≥ 29.3.1 |

**Почему Docker частично защищён:** Docker создаёт верхний ro-слой, который маскирует любые симлинки `/dev` в образе. Однако:
- `docker buildx build` с shared mounts может всё же активировать race
- containerd и Podman без ro-маскировки уязвимы напрямую
- rootless-контейнеры снижают воздействие (runc работает от непривилегированного пользователя)

**Проверка хоста:**

```bash
runc --version
# → runc version 1.2.8 (>= 1.2.8 — защищён)
```

**Митигации без патча:**
- Обновить runc ≥ 1.2.8.
- Использовать rootless-контейнеры (снижает привилегии runc-процесса).
- Отказаться от shared mounts в BuildKit (`--mount=type=bind` с `bind-propagation=rprivate`).
- Включить SELinux/AppArmor (Docker-default профиль ограничивает запись в `/proc/sysrq-trigger`).

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Хост на Docker 24.0.8 или старее | Не установлен патч Leaky Vessels | `docker version` → апгрейд до ≥ 24.0.9 (или ≥ 25.0.2). Рестарт демона не требуется для обновления пакетов runc/containerd в некоторых дистрибутивах, но контейнеры, запущенные старым runc, остаются уязвимыми до пересоздания |
| Контейнер запущен до апгрейда containerd | Старый shim продолжает обслуживать контейнер (CVE-2020-15257) | Остановить и пересоздать контейнер: `docker stop <c> && docker rm <c>` |
| `docker exec` в production обязателен, патч невозможен | Атака 3b CVE-2024-21626 не имеет обхода | Единственное решение — патч runc ≥ 1.1.12; временно ограничьте `docker exec` доверенными операторами |
| Сборка недоверенного Dockerfile падает/ведёт себя странно | Возможная эксплуатация CVE-2024-23651/23652 | Не собирайте недоверенные Dockerfile с `--mount`; обновите BuildKit ≥ 0.33.1; используйте `--network=none` на этапе сборки |
| Подозрение на эксплуатацию Dirty Pipe | Аномальные записи в `/etc/passwd`, SUID-файлы | `sudo ausearch -k dirty_pipe -i`; проверка целостности: `rpm -Va` / `debsums -c`; патч ядра |
| Контейнер в host-сети с UID 0 | Конфигурация уязвима к CVE-2020-15257 на старом containerd | Убрать `--network=host` или запускать с non-root UID; обновить containerd |
| runc < 1.2.8 на shared-mount окружении | CVE-2025-31133/52881/52565: race на `/dev/null` → произвольный mount → escape через `/proc/sys/kernel/core_pattern` | Обновить runc ≥ 1.2.8; использовать rootless-контейнеры; отключить shared mounts в BuildKit |
| Cache poisoning в BuildKit | CVE-2026-93318: недоверенный образ отравил кэш DiffIDs | `docker buildx prune --all --force`; использовать ephemeral builder для недоверенных образов |
| Control API BuildKit доступен всем | CVE-2026-75593: path traversal → модификация файлов хоста | Ограничить доступ к Unix-сокет / TLS по IP; обновить BuildKit ≥ 0.31.2 |
| Frontend отключил AppArmor/Seccomp | CVE-2026-61711: зловредный `#syntax` в Dockerfile | Проверить Dockerfile на `# syntax=`; использовать только `docker/dockerfile:1` или доверенные frontend'ы |

## Лучшие практики

1. **Патчите рантайм в приоритете.** runc/containerd — общий компонент всех контейнерных платформ; уязвимость в них обходит все механизмы изоляции контейнера. Подпишитесь на [Docker Security Advisories](https://docs.docker.com/security/security-announcements) и OSS-Security mailing list. runc ≥ 1.2.8 обязателен для защиты от CVE-2025-31133/52881/52565.
2. **Минимизируйте `docker exec` в production.** Атака 3b (CVE-2024-21626) не имеет практического обхода; каждый `exec` — потенциальный вектор на непропатченном хосте.
3. **Не собирайте недоверенные Dockerfile.** BuildKit frontend'ы и `RUN --mount` выполняются с правами демона сборки (CVE-2024/23651/23652/23653, CVE-2026/61711/15792/61712/75593/93318). Для чужих репозиториев — изолированный builder с минимальными правами. BuildKit ≥ 0.33.1 обязателен.
4. **Избегайте `--network=host` для недоверенных контейнеров.** Host-сеть исторически экспонирует API containerd-shim (CVE-2020-15257) и снимает сетевую изоляцию целиком.
5. **Мониторьте бинарники рантайма через auditd.** Правила на `/usr/bin/runc`, `/usr/bin/containerd`, `/var/run/docker.sock` — см. [auditd: аудит контейнерной инфраструктуры](../../Linux/SystemAdministration/Logging/auditd.md#7-аудит-контейнерной-инфраструктуры-docker).
6. **Приоритизируйте по EPSS, а не только по CVSS.** CVE-2019-5736 (EPSS 0.98) эксплуатируется в реальности; CVE-2020-15257 (CVSS 5.2) — только в узких конфигурациях.
7. **Пересоздавайте контейнеры после апгрейда рантайма.** Запущенные контейнеры продолжают работать на старом shim/runc до пересоздания.
8. **Ограничьте access к BuildKit control API.** CVE-2026-75593 позволяет модифицировать файлы хоста через path traversal. Фаервол по IP / TLS на Unix-сокет или порт 1624-1625; доступ только CI/CD-воркерам.
9. **Не шарите кэш BuildKit между проектами с разным доверием.** CVE-2026-93318 (cache poisoning) может отравить shared cache и выполнить код в последующих сборках. Используйте `--no-cache` для недоверенных Dockerfile и `docker buildx prune --all --force` после подозрительных сборок.
10. **Валидируйте `# syntax=` в Dockerfile.** CVE-2026-61711/15792: кастомный frontend может отключить Seccomp/AppArmor или вызвать panic buildkitd. Используйте только встроенный `docker/dockerfile:1` или frontend'ы из доверенных реестров.
11. **Rootless Docker — стандарт для production.** Запуск демона и рантайма от непривилегированного пользователя снижает impact дефектов runc (CVE-2025-31133 и подобных), так как runc-процесс не может писать в `/proc/sysrq-trigger` и `/proc/sys/kernel/core_pattern`.

## Дополнительная информация

### Граничные случаи и ограничения

- **Docker и CVE-2025-31133:** Docker не эксплуатируем напрямую благодаря ro-маскировке верхнего слоя, но `docker buildx build` с shared mounts теоретически активирует race. Для максимальной защиты используйте rootless-контейнеры и `--mount=type=bind,bind-propagation=rprivate`.
- **CVE-2026-41579 и Docker:** Advisory June 2026 (runc ≤ 1.3.5) — symlink `/dev` → удаление/создание файлов на хосте. В Docker не эксплуатируем (ro-слой), но актуально для Podman/containerd без маскировки.
- **CVE-2020-15257 в Kubernetes:** Если Docker-хосты управляются через Kubernetes, CRI-O и containerd тоже используют shim — уязвимость затрагивает весь стек. Апгрейд containerd и пересоздание подов обязательны.
- **Dirty Pipe в контейнерах:** Ядро уязвимо, даже если контейнеры изолированы; требуется хост-патч. В PaaS-средах (OpenShift, EKS) патч ядра может откладываться — проверяйте retention vendor-анонсов.
- **BuildKit control API в Docker Desktop:** По умолчанию Docker Desktop не экспонирует control API наружу; в production только builder driver `docker-container` с Unix-сокетом и правами `0600`.
- **Совместное действие CVE:** CVE-2025-31133 + CVE-2026-61711 = LSM bypass + Seccomp отключён → максимальный impact. Патч обоих компонентов обязателен.

**Связанные документы:**

- **[Обзор безопасности Docker](./overview.md)** — ландшафт угроз и векторы атак.
- **[Укрепление контейнеров](./container_hardening.md)** — превентивная изоляция (capabilities, seccomp, LSM).
- **[Мониторинг в Runtime](./runtime_monitoring.md)** — Falco/Tetragon-детекция аномалий.
- **[Сканирование уязвимостей](./vulnerability_scanning.md)** — Trivy, EPSS, VEX.
- **[Детекция Dirty Pipe](../../Security/Tools/Wazuh/kernel_monitoring.md)** — правила Wazuh для CVE-2022-0847.
- **[traitor](../../Security/Tools/traitor.md)** — инструмент эскалации привилегий в Linux (PoC Dirty Pipe и др.).
- **[Альтернативные среды выполнения](../alternative_runtimes_and_tools.md)** — runc, crun, containerd, Sysbox.
- **[Buildx builder security](./buildx_builder_security.md)** — изоляция сборки, control API, cache poisoning.
- **[API DoS protection](./api_dos_protection.md)** — DoS-CVE Docker Engine и containerd (CVE-2026-32288, CVE-2026-47262 и др.).

**Внешние ресурсы:**

- [Docker Security Advisories](https://docs.docker.com/security/security-announcements) — официальные бюллетени.
- [GHSA-xr7r-f8xq-vfvv (CVE-2024-21626)](https://github.com/opencontainers/runc/security/advisories/GHSA-xr7r-f8xq-vfvv) — advisory runc.
- [GHSA-36xw-fx78-c5r4 (CVE-2020-15257)](https://github.com/containerd/containerd/security/advisories/GHSA-36xw-fx78-c5r4) — advisory containerd.
- [GHSA-cgrx-mc8f-2prm (CVE-2025-31133)](https://github.com/opencontainers/runc/security/advisories/GHSA-cgrx-mc8f-2prm) — advisory runc (procfs write redirects).
- [Snyk Labs: CVE-2024-21626](https://labs.snyk.io/resources/cve-2024-21626-runc-process-cwd-container-breakout) — разбор атак от первооткрывателя.

**Инструменты:** `trivy` (сканирование), `auditd` (детекция), `docker version` (проверка версий компонентов).
