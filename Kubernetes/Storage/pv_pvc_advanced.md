# PV/PVC Advanced Scenarios

## Определения

Базовые концепции: [PersistentVolume и PVC](./pv_and_pvc.md). StorageClass: [StorageClass](./storageclass.md).

---

## Базовые концепции

### Детальный алгоритм связывания PV и PVC

Kubernetes связывает PVC с PV по строгому алгоритму:

1. **Фильтрация по `StorageClassName`**: PV с совпадающим классом (или без класса, если в PVC не указан).
2. **Фильтрация по `accessModes`**: PV с подходящим режимом доступа.
3. **Фильтрация по размеру**: PV не меньше запрошенного.
4. **Best Fit**: выбирается наименьший подходящий PV.

#### Алгоритм Best Fit — нюансы

- Если PVC запрашивает 500 MiB, а доступен PV на 1 GiB — PVC получит этот PV (ближайший больший).
- Если точного совпадения нет, PV большего размера будет использован — это приводит к неэффективному использованию ресурсов.
- PVC может оставаться в статусе `Pending` бесконечно, если в кластере нет PV, удовлетворяющего требованиям.

> **Примечание:** Для динамического выделения с учётом топологии (многозонные кластеры) используется `WaitForFirstConsumer`. Подробнее: [CSI Topology](./CSI/csi_advanced.md#csi-topology).

### Привязка PVC к конкретному PV через метки

По умолчанию PVC выбирает любой подходящий PV по алгоритму Best Fit. Для явного указания конкретного PV используются метки (labels) и `selector`:

**Шаг 1: Администратор создаёт PV с метками**

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-storage-pv
  labels:
    environment: production
    storage-tier: fast
spec:
  capacity:
    storage: 1Gi
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  nfs:
    path: /srv/nfs/k8s
    server: 192.168.1.100
```

**Шаг 2: Разработчик создаёт PVC с selector.matchLabels**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-data-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 500Mi
  selector:
    matchLabels:
      storage-tier: fast
```

В этом случае PVC привяжется только к PV, у которого есть метка `storage-tier: fast`. Без `selector` PVC мог бы привязаться к любому PV с подходящим размером и accessMode.

> **Рекомендация:** Используйте метки для гибкого управления: `environment`, `datacenter`, `storage-tier`, `instance`. Это позволяет разработчикам указывать требования к хранилищу без знания деталей инфраструктуры.

---

## Практические сценарии

### Диагностика состояния Pending у PVC

Если PVC создан, но находится в статусе `Pending` длительное время — это означает отсутствие подходящего PV в кластере.

**Возможные причины:**

- Нет PV с указанным `storageClassName`.
- Нет PV с подходящим `accessMode`.
- Все доступные PV меньше запрошенного размера.
- `selector.matchLabels` не соответствует ни одному PV.
- PV в состоянии `Released` (нельзя использовать повторно автоматически).

**Диагностика:**

```bash
# Проверка статуса PVC
kubectl get pvc

# Детальная информация о PVC (Events покажут причину)
kubectl describe pvc <pvc-name>

# Проверка доступных PV
kubectl get pv

# Проверка состояния PV
kubectl describe pv <pv-name>
```

**Решение:**

- Создать новый PV, удовлетворяющий требованиям PVC.
- Изменить требования PVC (размер, accessMode, selector).
- Удалить "зависший" PVC, если он больше не нужен.

### Сценарий повторного использования PVC

При правильной настройке (`reclaimPolicy: Retain`) данные сохраняются после удаления пода:

```
1. Pod удалён/перезапущен
         │
         │ (PVC и PV сохраняются)
         ▼
2. PVC остаётся в статусе Bound
         │
         │ (данные на физическом томе нетронуты)
         ▼
3. Новый Pod создаётся и ссылается на тот же PVC
         │
         ▼
4. Том монтируется в новый под
         │
         │ (все данные доступны)
         ▼
5. Приложение продолжает работу с теми же данными
```

**Важно:** PVC не удаляется автоматически при удалении пода. PVC удаляется только при явном удалении пользователем или при удалении StatefulSet (если PVC создан через `volumeClaimTemplates` и не установлен annotation для сохранения).

### Рекомендуемый порядок удаления ресурсов

При удалении приложения с постоянным хранилищем соблюдайте правильный порядок:

```
1. Удалить Pod (или Deployment/StatefulSet)
         │
         ▼
2. Удалить PersistentVolumeClaim (PVC)
         │
         │ (срабатывает reclaimPolicy)
         ▼
3. Проверить состояние PersistentVolume
         │
         ├─► Retain: PV → Released (данные сохранены, требуется ручная обработка)
         └─► Delete: PV и физический том удаляются автоматически
```

> **Критически важно:** Удаляйте PVC только после того, как поды перестали использовать том. Если удалить PVC при работающем поде, данные могут быть потеряны или повреждены.

---

## Дополнительная информация

Полные примеры манифестов (Ceph RBD, NFS, StatefulSet): [PV/PVC Practical Scenarios](./pv_and_pvc_scenarios.md). Локальное хранилище: [Local Path Provisioner](./local-path-provisioner.md). NFS-хранилище: [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md). Расширенные возможности CSI (snapshots, клонирование, топология): [CSI Advanced](./CSI/csi_advanced.md). Официальная документация: [Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/), [Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/).
