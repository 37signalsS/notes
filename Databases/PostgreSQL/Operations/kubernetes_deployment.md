# PostgreSQL в Kubernetes (CloudNativePG)

**Актуально для:** CloudNativePG 1.30.x (текущий релиз 1.30.1, сентябрь 2026; 1.28.x — EOL, финальный релиз 1.28.4; 1.29.x — поддерживается, текущий патч 1.29.3), PostgreSQL 14–18 (версия по умолчанию в операторе 1.30 — 18.4, поддержка 14 EOL 12.11.2026), Kubernetes 1.34–1.36 (оператор 1.30 поддерживает 1.34, 1.35, 1.36). Нативная интеграция бэкапов в object storage (`barmanObjectStore`) deprecated с 1.26 в пользу CNPG-I плагина (Barman Cloud Plugin).

## Определения

**CloudNativePG (CNPG)** — Kubernetes-оператор с открытым исходным кодом (CNCF Sandbox, изначально разработан EDB) для полного жизненного цикла кластеров PostgreSQL: bootstrapping, конфигурация, высокая доступность, failover, бэкапы и подключение. В отличие от Patroni, не требует внешнего DCS — координация идёт через Kubernetes API.

**Instance Manager** — процесс на Go, работающий как PID 1 в каждом пода PostgreSQL вместо стандартного `init`. Мониторит локальную БД, управляет конфигурацией и выполняет команды оператора — без SSH и sidecar-процессов.

**Декларативное управление (Reconciliation Loop)** — администратор описывает желаемое состояние в YAML-ресурсе (`Cluster`), оператор непрерывно приводит текущее состояние к целевому.

**Volume Snapshot** — мгновенная копия тома на уровне CSI. CNPG использует снапшоты для бэкапов (без object storage) и для seed-инга новых кластеров из существующих данных.

**CNPG-I (CloudNativePG Interface)** — плагинный интерфейс для бэкапов; официально поддерживаемый плагин — Barman Cloud (в object storage). Позволяет интегрировать сторонние средства резервного копирования.

**Primary Lease (1.30+)** — примитив выбора первичного на базе Kubernetes Lease: инстанс-менеджер держит Lease, и PostgreSQL стартует только при его наличии — закрывает временное окно при restart первичного.

**DatabaseRole CRD (1.30+)** — декларативное управление ролями PostgreSQL как отдельными Kubernetes-ресурсами вместо inline `.spec.managed.roles`. Поддерживает `databaseRoleReclaimPolicy` (`retain`/`delete`), Git-friendly workflow.

## Базовые концепции

### Архитектура: почему оператор, а не Patroni на Kubernetes
Раньше PostgreSQL в Kubernetes — это `StatefulSet` с ручным failover и самописными скриптами бэкапов. CloudNativePG (CNPG) заменяет этот стек декларативным CRD `Cluster`: оператор управляет стриминговой репликацией, автоматическим failover, архивированием WAL, резервными копиями и PITR через Kubernetes API — без внешнего DCS.

Традиционный HA-кластер на ВМ полагается на **Patroni + etcd/Consul** — в Kubernetes это «проблема матрешки» (stateful-стек ради stateful-стека). Теория DCS и Patroni: [Отказоустойчивость](../Concepts/high_availability.md). CNPG решает это иначе:
- **Кворум через Kubernetes API:** лидерство и выбор первичного — через ресурсы `Lease` (с 1.30 — выделенный примитив primary Lease).
- **Логика в основном процессе:** Instance Manager как PID 1 пода — проще диагностика и меньше потребление ресурсов.
- **Нативные Service:** мастер и реплики доступны через стандартные Kubernetes Service; переключение отражается на EndpointSlice автоматически (детали — [Сетевая связность](./kubernetes_connectivity.md)).
- **Не использует StatefulSet:** оператор управляет PVC напрямую (custom pod controller). StatefulSet достаточен для простых случаев без автоматического failover — критерии выбора: [StatefulSet: лучшие практики](../../../Kubernetes/Base/StatefulSet/statefulset_best_practices.md).

### Механизм failover

Failover инициируется контроллером, когда readiness-проб первичного пода начинает возвращать ошибки. Процесс состоит из двух фаз:

1. **Остановка первичного:** контроллер помечает `TargetPrimary` как `pending` — это вынуждает primary-под завершиться, чтобы остановить WAL-приёмники на репликах. Событие `PrimaryStatusCheckFailed` фиксируется в `kubectl describe cluster`.
2. **Лидерство и промоут:** среди реплик выбирается наиболее актуальная (наименьший LSN lag) и инициирует promotion до primary.

Оценочное время failover — **~30 секунд** (зависит от `.spec.failoverDelay`, размера WAL и состояния реплик). При трёх экземплярах quorum-модель требует, чтобы новая primary была подтверждена большинством реплик.

**Первичный Lease (1.30+):** Instance Manager держит Kubernetes `Lease` и PostgreSQL стартует только при его удержании — закрывает временное окно при restart первичного. Конфигурация в `.spec.primaryLease`:

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `leaseDurationSeconds` | `15` | Время, через которое Lease становится доступным для захвата другим инстансами |
| `renewDeadlineSeconds` | `10` | Интервал обновления Lease основным; при пропуске — уступает лидерство |
| `retryPeriodSeconds` | `2` | Частота попыток захвата/обновления Lease |
| `releasedLeaseDurationSeconds` | `1` | TTL при чистом завершении первичного |

Инварианты валидации (через webhook): `leaseDurationSeconds > renewDeadlineSeconds > retryPeriodSeconds × 1.2`. При abrupt loss кандидат наблюдает Lease в течение `leaseDurationSeconds` перед promotion; при clean switchover задержка равна `retryPeriodSeconds`. Значения меняются только после перезапуска primary-пода.

**FailoverQuorum CRD (1.28+):** при включённом `.spec.postgresql.synchronous.failoverQuorum` оператор создаёт CR `FailoverQuorum` с тем же именем `Cluster` — он хранит состояние кворума и обновляется primary в ходе reconciliation. Используйте `kubectl get failoverquorum <cluster-name> -o yaml` для диагностики кворума.

**`.spec.failoverDelay`** (по умолчанию `0`) — задержка перед запуском failover после обнаружения неисправности primary. **`.spec.switchoverDelay`** — таймаут graceful shutdown (fast shutdown) перед принудительной остановкой; влияет на RPO/RTO: низкое значение травмирует RTO (быстрее promotion, риск потери WAL), высокое — RPO (безопасное архивирование, дольше простоя). Используйте maintenance window для switchover.

### Обновления (Rolling Updates)
Rolling update запускается при: изменении `imageName`, изменения списка extension-образов (`.spec.postgresql.extensions`), обновлении Image Catalog (1.29+) или изменении параметров, требующих restart.
- **`spec.primaryUpdateStrategy`:** `unsupervised` (default — полностью автоматически) / `supervised` (пауза после обновления реплик — завершение вручную через плагин).
- **`spec.primaryUpdateMethod`:** `restart` (default с 1.20 — автоматический restart пода первичного; если невозможно, игнорируется и выполняется switchover) / `switchover` (promoted инстанс гарантированно уже на новой версии образа).
- **Ограничение:** при `primaryUpdateMethod: switchover` нельзя одновременно менять образ и параметры PostgreSQL — оператор отклонит такое обновление ошибкой валидации.
- **In-place обновление Instance Manager** (с 1.10, по умолчанию отключено): PostgreSQL не перезапускается и switchover не требуется, но под меняется после старта — нарушает чистоту immutability.

### Хранилище и QoS
- **Guaranteed QoS:** всегда `requests` = `limits` — предотвращает eviction пода при дефиците ресурсов на узле.
- **Отдельный том для WAL** (`walStorage`): WAL пишется последовательно, данные — random; разделение даёт параллельный I/O.
- **Local Persistent Volumes** для минимального latency: требуют `volumeBindingMode: WaitForFirstConsumer` и привязки к узлам через Affinity.
- **Шифрование at rest** делегируется Storage Class — уточняйте возможности CSI-драйвера.
- Перед production: бенчмарк хранилища и БД — `kubectl cnpg fio` и `kubectl cnpg pgbench`.

## Предпосылки
* Кластер Kubernetes 1.34–1.36 (оператор 1.30 поддерживает 1.34, 1.35, 1.36).
* `kubectl` и `helm` — оператор устанавливает свои RBAC, webhook и CRD через Helm-чарт.
* Storage Class с поддержкой **CSI VolumeSnapshot** — для снапшот-бэкапов (иначе доступны только бэкапы в object storage через плагин).
* **cert-manager не обязателен:** по умолчанию оператор сам выпускает сертификаты (operator-managed CA, автообновление за 7 дней до истечения, срок действия 90 дней). cert-manager нужен только для user-provided сертификатов (`serverTLSSecret`, `serverCASecret`, `clientCASecret`).
* Плагин `kubectl-cnpg` для администрирования.
* Значения в примерах (`premium-rwo-ssd`, `200Gi`, `pg-prod`) — placeholders, заменить на свои.

## Практические сценарии

### Шаг 1: Установка оператора

```bash
# Добавление репозитория и установка оператора с PodMonitor для Prometheus
helm repo add cloudnative-pg https://cloudnative-pg.github.io/charts
helm upgrade --install cnpg cloudnative-pg/cloudnative-pg \
  --namespace cnpg-system --create-namespace \
  --set monitoring.podMonitor.enabled=true
# → Deployed cnpg-cloudnative-pg; CRD clusters.postgresql.cnpg.io created

# Установка плагина управления
kubectl krew install cnpg
# → plugin cnpg installed

kubectl get pods -n cnpg-system
# → cnpg-controller-manager-... 1/1 Running
```

Текущий Helm-чарт: 0.29.1 (AppVersion 1.30.1). **Внимание:** `helm uninstall` не удаляет CRD; удаление CRD каскадно уничтожает все Cluster-ресурсы вместе с данными в PVC.

Установка через Argo CD (Application) — альтернатива Helm CLI:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cloudnative-pg
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://cloudnative-pg.github.io/charts
    chart: cloudnative-pg
    targetRevision: "0.29.x"
    helm:
      values: |
        monitoring:
          podMonitor:
            enabled: true
        grafanaDashboard:
          create: true
          namespace: monitoring
  destination:
    server: https://kubernetes.default.svc
    namespace: cnpg-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - SkipDryRunOnMissingResource=true
    retry:
      limit: 3
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

### Шаг 2: Манифест Production-кластера (PostgreSQL 18)

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-prod
spec:
  instances: 3
  imageName: ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie  # pinned minor, не плавающий :18

  # Синхронная репликация: один sync-standby (новый формат с 1.24;
  # minSyncReplicas/maxSyncReplicas — deprecated)
  postgresql:
    synchronous:
      method: any            # any (quorum) | first (priority)
      number: 1              # число sync-реплик
      dataDurability: required  # required (RPO=0, пауза при потере) | preferred (отключает sync)

    parameters:
      shared_buffers: "1Gi"    # ~25% от 8Gi
      max_connections: "500"
      log_statement: "ddl"     # не "all" в production
      wal_keep_size: "10GB"   # защита реплик от отвала при временных сбоях сети

    # pg_hba.conf: пользовательские правила добавляются после фиксированных (cert для реплик) и перед default
    pg_hba:
      - host all all 10.0.0.0/8 scram-sha-256

  storage:
    size: 200Gi
    storageClass: premium-rwo-ssd  # ← placeholder, заменить

  # Отдельный том WAL (опционально)
  # walStorage:
  #   size: 50Gi

  resources:
    requests: {cpu: "4", memory: "8Gi"}
    limits:   {cpu: "4", memory: "8Gi"}   # Guaranteed QoS

  affinity:
    enablePodAntiAffinity: true
    topologyKey: topology.kubernetes.io/zone  # on-prem: kubernetes.io/hostname

  # Бэкапы на Volume Snapshot (CSI, без object storage)
  backup:
    volumeSnapshot:
      className: csi-hostpath-snapclass  # ← placeholder, заменить
      online: true                        # hot backup (default)
      onlineConfiguration:
        immediateCheckpoint: true
      snapshotOwnerReference: none        # none (default) — сохранять снапшот после удаления Backup

  primaryUpdateStrategy: unsupervised
  primaryUpdateMethod: restart
```

```bash
kubectl apply -f cluster.yaml
kubectl get cluster pg-prod
# → pg-prod   3   18.4   ...   Running
```

### Сервисы и подключение из приложения

CNPG создаёт три сервиса для каждого кластера (имена основаны на `metadata.name`):

| Сервис | Трафик |
| :--- | :--- |
| `pg-prod-rw` | Primary (read-write) |
| `pg-prod-ro` | Реплики (read-only) |
| `pg-prod-r` | Все экземпляры |

Оператор также создаёт два `basic-auth` Secret-а: `[cluster-name]-app` (учётные данные владельца БД) и `[cluster-name]-superuser` (если включено `.spec.enableSuperuserAccess`).

Подключение из приложения (внутри namespace `app`):

```
postgresql://myapp:password@pg-main-rw.app.svc.cluster.local:5432/myapp
```

С PgBouncer (через `[cluster-name]-pooler`):

```
postgresql://myapp:password@pg-main-pooler.app.svc.cluster.local:5432/myapp
```

### Шаг 3: Пулер (PgBouncer)

CNPG создаёт PgBouncer как нативный ресурс `Pooler` (Deployment). Теория пулинга, режимы и sizing: [PgBouncer](./pgbouncer_setup.md); PgBouncer как прокси в кластере — [Сетевая связность](./kubernetes_connectivity.md).

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Pooler
metadata:
  name: pg-prod-pooler
spec:
  cluster:
    name: pg-prod
  instances: 3
  type: rw            # rw | ro
  pgbouncer:
    poolMode: transaction
    parameters:
      max_client_conn: "5000"
      default_pool_size: "50"
```

Внимание: при transaction pooling таймауты сессий на стороне PostgreSQL (`idle_session_timeout`) опасны — пулер держит сессии открытыми между транзакциями (предупреждение из документации PostgreSQL 14+).

### Шаг 3.1: Управление ролями (DatabaseRole, 1.30+)

Начиная с 1.30, роли PostgreSQL управляются через CRD `DatabaseRole` вместо inline `.spec.managed.roles`:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: DatabaseRole
metadata:
  name: app-reader
spec:
  cluster:
    name: pg-prod
  name: app_reader
  password:
    secretName: app-reader-creds  # Secret с ключом password
    updateSecretIfOutOfSync: true
  databases: [app_db]
  owner: app_user
  databaseRoleReclaimPolicy: retain  # retain (по умолчанию) | delete
```

`databaseRoleReclaimPolicy: delete` удалит роль при удалении CR; `retain` сохранит её.

### Шаг 4: Расписание бэкапов

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: pg-prod-daily
spec:
  schedule: "0 0 2 * * *"   # ежедневно в 02:00
  method: volumeSnapshot      # volumeSnapshot | plugin | barmanObjectStore (deprecated)
  immediate: true             # немедленный первый бэкап
  target: prefer-standby      # prefer-standby (по умолчанию) | primary — выбор инстанса для бэкапа
  backupOwnerReference: self
  cluster:
    name: pg-prod
```

* **volumeSnapshot** — чистый Kubernetes (CSI), object storage не нужен; основной выбор для on-prem. Снапшоты по умолчанию сохраняются после удаления Backup-объекта (`snapshotOwnerReference: none`).
* **plugin** — CNPG-I Barman Cloud Plugin в object storage. Self-hosted вариант — S3-совместимое хранилище (например, MinIO), см. [Disaster Recovery](../../../Concepts/disaster_recovery.md).
* **WAL archive без базового бэкапа бесполезен** — PITR требует base backup + WAL.
* Теория бэкапов и PITR: [Автоматизация бэкапов](./backup_automation.md), [Backup and Recovery](../Concepts/backup_and_recovery.md).

#### Резервное копирование в Object Storage (S3 / Yandex Object Storage)

Для S3-совместимого хранилища (Yandex Object Storage, MinIO) рекомендуется **CNPG-I Barman Cloud Plugin** (метод `plugin`). In-tree `barmanObjectStore` deprecated начиная с 1.26 и будет удалён. Миграция: [Barman Cloud Plugin](https://cloudnative-pg.github.io/plugin-barman-cloud/docs/migration/).

**Современный подход — ObjectStore CR + plugin:**

Перед использованием установите [Barman Cloud Plugin](https://cloudnative-pg.github.io/plugin-barman-cloud/) в том же namespace, что и кластер PostgreSQL:

```bash
kubectl cnpg plugin install barman-cloud.cloudnative-pg.io
```

```yaml
# ObjectStore CR (отдельный ресурс)
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: pg-main-store
  namespace: app
spec:
  configuration:
    destinationPath: s3://pg-backups/pg-main
    endpointURL: https://storage.yandexcloud.net
    s3Credentials:
      accessKeyId:
        name: pg-s3-secret
        key: ACCESS_KEY_ID
      secretAccessKey:
        name: pg-s3-secret
        key: SECRET_ACCESS_KEY
    wal:
      compression: gzip
    data:
      compression: gzip
---
# Cluster: подключаем плагин
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-main
  namespace: app
spec:
  instances: 3
  imageName: ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie

  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: pg-main-store

  backup:
    retentionPolicy: "30d"
    barmanObjectStore:  # ← DEPRECATED: см. миграцию выше
      destinationPath: s3://pg-backups/pg-main
      endpointURL: https://storage.yandexcloud.net
      s3Credentials:
        accessKeyId:
          name: pg-s3-secret
          key: ACCESS_KEY_ID
        secretAccessKey:
          name: pg-s3-secret
          key: SECRET_ACCESS_KEY
      wal:
        compression: gzip
      data:
        compression: gzip
```

`retentionPolicy` задаёт срок хранения локальных WAL-сегментов на узле. CNPG непрерывно отправляет WAL в object storage — каждый ежедневный бэкап становится базовым, а заархивированный WAL обеспечивает PITR с точностью до секунды.

### Шаг 5: Операционные задачи (kubectl cnpg)

| Задача | Команда |
| :--- | :--- |
| Статус кластера, LSN-лаги, WAL archiving | `kubectl cnpg status pg-prod` |
| Подключение psql | `kubectl cnpg psql pg-prod -- -d app_db` |
| Switchover (плановое обслуживание) | `kubectl cnpg promote pg-prod pg-prod-2` |
| Rollout restart кластера / одного инстанса | `kubectl cnpg restart pg-prod [pg-prod-2]` |
| Reconciliation (применить ConfigMap мониторинга) | `kubectl cnpg reload pg-prod` |
| Окно обслуживания для всех кластеров | `kubectl cnpg maintenance set --all-namespaces` |
| Снятие окна обслуживания | `kubectl cnpg maintenance unset --all-namespaces` |
| On-demand бэкап | `kubectl cnpg backup pg-prod` |
| Холодный снапшот (fencing standby) | `kubectl cnpg snapshot pg-prod` |
| Диагностика кластера | `kubectl cnpg report pg-prod` |
| Логи | `kubectl cnpg logs pg-prod` |
| Major upgrade (PG 18.x → 19.x) | окно `kubectl cnpg maintenance` + смена `imageName` |
| Гибернация (остановить поды, сохранить PVC) | `kubectl cnpg hibernate on pg-prod` / `hibernate off` для возврата |
| Список бэкапов | `kubectl get backup -n app` |
| Архивация WAL (детали) | `kubectl cnpg status pg-prod` \| grep -A5 "WAL Archiving" |

`kubectl cnpg status` показывает: точку восстановимости, состояние WAL archiving (из `pg_stat_archiver`) и таблицу репликации (Sent/Write/Flush/Replay LSN, лаги, Sync State). Switchover выполняется командой `promote` — отдельной команды `switchover` в текущем плагине нет; `promote` выполняет и switchover (при чистом shutdown primary), и emergency promotion (при аварийном отказе).

## Мониторинг

* PodMonitor устанавливается при `--set monitoring.podMonitor.enabled=true`; метрики Instance Manager — основа для Prometheus/Grafana. Дашборды, алерты, wait events: [Наблюдаемость](./observability.md).
* С 1.30 — TLS для метрик Pooler (`.spec.monitoring.tls.enabled`).
* **Безопасность:** экспортер метриков работает от роли `cnpg_metrics_exporter` с привилегиями только `pg_monitor` — фикс CVE-2026-44477 (Critical, CVSS 9.4, privilege escalation в metrics exporter). При использовании веток 1.28.x/1.29.x обновитесь минимум до 1.28.3/1.29.1.
* Сетевая связность, аннотации Service (Topology Aware Routing, `trafficDistribution: PreferClose`), mTLS с cert-manager: [Сетевая связность](./kubernetes_connectivity.md).

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Поды `Pending` | Нет ресурсов на узлах или нет свободного PV в зоне | `kubectl describe pod`; проверить PV и Storage Class |
| `OOMKilled` | PostgreSQL превысил лимит памяти K8s | Считать `shared_buffers` + `work_mem × max_connections`; увеличить limits (Guaranteed QoS) |
| `WAL archiving failing` | Недоступен endpoint бэкапа или неверные креды | `kubectl logs -n cnpg-system deploy/cnpg-controller-manager`; секция WAL в `kubectl cnpg status` |
| Failover «завис», первичный не переключается | Primary не проходит проверку `/pg/status` | Событие `PrimaryStatusCheckFailed`: `kubectl describe cluster pg-prod` (1.30+) |
| Нет снапшот-бэкапов | Storage Class не поддерживает CSI VolumeSnapshot | Проверить VolumeSnapshotClass; или перейти на method: plugin |
| Нет сети между подами | NetworkPolicy/Cilium блокирует трафик | Разрешить 5432 между инстансами кластера и от Pooler |
| Реплика отстаёт, WAL не очищается | Зависший replication slot удерживает WAL | Проверить `pg_replication_slots` на primary; удалить через `pg_drop_replication_slot`; установить `max_slot_wal_keep_size` для ограничения (PG 13+) |
| Primary не назначается после crash | Lease не освобождён или `primaryLease` settings misconfigured | `kubectl get lease <cluster-name> -o yaml`; проверить invariants: `leaseDuration > renewDeadline > retryPeriod × 1.2` |
| FailoverQuorum блокирует promotion | Недостаточно sync-реплик для quorum | `kubectl get failoverquorum <cluster-name> -o yaml`; убедиться что `number` sync-реплик доступны |
| `pgbench` job зависает | Не хватает PVC или pgbench-пода не стартовал | `kubectl get job, pod -n <ns> -l cnpg.io/job-type=pgbench`; логи job через `kubectl logs` |

## Пограничные случаи и ограничения

### Крупные базы (>5 ТБ)
`pg_basebackup` по сети может длиться сутки. Решение — **seed из Volume Snapshot** (минуты вместо часов). Корректное поле (не `bootstrap.recovery.volumeSnapshot.name`, как в устаревших примерах):

```yaml
bootstrap:
  recovery:
    source: pg-prod
    volumeSnapshots:
      storage:
        name: pg-prod-data-snapshot
        kind: VolumeSnapshot
        apiGroup: snapshot.storage.k8s.io
      # walStorage: ...   # если WAL на отдельном томе — снапшот и для него
```

Ограничение: при создании реплик после восстановления из снапшота оператор может откатиться к `pg_basebackup` (медленнее) — онлайн-бэкапы и PVC-cloning в процессе развития.

### PITR

Восстановление — это bootstrapping **нового** кластера, не in-place операция: `bootstrap.recovery` + `recoveryTarget.targetTime` + WAL archive (plugin/object storage). Используйте другое имя кластера, чтобы не конфликтовать с production. CNPG воспроизводит WAL до `targetTime`.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-main-restored
  namespace: app
spec:
  instances: 1
  bootstrap:
    recovery:
      source: pg-main
      recoveryTarget:
        targetTime: "2026-10-17 14:30:00"
  externalClusters:
    - name: pg-main
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: pg-main-store   # ObjectStore CR из Шага 4
          serverName: pg-main
   ```

### Миграция с других операторов и ВМ
`bootstrap.externalClusters` — CNPG подключается к старому мастеру как реплика и синхронизирует данные (pg_basebackup). Сценарий VM→Kubernetes без простоя: [Бесшовная миграция](./zero_downtime_migration.md). Сравнение с Zalando Postgres Operator: [Zalando Postgres Operator](./zalando_postgres_operator.md).

### Одиночный инстанс
Для кластера с `instances: 1` значение `primaryUpdateStrategy: supervised` не поддерживается — только `unsupervised`; приложения переподключаются при любом обновлении.

## Лучшие практики

* Pin версии образа (`...:18.4-system-trixie`), не плавающий тег `:18`.
* Guaranteed QoS; отдельный WAL-том (`walStorage`) для нагруженных БД.
* `log_statement: ddl` вместо `all` в production; `wal_keep_size` для защиты реплик.
* Проверять бэкапы восстановлением (PITR в изолированный кластер), а не только наличием снапшотов.
* Обновлять оператор вовремя (CVE-2026-44477); перед upgrade читать release notes — некоторые версии требуют ручных шагов.
* Бенчмарк хранилища (`kubectl cnpg fio`) перед production.
* Использовать `.spec.postgresql.synchronous` (method/number/dataDurability) вместо deprecated `minSyncReplicas`/`maxSyncReplicas`.
* Для on-prem с небольшим числом зон: `failoverQuorum` + `dataDurability: required` минимизируют RPO до 0.
* При миграции ролей на `DatabaseRole` (1.30+): удаляйте inline entries из `.spec.managed.roles` только после создания CR — иначе роль становится неуправляемой.

## Очистка и откат

* **Откат образа:** вернуть прежний `imageName` в манифесте — оператор выполнит rolling update в обратную сторону.
* **Удаление кластера:** `kubectl delete cluster pg-prod` — PVC по умолчанию сохраняются (данные не теряются); удаляйте PVC вручную после подтверждения.
* **Удаление оператора:** `helm uninstall cnpg -n cnpg-system` не удаляет CRD; удаление CRD каскадно уничтожает все Cluster и их данные — сначала сделайте бэкап.

## Валидация

```bash
kubectl cnpg status pg-prod
# → Status: Cluster in healthy state; Primary instance: pg-prod-1

kubectl cnpg psql pg-prod -- -c "SELECT pg_is_in_recovery();"
# → pg_is_in_recovery: f   (на первичном; t — на реплике)

kubectl cnpg pgbench pg-prod -- -c 20 -j 4 -T 30   # встроенный pgbench
# → transaction: ... tps

kubectl get volumeSnapshot -l cnpg.io/cluster=pg-prod
# → pg-prod-...   VolumeSnapshotClass: csi-hostpath-snapclass
```

## Дополнительная информация

### Вопросы на собеседованиях

1. Чем CNPG отличается от Patroni, развёрнутого в Kubernetes? (нет внешнего DCS; координация через Lease API; Instance Manager как PID 1)
2. Что делает `primaryUpdateMethod: restart` и когда выполняется fallback на switchover?
3. Почему `barmanObjectStore` deprecated и что такое CNPG-I?
4. Как сделать бэкап без object storage? (volumeSnapshot через CSI)
5. Почему WAL archive без base backup бесполезен?
6. Что такое Primary Lease (1.30+) и как закрывает окно двойного лидера?
7. Когда и зачем использовать `FailoverQuorum` для safe failover?

### Связанные документы

* [Наблюдаемость PostgreSQL](./observability.md) — Grafana, алерты, wait events.
* [Сетевая связность](./kubernetes_connectivity.md) — Service, Topology Routing, mTLS, cert-manager.
* [PgBouncer](./pgbouncer_setup.md) — теория пулинга и sizing.
* [Автоматизация бэкапов](./backup_automation.md) — pgBackRest/Barman, теория PITR.
* [Zalando Postgres Operator](./zalando_postgres_operator.md) — альтернативный оператор и сравнение с CNPG.
* [Отказоустойчивость](../Concepts/high_availability.md) — теория Patroni и DCS.
* [Backup and Recovery](../Concepts/backup_and_recovery.md) — теория PITR и WAL.
* [Бесшовная миграция](./zero_downtime_migration.md) — VM в Kubernetes.
* [Kubernetes-операторы](../../../Kubernetes/Concepts/kubernetes_operators.md) — общая теория операторов.
* [StatefulSet: лучшие практики](../../../Kubernetes/Base/StatefulSet/statefulset_best_practices.md) — когда StatefulSet достаточен без оператора.
