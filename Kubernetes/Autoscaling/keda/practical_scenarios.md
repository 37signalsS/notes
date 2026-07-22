# KEDA: Практические сценарии

## Определения

Для ознакомления с терминологией и описанием компонентов KEDA (Kubernetes Event-driven Autoscaling) обратитесь к основному источнику истины:

* **[KEDA: Основные концепции](./keda_concepts.md)**

## Базовые концепции

В данном файле представлены прикладные примеры настройки автоматического масштабирования. Все примеры используют API `keda.sh/v1alpha1`. Для понимания архитектуры (Operator, Metrics Server) см.:

* **[KEDA: Основные концепции](./keda_concepts.md)**

## Практические сценарии

### Предварительные требования

* Кластер Kubernetes 1.25+
* Helm 3.10+
* Установленный Prometheus (для соответствующих сценариев)
* Доступ к внешним источникам событий (RabbitMQ, Kafka и др.)

### Установка KEDA

Рекомендуемый способ установки — использование официального Helm-чарта.

```bash
# Добавление репозитория
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# Установка версии 2.20.0 (актуально на июнь 2026)
helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version 2.20.0 \
  --set prometheus.operator.enabled=true # Включение сервис-мониторов для Prometheus

# Проверка готовности
kubectl get pods -n keda
# → keda-operator-..., keda-metrics-apiserver-..., keda-admission-webhooks-...
```

### Сценарий 1: Масштабирование Deployment (RabbitMQ)

Классический сценарий для воркеров, обрабатывающих сообщения из очереди. При пустой очереди количество подов уменьшается до 0.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-worker-scaler
  namespace: prod
spec:
  scaleTargetRef:
    name: worker-deployment
  minReplicaCount: 0 
  maxReplicaCount: 50
  pollingInterval: 10
  cooldownPeriod: 300
  triggers:
    - type: rabbitmq
      metadata:
        queueName: task-queue
        host: amqp://guest:guest@rabbitmq.default.svc.cluster.local:5672
        queueLength: "5" # 1 под на каждые 5 сообщений
```

### Сценарий 2: Масштабирование задач (ScaledJob)

Используется для тяжелых задач, где один запуск Job соответствует одному событию. KEDA создаёт новую Job для каждого сообщения.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: video-transcoder-job
spec:
  jobTargetRef:
    parallelism: 1
    completions: 1
    template:
      spec:
        containers:
          - name: transcoder
            image: my-registry/video-tool:latest
        restartPolicy: OnFailure
  pollingInterval: 30
  maxReplicaCount: 100 # Максимальное количество одновременно запущенных Job
  scalingStrategy:
    strategy: "default"
  triggers:
    - type: aws-sqs
      metadata:
        queueURL: https://sqs.us-east-1.amazonaws.com/12345678/video-tasks
        queueLength: "1" # Одна Job на одно сообщение в SQS
      authenticationRef:
        name: aws-trigger-auth
```

### Сценарий 3: Глобальная аутентификация (ClusterTriggerAuthentication)

Позволяет переиспользовать учетные данные Kafka во всех пространствах имен.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ClusterTriggerAuthentication
metadata:
  name: global-kafka-auth
spec:
  secretTargetRef:
    - parameter: sasl
      name: kafka-global-secret
      key: sasl-config
---
# Использование в ScaledObject
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-scaler
spec:
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka:9092
        topic: telemetry
        lagThreshold: "100"
      authenticationRef:
        name: global-kafka-auth
        kind: ClusterTriggerAuthentication # Обязательно указать тип
```

### Сценарий 4: Применение модификаторов (Scaling Modifiers)

Пример использования `scalingModifiers` (v2.20+) для коррекции метрики Prometheus перед масштабированием.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: modified-prometheus-scaler
spec:
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        threshold: "100"
        query: sum(rate(http_requests_total[1m]))
  # Умножение полученной метрики на коэффициент 1.5 для агрессивного старта
  scalingModifiers:
    formula: "metricValue * 1.5"
    targetMetricName: "boosted_requests"
```

### Сценарий 5: Смешанное масштабирование (Prometheus + Cron)

Масштабирование по нагрузке, но с гарантированным минимумом в рабочие часы.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: hybrid-scaler
spec:
  minReplicaCount: 0
  triggers:
    # Триггер 1: Нагрузка
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        threshold: "50"
        query: avg(http_requests_per_second)
    # Триггер 2: Расписание (пн-пт, 09:00-18:00)
    - type: cron
      metadata:
        timezone: UTC
        start: 0 9 * * 1-5
        end: 0 18 * * 1-5
        desiredReplicas: "10" # В рабочее время всегда минимум 10
```

## Дополнительная информация

### Диагностика и отладка

Основные команды для проверки состояния:

```bash
# Проверка статуса всех ресурсов масштабирования
kubectl get scaledobject,scaledjob -A

# Детальная информация о причинах сбоя масштабирования
kubectl describe scaledobject <name>

# Просмотр созданного нативного HPA
kubectl get hpa
# → keda-hpa-<name>
```

### Наблюдаемость через OpenTelemetry

Для включения выгрузки метрик в формате OTLP при установке через Helm:

```bash
helm upgrade keda kedacore/keda \
  --set otel.enabled=true \
  --set otel.collectorUri="otel-collector.monitoring.svc:4317"
```
После включения станут доступны специфичные трейсы, позволяющие отследить время от появления события в очереди до запуска пода (`scaling_latency`).

### Рекомендации по эксплуатации

1.  **Безопасный Scale Down:** Для критичных Stateful нагрузок используйте `cooldownPeriod` не менее 600 секунд (10 минут), чтобы избежать частого перезапуска подов при колебаниях трафика.
2.  **Валидация триггеров:** Перед применением в Prod проверяйте запросы PromQL в интерфейсе Prometheus. KEDA не проверяет корректность самой логики запроса, только доступность сервера.
3.  **Лимиты для ScaledJob:** Всегда устанавливайте `maxReplicaCount` для `ScaledJob`, чтобы избежать исчерпания ресурсов кластера (например, при внезапном наплыве миллионов сообщений в очередь).
4.  **Аутентификация:** Предпочитайте использование IAM-ролей (через `podIdentity` или `workloadIdentity`) вместо явных секретов в `TriggerAuthentication` для облачных скейлеров (AWS, GCP, Azure).

## См. также

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура и определения
* **[Паттерн Workers + Queue](../workers_queue_pattern.md)** — проектирование систем обработки очередей
* **[HPA: Практические сценарии](../HPA/hpa_scenarios.md)** — стандартное масштабирование
