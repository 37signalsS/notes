# Безопасность MariaDB в контейнерах

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS; Docker Engine 29.x / Podman 5+ (секреты Podman — с 4.4)

## Определения

**Контейнерная изоляция** — изоляция процесса СУБД средствами ядра Linux: namespaces (PID, network, mount), cgroups (ресурсы), seccomp (фильтр системных вызовов), capabilities (ограничение root-привилегий).

**Rootless-контейнер** — контейнер, запущенный без root на хосте (user namespace); компрометация процесса не даёт root на хосте.

**Read-only root filesystem** — корневая файловая система контейнера смонтирована только для чтения; запись возможна только в явно подключённые тома и `tmpfs`.

**Docker secrets / Podman secrets** — механизм передачи секретов (паролей, ключей) в контейнер через tmpfs-монтирование `/run/secrets/`, а не через переменные окружения. Docker secrets доступны **только Swarm-сервисам** (в standalone Docker — bind-mount файла или Compose); Podman secrets работают в standalone-режиме, включая rootless (с Podman 4.4).

**Docker Content Trust (DCT)** — подпись образов на базе Notary v1. **Выводится из эксплуатации:** сервис Notary v1 (notary.docker.io) отключается 08.12.2026; замена — Cosign (Sigstore) и Notation (Notary Project). Не стройте новые пайплайны на DCT/`DOCKER_CONTENT_TRUST`.

**`gosu`** — утилита для смены пользователя без shell; entrypoint официального образа MariaDB использует её для запуска `mariadbd` от имени пользователя `mysql` после инициализации. Пользователь `mysql` создаётся в образе через `useradd -r` — в актуальных ubuntu-образах это UID 999, но номер не закреплён в Dockerfile (проверяйте: `docker run --rm mariadb:11.8 id mysql`).

## Основные концепции

### Модель запуска официального образа

1. Entrypoint стартует кратковременно от root: создаёт/исправляет права на datadir (`chown`), инициализирует системные таблицы.
2. Затем через `gosu` переключается на пользователя `mysql` (UID 999 в актуальных ubuntu-образах; номер не закреплён в Dockerfile) и запускает `mariadbd`.
3. `mariadbd` никогда не должен работать от root — переопределение `user=root` в конфиге опасно и ломает модель безопасности.

### Уровни защиты контейнера

| Уровень | Механизм | Эффект |
| :--- | :--- | :--- |
| Образ | подписанный, минимальный, сканированный | нет известных CVE в базовом образе |
| Процесс | non-root, read-only rootfs, dropped capabilities | ограничение при компрометации |
| Хост | rootless, seccomp, user namespace | изоляция от хоста |
| Сеть | отдельная сеть, `bind-address`, файрвол | ограничение доступа к 3306 |
| Секреты | Docker/Podman secrets, не env-переменные | нет паролей в `docker inspect` |

### Чего контейнер НЕ решает

- **Не заменяет hardening СУБД:** RBAC, TLS, аудит, `mariadb-secure-installation` применяются внутри контейнера так же, как на хосте.
- **Не шифрует данные:** тома с datadir шифруются на уровне хоста (LUKS) или СУБД (TDE).
- **Не изолирует от ядра:** контейнеры разделяют ядро; уязвимости ядра затрагивают всех.

## Предварительные требования

- Docker Engine 29.x или Podman 5+ (rootless рекомендуется; секреты Podman — с 4.4)
- Образ `mariadb:11.8` (или актуальный LTS-тег: 11.4 / 11.8 / 12.3)
- Хранилище секретов: Podman secrets или Vault; в standalone Docker — файл с правами 0400 (Docker secrets — только Swarm)
- Сеть для контейнеров (bridge или overlay)

## Практические сценарии

### Сценарий 1: Безопасный запуск (Docker, standalone)

```bash
# Сеть для контейнера
docker network create dbnet

# Секрет — файл на хосте (Docker secrets доступны ТОЛЬКО в Swarm!)
# entrypoint читает файл от root (инициализация) и от mysql (UID 999) при перезапуске —
# файл должен быть читаем UID 999
printf '%s' 'S3cureP@ss!' > ./mariadb_root_password
sudo chown 999:999 ./mariadb_root_password
chmod 0400 ./mariadb_root_password

# Запуск с read-only rootfs и ограничениями
docker run -d \
  --name mariadb \
  --network dbnet \
  --read-only \
  --tmpfs /run/mysqld:rw,noexec,nosuid,size=64m \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --cap-add CHOWN \
  --cap-add SETGID \
  --cap-add SETUID \
  --security-opt no-new-privileges \
  -v mariadb-data:/var/lib/mysql \
  -v ./mariadb_root_password:/run/secrets/mariadb_root_password:ro \
  -v ./custom.cnf:/etc/mysql/conf.d/custom.cnf:ro \
  -e MARIADB_ROOT_PASSWORD_FILE=/run/secrets/mariadb_root_password \
  -p 127.0.0.1:3306:3306 \
  --health-cmd="healthcheck.sh --connect" --health-interval=30s --health-retries=3 \
  mariadb:11.8
```

**Пояснения:**
- `--read-only` — корневая ФС только для чтения; `tmpfs` для `/run/mysqld` (сокет, pid-файл) и `/tmp`.
- `--cap-drop ALL` + минимальный `--cap-add` — entrypoint при инициализации от root нуждается в CHOWN/SETGID/SETUID (chown datadir + переход на `mysql`); при запуске с `--user` (сценарий 2) capabilities не нужны.
- `--security-opt no-new-privileges` — запрет повышения привилегий внутри контейнера.
- Seccomp: профиль `docker-default` (~44 заблокированных системных вызова) применяется автоматически; для кастомного профиля — `--security-opt seccomp=/path/to/profile.json`.
- `-p 127.0.0.1:3306:3306` — публикация только на loopback; доступ через хост-приложение.
- Конфиг и секрет монтируются `:ro` — контейнер не может их изменить.
- `--health-cmd` — образ поставляет `/usr/local/bin/healthcheck.sh`; тест `--connect` проверяет возможность подключения.
- Для multi-container изоляции без внешнего доступа — `docker network create --internal dbnet`: egress заблокирован, порт при этом не публикуется, приложение подключается по сети контейнеров.

### Сценарий 2: Запуск от произвольного пользователя

```bash
# Подготовка тома с правами для UID 2022
docker volume create mariadb-data
sudo mkdir -p /var/lib/docker/volumes/mariadb-data/_data
sudo chown 2022:2022 /var/lib/docker/volumes/mariadb-data/_data

# Запуск от UID 2022 (без root на любом этапе)
# секрет — файл, читаемый UID 2022 (Docker secrets — только Swarm)
printf '%s' 'S3cureP@ss!' > ./mariadb_root_password
sudo chown 2022:2022 ./mariadb_root_password
chmod 0400 ./mariadb_root_password

docker run -d \
  --name mariadb-nonroot \
  --user 2022:2022 \
  --read-only \
  --tmpfs /run/mysqld:rw,noexec,nosuid,size=64m \
  -v mariadb-data:/var/lib/mysql \
  -v ./mariadb_root_password:/run/secrets/mariadb_root_password:ro \
  -e MARIADB_ROOT_PASSWORD_FILE=/run/secrets/mariadb_root_password \
  mariadb:11.8
```

**Пояснение:** при `--user 2022:2022` entrypoint не может `chown` datadir — права должны быть выставлены заранее. Это устраняет кратковременный root-этап инициализации. Файл секрета должен быть читаем UID 2022 — entrypoint читает `MARIADB_ROOT_PASSWORD_FILE` уже после перехода на целевого пользователя: `chown 2022:2022 ./mariadb_root_password && chmod 0400`. Для rootless Docker путь к volume отличается: `~/.local/share/docker/volumes/mariadb-data/_data`.

### Сценарий 3: Rootless Podman

```bash
# Секрет Podman (работает в standalone-режиме, включая rootless)
printf '%s' 'S3cureP@ss!' | podman secret create mariadb_root_password -

# Rootless-запуск (процесс не root на хосте)
podman run -d \
  --name mariadb \
  --read-only \
  --tmpfs /run/mysqld:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --cap-add CHOWN \
  --cap-add SETGID \
  --cap-add SETUID \
  --security-opt no-new-privileges \
  -v mariadb-data:/var/lib/mysql \
  --secret source=mariadb_root_password,target=mariadb_root_password,uid=999,gid=999,mode=0400 \
  -e MARIADB_ROOT_PASSWORD_FILE=/run/secrets/mariadb_root_password \
  -p 127.0.0.1:3306:3306 \
  mariadb:11.8

# Проверка: user — пользователь в контейнере, huser — пользователь на хосте
podman top mariadb user,huser,pid,comm
# → mysql <ваш-user> ... mariadbd
```

**Пояснение:** rootless Podman запускает контейнер от непривилегированного пользователя хоста (user namespace): компрометация `mariadbd` не даёт root на хосте. Порт 3306 > 1024, поэтому rootless может его публиковать; порты < 1024 требуют `sysctl net.ipv4.ip_unprivileged_port_start=0`. Не используйте `--network host` — он снимает сетевую изоляцию контейнера.

### Сценарий 4: Проверка образа

```bash
# Сканирование на уязвимости
docker scout cves mariadb:11.8
# → список CVE и базовый образ

# Пиннинг по digest (иммунен к переизданию тега)
docker pull mariadb:11.8@sha256:<digest>

# Верификация подписи (Cosign из Sigstore; DCT/Notary v1 отключается 08.12.2026)
cosign verify --key cosign.pub docker.io/library/mariadb:11.8
# → образ должен быть подписан, иначе верификация отклонена

# Проверка, что mariadbd не root
docker top mariadb
# → mysql ... mariadbd
```

## Конфигурации и команды

### `custom.cnf` для контейнера

```ini
[mariadb]
# Hardening внутри контейнера (те же принципы, что на хосте)
bind-address        = 0.0.0.0
skip-name-resolve   = 1
require_secure_transport = ON
local-infile        = 0
skip-show-database  = 1
symbolic-links      = 0

# Аудит
plugin_load_add     = server_audit
server_audit_events = CONNECT, TABLE
server_audit_logging = ON
```

### Проверка изоляции

```bash
# Контейнер не имеет лишних capabilities
docker inspect mariadb --format '{{.HostConfig.CapDrop}} {{.HostConfig.CapAdd}}'
# → [ALL] [CHOWN SETGID SETUID]

# Rootfs read-only
docker inspect mariadb --format '{{.HostConfig.ReadonlyRootfs}}'
# → true

# Нет новых привилегий (seccomp-профиль docker-default применяется автоматически)
docker inspect mariadb --format '{{.HostConfig.SecurityOpt}}'
# → [no-new-privileges]
```

## Проверка и валидация

### Чек-лист безопасности контейнера

```bash
# 1. mariadbd работает не от root (ps в образе не установлен — используем docker top)
docker top mariadb
# → mysql ... mariadbd

# 2. Rootfs read-only
docker exec mariadb touch /test-write
# → touch: cannot touch '/test-write': Read-only file system

# 3. Секрет не в env
docker inspect mariadb --format '{{.Config.Env}}' | grep PASSWORD
# → пустой результат (только *_FILE)

# 4. Порт не опубликован на 0.0.0.0
docker port mariadb
# → 3306/tcp -> 127.0.0.1:3306
```

## Устранение неполадок

### Контейнер не стартует с `--read-only`

**Симптом:** `Can't create/write to file '/run/mysqld/mysqld.pid'`.

**Причина:** `/run/mysqld` не смонтирован как `tmpfs`.

**Решение:** добавьте `--tmpfs /run/mysqld:rw,noexec,nosuid,size=64m`.

### Entrypoint не может инициализировать datadir

**Симптом:** ошибки `chown` / `Permission denied` при первом запуске.

**Причина:** том с datadir не принадлежит пользователю контейнера (при `--user`).

**Решение:** выставьте права на том заранее (`chown 2022:2022`) или запускайте без `--user` (entrypoint сам выполнит `chown` кратковременно от root).

### Пароль виден в `docker inspect`

**Причина:** пароль передан через `MARIADB_ROOT_PASSWORD` (env).

**Решение:** используйте `MARIADB_ROOT_PASSWORD_FILE` + Docker/Podman secrets.

## Лучшие практики

1. **Non-root всегда.** Используйте `--user` с подготовленным томом или полагайтесь на `gosu` entrypoint; никогда не запускайте `mariadbd` от root.
2. **Read-only rootfs.** Минимизирует возможности злоумышленника при компрометации.
3. **Секреты — не env.** Env-переменные видны в `docker inspect`, логах, `ps`.
4. **Подписанные образы.** Cosign (Sigstore) или Notation; сканирование (`docker scout cves`, Trivy) перед деплоем. DCT (Notary v1) отключается 08.12.2026 — не используйте в новых пайплайнах.
5. **Hardening внутри контейнера.** Контейнер — не замена `mariadb-secure-installation`, RBAC, TLS и аудиту.
6. **Обновляйте образы.** Базовый образ (`debian`/`ubuntu`) получает патчи; пересобирайте регулярно.

## Граничные случаи

- **Docker < 28.0.0:** хосты в одном L2-сегменте (например, подключённые к одному коммутатору) могут достукиваться до портов, опубликованных на `127.0.0.1` (предупреждение из документации Docker). На старых версиях добавьте файрвол-правило на хосте.
- **UID не зафиксирован в образе:** пользователь `mysql` создаётся через `useradd -r` (на практике UID 999, но Dockerfile не гарантирует номер). Перед `chown` тома на хосте проверьте: `docker run --rm mariadb:11.8 id mysql`.
- **`healthcheck.sh` требует аргументов:** без аргументов скрипт завершается с ошибкой («At least one argument required»); минимальный тест — `healthcheck.sh --connect`. Доступные тесты: `connect`, `innodb_initialized`, `innodb_buffer_pool_loaded`, `galera_online`, `galera_ready`, `replication`, `mariadbupgrade`.
- **`--network host` ослабляет изоляцию:** контейнер разделяет сетевой стек хоста — `bind-address` и файрвол хоста становятся единственной защитой. Используйте bridge-сеть (`dbnet`) и публикацию только на loopback.
- **Ядро общее для всех контейнеров:** уязвимости ядра затрагивают всех. Для усиления границы — sandboxed runtimes (gVisor, Kata Containers), см. [Укрепление контейнеров](../../../Docker/Docker_security/container_hardening.md).
- **Rootless Docker:** путь к volumes отличается (`~/.local/share/docker/volumes/...`), и `sudo chown` на volume недоступен — готовьте владельца каталога до запуска.

## Дополнительная информация

### Ограничения

- `--cap-drop ALL` требует минимального набора `CHOWN/SETGID/SETUID` для entrypoint; при `--user` эти capabilities не нужны.
- Rootless Podman имеет ограничения на проброс портов < 1024 и некоторые сетевые режимы.
- Docker secrets (`docker secret create`, `--secret`) доступны только Swarm-сервисам; в standalone Docker секрет — bind-mount файла с правами 0400 или Compose-секрет (Compose реализует секреты как bind-mount, без шифрования).
- DCT/Notary v1 (notary.docker.io) отключается 08.12.2026 — мигрируйте на Cosign/Notation.

### Смежные темы

- **[Начальная закалка](hardening.md)** — hardening внутри контейнера.
- **[Сетевая безопасность](network-security.md)** — `bind-address`, файрвол.
- **[SSL/TLS](ssl-tls.md)** — TLS в контейнере.
- **[Аудит](audit.md)** — аудит в контейнере.
- **[TDE](tde.md)** — шифрование томов.
- **[Безопасность контейнеров (общая)](../../../Linux/Security/Concepts/container_security.md)** — теория изоляции.
- **[Укрепление контейнеров Docker](../../../Docker/Docker_security/container_hardening.md)** — capabilities, seccomp, LSM, rootless Docker.
- **[Podman hardening](../../../Podman/podman_security_hardening.md)** — rootless Podman, Cosign, SBOM.
