# Pod Terminating: Volume Unmount проблемы

## Определения

**Volume Unmount** — процесс размонтирования тома с узла kubelet'ом при удалении пода. Выполняется после завершения контейнеров.

**Stale Mount** — состояние, при котором точка монтирования остаётся активной, хотя pod удалён. Volume не освобождается, kubelet не может завершить удаление.

**Kubelet Volume Manager** — компонент kubelet, отвечающий за mount/unmount volumes. Отслеживает статус томов и выполняет cleanup.

**`umount -l` (Lazy Unmount)** — отсоединение файловой системы с отложенным освобождением ресурсов. Монтирование исчезает из namespace, но процессы могут продолжать писать в файловую систему.

---

## Базовые концепции

### Процесс размонтирования volumes

```
Контейнеры завершены (SIGTERM / SIGKILL)
    ↓
Kubelet Volume Manager начинает cleanup
    ↓
Для каждого volume в spec.volumes:
  1. Проверка, что все процессы остановлены
  2. Unmount volume с узла
  3. Для CSI: detach volume (через external-attacher)
    ↓
Удаление finalizers (kubernetes.io/pvc-protection)
    ↓
Pod удалён из etcd
```

### Почему volume не размонтируется

| Причина | Механизм |
|---------|----------|
| **Процесс держит файл** | Контейнер не остановился полностью, процесс открыл файл на томе |
| **Stale mount** | Монтирование "зависло" — kubelet не может отмонтировать |
| **CSI driver не отвечает** | external-attacher не подтверждает detach |
| **kubelet завис** | Volume Manager не обрабатывает cleanup |
| **Несколько pod используют volume** | Другой pod всё ещё монтирует этот же PVC |

### Отличие от CSI detachment (finalizer_issues.md)

| Уровень | Проблема | Где диагностируется |
|---------|----------|---------------------|
| **Unmount** (этот файл) | Volume не размонтируется на узле | SSH → узел, `findmnt`, `lsof` |
| **Detach** (finalizer_issues.md) | VolumeAttachment не удаляется | `kubectl get volumeattachment`, CSI logs |

Unmount — проблема на узле (mount point). Detach — проблема на уровне API (объект VolumeAttachment).

Общая диагностика: [Diagnostics](./diagnostics.md). Определения: [Definitions](./definitions.md).

---

## Практические сценарии

### Сценарий 1: Диагностика — процесс держит volume

**Симптом:**

```
Events:
  Warning  FailedUnmountVolume  Unable to unmount volumes for pod "my-pod":
  volume "data-vol" is still in use
```

**Диагностика:**

```bash
# 1. Получить UID пода
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')

# 2. SSH на узел
ssh <node-name>

# 3. Найти точки монтирования пода
findmnt | grep $POD_UID

# 4. Найти процессы, использующие volume
lsof +D /var/lib/kubelet/pods/$POD_UID/volumes
fuser -vm /var/lib/kubelet/pods/$POD_UID

# 5. Проверить, живы ли контейнеры
crictl ps | grep $POD_UID
```

**Решение:**

```bash
# 1. Принудительно остановить контейнер
crictl stop <container-id>
crictl rm <container-id>

# 2. Если не помогло — lazy unmount
umount -l /var/lib/kubelet/pods/$POD_UID/volumes/*/mount

# 3. Перезапуск kubelet (если stale mount)
systemctl restart kubelet
```

> **Warning:** `umount -l` отсоединяет файловую систему, но процессы могут продолжать писать. Данные могут быть потеряны.

### Сценарий 2: Stale mount — kubelet не может unmount

**Симптом:** Pod в Terminating, контейнеры завершены, volume не размонтируется.

**Диагностика:**

```bash
# SSH на узел
ssh <node-name>

POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')

# Проверить точки монтирования
findmnt -t ext4,xfs | grep $POD_UID

# Проверить, есть ли активные mount
mount | grep $POD_UID
```

**Решение — Вариант A: Lazy unmount:**

```bash
# Найти все mount points
mount | grep $POD_UID | awk '{print $3}'

# Lazy unmount каждого
for mp in $(mount | grep $POD_UID | awk '{print $3}'); do
  umount -l "$mp"
done
```

**Решение — Вариант B: Перезапуск kubelet:**

```bash
# Проверить статус kubelet
systemctl status kubelet

# Перезапуск
systemctl restart kubelet

# Проверить логи
journalctl -u kubelet -f --no-pager | grep -i "unmount\|volume"
```

После перезапуска kubelet Volume Manager повторит cleanup.

### Сценарий 3: Volume используется другим pod

**Симптом:** PVC смонтирован в нескольких подах, один pod не может unmount.

**Диагностика:**

```bash
# Найти все pod, использующие этот PVC
kubectl get pods --all-namespaces -o json \
  | jq '.items[] | select(.spec.volumes[]?.persistentVolumeClaim?.claimName == "<pvc-name>")'

# Проверить статус pod
kubectl get pods --all-namespaces -o wide | grep <pvc-name>
```

**Решение:**

- Удалить/остановить другие pod, использующие этот PVC
- Дождаться, пока все pod завершатся
- Volume размонтируется автоматически

### Сценарий 4: CSI driver не завершает detach

Если volume не размонтируется из-за CSI проблемы — смотри [Finalizer и CSI проблемы](./finalizer_issues.md).

Краткая проверка:

```bash
# Проверить VolumeAttachment
kubectl get volumeattachment | grep <pod-uid>

# Проверить CSI driver
kubectl get pods -n kube-system -l app=<csi-driver-name>

# Логи CSI
kubectl logs -n kube-system -l app=<csi-driver-name> --tail=100
```

### Сценарий 5: Предотвращение — graceful shutdown с volume

```yaml
spec:
  terminationGracePeriodSeconds: 60
  containers:
  - name: app
    image: my-app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sync; sleep 5"]
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: my-pvc
```

`sync` — гарантирует запись данных на диск перед unmount.

---

## Дополнительная информация

**Связанные разделы:**

- [Определения Pod Terminating](./definitions.md) — причины зависания в Terminating
- [Diagnostics](./diagnostics.md) — чек-лист диагностики terminating pods
- [Finalizer и CSI проблемы](./finalizer_issues.md) — CSI detachment, VolumeAttachment
- [Node Unavailable](./node_unavailable_issues.md) — узел недоступен
- [Graceful Shutdown](./graceful_shutdown.md) — terminationGracePeriodSeconds, preStop hooks
- [Volume Basics](../../../Base/Pod/volume_types/volumes_basics.md) — типы volumes, mount lifecycle
- [Обзор Troubleshooting](../../troubleshooting_overview.md) — классификация ошибок Kubernetes
