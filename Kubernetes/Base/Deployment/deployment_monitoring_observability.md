# Мониторинг и наблюдаемость Deployment

Практическое руководство по мониторингу Deployment в Kubernetes: метрики контроллера, алерты Prometheus и интеграция с CI/CD.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes с настроенным стеком мониторинга (Prometheus + Grafana).
- Установленный `kubectl` с доступом к кластеру.
- Базовое понимание [Deployment](./index.md).

## 1. Определения

**Observability (Наблюдаемость)** — способность понимать внутреннее состояние системы по её внешним проявлениям. Три столпа: метрики (metrics), логи (logs), трассировка (traces).

> Общая теория SLI/SLO/Error Budget см. в [SRE Concepts](../../../Concepts/sre_concepts_main.md). Архитектура мониторинга — в [Kubernetes Monitoring Architecture](../../../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md). Алерты для Kubernetes — в [Kubernetes Alerts](../../../Grafana/alerting/kubernetes_alerts.md).

## 2. Базовые концепции

### Три уровня метрик Deployment

| Уровень | Источник | Метрики |
|:--------|:---------|:--------|
| **Уровень контроллера** | kube-state-metrics | replicas, conditions, rollout status |
| **Уровень подов** | metrics-server, cAdvisor | CPU, memory, network |
| **Уровень приложения** | Приложение (Prometheus) | error rate, latency, throughput |

## 3. Практические сценарии

### Метрики kube-state-metrics для Deployment

```promql
# Текущее vs желаемое количество реплик
kube_deployment_spec_replicas != kube_deployment_status_replicas_ready

# Все поды готовы?
kube_deployment_status_replicas_unavailable > 0

# Rollout в процессе?
kube_deployment_status_replicas_updated != kube_deployment_status_replicas

# Контроллер обработал последнее изменение?
kube_deployment_status_observed_generation < kube_deployment_metadata_generation

# Условие Progressing: False (rollout провален)
kube_deployment_status_condition{condition="Progressing",status="false"} == 1
```

### Алерты Prometheus для Deployment

```yaml
groups:
- name: deployment-alerts
  rules:
  # Rollout завис
  - alert: DeploymentRolloutStuck
    expr: |
      kube_deployment_status_condition{condition="Progressing",status="false"} == 1
      and
      kube_deployment_status_condition{condition="Progressing",reason="ProgressDeadlineExceeded"} == 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Deployment {{ $labels.deployment }} rollout stuck"
      description: "Rollout deployment/{{ $labels.deployment }} in namespace {{ $labels.namespace }} exceeded progress deadline"

  # Не все поды доступны
  - alert: DeploymentReplicasUnavailable
    expr: |
      kube_deployment_status_replicas_unavailable > 0
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Deployment {{ $labels.deployment }} has unavailable replicas"
      description: "{{ $value }} replicas unavailable in deployment/{{ $labels.deployment }}"

  # Memory близко к лимиту
  - alert: PodMemoryNearLimit
    expr: |
      (
        container_memory_working_set_bytes
        /
        kube_pod_container_resource_limits{resource="memory"}
      ) > 0.9
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Pod {{ $labels.pod }} memory near limit"
      description: "Memory usage {{ $value | humanizePercentage }} of limit"
```

### Метрики приложения для canary analysis

```promql
# Error rate для canary
sum(rate(http_requests_total{version="canary",code=~"5.."}[5m]))
/
sum(rate(http_requests_total{version="canary"}[5m]))

# Latency p99 для canary
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{version="canary"}[5m])) by (le)
)

# Сравнение error rate canary vs baseline
(
  sum(rate(http_requests_total{version="canary",code=~"5.."}[5m]))
  / sum(rate(http_requests_total{version="canary"}[5m]))
)
-
(
  sum(rate(http_requests_total{version="baseline",code=~"5.."}[5m]))
  / sum(rate(http_requests_total{version="baseline"}[5m]))
)
```

### Custom Metrics для HPA

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: 1000
  - type: Pods
    pods:
      metric:
        name: http_request_duration_seconds_p99
      target:
        type: AverageValue
        averageValue: 500m
```

### Интеграция с CI/CD

```yaml
# GitLab CI: проверка метрик после деплоя
verify-metrics:
  stage: verify
  script:
    - |
      # Ждем 5 минут после деплоя
      sleep 300

      # Проверяем error rate через Prometheus
      ERROR_RATE=$(curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{service=\"my-app\",code=~\"5..\"}[5m]))/sum(rate(http_requests_total{service=\"my-app\"}[5m]))" | jq -r '.data.result[0].value[1]')

      if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
        echo "ERROR: Error rate too high: $ERROR_RATE"
        kubectl rollout undo deployment/my-app
        exit 1
      fi

      echo "SUCCESS: Error rate acceptable: $ERROR_RATE"
  when: on_success
```

### Логи Deployment

```bash
# Логи всех подов Deployment
kubectl logs -l app=my-app --tail=100

# Логи с фильтрацией по времени
kubectl logs -l app=my-app --since=10m

# Логи с фильтрацией по содержимому
kubectl logs -l app=my-app | grep -i error

# Логи через stern (multi-pod)
stern my-app -n production --tail 100

# Логи в Elasticsearch/Loki
# (настраивается отдельно через Fluentd/FluentBit/Promtail)
```

## 4. Дополнительная информация

### См. также
- [Kubernetes Monitoring Architecture](../../../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — архитектура мониторинга.
- [Kubernetes Alerts](../../../Grafana/alerting/kubernetes_alerts.md) — алерты для Kubernetes (717 строк).
- [SRE Concepts](../../../Concepts/sre_concepts_main.md) — SLI/SLO/Error Budget.
- [HPA](../../Autoscaling/HPA/index.md) — горизонтальное масштабирование.
- [Canary Monitoring](../../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md) — мониторинг canary.
- [Progressive Delivery](./progressive_delivery.md) — AnalysisTemplate для метрик.
