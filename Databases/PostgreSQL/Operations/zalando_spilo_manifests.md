# Zalando Spilo: Развертывание кластера PostgreSQL через манифесты

## Определения

**Spilo** — это специализированный Docker-образ от Zalando, который объединяет PostgreSQL, Patroni (для обеспечения высокой доступности) и набор инструментов для облачной эксплуатации (WAL-G для бэкапов, pg_view для мониторинга). Он является "золотым стандартом" для запуска Postgres в Kubernetes до появления нативных операторов.

**Patroni** — это управляющее приложение (на базе Python), которое контролирует жизненный цикл инстанса PostgreSQL. Оно автоматизирует выбор лидера (Leader Election), настройку репликации и переключение при сбоях (failover). В Spilo Patroni запускается как основной процесс (PID 1).

**WAL-G** — современный инструмент для эффективного резервного копирования и восстановления PostgreSQL. Он поддерживает инкрементальные бэкапы, сжатие (LZ4, ZSTD) и параллельную загрузку WAL-логов в объектные хранилища (S3, GCS, Azure).

**DCS (Distributed Configuration Store)** — распределенное хранилище конфигураций и блокировок. В Kubernetes Spilo чаще всего использует нативное **Kubernetes API** (через ресурсы Endpoints или ConfigMaps) в качестве DCS, что исключает зависимость от внешнего etcd.

**Fencing** — механизм защиты от "Split-Brain", при котором старый мастер принудительно изолируется (например, переводится в read-only или выключается), если он потерял связь с DCS.

## Базовые концепции

### Почему выбирают манифесты вместо операторов?

Хотя **[Zalando Postgres Operator](./zalando_postgres_operator.md)** и **[CloudNativePG](./kubernetes_deployment.md)** упрощают управление, использование прямых манифестов (StatefulSet) дает:
1.  **Максимальный контроль:** Вы управляете каждым байтом конфигурации `initContainers`, `sidecars` и `volumes`.
2.  **Специфический тюнинг:** Возможность настраивать параметры ядра (`sysctl`) или монтировать специфические устройства, что часто ограничено в операторах.
3.  **Отсутствие "магических" абстракций:** Проще отлаживать стандартные объекты Kubernetes при возникновении проблем в Control Plane оператора.

### Жизненный цикл пода в Spilo
При старте пода Patroni выполняет следующие действия:
1.  Опрашивает DCS, чтобы узнать, есть ли в кластере активный лидер.
2.  Если лидера нет — инициирует выборы. Победитель делает `initdb` или восстанавливается из бэкапа.
3.  Если лидер есть — настраивает текущий инстанс как реплику, используя `pg_basebackup` или `wal-g restore`.

## Предварительные требования
*   Кластер Kubernetes версии 1.28+.
*   Поддержка **StorageClass** с динамическим выделением (рекомендуется XFS/Ext4 с `noatime`).
*   Доступ к S3-совместимому хранилищу для бэкапов.
*   Настроенные лимиты ресурсов на узлах (минимум 2 CPU и 4 ГБ RAM для Production-инстанса).

## Практические сценарии

### Шаг 1: Настройка прав доступа (RBAC)

Patroni должен иметь права на чтение/запись Endpoints или ConfigMaps для управления блокировкой лидера.

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
  # Patroni использует эти ресурсы как DCS
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

### Шаг 2: Конфигурация через ConfigMap

Для декларативного управления параметрами Patroni и Postgres рекомендуется использовать ConfigMap.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: pg-prod-config
data:
  # Настройки Patroni
  patroni.yaml: |
    scope: pg-prod
    namespace: default
    name: $(POD_NAME)
    kubernetes:
      use_endpoints: true
    postgresql:
      listen: 0.0.0.0:5432
      callbacks:
        on_role_change: /home/postgres/callbacks.sh
      parameters:
        max_connections: 500
        shared_buffers: 1GB
        # Использование преимуществ PostgreSQL 18
        io_direct: "data,wal"
```

### Шаг 3: Спецификация StatefulSet (PostgreSQL 18)

Пример с использованием актуального образа Spilo-18 и интеграцией мониторинга.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: pg-prod
spec:
  serviceName: "pg-prod-nodes" # Headless Service
  replicas: 3
  selector:
    matchLabels:
      spilo-cluster: pg-prod
  template:
    metadata:
      labels:
        spilo-cluster: pg-prod
    spec:
      serviceAccountName: spilo-sa
      # Тюнинг ядра для БД (HugePages, TCP)
      initContainers:
      - name: sysctl-tuning
        image: busybox
        securityContext: { privileged: true }
        command: ["sysctl", "-w", "vm.nr_hugepages=512"]
      containers:
      - name: postgres
        image: "registry.opensource.zalan.do/acid/spilo-18:3.5-p1"
        ports:
        - containerPort: 5432
        - containerPort: 8008 # Patroni REST API
        env:
          - name: SCOPE
            value: "pg-prod"
          - name: POD_NAMESPACE
            valueFrom: { fieldRef: { fieldPath: metadata.namespace } }
          - name: POD_NAME
            valueFrom: { fieldRef: { fieldPath: metadata.name } }
          # Конфигурация WAL-G
          - name: WALG_S3_PREFIX
            value: "s3://backups/pg-prod"
          - name: AWS_ACCESS_KEY_ID
            valueFrom: { secretKeyRef: { name: s3-creds, key: ID } }
          - name: AWS_SECRET_ACCESS_KEY
            valueFrom: { secretKeyRef: { name: s3-creds, key: SECRET } }
        resources:
          requests: { cpu: "2", memory: "4Gi" }
          limits: { cpu: "2", memory: "4Gi" } # QOS: Guaranteed
        volumeMounts:
        - name: pgdata
          mountPath: /home/postgres/pgdata
      # Экспортер для Prometheus (v0.20.1)
      - name: exporter
        image: "prometheuscommunity/postgres-exporter:v0.20.1"
        env:
          - name: DATA_SOURCE_NAME
            value: "postgresql://postgres@localhost:5432/postgres?sslmode=disable"
        ports:
        - containerPort: 9187
  volumeClaimTemplates:
  - metadata: { name: pgdata }
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "premium-rwo-ssd"
      resources: { requests: { storage: 100Gi } }
```

### Шаг 4: Сетевая топология

Для корректной работы необходимо разделять трафик на запись и чтение.

```yaml
# 1. Headless Service (для внутреннего Service Discovery)
apiVersion: v1
kind: Service
metadata:
  name: pg-prod-nodes
spec:
  clusterIP: None
  selector: { spilo-cluster: pg-prod }
  ports: [{ port: 5432, name: postgres }]
---
# 2. Master Service (Запись)
# Patroni динамически обновляет Endpoints, добавляя туда только лидера
apiVersion: v1
kind: Service
metadata:
  name: pg-prod
spec:
  ports: [{ port: 5432 }]
---
apiVersion: v1
kind: Endpoints
metadata:
  name: pg-prod
subsets: [] # Управляется Patroni
---
# 3. Replica Service (Чтение)
apiVersion: v1
kind: Service
metadata:
  name: pg-prod-repl
spec:
  selector:
    spilo-cluster: pg-prod
    spilo-role: replica # Метка ставится Patroni автоматически
  ports: [{ port: 5432 }]
```

## Валидация и проверка

1.  **Проверка состояния кластера:**
    ```bash
    kubectl exec -it pg-prod-0 -c postgres -- patronictl list
    # Ожидаемый результат: Список узлов, один из которых в роли Leader (running)
    ```
2.  **Проверка готовности Postgres:**
    ```bash
    kubectl exec -it pg-prod-0 -c postgres -- pg_isready -h localhost
    # Ожидаемый результат: /var/run/postgresql:5432 - accepting connections
    ```
3.  **Проверка WAL-архивации:**
    Логи контейнера должны содержать записи об успешной выгрузке сегментов в S3.

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` на `/home/postgres/pgdata` | Неверный FSGroup или права на Volume. | Установите `securityContext.fsGroup: 1000` в StatefulSet. |
| Кластер не выбирает лидера | Отсутствие прав RBAC на Endpoints. | Проверьте `kubectl describe role spilo-role`. |
| `Stale leader lock` | Сбой DCS или сетевой лаг. | Проверьте доступность API Kubernetes. Удалите зависший Endpoint вручную. |
| `Streaming replication has stopped` | Реплика слишком сильно отстала. | Patroni автоматически перезапустит клонирование через `pg_basebackup`. |

## Пограничные случаи и ограничения

### Обновление мажорной версии
В отличие от операторов, обновление образа в StatefulSet (`spilo-17` -> `spilo-18`) не приведет к автоматическому `pg_upgrade`.
*   **Решение:** Используйте логическую репликацию или инструменты типа `pg_upgrade` внутри `initContainer` с временным вторым диском. См. **[Миграция без простоя](./zero_downtime_migration.md)**.

### Восстановление из S3 (Bootstrap)
Если кластер новый, но нужно восстановить данные:
В `env` добавьте:
```yaml
- name: CLONE_METHOD
  value: "CLONE_WITH_WALOG"
- name: CLONE_WAL_S3_BUCKET
  value: "backups"
```

## Дополнительная информация

### SRE Чек-лист
- [ ] Настроен **PodDisruptionBudget** (minAvailable: 1).
- [ ] Настроена **Anti-Affinity** (по `kubernetes.io/hostname`).
- [ ] Включены **HugePages** на уровне ОС и лимитов пода.
- [ ] Настроен алертинг на `pg_static_replication_lag`.

### Связанные документы
- **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — теория Patroni.
- **[Zalando Postgres Operator](./zalando_postgres_operator.md)** — автоматизированная альтернатива.
- **[Наблюдаемость PostgreSQL](./observability.md)** — детали мониторинга.
- **[Сетевая связность](./kubernetes_connectivity.md)** — работа с сервисами в K8s.
