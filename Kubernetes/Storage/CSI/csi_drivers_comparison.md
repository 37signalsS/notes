# Сравнение и эксплуатация CSI-драйверов

Документ — основной справочник для выбора, сравнения и первичной диагностики CSI-драйверов в Kubernetes. Здесь сравниваются возможности драйверов, даются практические рекомендации по выбору, подготовке узлов, мониторингу и отладке. Подробное устройство CSI (сервисы, RPC, жизненный цикл тома) — в [Обзоре CSI](./csi_overview.md), продвинутый функционал (снапшоты, клонирование, топология, хранение и отказоустойчивость) — в [Продвинутых возможностях CSI](./csi_advanced.md).

## Определения

**CSI Driver (Container Storage Interface Driver)** — программная реализация спецификации интерфейса хранения контейнеров для конкретной системы хранения данных (СХД). Он выступает посредником между Kubernetes и API внешнего хранилища.

**Sidecar-контейнеры** — стандартные вспомогательные компоненты (external-provisioner, external-attacher и др.), которые обеспечивают интеграцию драйвера с объектами Kubernetes (PVC, PV, VolumeAttachment).

**Provisioner** — компонент драйвера, отвечающий за динамическое создание и удаление физических томов в СХД.

**Attacher** — компонент, отвечающий за логическую привязку (attach) тома к конкретному узлу кластера.

**Topology Awareness** — способность драйвера учитывать физическое расположение узлов (зоны, стойки, конкретные узлы) при планировании томов, обеспечивая локальность данных. Для использования требуется `volumeBindingMode: WaitForFirstConsumer` в StorageClass.

**Снимок (Volume Snapshot)** — консистентная точка во времени состояния тома, создаваемая на уровне СХД через RPC `CreateSnapshot`. В Kubernetes представлен объектами `VolumeSnapshot` / `VolumeSnapshotContent` и требует установки `snapshot-controller`, CRD и `VolumeSnapshotClass`. Снимок **не является резервной копией** (живёт только в той же СХД), но является основой для быстрого восстановления и создания новых томов.

**Клонирование (Volume Cloning)** — создание нового тома по содержимому существующего PVC (поле `spec.dataSource` в PVC) без обращения к снимкам. Как и снимок, реализуется на стороне СХД; способ (копирование или copy-on-write) зависит от драйвера.

**Расширение тома (Volume Expansion)** — увеличение размера существующего тома без пересоздания PVC. Требует `allowVolumeExpansion: true` в StorageClass, поддержки `ControllerExpandVolume`/`NodeExpandVolume` драйвером. Может требовать рестарт пода или перезагрузку файловой системы.

---

## Базовые концепции

### Классификация драйверов по типу хранилища

Тип хранилища определяет семантику доступа, возможности отказоустойчивости и способ эксплуатации:

*   **Block (блочные):** том предоставляется как блочное устройство (или файловая система поверх него). Характерен доступ `ReadWriteOnce`. Подходят для СУБД и приложений с низкими задержками. Отказоустойчивость реализуется на уровне СХД (репликация Ceph RBD, Longhorn, Mayastor) либо на уровне приложения (StatefulSet с пересозданием).
*   **File (файловые/сетевые):** том монтируется как сетевая файловая система (NFS, CephFS, JuiceFS, vSphere File). Как правило поддерживают `ReadWriteMany` — несколько подов на разных узлах пишут в общее пространство имён файлов.
*   **Object (объектные):** S3-совместимые хранилища (MinIO, Ceph RGW, публичные объектные хранилища), монтируемые в кластер через FUSE-маунтеры. Имеют особые ограничения этого класса и выделены в отдельный документ — [S3 CSI-драйверы](./s3-csi-drivers.md).
*   **Local (локальные):** тома, создаваемые из дисков конкретного узла (Local Path, TopoLVM, OpenEBS LocalPV). Минимальные задержки, но данные **физически привязаны к узлу**: при потере узла том и данные недоступны, а под не сможет «переехать» без восстановления данных из резервной копии.

### Сравнение возможностей популярных драйверов

Выбор драйвера зависит от типа инфраструктуры, требований к производительности и необходимости в дополнительных функциях (снапшоты, репликация). Условные обозначения в таблицах: `+` — поддержка есть, `-` — поддержки нет. Колонка «Режимы доступа» приведена по наиболее распространённым режимам каждого драйвера.

#### Облачные и Enterprise решения

| СХД / Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **AWS EBS** (`ebs.csi.aws.com`) | Block | + | + | + | + | RWO, RWOP |
| **GCP PD** (`pd.csi.storage.gke.io`) | Block | + | + | + | + | RWO, RWOP |
| **Azure Disk** (`disk.csi.azure.com`) | Block | + | + | + | + | RWO, RWOP |
| **Yandex Disk** (`disk.csi.yandex.ru`) | Block | + | + | + | + | RWO, RWOP |
| **vSphere CSI** (`vsphere.csi.vmware.com`) | Block/File | + | + | + | + | RWO, RWX |
| **Portworx** (`pxd.portworx.com`) | Block | + | + | + | + | RWO, RWX |

> **Примечание:** имена провижионеров в таблице соответствуют официальным self-managed дистрибутивам драйверов. В Managed-кластерах провайдер может использовать собственный набор драйверов и имён StorageClass (например, Yandex Managed Kubernetes). Имена облачных драйверов приведены справочно; раздел фокусируется на эксплуатации self-hosted решений.

#### Программно-определяемые (SDS) и Open Source

| СХД / Драйвер | Тип | Snapshots | Cloning | Expansion | Topology | Режимы доступа |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Ceph RBD** (`rbd.csi.ceph.com`) | Block | + | + | + | + | RWO, RWOP |
| **CephFS** (`cephfs.csi.ceph.com`) | File | + | + | + | + | RWX, RWO |
| **Longhorn** (`driver.longhorn.io`) | Block | + | + | + | - | RWO, RWX |
| **Linstor** (`linstor.csi.linbit.com`) | Block | + | + | + | + | RWO, RWOP |
| **Mayastor** (`mayastor.openebs.io`) | Block | + | + | + | + | RWO |
| **Local Path** (`rancher.io/local-path`) | Local | - | - | - | + | RWO |
| **TopoLVM** (`topolvm.cybozu.com`) | Block (локальный) | + | - | + | + | RWO |
| **OpenEBS LocalPV LVM** (`local.csi.openebs.io`) | Block (локальный) | + | - | + | + | RWO |
| **NFS** (`nfs.csi.k8s.io`) | File | + | + | + | - | RWX, RWO |
| **S3 CSI** (`csi-s3`, `geesefs`) | Object | - | - | - | - | RWO, RWX |
| **JuiceFS** (`juicefs.csi.k8s.io`) | File/S3 | + | + | + | + | RWX, RWO |

> **Примечание:** `RWOP` (ReadWriteOncePod) — эксклюзивный доступ только для одного пода на узле (доступно с Kubernetes 1.22+).

> **Примечание по локальным драйверам (TopoLVM, OpenEBS LocalPV):** снимки TopoLVM доступны только для device-class'ов на thin-пулах LVM (`lvcreate -T -n pool0 ...`), толстые (thick) тома снимков не имеют. OpenEBS LVM-LocalPV умеет снимки и их восстановление, но не поддерживает resize тома, имеющего снимок, и клонирование «том в том» (допустимо восстановление нового тома из снимка). Данные таких томов не реплицируются — особенность локальных решений: потеря узла, на котором создан том, означает потерю и данных.

> **Примечание по NFS:** снапшоты и клонирование NFS CSI (`nfs.csi.k8s.io`) поддерживаются в актуальных (v4.x) версиях драйвера. Снимок — это архив `.tar.gz` на самом NFS-сервере (создаётся драйвером), восстановление из него создаёт новый раздел `subDir` на том же шаре. Расширение требует `allowVolumeExpansion: true` и увеличивает подкаталог на сервере. Помните: такой «снимок» создаётся службой драйвера на выбранном сервере и не является снапшотом СХД — регулярно делайте полноценные бэкапы.

### Как читать таблицу возможностей

*   **Snapshots (+) — что это значит на практике:** при использовании снимков потребуется установка `snapshot-controller` и CRD `volumesnapshotclasses`/`volumesnapshots`/`volumesnapshotcontents`, а для каждого хранилища — свой `VolumeSnapshotClass` с `deletionPolicy`. Снимок быстрый и дешёвый, но хранится в той же СХД, поэтому для защиты от потери данных нужен полноценный бэкап (см. [Стратегии резервного копирования](../../Operations/backup-strategies.md) и раздел снапшотов в [Продвинутых возможностях CSI](./csi_advanced.md)).
*   **Cloning (+) — создание независимого тома из PVC:** в отличие от снапшота не требует отдельного класса, просто `dataSource` PVC в спецификации нового PVC. Удобно для развёртывания сред тестирования и подготовки копий данных.
*   **Expansion (+):** в StorageClass обязательно `allowVolumeExpansion: true`. Некоторые драйверы расширяют том в онлайне, другие требуют, чтобы под был остановлен (например, Yandex Disk — `expanding` только при пересоздании пода). Расширение всегда только в большую сторону.
*   **Topology (+):** драйвер публикует топологические метки узлов (`CSINode`) и умеет создавать том в нужной зоне. Критично для локальных хранилищ (том должен оказаться на том же узле, где будет под) и мультизональных кластеров. Без `WaitForFirstConsumer` топология не работает.

Полный жизненный цикл тома (Provisioning → Attaching → Staging → Publishing) и объекты `CSIDriver`/`CSINode`/`VolumeAttachment` описаны в [Обзоре CSI](./csi_overview.md).

---

## Практические сценарии

### Выбор драйвера по критериям

1.  **Максимальная производительность (NVMe-oF):**
    *   Рекомендуется: **Mayastor (OpenEBS)** или **Linstor**. Идеально для высоконагруженных СУБД в bare-metal кластерах.
2.  **Отказоустойчивость и репликация (SDS):**
    *   Рекомендуется: **Ceph** (универсальность) или **Longhorn** (простота управления).
3.  **Общий доступ к файлам (Shared Storage):**
    *   Рекомендуется: **CephFS**, **NFS CSI** или **JuiceFS** (через S3).
4.  **Безопасное хранение секретов:**
    *   Используйте **Secrets Store CSI Driver**. Он монтирует данные из внешних хранилищ (Vault, AWS Secrets Manager) напрямую в `tmpfs` пода.
5.  **Локальное низкозатратное хранение на узлах (node-local):** если приложение переносит привязку к узлу и не требует репликации — **TopoLVM** или **OpenEBS LocalPV LVM**. Минимальные задержки (никакой сети), но помните: данные живы только на одном узле, `drain` узла = недоступность томов.
6.  **Объектное хранилище как файловая система (архивы, контент, общие данные):** S3 CSI (MinIO/RGW) — подробно в [S3 CSI-драйверы](./s3-csi-drivers.md). Дешёвое масштабирование и RWX, но ограниченная POSIX-семантика (нет блокировок, жёстких ссылок, есть задержки метаданных). Не для реляционных СУБД.
7.  **Подключение уже существующих данных:** если том/каталог создавался вручную (архив, сервис-общие хранилища) — используйте **статическое** провижионирование (PV c `claimRef` + PVC без StorageClass), а не динамическое. Примеры — в [Сценариях PV/PVC](../pv_and_pvc_scenarios.md) и [S3 CSI-драйверы](./s3-csi-drivers.md).
8.  **Легаси-провижионеры NFS (не-CSI):** `nfs-subdir-external-provisioner` для простых сред документирован отдельно — [NFS Subdir External Provisioner](../nfs-subdir-external-provisioner.md); для новых кластеров предпочтителен CSI-драйвер `nfs.csi.k8s.io`.

Общее правило выбора: **блочные** драйверы — под СУБД и персистентные сервисы (RWO), **файловые** — под общие многопоточные данные (RWX), **объектные** — под большие архивы и контент (RWX плюс экономия), **локальные** — под производительность при готовности к потере данных при отказе узла.

### Дерево решений: выбор CSI-драйвера

```
Нужен RWX (общий доступ)?
├─ Да → Файловое хранилище
│   ├─ Простое решение, dev/test → NFS CSI (nfs.csi.k8s.io)
│   ├─ Высокая производительность → CephFS (cephfs.csi.ceph.com)
│   ├─ Нужны снимки + S3-бэкенд → JuiceFS (juicefs.csi.k8s.io)
│   └─ S3-данные как ФС → S3 CSI (GeeseFS/Mountpoint)
└─ Нет → RWO достаточно
    ├─ Максимальные IOPS (OLTP-БД)
    │   ├─ Нетребовательно к HA → Local PV (rancher.io/local-path)
    │   ├─ Нужна репликация → Ceph RBD (rbd.csi.ceph.com)
    │   ├─ Простое решение → Longhorn (driver.longhorn.io)
    │   └─ Enterprise SAN → LINSTOR (linstor.csi.linbit.com)
    ├─ Средние IOPS, нужна отказоустойчивость
    │   ├─ До 5 узлов → Longhorn
    │   ├─ 10+ узлов → Ceph RBD
    │   └─ VMware среда → vSphere CSI
    └─ Dev/Test
        ├─ K3s → Local Path Provisioner (по умолчанию)
        └─ Минималистичное → HostPath (не рекомендуется)

Нужны снимки (snapshots)?
├─ Да → Проверить поддержку CSI-драйвером
│   ├─ Ceph RBD → да, нативные
│   ├─ Longhorn → да, инкрементальные
│   ├─ NFS CSI → частично (архивы .tar.gz)
│   ├─ Local Path → нет
│   └─ vSphere → да, через vSAN
└─ Нет → любое решение

Нужно расширение тома (expansion)?
├─ Да → allowVolumeExpansion: true в StorageClass
│   └─ Все современные CSI-драйверы поддерживают
└─ Нет → любой StorageClass
```

### Подготовка узлов перед установкой драйверов

Разные драйверы предъявляют разные требования к хостовым узлам. Проверяйте до установки:

```bash
# Блочные драйверы на базе iSCSI (например, некоторые SDS):
apt-get install -y open-iscsi lsscsi xfsprogs
systemctl enable --now iscsid
# Подготовка инициализатора, multipath — см. Linux/Networking/iSCSI

# Ceph CSI RBD: требуется модуль ядра rbd (или userspace-режим mounter 'nbd')
modprobe rbd            # проверить: lsmod | grep rbd
# Резервные утилиты форматирования: xfsprogs (xfs), e2fsprogs (ext4)

# NFS CSI: клиент ядра mount.nfs
apt-get install -y nfs-common
# Проверка монтирования с узла: mount -t nfs4 <server>:/share /mnt

# S3 CSI (FUSE-маунтеры GeeseFS/s3fs):
apt-get install -y fuse3
ls -l /dev/fuse         # устройство проброса FUSE должно существовать
# Подробности on-prem MinIO/RGW — в [S3 CSI-драйверы](./s3-csi-drivers.md)

# Локальные LVM-драйверы (TopoLVM, OpenEBS LVM-LocalPV):
apt-get install -y lvm2 thin-provisioning-tools
pvs                     # на узле должна существовать VG/пул
```

Ожидаемые результаты: open-iscsi запущен, `rbd` в `lsmod`, `/dev/fuse` существует, `pvs` показывает томовую группу. Подготовка iSCSI подробно описана в [Настройка iSCSI-инициатора](../../../Linux/Networking/iSCSI/iscsi_initiator_setup.md) и [iSCSI Multipath](../../../Linux/Networking/iSCSI/iscsi_multipath.md), устройство Ceph — в [Обзоре Ceph](../Ceph/ceph_overview.md).

### Инвентаризация CSI-ресурсов

```bash
# Список зарегистрированных драйверов и их возможностей
kubectl get csidrivers
# → NAME                  ATTACHREQUIRED   PODINFOONMOUNT   STORAGECAPACITY
# → rbd.csi.ceph.com      true             false            false

# Детальный разбор одного драйвера (attachRequired, fsGroupPolicy, требует ли токен SA)
kubectl get csidriver rbd.csi.ceph.com -o yaml

# Информация о драйверах на узлах (топология, сокеты, nodeID)
kubectl get csinodes
kubectl get csinode <node-name> -o yaml | grep -A6 'name: rbd.csi.ceph.com'

# Проверка статуса управляющих подов драйвера
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver
kubectl get pods -n rook-ceph -l app=csi-rbdplugin-provisioner

# StorageClass: провижионер, volumeBindingMode, allowVolumeExpansion
kubectl get sc -o wide

# Снапшоты: классы и объекты (если установлен snapshot-controller)
kubectl get volumesnapshotclass
kubectl get volumesnapshot -A

# Тома и заявки: статусы и привязки
kubectl get pvc -A
kubectl get pv
```

Если драйвер установлен, но `kubectl get csidriver` его не показывает, либо `CSINode` не заполнен — узелный под драйвера не зарегистрировался (см. [Регистрацию драйвера на узле](./csi_overview.md#регистрация-драйвера-на-узле-node-plugin-registration)).

### Отладка жизненного цикла тома

Если PVC "завис" в статусе `Pending`, следуйте алгоритму:

1.  **Проверка PVC:** `kubectl describe pvc <name>`. Ищите события `FailedBinding`, `Provisioning failed`, `Timeout` и текст ошибки от провижионера — обычно он прямо указывает на причину (нет секретов, нет прав, нет бакета и т.п.).
2.  **Проверка StorageClass:** Убедитесь, что `provisioner` указан верно и драйвер запущен (`kubectl get csidriver`), а для динамики корректны `volumeBindingMode` и `allowVolumeExpansion`.
3.  **Логи контроллера:** очень важный шаг — найти конкретный под и смотреть логи конкретного sidecar:
    ```bash
    kubectl get pods -n rook-ceph
    # → csi-rbdplugin-provisioner-0 ...
    kubectl logs -n rook-ceph csi-rbdplugin-provisioner-0 -c csi-provisioner
    # Типичные строки: "provisioning" / "Failed to provision volume ..." с причиной
    ```
4.  **Проверка VolumeAttachment:** Для ошибок монтирования (Attach) проверьте объект привязки:
    ```bash
    kubectl get volumeattachment
    kubectl describe volumeattachment <id>
    # → PHASE: Attached / Detached — при PHASE=Failed ищите сообщение ошибки в событиях
    ```
5.  **Состояние PV и «прилипшие» claimRef:** если PV создан, но не привязался — `kubectl get pv <pv> -o yaml`, проверьте `claimRef`, `volumeAttributes`, статус. При `reclaimPolicy: Retain` старый PV не удаляется автоматически (см. [Сценарии PV/PVC](../pv_and_pvc_scenarios.md)).
6.  **Узелная диагностика:** ошибки `NodeStageVolume`/`NodePublishVolume` видны в событиях пода и в kubelet. Проверьте сокет драйвера на узле и наличие маунта:
    ```bash
    kubectl describe pod <pod-name> | grep -A10 Events
    ssh <node> "ls -l /var/lib/kubelet/plugins/<driver>/csi.sock && mount | grep <driver>"
    journalctl -u kubelet --since "10 min ago" | grep -i csi
    ```
7.  **Проверка после успешной привязки:** статус PVC → `Bound`, под в `Running`, маунт виден внутри пода (`df -h /mount/path`), а при блок-томе — блочное устройство (`lsblk`).

### Типовые неисправности

| Симптом | Вероятная причина | Метод решения |
| :--- | :--- | :--- |
| `Pending` PVC (Topology) | Узлы в другой зоне или нет ресурсов | Проверить `WaitForFirstConsumer` в SC и доступные зоны в `csinodes`. Для локальных драйверов — том на другом узле: пересоздать том или подобрать узел. |
| `MountVolume.SetUp failed` | Отсутствие бинарных файлов (iscsid, xfsprogs) | Установить зависимости на хосты (например, `apt install open-iscsi`). |
| `Permission Denied` | Неверные IAM-права или секреты | Проверить права ServiceAccount (IRSA для AWS) или `Secret` драйвера. |
| `Volume In Use` | Под не может отмонтировать диск | Проверить наличие финализаторов (`finalizers`) в объекте PV/PVC. |
| `FailedAttachVolume` / `Multi-Attach error for volume` | Попытка примонтировать RWO-том вторым подом на другом узле | Проверить размещение подов (`-o wide`). RWO — один писатель на кластер; для «строго один под» — `RWOP`. |
| `FailedScheduling` / `0/1 nodes available` (local) | Локальный том создан на другом узле, под не туда запланирован | Убедиться в `WaitForFirstConsumer` + `allowedTopologies`/nodeAffinity; локальные тома не мигрируют между узлами. |
| Expansion «не сработал» | `allowVolumeExpansion` не включён / драйвер требует offline | Проверить SC и логи `external-resizer`; некоторые драйверы требуют пересоздания пода. Расширение только в большую сторону. |
| `0/1 nodes are available: ... driver not ready` / `unknown driver` | CSIDriver отсутствует или node plugin не поднят | Установить/обновить CSIDriver (без него K8s ведёт себя по умолчанию), проверить DaemonSet и регистрацию на узле. |
| `Failed to provision volume with StorageClass "csi-s3"` | Проблемы S3 CSI (секреты, права, endpoint) | Диагностика — в [S3 CSI-драйверы](./s3-csi-drivers.md): проверить связку secret-ссылок в StorageClass, `--list-type`, доступность endpoint. |
| Нет данных в `kubelet_volume_stats_available_bytes` для блочного тома | Драйвер не реализует `NodeGetVolumeStats` (raw-block тома обычно статистику не отдают) | Убедиться в поддержке `NodeGetVolumeStats` драйвером; для ФС-томов данные есть в `kubelet /stats/summary`. |

### Лучшие практики эксплуатации

*   **Topology Awareness:** Всегда используйте `volumeBindingMode: WaitForFirstConsumer` для сетевых томов. Это гарантирует создание диска в той же зоне, где планировщик разместил под.
*   **Ресурсные лимиты:** Назначайте `PriorityClass: system-node-critical` для DaemonSet драйвера, чтобы предотвратить его вытеснение при нехватке памяти на узле.
*   **Мониторинг:** Настройте алерты на метрику `storage_operation_duration_seconds` для отслеживания задержек в операциях монтирования/создания.
*   **Безопасность:** Ограничивайте RBAC для драйвера только необходимыми пространствами имен или ресурсами.
*   **Снапшоты как часть DR:** регулярно создавайте `VolumeSnapshot` для важных томов и проверяйте восстановление из них до того, как оно понадобится (см. [Продвинутые возможности CSI](./csi_advanced.md) и [Стратегии резервного копирования](../../Operations/backup-strategies.md)). Снимок не заменяет бэкап.
*   **Плановые обновления драйвера:** перед обновлением проверяйте матрицу совместимости «драйвер ↔ sidecar ↔ Kubernetes» (курируются в [kubernetes-csi/docs](https://kubernetes-csi.github.io/docs/)). Обновляйте controller-часть и node-часть отдельно, поэтапно по узлам, после перезапуска проверяйте `CSINode` и живые маунты на узлах (`mount | grep <driver>`).
*   **Очистка и reclaimPolicy:** для прод-томов используйте `reclaimPolicy: Retain` и ручное управление удалением бакетов/каталогов, чтобы случайное удаление PVC не уничтожало данные. Удаляйте неиспользуемые снимки и классы своевременно.

### Мониторинг эксплуатации

Состояние томов и драйверов отслеживается с трёх уровней:

```bash
# 1) Kubelet: статистика каждого тома (работает для тома ФС-типа, где драйвер поддерживает NodeGetVolumeStats):
#    kubelet_volume_stats_capacity_bytes / available / used / inodes_*
#    Алерт на переполнение:
#    (kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) > 0.85

# 2) Kube-controller-manager: задержки операций attach/detach/provision:
#    storage_operation_duration_seconds{operation_name="volume_attach", ...}

# 3) Sidecar: включение HTTP-эндпоинта метрик у external-provisioner/attacher:
#    args: --http-endpoint=:9090   # экспонирует /metrics и /healthz/leader-election
#    метрики: csi_operations_seconds (гистограмма задержек RPC к драйверу), статусы операций
```

Ожидаемый результат: в Prometheus присутствуют ряды `kubelet_volume_stats_*` с метками `namespace`/`persistentvolumeclaim`, и отклонения latency подтверждаются по стороне драйвера. Особенность: для **блочных** (raw block) томов статистика `kubelet_volume_stats_*`, как правило, не публикуется — за их заполнением следит сама СХД. Общая настройка мониторинга Kubernetes описана в [Prometheus — Kubernetes](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/persistent_volumes.md).

---

## Дополнительная информация

### Связанные темы

- [Обзор CSI](./csi_overview.md) — детальная архитектура и жизненный цикл.
- [Продвинутые возможности CSI](./csi_advanced.md) — снапшоты, клонирование и расширение томов.
- [S3 CSI-драйверы](./s3-csi-drivers.md) — специфика работы с объектными хранилищами.
- [Persistent Volumes и PVC](../pv_and_pvc.md) — базовые объекты хранения.

### Ссылки

- [Kubernetes CSI Drivers List](https://kubernetes-csi.github.io/docs/drivers.html) — официальный реестр поддерживаемых драйверов.
- [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/) — документация по интеграции внешних секретов.
- [CSI Spec GitHub](https://github.com/container-storage-interface/spec) — официальная спецификация интерфейса.