# TimescaleDB: Расширение PostgreSQL для временных рядов

**Актуально для:** TimescaleDB 2.30.x / PostgreSQL 16–18

Специализированное расширение для оптимизации PostgreSQL под задачи хранения и анализа временных рядов. Общие подходы к масштабированию описаны в **[Масштабирование PostgreSQL](./PostgreSQL/Concepts/scaling.md)**.

## Определения

**TimescaleDB** — это расширение (extension) для СУБД PostgreSQL, которое превращает ее в полноценную базу данных временных рядов (TSDB — Time-Series Database). Оно оптимизировано для хранения и анализа данных, привязанных ко времени, сохраняя при этом все возможности реляционной базы данных (ACID, JOIN, индексы).

**Текущее состояние:** линия TimescaleDB 2.30.x — стандарт для IoT, FinTech и систем мониторинга (например, **[Zabbix](../Zabbix/installation.md)**). Поддерживаются PostgreSQL 16, 17 и 18; поддержка PostgreSQL 15 прекращена в версии 2.29.0. Возможности PostgreSQL 18 (асинхронный ввод-вывод AIO, `uuidv7()`, skip scan) доступны на уровне движка PostgreSQL и ускоряют операции сканирования, vacuum и генерацию UUID.

**Редакции:**
- **TimescaleDB Apache 2 Edition** — полностью открытое ядро: гипертаблицы, чанки, retention-политики, tablespaces. Пакет `timescaledb-2-oss-postgresql-*`.
- **TimescaleDB Community Edition** — расширенная версия под лицензией TSL (Tiger Data License): columnstore, `move_chunk`, `add_reorder_policy`, SkipScan. Бесплатна при самостоятельном хостинге, но не может продаваться как сервис. Пакет по умолчанию из официального репозитория Timescale — это сборка Community.

**Временные ряды (Time-Series Data):** данные, где каждая запись является измерением в конкретный момент времени.
- **Особенности:** высокая интенсивность записи, преимущественно Append-only, важность временной локальности данных.

## Основные концепции

### Архитектура: гипертаблицы и чанки

**Гипертаблица (Hypertable)** — это виртуальная таблица, которая автоматически разбивается на физические части — **чанки (chunks)**.
- **Чанк:** обычная таблица PostgreSQL, содержащая данные за определенный интервал времени (и, опционально, по ключу шардирования).
- **Преимущество:** индексы активных чанков помещаются в RAM, что предотвращает деградацию производительности при росте объема данных (проблема B-tree в стандартном PG).
- **Создание (современный способ, с 2.23):** таблица с колонкой `timestamptz` автоматически становится гипертаблицей при указании `timescaledb.hypertable`; `create_hypertable()` — legacy API, работает для совместимости.
- **Индексы:** по умолчанию создаётся индекс по колонке времени (DESC); уникальный индекс на гипертаблице обязан включать все колонки партиционирования.

### Колоночное хранение (Columnstore / Hypercore)

TimescaleDB использует гибридное хранение: новые данные хранятся в строковом формате (rowstore/heap), а старые преобразуются в колоночный формат (columnstore). Терминология «compression» заменена на «columnstore» начиная с версии 2.18.0.
- **Эффективность:** сжатие до 98%; типично 90%+.
- **Segmentby:** группировка данных по колонке (например, `sensor_id`) внутри сжатого блока — запросы по этому устройству декомпрессируют только нужные сегменты.
- **Orderby:** сортировка данных внутри блока (обычно `time DESC`) для эффективного использования разреженных индексов.
- **Sparse-индексы:** bloom-фильтры и min/max-индексы позволяют отвечать на COUNT/MIN/MAX/FIRST/LAST без декомпрессии (custom node `ColumnarIndexScan`, ускорение до 70x).
- **Direct compress:** `SET timescaledb.enable_direct_compress_insert = on;` — запись сразу в колоночный формат при вставке, без ожидания политики.
- **DeferredChunkAppend (с 2.30.0):** ускорение запросов с LIMIT за счет отложенного разворачивания чанков на этапе планирования.

### Непрерывные агрегаты (Continuous Aggregates)

Материализованные представления, которые обновляются инкрементально в фоне.
- **Real-time Aggregation:** функция, объединяющая агрегированные данные на диске с «сырыми» данными из гипертаблицы прямо во время выполнения запроса. Отключается опцией `timescaledb.materialized_only = true`.
- **Иерархические агрегаты:** возможность создавать агрегаты поверх других агрегатов (например, `daily` поверх `hourly`) для экстремальной производительности на больших периодах.
- **Columnstore для агрегатов:** `ALTER MATERIALIZED VIEW ... SET (timescaledb.enable_columnstore = true, ...)` + `add_columnstore_policy` — агрегаты тоже переходят в колоночный формат.

### Хранение на разных носителях (self-hosted)

Прозрачное перемещение старых чанков в объектные хранилища (S3/GCS) в self-hosted TimescaleDB недоступно: Tiered Storage — функция управляемого сервиса Tiger Cloud, для self-hosted её нет и в планах нет (issue #6632, закрыт в январе 2026).
- **Альтернатива self-hosted:** tablespaces — `attach_tablespace` (Apache-редакция) и `move_chunk()` (Community) размещают чанки на разных дисках (NVMe для горячих данных, SATA SSD для холодных).
- **Прозрачность:** для приложения это остается одной таблицей.

### Timescale Toolkit

Набор продвинутых аналитических функций на базе Rust:
- **Hyperloglog:** быстрый приблизительный подсчет уникальных элементов с фиксированным потреблением памяти.
- **T-Digest:** вычисление приблизительных квантилей и перцентилей на потоковых данных.
- **State Aggregates:** отслеживание состояний систем (например, «сколько времени станок был в простое»).

## Установка и настройка

### Шаг 1: Установка (Debian/Ubuntu)

```bash
# Добавление официального репозитория
curl -s https://packagecloud.io/install/repositories/timescale/timescaledb/script.deb.sh | sudo bash
sudo apt update
# Пакет Community-редакции (включает columnstore); для Apache-only — timescaledb-2-oss-postgresql-18
sudo apt install timescaledb-2-postgresql-18

# Автоматическая оптимизация конфига (shared_buffers, work_mem и др.),
# в том числе добавление timescaledb в shared_preload_libraries
sudo timescaledb-tune --quiet --yes
sudo systemctl restart postgresql

# Проверка
psql -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb';"
# → timescaledb | 2.30.1
```

**RHEL/CentOS:** аналогично через `script.rpm.sh` и `sudo yum install timescaledb-2-postgresql-18`.
**Docker:** `docker run -d --name timescaledb -p 6543:5432 -e POSTGRES_PASSWORD=password timescale/timescaledb-ha:pg18` (порт 6543 выбран, чтобы не конфликтовать со стандартным 5432).

> **Важно:** расширение требует `shared_preload_libraries = 'timescaledb'` и перезапуска PostgreSQL. `timescaledb-tune` вносит эту настройку автоматически; без перезапуска `CREATE EXTENSION` завершится ошибкой.

### Шаг 2: Создание и настройка гипертаблицы

```sql
-- Активация расширения
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Создание гипертаблицы (с 2.23 таблица с timestamptz-колонкой
-- автоматически партиционируется; интервал чанка по умолчанию — 7 дней)
CREATE TABLE sensor_data (
    time        TIMESTAMPTZ NOT NULL,
    sensor_id   INTEGER,
    cpu_temp    DOUBLE PRECISION,
    mem_usage   DOUBLE PRECISION
) WITH (timescaledb.hypertable, timescaledb.chunk_interval = '7 days');

-- Legacy-вариант (до 2.23), по-прежнему работает:
-- SELECT create_hypertable('sensor_data', 'time', chunk_time_interval => INTERVAL '7 days');

-- Включение columnstore (сегментирование по датчику, сортировка по времени)
ALTER TABLE sensor_data SET (
    timescaledb.enable_columnstore,
    timescaledb.compress_segmentby = 'sensor_id',
    timescaledb.compress_orderby = 'time DESC'
);
```

## Практические сценарии

### Политики жизненного цикла данных

```sql
-- 1. Политика перевода в columnstore: данные старше 14 дней
CALL add_columnstore_policy('sensor_data', after => INTERVAL '14 days');

-- 2. Политика удаления (Retention): удалять данные старше 2 лет
SELECT add_retention_policy('sensor_data', INTERVAL '2 years');

-- 3. Политика переупорядочивания (Community): поддерживать индекс оптимальным
SELECT add_reorder_policy('sensor_data', 'sensor_data_time_idx');

-- Ручные операции
SELECT show_chunks('sensor_data', older_than => INTERVAL '7 days');   -- список чанков
CALL convert_to_columnstore('_timescaledb_internal._hyper_1_2_chunk'); -- ручной перевод чанка
CALL convert_to_rowstore('_timescaledb_internal._hyper_1_2_chunk');    -- обратно в rowstore
SELECT drop_chunks('sensor_data', INTERVAL '2 years');                 -- ручное удаление чанков
SELECT set_chunk_time_interval('sensor_data', INTERVAL '1 day');       -- интервал для новых чанков
```

> Старый API (`add_compression_policy`, `compress_chunk`, `ALTER TABLE ... SET (timescaledb.compress, ...)`) deprecated с 2.18.0, но продолжает работать; при обновлении мигрируйте на columnstore-вызовы.

### Использование непрерывных агрегатов

```sql
-- Создание агрегата для среднечасовых показателей
CREATE MATERIALIZED VIEW sensor_stats_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    sensor_id,
    AVG(cpu_temp) AS avg_temp,
    MAX(cpu_temp) AS max_temp
FROM sensor_data
GROUP BY bucket, sensor_id;

-- Политика обновления (раз в час обновлять данные за последние 2 часа)
SELECT add_continuous_aggregate_policy('sensor_stats_hourly',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

-- Ручное обновление за произвольный период
CALL refresh_continuous_aggregate('sensor_stats_hourly', '2026-01-01', '2026-02-01');
```

### Пропуск чанков по не-временным колонкам (Chunk Skipping)

```sql
-- Отслеживание min/max диапазонов по колонке: планировщик пропускает чанки,
-- где диапазон не пересекается с условием WHERE.
-- Работает только для чанков, переведённых в columnstore ПОСЛЕ включения;
-- поддерживаемые типы: smallint, int, bigint, serial, bigserial, date, timestamp, timestamptz.
SELECT enable_chunk_skipping('sensor_data', 'sensor_id');
```

## Обслуживание и эксплуатация

### Мониторинг заданий (Background Jobs)

Все политики (columnstore, агрегация, удаление, reorder) выполняются фоновыми воркерами.
- Проверка статуса заданий:
  ```sql
  SELECT * FROM timescaledb_information.job_stats;
  ```
- Текущий интервал чанков:
  ```sql
  SELECT * FROM timescaledb_information.dimensions WHERE hypertable_name = 'sensor_data';
  ```
- Размеры чанков и их индексов:
  ```sql
  SELECT * FROM chunks_detailed_size('sensor_data');
  ```
- Статистика columnstore (Community): представления `timescaledb_information.hypertable_columnstore_settings` и `hypertable_columnstore_stats`.
- **Prometheus:** метрики PostgreSQL собираются через `postgres_exporter` — устройство эндпоинта и алерты описаны в **[обзоре Prometheus](../Prometheus/overview.md)**.

### Резервное копирование и восстановление

- **Логическое:** стандартные `pg_dump` / `pg_restore` — гипертаблицы, чанки, политики и непрерывные агрегаты включаются в дамп как обычные объекты PostgreSQL.
- **PITR:** стандартная для PostgreSQL архивация WAL + `pg_basebackup`; восстановление на произвольный момент работает без специфики TimescaleDB.
- **Осторожно:** `DROP EXTENSION timescaledb CASCADE` удаляет все гипертаблицы, агрегаты и политики — только после бэкапа.

### Диагностика производительности

1. **Bloat индексов:** если вставка замедлилась, проверьте размер индексов активных чанков (`chunks_detailed_size`). Индексы записываемых чанков должны помещаться в 25% RAM.
2. **DML в columnstore:** INSERT/UPDATE/DELETE в сжатые чанки поддерживаются с версии 2.11 (декомпрессируются только затронутые данные). Массовые операции без фильтра по `segmentby`-колонке вызывают массовую декомпрессию — для бэкфилла сначала `convert_to_rowstore()`.
3. **Explain:** всегда используйте `EXPLAIN (ANALYZE, BUFFERS)` для проверки Chunk Exclusion (пропуск ненужных чанков) и запускайте `ANALYZE` после массовых загрузок.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR: extension "timescaledb" is not loaded` | нет `shared_preload_libraries` | `timescaledb-tune --yes` + перезапуск PostgreSQL |
| Политики не выполняются | остановлен воркер или ошибка в job | `timescaledb_information.job_stats` (`job_status`, `last_run_status`) |
| Замедление вставок | интервал чанка слишком велик — индексы не влезают в RAM | `set_chunk_time_interval` на меньший интервал |
| Долго планируются запросы | слишком много мелких чанков | увеличить интервал; не создавать десятки тысяч гипертаблиц |
| Ошибка при создании unique constraint на сжатом чанке | ограничение columnstore | создать ограничение до включения columnstore |
| RLS не работает на старых данных | row-level security не поддерживается на columnstore-чанках | применять RLS на rowstore или на уровне приложения |
| `timescaledb-tune` «не работает» | конфиг не перечитан | проверить `postgresql.conf` и перезапустить сервис |

## Дополнительная информация

### Сравнение с альтернативами

| Система | Тип | Ключевой кейс |
| :--- | :--- | :--- |
| **TimescaleDB** | Реляционная TSDB | Сложная аналитика, JOIN с SQL-данными, ACID. |
| **[MongoDB](./MongoDB/mongodb.md)** | Document TSDB | Гибкая схема, MongoDB 8.0+ (колоночное сжатие). |
| **[ClickHouse](./ClickHouse/clickhouse.md)** | OLAP | Петабайты данных, сверхбыстрые агрегации. |
| **[VictoriaMetrics](../VictoriaMetrics/overview.md)** | Monitoring TSDB | Метрики Prometheus, экстремальная плотность хранения. |
| **InfluxDB** | NoSQL TSDB | Простые IoT сценарии без сложной структуры. |

### Рекомендации (Best Practices)

- **Размер чанка:** стремитесь к тому, чтобы суммарный размер индексов всех *активных* чанков (те, куда идет запись) составлял не более 25% от RAM. Пример: 64 ГБ RAM, рост индексов ~2 ГБ/день — интервал 7 дней; ~10 ГБ/день — интервал 1 день.
- **Segmentby:** выбирайте низкокардинальные колонки, по которым фильтруют запросы (device_id, region); **Orderby** — `time DESC`.
- **Connection Pooling:** используйте **PgBouncer** в режиме транзакций, особенно если у вас тысячи IoT-устройств.
- **UUIDv7:** для первичных ключей (не связанных со временем) используйте `uuidv7()` — встроена в PostgreSQL 18 и сохраняет временную локальность записей. Сравнение стратегий ID — в **[Генерация идентификаторов](./Concepts/id_generation.md)**.
- **Массовая загрузка:** `CREATE TABLE ... WITH (timescaledb.hypertable, timescaledb.create_default_indexes = false)` — индексы добавить после загрузки; `COPY` быстрее `INSERT` в 2–3 раза.
- **ANALYZE** после массовых загрузок и после перевода чанков в columnstore.

### Ограничения

- **Multi-node:** распределённые гипертаблицы (multi-node) sunsetted в версии 2.14.x (последняя версия с поддержкой — 2.13). Для горизонтального масштабирования рассмотрите **[Citus](./citus.md)** или **[Greenplum](./greenplum.md)**.
- **Декомпрессия:** частые изменения в старых (сжатых) данных вызывают значительную нагрузку из-за необходимости декомпрессии блоков.
- **Columnstore-чанки:** не поддерживают RLS и уникальные ограничения; уникальный индекс на гипертаблице должен включать все колонки партиционирования.
- **Tiered Storage (S3/GCS):** только в управляемом Tiger Cloud; в self-hosted используйте tablespaces и `move_chunk()`.

### Обновление версий

- **Minor-обновления** (2.30.0 → 2.30.1) — in-place, без dump/restore.
- **2.28.0:** удалён старый формат непрерывных агрегатов (deprecated с 2.10) — мигрируйте до обновления.
- **2.29.0:** прекращена поддержка PostgreSQL 15 — сначала обновите PostgreSQL до 16/17/18.
- **С 2.18.0:** API сжатия deprecated в пользу columnstore (`add_compression_policy` → `add_columnstore_policy` и т.д.); старые вызовы работают, но планируйте миграцию.
- После обновления перезапустите `timescaledb-tune` и проверьте `timescaledb_information.job_stats`.

### См. также

- **[Секционирование данных](./Concepts/partitioning.md)** — TimescaleDB в контексте партиционирования.
- **[Шардирование в базах данных](./Concepts/sharding.md)** — основы партиционирования.
- **[ClickHouse](./ClickHouse/clickhouse.md)** — для массовой аналитики.
- **[VictoriaMetrics](../VictoriaMetrics/overview.md)** — для инфраструктурного мониторинга.
- **[Официальная документация self-hosted](https://docs.timescale.com/self-hosted/latest)**
- **[Hypercore (columnstore) API](https://www.tigerdata.com/docs/reference/timescaledb/hypercore)**
