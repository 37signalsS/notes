# Zalando Spilo: Развертывание кластера PostgreSQL через манифесты

**Актуально для:** Spilo 18 (`ghcr.io/zalando/spilo-18:4.1-p2`, Patroni 4.1.x, PostgreSQL 18; образ multi-arch: amd64/arm64) / Kubernetes 1.27+

## Определения

**Spilo** — Docker-образ от Zalando, объединяющий PostgreSQL, Patroni (для HA) и инструменты эксплуатации: WAL-G (бэкапы) и набор утилит для диагностики (в т.ч. `pg_view`). Spilo — это движок **[Zalando Postgres Operator](./zalando_postgres_operator.md)**, но он может работать и без оператора, через прямые манифесты. Образы публикуются в GitHub Container Registry (`ghcr.io/zalando/spilo-<PG-версия>`); старый registry `registry.opensource.zalan.do` больше не используется.

**Patroni** — управляющее приложение (Python), которое контролирует жизненный цикл инстанса PostgreSQL: выбор лидера (Leader Election), настройку репликации и автоматический failover. В Spilo Patroni запускается как основной процесс (PID 1). Теория работы Patroni, Watchdog и алгоритмов выбора лидера — в **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)**.

**WAL-G** — инструмент резервного копирования и восстановления PostgreSQL: инкрементальные бэкапы, сжатие (LZ4, ZSTD), параллельная загрузка/выгрузка (`WALG_UPLOAD_CONCURRENCY`, `WALG_DOWNLOAD_CONCURRENCY`). Поддерживает S3-совместимые хранилища (например, self-hosted MinIO), POSIX-файловые системы, SSH и Swift. Поддержка WAL-E в Spilo удалена (обратная совместимость для переменных `WALE*` сохранена, приоритет у `WALG*`). Теория бэкапов и PITR — в **[Автоматизация бэкапов](./backup_automation.md)**.

**DCS (Distributed Configuration Store)** — распределенное хранилище конфигураций и блокировок. В Kubernetes Patroni использует нативный **Kubernetes API** (ресурсы Endpoints или ConfigMaps) в качестве DCS, что исключает зависимость от внешнего etcd. В Spilo режим DCS управляется переменными окружения: `DCS_ENABLE_KUBERNETES_API` (непустое значение включает K8s API как DCS) и `KUBERNETES_USE_CONFIGMAPS` (хранить метаданные в ConfigMaps вместо Endpoints; требуется, например, на OpenShift).

**Fencing** — механизм защиты от Split-Brain: при потере связи с DCS Patroni принудительно останавливает PostgreSQL или переводит его в read-only, чтобы изолированный узел не мог принимать записи.

## Базовые концепции

### Почему выбирают манифесты вместо операторов?

Хотя **[Zalando Postgres Operator](./zalando_postgres_operator.md)** и **[CloudNativePG](./kubernetes_deployment.md)** упрощают управление, использование прямых манифестов (StatefulSet) даёт:
1.  **Максимальный контроль:** Вы управляете каждым байтом конфигурации `initContainers`, `sidecars` и `volumes`.
2.  **Специфический тюнинг:** Возможность настраивать параметры ядра на узлах или монтировать специфические устройства, что часто ограничено в операторах.
3.  **Отсутствие «магических» абстракций:** Проще отлаживать стандартные объекты Kubernetes при возникновении проблем в Control Plane оператора.

Spilo при этом остаётся активно развиваемым проектом (образы собираются multi-arch, последние релизы включают PostgreSQL 18), поэтому «сырые» манифесты — не legacy-подход, а осознанный выбор.

### DCS: Endpoints против ConfigMaps

Patroni в Kubernetes хранит конфигурацию кластера и лидерский ключ в одном из двух объектов (режим настраивается переменной `KUBERNETES_USE_CONFIGMAPS`):

| Режим | Механизм | Смена лидера |
| :--- | :--- | :--- |
| **Endpoints** (рекомендуется, но выключен по умолчанию в Patroni для совместимости) | Конфигурация и лидерский ключ в `metadata.annotations` Endpoints, именованного по `SCOPE` | Атомарная: аннотации и адрес лидирующего пода обновляются одной операцией |
| **ConfigMaps** | Аналогично, но в ConfigMaps | Минимум две операции: обновление ConfigMap с лидером и отдельное обновление Endpoints |

### Метки подов, которые ставит Patroni (Spilo)

Patroni патчит поды метками роли — на них опирается Service для чтения. В Spilo значения по умолчанию отличаются от «чистого» Patroni и задаются переменными:

| Метка | Значение по умолчанию | Переменная окружения |
| :--- | :--- | :--- |
| Роль пода | `spilo-role: master` / `spilo-role: replica` | `KUBERNETES_ROLE_LABEL`, `KUBERNETES_LEADER_LABEL_VALUE`, `KUBERNETES_STANDBY_LEADER_LABEL_VALUE` |
| Имя кластера | `version: <SCOPE>` | `KUBERNETES_SCOPE_LABEL` |
| Служебные метки | `application: spilo` | `KUBERNETES_LABELS` (по умолчанию `{"application": "spilo"}`) |

**Важно:** метка `application: spilo` обязательна — Patroni ищет членов кластера по ней (вместе с `version: <SCOPE>`). Если поды созданы без неё, узлы не увидят друг друга и кластер не соберётся.

### Жизненный цикл пода в Spilo
При старте пода Patroni выполняет следующие действия:
1.  Опрашивает DCS (Kubernetes API), чтобы узнать, есть ли в кластере активный лидер.
2.  Если лидера нет — инициирует выборы. Победитель делает `initdb` или восстанавливается из бэкапа WAL-G.
3.  Если лидер есть — настраивает текущий инстанс как реплику, используя `pg_basebackup` или `wal-g restore` (выбор зависит от объёма накопленных WAL: пороги `WALG_BACKUP_THRESHOLD_MEGABYTES` / `WALG_BACKUP_THRESHOLD_PERCENTAGE`).

## Предварительные требования

*   Кластер Kubernetes версии 1.27+ (матрица поддержки Zalando Postgres Operator v2.0.2; для bare Spilo более старые версии с API Endpoints v1 тоже работают).
*   **StorageClass** с динамическим выделением томов и `allowVolumeExpansion: true` (расширение диска без перезапуска пода).
*   Доступ к S3-совместимому хранилищу для бэкапов (например, self-hosted MinIO) — опционально, но необходимо для восстановления кластера из бэкапа.
*   Настроенные лимиты ресурсов на узлах (ориентир для Production: минимум 2 CPU и 4 ГБ RAM на инстанс).
*   Если `shared_buffers` не задан явно, Spilo автоматически рассчитывает его из лимита памяти пода (cgroup v2) — учитывайте это при тюнинге.

## Практические сценарии

### Шаг 1: Настройка прав доступа (RBAC)

Patroni должен иметь права на чтение/запись Endpoints или ConfigMaps для управления блокировкой лидера, а также на чтение подов для обнаружения членов кластера.

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
  resources: ["configmaps", "endpoints"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  # Обнаружение членов кластера
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
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

### Шаг 2: Конфигурация через переменные окружения

Spilo конфигурируется **исключительно переменными окружения** (полный список — в `ENVIRONMENT.rst` репозитория zalando/spilo). Произвольные параметры Patroni задаются через префикс `PATRONI_` (секции и ключи через подчёркивание), полный `patroni.yaml` можно передать через `SPILO_CONFIGURATION`. Монтируемый ConfigMap с `patroni.yaml` не используется: Spilo генерирует свою конфигурацию при старте.

| Переменная | Назначение |
| :--- | :--- |
| `SCOPE` | Имя кластера; все поды одного кластера должны иметь одинаковый `SCOPE`. Endpoints DCS именуется по нему |
| `DCS_ENABLE_KUBERNETES_API` | Непустое значение включает Kubernetes API как DCS |
| `KUBERNETES_USE_CONFIGMAPS` | Непустое значение переключает DCS с Endpoints на ConfigMaps |
| `PGVERSION` | Версия PostgreSQL в multi-version образе (`spilo-18` содержит 16/17/18; смена версии запускает in-place `pg_upgrade` при перезапуске пода) |
| `PGUSER_SUPERUSER` / `PGPASSWORD_SUPERUSER` | Учётные данные суперпользователя. **Дефолты `postgres`/`zalando` — обязательно переопределите из Secret** |
| `PGUSER_STANDBY` / `PGPASSWORD_STANDBY` | Пользователь репликации (дефолт `standby`/`standby` — тоже переопределите) |
| `PATRONI_<SECTION>_<KEY>` | Произвольные параметры Patroni, напр. `PATRONI_POSTGRESQL_PARAMETERS_MAX_CONNECTIONS` |
| `CALLBACK_SCRIPT` | Скрипт на события кластера (start/stop/restart/role change); получает имя кластера, строку подключения и действие |
| `PGROOT` / `PGDATA` | Расположение данных: по умолчанию `/home/postgres/pgroot` и `$PGROOT/pgdata` |
| `BACKUP_SCHEDULE` | Расписание базовых бэкапов WAL-G (по умолчанию `00 01 * * *` — ежедневно в 01:00 UTC) |
| `WALG_TMPDIR` | Временные файлы WAL-G; по умолчанию `PGROOT/../tmp` — нужно несколько ГБ свободного места |
| `ALLOW_NOSSL` | Разрешить клиентам подключаться без TLS (Spilo по умолчанию генерирует самоподписанные сертификаты) |

### Шаг 3: Спецификация StatefulSet (PostgreSQL 18)

Пример с актуальным образом Spilo-18, интеграцией бэкапов в S3-совместимое хранилище и экспортёром для Prometheus.

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
      application: spilo    # обязательная метка для Patroni
      version: pg-prod      # KUBERNETES_SCOPE_LABEL по умолчанию
  template:
    metadata:
      labels:
        application: spilo
        version: pg-prod
    spec:
      serviceAccountName: spilo-sa
      containers:
      - name: postgres
        image: "ghcr.io/zalando/spilo-18:4.1-p2"
        ports:
        - containerPort: 5432
        - containerPort: 8008 # Patroni REST API (самоподписанный TLS по умолчанию)
        env:
          - name: SCOPE
            value: "pg-prod"
          - name: DCS_ENABLE_KUBERNETES_API
            value: "true"
          - name: POD_NAMESPACE
            valueFrom: { fieldRef: { fieldPath: metadata.namespace } }
          - name: POD_NAME
            valueFrom: { fieldRef: { fieldPath: metadata.name } }
          - name: PGVERSION
            value: "18"
          - name: PGPASSWORD_SUPERUSER
            valueFrom: { secretKeyRef: { name: pg-prod-secrets, key: superuser-password } }
          - name: PGPASSWORD_STANDBY
            valueFrom: { secretKeyRef: { name: pg-prod-secrets, key: standby-password } }
          # Произвольные параметры Patroni/PostgreSQL
          - name: PATRONI_POSTGRESQL_PARAMETERS_MAX_CONNECTIONS
            value: "500"
          - name: PATRONI_POSTGRESQL_PARAMETERS_SHARED_BUFFERS
            value: "1GB"
          # PostgreSQL 18: прямой I/O для данных и WAL (требует поддержки ФС)
          - name: PATRONI_POSTGRESQL_PARAMETERS_IO_DIRECT
            value: "data,wal"
          # Бэкапы WAL-G в S3-совместимое хранилище (MinIO)
          - name: WALG_S3_PREFIX
            value: "s3://pg-prod-backups/pg-prod"
          - name: AWS_ENDPOINT
            value: "http://minio.minio-system.svc:9000"
          - name: AWS_S3_FORCE_PATH_STYLE
            value: "true"
          - name: AWS_ACCESS_KEY_ID
            valueFrom: { secretKeyRef: { name: walg-creds, key: access-key } }
          - name: AWS_SECRET_ACCESS_KEY
            valueFrom: { secretKeyRef: { name: walg-creds, key: secret-key } }
        resources:
          requests: { cpu: "2", memory: "4Gi" }
          limits: { cpu: "2", memory: "4Gi" } # QOS: Guaranteed
          # При использовании HugePages (настроенных на уровне узла):
          # limits: { hugepages-2Mi: "1Gi" }
        volumeMounts:
        - name: pgdata
          mountPath: /home/postgres/pgroot # PGROOT; PGDATA по умолчанию $PGROOT/pgdata
      # Экспортёр для Prometheus (v0.20.1, тестирован с PG 13–18)
      - name: exporter
        image: "prometheuscommunity/postgres-exporter:v0.20.1"
        env:
          # Не подключайте экспортёр от имени суперпользователя:
          # создайте пользователя с ролью pg_monitor
          - name: DATA_SOURCE_NAME
            value: "postgresql://monitoring:***@localhost:5432/postgres?sslmode=disable"
        ports:
        - containerPort: 9187
      # Anti-affinity: держать узлы кластера на разных нодах
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchLabels: { application: spilo, version: pg-prod }
              topologyKey: kubernetes.io/hostname
  volumeClaimTemplates:
  - metadata: { name: pgdata }
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "<storage-class-name>" # StorageClass с allowVolumeExpansion: true
      resources: { requests: { storage: 100Gi } }
```

**Про HugePages:** `vm.nr_hugepages` — node-wide (unsafe) sysctl, его нельзя задать в `securityContext.sysctls` пода и нельзя безопасно менять из initContainer (это повлияет на все поды на узле). Настраивайте HugePages на уровне узлов (kubelet/node tuning) и запрашивайте ресурс `hugepages-2Mi` в лимитах пода; параметр PostgreSQL `huge_pages` (по умолчанию `try`) подключит их автоматически.

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
  selector: { application: spilo, version: pg-prod }
  ports: [{ port: 5432, name: postgres }]
---
# 2. Master Service (Запись)
# Patroni динамически обновляет Endpoints с именем, совпадающим с SCOPE,
# добавляя туда только IP лидирующего пода (при DCS_ENABLE_KUBERNETES_API
# без KUBERNETES_USE_CONFIGMAPS)
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
# Селектор по метке роли, которую ставит сам Patroni (spilo-role: replica)
apiVersion: v1
kind: Service
metadata:
  name: pg-prod-repl
spec:
  selector:
    application: spilo
    version: pg-prod
    spilo-role: replica
  ports: [{ port: 5432 }]
```

### Шаг 5: TLS (опционально)

Spilo по умолчанию генерирует самоподписанные сертификаты для клиентских подключений (`/run/certs/server.crt`) и REST API (`/run/certs/restapi.crt`). Для production вместо самоподписанных можно передать свои сертификаты **содержимым** через переменные (значения удобно подставлять из Secret):

```yaml
- name: SSL_CERTIFICATE
  valueFrom: { secretKeyRef: { name: pg-tls, key: server.crt } }
- name: SSL_PRIVATE_KEY
  valueFrom: { secretKeyRef: { name: pg-tls, key: server.key } }
- name: SSL_CA
  valueFrom: { secretKeyRef: { name: pg-tls, key: ca.crt } }
```

Клиенты при этом подключаются с `sslmode=verify-full`. Для внутреннего трафика без TLS задайте `ALLOW_NOSSL: "true"`.

## Валидация и проверка

1.  **Проверка состояния кластера:**
    ```bash
    kubectl exec -it pg-prod-0 -c postgres -- patronictl list pg-prod
    # → Таблица узлов; ровно один Leader (State: running), остальные Replica
    ```
2.  **Проверка лидера через DCS (Endpoints):**
    ```bash
    kubectl get endpoints pg-prod -o yaml
    # → subsets.addresses содержит IP ровно одного пода (текущий лидер);
    #   при смене лидера IP меняется атомарно вместе с аннотациями
    ```
3.  **Проверка меток роли:**
    ```bash
    kubectl get pods -l spilo-role=master
    # → Ровно один под: pg-prod-0
    kubectl get pods -l spilo-role=replica
    # → Остальные поды кластера
    ```
4.  **Проверка готовности Postgres:**
    ```bash
    kubectl exec -it pg-prod-0 -c postgres -- pg_isready
    # → /var/run/postgresql:5432 - accepting connections
    ```
5.  **Проверка бэкапов WAL-G:**
    ```bash
    kubectl exec -it pg-prod-0 -c postgres -- \
      envdir "/run/etc/wal-e.d/env" wal-g backup-list
    # → Список базовых бэкапов с timestamp и размером
    ```
6.  **Логика бэкапа:** логи контейнера содержат записи `pg_basebackup`/`wal-g` по расписанию `BACKUP_SCHEDULE` (по умолчанию 01:00 UTC).

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` на `/home/postgres/pgroot` | Неверный `fsGroup` или права на Volume. | Установите `securityContext.fsGroup`, совпадающий с uid пользователя `postgres` в образе (проверьте: `kubectl exec pg-prod-0 -c postgres -- id postgres`). |
| Кластер не выбирает лидера | Отсутствие прав RBAC на Endpoints/ConfigMaps или отсутствие обязательной метки `application: spilo` на подах. | Проверьте `kubectl describe role spilo-role` и `kubectl get pod pg-prod-0 --show-labels`. |
| Поды не видят друг друга; в логах `running as a standalone` | Patroni не может достичь Kubernetes API (DCS) — опасный сигнал, узел изолирован от кластера. | Проверьте доступность API Kubernetes и ServiceAccount. См. **[Split Brain в Patroni](../Concepts/high_availability.md)**. |
| `Stale leader lock` | Сбой DCS или сетевой лаг. | Проверьте доступность API Kubernetes. Удалите зависший Endpoint вручную. |
| `Streaming replication has stopped` | Реплика слишком сильно отстала. | Patroni автоматически перезапустит клонирование через `pg_basebackup` или `wal-g restore`. |
| REST API недоступен по `http://...:8008` | Spilo по умолчанию включает TLS для REST API (самоподписанный сертификат). | Используйте `https://...:8008` (при проверке `curl -k`) или задайте `ALLOW_NOSSL: "true"`. |
| WAL-G: ошибки 403/404 при выгрузке | Неверный endpoint или стиль адресации для S3-совместимого хранилища. | Проверьте `AWS_ENDPOINT` и `AWS_S3_FORCE_PATH_STYLE=true` для MinIO и аналогов. |

## Пограничные случаи и ограничения

### Обновление мажорной версии
Образы Spilo multi-version: `spilo-18` содержит PostgreSQL 16, 17 и 18. Смена переменной `PGVERSION` (например, `17` → `18`) с последующим перезапуском пода запускает **in-place `pg_upgrade`** (механизм, начиная со Spilo 13, используется и оператором). Смена только тега образа без смены `PGVERSION` апгрейда не запустит. Для сложных миграций (в т.ч. логической репликацией) см. **[Миграция без простоя](./zero_downtime_migration.md)**.

### Восстановление из бэкапа (Bootstrap)
Если кластер новый, но нужно восстановить данные из WAL-G-архива, добавьте в `env` переменные с префиксом `CLONE_` (правило: все переменные конфигурации хранилища бэкапов копируются с префиксом `CLONE_`) и укажите метод:
```yaml
- name: CLONE_METHOD
  value: "CLONE_WITH_WAL_G"
- name: CLONE_WALG_S3_PREFIX
  value: "s3://pg-prod-backups/pg-prod"
- name: CLONE_AWS_ENDPOINT
  value: "http://minio.minio-system.svc:9000"
- name: CLONE_AWS_ACCESS_KEY_ID
  valueFrom: { secretKeyRef: { name: walg-creds, key: access-key } }
- name: CLONE_AWS_SECRET_ACCESS_KEY
  valueFrom: { secretKeyRef: { name: walg-creds, key: secret-key } }
- name: CLONE_TARGET_TIMELINE # опционально: timeline бэкапа, по умолчанию latest
  value: "latest"
```

### Стандартные пароли
Spilo стартует со стандартными учётными данными (`postgres`/`zalando` для суперпользователя, `standby`/`standby` для репликации, `admin`/`cola` для администратора). В Production всегда переопределяйте `PGPASSWORD_*` из Secret — иначе любой, кто знает образ, получит доступ к кластеру.

## Лучшие практики

**PodDisruptionBudget** — гарантирует доступность при плановых операциях (дренаж нод, обновления):
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: pg-prod-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels: { application: spilo, version: pg-prod }
```

- **Динамическая конфигурация Patroni** (`ttl`, `loop_wait`, `retry_timeout`, `maximum_lag_on_failover`) хранится в DCS и применяется на всех узлах — меняйте её через `patronictl edit-config pg-prod`, а не в манифестах. `maximum_lag_on_failover` защищает от промоции отстающей реплики.
- **Мониторинг:** помимо `postgres-exporter` (9187), Patroni экспортирует метрики Prometheus на порту 8008 (`/metrics`) и JSON-статус кластера (`/patroni`) — можно скрейпить напрямую.
- **Бэкапы с реплик:** `WALG_BACKUP_FROM_REPLICA=true` снимает базовые бэкапы с реплик, разгружая лидера.
- **WALG_TMPDIR:** держите временную директорию WAL-G на томе с запасом в несколько ГБ — при больших базах промежуточные файлы значительны.
- **SRE чек-лист:**
  - [ ] Настроен **PodDisruptionBudget** (`minAvailable: 1`).
  - [ ] Настроена **Anti-Affinity** (по `kubernetes.io/hostname`).
  - [ ] Переопределены стандартные пароли (`PGPASSWORD_SUPERUSER`, `PGPASSWORD_STANDBY`).
  - [ ] Поды несут обязательные метки `application: spilo` и `version: <SCOPE>`.
  - [ ] StorageClass поддерживает `allowVolumeExpansion: true`.
  - [ ] Настроен алертинг на `pg_static_replication_lag` и на статус Patroni (`/patroni` → `state`).

## Дополнительная информация

### Связанные документы
- **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — теория Patroni, Watchdog и Split-Brain.
- **[Zalando Postgres Operator](./zalando_postgres_operator.md)** — автоматизированная альтернатива (CRD-манифесты, PgBouncer, логические бэкапы).
- **[PostgreSQL в Kubernetes (CloudNativePG)](./kubernetes_deployment.md)** — альтернативный оператор.
- **[Наблюдаемость PostgreSQL](./observability.md)** — дашборды и алертинг.
- **[Сетевая связность](./kubernetes_connectivity.md)** — работа с сервисами в K8s.
- **[Автоматизация бэкапов](./backup_automation.md)** — теория WAL-G и PITR.

**Внешние источники:** [Spilo ENVIRONMENT.rst](https://github.com/zalando/spilo/blob/master/ENVIRONMENT.rst) — полный список переменных окружения; [Patroni: Using Patroni with Kubernetes](https://patroni.readthedocs.io/en/latest/kubernetes.html) — режимы Endpoints/ConfigMaps.

**Инструменты:** `Spilo`, `Patroni`, `WAL-G`, `postgres-exporter`, `kubectl`, `patronictl`.
