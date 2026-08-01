# Конкурентность и блокировки в PostgreSQL

## Определения

- **MVCC (Multi-Version Concurrency Control)** — механизм управления доступом, при котором чтение не блокирует запись, а запись не блокирует чтение. Каждое изменение создает новую версию строки.
- **Уровень изоляции (Isolation Level)** — настройка, определяющая видимость изменений других транзакций (Read Committed, Repeatable Read, Serializable).
- **Snapshot (Снимок)** — логическое состояние данных в конкретный момент времени, с которым работает транзакция.
- **Deadlock (Взаимоблокировка)** — ситуация, когда две или более транзакции циклически ждут освобождения ресурсов друг друга.
- **Advisor Locks (Рекомендательные блокировки)** — пользовательские блокировки по числовым идентификаторам, не привязанные к строкам таблиц.

> **Важно:** PostgreSQL фундаментально построен на блокировках (даже чтение вызывает блокировку минимального уровня). Мониторинг **локов** (особенно высокоуровневых, перекрывающих доступ к таблицам) — это первая и самая важная задача при диагностике производительности PostgreSQL.

## Базовые концепции

### Механизм MVCC и мертвые строки
PostgreSQL реализует MVCC через хранение версий строк непосредственно в таблице.
- **Версионность**: При `UPDATE` старая версия помечается как «мертвая», создается новая.
- **Bloat (Раздувание)** — накопление мертвых строк, замедляющее работу. Очисткой занимается процесс **Autovacuum**.
- **Visibility Map** — структура данных, позволяющая пропускать блоки данных, не содержащие мертвых строк, при выполнении `VACUUM`.

### Уровни изоляции транзакций
PostgreSQL поддерживает три уровня изоляции (четвертый, `Read Uncommitted`, работает как `Read Committed`).

| Уровень | Особенности в PostgreSQL | Применение |
| :--- | :--- | :--- |
| **Read Committed** | Снимок создается для **каждого запроса**. Дефолтный уровень. | Большинство стандартных приложений. |
| **Repeatable Read** | Снимок один на **всю транзакцию**. Защита от «фантомов». | Генерация отчетов, согласованная выборка. |
| **Serializable** | Полная изоляция через предикатные блокировки. | Критичные финансовые операции. |

### Иерархия блокировок

#### Блокировки таблиц
Существует 8 режимов блокировок таблиц. Самые частые:
1.  **ACCESS SHARE** — захватывается при `SELECT`. Совместим со всем, кроме `ACCESS EXCLUSIVE`.
2.  **ROW EXCLUSIVE** — захватывается при `INSERT`, `UPDATE`, `DELETE`.
3.  **SHARE UPDATE EXCLUSIVE** — захватывается при `VACUUM` и `CREATE INDEX CONCURRENTLY`.
4.  **ACCESS EXCLUSIVE** — захватывается при `ALTER TABLE`. Блокирует даже `SELECT`.

#### Блокировки строк (Row-Level Locks)
- **FOR UPDATE** — полная блокировка строки на изменение.
- **FOR SHARE** — позволяет другим читать (`FOR SHARE`), но не менять.
- **FOR NO KEY UPDATE** — захватывается при `UPDATE`, не затрагивающем уникальные ключи (позволяет параллельно создавать внешние ключи на эту строку).

## Практические сценарии

### Реализация очереди задач (SKIP LOCKED)
Для создания высокопроизводительных очередей без блокировок между воркерами:

```sql
-- Воркер забирает одну свободную задачу, пропуская уже заблокированные
BEGIN;
SELECT id FROM jobs 
WHERE status = 'pending' 
ORDER BY priority DESC 
FOR UPDATE SKIP LOCKED 
LIMIT 1;

-- Обработка ...
UPDATE jobs SET status = 'completed' WHERE id = :id;
COMMIT;
```

### Использование Advisor Locks
Идеально подходят для координации фоновых задач (например, `cron`).
- **Сессионные**: `pg_advisory_lock(id)` — действуют до конца сессии или явного `unlock`.
- **Транзакционные**: `pg_advisory_xact_lock(id)` — действуют до конца транзакции.

```sql
-- Попытка захватить блокировку без ожидания (возвращает boolean)
SELECT pg_try_advisory_lock(1001);
```

### Диагностика блокировок
Для поиска процесса, который «подвесил» систему:

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
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity AS blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.GRANTED;
```

### Безопасное выполнение DDL
Чтобы миграция не заблокировала доступ к таблице для всех пользователей:

```sql
-- Установка таймаута на ожидание блокировки
SET lock_timeout = '2s';
ALTER TABLE users ADD COLUMN age INT;
```

## Дополнительная информация

### Смежные темы
- **[Миграции схем в PostgreSQL](./schema_migrations.md)** — управление блокировками при изменении структуры.
- **[ACID в базах данных](../../Concepts/acid.md)** — теоретические основы изоляции.
- **[Репликация в PostgreSQL](./replication.md)** — передача блокировок на реплики.
- **[Performance Tuning](../Operations/performance_tuning.md)** — влияние MVCC Bloat на производительность.

### Рекомендации
- Старайтесь держать транзакции максимально короткими.
- При обновлении нескольких таблиц всегда соблюдайте один и тот же порядок обращения к ним (профилактика Deadlocks).
- Используйте `FOR UPDATE SKIP LOCKED` вместо сложных схем статусов для очередей.
