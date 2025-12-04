# Установка и настройка драйвера Ceph CSI для RBD

В данном руководстве описывается процесс установки и настройки драйвера [Ceph CSI](https://github.com/ceph/ceph-csi) для работы с блочными устройствами **RBD (RADOS Block Device)** в Kubernetes. Для общего понимания архитектуры Ceph и концепции RBD, пожалуйста, ознакомьтесь с [Обзором Ceph](ceph_overview.md).

Процесс включает в себя подготовку кластера Ceph, установку драйвера через Helm, создание необходимых учетных данных и `StorageClass`, а также проверку создания и динамического расширения томов (`PersistentVolume`).

## Шаг 1: Подготовка кластера Ceph

Предполагается, что у вас уже есть работающий кластер Ceph.

### 1.1. Создание пула для RBD

Сначала необходимо создать в Ceph пул, где будут храниться образы блочных устройств.

```bash
ceph osd pool create <pool_name> <pg_num>
# Пример:
ceph osd pool create kube 32
```

### 1.2. Активация приложения RBD для пула

Сообщаем Ceph, что данный пул будет использоваться для хранения RBD-образов.

```bash
ceph osd pool application enable <pool_name> rbd
# Пример:
ceph osd pool application enable kube rbd
```

---

## Шаг 2: Установка драйвера Ceph CSI через Helm

Для установки CSI-драйвера используется Helm. Более подробную информацию о Container Storage Interface (CSI) можно найти в [Обзор Container Storage Interface (CSI)](../CSI/csi_overview.md).

### 2.1. Добавление Helm-репозитория

Если репозиторий `ceph-csi` еще не добавлен, сделайте это:

```bash
helm repo add ceph-csi https://ceph.github.io/csi-charts
helm repo update
```

### 2.2. Подготовка файла с настройками (`values.yaml`)

Выгрузим стандартные настройки чарта в файл для дальнейшей модификации.

```bash
helm inspect values ceph-csi/ceph-csi-rbd > ceph-rbd-values.yaml
```

Далее, отредактируйте файл `ceph-rbd-values.yaml`. Ключевые параметры для настройки:

*   `csiConfig`: Здесь указывается информация для подключения к вашему кластеру Ceph.
*   `provisioner.podSecurityPolicy.enabled`: Включение PodSecurityPolicy для provisioner.
*   `nodeplugin.podSecurityPolicy.enabled`: Включение PodSecurityPolicy для nodeplugin.

**Пример конфигурации `csiConfig`:**

Чтобы найти `clusterID` и адреса мониторов, выполните на узле Ceph следующие команды:

```bash
# Получение Cluster ID
ceph fsid

# Получение адресов мониторов
ceph mon dump
```

После этого внесите данные в `ceph-rbd-values.yaml`:

```yaml
csiConfig:
  - clusterID: "<ваш-cluster-id>" # <-- ID вашего кластера Ceph
    monitors:
      - "192.168.1.5:6789" # <-- IP-адреса ваших мониторов
      - "192.168.1.6:6789"
      - "192.168.1.7:6789"

# Убедитесь, что пустой список csiConfig ниже закомментирован или удален
# - clusterID: ""
#   monitors: []

# Включение PodSecurityPolicy (если необходимо в вашем кластере)
provisioner:
  replicaCount: 1 # Для тестового кластера достаточно одной реплики
  podSecurityPolicy:
    enabled: true

nodeplugin:
  podSecurityPolicy:
    enabled: true
```

### 2.3. Установка чарта

Теперь установим Helm-чарт с нашими параметрами.

```bash
helm upgrade --install ceph-csi-rbd ceph-csi/ceph-csi-rbd \
  --namespace ceph-csi-rbd \
  --create-namespace \
  -f ceph-rbd-values.yaml
```

---

## Шаг 3: Создание пользователя и секрета Kubernetes

CSI-драйверу нужен пользователь в Ceph для управления RBD-образами.

### 3.1. Создание пользователя в Ceph

Создадим пользователя `csi-rbd-user` с правами на работу в пуле `kube`.

```bash
ceph auth get-or-create client.csi-rbd-user mon 'profile rbd' osd 'profile rbd pool=kube'
```

Эта команда вернет ключ пользователя. **Сохраните его, он понадобится на следующем шаге.**

### 3.2. Создание секрета Kubernetes

Создайте манифест `secret.yaml` для хранения учетных данных.

```yaml
# secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: csi-rbd-secret
  namespace: default # Пространство имен, где будут создаваться PVC
stringData:
  userID: csi-rbd-user
  userKey: "<ключ-пользователя-из-предыдущей-команды>"
```

Примените манифест:

```bash
kubectl apply -f secret.yaml
```

---

## Шаг 4: Создание StorageClass

`StorageClass` определяет, какой provisioner использовать для динамического создания `PersistentVolume`. Подробнее о `PersistentVolumes` и `PersistentVolumeClaims` можно узнать в [PersistentVolumes и PersistentVolumeClaims](../../Base/pv_and_pvc.md).

Создайте манифест `storageclass.yaml`:

```yaml
# storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-sc
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: "<ваш-cluster-id>" # Тот же ID, что и в values.yaml
  pool: "kube" # Пул, созданный на шаге 1
  imageFeatures: "layering" # Необходимый параметр для CSI
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

Примените манифест:

```bash
kubectl apply -f storageclass.yaml
```

---

## Шаг 5: Создание и проверка PersistentVolumeClaim (PVC)

### 5.1. Создание PVC

Создадим PVC, который запросит 1Gi дискового пространства.

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

Примените манифест:

```bash
kubectl apply -f pvc.yaml
```

### 5.2. Проверка

Убедитесь, что PVC перешел в статус `Bound`.

```bash
kubectl get pvc rbd-pvc
# NAME      STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# rbd-pvc   Bound    pvc-d8a7b5a5-c1b1-4e3e-8a1c-3e7c6b2a1b9e   1Gi        RWO            ceph-rbd-sc    30s
```

Проверьте, что в Ceph был создан соответствующий RBD-образ:

```bash
rbd ls -p kube
# csi-vol-d8a7b5a5-c1b1-4e3e-8a1c-3e7c6b2a1b9e

rbd info kube/csi-vol-d8a7b5a5-c1b1-4e3e-8a1c-3e7c6b2a1b9e
# ...
# size 1 GiB
# ...
```

---

## Шаг 6: Проверка расширения тома (Volume Expansion)

### 6.1. Изменение размера PVC

Отредактируйте манифест `pvc.yaml`, увеличив размер до `2Gi`.

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
      storage: 2Gi # <-- Измененный размер
  storageClassName: ceph-rbd-sc
```

Примените изменения:

```bash
kubectl apply -f pvc.yaml
```

### 6.2. Механизм расширения

Сразу после применения `kubectl get pv` покажет, что `PersistentVolume` уже имеет новый размер `2Gi`, но `kubectl get pvc` все еще будет показывать старый размер `1Gi`.

Это происходит потому, что CSI-драйвер сначала расширяет физический образ в Ceph, а затем должен расширить файловую систему на этом образе. **Расширение файловой системы возможно только тогда, когда том подключен к какому-либо поду.**

Чтобы завершить процесс, создайте под, использующий этот PVC.

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
```

После запуска пода драйвер смонтирует том и выполнит расширение файловой системы. Проверка PVC снова покажет корректный, увеличенный размер `2Gi`.

```bash
kubectl get pvc rbd-pvc
# NAME      STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# rbd-pvc   Bound    pvc-d8a7b5a5-c1b1-4e3e-8a1c-3e7c6b2a1b9e   2Gi        RWO            ceph-rbd-sc    5m
```
