# NFS Server Provisioner (устаревший Helm-чарт)

## Определения

**NFS Server Provisioner (Helm-чарт)** — устаревший Helm-чарт `stable/nfs-server-provisioner` (версия 1.8.0+), разворачивающий монолитное приложение (StatefulSet) со встроенным NFS-сервером и provisioner для Kubernetes.

> **Статус:** Чарт **не поддерживается** и находится в архивном репозитории. Используйте только для тестовых и учебных сред.

---

## Базовые концепции

### Архитектура

В отличие от `nfs-subdir-external-provisioner`, который использует внешний NFS-сервер, этот чарт объединяет в одном поде:

- Встроенный NFS-сервер
- Provisioner для интеграции с Kubernetes

Хранилище использует `hostPath` volume на ноде, что создаёт критическую зависимость от конкретной ноды.

> **Подробнее:** [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md) — современный аналог с внешним NFS-сервером.

### Принцип работы

1. StatefulSet запускается на конкретной ноде (опционально через `nodeSelector`)
2. Provisioner создаёт StorageClass `nfs`
3. При создании PVC provisioner динамически выделяет хранилище из `hostPath` volume пода
4. Данные записываются на локальный диск ноды

---

## Практические сценарии

### Установка через Helm

#### Подготовка

**Шаг 1: Создание namespace**

```bash
kubectl create namespace nfs
# → namespace/nfs created
```

**Шаг 2: Добавление репозитория**

```bash
# Добавление репозитория (можно использовать кастомное имя)
helm repo add stable https://charts.helm.sh/stable
helm repo update
# → Hang tight while we grab the latest from your chart repositories...
```

**Шаг 3: Скачивание и распаковка чарта**

```bash
# Скачивание чарта
helm pull stable/nfs-server-provisioner --untar
# → Создаётся директория nfs-server-provisioner/

# Проверка структуры
ls nfs-server-provisioner/
# → Chart.yaml  values.yaml  templates/
```

**Шаг 4: Правка values.yaml**

Ключевые параметры для редактирования:

```yaml
# nfs-server-provisioner/values.yaml

# Включение персистентности
persistence:
  enabled: true
  size: 10Gi  # Размер должен соответствовать доступному месту на ноде

# StorageClass как default (опционально)
storageClass:
  defaultClass: true

# NodeSelector для привязки пода к конкретной ноде
nodeSelector:
  kubernetes.io/hostname: node2  # Указать целевую ноду
```

> **Важно:** Параметр `persistence.size` должен соответствовать реальному доступному месту на ноде. Проверить: `df -h`.

**Шаг 5: Создание PersistentVolume**

Перед установкой чарта необходимо создать PV, который будет использовать provisioner:

```yaml
# pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-pv
spec:
  capacity:
    storage: 10Gi  # Должно совпадать с persistence.size в values.yaml
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: /data/nfs  # Путь на ноде для хранения данных
```

```bash
kubectl apply -f pv.yaml
# → persistentvolume/nfs-pv created

# Проверка
kubectl get pv
# → NAME     CAPACITY   STATUS    RECLAIM POLICY
# → nfs-pv   10Gi       Available Retain
```

#### Установка чарта

```bash
# Установка с кастомным именем
helm install nfs-server stable/nfs-server-provisioner \
  --namespace nfs \
  -f nfs-server-provisioner/values.yaml
```

> **Примечание:** Для передачи сложных структур (nodeSelector) рекомендуется использовать модифицированный `values.yaml` через флаг `-f values.yaml`.

#### Проверка работоспособности

```bash
# Проверка пода (StatefulSet)
kubectl get pods -n nfs
# → NAME                    READY   STATUS    RESTARTS   AGE
# → nfs-server-provisioner-0   1/1     Running   0          30s

# Проверка StorageClass
kubectl get storageclass
# → NAME   PROVISIONER                          RECLAIMPOLICY   VOLUMEBINDINGMODE
# → nfs    cluster.local/nfs-server-provisioner   Delete          Immediate

# Просмотр логов
kubectl logs -n nfs nfs-server-provisioner-0
```

### Тестирование динамического выделения хранилища

#### Шаг 1: Создание PVC

```yaml
# test-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dynamic-volume-claim
  namespace: nfs
spec:
  storageClassName: nfs
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 100Mi
```

```bash
kubectl apply -f test-pvc.yaml
# → persistentvolumeclaim/dynamic-volume-claim created

# Проверка
kubectl get pvc -n nfs
# → NAME                    STATUS   VOLUME   CAPACITY   ACCESS MODES
# → dynamic-volume-claim    Bound    ...      100Mi      RWO
```

#### Шаг 2: Тестирование с nginx pod

Создаём под с монтированием PVC для проверки сохранения данных:

```yaml
# test-nginx.yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-test
  namespace: nfs
spec:
  containers:
    - name: nginx
      image: nginx:latest
      volumeMounts:
        - name: test-storage
          mountPath: /usr/share/nginx/html/test
  volumes:
    - name: test-storage
      persistentVolumeClaim:
        claimName: dynamic-volume-claim
```

```bash
# Создание пода
kubectl apply -f test-nginx.yaml
# → pod/nginx-test created

# Ожидание запуска
kubectl get pods -n nfs -w
# → nginx-test   0/1   ContainerCreating   0   5s
# → nginx-test   1/1   Running             0   25s
```

#### Шаг 3: Запись данных и проверка

```bash
# Вход в оболочку пода
kubectl exec -it -n nfs nginx-test -- bash

# Создание тестовых файлов
ls /usr/share/nginx/html/test
# → (пусто)

echo "Hello" > /usr/share/nginx/html/test/hello.yaml
cat /usr/share/nginx/html/test/hello.yaml
# → Hello

mkdir /usr/share/nginx/html/test2
echo "World" > /usr/share/nginx/html/test2/world.yaml

exit
```

#### Шаг 4: Проверка сохранения данных при пересоздании

```bash
# Удаление пода
kubectl delete pod nginx-test -n nfs
# → pod "nginx-test" deleted

# Пересоздание пода
kubectl apply -f test-nginx.yaml

# Ожидание запуска и проверка
kubectl exec -it -n nfs nginx-test -- bash

ls /usr/share/nginx/html/test/
# → hello.yaml

cat /usr/share/nginx/html/test/hello.yaml
# → Hello

# Данные сохранены — PVC работает корректно
```

### Необходимые пакеты

Для монтирования NFS-томов к подам требуется установка NFS-клиента на все worker-ноды кластера:

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install nfs-common

# CentOS/RHEL
sudo yum install nfs-utils
```

> **Важно:** Без пакета `nfs-common` (или `nfs-utils`) поды не смогут смонтировать NFS-том. При проблемах с монтированием проверьте наличие пакета: `dpkg -l | grep nfs-common` или `rpm -q nfs-utils`.

---

## Дополнительная информация

### Критические ограничения

| Ограничение | Описание |
|-------------|----------|
| **Локальный диск ноды** | Хранилище использует `hostPath` volume — локальный диск ноды, на которой запущен под |
| **Привязка к ноде** | При переезде пода на другую ноду данные остаются на предыдущей ноде (новая нода не имеет доступа к старым данным) |
| **Однонодовые кластеры** | Применимо только для minikube, microk8s, однонодовых кластеров или кластеров с жёсткой привязкой пода к ноде через `nodeSelector` |
| **Не для production** | Отсутствуют механизмы HA, миграции, репликации. При падении ноды данные недоступны |
| **Не поддерживается** | Репозиторий заархивирован, обновления не выпускаются |

### Когда использовать

- **Обучение:** Посмотреть, как работает динамическое выделение хранилища в Kubernetes
- **Тестирование:** Быстрая проверка работы PVC/PV без развёртывания внешнего NFS-сервера
- **Локальные среды:** Minikube, microk8s, kind
- **Тестовые кластеры с одной нодой:** Где можно гарантировать запуск пода на конкретной ноде

### Когда НЕ использовать

- **Production-кластеры:** Используйте [nfs-subdir-external-provisioner](./nfs-subdir-external-provisioner.md) или [Ceph CephFS](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md)
- **Многонодовые кластеры без nodeSelector:** Данные могут остаться на старой ноде при миграции пода
- **Важные данные:** Отсутствуют механизмы резервирования и репликации

Базовые концепции: [PersistentVolume и PVC](./pv_and_pvc.md). Современный аналог: [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md). Альтернатива для RWO: [Local Path Provisioner](./local-path-provisioner.md). Альтернатива для RWX с репликацией: [Ceph CephFS](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md).

Архивный репозиторий: [kubernetes-charts.storage.googleapis.com](https://charts.helm.sh/stable). Документация Kubernetes по NFS: [Volumes — NFS](https://kubernetes.io/docs/concepts/storage/volumes/#nfs).
