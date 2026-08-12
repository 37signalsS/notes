# Podman: Хранилище и работа с файловой системой

> Актуально для: Podman 6.x (стабильная ветка 6.0.x).

## Определения

**Файловая система контейнера (Copy-on-Write)** — комбинированная структура, состоящая из неизменяемых слоев образа и верхнего записываемого слоя контейнера. Реализуется через драйверы файловых систем (обычно **OverlayFS**). Данные, записанные в записываемый слой, существуют только вместе с контейнером и удаляются вместе с ним.

**Bind Mount (Монтирование привязкой)** — прямое проброс директории или файла с хоста в контейнер. Изменения синхронизируются в реальном времени; Podman не управляет жизненным циклом таких данных.

**Named Volume (Именованный том)** — изолированное хранилище под управлением Podman. Идеально подходит для баз данных и постоянных данных, так как Podman берет на себя управление жизненным циклом и правами доступа.

**Anonymous Volume (Анонимный том)** — том без явного имени (задается только точка монтирования в контейнере, например `-v /var/lib/data`). Получает случайное имя и удаляется вместе с контейнером при его удалении (если не переиспользован другим контейнером).

**tmpfs** — временное хранилище в оперативной памяти (RAM), не записываемое на диск. Данные теряются при остановке контейнера.

**Storage Driver** — низкоуровневый компонент, отвечающий за создание и управление слоями образов и контейнеров (например, `overlay`, `vfs`, `btrfs`, `zfs`).

**Graph Root** — каталог постоянного хранилища, в котором находятся образы, контейнеры и тома.

**User Namespaces (ID Mapping)** — механизм сопоставления UID/GID хоста с идентификаторами внутри контейнера, критически важный для безопасности rootless-режима.

**Volume Driver** — драйвер, определяющий, где и как хранятся данные именованного тома (`local` — локальный каталог; `image` — образ; сторонние плагины).

---

## Основные концепции

### Конфигурация хранилища (`storage.conf`)

Глобальные настройки хранилища определяются в файле `storage.conf` (общий формат всех инструментов семейства containers — Podman, Buildah, Skopeo).

- **Rootful**: `/etc/containers/storage.conf`
- **Rootless**: `~/.config/containers/storage.conf`

**Основные параметры:**

| Параметр | Назначение |
| :--- | :--- |
| `driver` | Тип драйвера (по умолчанию `overlay`). |
| `runroot` | Путь для временных данных (монтирования слоев, точки монтирования). |
| `graphroot` | Путь для постоянных данных (образы, контейнеры, тома). |
| `mount_program` | Исполняемый файл для монтирования (например, `fuse-overlayfs`), задается в секции `[storage.options.overlay]`. |
| `additionalimagestores` | Дополнительные read-only каталоги образов (общие хранилища для нескольких хостов). |
| `remap-uids` / `remap-gids` | Принудительный маппинг UID/GID на уровне хранилища (rootful-режим, без user namespaces). |

### Бэкенд метаданных (`containers.conf`)

**`database_backend`** — параметр конфигурации, задается в **`containers.conf`** (секция `[engine]`), а не в `storage.conf`.

- **Rootful**: `/etc/containers/containers.conf`
- **Rootless**: `~/.config/containers/containers.conf`

```toml
[engine]
database_backend = "sqlite"
```

История бэкенда:
- До Podman 4.8/5.x использовался **BoltDB** (файл `bolt_state.db`).
- Начиная с Podman 4.8 **SQLite** стал бэкендом по умолчанию для новых установок.
- **В Podman 6.0 BoltDB полностью удален**, SQLite — единственный поддерживаемый бэкенд. При старте 6.0 существующая база BoltDB мигрируется автоматически (в 5.8 появилась автоконвертация при загрузке). Для принудительной конвертации: `podman system migrate --migrate-db`.
- Проверка активного бэкенда:

```bash
podman info --format '{{.Host.DatabaseBackend}}'
# → sqlite
```

**Важно:** при переходе со старых версий (до 5.8) с базой BoltDB сначала обновитесь до 5.8, дайте автоконвертации отработать, затем обновляйтесь до 6.0. `podman system reset` удаляет все данные (включая тома) и не является миграцией.

### Расположение данных по умолчанию

| Режим запуска | Graph Root | Тома | Run Root |
| :--- | :--- | :--- | :--- |
| **Rootless** | `~/.local/share/containers/storage` | `~/.local/share/containers/storage/volumes/<имя>/_data` | `/run/user/$(id -u)/containers` |
| **Rootful** | `/var/lib/containers/storage` | `/var/lib/containers/storage/volumes/<имя>/_data` | `/var/run/containers/storage` |

Путь к каталогу томов можно переопределить флагом `podman --volumepath <path>` либо параметром `volumes` в `containers.conf` (`[engine]`).

### Драйверы файловых систем

1. **OverlayFS** — стандарт индустрии. Требует поддержки со стороны ядра ОС.
   - Rootful: нативное монтирование overlay (нижние слои — слои образа, верхний слой — записываемый слой контейнера).
   - Rootless: на ядрах Linux **5.11+** доступен нативный непривилегированный overlay; на более старых ядрах и при хранении на NFS используется **fuse-overlayfs** (через FUSE, с накладными расходами). Переход между режимами требует `podman system reset` (признак — файл `$STORAGE/overlay/.has-mount-program`).
2. **VFS** — самый простой драйвер, не поддерживающий слои (копирует всё содержимое при каждом изменении). Используется как резервный вариант при отсутствии поддержки Overlay.
3. **btrfs / zfs** — драйверы для соответствующих файловых систем (rootful). Позволяют использовать снапшоты ФС для слоев.

**Ограничение rootless-режима:** поддерживаются только драйверы `overlay` (в т.ч. через `fuse-overlayfs`) и `vfs`. Нативный overlay не работает на сетевых ФС (NFS).

### Типы монтирований

| Тип | Синтаксис `-v` | Назначение | Персистентность |
| :--- | :--- | :--- | :--- |
| **Named Volume** | `-v my-data:/var/lib/data` | Данные приложений (БД, статика) | Да (переживает удаление контейнера) |
| **Anonymous Volume** | `-v /var/lib/data` | Временные данные контейнера | Удаляется с контейнером |
| **Bind Mount** | `-v /host/path:/container/path` | Код, конфиги, live-перезагрузка | Да (данные на хосте) |
| **tmpfs** | `-v` не используется; `--tmpfs /cache` или `--mount type=tmpfs` | Кэш, секреты, временные файлы | Нет (RAM) |
| **Image Volume** | `--mount type=image,source=img,target=/path` | Преднаполненные данные из образа | Зависит от опции `rw` |

Полный синтаксис `-v`/`--volume`:

```text
-v [source]:target[:options]
```

Опции монтирования `-v`:

| Опция | Назначение |
| :--- | :--- |
| `ro` | Только чтение. |
| `rw` | Чтение и запись (по умолчанию). |
| `:z` | Переразметка SELinux для совместного использования несколькими контейнерами (метка `container_file_t`). |
| `:Z` | Переразметка SELinux для эксклюзивного использования (уникальная MCS-метка). |
| `:U` | Рекурсивный `chown` источника под UID/GID процесса внутри контейнера. |
| `:idmap` | Использование idmapped-монтирований (сопоставление UID/GID на уровне ядра, без изменения владельца файлов на хосте). |
| `:O` | Overlay-монтирование: исходный каталог read-only, все изменения пишутся в верхний слой и уничтожаются вместе с контейнером. |
| `shared` / `slave` / `private` | Распространение монтирований (bind propagation), в т.ч. с префиксом `r` (рекурсивно). |

**Опции `--mount`** — альтернативный, более явный синтаксис:

```bash
# Named volume, только чтение, chown под пользователя контейнера
podman run -d --mount type=volume,source=pgdata,target=/var/lib/postgresql/data,ro,U nginx

# Bind mount с idmapped-монтированием и явным распространением
podman run -d --mount type=bind,src=/data,dst=/srv,idmap,bind-propagation=rshared nginx

# tmpfs с лимитом размера и правами
podman run -d --mount type=tmpfs,target=/cache,tmpfs-size=512M,tmpfs-mode=1777 nginx

# Монтирование подкаталога из образа (read-only по умолчанию)
podman run -d --mount type=image,source=myapp-data:v1,target=/app/data,subpath=/data,ro=true nginx

# Overlay-монтирование через --mount
podman run -d --mount type=bind,src=/etc/config,dst=/config:O nginx
```

Поддерживаемые типы `--mount`: `bind`, `volume`, `image`, `tmpfs`, `devpts`.

### Драйверы томов и плагины

Podman встроенно поддерживает два драйвера именованных томов:

- **`local`** (по умолчанию) — каталог на диске. С опциями `--opt` может монтировать ФС как том: `type` (тип ФС, аналог `mount -t`), `device` (устройство), `o` (опции монтирования), `[no]copy` (копирование содержимого пути из образа в новый том при первом подключении — `copy` по умолчанию).
- **`image`** — образ как основа тома (overlay). Изменения можно закоммитить как новый слой.

Любой другой драйвер — **volume plugin**. Плагины регистрируются в `containers.conf` (секция `[engine.volume_plugins]`) и запускаются как отдельные процессы (в т.ч. контейнеры).

```toml
[engine.volume_plugins]
nfs = "/run/containers/volume-plugins/nfs.sock"
```

---

## Практические сценарии

### 1. Работа с SELinux (флаги z и Z)

На системах с включенным SELinux (RHEL, Fedora) монтирование без корректных меток приведет к ошибке `Permission Denied`.

- **`:z`**: Переразмечает контент для совместного использования несколькими контейнерами (метка `container_file_t`).
- **`:Z`**: Переразмечает контент для эксклюзивного использования (уникальная MCS-метка).

```bash
# Монтирование с уникальной меткой безопасности
podman run -v /opt/app/data:/data:Z my-db-app
```

### 2. Управление правами в Rootless (флаги U, idmap и keep-id)

Самая частая проблема миграции — несовпадение UID владельца папки на хосте и пользователя внутри контейнера.

- **Флаг `:U`**: Автоматически выполняет `chown` на хосте для приведения папки в соответствие с пользователем контейнера.
- **Флаг `:idmap`**: (Podman 4.3+) Позволяет более гибко настраивать маппинг без физического изменения владельца файлов на хосте, используя idmapped-монтирования ядра. Поддерживает явные диапазоны: `idmap=uids=0-1-10#10-11-10;gids=0-100-10`.
- **`--userns=keep-id`**: Мапирует текущего пользователя хоста на тот же UID внутри контейнера (для каталогов из домашней директории).
- **`podman unshare`**: Вход в user namespace для смены владельца так, как его видит контейнер.

```bash
# Использование автоматического маппинга для прав root внутри контейнера
podman run -v ./web_root:/var/www/html:U nginx

# keep-id: текущий пользователь хоста остаётся собой внутри контейнера
podman run --userns=keep-id -v ./project:/app node:20

# Ручная коррекция владельца через unshare (UID 0 == текущий пользователь хоста)
podman unshare chown -R 0:0 ./data
podman unshare cat /proc/self/uid_map
# → 0       1000          1
# → 1     100000      65536
```

Подробнее: [Rootless режим](./podman_rootless.md).

### 3. Управление томами через CLI

```bash
# Создание именованного тома с меткой
podman volume create --label app=web pgdata

# Создание тома с правами владельца (uid/gid владеют точкой монтирования)
podman volume create --uid 1000 --gid 1000 appdata

# Создание с квотами XFS (только XFS с pquota; size/inodes)
podman volume create --opt o=size=10G,uid=1000 pgdata

# Создание tmpfs-тома (данные в RAM, не на диске)
podman volume create --opt device=tmpfs --opt type=tmpfs --opt o=size=512M myvol

# Создание тома на основе образа (overlay; изменения можно закоммитить)
podman volume create --driver image --opt image=fedora:latest fedoraVol

# Проверка существования тома без вывода (код возврата 0/1)
podman volume exists pgdata && echo "существует"

# Список томов (фильтр по метке)
podman volume ls --filter label=app=web

# Детальная информация: путь на хосте, драйвер, опции, квоты
podman volume inspect pgdata

# Удаление тома (только если не используется контейнером)
podman volume rm pgdata

# Принудительное удаление всех неиспользуемых томов
podman volume rm --force --all

# Удаление неиспользуемых томов по фильтру (оставить используемые)
podman volume prune --filter label!=backup
```

**Важно (Podman 6.0):** `podman volume prune` без аргументов удаляет **только анонимные** неиспользуемые тома (поведение приведено в соответствие с Docker). Для удаления всех неиспользуемых, включая именованные, используйте `--all`:

```bash
# Только анонимные (поведение по умолчанию в 6.0)
podman volume prune

# Все неиспользуемые тома (включая именованные)
podman volume prune --all
```

### 4. Монтирование данных PostgreSQL (Named Volume)

```bash
podman run -d --name my-postgres \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -v pgdata:/var/lib/postgresql/data \
  postgres:16-alpine
```

- Том `pgdata` создастся автоматически, если не существует.
- Содержимое пути из образа (если есть) копируется в новый том при первом подключении (`copy` по умолчанию; отключение — `--opt nocopy` при создании тома).
- Переменная `POSTGRES_PASSWORD` нужна только при первичной инициализации БД — при пересоздании контейнера с существующего тома её можно не задавать.

### 5. Хранение временных файлов (tmpfs)

```bash
# Флаг --tmpfs: кэш Nginx в оперативной памяти
podman run -d --name nginx-cache --tmpfs /var/cache/nginx:size=512M,mode=1777 nginx:latest

# То же через --mount
podman run -d --mount type=tmpfs,target=/var/cache/nginx,tmpfs-size=512M,tmpfs-mode=1777 nginx:latest
```

Данные не попадают на диск и исчезают при остановке контейнера. Важно для секретов (альтернатива bind mount, данные не видны на хосте) и высоконагруженного кэша.

### 6. Монтирование образа как тома (преднаполненные данные)

Подходит для доставки конфигов, статики и справочных данных: образ версионируется тегами и распространяется через реестр.

```bash
# Сборка образа с данными
podman build -t myapp-data:v1 -f Containerfile.data .

# Монтирование read-only (по умолчанию)
podman run -d --name webapp \
  --mount type=image,source=myapp-data:v1,target=/app/data,subpath=/data,ro=true \
  nginx:latest

# Монтирование с возможностью записи (изменения эфемерны)
podman run -d --mount type=image,source=myapp-data:v1,target=/config,rw=true \
  node:20 tail -f /dev/null
```

### 7. NFS-том и внешние хранилища (local driver)

```bash
# Том, монтирующий NFS-шару (требуются root и установленные nfs-utils)
podman volume create --driver local \
  --opt type=nfs \
  --opt device=192.168.1.100:/exports/shared \
  --opt o=addr=192.168.1.100,rw,nfsvers=4.2 \
  nfs-shared

# Использование в контейнере
podman run -d --name webapp -v nfs-shared:/app/data nginx:latest
```

Опции `o` монтирования `local`-драйвера с правами root: любые опции `mount(8)`; `uid`/`gid`/`size`/`inodes`/`noquota` (квоты) — без root. Не путайте флаг создания `-o` (`--opt`) с опцией монтирования `-o`: для UID используйте `-o=o=uid=1000`, а не `-o=uid=1000`.

### 8. Резервное копирование и восстановление томов

**Встроенные команды (Podman 4.4+):**

```bash
# Экспорт тома в tar (по умолчанию — stdout)
podman volume export pgdata --output /backups/pgdata-$(date +%F).tar

# Сжатие через stdout
podman volume export pgdata | gzip > /backups/pgdata-$(date +%F).tar.gz

# Импорт: создать том и восстановить содержимое
podman volume create pgdata-restored
podman volume import pgdata-restored /backups/pgdata-$(date +%F).tar

# Импорт из gzip через stdin
gunzip -c /backups/pgdata.tar.gz | podman volume import pgdata-restored -
```

**Классический способ через временный контейнер (больше контроля):**

```bash
# Бэкап: том монтируется read-only в /source, архив кладём в /backup
podman run --rm \
  -v pgdata:/source:ro \
  -v /backups:/backup \
  docker.io/library/alpine \
  tar czf /backup/pgdata.tar.gz -C /source .

# Восстановление в новый том
podman run --rm \
  -v pgdata-restored:/target \
  -v /backups:/backup:ro \
  docker.io/library/alpine \
  tar xzf /backup/pgdata.tar.gz -C /target
```

**Консистентность:** для БД используйте утилиты уровня приложения (`pg_dump`, `mysqldump`) или остановите контейнер (`podman stop`), чтобы избежать неконсистентного снимка. `podman pause` замораживает процессы без остановки.

### 9. Монтирование образов и контейнеров для отладки

Podman позволяет смонтировать файловую систему контейнера или образа прямо в дерево каталогов хоста. Это незаменимо для быстрого анализа содержимого без запуска `exec`.

```bash
# Монтирование образа (rootful) или через podman unshare (rootless)
mount_point=$(podman image mount my-app-image)
ls -la $mount_point
# Обязательно размонтировать после работы
podman image unmount my-app-image

# Монтирование ФС контейнера (созданного, но не запущенного)
podman container mount my-container
podman container unmount my-container
```

В rootless-режиме смонтированные каталоги видны только внутри user namespace — используйте `podman unshare ls $mount_point` / выполняйте весь анализ через `podman unshare`.

### 10. Использование Quadlet для управления томами

Декларативное описание томов в systemd-юнитах (файлы в `~/.config/containers/systemd/`). Том переиспользуется контейнерами через ссылку на юнит.

**Файл:** `database.volume`
```ini
[Volume]
User=1000
Group=1000
Label=app=production
```

**Использование в контейнере** (файл `db.container`):
```ini
[Container]
Image=postgres:16-alpine
Environment=POSTGRES_PASSWORD=secret
Volume=database.volume:/var/lib/postgresql/data
```

**Файл:** `myvol.volume` с опциями драйвера:
```ini
[Volume]
Driver=local
Label=app=production
# Опции --opt (тип, устройство, опции монтирования)
[Volume.Options]
device=/dev/sdb
type=xfs
o=defaults
```

После добавления файлов: `systemctl --user daemon-reload && systemctl --user start db`.

### 11. Очистка и инспекция

```bash
# Сколько места занимают образы, контейнеры, тома, build cache
podman system df

# Детальная информация о конкретном томе (путь на хосте, драйвер, квоты)
podman volume inspect my-data

# Удаление неиспользуемых томов (в 6.0 — только анонимных без --all)
podman volume prune --all

# Полная очистка всех неиспользуемых объектов (образы, контейнеры, сети, тома)
podman system prune

# Оценка объёма освобождаемого места без удаления
podman system df --verbose
```

**Предупреждение:** `podman system reset` удаляет **все** данные: образы, контейнеры, поды, сети, тома и хранилище. Не используется для миграции бэкенда БД — только как крайнее средство.

---

## Дополнительная информация

### Нюансы и ограничения

- **Квоты**: лимиты размера (`size`) и числа файлов (`inodes`) работают только на **XFS** с опцией `pquota` (`/etc/fstab: ... xfs defaults,pquota`). На других ФС квоты недоступны.
- **Rootless**: только драйверы `overlay`/`vfs`; нативный overlay требует ядра 5.11+ (для SELinux — 5.13+); на NFS используется `fuse-overlayfs`. Опции монтирования `local`-драйвера (кроме uid/gid) требуют root.
- **Распространение монтирований**: по умолчанию `private`/`rprivate`; для динамических точек монтирования (например, `/proc`, NFS, LVM) настраивайте `bind-propagation=shared|slave` (рекурсивно с префиксом `r`).
- **SELinux**: без корректных меток (`:z`/`:Z`) bind mount на RHEL/Fedora завершится `Permission Denied`.
- **Copy-on-Write**: запись в том обходит CoW и быстрее записи в слой контейнера — критично для БД и I/O-интенсивных нагрузок.

### Принудительное использование fuse-overlayfs

Если возникают ошибки с правами доступа или производительностью OverlayFS в rootless-режиме:

```bash
# В файле storage.conf
[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
```

### Связанные разделы

- **[Rootless режим](./podman_rootless.md)** — глубокое описание маппинга UID/GID, fuse-overlayfs и расположения данных.
- **[Изоляция в Linux](../Docker/Concepts/linux_isolation.md)** — теоретические основы изоляции файловой системы (namespaces).
- **[Основные команды CLI](./podman_basic_commands.md)** — справочник команд управления томами и хранилищем.

### Ссылки

- **[Podman: Volume create](https://docs.podman.io/en/latest/markdown/podman-volume-create.1.html)** (англ.) — драйверы, опции, квоты, примеры.
- **[Podman: Volume commands](https://docs.podman.io/en/latest/markdown/podman-volume.1.html)** (англ.) — все команды подсистемы томов.
- **[containers.conf(5)](https://github.com/containers/container-libs/blob/main/common/docs/containers.conf.5.md)** (англ.) — параметры `[engine]` (бэкенд БД, volume plugins).
