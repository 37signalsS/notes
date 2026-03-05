# Pod Terminating: Определения

## Определения

**`Terminating`** — статус пода, означающий, что под был удален (получил `deletionTimestamp`), но не может завершить работу и освободить ресурсы.

> - Volumes: [`../../../Base/Pod/pod_volumes.md`](../../../Base/Pod/pod_volumes.md)
> - PV/PVC: [`../../../Storage/pv_and_pvc.md`](../../../Storage/pv_and_pvc.md)
> - Node Maintenance: [`../../../Operations/node_maintenance.md`](../../../Operations/node_maintenance.md)
> - High Availability: [`../../../Base/high_availability.md`](../../../Base/high_availability.md)
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
