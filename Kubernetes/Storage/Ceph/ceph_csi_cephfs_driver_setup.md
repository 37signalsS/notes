# Установка драйвера CSI для CephFS

## Определения

* **CephFS CSI Driver (Драйвер CSI для CephFS):** Компонент, позволяющий Kubernetes управлять томами хранения, предоставляемыми файловой системой CephFS.
* **Helm Chart (Чарты Helm):** Коллекция предварительно настроенных ресурсов Kubernetes, используемых для развертывания приложений.
* **Ceph Cluster ID (Идентификатор кластера Ceph):** Уникальный идентификатор для кластера хранения Ceph.
* **Ceph Monitors (Мониторы Ceph):** Компоненты в кластере Ceph, отвечающие за поддержание согласованной карты кластера.
* **Node Plugin (Плагин узла):** Часть драйвера CSI, которая работает на каждом узле Kubernetes для выполнения операций с томами.
* **Pod Security Policies (PSP) (Политики безопасности подов):** Ресурс Kubernetes, контролирующий чувствительные к безопасности аспекты спецификации подов (упоминается в документе, хотя PSP устарели).
* **StorageClass (Класс хранения):** Ресурс Kubernetes, который определяет параметры для динамически выделяемого хранилища.
* **PersistentVolumeClaim (PVC) (Заявка на постоянный том):** Запрос пользователя на хранилище в Kubernetes.

### Основные концепции

Драйвер Ceph CSI необходим для интеграции файловой системы CephFS с Kubernetes, позволяя подам использовать хранилище Ceph. Развертывание драйвера обычно осуществляется с помощью Helm-чартов, что упрощает управление конфигурацией. Файл `values.yaml` используется для настройки параметров Helm-чарта, таких как `clusterID` и список `monitors`, которые драйвер использует для подключения к кластеру Ceph.

Плагины узлов драйвера могут работать в режиме `hostNetwork: true`, что может привести к конфликтам портов (например, порт `9080` для проверок живучести). Для безопасности рекомендуется создавать отдельного пользователя Ceph для CSI, а его учетные данные хранить в Kubernetes Secret.

StorageClass определяет, как динамически выделяется хранилище, включая провизионер, `clusterID`, имя файловой системы (`fsName`), пул данных (`pool`) и секреты для доступа. PersistentVolumeClaim (PVC) — это запрос пользователя на определенный объем и характеристики хранилища. Для CephFS расширение томов осуществляется путем обновления квоты на каталог, а не путем изменения размера файловой системы внутри пода.

## Практические сценарии

### 1. Подготовка и настройка Helm Chart

Для установки драйвера Ceph CSI используются Helm-чарты. Подробнее о Container Storage Interface (CSI) можно узнать в [Обзор Container Storage Interface (CSI)](../CSI/csi_overview.md).

**1.1. Получение и настройка переменных чарта**

Получите настройки чарта `ceph-csi-cephfs` и сохраните их в `values.yaml`:

```bash
helm show values ceph-csi/ceph-csi-cephfs > values.yaml
```

Отредактируйте файл `values.yaml`, указав `clusterID` и список мониторов Ceph.

**1.2. Получение Cluster ID**

На одном из узлов Ceph-кластера выполните:

```bash
ceph fsid
```

Скопируйте полученный ID и вставьте в `values.yaml`.

**1.3. Получение списка мониторов**

На одном из узлов Ceph-кластера получите список мониторов:

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

**1.4. Настройка портов Node Plugin**

Плагины узлов (`nodeplugin`) работают в режиме `hostNetwork: true`, что может привести к конфликтам портов. Если порт `9080` (по умолчанию для liveness-проб) занят (например, `kube-proxy` в кластере, развернутом через Kubespray), его необходимо изменить.

В `values.yaml` измените порт:

```yaml
# For nodeplugin...
liveness:
  # ...
  containerPort: 9091
```

**1.5. Настройка PSP и реплик**

Включите создание Pod Security Policies (PSP) и установите количество реплик для provisioner'а.

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

### 2. Установка драйвера

После сохранения изменений в `values.yaml`, установите драйвер с помощью Helm:

```bash
helm upgrade --install csi-cephfs-driver ceph-csi/ceph-csi-cephfs \
  --values values.yaml \
  --namespace ceph-csi-cephfs \
  --create-namespace
```

Проверьте статус подов:

```bash
kubectl get pods -n ceph-csi-cephfs -w
```

### 3. Создание пользователя и StorageClass

**3.1. Создание пользователя CephFS**

Для безопасности создайте отдельного пользователя для CSI вместо использования ключа администратора.

На узле Ceph выполните:

```bash
ceph auth get-or-create client.csi-cephfs-user mon 'allow r'mgr 'allow rw' mds 'allow rw, allow rw snapshot, allow r quota' osd 'allow rw pool=cephfs-data, allow rw pool=cephfs-metadata'
```

Скопируйте полученный ключ.

**3.2. Создание секрета Kubernetes**

Создайте манифест для секрета, например `secret.yaml`:

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

Примените манифест:

```bash
kubectl apply -f secret.yaml
```

**3.3. Создание StorageClass**

Создайте манифест для StorageClass, например `storageclass.yaml`:

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

Заполните `clusterID` и примените манифест:

```bash
kubectl apply -f storageclass.yaml
```

Проверьте, что StorageClass создан:

```bash
kubectl get sc
```

### 4. Тестирование: создание и расширение PVC

Этот раздел демонстрирует создание и расширение PersistentVolumeClaim (PVC) для CephFS. Более подробно о PersistentVolumes и PersistentVolumeClaims можно узнать в [PersistentVolumes и PersistentVolumeClaims](../../Base/pv_and_pvc.md).

**4.1. Создание PVC**

Создайте манифест `pvc.yaml`:

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

Примените:

```bash
kubectl apply -f pvc.yaml
```

Проверьте статус PVC:

```bash
kubectl get pvc csi-cephfs-pvc
# Ожидаемый статус: Bound
```

**4.2. Расширение PVC**

Отредактируйте манифест `pvc.yaml`, изменив размер:

```yaml
# ...
spec:
  # ...
  resources:
    requests:
      storage: 7Gi
# ...
```

Примените изменения:

```bash
kubectl apply -f pvc.yaml
```

Проверьте, что размер PVC и связанного с ним PV изменился:

```bash
kubectl get pvc,pv
```

Для CephFS изменение размера тома происходит через обновление квоты на каталог, поэтому нет необходимости вручную изменять размер файловой системы внутри пода.

### 5. Проверка на стороне Ceph

**5.1. Монтирование CephFS на узел (для отладки)**

Чтобы посмотреть, что создал драйвер, можно смонтировать CephFS непосредственно на один из узлов.

1. Создайте точку монтирования: `mkdir /mnt/cephfs`
2. Создайте файл с секретом: `echo "<your-admin-key>" > /etc/ceph/admin.secret`
3. Добавьте запись в `/etc/fstab`:

    ```
    <mon_ip>:6789:/ /mnt/cephfs ceph name=admin,secretfile=/etc/ceph/admin.secret,netdev 0 0
    ```

    **Важно:** Опция `netdev` предотвращает зависание системы при перезагрузке.
4. Смонтируйте: `mount -a`

**5.2. Проверка квоты**

Перейдите в каталог, где CSI создает тома, и проверьте расширенные атрибуты для просмотра квоты.

Установите утилиту:

```bash
# На Debian/Ubuntu
apt-get install -y attr
```

Проверьте квоту:

```bash
getfattr -n ceph.quota.max_bytes /mnt/cephfs/volumes/csi/csi-vol-<id>/
```

Вывод должен соответствовать размеру, указанному в PVC.
