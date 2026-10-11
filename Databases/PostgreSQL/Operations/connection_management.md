# Управление соединениями PostgreSQL

**Актуально для:** PostgreSQL 13–18 (текущие релизы: 18.6 / 17.11 / 16.15 / 15.19 / 14.24); `reserved_connections` — PG 17+, `idle_session_timeout` и `compute_query_id` — PG 14+

> Управление соединениями — критически важный аспект эксплуатации PostgreSQL в production. Из-за модели process-per-connection каждое подключение — отдельный процесс, а исчерпание `max_connections` блокирует всех клиентов, включая приложение. Здесь: слоты соединений, лимиты, таймауты, диагностика зависших сессий и безопасность подключений.

## Определения

- **Соединение (Backend)** — отдельный процесс PostgreSQL, обслуживающий одного клиента. Модель **process-per-connection**: каждое новое подключение порождает дочерний процесс (`postgres: myuser mydb 10.0.0.1(54321) idle`).
- **max_connections** — глобальный лимит одновременных соединений в `postgresql.conf`. Контекст `postmaster`: изменение требует **перезапуска** кластера, `pg_reload_conf()` недостаточно. При достижении лимита новые клиенты получают `FATAL: sorry, too many clients already`.
- **superuser_reserved_connections** — слоты, зарезервированные для суперпользователей (по умолчанию 3, контекст `postmaster`). Когда свободных слотов остаётся не больше этого значения, подключаются только суперпользователи — администратор сохраняет доступ для диагностики и восстановления.
- **reserved_connections** (PG 17+) — слоты для ролей с правом `pg_use_reserved_connections` (по умолчанию 0, контекст `postmaster`). Когда свободных слотов больше `superuser_reserved_connections`, но не больше суммы `superuser_reserved_connections + reserved_connections`, подключаются ещё и эти роли — резерв для мониторинга и миграций при исчерпании пула. Ограничение: значение должно быть меньше `max_connections − superuser_reserved_connections`.
- **Connection Storm** — лавинообразный рост попыток подключения (перезапуск приложения, отказ PgBouncer), приводящий к исчерпанию `max_connections`.
- **Состояния соединений** (`pg_stat_activity.state`):
  - `active` — выполняется запрос.
  - `idle` — соединение ожидает команду.
  - `idle in transaction` — транзакция открыта, запросов нет. **Критично:** удерживает `AccessShareLock` и мешает `VACUUM` (удерживает `xmin`, вызывает раздувание).
  - `idle in transaction (aborted)` — то же, но транзакция откатилась.
  - `fastpath function call` — выполняется быстрая функция.
  - `disabled` — отслеживание активности выключено (`track_activities = off`).
- **Wait Events** (`pg_stat_activity.wait_event` + `wait_event_type`) — причина, по которой процесс не выполняет работу: `Lock` (блокировка объекта), `LWLock` (внутренние защёлки), `IO` (DataFileRead/BufFileRead), `ClientRead/ClientWrite` (ожидание сети), `Extension` (FDW). Полная шпаргалка по событиям — в **[Наблюдаемость](./observability.md)**.

## Как распределяются слоты соединений

Слот занимает **любая** сессия — и `active`, и `idle` — до отключения. Три уровня доступа при исчерпании пула (логика параметров `superuser_reserved_connections` и `reserved_connections`):

| Свободных слотов | Кто может подключиться |
| :--- | :--- |
| Больше `superuser_reserved_connections + reserved_connections` | Все клиенты |
| Больше `superuser_reserved_connections`, но не больше суммы | Суперпользователи и роли с правом `pg_use_reserved_connections` |
| Не больше `superuser_reserved_connections` | Только суперпользователи — обычные клиенты получают `FATAL: remaining connection slots are reserved for non-replication superuser connections` |

Практический вывод: при `max_connections = 200`, `superuser_reserved_connections = 5`, `reserved_connections = 10` администратор и роли мониторинга сохраняют доступ при 185+ занятых слотах, а приложение — уже нет.

## Предпосылки

- **Доступ к кластеру:** `psql` (см. **[Работа через консоль](./console_basics.md)**), `pg_ctlcluster`/`systemctl` (см. **[Установка на Ubuntu](./installation_ubuntu.md)**).
- **Права:** непривилегированный пользователь видит в `pg_stat_activity` только свои сессии полностью (в строках чужих большинство колонок `NULL`); полный обзор требует `pg_read_all_stats` или суперпользователя. `pg_cancel_backend`/`pg_terminate_backend` для чужих сессий — право `pg_signal_backend` (см. **[Роли и базы данных](./role_management.md)**).
- **Файлы конфигурации:** `postgresql.conf`, `pg_hba.conf` — расположение и reload см. в **[Установке на Ubuntu](./installation_ubuntu.md)**.

## Параметры конфигурации

### Основные параметры (`postgresql.conf`)

| Параметр | По умолчанию | Рекомендация | Контекст / применение |
| :--- | :--- | :--- | :--- |
| `max_connections` | 100 | 100–500 (без PgBouncer); 100–300 (с PgBouncer) | `postmaster` — **только restart** |
| `superuser_reserved_connections` | 3 | 3–5 | `postmaster` — **только restart** |
| `reserved_connections` (PG 17+) | 0 | 5–20 для ролей мониторинга/миграций | `postmaster` — **только restart**; < `max_connections − superuser_reserved_connections` |
| `work_mem` | 4MB | 4–64MB | user — `SET`/`ALTER SYSTEM` + reload; на **каждую** операцию сортировки/хэша. При `max_connections=200` и `work_mem=64MB` потенциально 12.8 GB RAM только на сортировки |
| `idle_in_transaction_session_timeout` | 0 (off, PG 9.6+) | 30s–5min | user — `ALTER SYSTEM` + reload |
| `idle_session_timeout` (PG 14+) | 0 (off) | 5–30min; осторожно с пулерами | user — `ALTER SYSTEM` + reload |
| `statement_timeout` | 0 (off) | 30s–5min (OLTP); 0 (OLAP) | user — лучше `SET LOCAL` в транзакции |
| `lock_timeout` | 0 (off) | 2–10s | user; в `postgresql.conf` не рекомендуется (влияет на все сессии) |
| `tcp_keepalives_idle` | 7200s (2h) | 60s | user — время до первого keepalive-пакета |
| `tcp_keepalive_interval` | 75s | 10s | user — интервал между повторными keepalive |
| `tcp_keepalive_count` | 20 | 6 | user — неудачных keepalive перед закрытием |
| `track_activity_query_size` | 1024 | 2048–4096 | superuser — размер буфера текста запроса в `pg_stat_activity` |
| `compute_query_id` (PG 14+) | `auto` | `auto`/`on` | superuser; `auto` — вычисление `query_id` включается при загрузке `pg_stat_statements`/`auto_explain`, коррелирует `pg_stat_activity` и `pg_stat_statements` |

**Restart vs reload:** `max_connections`, `superuser_reserved_connections` и `reserved_connections` меняются только перезапуском кластера (`pg_ctlcluster <ver> <cluster> restart`). Таймауты, `tcp_keepalives_*`, `track_activity_query_size` применяются по `pg_reload_conf()` (SIGHUP). `statement_timeout`, `lock_timeout`, `idle_*_timeout` задаются на уровне сессии (`SET`).

### Взаимодействие с PgBouncer

При использовании внешнего пулера:
- `max_connections` можно снизить до 100–300, так как PgBouncer обслуживает тысячи клиентов через ограниченное число реальных соединений. Правило: суммарный `default_pool_size` всех пулов **меньше** `max_connections` (запас 30% на админов, миграции, логическую репликацию).
- `idle_in_transaction_session_timeout` и `statement_timeout` настраиваются **на стороне PostgreSQL**, а не PgBouncer.
- `superuser_reserved_connections` и `reserved_connections` резервируются для административных подключений, минуя пулер.

Режимы пулинга, `default_pool_size`, аутентификация и `max_prepared_statements` — в **[Настройка PgBouncer](./pgbouncer_setup.md)** (SSoT по PgBouncer); общая теория пулов — в **[Connection Pooling](../../../Networking/Concepts/connection_pooling.md)**.

## Capacity Planning

### Формула расчета RAM на соединения

```
Общая RAM на соединения = max_connections × (overhead + work_mem)
```

**Overhead** включает стек процесса, локальные переменные и кэш. Практическое правило:
- ~10 MB RAM на простое соединение в состоянии `idle`.
- Дополнительно `work_mem` на каждую активную операцию сортировки/хэша.

Формула выше — верхняя оценка для одного узла плана на соединение. Реальное потребление одного запроса выше: `work_mem` умножается на `hash_mem_multiplier`, на число узлов сортировки/хеша в плане и на число параллельных воркеров. Полная формула и признаки spill на диск — в **[Оптимизация производительности](./performance_tuning.md)**.

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
| Ожидание `Lock` длительностью > 30s | > 0 | Анализ блокировок через `pg_blocking_pids()` и `pg_locks`. |

## Мониторинг и диагностика

### `pg_stat_activity` — кто занимает слоты

```sql
-- Распределение соединений по состояниям
SELECT state, count(*)
FROM pg_stat_activity
GROUP BY state;

-- Соединения по пользователям, базам и приложениям
SELECT usename, datname, application_name, state, count(*)
FROM pg_stat_activity
GROUP BY 1, 2, 3, 4
ORDER BY count(*) DESC;

-- Старейшие клиентские сессии (по времени подключения)
SELECT pid, usename, datname, application_name, state,
       now() - backend_start AS conn_age, left(query, 80) AS query
FROM pg_stat_activity
WHERE backend_type = 'client backend'
ORDER BY backend_start
LIMIT 10;
```

`application_name` задаётся строкой подключения (`application_name=billing`) или `SET application_name = 'billing';` — без него все сессии приложения выглядят одинаково.

**Смежные диагностики — в SSoT-файлах:**
- Долгие транзакции (включая `idle in transaction`), Prometheus-метрики состояний сессий, шпаргалка по wait events — **[Наблюдаемость](./observability.md)**.
- Блокировки: рекомендуемый способ — `pg_blocking_pids(pid)` (документация рекомендует её вместо self-join `pg_locks`, который не видит порядка в очереди ожидания); глубокий разбор `pg_locks`, цепочек блокировок и каскада при миграциях — **[Управление параллелизмом и блокировки](../Concepts/concurrency_and_locking.md)**.

### Prometheus / Grafana

Через `postgres_exporter` (полный набор алертов — в **[Наблюдаемости](./observability.md)**):

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `pg_settings_max_connections` | Лимит соединений | — |
| `pg_stat_activity_count / pg_settings_max_connections` | Утилизация пула в % | > 80% |
| `pg_stat_activity_count{state="idle in transaction"}` | Зависшие транзакции | > 0 на протяжении 5 минут |
| `pg_stat_activity_max_tx_duration` | Длительность самой старой транзакции | > 300 сек. |

## Управление соединениями

### Принудительное завершение сессий

```sql
-- Отменить текущий запрос, не разрывая соединение
SELECT pg_cancel_backend(pid);

-- Завершить конкретную сессию (аналог kill -9 для сессии)
SELECT pg_terminate_backend(pid);

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

Права: для чужих сессий требуется `pg_signal_backend` или суперпользователь; свою сессию роль может завершить сама (см. **[Роли](./role_management.md)**). Для освобождения базы перед `DROP` в PG 13+ есть альтернатива: `DROP DATABASE myapp_db WITH (FORCE);` — завершает подключения автоматически.

### Изменение параметров без перезагрузки

```sql
-- Глобально (на все новые сессии; только для reloadable-параметров)
ALTER SYSTEM SET idle_in_transaction_session_timeout = '60s';
ALTER SYSTEM SET work_mem = '32MB';

-- Применить без restart (SIGHUP)
SELECT pg_reload_conf();

-- Только для текущей сессии
SET statement_timeout = '10s';
SET lock_timeout = '5s';
```

`max_connections`, `superuser_reserved_connections` и `reserved_connections` через `ALTER SYSTEM` + reload **не применяются** — требуется restart кластера.

### Ограничение соединений на уровне пользователя/базы

```sql
-- Лимит одновременных соединений для пользователя (-1 = без лимита)
ALTER ROLE app_user CONNECTION LIMIT 50;

-- Лимит для базы
ALTER DATABASE myapp_db CONNECTION LIMIT 100;
```

**Важно:** `pg_hba.conf` **не поддерживает** лимитов соединений — в нём нет опции вида `connection_limit`. Лимиты задаются только на уровне роли (`CREATE/ALTER ROLE ... CONNECTION LIMIT`) или базы (`ALTER DATABASE ... CONNECTION LIMIT`).

### Connection Storm: анатомия и защита

**Connection Storm** — лавинообразный рост попыток подключения (перезапуск приложения, отказ PgBouncer, раскрутка автомасштабирования), который исчерпывает `max_connections` и блокирует **всех** клиентов, включая администратора.

**Механика:** каждое подключение — форк процесса. При штурме:
1.  Ядро тратит CPU на форк и контекстные переключения (сначала деградация, потом недоступность).
2.  `max_connections` исчерпывается → новые клиенты получают `FATAL: sorry, too many clients already`.
3.  Когда свободных слотов ≤ `superuser_reserved_connections` → обычные клиенты получают `FATAL: remaining connection slots are reserved for non-replication superuser connections`, а администратор сохраняет доступ.

**Защита (в порядке эффективности):**

1.  **PgBouncer** — единственный способ пережать штурм тысяч клиентов: пулер ставит их в очередь (`client_waiting`), а не даёт ошибку.
2.  **`superuser_reserved_connections = 3–5`** (и `reserved_connections` на PG 17+ для ролей мониторинга) — доступ для диагностики во время штурма.
3.  **`ALTER ROLE app_user CONNECTION LIMIT`** — потолок на роль, чтобы одна служба не съела весь пул.
4.  **`tcp_keepalives_*`** с короткими интервалами (60s/10s/6) — быстрое обнаружение мёртвых клиентов.
5.  **`ulimit -n` (`LIMIT NOFILE`)** и `listen_backlog` в `postgresql.conf` — ядерные лимиты на число открытых сокетов и очередь SYN.
6.  **Exponential backoff на стороне приложения** — без него рестарт приложения порождает синхронный штурм.

**Диагностика во время штурма:**

```sql
-- Распределение по состояниям и приложениям (от суперпользователя или pg_read_all_stats)
SELECT application_name, state, count(*)
FROM pg_stat_activity
GROUP BY 1, 2 ORDER BY 3 DESC;

-- Сколько слотов осталось
SELECT (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')
     - count(*) AS free_slots
FROM pg_stat_activity;
-- → free_slots
-- → 3   — почти конец; админские слоты ещё доступны
```

**Валидация защиты:** см. сценарий инъекции в [Chaos Engineering](./chaos_engineering.md#6-connection-storm).

## Безопасность соединений

### `pg_hba.conf` — управление доступом

Файл определяет, кто, откуда и как может подключаться (расположение: `/etc/postgresql/<ver>/<cluster>/pg_hba.conf` или `$PGDATA/pg_hba.conf`):

```ini
# TYPE  DATABASE        USER            ADDRESS         METHOD
local   all             all                         peer
host    all             all             10.0.0.0/8    scram-sha-256
host    all             all             0.0.0.0/0     reject
hostssl all             all             10.0.0.0/8    scram-sha-256
host    replication     replicator      10.0.0.0/8    scram-sha-256
```

- Записи проверяются **последовательно** для каждого подключения — порядок важен; `reject` — явный запрет, `hostssl`/`hostnossl` — только TLS/не-TLS подключения.
- Метод аутентификации: `scram-sha-256` — стандарт для production; `peer` — локальный Unix-сокет; `trust` — только для локальной отладки. Разбор методов и SSL — в **[Безопасность и шифрование](../Concepts/security_and_encryption.md)** (SSoT).
- Правила применяются по SIGHUP:

```bash
sudo systemctl reload postgresql
# или
sudo -u postgres pg_ctlcluster 18 main reload
```

- Предпроверка правил без подключения клиентов — системное представление `pg_hba_file_rules`:

```sql
SELECT line_number, type, database, user_name, error
FROM pg_hba_file_rules
WHERE error IS NOT NULL;
-- → (0 rows) — нет синтаксических ошибок в pg_hba.conf
```

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

Генерация сертификатов, настройка CA и политики шифрования — в **[Безопасность установки](../../installation_security.md)**.

### Лимиты и правила

- Используйте `ALTER ROLE ... CONNECTION LIMIT` для критичных пользователей.
- Изолируйте административные и прикладные пользователи в разные базы данных или кластеры.
- Включите `log_connections = on` и `log_disconnections = on` для аудита подключений.

## Типичные проблемы и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`FATAL: sorry, too many clients already`** | `max_connections` исчерпан. | Завершить зависшие сессии (`pg_terminate_backend`), увеличить `max_connections` (restart) или внедрить PgBouncer. |
| **`FATAL: remaining connection slots are reserved for non-replication superuser connections`** | Обычные пользователи исчерпали лимит; остались только зарезервированные слоты. | То же, что выше; `superuser_reserved_connections` защищает админский доступ. |
| **`idle in transaction` растёт** | Приложение не закрывает транзакцию после запроса. | Установить `idle_in_transaction_session_timeout = '60s'`, исправить код приложения. |
| **`Lock`/`waiting` в `pg_stat_activity`** | Блокировка таблицы/строки. | Найти блокирующий PID через `pg_blocking_pids()`, завершить его или дождаться освобождения. |
| **Connection Storm после рестарта приложения** | Десятки/сотни воркеров одновременно создают соединения. | Внедрить PgBouncer, использовать `tcp_keepalive` с короткими интервалами, поднять `ulimit -n` (`LIMIT NOFILE`), настроить `listen_backlog`. |
| **Мало строк в `pg_stat_activity`, но слоты заняты** | Непривилегированный пользователь видит только свои сессии; либо пулер держит серверные бэкенды. | Проверить от суперпользователя (или с `pg_read_all_stats`); считать серверные бэкенды: `SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';` |
| **Рост `wait_event = 'ClientRead'`** | Приложение не читает ответы, буфер переполняется. | Проверить сеть, таймауты на стороне приложения, `tcp_keepalive`. |
| **Долгие запросы без `wait_event`** | Запрос активно выполняется, но медленно. | `EXPLAIN ANALYZE`, проверить индексы, `pg_stat_statements`. |
| **`FATAL: no pg_hba.conf entry for host ...`** | Нет подходящего правила для пары «адрес, база, пользователь». | Добавить запись в `pg_hba.conf`, reload; проверить `pg_hba_file_rules`. |
| **Изменения `pg_hba.conf` не применяются** | Файл перечитывается только по SIGHUP. | `systemctl reload postgresql` / `pg_reload_conf()`; проверить `pg_hba_file_rules` (поле `error`). |

## Валидация и проверка

1. **Проверка текущих соединений:**
   ```bash
   psql -c "SELECT count(*) FROM pg_stat_activity;"
   ss -tnp | grep :5432 | wc -l
   # → число сетевых подключений ≈ count(*) + служебные процессы
   ```
2. **Проверка `idle in transaction`:**
   ```sql
   SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction';
   -- → 0 в healthy-состоянии
   ```
3. **Проверка блокировок:**
   ```sql
   SELECT count(*) FROM pg_locks WHERE NOT granted;
   -- → 0 или кратковременные ненулевые значения
   ```
4. **Проверка `pg_hba.conf`:**
   ```bash
   sudo -u postgres pg_ctlcluster 18 main reload
   # → без ошибок
   psql -c "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;"
   # → 0
   ```
5. **Доступность кластера:**
   ```bash
   pg_isready -h localhost -p 5432
   # → localhost:5432 - accepting connections
   ```
6. **Нагрузочный тест** (требуется `postgresql-contrib` и инициализация тестовой базы `pgbench -i mydb`):
   ```bash
   pgbench -c 50 -j 4 -T 30 -P 1 mydb
   ```
   Убедитесь, что `max_connections` не исчерпан и нет `idle in transaction` после теста.

## Лучшие практики

- **Пулинг перед повышением лимита:** при подходе к 70% от `max_connections` сначала оцените PgBouncer — рост `max_connections` линейно потребляет RAM и требует restart.
- **Таймауты по умолчанию:** `idle_in_transaction_session_timeout = '60s'` и `statement_timeout` на критичных ролях — дешёвая страховка от зависших сессий и каскада блокировок.
- **Именование приложений:** `application_name` в строке подключения — без него диагностика «кто занял слоты» невозможна.
- **Резерв для администрирования:** `superuser_reserved_connections = 3–5`; на PG 17+ — `reserved_connections` для ролей мониторинга и миграций с правом `pg_use_reserved_connections`.
- **Таймауты в пулере:** `idle_session_timeout` применяйте осторожно через PgBouncer — пулер может плохо реагировать на неожиданное закрытие серверного соединения (предупреждение из документации); safer — только для интерактивных ролей.

## Очистка и откат

```sql
-- Откат изменений, внесённых через ALTER SYSTEM
ALTER SYSTEM RESET idle_in_transaction_session_timeout;
ALTER SYSTEM RESET work_mem;
-- или сразу все параметры
ALTER SYSTEM RESET ALL;

-- Применить (SIGHUP)
SELECT pg_reload_conf();
```

`ALTER SYSTEM` пишет в `postgresql.auto.conf`; `RESET ALL` очищает файл. Для параметров `postmaster`-контекста (`max_connections` и др.) после правки `postgresql.conf` достаточно убрать изменение и перезапустить кластер.

## Пограничные случаи

- **Transaction pooling и таймауты:** в PgBouncer в режиме transaction pooling `SET`-параметры теряются между транзакциями (кроме отслеживаемых через `track_extra_parameters`); сессионные таймауты задавайте на роли (`ALTER ROLE ... SET statement_timeout`), а не командой `SET`.
- **`max_connections` на репликах:** при логической репликации и FDW учитывайте, что каждая сессия, обращающаяся к FDW, удерживает соединение с удалённым сервером (`keep_connections 'off'` для экономии — см. **[FDW](../Integrations/fdw.md)**).
- **`track_activities = off`:** состояния сессий в `pg_stat_activity` показываются как `disabled` — диагностика по состояниям невозможна.
- **Несколько версий PostgreSQL на одном хосте:** лимиты и параметры задаются для каждого кластера отдельно (`pg_ctlcluster <ver> <cluster> ...`).

## Вопросы на собеседованиях

1. **`Process-per-connection` vs Connection Pooling:** — Ответ: PostgreSQL создает процесс на каждое соединение. При >500 соединениях накладные расходы на контекстные переключения снижают RPS. PgBouncer transaction pooling позволяет обслуживать тысячи клиентов через 100–200 реальных процессов.
2. **Чем `idle in transaction` отличается от `idle`?** — Ответ: `idle` — подключение ожидает команды, не удерживает блокировок. `idle in transaction` — транзакция открыта, удерживает `AccessShareLock` и мешает `VACUUM`.
3. **Как защититься от Connection Storm?** — Ответ: `superuser_reserved_connections`, на PG 17+ — `reserved_connections` для служебных ролей, PgBouncer, `tcp_keepalive` с короткими интервалами, `ulimit -n`, `listen_backlog` в `postgresql.conf`.
4. **Что делает `idle_in_transaction_session_timeout`?** — Ответ: автоматически завершает сессии, зависшие в `idle in transaction`, предотвращая деградацию VACUUM и накопление Bloat.
5. **Как найти и убить блокирующий процесс?** — Ответ: `pg_blocking_pids(pid)` (рекомендуется документацией) или `pg_locks` + `pg_stat_activity` join по `pid`, затем `pg_terminate_backend(pid)`.
6. **Можно ли изменить `max_connections` без перезапуска?** — Ответ: нет, контекст `postmaster` — только restart; `pg_reload_conf()` для этого параметра недостаточен.

## См. также

- **[Оптимизация производительности](./performance_tuning.md)** — общий тюнинг PostgreSQL, полная формула памяти.
- **[Ёмкостное планирование](./capacity_planning.md)** — бюджет RAM, диска, IOPS и соединений.
- **[Настройка PgBouncer](./pgbouncer_setup.md)** — внешний пул соединений (SSoT по PgBouncer).
- **[Эксплуатация и мониторинг PgBouncer](./pgbouncer_operations.md)** — админ-консоль, метрики, failover.
- **[Наблюдаемость PostgreSQL](./observability.md)** — wait events, Prometheus-алерты, трассировка.
- **[Управление параллелизмом и блокировки](../Concepts/concurrency_and_locking.md)** — MVCC, уровни изоляции, deadlocks, `pg_blocking_pids()`.
- **[Работа через консоль (psql)](./console_basics.md)** — `pg_stat_activity`, `\watch`, типовые ошибки.
- **[Connection Pooling: общая теория](../../../Networking/Concepts/connection_pooling.md)** — TCP keepalive, conntrack, пулы на уровне nginx/HAProxy.
