# Обзор Container Storage Interface (CSI)

## Определения

**Container Storage Interface (CSI)** — это открытый стандарт, определяющий универсальный API (Application Programming Interface) для взаимодействия систем оркестрации контейнеров (CO), таких как Kubernetes, с внешними системами хранения данных (СХД).

Основная цель CSI — сделать плагины хранения данных "внешними" по отношению к основному коду Kubernetes, что позволяет вендорам СХД разрабатывать и обновлять свои драйверы независимо от циклов релиза Kubernetes.

**Преимущества использования CSI:**
- **Независимость разработки:** Сторонние поставщики могут выпускать обновления драйверов без необходимости изменять код самого Kubernetes.
- **Широкая экосистема:** Доступ к огромному списку СХД (облачных, сетевых и локальных), имеющих CSI-драйверы.
- **Безопасность и гибкость:** Драйверы работают в изолированных контейнерах, что упрощает их деплой через стандартные примитивы Kubernetes (Deployment, DaemonSet).
- **Стандартизация:** Один и тот же драйвер может (теоретически) работать в разных оркестраторах (Kubernetes, Nomad, Cloud Foundry).

**Ключевые задачи, решаемые CSI:**
- **Динамическое выделение (Provisioning):** Автоматическое создание и удаление томов в СХД.
- **Управление доступом (Attaching/Detaching):** Привязка тома к конкретному узлу кластера.
- **Монтирование (Mounting/Unmounting):** Подключение тома к файловой системе контейнера или проброс как блочного устройства.
- **Продвинутое управление:** Снапшоты (Snapshots), клонирование, расширение томов без остановки приложений и мониторинг здоровья.
- **Topology Awareness:** Учёт физического расположения данных (зоны доступности, стойки) при планировании подов.

---

## Базовые концепции

### Сервисы CSI (RPC Interface)

Спецификация CSI определяет три gRPC сервиса, которые должен реализовать драйвер:

1.  **Identity Service:** Предоставляет информацию о драйвере (название, версия) и его возможностях (Capabilities).
2.  **Controller Service:** Отвечает за операции на уровне всего кластера или СХД: создание/удаление томов, создание снапшотов, привязка тома к узлу.
3.  **Node Service:** Отвечает за операции на конкретном узле: монтирование (Stage/Publish), размонтирование, сбор статистики использования диска.

Каждый сервис реализуется одним процессом драйвера, но в Kubernetes они разворачиваются раздельно: контроллерная часть (Controller Service) — в control plane, а узелная часть (Node Service) — на каждом узле.

#### Ключевые RPC-вызовы

| Сервис | RPC | Назначение |
| :--- | :--- | :--- |
| **Identity** | `GetPluginInfo` | Имя драйвера и версия. |
| | `GetPluginCapabilities` | Поддерживаемые расширения (снапшоты, expand, publish/unpublish). |
| | `Probe` | Проверка готовности драйвера (используется `livenessprobe`). |
| **Controller** | `CreateVolume` / `DeleteVolume` | Создание и удаление тома в СХД (динамическое провижинирование). |
| | `ControllerPublishVolume` / `ControllerUnpublishVolume` | Привязка/отвязка тома к узлу (опционально, если `attachRequired: false`). |
| | `ValidateVolumeCapabilities` | Проверка, поддерживает ли том заявленные режимы (FS/Block, access modes). |
| | `ListVolumes`, `GetCapacity` | Инвентаризация томов и свободного места СХД (используются storage capacity tracking и health monitoring). |
| | `ControllerExpandVolume` | Расширение тома без остановки приложений. |
| | `ControllerModifyVolume` (CSI v1.12+, GA) | Изменение параметров тома на лету (например, QoS/IOPS через `VolumeAttributesClass`). |
| | `CreateSnapshot` / `DeleteSnapshot` / `ListSnapshots` | Жизненный цикл снапшотов. |
| **Node** | `NodeStageVolume` / `NodeUnstageVolume` | Подготовка устройства (форматирование, монтирование в глобальный Staging Path) и её откат. |
| | `NodePublishVolume` / `NodeUnpublishVolume` | Финальное монтирование в директорию пода и размонтирование. |
| | `NodeGetVolumeStats` | Статистика использования и состояние тома (`abnormal`, `condition`) — основа Volume Health Monitoring. |
| | `NodeExpandVolume` | Расширение ФС/блочного устройства на узле после `ControllerExpandVolume`. |
| | `NodeGetInfo` | Топологические метки узла и максимум томов на узел — данные попадают в `CSINode`. |

Полный перечень RPC и их параметров описан в [спецификации CSI](https://github.com/container-storage-interface/spec). Реализация необязательных RPC определяется драйвером: например, драйвер без поддержки снапшотов не реализует Controller-группу `*Snapshot*`.

### Спецификация CSI: версии и протокол

- CSI построен на **gRPC** поверх HTTP/2 и **Protocol Buffers**; обмен между драйвером и sidecar-контейнерами происходит по Unix-сокету внутри пода, а `kubelet` на узле подключается к драйверу также через Unix-сокет.
- Версия `v1.0` (2018) считается первой стабильной; актуальная стабильная версия — **v1.13.0** (июль 2026).
- Ключевые недавние добавления:
  - `v1.12.0` (октябрь 2025): `ControllerModifyVolume` переведён в **GA**; добавлен Alpha-вызов `GetSnapshot`.
  - `v1.13.0`: Alpha-расширения **`ListVolumes`/`GetVolumeHealth`** (Controller) и **`Snapshot Topology`** (учёт топологии при создании снапшотов).
- Спецификация обратно совместима: драйвер, реализующий `v1.x`, работает и со старым, и с новым CO, пока не использует вызовы, появившиеся позже.

### Архитектура CSI-драйвера в Kubernetes

Драйвер обычно разворачивается как комбинация контроллера и агентов на узлах.

#### 1. Controller Plugin (Control Plane)
Запускается как `Deployment` (обычно в единственном экземпляре или с лидером для HA).
- **Ответственность:** Взаимодействие с API СХД для выделения ресурсов.
- **Компоненты:** Состоит из самого кода драйвера и набора **Sidecar-контейнеров**, предоставляемых сообществом Kubernetes.

#### 2. Node Plugin (Data Plane)
Запускается как `DaemonSet` на каждом рабочем узле.
- **Ответственность:** Выполнение привилегированных операций монтирования через `kubelet`.
- **Взаимодействие:** `kubelet` общается с драйвером через локальный Unix-сокет.
- **Привилегии:** Контейнеру драйвера требуются `privileged: true`, доступ к host mount namespace и общим путям kubelet (см. [Регистрацию драйвера на узле](#регистрация-драйвера-на-узле-node-plugin-registration)).

#### 3. Вспомогательные контейнеры (Sidecars)
Обеспечивают интеграцию CSI с Kubernetes API, избавляя вендоров от написания логики слежения за объектами K8s:
- **`external-provisioner`:** Следит за PVC и вызывает `CreateVolume`.
- **`external-attacher`:** Следит за `VolumeAttachment` и вызывает `ControllerPublishVolume`.
- **`external-resizer`:** Обрабатывает запросы на расширение томов.
- **`external-snapshotter`:** Управляет жизненным циклом `VolumeSnapshot`.
- **`node-driver-registrar`:** Сообщает `kubelet` о наличии драйвера на узле (API регистрации плагинов).
- **`livenessprobe`:** Периодически вызывает RPC `Probe` и отдаёт результат через HTTP `/healthz` для штатной livenessProbe Kubernetes; при сбое драйвера kubelet перезапускает его контейнер. Стандартный HTTP-порт — `9808`. Включается как в контроллерный, так и в узелный под.
- **`external-health-monitor-controller`:** Периодически вызывает `ListVolumes`/`ControllerGetVolume` (controller-часть Volume Health Monitoring).

Чёткое разделение sidecar по подам означает, что **контроллерный под общается со СХД через сеть**, а **узелный под обязательно сидит на hostPath с сокетом kubelet**.

#### Регистрация драйвера на узле (Node Plugin Registration)

Kubelet динамически находит узелные CSI-плагины через механизм **Plugin Registration**:

1. `node-driver-registrar` (sidecar узелного пода) вызывает у драйвера RPC `GetPluginInfo` и `NodeGetInfo`, получая имя драйвера, ограничение по количеству томов и топологию.
2. Регистратор создаёт файл регистрации в каталоге `/var/lib/kubelet/plugins_registry/<driver>-reg.sock` — kubelet по нему «видит» новый драйвер и опрашивает его по протоколу регистрации.
3. Рабочий Unix-сокет самого драйвера размещается в `/var/lib/kubelet/plugins/<driver>/csi.sock` (имя каталога равно имени драйвера).
4. После успешной регистрации данные попадают в объект **`CSINode`** (по одному на узел), а в `/var/lib/kubelet/plugins_registry` появляется симлинк на сокет.

```bash
# На узле проверить зарегистрированный сокет драйвера (имя = имя CSIDriver)
ls -l /var/lib/kubelet/plugins_registry/            # регистрационные файлы и симлинки
ls -l /var/lib/kubelet/plugins/<driver>/csi.sock    # рабочий сокет драйвера
# → srwxr-xr-x 1 root root 0 ... /var/lib/kubelet/plugins/rbd.csi.ceph.com/csi.sock
```

Если сокет на узле отсутствует или `CSINode` не заполнен — узелный под не поднялся, драйвер не зарегистрирован и тома на этом узле монтироваться не будут.

### Режимы работы с томами (Volume Modes)

CSI поддерживает два основных режима использования томов:
- **`Filesystem`:** Том форматируется в файловую систему (ext4, xfs) и монтируется как директория.
- **`Block` (Raw Block):** Том пробрасывается в контейнер как необработанное блочное устройство (например, `/dev/sdb`). Это необходимо для высокопроизводительных БД, которые сами управляют разметкой диска.

Режим тома задаётся в PVC полем `volumeMode` (по умолчанию `Filesystem`). В комбинации с режимом действуют **режимы доступа (access modes)** из лейера PV/PVC (`ReadWriteOnce`, `ReadOnlyMany`, `ReadWriteMany`, `ReadWriteOncePod`): CSI-тома поддерживают подмножество, сообщаемое драйвером (см. [Сравнение и эксплуатация CSI-драйверов](./csi_drivers_comparison.md)).

### Объекты CSI в Kubernetes API

- **`CSIDriver`:** Кластерный ресурс, описывающий драйвер. Указывает, поддерживает ли он `Attach`, требует ли токен сервисного аккаунта и может ли работать с эфемерными томами. Именно по этому объекту Kubernetes решает, как вести себя с драйвером. Поля `spec`:
  - `attachRequired` — нужно ли вызывать Controller (Attach/Detach). Для файловых сетевых СХД (NFS, CephFS при публикации без attach) часто `false`.
  - `podInfoOnMount` — передавать ли драйверу в `volumeAttributes` метаданные пода (имя, namespace, UID, SA). Требуется драйверам, которые ограничивают доступ по подам (например, Secrets Store CSI).
  - `volumeLifecycleModes` — список режимов: `Persistent` (тома через PV/PVC) и `Ephemeral` (inline-тома).
  - `storageCapacity` — публикует ли драйвер объекты `CSIStorageCapacity` (Storage Capacity Tracking).
  - `fsGroupPolicy` — как драйвер обрабатывает `fsGroup` пода: `ReadWriteOnceWithFSType`, `File`, `None`.
  - `tokenRequests` — запрашивает ли драйвер токены сервисного аккаунта (audience).
  - `requiresRepublish` — требует ли повторного вызова `NodePublishVolume` для уже примонтированных томов (используется ротацией секретов).
  - `seLinuxMount` — поддерживает ли драйвер монтирование с SELinux-меткой через `-o context=<label>` вместо рекурсивной переразметки (`Relabel`). Alpha с K8s 1.25, по умолчанию включено с 1.28, **Stable с K8s 1.37**.
- **`CSINode`:** Хранит информацию о драйвере на конкретном узле, включая топологические метки (например, `topology.ebs.csi.aws.com/zone: us-east-1a`) и максимум томов на узел.
- **`VolumeAttachment`:** Служит для отслеживания процесса привязки PV к конкретному узлу. Существует независимо от драйвера: создаётся контроллером `attach/detach` при назначении пода на узел и удаляется после детача.

### Жизненный цикл тома (Workflow)

1.  **Provisioning:** `external-provisioner` обнаруживает новый PVC → вызывает `CreateVolume` у Controller Plugin → появляется PV, связанный с PVC.
2.  **Attaching:** Планировщик назначает под на узел → `external-attacher` вызывает `ControllerPublishVolume` (привязка тома к узлу в СХД). Этот шаг пропускается, если `attachRequired: false`.
3.  **Staging (`NodeStageVolume`):** Выполняется на узле. Драйвер подготавливает устройство (например, форматирует) и монтирует его в глобальный путь (Staging Path) `/var/lib/kubelet/plugins/kubernetes.io/csi/pv/<pv>/globalmount`.
4.  **Publishing (`NodePublishVolume`):** Финальное монтирование из глобального пути в приватную директорию пода `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~csi/<pv>/mount`.

Размонтирование и освобождение идут в обратном порядке:

5.  **Unpublish / Unstage:** при удалении пода kubelet вызывает `NodeUnpublishVolume` (размонтирование приватной директории) и `NodeUnstageVolume` (размонтирование Staging Path). Только после этого становятся возможными отключение и новая публикация на другом узле.
6.  **Detach:** `external-attacher` вызывает `ControllerUnpublishVolume` и удаляет `VolumeAttachment` (если `attachRequired: true`).
7.  **Delete:** при удалении PVC `external-provisioner` вызывает `DeleteVolume`. **Важно:** если PV имеет `reclaimPolicy: Retain`, внешний том в СХД сохраняется, но его объект PV удаляется — для его повторного использования понадобится статическое провижинирование.

Шаги 2–4 могут выполняться с **read-only** доступом: поле `readOnly: true` в `volumeMounts`/`volumes` передаёт драйверу запрос на монтирование только для чтения.

---

## Практические сценарии

### Эфемерные тома (CSI Ephemeral Inline Volumes)

Позволяют использовать CSI-драйверы для монтирования томов напрямую в описании пода, минуя создание PV/PVC. Это часто используется для "инъекции" данных.
- **Примеры:** Secrets Store CSI (секреты из Vault), Cert-manager CSI (сертификаты).

**Требования к драйверу:**
- В объекте `CSIDriver` указан режим `volumeLifecycleModes: [Ephemeral]` (или `Persistent` + `Ephemeral`).
- Для таких томов вызываются только `NodePublishVolume`/`NodeUnpublishVolume` — динамическое провижинирование, attach и Staging отсутствуют.
- Жизненный цикл тома жёстко привязан к поду: при удалении пода kubelet должен удалить том (обычно через `NodeUnpublishVolume`), поэтому для Persistent-томов inline-режим **не** используется.

```yaml
kind: Pod
apiVersion: v1
metadata:
  name: my-csi-app
spec:
  containers:
    - name: app
      image: busybox
      volumeMounts:
      - name: ephemeral-storage
        mountPath: "/data"
  volumes:
    - name: ephemeral-storage
      csi:
        driver: secrets-store.csi.k8s.io
        volumeAttributes:
          secretProviderClass: "my-vault-provider"
```

**Особенности эксплуатации:**
- Внутренний том не виден через `kubectl get pvc`/`pv`; доступ к данным только внутри пода.
- При драйверах, требующих доступа к секретам, используется `nodePublishSecretRef` (ключи для аутентификации драйвера в СХД).
- Для отображения пода в метаданных драйвера нужно `podInfoOnMount: true` (актуально для Secrets Store CSI с его `SecretProviderClassPodStatus`).

### Установка CSI-драйвера (архитектура манифестов)

Вне зависимости от поставщика, онбординг CSI-драйвера в кластере сводится к созданию следующих объектов (в примерах — шаблон с плейсхолдерами `<driver>`):

1.  **ServiceAccount** и RBAC для controller-части (прав на PVC/PV, VolumeAttachment, конфигмапы и т.д. — перечень зависит от набора sidecar).
2.  **`CSIDriver`** с корректными полями `spec` — без него Kubernetes ведёт себя по умолчанию (считает attach обязательным, режим — только Persistent), что ломает работу NFS/эфемерных драйверов.
3.  **Controller Plugin (Deployment/StatefulSet):** сам контейнер драйвера + sidecar (`external-provisioner`, `external-attacher`, `external-resizer`, `livenessprobe`, при необходимости `external-snapshotter` и `external-health-monitor-controller`).
4.  **Node Plugin (DaemonSet):**
    - `hostPath` сокета драйвера: `/var/lib/kubelet/plugins/<driver>/` → `/csi/`
    - каталог регистрации: `/var/lib/kubelet/plugins_registry/` → `/registration/`
    - `privileged: true`, как правило `hostNetwork` и монтирование `/sys`/`/dev`/`/lib/modules` для операций с блочными устройствами.
    - `PriorityClass: system-node-critical` и tolerance на `CriticalAddonsOnly`, чтобы драйвер не вытеснялся при нехватке ресурсов.

Для on-prem инсталляций на Ceph самый простой путь — установка через Helm:

```bash
# Вариант A: Rook (оператор сам ставит ceph-csi-драйверы RBD/CephFS)
helm repo add rook-release https://charts.rook.io/release
helm install --create-namespace --namespace rook-ceph rook-ceph rook-release/rook-ceph

# Вариант B: ceph-csi напрямую (например, только RBD-драйвер), чарты ceph/csi-charts
helm repo add ceph-csi https://ceph.github.io/csi-charts
helm install --namespace storage ceph-csi-rbd ceph-csi/ceph-csi-rbd
```

Детали конфигурации Ceph (пулы, storage class) описаны в [Обзор Ceph](../Ceph/ceph_overview.md) и в [Сравнение и эксплуатация CSI-драйверов](./csi_drivers_comparison.md) (подготовка узлов: `open-iscsi`, `multipathd`, модули ядра `rbd`/`ceph`).

### Проверка CSI-стека после установки

Пошаговое подтверждение того, что драйвер полностью зарегистрирован и готов:

```bash
# 1. Объект CSIDriver существует в кластере
kubectl get csidriver
# → NAME                   ATTACHREQUIRED   PODINFOONMOUNT   STORAGECAPACITY
# → rbd.csi.ceph.com       true             false            false

# 2. Controller Plugin запущен и sidecar живы
kubectl get pods -n rook-ceph -l app=csi-rbdplugin-provisioner
# → NAME                     READY   STATUS    RESTARTS
# → csi-rbdplugin-provisioner-0   6/6  Running   0

# 3. Node Plugin запущен на всех узлах
kubectl get pods -n rook-ceph -l app=csi-rbdplugin
# → NAME                         READY   STATUS    RESTARTS
# → csi-rbdplugin-abc12          4/4     Running   0

# 4. Драйвер зарегистрирован на конкретном узле (kubelet Plugin Registration)
kubectl get csinode <node-name> -o yaml | grep -A5 rbd.csi.ceph.com
# → - drivers:
# →   - name: rbd.csi.ceph.com
# →     nodeID: <node-name>

# 5. Проверка liveness-пробы: контейнер драйвера отвечает на Probe
kubectl describe pod -l app=csi-rbdplugin-provisioner -n rook-ceph | grep -A5 Liveness
# →   Liveness:  http-get http://:healthz/healthz delay=0s timeout=3s period=10s

# 6. На самом узле сокет и регистрация на месте
ssh <node-name> "ls -l /var/lib/kubelet/plugins/rbd.csi.ceph.com/"
```

Ожидаемый результат: `CSIDriver` виден в кластере, controller и node plugin в `Running`, в `CSINode` есть driver, livenessProbe зелёная, на узле существует сокет. Если шаг 4 пуст — см. [Регистрацию драйвера на узле](#регистрация-драйвера-на-узле-node-plugin-registration).

### Драйвер Ceph CSI

Широко применяется в bare-metal кластерах.
- **RBD (Block):** Идеально для RWO (ReadWriteOnce) нагрузок, таких как PostgreSQL или MySQL.
- **CephFS (Shared):** Поддерживает RWX (ReadWriteMany), позволяя нескольким подам одновременно писать в одну файловую систему.

Для RBD через ядро требуется модуль `rbd` на каждом узле; альтернатива — пользовательский мounter `nbd` (используется, например, для QoS через `ControllerModifyVolume`). Настройка StorageClass и снапшотов — в [Продвинутые возможности CSI](./csi_advanced.md) и [Сравнение и эксплуатация CSI-драйверов](./csi_drivers_comparison.md).

### Отслеживание емкости (Storage Capacity Tracking)

Современные драйверы сообщают Kubernetes об остатке свободного места в СХД. Это позволяет планировщику не назначать поды на узлы, где невозможно создать требуемый том, что критично для локальных хранилищ (Local Storage) и квот в облаках.

Механизм: драйвер публикует объекты **`CSIStorageCapacity`** (для этого в `CSIDriver` должен быть флаг `spec.storageCapacity: true`), а `kube-scheduler` при `volumeBindingMode: WaitForFirstConsumer` учитывает свободное место в конкретной зоне. Подробности и диагностика — в [Продвинутые возможности CSI](./csi_advanced.md) (раздел [Отслеживание ёмкости](#отслеживание-ёмкости-storage-capacity-tracking)).

---

## Дополнительная информация

### Мониторинг здоровья (Volume Health Monitoring)

CSI-драйверы могут сообщать о проблемах на уровне данных (ошибки ФС, выход диска из строя). Реализация состоит из двух частей:
- **Controller-часть:** sidecar `external-health-monitor-controller` разворачивается вместе с controller plugin и периодически вызывает `ListVolumes`/`ControllerGetVolume`, помечая тома в ненормальном состоянии.
- **Node-часть:** с Kubernetes 1.21 логика узла перенесена из устаревшего отдельного агента (`external-health-monitor-agent`, deprecated) в сам `kubelet`: он вызывает `NodeGetVolumeStats` и порождает события (Events) на подах с reason `VolumeConditionAbnormal` при обнаружении проблем.

События могут быть использованы для автоматического рестарта подов или оповещения администраторов. Функция контролируется Alpha feature gate `CSIVolumeHealth` и реализована у ограниченного круга драйверов. Развёрнутое описание статусов и метрик — в [Продвинутые возможности CSI](./csi_advanced.md) (раздел [Мониторинг здоровья томов](#мониторинг-здоровья-томов-volume-health-monitoring)).

### Сравнение с In-Tree плагинами

| Критерий | In-Tree (Legacy) | CSI (Current Standard) |
| :--- | :--- | :--- |
| **Место кода** | Внутри ядра Kubernetes | Внешний проект / Контейнер |
| **Обновление** | Только вместе с Kubernetes | Независимо, в любое время |
| **Привилегии** | Высокие (внутри Kubelet) | Минимально необходимые для контейнера |
| **Функционал** | Базовый | Полный (Snapshots, Resizing, Topology) |

> **Важно:** В 2026 году использование CSI является безальтернативным стандартом подключения СХД. Встроенные (in-tree) плагины объявлены **deprecated** и переводятся на соответствующие CSI-реализации через механизм **CSI Migration** (по умолчанию включён). Часть уже полностью удалена из Kubernetes: `gcePersistentDisk` — v1.28, Ceph RBD/CephFS — v1.31, `gitRepo` — v1.36; остальные (EBS, Azure Disk, vSphere, Cinder, Portworx и др.) по-прежнему существуют, но работают поверх CSI-драйверов. Подробный статус по каждому плагину — в [Продвинутые возможности CSI](./csi_advanced.md) (раздел [Миграция CSI](#миграция-csi-csi-migration)).

### Связанные темы
- **Сравнение решений:** [CSI Drivers Comparison](./csi_drivers_comparison.md) — выбор драйвера под конкретные задачи.
- **Продвинутый функционал:** [CSI Advanced Features](./csi_advanced.md) — снапшоты, клонирование и детальная топология.
- **Работа с S3:** [S3 CSI-драйверы](./s3-csi-drivers.md) — объектные хранилища как файловые системы.
- **Основы хранения:** [PV, PVC и StorageClass](../pv_and_pvc.md).

### Официальные источники
- [Kubernetes CSI Documentation](https://kubernetes.io/docs/concepts/storage/volumes/#csi)
- [CSI Spec (GitHub)](https://github.com/container-storage-interface/spec)
- [Kubernetes CSI Drivers List](https://kubernetes-csi.github.io/docs/drivers.html)