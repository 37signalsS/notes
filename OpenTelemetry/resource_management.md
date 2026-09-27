# OpenTelemetry: Управление ресурсами Collector

## Определения

**Управление ресурсами OpenTelemetry Collector** — это процесс оптимизации потребления CPU, памяти и сети для обеспечения стабильной работы Collector при различных нагрузках. Включает настройку лимитов, requests, масштабирование и мониторинг.

В 2026 году правильное управление ресурсами критично для production-развёртывания OTel.

## Теоретический блок

### Модель ресурсов

```text
Collector Rесурсы:
├── CPU (вычисления)
│   ├── Receivers (приём данных)
│   ├── Processors (обработка)
│   └── Exporters (отправка)
├── Память (RAM)
│   ├── Buffer (буферы)
│   ├── Queue (очереди)
│   └── State (состояние)
└── Сеть (bandwidth)
    ├── Inbound (входящий трафик)
    └── Outbound (исходящий трафик)
```

### Факторы влияния

| Фактор | Влияние на CPU | Влияние на память |
| :--- | :--- | :--- |
| **Объём данных** | Пропорционально | Пропорционально |
| **Количество processors** | Линейно | Незначительно |
| **Tail-based sampling** | Высокое | Высокое |
| **Compression** | Среднее | Низкое |
| **Batch size** | Среднее | Пропорционально |

## Практические сценарии

### Сценарий 1: Базовая конфигурация ресурсов

**Рекомендуемые значения для разных нагрузок:**

| Нагрузка | CPU requests | CPU limits | Memory requests | Memory limits |
| :--- | :--- | :--- | :--- | :--- |
| **Dev/Test** | 100m | 500m | 128Mi | 256Mi |
| **Small** | 250m | 1 | 256Mi | 512Mi |
| **Medium** | 500m | 2 | 512Mi | 1Gi |
| **Large** | 1 | 4 | 1Gi | 2Gi |
| **High-load** | 2 | 8 | 2Gi | 4Gi |

**Конфигурация Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-collector
spec:
  replicas: 3
  selector:
    matchLabels:
      app: otel-collector
  template:
    spec:
      containers:
        - name: collector
          image: otel/opentelemetry-collector-contrib:0.96.0
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2"
              memory: "1Gi"
```

### Сценарий 2: Настройка memory_limiter

**Конфигурация memory_limiter processor:**

```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 800
    spike_limit_mib: 200
```

**Расчёт limit_mib:**

```
limit_mib = (Доступная RAM контейнера) × 0.7
spike_limit_mib = limit_mib × 0.25
```

**Пример для контейнера с 1Gi RAM:**

```
limit_mib = 1024 × 0.7 = 716.8 ≈ 700
spike_limit_mib = 700 × 0.25 = 175
```

### Сценарий 3: Горизонтальное масштабирование

**HPA (Horizontal Pod Autoscaler):**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: otel-collector
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: otel-collector
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

**Кастомные метрики для масштабирования:**

```yaml
metrics:
  - type: Pods
    pods:
      metric:
        name: otelcol_receiver_accepted_spans
      target:
        type: AverageValue
        averageValue: "10000"
```

### Сценарий 4: Оптимизация batch processor

**Настройка batch для оптимизации ресурсов:**

```yaml
processors:
  batch:
    send_batch_size: 1024
    timeout: 10s
    metadata_keys:
      - service.name
```

**Расчёт оптимального send_batch_size:**

```
send_batch_size = (Средний объём данных за 10 сек) × (Количество экземпляров Collector)
```

### Сценарий 5: Мониторинг ресурсов

**Метрики для мониторинга:**

```bash
# Потребление CPU и памяти
kubectl top pod -l app=otel-collector -n opentelemetry

# Метрики Collector
curl -s http://otel-collector:8888/metrics | grep otelcol_processor_memory_limiter

# Метрики Kubernetes
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/namespaces/opentelemetry/pods" | jq '.items[] | select(.metadata.name | contains("otel-collector"))'
```

**Алерты на ресурсы:**

```yaml
groups:
  - name: otel-collector-resources
    rules:
      - alert: OTelCollectorHighCPU
        expr: rate(container_cpu_usage_seconds_total{container="collector"}[5m]) > 1.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "OTel Collector потребляет много CPU"

      - alert: OTelCollectorHighMemory
        expr: container_memory_working_set_bytes{container="collector"} / container_spec_memory_limit_bytes > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "OTel Collector приближается к лимиту памяти"
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Collector падает с OOM** | Недостаточно памяти или отсутствует memory_limiter | Увеличить limits, настроить memory_limiter |
| **Высокое потребление CPU** | Слишком много processors или не оптимизирован batch | Уменьшить количество processors, оптимизировать batch |
| **Медленная обработка** | Недостаточно CPU или очереди переполнены | Увеличить CPU limits, увеличить send_batch_size |
| **Неравномерная нагрузка** | Неправильная балансировка | Настроить HPA, проверить PodAntiAffinity |

### Best Practices

1. **Начинайте с минимальных ресурсов** — масштабируйте по мере необходимости.
2. **Используйте memory_limiter** — это защита от OOM.
3. **Мониторьте ключевые метрики** — настройте алерты на критические пороги.
4. **Используйте HPA** — автоматическое масштабирование по метрикам.
5. **Регулярно пересматривайте** — оптимизируйте ресурсы на основе нагрузки.

### Ссылки

- [OTel Collector Performance](https://opentelemetry.io/docs/collector/performance/)
- [Kubernetes Resource Management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- [HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
