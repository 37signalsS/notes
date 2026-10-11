# Мониторинг и метрики GitLab CI/CD

**Актуально для:** GitLab 19.x / GitLab Runner 19.x

## Определения

**Мониторинг CI/CD** — непрерывный процесс сбора, анализа и визуализации метрик пайплайнов, Runner'ов и инфраструктуры CI/CD для выявления деградации производительности, сбоев и узких мест.

**Ключевые метрики CI/CD** — количественные показатели, отражающие здоровье и эффективность конвейера: время выполнения, частота ошибок, использование ресурсов и бизнес-влияние.

**CI/CD Observability** — способность понимать внутреннее состояние системы CI/CD через внешние проявления (метрики, логи, трейсы) без прямого отладки каждого компонента.

## Основные концепции

### Архитектура сбора метрик GitLab CI/CD

Мониторинг GitLab CI/CD строится на трёх источниках данных:

1. **Нативные метрики GitLab Server** — экспортируются через `/-/metrics` эндпоинт (требуют включения в Admin Area → Settings → Metrics and profiling). Покрывают pipeline processing, queue, Sidekiq, Gitaly, PostgreSQL, Redis.
2. **Нативные метрики GitLab Runner** — экспортируются через встроенный HTTP-сервер на `:9252/metrics` (настраивается в `config.toml` через `metrics_server = ":9252"`). Покрывают бизнес-логику Runner'а, concurrency, API-запросы, autoscaling.
3. **Внешние экспортёры** — инструменты вида `gitlab-ci-pipelines-exporter` или кастомные Pushgateway-джобы, которые агрегируют данные через GitLab API и предоставляют дополнительные метрики с префиксом `gitlab_ci_`.

При проектировании системы различайте эти три источника: нативные метрики отражают состояние самого GitLab, а экспортёры — состояние пайплайнов с точки зрения API. Для алертинга приоритетны нативные метрики, так как они не зависят от доступности API.

### Три уровня мониторинга CI/CD

| Уровень | Что мониторим | Инструменты | Зачем |
|:---|:---|:---|:---|
| **Инфраструктура** | CPU/RAM/Disk Runner'ов, доступность GitLab Server | Prometheus, node_exporter | Обнаружение аппаратных проблем |
| **Пайплайны** | Время выполнения, частота ошибок, очередь задач | GitLab API, Prometheus, Grafana | Оптимизация скорости CI/CD |
| **Бизнес-метрики** | Time to Deploy, Change Failure Rate, MTTR | DORA metrics, Grafana | Оценка эффективности команды |

### Нативные метрики GitLab Server (19.x)

GitLab Server экспортирует метрики через `/-/metrics`. Ниже — актуальные для CI/CD метрики:

| Метрика | Тип | Labels | Описание |
|:---|:---|:---|:---|
| `pipelines_created_total` | Counter | `source`, `partition_id` | Счётчик созданных пайплайнов |
| `pipelines_finished_total` | Counter | `source`, `partition_id`, `status` | Счётчик завершённых пайплайнов (success/failed/canceled). Доступно с 19.2 |
| `gitlab_ci_pipeline_creation_duration_seconds` | Histogram | `gitlab` | Время создания пайплайна (wall-clock от push до появления в Scheduler) |
| `gitlab_ci_pipeline_time_to_finished_seconds` | Histogram | `source`, `status` | Wall-clock время от создания до finished-статуса. Доступно с 19.2 |
| `gitlab_ci_pipeline_size_builds` | Histogram | `source` | Количество задач в пайплайне |
| `gitlab_ci_pipeline_failure_reasons` | Counter | `reason` | Причины падения пайплайна. См. [CI/CD failure reason metrics](https://docs.gitlab.com/administration/monitoring/prometheus/gitlab_metrics/#cicd-failure-reason-metrics) |
| `gitlab_ci_active_jobs` | Histogram | `plan` | Активные задачи на момент создания пайплайна |
| `gitlab_ci_current_queue_size` | Gauge | — | Текущий размер инициализированной очереди CI/CD. Доступно с 16.3, флаг `gitlab_ci_builds_queuing_metrics` |
| `gitlab_ci_queue_depth_total` | Histogram | — | Глубина очереди CI/CD в зависимости от результата операции. Доступно с 16.3, флаг `gitlab_ci_builds_queuing_metrics` |
| `gitlab_ci_queue_iteration_duration_seconds` | Histogram | — | Время поиска задачи в очереди. Доступно с 16.3, флаг `gitlab_ci_builds_queuing_metrics` |
| `gitlab_ci_job_failure_reasons` | Counter | `reason`, `runner_type` | Причины падения задач. `runner_type` добавлен в 19.3 |
| `gitlab_ci_runner_authentication_failure_total` | Counter | — | Сбои аутентификации Runner'ов |
| `gitlab_ci_runner_authentication_success_total` | Counter | `type` | Успешные аутентификации Runner'ов |

> **Примечание:** Метрики очереди (`gitlab_ci_queue_*`) требуют включения feature flag `gitlab_ci_builds_queuing_metrics` на инстансе. Без флага метрики не экспортируются.

### Метрики Runner'ов (19.x)

Runner экспортирует метрики через встроенный HTTP-сервер на `:9252/metrics`:

| Метрика | Тип | Labels | Описание |
|:---|:---|:---|:---|
| `gitlab_runner_concurrent` | Gauge | `runner_name` | Текущее значение `concurrent` из `config.toml` |
| `gitlab_runner_jobs_running_total` | Gauge | `runner_name` | Текущее количество выполняющихся задач |
| `gitlab_runner_errors_total` | Counter | — | Количество пойманных ошибок Runner'а |
| `gitlab_runner_api_request_attempts_total` | Counter | `runner_name`, `system_id`, `endpoint`, `status`, `method` | HTTP-запросы к GitLab API, включая ретраи |
| `gitlab_runner_api_request_statuses_total` | Counter | `runner_name`, `system_id`, `endpoint`, `status`, `method` | HTTP-запросы к GitLab API по статусам |
| `gitlab_runner_request_concurrency` | Gauge | `runner_name` | Текущее количество concurrent-запросов за новыми задачами |
| `gitlab_runner_request_concurrency_exceeded_total` | Counter | `runner_name` | Запросы, превысившие лимит `request_concurrency` |
| `gitlab_runner_version_info` | Gauge | `version`, `revision` | Версия Runner'а |

### Метрики инфраструктуры Runner'ов

Свободное место на диске Runner'ов отслеживается через **node_exporter**, а не через метрики Runner'а:

| Метрика (node_exporter) | Описание | Порог алерта |
|:---|:---|:---|
| `node_filesystem_avail_bytes{mountpoint="/builds"}` | Свободное место на разделе с кэшем/артефактами | < 10 ГБ |
| `node_memory_MemAvailable_bytes` | Доступная оперативная память | < 2 ГБ |
| `node_cpu_seconds_total` | CPU time по режимам | saturation > 85% за 5m |
| `node_disk_io_time_weighted_seconds_total` | Время дисковой подсистемы | > 2x baseline |

> **Важно:** Не путайте метрики Runner'а (`gitlab_runner_*`) с метриками хоста (`node_*`). Runner знает только о собственных задачах и API-запросах; состояние диска, памяти и CPU видно только через node_exporter.

### DORA Metrics (в контексте GitLab CI/CD)

Подробные определения, формулы и целевые значения DORA-метрик описаны в **[Метрики DORA](../../Core_Concepts/dora_metrics.md)**. Ниже — краткая шпаргалка по сбору через GitLab API:

| Метрика | Определение | Целевое значение (Elite 2025–2026) | Как собирать |
|:---|:---|:---|:---|
| **Deployment Frequency** | Частота деплоя в продакшен | > 1/день | GitLab API: `pipelines?status=success&ref=main&per_page=100` |
| **Lead Time for Changes** | Время от коммита до деплоя | < 1 дня | `pipeline.finished_at - commit.created_at` |
| **Change Failure Rate** | Доля неудачных деплоев | < 4% | `failed_deploys / total_deploys` |
| **Failed Deployment Recovery Time** | Время восстановления после инцидента, вызванного деплоем | < 1 часа | Разница между incident.created_at и resolve |
| **Deployment Rework Rate** | Незапланированные исправления после деплоя | < 5% | `rework_deploys / total_deploys` |

### Алертинг для CI/CD

**Критичные алерты (pages on-call):**
- Пайплайны для main ветки падают > 30 минут
- Все Runner'ы недоступны
- Очередь задач превышает лимит > 1 часа
- Время выполнения пайплайна выросло > 2x от baseline

**Предупреждения (slack/email):**
- Доля ошибок пайплайнов выросла > 10%
- Среднее время выполнения задач выросло > 50%
- Свободное место на Runner < 20 ГБ
- Кэш не восстанавливается > 3 дней подряд

## Практический блок

### Предварительные требования

**Аппаратные требования:**
- GitLab Server: 4 CPU, 8 ГБ RAM, 50 ГБ SSD (минимум для-small team)
- Runner: 2 CPU, 4 ГБ RAM, 20 ГБ SSD на инстанс
- Сеть: latency между GitLab Server и Runner'ами < 50 ms

**Программные требования:**
- GitLab 19.x (CE или EE)
- GitLab Runner 19.x
- Prometheus 2.40+
- Grafana 10+ (опционально, для дашбордов)

**Инициализация:**
1. Включите GitLab Prometheus metrics: Admin Area → Settings → Metrics and profiling → Enable GitLab Prometheus metrics endpoint.
2. Включите feature flag `gitlab_ci_builds_queuing_metrics` для метрик очереди: `Feature.enable(:ci_observe_pipelines_finished)` в Rails console или через API.
3. Настройте `metrics_server = ":9252"` в `/etc/gitlab-runner/config.toml` и перезапустите Runner.
4. Добавьте scrape-задачи в Prometheus:
   - `job: 'gitlab'` → `https://gitlab.example.com/-/metrics` (с basic auth или IP allowlist)
   - `job: 'gitlab-runner'` → `runner1.example.com:9252/metrics`
   - `job: 'node'` → `runner1.example.com:9100/metrics` (node_exporter)

### Сбор метрик GitLab через Prometheus

```yaml
# gitlab-ci.yml — пример отправки кастомных метрик пайплайна в Pushgateway
export_metrics:
  stage: .post
  image: python:3.11-slim
  script:
    - |
      python3 << 'PYTHON'
      import requests
      import os

      CI_PIPELINE_DURATION = os.getenv("CI_PIPELINE_DURATION") or "0"
      CI_JOB_STATUS = os.getenv("CI_JOB_STATUS") or "unknown"
      CI_PROJECT_NAME = os.getenv("CI_PROJECT_NAME") or "unknown"
      CI_COMMIT_REF_SLUG = os.getenv("CI_COMMIT_REF_SLUG") or "unknown"
      CI_JOB_ID = os.getenv("CI_JOB_ID") or "0"

      metrics = f"""# HELP gitlab_ci_pipeline_duration_seconds Время выполнения пайплайна
# TYPE gitlab_ci_pipeline_duration_seconds gauge
gitlab_ci_pipeline_duration_seconds{{project="{CI_PROJECT_NAME}",branch="{CI_COMMIT_REF_SLUG}"}} {CI_PIPELINE_DURATION}
# HELP gitlab_ci_pipeline_status Статус пайплайна
# TYPE gitlab_ci_pipeline_status gauge
gitlab_ci_pipeline_status{{project="{CI_PROJECT_NAME}",status="{CI_JOB_STATUS}"}} 1
"""

      requests.post(
          "http://prometheus:9091/metrics/job/gitlab_ci/instance/{}".format(CI_JOB_ID),
          data=metrics,
          headers={"Content-Type": "text/plain"}
      )
      PYTHON
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: never
    - when: always
```

**Валидация:**
```bash
# Проверка доступности эндпоинта GitLab Server
curl -sk -H "Authorization: Bearer $TOKEN" "https://gitlab.example.com/-/metrics" | grep pipelines_created_total

# Проверка метрик Runner'а
curl -s "http://runner1.example.com:9252/metrics" | grep gitlab_runner_jobs_running_total

# Проверка метрик очереди (требует feature flag)
curl -sk -H "Authorization: Bearer $TOKEN" "https://gitlab.example.com/-/metrics" | grep gitlab_ci_current_queue_size
```

### Настройка GitLab Runner в config.toml

```toml
# /etc/gitlab-runner/config.toml
concurrent = 10
check_interval = 3

[session_server]
  session_timeout = 1800

# Включение метрик Runner
metrics_server = ":9252"

# Опционально: referees для внешнего Prometheus (сбор метрик во время джобы)
# [runner.referees]
#   [runner.referees.metrics]
#     prometheus_address = "http://prometheus.example.com:9090"
#     query_interval = "30s"
#     metric_queries = [
#       { query = 'rate(node_cpu_seconds_total[5m])', label = "cpu_usage" },
#       { query = 'node_memory_MemAvailable_bytes', label = "mem_available" }
#     ]

[[runners]]
  name = "production-runner"
  executor = "docker"
  [runners.docker]
    image = "alpine:latest"
    privileged = false
    disable_cache = false
    volumes = ["/cache"]
    shm_size = 0
    memory = "4g"
    cpus = "2"
  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      ServerAddress = "minio.internal:9000"
      BucketName = "runner-cache"
      Insecure = false
```

### Дашборд Grafana для CI/CD

```json
{
  "dashboard": {
    "title": "GitLab CI/CD Overview",
    "panels": [
      {
        "title": "Pipeline Success Rate",
        "type": "stat",
        "targets": [
          {
            "expr": "sum(pipelines_finished_total{status=\"success\"}) / sum(pipelines_finished_total) * 100",
            "legendFormat": "Success Rate %"
          }
        ],
        "thresholds": {
          "steps": [
            { "value": 95, "color": "green" },
            { "value": 80, "color": "yellow" },
            { "value": 0, "color": "red" }
          ]
        }
      },
      {
        "title": "Pipeline Duration (p95)",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(gitlab_ci_pipeline_time_to_finished_seconds_bucket[5m])) by (le))",
            "legendFormat": "p95"
          }
        ]
      },
      {
        "title": "Queue Wait Time (p95)",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(gitlab_ci_queue_iteration_duration_seconds_bucket[5m])) by (le))",
            "legendFormat": "Queue p95"
          }
        ]
      },
      {
        "title": "Active Runners",
        "type": "stat",
        "targets": [
          {
            "expr": "sum(gitlab_runner_jobs_running_total) by (runner_name)",
            "legendFormat": "{{ runner_name }}"
          }
        ]
      },
      {
        "title": "Queue Depth",
        "type": "stat",
        "targets": [
          {
            "expr": "sum(gitlab_ci_queue_depth_total) by (le)",
            "legendFormat": "Queue {{ le }}"
          }
        ]
      }
    ]
  }
}
```

### Алерт-правила для Prometheus

```yaml
# prometheus/rules/gitlab_ci_alerts.yml
groups:
  - name: gitlab_ci
    rules:
      - alert: PipelineFailureRateHigh
        expr: |
          sum(rate(pipelines_finished_total{status="failed"}[1h])) /
          sum(rate(pipelines_finished_total[1h])) > 0.1
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "High pipeline failure rate"
          description: "Failure rate is {{ $value | humanizePercentage }} for the last hour"
          runbook_url: "https://wiki.internal/runbooks/ci-pipeline-failure"

      - alert: PipelineDurationHigh
        expr: |
          histogram_quantile(0.95, sum(rate(gitlab_ci_pipeline_time_to_finished_seconds_bucket[5m])) by (le)) > 600
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Pipeline duration p95 > 10 minutes"
          description: "Current p95: {{ $value }}s"

      - alert: RunnersUnavailable
        expr: sum(gitlab_runner_jobs_running_total) == 0 and sum(gitlab_ci_current_queue_size) > 5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "No active runners but jobs are pending"
          description: "{{ $value }} jobs waiting in queue"

      - alert: QueueWaitTimeHigh
        expr: |
          histogram_quantile(0.95, sum(rate(gitlab_ci_queue_iteration_duration_seconds_bucket[5m])) by (le)) > 300
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Jobs waiting > 5 minutes in queue"
          description: "Queue wait p95: {{ $value }}s"

      - alert: RunnerErrorsIncreasing
        expr: |
          sum(rate(gitlab_runner_errors_total[1h])) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Runner errors rate > 0.1/s"
          description: "Runner {{ $labels.runner_name }} is experiencing errors"

      - alert: RunnerDiskSpaceLow
        expr: |
          node_filesystem_avail_bytes{mountpoint="/builds"} < 10737418240
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Runner disk space < 10GB"
          description: "Runner {{ $labels.instance }} has {{ $value | humanize1024 }} free"
```

### Автоматический сбор DORA метрик

```yaml
dora_metrics:
  stage: .post
  image: python:3.11-slim
  script:
    - |
      python3 << 'PYTHON'
      import requests
      import json
      from datetime import datetime, timedelta

      GITLAB_URL = "$CI_SERVER_URL"
      TOKEN = "$DORA_METRICS_TOKEN"
      PROJECT_ID = "$CI_PROJECT_ID"

      headers = {"PRIVATE-TOKEN": TOKEN}

      week_ago = (datetime.now() - timedelta(days=7)).isoformat()
      url = f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines"
      params = {"since": week_ago, "per_page": 100, "status": "success"}
      pipelines = requests.get(url, headers=headers, params=params).json()

      deploy_count = len([p for p in pipelines if p["ref"] == "main"])
      deployment_frequency = deploy_count / 7

      lead_times = []
      for p in pipelines:
          created = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
          finished = datetime.fromisoformat(p["finished_at"].replace("Z", "+00:00"))
          lead_times.append((finished - created).total_seconds() / 3600)

      avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else 0

      metrics = {
          "deployment_frequency_per_day": deployment_frequency,
          "lead_time_hours": avg_lead_time,
          "total_deploys": deploy_count,
          "period": "7d"
      }

      print(json.dumps(metrics, indent=2))
      PYTHON
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

**Валидация:**
```bash
# Проверка сбора DORA метрик
python3 dora_collector.py
# → {
#   "deployment_frequency_per_day": 2.14,
#   "lead_time_hours": 4.2,
#   "total_deploys": 15,
#   "period": "7d"
# }
```

## Устранение неполадок

### Типичные ошибки

| Симптом | Возможная причина | Диагностика | Решение |
|:---|:---|:---|:---|
| Метрики очереди отсутствуют в Prometheus | Feature flag `gitlab_ci_builds_queuing_metrics` выключен | `curl /-/metrics | grep gitlab_ci_queue` | Включите флаг в Rails console: `Feature.enable(:ci_observe_pipelines_finished)` |
| `pipelines_finished_total` не появляется | GitLab версии < 19.2 | `curl /-/metrics | grep pipelines_finished_total` | Используйте `gitlab_ci_pipeline_time_to_finished_seconds` (требует флаг) или считайте из API |
| Runner метрики не собираются | `metrics_server` не настроен или порт закрыт | `curl runner:9252/metrics | grep gitlab_runner` | Добавьте `metrics_server = ":9252"` в `config.toml` и перезапустите Runner |
| `node_filesystem_*` метрики отсутствуют | node_exporter не установлен на Runner хосте | `curl runner:9100/metrics | grep node_filesystem` | Установите node_exporter на хост Runner'а |
| Дашборд показывает `no data` | Labels не совпадают между metric и query | Prometheus → Graph → проверить labels | Сравните labels метрики и expressions в Grafana |
| Алерт срабатывает на все пайплайны | Нет фильтра по `source` или `ref` | Выражение алерта | Добавьте `{source="push", ref="main"}` в PromQL |

### Диагностические команды

```bash
# 1. Проверка доступности метрик GitLab Server
curl -sk -H "Authorization: Bearer $TOKEN" "https://gitlab.example.com/-/metrics" | \
  grep -E "pipelines_created_total|gitlab_ci_pipeline_time_to_finished_seconds|gitlab_ci_queue_depth_total"

# 2. Проверка метрик Runner'а
curl -s "http://runner1.example.com:9252/metrics" | \
  grep -E "gitlab_runner_jobs_running_total|gitlab_runner_concurrent|gitlab_runner_errors_total"

# 3. Проверка метрик хоста Runner'а
curl -s "http://runner1.example.com:9100/metrics" | \
  grep -E "node_filesystem_avail_bytes|node_cpu_seconds_total|node_memory_MemAvailable_bytes"

# 4. Проверка feature flags
gitlab-rake gitlab:feature_flags:list | grep builds_queuing
# → gitlab_ci_builds_queuing_metrics | enabled | false

# 5. Включение feature flag (требует Rails console на GitLab Server)
gitlab-rails console
> Feature.enable(:ci_observe_pipelines_finished)
> Feature.enable(:gitlab_ci_builds_queuing_metrics)

# 6. Проверка срабатывания алертов
promtool query instant prometheus:9090 \
  'ALERTS{alertname="PipelineDurationHigh", alertstate="firing"}'
```

## Рекомендации

**При проектировании мониторинга:**
- Начинайте с 3 ключевых метрик: `pipelines_finished_total` (Success Rate), `gitlab_ci_pipeline_time_to_finished_seconds` (Duration), `gitlab_ci_queue_iteration_duration_seconds` (Queue Time).
- Настройте алерты до создания дашбордов. Алерт без runbook_url — технический долг.
- Используйте `gitlab_ci_pipeline_failure_reasons` вместо generic "pipeline failed" — `reason` label точно указывает причину (`config_error`, `runner_system_failure`, `script_failure`).
- Регулярно пересматривайте пороги алертов (раз в квартал) вместе с ростом нагрузки.

**При настройке Runner'ов:**
- Выставляйте `concurrent` на 20-30% ниже, чем суммарное количество слотов всех Runner'ов. Это предотвращает перегрузку Sidekiq.
- Настройте `request_concurrency` в `config.toml` для ограничения одновременных API-запросов к GitLab (по умолчанию 1).
- Мониторьте `gitlab_runner_request_concurrency_exceeded_total` — рост этого metrics означает, что Runner не успевает обрабатывать API-ответы.
- Используйте `node_exporter` на хосте Runner'а; `gitlab_runner_disk_space_available_bytes` не существует — метрика диска берётся из `node_filesystem_*`.

**При сборе DORA метрик:**
- Определите, что считается "деплоем", до начала сбора. Зафиксируйте определение в runbook.
- Исключайте Renovate-коммиты из `Deployment Frequency`, если они искажают метрику.
- Для `Lead Time for Changes` используйте `pipeline.finished_at - commit.created_at`, а не `pipeline.created_at`, чтобы учитывать время создания пайплайна.

## Дополнительная информация

### Связанные темы
- **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)** — SLI/SLO, трейсы, Golden Signals, архитектура сбора данных
- **[Метрики DORA](../../Core_Concepts/dora_metrics.md)** — определения, формулы, целевые значения DORA
- **[Отладка и устранение неполадок](./debugging_and_troubleshooting.md)** — диагностика проблем с пайплайнами
- **[Обзор Runner и Executor](./gitlab_ci_runners_executors.md)** — настройка и мониторинг Runner'ов
- **[API и Webhooks](./api_and_webhooks_automation.md)** — программный доступ к метрикам
- **[Мониторинг методологии](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — RED, USE, Golden Signals

### Ограничения и edge cases

1. **Feature flags:** Метрики очереди (`gitlab_ci_queue_*`) и `pipelines_finished_total` требуют включения feature flags. На GitLab.com они могут быть включены по умолчанию, на self-managed — нет.
2. **Cardinality:** Метрики с labels `project`, `ref`, `branch` имеют высокую кардинальность. При >10k projects в инстансе Prometheus TSDB может испытывать pressure. Используйте recording rules и агрегацию.
3. **Sparse status metrics:** `gitlab_ci_pipeline_status` (из внешних экспортёров) по умолчанию экспортирует только последний статус. Для исторических данных используйте `pipelines_finished_total` или внешний экспортёр с `output_sparse_status_metrics: false`.
4. **Runner autoscaling:** При использовании autoscaling (Docker Machine, Kubernetes) метрики `gitlab_runner_*` отражают только активные экземпляры, а не общий пул.
5. **Sidekiq metrics:** Метрики pipeline processing дублируются на Sidekiq и Rails endpoints. Дашборды должны суммировать значения из всех эндпоинтов.
