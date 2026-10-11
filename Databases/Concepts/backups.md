# Стратегии резервного копирования баз данных

## Определения

- **Резервное копирование (Backup)** — процесс создания копии данных для их восстановления в случае сбоя, повреждения, удаления или кибератаки.
- **RPO (Recovery Point Objective)** — целевая точка восстановления; максимально допустимый объем потери данных, выраженный во времени (например, "не более 15 минут данных").
- **RTO (Recovery Time Objective)** — целевое время восстановления; максимальное допустимое время простоя сервиса до его возврата в рабочее состояние.
- **PITR (Point-in-Time Recovery)** — технология восстановления базы данных на произвольный момент времени в прошлом, реализуемая через комбинацию полного бэкапа и журналов транзакций (WAL/Binlog).
- **Иммутабельный бэкап (Immutable Backup)** — копия данных, защищенная от любых изменений или удаления в течение заданного срока (защита от Ransomware).
- **Контрольная сумма (Checksum)** — уникальный хеш данных, используемый для проверки их целостности при хранении и передаче.
- **Политика удержания (Retention Policy)** — правила, определяющие срок хранения резервных копий и порядок их автоматического удаления или перемещения в архив.

## Основные концепции

### Правило "3-2-1-1-0"
Современный стандарт надежности, расширяющий классический подход:
- **3** копии данных (оригинал + 2 бэкапа).
- **2** разных типа носителей (например, диск и облако).
- **1** копия на удаленной площадке (offsite).
- **1** копия в **иммутабельном** хранилище (S3 Object Lock) или в офлайне (Air-gap).
- **0** ошибок при автоматической проверке восстановления.

### Репликация — это не бэкап
- **[Репликация](./replication.md)** обеспечивает **отказоустойчивость** (High Availability). Она защищает от отказа оборудования, но мгновенно тиражирует логические ошибки (например, `DROP TABLE` или `UPDATE` без `WHERE`) на все узлы.
- **Бэкап** обеспечивает **сохранность данных** во времени. Это единственный способ откатиться к состоянию "до ошибки пользователя или сбоя приложения".

### Уровни консистентности (Согласованности)
1. **Неконсистентный (Dirty):** Простое копирование файлов БД во время работы. Гарантированно приводит к повреждению данных при восстановлении.
2. **Согласованный на уровне диска (Crash-consistent):** Копия эквивалентна состоянию диска после внезапного выключения питания. СУБД восстановится через механизм **[Crash Recovery](./rollback_strategies.md)**, используя журналы транзакций. Достигается через снапшоты (LVM, EBS) без приостановки БД.
3. **Согласованный на уровне приложения (Application-consistent):** Перед созданием копии БД сбрасывает буферы (`fsync`) и приостанавливает запись (quiesce). Гарантирует полную целостность транзакций на момент снимка. Требует взаимодействия с СУБД (через `VSS` в Windows или `FREEZE/UNFREEZE` в Linux).

### Безопасность и целостность
Резервные копии должны быть защищены от несанкционированного доступа и порчи.
- **Шифрование:** Обязательно как при передаче (In Transit), так и при хранении (At Rest). См. подробнее **[Безопасность бэкапов](./backup_security.md)**.
- **Валидация:** Бэкап не считается существующим, пока его восстановление не протестировано. См. подробнее **[Проверка целостности бэкапов](./backup_validation.md)**.

## Типы резервных копий

| Тип | Что копируется | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Полный (Full)** | Все данные целиком | Самое быстрое и простое восстановление | Долго, большой объем, нагрузка на IO |
| **Инкрементальный** | Изменения с последнего бэкапа (любого типа) | Минимальный объем, высокая скорость создания | Долгое восстановление (нужна вся цепочка от последнего Full) |
| **Дифференциальный** | Изменения с последнего **полного** бэкапа | Быстрее восстановление, чем у инкремента (нужен Full + 1 Diff) | Объем растет с каждым днем до следующего Full |
| **Synthetic Full** | Сборка Full из Incr на стороне хранилища | Снимает нагрузку с БД, быстрое восстановление | Требует поддержки ПО (pgBackRest, Veeam) |

### Блочное vs Файловое копирование
- **Файловое:** Копирование данных на уровне файлов ОС. Просто, но неэффективно для больших баз (много мелких файлов).
- **Блочное (Block-level):** Копирование только измененных блоков диска. Эффективно для инкрементальных бэкапов огромных БД. Используется в снапшотах облаков (EBS) и специализированном ПО.

## Практические сценарии

### 1. Логический бэкап (SQL Dump)
Экспорт данных в виде текстовых SQL-команд.

#### PostgreSQL (`pg_dump`)

```bash
# Прямой дамп в файл (кастомный формат — поддерживает параллелизм и сжатие)
pg_dump -U postgres -d mydb -F c -j 4 -f /backup/mydb_$(date +%F).dump
# → ожидаемый вывод: pg_dump: завершено, 1420 объектов

# Проверка содержимого дампа без восстановления
pg_restore -l /backup/mydb_2026-09-30.dump | head -20
# → список объектов: TABLE public.users, TABLE public.orders, ...

# Восстановление из дампа
pg_restore -U postgres -d mydb_restored -j 4 /backup/mydb_2026-09-30.dump
# → ожидаемый вывод: processed 1420 objects
```

- **Инструменты:** `pg_dump`, `pg_dumpall`, `mysqldump`, `mydumper`.
- **Когда использовать:** Базы < 100 ГБ, миграции между версиями/ОС, выгрузка отдельных таблиц.
- **Особенности:** Долгое восстановление больших дампов. Используйте многопоточные форматы (`directory` в `pg_dump` с ключом `-j`, `mydumper` для MySQL).

#### MySQL (`mysqldump`)

```bash
# Полный дамп с позицией репликации (гарантирует консистентность для PITR)
mysqldump -u root -p --all-databases --single-transaction --flush-logs --source-data=2 > /backup/mysql_full_$(date +%F).sql
# → в начале файла будет строка: CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='mysql-bin.000123', SOURCE_LOG_POS=1540;
#   (в MySQL 5.7 — --master-data=2 и CHANGE MASTER TO MASTER_LOG_FILE=..., MASTER_LOG_POS=1540)

# Сжатие на лету
mysqldump -u root -p --single-transaction mydb | gzip > /backup/mydb_$(date +%F).sql.gz
```

### 2. Физический бэкап (Бинарный)
Прямое копирование файлов данных БД. Подходит для Production, где RTO критичен и база слишком велика для логического дампа.

#### PostgreSQL (`pg_basebackup` / `pgBackRest` / `wal-g`)

```bash
# pg_basebackup: базовый физический бэкап с streaming WAL
pg_basebackup -U postgres -D /backup/base -Ft -z -P --wal-method=stream
# → ожидаемый вывод:
#    transaction log start: LSN 0/2000028 (0x2000028)
#    transaction log end:   LSN 0/20000B0 (0x20000B0)
#    base backup completed
```

```bash
# pgBackRest: автоматическое резервное копирование с retention
pgbackrest --stanza=main --type=full backup
# → ожидаемый вывод:
#    00:00:06.119 INFO  backup full backup began
#    00:00:12.453 INFO  backup full backup complete, timestamp: 2026-09-30T18:00:00+03:00
```

```bash
# wal-g: непрерывная архивация WAL
# Проверка статуса архивации
wal-g backup-fetch LATEST --plain
# → ожидаемый вывод: загружен последний полный бэкап
```

#### MySQL / MariaDB (`Percona XtraBackup` / `mariadb-backup`)

```bash
# Percona XtraBackup 8.0+: горячий бэкап InnoDB без остановки сервиса
xtrabackup --backup --user=backup_user --password --target-dir=/backup/xtrabackup_$(date +%F)
# → ожидаемый вывод:
#    220929 18:00:12 xtrabackup: Transaction log being tracked up to LSN 123456
#    220929 18:00:15 xtrabackup: completed OK

# Подготовка бэкапа к восстановлению (применение Redo Log)
xtrabackup --prepare --target-dir=/backup/xtrabackup_2026-09-30
# → ожидаемый вывод: xtrabackup: completed OK!
```

- **PITR:** Комбинация физического бэкапа и архивирования **[WAL](./write_ahead_log.md)** позволяет откатиться на любую секунду.

### 3. Снапшоты и альтернативы на уровне тома
Снимки томов на уровне инфраструктуры или ОС.

#### Логические тома (LVM/ZFS) — без облаков

```bash
# LVM: создание снимка перед миграцией или апгрейдом
lvcreate -s -n db_pre_upgrade_snap -L 50G /dev/vg0/db_data

# ZFS: моментальный снапшот без остановки БД
zfs snapshot pool/db@pre_migration_$(date +%F_%H%M)
# → ожидаемый вывод: snapshot pool/db@pre_migration_2026-09-30_1800

# Список снапшотов
zfs list -t snapshot | grep db
# → NAME                        USED  AVAIL  REFER  MOUNTPOINT
# → pool/db@pre_migration_2026-09-30_1800   0   -  120G  -
```

- **Важно:** LVM/ZFS снапшот без остановки БД — **crash-consistent**. СУБД выполнит Crash Recovery при запуске через WAL/Redo Log. Для **application-consistent** снапшота выполните `FLUSH TABLES WITH READ LOCK` (MySQL) или `pg_start_backup()` (PostgreSQL) перед созданием снимка.

#### Облачные механизмы (существующие ссылки)
- **Механизмы:** AWS EBS Snapshots, GCP Snapshots, Azure Backup.
- **Kubernetes:** Использование **[Velero](../../Kubernetes/ToolsUtilities/velero-overview.md)** для бэкапа PV и манифестов кластера через CSI.
- **Преимущество:** Создание снимка занимает секунды (Copy-on-Write) и почти не влияет на производительность БД.

### 4. Универсальный алгоритм автоматизации
Любой скрипт автоматизации бэкапов должен следовать цепочке:
1.  **Pre-backup:** Проверка свободного места (`df -h`), очистка старых временных файлов, проверка доступности WAL-архивации.
2.  **Lock/Quiesce:** Приостановка записи (если требуется для консистентности): `FLUSH TABLES WITH READ LOCK` / `pg_start_backup()`.
3.  **Export:** Создание копии (Dump или Copy).
4.  **Unlock:** Возобновление записи: `UNLOCK TABLES` / `pg_stop_backup()`.
5.  **Transform:** Сжатие (`zstd -T0 -3`) и шифрование (именно в таком порядке!).
6.  **Transfer:** Выгрузка во внешнее хранилище (NFS, NAS, rsync).
7.  **Retention:** Удаление старых бэкапов согласно политике (`find /backup -name "*.dump" -mtime +30 -delete`).
8.  **Verification:** Проверка хеш-суммы выгруженного файла (`sha256sum`, `pg_verifybackup`).
9.  **Notify:** Отправка статуса в мониторинг (Prometheus Pushgateway, Zabbix).

```bash
# Пример pre-backup проверки для PostgreSQL
FREE_SPACE=$(df -h /backup | awk 'NR==2 {print $4}')
if [ "${FREE_SPACE%G}" -lt 10 ]; then
  echo "CRITICAL: less than 10GB free on /backup"
  exit 1
fi

# Проверка доступности репликации (если используется streaming replica для бэкапа)
pg_isready -h replica.internal -p 5432 || { echo "Replica not ready"; exit 1; }
```

## Крайние случаи и сценарии сбоев

### Сбой во время физического бэкапа (прерывание копирования)

**Сценарий:** `pg_basebackup` или `cp` файлов данных прерван по таймауту сети или нехватке места.

**Результат:** Получен неполный бэкап, который СУБД считает непригодным для восстановления (несовпадение контрольных сумм или отсутствие critical-файлов).

**Решение:**
1. Используйте инструменты с возобновляемой передачей: `pgBackRest`, `wal-g` или `rsync --partial`.
2. Проверяйте статус после создания: `pgBackRest info` показывает `status = OK` только при полной и валидной копии.
3. Никогда не восстанавливайтесь из частично скопированного каталога без проверки целостности.

### DDL-операция во время логического дампа

**Сценарий:** `mysqldump` или `pg_dump` выполняется, приложение одновременно выполняет `ALTER TABLE` или `DROP INDEX`.

**Результат:** Дамп может содержать неконсистентное состояние схемы или завершиться ошибкой `ERROR 1412 (HY000): Table definition has changed`.

**Решение:**
1. Используйте `--single-transaction` (MySQL) для иннодб-таблиц — это создает reproducible snapshot на уровне транзакции.
2. В PostgreSQL используйте `pg_dump` с дефолтной блокировкой схемы (`--no-lock` только для readonly-реплики).
3. Планируйте дампы вне часов пика или выполняйте их на реплике.

### Сетевой разрыв при передаче бэкапа по сети

**Сценарий:** `rsync` или `scp` прерван после передачи 80% файла.

**Результат:** Файл на стороне хранилища неполный, но без расширения `.part` или другой метки его можно принять за валидный.

**Решение:**
1. Используйте `rsync --partial --append-verify` или передачу через `mbuffer` с контрольными суммами.
2. После завершения передайте хеш: `sha256sum backup.dump` на источнике и приемнике, сравните.
3. Используйте `rclone copy` — он сам повторяет прерванные передачи и проверяет целостность на уровне чанков.

### Устаревание WAL при восстановлении

**Сценарий:** При восстановлении на точку времени СУБД запрашивает WAL-сегмент, который уже был удален retention-политикой или не был архивирован из-за сбоя `archive_command`.

**Результат:** Восстановление останавливается на последнем доступном сегменте с ошибкой `could not open file "pg_wal/..."`.

**Решение:**
1. Мониторьте `pg_stat_archiver` (PostgreSQL): `last_archived_wal`, `failed_count`.
2. Настройте `archive_command` с ретраями и алертом при ошибках.
3. Используйте `restore_command`, который возвращает ошибку явно, а не молча удаляет WAL.
4. Никогда не удаляйте старые WAL-сегменты вручную — используйте `archive_cleanup_command` или `pgBackRest expire`.

### Ротация бинарных логов MySQL во время `mysqldump`

**Сценарий:** Во время дампа `mysqldump` с `--source-data` происходит ротация `binlog`, и позиция `SOURCE_LOG_POS` указывает на уже удаленный или перезаписанный файл (в MySQL 5.7 — `--master-data` и `MASTER_LOG_POS`).

**Результат:** При восстановлении репликации из этого дампа MySQL вернет ошибку `ERROR 1236 (HY000): Could not find first log file name in binary log index file`.

**Решение:**
1. Используйте `--flush-logs --lock-all-tables` (полная блокировка) или `--single-transaction` (для InnoDB) вместе с `--source-data=2`.
2. Увеличьте `expire_logs_days` / `binlog_expire_logs_seconds` на мастере, чтобы запас был больше, чем время выполнения самого длительного дампа.
3. Для PITR используйте физические бэкапы (`XtraBackup`), которые включают позицию репликации и копируют весь бинарный лог целиком.

### Длинная транзакция, блокирующая создание бэкапа

**Сценарий:** В PostgreSQL открыта транзакция на несколько часов (`idle in transaction`), и `pg_start_backup()` ждет её завершения, так как она мешает созданию консистентного снапшота.

**Результат:** Бэкап не стартует, сервис мониторинга алертит, `pg_stat_activity` показывает активную транзакцию.

**Решение:**
1. Настройте `idle_in_transaction_session_timeout` (PostgreSQL) или `wait_timeout` (MySQL) для автоматического завершения зависших сессий.
2. Используйте мониторинг: `SELECT pid, state, xact_start FROM pg_stat_activity WHERE state = 'idle in transaction' AND xact_start < now() - interval '5 minutes';`.
3. При крайней необходимости завершите сессию: `SELECT pg_terminate_backend(pid);` — но только после подтверждения, что транзакция не выполняет критичные изменения.

## Поиск и устранение неисправностей (Troubleshooting)

### Блокировки (Locks)
**Симптомы:** `pg_dump` или `mysqldump` зависает или завершается ошибкой `ERROR 1412 (HY000): Table definition has changed`.
**Причины:** DDL (`ALTER TABLE`, `CREATE INDEX`) во время дампа.
**Решение:**
1. Запускайте дамп в часы минимальной нагрузки.
2. В PostgreSQL используйте `pg_dump` на readonly-реплике или с `--no-lock` (осторожно).
3. В MySQL используйте `--single-transaction` для InnoDB-таблиц.

### Нехватка места
**Симптомы:** Бэкап завершается ошибкой `No space left on device` или `could not write to file`.
**Причины:** Локальный диск `/backup` заполнен, не настроен piping в хранилище.
**Решение:**
1. Используйте потоковую передачу: `pg_dump db | gzip | ssh backup-server 'cat > /backup/db.sql.gz'`.
2. Для XtraBackup добавьте `--stream=xbstream` и передавайте напрямую в `ssh`.

### Разрыв соединения при передаче
**Симптомы:** `rsync` или `scp` обрывается с ошибкой `Broken pipe` или `Connection reset by peer`.
**Причины:** Таймаут сети, нестабильное соединение, слишком большой файл без сжатия.
**Решение:**
1. Используйте `rsync --partial --append-verify` или `mbuffer` для буферизации.
2. Передавайте через `screen`/`tmux` или системныйd-сервис с `Restart=on-failure`.
3. Используйте `rclone copy` — он сам повторяет прерванные передачи.

### Битый физический бэкап
**Симптомы:** `pg_basebackup` завершается с `FATAL: could not receive data from WAL stream: unexpected EOF`.
**Причины:** Прерывание сети, нехватка места на целевом диске, ошибка I/O.
**Решение:**
1. Используйте `pgBackRest` или `wal-g` — они поддерживают возобновляемые бэкапы и встроенную проверку.
2. После создания проверьте статус: `pgBackRest info` должен показывать `status = OK`.

### WAL-архивация не работает
**Симптомы:** PITR невозможен, `pg_stat_archiver` показывает `failed_count > 0`.
**Причины:** `archive_command` возвращает ошибку, диск для архива полон, права доступа.
**Решение:**
1. Проверьте `archive_command` вручную: `sudo -u postgres /usr/bin/pg_archivecleanup /var/lib/pgsql/wal_archive %r`.
2. Мониторьте `pg_stat_archiver.last_archived_wal` — если не меняется более часа, есть проблема.
3. Никогда не удаляйте WAL-файлы вручную — используйте `archive_cleanup_command`.

## Лучшие практики

1.  **Автоматизируйте всё:** Никаких ручных запусков. Используйте Cron, Kubernetes CronJobs или Airflow.
2.  **Бэкапируйте конфиги:** База без настроек СУБД и TLS-сертификатов может не запуститься. Включите `postgresql.conf`, `pg_hba.conf`, `my.cnf`, сертификаты, скрипты инициализации.
3.  **Принцип наименьших привилегий:** Пользователь бэкапа не должен иметь прав суперпользователя (только `SELECT`, `LOCK TABLES`, `REPLICATION CLIENT` и т.д.).
4.  **Именование и структура:** Используйте предсказуемое имя файла: `{db}_{type}_{date}_{time}.{ext}`. Пример: `mydb_full_2026-09-30_1800.dump`. Это упрощает поиск и сортировку.
5.  **Мониторинг успеха:** Настраивайте алерты не на "ошибку бэкапа", а на "отсутствие свежего успешного бэкапа". Используйте Dead Man's Switch: `time() - backup_last_success_timestamp_seconds > 86400` → алерт.
6.  **Проверка восстановления:** Минимум раз в квартал проводите учения по полному восстановлению из бэкапа в изолированной среде. Замеряйте реальное RTO.
7.  **Управление retention:** Храните полные бэкапы 30 дней, дифференциальные — 7 дней, инкрементальные — 1 день. Используйте `pgBackRest expire` или `find /backup -name "*.dump" -mtime +N -delete`.
8.  **WAL-архивация:** Для PostgreSQL включите `archive_mode = on` и мониторьте `pg_stat_archiver`. Для MySQL включите `log_bin` и `binlog_expire_logs_seconds`.
9.  **Шифрование:** Бэкапы должны шифроваться на стороне источника до передачи. Используйте `gpg --symmetric`, `age`, или нативные инструменты (`pgBackRest --compress=zstd --cipher=aes256`).
10. **Air-gap:** Храните одну копию на отключаемом носителе (LTO-лента, внешний HDD) или в иммутабельном хранилище (S3 Object Lock, ZFS snapshot readonly). Это защищает от Ransomware и удаленного уничтожения.

## Валидация бэкапов (SRE-чеклист)

Бэкап не считается существующим, пока его восстановление не протестировано. Валидация должна покрывать три уровня: целостность файла, логическую целостность СУБД и функциональное восстановление приложения.

### Логические бэкапы

```bash
# PostgreSQL: проверка дампа без восстановления
pg_restore -l /backup/mydb_2026-09-30.dump > /dev/null
# → exit code 0 = OK, non-zero = поврежден

# Проверка на уровне строк: количество записей в бэкапе vs production
pg_dump -F t -t users mydb | tar -xO | wc -l
# → должно совпадать с SELECT count(*) FROM users;

# MySQL: проверка дампа
mysqlcheck -u root -p --databases mydb --check-only-updated
# → OK для всех таблиц
```

### Физические бэкапы

```bash
# PostgreSQL: pg_verifybackup для каталоговного бэкапа
pg_verifybackup /backup/pg_basebackup_2026-09-30
# → ожидаемый вывод:
#    backup integrity: OK
#    files checked: 1420

# pgBackRest: встроенная проверка
pgbackrest --stanza=main check
# → INFO: backup check completed, no errors found

# Percona XtraBackup: этап prepare = фактическая проверка
xtrabackup --prepare --target-dir=/backup/xtrabackup_2026-09-30
# → xtrabackup: completed OK!
```

### Проверка PITR-готовности

```bash
# PostgreSQL: убедитесь, что WAL-сегменты архивируются
psql -c "SELECT * FROM pg_stat_archiver;"
# → last_archived_wal должен обновляться
# → failed_count = 0

# Тестовое восстановление на временный каталог
mkdir /tmp/test_restore && chown postgres:postgres /tmp/test_restore
su - postgres -c "pgbackrest --stanza=main --delta restore"
# → INFO: restore complete, timestamp: 2026-09-30T18:00:00+03:00

# Запуск временного кластера
initdb -D /tmp/test_restore/data
echo "restore_command = 'pgbackrest --stanza=main archive-get %f %p'" >> /tmp/test_restore/data/postgresql.conf
pg_ctl -D /tmp/test_restore/data -l /tmp/test_restore/logfile start
# → server started, database system is ready to accept connections

# Проверка данных
psql -d postgres -c "SELECT count(*) FROM users;"
# → должно совпадать с ожидаемым значением
```

### Проверка шифрования и целостности файла

```bash
# Проверка AES/GPG шифрования: попытка расшифровки и проверка заголовка
gpg --decrypt /backup/mydb_2026-09-30.sql.gz.gpg | gzip -t
# → gzip: /dev/stdin: decompression OK

# Проверка контрольной суммы после передачи
sha256sum /backup/mydb_2026-09-30.dump
# → abc123...  /backup/mydb_2026-09-30.dump
# Сравните с хешем, вычисленным на источнике.
```

### Функциональный smoke-test

```bash
# После восстановления в sandbox выполните бизнес-проверки
psql -h localhost -U app_user -d mydb_restored -c "
  SELECT count(*) FROM orders WHERE created_at > now() - interval '24 hours';
"
# → должно быть > 0, иначе бэкапу не хватает свежих данных

# Проверка ссылочной целостности
psql -c "SELECT count(*) FROM orders o JOIN users u ON o.user_id = u.id WHERE u.id IS NULL;"
# → должно быть 0, иначе есть битые ссылки
```

## Дополнительная информация

### Смотрите также
- **[Журнал предзаписи (WAL)](./write_ahead_log.md)** — физическая основа PITR.
- **[Безопасность бэкапов](./backup_security.md)** — шифрование, KMS и защита от Ransomware.
- **[Проверка целостности](./backup_validation.md)** — методы валидации и "Бэкап Шрёдингера".
- **[Обзор Velero](../../Kubernetes/ToolsUtilities/velero-overview.md)** — резервное копирование в K8s.
- **[Резервное копирование в Linux](../../Linux/SystemAdministration/backup_and_recovery.md)** — инструменты ОС (rsync, Borg).
- **[Стратегии отката (Rollback Strategies)](./rollback_strategies.md)** — логическое восстановление и Undo.
- **[Мета-мониторинг: Dead Man's Switch для бэкапов](../../Concepts/Observability_and_Monitoring/meta-monitoring.md)** — heartbeat-мониторинг выполнения резервного копирования.
- **[Метрики надежности SRE](../../Concepts/sre_concepts_main.md)** — подробнее об RPO, RTO и SLA.

