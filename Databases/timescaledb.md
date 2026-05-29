# TimescaleDB

## Определения

**TimescaleDB** — это расширение (extension) для СУБД (Система управления базами данных) PostgreSQL, которое превращает ее в полноценную базу данных временных рядов (TSDB — Time-Series Database). Оно оптимизировано для хранения и анализа данных, привязанных ко времени.

**Текущая версия:** TimescaleDB 2.25 (январь 2026).

**Временные ряды (Time-Series Data):** данные, которые последовательно изменяются во времени. Примеры: метрики мониторинга, показатели IoT-устройств (Internet of Things), финансовые котировки, логи событий.

## Основные концепции

### Архитектура: гипертаблицы и чанки

**Гипертаблица (Hypertable)** — это абстракция над множеством обычных таблиц PostgreSQL, называемых **чанками (chunks)**. Для пользователя гипертаблица выглядит как единая большая таблица, но внутри она разбита на части.

**Чанк (Chunk)** — внутренняя дочерняя таблица, в которой физически хранятся данные за определённый промежуток времени и/или для определённого ключа (например, идентификатора устройства).

**Принцип работы:**

1. Создаётся обычная таблица PostgreSQL.
2. Вызывается функция `create_hypertable()` для преобразования в гипертаблицу.
3. TimescaleDB автоматически создаёт новые чанки при поступлении данных и управляет ими.
4. Запросы к гипертаблице прозрачно распределяются по соответствующим чанкам.

**Преимущества такой архитектуры:**

- Высокая скорость вставки данных (Ingestion Rate) за счет работы с небольшими индексами в памяти.
- Автоматическое партиционирование по времени.
- Возможность дополнительного разбиения по пространственному ключу (space partitioning).
- Полная поддержка всей экосистемы и инструментов PostgreSQL.

### Ключевые возможности

| Функция | Описание |
| :--- | :--- |
| **Автоматическое партиционирование** | Создание и управление чанками по времени и другим измерениям. |
| **Специализированные функции** | Набор SQL-функций для аналитики: `time_bucket`, `first`, `last`, `histogram`, `interpolate`. |
| **Непрерывные агрегаты** | Автоматически обновляемые материализованные представления для ускорения запросов. |
| **Колоночное сжатие** | Сжатие старых данных (до 90% экономии места) с возможностью быстрого доступа. |
| **Политики управления** | Автоматизация удаления (Retention) или сжатия устаревших данных. |

### Непрерывные агрегаты (Continuous Aggregates)

Это материализованные представления, которые автоматически и инкрементально обновляются при вставке новых данных в фоновом режиме:

```sql
-- Создание непрерывного агрегата для часовых метрик
CREATE MATERIALIZED VIEW hourly_metrics
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    device_id,
    AVG(cpu_usage) AS avg_cpu
FROM device_metrics
GROUP BY bucket, device_id;

-- Запрос к агрегату (использует предрасчитанные данные)
SELECT * FROM hourly_metrics
WHERE bucket > NOW() - INTERVAL '7 days';
```

### Сжатие данных

TimescaleDB использует колоночный формат для сжатия старых данных, что значительно экономит место на диске:

```sql
-- Включение механизма сжатия для гипертаблицы
ALTER TABLE device_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id'
);

-- Настройка политики автоматического сжатия данных старше 7 дней
SELECT add_compression_policy('device_metrics', INTERVAL '7 days');
```

## Практические сценарии

### Установка и настройка

**Установка в Debian/Ubuntu:**

```bash
# Добавление официального репозитория
sudo add-apt-repository ppa:timescale/timescaledb-ppa
sudo apt update

# Установка расширения для PostgreSQL 16
sudo apt install timescaledb-2-postgresql-16

# Автоматическая настройка параметров postgresql.conf (память, воркеры)
sudo timescaledb-tune

# Перезапуск службы
sudo systemctl restart postgresql
```

**Активация в базе данных:**

```sql
-- Выполняется один раз для каждой целевой базы данных
CREATE EXTENSION IF NOT EXISTS timescaledb;
```

### Создание и использование гипертаблицы

```sql
-- 1. Создание базовой структуры таблицы
CREATE TABLE device_metrics (
    time TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL,
    cpu_usage DOUBLE PRECISION,
    memory_usage DOUBLE PRECISION
);

-- 2. Преобразование в гипертаблицу с интервалом чанка в 7 дней
SELECT create_hypertable(
    'device_metrics',
    'time',
    chunk_time_interval => INTERVAL '7 days'
);

-- 3. Аналитический запрос с использованием интервалов (time_bucket)
SELECT
    time_bucket('5 minutes', time) AS five_min,
    device_id,
    AVG(cpu_usage) AS avg_cpu
FROM device_metrics
WHERE time > NOW() - INTERVAL '1 day'
GROUP BY five_min, device_id
ORDER BY five_min DESC;
```

### Автоматизация обслуживания (Retention)

```sql
-- Удаление данных, возраст которых превышает 30 дней
SELECT add_retention_policy('device_metrics', INTERVAL '30 days');
```

## Дополнительная информация

### Сравнение с альтернативами

| Система | Тип решения | Основное назначение | Особенности |
| :--- | :--- | :--- | :--- |
| **TimescaleDB** | Extension для PostgreSQL | Временные ряды + реляционные данные | ACID-гарантии, полный SQL. |
| **[ClickHouse](./clickhouse.md)** | OLAP СУБД | Аналитика больших данных, логи | Сверхвысокая скорость на петабайтах. |
| **[Prometheus](../Prometheus/overview.md)** | TSDB / Мониторинг | Метрики инфраструктуры | Pull-модель, собственный язык PromQL. |
| **[VictoriaMetrics](../VictoriaMetrics/overview.md)** | TSDB | Хранение метрик Prometheus | Высокая плотность хранения, совместимость. |

### Ограничения и особенности

- **Требования к ресурсам:** небольшое увеличение потребления памяти по сравнению со стандартным PostgreSQL.
- **Масштабирование:** горизонтальное масштабирование (Multi-node) доступно, но требует более сложной настройки, чем одиночный узел.
- **Версии PostgreSQL:** новые функции TimescaleDB могут требовать обновления версии ядра PostgreSQL.

### Смежные темы

- Масштабирование PostgreSQL — **[PostgreSQL Scaling](./PostgreSQL/Concepts/scaling.md)**.
- Аналитика на больших данных — **[ClickHouse](./clickhouse.md)**.
- Корпоративные хранилища — **[Greenplum](./greenplum.md)**.
- Мониторинг систем — **[Prometheus Overview](../Prometheus/overview.md)**.
- Репликация данных — **[Репликация в PostgreSQL](./PostgreSQL/Concepts/replication.md)**.
