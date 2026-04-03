# Pod Terminating: Finalizer и CSI проблемы

## Определения

**Finalizer** — механизм защиты от удаления: API server не удаляет объект из etcd, пока массив `metadata.finalizers` не станет пустым. Каждый finalizer — это строка-идентификатор контроллера, ответственного за cleanup.

**VolumeAttachment** — объект Kubernetes, представляющий присоединение тома (PersistentVolume) к узлу. Управляется CSI external-attacher.

**CSI driver (Container Storage Interface)** — стандартный плагин для подключения внешних хранилищ к Pod. Состоит из controller-пода (attacher, provisioner) и node DaemonSet.

**`external-attacher/<driver-name>`** — финализатор, добавляемый CSI external-attacher контроллером. Блокирует удаление пода до отсоединения тома.

---

## Базовые концепции

### Механизм блокировки удаления

```
kubectl delete pod
    ↓
deletionTimestamp установлен
    ↓
API server проверяет metadata.finalizers
    ↓
finalizers не пустые → pod в Terminating
    ↓
Контроллер finalizer выполняет cleanup
    ↓
Контроллер удаляет свой finalizer из массива
    ↓
finalizers пустые → объект удалён из etcd
```

### Типичные finalizers блокирующие удаление

| Finalizer | Контроллер | Что блокирует |
|-----------|------------|---------------|
| `external-attacher/<csi-driver>` | CSI external-attacher | Volume detachment |
| `kubernetes.io/pvc-protection` | PVC protector controller | Удаление PVC |
| `foregroundDeletion` | Garbage collector | Удаление зависимостей |
| `storageos.com` | StorageOS | StorageOS volume |
| `rbd.csi.ceph.com` | Ceph RBD CSI | Ceph RBD image |

### Роль CSI driver в блокировке

CSI driver состоит из компонентов, участвующих в lifecycle volumes:

- **external-attacher** — управление VolumeAttachment (attach/detach)
- **external-provisioner** — создание/удаление PV
- **node DaemonSet** — mount/unmount на узле

Проблема в любом компоненте → finalizer не удаляется → pod зависает в Terminating.

Общая диагностика: [Diagnostics](./diagnostics.md). Определения: [Definitions](./definitions.md).

---

## Практические сценарии

### Сценарий 1: Finalizer не удаляется

**Симптом:**

```
kubectl get pod <pod-name>
NAME      STATUS       AGE
my-pod    Terminating  45m

kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'
[external-attacher/ebs-csi-aws-com]
```

**Причина:** CSI controller (external-attacher) не может завершить detachment — проблема с cloud provider API, таймауты, rate limiting.

**Диагностика:**

```bash
# 1. Проверка CSI controller
kubectl get pods -n kube-system -l app=csi-driver

# 2. Проверка VolumeAttachment
kubectl get volumeattachment | grep <pod-uid>

# 3. Детали VolumeAttachment
kubectl describe volumeattachment <attachment-name>
# Искать: ошибки detachment, timeout, API errors

# 4. Логи CSI controller
kubectl logs -n kube-system -l app=csi-driver --tail=100
```

**Решение — Вариант A: Удаление VolumeAttachment:**

```bash
# Найти зависший VolumeAttachment
kubectl get volumeattachment \
  -o custom-columns=NAME:.metadata.name,PV:.spec.source.persistentVolumeName,NODE:.spec.nodeName

# Удалить
kubectl delete volumeattachment <attachment-name>
```

После удаления VolumeAttachment external-attacher удаляет свой finalizer → pod завершается.

**Решение — Вариант B: Принудительное удаление finalizer (крайняя мера):**

```bash
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":[]}}'
```

> **Warning:** Это не отсоединяет том от узла. Volume может остаться в состоянии "attached", данные — потеряны. Используйте только если узел уничтожен и данные не важны.

### Сценарий 2: Проблемы с CSI driver

**Симптом:**

```
Events:
  Warning  FailedDetachVolume  Unable to detach volume: 
  rpc error: code = Internal desc = volume detachment failed
```

**Причина:** CSI driver не может отсоединить volume — сбой driver, проблемы storage backend, network issues.

**Диагностика:**

```bash
# 1. Статус CSI driver (CRD)
kubectl get csidrivers

# 2. Компоненты CSI driver
kubectl get pods -n kube-system -l app=<csi-driver-name>
kubectl get daemonset -n kube-system -l app=<csi-driver-name>

# 3. Логи CSI controller
kubectl logs -n kube-system -l app=<csi-driver-name> -c csi-attacher --tail=200

# 4. Логи CSI node plugin
kubectl logs -n kube-system -l app=<csi-driver-name> -c node-driver-registrar --tail=100

# 5. VolumeAttachment детали
kubectl describe volumeattachment <name>
```

**Решение:**

```bash
# 1. Перезапуск CSI controller
kubectl rollout restart deployment -n kube-system <csi-controller-deployment>

# 2. Перезапуск node DaemonSet
kubectl rollout restart daemonset -n kube-system <csi-node-ds>

# 3. Удаление зависших VolumeAttachment
kubectl delete volumeattachment -l <label-selector>
```

### Сценарий 3: PVC protection finalizer

**Симптом:**

```
Finalizers: [kubernetes.io/pvc-protection]
```

**Причина:** PVC всё ещё используется другим pod или controller не завершил cleanup.

**Диагностика и решение:**

```bash
# 1. Проверка PVC
kubectl get pvc <pvc-name>
kubectl describe pvc <pvc-name>
# Искать: используется ли ещё pod

# 2. Найти pod использующие этот PVC
kubectl get pods --all-namespaces -o json | jq '.items[] | select(.spec.volumes[]?.persistentVolumeClaim?.claimName == "<pvc-name>")'

# 3. Если PVC не используется — удалить finalizer
kubectl patch pvc <pvc-name> -p '{"metadata":{"finalizers":[]}}'
```

---

## Дополнительная информация

**Связанные разделы:**

- [Определения Pod Terminating](./definitions.md) — finalizers, причины зависания
- [Diagnostics](./diagnostics.md) — общий чек-лист диагностики
- [Volume Unmount проблемы](./volume_unmount_issues.md) — проблемы размонтирования на узле
- [Node Unavailable](./node_unavailable_issues.md) — узел недоступен
- [Graceful Shutdown](./graceful_shutdown.md) — terminationGracePeriodSeconds, preStop hooks
- [PDB Blocking](./pdb_blocking.md) — PodDisruptionBudget блокирует удаление
- [Обзор Troubleshooting](../overview.md) — классификация ошибок Kubernetes
