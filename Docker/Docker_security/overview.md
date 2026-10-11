# Обзор безопасности Docker

**Актуально для:** Docker Engine 29.x (актуальный релиз — 29.8.x, сентябрь 2026). Docker Engine 28.x и ранее достигли EOL (май 2026) и не получают исправлений безопасности.

Демон Docker (`dockerd`) по умолчанию работает от `root`. Любой процесс с доступом к Docker API получает полный `root`-доступ к хосту. Данный документ описывает основные векторы угроз и служит отправной точкой для изучения безопасности в экосистеме Docker.

## Предварительные требования

- **ОС:** Linux с ядром 5.4+ (требуется для Cgroups v2, User Namespaces и eBPF). RHEL/CentOS 8+, Debian 11+, Ubuntu 20.04+.
- **Docker Engine:** 29.x (актуальный релиз 29.8.x на сентябрь 2026). Docker 28.x и ранее достигли EOL.
- **Права:** Для управления демоном требуются права `root` или membership в группе `docker`. В production-средах предпочтителен Rootless Docker.
- **Сетевые возможности:** Доступ к портам 2376 (mTLS) или 22 (SSH) для удаленного управления. Порт 2375 (TCP без TLS) категорически запрещен.
- **Инструменты:** `auditd` для аудитa, `jq` для парсинга JSON-вывода Docker, `trivy` или `grype` для сканирования образов.

## Определения

**Поверхность атаки (Attack Surface)** — совокупность точек входа, через которые злоумышленник может скомпрометировать Docker-инфраструктуру (демон, образы, контейнеры, реестры).

**Группа `docker`** — системная группа, пользователи которой могут выполнять команды `docker` без `sudo`. Предоставляет неконтролируемый доступ к Docker API, что эквивалентно правам `root` на хосте.

**Docker Socket (`/var/run/docker.sock`)** — **[Unix-сокет](../../Networking/Concepts/socket_api.md#семейства-адресов-и-типы-сокетов)** для локального взаимодействия с демоном `dockerd`.

**Software Bill of Materials (SBOM)** — полный перечень всех компонентов, библиотек и зависимостей, входящих в состав Docker-образа. Необходим для анализа цепочки поставок.

**Энстайтлменты (Entitlements)** — механизм управления привилегиями, позволяющий гранулярно ограничивать доступ к функциям ядра (например, доступ к сети или файловой системе) даже для привилегированных контейнеров.

## Базовые концепции

Безопасность Docker базируется на модели нулевого доверия (Zero Trust) и максимальной изоляции компонентов.

### 1. Безопасность демона и хоста

Ошибки конфигурации демона могут привести к полной компрометации сервера. Приоритетом остается защита управляющего интерфейса:

- **Изоляция сокета:** Минимизация проброса `/var/run/docker.sock` в контейнеры.
- **Rootless mode:** Запуск демона и контейнеров от имени обычного пользователя — стандарт де-факто для production-сред.
- **Безопасный доступ к API:** Отказ от TCP/2375. Использование mTLS (порт 2376) или прямого подключения через SSH (`DOCKER_HOST=ssh://user@host`).

### 2. Безопасность внутри контейнера

Контейнеры используют общее ядро хоста, что требует многоуровневой изоляции:

- **Механизмы ядра (LSM):** Использование профилей AppArmor и SELinux для ограничения действий процессов.
- **Capabilities и Seccomp:** Блокировка потенциально опасных системных вызовов (например, `mount`, `ptrace`).
- **User Namespaces:** Изоляция UID/GID, предотвращающая получение прав root на хосте при взломе контейнера.
- **Resource Limits:** Ограничение CPU и RAM (`--memory`, `--cpus`) для предотвращения DoS-атак со стороны скомпрометированных контейнеров.

### 3. Сетевая безопасность

Начиная с Docker Engine 29, сетевая модель стала более закрытой по умолчанию:

- **Secure by Default (v29+):** В bridge-сетях входящий трафик из локальной сети (LAN) к IP-адресам контейнеров блокируется, если порты не опубликованы явно через `-p`.
- **Межконтейнерное взаимодействие (ICC):** Отключение связи между контейнерами в одной сети (`--icc=false`) для реализации сегментации.
- **Шифрование трафика:** Использование Overlay-сетей с IPSec (`--opt encrypted`) в средах Swarm для защиты данных в движении.

### 4. Безопасность образов и цепочки поставок (Supply Chain)

Современный подход требует перехода к модели Zero-CVE:

- **Минимизация образов:** Использование Distroless или Chainguard образов без пакетных менеджеров и shell.
- **Фиксация по дайджестам:** Использование `image@sha256:...` вместо тегов для гарантии неизменности образа.
- **Подписи и аттестации:** Обязательная проверка подписей через Cosign или Docker Content Trust перед запуском.
- **Анализ SBOM:** Интеграция генерации и проверки состава ПО в CI/CD пайплайны.

### 5. Аудит и мониторинг

Безопасность требует прозрачности действий системы:

- **События Docker:** Мониторинг через `docker events` для отслеживания жизненного цикла контейнеров и изменений конфигурации.
- **Аудит системных вызовов:** Использование `auditd` для контроля доступа к критическим файлам Docker.
- **Runtime Security:** Применение инструментов на базе eBPF (Falco, Tetragon) для обнаружения аномального поведения (например, запуск shell в контейнере базы данных).

### 6. Безопасность типовых workloads

Безопасность конкретных workload-типов (БД, брокеры, веб-серверы, CI-раннеры) документирована в доменных директориях базы знаний — каждый workload имеет свой SSoT-файл. Docker-специфичные механизмы (non-root, read-only FS, capabilities, лимиты) — в [Укрепление контейнеров](./container_hardening.md):

| Workload | SSoT по безопасности |
| :--- | :--- |
| PostgreSQL | [Databases/PostgreSQL/Operations/docker_deployment.md](../../Databases/PostgreSQL/Operations/docker_deployment.md) |
| MySQL | [Databases/MySQL/security.md](../../Databases/MySQL/security.md), [Databases/MySQL/docker.md](../../Databases/MySQL/docker.md) |
| MariaDB | [Databases/MariaDB/security/container-security.md](../../Databases/MariaDB/security/container-security.md) |
| Redis | [Databases/redis_vs_memcached.md](../../Databases/redis_vs_memcached.md) |
| Kafka | [Kafka/kafka_docker_setup.md](../../Kafka/kafka_docker_setup.md) |
| Nginx | [WebServers/Nginx/Scenarios/nginx_in_docker.md](../../WebServers/Nginx/Scenarios/nginx_in_docker.md) |
| CI/CD runners | [CI-CD/GitLab_CI/Advanced/cicd_security_hardening.md](../../CI-CD/GitLab_CI/Advanced/cicd_security_hardening.md) |
| Java-приложения | [java-image-security.md](./java-image-security.md) |

## Практические сценарии

### 1. Базовый файл `/etc/docker/daemon.json` для production

Полный пример конфигурации демона с включенными механизмами безопасности. Сохраните в `/etc/docker/daemon.json` и перезапустите демон (`systemctl restart docker`).

```json
{
  "icc": false,
  "userns-remap": "default",
  "no-new-privileges": true,
  "live-restore": true,
  "userland-proxy": false,
  "disable-legacy-registry": true,
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 65536,
      "Soft": 65536
    }
  }
}
```

**Валидация:**

```bash
# Проверка применения конфигурации
docker info --format '{{.SecurityOptions}}'
# → [userns-remap, no-new-privileges, ...]

# Проверка статуса User Namespaces
grep dockremap /etc/subuid /etc/subgid
# → dockremap:100000:65536

# Проверка отсутствия опасных флагов
ps aux | grep dockerd
# → не должно содержать --privileged
```

### 2. Сценарии эскалации привилегий

Подробные пошаговые сценарии эксплуатации уязвимостей и их предотвращение:

- **Через группу `docker` и TCP:** см. раздел в **[Защита хоста и демона](./host_daemon_hardening.md#4-docker-socket-и-группа-docker)**.
- **Побег из контейнера с проброшенным сокетом (container escape):** пошаговый сценарий и эксплуатация описаны в **[Защита хоста и демона](./host_daemon_hardening.md#4-docker-socket-и-группа-docker)**.

### 3. Сканирование образов на уязвимости

Практические примеры работы с Trivy описаны в **[Сканирование уязвимостей](./vulnerability_scanning.md)**.

### 4. Работа с секретами в Dockerfile

См. **[Управление секретами](./secrets_management.md)**.

### 5. Генерация и анализ SBOM

См. **[Docker SBOM](./docker_sbom.md)**.

### 6. Подпись и верификация образов

См. **[Подписи и Cosign](./image_signature_and_verification.md)**.

## Best Practices

- **Запуск без привилегий:** Используйте Rootless Docker и User Namespaces (`userns-remap`) во всех средах, где это возможно. Это предотвращает получение злоумышленником прав root на хосте даже при компрометации контейнера.
- **Минимизация образа:** Используйте минимальные базовые образы (Distroless, Chainguard, Alpine). Каждый лишний пакет — это дополнительная поверхность атака и потенциальная CVE.
- **Фиксация по дайджестам:** Никогда не используйте теги (`:latest`, `:1.0`) в production. Используйте `image@sha256:<digest>` для гарантии неизменности образа.
- **Drop All для Capabilities:** Запускайте контейнеры с `--cap-drop=ALL` и добавляйте только явно необходимые права через `--cap-add`. Запретите `--privileged` в production.
- **Seccomp по умолчанию:** Используйте стандартный профиль Docker или кастомный. Отключение seccomp (`unconfined`) резко расширяет поверхность атаки.
- **Read-only root FS:** Запускайте контейнеры с `--read-only` и временными директориями (`--tmpfs`) для данных, требующих записи.
- **Секреты вне метаданных:** Никогда не передавайте секреты через `ENV`, `ARG` или метаданные образа. Используйте Docker Secrets, BuildKit Secrets или внешние менеджеры (Vault, 1Password).
- **Регулярное обновление:** Поддерживайте Docker Engine, containerd и runc в актуальном состоянии. Docker 28.x и ранее перешли в статус EOL и не получают исправлений безопасности.
- **Аудит по умолчанию:** Включите `auditd` для критических файлов и мониторинг `docker events` в централизованное хранилище логов.
- **CI/CD в качестве контроля:** Внедрите сканирование уязвимостей (Trivy), генерацию SBOM и проверку подписей (Cosign) на этапе сборки. Блокируйте deployment образов с критическими уязвимостями.

## Troubleshooting

- **`permission denied` при доступе к `/var/run/docker.sock`:**
  - **Причина:** Пользователь не состоит в группе `docker` или сокет имеет ограниченные права.
  - **Решение:** Добавьте пользователя в группу `docker` (`sudo usermod -aG docker $USER`) и перелогиньтесь. Проверьте права на сокет: `ls -la /var/run/docker.sock`. В rootless-режиме используйте `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock`.

- **`operation not permitted` (Seccomp):**
  - **Причина:** Системный вызов заблокирован профилем seccomp.
  - **Решение:** Определите блокируемый вызов через `dmesg` или `audit.log`. Если вызов легитимен, добавьте исключение в кастомный профиль и передайте его через `--security-opt seccomp=profile.json`. Никогда не отключайте seccomp без обоснования.

- **`no such device` или ошибки overlay2 при использовании User Namespaces:**
  - **Причина:** Ядро хоста не настроено для работы с User Namespaces, или `kernel.apparmor_restrict_unprivileged_userns=1` блокирует создание неймспейсов.
  - **Решение:** Для rootless Docker выполните `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. Для production используйте `userns-remap` в `daemon.json`.

- **Контейнер не может писать на диск при `--read-only`:**
  - **Причина:** Приложение пытается записать данные в корневую ФС, но смонтированы только указанные `--tmpfs` или `--mount` пути.
  - **Решение:** Добавьте все необходимые для записи пути через `--tmpfs /path:rw,noexec,nosuid` или `--volume /host/path:/container/path`. Используйте `docker inspect` для проверки смонтированных томов.

- **Dopplegänger / скомпрометированный образ после фиксации по тегу:**
  - **Причина:** Тег образа (`:latest`) был обновлен в реестре, и образ в production отличается от проверенного.
  - **Решение:** Перейдите на фиксацию по дайджесту (`image@sha256:...`) и включите блокировку тегов в реестре (Docker Hub: Content Trust, Harbor: Immutable Tag). Внедрите проверку дайджеста в admission controller.

- **Контейнер получает больше CPU/RAM, чем ожидалось:**
  - **Причина:** Отсутствуют или некорректно настроены лимиты Cgroups v2. Docker использует `memory` и `cpus` как soft limits.
  - **Решение:** Установите жесткие лимиты: `--memory="512m" --memory-swap="512m" --cpus="0.5" --pids-limit 100`. Проверьте применение через `docker stats`. Для OOM detection используйте `memory.events` в cgroups.

- **Аномальная активность контейнера (подозрение на взлом):**
  - **Причина:** Скомпрометированный контейнер пытается подключиться к внешним ресурсам или запустить shell.
  - **Решение:** Используйте `docker events` для просмотра истории exec_create/exec_start. Примените Falco или Tetragon для eBPF-мониторинга. Изолируйте контейнер (`docker pause <id>`) и сохраните данные для расследования.

- **Cgroup v2 не активирован (Rootless Docker не запускается):**
  - **Причина:** На хосте не смонтирована файловая система cgroup2 или используется legacy cgroup v1.
  - **Решение:** Проверьте: `stat -fc %T /sys/fs/cgroup/` (должно быть `cgroup2fs`). Добавьте в `/etc/default/grub`: `GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"`, выполните `update-grub` и перезагрузитесь. Rootless Docker требует cgroup v2.

- **Ошибка `x509: certificate signed by unknown authority` при `docker pull`:**
  - **Причина:** Docker не доверяет самоподписанному сертификату частного реестра.
  - **Решение:** Поместите CA-сертификат в `/etc/docker/certs.d/<registry-host>/ca.crt` на хосте. Перезапустите демон. Убедитесь, что файл имеет права `0644` и принадлежит `root:root`.

- **`docker events` не генерирует события:**
  - **Причина:** События могут отбрасываться, если демон перегружен или используется `--event-lost` без обработчика. В Rootless-режиме проверьте переменную `DOCKER_HOST`.
  - **Решение:** Восстановите подписку: `docker events --filter 'type=container' --format '{{.Action}} {{.Actor.ID}}'`. Для централизованного сбора используйте `auditd` как резервный канал.

## Дополнительная информация

**Граничные случаи и ограничения:**

- **Rootless Docker и привилегированные порты (<1024):** В Rootless-режиме приложение не может биндить порты ниже 1024 без дополнительных настроек (`net.ipv4.ip_unprivileged_port_start`). Для production-сервисов используйте reverse proxy (Traefik, Nginx) на хосте или настройку `setcap 'cap_net_bind_service=+ep' /usr/bin/<binary>`.
- **User Namespaces и Bind Mount:** При включенном `userns-remap` UID 0 внутри контейнера маппится на непривилегированный UID на хосте (например, 100000). Это ломает запись в bind-mounted директории, если права на хосте не согласованы. Используйте Docker Volumes вместо Bind Mount для критичных данных.
- **Overlay2 и User Namespaces:** Файловая система `overlay2` не поддерживается с `userns-remap` на некоторых ядрах. Альтернативы: `fuse-overlayfs` (требует установки пакета) или `vfs` (медленнее, но совместим).
- **Seccomp и гетерогенные кластеры:** Кастомный Seccomp-профиль, работающий на ядре 5.4, может блокировать syscalls на ядре 6.1+ из-за изменений в таблице системных вызовов. Тестируйте профили на всех целевых ядрах.
- **Rootless Docker и systemd:** Привязка контейнера к systemd-юниту (`docker run --sdnotify=...`) работает только в root-режиме. В Rootless используйте `--init` или внешний supervisor (supervisord, s6).

**Связанные документы:**

- **[Защита хоста и демона](./host_daemon_hardening.md)** (userns-remap, Rootless)
- **[Укрепление контейнеров](./container_hardening.md)** (capabilities, seccomp, limits)
- **[SSH-agent в rootless Docker без экспозиции приватного ключа](./ssh-agent-rootless.md)** — безопасная передача сокета ssh-agent в контейнер.
- **[Механизмы изоляции Linux](../../Docker/Concepts/linux_isolation.md)**
- **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)**
- **[Мониторинг в Runtime](./runtime_monitoring.md)** (eBPF, Tetragon, Falco)
- **[Аудит событий (auditd)](../../Linux/SystemAdministration/Logging/auditd.md)**
- **[CVE побегов из контейнеров](./container_escape_cves.md)** — каталог container escape CVE (CVE-2019-5736, CVE-2024-21626 и др.)
- **[Сетевая безопасность](./network_security.md)** — ICC, DOCKER-USER, egress, CVE-2024-29018
- **[Пользовательские профили](./custom_security_profiles.md)** — AppArmor/SELinux/seccomp для контейнеров
- **[Авторизация Docker API](./api_authorization.md)** — authorization-плагины, mTLS, socket-proxy
- **[Безопасность реестров](./registry_security.md)** — подписи, сканирование, RBAC, immutable tags
- **[Compliance-фреймворки](./compliance_frameworks.md)** — PCI DSS, ISO 27001, SOC 2, GDPR, EU CRA
- **[Реагирование на инциденты](./incident_response.md)** — runbook: pause, форензика, ликвидация
- **[Защита Docker API от DoS](./api_dos_protection.md)** — rate limiting (nginx), firewall, containerd и Docker Engine DoS-CVE
- **[Метрики безопасности и SLO](./security_metrics.md)** — Docker-специфичные метрики, MTTR, drift
- **[Политика свежести образов](./image_freshness_policy.md)** — EOL-детекция, автообновление базовых образов
- **[FIPS 140-2](./fips_compliance.md)** — Mirantis Container Runtime, FIPS mode, UBI
- **[Multi-tenancy](./multi_tenancy_security.md)** — изоляция tenants в Docker standalone
- **[Безопасность Buildx builders](./buildx_builder_security.md)** — изоляция builders, cache, secrets, provenance
- **[Вопросы на собеседованиях](./docker_security_interview_qa.md)** — Q&A по Docker security

**Глубокое изучение:**
- **[CI/CD Security](../../Security/Supply_Chain_Security/overview.md)** — защита pipeline. В Docker: runner hardening (ephemeral runners), секреты через OIDC (не в variables), сканирование при сборке, signing перед push.
- **[Docker Desktop Security](https://docs.docker.com/desktop/security/)** — изоляция VM на macOS. В Docker: credential helper, file sharing limitations, Docker Socket exposure risks.

**Внешние стандарты:**

- **CIS Docker Benchmark:** Фундаментальные рекомендации по настройке.
- **NIST SP 800-190:** Руководство по безопасности контейнеров.
- **CVE Database:** Отслеживание новых уязвимостей (runc, containerd).
- **Docker Security Advisory:** Официальный бюллетень безопасности Docker.
