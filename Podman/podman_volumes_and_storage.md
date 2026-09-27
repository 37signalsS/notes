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

Путь к каталогу томов можно переопределить:
- Глобально — параметром `volumes` в `containers.conf` (секция `[engine]`), например `volumes = ["/mnt/diskr/containers/volumes"]`.
- Устаревший флаг `podman --volumepath <path>` deprecated; используйте конфигурационный файл.

```toml
[engine]
volumes = ["/mnt/diskr/containers/volumes"]
```

### Производительность драйверов и Copy-on-Write

| Драйвер | Особенности | Когда использовать |
| :--- | :--- | :--- |
| **overlay** (нативный) | Поддержка слоев, минимальный overhead. Требует ядро 5.11+ для rootless. | Стандарт для большинства workloads. |
| **overlay** через `fuse-overlayfs` | Работает в userspace; поддерживается на любом ядре, в т.ч. на NFS. Накладные расходы на FUSE (~5-15%). | Rootless на старых ядрах, NFS. |
| **vfs** | Без слоев: каждый слой — полная копия. Медленный, много места. | Fallback при отсутствии overlay; отладка. |
| **btrfs / zfs** | Снапшоты на уровне ФС. | Rootful, бэкапы через snapshot. |

**Copy-on-Write overhead:**
- Маленькие случайные записи в CoW-слой (том) медленнее, чем в bind mount, из-за копирования блоков.
- Для I/O-интенсивных баз данных используйте **Named Volume** (обходит CoW для данных) или **bind mount на отдельный диск/раздел**.
- При большой фрагментации overlay (`find /var/lib/containers/storage -type f | wc -l` > 100k) выполняйте `podman system prune -a` или переключитесь на `btrfs`/`zfs`.

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

### 12. Диагностика состояния томов и хранилища

```bash
# Размер томов, слоев и кэша (с детализацией по volumes)
podman system df -v

# JSON-информация о томе: путь, драйвер, опции, квоты
podman volume inspect pgdata
# → [
#   {
#     "Name": "pgdata",
#     "Driver": "local",
#     "Mountpoint": "/var/lib/containers/storage/volumes/pgdata/_data",
#     "Options": {
#       "o": "size=10G,uid=1000"
#     },
#     "Labels": {
#       "app": "web"
#     }
#   }
# ]

# События, связанные с томами (создание, удаление, монтирование)
podman events --filter event=volume --format '{{.Time}} {{.Action}} {{.Actor}}'

# Проверка точек монтирования контейнера
podman inspect --format '{{json .Mounts}}' my-postgres | jq .

# Сколько inode используется в graphroot (предотвращение исчерпания inodes)
df -i /var/lib/containers/storage
```

### 13. Миграция тома между хостами

```bash
# На хосте-источнике: экспорт тома
podman volume export pgdata --output /tmp/pgdata.tar

# Перенос на целевой хост (scp/rsync)
scp /tmp/pgdata.tar user@target:/tmp/

# На хосте-приемнике: импорт
podman volume create pgdata-restored
podman volume import pgdata-restored /tmp/pgdata.tar

# Или через tar + pipe (без промежуточного файла)
podman volume export pgdata | gzip | ssh user@target 'gunzip | podman volume import pgdata-restored -'
```

**Важно:** для больших баз данных используйте `pg_dump`/`mysqldump` вместо прямого экспорта тома, чтобы избежать неконсистентности.

### 14. Копирование данных в новый том без контейнера

```bash
# Создать новый пустой том
podman volume create newdata

# Скопировать данные через временный контейнер (alpine)
podman run --rm \
  -v olddata:/source:ro \
  -v newdata:/target \
  alpine \
  cp -a /source/. /target/
```

### 15. Совместное использование тома между контейнерами (read-only)

```bash
# Read-only том для статики (nginx + multiple backends)
podman volume create shared-static

# Заполнение тома данными через временный контейнер
podman run --rm \
  -v shared-static:/data \
  nginx:alpine \
  sh -c "echo '<h1>Hello</h1>' > /data/index.html"

# Два контейнера используют один том read-only
podman run -d --name web1 -v shared-static:/usr/share/nginx/html:ro nginx
podman run -d --name web2 -v shared-static:/usr/share/nginx/html:ro nginx
```

### 16. Консистентный бэкап базы данных

Для production баз данных используйте комбинацию логического дампа и экспорта тома:

```bash
# 1. Остановить контейнер (гарантирует консистентность CoW)
podman stop my-postgres

# 2. Логический бэкап (быстро, можно делать на лету через pg_dump)
podman run --rm \
  -v pgdata:/var/lib/postgresql/data:ro \
  -v /backups:/backup \
  postgres:16-alpine \
  pg_dump -U postgres -d mydb -F c -f /backup/mydb.dump

# 3. Экспорт тома для полного восстановления
podman volume export pgdata --output /backups/pgdata-$(date +%F).tar

# 4. Запуск контейнера обратно
podman start my-postgres
```

**Альтернатива без остановки:** используйте `podman container freeze` (замораживает процессы через cgroup) для snapshot-consistency:

```bash
podman container freeze my-postgres
podman volume export pgdata --output /backups/pgdata-$(date +%F).tar
podman container unfreeze my-postgres
```

### 17. Очистка хранилища и томов

```bash
# Удаление ВСЕХ неиспользуемых томов (включая именованные) — Podman 6.0+
podman volume prune --all

# Удаление неиспользуемых томов с фильтром по метке (сохранить backup-тома)
podman volume prune --filter label!=backup

# Полная очистка: образы, контейнеры, сети, тома, build cache
podman system prune -a --volumes

# Оценка места без удаления
podman system df --verbose

# Удаление неиспользуемых слоев overlay после prune (вручную)
podman system migrate --migrate-db  # оптимизирует SQLite и убирает висячие ссылки
```

### 18. Работа с опцией `nocopy`

По умолчанию Podman копирует содержимое пути из образа в новый том при первом подключении. Отключите для ускорения создания пустых томов:

```bash
# Без копирования (быстро)
podman volume create --opt nocopy=1 empty-vol

# С копированием (поведение по умолчанию)
podman volume create --opt nocopy=0 data-vol
```

### 19. XFS квоты: практическая настройка и проверка

Квоты работают только на XFS с опцией `pquota` в fstab или через `xfs_quota`:

```bash
# 1. Проверка поддержки pquota
xfs_info /var/lib/containers/storage | grep -E "ftype|reflink"
# Ожидается: ftype=1, reflink=1 (для overlay2)

# 2. Включение pquota (если не включено)
mount -o remount,prjquota /var/lib/containers/storage

# 3. Создание тома с квотой
podman volume create --opt o=size=10G,uid=1000 pgdata

# 4. Проверка использования
podman volume inspect pgdata --format '{{.Options.o}}'
# → size=10G,uid=1000

# 5. Мониторинг через xfs_quota (root)
xfs_quota -x -c 'report -h' /var/lib/containers/storage
```

### 20. Производительность: выбор типа монтирования

| Сценарий | Рекомендация | Почему |
| :--- | :--- | :--- |
| **База данных (PostgreSQL, MySQL)** | Named Volume | Избегает CoW overhead; Podman управляет правами. |
| **Код приложения (hot-reload)** | Bind Mount | Изменения на хосте сразу видны в контейнере. |
| **Конфиги и секреты** | Bind Mount + `:Z`/`:ro` | SELinux-метки, read-only. |
| **Кэш (node_modules, apt)** | tmpfs | Скорость RAM; не нуждается в персистентности. |
| **Большие статические данные** | Image Volume + `ro=true` | Версионирование через теги образа; read-only. |
| **Общие данные между контейнерами** | Named Volume | Персистентность; не зависит от жизненного цикла контейнера. |

**Bind propagation:** для динамических точек монтирования (NFS, LVM, `/proc`) используйте `bind-propagation=rshared`:

```bash
podman run -d \
  --mount type=bind,src=/data,dst=/app/data,bind-propagation=rshared \
  nginx
```

---

## Устранение неполадок

| Ошибка / Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Permission denied` при монтировании bind mount | SELinux не relabeled | `ls -Z /host/path` | Добавьте `:Z` (exclusive) или `:z` (shared) к монтированию. |
| `Permission denied` на файлы в rootless-томе | UID/GID не совпадают | `podman unshare ls -l /path/to/host/dir` | Используйте `:U`, `:idmap` или `--userns=keep-id`. |
| `no space left on device` на volume | Исчерпание inodes или дискового места | `df -h /var/lib/containers/storage && df -i /var/lib/containers/storage` | Очистите неиспользуемые образы (`podman system prune -a`) или расширьте ФС. |
| `stale file handle` (NFS) | NFS-сервер перезапущен; кэш монтирования устарел | `mount | grep nfs` | Перемонтируйте том (`podman volume rm + podman volume create`) или перезагрузите NFS-клиент. |
| `device is busy` при удалении тома | Том смонтирован в работающий контейнер | `podman ps --filter volume=myvol` | Остановите контейнер (`podman stop`) или используйте `podman volume rm --force`. |
| `overlay mount fails` в rootless | Ядро < 5.11 без `fuse-overlayfs` | `podman info --format '{{.Host.OCIRuntime}}'` | Установите `fuse-overlayfs` или переключитесь на драйвер `vfs`. |
| `unknown filesystem type 'overlay'` | Ядро без поддержки overlay | `modprobe overlay` | Включите модуль `overlay` или используйте `fuse-overlayfs`. |
| Контейнер не запускается: `mount propagation` | Некорректный `bind-propagation` для `/proc` или NFS | `podman inspect --format '{{.HostConfig.BindPropagation}}'` | Используйте `rshared` для динамических точек монтирования. |
| Данные тома исчезают после перезагрузки | Том смонтирован как tmpfs или используется драйвер `vfs` с неправильным `runroot` | `podman volume inspect` (проверьте `Mountpoint`) | Проверьте `storage.conf`: `graphroot` на постоянном диске. |
| `podman volume prune` не удаляет именованные тома | В Podman 6.0 по умолчанию удаляет только анонимные тома | `podman volume ls` | Добавьте флаг `--all` (`podman volume prune --all`). |

### Диагностические команды

```bash
# Список всех смонтированных точек Podman
mount | grep containers

# Проверка SELinux-контекстов томов
ls -Zd /var/lib/containers/storage/volumes/*/_data

# Проверка делегирования cgroup (rootless)
cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/cgroup.controllers

# Проверка, какие контейнеры используют том
podman ps --filter volume=pgdata --format '{{.ID}} {{.Names}}'

# Проверка свободного места и inodes
podman system df -v
df -h /var/lib/containers/storage
df -i /var/lib/containers/storage

# Проверка версии Podman и драйвера хранилища
podman info --format '{{.Host.StorageDriver}} {{.Host.OCIRuntime}}'
```

---

## Дополнительная информация

### Нюансы и ограничения

- **Квоты**: лимиты размера (`size`) и числа файлов (`inodes`) работают только на **XFS** с опцией `pquota` (`/etc/fstab: ... xfs defaults,pquota`). На других ФС квоты недоступны.
- **Rootless**: только драйверы `overlay`/`vfs`; нативный overlay требует ядра 5.11+ (для SELinux — 5.13+); на NFS используется `fuse-overlayfs`. Опции монтирования `local`-драйвера (кроме uid/gid) требуют root.
- **Распространение монтирований**: по умолчанию `private`/`rprivate`; для динамических точек монтирования (например, `/proc`, NFS, LVM) настраивайте `bind-propagation=shared|slave` (рекурсивно с префиксом `r`).
- **SELinux**: без корректных меток (`:z`/`:Z`) bind mount на RHEL/Fedora завершится `Permission Denied`.
- **Copy-on-Write**: запись в том обходит CoW и быстрее записи в слой контейнера — критично для БД и I/O-интенсивных нагрузок.
- **Inodes**: исчерпание inodes (`df -i` → 100%) приводит к ошибкам записи даже при наличии свободного места. Решение: `podman system prune -a` или увеличение количества inodes при форматировании ФС.
- **fuse-overlayfs**: при проблемах с производительностью проверьте версию `fuse-overlayfs` (>= 1.12 для Podman 6.x) и используйте `--log-level=debug` для диагностики монтирования.
- **`podman volume rm --force`**: принудительно удаляет том, даже если он смонтирован в работающий контейнер. Контейнер продолжает работать, но точка монтирования становится недоступной (stale mount).
- **Image Volume `rw=true`**: изменения пишутся в верхний слой overlay и исчезают вместе с контейнером. Для сохранения изменений используйте `podman commit` или экспортируйте том.

### Глобальный путь к томам

Вместо устаревшего флага `--volumepath` используйте `containers.conf`:

```toml
[engine]
volumes = ["/mnt/diskr/containers/volumes"]
```

Перезапуск Podman не требуется; новые тома создаются в указанном каталоге.

### Экспорт/импорт и совместимость

- `podman volume export` (Podman 4.4+) создает tar-архив с содержимым тома. Формат совместим с `podman volume import` и `docker volume export`/`import` (после конвертации путей).
- Для миграции с Docker скопируйте содержимое `/var/lib/docker/volumes/<name>/_data` в том же формате.
- Для больших (>100GB) томов используйте `tar` + `pigz` (parallel gzip) для ускорения.

### Практические советы по безопасности

- Никогда не монтируйте чувствительные каталоги хоста в контейнер без `:Z`/`:z` на системах с SELinux.
- Для секретов используйте `tmpfs` или `podman secret create`, а не bind mount с файлом на диске.
- Избегайте `--privileged`; для доступа к устройствам используйте `--device` или `--group-add`.

### Связанные разделы

- **[Rootless режим](./podman_rootless.md)** — глубокое описание маппинга UID/GID, fuse-overlayfs и расположения данных.
- **[Изоляция в Linux](../Docker/Concepts/linux_isolation.md)** — теоретические основы изоляции файловой системы (namespaces).
- **[Основные команды CLI](./podman_basic_commands.md)** — справочник команд управления томами и хранилищем.

### Ссылки

- **[Podman: Volume create](https://docs.podman.io/en/latest/markdown/podman-volume-create.1.html)** (англ.) — драйверы, опции, квоты, примеры.
- **[Podman: Volume commands](https://docs.podman.io/en/latest/markdown/podman-volume.1.html)** (англ.) — все команды подсистемы томов.
- **[containers.conf(5)](https://github.com/containers/container-libs/blob/main/common/docs/containers.conf.5.md)** (англ.) — параметры `[engine]` (бэкенд БД, volume plugins, глобальный путь к томам).
