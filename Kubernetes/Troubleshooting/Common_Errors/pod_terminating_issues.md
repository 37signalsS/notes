# Проблемы с завершением подов (`Terminating`)

## Определения

**`Terminating`** — статус пода, означающий, что под был удален (получил `deletionTimestamp`), но не может завершить работу и освободить ресурсы.

> - Volumes: [`pod_volumes.md`](../../Base/Pod/pod_volumes.md)
> - PV/PVC: [`pv_and_pvc.md`](../../Storage/pv_and_pvc.md)
> - Node Maintenance: [`node_maintenance.md`](../../Operations/node_maintenance.md)
> - High Availability: [`high_availability.md`](../../Base/high_availability.md)
> - Finalizers: [см. ниже](#finalizers)

## Основные концепции

### Workflow удаления пода

```
kubectl delete pod
    ↓
API устанавливает deletionTimestamp
    ↓
Pod переходит в Terminating
    ↓
kubelet получает уведомление
    ↓
Остановка контейнеров (SIGTERM → SIGKILL)
    ↓
Размонтирование volumes
    ↓
Удаление записи из etcd
    ↓
Pod удален
```

**Время ожидания:**
- `terminationGracePeriodSeconds` (по умолчанию 30s) — время на graceful shutdown
- После — SIGKILL и принудительное удаление

### Finalizers

**Finalizer** — это механизм, который предотвращает удаление объекта из etcd до тех пор, пока не будут выполнены определенные действия.

**Стандартные finalizers:**

| Finalizer | Описание |
|-----------|----------|
| `kubernetes.io/pod-protection` | Защита пода от удаления |
| `foregroundDeletion` | Ожидание удаления зависимостей |
| `external-attacher/csi-driver` | CSI volume attachment |
| `kubernetes.io/pvc-protection` | Защита PVC |

**Проверка finalizers:**
```bash
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'
```

### Причины зависания в Terminating

| Причина | % случаев | Описание |
|---------|-----------|----------|
| **Volume unmount** | ~50% | Volume не может размонтироваться |
| **Finalizers** | ~30% | Finalizer не удаляется |
| **Node unavailable** | ~15% | Узел недоступен, kubelet не отвечает |
| **API server issues** | ~5% | Проблемы с control plane |

## Практические сценарии

### Диагностика: пошаговый чек-лист

#### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в выводе:**
```
Name:         my-pod
Namespace:    default
Status:       Terminating
Deletion Timestamp:  2026-03-05T10:00:00Z
Finalizers:    [kubernetes.io/pod-protection external-attacher/csi-driver]
```

#### Шаг 2: Проверка finalizers

```bash
# Проверка finalizers
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'

# Полная информация в JSON
kubectl get pod <pod-name> -o json
```

#### Шаг 3: Проверка volumes

```bash
# Volumes пода
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes}'

# Mounts на узле (требуется SSH)
findmnt | grep <pod-uid>
```

#### Шаг 4: Проверка узла

```bash
# Статус узла
kubectl get node <node-name>

# Events узла
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name>
```

#### Шаг 5: Получение UID пода

```bash
kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}'
```

### Распространенные случаи и решения

#### 1. Volume не может размонтироваться

**Сообщение:**
```
Unable to attach or mount volumes: timed out waiting for the condition
volume "data-vol" is still attached to node
```

**Причина:** Процесс все еще использует файлы на томе, или CSI driver не отвечает.

**Диагностика:**
```bash
# SSH на узел
ssh <node-name>

# Получение UID пода
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')

# Поиск точек монтирования
findmnt | grep $POD_UID

# Поиск процессов, использующих volume
lsof +D /var/lib/kubelet/pods/$POD_UID/volumes
fuser -vm /var/lib/kubelet/pods/$POD_UID
```

**Решение:**
```bash
# Принудительное размонтирование (lazy unmount)
umount -l /var/lib/kubelet/pods/$POD_UID/volumes/*/mount

# Или конкретную точку
umount -l <mount-point>

# Перезапуск kubelet (если не помогает)
systemctl restart kubelet
```

> **Warning:** Lazy unmount (`-l`) может привести к потере данных, если приложение еще пишет в volume.

#### 2. Finalizer не удаляется

**Сообщение:**
```
Finalizers: [external-attacher/csi-driver]
Deletion Timestamp: <старая>
```

**Причина:** Внешний контроллер (CSI, cloud provider) не удаляет finalizer.

**Диагностика:**
```bash
# Проверка CSI driver
kubectl get pods -n kube-system -l app=csi-driver

# Проверка VolumeAttachment
kubectl get volumeattachment | grep <pod-uid>
```

**Решение:**

**Вариант A: Удаление VolumeAttachment**
```bash
# Найти VolumeAttachment
kubectl get volumeattachment -o custom-columns=NAME:.metadata.name,PV:.spec.source.persistentVolumeName

# Удалить зависший VolumeAttachment
kubectl delete volumeattachment <attachment-name>
```

**Вариант B: Принудительное удаление finalizer (крайняя мера!)**
```bash
# Патчинг finalizers
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":[]}}'
```

> **Warning:** Удаление finalizers без выполнения необходимых действий может привести к утечке ресурсов или потере данных!

#### 3. Узел недоступен

**Сообщение:**
```
Node <node-name> is unreachable
```

**Причина:** Узел в статусе `NotReady` или `Unknown`, kubelet не отвечает.

**Диагностика:**
```bash
kubectl get nodes
kubectl describe node <node-name>
```

**Решение:**
```bash
# Если узел не вернется — принудительное удаление
kubectl delete pod <pod-name> --force --grace-period=0

# Для StatefulSet — важно удалить PVC отдельно если нужно
kubectl delete pvc <pvc-name>
```

> **См. также:** [`node_unavailability.md`](./node_unavailability.md), [`node_maintenance.md`](../../Operations/node_maintenance.md)

#### 4. Проблемы с CSI driver

**Сообщение:**
```
rpc error: code = Internal desc = volume detachment failed
```

**Причина:** CSI driver не может отсоединить volume.

**Диагностика:**
```bash
# Статус CSI driver
kubectl get csidrivers

# Логи CSI driver
kubectl logs -n kube-system -l app=csi-driver

# Проверка VolumeAttachment
kubectl describe volumeattachment <name>
```

**Решение:**
```bash
# Перезапуск CSI driver
kubectl rollout restart daemonset -n kube-system <csi-driver-ds>

# Удаление зависших VolumeAttachment
kubectl delete volumeattachment -l <label-selector>
```

> **См. также:** [`csi_overview.md`](../../Storage/CSI/csi_overview.md)

#### 5. PodDisruptionBudget блокирует удаление

**Сообщение:**
```
Cannot evict pod as it would violate the pod's disruption budget.
```

**Причина:** PDB не позволяет удалить под, так как это нарушит `minAvailable`.

**Диагностика:**
```bash
kubectl get pdb
kubectl describe pdb <pdb-name>
```

**Решение:**
```bash
# Временное удаление PDB (не рекомендуется для production)
kubectl delete pdb <pdb-name>

# Или увеличение maxUnavailable
kubectl patch pdb <pdb-name> -p '{"spec":{"maxUnavailable":2}}'
```

> **См. также:** [`pod_disruption_budget.md`](../../Autoscaling/pod_disruption_budget.md)

### Принудительное удаление (крайняя мера)

```bash
# Принудительное удаление с bypass grace period
kubectl delete pod <pod-name> --force --grace-period=0

# Удаление напрямую из etcd (только если API не отвечает)
# ОПАСНО: Может привести к inconsistency!
```

> **Warning:** Принудительное удаление не решает проблему на узле. Volume может остаться в состоянии "attached", данные могут быть потеряны.

### Автоматизация диагностики

```bash
#!/bin/bash
# Скрипт диагностики Terminating pod

POD=$1
NS=${2:-default}

echo "=== Статус пода ==="
kubectl get pod $POD -n $NS -o wide

echo -e "\n=== Finalizers ==="
kubectl get pod $POD -n $NS -o jsonpath='{.metadata.finalizers}'
echo

echo -e "\n=== Volumes ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.volumes}'
echo

echo -e "\n=== Описание ==="
kubectl describe pod $POD -n $NS | grep -A 10 "Status:\|Finalizers:\|Conditions:"

echo -e "\n=== События ==="
kubectl get events -n $NS --field-selector involvedObject.name=$POD --sort-by='.lastTimestamp'
```

## Дополнительная информация

### Graceful shutdown

```yaml
# Настройка graceful shutdown
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  terminationGracePeriodSeconds: 60  # Увеличенное время
  containers:
  - name: app
    image: my-app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 10; kill -TERM 1"]
```

### Сравнение методов удаления

| Метод | Описание | Когда использовать |
|-------|----------|-------------------|
| `kubectl delete pod` | Стандартное удаление | Нормальный случай |
| `--grace-period=N` | Задать время ожидания | Приложение требует больше времени |
| `--force --grace-period=0` | Принудительное | Pod застрял в Terminating |
| `kubectl patch finalizers` | Удаление finalizers | Крайняя мера, когда ничего не помогает |

### Best Practices

| Практика | Описание |
|----------|----------|
| **Настройте preStop hook** | Graceful shutdown приложений |
| **Используйте PDB** | Защита от массового удаления |
| **Мониторьте finalizers** | Алерты на долгие Terminating |
| **Избегайте force delete** | Только когда другие методы не работают |
| **Проверяйте volumes** | Перед удалением finalizers |

### Ссылки

- [Pod Termination](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination)
- [Finalizers](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/)
- [Graceful Shutdown](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination)
