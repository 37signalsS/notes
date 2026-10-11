# Docker: Драйверы томов (volume drivers)

**Актуально для:** Docker 24.x–29.x

## Определения

- **Volume driver** — механизм (встроенный или плагин), определяющий, где и как хранятся данные именованного тома. По умолчанию — драйвер `local`.
- **local driver** — встроенный драйвер Docker. Хранит данные в `/var/lib/docker/volumes/<name>/_data` и умеет монтировать через опции `type`, `device`, `o` любую файловую систему, которую монтирует ядро хоста (NFS, CIFS, tmpfs, btrfs и т.д.).
- **Named bind mount** — том драйвера `local` с опциями `type=none, o=bind, device=<абсолютный путь>`: named volume, данные которого лежат в произвольной директории хоста. Нативная замена плагину local-persist.
- **Volume plugin** — внешний компонент, реализующий API `VolumeDriver` (Create/Remove/Mount/Path/Get/List). **Managed** — устанавливается через `docker plugin install` как образ; **unmanaged** — демон-процесс с Unix-сокетом, который демон Docker обнаруживает сам.
- **Cluster volume** — том Swarm с атрибутами доступа (`--scope`, `--sharing`, `--type`), API 1.42+ (Docker 23.0+).
- **CSI (Container Storage Interface)** — стандарт Kubernetes для подключения хранилищ. Для standalone Docker **не применим** — используйте volume plugins или опции local driver.

## Предварительные требования

- **Docker Engine** 24.x–29.x.
- **Доступ к Docker socket**: `/var/run/docker.sock` или `DOCKER_HOST`.
- **Для NFS/CIFS**: сетевой доступ к серверу; на хосте — поддержка протокола ядром (модули `nfs`, `cifs`; пакет `cifs-utils` для CIFS).
- **Для NFS/CIFS и managed-плагинов** — rootful-демон: ядро не разрешает монтирование NFS внутри user namespace, а managed-плагины в rootless-режиме имеют ограничения.
- **Для плагинов**: доступ к Docker Hub или локальному реестру плагинов.
- **Для квот (`size`)**: `/var/lib/docker` на XFS с включёнными project quotas (`pquota`).

## Базовые концепции

### 1. Как работает local driver

Механизм (исходники moby: `daemon/volume/local/local.go`, `local_unix.go`):

```
docker volume create --opt type=nfs --opt device=:/srv/share --opt o=addr=10.0.0.10,rw share
        ↓
[Create] валидация имени и опций → mkdir /var/lib/docker/volumes/share (0701)
         и _data (0755) → сохранение опций в opts.json (0600)
         МОНТИРОВАНИЯ НЕ ПРОИСХОДИТ
        ↓
docker run --mount type=volume,source=share,target=/data ...
        ↓
[Mount] mount(2) device → _data с опциями o= (при старте первого контейнера, refcount)
        ↓
[Unmount] размонтирование при остановке последнего контейнера (refcount → 0)
```

- Монтирование **ленивое**: `docker volume create` почти ничего не проверяет — недоступный NFS-сервер, неверный пароль CIFS и несуществующий `device` surfaced только при первом `docker run` (ошибка `error while mounting volume ... failed to mount local volume`).
- Монтирование **счётчиковое** (refcount): том монтируется один раз при старте первого контейнера и размонтируется при остановке последнего. При старте демона проверяется, не остался ли `_data` смонтированным (`restoreIfMounted`, live-restore).
- `docker volume rm` отказывает, пока том смонтирован: `volume has active mounts`.
- При удалении локальный driver проверяет, что путь данных остаётся внутри `/var/lib/docker/volumes/` (`unable to remove a directory outside of the local volume root`).

### 2. Опции local driver

Драйвер `local` принимает **только четыре опции** (любая другая → `invalid option`):

| Опция | Назначение | Обязательные спутники |
| :--- | :--- | :--- |
| `type` | Тип ФС для `mount -t`: `nfs`, `cifs`, `tmpfs`, `btrfs`, `none`... | `device` |
| `device` | Источник монтирования: `:/path` (NFS), `//server/share` (CIFS), `/dev/sda2` (btrfs), `/abs/path` (bind) | `type` |
| `o` | Опции монтирования (как в `/etc/fstab`): `addr=`, `username=`, `file_mode=` и т.д.; список через запятую | `type` + `device` |
| `size` | Квота на объём тома (XFS project quota), например `size=10G` | — |

- Docker документирует `nfs`, `cifs`, `tmpfs`, `btrfs`; остальное (например, `ceph`) работает, если ядро хоста умеет `mount -t <type>`, но Docker это не тестирует.
- **Windows**: local driver не принимает опций. **Docker Desktop** (macOS/Windows): опции работают (демон в Linux VM), но `device` для bind должен существовать и входить в список shared paths (File Sharing).
- Для NFS: `device` начинается с двоеточия (`:/path`) — хост уже указан в `o=addr=`. Для CIFS: порт нельзя указывать в `device` — только в `o=port=`.

### 3. Плагины

```bash
# Установка managed-плагина (пример — rclone, активно поддерживаемый)
docker plugin install rclone/docker-volume-rclone --alias rclone

# Список установленных плагинов
docker plugin ls
# → ID        NAME      DESCRIPTION   ENABLED

# Настройка опций плагина, включение/отключение, удаление
docker plugin set rclone config=/path/to/rclone.conf
docker plugin disable rclone
docker plugin rm rclone
```

- Плагин реализует API `VolumeDriver`: `Create`, `Remove`, `Mount` (вызывается при старте каждого контейнера), `Path`, `Get`, `List`; `Capabilities` опционален. `Scope`: `local` (том на каждом хосте) или `global` (том создаётся один раз для кластера).
- Плагинам запрещено писать данные в `/var/lib/docker/` (включая `/var/lib/docker/volumes/`).
- Если плагин требует опций, монтировать том нужно через `--mount` (не `-v`).
- **Unmanaged-плагин** — процесс с сокетом в `/run/docker/plugins/<name>.sock`; так работает, например, `rclone serve docker` в rootless-режиме.

### 4. Swarm

В сервисах драйвер и опции задаются в `--mount`:

```bash
docker service create -d \
  --name nfs-service \
  --mount 'type=volume,source=nfsvolume,target=/app,volume-driver=local,volume-opt=type=nfs,volume-opt=device=:/var/docker-nfs,volume-opt=o=addr=10.0.0.10' \
  nginx:latest
```

- Если опция содержит список через запятую (как `o=`), её нужно экранировать: обернуть значение в двойные кавычки внутри одинарных кавычек всего `--mount`:
  `"volume-opt=o=addr=10.0.0.10,rw,nfsvers=4,async"`.
- Тома local driver в Swarm — **per-node** (`Scope: local`): каждый узел монтирует свою копию. Для общего хранилища используйте плагин с `Scope: global` или cluster volumes.
- **Cluster volumes** (API 1.42+, Docker 23.0+): `docker volume create --scope multi --sharing all --type mount cluster-vol`, где `--sharing` (`none`/`readonly`/`onewriter`/`all`), `--type` (`mount`/`block`), `--availability` (`active`/`pause`/`drain`), `--limit-bytes`, `--required-bytes`, `--group`, `--secret`, `--topology-required`, `--topology-preferred`. Флаги скрыты в `--help`, пока демон не инициализирован как Swarm-менеджер (`docker swarm init`). Список: `docker volume ls --cluster` (колонки `NAME GROUP DRIVER AVAILABILITY STATUS`); изменение доступности: `docker volume update --availability drain <name>` (обязательно перед удалением cluster-тома). Подробно — **[Тома в Docker Swarm](../../Docker_swarm/swarm_volumes.md)**.

## Практические сценарии

### Сценарий 1: NFS-том через local driver

```bash
# Создание тома, монтирующего NFS-шару
docker volume create \
  --driver local \
  --opt type=nfs \
  --opt o=addr=192.168.1.100,rw,nfsvers=4 \
  --opt device=:/srv/nfs/share \
  nfs-share

# Проверка
docker volume inspect nfs-share
# → [
# →     {
# →         "Driver": "local",
# →         "Options": {
# →             "type": "nfs",
# →             "o": "addr=192.168.1.100,rw,nfsvers=4",
# →             "device": ":/srv/nfs/share"
# →         }
# →     }
# → ]

# Использование в контейнере
docker run --rm \
  --mount type=volume,source=nfs-share,target=/data \
  alpine ls /data
```

- `nfsvers=4` фиксирует протокол (иначе клиент может согласовать downgrade до NFSv3).
- Если вместо IP указано hostname в `addr=`, демон резолвит его в IP в момент монтирования.
- Для production добавьте `hard,timeo=600,retrans=2` (см. Лучшие практики).

### Сценарий 2: CIFS/SMB-том через local driver

```bash
# Создание тома с SMB-шарой
docker volume create \
  --driver local \
  --opt type=cifs \
  --opt device=//192.168.1.100/share \
  --opt o=addr=192.168.1.100,username=backup,password=secret,file_mode=0777,dir_mode=0777 \
  cifs-share

# Использование
docker run --rm \
  --mount type=volume,source=cifs-share,target=/backup \
  alpine sh -c "df -h /backup"
# → //192.168.1.100/share   500G  120G  380G  24% /backup
```

> **Важно:** пароль в опциях виден в `docker volume inspect` и в истории команд. Для production используйте credentials-файл: `o=addr=192.168.1.100,credentials=/etc/docker-smb.creds,file_mode=0777,dir_mode=0777` (файл root-owned, 0600). `addr` обязателен, если адрес — hostname, а не IP. Порт указывается в `o=port=445`, не в `device`.

### Сценарий 3: tmpfs-том через local driver

```bash
# Том в RAM (временные данные)
docker volume create \
  --driver local \
  --opt type=tmpfs \
  --opt device=tmpfs \
  --opt o=size=100m,uid=1000 \
  tmp-vol

docker run --rm \
  --mount type=volume,source=tmp-vol,target=/scratch \
  alpine df -h /scratch
# → tmpfs          100M     0  100M   0% /scratch
```

### Сценарий 4: named bind mount — том в произвольной директории хоста

```bash
# Директория на хосте должна существовать
mkdir -p /data/images

# Том, данные которого лежат в /data/images
docker volume create \
  --driver local \
  --opt type=none \
  --opt o=bind \
  --opt device=/data/images \
  images

# Проверка: запись из контейнера видна на хосте напрямую
docker run --rm --mount type=volume,source=images,target=/data alpine sh -c "echo test > /data/probe.txt"
cat /data/images/probe.txt
# → test
```

- Это нативная замена плагину local-persist (сценарий 8): тот же результат без внешнего плагина.
- Если `device` не существует, `docker volume create` **успешно отработает**, а ошибка (`no such file or directory`) возникнет при первом `docker run` — создавайте путь заранее.
- На Docker Desktop (macOS/Windows) путь должен входить в список shared paths (Settings → Resources → File Sharing); хостовые пути транслируются в VM (`/host_mnt/...`).

### Сценарий 5: квота на размер тома (size)

```bash
# Требуется: /var/lib/docker на XFS с pquota
docker volume create --opt size=10G app-data
```

- Квота применяется как XFS project quota при монтировании тома.
- Без поддержки pquota создание откажет сразу: `Error response from daemon: create app-data: quota size requested but no quota support`.

### Сценарий 6: плагин rclone (SFTP-том)

```bash
# Установка активно поддерживаемого плагина
docker plugin install rclone/docker-volume-rclone --alias rclone

# Создание SFTP-тома
docker volume create \
  -d rclone \
  --name rclonevolume \
  -o type=sftp \
  -o path=remote \
  -o sftp-host=1.2.3.4 \
  -o sftp-user=user \
  -o "sftp-password=$(cat file_containing_password_for_remote_host)"
```

### Сценарий 7: тома с драйверами в Docker Compose

```yaml
volumes:
  nfs-data:
    driver: local
    driver_opts:
      type: nfs
      o: "addr=10.40.0.199,nolock,soft,rw"
      device: ":/docker/example"
  # Named bind mount: стабильное имя тома + фиксированный путь на хосте
  app-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /srv/app-data # must be the absolute host path and already exist
```

- Если драйвер недоступен, Compose возвращает ошибку и не деплоит приложение.

### Сценарий 8: local-persist (legacy)

> **Статус:** проект **архивирован** (MatchbookLab/local-persist, не развивается с 2025; сам мейнтейнер рекомендует нативный `type=none, o=bind` — сценарий 4). Используйте только для поддержки существующих развёртываний.

```bash
# Историческая установка (бинарь + systemd на хосте)
curl -fsSL https://raw.githubusercontent.com/MatchbookLab/local-persist/master/scripts/install.sh | sudo bash

# Создание тома с фиксированной точкой на хосте
docker volume create \
  --driver local-persist \
  --opt mountpoint=/data/images \
  --name=images
```

- Нативно не работает на macOS/Windows (только в контейнере); не поддерживает Swarm; не делает SELinux-релейбл `:Z`.

### Сценарий 9: sshfs-плагин (legacy)

> **Статус:** проект **архивирован** (vieux/docker-volume-sshfs, не развивается). Требует `CAP_SYS_ADMIN`, `/dev/fuse` и host network; в rootless-режиме несовместим.

```bash
# Установка sshfs-плагина
docker plugin install --grant-all-permissions vieux/sshfs

# Создание sshfs-тома
docker volume create \
  --driver sshfs \
  --opt sshcmd=user@192.168.1.50:/home/user/data \
  --opt password=secret \
  ssh-vol
```

## Устранение неполадок

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`plugin not found`** | Плагин не установлен или сокет не в `/run/docker/plugins/` | `docker plugin install <name>`; проверьте `docker plugin ls` |
| **`error while mounting volume ... failed to mount local volume: mount ...: operation not supported`** (при `docker run`) | Ядро хоста не поддерживает ФС (нет модуля `nfs`/`cifs`) или недоступен сервер | `modprobe nfs` / установите `cifs-utils`; проверьте `mount -t <type>` вручную; проверьте сеть и адрес в `o=addr=` |
| **`no such file or directory` при монтировании bind-тома** | `device` не существует на хосте (или не в shared paths на Docker Desktop) | Создайте директорию; проверьте File Sharing на Docker Desktop |
| **`permission denied` при доступе к CIFS** | Неверные права или опции | Добавьте `file_mode=0777,dir_mode=0777` в `o`; проверьте `username`/`password` или credentials-файл |
| **`no such device`** | Неверный `device` (формат `:/path` для NFS, `//server/share` для CIFS) | Проверьте синтаксис `device`; для NFS — ведущее двоеточие |
| **`invalid option: "<opt>"`** | Опция не из списка `type`/`o`/`device`/`size` | Уберите опцию; произвольные опции local driver не принимает |
| **`missing required option: "<opt>"`** | Нарушены зависимости: `o` требует `type`+`device`, `type` требует `device` | Добавьте недостающие опции |
| **`port not allowed in CIFS device URL, include 'port' in 'o='`** | Порт указан в `device` (`//host:445/share`) | Перенесите порт в `o=port=445` |
| **`quota size requested but no quota support`** | `/var/lib/docker` не на XFS с pquota | Включите pquota на XFS-разделе или уберите `size` |
| **`volume has active mounts`** при `docker volume rm` | Том смонтирован работающим контейнером | Остановите/удалите контейнеры, использующие том (`docker ps -a --filter volume=<name>`) |
| **`no such volume`** | Том не существует (или удалён) | `docker volume ls`; имя тома ≥2 символов из `[a-zA-Z0-9][a-zA-Z0-9_.-]` |
| **Том пуст после перезагрузки хоста** | NFS/CIFS не примонтирован автоматически (сервер недоступен в момент старта Docker) | Настройте autofs или systemd mount с `_netdev` |
| **`docker volume create` с драйвером не работает в rootless** | Managed-плагины и NFS/CIFS требуют rootful-демон | Запускайте плагины и сетевые ФС в rootful-режиме; unmanaged-плагин — сокет в `$XDG_RUNTIME_DIR/docker/plugins/` |

## Валидация результатов

```bash
# Проверка драйвера и фильтров тома
docker volume create --label env=prod app-data
docker volume ls --filter driver=local
# → DRIVER              VOLUME NAME
# → local               app-data
docker volume ls --filter label=env=prod
# → local               app-data

# Полный inspect (поля: CreatedAt, Driver, Labels, Mountpoint, Name, Options, Scope)
docker volume inspect app-data
# → [
# →     {
# →         "CreatedAt": "2026-10-05T17:31:27Z",
# →         "Driver": "local",
# →         "Labels": { "env": "prod" },
# →         "Mountpoint": "/var/lib/docker/volumes/app-data/_data",
# →         "Name": "app-data",
# →         "Options": null,
# →         "Scope": "local"
# →     }
# → ]

# Проверка опций (Go-формат)
docker volume inspect nfs-share --format '{{.Driver}} {{.Options}}'
# → local map[type:nfs o:addr=192.168.1.100,rw device=:/srv/nfs/share]

# Проверка монтирования внутри контейнера
docker run --rm --mount type=volume,source=nfs-share,target=/data alpine df -h /data
# → 192.168.1.100:/srv/nfs/share  500G  120G  380G  24% /data

# Проверка, что том с опциями не удаляется prune (даже dangling)
docker volume prune -f
# → Total reclaimed space: 0B
```

Проверено на Docker Desktop 4.94.0 (macOS), Engine 29.8.2, overlayfs.

## Граничные случаи

### Перезагрузка хоста

NFS/CIFS-тома монтируются демоном Docker при первом использовании (старт контейнера), а не при старте демона. Если сетевой сервер недоступен в момент старта контейнера, контейнер не запустится (`failed to mount local volume`). Для production используйте autofs или systemd-юниты с `_netdev`.

### Производительность

NFS/CIFS-тома медленнее локальных: каждая операция идёт по сети. Для write-heavy нагрузок (БД) используйте локальные тома или блочные устройства. `docker system df -v` **не показывает** размер томов с опциями монтирования (намеренно пропускаются в `LocalVolumesSize`) — измеряйте `df -h` на хосте или на сервере NFS/CIFS.

### Rootless Docker

- NFS/CIFS через local driver **не работают** в rootless: ядро не разрешает `mount -t nfs/cifs` внутри user namespace (нужен CAP_SYS_ADMIN в initial namespace).
- Managed-плагины (`docker plugin install`) в rootless имеют ограничения: плагины, запрашивающие `CAP_SYS_ADMIN`/host network (как sshfs), несовместимы; часть проблем с монтированием в userns исправлена в 23.0.3+/25.0.3+.
- Unmanaged-плагин (собственный сокет) может работать в rootless, если сокет лежит в `$XDG_RUNTIME_DIR/docker/plugins/`.
- Хранилище rootless-демона: только `overlay2` (kernel 5.11+), `fuse-overlayfs`, `btrfs` (с `user_subvol_rm_allowed`), `vfs`; `data-root` на NFS не поддерживается.

### Данные при удалении тома и prune

- `docker volume rm` удаляет метаданные тома. Для local driver без опций данные в `/var/lib/docker/volumes/<name>/_data` удаляются; для NFS/CIFS — шара размонтируется, данные остаются на сервере; для bind — монтирование снимается, данные на хосте остаются.
- С Docker 23.0 (API 1.42) `docker volume prune` по умолчанию удаляет **только anonymous-тома**; для named нужен `-a`/`--all`. Томы с опциями монтирования (NFS, CIFS, bind) **не удаляются prune никогда** — даже с `-a` (намеренное поведение, moby#40152: опции означают, что данные управляются вручную). Подробно — **[Очистка и GC](./cleanup_gc_strategies.md)**.

### Docker Desktop

Local driver с опциями работает (демон в Linux VM), но bind-`device` должен существовать и входить в shared paths; хостовые пути видны в VM как `/host_mnt/...`. NFS-тома монтируются внутри VM — адрес NFS-сервера должен быть доступен из VM, а не только с macOS-хоста.

### Live-restore

При `live-restore` демон при старте проверяет, остался ли `_data` смонтированным (`restoreIfMounted`), и восстанавливает состояние без повторного монтирования.

## Лучшие практики

- **Не храните секреты в `o=`**: пароль виден в `docker volume inspect` и в shell history. Для CIFS — credentials-файл (root-owned, 0600); для плагинов — передача через файл или `docker plugin set`.
- **Маркируйте тома `--label`**: метки работают в фильтрах `docker volume ls --filter label=...` и `docker volume prune --filter label=...` (единственный поддерживаемый фильтр prune кроме `dangling`).
- **NFS для production**: `hard` (по умолчанию — бесконечные повторы), `timeo=600`, `retrans=2`, `nfsvers=4`. `soft` возвращает ошибки приложению после таймаута — риск потери/повреждения данных при записи; для БД не используйте.
- **Перед prune**: `docker volume ls -f dangling=true` + `docker ps -a --filter volume=<name>` — проверьте, что том не используется «зависшим» контейнером.
- **Миграция между драйверами**: драйвер тома нельзя изменить на месте — создайте новый том, перенесите данные (`docker cp` или `rsync` через временный контейнер), пересоздайте контейнер на новом томе.
- **Мониторинг**: `docker system df -v` (кроме томов с опциями — их размер смотрите на хосте), алерты на заполнение раздела `/var/lib/docker` и NFS/CIFS-серверов.

## Дополнительная информация

### Связанные документы

- **[Тома (Volumes)](./docker_volumes.md)** — типы монтирования, управление томами.
- **[Тома в Docker Swarm](../../Docker_swarm/swarm_volumes.md)** — драйверы томов в контексте Swarm (cluster volumes, NFS, placement).
- **[Очистка и GC](./cleanup_gc_strategies.md)** — поведение `volume prune`/`system prune --volumes`.
- **[Шифрование томов](./volume_encryption.md)** — LUKS, fscrypt для данных на покое.
- **[Драйвер хранения OverlayFS](./docker_overlayfs.md)** — файловая система контейнера (не путать с драйверами томов).

### local driver vs плагин vs CSI

| Критерий | local driver | Volume plugin | CSI |
| :--- | :--- | :--- | :--- |
| **Установка** | Встроен | `docker plugin install` или unmanaged-сокет | Только Kubernetes |
| **NFS/CIFS** | Через опции `type`/`device`/`o` | Зависит от плагина | Через CSI driver |
| **Произвольный путь на хосте** | Через `type=none, o=bind, device=<path>` | local-persist (legacy) — да | Нет |
| **Квота на том** | `size` (XFS pquota) | Зависит от плагина | Через StorageClass |
| **Применение** | Standalone Docker, Swarm (per-node) | Standalone Docker, Swarm (`Scope: global`) | Kubernetes |
