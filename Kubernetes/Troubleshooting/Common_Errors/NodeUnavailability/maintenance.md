# Недоступность узла: Проблемы при обслуживании

В данном разделе рассматриваются критические ситуации, возникающие в процессе планового вывода узлов из эксплуатации (Cordon/Drain), их перезагрузки или возврата в кластер. Это **SDoT для диагностики проблем обслуживания** — процедурные аспекты описаны в [Обслуживание узлов](../../../Operations/node_maintenance.md).

## Основные определения

**Зависание обслуживания (Maintenance Hang)** — состояние, при котором процедура дренажа (`drain`) не завершается из-за блокирующих факторов на уровне API или хоста. Типичные блокеры: нарушение PDB, зависшие финализаторы, задержки отмонтирования томов.

**Забытый узел (Stale SchedulingDisabled)** — исправный узел в статусе `Ready`, который остался в режиме `SchedulingDisabled` из-за отсутствия команды `uncordon`. После завершения работ оператор забывает вернуть узел, что приводит к недостаточной емкости кластера.

**Eviction API** — внутренний механизм Kubernetes, используемый `kubectl drain` для безопасного удаления подов. В отличие от прямого `kubectl delete pod`, запрос `evict` проходит через **PodDisruptionBudget** и может быть отклонен API-сервером, если выселение нарушит бюджет. Это ключевое отличие: `delete` — немедленное удаление без проверок, `evict` — безопасное выселение с соблюдением политик доступности.

**NodeMaintenance API (Alpha в 1.31)** — декларативный способ управления обслуживанием узлов через Custom Resource. Позволяет автоматизировать отслеживание статуса работ, связывать их с условиями узла и упорядочивать через контроллер. Основные манифесты и регламент: [Обслуживание узлов](../../../Operations/node_maintenance.md#nodemaintenance-api-alpha-начиная с-kubernetes-131).

## Основные концепции

### Механизмы блокировки обслуживания

Процесс вывода узла может быть остановлен API-сервером по следующим причинам:

1.  **Нарушение PodDisruptionBudget (PDB)**: Если удаление пода нарушает условие `minAvailable` или `maxUnavailable`. Eviction API проверяет PDB **перед** каждым удалением. Если `ALLOWED DISRUPTIONS = 0`, выселение блокируется, и drain ожидает восстановления бюджета. Подробнее: [PodDisruptionBudget](../../../Autoscaling/pod_disruption_budget.md).

2.  **Наличие финализаторов (`finalizers`)**: Метаданные в поде (например, `kubernetes.io/pvc-protection` от CSI или кастомные финализаторы операторов), которые требуют выполнения внешнего действия перед удалением объекта. Пока финализатор не удален, под остаётся в `Terminating` бесконечно.

3.  **Локальные данные (`emptyDir`)**: Kubelet защищает поды с локальными данными от случайного удаления. С версии 1.31 флаг `--delete-local-data` полностью удален; требуется `--delete-emptydir-data`. Без этого флага drain откажется удалять поды с `emptyDir` volumes.

4.  **Bare Pods (Голые поды)**: Поды без владельца (отсутствует `ownerReferences`). `drain` не удаляет их без флага `--force`, так как после удаления под не будет пересоздан контроллером. Включение `--force` означает, что оператор осознанно теряет этот под.

5.  **Static Pods**: Управляются kubelet напрямую через манифесты в `/etc/kubernetes/manifests`. `drain` их **игнорирует** — они не удаляются Eviction API. Для удаления static pod необходимо физически удалить или переместить манифест из директории на хосте.

6.  **DaemonSet**: `drain` не удаляет поды DaemonSet по умолчанию (требуется `--ignore-daemonsets`). DaemonSet контроллер сам управляет жизненным циклом этих подов; они должны работать на всех узлах, поэтому их выселение бессмысленно — они пересоздадутся на том же узле.

### Улучшения в 1.31 для стабильного обслуживания

**Политика выселения нездоровых подов (`unhealthyPodEvictionPolicy`)**:
Начиная с Kubernetes 1.31, поле в PDB стало стабильным. Оно позволяет игнорировать "мертвые" поды (например, в `CrashLoopBackOff`) при расчете бюджета:
```yaml
spec:
  unhealthyPodEvictionPolicy: AlwaysAllow # Разрешает выселение нездоровых подов, даже если бюджет нарушен
```
Это критически важно для предотвращения бесконечного ожидания `drain` из-за подов, которые и так не функционируют.

## Практические сценарии

### Сценарий 1: Блокировка kubectl drain из-за PDB

**Симптом**: `kubectl drain` висит часами, в логах сообщения: `Cannot evict pod as it would violate the pod's disruption budget`.

**Диагностика**:
```bash
# 1. Найти PDB с 0 разрешенными выселениями
kubectl get pdb -A
# → NAMESPACE   NAME        MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → default     web-pdb     80%             N/A               0                     10m
# → monitoring  prom-pdb    1               N/A               0                     5m

# 2. Детальная информация о проблемном PDB
kubectl describe pdb web-pdb -n default
# → Name:           web-pdb
# → Min available:  80%
# → Current:        4 (здоровых подов)
# → Desired:        5 (минимум для соблюдения бюджета)
# → Allowed disruptions: 0
# → Conditions:
#   Type                  Status  Reason
#   ----                  ------  ------
#   DisruptionAllowed     False   InsufficientPods

# 3. Проверка какие поды попадают под этот PDB
kubectl get pods -n default -l app=web -o wide
# → NAME                     READY   STATUS    NODE
# → web-app-7d8b6c4f5-x1a2   1/1     Running   node-1
# → web-app-7d8b6c4f5-b3c4   1/1     Running   node-2
# → web-app-7d8b6c4f5-d5e6   0/1     Pending   node-3

# 4. Проверка условий PDB (K8s 1.30+)
kubectl get pdb web-pdb -o jsonpath='{.status.conditions}'
# → [{"type":"DisruptionAllowed","status":"False","reason":"InsufficientPods"}]
```

**Решение (по порядку приоритета)**:
1. Добавьте реплики в соответствующий Deployment/StatefulSet на **других узлах**, чтобы `currentHealthy` достиг `desiredHealthy`.
2. Временно уменьшите `minAvailable` или увеличьте `maxUnavailable` в манифесте PDB.
3. **Экстренно**: Используйте флаг `--disable-eviction`, который переключает команду на прямое удаление (игнорируя PDB):
   ```bash
   kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --disable-eviction --timeout=5m
   ```
   **Внимание**: После `--disable-eviction` поды удаляются через `delete`, без graceful shutdown. Используйте только если узел угрожает стабильности кластера.

### Сценарий 2: Поды застряли в Terminating (Finalizers)

**Симптом**: Узел пуст, но `drain` не завершается, так как поды висят в `Terminating`.

**Причина**: Зависший финализатор (например, `kubernetes.io/pvc-protection` от CSI, `foregroundDeletion` отDeleteController, или кастомные финализаторы от операторов). Пока финализатор не удален, API-сервер не завершает удаление объекта Pod.

**Диагностика**:
```bash
# 1. Найти все поды в Terminating на проблемном узле
kubectl get pods --all-namespaces --field-selector spec.nodeName=node-1,status.phase=Failed
# → NAMESPACE   NAME                     READY   STATUS       NODE
# → default     web-app-7d8b6c4f5-x1a2   0/1     Terminating  node-1

# 2. Проверить финализаторы
kubectl get pod web-app-7d8b6c4f5-x1a2 -n default -o jsonpath='{.metadata.finalizers}'
# → ["kubernetes.io/pvc-protection"]

# 3. Проверить условия завершения
kubectl get pod web-app-7d8b6c4f5-x1a2 -n default -o jsonpath='{.status.conditions}'
# → [{"type":"Ready","status":"False","reason":"Terminating","message":"..."}]

# 4. Проверить PVC с finalizers
kubectl get pvc -n default -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.finalizers}{"\n"}{end}'
# → data-web-0   ["kubernetes.io/pvc-protection"]
```

**Решение**:
Если вы уверены, что процессы завершены и данные в безопасности, удалите финализаторы:
```bash
# Удаление финализатора из пода
kubectl patch pod web-app-7d8b6c4f5-x1a2 -n default -p '{"metadata":{"finalizers":null}}' --type=merge
# → pod/web-app-7d8b6c4f5-x1a2 patched

# Если под управляется оператором, сначала проверьте CR оператора
kubectl get persistentvolumeclaims -n default data-web-0 -o jsonpath='{.metadata.finalizers}'
# → ["kubernetes.io/pvc-protection"]

# Удаление finalizer из PVC (если PVC больше не нужен)
kubectl patch pvc data-web-0 -n default -p '{"metadata":{"finalizers":null}}' --type=merge
```

**Важно:** Удаление финализаторов — экстренная мера. Убедитесь, что данные в Persistent Volume в безопасности и что оператор (если есть) не выполняет критическую операцию очистки.

### Сценарий 3: Узел NotReady после перезагрузки

**Симптом**: Хост загрузился, но статус в кластере `NotReady` или `Unknown`.

**Причины**: Автоматическое включение Swap, незагруженные модули ядра, неработающий CNI, незапущенный containerd, проблемы с сертификатами.

**Диагностические шаги на узле (по порядку)**:

```bash
# 1. Проверка Swap (блокирует kubelet по умолчанию)
swapon --show
# → NAME      TYPE      SIZE  USED  PRIO
# → /dev/sda2 partition 4G    0B    -2
# Если есть своп — отключите:
swapoff -a
# Для постоянного отключения добавьте в /etc/fstab строку:
# /dev/sda2  none  swap  sw  0  0

# 2. Проверка модулей ядра (обязательны для контейнеров и сети)
lsmod | grep -E "overlay|br_netfilter"
# → overlay               163840  0
# → br_netfilter          28672   0
# Если модули не загружены:
modprobe overlay
modprobe br_netfilter

# 3. Проверка статуса containerd
systemctl status containerd
# → containerd.service - containerd container runtime
#    Active: active (running) since Thu 2026-09-04 17:30:00 UTC; 5min ago
# Если не запущен:
systemctl start containerd

# 4. Проверка kubelet
systemctl status kubelet
# → kubelet.service - kubelet: The Kubernetes Node Agent
#    Active: active (running) since Thu 2026-09-04 17:30:00 UTC; 5min ago

# 5. Проверка логов kubelet (поиск ошибок)
journalctl -u kubelet -n 50 --no-pager
# Типичные ошибки:
# → E0904 17:35:00.123456 123456 reflector.go:150] Failed to list *v1.Node: Get "https://10.0.1.1:6443/api/v1/nodes": dial tcp 10.0.1.1:6443: connect: connection refused
# → E0904 17:35:00.654321 123456 runtime.go:78] Abort: PLEG is not healthy

# 6. Проверка CNI-бинарников и конфигурации
ls /opt/cni/bin/
# → bridge  dhcp  flannel  host-local  loopback  macvlan  ptp  sbr  vlan
ls /etc/cni/net.d/
# → 10-calico.conflist  99-loopback.conf

# 7. Проверка NetworkUnavailable
kubectl get node <node-name> -o jsonpath='{.status.conditions[?(@.type=="NetworkUnavailable")].status}'
# → False
# Если True — CNI не работает

# 8. Проверка конфигурации CNI
cat /etc/cni/net.d/10-calico.confliste
# → {"name":"calico-k8s-network","cniVersion":"0.3.1","plugins":[{"type":"calico",...}]}

# 9. Проверка модулей conntrack
lsmod | grep nf_conntrack
# → nf_conntrack          180224  6 nf_nat,nf_nat_masquerade_ipv4,calico
```

### Сценарий 4: Сбой Graceful Node Shutdown

**Симптом**: При выключении узла (`systemctl poweroff`, IPMI) поды убиваются по `SIGKILL` мгновенно, не успевая сохранить состояние или завершить транзакции. После включения узла в логах видно `OOMKilled` или `Error` из-за некорректного завершения.

**Причина**: Неверная конфигурация `KubeletConfiguration`, отсутствие `systemd-logind`, или аппаратное выключение (hard reset, IPMI power off) без сигнала ACPI.

**Верификация**:
```bash
# 1. Проверка конфигурации kubelet
cat /var/lib/kubelet/config.yaml | grep -E "shutdown|gracePeriod"
# → shutdownGracePeriod: 30s
# → shutdownGracePeriodCriticalPods: 10s

# Если параметры отсутствуют — Graceful Shutdown не работает

# 2. Проверка наличия systemd-logind
systemctl status systemd-logind
# → systemd-logind.service - Login Service
#    Active: active (running) since Thu 2026-09-04 17:30:00 UTC; 5min ago

# Если сервис не активен — включите и запустите:
systemctl enable --now systemd-logind

# 3. Проверка логов Shutdown Manager
journalctl -u kubelet -g "Shutdown manager" --since "1 hour ago"
# Примеры сообщений:
# → I0904 17:35:00.123456 123456 shutdown_manager.go:100] Attempting to graceful shutdown pods
# → I0904 17:35:30.654321 123456 shutdown_manager.go:150] Graceful shutdown completed

# 4. Проверка Inhibit Locks (барьеры для systemd-logind)
systemd-inhibit --list
# → WHAT                          WHO        WHY                       MODE
# → kubelet                       kubelet    Kubelet graceful shutdown delay

# 5. Проверка событий завершения подов
kubectl get events -A --field-selector reason=Killing --sort-by='.lastTimestamp' | tail -10
# → default   3m    Normal   Killing   pod/web-app-7d8b   Stopping container web
# → default   3m    Normal   Killing   pod/db-0           Stopping container db
```

### Сценарий 5: Зависшие VolumeAttachments

**Симптом**: `drain` завершен, но узел нельзя удалить из инфраструктуры, так как блочные диски (EBS/PD/iSCSI/FC) все еще привязаны к нему. В логах CSI-контроллера ошибки `Failed to detach volume`.

**Причина**: CSI driver не смог отмонтировать том из-за зависших процессов на узле, блокировок файловой системы, или аппаратной проблемы с сетевым хранилищем. Для томов с **ReadWriteOnce (RWO)** семантикой Kubernetes дожидается `detach` перед тем, как разрешит новому поду примонтировать его на другом узле.

**Диагностика**:
```bash
# 1. Найти все VolumeAttachment для проблемного узла
kubectl get volumeattachments -o wide | grep <node-name>
# → NAME                                   ATTACHMENTSTATUS   NODE         AGE
# → csi-1234567890abcdef                   detaching          node-1       30m
# → csi-abcdef1234567890                   attached           node-1       25m

# 2. Проверить статус конкретного VolumeAttachment
kubectl get volumeattachment csi-abcdef1234567890 -o yaml
# → apiVersion: storage.k8s.io/v1
# → kind: VolumeAttachment
# → metadata:
# →   name: csi-abcdef1234567890
# → spec:
# →   nodeName: node-1
# →   source:
# →     persistentVolumeName: pvc-abc123
# → status:
# →   attached: true
# →   attachmentError: "detach timeout exceeded"

# 3. Проверить PVC и его привязку
kubectl get pvc -A -o wide | grep <pv-name>
# → default   data-web-0   Bound   pvc-abc123   100Gi   RWO   local-path   30d

# 4. Если узел доступен по SSH — проверить зависшие процессы
ssh node-1 "ps aux | grep -E 'mount|umount|dd|fsck'"
# → root     12345  0.0  0.0  123456  7890 ?        D    17:30   0:00 mount /dev/sdb1 /var/lib/kubelet/pods/...
```

**Решение**:
```bash
# Если узел физически выключен или не восстановится:
# 1. Удалить VolumeAttachment вручную
kubectl delete volumeattachment csi-abcdef1234567890
# → volumeattachment.storage.k8s.io "csi-abcdef1234567890" deleted

# 2. Если том все еще "attached" — проверить через API провайдера
# Для AWS: aws ec2 describe-volumes --filters Name=attachment.instance-id,Values=<instance-id>
# Для GCP: gcp compute disks list --filter="users~node-1"

# 3. Принудительное отмонтирование (если узел доступен)
ssh node-1 "umount -f /var/lib/kubelet/pods/abc123/volumes/kubernetes.io~csi/pvc-abc123/mount"

# 4. После отмонтирования — повторить удаление
kubectl delete volumeattachment csi-abcdef1234567890
```

**Важно:** Для томов **ReadWriteMany (RWX)** (NFS, CephFS) проблема отсутствует — том может быть примонтирован к нескольким узлам одновременно, и `detach` не требуется.

---

## Сценарий 6: DaemonSet блокирует полный drain узла

**Симптом**: После `kubectl drain --ignore-daemonsets` на узле остаются системные поды (kube-proxy, CNI, логирование). Это нормальное поведение, но иногда оператор ожидает полного опустошения узла.

**Причина**: DaemonSet контроллер автоматически добавляет `toleration` для `unschedulable:NoSchedule` всем подам DaemonSet. Это позволяет системным компонентам продолжать работу на изолированном узле.

**Диагностика**:
```bash
# 1. Проверить какие поды DaemonSet остались на узле
kubectl get pods --all-namespaces --field-selector spec.nodeName=node-1 -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,OWNER:.metadata.ownerReferences[0].kind
# → NAMESPACE       NAME                    STATUS    OWNER
# → kube-system     kube-proxy-abc12        Running   DaemonSet
# → kube-system     calico-node-xyz34       Running   DaemonSet
# → kube-system     node-exporter-def56     Running   DaemonSet

# 2. Проверить DaemonSet, которые НЕ должны работать на обслуживаемом узле
kubectl get ds -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,DESIRED:.status.desiredNumberScheduled,READY:.status.numberReady
# → NAMESPACE       NAME                    DESIRED   READY
# → kube-system     kube-proxy              3         3
# → kube-system     calico-node             3         3

# 3. Проверить, какие DaemonSet поды имеют local data
kubectl get pods -n kube-system -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.volumes[*].emptyDir}{"\n"}{end}' | grep -v "^$"
```

**Решение**:
- **Нормальное поведение**: DaemonSet поды останутся на узле. Это штатная ситуация — они необходимы для работы инфраструктуры.
- **Если нужен полный drain**: Используйте `--delete-emptydir-data` и убедитесь, что DaemonSet контроллер не блокирует удаление (проверьте `kubectl get events --field-selector reason=ScalingReplicaSet`).

---

## Сценарий 7: Задержка отмонтирования RWO томов

**Симптом**: `drain` завершен, но поды на других узлах остаются в `Pending` с ошибкой `Multi-Attach error for volume "pvc-xxx"`. Система хранения не может отмонтировать блокировку от удаленного узла.

**Причина**: Тома с **ReadWriteOnce (RWO)** семантикой привязаны к одному узлу. После drain должен выполниться `detach` (отвязка от хоста), что может занимать 2–5 минут в зависимости от CSI-провайдера и типа хранилища (блокочные устройства, iSCSI, FC).

**Диагностика**:
```bash
# 1. Проверить Pending-поды
kubectl get pods -o wide | grep Pending
# → NAME                     READY   STATUS    NODE
# → web-app-new-abc123       0/1     Pending

# 2. Проверить ошибку в описании пода
kubectl describe pod web-app-new-abc123 | grep -A 5 Events
# → Events:
# →   Type     Reason              Age   From               Message
# →   ----     ------              ----   ----               -------
# →   Warning  FailedAttachVolume  5m    attachdetach-controller  Multi-Attach error for volume "pvc-abc123"

# 3. Проверить VolumeAttachment
kubectl get volumeattachments -o wide | grep pvc-abc123
# → NAME                          ATTACHMENTSTATUS   NODE         AGE
# → csi-1234567890                detaching          node-old     10m

# 4. Проверить статус Volume через CSI
kubectl get pv pvc-abc123 -o jsonpath='{.status.phase}'
# → Bound

# 5. Проверить, где том примонтирован
kubectl get pv pvc-abc123 -o jsonpath='{.spec.claimRef.name}' && kubectl get pv pvc-abc123 -o jsonpath='{.status.phase}'
```

**Решение**:
```bash
# 1. Дождаться завершения detach (обычно 2-5 минут)
# Мониторинг статуса:
watch -n 5 "kubectl get volumeattachments | grep pvc-abc123"
# → csi-1234567890   detaching   node-old   15m
# → ... спустя 5 минут ...
# → csi-1234567890   (удалён)

# 2. Если detach завис — проверить CSI controller logs
kubectl logs -n kube-system -l app=csi-attacher -f

# 3. Если узел мертв — удалить VolumeAttachment вручную
kubectl delete volumeattachment csi-1234567890

# 4. После успешного detach под на новом узле перейдет в Running
kubectl get pods -o wide | grep web-app-new
# → NAME                     READY   STATUS    NODE
# → web-app-new-abc123       1/1     Running   node-new
```

**Профилактика**: Для критических сервисов используйте **ReadWriteMany (RWX)** тома (NFS, CephFS), которые допускают одновременное примонтирование к нескольким узлам.

---

## Сценарий 8: Забытый узел в режиме SchedulingDisabled

**Симптом**: После завершения обслуживания (обновление ОС, замена оборудования) оператор забыл выполнить `uncordon`. Узел работает в статусе `Ready`, но `SchedulingDisabled`, что снижает емкость кластера.

**Диагностика**:
```bash
# 1. Найти узлы с SchedulingDisabled
kubectl get nodes -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[?(@.type=="Ready")].status,SCHEDULING:.spec.unschedulable
# → NAME      STATUS    SCHEDULING
# → node-1    True      <unset>
# → node-2    True      true
# → node-3    True      <unset>

# 2. Проверить, что узел действительно исправен
kubectl describe node node-2 | grep -A 10 Conditions
# → Ready               True    Mon, 04 Sep 2026 17:30:00 +0000   KubeletReady    kubelet is posting ready status

# 3. Проверить, есть ли Taint unschedulable
kubectl get node node-2 -o jsonpath='{.spec.taints}'
# → [{"key":"node.kubernetes.io/unschedulable","effect":"NoSchedule"}]
```

**Решение**:
```bash
# Вернуть узел в пул планирования
kubectl uncordon node-2
# → node/node-2 uncordoned

# Проверить, что узел теперь принимает поды
kubectl get nodes -o wide
# → NAME      STATUS   ROLES    AGE   VERSION   INTERNAL-IP     OS-IMAGE
# → node-2    Ready    <none>   30d   v1.31.0   10.0.1.11       Ubuntu 22.04.3 LTS
```

**Профилактика**: Настройте алерт на длительное нахождение узла в `SchedulingDisabled`:
```yaml
- alert: NodeSchedulingDisabledLongPeriod
  expr: kube_node_spec_unschedulable == 1
  for: 2h
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.node }} в SchedulingDisabled более 2 часов"
```

---

## Мониторинг и алертинг

### Метрики для контроля обслуживания

| Метрика Prometheus | Описание |
| :--- | :--- |
| `kube_node_spec_unschedulable` | Узел в режиме `SchedulingDisabled` (1 = да) |
| `kube_pod_status_reason` | Причины завершения подов (включая `evicted`) |
| `kube_poddisruptionbudget_status_disruptions_allowed` | Количество разрешенных выселений по PDB |
| `kube_poddisruptionbudget_status_current_healthy` | Текущее количество здоровых подов в PDB |
| `kube_node_status_condition` | Все Conditions узла (Ready, MemoryPressure и т.д.) |

### Примеры алертов (PrometheusRule)

```yaml
groups:
  - name: node-maintenance
    rules:
      # Узел в SchedulingDisabled более 2 часов (забытый узел)
      - alert: NodeSchedulingDisabledLongPeriod
        expr: kube_node_spec_unschedulable == 1
        for: 2h
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.node }} в SchedulingDisabled более 2 часов"
          description: "Возможно, узел забыли вернуть после обслуживания"

      # PDB заблокирован (drain завис)
      - alert: PDBDisruptionsBlocked
        expr: kube_poddisruptionbudget_status_disruptions_allowed == 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "PDB {{ $labels.poddisruptionbudget }} заблокирован"
          description: "ALLOWED DISRUPTIONS = 0 уже 10 минут. Drain может зависнуть."

      # Узел NotReady после обслуживания (ошибка возврата)
      - alert: NodeNotReadyAfterMaintenance
        expr: kube_node_status_condition{condition="Ready",status="true"} == 0 and kube_node_spec_unschedulable == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Узел {{ $labels.node }} не готов после uncordon"
          description: "Узел был возвращен в кластер, но находится в NotReady"

      # Высокий churn (массовое выселение подов)
      - alert: HighPodEvictionRate
        expr: rate(kube_pod_status_reason{reason="Evicted"}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень выселения подов"
          description: "Более 10% подов выселяются в минуту. Проверьте обслуживание узлов."
```

### Автоматизация обслуживания

| Инструмент | Назначение | Особенности |
| :--- | :--- | :--- |
| **Kured** | Автоматический drain/reboot при наличии `/var/run/reboot-required` | Следит за файлом-маркером, выполняет безопасный drain с учетом PDB. Идеален для патчей безопасности ОС. |
| **Draino** | Автоматический drain при совпадении Conditions/Taints | Реагирует на `MemoryPressure`, `DiskPressure` и другие Conditions. Полезен для самовосстановления. |
| **NodeMaintenance Controller** | Управление через CR `NodeMaintenance` | Декларативный подход: создайте CR — контроллер изолирует и дренирует узел, вернет после `endTime`. |
| **Cluster Autoscaler** | Удаление неиспользуемых узлов | Включает логику drain перед удалением. Автоматически оптимизирует пул узлов. |

### Рекомендации по мониторингу

1. **Настройте алерты** на `NodeSchedulingDisabledLongPeriod` и `PDBDisruptionsBlocked` — это самые частые проблемы обслуживания.
2. **Используйте Grafana дашборд** для отслеживания `ALLOWED DISRUPTIONS` в реальном времени во время drain.
3. **Централизованное логирование** kubelet через `journalctl` + агрегатор (Loki, ELK) позволяет быстро находить ошибки.
4. **Отслеживание событий** `kubectl get events -A --field-selector reason=Eviction` показывает все выселения в кластере.

---

## Дополнительная информация

- [Диагностика недоступности узла](./diagnostics.md) — алгоритм поиска причин `NotReady`.
- [Проблемы рантайма](./runtime_issues.md) — если `containerd` не стартует после обслуживания.
- [Pod Disruption Budget](../../../Autoscaling/pod_disruption_budget.md) — архитектура защитных бюджетов.
- [Обслуживание узлов: Cordon, Drain и NodeMaintenance API](../../../Operations/node_maintenance.md) — полный регламент плановых работ.
