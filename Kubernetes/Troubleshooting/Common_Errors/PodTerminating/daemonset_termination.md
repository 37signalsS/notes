# Pod Terminating — DaemonSet и завершение подов

## Определения

**DaemonSet** — объект API (`apps/v1`), гарантирующий запуск экземпляра Pod на каждом (или отфильтрованном по `nodeSelector`/`tolerations`) узле кластера. Используется для системных агентов: kube-proxy, CNI-плагины (Calico, Cilium), сборщики логов (Fluent Bit), мониторинг (node-exporter), хранение (Longhorn, Rook-Ceph). При добавлении нового узла контроллер DaemonSet автоматически создаёт Pod на этом узле; при удалении узла — удаляет соответствующий Pod.

**Особенность завершения** — в отличие от Deployment, контроллер DaemonSet **не пересоздаёт** Pod на другом узле при завершении на текущем. Pod привязан к конкретному узлу, и его удаление не триггерит создание замены на здоровом узле. Если узел недоступен, Pod остаётся в `Terminating` до снятия финализаторов или удаления объекта Node из API.

**Pod Disruption Budget (PDB) не применяется к DaemonSet** — PDB защищает только поды, управляемые ReplicaSet/StatefulSet. DaemonSet-поды не защищены PDB, что означает: при `kubectl drain` с `--ignore-daemonsets=false` поды DaemonSet удаляются принудительно, даже если это нарушит доступность сервиса.

**Узел-привязка (Node Affinity)** — DaemonSet-под всегда запускается на конкретном узле. При `kubectl drain` под не может «переехать» на другой узел — он либо завершается корректно, либо удаляется принудительно. Это принципиальное отличие от Deployment, где поды мобильны.

---

## Базовые концепции

### Порядок завершения подов при kubectl drain

При выводе узла из эксплуатации (`kubectl drain`) контроллер следует строгому порядку:

```
kubectl drain <node>
    ↓
1. kubectl cordon <node> (пометка непригодным для новых подов)
    ↓
2. Эвикция подов, управляемых ReplicaSet/Deployment (с проверкой PDB)
    ↓
3. Если --ignore-daemonsets=false:
   → Удаление подов DaemonSet через Eviction API (без PDB)
    ↓
4. Если --ignore-daemonsets=true (по умолчанию):
   → Поды DaemonSet ИГНОРИРУЮТСЯ и остаются на узле
    ↓
5. Ожидание завершения всех eviction (--timeout)
    ↓
6. Узел считается выведенным из эксплуатации
```

### Различия завершения Deployment vs DaemonSet

| Характеристика | Deployment | DaemonSet |
| :--- | :--- | :--- |
| **PDB** | Защищает от eviction | **Не применяется** |
| **Пересоздание на другом узле** | Да (ReplicaSet создаёт новый под) | **Нет** (привязан к узлу) |
| **kubectl drain** | Эвикция с проверкой PDB | Удаление с `--ignore-daemonsets` |
| **Обновление (RollingUpdate)** | `maxSurge` + `maxUnavailable` | Только `maxUnavailable` (Beta v1.28+) |
| **Graceful Shutdown** | Стандартный (preStop + SIGTERM) | Стандартный, но зависит от kubelet на узле |
| **Недоступность узла** | Под пересоздаётся на другом узле | Под остаётся в Terminating до снятия финализаторов |

### Причины зависания DaemonSet в Terminating

| Причина | Механизм | Диагностика |
| :--- | :--- | :--- |
| **Узел недоступен** | Kubelet не может подтвердить завершение | `kubectl get node <name> -o jsonpath='{.status.conditions}'` |
| **Финализатор** | Системный или кастомный финализатор блокирует удаление | `kubectl get pod <name> -o jsonpath='{.metadata.finalizers}'` |
| **preStop hook завис** | Хук выполняется дольше `terminationGracePeriodSeconds` | `kubectl describe pod <name> \| grep -A 5 Events` |
| **Zombie/D-state процессы** | Процессы блокируют завершение контейнера | `ssh <node> 'ps -eo pid,stat,args \| awk "$2~/[DZ]/"'` |
| **Том не размонтируется** | CSI/Volume ошибки при unmount | `kubectl describe pod <name> \| grep -i unmount` |
| **Сетевой плагин** | CNI-плагин (Calico, Cilium) не может очистить сеть | Проверьте поды CNI в `kube-system` |

### Взаимодействие с kubectl drain

```bash
# По умолчанию: DaemonSet поды ИГНОРИРУЮТСЯ
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
# → WARNING: ignoring DaemonSet-managed pods: kube-flannel-xxxxx, kube-proxy-xxxxx
# → Поды DaemonSet остаются на узле

# Принудительное удаление DaemonSet подов (опасно!)
kubectl drain <node> --ignore-daemonsets=false --delete-emptydir-data
# → Все поды DaemonSet будут удалены (включая kube-proxy, CNI)
# → Узел потеряет сетевую связность и ability обрабатывать трафик
```

---

## Практические сценарии

### Быстрый чек-лист диагностики

```bash
# 1. Все DaemonSet поды на проблемном узле
kubectl get pods -A -o wide | grep <node-name> | grep -v kube-system
# Альтернатива: найти поды DaemonSet по label
kubectl get pods -A -l name=<daemonset-name> -o wide | grep <node-name>

# 2. Проверка статуса DaemonSet
kubectl get daemonset -A
# → Ищите DESIRED == CURRENT == READY == UP-TO-DATE
# → Если CURRENT != READY — проблемы с подами

# 3. Проверка финализаторов
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.nodeName == "<node-name>" and .metadata.deletionTimestamp != null) | "\(.metadata.namespace)/\(.metadata.name) finalizers=\(.metadata.finalizers)"'

# 4. Events узла (ищите taints и eviction)
kubectl describe node <node-name> | grep -A 20 "Taints:"

# 5. Состояние kubelet на узле
ssh <node> 'systemctl status kubelet --no-pager | head -20'
```

### Сценарий 1: Плановое обслуживание узла с DaemonSet

**Ситуация:** Нужно вывести узел для обновления ОС/замен дисков. На узле работают DaemonSet-поды (kube-proxy, Calico node, node-exporter).

**Решение:**

```bash
# 1. Проверьте, какие DaemonSet-поды работают на узле
kubectl get pods -A -o wide | grep <node-name>
# Пример:
#   kube-system    kube-proxy-abc12         1/1  Running  0  5d  <node-name>
#   kube-system    calico-node-xyz78        1/1  Running  0  5d  <node-name>
#   monitoring     node-exporter-def456     1/1  Running  0  5d  <node-name>

# 2. Выведите узел из эксплуатации (DaemonSet поды будут проигнорированы)
kubectl cordon <node-name>
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=60 \
  --timeout=300s

# 3. Выполните обслуживание на узле...

# 4. Верните узел в строй
kubectl uncordon <node-name>

# 5. Проверьте, что DaemonSet-поды восстановились
kubectl get pods -A -o wide | grep <node-name>
```

### Сценарий 2: DaemonSet-под завис на недоступном узле

**Ситуация:** Узел вышел из строя (Hardware failure). DaemonSet-под в `Terminating`, но Kubelet не может подтвердить завершение.

**Решение:**

```bash
# 1. Пометьте узел как гарантированно недоступный (K8s 1.24+)
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=NoExecute:NoExecute

# 2. Дождитесь автоматического удаления финализаторов
#    Контроллер DaemonSet удалит под и пересоздаст его на другом узле
#    (если на другом узле нет DaemonSet-пода с тем же label)
kubectl get pods -A -o wide | grep <daemonset-name>

# 3. Проверьте, что под появился на другом узле
kubectl get pods -A -o wide | grep <daemonset-name>
# Пример:
#   kube-system   kube-proxy-abc12   1/1  Running  0  30s   node-2

# 4. Удалите taint перед возвращением узла
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service-
```

### Сценарий 3: Принудительное удаление DaemonSet-пода

**Ситуация:** DaemonSet-под завис, `out-of-service` taint не помогает (узел частично доступен, kubelet работает, но под не завершается).

**Решение:**

```bash
# 1. Определите причину зависания
kubectl describe pod <pod-name> -n <namespace> | grep -A 20 Events
# → FailedPreStopHook? FailedUnmount? Unhealthy?

# 2. Если kubelet доступен — принудительное удаление
kubectl delete pod <pod-name> -n <namespace> --force --grace-period=0
# → Под будет убит по SIGKILL немедленно

# 3. Если kubelet НЕ доступен — удалите финализаторы
kubectl patch pod <pod-name> -n <namespace> \
  -p '{"metadata":{"finalizers":null}}' --type=merge
# → Под удалён из API, kubelet (если восстановится) очистит ресурсы

# 4. Если нужно ускорить пересоздание на другом узле
#    (DaemonSet-под НЕ пересоздаётся автоматически — узел должен стать NotReady)
kubectl get node <node-name> -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → Если Ready=True, под НЕ будет пересоздан на другом узле
# → Решение: пометьте узел taint: kubectl taint nodes <node-name> node.kubernetes.io/unreachable:NoExecute
```

### Сценарий 4: Обновление DaemonSet (RollingUpdate)

**Ситуация:** Нужно обновить DaemonSet (новая версия образа) без простоя сервиса.

**Механизм:**

DaemonSet поддерживает `RollingUpdate` (с K8s 1.21+, стабильно с 1.22). В отличие от Deployment, `maxSurge` **не поддерживается** — лишние экземпляры создавать нельзя, так как под привязан к узлу. Используется только `maxUnavailable`:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1  # Один под обновляется за раз
  template:
    spec:
      containers:
      - name: node-exporter
        image: prom/node-exporter:v1.7.0
```

**Порядок обновления:**

```
1. Контроллер выбирает узел для обновления
2. Удаляет старый Pod (с учётом terminationGracePeriodSeconds)
3. Ожидает удаления старого Pod
4. Создаёт новый Pod с обновлённым шаблоном
5. Ожидает прохождения readinessProbe
6. Переходит к следующему узлу
```

**Диагностика зависшего обновления:**

```bash
# Проверка статуса обновления
kubectl get daemonset <name> -o jsonpath='{
  Desired:  {.status.desiredNumberScheduled}
  Current:  {.status.currentNumberScheduled}
  Ready:    {.status.numberReady}
  Updated:  {.status.updatedNumberScheduled}
  Available:{.status.numberAvailable}
  Misscheduled: {.status.numberMisscheduled}
}'
# → Если Updated < Desired — обновление не завершено

# Поиск подов, которые блокируют обновление
kubectl get pods -l name=<daemonset-name> -o json | \
  jq -r '.items[] | select(.metadata.deletionTimestamp != null) | "\(.metadata.name) stuck in terminating"'

# Проверка, что новый образ доступен на узлах
kubectl get pods -l name=<daemonset-name> -o json | \
  jq -r '.items[] | "\(.spec.nodeName): \(.spec.containers[0].image) ready=\(.status.conditions[] | select(.type=="Ready") | .status)"'
```

### Сценарий 5: DaemonSet-контроллер не может создать под

**Ситуация:** На новом узле не появляется DaemonSet-под, хотя узел в статусе `Ready`.

**Диагностика:**

```bash
# 1. Проверьте, что узел соответствует nodeSelector/affinity DaemonSet
kubectl get node <node-name> --show-labels | tr ',' '\n' | grep -E "role|node"
kubectl get daemonset <name> -o jsonpath='{.spec.template.spec.nodeSelector}'
# → Совпадают ли метки?

# 2. Проверьте taints на узле
kubectl describe node <node-name> | grep -A 5 Taints
# → Если есть taint без toleration в DaemonSet — под не запустится

# 3. Проверьте, нет ли конфликта с существующим подом
kubectl get pods -l name=<daemonset-name> -o wide | grep <node-name>
# → Если под есть, но в Terminating — он блокирует создание нового

# 4. Проверьте DaemonSet events
kubectl describe daemonset <name> | grep -A 20 Events
# → FailedCreate? FailedPlacement?

# 5. Проверьте.scheduler (если под в Pending)
kubectl get events --field-selector reason=FailedScheduling --sort-by='.lastTimestamp'
```

---

## Дополнительная информация

### DaemonSet и Graceful Node Shutdown

DaemonSet-поды участвуют в `Graceful Node Shutdown` (K8s 1.21+). При выключении узла через `systemctl poweroff` kubelet завершает поды по приоритетам:

```yaml
# kubelet configuration
shutdownGracePeriod: 30s
shutdownGracePeriodCriticalPods: 10s
```

Важно: DaemonSet-поды, такие как `kube-proxy` и CNI-плагины, являются критическими для сети. Если они завершаются слишком быстро (или `terminationGracePeriodSeconds: 0`), узел потеряет сетевую связность до завершения остальных подов.

### DaemonSet и ResourceQuota

Pod'ы DaemonSet **не учитываются** в `ResourceQuota` (квота не блокирует создание DaemonSet-подов). Это сделано намеренно: DaemonSet — системный компонент, и его поды не должны блокироваться бизнес-квотами.

### DaemonSet и Cluster Autoscaler

Cluster Autoscaler **не может** удалить узел, на котором работают DaemonSet-поды (если `--ignore-daemonsets=true`). Это может привести к ситуации, когда CA не может уменьшить кластер, потому что DaemonSet-поды занимают узлы. Решение: используйте `--ignore-daemonsets=true` (по умолчанию) и убедитесь, что DaemonSet-поды не мешают CA масштабировать вниз.

### Monиторинг DaemonSet-подов

```promql
# Все DaemonSet-поды, не готовые (Ready=False)
kube_daemonset_status_number_ready{namespace="kube-system"}
  != kube_daemonset_status_desired_number_scheduled{namespace="kube-system"}

# DaemonSet-поды в Terminating (зависимые от узла)
kube_pod_status_phase{phase="Terminating"}
  and on(pod, namespace)
  kube_ownerref_owner{owner_kind="DaemonSet"} > 0

# Количество подов DaemonSet на каждом узле
count by (node) (
  kube_pod_info * on(pod, namespace) group_left()
  kube_ownerref_owner{owner_kind="DaemonSet"}
)
```

### Связанные команды kubectl

| Команда | Назначение |
| :--- | :--- |
| `kubectl get daemonset -A` | Все DaemonSet в кластере |
| `kubectl describe daemonset <name>` | Статус, conditions, events |
| `kubectl get pods -l name=<ds-name> -o wide` | Поды конкретного DaemonSet |
| `kubectl get pods -A -o wide \| grep <node>` | Все поды на конкретном узле |
| `kubectl drain <node> --ignore-daemonsets` | Вывод узла (DaemonSet игнорируются) |
| `kubectl drain <node> --ignore-daemonsets=false` | Вывод узла с удалением DaemonSet |
| `kubectl cordon <node>` | Пометка узла непригодным |
| `kubectl uncordon <node>` | Возврат узла в строй |
| `kubectl taint nodes <node> node.kubernetes.io/out-of-service=NoExecute:NoExecute` | Пометка недоступного узла |

---

**См. также:**
- [Определения Pod Terminating](./definitions.md) — базовые термины и механизмы.
- [Graceful Shutdown](./graceful_shutdown.md) — настройка периодов завершения и preStop.
- [Диагностика Pod Terminating](./diagnostics.md) — общий алгоритм поиска причин.
- [Недоступность узла](./node_unavailable_issues.md) — действия при отказе инфраструктуры.
- [Блокировка через PDB](./pdb_blocking.md) — PDB не применяется к DaemonSet.
- [Управление жизненным циклом Deployment](../../../Base/Deployment/lifecycle_management.md) — сравнение с RollingUpdate.
