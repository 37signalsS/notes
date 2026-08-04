# Конкурентность и блокировки в PostgreSQL

## Определения

- **MVCC (Multi-Version Concurrency Control)** — механизм управления доступом, при котором чтение не блокирует запись, а запись не блокирует чтение. Каждое изменение создает новую версию строки.
- **Уровень изоляции (Isolation Level)** — настройка, определяющая видимость изменений других транзакций (Read Committed, Repeatable Read, Serializable).
- **Snapshot (Снимок)** — логическое состояние данных в конкретный момент времени, с которым работает транзакция.
- **Deadlock (Взаимоблокировка)** — ситуация, когда две или более транзакции циклически ждут освобождения ресурсов друг друга.
- **Advisor Locks (Рекомендательные блокировки)** — пользовательские блокировки по числовым идентификаторам, не привязанные к строкам таблиц.
- **Lock Queue (Очередь блокировок)** — механизм FIFO, определяющий порядок получения доступа к ресурсу. Эксклюзивная блокировка в начале очереди блокирует все последующие запросы, включая «легкие» `SELECT`.

> **Важно:** PostgreSQL фундаментально построен на блокировках. Мониторинг **локов** (особенно высокоуровневых, перекрывающих доступ к таблицам) — это первоочередная задача при диагностике производительности.

## Базовые концепции

### Механизм MVCC (Низкий уровень)
PostgreSQL хранит версии строк непосредственно в страницах данных таблицы. Каждая строка (tuple) содержит скрытые служебные поля:
- **XMIN**: ID транзакции, которая создала (вставила) версию строки.
- **XMAX**: ID транзакции, которая удалила или обновила строку. Если поле пустое (0), строка считается «живой».
- **Bloat (Раздувание)**: Накопление «мертвых» строк (где `XMAX` заполнен и транзакция завершена), замедляющее работу. Очисткой занимается **Autovacuum**.

### Уровни изоляции транзакций

| Уровень | Особенности в PostgreSQL | Защита от аномалий |
| :--- | :--- | :--- |
| **Read Committed** | Снимок создается для **каждого запроса**. Дефолтный уровень. | Грязное чтение (Dirty Read) |
| **Repeatable Read** | Снимок один на **всю транзакцию**. Гарантирует целостность внутри транзакции. | Неповторяющееся чтение, Фантомы |
| **Serializable** | Полная изоляция через предикатные блокировки (SSI). | Все аномалии параллелизма |

## Иерархия блокировок

### Блокировки таблиц (Table-Level Locks)
Существует 8 режимов блокировок. Чем выше номер, тем выше уровень изоляции.

1.  **ACCESS SHARE**: `SELECT`. Совместим со всем, кроме `ACCESS EXCLUSIVE`.
2.  **ROW SHARE**: `SELECT ... FOR SHARE`.
3.  **ROW EXCLUSIVE**: `INSERT`, `UPDATE`, `DELETE`.
4.  **SHARE UPDATE EXCLUSIVE**: `VACUUM` (без Full), `CREATE INDEX CONCURRENTLY`, `ANALYZE`.
5.  **SHARE**: `CREATE INDEX` (обычный). Блокирует запись, разрешает чтение.
6.  **SHARE ROW EXCLUSIVE**: Защита от конкурентного изменения структуры.
7.  **EXCLUSIVE**: Блокирует всё, кроме `ACCESS SHARE`.
8.  **ACCESS EXCLUSIVE**: `ALTER TABLE`, `DROP TABLE`, `TRUNCATE`. Блокирует даже `SELECT`.

### Блокировки строк (Row-Level Locks)
- **FOR UPDATE**: Полная блокировка на изменение. Блокирует другие `UPDATE/DELETE/SELECT FOR UPDATE`.
- **FOR NO KEY UPDATE**: Как `FOR UPDATE`, но позволяет параллельно создавать внешние ключи, ссылающиеся на эту строку. Захватывается обычным `UPDATE`.
- **FOR SHARE**: Позволяет другим читать, но запрещает изменять.
- **FOR KEY SHARE**: Самая слабая блокировка. Позволяет другим `SELECT FOR SHARE`, но запрещает `DELETE`.

### Взаимоблокировки (Deadlocks)
PostgreSQL автоматически обнаруживает Deadlocks.
- **deadlock_timeout** (по умолчанию 1с): Время, через которое сервер начинает поиск циклов ожидания.
- **Разрешение**: Сервер принудительно обрывает одну из транзакций, чтобы остальные могли продолжить работу.

## Практические сценарии

### Высокопроизводительные очереди (SKIP LOCKED)
Позволяет воркерам не ждать друг друга на заблокированных строках.

```sql
BEGIN;
SELECT id FROM jobs 
WHERE status = 'pending' 
FOR UPDATE SKIP LOCKED 
LIMIT 1;

-- Обработка ...
UPDATE jobs SET status = 'completed' WHERE id = :id;
COMMIT;
```

### Координация задач (Advisor Locks)
Используются для предотвращения одновременного запуска фоновых скриптов.

```sql
-- Транзакционная блокировка: освободится при COMMIT/ROLLBACK
SELECT pg_advisory_xact_lock(1001);

-- Сессионная попытка: вернет false, если занято
SELECT pg_try_advisory_lock(1001);
```

### Диагностика очереди блокировок
Запрос для поиска PID, который блокирует остальные процессы:

```sql
SELECT 
    blocked_activity.pid AS blocked_pid,
    blocking_activity.pid AS blocking_pid,
    blocked_activity.query AS blocked_query,
    blocking_activity.query AS blocking_query
FROM pg_catalog.pg_locks AS blocked_locks
JOIN pg_catalog.pg_stat_activity AS blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks AS blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.DATABASE IS NOT DISTINCT FROM blocked_locks.DATABASE
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity AS blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.GRANTED;
```

### Безопасное выполнение миграций
Установка `lock_timeout` предотвращает «зависание» всей базы при очереди за `ALTER TABLE`.

```sql
-- Если блокировка не получена за 2 секунды, миграция завершится с ошибкой
SET lock_timeout = '2s';
ALTER TABLE products ADD COLUMN internal_code TEXT;
```

## Дополнительная информация

### Рекомендации
- **Порядок захвата**: Всегда обновляйте таблицы в одном и том же порядке (например, сначала `users`, потом `orders`), чтобы избежать Deadlocks.
- **Короткие транзакции**: Чем дольше открыта транзакция, тем дольше удерживаются блокировки и тем выше риск Bloat.
- **Индексы**: Отсутствие индекса при `UPDATE ... WHERE` заставит сервер просканировать всю таблицу, захватывая блокировки на каждую строку (или страницу).

### Смежные темы
- **[Миграции схем](./schema_migrations.md)** — управление блокировками DDL.
- **[ACID в базах данных](../../Concepts/acid.md)** — теоретические основы изоляции.
- **[Репликация в PostgreSQL](./replication.md)** — конфликты блокировок на репликах.
- **[Performance Tuning](../Operations/performance_tuning.md)** — влияние MVCC на I/O.
