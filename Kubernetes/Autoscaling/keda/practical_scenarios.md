# KEDA: Практические сценарии

## Определения

Для получения полных определений компонентов KEDA (Kubernetes Event-driven Autoscaling) обратитесь к основному файлу:

* **[KEDA: Основные концепции](./keda_concepts.md)**

## Основные концепции

KEDA расширяет возможности HPA (Horizontal Pod Autoscaler), позволяя масштабировать приложения на основе данных из внешних источников. Подробное описание архитектуры и принципов работы приведено в SSoT-файле:

* **[KEDA: Основные концепции](./keda_concepts.md)**

## Практические сценарии

### Предварительные требования

* Кластер Kubernetes 1.23+
* Helm 3.x
* Metrics Server для базовых метрик кластера
* Доступ к источникам событий (RabbitMQ, Kafka, Prometheus)

### Установка KEDA

Установка выполняется через Helm — менеджер пакетов для Kubernetes.

```bash
# Добавление репозитория
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# Установка оператора в отдельный namespace
helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version 2.19.0

# Проверка статуса компонентов
kubectl get pods -n keda
# → keda-operator-..., keda-metrics-apiserver-..., keda-admission-webhooks-...

# Проверка регистрации API
kubectl get apiservice v1beta1.external.metrics.k8s.io
# → v1beta1.external.metrics.k8s.io   keda/keda-metrics-apiserver   True   ...
```

### Сценарий 1: Масштабирование по очереди RabbitMQ

Масштабирование воркеров на основе количества готовых к обработке сообщений в очереди.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-consumer-scaledobject
  namespace: default
spec:
  scaleTargetRef:
    name: rabbitmq-consumer # Целевой Deployment

  minReplicaCount: 0 # Масштабирование до нуля при пустой очереди
  maxReplicaCount: 30

  pollingInterval: 15 # Интервал опроса очереди (секунды)
  cooldownPeriod: 300 # Период стабилизации после снижения нагрузки

  triggers:
    - type: rabbitmq
      metadata:
        queueName: orders
        host: amqp://rabbitmq:5672
        queueLength: "10" # Цель: 1 под на каждые 10 сообщений
```

### Сценарий 2: Масштабирование по очереди Kafka с аутентификацией

Использование `TriggerAuthentication` для безопасного хранения учетных данных.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaledobject
spec:
  scaleTargetRef:
    name: kafka-consumer

  minReplicaCount: 1
  maxReplicaCount: 50

  pollingInterval: 10

  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-broker:9092
        consumerGroup: my-consumer-group
        topic: orders
        lagThreshold: "100" # Масштабирование при отставании (lag) > 100 сообщений
      authenticationRef:
        name: kafka-trigger-auth
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-trigger-auth
spec:
  secretTargetRef:
    - parameter: sasl # Simple Authentication and Security Layer
      name: kafka-secret
      key: sasl
    - parameter: username
      name: kafka-secret
      key: username
    - parameter: password
      name: kafka-secret
      key: password
```

### Сценарий 3: Масштабирование по метрикам Prometheus

Использование PromQL (Prometheus Query Language) запросов для принятия решений о масштабировании.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: prometheus-scaledobject
spec:
  scaleTargetRef:
    name: web-api

  minReplicaCount: 2
  maxReplicaCount: 20

  pollingInterval: 30

  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        metricName: http_requests_per_second
        threshold: "100"
        query: |
          sum(rate(http_requests_total{service="web-api"}[1m]))
```

### Сценарий 4: Масштабирование по расписанию (Cron)

Позволяет заранее подготовить ресурсы к прогнозируемым скачкам нагрузки.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: cron-scaledobject
spec:
  scaleTargetRef:
    name: batch-processor

  minReplicaCount: 0
  maxReplicaCount: 10

  triggers:
    # Рабочие часы (9:00-18:00, пн-пт) — минимум 5 реплик
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: 0 9 * * mon-fri
        end: 0 18 * * mon-fri
        desiredReplicas: "5"

    # Остальное время — 0 реплик
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: 0 18 * * mon-fri
        end: 0 9 * * mon-fri
        desiredReplicas: "0"
```

### Сценарий 5: Несколько триггеров (логика ИЛИ)

KEDA вычисляет целевое количество реплик для каждого триггера и выбирает максимальное значение.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: multi-trigger-scaledobject
spec:
  scaleTargetRef:
    name: order-processor

  minReplicaCount: 0
  maxReplicaCount: 50

  fallback: # Резервное количество реплик при сбое источников метрик
    failureThreshold: 3
    replicas: 5

  triggers:
    # Триггер 1: Очередь RabbitMQ
    - type: rabbitmq
      metadata:
        queueName: orders
        host: amqp://rabbitmq:5672
        queueLength: "20"

    # Триггер 2: CPU (Central Processing Unit) через Prometheus
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        metricName: cpu_utilization
        threshold: "80"
        query: |
          avg(rate(container_cpu_usage_seconds_total{pod=~"order-processor.*"}[1m])) * 100
```

### Сценарий 6: Тонкая настройка поведения (Behavior)

Настройка скорости масштабирования для предотвращения резких колебаний (дребезга).

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: advanced-behavior-scaledobject
spec:
  scaleTargetRef:
    name: api-server

  minReplicaCount: 2
  maxReplicaCount: 100

  pollingInterval: 10
  cooldownPeriod: 300

  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleUp:
          stabilizationWindowSeconds: 0 # Мгновенный рост
          policies:
            - type: Percent
              value: 100
              periodSeconds: 15
            - type: Pods
              value: 10
              periodSeconds: 15
          selectPolicy: Max
        scaleDown:
          stabilizationWindowSeconds: 600 # Плавное снижение (10 минут)
          policies:
            - type: Percent
              value: 50
              periodSeconds: 60
          selectPolicy: Min
```

## Дополнительная информация

### Диагностика и мониторинг

Для проверки состояния ресурсов KEDA и отладки используйте следующие команды:

```bash
# Список ScaledObject в текущем namespace
kubectl get scaledobject
# → NAME                             SCALETARGETKIND      SCALETARGETNAME    READY   ACTIVE   AGE

# Просмотр событий и статуса конкретного ресурса
kubectl describe scaledobject rabbitmq-consumer-scaledobject

# Проверка HPA, созданного оператором KEDA
kubectl get hpa
# → keda-hpa-rabbitmq-consumer-scaledobject   Deployment/rabbitmq-consumer   ...

# Проверка доступности External Metrics API
kubectl get --raw /apis/external.metrics.k8s.io/v1beta1
```

### Ключевые метрики оператора

| Метрика | Описание |
| :--- | :--- |
| `keda_scaledobject_status` | Текущий статус ScaledObject (1 = Ready, 0 = Error) |
| `keda_scaledobject_ready` | Индикатор готовности объекта к работе |
| `keda_scaler_active` | Состояние активности конкретного scaler'а |
| `keda_scaling_operations_total` | Общее количество выполненных операций масштабирования |

### Лучшие практики

* **Избегайте Scale-to-Zero в Production:** Для критических сервисов рекомендуется `minReplicaCount: 1`, чтобы исключить задержку "холодного старта".
* **Используйте Fallback:** Всегда настраивайте блок `fallback` для сохранения работоспособности приложения при недоступности внешних систем мониторинга.
* **Безопасность данных:** Используйте `TriggerAuthentication` совместно с Kubernetes Secret для хранения паролей и токенов.
* **Период стабилизации:** Настраивайте `cooldownPeriod` (по умолчанию 300 секунд), чтобы предотвратить "флаппинг" (частые изменения количества реплик при пограничных значениях метрик).
* **Мониторинг задержек:** Учитывайте, что `pollingInterval` напрямую влияет на скорость реакции. Не устанавливайте его слишком низким (< 5с), чтобы не перегружать источники метрик.

## См. также

* **[KEDA: Основные концепции](./keda_concepts.md)** — SSoT по архитектуре и компонентам
* **[HPA: Практические сценарии](../HPA/hpa_scenarios.md)** — примеры нативного масштабирования
* **[Паттерн Workers + Queue](../workers_queue_pattern.md)** — архитектурные подходы к очередям
