# Обслуживание MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**mariadb-check** — основная утилита командной строки для проверки, восстановления, анализа и оптимизации таблиц. Является заменой устаревшей утилиты `mysqlcheck`. Работает как обёртка над SQL-командами `CHECK TABLE`, `REPAIR TABLE`, `ANALYZE TABLE` и `OPTIMIZE TABLE`.

**System-Versioned Partitioning** — механизм MariaDB для автоматического разделения данных на "текущие" и "исторические" на уровне партиций. Позволяет реализовать временные ряды без триггеров и прикладной логики.

**Data Dictionary** — внутренние системные таблицы (`mysql.*`, `information_schema.*`), которые MariaDB обновляет при мажорных изменениях версии через `mariadb-upgrade`.

## Основные концепции

### Модель обслуживания MariaDB

MariaDB разделяет обслуживание на два уровня:

1. **Уровень таблиц (Table-level):** Фрагментация, анализ статистики и проверка целостности выполняются через `mariadb-check`. Для движка InnoDB `OPTIMIZE TABLE` пересоздаёт таблицу (аналог `ALTER TABLE ... FORCE`), что освобождает неиспользуемое пространство, но создаёт нагрузку на I/O и временную копию данных на диске.

2. **Уровень системы (System-level):** Мажорные изменения версии требуют обновления системных словарей и таблиц привилегий через `mariadb-upgrade`. Начиная с MariaDB 10.5, `mysql_upgrade` является символической ссылкой на `mariadb-upgrade`.

### Влияние на репликацию

Команды обслуживания, изменяющие данные (`ANALYZE`, `OPTIMIZE`, `REPAIR`), по умолчанию записываются в бинарный лог и реплицируются на реплики. Для выполнения обслуживания только на мастере используйте флаг `--skip-write-binlog` в `mariadb-check` или добавьте `NO_WRITE_TO_BINLOG` в SQL-команду.

## Практические сценарии

### 1. Планирование окна обслуживания

Обслуживание InnoDB-таблиц требует свободного пространства на диске (до 1.5x от размера таблицы) и создаёт нагрузку на CPU/I/O. В production-среде выполняйте его в периоды минимальной нагрузки.

**Шаг 1.** Определите фрагментированные таблицы через `information_schema`:

```sql
SELECT table_schema, table_name, data_free, data_length
FROM information_schema.tables
WHERE engine = 'InnoDB'
  AND data_free > 0
  AND table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
ORDER BY data_free DESC;
```

**Шаг 2.** Создайте бэкап перед обслуживанием критичных таблиц:

```bash
mariadb-backup --backup \
  --target-dir=/data/backups/pre_optimize_$(date +%Y%m%d) \
  --user=backup --password
```

### 2. Дефрагментация и анализ таблиц

#### Анализ статистики

```bash
# Анализ всех баз (обновляет индексы кардинальности для оптимизатора)
mariadb-check --all-databases --analyze

# Анализ конкретной таблицы
mariadb-check app_db users --analyze
```

**Валидация:**

```sql
-- Проверка, что Analyze отработал (статус должен быть NULL или пуст)
SELECT table_name, engine, stats_auto_update_statistics
FROM information_schema.tables
WHERE table_schema = 'app_db' AND table_name = 'users';
```

#### Оптимизация (дефрагментация)

```bash
# Оптимизация всех таблиц
mariadb-check --all-databases --optimize

# Оптимизация без записи в бинарный лог (только на мастере)
mariadb-check --all-databases --optimize --skip-write-binlog

# Оптимизация конкретной таблицы
mariadb-check app_db large_table --optimize
```

**Валидация:**

```sql
-- Проверка свободного пространства после оптимизации
SELECT table_schema, table_name, data_free, data_length
FROM information_schema.tables
WHERE table_schema = 'app_db' AND table_name = 'large_table';
```

### 3. Проверка и восстановление таблиц

Для таблиц MyISAM/Aria `mariadb-check` может выполнять восстановление. InnoDB не поддерживает `REPAIR TABLE` — при повреждении используйте бэкап или `innodb_force_recovery`.

```bash
# Проверка всех баз
mariadb-check --all-databases --check

# Проверка только изменённых таблиц (быстрее)
mariadb-check --all-databases --check-only-changed

# Средняя проверка (быстрее extended, находит 99.99% ошибок)
mariadb-check --all-databases --medium-check
```

### 4. Обслуживание бинарных логов

Бинарные логи растут постоянно. Без ротации они заполнят диск.

```sql
-- Просмотр текущих логов
SHOW BINARY LOGS;

-- Просмотр позиции репликации (чтобы не удалить нужные логи)
SHOW REPLICA STATUS\G

-- Удаление логов старше заданной даты (не ранее позиции самой отсталой реплики)
PURGE BINARY LOGS BEFORE DATE_SUB(NOW(), INTERVAL 7 DAY);

-- Удаление логов старше определённого файла
PURGE BINARY LOGS TO 'mariadb-bin.000150';
```

**Автоматическая ротация:**

```sql
-- Включение автоматического удаления (по умолчанию 0 = отключено)
SET GLOBAL expire_logs_days = 7;
```

**Валидация:**

```bash
# Проверка размера директории с логами
du -sh /var/lib/mysql/mariadb-bin.*

# Проверка позиции реплики
mariadb -e "SHOW REPLICA STATUS\G" | grep -E "Source_Log_File|Read_Source_Log_Pos|Exec_Source_Log_Pos"
```

### 5. Управление партициями

Теория секционирования описана в **[Секционирование данных (Теория)](../Concepts/partitioning.md)**. В MariaDB добавлена уникальная возможность `SYSTEM VERSIONING`.

#### Добавление и удаление партиций

```sql
-- Добавление партиции для следующего месяца
ALTER TABLE events
  ADD PARTITION (
    PARTITION p202610 VALUES LESS THAN (20261101)
  );

-- Удаление старой партиции (мгновенное освобождение места)
ALTER TABLE events
  DROP PARTITION p202401;
```

**Валидация:**

```sql
-- Проверка структуры партиций
SELECT partition_name, partition_method, partition_expression
FROM information_schema.partitions
WHERE table_schema = 'app_db' AND table_name = 'events';
```

#### System-Versioned Partitioning

```sql
-- Создание таблицы с разделением на историю и текущие данные
CREATE TABLE employees (
    id INT NOT NULL,
    name VARCHAR(100),
    salary DECIMAL(10,2),
    sys_start TIMESTAMP(6) GENERATED ALWAYS AS ROW START,
    sys_end TIMESTAMP(6) GENERATED ALWAYS AS ROW END,
    PERIOD FOR SYSTEM_TIME(sys_start, sys_end)
) WITH SYSTEM VERSIONING
PARTITION BY SYSTEM_TIME (
    PARTITION p_hist HISTORY,
    PARTITION p_curr CURRENT
);

-- Просмотр исторических данных
SELECT * FROM employees FOR SYSTEM_TIME ALL WHERE id = 1;
```

### 6. Мажорное обновление (mariadb-upgrade)

Подробная процедура обновления кластеров описана в **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)**. Краткая последовательность для одного узла:

```bash
# 1. Остановка сервиса
systemctl stop mariadb

# 2. Обновление пакетов
apt update && apt install mariadb-server mariadb-client

# 3. Запуск и проверка
systemctl start mariadb
mariadb-admin -u root ping

# 4. Обновление системных таблиц (обязательно для мажорных версий)
mariadb-upgrade --user=root --password

# 5. Валидация
mariadb -e "SELECT VERSION();"
```

## Устранение неполадок

### Ошибка: `Table ... is corrupted`

**Причина:** Некорректное завершение работы сервера или аппаратный сбой.

**Решение:** Для Aria/MyISAM выполните `mariadb-check --repair`. Для InnoDB проверьте логи на наличие ошибок и восстановитесь из бэкапа. Если сервер не стартует, временно включите `innodb_force_recovery=1..6` в `my.cnf` для экспорта данных.

### Ошибка: `Table is full` при OPTIMIZE

**Причина:** Недостаточно свободного места на диске (требуется до 1.5x от размера таблицы для временной копии).

**Решение:** Освободите место или оптимизируйте таблицы по одной с использованием `pt-online-schema-change` (если доступен) или выполните в окно с очисткой диска.

### Ошибка: `mariadb-upgrade: Access denied`

**Причина:** Учётная запись не имеет прав `SELECT` на системные таблицы `mysql.*`.

**Решение:** Запустите от root или пользователя с привилегиями `SUPER`/`ALTER USER` в `mysql.user`.

### Ошибка: `Unknown table engine 'S3'`

**Причина:** Плагин S3 не установлен или не загружен.

**Решение:** Установите пакет `mariadb-plugin-s3` или загрузите плагин через `INSTALL SONAME 'ha_s3'`. Подробности см. в **[Движки хранения MariaDB](storage_engines.md)**.

## Best Practices

1. **Очередь обслуживания:** Для таблиц >100 ГБ используйте пакетное обслуживание по нескольким таблицам, чтобы контролировать нагрузку.
2. **Мониторинг после OPTIMIZE:** Проверяйте `Innodb_data_written` и `Innodb_data_read` в `SHOW GLOBAL STATUS` — резкий рост может указывать на фрагментацию индексов.
3. **Бинарные логи:** Настройте `expire_logs_days` не менее, чем максимальная задержка реплики + 1 день. Без этого PITR-восстановление будет невозможным.
4. **Партиции:** Удаляйте старые партиции вместо `DELETE` — это мгновенная операция, не создающая undo-лог и не фрагментирующая InnoDB.
5. **mariadb-upgrade:** Запускайте только при мажорном апгрейде. Для минорных обновлений (12.3.1 → 12.3.2) утилита не требуется, если Changelog не содержит изменений в системных таблицах.
6. **Валидация:** После любого обслуживания проверяйте `SHOW GLOBAL STATUS LIKE 'Handler%'` и `performance_schema` на предмет аномалий.

## Дополнительная информация

### Смежные темы
- **[Обзор MariaDB](overview.md)** — архитектура и стратегия развития.
- **[Конфигурация MariaDB](configuration.md)** — параметры, влияющие на обслуживание (`innodb_buffer_pool_size`, `max_binlog_size`).
- **[Клиентские утилиты](client_utilities.md)** — полный справочник `mariadb-check`, `mariadb-admin` и других инструментов.
- **[Резервное копирование MariaDB](backup_and_recovery.md)** — `mariadb-backup` и `mariadb-dump`.
- **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)** — стратегия обновления кластеров без остановки.
- **[Движки хранения MariaDB](storage_engines.md)** — особенности MyRocks, Aria и S3 Engine.
- **[Стандартная репликация MariaDB](./replication/overview.md)** — настройка Source-Replica и GTID.
- **[Секционирование данных (Теория)](../Concepts/partitioning.md)** — общие принципы и типы секций.
- **[Миграция с MySQL](./Operations/migration_mysql_to_mariadb.md)** — процедура смены вендора.
