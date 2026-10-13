# Шардирование рабочих нагрузок и данных в Kubernetes

**Актуально для:** Kubernetes 1.31+, Gateway API v1.2+, KEDA 2.15+

## Определения

**Шардирование (Sharding)** — метод горизонтального разделения вычислительной нагрузки, очередей или хранилища данных на независимые изолированные группы (шарды). В контексте Kubernetes под шардированием понимается развертывание нескольких независимых наборов контроллеров (`Deployment`, `StatefulSet`) и ассоциированных инфраструктурных ресурсов (PVC, Service, NetworkPolicy, PDB, ConfigMap), где каждый шард обслуживает строго определенный сегмент клиентского трафика или партицию данных.

**Шард (Shard)** — автономный домен выполнения рабочей нагрузки, состоящий из изолированного набора подов, сервисов, томов постоянного хранения и правил балансировки, функционирующий независимо от соседних шардов.

**Радиус поражения (Blast Radius)** — концепция ограничения масштаба негативных последствий аппаратного или программного сбоя. Шардирование локализует отказ: авария в одном шарде (утечка памяти, OOMKilled подов, шторм «тяжелых» запросов или зависание БД) не распространяется на остальные сегменты кластера.

**Перемешанное шардирование (Shuffled Sharding)** — математический паттерн распределения клиентских потоков по подмножествам очередей или шардов из общего пула (комбинация $k$ шардов из $N$ доступных). Даже при малом $k$ общее число виртуальных комбинаций $\binom{N}{k}$ стремительно возрастает, что изолирует конфликтующих клиентов друг от друга. Лежит в основе механизма Kubernetes API Priority and Fairness (APF).

**Перекос шардов (Shard Skew)** — статистическая асимметрия распределения запросов, CPU/памяти или объема хранимых данных между шардами. Возникает из-за неудачно выбранного ключа шардирования или изменения паттернов клиентского поведения.

**Горячий шард (Hot Shard)** — шард, испытывающий аномально высокую утилизацию ресурсов или задержку обработки (latency) по сравнению со средней величиной по кластеру.

**Консистентное хеширование (Consistent Hashing)** — алгоритм привязки запросов или партиций данных к узлам кольца (hash ring), при котором изменение количества шардов ($N \to N+1$ или $N \to N-1$) требует перемещения только $K/N$ ключей (где $K$ — общее число ключей), минимизируя объемы сетевого ребалансирования.

**Межшардная маршрутизация (Cross-shard Routing)** — слой диспетчеризации трафика (L4/L7 Ingress, Gateway API или координатор приложений), вычисляющий целевой шард на основе атрибутов пакета или сессии (IP клиента, HTTP-заголовки, tenant ID, ключ партиции) и направляющий трафик без промежуточных накладных расходов.

**Связанная концепция:** **[Шардирование баз данных (Общая теория)](../../Databases/Concepts/sharding.md)**.

---

## Архитектура и основные концепции

### Инфраструктурные предпосылки шардирования в Kubernetes (On-Premise / SRE)

В production-средах bare-metal и частных облаков масштабирование монолитного `Deployment` или `StatefulSet` до сотен подов сталкивается с жесткими системными ограничениями:

```
[ Клиентский трафик ]
         │
         ▼
[ L7 Shard Router / Gateway API ]
   ├── (Tenant A: dc1) ──► [ Shard 0: Deployment + HPA ] ──► [ Local PV / NVMe ]
   ├── (Tenant B: dc2) ──► [ Shard 1: Deployment + HPA ] ──► [ Local PV / NVMe ]
   └── (Tenant C: dc1) ──► [ Shard 2: Deployment + HPA ] ──► [ Local PV / NVMe ]
                                   │
              [ Shuffled Sharding Protection via APF ]
```

1. **Снижение нагрузки на Control Plane и etcd:**
   * Массовые изменения статусов подов (Ready/NotReady, фазы контейнеров) в рамках одного объекта вызывают лавинные обновления в `etcd`. База `etcd` чувствительна к размеру транзакций и задержкам `fsync` на дисках WAL (лимит размера базы по умолчанию 2–8 ГБ).
   * Разбиение монолита на шарды (`shard-0`, `shard-1`, ...) распределяет обновления по независимым контроллерам, исключая локальные блокировки `kube-controller-manager`.
2. **Изоляция профилей автомасштабирования (HPA / KEDA):**
   * Общий HPA для монолитного сервиса вычисляет агрегированную метрику по всем репликам. Если 5% клиентов генерируют 90% нагрузки («тяжелые» аналитические запросы), средняя утилизация CPU по пулу подов может не превысить порог срабатывания.
   * Шардирование позволяет привязать независимый HPA/ScaledObject к каждому сегменту нагрузки со своими порогами срабатывания (`targetUtilization`, `stabilizationWindowSeconds`).
3. **Физическая изоляция доменов сбоя (Failure Domains):**
   * В On-Premise инфраструктуре шарды разносятся по изолированным физическим стойкам (rack), серверным комнатам, ЦОД и сетевым коммутаторам L2/L3 через `topologySpreadConstraints` и `nodeSelector`.
   * Выход из строя стоечного PDU, Top-of-Rack (ToR) коммутатора или гипервизора локализует сбой в границах одного шарда, не затрагивая остальные.
4. **Строгий Multi-Tenancy и защита квот:**
   * Размещение разных клиентов или классов обслуживания (например, `critical-tier` и `background-tier`) в выделенные шарды позволяет применять `PriorityClass`, `ResourceQuota` и `LimitRange` для гарантирования ресурсов критическим воркгрупам.

### Стратегии и ключи шардирования

| Стратегия | Ключ шардирования | Инфраструктурная реализация в K8s | Сильные стороны | Риски |
| :--- | :--- | :--- | :--- | :--- |
| **Топологическая** | ЦОД, серверная зона, стойка (`dc1`, `dc2`, `rack-01`) | `Deployment` per DC + Gateway API routing по заголовку / GeoIP | Минимальные межсетевые задержки, локализация аварий каналов связи | Требует поддержания идентичных мощностей в площадках |
| **Tenant / Entity** | `tenant_id`, `organization_id` | Отдельный Namespace/Deployment на группу арендаторов | Строгая изоляция безопасности, гибкие SLA | Неравномерность активности клиентов (Shard Skew) |
| **Хеширование** | `hash(user_id) % N` или Consistent Hash ring | L7-прокси (Envoy, Gateway API) с Maglev/Ketama хешированием | Равномерное распределение трафика по шардам | Сложность ребалансировки при добавлении шарда |
| **Функциональная** | Тип задачи (API, Sync, Export, Report) | Раздельные Deployment с разными классами нод (Compute/IO) | Оптимизация узлов под конкретный профиль нагрузки | Разная кодовая база или сложная логика роутинга |
| **Shuffled Sharding** | Хеш контекста запроса по $k$-подмножеству | Встроенный механизм K8s API Priority and Fairness (APF) | Радикальное снижение вероятности коллизии потоков | Требует детерминированного пула очередей/шардов |

### Архитектура хранения: Stateful-шарды и On-Premise Storage

Для приложений с сохранением состояния (СУБД, кэши, брокеры сообщений) в Kubernetes применяется архитектура **Shared-Nothing**: каждый шард владеет собственными независимыми томами и дисковыми пулами.

```
+---------------------------------------------------------------+
|                       StatefulSet Shard                       |
|  +------------------------+      +-------------------------+  |
|  |     Pod: shard-0-0     |      |     Pod: shard-0-1      |  |
|  | (Postgres Leader/Node) |      | (Postgres Replica/Node) |  |
|  +-----------┬------------+      +------------┬------------+  |
+--------------┼--------------------------------┼---------------+
               ▼                                ▼
       [ PVC: data-0-0 ]                [ PVC: data-0-1 ]
               │                                │
               ▼                                ▼
    [ Local PV / TopoLVM ]           [ Local PV / TopoLVM ]
   (Host 1: NVMe /dev/nvme0n1)      (Host 2: NVMe /dev/nvme0n1)
```

1. **Типы постоянного хранилища для шардов:**
   * **Локальные NVMe / TopoLVM (LVM-CSI):** Наивысшая производительность операций ввода-вывода (IOPS) и субмиллисекундная задержка. PV привязан к физическому серверу через `nodeAffinity`. Репликация обеспечивается на уровне приложения (Patroni, ClickHouse, Kafka).
   * **Ceph RBD (Rook-Ceph):** Блочное сетевое хранилище для bare-metal. Обеспечивает возможность перемещения пода шарда на другой узел при выходе сервера из строя без потери данных на томе.
2. **Политика сохранения PVC при операциях с StatefulSet:**
   * `persistentVolumeClaimRetentionPolicy: {whenDeleted: Retain, whenScaled: Retain}` — предотвращает безвозвратное удаление томов с данными при уменьшении количества реплик или пересоздании контроллера шарда.
3. **Headless Service:**
   * Headless Service (`clusterIP: None`) создает детерминированные SRV- и A-записи в CoreDNS (`<pod-name>.<service-name>.<namespace>.svc.cluster.local`), обеспечивая прямую сетевую адресацию реплик конкретного шарда без накладных расходов `kube-proxy` и DNAT.

### Сетевая топология и балансировка трафика

1. **L4 балансировка (MetalLB / Cilium BGP):**
   * Каждому шарду или группе шардов выделяется отдельный Virtual IP (VIP) из корпоративного пула адресов. Коммутаторы ToR маршрутизируют трафик напрямую на ноды через BGP Equal-Cost Multi-Path (ECMP).
2. **L7 балансировка (Gateway API):**
   * Спецификация `HTTPRoute` сопоставляет заголовки запросов (например, `x-tenant-id`, `x-datacenter-tier`), пути URL или cookie с конкретными бэкенд-сервисами шардов.
3. **Защита от сбоев планирования (Topology Spread & PDB):**
   * Использование `topologySpreadConstraints` гарантирует, что поды одного шарда распределяются по разным физическим серверам (`kubernetes.io/hostname`) и стойкам (`topology.kubernetes.io/zone`).
   * Персональный `PodDisruptionBudget` для каждого шарда предотвращает одновременный вывод из эксплуатации реплик одного шарда при выполнении регламентных работ администратором (`kubectl drain`).

---

## Практические сценарии

### Сценарий 1: Двухзонное шардирование Stateless-сервиса (DC1 / DC2) с Gateway API и Topology Spread

Реализация разделения нагрузки сервиса по двум датацентрам (`dc1` и `dc2`) внутри корпоративной сети с маршрутизацией через Gateway API на основе HTTP-заголовка `x-datacenter`.

#### Манифест шардов и сетевой топологии

```yaml
# shard-dc1.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app-shard-dc1
  namespace: production
  labels:
    app.kubernetes.io/name: web-app
    app.kubernetes.io/part-of: core-platform
    shard: dc1
spec:
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: web-app
      shard: dc1
  template:
    metadata:
      labels:
        app.kubernetes.io/name: web-app
        shard: dc1
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: web-app
              shard: dc1
          matchLabelKeys:
            - pod-template-hash
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: topology.kubernetes.io/zone
                    operator: In
                    values:
                      - dc1
      containers:
        - name: application
          image: nginx:1.27-alpine
          ports:
            - containerPort: 8080
              name: http
          env:
            - name: SHARD_ID
              value: "dc1"
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          readinessProbe:
            httpGet:
              path: /
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: web-app-service-dc1
  namespace: production
  labels:
    app.kubernetes.io/name: web-app
    shard: dc1
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: web-app
    shard: dc1
  ports:
    - name: http
      port: 80
      targetPort: 8080
---
# shard-dc2.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app-shard-dc2
  namespace: production
  labels:
    app.kubernetes.io/name: web-app
    app.kubernetes.io/part-of: core-platform
    shard: dc2
spec:
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: web-app
      shard: dc2
  template:
    metadata:
      labels:
        app.kubernetes.io/name: web-app
        shard: dc2
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: web-app
              shard: dc2
          matchLabelKeys:
            - pod-template-hash
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: topology.kubernetes.io/zone
                    operator: In
                    values:
                      - dc2
      containers:
        - name: application
          image: nginx:1.27-alpine
          ports:
            - containerPort: 8080
              name: http
          env:
            - name: SHARD_ID
              value: "dc2"
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          readinessProbe:
            httpGet:
              path: /
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: web-app-service-dc2
  namespace: production
  labels:
    app.kubernetes.io/name: web-app
    shard: dc2
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: web-app
    shard: dc2
  ports:
    - name: http
      port: 80
      targetPort: 8080
```

#### Манифест маршрутизации Gateway API (HTTPRoute)

```yaml
# shard-routing-httproute.yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: web-app-shard-route
  namespace: production
spec:
  parentRefs:
    - name: internal-gateway
      namespace: infra-gateways
  hostnames:
    - "app.corp.internal"
  rules:
    - matches:
        - headers:
            - name: x-datacenter
              value: "dc1"
      backendRefs:
        - name: web-app-service-dc1
          port: 80
          weight: 100
    - matches:
        - headers:
            - name: x-datacenter
              value: "dc2"
      backendRefs:
        - name: web-app-service-dc2
          port: 80
          weight: 100
    - backendRefs:
        - name: web-app-service-dc1
          port: 80
          weight: 50
        - name: web-app-service-dc2
          port: 80
          weight: 50
```

#### Проверка развертывания и валидация маршрутизации

```bash
# 1. Проверка распределения подов по узлам и шардам
kubectl get pods -n production -l app.kubernetes.io/name=web-app -L shard,topology.kubernetes.io/zone -o wide
# → NAME                                  READY   STATUS    RESTARTS   AGE   IP            NODE          SHARD   ZONE
# → web-app-shard-dc1-7d6f5845c9-2j4z1    1/1     Running   0          45s   10.244.1.42   node-dc1-01   dc1     dc1
# → web-app-shard-dc1-7d6f5845c9-9m2k8    1/1     Running   0          45s   10.244.2.18   node-dc1-02   dc1     dc1
# → web-app-shard-dc1-7d6f5845c9-w8pl0    1/1     Running   0          45s   10.244.3.77   node-dc1-03   dc1     dc1
# → web-app-shard-dc2-849db44849-5kx9a    1/1     Running   0          40s   10.244.4.15   node-dc2-01   dc2     dc2
# → web-app-shard-dc2-849db44849-8vh2m    1/1     Running   0          40s   10.244.5.91   node-dc2-02   dc2     dc2
# → web-app-shard-dc2-849db44849-q4ln2    1/1     Running   0          40s   10.244.6.33   node-dc2-03   dc2     dc2

# 2. Проверка эндпоинтов сервисов шардов
kubectl get endpoints -n production web-app-service-dc1 web-app-service-dc2
# → NAME                   ENDPOINTS                                         AGE
# → web-app-service-dc1    10.244.1.42:8080,10.244.2.18:8080,10.244.3.77:8080   2m
# → web-app-service-dc2    10.244.4.15:8080,10.244.5.91:8080,10.244.6.33:8080   2m

# 3. Тест селективной маршрутизации через Gateway IP
curl -s -I -H "Host: app.corp.internal" -H "x-datacenter: dc1" http://10.100.0.50/ | grep -i HTTP
# → HTTP/1.1 200 OK

curl -s -I -H "Host: app.corp.internal" -H "x-datacenter: dc2" http://10.100.0.50/ | grep -i HTTP
# → HTTP/1.1 200 OK
```

---

### Сценарий 2: Шардированный StatefulSet (СУБД) с Headless Service, Local NVMe и политикой PVC

Развертывание шарда базы данных с сохранением сетевой идентичности реплик, локальным хранилищем TopoLVM (NVMe) и защитой персистентных томов от случайного удаления при сжатии пула.

#### Манифест StatefulSet шарда

```yaml
# stateful-shard-0.yaml
apiVersion: v1
kind: Service
metadata:
  name: db-shard-0-headless
  namespace: databases
  labels:
    app.kubernetes.io/name: postgresql-shard
    shard: "0"
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: postgresql-shard
    shard: "0"
  ports:
    - name: postgresql
      port: 5432
      targetPort: 5432
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db-shard-0
  namespace: databases
  labels:
    app.kubernetes.io/name: postgresql-shard
    shard: "0"
spec:
  serviceName: "db-shard-0-headless"
  replicas: 3
  podManagementPolicy: OrderedReady
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain
    whenScaled: Retain
  selector:
    matchLabels:
      app.kubernetes.io/name: postgresql-shard
      shard: "0"
  template:
    metadata:
      labels:
        app.kubernetes.io/name: postgresql-shard
        shard: "0"
    spec:
      terminationGracePeriodSeconds: 60
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: postgresql-shard
              shard: "0"
      containers:
        - name: postgresql
          image: postgres:16-alpine
          ports:
            - containerPort: 5432
              name: postgresql
          env:
            - name: POSTGRES_DB
              value: "shard_0_db"
            - name: POSTGRES_USER
              value: "postgres"
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: db-shard-0-credentials
                  key: password
            - name: PGDATA
              value: "/var/lib/postgresql/data/pgdata"
          resources:
            requests:
              cpu: "1000m"
              memory: "2Gi"
            limits:
              cpu: "2000m"
              memory: "4Gi"
          volumeMounts:
            - name: pgdata
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: pgdata
      spec:
        accessModes: [ "ReadWriteOnce" ]
        storageClassName: "topolvm-provisioner-nvme"
        resources:
          requests:
            storage: 150Gi
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: db-shard-0-pdb
  namespace: databases
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: postgresql-shard
      shard: "0"
```

#### Проверка DNS-имен, PDB и персистентных томов

```bash
# 1. Проверка состояния подов и PVC шарда
kubectl get statefulset,pods,pvc -n databases -l shard="0"
# → NAME                          READY   AGE
# → statefulset.apps/db-shard-0   3/3     3m
# →
# → NAME                 READY   STATUS    RESTARTS   AGE     IP            NODE
# → pod/db-shard-0-0     1/1     Running   0          3m      10.244.1.80   node-01
# → pod/db-shard-0-1     1/1     Running   0          2m15s   10.244.2.95   node-02
# → pod/db-shard-0-2     1/1     Running   0          1m30s   10.244.3.40   node-03
# →
# → NAME                               STATUS   VOLUME             CAPACITY   ACCESS MODES   STORAGECLASS               AGE
# → persistentvolumeclaim/pgdata-db-shard-0-0   Bound    pvc-11223344-01    150Gi      RWO            topolvm-provisioner-nvme   3m
# → persistentvolumeclaim/pgdata-db-shard-0-1   Bound    pvc-11223344-02    150Gi      RWO            topolvm-provisioner-nvme   2m15s
# → persistentvolumeclaim/pgdata-db-shard-0-2   Bound    pvc-11223344-03    150Gi      RWO            topolvm-provisioner-nvme   1m30s

# 2. Проверка разрешения DNS через Headless Service внутри кластера
kubectl exec -n databases db-shard-0-0 -- nslookup db-shard-0-headless.databases.svc.cluster.local
# → Server:         10.96.0.10
# → Address:        10.96.0.10#53
# →
# → Name:   db-shard-0-headless.databases.svc.cluster.local
# → Address: 10.244.1.80
# → Address: 10.244.2.95
# → Address: 10.244.3.40

# 3. Проверка PDB для шарда 0
kubectl get pdb -n databases db-shard-0-pdb
# → NAME             MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → db-shard-0-pdb   2               N/A               1                     3m30s
```

---

### Сценарий 3: Автомасштабирование воркеров по очередям шардов (KEDA + On-Premise RabbitMQ)

Функциональное разделение очередей RabbitMQ на шарды по приоритету клиентов: шард `tier-critical` обрабатывает транзакции с жестким SLA, а шард `tier-bulk` обрабатывает фоновую пакетную генерацию документов.

#### Манифест воркеров и KEDA ScaledObject

```yaml
# workers-sharding-keda.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: queue-worker-shard-critical
  namespace: processing
  labels:
    app.kubernetes.io/name: queue-worker
    shard: critical
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: queue-worker
      shard: critical
  template:
    metadata:
      labels:
        app.kubernetes.io/name: queue-worker
        shard: critical
    spec:
      priorityClassName: high-priority-workloads
      containers:
        - name: worker
          image: custom-worker:2.4.1
          env:
            - name: QUEUE_TARGET
              value: "orders.critical"
            - name: RABBITMQ_HOST
              value: "rabbitmq.infra.svc.cluster.local"
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: keda-scaler-shard-critical
  namespace: processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: queue-worker-shard-critical
  pollingInterval: 10
  cooldownPeriod: 60
  minReplicaCount: 2
  maxReplicaCount: 20
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleUp:
          stabilizationWindowSeconds: 0
          policies:
            - type: Percent
              value: 100
              periodSeconds: 15
        scaleDown:
          stabilizationWindowSeconds: 180
          policies:
            - type: Percent
              value: 10
              periodSeconds: 60
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: orders.critical
        mode: QueueLength
        value: "20"
      authenticationRef:
        name: rabbitmq-auth-secret
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: queue-worker-shard-bulk
  namespace: processing
  labels:
    app.kubernetes.io/name: queue-worker
    shard: bulk
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: queue-worker
      shard: bulk
  template:
    metadata:
      labels:
        app.kubernetes.io/name: queue-worker
        shard: bulk
    spec:
      priorityClassName: low-priority-workloads
      containers:
        - name: worker
          image: custom-worker:2.4.1
          env:
            - name: QUEUE_TARGET
              value: "orders.bulk"
            - name: RABBITMQ_HOST
              value: "rabbitmq.infra.svc.cluster.local"
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: keda-scaler-shard-bulk
  namespace: processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: queue-worker-shard-bulk
  pollingInterval: 30
  cooldownPeriod: 300
  minReplicaCount: 1
  maxReplicaCount: 10
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: orders.bulk
        mode: QueueLength
        value: "100"
      authenticationRef:
        name: rabbitmq-auth-secret
```

#### Проверка автомасштабирования шардов

```bash
# 1. Проверка статуса ScaledObject и сгенерированных HPA
kubectl get scaledobject,hpa -n processing
# → NAME                                                  SCALETARGETKIND      SCALETARGETNAME               MIN   MAX   TRIGGERS   AUTHENTICATION         READY   ACTIVE   AGE
# → scaledobject.keda.sh/keda-scaler-shard-bulk           apps/v1.Deployment   queue-worker-shard-bulk       1     10    rabbitmq   rabbitmq-auth-secret   True    False    2m
# → scaledobject.keda.sh/keda-scaler-shard-critical       apps/v1.Deployment   queue-worker-shard-critical   2     20    rabbitmq   rabbitmq-auth-secret   True    True     2m
# →
# → NAME                                                    REFERENCE                                TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
# → horizontalpodautoscaler.autoscaling/keda-hpa-keda-scaler-shard-bulk       Deployment/queue-worker-shard-bulk       0/100 (avg)     1         10        1          2m
# → horizontalpodautoscaler.autoscaling/keda-hpa-keda-scaler-shard-critical   Deployment/queue-worker-shard-critical   45/20 (avg)     2         20        5          2m

# 2. Мониторинг реакции шардов на всплеск критической очереди
kubectl describe hpa keda-hpa-keda-scaler-shard-critical -n processing | grep -A 5 "Conditions:"
# → Conditions:
# →   Type            Status  Reason                       Message
# →   ----            ------  ------                       -------
# →   AbleToScale     True    SucceededRescale             new size: 5; reason: external metric s0-rabbitmq-orders-critical(&LabelSelector{MatchLabels:map[string]string{scaledobject.keda.sh/name: keda-scaler-shard-critical,},}) above target
# →   ScalingActive   True    ValidMetricFound             the HPA was able to successfully calculate a replica count from external metric
```

---

### Сценарий 4: Защита Kubernetes API Server через Shuffled Sharding (API Priority and Fairness)

Настройка `FlowSchema` и `PriorityLevelConfiguration` для защиты Control Plane кластера от исчерпания потоков при активности агрессивных внутренних шардов или CI/CD контроллеров.

#### Манифест конфигурации APF

```yaml
# apf-shuffled-sharding.yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: tenant-workloads-sharded
spec:
  type: Queue
  limited:
    nominalConcurrencyShares: 50
    lendablePercent: 20
    limitResponse:
      type: Queue
      queuing:
        queues: 64
        handSize: 4
        queueLengthLimit: 50
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: tenant-shard-schema
spec:
  priorityLevelConfiguration:
    name: tenant-workloads-sharded
  matchingPrecedence: 500
  distinguisherMethod:
    type: ByUser
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            name: "*"
            namespace: "production"
      resourceRules:
        - verbs: ["get", "list", "watch"]
          apiGroups: ["*"]
          resources: ["*"]
```

#### Проверка распределения очередей в API Server

```bash
# 1. Проверка состояния PriorityLevelConfiguration
kubectl get prioritylevelconfiguration tenant-workloads-sharded -o yaml | grep -A 8 "queuing:"
# →         queuing:
# →           handSize: 4
# →           queueLengthLimit: 50
# →           queues: 64

# 2. Проверка метрик отброшенных или ожидающих запросов в APF
kubectl get --raw /metrics | grep apiserver_flowcontrol_current_inqueue_requests | grep tenant-workloads-sharded
# → apiserver_flowcontrol_current_inqueue_requests{priority_level="tenant-workloads-sharded"} 0

kubectl get --raw /metrics | grep apiserver_flowcontrol_rejected_requests_total | grep tenant-workloads-sharded
# → apiserver_flowcontrol_rejected_requests_total{priority_level="tenant-workloads-sharded",reason="queue-full"} 0
```

---

### Сценарий 5: Строгая сетевая изоляция шардов через NetworkPolicy

Ограничение сетевого взаимодействия: поды каждого шарда приложений могут обращаться только к своему шарду базы данных. Прямой межшардный трафик блокируется на уровне ядра Linux (CNI eBPF/iptables).

#### Манифест NetworkPolicy для шарда

```yaml
# shard-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: isolate-shard-0
  namespace: production
spec:
  podSelector:
    matchLabels:
      shard: "0"
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешаем входящий трафик только от L7 Gateway шлюза
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: infra-gateways
          podSelector:
            matchLabels:
              app.kubernetes.io/name: gateway-envoy
      ports:
        - protocol: TCP
          port: 8080
  egress:
    # Разрешаем исходящий трафик только к БД шарда 0
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: databases
          podSelector:
            matchLabels:
              app.kubernetes.io/name: postgresql-shard
              shard: "0"
      ports:
        - protocol: TCP
          port: 5432
    # Разрешаем системный DNS внутри кластера
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
```

#### Проверка сетевой изоляции

```bash
# 1. Проверка доступности БД своего шарда (должна возвращать успешное соединение)
kubectl exec -n production deploy/web-app-shard-0 -- nc -zvw 2 db-shard-0-headless.databases.svc.cluster.local 5432
# → db-shard-0-headless.databases.svc.cluster.local (10.244.1.80:5432) open

# 2. Проверка блокировки доступа к БД соседнего шарда (должен быть таймаут)
kubectl exec -n production deploy/web-app-shard-0 -- nc -zvw 2 db-shard-1-headless.databases.svc.cluster.local 5432
# → nc: connect to db-shard-1-headless.databases.svc.cluster.local (10.244.4.15) port 5432 (tcp) timed out
# → command terminated with exit code 1
```

---

## Операции и команды

Сводка инженерных команд для аудита, эксплуатации и диагностики шардированных кластеров.

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Инспекция распределения подов по шардам** | `kubectl get pods -A -L shard,topology.kubernetes.io/zone -o wide` | Проверка привязки подов к зонам и шардам |
| **Аудит перекоса подов (Pod Skew)** | `kubectl get pods -A -L shard --no-headers \| awk '{print $NF}' \| sort \| uniq -c \| sort -rn` | Определение количества подов в каждом шарде |
| **Проверка Topology Spread** | `kubectl describe deploy <deploy-name> \| grep -A 12 "Topology Spread"` | Валидация правил раскидывания реплик шарда |
| **Статус персистентных томов шардов** | `kubectl get pvc -A -l "shard in (0, 1, 2)" -o wide` | Проверка статуса томов и StorageClass |
| **Безопасный drain узла** | `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` | Вывод узла с соблюдением PDB каждого шарда |
| **Рестарт конкретного шарда** | `kubectl rollout restart deployment/<shard-deploy> -n <ns>` | Поэтапный перезапуск подов без простоя других шардов |
| **Проверка PDB нарушений** | `kubectl get pdb -A` | Аудит оставшихся разрешенных сбоев (`ALLOWED DISRUPTIONS`) |

### Практические команды с ожидаемым выводом

```bash
# 1. Аудит распределения подов по шардам в пространстве production
kubectl get pods -n production -L shard,app.kubernetes.io/name --no-headers | awk '{print $NF, $6}' | sort | uniq -c
# →       6 web-app dc1
# →       6 web-app dc2
# →       3 queue-worker bulk
# →       8 queue-worker critical

# 2. Проверка состояния PDB всех шардов
kubectl get pdb -n production
# → NAME                 MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → web-app-dc1-pdb      2               N/A               1                     4d
# → web-app-dc2-pdb      2               N/A               1                     4d
# → workers-crit-pdb     75%             N/A               2                     4d

# 3. Инспекция использования ресурсов подами конкретного шарда
kubectl top pods -n production -l shard=dc1
# → NAME                                  CPU(cores)   MEMORY(bytes)
# → web-app-shard-dc1-7d6f5845c9-2j4z1    45m          128Mi
# → web-app-shard-dc1-7d6f5845c9-9m2k8    52m          132Mi
# → web-app-shard-dc1-7d6f5845c9-w8pl0    48m          126Mi
```

---

## Мониторинг и SLO/SLA

Ключевые метрики для выявления перекоса шардов, деградации производительности и исчерпания ресурсов.

### Таблица ключевых метрик

| Метрика | Назначение | Источник | Пороговое значение |
| :--- | :--- | :--- | :--- |
| `http_requests_total{shard=~".+"}` | Оценка распределения входящего трафика по шардам | Ingress / Gateway API / Envoy | Отклонение > 30% от медианы = алерт |
| `http_request_duration_seconds` | 95-й и 99-й перцентили задержки обработки в шарде | Ingress-NGINX / Envoy / App | p99 > 200ms на конкретном шарде |
| `kube_hpa_status_current_replicas` | Отслеживание динамики расширения реплик шардов | Kube-State-Metrics | Приближение к `maxReplicas` (> 85%) |
| `kubelet_volume_stats_used_bytes` | Заполнение дискового пространства томов StatefulSet | Kubelet cAdvisor | Заполнение тома шарда > 80% |
| `apiserver_flowcontrol_current_inqueue_requests` | Очередь запросов в API Priority and Fairness | Kube-APIServer | Рост очереди > 30 запросов в очереди |

### PromQL-запросы для детекции перекоса (Shard Skew)

```promql
# 1. Расчет коэффициента вариации (дисбаланса RPS) между шардами
(
  stddev(sum by (shard) (rate(http_requests_total{job="web-app-gateway"}[5m])))
  /
  avg(sum by (shard) (rate(http_requests_total{job="web-app-gateway"}[5m])))
) > 0.4

# 2. Выявление «горячего» шарда (RPS превышает медианное значение более чем в 2 раза)
sum by (shard) (rate(http_requests_total{job="web-app-gateway"}[5m]))
  > 2 * scalar(median(sum by (shard) (rate(http_requests_total{job="web-app-gateway"}[5m]))))

# 3. Утилизация персистентных томов по шардам баз данных
(
  kubelet_volume_stats_used_bytes{persistentvolumeclaim=~"pgdata-db-shard-.*"}
  /
  kubelet_volume_stats_capacity_bytes{persistentvolumeclaim=~"pgdata-db-shard-.*"}
) * 100 > 85
```

### Манифест PrometheusRule для алертинга

```yaml
# sharding-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: sharding-workload-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
    - name: ShardingHealthAlerts
      rules:
        - alert: ShardTrafficSkewCritical
          expr: |
            (
              stddev(sum by (shard) (rate(http_requests_total{job="web-app-gateway"}[5m])))
              /
              avg(sum by (shard) (rate(http_requests_total{job="web-app-gateway"}[5m])))
            ) > 0.5
          for: 15m
          labels:
            severity: warning
            team: sre
          annotations:
            summary: "Высокий дисбаланс трафика между шардами"
            description: "Коэффициент вариации трафика между шардами составляет {{ $value | printf \"%.2f\" }}. Возможен перекос ключа шардирования (Hot Shard)."

        - alert: ShardReplicaLimitReached
          expr: |
            kube_hpa_status_current_replicas{hpa=~".*shard.*"}
            >=
            kube_hpa_spec_max_replicas{hpa=~".*shard.*"}
          for: 10m
          labels:
            severity: warning
            team: sre
          annotations:
            summary: "Шард достиг максимального лимита масштабирования HPA"
            description: "HPA {{ $labels.hpa }} в namespace {{ $labels.namespace }} находится на потолке maxReplicas. Требуется выделение дополнительных шардов."

        - alert: ShardVolumeStorageCritical
          expr: |
            (
              kubelet_volume_stats_used_bytes{persistentvolumeclaim=~".*shard.*"}
              /
              kubelet_volume_stats_capacity_bytes{persistentvolumeclaim=~".*shard.*"}
            ) > 0.85
          for: 10m
          labels:
            severity: critical
            team: dba
          annotations:
            summary: "Персистентный том шарда заполнен более чем на 85%"
            description: "PVC {{ $labels.persistentvolumeclaim }} в namespace {{ $labels.namespace }} заполнена на {{ $value | humanizePercentage }}. Необходим решардинг или расширение диска."
```

---

## Диагностика и устранение неполадок

| Проблема / Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Hot Shard: Аномальная задержка и CPU на одном шарде** | Неудачный ключ шардирования (высокая активность одного крупного tenant'а) | `kubectl top pods -l shard=<id>`, анализ RPS по эндпоинтам | Внедрить вторичный уровень шардирования, перенести горячего клиента на выделенный шард |
| **Поды шарда зависают в `Pending`** | Нарушение `TopologySpreadConstraints` или исчерпание квот | `kubectl describe pod <pod-name>`, просмотр события `FailedScheduling` | Ослабить `whenUnsatisfiable: ScheduleAnyway` или добавить узлы в дефицитную зону/стойку |
| **Зависание команды `kubectl drain` узла** | Нарушение PDB конкретного шарда (`ALLOWED DISRUPTIONS: 0`) | `kubectl get pdb -A`, проверка статуса готовности подов шарда | Проверить состояние нездоровых подов шарда; при регламенте временно увеличить реплики шарда |
| **Трафик направляется не в тот шард** | Ошибка селекторов сервиса или некорректные HTTPRoute правила | `kubectl get endpoints <svc>`, `kubectl describe httproute` | Проверить соответствие лейблов подов правилам Gateway API / Ingress |
| **Потеря данных при скейле StatefulSet вниз** | Дефолтная политика удаления PVC при пересоздании | Проверка `persistentVolumeClaimRetentionPolicy` | Установить `whenDeleted: Retain` и `whenScaled: Retain` в спецификации StatefulSet |
| **Коллизия клиентов в Control Plane (APF 429)** | Все запросы попадают в одну очередь APF | `kubectl get --raw /metrics \| grep apiserver_flowcontrol` | Увеличить `queues` и `handSize` в `PriorityLevelConfiguration` |

### Разбор инцидентов

#### 1. Deadlock при Rolling Update из-за сочетания TopologySpreadConstraints и PDB

* **Симптомы:** При накатке нового релиза подов шарда `kubectl rollout status deployment/web-app-shard-dc1` останавливается. Новые поды находятся в `Pending`, старые не удаляются.
* **Причина:** Старые поды занимают все допустимые топологические домены (`kubernetes.io/hostname`). Планировщик не может разместить новый под из-за жесткого правила `maxSkew: 1` (`whenUnsatisfiable: DoNotSchedule`), а PDB запрещает остановить старый под до готовности нового.
* **Решение:**
  1. В `topologySpreadConstraints` добавить `matchLabelKeys: [pod-template-hash]` (стандартное поведение с Kubernetes 1.31+), чтобы планировщик вычислял разницу только между подами одной ревизии.
  2. Если версия кластера ниже 1.31, настроить стратегию развертывания:
     ```yaml
     strategy:
       rollingUpdate:
         maxSurge: 1
         maxUnavailable: 0
     ```
     и задать `whenUnsatisfiable: ScheduleAnyway` на время миграции.

#### 2. Зависание локального тома при сбое физического узла

* **Симптомы:** Физический сервер вышел из строя. Под `db-shard-0-1` перешел в состояние `Terminating` или `NodeLost`. Новый под не может запуститься на другом узле с ошибкой `VolumeBindingFailed`.
* **Причина:** Использовался локальный PV (Local NVMe), привязанный к аппаратному контроллеру конкретного упавшего хоста через `nodeAffinity`.
* **Решение:**
  1. При использовании Shared-Nothing СУБД (например, Patroni/Postgres) инициировать перевыборы лидера внутри шарда: оставшиеся реплики подхватывают трафик.
  2. Вывести сломанный узел из кластера:
     ```bash
     kubectl delete node <failed-node>
     ```
  3. Удалить зависший под и его PVC с упавшего узла, создав новый PVC на исправном сервере. СУБД выполнит потоковую репликацию данных с лидера на новый узел.

---

## Лучшие практики

1. **Изолируйте конфигурации и секреты по шардам:**
   Каждый шард должен монтировать собственный экземпляр `ConfigMap` и `Secret`. Изменение параметров подключения или ротация ключей в одном шарде не должны вызывать перезапуск подов в других сегментах.
2. **Определяйте PDB на уровне каждого шарда:**
   Никогда не создавайте один общий PDB с селектором по всему приложению. При общем PDB `maxUnavailable: 10%` процедура `drain` может одновременно выселить 100% подов одного небольшого шарда, вызвав полный отказ сервиса.
3. **Используйте `matchLabelKeys: [pod-template-hash]`:**
   Всегда добавляйте поле `matchLabelKeys: [pod-template-hash]` в спецификацию `topologySpreadConstraints` подов шарда, чтобы избежать блокировок планирования при rolling-update.
4. **Фиксируйте политику удержания PVC (`persistentVolumeClaimRetentionPolicy`):**
   Для всех StatefulSet-шардов устанавливайте значения `whenDeleted: Retain` и `whenScaled: Retain`. Это защищает от потери данных при ошибочном сжатии реплик или пересоздании контроллера.
5. **Применяйте Shuffled Sharding для высоконагруженных очередей:**
   Если один клиент или воркер начинает генерировать аномальный объем запросов, применение перемешанного шардирования снижает вероятность того, что добросовестный клиент окажется в одной очереди с нарушителем до долей процента.
6. **Настраивайте Graceful Termination:**
   Задавайте достаточный `terminationGracePeriodSeconds` (45–90 секунд) и используйте хуки `preStop` для завершения активных транзакций и корректного отключения от брокера сообщений или шлюза.
7. **Контролируйте Shard Skew на постоянной основе:**
   Внедряйте алерты на коэффициент вариации трафика между шардами. Систематический перекос нагрузки сигнализирует о необходимости смены ключа шардирования или проведения планового решардинга.
8. **Комбинируйте NetworkPolicy с Default-Deny:**
   Изолируйте пространства имен шардов с помощью запрещающих правил по умолчанию. Доступ должен открываться только явно: от Ingress/Gateway к подам приложения и от подов приложения к выделенной БД шарда.
9. **Тестируйте радиус поражения (Chaos Engineering):**
   Регулярно проводите плановые учения по отключению одного полного шарда. Проверяйте, что соседние шарды продолжают функционировать без деградации времени отклика (Latency) и пропускной способности.
10. **Стандартизируйте маркировку (Labels):**
    Применяйте стандартные лейблы `app.kubernetes.io/name`, `app.kubernetes.io/part-of` и строго фиксируйте лейбл `shard: "<id>"`. Это упрощает автоматизацию мониторинга, построение дашбордов и управление сетевыми политиками.

---

## Дополнительная информация

### Внутренние материалы базы знаний

* **[Масштабирование StatefulSet: HPA, KEDA и паттерны](./statefulset_autoscaling.md)** — особенности управления репликами и томами приложений с состоянием.
* **[Бюджет прерывания подов (Pod Disruption Budget, PDB)](./pod_disruption_budget.md)** — детальный разбор Eviction API и обеспечения доступности сервисов.
* **[Автомасштабирование в On-Premise инфраструктуре](./on_premise_autoscaling.md)** — специфика автомасштабирования в частных датацентрах и на bare-metal.
* **[Шаблон воркеров с очередями](./workers_queue_pattern.md)** — реализация параллельной обработки очередей задач.
* **[Управление размещением подов: Affinity, Anti-Affinity и TopologySpreadConstraints](../Scheduling/affinity.md)** — правила топологического планирования подов.
* **[API Priority and Fairness (APF)](../Concepts/api_priority_and_fairness.md)** — архитектура защиты Control Plane и перемешанного шардирования (Shuffled Sharding).
* **[Шардирование баз данных (Общая теория)](../../Databases/Concepts/sharding.md)** — математика и алгоритмы разбиения данных.
* **[Сетевые политики (Network Policies)](../Networking/Network/network_policy.md)** — реализация сетевой изоляции микросервисов.
* **[Gateway API: маршрутизация и балансировка](../Networking/gateway_api/routing_features.md)** — спецификация L7 маршрутизации трафика в Kubernetes.

### Внешние источники и документация

* [Kubernetes Documentation: Pod Topology Spread Constraints](https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/) — официальная документация по топологическому распределению.
* [Kubernetes Documentation: API Priority and Fairness](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/) — спецификация механизмов APF и Shuffled Sharding.
* [Gateway API Specification](https://gateway-api.sigs.k8s.io/) — официальный стандарт сетевой маршрутизации и L7-шлюзов.
* [KEDA (Kubernetes Event-driven Autoscaling) Documentation](https://keda.sh/docs/) — автомасштабирование по внешним метрикам брокеров сообщений.
