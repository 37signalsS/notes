# StorageClass (классы хранения)

## Определения

**`StorageClass` (SC)** — объект Kubernetes, определяющий "профили" или "классы" доступного хранилища. Он выступает шаблоном для **динамического выделения (Dynamic Provisioning)** томов, избавляя администраторов от необходимости создавать каждый `PersistentVolume` (PV) вручную.

**`Динамическое выделение`** — процесс, при котором Kubernetes автоматически запрашивает у внешней системы хранения (SAN, NAS, локальные диски) создание физического диска и регистрирует его в кластере как PV в ответ на создание `PersistentVolumeClaim` (PVC).

**`CSI-драйвер` (Container Storage Interface Driver)** — стандартный плагин, реализующий интерфейс хранения контейнеров для конкретной СХД. Все современные provisioner'ы — это CSI-драйверы; встроенные (in-tree) плагины удалены в K8s 1.31+.

**`Provisioner`** — компонент CSI-драйвера, отвечающий за динамическое создание и удаление физических томов в СХД при создании/удалении PVC.

**`VolumeBindingMode`** — параметр StorageClass, определяющий момент создания физического тома: сразу при создании PVC (`Immediate`) или после назначения пода на узел (`WaitForFirstConsumer`).

**`ReclaimPolicy` (политика возврата)** — параметр, определяющий судьбу физического диска после удаления PVC: `Delete` (удаление диска) или `Retain` (сохранение данных).

**`VolumeAttributesClass`** — объект (GA в K8s 1.34), позволяющий изменять параметры производительности тома (IOPS, пропускную способность) на лету без пересоздания диска.

Подробнее о базовых концепциях PV/PVC: [Persistent Volumes и PVC](./pv_and_pvc.md).

---

## Основные концепции

### Назначение StorageClass

StorageClass абстрагирует детали реализации СХД. Разработчик запрашивает хранилище по смысловому имени (например, `fast-ssd`), а параметры реализации (тип диска в облаке, IOPS, шифрование) скрыты внутри SC.

**Ключевые возможности:**
- Определение конкретного **CSI-драйвера** (provisioner).
- Передача специфичных параметров (тип диска, файловая система).
- Управление жизненным циклом (политика возврата).
- Учет топологии кластера (зоны доступности).
- Определение параметров монтирования (mount options).
- **Динамическое изменение атрибутов:** Изменение IOPS/пропускной способности на лету через `VolumeAttributesClass` (начиная с K8s 1.34 GA).

**Важное свойство:** Большинство полей объекта `StorageClass` являются **неизменяемыми (immutable)** после создания. Для изменения параметров (например, типа диска) необходимо создать новый SC и обновить PVC (или использовать `VolumeAttributesClass`, если поддерживается).

---

## Параметры StorageClass

Типовой манифест современного StorageClass (CSI):

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
  annotations:
    storageclass.kubernetes.io/is-default-class: "false" # Сделать классом по умолчанию
provisioner: ebs.csi.aws.com           # CSI-драйвер (обязательно)
reclaimPolicy: Retain                  # Retain или Delete
volumeBindingMode: WaitForFirstConsumer # Immediate или WaitForFirstConsumer
allowVolumeExpansion: true             # Разрешить расширение тома
mountOptions:                          # Параметры монтирования в ОС
  - nodiscard
parameters:                            # Специфичные параметры драйвера
  type: gp3
  iops: "3000"
  throughput: "125"
  encrypted: "true"
allowedTopologies:                     # Ограничение создания томов по зонам
- matchLabelExpressions:
  - key: topology.ebs.csi.aws.com/zone
    values:
    - us-east-1a
    - us-east-1b
```

### `provisioner` (провижинер)

Поле определяет, какой плагин будет отвечать за создание тома. 
> **Важно:** Все встроенные (`in-tree`) плагины (например, `kubernetes.io/aws-ebs`) полностью удалены в версиях 1.31+. Всегда используйте современные **CSI-драйверы**.

| Провижинер | Технология | Режимы доступа |
|---|---|---|
| `ebs.csi.aws.com` | AWS EBS | RWO |
| `pd.csi.storage.gke.io` | Google Cloud PD | RWO, RWX (для Filestore) |
| `disk.csi.azure.com` | Azure Disk | RWO |
| `file.csi.azure.com` | Azure File | RWX |
| `rbd.csi.ceph.com` | Ceph RBD (Блок) | RWO, RWX (с ограничениями) |
| `cephfs.csi.ceph.com` | CephFS (Файлы) | RWX |
| `driver.longhorn.io` | [Longhorn](./longhorn.md) | RWO, RWX (через NFS) |
| `nfs.csi.k8s.io` | Универсальный NFS | RWX |
| `local.csi.openebs.io` | OpenEBS Local PV | RWO |
| `driver.linstor.linbit.com` | LINSTOR/DRBD | RWO, RWX (с 2-х узлов) |
| `nfs-subdir-external-provisioner` | NFS Subdir | RWX |
| `kubernetes.io/no-provisioner` | Local PV (内置) | RWO |

### `volumeBindingMode` (режим привязки)

Определяет момент создания физического тома:

1. **`Immediate`** (по умолчанию): Том создается сразу после создания PVC.
   - **Риск:** В многозонных (multi-AZ) кластерах диск может быть создан в Зоне А, а планировщик позже решит запустить Под в Зоне Б. Под не сможет примонтировать диск и зависнет в `Pending`.
2. **`WaitForFirstConsumer`** (рекомендуется): Том создается только тогда, когда Под, использующий этот PVC, назначен на конкретный узел.
   - **Преимущество:** Гарантирует создание тома в той же зоне/на том же узле, где фактически запущен Под. Обязательно для облачных дисков, локальных томов и топологически-зависимых систем.

### `reclaimPolicy` (политика возврата)

Определяет судьбу физического диска после удаления PVC:
- **`Delete`** (по умолчанию): Удаляет физический диск и объект PV автоматически. Удобно для временных данных.
- **`Retain`**: Сохраняет физический диск. PV переходит в статус `Released`. Требуется ручная очистка администратором. Рекомендуется для критических баз данных во избежание случайной потери данных.

### `allowVolumeExpansion`

Разрешает онлайн (без остановки пода) или офлайн расширение тома.
- Требует поддержки со стороны CSI-драйвера и файловой системы (XFS, Ext4 поддерживают расширение).
- После изменения размера в PVC, Kubernetes инициирует `FileSystemResize` на узле, где примонтирован том.

### `allowedTopologies` (топология)

Позволяет жестко ограничить зоны или узлы, в которых провижинер может создавать тома. Это полезно, если вы хотите, чтобы определенный класс хранения работал только в конкретных дата-центрах или стойках.

---

## Жизненный цикл StorageClass

### Этапы создания и использования StorageClass

```
1. Администратор создаёт StorageClass
         │
         ▼
2. StorageClass доступен в кластере
         │
         ▼
3. Пользователь создаёт PVC с указанием storageClassName
         │
         ├── Immediate binding ──> 4a. Provisioner создаёт физический том сразу
         │                              │
         │                              ▼
         │                         5a. PV создаётся и связывается с PVC (Bound)
         │
         └── WaitForFirstConsumer ──> 4b. Шедулер назначает Pod на узел
                                           │
                                           ▼
                                      5b. Provisioner создаёт том в нужной зоне
                                           │
                                           ▼
                                      6. PV связывается с PVC (Bound)
```

### Порядок изменений (Immutable vs Mutable)

| Поле | Mutable (можно менять) | Примечание |
|------|----------------------|------------|
| `provisioner` | ❌ Нет | Требует создания нового StorageClass |
| `reclaimPolicy` | ❌ Нет | Требует создания нового StorageClass |
| `volumeBindingMode` | ❌ Нет | Требует создания нового StorageClass |
| `allowVolumeExpansion` | ✅ Да | Можно включить/выключить без пересоздания |
| `parameters` | ❌ Нет | Требует нового StorageClass или VolumeAttributesClass |
| `allowedTopologies` | ❌ Нет | Требует нового StorageClass |
| `mountOptions` | ❌ Нет | Требует нового StorageClass |
| `metadata.annotations` | ✅ Да | Можно менять аннотации |
| `metadata.labels` | ✅ Да | Можно менять метки |

### Миграция между StorageClass

Если нужно изменить параметры (например, тип диска или `reclaimPolicy`):

```bash
# 1. Создайте новый StorageClass
kubectl apply -f new-storageclass.yaml

# 2. Для существующих PVC — измените storageClassName
kubectl patch pvc <pvc-name> -p '{"spec":{"storageClassName":"new-class"}}'

# 3. Для нового provisioning — используйте новый класс в PVC
```

**Важно:** изменение `storageClassName` у существующего PVC **не перемещает** данные. Физический том остаётся прежним. Новый класс используется только при создании **новых** томов.

---

## Практические сценарии

### Сценарий 1: Набор StorageClass для разных нагрузок

```yaml
# 1. Высокопроизводительный SSD для БД (production)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
  annotations:
    storageclass.kubernetes.io/is-default-class: "false"
provisioner: driver.longhorn.io
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  numberOfReplicas: "3"
  replicaSoftAntiAffinity: "true"
  staleReplicaTimeout: "2880"
---
# 2. Стандартный HDD для логов и временных данных
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard-hdd
provisioner: driver.longhorn.io
reclaimPolicy: Delete
volumeBindingMode: Immediate
allowVolumeExpansion: true
parameters:
  numberOfReplicas: "1"
  staleReplicaTimeout: "1440"
---
# 3. Локальные NVMe для максимальной производительности
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-nvme
provisioner: kubernetes.io/no-provisioner
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: false
```

### Сценарий 2: Управление классом по умолчанию

```bash
# Сделать класс по умолчанию
kubectl annotate storageclass longhorn storageclass.kubernetes.io/is-default-class=true

# Убрать класс по умолчанию
kubectl annotate storageclass longhorn storageclass.kubernetes.io/is-default-class-

# Проверить, какой класс сейчас default
kubectl get storageclass | grep "(default)"
# → longhorn (default)   driver.longhorn.io   Delete   WaitForFirstConsumer   true   10d
```

**Внимание:** Если в кластере более одного SC помечено как `default`, динамическое выделение может завершиться ошибкой, так как контроллер не сможет выбрать класс.

### Сценарий 3: Динамическое изменение атрибутов (VolumeAttributesClass)

Начиная с Kubernetes 1.34 (Stable), объект `VolumeAttributesClass` позволяет изменять параметры производительности тома (например, IOPS или Tier) без его пересоздания и без изменения размера.

```yaml
apiVersion: storage.k8s.io/v1
kind: VolumeAttributesClass
metadata:
  name: performance-tier-gold
driverName: driver.longhorn.io
parameters:
  numberOfReplicas: "3"
  replicaSoftAntiAffinity: "true"
  fromBackup: ""
---
apiVersion: storage.k8s.io/v1
kind: VolumeAttributesClass
metadata:
  name: performance-tier-silver
driverName: driver.longhorn.io
parameters:
  numberOfReplicas: "2"
  replicaSoftAntiAffinity: "false"
```

Применение к PVC:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  storageClassName: longhorn
  volumeAttributesClassName: performance-tier-gold
  resources:
    requests:
      storage: 100Gi
```

```bash
# Проверить текущий VolumeAttributesClass
kubectl get pvc my-pvc -o jsonpath='{.spec.volumeAttributesClassName}'
# → performance-tier-gold

# Переключить на другой профиль
kubectl patch pvc my-pvc -p '{"spec":{"volumeAttributesClassName":"performance-tier-silver"}}'
```

### Сценарий 4: Настройка для мультизональных кластеров

Для обеспечения отказоустойчивости и правильного маппинга зон всегда используйте сочетание:
1. `volumeBindingMode: WaitForFirstConsumer`
2. Настройка `allowedTopologies` для ограничения зон

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: multi-zone-ssd
provisioner: driver.longhorn.io
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
allowedTopologies:
- matchLabelExpressions:
  - key: topology.kubernetes.io/zone
    values:
    - zone-a
    - zone-b
    - zone-c
parameters:
  numberOfReplicas: "3"
  replicaSoftAntiAffinity: "true"
```

### Сценарий 5: NFS StorageClass с поддиректориями

Для NFS-хранилища с автоматическим созданием поддиректорий:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: managed-nfs
provisioner: cluster.local/nfs-client-provisioner
parameters:
  pathPattern: "${.PVC.namespace}-${.PVC.name}"
  archiveOnDelete: "true"
reclaimPolicy: Delete
volumeBindingMode: Immediate
mountOptions:
  - nfsvers=4.1
  - rsize=1048576
  - wsize=1048576
  - hard
```

### Сценарий 6: Локальные диски (Local PV)

Для локальных NVMe-дисков с привязкой к конкретным узлам:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-nvme
provisioner: kubernetes.io/no-provisioner
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: false
mountOptions:
  - noatime
  - nodiratime
---
# PV для каждого локального диска
apiVersion: v1
kind: PersistentVolume
metadata:
  name: local-nvme-node1
spec:
  capacity:
    storage: 1Ti
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-nvme
  local:
    path: /dev/nvme0n1
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - node-worker-1
```

### Сценарий 7: Ceph RBD StorageClass

Для Ceph RBD с динамическим выделением:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-block
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: <fsid-ceph-cluster>
  pool: kubernetes
  csi.storage.k8s.io/provisioner-secret-name: csi-rbd-secret
  csi.storage.k8s.io/provisioner-secret-namespace: default
  csi.storage.k8s.io/node-stage-secret-name: csi-rbd-secret
  csi.storage.k8s.io/node-stage-secret-namespace: default
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
mountOptions:
  - discard
```

### Сценарий 8: Просмотр и диагностика StorageClass

```bash
# Список всех StorageClass
kubectl get storageclass
# → NAME                 PROVISIONER                    RECLAIMPOLICY   VOLUMEBINDINGMODE   ALLOWVOLUMEEXPANSION
# → longhorn (default)   driver.longhorn.io             Delete          WaitForFirstConsumer true
# → ceph-block           rbd.csi.ceph.com               Retain          Immediate           true
# → local-nvme           kubernetes.io/no-provisioner   Retain          WaitForFirstConsumer false

# Детали конкретного StorageClass
kubectl describe storageclass longhorn
# → Name:                  longhorn
# → Default StorageClass:  Yes
# → Allow Volume Expansion: true
# → Provisioner:           driver.longhorn.io
# → Parameters:            numberOfReplicas=3,...
# → Reclaim Policy:        Delete
# → Volume Binding Mode:   WaitForFirstConsumer

# Проверить, какие PVC используют конкретный StorageClass
kubectl get pvc --all-namespaces -o json | jq -r '.items[] | select(.spec.storageClassName=="longhorn") | "\(.metadata.namespace)/\(.metadata.name)"'

# Проверить PVC без указанного storageClassName (используют Default)
kubectl get pvc --all-namespaces -o json | jq -r '.items[] | select(.spec.storageClassName==null) | "\(.metadata.namespace)/\(.metadata.name)"'
```

---

## Производительность

### Факторы, влияющие на выбор StorageClass

| Фактор | Влияние | Рекомендация |
|--------|---------|--------------|
| **Тип диска** | HDD ~100 IOPS, SSD ~10K+ IOPS | Для БД и кэширования — SSD/NVMe |
| **Режим доступа** | RWO (один узел) vs RWX (много узлов) | RWO быстрее (нет сетевого оверхеда) |
| **Replication Factor** | 1 (нет отказоустойчивости) vs 3 (теряет 2 узла) | Production: 3, Dev/Test: 1 |
| **Network** | Сетевая задержка между узлами и СХД | Для latency-критичных нагрузок — Local PV |
| **Filesystem** | ext4/xfs для файлов, raw для блочных устройств | XFS лучше для больших файлов |
| **Mount Options** | `noatime`, `discard`, `nobarrier` | Используйте для улучшения производительности |

### Оптимизация mountOptions

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: high-perf-ssd
provisioner: driver.longhorn.io
mountOptions:
  - noatime          # Отключить обновление времени доступа
  - nodiratime       # Отключить обновление времени доступа к директориям
  - discard          # TRIM для SSD (уменьшает износ)
  - data=writeback   # Ext4: отложенная запись (риск при аварии)
  - barrier=0        # Отключить барьеры (только для battery-backed SSD)
  - rsize=1048576    # Размер блока чтения (NFS)
  - wsize=1048576    # Размер блока записи (NFS)
```

### Мониторинг производительности

```bash
# Проверить IOPS и throughput на уровне CSI
kubectl logs -n longhorn-system <longhorn-manager-pod> | grep -i "iops\|throughput"

# Проверить использование диска на узле
df -h
iostat -x 1 5

# Проверить滞ожение (latency) на PVC
kubectl exec <pod-name> -- dd if=/dev/zero of=/data/testfile bs=1M count=100 oflag=direct
kubectl exec <pod-name> -- dd if=/data/testfile of=/dev/null bs=1M iflag=direct

# Проверить статистику Longhorn
kubectl get volumereplica -o wide
kubectl get volume -o wide
```

---

## Поиск и устранение неисправностей

### Диагностические команды

```bash
# Проверить StorageClass
kubectl get storageclass
kubectl describe storageclass <name>

# Проверить PVC
kubectl get pvc --all-namespaces
kubectl describe pvc <name> -n <namespace>

# Проверить PV
kubectl get pv
kubectl describe pv <name>

# Проверить CSI-драйвер
kubectl get csidriver
kubectl get pods -n <csi-namespace>

# Проверить события
kubectl get events --field-selector reason=ProvisioningFailed
kubectl get events --field-selector reason=ProvisioningSucceeded

# Проверить лимиты
kubectl get resourcequota -n <namespace>
```

### Типичные проблемы

| Ошибка | Причина | Решение |
|---|---|---|
| `FailedBinding`: no PersistentVolumeCheck found... | Нет PV, подходящего под запрос PVC, и не работает динамическое выделение. | Проверьте наличие SC, правильность имени `storageClassName` и статус провижинера. |
| `ProvisioningFailed`: Failed to provision volume... | Ошибка на стороне СХД (лимиты, права, недостаточно места). | Проверьте логи CSI-драйвера и квоты хранилища. |
| Под в `Pending`, PVC в `Bound` (AZ mismatch) | Диск создан в зоне А, а под назначен в зону Б. | Используйте `volumeBindingMode: WaitForFirstConsumer`. |
| `VolumeExpansion` завис в `Waiting for resize` | Файловая система не поддерживает онлайн-расширение или ошибка в CSI. | Перезапустите под для инициирования офлайн-расширения или проверьте версию CSI. |
| `StorageClass` не найден | Опечатка в `storageClassName` или SC удалён. | `kubectl get sc`, проверьте имя. |
| `ProvisionerFailed`: driver not found | CSI-драйвер не установлен или не запущен. | `kubectl get pods -n <csi-namespace>`, переустановите CSI. |
| `Multi-Attach error` | RWO-том примонтирован к нескольким узлам. | Дождитесь завершения detach, используйте `WaitForFirstConsumer`. |
| `ReclaimPolicy: Delete` удалил нужные данные | Администратор无意中 chose Delete вместо Retain. | Используйте `Retain` для production, настроите backup. |
| `VolumeAttributesClass` не применяется | CSI-драйвер не поддерживает `ModifyVolume` или версия K8s < 1.34. | Обновите CSI-драйвер и Kubernetes. |

---

## Дополнительная информация

- Базовые концепции: [Persistent Volumes и PVC](./pv_and_pvc.md).
- Практические примеры: [Практические сценарии PV и PVC](./pv_and_pvc_scenarios.md).
- Продвинутые механизмы: [Расширенные сценарии](./pv_pvc_advanced.md).
- Архитектура и установка CSI: [Обзор CSI](./CSI/csi_overview.md).
- Расширенные возможности (снимки, клонирование): [CSI Advanced](./CSI/csi_advanced.md).
- Сравнение драйверов: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md).
- Local Path Provisioner: [Local Path Provisioner](./local-path-provisioner.md).
- Longhorn StorageClass: [Longhorn](./longhorn.md).
- NFS Subdir: [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md).
- Официальная документация: [Storage Classes (en)](https://kubernetes.io/docs/concepts/storage/storage-classes/).
