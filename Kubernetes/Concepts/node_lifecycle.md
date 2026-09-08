# Жизненный цикл узла (Node Lifecycle)

## Определение

**Node Lifecycle** — совокупность состояний, через которые проходит узел Kubernetes на протяжении всего времени своей работы: от добавления в кластер до удаления. Управление жизненным циклом узла осуществляется **Node Lifecycle Controller** (компонент `kube-controller-manager`), который отслеживает сердцебиения (heartbeats) узлов, управляет taints и инициирует выселение подов при деградации узла.

Понимание жизненного цикла узла критично для SRE: от корректного реагирования на `NotReady` до планирования плановых работ без прерывания сервисов.

---

## Фазы жизненного цикла узла

### Добавление в кластер

При добавлении нового узла (через `kubeadm join`, API-запрос или cloud provider) kubelet:

1. Запускается на узле и регистрируется у API-сервера
2. Создаёт объект `Node` со статусом `Unknown` (временно, пока не получит heartbeat)
3. После первого heartbeat узел получает статус `NotReady`
4. После обработки Node Lifecycle Controller'ом — статус `Ready`

```bash
# Проверка текущего статуса узла
kubectl get nodes
# → NAME    STATUS     ROLES           AGE   VERSION
# → node-1  Ready      control-plane   30d   v1.30.2

# Детальный статус
kubectl describe node node-1 | grep -A5 "Conditions:"
```

### Готовность (Ready)

Узел в статусе `Ready` готов принимать поды. Controller проверяет:

- Узел отправляет heartbeat (Status Lease или NodeStatus)
- Heartbeat не старше `node-monitor-grace-period` (по умолчанию 40с)
- Все condiciones в нормальном состоянии

### Деградация (NotReady)

Если heartbeat пропущен или условия ухудшились:

1. Node Lifecycle Controller помечает узел taint `node.kubernetes.io/not-ready:NoExecute`
2. Все поды без соответствующего toleration получают `DeletionTimestamp` через `pod-eviction-timeout`
3. Узел остаётся в кластере, но поды пересоздаются на других узлах

### Автоматическое удаление (Unknown → Removed)

Если узел не восстанавливается в течение `pod-eviction-timeout` (по умолчанию 5 минут):

1. Все Pod'ы с `DeletionTimestamp` удаляются из etcd
2. Узел остаётся в статусе `Unknown` (не удаляется автоматически)
3. Для полного удаления необходимо выполнить `kubectl delete node <name>`

---

## Условия узла (Node Conditions)

Каждый узел содержит массив `status.conditions`, отражающий его текущее состояние:

| Condition | Описание | Taint |
|:---|:---|:---|
| **Ready** | Узел здоров и готов принимать поды (`True`/`False`/`Unknown`) | `node.kubernetes.io/not-ready:NoExecute` (при `False`) |
| **MemoryPressure** | Узел испытывает нехватку памяти | `node.kubernetes.io/memory-pressure:NoSchedule` |
| **DiskPressure** | Узел испытывает нехватку дискового пространства | `node.kubernetes.io/disk-pressure:NoSchedule` |
| **PIDPressure** | Узел испытывает нехватку PID | `node.kubernetes.io/pid-pressure:NoSchedule` |
| **NetworkUnavailable** | Сеть на узле не настроена (CNI) | `node.kubernetes.io/network-unavailable:NoSchedule` |

### Просмотр Conditions

```bash
# Все условия узла
kubectl get node <name> -o jsonpath='{range .status.conditions[*]}{.type}: {.status}{"\n"}{end}'
# → Ready: True
# → MemoryPressure: False
# → DiskPressure: False
# → PIDPressure: False
# → NetworkUnavailable: False

# Детально с последним изменением
kubectl describe node <name> | grep -A10 "Conditions:"
```

---

## Механизм сердцебиений (Heartbeats)

Kubelet отправляет heartbeat двумя способами:

### NodeStatus (устаревший)

- Kubelet обновляет поле `status.conditions` объекта Node
- Частота: каждые `--node-status-update-frequency` (по умолчанию 10с)
- Используется, когда Lease API отключён

### Lease API (рекомендуемый, по умолчанию)

- Kubelet создаёт объект `Lease` в namespace `kube-node-lease`
- Lease содержит только timestamp и UID (минимальный размер)
- Частота: каждые 10с (настраивается)
- Node Status обновляется реже (каждые 5 минут или при изменении conditions)

```bash
# Просмотр Lease узла
kubectl get lease -n kube-node-lease <node-name> -o yaml
# → apiVersion: coordination.k8s.io/v1
# → kind: Lease
# → spec:
# →   holderIdentity: <node-name>
# →   leaseDurationSeconds: 40
# →   renewTime: "2026-09-07T10:30:00Z"

# Просмотр всех Lease
kubectl get leases -n kube-node-lease
```

### Реакция на пропуск heartbeat

```
Kubelet перестал отправлять heartbeat
    ↓
40с (node-monitor-grace-period)
    ↓
Node Lifecycle Controller помечает узел NotReady
    ↓
Taint: node.kubernetes.io/not-ready:NoExecute
    ↓
5мин (pod-eviction-timeout, по умолчанию)
    ↓
Pod'ы получают DeletionTimestamp и удаляются
    ↓
Поды пересоздаются на здоровых узлах
```

---

## Taints и Conditions

Node Lifecycle Controller автоматически управляет taints на основе conditions:

### Автоматические taints

| Condition | Taint | Эффект |
|:---|:---|:---|
| Ready=False | `node.kubernetes.io/not-ready` | NoExecute |
| Ready=Unknown | `node.kubernetes.io/unreachable` | NoExecute |
| MemoryPressure=True | `node.kubernetes.io/memory-pressure` | NoSchedule |
| DiskPressure=True | `node.kubernetes.io/disk-pressure` | NoSchedule |
| PIDPressure=True | `node.kubernetes.io/pid-pressure` | NoSchedule |
| NetworkUnavailable=True | `node.kubernetes.io/network-unavailable` | NoSchedule |

### Различия между NoSchedule и NoExecute

| Эффект | Поведение | Влияние на существующие Pod'ы |
|:---|:---|:---|
| **NoSchedule** | Новые Pod'ы не планируются на узел | Существующие Pod'ы **не затрагиваются** |
| **NoExecute** | Новые Pod'ы не планируются + существующие Pod'ы выселены | Существующие Pod'ы **выселяются** через `pod-eviction-timeout` (если нет toleration с `tolerationSeconds`) |

### Toleration для taints conditions

```yaml
# Под tolerates not-ready taint на 5 минут (продолжит работу после потери heartbeat)
tolerations:
- key: "node.kubernetes.io/not-ready"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 300

# Под tolerates unreachable taint на 10 минут
tolerations:
- key: "node.kubernetes.io/unreachable"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 600
```

---

## Выселение подов (Eviction)

### Node-Pressure Eviction (kubelet)

Kubelet непрерывно мониторит ресурсы узла и инициирует выселение при достижении порогов:

```
Порог ресурсов достигнут
    ↓
Kubelet определяет Pod-жертву (QoS: BestEffort → Burstable → Guaranteed)
    ↓
Kubelet отправляет eviction request через Eviction API
    ↓
Pod получает Grace Period (10с для Hard, настраивается для Soft)
    ↓
Pod удаляется (SIGTERM → SIGKILL)
```

### Пороги выселения

| Ресурс | Hard порог | Soft порог | Время ожидания |
|:---|:---|:---|:---|
| `memory.available` | `< 100Mi` | `< 200Mi` | `--eviction-soft-grace-period` |
| `nodefs.available` | `< 10%` | `< 15%` | `--eviction-soft-grace-period` |
| `imagefs.available` | `< 15%` | `< 20%` | `--eviction-soft-grace-period` |
| `nodefs.inodesFree` | `< 5%` | `< 10%` | `--eviction-soft-grace-period` |

### Hard vs Soft Eviction

| Характеристика | Hard Eviction | Soft Eviction |
|:---|:---|:---|
| **Триггер** | Порог превышен | Порог превышен дольше grace-period |
| **Действие** | Немедленное удаление | Удаление после grace-period |
| **Grace Period** | Нет (0с) | Настраивается |
| **PDB** | Не учитывается | Учитывается (для подов с PDB) |

### Порядок выселения по QoS

Kubelet удаляет Pod'ы в следующем порядке:

1. **BestEffort** — Pod'ы без requests/limits (самые низкоприоритетные)
2. **Burstable** — Pod'ы с requests < limits
3. **Guaranteed** — Pod'ы с requests = limits (выселяются последними)

> **Важно:** Guaranteed Pod'ы выселяются только при критической нехватке ресурсов (Memory < 100Mi). Kubelet сам защищён от выселения (oom_score_adj = -999).

---

## Graceful Node Shutdown

Kubernetes поддерживает корректное завершение работы узла через интеграцию с systemd-logind:

### Механизм (K8s 1.21+)

1. Оператор выполняет `systemctl stop kubelet`
2. kubelet запускает **graceful shutdown** (terminate критических подов)
3. kubelet отправляет heartbeat с `node.kubernetes.io/unschedulable:NoExecute`
4. Pod'ы получают `DeletionTimestamp` и завершают работу

### Настройка

```yaml
# /var/lib/kubelet/config.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
shutdownGracePeriodSeconds: 300        # Общее время на graceful shutdown
shutdownGracePeriodCriticalPods: 100   # Время для критических подов (system-*)
```

### Порядок завершения

```
shutdownGracePeriodSeconds (300с)
├── Обычные Pod'ы: 200с (66.6%)
│   ├── SIGTERM
│   ├── terminationGracePeriodSeconds
│   └── Удаление
└── Критические Pod'ы: 100с (33.3%)
    ├── SIGTERM
    ├── terminationGracePeriodSeconds
    └── Удаление
```

---

## Практические сценарии

### Мониторинг состояния узлов

```bash
# Все узлы с их статусами и conditions
kubectl get nodes -o custom-columns=\
NAME:.metadata.name,\
STATUS:.status.conditions[-1].type,\
READY:.status.conditions[?(@.type=="Ready")].status,\
MEMORY_P:.status.conditions[?(@.type=="MemoryPressure")].status,\
DISK_P:.status.conditions[?(@.type=="DiskPressure")].status

# Узлы с taints
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Поды на конкретном узле
kubectl get pods --all-namespaces --field-selector spec.nodeName=<node-name>

# Ресурсы узла
kubectl describe node <name> | grep -A10 "Allocated resources"
```

### Плановые работы (Cordon/Drain)

```bash
# Запретить планирование подов на узел
kubectl cordon <node-name>

# Безопасное удаление подов с узла
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=60 \
  --force=false

# После работ — вернуть узел в рабочее состояние
kubectl uncordon <node-name>
```

### Диагностика NotReady узла

```bash
# 1. Проверить статус kubelet
ssh <node> "systemctl status kubelet"

# 2. Проверить логи kubelet
ssh <node> "journalctl -u kubelet --since '10 minutes ago' --no-pager"

# 3. Проверить доступность API-сервера
ssh <node> "kubectl cluster-info"

# 4. Проверить CRI-рантайм
ssh <node> "systemctl status containerd"

# 5. Проверить disk/memory
ssh <node> "df -h && free -h"

# 6. Проверить PLEG (Pod Lifecycle Event Generator)
ssh <node> "journalctl -u kubelet | grep -i pleg"

# 7. Проверить heartbeat
kubectl get lease -n kube-node-lease <node-name> -o jsonpath='{.spec.renewTime}'
```

### Алертинг на здоровье узлов

```yaml
groups:
- name: node-health
  rules:
  - alert: NodeNotReady
    expr: kube_node_status_condition{condition="Ready",status="true"} == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Node {{ $labels.node }} is NotReady"

  - alert: NodeMemoryPressure
    expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Node {{ $labels.node }} has memory pressure"

  - alert: NodeDiskPressure
    expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Node {{ $labels.node }} has disk pressure"

  - alert: NodePIDPressure
    expr: kube_node_status_condition{condition="PIDPressure",status="true"} == 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Node {{ $labels.node }} has PID pressure"
```

---

## Дополнительная информация

*   **[Taints and Tolerations](../Scheduling/taints_and_tolerations.md)** — теория taints, все эффекты, стандартные taints
*   **[QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md)** — классы QoS, приоритеты выселения
*   **[Diagnosing Node Unavailability](../Troubleshooting/Common_Errors/NodeUnavailability/diagnostics.md)** — пошаговая диагностика NotReady
*   **[Taint-based Eviction](../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md)** — глубокий разбор механизма выселения
*   **[Resource Pressure](../Troubleshooting/Common_Errors/NodeUnavailability/resource_pressure.md)** — MemoryPressure, DiskPressure, PIDPressure
*   **[Node Maintenance](../Operations/node_maintenance.md)** — cordon, drain, повседневные операции
