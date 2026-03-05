# Установка и настройка драйвера Ceph CSI для RBD

## Определения

**Ceph CSI (Container Storage Interface)** — стандартный интерфейс для интеграции систем хранения с Kubernetes. Драйвер Ceph CSI позволяет использовать блочные устройства RBD как постоянные тома.

**RBD (RADOS Block Device)** — блочное устройство Ceph, доступное для монтирования к ВМ или контейнерам.

**StorageClass** — объект Kubernetes, описывающий классы хранения для динамического выделения PV.

**PersistentVolumeClaim (PVC)** — запрос на хранилище, удовлетворяемый PersistentVolume.

---

## Базовые концепции

### Режимы доступа RBD

| Режим | Описание | Сценарий |
|-------|----------|----------|
| **ReadWriteOnce (RWO)** | Запись одним узлом | Базы данных, stateful-приложения |
| **ReadOnlyMany (ROX)** | Чтение множеством узлов | Статический контент |

> **Важно:** RBD не поддерживает ReadWriteMany (RWX). Для RWX используйте [CephFS](./ceph_csi_cephfs_driver_setup.md).

### Архитектура интеграции

```
Pod → PVC → PV (RBD) → Ceph CSI → RBD Image → Ceph Pool
```

### Требования

| Компонент | Требование |
|-----------|------------|
| **Kubernetes** | 1.21+ |
| **Ceph** | Reef (18.x) или Squid (19.x) |
| **Helm** | 3.x |
| **Ядро Linux** | Модуль `rbd` |

### Ключевые параметры RBD

| Параметр | Описание | Значение |
|----------|----------|----------|
| `imageFeatures` | Функции RBD | `layering` (обязательно) |
| `pool` | Пул Ceph для образов | — |
| `clusterID` | ID кластера Ceph | — |
| `reclaimPolicy` | Удаление PV при удалении PVC | `Delete` или `Retain` |

---

## Практические сценарии

### Шаг 1: Подготовка кластера Ceph

#### 1.1. Создание пула для RBD

```bash
# Создание пула (32 PG - рассчитайте по формуле)
ceph osd pool create kube 32

# Активация приложения RBD
ceph osd pool application enable kube rbd
```

> **Примечание:** Количество PG рассчитывается по формуле в [ceph_placement_groups.md](ceph_placement_groups.md).

### Шаг 2: Установка драйвера через Helm

#### 2.1. Добавление репозитория

```bash
helm repo add ceph-csi https://ceph.github.io/csi-charts
helm repo update
```

#### 2.2. Подготовка values.yaml

```bash
helm inspect values ceph-csi/ceph-csi-rbd > ceph-rbd-values.yaml
```

#### 2.3. Редактирование конфигурации

Получите Cluster ID и адреса мониторов:

```bash
ceph fsid        # Cluster ID
ceph mon dump    # Monitors
```

```yaml
# ceph-rbd-values.yaml
csiConfig:
  - clusterID: "a1b2c3d4-..."  # Вывод ceph fsid
    monitors:
      - "172.16.0.5:6789"
      - "172.16.0.6:6789"
      - "172.16.0.7:6789"

provisioner:
  replicaCount: 1
  serviceAccount:
    create: true

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

#### 2.4. Установка чарта

```bash
helm upgrade --install ceph-csi-rbd ceph-csi/ceph-csi-rbd \
  --namespace ceph-csi-rbd \
  --create-namespace \
  -f ceph-rbd-values.yaml
```

### Шаг 3: Создание пользователя Ceph и Secret

#### 3.1. Создание пользователя в Ceph

```bash
ceph auth get-or-create client.csi-rbd-user \
  mon 'profile rbd' \
  osd 'profile rbd pool=kube'
```

Сохраните выведенный ключ.

#### 3.2. Создание Kubernetes Secret

```yaml
# secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: csi-rbd-secret
  namespace: default
type: Opaque
stringData:
  userID: csi-rbd-user
  userKey: "AQB...ключ_из_предыдущей_команды"
```

```bash
kubectl apply -f secret.yaml
```

### Шаг 4: Создание StorageClass

```yaml
# storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-sc
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: "a1b2c3d4-..."
  pool: "kube"
  imageFeatures: "layering"
  csi.storage.k8s.io/provisioner-secret-name: "csi-rbd-secret"
  csi.storage.k8s.io/provisioner-secret-namespace: "default"
  csi.storage.k8s.io/controller-expand-secret-name: "csi-rbd-secret"
  csi.storage.k8s.io/controller-expand-secret-namespace: "default"
  csi.storage.k8s.io/node-stage-secret-name: "csi-rbd-secret"
  csi.storage.k8s.io/node-stage-secret-namespace: "default"
reclaimPolicy: Delete
allowVolumeExpansion: true
mountOptions:
  - discard
```

```bash
kubectl apply -f storageclass.yaml
```

### Шаг 5: Создание и проверка PVC

#### 5.1. Создание PVC

```yaml
# pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: rbd-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: ceph-rbd-sc
```

```bash
kubectl apply -f pvc.yaml
kubectl get pvc rbd-pvc
```

#### 5.2. Проверка на стороне Ceph

```bash
# Список образов
rbd ls -p kube

# Информация об образе
rbd info kube/csi-vol-<id>
```

### Шаг 6: Расширение тома (Volume Expansion)

#### 6.1. Изменение размера PVC

```yaml
# pvc.yaml
spec:
  resources:
    requests:
      storage: 2Gi  # Увеличиваем с 1Gi до 2Gi
```

```bash
kubectl apply -f pvc.yaml
```

#### 6.2. Механизм расширения

Расширение файловой системы завершается при подключении тома к поду:

```yaml
# pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
spec:
  containers:
    - name: app
      image: busybox
      command: ["/bin/sh", "-c", "sleep 3600"]
      volumeMounts:
        - name: my-volume
          mountPath: /data
  volumes:
    - name: my-volume
      persistentVolumeClaim:
        claimName: rbd-pvc
```

```bash
kubectl apply -f pod.yaml
kubectl get pvc rbd-pvc  # Должен показать 2Gi
```

---

## Дополнительная информация

### Рекомендации по `reclaimPolicy`

| Политика | Описание | Когда использовать |
|----------|----------|-------------------|
| **`Delete`** | PV и RBD-образ удаляются при удалении PVC | Dev/Test |
| **`Retain`** | PV и RBD-образ сохраняются | Production, важные данные |

> **Рекомендация:** Для production используйте `Retain` и вручную контролируйте удаление данных.

### Опции монтирования

| Опция | Описание |
|-------|----------|
| `discard` | Информирование Ceph о неиспользуемых блоках (trim) |

### Связанные темы

- **[Ceph CephFS](./ceph_csi_cephfs_driver_setup.md)** — файловая система (RWX)
- **[Ceph Overview](./ceph_overview.md)** — архитектура Ceph
- **[CSI Overview](../CSI/csi_overview.md)** — стандарт CSI

### Ресурсы

- [Официальный репозиторий Ceph CSI](https://github.com/ceph/ceph-csi)
- [Документация RBD](https://docs.ceph.com/en/latest/rbd/)
