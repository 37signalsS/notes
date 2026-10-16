# Apache Kafka в Kubernetes с использованием Helm-чарта Bitnami

**Актуально для:** Bitnami Kafka Helm chart 32.x.x / Apache Kafka 4.0.x (KRaft) / Kubernetes 1.30+

> **Статус:** Bitnami Secure Images — с 28 августа 2025 года доступна ограниченная бесплатная поддержка. Подписка на BSI рекомендуется для production-сред. Детали на [bitnami.com](https://bitnami.com).

## Определения

- **Bitnami Kafka Helm chart** — Helm-чарт (Broadcom / Bitnami) для развертывания Apache Kafka в Kubernetes в режиме KRaft. Автоматически создаёт два StatefulSet — контроллеры и брокеры, а также sidecar с JMX Exporter, NetworkPolicy, ServiceMonitor и PrometheusRule. Зависимостью является только чарт `bitnami/common` (v2.x).
- **KRaft (Kafka Raft Metadata Mode)** — протокол консенсуса, управляющий метаданными кластера через Raft-кворум контроллеров. Полностью заменил ZooKeeper, который удалён из Kafka начиная с версии 4.0 (был объявлен устаревшим в 3.5).
- **Контроллер (Controller)** — узел, входящий в кворум KRaft. Хранит и реплицирует метаданные кластера (лог `@metadata`), проводит выборы лидера партиций и управляет реорганизацией. Контроллеры могут также выполнять роль брокера (`controllerOnly: false` — комбинированный режим).
- **Брокер (Broker)** — узел, обслуживающий клиентский трафик (запись/чтение продюсеров и консьюмеров), хранящий пользовательские топики и выполняющий репликацию.
- **Listener** — сетевой интерфейс брокера/контроллера, определяющий порт, протокол и адрес. В chart 32.x существует 4 listener: `CLIENT` (9092), `CONTROLLER` (9093), `INTERNAL`/interbroker (9094), `EXTERNAL` (9095).
- **Sidecar-контейнер** — дополнительный контейнер в поде, запускаемый рядом с основным приложением для предоставления вспомогательной функциональности (в данном случае JMX Exporter для метрик).
- **NetworkPolicy** — объект Kubernetes для управления сетевым трафиком между подами.
- **ServiceMonitor** — объект Prometheus Operator для автоматической настройки сбора метрик с сервисов.
- **PrometheusRule** — объект Prometheus Operator для определения правил оповещений на основе метрик.
- **Rack Awareness** — механизм распределения реплик партиций по независимым зонам отказа (зонам доступности облака) посредством параметра `broker.rack`.
- **External Secrets Operator (ESO)** — контроллер Kubernetes для синхронизации секретов из внешних хранилищ (HashiCorp Vault, AWS Secrets Manager и др.) в Kubernetes Secret.
- **Сухой запуск (Dry Run)** — режим Helm, позволяющий проверить сгенерированные манифесты без применения.

## Предварительные условия

Перед развертыванием Bitnami Kafka Helm chart в production убедитесь, что выполнены следующие требования:

| Компонент | Минимальная версия | Обоснование |
|-----------|-------------------|-------------|
| **Kubernetes** | 1.30+ | KRaft требует современных StatefulSet (PVC retention policy, `podManagementPolicy`), а также Server-Side Apply для declarative-обновлений. |
| **Helm** | 3.8.0+ | Поддержка OCI-репозиториев и Helm Hooks. |
| **Persistent Volume provisioner** | любой CSI-драйвер с `WaitForFirstConsumer` | Kafka требует высокопроизводительных дисков (локальные NVMe preferred); `volumeBindingMode: WaitForFirstConsumer` гарантирует создание тома на узле, где планировщик разместил под. |
| **OCI registry access** | — | Bitnami charts распространяются через `oci://registry-1.docker.io/bitnamicharts`; для частных реестров потребуется pull secret. |

### Проверка готовности кластера

```bash
# Проверка версии Kubernetes и поддерживаемых API
kubectl version --short
# → Client Version: v1.31.0
# → Server Version: v1.31.1

# Проверка режима привязки StorageClass (обязательно WaitForFirstConsumer)
kubectl get sc -o custom-columns=NAME:.metadata.name,PROVISIONER:.provisioner,BINDING:.volumeBindingMode
# → NAME        PROVISIONER                    BINDING
# → Fast-ssd    kubernetes.io/no-provisioner   WaitForFirstConsumer
```

---

## Архитектура и принцип работы

### KRaft вместо ZooKeeper

Начиная с chart 32.x и Apache Kafka 4.0, ZooKeeper больше не является зависимостью. Координация метаданных выполняется через встроенный протокол Raft (KIP-500):

```text
┌─────────────────────────────────────────────────────────────────────┐
│                    KRaft Controller Quorum (3)                      │
│                                                                     │
│  ┌──────────────┐  Raft Consensus  ┌──────────────┐  ┌────────────┐ │
│  │ Controller-0 │ ◄──────────────► │ Controller-1 │  │ Controller-2│ │
│  │ (Лидер кворума)│                │ (Follower)   │  │ (Follower)  │ │
│  └──────┬───────┘                  └──────┬───────┘  └──────┬─────┘ │
│         │                                 │                  │        │
│         └────────────────────┬────────────┴──────────────────┘        │
│                              │ Metadata log (@metadata)               │
│                              ▼                                        │
│  ┌──────────────────────────────────────────────┐                     │
│  │  Broker Pool (данные)                        │                     │
│  │  ┌──────────────┐  ┌──────────────┐         │                     │
│  │  │ Broker-0     │  │ Broker-1     │ ...     │                     │
│  │  │ (данные)     │  │ (данные)     │         │                     │
│  │  └──────────────┘  └──────────────┘         │                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Архитектура controller/broker в chart 32.x:**

| Параметр | Значение по умолчанию | Описание |
|----------|----------------------|----------|
| `controller.replicaCount` | `3` | Количество controller-eligible узлов (входит в Raft-кворум). |
| `controller.controllerOnly` | `false` | Если `true` — выделенные контроллеры без брокерских ролей. |
| `broker.replicaCount` | `0` | Количество выделенных broker-only узлов (по умолчанию 0 — контроллеры совмещают брокерскую роль). |

В комбинированном режиме (`controllerOnly: false`, `broker.replicaCount: 0`) 3 узла одновременно являются контроллерами и брокерами. Для production с высокой нагрузкой рекомендуется выделить роли: `controllerOnly: true` + отдельный `broker.replicaCount`.

### Архитектура listeners

Chart 32.x конфигурирует 4 listener'а по умолчанию:

| Listener | Порт | Назначение |
|----------|------|------------|
| `CLIENT` | 9092 | Внешние продюсеры и консьюмеры (внутри K8s). |
| `CONTROLLER` | 9093 | Связь брокеров с контроллерами KRaft. |
| `INTERNAL` (interbroker) | 9094 | Межброкерная репликация. |
| `EXTERNAL` | 9095 | Доступ извне кластера (опционально). |

### Назначение портов и ролей

```text
                    ┌─────────────────────────┐
                    │   Service (ClusterIP)   │
                    │   порт 9092 (CLIENT)    │
                    └──────────┬──────────────┘
                               │
┌───── Внешние клиенты ───────┘
│
│  ┌────────────────┐  ┌──────────────┐  ┌────────────────┐
│  │ Broker-0       │  │ Broker-1     │  │ Broker-2       │
│  │ :9092 :9093    │  │ :9092 :9093  │  │ :9092 :9093    │
│  │ :9094 (repl)   │  │ :9094 (repl) │  │ :9094 (repl)   │
│  └────────┬───────┘  └────────┬─────┘  └────────┬───────┘
│           │ Raft quorum      │                │
│           └──────────────────┼────────────────┘
│                              ▼
│  ┌──────────────────────────────┐
│  │ Controller Quorum (KRaft)    │
│  │ Controller-0 (leader)        │
│  │ Controller-1, Controller-2     │
│  └──────────────────────────────┘
└──────────────────────────────────
```

---

## Практические сценарии / Установка и настройка

### Минимальная установка

```bash
# Добавить репозиторий Bitnami (OCI)
helm install kafka oci://registry-1.docker.io/bitnamicharts/kafka \
  --namespace kafka \
  --create-namespace \
  --set controller.replicaCount=3 \
  --set controller.controllerOnly=false
# → NAME: kafka
# → LAST DEPLOYED: ...
# → NAMESPACE: kafka
# → STATUS: deployed

# Проверка статуса
kubectl -n kafka get pods -l app.kubernetes.io/name=kafka
# → NAME                             READY   STATUS    RESTARTS   AGE
# → kafka-controller-0               2/2     Running   0          3m
# → kafka-controller-1               2/2     Running   0          2m
# → kafka-controller-2               2/2     Running   0          1m
```

### Wrapper chart с фиксированными версиями

Для production-деплоев используйте wrapper chart с `Chart.lock` для воспроизводимых установок:

```yaml
# Chart.yaml (wrapper chart)
apiVersion: v2
name: kafka-prod
version: 0.1.0
dependencies:
  - name: kafka
    version: "32.5.0"
    repository: "oci://registry-1.docker.io/bitnamicharts"
    condition: kafka.enabled
```

```yaml
# Chart.lock
dependencies:
  - name: kafka
    version: 32.5.0
    repository: "oci://registry-1.docker.io/bitnamicharts"
    digest: sha256:...
generated: 2026-10-15
```

**Важно:** плавающая версия `32.x.x` подходит для `helm dependency update`, но `Chart.lock` гарантирует воспроизводимые деплои.

### Конфигурация controller и broker

Продакшен-профиль с выделенными ролями:

```yaml
controller:
  replicaCount: 3
  controllerOnly: true          # Только контроллеры, без брокерских ролей
  heapOpts: "-XX:InitialRAMPercentage=75 -XX:MaxRAMPercentage=75"
  resources:
    requests:
      cpu: 1
      memory: 2Gi
    limits:
      cpu: 2
      memory: 4Gi
  persistence:
    enabled: true
    storageClass: "fast-ssd"
    size: 50Gi
  pdb:
    create: true
    minAvailable: 2             # 2 из 3 контроллеров всегда доступны

broker:
  replicaCount: 3               # 3 брокера-данных
  heapOpts: "-XX:InitialRAMPercentage=75 -XX:MaxRAMPercentage=75"
  resources:
    requests:
      cpu: 2
      memory: 8Gi
    limits:
      cpu: 4
      memory: 12Gi
  persistence:
    enabled: true
    storageClass: "fast-ssd"
    size: 200Gi
  pdb:
    create: true
    minAvailable: 2
```

**Обоснование параметров:**

- **heapOpts через JVM ergonomics** (`-XX:InitialRAMPercentage=75 -XX:MaxRAMPercentage=75`) — современный подход. Heap автоматически масштабируется до 75% контейнерной памяти. Оставшиеся 25% идут на page cache ОС, который Kafka активно использует для zero-copy чтения.
- **controllerOnly: true** — выделенные контроллеры не обслуживают клиентский трафик, что исключяет влияние пиковых нагрузок на брокерах на стабильность Raft-кворума.
- **podAntiAffinity** (через `topologySpreadConstraints` в `controller.template` и `broker.template`) гарантирует распределение узлов по разным нодам.

```yaml
# topologySpreadConstraints для брокеров
broker:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: "kubernetes.io/hostname"
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          app.kubernetes.io/name: kafka
          app.kubernetes.io/component: broker
```

### Конфигурация listeners

Чарт 32.x использует отдельные параметры для каждого listener — в отличие от устаревшего `auth.clientProtocol`/`auth.interBrokerProtocol`:

```yaml
listeners:
  client:
    containerPort: 9092
    protocol: SASL_SSL      # Внутри K8s: SASL_SSL для шифрования и аутентификации
    name: CLIENT
  controller:
    containerPort: 9093
    protocol: SASL_SSL
    name: CONTROLLER
  interbroker:
    containerPort: 9094
    protocol: SASL_SSL
    name: INTERNAL
  external:
    containerPort: 9095
    protocol: SASL_SSL
    name: EXTERNAL
```

### Аутентификация: SASL + TLS

Chart 32.x разделяет настройку SASL и TLS на отдельные секции. Согласно официальной документации Bitnami chart, в режиме KRaft механизм SCRAM пока не поддерживается для inter-broker и контроллерной коммуникации — используется PLAIN. SCRAM-SHA-256/512 включён в `enabledMechanisms`, но применяется только для клиентских подключений (при необходимости).

```yaml
# SASL: inter-broker и controller используют PLAIN; клиенты — через ESO
sasl:
  enabledMechanisms: PLAIN,SCRAM-SHA-256,SCRAM-SHA-512
  interBrokerMechanism: PLAIN
  controllerMechanism: PLAIN
  interbroker:
    user: inter_broker_user
    password: ""          # Генерируется случайно, если пусто
  controller:
    user: controller_user
    password: ""
  client:
    users:
      - app-user
      - monitoring-user
    passwords: ""          # Подставляется через ESO из Vault
  existingSecret: ""       # Secret с ключами client-passwords, inter-broker-password, controller-password

# TLS (JKS или PEM; autoGenerated работает только с PEM)
tls:
  type: PEM                  # JKS (устаревший) или PEM (рекомендуется; нужен для autoGenerated)
  autoGenerated:
    enabled: true            # Автоматическая генерация сертификатов через helm или cert-manager
    engine: helm             # или: cert-manager
  existingSecret: ""         # Custom secret: kafka-tls-{index}
  pemChainIncluded: false    # true, если CA certs bundled с endpoint cert (CertManager ACME)
```

Пароли SASL монтируются из Kubernetes Secret, создаваемого External Secrets Operator из Vault. Чарт использует `sasl.existingSecret` для ссылки на существующий Secret, либо генерирует случайные пароли для inter-broker и controller, если `password` пусты. Формат Secret:

```bash
kubectl create secret generic kafka-sasl \
  --from-literal=client-passwords="pass1,pass2" \
  --from-literal=inter-broker-password="broker-pass" \
  --from-literal=controller-password="controller-pass"
```

### Доступ извне кластера (External Access)

Chart 32.x поддерживает три паттерна внешнего доступа через `externalAccess`:

| Паттерн | Тип Service | Описание | Порт |
|---------|-------------|----------|------|
| **LoadBalancer** | LoadBalancer | По отдельному сервису на каждый брокер. Требует N+1 внешних IP для N брокеров. | 9094 |
| **NodePort** | NodePort | Авто- или ручной выбор NodePort для каждого брокера. | 30000–32767 |
| **ClusterIP + Ingress** | ClusterIP + TCP Ingress | Один внешний IP и порт (443) через TLS Passthrough. | 9094 |

```yaml
externalAccess:
  enabled: true
  controller:
    service:
      type: LoadBalancer
      ports:
        external: 9094
      loadBalancerIPs:
        - 203.0.113.10
        - 203.0.113.11
        - 203.0.113.12
  broker:
    service:
      type: LoadBalancer
      ports:
        external: 9094
      loadBalancerIPs:
        - 203.0.113.20
        - 203.0.113.21
        - 203.0.113.22
```

**Важно:** Kafka не может работать за единым L4/L7 балансировщиком для всех брокеров — клиент получает `advertised.listeners` с прямыми адресами каждого лидера партиции и подключается напрямую (см. [архитектуру внешнего доступа в Strimzi](../Kafka/strimzi_kafka_operator.md)).

### JMX Exporter и метрики

Chart 32.x использует sidecar `bitnami/jmx-exporter` (v1.4.0), метрики публикуются на порту 5555 в формате Prometheus:

```yaml
metrics:
  jmx:
    enabled: true
    kafkaJmxPort: 5555
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
  prometheusRule:
    enabled: true
```

Подробная матрица критических метрик Kafka и пороговых значений алертов приведена в [файле по мониторингу Kafka](kafka_for_monitoring.md).

### NetworkPolicy

```yaml
networkPolicy:
  enabled: true
  allowExternal: false
  allowExternalEgress: false
  extraIngress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: orders
      ports:
        - port: 9092
          protocol: TCP
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - port: 5555
          protocol: TCP
```

### Создание топиков (Provisioning)

Чарт содержит Job provisioning, который запускается после готовности брокеров (через initContainer):

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
        retention.ms: "604800000"     # 7 дней
        cleanup.policy: delete
        min.insync.replicas: 2
    - name: payments.completed
      partitions: 3
      replicationFactor: 3
      config:
        retention.ms: "2592000000"    # ~30 дней
        cleanup.policy: delete
        min.insync.replicas: 2
```

**Выбор количества партиций:**

| Нагрузка | Партиции | Комментарий |
|----------|----------|-------------|
| < 10 МБ/с | 3 | Минимальная конфигурация для тестовой среды. |
| 10–50 МБ/с | 6 | База для продакшена с умеренной нагрузкой. |
| > 50 МБ/с | 12–24 | Учитывайте, что рост партиций в production — операция с перераспределением данных. |

### PodDisruptionBudget

В chart 32.x PDB настраивается отдельно для controller и broker:

```yaml
controller:
  pdb:
    create: true
    minAvailable: 2

broker:
  pdb:
    create: true
    minAvailable: 2
```

При трёх брокерах и `minAvailable: 2` Kubernetes не позволит одновременно дрейнить более одного узла с брокером. Это защищает от потери ISR и нарушения `min.insync.replicas` при последовательных дренированиях.

### Rack Awareness

Для распределения реплик партиций по зонам доступности используется параметр `brokerRackAwareness`. Chart автоматически определяет зону через cloud provider metadata и устанавливает `broker.rack`:

```yaml
brokerRackAwareness:
  enabled: true
  cloudProvider: aws-az      # или: azure
#
# Для on-premise инфраструктуры задаётся rack вручную:
config:
  broker.rack: "rack1"       # Значение из node label topology.kubernetes.io/zone
```

Подробнее о принципах rack awareness — в [обзоре Kafka](kafka_overview.md).

### Argo CD Application (GitOps)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kafka
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: kafka
  source:
    repoURL: oci://registry-1.docker.io/bitnamicharts
    chart: kafka
    targetRevision: "32.x"
    helm:
      releaseName: kafka
      valueFiles:
        - $values/values/kafka-sasl.yaml    # values из Git
      values: |
        sasl:
          client:
            users:
              - app-user
              - monitoring-user
            passwords: ""          # Подставляется через External Secret из Vault
          existingSecret: kafka-sasl
        controller:
          replicaCount: 3
          controllerOnly: true
        broker:
          replicaCount: 3
  destination:
    server: https://kubernetes.default.svc
    namespace: kafka
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - SkipDryRunOnMissingResource=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

Для подстановки SASL-паролей из внешнего хранилища (Vault через External Secrets Operator) создаётся отдельный `ExternalSecret`, который генерирует Kubernetes `Secret` с ключами, используемыми в values:

---

## Операции и команды

### Отладка и диагностика

```bash
# Логи контроллера
kubectl logs -n kafka kafka-controller-0 -c kafka -f
# → [2026-10-15 12:00:00,000] INFO ...

# Список топиков
kubectl exec -n kafka kafka-controller-0 -- \
  kafka-topics.sh --bootstrap-server localhost:9092 --list
# → orders.created
# → payments.completed
# → __consumer_offsets
# → _schemas

# Проверка under-replicated партиций
kubectl exec -n kafka kafka-controller-0 -- \
  kafka-topics.sh --bootstrap-server localhost:9092 \
  --describe --under-replicated-partitions
# → (пустой вывод означает, что все партиции реплицированы)

# Статус KRaft кворума
kubectl exec -n kafka kafka-controller-0 -- \
  kafka-metadata-quorum.sh --bootstrap-server localhost:9093 describe --status
# → ClusterId:              0xAbCdEf1234567890AbCdEf1234567890
# → LeaderId:               1001
# → LeaderEpoch:            3
# → HighWatermark:          42
# → MaxFollowerLag:         0
# → CurrentVoters:          [0,1,2]

# Лаг consumer group
kubectl exec -n kafka kafka-controller-0 -- \
  kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group orders-consumer
# → TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID
# → orders.created  0          15234           15234           0    orders-consumer-1/...
# → orders.created  1          15892           15892           0    orders-consumer-2/...
```

### Обновление chart

```bash
# Сухой запуск перед upgrade
helm upgrade kafka oci://registry-1.docker.io/bitnamicharts/kafka \
  --namespace kafka \
  --version 32.5.1 \
  --values values.yaml \
  --dry-run
# → Ошибки валидации выводятся, но изменения не применяются

# Rolling update с паузой перед рестартом контроллеров
helm upgrade kafka oci://registry-1.docker.io/bitnamicharts/kafka \
  --namespace kafka \
  --version 32.5.1 \
  --values values.yaml \
  --wait --timeout 600s
```

---

## Устранение неисправностей

| Проблема | Возможная причина | Решение |
|----------|-------------------|---------|
| **CrashLoopBackOff контроллеров** | KRaft кворум не сформировался; недостаточно контроллеров (минимум 3 для production) | Проверить логи `kafka-metadata-quorum.sh`; убедиться, что PVC сохранили кластерный ID (`existingKraftSecret`) |
| **Брокер не регистрируется в кворуме** | `clusterId` в Secret не совпадает с сохранённым в data/meta.properties | Удалить Secret `existingKraftSecret` и перезапустить с правильным `clusterId` |
| **Отсутствие метрик в Prometheus** | JMX Exporter sidecar не запущен или ServiceMonitor не найден | Проверить `kubectl -n monitoring get servicemonitor`; проверить статус sidecar: `kubectl describe pod` |
| **Проблемы с аутентификацией SASL** | Неправильные учетные данные в Secret | Проверить Secret, созданный ESO; убедиться, что `sasl.clientUsers` и `sasl.clientPasswords` имеют одинаковую длину |
| **Топики не создаются через provisioning** | InitContainer не дождался готовности Kafka | Проверить логи Job provisioning; убедиться, что `serviceAccount` имеет права на создание топиков |
| **Проблемы с сетевым доступом** | NetworkPolicy слишком restrictive | Добавить `extraIngress` правила для namespace-источников |
| **Недостаточная производительность** | Недостаточные ресурсы или heap | Увеличить `resources`; использовать `-XX:InitialRAMPercentage=75 -XX:MaxRAMPercentage=75` |
| **Дисковое пространство заканчивается** | Неправильная retention | Проверить `log.retention.hours`, `log.segment.bytes`; включить Tiered Storage |
| **KRaft split-brain** | `ActiveControllerCount > 1` | Проверить сетевую стабильность между контроллерами; уменьшить нагрузку на GC (  см. [JVM GC tuning](kafka_jvm_gc_tuning.md)) |
| **Не удаётся подключиться извне** | `advertised.listeners` не настроены для external | Проверить `externalAccess` и DNS-имена; убедиться, что балансировщик пробрасывает трафик к каждому брокеру индивидуально |

---

## Best Practices

1. **Фиксируйте версии** в `Chart.lock` для воспроизводимых деплоев.
2. **Используйте KRaft** — ZooKeeper удалён из Kafka 4.0; для новых кластеров сразу настраивайте KRaft, а не пытайтесь организовать ZooKeeper.
3. **Разделяйте роли controller и broker** (`controllerOnly: true`) для production, чтобы изолировать Raft-кворум от клиентской нагрузки.
4. **Настраивайте ресурсы через JVM ergonomics** (`-XX:InitialRAMPercentage=75 -XX:MaxRAMPercentage=75`) — heap автоматически масштабируется с контейнером, а page cache использует оставшую память.
5. **Всегда используйте podAntiAffinity / topologySpreadConstraints** для распределения узлов по разным нодам и зонам.
6. **Включайте мониторинг с первого дня** — JMX Exporter, ServiceMonitor и PrometheusRule должны быть активны при initial deployment.
7. **Настраивайте PDB для controller и broker отдельно** — `minAvailable: 2` при 3 узлах гарантирует отсутствие потери кворума при дрейне.
8. **Используйте min.insync.replicas=2 и acks=all** для гарантии долговечности записи.
9. **Используйте внешние системы управления секретами** (Vault через ESO) вместо хранения паролей в values-файлах.
10. **Регулярно проверяйте under-replicated партиции** — они указывают на проблемы с дисками, сетью или брокерами.
11. **Для production используйте отдельные нодпулы** для контроллеров и брокеров при больших нагрузках.
12. **Тестируйте восстановление после сбоев** — регулярно проводите chaos-эксперименты (убить контроллер, брокер, зону).
13. **Включайте Rack Awareness** для защиты от потери зоны доступности.
14. **Осторожно растягивайте PVC** — используйте `persistentVolumeClaimRetentionPolicy` и `allowVolumeExpansion` в StorageClass.
15. **Ограничивайте размер сообщений** — `max.message.bytes: 1048588` (1 МБ) по умолчанию; увеличивайте только при необходимости.

---

## Дополнительная информация

### Официальные ресурсы

- [Bitnami Kafka Helm Chart Documentation](https://artifacthub.io/packages/helm/bitnami/kafka)
- [Bitnami Kafka Container Image Documentation](https://hub.docker.com/r/bitnami/kafka)
- [Apache Kafka Official Documentation](https://kafka.apache.org/documentation/)
- [Bitnami charts на GitHub](https://github.com/bitnami/charts/tree/main/bitnami/kafka)

### Связанные файлы

- [Strimzi — Kafka Operator для Kubernetes](strimzi_kafka_operator.md) — альтернативный подход к управлению Kafka в Kubernetes
- [Эксплуатация сотен кластеров Kafka в Kubernetes: опыт MindBox](kafka-k8s-operations-experience.md) — практический опыт крупномасштабного развертывания
- [Обзор Apache Kafka](kafka_overview.md) — архитектура, экосистема, принципы работы
- [Безопасность и управление доступом в Apache Kafka](kafka_security.md) — mTLS, SASL, ACL, StandardAuthorizer
- [Использование Apache Kafka в системах мониторинга и наблюдаемости](kafka_for_monitoring.md) — JMX Exporter vs Kafka Exporter, метрики, алерты
- [Перевод кластера Apache Kafka в Kubernetes из Deployment в StatefulSet](deployment_to_statefulset_migration.md)
- [JVM GC tuning для Kafka](kafka_jvm_gc_tuning.md) — настройка G1GC, борьба с pause
- [ISR и репликация в Apache Kafka](kafka_isr_replication.md) — механизм ISR Shrink/Expand
- [Capacity Planning и DR для Apache Kafka](kafka_capacity_dr.md) — сайзинг, репликация через MirrorMaker 2

### Версии и совместимость

| Компонент | Рекомендуемая версия | Примечания |
|-----------|---------------------|------------|
| Bitnami Kafka Helm chart | 32.5.x | Последняя стабильная на октябрь 2026 |
| Apache Kafka | 4.0.x | KRaft — единственный режим (ZooKeeper удалён) |
| JMX Exporter | 1.4.0 | Sidecar `bitnami/jmx-exporter` |
| ZooKeeper | Не используется | Удалён в Kafka 4.0 |
| Kubernetes | 1.30+ | Требуется для KRaft и современных StatefulSet |
| Helm | 3.8.0+ | Поддержка OCI-репозиториев |
