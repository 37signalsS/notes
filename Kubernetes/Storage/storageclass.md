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
```

### `provisioner` (провижинер)

Поле определяет, какой плагин будет отвечать за создание тома. 
> **Важно:** С версий 1.24+ старые встроенные драйверы (`in-tree`, начинающиеся с `kubernetes.io/`) считаются устаревшими. Всегда используйте **CSI-драйверы**.

| Провижинер | Технология |
|---|---|
| `ebs.csi.aws.com` | AWS EBS |
| `pd.csi.storage.gke.io` | Google Cloud Persistent Disk |
| `rbd.csi.ceph.com` | Ceph RBD (Блочное устройство) |
| `cephfs.csi.ceph.com` | CephFS (Файловая система) |
| `driver.longhorn.io` | [Longhorn](./longhorn.md) |
| `nfs.csi.k8s.io` | Универсальный NFS через CSI |
| `rancher.io/local-path` | [Local Path Provisioner](./local-path-provisioner.md) |

### `volumeBindingMode` (режим привязки)

Определяет момент создания физического тома:

1. **`Immediate`** (по умолчанию): Том создается сразу после создания PVC.
   - **Риск:** В многозонных (multi-AZ) кластерах диск может быть создан в Зоне А, а планировщик позже решит запустить Под в Зоне Б. Под не сможет примонтировать диск и зависнет в `Pending`.
2. **`WaitForFirstConsumer`** (рекомендуется): Том создается только тогда, когда Под, использующий этот PVC, назначен на конкретный узел.
   - **Преимущество:** Гарантирует создание тома в той же зоне/на том же узле, где фактически запущен Под. Обязательно для облачных дисков и локальных томов.

### `reclaimPolicy` (политика возврата)

Определяет судьбу физического диска после удаления PVC:
- **`Delete`**: Удаляет физический диск и PV автоматически.
- **`Retain`**: Сохраняет физический диск. PV переходит в статус `Released`. Требуется ручная очистка администратором. Рекомендуется для критических баз данных.

### `mountOptions` (параметры монтирования)

Список опций, которые будут переданы команде `mount` на узле. 
- Для NFS: `nfsvers=4.1`, `hard`, `timeo=600`.
- Для ускорения монтирования в современных K8s (1.30+) с SELinux: `context="system_u:object_r:container_file_t:s0"`.

---

## Практические сценарии

### Управление классом по умолчанию

Если в кластере установлен класс по умолчанию, PVC без указания `storageClassName` будет автоматически использовать его.

**Как сделать класс по умолчанию:**
```bash
kubectl annotate storageclass <name> storageclass.kubernetes.io/is-default-class=true
```

**Как убрать статус по умолчанию:**
```bash
kubectl annotate storageclass <name> storageclass.kubernetes.io/is-default-class=false --overwrite
```

### Динамическое изменение атрибутов (VolumeAttributesClass)

В новых версиях Kubernetes (1.30+ Beta) появился объект `VolumeAttributesClass`, который позволяет изменять параметры тома (например, IOPS) без его пересоздания.

```yaml
apiVersion: storage.k8s.io/v1alpha1
kind: VolumeAttributesClass
metadata:
  name: high-iops
driverName: ebs.csi.aws.com
parameters:
  iops: "10000"
```

---

## Дополнительная информация

- Архитектура и установка CSI: [Обзор CSI](./CSI/csi_overview.md).
- Расширенные возможности (снимки, клонирование): [CSI Advanced](./CSI/csi_advanced.md).
- Сравнение драйверов: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md).
- Работа с базами данных и StatefulSet: [Persistent Volumes и PVC](./pv_and_pvc.md).
- Официальная документация: [Storage Classes (en)](https://kubernetes.io/docs/concepts/storage/storage-classes/).
