# Планировщик пайплайнов (Pipeline Schedules)

**Актуально для:** GitLab 17.x–19.x

## Определения

- **Pipeline Schedule** — объект GitLab, запускающий пайплайн по cron-расписанию без необходимости коммитов. Используется для периодических задач: ночных сборок, сканирования безопасности, регулярных деплоев.
- **Scheduled Pipeline** — экземпляр пайплайна, созданный планировщиком. Имеет источник `schedule` и переменные, определенные в расписании.
- **Scheduled Pipeline Execution Policy** — корпоративный механизм (experiment 18.0 → beta 18.2 → GA 19.2), создающий отдельные пайплайны по расписанию для регулярного сканирования. В отличие от обычных пайплайнов, политика не исполняет задания проекта, а запускает задачи из security policy проекта.
- **Pipeline Schedule Variables** — переменные, передаваемые планировщиком в пайплайн. Переопределяются при каждом запуске и имеют приоритет над project/group переменными.
- **Active Schedule** — планировщик, который не был отключен и не превысил лимит пропусков запусков.
- **Schedule Token** — уникальный токен, идентифицирующий пайплайн как запущенный через планировщик (`$CI_PIPELINE_SOURCE == "schedule"`).
- **Cron Syntax** — стандартный формат cron, который GitLab парсит через библиотеку `fugit`. Поддерживает расширения: `#` (n-й день недели, например `1#2` — второй понедельник), `%` (остаток от деления, например `sun%2` — каждое второе воскресенье), `L` (последний день месяца). Интервалы меньше часа задаются как `*/5`. Минимальная granulality ограничена `maximum scheduled pipeline frequency` инстанса.
- **Pipeline Schedule Worker** — фоновый Sidekiq-воркер, который проверяет активные расписания и ставит пайплайны в очередь. Работает по собственному cron (`pipeline_schedule_worker_cron`), по умолчанию раз в 10 минут (`3-59/10 * * * *`).
- **Maximum Scheduled Pipeline Frequency** — минимальный интервал между запусками scheduled пайплайнов, задаваемый на уровне инстанса. По умолчанию 1 раз в 10 минут. Если cron-расписание просит чаще — пайплайн запускается с задержкой до следующего тика воркера.
- **Staggered Cron** — практика распределения cron-выражений во времени (например, `5 * * * *`, `15 * * * *`, `25 * * * *`), чтобы избежать thundering herd при массовом запуске расписаний.
- **spec:inputs** — типизированные входы пайплайна, определяемые в корневом `.gitlab-ci.yml`. Pipeline Schedule может передавать значения в эти входы (лимит 20 на расписание в GitLab 17.11+, 100 в 19.0+).
- **start_in** — опция расписания, откладывающая первый запуск на заданный интервал (например, `1h`, `30m`). Доступна с GitLab 13.7+.
- **Snooze** — временная пауза для Scheduled Pipeline Execution Policy (доступна в GA 19.2+). Позволяет приостановить политику на период обслуживания.

## Предварительные требования

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Pipeline Schedules (базовый) | 11.0+ | Стандартный cron-планировщик |
| `rules:changes` с `compare_to` | 12.3+ | Дифференциальный запуск |
| `rules:changes:compare_to` (переменные) | 17.2+ | Динамическое сравнение с веткой |
| Scheduled Pipeline Execution Policies | 19.2+ | GA (experiment 18.0, beta 18.2); регулярный compliance |
| `start_in` (отложенный запуск) | 13.7+ | Задержка первого запуска расписания |
| `inputs` в расписаниях | 17.11+ | Лимит 20; 100 в 19.0+; типизация через `spec:inputs` |
| `snooze` в policies | 19.2+ | Временная пауза политики |
| `branches` в policies | 19.2+ | До 5 веток на schedule (не default branch) |
| `time_window` distribution | 19.2+ | Random distribution для policies; минимум 600 сек |
| Fugit cron extensions (`#`, `%`) | 13.12+ | `1#2` — 2-й понедельник; `sun%2` — каждое 2-е воскресенье |
| Maximum scheduled pipeline frequency | Настраивается | По умолчанию раз в 10 мин (`3-59/10 * * * *`) |

### Необходимые знания

- Cron-синтаксис и ограничения GitLab (`fugit`, `maximum scheduled pipeline frequency`)
- Структура `.gitlab-ci.yml`, `workflow:rules`, `rules`, `spec:inputs`
- GitLab RBAC: роли Maintainer/Owner для создания расписаний
- Переменные пайплайна и их приоритеты
- REST API GitLab для управления расписаниями
- `glab` CLI для оперативного управления
- GitLab administration: `gitlab.rb`, `pipeline_schedule_worker_cron` (для self-hosted)
- Security Policies: структура `.gitlab/security-policies/policy.yml` (для Scheduled Execution Policies)

### Инструменты диагностики

- **UI**: Admin → CI/CD → Pipeline Schedules
- **API**: `GET /projects/:id/pipeline_schedules` — список расписаний
- **API**: `GET /projects/:id/pipeline_schedules/:schedule_id/pipelines` — история запусков
- **API**: `POST /projects/:id/pipeline_schedules/:schedule_id/play` — немедленный запуск
- **Audit Events**: Логи создания, изменения и удаления расписаний
- **`glab` CLI**: `glab schedule create/list/play/delete` — управление расписаниями через CLI
- **CI Lint**: `glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=schedule` — проверка конфигурации
- **Sidekiq/Queue**: `sidekiq_jobs_running_total{queue="pipeline_schedule"}` — метрика активности воркера

## Основные концепции

### Архитектура Pipeline Schedules

Pipeline Schedules реализованы как фоновые процессы GitLab Sidekiq:

1. **Хранилище (Database)**: Расписания хранятся в PostgreSQL. Каждое расписание имеет уникальный `id`, `cron`, `cron_timezone`, `description`, `ref`, `active`, `start_in`, набор `variables` и/или `inputs`, а также служебные поля `next_run_at` и `last_run_at`.
2. **Планировщик (Scheduler)**: Sidekiq-воркер `PipelineScheduleWorker` проверяет активные расписания по собственному cron (`pipeline_schedule_worker_cron`). По умолчанию воркер запускается раз в 10 минут (`3-59/10 * * * *`). При совпадении времени создается новый пайплайн. При высокой нагрузке воркер обрабатывает очереди батчами с небольшой задержкой между батчами, что может смещать фактический запуск на несколько минут.
3. **Парсинг cron**: GitLab использует библиотеку `fugit` для парсинга cron-выражений. Она поддерживает стандартный синтаксис плюс расширения `#` (nth weekday) и `%` (modulo). Валидация в UI выполняется через `cron-validator`, а отображение человекочитаемого описания — через `cRonstrue`.
4. **Контекст выполнения**: Пайплайн запускается с источником `schedule`. Код забирается как snapshot последнего коммита целевой ветки (`ref`) на момент создания пайплайна. Если между запуском и фактическим стартом ветка изменилась, пайплайн все равно использует тот коммит, который был HEAD в момент постановки в очередь.
5. **Переменные и inputs**: Переменные расписания и значения `inputs` merge-ятся с project/group переменными. Schedule variables и inputs имеют наивысший приоритет среди всех переменных, кроме переданных при ручном запуске (`Run Now`) через API.

### Cron-синтаксис GitLab

GitLab использует стандартный 5-польный cron, парсимый через `fugit`:

| Поле | Диапазон | Специальные значения |
| :--- | :--- | :--- |
| Минуты | 0-59 | `*`, `*/5`, `0,30` |
| Часы | 0-23 | `*`, `*/2`, `9-18` |
| День месяца | 1-31 | `*`, `1`, `L` (последний день) |
| Месяц | 1-12 | `*`, `1,4,7,10` (ежеквартально) |
| День недели | 0-6 (0=воскресенье) | `*`, `1` (понедельник), `5` (пятница) |

**Расширения fugit:**
- `1#2` — второй понедельник месяца.
- `sun%2` — каждое второе воскресенье.
- `L` — последний день месяца (поддерживается в UI/валидации).

**Важно:** даже если cron-выражение разрешает запуск чаще, пайплайн не начнется раньше следующего тика `PipelineScheduleWorker`. По умолчанию это раз в 10 минут. Для изменения частоты редактируйте `gitlab_rails['pipeline_schedule_worker_cron']` в `gitlab.rb` и выполните `gitlab-ctl reconfigure`.

**Примеры:**
```yaml
# Каждые 5 минут
schedule:
  - cron: "*/5 * * * *"

# Каждый час в 00 минут
schedule:
  - cron: "0 * * * *"

# Каждый день в 03:30 UTC
schedule:
  - cron: "30 3 * * *"
    timezone: "UTC"

# Каждый понедельник в 09:00 Europe/Moscow
schedule:
  - cron: "0 9 * * 1"
    timezone: "Europe/Moscow"

# Каждые 2 часа
schedule:
  - cron: "0 */2 * * *"

# Каждое воскресенье в полночь
schedule:
  - cron: "0 0 * * 0"

# Staggered: распределенный запуск для большого числа проектов
schedule:
  - cron: "5 * * * *"   # в :05 каждого часа
  - cron: "15 * * * *"  # в :15
  - cron: "25 * * * *"  # в :25

# Отложенный первый запуск на 1 час
schedule:
  - cron: "0 3 * * *"
    start_in: "1h"
    timezone: "UTC"
```

### Приоритет переменных в Scheduled Pipeline

При запуске через планировщик переменные и inputs merge-ятся в следующем порядке (от высшего к низшему):

1. Переменные, переданные при ручном запуске (Run Now / `play` API)
2. Значения `inputs` расписания
3. Переменные расписания (Schedule Variables)
4. Pipeline Variables (если разрешены)
5. Project Variables
6. Group Variables
7. Instance Variables
8. Predefined Variables (`CI_*`)

### Scheduled Pipeline Execution Policies (19.2+)

Отдельный механизм для регулярного сканирования безопасности и compliance, работающий на уровне security policy проекта:

- **Жизненный цикл**: Experiment в GitLab 18.0 (флаг `scheduled_pipeline_execution_policy_type`), beta в 18.2, GA в 19.2.
- **Отличие от обычных schedules**: Запускает пайплайны из security policy проекта, а не из `.gitlab-ci.yml` целевого проекта. Политика не исполняет задания целевого проекта, а инжектирует отдельные задания из policy.
- **Применение**: Регулярный аудит всех репозиториев группы на соответствие политикам, даже если в репозитории нет новых коммитов.
- **Ограничения**: Максимум 1 политика с 1 schedule на security policy проект (на момент GA). До 5 веток на schedule. Минимальный `time_window` — 600 секунд (10 минут).
- **Snooze**: Возможность временно приостановить schedule на период обслуживания через `snooze.until` (ISO8601).

## Практические сценарии

### Сценарий 1: Ночная сборка и тестирование

Запуск полного цикла тестирования каждую ночь для catching регрессий:

```yaml
# .gitlab-ci.yml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

stages:
  - test
  - report

test:nightly:
  stage: test
  image: python:3.12
  script:
    - pip install -r requirements.txt
    - pytest tests/ --junitxml=report.xml
  artifacts:
    reports:
      junit: report.xml
    expire_in: 1 week

# В UI: Admin → CI/CD → Pipeline Schedules → New schedule
# cron: "0 3 * * *" (каждый день в 03:00 UTC)
# target branch: main
# variables: NIGHTLY_BUILD=true
```

### Сценарий 2: Еженедельный security scan

Запуск сканирования безопасности раз в неделю:

```yaml
# .gitlab-ci.yml
security:weekly_scan:
  stage: test
  image: aquasec/trivy:latest
  script:
    - trivy fs --format cyclonedx --output sbom.json .
    - trivy fs --severity HIGH,CRITICAL --exit-code 0 .
  artifacts:
    reports:
      cyclonedx: sbom.json
    expire_in: 1 month
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: always
```

### Сценарий 3: Динамический деплой на staging по расписанию

Автоматический деплой в staging каждый день в рабочие часы:

```yaml
deploy:staging:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl apply -f k8s/staging/
    - kubectl rollout status deployment/app -n staging
  environment:
    name: staging
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: manual
    - if: $CI_COMMIT_BRANCH == "develop"
      when: manual
```

### Сценарий 4: Переменные расписания для дифференциального запуска

Использование переменных расписания для управления поведением:

```yaml
# .gitlab-ci.yml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      variables:
        SCHEDULED_RUN: "true"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

test:full:
  stage: test
  image: python:3.12
  script:
    - if [ "$SCHEDULED_RUN" == "true" ]; then pytest tests/ --full-suite; else pytest tests/ --quick; fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 5: Scheduled Pipeline Execution Policy для compliance

Регулярный аудит соответствия политикам безопасности (GitLab 19.2+). Конфигурация хранится в security policy проекте в файле `.gitlab/security-policies/policy.yml`:

```yaml
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

**Ключевые моменты:**
- `type`: `daily`, `weekly`, `monthly`.
- `start_time`: время старта в 24-часовом формате.
- `time_window.value`: длительность окна распределения в секундах (минимум 600).
- `time_window.distribution`: только `random` на текущий момент.
- `branches`: необязательный массив веток (максимум 5). Если не указан — запуск только на default branch.
- `snooze`: временная приостановка.
- `variables_override`: опциональный блок для контроля доступа к project/group переменным.

### Сценарий 6: Управление расписаниями через API

Создание, обновление и удаление расписаний программно. Обратите внимание: для создания с `inputs` используйте `--form`, а не `--data`:

```bash
# Создание расписания с переменными и отложенным запуском
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --request POST \
  --form "project_id=$PROJECT_ID" \
  --form "description=Nightly build" \
  --form "ref=main" \
  --form "cron=0 3 * * *" \
  --form "cron_timezone=UTC" \
  --form "active=true" \
  --form "start_in=1h" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules"

# Создание с inputs (17.11+)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --request POST \
  --form "project_id=$PROJECT_ID" \
  --form "description=Nightly deploy" \
  --form "ref=main" \
  --form "cron=0 3 * * *" \
  --form "inputs[][name]=deploy_env" \
  --form "inputs[][value]=staging" \
  --form "inputs[][name]=skip_tests" \
  --form "inputs[][value]=true" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules"

# Список расписаний (с фильтрацией по scope)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules?scope=active" | \
  jq '.[] | {id, description, cron, active, next_run_at}'

# Немедленный запуск расписания (игнорирует cron)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --request POST \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules/$SCHEDULE_ID/play"

# Обновление расписания
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --request PUT \
  --form "cron=0 4 * * *" \
  --form "active=false" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules/$SCHEDULE_ID"

# Удаление расписания
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --request DELETE \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules/$SCHEDULE_ID"
```

### Сценарий 7: Ограничение запусков по дням недели

Запуск только в рабочие дни (понедельник-пятница):

```yaml
# .gitlab-ci.yml
deploy:workdays:
  stage: deploy
  script:
    - ./deploy.sh
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: always
  # cron: "0 9 * * 1-5" (пн-пт, 09:00)
  # cron: "0 */4 * * 1-5" (пн-пт, каждые 4 часа)
```

### Сценарий 8: spec:inputs и типизированные переменные расписания

Использование `spec:inputs` вместо набора неструктурированных переменных. GitLab проверяет типы на этапе компиляции конфигурации:

```yaml
# .gitlab-ci.yml
spec:
  inputs:
    deploy_env:
      type: string
      default: "staging"
    skip_tests:
      type: boolean
      default: false
    notify_channel:
      type: string
      default: "#ci-notifications"

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:
  stage: deploy
  script:
    - echo "Deploying to $DEPLOY_ENV"
    - if [ "$SKIP_TESTS" != "true" ]; then pytest tests/; fi
    - echo "Notification: $NOTIFY_CHANNEL"
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

В UI/API расписание передает значения inputs:
```bash
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --request POST \
  --form "project_id=$PROJECT_ID" \
  --form "description=Nightly deploy" \
  --form "ref=main" \
  --form "cron=0 3 * * *" \
  --form "cron_timezone=UTC" \
  --form "inputs[][name]=deploy_env" \
  --form "inputs[][value]=staging" \
  --form "inputs[][name]=skip_tests" \
  --form "inputs[][value]=true" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules"
```

### Сценарий 9: Управление расписаниями через glab CLI

`glab` позволяет создавать,列出 и удалять расписания без curl:

```bash
# Создание расписания с переменными
glab schedule create \
  --cron "0 3 * * *" \
  --description "Nightly build" \
  --ref main \
  --variable "NIGHTLY_BUILD:true" \
  --variable "DEPLOY_ENV:staging"

# Список активных расписаний
glab schedule list --output json | jq '.[] | {id, description, cron, active}'

# Немедленный запуск расписания
glab schedule play 42

# Удаление расписания
glab schedule delete 42
```

### Сценарий 10: Backup и восстановление расписаний

Экспорт всех расписаний проекта в JSON для миграции или disaster recovery:

```bash
# Экспорт расписаний проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules" | \
  jq '.[] | {id, description, ref, cron, cron_timezone, active, variables, inputs}' \
  > schedules-backup.json

# Восстановление (создание копий)
jq -r '.[] | @sh "curl --header \"PRIVATE-TOKEN: $TOKEN\" \
  --request POST \
  --form \"project_id='"$PROJECT_ID"'\" \
  --form \"description=\(.description)\" \
  --form \"ref=\(.ref)\" \
  --form \"cron=\(.cron)\" \
  --form \"cron_timezone=\(.cron_timezone)\" \
  --form \"active=\(.active)\"' schedules-backup.json | bash
```

### Сценарий 11: Управление через Terraform (IaC)

Храните расписания как код. Ресурс `gitlab_pipeline_schedule` поддерживает переменные и `start_in`:

```hcl
resource "gitlab_pipeline_schedule" "nightly_security_scan" {
  project     = gitlab_project.app.id
  description = "Nightly security scan"
  ref         = "main"
  cron        = "0 2 * * *"
  cron_timezone = "UTC"
  active      = true

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

### Сценарий 12: Мониторинг и алертинг (SRE)

SRE-паттерн: мониторинг пропущенных или задержанных запусков через API + Prometheus/GitLab observability:

```bash
# Проверка расписаний, которые должны были запуститься, но не запустились
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules" | \
  jq '.[] | select(.active == true) | {id, description, next_run_at}' > schedules.json

# Сравнение next_run_at с текущим временем
python3 -c "
import json, datetime
now = datetime.datetime.now(datetime.timezone.utc)
for s in json.load(open('schedules.json')):
    next_run = datetime.datetime.fromisoformat(s['next_run_at'].replace('Z', '+00:00'))
    if next_run < now:
        print(f'MISSED: {s[\"id\"]} {s[\"description\"]} (next_run_at={s[\"next_run_at\"]})')
"
```

Интеграция с GitLab observability:
- Метрики Sidekiq: `sidekiq_jobs_running_total{queue="pipeline_schedule"}`.
- Метрики пайплайнов: `gitlab_ci_pipeline_duration_seconds{source="schedule"}`.
- Алерт: `absent(sidekiq_jobs_running_total{queue="pipeline_schedule"})` — воркер не запущен.

### Сценарий 13: Batch cleanup и аудит

Массовое удаление или деактивация старых расписаний:

```bash
# Деактивация расписаний, не запускавшихся больше 30 дней
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules" | \
  jq -r '.[] | select(.last_run_at < (now - 30*24*60*60 | tonumber) | todate) | .id' | \
  while read sched_id; do
    echo "Deactivating schedule $sched_id"
    curl --header "PRIVATE-TOKEN: $TOKEN" \
      --request PUT \
      --form "active=false" \
      "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules/$sched_id"
  done

# Удаление через glab
glab schedule list --output json | jq -r '.[] | select(.description | test("temp|deprecated")) | .id' | \
  while read sched_id; do
    echo "Deleting schedule $sched_id"
    glab schedule delete "$sched_id"
  done
```

### Проверка cron-синтаксиса и частоты

```bash
# Онлайн-валидаторы: crontab.guru, crontab.cronhub.io
# Учтите: GitLab использует UTC и fugit-расширения (#, %)
# Проверка через GitLab CI Lint (имитирует scheduled source)
glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=schedule --variable CI_COMMIT_BRANCH=main

# Проверьте cron воркера на self-hosted инстансе
sudo gitlab-ctl show-config | grep pipeline_schedule_worker_cron
# По умолчанию: 3-59/10 * * * * (раз в 10 минут)

# Проверка actual next_run_at через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules" | \
  jq '.[] | {id, description, next_run_at, last_run_at}'
```

### Просмотр истории запусков

```bash
# Список пайплайнов от конкретного расписания
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline_schedules/$SCHEDULE_ID/pipelines" | \
  jq '.[] | {id, status, created_at, duration}'
```

### Отладка переменных и inputs расписания

```yaml
debug_schedule:
  stage: .pre
  script:
    - echo "Pipeline source: $CI_PIPELINE_SOURCE"
    - echo "Schedule vars: $SCHEDULED_RUN"
    - echo "Inputs: $DEPLOY_ENV $SKIP_TESTS"
    - env | sort | grep -E "^(CI_|SCHEDULED_|DEPLOY_|SKIP_)"
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: always
```

## Лучшие практики

### Безопасность

1. **Least Privilege**: Создавайте расписания только для Maintainer/Owner. Ограничьте создание расписаний через групповые политики.
2. **Protected Variables**: Используйте protected переменные для деплоев из расписаний. Запретите push в protected ветки без approval.
3. **Audit Logging**: Включите Audit Events для отслеживания создания и изменения расписаний.
4. **Limit Schedule Variables**: Ограничьте количество переменных в расписании. Используйте `spec:inputs` для типизации.
5. **Token Rotation**: Регулярно ротируйте токены, используемые в scheduled пайплайнах.
6. **Policy Scope**: Для Scheduled Pipeline Execution Policies ограничьте `policy_scope` конкретными проектами/группами, а не `*`.

### Организация

7. **Naming Convention**: Используйте префиксы для расписаний: `nightly-`, `weekly-`, `hourly-`. Добавьте описание с контактом ответственного.
8. **Timezone Alignment**: Используйте UTC или единый timezone для всех расписаний. Документируйте локальное время в описании.
9. **Avoid Duplicates**: Не создавайте дублирующие расписания. Используйте один cron с нужной частотой вместо нескольких.
10. **Documentation**: Для каждого расписания укажите в описании: цель, контакт, ожидаемое время выполнения.
11. **Schedule Tokens**: Используйте уникальные переменные в каждом расписании для идентификации источника запуска.
12. **Staggered Cron**: При множестве проектов распределяйте cron-выражения во времени (`5 * * * *`, `15 * * * *`), чтобы избежать пиков на Sidekiq и Runner'ах.

### Производительность

13. **Off-Peak Scheduling**: Запускайте тяжелые пайплайны (ночные сборки, полные тесты) в нерабочее время (02:00–05:00 UTC).
14. **Pipeline Triggers vs Schedules**: Для внешних триггеров используйте Trigger API вместо schedules — меньше накладных расходов.
15. **Batch Execution**: Для множества проектов используйте Scheduled Pipeline Execution Policies вместо отдельных schedules.
16. **Resource Isolation**: Настройте `interruptible: false` для критических scheduled задач, чтобы их не отменил `auto_cancel`.
17. **Notification on Failure**: Добавьте уведомления (Slack, email, PagerDuty) для failed scheduled пайплайнов.
18. **start_in для деплоев**: Используйте `start_in` для отложенного первого запуска при создании расписания вручную, чтобы избежать случайного запуска в рабочее время.
19. **time_window distribution**: Для Scheduled Pipeline Execution Policies используйте `time_window` с `distribution: random` для плавного распределения нагрузки.
20. **Inputs вместо кучи переменных**: Используйте `spec:inputs` с типами (`string`, `boolean`, `number`) вместо набора строковых переменных — GitLab валидирует типы на этапе компиляции.

## Граничные случаи и ограничения

### Технические ограничения

| Параметр | Лимит | Примечание |
| :--- | :--- | :--- |
| Активных расписаний на проект | 10 (Free), 50 (Premium), 100 (Ultimate) | Настраивается администратором |
| Переменных в расписании | 20 (17.11+), 100 (19.0+) | Должны быть определены в пайплайне |
| Inputs в расписании | 20 (17.11+), 100 (19.0+) | Значения передаются в `spec:inputs` |
| Длина cron-строки | 255 символов | Стандартный cron |
| Timezone | Любая IANA timezone или ActiveSupport::TimeZone | Например: `Europe/Moscow`, `America/New_York`, `Pacific Time (US & Canada)` |
| Maximum scheduled pipeline frequency | Настраивается | По умолчанию раз в 10 мин (`3-59/10 * * * *`) |
| Scheduled Execution Policies на security policy проект | 1 policy с 1 schedule (GA 19.2) | Ограничение может быть расширено в будущих релизах |
| Веток в policy schedule | 5 | Включая default branch, если не указано явно |
| Минимальный time_window | 600 секунд (10 минут) | Для policies |
| Длина описания расписания | 255 символов | Ограничение API |

### Несовместимость и ограничения

| Ограничение | Описание | Решение |
| :--- | :--- | :--- |
| `workflow:rules` исключает schedule | Если `workflow:rules` не включает `schedule`, пайплайн не создастся | Добавьте `if: $CI_PIPELINE_SOURCE == "schedule"` в `workflow:rules` |
| `rules:changes` без коммитов | Если с последнего запуска нет новых коммитов, `changes` не сработает | Используйте `when: always` для scheduled пайплайнов |
| Protected branches | Scheduled пайплайн запускается на последний коммит ветки | Убедитесь, что целевая ветка существует и не удалена |
| `compare_to` в schedules | Переменные для `compare_to` должны быть определены в расписании | Передавайте `TARGET_BRANCH` как переменную расписания |
| Schedule Execution Policies + Free tier | Scheduled Execution Policies доступны только в Premium/Ultimate | Используйте обычные schedules в Free tier |
| Maximum frequency exceeded | Cron просит запуск чаще, чем `pipeline_schedule_worker_cron` | Увеличьте частоту воркера или измените cron |
| Ambiguous refs | Краткое имя `ref` может совпадать и с веткой, и с тегом | Используйте полные имена: `refs/heads/main` или `refs/tags/v1.0` |
| time_window < 600 сек | Для policies минимальное окно — 600 секунд | Увеличьте `time_window.value` |
| >5 branches в policy | В schedule можно указать максимум 5 веток | Ограничьте список или используйте default branch |

### Особые сценарии

**Scheduled пайплайн с `workflow:rules`:**
```yaml
# ОШИБКА: пайплайн не создается
workflow:
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# ПРАВИЛЬНО: включите schedule источник
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Запуск schedule при отсутствии новых коммитов:**
```yaml
# Scheduled пайплайн запускается даже если нет новых коммитов
# Но rules:changes может пропустить задачу
# Решение: добавьте fallback
test:
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: always
    - changes:
        paths: ["src/**/*"]
      when: on_success
    - when: never
```

## Дополнительная информация

- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — типы пайплайнов, включая Scheduled.
- **[Правила запуска задач](./job_rules.md)** — управление логикой включения задач.
- **[Продвинутые рабочие процессы](../gitlab_ci_advanced_workflow.md)** — архитектурные паттерны.
- **[API и Webhooks](../api_and_webhooks_automation.md)** — управление расписаниями через API.
- **[Compliance и Audit](../compliance_and_audit.md)** — Scheduled Execution Policies для compliance.
- **[Pipeline Schedules API](https://docs.gitlab.com/api/pipeline_schedules/)** — полное руководство по REST API.
- **[Scheduled Pipeline Execution Policies](https://docs.gitlab.com/user/application_security/policies/scheduled_pipeline_execution_policies/)** — конфигурация policies в `.gitlab/security-policies/policy.yml`.
- **[Cron syntax](https://docs.gitlab.com/topics/cron/)** — расширения fugit и ограничения GitLab.
- **[CI/CD limits](https://docs.gitlab.com/administration/cicd/limits/)** — лимиты расписаний и максимальная частота воркера.
- **[glab schedule commands](https://docs.gitlab.com/cli/schedule/)** — управление расписаниями из CLI.
- **[Официальная документация: Pipeline Schedules](https://docs.gitlab.com/ee/ci/pipelines/schedules.html)** — полное руководство.
