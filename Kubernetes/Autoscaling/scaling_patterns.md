# Паттерны масштабирования

## Определения

**Шардирование (Sharding)** — разделение рабочей нагрузки на изолированные группы (шарды) с независимым масштабированием и управлением.

**Workers + Queue** — архитектурный паттерн для асинхронной обработки задач через очередь сообщений, где Workers масштабируются по длине очереди.

**Producer** — сервис, генерирующий задачи и помещающий их в очередь.

**Consumer (Worker)** — под, извлекающий и обрабатывающий задачи из очереди.

**Идемпотентность** — свойство обработки задачи, при котором повторное выполнение не приводит к ошибкам или дублированию результата.

## Основные концепции

### Шардирование

Разделение трафика по ключу позволяет:
* **Изолировать сбои** — проблема в одном шарде не влияет на другие
* **Обеспечить локальность данных** — данные клиента хранятся в одном шарде
* **Обойти ограничения** — масштабирование beyond limits отдельных компонентов

#### Ключи шардирования

| Ключ | Описание | Пример |
|------|----------|--------|
| **Регион пользователя** | Географическое разделение | `us-west`, `eu-central`, `ap-south` |
| **ID клиента** | Хеш или диапазон ID | `customer_id % 10` |
| **Тип подписки** | Тарифный план | `free`, `premium`, `enterprise` |
| **Хеш данных** | Равномерное распределение | `hash(order_id) % 8` |

#### Типы шардирования

| Тип | Описание | Когда использовать |
|-----|----------|-------------------|
| **Горизонтальное** | Разделение по ключу (регион, клиент) | Мультирегиональные приложения |
| **Вертикальное** | Разделение по функциональности | Микросервисная архитектура |
| **Гибридное** | Комбинация подходов | Сложные распределённые системы |

### Workers + Queue

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

### Сценарий 1: Шардирование по региону

```yaml
# Deployment для шарда A (US)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-shard-us
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
      shard: us
  template:
    metadata:
      labels:
        app: webapp
        shard: us
    spec:
      containers:
        - name: app
          image: myapp:latest
          env:
            - name: SHARD_ID
              value: "us"
            - name: ALLOWED_REGIONS
              value: "us-west,us-east"
---
apiVersion: v1
kind: Service
metadata:
  name: service-us
spec:
  selector:
    app: webapp
    shard: us
  ports:
    - port: 80
      targetPort: 8080
---
# Deployment для шарда B (EU)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-shard-eu
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
      shard: eu
  template:
    metadata:
      labels:
        app: webapp
        shard: eu
    spec:
      containers:
        - name: app
          image: myapp:latest
          env:
            - name: SHARD_ID
              value: "eu"
            - name: ALLOWED_REGIONS
              value: "eu-west,eu-central"
---
apiVersion: v1
kind: Service
metadata:
  name: service-eu
spec:
  selector:
    app: webapp
    shard: eu
  ports:
    - port: 80
      targetPort: 8080
```

**Маршрутизация на уровне Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shard-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
    - host: us.api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service-us
                port:
                  number: 80
    - host: eu.api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service-eu
                port:
                  number: 80
```

### Сценарий 2: Workers + Queue с HPA (внешние метрики)

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

### Сценарий 3: Workers + Queue с KEDA (рекомендуется)

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

### Сценарий 4: Шардирование с независимым масштабированием

```yaml
# HPA для каждого шарда
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shard-us-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webapp-shard-us
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shard-eu-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webapp-shard-eu
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

### Сценарий 5: Priority Queue с несколькими очередями

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

### Выбор паттерна

| Сценарий | Рекомендуемый паттерн | Обоснование |
|----------|----------------------|-------------|
| Видео-обработка, отчёты | Workers + Queue | Асинхронная обработка, сглаживание пиков |
| Мультирегиональное приложение | Шардирование | Локальность данных, compliance (GDPR) |
| Пиковые нагрузки с непредсказуемым трафиком | Workers + Queue | Очередь как буфер |
| Требования к изоляции клиентов | Шардирование | Изоляция сбоев, безопасность |
| Обработка платежей | Шардирование + Workers | Изоляция + асинхронность |
| Real-time аналитика | Шардирование по времени | Разделение по временным окнам |

## Дополнительная информация

### Интеграция с Kubernetes

| Компонент | Интеграция |
|-----------|------------|
| **[HPA](hpa_detailed.md)** | Масштабирование workers по внешним метрикам (длина очереди) |
| **[KEDA](keda_detailed.md)** | Рекомендуемое решение для событийного масштабирования |
| **[Pod Distribution](pod_distribution.md)** | Распределение шардов по узлам/зонам для отказоустойчивости |
| **[Pod Disruption Budget](pod_disruption_budget.md)** | Защита workers при масштабировании узлов |
| **[Cluster Autoscaler](cluster_autoscaler_detailed.md)** | Добавление узлов при масштабировании workers |

### Технологии очередей

| Технология | Назначение | Интеграция с KEDA |
|------------|------------|-------------------|
| **RabbitMQ** | Традиционные очереди с подтверждением | ✅ RabbitMQ scaler |
| **Apache Kafka** | Потоковая обработка с высокой пропускной способностью | ✅ Kafka scaler |
| **AWS SQS** | Управляемая очередь без инфраструктурных затрат | ✅ AWS SQS scaler |
| **Azure Service Bus** | Управляемая очередь в Azure | ✅ Azure Service Bus scaler |
| **Google Pub/Sub** | Потоковая передача событий в GCP | ✅ Google Pub/Sub scaler |
| **Redis Streams** | Лёгковесная очередь на базе Redis | ✅ Redis Streams scaler |

### Дополнительные соображения

#### Маршрутизация шардов

| Уровень | Реализация |
|---------|------------|
| **Ingress** | На основе host/path (см. Сценарий 1) |
| **API Gateway** | На основе заголовков, JWT claims |
| **Клиентская** | Клиент определяет шард по ключу |
| **Service Mesh** | Istio VirtualService для маршрутизации |

#### Ребалансировка

* **Планирование миграции** — постепенное перемещение данных между шардами
* **Consistent Hashing** — минимизация перемещений при изменении количества шардов
* **Dual-write** — запись в старый и новый шард во время миграции

#### Мониторинг

| Метрика | Описание | Алерт |
|---------|----------|-------|
| `queue_length` | Длина очереди | >1000 сообщений |
| `processing_latency` | Задержка обработки | >5 секунд |
| `error_rate` | Процент ошибок | >1% |
| `consumer_lag` (Kafka) | Отставание потребителя | >10000 сообщений |
| `dead_letter_queue_size` | Размер DLQ | >100 задач |

### Ресурсы

* [KEDA Scalers Documentation](https://keda.sh/docs/latest/scalers/)
* [Kubernetes HPA with Custom Metrics](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/)
* [Sharding Patterns (Microservices.io)](https://microservices.io/patterns/data/sharding.html)
