# Observability-Driven Testing

## Определения

**Observability-Driven Testing** — подход к тестированию, при котором метрики системы (latency, error rate, throughput) из внешних источников (Prometheus, Grafana) используются как автоматические gate-ы для деплоя. Система сама решает, безопасно ли продолжать rollout на основе поведения в продакшене.

**SLO-Based Gate** — автоматический блокиратор деплоя, основанный на Service Level Objectives. Если метрика отклоняется от SLO, деплой останавливается.

**Metric-Driven Canary Analysis** — анализ метрик canary-подов (новая версия) относительно baseline-подов (старая версия) для принятия решения о продолжении rollout.

**Progressive Delivery** — подход, при котором деплой происходит поэтапно с автоматической верификацией метрик на каждом шаге (canary → percent traffic → full rollout).

## Основные концепции

### Как это работает

```
Деплой → Canary (5% трафика) → Prometheus собирает метрики
                                    ↓
                            Prometheus query (PromQL)
                                    ↓
                         AnalysisTemplate / SLO Gate
                                    ↓
                    ┌───────────────────────────────┐
                    │ Метрики в пределах SLO?        │
                    │                               │
                    │  Да → Увеличить % трафика     │
                    │  Нет → Rollback               │
                    └───────────────────────────────┘
```

### Метрики для SLO Gate

| Метрика | Пример PromQL | Типичный порог |
| :--- | :--- | :--- |
| **Error Rate** | `sum(rate(http_requests_total{status=~"5.."}[5m]))` | < 1% |
| **p95 Latency** | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))` | < 500ms |
| **Saturation (CPU)** | `avg(rate(container_cpu_usage_seconds_total[5m]))` | < 80% |
| **Saturation (Memory)** | `container_memory_working_set_bytes / container_spec_memory_limit_bytes` | < 85% |
| **Throughput** | `sum(rate(http_requests_total[5m]))` | > baseline * 0.9 |

### Инструменты

| Инструмент | Тип | Роль |
| :--- | :--- | :--- |
| **Prometheus** | Metrics backend | Источник метрик для анализа |
| **Argo Rollouts** | Progressive delivery | AnalysisTemplate + PromQL |
| **Flagger** | Progressive delivery | Canary + Prometheus analysis |
| **OpenTelemetry** | Tracing/Metrics | Телеметрия для анализа |
| **Grafana** | Visualization | Дашборды для мониторинга canary |

---

## Практические реализации

### Argo Rollouts: AnalysisTemplate

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: canary-analysis
spec:
  args:
    - name: service-name
    - name: namespace
  metrics:
    - name: error-rate
      interval: 30s
      count: 5
      successCondition: result[0] < 0.01
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus:9090
          query: |
            sum(rate(http_requests_total{service="{{args.service-name}}",status=~"5.."}[1m])) /
            sum(rate(http_requests_total{service="{{args.service-name}}"}[1m]))
    
    - name: latency-p95
      interval: 30s
      count: 5
      successCondition: result[0] < 500
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus:9090
          query: |
            histogram_quantile(0.95,
              sum(rate(http_request_duration_seconds_bucket{service="{{args.service-name}}"}[1m])) by (le)
            ) * 1000
```

### Argo Rollouts: Canary с AnalysisTemplate

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
spec:
  replicas: 10
  strategy:
    canary:
      canaryService: my-app-canary
      stableService: my-app-stable
      analysis:
        templates:
          - templateName: canary-analysis
        args:
          - name: service-name
            value: my-app
          - name: namespace
            valueFrom:
              fieldRef:
                fieldPath: metadata.namespace
      steps:
        - setWeight: 5
        - pause: { duration: 1m }
        - setWeight: 20
        - pause: { duration: 2m }
        - setWeight: 50
        - pause: { duration: 5m }
        - setWeight: 100
```

### Flagger: Canary с Prometheus

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: my-app
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  progressDeadlineSeconds: 600
  service:
    port: 8080
  analysis:
    interval: 30s
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
      - name: request-success-rate
        thresholdRange:
          min: 99
        interval: 1m
      - name: request-duration
        thresholdRange:
          max: 500
        interval: 1m
    webhooks: []  # Можно добавить custom webhooks
```

### Custom AnalysisScript: Python + Prometheus

```python
import requests
import sys

PROMETHEUS_URL = "http://prometheus:9090"
SERVICE = "my-app"
ERROR_THRESHOLD = 0.01
LATENCY_THRESHOLD_MS = 500

def query_prometheus(query):
    resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
    data = resp.json()
    if data["status"] == "success" and data["data"]["result"]:
        return float(data["data"]["result"][0]["value"][1])
    return None

# Проверка error rate
error_rate = query_prometheus(f"""
    sum(rate(http_requests_total{{service="{SERVICE}",status=~"5.."}}[1m])) /
    sum(rate(http_requests_total{{service="{SERVICE}"}}[1m]))
""")
print(f"Error rate: {error_rate}")
if error_rate is not None and error_rate > ERROR_THRESHOLD:
    print(f"FAIL: error rate {error_rate:.4f} exceeds threshold {ERROR_THRESHOLD}")
    sys.exit(1)

# Проверка p95 latency
p95 = query_prometheus(f"""
    histogram_quantile(0.95,
        sum(rate(http_request_duration_seconds_bucket{{service="{SERVICE}"}}[1m])) by (le)
    ) * 1000
""")
print(f"p95 latency: {p95}ms")
if p95 is not None and p95 > LATENCY_THRESHOLD_MS:
    print(f"FAIL: p95 latency {p95:.0f}ms exceeds threshold {LATENCY_THRESHOLD_MS}ms")
    sys.exit(1)

print("PASS: All SLO checks passed")
```

### Prometheus AlertRule как quality gate

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: deployment-gate
spec:
  groups:
    - name: deployment-gate
      rules:
        - alert: HighErrorRateDuringRollout
          expr: |
            sum(rate(http_requests_total{status=~"5.."}[2m])) by (service) /
            sum(rate(http_requests_total[2m])) by (service) > 0.02
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "High error rate during deployment"
            description: "Service {{ $labels.service }} has error rate {{ $value }}"
        
        - alert: HighLatencyDuringRollout
          expr: |
            histogram_quantile(0.95,
              sum(rate(http_request_duration_seconds_bucket[2m])) by (le, service)
            ) > 1
          for: 1m
          labels:
            severity: warning
          annotations:
            summary: "High p95 latency during deployment"
```

---

### GitLab CI: метрический gate

```yaml
deploy_and_verify:
  stage: deploy
  script:
    # Деплой canary
    - kubectl apply -f k8s/canary.yaml
    - sleep 60  # Ожидание стабилизации
    
    # Проверка метрик через Prometheus
    - |
      ERROR_RATE=$(curl -s "http://prometheus:9090/api/v1/query" \
        --data-urlencode "query=sum(rate(http_requests_total{service='my-app',status=~'5..'}[2m])) / sum(rate(http_requests_total{service='my-app'}[2m]))" \
        | jq -r '.data.result[0].value[1]')
      
      echo "Error rate: ${ERROR_RATE}"
      
      if [ $(echo "$ERROR_RATE > 0.01" | bc -l) -eq 1 ]; then
        echo "FAIL: Error rate ${ERROR_RATE} exceeds threshold"
        kubectl rollout undo deployment/my-app
        exit 1
      fi
    
    # Full rollout
    - kubectl set image deployment/my-app app=myapp:${CI_COMMIT_SHA}
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| AnalysisTemplate всегда падает | PromQL возвращает `NaN` (нет данных) | Проверить, что сервис отправляет метрики; добавить `successCondition: result[0] < 0.01 or absent(result[0])` |
| Canary analysis не запускается | Нет `analysis` в Rollout/Canary spec | Добавить секцию `analysis` с правильными `templates` |
| Prometheus query возвращает ошибку | Неверный PromQL или имя сервиса | Протестировать PromQL в Prometheus UI |
| Rollback происходит без причины | Слишком низкий `threshold` | Отрегулировать порог на основе реальных данных |
| Метрики не меняются после canary | Малый % трафика (5%) | Увеличить `setWeight` или увеличить `pause` duration |
| Flagger не находит метрику | Имя метрики не совпадает с настройкой | Проверить `request-success-rate` / `request-duration` в Flagger |

---

## Дополнительная информация

### См. также
- **[Канареечный деплой: мониторинг](../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md)** — AnalysisTemplate, PromQL, gate.
- **[Прогрессивная доставка](../../GitOps/Concepts/progressive_delivery_gitops.md)** — Argo Rollouts, Flagger, Prometheus.
- **[Nagрузочное тестирование в CI/CD](./load_testing_ci_cd.md)** — k6, performance budget.
- **[Smoke Testing](./smoke_testing.md)** — post-deploy verification.
- **[OTel в Feature Toggles](./feature_toggles/architecture.md)** — OTel integration.

### Внешние ресурсы
- [Argo Rollouts Analysis](https://argo-rollouts.readthedocs.io/en/stable/features/analysis/) — AnalysisTemplate.
- [Flagger Canary](https://docs.flagger.app/) — progressive delivery с Flagger.
- [Prometheus Querying](https://prometheus.io/docs/prometheus/latest/querying/) — PromQL.
