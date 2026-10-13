# KEDA: Эксплуатация — мониторинг и troubleshooting

**Актуально для:** KEDA 2.19.x / 2.20.x, Kubernetes 1.28–1.32+

## Определения

**KEDA Operator** — центральный контроллер Kubernetes (`keda-operator`), отвечающий за обработку пользовательских ресурсов (`ScaledObject`, `ScaledJob`, `TriggerAuthentication`), периодический опрос источников событий в режиме покоя (`0` реплик) и управление жизненным циклом стандартных объектов `HorizontalPodAutoscaler` (HPA) и `Job`.

**KEDA Metrics Server** — специализированный компонент (`keda-metrics-apiserver`), реализующий спецификацию Kubernetes External Metrics API (`external.metrics.k8s.io`). Выступает адаптером между `kube-controller-manager` (циклом HPA) и скейлерами KEDA, транслируя внешние метрики (размер очередей, latency, счетчики) в нативный формат метрик кластера.

**KEDA Admission Webhook** — валидирующий вебхук (`keda-admission-webhooks`), перехватывающий запросы на создание и изменение CRD KEDA. Проверяет корректность параметров триггеров, наличие обязательных полей и синтаксис спецификации до фиксации объектов в `etcd`.

**External Metrics API (`v1beta1.external.metrics.k8s.io`)** — точка расширения Kubernetes Aggregation Layer, через которую `kube-apiserver` проксирует вызовы контроллера HPA в под `keda-metrics-apiserver` для получения актуальных значений внешних триггеров.

**Leader Election** — механизм обеспечения высокой доступности `keda-operator`, использующий координационные примитивы Kubernetes (`Lease` в пространстве имён `keda`). При наличии нескольких реплик оператора опрос и управление объектами выполняет только один активный лидер; остальные реплики находятся в горячем резерве (standby).

**Fallback** — аварийный режим работы `ScaledObject`. Если скейлер KEDA не может связаться с источником метрик (сбой сети, недоступность брокера, ошибка аутентификации) в течение заданного числа попыток (`failureThreshold`), контроллер фиксирует количество подов на безопасном значении (`fallback.replicas`), предотвращая ложный сброс нагрузки в ноль.

**Scale-to-Zero** — цикл вывода рабочей нагрузки из эксплуатации до нуля реплик (`0` подов) при отсутствии входящих сообщений. Сокращает нецелевое потребление CPU и памяти, но требует контроля задержки холодного старта.

**Cold Start (Холодный старт)** — суммарное время, необходимое для перевода сервиса из состояния покоя (`0` подов) в состояние полной готовности обрабатывать входящий трафик (`1` под в статусе `Ready`). Включает обнаружение триггера, планирование пода, загрузку контейнерного образа и прохождение `readinessProbe`.

**Flapping (Осцилляция)** — нежелательный процесс непрерывного масштабирования вверх и вниз с коротким интервалом (1–3 минуты), возникающий из-за агрессивных порогов, отсутствия окна стабилизации или резких скачков метрик в источнике.

**Scaling Latency (Задержка масштабирования)** — сквозной временной интервал от момента появления события/сообщения в брокере до момента, когда созданный под воркера начинает его фактическую обработку.

**Pause Annotation (`autoscaling.keda.sh/paused`)** — специальная аннотация манифеста `ScaledObject`, позволяющая оперативно заморозить текущее количество реплик на время регламентных или восстановительных работ без удаления объекта автомасштабирования.

**Downstream Saturation** — состояние перегрузки зависимых внутренних инфраструктурных компонентов (реляционные базы данных, кэши, шины сообщений) из-за лавинообразного горизонтального расширения воркеров при пиковой нагрузке.

**Poison Message (Ядовитое сообщение)** — поврежденное или некорректное сообщение в очереди, вызывающее аварийное завершение воркера (CrashLoopBackOff) или повторный возврат в очередь (infinite retry loop), что приводит к искусственному удержанию максимального числа реплик (`maxReplicaCount`).

---

## Архитектура и эксплуатационные компоненты

### Компоненты KEDA в среде выполнения

KEDA функционирует в виде распределенного набора контроллеров и адаптеров внутри кластера:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   Kubernetes Cluster                                   │
│                                                                                        │
│   ┌────────────────────┐     watch CRDs     ┌──────────────────────────────────────┐   │
│   │   kube-apiserver   │ ◄───────────────── │     keda-operator (Deployment)       │   │
│   └─────────┬──────────┘                    │  - Leader Election (Lease)           │   │
│             │                               │  - Scale-to-Zero (0 <-> 1)           │   │
│             │ Aggregated API Proxy          │  - HPA Lifecycle Management          │   │
│             │ (/apis/external.metrics...)   └──────────────────┬───────────────────┘   │
│             ▼                                                  │                       │
│   ┌──────────────────────────────────────┐                     │                       │
│   │  keda-metrics-apiserver (Stateless)  │                     │ Poll (at 0 replicas)  │
│   │  - External Metrics API Provider     │                     │                       │
│   │  - Direct In-memory Scalers          │                     │                       │
│   └─────────────────┬────────────────────┘                     │                       │
│                     │                                          │                       │
└─────────────────────┼──────────────────────────────────────────┼───────────────────────┘
                      │ Query Metric (1 <-> N)                   │
                      ▼                                          ▼
       ┌──────────────────────────────────────────────────────────────────┐
       │     Внутренние инфраструктурные сервисы (On-Premises / Infra)    │
       │    [Apache Kafka]   [RabbitMQ]   [Redis]   [PostgreSQL]   [Prom] │
       └──────────────────────────────────────────────────────────────────┘
```

1. **`keda-operator`**:
   - Ведет наблюдение (watch) за ресурсами `ScaledObject`, `ScaledJob`, `TriggerAuthentication`.
   - Создает, обновляет и удаляет нативные ресурсы `HorizontalPodAutoscaler` для каждого `ScaledObject`.
   - Реализует масштабирование в ноль и выход из нуля (`0 ↔ 1`): стандартный HPA в Kubernetes не умеет масштабировать нагрузку до 0 реплик по внешним метрикам. Когда реплик 0, оператор самостоятельно выполняет цикл опроса с периодичностью `pollingInterval`. Как только значение превышает `activationThreshold`, оператор напрямую патчит subresource `/scale` целевого объекта (Deployment/StatefulSet), устанавливая `minReplicaCount` (обычно 1), после чего передает управление HPA.
   - Запускает и контролирует выполнение `Job` для спецификаций `ScaledJob`.

2. **`keda-metrics-apiserver`**:
   - Регистрируется в Kubernetes через `APIService` с именем `v1beta1.external.metrics.k8s.io`.
   - При активных репликах ($\ge 1$) встроенный контроллер `kube-controller-manager` (HPA controller) периодически (по умолчанию каждые 15 секунд) запрашивает внешние метрики у `kube-apiserver`, который проксирует их в `keda-metrics-apiserver`.
   - Выполняет запрос к внешнему источнику (Kafka, RabbitMQ, PostgreSQL, Prometheus) с помощью скейлера и возвращает текущее значение метрики обратно в HPA для расчета целевого числа реплик по стандартной формуле HPA:
     $$\text{DesiredReplicas} = \lceil \text{CurrentReplicas} \times \frac{\text{CurrentMetricValue}}{\text{TargetMetricValue}} \rceil$$

3. **`keda-admission-webhooks`**:
   - Предотвращает применение некорректных манифестов (неверные типы данных, отсутствующие триггеры, конфликтующие пороговые значения).
   - Использует mTLS-сертификаты, автоматически обновляемые встроенным генератором или через `cert-manager`.

### Отказоустойчивость (High Availability)

В производственных средах компоненты KEDA настраиваются с резервированием:
* **Operator Leader Election:** развертывается 2 или 3 реплики `keda-operator`. Активный инстанс захватывает `Lease` в namespace `keda`. При сбое пода или ноды резервный оператор перехватывает лидерство в течение 15 секунд (стандартный lease renewal period: 10s, lease duration: 15s).
* **Metrics Server Multi-Replica:** является stateless-компонентом. Развертывается минимум в 2 репликах под общим Service `keda-metrics-apiserver`. Запросы от `kube-apiserver` балансируются между репликами.
* **Webhook Multi-Replica:** развертывается в 2 репликах с `PodDisruptionBudget` для исключения блокировки развертываний манифестов при дренаже узлов.

### Сквозная задержка масштабирования (End-to-End Latency Breakdown)

Полная задержка от момента появления данных в брокере до старта их обработки складывается из пяти последовательных фаз:

```text
Фаза 1: Детекция события (Operator Polling)
├── Длительность: от 0 до pollingInterval (по умолчанию 30с)
└── При 0 реплик регулируется параметром spec.pollingInterval.

Фаза 2: Сбор метрик скейлером (Metric Scrape)
├── Длительность: keda_scaler_metrics_latency (10–500 мс)
└── Зависит от времени ответа источника (RTT до Kafka/Postgres/Prometheus).

Фаза 3: Расчет HPA и обновление статуса
├── Длительность: kube-controller-manager --horizontal-pod-autoscaler-sync-period (обычно 15с)
└── При активных репликах регулируется циклом HPA.

Фаза 4: Планирование и запуск подов (Scheduling & Container Runtime)
├── Длительность: от 2 до 60+ секунд
└── Зависит от наличия свободных нод, скорости Image Pull (кэширование слоев) и инициализации контейнера.

Фаза 5: Прохождение проверок готовности (Readiness Probe)
├── Длительность: initialDelaySeconds + (periodSeconds × failureThreshold)
└── Под считается готовым и получает сообщения только после перехода в статус Ready.
```

---

## Практические сценарии и конфигурация эксплуатации

### Сценарий 1: Отказоустойчивая установка KEDA в production (HA Helm Values)

Для промышленных on-premise кластеров развертывание KEDA выполняется через Helm с включением высокой доступности, распределения по узлам и интеграции с мониторингом:

```yaml
# values-production-ha.yaml
operator:
  replicaCount: 2
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchLabels:
                app.kubernetes.io/name: keda-operator
            topologyKey: kubernetes.io/hostname
  priorityClassName: system-cluster-critical
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi

metricsServer:
  replicaCount: 2
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchLabels:
                app.kubernetes.io/name: keda-metrics-apiserver
            topologyKey: kubernetes.io/hostname
  priorityClassName: system-cluster-critical
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi

webhooks:
  replicaCount: 2
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchLabels:
                app.kubernetes.io/name: keda-admission-webhooks
            topologyKey: kubernetes.io/hostname
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi

# Интеграция с Prometheus Operator
prometheus:
  metricServer:
    enabled: true
    port: 9022
    serviceMonitor:
      enabled: true
      interval: 15s
  operator:
    enabled: true
    port: 8080
    serviceMonitor:
      enabled: true
      interval: 15s
  webhooks:
    enabled: true
    port: 8080
    serviceMonitor:
      enabled: true
      interval: 15s

# Создание PodDisruptionBudget для сохранения доступности при дренаже нод
podDisruptionBudget:
  operator:
    minAvailable: 1
  metricServer:
    minAvailable: 1
  webhooks:
    minAvailable: 1
```

Команда установки или обновления с применением конфигурации:

```bash
helm upgrade --install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version 2.20.0 \
  -f values-production-ha.yaml
# → Release "keda" has been upgraded. Happy Helming!
```

### Сценарий 2: Сетевая изоляция компонентов (NetworkPolicy)

Компоненты KEDA требуют строго определенных сетевых доступов. Нарушение правил NetworkPolicy — одна из главных причин падения скейлеров (`context deadline exceeded`).

Манифест сетевой политики для пространства имён `keda`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: keda-operator-egress
  namespace: keda
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: keda-operator
  policyTypes:
    - Egress
  egress:
    # 1. Доступ к kube-apiserver (Control Plane)
    - ports:
        - protocol: TCP
          port: 6443
    # 2. Доступ к CoreDNS кластера
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # 3. Доступ к внутренним источникам метрик (Kafka, RabbitMQ, Redis, Prometheus)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - protocol: TCP
          port: 9090
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: middleware
      ports:
        - protocol: TCP
          port: 9092 # Kafka
        - protocol: TCP
          port: 5672 # RabbitMQ AMQP
        - protocol: TCP
          port: 15672 # RabbitMQ Management API
        - protocol: TCP
          port: 6379 # Redis
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: keda-metrics-server-ingress-egress
  namespace: keda
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: keda-metrics-apiserver
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Прием запросов от kube-apiserver (External Metrics API)
    - ports:
        - protocol: TCP
          port: 6443
        - protocol: TCP
          port: 443
  egress:
    # Опрос DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
    # Опрос брокеров и БД напрямую метрик-сервером
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: middleware
      ports:
        - protocol: TCP
          port: 9092
        - protocol: TCP
          port: 15672
        - protocol: TCP
          port: 6379
```

### Сценарий 3: Регламент регламентного обслуживания (Maintenance Mode / Pause Autoscaling)

При проведении регламентных работ на брокере (обновление кластера Kafka, ребалансировка партиций, миграция очередей RabbitMQ) автоскейлинг необходимо временно заморозить, чтобы воркеры не падали по таймаутам и не запускали лавину реплик.

1. Заморозка автомасштабирования (фиксация текущего числа подов):

```bash
kubectl annotate scaledobject order-consumer-scaler -n processing autoscaling.keda.sh/paused="true" --overwrite
# → scaledobject.keda.sh/order-consumer-scaler annotated
```

2. Проверка статуса заморозки в условиях:

```bash
kubectl get scaledobject order-consumer-scaler -n processing -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}'
# → ScaledObject is paused
```

3. Проведение технических работ на брокере. Поды приложения сохраняют свое текущее фиксированное количество и не масштабируются ни вверх, ни вниз.

4. Снятие аннотации паузы после завершения работ:

```bash
kubectl annotate scaledobject order-consumer-scaler -n processing autoscaling.keda.sh/paused-
# → scaledobject.keda.sh/order-consumer-scaler annotated
```

5. Плавное возобновление штатного контроля:

```bash
kubectl get scaledobject order-consumer-scaler -n processing
# → NAME                    SCALETARGETKIND   SCALETARGETNAME   MIN   MAX   TRIGGERS   READY   ACTIVE   AGE
# → order-consumer-scaler   Deployment        order-consumer    0     30    rabbitmq   True    True     45d
```

### Сценарий 4: Резервное копирование и Disaster Recovery (Velero)

Потеря манифестов `ScaledObject` и `TriggerAuthentication` приводит к удалению сгенерированных HPA и остановке динамического масштабирования. 

Для резервного копирования конфигураций KEDA с помощью Velero используется фильтрация по CRD-группе `keda.sh`:

```bash
# Создание бэкапа всех объектов KEDA во всем кластере
velero backup create keda-crds-backup \
  --include-resources scaledobjects.keda.sh,scaledjobs.keda.sh,triggerauthentications.keda.sh,clustertriggerauthentications.keda.sh \
  --include-cluster-resources=true \
  --wait
# → Backup completed with status: Completed.
```

Восстановление объектов при аварии в новом кластере:

```bash
velero restore create --from-backup keda-crds-backup --wait
# → Restore completed with status: Completed.
```

После восстановления оператор KEDA автоматически обнаруживает существующие `ScaledObject` и пересоздает связные объекты HPA в течение 10–30 секунд.

---

## Операции и команды

### Сводная таблица эксплуатационных команд

| Операция | Команда | Назначение и ожидаемый контекст |
| :--- | :--- | :--- |
| **Список объектов** | `kubectl get scaledobject,scaledjob -A` | Общий просмотр статусов `READY`, `ACTIVE`, `FALLBACK` |
| **Инспекция статуса** | `kubectl describe scaledobject <name> -n <ns>` | Анализ условий `Conditions`, ошибок скейлеров и событий `Events` |
| **Проверка HPA** | `kubectl describe hpa keda-hpa-<name> -n <ns>` | Анализ текущих значений метрик, переданных из KEDA в HPA |
| **Проверка APIService** | `kubectl get apiservice v1beta1.external.metrics.k8s.io` | Проверка доступности адаптера внешних метрик для kube-apiserver |
| **Сырой запрос метрики** | `kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" \| jq .` | Прямой опрос списка метрик, зарегистрированных в External API |
| **Чтение значения метрики** | `kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/<ns>/<metric_name>" \| jq .` | Получение фактического числового значения метрики от скейлера |
| **Проверка лидерства** | `kubectl get lease -n keda keda-operator` | Проверка держателя блокировки лидера среди реплик оператора |
| **Логи оператора** | `kubectl logs -n keda -l app.kubernetes.io/name=keda-operator -c keda-operator -f` | Мониторинг циклов синхронизации объектов и ошибок подключения |
| **Логи Metrics Server** | `kubectl logs -n keda -l app.kubernetes.io/name=keda-metrics-apiserver -f` | Диагностика входящих вызовов от HPA и выполнения PromQL/MQ запросов |

### Примеры выполнения команд с ожидаемым выводом

1. Проверка состояния всех объектов масштабирования в кластере:

```bash
kubectl get scaledobject -A
# → NAMESPACE    NAME                    SCALETARGETKIND   SCALETARGETNAME   MIN   MAX   TRIGGERS   READY   ACTIVE   FALLBACK   AGE
# → processing   order-consumer-scaler   Deployment        order-consumer    0     25    rabbitmq   True    True     False      14d
# → telemetry    kafka-metrics-worker    Deployment        kafka-worker      1     50    kafka      True    False    False      32d
# → payments     billing-batch-scaler    Deployment        billing-worker    0     10    postgresql True    False    False      4d
```

2. Проверка состояния лидерства (Leader Election Lease):

```bash
kubectl get lease keda-operator -n keda -o yaml
# → apiVersion: coordination.k8s.io/v1
# → kind: Lease
# → metadata:
# →   name: keda-operator
# →   namespace: keda
# → spec:
# →   holderIdentity: keda-operator-7b696f8c79-w4x9p
# →   leaseDurationSeconds: 15
# →   renewTime: "2026-10-13T15:20:01.458921Z"
```

3. Проверка регистрации и статуса External Metrics APIService:

```bash
kubectl get apiservice v1beta1.external.metrics.k8s.io
# → NAME                                SERVICE                     AVAILABLE   AGE
# → v1beta1.external.metrics.k8s.io     keda/keda-metrics-server   True        90d
```

4. Прямой запрос метрики скейлера через API Aggregation Layer:

```bash
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/processing/s0-rabbitmq-orders" | jq .
# → {
# →   "kind": "ExternalMetricValueList",
# →   "apiVersion": "external.metrics.k8s.io/v1beta1",
# →   "metadata": {},
# →   "items": [
# →     {
# →       "metricName": "s0-rabbitmq-orders",
# →       "metricLabels": {},
# →       "timestamp": "2026-10-13T15:21:00Z",
# →       "value": "42"
# →     }
# →   ]
# → }
```

5. Извлечение сообщений об ошибках из статуса `ScaledObject`:

```bash
kubectl get scaledobject order-consumer-scaler -n processing -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.reason}{"\t"}{.message}{"\n"}{end}'
# → Ready       True    ScaledObjectReady       ScaledObject is ready for scaling
# → Active      True    MetricsValueHigherThanTarget    Trigger rabbitmq is active
# → Fallback    False   NoFallbackOccurred      No fallback occurred
```

6. Сетевой тест подключения к брокеру очередей из тестового пода в кластере:

```bash
kubectl run net-test --image=curlimages/curl:8.5.0 --rm -it --restart=Never -n keda -- \
  curl -s -u "guest:guest" "http://rabbitmq.middleware.svc.cluster.local:15672/api/queues/%2F/orders" | jq '.messages'
# → 148
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Система алертов Prometheus для мониторинга KEDA

Промышленный набор алертов (`PrometheusRule`) для выявления деградации компонентов и сбоев опроса:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: keda-operational-alerts
  namespace: keda
  labels:
    role: alert-rules
spec:
  groups:
    - name: keda.operations
      rules:
        # 1. Отказ оператора KEDA
        - alert: KEDAOperatorDown
          expr: up{job="keda-operator"} == 0
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "Оператор KEDA недоступен"
            description: "Инстанс keda-operator {{ $labels.instance }} не отвечает. Переход 0 <-> 1 остановлен."

        # 2. Отказ Metrics Server (деградация HPA)
        - alert: KEDAMetricsServerDown
          expr: up{job="keda-metrics-server"} == 0
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "KEDA Metrics Server недоступен"
            description: "External Metrics API не отвечает. HPA заблокирован и держит текущее число реплик."

        # 3. APIService в состоянии Unavailable
        - alert: KEDAExternalMetricsAPIServiceUnavailable
          expr: kube_apiservice_status_condition{apiservice="v1beta1.external.metrics.k8s.io",condition="Available",status="true"} == 0
          for: 3m
          labels:
            severity: critical
          annotations:
            summary: "APIService v1beta1.external.metrics.k8s.io недоступен"
            description: "kube-apiserver не может проксировать запросы к keda-metrics-apiserver. Проверьте TLS-сертификаты и порт 6443."

        # 4. Высокая частота ошибок скейлеров
        - alert: KEDAScalerErrorsHigh
          expr: sum by (scaledObject, namespace, scaler) (rate(keda_scaler_errors_total[5m])) > 0.05
          for: 3m
          labels:
            severity: warning
          annotations:
            summary: "Скейлер {{ $labels.scaler }} возвращает ошибки"
            description: "Скейлер объекта {{ $labels.scaledObject }} в пространстве {{ $labels.namespace }} не может опросить источник."

        # 5. Активация аварийного режима Fallback
        - alert: KEDAFallbackTriggered
          expr: keda_scaledobject_fallback_activity == 1
          for: 2m
          labels:
            severity: warning
          annotations:
            summary: "ScaledObject {{ $labels.scaledObject }} перешел в Fallback"
            description: "Сбой сбора метрик длится более failureThreshold. Рабочая нагрузка удерживается на фиксированном числе реплик."

        # 6. Упор в максимальный лимит масштабирования
        - alert: KEDAMaxReplicasReached
          expr: keda_scaledobject_replicas >= keda_scaledobject_max_replicas
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "ScaledObject {{ $labels.scaledObject }} достиг maxReplicaCount"
            description: "Воркеры работают на максимуме ({{ $value }} реплик) более 10 минут. Риск накопления очереди или деградации SLA."

        # 7. Высокая задержка опроса метрик скейлером (P95)
        - alert: KEDAScalerMetricsLatencyHigh
          expr: histogram_quantile(0.95, rate(keda_scaler_metrics_latency_seconds_bucket[5m])) > 5
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Задержка получения метрик скейлером превышает 5 секунд"
            description: "Скейлер {{ $labels.scaler }} отвечает медленно (P95 > 5s). Проверьте нагрузку на источник метрик."
```

### Сценарии типовых инцидентов и Runbooks

#### Инцидент 1: Cold start съедает SLA и вызывает 504 Gateway Timeout

* **Симптомы:** При масштабировании из нуля (`0 → 1`) клиенты получают HTTP 504, сообщения в очереди накапливаются без обработки в течение 30–90 секунд.
* **Причины:**
  1. Большой объем Docker-образа (1+ ГБ), приводящий к длительному `image pull` на нодах без кэша.
  2. Долгая инициализация рантайма (прогрев JVM, загрузка моделей, предварительное заполнение кэшей).
  3. Неоптимальные параметры `readinessProbe` (большой `initialDelaySeconds` или редкий `periodSeconds`).
* **Диагностика:**
  ```bash
  # Анализ задержки старта подов
  kubectl get events -n processing --sort-by='.lastTimestamp' | grep -E "Pulling|Pulled|Started"
  # → 2m   Normal   Pulling   pod/order-consumer-xxx   Pulling image "registry.local/worker:v2"
  # → 1m   Normal   Pulled    pod/order-consumer-xxx   Successfully pulled image (took 58s)
  ```
* **Решение:**
  1. Если задержка инициализации приложения непреодолима на уровне кода — отказаться от `scale-to-zero`, зафиксировав минимальную реплику:
     ```yaml
     minReplicaCount: 1 # Удержание одного теплого воркера исключает фазу cold start
     ```
  2. Использовать `startupProbe` для защиты от ложных перезапусков при тяжелом старте с частым шагом опроса:
     ```yaml
     startupProbe:
       httpGet:
         path: /healthz
         port: 8080
       failureThreshold: 30
       periodSeconds: 2 # Проверка каждые 2 секунды позволяет перейти в Ready сразу после запуска
     ```
  3. Настроить предварительное кэширование базовых образов на рабочих нодах с помощью `DaemonSet` или image pre-pulling контроллеров.

#### Инцидент 2: Флаппинг реплик (осцилляция $0 \leftrightarrow N$)

* **Симптомы:** Каждые 2–3 минуты число подов меняется: $0 \to 10 \to 0 \to 10$. Постоянный churn подов, перегрузка Kube-API и планировщика.
* **Причины:**
  1. Слишком короткий `cooldownPeriod` в `ScaledObject`.
  2. Отсутствие окна стабилизации в конфигурации поведения HPA (`behavior.scaleDown.stabilizationWindowSeconds`).
  3. Высокая чувствительность триггера: один воркер моментально вычитывает батч сообщений, очередь пустеет, KEDA инициирует scale down, затем поступает следующая порция.
* **Диагностика:**
  ```bash
  # Мониторинг масштабирования в реальном времени
  kubectl get hpa keda-hpa-order-consumer-scaler -n processing -w
  ```
* **Решение:**
  Скорректировать спецификацию `ScaledObject`, добавив сглаживание и окно стабилизации:
  ```yaml
  spec:
    cooldownPeriod: 300 # Удержание реплик не менее 5 минут после опустошения очереди
    advanced:
      horizontalPodAutoscalerConfig:
        behavior:
          scaleDown:
            stabilizationWindowSeconds: 300
            policies:
              - type: Percent
                value: 20
                periodSeconds: 60 # Плавное уменьшение максимум на 20% в минуту
  ```

#### Инцидент 3: Упор в `maxReplicaCount` и насыщение downstream-систем (БД / сеть)

* **Симптомы:** Срабатывает алерт `KEDAMaxReplicasReached`. База данных PostgreSQL сообщает об ошибке `FATAL: remaining connection slots are reserved for non-replication superuser connections`.
* **Причины:**
  1. Лавинообразный рост воркеров исчерпал пул соединений с базой данных.
  2. Зависшие транзакции или деградация производительности SQL-запросов снижают пропускную способность консьюмеров.
* **Диагностика:**
  ```bash
  # Проверка соединений в PgBouncer / PostgreSQL
  kubectl exec -n database deploy/pgbouncer -- pgbouncer -c "SHOW POOLS;"
  ```
* **Решение:**
  1. Ограничить масштабирование исходя из физических лимитов downstream:
     $$\text{maxReplicaCount} \le \frac{\text{MaxDatabaseConnections} - \text{SystemReserved}}{\text{ConnectionsPerPod}}$$
  2. Внедрить connection pooler (PgBouncer) в режиме `pool_mode = transaction`.
  3. При наличии "ядовитых сообщений" (poison pill) настроить Dead Letter Queue (DLQ) в RabbitMQ/Kafka после 3–5 неудачных попыток обработки (NACK/DLX), чтобы воркеры не застревали в бесконечном цикле повторов.

#### Инцидент 4: APIService `v1beta1.external.metrics.k8s.io` в статусе `False`

* **Симптомы:** Алерт `KEDAExternalMetricsAPIServiceUnavailable`. `kubectl get hpa` показывает `<unknown>` в столбце `TARGETS`. В событиях HPA ошибка: `unable to fetch metrics from external metrics API: the server is currently unable to handle the request`.
* **Причины:**
  1. Истек срок действия serving TLS-сертификата пода `keda-metrics-apiserver`.
  2. Закрыт сетевой порт 6443 (или 443) между нодами Control Plane и Worker нодами, где запущен под `keda-metrics-apiserver`.
  3. Конфликт с другим внешним провайдером метрик (например, `prometheus-adapter`, если он также сконфигурирован на обработку `external.metrics.k8s.io`).
* **Диагностика:**
  ```bash
  kubectl describe apiservice v1beta1.external.metrics.k8s.io
  # → Status:
  # →   Conditions:
  # →     Last Transition Time:  2026-10-13T14:10:00Z
  # →     Message:               failing or missing response from webhooks: Get "https://10.244.2.15:6443/": x509: certificate has expired
  # →     Reason:                FailedDiscoveryCheck
  # →     Status:                False
  # →     Type:                  Available
  ```
* **Решение:**
  1. Если используется встроенный генератор сертификатов KEDA — перезапустить под оператора для перевыпуска секретов:
     ```bash
     kubectl rollout restart deployment keda-operator -n keda
     kubectl rollout restart deployment keda-metrics-apiserver -n keda
     # → deployment.apps/keda-metrics-apiserver restarted
     ```
  2. Если используется `cert-manager` — проверить статус Certificate и CertificateRequest в namespace `keda`:
     ```bash
     kubectl get certificate -n keda
     # → NAME                            READY   SECRET                       AGE
     # → keda-metrics-server-cert        True    keda-metrics-server-cert     45d
     ```
  3. Проверить отсутствие дублирующих адаптеров внешних метрик:
     ```bash
     kubectl get apiservice | grep external.metrics
     # Должна присутствовать только одна запись: v1beta1.external.metrics.k8s.io, указывающая на keda/keda-metrics-server.
     ```

#### Инцидент 5: Ошибки скейлера и переход в режим Fallback

* **Симптомы:** Срабатывает алерт `KEDAFallbackTriggered`. В статусе ScaledObject `Fallback: True`. Количество реплик фиксируется на резервном уровне.
* **Причины:**
  1. Ротация паролей/токенов в брокере сообщений без синхронизации секретов Kubernetes.
  2. Сетевая недоступность или падение инстанса брокера (Kafka Broker down, RabbitMQ OOM).
* **Диагностика:**
  ```bash
  kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=50 | grep -i "error"
  # → 2026-10-13T15:22:10Z ERROR error getting scale decision {"scaledObject.Namespace": "processing", "scaledObject.Name": "order-consumer-scaler", "error": "dial tcp 10.96.12.34:5672: connect: connection refused"}
  ```
* **Решение:**
  1. Проверить секрет, указанный в `TriggerAuthentication`:
     ```bash
     kubectl get triggerauthentication rabbitmq-trigger-auth -n processing -o yaml
     ```
  2. Проверить корректность параметров `fallback` в манифесте `ScaledObject`. Резервные реплики должны гарантировать базовую жизнеспособность сервиса без перегрузки кластера:
     ```yaml
     fallback:
       failureThreshold: 3 # Число неудачных попыток до перехода в Fallback
       replicas: 5        # Фиксированное безопасное число воркеров
     ```
  3. После восстановления доступности брокера KEDA автоматически снимет статус `Fallback: True` при первом же успешном цикле опроса метрики.

#### Инцидент 6: Исчерпание ресурсов KEDA Operator (OOMKilled) при масштабе >500 ScaledObjects

* **Симптомы:** Под `keda-operator` циклически перезапускается (`CrashLoopBackOff`, `OOMKilled`), логи содержат задержки reconciler worker pool.
* **Причины:**
  1. Рост числа управляемых объектов в кластере (сотни ScaledObjects).
  2. Каждый опрос триггера в памяти удерживает соединение и кэширует контекст. Дефолтных 256Mi памяти недостаточно.
* **Диагностика:**
  ```bash
  kubectl get pod -n keda -l app.kubernetes.io/name=keda-operator -o jsonpath='{.items[*].status.containerStatuses[*].lastState.terminated}'
  # → {"exitCode":137,"reason":"OOMKilled","startedAt":"...","finishedAt":"..."}
  ```
* **Решение:**
  1. Увеличить лимиты памяти и CPU для Deployment `keda-operator`:
     ```yaml
     resources:
       requests:
         cpu: 200m
         memory: 512Mi
       limits:
         cpu: 2000m
         memory: 2Gi
     ```
  2. Выполнить тюнинг параметров конкурентности контроллера в флагах запуска контейнера:
     ```yaml
     args:
       - "--leader-elect=true"
       - "--zap-log-level=info"
       - "--zap-encoder=json"
       - "--concurrent-reconciles=8" # Увеличение параллелизма обработки объектов
     ```

#### Инцидент 7: Утечка и накопление завершенных Job в ScaledJob

* **Симптомы:** В пространстве имён накапливаются тысячи завершенных или упавших `Job` (`Completed` / `Error`), растет нагрузка на `etcd` и `kube-apiserver`.
* **Причины:**
  В спецификации `ScaledJob` не заданы лимиты очистки истории (`successfulJobsHistoryLimit`, `failedJobsHistoryLimit`) или TTL завершенных задач.
* **Диагностика:**
  ```bash
  kubectl get jobs -n processing --no-headers | wc -l
  # → 4820
  ```
* **Решение:**
  Обязательно включить в спецификацию `ScaledJob` параметры очистки истории и TTL для планировщика Kubernetes:
  ```yaml
  apiVersion: keda.sh/v1alpha1
  kind: ScaledJob
  metadata:
    name: batch-processor
    namespace: processing
  spec:
    jobTargetRef:
      template:
        spec:
          ttlSecondsAfterFinished: 300 # Очистка пода на уровне Kubernetes через 5 минут
          restartPolicy: OnFailure
          containers:
            - name: worker
              image: registry.local/batch-worker:v1
    successfulJobsHistoryLimit: 5      # Хранить не более 5 успешных запусков
    failedJobsHistoryLimit: 10         # Хранить не более 10 упавших запусков для отладки
    maxReplicaCount: 20
    triggers:
      - type: rabbitmq
        metadata:
          queueName: batch-tasks
          queueLength: "10"
  ```

#### Инцидент 8: Admission Webhook блокирует развертывание

* **Симптомы:** Команда `kubectl apply -f scaledobject.yaml` завершается ошибкой: `Internal error occurred: failed calling webhook "vscaledobject.kb.io": failed to call webhook: Post "https://keda-admission-webhooks.keda.svc:443/validate-keda-sh-v1alpha1-scaledobject": context deadline exceeded`.
* **Причины:**
  1. Под `keda-admission-webhooks` упал или находится в состоянии `NotReady`.
  2. Сетевые задержки или отсутствие разрешающей NetworkPolicy между API-сервером и вебхуком на порту 443/9443.
* **Диагностика:**
  ```bash
  kubectl get pods -n keda -l app.kubernetes.io/name=keda-admission-webhooks
  # → NAME                                      READY   STATUS    RESTARTS   AGE
  # → keda-admission-webhooks-6c846d798-5k8q4   0/1     Running   0          5m
  ```
* **Решение:**
  1. В экстренной ситуации для восстановления возможности деплоя временно перевести политику сбоя вебхука в `Ignore`:
     ```bash
     kubectl patch validatingwebhookconfiguration keda-admission-webhooks \
       --type='json' -p='[{"op": "replace", "path": "/webhooks/0/failurePolicy", "value": "Ignore"}]'
     # → validatingwebhookconfiguration.admissionregistration.k8s.io/keda-admission-webhooks patched
     ```
  2. Устранить причину сбоя пода вебхука (проверить логи `kubectl logs -n keda deployment/keda-admission-webhooks`).
  3. Вернуть `failurePolicy: Fail` после стабилизации для предотвращения деплоя невалидных конфигураций.

#### Инцидент 9: Конфликт с PodDisruptionBudget при Scale-to-Zero

* **Симптомы:** Очередь пуста, но один под воркера остается в кластере бесконечно. В событиях HPA ошибка: `FailedScaleDown: could not delete pod, PDB violation`.
* **Причины:**
  Для воркера настроен `PodDisruptionBudget` с параметром `minAvailable: 1`. При попытке удалить последний под (`1 → 0`) eviction API или контроллер HPA блокирует операцию, так как это нарушит условие `minAvailable: 1`.
* **Диагностика:**
  ```bash
  kubectl get pdb -n processing
  # → NAME                MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
  # → order-consumer-pdb  1               N/A               0                     120d
  ```
* **Решение:**
  Для рабочих нагрузок с поддержкой `scale-to-zero` (`minReplicaCount: 0`) запрещено использовать `minAvailable: 1`. Вместо этого настраивается процентный `maxUnavailable`:
  ```yaml
  apiVersion: policy/v1
  kind: PodDisruptionBudget
  metadata:
    name: order-consumer-pdb
    namespace: processing
  spec:
    maxUnavailable: "25%" # Разрешает удаление последнего пода при нулевой нагрузке
    selector:
      matchLabels:
        app: order-consumer
  ```

---

## Рекомендации и лучшие практики (Best Practices)

### SRE SLI/SLO для масштабируемых систем

Для надежной эксплуатации систем с KEDA рекомендуется внедрить следующие индикаторы уровня обслуживания (SLI):

1. **Metric Freshness SLI (Свежесть метрик):**
   * *Метрика:* Доля времени, когда задержка опроса скейлера $P95 < 2$ секунд.
   * *SLO:* 99.5% времени за скользящий 30-дневный период.
   * *PromQL:*
     ```promql
     sum(rate(keda_scaler_metrics_latency_seconds_bucket{le="2.0"}[5m]))
     /
     sum(rate(keda_scaler_metrics_latency_seconds_count[5m])) >= 0.995
     ```

2. **Scaling Error Budget (Бюджет ошибок автоскейлинга):**
   * *Метрика:* Процент успешных запросов скейлеров к внешним источникам без ошибок connection/timeout.
   * *SLO:* $\ge 99.9\%$.
   * *PromQL:*
     ```promql
     1 - (sum(rate(keda_scaler_errors_total[5m])) / sum(rate(keda_scaler_metrics_value[5m]))) >= 0.999
     ```

3. **Cold Start Headroom:**
   * Если время холодного старта превышает допустимый таймаут очередей ($SLA_{start} > 15\text{с}$), всегда устанавливайте `minReplicaCount: 1`. Экономия ресурсов на нулевом поде не должна приводить к деградации пользовательского опыта.

### Безопасное обновление KEDA (Zero-Downtime Upgrade)

Обновление KEDA между минорными версиями (например, 2.19 $\to$ 2.20) должно проводиться по строгому регламенту:

1. **Проверка совместимости CRD и API:**
   ```bash
   kubectl api-resources --api-group=keda.sh
   # → NAME                      SHORTNAMES   APIVERSION             NAMESPACED   KIND
   # → scaledobjects             so           keda.sh/v1alpha1       true         ScaledObject
   # → scaledjobs                sj           keda.sh/v1alpha1       true         ScaledJob
   # → triggerauthentications    ta           keda.sh/v1alpha1       true         TriggerAuthentication
   ```

2. **Обновление Helm репозитория:**
   ```bash
   helm repo update kedacore
   # → Successfully got an update from the "kedacore" chart repository
   ```

3. **Проверка Diff перед применением:**
   ```bash
   helm diff upgrade keda kedacore/keda \
     --namespace keda \
     --version 2.20.0 \
     --reuse-values
   ```

4. **Выполнение обновления:**
   ```bash
   helm upgrade keda kedacore/keda \
     --namespace keda \
     --version 2.20.0 \
     --reuse-values
   # → Release "keda" has been upgraded. Happy Helming!
   ```

5. **Валидация после обновления:**
   * Убедиться, что поды перешли в `Running` без рестартов.
   * Проверить доступность APIService:
     ```bash
     kubectl get apiservice v1beta1.external.metrics.k8s.io -o jsonpath='{.status.conditions[?(@.type=="Available")].status}'
     # → True
     ```
   * Убедиться, что существующие `ScaledObject` не потеряли связку с HPA:
     ```bash
     kubectl get hpa -A | grep keda-hpa
     ```

6. **Процедура отката (Rollback):**
   При обнаружении критических сбоев выполняется откат на предыдущую стабильную ревизию:
   ```bash
   helm history keda -n keda
   helm rollback keda <PREVIOUS_REVISION> -n keda
   # → Rollback was a success! Happy Helming!
   ```

### Чек-лист готовности к production

#### До ввода в эксплуатацию (Pre-flight):
- [ ] KEDA установлена в изолированном namespace `keda` в HA-конфигурации (минимум по 2 реплики для оператора, метрик-сервера и вебхука).
- [ ] Для всех компонентов настроены `PodDisruptionBudget` и правила `podAntiAffinity`.
- [ ] Компоненты KEDA имеют класс приоритета `priorityClassName: system-cluster-critical`.
- [ ] Сетевые политики `NetworkPolicy` разрешают egress к CoreDNS, kube-apiserver и всем используемым брокерам/БД.
- [ ] Настроен экспорт метрик в Prometheus через `ServiceMonitor` или `PodMonitor`.
- [ ] Все алерты развернуты в PrometheusRule и протестированы.
- [ ] Настроен дашборд в Grafana с отслеживанием P95 задержки метрик и ошибок скейлеров.

#### После ввода в эксплуатацию (Post-deployment):
- [ ] В статусе всех `ScaledObject` условие `Ready: True`, `Fallback: False`.
- [ ] Зарегистрирован и доступен APIService `v1beta1.external.metrics.k8s.io`.
- [ ] Протестирован холодный старт (`0 → 1`) и зафиксировано время выхода в `Ready`.
- [ ] Для каждого воркера проверены лимиты downstream-зависимостей (пулы коннектов к БД).
- [ ] Настроен регламент аварийного перевода в режим паузы (`autoscaling.keda.sh/paused: "true"`).
- [ ] Команда дежурных инженеров (on-call SRE) ознакомлена с runbook по типовым инцидентам.

---

## Дополнительные материалы

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура, внутренние компоненты, жизненный цикл и глоссарий
* **[KEDA: Практические сценарии](./practical_scenarios.md)** — развертывание и примеры манифестов триггеров
* **[KEDA + Kafka: Масштабирование по Consumer Lag](./kafka-keda-scaler.md)** — эксплуатация скейлера Apache Kafka
* **[KEDA + Redis: Масштабирование по очередям и стримам](./redis-keda-scaler.md)** — эксплуатация скейлера Redis
* **[KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md)** — экономический эффект scale-to-zero и финансовые лимиты
* **[KEDA: Тестирование и валидация](./keda-testing-validation.md)** — chaos-инженерия, нагрузочное тестирование и валидация
* **[KEDA: Вопросы для собеседования](./keda-interview-questions.md)** — систематизация вопросов для SRE/DevOps
* **[Horizontal Pod Autoscaler (HPA): Практические сценарии](../HPA/hpa_scenarios.md)** — нативное масштабирование в Kubernetes
* **[Kubernetes Autoscaling: Алертинг и мониторинг](../alerting_monitoring.md)** — комплексный мониторинг автомасштабирования кластера
