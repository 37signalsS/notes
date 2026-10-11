# Мониторинг и observability

**Актуально для:** Apache Cassandra 5.0.x / ScyllaDB 2026.x / ScyllaDB Monitoring Stack 4.16

## Определения

- **nodetool** — CLI управления и диагностики узла. Cassandra обращается через него к JMX; ScyllaDB предоставляет совместимый CLI (подмножество команд — полный список: `nodetool help`).
- **JMX (Java Management Extensions)** — интерфейс управления JVM-приложениями. Cassandra экспонирует все метрики через JMX (порт 7199; безопасность — в [Безопасность](./security.md)).
- **JMX Exporter** — Java-агент Prometheus (проект prometheus/jmx_exporter): запускается в том же JVM и превращает JMX MBeans в HTTP-эндпоинт `/metrics` в формате Prometheus.
- **Prometheus endpoint** — нативный HTTP-эндпоинт метрик ScyllaDB (по умолчанию порт 9180, путь `/metrics`).
- **ScyllaDB Monitoring Stack** — официальный стек мониторинга и алертинга ScyllaDB (Prometheus + Grafana + Loki + Alertmanager), репозиторий [scylladb/scylla-monitoring](https://github.com/scylladb/scylla-monitoring).
- **Virtual Tables** — виртуальные таблицы Cassandra 5.0, позволяющие запрашивать метрики через CQL.
- **Dropwizard Metrics** — библиотека метрик Cassandra. Типы: Gauge (мгновенное значение), Counter (счётчик), Histogram (распределение: min/max/median/75/90/95/98/99/99.9 перцентили), Timer (частота + histogram), **Latency** (задержка в **микросекундах**: Timer + счётчик накопленной задержки; имена суффиксами `Latency` и `TotalLatency`), Meter (средняя пропускная способность и EMA 1/5/15 мин).
- **shard** — поток выполнения ScyllaDB, привязанный к ядру CPU. Метрики ScyllaDB экспортируются **per-shard** (лейбл `shard`); кластерные значения получаются суммированием.

## Как работает мониторинг

Метрики собираются **на каждом узле отдельно**; агрегация по кластеру — задача внешней системы (Prometheus). Путь экспорта зависит от СУБД:

| СУБД | Источник метрик | Путь в Prometheus |
| :--- | :--- | :--- |
| ScyllaDB | нативный HTTP-эндпоинт (порт 9180) | прямой scrape (`scrape_configs`) |
| Apache Cassandra (bare-metal/VM) | JMX MBeans (Dropwizard Metrics) | JMX Exporter как Java-агент |
| Apache Cassandra 5.0 | JMX + Virtual Tables (CQL) | JMX Exporter; Virtual Tables — для разовых запросов |
| Cassandra в K8ssandra | Management API for Apache Cassandra (MAAC), эндпоинт `localhost:9000/metrics` (alpha; MAAC v0.1.57+, Cassandra 3.11.13+/4.0.4+) | k8ssandra-operator v1.5.0+ (ранее — MCAC); хост-метрики — Vector sidecar. См. [Kubernetes](./kubernetes.md) |

Именование MBean Cassandra: `org.apache.cassandra.metrics:type=<Type>[,scope=<Scope>][,keyspace=<Keyspace>],name=<MetricName>`, где `type` — `Table`, `Keyspace`, `ThreadPools`, `ClientRequest`, `Storage`, `Compaction`, `DroppedMessage`, `ReadRepair`.

Инструменты: **nodetool** (CLI), **scylla-top** (ScyllaDB: нагрузка по ядрам CPU), **cqlsh** (разовые запросы, в т.ч. Virtual Tables), **Cassandra Reaper** (автоматизация repair — см. [Обслуживание](./operations.md)), **Prometheus + Grafana** (сбор и визуализация), **ScyllaDB Monitoring Stack** (готовый стек для ScyllaDB).

## nodetool: команды мониторинга

Команды работают и в Cassandra, и в ScyllaDB (в ScyllaDB — подмножество). При включённой аутентификации JMX добавьте `-u <user> -pw <пароль>` (см. [Безопасность](./security.md)).

```bash
# Состояние узлов кластера
nodetool status
# → Datacenter: dc1
#   Status=Up/Down
#   |/ State=Normal/Leaving/Joining/Moving
#   --  Address    Load        Tokens  Owns (effective)  Host ID                            Rack
#   UN  10.0.1.1   103.42 KiB  256     50.0%             c4e5d6f1-...  rack1
#   UN  10.0.1.2   103.42 KiB  256     50.0%             a1b2c3d4-...  rack1
# Флаг -r: разрешить IP в имена хостов

# Статистика по таблице (бывший cfstats — deprecated alias)
nodetool tablestats my_app.user_events
# → Keyspace : my_app
#     Read Count: 50000
#     Read Latency: 2.5 ms
#     Write Count: 100000
#     Write Latency: 1.2 ms
#     Pending Flushes: 0
#             Table: user_events
#             SSTable count: 5
#             Space used (live): 1024000
#             Number of keys (estimate): 100000
# Статистика обновляется при compaction/flush

# Информация об узле
nodetool info
# → ID, Gossip active, Native Transport active, Load,
#   Generation No, Uptime (seconds), Heap Memory (MB)

# Статистика пулов потоков: Active/Pending/Completed/Blocked
# и Dropped Messages за всё время и за последние 5 минут
nodetool tpstats

# Текущие compaction
nodetool compactionstats

# Гистограммы задержек координатора (Read/Write/Range/Slice)
nodetool proxyhistograms

# Гистограммы по таблице (бывший cfhistograms)
nodetool tablehistograms my_app.user_events

# Самые активные партиции (горячие точки) — Cassandra 4.0+
nodetool toppartitions

# Статистика GC — Cassandra 4.0+
nodetool gcstats

# Состояние failure detector по узлам
nodetool failuredetector

# Состояния gossip
nodetool gossipinfo

# Таймауты (read, write, range, ...)
nodetool gettimeout read

# Вероятностная трассировка запросов (0 — выкл., 1 — все, по умолчанию 0)
nodetool settraceprobability 0.1

# Версия
nodetool version
```

Логи: Cassandra — `/var/log/cassandra/system.log` (в Docker — `docker logs -f cassandra-1`), ScyllaDB — `/var/log/scylla/scylla.log`.

Диагностический bundle команд (describecluster, netstats и др.) — в [Поиск и устранение неисправностей](./troubleshooting.md).

## ScyllaDB: нативный Prometheus endpoint

ScyllaDB экспонирует метрики напрямую по HTTP (по умолчанию порт 9180, путь `/metrics`). Порт настраивается в `scylla.yaml` (`prometheus_port`; значение `0` отключает API).

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'scylla'
    scrape_interval: 15s
    static_configs:
      - targets: ['scylla-node1:9180', 'scylla-node2:9180']
    metrics_path: '/metrics'
```

Метрики **per-shard** (лейбл `shard`) — агрегируйте при запросах:

```promql
# Throughput чтения на узел (сумма по shards)
sum by (instance) (rate(scylla_database_total_reads[5m]))
# P99 задержки чтения координатора
histogram_quantile(0.99,
  sum by (le, instance) (rate(scylla_storage_proxy_coordinator_read_latency_bucket[5m])))
```

**Ключевые метрики ScyllaDB** (полный список — в [справочнике метрик](https://docs.scylladb.com/manual/branch-2026.3/reference/metrics.html)):

| Метрика | Тип | Что показывает |
| :--- | :--- | :--- |
| `scylla_storage_proxy_coordinator_read_latency` / `write_latency` | histogram | задержки координатора (`_bucket`/`_sum`/`_count`; есть также `_summary`-вариант) |
| `scylla_storage_proxy_coordinator_read_timeouts` / `write_timeouts` / `range_timeouts` | counter | таймауты координатора (норма: 0) |
| `scylla_storage_proxy_coordinator_read_unavailable` / `write_unavailable` | counter | исключения UnavailableException |
| `scylla_database_total_reads` / `total_writes` | counter | успешные чтения/записи (per-shard) |
| `scylla_database_total_reads_failed` / `total_writes_failed` / `total_writes_timedout` | counter | ошибки операций |
| `scylla_database_active_reads` | gauge | параллельные чтения |
| `scylla_database_sstable_read_queue_overloads` | counter | > 0 — чтения отбрасываются: запросы приходят быстрее, чем обслуживаются |
| `scylla_database_reads_shed_due_to_overload` | counter | сброшенные из-за перегрузки запросы |
| `scylla_reactor_utilization` | gauge | загрузка CPU shards (0..1) |
| `scylla_compaction_manager_pending_compactions` | gauge | задачи compaction в очереди |
| `scylla_compaction_manager_backlog` / `normalized_backlog` | gauge | compaction backlog (абсолютный и нормированный на память shard) |
| `scylla_compaction_manager_failed_compactions` | counter | неудавшиеся compaction |
| `scylla_gossip_live` / `scylla_gossip_unreachable` | gauge | живые/недостижимые узлы по мнению узла |
| `scylla_cql_reads` / `inserts` / `updates` / `deletes` / `batches` | counter | CQL-операции |
| `scylla_cql_prepared_cache_evictions` | counter | рост — клиент готовит новый запрос на каждый запрос вместо переиспользования prepared statements |
| `scylla_cql_filtered_read_requests` / `filtered_rows_read_total` / `filtered_rows_dropped_total` | counter | анализ ALLOW FILTERING: `dropped` ≈ `read_total` — фильтр неточен и тормозит чтение |
| `scylla_lsa_occupancy` | gauge | занятость памяти LogAlloc (%) |
| `scylla_cache_bytes_used` / `scylla_cache_bytes_total` | gauge | row cache |
| `scylla_commitlog_pending_allocations` | gauge | очередь выделений commitlog |
| `scylla_transport_current_connections` | gauge | CQL-соединения |
| `scylla_transport_requests_shed` | counter | сброшенные транспортные запросы |
| `scylla_hints_manager_send_errors` | counter | ошибки доставки hints |
| `scylla_node_operation_mode` | gauge | режим узла (bootstrap и т.п.) |
| `scylla_scylladb_current_version` | gauge | версия ScyllaDB |

Метрики ScyllaDB Manager (repair): `scylla_manager_repair_progress`, `scylla_manager_scheduler_last_duration` — см. [Обслуживание](./operations.md).

## Cassandra: экспорт метрик через JMX Exporter

Cassandra экспонирует метрики через JMX (все версии). Для Prometheus используется **JMX Exporter** как Java-агент.

Важно: Cassandra имеет **много медленных метрик** — полный скрап грузит CPU и превышает `scrape_timeout`. Используйте **whitelist** (официальный пример конфига — `examples/cassandra.yml` в репозитории prometheus/jmx_exporter; список всех метрик на узле: `jmxtool dump`).

```yaml
# config.yml для JMX Exporter (сокращённый официальный whitelist)
whitelistObjectNames:
  - "org.apache.cassandra.metrics:type=Client,*"
  - "org.apache.cassandra.metrics:type=Compaction,*"
  - "org.apache.cassandra.metrics:type=Connection,name=Timeouts,*"
  - "org.apache.cassandra.metrics:type=DroppedMessage,name=Dropped,*"
  - "org.apache.cassandra.metrics:type=Keyspace,name=AllMemtables*DataSize,*"
  - "org.apache.cassandra.metrics:type=Keyspace,name=ReadLatency,*"
  - "org.apache.cassandra.metrics:type=Keyspace,name=WriteLatency,*"
  - "org.apache.cassandra.metrics:type=Keyspace,name=PendingCompactions,*"
  - "org.apache.cassandra.metrics:type=ReadRepair,*"
  - "org.apache.cassandra.metrics:type=Storage,name=Exceptions,*"
  - "org.apache.cassandra.metrics:type=Storage,name=Load,*"
  - "org.apache.cassandra.metrics:type=Storage,name=TotalHints,*"
  - "org.apache.cassandra.metrics:type=ThreadPools,*"
  - "org.apache.cassandra.metrics:type=ColumnFamily,*,name=LiveSSTableCount"
  - "org.apache.cassandra.metrics:type=ColumnFamily,*,name=BytesUnrepaired"
rules:
  # Latency в Cassandra — в МИКРОСЕКУНДАХ: конвертация в секунды
  - pattern: org.apache.cassandra.metrics<type=(\S*)(?:, ((?!scope)\S*)=(\S*))?(?:, scope=(\S*))?, name=((?:.+)?(?:Total)(Latency))><>Count
    name: cassandra_$1_$5_seconds_sum
    type: UNTYPED
    labels:
      "$1": "$4"
      "$2": "$3"
    valueFactor: 0.000001
  - pattern: org.apache.cassandra.metrics<type=(\S*)(?:, ((?!scope)\S*)=(\S*))?(?:, scope=(\S*))?, name=((?:.+)?(?:Latency))><>Count
    name: cassandra_$1_$5_seconds_count
    type: UNTYPED
    labels:
      "$1": "$4"
      "$2": "$3"
  - pattern: org.apache.cassandra.metrics<type=(\S*)(?:, ((?!scope)\S*)=(\S*))?(?:, scope=(\S*))?, name=((?:.+)?(?:Latency))><>(\d+)thPercentile
    name: cassandra_$1_$5_seconds
    type: GAUGE
    labels:
      "$1": "$4"
      "$2": "$3"
      quantile: "0.$6"
    valueFactor: 0.000001
```

Запуск агента — добавить в `jvm-server.options` (Cassandra 4.x) или `jvm.options` (3.x):

```bash
# Порт 1234 — HTTP-эндпоинт экспортера; конфиг — рядом
-javaagent:/opt/jmx_exporter/jmx_prometheus_javaagent.jar=1234:/opt/jmx_exporter/config.yml
```

После правки — перезапуск Cassandra. Проверка: `curl -s http://cassandra-node1:1234/metrics | grep cassandra_`.

**Ключевые метрики Cassandra** (JMX MBean → экспортируется JMX Exporter):

| MBean (`org.apache.cassandra.metrics`) | Что показывает |
| :--- | :--- |
| `type=ClientRequest, scope=Read\|Write, name=Latency` | задержка (мкс); `99thPercentile` — P99, `TotalLatency` — накопленная |
| `type=ClientRequest, scope=Read\|Write, name=Timeouts` | таймауты (counter; норма: 0) |
| `type=ClientRequest, scope=Read\|Write, name=Unavailables` | исключения UnavailableException |
| `type=ThreadPools, path=request, scope=ReadStage\|MutationStage, name=PendingTasks` | задачи в очереди пула |
| `type=ThreadPools, name=TotalBlockedTasks` | задачи, заблокированные из-за насыщения очереди |
| `type=Keyspace, scope=<KS>, name=PendingCompactions` | очередь compaction keyspace |
| `type=ColumnFamily, scope=<Table>, name=LiveSSTableCount` | число SSTable на диске (рост — сигнал проблемы) |
| `type=ColumnFamily, name=TombstoneScannedHistogram` | распределение сканированных tombstones |
| `type=ColumnFamily, name=TombstoneWarnings` / `TombstoneFailures` | чтения, превысившие `tombstone_warn_threshold` / `tombstone_failure_threshold` |
| `type=ColumnFamily, name=KeyCacheHitRate` | hit rate key cache |
| `type=ColumnFamily, name=PercentRepaired` | доля данных, покрытых repair |
| `type=ColumnFamily, name=SSTablesPerReadHistogram` | число SSTable на чтение |
| `type=Storage, name=Load` | объём данных на узле (байты) |
| `type=Storage, name=Exceptions` | необработанные исключения |
| `type=DroppedMessage, name=Dropped` | потерянные сообщения репликации (норма: 0) |
| `type=ReadRepair` | статистика read repair |
| `type=Compaction` | статистика compaction |

## Cassandra 5.0: Virtual Tables

Cassandra 5.0 позволяет запрашивать метрики через CQL с помощью **Virtual Tables** (в дополнение к JMX и репортерам). Удобно для разовых проверок из `cqlsh` без JMX. Постоянный сбор в Prometheus — по-прежнему через JMX Exporter.

## ScyllaDB Monitoring Stack

Официальный стек для ScyllaDB (репозиторий [scylladb/scylla-monitoring](https://github.com/scylladb/scylla-monitoring), документация: monitoring.docs.scylladb.com). Компоненты (Docker-контейнеры):

- **prometheus** — сбор и хранение метрик ScyllaDB и хоста (с `node_exporter` на серверах ScyllaDB)
- **grafana** — дашборды; данные из Prometheus, Alertmanager и напрямую из ScyllaDB по CQL
- **alertmanager** — алерты от Prometheus и Loki; доставка в email/Slack
- **Grafana Loki** — метрики и алерты на основе логов (логи собираются агентами rsyslog с серверов БД)
- опционально: **grafana-image-renderer** (экспорт дашборда в изображение), **Thanos sidecar** (централизованное чтение локального Prometheus)

Установка: клонировать репозиторий и запустить `start-all.sh` (Docker), либо `docker-compose`, либо развернуть без Docker — см. [Install](https://monitoring.docs.scylladb.com/stable/install/index.html).

**Advisor** — компонент стека, анализирующий CQL-нагрузку и выявляющий: `ALLOW FILTERING`, консистентность `ALL`/`ANY`, запросы без token-awareness, непейджинированные запросы, неподготовленные (non-prepared) запросы, тяжёлые compaction, ошибки консистентности, I/O-ошибки (неисправный диск), неравномерное распределение запросов по shards, эвикции prepared-statements cache, перегрузку системы.

Стек поставляется с готовыми **Grafana-дашбордами** (Overview, Detailed, CQL, Advanced, OS, Keyspace) и **правилами алертов**; для Cassandra дашборды — community (официальных от Apache нет).

## Ключевые метрики и пороги

Пороги — стартовые точки для алертов; калибруйте под SLA и нагрузку.

| Сигнал | Норма (стартовая точка) | Где смотреть |
| :--- | :--- | :--- |
| Pending Tasks (пулы потоков) | < 50, стабильно | `nodetool tpstats` / `ThreadPools.*.PendingTasks` |
| Dropped Messages | 0 | `nodetool tpstats` / `DroppedMessage` |
| Tombstone scanned за запрос | < 1000 (дефолт `tombstone_warn_threshold`) | `TombstoneScannedHistogram`, `TombstoneWarnings` |
| Compaction pending | стабильно низкий | `nodetool compactionstats` / `PendingCompactions` / `scylla_compaction_manager_pending_compactions` |
| Heap Used (Cassandra) | < 75% от max | `nodetool info` / JVM-метрики |
| P99 latency | зависит от SLA; старт: read < 20 мс, write < 50 мс | `ClientRequest.*.Latency` / `scylla_storage_proxy_coordinator_*_latency` |
| Coordinator timeouts / unavailable (ScyllaDB) | 0 | `scylla_storage_proxy_coordinator_*_timeouts` / `*_unavailable` |
| Read queue overloads (ScyllaDB) | 0 | `scylla_database_sstable_read_queue_overloads` |
| Reactor utilization (ScyllaDB) | < 0.7 | `scylla_reactor_utilization` |
| Prepared cache evictions (ScyllaDB) | не растёт быстро | `scylla_cql_prepared_cache_evictions` |

## Валидация установки

```bash
# ScyllaDB: эндпоинт отдаёт метрики
curl -s http://scylla-node1:9180/metrics | head -5
# → # HELP scylla_database_total_reads ...
# → # TYPE scylla_database_total_reads counter

# Метрики обновляются (повторный запрос через 30 с)
curl -s http://scylla-node1:9180/metrics | grep '^scylla_database_total_reads '

# Cassandra: JMX Exporter
curl -s http://cassandra-node1:1234/metrics | grep '^cassandra_'

# Prometheus видит цель
curl -s 'http://prometheus:9090/api/v1/query?query=up{job="scylla"}'
# → "value": [..., "1"]

# Длительность скрапа в пределах scrape_timeout
curl -s 'http://prometheus:9090/api/v1/query?query=scrape_duration_seconds{job="scylla"}'

# promtool
promtool check metrics http://scylla-node1:9180/metrics
promtool check config prometheus.yml
```

## Поиск и устранение неисправностей мониторинга

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `up{job="scylla"} == 0` | эндпоинт недоступен, порт закрыт | `curl http://node:9180/metrics`, `ss -tlnp \| grep 9180` | проверить `prometheus_port` в `scylla.yaml` (0 = отключено), firewall |
| `scrape timeout` (Cassandra) | полный скрап JMX слишком тяжёлый | `curl -w '%{time_total}' http://node:1234/metrics` | добавить `whitelistObjectNames`, увеличить `scrape_timeout` |
| `metric not found` | неверное имя: у histogram нет суффикса `_p99` | `curl .../metrics \| grep <имя>` | использовать `_bucket`/`_sum`/`_count` и `histogram_quantile()` |
| Задержки Cassandra в микросекундах | JMX Exporter без `valueFactor` | проверить правила в `config.yml` | добавить `valueFactor: 0.000001` |
| `SecurityException: Authentication failed` (JMX Exporter) | включена JMX-аутентификация | логи экспортера | credentials в конфиге javaagent (см. [Безопасность](./security.md)) |
| `scylla_database_sstable_read_queue_overloads > 0` | перегрузка чтениями | метрика + `nodetool tpstats` | масштабирование, тюнинг (см. [Тюнинг](./performance.md)) |
| Высокая кардинальность в Prometheus | лейблы per-table/per-keyspace | `curl .../metrics \| wc -l`, API Prometheus | `metric_relabel_configs` с drop лишних лейблов |
| Значения ScyllaDB дублируются | метрики per-shard по дизайну | лейбл `shard` в метриках | агрегировать: `sum by (instance) (...)` |

## Рекомендации и очистка

- **Scrape interval:** 15–30 с для ScyllaDB/Cassandra; `scrape_timeout` — больше длительности скрапа.
- **Cassandra — только whitelist:** полный скрап JMX грузит CPU узла.
- **ScyllaDB — агрегация per-shard:** `sum by (instance) (rate(...))`.
- **Алерты:** `up`, `scrape_duration_seconds`, Dropped Messages, timeouts, unavailable, Pending Tasks, compaction backlog, TombstoneWarnings, `scylla_database_sstable_read_queue_overloads`.
- **Мониторьте сам мониторинг:** `up{job=...}` и `scrape_duration_seconds` — первые алерты.
- **Фиксируйте версии** экспортёров и стека в конфигурации.
- **Логи:** Cassandra — `/var/log/cassandra/system.log`; ScyllaDB — `/var/log/scylla/scylla.log`; в ScyllaDB Monitoring Stack — Loki + rsyslog.

Очистка (Cassandra, JMX Exporter):

```bash
# 1. Удалить строку -javaagent из jvm-server.options (или jvm.options)
# 2. Перезапустить Cassandra
# 3. Удалить /opt/jmx_exporter/
```

## См. также
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — диагностический bundle команд.
- **[Тюнинг производительности](./performance.md)** — JVM, I/O, Tombstones.
- **[Обслуживание и эксплуатация](./operations.md)** — Compaction, Repair.
- **[Безопасность](./security.md)** — JMX-аутентификация и TLS.
- **[Развёртывание и масштабирование в Kubernetes](./kubernetes.md)** — ScyllaDBMonitoring CRD, метрики в K8s.
- **[Мониторинг СУБД](../../Prometheus/Exporters/other_exporters.md)** — каталог экспортеров Prometheus.
