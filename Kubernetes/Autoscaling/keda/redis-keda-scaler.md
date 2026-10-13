# KEDA + Redis: Масштабирование на основе длины очередей и Streams

**Актуально для:** KEDA 2.15–2.17+ / Redis 6.x, 7.x, 8.x (Standalone, Sentinel, Cluster) / Kubernetes 1.28–1.35

## Определения

**Redis Lists Scaler** — встроенный специализированный адаптер KEDA (`type: redis`, `type: redis-sentinel`, `type: redis-cluster`), выполняющий опрос длины списков (List) в Redis с помощью легковесной команды `LLEN` и передающий рассчитанную метрику в HPA для горизонтального автомасштабирования подов-обработчиков.

**Redis Streams Scaler** — специализированный адаптер KEDA (`type: redis-streams`, `type: redis-sentinel-streams`, `type: redis-cluster-streams`), вычисляющий потребность в репликах на основе структур Redis Streams. Поддерживает три режима оценки нагрузки: по общему лагу группы потребителей (Consumer Group Lag через `XINFO GROUPS`), по размеру списка ожидающих подтверждения записей (Pending Entries List через `XPENDING`), либо по абсолютной длине потока (`XLEN`).

**Consumer Group Lag (Streams)** — разница между идентификатором последней записи, добавленной в поток (`last-generated-id`), и последним смещением, переданным группе потребителей (`last-delivered-id`). Возвращается полем `lag` команды `XINFO GROUPS`. Доступно начиная с Redis 7.0. Позволяет честно масштабировать нагрузку вплоть до нуля (`0 ↔ N`).

**Pending Entries List (PEL / XPENDING)** — системный список сообщений стрима, которые уже были прочитаны воркерами группы (`XREADGROUP`), но ещё не подтверждены командой `XACK`. Рост PEL сигнализирует о зависании, аварийном завершении воркеров или нехватке вычислительной мощности для своевременной обработки задач.

**listLength** — целевой порог средней длины списка Redis на одну активную реплику пода (по умолчанию `5`). Используется контроллером HPA для пропорционального расчета желаемого количества реплик (`desiredReplicas`).

**activationListLength** — пороговое значение длины списка Redis (по умолчанию `0`), при превышении которого KEDA активирует нагрузку и переводит её из состояния простоя в одну реплику (`0 -> 1`). Позволяет избегать преждевременного выхода из спящего режима при случайных одиночных сообщениях.

**lagCount** — целевое пороговое значение отставания группы потребителей (Consumer Group Lag) на одну реплику пода при использовании триггера `redis-streams` в режиме лага.

**activationLagCount** — пороговое значение лага группы потребителей (по умолчанию `0`), необходимое для активации нагрузки из нуля реплик (`0 -> 1`).

**pendingEntriesCount** — целевой порог количества неподтверждённых сообщений в PEL на одну реплику для стримов при мониторинге зависших задач.

**streamLength** — целевой порог абсолютного количества записей в Redis Stream (`XLEN`) на одну реплику при отсутствии консьюмер-групп.

**databaseIndex** — числовой индекс логической базы данных Redis (по умолчанию `0`). Redis Standalone и Sentinel поддерживают базы от `0` до `15` (по умолчанию директивой `databases 16`). В архитектуре Redis Cluster поддерживается строго база `0` (попытка смены базы возвращает ошибку `ERR SELECT is not allowed in cluster mode`).

**Redis Sentinel Quorum** — распределённый механизм арбитража и автоматического переключения при отказе (failover) мастера. KEDA подключается к пулу нод Sentinel по порту `26379`, опрашивает имя мастера (`sentinelMaster`) через команду `SENTINEL get-master-addr-by-name <master-name>`, динамически получает актуальный IP/порт ведущего узла и направляет запросы метрик на него.

**Redis Cluster Hash Slots** — схема шардирования данных, распределяющая ключи по 16 384 хэш-слотам. KEDA поддерживает кластерную топологию (`redis-cluster`, `redis-cluster-streams`), обращаясь к указанным сид-узлам, получая карту слотов через `CLUSTER SLOTS` / `CLUSTER SHARDS` и направляя запрос `LLEN` или `XLEN` строго на мастер-ноду, владеющую слотом целевого ключа.

---

## Архитектура и механизм работы

### Архитектурные паттерны подключения KEDA к Redis

Масштабирование воркеров Redis в Kubernetes реализуется через прямой протокольный опрос инстансов Redis без обязательного наличия промежуточных баз данных метрик.

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Инфраструктура Redis (On-Premise / Bare-Metal / Self-Hosted K8s)       │
│                                                                        │
│   ┌──────────────────┐   Failover    ┌──────────────────────────────┐  │
│   │ Redis Sentinel   │ ────────────▶ │ Redis Master (Node 0)        │  │
│   │ Quorum (26379)   │               │ Data & Queues: port 6379     │  │
│   └────────▲─────────┘               └──────────────▲───────────────┘  │
└────────────┼────────────────────────────────────────┼──────────────────┘
             │ SENTINEL get-master-addr               │ LLEN / XLEN /
             │                                        │ XINFO GROUPS
┌────────────┴────────────────────────────────────────┴──────────────────┐
│ Kubernetes Cluster                                                     │
│                                                                        │
│  ┌────────────────────────┐  TriggerAuthentication                     │
│  │ keda-operator          │ ◀── Secret (Password / ACL / mTLS)         │
│  │ (Active/Passive scale) │                                            │
│  └──────────┬─────────────┘                                            │
│             │ gRPC                                                     │
│  ┌──────────▼─────────────┐                                            │
│  │ keda-metrics-apiserver │ (Регистрируется как external.metrics.k8s.io)│
│  └──────────┬─────────────┘                                            │
│             │ External Metrics API                                     │
│  ┌──────────▼─────────────┐      scaleTargetRef                        │
│  │ kube-controller-manager│ ──────────────────────────┐                │
│  │ (HPA Controller)       │                           │                │
│  └────────────────────────┘                           ▼                │
│                                              ┌─────────────────┐       │
│                                              │ Queue Processor │       │
│                                              │ Worker Pods     │       │
│                                              └─────────────────┘       │
└────────────────────────────────────────────────────────────────────────┘
```

### Поддерживаемые типы триггеров Redis в KEDA

В зависимости от структуры данных и топологии развертывания хранилища KEDA предоставляет шесть нативных типов триггеров:

| Тип триггера | Топология Redis | Источник данных | Выполняемые Redis-команды | Минимальная версия |
|:---|:---|:---|:---|:---|
| `redis` | Standalone / Репликация | Redis Lists | `LLEN <listName>` | KEDA 1.0+ / Redis 2.0+ |
| `redis-sentinel` | Sentinel HA | Redis Lists | `SENTINEL get-master-addr-by-name` + `LLEN` | KEDA 2.1+ / Redis 2.8+ |
| `redis-cluster` | Redis Cluster | Redis Lists | `CLUSTER SLOTS` + `LLEN` на целевой шард | KEDA 2.1+ / Redis 3.0+ |
| `redis-streams` | Standalone / Репликация | Redis Streams | `XINFO GROUPS`, `XPENDING`, `XLEN` | KEDA 1.5+ / Redis 5.0+ (Lag: 7.0+) |
| `redis-sentinel-streams` | Sentinel HA | Redis Streams | Sentinel failover resolution + команды Streams | KEDA 2.5+ / Redis 5.0+ (Lag: 7.0+) |
| `redis-cluster-streams` | Redis Cluster | Redis Streams | Cluster slot resolution + команды Streams | KEDA 2.5+ / Redis 5.0+ (Lag: 7.0+) |

### Жизненный цикл масштабирования и формула расчета реплик

Автомасштабирование разделено на две независимые зоны ответственности:

1. **Фаза активации (`0 ↔ 1` реплика):**
   Выполняется процессом `keda-operator` с интервалом `pollingInterval`.
   - Если метрика очереди превышает `activationListLength` (или `activationLagCount`), оператор масштабирует `scaleTargetRef` из нуля в `1` (или в `minReplicaCount`, если он больше нуля).
   - Если очередь пуста в течение `cooldownPeriod` секунд, оператор возвращает количество реплик в `0`.
2. **Фаза динамического масштабирования (`1 ↔ N` реплик):**
   Выполняется штатным контроллером `kube-controller-manager` (HPA) на основе метрик, отдаваемых `keda-metrics-apiserver` каждые 15 секунд (параметр `--horizontal-pod-autoscaler-sync-period`).

Формула расчета целевого числа подов HPA:

$$\text{desiredReplicas} = \left\lceil \text{currentReplicas} \times \left( \frac{\text{currentMetricValue}}{\text{targetValue}} \right) \right\rceil$$

**Пример для Redis List:**
- Текущее число подов: 2
- Текущая длина списка `task-queue` (`LLEN`): 340
- Целевой порог `listLength`: 50
- Расчет: $\lceil 2 \times (340 / (2 \times 50)) \rceil = \lceil 340 / 50 \rceil = 7$ реплик.

### Три режима масштабирования Redis Streams

Для триггеров семейства `redis-streams` поведение адаптера определяется комбинацией переданных параметров:

```text
                                  ┌────────────────────────┐
                                  │ Опрос стрима в KEDA    │
                                  └───────────┬────────────┘
                                              │
                              Параметр consumerGroup задан?
                                      /               \
                                    Да                Нет
                                   /                    \
                     Параметр lagCount > 0?          Режим Stream Length
                         /             \             Команда: XLEN
                       Да              Нет           Метрика: TargetStreamLength
                      /                  \
             Режим Group Lag       Режим Pending (PEL)
             Команда: XINFO GROUPS Команда: XPENDING
             Метрика: TargetLag    Метрика: TargetPendingEntriesCount
             (Требует Redis 7.0+)
```

1. **Режим Consumer Group Lag (`lagCount`):**
   Рекомендуемый режим для современных очередей. Опрашивает отставание консьюмер-группы через `XINFO GROUPS <stream>`. Учитывает сообщения, поступившие в стрим, но еще не взятые ни одним консьюмером. Поддерживает scale-to-zero. Требует Redis 7.0+.
2. **Режим Pending Entries List (`pendingEntriesCount`):**
   Активируется при указании `consumerGroup` и отсутствии `lagCount`. Опрашивает суммарное число сообщений, прочитанных воркерами, но ожидающих `XACK`. Применяется для масштабирования сервисов разбора зависших задач или отслеживания деградации воркеров.
3. **Режим Stream Length (`streamLength`):**
   Активируется, если `consumerGroup` не указан. Опрашивает общий размер стрима через `XLEN`. Применяется для сервисов ротации, очистки или пакетной архивации данных.

### Сводная таблица параметров конфигурации триггеров

| Параметр | Применимость к триггеру | Обязательный | По умолчанию | Описание |
|:---|:---|:---|:---|:---|
| `address` | `redis`, `redis-streams` | Да* | — | Сетевой адрес сервера Redis в формате `host:port`. |
| `addresses` | `sentinel`, `cluster` | Да* | — | Список адресов нод через запятую (`host1:port,host2:port`). |
| `host` / `port` | Все | Нет | — | Альтернатива `address`. При указании `host` параметр `port` обязателен. |
| `listName` | `redis`, `redis-sentinel`, `redis-cluster` | Да | — | Имя ключа списка Redis, содержащего очередь задач. |
| `listLength` | `redis`, `redis-sentinel`, `redis-cluster` | Да | `5` | Среднее количество задач на одну реплику пода. |
| `activationListLength` | `redis`, `redis-sentinel`, `redis-cluster` | Нет | `0` | Порог длины очереди для активации реплик из нуля (`0 -> 1`). |
| `stream` | `redis-streams`, sentinel/cluster | Да | — | Имя ключа стрима Redis. |
| `consumerGroup` | `redis-streams`, sentinel/cluster | Нет** | — | Имя группы потребителей стрима. |
| `lagCount` | `redis-streams`, sentinel/cluster | Нет | — | Целевой лаг группы потребителей на под (требует Redis 7+). |
| `activationLagCount` | `redis-streams`, sentinel/cluster | Нет | `0` | Порог лага стрима для активации подов из нуля. |
| `pendingEntriesCount` | `redis-streams`, sentinel/cluster | Нет | `5` | Целевой объем неподтвержденных записей PEL на под. |
| `streamLength` | `redis-streams`, sentinel/cluster | Нет | `5` | Целевой общий размер стрима (`XLEN`) на под. |
| `databaseIndex` | Standalone, Sentinel | Нет | `0` | Номер логической БД (`SELECT <index>`). Запрещен в Cluster! |
| `sentinelMaster` | `redis-sentinel`, `redis-sentinel-streams` | Да | — | Имя мастера в конфигурации Sentinel. |
| `enableTLS` | Все | Нет | `false` | Использование шифрования TLS при подключении к Redis. |
| `unsafeSsl` | Все | Нет | `false` | Отключение валидации сертификата (для Self-Signed CA). |

*\* — Обязателен, если не переданы `host`/`port` или соответствующие параметры из переменных окружения.*
*\*\* — Обязателен при использовании режимов `lagCount` или `pendingEntriesCount`.*

---

## Практические сценарии и конфигурации

### Требования к окружению (Prerequisites)

- Развернутый кластер Kubernetes v1.28–v1.35.
- Установленный оператор KEDA v2.15–v2.17+ в пространстве имен `keda`.
- Доступный сервер Redis (Standalone, Sentinel или Cluster) версии 6.x, 7.x или 8.x.
- Сетевая связность между подами `keda-operator` / `keda-metrics-apiserver` и портами Redis (6379, 26379).

---

### Сценарий 1: Production Worker на базе Redis List (Celery / RQ / BullMQ)

Масштабирование пула воркеров фоновой обработки задач, потребляющих очередь из Redis List (паттерн `LPUSH` / `BRPOP`). Включает гардрейлы подавления флаппинга (scale-down stabilization) и активацию из нуля.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-worker-secret
  namespace: processing
type: Opaque
stringData:
  redis-host: "redis-master.storage.svc.cluster.local:6379"
  redis-username: "keda_scaler"
  redis-password: "SuperSecureWorkerPassword123!"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-list-auth
  namespace: processing
spec:
  secretTargetRef:
    - parameter: address
      name: redis-worker-secret
      key: redis-host
    - parameter: username
      name: redis-worker-secret
      key: redis-username
    - parameter: password
      name: redis-worker-secret
      key: redis-password
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: queue-worker
  namespace: processing
  labels:
    app: queue-worker
spec:
  replicas: 0
  selector:
    matchLabels:
      app: queue-worker
  template:
    metadata:
      labels:
        app: queue-worker
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: worker
          image: internal-registry.infra.local/apps/task-worker:v2.4.0
          env:
            - name: REDIS_URL
              value: "redis://keda_scaler:SuperSecureWorkerPassword123!@redis-master.storage.svc.cluster.local:6379/0"
            - name: QUEUE_NAME
              value: "high-priority-jobs"
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: redis-list-scaledobject
  namespace: processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: queue-worker
  minReplicaCount: 0
  maxReplicaCount: 20
  pollingInterval: 15
  cooldownPeriod: 180
  fallback:
    failureThreshold: 3
    replicas: 2
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
            - type: Pods
              value: 2
              periodSeconds: 60
          selectPolicy: Min
        scaleUp:
          stabilizationWindowSeconds: 0
          policies:
            - type: Percent
              value: 100
              periodSeconds: 15
            - type: Pods
              value: 4
              periodSeconds: 15
          selectPolicy: Max
  triggers:
    - type: redis
      metadata:
        listName: high-priority-jobs
        listLength: "25"
        activationListLength: "1"
        databaseIndex: "0"
      authenticationRef:
        name: redis-list-auth
```

**Особенности конфигурации:**
- `activationListLength: "1"` гарантирует моментальное появление первого пода при добавлении хотя бы одного задания.
- `stabilizationWindowSeconds: 300` удерживает поды от преждевременного удаления в моменты кратковременного опустошения очереди.
- `fallback.replicas: 2` поднимает дежурные реплики, если сетевой сбой блокирует запросы KEDA к Redis.

---

### Сценарий 2: Redis Streams с Consumer Group Lag (Redis 7.x+)

Масштабирование воркеров консьюмер-группы в Event-Driven архитектуре по метрике отставания (`lag`) с поддержкой Scale-to-Zero.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-stream-secret
  namespace: analytics
type: Opaque
stringData:
  address: "redis-cluster.storage.svc.cluster.local:6379"
  password: "SecureStreamAuthPass987!"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-stream-auth
  namespace: analytics
spec:
  secretTargetRef:
    - parameter: address
      name: redis-stream-secret
      key: address
    - parameter: password
      name: redis-stream-secret
      key: password
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: event-consumer-scaler
  namespace: analytics
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: telemetry-processor
  minReplicaCount: 0
  maxReplicaCount: 30
  pollingInterval: 10
  cooldownPeriod: 120
  triggers:
    - type: redis-streams
      metadata:
        stream: telemetry-stream
        consumerGroup: telemetry-workers
        lagCount: "100"
        activationLagCount: "5"
        databaseIndex: "0"
      authenticationRef:
        name: redis-stream-auth
```

**Особенности конфигурации:**
- Требует Redis версии не ниже 7.0, так как вычисление `lag` опирается на счетчик необслуженных записей внутри группы.
- Скейлер рассчитывает поды: при отставании в 800 сообщений HPA выставит $\lceil 800 / 100 \rceil = 8$ реплик.
- Если лаг меньше `5`, нагрузка сохраняет нулевое число реплик без расхода ресурсов кластера.

---

### Сценарий 3: Redis Streams по числу зависших задач (Pending Entries List / PEL)

Используется для масштабирования специализированного воркера-рековерера, задача которого — забирать брошенные задачи упавших воркеров через `XAUTOCLAIM` / `XCLAIM`.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: stream-deadletter-cleaner
  namespace: analytics
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: pel-recovery-service
  minReplicaCount: 0
  maxReplicaCount: 5
  pollingInterval: 30
  cooldownPeriod: 300
  triggers:
    - type: redis-streams
      metadata:
        address: redis-node.storage.svc.cluster.local:6379
        stream: telemetry-stream
        consumerGroup: telemetry-workers
        pendingEntriesCount: "50"
        databaseIndex: "0"
      authenticationRef:
        name: redis-stream-auth
```

**Особенности конфигурации:**
- Задействует вызов команды `XPENDING telemetry-stream telemetry-workers`.
- Не требует Redis 7+ (поддерживается нативно начиная с Redis 5.0).
- Идеально для изоляции нормального потока обработки и аварийного разбора подвисших сообщений.

---

### Сценарий 4: Отказоустойчивая топология Redis Sentinel (`type: redis-sentinel`)

Подключение KEDA к пулу нод Sentinel. При падении ведущего узла Sentinel выполняет элекцию нового мастера, а KEDA автоматически переключает запросы метрик без вмешательства инженера.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-sentinel-secrets
  namespace: order-service
type: Opaque
stringData:
  sentinel-nodes: "redis-sentinel-0.sentinel.storage.svc:26379,redis-sentinel-1.sentinel.storage.svc:26379,redis-sentinel-2.sentinel.storage.svc:26379"
  redis-password: "MasterNodeStrongPassword!"
  sentinel-password: "SentinelQuorumPassword!"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-sentinel-trigger-auth
  namespace: order-service
spec:
  secretTargetRef:
    - parameter: addresses
      name: redis-sentinel-secrets
      key: sentinel-nodes
    - parameter: password
      name: redis-sentinel-secrets
      key: redis-password
    - parameter: sentinelPassword
      name: redis-sentinel-secrets
      key: sentinel-password
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orders-queue-sentinel-scaler
  namespace: order-service
spec:
  scaleTargetRef:
    name: order-processor
  minReplicaCount: 1
  maxReplicaCount: 15
  pollingInterval: 15
  cooldownPeriod: 180
  triggers:
    - type: redis-sentinel
      metadata:
        sentinelMaster: "mymaster"
        listName: orders-incoming
        listLength: "20"
        activationListLength: "1"
        databaseIndex: "0"
      authenticationRef:
        name: redis-sentinel-trigger-auth
```

**Особенности конфигурации:**
- Параметр `type: redis-sentinel` сообщает оператору о необходимости выполнения протокола обнаружения через Sentinel.
- Параметр `sentinelMaster: "mymaster"` указывает имя группы мониторинга Sentinel.
- Раздельные учетные данные для доступа к самому Sentinel (`sentinelPassword`) и целевой базе Redis (`password`).

---

### Сценарий 5: Шардированный Redis Cluster (`type: redis-cluster`)

Масштабирование воркеров при хранении очередей в распределенном Redis Cluster. KEDA самостоятельно отслеживает хэш-слоты и подключается к мастеру конкретного шарда.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: redis-cluster-secret
  namespace: payments
type: Opaque
stringData:
  cluster-endpoints: "redis-cluster-node-0.cache.svc:6379,redis-cluster-node-1.cache.svc:6379,redis-cluster-node-2.cache.svc:6379"
  cluster-password: "ClusterPassword777!"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-cluster-auth
  namespace: payments
spec:
  secretTargetRef:
    - parameter: addresses
      name: redis-cluster-secret
      key: cluster-endpoints
    - parameter: password
      name: redis-cluster-secret
      key: cluster-password
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: payment-queue-cluster-scaler
  namespace: payments
spec:
  scaleTargetRef:
    name: payment-processing-worker
  minReplicaCount: 2
  maxReplicaCount: 25
  triggers:
    - type: redis-cluster
      metadata:
        listName: "{payment}:transactions"
        listLength: "50"
        activationListLength: "5"
        databaseIndex: "0"
      authenticationRef:
        name: redis-cluster-auth
```

**Особенности конфигурации:**
- Параметр `type: redis-cluster` активирует кластерный клиент Go-Redis в рантайме KEDA.
- Использование хэш-тегов (`{payment}:transactions`) гарантирует детерминированное попадание связанных ключей в один хэш-слот шарда.
- Значение `databaseIndex` обязано быть `0`.

---

### Сценарий 6: Защищенный mTLS / TLS (Enterprise PKI / cert-manager)

Подключение к защищенному корпоративному кластеру Redis с двусторонней аутентификацией по TLS-сертификатам.

```yaml
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: redis-mtls-auth
  namespace: secure-zone
spec:
  secretTargetRef:
    - parameter: address
      name: redis-conn-secret
      key: endpoint
    - parameter: ca
      name: redis-client-tls-secret
      key: ca.crt
    - parameter: cert
      name: redis-client-tls-secret
      key: tls.crt
    - parameter: key
      name: redis-client-tls-secret
      key: tls.key
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: secure-redis-scaler
  namespace: secure-zone
spec:
  scaleTargetRef:
    name: secure-processor
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: redis
      metadata:
        listName: encrypted-tasks
        listLength: "10"
        enableTLS: "true"
        unsafeSsl: "false"
      authenticationRef:
        name: redis-mtls-auth
```

**Особенности конфигурации:**
- Сертификаты монтируются KEDA из Secret, созданного `cert-manager`.
- Параметр `enableTLS: "true"` активирует обязательное TLS-рукопожатие.
- Параметр `unsafeSsl: "false"` запрещает игнорирование ошибок проверки сертификатов.

---

### Сценарий 7: Несколько очередей с весовыми приоритетами (High vs Low Priority)

Один ScaledObject отслеживает две разные очереди. HPA вычисляет необходимое число реплик по каждому триггеру независимо и выбирает максимальное (`selectPolicy: Max`).

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: priority-worker-scaler
  namespace: processing
spec:
  scaleTargetRef:
    name: unified-task-worker
  minReplicaCount: 1
  maxReplicaCount: 30
  pollingInterval: 10
  cooldownPeriod: 120
  triggers:
    - type: redis
      metricType: AverageValue
      metadata:
        address: redis-master.storage.svc:6379
        listName: high-priority-jobs
        listLength: "10"
      authenticationRef:
        name: redis-list-auth
    - type: redis
      metricType: AverageValue
      metadata:
        address: redis-master.storage.svc:6379
        listName: low-priority-jobs
        listLength: "100"
      authenticationRef:
        name: redis-list-auth
```

**Особенности конфигурации:**
- Если в очереди `high-priority-jobs` находится 50 задач, этот триггер запросит $50 / 10 = 5$ подов.
- Если в очереди `low-priority-jobs` находится 800 задач, второй триггер запросит $800 / 100 = 8$ подов.
- HPA установит итоговое число реплик равным $\max(5, 8) = 8$ подов.

---

### Сценарий 8: Гибридное расписание Cron + Redis List

В рабочие часы (с 09:00 до 18:00 по будням) удерживается гарантированный минимальный пул реплик для нулевого cold start, а в нерабочее время нагрузка сжимается до нуля и масштабируется только по факту появления данных в очереди.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: hybrid-cron-redis-scaler
  namespace: processing
spec:
  scaleTargetRef:
    name: business-worker
  minReplicaCount: 0
  maxReplicaCount: 20
  pollingInterval: 15
  cooldownPeriod: 300
  triggers:
    - type: redis
      metadata:
        address: redis-master.storage.svc:6379
        listName: billing-events
        listLength: "20"
        activationListLength: "1"
      authenticationRef:
        name: redis-list-auth
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: "0 9 * * 1-5"
        end: "0 18 * * 1-5"
        desiredReplicas: "5"
```

---

## Эксплуатация и команды системного администрирования

### Ручная валидация состояния очередей и стримов в Redis

Диагностика структур данных внутри Redis для сопоставления с метриками KEDA:

```bash
# 1. Проверка длины списка задач (List)
kubectl run -it --rm redis-cli-diag --image=redis:7.2-alpine --restart=Never -- \
  redis-cli -h redis-master.storage.svc -p 6379 -a "SuperSecureWorkerPassword123!" LLEN high-priority-jobs
# → (integer) 142

# 2. Инспекция консьюмер-групп в Redis Streams (проверка лага и числа активных воркеров)
kubectl run -it --rm redis-cli-diag --image=redis:7.2-alpine --restart=Never -- \
  redis-cli -h redis-master.storage.svc -p 6379 -a "SecureStreamAuthPass987!" XINFO GROUPS telemetry-stream
# → 1)  1) "name"
#       2) "telemetry-workers"
#       3) "consumers"
#       4) (integer) 4
#       5) "pending"
#       6) (integer) 12
#       7) "last-delivered-id"
#       8) "1710328912345-0"
#       9) "entries-read"
#      10) (integer) 84392
#      11) "lag"
#      12) (integer) 280

# 3. Детальная проверка Pending Entries List (PEL) — первые 5 зависших сообщений
kubectl run -it --rm redis-cli-diag --image=redis:7.2-alpine --restart=Never -- \
  redis-cli -h redis-master.storage.svc -p 6379 -a "SecureStreamAuthPass987!" XPENDING telemetry-stream telemetry-workers - + 5
# → 1) 1) "1710328800100-0"
#      2) "worker-pod-6d4f9b8c-x1"
#      3) (integer) 184500
#      4) (integer) 3

# 4. Проверка адреса мастера через Sentinel
kubectl run -it --rm redis-cli-diag --image=redis:7.2-alpine --restart=Never -- \
  redis-cli -h redis-sentinel-0.sentinel.storage.svc -p 26379 SENTINEL get-master-addr-by-name mymaster
# → 1) "10.244.3.45"
#   2) "6379"
```

### Валидация состояния CRD и External Metrics API в Kubernetes

```bash
# 1. Проверка статуса ScaledObject
kubectl get scaledobject redis-list-scaledobject -n processing
# → NAME                      READY   ACTIVE   FALLBACK   AGE
# → redis-list-scaledobject   True    True     False      42m

# 2. Детальный аудит условий ScaledObject
kubectl describe scaledobject redis-list-scaledobject -n processing
# → Status:
# →   Conditions:
# →     Type:            Ready
# →     Status:          True
# →     Reason:          ScaledObjectReady
# →     Type:            Active
# →     Status:          True
# →     Reason:          ScalerActive
# →     Message:         Initializing Scaling Logic

# 3. Проверка автоматически сгенерированного HPA
kubectl get hpa keda-hpa-redis-list-scaledobject -n processing
# → NAME                              REFERENCE                  TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
# → keda-hpa-redis-list-scaledobject  Deployment/queue-worker    142/25 (avg)    1         20        6          42m

# 4. Прямой запрос метрики из KEDA External Metrics API
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/processing/s0-redis-high-priority-jobs" | jq .
# → {
# →   "kind": "ExternalMetricValueList",
# →   "apiVersion": "external.metrics.k8s.io/v1beta1",
# →   "items": [
# →     {
# →       "metricName": "s0-redis-high-priority-jobs",
# →       "metricValues": [
# →         {
# →           "timestamp": "2026-10-13T15:45:00Z",
# →           "value": "142"
# →         }
# →       ]
# →     }
# →   ]
# → }
```

---

## Диагностика и устранение неполадок (Troubleshooting)

### Типичные ошибки скейлера Redis и регламент их устранения

| Симптом / Ошибка | Первопричина | Диагностика | Регламент устранения |
|:---|:---|:---|:---|
| `ScaledObject: Ready=False`, ошибка `i/o timeout` или `connection refused` | Сетевая недоступность порта Redis (6379/26379) из пода `keda-operator`. NetworkPolicy блокирует egress из namespace `keda`. | Проверить логи `keda-operator`: `kubectl logs -n keda -l app=keda-operator`. Проверить DNS-резолвинг. | Создать `NetworkPolicy`, разрешающую egress из подов `keda-operator` в namespace базы данных на порт `6379`/`26379`. |
| `WRONGTYPE Operation against a key holding the wrong kind of value` | Скейлер настроен на `type: redis` (List), а в Redis под этим ключом записан String, Hash, Set или Stream. | Выполнить команду `TYPE <key>` через `redis-cli`. | Проверить имя ключа. Если структура является стримом — изменить тип триггера на `redis-streams`. |
| `NOGROUP No such key '...' or consumer group '...' in XINFO` | Воркеры еще не стартовали и не выполнили `XGROUP CREATE`, поэтому группа отсутствует в Redis. | Запустить `XINFO GROUPS <stream>` через `redis-cli`. | Создать консьюмер-группу вручную перед запуском скейлера: `XGROUP CREATE <stream> <group> $ MKSTREAM`. |
| `NOAUTH Authentication required` или `WRONGPASS invalid username-password pair` | Ошибка учетных данных в `TriggerAuthentication` или несоответствие пользователя Redis ACL. | Проверить логи `keda-operator`. Проверить Secret: `kubectl get secret ... -o yaml`. | Сверить пароль и пользователя. Убедиться, что в Secret параметры закодированы корректно (без лишних `\n`). |
| Метрика зависла на `0`, поды не масштабируются при наличии задач | Неверно указан `databaseIndex` (задачи кладутся в базу `1`, а KEDA опрашивает базу `0`). | Проверить `SELECT <idx>` и `KEYS *` во всех логических базах Redis. | Указать точный индекс базы в параметре `databaseIndex` метаданных триггера. |
| Ошибка Sentinel: `IDONTKNOW: No such master with that name` | Неверно указано имя группы мониторинга в `sentinelMaster`. | Выполнить `SENTINEL masters` на узле Sentinel. | Исправить значение `sentinelMaster` на точное имя из конфигурации Sentinel (`sentinel.conf`). |
| Флаппинг реплик (быстрое переключение `0 -> 10 -> 0 -> 10`) | Слишком короткий `cooldownPeriod` при быстром опустошении очереди воркерами. | Анализ событий пода: `kubectl get events -n processing`. | Увеличить `cooldownPeriod` до 180–300с и настроить `behavior.scaleDown.stabilizationWindowSeconds`. |
| Рост задержек Redis при росте числа ScaledObjects | Сотни ScaledObjects с `pollingInterval: 1` перегружают однопоточный цикл событий Redis. | Проверить команду `INFO commandstats` на Redis (`cmdstat_llen:calls=...`). | Увеличить `pollingInterval` до 15–30 секунд. Разнести очереди по шардам. |

---

## Рекомендации SRE и Best Practices

### 1. Безопасность и минимальные привилегии Redis ACL (Redis 6.0+)

Никогда не используйте суперпользователя `default` с полным доступом к инстансу Redis. Для нужд KEDA создается выделенный технический пользователь по принципу Least Privilege.

**Команда создания ACL в Redis:**

```text
# Для скейлера Redis Lists:
ACL SETUSER keda_scaler on >SuperSecureWorkerPassword123! ~high-priority-jobs ~low-priority-jobs +llen resetchannels

# Для скейлера Redis Streams:
ACL SETUSER keda_stream_scaler on >SecureStreamAuthPass987! ~telemetry-stream +xlen +xinfo +xpending resetchannels
```

**Разрешенные команды:**
- Только `LLEN` для списков.
- Только `XLEN`, `XINFO`, `XPENDING` для стримов.
- Запрет команд изменения (`LPOP`, `LPUSH`, `DEL`, `FLUSHALL`) и административных интерфейсов (`CONFIG`, `DEBUG`).

### 2. Защита однопоточного цикла событий Redis (Event Loop Protection)

Redis исполняет команды в едином потоке (за исключением фонового ввода-вывода).
- **Частота опроса (`pollingInterval`):** Не устанавливайте значение ниже `10` секунд в production-окружениях с большим количеством очередей. Запрос `LLEN` имеет сложность $O(1)$, однако сотни частых TCP-рукопожатий и SSL-сессий могут существенно деградировать latency основного сервиса.
- **Поддержание постоянных соединений:** Начиная с KEDA 2.10+, оператор переиспользует пул соединений к брокерам, но при тысячах объектов рекомендуется консолидировать мониторинг через `redis_exporter` и триггер Prometheus.

### 3. Graceful Termination воркеров

При масштабировании вниз (Scale-Down) Kubernetes отправляет контейнерам сигнал `SIGTERM`. Если воркер выполняет операцию `BRPOP` или обрабатывает длинную задачу:
- Задайте `terminationGracePeriodSeconds` в спецификации Deployment с запасом, превышающим время обработки типичной задачи (например, `60` или `120` секунд).
- В коде приложения перехватывайте `SIGTERM`: прекращайте прием новых задач, завершайте текущую транзакцию, возвращайте сообщение в очередь либо подтверждайте его через `XACK`.

### 4. Мониторинг KEDA и алертинг в Prometheus

KEDA экспортирует собственные метрики, позволяющие контролировать работоспособность скейлеров и предотвращать сбои масштабирования.

**Ключевые Prometheus-метрики KEDA:**
- `keda_scaler_active{scaledObject="...", namespace="..."}` — флаг активности скейлера (`1` — активен, `0` — спит).
- `keda_scaler_errors{scaledObject="...", namespace="..."}` — счетчик ошибок опроса внешнего источника метрик.
- `keda_scaler_metrics_value{scaledObject="...", namespace="..."}` — последнее полученное значение метрики очереди.

**Правила алертинга (PrometheusRule):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: keda-redis-alerts
  namespace: monitoring
spec:
  groups:
    - name: keda.redis.rules
      rules:
        - alert: KedaRedisScalerFailing
          expr: rate(keda_scaler_errors{scaler="redis"}[5m]) > 0
          for: 3m
          labels:
            severity: critical
            team: sre
          annotations:
            summary: "KEDA Redis Scaler failing to poll metrics"
            description: "ScaledObject {{ $labels.scaledObject }} in {{ $labels.namespace }} has errors connecting to Redis for > 3 minutes."

        - alert: RedisQueueCriticallyHigh
          expr: keda_scaler_metrics_value{scaler="redis"} > 1000
          for: 10m
          labels:
            severity: warning
            team: backend
          annotations:
            summary: "Redis Queue processing backlog is growing"
            description: "Queue depth for {{ $labels.scaledObject }} is {{ $value }}, exceeding maximum auto-scaled throughput capacity."
```

---

## Дополнительная информация

### Связанные документы

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура оператора, Metrics Server, фазы активации и жизненный цикл ScaledObject.
* **[KEDA + Kafka: Масштабирование по Consumer Lag](./kafka-keda-scaler.md)** — специфика работы со стриминговыми брокерами и партициями.
* **[KEDA: Практические сценарии](./practical_scenarios.md)** — типовые сценарии масштабирования для RabbitMQ, PostgreSQL, Cron и Prometheus.
* **[KEDA: Операции и эксплуатация](./keda-operations.md)** — регламенты обновления, траблшутинга контроллера и резервного копирования.
* **[KEDA: Тестирование и валидация](./keda-testing-validation.md)** — генерация нагрузочных тестов и валидация HPA поведения.
* **[KEDA: FinOps-гардрейлы](./keda-finops.md)** — экономика масштабирования и оптимизация плотности размещения воркеров.
* **[Паттерн очереди воркеров в Kubernetes](../workers_queue_pattern.md)** — концептуальные шаблоны проектирования надежных систем распределенной обработки задач.
* **[Сертификаты и внутренний mTLS](../../ToolsUtilities/cert_manager/Administration/internal_mtls.md)** — настройка автоматической генерации mTLS-сертификатов через cert-manager.
