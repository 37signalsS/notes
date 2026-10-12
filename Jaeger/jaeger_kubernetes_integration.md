# Интеграция Jaeger с Kubernetes

**Актуально для:** Jaeger v2.x / OpenTelemetry Operator v0.118+ / Kubernetes 1.28–1.32

> **Статус:** Документация описывает **Jaeger v2** на базе кодовой базы OpenTelemetry Collector. Jaeger v1 достиг **EOL (End of Life)**; классический `jaegertracing/jaeger-operator` переведён в статус устаревшего (deprecated) в пользу OpenTelemetry Operator. Все практические примеры и сценарии ориентированы на bare-metal и on-premise инфраструктуру без облачных вендорных зависимостей.

Развертывание Jaeger v2 в Kubernetes базируется на использовании **OpenTelemetry Operator**. Поскольку вторая версия Jaeger построена на базе OpenTelemetry Collector, она нативно управляется через стандартные ресурсы OpenTelemetry (`OpenTelemetryCollector` и `Instrumentation`). Это позволяет автоматизировать развертывание компонентов трассировки, инъекцию агентов автоинструментации в поды приложений через Mutating Admission Webhooks, динамическое масштабирование и изоляцию сетевых потоков телеметрии в кластере.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **OpenTelemetry Operator** | Kubernetes-контроллер, автоматизирующий жизненный цикл компонентов телеметрии: развертывание коллекторов, инъекцию sidecar/init-контейнеров автоинструментации и валидацию манифестов |
| **OpenTelemetryCollector (CR)** | Custom Resource, определяющий режим развертывания (`deployment`, `daemonset`, `sidecar`), ресурсы и YAML-конфигурацию пайплайнов Jaeger v2 (receivers, processors, exporters, extensions) |
| **Instrumentation (CR)** | Custom Resource для декларативной настройки автоматического инструментирования приложений (Java, Python, NodeJS, Go, .NET) без модификации исходного кода |
| **Mutating Admission Webhook** | Механизм Kubernetes API-сервера, перехватывающий запросы создания подов для автоматической инъекции переменных окружения OTel SDK, агентов или sidecar-коллекторов |
| **k8sattributes processor** | Процессор OpenTelemetry Collector, обогащающий проходящие спаны контекстом метаданных Kubernetes (имя пода, неймспейс, узел, uid, метки, аннотации) по IP-адресу источника |
| **memory_limiter processor** | Критический SRE-процессор коллектора, отслеживающий потребление RAM и принудительно сбрасывающий или отклоняющий новые данные при приближении к cgroup-лимиту во избежание OOMKilled |
| **Target Allocator** | Механизм оператора для шардирования и распределения динамических целей сбора метрик и телеметрии между инстансами коллектора без дублирования нагрузки |
| **Downward API** | Механизм Kubernetes для проброса метаданных пода (IP узла `status.hostIP`, IP пода `status.podIP`, имя пода) внутрь контейнера через переменные окружения или volume mounts |
| **PodDisruptionBudget (PDB)** | Ресурс Kubernetes, гарантирующий минимально допустимое количество активных реплик Jaeger Collector во время регламентных процедур (drain узлов, обновление кластера) |
| **ServiceMonitor** | Custom Resource Prometheus Operator для декларативного включения сбора метрик с эндпоинтов Jaeger v2 (`:8888/metrics`) в мониторинг |
| **W3C Trace Context** | Общепринятый стандарт IETF/W3C для сквозной передачи идентификаторов трассировки (`traceparent`, `tracestate`) через сетевые вызовы |
| **Headless Service** | Kubernetes Service без кластерного IP (`clusterIP: None`), возвращающий A/AAAA-записи всех подов для реализации client-side балансировки gRPC соединений |

---

## Базовые концепции

### Архитектура OpenTelemetry Operator и Jaeger v2

В архитектуре Jaeger v2 исполняемый бинарный файл представляет собой дистрибутив OpenTelemetry Collector со встроенными компонентами Jaeger (`jaeger_storage` extension, `jaeger_query` extension, OTLP receivers и storage exporters).

```
                      Kubernetes API Server
                                │
               Mutating Admission Webhook (TLS via cert-manager)
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
   Pod приложения                             OpenTelemetry Operator
┌─────────────────────────┐                ┌─────────────────────────┐
│ App Container           │                │ Controllers:            │
│ (OTel Auto-Agent)       │                │ - OpenTelemetryCollector│
│  │ OTLP gRPC (:4317)    │                │ - Instrumentation       │
└──┼──────────────────────┘                │ - Target Allocator      │
   ▼                                       └─────────────────────────┘
┌────────────────────────────────────────────────────────────────────┐
│ Jaeger v2 Collector Pod (OpenTelemetryCollector CR)               │
│                                                                    │
│  ┌───────────┐    ┌────────────────┐    ┌───────────────────────┐  │
│  │ Receivers │───▶│ Processors     │───▶│ Storage Exporters     │  │
│  │ - OTLP    │    │ - memory_limiter│   │ - jaeger_storage_     │  │
│  │   gRPC/HTTP│   │ - k8sattributes│   │   exporter            │  │
│  └───────────┘    │ - batch        │    └───────────┬───────────┘  │
│                   └────────────────┘                │              │
│  Extensions:                                        │              │
│  - healthcheckv2 (:13133)                           │              │
│  - jaeger_storage (ClickHouse Connection Pool)      │              │
│  - jaeger_query (Query API & UI :16686)             │              │
└─────────────────────────────────────────────────────┼──────────────┘
                                                      │ TCP/Native (:9000)
                                                      ▼
                                       ┌─────────────────────────────┐
                                       │ On-Premise Storage Backend  │
                                       │ ClickHouse Cluster (Bare-Metal)│
                                       └─────────────────────────────┘
```

**Компоненты OpenTelemetry Operator:**
1. **OpenTelemetryCollector Controller:** Следит за созданием и модификацией CR `OpenTelemetryCollector`. Транслирует спеку CR в нативные ресурсы Kubernetes: Deployment/DaemonSet/StatefulSet, Service, ServiceAccount, ConfigMap с конфигурацией пайплайнов и RBAC-привязки.
2. **Instrumentation Controller:** Управляет внедрением библиотек автоматического инструментирования. Перехватывает создание подов с аннотациями `instrumentation.opentelemetry.io/inject-*`, монтирует init-контейнер с SDK и настраивает переменные среды (`OTEL_EXPORTER_OTLP_ENDPOINT`, `JAVA_TOOL_OPTIONS` и др.).
3. **Webhook Server:** Обслуживает Mutating Admission Webhook для инъекции sidecar-контейнеров и агентов, а также Validating Webhook для синтаксической проверки конфигурации коллектора до ее применения.
4. **Target Allocator:** Опциональный контроллер для шардирования Prometheus ServiceMonitors и распределения нагрузки скрапинга между несколькими подами Collector без дубликатов.

### Топологии развертывания коллектора

Выбор архитектурного паттерна определяет устойчивость к отказам, потребление вычислительных ресурсов узлов и сетевую сложность.

| Паттерн | Описание | Достоинства | Недостатки | Рекомендация для SRE |
| :--- | :--- | :--- | :--- | :--- |
| **Sidecar** | Collector запускается в каждом поде приложения через аннотацию оператора | Минимальная сетевая задержка (localhost), индивидуальные фильтры для сервиса | Огромный суммарный оверхед по RAM/CPU при масштабировании приложений (сотни реплик) | Только для единичных критичных сервисов с нестандартной обработкой спанов |
| **DaemonSet (Node Agent)** | По одному экземпляру Collector на каждом рабочем узле кластера | Сбор локальных системных метрик (`hostmetrics`), оптимальное использование ресурсов узла | Требует проброса `hostPort` или `status.hostIP` через Downward API | Подходит для сбора логов/метрик узла и первичной агрегации трасс |
| **Deployment (Gateway Cluster)** | Централизованный горизонтально масштабируемый пул коллекторов за балансировщиком Service | Простота масштабирования через HPA, централизованное хвостовое сэмплирование (tail sampling), единая точка записи в ClickHouse | Дополнительный сетевой переход (network hop), необходимость балансировки gRPC | Стандарт для централизованной обработки телеметрии в микросервисах |
| **Двухуровневая архитектура (Multi-tier)** | Приложения пишут в локальный DaemonSet на узле, который обогащает спаны метаданными и отправляет их в Deployment Gateway | Оптимальный компромисс: минимальный сетевой буфер на узле, надежное k8sattributes-обогащение и централизованный batching в ClickHouse | Усложнение конфигурации двух типов коллекторов | **Рекомендуемый эталон (Best Practice) для крупных Bare-Metal кластеров** |

### Сетевое взаимодействие, балансировка gRPC и порты

Jaeger v2 использует стандартные порты OpenTelemetry и компоненты ядра:

| Порт | Протокол | Компонент | Назначение |
| :--- | :--- | :--- | :--- |
| **4317** | TCP / gRPC | OTLP Receiver | Прием трассировок, метрик и логов по стандартному бинарному протоколу OTLP gRPC |
| **4318** | TCP / HTTP | OTLP Receiver | Прием OTLP данных в формате JSON/Protobuf по HTTP |
| **14250** | TCP / gRPC | Jaeger Receiver (Legacy) | Прием спанов от устаревших агентов и библиотек Jaeger v1 |
| **14268** | TCP / HTTP | Jaeger Receiver (Legacy) | Прием спанов от клиентов Jaeger v1 через HTTP POST `/api/traces` |
| **9411** | TCP / HTTP | Zipkin Receiver | Прием спанов в формате Zipkin v1/v2 (JSON, Thrift, Protobuf) |
| **8888** | TCP / HTTP | Collector Metrics | Экспорт внутренних метрик OpenTelemetry Collector в формате Prometheus |
| **13133** | TCP / HTTP | healthcheckv2 extension | Эндпоинт проверки жизнеспособности (liveness/readiness probes) |
| **16686** | TCP / HTTP | jaeger_query extension | Веб-интерфейс Jaeger UI и REST/gRPC Query API |

**Проблема балансировки gRPC в Kubernetes:**
gRPC работает поверх постоянных HTTP/2 соединений (multiplexing). Стандартный Kubernetes Service типа `ClusterIP` (через kube-proxy iptables/IPVS) работает на уровне L4 и распределяет TCP-сессии, а не отдельные RPC-запросы. В результате длительное соединение приложения "прилипает" к одному моду Collector, вызывая неравномерную нагрузку.
**Решения для SRE:**
1. Использование **Headless Service** (`clusterIP: None`) в сочетании с round-robin балансировкой на стороне OTel SDK (`dns:///jaeger-collector-headless.observability.svc:4317`).
2. Использование Service Mesh (Istio / Envoy) или ingress-контроллеров с поддержкой gRPC L7 proxying.
3. Ограничение времени жизни соединения (`max_connection_age` / `max_connection_age_grace`) в конфигурации OTLP-ресивера коллектора для принудительного переподключения клиентов.

### Безопасность и RBAC в On-Premise кластере

Для работы процессора `k8sattributes` коллектор опрашивает API-сервер Kubernetes для сопоставления входящих IP-адресов соединений с конкретными подами кластера. 

**Принцип наименьших привилегий (Least Privilege):**
- Доступ должен ограничиваться операциями чтения (`get`, `watch`, `list`) ресурсов `pods`, `nodes`, `namespaces`.
- Права на просмотр `secrets` или `configmaps` категорически запрещены.
- Если коллектор работает в режиме DaemonSet, он может извлекать метаданные только для подов своего узла с помощью фильтра `filter.node_from_env_var: K8S_NODE_NAME`.

**Pod Security Standards (PSS):**
В современных версиях Kubernetes (1.28+) поды коллектора обязаны соответствовать профилю `Restricted`:
- Запуск от не-root пользователя (`runAsNonRoot: true`, `runAsUser: 10001`).
- Запрет повышения привилегий (`allowPrivilegeEscalation: false`).
- Доступ только на чтение к корневой файловой системе (`readOnlyRootFilesystem: true`) с монтированием `emptyDir` в `/tmp`.
- Полный сброс Linux capabilities (`drop: ["ALL"]`).
- Включение профиля seccomp по умолчанию (`seccompProfile.type: RuntimeDefault`).

### Персистентное хранилище на Bare-Metal

Для On-Premise инфраструктур использование сетевых файловых систем общего назначения (NFS) под базы данных трассировки (ClickHouse, Elasticsearch) недопустимо из-за высоких требований к IOPS и блокировкам файлов.

**Требования к StorageClass для бэкендов хранения:**
- **Локальные NVMe диски:** Использование Local Storage Operator, `local-path-provisioner` или TopoLVM (LVM-CSI) обеспечивает максимальную скорость записи при десятках тысяч спанов в секунду.
- **Распределенное блочное хранилище:** Применение Rook-Ceph RBD (`rook-ceph-block`) обеспечивает репликацию на уровне дисковой подсистемы и динамический provisoning PVC.
- **Топологическое связывание:** Обязательная директива `volumeBindingMode: WaitForFirstConsumer` в StorageClass предотвращает создание PV на узле до того, как Kubernetes Scheduler определит узел с достаточными ресурсами CPU/RAM для пода базы данных.

---

## Практические сценарии

### Сценарий 1: Развертывание оператора и Jaeger v2 через OpenTelemetryCollector CR (Production Deployment)

Развертывание отказоустойчивого кластера Jaeger v2 (в режиме Deployment) с хранилищем ClickHouse в bare-metal окружении.

#### Предварительные требования
- Кластер Kubernetes 1.28+ (on-premise / bare-metal).
- Установленный `cert-manager` (для вебхуков валидации и мутации):
  ```bash
  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.yaml
  # → customresourcedefinition.apiextensions.k8s.io/certificates.cert-manager.io created
  ```
- Установленный OpenTelemetry Operator:
  ```bash
  kubectl apply -f https://github.com/open-telemetry/opentelemetry-operator/releases/download/v0.118.0/opentelemetry-operator.yaml
  # → deployment.apps/opentelemetry-operator-controller-manager created
  ```
- Развернутый в кластере кластер ClickHouse (`clickhouse.observability.svc.cluster.local:9000`).

#### 1. Создание ServiceAccount и RBAC для обогащения метаданными

```yaml
# jaeger-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jaeger-collector
  namespace: observability
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: jaeger-collector-k8sattributes
rules:
  - apiGroups: [""]
    resources: ["pods", "nodes", "namespaces"]
    verbs: ["get", "watch", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: jaeger-collector-k8sattributes
subjects:
  - kind: ServiceAccount
    name: jaeger-collector
    namespace: observability
roleRef:
  kind: ClusterRole
  name: jaeger-collector-k8sattributes
  apiGroup: rbac.authorization.k8s.io
```

#### 2. Создание манифеста OpenTelemetryCollector CR

> [!IMPORTANT]
> В пайплайнах обработки OpenTelemetry процессор `memory_limiter` **всегда обязан стоять первым** в списке `processors`. Это предотвращает выделение памяти под парсинг и метаданные при угрозе OOMKilled.

```yaml
# jaeger-v2-collector.yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: jaeger
  namespace: observability
spec:
  mode: deployment
  replicas: 3
  image: jaegertracing/jaeger:2.3.0
  serviceAccount: jaeger-collector
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile:
      type: RuntimeDefault
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 2Gi
  env:
    - name: GOMEMLIMIT
      value: "1800MiB"
    - name: GOMAXPROCS
      value: "2"
  config: |
    extensions:
      healthcheckv2:
        use_v2: true
        http:
          endpoint: 0.0.0.0:13133
      jaeger_storage:
        backends:
          ch_store:
            type: clickhouse
            clickhouse:
              endpoint: "tcp://clickhouse.observability.svc.cluster.local:9000"
              database: "jaeger_v2"
              connection_timeout: 5s
      jaeger_query:
        storage:
          traces: ch_store
        http:
          endpoint: 0.0.0.0:16686

    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
            max_concurrent_streams: 1024
          http:
            endpoint: 0.0.0.0:4318

    processors:
      memory_limiter:
        check_interval: 250ms
        limit_percentage: 80
        spike_limit_percentage: 20
      k8sattributes:
        auth_type: serviceAccount
        passthrough: false
        extract:
          metadata:
            - k8s.pod.name
            - k8s.pod.uid
            - k8s.namespace.name
            - k8s.node.name
            - k8s.deployment.name
          labels:
            - tag_name: app.label.version
              key: version
      batch:
        send_batch_size: 8192
        timeout: 500ms
        send_batch_max_size: 16384

    exporters:
      jaeger_storage_exporter:
        trace_storage: ch_store

    service:
      extensions: [healthcheckv2, jaeger_storage, jaeger_query]
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [jaeger_storage_exporter]
      telemetry:
        metrics:
          address: 0.0.0.0:8888
```

#### Валидация
```bash
# Применение конфигурации
kubectl apply -f jaeger-rbac.yaml
# → serviceaccount/jaeger-collector created
# → clusterrole.rbac.authorization.k8s.io/jaeger-collector-k8sattributes created
# → clusterrolebinding.rbac.authorization.k8s.io/jaeger-collector-k8sattributes created

kubectl apply -f jaeger-v2-collector.yaml
# → opentelemetrycollector.opentelemetry.io/jaeger created

# Проверка создания подов
kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-collector
# → NAME                               READY   STATUS    RESTARTS   AGE
# → jaeger-collector-7d8b5c46b-2k4l9   1/1     Running   0          45s
# → jaeger-collector-7d8b5c46b-8f3x2   1/1     Running   0          45s
# → jaeger-collector-7d8b5c46b-p9q1w   1/1     Running   0          45s

# Проверка доступности Health check
kubectl exec -n observability deploy/jaeger-collector -- curl -s http://127.0.0.1:13133/
# → {"status":"Server available"}

# Проверка готовности к приему спанов через OTLP
curl -i http://127.0.0.1:16686/api/services
# → HTTP/1.1 200 OK
# → {"data":["jaeger-query"],"total":1,"limit":0,"offset":0,"errors":null}
```

---

### Сценарий 2: Двухуровневая архитектура (DaemonSet Node Agent + Deployment Gateway)

Для масштабных кластеров (50+ рабочих узлов) рекомендуется разделение сбора:
1. **DaemonSet Agent:** Запускается на каждом узле, слушает `hostPort: 4317` или локальный IP пода, обогащает спаны метаданными `k8sattributes` узла без лишней нагрузки на API-сервер и отправляет трафик дальше.
2. **Deployment Gateway:** Централизованный кластер, который собирает данные от агентов, выполняет тяжелое пакетирование и сохраняет данные в ClickHouse.

```yaml
# jaeger-agent-daemonset.yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: jaeger-node-agent
  namespace: observability
spec:
  mode: daemonset
  image: jaegertracing/jaeger:2.3.0
  serviceAccount: jaeger-collector
  hostNetwork: false
  ports:
    - name: otlp-grpc
      port: 4317
      hostPort: 4317
    - name: otlp-http
      port: 4318
      hostPort: 4318
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi
  env:
    - name: K8S_NODE_NAME
      valueFrom:
        fieldRef:
          fieldPath: spec.nodeName
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318

    processors:
      memory_limiter:
        check_interval: 200ms
        limit_percentage: 75
        spike_limit_percentage: 20
      k8sattributes:
        auth_type: serviceAccount
        passthrough: false
        filter:
          node_from_env_var: K8S_NODE_NAME
        extract:
          metadata:
            - k8s.pod.name
            - k8s.namespace.name
            - k8s.node.name
      batch:
        send_batch_size: 2048
        timeout: 200ms

    exporters:
      otlp:
        endpoint: "jaeger-collector.observability.svc.cluster.local:4317"
        tls:
          insecure: true

    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [otlp]
```

#### Валидация
```bash
kubectl apply -f jaeger-agent-daemonset.yaml
# → opentelemetrycollector.opentelemetry.io/jaeger-node-agent created

# Проверка запуска агентов на всех узлах
kubectl get daemonset -n observability jaeger-node-agent-collector
# → NAME                         DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   AGE
# → jaeger-node-agent-collector  8         8         8       8            8           30s

# Проверка порта на узле
kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-node-agent-collector -o wide
# → jaeger-node-agent-collector-5k2j   1/1   Running   0   node-worker-01
```

---

### Сценарий 3: Автоматическая инструментация приложений (Instrumentation CR)

OpenTelemetry Operator автоматически инжектирует агенты трассировки в пользовательские контейнеры при помощи аннотаций.

```yaml
# otel-instrumentation.yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: cluster-instrumentation
  namespace: default
spec:
  exporter:
    endpoint: http://jaeger-collector.observability.svc.cluster.local:4317
  propagators:
    - tracecontext
    - baggage
  sampler:
    type: parentbased_traceidratio
    argument: "0.2" # 20% сэмплирования для экономии дискового пространства
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.11.0
  python:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:0.50b0
  nodejs:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-nodejs:0.56.0
  go:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-go:v0.19.0-alpha
```

#### Манифест приложения с включенной инъекцией:

```yaml
# demo-app.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-service
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: order-service
  template:
    metadata:
      labels:
        app: order-service
      annotations:
        instrumentation.opentelemetry.io/inject-java: "default/cluster-instrumentation"
    spec:
      containers:
        - name: app
          image: eclipse-temurin:21-jre-alpine
          command: ["sh", "-c", "sleep 3600"]
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
```

#### Валидация
```bash
kubectl apply -f otel-instrumentation.yaml
# → instrumentation.opentelemetry.io/cluster-instrumentation created

kubectl apply -f demo-app.yaml
# → deployment.apps/order-service created

# Проверка добавления init-контейнера в созданный под
kubectl describe pod -n default -l app=order-service | grep -A 5 "Init Containers:"
# → Init Containers:
# →   opentelemetry-auto-instrumentation-java:
# →     Container ID:  containerd://...
# →     Image:         ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.11.0

# Проверка инжектированных переменных окружения
kubectl get pod -n default -l app=order-service -o jsonpath='{.items[0].spec.containers[0].env[?(@.name=="JAVA_TOOL_OPTIONS")].value}'
# →  -javaagent:/otel-auto-instrumentation-java/javaagent.jar
```

---

### Сценарий 4: Hardened SecurityContext и изоляция прав (Pod Security Standards)

Развертывание модулей Jaeger v2 в строгом соответствии с профилем `Restricted` PSS (Pod Security Standards) для исключения рисков эскалации привилегий.

```yaml
# jaeger-hardened-pod.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger-query-standalone
  namespace: observability
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-query
  template:
    metadata:
      labels:
        app.kubernetes.io/name: jaeger-query
    spec:
      serviceAccountName: jaeger-collector
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: query
          image: jaegertracing/jaeger:2.3.0
          args: ["--config=/etc/jaeger/config.yaml"]
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: config
              mountPath: /etc/jaeger
              readOnly: true
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: 1000m
              memory: 512Mi
      volumes:
        - name: tmp
          emptyDir: {}
        - name: config
          configMap:
            name: jaeger-config
```

#### Валидация
```bash
kubectl apply -f jaeger-hardened-pod.yaml
# → deployment.apps/jaeger-query-standalone created

# Проверка применения seccomp и security context
kubectl get pod -n observability -l app.kubernetes.io/name=jaeger-query -o jsonpath='{.items[0].spec.securityContext}'
# → {"fsGroup":10001,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001,"seccompProfile":{"type":"RuntimeDefault"}}

# Проверка невозможности записи в корень ФС
kubectl exec -n observability -c query deploy/jaeger-query-standalone -- touch /root/test 2>&1
# → touch: /root/test: Read-only file system
```

---

### Сценарий 5: Сетевая изоляция с NetworkPolicy в On-Premise кластере

Защита пространства имен `observability`: разрешение входящих OTLP-соединений от приложений и UI-трафика, строгий запрет неавторизованного исходящего сетевого доступа.

```yaml
# jaeger-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: jaeger-collector-netpol
  namespace: observability
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешаем прием OTLP gRPC и HTTP трафика от всех подов кластера
    - from:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
    # Разрешаем скрапинг метрик только Prometheus-модулям
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - protocol: TCP
          port: 8888
  egress:
    # Разрешаем подключение к ClickHouse кластеру
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: observability
          podSelector:
            matchLabels:
              app.kubernetes.io/name: clickhouse
      ports:
        - protocol: TCP
          port: 9000
    # Разрешаем обращения к Kubernetes API-серверу (для k8sattributes)
    - to:
        - ipBlock:
            cidr: 10.96.0.1/32
      ports:
        - protocol: TCP
          port: 443
    # Разрешаем DNS запросы к CoreDNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

#### Валидация
```bash
kubectl apply -f jaeger-network-policy.yaml
# → networkpolicy.networking.k8s.io/jaeger-collector-netpol created

# Проверка прохождения разрешенного gRPC трафика
kubectl run test-grpc --rm -it --image=fullstorydev/grpcurl -n default -- \
  -plaintext jaeger-collector.observability.svc.cluster.local:4317 list
# → grpc.health.v1.Health
# → opentelemetry.proto.collector.trace.v1.TraceService

# Проверка блокировки запрещенного порта (например, попытка обращения наружу)
kubectl exec -n observability deploy/jaeger-collector -- nc -z -w 2 8.8.8.8 53
# → (таймаут соединения: Connection timed out)
```

---

### Сценарий 6: Горизонтальное автомасштабирование (HPA) и PodDisruptionBudget

Настройка отказоустойчивости во время пиковых нагрузок и регламентного обслуживания физических нод.

```yaml
# jaeger-hpa-pdb.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: jaeger-collector-hpa
  namespace: observability
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: jaeger-collector
  minReplicas: 3
  maxReplicas: 12
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Percent
          value: 100
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: jaeger-collector-pdb
  namespace: observability
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector
```

#### Валидация
```bash
kubectl apply -f jaeger-hpa-pdb.yaml
# → horizontalpodautoscaler.autoscaling/jaeger-collector-hpa created
# → poddisruptionbudget.policy/jaeger-collector-pdb created

kubectl get hpa -n observability jaeger-collector-hpa
# → NAME                   REFERENCE                     TARGETS           MINPODS   MAXPODS   REPLICAS   AGE
# → jaeger-collector-hpa   Deployment/jaeger-collector   42%/70%, 55%/80%  3         12        3          1m

# Проверка PDB
kubectl get pdb -n observability jaeger-collector-pdb
# → NAME                   MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → jaeger-collector-pdb   2               N/A               1                     1m
```

---

### Сценарий 7: Сквозная трассировка через Ingress-NGINX (Bare-Metal Ingress)

Настройка генерации спанов на точке входа в кластер с автоматической передачей W3C `traceparent` в бэкенд-сервисы.

#### 1. Модификация ConfigMap ingress-nginx

```bash
kubectl -n ingress-nginx patch configmap ingress-nginx-controller --type merge -p '{
  "data": {
    "enable-opentelemetry": "true",
    "otlp-collector-host": "jaeger-collector.observability.svc.cluster.local",
    "otlp-collector-port": "4317",
    "otel-service-name": "ingress-nginx",
    "otel-propagation-policy": "w3c",
    "otel-sampler": "ratio",
    "otel-sampler-ratio": "1.0"
  }
}'
# → configmap/ingress-nginx-controller patched
```

#### 2. Перезапуск Ingress-контроллера
```bash
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
# → deployment.apps/ingress-nginx-controller restarted
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx
# → deployment "ingress-nginx-controller" successfully rolled out
```

#### Валидация
```bash
# Выполняем тестовый HTTP-запрос к приложению через Ingress
curl -i -H "Host: app.local" http://192.168.1.100/api/order
# → HTTP/1.1 200 OK

# Проверяем наличие заголовка traceparent в логах ingress-nginx
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=5 | grep "traceparent"
# → "POST /api/order HTTP/1.1" 200 128 "-" "curl/8.5.0" ... traceparent=00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

---

### Сценарий 8: Хранилище ClickHouse на On-Premise с Rook-Ceph / Local PV

Конфигурация StorageClass и PVC для хранения сотен гигабайт спанов на локальных или распределенных блочных устройствах Ceph RBD.

```yaml
# clickhouse-onprem-storage.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: baremetal-fast-ssd
provisioner: rook-ceph.rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  pool: replicapool-nvme
  imageFormat: "2"
  imageFeatures: layering
  csi.storage.k8s.io/fstype: ext4
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: clickhouse-data-pvc
  namespace: observability
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: baremetal-fast-ssd
  resources:
    requests:
      storage: 500Gi
```

#### Валидация
```bash
kubectl apply -f clickhouse-onprem-storage.yaml
# → storageclass.storage.k8s.io/baremetal-fast-ssd created
# → persistentvolumeclaim/clickhouse-data-pvc created

kubectl get sc baremetal-fast-ssd
# → NAME                 PROVISIONER                  RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION
# → baremetal-fast-ssd   rook-ceph.rbd.csi.ceph.com   Retain          WaitForFirstConsumer   true

kubectl get pvc -n observability clickhouse-data-pvc
# → NAME                  STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS         AGE
# → clickhouse-data-pvc   Pending                                      baremetal-fast-ssd   10s
# (Статус Pending до первого подключения подом ClickHouse из-за WaitForFirstConsumer)
```

---

### Сценарий 9: Мониторинг Collector через Prometheus Operator (ServiceMonitor)

Сбор телеметрии с самого коллектора Jaeger v2 для контроля стабильности пайплайнов обработки.

```yaml
# jaeger-servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: jaeger-collector-monitor
  namespace: observability
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector
  endpoints:
    - port: metrics
      path: /metrics
      interval: 15s
      scrapeTimeout: 10s
      metricRelabelings:
        - sourceLabels: [__name__]
          regex: "otelcol_.*"
          action: keep
```

#### Валидация
```bash
kubectl apply -f jaeger-servicemonitor.yaml
# → servicemonitor.monitoring.coreos.com/jaeger-collector-monitor created

# Проверка ответа метрик напрямую с пода
kubectl exec -n observability deploy/jaeger-collector -- curl -s http://127.0.0.1:8888/metrics | grep "otelcol_receiver_accepted_spans"
# → # HELP otelcol_receiver_accepted_spans Number of spans successfully pushed into the pipeline.
# → # TYPE otelcol_receiver_accepted_spans counter
# → otelcol_receiver_accepted_spans{receiver="otlp",transport="grpc"} 15420
```

---

## Операции и команды

Сводная таблица регламентных команд системного администратора и SRE для диагностики и управления Jaeger v2 в кластере:

| Операция | Команда | Ожидаемый результат / Цель (`# →`) |
| :--- | :--- | :--- |
| **Проверка статуса CR** | `kubectl get opentelemetrycollector -n observability` | `# → NAME READY STATUS AGE; jaeger 3/3 Running 2d` |
| **Проверка статуса Instrumentation** | `kubectl get instrumentation -A` | `# → NAMESPACE NAME AGE; default cluster-instrumentation 5d` |
| **Генерация тестовых спанов** | `kubectl run telemetrygen --rm -it --image=ghcr.io/open-telemetry/opentelemetry-collector-contrib/telemetrygen:latest -- traces --otlp-endpoint=jaeger-collector.observability.svc:4317 --otlp-insecure=true --duration=5s --rate=100` | `# → Generating spans... Generated 500 spans. Exiting.` |
| **Проверка gRPC Health** | `kubectl run grpcurl --rm -it --image=fullstorydev/grpcurl -n observability -- -plaintext jaeger-collector:4317 grpc.health.v1.Health/Check` | `# → {"status":"SERVING"}` |
| **Скрапинг отказанных спанов (OOM-риск)** | `kubectl exec -n observability deploy/jaeger-collector -- curl -s http://127.0.0.1:8888/metrics \| grep -E "(refused|dropped)"` | `# → otelcol_processor_memory_limiter_refused_spans 0` |
| **Анализ потребления памяти cgroups** | `kubectl top pod -n observability -l app.kubernetes.io/name=jaeger-collector` | `# → NAME CPU(cores) MEMORY(bytes); jaeger-collector-... 250m 1120Mi` |
| **Проверка кэша k8sattributes** | `kubectl exec -n observability deploy/jaeger-collector -- curl -s http://127.0.0.1:8888/metrics \| grep "k8s_namespaces"` | `# → otelcol_processor_k8sattributes_active_pods 148` |
| **Перезапуск пула коллекторов** | `kubectl rollout restart deployment/jaeger-collector -n observability` | `# → deployment.apps/jaeger-collector restarted` |

---

## Типичные проблемы и устранение неполадок

| Проблема | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Поды приложения падают при запуске (CrashLoopBackOff)** | Mutating Webhook оператора недоступен или истек TLS-сертификат вебхука | `kubectl get events -n default \| grep FailedCreate`<br>`# → Internal error occurred: failed calling webhook` | Проверить статус cert-manager (`kubectl get pods -n cert-manager`). Убедиться, что поды `opentelemetry-operator-controller-manager` в статусе Running |
| **Спаны не поступают в Collector** | Неверный endpoint, протокол или блокировка NetworkPolicy | `kubectl exec -it <app-pod> -- nc -zvw3 jaeger-collector 4317`<br>`# → Connection timed out` | Открыть порт 4317 в Ingress правилах NetworkPolicy. Проверить значение `OTEL_EXPORTER_OTLP_ENDPOINT` (для gRPC префикс `http://` в некоторых SDK опускается) |
| **Падение Collector с OOMKilled (Exit Code 137)** | Отсутствует `memory_limiter` или `limit_percentage` превышает cgroup лимит контейнера | `kubectl describe pod -n observability <collector-pod> \| grep -i oom`<br>`# → Last State: Terminated, Reason: OOMKilled` | Поместить `memory_limiter` **первым** в цепочке процессоров. Установить `limit_percentage: 80` и передать переменную `GOMEMLIMIT: "1800MiB"` |
| **В спанах отсутствуют k8s.* атрибуты** | ServiceAccount коллектора не имеет прав на чтение API или трафик идет через SNAT прокси | Метрика `otelcol_processor_k8sattributes_errors_total` растет в `/metrics` | Проверить права: `kubectl auth can-i list pods --as=system:serviceaccount:observability:jaeger-collector`. Проверить, что IP клиента не подменяется kube-proxy |
| **UI не показывает трейсы после записи** | Отсутствует соединение между `jaeger_storage_exporter` и ClickHouse | В логах коллектора: `dial tcp: lookup clickhouse: no such host` или `connection refused` | Проверить FQDN адрес ClickHouse (`clickhouse.observability.svc.cluster.local:9000`), сетевой доступ и создание таблиц БД `jaeger_v2` |
| **Init-контейнер не внедряется в под** | Несовпадение namespace в аннотации или опечатка в имени CR Instrumentation | `kubectl describe pod <app-pod> \| grep -i annotations` | Указать полный путь к ресурсу в аннотации: `instrumentation.opentelemetry.io/inject-java: "default/cluster-instrumentation"` |
| **Рассинхронизация времени в трейсах (Clock Skew)** | Рассинхронизация часов между физическими узлами bare-metal кластера | В Jaeger UI спаны имеют отрицательную длительность или начинаются раньше родительских | Настроить службу синхронизации времени `chrony` на всех хостах кластера: `chronyc tracking` |
| **Неравномерное распределение нагрузки по репликам** | Long-lived gRPC соединения мультиплексируются в одну TCP сессию | В `kubectl top pods` одна реплика утилизирует 100% CPU, остальные простаивают | Настроить `Headless Service` для client-side балансировки или добавить директивы `max_connection_age: 120s` в блок `receivers.otlp.protocols.grpc` |

---

## Лучшие практики

1. **Единый стандарт через OpenTelemetry Operator:** Не используйте устаревший Jaeger Operator v1 для новых кластеров. OpenTelemetry Operator — единый стандарт CNCF для управления жизненным циклом компонентов трассировки.
2. **Строгий порядок процессоров:** В пайплайне Collector всегда ставьте `memory_limiter` первым процессором, а `batch` — последним. Это гарантирует, что избыточный трафик будет отклонен до расходования ресурсов памяти на обогащение атрибутами.
3. **Согласование GOMEMLIMIT и cgroup:** Задавайте переменную окружения `GOMEMLIMIT` на уровне 85-90% от лимита памяти контейнера (например, `GOMEMLIMIT=1800MiB` при `limits.memory: 2Gi`). Это заставляет рантайм Go запускать Garbage Collection до срабатывания механизма OOMKilled ядра Linux.
4. **Безопасность по умолчанию:** Развертывайте поды Jaeger в соответствии с политикой `Pod Security Standards: Restricted` (`runAsNonRoot: true`, `readOnlyRootFilesystem: true`, сброс всех capabilities).
5. **Headless Service для gRPC:** Создавайте парный Headless Service (`clusterIP: None`) для порта 4317, чтобы SDK приложений с поддержкой DNS round-robin могли балансировать gRPC вызовы по всем доступным репликам.
6. **Высокая доступность и PDB:** В production-среде развертывайте минимум 3 реплики коллектора, распределенные по разным узлам через `topologySpreadConstraints` (или `podAntiAffinity`), защищенные `PodDisruptionBudget` (`minAvailable: 2`).
7. **Локальные NVMe для ClickHouse:** Избегайте использования сетевых файловых систем общего назначения (NFS) для баз данных трейсов. Используйте локальные быстрые диски (TopoLVM, Local PV) или проверенный отказоустойчивый пул Ceph RBD (`rook-ceph-block`).
8. **Разумные политики сэмплирования:** Внедряйте адаптивное или вероятностное сэмплирование (`sampler.argument: "0.1"`) на уровне `Instrumentation` CR, чтобы исключить деградацию производительности приложений и переполнение хранилища при десятках тысяч запросов в секунду.
9. **Контроль метрик самого коллектора:** Настройте алерты на рост показателей `otelcol_processor_memory_limiter_refused_spans` (перегрузка по памяти) и `otelcol_exporter_enqueue_failed_spans` (сбои записи в базу данных).

---

## Очистка окружения

Команды последовательного удаления компонентов и освобождения ресурсов кластера:

```bash
# 1. Удаление тестовых приложений и Instrumentation CR
kubectl delete deployment order-service -n default --ignore-not-found=true
# → deployment.apps "order-service" deleted
kubectl delete instrumentation cluster-instrumentation -n default --ignore-not-found=true
# → instrumentation.opentelemetry.io "cluster-instrumentation" deleted

# 2. Удаление коллекторов Jaeger v2 (Deployment и DaemonSet)
kubectl delete opentelemetrycollector jaeger -n observability --ignore-not-found=true
# → opentelemetrycollector.opentelemetry.io "jaeger" deleted
kubectl delete opentelemetrycollector jaeger-node-agent -n observability --ignore-not-found=true
# → opentelemetrycollector.opentelemetry.io "jaeger-node-agent" deleted

# 3. Удаление HPA и PodDisruptionBudget
kubectl delete hpa jaeger-collector-hpa -n observability --ignore-not-found=true
# → horizontalpodautoscaler.autoscaling "jaeger-collector-hpa" deleted
kubectl delete pdb jaeger-collector-pdb -n observability --ignore-not-found=true
# → poddisruptionbudget.policy "jaeger-collector-pdb" deleted

# 4. Удаление сетевых политик и мониторинга
kubectl delete networkpolicy jaeger-collector-netpol -n observability --ignore-not-found=true
# → networkpolicy.networking.k8s.io "jaeger-collector-netpol" deleted
kubectl delete servicemonitor jaeger-collector-monitor -n observability --ignore-not-found=true
# → servicemonitor.monitoring.coreos.com "jaeger-collector-monitor" deleted

# 5. Удаление RBAC
kubectl delete clusterrolebinding jaeger-collector-k8sattributes --ignore-not-found=true
# → clusterrolebinding.rbac.authorization.k8s.io "jaeger-collector-k8sattributes" deleted
kubectl delete clusterrole jaeger-collector-k8sattributes --ignore-not-found=true
# → clusterrole.rbac.authorization.k8s.io "jaeger-collector-k8sattributes" deleted
kubectl delete serviceaccount jaeger-collector -n observability --ignore-not-found=true
# → serviceaccount "jaeger-collector" deleted

# 6. Проверка отсутствия зависших подов
kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-collector
# → No resources found in observability namespace.
```

---

## Дополнительная информация

**Смежные материалы базы знаний:**

* Компоненты ядра и внутренние механизмы: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Базовые сценарии локального и production запуска: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Высокая доступность и резервирование: **[High Availability и DR](./jaeger_high_availability.md)**
* Детальная настройка бэкендов хранения (ClickHouse, Elasticsearch): **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
* Интеграция с Istio и Linkerd: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**
* Настройка безопасности, TLS и mTLS: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**
* Трассировка без модификации кода на уровне ядра Linux: **[eBPF и автоматическая инструментация](./jaeger_ebpf_auto_instrumentation.md)**
* Визуализация и корреляция трейсов: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**
* Спецификация и формат передачи телеметрии: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**
* Переход с архитектуры Jaeger v1: **[Миграция Jaeger v1 → v2](./jaeger_migration_v1_to_v2.md)**
* Расчет вычислительных ресурсов: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**

### См. также

* [Официальная документация Jaeger v2](https://www.jaegertracing.io/docs/latest/)
* [Руководство по OpenTelemetry Operator для Kubernetes](https://opentelemetry.io/docs/kubernetes/operator/)
* [Спецификация процессора k8sattributes](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/k8sattributesprocessor)
