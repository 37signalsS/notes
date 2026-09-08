# Мониторинг и метрики GitLab CI/CD

## Определения

**Мониторинг CI/CD** — непрерывный процесс сбора, анализа и визуализации метрик пайплайнов, Runner'ов и инфраструктуры CI/CD для выявления деградации производительности, сбоев и узких мест.

**Ключевые метрики CI/CD** — количественные показатели, отражающие здоровье и эффективность конвейера: время выполнения, частота ошибок, использование ресурсов и бизнес-влияние.

**CI/CD Observability** — способность понимать внутреннее состояние системы CI/CD через внешние проявления (метрики, логи, трейсы) без прямого отладки каждого компонента.

## Теоретический блок

### Три уровня мониторинга CI/CD

| Уровень | Что мониторим | Инструменты | Зачем |
|:---|:---|:---|:---|
| **Инфраструктура** | CPU/RAM/Disk Runner'ов, доступность GitLab Server | Prometheus, node_exporter | Обнаружение аппаратных проблем |
| **Пайплайны** | Время выполнения, частота ошибок, очередь задач | GitLab API, Prometheus, Grafana | Оптимизация скорости CI/CD |
| **Бизнес-метрики** | Time to Deploy, Change Failure Rate, MTTR | DORA metrics, Grafana | Оценка эффективности команды |

### Встроенные метрики GitLab

GitLab предоставляет эндпоинт `/metrics` для Prometheus:

```
ci_pipeline_total                          — общее количество пайплайнов
ci_pipeline_status_total                   — пайплайны по статусам (success/failed/running)
ci_pipeline_duration_seconds               — время выполнения пайплайна
ci_job_status_total                        — задачи по статусам
ci_job_duration_seconds                    — время выполнения задачи
ci_job_queue_duration_seconds              — время ожидания задачи в очереди
ci_runner_builds_total                     — количество сборок на Runner
ci_runner_errors_total                     — ошибки Runner'ов
ci_pending_jobs_count                      — ожидающие задачи
ci_merge_requests_builds_total             — MR-пайплайны
```

### DORA Metrics (в контексте GitLab CI/CD)

| Метрика | Определение | Целевое значение | Как собирать |
|:---|:---|:---|:---|
| **Deployment Frequency** | Частота деплоя в продакшен | Daily+ | GitLab API: `pipelines?status=success&ref=main` |
| **Lead Time for Changes** | Время от коммита до деплоя | < 1 часа | `pipeline.created_at - commit.created_at` |
| **Change Failure Rate** | Доля неудачных деплоев | < 5% | `failed_deploys / total_deploys` |
| **Time to Restore Service** | Время восстановления после инцидента | < 1 часа | Разница между incident.created_at и resolve |
| **MTTR (Mean Time To Recovery)** | Среднее время восстановления | < 30 мин | Агрегация по инцидентам |

### Метрики Runner'ов

| Метрика | Описание | Порог алерта |
|:---|:---|:---|
| `gitlab_runner_active_jobs` | Активные задачи на Runner | > concurrent limit |
| `gitlab_runner_jobs_total` | Общее количество выполненных задач | Мониторинг тренда |
| `gitlab_runner_job_duration_seconds` | Время выполнения задачи | > 2x от baseline |
| `gitlab_runner_errors_total` | Ошибки выполнения | Рост > 10% в час |
| `gitlab_runner_request_duration_seconds` | Время ответа Runner API | > 5 сек |
| `gitlab_runner_disk_space_available_bytes` | Свободное место | < 10 ГБ |
| `gitlab_runner_docker_containers_total` | Контейнеры Docker | > concurrent limit |

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

### Сбор метрик GitLab через Prometheus

```yaml
# gitlab-ci.yml — экспорт метрик пайплайна
export_metrics:
  stage: .pre
  image: prom/prometheus:latest
  script:
    - |
      # Сбор метрик после завершения пайплайна
      cat > /tmp/pipeline_metrics.txt <<EOF
      # HELP ci_pipeline_duration_seconds Время выполнения пайплайна
      # TYPE ci_pipeline_duration_seconds gauge
      ci_pipeline_duration_seconds{project="$CI_PROJECT_NAME",branch="$CI_COMMIT_REF_SLUG"} $CI_PIPELINE_DURATION
      # HELP ci_pipeline_status Статус пайплайна
      # TYPE ci_pipeline_status gauge
      ci_pipeline_status{project="$CI_PROJECT_NAME",status="$CI_JOB_STATUS"} 1
      # HELP ci_pipeline_jobs_total Количество задач в пайплайне
      # TYPE ci_pipeline_jobs_total gauge
      ci_pipeline_jobs_total{project="$CI_PROJECT_NAME"} $(cat /tmp/job_count.txt)
      EOF
    - |
      # Отправка в Prometheus Pushgateway
      curl --data-binary @/tmp/pipeline_metrics.txt \
        http://prometheus:9091/metrics/job/gitlab_ci/instance/${CI_JOB_ID}
  rules:
    - when: always
```

### Настройка GitLab Prometheus в config.toml

```toml
# /etc/gitlab-runner/config.toml
concurrent = 10
check_interval = 3

[session_server]
  session_timeout = 1800

# Включение метрик Runner
metrics_server = ":9252"

[[runners]]
  name = "production-runner"
  executor = "docker"
  [runners.docker]
    image = "alpine:latest"
    privileged = false
    disable_cache = false
    volumes = ["/cache"]
    shm_size = 0
    # Лимиты ресурсов для мониторинга
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
            "expr": "sum(ci_pipeline_status_total{status='success'}) / sum(ci_pipeline_status_total) * 100",
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
            "expr": "histogram_quantile(0.95, sum(rate(ci_pipeline_duration_seconds_bucket[5m])) by (le))",
            "legendFormat": "p95"
          }
        ]
      },
      {
        "title": "Queue Wait Time",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(ci_job_queue_duration_seconds_bucket[5m])) by (le))",
            "legendFormat": "Queue p95"
          }
        ]
      },
      {
        "title": "Active Runners",
        "type": "stat",
        "targets": [
          {
            "expr": "gitlab_runner_active_jobs",
            "legendFormat": "{{ name }}"
          }
        ]
      }
    ]
  }
}
```

### Алерт规则 для Prometheus

```yaml
# prometheus/rules/gitlab_ci_alerts.yml
groups:
  - name: gitlab_ci
    rules:
      - alert: PipelineFailureRateHigh
        expr: |
          sum(rate(ci_pipeline_status_total{status="failed"}[1h])) /
          sum(rate(ci_pipeline_status_total[1h])) > 0.1
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "High pipeline failure rate"
          description: "Failure rate is {{ $value | humanizePercentage }} for the last hour"
          runbook_url: "https://wiki.internal/runbooks/ci-pipeline-failure"

      - alert: PipelineDurationHigh
        expr: |
          histogram_quantile(0.95, sum(rate(ci_pipeline_duration_seconds_bucket[5m])) by (le)) > 600
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Pipeline duration p95 > 10 minutes"
          description: "Current p95: {{ $value }}s"

      - alert: RunnersUnavailable
        expr: sum(gitlab_runner_active_jobs) == 0 and sum(ci_pending_jobs_count) > 5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "No active runners but jobs are pending"
          description: "{{ $value }} jobs waiting in queue"

      - alert: QueueWaitTimeHigh
        expr: |
          histogram_quantile(0.95, sum(rate(ci_job_queue_duration_seconds_bucket[5m])) by (le)) > 300
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Jobs waiting > 5 minutes in queue"
          description: "Queue wait p95: {{ $value }}s"
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

      # Получение пайплайнов за последние 7 дней
      week_ago = (datetime.now() - timedelta(days=7)).isoformat()
      url = f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/pipelines"
      params = {"since": week_ago, "per_page": 100, "status": "success"}
      pipelines = requests.get(url, headers=headers, params=params).json()

      # Расчет Deployment Frequency
      deploy_count = len([p for p in pipelines if p["ref"] == "main"])
      deployment_frequency = deploy_count / 7  # в день

      # Расчет Lead Time
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

## Дополнительная информация

### Связанные темы
- **[Отладка и устранение неполадок](./debugging_and_troubleshooting.md)** — диагностика проблем с пайплайнами
- **[Обзор Runner и Executor](./gitlab_ci_runners_executors.md)** — настройка и мониторинг Runner'ов
- **[API и Webhooks](./api_and_webhooks_automation.md)** — программный доступ к метрикам
- **[DORA Metrics](../../CI-CD/Core_Concepts/dora_metrics.md)** — подробный разбор метрик
- **[Наблюдаемость](../../Concepts/Observability_and_Monitoring/observability_definitions.md)** — общие концепции Observability
- **[Мониторинг методологии](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — RED, USE, Golden Signals

### Рекомендации
- Начинайте с 3 ключевых метрик: Success Rate, Duration, Queue Time
- Настройте алерты до создания дашбордов
- Используйте `runbook_url` в каждом алерте
- Регулярно пересматривайте пороги алертов (раз в квартал)
