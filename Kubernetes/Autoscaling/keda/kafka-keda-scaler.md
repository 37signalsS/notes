# KEDA + Kafka: Масштабирование на основе Consumer Lag

**Актуально для:** KEDA 2.15–2.17+ / Apache Kafka 3.x–3.9+ (включая Strimzi 1.x) / Kubernetes 1.28–1.35

## Определения

**Kafka Scaler** — встроенный специализированный адаптер KEDA (`type: kafka`), обеспечивающий масштабирование подов-консьюмеров в Kubernetes на основе отставания группы потребителей (consumer lag) в топиках Apache Kafka. Взаимодействует с брокерами напрямую по протоколу Kafka (на базе библиотеки Sarama) без необходимости развертывания промежуточных сборщиков метрик.

**Consumer Lag** — разница между максимальным смещением сообщений в партиции (High-Watermark) и текущим зафиксированным смещением (committed offset) группы потребителей. Выражает суммарное число необработанных сообщений в очереди.

**High-Watermark (HW)** — смещение последнего сообщения, успешно записанного брокером и реплицированного на все реплики в кворуме ISR (In-Sync Replicas). Определяет границу сообщений, доступных для чтения консьюмерами.

**Committed Offset** — последнее смещение, подтвержденное консьюмером и зафиксированное во внутреннем системном топике Kafka `__consumer_offsets`.

**lagThreshold** — целевой порог лага на одну реплику консьюмера (по умолчанию `10`). Используется алгоритмом HPA для вычисления необходимого количества подов.

**activationLagThreshold** — пороговое значение метрики лага (по умолчанию `0`), при превышении которого KEDA активирует рабочую нагрузку и масштабирует её из нуля в одну реплику (`0 -> 1`).

**allowIdleConsumers** — флаг (по умолчанию `false`), разрешающий или запрещающий HPA масштабировать консьюмеры выше общего числа доступных партиций топика.

**limitToPartitionsWithLag** — параметр (по умолчанию `false`), ограничивающий максимальное число реплик количеством партиций, имеющих ненулевой лаг на момент опроса.

**ensureEvenDistributionOfPartitions** — механизм KEDA (по умолчанию `false`), обеспечивающий масштабирование строго до чисел, являющихся делителями количества партиций топика, для исключения неравномерного распределения (skew) и избыточных ребалансировок.

**excludePersistentLag** — защитный механизм (по умолчанию `false`), исключающий из подсчета суммарного лага те партиции, чей оффсет не изменился между последовательными циклами опроса (защита от застревания на «отравленных сообщениях» / poison pills).

**scaleToZeroOnInvalidOffset** — политика обработки отсутствия зафиксированного смещения (по умолчанию `false`). При значении `false` удерживает 1 под для первичного коммита; при `true` масштабирует нагрузку до нуля.

**fullMetadata** — оптимизационный флаг клиента Kafka (по умолчанию `true`). При значении `false` отключает опрос метаданных всего кластера Kafka, запрашивая исключительно метаданные целевого топика, что снижает нагрузку на сеть и предотвращает OOMKilled у пода `keda-operator`.

**offsetResetPolicy** — политика поведения скейлера при обнаружении неинициализированного смещения (`latest` по умолчанию или `earliest`).

**Kafka Exporter** — сторонний сервис-экспортер (традиционно `danielqsj/kafka-exporter`), опрашивающий брокеры и отдающий метрики лага в формате Prometheus. Служит альтернативным источником метрик для триггера `type: prometheus` в случаях, когда KEDA не имеет прямого сетевого доступа к брокерам.

## Архитектура и механизм работы

### Архитектурные паттерны подключения

Масштабирование консьюмеров Kafka с помощью KEDA реализуется по двум основным архитектурным схемам:

#### Паттерн 1: Прямое подключение (Native Kafka Scaler) — Рекомендуемый

```text
┌────────────────────────────────────────────────────────┐
│ Apache Kafka Cluster (On-Premise / Strimzi)            │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │
│ │ Broker 0     │ │ Broker 1     │ │ __consumer_offsets│ │
│ └──────▲───────┘ └──────▲───────┘ └────────▲─────────┘ │
└────────┼────────────────┼──────────────────┼───────────┘
         │ Kafka Protocol (Port 9092 / 9093 / 9094)
         │ SASL_PLAINTEXT / SASL_SSL / SSL
┌────────▼────────────────┴──────────────────▼───────────┐
│ Kubernetes Cluster                                     │
│                                                        │
│ ┌────────────────────────┐  TriggerAuthentication      │
│ │ keda-operator          │ ◀─── Secret (SCRAM / mTLS)  │
│ └──────────┬─────────────┘                             │
│            │ gRPC                                      │
│ ┌──────────▼─────────────┐                             │
│ │ keda-metrics-apiserver │                             │
│ └──────────┬─────────────┘                             │
│            │ External Metrics API                      │
│ ┌──────────▼─────────────┐      scaleTargetRef         │
│ │ kube-controller-manager│ ──────────────────────────┐ │
│ │ (HPA Controller)       │                           │ │
│ └────────────────────────┘                           │ │
│                                                      ▼ │
│                                             ┌──────────┐
│                                             │ Consumer │
│                                             │ Pods     │
│                                             └──────────┘
```

- **Принцип:** KEDA Operator и Metrics Server используют встроенный клиент Sarama для прямого опроса брокеров Kafka через `bootstrapServers`.
- **Запросы:** KEDA с периодичностью `pollingInterval` выполняет:
  1. `MetadataRequest` — определение ведущих брокеров (Partition Leaders) и списка партиций;
  2. `OffsetFetchRequest` — запрос текущего зафиксированного смещения группы из топика `__consumer_offsets`;
  3. `ListOffsetsRequest` — запрос High-Watermark по каждой партиции;
  4. Расчет: `Partition Lag = High-Watermark - Committed Offset`.
- **Плюсы:** Минимальная задержка реакции, отсутствие зависимости от Prometheus и сторонних экспортеров.

#### Паттерн 2: Опосредованное подключение (Kafka Exporter + Prometheus Scaler)

```text
┌─────────────────┐      ┌────────────────┐      ┌─────────────────┐
│  Kafka Cluster  │ ◀─── │ Kafka Exporter │ ───▶ │   Prometheus    │
└─────────────────┘      └────────────────┘      └────────┬────────┘
                                                          │ PromQL
                                                 ┌────────▼────────┐
                                                 │ KEDA Prom Scaler│
                                                 └────────┬────────┘
                                                          │ HPA
                                                 ┌────────▼────────┐
                                                 │  Consumer Pods  │
                                                 └─────────────────┘
```

- **Принцип:** Prometheus скрейпит `kafka-exporter`, а KEDA опрашивает Prometheus через триггер `type: prometheus`.
- **Плюсы:** Учет сложных предикатов (скорость нарастания через `deriv()`, прогнозирование, объединение нескольких источников).
- **Минусы:** Двойная задержка (scrape_interval Kafka Exporter + scrape_interval Prometheus + pollingInterval KEDA), что критично для систем реального времени.

### Алгоритм вычисления целевых реплик и связь с партициями

Для триггера `type: kafka` KEDA регистрирует внешнюю метрику в HPA со спецификацией типа `AverageValue`:

```text
desiredReplicas = ceil( totalLag / lagThreshold )
```

Например:
- `totalLag = 450` сообщений, `lagThreshold = 100`:
  `desiredReplicas = ceil(450 / 100) = 5` подов.

#### Фундаментальное ограничение модели партиционирования Kafka

В протоколе Apache Kafka партиция является неделимой единицей параллелизма: **одну партицию в рамках одной Consumer Group может читать только один поток/под**. 

```text
Топик: orders (Всего партиций: 4)
Консьюмер-группа: orders-workers

Случай 1 (Replicas = 4):
Part-0 ───▶ Pod-1
Part-1 ───▶ Pod-2
Part-2 ───▶ Pod-3
Part-3 ───▶ Pod-4
[100% утилизация ресурсов]

Случай 2 (Replicas = 6):
Part-0 ───▶ Pod-1
Part-1 ───▶ Pod-2
Part-2 ───▶ Pod-3
Part-3 ───▶ Pod-4
         Pod-5 (IDLE — не назначено ни одной партиции)
         Pod-6 (IDLE — не назначено ни одной партиции)
[Бесполезный расход ресурсов узлов Kubernetes]
```

#### Защита от лишних реплик в KEDA

По умолчанию KEDA включает механизм защиты (`allowIdleConsumers: false`). Если расчетная метрика требует больше подов, чем число партиций топика, KEDA искусственно срезает значение метрики, передаваемое в Metrics Server:

```text
maxAllowedMetric = numberOfPartitions × lagThreshold
reportedMetric = min( totalLag, maxAllowedMetric )
```

Таким образом, HPA гарантированно никогда не запросит больше подов, чем доступно партиций в топике.

### Продвинутые режимы распределения нагрузки

#### 1. Режим `limitToPartitionsWithLag`

В production часто возникает перекос ключей (Key Skew) — из 10 партиций сообщения поступают только в 2, а остальные 8 пусты.
- По умолчанию KEDA масштабирует консьюмеры вплоть до всех 10 партиций.
- При включении `limitToPartitionsWithLag: true` KEDA подсчитывает число партиций с `lag > 0`. Если отставание наблюдается только на 2 партициях, максимальное число реплик будет ограничено двумя. Это предотвращает запуск подов, которым не достанется работы.
- *Ограничение:* требует обязательного указания параметра `topic` и несовместимо с `allowIdleConsumers: true` и `ensureEvenDistributionOfPartitions: true`.

#### 2. Режим `ensureEvenDistributionOfPartitions`

Если топик имеет 10 партиций, а HPA масштабирует группу до 3 реплик:
- Pod-1 получит 4 партиции;
- Pod-2 получит 3 партиции;
- Pod-3 получит 3 партиции.
Нагрузка на Pod-1 на 33% выше остальных. При дальнейшем росте до 4 подов распределение изменится на `(3, 3, 2, 2)`, спровоцировав повторную ребалансировку.

Параметр `ensureEvenDistributionOfPartitions: true` ограничивает шкалу масштабирования только набором целых делителей числа партиций:
- Для топика с 10 партициями допустимые реплики: **1, 2, 5, 10**.
- При пороге `lagThreshold: 10`:
  - Lag от 1 до 10 ──▶ 1 реплика (10 партиций на под);
  - Lag от 11 до 20 ──▶ 2 реплики (по 5 партиций на под);
  - Lag от 21 до 50 ──▶ 5 реплик (по 2 партиции на под);
  - Lag от 51 и выше ──▶ 10 реплик (по 1 партиции на под).

### Защита от «отравленных сообщений» (Poison Pills) через `excludePersistentLag`

Если в партицию попало поврежденное сообщение, на котором консьюмер аварийно завершается или зацикливается, смещение не продвигается:
1. `High-Watermark` продолжает расти или остается постоянным;
2. `Committed Offset` не сдвигается;
3. KEDA фиксирует высокий лаг и масштабирует Deployment до `maxReplicaCount`;
4. Все доступные реплики простаивают, либо поочередно падают на той же партиции, создавая паразитный расход вычислительных ресурсов.

При установке `excludePersistentLag: true` KEDA сохраняет значение оффсета предыдущего цикла (`previousOffset`). Если в текущем цикле `currentOffset == previousOffset`, данная партиция временно исключается из подсчета общего лага. Это предотвращает неуправляемый scale-up до устранения инцидента инженерами SRE.

### Инициализация группы и политика `offsetResetPolicy`

Когда разворачивается новая consumer group, записей в `__consumer_offsets` еще не существует. Запрос смещения возвращает статус `INVALID_OFFSET`. KEDA реагирует согласно `offsetResetPolicy`:

| `offsetResetPolicy` | Поведение KEDA | Поведение пода | Назначение |
|:---|:---|:---|:---|
| `earliest` | Скейлер принимает `committedOffset = 0` и считает лаг равным `High-Watermark`. Если топик пуст — масштабирует в 0. При появлении данных запускает под. | Консьюмер вычитывает историю с начала партиции. | Очереди задач, аудит, ETL-пайплайны. |
| `latest` | Скейлер возвращает отрицательный лаг (`-1`), но принудительно выставляет статус активности триггера `IsActive=true`. HPA удерживает `minReplicaCount` (или 1 под). | Консьюмер подключается к брокеру, регистрирует позицию и фиксирует первый оффсет. | Потоковая телеметрия, real-time события. |

> [!WARNING]
> **Опасность Scale-to-Zero без указания топика:** Если `topic` не задан в манифесте ScaledObject, а нагрузка уменьшилась до 0 реплик, по истечении срока хранения смещений в Kafka (`offsets.retention.minutes`, по умолчанию 7 суток) брокер удалит данные о группе. KEDA потеряет информацию о топиках группы и никогда больше не сможет масштабировать нагрузку из нуля. Для scale-to-zero всегда явно указывайте имя `topic`.

### Оптимизация памяти KEDA Operator: `fullMetadata: false`

По умолчанию KEDA инициализирует клиент Sarama с запросом метаданных обо всех топиках и брокерах кластера. 
- На enterprise-кластерах с тысячами топиков и десятками тысяч партиций каждый цикл опроса генерирует многомегабайтные ответы.
- Это вызывает резкие скачки потребления памяти (RAM spikes) и периодические падения пода `keda-operator` по **OOMKilled** (exit code 137).
- Установка `fullMetadata: false` заставляет KEDA передавать имя конкретного топика в `MetadataRequest`, сокращая объем передаваемых данных на 99% и стабилизируя работу оператора. Требует обязательного задания поля `topic`.

---

## Спецификация параметров триггера Kafka

| Параметр | Обязательный | По умолчанию | Допустимые значения | Описание |
|:---|:---|:---|:---|:---|
| `bootstrapServers` | Да | — | Строка хостов: `host1:port,host2:port` | Адреса брокеров Kafka для bootstrap-подключения. |
| `consumerGroup` | Да | — | Строка | Имя потребительской группы. Должно в точности совпадать с именем группы в конфигурации приложения-консьюмера. |
| `topic` | Нет | — | Строка | Имя топика. При отсутствии лаг суммируется по всем топикам, на которые подписана группа. |
| `lagThreshold` | Нет | `10` | Целое положительное число | Целевой порог среднего лага на один под для HPA. |
| `activationLagThreshold` | Нет | `0` | Целое неотрицательное число | Порог лага для перехода из 0 реплик в 1. |
| `offsetResetPolicy` | Нет | `latest` | `latest`, `earliest` | Политика расчета лага при отсутствии зафиксированного смещения. |
| `allowIdleConsumers` | Нет | `false` | `true`, `false` | Разрешение масштабирования сверх числа партиций. |
| `limitToPartitionsWithLag` | Нет | `false` | `true`, `false` | Ограничение максимальных реплик числом партиций с лагом > 0. |
| `ensureEvenDistributionOfPartitions` | Нет | `false` | `true`, `false` | Масштабирование только до чисел-делителей количества партиций. |
| `excludePersistentLag` | Нет | `false` | `true`, `false` | Исключение «зависших» партиций без продвижения оффсета. |
| `scaleToZeroOnInvalidOffset` | Нет | `false` | `true`, `false` | Масштабирование в 0 при отсутствии валидного смещения. |
| `fullMetadata` | Нет | `true` | `true`, `false` | Ограничение запроса метаданных целевым топиком (`false`). |
| `partitionLimitation` | Нет | — | Диапазоны через запятую: `"0,1,5-8"` | Учет лага только для указанного списка партиций. |
| `version` | Нет | `1.0.0` | Версия Kafka (например, `3.8.0`) | Версия протокола брокера для библиотеки Sarama. |
| `sasl` | Нет | `none` | `none`, `plaintext`, `scram_sha256`, `scram_sha512`, `gssapi`, `oauthbearer` | Механизм SASL-аутентификации. |
| `tls` | Нет | `disable` | `enable`, `disable` | Включение шифрования и аутентификации TLS. |
| `unsafeSsl` | Нет | `false` | `true`, `false` | Пропуск проверки валидности сертификатов (не рекомендуется в prod). |

---

## Практические сценарии и конфигурация

### Сценарий 1: Production Deployment с защитой от Rebalance Storm и Scale-to-Zero

Масштабирование воркеров обработки заказов из Kafka со сглаживанием резких колебаний (flapping) через HPA `behavior`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-consumer
  namespace: processing
spec:
  replicas: 1
  selector:
    matchLabels:
      app: orders-consumer
  template:
    metadata:
      labels:
        app: orders-consumer
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: worker
          image: internal-registry.corp/processing/orders-consumer:v2.4.0
          env:
            - name: KAFKA_BOOTSTRAP_SERVERS
              value: "kafka-broker-0.kafka.svc.cluster.local:9092,kafka-broker-1.kafka.svc.cluster.local:9092,kafka-broker-2.kafka.svc.cluster.local:9092"
            - name: KAFKA_GROUP_ID
              value: "orders-processor-group"
            - name: KAFKA_TOPIC
              value: "telemetry.orders"
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 1Gi
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orders-consumer-scaler
  namespace: processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: orders-consumer
  minReplicaCount: 0
  maxReplicaCount: 12                  # Не должно превышать число партиций топика (12)
  pollingInterval: 15
  cooldownPeriod: 180                  # Ожидание 3 минуты перед финальным scale-to-zero
  idleReplicaCount: 0
  fallback:
    failureThreshold: 3
    replicas: 2                        # Аварийный режим при потере связи с брокером
  advanced:
    restoreToOriginalReplicaCount: false
    horizontalPodAutoscalerConfig:
      name: keda-hpa-orders-consumer
      behavior:
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
        scaleDown:
          stabilizationWindowSeconds: 300  # 5 минут сглаживания для предотвращения rebalance storm
          policies:
            - type: Percent
              value: 25
              periodSeconds: 60
          selectPolicy: Min
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: "kafka-broker-0.kafka.svc.cluster.local:9092,kafka-broker-1.kafka.svc.cluster.local:9092,kafka-broker-2.kafka.svc.cluster.local:9092"
        consumerGroup: orders-processor-group
        topic: telemetry.orders
        lagThreshold: "100"
        activationLagThreshold: "10"
        offsetResetPolicy: latest
        allowIdleConsumers: "false"
        fullMetadata: "false"          # Запрашивать метаданные только топика orders
        excludePersistentLag: "true"   # Защита от poison pill
```

### Сценарий 2: Аутентификация SASL/SCRAM-SHA-512 (On-Premise / Strimzi)

Стандарт промышленной безопасности: учетные данные вынесены в Secret и подключены через `TriggerAuthentication`.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-scram-secret
  namespace: processing
type: Opaque
stringData:
  username: "keda-metrics-user"
  password: "KedaComplexPassword#2026"
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-scram-auth
  namespace: processing
spec:
  secretTargetRef:
    - parameter: username
      name: kafka-scram-secret
      key: username
    - parameter: password
      name: kafka-scram-secret
      key: password
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: secure-kafka-scaler
  namespace: processing
spec:
  scaleTargetRef:
    name: orders-consumer
  minReplicaCount: 1
  maxReplicaCount: 16
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: "kafka-cluster-kafka-bootstrap.kafka.svc:9092"
        consumerGroup: orders-processor-group
        topic: telemetry.orders
        lagThreshold: "50"
        sasl: scram_sha512             # Тип механизма SASL
      authenticationRef:
        name: kafka-scram-auth
```

### Сценарий 3: Двусторонняя аутентификация по TLS (mTLS)

Для закрытых enterprise-контуров с шифрованием и валидацией клиентских сертификатов на брокерах.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-mtls-secret
  namespace: processing
type: Opaque
stringData:
  ca.crt: |
    -----BEGIN CERTIFICATE-----
    MIIDXTCCAkWgAwIBAgIJALa1...[CA Root Certificate]...
    -----END CERTIFICATE-----
  tls.crt: |
    -----BEGIN CERTIFICATE-----
    MIIDWjCCAkKgAwIBAgIJAO89...[KEDA Client Certificate]...
    -----END CERTIFICATE-----
  tls.key: |
    -----BEGIN RSA PRIVATE KEY-----
    MIIEowIBAAKCAQEA0r12...[KEDA Client Private Key]...
    -----END RSA PRIVATE KEY-----
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-mtls-auth
  namespace: processing
spec:
  secretTargetRef:
    - parameter: ca
      name: kafka-mtls-secret
      key: ca.crt
    - parameter: cert
      name: kafka-mtls-secret
      key: tls.crt
    - parameter: key
      name: kafka-mtls-secret
      key: tls.key
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: mtls-kafka-scaler
  namespace: processing
spec:
  scaleTargetRef:
    name: orders-consumer
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: "kafka-headless.kafka.svc:9093"
        consumerGroup: orders-processor-group
        topic: telemetry.orders
        lagThreshold: "200"
        tls: enable                    # Включение TLS
      authenticationRef:
        name: kafka-mtls-auth
```

### Сценарий 4: Корпоративная Kerberos-аутентификация (SASL/GSSAPI)

При интеграции со с корпоративными Active Directory / FreeIPA и Kerberos KDC.

#### 1. Подготовка deployment оператора KEDA (Helm values)
KEDA оператор должен иметь доступ к разделяемой памяти для Kerberos credential cache:

```yaml
# keda-values.yaml
volumes:
  operator:
    extraVolumes:
      - name: temp-kerberos-vol
        emptyDir:
          medium: Memory
    extraVolumeMounts:
      - name: temp-kerberos-vol
        mountPath: /tmp/kerberos
        readOnly: false
```

#### 2. Манифест ScaledObject и TriggerAuthentication

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kafka-kerberos-secret
  namespace: processing
type: Opaque
stringData:
  username: "keda-service-account"
  realm: "CORP.INTERNAL"
  kerberosServiceName: "kafka"
  kerberosConfig: |
    [libdefaults]
    default_realm = CORP.INTERNAL
    dns_lookup_kdc = false
    dns_lookup_realm = false
    ticket_lifetime = 24h
    forwardable = true
    [realms]
    CORP.INTERNAL = {
      kdc = kdc01.corp.internal:88
      admin_server = kdc01.corp.internal:749
    }
data:
  # Base64-encoded keytab-файл сервисной учетной записи KEDA
  keytab: "BQIAAABrAAIA..."
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-kerberos-auth
  namespace: processing
spec:
  secretTargetRef:
    - parameter: username
      name: kafka-kerberos-secret
      key: username
    - parameter: realm
      name: kafka-kerberos-secret
      key: realm
    - parameter: kerberosServiceName
      name: kafka-kerberos-secret
      key: kerberosServiceName
    - parameter: kerberosConfig
      name: kafka-kerberos-secret
      key: kerberosConfig
    - parameter: keytab
      name: kafka-kerberos-secret
      key: keytab
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kerberos-kafka-scaler
  namespace: processing
spec:
  scaleTargetRef:
    name: orders-consumer
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: "kafka-broker-01.corp.internal:9092"
        consumerGroup: orders-processor-group
        topic: telemetry.orders
        lagThreshold: "100"
        sasl: gssapi
      authenticationRef:
        name: kafka-kerberos-auth
```

### Сценарий 5: Масштабирование через Kafka Exporter и Prometheus

Используется, если сетевые политики безопасности запрещают прямое подключение из KEDA в кластер Kafka, либо когда требуется фильтрация по производной лага.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-prom-scaler
  namespace: processing
spec:
  scaleTargetRef:
    name: orders-consumer
  minReplicaCount: 1
  maxReplicaCount: 16
  pollingInterval: 30
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-k8s.monitoring.svc:9090
        metricName: kafka_consumergroup_lag_orders
        query: |
          sum(kafka_consumergroup_lag{consumergroup="orders-processor-group",topic="telemetry.orders"})
        threshold: "150"
        activationThreshold: "20"
```

---

## Операции и команды диагностики

Все команды приводятся с ожидаемым выводом в реальном окружении Kubernetes и Apache Kafka.

### 1. Проверка статуса ScaledObject и привязанного HPA

```bash
kubectl get scaledobject orders-consumer-scaler -n processing
```
```text
# → NAME                     SCALETARGETKIND      SCALETARGETNAME   MIN   MAX   TRIGGERS   AUTHENTICATION        READY   ACTIVE   FALLBACK   AGE
# → orders-consumer-scaler   apps/v1/Deployment   orders-consumer   0     12    kafka      kafka-scram-auth      True    True     False      14m
```

```bash
kubectl get hpa -n processing -l app.kubernetes.io/managed-by=keda.sh
```
```text
# → NAME                               REFERENCE                    TARGETS          MINPODS   MAXPODS   REPLICAS   AGE
# → keda-hpa-orders-consumer-scaler    Deployment/orders-consumer   350/100 (avg)    1         12        4          14m
```

### 2. Детальное инспектирование условий (Conditions) и текущей метрики

```bash
kubectl describe scaledobject orders-consumer-scaler -n processing
```
```text
# → Name:         orders-consumer-scaler
# → Namespace:    processing
# → Status:
# →   Conditions:
# →     Type:            Ready
# →     Status:          True
# →     Reason:          ScaledObjectReady
# →     Message:         ScaledObject is ready for scaling
# →     Type:            Active
# →     Status:          True
# →     Reason:          ScalerActive
# →     Message:         Scaler is active
# →   Current Metrics:
# →     Resource Name:   kafka-telemetry.orders
# →     Current Value:   350
# →   External Metric Names:
# →     s0-kafka-telemetry.orders
# → Events:
# →   Type    Reason             Age   From           Message
# →   ----    ------             ----  ----           -------
# →   Normal  ScaledObjectReady  14m   keda-operator  ScaledObject is ready for scaling
```

### 3. Прямой запрос метрики через Kubernetes External Metrics API

Проверка значения лага, которое KEDA транслирует в контроллер HPA:

```bash
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/processing/s0-kafka-telemetry.orders" | jq .
```
```json
# → {
# →   "kind": "ExternalMetricValueList",
# →   "apiVersion": "external.metrics.k8s.io/v1beta1",
# →   "metadata": {},
# →   "items": [
# →     {
# →       "metricName": "s0-kafka-telemetry.orders",
# →       "metricLabels": {},
# →       "timestamp": "2026-10-13T17:15:00Z",
# →       "value": "350"
# →     }
# →   ]
# → }
```

### 4. Проверка состояния группы и партиций со стороны Apache Kafka

Запуск консольной утилиты внутри кластера для валидации High-Watermark и Committed Offset:

```bash
kubectl run -it --rm kafka-cli --image=apache/kafka:3.8.0 --restart=Never -n processing -- \
  /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka-broker-0.kafka.svc:9092 \
  --describe --group orders-processor-group
```
```text
# → GROUP                  TOPIC             PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST            CLIENT-ID
# → orders-processor-group telemetry.orders  0          104500          104620          120             orders-w-0-1    /10.244.2.14    orders-w-0
# → orders-processor-group telemetry.orders  1          98400           98480           80              orders-w-1-2    /10.244.3.22    orders-w-1
# → orders-processor-group telemetry.orders  2          112000          112100          100             orders-w-2-3    /10.244.1.89    orders-w-2
# → orders-processor-group telemetry.orders  3          89050           89100           50              orders-w-3-4    /10.244.4.10    orders-w-3
# → pod "kafka-cli" deleted
```

### 5. Проверка сетевой связности и портов из пода keda-operator

```bash
kubectl exec -n keda deployment/keda-operator -- nc -zv -w 3 kafka-broker-0.kafka.svc 9092
```
```text
# → Connection to kafka-broker-0.kafka.svc (10.96.12.44) 9092 port [tcp/*] succeeded!
```

### 6. Анализ логов KEDA Operator на предмет ошибок Sarama/Kafka

```bash
kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=50 | grep -i "kafka"
```
```text
# → 2026-10-13T17:10:02Z INFO scale_handler Successfully fetched metrics for trigger {"scaler": "kafka", "topic": "telemetry.orders", "lag": 350}
# → 2026-10-13T17:10:17Z INFO scale_handler Successfully fetched metrics for trigger {"scaler": "kafka", "topic": "telemetry.orders", "lag": 310}
```

---

## Устранение неполадок (Troubleshooting)

### Матрица типовых неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
|:---|:---|:---|:---|
| `ScaledObject Ready=False`, ошибка `context deadline exceeded` | Нет сетевого доступа от пода `keda-operator` к брокерам, либо заблокирован порт NetworkPolicy. | `kubectl logs -n keda deployment/keda-operator \| grep -i "kafka"` | Проверить NetworkPolicy, открыть порты 9092/9093 в namespace `kafka`. Проверить DNS-резолвинг. |
| Лаг растет, но число подов не увеличивается (`Replicas: 1`) | Несовпадение имени `consumerGroup` в коде сервиса и в ScaledObject; либо `lagThreshold` завышен. | Сравнить `consumerGroup` из ScaledObject с выводом `kafka-consumer-groups.sh --list`. | Привести имя группы в ScaledObject в строгое соответствие с приложением. |
| Поды масштабируются до максимума и простаивают без трафика | `maxReplicaCount` превышает число партиций топика при `allowIdleConsumers: true`. | Выполнить `kafka-topics.sh --describe` и сравнить с `maxReplicaCount`. | Выставить `maxReplicaCount` равным числу партиций; включить `allowIdleConsumers: false`. |
| Flapping: число подов циклично скачет, в логах постоянные rebalances | Слишком короткий `cooldownPeriod`, отсутствие stabilization window в HPA behavior. | Изучить события `kubectl get events -n processing` и логи ребалансировки в подах. | Увеличить `cooldownPeriod` до 300с; настроить `behavior.scaleDown.stabilizationWindowSeconds: 300`. Перевести консьюмеры на `CooperativeStickyAssignor`. |
| Runaway scale-up до максимума из-за одной партиции | В партицию попало отравленное сообщение (poison pill), оффсет не двигается, остальные вычитаны. | `kafka-consumer-groups.sh --describe` (одна партиция имеет огромный неизменный лаг). | Включить `excludePersistentLag: true`; направить poison pill в DLQ (Dead Letter Queue). |
| `keda-operator` падает по OOMKilled (Exit Code 137) | Кластер содержит тысячи топиков; Sarama запрашивает метаданные всех сущностей. | `kubectl describe pod -n keda keda-operator-...` (Last State: OOMKilled). | Выставить `fullMetadata: false` и явно указать параметр `topic`. Увеличить `resources.limits.memory` оператора. |
| При первом старте приложения под не поднимается из 0 | Установлен `offsetResetPolicy: earliest`, но топик абсолютно пуст (High-Watermark = 0). | Проверить `Status.CurrentMetrics` у ScaledObject. | Это штатное поведение. При появлении первого сообщения лаг станет равен 1 и под запустится. |

### Разбор критических кейсов

#### Кейс 1: Consumer Rebalance Storm при резком автоскейлинге

**Проблема:** При наплыве сообщений KEDA резко заказывает +6 реплик. Стандартный протокол Eager Rebalance (`RangeAssignor` / `RoundRobinAssignor`) останавливает чтение во всех подах (Stop-the-World), чтобы перераспределить партиции. В процессе ребалансировки обработка замирает, лаг возрастает еще сильнее, KEDA добавляет еще поды, вызывая бесконечный ребалансировочный шторм.

**Решение:**
1. В конфигурации Java/Go/Python консьюмеров включить кооперативный протокол:
   ```properties
   # client.properties
   partition.assignment.strategy=org.apache.kafka.clients.consumer.CooperativeStickyAssignor
   ```
2. В ScaledObject ограничить скорость масштабирования вниз и вверх через `advanced.horizontalPodAutoscalerConfig.behavior` (см. Сценарий 1).

#### Кейс 2: Потеря смещений при Scale-to-Zero и тайм-аут retention

**Проблема:** Консьюмер масштабирован в 0 реплик. В течение 7 дней сообщений не поступало. Kafka удалила метаданные группы из `__consumer_offsets`. При поступлении нового сообщения KEDA не видит группу и не может определить топик, если поле `topic` было опущено.

**Решение:**
1. Всегда явно декларировать `topic` в триггере ScaledObject.
2. Для критичных сервисов устанавливать `minReplicaCount: 1`.

---

## Рекомендации и лучшие практики (Best Practices)

### 1. SRE-гардрейлы и лимиты
- **Правило потолка партиций:** Значение `maxReplicaCount` никогда не должно превышать общее число партиций в топике:
  ```text
  maxReplicaCount ≤ PartitionsCount(topic)
  ```
  Если для обработки пиков требуется больше подов — необходимо предварительно расширить число партиций в Kafka (`kafka-topics.sh --alter --partitions N`).
- **Защита от нулевого деления:** Если топик динамически создается с 1 партицией, выставляйте `maxReplicaCount: 1`.

### 2. Согласование Graceful Shutdown и Kafka Poll Timeout
При уменьшении числа подов (scale down) Kubernetes отправляет контейнеру сигнал `SIGTERM`.
- Если под будет уничтожен (`SIGKILL`) до завершения обработки батча, смещение не зафиксируется, и сообщения будут повторно обработаны другим подом (at-least-once дубликаты).
- Параметр `terminationGracePeriodSeconds` в PodSpec должен удовлетворять условию:
  ```text
  terminationGracePeriodSeconds > (max.poll.interval.ms / 1000) + BatchCommitDuration
  ```
- В коде приложения обязателен перехват `SIGTERM`, вызов `consumer.wakeup()` и явный коммит `commitSync()` перед выходом.

### 3. Настройка PodDisruptionBudget (PDB)
Чтобы плановый drain нод Kubernetes (при обновлении ядра или версии K8s) не останавливал всю группу консьюмеров:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: orders-consumer-pdb
  namespace: processing
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: orders-consumer
```

### 4. Сетевая безопасность и изоляция (NetworkPolicy)
KEDA Operator и Metrics Server размещаются в служебном пространстве имен `keda`, а брокеры Kafka — в `kafka`. Обеспечьте разрешение трафика:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-keda-to-kafka
  namespace: kafka
spec:
  podSelector:
    matchLabels:
      strimzi.io/name: prod-cluster-kafka
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: keda
      ports:
        - protocol: TCP
          port: 9092
        - protocol: TCP
          port: 9093
```

### 5. Prometheus-алерты для мониторинга KEDA Kafka Scaler

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: keda-kafka-alerts
  namespace: monitoring
spec:
  groups:
    - name: keda-kafka.rules
      rules:
        - alert: KedaKafkaScalerPausedOrError
          expr: keda_scaler_errors{scaler="kafka"} > 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "KEDA Kafka scaler encountering errors in {{ $labels.namespace }}"
            description: "KEDA cannot fetch consumer lag for {{ $labels.scaledObject }}. Check Kafka connectivity and credentials."

        - alert: KafkaConsumerLagBreachingSLAWithMaxPods
          expr: |
            (keda_scaler_metrics_value{scaler="kafka"} > 10000)
            and
            (kube_deployment_status_replicas_available{deployment="orders-consumer"} == 12)
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "Consumer group orders-processor-group cannot keep up at max capacity"
            description: "Lag is > 10000 despite running at maxReplicaCount (12). Scale topic partitions or optimize processing pipeline."
```

---

## Дополнительная информация

### Внутренние связанные материалы
- [KEDA: Основные концепции](./keda_concepts.md) — фундаментальная архитектура, жизненный цикл CRD и контроллеров
- [KEDA: Эксплуатация и мониторинг](./keda-operations.md) — диагностика метрик-сервера, сбор логов и Prometheus-метрики KEDA
- [KEDA: FinOps-гардрейлы](./keda-finops.md) — экономика автомасштабирования и предотвращение утечек ресурсов
- [Strimzi: Kafka Operator для Kubernetes](../../../Kafka/strimzi_kafka_operator.md) — промышленное развертывание и эксплуатация кластеров Kafka в K8s
- [Kafka: Мониторинг](../../../Kafka/kafka_for_monitoring.md) — метрики брокеров, экспортеры и расчет SLO для очередей

### Внешняя документация
- [KEDA Official Docs: Apache Kafka Scaler](https://keda.sh/docs/latest/scalers/apache-kafka/)
- [Apache Kafka Consumer Group Protocol & Incremental Cooperative Rebalance](https://cwiki.apache.org/confluence/display/KAFKA/KIP-429%3A+Kafka+Consumer+Partial+Revocation)
- [IBM Sarama Library Repository](https://github.com/IBM/sarama)
