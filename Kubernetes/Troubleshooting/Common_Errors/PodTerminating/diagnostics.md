# Pod Terminating: Диагностика

## Определения

**Диагностическое дерево Pod Terminating** — последовательность проверок, определяющая корневую причину зависания пода в статусе `Terminating`: volumes → finalizers → node → PDB.

**UID пода** — уникальный идентификатор объекта, используемый для поиска точек монтирования на узле и связи с VolumeAttachment объектами.

**Deletion Timestamp** — метка времени удаления. "Старая" (более `terminationGracePeriodSeconds`) указывает на аномалию завершения.

---

## Базовые концепции

### Принцип диагностики

Диагностика идёт от общего к частному:

1. **Общий статус** → `kubectl describe` (Events, Finalizers, Conditions)
2. **Тип блокировки** → volume / finalizer / node / PDB
3. **Детализация** → специфичные команды для каждой причины
4. **Решение** → переход в специализированный файл

### Ключевые поля в выводе kubectl describe

```
Status:       Terminating
Deletion Timestamp:  2026-03-05T10:00:00Z    ← Если старая → проблема
Finalizers:    [kubernetes.io/pod-protection external-attacher/csi-driver]  ← Если есть → блокировка
```

### Инструменты диагностики

| Инструмент | Назначение | Что искать |
|------------|------------|-------------|
| `kubectl describe pod` | Общая информация + Events | Finalizers, Status, Events |
| `kubectl get pod -o json` | Полная спецификация | deletionTimestamp, finalizers, conditions |
| `kubectl get pod -o jsonpath` | Извлечение конкретных полей | UID, finalizers, volumes |
| `findmnt` / `lsof` (на узле) | Поиск активных mount/process | Процессы, держащие volume |
| `kubectl get volumeattachment` | Проверка CSI attachments | Зависшие volume attachments |

---

## Практические сценарии

### Пошаговый чек-лист

#### Шаг 1: Общая проверка

```bash
# Статус пода + узел
kubectl get pod <pod-name> -o wide

# Детальная информация (Events + Finalizers)
kubectl describe pod <pod-name>
```

**Анализ:**

- `DeletionTimestamp` старый (минуты/часы) → аномалия
- `Finalizers` не пустые → блокировка finalizer'ом
- Events показывают ошибки volumes / node → переход к шагу 2

#### Шаг 2: Определение типа блокировки

| Признак | Причина | Действие |
|---------|---------|----------|
| Finalizers: `[external-attacher/...]` | CSI volume | → [Volume Unmount](./volume_unmount_issues.md) |
| Finalizers: `[kubernetes.io/pvc-protection]` | PVC защита | → [Finalizer Issues](./finalizer_issues.md) |
| Node: `NotReady` / `Unknown` | Узел недоступен | → [Node Unavailable](./node_unavailable_issues.md) |
| Events: `violate disruption budget` | PDB блокирует | → [PDB Blocking](./pdb_blocking.md) |

#### Шаг 3: Проверка volumes

```bash
# Volumes пода
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes}'

# UID пода (для поиска на узле)
kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}'

# Mounts на узле (требуется SSH)
findmnt | grep <pod-uid>
lsof +D /var/lib/kubelet/pods/<pod-uid>/volumes
```

Подробная диагностика: [Volume Unmount проблемы](./volume_unmount_issues.md).

#### Шаг 4: Проверка finalizers

```bash
# Список finalizers
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'

# VolumeAttachment (для CSI)
kubectl get volumeattachment | grep <pod-uid>

# CSI driver статус
kubectl get pods -n kube-system -l app=csi-driver
```

Подробная диагностика: [Finalizer и CSI проблемы](./finalizer_issues.md).

#### Шаг 5: Проверка узла

```bash
# Статус узла
kubectl get node <node-name>

# Events узла
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name>
```

Подробная диагностика: [Узел недоступен](./node_unavailable_issues.md).

### Скрипт автоматической диагностики

```bash
#!/bin/bash
# Быстрая диагностика terminating pod

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

echo -e "\n=== Описание (Status/Finalizers/Conditions) ==="
kubectl describe pod $POD -n $NS | grep -A 10 "Status:\|Finalizers:\|Conditions:"

echo -e "\n=== События ==="
kubectl get events -n $NS --field-selector involvedObject.name=$POD --sort-by='.lastTimestamp'
```

**Использование:** `./diagnose_terminating_pod.sh <pod-name> [namespace]`

---

## Дополнительная информация

**Связанные разделы:**

- [Определения Pod Terminating](./definitions.md) — базовые понятия, finalizers, причины
- [Volume Unmount проблемы](./volume_unmount_issues.md) — размонтирование volumes, lsof, umount
- [Finalizer и CSI проблемы](./finalizer_issues.md) — удаление finalizers, VolumeAttachment, CSI driver
- [Узел недоступен](./node_unavailable_issues.md) — node NotReady, принудительное удаление
- [PDB блокирует удаление](./pdb_blocking.md) — PodDisruptionBudget, eviction
- [Graceful Shutdown](./graceful_shutdown.md) — terminationGracePeriodSeconds, preStop hooks
- [Общий troubleshooting overview](../overview.md) — классификация ошибок Kubernetes
