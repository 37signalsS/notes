# Pod Terminating — узел недоступен (Node Unavailable)

## Определения

**Pod на недоступном узле в Terminating** — состояние, при котором объект Pod получил метку времени удаления (`deletionTimestamp`), но Kubelet на целевом узле не может подтвердить завершение процессов и очистку ресурсов из-за потери связи с Control Plane.

**Lease объект (Node Lease)** — механизм в пространстве имен `kube-node-lease`, через который Kubelet сообщает о своей жизнеспособности. Обновляется чаще и легче, чем `NodeStatus` (каждые 10 секунд по умолчанию).

**Состояние Unknown** — статус узла (`Ready=Unknown`), возникающий, когда Control Plane не получает обновлений `Lease` или `NodeStatus` в течение `node-monitor-grace-period` (по умолчанию 40с).

**Тайм-аут выселения (Pod Eviction Timeout)** — задержка перед тем, как контроллер начнет удалять поды с неисправного узла (по умолчанию 5 минут). Настраивается через `--pod-eviction-timeout` в `kube-controller-manager`.

**Узел-призрак (Ghost Node)** — узел, который физически упал или потерял связь, но объект Node всё ещё существует в API как `Ready=Unknown`. Поды на этом узле остаются в `Terminating` до истечения `tolerationSeconds` (300с по умолчанию).

**Orphaned Pod (Осиротевший Pod)** — Pod, чей объект удалён из API, но физические ресурсы (контейнеры, тома, сетевые пространства) на узле не очищены, так как Kubelet не смог выполнить cleanup.

**Reattach (Повторное подключение тома)** — операция CSI-драйвера `ControllerPublishVolume` для подключения тома к новому узлу после того, как том был отсоединён от упавшего. Требует корректного завершения `ControllerUnpublishVolume` на старом узле или ручного удаления `VolumeAttachment`.

**Cordoning (Ограждение узла)** — пометка узла как непригодного для приёма новых подов (`kubectl cordon`). Существующие поды продолжают работать. Используется перед обслуживанием (drain).

**Graceful Node Shutdown** — механизм Kubernetes (GA с 1.24), при котором Kubelet получает сигнал о выключении ОС через `systemd-logind` и корректно завершает поды до остановки узла. Настраивается через `shutdownGracePeriod` и `shutdownGracePeriodCriticalPods`.

**Taint-based Eviction** — автоматический механизм удаления подов с нездоровых узлов через наложение `taints` с эффектом `NoExecute`. Поды без подходящего `toleration` удаляются через `tolerationSeconds` (по умолчанию 300с).

---

## Базовые концепции

### Механизм тайм-лайна при потере связи

Когда узел перестаёт отвечать, запускается строгий граф:

1.  **Обнаружение (40с):** Kubelet не обновляет `Lease`. Контроллер помечает узел как `Ready=Unknown`.
2.  **Tainting:** На узел накладывается `node.kubernetes.io/unreachable:NoExecute`.
3.  **Ожидание (300с):** По умолчанию поды имеют `toleration` на 5 минут. Если за это время связь не восстановлена, контроллер инициирует удаление подов.
4.  **Удаление:** API-сервер помечает Pod как `Terminating`. Если Kubelet доступен — выполняет cleanup. Если нет — под остаётся в `Terminating` с `deletionTimestamp`, пока не будут сняты финализаторы.

> **Отличие от PDB:** Taint-based eviction (involuntary disruption) **не блокируется** PDB. PDB защищает только добровольные прерывания (`kubectl drain`, масштабирование). См. [PDB Blocking](./pdb_blocking.md).

### Нюансы StatefulSet

Для StatefulSet состояние `Terminating` на недоступном узле является критическим механизмом защиты. В отличие от Deployment, StatefulSet гарантирует **уникальность индекса**. Если под `web-0` зависит на упавшем узле, контроллер **не создаст** новый `web-0` на другом узле до тех пор, пока старый объект не будет полностью удален из API. Это предотвращает одновременную запись в один том (Split-brain).

> **Важно:** Для безопасного восстановления StatefulSet на новом узле используйте `out-of-service` taint (см. Сценарий 3), а НЕ `kubectl delete pod --force`. Принудительное удаление без `out-of-service` может привести к порче данных при параллельной записи.

### Дерево решений: диагностика подов на недоступном узле

```
Pod в Terminating, узел NotReady/Unknown
│
├─ Узел вернулся в строй?
│   ├─ ДА → Под завершится автоматически (Kubelet cleanup)
│   └─ НЕТ
│       ├─ Под нужен СЕЙЧАС (критичный сервис)?
│       │   ├─ StatefulSet? → Сценарий 3: out-of-service taint
│       │   ├─ Deployment/ReplicaSet? → Сценарий 2: Force Delete
│       │   └─ DaemonSet? → Сценарий 5: Cordoning + ожидание
│       │
│       ├─ Узел будет восстановлен?
│       │   ├─ Да, в ближайшее время → Сценарий 1: Self-healing
│       │   └─ Нет, узел списан → Сценарий 3: out-of-service taint
│       │
│       └─ Том застрял (Multi-Attach)?
│           ├─ VolumeAttachment есть? → См. [Финализаторы и CSI](./finalizer_issues.md)
│           └─ Нет VolumeAttachment? → Сценарий 6: Reattach volumes
│
├─ Узел доступен, но под в Terminating?
│   ├─ Финализаторы в метаданных? → См. [Финализаторы и CSI](./finalizer_issues.md)
│   └─ terminationGracePeriodSeconds не истёк? → Ожидайте
│
└─ PDB блокирует удаление?
    └─ PDB не блокирует taint-based eviction → См. [PDB Blocking](./pdb_blocking.md)
```

### Таблица инструментов

| Уровень | Инструмент | Назначение | Пример |
| :--- | :--- | :--- | :--- |
| **K8s (API)** | `kubectl get nodes` | Статус узлов и Conditions. | `kubectl get nodes -o wide` |
| **K8s (API)** | `kubectl describe node` | Подробности: Conditions, Taints, Events. | `kubectl describe node <name>` |
| **K8s (API)** | `kubectl get lease` | Время последнего Heartbeat. | `kubectl get lease -n kube-node-lease <name> -o yaml` |
| **K8s (API)** | `kubectl get pods -o wide` | Распределение подов по узлам. | `kubectl get pods -A -o wide \| grep <node>` |
| **K8s (API)** | `kubectl get volumeattachment` | Статус отсоединения томов. | `kubectl get volumeattachment \| grep <node>` |
| **OS (на узле)** | `systemctl status kubelet` | Состояние Kubelet на узле. | `ssh <node> systemctl status kubelet` |
| **OS (на узле)** | `journalctl -u kubelet` | Логи Kubelet. | `ssh <node> journalctl -u kubelet --since "10 min ago"` |
| **OS (на узле)** | `crictl ps -a` | Контейнеры на узле (CRI). | `ssh <node> crictl ps -a` |
| **OS (на узле)** | `dmesg` | Ошибки ядра (hardware, OOM). | `ssh <node> dmesg \| tail -30` |
| **OS (на узле)** | `ip addr / ping` | Сетевая связность. | `ssh <node> ip addr show` |

---

## Практические сценарии

### Быстрый чек-лист диагностики

```bash
# 1. Статус узла и время последнего heartbeat
kubectl get node <node-name> -o jsonpath='{
  Ready:  {.status.conditions[?(@.type=="Ready")].status}
  Reason: {.status.conditions[?(@.type=="Ready")].reason}
  Since:  {.status.conditions[?(@.type=="Ready")].lastTransitionTime}
}'
# Пример: Ready: Unknown, Reason: NodeStatusUnknown, Since: 2026-09-03T10:00:00Z

# 2. Taints на узле
kubectl describe node <node-name> | grep -A 5 Taints
# Пример:
#   Taints:             node.kubernetes.io/unreachable:NoExecute

# 3. Поды на этом узле
kubectl get pods -A -o wide | grep <node-name>
# Пример:
#   default    web-0    1/1  Terminating  0  10h  <node-name>
#   default    api-5a   0/1  Terminating  0  10h  <node-name>

# 4. Когда началось завершение?
kubectl get pod <pod-name> -o jsonpath='{
  deletionTimestamp:       {.metadata.deletionTimestamp}
  deletionGracePeriod:    {.metadata.deletionGracePeriodSeconds}
  terminationGracePeriod: {.spec.terminationGracePeriodSeconds}
}'
# Пример: deletionTimestamp: 2026-09-03T10:05:00Z → прошло 5+ минут

# 5. Финализаторы (блокируют удаление?)
kubectl get pod <pod-name> -o jsonpath='DeletionTimestamp: {.metadata.deletionTimestamp}{"\n"}Finalizers: {.metadata.finalizers}'
# Пример: Finalizers: [kubernetes.io/pod-protection] → тормозит cleanup

# 6. VolumeAttachment для этого узла
kubectl get volumeattachment | grep <node-name>
# Пример:
#   a-attach-abc123   <driver-name>   <node-name>   true
```

### Сценарий 1: Кратковременный сбой (Self-healing)

**Ситуация:** Сетевой "морг" или перезагрузка ОС. Узел вернётся в строй через несколько минут.

**Действие:** Если критичность приложения позволяет, лучше дождаться возвращения узла. Kubelet после старта синхронизирует состояние с API, завершит старые контейнеры и подтвердит удаление подов.

**Как определить, что self-healing сработает:**
```bash
# Проверьте, когда узел стал Unknown
kubectl get node <node-name> -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastTransitionTime}'
# Пример: 2026-09-03T10:00:00Z

# Проверьте, есть ли сетевая связность (если доступен по SSH)
ssh <node-name> "ip addr show | grep 'inet ' | head -3"
# Если IP доступен — likely кратковременный сбой

# Мониторинг восстановления (измените интервал по ситуации)
watch -n 10 'kubectl get node <node-name> -o jsonpath="{.status.conditions[?(@.type==\"Ready\")].status}"'
# → Unknown → Ready = узел восстановился
```

**Когда НЕ стоит ждать:**
- Узел недоступен > 15 минут и нет признаков восстановления.
- УзелARTHardware failure (диски, RAM, CPU).
- Узел заражен и представляет угрозу кластеру.

### Сценарий 2: Принудительное удаление (Force Delete)

**Ситуация:** Узел физически уничтожен, и вы уверены, что процессы на нем не запущены. Pod критичен для доступности сервиса.

**Решение:**
```bash
# 1. Удалите Pod принудительно
kubectl delete pod <pod-name> --force --grace-period=0
# → pod "web-0" deleted

# 2. Проверьте, что под пересоздался на другом узле
kubectl get pod <pod-name> -o wide
# Пример:
#   NAME    READY  STATUS   RESTARTS  AGE   IP          NODE
#   web-0   1/1    Running  0         30s   10.244.1.5  node-2

# 3. Проверьте Multi-Attach: том не должен быть примонтирован к "мертвому" узлу
kubectl get volumeattachment | grep <dead-node-name>
# Если VolumeAttachment существует — проблема. См. Сценарий 6.
```

**Внимание для StatefulSet:** `--force --grace-period=0` удаляет Pod из API, но НЕ гарантирует, что старый узел не пишет на диск. Используйте только если:
- Узел физически уничтожен (fire, flood, hardware failure).
- Вы 100% уверены, что процессы на узле мертвы.
- Нет риска Split-brain (см. Сценарий 3).

### Сценарий 3: Non-graceful Node Shutdown (out-of-service taint)

**Ситуация:** Узел выключен намеренно (например, через IPMI), но Kubelet не успел корректно завершить работу. StatefulSet или критичный сервис нуждается в быстром восстановлении.

**Решение:**
```bash
# 1. Убедитесь, что узел физически выключен или гарантированно не работает
ping -c 3 <node-ip>  # → 100% packet loss
ssh <node-ip> "echo test" 2>&1  # → Connection refused / timeout

# 2. Установите out-of-service taint
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=NoExecute:NoExecute
# → node/node-name tainted

# 3. Дождитесь пересоздания подов
kubectl get pods -A -o wide | grep <pod-name>
# Пример (StatefulSet web-0):
#   NAME    READY  STATUS    RESTARTS  AGE  NODE
#   web-0   0/1    Pending   0         5s   node-2

# 4. Проверьте, что VolumeAttachment очищен
kubectl get volumeattachment | grep <dead-node-name>
# → (пусто — CSI-драйвер отсоединил том)

# 5. Удалите taint перед возвращением узла в строй
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service-
# → node/node-name untainted
```

**Почему это безопасно для StatefulSet:**
1. `out-of-service` taint сигнализирует контроллеру StatefulSet, что узел гарантированно не работает.
2. Контроллер безопасно удаляет старый Pod и создаёт новый с тем же индексом.
3. CSI-драйвер завершает `ControllerUnpublishVolume` и разрешает `ControllerPublishVolume` на новом узле.
4. Это работает для **всех** типов workload (Deployment, DaemonSet, StatefulSet).

### Сценарий 4: Очистка зависших финализаторов

**Ситуация:** Pod не исчезает даже после Force Delete и удаления узла.

**Диагностика:**
```bash
# Проверьте финализаторы
kubectl get pod <pod-name> -o jsonpath='{
  DeletionTimestamp: {.metadata.deletionTimestamp}
  Finalizers:        {.metadata.finalizers}
}'
# Пример:
#   DeletionTimestamp: 2026-09-03T10:05:00Z
#   Finalizers:        [kubernetes.io/pod-protection]

# Проверьте, с каким контроллером связан финализатор
kubectl get pod <pod-name> -o json | jq '.metadata.finalizers'
# → ["kubernetes.io/pod-protection"] — стандартный K8s финализатор
# → ["external-attacher/<driver>"] — CSI-драйвер
```

**Решение:**
```bash
# 1. Снимите финализаторы (последнее средство)
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":[]}}' --type=merge
# → pod "web-0" patched

# 2. Проверьте результат
kubectl get pod <pod-name>
# → Error from server (NotFound): pods "web-0" not found — под удалён

# 3. Если финализатор связан с CSI — сначала проверьте VolumeAttachment
kubectl get volumeattachment | grep <node-name>
# Если есть — удалите: kubectl delete volumeattachment <name>
# Затем снимите финализатор пода
```

**Внимание:** Удаление финализаторов может привести к "осиротевшим" ресурсам (неотсоединённые диски, неочищенные IP-адреса). Используйте только когда:
- Узел гарантированно мёртв.
- Вы проверили и при необходимости очистили `VolumeAttachment`.
- Вы понимаете последствия для StatefulSet (Split-brain risk).

### Сценарий 5: Плановое обслуживание (Cordon + Drain)

**Ситуация:** Узел нужно вывести из эксплуатации для обслуживания (обновление ОС, замена дисков, обновление Kubelet).

**Регламент:**
```bash
# 1. Пометите узел как непригодный для приёма новых подов
kubectl cordon <node-name>
# → node/node-name cordoned

# 2. Проверьте, что на узле нет критичных подов
kubectl get pods -A -o wide | grep <node-name>
# Убедитесь, что нет StatefulSet, DaemonSet (если нужно сохранить), или критичных сервисов

# 3. Выведите поды из узла (drain)
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=60 \
  --timeout=300s
# Пример вывода:
#   node/node-1 cordoned
#   WARNING: ignoring DaemonSet-managed pods: kube-flannel-ds-xxxxx, kube-proxy-xxxxx
#   pod/curl-xxxxx evicted
#   node/node-1 drained

# 4. Если drain зависает (PDB блокирует):
kubectl get pdb -A | grep -v "ALLOWED DISRUPTIONS: 0"
# Найдите PDB с ALLOWED DISRUPTIONS: 0 и либо подождите, либо временно отключите его

# 5. Выполните обслуживание на узле...

# 6. Верните узел в строй
kubectl uncordon <node-name>
# → node/node-name uncordon
```

**Если drain не завершается (Timeout):**
```bash
# Проверьте, какие поды блокируют drain
kubectl get pods -A -o wide | grep <node-name> | grep -v "kube-system"
# Найдите под с PDB и увеличьте тайм-аут:
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --timeout=600s

# Или принудительно удалите (если обслуживание критично):
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --force --timeout=300s
```

### Сценарий 6: Повторное подключение томов (Volume Reattach)

**Ситуация:** После уничтожения узла Pod пересоздан на другом узле, но не может стартовать, так как том всё ещё "примонтирован" к "мертвому" узлу.

**Диагностика:**
```bash
# Проверьте Pending-под
kubectl get pods -A -o wide | grep Pending
# Пример:
#   default  data-0  0/1  Pending  0  2m  node-2

# Проверьте Events Pending-пода
kubectl describe pod data-0 | grep -A 10 Events
# Пример:
#   Warning  FailedAttachVolume  2m  attachdetach-controller
#     Multi-AttachVolume failed for volume "pvc-abc" Volume is already exclusively
#     attached to node "dead-node" and cannot be attached to node "node-2"

# Проверьте VolumeAttachment
kubectl get volumeattachment | grep <dead-node-name>
# Пример:
#   a-attach-abc123   <driver>   dead-node   true
```

**Решение:**
```bash
# 1. Если узел мёртв — подождите автоматического отсоединения
#    (CSI-драйвер обычно обрабатывает через 6 минут — timeout неактивного узла)

# 2. Если автоснятие не работает — удалите VolumeAttachment вручную
kubectl delete volumeattachment <attachment-name>
# → volumeattachment.storage.k8ubernetes.io "a-attach-abc123" deleted

# 3. Проверьте, что под стартовал
kubectl get pod data-0 -o wide
# → Running на node-2

# 4. Если том локальный (local-path-provisioner, hostPath) — Reattach НЕВОЗМОЖЕН
#    Файлы физически привязаны к узлу. Нужно либо:
#    - Восстановить из бэкапа
#    - Использовать распределённый storage (Ceph, NFS, Longhorn)
```

### Сценарий 7: Длительная недоступность узла (часы/дни)

**Ситуация:** Узел недоступен долгое время. Поды уже выселены, но нужно убедиться, что система стабильна и нет рисков.

**Действия:**
```bash
# 1. Проверьте, что все поды пересозданы на здоровых узлах
kubectl get pods -A -o wide | grep <dead-node-name>
# → (пусто — все поды выселены)

# 2. Проверьте балансировку нагрузки
kubectl top nodes
# Пример:
#   NAME     CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
#   node-1   250m         12%    1024Mi          25%
#   node-2   800m         40%    2048Mi          50%  ← перегружен

# 3. Если node-2 перегружен — добавьте узел или масштабируйте
kubectl scale deployment <name> --replicas=<N>  # снизить нагрузку
# или добавьте новый узел в кластер

# 4. Проверьте PVC в Released (том не привязан)
kubectl get pv | grep Released
# Пример:
#   pv-local-abc   10Gi   RWO   Delete   Released   default/data-pvc   local-path   1h
# → Том не привязан, новый Pod не может его использовать

# 5. Проверьте PV с ReclaimPolicy: Retain (ручная очистка)
kubectl get pv -o json | jq -r '.items[] | select(.spec.persistentVolumeReclaimPolicy=="Retain") | "\(.metadata.name) \(.status.phase)"'
```

**Чистка ресурсов упавшего узла:**
```bash
# Удалите объект Node (если узел списан)
kubectl delete node <dead-node-name>

# Проверьте, что удаление не блокируется финализаторами
kubectl get node <dead-node-name> -o jsonpath='{.metadata.finalizers}'
# → [] (пусто — можно удалять)

# Если есть финализаторы — снимите их
kubectl patch node <dead-node-name> -p '{"metadata":{"finalizers":null}}' --type=merge
```

---

## Мониторинг и алерты

### PromQL запросы

```promql
# Узлы в статусе NotReady или Unknown
count by (node) (kube_node_status_condition{condition="Ready",status=~"false|unknown"}) > 0

# Поды на недоступных узлах
count by (namespace) (
  kube_pod_info * on(node) group_left()
  kube_node_status_condition{condition="Ready",status=~"false|unknown"}
)

# Поды в Terminating дольше 10 минут
(time() - kube_pod_created) > 600
  and
kube_pod_status_phase{phase="Terminating"} == 1

# Taint-based eviction events
increase(kube_pod_status_reason{reason="NodeAffinity"}[5m])

# VolumeAttachment для упавших узлов
count by (attached) (
  kube_volumeattachment_info * on(node) group_left()
  kube_node_status_condition{condition="Ready",status="unknown"}
)
```

### Готовые алерты (Prometheus AlertManager)

```yaml
groups:
- name: node_unavailable
  rules:
  - alert: NodeNotReady
    expr: kube_node_status_condition{condition="Ready",status="false"} == 1
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Node {{ $labels.node }} is NotReady"
      description: "Узел {{ $labels.node }} в статусе NotReady более 5 минут."

  - alert: NodeUnknown
    expr: kube_node_status_condition{condition="Ready",status="unknown"} == 1
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Node {{ $labels.node }} is Unknown"
      description: "Узел {{ $labels.node }} недоступен (Ready=Unknown). Проверьте сетевую связность."

  - alert: PodStuckTerminatingNodeDown
    expr: |
      kube_pod_status_phase{phase="Terminating"} == 1
      and on(node)
      kube_node_status_condition{condition="Ready",status=~"false|unknown"} == 1
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Pod stuck in Terminating on unavailable node"
      description: "Pod {{ $labels.pod }} в {{ $labels.namespace }} зависит на узле {{ $labels.node }} более 10 минут."

  - alert: VolumeAttachmentStuck
    expr: |
      kube_volumeattachment_info == 1
      and on(node)
      kube_node_status_condition{condition="Ready",status="unknown"} == 1
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "VolumeAttachment stuck on unavailable node"
      description: "VolumeAttachment на узле {{ $labels.node }} не очищается более 15 минут."
```

### Проверка логов Kubelet при восстановлении узла

```bash
# После возвращения узла в строй — проверьте, что Kubelet синхронизировался
ssh <node> "journalctl -u kubelet --since '5 min ago' | grep -i 'sync\|status\|evict'"
# Пример вывода:
#   Sep 03 10:30:00 node-1 kubelet[1234]: I1003 10:30:00.123] Syncing status with API server
#   Sep 03 10:30:01 node-1 kubelet[1234]: I1003 10:30:01.456] Status is now: Ready

# Проверка, что старые контейнеры очищены
ssh <node> "crictl ps -a"
# → (пусто — все старые контейнеры удалены)
```

---

## Команды kubectl

| Команда | Назначение |
| :--- | :--- |
| `kubectl get nodes -o wide` | Статус узлов (Ready/NotReady/Unknown). |
| `kubectl describe node <name>` | Conditions, Taints, Events узла. |
| `kubectl get lease -n kube-node-lease <name> -o yaml` | Время последнего Heartbeat (renewTime). |
| `kubectl get pods -A -o wide \| grep <node>` | Поды на конкретном узле. |
| `kubectl cordon <node>` | Пометить узел как непригодный для новых подов. |
| `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` | Вывести поды из узла. |
| `kubectl uncordon <node>` | Вернуть узел в строй. |
| `kubectl taint nodes <node> node.kubernetes.io/out-of-service=NoExecute:NoExecute` | Пометить узел как гарантированно недоступный. |
| `kubectl taint nodes <node> node.kubernetes.io/out-of-service-` | Снять taint out-of-service. |
| `kubectl delete pod <name> --force --grace-period=0` | Принудительное удаление Pod. |
| `kubectl get volumeattachment \| grep <node>` | Проверить VolumeAttachment узла. |
| `kubectl delete volumeattachment <name>` | Принудительно отсоединить том. |
| `kubectl patch pod <name> -p '{"metadata":{"finalizers":[]}}' --type=merge` | Снять финализаторы. |
| `kubectl get pv \| grep Released` | Найти непривязанные тома. |
| `kubectl get events -A --field-selector reason=TaintManagerEviction` | События выселения. |

---

## Граничные случаи и особенности

**Под с `hostNetwork` на недоступном узле:**
Поды с `hostNetwork: true` используют сетевое пространство узла. Если узел недоступен, такие поды не могут быть перезапущены на другом узле, пока порты не освободятся (особенно если приложение не освобождает порт корректно при завершении).

**DaemonSet на недоступном узле:**
DaemonSet-поды игнорируются `kubectl drain` (флаг `--ignore-daemonsets`). При unavailable узле Kubelet не может завершить DaemonSet-под, и он остаётся в `Terminating`. Kubelet не пересоздаёт DaemonSet-поды на других узлах — для этого контроллер DaemonSet должен удалить Pod-объект, что происходит только после снятия финализаторов.

**Pod с `externalTrafficPolicy: Local`:**
Если Service использует `externalTrafficPolicy: Local`, выселение пода с узла приводит к потере трафика на этом узле до переключения балансировщика. Для StatefulSet или системы с привязкой к узлу это может означать полную потерю доступности.

**Pod с `preStop` hook длиннее `terminationGracePeriodSeconds`:**
Если `preStop` hook выполняется дольше `terminationGracePeriodSeconds`, Kubelet принудительно завершает контейнер `SIGKILL`. При unavailable узле это не происходит, так как Kubelet не доступен. Под остаётся в `Terminating` до снятия финализаторов.

**Одновременное падение нескольких узлов:**
При падении >1 узла одновременно:
1. Все поды на обоих узлах перейдут в `Terminating`.
2. Контроллер будет пытаться пересоздать поды, но если здоровых узлов недостаточно — поды останутся в `Pending`.
3. ResourceQuota может заблокировать создание новых подов (Pod в `Terminating` всё ещё считается в квоте).
4. PDB может заблокировать `drain` здоровых узлов (если replica count < minAvailable).

**Graceful Node Shutdown (K8s 1.24+ GA):**
Если узел выключается через `shutdown` или `systemctl poweroff`, Kubelet получает сигнал через `systemd-logind` и корректно завершает поды. Но если узел выключается через `ipmitool power off` или hardware reset — Graceful Node Shutdown НЕ срабатывает. Настраивается через `shutdownGracePeriod` и `shutdownGracePeriodCriticalPods` в `KubeletConfiguration`.

---

**См. также:**
- [Taints и выселение](../NodeUnavailability/taints_and_eviction.md) — тайм-лайны и настройка tolerations.
- [Финализаторы и проблемы CSI](./finalizer_issues.md) — если том не отсоединяется или финализатор блокирует удаление.
- [Диагностика Pod Terminating](./diagnostics.md) — общий алгоритм поиска причин зависания.
