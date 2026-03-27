# Zalando Spilo: Развертывание кластера PostgreSQL через манифесты

## Определения

**Spilo** — Docker-образ от Zalando с готовой сборкой PostgreSQL и инструментами высокой доступности.

**Patroni** — open-source решение для создания отказоустойчивых кластеров PostgreSQL. Автоматизирует failover и управление жизненным циклом кластера.

## Основные концепции

### Подход к развёртыванию

Развёртывание через "голые" манифесты Kubernetes на основе шаблона от Zalando. Более гибкий, но сложный способ по сравнению с [Zalando Postgres Operator](./zalando_postgres_operator.md).

### Динамическое управление Endpoint'ами

**Проблема:** Стандартный `ClusterIP` сервис использует `round-robin` для всех подов. Для БД это неприемлемо — запись должна идти только на мастер.

**Решение Spilo:**

1. Создаётся сервис **без селектора**
2. Создаётся `Endpoint` с тем же именем и **пустым списком адресов**
3. Patroni внутри пода-мастера **редактирует `Endpoint`**, прописывая свой IP
4. Сервис всегда указывает только на актуальный мастер

**Требования:** RBAC с правами `patch`, `update` для ресурсов `endpoints`.

### Управление конфигурацией

Конфигурация Spilo и Patroni осуществляется через переменные окружения в манифесте `StatefulSet`.

## Практические сценарии

### Подготовка манифеста

За основу берётся [манифест из репозитория Zalando](https://github.com/zalando/spilo/blob/master/manifests/postgres-spilo.yaml).

#### StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: zalando-demo-01
  namespace: spilo
spec:
  replicas: 3
  selector:
    matchLabels:
      application: spilo
      cluster-name: zalando-demo-01
  podManagementPolicy: Parallel
  serviceName: "zalando-demo-01-config"
  template:
    metadata:
      labels:
        application: spilo
        cluster-name: zalando-demo-01
        spilo-cluster: zalando-demo-01
    spec:
      serviceAccountName: spilo-operator
      # ... affinity, containers ...
```

#### Affinity: Привязка подов к нодам

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - key: "db"
          operator: In
          values: ["spilo"]
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: spilo-cluster
          operator: In
          values: ["zalando-demo-01"]
      topologyKey: "kubernetes.io/hostname"
```

**Требование:** Пометить ноды: `kubectl label node <node-name> db=spilo`

#### Контейнер Spilo и переменные окружения

```yaml
containers:
- name: postgres
  image: "registry.opensource.zalan.do/acid/spilo-15:3.2-p1"
  imagePullPolicy: IfNotPresent
  env:
    # Бэкап на локальный диск (NFS)
    - name: WALG_FILE_PREFIX
      value: "file:///var/lib/postgresql/wal-g/zalando-demo-01"
    - name: CRON_SCHEDULE
      value: "00 01 * * * /scripts/postgres_backup.sh"

    # Доступ к паролям из Secret
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

    # Связь с Kubernetes API
    - name: KUBERNETES_SCOPE_LABEL
      value: "spilo-cluster"
    - name: KUBERNETES_LABELS
      value: '{"application": "spilo", "cluster-name": "zalando-demo-01"}'
```

#### Volume'ы и бэкапы

```yaml
# Данные PostgreSQL (локальные диски)
volumeClaimTemplates:
- metadata:
    name: pgdata
  spec:
    accessModes: ["ReadWriteOnce"]
    storageClassName: local-path
    resources:
      requests:
        storage: 20Gi

# Бэкапы (NFS, ReadWriteMany)
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: zalando-demo-01-backup
  namespace: spilo
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: nfs-storage
  resources:
    requests:
      storage: 10Gi
```

### Доступ к кластеру

#### Внутренний доступ (через Endpoint, управляемый Spilo)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: zalando-demo-01
  namespace: spilo
  labels:
    spilo-cluster: zalando-demo-01
spec:
  ports:
  - port: 5432
    targetPort: 5432
---
apiVersion: v1
kind: Endpoints
metadata:
  name: zalando-demo-01
  namespace: spilo
  labels:
    spilo-cluster: zalando-demo-01
subsets: []
```

#### Внешний доступ (через NodePort)

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
    targetPort: 5432
  selector:
    role: master
    spilo-cluster: zalando-demo-01
```

### Инструменты и операции

**Подключение к поду:**

```bash
kubectl exec -it <pod-name> -n spilo -- bash
```

**Просмотр состояния кластера:**

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

**Ручное переключение мастера (Switchover):**

```bash
patroni_ctl switchover zalando-demo-01
# Выбрать кандидата и подтвердить
# Success: switchover complete
```

После переключения сервисы автоматически переключатся на новый мастер.

## Дополнительная информация

### Связанные документы

- **Бэкапы:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
- **Высокая доступность:** **[High Availability](../Concepts/high_availability.md)**
- **Zalando Operator:** **[Zalando Postgres Operator](./zalando_postgres_operator.md)**
