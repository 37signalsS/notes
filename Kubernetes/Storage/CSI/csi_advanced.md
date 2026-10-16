# Продвинутые возможности CSI

## Определения

**Продвинутые возможности CSI (CSI Advanced Features)** — это расширенный набор функций Container Storage Interface, выходящий за рамки базового жизненного цикла томов (создание, удаление, монтирование). Эти возможности позволяют реализовывать сложные стратегии управления данными, такие как консистентное резервное копирование, интеллектуальное планирование с учётом топологии и проактивный мониторинг состояния хранилищ.

Ключевые продвинутые функции:
- **Volume Snapshots** — создание мгновенных снимков состояния томов через Kubernetes API.
- **Volume Cloning** — создание независимых копий существующих томов (клонов).
- **Volume Group Snapshots** — согласованные (crash-consistent) снимки нескольких томов как единой группы.
- **CSI Topology** — учёт физического расположения СХД (зоны, регионы, стойки) при планировании подов.
- **Volume Expansion & Performance Control** — динамическое изменение размера томов и параметров производительности (IOPS, пропускная способность).
- **Volume Health Monitoring** — обнаружение сбоев на уровне файловой системы или оборудования СХД.
- **Storage Capacity Tracking** — информирование планировщика о доступном свободном месте в конкретных зонах.
- **CSI Migration** — механизм прозрачного перевода старых встроенных плагинов на современный CSI-стек.

---

## Базовые концепции

### API снапшотов томов (Volume Snapshots)

Механизм создания "снимков" данных `PersistentVolume`. Реализуется через CSI-драйвер и стандартный Kubernetes API.

> **Статус:** API `snapshot.storage.k8s.io/v1` — **Stable (GA)** с Kubernetes 1.20. Работает **только** с out-of-tree CSI-драйверами; для встроенных (in-tree) плагинов снапшоты не поддерживаются, так как те не реализуют CSI RPC.

#### Ключевые компоненты
1. **snapshot-controller**: Служба Kubernetes, которая управляет объектами снапшотов. Разворачивается отдельно (например, через Helm-чарт `snapshot-controller` из `kubernetes-csi/external-snapshotter`), поскольку не входит в состав control-plane.
2. **external-snapshotter (Sidecar)**: Контейнер в поде CSI-драйвера, который взаимодействует с API СХД для создания снимка. Устанавливается вместе с контроллером и требует установки CRD (`volumesnapshots`, `volumesnapshotclasses`, `volumesnapshotcontents`).
3. **`VolumeSnapshotClass`**: Определяет параметры создания снапшотов (аналогично `StorageClass`).
   - `driver`: Имя CSI-драйвера (например, `rbd.csi.ceph.com`).
   - `deletionPolicy`: `Retain` (снапшот остаётся в СХД даже после удаления объекта `VolumeSnapshot` в K8s) или `Delete` (автоматическое удаление снимка вместе с объектом).
   - `parameters`: Специфичные настройки вендора (например, тип инкрементального бэкапа).
4. **`VolumeSnapshot`**: Запрос пользователя на создание снапшота конкретного PVC. Namespace-ресурс.
5. **`VolumeSnapshotContent`**: Физический указатель на снапшот в СХД. Это ресурс уровня кластера (аналог PV). Может быть создан как динамически (`snapshot-controller` создаёт его через sidecar), так и вручную администратором для **Pre-Provisioned** снимков (уже существующих в СХД), для которых в `VolumeSnapshot.spec.source` указывается `volumeSnapshotContentName`.

#### Жизненный цикл снапшота
1. Пользователь создаёт `VolumeSnapshot` со ссылкой на существующий PVC.
2. `VolumeSnapshotClass` сопоставляет снапшот с драйвером и `deletionPolicy`.
3. `snapshot-controller` создаёт `VolumeSnapshotContent`, а `external-snapshotter` вызывает CSI RPC `CreateSnapshot`.
4. В статусе снапшота появляется поле `readyToUse: true` — только после этого снимок можно использовать для восстановления.
5. При удалении `VolumeSnapshot` поведение зависит от `deletionPolicy`: `Delete` удаляет снимок и в СХД (через `DeleteSnapshot`), `Retain` оставляет снимок в СХД, а объект `VolumeSnapshotContent` остаётся в кластере без привязки к снапшоту.

**Важно про `Retain`:** после удаления `VolumeSnapshot` с политикой `Retain` в кластере остаются "осиротевшие" объекты `VolumeSnapshotContent` со ссылкой на данные в СХД. Kubernetes не удаляет их автоматически — связь с пользовательским объектом теряется, и доступ к данным сохраняется только через прямой вызов API СХД или повторное статическое восстановление. Администратор должен вести реестр таких снимков (например, через скрипты или инструменты вроде Velero).

#### Восстановление из снапшота
Из снапшота создаётся новый PVC через `dataSource` (см. практический пример ниже). Восстановление **не блокирует** исходный том и создаёт независимую копию данных (по умолчанию полноразмерную развёртку — клонирование данных при доступе либо полная копия, зависит от реализации СХД).

#### Согласованность снапшотов
Обычный `VolumeSnapshot` обеспечивает **crash-consistency** на уровне СХД, но не гарантирует **application-consistency**: если в момент снимка приложение активно пишет на диск (например, транзакции БД), данные могут быть неконсистентны. Для согласованных снимков используется механизм pre/post-хуков (см. раздел [Снапшоты для баз данных](#снапшоты-для-баз-данных)).

#### Статистика и метрики
- Для CLI (например, RBD) доступны служебные метрики: `qemu-img info` для пустых снапшотов, `rbd du` для занятого пространства.
- При создании множества снапшотов следите, чтобы СХД не упиралась в квоту на количество снимков.

### Групповые снапшоты (Volume Group Snapshots)

Единый, **согласованный по времени** снимок нескольких томов (например, данные и логи базы на разных PVC). Обеспечивает crash-consistency всей группы без необходимости приостанавливать приложение.

> **Статус:** Alpha в v1.27, Beta (`v1beta1`) в v1.32, в v1.34 — `v1beta2`, **GA в v1.36**. Поддержка доступна только у CSI-драйверов, реализующих расширение `CreateVolumeGroupSnapshot`.

**Ключевые API-объекты:** `VolumeGroupSnapshot` (запрос, аналог `VolumeSnapshot`), `VolumeGroupSnapshotContent` (кластерная привязка), `VolumeGroupSnapshotClass` (параметры).

Группа задаётся **label-селектором** по PVC (см. практический пример ниже). Снимок группы создаётся как один вызов CSI для всей группы сразу — это гарантирует единую точку согласованности (консистентную точку восстановления), в отличие от последовательных отдельных снимков.

### Клонирование томов (Volume Cloning)

Создание нового тома на основе существующего PVC через поле `dataSource`. В отличие от снапшота, клон создаётся как готовый к использованию `PersistentVolumeClaim`.

> **Статус:** API `v1` (feature `VolumePVCDataSource`), **GA с Kubernetes 1.18**. Работает только с CSI-драйверами, поддерживающими клонирование (только динамическое выделение).

#### Сравнение снапшотов и клонов

| Параметр | Снапшот (Snapshot) | Клон (Clone) |
| :--- | :--- | :--- |
| **Цель** | Точка восстановления / бэкап | Независимая рабочая копия |
| **Зависимость** | Часто зависит от родительского тома в СХД | Обычно независимый (зависит от СХД) |
| **Объект в K8s** | `VolumeSnapshot` | `PersistentVolumeClaim` |
| **Использование** | Восстановление после сбоев | Тестирование, Fork БД, аналитика |

**Ключевое отличие от снапшота:** клон не требует перемещения данных между "снимком" и новым томом — он создаётся напрямую из исходного тома, используя механизмы самой СХД (CoW-клонирование RBD, thin-provisioned клоны и т.п.), и сразу доступен для записи.

#### Требования для клонирования
- Драйвер должен поддерживать операцию `CREATE_DELETE_VOLUME` с источником (клонирование через CSI `CreateVolume` с параметром `source.volume_id`).
- Размер клона должен быть **больше или равен** размеру исходного тома.
- Оба PVC (источник и клон) должны находиться в **одном Namespace**.
- `dataSource` / `dataSourceRef` поддерживает три варианта источника:
  - `PersistentVolumeClaim` — прямое клонирование из существующего тома (только в том же Namespace).
  - `VolumeSnapshot` — восстановление из снимка (см. раздел снапшотов).
  - Произвольный CR — через **volume populators** (`dataSourceRef`, feature-гейт `AnyVolumeDataSource`, Beta с v1.24), когда наполнение тома выполняет внешний контроллер-популятор.
- Восстановление из **группового снимка** выполняется отдельными PVC: каждый новый том создается из своего `VolumeSnapshot`, входящего в группу `VolumeGroupSnapshot`.
- Для клонирования не требуется отдельный `VolumeSnapshotClass`, сам клон использует `StorageClass` целевого PVC.

### Топология CSI (CSI Topology)

Решает проблему доступности данных в распределённых кластерах (например, диск AWS EBS доступен только в той зоне `Availability Zone`, где он был создан).

#### Компоненты топологии
1. **`CSINode`**: Объект, хранящий информацию о топологических метках узла (зоны, регионы).
2. **`volumeBindingMode: WaitForFirstConsumer`**: Режим в `StorageClass`, при котором PV создаётся только после того, как планировщик выбрал узел для пода. Это гарантирует, что том будет создан именно в той зоне, где запустится под.
3. **`allowedTopologies`**: Список зон/узлов в `StorageClass`, где разрешено создавать тома.

### Расширение и управление атрибутами (Volume Expansion & Attributes)

#### Динамическое расширение (Volume Expansion)
Увеличение размера тома без потери данных.
- **Online Expansion**: Выполняется на лету без остановки пода. Требует поддержки файловой системы (XFS, Ext4) и драйвера.
- **Offline Expansion**: Требует отмонтирования тома (остановки пода).

#### Volume Attributes Class (v1.34+ GA)

Механизм (Beta в v1.31, **Stable (GA) в Kubernetes 1.34**, API `storage.k8s.io/v1`) для динамического изменения параметров производительности без изменения размера.
- Позволяет управлять **IOPS** и **Throughput** (пропускной способностью) через объект `VolumeAttributesClass`.
- Параметры изменяются "на лету" через CSI RPC `ControllerModifyVolume`, если CSI-драйвер поддерживает эту функцию.
- В GA версии добавлена поддержка **отмены операции** при ошибке модификации (PVC возвращается к стабильному состоянию) и **ResourceQuota на основе `scopeSelector`** (квота на PVC, ссылающиеся на конкретный `VolumeAttributesClass`).
- В отличие от `StorageClass`, объект `VolumeAttributesClass` предназначен для изменения атрибутов **существующего** связанного тома, а не для его провижининга. `StorageClass` при этом является неизменяемым (immutable) — это ключевой мотиватор использования VAC.
- **Ограничение:** работает только с CSI-драйверами, реализующими `ModifyVolume`. Примеры on-prem драйверов с поддержкой — Ceph RBD (QoS через RBD-NBD, Alpha с ceph-csi v3.17).

При изменении `volumeAttributesClassName` в PVC атрибуты применяются без удаления тома и перезапуска подов, что важно для production-нагрузок, требующих недоступности ноль.

### Мониторинг здоровья томов (Volume Health Monitoring)

Позволяет обнаруживать проблемы с данными (например, Read-only FS после сбоя диска), которые не видны стандартным проверкам подов.

> **Статус:** API в Kubernetes **Alpha** (v1.19, переработан в v1.21, текущий feature gate `CSIVolumeHealth`). Реализована только у ограниченного круга драйверов (csi-hostpath, mock) — перед применением проверяйте поддержку в документации вашего драйвера.

#### Как это работает
Функция реализована в **двух компонентах**, поэтому разговор о «Node sidecar» некорректен:
- **External Health Monitor Controller (sidecar)**: разворачивается рядом с Controller Plugin драйвера. Вызывает controller-RPC драйвера (`ListVolumes` / `ControllerGetVolume`), а при сбое узла (флаг `--enable-node-watcher`) сообщает о проблеме в событии на PVC.
- **Kubelet (node-сторона)**: начиная с v1.21 логика node-стороннего мониторинга перенесена из отдельного агента **в сам Kubelet** во избежание дублирующих CSI RPC. Kubelet вызывает `NodeGetVolumeStats` и публикует события в Pod.

#### События (Events)
- Если обнаружена проблема на уровне контроллера, генерируется Event **`VolumeConditionAbnormal`** для PVC.
- Если проблема найдена на узле, Kubelet создаёт событие для **Pod**, использующего том.
- Мониторинг показывает только индикацию проблемы; **автоматическое восстановление** (перезапуск пода) он не выполняет — реакцию необходимо реализовать внешними средствами (операторы, наблюдатели событий, Prometheus-оповещения).

### Отслеживание ёмкости (Storage Capacity Tracking)

Планировщик учитывает доступный объем хранилища в конкретной зоне перед назначением пода.
- Актуально для локальных дисков (Local PV) и СХД с ограниченным ресурсом на группу узлов.
- Используются объекты **`CSIStorageCapacity`**, которые создаёт CSI-драйвер.

> **Статус:** **Stable (GA)** с Kubernetes 1.24.

#### Условия активации
Планировщик учитывает данные о ёмкости **только** если выполнены **три** условия одновременно:
1. Под использует том с **unbound** PVC (том ещё не создан).
2. PVC использует `StorageClass` c `volumeBindingMode: WaitForFirstConsumer` (late binding).
3. В объекте `CSIDriver` установлен `spec.storageCapacity: true`.

#### Как это работает
- CSI-драйвер вызывает RPC `GetCapacity` и публикует `CSIStorageCapacity`-объекты в Namespace, где установлен драйвер. Каждый объект описывает доступную ёмкость для конкретного `StorageClass` в конкретном топологическом сегменте (node / зона). Поля: `storageClassName`, `nodeTopology` (метки), `capacity`, опционально `maximumVolumeSize` (габаритный лимит тома).
- Во время планирования под scheduler в фазе фильтрации отбрасывает узлы/сегменты, где свободного места недостаточно для запрашиваемого тома. Сравнение упрощённое: размер тома против `capacity`.
- Для `Immediate`-привязки отслеживание ёмкости **не применяется** — место резервируется драйвером независимо от последующего размещения пода.

#### Диагностика
```bash
# Список capacity-объектов
kubectl get csistoragecapacities -n <ns-драйвера>

# Проверить, что драйвер публикует capacity
kubectl get csidriver <имя> -o yaml | grep -A2 storageCapacity

# Ошибка планирования из-за нехватки ёмкости
kubectl describe pod <name> | grep -i capacity
```

### Миграция CSI (CSI Migration)

Процесс перевода старых встроенных (in-tree) плагинов на внешние CSI-драйверы.

> **Статус в Kubernetes 1.37+:**
> - **Ceph RBD и CephFS**: in-tree плагины **недоступны с v1.31** (код удалён). Автоматическая миграция для них **не поддерживается** — переход на `ceph-csi` должен быть выполнен явно.
> - **gcePersistentDisk**: удалён полностью в v1.28.
> - **gitRepo**: плагина нет с v1.36 (последний релиз с поддержкой — v1.35).
> - **Portworx (portworxVolume)**: порт на CSI-стек — самый зрелый: миграция **Stable с v1.33** (Alpha 1.23 → Beta 1.25 → включена по умолчанию в 1.31). Сам плагин помечен deprecated с v1.25, удаление in-tree кода запланировано.
> - **AWS EBS, Azure Disk/Azure File, vSphere, OpenStack Cinder**: in-tree плагины по-прежнему присутствуют, но отмечены **deprecated**; CSI-миграция для них включена по умолчанию и выполняется «прозрачно».

**На что обращать внимание при эксплуатации:** миграция для ещё существующих плагинов работает незаметно для пользователя — манифесты со старыми in-tree именами (`kubernetes.io/aws-ebs`, `kubernetes.io/gce-pd`, `kubernetes.io/azure-disk` и т.п.) продолжают работать, так как kubelet преобразует их в CSI-вызовы. Для удалённых плагинов (Ceph RBD/CephFS, gitRepo, gcePersistentDisk) переход необходимо выполнить заранее, пересоздав манифесты на out-of-tree драйвер (например, `ceph-csi`):

```bash
# Список CSI-драйверов, зарегистрированных на узлах
kubectl get csinodes -o yaml

# Проверить, какой CSIDriver обслуживает конкретный PV
kubectl describe pv <имя> | grep -i csi

# Найти PV, созданные устаревшими in-tree плагинами, требующие миграции
kubectl get pv -o custom-columns=NAME:.metadata.name,PROVISIONER:.spec.provisioner
```

---

## Практические сценарии

### Создание снапшота PVC (Ceph RBD)

```yaml
# 1. Класс для снапшотов
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: csi-rbd-snap-class
driver: rbd.csi.ceph.com
deletionPolicy: Retain
parameters:
  clusterID: rook-ceph
  csi.storage.k8s.io/snapshotter-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/snapshotter-secret-namespace: rook-ceph

---
# 2. Создание снапшота
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: pg-db-snapshot
spec:
  volumeSnapshotClassName: csi-rbd-snap-class
  source:
    persistentVolumeClaimName: postgres-data-pvc
```

### Восстановление из снапшота

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-db-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-rbd-ssd
  resources:
    requests:
      storage: 20Gi # Должно быть >= размера снапшота
  dataSource:
    name: pg-db-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

### Клонирование тома

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cloned-app-data
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard-ssd
  resources:
    requests:
      storage: 10Gi
  dataSource:
    name: original-app-data-pvc
    kind: PersistentVolumeClaim
```

### Групповой снапшот нескольких томов (Volume Group Snapshot)

Согласованный по времени снимок группы PVC (например, данные и WAL базы) за один вызов CSI.

**Предпосылки:**
- Драйвер с поддержкой расширения VolumeGroupSnapshot: для ceph-csi/RBD — свежий Ceph (в librbd включена функция `rbd_group_snap_get_info`), CephFS — по документации Rook требуется Ceph Squid+ и свежий ceph-csi.
- `snapshot-controller` и `external-snapshotter` ≥ v8.2 с включённым feature-gate `CSIVolumeGroupSnapshot=true` и установленными CRD `groupsnapshot.storage.k8s.io`.
- Все PVC группы должны обслуживаться одним CSI-драйвером.

```yaml
# 1. Класс групповых снапшотов (GA v1.36: groupsnapshot.storage.k8s.io/v1)
apiVersion: groupsnapshot.storage.k8s.io/v1
kind: VolumeGroupSnapshotClass
metadata:
  name: csi-rbd-group-snap-class
driver: rbd.csi.ceph.com
deletionPolicy: Retain
parameters:
  clusterID: rook-ceph
  csi.storage.k8s.io/group-snapshotter-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/group-snapshotter-secret-namespace: rook-ceph

---
# 2. Пометка PVC, входящих в группу (label-селектор по ним и выбирается группа)
# kubectl label pvc postgres-data-pvc postgres-wal-pvc group=pg-cluster

---
# 3. Групповой снапшот
apiVersion: groupsnapshot.storage.k8s.io/v1
kind: VolumeGroupSnapshot
metadata:
  name: pg-cluster-snap
  namespace: database
spec:
  volumeGroupSnapshotClassName: csi-rbd-group-snap-class
  source:
    selector:
      matchLabels:
        group: pg-cluster
```

Готовность и состав группы:
```bash
# Признак готовности всей группы: READYTOUSE=true
kubectl get volumegroupsnapshot pg-cluster-snap -n database

# Для каждого PVC группы автоматически создаётся свой VolumeSnapshot
# (имя берётся из VolumeGroupSnapshotContent/ownerReferences)
kubectl get volumesnapshot -n database -o jsonpath='{range .items[?(@.metadata.ownerReferences[0].name=="pg-cluster-snap")]}{.metadata.name}{"\n"}{end}'
```

Восстановление из группового снапшота — отдельным PVC на каждый снапшот-член группы (единое состояние гарантировано точкой времени группы):
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pg-data-restored
  namespace: database
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: ceph-rbd-ssd
  resources:
    requests:
      storage: 50Gi # >= restoreSize каждого члена группы
  dataSource:
    name: <имя-члена-группы-из-списка-выше>
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

### Снапшоты для баз данных

Обычный `VolumeSnapshot` даёт только crash-consistency. Чтобы получить консистентную копию БД, приложение нужно «заморозить» перед вызовом `CreateSnapshot` и «разморозить» после:

```bash
# MySQL (паттерн pre/post-хуков вручную):
kubectl exec deploy/pg -- mysql -e "FLUSH TABLES WITH READ LOCK"
kubectl apply -f snapshot.yaml                      # VolumeSnapshot или VolumeGroupSnapshot
until [ "$(kubectl get volumesnapshot pg-db-snapshot -o jsonpath='{.status.readyToUse}')" = "true" ]; do sleep 5; done
kubectl exec deploy/pg -- mysql -e "UNLOCK TABLES"

# PostgreSQL (при включённом журнале WAL):
kubectl exec deploy/pg -- psql -c "SELECT pg_start_backup('k8s-snap', true)"
kubectl apply -f snapshot.yaml
until [ "$(kubectl get volumesnapshot pg-db-snapshot -o jsonpath='{.status.readyToUse}')" = "true" ]; do sleep 5; done
kubectl exec deploy/pg -- psql -c "SELECT pg_stop_backup()"
```

Тот же паттерн автоматизируется инструментами бэкапа. Пример аннотаций-хуков Velero на поде приложения:
```yaml
# Хуки выполняются вокруг снятия снапшота автоматически
annotations:
  pre.hook.backup.velero.io/command: '["/bin/sh","-c","mysql -e \"FLUSH TABLES WITH READ LOCK\""]'
  post.hook.backup.velero.io/command: '["/bin/sh","-c","mysql -e \"UNLOCK TABLES\""]'
```

**Чеклист после восстановления:** смонтировать восстановленный том в тестовый под, запустить проверку целостности (`CHECK TABLE` для MySQL, `pg_isready`/восстановление через `pg_restore` для PostgreSQL). Если хуки не использовались — данные БД придётся проверять/восстанавливать через её собственный журнал транзакций.

### Управление производительностью (VolumeAttributesClass)

```yaml
apiVersion: storage.k8s.io/v1
kind: VolumeAttributesClass
metadata:
  name: high-iops-profile
driverName: ebs.csi.aws.com
parameters:
  type: gp3
  iops: "5000"
  throughput: "250"
```

> В примере использован облачный драйвер `ebs.csi.aws.com`. Для on-prem подойдёт драйвер с поддержкой `ControllerModifyVolume` (например, Ceph RBD QoS — см. раздел [Volume Attributes Class](#volume-attributes-class-v134-ga)), набор `parameters` зависит от вендора.

Применение к PVC:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: db-pvc
spec:
  volumeAttributesClassName: high-iops-profile
  # ...
```

### Использование топологии (AWS EBS)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: zonal-ebs
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
parameters:
  type: gp3
allowedTopologies:
- matchLabelExpressions:
  - key: topology.ebs.csi.aws.com/zone
    values:
    - us-east-1a
```

---

## Диагностика и мониторинг

### Мониторинг событий здоровья
Проверка наличия проблем с томами через события:
```bash
kubectl get events --field-selector involvedObject.kind=PersistentVolumeClaim
# Ищите событие: VolumeConditionAbnormal
```

### Проблемы планирования (Topology)
Если под висит в `Pending` с ошибкой `node(s) had volume node affinity conflict`:
1. Проверьте зоны в `StorageClass.allowedTopologies`.
2. Проверьте метки на узлах: `kubectl get nodes --show-labels`.
3. Убедитесь, что PV имеет корректный `nodeAffinity`.

### Диагностика снапшотов и клонов
```bash
# 1. Снапшот не переходит в readyToUse:true
kubectl describe volumesnapshot <имя>
# Типичные причины: драйвер не поддерживает снапшоты, ошибка учётных данных
# снапшоттера (секрет в VolumeSnapshotClass), нет подходящего VolumeSnapshotClass.

# 2. PVC из клона/снапшота висит в Pending
kubectl describe pvc <имя>
# Проверить: размер запроса >= размера источника, источник в том же Namespace,
# StorageClass целевого PVC поддерживает клонирование/восстановление.

# 3. «Осиротевшие» VolumeSnapshotContent после удаления VolumeSnapshot
#    (deletionPolicy: Retain): объект остаётся, данные в СХД сохраняются.
kubectl get volumesnapshotcontent -o jsonpath='{range .items[*]}{.metadata.name}{" -> "}{.spec.volumeSnapshotRef.name}{"\n"}{end}'
# Если ссылка ведёт на несуществующий снапшот — контент «осиротевший».
# Удаление такого контента с deletionPolicy: Delete удалит и данные в СХД — выполнять осознанно.
```

### Метрики и мониторинг
- **Метрики kubelet по томам** (`kubelet_volume_stats_available_bytes`, `kubelet_volume_stats_used_bytes`, `kubelet_volume_stats_inodes`) — агрегируются Prometheus для отслеживания заполнения PVC.
- **События кластера** — источник для alert-правил: `VolumeConditionAbnormal` (health monitoring), `FailedProvisioning` / `FailedCreateVolume` (провижининг), `ProvisioningFailed` (планирование по ёмкости).
- **Метрики самого CSI-драйвера**: ceph-csi публикует Prometheus-метрики через флаг `--metrics-address`, у Longhorn есть встроенный дашборд — это позволяет видеть операции (снапшоты, клоны, миграцию) на уровне СХД.
- **Контроль лимитов СХД**: следите за количеством снапшотов на том (квоты драйвера/СХД, `rbd snap ls` для Ceph), чтобы бэкапы не начинали «падать» втихую.

### Безопасность CSI-драйверов (Security Best Practices)

#### Шифрование данных в покое (Encryption at Rest)

Два подхода к шифрованию CSI-томов:

| Подход | Уровень | Реализация | Overhead |
| :--- | :--- | :--- | :--- |
| **Нативное шифрование СХД** | СХД | Ceph LUKS (`--data-pool` + dm-crypt), Linstor LUKS | Минимальный (hardware加速) |
| **LUKS/dm-crypt на узле** | Узел | `cryptsetup` на хосте перед монтированием | Низкий (AES-NI CPU) |
| **Шифрование приложения** | Приложение | TDE в PostgreSQL/MySQL, pgcrypto | Зависит от приложения |

```yaml
# Ceph RBD с LUKS-шифрованием (в StorageClass)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-encrypted
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  pool: encrypted-pool
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: rook-ceph
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-rbd-node
  csi.storage.k8s.io/node-stage-secret-namespace: rook-ceph
  encrypted: "true"
  encryptionPassphrase: "my-encryption-key"
```

#### Шифрование при передаче (Encryption in Transit)

```bash
# Проверка TLS для Ceph RBD
ceph config get mon. ms_cluster_mode
# → secure (или msgr2:加密)

# Проверка TLS для NFS CSI
# NFSv4 с Kerberos:
mount -t nfs4 -o sec=krb5 <server>:/share /mnt/nfs

# Минимальная рекомендация: NFSv4.2 с KRB5I ( integrity)
# Максимальная: NFSv4.2 с KRB5P ( confidentiality + integrity)
```

#### RBAC для CSI-драйверов

```yaml
# Минимальный RBAC для CSI-controller
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: csi-rbdplugin-provisioner
rules:
  - apiGroups: [""]
    resources: ["persistentvolumes"]
    verbs: ["get", "list", "watch", "create", "delete"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "watch", "update"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["snapshot.storage.k8s.io"]
    resources: ["volumesnapshots"]
    verbs: ["get", "list", "watch", "create", "delete"]
  # Не включайте:
  # - secrets (если не нужны для аутентификации в СХД)
  # - nodes (если не нужен topology)
  # - pods (если не нужен podInfoOnMount)
```

#### Pod Security Standards для CSI-подов

Node-plugin требует привилегий, но контроллерный под — нет:

```yaml
# Controller plugin — Restricted profile
apiVersion: v1
kind: Pod
metadata:
  name: csi-controller
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: csi-provisioner
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
```

```yaml
# Node plugin — Baseline profile (требуется privileged для операций с block devices)
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: csi-rbdplugin
spec:
  template:
    spec:
      securityContext:
        # node plugin требует privileged: true для монтирования
        # Pod Security Standards: Baseline (не restricted)
      containers:
        - name: csi-rbdplugin
          securityContext:
            privileged: true  # Необходимо для NodeStageVolume/NodePublishVolume
```

#### Secrets Management для CSI

```yaml
# Внешние секреты (External Secrets Operator) для CSI-драйвера
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: ceph-csi-secrets
  namespace: rook-ceph
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: csi-rbd-secret
  data:
    - secretKey: userID
      remoteRef:
        key: ceph
        property: userID
    - secretKey: userKey
      remoteRef:
        key: ceph
        property: userKey
```

**Практические правила:**
- **Никогда** не храните ключи CSI в манифестах ( secrets в Git)
- Используйте External Secrets Operator или HashiCorp Vault
- Регулярно ротируйте ключи доступа к СХД
- Ограничивайте RBAC для ServiceAccount CSI-драйвера минимально необходимыми правами
- Для production: `reclaimPolicy: Retain` (случайное удаление PVC не удалит данные)

---

## Дополнительная информация

### Ссылки на связанные темы
- [Обзор CSI](./csi_overview.md) — архитектура и базовые компоненты.
- [Сравнение CSI-драйверов](./csi_drivers_comparison.md) — возможности драйверов (Longhorn, Ceph, Cloud).
- [NFS Production Pitfalls](./csi_nfs_production.md) — проблемы NFS в продакшене.
- [Миграция между кластерами](./csi_cross_cluster_migration.md) — перенос данных между кластерами.
- [Мониторинг и алертинг](./csi_monitoring_rules.md) — Prometheus/Grafana для CSI.
- [Runbook: Обновление CSI](./csi_upgrade_runbook.md) — поэтапное обновление драйверов.
- [PV, PVC и StorageClass](../pv_and_pvc.md) — базовые операции с томами.
- [Обзор Ceph](../Ceph/ceph_overview.md) — общая информация о системе Ceph.

### Официальные источники
- [Kubernetes: Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
- [Kubernetes: Volume Group Snapshots (GA v1.36)](https://kubernetes.io/blog/2026/05/08/kubernetes-v1-36-volume-group-snapshot-ga/)
- [Kubernetes: Volume Attributes Classes](https://kubernetes.io/docs/concepts/storage/volume-attributes-classes/)
- [Kubernetes: Storage Capacity Tracking](https://kubernetes.io/docs/concepts/storage/storage-capacity/)
- [Kubernetes: Volume Health Monitoring](https://kubernetes.io/docs/concepts/storage/volume-health-monitoring/)
