# Наблюдаемость HTTP-сервисов

## Определения

**Наблюдаемость (Observability)** — способность понять внутреннее состояние системы по её внешним outputs (метрики, логи, трассировки). В контексте HTTP-сервисов observability строится на трёх китах: **метрики**, **логи**, **трассировки**.

**RED Method** — методология мониторинга микросервисов от Tom Wilkie:
- **Rate** — количество запросов в секунду (RPS).
- **Errors** — процент ошибок (4xx/5xx).
- **Duration** — распределение времени ответа (latency).

**Golden Signals** — методология Google SRE для мониторинга любого сервиса:
- **Latency** — время обработки запросов (среднее, p95, p99).
- **Traffic** — нагрузка на сервис (RPS, bandwidth).
- **Errors** — процент неуспешных запросов.
- **Saturation** — утилизация ресурсов (CPU, RAM, file descriptors, connections).

**SLI/SLO/SLA** — иерархия целевых показателей:
- **SLI (Service Level Indicator)** — метрика надёжности (например, доля 2xx-ответов).
- **SLO (Service Level Objective)** — целевое значение SLI за период (например, 99.9% 2xx за 30 дней).
- **SLA (Service Level Agreement)** — контракт с пользователем; нарушение SLA влечёт штрафы.

**Distributed Tracing** — технология отслеживания запроса через множество сервисов. Трассировка состоит из **Span** (один сервис/операция) и **Trace** (цепочка Span'ов, связанных `Trace-ID`).

## Основные концепции

### Метрики HTTP-сервисов

| Метрика | Источник | Тип | Назначение |
| :--- | :--- | :--- | :--- |
| `http_requests_total` | Nginx/HAProxy, Prometheus exporter | Counter | Общее число запросов (Rate) |
| `http_request_duration_seconds` | Nginx/HAProxy, app metrics | Histogram | Распределение latency (Duration) |
| `http_requests_failed_total` | Nginx/HAProxy | Counter | Ошибки 4xx/5xx (Errors) |
| `http_requests_by_status` | Nginx/HAProxy | Counter | Распределение по кодам ответа |
| `http_upstream_response_time_seconds` | Nginx | Histogram | Latency бэкендов |
| `http_connection_count` | Nginx/HAProxy | Gauge | Активные соединения (Saturation) |
| `http_request_body_bytes` | Nginx/HAProxy | Counter/H counter | Размер тела запроса |
| `http_response_body_bytes` | Nginx/HAProxy | Counter/H counter | Размер тела ответа |

### Prometheus: scrape конфигурация

```yaml
scrape_configs:
  - job_name: 'nginx'
    static_configs:
      - targets: ['localhost:9113']  # nginx-prometheus-exporter

  - job_name: 'haproxy'
    static_configs:
      - targets: ['localhost:8404']  # haproxy-exporter

  - job_name: 'node_exporter'
    static_configs:
      - targets: ['localhost:9100']  # системные метрики
```

### Правила алертинга Prometheus

```yaml
groups:
  - name: http_alerts
    rules:
      - alert: HighErrorRate
        expr: sum(rate(http_requests_failed_total[5m])) / sum(rate(http_requests_total[5m])) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Error rate > 5%"
          description: "Error rate is {{ $value | humanizePercentage }}"

      - alert: HighLatency
        expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le)) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "p99 latency > 1s"

      - alert: DownstreamDown
        expr: up{job="haproxy"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "HAProxy is down"
```

### Grafana Dashboard: ключевые панели

| Панель | Метрика | Вид |
| :--- | :--- | :--- |
| **RPS** | `sum(rate(http_requests_total[1m]))` | Graph (Time series) |
| **Error Rate %** | `sum(rate(http_requests_failed_total[5m])) / sum(rate(http_requests_total[5m])) * 100` | Gauge |
| **p50/p95/p99 Latency** | `histogram_quantile(0.5/0.95/0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))` | Graph |
| **Status Codes** | `sum by (status) (rate(http_requests_total[5m]))` | Pie chart / Bar gauge |
| **Upstream Latency** | `histogram_quantile(0.99, sum(rate(http_upstream_response_time_seconds_bucket[5m])) by (le, upstream))` | Heatmap |
| **Active Connections** | `http_connection_count` | Graph |
| **Bandwidth** | `sum(rate(http_response_body_bytes[5m])) / 1024 / 1024` | Graph (MB/s) |

### Распределённые трассировки

| Концепт | Инструмент | Назначение |
| :--- | :--- | :--- |
| **Trace ID** | W3C Trace Context (`traceparent`), Jaeger | Уникальный идентификатор запроса через все сервисы |
| **Span** | OpenTelemetry, Jaeger, Zipkin | Операция внутри сервиса (HTTP-запрос, DB-запрос) |
| **Propagation** | B3, W3C Trace Context, Jaeger | Передача Trace-ID через HTTP-заголовки |
| **Sampling** | Head-based, Tail-based | Обрезка трасс для снижения overhead |
| **Instrumentation** | OpenTelemetry SDK, middleware | Автоматический сбор спанов из HTTP-серверов |

## Практические сценарии

### Сценарий 1: Настройка nginx-prometheus-exporter

Экспорт метрик `stub_status` Nginx в Prometheus:

```bash
# Запуск exporter
docker run -d \
  --name nginx-exporter \
  --network=host \
  nginx/nginx-prometheus-exporter:latest \
  -nginx.scrape-uri=http://localhost/nginx_status
```

Конфиг Nginx для `stub_status`:
```nginx
server {
    listen 127.0.0.1:80;
    server_name _;

    location /nginx_status {
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Валидация:**
- `curl http://localhost:9113/metrics | grep nginx_` — метрики присутствуют.
- В Prometheus Targets: статус `UP`.

### Сценарий 2: HAProxy Prometheus exporter

Включение stats socket в HAProxy:
```haproxy
global
    stats socket /var/run/haproxy.sock level admin expose-fd listeners

frontend http-in
    bind *:80
    default_backend api_servers

backend api_servers
    balance roundrobin
    server app1 10.0.1.10:8080 check
    server app2 10.0.1.11:8080 check
```

Экспорт через `prometheus-haproxy-exporter`:
```bash
docker run -d \
  --name haproxy-exporter \
  --network=host \
  --volume /var/run/haproxy.sock:/var/run/haproxy.sock \
  prom/haproxy-exporter:latest
```

**Валидация:**
- `curl http://localhost:9101/metrics | grep haproxy_` — метрики HAProxy присутствуют.

### Сценарий 3: Alertmanager: уведомления при падении SLO

Конфигурация Alertmanager для pager-duty и Slack:

```yaml
route:
  group_by: ['alertname', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'slack-critical'

receivers:
  - name: 'slack-critical'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/...'
        channel: '#sre-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ .CommonAnnotations.description }}'
```

**Валидация:**
- Искусственный вызов alert (например, остановка сервиса).
- Проверка канала Slack: сообщение доставлено за <1 минуту.

### Сценарий 4: Grafana Dashboard для HTTP-сервиса

Импорт готового дашборда или создание кастомного:

| Панель | PromQL |
| :--- | :--- |
| RPS | `sum(rate(http_requests_total[1m]))` |
| Error Rate | `sum(rate(http_requests_failed_total[5m])) / sum(rate(http_requests_total[5m])) * 100` |
| p99 Latency | `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))` |
| Top 5 endpoints by RPS | `topk(5, sum(rate(http_requests_total[5m])) by (uri))` |
| Upstream latency heatmap | `histogram_quantile(0.99, sum(rate(http_upstream_response_time_seconds_bucket[5m])) by (le, upstream))` |

**Валидация:**
- Дашборд обновляется реальными данными без задержок >30 секунд.
- Панели коррелируют: всплеск latency совпадает с ростом 5xx.

### Сценарий 5: Distributed Tracing с OpenTelemetry

Автоматическая инструментация Nginx + приложения:

```yaml
# OpenTelemetry Collector
receivers:
  otlp:
    protocols:
      grpc:
      http:

exporters:
  jaeger:
    endpoint: jaeger:14250
  prometheus:
    endpoint: prometheus:9090

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [jaeger]
    metrics:
      receivers: [otlp]
      exporters: [prometheus]
```

Приложение (Python FastAPI):
```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider

trace.set_tracer_provider(TracerProvider())
FastAPIInstrumentor.instrument_app(app)
```

**Валидация:**
- Отправка запроса: `curl http://api/users/123`.
- В Jaeger UI: Trace с 2 спанами (Nginx → FastAPI → DB).
- Header `traceparent` присутствует в запросе к бэкенду.

### Сценарий 6: SLO/SLA для HTTP-сервиса

Определение SLO:

| SLO | Цель | Период | Действие при нарушении |
| :--- | :--- | :--- | :--- |
| **Availability** | 99.9% 2xx-ответов | 30 дней | Page на-call, если < 99.9% |
| **Latency** | p99 < 500ms | 30 дней | Инцидент, если p99 > 500ms более 1% запросов |
| **Error Budget** | 0.1% ошибок | 30 дней | При исчерпании — freeze deploys |

Расчёт Error Budget:
```python
# 99.9% availability за 30 дней
total_requests_per_month = 10_000_000
error_budget = total_requests_per_month * (1 - 0.999)  # 10 000 ошибок
```

**Валидация:**
- Grafana панель с текущим Error Budget: `(1 - sum(increase(http_requests_failed_total[30d])) / sum(increase(http_requests_total[30d])))`.
- Alert при исчерпании >80% бюджета.

### Сценарий 7: SRE Golden Signals Dashboard

Дашборд по 4 сигналам:

| Signal | Метрика | Alert |
| :--- | :--- | :--- |
| **Latency** | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))` | p99 > 1s |
| **Traffic** | `sum(rate(http_requests_total[5m]))` | Резкое падение RPS (>50%) |
| **Errors** | `sum(rate(http_requests_failed_total[5m])) / sum(rate(http_requests_total[5m]))` | >5% за 2m |
| **Saturation** | `node_filesystem_avail_bytes / node_filesystem_size_bytes` | <15% свободного места |

**Валидация:**
- Дашборд показывает все 4 сигнала в реальном времени.
- При остановке бэкенда: рост Errors, падение Traffic, рост Latency (queue), рост Saturation (очередь).

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Metric cardinality explosion** | Prometheus OOM, высокий usage | `promtool tsdb analyze` — высокие cardinality labels | Убрать `user_id`, `request_id` из labels; использовать values |
| **Missing Trace IDs** | Трассировки обрываются на прокси | `grep -c "traceparent" /var/log/nginx/access.log` | Включить `proxy_set_header traceparent $opentracing_traceid;` |
| **Scrape gap** | Пропуски в графиках метрик | `up{job="nginx"} == 0` | Проверить сеть, `scrape_timeout`, `scrape_interval` |
| **High latency, low error rate** | p99 растёт, но 5xx нет | `histogram_quantile(0.99, rate(...))` vs `rate(http_requests_total)` | Проверить бэкенд, БД, внешние API |
| **Error rate spike без 5xx** | Ошибки клиентов (4xx) | `sum by (status) (rate(http_requests_total[5m]))` | 401/403 — проблемы с аутентификацией/авторизацией |
| **Saturation spike** | connections_maxed | `http_connection_count` vs `worker_connections` | Увеличить `worker_connections` или добавить воркеры |
| **Cascading failure** | Один бэкенд убивает все остальные | Трассировки: длинные latency → connection pool exhaustion | Circuit breaker, bulkhead pattern |
| **Prometheus retention overflow** | Метрики старше 30 дней исчезают | `promtool tsdb analyze` — retention | Увеличить `--storage.tsdb.retention.time` |
| **Grafana time drift** | Панели показывают разное время | Настройки Time range в дашборде | Использовать `$__from`/`$__to` |
| **Tracing overhead** | Latency выросла на 10–20% после включения tracing | `ab` до/после instrumentation | Настроить sampling rate (1% или 10%) |

## Лучшие практики

1. **RED для каждого HTTP-сервиса:** Создавайте отдельные дашборды для каждого сервиса. Не смешивайте метрики Nginx и приложения на одной панели.
2. **Histogram с правильными buckets:** Для latency используйте buckets `[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]`. Для SLO 99.9% используйте `[0.1, 0.5, 1, 5]`.
3. **SLO с Error Budget:** Определите SLO до того, как произойдёт инцидент. Error Budget — ваш «топливо» для изменений.
4. **Alerting на основе SLO, а не на основе интуиции:** `rate(errors[5m]) > 0.01` лучше, чем `502 > 10`.
5. **Trace ID propagation:** Гарантируйте, что `traceparent` (W3C) или `X-B3-TraceId` (B3) передаётся через все прокси (Nginx `proxy_set_header traceparent $opentracing_traceid;`).
6. **Structured logging в JSON:** Облегчает парсинг и корреляцию с метриками и трассировками.
7. **Golden Signals дашборд:** Каждый сервис должен иметь панель с 4 сигналами (Latency, Traffic, Errors, Saturation).
8. **Correlation ID (Request ID):** Генерация `$request_id` в Nginx и передача в заголовке `X-Request-ID`. Позволяет связать лог, метрику и трассу.
9. **Prometheus recording rules:** Для сложных PromQL создайте recording rules, чтобы ускорить запросы и снизить нагрузку на Prometheus.
10. **Alert fatigue prevention:** Каждый alert должен быть actionable. Если alert не требует реакции — удалите его.
11. **Runbook для каждого alert:** Документируйте шаги диагностики для каждого alert (кто дергать, где смотреть, как фиксить).
12. **Grafana переменные:** Используйте переменные (`$service`, `$namespace`) для универсальных дашбордов.

## Граничные случаи и ограничения

1. **Histogram buckets и memory:** Каждый bucket создаёт серию в Prometheus. Слишком много buckets → high cardinality → OOM. Используйте 10–15 buckets.
2. **Counter reset при redeploy:** Prometheus counter сбрасывается при перезапуске процесса. Используйте `rate()` или `increase()`, а не `delta()`.
3. **Tracing overhead:** Distributed Tracing добавляет 5–15% latency при 100% sampling. Используйте tail-based sampling или probabilistic sampling (1–10%).
4. **Log volume explosion:** JSON-логи с correlation ID увеличивают объём в 2–3 раза. Настройте logrotate и retention (7–30 дней).
5. **SLO и праздники:** Black Friday/Cyber Monday дают всплески трафика. Учитывайте seasonality в SLO-окне или используйте rolling windows.
6. **Multi-cluster Prometheus:** Federated Prometheus или Thanos для глобального обзора. Осторожно с global recording rules.
7. **Alert storm:** При массовом отказе (например, дата-центр) приходит сотни алертов. Настройте `group_by` и `group_wait` в Alertmanager.
8. **Latency distribution vs average:** Среднее (average) скрывает p99. `mean + 3 sigma` тоже ненадёжно. Используйте percentiles.
9. **Error budget и внешние зависимости:** Если SRE управляет только своим сервисом, но 50% ошибок — от внешнего API, error budget быстро исчерпывается. Определите границы ответственности.
10. **Prometheus remote write и cost:** Хранение 30 дней метрик для 1000 инстансов может стоить дорого. Используйте Thanos/Cortex с tiered storage.

## Дополнительная информация

### Сравнение OpenTelemetry, Jaeger и Zipkin

| Инструмент | Статус | Особенности |
| :--- | :--- | :--- |
| **OpenTelemetry** | CNCF (graduated) | Унифицированный SDK + Collector; поддерживает traces, metrics, logs |
| **Jaeger** | CNCF (graduated) | Визуализация traces; storage: Cassandra, Elasticsearch, Kafka |
| **Zipkin** | Mature | Простой, легковесный; storage: MySQL, Cassandra, Elasticsearch |
| **Prometheus** | CNCF (graduated) | Метрики; не поддерживает traces natively |

**Рекомендация:** Используйте OpenTelemetry для instrumentation (единый SDK), Jaeger для визуализации traces, Prometheus для metrics.

### Маршрутизация Alertmanager

```yaml
route:
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty'
    - match:
        service: api
      receiver: 'slack-api'
    - match:
        service: frontend
      receiver: 'slack-frontend'
```

### SLI примеры для HTTP-сервисов

| SLI | Формула | SLO |
| :--- | :--- | :--- |
| **Availability** | `sum(rate(http_requests_failed_total[30d])) / sum(rate(http_requests_total[30d]))` | < 0.1% |
| **Latency** | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[30d]))` | < 500ms |
| **Throughput** | `sum(rate(http_requests_total[5m]))` | > 1000 RPS |

## Смотрите также

- **[Коды ответа HTTP](./http_status_codes.md)** — диагностика 4xx/5xx.
- **[HTTP-серверы и прокси](./http_servers_proxies.md)** — конфигурация Nginx/HAProxy.
- **[Rate Limiting и устойчивость](./http_rate_limiting_circuit_breakers.md)** — защита от перегрузки.
- **[Логирование и инструменты диагностики](./http_logging_troubleshooting_tools.md)** — анализ логов и трафика.
- **[Конфигурация Nginx](../../../WebServers/Nginx/Core/nginx_overview.md)** — мониторинг через stub_status.
- **[Концепции SRE: SLA, SLO, SLI](../../../Concepts/sre_concepts_main.md)** — методология надёжности.
