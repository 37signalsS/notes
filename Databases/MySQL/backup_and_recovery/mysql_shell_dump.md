# MySQL Shell Dump & Load — многопоточные логические дампы

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS, MySQL Shell 9.7.x

> **Статус:** `mysqlpump` удалён в MySQL 8.4. Для MySQL 8.0.34+ и 8.4+ используйте `mysqlsh util.dumpInstance()` как единственный рекомендуемый логический инструмент.

## Определения

**Логический бэкап** — дамп данных в виде SQL-инструкций или специализированного формата (в случае MySQL Shell — чанкованный `.json` + `.sql` пачками). В отличие от физического бэкапа, не зависит от версии MySQL и позволяет менять ОС или архитектуру CPU при восстановлении.

**MySQL Shell (`mysqlsh`)** — интерактивный клиент и утилита автоматизации от Oracle, поддерживающая SQL, JavaScript и Python. Содержит утилиты `util.dumpInstance()`, `util.dumpSchemas()`, `util.dumpTables()` и `util.loadDump()` для многопоточного логического бэкапа.

**Chunk (чанк)** — логический блок данных (диапазон строк таблицы), который экспортируется одним потоком. MySQL Shell автоматически разбивает таблицы на чанки по `defaultChunkSize` (по умолчанию 128 МБ) для параллелизации.

**xbstream** — формат потока Percona, используемый MySQL Shell для упаковки дампа. Поддерживает pipes, но не является тем же форматом, что и XtraBackup.

**Application-consistent snapshot** — состояние базы, при котором все закоммиченные транзакции на момент начала дампа полностью репрезентативны. Достигается через `LOCK INSTANCE FOR BACKUP` (MySQL Shell) или `FLUSH TABLES WITH READ LOCK` (mysqldump).

**RTO/RPO** — целевое время восстановления и целевая точка восстановления. Логические дампы MySQL Shell обеспечивают высокую RPO (до секунды в комбинации с PITR) при среднем RTO (зависит от размера и parallelism).

## Основные концепции

### Архитектура Dump & Load

MySQL Shell Dump использует **многоуровневую архитектуру**:

1. **Метаданные:** JSON-файл `dump_metadata.json` содержит список таблиц, чанков, версию MySQL Shell и GTID-позицию.
2. **Данные:** Каждая таблица экспортируется в `.sql` файл (DDL + INSERT пакетами) или `.json` (для Document Store).
3. **Индексы:** Восстанавливаются автоматически через `LOAD DATA`/`INSERT` + последующий `ALTER TABLE ... ADD INDEX` при загрузке.

### Механизм параллелизации

MySQL Shell назначает **один поток на таблицу** (или на чанк большой таблицы). Параллелизм ограничен:
- I/O capacity диска
- CPU для компрессии
- Лок-конкуренция на источнике

### Консистентность

MySQL Shell обеспечивает консистентность на уровне инстанса через `LOCK INSTANCE FOR BACKUP` (не блокирует DML, но кратковременно останавливает DDL, а также операции, изменяющие файлы вне redo log). Это **application-consistent** снимок, но не **crash-consistent**.

### Версионная совместимость

- MySQL Shell 9.7.x работает с MySQL 5.7+ для дампа и загрузки.
- Дампы, созданные MySQL Shell 8.0, можно загружать через MySQL Shell 8.4 (обратная совместимость).
- `ignoreVersion: true` позволяет игнорировать несовпадения версий, но может привести к ошибкам DDL.

### Ограничения

- **InnoDB:** Основной движок. MyISAM и MEMORY экспортируются, но не имеют механизма консистентности без `FLUSH TABLES WITH READ LOCK`.
- **INSTANT ADD/DROP COLUMN:** В MySQL 8.0.12–8.0.28 может привести к ошибкам экспорта. Обновите MySQL до 8.0.29+.
- **Табличные пространства:** Импорт требует одинакового keyring-бэкенда на источнике и цели.
- **Большие транзакции:** `max_binlog_size` не ограничивает размер отдельной транзакции. Очень большие INSERT могут вызвать OOM на источнике.
- **GTID:** При использовании `ignoreVersion: true` GTID-позиция может быть несовместима между версиями.

## Практические сценарии

### Сценарий 1: Установка и верификация

#### Debian/Ubuntu

```bash
# Через официальный APT-репозиторий MySQL
sudo apt-get update
sudo apt-get install mysql-shell

# Проверка версии
mysqlsh --version
# → MySQL Shell 9.7.x for Linux on x86_64
```

#### RHEL/CentOS/Rocky

```bash
# Через официальный YUM/DNF-репозиторий MySQL
sudo dnf install mysql-shell

# Проверка версии
mysqlsh --version
# → MySQL Shell 9.7.x for Linux on x86_64
```

### Сценарий 2: Базовый полный бэкап инстанса (util.dumpInstance)

```bash
mysqlsh --uri backup_user@localhost \
  -e "util.dumpInstance('/backups/shell_dump', {
    threads: 8,
    compression: 'zstd',
    showProgress: true,
    consistent: true
  })"
# → dumps: 8 tables (123456 rows)... done
# → Total dump size: 42.3 GB
```

**Ключевые параметры:**
- `threads` — количество параллельных потоков. Оптимальное значение: `(CPU cores / 2)`, но не более 16–32 для избежания конкуренции за I/O.
- `compression` — `zstd` (рекомендуется, баланс скорость/размер) или `lz4` (максимальная скорость).
- `defaultChunkSize` — размер чанка по умолчанию `128MB`. Уменьшение ускоряет загрузку малых таблиц, увеличение — снижает overhead для больших.
- `consistent: true` — application-consistent snapshot через `LOCK INSTANCE FOR BACKUP`.
- `showProgress: true` — вывод прогресса в stderr (удобно для cron-логов).

**Валидация:**
```bash
# Проверка структуры дампа
ls -la /backups/shell_dump/
# → @.json  @.sql  metadata.json  users.00000.sql  ...

# Проверка целостности через util.loadDump в изолированную среду
# См. automation.md — Сценарий 5: Расширенная верификация логического дампа
```

### Сценарий 3: Бэкап отдельной схемы (util.dumpSchemas)

```bash
mysqlsh --uri backup_user@localhost \
  -e "util.dumpSchemas(['mydb'], '/backups/mydb_dump', {
    threads: 8,
    compression: 'zstd',
    consistent: true
  })"
```

### Сценарий 4: Бэкап отдельных таблиц (util.dumpTables)

```bash
mysqlsh --uri backup_user@localhost \
  -e "util.dumpTables('mydb', ['users', 'orders', 'products'], '/backups/mydb_tables', {
    threads: 4,
    compression: 'zstd'
  })"
```

### Сценарий 5: Восстановление дампа (util.loadDump)

```bash
mysqlsh --uri backup_user@remote_host \
  -e "util.loadDump('/backups/shell_dump', {
    threads: 16,
    showProgress: true,
    ignoreExistingObjects: true,
    ignoreVersion: true
  })"
```

**Параметры загрузки:**
- `threads` — количество потоков для импорта. Обычно ставят в 2 раза больше, чем при выгрузке, так как INSERT параллелится эффективнее.
- `ignoreExistingObjects: true` — пропуск таблиц, которые уже существуют в целевой БД (для инкрементальной загрузки).
- `ignoreVersion: true` — игнорирование несовпадения версий MySQL (осторожно: может привести к ошибкам DDL).
- `loadUsers: true` — загрузка пользователей MySQL (только для полного дампа инстанса).

**Валидация после загрузки:**
```bash
# Проверка количества таблиц
mysql -u root -p -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('mysql','information_schema','performance_schema','sys');"

# Проверка строк в ключевой таблице
mysql -u root -p mydb -e "SELECT COUNT(*) FROM users;"
```

### Сценарий 6: Фильтрация при выгрузке

```bash
# Исключение системных схем
mysqlsh --uri backup_user@localhost \
  -e "util.dumpInstance('/backups/dump', {
    threads: 8,
    excludeSchemas: ['sys', 'performance_schema', 'information_schema']
  })"

# Исключение больлых таблиц (логи, кэши)
mysqlsh --uri backup_user@localhost \
  -e "util.dumpSchemas(['mydb'], '/backups/dump', {
    threads: 8,
    excludeTables: ['mydb.logs', 'mydb.session_data']
  })"
```

### Сценарий 7: Восстановление одной таблицы из логического дампа

Если есть только огромный `full_backup.sql`, созданный через `mysqldump`:

#### Способ 1: sed (быстрый)

```bash
sed -n -e '/CREATE TABLE.*`users`/,/UNLOCK TABLES/p' full_backup.sql > users_table.sql
mysql -u root -p mydb < users_table.sql
```

#### Способ 2: grep + sed (точный)

```bash
# Найти номер строки начала таблицы
grep -n "CREATE TABLE.*users" full_backup.sql
# → 124850:CREATE TABLE `users` ...

# Извлечь (подберите end-line по размеру таблицы)
sed -n '124850,128050p' full_backup.sql > users_table.sql
```

**Внимание:** Этот метод не консистентен с данными, созданными после начала дампа. Используйте PITR для строгой консистентности.

### Сценарий 8: mysqldump — классический инструмент

Для небольших БД (< 100 ГБ) или когда MySQL Shell недоступен:

```bash
# Полный дамп с консистентностью InnoDB
mysqldump --user=backup_user --password='StrongPassword!2024' \
  --single-transaction --routines --triggers --events \
  --source-data=2 \
  --all-databases | gzip > /backups/full_$(date +%F).sql.gz

# Дамп одной базы
mysqldump --user=backup_user --password='StrongPassword!2024' \
  --single-transaction mydb > /backups/mydb_$(date +%F).sql

# Восстановление
mysql -u root -p mydb < /backups/mydb_$(date +%F).sql
gunzip < /backups/full_$(date +%F).sql.gz | mysql -u root -p
```

**Ключевые флаги mysqldump:**
- `--single-transaction` — консистентный снимок InnoDB без блокировок (только для InnoDB).
- `--routines --triggers --events` — включить хранимые процедуры, триггеры, события (обязательно для полного дампа).
- `--source-data=2` — включить позицию бинарного лога в дамп (для replication setup или PITR). Флаг `--master-data` — устаревшее имя, депрекейтнут с MySQL 8.0.26; в MySQL 5.7 существует только `--master-data`. Полный разбор — в **[mysqldump](./mysqldump.md)**.
- `--set-gtid-purged=ON` — включить GTID-позицию (обязательно для репликации).

### Сценарий 9: mysqlpump (deprecated)

Утилита для параллельного логического бэкапа, представленная в MySQL 5.7. **Депрекейтнута в MySQL 8.0.34 и удалена в MySQL 8.4.** Основное ограничение: `--single-transaction` с параллельными потоками не гарантирует консистентность на уровне инстанса.

```bash
# Только для MySQL 5.7 / 8.0 до 8.0.33
mysqlpump --user=backup_user --password='StrongPassword!2024' \
  --all-databases \
  --default-parallelism=4 \
  --compress-output=LZ4 \
  > /backups/full_$(date +%F).lz4

# Распаковка (утилита входит в дистрибутив MySQL)
lz4_decompress /backups/full_$(date +%F).lz4 /backups/full_$(date +%F).sql
```

> **Замена:** Используйте `mysqlsh util.dumpInstance()` для MySQL 8.0.34+ и MySQL 8.4+.

### Сценарий 10: Интеграция с планировщиком и мониторингом

Скрипты ежедневного бэкапа и расширенной валидации описаны в **[Автоматизация и верификация](./automation.md#сценарий-2-ежедневный-логический-бэкап-mysql-shell)**.

**Мониторинг (локальный Prometheus Pushgateway):**

```bash
PUSHGATEWAY_URL="http://pushgateway:9091"

# Метрика: время последнего успешного бэкапа
echo "backup_last_success_timestamp $(date +%s)" | \
  curl --data-binary @- ${PUSHGATEWAY_URL}/metrics/job/mysql_backup/instance/$(hostname)

# Метрика: размер бэкапа в байтах
BACKUP_SIZE=$(du -sb "${DUMP_DIR}" | awk '{print $1}')
echo "backup_size_bytes ${BACKUP_SIZE}" | \
  curl --data-binary @- ${PUSHGATEWAY_URL}/metrics/job=mysql_backup/instance/$(hostname)
```

**Алерт:**

```yaml
- alert: MySQLBackupMissing
  expr: time() - backup_last_success_timestamp > 86400 * 2
  for: 0m
  labels:
    severity: critical
  annotations:
    summary: "MySQL Shell backup missing on {{ $labels.instance }}"
```

## Управление ресурсами и надёжность

### Приоритеты процесса

Понижайте приоритет бэкапа, чтобы не конкурировать с приложением:

```bash
# Понижение приоритета CPU и I/O
ionice -c2 -n6 nice -n10 mysqlsh --uri backup_user@localhost \
  -e "util.dumpInstance('/backups/dump', { threads: 8 })"

# Ограничение дискового I/O через cgroups (если поддерживается)
systemd-run --scope -p IOWeight=10 mysqlsh ...
```

### Использование памяти при prepare/load

MySQL Shell потребляет память пропорционально количеству потоков и размеру чанков. Для больших дампов (>500 ГБ) увеличивайте `--use-memory` или ограничивайте parallelism:

```bash
# Ограничение parallelism для серверов с малым RAM
mysqlsh --uri backup_user@localhost \
  -e "util.dumpInstance('/backups/dump', { threads: 4 })"
```

### Хранение метаданных

Файл `dump_metadata.json` содержит GTID-позицию и список таблиц. Храните его вместе с дампом для PITR и аудита.

## Диагностика и устранение неисправностей

| Ошибка / симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR: Unable to connect to MySQL Server` | Неверный URI или пользователь не существует | Проверьте `mysqlsh --uri backup_user@localhost --password` |
| `ERROR: Lock wait timeout exceeded` | Долгая транзакция блокирует `LOCK INSTANCE FOR BACKUP` | Увеличьте `lock_wait_timeout` или выполните бэкап в окно низкой нагрузки |
| `ERROR: Out of memory` | Слишком много потоков или большие чанки | Уменьшите `threads` или `defaultChunkSize` |
| `ERROR: Unsupported feature in dump metadata` | Версия MySQL Shell целевого сервера ниже источника | Обновите MySQL Shell на целевой стороне |
| `util.loadDump() зависает` | Недостаточно потоков или память | Уменьшите `threads`; проверьте `ulimit -n` |
| `Дамп больше исходных данных` | Не используется сжатие | Добавьте `compression: 'zstd'` |
| `Восстановление занимает часы` | Логический однопоточный дамп | Используйте `util.loadDump()` с многопоточным импортом |
| `Ошибка DDL при загрузке` | `ignoreVersion: true` скрывает несовместимость DDL | Уберите флаг, исправьте DDL, пересоздайте дамп |

## Бест-практисы

1. **Используйте MySQL Shell Dump как предпочтительный логический метод для MySQL 8.0+.** `mysqldump` оставьте для совместимости и одиночных таблиц.
2. **Запускайте бэкапы с replication-реплик**, а не с источника. См. **[Обзор методов резервного копирования](./overview.md)**.
3. **Ротация:** Храните логические дампы 14–30 дней. См. **[Автоматизация и верификация](./automation.md)**.
4. **Шифрование:** Используйте `compression: 'zstd'` + файловое шифрование (LUKS, GPG). См. **[Безопасность и сжатие резервных копий](../../Concepts/backup_security.md)**.
5. **Валидация:** Еженедельно выполняйте smoke-тест через `util.loadDump()` в изолированную среду. См. **[Проверка целостности и тестовое восстановление](../../Concepts/backup_validation.md)**.
6. **PITR:** Комбинируйте логический дамп с бинарными логами. См. **[Point-in-Time Recovery (PITR)](./pitr.md)**.
7. **Идемпотентность:** Скрипты бэкапа должны быть идемпотентными (повторный запуск не ломает состояние). См. **[Идемпотентность](../../../Concepts/idempotency.md)**.
8. **Мониторинг:** Отслеживайте время последнего успешного бэкапа и размер дампа.
9. **Документируйте GTID-позицию:** Фиксируйте позицию из `dump_metadata.json` для каждого дампа.
10. **Тестируйте восстановление:** Раз в квартал восстанавливайте логический дамп на тестовом стенде.

## Дополнительная информация

### См. также

- **[Обзор инструментов бэкапа](./overview.md)** — сравнение методов, определения, бест-практики.
- **[Percona XtraBackup](./xtrabackup.md)** — физические бэкапы для Production.
- **[Point-in-Time Recovery (PITR)](./pitr.md)** — комбинация дампа + бинарные логи.
- **[Автоматизация и верификация](./automation.md)** — скрипты, ротация, smoke-тестирование бэкапов.
- **[Проверка целостности и тестовое восстановление](../../Concepts/backup_validation.md)** — уровни валидации, smoke-тесты.
- **[Безопасность и сжатие резервных копий](../../Concepts/backup_security.md)** — шифрование, сжатие.
- **[Идемпотентность](../../../Concepts/idempotency.md)** — идемпотентные скрипты бэкапа.

### Внешние ресурсы

- **[MySQL Shell Dump & Load Guide](https://dev.mysql.com/doc/mysql-shell/8.4/en/mysql-shell-utilities-dump-instance-schema.html)** — официальная документация.
- **[MySQL Shell 9.7 Release Notes](https://dev.mysql.com/doc/relnotes/mysql-shell/9.7/en/)** — изменения в версии 9.7.
