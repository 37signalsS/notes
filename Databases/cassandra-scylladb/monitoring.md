# Мониторинг и observability

## Ключевые метрики

| Метрика | Описание | Норма |
| :--- | :--- | :--- |
| `Pending Tasks` | Задачи в очереди обработки | < 50 |
| `Total Latency (P99)` | 99-й перцентиль задержки | < 50мс (Write), < 20мс (Read) |
| `Dropped Messages` | Потерянные сообщения репликации | 0 |
| `Tombstone Scanned` | Сканированные Tombstones за запрос | < 1000 |
| `Compaction Pending` | Очередь Compaction | Стабильно низкий |
| `Heap Used` | Использование JVM (Cassandra) | < 75% от max |

---

## nodetool: основные команды

```bash
# Состояние узлов кластера
nodetool status
# → Datacenter: DC1
#   Status=Up/Down
#   UN  10.0.1.1  256 KB   256.0%   c4e5d6f1-...  node1
#   UN  10.0.1.2  128 KB   128.0%   a1b2c3d4-...  node2

# Статистика по таблицам
nodetool cfstats my_app.user_events
# → SSTable count: 5
#   Space used (live): 1024000
#   Read Count: 50000
#   Read Latency: 2.5 ms
#   Write Count: 100000
#   Write Latency: 1.2 ms

# Информация о кластере
nodetool info

# Статус Compaction
nodetool compactionstats

# Логи (просмотр последних ошибок)
tail -f /var/log/cassandra/system.log

# Профилирование запросов (Cassandra 5.x+)
nodetool settraceprobability 0.1  # 10% запросов
```

---

## Сбор диагностической информации

```bash
# Полный diagnostic report
nodetool describecluster   # Информация о кластере
nodetool status            # Состояние узлов
nodetool info              # Информация об узле
nodetool tpstats           # Статистика потоков
nodetool cfstats           # Статистика по таблицам
nodetool compactionstats   # Текущие Compaction
nodetool netstats          # Сетевая статистика
nodetool proxyhistograms   # Гистограммы задержек
```

---

## Инструменты мониторинга

- **nodetool:** Основная утилита управления (Cassandra/Scylla).
- **scylla-top:** Мониторинг нагрузки на ядра (только для ScyllaDB).
- **scylla监控:** Встроенный веб-интерфейс ScyllaDB для мониторинга (порт по умолчанию 9180).
- **cqlsh:** Интерактивный CLI для выполнения запросов.
- **Cassandra Reaper:** Автоматизация Repair с веб-интерфейсом и расписанием.
- **Prometheus + Grafana:** Сбор метрик через JMX Exporter (Cassandra) или нативный endpoint (ScyllaDB).

---

## Prometheus метрики (Cassandra 4.x+)

Cassandra 4.x+ экспонирует метрики через JMX. Для Prometheus используйте **JMX Exporter**:

```yaml
# jmx_prometheus_javaagent конфигурация
rules:
  - pattern: org.apache.cassandra.metrics<type=(ClientRequest), scope=(Read|Write), name=(Latency)><>Count
    name: cassandra_client_request_latency_count
    labels:
      request: "$2"
  - pattern: org.apache.cassandra.metrics<type=(ClientRequest), scope=(Read|Write), name=(Latency)><>50thPercentile
    name: cassandra_client_request_latency_p50
    labels:
      request: "$2"
  - pattern: org.apache.cassandra.metrics<type=(ClientRequest), scope=(Read|Write), name=(Latency)><>99thPercentile
    name: cassandra_client_request_latency_p99
    labels:
      request: "$2"
  - pattern: org.apache.cassandra.metrics<type=(Storage), name=(Load)><>Count
    name: cassandra_storage_load_bytes
  - pattern: org.apache.cassandra.metrics<type=(Table), scope=(.*), name=(TombstonesScanned)><>Count
    name: cassandra_tombstones_scanned_total
    labels:
      table: "$1"
```

---

## ScyllaDB: нативный Prometheus endpoint

ScyllaDB экспонирует метрики напрямую через HTTP (по умолчанию порт 9180):

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'scylla'
    static_configs:
      - targets: ['scylla-node1:9180', 'scylla-node2:9180']
    metrics_path: '/metrics'
```

**Ключевые метрики ScyllaDB:**
- `scylla_db_read_latency_p99` — P99 задержки чтения
- `scylla_db_write_latency_p99` — P99 задержки записи
- `scylla_storage_total_writes` — общий объем записи
- `scylla_io_queue_disk_total_read` — чтение с диска
- `scylla_compaction_pending_tasks` — ожидающие Compaction

---

## См. также
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — диагностика ошибок.
- **[Тюнинг производительности](./performance.md)** — JVM, I/O, Tombstones.
- **[Мониторинг СУБД](../../Prometheus/Exporters/other_exporters.md)** — каталог экспортеров.
