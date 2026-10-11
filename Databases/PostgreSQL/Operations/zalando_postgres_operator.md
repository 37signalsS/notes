# Zalando Postgres Operator

**Актуально для:** Postgres Operator v2.0.3 (PostgreSQL 14–18, Kubernetes 1.27+, Helm v3)

## Определения

**Postgres Operator** — Kubernetes-оператор с открытым исходным кодом (github.com/zalando/postgres-operator) для автоматизации полного жизненного цикла кластеров PostgreSQL. Реализует паттерн контроллера: следит за пользовательским ресурсом `postgresql` (CRD) и приводит текущее состояние кластера в соответствие с декларативным описанием в манифесте. Конфигурируется только через манифесты — не требуется прямого доступа к API Kubernetes из CI/CD.

**CRD `postgresql`** — пользовательский ресурс кластера. Группа API — **`acid.zalan.do/v1`**, kind — `postgresql` (plural `postgresqls`, сокращение `pg`). Оператор регистрирует его самостоятельно при старте (опция `enable_crd_registration`); при установке через Helm CRD нужно обновить из папки `crds/` **до** обновления чарта.

**OperatorConfiguration** — второй CRD (`acid.zalan.do/v1`) для глобальной конфигурации оператора (альтернатива ConfigMap `postgres-operator`). Создаётся только если в деплойменте оператора задана переменная `POSTGRES_OPERATOR_CONFIGURATION_OBJECT`.

**Spilo** — специализированный образ от Zalando (github.com/zalando/spilo), объединяющий PostgreSQL, Patroni и инструменты эксплуатации (WAL-G, `pg_view` и др.). Spilo — движок оператора; образ задаётся глобально опцией `docker_image` и переопределяется для кластера через `spec.dockerImage`. Подробнее — **[Spilo: манифесты без оператора](./zalando_spilo_manifests.md)**.

**Patroni** — агент HA внутри Spilo (PID 1): выбор лидера, репликация, автоматический failover. Теория работы — **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)**.

**DCS (Distributed Configuration Store)** — хранилище координации Patroni. Оператор использует нативный **Kubernetes API**: ресурсы ConfigMaps (по умолчанию с v2.0) или Endpoints, именованные по имени кластера. Внешний etcd не требуется. КонфигMaps именуются `<cluster>-config`, `<cluster>-failover`, `<cluster>-leader`.

**PostgresTeam** — CRD (`acid.zalan.do/v1`, kind `PostgresTeam`) глобального маппинга команд: `additionalTeams` (члены другой команды получают роли во всех кластерах команды), `additionalSuperuserTeams`, `additionalMembers` (отдельные пользователи), «виртуальные команды». Включается операторной опцией `enable_postgres_team_crd: true` (по умолчанию выключено). Это **не** механизм делегирования управления кластером, а маппинг членства в командах на PostgreSQL-роли.

**PgBouncer pooler** — встроенный пул соединений, который оператор разворачивает отдельным Deployment с сервисом `{cluster-name}-pooler`.

## Основные концепции

### Цикл управления

1. **Control Loop**: оператор опрашивает Kubernetes API на предмет изменений ресурсов `postgresql` и приводит порождённые объекты (StatefulSet, Services, Secrets, PDB, ConfigMaps Patroni) в соответствие с манифестом.
2. **Два типа сканов**: `sync scan` каждые `resync_period` секунд для каждого кластера и `repair scan` каждые `repair_period` только для кластеров, у которых последняя операция завершилась неуспешно.
3. **Обновление StatefulSet**: замена StatefulSet (и rolling update) при изменении контейнера, образа, ресурсов, env, labels, affinity и т. п.; простая замена без rolling update при изменении annotations, volumeClaimTemplates и template volumes. Есть «ленивое» обновление образа Spilo (`enable_lazy_spilo_upgrade`): StatefulSet обновляется без перезапуска подов — полезно, если поды всё равно будут перезапущены позже (ротация нод).
4. **Роли и секреты**: оператор создаёт PostgreSQL-роли из секции `users`, базы из `databases`/`preparedDatabases` и хранит автоматически сгенерированные пароли в секретах вида `{username}.{clustername}.credentials.postgresql.acid.zalan.do`.

### Сравнение с CloudNativePG (CNPG)

| Характеристика | Zalando Postgres Operator | CloudNativePG |
| :--- | :--- | :--- |
| **Движок HA** | Patroni внутри подов (PID 1), DCS через K8s API (ConfigMaps) | Instance Manager снаружи, встроенный DCS оператора |
| **Конфигурация** | CRD `postgresql` (`acid.zalan.do/v1`) | CRD `CloudNativePG` |
| **Бэкапы** | WAL-G через Spilo + логические бэкапы (CronJob) | volume snapshots + бэкапы оператором |
| **Пул соединений** | Встроенный PgBouncer (Deployment) | Внешний пул (нужно разворачивать отдельно) |
| **Особенности** | Многолетняя эксплуатация в Zalando, веб-UI, prepared databases с ролями | Современная кодовая база, снапшоты томов |

Сравнение со стороны CNPG и сценарии миграции — в **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)**.

## Предварительные требования

- **Kubernetes 1.27+**, `kubectl`, Helm v3 (для чарта; Helm v2 поддержка удалена в v1.8.0).
- **RBAC**: манифест `operator-service-account-rbac.yaml` задаёт ServiceAccount, ClusterRoles и биндинги оператора, включая ClusterRole `postgres-pod` с правами Patroni на поды и Endpoints/ConfigMaps.
- **StorageClass** с динамическим выделением томов и `allowVolumeExpansion: true` (для онлайн-расширения диска).
- **S3-совместимое объектное хранилище** (например, self-hosted MinIO) — опционально, но необходимо для WAL-архивирования, клонирования и PITR.
- Имя кластера — не более **53 символов**; при включённой операторной опции `enable_team_id_clustername_prefix` оно должно начинаться с `teamId-`.
- Минимальные лимиты ресурсов, которые оператор гарантирует сам: **250m CPU / 250Mi memory** на под.

## Практические сценарии

### 1. Установка оператора

**Вариант A — Helm (рекомендуется):**

```bash
# Подключение репозитория (чарты также доступны через ghcr.io:
# ghcr.io/zalando/charts/postgres-operator:2.0.3)
helm repo add postgres-operator-charts \
  https://opensource.zalando.com/postgres-operator/charts/postgres-operator
helm repo update

# Установка с фиксацией версии
helm install postgres-operator postgres-operator-charts/postgres-operator \
  --namespace postgres-operator \
  --create-namespace \
  --version 2.0.3
```

**Вариант B — манифесты (порядок важен):**

```bash
kubectl create -f manifests/configmap.yaml                  # конфигурация
kubectl create -f manifests/operator-service-account-rbac.yaml  # RBAC
kubectl create -f manifests/postgres-operator.yaml          # деплоймент
kubectl create -f manifests/api-service.yaml                # API для UI
# или одним шагом через kustomize:
kubectl apply -k github.com/zalando/postgres-operator/manifests
```

**Проверка запуска** (селектор зависит от способа установки):

```bash
kubectl get pod -l name=postgres-operator                          # манифесты
kubectl get pod -l app.kubernetes.io/name=postgres-operator       # Helm
```

**Веб-UI** (опционально): `helm install postgres-operator-ui postgres-operator-ui-charts/postgres-operator-ui`, затем `kubectl port-forward svc/postgres-operator-ui 8081:80` → `http://localhost:8081`. UI требует доступности REST API оператора через сервис из `api-service.yaml`.

Оператор следит за namespace, в котором развёрнут (переопределение: `WATCHED_NAMESPACE` в env или `watched_namespace` в конфигурации; значение `*` — все namespace, но тогда нужны права во всех них).

### 2. Минимальный манифест кластера

Обязательные поля: `teamId`, `numberOfInstances`, `postgresql.version`, `volume.size`.

```yaml
apiVersion: "acid.zalan.do/v1"   # группа API CRD этого оператора (postgresql.zalando.com — не группа данного оператора)
kind: postgresql
metadata:
  name: acid-minimal-cluster
spec:
  teamId: "acid"
  numberOfInstances: 2
  volume:
    size: 1Gi
  postgresql:
    version: "18"   # поддерживаются 14–18
  users:
    zalando:        # владелец баз
    - superuser
    - createdb
    foo_user: []    # роль без прав (логин по умолчанию)
  databases:
    foo: zalando    # база foo, владелец zalando (должен быть объявлен в users)
```

### 3. Production-манифест

```yaml
apiVersion: "acid.zalan.do/v1"
kind: postgresql
metadata:
  name: data-acid-prod
  labels:
    application: billing
spec:
  teamId: "acid"
  numberOfInstances: 3

  postgresql:
    version: "16"
    parameters:
      shared_buffers: "2GB"
      max_connections: "500"

  # Тюнинг Patroni (значения по умолчанию задаются образом Spilo)
  patroni:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 33554432   # 32 MiB в байтах: не промотировать отстающую реплику

  volume:
    size: "200Gi"
    storageClass: "ssd-storage"

  resources:
    requests: {cpu: "2", memory: "4Gi"}
    limits:   {cpu: "4", memory: "8Gi"}

  # Роли и базы
  users:
    billing_user: [createdb]
  databases:
    billing_db: billing_user
  preparedDatabases:
    reporting:
      schemas:
        data: {}        # схемы с ролями *_owner/_reader/_writer

  # Пул соединений PgBouncer
  enableConnectionPooler: true
  connectionPooler:
    numberOfInstances: 2
    mode: "transaction"   # или session
    maxDBConnections: 100 # делится между подами pooler
    resources:
      requests: {cpu: "500m", memory: "100Mi"}
      limits:   {cpu: "1", memory: "512Mi"}

  # Логические бэкапы (SQL-дампы через CronJob)
  enableLogicalBackup: true
  logicalBackupSchedule: "00 02 * * *"

  # Окно обслуживания (UTC): апгрейды и миграция мастер-пода
  maintenanceWindows:
  - "01:00-06:00"

  # Размещение: отдельные ноды + распределение по зонам
  tolerations:
  - key: postgres
    operator: Exists
    effect: NoSchedule
  topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule

  # Дополнительный контейнер (например, экспортёр для Prometheus)
  sidecars:
  - name: exporter
    image: "prometheuscommunity/postgres-exporter:v0.20.1"
    env:
    - name: DATA_SOURCE_NAME
      value: "postgresql://monitoring:***@localhost:5432/postgres?sslmode=require"
```

Пользовательские переменные окружения для подов БД задаются секциями `env`/`envFrom` в манифесте (приоритет выше операторной конфигурации); приоритет полностью: оператор → `env` манифеста → секция `clone` → секция `standby` → pod environment secret/configmap → настройки WAL/логических бэкапов.

### 4. Подключение к кластеру

```bash
# Имя мастер-пода по меткам (Patroni ставит метку spilo-role=master)
export PGMASTER=$(kubectl get pods -o jsonpath={.items..metadata.name} \
  -l application=spilo,cluster-name=data-acid-prod,spilo-role=master)

kubectl port-forward $PGMASTER 6432:5432

# Пароль суперпользователя — из секрета (нешифрованные подключения отклоняются,
# поэтому PGSSLMODE=require обязателен)
export PGPASSWORD=$(kubectl get secret \
  postgres.data-acid-prod.credentials.postgresql.acid.zalan.do \
  -o 'jsonpath={.data.password}' | base64 -d)
export PGSSLMODE=require
psql -U postgres -h localhost -p 6432
```

Пароли манифестных ролей шифруются **scram-sha-256** (default с v2.0; для совместимости pooler с `md5` задайте `password_encryption: md5` в `spec.postgresql.parameters` — требует перезапуска оператора).

### 5. WAL-архивирование и логические бэкапы

**WAL-архивирование** (физические бэкапы через WAL-G в Spilo): базовый бэкап nightly 01:00 UTC, ротация `BACKUP_NUM_TO_RETAIN: 5`. Для S3-совместимого хранилища (MinIO) задайте в конфигурации оператора `wal_s3_bucket` и endpoint, либо переопределите через `env` манифеста:

```yaml
spec:
  env:
  - name: wal_s3_bucket
    value: "s3://pg-backups/data-acid-prod"
  - name: s3_endpoint
    value: "http://minio.minio-system.svc:9000"
  - name: s3_force_path_style
    value: "true"
  - name: s3_access_key_id
    valueFrom: {secretKeyRef: {name: walg-creds, key: access-key}}
  - name: s3_secret_access_key
    valueFrom: {secretKeyRef: {name: walg-creds, key: secret-key}}
```

**Логические бэкапы**: `enableLogicalBackup: true` создаёт синхронизируемый CronJob. Из-за ограничений K8s CronJob (пропуск при простое) настройте отдельный мониторинг выполнения. Доступны `logicalBackupSchedule` и `logicalBackupRetention` (ретеншн старых дампов).

Теория бэкапов и PITR — **[Автоматизация бэкапов](./backup_automation.md)**; переменные WAL-G в Spilo — **[Spilo: манифесты](./zalando_spilo_manifests.md)**.

### 6. Клонирование и PITR

**Клон из WAL-архива** (рекомендуется: нет нагрузки на прод): поле `timestamp` (RFC 3339, **таймзона обязательна**, восстановление невключительно — до указанного момента) заставляет оператора идти в хранилище, а не в живой кластер; `uid` нужен для уникальности пути в бакете.

```bash
# UID исходного кластера:
kubectl get postgresql data-acid-prod -o jsonpath={.metadata.uid}
```

```yaml
apiVersion: "acid.zalan.do/v1"
kind: postgresql
metadata:
  name: data-acid-prod-clone
spec:
  teamId: "acid"
  numberOfInstances: 1
  postgresql:
    version: "18"   # при клонировании версия должна быть >= версии источника
  clone:
    cluster: "data-acid-prod"
    uid: "efd12e58-5786-11e8-b5a7-06148230260c"
    timestamp: "2026-08-15T10:00:00+00:00"
    # для S3-совместимого хранилища (MinIO и аналоги):
    s3_wal_path: "s3://pg-backups/data-acid-prod"
    s3_endpoint: "http://minio.minio-system.svc:9000"
    s3_force_path_style: true
  volume:
    size: "200Gi"
```

**Прямой клон** (pg_basebackup с живого кластера): секция `clone` без `timestamp` — оператор подключается к сервису источника (только кластеры в одном namespace, нагрузка на источник растёт).

**Restore in place** (без смены имени): удалите ресурс `postgresql` и создайте новый с **тем же именем**, указав в `clone` это же имя и **оригинальный UID** + `timestamp`. Бэкапы исходного кластера сохраняются под старым UID — сначала лучше сделать временный клон для выбора точки восстановления.

### 7. Standby-кластер (DR) и promote

```yaml
spec:
  standby:
    standby_host: "data-acid-prod.database.svc"   # или s3_wal_path для потока из архива
    standby_port: "5432"
    standby_primary_slot_name: "dr_slot"          # опционально
```

- Источником может быть удалённый мастер, WAL-архив (`s3_wal_path`) или их комбинация; версия PostgreSQL должна совпадать.
- Standby read-only; лидер standby помечается меткой `spilo-role=master`.
- При `standby_host` нужно скопировать учётные данные из секретов источника (иначе поды не стартуют: пароли в БД не совпадают с секретами).
- **Promote**: удалите секцию `standby` из манифеста — rolling update уберёт `STANDBY_*` переменные, Patroni промотирует кластер.

### 8. Обновление версий PostgreSQL

**Minor-апгрейд**: оператор обновляет образ Spilo и выполняет rolling update со switchover (обычно < 5 секунд; клиенты переподключаются).

**Major-апгрейд (in-place `pg_upgrade`)**: измените `postgresql.version` в манифесте. Режим задаётся операторной опцией `major_version_upgrade_mode`:
- `manual` (default) — оператор обновляет `PGVERSION` в подах; при заданных `maintenanceWindows` ротация подов откладывается до окна, иначе запускается rolling update; сам `pg_upgrade` выполняет скрипт Spilo при старте.
- `off` — апгрейд вручную из мастер-пода: `python3 /scripts/inplace_upgrade.py <N>`, где N — число инстансов (`numberOfInstances`).
- `full` — автоматический апгрейд всех кластеров ниже `minimal_major_version` до `major_target_version` (оператор не правит версию в манифесте — возможен drift).

Успех/неудача фиксируются аннотациями `last-major-upgrade-success` / `last-major-upgrade-failure`; при неудаче оператор не ретраит апгрейд, пока версию в манифесте не откатят к текущей. **Откат после `pg_upgrade` невозможен** — сначала тестируйте на клоне (см. п. 6). Окно обслуживания должно быть не короче чем 2× `resync_period`.

### 9. Онлайн-расширение тома

Измените `volume.size` и примените манифест — оператор скорректирует PVC без rolling update. **Сужение не поддерживается** (оператор выдаст предупреждение).

### 10. TLS-сертификаты

По умолчанию Spilo генерирует самоподписанные сертификаты (проверка клиентом невозможна, MITM возможен). Для production задайте свой сертификат через секрет:

```bash
kubectl create secret tls pg-tls --key tls.key --cert tls.crt
# опционально CA:
kubectl create secret generic pg-tls-ca --from-file=ca.crt=ca.crt
```

```yaml
spec:
  tls:
    secretName: "pg-tls"
    caSecretName: "pg-tls-ca"
    caFile: "ca.crt"     # клиенты подключаются с sslmode=verify-ca/verify-full
```

Требуется настроить `spilo_fsgroup` (в образе Spilo по умолчанию GID 103) или `spiloFSGroup` в манифесте. Совместим с cert-manager. Spilo проверяет изменение сертификатов каждые 5 минут и перезагружает PostgreSQL.

## Операции и команды

| Задача | Команда |
| :--- | :--- |
| Список кластеров (Team, Version, Pods, Volume, CPU/Memory-Request, Age, Status) | `kubectl get postgresql` |
| События кластера | `kubectl describe postgresql data-acid-prod` |
| Топология подов | `kubectl get pods -l application=spilo -L spilo-role` |
| Статус Patroni (внутри пода) | `kubectl exec -it data-acid-prod-0 -c postgres -- patronictl list` |
| Switchover | `kubectl exec -it data-acid-prod-0 -c postgres -- patronictl switchover` |
| Логи мастер-пода | `kubectl logs data-acid-prod-0 -c postgres` |
| Логи оператора | `kubectl logs -l name=postgres-operator` |
| Масштабирование | изменить `spec.numberOfInstances` → `kubectl apply` |
| Удаление кластера | `kubectl delete postgresql data-acid-prod` |

При удалении кластера оператор удаляет StatefulSet, поды, Services, Endpoints/ConfigMaps и PDB; **секреты с паролями и бэкапы остаются** (секреты удаляются только при `enable_secrets_deletion: true`). Если ресурс удалён во время старта кластера, могут остаться орфанные объекты — удалите их вручную.

**Валидация** после создания:

```bash
kubectl get postgresql
# → Status: Running (CreateFailed означает, что кластер с таким именем уже существует —
#   безопасно пересоздать манифест, оператор не заменяет существующий кластер)

kubectl get pods -l application=spilo -L spilo-role
# → ровно один под с spilo-role=master, остальные — replica

kubectl exec -it data-acid-prod-0 -c postgres -- pg_isready
# → /var/run/postgresql:5432 - accepting connections
```

## Устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Status: CreateFailed** | Кластер с таким именем уже существует (или ошибка валидации манифеста / нехватка RBAC). | `kubectl describe postgresql <name>` — события; проверьте логи оператора. Пересоздание манифеста безопасно. |
| **Поды в Pending** | Недостаточно CPU/RAM на нодах, нет подходящего PV/StorageClass. | `kubectl describe pod`; проверьте StorageClass и лимиты (минимум 250m/250Mi). |
| **Split-brain при миграции v1→v2** | Одновременно существуют лидерский Endpoints и ConfigMap во время rolling update. | Мигрируйте по процедуре из «Пограничных случаев»: сначала scale-in до 1 инстанса, затем включение `kubernetes_use_configmaps`, затем scale-out. |
| **Pooler не подключается после апгрейда до v2** | v2 по умолчанию шифрует пароли scram-sha-256, а pooler ожидает md5. | `password_encryption: "md5"` в `spec.postgresql.parameters` + перезапуск оператора. |
| **Standby не стартует** | Несовпадение учётных данных в секретах standby и источника. | Скопируйте секреты источника или дайте оператору создать и пропатчить их (см. п. 7). |
| **Логический бэкап не выполняется** | CronJob ограничен K8s (пропуск при простое) или нет хранилища. | Проверьте `kubectl get cronjob`, логи job; настройте мониторинг выполнения. |
| **Major upgrade не запускается** | Аннотация `last-major-upgrade-failure` или нет окна обслуживания. | Откатите версию в манифесте к текущей (снимет аннотацию), проверьте `maintenanceWindows`. |

## Пограничные случаи

**Миграция v1.x → v2 (breaking changes):**
1. **`kubernetes_use_configmaps` теперь true по умолчанию** (Endpoints deprecated в K8s 1.33). Безопасная миграция: (1) scale-in всех кластеров до 1 инстанса (`max_instances`/`min_instances` = 1), (2) включить `kubernetes_use_configmaps: true` (триггерит ротацию мастер-пода — простой), (3) scale-out обратно, (4) удалить осиротевшие Endpoints. Прямое переключение с репликами рискует split-brain.
2. **scram-sha-256 по умолчанию** — убедитесь, что клиенты и драйверы поддерживают его; для md5-pooler задайте `password_encryption: md5`.
3. **Удалённые поля манифеста**: `init_containers` → `initContainers`, `pod_priority_class_name` → `podPriorityClassName`, `replicaLoadBalancer` → `enableReplicaLoadBalancer`, `useLoadBalancer` → `enableMasterLoadBalancer`.
4. Убрана поддержка PostgreSQL 13, helm-чарта 1.10.1, kubectl-pg plugin; образы больше не публикуются в `registry.opensource.zalan.do` (только `ghcr.io`).

Прочие ограничения и особенности:
- **Volume**: только расширение; сужение — вручную через удаление PVC (под при этом зависает, удаляйте по одному).
- **Sidecars/initContainers**: включаются операторными опциями `enable_sidecars` / `enable_init_containers`; sidecar получает `POD_NAME`, `POD_NAMESPACE`, `POSTGRES_USER`, `POSTGRES_PASSWORD` и разделяет том БД (`/home/postgres/pgdata`); доступ к сокету PostgreSQL — через `share_pgsocket_with_sidecars`.
- **Owner references и finalizers выключены по умолчанию** (`enable_owner_references`, `enable_finalizers`): при сбое синхронизации удаление манифеста может оставлять орфанные ресурсы; финализеры добавляют задержку в два цикла SYNC.
- **Защита от удаления**: опции `delete_annotation_date_key` / `delete_annotation_name_key` — оператор откажет в удалении кластера без аннотаций с именем кластера и текущей датой (YYYY-MM-DD) в манифесте.
- **Множественные операторы**: `CONTROLLER_ID` в env оператора + аннотация `"acid.zalan.do/controller": "<id>"` в манифесте — оператор управляет только «своими» кластерами.
- **Минимальные лимиты** 250m CPU / 250Mi memory поднимаются оператором автоматически; HugePages — через `resources.requests/limits` (`hugepages-2Mi`).
- **Ротация паролей** в секретах: `enable_password_rotation` (интервал `password_rotation_interval`, default 90 дней) + `usersWithSecretRotation` / `usersWithInPlaceSecretRotation` / `usersIgnoringSecretRotation` в манифесте.

## Лучшие практики

- **PDB**: оператор создаёт два PDB — primary (`minAvailable: 1`, защита последнего инстанса) и critical-operations (`maxUnavailable: 0`, метка `critical-operation=true` во время апгрейдов). Не отключайте (`enable_pod_disruption_budget`) без крайней необходимости.
- **Anti-affinity**: включите `enable_pod_antiaffinity` (топология `kubernetes.io/hostname` по умолчанию) или `topologySpreadConstraints` по зонам — иначе все поды кластера могут оказаться на одной ноде.
- **Maintenance windows** задавайте не короче 2× `resync_period` и проводите в них мажорные апгрейды и миграцию мастер-пода.
- **Мониторьте CronJob логических бэкапов** отдельно — K8s CronJob молча пропускает запуски.
- **Защищайте удаление** аннотациями (см. пограничные случаи) и делайте бэкап перед мажорным апгрейдом; тестируйте апгрейд на клоне.
- **Не используйте дефолтные пароли Spilo** (`postgres`/`zalando`): оператор генерирует собственные пароли в секретах, но при прямых манифестах Spilo — переопределяйте (см. **[Spilo: манифесты](./zalando_spilo_manifests.md)**).
- **Откат оператора**: измените образ в деплойменте на предыдущий тег (`ghcr.io/zalando/postgres-operator:v<prev>`); CRD и манифесты кластеров при этом не затрагиваются.

## Дополнительная информация

### Смотрите также

* **[Spilo: манифесты без оператора](./zalando_spilo_manifests.md)** — тот же стек через прямые StatefulSet-манифесты (переменные окружения Spilo, DCS Endpoints/ConfigMaps).
* **[PostgreSQL в Kubernetes (CloudNativePG)](./kubernetes_deployment.md)** — альтернативный оператор и сравнение.
* **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — теория Patroni, Watchdog, split-brain.
* **[Автоматизация бэкапов](./backup_automation.md)** — теория WAL-G и PITR.
* **[Наблюдаемость PostgreSQL](./observability.md)** — дашборды и алертинг.
* **[Тюнинг производительности](./performance_tuning.md)** — параметры `postgresql.parameters`.

**Внешние источники:** [официальная документация](https://opensource.zalando.com/postgres-operator/) (quickstart, user guide, administrator guide, [референс манифеста](https://opensource.zalando.com/postgres-operator/docs/reference/cluster_manifest.html), [референс параметров оператора](https://opensource.zalando.com/postgres-operator/docs/reference/operator_parameters.html)), [миграция v1→v2](https://opensource.zalando.com/postgres-operator/docs/migrate.html), [releases](https://github.com/zalando/postgres-operator/releases).

**Инструменты:** `Postgres Operator`, `Spilo`, `Patroni`, `WAL-G`, `PgBouncer`, `kubectl`, `Helm`.
