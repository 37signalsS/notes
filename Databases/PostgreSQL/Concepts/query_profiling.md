# Профилирование запросов: pg_qualstats, pg_profile, pg_store_plans

**Актуально для:** PostgreSQL 14–18, pg_store_plans 1.10+

## Определения

- **`pg_qualstats`** — расширение (POWA team / Postgres Professional, пакеты PGDG), собирающее статистику по **предикатам** (WHERE/JOIN-условиям): какие колонки, операторы, константы и как часто встречаются. Источник для построения индексов по факту нагрузки, а не по догадкам.
- **`pg_profile`** — расширение (Andrei Zubkov, Postgres Professional), периодический снапшот `pg_stat_statements` + `pg_stat_kcache` + отчёты «top запросов за период» в стиле AWR/ASH. Даёт историю, которую `pg_stat_statements` (текущее состояние, сброс при перезапуске) не хранит. Генерирует отчёты в HTML-формате.
- **`pg_store_plans`** — расширение (OSSC-DB / datasentinel), сохраняющее **планы выполнения** (`EXPLAIN`) для запросов из `pg_stat_statements` по `queryid`. Позволяет видеть план исторически, без воспроизведения запроса. Поддерживает PostgreSQL 14+ (версия 1.10 добавляет поддержку PG 18).
- **`pg_idx_advisor`** — расширение для рекомендаций индексов на основе hypothetical indexes (требует `hypopg`). Использует виртуальные индексы и `EXPLAIN` для анализа влияния индекса на план.
- **`pg_qualstats_index_advisor()`** — встроенная функция `pg_qualstats`, выдающая рекомендации по индексам (включая частичные) на основе статистики предикатов.
- **`plprofiler`** — расширение для профилирования **PL/pgSQL** (строки функций, время по строкам). Описан в [Оптимизации PL/pgSQL](./pl_pgsql_optimization.md).
- **`pg_stat_statements`** — базовое расширение (ядро): статистика по запросам (вызовы, время, строки). Отправная точка; остальные расширения дополняют его. Полная конфигурация — в [Расширения PostgreSQL](./extensions_utility.md#pg_stat_statements-золотой-стандарт).
- **`auto_explain`** — встроенный модуль PostgreSQL для логирования планов медленных запросов. Не требует `CREATE EXTENSION` (модуль, а не extension); загружается через `session_preload_libraries` или `shared_preload_libraries`. Конфигурация — в [Расширения PostgreSQL](./extensions_utility.md) и [Планировщик](./planner_internals.md).

## Предпосылки

1. **PGDG-репозиторий** настроен (см. [Установку на Ubuntu](../Operations/installation_ubuntu.md) / [RHEL](../Operations/installation_rhel.md)).
2. **Права:** суперпользователь для `shared_preload_libraries` и `CREATE EXTENSION` (расширения не `trusted`).
3. **Зависимости:**
   - **pg_profile** требует `pg_stat_statements` и `pg_stat_kcache` (входит в PGDG-пакет `postgresql-18-pgstatkcache`); так же зависит от `plpgsql` и `dblink` (для распределённой конфигурации и сравнения серверов).
   - **pg_store_plans** требует `compute_query_id = on` (PG 14+); иначе `queryid` не вычисляется и расширение автоматически отключается.
   - **pg_idx_advisor** требует `hypopg` (виртуальные индексы).
4. **NTP:** синхронизация времени через chrony или systemd-timesyncd — критична для коррелирования снапшотов `pg_profile` с событиями в логах. См. [Наблюдаемость](../Operations/observability.md).
5. **logrotate:** для ротации логов `auto_explain` и `pg_store_plans.log` (если `plan_storage = file`).

## Базовые концепции

### Зачем это нужно, если есть `pg_stat_statements`

`pg_stat_statements` отвечает на «**какой** запрос медленный». Остальные расширения отвечают на:

- **pg_qualstats** — «по **каким колонкам и предикатам** фильтруют» → какие индексы нужны (через `pg_qualstats_index_advisor()`).
- **pg_profile** — «как запросы вели себя **во времени**» → история, корреляция с инцидентами, сравнение серверов (через `dblink`).
- **pg_store_plans** — «**какой план** был у запроса» → деградация плана, смена `custom`/`generic`.
- **pg_idx_advisor** — «какой **индекс** создать» → рекомендации на основе hypothetical indexes.

### Модель работы

- **pg_qualstats:** хук в исполнитель, считает предикаты в shared memory; `pg_qualstats()` — сырые данные, `pg_qualstats_pretty` — читаемый view с JOIN-ами к `pg_class`, `pg_attribute`, `pg_operator`. Требует `shared_preload_libraries = 'pg_qualstats'` (restart).
- **pg_profile:** фоновый воркер (или `take_sample()` по cron/pg_cron) пишет снапшоты в таблицы расширения; `get_report()` — HTML-отчёт. При создании снапшота вызывает `pg_stat_statements_reset()` для предотвращения потери запросов при переполнении `pg_stat_statements.max`. Зависит от `pg_stat_statements`, `pg_stat_kcache`, `dblink`.
- **pg_store_plans:** перехват `EXPLAIN` (не `EXPLAIN ANALYZE` по умолчанию), сохраняет планы по `queryid` в view `pg_store_plans`; `pg_store_plans_info` — метаданные. Требует `compute_query_id = on` (PG 14+).
- **pg_idx_advisor:** использует `hypopg` для создания виртуальных индексов и анализа их влияния на план через `EXPLAIN`.

Все — сторонние расширения (не в ядре), ставятся из PGDG (`postgresql-18-pgqualsstats`, `postgresql-18-pgprofile`, `postgresql-18-pgstoreplans`). Требуют суперпривилегий (не trusted).

## Справочник и операции

| Расширение | Функции / View | GUC-параметры | Требования |
|---|---|---|---|
| `pg_qualstats` | `pg_qualstats()` (функция), `pg_qualstats_pretty` (view), `pg_qualstats_by_query` (view), `pg_qualstats_index_advisor(min_filter, min_selectivity, forbidden_am)` | `shared_preload_libraries` | Суперпривилегии; `compute_query_id = on` для `queryid` |
| `pg_profile` | `take_sample([server])`, `get_report([server,] start_id, end_id [, ...])`, `get_report_latest([server])`, `get_report([server,] time_range tstzrange [, ...])` | Зависит от `pg_stat_statements` + `pg_stat_kcache` | `shared_preload_libraries`, `plpgsql`, `dblink` |
| `pg_store_plans` | `pg_store_plans` (view), `pg_store_plans_info` (view), `pg_store_plans_reset()`, `pg_store_plans(showtext)` | `pg_store_plans.max` (1000), `pg_store_plans.track` (top/all/none), `pg_store_plans.plan_format` (text/json/xml/yaml/raw), `pg_store_plans.plan_storage` (file/shmem), `pg_store_plans.min_duration` (0), `pg_store_plans.log_analyze` (off), `pg_store_plans.log_buffers` (off), `pg_store_plans.log_timing` (on) | `shared_preload_libraries`, `compute_query_id = on` |
| `pg_idx_advisor` | `index_advisor(query)` → таблица с `index_statements` | Требует `hypopg` | `LOAD 'pg_idx_advisor.so'` |
| `plprofiler` | `plprofiler()` — профилирование PL/pgSQL | — | `shared_preload_libraries` (см. [PL/pgSQL](./pl_pgsql_optimization.md)) |
| `auto_explain` *(модуль)* | Не требует `CREATE EXTENSION` | `auto_explain.log_min_duration`, `auto_explain.log_analyze`, `auto_explain.log_buffers`, `auto_explain.log_verbosity` | `session_preload_libraries` или `shared_preload_libraries` |

### Входные точки для профилирования

- **`EXPLAIN (ANALYZE, BUFFERS, VERBOSE)`** — встроенная команда PostgreSQL: показывает реальное время выполнения и I/O. Базовый инструмент для ручного профилирования (см. [Диагностика медленных запросов](../../../Concepts/Observability_and_Monitoring/database_observability.md)).
- **`auto_explain`** — автоматически логирует планы медленных запросов (порог `log_min_duration`). Альтернатива `pg_store_plans`, но вывод в лог, а не в view.
- **`pg_store_plans`** — сохраняет планы в `pg_store_plans` view для исторического анализа без воспроизведения запроса.

## Практические сценарии

### 1. Установка pg_qualstats

```bash
sudo apt install -y postgresql-18-pgqualsstats   # Ubuntu/Debian
# или: sudo dnf install -y pgdg18-pgqualsstats    # RHEL/Rocky/Alma
```

```bash
# postgresql.conf
shared_preload_libraries = 'pg_stat_statements,pg_qualstats'
compute_query_id = on
```

```sql
CREATE EXTENSION pg_qualstats;
-- → CREATE EXTENSION
```

### 2. Топ предикатов (по каким колонкам фильтруют)

```sql
SELECT
    left_schema || '.' || left_table AS relation,
    left_column AS column_name,
    operator AS "оператор",
    constvalue AS const_value,
    execution_count,
    nbfiltered
FROM pg_qualstats_pretty
ORDER BY execution_count DESC
LIMIT 10;
-- → relation      | column_name | operator    | const_value | execution_count | nbfiltered
-- → public.orders | status      | pg_catalog.=| 'paid'      | 152340          | 152000
-- → public.orders | created_at  | pg_catalog.>| '2026-10-01'| 98210           | 0
```

Вывод показывает: по `status = 'paid'` фильтруют 152k раз — кандидат на индекс `(status)` или частичный `WHERE status = 'paid'`.

### 3. Рекомендация частичного индекса (pg_qualstats_index_advisor)

```sql
-- Анализ pg_qualstats и вывод DDL индексов
SELECT v
FROM json_array_elements(
    pg_qualstats_index_advisor(min_filter => 100)->'indexes') v
ORDER BY v::text COLLATE "C";
-- → CREATE INDEX CONCURRENTLY idx_orders_created_at_paid
--   ON public.orders (created_at) WHERE status = 'paid'
```

Рекомендация — частичный индекс: меньше размер, выше селективность, чем полный индекс по `status`.

Для сравнения с hypothetical indexes (без создания реального индекса):

```sql
-- pg_idx_advisor + hypopg
CREATE EXTENSION hypopg;
```

```bash
# postgresql.conf
shared_preload_libraries = 'pg_idx_advisor'  # или session_preload_libraries
```

```sql
LOAD 'pg_idx_advisor.so';
-- Запустите запрос с EXPLAIN — pg_idx_advisor покажет виртуальные индексы в плане
EXPLAIN (FORMAT JSON) SELECT * FROM orders WHERE status = 'paid';
```

### 4. Установка и отчёт pg_profile

```bash
sudo apt install -y postgresql-18-pgprofile postgresql-18-pgstatkcache
```

```sql
-- pg_profile требует pg_stat_statements и pg_stat_kcache
CREATE EXTENSION pg_stat_statements;
CREATE EXTENSION pg_stat_kcache;
CREATE EXTENSION pg_profile;
```

Снапшот статистики — через `take_sample()` (вручную или по cron через `pg_cron`):

```sql
-- Снапшот вручную
SELECT take_sample();
-- → Snapshot created

-- Автоматические снапшоты — через pg_cron (см. [Вспомогательные расширения](./extensions_utility.md))
SELECT cron.schedule('pgprofile-snapshot', '*/30 * * * *',
    'SELECT take_sample()');
```

Отчёт top-10 запросов за последние сутки:

```sql
SELECT get_report(time_range => tstzrange(now() - interval '1 day', now()));
-- → HTML-отчёт с top-SQL, I/O, bloat и т.д.
```

### 5. Исторические планы (pg_store_plans)

```bash
sudo apt install -y postgresql-18-pgstoreplans
```

```sql
-- postgresql.conf
shared_preload_libraries = 'pg_store_plans'
compute_query_id = on
```

```sql
CREATE EXTENSION pg_store_plans;

-- планы для конкретного queryid из pg_stat_statements
SELECT queryid, planid, plan, calls, total_time, rows, last_call
FROM pg_store_plans
WHERE queryid = 123456789
ORDER BY last_call DESC
LIMIT 5;
-- → plan (JSON/text EXPLAIN) | calls | total_time
```

Позволяет сравнить план «сейчас» и «неделю назад» без воспроизведения запроса — ключевое при деградации после апгрейда или смены статистики.

### 6. Автоматическое логирование планов медленных запросов (auto_explain)

`auto_explain` — встроенный модуль PostgreSQL, логирует планы медленных запросов в стандартный лог. Альтернатива `pg_store_plans` (логирование в файл vs. сохранение в view).

```bash
# postgresql.conf
shared_preload_libraries = 'auto_explain'  # или session_preload_libraries для одной сессии
```

```sql
-- Динамически включить для текущей сессии
LOAD 'auto_explain';
SET auto_explain.log_min_duration = 100;  -- мс
SET auto_explain.log_analyze = true;
SET auto_explain.log_buffers = true;
```

После включения каждый запрос дольше 100ms автоматически логирует свой план с `ANALYZE` и `BUFFERS`.

## Валидация и проверка

1. **Проверка загрузки модулей:**
   ```sql
   SHOW shared_preload_libraries;
   -- → pg_stat_statements,pg_qualstats,pg_store_plans
   ```

2. **Проверка расширений:**
   ```sql
   SELECT extname, extversion FROM pg_extension
   WHERE extname IN ('pg_stat_statements', 'pg_qualstats', 'pg_profile', 'pg_store_plans');
   ```

3. **Проверка сбора предикатов (pg_qualstats):**
   ```sql
   SELECT count(*) FROM pg_qualstats_pretty;
   -- → > 0 после выполнения запросов с WHERE/JOIN
   ```

4. **Проверка снапшотов (pg_profile):**
   ```sql
   SELECT count(*) FROM profile.samples;
   -- → > 0 после take_sample()
   ```

5. **Проверка планов (pg_store_plans):**
   ```sql
   SELECT count(*) FROM pg_store_plans;
   -- → > 0 после выполнения запросов
   ```

## Мониторинг и алерты (DevOps/SRE)

### Метрики расширений

| Метрика | Источник | Что контролировать |
| :--- | :--- | :--- |
| `pg_stat_statements_info.dealloc` | `pg_stat_statements` | Рост → `max` недостаточен для нагрузки |
| `pg_store_plans` количество строк | `pg_store_plans` view | Рост → `pg_store_plans.max` подходит к пределу |
| `pg_profile` размер таблиц снапшотов | `profile.samples` | Рост → настройте retention |
| `pg_qualstats_info` переполнение | `pg_qualstats` | Рост distinct предикатов при высокой нагрузке |

### SRE-алерты

| Алерт | Метрика | Порог | Реакция |
| :--- | :--- | :--- | :--- |
| pg_qualstats OOM | `pg_qualstats_info` | Рост distinct предикатов > 10k | Отключить либо увеличить shared memory |
| pg_store_plans переполнение | `pg_store_plans` rows | >= `pg_store_plans.max` | Увеличить `pg_store_plans.max` |
| pg_profile рост | `profile.samples` size | Таблицы растут > 30 дней | Настроить retention / cron cleanup |
| pg_stat_statements переполнение | `dealloc` | `dealloc > 0` и растёт | Увеличить `pg_stat_statements.max` |
| auto_explain в прод | `log_min_duration` | < 1000ms в прод | Отключить — overhead выше, чем польза |
| pg_store_plans.log_analyze overhead | CPU | Рост CPU > 10% после включения | Отключить `log_analyze`, использовать `log_timing = off` |

### Интеграция с инструментами

- **pgBadger** — анализ логов `auto_explain`: pgbadger умеет парсить `EXPLAIN (ANALYZE)` из логов и строить отчёты с планами. См. [Анализ логов](../Operations/observability.md#анализ-логов).
- **logrotate** — ротация логов планов (если `auto_explain` или `pg_store_plans.plan_storage = file`):
  ```bash
  # /etc/logrotate.d/postgresql-plans
  /var/lib/postgresql/18/main/log/plans/*.log {
      daily
      rotate 7
      compress
      missingok
      notifempty
      copytruncate
  }
  ```

## Устранение неполадок и пограничные случаи

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `pg_stat_statements must be loaded via shared_preload_libraries` | Модуль не в `shared_preload_libraries` | Добавить в `postgresql.conf`, **перезапустить** сервер |
| `compute_query_id = off` → pg_store_plans не работает | `compute_query_id` выключен | Установить `compute_query_id = on` в `postgresql.conf` |
| pg_qualstats не собирает предикаты | Не в `shared_preload_libraries` | Добавить в `postgresql.conf`, перезапустить |
| `relation "profile.samples" does not exist` | pg_profile не создан в текущей БД | Выполнить `CREATE EXTENSION pg_profile` в целевой БД |
| `dblink` не работает в pg_profile | dblink не установлен | `shared_preload_libraries = 'pg_profile'`, установить `dblink` |
| Рост `dealloc` в `pg_stat_statements_info` | `pg_stat_statements.max` мал для нагрузки | Повысить `pg_stat_statements.max` (требует рестарта) |
| pg_store_plans потребляет много RAM | `plan_storage = shmem` и `max` высок | Использовать `plan_storage = file` или снизить `max` |
| `auto_explain.log_analyze = true` приводит к высокому CPU | `ANALYZE` добавляет overhead на каждый запрос | Включать `log_analyze` только для диагностики, не в прод |
| pg_profile сбрасывает `pg_stat_statements` при `take_sample()` | Это ожидаемо: `take_sample()` вызывает `pg_stat_statements_reset()` | Использовать достаточно частые снапшоты (15–30 мин) чтобы не потерять данные |
| pg_store_plans и transaction pooling | `queryid` стабилен, но план привязан к бэкенду | Планы могут отличаться при pooling; см. [Планировщик](./planner_internals.md) |
| pg_profile и `track_activity_query_size` | Длинные запросы обрезаются | Поднять `track_activity_query_size` (restart) для полного текста |
| pg_profile и `pg_stat_statements.track` | Если `track = top`, вложенные вызовы не считаются | Установить `pg_stat_statements.track = all` для полного покрытия (штраф на конкуренцию) |

## Лучшие практики

1. **Начинайте с `pg_stat_statements`** — он в ядре и бесплатен. `pg_qualstats`/`pg_profile` ставьте, когда нужна история или рекомендации индексов.
2. **pg_qualstats → индексы по факту**: не создавайте индексы «на всякий случай» — смотрите `execution_count` по предикатам.
3. **Частичные индексы** (рекомендации `pg_qualstats_index_advisor` или `pg_idx_advisor`) предпочтительнее полных для неравномерных распределений (например, `status = 'paid'` — 90% строк).
4. **pg_profile снапшоты каждые 15–30 мин** — компромисс между историей и overhead; храните 7–30 дней.
5. **pg_store_plans** — включайте на staging перед production: объём планов растёт с числом distinct `queryid`.
6. **Сравнивайте планы после изменений** (апгрейд, `ANALYZE`, смена `random_page_cost`) — `pg_store_plans` даёт «до/после» без воспроизведения.
7. **`auto_explain` в прод только при необходимости** — `log_analyze = true` добавляет overhead на каждый запрос; используйте `log_min_duration` для ограничения по времени.
8. **Ротируйте логи** `auto_explain` через `logrotate` (или `logging_collector`) — иначе диск быстро заполнится при высокой нагрузке.

## Очистка и откат

- **Сброс статистики:**
  ```sql
  SELECT pg_stat_statements_reset();      -- pg_stat_statements
  SELECT pg_store_plans_reset();           -- pg_store_plans
  ```
- **Отключение расширений:**
  ```sql
  DROP EXTENSION pg_store_plans;
  DROP EXTENSION pg_profile;
  DROP EXTENSION pg_qualstats;
  DROP EXTENSION hypopg;  -- если использовался pg_idx_advisor
  ```
- **Откат конфигурации:** удалить модули из `shared_preload_libraries` и **перезапустить** сервер:
  ```ini
  # postgresql.conf — до:
  shared_preload_libraries = 'pg_stat_statements,pg_qualstats,pg_profile,pg_store_plans'
  # после:
  shared_preload_libraries = 'pg_stat_statements'
  ```
- **Очистка данных pg_profile:** удалить таблицы снапшотов из схемы `profile` (DROP SCHEMA profile CASCADE) или очистить `profile.samples`.
- **`auto_explain`:** убрать из `shared_preload_libraries` / `session_preload_libraries` и перезагрузить (для `shared_preload_libraries` требуется рестарт).

## Дополнительная информация

- [Вспомогательные расширения](./extensions_utility.md) — `pg_stat_statements` конфигурация, `pg_cron`, `auto_explain`.
- [Планировщик: математика и кэш планов](./planner_internals.md) — generic/custom планы, `plan_cache_mode`, `auto_explain`.
- [Оптимизация PL/pgSQL](./pl_pgsql_optimization.md) — `plprofiler`.
- [Индексы](./indexes.md) — частичные и покрывающие индексы.
- [Наблюдаемость PostgreSQL](../Operations/observability.md) — wait events, `pg_stat_statements` top-N, SRE-алерты.
- [Наблюдаемость баз данных](../../../Concepts/Observability_and_Monitoring/database_observability.md) — диагностика медленных запросов, `EXPLAIN ANALYZE`, архитектура сигналов.
- [Оптимизация производительности](../Operations/performance_tuning.md) — настройка планировщика, bloat, VACUUM.

### Ссылки

- [PostgreSQL: pg_qualstats (документация)](https://github.com/powa-team/pg_qualstats/blob/master/doc/pg_qualstats.md)
- [PostgreSQL: pg_profile (документация)](https://github.com/zubkov-andrei/pg_profile/blob/master/doc/pg_profile.md)
- [pg_store_plans (документация)](https://ossc-db.github.io/pg_store_plans/)
- [pg_idx_advisor (GitHub)](https://github.com/cohenjo/pg_idx_advisor)
- [PostgreSQL: auto_explain](https://www.postgresql.org/docs/current/auto-explain.html)
