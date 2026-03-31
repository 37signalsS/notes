# PersistentVolume и PersistentVolumeClaim

## Определения

**`PersistentVolume` (PV)** — ресурс кластера, представляющий часть хранилища (NFS, RBD, CephFS, облачный диск). Имеет независимый от подов жизненный цикл. Содержит параметры СХД: тип, размер, путь, ID тома.

**`PersistentVolumeClaim` (PVC)** — запрос приложения к PV на выделение места. По аналогии с подами, запрашивающими CPU/память, PVC запрашивает у PV объём хранилища и режим доступа. При связывании PVC с PV, PV переходит в статус `Bound`.

**`StorageClass` (SC)** — механизм описания "классов" или "профилей" хранилища ("быстрый-ssd", "медленный-hdd"). Ключевой компонент — **`provisioner`** (плагин для взаимодействия с СХД). Современный стандарт — **[Container Storage Interface (CSI)](./CSI/csi_overview.md)**.

---

## Роли и ответственность

| Роль | Задача | Объекты |
|------|--------|---------|
| **Администратор** | Настройка инфраструктуры хранения, создание PV или StorageClass | PV, StorageClass |
| **Разработчик** | Запрос хранилища для приложения, использование в поде | PVC, Pod |

**Принцип разделения:** Разработчик не знает деталей инфраструктуры (какой тип СХД, где физически расположен том). Администратор не знает требований конкретных приложений. Связующее звено — PVC.

---

## Базовые концепции

### Проблема прямого управления томами

Изначально в Kubernetes тома определялись непосредственно в манифесте пода (`awsElasticBlockStore`, `gcePersistentDisk`, `azureDisk`).

**Недостатки:**

1. **Ручное создание томов** — администратор создаёт диски в СХД вручную.
2. **Жёсткая связь с инфраструктурой** — параметры доступа прописаны в манифесте приложения.
3. **Сложность миграции** — при смене хранилища требуется изменять манифесты всех приложений.

### Решение: трёхуровневая абстракция

| Роль | Задача |
|------|--------|
| **Разработчик** | Описывает требования: "нужно 10 ГБ быстрого хранилища с эксклюзивным доступом" |
| **Администратор** | Настраивает способы удовлетворения: "быстрое хранилище = Ceph RBD на SSD" |

### Режимы выделения хранилища

#### Статическое выделение (Static Provisioning)

Ручное создание PV администратором. Используется для интеграции с существующими СХД или когда динамическое выделение не настроено.

**Пошаговый рабочий процесс:**

```
┌─────────────────┐
│ Администратор   │
│                 │
│ 1. Создаёт PV   │──────┐
│    (манифест)   │      │
└─────────────────┘      │
                         ▼
                  ┌─────────────────┐
                  │  Kubernetes     │
                  │  Control Plane  │
                  │                 │
                  │ 2. PV доступен  │
                  │    в кластере   │
                  └─────────────────┘
                         │
                         │ (ожидает PVC)
                         ▼
                  ┌─────────────────┐
┌─────────────────┐│  Контроллер   │
│ Разработчик     ││  Persistent   │
│                 ││  Volume       │
│ 3. Создаёт PVC  │─────► Bind     │
│    (манифест)   ││               │
└─────────────────┘│ 4. Связывание │
                   │    PV + PVC   │
                   └─────────────────┘
                            │
                            │ (Bound)
                            ▼
                   ┌─────────────────┐
                   │  Pod ссылается  │
                   │  на PVC         │
                   │                 │
                   │ 5. Том          │
                   │    монтируется  │
                   └─────────────────┘
```

**Недостатки:**
1. **Ручное создание томов** — администратор создаёт диски в СХД вручную.
2. **Жёсткая связь с инфраструктурой** — параметры доступа прописаны в манифесте PV.
3. **Ограниченное повторное использование** — после удаления PVC судьба PV зависит от `reclaimPolicy`. При `Retain` требуется ручное вмешательство администратора для повторного использования.
4. **Сложность миграции** — при смене хранилища требуется изменять манифесты PV.

#### Динамическое выделение (Dynamic Provisioning) — рекомендуемый способ

Автоматический, событийно-ориентированный подход, стандарт для большинства кластеров.

**Пошаговый рабочий процесс:**

```
┌─────────────────────────┐
│ Администратор           │
│                         │
│ 1. Создаёт StorageClass │──────┐
│    (provisioner +       │      │
│     параметры)          │      │
└─────────────────────────┘      │
                                 │
                                 │ (StorageClass готов)
                                 ▼
                        ┌─────────────────┐
                        │  Kubernetes     │
                        │  Control Plane  │
                        └─────────────────┘
                                 │
                                 │ (ожидает PVC)
                                 ▼
                        ┌─────────────────┐
┌───────────────────────┤  Контроллер     │
│ Разработчик           │  StorageClass   │
│                       │                 │
│ 2. Создаёт PVC        │ 3. Обнаруживает │
│    storageClassName:  │    PVC          │
│    "standard-ssd"     │                 │
└───────────────────────┤ 4. Вызывает     │
                        │    provisioner  │
                        │                 │
                        │ 5. Создаёт      │
                        │    физический   │
                        │    том (СХД API)│
                        │                 │
                        │ 6. Создаёт PV   │
                        │    (манифест)   │
                        └─────────────────┘
                                 │
                                 │ (PV создан)
                                 ▼
                        ┌─────────────────┐
                        │  Автоматическое │
                        │  связывание     │
                        │  PV + PVC       │
                        │  (Bound)        │
                        └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  Pod ссылается  │
                        │  на PVC         │
                        │                 │
                        │ 7. Том          │
                        │    монтируется  │
                        │    в под        │
                        └─────────────────┘
```

**Преимущества:**
- **Полная автоматизация** — разработчик не знает деталей инфраструктуры, администратор не создаёт тома вручную.
- **Точное выделение** — PV создаётся точно под запрошенный размер.
- **Масштабируемость** — легко добавлять новые классы хранилищ.
- **Переносимость** — смена провайдера требует изменения только StorageClass.

**Роль контроллеров:**

В процессе участвуют несколько контроллеров:
1. **Контроллер PVC** — отслеживает появление новых PVC, ищет подходящие PV.
2. **Provisioner (CSI-контроллер)** — специфичен для типа хранилища (NFS, Ceph, AWS EBS). Реагирует на PVC с указанием соответствующего StorageClass, создаёт физический том через API СХД.
3. **Attach/Detach Controller** — управляет подключением тома к узлу, где запущен под.

### Логика связывания PV и PVC

Kubernetes связывает PVC с PV по алгоритму:

1. **Фильтрация по `StorageClassName`**: PV с совпадающим классом (или без класса, если в PVC не указан).
2. **Фильтрация по `accessModes`**: PV с подходящим режимом доступа.
3. **Фильтрация по размеру**: PV не меньше запрошенного.
4. **Best Fit**: выбирается наименьший подходящий PV.

> **Примечание:** Для динамического выделения с учётом топологии (многозонные кластеры) используется `WaitForFirstConsumer`. Подробнее: [CSI Topology](./CSI/csi_advanced.md#csi-topology).

### Режимы доступа (accessModes)

| Режим | Описание | Поддержка |
|-------|----------|-----------|
| `ReadWriteOnce` (RWO) | Чтение/запись одним узлом | Local Path, RBD, большинство облачных дисков |
| `ReadOnlyMany` (ROX) | Только чтение многими узлами | NFS, CephFS |
| `ReadWriteMany` (RWX) | Чтение/запись многими узлами | NFS, CephFS |
| `ReadWriteOncePod` (RWOP) | Эксклюзивный доступ одним подом | Зависит от CSI-драйвера |

> **Важно:** Поддерживаемые режимы доступа зависят от типа хранилища и CSI-драйвера.

### Политика возврата (reclaimPolicy)

Политика `reclaimPolicy` указывается в PV и определяет судьбу физического тома после удаления PVC.

| Политика | Описание | Когда использовать |
|----------|----------|-------------------|
| **`Retain`** | PV и физический том сохраняются после удаления PVC. PV переходит в статус `Released`, но не может быть автоматически пересвязан. Требуется ручное вмешательство администратора для очистки и повторного использования. | Production, важные данные |
| **`Delete`** | PV и физический том удаляются после удаления PVC. Контроллер автоматически удаляет PV и вызывает provisioner для удаления физического тома в СХД. | Dev/Test, временные данные |
| **`Recycle`** | **Устарело (deprecated)**. Очистка `rm -rf /thevolume/*` | **Не использовать** |

**Жизненный цикл при удалении:**

```
Удаление PVC
       │
       ▼
┌─────────────────┐
│ Проверка        │
│ reclaimPolicy   │
└─────────────────┘
       │
       ├──────────────┬────────────────┐
       │              │                │
       ▼              ▼                ▼
  Retain          Delete            Recycle
       │              │           (deprecated)
       ▼              ▼
┌─────────────┐ ┌─────────────┐
│ PV →        │ │ Удаление    │
│ Released    │ │ PV          │
│             │ │             │
│ Требуется   │ │ Удаление    │
│ ручная      │ │ физического │
│ очистка     │ │ тома (СХД)  │
└─────────────┘ └─────────────┘
```

> **Рекомендация:** Для production всегда используйте `Retain` и вручную контролируйте удаление данных. Для создания точек восстановления используйте [Volume Snapshots](./CSI/csi_advanced.md#volume-snapshots-api).

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

---

## StorageClass и динамическое выделение

### Назначение StorageClass

`StorageClass` описывает "классы" или "профили" хранилища с различными характеристиками:

- **Тип хранилища** (SSD, HDD, сетевое)
- **Provisioner** (CSI-драйвер для работы с конкретной СХД)
- **Параметры выделения** (тип диска, зона доступности, шифрование)
- **Политика возврата** (`Retain` или `Delete`)
- **Режим привязки** (`Immediate` или `WaitForFirstConsumer`)

### Ключевые параметры

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard-ssd
provisioner: ebs.csi.aws.com        # CSI-драйвер
parameters:
  type: gp2                         # Параметры для драйвера
reclaimPolicy: Delete               # Политика возврата
volumeBindingMode: WaitForFirstConsumer  # Режим привязки
allowVolumeExpansion: true          # Разрешить расширение
```

#### `volumeBindingMode`

| Режим | Описание | Когда использовать |
|-------|----------|-------------------|
| `Immediate` | PV создаётся сразу при создании PVC | Простые однозонные кластеры |
| `WaitForFirstConsumer` | PV создаётся после появления пода | Многозонные кластеры, локальные хранилища |

> **Важно:** Для stateful-приложений в многозонных кластерах всегда используйте `WaitForFirstConsumer`.

---

## Практические сценарии

### Пример: Динамическое выделение для Ceph RBD (локальный аринт)

```yaml
# 1. StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-ssd
provisioner: rbd.csi.ceph.com
parameters:
  pool: replicapool
  clusterID: rook-ceph
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: rook-ceph
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true

---
# 2. PersistentVolumeClaim
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-app-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-ssd
  resources:
    requests:
      storage: 10Gi

---
# 3. Pod с PVC
apiVersion: v1
kind: Pod
metadata:
  name: my-app-pod
spec:
  containers:
    - name: my-app
      image: nginx
      volumeMounts:
        - name: my-storage
          mountPath: /usr/share/nginx/html
  volumes:
    - name: my-storage
      persistentVolumeClaim:
        claimName: my-app-pvc
```

### Пример: Статическое выделение для NFS

```yaml
# 1. PV (администратор)
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-logs-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  nfs:
    path: /var/k8s-logs
    server: 192.168.1.100

---
# 2. PVC (разработчик)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: fluentd-logs-pvc
  namespace: logging
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Gi

---
# 3. Pod с PVC
apiVersion: v1
kind: Pod
metadata:
  name: fluentd
  namespace: logging
spec:
  containers:
    - name: fluentd
      image: fluent/fluentd
      volumeMounts:
        - name: log-storage
          mountPath: /fluentd/log
  volumes:
    - name: log-storage
      persistentVolumeClaim:
        claimName: fluentd-logs-pvc
```

### StatefulSet с PersistentVolume

Для stateful-приложений (БД) используется **[StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md)**. Он автоматически создаёт уникальный PVC для каждого пода на основе `volumeClaimTemplates`.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    spec:
      containers:
        - name: postgres
          image: postgres:15
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: standard-ssd
        resources:
          requests:
            storage: 10Gi
```

---

## Дополнительная информация

### Связанные темы

- **[CSI Overview](./CSI/csi_overview.md)** — базовая информация об архитектуре CSI
- **[CSI Advanced](./CSI/csi_advanced.md)** — VolumeSnapshots, клонирование, расширение томов, топология
- **[CSI Drivers Comparison](./CSI/csi_drivers_comparison.md)** — сравнение драйверов, диагностика
- **[Local Path Provisioner](./local-path-provisioner.md)** — локальное хранилище на узлах
- **[NFS Provisioner](./nfs-subdir-external-provisioner.md)** — динамическое выделение на NFS
- **[Ceph RBD](./Ceph/ceph_csi_rbd_driver_setup.md)** — блочное хранилище Ceph
- **[Ceph CephFS](./Ceph/ceph_csi_cephfs_driver_setup.md)** — файловая система Ceph

### Официальная документация

- [Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/)
- [Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
