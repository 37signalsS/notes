# Наблюдаемость PostgreSQL (Сквозной мониторинг)

**Актуально для:** PostgreSQL 13–18 (возможности PG 14+, 17+ и 18+ помечены отдельно), pg_stat_monitor 2.3.x, pg_tracing (DataDog), OpenTelemetry Collector contrib

## Определения

**Наблюдаемость (Observability)** для базы данных — это способность понимать внутреннее состояние PostgreSQL на основе внешних данных: метрик, логов, трассировок и событий ожидания.

**Ключевые понятия:**

- **Сквозная наблюдаемость (Full-Stack Observability)** — подход, объединяющий данные БД с контекстом приложения (`trace_id`) для сквозной диагностики.
- **4 столпа Observability** — логи, метрики, трассировки и профилирование, связанные через единый `trace_id` (Observability 2.0). Подробнее — [Четыре столпа Observability](../../../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md).
- **События ожидания (Wait Events)** — причина, по которой процесс PostgreSQL в данный момент не выполняет работу: пара `wait_event_type` (категория) + `wait_event` (имя) в `pg_stat_activity`. Доступны с PG 9.6, практически без накладных расходов и включены по умолчанию; описания всех событий — в системном представлении `pg_wait_events` (PG 17+).

**Распределение тем (SSoT-соседи — чтобы не дублировать контент):**

| Тема | SSoT |
| :--- | :--- |
| Общие концепции observability (типы метрик, агрегация, процентили, глубокие dive по логам/трейсам) | [Database Observability](../../../Concepts/Observability_and_Monitoring/database_observability.md) |
| Настройка `pg_stat_statements` (`max`, `track`, `track_utility`, `queryid`, безопасность, troubleshooting) | [Расширения PostgreSQL](../Concepts/extensions_utility.md#pg_stat_statements-золотой-стандарт) |
| Управление соединениями, пулинг | [Управление соединениями](./connection_management.md) |
| Ёмкостное планирование (RAM, диск, IOPS, соединения) | [Capacity Planning](./capacity_planning.md) |
| Тюнинг (`shared_buffers`, `max_wal_size`, bloat, VACUUM) | [Оптимизация производительности](./performance_tuning.md) |
| Репликация и лаг | [Репликация](../Concepts/replication.md) |
| PII в логах и маскирование чувствительных данных | [Анонимизация и маскирование](./anonymization.md) |
| Мониторинг через Zabbix Agent 2 (нативный PostgreSQL-плагин) | [Мониторинг PostgreSQL в Zabbix](../../../Zabbix/zabbix_postgresql_monitoring.md) |
| Разбор дисковых узких мест (iostat, pgbadger, wait events на практике) | [Дисковые узкие места](../../db_disk_bottleneck_troubleshooting.md) |
| Методология SLO/SLI и инцидент-менеджмент | [SRE-концепции](../../../Concepts/sre_concepts_main.md), [Incident Management](../../../Concepts/Observability_and_Monitoring/incident_management.md) |

## Предпосылки

1. **Версия PostgreSQL:** 13+ для базовой наблюдаемости. Ключевые возможности по версиям:
    - **PG 14–17:** `compute_query_id` (queryid в `pg_stat_activity`), `pg_stat_wal`, `pg_stat_replication_slots`, `pg_stat_progress_copy`, `track_wal_io_timing` (удалён в PG 18), session-статистика в `pg_stat_database`.
    - **PG 17+:** `pg_stat_checkpointer`, `pg_stat_io`, `pg_wait_events`, `pg_stat_recovery_prefetch`.
    - **PG 18+:** `track_wal_io_timing` удалён — WAL-тайминг теперь всегда доступен в `pg_stat_io` (объект `wal`); столбцы `wal_write`/`wal_sync` и их тайминги удалены из `pg_stat_wal` (переехали в `pg_stat_io`); `pg_stat_io` отчитывается в байтах, а не страницах.
2. **Роли и права:** технический пользователь с ролью `pg_monitor` (включает `pg_read_all_settings`, `pg_read_all_stats`, `pg_stat_scan_tables`). Мониторинг — не от суперпользователя:
   ```sql
   CREATE USER monitoring_user WITH PASSWORD 'password';
   GRANT pg_monitor TO monitoring_user;
   ```
   Тексты запросов в `pg_stat_statements` и полная информация о чужих сессиях видны только суперпользователю и `pg_read_all_stats` (входит в `pg_monitor`); обычные пользователи видят только существование сессии, её пользователя и базу.
3. **Расширения:** `pg_stat_statements` — загрузка модуля через `shared_preload_libraries` (требует перезапуска сервера) + `CREATE EXTENSION` в каждой базе данных. Полная конфигурация и параметры — [Расширения PostgreSQL](../Concepts/extensions_utility.md#pg_stat_statements-золотой-стандарт).
4. **Сетевой доступ:** порт 5432 (или unix-сокет) для коллектора/экспортера; учётная запись мониторинга должна подключаться только с хоста сбора метрик.
5. **Синхронизация времени:** chrony или systemd-timesyncd на всех узлах — без неё портится корреляция по `trace_id` и измерение лага репликации.

## Основные концепции

### Проблема мониторинга PostgreSQL

Традиционный мониторинг ресурсов (CPU, RAM) часто не даёт ответа на вопрос «почему база тормозит?». Система может деградировать при низком потреблении ресурсов из-за блокировок, неоптимальных планов запросов или нехватки памяти в `shared_buffers`.

**Ключевая идея:** переход от «мониторинга состояния» к «анализу производительности» через связывание активности приложения с внутренними процессами БД с помощью сквозного идентификатора трассировки (`trace_id`).

### Ключевые области анализа

1. **События ожидания (Wait Events):** информация из `pg_stat_activity` о том, чего именно ждёт процесс (IO, Lock, CPU). Позволяет отличить проблемы диска от конкуренции за блокировки. **Важно:** события разделяются на типы: `LWLock` (внутренние защёлки), `Lock` (тяжёлые блокировки объектов), `IO` (чтение/запись), `Client` (ожидание клиента), `Timeout`, `IPC`, `Activity`, `BufferPin`, `Extension`. Подробный разбор типов — [Шпаргалка по Wait Events](#шпаргалка-по-критическим-wait-events).
2. **Активные соединения и транзакции:** мониторинг состояний сессий (`active`, `idle`, `idle in transaction`, `idle in transaction (aborted)`). Особое внимание — транзакциям, открытым дольше нескольких минут: они мешают `VACUUM` (удерживают `xmin`) и вызывают раздувание (bloat). Управление соединениями и пулинг — [Управление соединениями](./connection_management.md).
3. **Дисковый ввод-вывод (I/O) и Buffer Cache:** анализ чтений и записей, отличие «хитов» кэша (`shared_buffers`) от физических чтений. `track_io_timing = on` измеряет время каждой блоковой операции — критично для диагностики деградации хранилища. Важная ограничение: статистика PostgreSQL не различает чтение с диска и попадание в кэш ОС (page cache) — для полной картины комбинируйте `pg_statio_*` с утилитами ОС (`iostat`, `iotop`).
4. **Блокировки (Locks):** обнаружение длительных блокировок таблиц и строк. Корреляция между `pg_stat_activity` (кто ждёт) и `pg_locks` (кто держит); цепочки блокировок — через `pg_blocking_pids()`.
5. **Отставание репликации (Replication Lag):** критичный показатель для отказоустойчивых кластеров (High Availability). Отслеживается через `pg_stat_replication` (`replay_lag`, `write_lag`, `flush_lag` — на Primary) и `pg_last_xact_replay_timestamp()` (на Standby). Пороги алертов — в разделе [Алертинг и пороги](#алертинг-и-пороги-sre).
6. **Прогресс длительных операций:** семейство представлений `pg_stat_progress_*` для `VACUUM` (PG 9.6+), `ANALYZE` (PG 10+), `BASE_BACKUP` (PG 11+), `CREATE INDEX`/`CLUSTER` (PG 12+), `COPY` (PG 14+) — оценка оставшегося времени тяжёлых административных задач. `REINDEX`/`REINDEX CONCURRENTLY` и `VACUUM FULL` не имеют отдельных представлений: они отражаются в `pg_stat_progress_create_index` и `pg_stat_progress_cluster` соответственно (колонка `command` различает операции).
7. **Фоновые процессы (SRE-метрики):** `bgwriter` и `checkpointer`. В PG 17+ статистика чекпоинтера — в `pg_stat_checkpointer` (в ≤16 — в `pg_stat_bgwriter`); помогает настроить `max_wal_size` и `checkpoint_timeout`.
8. **Журналы (Logs):** сбор медленных запросов (`log_min_duration_statement`), ошибок, контрольных точек и временных файлов.
   - **Безопасность логов:** перед сбором убедитесь, что в них не попадают PII-данные. Для маскирования чувствительной информации на уровне БД используйте **[Анонимизацию и маскирование](./anonymization.md)**.

### Базовые метрики здоровья (минимальный дашборд)

До внедрения глубокой наблюдаемости (wait events, трассировка) полезен минимальный набор метрик, отвечающих на вопрос «работает ли база и не собирается ли деградировать»:

| Метрика | Источник | Тревожные признаки |
| :--- | :--- | :--- |
| **Доступность** | `SELECT 1`, `pg_up` экспортера | Недоступность инстанса |
| **Число соединений** | `pg_stat_activity` | Приближение к `max_connections` (алерт >80%); рост доли `idle`-сессий |
| **Самая долгая транзакция** | `pg_stat_activity` | Транзакции часами; долгие `idle in transaction` |
| **Блокировки** | `pg_locks` + `pg_stat_activity` | Растущая очередь ожидающих, взаимные блокировки |
| **Отставание репликации и слоты** | `pg_stat_replication`, `pg_replication_slots` | Рост lag; неактивный слот, удерживающий WAL |
| **Cache hit ratio** | `pg_stat_database` (`blks_hit`/`blks_read`) | <99% для активных данных — возможен недостаток `shared_buffers` или рост bloat |
| **Чекпоинты** | `pg_stat_checkpointer` (PG 17+) / `pg_stat_bgwriter` (≤16) | `checkpoints_req` ≈ `checkpoints_timed` — увеличить `max_wal_size` |
| **WAL-архивация** | `pg_stat_archiver` | Растёт `failed_count`, `last_failed_wal` не NULL |
| **Deadlocks** | `pg_stat_database`.`deadlocks` | Любой рост — дефект логики приложения |
| **Автовакуум** | `pg_stat_user_tables` | Растёт `n_dead_tup`, стареет `last_autovacuum` |

```sql
-- Самые долгие активные транзакции (включая idle in transaction)
SELECT now() - xact_start AS xact_duration, pid, usename, state, left(query, 80) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
ORDER BY xact_start
LIMIT 5;

-- Количество запросов, ожидающих блокировку
SELECT count(*) FROM pg_locks WHERE NOT granted;

-- Цепочки блокировок: кто кого блокирует (PG 9.6+)
SELECT blocked.pid AS blocked_pid, blocked.query AS blocked_query,
       blocking.pid AS blocking_pid, blocking.query AS blocking_query
FROM pg_stat_activity blocked
JOIN pg_locks bl ON bl.pid = blocked.pid AND NOT bl.granted
JOIN pg_locks kl ON kl.locktype = bl.locktype AND kl.relation = bl.relation
JOIN pg_stat_activity blocking ON blocking.pid = kl.pid
WHERE kl.granted;
```

Практический кейс ценности метрики «самая долгая транзакция»: процесс логической репликации открыл транзакцию и не коммитил её, ожидая недоступный внешний ресурс (сетевые таймауты). Слот репликации не продвигался, WAL начал накапливаться вплоть до заполнения диска. Мониторинг долгих транзакций и статуса слотов (`pg_replication_slots.wal_status`, `active`) обнаруживает такую ситуацию заранее. Подробнее: [Репликация](../Concepts/replication.md), [Настройка PgBouncer](./pgbouncer_setup.md).

### Шпаргалка по критическим Wait Events

Данная шпаргалка помогает быстро интерпретировать события, занимающие верхние строчки в `pg_stat_activity` или `pg_wait_sampling`. В `pg_stat_activity` событие показывается парой: `wait_event_type` (тип) + `wait_event` (имя).

| Wait Event | Тип | Описание | Причины и решение |
| :--- | :--- | :--- | :--- |
| **DataFileRead** | `IO` | Чтение страниц данных с диска в Shared Buffers. | **Причина:** промах кэша (Buffer Cache Miss) — запрос требует данных, которых нет в RAM. <br> **Решение:** проверить индексы (избегать `Seq Scan`), увеличить `shared_buffers`, оптимизировать запрос для уменьшения объёма выборки. |
| **WALInsert** | `LWLock` | Ожидание вставки записи WAL в буфер в памяти. | **Причина:** чрезмерно высокая частота мелких транзакций — процессы борются за WAL-буферы. <br> **Решение:** группировать транзакции (batching), увеличить `wal_buffers`, перенести `pg_wal` на быстрые NVMe-диски. |
| **WALWrite / WALSync** | `IO` | Запись WAL в файл / сброс WAL на durable storage. | **Причина:** медленный диск под `pg_wal` или слишком частые чекпоинты. <br>   **Решение:** включить `track_wal_io_timing = on` (PG 14–17; в PG 18 — данные уже в `pg_stat_io` без включения) для времён записи/сброса, вынести WAL на отдельный быстрый диск, увеличить `max_wal_size`. |
| **extend** | `Lock` | Ожидание тяжёлой блокировки на расширение отношения. | **Причина:** массовая параллельная вставка в одну таблицу — процессы ждут право расширить файл. <br> **Решение:** проверить нагрузку на `INSERT`, рассмотреть партиционирование таблицы, batching. |
| **DataFileExtend** | `IO` | Ожидание физического расширения файла данных на уровне ОС. | **Причина:** файловая система медленно выделяет новые блоки. <br> **Решение:** проверить настройки ФС (XFS/Ext4 с `noatime`), убедиться, что диск не перегружен фоновыми задачами. |
| **tuple / transactionid** | `Lock` | Ожидание блокировки строки / ожидание завершения другой транзакции. | **Причина:** конкуренция за обновление одной строки («горячая строка») или длинная транзакция держит `xmin`. <br> **Решение:** пересмотреть логику приложения, использовать `SKIP LOCKED` для очередей, сократить транзакции. |
| **ClientRead / ClientWrite** | `Client` | Ожидание данных от клиента / записи клиенту. | **Причина:** приложение или пулер (PgBouncer) не успевает — проблема не в БД. <br> **Решение:** смотреть на приложение, пулинг и сетевые задержки. |
| **CheckpointWriteDelay / RegisterSyncRequest** | `Timeout` | Задержка между записями при чекпоинте / переполнение очереди запросов к checkpointer. | **Причина:** слишком частые или «запрошенные» чекпоинты (`checkpoints_req` растёт). <br> **Решение:** увеличить `max_wal_size` и `checkpoint_timeout`, распределить запись (checkpoint_completion_target). |

```sql
-- Агрегация событий ожидания (снимок «сейчас»)
SELECT wait_event_type, wait_event, count(*) AS sessions,
       string_agg(pid::text, ', ') AS pids
FROM pg_stat_activity
WHERE wait_event IS NOT NULL
GROUP BY wait_event_type, wait_event
ORDER BY sessions DESC;

-- Описания событий из каталога (PG 17+): ~350 событий на стоковом сервере
SELECT a.wait_event_type, a.wait_event, w.description, count(*) AS sessions
FROM pg_stat_activity a
JOIN pg_wait_events w ON w.type = a.wait_event_type AND w.name = a.wait_event
WHERE a.wait_event IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY sessions DESC;
```

Снимок `pg_stat_activity` показывает только текущее состояние; для истории событий ожидания (профили нагрузки, Flame Graphs) используйте `pg_wait_sampling` — см. [Расширения и инструменты](#расширения-и-инструменты-для-анализа).

## Практические сценарии

### Конфигурация для глубокой наблюдаемости

Для того чтобы PostgreSQL отдавал максимум полезных данных, необходимо изменить значения по умолчанию в `postgresql.conf`:

```ini
# --- Сбор статистики ---
# Включает сбор статистики времени ввода-вывода (накладные расходы минимальны на совр. ОС)
track_io_timing = on
# PG 14–17: время записи/сброса WAL (отдельно от track_io_timing; может давать overhead — включать при диагностике WAL); в PG 18 удалён — WAL-тайминг читается из pg_stat_io
# track_wal_io_timing = on  -- PG 14-17 только
# Включает сбор статистики по вызовам функций (pl — только PL; all — включая C-функции; только для суперпривилегий)
track_functions = all
# PG 14+: вычисление queryid в pg_stat_activity (auto — только при загруженном pg_stat_statements/auto_explain)
compute_query_id = on

# --- Логирование ---
# Логировать запросы дольше 250мс (настроить под нагрузку)
log_min_duration_statement = 250ms
# Стандартный уровень детализации ошибок (verbose добавляет SQLSTATE, DETAIL, HINT, CONTEXT)
log_error_verbosity = verbose
# Логировать информацию о выполнении контрольных точек (checkpoints)
log_checkpoints = on
# Логировать действия autovacuum дольше 10с (по умолчанию -1 = выключено)
log_autovacuum_min_duration = 10s
# Логировать блокировки, если ожидание превысило deadlock_timeout
log_lock_waits = on
# Префикс лога для удобного парсинга (включает время, pid, пользователя, базу и приложение)
log_line_prefix = '%m [%p] %u@%d [%a] '
# Логировать временные файлы (помогает найти нехватку work_mem); 0 = все файлы
log_temp_files = 0
```

### Корреляция через sqlcommenter и OpenTelemetry

**sqlcommenter** — это библиотека, которая автоматически внедряет метаданные (`trace_id`, `span_id`, имя контроллера) в SQL-запросы в виде комментариев.

**Шаги настройки:**

1. **Инструментация приложения:**
   - Для Python (Django/SQLAlchemy), Java (Spring Boot), Go (GORM), .NET установите соответствующий пакет `sqlcommenter`.
   - Убедитесь, что `traceparent` (W3C Trace Context) передаётся в комментариях.
2. **Настройка PostgreSQL:**
   - В `postgresql.conf` установите `log_line_prefix`, включающий `%a` (application_name).
   - Для расширенного анализа используйте расширение `pg_tracing` (см. ниже).

```sql
-- Пример запроса, генерируемого приложением
SELECT * FROM users
WHERE id = 42
/*application='billing-service',traceparent='00-84b5-01',controller='UserController'*/;
```

**Преимущество:** в `pg_stat_activity` и `pg_stat_statements` колонка `query` теперь содержит комментарий, позволяя найти конкретный трейс, вызвавший нагрузку. Комментарии также попадают в логи — их можно извлечать при парсинге (pgbadger, Loki).

### Расширенная трассировка с pg_tracing

Расширение `pg_tracing` (DataDog) позволяет PostgreSQL выступать в роли «участника» распределённой трассировки, создавая собственные спаны на стороне сервера.

1. **Установка:** добавьте `pg_tracing` в `shared_preload_libraries` и установите `compute_query_id = on` — требуется перезапуск сервера.
2. **Генерируемые спаны:**
   - Внутренние функции: `Planner`, `ProcessUtility`, `ExecutorRun`, `ExecutorFinish`;
   - Операторы (`SELECT`, `INSERT`, …) и utility-операторы (`ALTER`, `SHOW`, `TRUNCATE`, `CALL`);
   - Узлы плана выполнения (`SeqScan`, `NestedLoop`, `HashJoin`, …) — видна стоимость каждого узла;
   - Вложенные запросы (вызовы внутри функций), триггеры (BEFORE/AFTER), parallel workers;
   - Коммит транзакции (время `fsync` изменений в WAL).
3. **Распространение контекста трейса:** через SQLCommenter-комментарий или GUC `pg_tracing.trace_context` — спаны БД автоматически коррелируют со спанами приложения.
4. **Чтение спанов:** `pg_tracing_consume_spans` / `pg_tracing_peek_spans` (записи), `pg_tracing_json_spans` (OTLP-JSON), `pg_tracing_info` / `pg_tracing_reset` (статистика расширения).
5. **Конфигурация (GUC):**

```ini
shared_preload_libraries = 'pg_tracing'
compute_query_id = on
pg_tracing.max_span = 10000        # буфер спанов в разделяемой памяти
pg_tracing.track = all
pg_tracing.otel_endpoint = 'http://127.0.0.1:4318/v1/traces'   # OTLP HTTP
pg_tracing.otel_naptime = 2000     # интервал отправки, мс
```

**Ограничения:** расширение поддерживает **только PostgreSQL 14, 15 и 16**; находится в ранней разработке и может быть нестабильным; потребляет разделяемую память пропорционально `pg_tracing.max_span` всегда, даже когда спаны не генерируются.

**Отдельный механизм — dynamic tracing:** ядро PostgreSQL поддерживает пробы DTrace/SystemTap (`query-parse-start/done`, `query-rewrite-start/done`, `query-plan-start/done`, `query-execute-start/done`, `transaction-commit/abort`) для внешних трейсеров — это не OTel-интеграция, а низкоуровневый инструмент разработчиков.

### Расширения и инструменты для анализа

| Инструмент | Назначение | Особенности |
| :--- | :--- | :--- |
| `pg_stat_statements` | Статистика всех запросов. | **Must-have**, золотой стандарт Top-SQL. Конфигурация, параметры (`max`, `track`, `track_utility`, `track_planning`, `save`) и семантика `queryid` — [Расширения PostgreSQL](../Concepts/extensions_utility.md#pg_stat_statements-золотой-стандарт). |
| `pg_stat_monitor` | Современная альтернатива `pg_stat_statements` (Percona). | PG 13+; статистика по временным **бакетам** (`pgsm_max_buckets` — число бакетов в цепочке; данные не нарастают бесконечно, как в `pg_stat_statements`), гистограммы (`pgsm_histogram_*`), планы запросов (`pgsm_enable_query_plan`), `client_ip`, нормализованные запросы. Требует `shared_preload_libraries = 'pg_stat_statements, pg_stat_monitor'` + `CREATE EXTENSION` в каждой БД; пакеты из репозиториев Percona и PGDG. |
| `auto_explain` | Логирование планов медленных запросов. | Не требует `shared_preload_libraries` (достаточно `session_preload_libraries` или `LOAD`); `auto_explain.log_min_duration`, `log_analyze`, `log_buffers`, `log_wal`. |
| `pg_stat_kcache` | Статистика ресурсов ОС. | Показывает потребление CPU (user/system) и чтение из дискового кэша ОС (Dalibo); загружается через `shared_preload_libraries`. |
| `pg_wait_sampling` | История событий ожидания. | Регулярная выборка `pg_stat_activity` — профили нагрузки (Flame Graphs) по событиям ожидания (Postgres Professional). |
| `pgbadger` | Анализ логов. | Отчёты Top-SQL, ошибок и чекпоинтов по логам PostgreSQL — см. [Анализ логов](#анализ-логов). |
| PMM / Zabbix Agent 2 | Платформы мониторинга. | PMM (Percona) — Prometheus + Grafana + QAN; Zabbix Agent 2 — нативный PostgreSQL-плагин, шаблоны и настройки — [Мониторинг PostgreSQL в Zabbix](../../../Zabbix/zabbix_postgresql_monitoring.md). |

### Сбор метрик через OpenTelemetry Collector

Для сбора метрик без отдельного `postgres_exporter` можно использовать встроенный ресивер `postgresql` в OTel Collector (contrib).

**Пример конфигурации `otel-collector.yaml`:**

```yaml
receivers:
  postgresql:
    endpoint: "postgres:5432"     # host:port; для сокетов — transport: unix
    transport: tcp                  # tcp (по умолчанию) или unix
    username: "monitoring_user"
    password: "${env:POSTGRES_PASSWORD}"
    databases:
      - "main_db"                   # пустой список — все непустые (не template) базы
    exclude_databases: []           # системные/служебные БД можно исключить явно
    collection_interval: 10s        # интервал сбора (по умолчанию 10s)
    tls:
      insecure: true                # true → sslmode=disable; false (+ insecure_skip_verify) → sslmode=require

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"

service:
  pipelines:
    metrics:
      receivers: [postgresql]
      processors: [batch]
      exporters: [prometheus]
```

**Дополнительные возможности ресивера:**

```yaml
events:
  db.server.query_sample:
    enabled: true    # выборки запросов из pg_stat_activity
  db.server.top_query:
    enabled: true    # top-N запросов; требует pg_stat_statements в каждой базе
```

- `top_query` имеет собственный интервал `collection_interval` (по умолчанию 60s).
- Метрики: `postgresql.backends`, `postgresql.connection.max`, `postgresql.database.locks`, `postgresql.bgwriter.buffers.allocated` и др.
- **Преимущество:** уменьшение количества компонентов (не нужен отдельный экспортер) и нативная интеграция в OTel-пайплайн. Эталонное развёртывание exporter + Prometheus + Grafana через Ansible — [Ansible-пример](../../../Ansible/examples/postgresql_prometheus_monitoring.md).

### Алертинг и пороги (SRE)

Пороги — отправная точка; калибруйте под свои SLO ([SRE-концепции](../../../Concepts/sre_concepts_main.md)).

| Метрика | Порог | Источник | Реакция |
| :--- | :--- | :--- | :--- |
| Доступность | `pg_up = 0` | экспортер | Немедленный инцидент |
| Соединения | >80% от `max_connections` | `pg_stat_activity` / `max_connections` | Рост пула, PgBouncer, поиск «утечки» сессий |
| Лаг репликации | >30 с (read-heavy) / >10 с (OLTP) | `pg_stat_replication`.`replay_lag` | Проверка сети/диска standby, нагрузки на primary |
| Репликационные слоты | `wal_status` = `lost`/`unreserved`; неактивный слот удерживает WAL | `pg_replication_slots` | Удалить неиспользуемый слот, иначе заполнение диска |
| Cache hit ratio | <99% для активных данных | `pg_stat_database` | Проверить `shared_buffers`, bloat, индексы |
| Чекпоинты | `checkpoints_req` ≈ `checkpoints_timed` или выше | `pg_stat_checkpointer` (PG 17+) / `pg_stat_bgwriter` | Увеличить `max_wal_size` / `checkpoint_timeout` |
| WAL-архивация | `failed_count` растёт | `pg_stat_archiver` | Проверить `archive_command`, место в архиве |
| Deadlocks | Любой рост счётчика | `pg_stat_database`.`deadlocks` | Ревью логики блокировок в приложении |
| Автовакуум | `n_dead_tup` растёт, `last_autovacuum` стареет | `pg_stat_user_tables` | Проверить autovacuum workers, bloat |
| Диск | >80% заполнения tablespace | `pg_tablespace_size()` | Расширение, очистка, архивация |

### Дополнительные представления для SRE

| Представление | Версия | Что показывает |
| :--- | :--- | :--- |
| `pg_stat_checkpointer` | PG 17+ | `checkpoints_timed`/`checkpoints_req`, `buffers_checkpoint`, `checkpoint_write_time`/`checkpoint_sync_time` (в ≤16 эти столбцы были в `pg_stat_bgwriter`) |
| `pg_stat_bgwriter` | все | `buffers_clean`, `maxwritten_clean` — работа background writer'а |
| `pg_stat_io` | PG 17+ | I/O по `backend_type`/context/объекту (включая WAL-объекты с `read_bytes`/`write_bytes`/`fsync_time`; в PG 18 заменяет удалённые WAL timing столбцы из `pg_stat_wal`) |
| `pg_aios` | PG 18+ | In-use I/O-handle'ы асинхронного I/O с состояниями (`SUBMITTED`, `COMPLETED_IO`, `COMPLETED_SHARED` и т.д.) — для тюнинга AIO; см. [Асинхронный ввод-вывод](./async_io.md) |
| `pg_stat_wal` | PG 14+ | `wal_bytes`, `wal_records`, `wal_fpi` — генерация WAL; в PG 18 удалены столбцы `wal_write`/`wal_sync` и их тайминги (переехали в `pg_stat_io`); `track_wal_io_timing` удалён в PG 18 |
| `pg_stat_archiver` | все | `archived_count`, `failed_count`, `last_archived_wal`, `last_failed_wal` |
| `pg_stat_database` | все | `xact_commit`/`xact_rollback`, `conflicts`, `deadlocks`, `temp_bytes`; session/active-время — PG 14+ |
| `pg_stat_replication_slots` | PG 14+ | `wal_status`, `safe_wal_size`, `active` — здоровье слотов |
| `pg_stat_progress_*` | 9.6–14 | Прогресс `VACUUM` (9.6+), `ANALYZE` (10+), `BASE_BACKUP` (11+), `CREATE INDEX`/`REINDEX`/`CLUSTER`/`VACUUM FULL` (12+), `COPY` (14+) |
| `pg_stat_recovery_prefetch` | PG 17+ | Эффективность recovery prefetch на standby |

```sql
-- Коэффициент попадания в кэш (цель > 99% для горячих данных)
SELECT round(sum(blks_hit) * 100.0 / nullif(sum(blks_hit) + sum(blks_read), 0), 2) AS cache_hit_ratio
FROM pg_stat_database;

-- Соотношение запрошенных и плановых чекпоинтов (PG ≤16; в PG 17+ — pg_stat_checkpointer)
SELECT checkpoints_timed, checkpoints_req, buffers_checkpoint, buffers_clean
FROM pg_stat_bgwriter;
```

### Анализ логов

- **pgbadger** — генератор отчётов по логам PostgreSQL: Top-SQL по времени/вызовам, ошибки, чекпоинты, распределение по пользователям и базам. Работает с текстовыми и CSV-логами.
- **Ротация:** встроенный `logging_collector` с `log_filename`/`log_rotation_age`/`log_rotation_size`, либо `csvlog` + `logrotate` (для `pgbadger` и SIEM удобен CSV).
- **Сэмплирование при высокой нагрузке:** `log_min_duration_sample` + `log_sample_rate` (PG 13+) — логировать только случайную долю медленных запросов вместо всех.
- **PII:** логи и трейсы могут содержать персональные данные — маскирование на уровне БД: [Анонимизация и маскирование](./anonymization.md).

## Валидация и проверка

После настройки выполните следующие шаги для проверки корректности сбора данных:

1. **Проверка работы pg_stat_statements:**
   ```sql
   SELECT query, calls, total_exec_time
   FROM pg_stat_statements
   ORDER BY total_exec_time DESC LIMIT 5;
   ```
   *Ожидаемый результат:* список запросов с ненулевыми значениями времени.

2. **Проверка попадания метаданных (sqlcommenter) в БД:**
   Запустите запрос с комментарием и проверьте его наличие в активных сессиях:
   ```sql
   SELECT pid, query
   FROM pg_stat_activity
   WHERE query LIKE '%traceparent%';
   ```

3. **Проверка логов:** убедитесь, что в лог-файлах присутствуют записи с `trace_id` и `application_name`.

4. **Проверка wait events:** агрегация из [Шпаргалки](#шпаргалка-по-критическим-wait-events) возвращает ненулевое число сессий с событиями под нагрузкой; запрос к `pg_wait_events` (PG 17+) возвращает описания, а не ошибку «отношение не существует».

5. **Проверка экспортера/коллектора:** target `/metrics` (или OTLP-эндпоинт) отдаёт метрики `postgresql_*`; в OTel Collector — отсутствие ошибок в логах и ненулевые значения `postgresql.backends`.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Пустой query_id в pg_stat_activity** | `compute_query_id` выключен или PG < 14. | Установите `compute_query_id = on` в `postgresql.conf`. |
| **Комментарии sqlcommenter обрезаются** | Слишком длинные запросы или настройки драйвера. | Проверьте параметр `track_activity_query_size` (по умолчанию 1024 байт; увеличьте, требуется SIGHUP/рестарт). |
| **Высокий CPU при мониторинге** | Слишком высокая частота `pg_wait_sampling` или `track_functions = all`. | Уменьшите частоту сэмплирования или установите `track_functions = pl`. |
| **pg_stat_statements не показывает данные** | Расширение не создано в конкретной базе. | Выполните `CREATE EXTENSION pg_stat_statements;` в каждой БД. |
| **Ошибка `pg_stat_statements must be loaded via shared_preload_libraries`** | Модуль не загружен при старте сервера. | Добавьте в `shared_preload_libraries` и **перезапустите** сервер. |
| **Нулевые `*_blk_read_time` в pg_stat_statements** | `track_io_timing = off`. | Включите `track_io_timing = on` (user context, без рестарта). |
| **Не видны тексты запросов и сессии других пользователей** | Нет прав `pg_read_all_stats`. | `GRANT pg_monitor TO monitoring_user;` (роль включает `pg_read_all_stats`). |
| **pg_tracing не загружается на PG 17/18** | Расширение поддерживает только PG 14–16. | Используйте core dynamic tracing или трассировку на стороне клиента (OTel SDK). |
| **В PG 18 «исчезли» столбцы read/sync из pg_stat_wal** | Изменение в PG 18: WAL timing перенесён в `pg_stat_io` для объекта `wal`. | `track_wal_io_timing` удалён в PG 18 — WAL-тайминг читается из `pg_stat_io` без дополнительной конфигурации. |

## Лучшие практики

1. **Сначала минимальный дашборд** (базовые метрики здоровья), затем — углубление в wait events и трассировку.
2. **Кардинальность метрик:** метки `datname`, `usename`, `application_name` допустимы; текст запроса как метку — никогда (взрыв кардинальности в TSDB).
3. **Интервал сбора 10–30 с:** слишком частый scrape нагружает БД; для top-query OTel-приёмника хватит 60 с.
4. **Мониторинг не от суперпользователя:** выделенная роль `pg_monitor`, подключение только с хоста сбора.
5. **Алерты на симптомы и SLO**, а не на каждую аномалию; пороги документируйте и калибруйте ([Incident Management](../../../Concepts/Observability_and_Monitoring/incident_management.md)).
6. **NTP на всех узлах** — иначе искажаются лаги репликации и корреляция трейсов.
7. **Сэмплирование логов** (`log_min_duration_sample`) при высокой нагрузке вместо логирования всех медленных запросов.
8. **Защита PII** в логах, трейсах и метриках — маскирование на уровне БД ([Анонимизация](./anonymization.md)).
9. **Ретеншен:** детальные метрики 13–30 дней + даунсемплинг; логи — по политике хранения с ротацией.
10. **Версионируйте дашборды и алерты** вместе с инфраструктурой (code review порогов).

## Очистка и откат

- **Сброс статистики:** `pg_stat_reset()` (текущая БД), `pg_stat_reset_shared('bgwriter' | 'checkpointer' | 'archiver' | 'io' | 'wal')` (PG 17+: `checkpointer`, `io`; `wal` — PG 14+), `pg_stat_statements_reset()`.
- **Отключение расширений:** `DROP EXTENSION pg_stat_statements;` (в каждой БД), затем удалить модуль из `shared_preload_libraries` и перезапустить сервер.
- **Откат конфигурации:** `ALTER SYSTEM RESET track_io_timing;` + `SELECT pg_reload_conf();` (для SIGHUP-параметров; для `shared_preload_libraries` требуется рестарт).
- **pg_tracing / auto_explain:** убрать из `shared_preload_libraries` / `session_preload_libraries` соответственно и перезапустить (для `pg_tracing`).

## Дополнительная информация

### Выбор инструментов

Для построения современной платформы наблюдаемости рекомендуется связка:
- **Метрики:** Prometheus / VictoriaMetrics.
- **Логи:** Grafana Loki (с извлечением меток из логов PG).
- **Трейсы:** Grafana Tempo.
- **Коллектор:** Grafana Alloy (поддерживает нативный сбор метрик и логов PostgreSQL).

### Связанные документы

- [Управление соединениями PostgreSQL](./connection_management.md) — `pg_stat_activity`, таймауты, troubleshooting и capacity planning.
- [Оптимизация производительности](./performance_tuning.md) — детальный разбор `pg_stat_statements`, планов запросов, bloat и VACUUM.
- [Расширения PostgreSQL](../Concepts/extensions_utility.md) — полный разбор `pg_stat_statements` и механизма расширений.
- [Репликация](../Concepts/replication.md) — лаг, слоты, мониторинг кластеров.
- [Анонимизация и маскирование](./anonymization.md) — защита PII в логах и при выгрузках.
- [PostgreSQL в Kubernetes](./kubernetes_deployment.md) — особенности мониторинга в Kubernetes.
- [Четыре столпа Observability](../../../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md) и [Database Observability](../../../Concepts/Observability_and_Monitoring/database_observability.md) — общая теория наблюдаемости.
- [OpenTelemetry Overview](../../../OpenTelemetry/opentelemetry_overview.md) — основы распределённой трассировки.
- [Grafana Alloy Overview](../../../Grafana/grafana_alloy_overview.md) — конфигурация агента для сбора сигналов.
- [Мониторинг PostgreSQL в Zabbix](../../../Zabbix/zabbix_postgresql_monitoring.md) — нативный плагин Zabbix Agent 2.
- [Ansible-пример: Prometheus + PostgreSQL](../../../Ansible/examples/postgresql_prometheus_monitoring.md) — эталонное развёртывание экспортера.
- [Дисковые узкие места](../../db_disk_bottleneck_troubleshooting.md) — практика диагностики I/O.

### Ссылки

- [PostgreSQL: The Cumulative Statistics System (официальная документация)](https://www.postgresql.org/docs/current/monitoring-stats.html)
- [pg_wait_events (системное представление)](https://www.postgresql.org/docs/current/view-pg-wait-events.html)
- [pg_tracing (DataDog, GitHub)](https://github.com/DataDog/pg_tracing)
- [pg_stat_monitor (документация Percona)](https://docs.percona.com/pg-stat-monitor/)
- [OTel Collector: postgresql receiver (README)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/postgresqlreceiver)
