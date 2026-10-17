# Job и CronJob

**Актуально для:** Kubernetes 1.30–1.35+ (Bare-Metal / On-Premise)

## Определения

**Job** в Kubernetes — это контроллер пакетной обработки (API-группа `batch/v1`), создающий один или несколько подов и гарантирующий успешное завершение заданного числа подов с нулевым кодом возврата (**exit code 0**). В отличие от долгоживущих сервисов под управлением [Deployment](./Deployment/index.md) или [StatefulSet](../Base/StatefulSet/statefulset_overview.md), `Job` оптимизирован для задач с детерминированным жизненным циклом (batch processing, data engineering, регламентные утилиты).

**CronJob** — надстройка над Job (API-группа `batch/v1`, стабильная версия с v1.21), обеспечивающая периодический запуск пакетных задач по временной шкале cron. Он управляет созданием объектов Job в заданные моменты времени с учетом политик конкурентности и дедлайнов запуска.

**JobSet** — расширение API Kubernetes (Custom Resource Definition в рамках SIG-Batch, `jobset.x-k8s.io`), предназначенное для оркестрации группы взаимосвязанных Job как единой сущности. Обеспечивает семантику All-or-Nothing и сетевое обнаружение между подами через автоматический Headless Service.

**Indexed Job** — режим выполнения Job (`completionMode: Indexed`), при котором каждому поду назначается целочисленный индекс от `0` до `completions-1`. Номер индекса экспортируется в под через переменную окружения `JOB_COMPLETION_INDEX` и аннотацию `batch.kubernetes.io/job-completion-index`.

**Work Queue (Рабочая очередь)** — архитектурный паттерн пакетной обработки с нефиксированным числом задач, при котором параметр `completions` не задается, а несколько параллельных воркеров вычитывают единицы работы из внешнего брокера (RabbitMQ, Redis, СУБД) и завершаются при опустошении очереди.

### Ключевые сценарии использования в DevOps, SRE и системном администрировании

*   **Миграции схем баз данных:** применение структурированных изменений к СУБД (PostgreSQL, MySQL, ClickHouse) с помощью инструментов Flyway, Liquibase, Alembic, Django/Rails перед запуском или обновлением основного сервиса.
*   **Резервное копирование и экспорт дампов:** плановое создание физических и логических резервных копий (снимки `etcdctl snapshot save`, `pg_dump`, `mariabackup`) с последующей архивацией на локальные NFS-серверы, SAN/NAS или локальное S3-совместимое хранилище (MinIO, Ceph RGW). См. также **[Стратегии резервного копирования](../Operations/backup-strategies.md)**.
*   **Регламентное обслуживание и очистка кластера:** периодическое удаление устаревших ресурсов, чистка заброшенных `emptyDir`, ротация логов, проверка истечения сроков действия сертификатов, запуск аудиторов безопасности (Trivy, kube-bench).
*   **Тяжелая пакетная обработка и ETL:** пакетный импорт/экспорт данных, генерация бухгалтерских и аналитических отчетов, переиндексация поисковых движков, транскодирование медиафайлов.
*   **Хуки синхронизации GitOps:** выполнение разовых проверок конфигурации, прогрева кэша или инициализации инфраструктуры до или после выкатки релиза через ArgoCD. См. **[Хуки синхронизации (Hooks)](../../GitOps/ArgoCD/synchronization.md)**.

---

## Основные концепции и архитектура

### Архитектура контроллеров Job и CronJob

Управление пакетными нагрузками в Kubernetes разделено между двумя контроллерами внутри `kube-controller-manager`:

1.  **JobController:**
    *   Отслеживает объекты `Job` и связанные с ними поды через селектор меток `batch.kubernetes.io/job-name` и `batch.kubernetes.io/controller-uid`.
    *   Реализует reconcile-цикл: сравнивает текущее число успешных (`.status.succeeded`) и активных (`.status.active`) подов со значениями `spec.completions` и `spec.parallelism`.
    *   Обрабатывает сбои подов, управляет интервалами экспоненциального ожидания (`backoffLimit`), применяет правила `podFailurePolicy` и `successPolicy`.
    *   Управляет таймером жесткого прерывания `activeDeadlineSeconds` и удалением завершенных объектов через TTL-контроллер (`ttlSecondsAfterFinished`).
2.  **CronJobController:**
    *   Каждые 10 секунд проверяет расписание всех активных `CronJob`.
    *   Рассчитывает время последнего и следующего запуска на основе часового пояса (`timeZone`) и строки `schedule`.
    *   Создает манифест `Job` на основе `jobTemplate` при наступлении момента запуска, контролируя политики конкурентности (`concurrencyPolicy`) и отсекая просроченные запуски (`startingDeadlineSeconds`).

```
 +-------------------------------------------------------------+
 |                  kube-controller-manager                    |
 |                                                             |
 |  +--------------------+             +--------------------+  |
 |  | CronJobController  |             |   JobController    |  |
 |  | (Schedule / Sync)  |             | (Reconcile Loop)   |  |
 |  +---------+----------+             +---------+----------+  |
 +------------|----------------------------------|-------------+
              | создает Job по таймеру           |
              v                                  v создает / перезапускает
       +--------------+                   +--------------+
       |   CronJob    |                   |     Job      |
       +--------------+                   +-------+------+
                                                  |
                     +----------------------------+----------------------------+
                     |                            |                            |
                     v                            v                            v
              +--------------+             +--------------+             +--------------+
              | Pod 0 (Exit) |             | Pod 1 (Work) |             | Pod 2 (Wait) |
              +--------------+             +--------------+             +--------------+
```

### Параметры спецификации Job

*   **`template`**: Спецификация пода (`PodTemplateSpec`).
*   **`restartPolicy`**: Допустимы только два значения: `Never` или `OnFailure`.
*   **`completions`**: Количество успешных завершений подов для признания Job выполненным (по умолчанию `1`). При отсутствии поля активируется режим рабочей очереди (Work Queue).
*   **`parallelism`**: Максимальное количество одновременно исполняемых подов (по умолчанию `1`). Значение `0` замораживает создание подов до ручного увеличения.
*   **`completionMode`**:
    *   `NonIndexed` (по умолчанию): поды взаимозаменяемы и не имеют постоянной нумерации.
    *   `Indexed`: поды получают фиксированные индексы от `0` до `completions-1`.
*   **`backoffLimit`**: Предельное количество попыток перезапуска при сбоях (по умолчанию `6`). При превышении лимита Job переходит в терминальное состояние `Failed`.
*   **`backoffLimitPerIndex` (GA v1.33)**: Задает независимый лимит повторов для каждого индекса в `Indexed` Job. Требует `completionMode: Indexed` и `restartPolicy: Never`. Исключает ситуацию, когда один сбойный индекс исчерпывает общий лимит попыток всего задания. Количество падений на индекс сохраняется в аннотации `batch.kubernetes.io/job-index-failure-count`.
*   **`maxFailedIndexes`**: Максимально допустимое число упавших индексов при использовании `backoffLimitPerIndex`. Если упавших индексов меньше либо равно лимиту, Job завершится со статусом `Complete`, сохранив список проблемных индексов в поле `.status.failedIndexes` (например, `1,4-6`).
*   **`activeDeadlineSeconds`**: Предельное время выполнения Job в секундах. Отсчет начинается с момента запуска первого пода. По истечении таймера контроллер принудительно удаляет активные поды и маркирует Job условием `DeadlineExceeded` (`Failed`). Имеет безусловный приоритет над `backoffLimit`. При `suspend: true` таймер замораживается. Начиная с v1.31 терминальный статус выставляется только после полной остановки всех подов.
*   **`ttlSecondsAfterFinished`**: Интервал в секундах, по истечении которого завершенный Job (как успешный, так и упавший) вместе со своими подами автоматически удаляется TTL-контроллером. Предотвращает разрастание базы данных `etcd`.
*   **`suspend`**: Флаг ручной или автоматической приостановки создания подов (`true`/`false`). В приостановленном Job активные поды штатно останавливаются. Начиная с **v1.36 (Beta)**, в приостановленных Job разрешено «на лету» обновлять ресурсы (`cpu`, `memory`), лимиты и параметры планирования (`nodeSelector`, `affinity`, `tolerations`) в шаблоне пода.
*   **`managedBy` (GA v1.35)**: Имя внешнего контроллера-оркестратора (например, `kueue.x-k8s.io/kueue`). Встроенный `JobController` полностью игнорирует такие объекты, позволяя сторонним планировщикам управлять очередями без конфликтов на уровне API. Поле неизменяемо после создания.

### Глубокий разбор: `restartPolicy: Never` против `restartPolicy: OnFailure`

Выбор `restartPolicy` кардинально меняет поведение пода, kubelet и контроллера Job при возникновении ошибки:

| Параметр | `restartPolicy: Never` | `restartPolicy: OnFailure` |
| :--- | :--- | :--- |
| **Реакция kubelet на падение процесса** | Не перезапускает контейнер; под переходит в терминальную фазу `Failed`. | Перезапускает контейнер внутри того же пода с задержкой CrashLoopBackOff (`10s`..`300s`). |
| **Реакция JobController** | Создает **новый Pod** с новым UID и чистым окружением. | Ждет успешного завершения контейнера внутри существующего пода. |
| **Что считает `backoffLimit`** | Количество созданных **новых подов-замен** после сбоя. | Количество **внутренних перезапусков контейнера** в рамках пода. |
| **Сохранность логов для отладки** | Идеальная: логи каждого упавшего пода сохраняются отдельно (`kubectl logs <pod-name>`). | Ограниченная: доступны только текущие логи и предыдущий запуск (`kubectl logs -p`). |
| **Состояние локальных томов (`emptyDir`)** | Каждый новый под получает новый, чистый `emptyDir`. | Данные в `emptyDir` сохраняются между перезапусками контейнера. |
| **Совместимость с `podFailurePolicy`** | Полная совместимость. | **Не поддерживается** (API требует `Never` для детальных политик сбоев). |
| **Совместимость с `backoffLimitPerIndex`** | Полная совместимость. | **Не поддерживается** (требует `Never`). |
| **Рекомендация для Production** | **Рекомендуется** для транзакционных задач, миграций и надежной аналитики инцидентов. | Допустимо только для легковесных скриптов с локальным кэшированием в `emptyDir`. |

### Политики управления сбоями и успехом

#### 1. `podFailurePolicy` (GA v1.31)

Позволяет точно настраивать реакцию контроллера на сбои на основе кодов возврата контейнеров (`onExitCodes`) или системных состояний пода (`onPodConditions`).

Доступные действия (`action`):
*   **`FailJob`**: немедленно перевести весь Job в статус `Failed`, прервав выполнение всех активных подов (применяется при критических ошибках конфигурации, синтаксиса или неисправимых сбоях данных).
*   **`Ignore`**: не учитывать данный сбой в общем счетчике `backoffLimit` (критично для защиты от инфраструктурных сбоев узлов).
*   **`Count`**: стандартное поведение — учесть падение в счетчике `backoffLimit`.
*   **`FailIndex`**: пометить конкретный индекс в `Indexed` Job как неудачный и остановить попытки его перезапуска, не ломая остальные индексы.

> [!IMPORTANT]
> **Защита от инфраструктурных прерываний:** при дренаже узла (`kubectl drain`) или вытеснении подов из-за дефицита ресурсов под получает условие `DisruptionTarget`. Без `podFailurePolicy` такие вытеснения сжигают `backoffLimit` прикладного Job, приводя к ложному падению бизнес-задач при плановом техобслуживании нод.

#### 2. `successPolicy` (GA v1.33)

Позволяет объявить `Indexed` Job успешно завершенным досрочно при выполнении правил:
*   `succeededIndexes`: список индексов (например, `"0"` для схемы Лидер-Воркеры, где индекс 0 агрегирует данные и подтверждает успешность всей распределенной цепочки).
*   `succeededCount`: необходимое количество успешно выполненных индексов из общего пула.

#### 3. `podReplacementPolicy` (GA v1.34)

Определяет момент времени, когда контроллер создает замену завершающемуся или сбойному поду:
*   `TerminatingOrFailed` (по умолчанию): под-замена создается сразу же, как только старый под перешел в состояние `Terminating` (отправлен `SIGTERM`). Обеспечивает максимальную скорость работы.
*   `Failed`: контроллер ожидает полного завершения и удаления пода (`Terminated`) перед созданием нового. Это критично для bare-metal инфраструктуры, где поды используют эксклюзивные блокировки файлов, hostPort, эксклюзивные блочные тома (RWO) или выделенные аппаратные устройства (PCIe passthrough), чтобы исключить конфликт параллельного доступа между старым и новым экземпляром.

---

### Спецификация и нюансы CronJob

*   **`schedule`**: Строка расписания в стандартном 5-польном формате cron (`минуты часы день-месяца месяц день-недели`). Поддерживаются именованные дескрипторы (`@hourly`, `@daily`, `@weekly`) и интервальные выражения (`@every 30m`). Расписание по умолчанию интерпретируется в часовом поясе контроллера (UTC).
*   **`timeZone` (GA v1.27)**: Имя часового пояса из базы IANA (например, `UTC`, `Europe/Moscow`, `Asia/Almaty`). Исключает сдвиги выполнения при переходе на летнее/зимнее время.
    *   *Внимание:* указание префиксов `CRON_TZ` или `TZ` непосредственно в строке `schedule` не поддерживается и блокируется валидатором API-сервера.
*   **`concurrencyPolicy`**:
    *   `Allow` (по умолчанию): новые Job запускаются параллельно, даже если предыдущий экземпляр еще выполняется.
    *   `Forbid`: если предыдущий Job еще активен, новый запланированный запуск **пропускается**. Оптимально для тяжелых бэкапов и длительных регламентных скриптов.
    *   `Replace`: если предыдущий Job еще активен, он принудительно отменяется и удаляется, а вместо него запускается новый Job.
*   **`startingDeadlineSeconds`**: Временное окно (в секундах), в течение которого контроллер имеет право запустить задачу, если плановый момент старта был пропущен (например, из-за недоступности `kube-controller-manager` или остановки планирования через `suspend: true`).
    *   *Важно:* значение не должно быть меньше 10 секунд (период тика контроллера).
*   **Ловушка 100 пропущенных стартов (The 100 Missed Schedules Rule):**
    Если `startingDeadlineSeconds` **не задан**, а контроллер по любой причине (простой control-plane, рассинхронизация времени на мастер-нодах, долгий `suspend: true`) пропустил **более 100 запланированных интервалов**, CronJob навсегда прекращает запуск задач. В событиях появляется фатальная ошибка:
    `Too many missed start time (> 100). Set or decrease .spec.startingDeadlineSeconds or check clock skew.`
    Установка `startingDeadlineSeconds` (например, `300`–`600`) ограничивает глубину проверки пропусков только указанным окном и предотвращает полную блокировку CronJob.
*   **`successfulJobsHistoryLimit` / `failedJobsHistoryLimit`**: Количество завершенных объектов Job, сохраняемых в кластере (по умолчанию `3` успешных и `1` неудачный). При превышении старые Job удаляются вместе с логами. Для критичных задач рекомендуется увеличивать лимит неудачных задач (`failedJobsHistoryLimit: 5`..`10`), чтобы у дежурного инженера сохранялись логи упавших подов для постмортема.

---

### Взаимодействие с Native Sidecars (GA v1.33 / Beta v1.29)

До версии Kubernetes 1.28 классической проблемой пакетных задач было «вечное зависание» Job в статусе `Running`: вспомогательные sidecar-контейнеры (Vault Agent, Envoy/Istio-прокси, локальные лог-шипперы) продолжали работать после того, как основной рабочий процесс завершился. Контроллер не мог признать Job выполненным, так как не все контейнеры пода завершили работу.

С появлением **Native Sidecar Containers** (init-контейнеры со свойством `restartPolicy: Always`) поведение изменилось:
1.  Kubelet запускает sidecar-контейнер до старта основных контейнеров.
2.  После того как все основные контейнеры завершают работу с кодом 0, kubelet автоматически отправляет сигнал `SIGTERM` всем native sidecar-контейнерам.
3.  Под переходит в фазу `Succeeded`, а Job успешно завершается.

Подробнее о паттернах сайдкаров см. в **[Паттерны sidecar-контейнеров](./Pod/pod_sidecar_patterns.md)**.

---

### JobSet — распределенные пакетные нагрузки на Bare-Metal

В отличие от стандартного Job, работающего с однородными подами, **JobSet** (`jobset.x-k8s.io`) позволяет оркестрировать сложные распределенные нагрузки:

*   **Группировка разнородных ролей:** одновременный запуск мастер-узла (`coordinator`) и нескольких групп исполнителей (`workers`) с разными шаблонами подов, лимитами памяти и аргументами.
*   **Сетевая топология через Headless Service:** автоматическое выделение стабильных сетевых доменных имен по схеме:
    `<jobset-name>-<replicated-job-name>-<index>.<service-name>`
    Это позволяет узлам обмениваться данными напрямую по стабильным адресам без предварительной регистрации в центральном реестре.
*   **Семантика All-or-Nothing:** если один из ключевых воркеров распределенного вычислительного конвейера падает, JobSet перезапускает всю группу целиком, исключая порчу промежуточных данных.
*   **Интеграция с очередями [Kueue](../Scheduling/kueue.md):** задание удерживается в состоянии `suspend`, пока планировщик не гарантирует наличие всех необходимых вычислительных мощностей (gang scheduling).

---

## Практические сценарии и конфигурация

### 1. Продакшн-миграция базы данных (DevOps / CI/CD)

Идемпотентная миграция схемы PostgreSQL с жесткими тайм-аутами, ограничением попыток, безопасным контекстом (non-root) и автоматической очисткой завершенного объекта.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration-v42
  namespace: production
  labels:
    app.kubernetes.io/component: db-migration
spec:
  backoffLimit: 3                  # Максимум 3 попытки при сбоях
  activeDeadlineSeconds: 600       # Жёсткий потолок: 10 минут на всю миграцию
  ttlSecondsAfterFinished: 600     # Автоочистка через 10 минут после завершения
  podReplacementPolicy: Failed     # Не запускать замену, пока старый под не завершился
  template:
    metadata:
      labels:
        app.kubernetes.io/component: db-migration
    spec:
      restartPolicy: Never         # Обязательно: чистый перезапуск в новом поде
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: flyway-migration
        image: flyway/flyway:10.10-alpine
        command: ["flyway", "migrate"]
        resources:
          requests:
            cpu: 200m
            memory: 256Mi
          limits:
            cpu: 1000m
            memory: 512Mi
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
        env:
        - name: FLYWAY_URL
          value: "jdbc:postgresql://postgres-ha.database.svc.cluster.local:5432/app_db"
        - name: FLYWAY_USER
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: username
        - name: FLYWAY_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: password
```

### 2. Регламентный бэкап СУБД через CronJob с защитой от наслоений

Ежедневный бэкап PostgreSQL с блокировкой параллельных запусков (`concurrencyPolicy: Forbid`), фиксацией таймзоны, защитой от пропуска стартов и сохранением дампа на выделенный локальный том (NFS/Ceph).

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgres-nightly-backup
  namespace: ops-tools
spec:
  schedule: "0 2 * * *"                     # Каждый день в 02:00
  timeZone: "Europe/Moscow"                 # Локальный часовой пояс
  concurrencyPolicy: Forbid                 # Запрет параллельного запуска
  startingDeadlineSeconds: 300              # Допустимое окно опоздания запуска
  successfulJobsHistoryLimit: 3             # Хранить 3 успешных запуска
  failedJobsHistoryLimit: 7                 # Хранить 7 упавших для анализа
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 7200           # Максимум 2 часа на снятие дампа
      ttlSecondsAfterFinished: 86400        # Очистить Job через сутки
      template:
        spec:
          restartPolicy: OnFailure
          securityContext:
            runAsNonRoot: true
            runAsUser: 999
          volumes:
          - name: backup-storage
            persistentVolumeClaim:
              claimName: onprem-nfs-backups-pvc
          containers:
          - name: pg-dump
            image: postgres:16-alpine
            command:
            - /bin/sh
            - -c
            - |
              set -eo pipefail
              TIMESTAMP=$(date +%Y%m%d_%H%M%S)
              BACKUP_FILE="/backups/pg_dump_${TIMESTAMP}.sql.gz"
              echo "Starting backup to ${BACKUP_FILE}..."
              pg_dump -h pg-cluster.database.svc.cluster.local -U postgres -d main_db | gzip > "${BACKUP_FILE}"
              echo "Backup completed successfully. Size: $(du -h ${BACKUP_FILE} | cut -f1)"
            resources:
              requests:
                cpu: 500m
                memory: 512Mi
              limits:
                cpu: 2000m
                memory: 2Gi
            volumeMounts:
            - name: backup-storage
              mountPath: /backups
            env:
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef:
                  name: pg-backup-secret
                  key: password
```

### 3. Шардированная обработка (Indexed Job + FailIndex)

Параллельная обработка 8 партиций данных. При падении воркера с фатальным кодом ошибки `42` повторы для данного индекса прекращаются (`FailIndex`), а остальные индексы продолжают обработку. Если падает более 2 индексов (`maxFailedIndexes: 2`), весь Job признается неудачным.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: sharded-data-etl
  namespace: batch-processing
spec:
  completions: 8
  parallelism: 4
  completionMode: Indexed
  backoffLimitPerIndex: 2                   # Максимум 2 повтора на каждый индекс
  maxFailedIndexes: 2                       # Допустимо до 2 сбойных шардов
  podFailurePolicy:
    rules:
    - action: Ignore
      onPodConditions:
      - type: DisruptionTarget              # Игнорировать вытеснение ноды
    - action: FailIndex
      onExitCodes:
        operator: In
        values: [42]                        # Код 42: поврежденные данные шарда, не ретраить
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: etl-worker
        image: internal-registry.company.lan/data-tools/worker:v1.4
        command: ["/app/process-shard"]
        args: ["--partition", "$(JOB_COMPLETION_INDEX)"]
        env:
        - name: JOB_COMPLETION_INDEX
          valueFrom:
            fieldRef:
              fieldPath: metadata.annotations['batch.kubernetes.io/job-completion-index']
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 1500m
            memory: 2Gi
```

### 4. Динамическая очередь задач (Work Queue Pattern)

Параллельные воркеры вычитывают сообщения из локального брокера RabbitMQ/Redis. `completions` намеренно опущен. Как только очередь пустеет, приложение завершает процесс с кодом 0.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: redis-queue-processor
  namespace: batch-processing
spec:
  parallelism: 5                           # 5 параллельных воркеров
  # completions НЕ задан: режим рабочей очереди
  activeDeadlineSeconds: 3600              # Общий дедлайн 1 час
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: queue-consumer
        image: internal-registry.company.lan/apps/queue-consumer:v2.1
        env:
        - name: REDIS_ENDPOINT
          value: "redis-cluster.database.svc.cluster.local:6379"
        resources:
          requests:
            cpu: 250m
            memory: 256Mi
          limits:
            cpu: 1000m
            memory: 512Mi
```

### 5. Защита от вытеснений при обслуживании нод (Node Drain)

Конфигурация Job с защитой от ложного падения во время проведения регламентных работ системными администраторами (перезагрузка серверов, `kubectl drain`).

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: resilient-data-cruncher
  namespace: analytics
spec:
  backoffLimit: 4
  podFailurePolicy:
    rules:
    - action: Ignore                        # Вытеснение не тратит счетчик backoffLimit
      onPodConditions:
      - type: DisruptionTarget
    - action: FailJob                       # Ошибки валидации конфигурации фатальны
      onExitCodes:
        containerName: cruncher
        operator: In
        values: [2, 126, 127]
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: cruncher
        image: debian:12-slim
        command: ["/bin/sh", "-c"]
        args:
        - |
          trap 'echo "SIGTERM received, flushing buffer..."; exit 0' TERM
          echo "Processing batch..."
          sleep 300
```

---

## Операции и команды (kubectl)

### Управление и инспекция Job

```bash
# Императивное создание разового Job для быстрой диагностики
kubectl create job test-dns --image=busybox:1.36 -- nslookup kubernetes.default.svc
# → job.batch/test-dns created

# Создание Job из манифеста
kubectl apply -f job.yaml
# → job.batch/db-migration-v42 created

# Ожидание завершения выполнения в скриптах автоматизации и CI/CD
kubectl wait --for=condition=complete job/db-migration-v42 --timeout=300s
# → job.batch/db-migration-v42 condition met

# Просмотр статуса Job (колонки: COMPLETIONS, DURATION, AGE)
kubectl get jobs -n production
# → NAME                 COMPLETIONS   DURATION   AGE
# → db-migration-v42     1/1           42s        2m

# Детальная инспекция событий, условий и причин падения
kubectl describe job db-migration-v42 -n production

# Получение логов для одиночного Job
kubectl logs job/db-migration-v42 -n production
# → [INFO] Database schema successfully migrated to version 42.

# Сбор логов со всех подов многопоточного Job по метке
kubectl logs -n batch-processing -l batch.kubernetes.io/job-name=sharded-data-etl \
  --all-containers=true --prefix=true
# → [pod/sharded-data-etl-0-xxxx/etl-worker] Processing partition 0
# → [pod/sharded-data-etl-1-yyyy/etl-worker] Processing partition 1

# Проверка кодов возврата завершившихся подов через jsonpath
kubectl get pods -n batch-processing -l batch.kubernetes.io/job-name=sharded-data-etl \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\tExitCode: "}{.status.containerStatuses[*].state.terminated.exitCode}{"\n"}{end}'
# → sharded-data-etl-0-xxxx	ExitCode: 0
# → sharded-data-etl-1-yyyy	ExitCode: 0

# Заморозка выполнения (suspend) и возобновление
kubectl patch job db-migration-v42 -p '{"spec":{"suspend":true}}'
# → job.batch/db-migration-v42 patched
kubectl patch job db-migration-v42 -p '{"spec":{"suspend":false}}'
# → job.batch/db-migration-v42 patched

# Удаление Job и связанных с ним подов
kubectl delete job db-migration-v42 -n production
# → job.batch "db-migration-v42" deleted

# Массовая очистка всех завершенных Job в пространстве имен
kubectl delete jobs --field-selector status.successful=1 -n batch-processing
# → job.batch "sharded-data-etl" deleted
```

### Управление и отладка CronJob

```bash
# Императивное создание CronJob
kubectl create cronjob log-cleaner --schedule="0 3 * * *" \
  --image=busybox:1.36 -- /bin/sh -c "find /var/log -type f -mtime +7 -delete"
# → cronjob.batch/log-cleaner created

# Просмотр списка CronJob (колонки: SCHEDULE, SUSPEND, ACTIVE, LAST SCHEDULE)
kubectl get cronjobs -n ops-tools
# → NAME                      SCHEDULE    SUSPEND   ACTIVE   LAST SCHEDULE   AGE
# → postgres-nightly-backup   0 2 * * *   False     0        18h             5d

# Принудительный ручной запуск CronJob вне расписания (создает разовый Job)
kubectl create job manual-backup-run --from=cronjob/postgres-nightly-backup -n ops-tools
# → job.batch/manual-backup-run created

# Временная приостановка выполнения CronJob без удаления
kubectl patch cronjob postgres-nightly-backup -n ops-tools -p '{"spec":{"suspend":true}}'
# → cronjob.batch/postgres-nightly-backup patched

# Снятие с паузы
kubectl patch cronjob postgres-nightly-backup -n ops-tools -p '{"spec":{"suspend":false}}'
# → cronjob.batch/postgres-nightly-backup patched

# Поиск Job, созданных конкретным CronJob
kubectl get jobs -n ops-tools -o json | jq -r \
  '.items[] | select(.metadata.ownerReferences[0].name=="postgres-nightly-backup") | .metadata.name'
# → postgres-nightly-backup-28956480
# → postgres-nightly-backup-28957920
```

---

## Мониторинг и алертинг (SRE)

Сбои пакетных и фоновых задач часто протекают незаметно, так как они не вызывают всплеска 5xx HTTP-ошибок в ingress. Мониторинг batch-нагрузок строится на базе метрик **kube-state-metrics** (`kube-prometheus-stack`).

### Ключевые метрики Prometheus

| Метрика | Тип | Описание и назначение в SRE |
| :--- | :--- | :--- |
| `kube_job_status_succeeded` | Gauge | Количество успешно завершившихся подов в рамках Job. |
| `kube_job_status_failed` | Gauge | Текущее количество неудачных попыток запуска подов. |
| `kube_job_failed` | Gauge (0/1) | Флаг окончательного перехода Job в фатальное состояние `Failed`. |
| `kube_job_status_start_time` | Gauge | Unix-timestamp старта выполнения Job. |
| `kube_cronjob_status_last_schedule_time` | Gauge | Unix-timestamp последнего запланированного старта CronJob. |
| `kube_cronjob_status_active` | Gauge | Количество одновременно исполняемых в данный момент Job от CronJob. |
| `kube_cronjob_spec_suspend` | Gauge (0/1) | Флаг нахождения CronJob в состоянии паузы. |

### SRE Golden Signals для пакетных задач

1.  **Частота сбоев (Failure Rate):** доля окончательно упавших Job (`kube_job_failed == 1`).
2.  **Задержка расписания (Schedule Lag):** разница между текущим временем и `kube_cronjob_status_last_schedule_time`. Если интервал превышает регламентный период + дедлайн, CronJob считается «зависшим» или «онемевшим».
3.  **Длительность выполнения (Run Duration):** время выполнения активного Job `time() - kube_job_status_start_time`. Рост длительности свидетельствует о дедлоках СУБД или сетевых зависаниях.
4.  **Насыщение ресурсов (Resource Saturation):** CPU Throttling и утилизация памяти (WorkingSet) воркерами Job. Падение с exit code 137 свидетельствует об OOMKilled.

### Готовые правила PrometheusRule

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: kubernetes-batch-alerts
  namespace: monitoring
spec:
  groups:
  - name: batch.workloads
    rules:
    - alert: CronJobNotScheduledRecently
      expr: |
        time() - kube_cronjob_status_last_schedule_time{cronjob="postgres-nightly-backup"} > 26 * 3600
        and on(cronjob, namespace) kube_cronjob_spec_suspend == 0
      for: 30m
      labels:
        severity: critical
        tier: platform
      annotations:
        summary: "CronJob {{ $labels.namespace }}/{{ $labels.cronjob }} не запускался более 26 часов"
        description: "Периодическая задача бэкапа не была запущена вовремя. Проверьте состояние контроллера, clock skew и лимит 100 пропусков."

    - alert: JobFailedPermanently
      expr: kube_job_failed{job_name=~".+"} == 1
      for: 5m
      labels:
        severity: warning
        tier: workloads
      annotations:
        summary: "Пакетная задача {{ $labels.namespace }}/{{ $labels.job_name }} завершилась с ошибкой"
        description: "Job исчерпал лимит backoffLimit или превысил activeDeadlineSeconds. Изучите логи упавших подов через kubectl logs."

    - alert: JobExecutionTimeExceeded
      expr: |
        (time() - kube_job_status_start_time) > 3600
        and on(job_name, namespace) kube_job_status_active > 0
      for: 15m
      labels:
        severity: warning
        tier: workloads
      annotations:
        summary: "Job {{ $labels.namespace }}/{{ $labels.job_name }} выполняется дольше 1 часа"
        description: "Задача работает аномально долго. Возможен deadlock в базе данных или бесконечный цикл."
```

Подробнее о мониторинге пакетных задач см. **[Алерты для Kubernetes-приложений](../../Grafana/alerting/kubernetes_alerts.md)**.

---

## Диагностика и устранение неполадок (Troubleshooting)

### Сводная матрица типовых неисправностей

| Симптом | Первопричина | Метод локализации | Решение |
| :--- | :--- | :--- | :--- |
| Job «намертво» висит в `Running`, поды не завершаются | Процесс заблокирован на блокировке БД, ожидает ввода `stdin` или legacy-сайдкар держит под | `kubectl describe pod`, проверка `pg_stat_activity`, проверка статуса контейнеров | Задать `activeDeadlineSeconds`; настроить таймауты сетевых клиентов; перевести sidecars в Native Sidecars. |
| Событие `BackoffLimitExceeded`, статус `Failed` | Команда завершается с ненулевым кодом выхода, исчерпан лимит попыток | `kubectl logs <pod-name> --previous`, чтение exit code | Исправить баг в приложении; исправить переменные окружения/секреты; настроить `podFailurePolicy`. |
| Под завершается с ошибкой `OOMKilled` (Exit code 137) | Превышен лимит `resources.limits.memory` | `kubectl get pod -o yaml` (`terminated.reason: OOMKilled`) | Увеличить `limits.memory` в шаблоне пода; оптимизировать batch-размер выборки в приложении. |
| CronJob перестал создавать Job («онемел») | Превышен лимит в 100 пропущенных стартов; неверная таймзона; `suspend: true` | `kubectl describe cronjob` (`TooManyMissedStartTimes`) | Указать `startingDeadlineSeconds: 300`; проверить корректность `timeZone`; снять с `suspend`. |
| Дедлоки и конфликт портов/томов при перезапуске пода | Замена стартует до завершения старого пода | `kubectl get pods -w`, ошибки монтирования томов RWO | Задать в манифесте `spec.podReplacementPolicy: Failed`. |
| Вытеснение ноды при drain приводит к сбою Job | Kubelet завершает поды, сжигая счетчик `backoffLimit` | Событие `DisruptionTarget` в `.status.conditions` пода | Добавить правило в `podFailurePolicy` с действием `action: Ignore` на условие `DisruptionTarget`. |
| Замусоривание etcd сотнями Completed подов | В манифесте Job не настроена автоматическая ротация | Тысячи объектов в `kubectl get jobs -A` | Настроить `ttlSecondsAfterFinished: 300` (для Job) и `successfulJobsHistoryLimit` (для CronJob). |

### Детальные сценарии отладки

#### 1. Анализ падений и кодов возврата

Если Job перешел в состояние `Failed`, необходимо выяснить код завершения процесса:

```bash
# 1. Поиск упавших подов
kubectl get pods -l batch.kubernetes.io/job-name=db-migration-v42 --field-selector status.phase=Failed

# 2. Быстрое чтение exit code и причины
kubectl get pod db-migration-v42-failed-pod -o jsonpath='{range .status.containerStatuses[*]}{.name}{": "}{.state.terminated.reason}{" (exit code: "}{.state.terminated.exitCode}{")\n"}{end}'
# → flyway-migration: Error (exit code: 1)

# 3. Чтение логов аварийного завершения
kubectl logs db-migration-v42-failed-pod -c flyway-migration
```

Типовые коды возврата Linux:
*   `1`: Общая ошибка выполнения (синтаксис, исключение в приложении).
*   `126`: Команда не может быть выполнена (нет прав на запуск binary-файла).
*   `127`: Команда не найдена (неверный путь в `command` или отсутствует утилита в образе).
*   `137` (128 + 9): Процесс принудительно убит по сигналу `SIGKILL` ядром ОС (чаще всего **OOMKilled** из-за превышения лимитов памяти).
*   `143` (128 + 15): Процесс завершен по сигналу `SIGTERM` (истек `activeDeadlineSeconds` или выполнен `kubectl drain`).

#### 2. Разблокировка застрявшего CronJob (Too Many Missed Starts)

Если CronJob перестал генерировать задачи из-за превышения порога в 100 пропусков:

```bash
# 1. Проверка наличия ошибки в описании
kubectl describe cronjob postgres-nightly-backup | grep -E "TooManyMissed|Warning"

# 2. Исправление манифеста на лету: добавление startingDeadlineSeconds
kubectl patch cronjob postgres-nightly-backup -p '{"spec":{"startingDeadlineSeconds":600}}'

# 3. Пересоздание объекта при необходимости жесткого сброса счетчиков
kubectl get cronjob postgres-nightly-backup -o yaml > cronjob-backup.yaml
kubectl replace --force -f cronjob-backup.yaml
```

#### 3. Онлайн-диагностика зависшего Job через Ephemeral Containers

Если контейнер Job работает бесконечно, не завершаясь, системный администратор может подключить временный контейнер отладки для анализа процессов:

```bash
# Подключение ephemeral-контейнера к зависшему поду
kubectl debug -it db-migration-v42-running-pod --image=nicolaka/netshoot --target=flyway-migration

# Внутри debug-контейнера: проверка системных вызовов и открытых сокетов
strace -p 1
ss -tuna
```

Подробнее о механизме Ephemeral Containers см. в руководстве **[Отладка через Ephemeral Containers](./Pod/ephemeral_containers.md)**.
Общий алгоритм локализации проблем узлов и подов разобран в **[Troubleshooting Kubernetes](../Troubleshooting/troubleshooting_overview.md)**.

---

## Лучшие практики (Best Practices)

### Чек-лист надежности для DevOps и SRE инженеров

1.  **Триада обязательных предохранителей:**
    *   **`activeDeadlineSeconds`** — обязательно задавать для всех без исключения Job. Это гарантирует, что зависший сетевой вызов или блокировка транзакции в СУБД не оставят под запущенным бесконечно.
    *   **`backoffLimit`** — выставлять значение от `3` до `5`. Не оставляйте лимит бесконечным; если миграция или batch упали 3 раза подряд, четвертый запуск с теми же входными данными приведет к тому же результату.
    *   **`ttlSecondsAfterFinished`** — задавать интервал от `300` до `3600` секунд для очистки завершенных Job, освобождая ресурсы `etcd` и исключая исчерпание пула IP-адресов CNI-плагина.
2.  **Проектирование идемпотентности:**
    *   Kubernetes не обеспечивает семантику «строго однократного» выполнения (*exactly-once*). Из-за перезапуска узлов, временной потери связи с kubelet или восстановления контроллера под Job может быть запущен повторно.
    *   Скрипты миграций, пакетной загрузки и обработки данных должны быть строго **идемпотентными** (повторный запуск с теми же входными данными должен приводить к идентичному состоянию системы, не создавая дубликатов). Используйте транзакции, распределенные блокировки (`pg_advisory_lock`) или таблицы состояний.
3.  **Корректная обработка `SIGTERM` (Graceful Shutdown):**
    *   При наступлении `activeDeadlineSeconds` или вытеснении пода kubelet посылает процессу сигнал `SIGTERM`.
    *   Batch-приложение должно перехватывать этот сигнал, сбрасывать промежуточные буферы на диск, корректно закрывать соединения с базой данных и освобождать полученные локи до истечения `terminationGracePeriodSeconds`, после чего ядро пошлет `SIGKILL`.
4.  **Безопасность (Pod Security Standards Restricted):**
    *   Никогда не запускайте пакетные поды под пользователем `root`. Включайте в манифесте `runAsNonRoot: true` и назначайте произвольный числовой UID (`runAsUser: 10001`).
    *   Используйте `readOnlyRootFilesystem: true`. Для записи временных файлов подключайте локальный том `emptyDir` с типом памяти (`medium: Memory`).
    *   Отключайте монтирование служебного токена ServiceAccount (`automountServiceAccountToken: false`), если Job не взаимодействует с API Kubernetes.
5.  **Изоляция и приоритизация ресурсов кластера:**
    *   Всегда указывайте `resources.requests` и `resources.limits`. Пакетные нагрузки склонны утилизировать 100% доступного процессорного времени, создавая эффект шумного соседа (*noisy neighbor*) для критичных веб-сервисов.
    *   Для тяжелых фоновых задач используйте выделенный **`PriorityClass`** с низким весом (`priority: 1000`) и политикой вытеснения `preemptionPolicy: Never`, чтобы критичные поды приложений могли вытеснять пакетные воркеры при нехватке памяти на нодах.
6.  **Масштабирование по событиям очереди (KEDA ScaledJob):**
    *   Не используйте стандартный HPA (Horizontal Pod Autoscaler) для управления подами Job — HPA рассчитан исключительно на непрерывно работающие сервисы.
    *   Для масштабирования пула пакетных задач на основе длины очереди RabbitMQ, Redis или Kafka используйте кастомный ресурс **KEDA ScaledJob**. KEDA динамически создает отдельные экземпляры `Job` под порции данных и удаляет их по завершении. Подробнее см. **[KEDA ScaledJob в практических сценариях](../Autoscaling/keda/practical_scenarios.md)**.
7.  **Использование Native Sidecars:**
    *   Для вспомогательных задач (Vault-агент для получения секретов СУБД, Envoy-прокси) конфигурируйте их в секции `initContainers` со свойством `restartPolicy: Always`. Это исключает зависание Job после завершения главного скрипта.

---

## Дополнительная информация

### Динамическое изменение ресурсов и планирования в режиме паузы (v1.36 Beta)

Начиная с Kubernetes v1.36, если Job переведен в состояние `spec.suspend: true`, администратор или автоматизированный контроллер (например, VPA в batch-режиме) получают возможность обновлять параметры шаблона пода без пересоздания объекта Job:
*   Ресурсы контейнеров: `resources.requests` и `resources.limits` (`cpu`, `memory`).
*   Параметры размещения: `nodeSelector`, `affinity` и `tolerations`.

Это дает системным администраторам возможность оперативно подстраивать параметры ресурсоемких задач перед их возобновлением при дефиците мощностей на серверах.

### In-Place рестарт контейнеров (v1.35 Alpha)

В рамках feature-gate `RestartAllContainersOnContainerExits` появилась возможность выполнять быстрый перезапуск всех контейнеров внутри пода на том же узле без удаления самого пода. Это сохраняет локальный сетевой стек и кэш томов `emptyDir`, ускоряя восстановление многоконтейнерных пакетных конвейеров на bare-metal серверах.

---

## См. также

*   **[Жизненный цикл Pod и состояния](./Pod/pod_lifecycle_and_state.md)** — фазы, контейнерные состояния, механизмы работы kubelet.
*   **[Паттерны sidecar-контейнеров](./Pod/pod_sidecar_patterns.md)** — интеграция с Native Sidecars (`restartPolicy: Always`).
*   **[Отладка через Ephemeral Containers](./Pod/ephemeral_containers.md)** — интерактивная диагностика запущенных пакетных задач.
*   **[Управление Deployment](./Deployment/index.md)** — сравнение пакетных и долгоживущих сервисов.
*   **[KEDA ScaledJob в практических сценариях](../Autoscaling/keda/practical_scenarios.md)** — масштабирование пакетных задач на основе очередей.
*   **[Kueue — пакетный диспетчер](../Scheduling/kueue.md)** — диспетчеризация очередей и квот на уровне кластера.
*   **[Стратегии резервного копирования](../Operations/backup-strategies.md)** — методология бэкапов etcd, томов и баз данных.
*   **[Хуки синхронизации ArgoCD](../../GitOps/ArgoCD/synchronization.md)** — применение Job в GitOps-пайплайнах.
*   **[Алерты для Kubernetes-приложений](../../Grafana/alerting/kubernetes_alerts.md)** — построение мониторинга на базе Prometheus и Alertmanager.
*   **[Troubleshooting Kubernetes](../Troubleshooting/troubleshooting_overview.md)** — методология локализации сбоев в кластере.
*   **[Официальная документация: Kubernetes Job](https://kubernetes.io/docs/concepts/workloads/controllers/job/)**
*   **[Официальная документация: Kubernetes CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/)**
