# KEDA + Kafka: Масштабирование на основе Consumer Lag

## Определения

**Kafka Scaler** — встроенный скейлер KEDA для масштабирования подов-консьюмеров на основе длины очереди (consumer lag) в Kafka. Подключается напрямую к брокеру через Kafka-клиент или опосредованно через Kafka Exporter/Prometheus. Один из самых распространённых production-сценариев KEDA.

**Consumer Lag** — разница между последним опубликованным-offset в партиции и текущим committed-offset консьюмера. Характеризует количество необработанных сообщений. KEDA использует lag как основную метрику для принятия решения о масштабировании.

**activationLagThreshold** — порог активации, при достижении которого KEDA запускает под из 0 реплик. Отличается от `lagThreshold`: если lag больше `activationLagThreshold`, но меньше `lagThreshold`, под будет создан, но HPA не начнёт добавлять дополнительные реплики сверх 1.

**offsetResetPolicy** — политика сброса offset при отсутствии committed offset для консьюмера. Влияет на начальное поведение KEDA при первом запуске: `earliest` — начать с самого начала партиции, `latest` — начать с последнего сообщения.

**Kafka Exporter** — внешний компонент (обычно `danielqsj/kafka-exporter`), который экспортирует метрики Kafka (consumer lag, partition offset, throughput) в формате Prometheus. Позволяет KEDA использовать Prometheus scaler вместо прямого подключения к Kafka.

## Теоретический блок

### Архитектура взаимодействия

KEDA Kafka Scaler поддерживает два режима работы:

**1. Прямое подключение к Kafka (Scaler type: kafka):**

```text
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Kafka      │ ◀─── │  KEDA Kafka  │ ───▶ │  KEDA        │
│   Broker     │      │  Scaler      │      │  Operator    │
└──────────────┘      └──────────────┘      └──────┬───────┘
                                                    │
                                              ┌─────▼─────┐
                                              │    HPA    │
                                              └─────┬─────┘
                                                    │
                                              ┌─────▼─────┐
                                              │  Consumer  │
                                              │  Pods      │
                                              └───────────┘
```

- Scaler подключается к Kafka через `bootstrapServers`
- Запрашивает committed offset консьюмера и high-watermark партиции
- Вычисляет lag = highwatermark - committed offset
- Направляет метрику в HPA через Metrics API Server

**2. Через Kafka Exporter + Prometheus (Scaler type: prometheus):**

```text
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Kafka      │ ◀─── │    Kafka     │ ───▶ │  Prometheus  │
│   Broker     │      │   Exporter   │      │              │
└──────────────┘      └──────────────┘      └──────┬───────┘
                                                    │
                                              ┌─────▼─────┐
                                              │  KEDA     │
                                              │  (Prom.   │
                                              │  Scaler)  │
                                              └─────┬─────┘
                                                    │
                                              ┌─────▼─────┐
                                              │    HPA    │
                                              └───────┬───┘
                                                      │
                                              ┌───────▼───┐
                                              │  Consumer  │
                                              │  Pods      │
                                              └───────────┘
```

- Kafka Exporter опрашивает Kafka и публикует метрики `kafka_consumergroup_lag`
- Prometheus скрейпирует Exporter и хранит метрику
- KEDA Prometheus Scaler запрашивает PromQL-запрос
- Преимущество: не нужно передавать credentials Kafka в KEDA, логирование, централизация метрик

### Как KEDA вычисляет количество реплик

Формула расчёта (аналогична стандартному HPA):

```text
desiredReplicas = ceil(currentReplicas × (lag / lagThreshold))
```

Пример: 2 активных реплики, lag = 500 сообщений, lagThreshold = 100:

```text
desiredReplicas = ceil(2 × (500 / 100)) = ceil(10) = 10 реплик
```

При `minReplicaCount: 0` и lag = 0:

```text
desiredReplicas = minReplicaCount = 0
```

### Влияние количества партиций

Количество партиций напрямую влияет на масштабирование:

```text
Топик: orders, партиций: 10
Consumer group: orders-worker, активных консьюмеров: 3

Максимальный параллелизм = 10 (по числу партиций)
При >10 репликах — лишние поды не получат партиции и будут простаивать
```

**Важно:** `maxReplicaCount` не должен превышать количество партиций в топике. Если партиций 10, а maxReplicaCount = 20, то 10 подов будут idle.

### Параметры Kafka Scaler

| Параметр | Обязательный | По умолчанию | Описание |
|:---|:---|:---|:---|
| `bootstrapServers` | Да | — | Список брокеров через запятую |
| `consumerGroup` | Да | — | Имя consumer group |
| `topic` | Да | — | Имя топика |
| `lagThreshold` | Нет | `100` | Порог lag для масштабирования |
| `activationLagThreshold` | Нет | `0` | Порог активации из 0 реплик |
| `offsetResetPolicy` | Нет | `latest` | Политика сброса offset (`earliest`/`latest`) |
| `limitToPartitionsWithLag` | Нет | `false` | Учитывать только партиции с lag |
| `group` | Нет | — | Потребительская группа Kafka (для auth) |

### Аутентификация

Kafka Scaler поддерживает несколько методов аутентификации:

**1. Без аутентификации (plaintext):**

```yaml
metadata:
  bootstrapServers: kafka:9092
  consumerGroup: my-group
  topic: my-topic
```

**2. SASL/PLAIN (username + password):**

```yaml
metadata:
  bootstrapServers: kafka:9092
  consumerGroup: my-group
  topic: my-topic
  saslMechanism: plain
  saslGssApiServiceName: ""
  saslGssApiKerberosConfigPath: ""
  saslGssApiKeytabPath: ""
  saslGssApiPrincipal: ""
```

Credentials передаются через TriggerAuthentication:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-credentials
  namespace: app
type: Opaque
stringData:
  sasl.username: "kafka-user"
  sasl.password: "kafka-password"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: sasl.username
      name: kafka-credentials
      key: sasl.username
    - parameter: sasl.password
      name: kafka-credentials
      key: sasl.password
```

**3. SASL/SCRAM-SHA-256/512:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-scram-credentials
  namespace: app
type: Opaque
stringData:
  sasl.username: "scram-user"
  sasl.password: "scram-password"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-scram-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: sasl.username
      name: kafka-scram-credentials
      key: sasl.username
    - parameter: sasl.password
      name: kafka-scram-credentials
      key: sasl.password
```

**4. TLS (mTLS):**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-tls
  namespace: app
type: Opaque
data:
  tls.crt: <base64-encoded-client-cert>
  tls.key: <base64-encoded-client-key>
  ca.crt: <base64-encoded-ca-cert>
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-tls-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: tls
      name: kafka-tls
      key: tls.crt
    - parameter: key
      name: kafka-tls
      key: tls.key
    - parameter: cert
      name: kafka-tls
      key: ca.crt
```

### Kafka Exporter как альтернатива прямому подключению

Если Kafka кластер находится в отдельном кластере или требует сложной аутентификации, можно использовать Kafka Exporter:

```yaml
# Установка Kafka Exporter через Helm
helm install kafka-exporter bitnami/kafka-exporter \
  --namespace monitoring \
  --set kafka.servers[0]=kafka-external:9092 \
  --set kafka.topicBlacklist=".*__consumer_offsets" \
  --set kafka.groupBlacklist=".*"
```

Основные метрики Exporter:

```text
kafka_consumergroup_lag                     # Lag по consumer group (по всем партициям)
kafka_consumergroup_lag_topic               # Lag по конкретному topic
kafka_consumergroup_current_offset          # Текущий committed offset
kafka_topic_partition_current_offset        # High-watermark партиции
kafka_topic_partition_messages             # Количество сообщений в партиции
```

## Практические сценарии

### Сценарий 1: Базовое масштабирование по Consumer Lag

Классический production-сценарий: воркер обрабатывает сообщения из Kafka, KEDA масштабирует по lag.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: kafka-consumer-deployment
  minReplicaCount: 0
  maxReplicaCount: 20
  pollingInterval: 15
  cooldownPeriod: 300
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-0.kafka:9092,kafka-1.kafka:9092,kafka-2.kafka:9092
        consumerGroup: orders-worker
        topic: orders
        lagThreshold: "500"
        activationLagThreshold: "50"
      authenticationRef:
        name: kafka-auth
```

### Сценарий 2: SASL/SCRAM аутентификация + ClusterTriggerAuthentication

Глобальная аутентификация для всех namespace:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-global-scram
  namespace: keda
type: Opaque
stringData:
  sasl.username: "prod-consumer"
  sasl.password: "super-secret-password"
---
apiVersion: keda.sh/v1alpha1
kind: ClusterTriggerAuthentication
metadata:
  name: kafka-global-scram-auth
spec:
  secretTargetRef:
    - parameter: sasl.username
      name: kafka-global-scram
      key: sasl.username
      namespace: keda
    - parameter: sasl.password
      name: kafka-global-scram
      key: sasl.password
      namespace: keda
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orders-consumer-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: orders-consumer
  minReplicaCount: 0
  maxReplicaCount: 15
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-cluster:9093
        consumerGroup: orders-processor
        topic: orders
        lagThreshold: "200"
      authenticationRef:
        name: kafka-global-scram-auth
        kind: ClusterTriggerAuthentication
```

### Сценарий 3: TLS + SASL/PLAIN

Для кластеров Kafka с включённым mTLS:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-mtls
  namespace: app
type: Opaque
data:
  tls.crt: <base64>
  tls.key: <base64>
  ca.crt: <base64>
  sasl.username: <base64>
  sasl.password: <base64>
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-mtls-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: tls
      name: kafka-mtls
      key: tls.crt
    - parameter: key
      name: kafka-mtls
      key: tls.key
    - parameter: cert
      name: kafka-mtls
      key: ca.crt
    - parameter: sasl.username
      name: kafka-mtls
      key: sasl.username
    - parameter: sasl.password
      name: kafka-mtls
      key: sasl.password
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: secure-consumer-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: consumer-deployment
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-tls:9093
        consumerGroup: secure-group
        topic: sensitive-data
        lagThreshold: "100"
        activationLagThreshold: "10"
      authenticationRef:
        name: kafka-mtls-auth
```

### Сценарий 4: Через Kafka Exporter + Prometheus

Если прямое подключение к Kafka невозможно или нежелательно:

```yaml
# Шаг 1: Kafka Exporter (Helm)
helm install kafka-exporter bitnami/kafka-exporter \
  --namespace monitoring \
  --set kafka.servers[0]=kafka.external:9092 \
  --set serviceMonitor.enabled=true

# Шаг 2: ScaledObject через Prometheus Scaler
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-lag-scaler-via-prometheus
  namespace: app
spec:
  scaleTargetRef:
    name: consumer-deployment
  minReplicaCount: 0
  maxReplicaCount: 20
  pollingInterval: 30
  cooldownPeriod: 300
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring:9090
        query: |
          sum(kafka_consumergroup_lag{
            consumergroup="orders-worker",
            topic="orders"
          })
        threshold: "500"
        activationThreshold: "50"
```

Преимущества этого подхода:
- Нет передачи credentials Kafka в KEDA
- Единый источник метрик (Prometheus)
- Доступна история lag для аналитики
- Дополнительные метрики (throughput, partition count)

### Сценарий 5: Ограничение масштабирования по числу партиций

Если топик имеет 6 партиций, а maxReplicaCount = 20, лишние поды будут idle:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: partition-aware-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: consumer-deployment
  minReplicaCount: 0
  maxReplicaCount: 6  # Не больше числа партиций!
  pollingInterval: 15
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka:9092
        consumerGroup: partition-aware-group
        topic: orders
        lagThreshold: "100"
        limitToPartitionsWithLag: "true"  # Учитывать только партиции с lag
```

### Сценарий 6: Несколько consumer groups

Масштабирование по нескольким consumer groups одновременно (логика MAX):

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: multi-group-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: shared-worker-deployment
  minReplicaCount: 0
  maxReplicaCount: 30
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka:9092
        consumerGroup: orders-processor
        topic: orders
        lagThreshold: "200"
    - type: kafka
      metadata:
        bootstrapServers: kafka:9092
        consumerGroup: notifications-processor
        topic: notifications
        lagThreshold: "100"
```

**Расчёт:** MAX(orders_replicas, notifications_replicas) — HPA выберет максимальное значение.

## Дополнительная информация

### Диагностика Kafka Scaler

```bash
# Проверка статуса ScaledObject
kubectl describe scaledobject kafka-consumer-scaler -n app
# Смотрим Status.Conditions и CurrentMetrics

# Проверка логов Kafka Scaler
kubectl logs -n keda deployment/keda-operator -f | grep -i "kafka"

# Проверка connectivity до Kafka из пода KEDA
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  kafka-broker-api-versions --bootstrap-server kafka:9092

# Проверка connectivity через kafka-console-consumer
kubectl run -it --rm kafka-debug --image= confluentinc/cp-kafka:7.5.0 --restart=Never -- \
  kafka-console-consumer --bootstrap-server kafka:9092 \
  --topic orders --from-beginning --max-messages 1

# Проверка consumer group offset
kubectl run -it --rm kafka-debug --image=confluentinc/cp-kafka:7.5.0 --restart=Never -- \
  kafka-consumer-groups --bootstrap-server kafka:9092 \
  --group orders-worker --describe
```

### Типичные проблемы

**1. Consumer lag не определяется:**

```text
Причина: consumer group не имеет committed offset (первый запуск)
Решение: убедиться что offsetResetPolicy = earliest, либо что consumer уже делал commit
```

**2. KEDA не масштабирует при растущем lag:**

```bash
# Проверка метрики через raw API
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq .

# Проверка что lag передаётся корректно
kubectl get scaledobject kafka-consumer-scaler -n app \
  -o jsonpath='{.status.currentMetrics}' | jq .
```

**3. Масштабирование вниз не происходит:**

```text
Причина: cooldownPeriod ещё не истёк
Причина: lag ниже lagThreshold, но выше activationLagThreshold
Решение: проверить cooldownPeriod и логику HPA behavior
```

**4. Лишние поды без партиций:**

```text
Причина: maxReplicaCount > количество партиций
Решение: ограничить maxReplicaCount числом партиций
```

### Связь с FinOps

Kafka lag-based scaling напрямую влияет на FinOps:

- **При lag = 0:** 0 подов (scale-to-zero), нет расходов
- **При растущем lag:** пропорциональное масштабирование, расходы растут с нагрузкой
- **При maxReplicaCount:** финансовый потолок, защита от runaway scaling

Подробнее: [KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md)

### См. также

* [KEDA: Основные концепции](./keda_concepts.md) — архитектура и компоненты
* [KEDA: Практические сценарии](./practical_scenarios.md) — другие триггеры (RabbitMQ, Prometheus, Cron)
* [KEDA: Эксплуатация](./keda-operations.md) — мониторинг и troubleshooting
* [Kafka: Мониторинг](../../../Kafka/kafka_for_monitoring.md) — метрики Kafka и Exporter
* [Паттерн Workers + Queue](../workers_queue_pattern.md) — проектирование очередей
