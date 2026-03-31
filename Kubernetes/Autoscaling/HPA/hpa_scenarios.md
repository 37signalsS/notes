# Horizontal Pod Autoscaler (HPA): Практические сценарии

## 1. Определения

**Resource Metrics** — базовые метрики ресурсов (CPU, memory), предоставляемые Metrics Server через API `metrics.k8s.io`.

**Custom Metrics** — пользовательские метрики приложений (RPS, latency), предоставляемые через Prometheus Adapter API `custom.metrics.k8s.io`.

**External Metrics** — внешние метрики (очереди, бизнес-показатели), предоставляемые через External Metrics API (KEDA, Prometheus Adapter).

## 2. Базовые концепции

### 2.1. Предварительные требования

#### Установка Metrics Server

Для работы с базовыми метриками (`cpu`, `memory`) в кластере должен быть развернут **Metrics Server**:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

[Подробнее](../../MonitoringLogging/metrics-server.md)

#### Задать requests для контейнеров

Чтобы HPA мог корректно рассчитывать утилизацию CPU в процентах, у контейнеров должны быть установлены `requests`:

```yaml
resources:
  requests:
    cpu: "200m"  # 200 милли-ядер
    memory: "256Mi"
```

### 2.2. Типы сценариев масштабирования

| Тип | Метрика | Когда использовать |
| :--- | :--- | :--- |
| Базовый | CPU | Stateless-приложения с переменной вычислительной нагрузкой |
| Мультиметрика | CPU + Memory | Приложения с разными профилями потребления ресурсов |
| Внешние метрики | Очереди (Kafka, SQS) | Workers, обрабатывающие сообщения из очередей |
| Продвинутый | CPU с behavior | Приложения с резкими скачками нагрузки |
| Кастомные метрики | RPS, latency | Веб-сервисы, API, где важна скорость ответа |

## 3. Практические сценарии

### 3.1. Сценарий 1: Базовый HPA по CPU

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
  namespace: default
spec:
  # Ссылка на масштабируемый ресурс
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app

  # Границы масштабирования
  minReplicas: 3
  maxReplicas: 20

  # Метрики для принятия решений
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60  # Целевая утилизация 60%
```

**Когда использовать:** Stateless-приложения с переменной вычислительной нагрузкой.

### 3.2. Сценарий 2: HPA по CPU и памяти

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: multi-metric-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app

  minReplicas: 3
  maxReplicas: 20

  metrics:
    # CPU метрика
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60

    # Memory метрика
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 70
```

> **Примечание:** HPA выбирает метрику, требующую наибольшего количества реплик.

**Когда использовать:** Приложения с разными профилями потребления ресурсов (например, Java-приложения с высоким потреблением памяти).

### 3.3. Сценарий 3: HPA с внешними метриками (очередь)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: queue-based-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: workers

  minReplicas: 1
  maxReplicas: 50

  metrics:
    # Внешняя метрика из очереди сообщений
    - type: External
      external:
        metric:
          name: queue_messages_ready
        target:
          type: AverageValue
          averageValue: "200"  # 200 сообщений на под
```

> **Примечание:** Для внешних метрик требуется Prometheus Adapter или [KEDA](../keda/basic_concepts.md).

**Когда использовать:** Workers, обрабатывающие сообщения из очередей (Kafka, RabbitMQ, SQS).

### 3.4. Сценарий 4: HPA с продвинутым поведением

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: advanced-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-api

  minReplicas: 5
  maxReplicas: 100

  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70

  # Продвинутое поведение
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0  # Мгновенное масштабирование вверх
      policies:
        - type: Percent
          value: 100  # Увеличение на 100%
          periodSeconds: 15
        - type: Pods
          value: 10  # Или на 10 подов
          periodSeconds: 15
      selectPolicy: Max  # Выбрать максимальное значение

    scaleDown:
      stabilizationWindowSeconds: 300  # 5 минут для стабильности
      policies:
        - type: Percent
          value: 50  # Уменьшение на 50%
          periodSeconds: 60
        - type: Pods
          value: 5  # Или на 5 подов
          periodSeconds: 60
      selectPolicy: Min  # Выбрать минимальное значение
```

**Когда использовать:** Приложения с резкими скачками нагрузки и требованием к стабильности при спадах.

### 3.5. Сценарий 5: HPA с кастомными метриками Prometheus

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: prometheus-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-server

  minReplicas: 2
  maxReplicas: 30

  metrics:
    # Кастомная метрика RPS из Prometheus
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "100"  # 100 RPS на под
```

> **Примечание:** Требуется Prometheus Adapter с настроенными правилами.

**Когда использовать:** Веб-сервисы, API, где важны RPS или latency, а не утилизация CPU.

## 4. Дополнительная информация

### 4.1. Интеграции

- **[KEDA](../keda/basic_concepts.md)** — событийное масштабирование на основе внешних метрик (очереди, расписания).
- **[Metrics Server](../../MonitoringLogging/metrics-server.md)** — источник ресурсных метрик для HPA.
- **[Prometheus Adapter](https://github.com/kubernetes-sigs/prometheus-adapter)** — адаптер для кастомных метрик Prometheus.

---

**Связанные документы:**

- **[Основные концепции](./hpa_concepts.md)** — определения, алгоритм, типы метрик
- **[Дополнительные темы](./hpa_advanced.md)** — диагностика, проблемы, best practices
