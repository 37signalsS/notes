# KEDA: Основные концепции

**Актуально для:** KEDA 2.19.x / 2.20.x, Kubernetes 1.28–1.32+

## Определения

**KEDA (Kubernetes Event-driven Autoscaling)** — открытый оператор Kubernetes для автоматического масштабирования рабочих нагрузок на основе событий из внешних и внутренних источников. Дополняет стандартный Horizontal Pod Autoscaler (HPA), обеспечивая реакцию на бизнес-метрики (размер очередей, latency, таймеры, значения в БД), масштабирование до нуля (`0 ↔ 1`) и трансляцию внешних метрик через собственный Metrics API Server (`external.metrics.k8s.io`).

**ScaledObject** — Custom Resource Definition (CRD), определяющий параметры автомасштабирования для постоянных рабочих нагрузок: `Deployment`, `StatefulSet` или любого ресурса с поддержкой подресурса `/scale`. Задаёт границы репликации (`minReplicaCount`, `maxReplicaCount`), интервалы проверки, fallback-политики и перечень триггеров.

**ScaledJob** — CRD для управления пакетными задачами Kubernetes (`Job`). Вместо изменения числа подов в рамках одного контроллера, KEDA запускает отдельные независимые `Job` на каждое поступившее событие или порцию данных. Применяется для длительных, изолированных задач, где один запуск обрабатывает строго ограниченную порцию данных.

**Scaler (Скейлер)** — адаптер внутри KEDA, реализующий логику подключения к конкретной системе (RabbitMQ, Apache Kafka, Redis, PostgreSQL, Prometheus и др.). Скейлер считывает метрики с источника и возвращает числовые значения, на основании которых рассчитывается целевое количество реплик.

**Trigger (Триггер)** — описание источника данных внутри спецификации `ScaledObject` или `ScaledJob`. Включает имя скейлера, параметры подключения, пороговые значения (`threshold`), а также пороги активации.

**TriggerAuthentication** — ресурс уровня пространства имён (Namespaced) для безопасного хранения параметров аутентификации (секреты, mTLS-сертификаты, токены), используемых скейлерами. Позволяет отделить учётные данные от прикладного манифеста масштабирования.

**ClusterTriggerAuthentication** — кластерный ресурс (Cluster-scoped) аутентификации, доступный для повторного использования несколькими `ScaledObject` в разных пространствах имён администраторами платформы.

**Scale-to-Zero** — режим работы, при котором рабочая нагрузка полностью останавливается (`0` реплик) при отсутствии сообщений в очереди или внешних запросов, а при появлении первого события KEDA инициирует холодный старт (`0 → 1`).

**activationThreshold** — порог активации триггера. Минимальное значение метрики, необходимое для перехода рабочей нагрузки из состояния покоя (`0` реплик) в активное состояние (`1` реплика). Предотвращает ложный запуск подов при незначительных флуктуациях или единичных тестовых событиях.

**idleReplicaCount** — количество реплик, удерживаемое при неактивных триггерах (значение по умолчанию — 0). При превышении `activationThreshold` KEDA немедленно разворачивает поды до `minReplicaCount` для быстрого прогрева пула воркеров, а при спаде возвращает к `idleReplicaCount`. Из-за специфики взаимодействия с HPA поддерживаемым значением является 0.

**pollingInterval** — интервал (в секундах), с которым оператор KEDA опрашивает источники метрик в режиме покоя (при 0 реплик). При наличии 1 и более реплик опрос координируется циклом синхронизации HPA.

**cooldownPeriod** — период охлаждения (в секундах) после исчезновения нагрузки, в течение которого сохраняется `minReplicaCount` перед окончательным уменьшением числа подов до нуля.

**initialCooldownPeriod** — период задержки (в секундах) после создания `ScaledObject`, во время которого KEDA не инициирует scale-to-zero, предоставляя подам время на первоначальную инициализацию и прогрев кэшей.

**Fallback** — аварийный механизм удержания реплик. При сбое опроса источника метрик (сетевой сбой, недоступность БД) KEDA переводит воркеры в резервное состояние с фиксированным числом реплик, предотвращая ложное обнуление подов.

**Scaling Modifiers** — механизм KEDA v2.20+, позволяющий выполнять математические преобразования над метриками триггеров (формулы с весами, деление, округление) перед отправкой итогового значения в HPA.

**Pausing (Приостановка)** — режим временного отключения автоматического масштабирования конкретного `ScaledObject` через аннотацию `autoscaling.keda.sh/paused: "true"` для проведения технических работ на брокере или обновлений сервиса.

### Значения по умолчанию в спецификации ScaledObject

Согласно спецификации KEDA v2.20:

| Параметр | Значение по умолчанию | Назначение и поведение |
| :--- | :--- | :--- |
| `pollingInterval` | `30` сек | Периодичность опроса внешних скейлеров оператором (при 0 реплик) |
| `cooldownPeriod` | `300` сек | Время ожидания перед масштабированием $1 \to 0$ после исчезновения нагрузки |
| `initialCooldownPeriod` | `0` сек | Задержка запуска таймера охлаждения после первого создания манифеста |
| `minReplicaCount` | `0` | Нижняя граница репликации (по умолчанию включён scale-to-zero) |
| `maxReplicaCount` | `100` | Верхняя защитная граница репликации, передаваемая в HPA |
| `idleReplicaCount` | `0` (или игнорируется) | Целевое число подов в полном простое |
| `fallback.failureThreshold` | `3` | Число последовательных ошибок скейлера до перехода в fallback |
| `fallback.replicas` | `minReplicaCount` | Целевое количество подов в режиме fallback |
| `fallback.behavior` | `static` | Стратегия fallback (`static`, `currentReplicas`, `currentReplicasIfHigher`, `currentReplicasIfLower`) |
| Имя создаваемого HPA | `keda-hpa-{scaledobject-name}` | Автоматически генерируемый ресурс HorizontalPodAutoscaler |

Дополнительные системные поля:
* `advanced.restoreToOriginalReplicaCount` (`false` по умолчанию) — возврат исходного числа реплик объекту `Deployment` при удалении `ScaledObject`.
* `advanced.horizontalPodAutoscalerConfig.behavior` — прямое переопределение политик `scaleUp` / `scaleDown` и стабилизационных окон нативного HPA.

---

## Базовые концепции и архитектура

### Ключевые возможности

* **Масштабирование до нуля (Scale-to-Zero):** Освобождение CPU и памяти узлов кластера во время простоя очередей и очередей обработки фоновых задач.
* **Событийная модель управления:** Реакция на метрики глубины очередей сообщений, задержки обработки (consumer lag), таймеры и расписания вместо запаздывающих метрик потребления CPU/Memory.
* **Автономное управление HPA:** KEDA динамически создает, конфигурирует и синхронизирует ресурс HPA, избавляя администратора от ручной настройки External Metrics Adapter.
* **Аварийная устойчивость (Fault Tolerance):** Встроенные механизмы fallback и health checks защищают от деградации сервиса при падении систем мониторинга или брокеров очередей.
* **Композиция триггеров:** Возможность объединения нескольких триггеров (например, расписание + глубина очереди) с выбором максимального расчётного значения.

### Архитектура и системные компоненты

KEDA развёртывается в кластере в виде трёх независимых сервисов:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Kubernetes Cluster                             │
│                                                                             │
│   ┌────────────────────────┐                   ┌────────────────────────┐   │
│   │   External Sources     │                   │      K8s Workload      │   │
│   │ (RabbitMQ/Kafka/Prom)  │                   │ (Deployment/Stateful)  │   │
│   └──────────┬─────────────┘                   └───────────▲────────────┘   │
│              │                                             │                │
│              │ (metrics poll)               (/scale patch) │ (scale pods)   │
│              ▼                                             │                │
│   ┌──────────────────────┐                     ┌───────────┴────────────┐   │
│   │    keda-operator     │──(creates/syncs)───▶│ Native K8s HPA         │   │
│   │ (Controller/Agent)   │                     │ Controller             │   │
│   └──────────┬───────────┘                     └───────────▲────────────┘   │
│              │                                             │                │
│              │ (gRPC / internal)                           │ (query metrics)│
│              ▼                                             │                │
│   ┌──────────────────────┐                     ┌───────────┴────────────┐   │
│   │ keda-metrics-server  │◀────────────────────│ K8s API Server         │   │
│   │ (External Metrics)   │   (external.metrics.k8s.io)     │                │
│   └──────────────────────┘                                 │                │
│                                                            │                │
│   ┌──────────────────────┐                                 │ (validate YAML)│
│   │ keda-admission-      │◀────────────────────────────────┘                │
│   │ webhooks             │                                                  │
│   └──────────────────────┘                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

1. **keda-operator (Controller/Agent):**
   * Отслеживает жизненный цикл CRD (`ScaledObject`, `ScaledJob`, `TriggerAuthentication`).
   * Реализует логику холодного старта $0 \to 1$ и масштабирования в ноль $1 \to 0$ через прямое обновление подресурса `/scale` целевого контроллера (`Deployment`, `StatefulSet`).
   * Создаёт и обновляет связанный объект `HorizontalPodAutoscaler` при достижении $\ge 1$ реплики.
   * Управляет переключением в аварийный режим Fallback и обработкой аннотаций паузы.
   * Поддерживает High Availability с распределённым Leader Election (`--leader-elect=true`).

2. **keda-metrics-apiserver (Metrics Adapter):**
   * Реализует стандартный интерфейс расширения API Kubernetes `external.metrics.k8s.io`.
   * Служит адаптером между контроллером HPA и скейлерами KEDA.
   * Контроллер HPA запрашивает текущие числовые значения метрик через K8s API Server, который перенаправляет вызовы в `keda-metrics-apiserver`.

3. **keda-admission-webhooks:**
   * Валидирует синтаксическую корректность и целостность манифестов KEDA при вызовах `kubectl apply` / GitOps.
   * Предотвращает дублирование целей масштабирования (не позволяет нескольким `ScaledObject` управлять одним `Deployment`).
   * Проверяет допустимость пороговых значений интервалов `pollingInterval` и `cooldownPeriod`.

### KEDA HTTP Add-on

Для сценариев масштабирования приложений, обрабатывающих входящие HTTP-запросы без очередей сообщений, используется дополнительный оператор **KEDA HTTP Add-on**:
* **HTTP Interceptor:** Входной прокси-сервер. При наличии `0` реплик у сервиса он удерживает входящие HTTP-соединения в буфере и генерирует событие в KEDA Operator для старта первого пода.
* **HTTP Scaler:** Передаёт метрику числа ожидающих запросов (queue length / pending HTTP requests) в оператор.
* **Маршрутизация:** Как только под переходит в статус `Ready`, Interceptor перенаправляет накопленные HTTP-запросы на целевой сервис. Обеспечивает scale-to-zero без необходимости внедрения тяжеловесных Service Mesh решений.

### Принцип работы и жизненный цикл

Процесс масштабирования разделён на чёткие фазы ответственности между оператором KEDA и нативным HPA:

```text
    [0 реплик]             [1..N реплик]              [N..0 реплик]
        │                        │                          │
  Скейлер KEDA             Нативный HPA             Исчезновение событий
 опрашивает очередь       опрашивает KEDA          Метрики < activation
 (pollingInterval)         Metrics Server                   │
        │                        │                          ▼
 Метрика >= activation           ▼                 Старт cooldownPeriod
        │                 Расчёт реплик:                    │
        ▼                 ceil(curr * val/target)           ▼
 KEDA напрямую                   │                 По истечении таймера
 патчит /scale:                  ▼                 KEDA переводит
 0 -> 1 реплика           Масштабирование          Deployment: 1 -> 0
```

1. **Мониторинг простоя ($0$ реплик):** HPA находится в неактивном состоянии (нативный HPA в Kubernetes не умеет опускать реплики в ноль). Источник опрашивает исключительно `keda-operator` с интервалом `pollingInterval`.
2. **Активация ($0 \to 1$):** Значение метрики превышает `activationThreshold`. Оператор KEDA напрямую патчит подресурс `/scale` целевого объекта (Deployment/StatefulSet), устанавливая число реплик равным `minReplicaCount` (или 1).
3. **Рабочий режим ($1 \leftrightarrow N$):** Управление масштабированием подхватывает контроллер HPA Kubernetes. Каждые `--horizontal-pod-autoscaler-sync-period` (по умолчанию 15 секунд) HPA запрашивает значения через `keda-metrics-apiserver` и рассчитывает целевое число реплик по стандартной формуле:
   $$\text{DesiredReplicas} = \left\lceil \text{CurrentReplicas} \times \left( \frac{\text{CurrentMetricValue}}{\text{TargetMetricValue}} \right) \right\rceil$$
4. **Охлаждение и возврат в ноль ($N \to 0$):** Когда метрика падает ниже порога деактивации, HPA опускает реплики до 1. После этого запускается таймер `cooldownPeriod` (по умолчанию 300 секунд). Если за это время новых сообщений не появилось, оператор KEDA устанавливает реплики в `0`.

### Сравнение KEDA и стандартного HPA

| Критерий | Стандартный Kubernetes HPA | KEDA + HPA |
| :--- | :--- | :--- |
| **Масштабирование в ноль ($0 \leftrightarrow 1$)** | Не поддерживается (минимум 1 под) | Полная поддержка через `/scale` subresource |
| **Источники метрик** | Resource Metrics (CPU/RAM) и Custom Metrics через внешний адаптер | 60+ готовых скейлеров (RabbitMQ, Kafka, Redis, SQL, Prometheus) |
| **Поддерживаемые типы воркеров** | `Deployment`, `StatefulSet`, CR с `/scale` | `Deployment`, `StatefulSet`, кастомные CR + пакетные `Job` (`ScaledJob`) |
| **Аутентификация к источникам** | Требует отдельной настройки прав у адаптера | Декларативные CRD `TriggerAuthentication` / `ClusterTriggerAuthentication` |
| **Аварийный режим (Fallback)** | Отсутствует (ошибка метрики блокирует масштабирование) | Настраиваемый режим Fallback при недоступности брокера |
| **Математика метрик** | Простое пороговое значение | Scaling Modifiers (формулы, веса, логика MAX) |

### Особенности развёртывания в On-Premise / Bare-Metal инфраструктуре

В закрытых корпоративных контурах и Bare-Metal инсталляциях (kubeadm, RKE2, Kubespray):
1. **Prometheus как единая точка сбора:** В изолированных контурах предпочтительно использовать `prometheus` scaler вместо открытия прямых сетевых доступов оператора к десяткам отдельных баз данных. Prometheus централизованно агрегирует метрики с экспортеров.
2. **Безопасность без IAM:** Из-за отсутствия облачных сервисов метаданных (Instance Metadata Service) аутентификация строится строго на базе нативных `Secret`, mTLS-сертификатов или через интеграцию с локальным кластером HashiCorp Vault с помощью External Secrets Operator.
3. **Интеграция с локальным масштабированием узлов:** При резких всплесках очередей воркеры могут перейти в статус `Pending`. В Bare-Metal для динамического ввода новых серверов применяются Cluster API с Metal3/Ironic или предварительно прогретые пулы свободных узлов.
4. **Сетевая изоляция:** `keda-operator` и `keda-metrics-apiserver` должны иметь сетевой доступ к целевым сервисам через ClusterIP Service или внутренние балансировщики.

---

## Практические сценарии и конфигурация

### Высоконадёжная установка через Helm (On-Premise)

Для промышленной эксплуатации KEDA развёртывается с распределением компонентов по узлам и включённым мониторингом:

```yaml
# values-keda-production.yaml
crds:
  install: true

operator:
  replicaCount: 2
  leaderElection:
    enabled: true
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
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
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  useHostNetwork: false

webhooks:
  replicaCount: 2

prometheus:
  metricServer:
    enabled: true
    serviceMonitor:
      enabled: true
      interval: 15s
  operator:
    enabled: true
    serviceMonitor:
      enabled: true
      interval: 15s
```

Команда установки в кластер:

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm upgrade --install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  -f values-keda-production.yaml
# → Release "keda" has been upgraded. Happy Helming!
```

### Спецификация ScaledObject (Production-шаблон)

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: order-consumer-scaler
  namespace: processing
  labels:
    app.kubernetes.io/part-of: order-processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: order-consumer
  pollingInterval: 15
  cooldownPeriod: 180
  minReplicaCount: 0
  maxReplicaCount: 25
  fallback:
    failureThreshold: 3
    replicas: 4
    behavior: currentReplicasIfHigher
  advanced:
    restoreToOriginalReplicaCount: false
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300
          policies:
            - type: Percent
              value: 20
              periodSeconds: 60
        scaleUp:
          stabilizationWindowSeconds: 0
          policies:
            - type: Percent
              value: 100
              periodSeconds: 15
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: orders.v1
        mode: QueueLength
        value: "20"
        activationValue: "1"
      authenticationRef:
        name: rabbitmq-trigger-auth
```

### Спецификация ScaledJob (Пакетная обработка)

`ScaledJob` используется для ресурсоёмких или длительных задач, где масштабирование `Deployment` неприменимо (например, обработка медиафайлов или генерация тяжёлых отчётов):

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: report-generator-job
  namespace: batch-jobs
spec:
  jobTargetRef:
    parallelism: 1
    completions: 1
    activeDeadlineSeconds: 1800
    backoffLimit: 2
    template:
      spec:
        restartPolicy: OnFailure
        containers:
          - name: generator
            image: internal-registry.corp/reports/worker:v1.4.2
            resources:
              requests:
                cpu: 1000m
                memory: 2Gi
              limits:
                cpu: 2000m
                memory: 4Gi
  pollingInterval: 30
  maxReplicaCount: 50
  successfulJobsHistoryLimit: 5
  failedJobsHistoryLimit: 10
  scalingStrategy:
    strategy: "default"
  triggers:
    - type: redis
      metadata:
        addressFromEnv: REDIS_HOST
        listName: reports_queue
        listLength: "1"
      authenticationRef:
        name: redis-trigger-auth
```

### Аутентификация источников: TriggerAuthentication

#### 1. Использование локального Kubernetes Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-credentials
  namespace: processing
type: Opaque
stringData:
  amqp-host: "amqp://app_user:StrongPassword123@rabbitmq.infra.svc.cluster.local:5672/sales"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: rabbitmq-trigger-auth
  namespace: processing
spec:
  secretTargetRef:
    - parameter: host
      name: rabbitmq-credentials
      key: amqp-host
```

#### 2. Интеграция с Vault через External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: kafka-keda-secret
  namespace: processing
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-cluster-store
    kind: ClusterSecretStore
  target:
    name: kafka-keda-credentials
    creationPolicy: Owner
  data:
    - secretKey: sasl-password
      remoteRef:
        key: kv/data/kafka/consumers/orders
        property: password
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-trigger-auth
  namespace: processing
spec:
  secretTargetRef:
    - parameter: password
      name: kafka-keda-credentials
      key: sasl-password
```

### Примеры конфигурации On-Premise скейлеров

#### 1. Prometheus Scaler (Универсальный мониторинг)

```yaml
triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus-k8s.monitoring.svc.cluster.local:9090
      query: sum(rate(http_requests_total{app="api-gw",status=~"5.."}[2m]))
      threshold: "50"
      activationThreshold: "5"
```

#### 2. Apache Kafka Scaler (Consumer Lag)

```yaml
triggers:
  - type: kafka
    metadata:
      bootstrapServers: kafka-cluster-kafka-bootstrap.kafka.svc:9092
      consumerGroup: order-processors
      topic: orders.incoming
      lagThreshold: "100"
      activationLagThreshold: "10"
      offsetResetPolicy: latest
    authenticationRef:
      name: kafka-trigger-auth
```

#### 3. PostgreSQL Scaler (SQL Запрос)

```yaml
triggers:
  - type: postgresql
    metadata:
      connectionFromEnv: DB_CONNECTION_STRING
      query: "SELECT COUNT(*) FROM tasks WHERE status = 'pending';"
      targetQueryValue: "15"
      activationTargetQueryValue: "1"
    authenticationRef:
      name: postgres-trigger-auth
```

#### 4. Cron Scaler (Временные окна высокой нагрузки)

```yaml
triggers:
  - type: cron
    metadata:
      timezone: Europe/Moscow
      start: 0 8 * * 1-5       # Понедельник-пятница с 08:00
      end: 0 19 * * 1-5        # До 19:00
      desiredReplicas: "10"
```

### Сложная логика: Композиция триггеров и Scaling Modifiers

При указании нескольких триггеров KEDA по умолчанию выбирает максимальное значение среди них ($\text{MAX}$):

```yaml
triggers:
  - type: rabbitmq
    metadata:
      queueName: urgent-tasks
      value: "5"
  - type: rabbitmq
    metadata:
      queueName: regular-tasks
      value: "50"
```

В KEDA v2.20+ поддерживаются **Scaling Modifiers**, позволяющие вычислять составные формулы:

```yaml
spec:
  scalingModifiers:
    formula: "2 * (trigger_urgent + 0.5 * trigger_regular)"
    target: "10"
    activationTarget: "1"
  triggers:
    - type: rabbitmq
      name: trigger_urgent
      metadata:
        queueName: urgent
        value: "1"
    - type: rabbitmq
      name: trigger_regular
      metadata:
        queueName: regular
        value: "1"
```

---

## Операции и команды

Практический справочник команд управления для DevOps/SRE инженера:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Список объектов** | `kubectl get scaledobject,scaledjob -A` | Общий просмотр статусов и количества реплик |
| **Детальный статус** | `kubectl describe scaledobject <name> -n <ns>` | Просмотр Conditions (`Ready`, `Active`), событий и ошибок |
| **Проверка HPA** | `kubectl get hpa -n <ns>` | Проверка связанного нативного HPA и текущих метрик |
| **Опрос External API** | `kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" \| jq .` | Проверка регистрации адаптера метрик в K8s API |
| **Чтение метрики** | `kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/<ns>/<metric-name>" \| jq .` | Проверка фактического значения, возвращаемого скейлером |
| **Пауза автоскейлинга**| `kubectl annotate scaledobject <name> autoscaling.keda.sh/paused="true" -n <ns>` | Заморозка текущего числа реплик для регламентных работ |
| **Снятие паузы** | `kubectl annotate scaledobject <name> autoscaling.keda.sh/paused- -n <ns>` | Возобновление штатного автоматического масштабирования |
| **Логи оператора** | `kubectl logs -n keda -l app.kubernetes.io/name=keda-operator -c keda-operator -f` | Мониторинг синхронизации объектов и ошибок подключения |
| **Логи Metrics Server**| `kubectl logs -n keda -l app.kubernetes.io/name=keda-metrics-apiserver -f` | Диагностика запросов от HPA и вызовов скейлеров |

### Примеры вывода команд

Проверка состояния объектов в кластере:

```bash
kubectl get scaledobject -n processing
# → NAME                    SCALETARGETKIND   SCALETARGETNAME   MIN   MAX   TRIGGERS   AUTHENTICATION           READY   ACTIVE   FALLBACK   AGE
# → order-consumer-scaler   Deployment        order-consumer    0     25    rabbitmq   rabbitmq-trigger-auth    True    True     False      14d
```

Инспекция условий масштабирования (Conditions):

```bash
kubectl get scaledobject order-consumer-scaler -n processing -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.message}{"\n"}{end}'
# → Ready       True    ScaledObject is ready for scaling
# → Active      True    Scaling is active as metric threshold is reached
# → Fallback    False   Scaler is operating normally, no fallback needed
```

Проверка регистрации адаптера внешних метрик:

```bash
kubectl get apiservice v1beta1.external.metrics.k8s.io
# → NAME                                SERVICE                 AVAILABLE   AGE
# → v1beta1.external.metrics.k8s.io     keda/keda-metrics-server   True        45d
```

---

## Диагностика и устранение неполадок

### Сводная таблица типовых сбоев

| Проблема / Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Поды не выходят из нуля (`0 → 1`)** | `Active: False` в ScaledObject; скейлер не может подключиться к брокеру; неверный секрет | `kubectl describe scaledobject`; логи `keda-operator` | Проверить сетевые доступы, DNS, корректность `TriggerAuthentication` и формат строки подключения |
| **Флаппинг (колебания $0 \leftrightarrow 1 \leftrightarrow N$)** | Слишком малый `cooldownPeriod`; конфликт с окном стабилизации HPA | `kubectl get hpa -w`; события деплоймента | Увеличить `cooldownPeriod` до $\ge 180$ с; настроить `behavior.scaleDown.stabilizationWindowSeconds` |
| **Ошибка регистрации External Metrics API** | Порт 443/6443 закрыт; конфликт с Prometheus Adapter; просрочен TLS-сертификат | `kubectl get apiservice v1beta1.external.metrics.k8s.io` | Проверить валидность сертификатов вебхука; устранить дублирующие External Metrics серверы |
| **Зависание на `maxReplicaCount`** | Необрабатываемые "ядовитые" сообщения (poison pills); исчерпание пула БД | Очередь Dead Letter Queue (DLQ); Grafana | Настроить DLQ в брокере; задать жесткий `maxReplicaCount` во избежание DDoS внутренней инфраструктуры |
| **Утечка подов в ScaledJob** | Не настроен `successfulJobsHistoryLimit`; падение задач | `kubectl get jobs -n <ns>` | Задать `successfulJobsHistoryLimit: 3`, `failedJobsHistoryLimit: 5`, `activeDeadlineSeconds` |
| **PDB блокирует scale-to-zero** | `minAvailable: 1` в `PodDisruptionBudget` препятствует удалению последнего пода | `kubectl get pdb -n <ns>`; события `FailedScaleDown` в HPA | Заменить `minAvailable: 1` на `maxUnavailable: 20%` или убрать PDB для очередей без state |

### Детальные сценарии отладки

#### 1. Ошибки аутентификации или сетевой недоступности скейлера

Если `Ready: False`, просмотрите секцию Events:

```bash
kubectl describe scaledobject order-consumer-scaler -n processing
# → Warning  KedaScalerFailed  2m  keda-operator  dial tcp 10.96.14.22:5672: connect: connection refused
```

Шаги решения:
1. Запустите временный отладочный под в том же namespace и проверьте связность:
   ```bash
   kubectl run net-test --rm -it --image=curlimages/curl --restart=Never -n processing -- \
     nc -zvw3 rabbitmq.infra.svc.cluster.local 5672
   # → rabbitmq.infra.svc.cluster.local (10.96.14.22:5672) open
   ```
2. Проверьте NetworkPolicy, блокирующие egress-трафик из namespace `keda` к namespace целевого сервиса.

#### 2. Конфликт ручного HPA и KEDA

Если для одного и того же Deployment существует вручную созданный HPA и HPA от KEDA, контроллеры начнут перезаписывать число реплик друг друга:

```bash
kubectl get hpa -n processing
# → NAME                                 REFERENCE                   TARGETS
# → manual-order-hpa                     Deployment/order-consumer   cpu: 45%/80%
# → keda-hpa-order-consumer-scaler       Deployment/order-consumer   s0-rabbitmq: 15/20
```

Решение: Удалите ручной HPA. Если необходимо масштабирование и по CPU, и по событиям, объедините метрики внутри KEDA через `kubernetes-resource` или `prometheus` триггеры.

---

## Рекомендации и Best Practices

### Архитектурные и SRE гардрейлы

1. **Всегда задавайте `maxReplicaCount`:** Защищает кластер от каскадной деградации: лавинообразный рост очереди не должен приводить к исчерпанию пула IP-адресов CNI, лимитов памяти на узлах или исчерпанию соединений к базе данных.
2. **Обязательная настройка Fallback для критических систем:** Всегда конфигурируйте секцию `fallback` в `ScaledObject`. Если брокер или Prometheus станет недоступен, воркеры должны оставаться в рабочем состоянии (`behavior: currentReplicasIfHigher` или фиксированное резервное число подов), а не обнуляться.
3. **Безопасное завершение работы (Graceful Shutdown):**
   * В спецификации воркера задавайте достаточный `terminationGracePeriodSeconds` (например, 60–120 секунд).
   * При получении сигнала `SIGTERM` воркер должен прекратить брать новые сообщения из очереди, завершить обработку текущего сообщения и подтвердить его (`ACK`).
4. **Настройка PodDisruptionBudget (PDB):**
   * Избегайте `minAvailable: 1` для нагрузок со `scale-to-zero`. HPA не сможет удалить последний под, если PDB запрещает снижение доступности ниже единицы.
   * Используйте `maxUnavailable: 25%` или `maxUnavailable: 1`.
5. **Оптимизация опроса Prometheus:**
   * Не настраивайте `pollingInterval: 5s` для тяжелых PromQL-запросов (`sum(rate(...[1h]))`). Это создаст избыточную нагрузку на TSDB Prometheus. Оптимальный интервал — 15–30 секунд с окнами агрегации `[2m]` или `[5m]`.
6. **Разделение прав доступа (RBAC):**
   * Не используйте кластерные секреты (`ClusterTriggerAuthentication`) для изоляции сред (prod/stage/dev).
   * Назначайте права скейлерам на уровне отдельных пространств имён через `TriggerAuthentication`.

### Мониторинг и алертинг KEDA (PrometheusRule)

Критически важные алерты для Prometheus Alertmanager:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: keda-operational-alerts
  namespace: keda
spec:
  groups:
    - name: keda.rules
      rules:
        - alert: KEDAScalerErrorsHigh
          expr: sum by (scaledObject, namespace) (rate(keda_scaler_errors[5m])) > 0.1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "KEDA Scaler errors detected for {{ $labels.scaledObject }}"
            description: "Скейлер не может получить метрики из источника. Проверьте сетевую доступность и секреты."

        - alert: KEDAScaledObjectInFallback
          expr: keda_scaledobject_fallback_activity == 1
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "ScaledObject {{ $labels.scaledObject }} переключился в Fallback"
            description: "Источник метрик недоступен. Нагрузка работает в аварийном режиме с фиксированными репликами."

        - alert: KEDAMaxReplicasReached
          expr: keda_scaledobject_replicas >= keda_scaledobject_max_replicas
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "ScaledObject {{ $labels.scaledObject }} достиг максимума реплик"
            description: "Воркеры работают на пределе емкости (maxReplicaCount). Возможно образование очереди."
```

---

## Дополнительная информация

### Часто задаваемые вопросы (FAQ)

**Заменяет ли KEDA стандартный Kubernetes HPA?**  
Нет. KEDA расширяет HPA. KEDA берет на себя логику холодного старта ($0 \to 1$), периодического опроса внешних брокеров и поставку кастомных внешних метрик через `Metrics API Server`. Управление количеством реплик от 1 до N осуществляет стандартный контроллер HPA Kubernetes.

**Что произойдёт с приложениями, если упадут поды KEDA Operator?**  
Существующие воркеры продолжат функционировать на текущем числе реплик. Нативный контроллер HPA продолжит опрашивать последнюю кэшированную метрику или сохранит текущий масштаб. Новые поды не запустятся из нуля, а масштаб не уменьшится до восстановления оператора.

**Можно ли использовать KEDA для StatefulSet с постоянными дисками (PVC)?**  
Да, если сервис поддерживает параллельное добавление воркеров без кворумного согласования (`podManagementPolicy: Parallel`). Для stateful-воркеров с локальным кэшем KEDA эффективно масштабирует чтение или разбор очередей. Категорически запрещено подключать автоскейлинг к базам данных с кворумным консенсусом (etcd, Raft, ZooKeeper).

### Связанные материалы в базе знаний

* [KEDA: Практические сценарии](./practical_scenarios.md) — пошаговые сценарии настройки триггеров и Helm-установки
* [KEDA: Эксплуатация, мониторинг и troubleshooting](./keda-operations.md) — дашборды Grafana, операционные сценарии и алерты
* [KEDA + Apache Kafka Scaler](./kafka-keda-scaler.md) — детальная настройка масштабирования по Consumer Lag и SASL/mTLS
* [KEDA + Redis Scaler](./redis-keda-scaler.md) — масштабирование по длине списков и Redis Streams
* [KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md) — финансовая оптимизация и замер эффекта от scale-to-zero
* [KEDA: Тестирование и валидация](./keda-testing-validation.md) — нагрузочное тестирование и эмуляция отказа скейлеров
* [KEDA: Вопросы для собеседования](./keda-interview-questions.md) — разбор архитектурных вопросов и нюансов KEDA
* [Паттерн воркеров и очередей](../workers_queue_pattern.md) — архитектурные шаблоны обработки очередей в Kubernetes
* [Масштабирование StatefulSet](../statefulset_autoscaling.md) — особенности масштабирования StatefulSet нагрузок
* [HPA: Концепции и архитектура](../HPA/index.md) — устройство нативного контроллера Horizontal Pod Autoscaler
