# Параллельная репликация (Multi-Threaded Slave/MTS)

**Актуально для:** MySQL 5.6 / 5.7 / 8.0 / 8.4 LTS

## Определения

**MTS (Multi-Threaded Slave / Multi-Threaded Replica)** — режим репликации, при котором транзакции на реплике применяет не один SQL-поток, а координатор (coordinator) и несколько рабочих потоков (workers / applier threads). В MySQL 8.0.26+ терминология изменена: переменные `slave_*` переименованы в `replica_*`, «multithreaded slave» → «multithreaded applier» (MTA).

**Координатор (Coordinator)** — поток, который последовательно читает Relay Log, определяет зависимости между транзакциями и распределяет их по очередям воркеров. Появляется только при `replica_parallel_workers > 0`.

**Worker (applier thread)** — поток, выполняющий назначенные ему транзакции. При `replica_parallel_workers = 0` работает один applier-поток без координатора, а `replica_parallel_type` и `replica_preserve_commit_order` игнорируются.

**Dependency tracking** — механизм, которым источник помечает в binlog независимость транзакций. Определяет, что можно применять параллельно.

**Logical clock** — метки `last_committed` и `sequence_number`, которые источник записывает в binlog при group commit: транзакции одной группы коммита могут применяться параллельно.

**Write-set** — хеши (XXHASH64) уникальных ключей всех изменённых строк транзакции; уточняют зависимости сверху logical clock: две транзакции независимы, если их write-set не пересекаются.

## Базовые концепции

### Как устроен MTS

Цепочка потоков: receiver (I/O) записывает Relay Log → coordinator последовательно читает его, группирует транзакции по зависимостям и раскладывает по очередям воркеров → каждый воркер применяет свои транзакции в InnoDB. Порядок групп соблюдается всегда; внутри группы транзакции могут коммититься в любом порядке (если не включён `replica_preserve_commit_order`).

MTS ускоряет только **SQL-лаг** (применение). IO-лаг (сеть, получение событий) он не влияет — см. `lag_monitoring.md`.

### Типы параллелизма (replica_parallel_type)

| Значение | Как группирует транзакции | Когда применять |
| :--- | :--- | :--- |
| `DATABASE` | Параллельно — транзакции разных схем; одной схемы — последовательно | MySQL 5.6+; только если нагрузка равномерно распределена по многим БД; NDB Cluster не поддерживает |
| `LOGICAL_CLOCK` | Параллельно — транзакции одной группы коммита на источнике (логические часы); уточняется write-set при `binlog_transaction_dependency_tracking=WRITESET` | **Рекомендуется** (5.7.2+; дефолт с 8.0.27) |

### Как MTS обеспечивает корректность

- Зависимые транзакции (одни строки/индексы; при `WRITESET_SESSION` — ещё и одной сессии) попадают в одну группу и не применяются одновременно — видимый эффект совпадает с однопоточным применением.
- `replica_preserve_commit_order = ON` дополнительно гарантирует, что транзакции коммитятся на реплике в том же порядке, что и на источнике. Важно для приложений, чувствительных к commit order; при конкуренции воркеров может немного увеличивать лаг (цена порядка коммитов).
- DDL и очень большие транзакции не распределяются по воркерам — применяются последовательно и блокируют очередь координатора (детали — `master_slave_mechanism.md`, «Очень большие транзакции (> 1 ГБ) и MTS»).

### Значения по умолчанию (ключевые отличия между версиями)

| Версия | `replica_parallel_workers` | `replica_parallel_type` | `replica_preserve_commit_order` |
| :--- | :--- | :--- | :--- |
| 5.6 | 0 (однопоточно) | режим единственный — `DATABASE` | нет |
| 5.7.2 – 8.0.26 | 0 (однопоточно, координатора нет) | `DATABASE` | `OFF` |
| 8.0.27 – 8.0.x | **4** (MTS включён по умолчанию) | `LOGICAL_CLOCK` | `ON` |
| 8.4 LTS | **4** | `LOGICAL_CLOCK` | `ON` |

- Макс. число воркеров — 1024.
- С 8.0.30 значение `replica_parallel_workers = 0` deprecated (предупреждение); для однопоточного применения используйте `1`.
- Имена переменных: до 8.0.26 — `slave_parallel_workers` / `slave_parallel_type` / `slave_preserve_commit_order`; с 8.0.26 — `replica_*` (старые — deprecated-алиасы).

## Приусловия

- Версия: `DATABASE` — MySQL 5.6+; `LOGICAL_CLOCK` — 5.7.2+.
- На источнике включён binlog: для `LOGICAL_CLOCK` обязателен — именно в binlog записываются метки logical clock (в 8.0+ binlog включён по умолчанию).
- `binlog_format = ROW` для полноценного write-set dependency tracking: при STATEMENT write-set не вычисляется, работает fallback на `COMMIT_ORDER`.
- Performance Schema включён — иначе временные метки транзакций не собираются (колонки таймингов в P_S-таблицах = 0).
- Привилегии: `REPLICATION_SLAVE_ADMIN` (`START`/`STOP REPLICA`), `REPLICATION_CLIENT` (`SHOW REPLICA STATUS`).
- Crash-safety: `relay_log_info_repository = TABLE` (дефолт в 8.0; переменная удалена в 8.3), `sync_relay_log = 1` особенно важен для MTS, `relay_log_recovery = ON` (детали — раздел 7).
- Multi-source: число воркеров задаётся глобально; **каждый канал получает указанное число applier-потоков и собственный координатор** — настроить воркеров по каналам нельзя. Учитывайте умножение числа потоков на число каналов.

## Практический блок

### 1. Проверка текущей конфигурации

```sql
-- Активен ли MTS и в каком режиме
SHOW GLOBAL VARIABLES WHERE Variable_name IN
  ('replica_parallel_workers','replica_parallel_type','replica_preserve_commit_order');
-- → replica_parallel_workers > 0 ⇒ MTS включён; 0 (до 8.0.29) или 1 — однопоточный applier

-- Потоки репликации: 1 receiver + (при MTS) 1 coordinator + N workers
SELECT ID, USER, COMMAND, TIME, STATE
FROM information_schema.PROCESSLIST
WHERE USER = 'system user';
-- → воркеры в состоянии «Waiting for an event from Coordinator»

SHOW REPLICA STATUS\G
-- → Replica_SQL_Running: Yes; Seconds_Behind_Source — интерпретация в lag_monitoring.md
--   (SBM не показывает параллелизм: лаг может быть и при полностью idle воркерах)
```

### 2. Включение и настройка MTS

`my.cnf` на реплике:

```ini
[mysqld]
# Режим группировки (рекомендуется)
replica_parallel_type = LOGICAL_CLOCK

# Число воркеров: начать с 4, повысить до числа ядер CPU (раздел 4)
replica_parallel_workers = 8

# Сохранять порядок коммитов источника (требует LOGICAL_CLOCK)
replica_preserve_commit_order = ON
```

Изменение без перезапуска сервера (требуется остановка applier; receiver продолжает работать, Relay Log копится):

```sql
STOP REPLICA SQL_THREAD;
SET GLOBAL replica_parallel_type = 'LOGICAL_CLOCK';
SET GLOBAL replica_parallel_workers = 8;
SET GLOBAL replica_preserve_commit_order = ON;
START REPLICA SQL_THREAD;
```

Ограничения:
- `replica_preserve_commit_order = ON` требует `replica_parallel_type = LOGICAL_CLOCK` (во всех версиях).
- До 8.0.18 для `preserve_commit_order` требовались включённые `log_bin` и `log_replica_updates` на реплике; с 8.0.19 — не требуются.
- Смена `replica_parallel_type` / `replica_parallel_workers` вступает в силу только после перезапуска applier-потоков.

### 3. Dependency tracking на источнике (MySQL 5.7.22 – 8.2)

`LOGICAL_CLOCK` группирует по времени коммита. Точнее распараллеливает write-set tracking: источник вычисляет хеши уникальных ключей изменённых строк и помечает независимые транзакции:

```ini
# Источник, MySQL 5.7.22 – 8.2
binlog_transaction_dependency_tracking = WRITESET   # COMMIT_ORDER | WRITESET | WRITESET_SESSION
transaction_write_set_extraction = XXHASH64         # обязательно ≠ OFF; дефолт в 8.0+
```

- `COMMIT_ORDER` (дефолт 5.7.22–8.0.x): независимы транзакции с перекрывающимися окнами коммита.
- `WRITESET`: дополнительно независимы транзакции с непересекающимися write-set. Для транзакций с пустым или частичным write-set (таблицы без PK/UK, FK-родители) применяется `COMMIT_ORDER`.
- `WRITESET_SESSION`: дополнительно зависимы транзакции, зафиксированные в одной сессии.
- Дефолт `WRITESET` с 8.2.0 (переменная объявлена deprecated). **В 8.4.0 переменная удалена — write-set поведение встроено в сервер по умолчанию**, настраивать нечего; указание переменной в `my.cnf` приведёт к ошибке запуска.
- `transaction_write_set_extraction` удалена в 8.3.0.
- Изменения на источнике вступают в силу для реплицируемых транзакций после `STOP REPLICA; START REPLICA;` на реплике.
- Механизм вычисления write-set — `master_slave_mechanism.md` («Параллельная репликация (MTS) и WRITESET»).

### 4. Подбор числа воркеров

| Ядер CPU реплики | `replica_parallel_workers` | Пояснение |
| :--- | :--- | :--- |
| 2–4 | 2–4 | Близко к числу ядер |
| 8 | 4–8 | Типовая рабочая точка |
| 16+ | 8–16 | Свыше 16 — только по измерениям: overhead координатора и context switches растут |

Правило: начать с 4, повышать постепенно, наблюдая `Seconds_Behind_Source` и CPU/IO реплики в течение 1–2 часов типовой нагрузки. Если CPU недозагружен, а лаг есть — увеличить на 2–4; если растут переключения контекста или дедлоки воркеров без снижения лага — уменьшить. На multi-source число applier-потоков = `replica_parallel_workers` × число каналов — учитывайте при подсчёте.

### 5. Тюнинг очереди координатора

```ini
[mysqld]
# Мягкий лимит памяти под очереди событий всех воркеров (дефолт 8.0/8.4: 128M)
# Должен быть ≥ max_allowed_packet на источнике
replica_pending_jobs_size_max = 128M

# Как часто координатор сбрасывает метаданные applier и обновляет прогресс
replica_checkpoint_period = 300    # мс, дефолт
replica_checkpoint_group = 512     # транзакций, дефолт
```

- `replica_pending_jobs_size_max` — мягкий лимит, память разделяется между очередями всех воркеров. Событие, превышающее лимит, удерживается, пока все очереди воркеров не опустеют — штатно создаёт пик лага и снижает параллелизм. При регулярно больших событиях повышайте лимит.
- `replica_checkpoint_*` — не трогайте без причины: регулируют частоту flush метаданных applier (позиция для crash-recovery) и обновления прогресса в `SHOW REPLICA STATUS`.

### 6. Мониторинг MTS

```sql
-- Состояние воркеров (8.0+; в 5.7 — LAST_SEEN_TRANSACTION вместо LAST_APPLIED_TRANSACTION,
-- колонок таймингов и ретраев нет)
SELECT CHANNEL_NAME, WORKER_ID, THREAD_ID, SERVICE_STATE,
       LAST_APPLIED_TRANSACTION,
       LAST_APPLIED_TRANSACTION_END_APPLY_TIMESTAMP,
       LAST_APPLIED_TRANSACTION_RETRIES_COUNT,
       LAST_ERROR_NUMBER, LAST_ERROR_MESSAGE
FROM performance_schema.replication_applier_status_by_worker
ORDER BY CHANNEL_NAME, WORKER_ID;
-- → много воркеров в ON, но лаг растёт = зависимости/блокировки; OFF = поток завершён

-- Координатор (только при MTS; в 5.7 — только колонки ошибок)
SELECT CHANNEL_NAME, THREAD_ID, SERVICE_STATE,
       LAST_PROCESSED_TRANSACTION, PROCESSING_TRANSACTION,
       LAST_ERROR_NUMBER, LAST_ERROR_MESSAGE
FROM performance_schema.replication_applier_status_by_coordinator;
-- → PROCESSING_TRANSACTION застрял на одной транзакции — кандидат в тяжёлые/DDL

-- Ретраи по каналам (дефолт replica_transaction_retries = 10;
-- ретраи при InnoDB deadlock и превышении innodb_lock_wait_timeout)
SELECT CHANNEL_NAME, SERVICE_STATE, REMAINING_DELAY, COUNT_TRANSACTIONS_RETRIES
FROM performance_schema.replication_applier_status;

-- Применена ли транзакция, на которой воркер остановился с ошибкой (≠ 0 — зафиксирована)
SELECT CHANNEL_NAME, WORKER_ID,
       GTID_SUBSET(LAST_APPLIED_TRANSACTION, @@GLOBAL.GTID_EXECUTED) AS committed
FROM performance_schema.replication_applier_status_by_worker;
-- → при gtid_mode = OFF колонка содержит ANONYMOUS — запрос неприменим
```

Интерпретация:
- `SERVICE_STATE`: `ON` — поток существует (активен или idle); `OFF` — поток завершён (после `STOP REPLICA` `THREAD_ID` = NULL, `WORKER_ID` сохраняется).
- Ошибки воркера дублируются в error log реплики; `LAST_ERROR_TIMESTAMP` — время последней ошибки.
- Детальный лаг по меткам коммит/применение — в `lag_monitoring.md` (раздел «Точный лаг через Performance Schema»).

### 7. Crash-safety и MTS

```ini
[mysqld]
relay_log_recovery = ON
sync_relay_log = 1
```

- `relay_log_recovery = ON` с 5.7.13 автоматически устраняет разрывы (gaps) в последовательности транзакций MTS при старте сервера. До 5.7.13 требовалась ручная процедура: старт с `relay_log_recovery = OFF`, `START REPLICA UNTIL SQL_AFTER_MTS_GAPS`, затем рестарт с `ON`.
- При GTID-репликации с 5.7.28 реплика с `SOURCE_AUTO_POSITION = 1` (в 5.7 — `MASTER_AUTO_POSITION`) пропускает расчёт пропусков — старые relay logs не нужны для восстановления.
- `sync_relay_log = 1` минимизирует объём событий, которые придётся запросить с источника после краха: при восстановлении неприменённые relay log отбрасываются и перечитываются, а не «достраиваются» из локальных файлов. Дефолт `10000` — разумный баланс; детали — `relay_logs_crashsafe.md`.
- Метаданные applier в транзакционных таблицах (`relay_log_info_repository = TABLE`) — дефолт в 8.0; переменная удалена в 8.3. Детали — `relay_logs_crashsafe.md`.

### 8. Когда MTS не помогает

- Транзакции зависимы (одна горячая таблица/строка, длинные цепочки зависимостей) — логические часы группируют их в одну группу.
- DDL и очень большие транзакции — не распределяются по воркерам (`master_slave_mechanism.md`).
- Узкое место на реплике — диск/IO или CPU, а не параллелизм применения.
- Нагрузка по природе однопоточная (редкие крупные batch'и).

### 9. Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Лаг не падает после включения MTS | Транзакции зависимы; тяжёлые блокировки на реплике | Раздел 6: воркеры idle или долго в одной транзакции; `INNODB_TRX` / `performance_schema.data_locks`; оптимизировать паттерны записи |
| Дедлоки между воркерами | Конкуренция при применении | `replica_preserve_commit_order = ON`; снизить `replica_parallel_workers`; ретраи видны в `LAST_APPLIED_TRANSACTION_RETRIES_COUNT` |
| Ошибка в конкретном воркере | Конфликт/несовместимость данных | `LAST_ERROR_MESSAGE`; исправить как обычную ошибку применения (`replication_sql_errors.md`); перезапустить applier |
| Координатор «завис», воркеры бездействуют | Длинная транзакция/DDL в очереди; режим `DATABASE` при одной БД | `PROCESSING_TRANSACTION` в by_coordinator; переключить на `LOGICAL_CLOCK`; дождаться завершения тяжёлой транзакции |
| Пики лага на больших событиях | Событие > `replica_pending_jobs_size_max` | Повысить лимит (раздел 5) |
| Рост ретраев (`COUNT_TRANSACTIONS_RETRIES`) | Deadlock / lock timeout на реплике | Разобрать причину блокировок; `replica_transaction_retries` (дефолт 10) — сколько ретраев до остановки потока |

### 10. Валидация настройки

```sql
-- 1. Конфигурация применилась
SHOW GLOBAL VARIABLES WHERE Variable_name LIKE 'replica_parallel%'
   OR Variable_name = 'replica_preserve_commit_order';
-- → replica_parallel_workers = 8, replica_parallel_type = LOGICAL_CLOCK, replica_preserve_commit_order = ON

-- 2. Потоки созданы: 1 receiver + 1 coordinator + 8 workers
SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE USER = 'system user';
-- → 10

-- 3. P_S-таблицы наполняются
SELECT COUNT(*) FROM performance_schema.replication_applier_status_by_worker;
-- → 8 (по числу воркеров)

-- 4. Лаг не растёт при типовой нагрузке (наблюдение 1–2 часа)
SHOW REPLICA STATUS\G
-- → Seconds_Behind_Source стабильно мал (интерпретация — lag_monitoring.md)
```

### 11. Откат изменений

```sql
STOP REPLICA SQL_THREAD;
SET GLOBAL replica_parallel_workers = 4;   -- прежнее значение; 1 — однопоточный applier
START REPLICA SQL_THREAD;
```

В `my.cnf` верните исходные значения `replica_parallel_*` / `replica_preserve_commit_order`, чтобы при рестарте не применились непроверенные настройки. На источнике (≤ 8.2) откат write-set tracking: `SET GLOBAL binlog_transaction_dependency_tracking = COMMIT_ORDER;` + `STOP REPLICA; START REPLICA;` на реплике.

## Граничные случаи

- **Multi-source:** воркеры и координатор — на каждый канал; число воркеров глобальное, настройка по каналам невозможна; макс. 256 каналов. Детали — `multi-source.md`.
- **NDB Cluster:** MTS поддерживается с NDB 8.0.33 (раньше `replica_parallel_workers` молча игнорировался); на источнике требуется `binlog_transaction_dependency_tracking = WRITESET` и `--ndb-log-transaction-dependency=ON`; режим `DATABASE` NDB не поддерживает.
- **Delayed replication + MTS:** `START REPLICA UNTIL SQL_AFTER_GTIDS` несовместим с многопоточным применением — выдаётся предупреждение и переключение в однопоточный режим; для MTS используйте `UNTIL SQL_AFTER_MTS_GAPS` (`delayed_replication.md`).
- **P_S выключен:** колонки таймингов транзакций в `replication_applier_status_by_worker` / `_by_coordinator` равны 0 — точный лаг по меткам недоступен.
- **`replica_parallel_workers = 0`:** с 8.0.30 deprecated (предупреждение); для однопоточного применения — `1`.
- **Relay-log место:** `relay_log_space_limit` не абсолютен — при неприменимых транзакциях receiver временно игнорирует лимит (детали — `lag_monitoring.md`).

## Лучшие практика

1. `replica_parallel_type = LOGICAL_CLOCK` + `replica_preserve_commit_order = ON` — стандарт production.
2. Число воркеров ≈ число ядер CPU реплики; начинать с 4; свыше 16 — только по измерениям.
3. На источнике ≤ 8.2 — `binlog_transaction_dependency_tracking = WRITESET` (на 8.4 встроено); `binlog_format = ROW`.
4. `sync_relay_log = 1` + `relay_log_recovery = ON` для crash-safety MTS.
5. `replica_pending_jobs_size_max` ≥ `max_allowed_packet` источника; повышать при регулярно больших событиях.
6. Мониторить воркеров и координатора через Performance Schema, а не только `Seconds_Behind_Source`.
7. Менять число воркеров постепенно, под наблюдением лага и CPU.

## Дополнительная информация

- **Связанные файлы:** `lag_monitoring.md` (лаг и точные метки), `master_slave_mechanism.md` (механизм write-set, потоки, большие транзакции), `management_debug.md` (отладка), `multi-source.md` (каналы), `delayed_replication.md` (SOURCE_DELAY), `relay_logs_crashsafe.md` (relay-log и crash-safety), `replication_sql_errors.md` (ошибки применения), `gtid.md` (GTID), `semi-sync-replication.md` (полусинхронность), `failover_switchover.md` (failover), `../monitoring.md` (алертинг)
- **Переменные:** `replica_parallel_workers` (макс. 1024), `replica_parallel_type`, `replica_preserve_commit_order`, `replica_pending_jobs_size_max` (128M), `replica_checkpoint_period` (300 мс), `replica_checkpoint_group` (512), `replica_transaction_retries` (10), `binlog_transaction_dependency_tracking` (≤ 8.2), `transaction_write_set_extraction` (≤ 8.2)
- **Performance Schema:** `replication_applier_status`, `replication_applier_status_by_coordinator`, `replication_applier_status_by_worker`
- **Внешние ссылки:** [Replica Server Options and Variables (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replication-options-replica.html), [Replication Threads (8.0)](https://dev.mysql.com/doc/refman/8.0/en/replication-threads.html), [Performance Schema Replication Tables (8.4)](https://dev.mysql.com/doc/refman/8.4/en/performance-schema-replication-tables.html), [Replication Retries and Timeouts (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replication-features-timeout.html)
