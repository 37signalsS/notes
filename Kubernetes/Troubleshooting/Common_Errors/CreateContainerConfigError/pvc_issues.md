# CreateContainerConfigError: Проблемы с PVC

## Definitions

**PVC-related CreateContainerConfigError** — ошибка, возникающая когда Pod ссылается на PersistentVolumeClaim, который не существует, не привязан (Pending) или не может быть смонтирован.

## Basic Concepts

### Типичные сообщения об ошибке

| Сообщение | Причина |
|-----------|---------|
| `persistentvolumeclaim "x" not found` | PVC с указанным именем не существует в namespace |
| `unable to provision volume` | StorageClass не может динамически создать PV |
| `volume "x" not found` | PVC существует, но не Bound |

### Основные причины PVC в статусе Pending

| Причина | Диагностика | Решение |
|---------|-------------|---------|
| **Нет подходящего PV** (static) | `kubectl get pv` | Создать PV с matching StorageClassName и accessMode |
| **Нет StorageClass** | `kubectl get storageclass` | Создать StorageClass с provisioner |
| **Provisioner недоступен** | `kubectl get pods -n kube-system \| grep provisioner` | Проверить доступность provisioner (NFS, CSI driver) |
| **AccessMode несовместим** | `kubectl describe pvc` | Изменить accessMode в PVC или создать PV с нужным режимом |
| **Нехватка квоты** | `kubectl describe resourcequota` | Увеличить quota или запросить меньший объём |
| **Topology mismatch** | `kubectl describe pvc` | Использовать `volumeBindingMode: WaitForFirstConsumer` |

> Базовые концепции PV/PVC/StorageClass: [pv_and_pvc.md](../../../../Storage/pv_and_pvc.md).

## Practical Scenarios

### Сценарий 1: PVC не существует

**Сообщение:**

```
Error: persistentvolumeclaim "data-pvc" not found
```

**Диагностика:**

```bash
kubectl get pvc data-pvc -n <namespace>
```

**Решение:** Создать PVC.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard
  resources:
    requests:
      storage: 10Gi
```

### Сценарий 2: PVC в статусе Pending (dynamic provisioning)

**Диагностика:**

```bash
# Статус PVC
kubectl describe pvc data-pvc

# Проверка StorageClass
kubectl get storageclass

# Проверка provisioner
kubectl get pods -n kube-system | grep -E "nfs|csi|ebs|provisioner"
```

**Частые причины:**

- **StorageClass не существует** — создать или исправить имя в PVC
- **Provisioner не установлен** — установить NFS subdir external provisioner, CSI driver
- **Quota exceeded** — проверить ResourceQuota namespace

### Сценарий 3: PVC в статусе Pending (static provisioning)

**Диагностика:**

```bash
# Проверка доступных PV
kubectl get pv

# Проверка совместимости PV и PVC
kubectl describe pvc data-pvc
# Events: "No matching volume" — PV не подходит по размеру, режиму или StorageClass
```

**Решение:** Создать PV, matching требованиям PVC.

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: data-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: manual
  hostPath:
    path: "/mnt/data"
```

### Сценарий 4: AccessMode несовместим

**Симптом:** PVC Pending, в Events — `could not find information about volume`.

**Причина:** PVC запрашивает режим, который PV или StorageClass не поддерживает.

**Диагностика:**

```bash
# Режимы доступа PV
kubectl get pv <pv-name> -o jsonpath='{.spec.accessModes}'

# Режимы доступа PVC
kubectl get pvc <pvc-name> -o jsonpath='{.spec.accessModes}'
```

**Решение:** Привести accessMode PVC в соответствие с доступными PV или StorageClass.

| Хранилище | Поддерживаемые режимы |
|-----------|----------------------|
| Local Path, EBS, RBD | `ReadWriteOnce` |
| NFS, CephFS | `ReadWriteMany`, `ReadOnlyMany`, `ReadWriteOnce` |

### Сценарий 5: PVC привязан, но ошибка сохраняется

**Причина:** Pod запущен до того, как PVC перешёл в Bound.

**Решение:** После перехода PVC в Bound Kubernetes автоматически восстановит Pod (~10–30 сек). При необходимости — перезапустить:

```bash
kubectl rollout restart deployment/<deployment-name> -n <namespace>
```

## Additional Information

### Связанные ресурсы

- Определения: [definitions.md](./definitions.md)
- Диагностика: [diagnostics.md](./diagnostics.md)
- PV/PVC концепции: [pv_and_pvc.md](../../../../Storage/pv_and_pvc.md)
- StorageClass: [storageclass.md](../../../../Storage/storageclass.md)
- CSI: [csi_overview.md](../../../../Storage/CSI/csi_overview.md)
- PVC Pending (Pod Pending context): [pod_pending/common_cases_and_solutions.md](../../pod_pending/common_cases_and_solutions.md)
