# Job и CronJob

## Определения

**Job** в Kubernetes — это контроллер пакетной обработки (группа API `batch/v1`), который создаёт один или несколько подов и гарантирует, что определённое количество из них успешно завершит свою работу (**exit code 0**). 

В отличие от [Deployment](./Deployment/index.md), ориентированного на долгоживущие сервисы, `Job` предназначен для задач, имеющих чёткое завершение (batch processing). Если под завершается с ошибкой, контроллер перезапускает его до достижения лимита попыток или успешного выполнения.

**CronJob** — это надстройка над Job, позволяющая запускать задачи по расписанию в формате cron. Он управляет жизненным циклом Job, создавая их в указанные моменты времени. Начиная с версии **1.21**, CronJob перешел в стабильную версию API `batch/v1`.

**JobSet** — это API (реализованное как Custom Resource Definition в рамках SIG-Batch), предназначенное для управления группой зависимых Job как единым целым. Оно идеально подходит для распределенных вычислений (HPC, AI/ML), где требуется координация между несколькими наборами подов.

### Ключевые сценарии использования

*   **Миграции базы данных:** Применение изменений схемы БД перед деплоем приложения.
*   **Резервное копирование:** Регулярное создание снимков данных. См. также **[Стратегии резервного копирования](../Operations/backup-strategies.md)**.
*   **Пакетная обработка (Batch):** Рендеринг видео, очистка логов, генерация отчётов, обучение нейросетей.
*   **Обучение нейросетей:** Распределённое обучение с использованием индексированных Job или JobSet для координации узлов.
*   **CI/CD задачи:** Запуск тестов или сканеров безопасности (например, `kube-bench`) в изолированном окружении.

## Основные концепции

### Концепции Job

*   **`template`**: Спецификация пода. `restartPolicy` внутри шаблона должна быть либо `OnFailure` (перезапуск контейнера внутри того же пода), либо `Never` (создание нового пода при сбое).
*   **`completions`**: Количество успешных завершений подов для признания Job выполненным (по умолчанию `1`).
    *   Если **`completions` не задано** — используется паттерн **work queue (рабочая очередь)**: Job считается завершённым, когда все созданные поды завершились успешно. Приложение само забирает задачи из очереди (сообщения, API, БД), а не полагается на фиксированный номер успешных завершений.
*   **`parallelism`**: Максимальное количество одновременно запущенных подов (по умолчанию `1`). При `0` создание подов приостанавливается до увеличения значения.
*   **`completionMode`**:
    *   `NonIndexed`: Поды взаимозаменяемы.
    *   `Indexed`: Поды получают индексы от `0` до `completions-1`. Индекс доступен через переменную окружения `JOB_COMPLETION_INDEX` и аннотацию `batch.kubernetes.io/job-completion-index`.
*   **`backoffLimit`**: Лимит попыток перезапуска пода при сбоях (по умолчанию `6`). После исчерпания Job помечается как `Failed`. Семантика лимита зависит от `restartPolicy`:
    *   При `restartPolicy: Never` `backoffLimit` считает количество **новых подов-замен**, созданных после сбоя (при `backoffLimit: 3` может остаться до 4 неудачных подов).
    *   При `restartPolicy: OnFailure` счётчик учитывает **перезапуски контейнера внутри того же пода** (обрабатываются kubelet, а не контроллером Job).
    *   Между попытками задержка растёт **экспоненциально** (10с → 20с → 40с → …), что защищает API-сервер и приложение от лавины перезапусков на постоянно падающей команде.
    *   `podFailurePolicy` задаёт более точные правила учёта сбоев (см. ниже).
*   **`backoffLimitPerIndex` (GA v1.33)**: Позволяет задать лимит попыток **независимо для каждого индекса** `Indexed` Job. Применим только в сочетании с `completionMode: Indexed` и `restartPolicy: Never` (поле неизменяемо). При его указании `backoffLimit` по умолчанию приравнивается к максимальному значению (`2147483647`), чтобы старые клиенты не сломались. Число сбоев на индекс отслеживается в аннотации пода `batch.kubernetes.io/job-index-failure-count`.
*   **`maxFailedIndexes`**: Максимальное число неудачных индексов, после превышения которого **весь** Job помечается как `Failed` (используется вместе с `backoffLimitPerIndex`). Если не задано, Job выполнит все индексы, даже частично неудачные, и завершится с условием `Complete`. Неудачные индексы отображаются в `.status.failedIndexes` в сжатом интервальном формате (например, `1,3-5,7`).
*   **`activeDeadlineSeconds`**: Лимит времени на выполнение всего Job. Если время истекло, все поды удаляются, а Job завершается со статусом `DeadlineExceeded`. Смертный приговор: deadline имеет **приоритет над** `backoffLimit`. Обратите внимание: таймер активен только пока Job не приостановлен — при `suspend: true` счётчик останавливается и сбрасывается при возобновлении. Начиная с v1.31 терминальное условие `Failed`/`Complete` выставляется контроллером только после завершения **всех** подов (поэтому с учётом `terminationGracePeriodSeconds` итоговая длительность Job может быть заметно больше лимита).
*   **`ttlSecondsAfterFinished`**: Время жизни объекта Job после завершения (успешного или нет). Позволяет автоматически очищать кластер от завершенных объектов.
*   **`suspend`**: Если `true`, контроллер приостанавливает создание новых подов. Начиная с **v1.36 (Beta)**, в приостановленных Job можно обновлять ресурсы (`cpu`, `memory`), лимиты, а также параметры планирования (`nodeSelector`, `affinity`, `tolerations`) в шаблоне пода.
*   **`managedBy` (GA v1.35)**: Позволяет передать управление Job внешнему контроллеру (например, **Kueue** или **Argo Workflows**). Встроенный контроллер Kubernetes будет игнорировать такой Job, позволяя внешним инструментам более гибко управлять квотами и очередями. Поле является неизменяемым после создания.

#### Политики сбоев и успеха

*   **`podFailurePolicy` (GA v1.31)**: Тонкая настройка реакции на ошибки.
    *   **Действия (`action`)**: `FailJob` (завершить Job немедленно), `Ignore` (не учитывать в `backoffLimit`), `Count` (учитывать в лимите — по умолчанию), `FailIndex` (пометить конкретный индекс как неудачный и прекратить его перезапуски; доступно только вместе с `backoffLimitPerIndex`).
    *   **Условия**: Можно фильтровать по кодам выхода (`onExitCodes`) или состояниям пода (`onPodConditions`). Например, игнорировать вытеснение пода (`DisruptionTarget`) — такие сбои не тратят `backoffLimit`, поскольку вызваны инфраструктурой, а не приложением.
*   **`successPolicy` (GA v1.33)**: Позволяет считать Job успешным до завершения всех подов. Актуально для `Indexed` Job.
    *   Пример: Job считается успешным, если завершились поды с индексами 0-5 из 10, или если успешно завершился под с индексом 0 (лидер в схеме лидер-воркеры).
*   **`podReplacementPolicy` (GA v1.34)**:
    *   `TerminatingOrFailed` (Default): Создавать замену, как только старый под начал завершаться.
    *   `Failed`: Ждать полного удаления пода перед созданием нового. Критично для GPU-задач, где ресурс должен быть полностью освобожден перед выделением новому поду во избежание конфликтов.

### Концепции CronJob

*   **`schedule`**: Строка расписания в стандартном 5-польном формате cron (`0 1 * * *`). Поддерживается также синтаксис `@every 15m` и именованные записи (`@hourly`, `@daily`). Расписание по умолчанию интерпретируется в часовом поясе **kube-controller-manager** (на практике — UTC).
*   **`timeZone` (GA v1.27)**: Часовой пояс (имя IANA, например, `UTC` или `Europe/Moscow`). Позволяет избежать проблем с переходом на летнее/зимнее время. Указание часового пояса через `CRON_TZ`/`TZ` внутри `schedule` **не поддерживается официально** — API-сервер отклонит такой манифест ошибкой валидации. Если указанный пояс стал недействительным, контроллер перестаёт создавать новые Job и генерирует событие `UnknownTimeZone`.
*   **`suspend`**: При `true` приостанавливает **последующие** запуски (уже запущенные Job не затрагиваются). Расписания продолжают считаться, а пропущенные запуски учитываются как «пропущенные» (см. предупреждение о лимите в 100 пропусков ниже). При смене флага обратно на `false` без `startingDeadlineSeconds` пропущенные запуски выполняются немедленно.
*   **`concurrencyPolicy`**:
    *   `Allow` (по умолчанию): Новые Job запускаются параллельно старым.
    *   `Forbid`: Новый запуск пропускается, если предыдущий ещё активен.
    *   `Replace`: Старый активный Job удаляется и заменяется новым.
*   **`startingDeadlineSeconds`**: Если запуск пропущен (например, из-за сбоя контроллера), это окно времени, в течение которого его ещё можно выполнить. Если окно закрыто, запуск считается неудачным. Важные нюансы:
    *   Если значение больше периода расписания и `concurrencyPolicy: Allow`, каждый пропущенный запуск выполнится хотя бы один раз.
    *   Значение **меньше 10 секунд** может привести к тому, что запуск вообще не произойдёт, так как контроллер проверяет расписание не чаще раза в 10 секунд.
    *   **Лимит в 100 пропусков:** если без `startingDeadlineSeconds` контроллер накопил более 100 пропущенных запусков (например, длительный offline контроллера или долгая пауза через `suspend`), он **перестаёт планировать** новые Job и логирует ошибку `Too many missed start time (> 100). Set or decrease .spec.startingDeadlineSeconds or check clock skew.` Установка `startingDeadlineSeconds` пересчитывает окно учёта пропусков и позволяет восстановить планирование.
*   **`successfulJobsHistoryLimit` / `failedJobsHistoryLimit`**: Сколько завершённых Job хранить в истории (по умолчанию 3 успешных и 1 неудачный). Это частая причина «пропавших» логов — повышайте значения, если нужна большая история для аудита.

## JobSet — распределенные пакетные нагрузки

В то время как стандартный **Job** управляет жизненным циклом одного набора подов, **JobSet** позволяет группировать несколько Job (реплик или разных типов) в одну логическую единицу. Это расширение критично для рабочих нагрузок, требующих тесной связи между узлами.

### Ключевые особенности JobSet

*   **Координация групп:** Возможность запускать разные типы Job (например, `parameter-server` и `worker`) в рамках одного JobSet.
*   **Сетевая связность:** JobSet автоматически создает **Headless Service**, обеспечивая стабильные сетевые имена (DNS) для всех подов. Формат имен: `<jobset-name>-<job-name>-<index>.<service-name>`.
*   **Индексированное управление:** Дочерние Job запускаются в режиме `Indexed`, что дает каждому поду уникальный hostname.
*   **Жизненный цикл всей группы:** Если одна Job в наборе завершается с критической ошибкой, JobSet может перезапустить всю группу (All-or-Nothing) для обеспечения консистентности данных (например, при сбое обучения модели).

### Сравнение Job и JobSet

| Характеристика | Job / CronJob | JobSet |
| :--- | :--- | :--- |
| **Масштаб** | Одна batch-нагрузка. | Группа скоординированных Job. |
| **Сетевая идентификация** | Поды эфемерны (кроме Indexed Job). | Стабильные hostname через Headless Service. |
| **Сложные топологии** | Ограничены одним шаблоном пода. | Поддержка разных шаблонов для разных ролей (Replicated Jobs). |
| **Сценарии** | ETL, бэкапы, разовые скрипты. | Распределенное обучение ML (LLM), HPC, MPI-задачи. |
| **Источник** | Встроено в Kubernetes Core. | SIG-Batch (требует установки JobSet оператора). |

### Практический сценарий: Kubeflow и AI/ML

В экосистеме **Kubeflow** JobSet используется в качестве основы для `Training Operator`. Это позволяет запускать распределенное обучение моделей, где узлы должны знать адреса друг друга для обмена градиентами.

## Практические сценарии

### Индексированный Job для параллельных вычислений

Полезно для задач, где каждый экземпляр обрабатывает свой фрагмент данных (шард).

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: parallel-processor
spec:
  completions: 5
  parallelism: 5
  completionMode: Indexed
  template:
    spec:
      containers:
      - name: worker
        image: custom-worker:latest
        env:
        - name: PARTITION_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.annotations['batch.kubernetes.io/job-completion-index']
      restartPolicy: OnFailure
```

### Индексированный Job с частичным успехом (Success Policy)

Задача считается выполненной, если успешно завершился лидер (индекс 0).

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: leader-worker-job
spec:
  completions: 5
  completionMode: Indexed
  successPolicy:
    rules:
      - succeededIndexes: "0"
  template:
    spec:
      containers:
      - name: app
        image: my-app:latest
      restartPolicy: OnFailure
```

### CronJob с политикой запрета параллелизма

Гарантирует, что тяжелая задача (например, бэкап) не запустится второй раз, если первая ещё не закончила работу.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: maintenance-task
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: app
            image: alpine
            command: ["/bin/sh", "-c", "sleep 1200"] # Дольше 15 минут
          restartPolicy: OnFailure
```

### Использование podFailurePolicy для критических ошибок

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: critical-job
spec:
  backoffLimit: 10
  podFailurePolicy:
    rules:
    - action: FailJob
      onExitCodes:
        operator: In
        values: [1, 2, 3] # При системных ошибках выходим сразу
    - action: Ignore
      onPodConditions:
      - type: DisruptionTarget # Игнорируем вытеснение пода облаком
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: task
        image: my-app:err-prone
```

### Идемпотентная миграция БД с защитой от повторного запуска

Миграции — самая типичная задача Job. Ключевой принцип DevOps: **команда миграции должна быть идемпотентной**, потому что Job не гарантирует «ровно одного» запуска программы даже при `completions: 1`, `parallelism: 1` и `restartPolicy: Never` (возможны повторные старты из-за kubelet, eviction, восстановления контроллера). Используйте флаги инструмента (`--version`), файл блокировки или таблицу `schema_migrations`.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
spec:
  backoffLimit: 5
  activeDeadlineSeconds: 600      # Жёсткий потолок на всю миграцию
  ttlSecondsAfterFinished: 300    # Автоочистка завершённого Job через 5 минут
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: migrate
        image: my-app:migrate-cli
        args: ["migrate", "--version", "42"]   # Идемпотентная команда
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
```

### Work queue (рабочая очередь) — динамическое число задач

Когда число задач заранее неизвестно, `completions` не задают. Поды забирают работу из очереди (например, Redis, RabbitMQ, SQS) и завершаются успешно, когда очередь пуста.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: queue-worker
spec:
  parallelism: 5
  # completions НЕ задан -> work queue
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: worker
        image: my-app:queue-worker
        env:
        - name: QUEUE_URL
          value: redis://redis:6379/0
```

### Backoff limit per index и FailIndex для Indexed Job (GA v1.33)

Позволяет ограничивать повторы **независимо по каждому индексу** и не «сжигать» глобальный `backoffLimit` на одном застрявшем шарде. Здесь индекс 1, упавший с кодом 42, помечается как неудачный без повтора (`FailIndex`), остальные продолжают работать.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: job-per-index-failindex
spec:
  completions: 10
  parallelism: 3
  completionMode: Indexed
  restartPolicy: Never
  backoffLimitPerIndex: 1        # Максимум 1 повтора на индекс
  maxFailedIndexes: 5            # Больше 5 неудачных индексов -> весь Job Failed
  podFailurePolicy:
    rules:
    - action: Ignore
      onPodConditions:
      - type: DisruptionTarget
    - action: FailIndex           # Индекс, упавший с кодом 42, не перезапускаем
      onExitCodes:
        containerName: main
        operator: In
        values: [42]
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: main
        image: python:3
        command: ["python3", "-c", "import os,sys; sys.exit(42 if os.environ['JOB_COMPLETION_INDEX']=='1' else 0)"]
```

### Управление Job через kubectl

```bash
# Императивное создание разового Job
kubectl create job my-oneoff --image=busybox -- echo "hello"
# → job.batch/my-oneoff created

# Создать Job из манифеста
kubectl apply -f job.yaml

# Создать Job из шаблона CronJob (ручной запуск «а-ля сейчас»)
kubectl create job manual-run --from=cronjob/daily-report
# → job.batch/manual-run created

# Просмотр Job (колонки: COMPLETIONS, DURATION, AGE)
kubectl get jobs
# → NAME          COMPLETIONS   DURATION   AGE
# → my-oneoff     1/1           12s        5m

# Следить за прогрессом появления подов
kubectl get jobs -w

# Логи Job (для parallelism: 1); иначе читать логи по меткам, см. ниже
kubectl logs job/my-oneoff
# → hello

# Описание: события, условия, причины сбоев
kubectl describe job/my-oneoff

# Жёсткая остановка: suspend прекращает создание новых подов (+ завершает активные)
kubectl patch job/my-oneoff -p '{"spec":{"suspend":true}}'
kubectl patch job/my-oneoff -p '{"spec":{"suspend":false}}'

# Полное удаление (каскадно удаляет и его поды)
kubectl delete job/my-oneoff

# Удаление всех Job с меткой cleanup=true (простая массовая очистка)
kubectl delete jobs -l cleanup=true
```

Для Job с `parallelism > 1` читать логи всех воркеров нужно по метке, которую контроллер добавляет автоматически (`batch.kubernetes.io/job-name`):

```bash
# Все поды конкретного Job
kubectl get pods -l batch.kubernetes.io/job-name=my-oneoff
# Логи каждого пода
for p in $(kubectl get pods -l batch.kubernetes.io/job-name=my-oneoff -o name); do echo "== $p =="; kubectl logs $p; done
```

### Управление CronJob через kubectl

```bash
# Создать CronJob
kubectl create cronjob hourly-cleanup --image=busybox \
  --schedule="0 * * * *" -- /bin/sh -c "echo cleanup"

# Список CronJob и их Job (Job, созданные конкретным CronJob)
kubectl get cronjobs
kubectl get jobs -o json | jq -r \
  '.items[] | select(.metadata.ownerReferences[0].name=="hourly-cleanup") | .metadata.name'

# Приостановить / возобновить планирование (без удаления)
kubectl patch cronjob hourly-cleanup -p '{"spec":{"suspend":true}}'
kubectl patch cronjob hourly-cleanup -p '{"spec":{"suspend":false}}'

# Ручной запуск (создаёт разовый Job по шаблону)
kubectl create job manual --from=cronjob/hourly-cleanup

# Просмотр событий (причины «молчания»)
kubectl describe cronjob/hourly-cleanup
```

## Мониторинг и алертинг (SRE/DevOps)

Сбой batch-задачи часто незаметен, пока не накопились последствия. В наборе `kube-prometheus-stack` (kube-state-metrics) есть стандартные метрики для контроля Job и CronJob:

| Метрика | Смысл | Типовой алерт |
| :--- | :--- | :--- |
| `kube_job_status_succeeded` | Текущее число успешно завершившихся подов Job | `== 0` при активном Job — долго работает |
| `kube_job_status_failed` | Число неудачных подов Job | `> 0` — есть повторы |
| `kube_job_failed` | Флаг (0/1): Job в состоянии `Failed` | `== 1` — задача окончательно упала |
| `kube_job_labels{job_name="..."}` | Только выбранные Job по метке | — |
| `kube_cronjob_status_active` | Число одновременно активных Job CronJob | расхождение с `concurrencyPolicy` |
| `kube_cronjob_info` | Метаинформация (например, `schedule`) | — |

Пример правила алертинга на «молчащий» CronJob (по метке выбранной задачи и времени последнего запуска):

```yaml
groups:
- name: batch
  rules:
  - alert: CronJobNotScheduledRecently
    expr: |
      time() - kube_cronjob_status_last_schedule_time > 2 * 3600
      and on(cronjob, namespace) kube_cronjob_labels{cronjob="daily-report"}
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "CronJob {{ $labels.cronjob }} не запускался 2+ часа"
```

Важные уточнения по метрикам:
*   `kube_cronjob_status_last_schedule_time` — unix-время (секунды) последнего запланированного запуска; алертить на его «возраст», а не на равенство нулю.
*   `kube_job_failed` — флаг (0/1) окончательного падения Job; алерт `== 1` надёжнее, чем погоня за счётчиком повторов.
*   Для алертов на «отсутствие метрик» (упал экспортёр, молчит очередь) используйте конструкцию `absent()` — приём описан в **[Алерты для Kubernetes-приложений](../../Grafana/alerting/kubernetes_alerts.md)**.

Отслеживание «молчащих» периодических задач — стандартная практика SRE: гораздо лучше алертить на отсутствие ожидаемого запуска, чем ждать, пока пользователь сообщит о проблеме.

## Траблшутинг

Типичные проблемы Job/CronJob и способы их диагностики:

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Job «висит» в `Running`, поды не завершаются | Контейнер никогда не выходит (`completions` завышен, команда ждёт ввода, висит процесс) | Проверьте `kubectl get pods`, логи. Добавьте `activeDeadlineSeconds` как страховку. Исправьте команду, чтобы она завершалась при успехе. |
| Событие `BackoffLimitExceeded`, Job `Failed` | Команда, образ или зависимости падают после исчерпания повторов | Читайте логи неудачного пода и коды выхода: `kubectl logs <pod> --previous`. Исправьте команду/аргументы/переменные окружения. |
| Параллельных подов меньше, чем `parallelism` | Низкий остаток `completions`, нехватка ресурсов узлов, `ResourceQuota`, блокировка планирования | `kubectl describe job`, события пода; проверьте квоты и capacity кластера. |
| CronJob «молчит» и не создаёт Job | Накоплено >100 пропусков; контроллер не в том часовом поясе; `suspend: true` | `kubectl describe cronjob` (событие `TooManyMissedTimes`/`TooManyMissedStartTimes`). Задайте `startingDeadlineSeconds`; проверьте `timeZone`. |
| Завершённые Job копятся в неймспейсе | Не задан `ttlSecondsAfterFinished` и/или малая история CronJob | Добавьте `ttlSecondsAfterFinished`; увеличьте `successfulJobsHistoryLimit`/`failedJobsHistoryLimit` при необходимости. |
| Поды CronJob «не хватает» логов | По умолчанию хранятся только 3 успешных и 1 неудачный Job | Повысьте history-лимиты или настройте выгрузку логов. |

Для отладки живого (зависшего) Job используйте **Ephemeral Containers** — см. [Отладка Job и CronJob](./Pod/ephemeral_containers.md). Типовые сбои пода (ImagePullBackOff, CrashLoopBackOff, OOMKilled) разбираются в разделе [Troubleshooting Kubernetes](../Troubleshooting/troubleshooting_overview.md).

## Лучшие практики (Best Practices)

*   **Всегда задавайте страховки:** `activeDeadlineSeconds` (потолок времени), `backoffLimit` (потолок повторов, 4–6 — разумный баланс для транзиентных сбоев) и `ttlSecondsAfterFinished` (автоочистка) — это защита от «прожорливых» и «зависших» задач.
*   **Идемпотентность обязательна:** Job не даёт exactly-once семантики. Проектируйте команды так, чтобы повторный запуск был безопасен.
*   **Для CronJob задавайте `startingDeadlineSeconds`:** иначе длительный offline контроллера или долгая пауза через `suspend` могут остановить планирование из-за лимита 100 пропусков.
*   **Выбирайте `restartPolicy` осознанно:** `Never` лучше для чистого разделения повторов (контроллер создаёт новые поды и корректно работает с `podFailurePolicy` и `backoffLimitPerIndex`); `OnFailure` быстрее для простых сбоев внутри пода, но несовместим с `podFailurePolicy`.
*   **Не используйте HPA для Job/CronJob** — это задача для event-driven скейлинга. См. [KEDA ScaledJob](../Autoscaling/keda/practical_scenarios.md) для масштабирования по событиям очереди.
*   **Для разовых миграций в GitOps-цикле** применяйте Job как PreSync/PostSync-хуки. См. [Хуки синхронизации (Hooks)](../../GitOps/ArgoCD/synchronization.md).
*   **Мониторьте batch-нагрузки** через метрики kube-state-metrics и алертите на «молчащие» CronJob.
*   **Для Job/CronJob с инъекцией секретов через Vault** используйте init-only режим агента (`agent-pre-populate-only`), чтобы sidecar не блокировал завершение подов. См. [Vault Agent Injector](../../Vault/guides/vault_agent/injector.md).

## Дополнительная информация

### Взаимодействие с Sidecars (v1.29+)

Если используются **Native Sidecar Containers** (init-контейнеры с `restartPolicy: Always`), контроллер Job автоматически завершает их после успешного выполнения всех основных контейнеров. Это решает проблему "зависших" Job, которые не могли завершиться из-за работающего рядом прокси-контейнера (например, Istio или Cloud SQL Proxy).

### Жизненный цикл и условия (Conditions)

Состояние Job отражается в `.status`: поля `active`, `succeeded`, `failed` (числа подов в соответствующих фазах), `startTime`, `completionTime`, а для `Indexed` — `completedIndexes` и (при `backoffLimitPerIndex`) `failedIndexes` в сжатом интервальном виде (например, `0,3-5`).

Job имеет несколько условий в `.status.conditions`:
*   **Complete**: Задача успешно выполнена.
*   **Failed**: Превышен лимит попыток или произошла критическая ошибка.
*   **Suspended**: Выполнение приостановлено пользователем.
*   **FailureTarget**: (v1.30+) Указывает, что Job находится в процессе завершения из-за сбоя одного из подов.

Начиная с v1.31 контроллер добавляет терминальные условия (`Complete`/`Failed`) только **после** завершения всех подов — это нужно учитывать при чтении времени жизни Job из статуса (см. `activeDeadlineSeconds` выше).

### Динамическое изменение ресурсов и параметров планирования

С версии **v1.36 (Beta)**, если Job находится в состоянии `suspend: true`, администратор или автоматика (например, VPA или batch-планировщик) могут изменить:
1.  `resources.requests` и `limits` в `podTemplate`.
2.  `nodeSelector`, `affinity` и `tolerations`.
Это позволяет оптимизировать потребление ресурсов "на лету" перед возобновлением тяжелой задачи, не пересоздавая объект Job.

### Рестарт контейнеров внутри пода (Alpha v1.35)

Новая функциональность (feature gate `RestartAllContainersOnContainerExits`) позволяет выполнять In-place рестарт всех контейнеров в поде при сбое одного из них. Это значительно ускоряет восстановление для AI/ML нагрузок, сохраняя локальный контекст пода (тома, IP).

## См. также

*   [Жизненный цикл Pod и состояния](./Pod/pod_lifecycle_and_state.md)
*   [Управление Deployment](./Deployment/index.md)
*   [Официальная документация: Job](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
*   [Официальная документация: CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/)
