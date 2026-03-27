# Миграция PostgreSQL без простоя (Zero-Downtime)

## Определения

**Миграция без простоя (Zero-Downtime Migration)** — перенос production-базы данных на новый сервер без остановки обслуживания или с минимальным окном простоя, незаметным для пользователей.

**Логическая репликация** — технология репликации изменений на уровне строк по принципу "поставщик-подписчик" (Publisher-Subscriber). Подробнее — **[Репликация в PostgreSQL](../Concepts/replication.md)**.

## Основные концепции

Процесс основан на развёртывании новой БД, полной копии данных со старой, и "догонке" изменений через потоковую передачу WAL. Переключение происходит в конце и занимает минимальное время.

**Ключевая технология:** [Логическая репликация](../Concepts/replication.md).

## Практические сценарии

### Шаг 1: Подготовка

**1. Развернуть новый сервер (Target):**

Установите PostgreSQL, убедитесь в совместимости версий, оптимизируйте `postgresql.conf`.

**2. Настроить старый сервер (Source):**

Включите логическую репликацию:

```ini
# postgresql.conf
wal_level = logical
```

**Требуется перезагрузка** — проведите заранее в окно обслуживания.

**3. Создать пользователя для репликации:**

```sql
CREATE ROLE repl_user WITH REPLICATION LOGIN PASSWORD 'secure_password';
```

### Шаг 2: Начальная загрузка данных

**1. Создание дампа:**

```bash
# Дамп схемы
pg_dump -h <source_host> -U <user> -d <db_name> --schema-only > schema.sql

# Дамп данных
pg_dump -h <source_host> -U <user> -d <db_name> --data-only > data.sql
```

**2. Фиксация позиции WAL:**

`pg_dump` с `--snapshot` фиксирует LSN в рамках транзакции:

```bash
pg_dump --snapshot=<snapshot_name> ...
```

**3. Восстановление на Target:**

```bash
psql -h <target_host> -U <user> -d <db_name> -f schema.sql
psql -h <target_host> -U <user> -d <db_name> -f data.sql
```

### Шаг 3: Настройка логической репликации

**1. Публикация на Source:**

```sql
CREATE PUBLICATION migration_pub FOR ALL TABLES;
```

**2. Подписка на Target:**

```sql
CREATE SUBSCRIPTION migration_sub
CONNECTION 'host=<source_host> user=repl_user password=<pass> dbname=<db_name>'
PUBLICATION migration_pub
WITH (copy_data = false);
```

**Важно:** `copy_data = false` — не копировать данные повторно (уже скопированы вручную).

### Шаг 4: Синхронизация и мониторинг

**Мониторинг задержки:**

```sql
-- На Source
SELECT sent_lsn FROM pg_stat_replication WHERE application_name = 'migration_sub';

-- На Target
SELECT received_lsn, latest_end_lsn FROM pg_stat_subscription;
```

**Цель:** Дождаться минимальной задержки (близкой к нулю).

### Шаг 5: Переключение (Switchover)

**1. Остановка записей:**

Переведите приложение в режим "только чтение" или остановите трафик записи.

**2. Финальная синхронизация:**

Дождитесь нулевой задержки репликации.

**3. Перенаправление трафика:**

Измените конфигурацию приложения на новый сервер БД.

**4. Возобновление работы:**

Включите полный трафик.

**5. Проверка:**

Убедитесь в корректной работе приложения.

### Шаг 6: Завершение и очистка

```sql
-- На Target: удалить подписку
DROP SUBSCRIPTION migration_sub;

-- На Source: удалить публикацию
DROP PUBLICATION migration_pub;
```

Через некоторое время выведите старый сервер из эксплуатации.

## Дополнительная информация

### Ограничения логической репликации

| Ограничение | Решение |
| :--- | :--- |
| **DDL не реплицируется** | Применять `ALTER TABLE`, `CREATE INDEX` вручную на обоих серверах |
| **SEQUENCE не реплицируются** | После переключения обновить `setval()` на Target |
| **Большие объекты (LO)** | Не реплицируются — использовать альтернативные инструменты |

### Обновление SEQUENCE

```sql
-- На Source: получить последнее значение
SELECT last_value FROM my_sequence;

-- На Target: установить значение
SELECT setval('my_sequence', <last_value>);
```

### Альтернативные инструменты

- **`pglogical`** — расширение от 2ndQuadrant с расширенными возможностями
- **AWS DMS** — Database Migration Service
- **Google Cloud DMS** — Database Migration Service
- **Yandex Data Transfer** — сервис миграции

### Связанные документы

- **Репликация:** **[Replication](../Concepts/replication.md)**
- **Бэкапы:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
- **Логический бэкап:** **[Logical Backup Migration](./logical_backup_migration.md)**
