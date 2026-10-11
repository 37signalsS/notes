# ClickHouse — Альтернативы и сравнение

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS); Apache Druid 37.0.x; Apache Pinot 1.5.1; StarRocks 4.1.x; Apache Doris 4.1.4.x; Greenplum 7.8.x; Elasticsearch 9.5.x; TimescaleDB 2.30.x

## Определения

**Apache Druid** — колоночная OLAP-СУБД для аналитики в реальном времени с автоматическим шардированием и репликацией.

**Apache Pinot** — колоночная OLAP-СУБД для аналитики с низкой задержкой, разработанная в LinkedIn.

**StarRocks** — колоночная MPP-СУБД, форк Apache Doris, с поддержкой материализованных представлений и JOIN.

**Apache Doris** — колоночная MPP-СУБД для аналитики (ранее Palo), fork от MySQL-протокола.

**Greenplum** — MPP-СУБД на базе PostgreSQL для хранилищ данных.

**Elasticsearch** — поисковый движок на основе Lucene; силён в полнотекстовом поиске.

**TimescaleDB** — расширение PostgreSQL для временных рядов.

## Предварительные требования

- Базовое понимание OLAP и OLTP-моделей.
- Доступ к Linux-хосту или Docker для запуска СУБД.
- Знание SQL для оценки особенностей запросов (JOIN, агрегации).
- Для production-развертываний: планирование capacity (RAM, CPU, диски), резервное копирование, мониторинг.

## Основные концепции

### Матрица сравнения

| Характеристика | ClickHouse | Druid | Pinot | StarRocks/Doris | Greenplum | Elasticsearch | TimescaleDB |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Модель** | Колоночная LSM | Колоночная, сегменты | Колоночная, сегменты | Колоночная MPP | Колоночная MPP (PostgreSQL) | Инвертированный индекс | Строковая + Timeseries |
| **Вставка** | Очень высокая | Высокая (streaming) | Высокая (streaming) | Высокая | Средняя | Средняя | Высокая |
| **Агрегации** | Очень быстрые | Быстрые | Быстрые | Быстрые | Средние | Медленные | Быстрые (TS) |
| **JOIN** | Ограниченные | Ограниченные | Ограниченные | Хорошие | Хорошие | Нет | Хорошие (PostgreSQL) |
| **Полнотекстовый поиск** | Базовый (text index) | Нет | Нет | Нет | Нет | **Отличный** | Нет |
| **Обновления** | Мутации (дорого) | Перезапись сегментов | Перезапись сегментов | Поддержка | Поддержка | Поддержка | Поддержка |
| **Транзакции** | Нет | Нет | Нет | Нет | Нет | Нет | ACID (через PostgreSQL) |
| **Эксплуатация** | Простая | Сложная (ZK, Overlord) | Сложная (ZK, Controller) | Средняя | Средняя | Средняя | Простая |
| **Кейс** | Аналитика, логи, метрики | Аналитика в реальном времени | Аналитика с низкой задержкой | Хранилище данных | Хранилище данных | Поиск, логи | Временные ряды |

### Когда выбирать что

| Сценарий | Рекомендация |
| :--- | :--- |
| Аналитика по миллиардам строк, логи, метрики | **ClickHouse** |
| Полнотекстовый поиск по неструктурированному тексту | **Elasticsearch** |
| Аналитика в реальном времени с streaming-вставкой | **Druid** или **Pinot** |
| Хранилище данных со сложными JOIN | **StarRocks/Doris** или **Greenplum** |
| Временные ряды с SQL и расширениями PostgreSQL | **TimescaleDB** |
| OLTP + аналитика в одной СУБД | **PostgreSQL** (или гибрид) |

### SRE-сводная таблица: ресурсы, мониторинг, бэкапы

| СУБД | Рекомендуемые ресурсы (prod) | Ключевые метрики / мониторинг | Резервное копирование |
| :--- | :--- | :--- | :--- |
| **ClickHouse** | 32+ ядер, 128+ ГБ RAM, NVMe RAID 10, 10+ Гбит/с | Prometheus 9363: `Parts`, `MemoryUsage`, `QueriesRate` | `clickhouse-backup`, `FREEZE`/`RESTORE`, `s3()`-таблицы |
| **Druid** | 6 ГБ direct + 1 ГБ heap на Historical, отдельные хосты | JMX: `numSegments`, `broker/queries/time/mean`, pending tasks | Сегменты в Deep Storage (S3/HDFS), копирование + конфиг-экспорт |
| **Pinot** | 8–16 ГБ heap на Server, 4 ГБ на Controller | Console 9000, JMX: `serverSegmentCount`, `partitionUnbalanced` | Сегменты в глобальном хранилище (HDFS/S3), ZK + метаданные |
| **StarRocks/Doris** | 8+ ГБ heap FE, 16+ ГБ RAM BE, NVMe | HTTP API `fe/http/`, `be/http/`, `FE leader`, `tablet status` | `BACKUP ... TO s3://`, `DUMP`/`EXPORT`, `RESTORE` |
| **Greenplum** | 32+ ядер, 128+ ГБ RAM, NVMe RAID 10, 25+ Гбит/с | `gpstate`, `gp_toolkit`, GPCC GUI, `status='d'` | `gpbackup`/`gprestore` (инкрементальные), `pg_dump` |
| **Elasticsearch** | 32+ ГБ RAM, 16+ ядер, NVMe | `/_cluster/health`, `/_cat/indices`, `jvm.gc.time`, `pending_tasks` | `snapshot` (S3/Azure/GCS), `elasticdump`, `curator` + ILM |
| **TimescaleDB** | 8+ ядер, 64+ ГБ RAM, NVMe | `job_stats`, `chunks_detailed_size`, `postgres_exporter` | `pg_dump`/`pg_restore`, `pg_basebackup` + WAL (PITR) |

### ClickHouse vs Elasticsearch

- **ClickHouse** лучше: числовые агрегации, сжатие, скорость вставки, SQL.
- **Elasticsearch** лучше: полнотекстовый поиск, нечёткий поиск, анализ текста.
- **Гибрид:** ClickHouse для аналитики + Elasticsearch для поиска (через `external_data` или дублирование).

### ClickHouse vs Druid/Pinot

- **ClickHouse** проще в эксплуатации (нет отдельного координатора/оверлорда).
- **Druid/Pinot** лучше для streaming-вставки с автоматическим сегментированием и compaction.
- **Druid/Pinot** имеют встроенную координацию (ZooKeeper) и сегменты; ClickHouse требует ручного шардирования.

### ClickHouse vs StarRocks/Doris

- **StarRocks/Doris** лучше для сложных JOIN и хранилищ данных.
- **ClickHouse** быстрее на простых агрегациях и вставке.
- **StarRocks/Doris** имеют MySQL-протокол и лучшую поддержку UPDATE.

### ClickHouse vs TimescaleDB

- **ClickHouse** лучше: сверхбольшие объемы (>10 ТБ), сжатие, скорость агрегаций.
- **TimescaleDB** лучше: временные ряды с функциями `time_bucket()`, continuous aggregates, гипертаблицы, полная совместимость с PostgreSQL экосистемой.
- **Гибрид:** TimescaleDB для оперативных временных рядов + ClickHouse для долгосрочной аналитики.

## Установка и эксплуатация (DevOps/SRE справочник)

### ClickHouse

**Docker:**
```bash
docker run -d \
  --name clickhouse-server \
  --ulimit nofile=262144:262144 \
  -p 8123:8123 \
  -p 9000:9000 \
  clickhouse/clickhouse-server:26.9
```

**Порты:** `8123` (HTTP), `9000` (Native TCP), `8443` (HTTPS), `9363` (Prometheus).

**Systemd:** `clickhouse-server` (стандартный пакет).

**Валидация:**
```bash
curl -s http://localhost:8123/ping
# → Ok.
clickhouse-client --query "SELECT version()"
# → 26.9.4.3
```

**Ресурсы (рекомендации):** минимум 8 ядер / 32 ГБ RAM для тестов; для petabyte-нагрузки — 32+ ядер, 128+ ГБ RAM, NVMe SSD в RAID 10, сеть 10+ Гбит/с. Критически важен `max_memory_usage` (по умолчанию 0 = без лимита) и `max_threads`.

**Мониторинг:** встроенный Prometheus-эндпоинт на порту `9363`. Ключевые метрики: `ReplicatedMergeTree_parts_version`, `MergeTree_parts_size`, `MemoryUsage`, `QueriesRate`, `InsertsRate`. Алерты на рост `PendingParts` и `ReplicaQueueSize`.

**Резервное копирование:** `clickhouse-backup` (incremental/restore), `ALTER TABLE ... FREEZE` (снапшоты в `shadow/`), `RESTORE` из снапшота. Интеграция с S3-совместимыми хранилищами через `s3()`-таблицы.

### Apache Druid

**Docker (микросервисный режим — для production требуется docker-compose):**
```bash
docker run -d \
  --name druid-router \
  -p 8888:8888 \
  apache/druid:37.0.0 start-server server-type=router
```

**Порты:** `8888` (Router/UI), `8081` (Coordinator/Overlord), `8082` (Broker), `8083` (Historical), `8091` (MiddleManager).

**Валидация:**
```bash
curl -s http://localhost:8888/status
# → {"status":"healthy"}
```

**Ресурсы:** Druid — JVM-приложение. Рекомендуется 6 ГБ direct memory + 1 ГБ heap на Historical (переменные `DRUID_MAXDIRECTMEMORYSIZE`, `DRUID_XMX`). Для production — отдельные хосты для Historical/MiddleManager, Broker, Coordinator, Overlord.

**Мониторинг:** Druid публикует метрики через JMX и HTTP (`/status`). Ключевые метрики: `druid/history/historical/numSegments`, `druid/broker/queries/time/mean`, `druid/overlord/pendingTasks`. Алерты на backlog задач и деградацию Historical.

**Резервное копирование:** сегменты хранятся в Deep Storage (S3/HDFS/локальный диск). Резервное копирование — копирование сегментов из Deep Storage. `druid-index-console` и скрипты экспорта конфигурации.

### Apache Pinot

**Docker (QuickStart):**
```bash
docker run -d \
  --name pinot \
  -p 2123:2123 \
  -p 9000:9000 \
  -p 8000:8000 \
  -p 7050:7050 \
  apachepinot/pinot:1.5.1 QuickStart -type batch
```

**Порты:** `9000` (Controller), `8000` (Broker), `7050` (Server), `2123` (ZK).

**Валидация:**
```bash
curl -s http://localhost:9000/health
# → {"status":"UP"}
```

**Ресурсы:** Pinot — JVM-приложение. Рекомендуется 8–16 ГБ heap на Server, 4 ГБ на Controller. Критически важен баланс сегментов (каждый Server — 100–500 сегментов).

**Мониторинг:** встроенный Pinot Console на порту `9000`. Метрики через JMX: `serverSegmentCount`, `controllerStats`, `brokerMetrics`. Алерты на `partitionUnbalanced` и неравномерное распределение.

**Резервное копирование:** сегменты хранятся в глобальном хранилище (HDFS/S3/локальный диск). Резервное копирование — копирование сегментов и метаданных (ZooKeeper + off-heap storage).

### StarRocks

**Docker (allin1):**
```bash
docker run -d \
  --name starrocks \
  -p 9030:9030 \
  -p 8030:8030 \
  -p 8040:8040 \
  starrocks/allin1-ubuntu:4.1
```

**Порты:** `9030` (MySQL), `8030` (FE HTTP), `9020` (FE Thrift), `8040` (BE HTTP), `9060` (BE Thrift), `9010` (FE edit log).

**Валидация:**
```bash
mysql -P 9030 -h 127.0.0.1 -uroot -e "SHOW FRONTENDS;"
# → вывод активных FE
```

**Ресурсы:** StarRocks — FE (Java) и BE (C++). Рекомендуется 8+ ГБ heap для FE, 16+ ГБ RAM для BE, NVMe SSD. Масштабирование: минимум 3 FE (кворум), BE — по мере роста данных.

**Мониторинг:** встроенный web-интерфейс на `8040` (BE) и `8030` (FE). Метрики через HTTP API: `fe/http/`, `be/http/`. Алерты на `FE leader election`, `BE tablet status`, `query latency`.

**Резервное копирование:** `BACKUP DATABASE ... TO `s3://...`` (направленный бэкап в S3-совместимое хранилище), `DUMP`, `EXPORT`. Восстановление через `RESTORE`.

### Apache Doris

**Docker:**
```bash
docker run -d \
  --name doris \
  -p 9030:9030 \
  -p 8020:8020 \
  -p 8030:8030 \
  -p 8040:8040 \
  apache/doris:4.1.4.1-fe
```

**Порты:** `9030` (MySQL), `8020` (BE HTTP), `8030` (FE HTTP), `8040` (FE Thrift).

**Валидация:**
```bash
mysql -P 9030 -h 127.0.0.1 -uroot -e "SHOW BACKENDS;"
# → вывод активных BE
```

**Ресурсы:** Doris — FE (Java) и BE (C++). Рекомендуется 8+ ГБ heap для FE, 16+ ГБ RAM для BE, NVMe SSD. Поддержка compute-storage decoupled (3.X+).

**Мониторинг:** встроенный web-интерфейс на `8040` (BE) и `8030` (FE). Метрики через HTTP API и JMX. Алерты на `FE leader`, `BE tablet`, `routine load job status`.

**Резервное копирование:** `BACKUP DATABASE ... TO `s3://...``, `DUMP`, `EXPORT`. Восстановление через `RESTORE`. Поддержка инкрементальных бэкапов.

### Greenplum

**Docker (только для тестирования):**
```bash
docker run -d \
  --name greenplum \
  -p 5432:5432 \
  greenplum-db/greenplum-db:7.8.3
```

**Порты:** `5432` (Master), varies (Segments).

**Валидация:**
```bash
psql -h localhost -p 5432 -U gpadmin -c "SELECT version();"
# → PostgreSQL 12.22 (Greenplum Database 7.8.3 build commit:...)
```

**Ресурсы:** минимум 8 ядер / 32 ГБ RAM на сегмент-хост; рекомендуется 32+ ядер, 128+ ГБ RAM, NVMe SSD в RAID 10, сеть 25/40/100 Гбит/с. Критически важны `kernel.shmall`/`kernel.shmmax` (половина RAM) и отключение Transparent Huge Pages.

**Мониторинг:** `gpstate` (сегменты, mirror'ы), `gp_toolkit` (размеры объектов, bloat), Greenplum Command Center (GPCC, GUI). Алерты на `gp_segment_configuration WHERE status='d'`.

**Резервное копирование:** `gpbackup`/`gprestore` (параллельные, инкрементальные, линейка 1.33.x), `pg_dump`/`pg_dumpall` (только для частных случаев).

> Подробно: **[Greenplum](../greenplum.md)**.

### Elasticsearch

**Docker:**
```bash
docker run -d \
  --name elasticsearch \
  -p 9200:9200 \
  -p 9300:9300 \
  elasticsearch:9.5.5
```

**Порты:** `9200` (HTTP), `9300` (Transport).

**Валидация:**
```bash
curl -s http://localhost:9200
# → {"name":"...","cluster_name":"...","version":{...}}
```

**Ресурсы:** минимум 8 ГБ RAM, 2 ядра; рекомендуется 32+ ГБ RAM, 16+ ядер, NVMe SSD. Критически важны `node.total_memory`, `heap.size`, `indices.memory` и настройка `bootstrap.memory_lock: true`.

**Мониторинг:** встроенный API (`/_cluster/health`, `/_cat/indices`, `/_nodes/stats`). Метрики через `_nodes/stats` и Kibana Stack Monitoring. Алерты на `cluster_status: red`, `pending_tasks`, `jvm.gc.time`.

**Резервное копирование:** `snapshot` API (поддержка S3/Azure/GCS/ФС), `elasticdump` (логический бэкап), `curator` (управление индексами и ретеншном через ILM).

### TimescaleDB

**Docker:**
```bash
docker run -d \
  --name timescaledb \
  -p 5432:5432 \
  timescale/timescaledb:2.30.1-pg18
```

**Порты:** `5432` (PostgreSQL).

**Валидация:**
```bash
psql -h localhost -p 5432 -U postgres -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"
# → 2.30.1
```

**Ресурсы:** минимум 4 ядра / 16 ГБ RAM; рекомендуется 8+ ядер, 64+ ГБ RAM, NVMe SSD. Критически важен размер индексов активных чанков — не более 25% RAM.

**Мониторинг:** стандартные PostgreSQL-метрики через `pg_stat_statements` и `postgres_exporter` (Prometheus). Ключевые представления: `timescaledb_information.job_stats`, `chunks_detailed_size`, `hypertable_columnstore_stats`. Алерты на backlog фоновых заданий и рост чанков.

**Резервное копирование:** `pg_dump`/`pg_restore` (логическое), `pg_basebackup` + WAL-архивация (PITR). `DROP EXTENSION timescaledb CASCADE` удаляет все гипертаблицы — только после бэкапа.

> Подробно: **[TimescaleDB](../timescaledb.md)**.

## Практические сценарии

### Миграция с Elasticsearch в ClickHouse

```sql
-- Схема логов в ClickHouse
CREATE TABLE logs (
    timestamp DateTime64(3),
    level LowCardinality(String),
    service LowCardinality(String),
    message String,
    INDEX idx_msg message TYPE text(tokenizer = splitByNonAlpha)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (service, timestamp)
TTL timestamp + INTERVAL 30 DAY;

-- Поиск по слову (аналог match в ES)
SELECT * FROM logs WHERE hasToken(message, 'error');
```

### Гибрид: ClickHouse + Elasticsearch

```
[Приложение] --> [Kafka] --> [ClickHouse] (аналитика, агрегации)
                           \--> [Elasticsearch] (полнотекстовый поиск)
```

### Streaming-пайплайн: Kafka → Druid/Pinot

```
[Приложение] --> [Kafka] --> [Druid/Pinot] (аналитика в реальном времени)
```

### Хранилище данных: Greenplum/StarRocks

```
ETL/CDC --> [Greenplum/StarRocks] --> BI-инструменты (Metabase, Superset)
```

### Миграционные пути (SRE)

| Откуда | Куда | Типичный путь | Ловушки |
| :--- | :--- | :--- | :--- |
| **Elasticsearch** | **ClickHouse** | Репликация индексов через Kafka → ClickHouse; миграция агрегаций | Потеря полнотекстовой функциональности; нужен ES для поиска |
| **TimescaleDB** | **ClickHouse** | CDC (Debezium) → Kafka → ClickHouse; `time_bucket` → `toStartOfInterval` | Потеря ACID, непрерывных агрегатов; гибрид для оперативных данных |
| **Greenplum** | **StarRocks/Doris** | Экспорт через `gpfdist`/`COPY` → загрузка через Stream Load | Разное партиционирование; проверка статистики (`ANALYZE`) |
| **Druid/Pinot** | **ClickHouse** | Перенос сегментов в ClickHouse через Kafka/батч-загрузку | Потеря автоматической compaction; настройка `TTL` и `PARTITION BY` |
| **ClickHouse** | **StarRocks/Doris** | Экспорт через `SELECT ... INTO OUTFILE` → загрузка через Broker Load | Потеря производительности вставки; проверка `ORDER BY` и индексов |

### SRE-чек-листы

| Действие | ClickHouse | Druid | Pinot | StarRocks/Doris | Greenplum | Elasticsearch | TimescaleDB |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Graceful shutdown** | `clickhouse stop` / `SYSTEM SHUTDOWN` | `bin/service.sh stop` (все сервисы) | `bin/pinot-admin stop` | `STOP ALL` (FE/BE) | `gpstop -m` | `bin/elasticsearch stop` | `pg_ctl stop` |
| **Graceful restart** | `clickhouse restart` | `bin/service.sh restart` | `bin/pinot-admin restart` | `STOP ALL` + `START ALL` | `gpstop -r` | `bin/elasticsearch restart` | `pg_ctl restart` |
| **Проверка целостности** | `SYSTEM CHECK TABLE`, `SELECT count()` по партициям | `druid coordinator` — баланс сегментов | `pinot-admin cluster check` | `SHOW TABLET STATUS`, `SHOW BACKENDS` | `gpcheckcat`, `gpstate -e` | `/_cat/indices?v`, `/_cluster/health` | `VACUUM ANALYZE`, `chunks_detailed_size` |
| **Aварийное восстановление** | `RESTORE` из снапшота / `clickhouse-backup restore` | Восстановление сегментов из Deep Storage | Восстановление сегментов из хранилища + ZK | `RESTORE DATABASE`, `ALTER SYSTEM RESTORE` | `gprestore`, `gpbackup` | `snapshot` restore, `elasticdump` | `pg_restore`, `pg_basebackup` + WAL |

## Ограничения и крайние случаи

| СУБД | Ограничение | Обходное решение |
| :--- | :--- | :--- |
| **ClickHouse** | Нет ACID, дорогие UPDATE/DELETE | Мутации, CollapsingMergeTree, ReplacingMergeTree |
| **Druid** | Сложное развертывание (ZK, Overlord, MiddleManager) | Managed-решения (Imply, Atlan), Kubernetes Operator, docker-compose quickstart |
| **Pinot** | Высокая латентность при сложных JOIN | Денормализация, предвычисления, Materialized Views |
| **StarRocks/Doris** | Потребление RAM на Coordinator при больших JOIN | Партиционирование, увеличение FE памяти, shared-data архитектура (3.X+/4.X+) |
| **Greenplum** | Segment crashes при переполнении disk/memory | Мониторинг `gp_segment_configuration`, планирование capacity, зеркалирование |
| **Elasticsearch** | Агрегации на trillion-row медленные | Rollup jobs, ILM, переход на ClickHouse для аналитики |
| **TimescaleDB** | Ограничена одним узлом (если не использует Citus) | Citus extension для распределения, или ClickHouse |

### Капасити и деградация (SRE)

| СУБД | Порог деградации | Действие |
| :--- | :--- | :--- |
| **ClickHouse** | RAM > 80%, `PendingParts` растёт | Увеличить `max_memory_usage`, добавить узел, `SYSTEM MERGE` |
| **Druid** | `pendingTasks` > 100, Historical не успевают | Добавить Historical, настроить autoscaling MiddleManager |
| **Pinot** | `partitionUnbalanced` > 20% | Перераспределить сегменты, проверить `numReplicas` |
| **StarRocks/Doris** | `FE not leader`, lost quorum | Восстановить failed FE, проверить `SHOW FRONTENDS` |
| **Greenplum** | Диски сегментов > 70% | `VACUUM`, `ANALYZE`, расширить кластер (`gpexpand`) |
| **Elasticsearch** | `cluster_status: red`, shards unassigned | Добавить nodes, проверить `_cat/shards`, `_cluster/health` |
| **TimescaleDB** | Рост чанков, индексы > 25% RAM | Уменьшить `chunk_time_interval`, добавить RAM или Citus |

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Полнотекстовый поиск медленнее ES | ClickHouse не оптимизирован для поиска | Использовать ES для поиска, CH для аналитики |
| JOIN медленный | ClickHouse не оптимизирован для JOIN | Словари, денормализация, или StarRocks/Doris |
| Streaming-вставка сложна | Нет встроенного координатора | Kafka Engine, или Druid/Pinot |
| UPDATE медленный | Мутации перезаписывают части | CollapsingMergeTree, или OLTP-СУБД |
| Druid Overlord недоступен | ZK недоступен или не настроен | Проверить ZK: `echo ruok | nc localhost 2181` |
| Pinot Controller partition unbalanced | Неравномерное распределение | Проверить `numReplicas` и capacity Server |
| StarRocks FE not leader | Нет кворума FE | Восстановить failed FE или запустить новый |
| Greenplum segment down | Диск или memory overflow | `gpstate -e`, проверка `pg_log/` |
| Elasticsearch shards unassigned | Недостаточно nodes | Проверить `_cat/shards`, добавить nodes |
| TimescaleDB hypertable slow | Отсутствие индексов | Добавить индексы по времени, continuous aggregates |

## Лучшие практики

1. **ClickHouse** — для аналитики, логов, метрик, трейсов.
2. **Elasticsearch** — для полнотекстового поиска.
3. **Druid/Pinot** — для streaming-аналитики с автоматическим сегментированием.
4. **StarRocks/Doris** — для хранилищ данных со сложными JOIN.
5. **TimescaleDB** — для временных рядов в PostgreSQL экосистеме.
6. **Гибрид** — комбинировать системы под паттерн доступа.
7. **Очистка:** При удалении контейнеров удаляйте volumes: `docker rm -v <container>`.
8. **Резервное копирование:** Используйте нативные инструменты (`clickhouse-backup`, `snapshot`/`elasticdump`, `pg_dump`/`pg_basebackup`, `gpbackup`/`gprestore`) в связке с cron.

## Дополнительная информация

### Смежные темы

- Архитектура ClickHouse — **[Архитектура](./clickhouse-architecture.md)**.
- Полнотекстовый поиск — **[Полнотекстовый поиск](./clickhouse-full-text-search.md)**.
- Интеграция с Kafka — **[Интеграция ClickHouse и Kafka](./clickhouse_kafka_integration.md)**.
- Сравнение с Greenplum — **[Greenplum](../greenplum.md)**.
- Сравнение с TimescaleDB — **[TimescaleDB](../timescaledb.md)**.

### Ресурсы

- [ClickHouse vs Druid](https://clickhouse.com/docs/use-cases/olap)
- [ClickHouse vs Elasticsearch](https://clickhouse.com/docs/use-cases/olap)
- [Apache Druid Documentation](https://druid.apache.org/docs/latest/)
- [Apache Pinot Documentation](https://docs.pinot.apache.org/)
- [StarRocks Documentation](https://docs.starrocks.io/)
- [Apache Doris Documentation](https://doris.apache.org/docs/)
- [Greenplum Documentation](https://techdocs.broadcom.com/us/en/vmware-tanzu/data-solutions/tanzu-greenplum/)
- [Elasticsearch Reference](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html)
- [TimescaleDB Documentation](https://docs.timescale.com/)
