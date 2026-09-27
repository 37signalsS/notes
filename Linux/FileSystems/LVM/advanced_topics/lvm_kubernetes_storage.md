# LVM в контексте Kubernetes: LocalPV, CSI-драйверы и сценарии использования

## Определения

**Kubernetes LocalPV** — тип PersistentVolume (PV), который привязан к конкретному узлу кластера и использует локальное хранилище (LVM, ZFS, диски) этого узла. В отличие от распределённых решений (Ceph, NFS), LocalPV обеспечивает минимальную задержку, но не поддерживает миграцию подов между узлами.

**CSI (Container Storage Interface)** — стандарт взаимодействия между оркестратором контейнеров (Kubernetes) и системами хранения. CSI-драйверы предоставляют плагины для provisioner (создание томов), node (монтирование на узле) и controller (управление жизненным циклом).

**Dynamic Provisioning** — автоматическое создание PersistentVolume при создании PersistentVolumeClaim. Если CSI-драйвер настроен, Kubernetes сам создаёт LV в VG при запросе пода.

**StorageClass** — объект Kubernetes, определяющий класс хранилища (provisioner, параметры, политику восстановления). Каждый StorageClass ссылается на конкретный CSI-драйвер.

**WaitForFirstConsumer** — политика привязки PV, при которой физическое создание тома откладывается до момента назначения пода на конкретный узел. Критична для LocalPV, чтобы том создавался на правильном узле.

**ReclaimPolicy** — политика обработки PV после удаления PVC: `Delete` (удалить LV), `Retain` (оставить LV).

## Базовые концепции

### Архитектура LVM + Kubernetes

```
Kubernetes API Server
    ↓
PersistentVolumeClaim (PVC)
    ↓
StorageClass (provisioner: lvm.topolvm.io или local-hostpath)
    ↓
CSI Driver Controller
    ↓ (создаёт LV)
Physical Node
    ↓
VG (volume group) → LV (logical volume) → mount → Pod
```

### Основные CSI-драйверы для LVM

| Драйвер | Проект | Особенности |
|:---|:---|:---|
| **topolvm** | TopoLVM | Dynamic provisioning, thin provisioning, snapshot через LVM, hardware-accelerated. Наиболее зрелый. |
| **localpv-provisioner** | OpenEBS | Простой provisioner для локальных LV, не требует CSI-контроллера. |
| **democratic-csi** | democratic-csi | Универсальный: поддерживает LVM, ZFS, iSCSI, FC. |
| **openebs-lvmlocalpv** | OpenEBS | LVM-based LocalPV, интеграция с OpenEBS ecosystem. |

### Сравнение: LVM vs распределённые решения

| Критерий | LVM LocalPV | Ceph RBD | NFS |
|:---|:---|:---|:---|
| **Задержка** | Минимальная (локальный I/O) | Средняя (сеть) | Высокая (сеть + файловый протокол) |
| **Миграция подов** | Нет (привязка к узлу) | Да | Да |
| **Масштабируемость** | Одиночный узел | Кластер | Сетевое хранилище |
| **Snapshot** | Да (LVM) | Да (Ceph) | Нет |
| **Сложность** | Низкая | Высокая | Средняя |

## Практические сценарии

### Шаг 1: Установка TopoLVM CSI (Helm)

```bash
# Добавление репозитория
helm repo add topolvm https://topolvm.github.io/topolvm
helm repo update

# Создание namespace
kubectl create namespace topolvm-system

# Создание VG для TopoLVM на каждом узле
# (на каждом узле):
sudo pvcreate /dev/nvme0n1
sudo vgcreate topolvm-vg /dev/nvme0n1

# Установка
helm install topolvm topolvm/topolvm \
  --namespace topolvm-system \
  --set controller.storage.topolvm.defaultVgName=topolvm-vg

# Проверка
kubectl get pods -n topolvm-system
kubectl get sc
```

### Шаг 2: Настройка StorageClass

```yaml
# storage-class-lvm.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: topolvm-provisioner
provisioner: topolvm.io
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
parameters:
  namePrefix: pvc-
allowVolumeExpansion: true
parameters:
  # Thin provisioning (опционально)
  type: thin
  thinPool: topolvm-thin-pool
```

```bash
kubectl apply -f storage-class-lvm.yaml
```

### Шаг 3: Создание PVC и пода

```yaml
# pvc-and-pod.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: topolvm-provisioner
  resources:
    requests:
      storage: 50Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
spec:
  containers:
    - name: app
      image: nginx:latest
      volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: data-pvc
```

```bash
kubectl apply -f pvc-and-pod.yaml

# Проверка: LV создан в topolvm-vg
sudo lvs topolvm-vg
# → pvc-xxxx  -wi-a-----  50.00g

# Проверка: под работает
kubectl get pod test-pod -o wide
# → NODE: worker-01 (где есть topolvm-vg)
```

### Шаг 4: Snapshot через CSI

```yaml
# volume-snapshot.yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: data-snapshot
spec:
  volumeSnapshotClassName: topolvm-snapshot-class
  source:
    persistentVolumeClaimName: data-pvc
```

```bash
# Создание snapshot class
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: topolvm-snapshot-class
driver: topolvm.io
deletionPolicy: Delete
EOF

# Создание снимка
kubectl apply -f volume-snapshot.yaml

# Проверка: LVM snapshot создан
sudo lvs -a -o lv_name,lv_attr,lv_size,snap_percent
# → pvc-xxxx-snap  Swi-a-----  50.00g  0.01
```

### Шаг 5: Безопасное удаление

```bash
# Удаление пода и PVC
kubectl delete pod test-pod
kubectl delete pvc data-pvc

# LV автоматически удаляется (reclaimPolicy: Delete)
sudo lvs topolvm-vg
# → (пусто)
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
|:---|:---|:---|
| Pod в��态 Pending | Нет подходящего узла с VG | Проверить `kubectl describe pod`, убедиться что на узле есть `topolvm-vg` |
| PVC в Pending | StorageClass не найден | `kubectl get sc`, проверить provisioner name |
| LV не создаётся | VG заполнена или нет PV | `vgs`, `vgextend topolvm-vg /dev/new-disk` |
| Snapshot не создаётся | Thin pool не настроен | Проверить `lvs -a -o +devices` в topolvm-vg |

### См. также
- **[LVM — Thin Provisioning](../thin-provisioning.md)** — архитектура thin pool.
- **[LVM — Снимки](../snapshots.md)** — COW-механизмы.
- **[LVM — Управление](../management_operations.md)** — мониторинг и метрики.
