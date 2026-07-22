# Job и CronJob

## Определения

**Job** в Kubernetes — это объект, который создаёт один или несколько подов и гарантирует, что определённое количество из них успешно завершит свою работу (**exit code 0**).

В отличие от [Deployment](./Deployment/index.md), который ориентирован на приложения, работающие постоянно (контроллер следит, чтобы под был "жив"), `Job` следит за тем, чтобы задача была **выполнена до конца**. Если под упал — Job перезапустит его, пока задача не выполнится или не исчерпается лимит попыток.

**CronJob** — это контроллер, который по расписанию (классический cron-синтаксис) создаёт объекты `Job`. Сам он ничего не выполняет — только штампует Job'ы в нужный момент.

### Ключевые сценарии использования

* **Миграции базы данных:** Применение схемы или перенос данных.
* **Резервное копирование:** Создание бэкапов данных из томов (`PersistentVolume`).
* **Обработка данных:** Запуск скриптов для анализа, очистки или **ETL (Extract, Transform, Load)** процессов.
* **Запуск тестов:** Выполнение тестов в изолированном окружении.
* **Регулярные отчеты:** Генерация отчетов или отправка уведомлений по расписанию.

## Основные концепции

### Концепции Job

* **`template`**: Обязательное поле, описывающее шаблон пода для запуска.
* **`restartPolicy`**: Определяет политику перезапуска контейнеров в поде. Для `Job` допустимы только:
  * `OnFailure`: Перезапускать контейнер, если он завершился с ошибкой.
  * `Never`: Никогда не перезапускать контейнер. `Job` сам управляет созданием новых подов в случае неудачи.
  **Важно:** В отличие от Deployment, где kubelet перезапускает поды, в Job решение о перезапуске принимает контроллер Job.
* **`completions`**: Количество подов, которые должны успешно завершиться. По умолчанию `1`.
* **`parallelism`**: Сколько подов могут работать одновременно. По умолчанию `1`.
* **`completionMode`**:
  * `NonIndexed` (по умолчанию): Поды взаимозаменяемы.
  * `Indexed`: Каждый под получает статический индекс (от `0` до `completions-1`) в аннотации `batch.kubernetes.io/job-completion-index` и имени хоста. Полезно для MPI и распределенного обучения.
* **`backoffLimit`**: Количество повторных попыток перед тем, как `Job` будет помечен как неудавшийся (`failed`). По умолчанию `6`. Используется **exponential backoff**.
* **`activeDeadlineSeconds`**: Жёсткий таймаут на всю задачу. Если время истекло, Job и все его поды будут завершены.
* **`ttlSecondsAfterFinished`**: Время автоочистки завершённых Job (и их подов) из кластера.
* **`suspend`**: Приостановка выполнения `Job`. Если `true`, новые поды не создаются.
* **`podFailurePolicy`**: Позволяет уточнить действия при сбое пода (например, "игнорировать этот код ошибки при подсчете `backoffLimit`" или "сразу пометить Job как Failed").
* **`successPolicy`**: (v1.30+) Позволяет считать Job успешным при достижении определённых условий (например, завершение 50% индексированных подов).
* **`podReplacementPolicy`**:
  * `TerminatingOrFailed` (по умолчанию): Заменяет под, как только он начинает завершаться или упал.
  * `Failed`: Создаёт замену только после полного завершения (terminating -> exited) старого пода. Рекомендуется для экономии ресурсов (например, GPU).

### Концепции CronJob

* **`schedule`**: Расписание в формате `cron` (например, `"0 2 * * *"`).
* **`timeZone`**: Временная зона для расписания (например, `Europe/Moscow`).
* **`concurrencyPolicy`**:
  * `Allow` (по умолчанию): Запускать Job параллельно.
  * `Forbid`: Пропустить новый запуск, если старый ещё работает.
  * `Replace`: Заменить текущий Job новым.
* **`startingDeadlineSeconds`**: Окно времени, в течение которого пропущенный запуск может быть выполнен.
* **`successfulJobsHistoryLimit` / `failedJobsHistoryLimit`**: Количество хранимых завершённых Job.

## Практические сценарии

### Пример манифеста Job с политикой сбоев

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: data-sync
spec:
  backoffLimit: 4
  podFailurePolicy:
    rules:
    - action: FailJob
      onExitCodes:
        operator: In
        values: [42] # Сразу выходим, если код 42 (критическая ошибка)
    - action: Ignore
      onPodConditions:
      - type: DisruptionTarget # Не считаем вытеснение (preemption) за ошибку
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: worker
        image: worker-image:v1.2
```

### Пример индексированного Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: indexed-job
spec:
  completions: 3
  parallelism: 3
  completionMode: Indexed
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: worker
        image: busybox
        command: ["sh", "-c", "echo I am worker ${JOB_COMPLETION_INDEX}"]
```

### Пример CronJob с часовым поясом

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: nightly-backup
spec:
  schedule: "0 1 * * *"
  timeZone: "Europe/Moscow"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: backup
            image: backup-tool:latest
```

### Управление через kubectl

1. **Создать и проверить:**
    ```bash
    kubectl apply -f my-job.yaml
    kubectl get jobs
    kubectl describe job my-job
    ```

2. **Запуск Job вручную из CronJob:**
    ```bash
    kubectl create job --from=cronjob/nightly-backup manual-backup-001
    ```

3. **Логи индексированного Job:**
    ```bash
    # Логи конкретного индекса
    kubectl logs job/indexed-job --index=0
    ```

## Дополнительная информация

### Взаимодействие с Sidecars (v1.29+)

Если в поде Job используются **Native Sidecar Containers** (init-контейнеры с `restartPolicy: Always`), контроллер Job считает задачу завершённой, когда все основные (non-sidecar) контейнеры успешно завершились. После этого Kubernetes автоматически завершает sidecar-контейнеры.

### Изменение ресурсов в приостановленных Job (v1.36+)

Начиная с v1.36, можно обновлять `resources` в `podTemplate` у Job, если он находится в состоянии `suspend: true`. Это позволяет динамически подстраивать ресурсы (например, через Kueue) без пересоздания объекта Job, сохраняя историю событий.

### Делегированное управление (.spec.managedBy)

Стабильно с v1.35. Позволяет сторонним контроллерам (Argo Workflows, Kueue) полностью брать на себя управление жизненным циклом Job, отключая встроенный контроллер Kubernetes для конкретного экземпляра.

### Эластичные индексированные Job (v1.30+)

Для индексированных Job (`completionMode: Indexed`) можно изменять поле `completions` (при условии, что `parallelism` изменяется согласованно). Это позволяет масштабировать запущенные пакетные задачи в зависимости от доступных ресурсов кластера.

## См. также

* [Pod и его жизненный цикл](./Pod/pod_lifecycle_and_state.md)
* [Управление Deployment](./Deployment/index.md)
* [Официальная документация: Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
