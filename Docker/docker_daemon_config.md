# Docker daemon.json — полный референс

**Актуально для:** Docker Engine 29.x (containerd image store — дефолт для новых установок; classic graph drivers deprecated), минимальная API v1.44 (2026)

## Определения

**daemon.json** — файл конфигурации Docker Engine, определяющий глобальные параметры демона: драйвер хранения, логирования, сетевые настройки, политики безопасности и адреса сервисов. Расположение по умолчанию:

| ОС / режим | Путь |
|---|---|
| Linux, обычная установка | `/etc/docker/daemon.json` |
| Linux, rootless mode | `~/.config/docker/daemon.json` (учитывается `XDG_CONFIG_HOME`) |
| Windows | `C:\ProgramData\docker\config\daemon.json` |

Путь меняется флагом `dockerd --config-file=<path>`. На Docker Desktop редактирование storage-драйвера через daemon.json не поддерживается (Desktop использует containerd image store).

**Конфликт конфигурации** — правило разрешения настроек демона. Опция, заданная одновременно в `daemon.json` и флагом `dockerd`, приводит к ошибке запуска (`unable to configure the Docker daemon ... specified both as a flag and in the configuration file`) — приоритета «флаг над файлом» нет, даже при совпадающих значениях. Иерархия применения: daemon.json/флаги dockerd (глобально) → `docker run`/Compose (контейнер). Часть опций перечитывается без перезапуска по сигналу `SIGHUP`.

**Docker Engine** — демон `dockerd`, отвечающий за управление образами, контейнерами, сетями и хранилищами. Конфигурация демона через `daemon.json` определяет поведение всех операций Docker на хосте.

**Storage Driver** — подсистема управления файловой системой контейнеров. Отвечает за хранение слоёв образов (image layers), файловую систему контейнера (container layer) и данные volume (volume data). Дефолтный classic-драйвер — `overlay2`, реализующий union mount через OverlayFS ядра Linux. С Docker 29.0 хранение образов по умолчанию перешло на containerd snapshotters (см. ниже).

**Containerd image store** — хранилище образов на базе containerd snapshotters (дефолт для новых установок Docker Engine 29.0+). Поддерживает multi-platform образы и attestations; snapshotter по умолчанию — `overlayfs`. На обновлённых установках включается через `features.containerd-snapshotter`.

**Logging Driver** — подсистема перехвата потоков `stdout` и `stderr` контейнера и маршрутизации логов в указанное хранилище (локальные файлы, системный журнал, удалённый сервис). Дефолтный драйвер — `json-file`.

**BuildKit** — современный движок сборки образов Docker, заменивший классический сборщик. Поддерживает параллельную сборку, кеширование через `--mount=type=cache`, секреты и экспериментальные функции через `experimental: true`.

## Базовые концепции

### Архитектура конфигурации

Docker Engine считывает `daemon.json` при запуске демона. Файл содержит JSON-объект с ключами, сгруппированными по функциональным областям. Изменения вступают в силу после перезапуска демона:

```bash
sudo systemctl restart docker
```

Часть опций перечитывается без перезапуска по сигналу `SIGHUP` (см. Сценарий 15).

Текущая конфигурация отображается через:

```bash
docker info
docker info --format '{{.LoggingDriver}}'
docker info --format '{{.DockerRootDir}}'
```

**Конфликт с флагами запуска.** Демон не стартует, если опция задана и в файле, и флагом — даже если значения совпадают:

```text
unable to configure the Docker daemon with file /etc/docker/daemon.json:
the following directives are specified both as a flag and in the configuration file:
hosts: (from flag: [fd://], from file: [tcp://127.0.0.1:2376])
```

На Debian/Ubuntu systemd всегда передаёт `-H fd://`, поэтому ключ `hosts` в `daemon.json` требует systemd drop-in (см. Сценарий 7).

### Хранение образов: containerd image store и classic graph drivers

**Docker Engine 29.0+**: containerd image store — дефолт для свежих установок. При обновлении с более ранней версии демон продолжает использовать classic graph drivers (overlay2) до явного включения:

```json
{
  "features": {
    "containerd-snapshotter": true
  }
}
```

Ограничения и следствия:

- **Не совместим с `userns-remap`** (moby#47377): при включённом remap containerd image store временно недоступен (moby#51042)
- Legacy graph drivers deprecated и будут удалены в будущем релизе
- Образы, загруженные в overlay2, не видны в containerd image store и наоборот — миграция через реестр (`docker pull`/`push`) или `docker save`/`load`
- Экспериментальный бэкенд файрвола: `"firewall-backend": "nftables"` (Docker 29.0+)

**Classic graph drivers** (для обновлённых установок и rootless):

| Драйвер | Описание | Требования |
|---------|----------|------------|
| `overlay2` | Рекомендуемый. Union mount через OverlayFS. | Ядро ≥4.0 (RHEL/CentOS ≥3.10.0-514); xfs с `ftype=1`, ext4, btrfs |
| `fuse-overlayfs` | Только rootless на ядрах <5.11; на ≥5.11 overlay2 работает rootless нативно | любая ФС |
| `btrfs` | Снапшоты; только SLES/Ubuntu/Debian CE; известные проблемы (moby#27653) | ФС btrfs, выделенный блочный диск, пакет `btrfsprogs` |
| `zfs` | Снапшоты; модуль ZFS on Linux (ZoL); не рекомендуется в production без опыта работы с ZFS | ФС zfs, выделенные блочные диски |
| `vfs` | Тестирование и отладка. Нет union mount и CoW — каждый слой полная копия; низкая производительность | любая ФС |

`overlay2` работает путём наложения директорий: нижний слой (read-only) + верхний слой (read-write) = объединённая файловая система контейнера. При записи файлов в контейнер происходит copy-on-write: файл копируется из нижнего слоя в верхний перед модификацией.

**Важно:** смена `storage-driver` делает существующие контейнеры недоступными (меняется layout хранилища). Перед сменой сохраните образы: `docker save` или `push` в реестр.

Дополнительные опции драйвера — ключ `storage-opts` (например, `overlay2.size` для лимита размера контейнера на xfs с `pquota`, `overlay2.override_kernel_check`).

### Обновление Docker Engine: путь миграции

Мажорные версии вносят изменения, влияющие на конфигурацию демона. Ключевые вехи (проверено по официальным release notes):

| Версия | Ключевые изменения для эксплуатации |
|---|---|
| **27.0** (06.2024) | `ip6tables` включён по умолчанию для bridge-сетей (breaking change для IPv6-сетей без ip6tables: доступны только опубликованные порты; откат — `"ip6tables": false`); ULA-префикс автоматически добавляется в `default-address-pools`; IPv6 по умолчанию на custom bridge-сетях через `"default-network-opts"`; containerd image store: `--platform` для `docker image push` |
| **28.0** (02.2025) | Hardening сети по умолчанию: трафик на неопубликованные порты дропается (opt-out: `"ip-forward-no-drop": true` или сеть `nat-unprotected`); требуется поддержка `ipset` в ядре (в 28.0.1 зависимость от модулей `ip_set`/`netfilter_xt_set` убрана); `--mount type=image`; `--platform` для `save`/`load`/`history`; API v1.48; deprecated `KernelMemoryTCP`; удалены legacy CBC cipher suites; обновлённый `docker-proxy` не работает со старым `dockerd` |
| **29.0** (11.2025) | containerd image store — дефолт для свежих установок; legacy graph drivers deprecated (будут удалены в будущем релизе); cgroup v1 deprecated (поддержка до мая 2029, moby#51111); DCT удалён из CLI (доступен как отдельный плагин); минимальная API v1.44 (клиенты Docker 25.0+); экспериментальный `firewall-backend: nftables` |

**Процедура обновления:**

```bash
# 1. Текущая версия
docker version --format '{{.Server.Version}}'
# → 27.5.1

# 2. Бэкап конфигурации и образов
sudo cp /etc/docker/daemon.json{,.bak.$(date +%F)}
docker save -o /backup/images-$(date +%F).tar $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -v '<none>')

# 3. Обновление пакетов
sudo apt-get update && sudo apt-get install --only-upgrade docker-ce docker-ce-cli containerd.io
# (RHEL/CentOS: sudo yum update docker-ce docker-ce-cli containerd.io)

# 4. Проверка
sudo systemctl restart docker && systemctl is-active docker
# → active
docker info --format '{{.ServerVersion}} | {{.StorageDriver}}'
# → 29.8.1 | overlay2 (обновлённая установка) или containerd (свежая)
```

**Миграция на containerd image store** (обновлённые установки 29.x) — включается явно:

```json
{
  "features": {
    "containerd-snapshotter": true
  }
}
```

- Существующие образы и контейнеры overlay2 остаются на диске, но становятся невидимы; возвращаются при откате на overlay2
- Чтобы использовать старые образы в containerd image store: `docker push` в реестр или `docker save`/`load`
- Автоматический переход: если нет запущенных/остановленных контейнеров и ≤5 образов, демон переключается при restart
- Не совместим с `userns-remap` (moby#47377; временно недоступен — moby#51042)

**Откат с 28.x:** при даунгрейде требуется ручная очистка новых iptables-правил — перезагрузка хоста или `iptables -F` + `ip6tables -F` перед стартом старой версии демона.

**Чек-лист перед обновлением:**
- `userns-remap` включён? На 29.x containerd image store недоступен (moby#47377)
- Ядро поддерживает `ipset`? (28.0.0; в 28.0.1+ зависимость смягчена)
- cgroup v2 включён? (29.x: cgroup v1 deprecated, поддержка до мая 2029)
- Клиенты Docker ≥25.0? (29.x: минимальная API v1.44)
- Сторонние плагины и `docker-proxy` обновлены? (28.x: версии `docker-proxy` и `dockerd` должны совпадать)

### Logging Driver — система логирования

Docker реализует стандартный подход: приложение пишет в стандартные потоки (`stdout`/`stderr`), а Docker Engine перехватывает вывод и направляет его через лог-драйвер.

**Поток данных:**
```
Процесс в контейнере → Pipe (ядро) → Docker Engine → Лог-драйвер → Хранилище
```

**Формат записи (json-file / local):**
```json
{
  "log": "2026-08-22 12:00:00 [INFO] Started\n",
  "stream": "stdout",
  "time": "2026-08-22T12:00:00.123456789Z"
}
```

**Dual Logging** (Docker 20.10+) — механизм параллельной записи: логи хранятся локально (для `docker logs`) и одновременно отправляются на сетевой драйвер. Это позволяет использовать удалённые драйверы без потери работоспособности `docker logs`.

**Non-blocking mode** — альтернатива стандартному поведению. Вместо блокировки контейнера при недоступности удалённого хранилища, Docker пишет логи в кольцевой буфер в памяти. При переполнении буфера записи отбрасываются (FIFO). Это предотвращает каскадные сбои ценой потери части логов.

Все драйверы (local, journald, fluentd, syslog, gelf, loki и др.) и их опции — в **[Обзоре логирования](Docker_logs/docker_logging_drivers_overview.md)**.

### Логи Docker daemon

Сам демон (`dockerd`) пишет свои логи не через лог-драйверы контейнеров, а в системный журнал:

- **systemd** (Ubuntu 16.04+, RHEL 7+, Debian 8+): `journalctl -u docker` (follow: `journalctl -u docker -f`)
- **syslog без systemd**: `/var/log/docker.log`
- **Docker Desktop**: логи демона через GUI (Troubleshoot → Get support)

Уровень детализации задаётся ключом `log-level` в `daemon.json` (`debug`, `info`, `warn`, `error`, `fatal`; по умолчанию `info`) или флагом `dockerd --debug`. Для диагностики проблем с лог-драйверами (например, silent-режима плагина Loki) полезен `debug`-уровень:

```bash
journalctl -u docker --since "10 min ago" | grep -i loki
```

Подробнее о чтении логов контейнеров — в **[Справочнике docker logs](Docker_logs/docker_logs_cli.md)**.

### Сетевые настройки демона

Docker создаёт и управляет сетевыми интерфейсами на хосте. Ключевые параметры:

- **bridge** — виртуальный мост `docker0`, обеспечивающий связь контейнеров через NAT
- **DNS** — встроенный DNS-сервер `127.0.0.11` для именованной связи контейнеров
- **iptables** — Docker управляет правилами фильтрации и трансляции адресов
- **Адресация** — `bip` (IP моста), `fixed-cidr` (подсеть контейнеров), `default-address-pools` (пулы для пользовательских сетей) — подробнее в **[Сетях](Docker_network/docker_network.md)**

При `icc: false` (Inter-Container Communication) контейнеры в одной bridge-сети не могут общаться напрямую — требуется явное подключение через именованные сети или `--link`.

### Безопасность демона

Конфигурация безопасности определяет уровень изоляции контейнеров:

- **User Namespaces** (`userns-remap`) — маппинг UID: root в контейнере ≠ root на хосте
- **no-new-privileges** — запрет на получение привилегий через setuid/setgid бинарники
- **live-restore** — сохранение контейнеров при перезапуске демона
- **icc: false** — изоляция контейнеров друг от друга
- **seccomp-profile** — путь к профилю seccomp; значение `"unconfined"` отключает дефолтный профиль, по умолчанию используется встроенный (`builtin`)
- **selinux-enabled** — поддержка SELinux-маркировки (RHEL/CentOS/Fedora)

### BuildKit — движок сборки

BuildKit — дефолтный движок сборки с Docker 23.0+. Поддерживает:

- Параллельную сборку слоёв
- Кеширование через `--mount=type=cache`
- Секреты через `--mount=type=secret`
- Garbage Collection кеша через `builder.gc.*`

### Runtimes

Демон поддерживает несколько OCI-runtimes одновременно (ключ `runtimes`), дефолтный — `runc` (ключ `default-runtime`). Подробно об альтернативных runtime — в **[Альтернативных средах выполнения](alternative_runtimes_and_tools.md)**.

## Предварительные требования

- **Docker Engine** установлен (установка: **[docker_install_ubuntu.md](./docker_install_ubuntu.md)**); версия ≥29.0 для containerd image store по умолчанию
- **Права:** root для правки `/etc/docker/daemon.json`; root или членство в группе `docker` для чтения состояния
- **systemd** (Linux) для управления службой; для ключа `hosts` — возможность создавать systemd drop-in
- **Ядро Linux** ≥4.0 для `overlay2`; ≥5.11 для rootless overlay2; ≥5.12 для idmapped bind-монтов (`bind-idmap`)
- **Валидный JSON** в `/etc/docker/daemon.json` (проверка — в разделе Валидация)

## Практические сценарии

### 1. Базовая настройка логирования с ротацией

Настройка глобального лог-драйвера с автоматической ротацией файлов:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5",
    "compress": "true"
  }
}
```

- `max-size` — максимальный размер одного файла лога перед ротацией
- `max-file` — количество ротированных файлов (старые удаляются)
- `compress` — gzip-сжатие ротированных файлов (значение **строка** `"true"`, не булево `true`)

**Частые ошибки:**
- `max-file` без `max-size` — игнорируется, ротации нет
- `compress: true` (bool) — ошибка парсинга, нужна строка `"true"`
- Отсутствие `log-opts` — json-file без ротации, диск заполняется

Расположение файлов логов:
```
/var/lib/docker/containers/<id>/<id>-json.log
```

Ссылки: [Logging Drivers](Docker_logs/docker_logging_drivers_overview.md), [Log Rotation](Docker_logs/docker_log_rotation.md)

### 2. Non-blocking mode для стабильности

Настройка буферизации логов для предотвращения блокировки контейнеров:

```json
{
  "log-opts": {
    "mode": "non-blocking",
    "max-buffer-size": "8m"
  }
}
```

- `mode: non-blocking` — логи пишутся в кольцевой буфер, не блокируя приложение
- `max-buffer-size` — размер буфера на контейнер (4m dev, 8-16m production)
- Форма потребления RAM: `max-buffer-size × количество контейнеров`
- При переполнении буфера: логи отбрасываются, приложение продолжает работу

Ссылка: [Centralized Logging](Docker_logs/docker_centralized_logging.md)

### 3. Настройка DNS для контейнеров

Глобальная конфигурация DNS-серверов для разрешения имён:

```json
{
  "dns": ["8.8.8.8", "1.1.1.1"],
  "dns-search": ["company.local", "dev.internal"]
}
```

- Применяется ко всем контейнерам на хосте
- Решает проблемы с `systemd-resolved` на Ubuntu (когда `/etc/resolv.conf` указывает на `127.0.0.53`)
- Корпоративные DNS для VPN-окружений

Проверка текущего DNS:
```bash
docker run --rm alpine cat /etc/resolv.conf
```

Ссылки: [DNS Issues](Docker_network/troubleshooting/dns_resolution_issues.md), [DNS & Service Discovery](Docker_network/dns_and_service_discovery.md)

### 4. Настройка MTU для VPN/туннелей

Корректировка MTU при работе через IPsec или WireGuard:

```json
{
  "mtu": 1400
}
```

- Стандартный MTU Ethernet = 1500 байт (дефолт демона)
- IPsec/WireGuard добавляют заголовки (20-60 байт), реальный MTU < 1500
- Несовпадение MTU → обрыв TCP-соединений, таймауты, «зависшие» контейнеры

Диагностика MTU:
```bash
# Проверка текущего MTU моста
ip link show docker0 | grep mtu
# Тест на пропускную способность
docker run --rm alpine ping -M do -s 1472 8.8.8.8
```

Ссылка: [Network Issues](Docker_troubleshooting/network_connectivity_issues.md)

### 5. Отключение ICC и userland-proxy

Усиление сетевой изоляции контейнеров:

```json
{
  "icc": false,
  "userland-proxy": false
}
```

- `icc: false` — контейнеры в bridge-сети не могут общаться напрямую; связь только через именованные сети с explicit подключением
- `userland-proxy: false` — port publishing через iptables DNAT вместо userland proxy (меньше overhead, ниже потребление памяти)

Следствие `icc: false`: контейнеры в дефолтной сети `bridge` не видят друг друга. Для связи необходимо создавать пользовательские сети:
```bash
docker network create app-net
docker run --network app-net --name web nginx
docker run --network app-net --name api myapp
```

Ссылки: [Docker Network](Docker_network/docker_network.md), [Host Daemon Hardening](Docker_security/host_daemon_hardening.md)

### 6. Настройка User Namespaces

Маппинг UID для предотвращения эскалации привилегий:

```bash
# Создание пользователя и выделение диапазонов UID/GID
sudo useradd dockremap
sudo usermod --add-subuids 100000-165536 --add-subgids 100000-165536 dockremap
```

```json
{
  "userns-remap": "dockremap"
}
```

Значение `userns-remap` — пользователь (или `default`); диапазоны subuid/subgid читаются из `/etc/subuid` и `/etc/subgid`, а не из daemon.json.

Маппинг работает по формуле: `host_uid = container_uid + base_id`

При диапазоне `100000-165536`:
- UID 0 (root) в контейнере → UID 100000 на хосте
- UID 1000 в контейнере → UID 101000 на хосте

**Следствия включения:** существующие образы и контейнеры становятся невидимы (другое ID-пространство хранилища) — пересоздайте их после включения. Не совместимо с containerd image store (moby#47377).

**Проблема Bind Mount vs Volume:**
- Bind mount (`/data:/data`): файлы на хосте принадлежат UID 1000, контейнер (UID 0 → 100000) не может писать
- Named volume: Docker автоматически устанавливает корректные права

Решения для bind mount:
| Способ | Проблема |
|--------|----------|
| `chown 100000:100000 /data` | UID может не существовать, хрупко при смене subuid |
| `chmod 777` | Дыра в безопасности |
| `bind-idmap` в `--mount` (API v1.56) | Idmapped mount: владелец источника виден в контейнере как пользователь контейнера (`match-user`) или маппинг следует userns контейнера (`userns`); rootful-only, ядро ≥5.12, runc 1.2+ |

Версия Engine с API v1.56 проверяется командой `docker version --format '{{.Server.APIVersion}}'`.

Ссылка: [Host Daemon Hardening](Docker_security/host_daemon_hardening.md)

### 7. Настройка TLS для удалённого доступа

Безопасное подключение к удалённому Docker daemon через mTLS:

```json
{
  "tlsverify": true,
  "tlscacert": "/etc/docker/ca.pem",
  "tlscert": "/etc/docker/server-cert.pem",
  "tlskey": "/etc/docker/server-key.pem",
  "hosts": ["tcp://0.0.0.0:2376", "unix:///var/run/docker.sock"]
}
```

Без TLS доступ к Docker socket эквивалентен root-доступу ко всей машине. Проброс сокета в контейнер (`-v /var/run/docker.sock:/var/run/docker.sock`) — критическая дыра в безопасности.

**Конфликт `hosts` на systemd (Debian/Ubuntu).** systemd передаёт dockerd флаг `-H fd://`, поэтому `hosts` в daemon.json вызовет ошибку запуска. Сначала создайте drop-in, снимающий флаг:

```systemd
# /etc/systemd/system/docker.service.d/docker.conf
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

Альтернатива — прямое подключение через SSH (рекомендуется):
```bash
export DOCKER_HOST="ssh://user@remote-host"
docker info
```

Ссылка: [Host Daemon Hardening](Docker_security/host_daemon_hardening.md)

### 8. Настройка BuildKit и Garbage Collection

Включение BuildKit и настройка автоматической очистки кеша сборки:

```json
{
  "features": {
    "buildkit": true,
    "containerd-snapshotter": true
  },
  "builder": {
    "gc": {
      "enabled": true,
      "defaultKeepStorage": "20GB",
      "policy": [
        {
          "keepBytes": 10737418240,
          "keepDuration": 604800,
          "filters": ["type==source.local"]
        }
      ]
    }
  }
}
```

- `features.buildkit` — альтернатива `DOCKER_BUILDKIT=1`
- `features.containerd-snapshotter` — containerd image store (дефолт на свежих установках 29.0+; на обновлённых включается вручную)
- `builder.gc.policy[].keepBytes` — байты для хранения кеша (10737418240 = 10GB)
- `builder.gc.policy[].keepDuration` — секунды хранения (604800 = 7 дней)
- `builder.gc.policy[].filters` — типы кеша: `source.local`, `exec.cachemount`, `regular`

Ссылка: [BuildKit](Dockerfile/dockerfile_buildkit.md)

### 9. Настройка mirror registry

Корпоративный кеш образов Docker Hub через Harbor:

```json
{
  "registry-mirrors": [
    "https://harbor.example.com/v2/docker-hub-proxy"
  ]
}
```

Docker ищет образ сначала в mirror, затем в Docker Hub. Это ускоряет pull в корпоративных средах и снижает нагрузку на внешний канал.

**Ограничения:**
- `registry-mirrors` работает **только для Docker Hub** — для других реестров маршрутизация настраивается через `hosts.toml` containerd
- С containerd image store известна регрессия зеркал и upstream (moby#51994) — при проблемах проверьте `hosts.toml`

Для development/test (без TLS):
```json
{
  "insecure-registries": ["registry.internal:5000"]
}
```

Ссылки: [Harbor Usage](Docker_registries/Harbor/usage.md), [Registries Overview](docker_registries.md)

### 10. Настройка метрик и лимитов производительности

Включение Prometheus-метрик и ограничение параллельных операций:

```json
{
  "metrics-addr": "0.0.0.0:9323",
  "log-level": "info",
  "max-concurrent-downloads": 6,
  "max-concurrent-uploads": 3,
  "max-download-attempts": 5
}
```

- `metrics-addr` — адрес экспортёра метрик Docker Engine (порт 9323)
- `log-level` — уровень логирования демона: `panic`, `fatal`, `error`, `warn`, `info` (дефолт), `debug`, `trace`
- `max-concurrent-downloads` — дефолт: 3; увеличение ускоряет `docker pull` больших образов
- `max-concurrent-uploads` — дефолт: 5; уменьшение снижает нагрузку на сеть при push
- `max-download-attempts` — дефолт: 5; число повторов при обрыве соединения во время pull
- `debug: true` — синоним `log-level: debug` (для troubleshooting, не для прода)

Ссылка: [Prometheus Integration](Docker_metrics/docker_prometheus_integration.md)

### 11. Сетевые пулы и адресация

Планирование адресного пространства на хостах с большим числом сетей:

```json
{
  "default-address-pools": [
    {"base": "172.30.0.0/16", "size": 24},
    {"base": "172.31.0.0/16", "size": 24}
  ],
  "bip": "172.17.0.1/16",
  "fixed-cidr": "172.17.0.0/24",
  "ipv6": false
}
```

- `default-address-pools` — пулы, из которых IPAM выделяет подсети для пользовательских bridge-сетей; заданные пулы **заменяют** встроенный пул целиком. Дефолт (Docker 29.x): блоки `172.17.0.0/16`–`172.31.0.0/16` (`size: 16`) и `192.168.0.0/16` (`size: 20`) — ~30 сетей; подробнее и с эмпирической проверкой — в **[IPAM и планирование ёмкости](Docker_network/docker_network_ipam_scale.md)**; на хостах с десятками сетей пул может исчерпаться или пересечься с корпоративными диапазонами
- `bip` — IP-адрес моста `docker0` (дефолт `172.17.0.1/16`)
- `fixed-cidr` — подсеть для контейнеров в дефолтном bridge (дефолт `172.17.0.0/16`)
- `ipv6` / `fixed-cidr-v6` — включение IPv6 и его подсеть

Подробно про сетевую адресацию — в **[Сетях](Docker_network/docker_network.md)**.

### 12. exec-opts: драйвер cgroup для Kubernetes

```json
{
  "exec-opts": ["native.cgroupdriver=systemd"]
}
```

- `native.cgroupdriver=systemd` — драйвер cgroup systemd; рекомендуется для systemd-хостов и обязателен для Kubernetes-нод (kubelet требует совпадения cgroup-драйвера)
- Формат элементов: `opt=value`; несколько опций — через запятую в массиве
- Проверка применённого драйвера: `docker info | grep -i cgroup`

Ссылка: [Systemd в Docker](docker_systemd.md)

### 13. Production-конфигурация

Полный пример production-ready `daemon.json`:

```json
{
  "data-root": "/mnt/docker-data",

  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5",
    "compress": "true",
    "mode": "non-blocking",
    "max-buffer-size": "8m"
  },
  "log-level": "info",

  "dns": ["8.8.8.8", "1.1.1.1"],
  "mtu": 1500,

  "icc": false,
  "userland-proxy": false,
  "live-restore": true,
  "no-new-privileges": true,
  "init": true,
  "default-shm-size": "64M",
  "shutdown-timeout": 15,

  "exec-opts": ["native.cgroupdriver=systemd"],

  "max-concurrent-downloads": 6,
  "max-concurrent-uploads": 3,
  "max-download-attempts": 5,

  "metrics-addr": "0.0.0.0:9323",

  "builder": {
    "gc": {
      "enabled": true,
      "defaultKeepStorage": "20GB"
    }
  }
}
```

- `storage-driver` намеренно опущен: на свежей установке 29.x используется containerd image store; на обновлённой — дефолтный overlay2. Явно задавайте только при необходимости (смена драйвера делает существующие контейнеры недоступными)
- `init: true` — `docker-init` (tini) как PID 1 для корректной обработки сигналов и зомби-процессов
- `default-shm-size` — дефолт `/dev/shm` для контейнеров (64M)
- `shutdown-timeout` — секунды ожидания остановки контейнеров при выключении демона (дефолт 15)
- `experimental: true` включает экспериментальные функции — в production только при необходимости

### 14. Альтернативные runtimes

Настройка нестандартных OCI-runtimes для контейнеров:

```json
{
  "runtimes": {
    "kata": {
      "path": "/usr/bin/kata-runtime"
    },
    "gvisor": {
      "path": "/usr/bin/runsc"
    }
  },
  "default-runtime": "runc"
}
```

- `runc` — дефолтный OCI runtime, использует namespaces и cgroups ядра
- `kata` — аппаратная изоляция через lightweight VM
- `gvisor` — пользовательская изоляция через syscall interception (runsc)

Использование: `docker run --runtime=kata myimage`

Ссылки: [Alternative Runtimes](alternative_runtimes_and_tools.md), [Container Hardening](Docker_security/container_hardening.md)

### 15. Перезагрузка демона без даунтайма

Часть опций перечитывается без перезапуска процесса — по сигналу `SIGHUP`:

```bash
sudo kill -SIGHUP $(pidof dockerd)
```

SIGHUP-перечитываемые опции: `debug`, `labels`, `live-restore`, `max-concurrent-downloads`, `max-concurrent-uploads`, `max-download-attempts`, `default-runtime`, `runtimes`, `authorization-plugins`, `insecure-registries`, `registry-mirrors`, `shutdown-timeout`, `features`.

Остальные опции (сеть, хранилище, TLS, DNS) требуют `sudo systemctl restart docker`. Для нулевого даунтайма контейнеров сочетайте restart с `live-restore: true` — контейнеры продолжают работать, пока демон перезапускается.

## Валидация

```bash
# 1. Синтаксис JSON (нет вывода = валидный файл)
python3 -c "import json; json.load(open('/etc/docker/daemon.json'))"

# 2. Демон стартовал с новой конфигурацией
sudo systemctl restart docker && systemctl is-active docker
# → active

# 3. Ключевые параметры применились
docker info --format '{{.LoggingDriver}} | {{.StorageDriver}} | {{.DockerRootDir}}'
# → json-file | overlay2 | /mnt/docker-data

# 4. Конфигурация конкретного контейнера
docker inspect --format '{{.HostConfig.LoggingConfig.Type}}' <container>
# → json-file

# 5. Ошибки запуска демона (если не стартует)
journalctl -u docker -n 50 --no-pager
```

## Устранение неполадок

| Симптом | Причина | Решение |
|:---|:---|:---|
| `unable to configure the Docker daemon ... specified both as a flag and in the configuration file` | Опция задана и в daemon.json, и флагом (часто `hosts` vs `-H fd://` из systemd) | Убрать дубликат; для `hosts` — systemd drop-in (Сценарий 7) |
| Демон не стартует после правки файла | Невалидный JSON | `python3 -c "import json; json.load(open('/etc/docker/daemon.json'))"`; `journalctl -u docker -n 50` |
| `hosts` в daemon.json не применяется | systemd передаёт `-H fd://` | Drop-in `ExecStart=` + `ExecStart=/usr/bin/dockerd`, затем `systemctl daemon-reload` |
| Ротация логов не работает | `max-file` без `max-size` | Задать оба ключа (Сценарий 1) |
| Ошибка парсинга `compress` | Булево `true` вместо строки | `"compress": "true"` |
| Контейнеры недоступны после смены `storage-driver` | Изменился layout хранилища | `docker save`/`push` до смены; откат ключа |
| containerd image store недоступен | Включён `userns-remap` (moby#47377) | Отключить remap или остаться на overlay2 |
| Образы «пропали» после обновления до 29.x | containerd image store: образы overlay2 скрыты, но не удалены | **[docker_overview.md](./docker_overview.md)** |
| `invalid logging level: ...` | Опечатка в `log-level` | Допустимы: `panic`, `fatal`, `error`, `warn`, `info`, `debug`, `trace` |
| `iptables: false` ломает port publishing | Docker не управляет NAT-правилами | Не отключайте без замены правил вручную |
| Mirror не кэширует образы | `registry-mirrors` работает только для Docker Hub | Для других реестров — `hosts.toml` containerd; см. **[docker_registries.md](./docker_registries.md)** |
| `invalid exec-opt (...)` | Формат не `opt=value` | `"exec-opts": ["native.cgroupdriver=systemd"]` |
| После обновления до 28.x недоступны неопубликованные порты контейнеров | 28.0+ дропает трафик на неопубликованные порты по умолчанию | Опубликовать порты (`-p`); или `"ip-forward-no-drop": true`; или сеть `nat-unprotected` |
| Демон не стартует после обновления до 28.0 на ядре без `ipset` | 28.0.0 требует модулей `ip_set`/`netfilter_xt_set` | Обновиться до 28.0.1+ (зависимость убрана) или включить модули ядра |
| Образы «пропали» после включения containerd image store | overlay2-образы скрыты, но не удалены | `docker push`/`docker save` до миграции; откат на overlay2 возвращает образы |

## Лучшие практики и очистка

- **Бэкап перед правкой:** `sudo cp /etc/docker/daemon.json{,.bak.$(date +%F)}` — откат: восстановить бэкап и `sudo systemctl restart docker`
- **Минимальный набор ключей:** не настраивайте то, что не требуется — каждый ключ меняет поведение всех контейнеров на хосте
- **Ротация логов всегда** (Сценарий 1) — иначе `/var/lib/docker` заполняется
- **`live-restore: true`** в production — контейнеры живут при перезапуске демона
- **Контроль версий** для daemon.json на серверах (изменения аудируемы)
- **Очистка после экспериментов:** `docker system prune` и `docker builder prune` — см. **[docker_commands.md](./docker_commands.md)**

## Дополнительная информация

**Связанные документы:**
- **[Защита хоста и демона](Docker_security/host_daemon_hardening.md)** — CIS Benchmark, безопасные настройки, sysctl
- **[Docker Bench for Security](Docker_security/docker_bench_cis.md)** — автоматизированная проверка CIS Docker Benchmark
- **[Укрепление безопасности контейнеров](Docker_security/container_hardening.md)** — настройки внутри контейнера
- **[Обзор логирования](Docker_logs/docker_logging_drivers_overview.md)** — все драйверы логов
- **[Ротация логов](Docker_logs/docker_log_rotation.md)** — настройка ротации
- **[BuildKit](Dockerfile/dockerfile_buildkit.md)** — кеширование, секреты, GC
- **[Prometheus Integration](Docker_metrics/docker_prometheus_integration.md)** — метрики Docker Engine
- **[Сетевые драйверы](Docker_network/docker_network.md)** — bridge, host, overlay, адресация
- **[Alternative Runtimes](alternative_runtimes_and_tools.md)** — kata, gVisor, sysbox
- **[Обзор Docker](docker_overview.md)** — архитектура Engine, containerd, moby#53388
- **[Реестры](docker_registries.md)** — registry-mirrors, insecure-registries

**Типичные ошибки:**
- Забыть `systemctl restart docker` после изменения daemon.json (для не-SIGHUP опций)
- Использовать булево `true` вместо строки `"true"` в `compress`
- `max-file` без `max-size` — ротация не работает
- `iptables: false` — ломает port publishing для всех контейнеров
- Забыть `data-root` при установке — данные на системном разделе без бэкапа
- Задать `hosts` в daemon.json на Debian/Ubuntu без systemd drop-in — демон не стартует
