# Stack Monitoring: Мониторинг Elastic Stack

**Актуально для:** Elasticsearch 8.x / 9.x (Elasticsearch Monitoring plugin deprecated, удаление в 10.0)

> **Статус:** Elasticsearch Monitoring plugin (внутренний сбор `xpack.monitoring.collection.*`) deprecated и будет удалён в 10.0. Рекомендуемые подходы: **Elastic Agent** (рекомендуется) или **Metricbeat**; в Elastic Cloud Hosted / Serverless / ECE / ECK — **AutoOps**. Legacy-сбор через internal exporters — не рекомендуется; при наличии — мигрировать на Agent/Metricbeat.
>
> Руководство по мониторингу Elastic Stack: архитектура сбора, настройка, ключевые метрики, диагностические API, алертинг и интеграции.
>
> Связанные темы: capacity planning — [Capacity Planning](./elasticsearch_capacity_planning.md); траблшутинг — [Troubleshooting](./elasticsearch_troubleshooting_indexing.md); алертинг — [Alerting](./elasticsearch_alerting.md); watermarks и allocation — [Обзор](./elasticsearch_overview.md); slow logs и circuit breakers — [Search Tuning](./elasticsearch_search_tuning.md).

## Определения

* **Stack Monitoring** — функциональность Kibana для визуализации состояния кластеров Elasticsearch, Logstash, Beats, Kibana, APM Server. Данные хранятся в Elasticsearch и отображаются на странице **Stack Monitoring** (Kibana → глобальный поиск).
* **Monitoring Cluster** — кластер Elasticsearch для хранения метрик мониторинга: тот же (internal collection) или выделенный (Metricbeat/Agent шлют данные напрямую).
* **Collector** — компонент, раз в collection interval опрашивающий публичные API Elasticsearch. Все collectors запускаются однопоточным планировщиком на каждом узле.
* **Exporter** — компонент, маршрутизирующий собранные данные в monitoring cluster: `local` (индексация в свой кластер, default) или `http` (отправка в отдельный кластер).
* **Internal Collection (legacy)** — сбор метрик самим Elasticsearch через exporters. Deprecated с 7.16, удаление в 10.0.
* **Agent/Metricbeat Collection** — сбор метрик Elastic Agent (рекомендуется, управляется централизованно через Fleet) или Metricbeat (лёгкий shipper; предпочтителен при существующих инвестициях в Beats).
* **Persistent UUID** — идентификатор мониторируемого компонента, записываемый в `path.data` при старте; по нему компонент уникален в Stack Monitoring UI.
* **Monitoring documents** — обычные JSON-документы, строимые каждым компонентом с заданным интервалом и индексируемые в `.monitoring-*` индексы.
* **AutoOps** — инструмент мониторинга (Elastic Cloud Hosted, Serverless, ECE, ECK, self-managed): детекция проблем в реальном времени, пути решения, утилизация ресурсов, рекомендации по производительности.

## Предварительные требования

1. **Привилегии Elasticsearch** (при включённых security features):
   * `monitor` или `manage` cluster privilege — для чтения `_cluster/health`, `_nodes/stats`, `_nodes/hot_threads`, `_cluster/allocation/explain`.
   * `monitor` — для просмотра cluster settings; `manage` — для изменения (включение сбора).
   * Встроенные роли: `remote_monitoring_collector` (сбор данных с production-кластера), `remote_monitoring_agent` (запись в `.monitoring-*` на monitoring-кластере), `monitoring_user` (чтение monitoring-индексов + базовая информация о кластере + все Kibana-привилегии Stack Monitoring; назначать вместе с `kibana_admin`).
   * Встроенный пользователь `remote_monitoring_user` (пароль задаётся через `elasticsearch-setup-passwords`) — комбинирует роли для сбора и записи.
2. **Kibana**: Stack Monitoring включён по умолчанию, но сбор данных выключен; при первом входе предлагается включить (требуется `cluster:manage` — есть у `elastic`). Для алертинга — TLS на HTTP-интерфейсе Kibana (см. [Alerting](./elasticsearch_alerting.md)).
3. **Версии**: monitoring-кластер и мониторируемые кластеры должны работать на одной версии стека. Monitoring-кластер не может мониторить кластеры новее себя; допустим latest release предыдущего major.
4. **Лицензия**: для маршрутизации данных нескольких production-кластеров в один monitoring-кластер требуется соответствующая подписка. Built-in cluster alerts (Watcher watches) требуют Watcher (Platinum).

## Как работает

```
Monitored component (ES / Kibana / Logstash / Beats / APM)
   │  collector: раз в interval опрашивает публичные API
   ▼
Exporter (local → свой кластер | http → monitoring cluster)
   │  bulk-запросы с placeholder pipeline (use_ingest: true)
   ▼
.monitoring-* индексы (daily: .monitoring-es-8-2026.10.05)
   │
   ▼
Kibana Stack Monitoring (чтение, визуализация, алерты)
```

* Каждый collector запускается один раз за collection interval; данные передаются exporter'ам. Независимо от числа exporter'ов collector запускается один раз.
* Stack-level «collector» для данных Kibana/Beats/Logstash/APM живёт вне collection interval Elasticsearch и не зависит от `xpack.monitoring.collection.interval`.
* **Важно:** при `xpack.monitoring.collection.enabled: false` (default) не собираются данные Elasticsearch **и игнорируются данные из всех остальных источников** (Kibana, Beats, Logstash) — типичная причина «пустого» Stack Monitoring.
* Логи компонентов собираются отдельно — Filebeat (рекомендуется) или legacy-методами.

## Архитектура

### Вариант 1: Elastic Agent (рекомендуется)

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Elastic Agent│────▶│ Monitoring       │────▶│   Kibana    │
│ (Fleet-      │     │  Cluster         │     │ (visualize) │
│  managed)    │     │ (dedicated)      │     │             │
└──────────────┘     └──────────────────┘     └─────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│ Production Cluster (Elasticsearch)      │
└─────────────────────────────────────────┘
```

Один агент собирает логи и метрики, управляется централизованно через Fleet. Для Kibana и Logstash — Agent на каждом инстансе.

### Вариант 2: Metricbeat (альтернатива)

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Metricbeat  │────▶│ Monitoring       │────▶│   Kibana    │
│ (collector)  │     │  Cluster         │     │ (visualize) │
└──────────────┘     └──────────────────┘     └─────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│ Production Cluster (Elasticsearch)      │
└─────────────────────────────────────────┘
```

Metricbeat на каждом узле production-кластера; данные шлёт напрямую в monitoring-кластер, не нагружая production.

### Вариант 3: Internal Collection (legacy, deprecated)

```
┌──────────────┐
│ Elasticsearch│──▶ Метрики в .monitoring-* (local exporter)
│  (monitored) │
└──────────────┘
         │
         ▼
┌──────────────┐
│    Kibana    │◀── Чтение из .monitoring-* и визуализация
└──────────────┘
```

Метрики индексируются в тот же кластер. Не рекомендуется: нагружает production и deprecated (удаление в 10.0).

## Настройка Stack Monitoring

### Elastic Agent (рекомендуется)

1. Установить Elastic Agent на узлах Elasticsearch/Kibana/Logstash (или Fleet Server — централизованно).
2. Включить integration `Elasticsearch` (metrics + logs) и `Kibana`.
3. Настроить output Agent'а на monitoring-кластер.
4. В Kibana: **Stack Monitoring** → данные появятся автоматически.

### Metricbeat

```yaml
# modules.d/elasticsearch.yml
- module: elasticsearch
  metricsets:
    - ccr
    - cluster_stats
    - index
    - index_recovery
    - index_summary
    - ml_job
    - node_stats
    - shard
  period: 10s
  hosts: ["http://localhost:9200"]
  username: "remote_monitoring_user"   # или пользователь с ролью remote_monitoring_collector
  password: "${ES_MONITORING_PASSWORD}"
  xpack.enabled: true
```

```yaml
# metricbeat.yml — output на monitoring-кластер
output.elasticsearch:
  hosts: ["https://monitoring-es:9200"]
  username: "remote_monitoring_user"   # или пользователь с ролью remote_monitoring_agent
  password: "${MONITORING_ES_PASSWORD}"
  ssl.certificate_authorities: ["/path/to/ca.crt"]
```

```bash
metricbeat modules enable elasticsearch
# Опционально: данные system-модуля не отображаются в Stack Monitoring
metricbeat modules disable system
```

**Обязательно:** отключить legacy-внутренний сбор на production-кластере, иначе метрики собираются дважды:

```json
PUT _cluster/settings
{
  "persistent": {
    "xpack.monitoring.elasticsearch.collection.enabled": false
  }
}
```

Для Kibana — модуль `kibana-xpack` (`metricsets: [stats]`, `period: 10s`, `hosts: ["localhost:5601"]`, `xpack.enabled: true`) и отключение внутреннего сбора Kibana: `monitoring.kibana.collection.enabled: false` в `kibana.yml` (значение `monitoring.enabled` оставить `true`).

### Internal Collection (legacy — elasticsearch.yml)

```yaml
# На monitored-кластере (deprecated, удаление в 10.0)
xpack.monitoring.collection.enabled: true
xpack.monitoring.collection.interval: 10s
```

| Настройка | Default | Описание |
|---|---|---|
| `xpack.monitoring.collection.enabled` | `false` | Включить сбор. При `false` игнорируются данные и из Kibana/Beats/Logstash |
| `xpack.monitoring.collection.interval` | `10s` | Интервал сэмплирования. При изменении — поставить `monitoring.ui.min_interval_seconds` в `kibana.yml` в то же значение |
| `xpack.monitoring.elasticsearch.collection.enabled` | `true` | Только ES-статистика; остальные источники проходят дальше |
| `xpack.monitoring.collection.indices` | все индексы | Какие индексы мониторить: `.*,test*,-test3`. Системные индексы (`.security*`, `.kibana*`) обычно следует мониторить — включайте `.*` |
| `xpack.monitoring.collection.cluster.stats.timeout` | `10s` | Timeout сбора cluster stats |
| `xpack.monitoring.collection.node.stats.timeout` | `10s` | Timeout сбора node stats |
| `xpack.monitoring.collection.index.stats.timeout` | `10s` | Timeout сбора index stats |
| `xpack.monitoring.collection.index.recovery.active_only` | `false` | Только активные recoveries |
| `xpack.monitoring.collection.index.recovery.timeout` | `10s` | Timeout сбора recovery |

Настройки динамические (`PUT _cluster/settings`), кроме `xpack.monitoring.exporters` (static).

### Доступ к данным в Kibana

1. По умолчанию данные читаются из кластера в `elasticsearch.hosts` (`kibana.yml`). Для выделенного monitoring-кластера — `monitoring.ui.elasticsearch.hosts` + `monitoring.ui.elasticsearch.username/password`.
2. `monitoring.ui.enabled: true` (default). При отдельном monitoring-кластере включать сбор не нужно — дашборды появятся, когда в кластере появятся данные.
3. Kibana → глобальный поиск → **Stack Monitoring**.

## Хранение данных мониторинга

* Индексы создаются ежедневно: `.monitoring-es-8-<yyyy.MM.dd>` (формат суффикса — `index.name.time_format`, default `yyyy.MM.dd`).
* **Retention:** `xpack.monitoring.history.duration` — default `7d`, минимум `1d`. Удаляет старые индексы **только для `local`-экспортёров**; индексы `http`-экспортёра не удаляются автоматически — настраивайте ILM на monitoring-кластере.
* Default exporter — `xpack.monitoring.exporters.default_local` (`type: local`); если задан хоть один exporter, default не создаётся.
* HTTP exporter: `type: http`, `host` (можно массив), `auth.username` + `auth.secure_password` (secure setting), `connection.timeout` (default `6s`), `connection.read_timeout` (default `10 × connection.timeout`), `headers`, `proxy.base_path`, TLS-настройки (`ssl.verification_mode` default `full`).
* **Built-in cluster alerts:** при `cluster_alerts.management.enabled: true` (default) exporter создаёт Watcher watches: `elasticsearch_cluster_status`, `elasticsearch_version_mismatch`, `elasticsearch_nodes`, `kibana_version_mismatch`, `logstash_version_mismatch`, `xpack_license_expiration`. Требуется Watcher (Platinum); на Basic-лицензии алерты не отображаются. Отключение отдельных алертов — `cluster_alerts.management.blacklist`.

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

Механика watermarks (low 85% / high 90% / flood_stage 95%) и снятие блока `read_only_allow_delete` — в [Обзоре](./elasticsearch_overview.md) и [Troubleshooting](./elasticsearch_troubleshooting_indexing.md).

### Thread Pools

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `thread_pool.write.queue` | Очередь записи | > 200 |
| `thread_pool.write.rejected` | Отклоненные записи | > 0 |
| `thread_pool.search.queue` | Очередь поиска | > 500 |
| `thread_pool.search.rejected` | Отклоненные поиски | > 0 |
| `thread_pool.management.queue` | Очередь управления | > 10 |

### OS, Process, Circuit Breaker, Merge/Refresh

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `os.cpu.percent` | CPU узла | > 80% |
| `os.load_average.1m` | Load average | > число ядер |
| `os.mem.used_percent` | Память хоста | > 90% |
| `process.cpu.percent` | CPU процесса ES | Рост |
| `process.open_file_descriptors` | Открытые FD | > 80% от `max_file_descriptors` |
| `breakers.<name>.tripped` | Срабатывания breaker | > 0 |
| `breakers.<name>.memory_used_in_bytes` | Память breaker | близко к `memory_limit_in_bytes` |
| `indices.merges.current` | Активные merges | Рост |
| `indices.refresh.total_time_in_millis` | Время refresh | Рост latency |
| `indices.flush.total_time_in_millis` | Время flush | Рост |

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

| Метрика | Описание | Пороги алертов |
|---------|----------|----------------|
| `kibana_stats.requests.total` | Всего запросов | Аномалии |
| `kibana_stats.response_times.max` | Макс. время ответа | > порог |
| `kibana_stats.concurrent_connections` | Соединения | > limit |
| `kibana_stats.process.memory.heap.size_limit` | Heap limit | - |
| `kibana_stats.process.memory.resident_set_size_in_bytes` | RSS | Рост |

## API для получения метрик

### Cluster Health и Stats

```bash
GET _cluster/health
GET _cluster/health?level=indices
GET _cluster/health?level=shards
GET _cluster/health?wait_for_status=green&timeout=30s
GET _cluster/stats
GET _cluster/pending_tasks
```

### Nodes

```bash
GET _nodes/stats
GET _nodes/stats/jvm,os,fs,process,thread_pool,transport,http,breaker,script,discovery,ingest
GET _nodes/node-id1,node-id2/stats
GET _nodes/usage          # включённые features
GET _nodes/hot_threads    # горячие потоки (plain text)
GET _nodes/node-id/hot_threads?threads=10&interval=500ms&type=cpu
```

Параметры `hot_threads`: `threads` (default 3; для траблшутинга ставьте большое, например 9999 — все потоки), `interval` (default 500ms, второй сэмпл), `snapshots` (default 10), `type` — `cpu` (default) | `wait` | `block`, `ignore_idle_threads` (default true — фильтрует idle-потоки), `timeout`. Требует `monitor` или `manage` cluster privilege.

### Index Stats

```bash
GET _stats
GET my-index/_stats
GET my-index/_stats/indexing,search,refresh,flush,merge,fielddata
GET _stats/query_cache,request_cache   # cache hit ratio
GET _nodes/stats/indices/fielddata
GET _nodes/stats/breaker               # circuit breaker trips
```

### Диагностика шардов и задач

```bash
GET _cluster/allocation/explain        # почему шард unassigned / не перебалансируется
GET _cluster/allocation/explain?include_disk_info=true&include_yes_decisions=true
# Тело: {"index": "my-index-000001", "shard": 0, "primary": true}
# 400, если unassigned шардов нет
GET _tasks?actions=*search&detailed    # длительные запросы
GET _cat/nodes?v&h=name,heap.percent,cpu,load_1m,disk.used_percent
GET _cat/indices?v&s=store.size:desc
GET _cat/allocation?v&h=node,disk.percent,disk.used,disk.avail,disk.total
GET _cat/shards?v
GET _cat/segments?v
GET _cat/recovery?v
GET _cat/thread_pool?v&h=node_name,write,search
GET _cat/pending_tasks?v
```

`_cluster/allocation/explain` для unassigned шарда возвращает `unassigned_info.reason` (например, `NODE_LEFT`, `INDEX_CREATED`), `can_allocate` и `node_allocation_decisions` с объяснением каждого decider'а. Механика watermarks и типичные причины — в [Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md).

### Slow logs

Конфигурация порогов (`index.search.slowlog.threshold.query.warn` и т.д., default `-1` — выключено), уровни и расположение файлов — в [Search Tuning](./elasticsearch_search_tuning.md). В Kibana: Stack Monitoring → Elasticsearch → Search latency; для разового анализа конкретного запроса — Profile API и `GET _tasks?actions=*search&detailed`.

## Алертинг по метрикам

**Основная система — Kibana Alerting** (правила `.index-threshold` / `.es-query` на данных мониторинга, connectors Slack/Email/PagerDuty/Webhook): создание, action groups, throttling — в [Alerting](./elasticsearch_alerting.md). Stack Monitoring предоставляет готовые alerts на основе метрик стека.

**Watcher (legacy, Platinum)** — низкоуровневый контроль input/condition/action. Создание watch: `PUT _watcher/watch/<watch_id>` (требует `manage_watcher` cluster privilege / роль `watcher_admin`):

```bash
# Алерт на Heap > 85%
PUT _watcher/watch/high-heap
{
  "trigger": { "schedule": { "interval": "5m" } },
  "input": {
    "http": {
      "request": {
        "host": "localhost",
        "port": 9200,
        "path": "/_cluster/stats",
        "scheme": "http"
      }
    }
  },
  "condition": {
    "compare": {
      "ctx.payload.nodes.jvm.mem.heap_used_percent": { "gt": 85 }
    }
  },
  "actions": {
    "log_alert": {
      "logging": {
        "text": "High heap usage detected: {% raw %}{{ctx.payload.nodes.jvm.mem.heap_used_percent}}{% endraw %}%"
      }
    }
  }
}
```

```bash
# Алерт на Unassigned Shards
PUT _watcher/watch/unassigned-shards
{
  "trigger": { "schedule": { "interval": "1m" } },
  "input": {
    "http": {
      "request": { "host": "localhost", "port": 9200, "path": "/_cluster/health", "scheme": "http" }
    }
  },
  "condition": {
    "compare": { "ctx.payload.unassigned_shards": { "gt": 0 } }
  }
}
```

PagerDuty / Opsgenie — через connectors Kibana Alerting или Watcher webhook.

## Prometheus и Grafana

### Prometheus Remote Write (GA с 9.5, preview в 9.4)

Elasticsearch принимает метрики по протоколу Prometheus remote write и сохраняет их в TSDS:

```yaml
# prometheus.yml
remote_write:
  - url: "https://elasticsearch:9200/_prometheus/api/v1/write"
    authorization:
      type: ApiKey
      credentials: <api_key>
    # или basic_auth: {username: <user>, password: <password>}
```

* Endpoint `/_prometheus/api/v1/write` → data stream `metrics-generic.prometheus-default`; `/_prometheus/metrics/{dataset}/api/v1/write` → `metrics-{dataset}.prometheus-default`.
* Встроенный index template для `metrics-*.prometheus-*`: TSDS-режим, labels как passthrough-измерения, поле limit 10 000, failure store включён.
* Запросы — PromQL-функция в ES|QL.
* Для scrape-архитектуры (Prometheus опрашивает ES) используйте сторонний `prometheus-community/elasticsearch_exporter` — ES не предоставляет scrape-endpoint.

### Grafana

* Elasticsearch data source в Grafana — прямые запросы к кластеру (включая `.monitoring-*`).
* Dashboards: импортируйте актуальные ID с grafana.com (поиск «Elasticsearch»); ссылка на конкретный dashboard меняется, проверяйте актуальность.

## Рекомендации по мониторингу

### Обязательные алерты

1. **Cluster status red** — немедленное оповещение
2. **Heap > 85%** — предупреждение о нехватке памяти
3. **Disk watermark** — приближение к лимиту диска (см. watermarks в [Обзоре](./elasticsearch_overview.md))
4. **Unassigned shards** — проблемы с распределением
5. **Thread pool rejections** — перегрузка кластера
6. **Search latency p99** — деградация поиска
7. **Indexing throttling** — проблемы с записью

### Retention для метрик

Default retention monitoring-индексов — `7d` (`xpack.monitoring.history.duration`, минимум `1d`, только local-экспортёр). Рекомендуемая политика для долгосрочного хранения метрик (dedicated monitoring cluster / metrics store):

- **7 дней** — детальные метрики (10s interval)
- **30 дней** — агрегированные (1m interval)
- **90 дней** — hourly aggregates
- **1 год** — daily aggregates (для capacity planning)

### Выделенный Monitoring Cluster

Рекомендуется когда:

- Production кластер большой (ориентир: > 50 узлов) или мониторинг не должен влиять на production
- Требуется высокая доступность мониторинга
- Необходимо хранить метрики дольше, чем production данные
- Маршрутизация нескольких production-кластеров в один monitoring-кластер (требуется соответствующая лицензия)

В production настоятельно рекомендуется отдельный кластер для метрик. Учтите правило совместимости версий (см. Предварительные требования).

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
4. Проверить circuit breaker trips: GET _nodes/stats/breaker
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

### Мониторинг не собирает данные / Stack Monitoring пуст

```
1. GET _cluster/settings — проверить xpack.monitoring.collection.enabled
   (false = default: ES-данные не собираются И данные Kibana/Beats/Logstash игнорируются)
2. Проверить наличие .monitoring-* индексов: GET _cat/indices?v&filter_path=*.monitoring-*
3. Metricbeat/Agent: проверить output и credentials (remote_monitoring_user / remote_monitoring_agent)
4. Kibana: monitoring.ui.enabled, monitoring.ui.elasticsearch.hosts и credentials
5. Проверить, что интервал в elasticsearch.yml совпадает с monitoring.ui.min_interval_seconds
```

## Граничные случаи

* **Collection interval < 10s** — рост нагрузки: collectors запускаются однопоточным планировщиком на каждом узле.
* **`xpack.monitoring.collection.enabled: false`** — «сюрприз»: игнорируются данные всех источников, не только ES.
* **HTTP-экспортёр** — его индексы не удаляются по `xpack.monitoring.history.duration`; нужен ILM на monitoring-кластере.
* **Version drift** — monitoring-кластер не мониторит кластеры новее себя; только latest release предыдущего major.
* **Built-in cluster alerts** — требуют Watcher (Platinum); на Basic не отображаются.
* **`remote_monitoring_collector`** — по сообщению в issue elastic/elasticsearch#51677 (2020) не покрывает `_enrich/_stats` (HTTP 403); при использовании enrich проверьте доступ и при необходимости добавьте `manage_enrich` в кастомную роль.
* **Контейнеры** — `monitoring.ui.container.elasticsearch.enabled: true` в `kibana.yml`: Node Listing показывает CPU по Cgroup-статистике.
* **CCS для monitoring-данных** — `monitoring.ui.ccs.enabled: true` (default); требует роль `remote_cluster_client` на каждом узле.

## Best Practices и cleanup

1. Используйте Elastic Agent или Metricbeat; internal collection — только для legacy-кластеров до миграции.
2. При переходе на Agent/Metricbeat — отключайте внутренний сбор (`xpack.monitoring.elasticsearch.collection.enabled: false`), чтобы не собирать метрики дважды.
3. При изменении `xpack.monitoring.collection.interval` — синхронизируйте `monitoring.ui.min_interval_seconds` в `kibana.yml`.
4. Задайте пароль `remote_monitoring_user` (`elasticsearch-setup-passwords interactive`).
5. Очистка: старые `.monitoring-*` индексы удаляются автоматически (local-экспортёр, `xpack.monitoring.history.duration`); для ручной очистки — `DELETE <.monitoring-index>`. Полное отключение сбора: `xpack.monitoring.collection.enabled: false` (учтите эффект для других источников).
6. Валидация: `GET _cluster/settings` показывает `xpack.monitoring.collection.enabled: true`; `GET _cat/indices?v` содержит `.monitoring-es-*`; страница Stack Monitoring в Kibana отображает узлы и метрики.

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера, watermarks.
* **[Alerting](./elasticsearch_alerting.md)** — Kibana Alerting и Watcher: правила, connectors, actions.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов на основе метрик.
* **[Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md)** — диагностика проблем, allocation explain, watermarks.
* **[Search Tuning](./elasticsearch_search_tuning.md)** — slow logs, circuit breakers, cache stats.
* **[Beats Family](./beats_family.md)** — Metricbeat для сбора метрик.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — Stack Monitoring UI.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты для мониторинга.
