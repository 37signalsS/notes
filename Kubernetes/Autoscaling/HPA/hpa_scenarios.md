# Horizontal Pod Autoscaler (HPA): Практические сценарии

## 1. Предварительные требования

### 1.1. Установка Metrics Server

Для работы с базовыми метриками (`cpu`, `memory`) в кластере должен быть развернут **Metrics Server**:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

[Подробнее](../MonitoringLogging/metrics-server.md)

### 1.2. Задать requests для контейнеров

Чтобы HPA мог корректно рассчитывать утилизацию CPU в процентах, у контейнеров должны быть установлены `requests`:

```yaml
resources:
  requests:
    cpu: "200m"  # 200 милли-ядер
    memory: "256Mi"
```

## 2. Сценарий 1: Базовый HPA по CPU

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

## 3. Сценарий 2: HPA по CPU и памяти

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

## 4. Сценарий 3: HPA с внешними метриками (очередь)

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

> **Примечание:** Для внешних метрик требуется Prometheus Adapter или [KEDA](../Autoscaling/keda_detailed.md).

## 5. Сценарий 4: HPA с продвинутым поведением

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

## 6. Сценарий 5: HPA с кастомными метриками Prometheus

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

## Связанные документы

- **[Основные концепции](./hpa_concepts.md)** — определения, алгоритм, типы метрик
- **[Дополнительные темы](./hpa_advanced.md)** — диагностика, проблемы, best practices
- **[KEDA](../Autoscaling/keda_detailed.md)** — событийное масштабирование
- **[Metrics Server](../MonitoringLogging/metrics-server.md)** — источник метрик
