# CreateContainerConfigError: Проблемы с PVC

## PVC не найден или не привязан

**Сообщение:**
```
Error: persistentvolumeclaim "data-pvc" not found
unable to provision volume: persistentvolumeclaim "data-pvc" not found
```

**Причина:** PVC не существует или находится в статусе `Pending`.

**Диагностика:**
```bash
kubectl describe pvc data-pvc
```

### Возможные причины PVC в Pending

| Причина | Решение |
|---------|---------|
| **Нет PV** | Создать PV или настроить StorageClass |
| **Неверный StorageClass** | Проверить: `kubectl get storageclass` |
| **Нехватка места** | Освободить место или увеличить quota |
| **AccessMode несовместим** | Изменить accessMode |

**Решение:**
```yaml
# Создание PVC с StorageClass
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

**Создание PV (если нет dynamic provisioning):**
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

> **См. также:** [`../../../Storage/pv_and_pvc.md`](../../../Storage/pv_and_pvc.md), [`../../../Storage/CSI/csi_drivers_comparison.md`](../../../Storage/CSI/csi_drivers_comparison.md)
