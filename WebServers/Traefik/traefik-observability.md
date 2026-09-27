# Наблюдаемость Traefik: метрики, трейсинг, логи

## Определения

**Entrypoint metrics** — метрики входящего трафика на entrypoint.

**Prometheus metrics** — экспорт стандартных метрик в формате Prometheus на отдельный эндпоинт (или на API-порт).

**AccessLog** — журнал HTTPS-сессий в форматах `common`/`logfmt`/`json` с гибкой настройкой полей.

**Tracing (OTLP)** — распределенная трассировка с экспортом в стандарт OTLP (в v3 единственный протокол).

**Dashboard/API** — REST API (read/write) с Dashboard на `:8080`.

**Metrics labels** — поля, агрегируемые по `service`, `route`, `entrypoint`, `code`.

## Базовые концепции

### Prometheus

Traefik отдает метрики на `http://host:9100/metrics` (дефолтный порт) или через entrypoint `metrics` (чаще выделенный, отдельный):

```yaml
metrics:
  prometheus:
    entryPoint: metrics          # отдельный слушатель
    addEntryPointsLabels: true
    addServicesLabels: true
    addRoutersLabels: true
    addServerLabels: false      # метки отдельных бэкендов (вкл. по желанию)
    manualRouting: true
    buckets: [0.1, 0.3, 1.2, 5] # исторические buckets latency
    # addInternalLabels: false   # (для Router цели по умолчанию)
    oversizeHostHeader: 4000
```

Основные метрики:

| Метрика | Назначение |
| :--- | :--- |
| `traefik_http_requests_total` | Число запросов по route/entrypoint/code |
| `traefik_http_requests_duration_seconds` | Гистограмма latency (p50/p90/p99) |
| `traefik_entrypoint_requests_total` | Общий трафик на entrypoint |
| `traefik_entrypoint_requests_tls_total` | TLS-запросы на entrypoint |
| `traefik_router_requests_total` | По роутерам |
| `traefik_service_requests_total` | По сервисам (ответы бэкендов) |
| `traefik_service_server_up` | «1» если сервер alive (по health check) |
| `traefik_config_reloads_total` / `traefik_config_last_reload_success` | Перезагрузки конфига |

### Grafana + черный мониторинг

Dashboard'ы и микросервис метрик — в [Галерея Grafana](https://grafana.com/grafana/dashboards/): официальный трафик `12446` (Traefik). Алерты (по `traefik_http_requests_total{code="5xx"}`), жилые анимированные панели — в [Kubernetes Gateway API Traefik](../../Kubernetes/Networking/gateway_api/traefik.md) (там же про K8s-развертывания).

### AccessLog

```yaml
accessLog:
  filePath: /var/log/traefik/access.log
  format: json          # logfmt (default) | json | common
  filters:
    statusCodes: [200, 301, 302]
    retryAttempts: true
    minDuration: 50ms
  fields:
    names:
      ClientUserName: keep
      ClientHost: keep
      ClientPort: drop
    headers:
      defaultMode: keep
      names:
        Authorization: redact
        Cookie: drop
```

Моды полей: `keep`, `drop`, `dropHead`, `dropTail`, `redact`. Полей много: `RequestHost`, `RequestPath`, `RequestMethod`, `RequestProtocol`, `RouterNames`, `ServiceName`, `Duration`, `RetryAttempts`, `RequestCount`, `DownstreamStatus`.

`bufferingSize` — размеры буфера по забытым большим запросам: `bufferingSize: 0` — отключить буферизацию (для стримов), `bufferingSize: 100` — 100 KiB.

### Tracing (OTLP)

Трейсы по HTTP/2 через OTLP/gRPC. В v3 поддерживается **только OpenTelemetry** (`--tracing.opentelemetry.address`):

```yaml
tracing:
  serviceName: "traefik"
  openTelemetry:
    address: otel-collector:4317
    insecure: true
    headers: 
      X-Token: "secret"
    # propagation: b3 | tracecontext|baggage (default tracecontext)
    podName: "traefik-replica-1"
```

Стек по умолчанию: Traefik → OTel Collector → Jaeger/Tempo/OTel Backend; `serviceName` будет в трейсе. ИД-эндпоинт `address` (GRPC) либо `http.address` (HTTP/OTLP).

## Практические сценарии

### Сценарий 1: Выделенный entrypoint для метрик + доступ извне

```yaml
entryPoints:
  metrics:
    address: ":9100"

metrics:
  prometheus:
    entryPoint: metrics
    addEntryPointsLabels: true
    addRoutersLabels: true

api:
  dashboard: true
  insecure: false   # безопасный (auth на Dashboard), не публикуем API в интернет
```

Держите `metrics`/`api` **не** в публичных entrypoints и всегда ограничивайте сеть доступа.

### Сценарий 2: JSON-логи для аггрегации (Loki/ELK)

```yaml
accessLog:
  format: json
  filters:
    minDuration: 100ms     # не шуметь мелкими 200
  fields:
    headers:
      names:
        Authorization: redact
        Set-Cookie: drop
```

Парсинг в Grafana Loki очевидный: `{app="traefik"} |= "ServiceName=api-service"`.

### Сценарий 3: Полный стек мониторинга (Prometheus + OTel + Logs)

```yaml
metrics:
  prometheus:
    entryPoint: metrics

tracing:
  serviceName: "traefik"
  openTelemetry:
    address: "otel-collector:4317"
    insecure: true

accessLog:
  filePath: /var/log/traefik/access.log
  format: json
```

Скоффиг `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "traefik"
    static_configs:
      - targets: ["traefik:9100"]
```

## Операции и команды

```bash
# Доступ к метрикам
curl -s localhost:9100/metrics | grep '^traefik_http_requests_total'

# Значение конкретной метрики
curl -s localhost:9100/metrics | grep 'traefik_config_last_reload_success'

# Общие значения разреза
curl -s localhost:9100/metrics | grep '^traefik.*' | head -50
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Метрик нет / «403»** | `metrics.prometheus` не включен, или entrypoint не на нужном порту | Проверьте статику; откройте порт метрик |
| **Нет меток по роутерам** | `addRoutersLabels: true` не задан | Включите labels по мере необходимости |
| **AccessLog не пишется** | `filePath` нет или права на запись | Укажите путь и права; иначе логи уходят в stdout |
| **Трейсы не появляются** | Неверный адрес OTLP-коллектора/GRPC vs HTTP | Проверьте `address` (4317 grpc / 4318 http), `insecure` |
| **Dashboard 404** | `api.dashboard` не включён или включён на непубличном entrypoint | Включите в статике: `api.dashboard: true` |

### Prometheus alert rules и SLO

```yaml
groups:
- name: traefik.slo
  interval: 30s
  rules:
  - record: traefik:http_requests_total:rate5m
    expr: sum(rate(traefik_http_requests_total[5m])) by (service, entrypoint)

  - record: traefik:http_error_rate:rate5m
    expr: sum(rate(traefik_http_requests_total{code=~"5.."}[5m])) by (service) / sum(rate(traefik_http_requests_total[5m])) by (service)

  - record: traefik:latency_p99:seconds
    expr: histogram_quantile(0.99, sum(rate(traefik_http_request_duration_seconds_bucket[5m])) by (le, service))

- name: traefik.alerts
  interval: 1m
  rules:
  - alert: TraefikHighErrorRate
    expr: traefik:http_error_rate:rate5m > 0.05
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High error rate on {{ $labels.service }}"
      description: "Error rate {{ $value | humanizePercentage }} for service {{ $labels.service }}"

  - alert: TraefikHighLatency
    expr: traefik:latency_p99:seconds > 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High latency on {{ $labels.service }}"
      description: "P99 latency {{ $value }}s for service {{ $labels.service }}"

  - alert: TraefikNoHealthyBackend
    expr: sum(traefik_service_server_up{service=~".+"}) by (service) == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "No healthy backends for {{ $labels.service }}"
      description: "All backends are down for service {{ $labels.service }}"

  - alert: TraefikCertificateExpiringSoon
    expr: (traefik_certificate_expiration_timestamp_seconds - time()) < 86400 * 30
    for: 0m
    labels:
      severity: warning
    annotations:
      summary: "Certificate expiring soon"
      description: "Certificate {{ $labels.domain }} expires in {{ $value | humanizeDuration }}"

  - alert: TraefikConfigReloadFailed
    expr: increase(traefik_config_last_reload_success{status="false"}[5m]) > 0
    for: 0m
    labels:
      severity: critical
    annotations:
      summary: "Config reload failed"
      description: "Traefik configuration reload failed"

## Рекомендации

- Не публикуйте API-порт (`:8080`) в интернет; Dashboard защищайте BasicAuth/ForwardAuth (см. [Middleware для безопасности](./traefik-middlewares-security.md)).
- Метрики — в отдельный entrypoint/порт, соберите в Graviton/Промetheus на выделенных хостах.
- В `filters`/`fields` «снижайте» базовые шумы: `minDuration`, `drop` ненужным заголовкам, `redact` для `Authorization`/`Set-Cookie`.
- Храните логи в JSON для observability платформ; формат `common` — для Nginx-совместимых инструментов.
- Трейсы поднимайте через OTel Collector; не тяните Traefik напрямую в Jaeger/Tempo без него (для v3 только OTLP).

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — статические опции и runtime.
- [Kubernetes Gateway API Traefik](../../Kubernetes/Networking/gateway_api/traefik.md) — метрики и мониторинг в K8s-окружении.
- [Grafana Docs: Traefik dashboards](https://grafana.com/grafana/dashboards/) — готовые дашборды (ID 12446).
- [OpenTelemetry](https://opentelemetry.io/docs/) — протокол OTLP.