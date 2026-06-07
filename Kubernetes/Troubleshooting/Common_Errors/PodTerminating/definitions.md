# Pod Terminating: Определения

## Определения

**`Terminating`** — состояние (status) Pod, означающее, что объект получил `deletionTimestamp`, но не может завершить работу и освободить ресурсы. Объект находится в процессе корректного завершения (graceful shutdown) или заблокирован внешними условиями.

**`deletionTimestamp`** — метка времени, устанавливаемая API server при получении команды на удаление объекта. После установки объект переходит в режим удаления.

**`terminationGracePeriodSeconds`** — период ожидания (по умолчанию 30 секунд), в течение которого контейнеры получают сигнал `SIGTERM (Signal Termination)` для корректного завершения до принудительной остановки сигналом `SIGKILL (Signal Kill)`.

**Финализатор (Finalizer)** — механизм защиты от удаления, предотвращающий удаление объекта из `etcd` до выполнения определённых действий (освобождение volumes, очистка внешних ресурсов).

**Терминальная фаза (Terminal Phase)** — финальная стадия жизни Pod (`Succeeded` или `Failed`), в которую `kubelet` переводит объект после завершения всех контейнеров. Гарантировано начиная с Kubernetes 1.27+.

**Сборщик мусора подов (Pod Garbage Collector, Pod GC)** — контроллер в `kube-controller-manager`, автоматически удаляющий завершённые поды при превышении порога `terminated-pod-gc-threshold`.

---

## Базовые концепции

### Процесс удаления Pod

```
kubectl delete pod
    ↓
API устанавливает deletionTimestamp → Pod в состоянии Terminating
    ↓
kubelet получает уведомление
    ↓
preStop hook (если определён)
    ↓
SIGTERM → корректное завершение (graceful shutdown)
    ↓
[ожидание terminationGracePeriodSeconds]
    ↓
SIGKILL (если процесс не завершился)
    ↓
Размонтирование томов (volumes)
    ↓
Очистка pause-контейнера
    ↓
Kubelet → терминальная фаза (Succeeded / Failed)
    ↓
Удаление финализаторов (finalizers)
    ↓
Удаление записи из etcd
```

Подробное описание процесса: [Graceful Shutdown](./graceful_shutdown.md).

### Стандартные финализаторы (Finalizers)

| Финализатор | Описание |
| :--- | :--- |
| `kubernetes.io/pod-protection` | Защита Pod от преждевременного удаления. |
| `foregroundDeletion` | Ожидание удаления зависимых объектов (Deployment → ReplicaSet → Pod). |
| `external-attacher/<csi-driver>` | Ожидание отсоединения тома CSI (Container Storage Interface). |
| `kubernetes.io/pvc-protection` | Защита PVC (PersistentVolumeClaim) от удаления при использовании подом. |

Проверка активных финализаторов: `kubectl get pod <name> -o jsonpath='{.metadata.finalizers}'`

Подробно: [Финализаторы и проблемы CSI](./finalizer_issues.md).

### Основные причины зависания в состоянии Terminating

| Причина | Частота | Описание | Ссылка |
| :--- | :--- | :--- | :--- |
| **Ошибки размонтирования томов** | ~50% | Том не может быть отмонтирован (ошибка CSI-драйвера, недоступность узла). | [Размонтирование томов](./volume_unmount_issues.md) |
| **Зависшие финализаторы** | ~30% | Внешний контроллер не может завершить очистку и снять финализатор. | [Проблемы финализаторов](./finalizer_issues.md) |
| **Недоступность узла** | ~15% | Узел (node) недоступен, `kubelet` не может подтвердить удаление. | [Недоступность узла](./node_unavailable_issues.md) |
| **Блокировка через PDB** | ~5% | PodDisruptionBudget запрещает удаление последнего реплика-пода. | [Блокировка PDB](./pdb_blocking.md) |

---

## Практические сценарии

### Быстрая диагностика

```bash
# 1. Проверка статуса и deletionTimestamp
kubectl get pod <pod-name> -o wide

# 2. Просмотр событий и финализаторов
kubectl describe pod <pod-name>

# 3. Список активных финализаторов
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'

# 4. Поиск всех подов в состоянии Terminating
kubectl get pods --all-namespaces | grep Terminating
```

Полный чек-лист диагностики: [Диагностика](./diagnostics.md).

---

## Дополнительная информация

### Сборщик мусора подов (Pod Garbage Collector)

**Pod Garbage Collector (Pod GC)** — контроллер, предотвращающий накопление завершённых объектов в кластере.

**Критерии удаления подов сборщиком мусора:**

- Количество подов в фазах `Succeeded` или `Failed` превышает установленный порог (`terminated-pod-gc-threshold`).
- Pod привязан к узлу, который был удалён из кластера.
- Pod не был запланирован (unscheduled), но имеет метку `Terminating`.
- Pod привязан к узлу с состоянием `NodeVolumeOut` (проблемы CSI при отмонтировании).

Pod GC также маркирует «бесхозные» поды как завершённые, даже если они не достигли терминальной фазы.

> **Примечание:** Завершённые поды остаются в кластере для возможности анализа логов и причин завершения, пока не сработает Pod GC или ручное удаление.

**См. также:**

- [Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md) — фазы, условия и graceful shutdown.
- [Graceful Shutdown](./graceful_shutdown.md) — настройка периодов завершения и хуков.
- [Обслуживание узлов](../../../Operations/node_maintenance.md) — процедуры drain и eviction.
