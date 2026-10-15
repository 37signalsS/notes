# Apache Kafka в Kubernetes с использованием Helm-чарта Bitnami

**Актуально для:** Bitnami Kafka Helm chart 22.x.x / Apache Kafka 3.x.x / Kubernetes 1.25+

## Определения

- **Bitnami Kafka Helm chart** — официальный Helm-чарт для развертывания Apache Kafka в Kubernetes, включающий ZooKeeper как зависимый субчарт, JMX Exporter в виде sidecar-контейнера и генерацию манифестов NetworkPolicy, ServiceMonitor и PrometheusRule.
- **Sub-chart** — зависимый Helm-чарт, включаемый в основной чарт (в данном случае ZooKeeper).
- **Sidecar-контейнер** — дополнительный контейнер в поде, запускаемый рядом с основным приложением для предоставления вспомогательной функциональности (в данном случае JMX Exporter для метрик).
- **NetworkPolicy** — объект Kubernetes для управления сетевым трафиком между подами.
- **ServiceMonitor** — объект Prometheus Operator для автоматической настройки сбора метрик с сервисов.
- **PrometheusRule** — объект Prometheus Operator для определения правил оповещений на основе метрик.

## Prerequisites

Перед использованием Bitnami Kafka Helm chart убедитесь, что выполнены следующие предварительные условия:

- Kubernetes кластер версии 1.23 или выше
- Helm версии 3.8.0 или выше
- Наличие провайдера постоянных томов (Persistent Volume) в кластере
- Доступ к репозиторию Bitnami charts (обычно уже добавлен по умолчанию)

- **Bitnami Kafka Helm chart** — официальный Helm-чарт для развертывания Apache Kafka в Kubernetes, включающий ZooKeeper как зависимый субчарт, JMX Exporter в виде sidecar-контейнера и генерацию манифестов NetworkPolicy, ServiceMonitor и PrometheusRule.
- **Sub-chart** — зависимый Helm-чарт, включаемый в основной чарт (в данном случае ZooKeeper).
- **Sidecar-контейнер** — дополнительный контейнер в поде, запускаемый рядом с основным приложением для предоставления вспомогательной функциональности (в данном случае JMX Exporter для метрик).
- **NetworkPolicy** — объект Kubernetes для управления сетевым трафиком между подами.
- **ServiceMonitor** — объект Prometheus Operator для автоматической настройки сбора метрик с сервисов.
- **PrometheusRule** — объект Prometheus Operator для определения правил оповещений на основе метрик.

## Basic Concepts / Architecture / How it works

Bitnami Kafka Helm chart предоставляет полноценное решение для развертывания Apache Kafka в Kubernetes с следующими характеристиками:

1. **Встроенный ZooKeeper** — chart включает ZooKeeper как зависимый sub-chart, который автоматически развертывается и настраивается для работы с Kafka.
2. **JMX Exporter sidecar** — для экспорта метрик Kafka в формате Prometheus используется sidecar-контейнер на основе образа `bitnami/jmx-exporter`.
3. **Автоматическое генерирование манифестов** — chart создает NetworkPolicy для ограничения сетевого доступа, ServiceMonitor для интеграции с Prometheus и PrometheusRule для оповещений.
4. **Поддержка provisioning** — встроенный Job для автоматического создания топиков после готовности брокеров.
5. **Интеграция с внешними системами секретов** — поддержка External Secrets Operator для безопасного управления паролями через Vault или другие хранилища секретов.

## Practical Scenarios / Installation and Setup

### Настройка чарта

Для продакшен-деплоя рекомендуется использовать wrapper chart, который фиксирует версии зависимостей:

```yaml
# Chart.yaml (wrapper chart)
apiVersion: v2
name: kafka
version: 0.1.0
dependencies:
  - name: kafka
    version: "22.x.x"
    repository: "oci://registry-1.docker.io/bitnamicharts"
  - condition: zookeeper.enabled
    name: zookeeper
    version: "11.x.x"
    repository: "oci://registry-1.docker.io/bitnamicharts"
```

**Важно:** Версию чарта стоит зафиксировать в `Chart.lock` и закоммитить его. Хотя плавающая версия `22.x.x` подходит для `helm dependency update`, воспроизводимые деплои обеспечивает именно lock-файл.

### Параметры StatefulSet

Основные параметры для настройки StatefulSet Kafka брокеров:

```yaml
replicaCount: 3

heapOpts: "-Xmx2g -Xms2g"

persistence:
  enabled: true
  storageClass: "yc-network-ssd"
  size: 50Gi

podManagementPolicy: Parallel

resources:
  requests:
    cpu: 500m
    memory: 3Gi
  limits:
    cpu: 2
    memory: 4Gi

affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app.kubernetes.io/name: kafka
        topologyKey: kubernetes.io/hostname
```

**Обоснование параметров:**

- **Политика управления подами Parallel** безопасна для Kafka — брокеры не образуют кворум при запуске (это делает ZooKeeper). Она заметно ускоряет rolling-restart на кластерах с тремя и более брокерами.
- **Heap JVM** — примерно 75 % от лимита памяти контейнера. При лимите 4Gi настройка `-Xmx2g -Xms2g` оставляет 2Gi под page cache ОС, который Kafka активно использует при чтении.
- **podAntiAffinity** гарантирует, что каждый брокер попадёт на отдельный узел. Без этого два брокера на одном узле означают потерю кворума при отказе узла.

### Listeners и аутентификация

Для внутрикластерного взаимодействия используется PLAINTEXT (шифруется на сетевом уровне Cilium). Для клиентов вне namespace принудительно SASL/SCRAM:

```yaml
auth:
  clientProtocol: sasl
  interBrokerProtocol: plaintext
  sasl:
    mechanisms: scram-sha-256
    interBrokerMechanism: plain
    jaas:
      clientUsers:
        - app-user
        - monitoring-user
      clientPasswords:
        - ""   # подставляется через ESO; оставляем пустым
        - ""
```

Пароли монтируются из Kubernetes Secret, создаваемого External Secrets Operator из Vault. Чарт ищет Secret `kafka-jaas` в том же namespace — заполняем только секрет, не values-файл.

### JMX exporter sidecar

Чарт поставляет sidecar `bitnami/jmx-exporter` и `jmx-configmap.yaml`. При включении метрики брокера публикуются на порту 5556 в формате Prometheus:

```yaml
metrics:
  jmx:
    enabled: true
    resources:
      requests:
        cpu: 50m
        memory: 128Mi
      limits:
        cpu: 200m
        memory: 256Mi
  serviceMonitor:
    enabled: true
    namespace: monitoring
    labels:
      release: kube-prometheus-stack
```

**Ключевые метрики для мониторинга:**
- `kafka_server_replicamanager_underreplicatedpartitions` — должно быть 0
- `kafka_controller_kafkacontroller_activecontrollercount` — ровно 1 в кластере
- `kafka_network_requestmetrics_requestspersec` — паттерны трафика по типу запросов
- `kafka_server_brokertopicmetrics_messagesinpersec` — пропускная способность по топикам

### PrometheusRule

```yaml
metrics:
  prometheusRule:
    enabled: true
    rules:
      - alert: KafkaUnderReplicatedPartitions
        expr: kafka_server_replicamanager_underreplicatedpartitions > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Under-replicated partitions on {{ $labels.pod }}"
      - alert: KafkaOfflinePartitions
        expr: kafka_controller_kafkacontroller_offlinepartitionscount > 0
        for: 5m
        labels:
          severity: critical
      - alert: KafkaActiveControllers
        expr: sum(kafka_controller_kafkacontroller_activecontrollercount) != 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Неправильное количество активных контроллеров Kafka"
```

### NetworkPolicy

Чарт генерирует NetworkPolicy при `networkPolicy.enabled: true`. Расширяем её через `additionalRules` — до порта 9092 могут достучаться только нужные неймспейсы:

```yaml
networkPolicy:
  enabled: true
  allowExternal: false
  additionalRules:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: orders
      ports:
        - port: 9092
          protocol: TCP
```

### Создание топиков (provisioning)

Чарт содержит Job provisioning, который запускается после готовности брокеров:

```yaml
provisioning:
  enabled: true
  numPartitions: 6
  replicationFactor: 3
  topics:
    - name: orders.created
      partitions: 6
      replicationFactor: 3
      config:
        retention.ms: "604800000"   # 7 дней
        cleanup.policy: delete
    - name: payments.completed
      partitions: 3
      replicationFactor: 3
      config:
        retention.ms: "2592000000"  # 30 дней
```

**Выбор количества партиций**
| Нагрузка | Партиции |
|----------|----------|
| < 10 МБ/с | 3 |
| 10–50 МБ/с | 6 |
| > 50 МБ/с | 12–24 |

### PodDisruptionBudget

```yaml
pdb:
  create: true
  minAvailable: 2
```

При трёх брокерах и `minAvailable: 2` Kubernetes не позволит одновременно дрейнить больше одного узла с брокером. В сочетании с `offsets.topic.replication.factor=3` это гарантирует сохранность офсетов consumer groups при последовательном дрейне узлов.

### Sub-chart ZooKeeper

```yaml
zookeeper:
  enabled: true
  replicaCount: 3
  persistence:
    enabled: true
    storageClass: "yc-network-ssd"
    size: 8Gi
  resources:
    requests:
      cpu: 100m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 1Gi
```

**Важно:** ZooKeeper должен выбрать лидера до того, как брокеры Kafka начнут регистрироваться. Если брокеры при запуске падают в CrashLoopBackOff — сначала проверьте логи ZooKeeper.

### Flux HelmRelease

При использовании GitOps с Flux можно настроить HelmRelease следующим образом:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: kafka
  namespace: kafka
spec:
  interval: 10m
  chart:
    spec:
      chart: ./kafka
      sourceRef:
        kind: GitRepository
        name: infra-repo
  valuesFrom:
    - kind: Secret
      name: kafka-jaas
      valuesKey: jaasPasswords
      targetPath: auth.sasl.jaas.clientPasswords
  values:
    replicaCount: 3
```

Значения из `valuesFrom` подставляют SASL-пароли из Secret во время реконсиляции. В values-файле реального пароля нет.

## Operations and Commands

### Отладка

```bash
# Логи брокера
kubectl logs -n kafka kafka-0 -f
# → Вывод логов брокера в реальном времени

# Список топиков
kubectl exec -n kafka kafka-0 -- \
  kafka-topics.sh --bootstrap-server localhost:9092 --list
# → orders.created
# → payments.completed
# → __consumer_offsets
# → _schemas

# Under-replicated партиции
kubectl exec -n kafka kafka-0 -- \
  kafka-topics.sh --bootstrap-server localhost:9092 \
  --describe --under-replicated-partitions
# → Вывод только подреплицированных партиций (если все партиции реплицированы - пустой вывод)

# Лаг consumer group
kubectl exec -n kafka kafka-0 -- \
  kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group orders-consumer
# → TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID                                     HOST            CLIENT-ID
# → orders.created  0          15234           15234           0               orders-consumer-1-...   /10.0.0.5       orders-consumer
# → orders.created  1          15892           15892           0               orders-consumer-1-...   /10.0.0.5       orders-consumer
```

## Troubleshooting

| Проблема | Возможная причина | Решение |
|----------|-------------------|---------|
| CrashLoopBackOff брокеров | ZooKeeper не готов | Проверить логи ZooKeeper подов |
| Отсутствие метрик в Prometheus | JMX Exporter не запущен или неправильно настроен | Проверить статус sidecar-контейнера и конфигурацию JMX Exporter |
| Проблемы с аутентификацией SASL/SCRAM | Неправильные учетные данные в Secret | Проверить Secret `kafka-jaas` и его соответствие ожидаемому формату |
| Не создаются топики через provisioning | Job provisioning не завершается успешно | Проверить логи Job provisioning и убедиться, что брокеры готовы |
| Проблемы с сетевым доступом | NetworkPolicy слишком restrictive | Проверить правила NetworkPolicy и добавить необходимые исключения |
| Высокая latency при производстве/потреблении | Недостаточные ресурсы или неправильная конфигурация | Проверить использования CPU/memory, настройки heap, сетевую топологию |
| Проблемы с контроллером Kafka | Неправильное количество активных контроллеров | Проверить метрики `kafka_controller_kafkacontroller_activecontrollercount`, логи ZooKeeper |
| Дисковое пространство заканчивается | Неправильная конфигурация retention или слишком большое хранение данных | Проверить настройки retention.ms, размеры PVC, удалить старые данные если необходимо |

## Best Practices

1. **Фиксируйте версии** в `Chart.lock` для воспроизводимых деплоев.
2. **Настраивайте ресурсы консервативно** — оставляйте достаточно памяти для page cache ОС (примерно 25-30% от общего лимита).
3. **Всегда используйте podAntiAffinity** для распределения брокеров по разным узлам.
4. **Включайте мониторинг с первого дня** — JMX Exporter и ServiceMonitor должны быть активны при初始 развертывании.
5. **Настраивайте PodDisruptionBudget** для защиты от потери кворума podczas узловых дренирований.
6. **Используйте внешние системы управления секретами** (Vault, AWS Secrets Manager) через External Secrets Operator вместо хранения паролей в values-файлах.
7. **Регулярно проверяйте подреплицированные партиции** — они указывают на проблемы с производительностью или доступностью брокеров.
8. **Для production сред используйте отдельные нодпулы** для ZooKeeper и Kafka брокеров при больших нагрузках.
9. **Тестируйте восстановление после сбоев** — регулярно проводите chaos-эксперименты для проверки устойчивости кластера.
10. **Следите за версией ZooKeeper** — при апгрейде Kafka убедитесь, что используется совместимая версия ZooKeeper.

## Additional Information

### Official Resources
- [Bitnami Kafka Helm Chart Documentation](https://artifacthub.io/packages/helm/bitnamicharts/kafka)
- [Bitnami Kafka Container Image Documentation](https://hub.docker.com/r/bitnami/kafka)
- [Apache Kafka Official Documentation](https://kafka.apache.org/documentation/)

### Related Files
- [Strimzi — Kafka Operator для Kubernetes](../Kafka/strimzi_kafka_operator.md) — альтернативный подход к управлению Kafka в Kubernetes
- [Эксплуатация сотен кластеров Kafka в Kubernetes: опыт MindBox](../Kafka/kafka-k8s-operations-experience.md) — практический опыт крупномасштабного развертывания
- [Перевод кластера Apache Kafka в Kubernetes из Deployment в StatefulSet](../Kafka/deployment_to_statefulset_migration.md) — technical детали миграции

### Версии и совместимость
| Компонент | Рекомендуемая версия | Примечания |
|-----------|---------------------|------------|
| Bitnami Kafka Helm chart | 22.x.x | Последняя стабильная версия на октябрь 2026 |
| Apache Kafka | 3.x.x | Совместима с chart 22.x.x |
| ZooKeeper (sub-chart) | 11.x.x | Включен как зависимость |
| Kubernetes | 1.25+ | Минимальная поддерживаемая версия |