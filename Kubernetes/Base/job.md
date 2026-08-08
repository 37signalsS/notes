# Job и CronJob

## Определения

**Job** в Kubernetes — это контроллер пакетной обработки (группа API `batch/v1`), который создаёт один или несколько подов и гарантирует, что определённое количество из них успешно завершит свою работу (**exit code 0**).

В отличие от [Deployment](./Deployment/index.md), ориентированного на долгоживущие сервисы, `Job` предназначен для задач, имеющих чёткое завершение (batch processing). Если под завершается с ошибкой, контроллер перезапускает его до достижения лимита попыток или успешного выполнения.

**CronJob** — это надстройка над Job, позволяющая запускать задачи по расписанию в формате cron. Он управляет жизненным циклом Job, создавая их в указанные моменты времени.

### Ключевые сценарии использования

*   **Миграции базы данных:** Применение изменений схемы БД перед деплоем приложения.
*   **Резервное копирование:** Регулярное создание снимков данных. См. также **[Стратегии резервного копирования](../Operations/backup-strategies.md)**.
*   **Пакетная обработка (Batch):** Рендеринг видео, очистка логов, генерация отчётов.
*   **Обучение нейросетей:** Распределённое обучение с использованием индексированных Job.
*   **CI/CD задачи:** Запуск тестов или сканеров безопасности (например, `kube-bench`) в изолированном окружении.

## Основные концепции

### Концепции Job

*   **`template`**: Спецификация пода. `restartPolicy` внутри шаблона должна быть либо `OnFailure`, либо `Never`.
*   **`completions`**: Количество успешных завершений подов для признания Job выполненным.
*   **`parallelism`**: Максимальное количество одновременно запущенных подов.
*   **`completionMode`**:
    *   `NonIndexed`: Поды взаимозаменяемы.
    *   `Indexed`: Поды получают индексы от `0` до `completions-1`. Индекс доступен через переменную окружения `JOB_COMPLETION_INDEX` и аннотацию `batch.kubernetes.io/job-completion-index`.
*   **`backoffLimit`**: Лимит попыток перезапуска пода при сбоях (по умолчанию `6`). После исчерпания Job помечается как `Failed`.
*   **`activeDeadlineSeconds`**: Лимит времени на выполнение всего Job. Если время истекло, все поды удаляются, а Job завершается со статусом `DeadlineExceeded`.
*   **`ttlSecondsAfterFinished`**: Время жизни объекта Job после завершения (успешного или нет). Позволяет автоматически очищать кластер.
*   **`suspend`**: Если `true`, контроллер приостанавливает создание новых подов. Начиная с **v1.36**, в приостановленных Job можно обновлять ресурсы (`cpu`, `memory`) в шаблоне пода.

#### Политики сбоев и успеха

*   **`podFailurePolicy`**: Тонкая настройка реакции на ошибки.
    *   **Действия (`action`)**: `FailJob` (завершить Job немедленно), `Ignore` (не учитывать в `backoffLimit`), `Count` (учитывать в лимите — по умолчанию).
    *   **Условия**: Можно фильтровать по кодам выхода (`onExitCodes`) или состояниям пода (`onPodConditions`).
*   **`successPolicy` (v1.30+)**: Позволяет считать Job успешным до завершения всех подов. Актуально для `Indexed` Job.
    *   Пример: Job считается успешным, если завершились поды с индексами 0-5 из 10.
*   **`podReplacementPolicy`**:
    *   `TerminatingOrFailed`: Создавать замену, как только старый под начал завершаться.
    *   `Failed`: Ждать полного удаления пода перед созданием нового (критично для GPU-задач).

### Концепции CronJob

*   **`schedule`**: Строка расписания (`0 1 * * *`).
*   **`timeZone`**: Часовой пояс (например, `UTC` или `Europe/Moscow`). Позволяет избежать проблем с переходом на летнее/зимнее время.
*   **`concurrencyPolicy`**:
    *   `Allow`: Новые Job запускаются параллельно старым.
    *   `Forbid`: Новый запуск пропускается, если предыдущий ещё активен.
    *   `Replace`: Старый активный Job удаляется и заменяется новым.
*   **`startingDeadlineSeconds`**: Если запуск пропущен (например, из-за сбоя контроллера), это окно времени, в течение которого его ещё можно выполнить. Если окно закрыто, запуск считается неудачным.
*   **`successfulJobsHistoryLimit` / `failedJobsHistoryLimit`**: Сколько завершённых Job хранить в истории (по умолчанию 3 успешных и 1 неудачный).

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

## Дополнительная информация

### Взаимодействие с Sidecars (v1.29+)

Если используются **Native Sidecar Containers** (init-контейнеры с `restartPolicy: Always`), контроллер Job автоматически завершает их после успешного выполнения всех основных контейнеров. Это решает проблему "зависших" Job, которые не могли завершиться из-за работающего рядом прокси-контейнера (например, Istio или Cloud SQL Proxy).

### Делегированное управление (.spec.managedBy)

Начиная с **v1.35**, поле `managedBy` позволяет передать управление Job внешнему контроллеру (например, **Kueue** или **Argo Workflows**). Встроенный контроллер Kubernetes будет игнорировать такой Job, позволяя внешним инструментам более гибко управлять квотами и очередями в мультиарендных кластерах.

### Жизненный цикл и условия (Conditions)

Job имеет несколько статусов, доступных в `.status.conditions`:
*   **Complete**: Задача успешно выполнена.
*   **Failed**: Превышен лимит попыток или произошла критическая ошибка.
*   **Suspended**: Выполнение приостановлено пользователем.
*   **FailureTarget**: (v1.30+) Указывает, что Job находится в процессе завершения из-за сбоя одного из подов.

### Динамическое изменение ресурсов

С версии **v1.36**, если Job находится в состоянии `suspend: true`, администратор или автоматика (например, VPA или batch-планировщик) могут изменить `resources.requests` и `limits` в `podTemplate`. Это позволяет оптимизировать потребление ресурсов "на лету" перед возобновлением тяжелой задачи.

## См. также

*   [Жизненный цикл Pod и состояния](./Pod/pod_lifecycle_and_state.md)
*   [Управление Deployment](./Deployment/index.md)
*   [Официальная документация: Job](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
*   [Официальная документация: CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/)
