# Strimzi — Kafka Operator для Kubernetes

## Определения

**Strimzi** — это open-source проект, предоставляющий Kubernetes-оператор для развертывания, управления и эксплуатации кластеров **Apache Kafka** в облачных средах. Strimzi упрощает запуск Kafka, которая является сложной распределенной системой с состоянием (stateful), делая процесс управления нативным для Kubernetes.

*   **Репозиторий:** [github.com/strimzi/strimzi-kafka-operator](https://github.com/strimzi/strimzi-kafka-operator)
*   **Назначение:** Автоматизация полного жизненного цикла Kafka, включая Zookeeper (или KRaft), Kafka Connect и сопутствующие компоненты.

## Основные возможности

Strimzi предоставляет набор контроллеров и [CRD](../Kubernetes/Concepts/kubernetes_crd.md), которые автоматизируют:

*   **Развертывание и настройка:** Быстрое создание кластеров Kafka с заданными параметрами.
*   **Управление темами и пользователями:** Декларативное описание топиков (`KafkaTopic`) и прав доступа (`KafkaUser`) через API Kubernetes.
*   **Непрерывные обновления:** Безопасное проведение обновлений версий брокеров и конфигураций без простоя (Rolling Updates).
*   **Масштабирование:** Увеличение или уменьшение количества брокеров в кластере.
*   **Мониторинг и оповещение:** Интеграция с Prometheus и Grafana для сбора метрик и настройки алертинга.
*   **Безопасность:** Поддержка TLS для шифрования трафика и аутентификации (SCRAM-SHA, OAuth, TLS Client Auth).
*   **Kafka Bridge:** Компонент для взаимодействия с Kafka через HTTP API.

## Архитектура и компоненты

### Основные операторы внутри Strimzi

1.  **Cluster Operator:** Отвечает за развертывание и управление кластерами Kafka, Zookeeper, Kafka Connect, MirrorMaker и Entity Operator.
2.  **Topic Operator:** Обеспечивает синхронизацию между ресурсами `KafkaTopic` в Kubernetes и реальными топиками внутри Kafka.
3.  **User Operator:** Управляет пользователями Kafka через ресурсы `KafkaUser`, настраивая аутентификацию и ACL.

### Ключевые Custom Resources (CR)

| Ресурс | Назначение |
| :--- | :--- |
| **Kafka** | Описание кластера Kafka (брокеры, хранилище, Zookeeper/KRaft). |
| **KafkaTopic** | Создание и настройка топиков. |
| **KafkaUser** | Управление учетными данными и правами доступа. |
| **KafkaConnect** | Развертывание кластера Kafka Connect для интеграции данных. |
| **KafkaRebalance** | Оптимизация распределения данных между брокерами (через Cruise Control). |

## Практические сценарии

### Пример манифеста кластера Kafka

```yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: my-cluster
spec:
  kafka:
    version: 3.6.0
    replicas: 3
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
      transaction.state.log.min.isr: 2
    storage:
      type: persistent-claim
      size: 100Gi
      class: fast-storage
  zookeeper:
    replicas: 3
    storage:
      type: persistent-claim
      size: 10Gi
      class: fast-storage
  entityOperator:
    topicOperator: {}
    userOperator: {}
```

## Дополнительная информация

*   **[Официальный сайт Strimzi](https://strimzi.io/)**
*   **[Kafka Overview](./kafka_overview.md)** — основы и архитектура Apache Kafka.
*   **[Kubernetes Operators](../Kubernetes/Concepts/kubernetes_operators.md)** — паттерн проектирования контроллеров.
