# Резервное копирование и восстановление MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**`mariadb-backup`** — основной инструмент для создания «горячих» **физических** бэкапов. Является форком Percona XtraBackup, полностью оптимизированным под архитектуру MariaDB, включая поддержку движков MyRocks, Aria и новых атомарных бинарных логов InnoDB (Binlog-in-InnoDB, MariaDB 12.3 LTS).

**`mariadb-dump`** — стандартная утилита для создания **логических** резервных копий (SQL-дампов). Подходит для небольших БД, миграций между мажорными версиями или когда требуется перенос данных между разными форками MySQL. Начиная с MariaDB 11.4.1 поддерживает параллельный дамп (`--parallel`), начиная с 11.5 — пакетный режим (`--dir`).

**`mydumper` / `myloader`** — альтернативный набор утилит для многопоточного логического бэкапа. Рекомендуется для БД объемом от 50 ГБ, где стандартный `mariadb-dump` становится узким местом. Поддерживает компрессию zstd/gzip и фильтрацию по таблицам/потокам.

**Point-in-Time Recovery (PITR)** — процесс восстановления базы данных до точно определенного момента времени в прошлом путем наката бинарных логов (WAL) на предварительно восстановленный полный физический бэкап. В MariaDB 10.8+ поддерживается позиционирование по GTID; в 11.4+ ускорено индексом `binlog_gtid_index`.

**SST (State Snapshot Transfer)** — процесс полной синхронизации данных нового узла Galera Cluster с существующим донором. `mariadb-backup` является методом SST по умолчанию (рекомендуемым) для минимизации блокировок.

**IST (Incremental State Transfer)** — инкрементальная передача данных в Galera Cluster. Передаются только транзакции, пропущенные узлом, из gcache. Не блокирует донора. Используется, когда узел пропустил небольшой объем транзакций, и они все еще находятся в gcache.

**FTWRL (FLUSH TABLES WITH READ LOCK)** — глобальная блокировка чтения/записи на время создания консистентного бэкапа. `mariadb-backup` минимизирует необходимость в FTWRL за счет копирования файлов данных на уровне страниц InnoDB, но для не-InnoDB движков (Aria, MyISAM) кратковременная блокировка может потребоваться.

**Layered Encryption** — практика двойного шифрования бэкапа: на уровне данных (TDE InnoDB/Aria) и на уровне архива (внешний инструмент — OpenSSL, GPG, 7z). Рекомендуется для смешанных сред, где часть таблиц зашифрована, а часть нет.

**Backup Catalog (Каталог бэкапов)** — систематизированный реестр бэкапов с метаданными: дата, тип (full/inc/logical), GTID-позиция, размер, контрольные суммы. Критичен для быстрого PITR и аудита.

## Базовые концепции

### Иерархия методов резервного копирования

MariaDB поддерживает три уровня резервного копирования, которые комбинируются для достижения целевых RPO/RTO:

```
┌─────────────────────────────────────────────────────────────┐
│                     Уровень 1: Физический                    │
│              mariadb-backup (hot physical)                   │
│  • Полный (full) — копирование всех страниц данных          │
│  • Инкрементальный (L1/L2) — только измененные страницы     │
│  • Сжатие: --stream=xbstream + gzip/zstd/openssl            │
│  • Шифрование: --encrypted-backup + layered encryption      │
├─────────────────────────────────────────────────────────────┤
│                     Уровень 2: Логический                    │
│         mariadb-dump (--parallel) / mydumper                 │
│  • Полный дамп всех БД/таблиц                               │
│  • Частичный дамп (--where, --ignore-table)                  │
│  • Пакетный режим (--dir, MariaDB 11.5+)                     │
├─────────────────────────────────────────────────────────────┤
│                     Уровень 3: Бинарные логи                 │
│                   binlog / GTID archiving                    │
│  • PITR: накат binlog на физический бэкап                   │
│  • GTID index (11.4+) ускоряет поиск позиции               │
│  • Ротация: binlog_expire_logs_seconds                      │
└─────────────────────────────────────────────────────────────┘
```

### Physical vs Logical: сравнение для SRE

| Характеристика | Physical (mariadb-backup) | Logical (mariadb-dump / mydumper) |
| :--- | :--- | :--- |
| **Скорость создания** | Высокая (копирование страниц) | Низкая (SELECT + генерация SQL) |
| **Скорость восстановления** | Очень высокая (копирование + накат) | Низкая (INSERT + построение индексов) |
| **Размер бэкапа** | Большой (равен объему данных) | Малый (текстовое сжатие) |
| **Блокировки** | Минимальные (не блокирует R/W) | Зависят от флагов (могут блокировать DDL) |
| **Версионность** | Только та же мажорная версия | Можно восстанавливать на другие версии |
| **Совместимость с движками** | InnoDB, Aria, MyRocks (полная) | Все движки (включая S3, Archive) |
| **Сжатие** | Внешнее (xbstream + gzip/zstd) | Встроенное (--compress) |
| **Шифрование** | На уровне файлов + layered | Текстовое (не рекомендуется для production) |

### Архитектура физического бэкапа (mariadb-backup)

`mariadb-backup` работает на уровне файлов данных, копируя измененные страницы InnoDB в реальном времени:

1.  **Копирование файлов:** Инструмент читает `.ibd` файлы табличных пространств InnoDB и файлы Aria. При включенном `binlog_storage_engine=innodb` (MariaDB 12.3 LTS) бинарные логи также хранятся в табличном пространстве и копируются автоматически.
2.  **Отслеживание изменений:** Создается снимок LSN (Log Sequence Number) в момент начала бэкапа. Все страницы, измененные после этого LSN, копируются в инкрементальном режиме.
3.  **Фаза prepare:** Накат redo-логов на файлы данных для приведения бэкапа к консистентному состоянию. Для цепочки инкрементальных бэкапов: все кроме последнего применяются с флагом `--apply-log-only`, последний — без флага.
4.  **Фаза restore:** Копирование файлов обратно в `datadir` через `--copy-back` (или `--move-back` для перемещения).

**Важно:** `mariadb-backup` не требует `FLUSH TABLES WITH READ LOCK` для InnoDB-таблиц благодаря snapshot-механизму. Для Aria/MyISAM кратковременная блокировка может потребоваться.

### Шифрование бэкапов

**Encryption at Rest (TDE):**
- Если на сервере включено шифрование InnoDB/Aria (`file_key_management` или внешний KMS), `mariadb-backup` копирует зашифрованные файлы как есть.
- На этапе `--prepare` инструменту требуется доступ к тем же ключам, что и у сервера, для применения redo-логов к зашифрованным таблицам.
- На этапе `--copy-back` целевой сервер должен иметь идентичные ключи. При несовпадении — таблицы будут помечены как corrupted.

**Layered Encryption (рекомендуется):**
- Потоковая компрессия + шифрование через внешние инструменты: `--stream=xbstream | gzip | openssl enc -aes-256-cbc`.
- Защищает не только зашифрованные таблицы, но и метаданные, имена файлов, системные таблицы.
- Восстановление требует два набора credentials: внешний пароль для потока + KMS-ключи MariaDB.

### Безопасность бэкапов

Бэкап — полная копия данных, поэтому к нему применимы те же требования безопасности, что и к самому инстансу. Утечка бэкапа эквивалентна утечке базы.

**Контроль доступа:**
- Бэкапы хранятся на отдельном носителе/сервере с правами `0700`/`0600`, владелец — выделенный пользователь (не `mysql`, не `root` повседневного администрирования).
- Учётная запись для бэкапа имеет минимальные привилегии: `RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT` — без `SUPER` и `FILE`.
- Доступ к хранилищу бэкапов — по отдельным учётным записям, не совпадающим с доступом к инстансу.

**Управление ключами:**
- Ключи шифрования бэкапов (внешний пароль `openssl`/`gpg` и KMS-ключи MariaDB) хранятся отдельно от бэкапов — в Vault или на air-gapped носителе.
- Компрометация хранилища бэкапов без ключей не приводит к утечке данных (при layered encryption).

**Целостность и неизменяемость:**
- Контрольные суммы (`sha256sum`) для каждого бэкапа; проверка перед восстановлением.
- Immutable/air-gapped копия (WORM-хранилище, Object Lock) — защита от ransomware и случайного удаления.
- Стратегия 3-2-1-1-0: 3 копии, 2 носителя, 1 вне площадки, 1 immutable, 0 ошибок при проверке.

**Секреты в бэкапах:**
- Системные таблицы (`mysql.user`) содержат хеши паролей — бэкап системных таблиц чувствителен.
- Логические дампы могут содержать данные из `SELECT`-запросов в slow/general log — исключите логи из бэкапа или зашифруйте.

**Верификация восстановления:**
- Тестовое восстановление на изолированном сервере — не реже раза в квартал.
- Проверка: `mariadb-backup --prepare` без ошибок, `CHECKSUM TABLE` на восстановленных данных, сравнение контрольных сумм.

Подробнее о шифровании и ключах: [Шифрование данных (TDE)](security/tde.md), [HashiCorp Vault](../../Vault/overview.md).

### Компрессия

**Устаревший подход:** `--compress` (QuickLZ) устарел и будет удален. Рекомендуется потоковая компрессия:

```bash
mariadb-backup --backup --stream=xbstream | zstd - -o backupstream.zst
```

**Параметры потокового бэкапа:**
- `--stream=xbstream` — вывод в поток (stdout) вместо файловой системы.
- `--extra-lsndir=/path` — запись `xtrabackup_checkpoints` в отдельный каталог (необходимо для инкрементальных бэкапов из потока).
- Внешний инструмент: `gzip` (широко доступен), `zstd` (лучшее сжатие/скорость), `openssl`, `gpg`, `7z`.

### PITR: архитектура восстановления

PITR требует трех компонентов:
1. **Полный физический бэкап** — базовая точка восстановления.
2. **Бинарные логи** — журнал всех изменений после бэкапа.
3. **GTID или позиция файла** — точка старта для наката.

**GTID-based PITR (рекомендуется, MariaDB 10.8+):**
- `mariadb-binlog --start-position=GTID --stop-position=GTID` — точное позиционирование.
- `binlog_gtid_index=ON` (11.4+, default) ускоряет поиск GTID в binlog.
- Преимущество: не зависит от имен файлов и смещений, устойчив к ротации логов.

**File:Offset PITR (legacy):**
- `mariadb-binlog --start-position=N --stop-datetime="..."` — позиционирование по смещению.
- Менее надежен в кластерных средах, где файлы могут ротироваться на разных узлах.

**Важно:** Для PITR требуется `binlog_expire_logs_seconds` настроен с запасом: не менее `максимальный_лаг_реплики + 1 день`. Без этого старые логи удалятся, и восстановление будет невозможным.

## Предварительные требования

### Требования к оборудованию и ОС

- **ОЗУ:** Минимум 2GB для тестовых сред. Production: минимум 8GB, рекомендуется 16GB+.
- **Диск:** Поддерживаются любые файловые системы, совместимые с `O_DIRECT` (ext4, XFS, ZFS). Для потоковых бэкапов убедитесь, что `/tmp` или целевой каталог имеют достаточно места для временных файлов.
- **Ядра Linux:** 5.4+ для стабильной работы Thread Pool и Transparent Huge Pages.
- **Права доступа:** Пользователь `mysql` должен иметь права на запись в `datadir`, каталог логов и каталог сокета. Для бэкапов требуется отдельный пользователь с привилегиями `RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT`.

### Подготовка ОС

```bash
# Проверка прозрачных огромных страниц (THP)
cat /sys/kernel/mm/transparent_hugepage/enabled
# → рекомендуется: never

# Проверка лимитов файловых дескрипторов
ulimit -n
# → должно быть >= 65535 для production

# Проверка vm.swappiness
cat /proc/sys/vm/swappiness
# → рекомендуется: 1
```

**Валидация:**

```bash
# Проверка vm.swappiness
sysctl vm.swappiness
# → vm.swappiness = 1

# Проверка открытых файловых дескрипторов для mysql
cat /proc/$(pidof mysqld)/limits | grep "open files"
# → Max open files 65535 65535 files
```

### Подготовка пользователя для бэкапов

```sql
-- Создание пользователя с минимально необходимыми правами
CREATE USER 'backup_admin'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT ON *.* TO 'backup_admin'@'localhost';
GRANT SELECT ON performance_schema.* TO 'backup_admin'@'localhost';
GRANT SELECT ON mysql.* TO 'backup_admin'@'localhost';
FLUSH PRIVILEGES;
```

**Валидация:**

```bash
# Проверка подключения
mariadb -u backup_admin -p -e "SHOW DATABASES;"
# → список БД

# Проверка прав
mariadb -u backup_admin -p -e "SHOW GRANTS FOR CURRENT_USER();"
# → GRANT RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT ON *.* TO ...
```

## Практические сценарии

### Сценарий 1: Полный физический бэкап (mariadb-backup)

Используется для минимизации RTO в Production-средах. Полный бэкап — база для всех последующих инкрементальных копий и PITR.

```bash
mariadb-backup --backup \
    --target-dir=/data/backups/full_$(date +%Y%m%d_%H%M%S) \
    --user=backup_admin --password=STRONG_PASSWORD \
    --slave-info --binlog-info --galera-info
# → result: В каталоге создается копия файлов .ibd, .frm (если есть), логов транзакций и метаданных.
```

**Ключевые опции:**
- `--slave-info` — записывает позицию репликации в `xtrabackup_slave_info` (для Source-Replica топологий).
- `--binlog-info` — записывает позицию бинарного лога в `mariadb_backup_binlog_info` (для PITR).
- `--galera-info` — записывает GTID и состояние кластера Galera в `xtrabackup_galera_info` (для восстановления SST).

**Валидация:**

```bash
# Проверка контрольных сумм
mariadb-backup --prepare --target-dir=/data/backups/full_20260930_120000
# → backup prepared successfully

# Проверка метаданных
cat /data/backups/full_20260930_120000/xtrabackup_checkpoints
# → backup_type = 1 (full), from_lsn = 123456, to_lsn = 789012

cat /data/backups/full_20260930_120000/mariadb_backup_binlog_info
# → filename = 'mariadb-bin.000123', position = 45678, GTID = '1-123-456'
```

### Сценарий 2: Инкрементальный физический бэкап (mariadb-backup)

Минимизирует объем хранимых данных и время создания бэкапа.

```bash
# Создание полного (Full) бэкапа (базовый)
mariadb-backup --backup \
    --target-dir=/data/backups/full_base \
    --user=backup_admin --password=STRONG_PASSWORD \
    --slave-info --binlog-info

# Создание первого инкрементального бэкапа (L1)
mariadb-backup --backup \
    --target-dir=/data/backups/inc_L1 \
    --incremental-basedir=/data/backups/full_base \
    --user=backup_admin --password=STRONG_PASSWORD

# Создание второго инкрементального бэкапа (L2)
mariadb-backup --backup \
    --target-dir=/data/backups/inc_L2 \
    --incremental-basedir=/data/backups/inc_L1 \
    --user=backup_admin --password=STRONG_PASSWORD
```

**Подготовка к восстановлению:**

```bash
# А) Подготовка базового бэкапа (не завершаем транзакции!)
mariadb-backup --prepare --apply-log-only --target-dir=/data/backups/full_base

# Б) Накат первого инкремента
mariadb-backup --prepare --apply-log-only --target-dir=/data/backups/full_base \
               --incremental-dir=/data/backups/inc_L1

# В) Накат второго инкремента
mariadb-backup --prepare --apply-log-only --target-dir=/data/backups/full_base \
               --incremental-dir=/data/backups/inc_L2

# Г) Финальный Prepare (завершаем незавершенные транзакции)
mariadb-backup --prepare --target-dir=/data/backups/full_base
```

**Важно:** Для инкрементальных бэкапов из потока используйте `--extra-lsndir` для сохранения `xtrabackup_checkpoints` отдельно от потока.

### Сценарий 3: Потоковый бэкап с компрессией и шифрованием

Рекомендуется для production-сред, где необходимо минимизировать место на диске и обеспечить безопасность бэкапов.

```bash
# Потоковый бэкап: компрессия zstd + шифрование OpenSSL AES-256
mariadb-backup --backup \
    --user=backup_admin --password=STRONG_PASSWORD \
    --stream=xbstream \
    --extra-lsndir=/data/backups/lsn_tmp \
    | zstd - -o /data/backups/full_$(date +%Y%m%d).xb.zst \
    && rm -rf /data/backups/lsn_tmp

# Восстановление: дешифрование + декомпрессия + распаковка
# 1. Расшифровать и декомпрессировать
# 2. Распаковать xbstream
mbstream -x < full_20260930.xb.zst.dec

# 3. Подготовить (apply logs)
mariadb-backup --prepare --target-dir=/data/backups/full_20260930

# 4. Восстановить (copy-back)
mariadb-backup --copy-back --target-dir=/data/backups/full_20260930
```

**Валидация:**

```bash
# Проверка контрольной суммы архива
sha256sum /data/backups/full_20260930.xb.zst
# → e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

# Проверка содержимого архива (без распаковки)
mbstream -t < full_20260930.xb.zst
# → перечисление всех файлов в архиве

# Проверка после восстановления
mariadb -u root -e "SHOW DATABASES;"
# → список БД совпадает с исходным сервером
```

### Сценарий 4: Логический бэкап (mariadb-dump)

Для миграций, тестовых сред и резервных копий небольших БД.

```bash
# Консистентный дамп всей БД с хранимыми объектами и GTID
mariadb-dump --user=root --password \
    --all-databases \
    --single-transaction \
    --routines --triggers --events \
    --master-data=2 \
    --gtid \
    --compress \
    --order-by-primary \
    > /data/backups/full_dump_$(date +%Y%m%d).sql
```

**Ключевые опции:**
- `--single-transcation` — не блокирует чтение/запись в InnoDB (MVCC snapshot). Не работает для Aria/MyISAM.
- `--routines --triggers --events` — включает хранимые процедуры, функции, триггеры и события.
- `--master-data=2` — записывает позицию бинарного лога в дамп (закомментированная строка).
- `--gtid` — включает GTID в дамп (MariaDB 10.10+).
- `--compress` — сжатие данных в протоколе клиент-сервер.
- `--order-by-primary` — ускоряет импорт, упорядочивая строки по PRIMARY KEY.

**Валидация:**

```bash
# Проверка размера дампа
ls -lh /data/backups/full_dump_20260930.sql

# Проверка начала файла (GTID и master-data)
head -20 /data/backups/full_dump_20260930.sql
# → SET @MARIADB_MASTER_LOG_INFO = ...;
# → SET @@GLOBAL.GTID_PURGED = '1-123-456,...';
```

### Сценарий 5: Параллельный логический бэкап (mariadb-dump --parallel)

Начиная с MariaDB 11.4.1, `mariadb-dump` поддерживает параллельный дамп через `--parallel` и пакетный режим через `--dir`.

```bash
# Параллельный дамп в 8 потоков
mariadb-dump --user=root --password \
    --all-databases \
    --parallel=8 \
    --single-transaction \
    --routines --triggers --events \
    --compress \
    --outputdir=/data/backups/parallel_dump_$(date +%Y%m%d)

# Пакетный режим (MariaDB 11.5+)
mariadb-dump --user=root --password \
    --all-databases \
    --dir=/data/backups/batch_dump_$(date +%Y%m%d) \
    --parallel=8
```

**Восстановление:**

```bash
# Восстановление из параллельного дампа
mariadb-dump --user=root --password \
    --parallel=8 \
    --inputdir=/data/backups/parallel_dump_20260930 \
    | mariadb --user=root --password
```

### Сценарий 6: Многопоточный логический бэкап (mydumper)

Для БД объемом от 50 ГБ, где стандартный `mariadb-dump` становится узким местом.

```bash
# Бэкап в 8 потоков с компрессией zstd
mydumper --user=root --password=STRONG_PASSWORD \
         --threads=8 \
         --compress --compress-algo=zstd \
         --long-query-guard=60 \
         --outputdir=/data/backups/mydumper_$(date +%Y%m%d)

# Восстановление через myloader
myloader --user=root --password=STRONG_PASSWORD \
         --directory=/data/backups/mydumper_20260930 \
         --threads=8
```

**Валидация:**

```bash
# Проверка количества загруженных строк
mariadb -u root -p -e "SELECT COUNT(*) FROM information_schema.tables;"
# → совпадает с исходным сервером
```

### Сценарий 7: Point-in-Time Recovery через GTID (MariaDB 10.8+)

Восстановление данных после случайного `DROP TABLE` в 14:30. Бэкап был создан в 00:00.

```bash
# 1. Восстанавливаем последний физический бэкап
mariadb-backup --copy-back --target-dir=/data/backups/full_20260930

# 2. Извлекаем GTID позицию из файла бэкапа
GTID_START=$(grep -oP 'GTID = \K[^,\s]+' /data/backups/full_20260930/xtrabackup_binlog_info)
# → 1-123-456

# 3. Извлекаем данные из бинарных логов с момента бэкапа до ошибки
mariadb-binlog --start-position="$GTID_START" \
               --stop-datetime="2026-08-17 14:30:00" \
               --base64-output=DECODE-ROWS -v \
               /var/lib/mysql/binlog.000010 > recovery_pitr.sql

# 4. Накатываем логи на восстановленную базу
mariadb -u root < recovery_pitr.sql
```

**Альтернатива: File:Offset PITR (legacy):**

```bash
mariadb-binlog --start-position=45678 \
               --stop-datetime="2026-08-17 14:30:00" \
               --base64-output=DECODE-ROWS -v \
               /var/lib/mysql/binlog.000010 > recovery_pitr.sql
```

**Валидация:**

```sql
-- Проверка восстановленной таблицы
SELECT COUNT(*) FROM app_db.users;
-- → 150000

-- Проверка GTID-позиции
SELECT @@GLOBAL.GTID_PURGED;
-- → должен включать все транзакции до момента восстановления
```

### Сценарий 8: Резервное копирование и восстановление Galera Cluster

Для Galera Cluster используйте физические бэкапы (`mariadb-backup`), которые также служат методом SST:

```bash
# Физический бэкап на одном из узлов (не блокирует запись на других узлах)
mariadb-backup --user=backup --password \
  --backup \
  --target-dir=/backup/galera_node1_$(date +%Y%m%d_%H%M%S) \
  --galera-info \
  --slave-info --binlog-info
```

**Восстановление после сбоя всех узлов:**

1. Остановите все узлы кластера.
2. Восстановите бэкап на одном из узлов: `mariadb-backup --copy-back --target-dir=/backup/galera_node1_20260930`.
3. Запустите этот узел как новый кластер: `galera_new_cluster`.
4. По очереди присоединяйте остальные узлы через обычный `systemctl start mariadb`.

**Валидация:**

```sql
-- На каждом узле
SHOW STATUS LIKE 'wsrep_cluster_size';
-- → 3 (все узлы подключены)

SHOW STATUS LIKE 'wsrep_local_state_comment';
-- → Synced
```

## Устранение неполадок (Troubleshooting)

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`Redo log size mismatch`** | Попытка выполнить `--prepare` на версии сервера, отличной от той, где создавался бэкап. | Проверьте версии: `mariadb-backup --version` vs `SELECT VERSION();`. | Используйте `mariadb-backup` той же версии, что и сервер-источник. |
| **`Can't connect to local server`** | Путь к сокету указан неверно или сервер не запущен. | Проверьте `SHOW VARIABLES LIKE 'socket';`. | Передайте `--socket=/run/mysqld/mysqld.sock` явно. |
| **OOM Killer при бэкапе** | `mariadb-backup` потребляет память при копировании. В системах с малым RAM потоковый бэкап может вызвать нехватку памяти. | `dmesg | grep -i oom`; `free -h`. | Уменьшите `--parallel` (по умолчанию 1). Используйте `ionice` и `nice` для снижения приоритета. |
| **Бэкап слишком большой** | Нет компрессии или используются неэффективные параметры. | `du -sh /data/backups/*`. | Используйте потоковый бэкап с `zstd` или `gzip`. Для инкрементальных стратегий — L1/L2. |
| **PITR не восстанавливает нужные данные** | Неправильная GTID-позиция или binlog удален ротацией. | Проверьте `binlog_expire_logs_seconds`; проверьте GTID в `xtrabackup_binlog_info`. | Увеличьте `binlog_expire_logs_seconds` (не менее `лаг_реплики + 1 день`). Используйте GTID вместо File:Offset. |
| **`prepare` падает на зашифрованных таблицах** | На целевом сервере нет доступа к KMS-ключам. | Проверьте, что `file_key_management` или KMS-плагин доступен. | Настройте идентичные ключи на целевом сервере перед `--prepare`. |
| **Сетевой разрыв при потоковом бэкапе** | При `--stream=xbstream` разрыв соединения приводит к неполному архиву. | Проверьте размер архива vs ожидаемый. | Используйте `mbstream` с проверкой целостности. Для удаленных хранилищ — `ssh` + `dd` или `mbstream` через pipe. |
| **Восстановление занимает слишком много времени** | Большой объем данных или отсутствие индексов после восстановления логического дампа. | `time mariadb-dump ...` для оценки. | Используйте физический бэкап для больших БД. После восстановления логического дампа выполните `ANALYZE TABLE`. |
| **`Created_tmp_disk_tables` растет после восстановления** | Временные таблицы превышают `tmp_table_size` при восстановлении. | `SHOW GLOBAL STATUS LIKE 'Created_tmp%';`. | Увеличьте `tmp_table_size` и `max_heap_table_size` на время восстановления. |
| **Galera SST не завершается** | Неверные учетные данные `wsrep_sst_auth`, блокировка порта, нехватка диска. | `journalctl -u mariadb | grep -i sst`. | Проверьте учетные данные, порты 4444/4567/4568, свободное место. |
| **Репликация останавливается после восстановления** | GTID-позиция восстановления не совпадает с позицией источника. | `SHOW REPLICA STATUS\G` — проверьте `Last_IO_Error`. | Используйте `RESET REPLICA ALL` и `CHANGE REPLICATION SOURCE TO ... SOURCE_USE_GTID=slave_pos`. |
| **MyRocks таблицы не восстанавливаются** | `mariadb-backup` не копирует данные MyRocks корректно при старых версиях. | Проверьте `SHOW TABLES WHERE ENGINE='MyRocks';` после восстановления. | Используйте `mariadb-backup` версии, совместимой с версией сервера. Для MyRocks 5.5+ требуетсяMariaDB 10.2+. |

## Лучшие практики (Best Practices)

1.  **Стратегия 3-2-1-1-0:** 3 копии данных (1 production + 2 бэкапа), 2 разных носителя, 1 копия вне площадки, 1 immutable/air-gapped бэкап, 0 ошибок при проверке. Для MariaDB: локальный диск + NFS/сетевое хранилище + ленточная библиотека или удаленный сервер.
2.  **Физические бэкапы для production:** Используйте `mariadb-backup` как основной метод. Логические бэкапы (`mariadb-dump`, `mydumper`) — для миграций, тестовых сред и мелких БД.
3.  **Инкрементальная стратегия:** Full раз в неделю + инкрементальные (L1) раз в день + binlog-архивирование раз в час. Это обеспечивает RPO < 1 час и RTO < 30 минут для большинства production-сценариев.
4.  **Валидация бэкапов:** После каждого бэкапа выполняйте `--prepare` на отдельном сервере или контейнере. Автоматизируйте проверку контрольных сумм и тестовое восстановление.
5.  **Шифрование:** Используйте layered encryption: TDE для чувствительных таблиц + `--stream=xbstream | openssl enc` для всего архива. Храните ключи отдельно от бэкапов.
6.  **Компрессия:** Используйте `zstd` вместо `gzip` для лучшего соотношения скорость/сжатие. Избегайте устаревшего `--compress` (QuickLZ).
7.  **Ротация binlog:** Настройте `binlog_expire_logs_seconds` не менее, чем `максимальный_лаг_реплики + 1 день`. Без этого PITR-восстановление будет невозможным.
8.  **GTID для PITR:** Используйте GTID вместо File:Offset. Начиная с MariaDB 10.8+, `mariadb-binlog` поддерживает `--start-position=GTID`. Включите `binlog_gtid_index=ON` (11.4+, default).
9.  **Привилегии:** Пользователь бэкапа должен иметь только `RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT`. Никаких прав `SUPER` или `FILE` (если не требуется).
10. **Хранение бэкапов:** Никогда не храните бэкапы на том же диске, где лежат данные БД. Используйте отдельный массив или сервер. Для immutable-бэкапов используйте WORM-хранилища или объектные хранилища с Object Lock.
11. **Каталог бэкапов:** Ведите реестр бэкапов (дата, тип, GTID, контрольные суммы). Автоматизируйте через скрипты или специализированные инструменты (Percona Toolkit, `backupninja`).
12. **Тестирование восстановления:** Регулярно (раз в квартал) выполняйте тестовое восстановление на staging. Без этого вы не узнаете о проблемах с целостностью бэкапа в момент инцидента.
13. **Galera:** Используйте `mariadb-backup` как метод SST. Настройте `wsrep_sst_auth` с надежным паролем. Для 2-узловых кластеров добавьте QDevice.
14. **MyRocks:** Для бэкапов MyRocks используйте `mariadb-backup`. Логические бэкапы через `mariadb-dump` требуют перестроения индексов при восстановлении.
15. **S3 Engine:** Резервное копирование S3-таблиц не требуется — объектное хранилище само по себе реплицировано. Но резервируйте метаданные (определения таблиц) через `mariadb-dump`.

## Особенности и ограничения (Edge Cases)

1.  **MyRocks и бэкапы:** При использовании MyRocks `mariadb-backup` копирует файлы RocksDB. Убедитесь, что версия `mariadb-backup` совместима с версией сервера. Логическое восстановление MyRocks через `mariadb-dump` требует перестроения индексов.
2.  **Galera и SST блокировка:** При использовании `rsync` или `mysqldump` как метода SST донор блокируется на время передачи данных. Всегда используйте `mariabackup` для production.
3.  **2-узловой кластер без arbitrator:** В Galera с 2 узлами без QDevice кворум может быть потерян при падении одного узла. Для HA-сценариев используйте 3 узла или 2 + QDevice.
4.  **Flow Control:** При перегрузке одного узла Flow Control замедляет весь кластер. Мониторьте `wsrep_flow_control_paused`. При создании бэкапа на узле Galera используйте `SET GLOBAL wsrep_desync = ON` для исключения влияния на кластер.
5.  **SST и блокировка донора:** При добавлении узла в Galera без `mariadb-backup` SST блокирует донора на время передачи данных. Для production всегда используйте `mariabackup`.
6.  **gtid_slave_pos после failover:** При переключении мастера в Source-Replica топологии `Seconds_Behind_Source` может показывать `NULL` или отрицательные значения в течение нескольких секунд. Настройте алерт с `for: >= 5m` и дополнительную проверку `Replica_IO_Running` / `Replica_SQL_Running`.
7.  **Ограничения `mariadb-dump`:** Флаг `--single-transaction` работает только для движков с MVCC (InnoDB). Для Aria/MyISAM он не снимает блокировки. Используйте `--lock-all-tables` для консистентности смешанных дампов.
8.  **Пароли в истории:** Даже с `--defaults-extra-file` убедитесь, что файл имеет права `0600` и не попал в репозиторий. Проверяйте через `git diff` перед коммитом.
9.  **Символические ссылки:** Старые имена (`mysqldump`, `mysqlbinlog`) являются символическими ссылками. При обновлении пакетов они могут быть удалены. Всегда используйте новые имена (`mariadb-dump`, `mariadb-binlog`) в скриптах.
10. **innodb_log_archive (13.0+):** Начиная с MariaDB 13.0, доступен `innodb_log_archive=ON` для PITR без зависимости от binlog. Это экспериментальная функция, не используйте в production без тестирования.

## Дополнительная информация

### См. также

- **[Конфигурация MariaDB](configuration.md)** — параметры бинарных логов, `binlog_expire_logs_seconds`, `binlog_gtid_index`.
- **[Мониторинг MariaDB](monitoring.md)** — отслеживание метрик бэкапов через Prometheus, алерты на рост `Created_tmp_disk_tables` и `wsrep_flow_control_paused`.
- **[Движки хранения MariaDB](storage_engines.md)** — особенности MyRocks и S3 Engine при бэкапах.
- **[Отказоустойчивость MariaDB](high_availability.md)** — использование `mariadb-backup` как метод SST, восстановление Galera после сбоя.
- **[Репликация MariaDB: Обзор](replication/overview.md)** — GTID, бинарные логи, Crash-safe Replication.
- **[Клиентские утилиты](client_utilities.md)** — `mariadb-dump`, `mariadb-binlog`, `mariadb-upgrade`.
- **[Обслуживание MariaDB](maintenance.md)** — `mariadb-check`, `mariadb-admin`, окна обслуживания.
- **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)** — обязательное создание бэкапа перед апгрейдом.

### Внешние ресурсы

- [MariaDB Backup Overview](https://mariadb.com/docs/server/server-usage/backup-and-restore/mariadb-backup/)
- [Point-In-Time Recovery (PITR)](https://mariadb.com/docs/server/server-usage/backup-and-restore/mariadb-backup/point-in-time-recovery-pitr-mariadb-backup)
- [Encryption and Compression Tools With mariadb-backup](https://mariadb.com/docs/server/server-usage/backup-and-restore/mariadb-backup/using-encryption-and-compression-tools-with-mariadb-backup)
- [mariadb-backup Options](https://mariadb.com/docs/server/server-usage/backup-and-restore/mariadb-backup/mariadb-backup-options)
- [MariaDB 12.3 Release Notes](https://mariadb.com/docs/release-notes/community-server/12.3/)
