# Профилактика выселения подов (Pod Evicted)

## Определения

**Профилактика выселения (Eviction Prevention)** — комплекс архитектурных и конфигурационных мер, направленных на обеспечение стабильности подов и предотвращение их принудительного завершения компонентом `kubelet` при дефиците ресурсов узла.

**Цели профилактики:**
1. **Исключение resource starvation:** Предотвращение состояний `MemoryPressure`, `DiskPressure` и `PIDPressure`.
2. **Гарантия доступности:** Обеспечение работы критических сервисов даже при плановом обслуживании или частичной деградации узлов.
3. **Автоматизация управления:** Переход от ручного исправления последствий к автоматическому масштабированию и перераспределению ресурсов.
4. **Предсказуемость:** Обеспечение стабильного поведения кластера при колебаниях нагрузки и ресурсной базы.

**Eviction Prevention vs. High Availability:**
Профилактика выделения фокусируется на *предотвращении* принудительного завершения подов из-за нехватки ресурсов на узле. High Availability (HA) решает более широкую задачу — обеспечение доступности сервисов при сбоях любого типа (аппаратные, программные, сетевые). Профилактика выселения является одной из ключевых составляющих HA.

## Основные концепции

### Уровни защиты от выселения

| Уровень | Механизм защиты | Тип угрозы | Критичность |
|:---|:---|:---|:---|
| **Приоритезация** | `PriorityClass` | Вытеснение менее важных подов вместо критических | Critical |
| **Ресурсы (QoS)** | `requests` == `limits` (Guaranteed) | Дефицит памяти/CPU на узле | Critical |
| **Хранилище** | Лимиты `ephemeral-storage` | `DiskPressure` (переполнение разделов) | High |
| **Доступность** | `PodDisruptionBudget` (PDB) | Массовый `kubectl drain` или API-выселение | High |
| **Конфигурация узла** | `kubeReserved` + `systemReserved` | Краш системных компонентов (System Starvation) | Critical |
| **PID-защита** | `podPidsLimit` | Fork-бомбы, утечки процессов | Medium |
| **Балансировка** | `Descheduler` | Перекосы нагрузки между узлами | Medium |
| **Кластер** | Cluster Autoscaler / Karpenter | Исчерпание общей емкости кластера | High |

### Конфигурация Kubelet: Пороги выселения

`kubelet` инициирует выселение подов на основе заданных порогов. Правильная настройка этих параметров позволяет создать "буфер безопасности" между потреблением ресурсов и моментом выселения.

#### Hard Eviction vs. Soft Eviction

| Параметр | Hard Eviction | Soft Eviction |
|:---|:---|:---|
| **Сигнал** | `SIGKILL` | `SIGTERM` |
| **Grace Period** | Игнорируется | `eviction-soft-grace-period` |
| **Назначение** | Экстренная защита узла | Плавное снижение нагрузки |
| **Рекомендация** | Всегда настраивать | Для приложений с длительным завершением |

**Hard Eviction (`--eviction-hard`)**: Немедленное выселение подов при достижении порога. По умолчанию: `memory.available<100Mi`, `nodefs.available<10%`.

**Soft Eviction (`--eviction-soft`)**: Выселение начинается только если порог превышен в течение заданного времени (`--eviction-soft-grace-period`). Позволяет игнорировать кратковременные всплески нагрузки.

**Важно:** Если `evictionHard` и `evictionSoft` наложены на один и тот же ресурс (например, `memory.available`), жесткий порог имеет приоритет и `soft` игнорируется для этого ресурса.

Пример конфигурации `/var/lib/kubelet/config.yaml`:
```yaml
evictionHard:
  memory.available: "500Mi"
  nodefs.available: "10%"
  nodefs.inodesFree: "5%"
  pid.available: "10%"
evictionSoft:
  memory.available: "1Gi"
  nodefs.available: "15%"
evictionSoftGracePeriod:
  memory.available: "2m"
  nodefs.available: "1m30s"
evictionMinimumReclaim:
  memory.available: "200Mi"
  nodefs.available: "5%"
```

**Рекомендации по настройке порогов:**

| Тип узла | `memory.available` (Hard) | `memory.available` (Soft) | Комментарий |
|:---|:---|:---|:---|
| Worker (8-32 ГБ RAM) | `500Mi` | `1Gi` | Стандартная конфигурация |
| Worker (64-128 ГБ RAM) | `1Gi` | `2Gi` | Увеличенный буфер для крупных кластеров |
| Worker (256+ ГБ RAM) | `2Gi` | `4Gi` | Для вычислительных узлов с высокой нагрузкой |
| Control Plane | `1Gi` | `2Gi` | Приоритет стабильности компонентов управления |

### Node Allocatable: Резервирование ресурсов

Для защиты самого `kubelet` и системных демонов (sshd, systemd, containerd) необходимо резервировать ресурсы, которые **не будут** доступны подам.

**Формула:**
`[Allocatable] = [Capacity] - [kube-reserved] - [system-reserved] - [eviction-threshold]`

#### Компоненты резервирования

| Параметр | Назначение | Типичные значения |
|:---|:---|:---|
| **`kube-reserved`** | Для компонентов K8s (`kubelet`, `container runtime`, `kube-proxy`) | `cpu=250m-500m`, `memory=512Mi-1Gi` |
| **`system-reserved`** | Для ОС (`kernel`, `systemd`, `sshd`, `journald`) | `cpu=250m-500m`, `memory=512Mi-1Gi` |
| **`eviction-threshold`** | Запас для срабатывания порогов выселения | Задается через `evictionHard` |

**Почему это важно:** Если `kube-reserved` и `system-reserved` не настроены, `kubelet` и системные процессы конкурируют с подами за ресурсы. При высокой нагрузке это приводит к:
- Старту OOM Killer на системных процессах (краш kubelet, containerd)
- Некорректной работе eviction manager (недостаточно ресурсов для мониторинга)
- Нестабильности узла и каскадным выселениям

**Пример конфигурации:**
```yaml
kubeReserved:
  cpu: "500m"
  memory: "1Gi"
  ephemeral-storage: "1Gi"
systemReserved:
  cpu: "500m"
  memory: "512Mi"
  ephemeral-storage: "1Gi"
```

**Как рассчитать необходимые резервы:**
1. Мониторьте потребление `kubelet` и системных процессов через `cAdvisor` или `node_exporter`.
2. Добавьте запас 20-30% от пиковых значений.
3. Учитывайте количество подов на узле (каждый под добавляет overhead для `kubelet`).

> Подробнее: **[Kubelet — агент Kubernetes на узле](../../../Concepts/kubelet.md)**.

### Классы QoS и PriorityClass

#### QoS (Quality of Service)

Определяет очередность выселения при дефиците памяти. Поды `Guaranteed` имеют наивысшую выживаемость.

| Класс QoS | Определение | Приоритет выселения | Защита |
|:---|:---|:---|:---|
| **Guaranteed** | `requests` == `limits` для всех контейнеров | Последняя | Максимальная |
| **Burstable** | Хотя бы один контейнер с `requests` < `limits` | Средняя | До уровня `requests` |
| **BestEffort** | Нет `requests` и `limits` | Первая | Нет |

#### PriorityClass

Позволяет планировщику вытеснять менее важные поды при нехватке места для высокоприоритетных.

**Рекомендуемая иерархия приоритетов:**

| PriorityClass | Value | Назначение | Пример использования |
|:---|:---|:---|:---|
| `system-node-critical` | 2000000000 | Системные компоненты | kube-proxy, CNI, DNS |
| `system-cluster-critical` | 2000001000 | Критические кластерные сервисы | CoreDNS, Metrics Server |
| `prod-critical` | 1000000 | Критические production-сервисы | API Gateway, Payment |
| `prod-high` | 100000 | Важные production-сервисы | Order Service, Auth |
| `prod-medium` | 10000 | Обычные production-сервисы | User Service, Notification |
| `dev-low` | 1000 | Development/test нагрузки | CI/CD runners, Staging |

**Важно:** QoS определяет порядок выселения *внутри* узла (kubelet), а PriorityClass — порядок вытеснения *между* подами на уровне планировщика (scheduler).

> Детали: **[QoS и выселение](./qos_and_eviction.md)**, **[Приоритеты подов (PriorityClass)](../../../Concepts/priorityclass.md)**.

### PID-защита и предотвращение Fork-бомб

Исчерпание лимита PID (`PIDPressure`) приводит к невозможности запуска новых процессов, включая контейнеры и shell-сессии.

**Настройка защиты:**
```yaml
# В KubeletConfiguration
podPidsLimit: 4096  # Максимум PID на под (по умолчанию -1 = без лимита)
```

**Системный лимит:**
```bash
# Проверка текущего лимита
sysctl kernel.pid_max
# → 32768

# Увеличение (если необходимо)
sysctl -w kernel.pid_max=4194304
```

**Мониторинг PIDPressure:**
```yaml
- alert: NodePIDPressure
  expr: kube_node_status_condition{condition="PIDPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.node }} в состоянии PIDPressure"
```

### Время завершения подов (Graceful Shutdown)

Правильная настройка времени завершения критична для предотвращения потери данных при выселении.

**Параметры:**
- `terminationGracePeriodSeconds` в манифесте пода (по умолчанию 30s)
- `evictionSoftGracePeriod` в конфигурации kubelet
- `shutdownGracePeriod` и `shutdownGracePeriodCriticalPods` для Graceful Node Shutdown

**Рекомендации по настройке:**

| Тип приложения | `terminationGracePeriodSeconds` | Комментарий |
|:---|:---|:---|
| Stateless API | 30-60s | Стандартное завершение |
| Stateless с Long Polling | 60-120s | Завершение активных соединений |
| Database (PostgreSQL, MySQL) | 120-300s | Checkpoint, flush WAL |
| Queue Consumer (Kafka, RabbitMQ) | 60-180s | Commit offsets, acknowledge |
| Batch Job | 600-1800s | Корректное завершение обработки |

**PreStop Hook:**
Для приложений, которым нужно выполнить дополнительные действия перед получением `SIGTERM`:
```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "sleep 15 && /app/graceful-shutdown.sh"]
```

**Важно:** `preStop` выполняется *до* отправки `SIGTERM`. Общее время завершения = `preStop` + `terminationGracePeriodSeconds`. Если `preStop` длится дольше `terminationGracePeriodSeconds`, под будет убит `SIGKILL`.

## Практические сценарии

### 1. Настройка Guaranteed QoS для критичных приложений

Для предотвращения `MemoryPressure` необходимо выровнять `requests` и `limits` для всех контейнеров в поде. Это гарантирует, что `kubelet` не выберет этот под как кандидата на выселение, пока есть поды других классов.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service
  namespace: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: payment-service
  template:
    metadata:
      labels:
        app: payment-service
    spec:
      priorityClassName: prod-critical
      containers:
      - name: payment
        image: payment-service:2.1.0
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        terminationGracePeriodSeconds: 120
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 10"]
```

**Валидация:**
```bash
# Проверка QoS класса
kubectl get pod -n production -l app=payment-service -o jsonpath='{.items[*].status.qosClass}'
# → Guaranteed Guaranteed Guaranteed

# Проверка priority
kubectl get pod -n production -l app=payment-service -o jsonpath='{.items[*].spec.priority}'
# → 1000000 1000000 1000000
```

### 2. Полная конфигурация Kubelet для профилактики

**Цель:** Настроить kubelet с резервированием ресурсов, порогами выселения и защитой от PID-бомб.

```yaml
# /var/lib/kubelet/config.yaml (KubeletConfiguration v1)
apiVersion: kubelet.config.k8s.io/v1
kind: KubeletConfiguration
authentication:
  anonymous:
    enabled: false
  webhook:
    enabled: true
authorization:
  mode: Webhook
clusterDNS:
- "10.96.0.10"
clusterDomain: "cluster.local"
resolvConf: "/run/systemd/resolve/resolv.conf"

# === Резервирование ресурсов ===
kubeReserved:
  cpu: "500m"
  memory: "1Gi"
  ephemeral-storage: "1Gi"
systemReserved:
  cpu: "500m"
  memory: "512Mi"
  ephemeral-storage: "1Gi"

# === Пороги выселения ===
evictionHard:
  memory.available: "500Mi"
  nodefs.available: "10%"
  nodefs.inodesFree: "5%"
  imagefs.available: "15%"
  pid.available: "10%"
evictionSoft:
  memory.available: "1Gi"
  nodefs.available: "15%"
evictionSoftGracePeriod:
  memory.available: "2m"
  nodefs.available: "1m30s"
evictionMinimumReclaim:
  memory.available: "200Mi"
  nodefs.available: "5%"

# === Защита от PID-бомб ===
podPidsLimit: 4096

# === Время завершения при перезагрузке узла ===
shutdownGracePeriod: 30s
shutdownGracePeriodCriticalPods: 10s

# === Контейнерный runtime ===
containerRuntimeEndpoint: "unix:///run/containerd/containerd.sock"
```

**Применение и проверка:**
```bash
# 1. Применить конфигурацию
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# 2. Проверить Allocated resources
kubectl describe node <node-name> | grep -A 20 "Allocated resources"
# → cpu: 2500m (reserved: 1000m, allocatable: 1500m)
# → memory: 32Gi (reserved: 1536Mi, allocatable: 30464Mi)

# 3. Проверить пороги
kubectl get node <node-name> -o jsonpath='{.status.conditions[*].type}'
# → MemoryPressure DiskPressure PIDPressure Ready
```

### 3. Изоляция и лимиты эфемерного хранилища

Для защиты от `DiskPressure` используйте два подхода:

#### Подход 1: Лимиты в манифестах

Ограничивайте `ephemeral-storage` для `emptyDir` и логов:
```yaml
resources:
  limits:
    ephemeral-storage: "2Gi"  # Под выселяется при превышении
```

#### Подход 2: Разделение дисков

Рекомендуется выносить `/var/lib/kubelet` (основная ФС) и `/var/lib/containerd` (ФС образов) на разные физические диски или логические разделы.

```bash
# Проверка текущего использования
df -h /var/lib/kubelet /var/lib/containerd

# Настройка отдельного раздела для образов (в /etc/containerd/config.toml)
[plugins."io.containerd.grpc.v1.cri"]
  root = "/mnt/containerd/data"
  snapshotter = "overlayfs"
```

#### Подход 3: Очистка образов

```bash
# Удаление неиспользуемых образов
crictl rmi --prune

# Проверка размера кэша образов
crictl images | awk '{sum += $4} END {print sum/1024/1024 " GB"}'
```

> Подробнее: **[Выселение по диску (Disk Eviction)](./disk_eviction.md)**.

### 4. Защита доступности через PDB

`PodDisruptionBudget` предотвращает массовое выселение подов одного сервиса при операциях обслуживания (например, обновлении узлов).

**Минимальная конфигурация для production:**
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: payment-service-pdb
  namespace: production
spec:
  minAvailable: 2  # Или maxUnavailable: 1
  selector:
    matchLabels:
      app: payment-service
```

**Расширенная конфигурация с unhealthyPodEvictionPolicy (K8s 1.30+):**
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: critical-service-pdb
spec:
  minAvailable: 3
  unhealthyPodEvictionPolicy: AlwaysAllow  # Разрешает выселение "битых" подов
  selector:
    matchLabels:
      app: critical-service
```

**Проверка PDB:**
```bash
# Список всех PDB
kubectl get pdb -A

# Детали конкретного PDB
kubectl describe pdb payment-service-pdb -n production

# Проверка доступных нарушений
kubectl get pdb payment-service-pdb -o jsonpath='{.status.disruptionsAllowed}'
# → 1
```

> **Важно:** PDB игнорируется при `Hard Eviction`, если узел находится в критическом состоянии. Детали: **[Pod Disruption Budget](../../../Autoscaling/pod_disruption_budget.md)**.

### 5. Проактивное перераспределение (Descheduler)

`Descheduler` помогает избежать выселений, обнаруживая узлы с избыточной нагрузкой и аккуратно перенося поды на более свободные узлы **до** того, как сработают пороги `kubelet`.

**Полезные стратегии:**
- `RemoveDuplicates`: Убирает лишние реплики с одного узла.
- `LowNodeUtilization`: Переносит поды с перегруженных узлов на недогруженные.
- `RemovePodsViolatingInterPodAntiAffinity`: Исправляет нарушения правил анти-аффинити.
- `RemovePodsViolatingNodeAffinity`: Перемещает поды, нарушающие `requiredDuringSchedulingIgnoredDuringExecution`.

**Пример конфигурации Descheduler:**
```yaml
apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
profiles:
- name: ProfileName
  pluginConfig:
  - name: "LowNodeUtilization"
    args:
      thresholds:
        cpu: 20
        memory: 20
        pods: 15
      targetThresholds:
        cpu: 50
        memory: 60
        pods: 30
  plugins:
    balance:
      enabled:
      - "LowNodeUtilization"
```

### 6. Автоматизация лимитов (VPA)

Часто выселения происходят из-за некорректно настроенных `requests/limits`. `Vertical Pod Autoscaler` (VPA) в режиме `Auto` или `Initial` помогает автоматически выставлять значения на основе реального потребления.

**Пример VPA для критического сервиса:**
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: payment-service-vpa
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: payment-service
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: "payment"
      minAllowed:
        cpu: 500m
        memory: 512Mi
      maxAllowed:
        cpu: 4000m
        memory: 8Gi
      controlledResources: ["cpu", "memory"]
```

> Подробнее: **[VPA: Вертикальное масштабирование подов](../../../Autoscaling/vpa_detailed.md)**.

### 7. Ранбук: Предотвращение выселений в production

**Чеклист перед запуском сервиса:**

```bash
#!/bin/bash
# pre-deployment-check.sh

NAMESPACE=${1:-production}
DEPLOYMENT=${2:-""}

echo "=== Pre-deployment Eviction Prevention Check ==="

# 1. Проверка QoS класса
echo "--- QoS Check ---"
kubectl get deploy $DEPLOYMENT -n $NAMESPACE -o jsonpath='{.spec.template.spec.containers[*].resources}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('requests:', d.get('requests',{})); print('limits:', d.get('limits',{}))"

# 2. Проверка PriorityClass
echo "--- PriorityClass Check ---"
kubectl get deploy $DEPLOYMENT -n $NAMESPACE -o jsonpath='{.spec.template.spec.priorityClassName}'
echo ""

# 3. Проверка PDB
echo "--- PDB Check ---"
kubectl get pdb -n $NAMESPACE -l app=$DEPLOYMENT 2>/dev/null || echo "WARNING: No PDB found"

# 4. Проверка ресурсов узла
echo "--- Node Resources ---"
kubectl top nodes

# 5. Проверка conditions
echo "--- Node Conditions ---"
kubectl get nodes -o custom-columns="NAME:.metadata.name,MEMORY_PRESSURE:.status.conditions[?(@.type=='MemoryPressure')].status,DISK_PRESSURE:.status.conditions[?(@.type=='DiskPressure')].status,PID_PRESSURE:.status.conditions[?(@.type=='PIDPressure')].status"
```

### 8. Мониторинг и алертинг

Настраивайте алерты в Prometheus с упреждением (до достижения Hard thresholds).

```yaml
# Предупреждение о росте использования памяти на узле
- alert: NodeMemoryUsageApproachingEviction
  expr: (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 < 15
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.node }} близок к MemoryPressure (свободно < 15%)"

# Критическое предупреждение о нехватке памяти
- alert: NodeMemoryCritical
  expr: (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 < 5
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Узел {{ $labels.node }} критически близок к MemoryPressure (свободно < 5%)"

# Предупреждение о DiskPressure
- alert: NodeDiskPressure
  expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 15
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.node }} близок к DiskPressure (свободно < 15%)"

# Предупреждение о PIDPressure
- alert: NodePIDPressure
  expr: kube_node_status_condition{condition="PIDPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.node }} в состоянии PIDPressure"

# Мониторинг количества выселенных подов
- alert: HighEvictionRate
  expr: increase(kube_pod_status_reason{reason="Evicted"}[1h]) > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Высокий уровень выселений в кластере (>5 в час)"

# Мониторинг PDB блокировок
- alert: PDBBlockingEvictions
  expr: kube_poddisruptionbudget_status_current_healthy < kube_poddisruptionbudget_status_desired_healthy
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "PDB {{ $labels.name }} блокирует выселения"
```

### 9. Очистка завершенных подов

Выселенные поды остаются в API в статусе `Failed` (Reason: `Evicted`). Это полезно для диагностики, но замусоривает вывод.

```bash
# Удаление выселенных подов старше 24 часов
kubectl get pods -A --field-selector status.reason=Evicted,status.phase=Failed --no-headers | \
  awk '{print $1, $2, $4}' | \
  while read ns pod age; do
    echo "Deleting: $ns/$pod (age: $age)"
    kubectl delete pod $pod -n $ns
  done

# Автоматизация через CronJob
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup-evicted-pods
  namespace: kube-system
spec:
  schedule: "0 */6 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: evicted-pod-cleanup
          containers:
          - name: cleanup
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl get pods -A --field-selector status.reason=Evicted --no-headers | \
              awk '{print $1 " " $2}' | xargs -L1 bash -c 'kubectl delete pod $1 -n $0'
          restartPolicy: OnFailure
```

### 10. Расчет ресурсов для нового узла

При добавлении узла в кластер необходимо правильно рассчитать `Allocatable` ресурсы.

**Формула расчета:**
```
Allocatable = Capacity - kube-reserved - system-reserved - eviction-threshold
```

**Пример для узла с 32 ГБ RAM и 8 CPU:**

| Параметр | CPU | Memory |
|:---|:---|:---|
| Capacity | 8000m | 32Gi |
| kube-reserved | 500m | 1Gi |
| system-reserved | 500m | 512Mi |
| eviction-threshold (Hard) | 0 | 500Mi |
| **Allocatable** | **7000m** | **29.5Gi** |

**Валидация:**
```bash
kubectl describe node <node-name> | grep -A 10 "Allocated resources"
# → cpu: 7000m (reserved: 1000m)
# → memory: 29.5Gi (reserved: 1.5Gi)
```

## Дополнительная информация

### Резюме лучших практик

| Практика | Описание | Приоритет |
|:---|:---|:---|
| **Requests == Limits** | Используйте для всех production-нагрузок (Guaranteed QoS). | Critical |
| **PriorityClass** | Разделяйте системные (high) и пользовательские (low) приоритеты. | High |
| **Kube-reserved** | Всегда настраивайте резервирование ресурсов на уровне Kubelet. | High |
| **System-reserved** | Резервируйте ресурсы для системных демонов ОС. | High |
| **PodPidsLimit** | Ограничивайте количество процессов в поде. | Medium |
| **PDB** | Настраивайте для каждого production-сервиса с высокой доступностью. | High |
| **Graceful Shutdown** | Настраивайте `terminationGracePeriodSeconds` и PreStop hooks. | High |
| **Логирование** | Используйте внешние системы сбора логов (Loki, ELK), чтобы не забивать диск узла. | Medium |
| **Мониторинг** | Настройте алерты для `MemoryPressure`, `DiskPressure`, `PIDPressure`. | High |
| **Очистка** | Автоматизируйте удаление выселенных подов через CronJob. | Medium |

### Типичные ошибки и как их избежать

| Ошибка | Последствия | Решение |
|:---|:---|:---|
| Отсутствие `kube-reserved` | Kubelet конкурирует с подами за память, возможен краш | Всегда настраивайте резервирование |
| `requests` < реального потребления | Поды выселяются при MemoryPressure | Мониторьте и корректируйте requests |
| PDB с `minAvailable: 100%` | `kubectl drain` блокируется, обслуживание невозможно | Используйте `maxUnavailable: 1` или `minAvailable: N-1` |
| Нет PDB для критических сервисов | Массовое выселение при drain узла | Создавайте PDB для каждого production-сервиса |
| Отсутствие алертов на eviction | Проблемы обнаруживаются только после вылета сервисов | Настройте превентивные алерты в Prometheus |

### Ограничения и особенности

1. **Hard Eviction игнорирует PDB:** При критическом давлении ресурсов kubelet убивает поды без учета бюджета прерываний.
2. **Taint-based Eviction игнорирует PDB:** Выселение по `NoExecute` taint не проверяет PodDisruptionBudget.
3. **Preemption и QoS:** При вытеснении (preemption) планировщик учитывает только `PriorityClass`, а не QoS класс.
4. **Local Persistent Volume:** Поды с Local PV не могут быть перемещены на другой узел при drain.
5. **Static Pods:** Управляются kubelet напрямую, `drain` их игнорирует.

#### 11. Влияние LimitRange на QoS класс подов

LimitRange может неожиданно изменить QoS класс пода через автоматическое назначение `requests` и `limits` по умолчанию.

**Типичная проблема:** Разработчик указывает только `limits.memory: 512Mi`, ожидая Burstable. LimitRange автоматически проставляет `requests.memory = limits.memory` (512Mi), и под становится **Guaranteed** вместо Burstable. Это может привести к тому, что под не будет выселен при MemoryPressure, хотя ресурсы на узле заканчиваются.

**Обратная проблема:** Разработчик не указывает ресурсы вообще. LimitRange ставит `defaultRequest` и `default`, что формирует Burstable под с низкими запросами — такой под будет первым кандидатом на выселение.

```yaml
# LimitRange с дефолтами для namespace
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
  - type: Container
    defaultRequest:
      cpu: "100m"
      memory: "128Mi"
    default:
      cpu: "500m"
      memory: "512Mi"
    min:
      cpu: "50m"
      memory: "64Mi"
    max:
      cpu: "4"
      memory: "8Gi"
```

**Валидация:**
```bash
# Проверка LimitRange в namespace
kubectl get limitrange -n production -o yaml

# Проверка QoS класса пода
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'
```

> Подробнее: **[Управление ресурсами: QoS, LimitRange и ResourceQuota](../../../Scheduling/qos_limit_and_requests.md)**, **[Multi-tenancy](../../../Concepts/multi-tenancy.md)**.

### 12. Pod Overhead при использовании изолированных рантаймов

При использовании RuntimeClass с изолированными рантаймами (gVisor, Kata Containers) Kubernetes автоматически резервирует дополнительные ресурсы для среды выполнения. Этот overhead учитывается планировщиком при размещении Pod.

**Как это влияет на eviction:** Если под потребляет `limits.memory: 256Mi`, но overhead рантайма добавляет ещё `128Mi`, общий расход на узле — `384Mi`. Если `kubeReserved` и `systemReserved` не учтены, узел может войти в MemoryPressure раньше ожидаемого.

```yaml
# Проверка overhead для RuntimeClass
kubectl get runtimeclass gvisor -o jsonpath='{.overhead}'
# → {"cpu":"100m","memory":"128Mi"}

# Pod с overhead будет потреблять больше ресурсов на узле
# CPU: 500m (requests) + 100m (overhead) = 600m
# Memory: 256Mi (limits) + 128Mi (overhead) = 384Mi
```

> Подробнее: **[Pod Overhead](../../../Base/Pod/pod_advanced_topics.md#overhead-пода)**.

### 13. Kernel-level тюнинг узлов

Некоторые параметры ядра косвенно влияют на стабильность узлов и предотвращение eviction:

| Параметр | Влияние | Рекомендуемое значение |
|:---|:---|:---|
| `vm.max_map_count` | Лимит memory map areas (важно для Elasticsearch, Java). При исчерпании — OOM. | `262144` |
| `fs.file-max` | Общий лимит файловых дескрипторов. | `2097152` |
| `fs.inotify.max_user_watches` | Лимит отслеживания файлов (ConfigMap/Secret монтируются через inotify). | `524288` |
| `fs.inotify.max_user_instances` | Лимит inotify-очередей. | `512` |
| `kernel.pid_max` | Максимальное количество PID. | `4194304` |
| `net.core.somaxconn` | Размер очереди входящих соединений. | `65535` |

```bash
# Пример конфигурации для узла Kubernetes (/etc/sysctl.d/99-k8s-worker.conf)
vm.max_map_count = 262144
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 512
kernel.pid_max = 4194304
net.core.somaxconn = 65535
```

> Подробнее: **[sysctl: Параметры ядра](../../../../Linux/Core/kernel/sysctl.md)**, **[Лимиты ресурсов](../../../../Linux/Core/processes/resource_limits_concepts.md)**, **[Подготовка узлов](../../../Installation/kubeadm/kubeadm_installation_guide.md)**.

## Смотрите также

- **[Подробный разбор QoS и выселения](./qos_and_eviction.md)**
- **[Выселение по памяти (Memory Eviction)](./memory_eviction.md)**
- **[Выселение по диску (Disk Eviction)](./disk_eviction.md)**
- **[Бюджет прерывания подов (PDB)](../../../Autoscaling/pod_disruption_budget.md)**
- **[VPA: Вертикальное масштабирование подов](../../../Autoscaling/vpa_detailed.md)**
- **[Kubelet: Основные концепции](../../../Concepts/kubelet.md)**
- **[Обслуживание узлов (Cordon/Drain)](../../../Operations/node_maintenance.md)**
