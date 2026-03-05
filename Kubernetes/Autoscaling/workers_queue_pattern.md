# Паттерн Workers + Queue в Kubernetes

## Определения

**Workers + Queue** — архитектурный паттерн для асинхронной обработки задач через очередь сообщений, где Workers масштабируются по длине очереди.

**Producer** — сервис, генерирующий задачи и помещающий их в очередь.

**Consumer (Worker)** — под, извлекающий и обрабатывающий задачи из очереди.

**Идемпотентность** — свойство обработки задачи, при котором повторное выполнение не приводит к ошибкам или дублированию результата.

**Dead Letter Queue (DLQ)** — очередь для неудачных задач, требующих ручного разбора.

## Основные концепции

### Архитектура Workers + Queue

Архитектура для фоновой обработки:
* **Очередь сглаживает пиковые нагрузки** — буфер между Producer и Consumer
* **Workers масштабируются по длине очереди** — эластичное потребление ресурсов
* **Гарантируется доставка сообщений** — подтверждение обработки

#### Требования к задачам

| Требование | Описание | Реализация |
|------------|----------|------------|
| **Идемпотентность** | Повторная обработка не приводит к ошибкам | Уникальные ID задач, проверка состояния |
| **Дедупликация** | Предотвращение двойной обработки | Таблица обработанных задач, TTL |
| **Ограничение параллелизма** | Контроль нагрузки на внешние системы | Semaphore, rate limiting |
| **Timeout обработки** | Защита от зависших задач | Deadline, heartbeat |
| **Dead Letter Queue** | Обработка неудачных задач | DLQ для ручного разбора |

#### Паттерны обработки очередей

| Паттерн | Описание | Когда использовать |
|---------|----------|-------------------|
| **Competing Consumers** | Несколько Workers обрабатывают одну очередь | Балансировка нагрузки |
| **Publisher-Subscriber** | Одно сообщение — множеству подписчиков | Уведомления, события |
| **Priority Queue** | Обработка по приоритету | Критические задачи вперёд |
| **Scheduled Messages** | Отложенная обработка | Таймеры, напоминания |

## Практические сценарии

### Сценарий 1: Workers + Queue с HPA (внешние метрики)

```yaml
# Deployment Workers
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-workers
spec:
  replicas: 2
  selector:
    matchLabels:
      app: order-workers
  template:
    metadata:
      labels:
        app: order-workers
    spec:
      containers:
        - name: worker
          image: order-processor:latest
          env:
            - name: RABBITMQ_HOST
              value: "rabbitmq"
            - name: QUEUE_NAME
              value: "orders"
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
---
# HPA с внешней метрикой (длина очереди)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: workers-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: order-workers
  minReplicas: 1
  maxReplicas: 50
  metrics:
    - type: External
      external:
        metric:
          name: queue_messages_ready
        target:
          type: AverageValue
          averageValue: "100"  # 1 под на 100 сообщений
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
        - type: Percent
          value: 50
          periodSeconds: 60
```

### Сценарий 2: Workers + Queue с KEDA (рекомендуется)

```yaml
# ScaledObject KEDA для RabbitMQ
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-workers-scaledobject
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: order-workers
  minReplicaCount: 2
  maxReplicaCount: 50
  pollingInterval: 10
  cooldownPeriod: 300
  triggers:
    - type: rabbitmq
      metadata:
        queueName: orders
        host: amqp://rabbitmq:5672
        queueLength: "20"  # Целевое значение: 20 сообщений на под
```

**Преимущества KEDA:**
* Масштабирование до нуля при отсутствии задач
* 60+ источников событий (Kafka, SQS, Prometheus)
* Встроенная аутентификация через `TriggerAuthentication`

### Сценарий 3: Priority Queue с несколькими очередями

```yaml
# Workers для критических задач
apiVersion: apps/v1
kind: Deployment
metadata:
  name: priority-workers
spec:
  replicas: 5
  selector:
    matchLabels:
      app: priority-workers
      priority: high
  template:
    metadata:
      labels:
        app: priority-workers
        priority: high
    spec:
      containers:
        - name: worker
          image: task-processor:latest
          env:
            - name: QUEUE_NAME
              value: "priority-tasks"
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
---
# Workers для обычных задач
apiVersion: apps/v1
kind: Deployment
metadata:
  name: standard-workers
spec:
  replicas: 3
  selector:
    matchLabels:
      app: standard-workers
      priority: normal
  template:
    metadata:
      labels:
        app: standard-workers
        priority: normal
    spec:
      containers:
        - name: worker
          image: task-processor:latest
          env:
            - name: QUEUE_NAME
              value: "standard-tasks"
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
```

## Дополнительная информация

### Интеграция с Kubernetes

| Компонент | Интеграция |
|-----------|------------|
| **[HPA](./hpa_detailed.md)** | Масштабирование workers по внешним метрикам (длина очереди) |
| **[KEDA](./keda_detailed.md)** | Рекомендуемое решение для событийного масштабирования |
| **[Pod Distribution](./pod_distribution.md)** | Распределение workers по узлам для отказоустойчивости |
| **[Pod Disruption Budget](./pod_disruption_budget.md)** | Защита workers при масштабировании узлов |
| **[Cluster Autoscaler](./cluster_autoscaler_detailed.md)** | Добавление узлов при масштабировании workers |

### Технологии очередей

| Технология | Назначение | Интеграция с KEDA |
|------------|------------|-------------------|
| **RabbitMQ** | Традиционные очереди с подтверждением | ✅ RabbitMQ scaler |
| **Apache Kafka** | Потоковая обработка с высокой пропускной способностью | ✅ Kafka scaler |
| **AWS SQS** | Управляемая очередь без инфраструктурных затрат | ✅ AWS SQS scaler |
| **Azure Service Bus** | Управляемая очередь в Azure | ✅ Azure Service Bus scaler |
| **Google Pub/Sub** | Потоковая передача событий в GCP | ✅ Google Pub/Sub scaler |
| **Redis Streams** | Лёгковесная очередь на базе Redis | ✅ Redis Streams scaler |

### Мониторинг

| Метрика | Описание | Алерт |
|---------|----------|-------|
| `queue_length` | Длина очереди | >1000 сообщений |
| `processing_latency` | Задержка обработки | >5 секунд |
| `error_rate` | Процент ошибок | >1% |
| `consumer_lag` (Kafka) | Отставание потребителя | >10000 сообщений |
| `dead_letter_queue_size` | Размер DLQ | >100 задач |

### Сценарии использования

| Сценарий | Обоснование |
|----------|-------------|
| Видео-обработка, отчёты | Асинхронная обработка, сглаживание пиков |
| Пиковые нагрузки с непредсказуемым трафиком | Очередь как буфер |
| Обработка платежей | Асинхронность + гарантии доставки |

### Ресурсы

* [KEDA Scalers Documentation](https://keda.sh/docs/latest/scalers/)
* [Kubernetes HPA with Custom Metrics](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/)
