# Pipeline Schedules и триггеры в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

> **Примечание:** Полная теория планировщика, cron-синтаксиса и Scheduled Pipeline Execution Policies описана в **[Pipeline Schedules](../Advanced/pipeline_schedules.md)**. Это руководство фокусируется на практической настройке операционных пайплайнов.

## Определения

* **Pipeline Schedule** — объект GitLab, запускающий пайплайн по cron-расписанию без необходимости коммитов; создаётся в UI или через API с правами Maintainer/Owner.
* **Scheduled Pipeline** — экземпляр пайплайна, созданный планировщиком; имеет источник `schedule` и переменные, определённые в расписании.
* **Pipeline Trigger** — программный запуск пайплайна через REST API (`POST /projects/:id/trigger/pipeline`) или ключевое слово `trigger:` в `.gitlab-ci.yml`.
* **Trigger Token** — токен проекта, дающий право на запуск пайплайна через Pipeline Triggers API; не даёт доступ к данным проекта.
* **Cross-project Pipeline** — пайплайн, запущенный в одном проекте из другого через `trigger: project:` или Pipeline Triggers API с `CI_JOB_TOKEN`.
* **Push Options** — флаги `git push` (`-o ci.variable.KEY=VALUE`, `-o ci.skip`), переопределяющие переменные или пропускающие пайплайн при push.
* **Webhook-based Trigger** — запуск пайплайна через вебхук из внешней системы или другого GitLab-проекта; использует эндпоинт `/projects/:id/ref/:ref/trigger/pipeline?token=`.
* **Scheduled Pipeline Execution Policy** — корпоративный механизм (GA в 19.2), запускающий пайплайны из security policy проекта по расписанию, независимо от коммитов.
* **Pipeline Schedule Worker** — фоновый Sidekiq-воркер, проверяющий активные расписания по собственному cron (`pipeline_schedule_worker_cron`); по умолчанию раз в 10 минут (`3-59/10 * * * *`).
* **Maximum Scheduled Pipeline Frequency** — минимальный интервал между запусками scheduled пайплайнов, задаваемый на уровне инстанса; по умолчанию 1 раз в 10 минут.
* **Staggered Cron** — практика распределения cron-выражений во времени (`5 * * * *`, `15 * * * *`, `25 * * * *`), чтобы избежать thundering herd при массовом запуске расписаний.
* **TRIGGER_PAYLOAD** — predefined переменная типа `file`, содержащая исходный вебхук-пайлоад при вебхук-триггере.

## Основные концепции

### Архитектура Pipeline Schedules

Pipeline Schedules реализованы как фоновые процессы GitLab Sidekiq:

1. **Хранилище**: Расписания хранятся в PostgreSQL с полями `id`, `cron`, `cron_timezone`, `ref`, `active`, `next_run_at`, `last_run_at`, `variables`, `inputs`.
2. **Планировщик**: Sidekiq-воркер `PipelineScheduleWorker` проверяет активные расписания по собственному cron (`pipeline_schedule_worker_cron`). По умолчанию воркер запускается раз в 10 минут (`3-59/10 * * * *`). При совпадении времени создаётся новый пайплайн. При высокой нагрузке воркер обрабатывает очереди батчами с небольшой задержкой, что может смещать фактический запуск на несколько минут.
3. **Парсинг cron**: GitLab использует библиотеку `fugit`, поддерживающую стандартный 5-польный cron плюс расширения `#` (n-й день недели, например `1#2` — второй понедельник) и `%` (остаток от деления, например `sun%2` — каждое второе воскресенье).
4. **Контекст выполнения**: Пайплайн запускается с источником `schedule`. Код забирается как snapshot последнего коммита ветки (`ref`) на момент создания пайплайна. Если между запуском и фактическим стартом ветка изменилась, пайплайн всё равно использует тот коммит, который был HEAD в момент постановки в очередь.
5. **Переменные и inputs**: Переменные расписания и значения `inputs` merge-ятся с project/group переменными. Schedule variables и inputs имеют наивысший приоритет среди всех переменных, кроме переданных при ручном запуске (`Run Now` / `play` API).

### Типы запуска пайплайнов

| Источник | `$CI_PIPELINE_SOURCE` | Механизм | Приоритет |
| :--- | :--- | :--- | :--- |
| Push | `push` | Webhook от Git push | Стандартный |
| Merge Request | `merge_request_event` | Webhook от MR | Стандартный |
| Schedule | `schedule` | Pipeline Schedule Worker | Плановый |
| API Trigger | `trigger` | Pipeline Triggers API | Программный |
| Parent Pipeline | `parent_pipeline` | `trigger:` keyword | Внутри CI/CD |
| Push Options | `push` | `git push -o ci.variable.KEY=VALUE` | Push-time override |
| Webhook | `trigger` | Внешний вебхук → `/projects/:id/ref/:ref/trigger/pipeline` | Внешний |
| Manual | `webide` / `api` | UI / API | Ручной |

### Push Options

Push Options позволяют переопределять переменные или пропускать пайплайн напрямую при `git push`:

- `-o ci.variable.KEY=VALUE` — добавляет/переопределяет переменную
- `-o ci.skip` — пропускает создание пайплайна
- `-o ci.deployment_branch=production` — устанавливает `CI_DEPLOYMENT_BRANCH`

Push Options работают только при push в GitLab и не влияют на уже созданные пайплайны.

### Webhook-based Trigger

GitLab поддерживает запуск пайплайнов через вебхук из внешней системы или другого GitLab-проекта. Для этого используется эндпоинт:

```
POST /projects/:id/ref/:ref/trigger/pipeline?token=<trigger_token>
```

Отличия от стандартного Pipeline Triggers API:
- `ref` передаётся в URL пути, а не в теле запроса
- Исходный вебхук-пайлоад доступен через predefined переменную `TRIGGER_PAYLOAD` (тип `file`)
- Предназначен для вызова из вебхуков push/tag событий

### Rate Limiting для Pipeline Triggers API

Pipeline Triggers API имеет собственный лимит запросов (~100 req/min на проект), отдельный от общего REST API. При массовом fan-out (>100 параллельных триггеров) возможен 429. Для защиты от каскадных отказов используйте circuit breaker с exponential backoff.

## Предварительные требования

1. **GitLab**: версия 17.x–19.x (текущий релиз — 19.4). Scheduled Pipeline Execution Policies доступны с 19.2+ (GA, experiment 18.0, beta 18.2).
2. **Права доступа**: роль Maintainer или Owner для создания расписаний; Developer для создания trigger tokens; Guest для read-only доступа к истории запусков.
3. **Токены**: для schedules — авторизация через сессию UI или PAT; для API — Project Access Token с scope `api`; для triggers — Trigger Token с scope `create_pipeline`; для cross-project — `CI_JOB_TOKEN` или Trigger Token целевого проекта.
4. **Сеть**: исходящий HTTPS (TCP 443) из GitLab для доставки вебхуков; входящий HTTPS для приёма вебхук-запросов с валидным сертификатом.
5. **Sidekiq**: для self-hosted инстансов убедитесь, что воркер `pipeline_schedule` запущен: `gitlab-ctl status sidekiq`. Частота воркера настраивается через `gitlab_rails['pipeline_schedule_worker_cron']` в `gitlab.rb`.
6. **Инструменты**: `curl` 7.68+, `jq` 1.6+, `glab` 2.20+ (опционально), `git` 2.30+, `terraform` 1.5+ (опционально).

## Практические сценарии

### Сценарий 1: Ежедневное сканирование безопасности

```yaml
stages:
  - scan

sast_scan:
  stage: scan
  image: aquasec/trivy:0.74.0
  script:
    - trivy image --format json --output report.json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  artifacts:
    reports:
      cyclonedx: sbom.json
    paths: [report.json]
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

**Создание расписания через UI:**
1. Перейдите в **CI/CD > Schedules**
2. Нажмите **New schedule**
3. Укажите:
   - **Description:** `Daily security scan`
   - **Cron:** `0 2 * * *` (ежедневно в 02:00 UTC)
   - **Timezone:** `UTC`
   - **Branch:** `main`
   - **Variables:** `SCAN_TYPE=full`
   - **Start in:** `1h` (опционально, отложенный первый запуск)

**Создание через API:**
```bash
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --request POST \
  --form "project_id=$PROJECT_ID" \
  --form "description=Daily security scan" \
  --form "ref=main" \
  --form "cron=0 2 * * *" \
  --form "cron_timezone=UTC" \
  --form "active=true" \
  --form "start_in=1h" \
  --form "variables[SCAN_TYPE]=full" \
  "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/pipeline_schedules"
```

### Сценарий 2: Pipeline Trigger через API

```bash
# Запуск пайплайна через Pipeline Triggers API
curl --request POST \
  --form "token=$TRIGGER_TOKEN" \
  --form "ref=main" \
  --form "variables[DEPLOY_ENV]=production" \
  --form "variables[RUN_MIGRATIONS]=true" \
  "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/trigger/pipeline"
```

```yaml
# .gitlab-ci.yml
stages:
  - deploy

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
    - if [ "$RUN_MIGRATIONS" == "true" ]; then
        kubectl exec -n production deploy/myapp -- flask db upgrade;
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "trigger"
```

> **Примечание:** Для передачи `spec:inputs` добавьте `--form "inputs[deploy_env]=production"` в curl-запрос. Для cross-project триггера используйте `CI_JOB_TOKEN` вместо Trigger Token — созданный пайплайн будет multi-project с видимым графом зависимостей.

### Сценарий 3: Scheduled Pipeline Execution Policy (GitLab 19.2+)

Scheduled Pipeline Execution Policy запускает compliance-пайплайны по расписанию в security policy проекте, независимо от коммитов в целевом проекте. В отличие от обычных schedules, политика не исполняет задания целевого проекта, а запускает задачи из security policy проекта.

```yaml
# .gitlab/security-policies/policy.yml в security policy проекте
pipeline_execution_schedule_policy:
  - name: weekly-security-audit
    description: Weekly security scan of all repositories
    enabled: true
    content:
      include:
        - project: your-group/your-project
          file: security-scan.yml
    schedules:
      - type: weekly
        start_time: "02:00"
        time_window:
          value: 3600
          distribution: random
        timezone: "UTC"
        days:
          - Monday
        # snooze:
        #   until: "2025-06-26T16:27:00+00:00"
        #   reason: "Critical production deployment"
```

> **Примечание:** Полная конфигурация policies, `snooze`, `branches` и `time_window` описана в **[Pipeline Schedules — полное руководство](../Advanced/pipeline_schedules.md)**.

### Сценарий 4: Push Options

```bash
# Запуск пайплайна с переопределением переменных
git push origin main \
  -o ci.variable.DEPLOY_ENV=staging \
  -o ci.variable.SKIP_TESTS=true \
  -o ci.skip
```

```yaml
workflow:
  rules:
    - if: $CI_COMMIT_BRANCH && $CI_PIPELINE_SOURCE == "push"
```

### Сценарий 5: Cross-project trigger

```yaml
# В проекте A
trigger_child:
  stage: deploy
  trigger:
    project: 'group/child-project'
    branch: main
    strategy: depend
  variables:
    PARENT_PROJECT: "project-a"
```

```yaml
# В проекте B (child)
trigger_from_parent:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - echo "Triggered from $PARENT_PROJECT"
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_PIPELINE_SOURCE == "parent_pipeline"
```

### Сценарий 6: Webhook-based Trigger

Для запуска пайплайна через вебхук из внешней системы или другого GitLab-проекта используйте специализированный эндпоинт:

```bash
# URL вебхука в исходной системе (внешний сервис или GitLab)
# https://gitlab.example.com/api/v4/projects/${CI_PROJECT_ID}/ref/main/trigger/pipeline?token=${TRIGGER_TOKEN}

# Проверка через curl (имитация входящего вебхука)
curl --request POST \
  "https://${CI_SERVER_HOST}/api/v4/projects/${CI_PROJECT_ID}/ref/main/trigger/pipeline?token=${TRIGGER_TOKEN}"
```

```yaml
# .gitlab-ci.yml
stages:
  - deploy

deploy_via_webhook:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - echo "Triggered via webhook"
    - echo "Source payload: $TRIGGER_PAYLOAD"
  rules:
    - if: $CI_PIPELINE_SOURCE == "trigger"
```

> **Примечание:** При вебхук-триггере исходный payload доступен через predefined переменную `TRIGGER_PAYLOAD` (тип `file`). Для просмотра: `cat $TRIGGER_PAYLOAD`.

### Сценарий 7: Управление расписаниями через glab CLI

`glab` позволяет управлять расписаниями без curl:

```bash
# Создание расписания с переменными и отложенным запуском
glab schedule create \
  --cron "0 3 * * *" \
  --description "Nightly build" \
  --ref main \
  --cron-timezone "UTC" \
  --active \
  --start-in "1h" \
  --variable "NIGHTLY_BUILD:true" \
  --variable "DEPLOY_ENV:staging"

# Список активных расписаний
glab schedule list --output json | jq '.[] | {id, description, cron, active, next_run_at}'

# Немедленный запуск расписания
glab schedule run 42

# Обновление расписания
glab schedule update 42 --cron "0 4 * * *" --active false

# Удаление расписания
glab schedule delete 42
```

### Сценарий 8: Управление расписаниями через Terraform (IaC)

Храните расписания как код. Ресурс `gitlab_pipeline_schedule` поддерживает переменные и `start_in`:

```hcl
resource "gitlab_pipeline_schedule" "nightly_security_scan" {
  project       = gitlab_project.app.id
  description   = "Nightly security scan"
  ref           = "main"
  cron          = "0 2 * * *"
  cron_timezone = "UTC"
  active        = true
  start_in      = "1h"

  variable {
    key   = "SCAN_TYPE"
    value = "full"
  }

  variable {
    key   = "NOTIFY_CHANNEL"
    value = "#security-scans"
  }
}
```

### Сценарий 9: SRE-мониторинг пропущенных запусков

Паттерн для отслеживания пропущенных или задержанных запусков через API + Prometheus:

```bash
# Получение активных расписаний
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/pipeline_schedules" | \
  jq '.[] | select(.active == true) | {id, description, next_run_at}' > schedules.json

# Проверка задержанных запусков
python3 -c "
import json, datetime
now = datetime.datetime.now(datetime.timezone.utc)
for s in json.load(open('schedules.json')):
    next_run = datetime.datetime.fromisoformat(s['next_run_at'].replace('Z', '+00:00'))
    if next_run < now:
        print(f'MISSED: {s[\"id\"]} {s[\"description\"]} (next_run_at={s[\"next_run_at\"]})')
"
```

Интеграция с мониторингом GitLab / Prometheus:
- Метрики Sidekiq: `sidekiq_jobs_running_total{queue="pipeline_schedule"}` — активность воркера
- Метрики пайплайнов: `gitlab_ci_pipeline_duration_seconds{source="schedule"}` — длительность scheduled пайплайнов
- Алерт: `absent(sidekiq_jobs_running_total{queue="pipeline_schedule"})` — воркер не запущен
- Алерт: `gitlab_ci_pipeline_duration_seconds{source="schedule"} > 3600` — пайплайн висит больше часа

## Валидация и проверка

Выполните проверки после настройки расписания или триггера:

1. **Schedule history:** Проверьте историю запусков в **CI/CD > Schedules > History**
   - *Ожидаемый результат:* расписание имеет записи запусков с корректным временем и статусом.
2. **Pipeline source:** В пайплайне проверьте `$CI_PIPELINE_SOURCE == "schedule"` или `"trigger"`
   - *Ожидаемый результат:* переменная содержит правильный источник.
3. **Trigger API:** Выполните curl-запрос и убедитесь, что пайплайн запустился
   - *Ожидаемый результат:* ответ содержит `id` нового пайплайна, статус `pending` или `running`.
4. **Push options:** Выполните `git push` с опциями и проверьте переменные в пайплайне
   - *Ожидаемый результат:* переменные `DEPLOY_ENV` и `SKIP_TESTS` имеют переданные значения.
5. **Webhook delivery:** Проверьте доставку вебхука в **Settings > Webhooks > Recent deliveries**
   - *Ожидаемый результат:* статус доставки `200 OK`, пайплайн запущен.
6. **CI Lint:** Проверьте конфигурацию под источник `schedule`
   ```bash
   glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=schedule --variable CI_COMMIT_BRANCH=main
   ```
   - *Ожидаемый результат:* lint проходит без ошибок, jobs для `schedule` source присутствуют.

## Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Schedule not running** | Неверный cron-синтаксис | Проверьте синтаксис: `crontab.guru`. GitLab использует UTC. |
| **Pipeline skipped** | Ветка не существует или недоступна | Убедитесь, что ветка `main` существует и доступна для Runner'ов |
| **Trigger returns 404** | Неверный URL или проект | Проверьте URL: `/api/v4/projects/:id/trigger/pipeline` |
| **Trigger returns 401** | Неверный или просроченный токен | Используйте Trigger Token с scope `create_pipeline` или `CI_JOB_TOKEN` для cross-project |
| **Variables not passed** | Переменные определены неправильно | Проверьте формат `--form "variables[KEY]=value"` в API-запросе |
| **Webhook not delivered** | URL недоступен или токен неверный | Проверьте URL доступность и `token` параметр в вебхук-URL |
| **Schedule token invalid** | Токен истек или удалён | Пересоздайте токен в настройках проекта |
| **Cron timezone wrong** | Используется локальное время вместо UTC | Укажите `timezone` явно в настройках расписания |
| **429 Too Many Requests** | Превышен лимит Pipeline Triggers API | Увеличьте задержку между триггерами или используйте circuit breaker |
| **Maximum frequency exceeded** | Cron просит запуск чаще, чем `pipeline_schedule_worker_cron` | Увеличьте частоту воркера в `gitlab.rb` или измените cron |
| **TRIGGER_PAYLOAD empty** | Вебхук не передал payload или неверный Content-Type | Убедитесь, что исходный вебхук отправляет `Content-Type: application/json` |
| **Cross-project 403** | `CI_JOB_TOKEN` не имеет доступа к другому проекту | Используйте Trigger Token из проекта-получателя |

## Лучшие практики (Best Practices)

### Безопасность

* **Токены:** используйте отдельные Trigger Tokens для разных источников; ротируйте токены каждые 90 дней; храните токены в Vault или GitLab Variables (protected, masked).
* **RBAC:** ограничьте создание расписаний ролью Maintainer; отключите `Allow pipeline triggers` для Contributor в групповых настройках.
* **Audit Logging:** включите Audit Events для отслеживания создания, изменения и удаления расписаний; интегрируйте с SIEM.
* **Webhook Security:** для вебхук-триггеров используйте HTTPS с валидным сертификатом; ограничьте IP-источники в firewall.
* **Protected Branches:** для schedules, запускающих деплой, используйте protected ветки с required approvals.

### Организация

* **Naming Convention:** используйте префиксы `nightly-`, `weekly-`, `hourly-`; добавьте описание с контактом ответственного.
* **Timezone Alignment:** используйте UTC или единый timezone для всех расписаний; документируйте локальное время в описании.
* **Avoid Duplicates:** не создавайте дублирующие расписания; используйте один cron с нужной частотой вместо нескольких.
* **Documentation:** для каждого расписания укажите: цель, контакт, ожидаемое время выполнения, escalation path.
* **Staggered Cron:** при множестве проектов распределяйте cron-выражения (`5 * * * *`, `15 * * * *`, `25 * * * *`), чтобы избежать thundering herd на Sidekiq и Runner'ах.
* **Change Management:** все изменения в production-расписаниях проходят через MR с approval; используйте protected ветки для schedules, запускающих деплой.

### Производительность

* **Off-Peak Scheduling:** запускайте тяжелые пайплайны (ночные сборки, полные тесты) в 02:00–05:00 UTC.
* **Resource Isolation:** настройте `interruptible: false` для критических scheduled задач, чтобы их не отменил `auto_cancel`.
* **start_in для деплоев:** используйте `start_in` для отложенного первого запуска при создании расписания, чтобы избежать случайного запуска в рабочее время.
* **Inputs вместо переменных:** используйте `spec:inputs` с типами (`string`, `boolean`, `number`) вместо набора строковых переменных — GitLab валидирует типы на этапе компиляции.
* **Batch Execution:** для множества проектов используйте Scheduled Pipeline Execution Policies вместо отдельных schedules.
* **time_window distribution:** для Scheduled Pipeline Execution Policies используйте `time_window` с `distribution: random` для плавного распределения нагрузки.

### Надёжность (SRE)

* **Мониторинг:** отслеживайте `sidekiq_jobs_running_total{queue="pipeline_schedule"}`, `gitlab_ci_pipeline_duration_seconds{source="schedule"}`; настройте алерты на отсутствие воркера или задержанные запуски.
* **Резервное копирование:** экспортируйте расписания через API в JSON для disaster recovery: `curl .../pipeline_schedules | jq > schedules-backup.json`.
* **Disaster Recovery:** восстанавливайте расписания через Terraform или API; тестируйте восстановление раз в квартал.
* **Capacity Planning:** при росте количества расписаний мониторьте длину очереди `pipeline_schedule`; при превышении 1000 jobs увеличивайте количество Sidekiq-воркеров.
* **Incident Response:** подготовьте runbook для пропущенных критических расписаний (ночной деплой, security scan); определите escalation path.
* **Notification on Failure:** добавьте уведомления (Slack, email, PagerDuty) для failed scheduled пайплайнов.

## Крайние случаи (Edge Cases)

* **Thundering herd:** При одновременном запуске 100+ расписаний в одно время Sidekiq и Runner'ы испытывают пиковую нагрузку. Решение: staggered cron (`5 * * * *`, `15 * * * *`, `25 * * * *`).
* **Maximum frequency exceeded:** Cron-выражение просит запуск чаще, чем `pipeline_schedule_worker_cron`. Пайплайн запускается с задержкой до следующего тика воркера. Решение: увеличьте частоту воркера в `gitlab.rb` или измените cron.
* **Ambiguous refs:** Краткое имя `ref` может совпадать и с веткой, и с тегом. Используйте полные имена: `refs/heads/main` или `refs/tags/v1.0`.
* **Schedule execution during maintenance:** При обновлении GitLab или перезапуске Sidekiq scheduled пайплайны могут быть отложены. Решение: используйте `start_in` для критических расписаний.
* **Timezones и DST:** При переходе на летнее/зимнее время cron-выражения сдвигаются на 1 час. Используйте UTC для критических расписаний.
* **Trigger loop:** Рекурсивный вызов пайплайна через вебхук или API может создать бесконечный цикл. GitLab не предотвращает это автоматически. Решение: добавьте guard-переменную или лимит depth.
* **Pipeline cancellation during schedule:** Если пайплайн запущен по расписанию, но в это время запущен ручной деплой, `auto_cancel` может отменить scheduled пайплайн. Решение: `interruptible: false` для критических scheduled задач.
* **Storage quota during scheduled cleanup:** Scheduled пайплайны, генерирующие артефакты, могут быстро заполнить storage. Решение: настройте `expire_in` для артефактов и lifecycle policies.
* **Cross-project trigger with deleted project:** Если дочерний проект удалён, родительский пайплайн завершается с 404. Решение: используйте `strategy: depend` и добавьте fallback-задачу.
* **Webhook payload size:** `TRIGGER_PAYLOAD` ограничен размером вебхука (по умолчанию 1 MB). Для больших payload используйте S3 или blob storage с ссылкой в переменной.
* **Schedule limits on Free tier:** Free tier ограничивает 10 активных расписаний на проект; Premium — 50; Ultimate — 100. При необходимости запросите увеличение у администратора.

## Очистка

### Удаление расписаний через API

```bash
# Удаление конкретного расписания
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/pipeline_schedules/$SCHEDULE_ID"

# Деактивация расписаний, не запускавшихся больше 30 дней
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/pipeline_schedules" | \
  jq -r '.[] | select(.last_run_at < (now - 30*24*60*60 | tonumber) | todate) | .id' | \
  while read sched_id; do
    echo "Deactivating schedule $sched_id"
    curl --header "PRIVATE-TOKEN: $TOKEN" \
      --request PUT \
      --form "active=false" \
      "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/pipeline_schedules/$sched_id"
  done
```

### Через glab CLI

```bash
# Пакетная очистка старых расписаний по критерию описания
glab schedule list --output json | jq -r '.[] | select(.description | test("temp|deprecated")) | .id' | \
  while read sched_id; do
    echo "Deleting schedule $sched_id"
    glab schedule delete "$sched_id"
  done
```

### Резервное копирование и восстановление

```bash
# Экспорт всех расписаний проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/pipeline_schedules" | \
  jq '.[] | {id, description, ref, cron, cron_timezone, active, variables, inputs}' \
  > schedules-backup.json

# Восстановление (создание копий)
jq -r '.[] | @sh "curl --header \\\"PRIVATE-TOKEN: $TOKEN\\\" \
  --request POST \
  --form \\\"project_id='"$PROJECT_ID"'\\\" \
  --form \\\"description=\(.description)\\\" \
  --form \\\"ref=\(.ref)\\\" \
  --form \\\"cron=\(.cron)\\\" \
  --form \\\"cron_timezone=\(.cron_timezone)\\\" \
  --form \\\"active=\(.active)\\\"" schedules-backup.json | bash
```

## Дополнительная информация

### Смотрите также

- **[Pipeline Schedules — полное руководство](../Advanced/pipeline_schedules.md)** — теория, cron-синтаксис, Scheduled Pipeline Execution Policies
- **[Cross-project pipelines](../Advanced/Downstream_Pipelines/multi_project_pipelines.md)** — триггеры между проектами
- **[API и Webhooks автоматизация](../Advanced/api_and_webhooks_automation.md)** — програмный запуск пайплайнов
- **[Merge Trains и advanced workflows](../Advanced/gitlab_ci_advanced_workflow.md)** — оптимизация параллельных запусков
- **[Pipeline Triggers API rate limits](../Advanced/ci_cd_api_rate_limits.md)** — лимиты и circuit breaker
- **[glab schedule commands](https://docs.gitlab.com/cli/schedule/)** — управление расписаниями из CLI
- **[Pipeline Schedules API](https://docs.gitlab.com/api/pipeline_schedules/)** — полное руководство по REST API
- **[Scheduled Pipeline Execution Policies](https://docs.gitlab.com/user/application_security/policies/scheduled_pipeline_execution_policies/)** — конфигурация policies в `.gitlab/security-policies/policy.yml`
- **[Cron syntax](https://docs.gitlab.com/topics/cron/)** — расширения fugit и ограничения GitLab
- **[CI/CD limits](https://docs.gitlab.com/administration/cicd/limits/)** — лимиты расписаний и максимальная частота воркера
