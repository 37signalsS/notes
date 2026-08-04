# Zalando Spilo: Развертывание кластера PostgreSQL через манифесты

## Определения

**Spilo** — специализированный Docker-образ от Zalando, объединяющий PostgreSQL, Patroni для обеспечения высокой доступности и набор инструментов для облачной эксплуатации (WAL-G, pg_view).

**Patroni** — Python-приложение (шаблон), управляющее жизненным циклом инстанса PostgreSQL. Оно автоматизирует выбор лидера, настройку репликации и переключение при сбоях (failover). Подробнее — **[High Availability](../Concepts/high_availability.md)**.

**WAL-G** — инструмент для эффективного резервного копирования и восстановления PostgreSQL. Поддерживает инкрементальные бэкапы и архивацию WAL-логов в объектные хранилища (S3, GCS, Azure).

**DCS (Distributed Configuration Store)** — распределенное хранилище для координации кластера. В Kubernetes Spilo использует нативное K8s API (Endpoints или ConfigMaps) в качестве DCS.

## Основные концепции

### Подход к развертыванию через манифесты

Использование прямых манифестов (StatefulSet, Service, ConfigMap) вместо **[Zalando Postgres Operator](./zalando_postgres_operator.md)** оправдано в случаях:
- Необходимости кастомной логики в Sidecar-контейнерах.
- Специфического тюнинга параметров ядра (sysctl) через `initContainers`.
- Жесткого контроля версий и инфраструктуры как кода (IaC) без промежуточных слоев абстракции.

### Механизм выбора лидера (Leader Election)

Patroni реализует алгоритм выбора лидера через Kubernetes API:
1. **Endpoint Lock**: Инстанс, успешно выполнивший `patch` объекта Endpoints и удерживающий его, становится Primary (Master).
2. **TTL**: Лидер обязан постоянно обновлять временную метку (Time-to-Live). Если обновление не произошло (зависание ОС или сети), лидер считается упавшим, и реплики начинают новые выборы.
3. **Безопасность (Fencing)**: При потере связи с DCS Patroni принудительно переводит PostgreSQL в режим `read-only` или останавливает его, чтобы предотвратить Split-brain.

### Хранение данных и WAL-архивация

Spilo ожидает монтирования данных в `/home/postgres/pgdata`. Рекомендуется использовать **XFS** или **ext4** с опцией `noatime`.
Архивация WAL выполняется автоматически через WAL-G, если настроены соответствующие переменные окружения. Это критически важно для обеспечения RPO (Recovery Point Objective) близкого к нулю.

## Практические сценарии

### Шаг 1: Настройка прав доступа (RBAC)

Patroni требует прав на манипуляцию ресурсами в своем Namespace для управления кворумом.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: spilo-sa
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: spilo-role
rules:
- apiGroups: [""]
  resources: ["configmaps", "endpoints", "pods", "services"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: spilo-rb
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: spilo-role
subjects:
- kind: ServiceAccount
  name: spilo-sa
```

### Шаг 2: Спецификация StatefulSet (PostgreSQL 17)

Пример конфигурации с лимитами ресурсов, мониторингом и WAL-архивацией.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: pg-prod
spec:
  replicas: 3
  serviceName: "pg-prod-nodes"
  selector:
    matchLabels:
      spilo-cluster: pg-prod
  template:
    metadata:
      labels:
        spilo-cluster: pg-prod
    spec:
      serviceAccountName: spilo-sa
      containers:
      - name: postgres
        image: "registry.opensource.zalan.do/acid/spilo-17:3.4-p1"
        ports:
        - containerPort: 5432
        - containerPort: 8008 # Patroni REST API
        env:
          - name: SCOPE
            value: "pg-prod"
          - name: DCS_ENABLE_KUBERNETES_API
            value: "true"
          - name: KUBERNETES_SCOPE_LABEL
            value: "spilo-cluster"
          - name: POD_NAMESPACE
            valueFrom:
              fieldRef:
                fieldPath: metadata.namespace
          # Конфигурация бэкапов (S3)
          - name: WALG_S3_PREFIX
            value: "s3://my-backups/pg-prod"
          - name: AWS_ACCESS_KEY_ID
            valueFrom: { secretKeyRef: { name: s3-creds, key: ID } }
          - name: AWS_SECRET_ACCESS_KEY
            valueFrom: { secretKeyRef: { name: s3-creds, key: SECRET } }
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "2Gi" # Requests = Limits для RAM (Best Practice)
        readinessProbe:
          httpGet: { path: /readiness, port: 8008 }
        livenessProbe:
          httpGet: { path: /liveness, port: 8008 }
      # Sidecar для экспорта метрик Prometheus
      - name: exporter
        image: "prometheuscommunity/postgres-exporter:v0.15.0"
        env:
          - name: DATA_SOURCE_NAME
            value: "postgresql://postgres@localhost:5432/postgres?sslmode=disable"
        ports:
        - containerPort: 9187
```

### Шаг 3: Сетевая топология

Для корректной работы приложений создается два сервиса: статический для записи и динамический для чтения.

```yaml
# Сервис для записи (Master)
# Patroni автоматически обновит Endpoints с этим именем
apiVersion: v1
kind: Service
metadata:
  name: pg-prod
spec:
  ports:
  - port: 5432
---
apiVersion: v1
kind: Endpoints
metadata:
  name: pg-prod
subsets: []
---
# Сервис для чтения (Replicas)
apiVersion: v1
kind: Service
metadata:
  name: pg-prod-repl
spec:
  selector:
    spilo-cluster: pg-prod
    spilo-role: replica # Метка добавляется Patroni динамически
  ports:
  - port: 5432
```

## Дополнительная информация

### Диагностика и обслуживание

Основные команды для работы с кластером через `patronictl`:

```bash
# Просмотр статуса кластера и отставания реплик
kubectl exec -it pg-prod-0 -c postgres -- patronictl list

# Ручное переключение мастера (Maintenance)
kubectl exec -it pg-prod-0 -c postgres -- patronictl switchover

# Изменение параметров postgresql.conf без перезапуска (где возможно)
kubectl exec -it pg-prod-0 -c postgres -- patronictl edit-config
```

### SRE Чек-лист

1. **Anti-Affinity**: Убедитесь, что настроен `podAntiAffinity` по `kubernetes.io/hostname`, чтобы избежать падения всего кластера при выходе ноды из строя.
2. **PDB (Pod Disruption Budget)**: Настройте `minAvailable: 1` для предотвращения одновременного удаления всех реплик при drain нод.
3. **HugePages**: Для высоконагруженных систем включите HugePages на уровне нод и пробросьте их в контейнер.
4. **Мониторинг**: Настройте алертинг на `pg_static_replication_lag` (> 100MB) и на состояние `Leader Lock`.

### Смотрите также

* **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — архитектура Patroni.
* **[Zalando Postgres Operator](./zalando_postgres_operator.md)** — автоматизированное управление.
* **[Наблюдаемость PostgreSQL](./observability.md)** — интеграция с мониторингом.
* **[Сетевая связность](./kubernetes_connectivity.md)** — особенности работы в K8s.
