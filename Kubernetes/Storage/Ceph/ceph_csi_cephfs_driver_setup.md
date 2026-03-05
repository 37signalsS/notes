# Установка драйвера CSI для CephFS

## Определения

**CephFS CSI Driver** — компонент для интеграции CephFS с Kubernetes, позволяющий управлять томами через стандартный интерфейс CSI.

**StorageClass** — ресурс Kubernetes, определяющий параметры динамического выделения хранилища.

**PersistentVolumeClaim (PVC)** — запрос пользователя на хранилище определённого размера и класса.

---

## Базовые концепции

### Архитектура Ceph CSI

Драйвер состоит из двух компонентов:

| Компонент | Назначение | Режим работы |
|-----------|------------|--------------|
| **Provisioner** | Создание/удаление томов, снапшотов, расширение | Deployment (1+ реплика) |
| **Node Plugin** | Монтирование томов к подам | DaemonSet (на каждом узле) |

### Требования

| Компонент | Требование |
|-----------|------------|
| **Kubernetes** | 1.21+ (PSP удалены в 1.25+, используется Pod Security Admission) |
| **Ceph** | Reef (18.x) или Squid (19.x) |
| **Ядро Linux** | 5.4+ с поддержкой Ceph |
| **Helm** | 3.x |

### Конфигурация подключения

Для работы драйвера требуются:

1. **Cluster ID** — уникальный идентификатор кластера Ceph (`ceph fsid`)
2. **Monitors** — адреса мониторов (формат: `IP:6789`)
3. **Пользователь Ceph** — отдельная учётная запись с ограниченными правами
4. **Secret** — Kubernetes Secret с учётными данными

> **Важно:** Модуль ядра CephFS не поддерживает протокол v2. Указывайте только адреса с портом 6789.

---

## Практические сценарии

### 1. Подготовка Helm Chart

```bash
# Добавляем репозиторий
helm repo add ceph-csi https://ceph.github.io/csi-charts
helm repo update

# Получаем значения по умолчанию
helm show values ceph-csi/ceph-csi-cephfs > values.yaml
```

### 2. Настройка values.yaml

#### 2.1. Получение Cluster ID и мониторов

```bash
# Cluster ID
ceph fsid

# Список мониторов
ceph mon dump
```

#### 2.2. Редактирование values.yaml

```yaml
csiConfig:
  - clusterID: "a1b2c3d4-..."  # Вывод ceph fsid
    monitors:
      - "172.16.0.5:6789"
      - "172.16.0.6:6789"
      - "172.16.0.7:6789"

# Настройка provisioner
provisioner:
  replicaCount: 1  # Для HA используйте 2+
  serviceAccount:
    create: true

# Настройка nodeplugin
nodeplugin:
  liveness:
    containerPort: 9091  # Измените если 9080 занят

# Pod Security (для Kubernetes 1.25+)
security:
  podSecurityPolicy:
    enabled: false  # PSP удалены в K8s 1.25+
  podSecurityContext:
    enabled: true
```

### 3. Установка драйвера

```bash
helm upgrade --install csi-cephfs-driver ceph-csi/ceph-csi-cephfs \
  --values values.yaml \
  --namespace ceph-csi-cephfs \
  --create-namespace
```

Проверка статуса:

```bash
kubectl get pods -n ceph-csi-cephfs -w
```

### 4. Создание пользователя Ceph

```bash
ceph auth get-or-create client.csi-cephfs-user \
  mon 'allow r' \
  mgr 'allow rw' \
  mds 'allow rw, allow rw snapshot, allow r quota' \
  osd 'allow rw pool=cephfs-data, allow rw pool=cephfs-metadata'
```

Сохраните выведенный ключ.

### 5. Создание Kubernetes Secret

```yaml
# secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: csi-cephfs-secret
  namespace: ceph-csi-cephfs
type: Opaque
stringData:
  userID: csi-cephfs-user
  userKey: "AQB...ключ_из_предыдущей_команды"
```

```bash
kubectl apply -f secret.yaml
```

### 6. Создание StorageClass

```yaml
# storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: csi-cephfs-sc
provisioner: cephfs.csi.ceph.com
parameters:
  clusterID: "a1b2c3d4-..."
  fsName: "cephfs"
  pool: "cephfs-data"
  csi.storage.k8s.io/provisioner-secret-name: csi-cephfs-secret
  csi.storage.k8s.io/provisioner-secret-namespace: ceph-csi-cephfs
  csi.storage.k8s.io/node-stage-secret-name: csi-cephfs-secret
  csi.storage.k8s.io/node-stage-secret-namespace: ceph-csi-cephfs
  csi.storage.k8s.io/controller-expand-secret-name: csi-cephfs-secret
  csi.storage.k8s.io/controller-expand-secret-namespace: ceph-csi-cephfs
reclaimPolicy: Delete
allowVolumeExpansion: true
mountOptions:
  - noatime
```

```bash
kubectl apply -f storageclass.yaml
```

### 7. Тестирование: создание PVC

```yaml
# pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: csi-cephfs-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 5Gi
  storageClassName: csi-cephfs-sc
```

```bash
kubectl apply -f pvc.yaml
kubectl get pvc csi-cephfs-pvc
```

Ожидаемый статус: `Bound`.

### 8. Расширение PVC

CephFS поддерживает динамическое расширение томов:

```yaml
# Изменяем размер в pvc.yaml
spec:
  resources:
    requests:
      storage: 7Gi  # Увеличиваем с 5Gi до 7Gi
```

```bash
kubectl apply -f pvc.yaml
kubectl get pvc,pv
```

> **Примечание:** Для CephFS расширение происходит через обновление квоты на каталог. Перезапуск пода не требуется.

---

## Дополнительная информация

### Проверка на стороне Ceph

#### Монтирование CephFS для отладки

```bash
# Создание точки монтирования
mkdir /mnt/cephfs

# Файл с секретом администратора
echo "<admin-key>" > /etc/ceph/admin.secret
chmod 600 /etc/ceph/admin.secret

# Запись в /etc/fstab
echo "<mon-ip>:6789:/ /mnt/cephfs ceph name=admin,secretfile=/etc/ceph/admin.secret,_netdev 0 0" >> /etc/fstab

# Монтирование
mount -a
```

#### Проверка квот

```bash
# Установка утилиты для работы с расширенными атрибутами
apt-get install -y attr

# Проверка квоты
getfattr -n ceph.quota.max_bytes /mnt/cephfs/volumes/csi/csi-vol-<id>/
```

### Связанные темы

- **[Ceph RBD](./ceph_csi_rbd_driver_setup.md)** — блочное хранилище (RWO)
- **[Ceph Overview](./ceph_overview.md)** — архитектура Ceph
- **[CSI Overview](../CSI/csi_overview.md)** — стандарт CSI

### Ресурсы

- [Официальный репозиторий Ceph CSI](https://github.com/ceph/ceph-csi)
- [Документация CephFS](https://docs.ceph.com/en/latest/cephfs/)
