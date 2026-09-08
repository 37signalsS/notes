# Prometheus Adapter: настройка и интеграция с HPA

## Определения

**Prometheus Adapter** — компонент Kubernetes Aggregation Layer, реализующий Custom Metrics API (`custom.metrics.k8s.io`) и External Metrics API (`external.metrics.k8s.io`). Преобразует Prometheus-запросы (PromQL) в метрики, понятные HPA Controller.

**Custom Metrics API** — агрегированный API-сервер, расширяющий базовый Kubernetes API. Позволяет HPA запрашивать пользовательские метрики (RPS, latency, длина очереди) наравне со стандартными CPU/Memory.

**External Metrics API** — API для метрик, находящихся за пределами кластера (очереди Kafka, RabbitMQ, метрики внешних сервисов). Отличается от Custom Metrics тем, что метрика не привязана к конкретному поду или объекту Kubernetes.

**Recommends Scaling (рекомендации)** — Prometheus Adapter может не только предоставлять метрики, но и генерировать рекомендации по количеству реплик для HPA через секцию `config.yaml`.

---

## Теоретический блок

### Архитектура интеграции

```
Prometheus ← (PromQL) ← Prometheus Adapter → Custom Metrics API → HPA Controller
                                                         ↓
                                              kube-apiserver (Aggregation Layer)
```

1. **Prometheus** хранит метрики (CPU, RPS, latency, очередь и т.д.)
2. **Prometheus Adapter** опрашивает Prometheus по PromQL-запросам
3. **Преобразование:** Adapter конвертирует результат PromQL в формат Kubernetes Metrics API
4. **HPA Controller** запрашивает метрики через `custom.metrics.k8s.io` или `external.metrics.k8s.io`
5. **HPA** применяет формулу расчёта с использованием полученных метрик

### Ключевые различия: Custom vs External Metrics

| Характеристика | Custom Metrics | External Metrics |
|:---|:---|:---|
| **Привязка** | К объекту Kubernetes (Pod, Deployment, Ingress) | Вне кластера (очередь, БД, API) |
| **API endpoint** | `custom.metrics.k8s.io` | `external.metrics.k8s.io` |
| **HPA тип метрики** | `Pods`, `Object` | `External` |
| **Пример** | RPS на под, latency Ingress | Глубина очереди RabbitMQ |
| **Скоуп** | Namespace (метрика видна в том же namespace) | Cluster-wide |

### Как Prometheus Adapter маппит метрики

Adapter преобразует PromQL-результат в иерархию:

```
MetricName → ObjectReference → (Pod/Ingress/Service) → Labels → Values
```

Для `custom.metrics.k8s.io`:
- Метрика привязана к **объекту** Kubernetes (Pod, Deployment, Ingress)
- HPA получает значение метрики для каждого пода или объекта

Для `external.metrics.k8s.io`:
- Метрика **глобальная** (не привязана к поду)
- HPA получает агрегированное значение

### Когда использовать Prometheus Adapter vs KEDA

| Критерий | Prometheus Adapter | KEDA |
|:---|:---|:---|
| **Источник метрик** | Только Prometheus | 50+ скейлеров (Kafka, RabbitMQ, Redis, Cron...) |
| **Scale-to-Zero** | Нет | Да (нативно) |
| **Простота настройки** | Средняя (нужен PromQL) | Высокая (декларативные триггеры) |
| **Производительность** | Зависит от Prometheus | Зависит от скейлера |
| **Рекомендации** | Да (recommendations) | Нет |
| **Сложные PromQL** | Полная поддержка | Ограничена |

**Рекомендация:** Если метрики уже есть в Prometheus и не нужен scale-to-zero — Prometheus Adapter. Если нужен scale-to-zero или метрики из внешних систем — KEDA.

---

## Практический блок

### Шаг 1: Установка Prometheus Adapter

```bash
# Добавление Helm-репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка в отдельный namespace
helm install prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --set prometheus.url=http://prometheus-kube-prometheus-prometheus.monitoring.svc \
  --set prometheus.port=9090 \
  --wait
```

**Проверка:**
```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-adapter
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → prometheus-adapter-xxxxx                    1/1     Running   0          2m

kubectl get apiservice | grep custom.metrics
# → v1beta1.custom.metrics.k8s.io   monitoring/prometheus-adapter   True   5m
```

### Шаг 2: Конфигурация PromQL-правил (config.yaml)

Файл `config.yaml` — сердце Prometheus Adapter. Он определяет, какие PromQL-запросы и в каком формате отдавать в Kubernetes API.

**Пример: RPS по подам (Pods метрика)**
```yaml
config.yaml: |
  rules:
    # HTTP Requests Per Second (RPS) на каждый под
    - seriesQuery: 'http_requests_total{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        matches: "^(.*)_total$"
        as: "${1}_per_second"
      metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'
```

**Пример: Latency P99 по Ingress (Object метрика)**
```yaml
    # P99 latency для Ingress
    - seriesQuery: 'http_request_duration_seconds_bucket{namespace!="",ingress!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          ingress: {resource: "ingress", group: "networking.k8s.io", version: "v1"}
      name:
        matches: "^(.*)_bucket$"
        as: "${1}_p99"
      metricsQuery: 'histogram_quantile(0.99, sum(rate(<<.Series>>{<<.LabelMatchers>>}[5m])) by (le, <<.GroupBy>>))'
```

**Пример: Длина очереди RabbitMQ (External метрика)**
```yaml
    # Количество сообщений в очереди RabbitMQ
    - seriesQuery: 'rabbitmq_queue_messages{queue!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
      name:
        as: "queue_depth"
      metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>}) by (<<.GroupBy>>)'
```

**Пример: Кастомная метрика с производной**
```yaml
    # Активные соединения на под
    - seriesQuery: 'net_connections_established{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        as: "active_connections"
      metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>}) by (<<.GroupBy>>)'
```

### Шаг 3: Применение конфигурации

```bash
# Обновление через Helm
helm upgrade prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --values values.yaml

# Или через kubectl (если configmap управляется вручную)
kubectl apply -f prometheus-adapter-config.yaml -n monitoring
kubectl rollout restart deployment prometheus-adapter -n monitoring
```

### Шаг 4: Проверка доступности метрик

```bash
# Все доступные custom metrics
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq .

# Конкретная метрика для подов
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/http_requests_per_second" | jq .

# Метрика для Ingress (Object)
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/ingresses.networking.k8s.io/*/http_request_duration_seconds_p99" | jq .

# Все доступные external metrics
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq .
```

**Ожидаемый результат:**
```json
{
  "kind": "MetricValueList",
  "apiVersion": "custom.metrics.k8s.io/v1beta1",
  "metadata": {},
  "items": [
    {
      "describedObject": {
        "kind": "Pod",
        "name": "my-app-abc123",
        "namespace": "default",
        "apiVersion": "/v1"
      },
      "metricName": "http_requests_per_second",
      "timestamp": "2026-09-08T10:00:00Z",
      "value": "150m"
    }
  ]
}
```

### Шаг 5: Создание HPA с custom metrics

**HPA по RPS на под (Pods метрика):**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-rps-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "500"  # 500 RPS на под
```

**HPA по Latency P99 (Pods метрика):**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-latency-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 15
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_request_duration_seconds_p99
        target:
          type: AverageValue
          averageValue: "500m"  # P99 < 500ms = 0.5 секунды
```

**HPA по нагрузке на Ingress (Object метрика):**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-ingress-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: my-app-ingress
        metric:
          name: http_request_duration_seconds_p99
        target:
          type: Value
          value: "500m"  # P99 < 500ms
```

### Шаг 6: Мультиметрика (CPU + custom)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-multi-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 3
  maxReplicas: 25
  metrics:
    # Метрика 1: CPU (базовая)
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    # Метрика 2: RPS (бизнес-метрика)
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "500"
    # Метрика 3: Latency (SLA)
    - type: Pods
      pods:
        metric:
          name: http_request_duration_seconds_p99
        target:
          type: AverageValue
          averageValue: "500m"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
```

**Логика:** HPA рассчитывает целевое количество реплик для каждой метрики и выбирает **наибольшее** значение. Если CPU требует 5 реплик, а RPS — 8, HPA масштабирует до 8.

### Диагностика проблем

| Проблема | Команда диагностики | Решение |
|:---|:---|:---|
| Custom metrics API не доступен | `kubectl get apiservice \| grep custom.metrics` | Проверить Pod adapter, перезапустить |
| Метрика не отображается | `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" \| jq .` | Проверить PromQL в config.yaml |
| HPA показывает `<unknown>` | `kubectl describe hpa <name>` (Events) | Проверить имя метрики в HPA vs config |
| Adapter не подключается к Prometheus | `kubectl logs -n monitoring deploy/prometheus-adapter` | Проверить URL Prometheus, network policy |
| Нет данных для PromQL | `kubectl port-forward -n monitoring svc/prometheus 9090` | Проверить PromQL в Prometheus UI |

**Проверка логов Adapter:**
```bash
kubectl logs -n monitoring deploy/prometheus-adapter -f | grep -i "error\|fail\|custom"
```

**Проверка доступности Prometheus:**
```bash
kubectl exec -n monitoring deploy/prometheus-adapter -- \
  wget -qO- http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090/api/v1/query?query=up
```

---

## Дополнительная информация

### Лучшие практики

1. **Стабильные имена метрик:** В `name.as` используйте предсказуемые имена без автоматических суффиксов — это упрощает отладку HPA.
2. **Время агрегации:** В `metricsQuery` используйте окно `[2m]`–`[5m]` для rate/irate. Слишком короткое окно → шумные метрики, слишком длинное → запаздывание.
3. **Cardinality:** Избегайте PromQL с высокой кардинальностью (undreds of unique label values) — это нагрузка на Prometheus и Adapter.
4. **Ресурсы Adapter:** Установите `resources.requests` для самого Adapter — он опрашивает Prometheus каждые 15 секунд и может потреблять CPU при большом количестве правил.
5. **Тестирование PromQL:** Всегда проверяйте PromQL-запрос в Prometheus UI перед добавлением в config.yaml.

### RBAC для Adapter

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-adapter
rules:
  - apiGroups: ["custom.metrics.k8s.io"]
    resources: ["*"]
    verbs: ["list", "watch"]
  - apiGroups: ["external.metrics.k8s.io"]
    resources: ["*"]
    verbs: ["list", "watch"]
```

### Совместимость с версиями Kubernetes

| Версия Prometheus Adapter | Минимальная версия Kubernetes | API |
|:---|:---|:---|
| v0.11+ | 1.24+ | `custom.metrics.k8s.io/v1beta2` |
| v0.12+ | 1.26+ | `custom.metrics.k8s.io/v1beta1` (stable) |

### См. также

- **[HPA: Основные концепции](./hpa_concepts.md)** — типы метрик и формула расчёта
- **[HPA: Практические сценарии](./hpa_scenarios.md)** — YAML-манифесты для каждого типа метрик
- **[KEDA: Основные концепции](../keda/keda_concepts.md)** — альтернатива Prometheus Adapter для event-driven метрик
- **[Устранение неполадок HPA](../../Troubleshooting/Common_Errors/hpa_troubleshooting.md)** — диагностика проблем с метриками
