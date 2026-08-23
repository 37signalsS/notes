# Stack Monitoring: Мониторинг Elastic Stack

> Руководство по мониторингу Elastic Stack. Рассматриваются компоненты, ключевые метрики, настройка Stack Monitoring и алертинг.
>
> Связанные темы: capacity planning — [Capacity Planning](./elasticsearch_capacity_planning.md); траблшутинг — [Troubleshooting](./elasticsearch_troubleshooting_indexing.md); алертинг — [Alerting](./elasticsearch_alerting.md).

## Определения

* **Stack Monitoring** — встроенная функциональность Kibana для визуализации состояния кластеров Elasticsearch, Logstash, Beats, Kibana.
* **Metricbeat** — агент сбора метрик для Elastic Stack компонентов.
* **Monitoring Cluster** — выделенный кластер Elasticsearch для хранения метрик мониторинга (может быть тем же или отдельным).
* **Internal Collection** — сбор метрик самим Elasticsearch без дополнительных агентов (simpler, но less flexible).
* **Beats/Agent Collection** — сбор метрик через Metricbeat или Elastic Agent (more flexible, richer data).

## Архитектура

### Вариант 1: Internal Collection (упрощенный)

```
┌─────────────┐
│ Elasticsearch│──▶ Метрики записываются в .monitoring-* индексы
│  (monitored) │
└─────────────┘
        │
        ▼
┌─────────────┐
│   Kibana    │◀── Чтение из .monitoring-* и визуализация
└─────────────┘
```

### Вариант 2: Beats Collection (рекомендуется для production)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Metricbeat  │────▶│ Monitoring  │────▶│   Kibana    │
│ (collector) │     │  Cluster    │     │ (visualize) │
└─────────────┘     └─────────────┘     └─────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│ Monitored Cluster (Elasticsearch)       │
└─────────────────────────────────────────┘
```

### Вариант 3: Выделенный Monitoring Cluster

```
┌──────────────┐     ┌──────────────────┐
│  Production  │     │ Monitoring       │
│   Cluster    │────▶│ Cluster          │
│  (monitored) │     │ (dedicated)      │
└──────────────┘     └──────────────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │   Kibana    │
                     └─────────────┘
```

## Настройка Stack Monitoring

### Internal Collection (через elasticsearch.yml)

```yaml
# На monitored кластере
xpack.monitoring.collection.enabled: true
xpack.monitoring.collection.interval: 10s

# На всех узлах кластера
```

### Beats Collection (Metricbeat)

```yaml
# metricbeat.yml
metricbeat.modules:
  - module: elasticsearch
    xpack.enabled: true
    period: 10s
    hosts: ["https://elasticsearch:9200"]
    username: "remote_monitoring"
    password: "${ES_MONITORING_PASSWORD}"
    ssl.certificate_authorities: ["/path/to/ca.crt"]

output.elasticsearch:
  hosts: ["https://monitoring-es:9200"]
  username: "metricbeat_writer"
  password: "${MONITORING_ES_PASSWORD}"
```

```bash
# Включение модуля
metricbeat modules enable elasticsearch
```

### Через Kibana UI

1. **Stack Monitoring** → **Settings**
2. Выбрать источник данных (Internal или Beats)
3. Указать monitoring cluster (если Beats)
4. Настроить retention period

## Ключевые метрики Elasticsearch

### Cluster Health

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `status` | green/yellow/red | red > 0 |
| `number_of_nodes` | Количество узлов | < expected |
| `unassigned_shards` | Неназначенные шарды | > 0 |
| `pending_tasks` | Ожидающие задачи | > 50 |
| `task_max_waiting_in_queue_millis` | Макс. ожидание в очереди | > 1000 |

### Indexing Performance

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `indexing.index_total` | Всего проиндексировано | Аномалии |
| `indexing.index_time_in_millis` | Время индексации | Рост latency |
| `indexing.index_current` | Текущие операции записи | - |
| `indexing.is_throttled` | Торможение записи | true > 0 |

### Search Performance

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `search.query_total` | Всего запросов | Аномалии |
| `search.query_time_in_millis` | Время запроса | > порог |
| `search.query_current` | Текущие запросы | > capacity |
| `search.fetch_time_in_millis` | Время fetch фазы | Рост latency |
| `search.scroll_current` | Активные scroll | > limit |

### JVM

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `jvm.mem.heap_used_percent` | Использование heap | > 85% |
| `jvm.gc.collectors.old.collection_count` | Old GC циклы | Частые |
| `jvm.gc.collectors.old.collection_time_in_millis` | Время Old GC | > 1s |
| `jvm.gc.collectors.young.collection_count` | Young GC циклы | Частые |

### Диск и хранилище

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `fs.total_in_bytes` | Общий размер диска | - |
| `fs.available_in_bytes` | Доступно | < 15% |
| `disk_threshold_enabled` | Watermark активен | true |
| `shard_stats.total_count` | Количество шардов | > limit per node |

### Thread Pools

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `thread_pool.write.queue` | Очередь записи | > 200 |
| `thread_pool.write.rejected` | Отклоненные записи | > 0 |
| `thread_pool.search.queue` | Очередь поиска | > 500 |
| `thread_pool.search.rejected` | Отклоненные поиски | > 0 |
| `thread_pool.management.queue` | Очередь управления | > 10 |

## Метрики Logstash

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `logstash_stats.logstash.uuid` | Инстанс | - |
| `logstash_stats.events.in` | Входящие события | Аномалии |
| `logstash_stats.events.out` | Исходящие события | < events.in |
| `logstash_stats.events.filtered` | Отфильтрованные | - |
| `logstash_stats.events.queue_duration_in_millis` | Время в очереди PQ | Рост |
| `logstash_stats.reload.successes` | Успешные перезагрузки | - |
| `logstash_stats.reload.failures` | Ошибки перезагрузки | > 0 |
| `logstash_stats.jvm.mem.heap_used_percent` | Heap | > 85% |
| `logstash_stats.pipelines.events` | По пайплайнам | - |

## Метрики Beats/Agent

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `beat.stats.libbeat.output.events.acked` | Подтвержденные события | - |
| `beat.stats.libbeat.output.events.dropped` | Потерянные события | > 0 |
| `beat.stats.libbeat.output.events.failed` | Ошибки отправки | > 0 |
| `beat.stats.libbeat.output.read.bytes` | Прочитано байт | - |
| `beat.stats.libbeat.output.read.errors` | Ошибки чтения | > 0 |
| `beat.stats.memstats.memory_alloc` | Память агента | Рост |

## Метрики Kibana

| метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `kibana_stats.requests.total` | Всего запросов | Аномалии |
| `kibana_stats.response_times.max` | Макс. время ответа | > порог |
| `kibana_stats.concurrent_connections` | Соединения | > limit |
| `kibana_stats.process.memory.heap.size_limit` | Heap limit | - |
| `kibana_stats.process.memory.resident_set_size_in_bytes` | RSS | Рост |

## Настройка алертинга по метрикам

### Пример: Алерт на Heap > 85%

```bash
PUT _watcher/elasticsearch/high-heap
{
  "trigger": { "schedule": { "interval": "5m" } },
  "condition": {
    "compare": {
      "ctx.payload.elasticsearch.cluster.stats.nodes.jvm.mem.heap_used_percent": {
        "gt": 85
      }
    }
  },
  "actions": {
    "log_alert": {
      "logging": {
        "text": "High heap usage detected: {% raw %}{{ctx.payload...}}{% endraw %}"
      }
    }
  }
}
```

### Пример: Алерт на Unassigned Shards

```bash
PUT _watcher/elasticsearch/unassigned-shards
{
  "trigger": { "schedule": { "interval": "1m" } },
  "condition": {
    "compare": {
      "ctx.payload.elasticsearch.cluster.health.unassigned_shards": {
        "gt": 0
      }
    }
  }
}
```

## API для получения метрик

### Cluster Health

```bash
GET _cluster/health
GET _cluster/health?level=indices
GET _cluster/health?level=shards
```

### Nodes Stats

```bash
GET _nodes/stats
GET _nodes/stats/jvm,os,fs,process,thread_pool,transport,http,breaker,script,discovery,ingest
GET _nodes/node-id1,node-id2/stats
```

### Index Stats

```bash
GET _stats
GET my-index/_stats
GET my-index/_stats/indexing,search,refresh,flush,merge,fielddata
```

### Pending Tasks

```bash
GET _cluster/pending_tasks
```

### Hot Threads

```bash
GET _nodes/hot_threads
GET _nodes/node-id/hot_threads?threads=10&interval=500ms
```

## Рекомендации по мониторингу

### Обязательные алерты

1. **Cluster status red** — немедленное оповещение
2. **Heap > 85%** — предупреждение о нехватке памяти
3. **Disk watermark** — приближение к лимиту диска
4. **Unassigned shards** — проблемы с распределением
5. **Thread pool rejections** — перегрузка кластера
6. **Search latency p99** — деградация поиска
7. **Indexing throttling** — проблемы с записью

### Retention для метрик

- **7 дней** — детальные метрики (10s interval)
- **30 дней** — агрегированные (1m interval)
- **90 дней** — hourly aggregates
- **1 год** — daily aggregates (для capacity planning)

### Выделенный Monitoring Cluster

Рекомендуется когда:
- Production кластер > 50 узлов
- Требуется высокая доступность мониторинга
- Мониторинг не должен влиять на production
- Необходимо хранить метрики дольше, чем production данные

## Troubleshooting через метрики

### Высокий Heap Usage

```
1. Проверить fielddata size: GET _nodes/stats/indices/fielddata
2. Проверить aggregations: тяжелые terms на high-cardinality
3. Проверить bulk size: слишком большие bulk запросы
4. Проверить segment count: много мелких сегментов
5. Решение: увеличить heap, оптимизировать запросы, force merge
```

### Высокий Search Latency

```
1. Проверить thread_pool.search.queue
2. Проверить cache hit ratio: GET _stats/query_cache,request_cache
3. Проверить slow logs: index.search.slowlog
4. Проверить circuit breaker trips
5. Решение: оптимизировать запросы, увеличить ресурсы, кэширование
```

### Indexing Throttling

```
1. Проверить thread_pool.write.rejected
2. Проверить merge throttle: GET _tasks?actions=*merge*
3. Проверить disk I/O
4. Проверить refresh_interval
5. Решение: увеличить refresh_interval, оптимизировать bulk size
```

## Интеграция с внешними системами

### Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'elasticsearch'
    metrics_path: '/_prometheus/metrics'
    static_configs:
      - targets: ['elasticsearch:9200']
```

### Grafana

- Официальный dashboard: [Elasticsearch](https://grafana.com/grafana/dashboards/elasticsearch-overview)
- Использовать Elasticsearch data source в Grafana для прямых запросов

### PagerDuty / Opsgenie

Интеграция через Kibana Alerting actions или Watcher webhook.

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера.
* **[Alerting](./elasticsearch_alerting.md)** — настройка алертов по метрикам.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов на основе метрик.
* **[Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md)** — диагностика проблем.
* **[Beats Family](./beats_family.md)** — Metricbeat для сбора метрик.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — Stack Monitoring UI.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты для мониторинга.
