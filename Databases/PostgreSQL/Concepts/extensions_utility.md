# Вспомогательные расширения PostgreSQL

**Актуально для:** PostgreSQL 13–18 (механизм trusted extensions — с PG 13; различия между версиями помечены явно)

## Определения

- **Расширение (Extension)** — программный модуль, дополняющий PostgreSQL новыми типами данных, функциями, операторами или индексами. Состоит из управляющего файла `<name>.control`, SQL-скрипта установки и опционально разделяемой библиотеки (`.so`). Объекты регистрируются в системном каталоге `pg_extension` текущей базы данных.
- **Trusted Extension** — расширение, помеченное в `.control`-файле как безопасное (механизм — с PG 13). Установить его может любой пользователь с правом `CREATE` в текущей базе данных, без суперпривилегий. Принцип отбора: trusted-расширение не предоставляет доступа к функциональности вне базы данных. В стандартной поставке trusted: `btree_gin`, `btree_gist`, `citext`, `cube`, `dict_int`, `fuzzystrmatch`, `hstore`, `intarray`, `isn`, `lo`, `ltree`, `pgcrypto`, `pg_trgm`, `seg`, `tablefunc`, `tcn`, `tsm_system_rows`, `tsm_system_time`, `unaccent`, `uuid-ossp`. Всё остальное (`pg_stat_statements`, `pg_cron`, `pgaudit`, `amcheck`, `pageinspect`, `pg_repack`, `postgis` и др.) требует суперпривилегий.
- **Shared Preload Libraries** — модули, загружаемые в оперативную память при старте сервера (`shared_preload_libraries` в `postgresql.conf`). Без этой настройки расширение может не работать или работать не полностью (например, `pg_stat_statements`, `pg_cron`, `pgaudit`). Изменение списка требует перезапуска сервера.
- **Contrib-модули** — дополнительные модули, поставляемые вместе с PostgreSQL отдельными пакетами (типично `postgresql<version>-contrib`). Каталог `pg_available_extensions` отражает только то, что физически присутствует в `SHAREDIR/extension`, поэтому контроль доступных расширений на практике сводится к управлению пакетами на уровне ОС.

## Механика и управление

### Как работает CREATE EXTENSION
При выполнении `CREATE EXTENSION` PostgreSQL:
1. Находит файл `<name>.control` в каталоге `SHAREDIR/extension` (путь: `pg_config --sharedir`).
2. Выполняет SQL-скрипт из этого же каталога.
3. Регистрирует объекты расширения в системном каталоге `pg_extension`.

Особенности установки:
- Расширение устанавливается **в одну базу данных** — `CREATE EXTENSION` нужно выполнить в каждой базе, где оно требуется. Выполнение в `template1` копирует расширение во все создаваемые впоследствии базы.
- По умолчанию объекты создаются в текущей целевой схеме (по умолчанию `public`). Схему можно выбрать явно: `CREATE EXTENSION <name> SCHEMA <schema>`.
- `CREATE EXTENSION IF NOT EXISTS` идемпотентен — удобен для автоматизации.
- `CASCADE` автоматически установит расширения из поля `requires` (зависимости).

### Установка на уровне ОС (sysadmin)
1. Установить пакет расширения (например, `postgresql16-contrib` в RHEL/Alma; в Debian/Ubuntu contrib-модули входят в основной пакет `postgresql-16`).
2. Убедиться, что файлы появились: `ls $(pg_config --sharedir)/extension/ | grep <name>`.
3. Выполнить `CREATE EXTENSION` в целевой базе от имени суперпривилегированной роли (если расширение не trusted).

### Версионирование и обновление
Расширения имеют собственные версии, независимые от версии PostgreSQL.
- **Доступные версии**: `SELECT * FROM pg_available_extension_versions;` — столбцы `version`, `installed`, `superuser`, `trusted`, `relocatable`, `schema`, `requires`.
- **Обновление**: `ALTER EXTENSION <name> UPDATE [TO '<new_version>'];` — только повышение версии; понижение не поддерживается.
- **Нет пути обновления**: ошибка `extension "X" has no update path from version "a" to "b"` — либо запрошено понижение, либо промежуточный скрипт обновления отсутствует в системе.
- **Бинарники ≠ база**: обновление пакета на диске не меняет логику в базе данных — после апгрейда пакетов нужно выполнить `ALTER EXTENSION ... UPDATE` (см. сценарий 5).
- **Конфигурационные таблицы**: расширения, хранящие пользовательские данные в своих таблицах, должны вызвать `pg_extension_config_dump('<table>', '<condition>')`, иначе `pg_dump` не сохранит их содержимое.

### Перемещение и удаление
- `ALTER EXTENSION <name> SET SCHEMA <schema>` — только если расширение `relocatable` (см. `pg_available_extension_versions.relocatable`).
- `DROP EXTENSION [IF EXISTS] <name> [CASCADE]` — `CASCADE` удалит все зависимые объекты, включая столбцы типов расширения.

### Права и безопасность
- **Установка**: суперпривилегии, кроме trusted-расширений (достаточно права `CREATE` в базе).
- **Выполнение функций**: отзывайте `EXECUTE` у `PUBLIC` для чувствительных функций (например, `pg_read_file` из `adminpack`).
- **Чтение текстов запросов** в `pg_stat_statements`: только суперпривилегии и роль `pg_read_all_stats`.

## Основные расширения

### Мониторинг и диагностика

#### pg_stat_statements (Золотой стандарт)
Фиксирует статистику планирования и выполнения всех SQL-инструкций сервера (по всем базам): время, строки, буферы, I/O, WAL, JIT, parallel workers.
- **Зачем:** выявление «тяжёлых» запросов и планирование оптимизации; основа для Top-SQL отчётов.
- **Конфигурация** (`postgresql.conf`, требуется рестарт; вычисление `queryid` включается при `compute_query_id = auto/on`):

```ini
shared_preload_libraries = 'pg_stat_statements'
compute_query_id = on
pg_stat_statements.max = 10000
pg_stat_statements.track = all
```

- **Параметры**:

| Параметр | Default | Описание |
|---|---|---|
| `pg_stat_statements.max` | 5000 | Максимум отслеживаемых инструкций; только при старте сервера. Разделяемая память пропорциональна `max` и потребляется всегда, даже при `track = none` |
| `pg_stat_statements.track` | `top` | `top` — только клиентские инструкции; `all` — включая вложенные (вызовы внутри функций); `none` — выключить. Менять может только суперпривилегия |
| `pg_stat_statements.track_utility` | `on` | Учитывать utility-команды (всё, кроме SELECT/INSERT/UPDATE/DELETE; в PG 18+ также MERGE). Только суперпривилегия |
| `pg_stat_statements.track_planning` | `off` | Считать время планирования; заметный штраф при множестве конкурентных соединений с одинаковыми запросами. Только суперпривилегия |
| `pg_stat_statements.save` | `on` | Сохранять статистику между выключениями сервера; задаётся только в `postgresql.conf` или командной строке |

- **Виды и функции**: `pg_stat_statements` (строка на комбинацию `userid`/`dbid`/`queryid`/`toplevel`), `pg_stat_statements_info` (`dealloc` — сколько раз записи вытеснялись из-за переполнения `max`; `stats_reset`). `pg_stat_statements_reset([userid, dbid, queryid, minmax_only])` — сброс статистики; сигнатура с `minmax_only` и возвратом `timestamptz` — с PG 17, в 13–16 — трёхаргументная, возвращает `void`.
- **Безопасность**: текст запроса и `queryid` других пользователей видны только суперпривилегиям и `pg_read_all_stats`; остальные видят статистику, если расширение установлено в их базе.
- **queryid**: хэш пост-анализного дерева запроса. Стабилен между минорными версиями при совпадении архитектуры и метаданных каталога; **не гарантирован стабильным между мажорными версиями**. Различается при пересоздании функции/таблицы и при разном `search_path`; возможны коллизии хэшей; список констант схлопывается до одного элемента с комментарием `/*, ... */`.
- **Тексты запросов** хранятся во внешнем файле, не в разделяемой памяти. При чрезмерном росте файла сервер может отбросить тексты — столбец `query` станет `NULL` при сохранении статистики по `queryid`; лечится снижением `pg_stat_statements.max`.
- **`plans` ≠ `calls`**: статистика обновляется в конце соответствующей фазы и только при успехе — успешное планирование с ошибкой на этапе выполнения увеличивает только `plans`; кэшированный план — только `calls`.
- Смежное: [Планировщик](./planner_internals.md), [Хранимые объекты](./stored_objects_debugging.md).

#### auto_explain
Автоматическое логирование планов медленных запросов. Это **не** extension (не требует `CREATE EXTENSION`), а модуль, загружаемый через `shared_preload_libraries`. Детали: [Планировщик](./planner_internals.md).

#### pg_buffercache / pg_prewarm
- `pg_buffercache` — просмотр содержимого shared buffers (какие таблицы и страницы в кэше).
- `pg_prewarm` — прогрев буферов после рестарта: `SELECT pg_prewarm('big_table');`.

### Аудит безопасности

#### pgaudit
Детальное протоколирование действий пользователей для соответствия требованиям (PCI DSS, SOC 2) и расследования инцидентов.
- **Загрузка**: требуется `shared_preload_libraries = 'pgaudit'` (без этого — ошибка при загрузке, аудит не работает) и `CREATE EXTENSION pgaudit` (устанавливает event triggers, дающие в логе тип и имя объекта для DDL).
- **Классы** (`pgaudit.log`, default `none`): `READ` (SELECT/COPY из relations), `WRITE` (INSERT/UPDATE/DELETE/TRUNCATE/COPY в relations), `FUNCTION` (вызовы функций и DO-блоки), `ROLE` (GRANT/REVOKE/CREATE/ALTER/DROP ROLE), `DDL` (остальной DDL), `MISC` (DISCARD, FETCH, CHECKPOINT, VACUUM, SET), `MISC_SET` (SET ROLE и т.п.), `ALL`. Список через запятую, вычитание через `-`: `'all, -misc'`.
- **Дополнительные параметры**: `pgaudit.log_catalog` (default `on` — шум от psql/pgAdmin; отключайте), `pgaudit.log_client` (`off`), `pgaudit.log_parameter` (`off` — параметры в CSV), `pgaudit.log_relation` (`off` — отдельная запись на каждый объект), `pgaudit.log_statement_once` (`off`), `pgaudit.role` (master-роль для object audit).
- **Два режима**: session audit (все инструкции бэкенда, управляется `pgaudit.log`) и object audit (логируются операции над объектами, на которые у `pgaudit.role` есть права на выполняемую команду).
- **Область действия**: `postgresql.conf`/`ALTER SYSTEM`, `ALTER DATABASE`, `ALTER ROLE`; менять может только суперпривилегия. Настройки **не наследуются** через role inheritance, и `SET ROLE` их не меняет.

```sql
-- Enable audit of DDL and write operations in current session
SET pgaudit.log = 'write, ddl';
SET pgaudit.log_relation = on;
```

### Целостность данных

#### amcheck / pageinspect
- `amcheck` — логическая проверка структур B-Tree и связей индексов с таблицами, например `SELECT bt_index_parent_check('idx_name', true);`.
- `pageinspect` — низкоуровневый разбор страниц (заголовки, отдельные записи/items).
- Детальные сценарии диагностики и спасения данных: [Corruption Recovery](./corruption_recovery.md).

### Автоматизация и обслуживание

#### pg_cron (Планировщик задач)
Запускает SQL-команды по расписанию прямо внутри БД как background worker (аналог `cron`).
- **Зачем:** регулярная очистка логов, обновление материализованных представлений, сбор кастомной статистики — без внешнего планировщика.
- **Конфигурация** (`postgresql.conf`, требуется рестарт):

```ini
shared_preload_libraries = 'pg_cron'
cron.database_name = 'postgres'
cron.timezone = 'GMT'
```

- **Особенности**: метаданные (`cron.job`) живут в одной базе на кластер (`cron.database_name`, default `postgres`); для задач в других базах — `cron.schedule_in_database()` (с версии 1.4); расписание — стандартный 5-плевой cron, плюс интервалы вида `'30 seconds'` и `$` для последнего дня месяца; время трактуется по `cron.timezone` (default GMT).
- **Функции**: `cron.schedule(schedule, command)` и `cron.schedule(job_name, schedule, command)` → `jobid`; `cron.unschedule(job_id)` → bool; `cron.alter_job(...)`.
- **Права**: `GRANT USAGE ON SCHEMA cron TO <role>`; политика RLS на `cron.job` — каждый видит и меняет только свои задачи (кроме superuser/bypassrls).
- **HA**: на hot standby задачи не выполняются, автоматически стартуют после повышения (promotion). Параметр `cron.enable_superuser_jobs` (default `on`); фондовых воркеров по умолчанию 8 — при большом числе задач повышайте `max_worker_processes`.

#### pg_repack (Онлайн-очистка)
Перестраивает таблицы и индексы без длинной эксклюзивной блокировки (`ACCESS EXCLUSIVE`).
- **Зачем:** устранение раздувания (Bloat) на «живых» нагруженных системах, где `VACUUM FULL` невозможен.
- Требования (PK/UNIQUE NOT NULL-индекс, ~2× места), уровни блокировок и альтернативы: [Performance Tuning](../Operations/performance_tuning.md), [Schema Migrations](./schema_migrations.md).

### Специализированные типы и поиск

#### postgis (Геоданные)
Превращает PostgreSQL в полноценную пространственную БД: координаты, карты, сложная геометрия.

#### citext, unaccent, pg_trgm
- `citext`: регистронезависимый текст (удобно для Email).
- `unaccent`: удаление диакритики (ё→е, é→e) для нормализации поиска.
- `pg_trgm`: триграммный поиск и индексы GIN/GiST.
- Сценарии: [Полнотекстовый поиск](./full_text_search.md).

#### Часто используемые contrib-типы
- `hstore`, `ltree`, `cube`, `seg`, `intarray`, `isn`, `dict_int`, `fuzzystrmatch`, `tablefunc`, `tcn`, `tsm_system_rows`/`tsm_system_time` (TABLESAMPLE), `btree_gist`/`btree_gin`, `lo` (large objects).
- `uuid-ossp` — генерация UUID; с PG 13 для `gen_random_uuid()` расширение не требуется (функция в ядре).
- Временные ряды: [TimescaleDB](../../timescaledb.md); распределённые запросы: Citus — [Scaling](./scaling.md).

## Практические сценарии

### 1. Безопасная установка в отдельную схему
Изолируйте расширения от бизнес-таблиц для предотвращения конфликтов имён.

```sql
-- Create dedicated schema
CREATE SCHEMA IF NOT EXISTS extensions;

-- Install (objects will be created in this schema)
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA extensions;

-- Set search path for application role
ALTER ROLE app_user SET search_path TO public, extensions;
```

```text
-- → CREATE SCHEMA
-- → CREATE EXTENSION
-- → ALTER ROLE
```

### 2. Инвентаризация расширений
Разница между доступными и установленными расширениями:

```sql
-- Installed extensions with versions and target schema
SELECT e.extname, e.extversion, n.nspname AS schema
FROM pg_extension e
JOIN pg_namespace n ON n.oid = e.extnamespace
ORDER BY 1;
```

```text
-- →  extname  | extversion |  schema
-- → ------------+------------+------------
-- →  plpgsql   | 1.0        | pg_catalog
-- → (1 row)
```

```sql
-- Which extensions require superuser (trusted = false)?
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE installed_version IS NOT NULL;
```

### 3. Анализ "тяжелых" запросов по I/O
После включения `pg_stat_statements` и `track_io_timing = on` (без `track_io_timing` столбцы времени I/O равны нулю):

```sql
-- PostgreSQL 17+; in 13-16 use blk_read_time/blk_write_time
-- (temp_blk_read_time/temp_blk_write_time доступны с PG 15)
SELECT
    query,
    calls,
    round(total_exec_time::numeric, 2) AS total_ms,
    round((shared_blk_read_time + shared_blk_write_time)::numeric, 2) AS io_ms
FROM pg_stat_statements
ORDER BY io_ms DESC
LIMIT 10;
```

### 4. Планирование задач через pg_cron
Автоматическое обновление статистики каждую ночь в 03:00 (время по `cron.timezone`):

```sql
-- Create named job, returns jobid
SELECT cron.schedule('daily-analyze', '0 3 * * *', 'ANALYZE my_large_table');

-- Verify the job
SELECT jobid, schedule, command, database, username FROM cron.job;

-- Remove by jobid
SELECT cron.unschedule(42);
```

```text
-- →  jobid | schedule |       command       | database | username
-- → -------+----------+---------------------+----------+----------
-- →     42 | 0 3 * * * | ANALYZE my_large_table | postgres | postgres
```

### 5. Обновление расширений после апгрейда пакетов
После обновления пакетов PostgreSQL на сервере сгенерируйте инструкции для расширений, чья установленная версия не совпадает с `default_version`:

```sql
-- Generate upgrade statements for outdated extensions
SELECT format('ALTER EXTENSION %I UPDATE;', name)
FROM pg_available_extensions
WHERE installed_version IS NOT NULL
  AND installed_version <> default_version;
```

```text
-- →                 format
-- → ------------------------------------------
-- →  ALTER EXTENSION pg_stat_statements UPDATE;
-- → (1 row)
```

> **Важно:** скрипты обновления расширений могут быть необратимыми — сначала прогоните на staging и сделайте backup перед выполнением на проде.

## Диагностика и Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| `could not open extension control file ".../<name>.control"` | Расширение не установлено на уровне ОС | Установить пакет (например, `postgresql16-contrib`), проверить `pg_config --sharedir` |
| Расширения нет в `pg_available_extensions` | Файлы `.control` вне `SHAREDIR/extension` | Переустановить пакет расширения |
| `permission denied to create extension` | Расширение не trusted | Выполнить `CREATE EXTENSION` от суперпривилегированной роли |
| `extension "X" has no update path from version "a" to "b"` | Запрошено понижение или нет промежуточного скрипта | Обновлять пошагово через версии из `pg_available_extension_versions` |
| `pg_stat_statements must be loaded via shared_preload_libraries` | Модуль не в `shared_preload_libraries` | Добавить в `postgresql.conf` и **перезапустить** сервер |
| `can only create extension in database "postgres"` (pg_cron) | `CREATE EXTENSION` выполнен не в `cron.database_name` | Выполнить в настроенной базе |
| pgaudit не логирует | Не в `shared_preload_libraries` (ошибка при загрузке) или `pgaudit.log` не задан (default `none`) | Загрузить библиотеку, задать классы, проверить `pgaudit.log_catalog` |
| Объекты расширения не видны в запросах | Расширение установлено в другую схему, не входящую в `search_path` | `ALTER ROLE ... SET search_path` или квалифицировать имена явно |
| `DROP EXTENSION` падает с ошибкой зависимостей | Есть зависимые объекты | Оценить `CASCADE` (удалит и столбцы типов расширения) или удалить зависимости вручную |
| `query` = `NULL` при сохранённой статистике | Сервер отбросил тексты из-за роста внешнего файла | Снизить `pg_stat_statements.max` |
| Растёт `pg_stat_statements_info.dealloc` | `max` мал для нагрузки | Повысить `pg_stat_statements.max` (требует рестарта) |

## Лучшие практики (Security & Ops)

1. **Принцип минимизации**: каждое расширение — потенциальная уязвимость и нагрузка на память. Удаляйте неиспользуемые.
2. **Схемная изоляция**: никогда не ставьте расширения в `public` в многопользовательских базах.
3. **Ограничение прав**: отзывайте `EXECUTE` у `PUBLIC` для функций чувствительных расширений (например, `pg_read_file` из `adminpack`).
4. **Мониторинг ресурсов**: расширения из `shared_preload_libraries` потребляют разделяемую память. Закладывайте это при расчёте `shared_buffers` и RAM.
5. **Обновления**: тестируйте `ALTER EXTENSION UPDATE` на staging перед продом; SQL-скрипты расширений могут быть необратимыми.
6. **Наблюдаемость**: следите за `pg_stat_statements_info.dealloc` — рост означает, что `pg_stat_statements.max` не хватает для нагрузки.
7. **Идемпотентность в автоматизации**: используйте `IF NOT EXISTS` и версионируйте набор расширений в миграциях (см. [Schema Migrations](./schema_migrations.md)).

## Дополнительная информация

### Смежные темы
- Индексы: **[Индексы в PostgreSQL](./indexes.md)** — GIN и GiST, используемые расширениями.
- Поиск: **[Полнотекстовый поиск](./full_text_search.md)** — использование `pg_trgm` и `unaccent`.
- Целостность: **[Corruption Recovery](./corruption_recovery.md)** — `amcheck` и `pageinspect` в сценариях спасения данных.
- Криптография: **[pgcrypto](./pgcrypto.md)** — глубокий разбор безопасности.
- Планировщик: **[Planner Internals](./planner_internals.md)** — `auto_explain` и анализ планов.
- Хранимые объекты: **[Stored Objects Debugging](./stored_objects_debugging.md)** — `pg_stat_statements` для процедур.
- Наблюдаемость: **[Observability](../Operations/observability.md)** — роль расширений в мониторинге.
- Производительность: **[Performance Tuning](../Operations/performance_tuning.md)** — `pg_repack` и борьба с bloat.
- Установка на ОС: **[Installation Ubuntu](../Operations/installation_ubuntu.md)** — пакеты и пути.
