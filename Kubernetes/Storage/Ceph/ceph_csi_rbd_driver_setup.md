# Установка и настройка драйвера Ceph CSI для RBD

## Определения

*   **Ceph CSI (Container Storage Interface)**: Стандартный интерфейс для интеграции различных систем хранения данных с Kubernetes. Драйвер Ceph CSI позволяет Kubernetes использовать блочные устройства Ceph (RBD) в качестве постоянных томов.
*   **RBD (RADOS Block Device)**: Блочное устройство, предоставляемое Ceph, которое может быть примонтировано к виртуальным машинам или контейнерам.
*   **StorageClass**: Объект Kubernetes, который описывает "классы" хранения, предлагаемые кластером. Используется для динамического выделения PersistentVolume.
*   **PersistentVolume (PV)**: Объект API в Kubernetes, представляющий собой часть хранилища, абстрагированную от базовой реализации хранения.
*   **PersistentVolumeClaim (PVC)**: Запрос пользователя на хранилище, который может быть удовлетворен PersistentVolume.

## Основные концепции

Интеграция Ceph RBD с Kubernetes через CSI драйвер включает следующие ключевые шаги и компоненты:

1.  **Подготовка Ceph кластера**: Создание специализированного пула для RBD-образов и активация приложения RBD для этого пула.
2.  **Развертывание CSI драйвера**: Установка драйвера Ceph CSI в кластере Kubernetes, обычно с использованием Helm, который обеспечивает взаимодействие между Kubernetes и Ceph.
3.  **Авторизация**: Создание пользователя Ceph с необходимыми правами и хранение его ключа в Kubernetes Secret для аутентификации CSI драйвера в Ceph.
4.  **Динамическое выделение хранилища**: Использование StorageClass для определения параметров хранения, таких как пул Ceph и функции RBD, позволяя Kubernetes динамически создавать PersistentVolume из Ceph по запросу PersistentVolumeClaim.
5.  **Расширение томов**: Возможность динамического увеличения размера PersistentVolume, требующая расширения как на стороне Ceph, так и на файловой системе внутри пода.

Более подробную информацию о Container Storage Interface (CSI) можно найти в [Обзор Container Storage Interface (CSI)](../CSI/csi_overview.md). Для общего понимания архитектуры Ceph и концепции RBD, пожалуйста, ознакомьтесь с [Обзором Ceph](ceph_overview.md), а о PersistentVolumes и PersistentVolumeClaims — в [PersistentVolumes и PersistentVolumeClaims](../../Base/pv_and_pvc.md).

## Практические сценарии

Данный раздел описывает пошаговую установку и настройку драйвера Ceph CSI для работы с RBD в Kubernetes.

### Шаг 1: Подготовка кластера Ceph

Предполагается, что у вас уже есть работающий кластер Ceph.

#### 1.1. Создание пула для RBD

Создайте в Ceph пул, где будут храниться образы блочных устройств:

```bash
ceph osd pool create <pool_name> <pg_num>
# Пример:
ceph osd pool create kube 32
```

#### 1.2. Активация приложения RBD для пула

Сообщите Ceph, что данный пул будет использоваться для хранения RBD-образов:

```bash
ceph osd pool application enable <pool_name> rbd
# Пример:
ceph osd pool application enable kube rbd
```

### Шаг 2: Установка драйвера Ceph CSI через Helm

#### 2.1. Добавление Helm-репозитория

Если репозиторий `ceph-csi` еще не добавлен, выполните:

```bash
helm repo add ceph-csi https://ceph.github.io/csi-charts
helm repo update
```

#### 2.2. Подготовка файла с настройками (`values.yaml`)

Выгрузите стандартные настройки чарта в файл для дальнейшей модификации:

```bash
helm inspect values ceph-csi/ceph-csi-rbd > ceph-rbd-values.yaml
```

Отредактируйте файл `ceph-rbd-values.yaml`. Укажите `clusterID` и адреса мониторов, полученные с помощью команд `ceph fsid` и `ceph mon dump` на узле Ceph.

**Пример конфигурации `csiConfig` и PodSecurityPolicy:**

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

#### 2.3. Установка чарта

Установите Helm-чарт с вашими параметрами:

```bash
helm upgrade --install ceph-csi-rbd ceph-csi/ceph-csi-rbd \
  --namespace ceph-csi-rbd \
  --create-namespace \
  -f ceph-rbd-values.yaml
```

### Шаг 3: Создание пользователя Ceph и секрета Kubernetes

Драйверу Ceph CSI требуется пользователь Ceph для управления RBD-образами.

#### 3.1. Создание пользователя в Ceph

Создайте пользователя `csi-rbd-user` с необходимыми правами:

```bash
ceph auth get-or-create client.csi-rbd-user mon 'profile rbd' osd 'profile rbd pool=kube'
```

**Важно:** Сохраните ключ пользователя, который будет выведен этой командой, он понадобится на следующем шаге.

#### 3.2. Создание секрета Kubernetes

Создайте манифест `secret.yaml` для хранения учетных данных:

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

### Шаг 4: Создание StorageClass

`StorageClass` определяет provisioner и параметры для динамического создания `PersistentVolume`.

Создайте манифест `storageclass.yaml`, используя тот же `clusterID` и имя пула, что и в предыдущих шагах:

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

### Шаг 5: Создание и проверка PersistentVolumeClaim (PVC)

#### 5.1. Создание PVC

Создайте PVC для запроса дискового пространства:

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

#### 5.2. Проверка

Убедитесь, что PVC перешел в статус `Bound` и что в Ceph был создан соответствующий RBD-образ:

```bash
kubectl get pvc rbd-pvc
# Пример вывода:
# NAME      STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# rbd-pvc   Bound    pvc-d8a7b5a5-c1b1-4e3e-8a1c-3e7c6b2a1b9e   1Gi        RWO            ceph-rbd-sc    30s

rbd ls -p kube
# Пример вывода:
# csi-vol-d8a7b5a5-c1b1-4e3e-8a1c-3e7c6b2a1b9e

rbd info kube/csi-vol-d8a7b5a5-c1b1-4e3e-8a1c-3e7c6b2a1b9e
# Пример вывода:
# ...
# size 1 GiB
# ...
```

### Шаг 6: Проверка расширения тома (Volume Expansion)

#### 6.1. Изменение размера PVC

Отредактируйте манифест `pvc.yaml`, увеличив размер:

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

#### 6.2. Механизм расширения и проверка

После применения изменений `kubectl get pv` покажет обновленный размер, но `kubectl get pvc` может все еще показывать старый. Расширение файловой системы на томе завершится только при его подключении к поду.

Создайте под, использующий этот PVC, чтобы завершить процесс расширения:

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

После запуска пода драйвер смонтирует том и выполнит расширение файловой системы. Проверка PVC снова покажет корректный, увеличенный размер:

```bash
kubectl get pvc rbd-pvc
# Пример вывода:
# NAME      STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# rbd-pvc   Bound    pvc-d8a7b5a5-c1b1-4e3e-8a1c-3e7c6b2a1b9e   2Gi        RWO            ceph-rbd-sc    5m
```

## Дополнительная информация

### Рекомендации по `reclaimPolicy`

В данном руководстве `reclaimPolicy` установлен в `Delete`. Это означает, что при удалении `PersistentVolumeClaim` соответствующий `PersistentVolume` и базовый RBD-образ в Ceph также будут удалены. Для производственных сред рассмотрите возможность использования `Retain` для сохранения данных после удаления PVC.

### Опции монтирования

Опция `discard` в `mountOptions` позволяет Kubernetes информировать Ceph о неиспользуемых блоках, что способствует более эффективному управлению дисковым пространством, особенно при удалении данных.