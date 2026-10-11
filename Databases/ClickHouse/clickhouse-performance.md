# ClickHouse — Производительность и оптимизация

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

- **Векторное выполнение (Vectorized Execution):** Обработка данных блоками (пачками) вместо построчной. Позволяет эффективно использовать SIMD-инструкции процессора (SSE 4.2, AVX-512) и кэши L1/L2/L3.
- **Гранула (Granule):** Минимальный блок данных, читаемый ClickHouse с диска. Размер задается параметром `index_granularity` (по умолчанию 8192 строк). Все индексы пропуска данных работают на уровне гранул.
- **Часть (Part):** Независимый каталог на диске с данными одной таблицы. ClickHouse выполняет запросы параллельно по частям.
- **Слияние (Merge):** Фоновый процесс объединения мелких частей в большие для оптимизации чтения.
- **Data Skipping Index:** Вторичный индекс, хранящий агрегированную информацию о гранулах (min/max, bloom filter, набор значений). Позволяет пропускать чтение целых блоков.
- **PREWHERE:** Фильтр, применяемый до чтения основных колонок. ClickHouse сначала читает только колонки из `PREWHERE`, отфильтровывает строки и только потом читает остальные колонки.
- **Materialized View (MV):** Фоновая таблица, обновляемая при каждой вставке в исходную таблицу. Работает как триггер на уровне СУБД.
- **Проекция (Projection):** "Скрытая" копия данных внутри таблицы с другим порядком сортировки или предварительной агрегацией. Выбирается автоматически оптимизатором запросов.
- **External Aggregation:** Способ выполнения GROUP BY, при котором промежуточные данные сбрасываются на диск при превышении лимита памяти. Защита от OOM.
- **SLO (Service Level Objective):** Целевой показатель производительности, например P95 latency < 500 мс или Throughput > 10 000 строк/сек.

## Основные концепции

### Архитектура производительности

ClickHouse оптимизирован для аналитических рабочих нагрузок (OLAP) и строится на трех столпах:

1. **Колоночное хранение:** Данные одной колонки хранятся отдельно. Запрос читает только необходимые колонки, что минимизирует I/O.
2. **Векторное выполнение:** Обработка пачками позволяет использовать SIMD и эффективно загружать кэши процессора.
3. **Разреженные индексы:** Вместо B-Tree, ClickHouse хранит min/max для блоков гранул и может полностью пропускать чтение ненужных частей.

### Иерархия памяти и NUMA

На многопроцессорных серверах (NUMA) ClickHouse может испытывать contention при доступе к памяти. Рекомендации:

- Размещайте ClickHouse на NUMA-node 0 для простых инсталляций.
- Для высоконагруженных кластеров используйте `numactl --cpunodebind=0 --membind=0` при запуске.
- Убедитесь, что `vm.max_map_count` >= 262144 и `THP` отключен (`echo never > /sys/kernel/mm/transparent_hugepage/enabled`).

### Сравнение с OLTP-СУБД

| Характеристика | ClickHouse (OLAP) | PostgreSQL / MySQL (OLTP) |
| :--- | :--- | :--- |
| **Модель данных** | Колоночная, иммутабельные вставки | Строковая, мутации в месте |
| **Индексы** | Разреженные (на уровне гранул) | B-Tree, B+Tree |
| **JOIN** | Hash, Merge, Grace Hash, Direct (словари) | Nested Loop, Hash, Merge Join |
| **Транзакции** | Нет ACID в классическом понимании | Полные ACID-транзакции |
| **Оптимальная нагрузка** | Сложные агрегации по billions строк | Много мелких транзакций, JOIN |

## Системные требования и подготовка ОС

### Железо

| Компонент | Минимум | Рекомендация для production |
| :--- | :--- | :--- |
| **CPU** | 4 vCPU, SSE 4.2+ | 16+ vCPU, AVX-512, частота > 3 GHz |
| **RAM** | 8 GB | 64–256 GB (в зависимости от working set) |
| **Диск** | NVMe SSD 100 GB | NVMe SSD 1–10 TB+ (в зависимости от объема данных) |
| **Сеть** | 1 Gbps | 10+ Gbps для межшардового трафика |

### Проверка поддержки CPU-инструкций

```bash
# Проверка SSE 4.2 и AVX
grep -E 'sse4_2|avx|avx2' /proc/cpuinfo
# → sse4_2, avx, avx2 (должны присутствовать)
```

### Планировщик диска и THP

```bash
# Проверка текущего планировщика
cat /sys/block/sda/queue/scheduler
# → [mq-deadline] kyber bfq none (для SSD предпочтительно mq-deadline или none)

# Отключение THP (Transparent Huge Pages)
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag

# Проверка
cat /sys/kernel/mm/transparent_hugepage/enabled
# → [never] always madvise
```

### Лимиты ОС (systemd)

Создайте `/etc/systemd/system/clickhouse-server.service.d/limits.conf`:

```ini
[Service]
LimitNOFILE=262144
LimitNPROC=131072
```

Примените:

```bash
sudo systemctl daemon-reload
sudo systemctl restart clickhouse-server
sudo systemctl status clickhouse-server
# → active (running)
```

## Настройка производительности

### Параметры серверного конфига (config.xml)

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| `max_memory_usage` | 50–70% от общей RAM | Защита от OOM при конкурентных запросах. |
| `max_bytes_before_external_group_by` | 25–30% от RAM | Включение External Aggregation для предотвращения падения запросов при больших GROUP BY. |
| `max_bytes_before_external_sort` | 25–30% от RAM | Аналогично для ORDER BY. |
| `max_execution_time` | 300–600 сек | Таймаут по умолчанию для защиты от "вечных" запросов. |
| `priority` | 1 (по умолчанию) | Понизить до 2–5 для фоновых ETL, чтобы BI-запросы имели приоритет. |
| `max_threads` | Количество ядер | По умолчанию равно ядрам. Для конкурентных сред можно уменьшить до 0.5–0.7 от ядер. |
| `max_concurrent_queries` | 200–500 | Лимит параллельных запросов. Зависит от CPU и RAM. |
| `async_insert` | 1 | Включить для снижения количества частых мелких вставок. |
| `async_insert_threads` | 1–4 | Количество потоков для асинхронных вставок. |
| `max_insert_block_size` | 1 000 000 | Размер пачки вставки. Увеличьте для снижения числа частей. |
| `min_insert_block_size_rows` | 100 000 | Минимальный размер пачки перед принудительной отправкой. |
| `max_partitions_per_insert_block` | 100 | Лимит партиций в одном INSERT-блоке (защита от перегрузки; при превышении — предупреждение или ошибка, управляется `throw_on_max_partitions_per_insert_block`). |

### Пользовательские профили (users.xml)

Для разделения приоритетов создайте профили:

```xml
<profiles>
    <default>
        <max_memory_usage>10000000000</max_memory_usage>
        <max_execution_time>300</max_execution_time>
        <max_threads>8</max_threads>
        <priority>1</priority>
    </default>
    <bi_dashboards>
        <max_memory_usage>20000000000</max_memory_usage>
        <max_execution_time>60</max_execution_time>
        <priority>1</priority>
    </bi_dashboards>
    <etl_background>
        <max_memory_usage>30000000000</max_memory_usage>
        <max_execution_time>3600</max_execution_time>
        <priority>5</priority>
    </etl_background>
</profiles>
```

## Сжатие и кодеки

ClickHouse позволяет задавать кодеки для каждой колонки индивидуально. Выбор кодека — это баланс между скоростью чтения и объемом хранения.

| Кодек | Описание | Рекомендации по применению |
| :--- | :--- | :--- |
| **LZ4** | Стандартный кодек, сверхбыстрая декомпрессия. | По умолчанию для всех типов. Идеален для горячих данных. |
| **ZSTD(level)** | Высокая степень сжатия, выше нагрузка на CPU. | Для исторических (холодных) данных. Уровни 1–3 — баланс, 10+ — архив. |
| **Delta(N)** | Сохраняет разницу между соседними значениями. | Для монотонно растущих чисел (ID, временные метки). Эффективен вместе с LZ4/ZSTD. |
| **DoubleDelta** | Разница разниц (вторая производная). | Идеально для временных рядов (Time-series) с регулярным шагом. |
| **Gorilla** | Алгоритм сжатия чисел с плавающей точкой (FCM). | Для `Float32/Float64` (метрики, показания датчиков). |
| **T64** | Транспонирование 64-битных чисел. | Для разреженных данных, где много нулевых битов. |

**Техническое обоснование:** Декомпрессия данных в ClickHouse обычно происходит быстрее, чем чтение с диска. Поэтому использование сильного сжатия (ZSTD) для I/O-bound запросов может парадоксальным образом ускорить выполнение за счет снижения объема передаваемых данных.

### Пример применения кодеков

```sql
CREATE TABLE metrics (
    ts DateTime CODEC(Delta(4), ZSTD(3)),
    service LowCardinality(String),
    value Float64 CODEC(Gorilla),
    status String
) ENGINE = MergeTree()
ORDER BY (service, ts);
```

## Оптимизация запросов

### PREWHERE

`PREWHERE` — специфичная для ClickHouse оптимизация, позволяющая радикально снизить объем читаемых данных.

- **Логика работы:** В классическом `WHERE` ClickHouse читает все колонки, указанные в `SELECT` и `WHERE`, для всех гранул, которые не были отсечены разреженным индексом. В `PREWHERE` ClickHouse сначала считывает только те колонки, которые участвуют в условии фильтрации. Затем он отфильтровывает ненужные строки и считывает остальные запрошенные колонки только для тех строк, которые прошли фильтр.
- **Pushdown:** В большинстве случаев ClickHouse автоматически переносит простые фильтры из `WHERE` в `PREWHERE`, но для сложных выражений или специфических условий может потребоваться ручное указание ключевого слова `PREWHERE`.

```sql
-- Автоматический pushdown ClickHouse обычно справляется, но для тяжелых запросов:
SELECT url, count()
FROM access_logs
WHERE event_time > now() - INTERVAL 1 DAY
PREWHERE severity = 'ERROR'
GROUP BY url;
```

### Индексы пропуска данных (Data Skipping Indices)

Вторичные индексы, которые хранят агрегированную информацию о блоках гранул.

- **Принцип действия:** ClickHouse разбивает колонку на блоки (размер задается через `GRANULARITY`). Для каждого блока вычисляется индекс (min/max, bloom filter и др.). При запросе ClickHouse сначала проверяет индекс и, если блок гарантированно не содержит нужных данных, полностью пропускает его чтение.
- **Типы индексов:**
  - `minmax`: Хранит границы значений. Полезен для временных меток, не входящих в основной ключ.
  - `set(N)`: Хранит набор уникальных значений (до N штук). Полезен для колонок с низкой мощностью (например, `status_id`).
  - `bloom_filter([false_positive])`: Позволяет быстро проверить отсутствие значения. Идеален для идентификаторов (UUID, ID), которые редко встречаются.

```sql
CREATE TABLE access_logs (
    event_time DateTime,
    user_id UUID,
    url String,
    INDEX idx_url url TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX idx_status status TYPE set(100) GRANULARITY 4
) ENGINE = MergeTree() ORDER BY event_time;
```

### ORDER BY и ключевые колонки

Правильный выбор колонок в `ORDER BY` — самое важное решение для производительности:

1. **Колонка для фильтрации по времени:** Первая колонка должна быть временной меткой, если запросы часто содержат условие на дату.
2. **Колонка с высокой мощностью (High Cardinality):** Вторая колонка должна иметь много уникальных значений (например, `request_id`), чтобы избежать большого числа строк на одну гранулу.
3. **Избегайте низкой мощности в начале ORDER BY:** `status` или `country` в начале ORDER BY приведут к большому числу строк на гранулу и снизят эффективность индексов.

```sql
-- Плохо: status имеет низкую мощность
CREATE TABLE bad (status String, ts DateTime) ENGINE = MergeTree() ORDER BY (status, ts);

-- Хорошо: ts + request_id
CREATE TABLE good (ts DateTime, request_id String, status String) ENGINE = MergeTree() ORDER BY (ts, request_id);
```

## Оптимизация JOIN

ClickHouse выбирает алгоритм на основе настроек и объема данных:

- **Hash Join:** Правая таблица полностью считывается в хэш-таблицу. Самый быстрый метод, но требует много RAM.
- **Direct Join (Dictionaries):** Ультимативный способ оптимизации соединения со справочниками. Поиск по ключу в RAM без построения промежуточных структур.
- **Merge Join:** Обе таблицы сортируются по ключу. Используется, когда данные не влезают в RAM.
- **Grace Hash Join:** Гибридный метод с разбиением на корзины и возможным сбросом на диск.

### Настройки для JOIN

```sql
SET join_algorithm = 'grace_hash'; -- или 'hash', 'direct', 'merge'
SET max_rows_in_join = 1000000000;
SET max_bytes_in_join = 100000000000;
SET join_use_nulls = 0; -- По умолчанию: заполнение значениями по умолчанию
```

### Рекомендации

- Всегда помещайте меньшую таблицу справа в `JOIN`.
- Используйте **Словари (Dictionaries)** для статических справочников — это самый быстрый способ соединения.
- Для распределенных окружений используйте `distributed_product_mode = 'local'` или `'global'` в зависимости от задачи.

## Предварительная агрегация

### Материализованные представления (Materialized Views)

Работают как "триггеры" на вставку данных. При поступлении пачки данных в исходную таблицу, ClickHouse выполняет запрос, описанный в MV, и записывает результат в целевую таблицу.

- **Преимущество:** Аналитические отчеты строятся мгновенно.
- **Ограничение:** MV видит только новые вставляемые данные; изменения существующих данных через мутации не отражаются автоматически.

```sql
CREATE MATERIALIZED VIEW mv_daily_stats
ENGINE = SummingMergeTree
PARTITION BY toDate(ts)
ORDER BY (service, toDate(ts))
AS SELECT
    service,
    toDate(ts) AS day,
    sum(value) AS total_value,
    count() AS cnt
FROM metrics
GROUP BY service, toDate(ts);
```

### Refreshable Materialized Views

В отличие от инкрементальных MV (выше), refreshable MV периодически перевыполняет запрос по всему набору данных и перезаписывает результат в целевую таблицу. Production-ready с версии 24.10.

```sql
-- Создание: обновление каждую минуту
CREATE MATERIALIZED VIEW events_summary_mv
REFRESH EVERY 1 MINUTE TO events_summary AS
SELECT
    service,
    count() AS events_count,
    uniqCombined(user_id) AS users
FROM events
GROUP BY service;

-- Принудительное обновление
SYSTEM REFRESH VIEW events_summary_mv;

-- Управление обновлениями
SYSTEM STOP VIEW events_summary_mv;    -- остановить и отменить текущий refresh
SYSTEM PAUSE VIEW events_summary_mv;   -- дождаться текущего, не начинать новые
SYSTEM START VIEW events_summary_mv;   -- возобновить обновления
SYSTEM CANCEL VIEW events_summary_mv;  -- отменить текущий refresh
SYSTEM WAIT VIEW events_summary_mv;    -- дождаться завершения

-- Изменение интервала
ALTER TABLE events_summary_mv MODIFY REFRESH EVERY 30 MINUTE;

-- Статус обновлений
SELECT database, view, status, last_success_time, next_refresh_time, exception
FROM system.view_refreshes;
```

**Режимы записи в целевую таблицу:**
- `REPLACE` (по умолчанию) — при каждом обновлении содержимое целевой таблицы полностью перезаписывается.
- `APPEND` — результат добавляется в конец (для снапшотов состояния во времени).

**Когда использовать:**
- Сложные JOIN и денормализация, несовместимые с инкрементальным подходом.
- Периодическое полное перестроение (batch-процессы, DAG-подобные зависимости между MV).
- Кэширование «топ-N» и справочных результатов.

**Когда НЕ использовать:** агрегация по одной таблице — для этого инкрементальные MV масштабируются лучше (обрабатывают только новые данные).

**Ограничения:** refreshable MV, обновления которых не координируются через Keeper, забывают время последнего обновления — после перезапуска сервера все они могут обновиться одновременно.

### Проекции (Projections)

"Скрытые" копии данных внутри основной таблицы с другим порядком сортировки или агрегацией.

- **Автоматическая маршрутизация:** ClickHouse сам проверяет, какая проекция позволит выполнить запрос быстрее.
- **Синхронность:** Проекции всегда консистентны с основными данными.

```sql
ALTER TABLE metrics
ADD PROJECTION proj_by_hour
(
    SELECT
        toStartOfHour(ts) AS hour,
        service,
        sum(value) AS total_value
    GROUP BY hour, service
);

-- Активация проекции
ALTER TABLE metrics MATERIALIZE PROJECTION proj_by_hour;
```

## Уровни хранения (TTL и Tiered Storage)

### TTL (Time To Live)

Автоматическое удаление, перемещение или агрегация данных по истечении времени.

**Формы TTL:**

```sql
-- 1. Удаление через месяц (табличное TTL)
ALTER TABLE metrics
MODIFY TTL ts + INTERVAL 1 MONTH DELETE;

-- 2. Условное удаление (только для строк, удовлетворяющих WHERE)
ALTER TABLE metrics
MODIFY TTL ts + INTERVAL 1 MONTH DELETE WHERE service = 'debug';

-- 3. Перемещение на холодный диск через неделю
ALTER TABLE metrics
MODIFY TTL ts + INTERVAL 1 WEEK TO DISK 'hdd';

-- 4. Перемещение в другой volume
ALTER TABLE metrics
MODIFY TTL ts + INTERVAL 1 WEEK TO VOLUME 'cold';

-- 5. Перекомпрессия через месяц (экономия места на архиве)
ALTER TABLE metrics
MODIFY TTL ts + INTERVAL 1 MONTH RECOMPRESS CODEC(ZSTD(10));

-- 6. Агрегация (rollup) через неделю — downsampling
ALTER TABLE metrics
MODIFY TTL ts + INTERVAL 1 WEEK GROUP BY
    service, toStartOfHour(ts)
SET value = sum(value), cnt = sum(cnt);

-- 7. Колоночное TTL: удаление значения конкретной колонки
ALTER TABLE metrics
MODIFY COLUMN raw_payload String TTL ts + INTERVAL 1 DAY;
```

**Колоночное TTL:** задаётся при создании колонки или через `MODIFY COLUMN`. Удаляет значение колонки (заменяет на default) по истечении времени, оставляя строку.

**Настройки TTL-мержей:**

| Настройка | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `merge_with_ttl_timeout` | 14400 (4 часа) | Минимальный интервал между TTL-мержами (DELETE/TO DISK). |
| `merge_with_recompression_ttl_timeout` | 14400 (4 часа) | Минимальный интервал между TTL-мержами (RECOMPRESS). |

**Принудительное применение TTL:**
```sql
-- Применить TTL немедленно (перезаписать части)
ALTER TABLE metrics MATERIALIZE TTL;
```

**Важно:** TTL применяется при слиянии, а не мгновенно. Данные могут оставаться в частях до `merge_with_ttl_timeout`. `MATERIALIZE TTL` применяет TTL принудительно.

### Tiered Storage

Прозрачное объединение SSD (hot) и HDD (cold) в рамках одной таблицы. Для on-prem сред используйте локальные диски или S3-совместимые хранилища (MinIO, Ceph RGW).

Детальное описание Tiered Storage с S3 см. в **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)**.

## Мониторинг производительности и SLO

### Ключевые метрики SRE

| Метрика | Источник | Алерт | SLO |
| :--- | :--- | :--- | :--- |
| **Query latency P95/P99** | `system.query_log` | P99 > 2 сек | P95 < 500 мс |
| **Queries per second** | `system.metrics` | Резкое падение > 50% | Стабильная throughput |
| **Очередь запросов** | `system.metrics` | `Query` > 50 | < 10 |
| **CPU utilization** | `node_exporter` | > 80% в течение 5 мин | < 70% среднее |
| **Disk usage** | `node_exporter` | > 85% | < 75% с запасом |
| **Parts count** | `system.parts` | Рост без снижения | Стабильное число после merge |
| **Merges in progress** | `system.merges` | > 10 на таблицу | < 5 |
| **Memory usage** | `system.metrics` | > 85% от `max_memory_usage` | < 70% |

### Prometheus конфигурация

```yaml
scrape_configs:
  - job_name: 'clickhouse'
    static_configs:
      - targets: ['localhost:9363']
```

ClickHouse экспортирует метрики в Prometheus через встроенный exporter на порту 9363 (если включен в конфиге).

### Диагностика медленных запросов

```sql
-- Топ-10 самых медленных запросов за последний час
SELECT
    query_id,
    query,
    query_duration_ms / 1000 AS duration_sec,
    read_rows,
    read_bytes,
    memory_usage
FROM system.query_log
WHERE type = 'QueryFinish'
  AND event_time > now() - INTERVAL 1 HOUR
ORDER BY query_duration_ms DESC
LIMIT 10;
```

### Проверка текущих слияний

```sql
-- Текущие слияния и их прогресс
SELECT
    database,
    table,
    is_mutation,
    mutation_id,
    elapsed,
    progress,
    rows_written
FROM system.merges
ORDER BY elapsed DESC;
```

### Анализ query_log (SRE/DevOps)

`system.query_log` — основной источник для диагностики медленных запросов и построения SLO. Лог включается в `config.xml`:

```xml
<!-- config.xml -->
<clickhouse>
    <logger>
        <level>information</level>
    </logger>
</clickhouse>
```

**Настройка retention для query_log через TTL (предотвращает рост таблицы на сотни ГБ):**

```sql
ALTER TABLE system.query_log MODIFY TTL event_date + INTERVAL 7 DAY DELETE;
```

**Logrotate для системных логов на уровне ОС:**

```bash
# /etc/logrotate.d/clickhouse-server
/var/log/clickhouse-server/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

**Метрики запросов для алертов в Prometheus:**

```yaml
groups:
- name: clickhouse.query.slo
  rules:
  - alert: ClickHouseSlowQueriesP95
    expr: histogram_quantile(0.95, sum(rate(clickhouse_query_duration_seconds_bucket[5m])) by (le)) > 0.5
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "ClickHouse: P95 latency превышает 500ms"

  - alert: ClickHouseQueryErrors
    expr: increase(clickhouse_metrics_QueryExecutionFailedEvents[5m]) > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "ClickHouse: ошибки выполнения запросов (Code: {{ $value }})"
```
```

```sql
-- Проверка количества частей
SELECT
    database,
    table,
    count() AS parts,
    sum(rows) AS total_rows,
    sum(bytes_on_disk) AS total_bytes
FROM system.parts
WHERE active
GROUP BY database, table
ORDER BY parts DESC;
```

## Тюнинг запросов

### EXPLAIN и анализ плана

ClickHouse поддерживает несколько вариантов `EXPLAIN` для разных уровней анализа:

```sql
-- Базовый план выполнения
EXPLAIN SELECT count() FROM access_logs WHERE event_time > now() - INTERVAL 1 DAY;

-- AST (абстрактное синтаксическое дерево) — для всех типов запросов
EXPLAIN AST SELECT count() FROM access_logs;

-- SYNTAX — текст запроса после AST-оптимизаций
EXPLAIN SYNTAX SELECT count() FROM access_logs WHERE 1=1;

-- QUERY TREE — дерево запроса после оптимизаций
EXPLAIN QUERY TREE SELECT count() FROM access_logs;

-- PLAN — план выполнения (с настройками: optimize, json, actions, indexes, projections, sorting, compact, pretty)
EXPLAIN PLAN indexes = 1 SELECT count() FROM access_logs WHERE event_time > now() - INTERVAL 1 DAY;

-- PIPELINE — план конвейера выполнения
EXPLAIN PIPELINE SELECT count() FROM access_logs;

-- ANALYZE — выполняет запрос и аннотирует план реальными метриками
EXPLAIN ANALYZE SELECT count() FROM access_logs WHERE event_time > now() - INTERVAL 1 DAY;

-- ESTIMATE — оценка строк, марок и частей для чтения (только MergeTree)
EXPLAIN ESTIMATE SELECT count() FROM access_logs WHERE event_time > now() - INTERVAL 1 DAY;

-- WHATIF — оценка выгоды от гипотетического индекса
CREATE HYPOTHETICAL INDEX idx_hyp ON access_logs (service);
EXPLAIN WHATIF SELECT count() FROM access_logs WHERE service = 'web';
```

**Что смотреть в выводе:**
- **PLAN:** использование индексов (`index`), количество читаемых гранул, тип JOIN, внешняя агрегация (`external`).
- **ESTIMATE:** оценочное число строк, марок (marks) и частей (parts) — полезно до выполнения тяжёлого запроса.
- **ANALYZE:** реальные метрики выполнения (строки, байты, время) по каждому шагу плана.
- **PIPELINE:** параллелизм конвейера, количество потоков.

**Важно (с 25.9):** `EXPLAIN PLAN` с `indexes = 1` показывает разумный вывод только при `SETTINGS use_query_condition_cache = 0, use_skip_indexes_on_data_read = 0`.

Обратите внимание на:
- Использование индексов (`index`)
- Количество читаемых гранул
- Тип JOIN
- Внешняя агрегация (`external`)

### Оптимизация ORDER BY

Выбор правильного `ORDER BY` — ключевой фактор производительности. Правила:

1. Первая колонка должна быть временной меткой или фильтруемым полем.
2. Используйте колонки с высокой мощностью (cardinality) во второй и последующих позициях.
3. Избегайте `LowCardinality` в `ORDER BY` — это может привести к неэффективному использованию индексов.

### Partition BY

Используйте партиционирование для очень больших таблиц (> 1 млрд строк), чтобы ускорить удаление старых данных:

```sql
PARTITION BY toYYYYMM(event_time)
```

Партиционирование не ускоряет SELECT-запросы автоматически, но позволяет быстро удалять данные через `DROP PARTITION`.

## Процессы слияния и фоновые операции

ClickHouse выполняет слияния (merges) фоново. Контролируйте их параметры:

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| `merge_max_block_size` | 100 000 | Максимальный размер блока при слиянии. |
| `number_of_free_entries_in_pool_to_lower_max_size_of_merge` | 8 | Адаптивное снижение размера слияний при высокой нагрузке. |
| `merge_with_ttl_timeout` | 14400 | Минимальный интервал между TTL-мержами. |

Мониторинг слияний:

```sql
SELECT *
FROM system.merges
ORDER BY elapsed DESC;
```

## Поиск и устранение неисправностей (Troubleshooting)

### Частые проблемы производительности

1. **Слишком много мелких частей (Too many parts):**
   - *Причина:* Частые вставки мелкими порциями.
   - *Решение:* Батчинг на клиенте (100k+ строк) или включение `async_insert = 1`. Увеличьте `min_insert_block_size_rows`.

2. **Memory limit exceeded (Code: 241):**
   - *Причина:* Запрос превысил `max_memory_usage`.
   - *Решение:* Оптимизация запроса (уменьшение выборки), использование `PREWHERE`, включение `max_bytes_before_external_group_by`.

3. **Медленные слияния (Merges):**
   - *Причина:* Слишком много мелких частей или нехватка I/O.
   - *Решение:* Увеличьте `merge_max_block_size`, проверьте загрузку диска (`iostat -xz 1`), убедитесь что THP отключен.

4. **Высокая загрузка CPU при сжатии:**
   - *Причина:* Слишком сильный уровень ZSTD (10+) на горячих данных.
   - *Решение:* Используйте ZSTD(1–3) или LZ4 для горячих данных, ZSTD(10+) только для архивных.

5. **Mutation зависла:**
   - *Причина:* Большая таблица или блокировка.
   - *Решение:* Проверьте `system.mutations`. Увеличьте `mutations_concurrency` или разбейте операцию на несколько партиций.

6. **Блокировка на запись (WRITE lock):**
   - *Причина:* Долгий `ALTER TABLE` или `OPTIMIZE` блокирует вставки.
   - *Решение:* Проверить `system.mutations` и `system.locks`. Использовать `ALTER TABLE ... MODIFY COLUMN` с ограничением `mutations_concurrency`.

7. **Рост query_log на диск:**
   - *Причина:* Нет TTL на `system.query_log`.
   - *Решение:* Добавить `TTL event_date + INTERVAL 7 DAY` и настроить `logrotate` для файлов журналов.

## Лучшие практики

1. **Выбирайте правильный ORDER BY:** Это самое важное решение для производительности. Тестируйте на реальных паттернах запросов.
2. **Используйте PREWHERE:** Для тяжелых запросов с фильтрацией ручное указание `PREWHERE` может дать значительный прирост.
3. **Батчинг вставок:** Минимум 10 000–100 000 строк за раз. Используйте `async_insert = 1` если батчинг на клиенте невозможен.
4. **Словари для справочников:** Для статических данных используйте `Dictionaries` — это самый быстрый способ JOIN.
5. **Типизация:** Используйте `LowCardinality(String)` для строк с небольшим количеством уникальных значений.
6. **Настройка лимитов ОС:** `nofile` >= 262144, отключите THP, используйте `noop`/`deadline` планировщик для SSD.
7. **Включите External Aggregation:** `max_bytes_before_external_group_by` и `max_bytes_before_external_sort` для защиты от OOM.
8. **Мониторинг фоновых процессов:** Добавьте дашборды по `system.merges`, `system.mutations`, `system.parts`.
9. **Benchmark до изменений:** Используйте ClickBench или собственные сценарии для измерения baseline перед оптимизацией.
10. **Capacity Planning:** Планируйте ресурсы с запасом 30–50% на рост данных и нагрузки.

## Дополнительная информация

### См. также

- **[Архитектура ClickHouse](./clickhouse-architecture.md)** — внутреннее устройство, MergeTree, разреженный индекс.
- **[Эксплуатация ClickHouse](./clickhouse-operations.md)** — системные требования, безопасность, бэкапы, мониторинг.
- **[Наблюдаемость ClickHouse](./clickhouse-observability.md)** — query_log, trace_log, метрики в Prometheus.
- **[Кластерное управление ClickHouse](./clickhouse-cluster.md)** — репликация, шардирование, ClickHouse Keeper.
- **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)** — многоуровневое хранение (Tiered Storage).
- **[Бенчмаркинг баз данных](../Concepts/benchmarking.md)** — методологии тестирования производительности.
- **[Шардирование баз данных](../Concepts/sharding.md)** — теория и методы распределения данных.
