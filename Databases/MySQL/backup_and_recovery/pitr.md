# Point-in-Time Recovery (PITR) — восстановление на конкретный момент

**Point-in-Time Recovery (PITR)** — восстановление состояния БД на конкретный момент времени с помощью полного физического или логического бэкапа и последующего применения бинарных логов через `mysqlbinlog`.

> **Требование:** Бинарный лог должен быть включён до момента создания бэкапа. Конфигурация — в **[Обзоре](./overview.md#включённый-бинарный-лог-обязательно-для-pitr)**.

## Алгоритм PITR

1. Восстановить БД из полного бэкапа (физического или логического).
2. Определить целевой момент восстановления (datetime или позиция в логе).
3. Применить бинарные логи от момента бэкапа до целевого через `mysqlbinlog`.

## Шаг 1: Восстановление из полного бэкапа

### Из физического бэкапа (XtraBackup)

```bash
xtrabackup --prepare --target-dir=/backups/full_latest
systemctl stop mysql
rm -rf /var/lib/mysql/*
xtrabackup --copy-back --target-dir=/backups/full_latest
chown -R mysql:mysql /var/lib/mysql
systemctl start mysql
```

### Из логического дампа (MySQL Shell)

```bash
mysqlsh --uri backup_user@localhost \
  -e "util.loadDump('/backups/shell_dump', {threads: 16})"
```

### Определение позиции бинарного лога в бэкапе

После восстановления из XtraBackup проверьте файл `xtrabackup_binlog_info`:

```bash
cat /var/lib/mysql/xtrabackup_binlog_info
# → mysql-bin.000005    89234    3E11FA47-71CA-11E1-9E33-C80AA9429562:1-100
```

Это начальная точка для применения бинарных логов (все логи до этого момента уже содержатся в бэкапе).

## Шаг 2: Определение целевой точки восстановления

```sql
-- Просмотр списка бинарных логов
SHOW BINARY LOGS;
-- →mysql-bin.000001   154
-- →mysql-bin.000002   15267
-- →mysql-bin.000003   89234

-- Просмотр событий в конкретном логе
SHOW BINLOG EVENTS IN 'mysql-bin.000005' LIMIT 20;
```

```bash
# Просмотр через mysqlbinlog (удобнее для больших логов)
mysqlbinlog --no-defaults /var/lib/mysql/mysql-bin.000005 | head -100

# Поиск конкретной операции (например, DROP TABLE)
mysqlbinlog --no-defaults -v --base64-output=DECODE-ROWS \
  /var/lib/mysql/mysql-bin.000005 | grep -B 5 "DROP TABLE"
```

## Шаг 3: Применение бинарных логов

### Вариант 1: До конкретного момента времени (datetime)

```bash
mysqlbinlog --no-defaults \
  --stop-datetime="2024-08-20 14:30:00" \
  /var/lib/mysql/mysql-bin.000001 \
  /var/lib/mysql/mysql-bin.000002 \
  /var/lib/mysql/mysql-bin.000003 \
  /var/lib/mysql/mysql-bin.000004 \
  /var/lib/mysql/mysql-bin.000005 \
  | mysql -u root -p
# → Все транзакции до 14:30:00 применены
```

### Вариант 2: До конкретной позиции в логе (pos)

```bash
mysqlbinlog --no-defaults \
  --stop-position=12345 \
  /var/lib/mysql/mysql-bin.000005 \
  | mysql -u root -p
# → Транзакции до позиции 12345 в mysql-bin.000005 применены
```

### Вариант 3: С исключением GTID (отмена конкретной транзакции)

```bash
# Исключить транзакцию с GTID=542 (например, DROP TABLE)
mysqlbinlog --no-defaults \
  --exclude-gtids="server-uuid:542" \
  /var/lib/mysql/mysql-bin.000005 \
  | mysql -u root -p
# → Все транзакции, КРОМЕ с GTID=542, применены
```

### Вариант 4: Фильтрация по базе данных

```bash
# Применить только транзакции конкретной базы
mysqlbinlog --no-defaults \
  --database=mydb \
  --stop-datetime="2024-08-20 14:30:00" \
  /var/lib/mysql/mysql-bin.000005 \
  | mysql -u root -p
```

### Вариант 5: Чтение бинарного лога с удалённого сервера

```bash
# Прямое чтение с реплики (не требует скачивания логов)
mysqlbinlog --no-defaults \
  --read-from-remote-server \
  --host=replica_host --port=3306 \
  --user=backup_user --password='ClonePassword!2024' \
  --stop-datetime="2024-08-20 14:30:00" \
  mysql-bin.000005 \
  | mysql -u root -p
```

## Полный сценарий PITR: откат после DROP TABLE

### Ситуация

В 15:05 выполнен `DROP TABLE critical_data`. Нужно восстановить БД на состояние 15:04.

```bash
# 1. Остановить сервер (предотвратить дальнейшие записи)
systemctl stop mysql

# 2. Сохранить текущие бинарные логи (на случай, если сервер ещё писал)
cp /var/lib/mysql/mysql-bin.000005 /tmp/mysql-bin.000005.bak

# 3. Определить позицию бэкапа
cat /var/lib/mysql/xtrabackup_binlog_info
# → mysql-bin.000005    89234

# 4. Восстановить из полного бэкапа (сделанного вчера в 03:00)
rm -rf /var/lib/mysql/*
xtrabackup --copy-back --target-dir=/backups/full_2024-08-19
chown -R mysql:mysql /var/lib/mysql

# 5. Запустить сервер в readonly (временно)
mysql -u root -p -e "SET GLOBAL read_only = ON;"

# 6. Применить бинарные логи до момента 15:04:59 (за минуту до DROP)
mysqlbinlog --no-defaults \
  --stop-datetime="2024-08-20 15:04:59" \
  /var/lib/mysql/mysql-bin.000005 \
  | mysql -u root -p
# → Транзакции с 03:00 (момент бэкапа) до 15:04:59 применены

# 7. Убрать readonly и проверить данные
mysql -u root -p -e "SET GLOBAL read_only = OFF;"
mysql -u root -p -e "SELECT COUNT(*) FROM critical_data;"
# → Таблица восстановлена и содержит данные до 15:04
```

### Альтернатива: исключение DROP TABLE через GTID

Если GTID включён и известен идентификатор транзакции DROP TABLE:

```bash
# 1. Найти GTID транзакции DROP
mysqlbinlog --no-defaults -v --base64-output=DECODE-ROWS \
  /var/lib/mysql/mysql-bin.000005 | grep -A 3 "DROP TABLE"
# → GTID: 3E11FA47-...:542

# 2. Применить все логи, исключая эту транзакцию
mysqlbinlog --no-defaults \
  --exclude-gtids="3E11FA47-71CA-11E1-9E33-C80AA9429562:542" \
  /var/lib/mysql/mysql-bin.000005 \
  | mysql -u root -p
# → Все транзакции применены, КРОМЕ DROP TABLE
```

> **Преимущество GTID-метода:** Не нужно восстанавливать из полного бэкапа — можно просто исключить вредоносную транзакцию при повторном применении логов. Однако это работает только для логических операций (DROP, UPDATE без WHERE и т.д.), не для физических повреждений данных.

## Ограничения и особенности

1. **Бинарный лог обязателен:** Если `log_bin=OFF`, PITR невозможен. Бэкап будет восстанавливаться только на момент его создания.
2. **Ротация логов:** Если `binlog_expire_logs_seconds` мал, старые логи могут быть удалены до завершения PITR. Убедитесь, что все логи от момента бэкапа до целевого момента доступны.
3. **Non-transactional DDL:** Операции `CREATE TABLE`, `ALTER TABLE`, `DROP TABLE` фиксируются в бинарном логе немедленно (не в рамках транзакции). Их невозможно откатить через `ROLLBACK`, но можно исключить через GTID.
4. **Длинные транзакции:** Если транзакция началась до целевого момента, но была зафиксирована после, `--stop-datetime` может не отработать корректно. Используйте `--stop-position` для точного контроля.
5. **Промежуточные состояния:** PITR восстанавливает БД на **консистентное** состояние. Если вы откатываетесь на момент до завершения длинной транзакции, InnoDB откатит её при старте сервера.

## Дополнительная информация

- **[Обзор инструментов бэкапа](./overview.md)** — конфигурация binlog, определения инструментов.
- **[Percona XtraBackup](./xtrabackup.md)** — физические бэкапы как основа для PITR.
- **[MySQL Shell Dump & Load](./mysql_shell_dump.md)** — логические дампы как основа для PITR.
- **[Настройка репликации MySQL](../replication/setup_guide.md)** — PITR и replication тесно связаны.
- **[GTID в MySQL](../replication/gtid.md)** — подробнее о GTID-фильтрации в mysqlbinlog.
- **[Бинарные логи: формат и управление](../replication/binlog_management.md)** — архивация и ротация.
