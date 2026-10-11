# Docker Bench for Security: CIS Benchmark

**Актуально для:** CIS Docker Benchmark v1.6.0, Docker 24.x–29.x, Docker Bench for Security (docker/docker-bench-security)

## Предварительные требования

Перед выполнением практических сценариев убедитесь, что окружение готово:

- **Docker Engine** версии **1.13.0+** (Docker Bench требует минимум 1.13.0; актуален для 24.x–29.x). Проверка: `docker version --format '{{.Server.Version}}'` → `29.8.1`.
- **Права**: root или пользователь в группе `docker` (для host-режима); для контейнерного запуска — доступ к `/var/run/docker.sock`.
- **Утилиты**: `git` (клонирование репозитория), `jq` (парсинг JSON-лога). Опционально: `docker-compose` (для compose-запуска).
- **Доступ к файловой системе хоста**: скрипт читает `/etc`, `/var/lib`, `/usr/lib/systemd`, `/var/run/docker.sock` — при контейнерном запуске они монтируются в контейнер.

## Определения

- **Docker Bench for Security** — открытый скрипт от Docker, Inc., автоматически проверяющий десятки best-practices развёртывания Docker в production. Тесты основаны на **CIS Docker Benchmark** и полностью автоматизированы. Репозиторий: [docker/docker-bench-security](https://github.com/docker/docker-bench-security).
- **CIS Docker Benchmark** — отраслевой стандарт (Center for Internet Security), содержащий набор атомарных проверок конфигурации Docker. Версия 1.6.0 — актуальная на 2026 год. Организован по разделам (sections), каждый — группа родственных проверок.
- **Check (проверка)** — атомарный тест, именованный `check_<section>_<number>` (например, `check_2_6` — «Ensure the logging level is set to 'info'»). Community-вклады именуются `check_c_<name>`.
- **Результат проверки** — один из трёх исходов: **Pass** (соответствует), **Warning** (не соответствует, требует внимания), **Info** (информационно, не требует действий). Итоговый score — доля пройденных проверок.
- **Remediation** — рекомендация по исправлению, выводимая скриптом для каждой несоответствующей проверки (секция B вывода).
- **Host Configuration** — раздел 1 CIS Benchmark: параметры хоста (контейнеризация самого Docker, пользователь docker, сетевые настройки).
- **Container Runtime** — раздел 5 CIS Benchmark: параметры запуска контейнеров (привилегии, capabilities, read-only rootfs, resource limits).

## Основные концепции

### Структура CIS Docker Benchmark v1.6.0

Проверки организованы по разделам — от хоста к контейнеру:

| Раздел | Название | Что проверяет |
| :--- | :--- | :--- |
| **1** | Host Configuration | Контейнеризация Docker, пользователь `docker`, сетевая конфигурация хоста |
| **2** | Docker Daemon Configuration | Параметры демона (`dockerd`): logging level, TLS, `--userns-remap`, live-restore |
| **3** | Docker Daemon Configuration Files | Права на файлы конфигурации демона (`daemon.json`, `docker.service`, сокет) |
| **4** | Container Images and Build Files | Образы и Dockerfile: base images, content trust, обновления, HEALTHCHECK |
| **5** | Container Runtime | Запуск контейнеров: `--privileged`, capabilities, `--read-only`, PIDs limit, resource limits |
| **6** | Docker Security Operations | Операции безопасности: аудит, мониторинг, ротация логов |

**Практический смысл:** разделы 2–3 — hardening демона и хоста; раздел 4 — supply chain образов; раздел 5 — runtime hardening контейнеров. Для SRE/DevOps наиболее операционно значимы разделы 2 (daemon), 4 (образы) и 5 (runtime).

### Как работает скрипт

Скрипт (`docker-bench-security.sh`) загружает тесты из `tests/`, выполняет их последовательно и выводит три секции:

```text
Section A - Check results        # результаты каждой проверки (Pass/Warning/Info)
Section B - Remediation measures # рекомендации по исправлению Warning
Section C - Score                # итоговый score (Checks: N, Score: M)
```

Логи пишутся в `docker-bench-security.log` (текст) и `docker-bench-security.log.json` (машиночитаемый) в текущем каталоге (или `/usr/local/bin/log/` при контейнерном запуске).

### Интеграция с другими проверками

Docker Bench проверяет **конфигурацию** (host + daemon + runtime), но не сканирует образы на CVE. Для полной картины безопасности комбинируйте:

| Аспект | Инструмент | Файл в базе |
| :--- | :--- | :--- |
| Конфигурация (CIS) | **Docker Bench** | этот файл |
| CVE в образах | Trivy, Grype, Docker Scout | **[Сканирование уязвимостей](../Docker_security/vulnerability_scanning.md)** |
| Best-practices Dockerfile | Dockle, Hadolint | **[Безопасность в Dockerfile](../Dockerfile/Docker_best_practices/security.md)** |
| Подпись образов | Cosign, Notation | **[Подпись и верификация](../Docker_security/image_signature_and_verification.md)** |
| Kubernetes-кластер | kube-bench | **[kube-bench](../../Kubernetes/Security/kube-bench.md)** |

## Практические сценарии

### Сценарий 1: Запуск на хосте (рекомендуемый)

Прямой запуск скрипта — самый полный способ (проверяет host-конфигурацию).

```bash
# 1. Клонировать репозиторий
git clone https://github.com/docker/docker-bench-security.git
cd docker-bench-security

# 2. Запустить от root
sudo sh docker-bench-security.sh
# → Section A - Check results
# → [INFO] 1.1  - Ensure a separate partition for containers has been created
# → [WARN] 2.8  - Ensure user namespace support is enabled
# → [PASS] 2.11 - Ensure base device size is not changed until needed
# → ...
# → Section B - Remediation measures
# → Section C - Score
# → Checks: 263, Score: 187

# 3. Логи
ls -l docker-bench-security.log*
# → docker-bench-security.log        (текстовый)
# → docker-bench-security.log.json   (JSON)
```

**Валидация:** вывод содержит три секции; лог-файлы созданы в текущем каталоге. `Score` — доля Pass от общего числа проверок.

### Сценарий 2: Запуск в контейнере

Когда нет git/root на хосте, но есть доступ к Docker-сокету.

```bash
# Предсобранный образ с Docker Hub
docker run --rm --net host --pid host --userns host --cap-add audit_control \
    -e DOCKER_CONTENT_TRUST=$DOCKER_CONTENT_TRUST \
    -v /etc:/etc:ro \
    -v /usr/bin/containerd:/usr/bin/containerd:ro \
    -v /usr/bin/runc:/usr/bin/runc:ro \
    -v /usr/lib/systemd:/usr/lib/systemd:ro \
    -v /var/lib:/var/lib:ro \
    -v /var/run/docker.sock:/var/run/docker.sock:ro \
    --label docker_bench_security \
    docker/docker-bench-security
# → Section A - Check results
# → ...
```

**Валидация:** контейнер запускается с монтированием host-ФС (read-only) и Docker-сокета; вывод аналогичен host-режиму. Логи — внутри контейнера (`/usr/local/bin/log/`); для доступа с хоста смонтируйте `-v $(pwd)/logs:/usr/local/bin/log`.

> **Важно:** контейнерный запуск требует `--net host --pid host --userns host --cap-add audit_control` — скрипт проверяет host-конфигурацию, поэтому ему нужен доступ к host-пространствам имён. Это не production-контейнер, а разовая проверка.

### Сценарий 3: Запуск через Docker Compose

```bash
git clone https://github.com/docker/docker-bench-security.git
cd docker-bench-security
docker-compose run --rm docker-bench-security
# → Section A - Check results
# → ...
```

**Валидация:** compose-файл из репозитория содержит те же монтирования и флаги, что и сценарий 2.

### Сценарий 4: Выборочный запуск проверок

Для целевой диагностики — запуск только нужных разделов или конкретных проверок.

```bash
# Только раздел container_images (раздел 4)
sudo sh docker-bench-security.sh -c container_images
# → [PASS] 4.1 - Ensure a user for the container has been created
# → [WARN] 4.2 - Ensure that containers use trusted base images
# → ...

# Только конкретная проверка 2.2 (logging level)
sudo sh docker-bench-security.sh -c check_2_2
# → [PASS] 2.2 - Ensure the logging level is set to 'info'

# Все проверки кроме host_configuration и check_2_8
sudo sh docker-bench-security.sh -e host_configuration,check_2_8

# Разделы container_images и container_runtime, кроме 4.5
sudo sh docker-bench-security.sh -c container_images,container_runtime -e check_4_5
```

**Валидация:** `-c` принимает список разделов или `check_<id>`; `-e` исключает. Комбинируются через запятую.

### Сценарий 5: Интерпретация JSON-лога в CI

Машиночитаемый лог для автоматизации и отслеживания динамики.

```bash
# Запуск с JSON-логом
sudo sh docker-bench-security.sh -l /tmp/bench.log

# Парсинг: только Warning-проверки
jq -r '.tests[] | select(.result == "WARN") | "\(.id) \(.desc)"' docker-bench-security.log.json
# → check_2_8 Ensure user namespace support is enabled
# → check_5_1 Ensure that, if applicable, an AppArmor Profile is enabled
# → ...

# Итоговый score
jq -r '"Checks: \(.total_checks), Pass: \(.score), Score: \(.score * 100 / .total_checks | floor)%"' docker-bench-security.log.json
# → Checks: 263, Pass: 187, Score: 71%
```

**Валидация:** JSON содержит массив `tests` с полями `id`, `desc`, `result` (`PASS`/`WARN`/`INFO`); score вычисляется как доля Pass.

### Сценарий 6: Типичные находки и remediation

Наиболее частые Warning на production-хостах и как их исправлять.

| Check | Симптом | Remediation |
| :--- | :--- | :--- |
| `2.8` userns-remap | `[WARN] Ensure user namespace support is enabled` | Включить `"userns-remap": "default"` в `daemon.json` (см. **[Защиту хоста и демона](../Docker_security/host_daemon_hardening.md)**). Внимание: несовместим с containerd image store (moby#47377) |
| `2.11` base device size | `[WARN] Ensure base device size is not changed` | Не менять `dm.basesize` без необходимости; использовать overlay2 |
| `4.2` trusted base images | `[WARN] Ensure containers use trusted base images` | Использовать official images или подписанные образы; пинить по дайджесту |
| `4.5` content trust | `[WARN] Ensure Content trust for Docker is Enabled` | **DCT (Notary v1) устарел** — мигрировать на Cosign/Notation (см. **[Подпись и верификацию](../Docker_security/image_signature_and_verification.md)**) |
| `5.1` AppArmor | `[WARN] Ensure AppArmor Profile is enabled` | Задать `apparmor=...` профиль или использовать default |
| `5.3` privileged | `[WARN] Ensure privileged containers are not used` | Не использовать `--privileged`; применять `--cap-add` точечно |
| `5.12` read-only rootfs | `[WARN] Ensure root file system is read only` | Запускать с `--read-only` + `--tmpfs` для временных путей |
| `5.28` PIDs limit | `[WARN] Ensure PIDs cgroup limit is used` | Задать `--pids-limit` (например, `--pids-limit=100`) |

**Валидация:** после remediation повторный запуск показывает `PASS` вместо `WARN` для исправленных проверок.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `docker-bench-security.sh: Permission denied` | Скрипт не исполняемый | `sudo sh docker-bench-security.sh` (через `sh`, не `./`) |
| Пустой вывод / нет проверок | Нет прав на чтение host-ФС | Запуск от root (`sudo`); при контейнерном — проверьте монтирования `/etc`, `/var/lib` |
| `Cannot connect to the Docker daemon` | Нет доступа к сокету | `-v /var/run/docker.sock:/var/run/docker.sock:ro` или пользователь в группе `docker` |
| Много `[INFO]` без `[WARN]` | Проверки не применимы к ОС | Норма: INFO — информационные проверки; фокус на WARN |
| `check_4_5` всегда WARN | DCT (Notary v1) устарел | Ожидаемо: DCT deprecated 2025; используйте Cosign — check 4.5 неактуален для современных пайплайнов |
| Логи не видны на хосте | Контейнерный запуск без монтирования логов | Добавьте `-v $(pwd)/logs:/usr/local/bin/log` |
| `userns-remap` конфликтует с containerd store | moby#47377 | Выберите: либо userns-remap (classic overlay2), либо containerd image store; не оба одновременно |
| Разный score на разных хостах | Разные ОС/версии Docker | Норма: проверки зависят от ОС (systemd vs SysV) и версии; сравнивайте с baseline той же ОС |

## Рекомендации и очистка

**Лучшие практики:**
- Запускайте Docker Bench регулярно (ежемесячно или при изменении конфигурации) и отслеживайте динамику score — регресс score сигнализирует о дрейфе конфигурации.
- В CI запускайте выборочно (`-c container_images,container_runtime`) — это быстрее полного прогона и покрывает наиболее операционно значимые разделы.
- Комбинируйте с Trivy (CVE) и Dockle (Dockerfile best-practices) — Docker Bench проверяет конфигурацию, но не содержимое образов.
- Для Kubernetes-нод используйте kube-bench (CIS Kubernetes Benchmark) параллельно — Docker Bench проверяет Docker, kube-bench — кластер.
- Не гонитесь за 100% score: некоторые проверки (например, `2.8` userns-remap) конфликтуют с другими возможностями (containerd image store). Оценивайте каждый Warning по контексту.
- Храните JSON-лог в системе мониторинга/ITSM для аудита compliance (PCI-DSS, SOC 2).

**Очистка окружения:**
```bash
# Удалить клонированный репозиторий и логи
cd .. && rm -rf docker-bench-security
# Удалить образ (если запускали из Docker Hub)
docker rmi docker/docker-bench-security
# → Untagged: docker/docker-bench-security:latest
# → Deleted: sha256:...
```

## Особые случаи и ограничения

- **DCT (check 4.5) устарел**: Docker Content Trust (Notary v1) выведен из эксплуатации (архивация Notary — 30.07.2025). Check 4.5 будет WARN даже при корректной настройке Cosign — это ожидаемо и не является дефектом. Мигрируйте на Cosign/Notation.
- **userns-remap vs containerd image store**: несовместимы (moby#47377). На Docker 29+ с containerd image store по умолчанию check 2.8 будет WARN — это архитектурное ограничение, не ошибка конфигурации.
- **ОС-специфичность**: проверки разделов 1–3 зависят от ОС (systemd, auditd, пакетный менеджер). На Alpine/BusyBox-хостах часть проверок неприменима (INFO).
- **Контейнерный запуск не полон**: скрипт в контейнере проверяет host через монтирования, но некоторые проверки (например, требующие `audit_control` или host-PID) могут давать ложно-отрицательные результаты. Для аудита предпочтителен host-режим.
- **Не сканирует CVE**: Docker Bench проверяет конфигурацию, а не содержимое образов. Для CVE — Trivy/Grype.
- **Windows-контейнеры**: CIS Docker Benchmark ориентирован на Linux-хосты; для Windows-нод используйте CIS Windows Benchmark.
- **Версия Benchmark**: скрипт соответствует CIS Docker Benchmark v1.6.0. Более новые версии Benchmark требуют обновления скрипта из upstream-репозитория.

## Примечания по версиям

- **CIS Docker Benchmark v1.6.0**: актуальная версия, на которой основан скрипт. Проверки именуются `check_<section>_<number>`.
- **Docker Bench for Security**: требует Docker 1.13.0+; актуален для Docker 24.x–29.x. Образ — `docker/docker-bench-security` на Docker Hub.
- **Docker Content Trust**: deprecated (Notary v1 архивирован 30.07.2025). Check 4.5 неактуален — используйте Cosign/Notation с OCI 1.1 Referrers.
- **containerd image store (Docker 29.0+)**: дефолт для новых установок; несовместим с userns-remap (check 2.8 будет WARN).

## Дополнительная информация

- **Репозиторий**: [docker/docker-bench-security](https://github.com/docker/docker-bench-security) — полный список проверок в `tests/`, опции в `usage()`.
- **CIS Docker Benchmark**: [CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks/) — официальный стандарт (требуется регистрация для PDF).
- **Hardening демона и хоста** — **[Защита хоста и демона](../Docker_security/host_daemon_hardening.md)**.
- **Hardening контейнеров** (runtime, capabilities, read-only rootfs) — **[Укрепление безопасности контейнеров](../Docker_security/container_hardening.md)**.
- **Сканирование CVE** — **[Сканирование уязвимостей](../Docker_security/vulnerability_scanning.md)**.
- **Подпись образов (Cosign/Notation)** — **[Подпись и верификация](../Docker_security/image_signature_and_verification.md)**.
- **kube-bench** (CIS Kubernetes Benchmark) — **[kube-bench](../../Kubernetes/Security/kube-bench.md)**.

### См. также

- **[Обзор безопасности Docker](../Docker_security/overview.md)** — ландшафт безопасности Docker.
- **[Безопасность в Dockerfile](../Dockerfile/Docker_best_practices/security.md)** — best-practices сборки (Dockle, Hadolint).
- **[Lynis](../../Security/Tools/lynis.md)** — общий аудит хоста (сравнение с Docker Bench).
