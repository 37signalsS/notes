# Методология мониторинга: Матрица «Сервис → Метрики → Экспортер → Алерты»

## Определения

**Матрица мониторинга** — структурированный подход к проектированию системы наблюдаемости, при котором для каждого сервиса определяется набор ключевых метрик, соответствующий экспортер и пороговые значения алертов. Матрица обеспечивает полноту покрытия и исключает пропуски критичных компонентов.

**USE-методика (Utilization, Saturation, Errors)** — для ресурсов (CPU, RAM, диск, сеть). Определяет: загрузку, насыщение и ошибки. Подробнее: [Мониторинг и наблюдаемость](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md).

**RED-методика (Rate, Errors, Duration)** — для сервисов и API. Определяет: частоту запросов, ошибки и длительность.

**Golden Signals** — для сервисов (Google SRE): Latency, Traffic, Errors, Saturation.

**См. также:** [USE/RED/Golden Signals](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md), [Обзор экспортеров](./overview.md).

## Основные концепции

### Как пользоваться матрицей

1.  Найдите свой сервис в таблице.
2.  Определите, какие метрики критичны для вашего SLA.
3.  Выберите соответствующий экспортер и настройте scrape.
4.  Настройте алерты по пороговым значениям.
5.  Добавьте Recording Rules для длинных промежутков.

### Матрица: Инфраструктурные компоненты

| Сервис | Методика | Ключевые метрики | Экспортер | Порт | Минимальные алерты |
|:---|:---|:---|:---|:---|:---|
| **Linux (CPU)** | USE | `node_cpu_seconds_total`, `node_load1` | [node_exporter](./node_exporter.md) | 9100 | `CPU > 85% 10m`, `Load > cores×1.5 10m` |
| **Linux (RAM)** | USE | `node_memory_MemAvailable_bytes`, `node_memory_SwapTotal_bytes` | node_exporter | 9100 | `RAM > 90% 5m`, `Swap > 50% 10m` |
| **Linux (Disk)** | USE | `node_filesystem_avail_bytes`, `node_disk_io_time_seconds_total` | node_exporter | 9100 | `Disk < 10% free 5m`, `I/O > 90% 15m` |
| **Linux (Network)** | USE | `node_network_receive_bytes_total`, `node_network_receive_errs_total` | node_exporter | 9100 | `Errors > 0 5m`, `Drops > 0 5m` |
| **Docker/K8s** | USE | `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes` | [cAdvisor](./cadvisor.md) | 8080 | `CPU > 80% 10m`, `RAM > 85% 5m` |
| **Kubernetes Node** | USE | `kube_node_status_condition`, `kube_node_labels` | kube-state-metrics | 8080 | `Node NotReady 5m` |

### Матрица: Базы данных

| Сервис | Методика | Ключевые метрики | Экспортер | Порт | Минимальные алерты |
|:---|:---|:---|:---|:---|:---|
| **PostgreSQL** | USE + RED | `pg_stat_activity`, `pg_stat_database`, `pg_locks` | postgres_exporter | 9187 | `Connections > 80% max`, `Deadlocks > 0`, `Replication lag > 10s` |
| **MySQL/MariaDB** | RED | `mysql_global_status_threads_connected`, `mysql_global_status_queries` | mysqld_exporter | 9104 | `Connections > 80% max`, `Slow queries > 0 5m`, `Replication lag > 10s` |
| **Redis** | USE | `redis_connected_clients`, `redis_used_memory_bytes`, `redis_evicted_keys_total` | [redis_exporter](./redis_exporter.md) | 9121 | `Memory > 80% maxmemory`, `Hit ratio < 80%`, `Evictions > 0` |
| **MongoDB** | USE | `mongodb_connections`, `mongodb_mempool_size`, `mongodb_op_counters_total` | mongodb_exporter | 9216 | `Connections > 80% max`, `Replication lag > 10s` |
| **ClickHouse** | RED | `clickhouse_query_duration_seconds`, `clickhouse_merge_total` | clickhouse_exporter | 9116 | `Query p99 > 5s`, `Failed queries > 0 5m` |
| **Elasticsearch** | USE | `elasticsearch_cluster_health_status`, `elasticsearch_node_fs_disk_usage` | elasticsearch_exporter | 9114 | `Cluster status = yellow/red`, `Disk > 85%` |

### Матрица: Веб-серверы и прокси

| Сервис | Методика | Ключевые метрики | Экспортер | Порт | Минимальные алерты |
|:---|:---|:---|:---|:---|:---|
| **Nginx** | RED | `nginx_http_requests_total`, `nginx_upstream_response_time_seconds` | nginx-prometheus-exporter | 9113 | `5xx > 1% 5m`, `Latency p99 > 2s` |
| **Angie (natивно)** | RED | `angie_http_requests_total`, `angie_upstream_response_time` | Встроен (Native) | 80/443 | `5xx > 1% 5m` |
| **HAProxy** | RED | `haproxy_backend_http_requests_total`, `haproxy_server_status` | haproxy_exporter (или нативный) | 9101 | `5xx > 1% 5m`, `Server down > 2m` |
| **Traefik (natивно)** | RED | `traefik_router_requests_total`, `traefik_service_request_duration_seconds` | Встроен (Native) | 8080 | `5xx > 1% 5m`, `Latency p99 > 2s` |
| **Apache** | RED | `apache_httpd_total_accesses`, `scrape_duration_seconds` | apache_exporter | 9117 | `5xx > 1% 5m`, `Workers busy > 80%` |

### Матрица: Брокеры сообщений

| Сервис | Методика | Ключевые метрики | Экспортер | Порт | Минимальные алерты |
|:---|:---|:---|:---|:---|:---|
| **RabbitMQ (natивно)** | RED | `rabbitmq_queue_messages`, `rabbitmq_queue_consumer_utilisation` | Встроен (rabbitmq_prometheus) | 15692 | `Queue > 10k messages 10m`, `Consumer utilisation < 80%` |
| **Kafka** | RED | `kafka_consumergroup_lag`, `kafka_broker_topics_messages_in_total` | kafka_exporter | 9308 | `Consumer lag > 1000 10m`, `Broker down > 2m` |

### Матрица: Сетевое оборудование

| Сервис | Методика | Ключевые метрики | Экспортер | Порт | Минимальные алерты |
|:---|:---|:---|:---|:---|:---|
| **SNMP-устройства** | USE | `ifHCInOctets`, `ifOperStatus`, `hrStorageUsed` | snmp_exporter | 9116 | `Interface down > 2m`, `CPU > 80% 10m` |
| **IPMI/BMC** | USE | `ipmi_fan_speed_rpm`, `ipmi_temperature_celsius`, `ipmi_power_watts` | ipmi_exporter | 9290 | `Fan = 0 RPM`, `Temp > 80°C`, `PSU status != OK` |

### Матрица: Специализированные проверки

| Проверка | Методика | Ключевые метрики | Инструмент | Порт | Минимальные алерты |
|:---|:---|:---|:---|:---|:---|
| **HTTP Availability** | Golden Signals | `probe_success`, `probe_duration_seconds`, `probe_http_status_code` | [blackbox_exporter](./blackbox/blackbox_exporter_overview.md) | 9115 | `probe_success == 0 2m`, `Latency > 5s 5m` |
| **SSL Certificate** | Golden Signals | `probe_ssl_earliest_cert_expiry` | blackbox_exporter | 9115 | `Expiry < 30d`, `Expiry < 7d (critical)` |
| **DNS** | Golden Signals | `probe_dns_lookup_time_seconds`, `probe_success` | blackbox_exporter | 9115 | `DNS lookup > 1s 5m`, `probe_success == 0 5m` |
| **TCP Connectivity** | Golden Signals | `probe_success`, `probe_duration_seconds` | blackbox_exporter | 9115 | `probe_success == 0 2m` |

### Матрица: Хранилища данных

| Сервис | Методика | Ключевые метрики | Экспортер | Порт | Минимальные алерты |
|:---|:---|:---|:---|:---|:---|
| **Ceph** | USE | `ceph_osd_utilization`, `ceph_osd_flags` | ceph_exporter | 9128 | `OSD down > 2m`, `Disk usage > 85%` |
| **NFS** | USE | `node_nfsd_disk_bytes_read_total`, `node_nfsd_threads_total` | node_exporter | 9100 | `NFS down > 2m`, `RPC errors > 0 5m` |

## Практические сценарии

### Создание матрицы для вашего стека

**Шаг 1: Инвентаризация сервисов**

```bash
# Пример: список сервисов из Prometheus
curl -s http://prometheus:9090/api/v1/label/__name__/values | jq -r '.data[]' | grep -v "^__" | sort -u | head -50
```

**Шаг 2: Заполнение матрицы**

```markdown
| Сервис | Методика | Метрики | Экспортер | Алерты |
|:---|:---|:---|:---|:---|
| PostgreSQL prod | USE + RED | connections, deadlocks, replication lag | postgres_exporter:9187 | connections>80%, lag>10s |
| Nginx gateway | RED | 5xx, latency | nginx-prometheus-exporter:9113 | 5xx>1%, p99>2s |
| Redis cache | USE | memory, hit ratio, evictions | redis_exporter:9121 | memory>80%, hit<80% |
```

**Шаг 3: Валидация полноты**

Проверьте, что каждый сервис в матрице покрыт алертом:

```bash
# Проверка наличия алертов для каждого сервиса
for service in postgres nginx redis; do
  echo "=== $service ==="
  curl -s http://prometheus:9090/api/v1/rules | \
    jq ".data.groups[].rules[] | select(.labels.job | contains(\"$service\"))" | \
    grep alertname || echo "NO ALERTS!"
done
```

### Recording Rules для матричных метрик

```yaml
groups:
  - name: matrix_recording_rules
    interval: 30s
    rules:
      # === USE: Ресурсы ===
      # CPU utilisation
      - record: node:cpu_utilisation:rate5m
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

      # RAM utilisation
      - record: node:memory_utilisation:ratio
        expr: 1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)

      # Disk utilisation
      - record: node:disk_utilisation:ratio
        expr: 1 - (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"})

      # === RED: Сервисы ===
      # Request rate
      - record: job:http_requests:rate5m
        expr: sum by(job) (rate(http_requests_total[5m]))

      # Error rate
      - record: job:http_errors:ratio_rate5m
        expr: sum by(job) (rate(http_requests_total{code=~"5.."}[5m])) / sum by(job) (rate(http_requests_total[5m]))

      # P99 latency
      - record: job:http_duration:p99_5m
        expr: histogram_quantile(0.99, sum by(job, le) (rate(http_request_duration_seconds_bucket[5m])))

      # === Доступность ===
      # Blackbox probe success
      - record: blackbox:probe_success:ratio_rate5m
        expr: avg by(job) (avg_over_time(probe_success[5m]))
```

## Лучшие практики

1.  **Начните с USE/RED:** Определите, что является ресурсом (USE) или сервисом (RED) в вашем стеке.
2.  **Не перегружайте матрицу:** Начните с 3–5 ключевых метрик на сервис, расширяйте по мере необходимости.
3.  **Recording Rules для SLO:** Используйте предвычисленные метрики для алертов и дашбордов.
4.  **Периодический аудит:** Каждые 3 месяца проверяйте матрицу на полноту покрытия.
5.  **Связь с SLA:** Каждый алерт в матрице должен соответствовать пункту SLA.

## См. также

*   [USE/RED/Golden Signals](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md) — детали методологий
*   [Обзор экспортеров](./overview.md) — каталог и выбор экспортера
*   [Каталог экспортеров](./other_exporters.md) — полный список
*   [Alerting Rules](../rules.md) — настройка алертов
*   [Recording Rules](../recording_rules.md) — оптимизация запросов
