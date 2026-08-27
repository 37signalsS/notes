# Strimzi — Kafka Operator для Kubernetes

**Strimzi** — это open-source проект (CNCF), предоставляющий Kubernetes-оператор для развертывания, управления и эксплуатации кластеров **Apache Kafka** в облачных средах. Strimzi упрощает запуск Kafka, которая является сложной распределенной системой с состоянием (stateful), делая процесс управления нативным для Kubernetes.

---

## Определения

- **Cluster Operator:** Основной контроллер, отвечающий за жизненный цикл Kafka, Connect, MirrorMaker и Entity Operator. Управляет StatefulSet'ами брокеров и контроллеров, выполняет rolling updates, обрабатывает изменения Custom Resources.
- **Entity Operator:** Набор контроллеров (Topic Operator и User Operator), управляющих внутренними ресурсами Kafka через Kubernetes API. Обеспечивает декларативное управление топиками и пользователями без прямого доступа к CLI Kafka.
- **Topic Operator:** Компонент Entity Operator, синхронизирующий состояние `KafkaTopic` ресурсов в Kubernetes с реальными топиками в Kafka. Создает, обновляет и удаляет топики согласно манифестам.
- **User Operator:** Компонент Entity Operator, управляющий `KafkaUser` ресурсами. Автоматически создает TLS-сертификаты, учетные данные SASL и ACL, храня их в Kubernetes Secrets.
- **KafkaNodePool:** Custom Resource для управления группами узлов Kafka, позволяющий разделять роли (Controller, Broker) и настраивать разные типы хранилищ для разных групп брокеров. Обязателен для архитектуры KRaft.
- **Cruise Control:** Компонент для автоматического мониторинга и оптимизации распределения данных (ребалансировки) в кластере. Собирает метрики CPU, сети и диска, строит математическую модель и генерирует план перемещения партиций.
- **KRaft (Kafka Raft):** Режим работы Kafka без ZooKeeper, основанный на протоколе консенсуса Raft (KIP-500). Strimzi полностью поддерживает KRaft для новых кластеров. ZooKeeper полностью удален из Kafka начиная с версии 4.0 (март 2025).
- **StrimziPodSet:** Альтернатива StatefulSet, введенная в современных версиях Strimzi для более гибкого управления подами и упрощения операций обновления.
- **Unidirectional Topic Operator (UTO):** Улучшенная версия Topic Operator с повышенной производительностью и надежностью, работающая в одном направлении (Kubernetes → Kafka).

---

## Предварительные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.25+ | Рекомендуется 1.28+ для поддержки новых функций |
| StorageClass | Динамическое  provisioning | Обязательно `volumeBindingMode: WaitForFirstConsumer` для корректной работы с топологией |
| Диск | SSD/NVMe | Для production-нагрузок обязателен быстрый диск с низкой задержью |
| Сеть | CNI с поддержкой NetworkPolicy | Strimzi создает NetworkPolicy для изоляции listener'ов |
| Ресурсы | Минимум 2 GB RAM на брокер | Рекомендуется 4-8 GB RAM и 4 vCPU на брокер для production |

**Проверка совместимости версий:**
```bash
# Проверить версию Kubernetes
kubectl version --short

# Проверить доступные StorageClass
kubectl get storageclass

# Проверить поддержку API Strimzi
kubectl api-resources | grep strimzi.io
```

---

## Основные возможности

Strimzi предоставляет набор контроллеров и [CRD](../Kubernetes/Concepts/kubernetes_crd.md), которые автоматизируют:

- **Декларативное управление:** Описание кластера, топиков и пользователей в виде YAML-манифестов. Полная интеграция с GitOps-процессами (ArgoCD, Flux).
- **Безопасные обновления:** Автоматическое проведение Rolling Updates брокеров при изменении конфигураций или версий образов. Контроль порядка обновления и проверка здоровья после каждого брокера.
- **Безопасность «из коробки»:** Автоматическая генерация и ротация TLS-сертификатов через интеграцию с cert-manager, поддержка SCRAM-SHA-256/512, OAuth и mTLS.
- **Масштабирование и балансировка:** Увеличение количества брокеров изменением `replicas` в KafkaNodePool и автоматическое перераспределение партиций через Cruise Control.
- **Observability:** Встроенные метрики Prometheus через `PodMonitor`, интеграция с Grafana, распространение trace context через OpenTelemetry.
- **Межкластерная репликация:** KafkaMirrorMaker2 для Disaster Recovery и гибридных облачных сценариев.
- **Kafka Connect:** Управление кластерами коннекторов для интеграции с внешними системами (БД, S3, Elasticsearch).

---

## Архитектура и компоненты

### Custom Resources (CR)

| Ресурс | Назначение | Версия API |
| :--- | :--- | :--- |
| **Kafka** | Корневой ресурс, описывающий кластер (версия, листенеры, конфиги). | `kafka.strimzi.io/v1beta2` |
| **KafkaNodePool** | Управление группами узлов (роли, количество, ресурсы). Рекомендуется для новых инсталляций. | `kafka.strimzi.io/v1beta2` |
| **KafkaTopic** | Создание и настройка параметров топиков (партиции, репликация). | `kafka.strimzi.io/v1beta2` |
| **KafkaUser** | Управление пользователями, аутентификацией и ACL. | `kafka.strimzi.io/v1beta2` |
| **KafkaConnect** | Развертывание и масштабирование кластера коннекторов. | `kafka.strimzi.io/v1beta2` |
| **KafkaMirrorMaker2** | Настройка репликации данных между несколькими кластерами. | `kafka.strimzi.io/v1beta2` |
| **KafkaRebalance** | Описание стратегии оптимизации кластера (через Cruise Control). | `kafka.strimzi.io/v1beta2` |
| **KafkaConnector** | Управление отдельными коннекторами без развертывания полного KafkaConnect кластера. | `kafka.strimzi.io/v1beta2` |

### Компоненты оператора

```
┌─────────────────────────────────────────────────────────────┐
│                    Strimzi Cluster Operator                 │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │  Kafka Assembly  │  │  Entity Operator │  │  Cruise     │ │
│  │  Operator        │  │                  │  │  Control    │ │
│  │                  │  │  ┌────────────┐  │  │             │ │
│  │  - Kafka         │  │  │   Topic    │  │  │  - Rebalance│ │
│  │  - KafkaNodePool │  │  │  Operator  │  │  │  - Anomaly  │ │
│  │  - KafkaConnect  │  │  └────────────┘  │  │    Detection│ │
│  │  - MirrorMaker2  │  │  ┌────────────┐  │  │             │ │
│  │                  │  │  │   User     │  │  │             │ │
│  │                  │  │  │  Operator  │  │  │             │ │
│  │                  │  │  └────────────┘  │  │             │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Установка оператора

### Способ 1: Быстрая установка через манифесты (для разработки)

```bash
# Создать namespace для Kafka
kubectl create namespace kafka

# Установить оператор и CRD
kubectl apply -f 'https://strimzi.io/install/latest?namespace=kafka' -n kafka

# Проверить установку
kubectl get pods -n kafka -w
# → strimzi-cluster-operator-7d8f9b6c4-xxxxx   1/1     Running   0          30s
```

### Способ 2: Helm (рекомендуется для production)

```bash
# Добавить репозиторий
helm repo add strimzi https://strimzi.io/charts/
helm repo update

# Установить оператор
helm install strimzi-operator strimzi/strimzi-kafka-operator \
  --namespace kafka \
  --create-namespace \
  --set watchAnyNamespace=true \
  --version 0.44.0

# Проверить установку
kubectl get pods -n kafka
helm list -n kafka
```

### Способ 3: OperatorHub (OLM)

```bash
# Установить через Operator Lifecycle Manager
kubectl create -f https://operatorhub.io/install/strimzi-kafka-operator.yaml
```

**Валидация установки:**
```bash
# Проверить CRD
kubectl get crd | grep strimzi.io
# → kafkabridges.kafka.strimzi.io
# → kafkaconnectors.kafka.strimzi.io
# → kafkaconnects.kafka.strimzi.io
# → kafkamirrormaker2s.kafka.strimzi.io
# → kafkanodepools.kafka.strimzi.io
# → kafkas.kafka.strimzi.io
# → kafkatopics.kafka.strimzi.io
# → kafkarebalances.kafka.strimzi.io
# → kafkausers.kafka.strimzi.io

# Проверить логи оператора
kubectl logs deployment/strimzi-cluster-operator -n kafka --tail=50
```

---

## Практические сценарии

### Сценарий 1: Развертывание кластера в режиме KRaft (Kafka 3.7+/4.0)

В современных версиях Strimzi (0.40+) рекомендуется использовать KRaft и NodePools для гибкого управления узлами. Kafka 4.0 работает исключительно в режиме KRaft.

```yaml
# kafka-cluster.yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaNodePool
metadata:
  name: controller
  labels:
    strimzi.io/cluster: my-cluster
spec:
  replicas: 3
  roles:
    - controller
  storage:
    type: persistent-claim
    size: 50Gi
    class: fast-ssd
  resources:
    requests:
      cpu: "1"
      memory: 4Gi
    limits:
      cpu: "2"
      memory: 6Gi
---
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaNodePool
metadata:
  name: broker
  labels:
    strimzi.io/cluster: my-cluster
spec:
  replicas: 3
  roles:
    - broker
  storage:
    type: persistent-claim
    size: 500Gi
    class: fast-ssd
  resources:
    requests:
      cpu: "4"
      memory: 8Gi
    limits:
      cpu: "8"
      memory: 12Gi
---
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: my-cluster
spec:
  kafka:
    version: 4.0.0
    metadataVersion: 4.0-IV0  # Обязательно для KRaft
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
        type: loadbalancer
        tls: true
    config:
      offsets.topic.replication.factor: 3
      transaction.state.log.replication.factor: 3
      transaction.state.log.min.isr: 2
      default.replication.factor: 3
      min.insync.replicas: 2
      num.partitions: 12
      log.retention.hours: 168
      log.segment.bytes: 1073741824
  entityOperator:
    topicOperator: {}
    userOperator: {}
  cruiseControl: {}  # Включить Cruise Control
```

**Применение и валидация:**
```bash
# Применить конфигурацию
kubectl apply -f kafka-cluster.yaml -n kafka

# Отслеживание создания подов
kubectl get pods -n kafka -w
# → my-cluster-controller-0   1/1   Running   0   1m
# → my-cluster-controller-1   1/1   Running   0   50s
# → my-cluster-controller-2   1/1   Running   0   40s
# → my-cluster-broker-0       1/1   Running   0   30s
# → my-cluster-broker-1       1/1   Running   0   25s
# → my-cluster-broker-2       1/1   Running   0   20s

# Проверить состояние кластера
kubectl get kafka my-cluster -n kafka -o yaml | grep -A 10 "status:"
# → status:
# →   conditions:
# →   - type: Ready
# →     status: "True"

# Проверить метаданные KRaft
kubectl exec -it my-cluster-controller-0 -n kafka -- \
  /opt/kafka/bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9093 describe --status
# → Cluster ID: 5L6g3nShT-eMCtK--X86sw
# → Leader ID: 0
# → ...
```

### Сценарий 2: Управление топиками через KafkaTopic

```yaml
# orders-topic.yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: orders
  labels:
    strimzi.io/cluster: my-cluster
spec:
  partitions: 12
  replicas: 3
  config:
    retention.ms: 604800000  # 7 дней
    min.insync.replicas: 2
    cleanup.policy: delete
    max.message.bytes: 10485760
```

**Валидация:**
```bash
kubectl apply -f orders-topic.yaml -n kafka

# Проверить создание топика
kubectl get kafkatopic orders -n kafka
# → NAME      PARTITIONS   REPLICATION FACTOR   READY
# → orders    12           3                    True

# Проверить в самом Kafka
kubectl exec -it my-cluster-broker-0 -n kafka -- \
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders
# → Topic: orders	TopicId: ...	PartitionCount: 12	ReplicationFactor: 3	Configs: ...
```

### Сценарий 3: Управление пользователями и TLS-аутентификация

```yaml
# app-user.yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaUser
metadata:
  name: app-producer
  labels:
    strimzi.io/cluster: my-cluster
spec:
  authentication:
    type: tls
  authorization:
    type: simple
    acls:
      - resource:
          type: topic
          name: orders
          patternType: literal
        operation: Write
        host: "*"
      - resource:
          type: topic
          name: orders
          patternType: literal
        operation: Describe
        host: "*"
```

**Извлечение сертификатов для приложения:**
```bash
kubectl apply -f app-user.yaml -n kafka

# Проверить создание пользователя
kubectl get kafkauser app-producer -n kafka
# → NAME           AUTHENTICATION   AUTHORIZATION   READY
# → app-producer   tls              simple          True

# Извлечь секреты для подключения
kubectl get secret app-producer -n kafka -o jsonpath='{.data\.crt\.pem}' | base64 -d > client.crt
kubectl get secret app-producer -n kafka -o jsonpath='{.data\.key\.pem}' | base64 -d > client.key
kubectl get secret app-producer -n kafka -o jsonpath='{.data\.ca\.crt}' | base64 -d > ca.crt

# Или использовать готовый секрет для подключения
kubectl get secret app-producer -n kafka -o yaml
```

### Сценарий 4: Автоматическая ребалансировка через Cruise Control

Для оптимизации распределения дискового пространства и CPU необходимо включить Cruise Control в ресурсе `Kafka` и создать объект `KafkaRebalance`.

1. **Включение в Kafka CR:**
    ```yaml
    spec:
      cruiseControl: {} # Использует настройки по умолчанию
    ```

2. **Запуск ребалансировки:**
    ```yaml
    # rebalance.yaml
    apiVersion: kafka.strimzi.io/v1beta2
    kind: KafkaRebalance
    metadata:
      name: my-rebalance
      labels:
        strimzi.io/cluster: my-cluster
    spec:
      goals:
        - CpuCapacityGoal
        - DiskCapacityGoal
        - NetworkInboundCapacityGoal
        - NetworkOutboundCapacityGoal
      skipHardGoalCheck: false
      allowCapacityEstimation: false
      excludedTopics: ".*__.*"  # Исключить внутренние топики
    ```

**Мониторинг прогресса:**
```bash
kubectl apply -f rebalance.yaml -n kafka

# Проверить статус
kubectl get kafkarebalance my-rebalance -n kafka -o yaml | grep -A 20 "status:"
# → status:
# →   conditions:
# →   - type: Ready
# →     status: "True"
# →   optimizationResult: ...

# Наблюдать за планом ребалансировки
kubectl describe kafkarebalance my-rebalance -n kafka
```

### Сценарий 5: Репликация данных (MirrorMaker 2)

Используется для построения гибридных облаков или Disaster Recovery.

```yaml
# mirror-maker.yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaMirrorMaker2
metadata:
  name: my-mirror-maker
spec:
  version: 4.0.0
  replicas: 2
  connectCluster: "target-cluster"
  clusters:
    - alias: "source"
      bootstrapServers: "source-cluster-kafka-bootstrap.source-namespace:9093
      authentication:
        type: tls
        certificateAndKey:
          secretName: source-cluster-clients-ca-cert
          certificate: ca.crt
          key: ca.key
    - alias: "target"
      bootstrapServers: "target-cluster-kafka-bootstrap.target-namespace:9093"
      authentication:
        type: tls
        certificateAndKey:
          secretName: target-cluster-clients-ca-cert
          certificate: ca.crt
          key: ca.key
  mirrors:
    - sourceCluster: "source"
      targetCluster: "target"
      sourceConnector:
        tasksMax: 4
        config:
          replication.factor: 3
          offset-syncs.topic.replication.factor: 3
          sync.topic.acls.enabled: "false"
      checkpointConnector:
        tasksMax: 2
        config:
          checkpoints.topic.replication.factor: 3
      topicsPattern: "orders|payments|inventory"
      groupsPattern: ".*"
```

### Сценарий 6: Kafka Connect для интеграции с внешними системами

```yaml
# kafka-connect.yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaConnect
metadata:
  name: my-connect-cluster
  annotations:
    strimzi.io/use-connector-resources: "true"  # Включить KafkaConnector CRD
spec:
  version: 4.0.0
  replicas: 2
  bootstrapServers: my-cluster-kafka-bootstrap:9093
  tls:
    trustedCertificates:
      - secretName: my-cluster-cluster-ca-cert
        certificate: ca.crt
  config:
    group.id: connect-cluster
    offset.storage.topic: connect-cluster-offsets
    config.storage.topic: connect-cluster-configs
    status.storage.topic: connect-cluster-status
    config.storage.replication.factor: 3
    offset.storage.replication.factor: 3
    status.storage.replication.factor: 3
  resources:
    requests:
      cpu: "1"
      memory: 2Gi
    limits:
      cpu: "2"
      memory: 4Gi
```

**Создание коннектора:**
```yaml
# elasticsearch-sink.yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaConnector
metadata:
  name: elasticsearch-sink
  labels:
    strimzi.io/cluster: my-connect-cluster
spec:
  class: io.confluent.connect.elasticsearch.ElasticsearchSinkConnector
  tasksMax: 2
  config:
    topics: orders
    connection.url: https://elasticsearch:9200
    type.name: _doc
    key.ignore: true
    schema.ignore: true
```

---

## Observability и мониторинг

### Включение метрик Prometheus

Strimzi автоматически создает `PodMonitor` ресурсы для сбора метрик:

```yaml
# Включить мониторинг в Kafka CR
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: my-cluster
spec:
  kafka:
    # ... конфигурация брокера
  entityOperator:
    topicOperator: {}
    userOperator: {}
  cruiseControl: {}
  metricsConfig:
    type: jmxPrometheusExporter
    valueFrom:
      configMapKeyRef:
        name: kafka-metrics
        key: kafka-metrics-config.yml
```

**Конфигурация метрик (ConfigMap):**
```yaml
# kafka-metrics-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kafka-metrics
data:
  kafka-metrics-config.yml: |
    lowercaseOutputName: true
    rules:
    # Специфичные метрики Kafka
    - pattern: 'kafka.server<type=(.+), name=(.+), clientId=(.+)><>Value'
      name: kafka_server_$1_$2
      labels:
        clientId: "$3"
    - pattern: 'kafka.consumer<type=(.+), name=(.+), clientId=(.+)><>Value'
      name: kafka_consumer_$1_$2
      labels:
        clientId: "$3"
    # Общие метрики
    - pattern: 'kafka\.(.+)<type=(.+), name=(.+)><>Value'
      name: kafka_$1_$2_$3
```

### Ключевые метрики для мониторинга

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `kafka_server_under_replicated_partitions` | Количество недореплицированных партиций | > 0 |
| `kafka_controller_active_controller_count` | Количество активных контроллеров | != 1 |
| `kafka_network_request_handler_avg_idle_percent` | Процент простоя обработчиков запросов | < 0.3 |
| `kafka_log_log_size` | Размер логов на брокере | > 80% диска |
| `kafka_consumer_lag` | Отставание консьюмеров | > 10000 |

### Интеграция с Grafana

```bash
# Применить дашборды Strimzi
kubectl apply -f https://raw.githubusercontent.com/strimzi/strimzi-kafka-operator/main/examples/metrics/grafana-dashboards/strimzi-kafka-dashboard.json -n monitoring
kubectl apply -f https://raw.githubusercontent.com/strimzi/strimzi-kafka-operator/main/examples/metrics/grafana-dashboards/strimzi-operators-dashboard.json -n monitoring
```

---

## Troubleshooting

### Типичные проблемы и решения

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Поды брокеров не стартуют | Недостаточно ресурсов или PVC не создан | `kubectl describe pod my-cluster-broker-0 -n kafka` | Проверить StorageClass и ResourceQuota |
| `NotReady` статус Kafka | Ошибка в конфигурации | `kubectl get kafka my-cluster -n kafka -o yaml` | Проверить conditions в status |
| Топики не создаются | Topic Operator не работает | `kubectl logs deployment/strimzi-cluster-operator -n kafka` | Проверить RBAC и логи Entity Operator |
| Высокий Consumer Lag | Медленные консьюмеры или недостаточно партиций | `kubectl run kafka-consumer -ti --image=quay.io/strimzi/kafka:latest-kafka-4.0.0 --rm=true --restart=Never -- /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server my-cluster-kafka-bootstrap:9092 --describe --group my-group` | Масштабировать консьюмеров или оптимизировать обработку |
| Cruise Control не балансирует | Недостаточно данных или кластер уже сбалансирован | `kubectl describe kafkarebalance my-rebalance -n kafka` | Проверить логи Cruise Control и цели |
| TLS-ошибки подключения | Истекшие или неверные сертификаты | `openssl s_client -connect my-cluster-kafka-bootstrap:9093` | Проверить секреты пользователя и CA |

### Диагностические команды

```bash
# Проверить логи оператора
kubectl logs deployment/strimzi-cluster-operator -n kafka --tail=100

# Проверить логи брокера
kubectl logs my-cluster-broker-0 -n kafka --tail=100

# Проверить события кластера
kubectl get events -n kafka --sort-by='.lastTimestamp'

# Проверить состояние всех ресурсов Strimzi
kubectl get kafka,kafkanodepool,kafkatopic,kafkauser,kafkaconnect,kafkamirrormaker2 -n kafka

# Экспортировать полный статус для анализа
kubectl get kafka my-cluster -n kafka -o yaml > kafka-debug.yaml
```

---

## Best Practices

1. **Разделение ролей в KRaft:** Всегда используйте отдельные KafkaNodePool для controller и broker в production. Это предотвращает влияние тяжелой нагрузки брокеров на кворум метаданных.

2. **Выбор хранилища:** Используйте локальные SSD/NVMe с `volumeBindingMode: WaitForFirstConsumer`. Избегайте сетевых хранилищ с высокой задержкой для логов Kafka.

3. **Настройка retention:** Устанавливайте `log.retention.hours` или `log.retention.bytes` в соответствии с бизнес-требованиями. Для больших объемов включите Tiered Storage (Kafka 3.9+).

4. **Мониторинг:** Обязательно настройте алерты на `UnderReplicatedPartitions`, `ActiveControllerCount` и Consumer Lag.

5. **Бэкапы:** Используйте MirrorMaker 2 для межкластерной репликации и Velero для бэкапа Kubernetes-ресурсов и PVC.

6. **Обновления:** При обновлении версии Kafka всегда проверяйте [Strimzi upgrade guide](https://strimzi.io/docs/operators/latest/full/deploying.html). Используйте `inter.broker.protocol.version` для плавной миграции.

7. **Безопасность:** Всегда используйте TLS для внешних listener'ов. Регулярно ротируйте сертификаты через `KafkaUser` с настроенным `expirationSeconds`.

---

## Edge Cases и ограничения

1. **Kafka 4.0 и ZooKeeper:** Kafka 4.0 не поддерживает ZooKeeper. Для миграции с ZooKeeper на KRaft используйте промежуточное обновление до 3.9 с последующей миграцией.

2. **JVM версии:** Kafka 4.0 требует JVM 17+. Убедитесь, что образ Strimzi поддерживает эту версию.

3. **StrimziPodSet vs StatefulSet:** В новых версиях Strimzi можно использовать StrimziPodSet вместо StatefulSet, но это требует тщательного тестирования в вашем окружении.

4. **Мульти-тенантность:** В production рекомендуется использовать отдельные namespace для разных команд с ResourceQuota и NetworkPolicy.

5. **Cruise Control goals:** Некоторые goals могут конфликтовать друг с другом. Начните с базовых целей (CpuCapacityGoal, DiskCapacityGoal) и постепенно добавляйте остальные.

---

## Дополнительная информация

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — основы архитектуры и механизмы KRaft.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — теория, на которой основана работа Cruise Control.
- **[Kubernetes Operators](../Kubernetes/Concepts/kubernetes_operators.md)** — фундаментальные принципы работы паттерна Оператор.
- **[Kafka для мониторинга](./kafka_for_monitoring.md)** — детальный мониторинг метрик и Consumer Lag.

### Ресурсы

- **[Официальный сайт Strimzi](https://strimzi.io/)**
- **[Strimzi Documentation (Latest)](https://strimzi.io/docs/operators/latest/full/)**
- **[Strimzi GitHub](https://github.com/strimzi/strimzi-kafka-operator)**
- **[Strimzi Examples](https://github.com/strimzi/strimzi-kafka-operator/tree/main/examples)**
