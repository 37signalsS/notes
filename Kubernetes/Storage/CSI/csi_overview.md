# Обзор Container Storage Interface (CSI)

## Определения

**Container Storage Interface (CSI)** — это открытый стандарт, определяющий универсальный API (Application Programming Interface) для взаимодействия систем оркестрации контейнеров (CO), таких как Kubernetes, с внешними системами хранения данных (СХД).

Основная цель CSI — сделать плагины хранения данных "внешними" по отношению к основному коду Kubernetes, что позволяет вендорам СХД разрабатывать и обновлять свои драйверы независимо от циклов релиза Kubernetes.

**Ключевые задачи, решаемые CSI:**
- **Динамическое выделение (Provisioning):** Автоматическое создание и удаление томов.
- **Подключение (Attaching/Detaching):** Привязка тома к конкретному узлу кластера.
- **Монтирование (Mounting/Unmounting):** Подключение тома к файловой системе контейнера.
- **Управление данными:** Снапшоты (Snapshots), клонирование и расширение томов.
- **Topology Awareness:** Учёт физического расположения данных (зоны доступности) при планировании.

> **Расширенные функции:** [CSI Advanced Features](./csi_advanced.md)

---

## Базовые концепции

### Архитектура CSI-драйвера

CSI-драйвер состоит из двух основных логических компонентов, работающих как поды в Kubernetes, и набора стандартных Sidecar-контейнеров, предоставляемых сообществом Kubernetes.

#### 1. Controller Plugin (Control Plane)
Централизованный компонент (обычно `Deployment` или `StatefulSet`), отвечающий за высокоуровневое управление томами через API СХД.
- **Функции:** Создание/удаление томов, создание снапшотов, управление квотами в СХД.
- **Взаимодействие:** Общается с API СХД и слушает запросы от Sidecar-контейнеров через gRPC.

#### 2. Node Plugin (Data Plane)
Компонент, работающий на каждом узле кластера (`DaemonSet`), выполняющий низкоуровневые операции.
- **Функции:** Форматирование дисков, монтирование (через `mount`), настройка путей для контейнеров.
- **Взаимодействие:** Слушает запросы от `kubelet` через локальный сокет на узле.

#### 3. Sidecar-контейнеры (Вспомогательные компоненты)
Для интеграции CSI-драйвера с Kubernetes используются стандартные вспомогательные контейнеры (sidecars), которые запускаются в том же поде, что и драйвер:
- **`external-provisioner`:** Следит за объектами `PersistentVolumeClaim` (PVC) и вызывает `CreateVolume` у драйвера.
- **`external-attacher`:** Следит за объектами `VolumeAttachment` и вызывает `ControllerPublishVolume` (привязка тома к ноде).
- **`external-resizer`:** Следит за изменениями размера в PVC и вызывает `ControllerExpandVolume`.
- **`external-snapshotter`:** Управляет созданием снапшотов через `VolumeSnapshot` объекты.
- **`node-driver-registrar`:** Регистрирует CSI-драйвер в `kubelet` на узле, передавая информацию о сокете.
- **`livenessprobe`:** Мониторит состояние здоровья драйвера и передаёт его в Kubernetes.

### Объекты CSI в Kubernetes API

Для работы CSI Kubernetes использует специальные ресурсы:
- **`CSIDriver`:** Объект, описывающий возможности драйвера (нужен ли `Attach`, поддерживает ли эфемерные тома).
- **`CSINode`:** Объект на каждом узле, содержащий информацию о зарегистрированных драйверах и их топологических данных (например, `topology.kubernetes.io/zone`).
- **`VolumeAttachment`:** Служебный объект, фиксирующий факт "прикрепления" тома к конкретному узлу.

### Жизненный цикл тома (Workflow)

Процесс подключения тома к поду проходит через следующие стадии:
1. **Provisioning:** `external-provisioner` видит PVC → Драйвер создаёт том в СХД → Создаётся объект `PersistentVolume` (PV).
2. **Attaching:** Kubernetes назначает под на узел → `external-attacher` привязывает том к этому узлу через API СХД.
3. **Staging (StageVolume):** `Node Plugin` форматирует устройство и монтирует его в глобальный каталог на узле (если том блочный).
4. **Publishing (PublishVolume):** `Node Plugin` монтирует том из глобального каталога в приватный каталог пода (bind mount).

---

## Практические сценарии

### CSI Ephemeral Inline Volumes (Эфемерные тома)

Некоторые драйверы (например, Secrets Store CSI, Cert-manager CSI) позволяют монтировать тома "на лету" без создания PV/PVC. Срок жизни такого тома ограничен жизненным циклом пода.

```yaml
kind: Pod
apiVersion: v1
metadata:
  name: my-csi-app
spec:
  containers:
    - name: my-frontend
      image: busybox
      volumeMounts:
      - name: my-csi-volume
        mountPath: "/data"
  volumes:
    - name: my-csi-volume
      csi:
        driver: inline.storage.kubernetes.io
        volumeAttributes:
          foo: bar
```

### Ceph CSI

Драйвер **Ceph CSI** — один из самых популярных для локальных кластеров.
- **RBD (RADOS Block Device):** Блочные устройства для баз данных (RWO). См. [Концепции Ceph RBD](../Ceph/ceph_rbd_usage/definitions_and_concepts.md).
- **CephFS:** Общие файловые системы (RWX) для медиа-данных или конфигов. См. [Концепции CephFS](../Ceph/cephfs_setup_and_usage/definitions_and_concepts.md).

### Драйвер Secrets Store CSI

Позволяет безопасно доставлять секреты из внешних Vault/KMS напрямую в поды.
- **Преимущество:** Секреты не сохраняются в `etcd` и доступны только в памяти пода (`tmpfs`).
- **См. также:** [Сравнение Secrets Store CSI](./csi_drivers_comparison.md#драйвер-secrets-store-csi).

---

## Дополнительная информация

### Мониторинг здоровья томов (Volume Health Monitoring)

Современные CSI-драйверы поддерживают мониторинг состояния данных. Если диск в СХД выходит из строя или файловая система повреждена, драйвер сообщает об этом через `external-health-monitor`, и Kubernetes может выдать Event или пометить узел как проблемный.

### Сравнение с In-Tree плагинами

| Критерий | In-Tree (Устарело) | CSI (Современно) |
| :--- | :--- | :--- |
| **Разработка** | Часть кода Kubernetes | Отдельный проект вендора |
| **Цикл релиза** | Раз в 3-4 месяца | Независимый |
| **Безопасность** | Нужны права root для Kubelet | Изолированные контейнеры |
| **Возможности** | Базовые | Snapshots, Cloning, Health Check |

> **Важно:** В Kubernetes 1.31+ большинство in-tree плагинов полностью удалены. Использование CSI обязательно. Подробнее в [CSI Migration](./csi_advanced.md#миграция-csi).

### Связанные темы
- **Сравнение драйверов:** [CSI Drivers Comparison](./csi_drivers_comparison.md) — выбор между Ceph, Longhorn и облачными решениями.
- **Продвинутые фичи:** [CSI Advanced Features](./csi_advanced.md) — детали работы снапшотов и топологии.
- **S3 CSI-драйверы:** [S3 CSI-драйверы](./s3-csi-drivers.md) — использование объектного хранилища в Kubernetes.
- **Основы хранения:** [PV, PVC и StorageClass](../pv_and_pvc.md).

### Официальные источники
- [Kubernetes CSI Docs](https://kubernetes.io/docs/concepts/storage/volumes/#csi)
- [CSI Driver List](https://kubernetes-csi.github.io/docs/drivers.html)
- [CSI Spec](https://github.com/container-storage-interface/spec)
