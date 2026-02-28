# Zalando Spilo: Развертывание кластера PostgreSQL через манифесты

## Определения

- **Spilo:** Это Docker-образ от Zalando, который содержит готовую сборку PostgreSQL с инструментами для обеспечения высокой доступности.
- **Patroni:** Ключевой компонент Spilo. Это open-source решение для создания отказоустойчивых кластеров PostgreSQL. Patroni автоматизирует управление жизненным циклом кластера, включая автоматическое переключение при сбоях (failover).

## Базовые концепции

Этот подход описывает развертывание кластера PostgreSQL в Kubernetes с использованием "голых" манифестов, на основе базового шаблона от Zalando. Это более гибкий, но и более сложный способ по сравнению с использованием [Zalando Postgres Operator](./zalando_postgres_operator.md).

### Ключевая особенность: динамическое управление Endpoint'ами

Самое элегантное решение в Spilo — это механизм обнаружения мастера.

1.  **Проблема:** Стандартный сервис `ClusterIP` в Kubernetes использует `round-robin` для распределения трафика между всеми подами, на которые он нацелен. Для кластера БД это неприемлемо, так как запросы на запись должны идти только на мастер.
2.  **Решение Spilo:**
    - В манифесте создается сервис **без селектора** (`selector`).
    - Одновременно создается объект `Endpoint` с тем же именем, но с **пустым списком адресов** (`subsets`).
    - Приложение Patroni, работающее внутри каждого пода Spilo, после выборов лидера обращается к Kubernetes API.
    - Победивший под (мастер) самостоятельно **редактирует объект `Endpoint`**, прописывая в него свой собственный IP-адрес.
3.  **Результат:** Сервис всегда указывает только на актуальный мастер-под.
4.  **Требования:** Для работы этого механизма необходимо настроить RBAC: создать `ServiceAccount`, `Role` с правами на `patch`, `update` для ресурсов `endpoints` и `RoleBinding`.

### Управление конфигурацией

Конфигурация Spilo и Patroni почти полностью осуществляется через переменные окружения (`env`) в манифесте `StatefulSet`.

## Практические сценарии

### 1. Подготовка манифеста

За основу берется [манифест из репозитория Zalando](https://github.com/zalando/spilo/blob/master/manifests/postgres-spilo.yaml) и модифицируется.

#### StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: zalando-demo-01
  namespace: spilo
spec:
  replicas: 3 # 1 мастер и 2 реплики
  selector:
    matchLabels:
      application: spilo
      cluster-name: zalando-demo-01
  # Позволяет выполнять rolling restart без простоя
  podManagementPolicy: Parallel
  serviceName: "zalando-demo-01-config"
  template:
    metadata:
      labels:
        application: spilo
        cluster-name: zalando-demo-01
        spilo-cluster: zalando-demo-01 # Для endpoint'ов
    spec:
      serviceAccountName: spilo-operator # RBAC
      # ... affinity, containers ...
```

#### Affinity: Привязка подов к нодам

При использовании локальных дисков (например, через `local-path-provisioner`), крайне важно обеспечить, чтобы каждый под всегда запускался на своей ноде и не "переезжал".

```yaml
# spec.template.spec.affinity
affinity:
  # 1. Выбираем только те ноды, которые мы пометили для БД
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - key: "db"
          operator: In
          values:
          - "spilo"
  # 2. Запрещаем запуск двух подов этого кластера на одной ноде
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: spilo-cluster
          operator: In
          values:
          - zalando-demo-01
      topologyKey: "kubernetes.io/hostname"
```

Перед применением нужно пометить рабочие ноды:
`kubectl label node <node-name> db=spilo`

#### Контейнер Spilo и переменные окружения

```yaml
# spec.template.spec.containers
containers:
- name: postgres
  # Актуальную версию ищем через API Zalando или в их репозитории
  image: "registry.opensource.zalan.do/acid/spilo-15:3.0-p1"
  imagePullPolicy: IfNotPresent # Обязательно, образ весит >1ГБ
  env:
    # --- Переменные для бэкапа на локальный диск (NFS) ---
    - name: WALG_FILE_PREFIX
      value: "file:///var/lib/postgresql/wal-g/zalando-demo-01"
    # Запускает бэкап по расписанию через cron внутри контейнера
    - name: CRON_SCHEDULE
      value: "00 01 * * * /scripts/postgres_backup.sh"
    
    # --- Переменные для доступа к паролям из Secret ---
    - name: PGUSER_SUPERUSER
      valueFrom:
        secretKeyRef:
          name: postgres.zalando-demo-01.credentials
          key: superuser-username
    - name: PGPASSWORD_SUPERUSER
      valueFrom:
        secretKeyRef:
          name: postgres.zalando-demo-01.credentials
          key: superuser-password
    # ... другие пользователи
    
    # --- Переменные для связи с Kubernetes API ---
    - name: KUBERNETES_SCOPE_LABEL
      value: "spilo-cluster" # Имя лейбла для поиска Endpoint'а
    - name: KUBERNETES_LABELS
      value: '{"application": "spilo", "cluster-name": "zalando-demo-01"}'
  
  # ... ports, resources, volumeMounts ...
```

#### Volume'ы и бэкапы

- **Данные PostgreSQL:** Хранятся на локальных дисках нод. Для этого используется `volumeClaimTemplates` со `storageClassName: local-path`.
- **Бэкапы:** Чтобы все поды писали бэкапы в одно общее место, создается отдельный `PersistentVolumeClaim` (не через template) с `accessModes: ReadWriteMany` и подключается ко всем подам. Обычно для этого используется NFS.

```yaml
# Внутри StatefulSet
volumeClaimTemplates:
- metadata:
    name: pgdata
  spec:
    accessModes: [ "ReadWriteOnce" ]
    storageClassName: local-path # Для данных БД
    resources:
      requests:
        storage: 20Gi
---
# Отдельный PVC для бэкапов
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: zalando-demo-01-backup
  namespace: spilo
spec:
  accessModes:
  - ReadWriteMany # Требует NFS или аналогичное хранилище
  storageClassName: nfs-storage
  resources:
    requests:
      storage: 10Gi
```

### 2. Доступ к кластеру

#### Внутренний доступ (через сервис, управляемый Spilo)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: zalando-demo-01
  namespace: spilo
  labels:
    # Этот лейбл используется Spilo для поиска сервиса
    spilo-cluster: zalando-demo-01
spec:
  ports:
  - port: 5432
    protocol: TCP
    targetPort: 5432
---
apiVersion: v1
kind: Endpoints
metadata:
  name: zalando-demo-01 # Имя должно совпадать с сервисом
  namespace: spilo
  labels:
    # Этот лейбл используется Spilo для поиска Endpoint'а
    spilo-cluster: zalando-demo-01
# subsets изначально пуст и заполняется мастером
subsets: []
```

#### Внешний доступ (через NodePort, управляемый Kubernetes)

Этот сервис использует селектор по лейблу `role: master`, который Patroni автоматически устанавливает на мастер-под.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: zalando-demo-01-nodeport
  namespace: spilo
spec:
  type: NodePort
  ports:
  - name: postgresql
    port: 5432
    protocol: TCP
    targetPort: 5432
  selector:
    # Kubernetes будет сам следить, у какого пода есть этот лейбл
    role: master
    spilo-cluster: zalando-demo-01
```

### 3. Инструменты и операции

- **Подключение к поду:** `kubectl exec -it <pod-name> -n spilo -- bash`
- **Просмотр состояния кластера:**
  ```bash
  patroni_ctl list
  # +------------------+--------------------+-------------+--------+---------+----+-----------+
  # | Cluster          | Member             | Host        | Role   | State   | TL | Lag in MB |
  # +------------------+--------------------+-------------+--------+---------+----+-----------+
  # | zalando-demo-01  | zalando-demo-01-0  | 10.244.1.25 | Leader | running |  1 |         0 |
  # | zalando-demo-01  | zalando-demo-01-1  | 10.244.2.29 |        | running |  1 |         0 |
  # | zalando-demo-01  | zalando-demo-01-2  | 10.244.3.26 |        | running |  1 |         0 |
  # +------------------+--------------------+-------------+--------+---------+----+-----------+
  ```
- **Ручное переключение мастера (Switchover):**
  ```bash
  # Запускается на одном из подов
  patroni_ctl switchover zalando-demo-01

  # Выбрать кандидата и подтвердить
  # ...
  # Success: switchover complete
  ```
  После этого оба сервиса (`zalando-demo-01` и `zalando-demo-01-nodeport`) автоматически переключатся на новый мастер.
