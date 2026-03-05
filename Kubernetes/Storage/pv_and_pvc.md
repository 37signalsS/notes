# PersistentVolume и PersistentVolumeClaim

## Определения

**`PersistentVolume` (PV)** — ресурс кластера, представляющий часть хранилища (NFS, RBD, CephFS, облачный диск). Имеет независимый от подов жизненный цикл. Содержит параметры СХД: тип, размер, путь, ID тома.

**`PersistentVolumeClaim` (PVC)** — запрос приложения к PV на выделение места. По аналогии с подами, запрашивающими CPU/память, PVC запрашивает у PV объём хранилища и режим доступа. При связывании PVC с PV, PV переходит в статус `Bound`.

**`StorageClass` (SC)** — механизм описания "классов" или "профилей" хранилища ("быстрый-ssd", "медленный-hdd"). Ключевой компонент — **`provisioner`** (плагин для взаимодействия с СХД). Современный стандарт — **[Container Storage Interface (CSI)](./CSI/csi_overview.md)**.

---

## Базовые концепции

### Проблема прямого управления томами

Изначально в Kubernetes тома определялись непосредственно в манифесте пода (`awsElasticBlockStore`, `gcePersistentDisk`).

**Недостатки:**

1. **Ручное создание томов** — администратор создаёт диски в СХД вручную.
2. **Жёсткая связь с инфраструктурой** — параметры доступа прописаны в манифесте приложения.
3. **Сложность миграции** — при смене облака требуется изменять манифесты всех приложений.

### Решение: трёхуровневая абстракция

| Роль | Задача |
|------|--------|
| **Разработчик** | Описывает требования: "нужно 10 ГБ быстрого хранилища с эксклюзивным доступом" |
| **Администратор** | Настраивает способы удовлетворения: "быстрое хранилище = SSD в облаке" |

### Режимы выделения хранилища

#### Динамическое выделение (Dynamic Provisioning) — рекомендуемый способ

Автоматический, событийно-ориентированный подход, стандарт для большинства кластеров.

**Пошаговый рабочий процесс:**

1. **Администратор** настраивает `StorageClass` и разворачивает **provisioner** — контроллер для работы с конкретной СХД.
2. **Разработчик** создаёт PVC с указанием `storageClassName`.
3. **Provisioner** обнаруживает новый PVC и создаёт физическое хранилище через API СХД.
4. Provisioner создаёт объект PV с информацией о новом ресурсе.
5. Kubernetes автоматически связывает PV с PVC (статус `Bound`).

**Преимущество:** Полная автоматизация. Разработчик не знает деталей инфраструктуры, администратор не создаёт тома вручную.

#### Статическое выделение (Static Provisioning)

Для интеграции с существующими СХД:

1. **Администратор** вручную создаёт PV, описывающий существующий том.
2. **Разработчик** создаёт PVC с параметрами под существующий PV.
3. **Kubernetes** связывает PVC с подходящим PV.

> **Разница:** статически — PVC получает весь PV (может быть избыточно); динамически — PV создаётся точно под запрошенный размер.

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
| **`Retain`** | PV и физический том сохраняются после удаления PVC | Production, важные данные |
| **`Delete`** | PV и физический том удаляются после удаления PVC | Dev/Test, временные данные |
| **`Recycle`** | **Устарело (deprecated)**. Очистка `rm -rf /thevolume/*` | **Не использовать** |

> **Рекомендация:** Для production всегда используйте `Retain` и вручную контролируйте удаление данных. Для создания точек восстановления используйте [Volume Snapshots](./CSI/csi_advanced.md#volume-snapshots-api).

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

### Пример: Динамическое выделение в облаке (AWS EBS)

```yaml
# 1. StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard-ssd
provisioner: ebs.csi.aws.com
parameters:
  type: gp2
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer

---
# 2. PersistentVolumeClaim
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-app-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard-ssd
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

Для stateful-приложений (БД) используется **[StatefulSet](../Concepts/statefulset_overview.md)**. Он автоматически создаёт уникальный PVC для каждого пода на основе `volumeClaimTemplates`.

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
