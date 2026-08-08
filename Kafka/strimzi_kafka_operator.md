# Strimzi — Kafka Operator для Kubernetes

**Strimzi** — это open-source проект, предоставляющий Kubernetes-оператор для развертывания, управления и эксплуатации кластеров **Apache Kafka** в облачных средах. Strimzi упрощает запуск Kafka, которая является сложной распределенной системой с состоянием (stateful), делая процесс управления нативным для Kubernetes.

---

## Определения

- **Cluster Operator:** Основной контроллер, отвечающий за жизненный цикл Kafka, Connect, MirrorMaker и Entity Operator.
- **Entity Operator:** Набор контроллеров (Topic и User), управляющих внутренними ресурсами Kafka через Kubernetes API.
- **KafkaNodePool:** Custom Resource для управления группами узлов Kafka, позволяющий разделять роли (Controller, Broker) и настраивать разные типы хранилищ для разных групп брокеров.
- **Cruise Control:** Компонент для автоматического мониторинга и оптимизации распределения данных (ребалансировки) в кластере.
- **KRaft (Kafka Raft):** Режим работы Kafka без ZooKeeper. Strimzi полностью поддерживает KRaft для новых кластеров.

---

## Основные возможности

Strimzi предоставляет набор контроллеров и [CRD](../Kubernetes/Concepts/kubernetes_crd.md), которые автоматизируют:

- **Декларативное управление:** Описание кластера, топиков и пользователей в виде YAML-манифестов.
- **Безопасные обновления:** Автоматическое проведение Rolling Updates брокеров при изменении конфигураций или версий образов.
- **Безопасность «из коробки»:** Автоматическая генерация и ротация TLS-сертификатов, поддержка SCRAM-SHA и OAuth.
- **Масштабирование и балансировка:** Увеличение количества брокеров и автоматическое перераспределение партиций через Cruise Control.
- **Observability:** Интеграция с Prometheus (через `PodMonitor`) и Grafana.

---

## Архитектура и компоненты

### Custom Resources (CR)

| Ресурс | Назначение |
| :--- | :--- |
| **Kafka** | Корневой ресурс, описывающий кластер (версия, листенеры, конфиги). |
| **KafkaNodePool** | Управление группами узлов (роли, количество, ресурсы). Рекомендуется для новых инсталляций. |
| **KafkaTopic** | Создание и настройка параметров топиков (партиции, репликация). |
| **KafkaUser** | Управление пользователями, аутентификацией и ACL. |
| **KafkaConnect** | Развертывание и масштабирование кластера коннекторов. |
| **KafkaMirrorMaker2** | Настройка репликации данных между несколькими кластерами. |
| **KafkaRebalance** | Описание стратегии оптимизации кластера (через Cruise Control). |

---

## Практические сценарии

### Сценарий 1: Развертывание кластера в режиме KRaft (Kafka 3.7+)

В современных версиях Strimzi (0.40+) рекомендуется использовать KRaft и NodePools для гибкого управления узлами.

```yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaNodePool
metadata:
  name: dual-role-pool
  labels:
    strimzi.io/cluster: my-cluster
spec:
  replicas: 3
  roles:
    - controller
    - broker
  storage:
    type: persistent-claim
    size: 100Gi
    class: fast-ssd
---
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: my-cluster
spec:
  kafka:
    version: 3.7.0
    metadataStateDetached: true # Использование NodePools
    listeners:
      - name: plain
        port: 9092
        type: internal
        tls: false
      - name: tls
        port: 9093
        type: internal
        tls: true
    config:
      offsets.topic.replication.factor: 3
      transaction.state.log.replication.factor: 3
      default.replication.factor: 3
      min.insync.replicas: 2
  entityOperator:
    topicOperator: {}
    userOperator: {}
```

### Сценарий 2: Автоматическая ребалансировка через Cruise Control

Для оптимизации распределения дискового пространства и CPU необходимо включить Cruise Control в ресурсе `Kafka` и создать объект `KafkaRebalance`.

1. **Включение в Kafka CR:**
   ```yaml
   spec:
     cruiseControl: {} # Использует настройки по умолчанию
   ```

2. **Запуск ребалансировки:**
   ```yaml
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
   ```

### Сценарий 3: Репликация данных (MirrorMaker 2)

Используется для построения гибридных облаков или Disaster Recovery.

```yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaMirrorMaker2
metadata:
  name: my-mirror-maker
spec:
  version: 3.7.0
  replicas: 2
  connectCluster: "my-cluster-target"
  clusters:
    - alias: "source"
      bootstrapServers: "source-cluster-kafka-bootstrap:9092"
    - alias: "target"
      bootstrapServers: "target-cluster-kafka-bootstrap:9092"
  mirrors:
    - sourceCluster: "source"
      targetCluster: "target"
      sourceConnector: {}
      checkpointConnector: {}
```

---

## Дополнительная информация

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — основы архитектуры и механизмы KRaft.
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — теория, на которой основана работа Cruise Control.
- **[Kubernetes Operators](../Kubernetes/Concepts/kubernetes_operators.md)** — фундаментальные принципы работы паттерна Оператор.

### Ресурсы

- **[Официальный сайт Strimzi](https://strimzi.io/)**
- **[Strimzi Documentation (Current)](https://strimzi.io/docs/operators/latest/full/)**
