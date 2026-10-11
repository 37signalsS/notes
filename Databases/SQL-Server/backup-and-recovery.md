# Резервное копирование и восстановление в SQL Server

**Актуально для:** SQL Server 2025 (17.x) / 2022 (16.x) / 2019 (15.x) — Windows и Linux

Специфичные для Microsoft SQL Server инструменты, модели восстановления и подходы. Общие теоретические основы (логические и физические бэкапы, правило 3-2-1, метрики RPO/RTO) описаны в разделе **[Стратегии резервного копирования баз данных](../Concepts/backups.md)**.

## Определения

- **Модель восстановления (Recovery Model)** — свойство базы данных, управляющее регистрацией транзакций в журнале, необходимостью бэкапов журнала и доступными операциями восстановления. Задаётся командой `ALTER DATABASE [DB] SET RECOVERY FULL|SIMPLE|BULK_LOGGED`.
- **Журнал транзакций (Transaction Log)** — файл с расширением `.ldf`, обеспечивающий ACID-свойства. Содержит записи обо всех изменениях данных.
- **Write-Ahead Logging (WAL)** — механизм, при котором изменения сначала фиксируются в журнале транзакций, а затем записываются в файлы данных (`.mdf`/`.ndf`). Фундамент работы бэкапов и восстановления.
- **Очистка журнала (Log Truncation)** — пометка неактивных записей журнала как перезаписываемых. В модели `SIMPLE` — при Checkpoint; в `FULL`/`BULK_LOGGED` — только после `BACKUP LOG`. Очистка не уменьшает файл `.ldf` физически (для этого нужен `SHRINK`, применяемый точечно).
- **Цепочка LSN (Log Sequence Number)** — каждая запись журнала и каждый бэкап имеют LSN. Для PITR необходима непрерывная цепочка бэкапов журнала с момента последнего полного (или дифференциального) бэкапа.
- **VLF (Virtual Log File)** — внутренняя логическая сегментация журнала. Избыток VLF (тысячи и десятки тысяч при частом приращении маленькими порциями) замедляет восстановление и старт базы. Рекомендуется фиксированный прирост большими порциями.
- **Checkpoint (Контрольная точка)** — запись «грязных» страниц из буферного пула на диск; сокращает время восстановления после сбоя.
- **Point-in-Time Recovery (PITR)** — возврат базы в состояние на произвольную метку времени (`STOPAT`). Доступно только в моделях `FULL` и `BULK_LOGGED` (в последней — не внутри массовой операции).
- **Tail-Log Backup (Бэкап хвоста журнала)** — резервная копия журнала перед началом восстановления, фиксирующая изменения, произошедшие после последнего бэкапа лога, даже если база повреждена (`WITH NO_TRUNCATE`).
- **Copy-Only Backup** — независимый бэкап, не влияющий на цепочку LSN и дифференциальную битовую карту.
- **STANDBY (режим ожидания)** — состояние восстановленной базы между накатом журналов: доступна только для чтения (undo-файл), позволяет применять логи порциями.
- **T-SQL Snapshot Backup** (SQL Server 2022+) — интеграция с аппаратными снимками хранилища: `SUSPEND_FOR_SNAPSHOT_BACKUP` замораживает I/O, затем записывается метаданный бэкап (`WITH METADATA_ONLY`).
- **ADR (Accelerated Database Recovery)** — технология (SQL Server 2019+), использующая версионирование строк для мгновенного отката транзакций и быстрого восстановления после сбоя.
- **ZSTD (Zstandard)** — алгоритм сжатия бэкапов (SQL Server 2025+), быстрее и эффективнее MS_XPRESS.
- **Неизменяемый бэкап (Immutable Backup)** — резервная копия, защищённая от удаления или модификации на уровне хранилища (WORM).

## Модели восстановления

| Модель | PITR | Протоколирование | Очистка лога | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **Simple** | Нет | Минимальное | Авто (Checkpoint) | Test, Dev, read-only базы |
| **Full** | Да | Полное | После `BACKUP LOG` | Production, критичные данные |
| **Bulk-Logged** | Частично | Оптимизированное (массовые операции — минимально) | После `BACKUP LOG` | Массовая загрузка данных |

**Важные следствия:**

- Переключение `FULL` → `SIMPLE` разрывает цепочку LSN: для восстановления потребуется новый полный бэкап.
- В `BULK_LOGGED` PITR невозможен внутрь массовой операции (BULK INSERT, SELECT INTO, индексные операции): восстановление возможно только до конца бэкапа журнала, содержащего эту операцию.
- Если в `FULL`/`BULK_LOGGED` не делать бэкапы лога, файл `.ldf` растёт до заполнения диска (ошибка 9002).

## Типы бэкапов

| Тип | T-SQL | Описание |
| :--- | :--- | :--- |
| **Полный (Full)** | `BACKUP DATABASE [DB] TO DISK = '...' WITH COMPRESSION, CHECKSUM` | Все данные + активная часть лога. Точка отсчёта цепочки. |
| **Дифференциальный** | `BACKUP DATABASE [DB] TO DISK = '...' WITH DIFFERENTIAL` | Изменения с последнего **Full** (не с последнего diff). Ускоряет восстановление. |
| **Журнал (Log)** | `BACKUP LOG [DB] TO DISK = '...'` | Только записи лога. Требуется для PITR; очищает журнал. |
| **Copy-Only** | `BACKUP DATABASE [DB] TO DISK = '...' WITH COPY_ONLY` | Не влияет на цепочку и дифференциальную битовую карту. |
| **Файловый / файловой группы** | `BACKUP DATABASE [DB] FILE = '...' TO DISK = '...'` | Бэкап части БД; для очень больших БД. |
| **Snapshot (метаданные)** | `BACKUP DATABASE [DB] TO DISK = '...' WITH METADATA_ONLY` | (SQL 2022+) Метаданные для аппаратного снимка хранилища — см. сценарий ниже. |

**Опции `WITH` (часто используемые):**

- `COMPRESSION [ ( ALGORITHM = { MS_XPRESS | ZSTD } [ , LEVEL = { LOW | MEDIUM | HIGH } ] ) ]` — сжатие (по умолчанию выключено серверной опцией `backup compression default`; алгоритм по умолчанию — MS_XPRESS; `ZSTD` — SQL 2025+; `LEVEL` по умолчанию `LOW`). Сжатие поддерживается в редакциях Enterprise, Standard, Developer; восстановить сжатый бэкап может любая редакция.
- `CHECKSUM` — контрольные суммы бэкапа (по умолчанию не создаются); рекомендуется для валидации.
- `ENCRYPTION (ALGORITHM = AES_256, SERVER CERTIFICATE = <cert>)` — шифрование (SQL 2014+; AES_128/192/256, TRIPLE_DES_3KEY; редакции Enterprise/BI/Standard, не Express/Web).
- `STATS = 10` — прогресс каждые 10%.
- `FORMAT` / `INIT` / `NOINIT` / `SKIP` — управление media set: инициализация новой ленты, перезапись, дозапись (по умолчанию), игнорирование срока хранения.
- `EXPIREDATE` / `RETAINDAYS` — срок хранения backup set.
- `COPY_ONLY`, `DIFFERENTIAL`, `NO_TRUNCATE` (для tail-log при повреждённой БД).

**Сжатие и TDE:** начиная с SQL Server 2019 CU5, при `WITH COMPRESSION` `MAXTRANSFERSIZE` автоматически увеличивается до 128 КБ, что включает оптимизированный алгоритм (расшифровка → сжатие → шифрование страницы).

## Практические сценарии

### 1. Стратегия и расписание

Типовая стратегия для `FULL`-модели (пример: RPO 15 минут):

- Full — ежедневно (например, 02:00).
- Differential — каждые 4–6 часов (ускоряет восстановление, сокращая цепочку логов).
- Log — каждые 15 минут.

Перед бэкапом — `DBCC CHECKDB` (см. [Валидацию бэкапов](../Concepts/backup_validation.md)); бэкап повреждённой БД бесполезен.

### 2. Создание бэкапов (T-SQL)

```sql
-- Полный бэкап со сжатием, контрольными суммами и шифрованием
BACKUP DATABASE [MyDb]
TO DISK = '/var/opt/mssql/backup/MyDb_full.bak'
WITH COMPRESSION, CHECKSUM, STATS = 10,
     ENCRYPTION (ALGORITHM = AES_256, SERVER CERTIFICATE = BackupCert);

-- Дифференциальный
BACKUP DATABASE [MyDb]
TO DISK = '/var/opt/mssql/backup/MyDb_diff.bak'
WITH DIFFERENTIAL, COMPRESSION, CHECKSUM;

-- Журнал транзакций
BACKUP LOG [MyDb]
TO DISK = '/var/opt/mssql/backup/MyDb_log.trn'
WITH CHECKSUM;

-- Copy-only (не разрывает цепочку)
BACKUP DATABASE [MyDb]
TO DISK = '/var/opt/mssql/backup/MyDb_copyonly.bak'
WITH COPY_ONLY, COMPRESSION;
```

**Шифрование — подготовка (однократно на экземпляре):**

```sql
USE master;
CREATE MASTER KEY ENCRYPTION BY PASSWORD = '<пароль>';
CREATE CERTIFICATE BackupCert WITH SUBJECT = 'Backup Encryption Certificate';
-- Сертификат и master key обязательно бэкапить отдельно от бэкапов:
BACKUP CERTIFICATE BackupCert TO FILE = '/var/opt/mssql/backup/BackupCert.cer'
    WITH PRIVATE KEY (FILE = '/var/opt/mssql/backup/BackupCert.pvk',
                      ENCRYPTION BY PASSWORD = '<пароль>');
```

> **Внимание:** без сертификата/асимметричного ключа зашифрованный бэкап невозможно восстановить. Сертификат нельзя обновлять (смена thumbprint делает бэкапы непригодными).

### 3. Восстановление на момент времени (PITR)

Последовательность для модели **Full** (база недоступна, поэтому сначала — tail-log):

```sql
-- 1. Tail-log: зафиксировать последние изменения (NORECOVERY)
BACKUP LOG [MyDb] TO DISK = '/var/opt/mssql/backup/MyDb_tail.trn' WITH NORECOVERY;
-- Если БД повреждена и недоступна: ... WITH NO_TRUNCATE;

-- 2. Полный бэкап (база остаётся в RESTORING)
RESTORE DATABASE [MyDb] FROM DISK = '/var/opt/mssql/backup/MyDb_full.bak'
WITH NORECOVERY, REPLACE;

-- 3. Дифференциальный (если есть — сокращает цепочку логов)
RESTORE DATABASE [MyDb] FROM DISK = '/var/opt/mssql/backup/MyDb_diff.bak'
WITH NORECOVERY;

-- 4. Журналы последовательно, последний — до нужной точки
RESTORE LOG [MyDb] FROM DISK = '/var/opt/mssql/backup/MyDb_log_1.trn' WITH NORECOVERY;
RESTORE LOG [MyDb] FROM DISK = '/var/opt/mssql/backup/MyDb_tail.trn'
WITH NORECOVERY, STOPAT = '2026-08-17 12:00:00';

-- 5. Завершение: перевод в ONLINE
RESTORE DATABASE [MyDb] WITH RECOVERY;
```

**Полезные варианты `RESTORE`:**

- `WITH MOVE 'MyDb' TO '...', MOVE 'MyDb_log' TO '...'` — перенос файлов на другие пути/диски (обязателен, если пути в бэкапе недоступны).
- `WITH STANDBY = '/path/undo.ldf'` — между накатами журналов база доступна только для чтения (удобно для поиска нужной точки во времени).
- `WITH STOPATMARK` / `STOPBEFOREMARK` — восстановление до помеченной транзакции.
- `WITH FILE = n` — выбор конкретного backup set в файле с несколькими бэкапами.
- `WITH RESTRICTED_USER` — доступ только для `db_owner` после восстановления.

### 4. Валидация бэкапов без восстановления

```sql
RESTORE HEADERONLY FROM DISK = '/var/opt/mssql/backup/MyDb_full.bak';   -- метаданные backup set
RESTORE FILELISTONLY FROM DISK = '/var/opt/mssql/backup/MyDb_full.bak';  -- логические/физические файлы
RESTORE LABELONLY  FROM DISK = '/var/opt/mssql/backup/MyDb_full.bak';    -- информация о media set
RESTORE VERIFYONLY FROM DISK = '/var/opt/mssql/backup/MyDb_full.bak';    -- проверка контрольных сумм
```

`VERIFYONLY` проверяет целостность заголовка и контрольных сумм, но не гарантирует полную восстанавливаемость — периодически делайте тестовое восстановление на стенде.

### 5. Бэкапы на Secondary-репликах (Always On AG)

Разгрузка Primary от I/O и CPU бэкапов:

- **SQL Server 2012–2022:** на Secondary допустимы **copy-only full** и **log**-бэкапы; дифференциальные бэкапы на Secondary **не поддерживаются**.
- **SQL Server 2025+:** на Secondary дополнительно доступны обычные **full** и **differential** бэкапы.

Ограничения (все версии):

- Реплика должна быть `SYNCHRONIZED` или `SYNCHRONIZING` и связана с Primary.
- Одновременные бэкапы (log на Primary + full на Secondary) не поддерживаются.
- `BACKUP LOG` на Secondary — только обычный (без `COPY_ONLY`); цепочка LSN остаётся непрерывной независимо от реплики.
- Copy-only full на Secondary блокирует очистку журнала на этой реплике на время бэкапа; при ошибке 9019 — делайте full на Primary.

Управление выбором реплики:

```sql
-- Предпочтение бэкапов на уровне AG (PRIMARY | SECONDARY_ONLY | SECONDARY | NONE)
ALTER AVAILABILITY GROUP [ag1]
    SET (AUTOMATED_BACKUP_PREFERENCE = SECONDARY);

-- Приоритет реплики 0–100 (по умолчанию 50; 0 — не участвует)
ALTER AVAILABILITY REPLICA 'node2'
    WITH (BACKUP_PRIORITY = 80);

-- Проверка в job-скрипте: бэкапить только на предпочитаемой реплике
IF sys.fn_hadr_backup_is_preferred_replica('MyDb') = 1
    BACKUP DATABASE [MyDb] TO DISK = '/var/opt/mssql/backup/MyDb_full.bak' WITH COMPRESSION;
```

Job с такой проверкой ставится на **все** реплики с одним расписанием — выполняется только на одной.

### 6. Бэкапы в S3-совместимое объектное хранилище (SQL Server 2022+)

Нативный S3-коннектор (`s3://` схема, только HTTPS): MinIO, Ceph, Pure FlashBlade, Dell ECS и др. Не поддерживается в Express.

```sql
-- 1. Credential: имя должно совпадать с началом URL; IDENTITY фиксирован
USE master;
CREATE CREDENTIAL [s3://<endpoint>:<port>/<bucket>]
WITH IDENTITY = 'S3 Access Key', SECRET = '<AccessKeyID>:<SecretKeyID>';

-- 2. Бэкап (FORMAT — перезапись; INIT не поддерживается)
BACKUP DATABASE [MyDb]
TO URL = 's3://<endpoint>:<port>/<bucket>/MyDb.bak'
WITH FORMAT, COMPRESSION, STATS = 10, MAXTRANSFERSIZE = 20971520;
```

Особенности: `MAXTRANSFERSIZE` 5–20 МБ (по умолчанию 10 МБ); striping до 64 URL; `MIRROR TO` — только S3→S3; `REGION` через `WITH BACKUP_OPTIONS = '{"s3": {"region":"us-west-1"}}'` (по умолчанию `us-east-1`); длина URL ≤ 259 символов; в `SECRET` не должно быть `:`. На Linux CA-сертификаты endpoint'а кладутся в `/var/opt/mssql/security/ca-certificates` (макс. 50) до старта `mssql-server`.

### 7. T-SQL snapshot backup (SQL Server 2022+)

Интеграция с аппаратными снимками хранилища (LVM, SAN) — работает на Linux и Windows, БД остаётся online:

```sql
-- 1. Заморозить I/O (блокировка записи; системные БД не поддерживаются)
ALTER DATABASE [MyDb] SET SUSPEND_FOR_SNAPSHOT_BACKUP = ON;
-- Или для группы: ALTER SERVER CONFIGURATION SET SUSPEND_FOR_SNAPSHOT_BACKUP = ON (GROUP = (db1, db2));

-- 2. Снимок хранилища средствами ОС/СХД, например LVM:
-- sudo lvcreate --size 10G --name mydb-ss1 --snapshot /dev/vg00/mydb

-- 3. Метаданные бэкапа (снимают блокировку); по умолчанию сбрасывается дифференциальная битовая карта
BACKUP DATABASE [MyDb] TO DISK = '/var/opt/mssql/backup/MyDb.bkm'
WITH METADATA_ONLY, MEDIANAME = 'LVM vg00/mydb-ss1';
-- Режим COPY_ONLY сохраняет дифференциальную битовую карту:
-- ALTER DATABASE [MyDb] SET SUSPEND_FOR_SNAPSHOT_BACKUP = ON (MODE = COPY_ONLY);
```

Восстановление: смонтировать снимок, затем `RESTORE DATABASE [MyDb] FROM DISK = '...' WITH METADATA_ONLY, MOVE ...` — аналог attach. Далее накатываются обычные log-бэкапы для PITR.

### 8. Автоматизация

- **SQL Server Agent** — встроенный планировщик. На Linux (2017 CU4+) входит в пакет `mssql-server`, выключен по умолчанию:
  ```bash
  sudo /opt/mssql/bin/mssql-conf set sqlagent.enabled true
  sudo systemctl restart mssql-server
  ```
  Ограничения Linux: нет подсистем CmdExec, PowerShell, Alerts, DB Mail, Log Shipping, CDC.
- **Ola Hallengren's Maintenance Solution** — общепринятый стандарт скриптов для DBA: бэкапы всех БД с ротацией, проверкой и индексным обслуживанием одной установкой.
- **dbatools (PowerShell)** — `Backup-DbaDatabase`, `Restore-DbaDatabase` (восстановление всей цепочки одной командой), миграции и проверки.
- **sqlcmd + cron** — минимальный вариант на Linux без Agent.

## Операции и команды

| Задача | Команда / запрос |
| :--- | :--- |
| Модель восстановления БД | `SELECT name, recovery_model_desc FROM sys.databases;` |
| Включить HADR/Agent на Linux | `sudo /opt/mssql/bin/mssql-conf set hadr.hadrenabled 1` / `sqlagent.enabled true` |
| Сжатие по умолчанию (сервер) | `EXEC sp_configure 'backup compression default', 1; RECONFIGURE;` |
| Алгоритм сжатия (2022+) | `EXEC sp_configure 'backup compression algorithm', 3; RECONFIGURE;` (1=MS_XPRESS, 2=Intel QAT, 3=ZSTD) |
| Прогресс бэкапа/восстановления | `SELECT percent_complete, estimated_completion_time FROM sys.dm_exec_requests;` |
| История бэкапов | `SELECT * FROM msdb.dbo.backupset;` (ratio: `backup_size/compressed_backup_size`) |
| Статус AG-реплик для бэкапа | `sys.fn_hadr_backup_is_preferred_replica('MyDb')` |
| Очистка журнала (аварийно) | `BACKUP LOG [MyDb] TO DISK = '...';` или (если история не важна) `ALTER DATABASE [MyDb] SET RECOVERY SIMPLE;` |
| Уменьшение .ldf (точечно!) | `DBCC SHRINKFILE (MyDb_log, <target_MB>);` |

## Мониторинг (SRE)

| Метрика | Источник | Описание |
| :--- | :--- | :--- |
| Успешность бэкапов | `msdb.dbo.backupset` + дата/время | Актуальность последнего full/diff/log по каждой БД |
| Прогресс | `sys.dm_exec_requests` (`percent_complete`, `estimated_completion_time`) | Долгие бэкапы/восстановления |
| Пропускная способность | PerfMon: `SQLServer:Backup Device` (Device Throughput Bytes/sec), `SQLServer:Databases` (Backup/Restore Throughput/sec) | Базелайн скорости |
| Размер цепочки | `msdb.dbo.backupset` (`backup_size`, `compressed_backup_size`) | Коэффициент сжатия, рост БД |
| Ошибки | SQL Server errorlog, `journalctl -u mssql-server` | Ошибки 3013/3201/9002/9019 |

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Ошибка 9002 «The transaction log for database is full» | Нет бэкапов лога в `FULL`/`BULK_LOGGED`, либо длинная активная транзакция, репликация/CDC | `BACKUP LOG`; при неважности истории — `SET RECOVERY SIMPLE`; найти активные транзакции (`sys.dm_tran_database_transactions`) |
| «LSN mismatch / chain broken» при восстановлении | Разрыв цепочки логов (пропущен лог, переключение модели, не-COPY_ONLY full на Secondary до 2025) | Новый полный бэкап и восстановление от него |
| Долгое восстановление (Slow Recovery) | Тысячи VLF из-за частого прироста маленькими порциями | `DBCC SHRINKFILE` журнала и фиксированный прирост большими порциями (например, 8 ГБ) |
| Ошибка 3201/3013 при `BACKUP TO URL = 's3://...'` | Credential не создан или имя не совпадает с URL; endpoint не HTTPS | `CREATE CREDENTIAL [s3://...]` с `IDENTITY = 'S3 Access Key'`; проверить TLS |
| Ошибка 9019 на Secondary | Copy-only full на Secondary: VLF журнала активен | Дождаться завершения бэкапа; full делать на Primary |
| «Cannot open backup device» | Нет прав Write у учётной записи службы SQL Server на папку | Выдать права `mssql` (Linux) / service account (Windows) |
| Восстановление на другой экземпляр зашифрованного бэкапа | Нет сертификата шифрования на целевом экземпляре | `BACKUP CERTIFICATE` → `CREATE MASTER KEY` + `CREATE CERTIFICATE FROM FILE` на целевом |

## Ограничения и риски

- **BULK_LOGGED:** PITR невозможен внутрь массовой операции — только до конца лог-бэкапа, её содержащего.
- **Сжатие:** сжатые и несжатые бэкапы не могут сосуществовать в одном media set; старые версии SQL Server не читают сжатые бэкапы; шифрованные/сжатые данные (TDE, Always Encrypted) сжимаются плохо.
- **Шифрование:** Express и Web не поддерживают создание зашифрованных бэкапов (восстановление — поддерживают); асимметричные ключи — только через EKM.
- **S3:** не поддерживается в Express; при сбое `BACKUP` временные multipart-файлы остаются в хранилище (убирает garbage collector провайдера).
- **Snapshot backup:** системные БД (`master`, `model`, `msdb`) не поддерживаются; по умолчанию сбрасывается дифференциальная битовая карта (используйте `MODE = COPY_ONLY`, если это критично).
- **DTC:** поддерживается на Linux с 2017 CU16, но **не для AG на Linux** — распределённые транзакции + AG требуют Windows.

## Best Practices

- **Правило 3-2-1:** 1 копия — быстрый локальный диск; 2 копия — сетевая папка (SMB/NFS); 3 копия — внешний сайт (S3-совместимое хранилище, например MinIO/Ceph, или другой физический сайт) с политикой Immutable (WORM).
- **`WITH CHECKSUM`** на всех бэкапах + `RESTORE VERIFYONLY` после каждого бэкапа.
- **Сертификаты шифрования** хранить отдельно от бэкапов (в т.ч. off-site); не обновлять сертификат, которым шифровались бэкапы.
- **Тестируйте восстановление** на стенде: бэкап без проверенного восстановления — не бэкап.
- **Бэкапы на Secondary** (Enterprise) — снять I/O с Primary; см. [High Availability](./high_availability.md).
- **Фиксированный прирост журнала** большими порциями — контроль числа VLF.
- **Пинить версии** CU и образов; перед включением ZSTD/QAT — тестовый стенд.

## Дополнительная информация

### См. также
- **[Обзор SQL Server](./overview.md)** — архитектура, редакции, лицензирование, порты.
- **[SQL Server: Always On HA](./high_availability.md)** — кластеризация на Linux, бэкапы на Secondary.
- **[Тюнинг производительности в Linux](./performance_tuning_linux.md)** — оптимизация контейнеров.
- **[Стратегии резервного копирования баз данных](../Concepts/backups.md)** — общая теория и метрики RPO/RTO.
- **[Валидация бэкапов](../Concepts/backup_validation.md)** — расширенные методы проверки и DBCC CHECKDB.
- **[Метрики надежности SRE](../../Concepts/sre_concepts_main.md)** — SLA и SLO в контексте доступности данных.
- **[Журнал предзаписи (WAL)](../Concepts/write_ahead_log.md)** — фундаментальный механизм работы транзакционных СУБД.
- **[Backup Compression (SQL Server)](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/backup-compression-sql-server?view=sql-server-ver17)** (Microsoft Learn)
- **[Create a Transact-SQL snapshot backup](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/create-a-transact-sql-snapshot-backup?view=sql-server-ver17)** (Microsoft Learn)
- **[SQL Server backup to URL for S3-compatible object storage](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/sql-server-backup-to-url-s3-compatible-object-storage?view=sql-server-ver17)** (Microsoft Learn)
- **[Backup encryption](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/backup-encryption?view=sql-server-ver17)** (Microsoft Learn)
- **[Offload backups to secondary replicas](https://learn.microsoft.com/en-us/sql/database-engine/availability-groups/windows/active-secondaries-backup-on-secondary-replicas-always-on-availability-groups?view=sql-server-ver17)** (Microsoft Learn)
