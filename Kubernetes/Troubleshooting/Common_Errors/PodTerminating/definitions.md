# Pod Terminating: Определения

## Определения

**`Terminating`** — статус пода, означающий, что объект получил `deletionTimestamp`, но не может завершить работу и освободить ресурсы. Под находится в процессе корректного завершения (graceful shutdown) или заблокирован external условиями.

**`deletionTimestamp`** — метка времени, устанавливаемая API server при получении команды на удаление объекта. После установки объект переходит в режим удаления.

**`terminationGracePeriodSeconds`** — период ожидания (по умолчанию 30s), в течение которого контейнеры получают SIGTERM для корректного завершения до принудительного SIGKILL.

**Finalizer** — механизм защиты от удаления, предотвращающий удаление объекта из etcd до выполнения определённых действий (освобождение volumes, cleanup внешних ресурсов).

**Terminal Phase** — финальная фаза пода (`Succeeded` или `Failed`), в которую kubelet переводит под после завершения всех контейнеров. Гарантировано в Kubernetes 1.27+.

**Pod Garbage Collector (Pod GC)** — контроллер в `kube-controller-manager`, автоматически удаляющий завершённые поды при превышении порога `terminated-pod-gc-threshold`.

---

## Базовые концепции

### Процесс удаления пода

```
kubectl delete pod
    ↓
API устанавливает deletionTimestamp → pod в Terminating
    ↓
kubelet получает уведомление
    ↓
preStop hook (если определён)
    ↓
SIGTERM → graceful shutdown
    ↓
[ожидание terminationGracePeriodSeconds]
    ↓
SIGKILL (если не завершился)
    ↓
Размонтирование volumes
    ↓
Очистка pause container
    ↓
Kubelet → terminal phase (Succeeded / Failed)
    ↓
Удаление finalizers
    ↓
Удаление записи из etcd
```

Полный процесс graceful shutdown: [Graceful Shutdown](./graceful_shutdown.md).

### Стандартные finalizers

| Finalizer | Описание |
|-----------|----------|
| `kubernetes.io/pod-protection` | Защита пода от удаления |
| `foregroundDeletion` | Ожидание удаления зависимостей (Deployment → ReplicaSet → Pod) |
| `external-attacher/<csi-driver>` | CSI volume attachment |
| `kubernetes.io/pvc-protection` | Защита PVC от удаления |

Проверка: `kubectl get pod <name> -o jsonpath='{.metadata.finalizers}'`

Подробно: [Finalizer и CSI проблемы](./finalizer_issues.md).

### Практические сценарии: основные причины зависания

| Причина | Частота | Описание | Ссылка |
|---------|---------|----------|--------|
| **Volume unmount** | ~50% | Volume не может размонтироваться (CSI driver, node unavailable) | [Volume Unmount](./volume_unmount_issues.md) |
| **Finalizers** | ~30% | External controller не удаляет finalizer | [Finalizer Issues](./finalizer_issues.md) |
| **Node unavailable** | ~15% | Узел недоступен, kubelet не отвечает | [Node Unavailable](./node_unavailable_issues.md) |
| **PDB blocking** | ~5% | PodDisruptionBudget не позволяет удалить pod | [PDB Blocking](./pdb_blocking.md) |

---

## Практические сценарии

### Быстрая диагностика

```bash
# 1. Проверка статуса и deletionTimestamp
kubectl get pod <pod-name> -o wide

# 2. Детальная информация (Events + Finalizers)
kubectl describe pod <pod-name>

# 3. Проверка finalizers
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'

# 4. Поиск всех terminating pods
kubectl get pods --field-selector status.phase=Running | grep Terminating
```

Полный чек-лист диагностики: [Diagnostics](./diagnostics.md).

---

## Дополнительная информация

### Pod Garbage Collector

**Pod Garbage Collector (Pod GC)** — контроллер в `kube-controller-manager`, предотвращающий накопление «мусора» из завершённых подов.

**Когда Pod GC удаляет поды:**

- Количество подов в фазах `Succeeded`/`Failed` превышает `terminated-pod-gc-threshold`
- Под привязан к узлу, который больше не существует
- Под не был запланирован, но находится в статусе `Terminating`
- Под привязан к узлу с `NodeVolumeOut` (CSI driver не может отмонтировать volume)

Pod GC также маркирует «бесхозные» поды (без привязанного узла) как завершённые, даже если они ещё не в терминальной фазе.

> **Примечание:** Завершённые поды (`Succeeded`/`Failed`) остаются в класте до тех пор, пока не будут удалены явно (пользователем, контроллером или Pod GC). Это позволяет анализировать причины завершения.

**Связанные разделы:**

- [Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md) — фазы, условия, graceful shutdown, Pod GC
- [Graceful Shutdown](./graceful_shutdown.md) — настройка terminationGracePeriodSeconds, preStop hooks
- [Обслуживание узлов](../../../Operations/node_maintenance.md) — drain, eviction, PDB
