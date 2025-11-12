# Установка драйвера CSI для CephFS

В этой инструкции описывается процесс установки и настройки драйвера CSI для подключения CephFS в кластере Kubernetes.

## 1. Подготовка и настройка Helm Chart

Переходим в каталог с манифестами. Репозиторий с чартами Ceph-CSI уже должен быть подключен.

### 1.1. Получение и настройка переменных чарта

Получаем настройки чарта `ceph-csi-cephfs`:
```bash
helm show values ceph-csi/ceph-csi-cephfs > values.yaml
```

Редактируем файл `values.yaml`. Необходимо указать `clusterID` и список мониторов Ceph.

### 1.2. Получение Cluster ID

На одном из узлов Ceph-кластера выполняем:
```bash
ceph fsid
```
Копируем полученный ID и вставляем в `values.yaml`.

### 1.3. Получение списка мониторов

На одном из узлов Ceph-кластера получаем список мониторов:
```bash
ceph mon dump
```
Нам нужны IP-адреса и порты. Модуль ядра CephFS не умеет работать с протоколом v2, поэтому указываем только адрес и порт.

Пример для `values.yaml`:
```yaml
csiConfig:
  - clusterID: "<your-cluster-id>"
    monitors:
      - "172.16.0.5:6789"
      - "172.16.0.6:6789"
      - "172.16.0.7:6789"
```
**Важно:** Закомментируйте или удалите пустой список `csiConfig` ниже в файле, чтобы избежать переопределения.

### 1.4. Настройка портов Node Plugin

Плагины узлов (`nodeplugin`) работают в режиме `hostNetwork: true`, что может привести к конфликтам портов. Если порт `9080` (по-умолчанию для liveness-проб) занят (например, `kube-proxy` в кластере, развернутом через Kubespray), его необходимо изменить.

В `values.yaml` изменяем порт:
```yaml
# For nodeplugin...
liveness:
  # ...
  containerPort: 9091
```

### 1.5. Настройка PSP и реплик

Включаем создание Pod Security Policies (PSP) и устанавливаем количество реплик для provisioner'а.

```yaml
# In values.yaml
csiAddons:
  # ...
  enabled: true # If you need PSPs

# For provisioner...
replicaCount: 1
# ...
# Also enable PSP for provisioner if needed
```

## 2. Установка драйвера

После сохранения изменений в `values.yaml`, устанавливаем драйвер с помощью Helm:

```bash
helm upgrade --install csi-cephfs-driver ceph-csi/ceph-csi-cephfs \
  --values values.yaml \
  --namespace ceph-csi-cephfs \
  --create-namespace
```

Проверяем статус подов:
```bash
kubectl get pods -n ceph-csi-cephfs -w
```

## 3. Создание пользователя и StorageClass

### 3.1. Создание пользователя CephFS

Для безопасности создадим отдельного пользователя для CSI вместо использования ключа администратора.

На узле Ceph выполняем:
```bash
ceph auth get-or-create client.csi-cephfs-user mon 'allow r' mgr 'allow rw' mds 'allow rw, allow rw snapshot, allow r quota' osd 'allow rw pool=cephfs-data, allow rw pool=cephfs-metadata'
```
Копируем полученный ключ.

### 3.2. Создание секрета Kubernetes

Создаем манифест для секрета, например `secret.yaml`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: csi-cephfs-secret
  namespace: ceph-csi-cephfs
stringData:
  userID: csi-cephfs-user
  userKey: "<your-user-key>"
```
**Примечание:** В старых версиях драйвера поля могли называться `adminID` и `adminKey`.

Применяем манифест:
```bash
kubectl apply -f secret.yaml
```

### 3.3. Создание StorageClass

Создаем манифест для StorageClass, например `storageclass.yaml`:
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: csi-cephfs-sc
provisioner: cephfs.csi.ceph.com
parameters:
  clusterID: "<your-cluster-id>"
  fsName: "cephfs" # Имя файловой системы по умолчанию
  pool: "cephfs-data" # опционально, если нужно указать data pool
  csi.storage.k8s.io/provisioner-secret-name: csi-cephfs-secret
  csi.storage.k8s.io/provisioner-secret-namespace: ceph-csi-cephfs
  csi.storage.k8s.io/node-stage-secret-name: csi-cephfs-secret
  csi.storage.k8s.io/node-stage-secret-namespace: ceph-csi-cephfs
reclaimPolicy: Delete
allowVolumeExpansion: true
mountOptions:
  - noatime
```
Заполняем `clusterID` и применяем манифест:
```bash
kubectl apply -f storageclass.yaml
```

Проверяем, что StorageClass создан:
```bash
kubectl get sc
```

## 4. Тестирование: создание и расширение PVC

### 4.1. Создание PVC

Создаем манифест `pvc.yaml`:
```yaml
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
Применяем:
```bash
kubectl apply -f pvc.yaml
```
Проверяем статус PVC:
```bash
kubectl get pvc csi-cephfs-pvc
# Ожидаемый статус: Bound
```

### 4.2. Расширение PVC

Редактируем манифест `pvc.yaml`, изменяя размер:
```yaml
# ...
spec:
  # ...
  resources:
    requests:
      storage: 7Gi
# ...
```
Применяем изменения:
```bash
kubectl apply -f pvc.yaml
```
Проверяем, что размер PVC и связанного с ним PV изменился:
```bash
kubectl get pvc,pv
```
Для CephFS изменение размера тома происходит через обновление квоты на каталог, поэтому нет необходимости вручную изменять размер файловой системы внутри пода.

## 5. Проверка на стороне Ceph

### 5.1. Монтирование CephFS на узел (для отладки)

Чтобы посмотреть, что создал драйвер, можно смонтировать CephFS непосредственно на один из узлов.

1.  Создаем точку монтирования: `mkdir /mnt/cephfs`
2.  Создаем файл с секретом: `echo "<your-admin-key>" > /etc/ceph/admin.secret`
3.  Добавляем запись в `/etc/fstab`:
    ```
    <mon_ip>:6789:/ /mnt/cephfs ceph name=admin,secretfile=/etc/ceph/admin.secret,netdev 0 0
    ```
    **Важно:** Опция `netdev` предотвращает зависание системы при перезагрузке.
4.  Монтируем: `mount -a`

### 5.2. Проверка квоты

Переходим в каталог, где CSI создает тома, и проверяем расширенные атрибуты для просмотра квоты.

Устанавливаем утилиту:
```bash
# На Debian/Ubuntu
apt-get install -y attr
```

Проверяем квоту:
```bash
getfattr -n ceph.quota.max_bytes /mnt/cephfs/volumes/csi/csi-vol-<id>/
```
Вывод должен соответствовать размеру, указанному в PVC.
