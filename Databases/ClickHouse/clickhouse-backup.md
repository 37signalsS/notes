# ClickHouse — Бэкапы и восстановление

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

- **BACKUP / RESTORE** — нативные SQL-команды логического резервного копирования. Поддерживают физические и S3-совместимые хранилища, инкрементальные бэкапы через `base_backup`, асинхронный режим и параллельные операции.
- **FREEZE PARTITION** — создание hardlinks на части данных в `/var/lib/clickhouse/shadow/`. Мгновенная операция, основа физических бэкапов. Не реплицируется.
- **FETCH PARTITION** — загрузка партиции с другой реплики по сети для восстановления повреждённой части.
- **RPO (Recovery Point Objective)** — максимально допустимая потеря данных (например, RPO 1 час = при сбое можно потерять до 1 часа данных).
- **RTO (Recovery Time Objective)** — максимально допустимое время восстановления сервиса.
- **Инкрементальный бэкап** — бэкап только изменённых с момента базового бэкапа частей. ClickHouse части неизменяимы — инкремент эффективен.
- **shadow** — каталог `/var/lib/clickhouse/shadow/`, куда `FREEZE` помещает hardlinks снапшотов.
- **clickhouse-backup** — сторонний инструмент (Altinity) для автоматизации физических бэкапов с поддержкой S3, инкрементальных копий, retention и systemd-автоматизации.
- **system.backups** — системная таблица с историей `BACKUP`/`RESTORE` операций (id, name, status, timings, размеры, ошибки). Не persistent — сбрасывается при перезапуске сервера.
- **system.backup_log** — системный лог (persistent) с полной историей всех событий бэкапа/восстановления.

## Предварительные требования

- **ClickHouse:** 26.9.x (Stable) или 26.8.x (LTS). Нативный `BACKUP`/`RESTORE` доступен с 22.3.
- **Диск:** свободное место не менее размера самой большой таблицы для `FREEZE` (hardlinks, но metadata требует места). Для `clickhouse-backup` — место под временный каталог (по умолчанию `/var/lib/clickhouse/`).
- **Права:** пользователь `clickhouse` должен иметь запись в `/var/lib/clickhouse/shadow/`.
- **Сеть:** для `BACKUP` в S3/NFS — доступность endpoint, корректные credentials.
- **Инструменты:** `rsync` для FREEZE workflow; `clickhouse-backup` (Altinity) для автоматизации; `systemd` для управления таймерами.
- **Keeper:** если используется встроенный Keeper — стандартный путь `/var/lib/clickhouse/coordination/`. Для standalone `clickhouse-keeper` — путь определяется `log_storage_path` (по умолчанию `/var/lib/clickhouse-keeper/log`).

## Основные концепции

### Почему бэкапы в ClickHouse эффективны

Части (parts) в MergeTree **неизменяемы** — данные никогда не модифицируются на месте, только добавляются новые части и удаляются старые при слияниях. Это даёт:

- **FREEZE мгновенна** — hardlinks на существующие части, без копирования.
- **Инкрементальные бэкапы эффективны** — с момента базового бэкапа изменились только новые части.
- **Консистентность** — снапшот частей всегда в согласованном состоянии (части атомарны).

### Модели бэкапов

| Метод | Тип | RPO | RTO | Кейс |
| :--- | :--- | :--- | :--- | :--- |
| `BACKUP/RESTORE` | Логический (SQL) | зависит от частоты | средний | Портативные бэкапы, S3, инкрементальные |
| `FREEZE` + копирование | Физический (hardlinks) | зависит от частоты | быстрый | Полные снапшоты на диск/ленту |
| `clickhouse-backup` | Физический (утилита) | зависит от частоты | быстрый | Автоматизация, S3, инкрементальные |
| Репликация | Непрерывный | ~0 (с quorum) | мгновенный (failover) | HA, не замена бэкапу |
| Kafka replay | Логический (источник) | зависит от retention | медленный | Восстановление потока с начала |

**Важно:** репликация — не бэкап. Репликация защищает от отказа узла, но не от `DELETE`/`DROP` (операции реплицируются). Для защиты от логических ошибок нужен бэкап.

### Синтаксис BACKUP / RESTORE

```sql
-- core commands
BACKUP | RESTORE
    TABLE [db.]table_name [AS [db.]table_name_in_backup] |
    DICTIONARY [db.]dictionary_name [AS [db.]name_in_backup] |
    DATABASE database_name [AS database_name_in_backup] |
    TEMPORARY TABLE table_name [AS table_name_in_backup] |
    VIEW view_name [AS view_name_in_backup] |
    [EXCEPT TABLES ...] |
    [EXCEPT DATA FROM {TABLE|TABLES} ...] | -- BACKUP only
    ALL [EXCEPT {TABLES|DATABASES}...] |
    [,...]
    [ON CLUSTER 'cluster_name']
TO|FROM
    File('<path>/<filename>') |
    Disk('<disk_name>', '<path>/') |
    S3('<S3 endpoint>/<path>', '<Access key ID>', '<Secret access key>') |
    AzureBlobStorage('<connection string>', '<container>', '<path>') |
    [SETTINGS ...]
    [ASYNC]
```

## Практические сценарии

### Нативный BACKUP / RESTORE на S3

Современный синтаксис использует функцию `S3()` вместо устаревшего `s3://bucket/path` с inline credentials:

```sql
-- Полный бэкап таблицы на S3
BACKUP TABLE logs TO S3(
    'https://s3.us-east-1.amazonaws.com/clickhouse-backups/logs/full',
    '<access_key_id>',
    '<secret_access_key>'
);

-- Инкрементальный бэкап (только изменения с базового)
BACKUP TABLE logs TO S3(
    'https://s3.us-east-1.amazonaws.com/clickhouse-backups/logs/incr-20261004',
    '<access_key_id>',
    '<secret_access_key>'
)
SETTINGS base_backup = S3(
    'https://s3.us-east-1.amazonaws.com/clickhouse-backups/logs/full',
    '<access_key_id>',
    '<secret_access_key>'
);

-- Бэкап на локальный диск
BACKUP TABLE logs TO Disk('backups', 'logs_full.zip');

-- Асинхронный бэкап (возвращает id для мониторинга)
BACKUP TABLE logs TO S3(
    'https://s3.us-east-1.amazonaws.com/clickhouse-backups/logs/full',
    '<access_key_id>',
    '<secret_access_key>'
) ASYNC;

-- Восстановление с переименованием таблицы
RESTORE TABLE logs AS logs_restored FROM S3(
    'https://s3.us-east-1.amazonaws.com/clickhouse-backups/logs/full',
    '<access_key_id>',
    '<secret_access_key>'
);

-- Бэкап всей БД без данных (только схема)
BACKUP DATABASE mydb EXCEPT DATA FROM TABLES events TO Disk('backups', 'schema_only');

-- Бэкап всего кластера
BACKUP ALL ON CLUSTER '{cluster}' TO S3('...', '<key>', '<secret>');

-- Бэкап с access entities (users, roles)
BACKUP TABLE system.users, TABLE system.roles, TABLE system.settings_profiles,
       TABLE system.row_policies, TABLE system.quotas, TABLE system.functions,
       ALL EXCEPT DATABASES INFORMATION_SCHEMA, information_schema, system
TO S3('...', '<key>', '<secret>');
```

### FREEZE / FETCH (физические снапшоты)

```sql
-- Снапшот партиции (hardlinks в /var/lib/clickhouse/shadow/)
ALTER TABLE logs FREEZE PARTITION '2026-09';

-- С именованный снапшот
ALTER TABLE logs FREEZE PARTITION '2026-09' WITH NAME 'pre_merge_202609';

-- Снапшот всей таблицы
ALTER TABLE logs FREEZE;

-- Снапшот на всех репликах кластера
ALTER TABLE logs FREEZE ON CLUSTER '{cluster}';
```

**Workflow физического бэкапа:**
1. `ALTER TABLE ... FREEZE` — мгновенное создание hardlinks в `/var/lib/clickhouse/shadow/<N>/`.
2. Скопировать содержимое `shadow/` на внешний носитель (S3, NFS, ленту) — `rsync` или скрипт.
3. Очистить `shadow/` после копирования (утилита `clickhouse-backup` делает это автоматически).

```bash
# Пример: копирование снапшота на удалённый хост
rsync -av /var/lib/clickhouse/shadow/ backup-server:/backups/clickhouse/$(date +%F)/
```

**Важно:** `FREEZE` не реплицируется — создает снапшот только на локальном сервере. Для кластера используйте `FREEZE ON CLUSTER` (но каждый узел создаёт свой снапшот локально).

### FETCH PARTITION (восстановление с реплики)

```sql
-- Скачать партицию с другой реплики (восстановление повреждённой партиции)
ALTER TABLE logs FETCH PARTITION '2026-09' FROM '/clickhouse/tables/{shard}/logs';

-- После FETCH присоединить партицию
ALTER TABLE logs ATTACH PARTITION '2026-09';
```

`FETCH` загружает партицию с указанного пути (реплики) по сети. Полезно для восстановления повреждённых частей без полного бэкапа.

### clickhouse-backup (автоматизация)

`clickhouse-backup` (Altinity) — стандартный инструмент для автоматизации физических бэкапов. Использует `FREEZE` + копирование с поддержкой S3, инкрементальных копий, retention и parallel upload.

**Установка:**
```bash
# Скачать последний релиз
VERSION=$(curl -s https://api.github.com/repos/Altinity/clickhouse-backup/releases/latest | grep '"tag_name"' | cut -d'"' -f4)
wget https://github.com/Altinity/clickhouse-backup/releases/download/${VERSION}/clickhouse-backup-linux-amd64.tar.gz
tar xzf clickhouse-backup-linux-amd64.tar.gz
mv clickhouse-backup/clickhouse-backup /usr/local/bin/
chmod +x /usr/local/bin/clickhouse-backup
```

**Конфигурация (`/etc/clickhouse-backup/config.yml`):**
```yaml
general:
  remote_storage: s3
  disable_progress_bar: true
  backups_to_keep_local: 3
  backups_to_keep_remote: 30
  log_level: info
  allow_empty_backups: false

clickhouse:
  username: default
  password: ""
  host: localhost
  port: 9000
  skip_tables:
    - system.*
    - INFORMATION_SCHEMA.*
    - information_schema.*
  timeout: 5m
  log_sql_queries: false

s3:
  access_key: "<access_key>"
  secret_key: "<secret_key>"
  bucket: "clickhouse-backups"
  endpoint: "https://s3.us-east-1.amazonaws.com"
  region: "us-east-1"
  acl: "private"
  force_path_style: false
  path: "cluster-prod/node-1/"
  disable_ssl: false
  compression_level: 1
  compression_format: "tar"
```

**Создание бэкапа:**
```bash
# Полный бэкап
clickhouse-backup create full-$(date +%F)

# Инкрементальный бэкап (от базового)
clickhouse-backup create --base-backup-name="full-$(date +%F)" incr-$(date +%F)

# Загрузка в S3
clickhouse-backup upload full-$(date +%F)
```

**Восстановление:**
```bash
# Скачать бэкап
clickhouse-backup download full-20261004

# Восстановить
clickhouse-backup restore full-20261004
```

**Автоматизация через systemd:**
```bash
# /etc/systemd/system/clickhouse-backup.service
[Unit]
Description=ClickHouse backup
After=network.target

[Service]
Type=oneshot
User=clickhouse
ExecStart=/usr/local/bin/clickhouse-backup create full-$(date +%F)
ExecStart=/usr/local/bin/clickhouse-backup upload full-$(date +%F)

# /etc/systemd/system/clickhouse-backup.timer
[Unit]
Description=Daily ClickHouse backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

### Бэкап ClickHouse Keeper

Keeper хранит состояние в `log_storage_path` (по умолчанию `/var/lib/clickhouse/coordination/log` для встроенного Keeper, `/var/lib/clickhouse-keeper/log` для standalone) и снапшотах в `snapshots/`.

```bash
# 1. Остановить Keeper (для консистентности)
systemctl stop clickhouse-keeper

# 2. Скопировать данные координации
rsync -av /var/lib/clickhouse/coordination/ backup-server:/backups/keeper/$(date +%F)/

# 3. Запустить Keeper
systemctl start clickhouse-keeper
```

**Важно:** бэкап Keeper нужен для восстановления метаданных репликации (znode с частями, очередями, DDL). Без него при полной потере кластера придётся пересоздавать метаданные вручную.

### Политики хранения бэкапов (retention)

Стратегия хранения бэкапов определяется RPO и доступным местом:

| Стратегия | Описание | Кейс |
| :--- | :--- | :--- |
| **GFS (Grandfather-Father-Son)** | Дневные (7), недельные (4), месячные (12) бэкапы | Стандартная политика для compliance |
| **Инкрементальная цепочка** | Полный + цепочка инкрементов | Экономия места, быстрая ротация |
| **Tiered retention** | Горячие (7 дней) → холодные (90 дней) → архив (1 год) | Баланс скорости восстановления и стоимости |

**Реализация retention для `clickhouse-backup`:**
```bash
# Настройка через config.yml
# general.backups_to_keep_local: 3  — держать 3 последних локальных
# general.backups_to_keep_remote: 30  — держать 30 последних удалённых

# Ручная очистка старых бэкапов (GNU date)
# Удалить локальные бэкапы старше 7 дней
clickhouse-backup list --local | awk 'NR>1{print $1}' | while read b; do
    if [[ "$b" < "$(date -d '7 days ago' +%Y%m%d)" ]]; then
        clickhouse-backup delete --local "$b"
    fi
done

# Удалить удалённые бэкапы старше 30 дней
clickhouse-backup list --remote | awk 'NR>1{print $1}' | while read b; do
    if [[ "$b" < "$(date -d '30 days ago' +%Y%m%d)" ]]; then
        clickhouse-backup delete --remote "$b"
    fi
done
```

**Важно:** при удалении инкрементального бэкапа убедитесь, что базовый (full) бэкап сохранён — иначе цепочка инкрементов станет непригодной.

## Операции и команды

### Мониторинг нативных BACKUP/RESTORE

```sql
-- История операций (из system.backups, не persistent — сбрасывается при restart)
SELECT id, name, status, error, start_time, end_time,
       num_files, total_size, uncompressed_size, compressed_size
FROM system.backups
ORDER BY start_time DESC
LIMIT 10;

-- Лог операций (persistent)
SELECT event_date, event_time_microseconds, id, name, status, error
FROM system.backup_log
WHERE event_date = today()
ORDER BY event_time_microseconds DESC;

-- Инкрементальные бэкапы с указанием базового
SELECT name, base_backup_name, status
FROM system.backups
WHERE base_backup_name != '';

-- Активные асинхронные операции
SELECT id, name, status
FROM system.backups
WHERE status IN ('CREATING_BACKUP', 'RESTORING');
```

**Колонки `system.backups`:**

| Колонка | Тип | Описание |
| :--- | :--- | :--- |
| `id` | String | UUID операции (или указанный через `SETTINGS id=...`) |
| `name` | String | Имя хранилища (например, `S3('...', '...', '...')`) |
| `base_backup_name` | String | Базовый бэкап для инкремента (пусто для full) |
| `query_id` | String | Query ID операции |
| `status` | Enum8 | `CREATING_BACKUP`, `BACKUP_CREATED`, `BACKUP_FAILED`, `RESTORING`, `RESTORED`, `RESTORE_FAILED`, `BACKUP_CANCELLED`, `RESTORE_CANCELLED` |
| `error` | String | Сообщение об ошибке (если есть) |
| `start_time` | DateTime64(6) | Время начала |
| `end_time` | DateTime64(6) | Время окончания |
| `num_files` | UInt64 | Количество файлов |
| `total_size` | UInt64 | Размер файлов |
| `num_entries` | UInt64 | Количество entries (может отличаться от num_files для инкрементов) |
| `uncompressed_size` | UInt64 | Несжатый размер |
| `compressed_size` | UInt64 | Сжатый размер |
| `files_read` | UInt64 | Файлы прочитаны при RESTORE |
| `bytes_read` | UInt64 | Байты прочитаны при RESTORE |
| `settings` | Map | Использованные settings |
| `engine_settings` | Map | Engine-specific settings (S3, Azure) |

### Локальный BACKUP

```sql
-- Полный бэкап на локальный диск
BACKUP TABLE mydb.logs TO File('/backups/clickhouse/logs.zip');

-- Инкрементальный
BACKUP TABLE mydb.logs TO File('/backups/clickhouse/logs-inc.zip')
SETTINGS base_backup = File('/backups/clickhouse/logs.zip');

-- С именованный id для мониторинга
BACKUP TABLE mydb.logs TO File('/backups/clickhouse/logs.zip')
SETTINGS id = 'backup-2026-10-04';
```

### Настройка параллельных бэкапов

```xml
<!-- config.xml -->
<clickhouse>
    <backups>
        <allow_concurrent_backups>true</allow_concurrent_backups>
        <allow_concurrent_restores>true</allow_concurrent_restores>
    </backups>
</clickhouse>
```

По умолчанию параллельные бэкапы разрешены (`true`). При `false` — только одна операция на кластере.

### Атомарность RESTORE

`RESTORE` не транзакционен — не откатывает при ошибке. Таблицы обрабатываются независимо: таблица, чей restore завершился, остаётся восстановленной даже если другая таблица в том же запросе упала.

Чтобы восстанавливать партиции независимо:
```sql
RESTORE TABLE db.t0 PARTITIONS '2026-06-01' FROM S3('...', '<key>', '<secret>')
SETTINGS allow_non_empty_tables = true;
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `BACKUP` не завершается | Нет доступа к S3, нехватка места | Проверить credentials, квоту S3, место на диске |
| `RESTORE ... already exists` | Таблица уже существует с данными | Использовать `AS new_table` для ренейма, или `allow_non_empty_tables=true` |
| `FREEZE` не создаёт снапшот | Нет прав на `shadow/` | Проверить права `/var/lib/clickhouse/shadow/` |
| `FREEZE` медленна | Активные запросы к таблице | Дождаться завершения запросов или использовать `FREEZE ... ON CLUSTER` с остановкой записи |
| `RESTORE` не находит таблицу | Бэкап другой таблицы или путь неверный | Проверить путь в `BACKUP ... TO`; использовать `clickhouse-backup list` |
| `FETCH PARTITION` не работает | Путь реплики неверный или партиция отсутствует | Проверить путь в `FROM` (ZooKeeper путь, например `/clickhouse/tables/{shard}/logs`); наличие партиции на реплике |
| Инкрементальный бэкап огромен | Базовый бэкап слишком старый | Обновить базовый бэкап; проверить `base_backup` в `system.backups` |
| `BACKUP_ALREADY_EXISTS` | Бэкап с таким именем уже существует | Использовать новое имя; или удалить старый через `system` |
| Keeper не восстанавливается | Несогласованный бэкап `log`/`snapshots` | Копировать оба каталога (`log` + `snapshots`); останавливать Keeper перед копированием |
| `FREEZE` после power loss исчезает | Hardlinks не синхронизированы на диске (см. issue #111331) | Использовать `fsync_part_directory=1` для таблиц; регулярно архивировать `shadow/` после `FREEZE` |
| Потеря снапшота при `DETACH PARTITION` | Тот же unsynced путь (issue #111331/#111382) | Использовать `fsync_part_directory=1` |

## Лучшие практики

1. **Комбинируйте методы:** репликация (HA) + `clickhouse-backup` на S3 (DR) + Kafka replay (поток).
2. **Инкрементальные бэкапы** для частого резервирования без перегрузки.
3. **`FREEZE` перед структурными изменениями** — мгновенный снапшот.
4. **Бэкапьте Keeper** вместе с данными — без метаданных репликации кластер не восстановить.
5. **Тестируйте восстановление** (restore-drills) — не только создание бэкапов.
6. **RPO/RTO зафиксируйте** и сверяйтесь с ними при выборе частоты бэкапов.
7. **Храните бэкапы в другом AZ/регионе** — не в том же, что и кластер.
8. **Шифруйте бэкапы** (S3 SSE, шифрование на стороне клиента).
9. **Настраивайте retention** через `backups_to_keep_local`/`backups_to_keep_remote` в `clickhouse-backup` или через cron-скрипты.
10. **Используйте `ASYNC`** для долгих бэкапов — мониторьте через `system.backups`.
11. **Не удаляйте базовый бэкап** при инкрементальной цепочке — иначе все инкременты становятся непригодными.
12. **Связывайте с systemd timers** для автоматизации `clickhouse-backup`.

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- `clickhouse-backup` (установка и конфиг) — **[Эксплуатация](./clickhouse-operations.md#резервное-копирование-и-восстановление)**.
- FREEZE/FETCH в операционном SQL — **[Операционный SQL](./clickhouse-sql-operations.md#freeze--fetch-partition-бэкапы-через-hardlinks)**.
- Репликация и quorum — **[Кластер](./clickhouse-cluster.md)**.
- Отказоустойчивость и DR — **[DR](./clickhouse-disaster-recovery.md)**.

### Ресурсы

- [Документация: BACKUP / RESTORE](https://clickhouse.com/docs/concepts/features/backup-restore)
- [Документация: system.backups](https://clickhouse.com/docs/reference/system-tables/backups)
- [Документация: system.backup_log](https://clickhouse.com/docs/reference/system-tables/backup_log)
- [Документация: FREEZE PARTITION](https://clickhouse.com/docs/sql-reference/statements/alter/other#freeze)
- [clickhouse-backup (Altinity)](https://github.com/Altinity/clickhouse-backup)
- [RPO/Power-loss FREEZE issue #111331](https://github.com/ClickHouse/ClickHouse/issues/111331)