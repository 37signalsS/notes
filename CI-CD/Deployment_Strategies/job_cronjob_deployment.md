# Деплой пакетных задач через CI/CD (Job и CronJob)

> **Актуально для:** Kubernetes 1.37.x, GitLab CI 17.x

## Определения

**Batch Deployment** — паттерн доставки и выполнения пакетных задач (миграции БД, фоновые расчёты, очистка данных) через CI/CD-пайплайн, где Job или CronJob выступают исполнителем, а GitLab CI — триггером и координатором.

**Migration Job** — разовый Kubernetes Job, применяющий схематичные изменения к базе данных перед или во время деплоя приложения. Критичен для стратегий Recreate и Blue-Green, где старая и новая версия не могут сосуществовать.

**CronJob Promotion** — процесс обновления шаблона CronJob в кластере через CI: изменение образа, проверка расписания и валидация запуска. Отличается от Deployment тем, что нет «прогрессивной раскатки» — новая версия подхватывается на следующем запуске по расписанию.

**Job Artifact Collection** — механизм сохранения stdout/stderr пода, логов и exit-кода Job обратно в GitLab как артефакт пайплайна, чтобы результаты batch-задачи были доступны для анализа и аудита.

## Основные концепции

### Чем Job/CronJob Deployment отличается от Deployment

| Аспект | Deployment | Job / CronJob |
| :--- | :--- | :--- |
| **Жизненный цикл** | Бесконечный, self-healing | Ограниченный, завершается после успеха или превышения попыток |
| **Rollback** | `kubectl rollout undo`, мгновенный | Невозможен автоматически; требует создания нового Job с предыдущей версией образа |
| **Параллелизм** | Регулируется ReplicaSet | `parallelism` и `completions` дают явный контроль над параллельными экземплярами |
| **Триггер** | Постоянно | По расписанию (CronJob) или явный запуск (Job) |
| **Артефакты** | Не хранит результаты | stdout/stderr можно собрать через `kubectl logs` после завершения |
| **Идемпотентность** | Не требуется | Обязательна: повторный запуск миграции не должен ломать данные |

### Паттерны запуска Job из GitLab CI

1. **Trigger Job (явный запуск):** `kubectl apply -f job.yaml` → `kubectl wait --for=condition=complete` → сбор логов.
2. **Work Queue (рабочая очередь):** Job создаётся с `completions: N`, поды сами забирают задачи из очереди (RabbitMQ, Redis, SQS). Подходит для параллельной обработки.
3. **Migration as Pipeline Stage:** Job определяется в том же манифесте, что и Deployment, но запускается в отдельном stage с `when: manual` или автоматически перед деплоем.
4. **Child Pipeline for Batch:** Отдельный `.gitlab/ci/jobs.yml` пайплайн, вызываемый через `trigger` для сложных batch-сценариев с несколькими Job.

### Варианты: GitLab CI vs in-cluster Cron

| Критерий | CronJob (Kubernetes) | GitLab CI Scheduler |
| :--- | :--- | :--- |
| **Управление расписанием** | `spec.schedule` в манифесте | `only: schedules` в `.gitlab-ci.yml` |
| **Секреты** | K8s Secrets / External Secrets | CI/CD Variables (зашифрованы) |
| **Артефакты** | Внешнее хранилище (S3, NFS) | Встроенные артефакты GitLab |
| **Оповещения** | EventRecorder / Alertmanager | GitLab Pipeline notifications |
| **Отладка** | `kubectl logs job/xxx` | Логи пайплайна, встроенный трейс |
| **Репликация** | Multi-cluster через Argo/CD | Multi-project через Trigger |

## Практические сценарии

### 1. Базовый запуск Job из GitLab CI

```yaml
stages:
  - migrate
  - deploy
  - verify

db_migrate:
  stage: migrate
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/job-db-migration.yaml
    - kubectl wait --for=condition=complete job/db-migration-v2 --timeout=600s
    # Сбор артефакта: вывод миграции
    - kubectl logs job/db-migration-v2 > migration.log
  artifacts:
    paths:
      - migration.log
    expire_in: 7d
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

`job-db-migration.yaml`:
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration-v2
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: registry.internal/db-migrate:v2.4.0
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secrets
              key: url
        resources:
          requests:
            memory: "256Mi"
            cpu: "500m"
          limits:
            memory: "512Mi"
            cpu: "1000m"
```

### 2. Распараллеливание через Indexed Job (Work Queue)

```yaml
# k8s/job-batch-process.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: batch-processor
spec:
  completions: 10
  parallelism: 3
  completionMode: Indexed
  backoffLimit: 2
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: worker
        image: registry.internal/batch-worker:v2.4.0
        env:
        - name: BATCH_SIZE
          value: "1000"
        - name: JOB_COMPLETION_INDEX
          valueFrom:
            fieldRef:
              fieldPath: metadata.annotations['batch.kubernetes.io/job-completion-index']
```

```yaml
# .gitlab-ci.yml
batch_process:
  stage: deploy
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/job-batch-process.yaml
    - kubectl wait --for=condition=complete job/batch-processor --timeout=1800s
    # Проверка, что все индексы завершились
    - kubectl get job/batch-processor -o jsonpath='{.status.succeeded}' | grep -q '^10$'
  environment:
    name: production
```

### 3. Обновление CronJob через GitLab CI

```yaml
stages:
  - validate
  - deploy_cron
  - verify

validate_cron:
  stage: validate
  image: bitnami/kubectl:1.37
  script:
    # Проверка валидности манифеста
    - kubectl apply --dry-run=server -f k8s/cronjob-report.yaml
    # Проверка, что новое расписание не конфликтует с существующим
    - kubectl get cronjob report-generator -o jsonpath='{.spec.schedule}'

deploy_cron:
  stage: deploy_cron
  image: bitnami/kubectl:1.37
  needs:
    - validate_cron
  script:
    - kubectl apply -f k8s/cronjob-report.yaml
    - kubectl rollout status cronjob/report-generator --timeout=60s
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

verify_cron:
  stage: verify
  image: bitnami/kubectl:1.37
  needs:
    - deploy_cron
  script:
    # Принудительный запуск для проверки
    - kubectl create job --from=cronjob/report-generator manual-verify-$CI_COMMIT_SHORT_SHA
    - kubectl wait --for=condition=complete job/manual-verify-$CI_COMMIT_SHORT_SHA --timeout=300s
    - kubectl logs job/manual-verify-$CI_COMMIT_SHORT_SHA > cron_verify.log
  artifacts:
    paths:
      - cron_verify.log
  environment:
    name: production
```

`cronjob-report.yaml`:
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: report-generator
spec:
  schedule: "0 2 * * *"
  timeZone: "Europe/Moscow"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        spec:
          restartPolicy: Never
          containers:
          - name: report
            image: registry.internal/report-gen:v2.4.0
            env:
            - name: REPORT_TYPE
              value: "daily"
            resources:
              requests:
                memory: "512Mi"
                cpu: "1000m"
              limits:
                memory: "1Gi"
                cpu: "2000m"
```

### 4. Пайплайн с approval gate для миграции БД

```yaml
stages:
  - preflight
  - migrate
  - deploy_app
  - smoke_test

preflight:
  stage: preflight
  image: bitnami/kubectl:1.37
  script:
    # Проверка, что нет активных миграций
    - kubectl get jobs -l app=migrate --field-selector=status.active=1 || true
    # Проверка доступности БД
    - kubectl exec -it deploy/prod-db -- pg_isready -U postgres
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

db_migrate:
  stage: migrate
  image: bitnami/kubectl:1.37
  needs:
    - preflight
  script:
    - kubectl apply -f k8s/job-db-migration.yaml
    - kubectl wait --for=condition=complete job/db-migration-v2 --timeout=600s
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

deploy_app:
  stage: deploy_app
  image: bitnami/kubectl:1.37
  needs:
    - db_migrate
  script:
    - kubectl apply -f k8s/deployment.yaml
    - kubectl rollout status deployment/myapp --timeout=300s
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

smoke_test:
  stage: smoke_test
  image: curlimages/curl:8.22.0
  needs:
    - deploy_app
  script:
    - curl -sf https://app.example.com/healthz || exit 1
```

### 5. Автоматический откат миграции при провале

```yaml
stages:
  - migrate
  - verify
  - rollback

db_migrate:
  stage: migrate
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/job-db-migration.yaml
    - kubectl wait --for=condition=complete job/db-migration-v2 --timeout=600s

verify_migration:
  stage: verify
  image: bitnami/kubectl:1.37
  needs:
    - db_migrate
  script:
    # Smoke-test после миграции
    - kubectl exec -it deploy/myapp -- curl -sf http://localhost:8080/healthz || exit 1

auto_rollback_migration:
  stage: rollback
  image: bitnami/kubectl:1.37
  needs:
    - verify_migration
  script:
    # Запуск Job с предыдущей версией миграции (откат)
    - kubectl apply -f k8s/job-db-migration-rollback.yaml
    - kubectl wait --for=condition=complete job/db-migration-rollback --timeout=600s
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### 6. Мониторинг выполнения Job из GitLab CI

```yaml
monitor_job:
  stage: verify
  image: bitnami/kubectl:1.37
  needs:
    - db_migrate
  script:
    - |
      JOB_STATUS=$(kubectl get job/db-migration-v2 -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
      if [ "$JOB_STATUS" != "True" ]; then
        echo "Migration job failed"
        kubectl logs job/db-migration-v2 --tail=100
        exit 1
      fi
      # Проверка, что нет неудачных подов
      FAILED=$(kubectl get job/db-migration-v2 -o jsonpath='{.status.failed}')
      if [ "$FAILED" -gt 0 ]; then
        echo "Job had $FAILED failed pods"
        exit 1
      fi
  environment:
    name: production
```

## Операции и команды

### Kubernetes — управление Job и CronJob

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Создать Job** | `kubectl apply -f job.yaml` | Создает Job с указанным шаблоном пода |
| **Создать CronJob** | `kubectl apply -f cronjob.yaml` | Создает или обновляет CronJob в кластере |
| **Статус Job** | `kubectl get job db-migration-v2` | Показывает completions, duration, age |
| **Логи Job** | `kubectl logs job/db-migration-v2` | stdout/stderr завершенного пода |
| **Логи предыдущего пода** | `kubectl logs job/db-migration-v2 --previous` | Логи упавшего пода перед перезапуском |
| **Описание Job** | `kubectl describe job db-migration-v2` | Conditions, events, selector, pod-template-hash |
| **Удалить Job** | `kubectl delete job db-migration-v2` | Удаляет Job и связанные поды |
| **Принудительный запуск CronJob** | `kubectl create job --from=cronjob/report-generator manual-run-$CI_COMMIT_SHORT_SHA` | Одноразовый Job из шаблона CronJob |
| **Статус CronJob** | `kubectl get cronjob report-generator -o yaml` | Schedule, suspend, lastScheduleTime, active jobs |
| **TTL после завершения** | `kubectl patch job db-migration-v2 -p '{"spec":{"ttlSecondsAfterFinished":86400}}'` | Автоудаление Job через 24 ч |
| **События namespace** | `kubectl get events --sort-by='.lastTimestamp' -n production` | FailedScheduling, BackOff, OOMKilled, quota violations |
| **Анализ ресурсов пода** | `kubectl top pod -l job-name=db-migration-v2` | CPU/RAM потребление подами Job |

### GitLab CI — управление пайплайном

| Действие | Команда / фрагмент | Результат |
| :--- | :--- | :--- |
| **Ручной запуск миграции** | `when: manual` в задаче | Блокирует автоматический запуск до подтверждения в UI |
| **Protected Environment** | `environment: production` + Protected Environment | Только authorized users могут запустить деплой |
| **Сбор артефактов** | `artifacts: paths: - migration.log expire_in: 7d` | Сохраняет логи Job в GitLab для аудита |
| **API отмены пайплайна** | `curl -X POST "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/pipelines/$CI_PIPELINE_ID/cancel"` | Отменяет активный пайплайн |
| **Child pipeline trigger** | `trigger: project: ...` | Запускает отдельный `.gitlab/ci/jobs.yml` для batch-сценариев |
| **Pre-flight проверка** | `kubectl get jobs -l app=migrate --field-selector=status.active=1 || true` | Проверяет, что нет активных миграций |

### systemd — управление артефактами и супервизор

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Статус сервиса** | `systemctl status my-service` | Active: active (running) / failed / inactive |
| **Логи сервиса** | `journalctl -u my-service -n 50 --no-pager` | Последние 50 строк логов |
| **Watchdog статус** | `systemctl show my-service -p WatchdogTimestamp` | Время последнего продления watchdog |
| **Счетчик перезапусков** | `systemctl show my-service -p NRestarts` | Число перезапусков за время загрузки юнита |
| **Откат юнита** | `systemctl revert my-service` | Возвращает юнит к vendor-версии |

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Job завис в Pending** | Нет места для новых подов (ResourceQuota, CPU/RAM лимиты namespace) | Проверить `kubectl get events`; увеличить quota; при необходимости добавить узлы |
| **Job падает с OOMKilled** | `limits.memory` меньше, чем требует миграция | Увеличить лимиты; проверить `kubectl top pod` |
| **CronJob не запускается по расписанию** | Поле `suspend: true`, неверный cron-синтаксис или часовой пояс | `kubectl get cronjob` — проверить `SUSPEND` и `lastScheduleTime` |
| **Job перезапускается бесконечно** | `backoffLimit` слишком высокий или миграция неидемпотентна | Для миграций установить `backoffLimit: 0`; проверить идемпотентность SQL |
| **Логи Job недоступны после TTL** | Pod удален TTL-контроллером или `restartPolicy: Never` | Собрать логи в артефакт пайплайна до завершения Job; использовать `--previous` |
| **CronJob создает дубликаты** | `concurrencyPolicy: Allow` и предыдущий Job еще выполняется | Установить `concurrencyPolicy: Forbid` или `Replace` |
| **Artifact Collection timeout** | Логи на сетевой ФС еще не синхронизированы | Добавить `sleep 5` перед `kubectl logs` или использовать sidecar-контейнер |
| **Миграция упала на половине данных** | Длинная миграция прервана, схема в несогласованном состоянии | Использовать идемпотентные миграции; иметь `down`-миграции; тестировать откат заранее |
| **Multi-cluster запуск не работает** | Контекст kubectl указывает не на тот кластер | Использовать `KUBECONFIG` с множеством контекстов или `kubectl config use-context` |
| **External Secrets не готовы** | Job стартовал до синхронизации секретов из внешнего хранилища | Добавить `initContainers` с проверкой или увеличить `refreshInterval` |
| **Migration и DDL Locks** | Долгие миграции удерживают блокировки на таблицах | Использовать `LOCK TIMEOUT`; планировать миграции в окна низкой нагрузки |
| **Job создает слишком много подов** | `parallelism` не ограничен или превышен лимит API-server | Установить `parallelism` с запасом под лимиты etcd и API-server |

## Лучшие практики

1. **Идемпотентность миграций:** Каждая миграция должна быть безопасна для повторного запуска (использовать `CREATE IF NOT EXISTS`, идемпотентные SQL-операторы). Подробнее: **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.
2. **`backoffLimit: 0` для миграций:** При неудаче Job должен завершиться сразу, без попыток перезапуска, которые могут повредить данные.
3. **`restartPolicy: Never` для миграций:** Если миграция упала с ошибкой, повторный запуск в том же поде опасен — всегда создавайте новый под.
4. **TTL для завершённых Job:** Указывайте `ttlSecondsAfterFinished: 86400` (24 ч), чтобы кластер не засорялся завершёнными Job.
5. **Артефакты и логи:** Собирайте `kubectl logs job/xxx` в артефакт пайплайна с `expire_in: 7d` для аудита.
6. **Resource Quotas:** Указывайте `resources.requests/limits` в Job, чтобы не истощать ноду во время миграции.
7. **Separate ServiceAccount:** Job для миграций должен использовать отдельный ServiceAccount с минимальными правами, а не account приложения.
8. **Pre-flight проверки:** Запускайте `pg_isready`, `curl -sf http://db:5432` перед миграцией, чтобы отловить недоступность БД.
9. **Approval Gate для разрушительных миграций:** Миграции, которые нельзя откатить (DROP COLUMN, ALTER TYPE), должны требовать ручного approval.
10. **Notification on Completion:** Используйте `kubectl wait --for=condition=complete` и отправляйте уведомление в Slack/Telegram по завершении.

## Граничные случаи и ограничения

- **CronJob и часовой пояс:** `CRON_TZ` внутри поля `schedule` не поддерживается. Используйте `timeZone` (GA v1.27+).
- **Job и HPA:** CronJob, создающий Job с большим `parallelism`, может вызвать scale-up ноды; проверьте Cluster Autoscaler.
- **Секреты в Job:** Секреты должны быть созданы до запуска Job; используйте External Secrets Operator для автоматической синхронизации.
- **PodFailurePolicy (Kubernetes 1.25+):** Позволяет контролировать, при каких условиях Job считается неудавшимся (ExitCode, RetryLimit). Без политики любой CrashLoopBackOff считается неудачей. Пример: `podFailurePolicy: rules: - action: Fail - reason: ExitCode - containerName: migrate - exitCode: 1`
- **successPolicy (Kubernetes 1.28+):** Позволяет определить, когда Job считается успешным (`MaxIndexed`, `NonIndexed`). Для Work Queue с `completionMode: Indexed` используйте `MaxIndexed`, чтобы дождаться всех N шард.
- **Retention policies:** `successfulJobsHistoryLimit` и `failedJobsHistoryLimit` контролируют, сколько завершенных Job хранится в etcd. Для production CronJob рекомендуется `successfulJobsHistoryLimit: 3`, `failedJobsHistoryLimit: 1`.
- **Log shipping:** По умолчанию логи Job исчезают вместе с подом. Для аудита настройте `sidecar` или центральный коллектор (Fluentd/Vector) на уровне DaemonSet.
- **Error Budget при batch-задачах:** Длительные или часто падающие Job могут сжигать Error Budget через алерты. Отслеживайте burn rate отдельно для batch-воркеров.
- **CronJob schedule drift:** При изменении `spec.schedule` существующие Job не перезапускаются. Новая версия подхватывается только на следующем запуске. Для немедленной проверки используйте `kubectl create job --from=cronjob/...`.
- **Resource Quota exhaustion:** Массовый запуск Job может исчерпать quota namespace. Используйте `ResourceQuota` с `scopeSelector` для ограничения batch-воркеров.
- **Node affinity и taints:** Для фоновых задач настройте `nodeSelector`/`tolerations` на выделенные ноды, чтобы не конкурировать с latency-sensitive сервисами.
- **Immutable artifacts для Job:** Храните образы миграций по уникальному тегу (SHA digest), а не `latest`. Это гарантирует воспроизводимость и упрощает откат.

## Дополнительная информация

### Рекомендованные ссылки

- **[Recreate Deployment](./recreate_deployment.md)** — стратегия Recreate с примерами запуска Job и CronJob.
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — архитектура отката, включая откат миграций.
- **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)** — обратно-совместимые миграции БД.
- **[Job и CronJob в Kubernetes](../../Kubernetes/Base/job.md)** — полный справочник по API, `backoffLimit`, `podFailurePolicy`, `successPolicy`.
