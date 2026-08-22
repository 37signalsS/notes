# Docker daemon.json — полный референс

## Определения

**daemon.json** — файл конфигурации Docker Engine, определяющий глобальные параметры демона: драйвер хранения, логирования, сетевые настройки, политики безопасности и адреса сервисов. Расположение: `/etc/docker/daemon.json` (Linux, systemd) или `~/.docker/daemon.json` (Docker Desktop, rootless mode).

**Приоритет конфигурации** — иерархия перекрытия настроек Docker. Настройки применяются в порядке возрастания приоритета: `daemon.json` < флаги запуска `dockerd` < флаги контейнера `docker run` < директивы Compose. При конфликтах побеждает наиболее специфичный уровень.

**Docker Engine** — демон `dockerd`, отвечающий за управление образами, контейнерами, сетями и хранилищами. Конфигурация демона через `daemon.json` определяет поведение всех операций Docker на хосте.

**Storage Driver** — подсистема управления файловой системой контейнеров. Отвечает за хранение слоёв образов (image layers), файловую систему контейнера (container layer) и.volume data. Дефолтный драйвер — `overlay2`, реализующий union mount через OverlayFS ядра Linux.

**Logging Driver** — подсистема перехвата потоков `stdout` и `stderr` контейнера и маршрутизации логов в указанное хранилище (локальные файлы, системный журнал, удалённый сервис). Дефолтный драйвер — `json-file`.

**BuildKit** — современный движок сборки образов Docker, заменивший классический сборщик. Поддерживает параллельную сборку, кеширование с糒.mount, секреты и экспериментальные функции через `experimental: true`.

## Базовые концепции

### Архитектура конфигурации

Docker Engine считывает `daemon.json` при запуске демона. Файл содержит JSON-объект с ключами, сгруппированными по функциональным областям. Изменения вступают в силу после перезапуска демона:

```bash
sudo systemctl restart docker
```

Текущая конфигурация отображается через:

```bash
docker info
docker info --format '{{.LoggingDriver}}'
docker info --format '{{.DockerRootDir}}'
```

### Storage Driver — драйвер хранения

Docker поддерживает несколько файловых систем для хранения данных. Выбор зависит от ядра хоста и требований производительности:

| Драйвер | Описание | Ядро |
|---------|----------|------|
| `overlay2` | Рекомендуемый. Union mount через OverlayFS. | ≥3.18 |
| `fuse-overlayfs` | FUSE-based OverlayFS для rootless mode. | ≥4.18 |
| `btrfs` | Нативная поддержка Btrfs. | ≥3.7 |
| `zfs` | Нативная поддержка ZFS. | ≥2.6.37 |
| `vfs` | Тестовый. Каждый слой — полная копия. Нет union mount. |любое |

`overlay2` работает путём наложения директорий: нижний слой (read-only) + верхний слой (read-write) = объединённая файловая система контейнера. При записи файлов в контейнер происходит copy-on-write: файл копируется из нижнего слоя в верхний перед модификацией.

Для rootless Docker на ядрах <5.11 используется `fuse-overlayfs`, так как нативный OverlayFS требует привилегий `CAP_SYS_ADMIN`.

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

### Сетевые настройки демона

Docker создаёт и управляет сетевыми интерфейсами на хосте. Ключевые параметры:

- **bridge** — виртуальный мост `docker0`, обеспечивающий связь контейнеров через NAT
- **DNS** — встроенный DNS-сервер `127.0.0.11` для именованной связи контейнеров
- **iptables** — Docker управляет правилами фильтрации и трансляции адресов

При `icc: false` (Inter-Container Communication) контейнеры в одной bridge-сети не могут общаться напрямую —都需要 явного подключения через именованные сети или `--link`.

### Безопасность демона

Конфигурация безопасности определяет уровень изоляции контейнеров:

- **User Namespaces** (`userns-remap`) — маппинг UID: root в контейнере ≠ root на хосте
- **no-new-privileges** — запрет на получение привилегий через setuid/setgid бинарники
- **live-restore** — сохранение контейнеров при перезапуске демона
- **icc: false** — изоляция контейнеров друг от друга

### BuildKit — движок сборки

BuildKit — дефолтный движок сборки с Docker 23.0+. Поддерживает:

- Параллельную сборку слоёв
- Кеширование через `--mount=type=cache`
- Секреты через `--mount=type=secret`
- Garbage Collection кеша через `builder.gc.*`

Containerd Snapshotter (Docker 25+) — новый image store для multi-platform builds, заменяющий классический storage driver для хранения образов.

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

- Стандартный MTU Ethernet = 1500 байт
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
# Выделение диапазонов UID/GID
sudo usermod --add-subuids 100000-165536 --add-subgids 100000-165536 dockremap
```

```json
{
  "userns-remap": "default"
}
```

Маппинг работает по формуле: `host_uid = container_uid + base_id`

При `dockremap:100000:65536`:
- UID 0 (root) в контейнере → UID 100000 на хосте
- UID 1000 в контейнере → UID 101000 на хосте

**Проблема Bind Mount vs Volume:**
- Bind mount (`/data:/data`): файлы на хосте принадлежат UID 1000, контейнер (UID 0 → 100000) не может писать
- Named volume: Docker автоматически устанавливает корректные права

Решения для bind mount:
| Способ | Проблема |
|--------|----------|
| `chown 100000:100000 /data` | UID может не существовать, хрупко при смене subuid |
| `chmod 777` | Дыра в безопасности |
| `:idmap` (Docker 25+) | Требует XFS с reflink, ядро ≥5.12 |

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

Альтернатива — SSH-туннель (рекомендуется):
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
- `features.containerd-snapshotter` — новый image store для multi-platform builds (Docker 25+)
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
  "experimental": true,
  "max-concurrent-downloads": 6,
  "max-concurrent-uploads": 3,
  "debug": true
}
```

- `metrics-addr` — адрес экспортёра метрик Docker Engine (порт 9323)
- `experimental` — включение BuildKit build stats и containerd internals
- `max-concurrent-downloads` — дефолт: 3; увеличение ускоряет `docker pull` больших образов
- `max-concurrent-uploads` — дефолт: 5; уменьшение снижает нагрузку на сеть при push
- `debug` — расширенное логирование daemon (для troubleshooting, не для прода)

Ссылка: [Prometheus Integration](Docker_metrics/docker_prometheus_integration.md)

### 11. Production-конфигурация

Полный пример production-ready `daemon.json`:

```json
{
  "storage-driver": "overlay2",
  "data-root": "/mnt/docker-data",

  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5",
    "compress": "true",
    "mode": "non-blocking",
    "max-buffer-size": "8m"
  },

  "dns": ["8.8.8.8", "1.1.1.1"],
  "mtu": 1500,

  "icc": false,
  "userland-proxy": false,
  "live-restore": true,
  "no-new-privileges": true,

  "features": {
    "buildkit": true
  },

  "metrics-addr": "0.0.0.0:9323",
  "experimental": true,

  "max-concurrent-downloads": 6,
  "max-concurrent-uploads": 3,

  "builder": {
    "gc": {
      "enabled": true,
      "defaultKeepStorage": "20GB"
    }
  }
}
```

### 12. Альтернативные runtimes

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

## Дополнительная информация

**Диагностика текущей конфигурации:**
```bash
# Все настройки демона
docker info

# Конкретные параметры
docker info --format '{{.LoggingDriver}}'
docker info --format '{{.StorageDriver}}'
docker info --format '{{.DockerRootDir}}'

# Конфигурация конкретного контейнера
docker inspect --format '{{.HostConfig.LoggingConfig.Type}}' <container>
docker inspect --format '{{.HostConfig.Memory}}' <container>
```

**Перезапуск после изменений:**
```bash
sudo systemctl restart docker
# Проверка
docker info | head -30
```

**Валидация JSON:**
```bash
python3 -c "import json; json.load(open('/etc/docker/daemon.json'))"
```

**Связанные документы:**
- **[Защита хоста и демона](Docker_security/host_daemon_hardening.md)** — CIS Benchmark,安全 настройки, sysctl
- **[Укрепление безопасности контейнеров](Docker_security/container_hardening.md)** — настройки внутри контейнера
- **[Обзор логирования](Docker_logs/docker_logging_drivers_overview.md)** — все драйверы логов
- **[Ротация логов](Docker_logs/docker_log_rotation.md)** — настройка ротации
- **[BuildKit](Dockerfile/dockerfile_buildkit.md)** — кеширование, секреты, GC
- **[Prometheus Integration](Docker_metrics/docker_prometheus_integration.md)** — метрики Docker Engine
- **[Сетевые драйверы](Docker_network/docker_network.md)** — bridge, host, overlay
- **[Alternative Runtimes](alternative_runtimes_and_tools.md)** — kata, gVisor, sysbox

**Типичные ошибки:**
- Забыть `systemctl restart docker` после изменения daemon.json
- Использовать булево `true` вместо строки `"true"` в `compress`
- `max-file` без `max-size` — ротация не работает
- `iptables: false` — ломает port publishing для всех контейнеров
- Забыть `data-root` при установке — данные на системном разделе без бэкапа
