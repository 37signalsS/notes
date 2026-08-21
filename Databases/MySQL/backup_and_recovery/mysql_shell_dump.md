# MySQL Shell Dump & Load — многопоточные логические дампы

`mysqlsh` (MySQL Shell) Dump & Load — современная замена `mysqldump` и `mysqlpump`. Поддерживает многопоточность, сжатие Zstandard и прямую выгрузку в облачные хранилища (S3/OCI). Является предпочтительным методом логического бэкапа для MySQL 8.0+.

> **Версии:** MySQL Shell 9.7.x (актуальная). Совместим с MySQL 5.7+ (для выгрузки), MySQL 5.7+ (для загрузки). С MySQL 8.4+ является единственным рекомендуемым логическим инструментом (mysqldump/mysqlpump удалены/deprecated).

## Ключевые преимущества перед mysqldump

| Возможность | mysqldump | MySQL Shell Dump |
| :--- | :--- | :--- |
| Многопоточность | Нет (однопоточный) | Да (настраиваемое кол-во потоков) |
| Сжатие | Через pipe (gzip/zstd) | Нативное (Zstd, LZ4) |
| Облачные хранилища | Нет | Да (OCI, S3) |
| Инкрементальный импорт | Нет | Да (пропуск существующих данных) |
| Чанкинг данных | Нет | Да (управление размером чанков) |
| Прогресс | Нет | Да (showProgress) |

## Установка

```bash
# Через MySQL APT/YUM repository
sudo apt-get install mysql-shell

# Или статический бинарник
# См. https://dev.mysql.com/doc/mysql-shell/8.4/en/mysql-shell-install.html

# Проверка версии
mysqlsh --version
# → MySQL Shell 9.7.x
```

## Дамп всего инстанса (util.dumpInstance)

```bash
mysqlsh --uri backup_user@localhost \
  -e "util.dumpInstance('/backups/shell_dump', {
    threads: 8,
    compression: 'zstd',
    showProgress: true
  })"
# → dumps: 8 tables (123456 rows)... done
# → Total dump size: 42.3 GB
```

**Ключевые параметры:**
- `threads` — количество параллельных потоков. Оптимальное значение: `(количество CPU ядер / 2)`, но не более 16–32 для избежания конкуренции за I/O.
- `compression` — `zstd` (рекомендуется, баланс скорость/размер) или `lz4` (максимальная скорость).
- `defaultChunkSize` — размер чанка по умолчанию `128MB`. Уменьшение ускоряет загрузку малых таблиц, увеличение — снижает overhead для больших.
- `consistent: true` — application-consistent snapshot через `LOCK TABLES FOR BACKUP`.

## Дамп отдельной схемы (util.dumpSchemas)

```bash
mysqlsh --uri backup_user@localhost \
  -e "util.dumpSchemas(['mydb'], '/backups/mydb_dump', {
    threads: 8,
    compression: 'zstd',
    consistent: true
  })"
```

## Дамп отдельных таблиц (util.dumpTables)

```bash
mysqlsh --uri backup_user@localhost \
  -e "util.dumpTables('mydb', ['users', 'orders', 'products'], '/backups/mydb_tables', {
    threads: 4,
    compression: 'zstd'
  })"
```

## Выгрузка напрямую в S3

```bash
mysqlsh --uri backup_user@localhost \
  -e "util.dumpInstance('my-backup-bucket:mysql-backups/daily', {
    threads: 16,
    compression: 'zstd',
    s3BucketName: 'my-backup-bucket',
    s3ConfigFile: '~/.aws/config',
    s3CredentialsFile: '~/.aws/credentials'
  })"
```

**Примечания по S3:**
- `s3BucketName:prefix` — формат: имя_бакета:префикс_путя.
- Ключи AWS хранятся в `~/.aws/credentials` (стандартный формат AWS CLI).
- Для OCI Object Storage используйте параметры `osBucketName`, `osConfigFile`.

## Загрузка дампа (util.loadDump)

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

## Фильтрация при выгрузке

```bash
# Исключение определённых схем
mysqlsh --uri backup_user@localhost \
  -e "util.dumpInstance('/backups/dump', {
    threads: 8,
    excludeSchemas: ['sys', 'performance_schema', 'information_schema']
  })"

# Исключение определённых таблиц
mysqlsh --uri backup_user@localhost \
  -e "util.dumpSchemas(['mydb'], '/backups/dump', {
    threads: 8,
    excludeTables: ['mydb.logs', 'mydb.session_data']
  })"
```

## mysqldump — классический инструмент

Для небольших БД (< 100 ГБ) или когда MySQL Shell недоступен:

```bash
# Полный дамп с консистентностью InnoDB
mysqldump --user=backup_user --password='StrongPassword!2024' \
  --single-transaction --routines --triggers --events \
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
- `--master-data=2` — включить позицию бинарного лога в дамп (для replication setup или PITR).

## Восстановление одной таблицы из логического дампа

Если есть только огромный `full_backup.sql`, созданный через `mysqldump`:

### Способ 1: sed (быстрый)

```bash
sed -n -e '/CREATE TABLE.*`users`/,/UNLOCK TABLES/p' full_backup.sql > users_table.sql
mysql -u root -p mydb < users_table.sql
```

### Способ 2: grep + sed (точный)

```bash
# Найти номер строки начала таблицы
grep -n "CREATE TABLE.*users" full_backup.sql
# → 124850:CREATE TABLE `users` ...

# Извлечь (подберите end-line по размеру таблицы)
sed -n '124850,128050p' full_backup.sql > users_table.sql
```

## mysqlpump (deprecated)

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

## Дополнительная информация

- **[Обзор инструментов бэкапа](./overview.md)** — сравнение методов, определения, бест-практики.
- **[Percona XtraBackup](./xtrabackup.md)** — физические бэкапы для Production.
- **[Point-in-Time Recovery](./pitr.md)** — комбинация дампа + бинарные логи.
- **[MySQL Shell Dump & Load Guide](https://dev.mysql.com/doc/mysql-shell/8.4/en/mysql-shell-utilities-dump-instance-schema.html)**
