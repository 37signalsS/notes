# Управление соединениями PostgreSQL

> Управление соединениями — критически важный аспект эксплуатации PostgreSQL в production. От правильной настройки зависят стабильность, масштабируемость и безопасность базы данных.

## Определения

- **Соединение (Session/Backend)** — отдельный процесс PostgreSQL, обслуживающий одного клиента. Модель **Process-per-connection**: каждое новое подключение порождает дочерний процесс (`postgres: checkpointer`, `postgres: writer`, `postgres: myuser mydb 10.0.0.1(54321) idle`).
- **max_connections** — глобальный лимит одновременных соединений, задаваемый в `postgresql.conf`. При достижении лимита новые клиенты получают `FATAL: sorry, too many clients already`.
- **superuser_reserved_connections** — зарезервированные слоты для суперпользователей (по умолчанию 3). При исчерпании `max_connections` обычные пользователи не могут подключиться, но администратор сохраняет доступ для диагностики и восстановления.
- **Connection Storm** — лавинообразный рост попыток подключения, приводящий к исчерпанию `max_connections`, fork-зависанию или падению кластера. Часто возникает при перезапуске пула приложений или отказе PgBouncer.
- **Состояния соединений (`pg_stat_activity.state`):**
  - `active` — выполняется запрос.
  - `idle` — соединение ожидает команды.
  - `idle in transaction` — транзакция открыта, но запросов нет. **Критично:** удерживает `AccessShareLock` и мешает `VACUUM`.
  - `idle in transaction (aborted)` — то же, но транзакция откатилась.
  - `fastpath function call` — выполняется быстрая функция.
  - `disabled` — соединение отключено.
- **Wait Events (`pg_stat_activity.wait_event`):** `Lock` (блокировка объекта), `LWLock` (внутренние защелки), `IO` (DataFileRead/BufFileRead), `ClientRead/ClientWrite` (ожидание сети), `Extension` (FDW).

## Параметры конфигурации

### Основные параметры (`postgresql.conf`)

| Параметр | По умолчанию | Рекомендация | Комментарий |
| :--- | :--- | :--- | :--- |
| `max_connections` | 100 | 100–500 (без PgBouncer); 100–300 (с PgBouncer) | Каждое соединение ~10 MB RAM + `work_mem` на операцию. |
| `superuser_reserved_connections` | 3 | 3–5 | Защита от полной блокировки при Connection Storm. |
| `work_mem` | 4MB | 4–64MB | На **каждую** операцию сортировки/хэша. При `max_connections=200` и `work_mem=64MB` потенциально 12.8 GB RAM только на сортировки. |
| `idle_in_transaction_session_timeout` | 0 (off) | 30s–5min | Автоматически завершает сессии в `idle in transaction`. См. troubleshooting. |
| `statement_timeout` | 0 (off) | 30s–5min (OLTP); 0 (OLAP) | Прерывает запросы, выполняющиеся дольше лимита. |
| `lock_timeout` | 0 (off) | 2–10s | Ограничивает время ожидания блокировки. |
| `tcp_keepalives_idle` | 2h | 60s | Время до отправки первого keepalive-пакета. |
| `tcp_keepalive_interval` | 75s | 10s | Интервал между повторными keepalive-пакетами. |
| `tcp_keepalive_count` | 20 | 6 | Количество неудачных keepalive перед закрытием соединения. |
| `track_activity_query_size` | 1024 | 2048–4096 | Размер буфера для хранения текста запроса в `pg_stat_activity`. |
| `compute_query_id` | off | on (PG 14+) | Позволяет коррелировать `pg_stat_activity` и `pg_stat_statements` по `query_id`. |

### Взаимодействие с PgBouncer

При использовании внешнего пулера:
- `max_connections` можно снизить до 100–300, так как PgBouncer обслуживает тысячи клиентов через ограниченное число реальных соединений.
- `idle_in_transaction_session_timeout` и `statement_timeout` настраиваются **на стороне PostgreSQL**, а не PgBouncer.
- `superuser_reserved_connections` резервируются для административных подключений, минуя пулер.

Подробнее: **[Настройка PgBouncer](./pgbouncer_setup.md)**.

## Capacity Planning

### Формула расчета RAM на соединения

```
Общая RAM на соединения = max_connections × (work_mem + overhead)
```

**Overhead** включает стек процесса, локальные переменные и кэш. Практическое правило:
- ~10 MB RAM на простое соединение в состоянии `idle`.
- Дополнительно `work_mem` на каждую активную операцию сортировки/хэша.

**Пример:**
```
max_connections = 200
work_mem = 16MB
RAM ≈ 200 × (10 MB + 16 MB) = 5.2 GB
```

### Правило загрузки

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| `pg_stat_activity_count / max_connections` | > 70% | Планировать увеличение пула или PgBouncer. |
| Доля `idle in transaction` | > 5% | Найти и исправить зависшие транзакции в приложении. |
| `client_waiting` (PgBouncer) | > 0 | Увеличить `default_pool_size` или оптимизировать долгие запросы. |
| `wait_event = 'Lock'` длительностью > 30s | > 0 | Анализ блокировок через `pg_locks`. |

## Мониторинг и диагностика

### Системные представления

**`pg_stat_activity`** — основное представление для анализа соединений:

```sql
-- Общая статистика по состояниям
SELECT state, count(*)
FROM pg_stat_activity
GROUP BY state;

-- Топ-10 долгих транзакций (включая idle in transaction)
SELECT pid, usename, state, now() - xact_start AS xact_age, now() - query_start AS query_age, left(query, 100) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
ORDER BY xact_start
LIMIT 10;

-- Соединения, ожидающие блокировок
SELECT pid, usename, wait_event_type, wait_event, state, query
FROM pg_stat_activity
WHERE wait_event_type = 'Lock';

-- Запросы, ожидающие I/O
SELECT pid, wait_event, query
FROM pg_stat_activity
WHERE wait_event_type = 'IO'
ORDER BY query_start;
```

**`pg_locks`** — анализ блокировок:

```sql
-- Поиск блокирующих и заблокированных процессов
SELECT blocked_locks.pid AS blocked_pid,
       blocking_locks.pid AS blocking_pid,
       blocked_activity.query AS blocked_statement,
       blocking_activity.query AS blocking_statement,
       age(blocked_activity.xact_start) AS blocked_xact_age
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

### Prometheus / Grafana

Через `postgres_exporter`:

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `pg_stat_activity_count{state="active"}` | Активные запросы | Рост без роста TPS = долгие запросы. |
| `pg_stat_activity_count{state="idle in transaction"}` | Зависшие транзакции | > 0 на протяжении 5 минут. |
| `pg_stat_activity_count{state="waiting"}` | Ожидающие блокировки | > 0 — блокировка. |
| `pg_stat_activity_max_tx_duration` | Длительность самой старой транзакции | > 300 сек. |
| `pg_settings_max_connections` | Лимит соединений | — |
| `pg_stat_activity_count / pg_settings_max_connections` | Утилизация пула в % | > 80%. |

## Управление соединениями

### Принудительное завершение сессий

```sql
-- Завершить конкретный процесс (аналог kill -9 для сессии)
SELECT pg_terminate_backend(pid);

-- Отменить текущий запрос, но не разрывать соединение
SELECT pg_cancel_backend(pid);

-- Завершить все соединения с базой, кроме текущего
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'myapp_db' AND pid <> pg_backend_pid();

-- Завершить все idle in transaction старше 5 минут
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND xact_start < now() - interval '5 minutes';
```

### Изменение параметров без перезагрузки

```sql
-- Глобально (на все новые сессии)
ALTER SYSTEM SET idle_in_transaction_session_timeout = '60s';
ALTER SYSTEM SET work_mem = '32MB';

-- Применить без restart
SELECT pg_reload_conf();

-- Только для текущей сессии
SET statement_timeout = '10s';
SET lock_timeout = '5s';
```

### Ограничение соединений на уровне пользователя/базы

```sql
-- Лимит соединений для пользователя
ALTER ROLE app_user CONNECTION LIMIT 50;

-- Лимит для базы (через pg_hba.conf или ALTER DATABASE)
-- В pg_hba.conf:
-- host    myapp_db    app_user    10.0.0.0/8    scram-sha-256    +connection_limit=50
```

## Типичные проблемы и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`FATAL: sorry, too many clients already`** | `max_connections` исчерпан. | Завершить зависшие сессии (`pg_terminate_backend`), увеличить `max_connections` или внедрить PgBouncer. |
| **`FATAL: remaining connection slots are reserved`** | Обычные пользователи исчерпали лимит, остались только зарезервированные слоты. | То же, что выше; `superuser_reserved_connections` защищает админский доступ. |
| **`idle in transaction` растет** | Приложение не закрывает транзакцию после запроса. | Установить `idle_in_transaction_session_timeout = '60s'`, исправить код приложения. |
| **`Lock`/`waiting` в `pg_stat_activity`** | Блокировка таблицы/строки. | Найти блокирующий PID через `pg_locks`, завершить его или дождаться освобождения. |
| **Connection Storm после рестарта приложения** | Десятки/сотни воркеров одновременно создают соединения. | Внедрить PgBouncer, использовать `tcp_keepalive` для быстрого обнаружения мертвых соединений, настроить `LIMIT NOFILE`. |
| **`pg_stat_activity` пустой, но `max_connections` исчерпан** | Соединения в состоянии `idle in transaction (aborted)` или зависли на уровне ОС. | `netstat -tnp | grep :5432`, `ss -tnp state established '( dport = :5432 )'`, `lsof -i :5432`. |
| **Рост `wait_event = 'ClientRead'`** | Приложение не читает ответы, буфер переполняется. | Проверить сеть, таймауты на стороне приложения, `tcp_keepalive`. |
| **Долгие запросы без `wait_event`** | Запрос активно выполняется, но медленно. | `EXPLAIN ANALYZE`, проверить индексы, `pg_stat_statements`. |

## Безопасность соединений

### `pg_hba.conf` — управление доступом

Файл `/etc/postgresql/.../main/pg_hba.conf` (или `$PGDATA/pg_hba.conf`) определяет, кто, откуда и как может подключаться:

```ini
# TYPE  DATABASE  USER  ADDRESS  METHOD  [OPTIONS]
local   all       all              trust
host    all       all   10.0.0.0/8  scram-sha-256
host    all       all   0.0.0.0/0   reject
host    replication  replicator  10.0.0.0/8  scram-sha-256
```

Применение:
```bash
sudo systemctl reload postgresql
# или
pg_ctlcluster 16 main reload
```

**Важно:** `scram-sha-256` — обязательный метод для production. `trust` разрешает только на `local` или `127.0.0.1` (локальная отладка). `reject` — явный запрет.

### TLS/SSL для соединений

```ini
# postgresql.conf
ssl = on
ssl_cert_file = '/etc/ssl/certs/postgres.crt'
ssl_key_file = '/etc/ssl/private/postgres.key'
ssl_ca_file = '/etc/ssl/certs/ca.crt'
ssl_min_protocol_version = 'TLSv1.3'
```

```sql
-- Проверка SSL-статуса соединения
SELECT pid, ssl, version, client_addr
FROM pg_stat_ssl
JOIN pg_stat_activity USING (pid);
```

### Лимиты и правила

- Используйте `ALTER ROLE ... CONNECTION LIMIT` для критичных пользователей.
- Изолируйте административные и прикладные пользователи в разные базы данных или кластеры.
- Включите `log_connections = on` и `log_disconnections = on` для аудита.

## Валидация и проверка

1. **Проверка текущих соединений:**
   ```bash
   psql -c "SELECT count(*) FROM pg_stat_activity;"
   ss -tnp | grep :5432 | wc -l
   ```
2. **Проверка `idle in transaction`:**
   ```sql
   SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction';
   ```
   Ожидаемый результат: `0` в healthy-состоянии.
3. **Проверка блокировок:**
   ```sql
   SELECT count(*) FROM pg_locks WHERE NOT granted;
   ```
   Ожидаемый результат: `0` или кратковременные ненулевые значения.
4. **Проверка `pg_hba.conf`:**
   ```bash
   sudo -u postgres pg_ctlcluster 16 main reload
   # → без ошибок
   ```
5. **Нагрузочный тест:**
   ```bash
   pgbench -c 50 -j 4 -T 30 -P 1 mydb
   ```
   Убедитесь, что `max_connections` не исчерпан и нет `idle in transaction` после теста.

## Вопросы на собеседованиях

1. **`Process-per-connection` vs Connection Pooling:** — Ответ: PostgreSQL создает процесс на каждое соединение. При >500 соединениях накладные расходы на контекстные переключения снижают RPS. PgBouncer transaction pooling позволяет обслуживать тысячи клиентов через 100–200 реальных процессов.
2. **Чем `idle in transaction` отличается от `idle`?** — Ответ: `idle` — подключение ожидает команды, не удерживает блокировок. `idle in transaction` — транзакция открыта, удерживает `AccessShareLock` и мешает `VACUUM`.
3. **Как защититься от Connection Storm?** — Ответ: `superuser_reserved_connections`, PgBouncer, `tcp_keepalive` с короткими интервалами, `ulimit -n`, `backlog` в `postgresql.conf` (`listen_backlog`).
4. **Что делает `idle_in_transaction_session_timeout`?** — Ответ: автоматически завершает сессии, зависшие в `idle in transaction`, предотвращая деградацию VACUUM и накопление Bloat.
5. **Как найти и убить блокирующий процесс?** — Ответ: `pg_locks` + `pg_stat_activity` join по `pid`, затем `pg_terminate_backend(pid)`.

## См. также

- **[Оптимизация производительности](./performance_tuning.md)** — общий тюнинг PostgreSQL.
- **[Настройка PgBouncer](./pgbouncer_setup.md)** — внешний пул соединений.
- **[Наблюдаемость PostgreSQL](./observability.md)** — мониторинг, wait events, трассировка.
- **[Управление параллелизмом и блокировки](../Concepts/concurrency_and_locking.md)** — MVCC, уровни изоляции, deadlocks.
- **[Работа через консоль (psql)](./console_basics.md)** — `pg_stat_activity`, `\watch`, типовые ошибки.
- **[Сетевая связность в Kubernetes](./kubernetes_connectivity.md)** — Topology Aware Routing, latency.
