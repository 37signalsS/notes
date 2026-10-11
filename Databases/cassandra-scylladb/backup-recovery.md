# Бэкап и восстановление

**Актуально для:** Apache Cassandra 5.0.x (актуальный патч 5.0.9) / ScyllaDB 2026.x (актуальный патч 2026.3.2; LTS — 2026.1)

## Определения

- **Снапшот (snapshot)** — набор hardlinks на SSTables таблицы на момент создания. Перед снапшотом memtable сбрасывается на диск (flush), поэтому снапшот содержит все данные на этот момент. В каталоге снапшота также лежит `schema.cql` — DDL таблицы.
- **Hardlink** — ссылка на тот же inode. Снапшот не занимает место сразу, но блокирует compaction: старые SSTables не удаляются, пока на них есть ссылки.
- **Инкрементальный бэкап** — hardlink на каждый SSTable, появившийся после flush/stream, в подкаталоге `backups/` таблицы.
- **PITR (point-in-time recovery)** — восстановление до произвольного момента времени: базовый снапшот + архив сегментов commitlog.
- **sstableloader** — утилита потоковой загрузки SSTables в кластер: читает файлы и передаёт их на узлы, владеющие соответствующими токенами.
- **Medusa** — инструмент бэкапа Apache Cassandra (проект TheLastPickle): оркестрация снапшотов по кластеру, хранение в local/S3-совместимых/GCS/Azure, full/differential-режимы.
- **ScyllaDB Manager** — companion-сервис ScyllaDB для расписания backup и repair; CLI `sctool`, агент на каждом узле. В K8s интегрируется через оператор (см. [Развёртывание в Kubernetes](./kubernetes.md)).
- **Manifest** — файл метаданных бэкапа: список файлов, токены узла, схема, хеши (у Medusa — md5).

## Как устроен бэкап в LSM-хранилище

Cassandra и ScyllaDB — LSM-движки: записи сначала попадают в commitlog (дurable) и memtable (память), затем сбрасываются на диск в неизменяемые (immutable) SSTables. Это определяет стратегию бэкапа:

1. **Снапшот** — hardlinks на текущие SSTables таблицы. Дешёвый (не копирует данные), но «заморожен» на момент создания.
2. **Инкрементальный бэкап** — hardlinks на каждый новый SSTable после flush. Полное восстановление = базовый снапшот + все инкрементальные с момента снапшота.
3. **Архив commitlog** — сегменты commitlog копируются при ротации; даёт PITR поверх снапшота.

Ключевое следствие hardlink-механики: место на диске растёт не от снапшотов как таковых, а от того, что compaction не может освободить старые SSTables, пока снапшот/инкрементальный бэкап ссылается на них. Поэтому снапшоты нужно копировать наружу и удалять (`clearsnapshot`) — это ответственность оператора.

Пути данных:
- Cassandra (пакет): `/var/lib/cassandra/data/<keyspace>/<table>-<uuid>/` — подкаталоги `snapshots/<tag>/` и `backups/`
- ScyllaDB: `/var/lib/scylla/data/<keyspace>/<table>-<uuid>/`
- Cassandra (tarball): `<install>/data/data/`

---

## Снапшоты (Cassandra и ScyllaDB)

```bash
# Снапшот всей keyspace (memtable сбрасывается автоматически)
nodetool snapshot -t backup_2026_01_15 my_app
# → Snapshot directory: /var/lib/cassandra/data/my_app/user_events-<uuid>/snapshots/backup_2026_01_15

# Снапшот одной таблицы (Cassandra 5.0: таблица задаётся опцией -cf/--table)
nodetool snapshot -t backup_2026_01_15 -cf user_events my_app

# Снапшот списка таблиц keyspace.table
nodetool snapshot -t backup_2026_01_15 -kt my_app.user_events,my_app.orders

# Снапшот без flush (НЕ содержит незалитых данных — только для отладки)
nodetool snapshot -t debug_1 -sf my_app

# Список снапшотов: размер на диске и «истинный» размер (без дедупликации SSTables)
nodetool listsnapshots
nodetool listsnapshots -k my_app -n backup_2026_01_15   # фильтры: keyspace, snapshot, table
nodetool listsnapshots -nt                                # исключить снапшоты с TTL
nodetool listsnapshots -e                                 # включить ephemeral-снапшоты

# Удаление снапшотов
nodetool clearsnapshot -t backup_2026_01_15 my_app   # по тегу
nodetool clearsnapshot -all my_app                   # все снапшоты keyspace
nodetool clearsnapshot                                # все снапшоты на узле

# Ограничение скорости создания hardlinks (ссылок/сек), чтобы не вытеснять нагрузку
nodetool setsnapshotthrottle 1000
nodetool getsnapshotthrottle
```

Снапшот содержит `schema.cql` — используйте его для восстановления схемы таблицы, если таблица была удалена. Снапшоты всех keyspaces (включая `system`) создаются при вызове без аргументов.

---

## Инкрементальные бэкапы

```bash
# Включение (cassandra.yaml / scylla.yaml)
incremental_backups: true     # дефолт: false
# ScyllaDB: после правки scylla.yaml требуется restart сервиса (Liveness: False)

# Или на живом узле без правки конфига (Cassandra)
nodetool enablebackup
nodetool statusbackup
nodetool disablebackup
```

После включения каждый flush/stream создаёт hardlink нового SSTable в `<keyspace>/<table>-<uuid>/backups/`. Инкрементальные бэкапы создаются и для системных таблиц. Отключить можно для конкретной таблицы параметром `incremental_backups: false` в `ALTER TABLE` (CASSANDRA-15402).

**Важно:**
- Удаление файлов из `backups/` — ответственность оператора; Cassandra не чистит их сама.
- Инкрементальный бэкап **не содержит DDL** — схема берётся из снапшота (`schema.cql`).
- Полное восстановление = базовый снапшот + все инкрементальные с момента снапшота.

---

## Архивирование commitlog и PITR

Настройка в `/etc/cassandra/commitlog-archiving.properties` (для ScyllaDB — аналогично в конфигурации архивирования):

```properties
# Копирование завершённого сегмента commitlog при его ротации
# %path — полный путь сегмента, %name — имя файла
# Только ОДНА команда: STDOUT/STDIN и цепочки запрещены — сложную логику выносите в скрипт
archive_command=/bin/ln %path /backup/commitlog/%name

# Восстановление сегмента из архива в живой commitlog при рекавери
# %from — путь к архивному сегменту в restore_directories, %to — живой commitlog
restore_command=cp -f %from %to

# Каталог(и), из которых сканируются восстанавливаемые сегменты
restore_directories=/backup/commitlog

# Точка восстановления (GMT): применяются мутации с timestamp <= этой
restore_point_in_time=2026:10:04 09:00:00
```

**Процедура PITR:**
1. Восстановить базовый снапшот (см. «Восстановление» ниже).
2. Остановить узел: `systemctl stop cassandra`.
3. Настроить `restore_command`, `restore_directories`, `restore_point_in_time`.
4. Запустить узел — Cassandra копирует архивные сегменты в живой commitlog и реплеит их до точки восстановления.

Ограничение (документированное): реплей останавливается на первом клиентском timestamp больше точки восстановления; порядок мутаций не строго хронологический, поэтому часть мутаций около границы может быть не восстановлена.

---

## Политика бэкапа: скрипт с ротацией

```bash
#!/bin/bash
# Ежедневный бэкап keyspace: снапшот -> rsync на backup-сервер -> ротация
set -euo pipefail

KEYSPACE="my_app"
TAG="daily_$(date +%F)"
SNAP_ROOT="/var/lib/cassandra/data/$KEYSPACE"
RETENTION_DAYS=14

# 1. Снапшот (memtable сброшен, данные консистентны на момент создания)
nodetool snapshot -t "$TAG" "$KEYSPACE"

# 2. Копирование на backup-сервер: hardlinks разворачиваются в независимые файлы
#    rsync без -H: копируется содержимое, а не ссылки — именно это нужно для бэкапа
rsync -av "$SNAP_ROOT"/*/snapshots/"$TAG"/ backup-server:"/backups/cassandra/$TAG/"

# 3. Локальный снапшот удаляется ТОЛЬКО после успешного копирования (set -e)
nodetool clearsnapshot -t "$TAG" "$KEYSPACE"

# 4. Ротация на backup-сервере
ssh backup-server "find /backups/cassandra -maxdepth 1 -mtime +$RETENTION_DAYS -exec rm -rf {} +"
```

---

## ScyllaDB Manager (bare-metal)

ScyllaDB Manager — официальный инструмент расписания backup/repair для on-prem-кластеров (агент устанавливается на каждом узле). Провайдеры хранилища: `localstorage` (сетевой файловый ресурс), `s3` (в т.ч. S3-совместимые: Ceph, MinIO), `gcs`, `azure`.

```bash
# 1. Локальное хранилище (NFS): все узлы DC должны видеть один и тот же shared-файл
#    /etc/scylla-manager-agent/scylla-manager-agent.yaml
#    localstorage:
#      path: /mnt/nfs
#    Bucket = подкаталог под path; создать заранее.
#    Только rclone-based backup/restore (native недоступен для localstorage).

# 2. Проверка доступности location с узла
scylla-manager-agent check-location --location localstorage:backups

# 3. Бэкап (keyspace поддерживает glob: --keyspace "my_app,!my_app.audit_*")
sctool backup --cluster my-cluster --location localstorage:backups --keyspace my_app

# 4. Список бэкапов
sctool backup list -c my-cluster -L localstorage:backups

# 5. Восстановление (по тегу снапшота)
sctool restore -c my-cluster -L localstorage:backups -T <SNAPSHOT_TAG> --restore-schema
sctool restore -c my-cluster -L localstorage:backups -T <SNAPSHOT_TAG> --restore-tables
```

Поля задачи backup (расширенный cron: `@daily`, `@every 4h`): `cron`, `location` (формат `[<dc>:]<provider>:<name>`, в multi-DC — location на DC), `keyspace` (glob), `dc` (glob по datacenter), `retention`, `rateLimit` (МиБ/с, по умолчанию 100), `numRetries`, `retryWait` (экспоненциальный backoff), `snapshotParallel`/`uploadParallel`, `startDate`, `timezone`. Структура в location: `/backup/meta/cluster/<cluster_id>/dc/<dc>/node/<node_id>/` (манифесты) и `/backup/sst/...` (SSTables).

---

## Medusa (Apache Cassandra)

Medusa — инструмент бэкапа Cassandra с оркестрацией по кластеру. Хранилища: `local` (в т.ч. NFS), S3 и S3-совместимые (Ceph, MinIO), GCS, Azure.

```bash
# Установка на каждом узле
sudo apt-get install cassandra-medusa        # Debian/Ubuntu
# или: sudo pip3 install cassandra-medusa    (для S3-бэкендов: cassandra-medusa[S3])

# /etc/medusa/medusa.ini
# [storage]
# storage_provider = local
# base_path = /mnt/backups/medusa
# bucket_name = cassandra_backups

# Бэкап: differential (дефолт, хранит ссылки на SSTables) или full
medusa backup --backup-name=daily_2026_10_04
medusa backup --backup-name=full_2026_10_04 --mode=full

# Бэкап всего кластера (оркестрация с v0.8.0)
medusa backup-cluster --backup-name=cluster_2026_10_04

# Восстановление: in-place (тот же кластер) и remote (другой кластер)
medusa restore --backup-name=daily_2026_10_04
```

Механика: Medusa создаёт снапшот через `nodetool`, загружает SSTables в хранилище, удаляет локальный снапшот. К каждому бэкапу сохраняются три мета-файла: полный CQL-схема, карта токенов и manifest с md5-хешами (`--enable-md5-checks` включает контроль целостности при бэкапе/verify). Differential-режим — дефолт: в каталоге хранится одна копия каждого SSTable, а манифесты ссылаются на неё (в продакшене Spotify сокращало размер бэкапов до 80%). Ограничение: не поддерживает несколько data-директорий. Троттлинг: `transfer_max_bandwidth = 50MB/s`.

---

## Восстановление

### Из снапшота на том же узле (Cassandra 4.0+/5.0)

Рекомендуемый способ — `nodetool import` (заменил deprecated `nodetool refresh`, CASSANDRA-6719); файлы не нужно перемещать в `upload/`:

```bash
# 1. Если таблица удалена — воссоздать схему из снапшота
cqlsh <node> -e "SOURCE '/var/lib/cassandra/data/my_app/user_events-<uuid>/snapshots/backup_2026_01_15/schema.cql';"

# 2. Импорт SSTables из каталога снапшота (или backups/ для инкрементальных)
nodetool import -- my_app user_events \
    /var/lib/cassandra/data/my_app/user_events-<uuid>/snapshots/backup_2026_01_15/
# Опции: -cd/--copy-data (копировать вместо move), -q/--quick, -v/--no-verify,
#         -r/--keep-repaired, -l/--keep-level, -e/--extended-verify

# ScyllaDB: nodetool refresh (поддерживается); для потоковой передачи на владельцев токенов:
#   скопировать файлы в <table>-<uuid>/upload/ (владелец scylla:scylla) и
#   nodetool refresh my_app user_events --load-and-stream
```

Полное восстановление с инкрементальными бэкапами: сначала импортировать снапшот, затем все `backups/` с момента снапшота (порядок: от старых к новым).

### Через sstableloader (топология-независимо)

`sstableloader` читает SSTables и стримит их на узлы, владеющие токенами — работает при любой топологии, узлы не перезагружаются. Требование: путь должен быть строго `<keyspace>/<table>/` — каталоги `snapshots/` и `backups/` (`<keyspace>/<table>-<uuid>/...`) напрямую не подходят:

```bash
# 1. Создать структуру и скопировать (или сделать symlink) файлы снапшота
mkdir -p /restore/my_app/user_events
cp /var/lib/cassandra/data/my_app/user_events-<uuid>/snapshots/backup_2026_01_15/*-Data.db /restore/my_app/user_events/

# 2. Потоковая передача SSTables в кластер
sstableloader -d <node_ip> /restore/my_app/user_events
```

### На новом узле / идентичном кластере

```bash
# 1. Установить ту же версию Cassandra/ScyllaDB
# 2. Остановить сервис
systemctl stop cassandra

# 3. Очистить данные
rm -rf /var/lib/cassandra/data/*

# 4. Скопировать снапшоты В КАТАЛОГИ ТАБЛИЦ (не в корень data/!):
#    <data_dir>/<keyspace>/<table>-<uuid>/ — UUID берётся из снапшота
#    или воссоздаётся через CREATE TABLE + schema.cql
rsync -av backup-server:/backups/cassandra/latest/ /var/lib/cassandra/data/

# 5. Запустить сервис — узел загружает SSTables при старте
systemctl start cassandra

# 6. Синхронизация с кластером (если узел возвращается в живой кластер)
nodetool repair -pr my_app     # см. [Обслуживание](./operations.md)
```

Ограничения: копирование файлов в каталог таблицы допустимо только при остановленном сервисе (для живого узла — `upload/` + `refresh`/`import`). Восстановление «на место» корректно только для идентичного кластера: то же число узлов и распределение токенов, каждый узел восстанавливается из своего бэкапа (для ScyllaDB — только vnode keyspaces). При изменившейся топологии используйте sstableloader или load-and-stream. Для замены вышедшего из строя узла — `nodetool replace` (см. [Обслуживание](./operations.md)).

**ScyllaDB — три метода restore** (по документации ScyllaDB):
1. **Из object storage** (`nodetool backup` restore из S3-совместимого хранилища) — на живом кластере, независимо от изменений топологии.
2. **Load and stream** — SSTables в `upload/` одной из нод + `nodetool refresh --load-and-stream`; независимо от топологии, кластер онлайн.
3. **В идентичный кластер** — файлы обратно в каталоги таблиц при остановленном сервисе + restart; требует того же числа узлов и токенов.

Перед restore в ScyllaDB данные таблицы должны быть усечены (truncate), чтобы существующие данные не перезаписали восстанавливаемые.

---

## Валидация бэкапа и restore

```bash
# Размеры и список снапшотов
nodetool listsnapshots

# После restore — сверка содержимого
cqlsh <node> -e "SELECT COUNT(*) FROM my_app.user_events;"
nodetool tablestats my_app.user_events

# Проверка контрольных сумм SSTables (см. operations.md)
nodetool verify my_app

# Medusa: бэкап/верификация с md5
medusa backup --backup-name=... --enable-md5-checks

# ScyllaDB Manager: доступность location
scylla-manager-agent check-location --location localstorage:backups
```

---

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Место на диске растёт после снапшотов | hardlinks блокируют удаление старых SSTables compaction | копировать снапшот наружу, затем `nodetool clearsnapshot` |
| `nodetool import` не загружает файлы | неверный путь к каталогу или не совпадает схема | проверить путь и `schema.cql` из снапшота; опция `-v` для деталей |
| sstableloader: ошибка структуры каталога | путь должен быть `<keyspace>/<table>/`, а не `.../snapshots/` | создать структуру и скопировать файлы (или symlink) |
| Restore на новом узле: данных нет | файлы скопированы в корень `data/`, а не в каталог таблицы `<keyspace>/<table>-<uuid>/` | положить файлы в каталог таблицы при остановленном сервисе |
| PITR: часть мутаций не восстановлена | порядок мутаций не строго по timestamp | документированное ограничение; выбирать точку с запасом |
| ScyllaDB Manager: задача backup failed | агент не достигает location | `scylla-manager-agent check-location`; проверить NFS-монт и права |
| ScyllaDB restore: «table data must be truncated» | в таблице есть данные | `TRUNCATE` перед restore |
| Medusa restore: permission denied | пользователь medusa не имеет прав на data-dir | `use_sudo_for_restore = True` в `medusa.ini` / настроить права |
| Инкрементальные бэкапы не появляются | `incremental_backups: false` | `nodetool enablebackup` или параметр в yaml |

---

## Best Practices

- **Правило 3-2-1:** 3 копии данных, на 2 разных носителях, 1 копия вне сайта (backup-сервер/NFS).
- **PITR-цепочка:** снапшот (база) + инкрементальные бэкапы + архив commitlog — единственный способ восстановить произвольный момент.
- **Тестируйте restore.** Бэкап без проверенного восстановления — не бэкап: регулярно разворачивайте снапшот в тестовый кластер и сверяйте `SELECT COUNT(*)`.
- **Снапшот перед рискованными операциями:** изменение схемы, upgrade версии, repair/scrub/verify (scrub/verify создают снапшоты по умолчанию — см. [Обслуживание](./operations.md)).
- **Троттлинг** снапшотов и стриминга в часы нагрузки: `nodetool setsnapshotthrottle`, `nodetool setstreamthroughput`.
- **Схема отдельно:** снапшот содержит `schema.cql`, Medusa — полный CQL; храните выгрузку схемы (`DESCRIBE KEYSPACE`) вне кластера.
- **Retention:** политика удаления для снапшотов, `backups/` и архивов commitlog; мониторьте успешность задач (см. [Мониторинг](./monitoring.md)).
- **Не снапшотируйте в пик** без throttle: создание hardlinks нагружает диск.

### Очистка

```bash
# Снапшоты
nodetool clearsnapshot -t <tag> <keyspace>
nodetool clearsnapshot -all <keyspace>
nodetool clearsnapshot                     # все снапшоты узла (в т.ч. после scrub/verify)

# Инкрементальные бэкапы (удаляются вручную — ответственность оператора)
find /var/lib/cassandra/data -path '*/backups/*' -mtime +14 -delete

# Архивные commitlog старше retention
find /backup/commitlog -mtime +30 -delete
```

---

## См. также

- **[Обслуживание и эксплуатация](./operations.md)** — repair, `nodetool replace`, scrub/verify, throttling, `sstableloader`.
- **[Установка и настройка](./installation.md)** — пути данных и конфигурации.
- **[Развёртывание в Kubernetes](./kubernetes.md)** — ScyllaDB Manager как CRD `ScyllaDBManagerTask`, Medusa в K8ssandra.
- **[Мониторинг и observability](./monitoring.md)** — метрики и проверка состояния после restore.
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — восстановление после сбоев.
- Официальная документация: [Cassandra: Backups](https://cassandra.apache.org/doc/latest/cassandra/managing/operating/backups.html), [commitlog-archiving.properties](https://cassandra.apache.org/doc/latest/cassandra/managing/configuration/cass_cl_archive_file.html), [ScyllaDB Manager](https://manager.docs.scylladb.com/stable/), [Medusa](https://github.com/thelastpickle/cassandra-medusa).
