# Strimzi — Kafka Operator для Kubernetes

**Актуально для:** Strimzi 1.2.x / Apache Kafka 4.2.x – 4.3.x (KRaft), Kubernetes 1.30+

**Strimzi** — это open-source проект (CNCF), предоставляющий набор Kubernetes-операторов для развертывания, декларативного управления и промышленной эксплуатации кластеров **Apache Kafka** в Kubernetes (включая bare-metal и on-premise инфраструктуры). Strimzi автоматизирует управление распределенным состоянием (stateful), подготовку хранилищ, выпуск и ротацию TLS-сертификатов, ребалансировку данных и rolling updates без деградации доступности.

---

## Определения

- **Cluster Operator:** Главный контроллер Strimzi, отвечающий за жизненный цикл кластера Kafka, KafkaNodePool, Kafka Connect, MirrorMaker 2 и Entity Operator. Отслеживает Custom Resources, управляет подами через StrimziPodSet и реализует безопасные rolling updates.
- **KafkaNodePool:** Кастомный ресурс (`kafka.strimzi.io/v1`), определяющий отдельный пул узлов Kafka с единым набором ролей (`broker`, `controller` или обе), конфигурацией дисков, лимитами ресурсов и правилами планирования (nodeSelector, affinity, tolerations).
- **StrimziPodSet:** Собственный контроллер и ресурс Strimzi, полностью заменивший стандартный Kubernetes StatefulSet. Обеспечивает гранулярное управление каждым отдельным подом брокера (точечные рестарты, независимое изменение размера томов, произвольный выбор брокера при масштабировании вниз).
- **KRaft (Kafka Raft Metadata Mode):** Нативный протокол консенсуса и управления метаданными Kafka без использования ZooKeeper (KIP-500). В Kafka 4.x ZooKeeper полностью удален; кворум метаданных формируется выделенными узлами-контроллерами.
- **Entity Operator:** Составной контроллер, объединяющий Topic Operator и User Operator. Обеспечивает декларативное управление внутренними сущностями Kafka через Kubernetes API.
- **Unidirectional Topic Operator (UTO):** Архитектура Topic Operator с однонаправленной синхронизацией (`Kubernetes → Kafka`). Гарантирует отсутствие конфликтов двусторонней синхронизации и высокую производительность при тысячах топиков.
- **User Operator:** Контроллер для декларативного управления учетными записями (`KafkaUser`), автоматической генерации mTLS-сертификатов, учетных данных SCRAM-SHA и конфигурации списков контроля доступа (ACL).
- **Cruise Control:** Компонент для автоматического сбора метрик утилизации (диск, CPU, сеть), математического моделирования и оптимизации распределения партиций (ребалансировки) в кластере.
- **KafkaRebalance:** Кастомный ресурс для запроса, анализа и применения планов ребалансировки данных через Cruise Control.
- **Rack Awareness:** Механизм распределения реплик партиций по независимым зонам отказа (стойкам, серверам или дата-центрам) путем проброса топологических меток Kubernetes в параметр `broker.rack`.
- **PodDisruptionBudget (PDB):** Механизм Kubernetes, автоматически настраиваемый Strimzi для каждого пула узлов, защищающий кластер от одновременного вывода из строя кворума брокеров или контроллеров при drain узлов.

---

## Архитектура и принцип работы

### Архитектура компонентов оператора

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Strimzi Cluster Operator                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────┐  ┌───────────────────────┐  ┌─────────────────┐  │
│  │ Kafka Assembly        │  │ Entity Operator       │  │ Cruise Control  │  │
│  │ Operator              │  │                       │  │ Integration     │  │
│  │                       │  │  ┌─────────────────┐  │  │                 │  │
│  │  - Kafka CR           │  │  │ Unidirectional  │  │  │  - Rebalance    │  │
│  │  - KafkaNodePool CR   │  │  │ Topic Operator  │  │  │  - Anomaly      │  │
│  │  - KafkaConnect CR    │  │  └─────────────────┘  │  │    Detection    │  │
│  │  - MirrorMaker2 CR    │  │  ┌─────────────────┐  │  │  - Disk Capacity │  │
│  │                       │  │  │ User Operator   │  │  │                 │  │
│  │                       │  │  └─────────────────┘  │  │                 │  │
│  └───────────┬───────────┘  └───────────────────────┘  └────────┬────────┘  │
└──────────────┼──────────────────────────────────────────────────┼───────────┘
               │ Управляет подами и сервисами                     │ Метрики / План
               ▼                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Data & Metadata Plane                              │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ Controller Pool (KafkaNodePool)      │ Broker Pool (KafkaNodePool)          │
│ ┌──────────────┐ ┌──────────────┐    │ ┌──────────────┐ ┌──────────────┐    │
│ │ Controller-0 │ │ Controller-1 │    │ │ Broker-0     │ │ Broker-1     │    │
│ │ (KRaft Quorum) (KRaft Quorum) │    │ │ (Data Logs)  │ │ (Data Logs)  │    │
│ └──────────────┘ └──────────────┘    │ └──────────────┘ └──────────────┘    │
│ Управляется через StrimziPodSet       │ Управляется через StrimziPodSet       │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

### StrimziPodSet против StatefulSet

Исторически Strimzi использовал стандартный Kubernetes `StatefulSet`. Начиная с версий Strimzi 0.35+ и окончательно в линейке 1.x, оператор перешел на собственный контроллер **StrimziPodSet**. 

Причины отказа от StatefulSet в SRE-эксплуатации:
1. **Жесткий порядок обновлений:** StatefulSet обновляет поды строго в обратном порядке индексов (`N-1 → 0`). Если сбой произошел на брокере `0`, перезапустить только его без затрагивания остальных узлов штатно невозможно.
2. **Неизменяемость томов (VolumeClaimTemplates):** В StatefulSet шаблон PVC неизменяем. Нельзя было изменить размер диска отдельного брокера или добавить JBOD-диск без удаления всего StatefulSet.
3. **Неуправляемый Scale-Down:** При уменьшении `replicas` StatefulSet всегда удаляет под с максимальным номером, даже если на нем находятся недореплицированные данные или лидеры критичных партиций.
4. **Контроль доступности:** StrimziPodSet позволяет Cluster Operator проверять статус синхронизации партиций (`UnderReplicatedPartitions == 0`) перед остановкой каждого следующего пода, гарантируя отсутствие потери кворума ISR (`min.insync.replicas`).

### Топология KRaft: разделение ролей

В архитектуре KRaft узлы выполняют две принципиально разные функции:
- **Контроллеры (`roles: [controller]`):** Хранят журнал метаданных кластера в памяти и на диске, участвуют в выборах лидера Raft-кворума. Не обслуживают пользовательский трафик данных. Требуют минимального дискового пространства (10–30 GiB), но критичны к задержкам диска (низкий fsync latency) и стабильности CPU.
- **Брокеры (`roles: [broker]`):** Хранят пользовательские топики, обслуживают чтение/запись продюсеров и консьюмеров, выполняют сжатие и сегментацию логов. Требуют больших объемов дискового пространства и оперативной памяти для системного PageCache.

> [!WARNING]
> Использование совмещенной роли (`roles: [broker, controller]`) допустимо исключительно в тестовых стендах. В production при пиковой нагрузке на брокер (I/O насыщение, GC паузы или OOM) контроллер теряет сердечные сокращения (heartbeats) кворума, что приводит к развалу Raft-метаданных всего кластера.

### Сетевая топология и типы Listener'ов

Strimzi организует двухуровневую адресацию:
1. **Bootstrap Service (ClusterIP):** Единая точка входа для первоначального обнаружения метаданных клиентами.
2. **Per-Broker Services:** Индивидуальные сетевые адреса для каждого брокера, по которым клиенты подключаются к лидерам соответствующих партиций после получения метаданных.

Поддерживаемые типы listener'ов:
- `plain` / `tls` (тип `internal`): Создает стандартные сервисы Kubernetes `ClusterIP` и Headless Service внутри кластера.
- `loadbalancer`: Выделяет внешние IP-адреса через LoadBalancer (в on-premise инфраструктурах работает через MetalLB).
- `nodeport`: Назначает фиксированные порты на узлах Kubernetes (диапазон 30000–32767). Оптимально для bare-metal без программных балансировщиков.
- `ingress`: Маршрутизирует трафик через Ingress-контроллер (например, Ingress-NGINX с TLS SNI passthrough).

---

## Custom Resources (CRD API v1)

Начиная со Strimzi 1.0+, поддерживается исключительно версия API `kafka.strimzi.io/v1` (версии `v1beta2` удалены).

| Ресурс | Назначение |
| :--- | :--- |
| **Kafka** | Корневой ресурс кластера: версии ПО, listeners, общие параметры конфигурации брокеров, TLS CA, метрики. |
| **KafkaNodePool** | Спецификация пула узлов: количество реплик, роли (controller/broker), хранилище, JVM-ресурсы, node affinity. |
| **KafkaTopic** | Декларативное описание топика: количество партиций, фактор репликации, retention, min.insync.replicas. |
| **KafkaUser** | Управление учетными записями: генерация mTLS-сертификатов, паролей SCRAM-SHA, назначение прав ACL. |
| **KafkaRebalance** | Управление задачами балансировки данных через Cruise Control (генерация плана, одобрение, остановка). |
| **KafkaConnect** | Развертывание распределенного кластера Kafka Connect для интеграций с внешними системами. |
| **KafkaConnector** | Управление отдельными экземплярами коннекторов (Source/Sink) через Kubernetes API. |
| **KafkaMirrorMaker2** | Настройка двусторонней или односторонней репликации между несколькими независимыми кластерами. |
| **KafkaBridge** | HTTP/REST шлюз для публикации и вычитки сообщений в Kafka. |

---

## Предварительные требования

| Компонент | Требование | Обоснование SRE / DevOps |
| :--- | :--- | :--- |
| **Kubernetes** | 1.30+ | Поддержка актуального CRD API `v1`, Server-Side Apply и современных Pod Security Standards. |
| **StorageClass** | Динамическое выделение с `WaitForFirstConsumer` | Гарантирует создание тома строго на том узле, где планировщик разместил под с учетом правил Affinity и топологии. |
| **Тип дисков** | Локальные NVMe (Local PV) или блочный Ceph-RBD | Kafka требует высокой скорости последовательной записи и минимального времени `fsync`. Использование NFS строго запрещено. |
| **Оперативная память** | Минимум 8 GB на брокер | 50% выделяется JVM Heap, остальные 50% — ядру Linux под PageCache для нулевого копирования (Zero-Copy) данных. |
| **Сеть** | CNI с поддержкой NetworkPolicy | Изоляция трафика listener'ов и межброкерной репликации от остальных неймспейсов кластера. |

**Проверка готовности кластера:**
```bash
# Проверка версии ядра и API Kubernetes
kubectl version
# → Client Version: v1.31.1
# → Server Version: v1.31.1

# Проверка режима привязки StorageClass (обязательно WaitForFirstConsumer)
kubectl get storageclass -o custom-columns=NAME:.metadata.name,PROVISIONER:.provisioner,BINDINGMODE:.volumeBindingMode
# → NAME                 PROVISIONER                    BINDINGMODE
# → local-nvme (default) kubernetes.io/no-provisioner   WaitForFirstConsumer
# → ceph-block           rook-ceph.rbd.csi.ceph.com     WaitForFirstConsumer
```

---

## Установка оператора

### Способ 1: Установка через Helm (рекомендуется для Production)

Helm-чарт позволяет изолировать оператор, включить строгий Pod Security Standard (Restricted) и настроить отслеживание пространств имен.

```bash
# Добавить официальный репозиторий Strimzi
helm repo add strimzi https://strimzi.io/charts/
helm repo update

# Создать изолированный namespace
kubectl create namespace kafka

# Установить Strimzi Cluster Operator версии 1.2.0
helm install strimzi-operator strimzi/strimzi-kafka-operator \
  --namespace kafka \
  --version 1.2.0 \
  --set watchAnyNamespace=false \
  --set defaultImageRegistry=quay.io

# Проверить статус запуска оператора
kubectl get pods -n kafka -l name=strimzi-cluster-operator
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → strimzi-cluster-operator-6d8b9f7c45-k8w2q   1/1     Running   0          42s
```

### Способ 2: Установка через манифесты выпуска

```bash
# Загрузка и применение манифестов оператора и CRD напрямую из релиза
kubectl create namespace kafka
kubectl apply -f 'https://github.com/strimzi/strimzi-kafka-operator/releases/download/1.2.0/strimzi-cluster-operator-1.2.0.yaml' -n kafka

# Проверка регистрации CRD версии v1
kubectl get crd | grep 'kafka.strimzi.io'
# → kafkabridges.kafka.strimzi.io         2026-10-12T16:00:00Z
# → kafkaconnectors.kafka.strimzi.io       2026-10-12T16:00:00Z
# → kafkaconnects.kafka.strimzi.io          2026-10-12T16:00:00Z
# → kafkamirrormaker2s.kafka.strimzi.io     2026-10-12T16:00:00Z
# → kafkanodepools.kafka.strimzi.io         2026-10-12T16:00:00Z
# → kafkarebalances.kafka.strimzi.io        2026-10-12T16:00:00Z
# → kafkas.kafka.strimzi.io                 2026-10-12T16:00:00Z
# → kafkatopics.kafka.strimzi.io            2026-10-12T16:00:00Z
# → kafkausers.kafka.strimzi.io             2026-10-12T16:00:00Z
```

---

## Практические сценарии

### Сценарий 1: Развертывание отказоустойчивого KRaft-кластера (Production)

Конфигурация включает:
- Отдельный пул контроллеров (3 узла) для кворума Raft.
- Отдельный пул брокеров (3 узла) с Rack Awareness по зонам (`topology.kubernetes.io/zone`).
- Выделение половины оперативной памяти под OS PageCache.
- Включение Cruise Control и Unidirectional Topic Operator.

```yaml
# kafka-production-cluster.yaml
apiVersion: kafka.strimzi.io/v1
kind: KafkaNodePool
metadata:
  name: controller
  namespace: kafka
  labels:
    strimzi.io/cluster: prod-cluster
spec:
  replicas: 3
  roles:
    - controller
  storage:
    type: persistent-claim
    size: 20Gi
    class: local-nvme
    deleteClaim: false
  resources:
    requests:
      cpu: "1000m"
      memory: 2Gi
    limits:
      cpu: "2000m"
      memory: 3Gi
  jvmOptions:
    -Xms: 1536m
    -Xmx: 1536m
  template:
    pod:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: strimzi.io/name
                    operator: In
                    values:
                      - prod-cluster-controller
              topologyKey: "kubernetes.io/hostname"
---
apiVersion: kafka.strimzi.io/v1
kind: KafkaNodePool
metadata:
  name: broker
  namespace: kafka
  labels:
    strimzi.io/cluster: prod-cluster
spec:
  replicas: 3
  roles:
    - broker
  storage:
    type: persistent-claim
    size: 500Gi
    class: local-nvme
    deleteClaim: false
  resources:
    requests:
      cpu: "4000m"
      memory: 8Gi
    limits:
      cpu: "8000m"
      memory: 12Gi
  jvmOptions:
    -Xms: 4096m
    -Xmx: 4096m
    -XX:
      InitiatingHeapOccupancyPercent: "45"
      G1ReservePercent: "15"
  template:
    pod:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: "topology.kubernetes.io/zone"
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              strimzi.io/name: prod-cluster-broker
---
apiVersion: kafka.strimzi.io/v1
kind: Kafka
metadata:
  name: prod-cluster
  namespace: kafka
spec:
  kafka:
    version: 4.3.0
    metadataVersion: 4.3-IV0
    rack:
      topologyKey: "topology.kubernetes.io/zone"
    listeners:
      - name: plain
        port: 9092
        type: internal
        tls: false
      - name: tls
        port: 9093
        type: internal
        tls: true
        authentication:
          type: tls
      - name: external
        port: 9094
        type: nodeport
        tls: true
        authentication:
          type: scram-sha-512
    config:
      default.replication.factor: 3
      min.insync.replicas: 2
      offsets.topic.replication.factor: 3
      offsets.topic.num.partitions: 50
      transaction.state.log.replication.factor: 3
      transaction.state.log.min.isr: 2
      log.retention.hours: 168
      log.segment.bytes: 1073741824
      log.cleanup.policy: delete
      auto.create.topics.enable: false
      unclean.leader.election.enable: false
  entityOperator:
    topicOperator: {}
    userOperator: {}
  cruiseControl: {}
```

**Применение и валидация развертывания:**
```bash
kubectl apply -f kafka-production-cluster.yaml

# Наблюдение за созданием подов пулов
kubectl get pods -n kafka -l strimzi.io/cluster=prod-cluster
# → NAME                               READY   STATUS    RESTARTS   AGE
# → prod-cluster-controller-0          1/1     Running   0          2m
# → prod-cluster-controller-1          1/1     Running   0          100s
# → prod-cluster-controller-2          1/1     Running   0          70s
# → prod-cluster-broker-0              1/1     Running   0          60s
# → prod-cluster-broker-1              1/1     Running   0          40s
# → prod-cluster-broker-2              1/1     Running   0          20s
# → prod-cluster-entity-operator-xxx   2/2     Running   0          15s
# → prod-cluster-cruise-control-xxx    1/1     Running   0          15s

# Проверка условий готовности кластера
kubectl get kafka prod-cluster -n kafka -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → True

# Проверка статуса кворума контроллеров KRaft
kubectl exec -it prod-cluster-controller-0 -n kafka -c kafka -- \
  bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9093 describe --status
# → ClusterId:              Y0vB6e1aTu-U7P98y1LzQw
# → LeaderId:               0
# → LeaderEpoch:            1
# → HighWatermark:          2481
# → MaxFollowerLag:         0
# → CurrentVoters:          [0,1,2]
```

---

### Сценарий 2: Декларативное управление топиками (KafkaTopic)

Unidirectional Topic Operator (UTO) непрерывно синхронизирует состояние манифестов в Kafka. Любые попытки изменить топик вне GitOps перезаписываются оператором согласно манифесту.

```yaml
# orders-events-topic.yaml
apiVersion: kafka.strimzi.io/v1
kind: KafkaTopic
metadata:
  name: orders-events
  namespace: kafka
  labels:
    strimzi.io/cluster: prod-cluster
spec:
  partitions: 12
  replicas: 3
  config:
    min.insync.replicas: 2
    retention.ms: 604800000          # 7 суток
    segment.bytes: 536870912         # 512 MiB
    cleanup.policy: delete
    compression.type: zstd
    max.message.bytes: 2097152       # 2 MiB
```

**Применение и диагностика топика:**
```bash
kubectl apply -f orders-events-topic.yaml

# Проверка статуса ресурса в Kubernetes
kubectl get kafkatopic orders-events -n kafka
# → NAME            CLUSTER        PARTITIONS   REPLICATION FACTOR   READY
# → orders-events   prod-cluster   12           3                    True

# Проверка параметров в самой Kafka через внутренний CLI
kubectl exec -it prod-cluster-broker-0 -n kafka -c kafka -- \
  bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders-events
# → Topic: orders-events	TopicId: 9r8_o3W2RiqsC_zP...	PartitionCount: 12	ReplicationFactor: 3	Configs: min.insync.replicas=2,cleanup.policy=delete,segment.bytes=536870912,retention.ms=604800000,compression.type=zstd
```

---

### Сценарий 3: Управление пользователями, аутентификацией и ACL (KafkaUser)

Strimzi автоматизирует генерацию учетных данных. Для `tls` выпускаются клиентские сертификаты от внутреннего CA кластера; для `scram-sha-512` генерируются криптостойкие пароли.

```yaml
# billing-consumer-user.yaml
apiVersion: kafka.strimzi.io/v1
kind: KafkaUser
metadata:
  name: billing-service
  namespace: kafka
  labels:
    strimzi.io/cluster: prod-cluster
spec:
  authentication:
    type: tls
  authorization:
    type: simple
    acls:
      - resource:
          type: topic
          name: orders-events
          patternType: literal
        operations:
          - Read
          - Describe
        host: "*"
      - resource:
          type: group
          name: billing-group
          patternType: prefix
        operations:
          - Read
        host: "*"
```

**Извлечение клиентских сертификатов для подключения сервиса:**
```bash
kubectl apply -f billing-consumer-user.yaml

# Проверка готовности пользователя
kubectl get kafkauser billing-service -n kafka
# → NAME              AUTHENTICATION   AUTHORIZATION   READY
# → billing-service   tls              simple          True

# Извлечение закрытого ключа, клиентского сертификата и CA кластера
kubectl get secret billing-service -n kafka -o jsonpath='{.data.user\.crt}' | base64 -d > user.crt
kubectl get secret billing-service -n kafka -o jsonpath='{.data.user\.key}' | base64 -d > user.key
kubectl get secret prod-cluster-cluster-ca-cert -n kafka -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt

# Проверка валидности сертификата
openssl x509 -in user.crt -noout -subject -issuer
# → subject=CN = billing-service
# → issuer=O = io.strimzi, CN = cluster-ca v0
```

---

### Сценарий 4: Двухфазная ребалансировка через Cruise Control (KafkaRebalance)

Процесс ребалансировки в Strimzi спроектирован так, чтобы исключить случайное создание паразитной сетевой нагрузки в пиковые часы:
1. Создание ресурса `KafkaRebalance` запускает расчет математической модели и генерацию плана.
2. SRE анализирует предложенный объем перемещаемых данных (`optimizationResult`).
3. SRE утверждает выполнение плана через аннотацию.

```yaml
# cluster-disk-rebalance.yaml
apiVersion: kafka.strimzi.io/v1
kind: KafkaRebalance
metadata:
  name: disk-rebalance
  namespace: kafka
  labels:
    strimzi.io/cluster: prod-cluster
spec:
  goals:
    - RackAwareGoal
    - DiskCapacityGoal
    - CpuCapacityGoal
    - NetworkInboundCapacityGoal
    - NetworkOutboundCapacityGoal
    - ReplicaDistributionGoal
  skipHardGoalCheck: false
  concurrentPartitionMovementsPerBroker: 5
  concurrentLeaderMovements: 20
  replicationThrottle: 50000000   # Ограничение скорости репликации: 50 MB/s
```

**Управление жизненным циклом ребалансировки:**
```bash
kubectl apply -f cluster-disk-rebalance.yaml

# 1. Проверить статус генерации плана (ожидание статуса ProposalReady)
kubectl get kafkarebalance disk-rebalance -n kafka
# → NAME             CLUSTER        PENDINGPROPOSAL   PROPOSALREADY   REBALANCING   READY
# → disk-rebalance   prod-cluster                     True

# 2. Анализ предложенного плана перемещения данных
kubectl describe kafkarebalance disk-rebalance -n kafka | grep -A 10 "Optimization Result:"
# → Optimization Result:
# →   Data To Move MB:                   42810
# →   Excluded Brokers:                  []
# →   Excluded Topics:                   []
# →   Num Intra Broker Partition Movements: 0
# →   Num Leader Movements:              14
# →   Num Partition Movements:           38
# →   On-Demand Balancedness Score After: 91.4

# 3. Одобрение выполнения плана ребалансировки SRE-инженером
kubectl annotate kafkarebalance disk-rebalance strimzi.io/rebalance=approve -n kafka --overwrite
# → kafkarebalance.kafka.strimzi.io/disk-rebalance annotated

# 4. Отслеживание процесса перемещения
kubectl get kafkarebalance disk-rebalance -n kafka -w
# → disk-rebalance   prod-cluster                     False           True
# → disk-rebalance   prod-cluster                                                   True

# При необходимости экстренной остановки процесса:
# kubectl annotate kafkarebalance disk-rebalance strimzi.io/rebalance=stop -n kafka --overwrite
```

---

### Сценарий 5: Управляемые Rolling Updates и регламентное обслуживание

В промышленных средах автоматический рестарт подов во время дневной пиковой нагрузки недопустим. Strimzi предоставляет два механизма контроля: окна обслуживания и ручные триггеры перезапуска.

#### Окна обслуживания (Maintenance Windows)
```yaml
# Добавляется в спецификацию Kafka CR
spec:
  maintenanceTimeWindows:
    - "* * 01-04 * * ?"    # Ежедневно с 01:00 до 04:00 UTC
    - "* * * ? * SAT,SUN"  # Круглосуточно в выходные дни
```
Оператор будет накапливать конфигурационные изменения, требующие рестарта брокеров, и применит их строго в указанный интервал.

#### Точечный перезапуск конкретного брокера (Manual Rolling Update)
Если брокер демонстрирует утечку дескрипторов или высокую задержку диска, SRE может инициировать его перезапуск без изменения манифестов:

```bash
# Перезапуск одного конкретного пода брокера
kubectl annotate pod prod-cluster-broker-1 strimzi.io/manual-rolling-update=true -n kafka
# → pod/prod-cluster-broker-1 annotated

# Проверка логов оператора: безопасное ожидание синхронизации партиций перед перезапуском
kubectl logs deployment/strimzi-cluster-operator -n kafka --tail=30 | grep -i "rolling pod"
# → 2026-10-12 16:30:10 INFO AbstractPodRollingController: Rolling pod prod-cluster-broker-1
# → 2026-10-12 16:30:45 INFO AbstractPodRollingController: Pod prod-cluster-broker-1 is ready and all partitions are in-sync
```

#### Экстренная заморозка оператора (Pause Reconciliation)
В случае аварии, когда действия оператора могут усугубить сбой:
```bash
# Приостановить все действия оператора над кластером
kubectl annotate kafka prod-cluster strimzi.io/pause-reconciliation="true" -n kafka
# Возобновить штатную работу
kubectl annotate kafka prod-cluster strimzi.io/pause-reconciliation- -n kafka
```

---

### Сценарий 6: Масштабирование пула и расширение хранилища (Day-2 Operations)

#### Онлайн-расширение дисков
Благодаря `StrimziPodSet` размер тома меняется редактированием манифеста `KafkaNodePool` (при условии поддержки `allowVolumeExpansion: true` в StorageClass):

```yaml
# Изменение размера в spec.storage.size
spec:
  storage:
    type: persistent-claim
    size: 1000Gi # Было 500Gi
```
Оператор обновит размер в PVC, CSI-драйвер выполнит расширение файловой системы в работающем поде без его рестарта.

#### Горизонтальное масштабирование пула брокеров
1. Увеличение числа брокеров в `KafkaNodePool`:
   ```bash
   kubectl scale kafkanodepool broker --replicas=5 -n kafka
   ```
2. Новый брокер стартует пустым. Для распределения нагрузки на него запускается генерация ребаланс-плана через `KafkaRebalance` (см. Сценарий 4).

---

### Сценарий 7: Межкластерная репликация (MirrorMaker 2)

Используется для создания независимого Disaster Recovery кластера в удаленном ЦОД.

```yaml
# kafka-mirror-maker-dr.yaml
apiVersion: kafka.strimzi.io/v1
kind: KafkaMirrorMaker2
metadata:
  name: dr-mirror-maker
  namespace: kafka
spec:
  version: 4.3.0
  replicas: 2
  connectCluster: "backup-cluster"
  clusters:
    - alias: "primary"
      bootstrapServers: "prod-cluster-kafka-bootstrap.kafka.svc.cluster.local:9093"
      authentication:
        type: tls
        certificateAndKey:
          secretName: mm2-primary-credentials
          certificate: user.crt
          key: user.key
      tls:
        trustedCertificates:
          - secretName: prod-cluster-cluster-ca-cert
            certificate: ca.crt
    - alias: "backup"
      bootstrapServers: "backup-cluster-kafka-bootstrap.dr-kafka.svc.cluster.local:9093"
      authentication:
        type: tls
        certificateAndKey:
          secretName: mm2-backup-credentials
          certificate: user.crt
          key: user.key
      tls:
        trustedCertificates:
          - secretName: backup-cluster-cluster-ca-cert
            certificate: ca.crt
  mirrors:
    - sourceCluster: "primary"
      targetCluster: "backup"
      sourceConnector:
        tasksMax: 4
        config:
          replication.factor: 3
          offset-syncs.topic.replication.factor: 3
          sync.topic.acls.enabled: "false"
          refresh.topics.interval.seconds: 60
      checkpointConnector:
        tasksMax: 2
        config:
          checkpoints.topic.replication.factor: 3
          sync.group.offsets.enabled: "true"
          sync.group.offsets.interval.seconds: 10
      topicsPattern: "orders-.*|payments-.*"
      groupsPattern: ".*"
```

---

### Сценарий 8: Управление кластером Kafka Connect и коннекторами

Декларативное развертывание распределенного конвейера интеграции баз данных без прямого обращения к REST API коннекторов.

```yaml
# kafka-connect-pipeline.yaml
apiVersion: kafka.strimzi.io/v1
kind: KafkaConnect
metadata:
  name: prod-connect
  namespace: kafka
  annotations:
    strimzi.io/use-connector-resources: "true"
spec:
  version: 4.3.0
  replicas: 3
  bootstrapServers: prod-cluster-kafka-bootstrap:9093
  tls:
    trustedCertificates:
      - secretName: prod-cluster-cluster-ca-cert
        certificate: ca.crt
  config:
    group.id: prod-connect-group
    offset.storage.topic: connect-offsets
    config.storage.topic: connect-configs
    status.storage.topic: connect-status
    config.storage.replication.factor: 3
    offset.storage.replication.factor: 3
    status.storage.replication.factor: 3
  resources:
    requests:
      cpu: "1000m"
      memory: 2Gi
    limits:
      cpu: "2000m"
      memory: 4Gi
---
apiVersion: kafka.strimzi.io/v1
kind: KafkaConnector
metadata:
  name: postgres-cdc-source
  namespace: kafka
  labels:
    strimzi.io/cluster: prod-connect
spec:
  class: io.debezium.connector.postgresql.PostgresConnector
  tasksMax: 2
  config:
    database.hostname: "postgres.db.internal"
    database.port: "5432"
    database.user: "debezium"
    database.password: "${secrets:kafka/db-credentials:password}"
    database.dbname: "production"
    database.server.name: "prod_pg"
    table.include.list: "public.orders,public.payments"
    plugin.name: "pgoutput"
```

---

## Операции и команды

### Сводная таблица команд администратора

| Категория | Команда | Назначение |
| :--- | :--- | :--- |
| **Инспекция** | `kubectl get kafka,kafkanodepool,kafkatopic -n kafka` | Просмотр состояния всех ключевых сущностей кластера. |
| **Диагностика** | `kubectl get kafka <name> -n kafka -o yaml` | Проверка секции `status.conditions` и текущих проблем. |
| **Рестарт** | `kubectl annotate pod <pod> strimzi.io/manual-rolling-update=true` | Инициация безопасного rolling update одного пода. |
| **Ребалансировка** | `kubectl annotate kafkarebalance <name> strimzi.io/rebalance=approve` | Утверждение выполнения плана Cruise Control. |
| **Остановка ребаланса**| `kubectl annotate kafkarebalance <name> strimzi.io/rebalance=stop` | Экстренное прерывание перемещения данных. |
| **Заморозка** | `kubectl annotate kafka <name> strimzi.io/pause-reconciliation=true` | Отключение вмешательства оператора на время аварии. |
| **KRaft кворум** | `kafka-metadata-quorum.sh describe --status` | Проверка состояния лидеров и отставания контроллеров. |

### Практические команды с ожидаемым выводом

```bash
# 1. Проверка состояния всех узлов пулов StrimziPodSet
kubectl get strimzipodset -n kafka
# → NAME                    PODS   READY PODS   CURRENT PODS   AGE
# → prod-cluster-broker     3      3            3              5d
# → prod-cluster-controller 3      3            3              5d

# 2. Быстрый аудит недореплицированных топиков в кластере
kubectl exec -it prod-cluster-broker-0 -n kafka -c kafka -- \
  bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --under-replicated-partitions
# → (пустой вывод означает полное соответствие ISR заданным репликам)

# 3. Проверка потребительских лагов (Consumer Lag)
kubectl exec -it prod-cluster-broker-0 -n kafka -c kafka -- \
  bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group billing-group
# → GROUP           TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST
# → billing-group   orders-events   0          104857          104860          3               client-1_xxx    /10.244.2.14
# → billing-group   orders-events   1          209411          209411          0               client-2_xxx    /10.244.3.28

# 4. Просмотр текущих сертификатов кластерного CA
kubectl get secret prod-cluster-cluster-ca-cert -n kafka -o jsonpath='{.data.ca\.crt}' | base64 -d | openssl x509 -noout -dates
# → notBefore=Oct 12 12:00:00 2026 GMT
# → notAfter=Oct 12 12:00:00 2027 GMT
```

---

## Observability и мониторинг

### Экспорт метрик Prometheus через JMX Exporter

Strimzi развертывает Prometheus JMX Exporter агент внутри контейнера брокера:

```yaml
# metrics-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kafka-metrics-config
  namespace: kafka
data:
  kafka-metrics-config.yml: |
    lowercaseOutputName: true
    rules:
      - pattern: "kafka.server<type=ReplicaManager, name=(.+)><>(Value|OneMinuteRate)"
        name: "kafka_server_replicamanager_$1"
      - pattern: "kafka.controller<type=KafkaController, name=(.+)><>Value"
        name: "kafka_controller_$1"
      - pattern: "kafka.network<type=RequestMetrics, name=RequestsPerSec, request=(.+)><>OneMinuteRate"
        name: "kafka_network_request_rate"
        labels:
          request: "$1"
      - pattern: "kafka.log<type=Log, name=Size, topic=(.+), partition=(.+)><>Value"
        name: "kafka_log_partition_size_bytes"
        labels:
          topic: "$1"
          partition: "$2"
```

### Ключевые метрики SRE и пороговые значения алертов

| Метрика | Значение / Источник | Критический порог | Действие SRE |
| :--- | :--- | :--- | :--- |
| `kafka_server_replicamanager_underreplicatedpartitions` | Количество недореплицированных партиций | `> 0` дольше 3 минут | Проверить состояние дисков, сеть и логи брокеров. |
| `kafka_server_replicamanager_undermin_isrpartitioncount` | Партиции, у которых ISR ниже `min.insync.replicas` | `> 0` | Критическая авария. Запись в топики заблокирована продюсерам с `acks=all`. |
| `kafka_controller_activecontrollercount` | Количество активных контроллеров KRaft | `!= 1` | Сбой кворума Raft или рассинхронизация контроллеров. |
| `kafka_network_request_handler_avg_idle_percent` | Процент простоя обработчиков запросов | `< 0.2` (20%) | Насыщение пула I/O или сетевых потоков. Масштабировать CPU. |
| `container_fs_usage_bytes / container_fs_limit_bytes` | Заполнение дискового тома брокера | `> 85%` | Срочно запустить ребалансировку или расширить PVC. |
| `kafka_consumergroup_lag` | Отставание группы консьюмеров | `> 50000` | Консьюмер не успевает обрабатывать поток или завис. |

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Типичные аварийные ситуации и алгоритмы решения

#### 1. Брокер застрял в `CrashLoopBackOff` из-за переполнения тома PVC
- **Симптом:** Под брокера падает при старте, в логах: `java.io.IOException: No space left on device`.
- **Причина:** Объем данных превысил размер PVC; Kafka не может инициализировать индексный файл логов.
- **Решение:**
  1. Отредактировать манифест `KafkaNodePool`, увеличив `spec.storage.size` (например, с `500Gi` до `700Gi`).
  2. Применить манифест. Если StorageClass поддерживает онлайн-расширение, дождаться обновления емкости.
  3. Если том не расширяется при выключенном поде, временно увеличить квоту диска на уровне CSI-провайдера. После старта брокера настроить более агрессивный retention (`log.retention.hours`).

#### 2. Зависание Rolling Update оператором
- **Симптом:** Оператор перезапустил один брокер и остановился. В логах оператора: `Partitions are not in sync, waiting before rolling next pod`.
- **Причина:** Новый брокер восстанавливается и вычитывает недостающие реплики. Оператор соблюдает безопасность данных и отказывается выводить следующий брокер из строя, пока `UnderReplicatedPartitions > 0`.
- **Решение:**
  1. Не прерывать работу оператора принудительным удалением подов!
  2. Проверить сетевую пропускную способность между брокерами и задержку дисков.
  3. Дождаться синхронизации реплик. Если брокер не может синхронизироваться из-за троттлинга репликации Cruise Control, временно снять ограничение: `kafka-configs.sh --alter --entity-type brokers --entity-name <id> --delete-config leader.replication.throttled.rate`.

#### 3. Нарушение кворума KRaft контроллеров (Quorum Loss)
- **Симптом:** Кластер Kafka не принимает запросы на создание топиков, брокеры циклично логируют `NOT_CONTROLLER` или `LEADER_RECOVERY`.
- **Причина:** Недоступно большинство узлов пула контроллеров (например, 2 из 3 контроллеров отключились из-за сбоя хостов).
- **Решение:**
  1. Проверить статус подов пула контроллеров: `kubectl get pods -n kafka -l strimzi.io/name=prod-cluster-controller`.
  2. Проверить события планировщика: `kubectl describe pod prod-cluster-controller-X -n kafka`.
  3. Убедиться, что диски контроллеров смонтированы без ошибок read-only.
  4. При повреждении кворума выполнить диагностику через `kafka-metadata-quorum.sh describe --status`.

#### 4. Невозможность планирования подов из-за StorageClass `Immediate`
- **Симптом:** Поды брокеров остаются в статусе `Pending`, PVC в статусе `Bound`, но `pod.status`: `1 node(s) had volume node affinity conflict`.
- **Причина:** StorageClass использовал режим `volumeBindingMode: Immediate`. Том PV был создан на произвольной ноде, где размещение брокера запрещено правилами `podAntiAffinity` или `topologySpreadConstraints`.
- **Решение:**
  1. Пересоздать StorageClass с обязательным параметром `volumeBindingMode: WaitForFirstConsumer`.
  2. Пересоздать PVC кластера.

#### 5. Unidirectional Topic Operator (UTO) сообщает о конфликтах
- **Симптом:** В статусе `KafkaTopic` условие `Ready: False`, причина `InvalidResourceException`.
- **Причина:** Запрошена конфигурация топика с `partitions < current_partitions` (Kafka не поддерживает уменьшение количества партиций) либо `min.insync.replicas > replicas`.
- **Решение:**
  1. Привести манифест `KafkaTopic` к допустимым параметрам.
  2. Проверить логи: `kubectl logs deployment/strimzi-cluster-operator -n kafka -c topic-operator`.

---

## Рекомендации и лучшие практики (Best Practices)

### 1. Надежность данных и расчет кворума
- **Фактор репликации:** Для production-топиков всегда устанавливать `replication.factor: 3` и `min.insync.replicas: 2`. Продюсеры критичных систем обязаны отправлять сообщения с `acks=all` (`acks=-1`).
- **Защита от потери данных:** Всегда выключать `unclean.leader.election.enable: false`. Ни при каких обстоятельствах не назначать лидером несинхронизированную реплику.

### 2. Память: JVM Heap против OS PageCache
- Kafka — это система с интенсивным вводом-выводом, работающая через системный вызов `sendfile` (Zero-Copy) напрямую из PageCache ядра Linux.
- **Золотое правило:** Выделяйте JVM Heap (`-Xms`, `-Xmx`) не более чем на 40–50% от лимита оперативной памяти контейнера. Оставшиеся 50–60% памяти должны быть свободны от JVM для использования ядром Linux под кэш страниц диска.
- Никогда не настраивайте `Xmx` равным `resources.limits.memory` — это приведет к деградации пропускной способности чтения и постоянным сбросам страниц на диск.

### 3. Топология и размещение узлов
- **Anti-Affinity:** Разносите контроллеры по разным физическим серверам (`topologyKey: "kubernetes.io/hostname"`).
- **Topology Spread Constraints:** Разносите брокеры равномерно по стойкам или зонам доступности (`topologyKey: "topology.kubernetes.io/zone"`).
- **Rack Awareness:** Включайте `spec.kafka.rack.topologyKey`, чтобы Kafka автоматически учитывала физическое расположение брокеров при распределении реплик каждой партиции.

### 4. Дисковая подсистема
- Используйте исключительно быстрые SSD/NVMe диски с низким latency записи.
- Обязательно используйте StorageClass с `volumeBindingMode: WaitForFirstConsumer`.
- Запрещается использовать NFS, SMB или CIFS файловые системы для хранения логов Kafka (несовместимость с POSIX lock и механизмом сегментации логов).

### 5. Обновления версий (Upgrades)
- Перед повышением версии оператора или Kafka ознакомьтесь с [Strimzi Upgrade Guide](https://strimzi.io/docs/operators/1.2.0/deploying.html#assembly-upgrade-str).
- В KRaft обновление версии ПО выполняется последовательно: сначала обновляется образ оператора, затем версия брокеров в манифесте `Kafka`, и только после успешного завершения rolling update повышается `metadataVersion`.

---

## Ограничения и особенности эксплуатации

1. **Полное отсутствие ZooKeeper:** Kafka 4.x и актуальные версии Strimzi 1.x не поддерживают ZooKeeper. Все кластеры развертываются исключительно в режиме KRaft.
2. **Неизменяемость числа контроллеров:** Рекомендуемый размер кворума контроллеров — ровно 3 или 5 узлов. Четное количество контроллеров не повышает отказоустойчивость из-за формулы кворума `(N/2) + 1`.
3. **Уменьшение числа партиций:** Протокол Apache Kafka не поддерживает уменьшение количества партиций существующего топика. Если топик создан с 24 партициями, уменьшить их до 12 через `KafkaTopic` невозможно (потребуется создание нового топика и миграция данных).
4. **Принудительный scale-down без ребалансировки:** Простое уменьшение `replicas` в пуле брокеров без предварительного переноса партиций приведет к потере реплик и недоступности данных, если удаленный брокер содержал единственные оставшиеся копии партиций.

---

## Дополнительная информация

### См. также
- **[Опыт эксплуатации сотен кластеров Kafka в Kubernetes](./kafka-k8s-operations-experience.md)** — архитектура мульти-кластерной инфраструктуры, тиры и опыт MindBox.
- **[Обзор Apache Kafka](./kafka_overview.md)** — базовые концепции, архитектура топиков, партиций и протокол KRaft.
- **[Партиционирование и балансировка нагрузки](./partitioning_and_balancing.md)** — алгоритмы партиционирования, математическая модель и архитектура Cruise Control.
- **[Kafka Connect в Production](./kafka_connect_production.md)** — распределенный режим, архитектура воркеров и Single Message Transformations.
- **[Диагностика и устранение неисправностей Kafka](./kafka_troubleshooting_playbook.md)** — практический плейбук по локализации сетевых задержек, сбоев брокеров и лагов консьюмеров.
- **[Kubernetes Operators](../Kubernetes/Concepts/kubernetes_operators.md)** — принципы работы операторов, циклы согласования (reconciliation loop) и контроллеры.
- **[Custom Resource Definitions (CRD)](../Kubernetes/Concepts/kubernetes_crd.md)** — устройство и версии пользовательских ресурсов в Kubernetes.
- **[StatefulSet: Local PV против CSI](../Kubernetes/Base/StatefulSet/statefulset_local_pv_vs_csi.md)** — сравнительный анализ производительности и надежности локальных дисков и блочных хранилищ.
- **[Kubernetes Scheduling & Affinity](../Kubernetes/Scheduling/affinity.md)** — правила размещения рабочих нагрузок с учетом топологии и зон отказа.

### Внешние ресурсы
- **[Официальный сайт проекта Strimzi](https://strimzi.io/)**
- **[Документация Strimzi 1.2.0 (Latest)](https://strimzi.io/docs/operators/1.2.0/full/)**
- **[Репозиторий Strimzi на GitHub](https://github.com/strimzi/strimzi-kafka-operator)**
- **[Примеры манифестов Strimzi](https://github.com/strimzi/strimzi-kafka-operator/tree/main/examples)**
