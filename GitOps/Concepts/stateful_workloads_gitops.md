# Stateful-нагрузки в GitOps: базы данных и операторы

**Актуально для:** Kubernetes 1.28–1.32+, Argo CD v3.x (v3.4–v3.6+), Flux v2.x (v2.3–v2.9+), CloudNativePG 1.25–1.30+, Strimzi 0.40–0.44+ (bare-metal / on-premise)

Развертывание баз данных, брокеров сообщений и распределенных систем хранения в Kubernetes под управлением GitOps — стандартная практика зрелой онпремизной (bare-metal / on-premise) инфраструктуры. При этом GitOps берет на себя управление декларативной топологией, конфигурацией и версиями операторов, тогда как реальное физическое состояние и бинарные данные хранятся на постоянных томах (PVC/PV) и в механизмах репликации. На стыке этих двух парадигм — декларативного контроллера GitOps и автономного контроллера оператора базы данных — кроется большинство критических рисков: случайные каскадные удаления (prune), деградация кворума при неконтролируемом перезапуске подов, зацикливание reconciliation loop из-за runtime-дрейфа и повреждения схемы данных при рассинхронизации релизов.

---

## Определения

- **Stateful workload (нагрузка с состоянием)** — приложение, чья идентичность, сетевое имя и данные должны непрерывно сохраняться при пересоздании, миграции или перезапуске подов (СУБД PostgreSQL/MariaDB, брокеры Kafka/RabbitMQ, распределенные кэши Redis).
- **Operator pattern (паттерн оператора)** — расширение Kubernetes API, объединяющее кастомные определения ресурсов (CRD) и контроллер, который кодирует эксплуатационные знания администратора: процедуру первичной инициализации (bootstrap), синхронизацию реплик, автоматический failover, ротацию сертификатов, резервное копирование и мажорные апгрейды.
- **VolumeClaimTemplates** — декларативный шаблон внутри спецификации StatefulSet, по которому Kubernetes автоматически создает уникальный `PersistentVolumeClaim` для каждого ordinal-индекса пода (`data-db-0`, `data-db-1`).
- **VolumeBindingMode (`WaitForFirstConsumer`)** — режим связывания в `StorageClass`, откладывающий создание и биндинг тома PV до момента, когда планировщик (`kube-scheduler`) определит узел для пода с учетом Affinity, Taints и доступных аппаратных ресурсов. Предотвращает топологический тупик планирования в bare-metal кластерах.
- **Reclaim Policy (`Retain` vs `Delete`)** — политика жизненного цикла физического хранилища при удалении объекта `PersistentVolumeClaim`. При значении `Retain` физический том на дисковом массиве (Ceph RBD, LVM) сохраняется вместе со всеми данными.
- **Finalizer cascade (каскад финализаторов)** — цепочка зависимого удаления: удаление родительского кастомного ресурса (например, `Cluster`) запускает встроенный финализатор оператора, который удаляет подчиненные StatefulSet/Deployment, затем поды, а при определенных настройках инициирует удаление томов PVC.
- **Prune (обрезка устаревших ресурсов)** — автоматическое удаление GitOps-агентом (Argo CD / Flux) тех ресурсов в кластере, чьи декларативные файлы были удалены или переименованы в Git-репозитории.
- **IgnoreDifferences** — механизм фильтрации в GitOps, исключающий заданные поля живого ресурса (`live state`) из сравнения с манифестом в Git (`desired state`), защищающий от ложного `OutOfSync` и циклов самолечения (`SelfHeal`).
- **Expand-Contract (миграция «расширение-сжатие»)** — трехфазный паттерн версионирования схемы базы данных: добавление обратно совместимых изменений (шаг 1), перевод прикладного кода на новую схему (шаг 2), удаление устаревших структур после полной стабилизации сервиса (шаг 3).
- **PodDisruptionBudget (PDB)** — примитив Kubernetes, ограничивающий количество одновременно недоступных реплик при добровольном дренаже узлов (`kubectl drain`), гарантирующий сохранение кворума кластера.

---

## Базовые концепции и архитектура

### 1. Декларативное описание (Git) vs Физическое состояние томов

Фундаментальный принцип надежности: **Git описывает намерение и топологию, но никогда не содержит и не заменяет собой данные**.

```text
┌────────────────────────────────────────┐         ┌─────────────────────────────────────────┐
│         Git-репозиторий (GitOps)       │         │        Кластер Kubernetes (On-Prem)     │
├────────────────────────────────────────┤         ├─────────────────────────────────────────┤
│ • Манифесты операторов и CRD           │         │ • Блочные устройства (Ceph RBD / LVM)   │
│ • CR топологии (3 реплики, лимиты, CPU)│  Sync   │ • Содержимое таблиц БД и WAL-журналы    │
│ • Конфигурация параметров СУБД (sysctl)├────────►│ • Текущие роли нод (Primary/Replica)    │
│ • Расписания бэкапов (Cron, retention) │         │ • Динамические LSN-позиции репликации   │
│ • Ссылки на секреты (SealedSecret/ESO) │         │ • Runtime-статусы и условия healthcheck │
└────────────────────────────────────────┘         └─────────────────────────────────────────┘
```

| Входит в Git (декларативно) | Категорически исключено из Git | Причина разделения |
| :--- | :--- | :--- |
| Версия образа и оператора | Бинарные файлы баз данных и WAL | Git не предназначен для хранения терабайтных блочных состояний. |
| Количество реплик и топология | Динамические роли (Primary / Replica) | Выбор лидера происходит автономно по протоколам кворума (Raft, Patroni DCS). |
| Ресурсы (requests/limits) и QoS | Сгенерированные пароли и криптоключи | Секреты шифруются через [управление секретами](../secrets_encryption.md) (ESO/SOPS). |
| StorageClass, размер тома и точки монтирования | Локальные PV-библиотеки и UUID томов | Диски связываются CSI-драйвером динамически на уровне кластера. |
| Расписания и цели бэкапов | Состояние бэкап-снапшотов и LSN | Бэкапы версионируются в S3-совместимом хранилище (MinIO / Ceph RGW). |

---

### 2. Архитектура On-Premise хранения для Stateful-нагрузок

В корпоративной инфраструктуре без публичных облачных провайдеров выбор технологии хранения определяет надежность и латентность дискового ввода-вывода (I/O).

#### Режим связывания `volumeBindingMode: WaitForFirstConsumer`
Стандартный режим `Immediate` выделяет физический том в момент создания PVC, до того, как pod запланирован на конкретную ноду. В bare-metal кластерах с локальными дисками (LVM/TopoLVM) или зональным распределением узлов это приводит к фатальной ошибке планировщика: **`volume node affinity conflict`**. Том оказывается на одном сервере, а pod не может туда запуститься из-за нехватки RAM или правил `podAntiAffinity`.
Режим `WaitForFirstConsumer` в StorageClass обязателен для всех stateful-систем: он заставляет CSI ждать, пока `kube-scheduler` выберет оптимальный узел для пода, и только затем аллоцирует диск на этом узле.

#### Выбор типа CSI-драйвера
- **Local Storage (TopoLVM / local-static-provisioner / Direct LVM):** Напрямую монтирует локальные NVMe/SSD хоста. Обеспечивает минимальную задержку (sub-millisecond p99 latency) и максимальный IOPS. Идеально для высоконагруженных СУБД (PostgreSQL, ClickHouse) и Kafka при условии, что отказоустойчивость обеспечивается на уровне самого приложения (репликация 3+ узлов). Недостаток: pod жестко привязан к конкретному физическому серверу.
- **Распределенное блочное хранилище (Ceph RBD через Rook-Ceph):** Сетевой блочный диск. Обеспечивает свободную миграцию подов между любыми worker-нодами кластера, поддержку CSI VolumeSnapshot и онлайн-расширение дисков. Задержка выше, чем у локального NVMe, но упрощается эксплуатация и обслуживание серверов.
- **Файловое хранилище (NFS / CephFS):** Допускается только для разделяемых dump-архивов и ReadWriteMany-логов; **категорически запрещено** для размещения каталогов данных транзакционных СУБД (WAL fsync и блокировки файлов в NFS приводят к деградации и повреждению данных).

#### Неизменяемость `volumeClaimTemplates`
В нативном Kubernetes `volumeClaimTemplates` в спецификации StatefulSet является **иммутабельным**. Попытка изменить размер диска `size: 100Gi → 200Gi` в манифесте StatefulSet приведет к ошибке `StatefulSet spec is invalid: forbidden`.
В GitOps эту проблему решают операторы баз данных: современные операторы (CloudNativePG, Strimzi) перехватывают изменение размера в собственном Custom Resource (`spec.storage.size`), напрямую отправляют запрос на изменение размера в существующие объекты `PersistentVolumeClaim`, а CSI-драйвер выполняет онлайн-расширение файловой системы на узле.

---

### 3. Анатомия риска: Prune, каскадные удаления и финализаторы

Главная катастрофа взаимодействия GitOps и Stateful-нагрузок — случайный снос базы данных в результате очистки Git-репозитория:

```text
Инженер переименовал каталог: apps/billing-db/ ──► apps/billing/db/
                                     │
                                     ▼
                   Argo CD считает старый CR удаленным
                                     │
                                     ▼
       ┌────────────────────────────────────────────────────────┐
       │ Опция prune: true удаляет кастомный ресурс СУБД (CR)    │
       └─────────────────────────────┬──────────────────────────┘
                                     │
                                     ▼
       ┌────────────────────────────────────────────────────────┐
       │ Контроллер оператора видит удаление родительского CR:  │
       │ срабатывает встроенный Finalizer                       │
       └─────────────────────────────┬──────────────────────────┘
                                     │
                  ┌──────────────────┴──────────────────┐
                  ▼                                     ▼
     Удаление Pods и StatefulSet         Остановка репликации и кворума
                  │
                  ▼
   PVC переходят в Terminating (если reclaimPolicy: Delete) ──► ПОТЕРЯ ДАННЫХ
```

#### Эшелоны защиты (Defense in Depth)

1. **Защитная аннотация `Prune=false`**:
   Установка аннотации `argocd.argoproj.io/sync-options: Prune=false` на уровне Custom Resource кластера, StatefulSet и всех PVC запрещает Argo CD посылать вызов `DELETE` в Kubernetes API, даже если манифест полностью исчез из Git. Детали работы механизмов очистки описаны в [удаление и очистка в Argo CD](../ArgoCD/argocd_deletion_and_cleanup.md).
2. **Политика сохранения физических дисков (`reclaimPolicy: Retain`)**:
   В StorageClass для баз данных всегда задается `reclaimPolicy: Retain`. Даже если PVC был непреднамеренно удален, физический том в Ceph RBD или раздел LVM переходит в статус `Released`, исключая физическое уничтожение байтов данных.
3. **Изоляция в выделенные `AppProject`**:
   Stateful-нагрузки выносятся в отдельный проект Argo CD (`data-infrastructure`), где на уровне политик отключен `prune`, ограничен круг лиц с правами коммита, а в репозитории настроен жесткий `CODEOWNERS` на пути `databases/**`.
4. **Политики удаления оператора (`deletionPolicy: Retain / Orphan`)**:
   Конфигурация оператора должна переводиться в режим, при котором удаление ресурса `Cluster` удаляет управляющую логику, но оставляет StatefulSet, поды и диски нетронутыми в кластере.
5. **PreDelete Hooks для аварийных снапшотов**:
   Хук жизненного цикла `argocd.argoproj.io/hook: PreDelete` запускает Job создания снапшота томов или вызова утилиты бэкапа перед тем, как начнется процедура деструкции приложения.

---

### 4. Управление дрейфом (Drift) и `ignoreDifferences`

Операторы баз данных являются динамическими контроллерами: они непрерывно инспектируют кластер и самостоятельно меняют метаданные живых ресурсов (`live state`).

Если GitOps-агент не проинформирован об этих легитимных мутациях, возникает патологический дрейф:
- Argo CD фиксирует статус `OutOfSync`.
- Если включен `selfHeal: true`, Argo CD пытается перезаписать манифест из Git, стирая динамические метки оператора.
- В худшем случае GitOps сбрасывает метку `role: master` на старый узел, вызывая кратковременный Split-Brain или разрыв клиентских сессий.

```yaml
# Пример настройки в Application для исключения операторного дрейфа
spec:
  ignoreDifferences:
    # Игнорирование runtime-статуса кластера СУБД
    - group: postgresql.cnpg.io
      kind: Cluster
      jsonPointers:
        - /status
    # Игнорирование динамических меток failover, выставляемых оператором на поды
    - group: ""
      kind: Pod
      jqPathExpressions:
        - .metadata.labels["cnpg.io/instanceRole"]
        - .metadata.labels["role"]
    # Игнорирование условий расширения и емкости PVC
    - group: ""
      kind: PersistentVolumeClaim
      jsonPointers:
        - /status
        - /metadata/annotations/volume.kubernetes.io~1storage-provisioner
        - /metadata/annotations/pv.kubernetes.io~1bind-completed
```
Подробная механика конфигурации diffing-движка и JQ-путей представлена в руководстве [игнорирование различий и дрейф](../ArgoCD/synchronization/ignore_differences.md).

---

### 5. Упорядоченность раскатки и сохранение кворума

В отличие от stateless-сервисов, где допустим параллельный перезапуск подов, распределенные базы данных и брокеры сообщений (Kafka, RabbitMQ, Patroni, etcd) требуют строгого соблюдения кворума:
$$Q = \lfloor N/2 \rfloor + 1$$
Где $N$ — общее число активных узлов. Одновременная перезагрузка двух узлов из трех приводит к потере кворума, заморозке операций записи и остановке всего сервиса.

#### Стратегии обновления контроллеров
- **`podManagementPolicy: OrderedReady`**: Поды создаются строго по очереди (`0 → 1 → 2`) и удаляются в обратном порядке (`2 → 1 → 0`). Следующий под не трогается, пока предыдущий не прошел `readinessProbe` и не синхронизировал данные.
- **Категорический запрет `podManagementPolicy: Parallel`**: Параллельный запуск/перезапуск разрушает кворум брокеров сообщений и инициаторов выборов лидера.
- **Использование `RollingUpdate.partition`**: Позволяет через Git зафиксировать canary-обновление: обновляется только реплика с максимальным индексом, после чего раскатка останавливается для снятия метрик производительности.
- **Поддержка `PodDisruptionBudget` (PDB)**: Обязательный примитив для bare-metal инфраструктуры. При вызове системным администратором `kubectl drain node-01` PDB с `minAvailable: 2` не позволит выселить pod СУБД, пока остальные реплики не находятся в полностью синхронном состоянии.

---

### 6. Жизненный цикл версий и миграции схемы

#### Минорные обновления vs Мажорные апгрейды
- **Patch/Minor (PostgreSQL 17.2 → 17.4, Kafka 3.8.0 → 3.8.1):** Двоичные файлы совместимы по формату хранения на диске. Допускается автоматический Rolling Update средствами оператора (сначала реплики, затем контролируемый switchover лидера).
- **Major upgrades (PostgreSQL 16 → 17):** Формат хранения на диске несовместим. Требуется либо утилита `pg_upgrade` слинкованными томами, либо логическая репликация на параллельно развернутый новый кластер. **Категорически запрещено отдавать мажорные апгрейды на автосинк GitOps**. Мажорный апгрейд проводится только в рамках согласованного технологического окна через `syncWindows` или временный перевод приложения в `manual sync`.

#### Паттерн Expand-Contract для миграций схемы
При раздельном деплое манифестов БД и микросервисов изменение схемы базы должно быть полностью обратно совместимым со старой версией прикладного кода:
1. **Expand (Расширение):** В схему добавляется новая колонка `user_email_v2`, старая `email` не удаляется. Приложение v1 пишет в обе колонки или читает старую.
2. **Transition (Переключение):** Выкатывается новая версия приложения v2, использующая новую колонку.
3. **Contract (Сжатие):** Через отдельный релиз после подтверждения стабильности удаляются устаревшие колонки и триггеры.

---

## Практические сценарии

### Сценарий 1: Production HA-кластер CloudNativePG на On-Premise Ceph через Argo CD

В данном сценарии реализуется отказоустойчивый кластер PostgreSQL из 3 реплик на базе оператора CloudNativePG в bare-metal окружении с сетевым блочным хранилищем Ceph RBD. Развертывание организовано через [волны синхронизации](../ArgoCD/synchronization/scenarios/sync_waves_hooks.md) для гарантии правильного порядка создания зависимостей.

#### Манифест инфраструктуры базы данных (`db-cluster.yaml`)

```yaml
# Волна -1: StorageClass с безопасной политикой удержания дисков
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd-sc
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
provisioner: rbd.csi.ceph.com
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
parameters:
  pool: k8s-rbd-pool
  clusterID: ceph-prod-cluster
---
# Волна 0: Кластер CloudNativePG с разделением WAL и данных
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: billing-postgres
  namespace: billing
  annotations:
    argocd.argoproj.io/sync-wave: "0"
    argocd.argoproj.io/sync-options: Prune=false   # Защита от случайного удаления
spec:
  instances: 3
  imageName: ghcr.io/cloudnative-pg/postgresql:17.4

  # Архитектура хранения: разделение случайного I/O данных и последовательного WAL
  storage:
    size: 150Gi
    storageClass: ceph-rbd-sc
  walStorage:
    size: 50Gi
    storageClass: ceph-rbd-sc

  # Стратегия обновления первичного инстанса
  primaryUpdateStrategy: unsupervised
  primaryUpdateMethod: switchover

  # Конфигурация базы и системных параметров
  postgresql:
    parameters:
      shared_buffers: "4GB"
      work_mem: "32MB"
      maintenance_work_mem: "512MB"
      max_connections: "200"
      wal_keep_size: "10GB"
      checkpoint_completion_target: "0.9"

  # Мониторинг Prometheus (без внешних облачных зависимостей)
  monitoring:
    enablePodMonitor: true

  # Распределение по физическим серверам инфраструктуры
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchExpressions:
              - key: cnpg.io/cluster
                operator: In
                values: [billing-postgres]
          topologyKey: kubernetes.io/hostname
---
# Волна 1: Микросервис, подключающийся к автоматически сгенерированным секретам
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  namespace: billing
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  replicas: 2
  selector:
    matchLabels:
      app: billing-service
  template:
    metadata:
      labels:
        app: billing-service
    spec:
      containers:
        - name: app
          image: internal-registry.domain.local/billing/service:v2.4.0
          env:
            - name: DB_HOST
              value: "billing-postgres-rw.billing.svc.cluster.local"
            - name: DB_NAME
              value: "app"
            - name: DB_USER
              valueFrom:
                secretKeyRef:
                  name: billing-postgres-app
                  key: username
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: billing-postgres-app
                  key: password
```

---

### Сценарий 2: Безопасные миграции схемы БД через Argo CD PreSync Hook

Схема БД обновляется строго **до** того, как запустится новый код сервиса. Если Job миграции падает с ошибкой, синхронизация прерывается (`SyncFailed`), старые поды продолжают обрабатывать трафик без даунтайма.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: billing-schema-migration
  namespace: billing
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 600   # 10 минут таймаут на выполнение миграции
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrator
          image: internal-registry.domain.local/tools/flyway:10.15-alpine
          args:
            - -url=jdbc:postgresql://billing-postgres-rw.billing.svc:5432/app
            - -connectRetries=15
            - -baselineOnMigrate=true
            - migrate
          env:
            - name: FLYWAY_USER
              valueFrom:
                secretKeyRef:
                  name: billing-postgres-app
                  key: username
            - name: FLYWAY_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: billing-postgres-app
                  key: password
```

---

### Сценарий 3: Резервное копирование и Disaster Recovery в On-Premise инфраструктуре

Резервное копирование в GitOps описывается декларативно через кастомные ресурсы расписаний, а физические архивы направляются в локальный S3-совместимый объектный кластер (MinIO / Ceph RadosGW).

#### Декларативное расписание бэкапов CloudNativePG

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: billing-postgres-daily
  namespace: billing
  annotations:
    argocd.argoproj.io/sync-options: Prune=false
spec:
  schedule: "0 0 2 * * *"   # Ежедневно в 02:00
  backupOwnerReference: self
  cluster:
    name: billing-postgres
  target: prefer-standby    # Снятие бэкапа со standby-реплики для снижения нагрузки на primary
```

#### Runbook аварийного восстановления (Disaster Recovery Runbook)

При полной аппаратной катастрофе площадки или фатальном удалении namespace процедура восстановления выполняется по регламенту:

1. **Заморозка GitOps (Pause Sync):**
   Приостановить автоматическую синхронизацию в Argo CD, чтобы контроллер не пересоздавал пустую чистую базу:
   ```bash
   argocd app set billing-app --sync-policy manual
   # → Application 'billing-app' sync policy updated to manual
   ```
2. **Восстановление кластера из архива бэкапов:**
   Создать манифест инициализации нового кластера из существующего бэкапа в MinIO/Ceph RGW:
   ```yaml
   apiVersion: postgresql.cnpg.io/v1
   kind: Cluster
   metadata:
     name: billing-postgres-recovered
     namespace: billing
   spec:
     instances: 3
     bootstrap:
       recovery:
         source: billing-backup-storage
   ```
3. **Проверка целостности данных (Integrity Drill):**
   Выполнить тестовые запросы и валидацию LSN через канареечный pod перед переключением боевого трафика.
4. **Обновление Git и возврат на автосинк:**
   Зафиксировать имя нового кластера в Git, выполнить pull request, получить одобрение владельца сервиса и перевести Argo CD обратно в автоматический режим.

---

### Сценарий 4: Kafka-кластер (Strimzi) на Bare-Metal с упорядоченными обновлениями

При эксплуатации брокеров Apache Kafka на bare-metal критически важно исключить удаление томов при масштабировании вниз (`deleteClaim: false`) и зафиксировать упорядоченный рестарт брокеров.

```yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: telemetry-kafka
  namespace: kafka
  annotations:
    argocd.argoproj.io/sync-options: Prune=false
spec:
  kafka:
    version: 3.9.0
    replicas: 3
    listeners:
      - name: plain
        port: 9092
        type: internal
        tls: false
    config:
      offsets.topic.replication.factor: 3
      transaction.state.log.replication.factor: 3
      transaction.state.log.min.isr: 2
      default.replication.factor: 3
      min.insync.replicas: 2
    storage:
      type: jbod
      volumes:
        - id: 0
          type: persistent-claim
          size: 500Gi
          class: ceph-rbd-sc
          deleteClaim: false   # Защита PVC от удаления при удалении или уменьшении брокеров
    template:
      statefulset:
        podManagementPolicy: OrderedReady
      pod:
        affinity:
          podAntiAffinity:
            requiredDuringSchedulingIgnoredDuringExecution:
              - labelSelector:
                  matchExpressions:
                    - key: strimzi.io/name
                      operator: In
                      values: [telemetry-kafka-kafka]
                topologyKey: kubernetes.io/hostname
  zookeeper:
    replicas: 3
    storage:
      type: persistent-claim
      size: 50Gi
      class: ceph-rbd-sc
      deleteClaim: false
```

---

### Сценарий 5: Управление stateful-нагрузками в Flux v2

В экосистеме Flux v2 защита от prune и контроль последовательности задаются через примитивы `kustomize.toolkit.fluxcd.io` и аннотации Kustomize.

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: databases-subsystem
  namespace: flux-system
spec:
  interval: 10m
  targetNamespace: billing
  sourceRef:
    kind: GitRepository
    name: infrastructure-fleet
  path: ./clusters/dc-primary/databases
  prune: false                 # Глобальный запрет prune для всего слоя баз данных
  wait: true                   # Ожидание готовности всех подов перед успешным завершением
  timeout: 15m
  healthChecks:
    - apiVersion: postgresql.cnpg.io/v1
      kind: Cluster
      name: billing-postgres
      namespace: billing
```

Для тонкой защиты отдельных ресурсов в Kustomize оверлее добавляется аннотация:
```yaml
metadata:
  annotations:
    kustomize.toolkit.fluxcd.io/prune: disabled
```

---

## Операции и команды

В данном разделе представлены практические команды системного администратора и SRE для обслуживания stateful-нагрузок под управлением GitOps.

### 1. Инспекция состояния кворума и репликации

```bash
# Проверка глобального состояния и роли узлов кластера CloudNativePG
kubectl get cluster -n billing billing-postgres
# → NAME               AGE   INSTANCES   READY   STATUS                     PRIMARY
# → billing-postgres   12d   3           3       Cluster in healthy state   billing-postgres-1

# Детализированная диагностика репликации, WAL-задержки и непрерывного бэкапа
kubectl cnpg status billing-postgres -n billing
# → Cluster Summary:
# → Name: billing-postgres
# → Status: Cluster in healthy state
# → Primary instance: billing-postgres-1
# → Continuous Backup: OK (Destination: MinIO, Last WAL: 000000010000004500000021)
# → Replicas status:
# →   billing-postgres-2: Streaming (Replication lag: 0 bytes)
# →   billing-postgres-3: Streaming (Replication lag: 0 bytes)
```

### 2. Процедура онлайн-расширения томов (PVC Expansion) через GitOps

Для увеличения диска с 150Gi до 200Gi:

1. Отредактировать в Git значение `spec.storage.size: 200Gi` и запушить коммит.
2. После синхронизации Argo CD проинспектировать статус файловой системы:
```bash
# Проверка отправки запроса на расширение в PVC
kubectl get pvc -n billing -l cnpg.io/cluster=billing-postgres
# → NAME                 STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → billing-postgres-1   Bound    pvc-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d   200Gi      RWO            ceph-rbd-sc    12d
# → billing-postgres-2   Bound    pvc-2b3c4d5e-6f7a-8b9c-0d1e-2f3a4b5c6d7e   200Gi      RWO            ceph-rbd-sc    12d
# → billing-postgres-3   Bound    pvc-3c4d5e6f-7a8b-9c0d-1e2f-3a4b5c6d7e8f   200Gi      RWO            ceph-rbd-sc    12d

# Проверка событий расширения на уровне блочного драйвера узла
kubectl describe pvc billing-postgres-1 -n billing | grep -A 5 Events
# → Events:
# →   Type    Reason                 Age    From                               Message
# →   ----    ------                 ----   ----                               -------
# →   Normal  Resizing               2m     external-resizer rbd.csi.ceph.com  External resizer is resizing volume pvc-1a2b3c4d
# →   Normal  FileSystemResizeSuccess 90s    kubelet, worker-node-03            MountVolume.NodeExpandVolume succeeded for volume
```

### 3. Регламентный Switchover (плановая ротация первичного узла)

Если необходимо провести регламентное обслуживание физического сервера, на котором работает Primary:

```bash
# Переключение роли лидера на конкретную реплику без генерации дрейфа для GitOps
kubectl cnpg switchover billing-postgres --target billing-postgres-2 -n billing
# → Step 1: Issuing switchover request... OK
# → Step 2: Waiting for billing-postgres-2 to become primary... OK
# → Switchover completed successfully. New primary: billing-postgres-2

# Проверка отсутствия аномального OutOfSync в Argo CD
argocd app get billing-app | grep Sync
# → Sync Status:       Synced to 4a12f8c
```

### 4. Временная приостановка (Suspend) GitOps для аварийных работ

```bash
# Argo CD: перевод приложения в ручной режим управления
argocd app set billing-app --sync-policy manual
# → Application 'billing-app' sync policy updated to manual

# Flux v2: полная приостановка цикла реконсиляции Kustomization
flux suspend kustomization databases-subsystem -n flux-system
# → ► suspending kustomization databases-subsystem in flux-system namespace
# → ✔ kustomization suspended

# Возврат к автоматической реконсиляции после завершения работ
flux resume kustomization databases-subsystem -n flux-system
# → ► resuming kustomization databases-subsystem in flux-system namespace
# → ✔ kustomization resumed
```

### 5. Ручной внеплановый бэкап и проверка восстановления в test-контур

```bash
# Создание мгновенного бэкапа перед рискованными операциями
kubectl cnpg backup billing-postgres --backup-name manual-pre-maintenance -n billing
# → Backup billing-postgres-manual-pre-maintenance created successfully

# Проверка завершения заливки бэкапа в MinIO/Ceph RGW
kubectl get backup -n billing manual-pre-maintenance
# → NAME                      AGE   CLUSTER            PHASE       ERROR
# → manual-pre-maintenance    3m    billing-postgres   completed   
```

---

## Диагностика и устранение неполадок

| Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **PVC завис в статусе `Terminating`** | Активен финализатор `kubernetes.io/pvc-protection`, том примонтирован подом или CSI-драйвер не отпустил lock. | `kubectl describe pvc <name>` → проверить секцию `Finalizers` и `Used By`. | Завершить pod-потребитель; убедиться, что том размонтирован на worker-ноде; при зависании CSI-демона проверить логи CSI nodeplugin. |
| **Под базы висит в `Pending`: `volume node affinity conflict`** | StorageClass имеет `volumeBindingMode: Immediate` с локальным хранилищем (Local PV), либо pod требует ноду, несовместимую с PV. | `kubectl describe pod <name>` → проверить события планировщика (Events). | Пересоздать StorageClass с `volumeBindingMode: WaitForFirstConsumer`; скорректировать правила `nodeAffinity` / `taints`. |
| **Вечный статус `OutOfSync` в Argo CD** | Оператор СУБД обновляет runtime-поля (`status`, LSN, `labels: role=primary`), которые не исключены из diff. | `argocd app diff <app-name>` → проверить, какие именно поля подсвечены зеленым/красным. | Добавить мутируемые поля в секцию `spec.ignoreDifferences` манифеста `Application` через `jsonPointers` или `jqPathExpressions`. |
| **Кластер СУБД удален после удаления папки в Git** | Включен `automated.prune: true`, отсутствовала аннотация `Prune=false` на кастомном ресурсе. | Проверить Git commit history и журнал аудита Argo CD (`kubectl get events -n argocd`). | Инициировать Disaster Recovery Runbook: остановить синк, развернуть кластер из бэкапа, вернуть манифесты в Git, добавить `Prune=false`. |
| **Ошибка при попытке изменить размер диска в StatefulSet** | Спецификация `volumeClaimTemplates` в нативном StatefulSet неизменяема на уровне API Kubernetes. | `kubectl apply` возвращает ошибку `spec: Forbidden: updates to statefulset spec for fields other than ... are forbidden`. | Использовать операторы баз данных, управляющие размером томов через CR; либо вручную патчить каждый PVC и удалять StatefulSet с каскадом `--cascade=orphan`. |
| **PreSync Job миграции схемы завис или упал** | Ошибка SQL-скрипта миграции, конфликт блокировок таблицы (`exclusive lock`), превышен `activeDeadlineSeconds`. | `kubectl logs job/<migration-job> -n <ns>` → просмотреть трейс утилиты миграции. | Исправить SQL-миграцию; устранить долгие блокировки в базе; перевыкатить Job с исправленным манифестом; синк завершится успешно. |
| **Потеря кворума брокеров Kafka при обновлении** | Использовался `podManagementPolicy: Parallel` или отсутствовал `PodDisruptionBudget` при ротации нод. | `kubectl get kafka` → статус `Degraded`; логи брокеров фиксируют `NotEnoughReplicasException`. | Установить `podManagementPolicy: OrderedReady`; настроить PDB (`minAvailable: 2`); поднимать поды по одному в ручном режиме. |
| **Сбой применения CRD при обновлении оператора** | Новая версия оператора добавила обязательные поля или изменила API-версию схемы, а Argo CD синкал ресурсы в одной волне. | `kubectl apply` выдает ошибку валидации схемы CRD. | Разносить установку CRD и самих инстансов кластеров по разным волнам (`sync-wave: -2` для CRD/оператора, `wave: 0` для баз данных). |

---

## Лучшие практики

1. **Принцип нулевого доверия к автоматическому Prune (`Prune=false`)**:
   Все ресурсы, связанные с сохранением данных (`Cluster`, `StatefulSet`, `PersistentVolumeClaim`), должны иметь явную аннотацию `argocd.argoproj.io/sync-options: Prune=false`. Удаление базы данных из кластера должно производиться исключительно осознанным ручным действием инженера.
2. **Явная фиксация `reclaimPolicy: Retain` в StorageClass**:
   Никогда не используйте StorageClass со значением `Delete` по умолчанию для продуктивных баз данных. При случайном удалении PVC дисковый том на Ceph или локальном массиве должен оставаться доступным для восстановления.
3. **Обязательный режим `volumeBindingMode: WaitForFirstConsumer`**:
   Данный режим устраняет гонки планировщика и привязку томов к неоптимальным или недоступным физическим серверам.
4. **Физическое разделение дисков данных (Data) и журнала транзакций (WAL/redo-log)**:
   Транзакционные журналы требуют минимальной латентности последовательной записи (`fsync`), тогда как табличные пространства генерируют случайный ввод-вывод. Разделение их по двум независимым томам (через `storage` и `walStorage`) предотвращает I/O-голодание СУБД.
5. **Защита кворума через PodDisruptionBudget**:
   Для любого кластера из $N \ge 3$ узлов всегда объявляйте манифест PDB с `maxUnavailable: 1` или `minAvailable: 2`. Это гарантирует, что плановое обслуживание гипервизоров и bare-metal серверов (`kubectl drain`) не приведет к деградации сервиса.
6. **Полная изоляция мажорных обновлений от GitOps-автоматики**:
   Никогда не переводите мажорные версии СУБД (например, переход на новый мажорный релиз PostgreSQL) в автоматический GitOps-синк. Выполняйте такие процедуры строго в рамках выделенных регламентных окон с ручным подтверждением (`Manual Sync / Sync Windows`).
7. **Регулярные учения по аварийному восстановлению (DR Drills)**:
   Бэкап, восстановление из которого ни разу не проверялось на практике, считается отсутствующим. Не реже одного раза в квартал развертывайте тестовый кластер из архивного бэкапа в изолированном staging-пространстве имен и выполняйте smoke-тестирование данных.
8. **Изоляция секретов и учетных записей**:
   Пароли суперпользователей баз данных не должны храниться в Git в открытом виде. Используйте [SOPS или External Secrets Operator](../secrets_encryption.md), либо доверяйте генерацию учетных записей операторам баз данных.

---

## Дополнительная информация

### Связанные концепции и смежные документы

- [Удаление и каскадная очистка в Argo CD](../ArgoCD/argocd_deletion_and_cleanup.md) — детальный разбор логики работы финализаторов, GC и режимов orphaning.
- [Игнорирование различий и дрейф](../ArgoCD/synchronization/ignore_differences.md) — глубокое погружение в настройку diffing-движка, JQ-выражений и Server-Side Diff.
- [Волны синхронизации и хуки](../ArgoCD/synchronization/scenarios/sync_waves_hooks.md) — управление фазами развертывания, PreSync Jobs и Health Gating.
- [Аварийное восстановление в Argo CD (Disaster Recovery)](../ArgoCD/argocd_disaster_recovery.md) — стратегии восстановления контроллеров и кластеров из резервных копий.
- [Шифрование и управление секретами в GitOps](../secrets_encryption.md) — безопасная передача паролей и сертификатов баз данных.
- [Мульти-кластерные паттерны в GitOps](./multi_cluster_patterns.md) — организация топологии доставки и различия StorageClass в распределенном парке кластеров.
- [PostgreSQL в Kubernetes (CloudNativePG)](../../Databases/PostgreSQL/Operations/kubernetes_deployment.md) — детальное руководство по эксплуатации оператора CloudNativePG на bare-metal.
- [Zalando Postgres Operator](../../Databases/PostgreSQL/Operations/zalando_postgres_operator.md) — альтернативный оператор баз данных на базе Patroni и Spilo.
- [Паттерны хранения для баз данных в Kubernetes](../../Kubernetes/Storage/database-storage-patterns.md) — требования СУБД к дисковой подсистеме, IOPS и latency.
- [StatefulSet: архитектурный обзор](../../Kubernetes/Base/StatefulSet/statefulset_overview.md) — базовые примитивы Kubernetes для нагрузок с состоянием.

---

## Вопросы для собеседования

### 1. Что произойдет с постоянными данными базы данных, если манифест StatefulSet будет случайно удален из Git-репозитория при включенной опции `prune: true`?
**Ответ:** По умолчанию в Kubernetes контроллер StatefulSet управляет жизненным циклом подов, но **не удаляет** связанные с ними PersistentVolumeClaim (PVC). При срабатывании `prune: true` Argo CD или Flux удалят объект `StatefulSet` и поды СУБД завершат работу, однако сами PVC останутся в кластере в статусе `Bound` вместе с данными на физических дисках. Чтобы восстановить сервис, достаточно вернуть манифест в Git — контроллер повторно подключит существующие PVC. **Главный риск:** если из Git удаляется не отдельный StatefulSet, а весь `Namespace` приложения, Kubernetes каскадно уничтожит все ресурсы внутри него, включая PVC. В этом случае сохранность данных на уровне On-Premise дисковой полки зависит исключительно от параметра `persistentVolumeReclaimPolicy: Retain` в `StorageClass`.

### 2. Как организуются миграции схемы БД в GitOps и что произойдет, если PreSync Job упадет с ошибкой?
**Ответ:** Миграция схемы упаковывается в Kubernetes `Job` и помечается аннотацией `argocd.argoproj.io/hook: PreSync` (либо шагом перед приложением во Flux). Argo CD сначала применяет `PreSync Job` и ожидает ее успешного завершения (`Completed`). Если миграция падает (Job переходит в `Error` / `BackoffLimitExceeded`), фаза синхронизации прерывается. Новая версия приложения (Deployment) не начинает выкатку, а старая стабильная версия продолжает обслуживать пользовательский трафик со старой схемой данных. Важно использовать аннотацию `hook-delete-policy: BeforeHookCreation`, чтобы упавший под миграции не удалялся немедленно, позволяя SRE-инженеру изучить логи ошибки через `kubectl logs`.

### 3. Почему попытка уменьшить размер диска в `spec.resources.requests.storage` через GitOps приводит к фатальной ошибке?
**Ответ:** Драйверы CSI и спецификация Kubernetes API поддерживают только **увеличение** емкости томов (Volume Expansion), если в StorageClass установлен флаг `allowVolumeExpansion: true`. Уменьшение файловых систем «на лету» физически небезопасно и запрещено валидатором API-сервера. Если инженер уменьшит значение `storage` в Git, контроллер GitOps вернет ошибку `FieldValueForbidden: field is immutable` при попытке патча PVC, а статус приложения навсегда зависнет в `SyncFailed`. Уменьшение диска возможно только путем создания нового PVC меньшего объема, ручной репликации/переноса данных и переключения StatefulSet.

### 4. Зачем для баз данных под управлением операторов (CloudNativePG, Strimzi) обязательно настраивать `ignoreDifferences`?
**Ответ:** Операторы баз данных непрерывно управляют рантаймом кластера и динамически выставляют аннотации, системные метки, статусы кворума, а также могут менять внутренние поля подов при ротации сертификатов или переключении лидера. Если GitOps-агент не настроен на игнорирование этих полей, он будет интерпретировать изменения оператора как дрейф конфигурации (`OutOfSync`) и пытаться перетереть их значениями из Git. Это порождает **войну контроллеров (reconciliation fight)**: GitOps накатывает свой манифест, оператор СУБД возвращает свое состояние, что приводит к циклическому рестарту подов базы данных.

### 5. Как выполнить плановый Switchover (переключение мастера) в кластере PostgreSQL без создания расхождения с Git?
**Ответ:** В современных операторах (например, CloudNativePG) текущий мастер не фиксируется жестко в манифесте `Cluster`, а определяется алгоритмом консенсуса оператора в рантайме. Ротация лидера инициируется через CLI оператора (`kubectl cnpg switchover`) или временную аннотацию. Манифест в Git описывает лишь желаемое количество реплик (например, `instances: 3`) и параметры пула. В результате плановое переключение мастера не меняет декларативное описание кластера в Git и не вызывает ложного `OutOfSync` в Argo CD.
