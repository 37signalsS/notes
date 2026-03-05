# Pod Terminating: Finalizer и CSI проблемы

## 2. Finalizer не удаляется

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

### Вариант A: Удаление VolumeAttachment

```bash
# Найти VolumeAttachment
kubectl get volumeattachment -o custom-columns=NAME:.metadata.name,PV:.spec.source.persistentVolumeName

# Удалить зависший VolumeAttachment
kubectl delete volumeattachment <attachment-name>
```

### Вариант B: Принудительное удаление finalizer (крайняя мера!)

```bash
# Патчинг finalizers
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":[]}}'
```

> **Warning:** Удаление finalizers без выполнения необходимых действий может привести к утечке ресурсов или потере данных!

## 3. Проблемы с CSI driver

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

> **См. также:** [`../../../Storage/CSI/csi_overview.md`](../../../Storage/CSI/csi_overview.md)
