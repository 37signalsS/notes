# CQL: синтаксис и примеры

**CQL (Cassandra Query Language)** — SQL-подобный язык запросов для Cassandra и ScyllaDB. Подробности по моделированию данных и типам — **[Обзор и моделирование данных](./overview.md)**.

## Подключение
```bash
# Подключение к кластеру
cqlsh <node_ip> 9042

# С аутентификацией
cqlsh -u <username> -p <password> <node_ip> 9042

# В Docker
docker exec -it <cassandra_container> cqlsh
```

## DDL: управление схемой

```sql
-- Создание Keyspace с NetworkTopologyStrategy
CREATE KEYSPACE IF NOT EXISTS my_app WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'DC1': 3,
    'DC2': 3
};

-- Использование Keyspace
USE my_app;

-- Создание таблицы
CREATE TABLE user_events (
    user_id uuid,
    event_time timeuuid,
    event_type text,
    payload text,
    PRIMARY KEY (user_id, event_time)
) WITH CLUSTERING ORDER BY (event_time DESC)
  AND default_time_to_live = 7776000;  -- TTL 90 дней

-- Добавление колонки
ALTER TABLE user_events ADD metadata map<text, text>;

-- Удаление таблицы
DROP TABLE IF EXISTS user_events;
```

## DML: вставка и чтение данных

```sql
-- Вставка данных
INSERT INTO user_events (user_id, event_time, event_type, payload)
VALUES (550e8400-e29b-41d4-a716-446655440000, now(), 'login', '{"ip":"10.0.0.1"}')
USING TTL 86400;  -- автоудаление через 24 часа

-- Обновление данных (upsert)
UPDATE user_events
SET payload = '{"ip":"10.0.0.2"}'
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
  AND event_time = '2026-01-15 10:30:00+0000';

-- Удаление данных
DELETE FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
  AND event_time = '2026-01-15 10:30:00+0000';
```

## SELECT: чтение данных

```sql
-- Точечный запрос (самый быстрый)
SELECT * FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000;

-- Range-запрос по clustering column
SELECT event_type, payload FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
  AND event_time > '2026-01-01 00:00:00+0000'
  AND event_time < '2026-01-31 23:59:59+0000';

-- Лимит результатов
SELECT * FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
LIMIT 100;

-- COUNT
SELECT COUNT(*) FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000;

-- Агрегации
SELECT event_type, COUNT(*) as cnt
FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
GROUP BY event_type;
```

## BATCH: группировка операций

```sql
-- Атомарная запись в пределах одного partition (рекомендуется)
BEGIN BATCH
    INSERT INTO user_events (user_id, event_time, event_type)
    VALUES (550e8400-e29b-41d4-a716-446655440000, now(), 'purchase');
    INSERT INTO user_events (user_id, event_time, event_type)
    VALUES (550e8400-e29b-41d4-a716-446655440000, now(), 'notification');
APPLY BATCH;
```

**Внимание:** Кросс-партиционные `BATCH` (для разных Partition Key) — антипаттерн. Подробнее — **[Антипаттерны](./performance.md#антипаттерны-чего-нельзя-делать)**.

## Lightweight Transactions (LWT)

Cassandra/ScyllaDB поддерживают атомарные операции сравнения (IF) на основе Paxos:

```sql
-- Условная вставка (только если ключ еще не существует)
INSERT INTO users (user_id, name, email)
VALUES (550e8400-e29b-41d4-a716-446655440000, 'Ivan', 'ivan@example.com')
IF NOT EXISTS;

-- Условное обновление
UPDATE users SET name = 'Ivan Petrov'
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
IF name = 'Ivan';
```

**Особенности LWT:**
- Стоимость в 3-4 раза выше обычной операции (2 дополнительных round-trip для Paxos).
- Не масштабируются: при большом количестве LWT возникают конфликты и таймауты.
- Используйте только для атомарных проверок, не для высокочастотных записей.

## Настройка уровня согласованности

```sql
-- Установка для текущей сессии
CONSISTENCY LOCAL_QUORUM;

-- Установка для конкретного запроса
CONSISTENCY QUORUM;
SELECT * FROM users WHERE id = 1;

-- Просмотр текущего уровня
CONSISTENCY;

-- Уровень для операций чтения (отдельно от записи)
-- В Cassandra 5.x+ доступен
READ CONSISTENCY LOCAL_ONE;
```

Подробнее о уровнях согласованности — **[SRE-практики: Репликация и согласованность](./operations.md#уровни-согласованности-consistency-levels)**.

---

## См. также
- **[Обзор и моделирование данных](./overview.md)** — определения, Primary Key, типы данных.
- **[Обслуживание и эксплуатация](./operations.md)** — Compaction, Repair.
- **[Тюнинг производительности](./performance.md)** — антипаттерны, Tombstones.
