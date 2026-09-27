# Cluster Autoscaler (CA)

## Определения

**Cluster Autoscaler (CA)** — это системный контроллер Kubernetes, предназначенный для автоматического изменения размера вычислительного кластера (количества рабочих узлов). Решение о масштабировании принимается исключительно на основе анализа потребностей подов в ресурсах (`requests`) и их текущего распределения, а не на основе реальной загрузки CPU/RAM.

**Node Group (ASG / MIG / VMSS)** — логическое объединение идентичных виртуальных или физических машин (одинаковый тип, диск, метки), управляемое облачным провайдером. CA работает именно с абстракцией групп узлов, а не с отдельными инстансами.

**ProvisioningRequest** — механизм (CRD, Beta в 1.30+), позволяющий запрашивать у CA создание пула узлов определенной емкости до фактического создания подов, что критически важно для пакетных (batch) задач и машинного обучения.

**Dynamic Resource Allocation (DRA)** — фреймворк Kubernetes для запроса специфического оборудования (GPU, TPU, FPGA). CA версии 1.30+ умеет симулировать выделение DRA-ресурсов до создания узла.

**Expander** — стратегия выбора группы узлов при масштабировании вверх, когда `Pending` под может быть размещен в нескольких Node Groups.

**Scale-Down Cooldown** — период после масштабирования вверх, в течение которого CA не удаляет узлы (по умолчанию 10 минут). Предотвращает «флаппинг» — цикличное добавление и удаление узлов.

---

## Предварительные требования

### Версии и компоненты

Матрица совместимости строго привязана к минорной версии Kubernetes (начиная с Kubernetes 1.12 CA версионируется в соответствии с K8s). Использование CA неподдерживаемой версии чревато расхождениями в API (например, `Lease` объект, фичи `kube-scheduler`).

| Версия Kubernetes | Версия CA | Версия Helm-чарта |
| :--- | :--- | :--- |
| 1.34.x | 1.34.x | 9.51.0+ |
| 1.33.x | 1.33.x | 9.47.0+ |
| 1.32.x | 1.32.x | 9.45.0+ |
| 1.31.x | 1.31.x | 9.38.0+ |
| 1.30.x | 1.30.x | 9.37.0+ |
| 1.29.x | 1.29.x | 9.35.0+ |
| 1.28.x | 1.28.x | 9.34.0+ |
| 1.27.x | 1.27.x | 9.29.0+ |

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
| :--- | :--- | :--- | :--- |
| Kubernetes | 1.27 | 1.32+ | Поддерживаемые ветки: `n`, `n-1`, `n-2`, `n-3` |
| Cluster Autoscaler | 1.27+ | 1.33+ | Поддержка DRA (structured parameters) с 1.32; ProvisioningRequest — Beta с 1.30 |
| Metrics Server | 0.6.0+ | 0.7.0+ | Не обязателен для CA, но необходим для HPA |
| Cluster API (on-prem) | v1.5+ | v1.7+ | Для bare-metal через Metal3 / Cluster API Provider |

> **Замечание о политике поддержки:** CA выполняет обратный бэкпорт (backport) баг-фиксов и фич облачных провайдеров только в три последние поддерживаемые ветки (N, N-1, N-2). Бэкпорт в более старые ветки возможен только по отдельному issue в upstream.

### Feature Gates

| Feature Gate | Версия | Статус | Описание |
| :--- | :--- | :--- | :--- |
| `InPlacePodVerticalScaling` | 1.27 | Beta (1.33+) | Влияет на расчет `requests` при симуляции |
| `DynamicResourceAllocation` | 1.27 | Beta (1.34+) | Симуляция DRA-ресурсов при scale-up |
| `NodeSwap` | 1.30 | Alpha | Учитывает swap при расчете емкости узла |
| `DRAAdminAccess` | 1.32 | Alpha | Доступ администратора кластера к `ResourceClaims` |
| `DRAPartitionableDevices` | 1.33 | Alpha | Разделение аппаратного устройства между несколькими подами |

> **Важно (Kubernetes 1.32):** старая (alpha) реализация DRA, появившаяся в 1.26, **удалена** в 1.32. Остался только новый «Structured Parameters» подход (KEP-4381). Это изменение было сделано из-за несовместимости старого API с autoscaling (прозрачность доступности ресурсов была недостаточной для принятия решений планировщиком и контроллерами).

### Требования к окружению

**Проверка перед развертыванием:**

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Server Version: v1.30.x

# Проверка наличия Node Groups (облачные провайдеры)
kubectl get nodes -L topology.kubernetes.io/zone
# → Узлы должны иметь метки групп (например, karpenter.sh/provisioner-name)

# Проверка RBAC прав для CA
kubectl auth can-i create deployments --namespace=kube-system
# → yes

# Проверка доступа к Cloud API (для on-prem — к Cluster API)
kubectl get endpointslices.discovery.k8s.io
# → Должен вернуть список или пустой результат без ошибок
```

### Интеграция с ResourceQuota

CA не учитывает ResourceQuota при принятии решений о масштабировании. Если квота исчерпана:
- Поды остаются в `Pending`
- CA добавляет узлы, но поды не могут быть запланированы
- Необходим мониторинг `resourcequota` и настройка [VPA в режиме Off](./vpa_detailed.md) для корректных `requests`

### Минимальные RBAC-права для CA

CA работает с большим набором API-объектов. Недостаточные права приводят к ошибкам типа `forbidden: User "system:serviceaccount:kube-system:cluster-autoscaler" cannot create/get resource ...`. Полный манифест ролей (используется и Helm-чартом, и Kustomize-установкой):

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    k8s-addon: cluster-autoscaler.addons.k8s.io
    k8s-app: cluster-autoscaler
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cluster-autoscaler
rules:
  - apiGroups: [""]
    resources: ["events", "endpoints"]
    verbs: ["create", "patch"]
  - apiGroups: [""]
    resources: ["pods/eviction"]
    verbs: ["create"]
  - apiGroups: [""]
    resources: ["pods/status"]
    verbs: ["update"]
  - apiGroups: [""]
    resources: ["endpointslices"]
    verbs: ["get", "list"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["create", "get", "update"]
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["list", "watch", "get", "patch", "update"]
  - apiGroups: [""]
    resources: ["pods", "services", "replicationcontrollers", "persistentvolumeclaims", "persistentvolumes"]
    verbs: ["get", "list", "watch", "update"]
  - apiGroups: ["apps", "extensions"]
    resources: ["daemonsets", "replicasets", "statefulsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses", "csinodes", "csidrivers", "csistoragecapacities"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch", "extensions"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["create"]
  - apiGroups: ["resource.k8s.io"]
    resources: ["resourceclaims", "resourceclaimtemplates", "resourceclaims/status"]
    verbs: ["get", "list", "watch", "update", "patch"]
  - apiGroups: ["autoscaling.x-k8s.io"]
    resources: ["provisioningrequests", "provisioningrequests/status"]
    verbs: ["get", "list", "watch", "update", "patch"]
  - apiGroups: ["cluster.x-k8s.io"]
    resources: ["machinedeployments", "machinesets", "machines", "machinepools"]
    verbs: ["get", "list", "watch", "create", "update", "delete"]
  - apiGroups: ["cluster.x-k8s.io"]
    resources: ["machines/status", "machinesets/status", "machinedeployments/status"]
    verbs: ["get", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cluster-autoscaler
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-autoscaler
subjects:
  - kind: ServiceAccount
    name: cluster-autoscaler
    namespace: kube-system
```

> **Примечание:** для провайдеров на базе Cluster API (CAPI) CA требует прав на объекты `machines`, `machinesets`, `machinedeployments`. Для on-prem через Cluster API (vSphere, Metal3) эти разрешения обязательны. Для облачных провайдеров CA фактически не использует CAPI-объекты, но безопаснее оставить разрешения, чтобы избежать ошибок при миграции.

---

## Основные концепции

### Двухуровневая архитектура масштабирования

В современной парадигме Kubernetes масштабирование разделено:
1.  **Control Plane (API, etcd, Scheduler):** Управляется и масштабируется облачным провайдером (в Managed-решениях) или администратором платформы.
2.  **Data Plane (Worker Nodes):** Масштабируется автоматически компонентами вроде **Cluster Autoscaler** или **[Karpenter](./Karpenter/overview.md)**.

### Механизм масштабирования вверх (Scale-Up)

Триггером для CA является **только** наличие подов в состоянии `Pending` с причиной `Unschedulable` (невозможность планирования из-за нехватки ресурсов или несовпадения `nodeSelector`/`affinity`).

1.  **Сканирование:** CA опрашивает API-сервер (по умолчанию каждые 10 секунд).
2.  **Симуляция:** CA прогоняет логику `kube-scheduler` (включая DRA и топологию), чтобы понять, поможет ли добавление узла конкретного типа разместить `Pending` поды.
3.  **Запрос к Cloud API:** Если симуляция успешна, CA увеличивает `DesiredCapacity` в целевой Node Group.
4.  **Ожидание:** Узел запускается, проходит процесс `bootstrap` (cloud-init), регистрируется в кластере и переходит в статус `Ready`. Весь процесс занимает **от 3 до 10 минут**.

### Механизм масштабирования вниз (Scale-Down)

CA анализирует узлы на предмет простоя. Узел считается кандидатом на удаление, если:
1.  Утилизация узла (сумма `requests` всех подов / емкость узла) ниже порога `--scale-down-utilization-threshold` (по умолчанию 50%).
2.  **Все** поды на узле (кроме DaemonSet) могут быть безопасно перемещены (Evicted) на другие узлы.
3.  Узел находится в таком состоянии дольше `--scale-down-unneeded-time` (по умолчанию 10 минут).

**Что блокирует выселение (и удаление узла):**
-   Наличие подов с аннотацией `"cluster-autoscaler.kubernetes.io/safe-to-evict": "false"`.
-   Наличие подов, использующих `emptyDir` или `hostPath` (если не задан флаг `--skip-nodes-with-local-storage=false`).
-   Блокировка со стороны [Pod Disruption Budget (PDB)](./pod_disruption_budget.md).
-   Системные поды `kube-system`, у которых нет PDB.
-   Узлы с аннотацией `cluster-autoscaler.kubernetes.io/scale-down-disabled: "true"`.
-   Поды, которые не могут быть перемещены из-за нарушения `PodAntiAffinity` или `TopologySpreadConstraints` на других узлах.

### Важные флаги запуска CA

| Флаг | По умолчанию | Описание |
| :--- | :--- | :--- |
| `--scan-interval` | 10s | Частота опроса API-сервера на наличие `Pending` подов |
| `--scale-down-utilization-threshold` | 0.5 | Порог утилизации узла, ниже которого он считается кандидатом на удаление |
| `--scale-down-gpu-utilization-threshold` | 0.5 | Отдельный порог утилизации GPU (если на узле есть GPU-ресурсы) |
| `--scale-down-unneeded-time` | 10m | Время, в течение которого узел должен быть не нужен, прежде чем будет удален |
| `--scale-down-delay-after-add` | 10m | Задержка перед началом scale-down после scale-up (предотвращает флаппинг) |
| `--scale-down-delay-after-delete` | 0s | Задержка после удаления узла перед следующим scale-down в этой группе |
| `--scale-down-non-empty-candidates-count` | 30 | Максимум непустых кандидатов, которые CA рассматривает за один цикл |
| `--scale-down-enabled` | true | Полностью отключает логику scale-down (например, для тестовых сред) |
| `--max-node-provision-time` | 15m | Максимальное время ожидания появления узла; после — ошибка |
| `--max-graceful-termination-sec` | 600 (10m) | Максимальное время ожидания корректного завершения подов при drain |
| `--max-nodes-total` | 0 (без лимита) | Глобальный лимит на количество узлов во всех группах |
| `--min-node-count` | 0 | Минимальное суммарное количество узлов, которое CA поддерживает (ниже не опускается) |
| `--max-nodes-per-nodegroup` | 0 | Лимит на размер отдельной Node Group |
| `--expander` | random | Стратегия выбора группы узлов (см. раздел Expanders) |
| `--balance-similar-node-groups` | false | Автоматический поиск похожих групп и балансировка |
| `--balancing-ignore-label` | (пусто) | Метка, вариация которой по узлам не учитывается при балансировке |
| `--balancing-max-violation-preference` | -1 | Допустимое «нарушение» баланса при выборе группы |
| `--skip-nodes-with-system-pods` | true | Не удалять узлы с системными подами без PDB |
| `--skip-nodes-with-local-storage` | true | Не удалять узлы с подами, использующими local storage |
| `--expendable-pods-priority-cutoff` | -10 | Поды с приоритетом ≤ cutoff считаются «жертвуемыми» при scale-down (можно выселять без PDB) |
| `--node-labels` | (пусто) | Список меток `key=value`, автоматически добавляемых на все созданные узлы |
| `--node-taints` | (пусто) | Список taints, автоматически добавляемых на все созданные узлы (`key=value:NoSchedule`) |
| `--node-template-configmap-path` | (пусто) | Путь к ConfigMap со сложным шаблоном меток/taints (альтернатива CLI-флагам) |
| `--leader-elect` | true (при `--namespace`) | Использовать leader election (только один активный CA в `kube-system`) |
| `--namespace` | default | Ограничить область наблюдения конкретным namespace (только при `--watched-namespace-label`) |
| `--watched-namespace-label` | (пусто) | Наблюдать только за namespaces с данной меткой |
| `--cloud-provider` | (auto) | Имя провайдера облака (`aws`, `gce`, `azure`, `clusterapi`, `kubemark`, и т.д.) |
| `--cluster-name` | (пусто) | Имя кластера для провайдеров, где оно обязательно (AWS EKS, GKE) |
| `--cluster-autoscaler-status-config-map` | (пусто) | Имя ConfigMap для публикации статуса CA (см. сценарий мониторинга) |

---

## Алгоритмы выбора группы узлов (Expanders)

Если `Pending` под может быть размещен в нескольких разных Node Groups, CA использует `Expander` для выбора оптимальной:

| Стратегия | Логика выбора | Сценарий применения |
| :--- | :--- | :--- |
| **`random`** | Выбирает случайную группу. (По умолчанию). | Однородные кластеры, где все группы равны. |
| **`most-pods`** | Группа, на которую влезет максимум текущих `Pending` подов. | Массовые развертывания микросервисов. |
| **`least-waste`** | Группа, после заполнения которой останется минимум свободного CPU/RAM. | Строгая экономия ресурсов. |
| **`priority`** | На основе весов в ConfigMap. | Приоритетное использование Spot/Preemptible инстансов. |
| **`price`** | Минимальная стоимость (поддерживается AWS и GCP). | Динамическая оптимизация биллинга. |

---

## Практические сценарии

### Сценарий 1: Настройка избыточного резервирования (Over-provisioning)

Для обхода задержки в 3–10 минут при старте узлов используется паттерн «Pause Pods». Это позволяет иметь "горячий резерв" мощностей.

1. Создаем PriorityClass с низким приоритетом:
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: overprovisioning
value: -10
globalDefault: false
description: "Priority class for overprovisioning pause pods."
```

2. Разворачиваем "пустые" поды:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: overprovisioning
spec:
  replicas: 2
  selector:
    matchLabels:
      app: overprovisioning
  template:
    metadata:
      labels:
        app: overprovisioning
    spec:
      priorityClassName: overprovisioning
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.9
          resources:
            requests:
              cpu: "1"
              memory: "2Gi"
```
*Механика:* Pause-поды занимают узел. Когда приходит реальный под, он вытесняет (preempt) pause-под. Pause-под уходит в `Pending`, триггеря CA на создание нового узла в фоновом режиме, пока реальный под уже работает.

### Сценарий 2: Приоритетный выбор Spot-инстансов (Priority Expander)

Требует запуска CA с флагом `--expander=priority`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler-priority-expander
  namespace: kube-system
data:
  priorities: |-
    100:
      - .*spot-group.*    # Наивысший приоритет
    50:
      - .*on-demand-group.* # Запасной вариант, если Spot недоступны
```

### Сценарий 3: Защита критических узлов от Scale-Down

```yaml
apiVersion: v1
kind: Node
metadata:
  name: db-node-01
  annotations:
    # Узел никогда не будет удален, даже если утилизация упадет до 0%
    cluster-autoscaler.kubernetes.io/scale-down-disabled: "true"
```

### Сценарий 4: Корректное завершение работы при Scale-Down (Graceful Shutdown)

Для обеспечения корректного завершения приложений при удалении узлов необходимо настроить Graceful Shutdown и PDB.

1. Настройте `terminationGracePeriodSeconds` в спецификации пода:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker-app
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 60  # Время на завершение работы
      containers:
        - name: worker
          image: my-worker:latest
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 10"]  # Задержка перед завершением
```

2. Настройте приложение для обработки `SIGTERM`:
```go
// Пример на Go
sigChan := make(chan os.Signal, 1)
signal.Notify(sigChan, syscall.SIGTERM)
go func() {
    <-sigChan
    log.Println("Received SIGTERM, finishing current work...")
    // Завершение текущих задач, закрытие соединений
    time.Sleep(5 * time.Second)
    os.Exit(0)
}()
```

3. Используйте PDB для гарантии доступности:
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: worker-app-pdb
spec:
  minAvailable: 1  # Минимум 1 реплика всегда доступна
  selector:
    matchLabels:
      app: worker-app
```

4. Проверьте настройку:
```bash
# Симуляция drain (безопасное выселение)
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --dry-run=client

# Проверка, что поды корректно завершают работу
kubectl logs -f <pod-name> | grep -i "sigterm\|graceful\|shutdown"
```

### Сценарий 5: Развёртывание через Kustomize (без Helm)

В средах, где Helm запрещён политикой безопасности (например, требуется reproducible build через GitOps на Argo CD/Flux), CA разворачивается чистыми манифестами. Преимущества: каждая ревизия — это `git`-дифф, нет `tiller`, минимизируется TCB.

```bash
# Структура репозитория
mkdir -p overlays/production/base/cluster-autoscaler
```

```yaml
# base/cluster-autoscaler/serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app.kubernetes.io/name: cluster-autoscaler
```

```yaml
# base/cluster-autoscaler/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app.kubernetes.io/name: cluster-autoscaler
spec:
  replicas: 1
  revisionHistoryLimit: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: cluster-autoscaler
  strategy:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cluster-autoscaler
    spec:
      serviceAccountName: cluster-autoscaler
      priorityClassName: system-cluster-critical
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.33.0
          imagePullPolicy: IfNotPresent
          command:
            - ./cluster-autoscaler
            - --v=4
            - --stderrthreshold=info
            - --cloud-provider=clusterapi
            - --cluster-name=prod-eu-1
            - --node-group-auto-discovery=clusterapi:machinedeployments.cluster.x-k8s.io/asg-
            - --balance-similar-node-groups=true
            - --expander=least-waste
            - --skip-nodes-with-local-storage=false
            - --leader-elect=true
            - --leader-elect-lease-duration=15s
            - --leader-elect-renew-deadline=10s
            - --leader-elect-retry-period=5s
            - --scale-down-delay-after-add=10m
            - --scale-down-unneeded-time=10m
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 1Gi
          livenessProbe:
            httpGet:
              path: /health-check
              port: 8085
            initialDelaySeconds: 30
            periodSeconds: 30
            timeoutSeconds: 10
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health-check
              port: 8085
            initialDelaySeconds: 10
            periodSeconds: 10
          ports:
            - name: metrics
              containerPort: 8085
              protocol: TCP
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
```

```yaml
# base/cluster-autoscaler/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app.kubernetes.io/name: cluster-autoscaler
spec:
  type: ClusterIP
  clusterIP: None
  selector:
    app.kubernetes.io/name: cluster-autoscaler
  ports:
    - name: metrics
      port: 8085
      targetPort: 8085
```

```yaml
# base/cluster-autoscaler/servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app.kubernetes.io/name: cluster-autoscaler
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: cluster-autoscaler
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
      scrapeTimeout: 10s
```

```yaml
# base/cluster-autoscaler/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - serviceaccount.yaml
  - clusterrole.yaml
  - clusterrolebinding.yaml
  - deployment.yaml
  - service.yaml
  - servicemonitor.yaml
images:
  - name: registry.k8s.io/autoscaling/cluster-autoscaler
    newTag: v1.33.0
commonLabels:
  app.kubernetes.io/name: cluster-autoscaler
```

```yaml
# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: kube-system
resources:
  - ../../base/cluster-autoscaler
patches:
  - target:
      kind: Deployment
      name: cluster-autoscaler
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/resources/requests/cpu
        value: "200m"
```

> **Совет:** рекомпилируйте манифесты через `kustomize build overlays/production | kubectl diff -f -` перед `kubectl apply`, чтобы отследить drift и непреднамеренные изменения от rolling-updates.

### Сценарий 6: ProvisioningRequest — запрос емкости до появления подов (Batch/ML)

ProvisioningRequest (CRD, группа `autoscaling.x-k8s.io`) позволяет декларативно попросить CA заранее подготовить пул узлов под пакетное задание. Это решает классическую проблему: batch-job не может стартовать, пока CA не увидит `Pending` поды, но создание узлов занимает минуты, что для DAG-планировщиков (Airflow, Argo Workflows) недопустимо.

```yaml
apiVersion: autoscaling.x-k8s.io/v1
kind: ProvisioningRequest
metadata:
  name: batch-2026-08-31-nightly
  namespace: ml-team
spec:
  # Владелец, на котором CA будет основывать решения о scale-down
  # (если владелец удалён, PR очищается)
  provisioningClassName: "best-effort-atomic-scale-up.autoscaling.x-k8s.io"
  # Время жизни — если за это время поды не созданы, ресурс уходит
  validUntilSeconds: 1800
  podSets:
    - name: trainer
      # Целевое количество реплик
      count: 4
      # Контейнеры, описывающие ресурсы и политики (без запуска)
      podTemplateRef:
        apiVersion: v1
        kind: PodTemplate
        name: trainer-template
      # Если потребуются дополнительные ресурсы — запас
      resources:
        requests:
          cpu: "64"
          memory: "256Gi"
          nvidia.com/gpu: "1"
```

```yaml
apiVersion: v1
kind: PodTemplate
metadata:
  name: trainer-template
  namespace: ml-team
template:
  spec:
    priorityClassName: batch-train
    nodeSelector:
      workload: ml-training
    tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
    containers:
      - name: trainer
        image: my-registry/trainer:1.4
        resources:
          requests:
            cpu: "16"
            memory: "64Gi"
            nvidia.com/gpu: "1"
          limits:
            nvidia.com/gpu: "1"
        # Настоящий entrypoint не запускается, PR не создаёт поды
        command: ["sleep", "infinity"]
    restartPolicy: Never
```

**Проверка состояния:**

```bash
# CA константно обновляет status PR
kubectl get provisioningrequest -n ml-team batch-2026-08-31-nightly -o yaml
# → status.conditions[].type=Provisioned|CapacityAvailable
# → status.conditions[].status=True/False
# → status.conditions[].reason содержит подробности

# Пример успешного состояния:
# conditions:
#   - type: Provisioned
#     status: "True"
#     reason: "ScaleUpSucceeded"
#   - type: CapacityAvailable
#     status: "True"
```

**Классы ProvisioningRequest (`provisioningClassName`):**

| Класс | Семантика | Когда использовать |
| :--- | :--- | :--- |
| `best-effort-atomic-scale-up.autoscaling.x-k8s.io` | Атомарный (все или ничего) best-effort. Если не удалось — частично созданные узлы удаляются, через `ValidUntilSeconds` повторяется попытка. | ML-обучение, пакетные отчёты, где критично стартовать одновременно |
| `check-capacity.autoscaling.x-k8s.io` | Только проверяет наличие емкости, не создаёт узлы. | Планировщики (Airflow), желающие «забронировать» ресурс заранее |

> **Edge case:** узлы, созданные по `best-effort-atomic-scale-up`, подчиняются обычной scale-down-логике. Если поды не были созданы в течение `--scale-down-unneeded-time`, узлы уйдут. Поэтому `validUntilSeconds` подбирается исходя из реальной длительности подготовки воркеров.

### Сценарий 7: StatefulSet + `WaitForFirstConsumer` + CA

`StorageClass` с `volumeBindingMode: WaitForFirstConsumer` откладывает создание PersistentVolume до момента, когда планировщик выберет узел. Это критично для динамических провижионеров (Ceph RBD, Cinder, iSCSI). Ошибка новичков: `StorageClass` с immediate binding даёт PV в «неправильной» зоне, и под зависает в `Pending`.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-wffc
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: <ceph-cluster-id>
  pool: kubernetes
  csi.storage.k8s.io/provisioner-secret-name: ceph-secret
  csi.storage.k8s.io/provisioner-secret-namespace: kube-system
  csi.storage.k8s.io/node-publish-secret-name: ceph-secret
  csi.storage.k8s.io/node-publish-secret-namespace: kube-system
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer   # ← ключ
allowVolumeExpansion: true
```

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: postgres
              topologyKey: kubernetes.io/hostname
      containers:
        - name: postgres
          image: postgres:16
          resources:
            requests:
              cpu: "2"
              memory: "8Gi"
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: ceph-rbd-wffc
        resources:
          requests:
            storage: 100Gi
```

**Как CA взаимодействует с этим сценарием:**

1. Scheduler выбирает узел для первого пода StatefulSet (например, существующий).
2. PV создаётся на этой зоне (WaitForFirstConsumer срабатывает).
3. Когда под реплики #2 не помещается на существующих узлах, он уходит в `Pending`.
4. CA добавляет новый узел **в ту же зону**, что существующие поды, чтобы удовлетворить `topologySpreadConstraints` и `podAntiAffinity`.
5. PV для второго пода создаётся на новом узле, но всё ещё в той же зоне.

> **Важно для администратора:** проверьте, что все зоны доступности покрыты `MachineDeployment`/`ASG` с достаточным `maxSize`. CA балансирует между зонами только при `--balance-similar-node-groups=true` (см. таблицу флагов).

### Сценарий 8: Горизонтальное масштабирование самого CA (Sharding)

В больших кластерах (>1000 узлов) CA становится узким местом: он сериализует обработку `Pending`-подов и scale-down операций. Решение — запуск нескольких экземпляров CA, каждый из которых «отвечает» за свой шард.

**Стратегия шардинга через метки нод:**

```yaml
# Deployment cluster-autoscaler-east
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          args:
            - --cloud-provider=aws
            - --cluster-name=prod
            # Только узлы в зонах us-east-*
            - --node-labels=shard=east
            - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled
```

```yaml
# Deployment cluster-autoscaler-west (отдельный Deployment)
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          args:
            - --cloud-provider=aws
            - --cluster-name=prod
            - --node-labels=shard=west
            - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled
```

**Стратегия через `--watched-namespace-label` (multi-tenant):**

```yaml
# Отдельный CA на команду platform-team
spec:
  template:
    spec:
      containers:
        - args:
            - --watched-namespace-label=team=platform
```

> **Подробнее о стратегиях шардинга на уровне кластеров и самих узлов:** см. [Sharding](./sharding.md). В контексте CA шардинг решает проблему задержек на больших флотках (10k+ подов), но требует `leader-elect=false` (каждый инстанс независим) и тщательного разделения групп узлов.

### Сценарий 9: Миграция с Cluster Autoscaler на Karpenter

Karpenter обеспечивает существенно более быстрый JIT-скейлинг и лучший bin-packing, но миграция — это не просто «выключить CA, включить Karpenter». Ниже — проверенный план.

**Фаза 1: Подготовка (0–2 недели)**

1. Установите Karpenter (см. [Karpenter Installation](./Karpenter/installation.md)).
2. Подготовьте `NodePool`/`EC2NodeClass`/`AKSNodeClass` со всеми метками и taints, которые раньше задавались в `Node Group` через `--node-labels`/`--node-taints`.
3. Синхронизируйте subnet/security group/AMI параметры.
4. **Не отключайте CA** на этом этапе.

**Фаза 2: Двойное управление (2–4 недели)**

1. В Karpenter `NodePool` задайте `weight: 10`, в существующих `MachineDeployment` — высокую «стоимость» через instance type (CA выберет их последними).
2. Новые поды будут создаваться Karpenter-узлами. Старые — продолжать работать на CA-узлах.
3. Проверьте `kubectl get nodes -L karpenter.sh/registered,cluster-autoscaler=true` — оба набора должны сосуществовать.
4. Проверьте PDB: Karpenter учитывает PDB автоматически, но требует, чтобы все поды имели корректный `pdb`.

**Фаза 3: Перевод существующих нагрузок**

```bash
# Переведите StatefulSet на Karpenter через cordon
kubectl cordon -l cluster-autoscaler=true
# Дождитесь, пока Karpenter создаст замену
kubectl drain -l cluster-autoscaler=true --ignore-daemonsets --delete-emptydir-data
# Проверьте, что все ноды переехали
kubectl get nodes -l cluster-autoscaler=true
# → пустой список
```

**Фаза 4: Демонтаж CA**

```bash
helm uninstall cluster-autoscaler -n kube-system
kubectl delete clusterrolebinding,clusterrole,serviceaccount -l app.kubernetes.io/name=cluster-autoscaler -n kube-system
```

> **Подводный камень:** ProvisioningRequest (`autoscaling.x-k8s.io/v1`) обрабатываются и CA, и Karpenter одновременно. На этапе двойного управления Karpenter может «перехватить» PR. Рекомендуется временно исключить Karpenter из PR-обработки через аннотации ресурса или флаг `consolidationPolicy`.

---

## Особенности эксплуатации и On-Premise

### Развёртывание на Bare-metal (On-Premise)

В локальных дата-центрах CA сталкивается с фундаментальной проблемой: отсутствием безлимитного пула машин и стандартизированного API. 

*   **Интеграция:** Требует обвязки в виде **Metal3** (Bare Metal Operator), **MAAS** или кластерного API (Cluster API) для vSphere.
*   **Скорость:** Процесс PXE-загрузки, настройки BIOS и регистрации физического узла может занимать от 15 до 40 минут.
*   **Смысл применения:** В On-Premise "железо" уже куплено. Scale-down не экономит деньги напрямую (только электричество). CA здесь используется скорее для перераспределения серверов между разными кластерами, а не для классической эластичности.

### Специфика провайдеров (Out-of-Tree)

С версии Kubernetes 1.30 все облачные провайдеры (AWS, Azure, GCP) работают через механизм **Cloud Controller Manager (CCM)** (out-of-tree). CA должен запускаться с соответствующим провайдером облака и иметь права (IAM Roles) на изменение групп узлов.

### Типичные ошибки и их решения

#### Ошибка 1: Поды в `Pending`, CA не добавляет узлы

**Причины:**
- Лимит `max-nodes-total` достигнут
- Нет подходящей Node Group (не совпадают `nodeSelector`, `affinity`, `taints`)
- Недостаточно IAM-прав для изменения Node Group
- Узлы добавляются, но не успевают запуститься (превышен `--max-node-provision-time`)

**Диагностика:**
```bash
# Проверка логов CA
kubectl logs -n kube-system -l app=cluster-autoscaler | grep -i "noExpansion\|maxNodes\|limit"

# Проверка статуса узлов
kubectl get nodes --field-selector=status!=Ready

# Проверка Pending подов и причин
kubectl get pods --all-namespaces --field-selector=status.phase=Pending -o wide
kubectl describe pod <pod-name> | grep -A 10 "Events:"
```

**Решение:**
```bash
# Увеличение лимита (для Helm-установки)
helm upgrade cluster-autoscaler cluster-autoscaler/cluster-autoscaler \
  --set "autoDiscovery.clusterName=<cluster-name>" \
  --set "extraArgs.max-nodes-total=100"

# Или создание новой Node Group с подходящими метками
kubectl label node <node-name> node-type=high-memory
```

#### Ошибка 2: Узлы не удаляются при низкой утилизации

**Причины:**
- PDB блокирует выселение подов
- Поды с `safe-to-evict: "false"`
- Узел находится в cooldown-периоде (`--scale-down-delay-after-add`)
- Системные поды без PDB на узле

**Диагностика:**
```bash
# Проверка unremovable-узлов в логах
kubectl logs -n kube-system -l app=cluster-autoscaler | grep -i "unremovable"

# Проверка PDB, блокирующих выселение
kubectl get pdb --all-namespaces -o yaml | grep -A 5 "allowedDisruptions: 0"

# Проверка аннотаций узлов
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, disabled: .metadata.annotations["cluster-autoscaler.kubernetes.io/scale-down-disabled"]}'
```

**Решение:**
```bash
# Настройка PDB с разрешением на 1 disruption
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 90%
  # или maxUnavailable: 1
  selector:
    matchLabels:
      app: my-app
```

#### Ошибка 3: Флаппинг (цикличное добавление/удаление узлов)

**Причины:**
- Слишком маленький `--scale-down-delay-after-add`
- Короткий `--scale-down-unneeded-time`
- Высокая вариативность утилизации (HPA и CA работают несинхронно)

**Решение:**
```bash
# Увеличение задержек для стабильности
--scale-down-delay-after-add=15m
--scale-down-unneeded-time=15m

# Использование stabilizationWindowSeconds в HPA для синхронизации
```

### Edge Cases и известные ограничения

1. **DaemonSet и Scale-Down:** CA не удаляет узлы, если на них есть DaemonSet-поды, которые нельзя переместить (хотя формально DaemonSet исключается из расчета, некоторые конфигурации могут блокировать удаление).

2. **Pod Priority и Preemption:** При включенном `PodPriority` CA может удалять узлы с низкоприоритетными подами, если есть `Pending` поды с высоким приоритетом и настроен `preemptionPolicy: PreemptLowerPriority`.

3. **Topology Manager и DRA:** С Kubernetes 1.30+ CA учитывает `TopologyManagerPolicy` при симуляции. Неправильная настройка может привести к тому, что CA будет создавать узлы, которые не смогут удовлетворить `restricted` или `single-numa-node` политику.

4. **ProvisioningRequest и `WaitForFirstConsumer`:** Если в кластере действует `StorageClass` с `volumeBindingMode: WaitForFirstConsumer`, CA не создаст новый узел заранее по `ProvisioningRequest` в режиме `best-effort-atomic-scale-up`, пока планировщик не назначит первый под. Это вынуждает согласовывать топологию узлов с зональными ограничениями StorageClass (см. [Сценарий 7](#сценарий-7-statefulset--waitforfirstconsumer--ca)).

5. **SchedulingGates:** Поды с заданными `spec.schedulingGates` остаются в `Pending` без возможности планирования. CA **не учитывает** их как триггеры для scale-up, поэтому гейты должны сниматься либо человеком, либо сторонним контроллером до того, как потребуется емкость.

5. **Multi-Zone:** CA автоматически балансирует узлы по зонам, если настроен `--balance-similar-node-groups`. Без этого флага может возникнуть ситуация, когда узлы добавляются только в одну зону.

6. **Windows Nodes:** CA поддерживает Windows-узлы, но требует отдельной Node Group и корректной настройки `--node-group-auto-discovery` для смешанных кластеров.

---

## Мониторинг и диагностика

CA экспортирует метрики в формате Prometheus. Их мониторинг критичен для понимания причин, по которым узлы не добавляются или не удаляются.

| Метрика | Описание | Траблшутинг |
| :--- | :--- | :--- |
| `cluster_autoscaler_nodes_count` | Текущее количество узлов в разрезе групп. | Контроль достижения `max-nodes-total`. |
| `cluster_autoscaler_unschedulable_pods_count` | Поды, которые CA **не может** разместить. | Если > 0, значит CA уперся в лимиты, не нашел подходящей группы или нет прав IAM. |
| `cluster_autoscaler_scale_down_in_cooldown` | Находится ли группа в "заморозке" (cooldown) после масштабирования. | Объясняет, почему узлы не удаляются сразу. |
| `cluster_autoscaler_evicted_pods_total` | Количество подов, убитых при scale-down. | Анализ влияния на доступность приложения. |
| `cluster_autoscaler_scaled_up_nodes_total` | Счетчик успешных scale-up операций. | Мониторинг частоты масштабирования. |
| `cluster_autoscaler_failed_scale_ups_total` | Неудачные попытки scale-up. | Критический индикатор проблем с лимитами или правами. |
| `cluster_autoscaler_unremovable_nodes_count` | Узлы, которые CA не может удалить. | Выявление блокировок PDB или аннотациями. |
| `cluster_autoscaler_last_activity` | Unix-timestamp последнего полезного действия (scale-up или scale-down). | Детектор «зависшего» CA. |
| `cluster_autoscaler_provisioning_requests_count` | Количество активных `ProvisioningRequest` в кластере. | Контроль очереди batch/ML задач. |
| `cluster_autoscaler_cluster_simulation_scheduling_step_duration_seconds` | Гистограмма времени симуляции планировщика. | SLA при большом количестве узлов (>500). |

**Health-эндпоинт:** помимо метрик, CA экспонирует `GET /health-check` на порту `8085` (`--port`). Поддерживается как liveness-, так и readiness-probe (см. манифест Deployment в Сценарии 5). Endpoint возвращает 200 при успешной синхронизации с `kube-apiserver` и `cloud-provider`, 503 — при потере связи с любым из них.

### Prometheus-алерты

```yaml
# Алерт при неудачном масштабировании
- alert: ClusterAutoscalerFailedScaleUp
  expr: increase(cluster_autoscaler_failed_scale_ups_total[10m]) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Cluster Autoscaler не может добавить узел"
    description: "Обнаружены неудачные попытки scale-up за последние 10 минут. Проверьте лимиты, IAM-права и наличие подходящих Node Groups."

# Алерт при наличии длительных Pending подов
- alert: ClusterAutoscalerUnschedulablePods
  expr: cluster_autoscaler_unschedulable_pods_count > 0
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Unschedulable поды обнаружены более 15 минут"
    description: "{{ $value }} подов не могут быть запланированы. CA может быть не справляется или отсутствуют подходящие Node Groups."

# Алерт при невозможности scale-down
- alert: ClusterAutoscalerNodesNotScaledDown
  expr: cluster_autoscaler_unremovable_nodes_count > 5
  for: 30m
  labels:
    severity: info
  annotations:
    summary: "Более 5 узлов не могут быть удалены"
    description: "Возможна блокировка PDB или аннотациями safe-to-evict."
```

### Команды для диагностики

```bash
# Просмотр текущего состояния CA (events)
kubectl get events --field-selector source=cluster-autoscaler --sort-by='.lastTimestamp'

# Проверка текущих узлов в группах
kubectl get nodes -o custom-columns=NAME:.metadata.name,GROUP:.metadata.labels['karpenter.sh/provisioner-name'],STATUS:.status.conditions[-1].type

# Проверка утилизации узлов (для ручного анализа)
kubectl top nodes

# Просмотр логов CA с фильтром по scale-down
kubectl logs -n kube-system -l app=cluster-autoscaler --tail=100 | grep -i "scaleDown\|remov\|evict"

# Просмотр логов CA с фильтром по scale-up
kubectl logs -n kube-system -l app=cluster-autoscaler --tail=100 | grep -i "scaleUp\|expand\|provision"
```

### Диагностика через ConfigMap статуса

Для длинных логов (когда CA пишет события на каждой итерации) полезна публикация агрегированного статуса в ConfigMap через флаг `--cluster-autoscaler-status-config-map=cluster-autoscaler-status`. CA обновляет её при каждом цикле планирования.

```bash
# Проверка «последнего сканирования» и активных групп
kubectl get cm -n kube-system cluster-autoscaler-status -o yaml

# → data.status содержит JSON с:
#   - health: "Healthy"/"Unhealthy"
#   - lastUpdated: "2026-08-31T..."
#   - nodeGroups: [{name, minSize, maxSize, desiredCapacity, ...}]
#   - pendingPods: {<count>: <reason>}
```

> **Edge case:** ConfigMap пересоздаётся при каждом restart под CA. Чтобы избежать ложных алертов, не алертите на её отсутствие — алертите только на возраст `lastUpdated` (например, `> 5m` означает, что CA «застрял»).

### Эксплуатационные процедуры (Runbook)

#### Аварийное отключение scale-down

```bash
# Через ConfigMap (если используется Helm value extraArgs.scale-down-enabled=false → правка релиза)
helm upgrade cluster-autoscaler autoscaler/cluster-autoscaler \
  --reuse-values \
  --set extraArgs.scale-down-enabled=false

# Или через аннотацию конкретных узлов
kubectl annotate nodes -l workload=critical \
  cluster-autoscaler.kubernetes.io/scale-down-disabled=true --overwrite
```

#### Ротация логов CA

CA пишет в stderr (`--stderrthreshold=info`). При активной нагрузке лог может расти на десятки MB/час. Рекомендуется внешний log shipper (Fluent Bit, Vector) либо следующий обходной подход:

```yaml
# Volume для буфера логов (если используется не-prometheus-сборка)
volumeMounts:
  - name: log-buffer
    mountPath: /var/log/cluster-autoscaler
volumes:
  - name: log-buffer
    emptyDir:
      sizeLimit: 256Mi
```

```bash
# Однократная очистка при переполнении
kubectl exec -n kube-system deploy/cluster-autoscaler -- \
  sh -c 'find /var/log -name "*.log" -size +50M -delete'
```

#### Обновление CA без простоя

CA поддерживает `RollingUpdate` с `maxUnavailable: 0` (см. манифест в Сценарии 5). Однако фактического «простоя» не бывает: leader-election выполняется на каждой реплике, и при рестарте лидера lease автоматически переходит к другому реплике за 5–10 секунд. Без `replicas>1` будет кратковременный gap — задавайте `replicas: 2` для продакшна.

#### Проверка конфигурации перед применением

```bash
# Локальная проверка аргументов
./cluster-autoscaler \
  --cloud-provider=clusterapi \
  --node-group-auto-discovery=clusterapi:machinedeployments.cluster.x-k8s.io/asg- \
  --dry-run   # доступен с v1.31+ для большинства операций
```

```bash
# Валидация ConfigMap Priority Expander (regexp на имена групп)
kubectl get cm cluster-autoscaler-priority-expander -n kube-system -o jsonpath='{.data.priorities}' | \
  python3 -c "import sys, yaml, json; data = yaml.safe_load(sys.stdin); print(json.dumps(data, indent=2))"
# → {100: ['.*spot-group.*'], 50: ['.*on-demand-group.*']}
# Регулярные выражения компилируются Go regexp/syntax; ошибки появятся в логах CA.
```

---

## Влияние ResourceQuota и LimitRange на autoscaling

ResourceQuota и LimitRange в Namespace могут блокировать масштабирование, если не настроены с учётом autoscaling.

### Проблема: ResourceQuota блокирует HPA

HPA масштабирует Deployment, но поды не могут быть созданы из-за превышения квоты Namespace:

```bash
# Проверка квот
kubectl describe quota -n my-namespace
# → ResourceQuota: requests.cpu=10, limits.cpu=20
# → Текущее потребление: requests.cpu=9.5 (95%)

# HPA масштабирует до 5 подов (250m каждый):
# → 5 × 250m = 1250m > остаток 500m → поды в Pending
```

**Решение 1:** Увеличьте ResourceQuota с учётом maxReplicas HPA:

```
ResourceQuota (CPU) >= maxReplicas × requests.cpu + запас
```

**Решение 2:** Используйте `resourcequotas` с扩大的 quota для критичных Namespace:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: autoscaling-quota
  namespace: production
spec:
  hard:
    requests.cpu: "20"       # >= maxReplicas HPA × requests
    requests.memory: 40Gi
    limits.cpu: "40"
    limits.memory: 80Gi
    pods: "50"
```

### Проблема: LimitRange ограничивает масштабирование

LimitRange может установить min/max для CPU/memory, что конфликтует с requests Deployment:

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
    - type: Container
      default:
        cpu: "1"
        memory: 1Gi
      defaultRequest:
        cpu: 200m
        memory: 256Mi
      max:
        cpu: "4"       # HPA не может создать под с requests > 4 CPU
        memory: 8Gi
      min:
        cpu: 50m
        memory: 64Mi
```

**Проблема:** Если HPA настроен на масштабирование по CPU с `requests.cpu = 500m`, но LimitRange.max = 4 CPU, то limits не могут быть увеличены для горячих подов.

**Решение:** Убедитесь, что `max` в LimitRange >= HPA limits для контейнеров.

### Сценарий: CA + ResourceQuota + HPA

```yaml
# ResourceQuota для Namespace
apiVersion: v1
kind: ResourceQuota
metadata:
  name: production-quota
  namespace: production
spec:
  hard:
    requests.cpu: "30"
    requests.memory: 60Gi
    pods: "30"
---
# HPA с maxReplicas = 15
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
---
# Deployment: requests.cpu = 1000m
# maxReplicas × requests = 15 × 1000m = 15000m = 15 CPU
# ResourceQuota.requests.cpu = 30 CPU (достаточно для 30 × 1000m)
```

**Расчёт:** ResourceQuota.requests.cpu >= maxReplicas × requests.cpu + запас 20%.

### Диагностика

```bash
# Проверка ResourceQuota
kubectl describe quota -n production
# → requests.cpu: 15/30 (50% используется)

# Проверка LimitRange
kubectl describe limitrange -n production
# → Container Limits: max=4 CPU, min=50m

# Проверка Pending-подов из-за квоты
kubectl get events -n production --field-selector reason=FailedCreate | grep quota
# → Warning  FailedCreate  pods "api-xxxxx" is forbidden: exceeded quota

# Проверка CA логов
kubectl logs -n kube-system -l app=cluster-autoscaler | grep -i "quota\|limit"
# → W0115 10:35:00.123456 1 autoscaler.go:456] Failed to increase group size: quota exceeded
```

### Best Practices

1. **Квота с запасом:** `ResourceQuota.requests.cpu >= maxReplicas × requests.cpu × 1.2`
2. **LimitRange.max >= HPA.limits:** Убедитесь, что max в LimitRange позволяет HPA создавать поды с нужными limits
3. **Мониторинг:** Алерты на приближение к лимитам ResourceQuota
4. **Auto-scaling квот:** Рассмотрите использование чарта `resourcequota-controller` для автоматического масштабирования квот
5. **PriorityClass + Quota:** Используйте `PriorityClass` для выделения критичных Namespace с бо́льшими квотами

---

## Лучшие практики 2026 года

1.  **Синхронизация с HPA/VPA:** Убедитесь, что лимиты `requests` настроены корректно (желательно с помощью [VPA в режиме Off](./vpa_detailed.md)). CA масштабирует кластер опираясь на `requests`. Если они завышены, кластер будет раздут (over-provisioning), если занижены — узлов будет не хватать.
2.  **Разделение групп узлов:** Создавайте отдельные Node Groups для разных типов нагрузок (CPU-intensive, GPU, Stateful) и используйте Taints/Tolerations.
3.  **Использование PDB:** Всегда настраивайте `PodDisruptionBudget`. Это единственная гарантия того, что CA не выселит все реплики вашего сервиса одновременно при Scale-Down.
4.  **Karpenter как альтернатива:** Для кластеров в AWS и Azure рассмотрите переход на **[Karpenter](./Karpenter/overview.md)**. Он работает без абстракции Node Groups (JIT-provisioning), быстрее реагирует на нагрузку и обеспечивает лучший бинпакинг. Подробный план миграции — см. [Сценарий 9](#сценарий-9-миграция-с-cluster-autoscaler-на-karpenter).
5.  **Мониторинг и алертинг:** Настройте Prometheus-алерты на `cluster_autoscaler_failed_scale_ups_total` и `cluster_autoscaler_unschedulable_pods_count`. Это позволит оперативно реагировать на проблемы с масштабированием.
6.  **Over-provisioning для критичных сервисов:** Используйте Pause Pods с низким приоритетом для обеспечения «горячего резерва» мощностей (см. Сценарий 1).
7.  **Балансировка по зонам:** Включите `--balance-similar-node-groups` для автоматического распределения узлов между зонами доступности.
8.  **Graceful Shutdown:** Убедитесь, что приложения корректно обрабатывают `SIGTERM` и завершают работу в течение `terminationGracePeriodSeconds`. Это критично для безопасного scale-down.

---

## Дополнительная информация

### Сравнение Cluster Autoscaler и Karpenter

| Характеристика | Cluster Autoscaler | Karpenter |
| :--- | :--- | :--- |
| **Архитектура** | Управление Node Groups | JIT-provisioning без групп |
| **Скорость scale-up** | 3-10 минут | 45-90 секунд |
| **Поддержка on-prem** | Да (через Cluster API, Metal3) | Нет (только облако) |
| **Бинпакинг** | Ограничен Node Groups | Оптимальный (под конкретный под) |
| **Сложность конфигурации** | Высокая (Node Groups, Expanders) | Низкая (NodePool) |
| **Поддержка DRA** | Да (с 1.32 — structured parameters) | Да |
| **Поддержка ProvisioningRequest** | Да (с 1.30) | Частичная (создаёт узлы, но не все классы) |
| **Лидер-элект / HA** | Встроенный (Lease), `replicas>1` | Несколько реплик через webhooks, лидер не выбирается |
| **Рекомендация 2026** | On-premise, bare-metal, mixed, multi-cluster | EKS, AKS (где есть Karpenter) |

### Эволюция: от CA к ProvisioningRequest и далее

Классический CA (2016–2024) использовал абстракцию Node Groups и ждал `Pending` подов. Это создавало две проблемы:

1. **Задержка для batch-сценариев** — планировщики (Airflow, Volcano) не могут создать `Pending` под заранее, узлы не подготавливаются до момента реального планирования.
2. **Слабая координация со специализированным стеком** — Volcano, Spark on K8s, Argo Workflows вынуждены были сами вызывать API провайдера.

`ProvisioningRequest` (CRD `autoscaling.x-k8s.io/v1`, Beta с 1.30, GA планируется в 1.34/1.35) — это попытка вынести «заказ емкости» из логики CA на отдельный уровень. Любой контроллер (планировщик, Volcano, Argo Workflows) может создать `ProvisioningRequest` без фактического создания подов, и CA начнёт готовить узлы заранее. В перспективе это даёт единый декларативный API для запроса емкости, независимый от того, какой автоскейлер установлен в кластере (CA/Karpenter/Volcano).

### Источники и первоисточники

* [Cluster Autoscaler — README](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/README.md) — актуальная матрица совместимости и список флагов.
* [ProvisioningRequest — design proposal](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/proposals/provisioning-request.md) — спецификация CRD.
* [Kubernetes docs — Node Autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/node-autoscaling/) — официальная страница Kubernetes о концепции.

### См. также
* **[Pod Disruption Budget (PDB)](./pod_disruption_budget.md)** — критически важная интеграция при scale-down.
* **[Karpenter: отличия от Cluster Autoscaler](./Karpenter/overview.md#отличия-от-cluster-autoscaler)** — современная JIT-альтернатива для облачных провайдеров.
* **[Cluster Autoscaler vs Karpenter](./cluster_autoscaler_vs_karpenter.md)** — подробный сравнительный анализ.
* **[Descheduler](./descheduler.md)** — дефрагментация кластера после scale-down.
* **[Autoscaling в On-Premise](./on_premise_autoscaling.md)** — масштабирование в bare-metal средах.
* **[Алертинг и мониторинг](./alerting_monitoring.md)** — Prometheus-алерты для CA.
* **[Горизонтальное масштабирование кластеров (sharding)](./sharding.md)** — мульти-CA стратегии для крупных инсталляций.
