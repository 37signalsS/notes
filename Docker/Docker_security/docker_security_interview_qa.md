# Docker Security: Вопросы на собеседованиях

**Актуально для:** Docker Engine 29.x, runc 1.2.x, containerd 1.7.x/2.x, BuildKit 0.13+. Ответы верифицированы по документации Docker и содержимому базы знаний; теория и практика — в смежных файлах (ссылки в конце).

## Определения

**Задачи этого файла** — краткие, точные ответы на типичные вопросы DevOps/SRE-собеседований по безопасности Docker: изоляция контейнеров, образы и сборка, сеть, секреты, мониторинг, инциденты. Файл не заменяет теорию: механизмы (namespaces, cgroups, LSM) и пошаговые практики — в смежных файлах базы знаний.

## Изоляция и рантайм

**Q: Что такое container escape? Приведите примеры CVE.**
A: Побег из контейнера — эксплуатация дефекта в рантайме, ядре или инструментах Docker, позволяющая процессу внутри контейнера выполнить код или получить доступ к ФС хоста. Ключевые примеры:
- **CVE-2019-5736** (runc ≤ 1.0-rc6, Docker < 18.09.2): перезапись хостового бинарника runc через `/proc/self/exe`; код на хосте при следующем `docker exec`. CVSS 8.6, EPSS ≈ 0.98.
- **CVE-2024-21626** (Leaky Vessels, runc ≤ 1.1.11): утечка fd хостового `/sys/fs/cgroup`; `process.cwd = /proc/self/fd/7/` даёт PID 1 рабочую директорию в хостовом mount namespace. CVSS 8.6; исправлен в runc 1.1.12, Docker ≥ 25.0.2 / ≥ 24.0.9.
- **CVE-2019-14271** (Docker 19.03.0): инъекция кода через glibc `nsswitch` при `docker cp`; CVSS 9.8.
- **CVE-2020-15257** (containerd < 1.3.9, 1.4.0–1.4.2): API-сокет shim'а доступен контейнерам в host-сети с UID 0.
- **CVE-2022-0847** (Dirty Pipe, ядро 5.8–5.16.10): перезапись read-only файлов через `splice()`.
Полный каталог — в [container_escape_cves.md](./container_escape_cves.md).

**Q: Чем опасен `--privileged`?**
A: Контейнер получает **все** capabilities хоста, доступ ко всем устройствам (`--device` без ограничений) и снимает ограничения LSM (AppArmor/SELinux). Фактически это эквивалент root на хосте: монтирование `/dev/sda`, загрузка модулей ядра, изменение sysctl. Никогда не используйте для недоверенных образов; если нужны конкретные привилегии — выдавайте точечно: `--cap-add=NET_ADMIN`, `--device=/dev/fuse`.

**Q: Как минимизировать привилегии контейнера?**
A:
```bash
docker run --security-opt=no-new-privileges \
  --cap-drop=ALL --cap-add=NET_BIND_SERVICE \
  --read-only --tmpfs /tmp:rw,noexec,nosuid \
  --security-opt apparmor=my-profile \
  --user 10001:10001 nginx
```
`--cap-drop=ALL` убирает все Linux capabilities; `--security-opt=no-new-privileges` запрещает setuid/sudo внутри контейнера; `--read-only` делает ФС неизменяемой. Важно: эти меры ограничивают **контейнер**, но не защищают от дефектов **рантайма** (runc/containerd) — патчинг рантайма независимая мера.

**Q: Что такое seccomp и как запретить syscall?**
A: Seccomp (secure computing mode) — фильтр системных вызовов ядра. Docker по умолчанию блокирует ~44 опасных syscall'а (mount, kexec, ptrace и др.). Свой профиль:
```bash
docker run --security-opt seccomp=custom.json nginx
```
JSON-профиль: `{"defaultAction":"SCMP_ACT_ERRNO","syscalls":[{"names":["reboot"],"action":"SCMP_ACT_ALLOW"}]}`. Отладка: `strace` для списка нужных syscall'ов, `audit2seccomp` для генерации из auditd-логов. Теория и ручные профили — в [Seccomp](../../Linux/Security/Mechanisms/Seccomp.md).

**Q: AppArmor или SELinux — что выбрать?**
A: AppArmor (Ubuntu/Debian/SUSE) — path-based профили, проще в написании; Docker назначает профиль `docker-default` автоматически, свой — через `--security-opt apparmor=my-profile`. SELinux (RHEL/Fedora) — label-based (MAC), сильнее, но сложнее; контейнеры получают тип `container_t`. Для Docker в production на RHEL — SELinux enforcing; на Ubuntu — AppArmor. Оба — LSM и работают поверх capabilities.

**Q: Что такое rootless Docker и что он НЕ защищает?**
A: Демон и контейнеры работают от непривилегированного пользователя через user namespace (UID-mapping: root в контейнере = обычный UID на хосте). Побег из контейнера не даёт root на хосте. НЕ защищает: от уязвимостей в самом Docker (CVE рантайма), от атак на пользовательские namespace, от проблем с ресурсами (cgroup v2 delegation). Настройка — в [host_daemon_hardening.md](./host_daemon_hardening.md).

## Образы и сборка

**Q: Как проверить образ на уязвимости?**
A:
```bash
trivy image --severity CRITICAL,HIGH --ignore-unfixed my-app:latest
# → library/nginx (debian 12.5): CVE-2024-XXXX CRITICAL ...
```
Принципы: сканировать в CI (fail build на CRITICAL), использовать `--ignore-unfixed` для фокуса на исправленных, проверять базовые образы, пинить по digest (`nginx@sha256:...`), а не по тегу. Подробно — в [vulnerability_scanning.md](./vulnerability_scanning.md).

**Q: Почему тег образа ненадёжен, а digest надёжен?**
A: Тег — изменяемая ссылка: `nginx:latest` может указывать на разный контент в разное время (supply-chain атака, перепубликация). Digest (`@sha256:...`) — криптографический хеш манифеста: неизменяем. Для production: `docker pull my-app@sha256:abc123...`. Immutable tags и политики — в [image_versioning_and_tagging.md](../Docker_registries/image_versioning_and_tagging.md).

**Q: Чем опасна сборка недоверенного Dockerfile?**
A: BuildKit выполняет инструкции сборки с правами демона сборки. CVE-2024-23651/23652/23653 (BuildKit ≤ 0.12.4): race condition на cache-mount'ах, удаление файлов хоста через `RUN --mount`, эскалация через зловредный frontend. CVE-2026-61711 (CVSS 5.3, BuildKit ≤ 0.31.0): кастомный frontend отключает Seccomp/AppArmor. CVE-2026-15792 (BuildKit < 0.31.2): panic buildkitd через зловредный client/frontend. CVE-2026-61712 (CVSS 2.3, BuildKit ≤ 0.31.0): OOM buildkitd через unbounded group parsing. CVE-2026-75593 (CVSS 6.5, BuildKit < 0.31.2): path traversal через control API upload. CVE-2026-93318 (CVSS 7.5 High, BuildKit < 0.33.1): cache poisoning через подмену DiffIDs. Правила: не собирать недоверенные Dockerfile; не использовать `--mount=type=cache,source=...` из чужих репозиториев; не подключать сторонние `--frontend`; патч BuildKit ≥ 0.33.1; `--network=none` на этапе сборки.

**Q: Что такое SBOM и зачем он?**
A: Software Bill of Materials — перечень компонентов образа (пакеты, зависимости). Нужен для: быстрого ответа «затронут ли нас CVE» без повторного сканирования, compliance (PCI DSS, EU CRA), отслеживания supply chain. Генерация: `syft my-app:latest -o spdx-json > sbom.json`; подпись — cosign. Подробно — в [docker_sbom.md](./docker_sbom.md).

## Сеть

**Q: Как изолировать контейнеры друг от друга?**
A: По умолчанию контейнеры в bridge-сети общаются свободно (ICC=true). Запрет:
```bash
# Глобально (daemon.json)
{"icc": false}
# Или правилом в цепочке DOCKER-USER (применяется ко всем сетям)
iptables -I DOCKER-USER -i docker0 -o docker0 -j DROP
```
Сегментация: отдельные bridge-сети (`docker network create --internal app-net`), `--internal` блокирует egress. Полная теория — в [docker_network_policies.md](../Docker_network/docker_network_policies.md) и [network_security.md](./network_security.md).

**Q: Как ограничить исходящий трафик контейнера?**
A: Docker не имеет встроенного egress-файрвола. Варианты: (1) `--internal` сеть без шлюза; (2) iptables в DOCKER-USER по образу/метке; (3) HTTP-прокси (Squid) с whitelist доменов; (4) Cilium/Tetragon для L7-политик. Пошаговые конфиги — в [docker_network_egress.md](../Docker_network/docker_network_egress.md).

**Q: Что такое CVE-2024-29018?**
A: Docker DNS-forwarder пересылал запросы на внешние DNS-серверы для контейнера, подключённого **только** к `--internal` сети, если DNS хоста слушал на loopback (например, systemd `127.0.0.53`) — эксфильтрация данных из «изолированной» сети. Исправлен в Docker ≥ 25.0.5. Вывод: `--internal` не гарантирует отсутствие исходящего трафика без патча.

## Секреты и конфигурация

**Q: Почему нельзя передавать секреты через ENV?**
A: Переменные окружения видны: в `docker inspect`, в `/proc/<pid>/environ` (для процессов с правами на хосте), в логах, в `docker exec`-сессиях, наследуются дочерними процессами. Альтернативы: файлы (`--env-file` с правами 600), Docker secrets (Swarm: `/run/secrets/` в tmpfs), внешние менеджеры (Vault, SOPS) с монтированием в runtime. Сравнение и практики — в [secrets_management.md](./secrets_management.md).

**Q: Как защитить Docker socket?**
A: `/var/run/docker.sock` = root-эквивалент на хосте. Правила:
1. Никогда не монтировать в контейнер (`-v /var/run/docker.sock:/var/run/docker.sock` — полный побег).
2. Для инструментов (Portainer, CI) — [docker-socket-proxy](../Docker_compose/docker_compose_security.md) с whitelist эндпоинтов.
3. Права: `root:docker 660`, минимальный состав группы `docker`.
4. Опционально: TLS-mutual auth на TCP-сокете, authorization-плагины.

**Q: Что такое authorization-плагин Docker?**
A: Механизм, позволяющий внешнему сервису разрешать или запрещать вызовы Docker API (например, запретить `docker run --privileged` для обычных пользователей). Реализуется как HTTP-мидлвейр (`--authorization-plugin=myplugin`), работает только для HTTP API (не gRPC), fail-closed при недоступности. Плагины не deprecated, но имели bypass-CVE (CVE-2024-41110, fixed 27.1.1; CVE-2026-34040, fixed 29.3.1) — держите Engine актуальным. Теория — в [api_authorization.md](./api_authorization.md).

## Мониторинг и инциденты

**Q: Как мониторить контейнеры в runtime?**
A: eBPF-агенты, отслеживающие syscall'и и сетевые события:
- **Falco** — правила вида «shell в контейнере», «запись в /etc», «монтирование ФС хоста».
- **Tetragon** (Cilium) — eBPF-политики с автоматическим kill процесса.
- **auditd** — правила на `/usr/bin/runc`, `/var/run/docker.sock`.
Пример правила Falco и интеграция — в [runtime_monitoring.md](./runtime_monitoring.md).

**Q: Контейнер сбежал (подозрение). Что делать первым?**
A: Порядок (полный runbook — в [incident_response.md](./incident_response.md)):
1. **Изолировать**: `docker pause <c>` (не `stop` — сохраняет состояние для форензики), отключить сеть.
2. **Зафиксировать**: `docker inspect <c>`, дамп памяти, логи (`journalctl -u docker`), снапшот ФС.
3. **Определить масштаб**: какие ещё контейнеры на хосте, версии runc/containerd (`docker version`), проверка по CVE-каталогу.
4. **Содержать**: пересоздать контейнеры после апгрейда рантайма (старый shim/runc остаётся у запущенных контейнеров).
5. **Восстановить**: ротация всех секретов, видимых скомпрометированному контейнеру.

**Q: Что такое Docker Bench CIS?**
A: Скрипт, проверяющий конфигурацию хоста и демона против CIS Docker Benchmark (~200 проверок: права на сокет, AppArmor, ICC, логирование). Запуск:
```bash
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -e DOCKER_CONTENT_TRUST=1 -v /var/lib:/var/lib -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/lib/systemd:/usr/lib/systemd -v /etc:/etc --label docker_bench_security \
  docker/docker-bench-security
```
Подробно — в [docker_bench_cis.md](./docker_bench_cis.md).

**Q: Как контейнеры вписываются в PCI DSS / compliance?**
A: PCI DSS v4.0.1 требует: сканирование образов (req. 6), минимальные привилегии (req. 2/7), сегментацию сети (req. 1), логирование (req. 10), управление секретами (req. 3). Контейнеры не создают исключений — каждый контейнер в CDE (Cardholder Data Environment) — отдельный объект аудита. Карта контроля — в [compliance_frameworks.md](./compliance_frameworks.md).

## Защита API и DoS

**Q: Есть ли встроенный rate limiting в Docker Engine API?**
A: Нет. `dockerd` не имеет настроек rate limiting для API — документация рекомендует защищать демон либо встроенным HTTPS-сокетом, либо безопасным веб-прокси перед ним. Rate limiting реализуется на nginx перед TCP API (`limit_req_zone`/`limit_req`/`limit_conn`) плюс firewall по IP. Docker Hub rate limits (100 pulls/6h) — ограничение **реестра**, не демона. Подробно — в [api_dos_protection.md](./api_dos_protection.md).

**Q: Как защитить dockerd от DoS?**
A: Слои: (1) TCP API не экспонировать — только Unix-сокет или SSH (`DOCKER_HOST=ssh://`); (2) если TCP нужен — firewall по IP + nginx rate limiting; (3) mTLS на 2376; (4) AuthZ-плагин с политикой, требующей лимитов ресурсов; (5) cgroups-лимиты на контейнеры; (6) патчить containerd — DoS-CVE (образы: CVE-2026-47262, CVE-2026-53493; CRI: CVE-2025-64329, CVE-2025-47291, CVE-2026-53495); (7) патчить Docker Engine — DoS-CVE (CVE-2026-32288, CVE-2026-93323).

**Q: Что такое CVE-2026-47262?**
A: DoS-уязвимость в containerd (GHSA-jpcc-p29g-p8mq, CWE-400, CVSS 5.5 MEDIUM; GHSA 2026-06, NVD 2026-07-01): зловредный образ (unbounded group parsing) вызывает неограниченное потребление памяти при создании контейнера; OOM-killer завершает процесс containerd, ломая рантайм на всём узле (Docker Engine и kubelet CRI). Исправлена в containerd 1.7.33, 2.0.10, 2.1.9, 2.2.5, 2.3.2. Митигация: обновить containerd, сканировать образы перед pull, не тянуть образы из недоверенных реестров. Серия CRI-DoS: CVE-2025-64329 (1.7.29+/2.0.7+/2.1.5+/2.2.1+), CVE-2025-47291 (2.0.5+/2.1.0+), CVE-2026-53495 (1.7.35/2.0.12/2.2.8/2.3.5). Дополнительные DoS-CVE Docker Engine 29.x: CVE-2026-32288 (sparse tar → OOM), CVE-2026-93323 (oversized Dockerfile/.dockerignore/LLB → OOM), CVE-2026-53493 (deeply nested OCI index → unbounded CPU/memory при pull).

## Соответствие, метрики и SLO

**Q: Что такое FIPS 140-2 и как он связан с Docker?**
A: FIPS 140-2 — стандарт NIST для криптомодулей. Docker Engine CE **не имеет** FIPS-валидированного криптомодуля; валидированный модуль (Certificate #3304, FIPS 140-2 Level 1) есть только в Mirantis Container Runtime (ex Docker Engine Enterprise): покрывает TLS сокета демона, Swarm mTLS, Swarm Raft log (Secrets/Configs), control plane overlay-сетей, ID hashes. Активация: FIPS mode на хосте (`fips=1`, проверка `cat /proc/sys/crypto/fips_enabled` → `1`) + `DOCKER_FIPS=1`. MKE и MSR FIPS не поддерживают. Для CE — альтернативы: FIPS-enabled хост, UBI base images, Go boringcrypto. Подробно — в [fips_compliance.md](./fips_compliance.md).

**Q: Какие метрики безопасности Docker отслеживать?**
A: Образы: % просканированных / подписанных / pinned by digest / non-root, число EOL-образов. Конфигурация: CIS Docker Benchmark score (цель ≥ 90%), % read-only FS, % cap-drop=ALL, число привилегированных контейнеров. Рантайм: drift rate, события `docker exec`. Инциденты: MTTR по severity. Источники: `docker inspect`, `trivy`, `cosign verify`, `docker-bench-security` → Prometheus. Стек мониторинга — SSoT в [devsecops_monitoring.md](../../CI-CD/DevSecOps/devsecops_monitoring.md); Docker-метрики — в [security_metrics.md](./security_metrics.md).

**Q: Какой SLO по MTTR для Critical CVE?**
A: MTTR Critical < 24 ч, High < 7 дней — согласовано с практикой security-scanning в базе знаний. Время фиксируется от обнаружения (сканер/SIEM) до устранения (пересборка + деплой); recurring инциденты — отдельная метрика.

## Свежесть образов

**Q: Как обнаружить EOL ОС в образе?**
A: `trivy image --exit-code 1 --exit-on-eol 1 --severity CRITICAL <image>` — fail сборки на EOL-ОС (`ERROR Detected EOL OS: ...`). Критично: без `--exit-on-eol` Trivy может показать 0 CVE на EOL-ОС (пакеты удалены из базы) — ложное «чисто». Дополнительно: `eol-scanner` (данные endoflife.date), GitLab `CS_REPORT_OS_EOL`. Политика — в [image_freshness_policy.md](./image_freshness_policy.md).

**Q: Как автоматизировать обновление базовых образов?**
A: Renovate: `dockerfile` manager (обновляет `FROM`, `COPY --from`, `RUN --mount`, `syntax`) + пресет `docker:pinDigests` + `packageRules` с automerge для `updateTypes: ["patch", "digest"]`. Dependabot: `package-ecosystem: dockerfile` (теги, без автоматического digest-пининга). Podman: `podman auto-update` с label `io.containers.autoupdate`.

## Multi-tenancy

**Q: Как изолировать tenants в Docker без Kubernetes?**
A: Уровни изоляции (от слабого к сильному): (1) сетевая сегментация — отдельные bridge-сети, `icc=false`, правила DOCKER-USER; (2) resource limits — `--memory`, `--cpus`, `--pids-limit` (защита от noisy neighbor); (3) `userns-remap`; (4) отдельный rootless-демон на tenant — сильная изоляция; (5) gVisor (`runsc`) для недоверенных tenants. В Kubernetes — namespaces/NetworkPolicy/RBAC (см. [multi-tenancy.md](../../Kubernetes/Concepts/multi-tenancy.md)). Подробно — в [multi_tenancy_security.md](./multi_tenancy_security.md).

**Q: Что такое noisy neighbor и как его предотвратить?**
A: Tenant, чья нагрузка или компрометация исчерпывает общие ресурсы хоста (RAM, CPU, PIDs, диск). Предотвращение: жёсткие cgroups v2-лимиты на каждый контейнер, мониторинг `docker stats`, отдельные демоны на tenants. Docker не имеет встроенного лимита network bandwidth — через `tc`/iptables.

## Сборка и builders

**Q: Чем опасен shared Buildx builder?**
A: Builder — граница доверия: недоверенный Dockerfile на shared builder может отравить кэш (cache poisoning) и использовать entitlements доверенных сборок. Правило: отдельный builder per trust boundary (`docker buildx create --driver docker-container`), отдельный registry-кэш, `--no-cache` для недоверенных Dockerfile. Патч BuildKit ≥ 0.33.1 (CVE-2024-23651/23652/23653, CVE-2026-61711/15792/61712/75593/93318). Подробно — в [buildx_builder_security.md](./buildx_builder_security.md).

**Q: Почему секреты нельзя передавать через `--build-arg`?**
A: Значения build args видны в `docker history`, слоях образа и provenance-аттестации `mode=max`. Альтернатива: `--secret id=...,src=...` + `RUN --mount=type=secret` — секрет не попадает в слои и аттестации. SSH-ключи — `--ssh default`.

**Q: Что такое provenance в buildx?**
A: SLSA-аттестация происхождения образа (кто, чем и из каких материалов собрал). `mode=min` генерируется **по умолчанию** — но только для образов, push-имых в реестр (`--push`); не содержит значений build args. `mode=max` — полная информация, но включает значения build args (не передавайте секреты через args). Проверка: `docker buildx imagetools inspect <image> --format '{{ json .Provenance.SLSA }}'`. Отключение: `--provenance=false` или `BUILDX_NO_DEFAULT_ATTESTATIONS=1`.

## Дополнительная информация

**Связанные документы:**

- [Обзор безопасности Docker](./overview.md) — ландшафт угроз и векторы атак.
- [CVE побегов из контейнеров](./container_escape_cves.md) — каталог уязвимостей.
- [Укрепление контейнеров](./container_hardening.md), [хоста и демона](./host_daemon_hardening.md).
- [Сетевая безопасность](./network_security.md), [политики](../Docker_network/docker_network_policies.md).
- [Авторизация Docker API](./api_authorization.md), [безопасность реестров](./registry_security.md).
- [Реагирование на инциденты](./incident_response.md), [compliance](./compliance_frameworks.md).
- [Docker Networking: вопросы на собеседованиях](../Docker_network/docker_network_interview_qa.md) — сетевая специфика.
- [Защита Docker API от DoS](./api_dos_protection.md) — rate limiting, containerd DoS-CVE.
- [Метрики безопасности и SLO](./security_metrics.md) — Docker-метрики, MTTR.
- [Политика свежести образов](./image_freshness_policy.md) — EOL, автообновление.
- [FIPS 140-2](./fips_compliance.md) — MCR, FIPS mode.
- [Multi-tenancy](./multi_tenancy_security.md) — изоляция tenants.
- [Безопасность Buildx builders](./buildx_builder_security.md) — builders, cache, secrets, provenance.
