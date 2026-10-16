# KEDA: Практические сценарии

**Актуально для:** KEDA 2.19.x / 2.20.x, Kubernetes 1.28–1.32+

## Определения

**KEDA (Kubernetes Event-driven Autoscaling)** — событийно-ориентированный оператор Kubernetes, расширяющий функциональность Horizontal Pod Autoscaler (HPA) за счет прямого взаимодействия с брокерами очередей, базами данных, брокерами потоков и системами мониторинга без необходимости написания промежуточных экспортеров метрик.

**ScaledObject** — Custom Resource Definition (CRD), определяющий параметры автомасштабирования для постоянных рабочих нагрузок (`Deployment`, `StatefulSet`, `CustomResource`), поддерживающих подресурс `/scale`. Управляет жизненным циклом стандартного HPA и обеспечивает масштабирование в ноль ($0 \leftrightarrow 1$).

**ScaledJob** — CRD для управления пакетными задачами Kubernetes (`Job`). Запускает отдельные изолированные экземпляры `Job` под каждое поступившее событие или порцию данных из очереди, предотвращая конкуренцию воркеров за ресурсы хоста.

**TriggerAuthentication** — ресурс уровня пространства имён (Namespaced) для безопасной привязки учётных данных (секреты, mTLS-сертификаты, токены) к триггерам скейлера без раскрытия чувствительных параметров в манифесте `ScaledObject`.

**ClusterTriggerAuthentication** — кластерный ресурс (Cluster-scoped) аутентификации, позволяющий администраторам платформы централизованно задать подключение к общекластерной инфраструктуре (например, централизованный кластер Kafka или RabbitMQ) и переиспользовать его в разных пространствах имён.

**Scale-to-Zero** — режим работы, при котором рабочая нагрузка полностью останавливается (`0` реплик) при отсутствии сообщений в очереди или внешних запросов, а при появлении первого события KEDA инициирует холодный старт ($0 \to 1$).

**activationTargetValue / activationValue** — порог активации триггера. Минимальное значение метрики, необходимое для перехода рабочей нагрузки из состояния покоя (`0` реплик) в активное состояние (`1` реплика). Защищает от паразитного запуска подов при единичных тестовых событиях или служебных сообщениях.

**Scaling Modifiers** — механизм KEDA v2.20+, позволяющий применять математические формулы к числовым значениям метрик триггеров до передачи итогового значения в контроллер HPA.

**HPA Behavior** — секция тонкой настройки нативного контроллера HPA (`advanced.horizontalPodAutoscalerConfig.behavior`), определяющая политики и стабилизационные окна раздельно для масштабирования вверх (`scaleUp`) и вниз (`scaleDown`).

**KEDA HTTP Add-on** — дополнительный компонент KEDA, состоящий из перехватчика трафика (Interceptor), оператора маршрутизации и внешнего скейлера, позволяющий масштабировать HTTP-сервисы от нуля на основе входящих запросов с удержанием соединений в очереди на время холодного старта.

---

## Базовые концепции и архитектура прикладных сценариев

### Архитектура контура масштабирования в On-Premise инфраструктуре

В локальной инфраструктуре (on-premise дата-центры, bare-metal серверы или виртуализация на базе KVM) KEDA функционирует полностью автономно: все метрики извлекаются напрямую из локальных сервисов:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              On-Premise Kubernetes Cluster                             │
│                                                                                        │
│   ┌────────────────────┐     watch CRDs     ┌──────────────────────────────────────┐   │
│   │   kube-apiserver   │ ◄───────────────── │     keda-operator (Deployment, HA)   │   │
│   └─────────┬──────────┘                    │  - Scale-to-Zero (0 <-> 1)           │   │
│             │                               │  - Lifecycle HPA & ScaledJob         │   │
│             │ Aggregated API Proxy          └──────────────────┬───────────────────┘   │
│             │ (/apis/external.metrics...)                      │                       │
│             ▼                                                  │                       │
│   ┌──────────────────────────────────────┐                     │ Poll at 0 replicas    │
│   │  keda-metrics-apiserver              │                     │                       │
│   │  - External Metrics API Provider     │                     │                       │
│   └─────────────────┬────────────────────┘                     │                       │
│                     │                                          │                       │
└─────────────────────┼──────────────────────────────────────────┼───────────────────────┘
                      │ Query Metric (1 <-> N)                   │
                      ▼                                          ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │                          Локальные источники событий (On-Premise)                   │
   │                                                                                     │
   │   ┌───────────────┐   ┌────────────────┐   ┌──────────────┐   ┌─────────────────┐   │
   │   │  RabbitMQ     │   │  Apache Kafka  │   │  PostgreSQL  │   │   Prometheus    │   │
   │   │  (AMQP/HTTP)  │   │  (mTLS/SASL)   │   │  (pg_stat)   │   │   (PromQL API)  │   │
   │   └───────────────┘   └────────────────┘   └──────────────┘   └─────────────────┘   │
   └─────────────────────────────────────────────────────────────────────────────────────┘
```

### Разделение обязанностей: ScaledObject vs ScaledJob

| Критерий | `ScaledObject` | `ScaledJob` |
| :--- | :--- | :--- |
| **Целевой контроллер** | `Deployment`, `StatefulSet`, `CustomResource` | Kubernetes `Job` |
| **Тип нагрузки** | Долгоживущие воркеры, API, потоковые консьюмеры | Изолированные пакетные задачи (batch processing) |
| **Жизненный цикл** | Поды работают непрерывно, разбирая поток сообщений | Под запускается на порцию данных, завершается и удаляется |
| **Механизм масштабирования** | Управляет числом реплик через подресурс `/scale` и HPA | Создает новые объекты `Job` напрямую через `keda-operator` |
| **Реакция на ошибки** | Воркер рестартует контейнер при сбое (`RestartPolicy: Always`) | Контролируется через `backoffLimit` и DLQ на брокере |
| **Типичные сценарии** | Web-сервисы, HTTP API, консьюмеры RabbitMQ/Kafka/Redis | Рендеринг видео, расчет отчетов, тяжелый импорт БД, миграции |

### Безопасное хранение учетных данных в On-Premise среде

В production-контурах жестко запрещено указывать пароли и токены подключения в секции `metadata` скейлеров. Для On-Premise инфраструктуры стандартом является интеграция **External Secrets Operator (ESO)** с локальным хранилищем **HashiCorp Vault**:

```text
┌──────────────────┐        Sync Secret        ┌───────────────────┐     secretTargetRef     ┌────────────────────────┐
│ HashiCorp Vault  │ ────────────────────────▶ │ Kubernetes Secret │ ──────────────────────▶ │  TriggerAuthentication │
│ (On-Premise HA)  │   (External Secrets Op)   │ (Opaque, app ns)  │                         │  (KEDA CRD)            │
└──────────────────┘                           └───────────────────┘                         └───────────┬────────────┘
                                                                                                         │ authenticationRef
                                                                                                         ▼
                                                                                             ┌────────────────────────┐
                                                                                             │   ScaledObject         │
                                                                                             └────────────────────────┘
```

---

## Практические сценарии и конфигурация

### Предварительные требования

* Кластер Kubernetes версии 1.28–1.32+.
* Helm версии 3.14+.
* Локальный стек мониторинга Prometheus (Prometheus Operator / kube-prometheus-stack).
* Доступность сетевых портов до локальных источников событий (RabbitMQ 5672/15672, Kafka 9092/9093, Redis 6379, PostgreSQL 5432, Prometheus 9090).
* Установленный External Secrets Operator для синхронизации секретов из HashiCorp Vault (для production-аутентификации).

### Отказоустойчивая установка KEDA через Helm

В production-среде SRE и системные администраторы разворачивают KEDA в отказоустойчивой конфигурации с несколькими репликами оператора, ресурсами, PDB и интеграцией с Prometheus Operator.

```bash
# Добавление официального репозитория
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# Создание конфигурационного файла значений для Helm
cat <<'EOF' > keda-values.yaml
operator:
  replicaCount: 2
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 1000m
      memory: 512Mi
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchLabels:
                app.kubernetes.io/name: keda-operator
            topologyKey: kubernetes.io/hostname

metricsServer:
  replicaCount: 2
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 1000m
      memory: 512Mi

webhooks:
  replicaCount: 2

podDisruptionBudget:
  operator:
    minAvailable: 1
  metricsServer:
    minAvailable: 1
  webhooks:
    minAvailable: 1

prometheus:
  operator:
    enabled: true
    serviceMonitor:
      enabled: true
      interval: 15s

otel:
  enabled: true
  collectorUri: "otel-collector.monitoring.svc.cluster.local:4317"
  protocol: "grpc"
EOF

# Установка KEDA v2.20.0 в пространство имён keda
helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version 2.20.0 \
  -f keda-values.yaml
```

Проверка состояния установленных компонентов:

```bash
kubectl get pods -n keda -o wide
# → keda-operator-6bf968b59d-abcde        1/1     Running   0          45s
# → keda-operator-6bf968b59d-xyz12        1/1     Running   0          45s
# → keda-metrics-apiserver-7b89f-12345    1/1     Running   0          45s
# → keda-metrics-apiserver-7b89f-67890    1/1     Running   0          45s
# → keda-admission-webhooks-8c9f-aaaaa    1/1     Running   0          45s
# → keda-admission-webhooks-8c9f-bbbbb    1/1     Running   0          45s

# Проверка регистрации External Metrics API в Aggregated API Server
kubectl get apiservice v1beta1.external.metrics.k8s.io
# → NAME                            SERVICE                AVAILABLE   AGE
# → v1beta1.external.metrics.k8s.io   keda/keda-metrics-apiserver   True        1m
```

### Настройка аутентификации через External Secrets Operator (Vault)

Создание секрета подключения к RabbitMQ через HashiCorp Vault и привязка к KEDA через `TriggerAuthentication`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: rabbitmq-credentials
  namespace: processing
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: rabbitmq-credentials
    creationPolicy: Owner
  data:
    - secretKey: host
      remoteRef:
        key: production/rabbitmq
        property: amqp_connection_uri
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: rabbitmq-auth
  namespace: processing
spec:
  secretTargetRef:
    - parameter: host
      name: rabbitmq-credentials
      key: host
```

---

### Сценарий 1: Масштабирование Deployment (RabbitMQ)

Классический сценарий для фоновых обработчиков задач (workers), читающих сообщения из очереди RabbitMQ. При отсутствии задач поды выключаются до 0 (`minReplicaCount: 0`). Использование `activationValue: "3"` предотвращает холодный старт пула воркеров при прохождении единичных служебных сообщений или healthcheck-проверок.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-worker-scaler
  namespace: processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: order-processor
  minReplicaCount: 0
  maxReplicaCount: 40
  pollingInterval: 15
  cooldownPeriod: 300
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: order-tasks
        mode: QueueLength       # Поддерживаемые режимы v2.20+: QueueLength, MessageRate, DeliverGetRate
        value: "10"             # Целевое соотношение: 1 под на каждые 10 сообщений
        activationValue: "3"    # Масштабировать из 0 в 1 только при накоплении от 3 сообщений
      authenticationRef:
        name: rabbitmq-auth
```

Проверка применения и статуса масштабирования:

```bash
kubectl get scaledobject rabbitmq-worker-scaler -n processing
# → NAME                     SCALETARGETKIND      SCALETARGETNAME   MIN   MAX   TRIGGERS   AUTHENTICATION   READY   ACTIVE   AGE
# → rabbitmq-worker-scaler   apps/v1.Deployment   order-processor   0     40    rabbitmq   rabbitmq-auth    True    False    2m

# Инспекция автоматически созданного ресурса HPA
kubectl get hpa keda-hpa-rabbitmq-worker-scaler -n processing
# → NAME                               REFERENCE                    TARGETS       MINPODS   MAXPODS   REPLICAS   AGE
# → keda-hpa-rabbitmq-worker-scaler   Deployment/order-processor   0/10 (avg)    1         40        0          2m
```

> **Важно по синтаксису KEDA v2.20+:** Параметр `queueLength` объявлен устаревшим в пользу связки `mode: QueueLength` и `value`. Режимы `MessageRate` (темп публикации), `DeliverGetRate` (темп потребления) и `PublishedToDeliveredRatio` требуют протокола `http` (обращение к RabbitMQ Management HTTP API, порт 15672).

---

### Сценарий 2: Масштабирование пакетных задач (ScaledJob на базе On-Premise RabbitMQ)

Используется для тяжелых изолированных задач (например, перекодирование медиафайлов, генерация PDF-отчетов, пакетный импорт), где запуск одного пода соответствует обработке строго одной порции данных. `ScaledJob` исключает конкуренцию воркеров за процессорные ядра на нодах и освобождает память сразу после завершения шага.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: video-transcoder-job
  namespace: processing
spec:
  jobTargetRef:
    parallelism: 1
    completions: 1
    activeDeadlineSeconds: 1800
    backoffLimit: 3
    template:
      spec:
        restartPolicy: OnFailure
        containers:
          - name: transcoder
            image: internal-registry.corp.local/media/transcoder:v1.8.4
            resources:
              requests:
                cpu: "2"
                memory: "4Gi"
              limits:
                cpu: "4"
                memory: "8Gi"
            env:
              - name: QUEUE_NAME
                value: "transcode-jobs"
  pollingInterval: 20
  maxReplicaCount: 30
  successfulJobsHistoryLimit: 5
  failedJobsHistoryLimit: 10
  scalingStrategy:
    strategy: "default"
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: transcode-jobs
        mode: QueueLength
        value: "1"              # Ровно 1 Job на каждое новое сообщение в очереди
      authenticationRef:
        name: rabbitmq-auth
```

Проверка выполнения пакетных задач:

```bash
kubectl get scaledjob video-transcoder-job -n processing
# → NAME                   SCALETARGETKIND   SCALETARGETNAME   TRIGGERS   AUTHENTICATION   READY   ACTIVE   AGE
# → video-transcoder-job   batch/v1.Job      video-transcoder  rabbitmq   rabbitmq-auth    True    True     5m

kubectl get jobs -n processing -l kedacore.io/scaledjob-name=video-transcoder-job
# → NAME                            COMPLETIONS   DURATION   AGE
# → video-transcoder-job-7x9qk      1/1           4m12s      8m
# → video-transcoder-job-9z2lp      0/1           1m30s      1m30s
```

---

### Сценарий 3: Глобальная аутентификация (ClusterTriggerAuthentication для Apache Kafka)

Позволяет системным администраторам платформы настроить безопасный доступ к единому общекластерному брокеру Apache Kafka (SASL/SCRAM или mTLS) один раз на уровне кластера, предоставляя разработчикам возможность масштабировать воркеры в любых пространствах имён без дублирования секретов.

Секрет и кластерный ресурс аутентификации в системном пространстве имён `keda`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-platform-secret
  namespace: keda
type: Opaque
stringData:
  sasl: |
    username=keda-autoscaler
    password=SuperSecureClusterPassword987!
    algorithm=scram-sha-512
  tls: "enable"
---
apiVersion: keda.sh/v1alpha1
kind: ClusterTriggerAuthentication
metadata:
  name: global-kafka-auth
spec:
  secretTargetRef:
    - parameter: sasl
      name: kafka-platform-secret
      namespace: keda
      key: sasl
    - parameter: tls
      name: kafka-platform-secret
      namespace: keda
      key: tls
```

Использование в прикладном `ScaledObject` внутри пространства имён `telemetry`:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: telemetry-consumer-scaler
  namespace: telemetry
spec:
  scaleTargetRef:
    name: telemetry-consumer
  minReplicaCount: 1
  maxReplicaCount: 64
  pollingInterval: 15
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-brokers.infra.svc.cluster.local:9092
        consumerGroup: telemetry-ingest-group
        topic: device-telemetry-raw
        lagThreshold: "250"     # Добавлять 1 реплику на каждые 250 сообщений суммарного лага
        offsetResetPolicy: latest
      authenticationRef:
        name: global-kafka-auth
        kind: ClusterTriggerAuthentication   # Обязательное указание вида ресурса
```

---

### Сценарий 4: Применение модификаторов метрик (Scaling Modifiers, KEDA v2.20+)

Механизм `scalingModifiers` позволяет преобразовывать «сырые» метрики мониторинга с помощью математических формул до их передачи в алгоритм HPA. Это полезно для создания агрессивного коэффициента ускорения на старте пиковых нагрузок или для компенсации задержек обработки.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: modified-prometheus-scaler
  namespace: payments
spec:
  scaleTargetRef:
    name: payment-gateway
  minReplicaCount: 2
  maxReplicaCount: 50
  pollingInterval: 15
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-k8s.monitoring.svc.cluster.local:9090
        threshold: "100"
        query: sum(rate(payment_requests_total{status="incoming"}[1m]))
        metricName: payment_requests_raw
  # Математическое масштабирование: умножение метрики на коэффициент 1.4 для опережающего развертывания
  scalingModifiers:
    formula: "metricValue * 1.4"
    targetMetricName: "boosted_payment_requests"
```

---

### Сценарий 5: Смешанное масштабирование (Prometheus + Cron)

Объединение динамического масштабирования по реальной нагрузке (RPS из Prometheus) с гарантированным резервом ресурсов в рабочие часы через триггер `cron`.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: hybrid-api-scaler
  namespace: backend
spec:
  scaleTargetRef:
    name: core-api
  minReplicaCount: 1
  maxReplicaCount: 30
  cooldownPeriod: 300
  triggers:
    # Триггер 1: Динамическая нагрузка по RPS
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-k8s.monitoring.svc.cluster.local:9090
        threshold: "50"
        query: sum(rate(http_requests_total{service="core-api"}[2m]))
    # Триггер 2: Гарантированный пул реплик в рабочее время (пн-пт, 08:30 - 20:00 МСК)
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: "30 8 * * 1-5"
        end: "0 20 * * 1-5"
        desiredReplicas: "8"    # В рабочие часы держим минимум 8 реплик независимо от RPS
```

> **Принцип работы множественных триггеров:** Контроллер HPA рассчитывает целевое число реплик для каждого триггера независимо и всегда выбирает **максимальное значение** (`MAX(desiredReplicas)`). Если в рабочее время RPS требует 14 подов — поднимется 14. Если нагрузка падает до нуля, сработает cron-триггер и удержит 8 подов. Ночью оба триггера позволят сжаться до `minReplicaCount: 1`.

---

### Сценарий 6: Масштабирование HTTP-сервисов до нуля (KEDA HTTP Add-on)

Установка KEDA HTTP Add-on в локальный кластер:

```bash
helm install http-add-on kedacore/keda-http-add-on \
  --namespace keda \
  --version 0.16.0
```

Актуальный API (v0.15+) использует ресурс `InterceptorRoute` (v1beta1), разделяющий маршрутизацию и логику масштабирования.

Конфигурация масштабирования внутреннего HTTP-сервиса:

```yaml
apiVersion: http.keda.sh/v1beta1
kind: InterceptorRoute
metadata:
  name: report-generator-route
  namespace: services
spec:
  host: "reports.internal.corp.local"
  target:
    service: report-generator-svc
    port: 8080
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: report-generator-scaler
  namespace: services
spec:
  scaleTargetRef:
    name: report-generator-deployment
  minReplicaCount: 0
  maxReplicaCount: 15
  cooldownPeriod: 180
  triggers:
    - type: external-push
      metadata:
        scalerAddress: keda-http-add-on-interceptor.keda.svc.cluster.local:9090
        hosts: "reports.internal.corp.local"
        targetPendingRequests: "50"
```

*(Для кластеров, использующих традиционный манифест `HTTPScaledObject` v1alpha1):*

```yaml
apiVersion: http.keda.sh/v1alpha1
kind: HTTPScaledObject
metadata:
  name: legacy-http-scaler
  namespace: services
spec:
  hosts:
    - "reports.internal.corp.local"
  scaleTargetRef:
    name: report-generator-deployment
    service: report-generator-svc
    port: 8080
  replicas:
    min: 0
    max: 15
  scalingMetric:
    concurrency:
      targetValue: 50
  scaledownPeriod: 180
```

#### Чеклист надежности HTTP Add-on для SRE

1. **Время холодного старта (Cold Start):**
   * Измерить задержку от поступления первого HTTP-запроса до перехода первого пода в `Ready`.
   * Убедиться, что время холодного старта не превышает client timeout (например, таймаут шлюза Nginx Ingress).
2. **Сквозная цепочка таймаутов:**
   * `Client Timeout` $\ge$ `Ingress proxy_read_timeout` $\ge$ `KEDA Interceptor Timeout` $\ge$ `Pod Handler Timeout`.
3. **Readiness Probe:**
   * Не устанавливать избыточный `initialDelaySeconds`. Настроить `startupProbe` с частыми интервалами (`periodSeconds: 1`, `failureThreshold: 30`) для быстрой фиксации готовности.
4. **План экстренного вывода из Scale-to-Zero:**

```bash
# Принудительная фиксация минимума в 2 реплики при аварии Interceptor
kubectl patch scaledobject report-generator-scaler -n services \
  --type='json' -p='[{"op": "replace", "path": "/spec/minReplicaCount", "value": 2}]'
```

---

### Сценарий 7: Масштабирование на основе ресурсов Kubernetes (ConfigMap)

Применяется, когда локальная внутренняя система оркестрации или пакетный шедулер периодически фиксирует агрегированную нагрузку или число задач в `ConfigMap` кластера.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: configmap-batch-scaler
  namespace: batch-system
spec:
  scaleTargetRef:
    name: batch-executor
  minReplicaCount: 0
  maxReplicaCount: 20
  pollingInterval: 10
  cooldownPeriod: 120
  triggers:
    - type: kubernetes-resource
      metadata:
        resourceKind: "ConfigMap"
        resourceName: "batch-cluster-status"
        key: "unprocessed_chunks_count"
        format: "number"
        targetValue: "50"
        activationTargetValue: "1"
```

---

### Сценарий 8: Выключение тестовых сред и управление графиком работы (Cron)

Замена нестабильных bash-скриптов и внешних cron-задач на декларативное управление в GitOps. Сервис в dev/staging или офисный B2B API активен в рабочие часы и полностью выключается в ночное время и выходные.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: staging-env-scheduler
  namespace: staging
spec:
  scaleTargetRef:
    name: staging-backend-api
  minReplicaCount: 0
  maxReplicaCount: 4
  cooldownPeriod: 300
  triggers:
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: "45 8 * * 1-5"   # 08:45 Пн-Пт: плавный прогрев сред перед приходом разработчиков
        end: "30 19 * * 1-5"    # 19:30 Пн-Пт: окончание рабочего дня
        desiredReplicas: "2"
```

#### Сравнение подходов: Bash-скрипты vs KEDA Cron

| Критерий | Традиционные Bash-скрипты / Cron | KEDA Cron Scaler |
| :--- | :--- | :--- |
| **Хранение конфигурации** | На серверах шедулеров, в Jenkins/Gitlab jobs | Декларативно в GitOps-репозитории проекта |
| **Наблюдаемость (Observability)** | Логи bash, отсутствие метрик в Prometheus | Kubernetes Events, Prometheus-метрики KEDA |
| **Отказоустойчивость** | Падение хоста скрипта ломает график | Контроллер KEDA работает в HA-режиме внутри кластера |
| **Взаимодействие с HPA** | Конфликтует с HPA, переписывая `spec.replicas` | Гармонично интегрируется с HPA через подресурс `/scale` |

---

### Сценарий 9: Масштабирование по метрикам Prometheus (PromQL)

Масштабирование API-сервисов по метрикам входящего сетевого трафика, latency или длины внутренних очередей, собираемых Prometheus.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: api-prometheus-scaler
  namespace: production
spec:
  scaleTargetRef:
    name: core-gateway
  minReplicaCount: 3
  maxReplicaCount: 50
  pollingInterval: 15
  cooldownPeriod: 300
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-k8s.monitoring.svc.cluster.local:9090
        metricName: http_requests_per_second
        query: sum(rate(nginx_ingress_controller_requests{ingress="core-gateway-ingress"}[2m]))
        threshold: "150"        # 1 под на каждые 150 RPS
        activationThreshold: "10"
```

#### Обязательные требования к запросам PromQL в KEDA

1. **Строго один скалярный результат:** Запрос `query` обязан возвращать либо `scalar`, либо `vector` ровно с одним элементом. Если запрос возвращает множественные серии (например, по одной на инстанс), KEDA завершится ошибкой скейлера. Всегда используйте агрегации `sum()`, `avg()`, `max()`.
2. **Выбор временного окна `rate()`:** Окно `[2m]` обеспечивает быструю реакцию на пики. Окно `[5m]` обеспечивает сглаженную характеристику и предотвращает лишние колебания.
3. **Примеры других типовых On-Premise метрик:**

```yaml
# 1. По задержке ответов (Latency p95)
query: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{app="core-gateway"}[5m])) by (le))
threshold: "0.4"   # 400 мс целевой порог на p95

# 2. По числу активных соединений на локальном HAProxy / Nginx
query: sum(haproxy_backend_current_sessions{proxy="backend_api"})
threshold: "500"

# 3. По объему необработанных задач в Redis
query: redis_connected_clients{service="redis-master"}
threshold: "200"
```

---

### Сценарий 10: Тонкая настройка поведения масштабирования (HPA Behavior)

Оптимальная эксплуатационная модель автоскейлинга асимметрична: мгновенный агрессивный рост при всплеске нагрузки (защита SLA сервиса) и плавное ступенчатое сжатие при спаде (защита от осцилляции и лишних холодных стартов).

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: hardened-behavior-scaler
  namespace: production
spec:
  scaleTargetRef:
    name: transaction-processor
  minReplicaCount: 2
  maxReplicaCount: 40
  cooldownPeriod: 300           # Управляет исключительно переходом 1 -> 0
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300   # Окно оценки в 5 минут для фильтрации провалов нагрузки
          policies:
            - type: Percent
              value: 25                     # Сжимать максимум на 25% объема...
              periodSeconds: 60             # ...за одну минуту
            - type: Pods
              value: 2                      # ...или максимум на 2 пода
              periodSeconds: 60
          selectPolicy: Min                 # Выбирать наиболее осторожное ограничение
        scaleUp:
          stabilizationWindowSeconds: 0     # Мгновенная реакция без стабилизационного ожидания
          policies:
            - type: Percent
              value: 100                    # Удваивать пул воркеров...
              periodSeconds: 15             # ...каждые 15 секунд
            - type: Pods
              value: 4                      # ...или добавлять по 4 пода
              periodSeconds: 15
          selectPolicy: Max                 # Выбирать наиболее агрессивный рост
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: transactions
        mode: QueueLength
        value: "20"
      authenticationRef:
        name: rabbitmq-auth
```

---

### Сценарий 11: Масштабирование StatefulSet (Read-Replicas PostgreSQL)

KEDA поддерживает управление ресурсами `StatefulSet` через подресурс `/scale`. Типичный сценарий системного администрирования: динамическое масштабирование read-реплик PostgreSQL в зависимости от нагрузки на чтение.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: postgres-replica-scaler
  namespace: databases
spec:
  scaleTargetRef:
    kind: StatefulSet
    name: postgres-replica
  minReplicaCount: 1      # КАТЕГОРИЧЕСКИ НЕЛЬЗЯ 0: холодный старт реплики СУБД занимает минуты
  maxReplicaCount: 6
  cooldownPeriod: 600     # Длинный cooldown для исключения частых переподключений пулов PgBouncer
  pollingInterval: 20
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-k8s.monitoring.svc.cluster.local:9090
        query: sum(pg_stat_activity_count{state="active", datname="appdb"})
        threshold: "40"   # 40 активных запросов на одну реплику
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: "0 8 * * 1-5"
        end: "0 21 * * 1-5"
        desiredReplicas: "2"
```

#### Защитные ограничения при масштабировании StatefulSet

1. **Гарантия минимального пула (`minReplicaCount: 1`):** Запуск нового пода реплики PostgreSQL требует развертывания PVC, репликации WAL-логов и прохождения точки консистентности. Масштабирование в ноль разрушает read-доступность.
2. **Обязательный PodDisruptionBudget:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgres-replica-pdb
  namespace: databases
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: postgres-replica
```

3. **Согласование с Patroni:** Если СУБД управляется Patroni, масштабирование узлов с кворумом (DCS etcd/Consul) через KEDA **запрещено**. KEDA допускает масштабирование только пула асинхронных read-only реплик (`pg_is_in_recovery() = true`), не участвующих в кворуме лидеров.

---

### Сценарий 12: Масштабирование воркеров по очередям в PostgreSQL (PostgreSQL Scaler)

Частый сценарий в On-Premise корпоративных системах: фоновые задачи хранятся в реляционной таблице PostgreSQL (`job_queue`), где воркеры выбирают записи конструкцией `SELECT ... FOR UPDATE SKIP LOCKED`.

Секрет подключения:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: pg-queue-auth
  namespace: backend
type: Opaque
stringData:
  connection: "postgresql://queue_reader:SecureDbPass123@pgbouncer.databases.svc.cluster.local:6432/appdb?sslmode=disable"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: pg-queue-trigger-auth
  namespace: backend
spec:
  secretTargetRef:
    - parameter: connection
      name: pg-queue-auth
      key: connection
```

Манифест `ScaledObject`:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: db-queue-worker-scaler
  namespace: backend
spec:
  scaleTargetRef:
    name: db-queue-worker
  minReplicaCount: 0
  maxReplicaCount: 20
  pollingInterval: 15
  cooldownPeriod: 180
  triggers:
    - type: postgresql
      metadata:
        query: "SELECT count(*) FROM background_tasks WHERE status = 'pending';"
        targetQueryValue: "25"              # 1 под на каждые 25 необработанных задач в таблице
        activationTargetQueryValue: "1"     # Поднимать 1 под при появлении хотя бы одной задачи
        dbName: "appdb"
      authenticationRef:
        name: pg-queue-trigger-auth
```

> **Рекомендация SRE:** Подключайте KEDA PostgreSQL scaler к пулу соединений **PgBouncer** (в режиме session или transaction pooling), а не напрямую к мастер-инстансу PostgreSQL, чтобы опрос KEDA каждые 15 секунд не приводил к исчерпанию лимита `max_connections`.

---

### Сценарий 13: Масштабирование Celery / Redis воркеров по длине списка

Масштабирование воркеров Python Celery, использующих локальный Redis в качестве брокера очередей.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-credentials
  namespace: workers
type: Opaque
stringData:
  address: "redis-master.cache.svc.cluster.local:6379"
  password: "MasterRedisAuthPassword!"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-trigger-auth
  namespace: workers
spec:
  secretTargetRef:
    - parameter: address
      name: redis-credentials
      key: address
    - parameter: password
      name: redis-credentials
      key: password
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: celery-worker-scaler
  namespace: workers
spec:
  scaleTargetRef:
    name: celery-task-worker
  minReplicaCount: 0
  maxReplicaCount: 30
  pollingInterval: 15
  cooldownPeriod: 240
  triggers:
    - type: redis
      metadata:
        listName: celery        # Имя ключа списка очереди Celery в Redis
        listLength: "15"        # 1 под на каждые 15 задач в очереди
        activationListLength: "1"
        databaseIndex: "0"
      authenticationRef:
        name: redis-trigger-auth
```

---

## Операции и команды

Практические команды системного администрирования и эксплуатации KEDA в Kubernetes:

| Операция | Команда | Назначение и ожидаемый результат |
| :--- | :--- | :--- |
| **Список всех ScaledObject** | `kubectl get scaledobject -A` | Обзор состояния всех объектов масштабирования во всех пространствах имён |
| **Детальная инспекция статуса** | `kubectl describe scaledobject <name> -n <ns>` | Анализ условий `Ready`, `Active`, ошибок аутентификации и истории событий |
| **Инспекция ScaledJob** | `kubectl get scaledjob -A` | Проверка запущенных и завершенных пакетных задач под управлением KEDA |
| **Проверка внешних метрик KEDA** | `kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" \| jq .` | Подтверждение отдачи числовых значений в External Metrics API |
| **Просмотр связанного HPA** | `kubectl get hpa keda-hpa-<name> -n <ns>` | Проверка целевых и текущих метрик HPA, управляемого KEDA |
| **Заморозка (Пауза) автоскейлинга** | `kubectl annotate scaledobject <name> autoscaling.keda.sh/paused="true" -n <ns>` | Фиксация текущего числа реплик на время регламентных работ на брокере |
| **Возобновление автоскейлинга** | `kubectl annotate scaledobject <name> autoscaling.keda.sh/paused- -n <ns>` | Снятие блокировки и возврат к штатному автоматическому масштабированию |
| **Логи KEDA Operator** | `kubectl logs -n keda -l app.kubernetes.io/name=keda-operator -f --tail=100` | Отслеживание цикла обнаружения триггеров и взаимодействия с API |
| **Логи Metrics Server** | `kubectl logs -n keda -l app.kubernetes.io/name=keda-metrics-apiserver -f --tail=100` | Диагностика сетевых ошибок обращения к источникам метрик |

### Примеры выполнения ключевых команд

Инспекция состояния `ScaledObject`:

```bash
kubectl describe scaledobject rabbitmq-worker-scaler -n processing
# → Name:         rabbitmq-worker-scaler
# → Namespace:    processing
# → Status:
# →   Conditions:
# →     Type           Status  Reason
# →     ----           ------  ------
# →     Ready          True    ScaledObjectReady
# →     Active         True    ScaledObjectActive
# →     Fallback       False   FallbackPolicyInactive
# →   External Metric Names:
# →     s0-rabbitmq-order-tasks
# →   Health:
# →     s0-rabbitmq-order-tasks:
# →       Number Of Failures:  0
# →       Status:              Happy
# → Events:
# →   Type    Reason                   Age   From           Message
# →   ----    ------                   ----  ----           -------
# →   Normal  KEDAScalersStarted       5m    keda-operator  Started scalers watch
# →   Normal  ScaledObjectReady        5m    keda-operator  ScaledObject is ready for scaling
```

Оперативная заморозка автомасштабирования во время обслуживания брокера сообщений:

```bash
# Включение паузы
kubectl annotate scaledobject rabbitmq-worker-scaler -n processing autoscaling.keda.sh/paused="true" --overwrite
# → scaledobject.keda.sh/rabbitmq-worker-scaler annotated

# Проверка заморозки: в describe появится статус Paused
kubectl describe scaledobject rabbitmq-worker-scaler -n processing | grep -i paused
# → Reason:  ScaledObjectPaused

# Снятие паузы после завершения работ
kubectl annotate scaledobject rabbitmq-worker-scaler -n processing autoscaling.keda.sh/paused-
# → scaledobject.keda.sh/rabbitmq-worker-scaler annotated
```

---

## Диагностика и устранение неполадок

### 1. Ошибка `ScaledObject TargetNotFound`

* **Симптомы:** В `kubectl describe scaledobject` отображается условие `Ready: False`, причина `TargetNotFound`. Поды не масштабируются.
* **Причина:** Неверно указано имя ресурса в `scaleTargetRef.name`, указан ошибочный `kind` или целевой `Deployment` находится в другом пространстве имён.
* **Диагностика:**

```bash
kubectl get deployment -n <namespace>
kubectl get scaledobject <name> -n <namespace> -o jsonpath='{.spec.scaleTargetRef}'
```

* **Решение:** Исправить манифест `ScaledObject`, приведя `scaleTargetRef.name` в точное соответствие с именем существующего ресурса в том же namespace.

### 2. Сбой `FailedGetExternalMetric` в событиях HPA

* **Симптомы:** HPA переходит в состояние `ScalingActive: False` с сообщением `unable to get external metric: unable to fetch metrics from external metrics API`.
* **Причина:**
  1. `keda-metrics-apiserver` не имеет сетевого доступа к брокеру (NetworkPolicy блокирует трафик из namespace `keda`).
  2. Неверные учетные данные в `TriggerAuthentication` / истек пароль.
  3. Неверно указано имя очереди или топика в источнике.
* **Диагностика:**

```bash
# Проверка логов Metrics Server на предмет таймаутов или HTTP/Auth ошибок
kubectl logs -n keda -l app.kubernetes.io/name=keda-metrics-apiserver --tail=200 | grep -i error

# Проверка сетевой связности из пода KEDA до источника
kubectl exec -n keda -it deploy/keda-metrics-apiserver -- nc -zv rabbitmq.infra.svc.cluster.local 5672
```

* **Решение:** Добавить разрешающую `NetworkPolicy` между namespace `keda` и namespace брокера; проверить актуальность секрета в Vault/ESO.

### 3. Конфликт двойного HPA (`Deployment is already managed by another autoscaler`)

* **Симптомы:** KEDA Operator пишет в логах предупреждение о невозможности управлять объектом, число реплик хаотично меняется.
* **Причина:** Для целевого `Deployment` уже существует ручной манифест `HorizontalPodAutoscaler` (например, настроенный на CPU/Memory). KEDA создает свой собственный HPA с именем `keda-hpa-{scaledobject-name}`, что приводит к конфликту двух контроллеров за подресурс `/scale`.
* **Решение:** Удалить старый ручной HPA. Если требуется масштабирование одновременно по CPU/Memory и событиям KEDA, добавьте триггеры `cpu` и `memory` непосредственно внутрь спецификации `ScaledObject.spec.triggers`.

### 4. Зависание и утечка ресурсов в `ScaledJob` (Poison Message)

* **Симптомы:** KEDA непрерывно создает новые `Job` вплоть до достижения `maxReplicaCount`. Все ноды кластера исчерпывают лимиты CPU/RAM.
* **Причина:** В очередь попало битое («ядовитое») сообщение. Каждый запускаемый `Job` читает его, аварийно завершается (`CrashLoopBackOff`), сообщение возвращается в очередь и KEDA инициирует запуск следующего Job.
* **Решение:**
  1. Настроить в брокере (RabbitMQ/Kafka) очередь недоставленных сообщений (**Dead Letter Queue / DLQ**) с ограничением максимального числа повторов (max-delivery-attempts $\le$ 3).
  2. Ограничить время жизни и очистку в манифесте `ScaledJob`: выставить `activeDeadlineSeconds: 1800` и `failedJobsHistoryLimit: 5`.

### 5. Осцилляция реплик (Flapping)

* **Симптомы:** Количество воркеров резко увеличивается (например, до 30 подов), через 2 минуты падает до 0, затем снова подскакивает до 30.
* **Причина:** Отсутствует окно стабилизации HPA, `cooldownPeriod` слишком короткий (< 60 сек), или порог `value` триггера ниже объема пачки, считываемой одним воркером за цикл.
* **Решение:**
  * Увеличить `cooldownPeriod` минимум до 300 секунд.
  * Настроить `behavior.scaleDown.stabilizationWindowSeconds: 300`.
  * Убедиться, что параметр `value` превышает размер единичной пачки сообщений (batch size / prefetch count воркера).

---

## Лучшие практики

1. **Гарантированный PodDisruptionBudget (PDB):**
   Всегда объявляйте PDB для рабочих нагрузок, управляемых KEDA. Это предотвращает одновременное удаление всех воркеров при эвакуации нод (Node Drain) системными администраторами при обновлении ядра или Kubernetes.
2. **Лимиты ResourceQuota для ScaledJob:**
   В каждом пространстве имён с `ScaledJob` обязательна настройка `ResourceQuota`. При массовом сбросе сотен тысяч сообщений в очередь KEDA не сможет создать подов больше, чем выделено квотой, что защитит критические сервисы кластера от дефицита ресурсов.
3. **Безопасное время завершения (Graceful Termination):**
   Для воркеров очередей устанавливайте адекватный `terminationGracePeriodSeconds` (например, 60–120 секунд). В коде приложения перехватывайте сигнал `SIGTERM`, прекращайте прием новых сообщений из очереди и дорабатывайте текущее в обработке сообщение до отправки `ACK`.
4. **Исключение `spec.replicas` из Git при работе с GitOps (Argo CD / Flux):**
   При управлении кластером через Argo CD или Flux обязательно удаляйте строку `spec.replicas` из манифеста `Deployment` в Git. Дополнительно добавьте `ignoreDifferences` для пути `/spec/replicas`, чтобы GitOps-контроллер не вступал в конфликт с KEDA:

```yaml
# Пример настройки в Argo CD Application
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
```

5. **Очистка ресурсов при удалении ScaledObject:**
   Используйте поле `advanced.restoreToOriginalReplicaCount: true`, если при удалении `ScaledObject` требуется вернуть `Deployment` к фиксированному числу реплик, а не оставлять в последнем динамическом состоянии.

---

## Дополнительная информация

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектурные основы, устройство оператора, Metrics Server, полный глоссарий и спецификация полей CRD
* **[KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md)** — глубокая эксплуатация, Prometheus-алерты, runbooks и диагностика сбоев платформы
* **[KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md)** — расчет финансового эффекта scale-to-zero, лимиты емкости и оптимизация стоимости
* **[KEDA: Тестирование и валидация](./keda-testing-validation.md)** — chaos-тестирование, синтетические smoke-тесты и валидация холодного старта
* **[KEDA: Вопросы для собеседования](./keda-interview-questions.md)** — типовые сценарии и вопросы для проверки компетенций SRE/DevOps
* **[KEDA + Kafka](./kafka-keda-scaler.md)** — детальная настройка скейлера Apache Kafka по consumer group lag
* **[KEDA + Redis](./redis-keda-scaler.md)** — масштабирование по спискам и потокам (Streams) Redis
* **[Паттерн Workers + Queue](../workers_queue_pattern.md)** — проектирование очередей и архитектура масштабируемых воркеров
* **[GitOps для Autoscaling](../gitops_autoscaling.md)** — устранение конфликтов HPA/KEDA с Argo CD и Flux
* **[StatefulSet Autoscaling](../statefulset_autoscaling.md)** — специфика автомасштабирования stateful-приложений в Kubernetes
* **[HPA: Практические сценарии](../HPA/hpa_scenarios.md)** — нативное горизонтальное масштабирование по ресурсам CPU/Memory
