# eBPF и автоматическая инструментация Jaeger

**Актуально для:** Jaeger v2.x, OpenTelemetry eBPF (Grafana Beyla 1.x / OTel Go Auto-Instrumentation / OTel Operator / Linux Kernel 5.8+)

> **Важно:** Документация описывает интеграцию с **Jaeger v2** (текущая стабильная версия на базе архитектуры OpenTelemetry Collector). Версия Jaeger v1 признана устаревшей (EOL).

**eBPF и автоматическая инструментация Jaeger** — это технологии безинвазивного внедрения распределенной трассировки в приложения без модификации исходного кода, перекомпиляции или изменения бинарных файлов. В современной Linux-инфраструктуре (bare-metal, виртуальные машины и on-premise кластеры Kubernetes) инструментация через eBPF переносит перехват вызовов в пространство ядра Linux. Специализированные агенты (Grafana Beyla, OpenTelemetry Go Auto-Instrumentation, Odigos) перехватывают системные вызовы сокетов и функции L7-протоколов (HTTP, HTTPS/TLS, gRPC, базы данных SQL), генерируют спаны и транслируют их напрямую в Jaeger v2 Collector по стандартному протоколу OTLP (OpenTelemetry Protocol).

Это решение критически важно для SRE, DevOps и системных администраторов при мониторинге legacy-монолитов, закрытых third-party сервисов, утилит на компилируемых языках (Go, Rust, C++) и компонентов, для которых ручная модификация кода невозможна или экономически нецелесообразна.

Смежные темы:
- Общий обзор концепций и терминологии: **[Обзор Jaeger](./jaeger_overview.md)**
- Компоненты коллектора и пайплайны Jaeger v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
- Настройка приема протокола OTLP: **[Конфигурация OTLP для Jaeger](./jaeger_otlp_configuration.md)**
- Базовое развертывание в Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
- Традиционная инструментация через SDK: **[OpenTelemetry: Инструментация и SDK](../OpenTelemetry/instrumentation_sdk.md)**

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **eBPF (Extended Berkeley Packet Filter)** | Подсистема ядра Linux, позволяющая безопасно исполнять байт-код в пространстве ядра при наступлении определенных событий без изменения исходного кода ядра и без загрузки модулей ядра (LKM). |
| **Auto-instrumentation (Автоинструментация)** | Процесс автоматического сбора телеметрии (трейсов и метрик) рантаймом или внешним перехватчиком без ручного добавления вызовов OpenTelemetry API в код приложения. |
| **Grafana Beyla** | Open-source инструмент автоматической инструментации на базе eBPF, отслеживающий сетевые протоколы L7 (HTTP/1.1, HTTP/2, gRPC, SQL) и передающий трейсы в формате OTLP в коллекторы (включая Jaeger v2). |
| **OpenTelemetry Go Auto-Instrumentation** | Официальный проект OpenTelemetry, использующий eBPF uprobes для автоматического перехвата HTTP и gRPC вызовов в Go-бинарниках без перекомпиляции. |
| **Odigos** | Open-source платформа оркестрации автоматической инструментации в Kubernetes, комбинирующая eBPF и рантайм-агенты с экспортом по OTLP. |
| **Kprobes / Kretprobes** | Механизмы динамической трассировки ядра Linux для перехвата входа в функцию ядра и возврата из нее (например, системных вызовов сокетов `sys_enter_write`, `tcp_sendmsg`). |
| **Uprobes / Uretprobes** | Механизмы динамической трассировки пользовательского пространства (user-space) для перехвата вызовов функций в исполняемых файлах и разделяемых библиотеках (например, функций OpenSSL `SSL_read`/`SSL_write` или Go-пакетов `net/http`). |
| **Tracepoints** | Статически определенные в ядре Linux точки трассировки, обладающие меньшим оверхедом и более высокой стабильностью API по сравнению с kprobes. |
| **USDT (User Statically-Defined Tracing)** | Статически скомпилированные точки трассировки в приложениях пользовательского пространства. |
| **CO-RE (Compile Once — Run Everywhere)** | Технология eBPF на базе BPF Type Format (BTF), позволяющая скомпилированной eBPF-программе работать на разных версиях ядра Linux без перекомпиляции на целевом хосте. |
| **W3C Trace Context** | Стандарт распределенного контекста (`traceparent`, `tracestate`), передаваемый в заголовках сетевых пакетов для связывания клиентских и серверных спанов в единый граф трассировки. |
| **Sidecar-less** | Архитектура развертывания, при которой мониторинг приложений выполняется одним демоном на уровне узла (Host Daemon) без внедрения sidecar-контейнера в каждый Pod. |
| **RLIMIT_MEMLOCK** | Системное ограничение Linux на объем памяти, которую процесс может заблокировать в ОЗУ (требуется для загрузки карт и программ eBPF в ядро). |

---

## Архитектура и принципы работы eBPF-инструментации

### Механизм перехвата трафика и генерации спанов

В традиционной модели OpenTelemetry SDK приложение самостоятельно создает спаны, сериализует их и отправляет в Jaeger по сети. При eBPF-инструментации приложение работает без изменений, а перехват происходит на двух уровнях:

1. **User-Space (Uprobes):**
   - Перехват вызовов динамических библиотек TLS (`libssl.so`, `libcrypto.so`) до шифрования исходящих данных и после дешифрования входящих данных.
   - Перехват внутренних рантайм-функций компилируемых языков (например, HTTP-роутеров и gRPC-клиентов в Go).
   - Чтение URL, HTTP-методов, заголовков `traceparent` и статус-кодов ответов в открытом виде.
2. **Kernel-Space (Kprobes / Tracepoints / Socket Filters):**
   - Перехват системных вызовов сокетов (`sys_enter_connect`, `sys_enter_accept`, `tcp_sendmsg`, `tcp_recvmsg`).
   - Измерение точных временных меток задержки TCP-соединений, очередей сокетов и сетевой задержки.
   - Ассоциация сетевых сокетов с дескрипторами процессов (PID, TGID, cgroup).

Собранные данные через кольцевые буферы (BPF Ring Buffers) передаются агенту в пространстве пользователя (например, Grafana Beyla), который реконструирует транзакции, сопоставляет запросы и ответы, формирует OTLP Spans и отправляет их в Jaeger v2 Collector.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            User Space (Хост / Pod)                          │
│                                                                             │
│   ┌─────────────────────┐                   ┌───────────────────────────┐   │
│   │   Приложение А      │                   │       Приложение Б        │   │
│   │   (Go / Rust / C++) │                   │     (Python / Nginx)      │   │
│   └──────────┬──────────┘                   └─────────────┬─────────────┘   │
│              │ (uprobes на HTTP/TLS/gRPC)                 │ (libssl uprobes)│
│              ▼                                            ▼                 │
├──────────────┼────────────────────────────────────────────┼─────────────────┤
│              │            Kernel Space (eBPF)             │                 │
│              │                                            │                 │
│   ┌──────────▼────────────────────────────────────────────▼─────────────┐   │
│   │                     eBPF Probes / Programs                          │   │
│   │     - kprobes/tracepoints: sys_enter_read, tcp_sendmsg              │   │
│   │     - uprobes: SSL_read, SSL_write, runtime symbol hooks            │   │
│   └──────────────────────────────┬──────────────────────────────────────┘   │
│                                  │ (BPF Ring Buffer / BPF Perf Event)       │
├──────────────────────────────────┼──────────────────────────────────────────┤
│                                  ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │           eBPF Agent: Grafana Beyla / OTel Go Agent                 │   │
│   │  - Корреляция Request / Response по PID и сокету                    │   │
│   │  - Извлечение W3C traceparent заголовков                            │   │
│   │  - Обогащение k8s / host метаданными                                │   │
│   │  - Сериализация спанов в OTLP Spans                                 │   │
│   └──────────────────────────────┬──────────────────────────────────────┘   │
│                                  │ OTLP / gRPC (порт 4317)                  │
│                                  ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                   Jaeger v2 Collector (On-Premise)                  │   │
│   │    receiver: otlp -> processors -> jaeger_storage (ClickHouse/ES)   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Сравнение методов инструментации для Jaeger

| Критерий | eBPF Agent (Beyla / OTel-Go) | Runtime Agent (Javaagent/Python) | Service Mesh (Envoy/Istio) | Manual OTel SDK |
| :--- | :--- | :--- | :--- | :--- |
| **Модификация кода** | Не требуется (Zero-code) | Не требуется (конфиг запуска) | Не требуется (sidecar/ambient) | Требуется правка исходников |
| **Поддерживаемые языки** | Все (Go, C++, Rust, Node, Python, Java) | Зависит от языка (Java, Python, JS, .NET) | Все (на уровне L7 прокси) | Любые языки с OTel SDK |
| **Оверхед на CPU/RAM** | Минимальный (1–3% CPU, ядро Linux) | Средний (дополнительная память JVM/рантайма) | Средний/Высокий (sidecar tax, проксирование) | Минимальный (0.5–1% CPU) |
| **Поддержка HTTPS/TLS** | Да (через uprobes к libssl и Go TLS) | Да (рантайм видит открытый текст) | Да (mTLS на уровне прокси) | Да (до уровня шифрования) |
| **Контекст бизнес-логики** | Ограничен (только L7 URL, методы, статусы) | Частично (параметры методов фреймворков) | Нет (только сетевые L7-атрибуты) | Полный (произвольные атрибуты, user_id) |
| **Пропагация W3C Trace Context** | Поддерживается для HTTP/gRPC (L7) | Полная (внутрипоточная и межсервисная) | Требует проброса заголовков кодом | Полная ручная/библиотечная |
| **Требования к правам** | `CAP_BPF`, `CAP_PERFMON` или `privileged` | Права обычного пользователя процесса | Права управления сетевым стеком | Права обычного пользователя |

### Распространение контекста (Trace Context Propagation) через eBPF

Один из главных архитектурных вызовов eBPF — обеспечение непрерывности трейса (Distributed Context Propagation):
1. **Входящий запрос:** eBPF-программа перехватывает сетевой буфер или вызов чтения из сокета, парсит заголовок `traceparent` стандарта W3C и регистрирует входящий `parent_span_id`.
2. **Локальный спан:** Агент замеряет длительность обработки запроса сервером от момента приема первого байта до отправки ответа.
3. **Исходящий запрос:** Если сервис делает вызов к зависимому сервису, eBPF-программа может либо инжектировать новый сгенерированный `traceparent` в исходящий сетевой буфер (в поддерживаемых протоколах), либо связать спаны на основе эвристики временных окон и PID процесса.
4. **Ограничение eBPF:** Если приложение использует асинхронные очереди (Kafka, RabbitMQ) или сложные внутренние пулы потоков, eBPF на уровне сокетов не может однозначно связать входящее сообщение из очереди с исходящим HTTP-запросом без помощи рантайм-контекста приложения.

### Требования к ядру Linux

Для корректной работы eBPF-инструментации требуются следующие параметры хоста:
- **Версия ядра:** Linux **5.8+** (рекомендуется **5.15+** LTS или **6.x**). Ядра ниже 5.8 требуют полных привилегий `CAP_SYS_ADMIN` и не поддерживают изолированные `CAP_BPF` и `CAP_PERFMON`.
- **Поддержка BPF Type Format (BTF):** Наличие файла `/sys/kernel/btf/vmlinux` (включена опция ядра `CONFIG_DEBUG_INFO_BTF=y`).
- **Файловая система tracefs/debugfs:** Смонтированные `/sys/kernel/tracing` или `/sys/kernel/debug`.
- **Настройка perf_event:** `kernel.perf_event_paranoid <= 2` (для Debian/Ubuntu по умолчанию может быть `3` or `4`, что блокирует создание perf-событий без root).

---

## Практические сценарии развертывания и настройки

### Сценарий 1: Развертывание Grafana Beyla как DaemonSet в Kubernetes

**Задача:** Автоматически получать трейсы со всех микросервисов в кластере Kubernetes без sidecar-контейнеров и отправлять их в централизованный коллектор Jaeger v2 по протоколу OTLP gRPC.

#### 1. Создание RBAC для декорирования метаданными Kubernetes

Для того чтобы Beyla обогащала спаны атрибутами `k8s.namespace.name`, `k8s.pod.name`, `k8s.deployment.name` и `k8s.node.name`, агенту требуется доступ к Kubernetes API:

```yaml
# beyla-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: beyla
  namespace: observability
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: beyla
rules:
  - apiGroups: ["apps"]
    resources: ["replicasets", "deployments", "statefulsets", "daemonsets"]
    verbs: ["list", "watch", "get"]
  - apiGroups: [""]
    resources: ["pods", "services", "nodes"]
    verbs: ["list", "watch", "get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: beyla
subjects:
  - kind: ServiceAccount
    name: beyla
    namespace: observability
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: beyla
```

#### 2. Манифест DaemonSet с минимально необходимыми Linux Capabilities

Запуск eBPF-агента без полного флага `privileged: true` с соблюдением требований безопасности (least privilege):

```yaml
# beyla-daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: beyla
  namespace: observability
  labels:
    app.kubernetes.io/name: beyla
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: beyla
  template:
    metadata:
      labels:
        app.kubernetes.io/name: beyla
    spec:
      serviceAccountName: beyla
      hostPID: true
      hostNetwork: false
      tolerations:
        - operator: Exists
          effect: NoSchedule
        - operator: Exists
          effect: NoExecute
      containers:
        - name: beyla
          image: grafana/beyla:1.8.4
          imagePullPolicy: IfNotPresent
          env:
            # Адрес OTLP gRPC ресивера Jaeger v2 Collector
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://jaeger-collector.observability.svc.cluster.local:4317"
            # Включение автоматического связывания метаданных K8s
            - name: BEYLA_KUBE_METADATA_ENABLE
              value: "autodetect"
            # Фильтрация портов для мониторинга (порты сервисов)
            - name: BEYLA_OPEN_PORT
              value: "80,443,8080,8081,8443,9090,50051"
            # Уровень логирования
            - name: BEYLA_LOG_LEVEL
              value: "INFO"
            # Ограничение очередей BPF
            - name: BEYLA_BPF_BATCH_TIMEOUT
              value: "50ms"
          securityContext:
            runAsUser: 0
            readOnlyRootFilesystem: true
            capabilities:
              add:
                - BPF                 # Загрузка BPF-программ и карт
                - PERFMON             # Чтение перформанс-счетчиков и трассировок
                - SYS_PTRACE          # Доступ к пространствам имен процессов (/proc/*/ns)
                - NET_RAW             # Сокетные фильтры для пакетов
                - CHECKPOINT_RESTORE  # Чтение символов исполняемых файлов
                - DAC_READ_SEARCH     # Доступ к бинарным файлам хоста
              drop:
                - ALL
          volumeMounts:
            - name: cgroup
              mountPath: /sys/fs/cgroup
              readOnly: true
            - name: tracefs
              mountPath: /sys/kernel/tracing
              readOnly: true
            - name: var-run-beyla
              mountPath: /var/run/beyla
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
      volumes:
        - name: cgroup
          hostPath:
            path: /sys/fs/cgroup
        - name: tracefs
          hostPath:
            path: /sys/kernel/tracing
        - name: var-run-beyla
          emptyDir: {}
```

#### 3. Валидация работы

Применение и проверка состояния:

```bash
# Применение манифестов
kubectl apply -f beyla-rbac.yaml
# → serviceaccount/beyla created
# → clusterrole.rbac.authorization.k8s.io/beyla created
# → clusterrolebinding.rbac.authorization.k8s.io/beyla created

kubectl apply -f beyla-daemonset.yaml
# → daemonset.apps/beyla created

# Проверка статуса запуска подов
kubectl get pods -n observability -l app.kubernetes.io/name=beyla -o wide
# → beyla-7x9q2   1/1   Running   0   18s   10.244.1.15   node-01   <none>   <none>
# → beyla-m4k8p   1/1   Running   0   18s   10.244.2.22   node-02   <none>   <none>

# Проверка логов агента на предмет перехвата процессов
kubectl logs -n observability -l app.kubernetes.io/name=beyla --tail=20
# → time="2026-10-12T10:15:00Z" level=info msg="Starting Beyla" version=1.8.4
# → time="2026-10-12T10:15:01Z" level=info msg="Finding instrumentable processes for ports: 80,443,8080,8081,8443,9090,50051"
# → time="2026-10-12T10:15:02Z" level=info msg="Instrumenting process" cmd=/app/order-service pid=24912
```

---

### Сценарий 2: Развертывание Beyla на физическом сервере / Linux VM (systemd)

**Задача:** Системному администратору необходимо обеспечить трассировку нативных сервисов Linux (Nginx, бэкенды на Go/Rust, обращения к локальному PostgreSQL) без использования контейнеров и отправлять спаны в on-premise инсталляцию Jaeger v2.

#### 1. Подготовка хоста и установка бинарного файла

```bash
# 1. Проверка поддержки BTF ядром Linux
test -f /sys/kernel/btf/vmlinux && echo "BTF OK" || echo "BTF MISSING"
# → BTF OK

# 2. Настройка параметра perf_event_paranoid в sysctl
echo "kernel.perf_event_paranoid = 2" | sudo tee /etc/sysctl.d/99-ebpf.conf
sudo sysctl --system | grep perf_event_paranoid
# → kernel.perf_event_paranoid = 2

# 3. Загрузка бинарного файла Beyla
sudo curl -fsSL -o /usr/local/bin/beyla https://github.com/grafana/beyla/releases/download/v1.8.4/beyla-linux-amd64
sudo chmod +x /usr/local/bin/beyla
/usr/local/bin/beyla --version
# → beyla version 1.8.4
```

#### 2. Создание файла конфигурации `/etc/beyla/beyla.yml`

```yaml
# /etc/beyla/beyla.yml
print_traces: false
log_level: "INFO"

# Выбор процессов для инструментации по имени исполняемого файла или открытому порту
discovery:
  services:
    - name: "nginx-ingress"
      exe_path: ".*/nginx$"
      open_ports: "80,443"
    - name: "auth-backend"
      exe_path: ".*/auth-service$"
      open_ports: "8080"
    - name: "billing-api"
      exe_path: ".*/billing-worker$"

# Настройка экспорта OTLP в Jaeger v2
otel_traces_export:
  endpoint: "http://jaeger.internal.corp:4317"
  sampler:
    name: "parentbased_always_on"
  batch_timeout: 100ms
  max_queue_size: 4096

# Фильтрация L7 маршрутов (схлопывание параметров URL в шаблоны)
routes:
  unmatched: "heuristic"
  patterns:
    - "/api/v1/users/{id}"
    - "/api/v1/orders/{order_id}/status"
```

#### 3. Настройка и запуск systemd-юнита

```ini
# /etc/systemd/system/beyla.service
[Unit]
Description=Grafana Beyla eBPF Auto-Instrumentation Agent for Jaeger
Documentation=https://grafana.com/docs/beyla/latest/
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/beyla --config=/etc/beyla/beyla.yml
Restart=always
RestartSec=5s

# Настройки безопасности и лимитов для eBPF
User=root
Group=root
LimitMEMLOCK=infinity
LimitNOFILE=65536

# Изоляция файловой системы (за исключением необходимых путей ядра)
ProtectSystem=full
ProtectHome=true
ReadOnlyPaths=/sys/fs/cgroup
ReadWritePaths=/sys/kernel/tracing /run

[Install]
WantedBy=multi-user.target
```

Запуск и проверка сервиса:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now beyla.service
# → Created symlink /etc/systemd/system/multi-user.target.wants/beyla.service → /etc/systemd/system/beyla.service.

sudo systemctl status beyla.service --no-pager
# → ● beyla.service - Grafana Beyla eBPF Auto-Instrumentation Agent for Jaeger
# →      Loaded: loaded (/etc/systemd/system/beyla.service; enabled; vendor preset: enabled)
# →      Active: active (running) since Mon 2026-10-12 10:20:15 UTC; 5s ago
# →    Main PID: 31204 (beyla)
# →       Tasks: 8 (limit: 18881)
# →      Memory: 42.1M
# →         CPU: 120ms
```

---

### Сценарий 3: OpenTelemetry Operator с eBPF для Go-приложений

**Задача:** В кластере под управлением OpenTelemetry Operator автоматически инструментировать Go-приложения с помощью eBPF (`opentelemetry-go-instrumentation`) без ручной сборки с CGO или правки кода.

#### 1. Создание ресурса `Instrumentation` CRD

```yaml
# otel-go-instrumentation.yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: otel-ebpf-go-instrumentation
  namespace: default
spec:
  exporter:
    endpoint: "http://jaeger-collector.observability.svc.cluster.local:4317"
  propagators:
    - tracecontext
    - baggage
  sampler:
    type: parentbased_always_on
  go:
    image: ghcr.io/open-telemetry/opentelemetry-go-instrumentation/autoinstrumentation-go:v0.14.0
    env:
      - name: OTEL_GO_AUTO_TARGET_EXE
        value: "/app/server"
```

#### 2. Подключение к Deployment через аннотацию

OpenTelemetry Operator автоматически инжектирует sidecar или агент со специальными привилегиями для крепления eBPF uprobes к целевому исполняемому файлу:

```yaml
# go-service-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: go-order-api
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: go-order-api
  template:
    metadata:
      labels:
        app: go-order-api
      annotations:
        instrumentation.opentelemetry.io/inject-go: "true"
        instrumentation.opentelemetry.io/container-names: "server"
    spec:
      # Необходимо для инспекции процессов контейнера eBPF-инжектором
      shareProcessNamespace: true
      containers:
        - name: server
          image: internal-registry.corp/apps/go-order-api:v2.4.0
          ports:
            - containerPort: 8080
              name: http
          resources:
            limits:
              cpu: "1"
              memory: 512Mi
            requests:
              cpu: "100m"
              memory: 128Mi
```

#### 3. Валидация

```bash
kubectl apply -f otel-go-instrumentation.yaml
# → instrumentation.opentelemetry.io/otel-ebpf-go-instrumentation created

kubectl apply -f go-service-deployment.yaml
# → deployment.apps/go-order-api created

# Проверка инъекции sidecar-контейнера eBPF
kubectl get pods -l app: go-order-api -o jsonpath='{.items[0].spec.containers[*].name}'
# → server opentelemetry-auto-instrumentation-go
```

---

## Эксплуатация и команды диагностики

### Инспекция ядра и BPF-подсистемы

Команды системного администратора для валидации поддержки eBPF на хосте:

```bash
# 1. Проверка наличия BTF (BPF Type Format)
ls -la /sys/kernel/btf/vmlinux
# → -r--r--r-- 1 root root 4829104 Oct 12 09:00 /sys/kernel/btf/vmlinux

# 2. Проверка смонтированных файловых систем BPF и трассировки
mount -t bpf
# → none on /sys/fs/bpf type bpf (rw,nosuid,nodev,noexec,relatime,mode=700)

mount -t tracefs
# → tracefs on /sys/kernel/tracing type tracefs (rw,nosuid,nodev,noexec,relatime)

# 3. Проверка лимитов заблокированной памяти (Locked Memory)
ulimit -l
# → unlimited
```

### Мониторинг загруженных BPF-программ и карт (`bpftool`)

Утилита `bpftool` позволяет инспектировать программы, загруженные агентом Beyla или OTel в ядро:

```bash
# Просмотр списка загруженных BPF-программ фильтрации
sudo bpftool prog show --pinned /sys/fs/bpf
# → 412: kprobe  name kprobe__sys_enter_write  tag a24b89df51cb2a01  gpl
# → 	loaded_at 2026-10-12T10:15:02+0000  uid 0
# → 	xlated 1488B  jited 896B  memlock 4096B  map_ids 128,129
# → 413: uprobe  name uprobe__SSL_write  tag f721a91e0a81d441  gpl
# → 	loaded_at 2026-10-12T10:15:02+0000  uid 0
# → 	xlated 2120B  jited 1240B  memlock 4096B  map_ids 128,130

# Проверка BPF Maps (хранилищ состояния сокетов и буферов)
sudo bpftool map list
# → 128: ringbuf  name events  flags 0x0
# → 	key 0B  value 0B  max_entries 4194304  memlock 4198400B
# → 129: hash  name active_spans  flags 0x0
# → 	key 16B  value 128B  max_entries 10240  memlock 1048576B

# Проверка активности uprobes в tracefs
sudo cat /sys/kernel/tracing/uprobe_events
# → p:uprobes/p__usr_lib_x86_64_linux_gnu_libssl_so_3_0x39a40 /usr/lib/x86_64-linux-gnu/libssl.so.3:0x0000000000039a40
```

### Проверка сетевой связности с Jaeger v2 OTLP Receiver

```bash
# Проверка доступности OTLP gRPC порта Jaeger Collector
nc -zv jaeger-collector.observability.svc.cluster.local 4317
# → Connection to jaeger-collector.observability.svc.cluster.local 4317 port [tcp/otlp-grpc] succeeded!

# Тестовая отправка HTTP-запроса в инструментированное приложение
curl -I -s http://127.0.0.1:8080/api/v1/orders/1054
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → Date: Mon, 12 Oct 2026 10:25:01 GMT

# Проверка приема спанов в Jaeger v2 через его Prometheus-метрики
curl -s http://jaeger-collector.observability.svc.cluster.local:8888/metrics | grep otelcol_receiver_accepted_spans
# → otelcol_receiver_accepted_spans{receiver="otlp",transport="grpc"} 1542
```

---

## Диагностика и устранение неполадок

| Проблема / Симптом | Вероятная причина | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| **`operation not permitted` при старте агента** | Отсутствуют capabilities `CAP_BPF` / `CAP_PERFMON` или `kernel.perf_event_paranoid > 2`. | `dmesg \| grep -i bpf` или логи Beyla: `failed to create perf event`. | Добавить capabilities в SecurityContext; выполнить `sysctl -w kernel.perf_event_paranoid=2`. |
| **Спаны не появляются в Jaeger UI** | Приложение слушает порты, не входящие в `BEYLA_OPEN_PORT`, или имя бинарника не совпадает с `exe_path`. | Запустить `sudo bpftool prog show` и проверить логи агента: `Finding instrumentable processes`. | Указать правильный порт в `BEYLA_OPEN_PORT` или шаблон `BEYLA_AUTO_TARGET_EXE` (например, `*`). |
| **Трейс обрывается (нет связи между сервисами)** | Асинхронная передача через очередь сообщений или клиент не передает W3C `traceparent`. | Проверить спан в Jaeger UI: `flags: 0` или отсутствие `parentSpanId`. | Внедрить явный проброс заголовков в код продюсера/консьюмера либо использовать OpenTelemetry SDK для шины сообщений. |
| **`failed to attach uprobe: symbol not found`** | Go или C++ бинарник очищен от символов (`stripped binary`), нет таблицы символов. | `file /app/server` показывает `stripped`, `nm -D /app/server` возвращает `no symbols`. | Компилировать бинарники без флага `-s -w` для Go; для C++ оставить таблицу динамических символов (`-rdynamic`). |
| **HTTPS запросы не отслеживаются** | Статически скомпилированный бинарник с кастомным TLS движком (не OpenSSL/BoringSSL). | `ldd /path/to/binary \| grep ssl` пуст. | Использовать `opentelemetry-go-instrumentation` (для Go TLS) или динамическую линковку с системным OpenSSL. |
| **`BPF ring buffer full / events dropped`** | Слишком высокий RPS на узле, агент не успевает вычитывать события из кольцевого буфера ядра. | Метрика Beyla `beyla_bpf_lost_spans_total > 0` или логи ядра `ringbuf event dropped`. | Увеличить размер буфера через `BEYLA_BPF_RING_BUFFER_SIZE=8388608` (8MB) и выделить больше CPU DaemonSet. |
| **`ENOMEM` / `cannot allocate memory` при bpf() syscall** | Исчерпан лимит `RLIMIT_MEMLOCK` для процесса агента. | Выполнить `ulimit -l`; проверить лимиты cgroup. | Установить `LimitMEMLOCK=infinity` в systemd или снять ограничения memlock в манифесте подов. |
| **Дублирование спанов с Istio / Envoy** | На узле одновременно работают Service Mesh Sidecar и eBPF-агент. | В Jaeger UI для одного HTTP-вызова отображаются два идентичных клиентских спана. | Настроить фильтрацию в Beyla через `BEYLA_DISCOVERY_EXCLUDE` для сервисов, находящихся внутри Service Mesh. |

---

## Лучшие практики и безопасность

1. **Принцип наименьших привилегий (Least Privilege):**
   - Отказывайтесь от `privileged: true` в production-кластерах Kubernetes. Начиная с Linux 5.8, разделяйте привилегии на изолированные capabilities: `CAP_BPF`, `CAP_PERFMON`, `CAP_SYS_PTRACE`, `CAP_NET_RAW`.
   - Задавайте файловые системы контейнера как `readOnlyRootFilesystem: true`, монтируя только необходимые системные пути (`/sys/kernel/tracing`, `/sys/fs/cgroup`).

2. **Точечная фильтрация процессов (Scoping):**
   - Не запускайте автоинструментацию на все порты хоста подряд (`0-65535`). Это создает паразитный оверхед на парсинг системного трафика (etcd, kubelet, coredns).
   - Четко задавайте порты бизнес-сервисов (`BEYLA_OPEN_PORT`) или регулярные выражения исполняемых файлов (`BEYLA_AUTO_TARGET_EXE`).

3. **Нормализация и сжатие маршрутов (Route Normalization):**
   - Динамические идентификаторы в URI (например, `/users/84920/orders/194`) приводят к эффекту высокой кардинальности (High Cardinality) в спанах Jaeger.
   - Используйте секцию `routes.patterns` в конфигурации Beyla для автоматической группировки путей в шаблоны вида `/users/{id}/orders/{order_id}`.

4. **Гибридная модель трассировки:**
   - Применяйте eBPF для быстрого 100% покрытия инфраструктуры, сетевых зависимостей L7 и задержек между процессами.
   - Для ключевых транзакций и критических бизнес-процессов обогащайте трейсы через ручной OpenTelemetry SDK (добавление `customer_id`, бизнес-ошибок, кастомных спанов). Спаны OTel SDK и спаны eBPF корректно склеиваются в Jaeger благодаря общему стандарту W3C Trace Context.

5. **Мониторинг самого eBPF-агента:**
   - Настройте сбор метрик Beyla (`:8999/metrics`) в Prometheus: отслеживайте `beyla_bpf_lost_spans_total`, `beyla_bpf_cpu_seconds_total` и использование памяти процессом агента.

---

## Очистка окружения

Команды для полного удаления компонентов автоинструментации:

### Очистка в Kubernetes

```bash
# Удаление DaemonSet и RBAC Beyla
kubectl delete daemonset beyla -n observability
# → daemonset.apps "beyla" deleted

kubectl delete clusterrolebinding beyla
# → clusterrolebinding.rbac.authorization.k8s.io "beyla" deleted

kubectl delete clusterrole beyla
# → clusterrole.rbac.authorization.k8s.io "beyla" deleted

kubectl delete serviceaccount beyla -n observability
# → serviceaccount "beyla" deleted

# Удаление OpenTelemetry Instrumentation CR
kubectl delete instrumentation otel-ebpf-go-instrumentation -n default
# → instrumentation.opentelemetry.io "otel-ebpf-go-instrumentation" deleted
```

### Очистка на физическом сервере / Linux VM

```bash
# Остановка и отключение сервиса systemd
sudo systemctl stop beyla.service
sudo systemctl disable beyla.service
# → Removed /etc/systemd/system/multi-user.target.wants/beyla.service.

# Удаление файлов сервиса и конфигурации
sudo rm -f /etc/systemd/system/beyla.service
sudo rm -rf /etc/beyla
sudo rm -f /usr/local/bin/beyla
sudo systemctl daemon-reload

# Очистка оставшихся точек uprobe в ядре (при необходимости)
echo "" | sudo tee /sys/kernel/tracing/uprobe_events
```

---

## Дополнительная информация

**Смежные разделы базы знаний:**
- Общие сведения о распределенной трассировке: **[Обзор Jaeger](./jaeger_overview.md)**
- Внутреннее устройство коллектора и пайплайны: **[Архитектура Jaeger](./jaeger_architecture.md)**
- Спецификация и тюнинг протокола OTLP: **[Конфигурация OTLP для Jaeger](./jaeger_otlp_configuration.md)**
- Развертывание коллектора в Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
- Ручная инструментация и работа с OpenTelemetry SDK: **[OpenTelemetry: Инструментация и SDK](../OpenTelemetry/instrumentation_sdk.md)**
- Трассировка в Service Mesh: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**

### См. также

- [Официальная документация Grafana Beyla](https://grafana.com/docs/beyla/latest/)
- [Репозиторий OpenTelemetry Go Auto-Instrumentation](https://github.com/open-telemetry/opentelemetry-go-instrumentation)
- [Проект Odigos — Distributed Tracing with eBPF](https://github.com/odigos-io/odigos)
- [Спецификация W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [Документация BPF в ядре Linux](https://www.kernel.org/doc/html/latest/bpf/index.html)
