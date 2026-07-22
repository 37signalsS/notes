# Расширенные сценарии работы с PV и PVC

## Определения

В данном файле рассматриваются продвинутые механизмы управления жизненным циклом и поведением постоянных томов в Kubernetes.

**Смежные темы:**
- [Базовые концепции PV и PVC](./pv_and_pvc.md) — основы, режимы доступа, политики возврата.
- [StorageClass](./storageclass.md) — параметры динамического провижининга.
- [Volume Claims в StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md#persistentvolumeclaim-pvc) — специфика работы с шаблонами.

---

## Основные концепции

### Детальный алгоритм связывания PV и PVC

Kubernetes связывает PVC с PV по строгому алгоритму (Binding Loop):

1. **StorageClassName**: PV с совпадающим классом. Если в PVC класс не указан, ищется PV без класса (или используется Default StorageClass при создании нового тома).
2. **AccessModes**: PV должен поддерживать все режимы доступа, указанные в PVC.
3. **VolumeMode**: Совпадение `Filesystem` или `Block`.
4. **Размер**: PV не меньше запрошенного.
5. **Best Fit**: Выбирается наименьший подходящий PV из всех доступных.
6. **Selector**: Если в PVC указан `selector`, PV должен иметь соответствующие метки.

#### Нюансы Best Fit
- Если PVC запрашивает 5 ГБ, а доступен только PV на 100 ГБ, PVC будет привязан к нему. 95 ГБ будут фактически недоступны для других PVC.
- PVC остается в статусе `Pending`, пока не появится PV, удовлетворяющий **всем** критериям.

### Режимы объема (Volume Mode)

Позволяют выбрать, как том будет представлен внутри контейнера (K8s 1.18+).

| Режим | Описание | Применение |
|---|---|---|
| **`Filesystem`** (Default) | Том монтируется как директория с файловой системой (ext4, xfs). | Обычные приложения, логи, статика. |
| **`Block`** | Том монтируется как "сырое" блочное устройство (`/dev/sdb`). | Высоконагруженные БД (Oracle, SAP HANA), виртуализация (KubeVirt). |

### Эксклюзивный доступ (ReadWriteOncePod)

Новый режим доступа (GA в 1.29), обеспечивающий более строгую изоляцию:
- **RWO (ReadWriteOnce)**: Позволяет нескольким подам на **одном узле** читать/писать в один том.
- **RWOP (ReadWriteOncePod)**: Гарантирует, что только **один под в кластере** может монтировать этот том. Это предотвращает повреждение данных при некорректном переезде Stateful-приложений.

### Механизмы защиты (Finalizers)

Kubernetes предотвращает случайное удаление используемых данных через `finalizers`:
- `kubernetes.io/pvc-protection`: Не дает удалить PVC, пока он используется активным подом.
- `kubernetes.io/pv-protection`: Не дает удалить PV, пока он привязан к PVC.

---

## Практические сценарии

### Динамическое расширение тома (Volume Expansion)

Позволяет увеличить размер диска без удаления PVC.

**Условия успеха:**
1. CSI-драйвер поддерживает расширение (почти все современные драйверы).
2. В StorageClass установлено: `allowVolumeExpansion: true`.
3. Файловая система поддерживает расширение (XFS, Ext4).

**Алгоритм:**
1. Отредактируйте PVC:
   ```yaml
   spec:
     resources:
       requests:
         storage: 20Gi # Было 10Gi
   ```
2. **Online Expansion**: Если драйвер поддерживает, размер изменится сразу.
3. **Offline Expansion**: Если драйвер не поддерживает расширение при смонтированном томе, потребуется перезагрузить под.

### Использование источников данных (Volume Data Sources)

Позволяет создавать PVC на основе уже существующих данных (клоны и снимки).

#### 1. Клонирование тома (Volume Cloning)
Создание идентичной копии существующего PVC внутри того же Namespace.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pvc-clone
spec:
  dataSource:
    name: source-pvc # Имя исходного PVC
    kind: PersistentVolumeClaim
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 10Gi # Размер должен быть >= исходного
```

#### 2. Восстановление из снимка (Volume Snapshot)
Создание тома из заранее сделанного `VolumeSnapshot`.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pvc-from-snapshot
spec:
  dataSource:
    name: my-snapshot # Имя объекта VolumeSnapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 10Gi
```

### Привязка к конкретному PV через метки и ClaimRef

#### Способ 1: Selector (Гибкий)
Позволяет PVC выбрать PV с определенными характеристиками (например, `fast-disk: "true"`) через метки.

```yaml
# В спецификации PVC
spec:
  selector:
    matchLabels:
      fast-disk: "true"
```

#### Способ 2: ClaimRef (Жесткий)
Администратор может заранее "зарезервировать" PV для конкретного PVC, указав его в спецификации PV.

```yaml
# В манифесте PersistentVolume
spec:
  claimRef:
    name: database-pvc-0
    namespace: prod
```
В этом случае ни один другой PVC не сможет занять этот PV, даже если он идеально подходит по параметрам.

### Топология и локальные диски (Node Affinity)

Для томов, которые физически привязаны к узлу (Local PV) или зоне (AWS EBS), используется `nodeAffinity`.

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: local-ssd-pv
spec:
  capacity:
    storage: 100Gi
  volumeMode: Filesystem
  accessModes: ["ReadWriteOnce"]
  local:
    path: /mnt/disks/ssd1
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values: ["worker-node-1"]
```

> **Важно:** При использовании таких PV в StorageClass обязательно должен быть установлен режим `volumeBindingMode: WaitForFirstConsumer`, чтобы планировщик сначала выбрал подходящий узел для пода, а уже потом привязывал к нему PV.

### Диагностика состояния Pending

Если PVC "завис" в `Pending`, используйте чек-лист:

1. **Проверка событий**: `kubectl describe pvc <name>`.
   - `waiting for a volume to be created, either by external provisioner...` -> Проблема в StorageClass или CSI-драйвере.
   - `failed to find a compliant node...` -> Проблема в Node Affinity или лимитах узлов.
2. **Проверка StorageClass**: `kubectl get sc`. Убедитесь, что указанный в PVC класс существует.
3. **Проверка PV (для статического выделения)**: `kubectl get pv`. Убедитесь, что есть PV в статусе `Available` с подходящим размером и AccessMode.
4. **Проверка квот**: `kubectl get resourcequota`. Возможно, исчерпан лимит на суммарный объем дисков в Namespace.

---

## Дополнительная информация

- [CSI Advanced — снимки, клонирование, топология](./CSI/csi_advanced.md)
- [Официальная документация: Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [Официальная документация: Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
