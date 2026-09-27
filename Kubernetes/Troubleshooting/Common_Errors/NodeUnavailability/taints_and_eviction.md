# Недоступность узла: Taints и выселение

Механизм **Taint-based Eviction** является основным способом автоматического восстановления доступности приложений при отказах инфраструктуры. Kubernetes использует taints (метки-«отравления») узлов для идентификации проблем и принятия решения о переносе нагрузки. Данный файл фокусируется на **аварийных сценариях и операциях по восстановлению** — теоретические основы taints/tolerations описаны в [Taints и Tolerations: Теория](../../../Scheduling/taints_and_tolerations.md), взаимодействие с PDB — в [PDB и Taint Eviction](../PodEvicted/pdb_and_taint_eviction.md).

## Основные определения

**Taint (отравление)** — свойство узла (`spec.taints`), которое «отталкивает» поды, не имеющие соответствующего `toleration`. Taint состоит из трёх полей: `key`, `value` и `effect`. При недоступности узла система накладывает taints с эффектом `NoExecute`, что инициирует удаление подов.

**Toleration (терпимость)** — параметр спецификации пода (`spec.tolerations`), позволяющий ему игнорировать конкретные taints. Toleration указывает `key`, `operator` (`Equal` или `Exists`), `effect` и опционально `tolerationSeconds`.

**TolerationSeconds** — период времени (в секундах), в течение которого под может оставаться на узле с taint эффекта `NoExecute` после появления этого taint. По умолчанию для автоматических taints `unreachable` и `not-ready` = **300 секунд** (5 минут). По истечении этого времени API-сервер помечает Pod для удаления.

**DisruptionTarget** — условие (Condition) пода (`status.conditions`), указывающее на то, что под был выбран для удаления в результате добровольного или вынужденного прерывания. Стабилен с Kubernetes 1.31. Устанавливается контроллером при удалении пода через Eviction API или Taint Manager.

**Node Lifecycle Controller** — компонент `kube-controller-manager`, отвечающий за:
1. Мониторинг состояния узлов (опрос каждые `--node-monitor-period`, по умолчанию 5с).
2. Наложение taints при потере связи (`--node-monitor-grace-period`, по умолчанию 40с).
3. Запуск таймеров `tolerationSeconds` для каждого пода без соответствующего toleration.
4. Удаление подов через API-сервер по истечении таймера.

**Eviction API** — API-эндпоинт (`pods/eviction`), через который Taint Manager или kubelet запрашивает удаление пода. В отличие от прямого `DELETE`, Eviction API проверяет PDB перед удалением (но taint-based eviction игнорирует PDB).

**Taint flip-flopping (осцилляция)** — состояние, при котором taint периодически появляется и исчезает (например, из-за осцилляции `memory.available` вокруг порога `evictionHard`). Это вызывает циклическое выселение и перепланирование подов, что дестабилизирует кластер.

## Основные концепции

### Автоматические Taints при сбоях

Node Lifecycle Controller автоматически накладывает taints при обнаружении проблем с узлом:

| Taint | Триггер (Condition) | Eff | Описание | Источник |
| :--- | :--- | :--- | :--- | :--- |
| **`node.kubernetes.io/not-ready`** | `Ready=False` | `NoExecute` | Kubelet сообщает о неисправности узла | node-controller |
| **`node.kubernetes.io/unreachable`** | `Ready=Unknown` | `NoExecute` | Узел перестал отвечать (тайм-аут Lease API) | node-controller |
| **`node.kubernetes.io/memory-pressure`** | `MemoryPressure=True` | `NoSchedule` | Критическая нехватка RAM | kubelet (eviction manager) |
| **`node.kubernetes.io/disk-pressure`** | `DiskPressure=True` | `NoSchedule` | Критическая нехватка диска / inodes | kubelet (eviction manager) |
| **`node.kubernetes.io/pid-pressure`** | `PIDPressure=True` | `NoSchedule` | Исчерпание лимита PID | kubelet (eviction manager) |
| **`node.kubernetes.io/network-unavailable`** | `NetworkUnavailable=True` | `NoSchedule` | Сетевая проблема (CNI) | network-plugin |
| **`node.kubernetes.io/unschedulable`** | `spec.unschedulable=true` | `NoSchedule` | Узел переведён в режим обслуживания | `kubectl cordon` |
| **`node.kubernetes.io/out-of-service`** | вручную | `NoExecute` | Узел гарантированно выключен (K8s 1.24+, GA 1.28) | оператор |

> **Важно:** Taints `NoSchedule` и `PreferNoSchedule` **не удаляют** существующие поды — они только запрещают/ограничивают планирование новых. Только `NoExecute` инициирует выселение.

### Различия效应 taint effects

| Effect | Поведение | Удаление существующих подов | Пример использования |
| :--- | :--- | :--- | :--- |
| **`NoSchedule`** | Запрет планировки новых подов без toleration | Нет | `MemoryPressure`, `DiskPressure`, `cordon` |
| **`PreferNoSchedule`** | Планировщик предпочитает избегать узел (мягкий запрет) | Нет | Экспериментальные узлы |
| **`NoExecute`** | Запрет планировки + удаление существующих подов (с `tolerationSeconds`) | Да | `unreachable`, `not-ready`, `out-of-service` |

### Таймлайн жизненного цикла выселения

Процесс переноса нагрузки при потере связи с узлом следует строгому графику:

```
Узел теряет связь
       │
       ▼
[Шаг 1] Ожидание (40с по умолчанию)
       │ node-monitor-grace-period
       │ Kubelet не отправляет heartbeat (Lease API)
       ▼
[Шаг 2] Узел → Ready=Unknown
       │ node-controller накладывает taint:
       │ node.kubernetes.io/unreachable:NoExecute
       ▼
[Шаг 3] Для каждого Pod без toleration запускается таймер
       │ tolerationSeconds (по умолчанию 300с = 5 минут)
       │ Pod получает condition DisruptionTarget=True
       ▼
[Шаг 4] Истечение таймера
       │ API-сервер помечает Pod deletionTimestamp
       │ kubelet начинает graceful shutdown (terminationGracePeriodSeconds)
       ▼
[Шаг 5] Планировщик назначает новые поды на здоровые узлы
       │ Deployment/ReplicaSet контроллер создает замену
       ▼
[Шаг 6] Восстановление
       │ Новые поды запускаются, сервис восстанавливается
```

**Параметры таймлайна:**

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `--node-monitor-period` | 5s | Интервал опроса состояния узла |
| `--node-monitor-grace-period` | 40s | Время до присвоения `Ready=Unknown` |
| `--pod-eviction-timeout` | 5m | Устаревший параметр (в modern K8s приоритет у `tolerationSeconds`) |
| `tolerationSeconds` (авто) | 300s | Автоматический toleration для `unreachable`/`not-ready` |
| `terminationGracePeriodSeconds` | 30s | Время на graceful shutdown Pod |

### Node Conditions и связь с Taints

Каждый taint от `kubelet` (eviction manager) связан с `NodeCondition`:

| Condition | Taint | Граница taint | Автоматическое снятие |
| :--- | :--- | :--- | :--- |
| `MemoryPressure=True` | `memory-pressure:NoSchedule` | `memory.available < evictionHard.memory.available` | Когда `memory.available` > порога |
| `DiskPressure=True` | `disk-pressure:NoSchedule` | `nodefs.available < evictionHard.nodefs.available` | Когда `nodefs.available` > порога |
| `PIDPressure=True` | `pid-pressure:NoSchedule` | `pid.available < evictionHard.pid.available` | Когда `pid.available` > порога |
| `NetworkUnavailable=True` | `network-unavailable:NoSchedule` | CNI сообщает о проблеме | Когда CNI восстанавливает сеть |
| `Ready=False` | `not-ready:NoExecute` | Kubelet не отвечает | Когда Kubelet восстанавливается |
| `Ready=Unknown` | `unreachable:NoExecute` | Lease не обновляется | Когда Lease обновляется |

> **Важно:** `NoSchedule` taints от eviction manager **автоматически снимаются** при восстановлении условия. `NoExecute` taints (`unreachable`, `not-ready`) снимаются при восстановлении узла, но поды уже могут быть выселены.

### Механика удаления через Eviction API

```
Pod Spec (tolerations, priority, QoS)
       │
       ▼
┌─────────────────────────────┐
│   Taint Manager / kubelet   │
│   Определяет кандидатов     │
│   на выселение              │
└─────────┬───────────────────┘
          │
          ▼
┌─────────────────────────────┐
│   Eviction API Request      │
│   POST /pods/eviction       │
└─────────┬───────────────────┘
          │
          ▼
┌─────────────────────────────┐
│   API Server проверяет:     │
│   1. PDB (minAvailable)     │  ← ТОЛЬКО для добровольных
│   2. Priority               │     прерываний
│   3. QoS (при resource      │
│      pressure)              │
└─────────┬───────────────────┘
          │
          ▼
┌─────────────────────────────┐
│   Pod deletionTimestamp     │
│   = terminationGracePeriod  │
│   kubelet: SIGTERM → wait   │
│   → SIGKILL                 │
└─────────────────────────────┘
```

> **Важно:** При taint-based eviction через `NoExecute` taint **PDB не проверяется** — поды удаляются немедленно (после `tolerationSeconds`). PDB проверяется только при добровольных прерываниях (`kubectl drain`, Cluster Autoscaler). Подробнее: [PDB и Taint Eviction](../PodEvicted/pdb_and_taint_eviction.md).

## Практические сценарии

### Сценарий 1: Настройка устойчивости к сетевым «морганиям»

**Контекст**: Для критических приложений (базы данных, очереди) рекомендуется увеличивать время ожидания, чтобы избежать дорогостоящих переездов при кратковременных сбоях сети.

**Манифест**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
spec:
  replicas: 3
  template:
    spec:
      tolerations:
      - key: "node.kubernetes.io/unreachable"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: 900  # 15 минут до выселения
      - key: "node.kubernetes.io/not-ready"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: 900
```

**Диагностика после настройки**:
```bash
# Проверка tolerations пода
kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}' | jq .

# Результат:
# [
#   {"key":"node.kubernetes.io/unreachable","operator":"Exists","effect":"NoExecute","tolerationSeconds":900},
#   {"key":"node.kubernetes.io/not-ready","operator":"Exists","effect":"NoExecute","tolerationSeconds":900}
# ]

# Проверка, что под НЕ будет выселен немедленно при not-ready
kubectl get events --field-selector reason=TaintManagerEviction | grep <pod-name>
# → (пусто — под ожидает 900с)
```

**Проверка**: При потере связи с узлом под продержится 15 минут перед выселением (вместо стандартных 5).

---

### Сценарий 2: PDB + unhealthyPodEvictionPolicy (Kubernetes 1.31)

**Проблема**: Узел недоступен, время ожидания `tolerationSeconds` истекло, но поды не удаляются, так как `kubectl get pdb` показывает `ALLOWED DISRUPTIONS: 0`.

**Причина**: PDB блокирует удаление подов, даже если они уже не проходят Readiness-пробы (pod networking loss).

**Диагностика**:
```bash
# Проверка PDB
kubectl get pdb -A
# → NAME        MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → web-pdb     2               1                 0                     5d

# Проверка disruptionTarget (K8s 1.31+)
kubectl get pdb web-pdb -o jsonpath='{.status.disruptionTarget}'
# → [web-abc12, web-def34]   ← поды, выселение которых одобрено, но не завершено

# Проверка conditions подов
kubectl get pod web-abc12 -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
# → {"type":"DisruptionTarget","status":"True","reason":"DeletionByTaintManager"}
```

**Решение (Kubernetes 1.31+)**:
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-pdb
spec:
  minAvailable: 2
  unhealthyPodEvictionPolicy: AlwaysAllow  # ← ключевое поле
```

**Поведение `unhealthyPodEvictionPolicy`**:

| Значение | Поведение |
| :--- | :--- |
| `IfHealthyEvictBudget` (по умолчанию) | N unhealthy pods can be evicted if the budget allows it |
| `AlwaysAllow` | Unhealthy pods can ALWAYS be evicted, even if the budget is exceeded |

> **Подробнее:** [PDB и Taint Eviction: Политика выселения нездоровых подов](../PodEvicted/pdb_and_taint_eviction.md#политика-выселения-нездоровых-подов-kubernetes-130).

---

### Сценарий 3: Риски StatefulSet и Split-brain

**Проблема**: При потере связи с узлом поды StatefulSet не пересоздаются автоматически на других узлах (даже после эвикции), чтобы избежать одновременной записи в одно хранилище с двух узлов.

**Опасный метод**: `kubectl delete pod <name> --force --grace-period=0`.
- **Риск**: Если старый узел все еще жив и пишет на диск, принудительный запуск второй копии на другом узле приведет к **порче данных** (Split-brain).

**Безопасный метод (K8s 1.24+, GA 1.28)**: Использование taint `out-of-service`.

```bash
# 1. Убедитесь, что узел физически выключен (не перезагружается)
ssh <node-ip> 'uptime'  # → Connection refused

# 2. Наложите taint
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=nodeshutdown:NoExecute

# 3. Дождитесь завершения подов (проверка)
kubectl get pods -l app=postgres -o wide
# → NAME       READY   STATUS        NODE
# → postgres-0  1/1    Terminating   node-1
# → postgres-1  1/1    Running       node-2
# → postgres-2  0/1    Pending       node-3   ← новая реплика

# 4. После обслуживания снимите taint (если узел восстанавливается)
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-
```

**Что происходит при наложении `out-of-service`**:
1. Taint `NoExecute` немедленно помечает все поды для удаления.
2. `NodeOutOfServiceVolumeDetach` (GA 1.28) безопасно отмонтирует тома от мертвого узла.
3. StatefulSet контроллер пересоздает поды на здоровых узлах.
4. PDB **не блокирует** удаление (taint-based eviction).

> **Подробнее:** [StatefulSet: Ключевые концепции](../../../Base/StatefulSet/statefulset_core_concepts.md#неплановый-отказ-узла), [StatefulSet: Практическое руководство](../../../Base/StatefulSet/statefulset_practical_guide.md#неплановый-отказ-узла).

---

### Сценарий 4: Ручное выселение всех подов с узла через taint (bypass PDB)

**Контекст**: Когда PDB настроен некорректно и блокирует `kubectl drain`, можно использовать taint `NoExecute` для принудительного выселения всех подов без toleration.

**Внимание**: Этот метод **игнорирует PDB**. Используйте только если узел действительно нужно очистить немедленно.

```bash
# 1. Наложите taint (все поды без toleration будут выселены)
kubectl taint node <node-name> manual-eviction=true:NoExecute

# 2. Дождитесь завершения (проверка)
kubectl get pods --field-selector spec.nodeName=<node-name> -w
# → NAME    READY   STATUS        NODE
# → pod-1   1/1    Terminating   node-1
# → pod-2   0/1    Pending       node-2   ← перепланирован

# 3. Проверка events
kubectl get events --field-selector reason=TaintManagerEviction --field-selector involvedObject.name=<pod-name>

# 4. После обслуживания снимите taint
kubectl taint node <node-name> manual-eviction=true:NoExecute-
```

**Проверка после выселения**:
```bash
# Убедитесь, что узел пуст
kubectl get pods --field-selector spec.nodeName=<node-name>
# → No resources found

# Проверка conditions узла
kubectl describe node <node-name> | grep -A 5 Conditions
# → Ready   True    ...
# → (без pressure conditions)
```

---

### Сценарий 5: DaemonSet и автоматические tolerations

**Контекст**: DaemonSet контроллер автоматически добавляет подам tolerations для taints `node.kubernetes.io/unreachable:NoExecute` и `node.kubernetes.io/not-ready:NoExecute` с `tolerationSeconds: null` (без таймаута). Это гарантирует, что агенты (CNI, логирование, мониторинг) **никогда не выселяются** с проблемного узла.

**Проблема**: Пользовательский DaemonSet не запускается на узле с taint `custom-maintenance:NoSchedule`.

**Диагностика**:
```bash
# Проверка taints узла
kubectl get node <node-name> -o jsonpath='{.spec.taints}'
# → [{"key":"custom-maintenance","value":"true","effect":"NoSchedule"}]

# Проверка, что DaemonSet имеет нужный toleration
kubectl get ds <ds-name> -o jsonpath='{.spec.template.spec.tolerations}'
# → [{"key":"custom-maintenance","operator":"Exists","effect":"NoSchedule"}]

# Проверка events DaemonSet
kubectl describe ds <ds-name> | grep -A 5 Events
# → Warning  FailedCreate  ...
# → pods "nginx-" is forbidden: node(s) had taint {custom-maintenance: true}, that pod doesn't tolerate it
```

**Решение**:
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: logging-agent
spec:
  template:
    spec:
      tolerations:
      # Автоматические tolerations (добавляются DaemonSet controller)
      - key: "node.kubernetes.io/unreachable"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: null    # ← никогда не выселяется
      - key: "node.kubernetes.io/not-ready"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: null
      # Пользовательский toleration для обслуживания
      - key: "custom-maintenance"
        operator: "Exists"
        effect: "NoSchedule"
```

**Какие taints DaemonSet НЕ tolerates автоматически**:
- `node.kubernetes.io/memory-pressure`
- `node.kubernetes.io/disk-pressure`
- `node.kubernetes.io/pid-pressure`
- `node.kubernetes.io/network-unavailable`
- `node-role.kubernetes.io/control-plane`
- Любые пользовательские taints

> **Подробнее:** [DaemonSet](../../../Base/daemonset.md#taints-и-tolerations), [Taints и Tolerations: Поведение DaemonSet](../../../Scheduling/taints_and_tolerations.md#поведение-daemonset).

---

### Сценарий 6: Диагностика Pending pod из-за Taints

**Симптом**: Pod в состоянии `Pending`. `kubectl describe pod` показывает `0/N nodes are available: N(s) had taint ... that pod doesn't tolerate`.

**Диагностика**:
```bash
# 1. Найти причину Pending
kubectl describe pod <pod-name> | grep -A 5 "Events"
# → Warning  FailedScheduling  ...
# → 0/5 nodes are available: 2(s) had taint node.kubernetes.io/disk-pressure that pod doesn't tolerate,
#                            1(s) had taint node.kubernetes.io/memory-pressure that pod doesn't tolerate,
#                            2(s) had taint custom/gpu-only:NoSchedule that pod doesn't tolerate.

# 2. Проверить taints всех узлов
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
# → NAME     TAINTS
# → node-1   [node.kubernetes.io/disk-pressure:NoExecute]
# → node-2   [node.kubernetes.io/memory-pressure:NoExecute]
# → node-3   [custom/gpu-only:NoSchedule]
# → node-4   []
# → node-5   []

# 3. Проверить conditions узлов (связь с taints)
kubectl get nodes -o custom-columns=NAME:.metadata.name,DISK:.status.conditions[?(@.type=="DiskPressure")].status,MEM:.status.conditions[?(@.type=="MemoryPressure")].status
# → NAME     DISK     MEM
# → node-1   True     False
# → node-2   False    True
# → node-3   False    False
# → node-4   False    False
# → node-5   False    False

# 4. Проверить, какие поды уже работают на проблемных узлах
kubectl get pods --field-selector spec.nodeName=node-1 -o wide
# → NAME    READY   STATUS    NODE
# → agent   1/1     Running   node-1   ← tolerates disk-pressure
```

**Решение** (по ситуации):
- **Taint `disk-pressure`**: освободите место на диске → taint снимется автоматически.
- **Taint `memory-pressure`**: освободите память → taint снимется автоматически.
- **Пользовательский taint**: добавьте `toleration` в манифест пода.

---

### Сценарий 7: Осцилляция taints и бесконечное выселение

**Симптом**: Поды постоянно выселяются и пересоздаются. `kubectl get events` показывает повторяющиеся `TaintManagerEviction` каждые несколько минут.

**Причина**: Taint периодически появляется и исчезает (flip-flopping). Например, `memory.available` осциллирует вокруг порога `evictionHard`.

**Диагностика**:
```bash
# 1. Проверка frequency taints
kubectl get node <node-name> -o jsonpath='{range .spec.taints[*]}{.key}{"\t"}{.timeAdded}{"\n"}{end}'
# → node.kubernetes.io/memory-pressure    2026-09-04T17:30:00Z
# → node.kubernetes.io/memory-pressure    2026-09-04T17:35:00Z
# → node.kubernetes.io/memory-pressure    2026-09-04T17:40:00Z  ← каждые 5 минут

# 2. Проверка conditions (осцилляция)
kubectl get node <node-name> -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.lastTransitionTime}{"\n"}{end}'
# → MemoryPressure   True    2026-09-04T17:30:00Z
# → MemoryPressure   False   2026-09-04T17:32:00Z
# → MemoryPressure   True    2026-09-04T17:35:00Z  ← осцилляция

# 3. Проверка eviction events
kubectl get events -A --field-selector reason=TaintManagerEviction --sort-by='.lastTimestamp' | tail -10
# → 5m    Normal  TaintManagerEviction  pod/app-1  Marking for deletion
# → 3m    Normal  TaintManagerEviction  pod/app-2  Marking for deletion
# → 1m    Normal  TaintManagerEviction  pod/app-1  Marking for deletion  ← повторно
```

**Решение**:
```bash
# 1. Увеличьте evictionHard (добавьте запас)
# В /var/lib/kubelet/config.yaml:
# evictionHard:
#   memory.available: "500Mi"   # было 200Mi

# 2. Перезапустите kubelet
sudo systemctl restart kubelet

# 3. Проверка, что осцилляция прекратилась
kubectl get node <node-name> -o jsonpath='{.status.conditions[?(@.type=="MemoryPressure")].status}'
# → False   ← стабильно
```

---

### Сценарий 8: Пользовательский taint для обслуживания узла

**Контекст**: При плановом обслуживании (замена дисков, обновление ОС) нужно безопасно перевести узел в обслуживание без нарушения SLA.

**Пошаговая процедура**:
```bash
# 1. Проверка текущего состояния узла
kubectl get node <node-name> -o wide
# → NAME     STATUS   ROLES    AGE    VERSION   INTERNAL-IP
# → node-1   Ready    worker   90d    v1.31.0   10.0.1.10

# 2. Проверка PodDisruptionBudget
kubectl get pdb -A | grep -v "ALLOWED DISRUPTIONS: 0"
# → NAME        MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → web-pdb     2               1                 2                     5d   ← OK

# 3. Перевод узла в режим обслуживания (cordon)
kubectl cordon <node-name>
# → node/node-1 cordoned
# → Автоматически накладывается taint: node.kubernetes.io/unschedulable:NoSchedule

# 4. Наложение taint для безопасного выселения (если нужно)
kubectl taint node <node-name> maintenance=true:NoSchedule

# 5. Drain с учетом PDB
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=60 \
  --timeout=5m
# → node-1 drained

# 6. Обслуживание узла (замена дисков, обновление ОС и т.д.)
ssh <node-ip> 'sudo reboot'

# 7. После обслуживания — снятие taints и uncordon
kubectl taint node <node-name> maintenance=true:NoSchedule-
kubectl uncordon <node-name>
# → node/node-1 uncordoned

# 8. Проверка восстановления
kubectl get node <node-name>
# → NAME     STATUS   ROLES    AGE    VERSION   INTERNAL-IP
# → node-1   Ready    worker   90d    v1.31.0   10.0.1.10
```

**Что происходит при `kubectl drain`**:
1. Узел помечается `unschedulable:NoSchedule` (как `cordon`).
2. Для каждого Pod запускается Eviction API запрос (проверяется PDB).
3. Если PDB блокирует — drain повторяет попытку (до `--timeout`).
4. Если PDB не блокирует — Pod получает `deletionTimestamp`, kubelet завершает его.
5. DaemonSet поды игнорируются (с `--ignore-daemonsets`).

> **Подробнее:** [Обслуживание узлов](./maintenance.md), [kubectl drain](../../../Operations/node_maintenance.md).

---

### Сценарий 9: Out-of-service taint и NodeOutOfServiceVolumeDetach (K8s 1.28+)

**Проблема**: Узел с RWO-томами (PersistentVolumeClaim с `ReadWriteOnce`) выключен. Tom на недоступном узле заблокирован, новый под не может примонтировать его.

**Диагностика**:
```bash
# 1. Проверка events PVC
kubectl describe pvc <pvc-name> | grep -A 5 Events
# → Warning  FailedAttachVolume  ...
# → Multi-Attach detected for volume "pvc-abc12"
# → volume is already exclusively attached to node node-1 and can't be attached to node-2

# 2. Проверка status PV
kubectl get pv <pv-name> -o jsonpath='{.spec.nodeAffinity}'
# → {"required":{"nodeSelectorTerms":[{"matchExpressions":[{"key":"kubernetes.io/hostname","operator":"In","values":["node-1"]}]}]}}

# 3. Проверка conditions узла
kubectl get node node-1 -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → Unknown   ← узел недоступен
```

**Решение**:
```bash
# 1. Наложите out-of-service taint
kubectl taint nodes node-1 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute

# 2. Что происходит:
#    a. Taint NoExecute удаляет все поды с узла
#    b. NodeOutOfServiceVolumeDetach (GA 1.28) безопасно отмонтирует тома
#    c. Pod с PVC пересоздается на другом узле
#    d. Volume привязывается к новому узлу

# 3. Проверка
kubectl get pods -o wide | grep postgres
# → postgres-0   1/1   Running   node-2   ← новый узел
kubectl get pvc postgres-pvc -o jsonpath='{.spec.volumeName}'
# → pvc-abc12   ← тот же том, но привязан к node-2
```

**Порядок восстановления узла**:
```bash
# 1. Восстановите узел (включите, загрузите ОС)
# 2. Убедитесь, что kubelet запустился
ssh <node-ip> 'systemctl status kubelet'

# 3. Снимите out-of-service taint
kubectl taint nodes node-1 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-

# 4. Узел вернется в кластер автоматически
kubectl get node node-1
# → NAME     STATUS   ROLES    AGE    VERSION
# → node-1   Ready    worker   90d    v1.31.0
```

> **Подробнее:** [Non-Graceful Node Shutdown](../../../Base/StatefulSet/statefulset_core_concepts.md#неплановый-отказ-узла), [NodeUnavailability: Definitions](./definitions.md).

---

### Сценарий 10: Диагностика через эфемерные контейнеры

**Контекст**: Когда kubelet на проблемном узле не работает и стандартные команды недоступны, используйте эфемерный контейнер для отладки.

```bash
# 1. Запуск отладочного контейнера на проблемном узле
kubectl debug node/<node-name> -it --image=busybox -- /bin/sh

# 2. Внутри контейнера — проверка kubelet
nsenter -t 1 -m -u -i -n -p -- systemctl status kubelet
# → ● kubelet.service - kubelet
#    Active: active (running) since ...

# 3. Проверка taints в файловой системе
cat /var/lib/kubelet/config.yaml | grep -A 10 "evictionHard"

# 4. Проверка PSI (если ядро поддерживает)
cat /proc/pressure/memory
# → some avg10=15.30 avg60=8.20 avg300=3.50 total=12345678

# 5. Проверка логов kubelet
journalctl -u kubelet --since "1 hour ago" --no-pager | grep -i "taint\|eviction\|pressure"

# 6. Выход из контейнера
exit
```

> **Подробнее:** [Kubernetes Debug Nodes](https://kubernetes.io/docs/tasks/debug/debug-cluster/debug-node/), [Diagnostics узла](./diagnostics.md).

## Мониторинг и алертинг

### Метрики taint-based eviction (Prometheus)

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `kube_node_status_condition{condition="Ready",status="true"}` | Узел Ready | == 0持续 2 минуты |
| `kube_node_status_condition{condition="MemoryPressure",status="true"}` | MemoryPressure=True | == 1持续 2 минуты |
| `kube_node_status_condition{condition="DiskPressure",status="true"}` | DiskPressure=True | == 1持续 2 минуты |
| `kube_node_status_condition{condition="PIDPressure",status="true"}` | PIDPressure=True | == 1持续 2 минуты |
| `kube_node_spec_taint` | Количество taints на узле | > 3持续 10 минут |
| `kubelet_evictions` | Количество eviction-событий по kubelet | > 0持续 5 минут |
| `increase(kube_pod_status_reason{reason="NodeLost"}[5m])` | Поды с причиной NodeLost | > 0持续 5 минут |

### Примеры алертов (PrometheusRule)

```yaml
groups:
  - name: taint-eviction
    rules:
      # Узел NotReady
      - alert: NodeNotReady
        expr: kube_node_status_condition{condition="Ready",status="true"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Узел {{ $labels.node }} не отвечает (Ready=False/Unknown)"
          description: "Возможно taint-based eviction через 5 минут"

      # Taint MemoryPressure
      - alert: NodeMemoryPressureTaint
        expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.node }}: taint memory-pressure:NoSchedule"
          description: "Новые поды без toleration не могут быть запланированы"

      # Taint DiskPressure
      - alert: NodeDiskPressureTaint
        expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.node }}: taint disk-pressure:NoSchedule"
          description: "Возможно раздражающее盤 очистка образов (Image GC)"

      # Mass eviction
      - alert: KubeletEvictionsHigh
        expr: increase(kubelet_evictions[5m]) > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Kubelet на {{ $labels.instance }} выселяет поды"
          description: "Обнаружены массовые eviction-события"

      # Node lost
      - alert: NodeLost
        expr: increase(kube_pod_status_reason{reason="NodeLost"}[5m]) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Поды потеряли узел (NodeLost)"
          description: "Поды {{ $labels.pod }} были перепланированы из-за потери узла {{ $labels.node }}"
```

### Быстрая диагностика taints

```bash
# Все taints в кластере
kubectl get nodes -o json | jq -r '.items[] | .metadata.name as $n | .spec.taints[]? | "\($n)\t\(.key)\t\(.effect)"'
# → node-1    node.kubernetes.io/disk-pressure    NoExecute
# → node-2    node.kubernetes.io/memory-pressure   NoExecute
# → node-3    custom/gpu-only                      NoSchedule

# Узлы с taints NoExecute (критические)
kubectl get nodes -o json | jq -r '.items[] | select(.spec.taints[]? | .effect == "NoExecute") | .metadata.name'
# → node-1
# → node-2

# Поды с tolerations для unreachable/not-ready (включая DaemonSet)
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.tolerations[]? | .key == "node.kubernetes.io/unreachable") | .metadata.namespace + "/" + .metadata.name'
# → kube-system/kube-proxy
# → kube-system/calico-node
# → monitoring/node-exporter
```

## Связанные разделы

- **[Taints и Tolerations: Теория](../../../Scheduling/taints_and_tolerations.md)** — определения, эффекты, операторы, DaemonSet, сравнение с Affinity.
- **[PDB и Taint Eviction](../PodEvicted/pdb_and_taint_eviction.md)** — взаимодействие PDB и taint-based eviction, Eviction API, unhealthyPodEvictionPolicy.
- **[Диагностика недоступности узла](./diagnostics.md)** — первичный анализ причин сбоя.
- **[Обслуживание узлов (PDB и drain)](./maintenance.md)** — как бюджеты влияют на drain.
- **[Definitions: Taints](./definitions.md)** — базовые определения, включая `out-of-service` taint.
- **[QoS и выселение](../PodEvicted/qos_and_eviction.md)** — PriorityQueue, oom_score_adj, порядок выселения по QoS.
- **[Resource Pressure](./resource_pressure.md)** — MemoryPressure, DiskPressure, PIDPressure: диагностика и сценарии.
- **[Тюнинг ядра](./kernel_tuning.md)** — sysctl параметры, влияющие на conntrack и маршрутизацию.
- **[Hostname и DNS](./hostname_dns_issues.md)** — имя узла влияет на регистрацию и TLS.
- **[SSH-доступ](./bastion_ssh_access.md)** — диагностика узлов через bastion.
