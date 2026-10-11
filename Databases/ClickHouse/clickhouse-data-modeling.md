# ClickHouse — Моделирование данных и продвинутая оптимизация

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Кардинальность (cardinality)** — число уникальных значений колонки. Высокая кардинальность (миллионы уникальных значений) требует особых подходов к агрегации и индексированию.

**Денормализация** — хранение избыточных данных в одной широкой таблице вместо JOIN нескольких нормализованных таблиц. Предпочтительная модель для ClickHouse (columnar + слияния).

**Приближённая функция** — функция, дающая результат с погрешностью при значительно меньшем потреблении RAM: `uniqCombined`, `quantileTDigest`, `topK`.

**Оконная функция (window function)** — функция, вычисляемая по окну строк (`row_number`, `lag`, `sum() OVER (...)`).

**Сессия (sessionization)** — группировка событий пользователя в сессии по тайм-ауту неактивности.

**SAMPLE** — выборка фиксированной доли данных (требует `SAMPLE BY` в определении таблицы).

**Downsampling** — снижение гранулярности исторических данных (агрегация 1m → 1h → 1d) для экономии хранения и ускорения долгосрочных запросов.

**MergeTree** — семейство движков таблиц ClickHouse на базе LSM-дерева с фоновым слиянием частей. Определяет физический порядок хранения, индексы и поведение слияний.

**Granule (гранула)** — минимальная единица чтения в MergeTree (по умолчанию 8192 строк). Разреженный индекс указывает на границы гранул.

## Основные концепции

### Архитектурные принципы моделирования для ClickHouse

ClickHouse — колоночная OLAP СУБД на базе MergeTree (LSM-дерево). Понимание внутреннего устройства определяет правильные решения при моделировании:

1. **Порядок данных на диске задаётся `ORDER BY`**. При вставке строки попадают в новую "часть" (part), затем фоновые слияния (merges) упорядочивают части по ключу сортировки. Разреженный индекс строится по границам гранул (по умолчанию 8192 строк) в отсортированном порядке.
2. **Чтение работает через разреженный индекс**. Запрос с фильтром по префиксу `ORDER BY` отсекает целые гранулы без чтения. Фильтр по не-префиксу требует сканирования всех гранул.
3. **Слияния — единственный момент физической перезаписи**. `PARTITION BY` определяет границы, в которых происходят слияния. Слишком много мелких партиций → тысячи файлов метаданных → медленные `SELECT`, `OPTIMIZE`, репликация.
4. **Колонки сжимаются независимо**. Типы данных и кардинальность напрямую влияют на коэффициент сжатия и потребление RAM при чтении.

### Принципы моделирования для OLAP

1. **Денормализация вместо JOIN.** Широкая таблица с дублированием атрибутов — норма для ClickHouse. JOIN дорог, денормализация бесплатна при вставке.
2. **`ORDER BY` определяет всё.** Ключ сортировки задаёт физический порядок, разреженный индекс, эффективность `optimize_read_in_order` и слияний. Выбирайте по паттернам фильтрации.
3. **Партиционирование — грубая единица.** Партиция — единица удаления (`DROP PARTITION`) и оптимизации (`OPTIMIZE PARTITION`). Не делайте слишком много партиций.
4. **Кардинальность влияет на агрегацию.** `GROUP BY` по высококардинальной колонке (user_id, session_id) требует много RAM; используйте приближённые функции.
5. **Типы данных экономят RAM.** `LowCardinality(String)` для строк с малым числом уникальных значений, `Enum` для фиксированного набора, `DateTime` вместо `String`.

### Паттерн: downsampling (снижение гранулярности)

Снижение гранулярности старых данных для экономии хранения и ускорения запросов по историческим данным:

```sql
-- Таблица для почасовых агрегатов
CREATE TABLE metrics_hourly (
    hour DateTime,
    metric_name LowCardinality(String),
    value_avg Float64,
    value_max Float64,
    value_min Float64,
    cnt UInt64
) ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (metric_name, hour);

-- Процедура downsampling (запускать по cron, например, раз в сутки)
INSERT INTO metrics_hourly
SELECT
    toStartOfHour(event_time) AS hour,
    metric_name,
    avg(value) AS value_avg,
    max(value) AS value_max,
    min(value) AS value_min,
    count() AS cnt
FROM metrics
WHERE event_time >= today() - INTERVAL 8 DAY
  AND event_time < today() - INTERVAL 7 DAY
GROUP BY hour, metric_name;

-- После downsampling удалить сырые данные за этот период
ALTER TABLE metrics DROP PARTITION toYYYYMM(today() - INTERVAL 7 DAY);
```

**Стратегия:**
- Хранить сырые данные (1m) за 7 дней, почасовые — за 90 дней, суточные — за 1 год.
- Использовать `SummingMergeTree` для агрегатов, которые можно суммировать (cnt, sum).
- Для avg/min/max хранить промежуточные значения и пересчитывать при rollup.
- Запускать downsampling по cron или через refreshable MV.

**Важно:** downsampling необратим — после удаления сырых данных восстановить гранулярность невозможно. Убедитесь, что агрегаты достаточны для аналитики.

### Паттерн: контроль качества данных (CHECK constraints)

Ограничения `CHECK`/`ASSUME` для валидации данных при вставке:

```sql
-- CHECK: проверяется при INSERT (нарушение — ошибка вставки)
CREATE TABLE sales (
    event_date Date,
    revenue Decimal(18, 2),
    quantity UInt32,
    CONSTRAINT revenue_positive CHECK (revenue >= 0),
    CONSTRAINT quantity_positive CHECK (quantity > 0)
) ENGINE = MergeTree()
ORDER BY event_date;

-- ASSUME: оптимизатор доверяет условию без проверки (ускоряет план)
CREATE TABLE events (
    event_time DateTime,
    user_id UInt64,
    CONSTRAINT date_not_future ASSUME event_time <= now()
) ENGINE = MergeTree()
ORDER BY event_time;
```

**Важно:**
- `CHECK` **не выполняется** на уже существующих данных при добавлении ограничения — только на новых вставках.
- Для валидации старых данных используйте отдельный запрос: `SELECT count() FROM sales WHERE revenue < 0;`
- `ASSUME` не проверяет данные, но позволяет оптимизатору строить более эффективный план (например, отсекать диапазоны).
- Ограничения реплицируются через Keeper на все реплики.

Ограничения можно добавлять/изменять через `ALTER TABLE ... ADD/MODIFY/DROP CONSTRAINT` — подробнее: **[Эволюция схемы — Ограничения](./clickhouse-schema-evolution.md#ограничения-check--assume)**.

### Паттерн: временные ряды (time-series)

```sql
CREATE TABLE metrics (
    event_time DateTime,
    metric_name LowCardinality(String),
    value Float64,
    tags Map(LowCardinality(String), LowCardinality(String))
) ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (metric_name, event_time)
TTL event_time + INTERVAL 1 YEAR DELETE;
```

**Ключевые решения:**
- `ORDER BY (metric_name, event_time)` — фильтрация по метрике + диапазону времени.
- `PARTITION BY toYYYYMM(event_time)` — месячные партиции (не `toYYYYMMDD` — слишком много партиций).
- `TTL` — автоматическое удаление старых данных.
- `Map` для тегов — гибкая схема без изменения DDL.

### Паттерн: сессии (sessionization)

```sql
-- Разбивка событий на сессии по тайм-ауту 30 минут
WITH events_with_gap AS (
    SELECT
        user_id,
        event_time,
        event_time - lagInFrame(event_time) OVER (PARTITION BY user_id ORDER BY event_time) AS gap
    FROM events
)
SELECT
    user_id,
    session_id,
    count() AS events_count,
    min(event_time) AS session_start,
    max(event_time) AS session_end,
    any(session_duration) AS duration
FROM (
    SELECT
        user_id,
        event_time,
        sum(gap > INTERVAL 30 MINUTE) OVER (PARTITION BY user_id ORDER BY event_time) AS session_id
    FROM events_with_gap
)
GROUP BY user_id, session_id
ORDER BY user_id, session_id;
```

**Как работает:** `lagInFrame` берёт время предыдущего события; разрыв > 30 минут увеличивает счётчик сессий (`sum(...) OVER`), формируя `session_id`.

### Паттерн: воронка (funnel)

```sql
-- Воронка: view → cart → purchase за 24 часа
SELECT
    windowFunnel(86400)(event_time, event = 'view', event = 'cart', event = 'purchase') AS funnel_step
FROM events
WHERE event_time > now() - INTERVAL 7 DAY
GROUP BY user_id;

-- Доля пользователей, дошедших до каждого шага
SELECT
    countIf(funnel_step >= 1) AS viewed,
    countIf(funnel_step >= 2) AS carted,
    countIf(funnel_step >= 3) AS purchased
FROM (
    SELECT windowFunnel(86400)(event_time, event = 'view', event = 'cart', event = 'purchase') AS funnel_step
    FROM events
    GROUP BY user_id
);
```

`windowFunnel(window)(timestamp, cond1, cond2, ...)` — проверяет цепочку событий в заданном временном окне, возвращает номер последнего выполненного шага.

### Паттерн: высококардинальные теги

```sql
-- Плохо: GROUP BY по высококардинальной колонке
SELECT user_id, count() FROM events GROUP BY user_id;  -- миллионы групп

-- Хорошо: приближённые функции
SELECT uniqCombined(user_id) AS users FROM events;

-- Топ-K значений
SELECT topK(10)(user_id) AS top_users FROM events;

-- Агрегация по тегам через sumMap
SELECT sumMap(tags) AS tag_counts FROM events;
```

### Паттерн: широкие таблицы и Array/Map

```sql
-- Array-колонка: теги события
CREATE TABLE events (
    event_time DateTime,
    user_id UInt64,
    tags Array(LowCardinality(String))
) ENGINE = MergeTree
ORDER BY (event_time, user_id);

-- Разворот массива в строки
SELECT tag, count() FROM events ARRAY JOIN tags AS tag GROUP BY tag;

-- Map-колонка: гибкие атрибуты
CREATE TABLE events (
    event_time DateTime,
    attrs Map(LowCardinality(String), String)
) ENGINE = MergeTree
ORDER BY event_time;

-- Доступ к элементу
SELECT attrs['source'] AS source, count() FROM events GROUP BY source;
```

### Паттерн: материализованные представления для предварительной агрегации

Используйте Materialized Views для автоматического поддержания агрегатов при вставке:

```sql
-- Исходная таблица сырых событий
CREATE TABLE events_raw (
    event_time DateTime,
    service LowCardinality(String),
    endpoint LowCardinality(String),
    status_code UInt16,
    duration_ms UInt32
) ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (service, event_time);

-- Агрегатная таблица для дашбордов
CREATE TABLE events_agg_1m (
    minute DateTime,
    service LowCardinality(String),
    endpoint LowCardinality(String),
    status_code UInt16,
    cnt UInt64,
    sum_duration UInt64,
    max_duration UInt32
) ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(minute)
ORDER BY (service, endpoint, minute);

-- Materialized View: заполняет агрегат при каждой вставке в events_raw
CREATE MATERIALIZED VIEW events_mv_1m TO events_agg_1m AS
SELECT
    toStartOfMinute(event_time) AS minute,
    service,
    endpoint,
    status_code,
    count() AS cnt,
    sum(duration_ms) AS sum_duration,
    max(duration_ms) AS max_duration
FROM events_raw
GROUP BY minute, service, endpoint, status_code;
```

**Преимущества:**
- Агрегаты обновляются автоматически и синхронно с вставкой
- Нет необходимости в отдельном ETL-процессе
- Запросы к дашбордам читают предварительно агрегированные данные (в 10-1000 раз быстрее)

**Ограничения:**
- MV не обрабатывают `UPDATE`/`DELETE` в исходной таблице (только `INSERT`)
- Для `ReplacingMergeTree`/`CollapsingMergeTree` нужны специальные паттерны дедупликации

### Ловушки партиционирования

| Антипаттерн | Проблема | Решение |
| :--- | :--- | :--- |
| `PARTITION BY toYYYYMMDD(event_time)` | Партиция на каждый день → тысячи партиций, медленные метаданные | `toYYYYMM(event_time)` (месяцы) или `toYYYYMM(event_time)` |
| `PARTITION BY toDate(event_time)` при высоком потоке | Много мелких партиций | Месячные партиции + `ORDER BY` с временем |
| Слишком мелкие партиции | `max_partitions_per_insert_block` блокирует вставки | Увеличить лимит или укрупнить партиции |
| `PARTITION BY` высококардинальной колонки | Каждая строка — отдельная партиция | Партиционировать только по времени/грубому признаку |

### Приближённые функции (справочник)

| Функция | Точный аналог | Погрешность | RAM | Кейс |
| :--- | :--- | :--- | :--- | :--- |
| `uniqCombined` | `uniqExact` | ~1–2% | низкая | уникальные пользователи, high-cardinality |
| `uniqHLL12` | `uniqExact` | ~2% | очень низкая | очень высокая кардинальность |
| `quantileTDigest` | `quantileExact` | ~1% | низкая | медиана, p95, p99 |
| `quantilesTDigest` | `quantilesExact` | ~1% | низкая | несколько квантилей сразу |
| `topK` | — | приближённо | низкая | топ-N частых значений |
| `any` / `anyLast` | — | нет (произвольное) | минимальная | любое значение из группы |
| `groupArray` | — | нет | средняя | массив значений группы |

**Правило:** если точный результат не обязателен (аналитика, дашборды) — используйте приближённые функции. Точные (`uniqExact`, `quantileExact`) — только для финансовых отчётов и малых выборок.

### Оконные функции

```sql
SELECT
    user_id,
    event_time,
    row_number() OVER (PARTITION BY user_id ORDER BY event_time) AS rn,
    lag(event_time) OVER (PARTITION BY user_id ORDER BY event_time) AS prev_time,
    sum(amount) OVER (PARTITION BY user_id ORDER BY event_time) AS running_total
FROM events;
```

**Доступные:** `row_number`, `rank`, `dense_rank`, `lag`, `lead`, `lagInFrame`, `leadInFrame`, `first_value`, `last_value`, `nth_value`, `neighbor`.

### Оптимизация порядка чтения и агрегации

```sql
-- Использовать порядок ORDER BY для чтения (ускоряет ORDER BY + LIMIT)
SELECT * FROM logs ORDER BY event_time DESC LIMIT 100
SETTINGS optimize_read_in_order = 1;

-- Использовать порядок ORDER BY для GROUP BY (ускоряет, когда GROUP BY — префикс ORDER BY)
SELECT service, count() FROM logs GROUP BY service
SETTINGS optimize_aggregation_in_order = 1;
```

`optimize_read_in_order` эффективен, когда запрос фильтрует/сортирует по префиксу ключа сортировки. `optimize_aggregation_in_order` — когда `GROUP BY` совпадает с префиксом `ORDER BY`.

## Предварительные требования

Перед проектированием схемы и внедрением паттернов убедитесь в наличии:

**Оборудование и ОС:**
- Linux (Ubuntu 22.04/24.04, Debian 12, RHEL 9, Rocky/AlmaLinux 9)
- CPU с поддержкой AVX2/AVX-512 (для векторного выполнения SIMD) — рекомендуется для продакшена
- RAM: минимум 32 ГБ на узел для production (64+ ГБ рекомендуется для высококардинальных данных)
- Диски: NVMe SSD для горячих данных; HDD/S3 — для холодных (Tiered Storage)
- Файловая система: XFS (рекомендуется) или ext4 с опциями `noatime,nodiratime`

**Программное обеспечение:**
- ClickHouse 26.8.x (LTS) или 26.9.x (Stable)
- Доступ к `clickhouse-client` для DDL/DML
- Для кластера: ClickHouse Keeper (встроен, не требует отдельного ZooKeeper)

**Настройки ОС (применяются через sysctl):**
```bash
# /etc/sysctl.d/99-clickhouse.conf
fs.file-max = 1000000
vm.max_map_count = 262144
vm.swappiness = 1
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
```

**Лимиты пользователя clickhouse (`/etc/security/limits.d/clickhouse.conf`):**
```text
clickhouse soft nofile 262144
clickhouse hard nofile 262144
clickhouse soft nproc 131072
clickhouse hard nproc 131072
```

**Проверка готовности:**
```bash
# Проверка версии
clickhouse-client --query "SELECT version()"

# Проверка настроек MergeTree
clickhouse-client --query "SELECT name, value FROM system.merge_tree_settings WHERE name IN ('index_granularity', 'max_partitions_per_insert_block') FORMAT Vertical"
```

## Установка и базовая конфигурация

### Быстрый старт (Docker для разработки)

```bash
docker run -d \
    --name clickhouse-dev \
    --ulimit nofile=262144:262144 \
    -p 8123:8123 \
    -p 9000:9000 \
    -v clickhouse-data:/var/lib/clickhouse \
    clickhouse/clickhouse-server:26.9
```

### Production установка (bare metal)

```bash
# Официальный установщик (устанавливает последнюю стабильную)
curl https://clickhouse.com/ | sh

# Включение и запуск
sudo systemctl enable --now clickhouse-server

# Проверка
clickhouse-client --query "SELECT version(), uptime()"
```

### Ключевые конфигурационные файлы

| Файл | Назначение |
|------|------------|
| `/etc/clickhouse-server/config.d/zzz-custom.xml` | Переопределение настроек сервера (не трогать `config.xml`) |
| `/etc/clickhouse-server/users.d/zzz-custom.xml` | Пользователи, роли, квоты, профили настроек |
| `/etc/clickhouse-server/config.d/listen.xml` | `<listen_host>::</listen_host>` для слушания на всех интерфейсах |

**Пример `zzz-custom.xml` для моделей с высокой нагрузкой:**
```xml
<clickhouse>
    <!-- Увеличить лимит памяти на запрос для сложных агрегаций -->
    <max_memory_usage>20000000000</max_memory_usage>  <!-- 20 GB -->
    <max_bytes_before_external_group_by>10000000000</max_bytes_before_external_group_by>  <!-- 10 GB -->
    
    <!-- Настройки слияний -->
    <merge_tree>
        <parts_to_delay_insert>2000</parts_to_delay_insert>
        <parts_to_throw_insert>3000</parts_to_throw_insert>
        <max_partitions_per_insert_block>300</max_partitions_per_insert_block>
    </merge_tree>
    
    <!-- Асинхронные вставки для батчинга на стороне сервера -->
    <async_insert>1</async_insert>
    <async_insert_threads>16</async_insert_threads>
    <async_insert_max_batch_size>1000000</async_insert_max_batch_size>
    <async_insert_busy_timeout_ms>200</async_insert_busy_timeout_ms>
</clickhouse>
```

## Конфигурация модели данных (DDL шаблоны)

### Базовый шаблон для time-series / observability

```sql
CREATE TABLE IF NOT EXISTS {table_name} (
    timestamp DateTime64(3),
    service_name LowCardinality(String),
    -- Высококардинальные поля — отдельно, без LowCardinality
    trace_id String,
    span_id String,
    -- Метрики
    duration_ms UInt32,
    status_code UInt16,
    -- Гибкие атрибуты
    attributes Map(LowCardinality(String), String)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (service_name, timestamp)
TTL timestamp + INTERVAL 30 DAY DELETE
SETTINGS index_granularity = 8192;
```

### Шаблон для событий с сессиями / воронками

```sql
CREATE TABLE IF NOT EXISTS user_events (
    event_time DateTime64(3),
    user_id UInt64,
    event_type LowCardinality(String),
    event_name LowCardinality(String),
    properties Map(LowCardinality(String), String),
    -- Для sessionization: нужен ORDER BY (user_id, event_time)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (user_id, event_time)
TTL event_time + INTERVAL 90 DAY DELETE
SETTINGS index_granularity = 8192;
```

### Шаблон для предварительно агрегированных метрик (downsampling)

```sql
CREATE TABLE IF NOT EXISTS metrics_hourly (
    hour DateTime,
    metric_name LowCardinality(String),
    labels Map(LowCardinality(String), String),
    value_sum Float64,
    value_min Float64,
    value_max Float64,
    value_cnt UInt64
) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (metric_name, hour)
TTL hour + INTERVAL 365 DAY DELETE
SETTINGS index_granularity = 8192;
```

## Валидация схемы и проверка работоспособности

После создания таблиц выполните следующие проверки:

### 1. Проверка структуры таблицы

```sql
-- Структура колонок
DESCRIBE TABLE metrics;

-- Настройки движка
SELECT name, value FROM system.merge_tree_settings 
WHERE name IN ('index_granularity', 'max_partitions_per_insert_block') 
FORMAT Vertical;
```

### 2. Тестовая вставка и проверка ORDER BY

```sql
-- Вставка тестовых данных
INSERT INTO metrics VALUES
    (now(), 'api-gateway', 120, 200),
    (now() - 60, 'auth-service', 45, 200),
    (now() - 120, 'db-proxy', 500, 504);

-- Проверка: чтение должно использовать индекс (IndexOf в EXPLAIN)
EXPLAIN SYNTAX SELECT * FROM metrics WHERE service_name = 'api-gateway' AND timestamp > now() - INTERVAL 1 HOUR;

-- Ожидаемый результат: в плане видно IndexOf / PrimaryKey
```

### 3. Проверка сжатия и размера

```sql
-- Размер таблицы и коэффициент сжатия
SELECT 
    table,
    formatReadableSize(sum(bytes_on_disk)) AS size_on_disk,
    formatReadableSize(sum(data_compressed_bytes)) AS compressed,
    formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed,
    round(sum(data_uncompressed_bytes) / sum(data_compressed_bytes), 2) AS compression_ratio
FROM system.parts
WHERE active AND database = currentDatabase() AND table = 'metrics'
GROUP BY table;
```

### 4. Проверка Partiционирования

```sql
-- Список партиций и их размер
SELECT 
    partition,
    formatReadableSize(sum(bytes_on_disk)) AS size,
    count() AS parts_count
FROM system.parts
WHERE active AND database = currentDatabase() AND table = 'metrics'
GROUP BY partition
ORDER BY partition;
```

### 5. Бенчмарк типичных запросов

```sql
-- 1. Фильтр по service + время (должен использовать PRIMARY KEY)
SELECT count() FROM metrics 
WHERE service_name = 'api-gateway' 
  AND timestamp > now() - INTERVAL 1 HOUR;

-- 2. Агрегация по service (должен использовать optimize_aggregation_in_order)
SELECT service_name, count(), avg(duration_ms) 
FROM metrics 
WHERE timestamp > now() - INTERVAL 1 HOUR 
GROUP BY service_name 
SETTINGS optimize_aggregation_in_order = 1;

-- 3. Приближённый подсчёт уникальных пользователей
SELECT uniqCombined(user_id) FROM user_events 
WHERE event_time > now() - INTERVAL 1 DAY;
```

**Критерии успеха:**
- Запрос 1: < 10 мс на 1 млн строк (использует индекс)
- Запрос 2: < 100 мс на 10 млн строк
- Запрос 3: < 500 мс на 100 млн строк, RAM < 1 ГБ

## Граничные случаи и ограничения

| Сценарий | Ограничение | Обходное решение |
|----------|-------------|------------------|
| **UPDATE/DELETE по PK** | MergeTree не поддерживает эффективные точечные обновления | Использовать `ReplacingMergeTree` (дедуп при слиянии) или `CollapsingMergeTree` (состояние + sign) |
| **JOIN больших таблиц** | Распределённый JOIN потребляет много RAM/сети | Денормализовать заранее; использовать `join_use_nulls=1`, `max_rows_in_join`; External JOIN для справочников |
| **Высокая кардинальность в PK** | `user_id`, `trace_id` в PRIMARY KEY → раздувание разреженного индекса | Вынести высококардинальные поля из PK; использовать `bloom_filter` индексы на этих колонках |
| **Слишком частые вставки (микробатчи)** | `Too many parts` (Code 252) | Включить `async_insert=1`; батчить на клиенте ≥10k строк; увеличить `parts_to_delay_insert` |
| **TTL не срабатывает сразу** | TTL применяется только при слиянии (merge) | `ALTER TABLE ... MATERIALIZE TTL` для принудительного применения; настроить `merge_with_ttl_timeout` |
| **SAMPLE на неравномерных данных** | `SAMPLE BY user_id` даёт смещение, если пользователи неравномерны | Использовать `SAMPLE BY` по равномерно распределённому полю (hash от user_id) |
| **windowFunnel на больших окнах** | Окно > суток требует много RAM для хранения состояния | Ограничивать окно; предварительно фильтровать пользователей; использовать `funnel_steps_limit` |
| **Материализованные представления + ReplacingMergeTree** | MV не видит дедупликацию в целевой таблице | Использовать `AggregatingMergeTree` + `sumMap`/`uniqState` в MV; или refreshable MV для пересчёта |
| **Колонка JSON с высокой кардинальностью** | Каждый уникальный путь в JSON создаёт подколонку | Ограничивать известные пути; использовать `JSON` тип (v24.8+) с автоматическим выводом схемы |
| **Размер гранулы по умолчанию (8192)** | На маленьких таблицах гранула больше таблицы → индекс бесполезен | Для таблиц < 10M строк можно уменьшить `index_granularity` до 1024/2048 |

## Практические сценарии

### LIMIT BY: лучшая строка в группе

```sql
-- Последнее событие каждого пользователя
SELECT * FROM events ORDER BY event_time DESC LIMIT 1 BY user_id;

-- Топ-3 события по длительности для каждого сервиса
SELECT service, event, duration FROM events ORDER BY duration DESC LIMIT 3 BY service;
```

### SAMPLE: быстрая оценка на больших данных

```sql
-- Требуется SAMPLE BY в определении таблицы:
-- ORDER BY (event_time, user_id) SAMPLE BY user_id

-- 10% выборка
SELECT count(), avg(amount) FROM events SAMPLE 0.1;

-- Выборка со смещением (для кросс-валидации)
SELECT count() FROM events SAMPLE 0.1 OFFSET 0.5;
```

**Важно:** `SAMPLE` работает только для таблиц с `SAMPLE BY` в определении и только для `MergeTree`-семейства. Выборка детерминирована (одна и та же доля при повторных запросах).

### WITH TOTALS: итоги по GROUP BY

```sql
SELECT service, count() AS cnt, sum(amount) AS total
FROM events
GROUP BY service
WITH TOTALS
ORDER BY cnt DESC;
```

`totals_mode` управляет способом расчёта итогов (`before_having`, `after_having_exclusive`, `after_having_inclusive`, `after_having_auto`).

### GLOBAL IN: корректный подзапрос на шардах

```sql
-- Без GLOBAL: каждый шард выполняет подзапрос локально (неполные данные)
SELECT * FROM distributed_events WHERE user_id IN (SELECT id FROM users_local);

-- С GLOBAL: подзапрос выполняется на инициаторе и результат отправляется на шарды
SELECT * FROM distributed_events WHERE user_id GLOBAL IN (SELECT id FROM users_local);
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `GROUP BY` по user_id медленный / не хватает RAM | Высокая кардинальность | `uniqCombined` вместо `uniqExact`; `topK` вместо полного `GROUP BY`; увеличить `max_bytes_before_external_group_by` |
| `SELECT ... FINAL` медленный | Движок обрабатывает части особым образом | Избегать `FINAL`; использовать `argMax`/`anyLast` или дедупликацию в MV |
| Сессии некорректны | Неверный тайм-аут или `lagInFrame` без `ORDER BY` | Проверить `PARTITION BY ... ORDER BY` в оконной функции |
| `SAMPLE` не работает | Нет `SAMPLE BY` в определении таблицы | Добавить `SAMPLE BY` при создании таблицы |
| `windowFunnel` возвращает 0 | События не в нужном порядке или вне окна | Проверить порядок условий и размер окна |
| `optimize_read_in_order` не ускоряет | Запрос не фильтрует по префиксу `ORDER BY` | Пересмотреть ключ сортировки под паттерн запросов |
| Слишком много партиций | `toYYYYMMDD` или высококардинальный `PARTITION BY` | Укрупнить партиции; `OPTIMIZE TABLE ... FINAL` после изменения |
| `Too many parts` (Code 252) | Частые мелкие вставки; слияния не успевают | `async_insert=1`; батчинг ≥10k строк; увеличить `parts_to_delay_insert` |
| Медленная вставка / высокое CPU на слияниях | Мелкие батчи, неоптимальный `ORDER BY` | Бачить данные; подобрать `ORDER BY` под селективность; проверить `system.merges` |
| Реплика в read-only / данные расходятся | Потеря связи с Keeper; сбой репликации | Проверить `system.replicas`; `SYSTEM SYNC REPLICA`; `SYSTEM RESTORE REPLICA` |
| Рост диска несмотря на TTL | TTL применяется только при merge; нет места для merge | `ALTER TABLE ... MATERIALIZE TTL`; добавить диск через Tiered Storage; очистить `system.parts` detached |
| `Memory limit exceeded` (Code 241) | Запрос превысил `max_memory_usage` | Добавить `PREWHERE`; увеличить `max_bytes_before_external_group_by`; использовать approximate функции |
| Некорректные агрегаты в SummingMergeTree | Дубликаты не схлопнулись (нет FINAL merge) | `OPTIMIZE TABLE ... FINAL` для форсирования; читать через `GROUP BY` + `sum()` |
| Bloom filter не помогает | Индекс не построен / кардинальность слишком высока | `ALTER TABLE ... ADD INDEX ... TYPE bloom_filter`; пересоздать таблицу с индексом |

## Лучшие практики (DevOps/SRE фокус)

### Проектирование схемы
1. **Денормализуйте.** Широкая таблица с дублированием атрибутов — стандартная модель ClickHouse.
2. **`ORDER BY` под паттерн запросов** — фильтрующие колонки первыми, время последним (или наоборот, по селективности).
3. **Месячные партиции** (`toYYYYMM`) — не ежедневные, если только данных очень много (>100M строк/день).
4. **`LowCardinality(String)`** для строк с малым числом уникальных значений (до ~1000 уникальных значений).
5. **Приближённые функции** для аналитики (`uniqCombined`, `quantileTDigest`, `topK`); точные — только для финансовых отчётов.
6. **Высококардинальные поля (trace_id, user_id) — вне PRIMARY KEY.** Используйте `bloom_filter` индексы для фильтрации.
7. **TTL на уровне таблицы** — автоматическое удаление/перемещение старых данных предотвращает неконтролируемый рост диска.

### Эксплуатация и мониторинг
8. **`LIMIT BY`** вместо подзапросов для «лучшая строка в группе».
9. **`GLOBAL IN`** для подзапросов к Distributed-таблицам.
10. **`SAMPLE`** для быстрой оценки на больших таблицах (при наличии `SAMPLE BY`).
11. **`optimize_read_in_order` / `optimize_aggregation_in_order`** — включайте для запросов по префиксу `ORDER BY`.
12. **`windowFunnel`** для воронок, `lagInFrame` + `sum() OVER` для сессий.

### Capacity Planning и автоматизация
13. **Downsampling по расписанию** — cron/systemd timer или refreshable MV для агрегации 1m→1h→1d.
14. **Мониторинг `system.parts`** — рост `parts_count` без снижения = проблема с батчингом или слияниями.
15. **Мониторинг `system.merges`** — зависшие слияния блокируют освобождение места и TTL.
16. **Алерты SRE:**
    - `ClickHousePartsCount > 5000` на таблицу
    - `ClickHouseMergeQueueLength > 10` 
    - `ClickHouseDiskUsage > 80%`
    - `ClickHouseQueryDurationP99 > 5s`
17. **Бэкап схемы** — храните DDL в Git; `clickhouse-client --query "SHOW CREATE TABLE ..."` в CI/CD.
18. **Тестирование схемы** — прогоняйте `EXPLAIN` и бенчмарки на staging с production-like объёмами перед ролл-аутом.

### Обслуживание
19. **`OPTIMIZE TABLE ... FINAL` только по требованию** — не по расписанию. Фоновые слияния справляются сами.
20. **`ALTER TABLE ... MATERIALIZE TTL`** после изменения TTL или для принудительной очистки.
21. **Ротация логов ClickHouse** — настройте logrotate для `/var/log/clickhouse-server/` (макс 100МБ, 30 дней).
22. **План восстановления (DR)** — документируйте RPO/RTO; тестируйте `BACKUP/RESTORE` и `FREEZE/FETCH` раз в квартал.

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- Архитектура и MergeTree — **[Архитектура](./clickhouse-architecture.md)**.
- Кодеки и сжатие — **[Производительность](./clickhouse-performance.md#сжатие-и-кодеки)**.
- Materialized Views — **[Производительность](./clickhouse-performance.md#материализованные-представления-materialized-views)**.
- Refreshable MV — **[Производительность](./clickhouse-performance.md#refreshable-materialized-views)**.
- Кластерное управление (репликация, шардирование) — **[Кластерное управление](./clickhouse-cluster.md)**.
- Операционный SQL (OPTIMIZE, DELETE, TTL, FREEZE) — **[Операционный SQL](./clickhouse-sql-operations.md)**.
- Эволюция схемы (ALTER, CONSTRAINTS) — **[Эволюция схемы](./clickhouse-schema-evolution.md)**.
- Наблюдаемость (логи, метрики, трейсы, downsampling) — **[Наблюдаемость](./clickhouse-observability.md)**.
- Tiered Storage и S3 — **[Интеграция S3](./clickhouse_s3_integration.md)**.
- Интеграция Kafka — **[Интеграция Kafka](./clickhouse_kafka_integration.md)**.
- Бэкапы и восстановление — **[Бэкапы](./clickhouse-backup.md)**.
- Capacity Planning и HA — **[Capacity Planning](./clickhouse-capacity-upgrades.md)**.
- Файловая система и хранение — **[Файловая система](./clickhouse-filesystem-storage.md)**.
- Полнотекстовый поиск — **[Полнотекстовый поиск](./clickhouse-full-text-search.md)**.
- Высокая конкурентность — **[Высокая конкурентность](./clickhouse-high-concurrency.md)**.

### Ресурсы

- [Документация: windowFunnel](https://clickhouse.com/docs/ru/sql-reference/functions/window-functions)
- [Документация: приближённые функции](https://clickhouse.com/docs/ru/sql-reference/functions/approximate-functions)
- [Документация: SAMPLE](https://clickhouse.com/docs/ru/sql-reference/statements/select/sample-by)
- [Документация: TTL](https://clickhouse.com/docs/ru/engines/table-engines/mergetree-family/mergetree#ttl)
- [Документация: Materialized Views](https://clickhouse.com/docs/ru/sql-reference/statements/create/view)
- [Документация: CHECK/ASSUME constraints](https://clickhouse.com/docs/ru/sql-reference/statements/alter/constraint)
- [Документация: MergeTree settings](https://clickhouse.com/docs/ru/operations/settings/merge-tree-settings)
- [Документация: Downsampling с TTL GROUP BY](https://clickhouse.com/docs/ru/engines/table-engines/mergetree-family/mergetree#ttl-group-by)
- [ClickHouse Performance Tuning Guide](https://clickhouse.com/docs/ru/guides/performance)
- [ClickHouse Data Modeling Best Practices](https://clickhouse.com/docs/ru/guides/data-modeling)
