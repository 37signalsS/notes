# High Availability и Disaster Recovery для Jaeger

**Актуально для:** Jaeger v2.x

**High Availability (HA)** и **Disaster Recovery (DR)** для Jaeger — комплекс архитектурных и эксплуатационных решений, обеспечивающих непрерывный сбор, буферизацию, сохранение и анализ данных распределенной трассировки при отказах оборудования, сетевых сбоях и масштабных авариях дата-центров. В корпоративной инфраструктуре система распределенной трассировки является критически важным компонентом контура наблюдаемости (Observability). Ее недоступность в момент инцидента приводит к информационной изоляции SRE-инженеров и кратному росту MTTR (Mean Time to Recovery).

Данный документ является единым источником правды (SSoT) по проектированию и эксплуатации отказоустойчивых и катастрофоустойчивых инсталляций Jaeger v2 в локальных (on-premise / bare-metal / частное облако) инфраструктурах без привязки к проприетарным облачным сервисам.

Общий обзор компонентов: **[Обзор Jaeger](./jaeger_overview.md)**.  
Архитектура конвейеров v2: **[Архитектура Jaeger](./jaeger_architecture.md)**.  
Базовые сценарии развертывания: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.  
Внутреннее устройство хранилищ: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**.  
Расчет сайзинга и очередей: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **High Availability (HA)** | Архитектурный подход, обеспечивающий сохранение работоспособности системы при локальных отказах отдельных компонентов (падение процесса, выход из строя сервера, сетевого интерфейса или накопителя) |
| **Disaster Recovery (DR)** | Комплекс мер и процедур по восстановлению работоспособности системы при катастрофических событиях (полная недоступность дата-центра, отказ сетевой магистрали, потеря центрального кластера СУБД) |
| **RTO (Recovery Time Objective)** | Целевое максимальное допустимое время простоя сервиса трассировки до восстановления приема и поиска данных |
| **RPO (Recovery Point Objective)** | Целевой максимально допустимый объем безвозвратно утраченных данных трассировки (например, не более 30 секунд спанов из буфера) |
| **Failover** | Процедура автоматического или ручного переключения входящего трафика и обработки данных на резервные узлы или резервную площадку |
| **Split-Brain** | Состояние распределенной системы, при котором сетевая изоляция разделяет кластер на изолированные сегменты, каждый из которых считает себя лидером, что ведет к повреждению данных |
| **Quorum** | Минимально необходимое число согласованных узлов в распределенном консенсусе (например, в ClickHouse Keeper: `(N/2) + 1`), требуемое для подтверждения операций |
| **In-Sync Replicas (ISR)** | Множество реплик партиции Kafka, полностью синхронизированных с лидером на текущий момент времени |
| **PodDisruptionBudget (PDB)** | Политика Kubernetes, гарантирующая минимальное количество доступных реплик пода при плановом обслуживании узлов (drain, kernel upgrade) |
| **gRPC Load Balancing** | Балансировка мультиплексированных HTTP/2-соединений на прикладном уровне L7 для предотвращения привязки всех запросов одного клиента к единственному Collector |
| **Circuit Breaker** | Защитный механизм, временно прерывающий отправку данных в перегруженный или деградировавший бэкенд для предотвращения исчерпания памяти и каскадного падения сервиса |

---

## Базовые концепции

### Уровни отказоустойчивости

| Уровень | Топология | Резервирование компонентов | Целевой RTO | Целевой RPO | Применимость |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Basic (Standalone)** | 1 ЦОД / 1 стойка | Collector: 1, Query: 1, ClickHouse: Standalone (MergeTree) | Часы | Часы | Тестовые стенды, dev-окружения |
| **High Availability (HA)** | 1 ЦОД / Несколько стоек | Collector: 3+, Query: 2+, Kafka: 3 брокера (RF=3), ClickHouse: 2+ реплики (ReplicatedMergeTree) | < 1 минуты (автоматически) | < 5 секунд | Production средней и высокой нагрузки |
| **Disaster Recovery (DR)** | 2+ независимых ЦОД | Геораспределенный Kafka MirrorMaker 2, репликация хранилища, холодный/горячий резерв Query | 5–15 минут | 10–60 секунд | Enterprise-контуры с жесткими SLA |

### Компоненты и механизмы отказоустойчивости

| Компонент | Тип нагрузки | Механизм HA (локальный контур) | Механизм DR (межЦОД контур) |
| :--- | :--- | :--- | :--- |
| **Collector (Jaeger v2)** | Stateless | Горизонтальное масштабирование (Deployment, 3+ реплики), PodDisruptionBudget, L7-балансировка gRPC, процессор `memory_limiter` | Резервные инстансы во втором ЦОД за глобальным DNS/BGP Anycast |
| **Query / UI (Jaeger v2)** | Stateless | 2+ реплики за обратным прокси (NGINX/HAProxy/Envoy), health-check маршрутизация, чтение с read-only реплик СУБД | Параллельный запуск UI в резервном ЦОД с переключением через GeoDNS |
| **Буфер сообщений (Kafka)** | Stateful | Кластер из 3+ брокеров, топики с `replication.factor=3`, `min.insync.replicas=2`, `acks=all` | Асинхронная межкластерная репликация через Kafka MirrorMaker 2 |
| **Ingester (Jaeger v2)** | Stateless Worker | Масштабирование внутри Consumer Group, автоматический партиционный rebalance при сбое | Резервная Consumer Group в DR-ЦОД в остановленном состоянии (Cold Standby) |
| **Хранилище (ClickHouse)** | Stateful | `ReplicatedMergeTree`, кворум ClickHouse Keeper (3 узла), Distributed-таблицы для маршрутизации | Автоматические регулярные бэкапы в локальное S3-хранилище (MinIO/Ceph RGW), репликация |

### Архитектура высокой доступности

В высоконагруженной и отказоустойчивой архитектуре компоненты Jaeger разделяются на уровни:

```
[ Приложения / SDK / OTel Agent ]
               │
               │ (gRPC / OTLP порт 4317 через L7 Envoy / Headless Service)
               ▼
┌────────────────────────────────────────────────────────┐
│             Jaeger Collector Pool (Stateless)          │
│   [Collector 1]       [Collector 2]       [Collector 3] │
│   (memory_limiter)    (memory_limiter)    (memory_limiter)│
└───────────────────────┬────────────────────────────────┘
                        │
                        │ (Kafka Producer acks=all)
                        ▼
┌────────────────────────────────────────────────────────┐
│               Apache Kafka Cluster (Buffer)             │
│   [Broker 1 (Leader)]   [Broker 2 (ISR)]  [Broker 3 (ISR)]│
│   Топик: jaeger-spans (Partitions: 12, RF: 3)          │
└───────────────────────┬────────────────────────────────┘
                        │
                        │ (Kafka Consumer Group: jaeger-ingester)
                        ▼
┌────────────────────────────────────────────────────────┐
│              Jaeger Ingester Pool (Stateless)          │
│    [Ingester 1]        [Ingester 2]        [Ingester 3] │
└───────────────────────┬────────────────────────────────┘
                        │
                        │ (Native TCP порт 9000)
                        ▼
┌────────────────────────────────────────────────────────┐
│         ClickHouse Cluster (ReplicatedMergeTree)       │
│   ┌───────────────────────┐   ┌───────────────────────┐│
│   │ Node 1 (Replica 1)    │   │ Node 2 (Replica 2)    ││
│   └───────────┬───────────┘   └───────────┬───────────┘│
│               │                           │            │
│               └─────► [ Keeper Quorum ] ◄─┘            │
│                       (3 узла Raft)                    │
└───────────────────────────────────▲────────────────────┘
                                    │ (Чтение)
┌───────────────────────────────────┴────────────────────┐
│              Jaeger Query / UI Pool (Stateless)        │
│          [Query 1]                 [Query 2]           │
│                       ▲                                │
│                       │ (HTTP порт 16686)              │
│               [ Ingress / HAProxy ]                    │
└────────────────────────────────────────────────────────┘
```

#### 1. Уровень приема (Collector)
- **Проблема длительных gRPC-соединений:** OTel SDK и агентские процессы используют постоянные HTTP/2 TCP-соединения. Стандартные L4-балансировщики распределяют только факт открытия TCP-сокета, из-за чего при старте клиентов один инстанс Collector может получить 90% нагрузки.
- **Решение:** Использование L7-проксирования (Envoy, NGINX с `grpc_pass`) с периодическим сбросом соединений (`max_connection_age: 5m`) либо использование Kubernetes Headless Service с клиентской балансировкой Round-Robin в SDK.
- **Предотвращение OOM:** Каждый Collector обязан содержать процессор `memory_limiter` в начале конвейера перед `batch`. При приближении к лимиту памяти Collector возвращает код `ResourceExhausted` (gRPC) или `429 Too Many Requests` (HTTP), защищая процесс от аварийного завершения ядром ОС (OOMKilled).

#### 2. Буферный уровень (Kafka)
- Разделяет контур приема спанов и контур записи в постоянное хранилище. При временной деградации или плановом обслуживании ClickHouse входящие спаны накапливаются в брокере Kafka, гарантируя нулевой RPO.
- Гарантия сохранения: параметр топика `min.insync.replicas=2` в связке с `acks=all` у продюсера гарантирует, что сообщение считается записанным только после фиксации на дисках минимум двух брокеров.

#### 3. Уровень консьюмеров (Ingester)
- Экземпляры Ingester объединяются в единую Consumer Group (`jaeger-ingester`).
- Количество партиций топика задает верхний предел параллелизма вычитки. Рекомендуется выделять не менее 12–24 партиций.
- Offset фиксируется консьюмером только после успешного завершения транзакции сброса пакета спанов в ClickHouse.

#### 4. Уровень хранения (ClickHouse + Keeper)
- Использование движка `ReplicatedMergeTree` гарантирует репликацию данных между узлами на уровне блоков без участия сторонних утилит.
- Метаданные репликации и блокировки координируются через ClickHouse Keeper по протоколу Raft. Кворум из 3 узлов переносит потерю 1 узла без остановки записи.
- Для запросов поиска используется Distributed-таблица, которая выполняет веерную рассылку запроса по шардам и агрегацию результатов.

### Стратегии катастрофоустойчивости (DR)

В локальных средах без использования публичных облаков применяются две основные DR-модели:

1. **Active-Passive (Холодный / Теплый резерв):**
   - **ЦОД-1 (Primary):** Принимает 100% трафика, производит обработку и запись.
   - **МежЦОД канал:** Выделенный L3 VPN / Dark Fiber. Асинхронная передача спанов из кластера Kafka в ЦОД-1 в кластер Kafka в ЦОД-2 через сервис MirrorMaker 2 с политикой `IdentityReplicationPolicy`.
   - **ЦОД-2 (Standby):** Ingester находится в режиме ожидания либо вычитывает реплицированный топик с минимальным числом реплик. ClickHouse в ЦОД-2 синхронизируется через резервные копии либо асинхронную репликацию.
   - **Процедура переключения:** При падении ЦОД-1 выполняется переключение клиентских точек входа (DNS failover / BGP Anycast), запуск Ingester в ЦОД-2 на полную мощность.

2. **Active-Active (Двойной прием):**
   - Клиентские сервисы в каждом ЦОД отправляют трафик в локальный пул Jaeger Collector.
   - Каждый ЦОД изолированно накапливает данные в своем локальном ClickHouse.
   - Jaeger Query настраивается с доступом к обоим кластерам через Distributed-таблицы либо федеративный запрос, объединяя результаты поиска в едином UI.

### Матрица сбоев и реакция системы

| Сценарий отказа | Влияние на систему | Автоматическая реакция | Действия дежурного инженера (SRE) |
| :--- | :--- | :--- | :--- |
| **Падение 1 реплики Collector** | Кратковременный рост задержки на клиентах | Kubernetes перезапускает под; L7 LB исключает узел из пула | Проверить причину падения (`kubectl describe pod`, OOMKilled/Panic) |
| **Плановое обновление узла K8s (drain)** | Нагрузка перераспределяется на оставшиеся реплики | PodDisruptionBudget блокирует одновременное удаление более 1 пода | Контролировать процесс: `kubectl get pdb -A` |
| **Отказ 1 брокера Kafka** | Партиции брокера теряют одну реплику | Лидерство партиций передается оставшимся брокерам из ISR | Заменить вышедший из строя брокер, проверить ребалансировку |
| **Отказ 1 узла ClickHouse** | Снижение емкости пула чтения | Трафик чтения переводится на выжившую реплику; запись продолжается | Восстановить узел; Keeper автоматически передаст недостающие парты |
| **Потеря кворума Keeper (2 из 3 узлов)** | Полная блокировка записи в `ReplicatedMergeTree` | Таблицы переходят в режим `is_readonly = 1`, Collector/Ingester накапливают очередь | Аварийный перезапуск Keeper, ручное восстановление кворума через `force_recovery` |
| **Разрыв межЦОД канала** | Остановка репликации MirrorMaker 2 | Буфер Kafka в ЦОД-1 накапливает спаны в рамках retention (48ч) | Восстановить связность; MirrorMaker автоматически догонит лаг |

---

## Практические сценарии

### Сценарий 1: Отказоустойчивое развертывание Collector и Query в Kubernetes

**Ситуация:** Развертывание пула Jaeger v2 Collector и Query на платформе Kubernetes с защитой от одновременного падения при обслуживании узлов, правильной балансировкой gRPC и мониторингом состояния.

**Предварительные требования:**
- Кластер Kubernetes версии 1.26+ с минимум 3 рабочими нодами.
- Установленный `kubectl` с правами администратора в неймспейсе `observability`.
- Наличие работающего бэкенда (ClickHouse или Kafka).

**Пошаговые инструкции:**

1. Создание манифеста конфигурации Jaeger v2 (`collector-config.yaml`):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: jaeger-collector-config
  namespace: observability
data:
  config.yaml: |
    service:
      extensions: [healthcheckv2]
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, batch]
          exporters: [jaeger_storage_exporter]
      telemetry:
        metrics:
          address: "0.0.0.0:8888"

    extensions:
      healthcheckv2:
        use_v2: true
        http:
          endpoint: "0.0.0.0:13133"
      jaeger_storage:
        backends:
          ch_backend:
            type: clickhouse
            clickhouse:
              endpoint: "tcp://clickhouse.observability.svc.cluster.local:9000"
              database: "jaeger_v2"

    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: "0.0.0.0:4317"
            max_concurrent_streams: 1024
          http:
            endpoint: "0.0.0.0:4318"

    processors:
      memory_limiter:
        check_interval: 250ms
        limit_percentage: 80
        spike_limit_percentage: 20
      batch:
        send_batch_size: 8192
        timeout: 500ms

    exporters:
      jaeger_storage_exporter:
        trace_storage: ch_backend
```

2. Создание манифеста Deployment, Service и PodDisruptionBudget для Collector (`collector-ha.yaml`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger-collector
  namespace: observability
  labels:
    app.kubernetes.io/name: jaeger-collector
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector
  template:
    metadata:
      labels:
        app.kubernetes.io/name: jaeger-collector
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app.kubernetes.io/name: jaeger-collector
                topologyKey: kubernetes.io/hostname
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: jaeger-collector
      containers:
        - name: collector
          image: jaegertracing/jaeger:2.3.0
          args: ["--config", "/etc/jaeger/config.yaml"]
          ports:
            - name: otlp-grpc
              containerPort: 4317
            - name: otlp-http
              containerPort: 4318
            - name: health
              containerPort: 13133
            - name: metrics
              containerPort: 8888
          livenessProbe:
            httpGet:
              path: /
              port: 13133
            initialDelaySeconds: 10
            periodSeconds: 15
            timeoutSeconds: 3
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /
              port: 13133
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 2
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: 2000m
              memory: 2Gi
          volumeMounts:
            - name: config
              mountPath: /etc/jaeger
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: jaeger-collector-config
---
apiVersion: v1
kind: Service
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: jaeger-collector
  ports:
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
    - name: otlp-http
      port: 4318
      targetPort: 4318
    - name: metrics
      port: 8888
      targetPort: 8888
---
apiVersion: v1
kind: Service
metadata:
  name: jaeger-collector-headless
  namespace: observability
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: jaeger-collector
  ports:
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: jaeger-collector-pdb
  namespace: observability
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector
```

3. Развертывание пула интерфейса Jaeger Query (`query-ha.yaml`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger-query
  namespace: observability
  labels:
    app.kubernetes.io/name: jaeger-query
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-query
  template:
    metadata:
      labels:
        app.kubernetes.io/name: jaeger-query
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app.kubernetes.io/name: jaeger-query
                topologyKey: kubernetes.io/hostname
      containers:
        - name: query
          image: jaegertracing/jaeger:2.3.0
          args: ["--config", "/etc/jaeger/query-config.yaml"]
          ports:
            - name: query-http
              containerPort: 16686
            - name: health
              containerPort: 13133
          livenessProbe:
            httpGet:
              path: /
              port: 13133
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /
              port: 13133
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          volumeMounts:
            - name: config
              mountPath: /etc/jaeger
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: jaeger-collector-config
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: jaeger-query-pdb
  namespace: observability
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-query
```

**Валидация:**

1. Применить конфигурацию и проверить статус подов:
```bash
kubectl apply -f collector-config.yaml
# → configmap/jaeger-collector-config created
kubectl apply -f collector-ha.yaml
# → deployment.apps/jaeger-collector created
# → service/jaeger-collector created
# → service/jaeger-collector-headless created
# → poddisruptionbudget.policy/jaeger-collector-pdb created
kubectl apply -f query-ha.yaml
# → deployment.apps/jaeger-query created
# → poddisruptionbudget.policy/jaeger-query-pdb created

kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-collector -o wide
# → NAME                                READY   STATUS    RESTARTS   AGE   IP             NODE
# → jaeger-collector-7d8b5c98-1a2b3     1/1     Running   0          45s   10.244.1.15    worker-node-01
# → jaeger-collector-7d8b5c98-4c5d6     1/1     Running   0          45s   10.244.2.22    worker-node-02
# → jaeger-collector-7d8b5c98-7e8f9     1/1     Running   0          45s   10.244.3.18    worker-node-03
```

2. Проверить состояние политик PodDisruptionBudget:
```bash
kubectl get pdb -n observability
# → NAME                   MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → jaeger-collector-pdb   N/A             1                 1                     1m
# → jaeger-query-pdb       N/A             1                 1                     1m
```

3. Проверить ответ встроенного healthcheckv2 расширения:
```bash
kubectl exec -n observability deploy/jaeger-collector -- curl -s -i http://127.0.0.1:13133/
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → Date: Mon, 12 Oct 2026 14:15:00 GMT
# → Content-Length: 0
```

---

### Сценарий 2: Настройка отказоустойчивого кластера ClickHouse с ReplicatedMergeTree и ClickHouse Keeper

**Ситуация:** Развертывание 2-узлового кластера ClickHouse с репликацией таблиц Jaeger v2 и кворумной координацией через ClickHouse Keeper для обеспечения безотказной записи при потере одного сервера.

**Предварительные требования:**
- Два сервера Linux (CentOS Stream / Debian / Ubuntu) с установленным `clickhouse-server` (версия 24.x или 26.x).
- Hostnames: `ch-node-01` (192.168.10.21), `ch-node-02` (192.168.10.22).
- Сетевая связность по портам 9000 (Native), 8123 (HTTP), 9234 (Raft), 2181 (Keeper TCP).

**Пошаговые инструкции:**

1. Настройка ClickHouse Keeper на обоих узлах (`/etc/clickhouse-server/config.d/keeper.xml`).  
*На узле ch-node-01 (`server_id: 1`):*

```xml
<clickhouse>
    <keeper_server>
        <tcp_port>2181</tcp_port>
        <server_id>1</server_id>
        <log_storage_path>/var/lib/clickhouse/keeper/log</log_storage_path>
        <snapshot_storage_path>/var/lib/clickhouse/keeper/snapshots</snapshot_storage_path>
        <coordination_settings>
            <operation_timeout_ms>10000</operation_timeout_ms>
            <session_timeout_ms>30000</session_timeout_ms>
            <raft_logs_level>information</raft_logs_level>
        </coordination_settings>
        <raft_configuration>
            <server>
                <id>1</id>
                <host>192.168.10.21</host>
                <port>9234</port>
            </server>
            <server>
                <id>2</id>
                <host>192.168.10.22</host>
                <port>9234</port>
            </server>
        </raft_configuration>
    </keeper_server>

    <zookeeper>
        <node>
            <host>192.168.10.21</host>
            <port>2181</port>
        </node>
        <node>
            <host>192.168.10.22</host>
            <port>2181</port>
        </node>
    </zookeeper>
</clickhouse>
```
*(На узле `ch-node-02` в секции `<keeper_server>` значение `<server_id>` устанавливается равным `2`).*

2. Описание топологии кластера и макросов (`/etc/clickhouse-server/config.d/cluster.xml`):

```xml
<clickhouse>
    <remote_servers>
        <jaeger_cluster>
            <shard>
                <internal_replication>true</internal_replication>
                <replica>
                    <host>192.168.10.21</host>
                    <port>9000</port>
                </replica>
                <replica>
                    <host>192.168.10.22</host>
                    <port>9000</port>
                </replica>
            </shard>
        </jaeger_cluster>
    </remote_servers>

    <macros>
        <cluster>jaeger_cluster</cluster>
        <shard>01</shard>
        <!-- На ch-node-01: ch-node-01; на ch-node-02: ch-node-02 -->
        <replica>ch-node-01</replica>
    </macros>
</clickhouse>
```

3. Перезапуск службы ClickHouse на серверах:
```bash
sudo systemctl restart clickhouse-server
# → [OK] clickhouse-server restarted
```

4. Создание схемы базы данных и реплицируемой таблицы на кластере:

```sql
-- 1. Создание базы данных на всех узлах кластера
CREATE DATABASE IF NOT EXISTS jaeger_v2 ON CLUSTER '{cluster}';

-- 2. Создание локальной реплицируемой таблицы
CREATE TABLE IF NOT EXISTS jaeger_v2.spans_local ON CLUSTER '{cluster}'
(
    trace_id String,
    span_id String,
    operation_name String,
    start_time_ns UInt64,
    duration_ns UInt64,
    service_name String,
    tags Map(String, String),
    logs Array<JSON>,
    references Array<String>,
    process Array<String>,
    flags UInt32,
    PRIMARY KEY (trace_id, span_id)
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/jaeger_v2/spans', '{replica}')
PARTITION BY toDate(fromUnixTimestamp64Nano(start_time_ns))
ORDER BY (service_name, operation_name, start_time_ns)
TTL toDateTime(start_time_ns / 1000000000) + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;

-- 3. Создание распределенной таблицы для запросов поиска
CREATE TABLE IF NOT EXISTS jaeger_v2.spans ON CLUSTER '{cluster}' AS jaeger_v2.spans_local
ENGINE = Distributed('{cluster}', jaeger_v2, spans_local, rand());
```

**Валидация:**

1. Проверить состояние кворума Keeper:
```bash
echo mntr | nc 192.168.10.21 2181 | grep -E "zk_version|zk_server_state|zk_synced_followers"
# → zk_version       v26.8.2.1-testing-deadbeef
# → zk_server_state  leader
# → zk_synced_followers      1
```

2. Проверить статус репликации в таблице `system.replicas`:
```bash
clickhouse-client --query "SELECT database, table, is_leader, is_readonly, absolute_delay FROM system.replicas WHERE database='jaeger_v2'"
# → jaeger_v2   spans_local     1       0       0
```

3. Тестирование сбоя узла (Failover):
```bash
# Имитация аварии первого узла
sudo systemctl stop clickhouse-server # на ch-node-01

# Проверка статуса со второго узла
clickhouse-client --host 192.168.10.22 --query "
INSERT INTO jaeger_v2.spans_local (trace_id, span_id, operation_name, start_time_ns, service_name)
VALUES ('trace-failover-test-01', 'span-01', 'GET /checkout', 1700000000000000000, 'billing-service');
SELECT count() FROM jaeger_v2.spans_local;
"
# → 1

# Запуск первого узла обратно
sudo systemctl start clickhouse-server # на ch-node-01

# Проверка автоматической синхронизации данных
clickhouse-client --host 192.168.10.21 --query "SELECT count() FROM jaeger_v2.spans_local WHERE trace_id='trace-failover-test-01'"
# → 1
```

---

### Сценарий 3: Резервное копирование и восстановление ClickHouse в локальное S3-хранилище (MinIO / Ceph RGW)

**Ситуация:** Организация регулярного создания резервных копий таблицы трейсов в корпоративное локальное S3-хранилище (MinIO / Ceph Object Gateway) и проведение планового учения по восстановлению (DR drill).

**Предварительные требования:**
- Доступность S3-совместимого хранилища (MinIO): `http://minio.storage.internal:9000`.
- Созданный бакет: `jaeger-backups`.
- Учетные данные с правами на запись и чтение: `access_key` / `secret_key`.

**Пошаговые инструкции:**

1. Создание резервной копии таблицы спанов в MinIO:

```bash
# Запуск создания снапшота таблицы с отметкой даты
BACKUP_TIMESTAMP=$(date +%Y%m%d_%H%M%S)

clickhouse-client --query "
BACKUP TABLE jaeger_v2.spans_local
TO S3('http://minio.storage.internal:9000/jaeger-backups/${BACKUP_TIMESTAMP}/', 'minio_admin', 'Secr3t_MinIO_P@ss')
SETTINGS compression_method = 'zstd';
"
# → Backup jaeger_v2.spans_local completed: 1 table(s), 42 parts backed up.
```

2. Моделирование катастрофы (случайное удаление данных или повреждение диска):

```bash
clickhouse-client --query "DROP TABLE jaeger_v2.spans_local NO DELAY;"
# → Table jaeger_v2.spans_local dropped.
```

3. Восстановление таблицы из резервной копии:

```bash
clickhouse-client --query "
RESTORE TABLE jaeger_v2.spans_local
FROM S3('http://minio.storage.internal:9000/jaeger-backups/${BACKUP_TIMESTAMP}/', 'minio_admin', 'Secr3t_MinIO_P@ss');
"
# → Restore jaeger_v2.spans_local completed: 1 table(s), 42 parts restored.
```

**Валидация:**

1. Проверить наличие и целостность восстановленных данных:
```bash
clickhouse-client --query "
SELECT count(), min(toDate(fromUnixTimestamp64Nano(start_time_ns))), max(toDate(fromUnixTimestamp64Nano(start_time_ns)))
FROM jaeger_v2.spans_local;
"
# → 48291054    2026-10-05      2026-10-12
```

2. Проверить доступность таблицы через распределенный интерфейс:
```bash
clickhouse-client --query "SELECT count() FROM jaeger_v2.spans;"
# → 48291054
```

---

### Сценарий 4: МежЦОД репликация буфера трейсов через Kafka MirrorMaker 2 (Active-Passive DR)

**Ситуация:** Организация непрерывной асинхронной передачи спанов из основного дата-центра (DC-1) в резервный дата-центр (DC-2) с сохранением исходных имен топиков и смещений групп консьюмеров.

**Предварительные требования:**
- Кластер Apache Kafka в DC-1 (`dc1-broker-01:9092,dc1-broker-02:9092,dc1-broker-03:9092`).
- Кластер Apache Kafka в DC-2 (`dc2-broker-01:9092,dc2-broker-02:9092,dc2-broker-03:9092`).
- Выделенный сервер или виртуальная машина под процесс MirrorMaker 2 в DC-2.

**Пошаговые инструкции:**

1. Создание топика `jaeger-spans` в основном и резервном кластерах:
```bash
# Выполняется на брокерах в DC-1 и DC-2
kafka-topics.sh --bootstrap-server localhost:9092 --create \
  --topic jaeger-spans \
  --partitions 12 \
  --replication-factor 3 \
  --config min.insync.replicas=2 \
  --config retention.hours=48 \
  --config compression.type=lz4
# → Created topic jaeger-spans.
```

2. Создание файла конфигурации MirrorMaker 2 (`/etc/kafka/mm2-jaeger.properties`):

```properties
# Алиасы кластеров
clusters = dc1, dc2

# Точки подключения брокеров
dc1.bootstrap.servers = 10.10.10.11:9092,10.10.10.12:9092,10.10.10.13:9092
dc2.bootstrap.servers = 10.20.10.11:9092,10.20.10.12:9092,10.20.10.13:9092

# Направление передачи: только dc1 -> dc2
dc1->dc2.enabled = true
dc2->dc1.enabled = false

# Фильтрация топиков: только топики трассировки
dc1->dc2.topics = jaeger-spans.*
dc1->dc2.topics.exclude = .*[\-\.]internal, .*[\-\.]checkpoint, .*[\-\.]heartbeat

# Сохранение исходного имени топика в DC-2 без добавления префикса "dc1."
replication.policy.class = org.apache.kafka.connect.mirror.IdentityReplicationPolicy

# Синхронизация смещений групп консьюмеров (Offset Sync)
dc1->dc2.sync.group.offsets.enabled = true
dc1->dc2.sync.group.offsets.interval.seconds = 5
dc1->dc2.emit.checkpoints.interval.seconds = 5
dc1->dc2.groups = jaeger-ingester.*

# Факторы репликации служебных топиков в DC-2
replication.factor = 3
checkpoints.topic.replication.factor = 3
heartbeats.topic.replication.factor = 3
offset-syncs.topic.replication.factor = 3

# Тюнинг пропускной способности продюсера MM2
dc1->dc2.producer.compression.type = zstd
dc1->dc2.producer.batch.size = 131072
dc1->dc2.producer.linger.ms = 25
dc1->dc2.producer.max.in.flight.requests.per.connection = 5
```

3. Запуск MirrorMaker 2 в фоновом режиме через systemd (`/etc/systemd/system/kafka-mm2.service`):

```ini
[Unit]
Description=Apache Kafka MirrorMaker 2 (Jaeger Tracing DR)
After=network.target

[Service]
Type=simple
User=kafka
ExecStart=/opt/kafka/bin/connect-mirror-maker.sh /etc/kafka/mm2-jaeger.properties
Restart=on-failure
RestartSec=10s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kafka-mm2
# → Created symlink /etc/systemd/system/multi-user.target.wants/kafka-mm2.service
```

**Валидация:**

1. Проверить статус службы MirrorMaker 2:
```bash
sudo systemctl status kafka-mm2 --no-pager
# → ● kafka-mm2.service - Apache Kafka MirrorMaker 2 (Jaeger Tracing DR)
# →    Loaded: loaded (/etc/systemd/system/kafka-mm2.service; enabled; vendor preset: disabled)
# →    Active: active (running) since Mon 2026-10-12 14:20:10 MSK; 1min ago
# →  Main PID: 18452 (java)
```

2. Отправить тестовый спан в кластер DC-1 и проверить появление сообщения в топике DC-2:
```bash
# Отправка тестового сообщения в DC-1
echo "test-span-payload-dr-verification" | /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server 10.10.10.11:9092 \
  --topic jaeger-spans

# Чтение из топика в DC-2
/opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server 10.20.10.11:9092 \
  --topic jaeger-spans \
  --from-beginning \
  --max-messages 1
# → test-span-payload-dr-verification
```

3. Проверить состояние трансляции офсетов для Ingester в DC-2:
```bash
/opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server 10.20.10.11:9092 \
  --describe \
  --group jaeger-ingester
# → GROUP           TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST            CLIENT-ID
# → jaeger-ingester jaeger-spans    0          1045820         1045822         2               -               -               -
```

---

### Сценарий 5: Graceful Shutdown, дрейн очередей и Persistent Queue при Rolling Updates в Kubernetes

**Задача:** Предотвратить потерю спанов, находящихся в памяти и очередях коллектора, при плановых обновлениях подов (`kubectl rollout restart`), выселении подов (`kubectl drain`) и автомасштабировании.

#### Проблема потери данных при SIGTERM:
1. При получении сигнала `SIGTERM` процесс OTel/Jaeger немедленно закрывает входящие порты и начинает сброс внутренних буферов.
2. Однако контроллер эндпоинтов Kubernetes (`kube-proxy`, IPVS, CNI) обновляет сетевые таблицы с задержкой в 2–5 секунд. В этот интервал клиентские сервисы продолжают слать gRPC-запросы в закрывающийся под, получая ошибки `Unavailable`.
3. Если буфер экспортера (`queue`) хранится только в RAM, а база данных медленно подтверждает запись, по истечении `terminationGracePeriodSeconds` процесс принудительно убивается сигналом `SIGKILL`, уничтожая оставшиеся в памяти спаны.

#### 1. Конфигурация надежного сброса через Persistent Queue (`file_storage`)

В Jaeger v2 для гарантии сохранности очередей при перезапусках подключается расширение `file_storage`:

```yaml
extensions:
  file_storage:
    directory: /var/lib/jaeger/buffer
    timeout: 5s
    compaction:
      on_rebound: true
      directory: /var/lib/jaeger/buffer/compact

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_main
    sending_queue:
      enabled: true
      num_consumers: 16
      queue_size: 25000
      # Буферизация на диске защищает от потери при рестартах пода
      storage: file_storage
    retry_on_failure:
      enabled: true
      initial_interval: 1s
      max_interval: 30s
      max_elapsed_time: 5m
```

#### 2. Тюнинг манифеста Deployment в Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    spec:
      # Достаточное время на сброс дисковых очередей и досыл данных в СУБД
      terminationGracePeriodSeconds: 60
      containers:
        - name: jaeger
          image: jaegertracing/jaeger:2.2.0
          lifecycle:
            preStop:
              exec:
                # Пауза 10 секунд гарантирует, что kube-proxy успел исключить под из iptables/IPVS
                # до того, как Jaeger закроет OTLP порты
                command: ["/bin/sh", "-c", "sleep 10"]
          volumeMounts:
            - name: buffer-storage
              mountPath: /var/lib/jaeger/buffer
      volumes:
        - name: buffer-storage
          emptyDir:
            sizeLimit: 10Gi
```

#### 3. Валидация штатного завершения в логах

```bash
# Инициация планового перезапуска пула коллекторов
kubectl rollout restart deployment/jaeger-collector -n observability
# → deployment.apps/jaeger-collector restarted

# Просмотр логов останавливаемого пода
kubectl logs -n observability <terminating-pod-name> -c jaeger --tail=50
# → {"level":"info","msg":"Received SIGTERM signal. Initiating shutdown..."}
# → {"level":"info","msg":"Stopping OTLP gRPC and HTTP receivers..."}
# → {"level":"info","msg":"Flushing remaining spans in exporter queues to storage..."}
# → {"level":"info","msg":"Exporter queue drained successfully. 0 spans remaining."}
# → {"level":"info","msg":"Everything stopped? Welcome to the universe! Process exited gracefully."}
```

---

### Сценарий 6: Продакшен-мониторинг и алертинг через PrometheusRule (Alertmanager)

**Задача:** Настроить проактивный мониторинг работоспособности кластера Jaeger v2 и выявление переполнения очередей, деградации хранилища и потери спанов до того, как инцидент повлияет на SRE-команды.

#### Манифест `PrometheusRule` для Prometheus Operator

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: jaeger-cluster-alerts
  namespace: observability
  labels:
    role: alert-rules
    prometheus: k8s-prometheus
spec:
  groups:
    - name: jaeger_v2_operational_alerts
      rules:
        # 1. Отклонение спанов на входе (проблемы сети, сериализации, квот)
        - alert: JaegerReceiverRefusedSpansHigh
          expr: |
            (
              sum(rate(otelcol_receiver_refused_spans_total[5m])) 
              / 
              (sum(rate(otelcol_receiver_accepted_spans_total[5m])) + sum(rate(otelcol_receiver_refused_spans_total[5m])))
            ) * 100 > 1.0
          for: 3m
          labels:
            severity: warning
            tier: observability
          annotations:
            summary: "Jaeger Collector отклоняет более 1% входящих спанов"
            description: "Текущий процент отказа: {{ $value | printf \"%.2f\" }}%. Возможная причина: переполнение буферов, невалидные OTLP структуры или mTLS сбои."

        # 2. Насыщение очереди экспортера (риск переполнения буфера записи)
        - alert: JaegerExporterQueueSaturationCritical
          expr: |
            (
              max(otelcol_exporter_queue_size) by (pod, exporter)
              / 
              max(otelcol_exporter_queue_capacity) by (pod, exporter)
            ) > 0.85
          for: 2m
          labels:
            severity: critical
            tier: observability
          annotations:
            summary: "Очередь экспортера Jaeger переполнена более чем на 85%"
            description: "Экспортер {{ $labels.exporter }} на поде {{ $labels.pod }} заполнен на {{ $value | printf \"%.2f\" }}%. Узкое место в дисковой подсистеме ClickHouse или перегрузка сети."

        # 3. Экстренный сброс спанов процессором memory_limiter (OOM Protection)
        - alert: JaegerMemoryLimiterDroppingSpans
          expr: sum(rate(otelcol_processor_dropped_spans_total{processor="memory_limiter"}[3m])) > 0
          for: 1m
          labels:
            severity: critical
            tier: observability
          annotations:
            summary: "Jaeger Memory Limiter принудительно отбрасывает спаны"
            description: "Потребление памяти коллектора превысило пороговые значения limit_percentage. Срочно увеличьте RAM-лимиты или включите агрессивное сэмплирование."

        # 4. Ошибки физической записи в ClickHouse / Elasticsearch
        - alert: JaegerStorageWriteFailures
          expr: sum(rate(otelcol_exporter_send_failed_spans_total[5m])) > 0
          for: 2m
          labels:
            severity: critical
            tier: observability
          annotations:
            summary: "Ошибки физической фиксации спанов в хранилище"
            description: "Экспортер не может записать пачки спанов в ClickHouse. Проверьте статус readonly в репликах СУБД, дисковое пространство и логи драйвера."

        # 5. Критический лаг вычитывания из Kafka (при стриминговой топологии)
        - alert: JaegerKafkaConsumerLagHigh
          expr: sum(kafka_consumergroup_lag{topic="jaeger-spans"}) > 100000
          for: 5m
          labels:
            severity: warning
            tier: observability
          annotations:
            summary: "Накопление лага консьюмеров Jaeger Ingester в Kafka"
            description: "Необработанный лаг в топике jaeger-spans превысил 100 000 спанов (текущее значение: {{ $value }}). Увеличьте число реплик Ingester."
```

#### Валидация правил алертинга через PromQL

```bash
# Проверка срабатывания формулы насыщенности очереди в Prometheus API
curl -sS "http://prometheus.observability.svc:9090/api/v1/query?query=max(otelcol_exporter_queue_size)/max(otelcol_exporter_queue_capacity)" | jq .
# → {
# →   "status": "success",
# →   "data": {
# →     "resultType": "vector",
# →     "result": [
# →       {
# →         "metric": { "exporter": "jaeger_storage_exporter/clickhouse_main" },
# →         "value": [ 1773315000, "0.12" ]
# →       }
# →     ]
# →   }
# → }
```

---

## Операции и команды

Сводная таблица регламентных и аварийных команд при эксплуатации отказоустойчивого контура:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Проверка готовности Collector** | `curl -s -o /dev/null -w "%{http_code}\n" http://<collector-ip>:13133/` | Проверка `healthcheckv2` расширения (`# → 200`) |
| **Проверка очереди отправки** | `curl -s http://<collector-ip>:8888/metrics \| grep otelcol_exporter_queue_size` | Контроль переполнения очередей отправки спанов в бэкенд |
| **Безопасный вывод узла K8s (drain)** | `kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data` | Эвакуация подов с соблюдением `PodDisruptionBudget` |
| **Проверка кворума Keeper** | `echo mntr \| nc <keeper-ip> 2181 \| grep zk_server_state` | Определение роли узла Keeper (`leader` или `follower`) |
| **Контроль задержки репликации CH** | `clickhouse-client --query "SELECT database, table, is_readonly, absolute_delay FROM system.replicas"` | Выявление отстающих реплик (`absolute_delay > 0`) |
| **Проверка лага Ingester** | `kafka-consumer-groups.sh --bootstrap-server <broker>:9092 --describe --group jaeger-ingester` | Контроль накопления невычитанных спанов в партициях |
| **Принудительный сброс соединений L7** | `kubectl rollout restart deployment/jaeger-collector -n observability` | Перебалансировка gRPC потоков при неравномерной нагрузке |

---

## Диагностика и устранение неисправностей

| Проблема / Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Сильный перекос нагрузки между подами Collector (1 под загружен на 100%, остальные на 5%)** | L4-балансировщик привязал мультиплексированные gRPC HTTP/2 потоки одного крупного сервиса к одному проду | Метрика `otelcol_receiver_accepted_spans` различается в 10+ раз между подами (`curl http://pod-ip:8888/metrics`) | 1. Настроить L7 Ingress (Envoy/Traefik) с директивой балансировки стримов.<br>2. Настроить Kubernetes Headless Service и включить `round_robin` DNS load balancing в OTel SDK клиента. |
| **ClickHouse реплика перешла в режим read-only (`is_readonly = 1`)** | Потеряна связь с узлами ClickHouse Keeper или нарушен кворум Raft | Запрос: `SELECT is_readonly FROM system.replicas WHERE database='jaeger_v2';`<br>Лог: `/var/log/clickhouse-server/clickhouse-server.err.log` содержит `Coordination::Exception` | 1. Проверить доступность портов Keeper: `echo ruok \| nc 127.0.0.1 2181`.<br>2. Восстановить сетевую связность между узлами Keeper.<br>3. При фатальной потере узлов выполнить восстановление кворума через `<force_recovery>`. |
| **Лавинообразный рост Consumer Lag у Ingester** | ClickHouse не успевает принимать спаны (дисковый bottleneck) либо число инстансов Ingester меньше числа партиций | `kafka-consumer-groups.sh --describe` показывает рост `LAG`; логи Ingester: `Exporting failed: timeout` | 1. Увеличить число реплик Ingester до числа партиций топика.<br>2. Увеличить `send_batch_size` до 16384 в `batch` процессоре Ingester.<br>3. Проверить IOPS дисков ClickHouse (`iostat -xz 1`). |
| **Collector падает с кодом OOMKilled (Exit Code 137)** | Всплеск спанов переполнил очередь батчера при отсутствии или заниженном лимите `memory_limiter` | `kubectl describe pod` показывает `Last State: Terminated, Reason: OOMKilled`; метрика `otelcol_processor_dropped_spans = 0` | 1. Убедиться, что процессор `memory_limiter` стоит первым в `processors: [memory_limiter, batch]`.<br>2. Выставить `limit_percentage: 80`, `spike_limit_percentage: 20`.<br>3. Увеличить RAM limit пода до значения, согласованного с Capacity Planning. |
| **`kubectl drain` зависает с ошибкой `Cannot evict pod: PDB blocks eviction`** | Спецификация PDB задана как `minAvailable: 2`, при этом один из трех подов находится в состоянии CrashLoopBackOff | `kubectl get pdb -n observability` показывает `ALLOWED DISRUPTIONS: 0` | 1. Использовать `maxUnavailable: 1` вместо жесткого `minAvailable`.<br>2. Устранить сбой в упавшем поде либо временно масштабировать Deployment: `kubectl scale deploy/jaeger-collector --replicas=4`. |

---

## Лучшие практики

1. **Правило N+2 для stateless компонентов:** В production-среде развертывайте не менее 3 реплик Collector и Ingester. Это гарантирует сохранение запаса емкости при одновременном падении одного пода и плановом обновлении (Rolling Update) второго.
2. **Использование `maxUnavailable: 1` в PDB:** Для пулов с динамическим масштабированием (HPA) всегда используйте процентное соотношение или `maxUnavailable: 1` вместо `minAvailable`. Это предотвращает тупиковые блокировки при выводе нод в drain.
3. **Разделение дисковых пулов для СУБД:** Храните журнал предзаписи (WAL/log) ClickHouse Keeper на выделенном быстром SSD/NVMe отдельно от директории данных `data_path` ClickHouse. Высокая дисковая задержка на запись спанов не должна замедлять отклики консенсуса Raft.
4. **Конфигурация `acks=all` и `min.insync.replicas=2`:** Всегда комбинируйте эти параметры в Kafka для защиты от потери спанов при внезапной перезагрузке брокера-лидера.
5. **Circuit Breaker и контролируемый сброс:** При катастрофической перегрузке хранилища Jaeger должен сбрасывать входящие спаны через `memory_limiter`, а не пытаться бесконечно буферизировать их в ОЗУ. Падение системы трассировки не должно вызывать деградацию бизнес-приложений.
6. **Регулярные учения по аварийному переключению (GameDays):** Раз в квартал имитируйте внезапное отключение одного сервера ClickHouse и сетевую изоляцию одной зоны Kubernetes для подтверждения автоматического восстановления сервиса.

---

## Очистка окружения

Команды удаления тестовых и лабораторных ресурсов:

```bash
# 1. Удаление ресурсов Kubernetes
kubectl delete namespace observability
# → namespace "observability" deleted

# 2. Остановка службы репликации MirrorMaker 2
sudo systemctl stop kafka-mm2
# → [OK] kafka-mm2.service stopped

# 3. Удаление тестовой базы данных в ClickHouse
clickhouse-client --query "DROP DATABASE IF EXISTS jaeger_v2 ON CLUSTER '{cluster}';"
# → Dropped database jaeger_v2.

# 4. Удаление топиков в Kafka
kafka-topics.sh --bootstrap-server localhost:9092 --delete --topic jaeger-spans
# → Topic jaeger-spans marked for deletion.
```

---

## Дополнительная информация

**Смежные материалы в базе знаний:**
- Общие архитектурные концепции отказоустойчивости: **[Высокая доступность: Обзор](../Concepts/High_Availability/ha_overview.md)**
- Корпоративные стратегии межЦОД аварийного восстановления: **[Стратегии аварийного восстановления](../Concepts/disaster_recovery.md)**
- Кластеризация и настройка ClickHouse Keeper: **[Кластеризация ClickHouse](../Databases/ClickHouse/clickhouse-cluster.md)**
- Disaster Recovery и сайзинг очередей Kafka: **[Планирование емкости и DR для Kafka](../Kafka/kafka_capacity_dr.md)**
- Детальный разбор хранилищ Jaeger v2: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**
- Интеграция с оркестрацией Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**

**Официальная документация:**
- [Jaeger Tracing v2 Documentation](https://www.jaegertracing.io/docs/)
- [ClickHouse Keeper Configuration Guide](https://clickhouse.com/docs/en/operations/clickhouse-keeper)
- [Apache Kafka MirrorMaker 2 Architecture](https://kafka.apache.org/documentation/#georeplication)
