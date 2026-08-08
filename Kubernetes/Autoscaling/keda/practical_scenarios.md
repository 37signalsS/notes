# KEDA: Практические сценарии

## Определения и базовые концепции

Данный материал содержит прикладные примеры конфигурации. Теоретическая база, описания компонентов (Operator, Metrics Server) и глоссарий представлены в основном файле:

* **[KEDA: Основные концепции](./keda_concepts.md)**

## Практические сценарии

### Предварительные требования

* Кластер Kubernetes 1.27+
* Helm 3.12+
* Установленный Prometheus (для соответствующих сценариев)
* Настроенный доступ к внешним источникам событий (RabbitMQ, Kafka, AWS SQS)
* Для облачных сценариев: настроенный **Workload Identity** (замена устаревшему Pod Identity)

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
  --set prometheus.operator.enabled=true

# (Опционально) Установка KEDA HTTP Add-on для масштабирования HTTP-трафика
helm install http-add-on kedacore/keda-http-add-on \
  --namespace keda
```

### Проверка готовности

После установки проверьте состояние подов:

```bash
kubectl get pods -n keda
# → keda-operator-..., keda-metrics-apiserver-..., keda-admission-webhooks-...
```

### Сценарий 1: Масштабирование Deployment (RabbitMQ)

Классический сценарий для воркеров, обрабатывающих сообщения из очереди. При пустой очереди количество подов уменьшается до 0. Использование `activationThreshold` предотвращает запуск подов при единичных сообщениях.

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
        queueLength: "5"            # 1 под на каждые 5 сообщений
        activationThreshold: "3"    # Не масштабировать из 0, пока в очереди < 3 сообщений
```

### Сценарий 2: Масштабирование задач (ScaledJob)

Используется для тяжелых задач, где один запуск Job соответствует одному событию. Параметр `idleReplicaCount: 0` гарантирует отсутствие ресурсов в простое.

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
  maxReplicaCount: 100
  idleReplicaCount: 0 # Явно указываем отсутствие Job при отсутствии событий
  triggers:
    - type: aws-sqs
      metadata:
        queueURL: https://sqs.us-east-1.amazonaws.com/12345678/video-tasks
        queueLength: "1"
      authenticationRef:
        name: aws-workload-identity-auth # Рекомендуется использовать IAM Roles for Service Accounts
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

### Сценарий 6: Масштабирование HTTP до нуля (KEDA HTTP Add-on)

Требует установленного `keda-http-add-on`. Позволяет масштабировать приложение на основе количества ожидающих HTTP-запросов.

```yaml
apiVersion: http.keda.sh/v1alpha1
kind: HTTPScaledObject
metadata:
  name: web-app-scaler
spec:
  host: my-service.example.com
  scaleTargetRef:
    name: web-app-deployment
    kind: Deployment
    apiVersion: apps/v1
  replicas:
    min: 0
    max: 20
  targetPendingRequests: 100 # Целевое кол-во запросов в очереди на один под
  scaledownPeriod: 300
```

### Сценарий 7: Масштабирование на основе ресурсов K8s (ConfigMap)

Используется, когда внешняя система записывает текущий уровень нагрузки в ConfigMap кластера.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: configmap-scaler
spec:
  triggers:
    - type: kubernetes-resource
      metadata:
        resourceKind: "ConfigMap"
        resourceName: "external-load-metrics"
        key: "current_rps"
        format: "number"
        targetValue: "100"
        activationTargetValue: "10" # Масштабировать из 0 только если RPS > 10
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

Для включения выгрузки метрик и трейсов в формате OTLP при установке через Helm:

```bash
helm upgrade keda kedacore/keda \
  --set otel.enabled=true \
  --set otel.collectorUri="otel-collector.monitoring.svc:4317" \
  --set otel.protocol="grpc"
```
После включения становятся доступны метрики задержки масштабирования (`scaling_latency`), что позволяет отследить время от появления события в очереди до запуска пода.

### Рекомендации по эксплуатации

1.  **Безопасный Scale Down:** Для критичных Stateful нагрузок используйте `cooldownPeriod` не менее 600 секунд (10 минут), чтобы избежать частого перезапуска подов при колебаниях трафика.
2.  **Pod Disruption Budget (PDB):** Всегда настраивайте PDB для масштабируемых нагрузок. При резком падении нагрузки KEDA может попытаться удалить слишком много подов одновременно, что может нарушить доступность.
3.  **Борьба с Cold Start:** Если приложение запускается долго (>30 сек), избегайте `minReplicaCount: 0`. Используйте `minReplicaCount: 1`, если бизнес-логика требует мгновенной реакции.
4.  **Валидация триггеров:** Перед применением в Prod проверяйте запросы PromQL в интерфейсе Prometheus. KEDA не проверяет корректность самой логики запроса.
5.  **Лимиты для ScaledJob:** Всегда устанавливайте `maxReplicaCount` для `ScaledJob`, чтобы избежать исчерпания ресурсов кластера (например, при внезапном наплыве миллионов сообщений в очередь).
6.  **Аутентификация:** Предпочитайте использование **Workload Identity** (IAM-роли) вместо явных секретов в `TriggerAuthentication` для облачных скейлеров (AWS, GCP, Azure).

## См. также

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура и определения
* **[Паттерн Workers + Queue](../workers_queue_pattern.md)** — проектирование систем обработки очередей
* **[Horizontal Pod Autoscaler (HPA): Практические сценарии](../HPA/hpa_scenarios.md)** — стандартное масштабирование
* **[Karpenter: Обзор и концепции](../Karpenter/overview.md)** — динамическое масштабирование узлов под нагрузку KEDA
