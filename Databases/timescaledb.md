# TimescaleDB

## Определения

**TimescaleDB** — это расширение (extension) для PostgreSQL, которое превращает его в полноценную базу данных временных рядов (time-series database). Оно оптимизировано для хранения и анализа данных, привязанных ко времени.

**Текущая версия:** TimescaleDB 2.25 (январь 2026).

**Временные ряды (Time-Series Data):** Данные, которые изменяются во времени — метрики мониторинга, данные с IoT-устройств, финансовые котировки, логи событий.

## Основные концепции

### Архитектура: Гипертаблицы и Чанки

**Гипертаблица (Hypertable)** — абстракция над множеством обычных таблиц PostgreSQL, называемых **чанками (chunks)**. Для пользователя выглядит как единая таблица.

**Чанк (Chunk)** — внутренняя дочерняя таблица, в которой физически хранятся данные за определённый промежуток времени и/или для определённого ключа (например, ID устройства).

**Принцип работы:**

1. Создаётся обычная таблица PostgreSQL
2. Вызывается `create_hypertable()` для преобразования в гипертаблицу
3. TimescaleDB автоматически создаёт и управляет чанками
4. Запросы к гипертаблице прозрачно распределяются по чанкам

**Преимущества:**

- Простота работы с единой таблицей
- Автоматическое партиционирование по времени
- Возможность дополнительного разбиения по пространственному ключу (space partitioning)
- Все преимущества экосистемы PostgreSQL

### Ключевые особенности

| Функция | Описание |
| :--- | :--- |
| **Автоматическое партиционирование** | Создание и управление чанками по времени и другим измерениям |
| **Специализированные функции** | `time_bucket`, `first`, `last`, `histogram`, `interpolate` |
| **Непрерывные агрегаты** | Автоматически обновляемые материализованные представления |
| **Сжатие данных** | Колоночное сжатие для старых данных (до 90% экономии) |
| **Политики управления** | Автоматическое удаление или сжатие старых данных |
| **Гипертаблицы** | Прозрачное распределение данных по чанкам |

### Непрерывные агрегаты (Continuous Aggregates)

Материализованные представления, которые автоматически обновляются при вставке новых данных:

```sql
-- Создание непрерывного агрегата
CREATE MATERIALIZED VIEW hourly_metrics
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    device_id,
    AVG(cpu_usage) AS avg_cpu
FROM device_metrics
GROUP BY bucket, device_id;

-- Запрос к агрегату (автоматически использует предрасчитанные данные)
SELECT * FROM hourly_metrics
WHERE bucket > NOW() - INTERVAL '7 days';
```

### Сжатие данных

TimescaleDB поддерживает колоночное сжатие для старых данных:

```sql
-- Включение сжатия для гипертаблицы
ALTER TABLE device_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id'
);

-- Добавление политики сжатия (сжимать данные старше 7 дней)
SELECT add_compression_policy('device_metrics', INTERVAL '7 days');
```

**Преимущества:**

- Экономия места до 90%
- Ускорение запросов к сжатым данным
- Прозрачное сжатие/расжатие для приложений

### Политики управления данными

Автоматизация рутинных задач:

```sql
-- Удаление данных старше 30 дней
SELECT add_retention_policy('device_metrics', INTERVAL '30 days');

-- Сжатие данных старше 7 дней
SELECT add_compression_policy('device_metrics', INTERVAL '7 days');

-- Реорганализация чанков (оптимизация)
SELECT add_reorder_policy('device_metrics', index_name => 'device_metrics_time_idx');
```

## Практические сценарии

### Установка и активация

**Установка через apt (Debian/Ubuntu):**

```bash
# Добавление репозитория Timescale
sudo add-apt-repository ppa:timescale/timescaledb-ppa
sudo apt update

# Установка TimescaleDB для PostgreSQL 16
sudo apt install timescaledb-2-loader-postgresql-16

# Инициализация
sudo timescaledb-tune

# Перезапуск PostgreSQL
sudo systemctl restart postgresql
```

**Активация расширения:**

```sql
-- В каждой базе данных, где нужен TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;
```

### Создание гипертаблицы

```sql
-- 1. Создание обычной таблицы
CREATE TABLE device_metrics (
    time TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL,
    cpu_usage DOUBLE PRECISION,
    memory_usage DOUBLE PRECISION,
    disk_io BIGINT
);

-- 2. Преобразование в гипертаблицу
-- Разбиение на чанки по 7 дней
SELECT create_hypertable(
    'device_metrics',
    'time',
    chunk_time_interval => INTERVAL '7 days'
);

-- 3. Создание индексов
CREATE INDEX ON device_metrics (device_id, time DESC);
```

### Вставка и запрос данных

```sql
-- Вставка (стандартный INSERT)
INSERT INTO device_metrics(time, device_id, cpu_usage, memory_usage)
VALUES 
    (NOW(), 'device-001', 85.5, 76.2),
    (NOW(), 'device-002', 42.1, 58.9);

-- Запрос с time_bucket (аналог GROUP BY для временных интервалов)
SELECT
    time_bucket('5 minutes', time) AS five_min,
    device_id,
    AVG(cpu_usage) AS avg_cpu,
    MAX(memory_usage) AS max_mem
FROM device_metrics
WHERE time > NOW() - INTERVAL '1 day'
GROUP BY five_min, device_id
ORDER BY five_min DESC;

-- Запрос с функциями TimescaleDB
SELECT
    time_bucket('1 hour', time) AS hour,
    first(cpu_usage, time) AS first_cpu,
    last(cpu_usage, time) AS last_cpu,
    avg(cpu_usage) AS avg_cpu
FROM device_metrics
WHERE device_id = 'device-001'
  AND time > NOW() - INTERVAL '7 days'
GROUP BY hour;
```

### Мониторинг и обслуживание

```sql
-- Просмотр информации о гипертаблице
SELECT * FROM timescaledb_information.hypertables;

-- Просмотр чанков
SELECT * FROM timescaledb_information.chunks 
WHERE hypertable_name = 'device_metrics';

-- Статистика сжатия
SELECT 
    hypertable_name,
    compressed,
    total_bytes,
    compressed_bytes,
    compression_ratio
FROM timescaledb_information.compressed_hypertable_stats;

-- Размер гипертаблицы
SELECT hypertable_size('device_metrics');
```

## Дополнительная информация

### Сравнение с альтернативами

| Система | Тип | Назначение | Особенности |
| :--- | :--- | :--- | :--- |
| **TimescaleDB** | Extension для PostgreSQL | Временные ряды + реляционные данные | Полная совместимость с PostgreSQL |
| **[ClickHouse](./clickhouse.md)** | OLAP-СУБД | Аналитика, временные ряды | Высокая производительность, колоночное хранение |
| **[Prometheus](../Prometheus/overview.md)** | TSDB | Метрики мониторинга | Pull-модель, PromQL |
| **[VictoriaMetrics](../VictoriaMetrics/overview.md)** | TSDB | Долгосрочное хранение метрик | Совместимость с Prometheus |

### Преимущества интеграции с PostgreSQL

- **Надёжность:** Проверенная временем СУБД с ACID-гарантиями
- **Гибкость:** Временные ряды + реляционные данные + JSONB в одной базе
- **Совместимость:** Все инструменты PostgreSQL (pg_dump, репликация, бэкапы)
- **SQL:** Полная поддержка SQL, включая сложные JOIN и подзапросы

### Ограничения

- **Оверхеад расширения:** Небольшая дополнительная нагрузка по сравнению с ванильным PostgreSQL
- **Сложность шардирования:** Для горизонтального масштабирования требуется дополнительное решение
- **Версия PostgreSQL:** Может отставать от последней версии PostgreSQL

### Примеры использования

- **Мониторинг:** Хранение метрик производительности систем и приложений
- **IoT:** Сбор и анализ данных с сенсоров и устройств
- **Финансовый анализ:** Хранение биржевых котировок, транзакций
- **Логирование:** Анализ логов событий во времени
- **Метрики приложений:** APM-системы, трассировка запросов

### Смежные темы

- Масштабирование PostgreSQL — **[PostgreSQL Scaling](./PostgreSQL/Concepts/scaling.md)**
- Партиционирование в PostgreSQL — **[PostgreSQL Scaling: Partitioning](./PostgreSQL/Concepts/scaling.md)**
- Альтернативы для аналитики — **[ClickHouse](./clickhouse.md)**, **[Greenplum](./greenplum.md)**
- Мониторинг с Prometheus — **[Prometheus Overview](../Prometheus/overview.md)**
- Долгосрочное хранение метрик — **[VictoriaMetrics](../VictoriaMetrics/overview.md)**
