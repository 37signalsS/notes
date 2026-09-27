# Pod в состоянии `Pending`: Вопросы для собеседования

---

## Определения

**Интервью-вопросы по Pending** — подготовленные вопросы и ответы, покрывающие типичные сценарии диагностики, планирования и устранения проблем с Pod в состоянии Pending на позициях DevOps/SRE/sysadmin. Вопросы сгруппированы по тематике и уровню сложности.

---

## Базовый уровень

### 1. Что означает статус Pending у Pod?

**Ответ:** Pod принят API-сервером, но один или несколько контейнеров не перешли в состояние `Running`. Существует три подсостояния:
- **Unscheduled** — планировщик не назначил узел (`spec.nodeName` пустое)
- **SchedulingGated** — Pod удерживается механизмом Scheduling Gates (v1.30+)
- **Scheduled / ContainerCreating** — узел назначен, но запуск контейнеров заблокирован

**Ключевой момент:** Статус Pending ≠ ошибка. Это фаза жизненного цикла, которая может быть нормальной (ожидание ресурсов, инициализация).

### 2. Как диагностировать Pending Pod за 5 минут?

**Ответ:**
```bash
# 1. Найти Pending поды
kubectl get pods -A --field-selector status.phase=Pending

# 2. Определить этап (назначен ли узел)
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}'
# → пусто = Unscheduled, имя узла = Scheduled

# 3. Получить событие планирования
kubectl describe pod <pod-name> | grep -A 5 "Events:"
```

Если `Node: <none>` — проблема в планировщике. Если узел назначен — проблема на узле (init-контейнеры, тома, CNI).

### 3. Какие основные причины Pending?

**Ответ (по частоте):**
| Причина | Симптом |
|---------|---------|
| Нехватка CPU/RAM | `Insufficient cpu/memory` |
| Taints/Tolerations | `had taint {...}, that pod didn't tolerate` |
| Affinity/Topology | `didn't match node affinity/selector` |
| ResourceQuota | `exceeded quota` |
| PVC не привязан | `pod has unbound immediate PersistentVolumeClaims` |
| Scheduling Gates | `SchedulingGated` в статусе |

### 4. В чём разница между `requests` и `limits` для планирования?

**Ответ:** Планировщик работает с `requests` (гарантированные ресурсы), а не с `limits` (максимум). Pod с `requests: cpu=1000m` требует 1 ядро, даже если `limits: cpu=2000m`. Если `requests` превышают доступные ресурсы узла — Pod будет Pending.

---

## Средний уровень

### 5. Pod назначён на узел, но висит в Pending. Как диагностировать?

**Ответ:** Проверяйте вектор "Запуск на узле":
```bash
# Init-контейнеры
kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*]}'
kubectl logs <pod> -c <init-container>

# Тома
kubectl describe pod <pod> | grep -E "MountVolume|AttachVolume"
kubectl get pvc -n <namespace>

# CNI/Sandbox
kubectl get pod <pod> -o jsonpath='{.status.conditions[?(@.type=="PodReadyToStartContainers")]}'

# Node Pressure
kubectl describe node <node> | grep -A 10 "Conditions:"
```

### 6. Что такое Scheduling Gates и когда они используются?

**Ответ:** Scheduling Gates (GA v1.30) — механизм удержания Pod в Pending до завершения внешних проверок. Планировщик полностью игнорирует такие Pod (в отличие от `Unschedulable`).

**Диагностика:**
```bash
kubectl get pod <pod> -o jsonpath='{.spec.schedulingGates}'
kubectl get pod <pod> -o jsonpath='{.status.conditions[?(@.type=="PodScheduled")]}'
```

**Типичные сценарии:** Gatekeeper/Kyverno ожидание admission policy, кастомный контроллер подготовки данных.

### 7. Как работает preemption и почему он может не помочь?

**Ответ:** Если Pod с высоким приоритетом не может быть запланирован, планировщик ищет Pod с более низким приоритетом для удаления. Но:
- **PDB** может блокировать удаление (по умолчанию preemption игнорирует PDB, но с v1.21+ настраивается)
- **Нет Pod с более низким приоритетом** — нечего вытеснять
- **Каскадное вытеснение** — удаление Pod вызывает цепную реакцию Pending

### 8. Как Cluster Autoscaler реагирует на Pending Pod?

**Ответ:** CA масштабирует кластер **только** для Pod с причиной `Unschedulable`. CA:
- Сканирует каждые 10 секунд
- Симулирует логику планировщика
- Запрашивает добавление узла через Cloud API
- Ожидает 3-10 минут

**Не масштабирует для:** SchedulingGated, ResourceQuota (Pod не доходит до планировщика).

### 9. Что такое ресурсная фрагментация и как она влияет на Pending?

**Ответ:** Ситуация, когда суммарно ресурсов на узлах достаточно, но ни один узел не подходит из-за granular requests. Пример:
- Узел A: 1Gi RAM свободно, узел B: 1Gi RAM свободно
- Pod требует 1.5Gi RAM → Pending, хотя суммарно 2Gi доступно

**Решения:** Right-sizing requests, bin-packing (MostRequestedPriority), VPA.

### 10. Как влияет `system-reserved` и `kube-reserved` на планирование?

**Ответ:** Формула Allocatable:
```
Allocatable = Node Capacity - kube-reserved - system-reserved - eviction-threshold
```
Планировщик работает с Allocatable, а не с Capacity. Если на узле 16Gi RAM, но `kube-reserved=1Gi` + `system-reserved=2Gi` + `eviction-threshold=1Gi`, то Allocatable = 12Gi. Pod с `requests: 13Gi` будет Pending.

---

## Продвинутый уровень

### 11. Pod Security Admission (PSA) может блокировать Pod. Как диагностировать?

**Ответ:** PSA отклоняет Pod на уровне admission (до планирования). Симптом: Pod в Pending без событий `FailedScheduling`.

```bash
# Проверка PSA-меток namespace
kubectl get ns <namespace> -o jsonpath='{.metadata.labels}'
# → pod-security.kubernetes.io/enforce: restricted

# Проверка events на admission errors
kubectl get events --field-selector reason=FailedCreate --sort-by='.lastTimestamp'

# Проверка securityContext Pod
kubectl get pod <pod> -o jsonpath='{.spec.securityContext}'
```

**Решение:** Добавить `securityContext` в Pod (runAsNonRoot, allowPrivilegeEscalation=false, capabilities.drop) или ослабить PSA на namespace.

### 12. Admission Webhook может блокировать Pod. Как отличить от проблемы планировщика?

**Ответ:** Ключевое различие:
- **Проблема планировщика:** `kubectl describe pod` показывает `Events: FailedScheduling`
- **Admission Webhook:** Pod может не создаться вообще, или быть в Pending без событий планировщика

```bash
# Проверка ошибок admission webhook
kubectl get events --field-selector reason=FailedCreate --sort-by='.lastTimestamp'
# → Warning  FailedCreate  ... admission webhook "..." denied the request: ...

# Проверка ValidatingWebhookConfiguration
kubectl get validatingwebhookconfigurations
kubectl get mutatingwebhookconfigurations
```

### 13. ServiceAccount может вызвать Pending. Как диагностировать?

**Ответ:** Несколько сценариев:
1. **Отсутствует ServiceAccount:** Pod создаётся с `automountServiceAccountToken: true`, но SA не существует
2. **Secret SA не создан:** kubelet не может смонтировать токен
3. **RBAC:** SA существует, но не имеет прав на required ресурсы

```bash
# Проверка SA
kubectl get sa <sa-name> -n <namespace>
kubectl get sa <sa-name> -n <namespace> -o jsonpath='{.secrets}'

# Проверка событий монтирования
kubectl describe pod <pod> | grep -A 5 "Events:"
# → Warning  FailedMount  ... secret "xxx" not found
```

### 14. Как container runtime (containerd/CRI-O) влияет на Pending?

**Ответ:** Если Pod назначен на узел, но CRI не работает:
```bash
# Проверка CRI
ssh <node> "crictl info"
ssh <node> "systemctl status containerd"

# Проверка логов kubelet
ssh <node> "journalctl -u kubelet --since '10 minutes ago' | grep -i 'cri\|runtime'"

# Проверка sandbox
ssh <node> "crictl pods | grep <pod-name>"
```

**Типичные ошибки:** CRI socket недоступен, version mismatch между kubelet и CRI, CNI не установлен.

### 15. Как kube-proxy влияет на Pending Pod?

**Ответ:** kube-proxy напрямую не блокирует планирование, но может косвенно влиять:
- При большом количестве сервисов (>5000) kube-proxy тормозит обновление iptables/ipvs
- Pod в Running не может достучаться до сервисов → readiness probe падает → Pod не готов
- Это создаёт видимость "зависания", хотя формально Pod в Running

```bash
# Проверка времени обновления правил
ssh <node> "iptables -L -n | wc -l"
ssh <node> "ipvsadm -L -n | wc -l"

# Проверка latency kube-proxy
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=50
```

### 16. Как NetworkPolicy может привести к Pending?

**Ответ:** NetworkPolicy не блокирует планирование, но:
- **CNI не может выделить IP** если Policy блокирует трафик между Pod и CNI-плагином
- **DNS не работает** → readiness probe падает → Pod не проходит health check
- **Admission webhook CNI** (Cilium, Calico) может отклонять Pod

```bash
# Проверка DNS
kubectl exec <pod> -- nslookup kubernetes.default
# Проверка NetworkPolicy
kubectl get networkpolicy -n <namespace>
```

### 17. Многозонный кластер (multi-AZ): типичные проблемы Pending

**Ответ:** Zonal Mismatch — PVC привязан к зоне A, но Pod планируется в зону B:
```bash
# Проверка зоны PVC
kubectl get pvc <pvc> -o jsonpath='{.spec.storageClassName}'
kubectl get sc <sc> -o jsonpath='{.volumeBindingMode}'
# → WaitForFirstConsumer (правильно) или Immediate (риск)

# Проверка зоны Pod
kubectl get pod <pod> -o jsonpath='{.spec.nodeName}'
kubectl get node <node> -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}'
```

**Решение:** `volumeBindingMode: WaitForFirstConsumer` + согласование `nodeSelector`.

### 18. Karpenter vs Cluster Autoscaler: как влияют на Pending?

**Ответ:**
| Параметр | Cluster Autoscaler | Karpenter |
|----------|-------------------|-----------|
| Триггер | Pod с `Unschedulable` | Pod с `Unschedulable` |
| Логика | Добавляет узлы в существующие группы | Создаёт узлы "под" Pod |
| Скорость | 3-10 минут | 30-60 секунд |
| Spot | Группы узлов | Динамический приоритет |
| Consolidation | Нет | Да (перемещение Pod) |

---

## Кейсы для собеседования

### Кейс 1: Pod Pending после деплоя через Helm

**Ситуация:** После `helm upgrade` Pod в Pending. `kubectl describe pod` показывает `0/5 nodes are available: 5 Insufficient cpu`.

**Вопрос:** Что проверить?

**Ответ:**
1. `kubectl describe nodes | grep -A 5 "Allocated resources"` — проверить загрузку узлов
2. `kubectl get resourcequota -n <namespace>` — проверить квоты
3. Сравнить `requests` Pod с доступными ресурсами
4. Проверить, не изменились ли `requests` в новой версии Helm-чарта
5. При необходимости: уменьшить `requests` или добавить узлы

### Кейс 2: Pod Pending без событий ошибок

**Ситуация:** Pod в Pending, но `kubectl describe pod` не показывает событий `FailedScheduling`.

**Вопрос:** Какова вероятная причина?

**Ответ:**
1. Scheduling Gates — `kubectl get pod <pod> -o jsonpath='{.spec.schedulingGates}'`
2. ResourceQuota — `kubectl describe quota -n <namespace>` (если квота исчерпана, Pod не доходит до планировщика)
3. Admission Webhook — `kubectl get events --field-selector reason=FailedCreate`
4. PSA — проверить labels namespace

### Кейс 3: Rolling Update зависает

**Ситуация:** Deployment с 5 репликами и `topologySpreadConstraints` обновляется, но новые Pod не могут запланироваться.

**Вопрос:** Что произошло и как исправить?

**Ответ:**
- **Проблема:** Rolling Update Deadlock — старые Pod ( ReplicaSet v1) занимают все домены, новые Pod (ReplicaSet v2) не могут соблюсти `maxSkew`
- **Решение:** Добавить `matchLabelKeys: [pod-template-hash]` в `topologySpreadConstraints`
- **Временное:** `whenUnsatisfiable: ScheduleAnyway` или увеличить `maxSkew`

### Кейс 4: Pod Pending на spot-узлах

**Ситуация:** Pod не запускается на spot-узлах. В событиях: `had taint {spot-instance: true}, that pod didn't tolerate`.

**Вопрос:** Как решить?

**Ответ:**
1. Добавить `tolerations` в Pod:
```yaml
tolerations:
- key: "spot-instance"
  value: "true"
  effect: "NoSchedule"
```
2. Или использовать `nodeSelector` для выбора on-demand узлов
3. Для критических сервисов: использовать `PriorityClass` + `preemptionPolicy` для вытеснения

### Кейс 5: DaemonSet Pod Pending на одном узле

**Ситуация:** DaemonSet работает на 9 узлах из 10. На одном узле Pod в Pending.

**Вопрос:** Как диагностировать?

**Ответ:**
1. `kubectl describe node <node>` — проверить taints, conditions (MemoryPressure, DiskPressure)
2. `kubectl describe daemonset <ds>` — проверить, почему Pod не создан
3. Если узел имеет `taint` без соответствующего `toleration` — Pod не будет создан
4. Если `MemoryPressure=True` — kubelet не запустит контейнеры DaemonSet
5. DaemonSet автоматически добавляет `toleration` для `node.kubernetes.io/unschedulable:NoSchedule`, но не для других taints

---

## Полезные команды для собеседований

| Задача | Команда |
|--------|---------|
| **Все Pending поды** | `kubectl get pods -A --field-selector status.phase=Pending` |
| **Назначен ли узел** | `kubectl get pod <pod> -o jsonpath='{.spec.nodeName}'` |
| **Причина Pending** | `kubectl describe pod <pod> \| grep -A 10 Events` |
| **Квоты** | `kubectl describe quota -n <ns>` |
| **Ресурсы узлов** | `kubectl describe nodes \| grep -A 5 "Allocated resources"` |
| **Taints** | `kubectl get nodes -o json \| jq '.items[] \| {name:.metadata.name, taints:.spec.taints}'` |
| **PDB** | `kubectl get pdb -A` |
| **StorageClass** | `kubectl get sc` |
| **Scheduling Gates** | `kubectl get pods -A -o json \| jq '.items[] \| select(.spec.schedulingGates != null)'` |
| **PSA метки** | `kubectl get ns <ns> -o jsonpath='{.metadata.labels}'` |

---

## Связанные ресурсы

- **[Определения и концепции](./definitions_and_concepts.md)** — базовые термины и архитектура.
- **[Распространенные случаи](./common_cases_and_solutions.md)** — практические решения.
- **[Диагностика](./diagnostics.md)** — алгоритмы поиска неисправностей.
- **[Продвинутые темы](./advanced_topics.md)** — Scheduling Gates, DRA, Gang Scheduling.
- **[Pod Security Context](../../../Security/pod_security_context.md)** — PSA и безопасность Pod.
- **[Admission Controllers](../../../Concepts/admission_controllers.md)** — вебхуки admission.
- **[Kubelet](../../../Concepts/kubelet.md)** — system-reserved, kube-reserved, Allocatable.
- **[Kubernetes Networking Interview](../../../Networking/Network/kubernetes_networking_interview.md)** — вопросы по сети.
