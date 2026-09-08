# Мониторинг и наблюдаемость Gateway API

## Определения

**ServiceMonitor** — Custom Resource Definition Prometheus Operator, описывающий как Prometheus должен скрапить метрики с эндпоинтов Kubernetes Service. Используется для автоматического обнаружения и сбора метрик Gateway API контроллеров.

**PrometheusRule** — Custom Resource Definition Prometheus Operator для определения алертинг-правил и записей recording rules. Позволяет декларативно описывать условия срабатывания алертов на основе метрик Gateway API.

**Access Log** — запись о каждом запросе, обработанном Data Plane (Envoy, NGINX). Содержит информацию о клиенте, запрошенном ресурсе, времени ответа, коде статуса. Ключевой источник данных для анализа трафика и диагностики проблем.

**Distributed Tracing** — методика отслеживания пути запроса через несколько компонентов системы с помощью уникального Trace ID. Позволяет визуализировать задержки на каждом этапе обработки трафика Gateway API.

**SLI (Service Level Indicator)** — количественная метрика качества сервиса. Для Gateway API основные SLI: доля успешных запросов (availability), процентиль задержки (latency P99), количество ошибок маршрутизации.

**SLO (Service Level Objective)** — целевое значение SLI, определяющее допустимый уровень качества сервиса. Например: availability >= 99.9%, P99 latency <= 500ms.

## Предварительные требования

| Компонент | Минимальная версия | Проверка |
|:---|:---|:---|
| Kubernetes | 1.25+ | `kubectl version --short` |
| Prometheus Operator | 0.65+ | `kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator` |
| Grafana | 10.0+ | `kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana` |
| Gateway API контроллер | Зависит от реализации | `kubectl get pods -n <controller-ns>` |

## Базовые концепции

### Архитектура мониторинга Gateway API

Мониторинг Gateway API строится на трёх уровнях:

1. **Метрики контроллера (Control Plane):** количество reconcile-операций, ошибки конфигурации, время распространения изменений.
2. **Метрики Data Plane:** количество запросов, задержки, коды ответов, количество активных соединений, статус бэкендов.
3. **Метрики ресурсов:** статус Conditions (Accepted, Programmed, ResolvedRefs) ресурсов Gateway API.

### Источники метрик по контроллерам

| Контроллер | Endpoint | Порт | Формат |
|:---|:---|:---|:---|
| **Envoy Gateway** | `/stats/prometheus` | 19000 | Envoy stats |
| **Traefik** | `/metrics` | 9100 | Traefik native |
| **KGateway** | `/metrics` | 9090 | Prometheus |
| **NGINX Gateway Fabric** | `/metrics` | 9113 | nginx-prometheus-exporter |

### Ключевые метрики для SLI/SLO

| SLI | Метрика (Envoy) | Метрика (Traefik) | Описание |
|:---|:---|:---|:---|
| **Availability** | `sum(envoy_cluster_upstream_rq_xx{code=~"2.."}) / sum(envoy_cluster_upstream_rq_total)` | `sum(traefik_backend_requests_total{code=~"2.."}) / sum(traefik_backend_requests_total)` | Доля успешных запросов |
| **Latency P99** | `histogram_quantile(0.99, sum(rate(envoy_cluster_upstream_rq_time_bucket[5m])) by (le))` | `histogram_quantile(0.99, sum(rate(traefik_backend_request_duration_seconds_bucket[5m])) by (le))` | 99-й процентиль задержки |
| **Error Rate** | `sum(rate(envoy_cluster_upstream_rq_xx{code=~"5.."}[5m])) / sum(rate(envoy_cluster_upstream_rq_total[5m]))` | `sum(rate(traefik_backend_requests_total{code=~"5.."}[5m])) / sum(rate(traefik_backend_requests_total[5m]))` | Доля серверных ошибок |
| **Active Connections** | `envoy_server_total_connections` | `traefik_backend_open_connections` | Количество активных соединений |

## Практические сценарии

### Настройка ServiceMonitor для Envoy Gateway

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: envoy-gateway
  namespace: envoy-gateway-system
  labels:
    release: prometheus  # Лейбл для selector Prometheus Operator
spec:
  selector:
    matchLabels:
      gateway.envoyproxy.io/owning-gateway-name: ""
  namespaceSelector:
    matchNames:
    - envoy-gateway-system
  endpoints:
  - port: envoy-http  # Порт Envoy admin interface
    path: /stats/prometheus
    interval: 30s
    scrapeTimeout: 10s
    metricRelabelings:
    # Фильтация ненужных метрик для снижения нагрузки
    - sourceLabels: [__name__]
      regex: "envoy_.*"
      action: keep
```

**Валидация:**
```bash
kubectl get servicemonitor envoy-gateway -n envoy-gateway-system
# → NAME             AGE
# → envoy-gateway    2m

# Проверка что Prometheus обнаружил таргет
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
# Открыть http://localhost:9090/targets и найти envoy-gateway таргет
```

### Настройка ServiceMonitor для Traefik

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: traefik-gateway
  namespace: traefik
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
  namespaceSelector:
    matchNames:
    - traefik
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
```

Дополнительная конфигурация Traefik для включения метрик (Helm values):
```yaml
# values.yaml
ports:
  metrics:
    port: 9100
    expose: true
    exposedPort: 9100
    protocol: TCP
additionalArguments:
- "--metrics.prometheus=true"
- "--metrics.prometheus.entryPoint=metrics"
- "--metrics.prometheus.addEntryPointsLabels=true"
- "--metrics.prometheus.addRoutersLabels=true"
- "--metrics.prometheus.addServicesLabels=true"
```

### Настройка ServiceMonitor для NGINX Gateway Fabric

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: nginx-gateway-fabric
  namespace: nginx-gateway
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: nginx-gateway-fabric
  namespaceSelector:
    matchNames:
    - nginx-gateway
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
```

Helm values для NGINX Gateway Fabric:
```yaml
# values.yaml
nginxGatewayFabric:
  prometheus:
    enabled: true
    port: 9113
```

### Настройка ServiceMonitor для KGateway

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kgateway
  namespace: kgateway-system
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: kgateway
  namespaceSelector:
    matchNames:
    - kgateway-system
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
```

Helm values для KGateway:
```yaml
# values.yaml
metrics:
  enabled: true
  port: 9090
  path: /metrics
```

### Алертинг-правила (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: gateway-api-alerts
  namespace: monitoring
  labels:
    release: prometheus
spec:
  groups:
  - name: gateway-api.rules
    rules:
    # Высокий процент ошибок 5xx
    - alert: GatewayAPIHighErrorRate
      expr: |
        sum(rate(envoy_cluster_upstream_rq_xx{code=~"5.."}[5m])) by ( envoy_cluster )
        /
        sum(rate(envoy_cluster_upstream_rq_total[5m])) by ( envoy_cluster )
        > 0.05
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Gateway API: более 5% ошибок 5xx"
        description: "Кластер {{ $labels.envoy_cluster }} возвращает {{ $value | humanizePercentage }} ошибок"

    # Высокая задержка P99
    - alert: GatewayAPIHighLatency
      expr: |
        histogram_quantile(0.99,
          sum(rate(envoy_cluster_upstream_rq_time_bucket[5m])) by (le, envoy_cluster)
        ) > 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Gateway API: P95 задержка превышает 1 секунду"
        description: "Кластер {{ $labels.envoy_cluster }}: P99 = {{ $value }}s"

    # Gateway не Programmed
    - alert: GatewayNotProgrammed
      expr: |
        kube_gateway_status_condition{condition="Programmed", status="true"} == 0
      for: 2m
      labels:
        severity: critical
      annotations:
        summary: "Gateway API: шлюз не сконфигурирован"
        description: "Gateway {{ $labels.namespace }}/{{ $labels.gateway }} не в состоянии Programmed"

    # HTTPRoute не Accepted
    - alert: HTTPRouteNotAccepted
      expr: |
        kube_httproute_status_condition{condition="Accepted", status="true"} == 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Gateway API: HTTPRoute не принята контроллером"
        description: "HTTPRoute {{ $labels.namespace }}/{{ $labels.httproute }} не принята"

    # Нет доступных бэкендов
    - alert: GatewayNoHealthyBackends
      expr: |
        sum(envoy_cluster_membership_total{envoy_cluster=~".*"}) by (envoy_cluster) == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "Gateway API: нет здоровых бэкендов"
        description: "Для кластера {{ $labels.envoy_cluster }} нет доступных эндпоинтов"

    # Высокая нагрузка на Control Plane
    - alert: GatewayAPIControllerHighReconcileErrors
      expr: |
        sum(rate(gatewayapi_controller_reconcile_errors_total[5m])) > 0.1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Gateway API: ошибки reconcile控制器"
        description: "Контроллер Gateway API генерирует ошибки reconcile"
```

**Валидация:**
```bash
kubectl get prometheusrule gateway-api-alerts -n monitoring
# → NAME                  AGE
# → gateway-api-alerts    1m

# Проверка что Prometheus загрузил правила
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
# Открыть http://localhost:9090/alerts и найти правила gateway-api
```

### Готовые PromQL-запросы для дашбордов

```promql
# === Availability ===
# Доля успешных запросов (2xx/3xx)
sum(rate(envoy_cluster_upstream_rq_xx{code=~"[23].."}[5m]))
/ sum(rate(envoy_cluster_upstream_rq_total[5m]))

# === Latency ===
# P50 задержка
histogram_quantile(0.50, sum(rate(envoy_cluster_upstream_rq_time_bucket[5m])) by (le))

# P95 задержка
histogram_quantile(0.95, sum(rate(envoy_cluster_upstream_rq_time_bucket[5m])) by (le))

# P99 задержка
histogram_quantile(0.99, sum(rate(envoy_cluster_upstream_rq_time_bucket[5m])) by (le))

# === Throughput ===
# Запросы в секунду
sum(rate(envoy_cluster_upstream_rq_total[5m]))

# Запросы по кодам ответа
sum(rate(envoy_cluster_upstream_rq_xx{code=~"2.."}[5m])) by (code)

# === Connections ===
# Активные соединения
envoy_server_total_connections

# Открытые соединения к бэкендам
sum(envoy_cluster_upstream_cx_active) by (envoy_cluster)

# === Errors ===
# 5xx ошибки в секунду
sum(rate(envoy_cluster_upstream_rq_xx{code=~"5.."}[5m]))

# Rate limiting (если настроен)
sum(rate(envoy_http_rls_ok_total[5m]))
sum(rate(envoy_http_rls_error_total[5m]))

# === Resource Status ===
# Количество Gateway в состоянии Programmed
kube_gateway_status_condition{condition="Programmed", status="true"}

# Количество HTTPRoute в состоянии Accepted
kube_httproute_status_condition{condition="Accepted", status="true"}
```

### Настройка Access Logs в Envoy Gateway

Envoy Gateway позволяет настраивать access logs через `EnvoyProxy` ресурс:

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: EnvoyProxy
metadata:
  name: access-log-config
  namespace: envoy-gateway-system
spec:
  ipFamily: IPv4
  accessLog:
    sinks:
    # JSON формат для結構化解析
    - name: json-file
      json:
        path: /dev/stdout
    # TensorFlow формат для Loki/Promtail
    - name: tensor
      tensor:
        path: /dev/stdout
  logging:
    level:
      default: INFO
```

### Настройка Access Logs в NGINX Gateway Fabric

```yaml
apiVersion: gateway.nginx.org/v1alpha1
kind: NginxProxy
metadata:
  name: nginx-proxy-config
  namespace: nginx-gateway
spec:
  logging:
    access:
      enable: true
      level: info
```

### Интеграция с OpenTelemetry

Для экспорта метрик и traces через OpenTelemetry Collector:

```yaml
# Конфигурация Envoy Gateway для OTLP экспорта
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: EnvoyProxy
metadata:
  name: otel-config
  namespace: envoy-gateway-system
spec:
  telemetry:
    metrics:
      matchLabels:
        envoy_gateway_exported_from_namespace: envoy-gateway-system
    tracing:
      samplingRate: "100"
      provider:
        type: OpenTelemetry
        openTelemetry:
          host: otel-collector.monitoring.svc.cluster.local
          port: 4317
    accessLogs:
      sinks:
      - name: otel
        openTelemetry:
          host: otel-collector.monitoring.svc.cluster.local
          port: 4317
```

## Troubleshooting

### Типичные ошибки мониторинга

| Симптом | Причина | Решение |
|:---|:---|:---|
| Нет метрик в Prometheus | ServiceMonitor не создан или неверные лейблы | Проверить `kubectl get servicemonitor -A` и лейбл `release` |
| Таргет в state `DOWN` | Неверный порт или path в ServiceMonitor | Проверить порт endpoints контроллера, curl `/stats/prometheus` |
| Метрики дублируются | Несколько ServiceMonitor на один сервис | Проверить пересечение selector'ов, удалить дубликат |
| Алерты не срабатывают | PrometheusRule не загружен | Проверить `kubectl get prometheusrule`, перезагрузить Prometheus |
| Пустые графики | Метрики называются иначе | Проверить `curl localhost:19000/stats/prometheus | grep envoy` |

### Диагностика сбора метрик

```bash
# Проверка что Envoy экспортирует метрики
kubectl port-forward -n envoy-gateway-system <envoy-pod> 19000:19000
curl -s http://localhost:19000/stats/prometheus | head -20
# → Должны быть метрики envoy_server_total_connections, envoy_cluster_*

# Проверка что Traefik экспортирует метрики
kubectl port-forward -n traefik svc/traefik 9100:9100
curl -s http://localhost:9100/metrics | head -20
# → Должны быть метрики traefik_backend_requests_total, traefik_router_*

# Проверка ServiceMonitor
kubectl get servicemonitor -A -o wide
# → Все ServiceMonitor должны иметь правильный selector

# Проверка что Prometheus видит таргеты
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
# → http://localhost:9090/targets — все таргеты должны быть UP
```

## Best Practices

### Организация мониторинга

1. **Используйте единый namespace для мониторинга:**
   - Все ServiceMonitor и PrometheusRule в `monitoring`
   - Упрощает управление и аудит

2. **Применяйте label selector:**
   - Все ServiceMonitor с лейблом `release: prometheus`
   - Автоматическое обнаружение Prometheus Operator

3. **Группируйте алерты по критичности:**
   - `critical`: Gateway not Programmed, нет бэкендов
   - `warning`: High error rate, high latency
   - `info`: Configuration changes

### Производительность

1. **Фильтруйте ненужные метрики:**
   - Используйте `metricRelabelings` для удаления высокочастотных метрик
   - Ограничивайте количество лейблов

2. **Настройте scrape interval:**
   - 30s для стандартных метрик
   - 10s для критичных эндпоинтов
   - Не менее 15s для снижения нагрузки

3. **Используйте recording rules:**
   - Предвычисляйте сложные запросы
   - Снижайте нагрузку на Prometheus при рендеринге дашбордов

### Дашборды

Рекомендуемые Grafana Dashboard ID:

| Dashboard | ID | Описание |
|:---|:---|:---|
| Envoy Global | `18364` | Глобальные метрики Envoy |
| Envoy Clusters | `18366` | Метрики по кластерам Envoy |
| Traefik v2/v3 Overview | `11462` | Обзор Traefik |
| Traefik with Gateway API | `13174` | Traefik + Gateway API |
| NGINX Ingress | `14314` | NGINX Ingress Controller |

## Дополнительная информация

### Связанные ресурсы

- [Envoy Gateway](./envoy_gateway.md) — настройка Envoy admin interface и метрик
- [Traefik](./traefik.md) — метрики и ServiceMonitor для Traefik
- [KGateway](./kgateway.md) — метрики для KGateway
- [NGINX Gateway Fabric](./nginx_gateway_fabric.md) — Prometheus для NGF
- [Определения Gateway API](./definitions.md) — общие концепции мониторинга

**Родительская тема:** [Gateway API](./definitions.md)
