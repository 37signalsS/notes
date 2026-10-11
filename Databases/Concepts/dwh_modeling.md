**Актуально для:** Kimball Dimensional Modeling (3rd ed.) / ClickHouse 26.9.x (Stable) / 26.8.x (LTS) / Greenplum 7.x (Tanzu Greenplum 7.5.x) / dbt 1.8+ / Apache Airflow 2.9+ (2024–2026)

# Моделирование хранилища данных: star schema, SCD, ETL

## Определения

**Data Warehouse (DWH, хранилище данных)** — централизованное хранилище исторических данных из множества источников, оптимизированное для аналитических запросов (OLAP), а не для транзакций (OLTP).

**OLAP vs OLTP:** OLTP — много коротких транзакций, нормализованная схема, запись; OLAP — сложные агрегации по историческим данным, денормализованная схема, чтение.

**Fact table (таблица фактов)** — центральная таблица звезды: измерения (метрики: сумма, количество) + FK на таблицы измерений. Одна строка = одно бизнес-событие на заданном grain.

**Dimension table (таблица измерений)** — контекст фактов: кто, что, где, когда. Денормализована (много текстовых атрибутов) для удобства фильтрации и группировки.

**Grain (зерно)** — уровень детализации строки факта: «одна строка = одна продажа» / «одна строка = день по магазину». Объявляется первым при моделировании.

**Star schema (звезда)** — схема: факт в центре, измерения вокруг, без нормализации измерений. Стандарт Kimball.

**Snowflake schema (снежинка)** — измерения нормализованы (разложены на подтаблицы). Kimball рекомендует избегать: сложнее для бизнес-пользователей, больше JOIN, выигрыш по месту обычно не оправдан.

**Conformed dimension (согласованное измерение)** — измерение, одинаковое по смыслу и ключам во всех фактах (например, `dim_date`). Позволяет «drill across» — объединять факты разных процессов по общим измерениям.

**Bus matrix (матрица шины)** — таблица: строки = бизнес-процессы (факты), столбцы = согласованные измерения. План интеграции DWH.

**Surrogate key в DWH** — системный ключ измерения (обычно `INT IDENTITY`), отделяющий историю версий от natural key бизнеса.

**SCD (Slowly Changing Dimension)** — методика обработки изменений атрибутов измерений во времени (Kimball, типы 0–7).

**ETL / ELT** — Extract-Transform-Load (трансформация до загрузки) vs Extract-Load-Transform (загрузка сырых данных, трансформация в хранилище — MPP-архитектуры: ClickHouse, Greenplum, Snowflake).

## Предварительные требования

Перед внедрением DWH-моделирования убедитесь в наличии:

1. **Инфраструктура хранилища:**
   - ClickHouse 26.8.x LTS / 26.9.x Stable (кластер или single-node) ИЛИ Greenplum 7.x (Tanzu Greenplum 7.5.x) кластер
   - Достаточный дисковый объём: данные должны превышать RAM в 2–3× для реалистичных тестов (см. **[Benchmarking](./benchmarking.md)**)
   - Партиционирование по дате настроено (**[Partitioning](./partitioning.md)**)

2. **Инструменты трансформации:**
   - dbt Core 1.8+ или dbt Cloud для ELT-конвейеров
   - Apache Airflow 2.9+ / Dagster / Prefect для оркестрации
   - Среда CI/CD для проверки миграций схем

3. **Источники данных:**
   - Доступ к OLTP-источникам (PostgreSQL, MySQL) с включенным CDC (Debezium — **[CDC-архитектуры](./cdc_architectural_patterns.md)**)
   - Определённые watermark'и / LSN для инкрементальной загрузки
   - Согласованные natural keys в источниках

4. **Команда и процессы:**
   - Data Engineer / Analytics Engineer для разработки моделей
   - Согласованный Business Glossary (определения метрик, grain)
   - Процесс код-ревью для DDL и dbt-моделей

5. **Мониторинг и SLA:**
   - Prometheus + Grafana для метрик загрузки (lag, row count, duration)
   - Алерты на SLA: freshness < 1ч, row count drift < 5%, load duration < baseline × 1.5

## Основные концепции

### Методология Kimball: 4 шага

1. **Выбрать бизнес-процесс** (продажи, поддержка, логистика).
2. **Объявить grain** — максимально детальный уровень («одна строка = один скан штрих-кода на кассе»). Нельзя смешивать зерна в одной таблице фактов.
3. **Определить измерения** (date, product, store, customer, cashier).
4. **Определить факты** (quantity, amount, discount).

### Типы фактов

| Тип | Свойство | Пример |
| :--- | :--- | :--- |
| **Additive** | суммируется по всем измерениям | amount, quantity |
| **Semi-additive** | суммируется по некоторым измерениям, но не по времени | остаток на складе (нельзя суммировать по дням) |
| **Non-additive** | не суммируется | температура, ratio, % |

**Типы fact table по процессу:**
- **Transaction fact** — одно событие (продажа). Максимальная детализация.
- **Periodic snapshot** — состояние за период (остаток на конец дня). Для semi-additive.
- **Accumulating snapshot** — процесс с этапами (заказ → оплата → доставка), даты этапов в колонках, строка обновляется.

**Degenerate dimension** — атрибут факта без своей таблицы (номер чека, номер заказа): хранится прямо в fact table.

**Junk dimension** — набор флагов/низкокардинальных атрибутов (is_paid, channel, device) в одной компактной таблице вместо десятков отдельных.

**Role-playing dimension** — одна физическая таблица играет несколько ролей (`dim_date` как order_date, ship_date, due_date) через разные FK и view-алиасы.

### SCD — типы (Kimball)

| Тип | Механизм | История | Когда применять |
| :--- | :--- | :--- | :--- |
| **Type 0: Retain original** | значение никогда не меняется | исходное значение навсегда | «оригинальный» атрибут: первый кредитный скоринг, дата регистрации |
| **Type 1: Overwrite** | старое значение перезаписывается | нет | исправление ошибок; атрибуты, история которых не нужна |
| **Type 2: Add new row** | новая строка с новыми датами `effective_from`/`effective_to` + `is_current` | полная | стандарт для истории: адрес, категория товара |
| **Type 3: Add new column** | колонка `previous_value` + `current_value` | только предыдущее | «альтернативная реальность»: сравнение «было/стало» (редко) |
| **Type 4: Mini-dimension** | быстро меняющиеся атрибуты выносятся в отдельную таблицу | полная (в mini-dim) | группа волатильных атрибутов (доход, кредитный класс) |
| **Type 5: Mini-dim + Type 1 outrigger** | Type 4 + ссылка на «текущий» профиль в базовой таблице | полная + текущий срез | отчёты «as-is» и «as-was» |
| **Type 6: Hybrid** | Type 2 + Type 1: текущие значения дублируются на всех исторических строках | полная + текущий срез на каждой строке | самый частый компромисс: одна таблица для «as-is» и «as-was» |
| **Type 7: Dual 1/2** | две версии измерения (Type 1 и Type 2) через один view | полная | редко; сложность поддержки |

**Type 2 — ключевые поля:** `surrogate_key` (новый на каждую версию), `natural_key` (бизнес-ключ, общий для версий), `effective_from`, `effective_to` (конец = начало следующей версии), `is_current` (флаг), `version`.

**Surrogate key обязателен для Type 2:** natural key не меняется между версиями, поэтому PK таблицы измерения — surrogate.

### ETL vs ELT

| | ETL | ELT |
| :--- | :--- | :--- |
| **Трансформация** | в промежуточном движке до загрузки | внутри хранилища после загрузки |
| **Подходит для** | сложные трансформации, чувствительные данные | MPP/columnar-хранилища (ClickHouse, Greenplum) |
| **Паттерн** | staging → transform → DWH | raw → DWH → dbt/SQL-трансформации |

**CDC как источник:** изменения из OLTP в DWH — через CDC (Debezium + Kafka), см. **[CDC-архитектуры](./cdc_architectural_patterns.md)**.

## Практические сценарии

### Сценарий 1: Star schema для розничных продаж

```sql
-- Измерения (денормализованные)
CREATE TABLE dim_date (
    date_key    integer PRIMARY KEY,      -- 20260101
    full_date   date NOT NULL,
    year        smallint, month smallint, day smallint,
    quarter     smallint, weekday smallint, is_holiday boolean
);

CREATE TABLE dim_product (
    product_key integer PRIMARY KEY,      -- surrogate
    sku         text NOT NULL,            -- natural key
    name        text, category text, brand text,
    price_cents integer,
    effective_from date, effective_to date, is_current boolean  -- SCD Type 2
);

CREATE TABLE dim_store (
    store_key   integer PRIMARY KEY,
    store_id    text NOT NULL,
    city text, region text, country text, format text
);

-- Факт
CREATE TABLE fact_sales (
    date_key        integer REFERENCES dim_date(date_key),
    product_key     integer REFERENCES dim_product(product_key),
    store_key       integer REFERENCES dim_store(store_key),
    quantity        integer NOT NULL,
    amount_cents    bigint NOT NULL,      -- additive fact
    discount_cents  bigint NOT NULL,
    receipt_id      text                  -- degenerate dimension
);
-- Индексы/партиционирование по date_key (см. partitioning.md)
```

**Запрос «продажи по категориям за квартал»:**
```sql
SELECT p.category, d.quarter, sum(f.amount_cents)
FROM fact_sales f
JOIN dim_product p ON p.product_key = f.product_key
JOIN dim_date d ON d.date_key = f.date_key
WHERE d.year = 2026 AND d.quarter = 1
GROUP BY p.category, d.quarter;
```

### Сценарий 2: SCD Type 2 — обработка изменения

```sql
-- 1. Закрыть текущую версию
UPDATE dim_product
SET effective_to = '2026-10-01', is_current = false
WHERE sku = 'SKU-123' AND is_current = true;

-- 2. Открыть новую версию
INSERT INTO dim_product (sku, name, category, price_cents,
                         effective_from, effective_to, is_current)
VALUES ('SKU-123', 'New Name', 'Electronics', 5990,
        '2026-10-01', '9999-12-31', true);

-- 3. Факты, привязанные к старому surrogate_key, остаются с историческими
--    значениями — «as-was» отчётность сохранена
```

**«As-is» отчёт (текущие значения):**
```sql
SELECT ... FROM fact_sales f JOIN dim_product p
  ON p.product_key = f.product_key AND p.is_current = true;
```

**«As-was» отчёт (на момент продажи):**
```sql
SELECT ... FROM fact_sales f JOIN dim_product p
  ON p.product_key = f.product_key
  AND f.sale_date BETWEEN p.effective_from AND p.effective_to;
```

### Сценарий 3: ELT в ClickHouse

```sql
-- Сырые данные загружаются как есть, трансформация — SQL внутри CH
CREATE TABLE raw.orders (event_time DateTime, data String)
ENGINE = MergeTree ORDER BY event_time;

-- Трансформация в витрину (dbt или SQL-скрипт)
CREATE TABLE analytics.daily_sales ENGINE = SummingMergeTree
ORDER BY (date, store_id) AS
SELECT toDate(event_time) AS date,
       JSONExtractString(data, 'store_id') AS store_id,
       sum(JSONExtractInt(data, 'amount')) AS amount
FROM raw.orders GROUP BY date, store_id;
```

## Операции и команды

### Инкрементальная загрузка

```sql
-- Только новые/изменённые строки с последнего watermark
INSERT INTO fact_sales
SELECT ... FROM staging.sales
WHERE updated_at > :last_watermark;
-- watermark хранится в таблице контроля загрузок
```

### Управление surrogate keys

```sql
-- Выделение новых surrogate keys для входящих natural keys
INSERT INTO dim_product (sku, ..., effective_from, effective_to, is_current)
SELECT s.sku, ..., current_date, '9999-12-31', true
FROM staging.products s
LEFT JOIN dim_product p ON p.sku = s.sku AND p.is_current
WHERE p.sku IS NULL;  -- только новые
```

### ELT-конвейер с dbt (ClickHouse / Greenplum)

**Структура проекта dbt:**
```text
models/
├── staging/          -- сырые данные (raw → staging)
│   ├── stg_orders.sql
│   └── stg_products.sql
├── intermediate/     -- промежуточные трансформации
│   ├── int_sales_enriched.sql
│   └── int_scd2_products.sql
├── marts/            -- витрины (факт/измерения)
│   ├── dim_date.sql
│   ├── dim_product.sql
│   ├── dim_customer.sql
│   └── fact_sales.sql
└── macros/           -- кастомные макросы
    └── generate_surrogate_key.sql
```

**Пример модели измерения SCD Type 2 (dbt):**
```sql
-- models/marts/dim_product.sql
{{ config(
    materialized='incremental',
    unique_key='product_key',
    incremental_strategy='merge',
    merge_update_columns=['name', 'category', 'price_cents', 'effective_to', 'is_current'],
    on_schema_change='sync_all_columns'
) }}

WITH source AS (
    SELECT * FROM {{ ref('stg_products') }}
),
current_dim AS (
    SELECT * FROM {{ this }} WHERE is_current = true
),
changes AS (
    SELECT
        s.sku AS natural_key,
        s.name,
        s.category,
        s.price_cents,
        CASE WHEN c.product_key IS NULL THEN true ELSE false END AS is_new,
        CASE WHEN c.product_key IS NOT NULL AND
                  (c.name <> s.name OR c.category <> s.category OR c.price_cents <> s.price_cents)
             THEN true ELSE false END AS is_changed
    FROM source s
    LEFT JOIN current_dim c ON c.sku = s.sku
    WHERE c.product_key IS NULL
       OR c.name <> s.name OR c.category <> s.category OR c.price_cents <> s.price_cents
),
new_keys AS (
    SELECT
        row_number() OVER (ORDER BY natural_key) + COALESCE((SELECT max(product_key) FROM {{ this }}), 0) AS product_key,
        natural_key, name, category, price_cents,
        CURRENT_DATE AS effective_from,
        DATE '9999-12-31' AS effective_to,
        true AS is_current
    FROM changes WHERE is_new
),
closed_rows AS (
    SELECT product_key, effective_to, is_current
    FROM {{ this }}
    WHERE product_key IN (SELECT product_key FROM changes WHERE is_changed)
      AND is_current = true
),
updated_rows AS (
    SELECT
        c.product_key,
        c.natural_key AS sku,
        c.name, c.category, c.price_cents,
        CURRENT_DATE AS effective_from,
        DATE '9999-12-31' AS effective_to,
        true AS is_current
    FROM changes c
    JOIN {{ this }} d ON d.product_key = c.product_key
    WHERE c.is_changed
)
SELECT * FROM new_keys
UNION ALL
SELECT product_key, sku, name, category, price_cents, effective_from,
       CURRENT_DATE - INTERVAL '1 day' AS effective_to, false AS is_current
FROM closed_rows
UNION ALL
SELECT * FROM updated_rows
```

**Запуск dbt:**
```bash
# Полный запуск (dev)
dbt run --target dev

# Только инкрементальные модели (prod)
dbt run --select marts.* --target prod

# Тесты качества данных
dbt test --target prod
```

### Валидация и верификация загрузки

**1. Проверка количества строк (Row Count Reconciliation):**
```sql
-- Источник vs Стейджинг vs Факт
WITH src AS (SELECT count(*) AS cnt FROM source.orders WHERE order_date = CURRENT_DATE - 1),
     stg AS (SELECT count(*) AS cnt FROM staging.orders WHERE order_date = CURRENT_DATE - 1),
     fact AS (SELECT count(*) AS cnt FROM fact_sales WHERE date_key = toYYYYMMDD(CURRENT_DATE - 1))
SELECT 'source' AS layer, cnt FROM src
UNION ALL SELECT 'staging', cnt FROM stg
UNION ALL SELECT 'fact', cnt FROM fact;
-- → Ожидаемое: source = staging = fact (допуск ±0.1% для late-arriving)
```

**2. Проверка сумм (Control Totals):**
```sql
-- Суммы по additive facts
SELECT
    sum(amount_cents) AS total_amount,
    sum(quantity) AS total_qty,
    count(DISTINCT receipt_id) AS unique_orders
FROM fact_sales
WHERE date_key = toYYYYMMDD(CURRENT_DATE - 1);
-- → Сравнить с отчётом источника за тот же день
```

**3. Проверка SCD Type 2 целостности:**
```sql
-- Нет перекрывающихся диапазонов дат
SELECT sku, count(*) AS overlaps
FROM dim_product
GROUP BY sku, effective_from, effective_to
HAVING count(*) > 1;
-- → Ожидаем: 0 строк

-- Нет разрывов в истории (кроме текущей версии)
SELECT sku, effective_to, LEAD(effective_from) OVER (PARTITION BY sku ORDER BY effective_from) AS next_from
FROM dim_product
WHERE is_current = false
  AND effective_to + INTERVAL '1 day' <> LEAD(effective_from) OVER (PARTITION BY sku ORDER BY effective_from);
-- → Ожидаем: 0 строк (нет gaps)
```

**4. Проверка согласованности измерений (Conformed Dimensions):**
```sql
-- Все факты ссылаются на существующие измерения
SELECT 'fact_sales' AS fact, 'dim_product' AS dim, count(*) AS orphan_rows
FROM fact_sales f
LEFT JOIN dim_product p ON p.product_key = f.product_key
WHERE p.product_key IS NULL
UNION ALL
SELECT 'fact_sales', 'dim_date', count(*)
FROM fact_sales f
LEFT JOIN dim_date d ON d.date_key = f.date_key
WHERE d.date_key IS NULL;
-- → Ожидаем: 0 orphan rows
```

### Мониторинг качества загрузки

```sql
-- Дрейф числа строк: факт vs источник
SELECT 'fact' AS src, count(*) FROM fact_sales
UNION ALL SELECT 'staging', count(*) FROM staging.sales;
-- → расхождение > порога = алерт (см. Prometheus alerting)
```

### Очистка и откат (Cleanup / Rollback)

**Откат неудачной загрузки факта:**
```sql
-- 1. Найти последнюю успешную загрузку по watermark
SELECT max(watermark) FROM load_control WHERE status = 'success';

-- 2. Удалить строки факта, загруженные после watermark
DELETE FROM fact_sales
WHERE load_batch_id > (SELECT max(watermark) FROM load_control WHERE status = 'success');

-- 3. Откатить surrogate keys (если выделялись в рамках батча)
DELETE FROM dim_product
WHERE product_key > (SELECT max(product_key) FROM dim_product WHERE load_batch_id <= :last_good_watermark);

-- 4. Восстановить watermark
UPDATE load_control SET status = 'rolled_back' WHERE load_batch_id = :bad_batch_id;
```

**Очистка старых версий SCD Type 2 (по политике ретеншна):**
```sql
-- Удалить исторические версии старше N лет, оставив только текущую
DELETE FROM dim_product
WHERE is_current = false
  AND effective_to < CURRENT_DATE - INTERVAL '7 years'
  AND product_key NOT IN (
      SELECT DISTINCT product_key FROM fact_sales
      WHERE date_key >= toYYYYMMDD(CURRENT_DATE - INTERVAL '7 years')
  );
-- ВАЖНО: сначала проверить, что никакие факты не ссылаются на удаляемые ключи
```

## Поиск и устранение неисправностей

### Проблема: «drill across» даёт неверные суммы

**Симптомы:** сумма по двум фактам ≠ сумме по каждому отдельно при объединении по измерению.

**Причина:** измерения не согласованы (conformed): разные ключи, разные домены значений, разные grain.

**Решение:** единая `dim_date`/`dim_customer` для всех фактов; bus matrix как контракт; проверка доменов ключей.

### Проблема: late-arriving dimension (опоздавшее измерение)

**Симптомы:** факт ссылается на `product_key`, которого ещё нет в `dim_product` → FK violation или orphan.

**Решение:** «early-arriving fact» обработка: при загрузке факта отсутствующее измерение создаётся автоматически как placeholder-строка (unknown member, `natural_key = 'UNKNOWN'`), обновляется при прибытии измерения.

### Проблема: взрыв таблицы при SCD Type 2

**Симптомы:** `dim_product` растёт в 10× быстрее, чем количество товаров.

**Причина:** атрибут, меняющийся каждый день (цена), вынесен в SCD2-измерение.

**Решение:** волатильные атрибуты — в mini-dimension (Type 4) или в факт (цена на момент продажи — в fact row, как `price_cents` в `order_items` OLTP).

### Проблема: двойной подсчёт при JOIN

**Симптомы:** `sum(amount)` после JOIN с измерением, у которого несколько строк на один ключ, завышен.

**Причина:** fan-out: одна строка факта дублируется при JOIN (не-unique ключ в измерении).

**Решение:** проверка уникальности PK измерения; агрегация до JOIN; `DISTINCT` только при понимании причины.

### Проблема: grain mismatch

**Симптомы:** в fact_sales смешаны строки «продажа» и «возврат» с разными измерениями → некорректные агрегаты.

**Решение:** отдельные fact table для разных grain/процессов; `fact_type` column только если grain одинаков.

### Проблема: параллельная загрузка создаёт дубликаты surrogate keys

**Симптомы:** при параллельном запуске dbt-моделей SCD Type 2 получаются дублирующиеся `product_key` или нарушается уникальность natural key.

**Причина:** `row_number() OVER () + max(product_key)` не атомарен; race condition между параллельными процессами.

**Решение:**
- Использовать централизованный генератор ключей (sequence / таблица-счётчик) с `SELECT nextval()` под блокировкой
- В ClickHouse: `generateUUIDv4()` для surrogate keys + `ReplacingMergeTree` для дедупликации
- В Greenplum: `SERIAL` / `IDENTITY` колонка + `ON CONFLICT DO NOTHING`
- Ограничить параллелизм dbt: `dbt run --threads 1` для моделей с surrogate key generation

### Проблема: late-arriving facts (опоздавшие факты) ломают партиционирование

**Симптомы:** факты за прошедшие месяцы приходят после закрытия партиции → `INSERT` в detached/archived partition fails.

**Причина:** политика TTL закрывает партиции (DROP/DETACH), но источники могут присылать корректировки поздно.

**Решение:**
- `DEFAULT` / `MAXVALUE` партиция как ловушка для поздних данных
- Отложенная архивация: держать последние 2-3 месяца в «горячих» партициях
- Процесс backfill: `INSERT` в исторические партиции через `ATTACH PARTITION` → загрузка → `DETACH`
- Мониторинг: алерт на вставки в `DEFAULT` партицию > порога

### Проблема: производительность запросов падает после добавления новых измерений

**Симптомы:** запросы к fact table замедлились в 3-5× после JOIN с новым измерением.

**Причина:**
- Новое измерение не денормализовано (snowflake вместо star) → лишние JOIN
- Отсутствует индекс на FK в fact table
- Статистика планировщика устарела (`ANALYZE` не запускался)

**Решение:**
- Денормализовать измерение (перевести в star schema)
- Создать индекс на FK колонке fact table (в ClickHouse — `PRIMARY KEY` включает FK; в Greenplum — `CREATE INDEX`)
- Запустить `ANALYZE` / `dbt run-operation grant_select` после загрузки
- Проверить план: `EXPLAIN ANALYZE` — должен быть Partition Pruning + Merge Join / Hash Join

### Проблема: dbt incremental модель пересчитывает всю таблицу вместо инкремента

**Симптомы:** время запуска модели растёт линейно с объёмом данных; логи показывают `full refresh` вместо `merge`.

**Причина:**
- `unique_key` не задан или не уникален
- `incremental_strategy` не подходит (merge vs append vs delete+insert)
- Фильтр `is_incremental()` отсутствует или некорректен

**Решение:**
```sql
-- Правильный паттерн для merge
{{ config(
    materialized='incremental',
    unique_key='surrogate_key',
    incremental_strategy='merge',
    merge_update_columns=['col1', 'col2', 'updated_at']
) }}

SELECT ... FROM source
{% if is_incremental() %}
WHERE updated_at > (SELECT max(updated_at) FROM {{ this }})
{% endif %}
```

### Проблема: данные в materialized view (ClickHouse) расходятся с исходной таблицей

**Симптомы:** `SELECT sum(amount) FROM mv_sales` ≠ `SELECT sum(amount) FROM raw_sales` за тот же период.

**Причина:**
- `POPULATE` при создании MV не захватывает данные, вставленные во время создания
- Mutations (UPDATE/DELETE) в исходной таблице не распространяются на incremental MV
- `JOIN` внутри MV на right-hand таблице не обновляется при изменениях справа

**Решение:**
- Не использовать `POPULATE` на больших таблицах — ручной backfill: `INSERT INTO mv_target SELECT ... FROM source WHERE ...`
- Для изменяемых справочников — использовать `Refreshable Materialized View` с расписанием
- Избегать JOIN на right-hand таблице в incremental MV; использовать Dictionary или денормализацию
- Мониторинг: сравнение `count()` и `sum()` между MV и source каждую загрузку

## Эксплуатация (DevOps / SRE)

### Мониторинг и алертинг

**Ключевые метрики (Prometheus):**
```yaml
# Freshness данных
- dwh_last_load_timestamp_seconds{layer="fact_sales"}
- dwh_freshness_hours = (time() - dwh_last_load_timestamp_seconds) / 3600
  # SLO: < 1h для operational, < 4h для analytical

# Объём и дрейф
- dwh_row_count_total{table="fact_sales", layer="fact"}
- dwh_row_count_drift_ratio = abs(fact - source) / source
  # SLO: < 0.5% (0.005)

# Производительность загрузки
- dwh_load_duration_seconds{table="fact_sales"}
- dwh_load_duration_ratio = current_duration / baseline_duration
  # SLO: < 1.5x baseline

# Качество SCD
- dwh_scd_overlaps_total{table="dim_product"}  # должен быть 0
- dwh_scd_gaps_total{table="dim_product"}      # должен быть 0

# Партиционирование
- dwh_partition_count{table="fact_sales"}
- dwh_default_partition_rows{table="fact_sales"}  # алерт если > 1000
```

**Примеры алертов (Alertmanager / PrometheusRule):**
```yaml
groups:
- name: dwh.rules
  rules:
  - alert: DWHFreshnessBreach
    expr: (time() - dwh_last_load_timestamp_seconds{layer="fact"}) > 3600
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "DWH fact table not updated for > 1h"
      
  - alert: DWHRowCountDrift
    expr: dwh_row_count_drift_ratio > 0.005
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Row count drift > 0.5% between source and fact"
      
  - alert: DWHLoadDurationDegraded
    expr: dwh_load_duration_ratio > 1.5
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Load duration 1.5x baseline - investigate"
      
  - alert: DWHDefaultPartitionGrowing
    expr: dwh_default_partition_rows > 1000
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Default partition accumulating rows - missing partition range"
      
  - alert: DWHSCDIntegrityViolation
    expr: dwh_scd_overlaps_total > 0 OR dwh_scd_gaps_total > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "SCD Type 2 integrity violation - overlapping or gapped ranges"
```

### Capacity Planning

**Расчёт дискового пространства (ClickHouse / Greenplum):**
```
Факт: rows_per_day × avg_row_size_bytes × retention_days × compression_ratio
  Пример: 50M rows/day × 200 bytes × 730 days (2 года) × 0.15 (CH compression) ≈ 1.1 TB

Измерения: dimension_cardinality × avg_dim_row_size × version_factor (SCD2)
  Пример: 1M products × 500 bytes × 5 versions (SCD2) ≈ 2.5 GB

Резерв: +30% на временные файлы, мёрджи, репликацию
```

**Планирование партиций:**
- ClickHouse: партиция на месяц (`toYYYYMM(date)`) → 24 партиции на 2 года
- Greenplum: партиция на месяц → 24 партиции; sub-partition по `region` при необходимости
- Мониторинг: `system.parts` (CH) / `pg_partition_tree` (GP) — размер каждой партиции

**Масштабирование:**
| Нагрузка | Решение ClickHouse | Решение Greenplum |
|----------|-------------------|-------------------|
| Растёт объём данных | Добавить шарды (шардинг по `cityHash64(user_id)`) | Добавить сегменты (rebalance) |
| Растёт конкурентность чтения | Реплики (Keeper/ZooKeeper) + `max_threads` | Resource Queues / Resource Groups |
| Медленные тяжелые JOIN | Denormalize + Materialized Views / Projections | Columnar AO + Bitmap Indexes |
| Late-arriving facts | `DEFAULT` partition + периодический backfill | `DEFAULT` partition + `ALTER TABLE ... EXCHANGE PARTITION` |

### CI/CD для DWH-схем

**Пайплайн проверки (GitLab CI / GitHub Actions):**
```yaml
stages:
  - lint          # sqlfluff, dbt parse
  - test          # dbt test (schema, not_null, unique, relationships)
  - build         # dbt compile → check generated SQL
  - deploy-staging # dbt run --target staging
  - validate      # smoke tests на staging
  - deploy-prod   # dbt run --target prod (manual approval)
```

**Проверки в `dbt test`:**
```yaml
# models/marts/schema.yml
models:
  - name: fact_sales
    tests:
      - dbt_utils.expression_is_true:
          expression: "amount_cents >= 0"
      - dbt_utils.recency:
          field: "sale_date"
          datepart: day
          interval: 2  # данные не старше 2 дней
    columns:
      - name: product_key
        tests:
          - not_null
          - relationships:
              to: ref('dim_product')
              field: product_key
      - name: date_key
        tests:
          - not_null
          - relationships:
              to: ref('dim_date')
              field: date_key
```

### Runbook: инциденты загрузки

| Инцидент | Диагностика | Действия |
|----------|-------------|----------|
| Загрузка зависла > 2h | `pg_stat_activity` / `system.processes` — blocking locks, long-running MERGE | Kill blocker; проверить `max_execution_time`; перезапуск с `--full-refresh` |
| Row count drift > 5% | Сравнить `source → staging → fact` по watermark | Найти пропущенный батч в `load_control`; репрогруз конкретного диапазона |
| SCD overlaps detected | Запрос проверки диапазонов (см. валидацию) | Ручной `UPDATE` для закрытия лишних версий; пересчёт `effective_to` |
| Default partition > 10k rows | `SELECT * FROM fact_sales WHERE partition = 'default'` | Добавить недостающие партиции; backfill в правильные партиции |
| dbt run failed на prod | Логи dbt + `EXPLAIN ANALYZE` падающего запроса | Откат: `dbt run --select +model --target prod --vars '{full_refresh: true}'` на staging, затем prod |

## Лучшие практики

### Моделирование (Kimball)

1. **Grain первым** — до таблиц и колонок. Один grain = одна fact table.
2. **Star schema по умолчанию;** snowflake — только при веской причине (Kimball: избегать).
3. **Conformed dimensions** — единые `dim_date`, `dim_customer` для всех процессов; bus matrix как план.
4. **SCD Type 2 — стандарт для истории;** Type 1 — только для исправлений ошибок.
5. **Surrogate keys** в измерениях; natural key — уникальный индекс, не PK.
6. **Цена/статус на момент события — в факте** (историческая точность), не ссылка на текущее значение.
7. **Партиционирование фактов по дате** (**[Партиционирование](./partitioning.md)**) + агрегатные таблицы для старых данных.
8. **Тест восстановления и сверки** после каждой загрузки (**[Валидация бэкапов](./backup_validation.md)**, **[Benchmarking](./benchmarking.md)**).

### Эксплуатация (DevOps / SRE)

9. **Автоматизированная валидация каждого батча** — row count, control totals, SCD integrity, orphan keys. Никаких ручных проверок.
10. **Метрики freshness и drift в Prometheus** — алерты на SLA (freshness < 1h, drift < 0.5%). Dead man's switch на отсутствие метрик.
11. **Идемпотентность загрузки** — повторный запуск того же батча не создаёт дубликатов (merge по surrogate key, watermark в load_control).
12. **CI/CD для схем** — sqlfluff + dbt parse + dbt test в pipeline; staging deploy перед prod; manual approval для prod.
13. **Capacity planning заранее** — диск под 2 года данных + 30% запас; партиции создавать за 2-3 месяца вперед (pg_partman / CH TTL).
14. **Runbook для типовых инцидентов** — зависшая загрузка, drift, SCD overlaps, default partition growth. Таблица действий для дежурного.
15. **Изоляция сред** — dev/staging/prod в разных БД/схемах/каталогах; маскирование PII на staging (см. **[Анонимизация](../PostgreSQL/Operations/anonymization.md)**).
16. **Документирование решений** — bus matrix в Git (Markdown), ADR для отклонений от Kimball (почему snowflake, почему Type 3), data dictionary в dbt docs.

## Дополнительная информация

### Смежные темы
- **[CDC-архитектуры](./cdc_architectural_patterns.md)** — поставка изменений из OLTP в DWH.
- **[ClickHouse](../ClickHouse/clickhouse.md)** — columnar DWH/OLAP.
- **[Greenplum](../greenplum.md)** — MPP-аналитика на PostgreSQL.
- **[TimescaleDB](../timescaledb.md)** — time-series как DWH для метрик.
- **[Партиционирование](./partitioning.md)** — партиции фактов по дате.
- **[Шардирование](./sharding.md)** — масштабирование аналитики.
- **[Проектирование схемы](./data_modeling.md)** — нормализация (OLTP) vs денормализация (OLAP).
- **[Материализованные представления](./materialized_views.md)** — предагрегаты.
- **[SQL vs NoSQL](./sql_vs_nosql.md)** — выбор модели для аналитики.
