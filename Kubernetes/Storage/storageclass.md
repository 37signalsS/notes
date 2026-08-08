# StorageClass (классы хранения)

## Определения

**`StorageClass` (SC)** — объект Kubernetes, определяющий "профили" или "классы" доступного хранилища. Он выступает шаблоном для **динамического выделения (Dynamic Provisioning)** томов, избавляя администраторов от необходимости создавать каждый `PersistentVolume` (PV) вручную.

**Динамическое выделение** — процесс, при котором Kubernetes автоматически запрашивает у внешней системы хранения (облако, SAN, NAS) создание физического диска и регистрирует его в кластере как PV в ответ на создание `PersistentVolumeClaim` (PVC).

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

## Практические сценарии

### Управление классом по умолчанию

Если в кластере установлен класс по умолчанию, PVC без указания `storageClassName` будет автоматически использовать его.

**Как сделать класс по умолчанию:**
```bash
kubectl annotate storageclass <name> storageclass.kubernetes.io/is-default-class=true
```

**Внимание:** Если в кластере более одного SC помечено как `default`, динамическое выделение может завершиться ошибкой, так как контроллер не сможет выбрать класс.

### Динамическое изменение атрибутов (VolumeAttributesClass)

Начиная с Kubernetes 1.34 (Stable), объект `VolumeAttributesClass` позволяет изменять параметры производительности тома (например, IOPS или Tier) без его пересоздания и без изменения размера.

```yaml
apiVersion: storage.k8s.io/v1
kind: VolumeAttributesClass
metadata:
  name: performance-tier-gold
driverName: ebs.csi.aws.com
parameters:
  type: io2
  iops: "15000"
```

Применение к PVC:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  storageClassName: fast-ssd
  volumeAttributesClassName: performance-tier-gold # Применение нового профиля
  resources:
    requests:
      storage: 100Gi
```

### Настройка для мультизональных кластеров

Для обеспечения отказоустойчивости и правильного маппинга зон всегда используйте сочетание:
1. `volumeBindingMode: WaitForFirstConsumer`
2. Настройка `nodeAffinity` в PV (автоматически делается CSI-драйвером).

---

## Поиск и устранение неисправностей

| Ошибка | Причина | Решение |
|---|---|---|
| `FailedBinding`: no PersistentVolumeCheck found... | Нет PV, подходящего под запрос PVC, и не работает динамическое выделение. | Проверьте наличие SC, правильность имени `storageClassName` и статус провижинера. |
| `ProvisioningFailed`: Failed to provision volume... | Ошибка на стороне СХД или облачного провайдера (лимиты, права). | Проверьте логи CSI-драйвера и квоты в облаке. |
| Под в `Pending`, PVC в `Bound` (AZ mismatch) | Диск создан в зоне А, а под назначен в зону Б. | Используйте `volumeBindingMode: WaitForFirstConsumer`. |
| `VolumeExpansion` завис в `Waiting for resize` | Файловая система не поддерживает онлайн-расширение или ошибка в CSI. | Перезапустите под для инициирования офлайн-расширения или проверьте версию CSI. |

---

## Дополнительная информация

- Архитектура и установка CSI: [Обзор CSI](./CSI/csi_overview.md).
- Расширенные возможности (снимки, клонирование): [CSI Advanced](./CSI/csi_advanced.md).
- Сравнение драйверов: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md).
- Работа с базами данных и StatefulSet: [Persistent Volumes и PVC](./pv_and_pvc.md).
- Официальная документация: [Storage Classes (en)](https://kubernetes.io/docs/concepts/storage/storage-classes/).
