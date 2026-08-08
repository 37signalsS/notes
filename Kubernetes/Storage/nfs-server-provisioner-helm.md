# NFS Server Provisioner (Встроенный NFS-сервер через Helm)

> **Статус: Archived / Deprecated.** Helm-чарт `stable/nfs-server-provisioner` официально заархивирован. Для современных инсталляций (K8s 1.25+) рекомендуется использовать официальный преемник: [nfs-ganesha-server-and-external-provisioner](https://github.com/kubernetes-sigs/nfs-ganesha-server-and-external-provisioner).

## Определения

**NFS Server Provisioner (Helm-чарт)** — это способ развертывания NFS-сервера непосредственно внутри кластера Kubernetes в виде монолитного приложения (`StatefulSet`).

В отличие от классических решений (например, `nfs-subdir-external-provisioner`), где провизионер подключается к внешнему хранилищу, данный чарт объединяет в одном поде и серверную часть (на базе **NFS-Ganesha**), и логику взаимодействия с Kubernetes API.

**Основные характеристики:**
- **Встроенный сервер:** NFS-экспорт создается внутри самого пода.
- **Локальное хранение:** Использует `hostPath` или выделенный `PersistentVolume` на узле как основу для всех динамических томов.
- **Динамический провижининг:** Автоматически создает поддиректории и PV при появлении PVC с соответствующим `StorageClass`.

**Назначение:**
- Быстрое создание RWX-хранилища в однонодовых кластерах (Minikube, MicroK8s, K3s).
- Тестирование механизмов динамического выделения томов без внешней инфраструктуры.
- Обучающие сценарии и лабораторные работы.

---

## Современная альтернатива: NFS-Ganesha Provisioner

Поскольку проект `stable` больше не поддерживается, сообщество `kubernetes-sigs` развивает официальную замену.

**Преимущества нового чарта:**
- **Поддержка современных API:** Полная совместимость с Kubernetes 1.25–1.30+.
- **NFS-Ganesha:** Использование современного пользовательского NFS-сервера, который не требует модулей ядра на хосте.
- **Безопасность:** Улучшенные настройки RBAC и поддержка `securityContext`.

**Установка преемника:**
```bash
helm repo add nfs-ganesha-server-and-external-provisioner https://kubernetes-sigs.github.io/nfs-ganesha-server-and-external-provisioner/
helm install nfs-server nfs-ganesha-server-and-external-provisioner/nfs-server-provisioner
```

---

## Базовые концепции

### Архитектура

Система разворачивается как `StatefulSet` с одной репликой. Это необходимо для сохранения стабильного сетевого идентификатора и корректной работы блокировок файловой системы.

**Компоненты внутри пода:**
1. **Ganesha NFS / Kernel NFS:** Программный сервер, обеспечивающий экспорт директорий.
2. **NFS Provisioner:** Контроллер, который слушает Kubernetes API и создает поддиректории в основной "шаре".

**Зависимость от узла:** Хранилище привязано к конкретной ноде через `hostPath`. Если под переедет на другую ноду, он не найдет свои старые данные.

> **Подробнее:** [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md) — современный и рекомендуемый аналог для работы с внешними серверами.

### Принцип работы

1. **Запуск:** Под монтирует локальную директорию узла (например, `/var/lib/nfs-storage`).
2. **Регистрация:** Создается `StorageClass` (по умолчанию `nfs`).
3. **Выделение:** При создании PVC на 100Mi, провизионер создает папку внутри монтирования и генерирует объект `PersistentVolume`, указывающий на IP пода и эту папку.
4. **Монтирование:** Клиентские поды подключаются к IP-адресу пода-сервера через стандартный протокол NFS.

---

## Практические сценарии

### Полный цикл установки и настройки

#### Шаг 1: Подготовка окружения

Создайте отдельное пространство имен для изоляции ресурсов хранения:

```bash
kubectl create namespace nfs-storage
# → namespace/nfs-storage created
```

#### Шаг 2: Подключение архивного репозитория

Репозиторий `stable` больше не обновляется, но чарты доступны в архиве:

```bash
helm repo add stable https://charts.helm.sh/stable
helm repo update
# → Hang tight while we grab the latest from your chart repositories...
```

#### Шаг 3: Скачивание и исправление чарта

Поскольку чарт старый, рекомендуется скачать его локально для возможной правки API-версий (если ваш кластер v1.25+):

```bash
helm pull stable/nfs-server-provisioner --untar
# → Создаётся директория nfs-server-provisioner/

# Проверка структуры
ls nfs-server-provisioner/
# → Chart.yaml  values.yaml  templates/
```

#### Шаг 4: Конфигурация (values.yaml)

Отредактируйте `nfs-server-provisioner/values.yaml`. Важно настроить персистентность и привязку к ноде:

```yaml
# nfs-server-provisioner/values.yaml

persistence:
  enabled: true
  size: 10Gi  # Общий объем дискового пространства на ноде

storageClass:
  name: nfs-internal
  defaultClass: false

# Обязательно для hostPath: привязка к конкретной железной ноде
nodeSelector:
  kubernetes.io/hostname: "worker-01" 
```

#### Шаг 5: Создание базового PV (Подложка)

Перед установкой чарта создайте PV, который под провизионера будет использовать как свое хранилище:

```yaml
# nfs-root-pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-root-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  hostPath:
    path: /data/nfs-export  # Путь на диске ноды worker-01
---
# nfs-root-pvc.yaml (если чарт требует существующий PVC)
# Обычно чарт сам создает PVC, если persistence.enabled=true
```

#### Шаг 6: Установка

```bash
helm install nfs-server ./nfs-server-provisioner \
  --namespace nfs-storage \
  -f nfs-server-provisioner/values.yaml
```

### Проверка и тестирование

#### 1. Валидация развертывания

```bash
# Проверка пода
kubectl get pods -n nfs-storage
# → NAME                    READY   STATUS    RESTARTS   AGE
# → nfs-server-provisioner-0   1/1     Running   0          1m

# Проверка StorageClass
kubectl get storageclass
# → NAME           PROVISIONER                            RECLAIMPOLICY   VOLUMEBINDINGMODE
# → nfs-internal   cluster.local/nfs-server-provisioner   Delete          Immediate
```

#### 2. Тестирование динамического PVC

Создайте запрос на том:

```yaml
# test-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dynamic-nfs-pvc
  namespace: nfs-storage
spec:
  storageClassName: nfs-internal
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 500Mi
```

```bash
kubectl apply -f test-pvc.yaml
kubectl get pvc -n nfs-storage
# → NAME              STATUS   VOLUME                                     CAPACITY   ACCESS MODES
# → dynamic-nfs-pvc   Bound    pvc-12345678-abcd-1234-abcd-1234567890ab   500Mi      RWX
```

#### 3. Проверка сохранения данных (Nginx)

Разверните под для проверки записи:

```yaml
# test-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: storage-test-pod
  namespace: nfs-storage
spec:
  containers:
    - name: nginx
      image: nginx:latest
      volumeMounts:
        - name: nfs-vol
          mountPath: /data
  volumes:
    - name: nfs-vol
      persistentVolumeClaim:
        claimName: dynamic-nfs-pvc
```

**Процедура верификации:**

1. **Запись данных:**
   ```bash
   kubectl exec -it -n nfs-storage storage-test-pod -- bash -c "echo 'Persistence Works' > /data/test.txt"
   ```

2. **Пересоздание пода:**
   ```bash
   kubectl delete pod storage-test-pod -n nfs-storage
   kubectl apply -f test-pod.yaml
   ```

3. **Проверка:**
   ```bash
   kubectl exec -it -n nfs-storage storage-test-pod -- cat /data/test.txt
   # → Persistence Works
   ```

---

## Безопасность и конфигурация

### Привилегии контейнера
Запуск NFS-сервера внутри контейнера требует расширенных привилегий для работы с системными вызовами монтирования и экспорта.

**Рекомендуемый `securityContext`:**
```yaml
securityContext:
  privileged: true
  capabilities:
    add: ["SYS_ADMIN", "DAC_READ_SEARCH"]
```

### Сетевые политики (NetworkPolicies)
Поскольку NFS-сервер открывает порты (2049) внутри кластера, рекомендуется ограничить доступ к нему только для тех пространств имен, которым действительно нужно хранилище.

**Пример политики:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-nfs-access
  namespace: nfs-storage
spec:
  podSelector:
    matchLabels:
      app: nfs-server-provisioner
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              storage-client: "true"
      ports:
        - protocol: TCP
          port: 2049
```

---

## Необходимые системные пакеты

Для успешного монтирования NFS на клиентских нодах должны быть установлены утилиты:

- **Ubuntu/Debian:** `sudo apt update && sudo apt install nfs-common -y`
- **CentOS/RHEL/Rocky:** `sudo yum install nfs-utils -y`

---

## Дополнительная информация

### Критические ограничения

| Ограничение | Описание | Риски |
| :--- | :--- | :--- |
| **Локальная привязка** | Данные часто хранятся на локальном диске ОДНОЙ ноды. | При выходе ноды из строя данные становятся недоступны (SPOF). |
| **Отсутствие HA** | Сервер — это одиночный под (StatefulSet с 1 репликой). | Перезагрузка пода вызывает прерывание связи (I/O hang) у клиентов. |
| **Устаревший код (stable)** | Оригинальный чарт `stable` не обновляется. | Проблемы безопасности и несовместимость с новыми K8s API (v1.25+). |
| **Производительность** | Весь трафик идет через один под. | Ограничение пропускной способности сети одного узла. |

### Рекомендации по выбору

- **Использовать для:** локальных экспериментов, CI/CD пайплайнов в однонодовых окружениях, демонстраций RWX.
- **НЕ использовать для:** Production-баз данных, высоконагруженных систем, многонодовых кластеров с потребностью в отказоустойчивости.

### См. также

- Базовые концепции хранения: [PersistentVolume и PVC](./pv_and_pvc.md)
- Рекомендуемый современный аналог: [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md)
- Альтернатива для локальных дисков: [Local Path Provisioner](./local-path-provisioner.md)
- Сравнение CSI-драйверов: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md)
- Распределенное хранилище: [Ceph CephFS](./Ceph/cephfs_setup_and_usage/definitions_and_concepts.md)
