# Наблюдаемость пайплайнов GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

*   **CI/CD Observability** — способность понимать внутреннее состояние пайплайнов через метрики, логи и трейсы без прямого отладки каждого запуска.
*   **Pipeline Success Rate** — процент успешных пайплайнов за период. Target: ≥ 95%.
*   **Pipeline Duration (p95)** — 95-й перцентиль времени выполнения пайплайна. Target: < 15 мин.
*   **Queue Wait Time** — время ожидания свободного раннера. Target: < 2 мин.
*   **Flaky Test Rate** — доля нестабильных тестов. Target: < 1%.
*   **OpenTelemetry (OTel)** — открытый стандарт для сбора трейсов, метрик и логов. GitLab поддерживает OTLP экспорт.
*   **Pushgateway** — сервис для временного хранения метрик от короткоживущих задач CI/CD.
*   **Prometheus** — система мониторинга и алертинга, собирающая метрики GitLab Server и Runner'ов.
*   **Grafana** — визуализация метрик в дашбордах.

> **Примечание:** DORA Metrics, Golden Signals и общие принципы наблюдаемости описаны в **[Метрики DORA](../../Core_Concepts/dora_metrics.md)** и **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)**. Ниже — GitLab-specific метрики, конфигурация и практические сценарии.

## Предварительные требования

**Аппаратные требования:**
*   GitLab Server: 4 CPU, 8 ГБ RAM, 50 ГБ SSD (минимум для small team)
*   Runner: 2 CPU, 4 ГБ RAM, 20 ГБ SSD на инстанс
*   Сеть: latency между GitLab Server и Runner'ами < 50 ms

**Программные требования:**
*   GitLab 17.x+ (CE достаточно для базовой наблюдаемости; Premium/Ultimate для Pipeline Execution Policies, advanced analytics)
*   GitLab Runner 17.x+
*   Prometheus 2.40+ (для сбора нативных метрик)
*   Grafana 10+ (опционально, для дашбордов)
*   node_exporter на хостах Runner'ов (для метрик диска/памяти)

**Инициализация:**
1.  Включите GitLab Prometheus metrics: Admin Area → Settings → Metrics and profiling → Enable GitLab Prometheus metrics endpoint.
2.  Включите feature flag `gitlab_ci_builds_queuing_metrics` для метрик очереди: `Feature.enable(:ci_observe_pipelines_finished)` в Rails console или через API.
3.  Настройте `metrics_server = ":9252"` в `/etc/gitlab-runner/config.toml` и перезапустите Runner.
4.  Добавьте scrape-задачи в Prometheus:
    *   `job: 'gitlab'` → `https://gitlab.example.com/-/metrics` (с basic auth или IP allowlist)
    *   `job: 'gitlab-runner'` → `runner1.example.com:9252/metrics`
    *   `job: 'node'` → `runner1.example.com:9100/metrics` (node_exporter)

## Базовые концепции

### Архитектура сбора метрик GitLab CI/CD

Мониторинг GitLab CI/CD строится на трёх источниках данных:

1.  **Нативные метрики GitLab Server** — экспортируются через `/-/metrics` эндпоинт (требуют включения в Admin Area → Settings → Metrics and profiling). Покрывают pipeline processing, queue, Sidekiq, Gitaly, PostgreSQL, Redis.
2.  **Нативные метрики GitLab Runner** — экспортируются через встроенный HTTP-сервер на `:9252/metrics` (настраивается в `config.toml` через `metrics_server = ":9252"`). Покрывают бизнес-логику Runner'а, concurrency, API-запросы, autoscaling.
3.  **Внешние экспортёры** — инструменты вида `gitlab-ci-pipelines-exporter` или кастомные Pushgateway-джобы, которые агрегируют данные через GitLab API и предоставляют дополнительные метрики с префиксом `gitlab_ci_`.

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

> **Важно:** Не путайте метрики Runner'а (`gitlab_runner_*`) с метриками хоста (`node_*`). Runner знает только о собственных задачах и API-запросах; состояние диска, памяти и CPU видно только через node_exporter.

### DORA Metrics в контексте GitLab CI/CD

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
*   Пайплайны для main ветки падают > 30 минут
*   Все Runner'ы недоступны
*   Очередь задач превышает лимит > 1 часа
*   Время выполнения пайплайна выросло > 2x от baseline

**Предупреждения (slack/email):**
*   Доля ошибок пайплайнов выросла > 10%
*   Среднее время выполнения задач выросло > 50%
*   Свободное место на Runner < 20 ГБ
*   Кэш не восстанавливается > 3 дней подряд

## Практические сценарии

### Сценарий 1: Включение метрик в GitLab Server

```bash
# В /etc/gitlab/gitlab.rb
gitlab_rails['prometheus_metrics_enabled'] = true
gitlab_rails['prometheus_metrics_method'] = :thread
prometheus['listen_address'] = 'localhost:9090'

# Применение
sudo gitlab-ctl reconfigure

# Проверка
curl -s http://localhost:9090/-/metrics | grep gitlab_ci
```

**Ожидаемый результат:**
```
# HELP gitlab_ci_pipeline_creation_duration_seconds ...
# TYPE gitlab_ci_pipeline_creation_duration_seconds histogram
gitlab_ci_pipeline_creation_duration_seconds_bucket{le="0.1"} 1234
...
```

### Сценарий 2: Включение метрик в Runner

```toml
# /etc/gitlab-runner/config.toml
[[runners]]
  name = "docker-runner"
  url = "https://gitlab.example.com/"
  token = "TOKEN"
  executor = "docker"
  
  [runners.metrics]
    enabled = true
    address = ":9252"
    profile_time = 5s
```

```bash
# Проверка метрик Runner'а
curl -s http://runner-host:9252/metrics | grep gitlab_runner
```

**Ожидаемый результат:**
```
# HELP gitlab_runner_jobs_running_total ...
# TYPE gitlab_runner_jobs_running_total gauge
gitlab_runner_jobs_running_total{runner_name="docker-runner"} 3
```

### Сценарий 3: Дашборд Grafana для CI/CD

```json
{
  "dashboard": {
    "title": "GitLab CI/CD Pipeline Metrics",
    "panels": [
      {
        "title": "Pipeline Success Rate",
        "targets": [
          {
            "expr": "sum(rate(gitlab_ci_pipeline_time_to_finished_seconds_total{status=\"success\"}[1h])) / sum(rate(gitlab_ci_pipeline_time_to_finished_seconds_total[1h])) * 100"
          }
        ],
        "thresholds": [
          {"color": "red", "value": 0, "op": "lt"},
          {"color": "yellow", "value": 95, "op": "lt"},
          {"color": "green", "value": 99, "op": "gte"}
        ]
      },
      {
        "title": "Pipeline Duration (p95)",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(gitlab_ci_pipeline_time_to_finished_seconds_bucket[1h])) by (le))"
          }
        ],
        "unit": "s"
      },
      {
        "title": "Queue Wait Time",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(gitlab_ci_queue_iteration_duration_seconds_bucket[1h])) by (le))"
          }
        ],
        "unit": "s"
      },
      {
        "title": "Runner Saturation",
        "targets": [
          {
            "expr": "sum(gitlab_runner_jobs_running_total) / sum(gitlab_runner_concurrent) * 100"
          }
        ],
        "thresholds": [
          {"color": "green", "value": 0, "op": "lt"},
          {"color": "yellow", "value": 70, "op": "lt"},
          {"color": "red", "value": 90, "op": "gte"}
        ]
      },
      {
        "title": "Pipeline Failures by Reason",
        "targets": [
          {
            "expr": "sum(rate(gitlab_ci_pipeline_failure_reasons[1h])) by (reason)"
          }
        ]
      }
    ]
  }
}
```

### Сценарий 4: Отправка метрик из пайплайна через Pushgateway

```yaml
stages:
  - build
  - test
  - deploy

build:
  stage: build
  script:
    - echo "Building..."
  after_script:
    - |
      echo "gitlab_ci_job_duration_seconds{job=\"$CI_JOB_NAME\",project=\"$CI_PROJECT_NAME\"} $CI_JOB_DURATION" | \
      curl --data-binary @- http://pushgateway:9091/metrics/job/gitlab_ci

test:
  stage: test
  script:
    - pytest -v
  after_script:
    - |
      TEST_RESULT=$([ $? -eq 0 ] && echo 1 || echo 0)
      echo "gitlab_ci_test_result{job=\"$CI_JOB_NAME\",project=\"$CI_PROJECT_NAME\"} $TEST_RESULT" | \
      curl --data-binary @- http://pushgateway:9091/metrics/job/gitlab_ci
```

### Сценарий 5: OpenTelemetry интеграция

```yaml
# Включение OpenTelemetry в GitLab Server
# /etc/gitlab/gitlab.rb
gitlab_rails['opentelemetry_enabled'] = true
gitlab_rails['opentelemetry_url'] = 'http://otel-collector:4317'
gitlab_rails['opentelemetry_excluded_endpoints'] = '/health_check'

# В пайплайне
test_with_otel:
  stage: test
  image: node:20
  script:
    - export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
    - export OTEL_RESOURCE_ATTRIBUTES=ci.pipeline.id=$CI_PIPELINE_ID,ci.job.id=$CI_JOB_ID
    - npm test
```

### Сценарий 6: Алертинг на метрики

```yaml
# prometheus/rules/gitlab-ci.yml
groups:
  - name: gitlab_ci
    rules:
      - alert: HighPipelineFailureRate
        expr: sum(rate(gitlab_ci_pipeline_time_to_finished_seconds_total{status="failed"}[1h])) / sum(rate(gitlab_ci_pipeline_time_to_finished_seconds_total[1h])) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High pipeline failure rate"
          description: "Pipeline failure rate is {{ $value | humanizePercentage }}"

      - alert: HighQueueWaitTime
        expr: histogram_quantile(0.95, sum(rate(gitlab_ci_queue_iteration_duration_seconds_bucket[1h])) by (le)) > 120
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High queue wait time"
          description: "Queue wait time p95 is {{ $value }}s"

      - alert: RunnerSaturation
        expr: sum(gitlab_runner_jobs_running_total) / sum(gitlab_runner_concurrent) > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Runner saturation"
          description: "Runner saturation is {{ $value | humanizePercentage }}"
```

## Валидация

### Проверка включения метрик

```bash
# 1. Проверка доступности метрик GitLab Server
curl -sk -H "Authorization: Bearer $TOKEN" "https://gitlab.example.com/-/metrics" | \
  grep -E "pipelines_created_total|gitlab_ci_pipeline_time_to_finished_seconds|gitlab_ci_queue_depth_total"
# → должны присутствовать все три метрики

# 2. Проверка метрик Runner'а
curl -s "http://runner1.example.com:9252/metrics" | \
  grep -E "gitlab_runner_jobs_running_total|gitlab_runner_concurrent|gitlab_runner_errors_total"
# → gitlab_runner_jobs_running_total{runner_name="..."} 0

# 3. Проверка метрик хоста Runner'а
curl -s "http://runner1.example.com:9100/metrics" | \
  grep -E "node_filesystem_avail_bytes|node_cpu_seconds_total|node_memory_MemAvailable_bytes"
# → node_filesystem_avail_bytes{mountpoint="/builds"} 1.073741824e+10
```

### Проверка feature flags

```bash
# Список флагов очереди
gitlab-rake gitlab:feature_flags:list | grep builds_queuing
# → gitlab_ci_builds_queuing_metrics | enabled | false

# Включение флага (требует Rails console на GitLab Server)
gitlab-rails console
> Feature.enable(:ci_observe_pipelines_finished)
> Feature.enable(:gitlab_ci_builds_queuing_metrics)
```

### Проверка срабатывания алертов

```bash
# Проверка активных алертов в Prometheus
promtool query instant prometheus:9090 \
  'ALERTS{alertname="PipelineDurationHigh", alertstate="firing"}'
# → пустой результат, если алертов нет
```

## Лучшие практики

### Безопасность

1.  **Не экспортируйте секреты**: Метрики не должны содержать敏感数据.
2.  **Ограничьте доступ к Pushgateway**: Только для authorized job'ов.
3.  **Аудит метрик**: Логируйте доступ к метрикам.

### Организация

1.  **DORA-метрики**: Включите `deployment_tier` для окружений.
2.  **Feature flags**: Используйте для включения метрик только для нужных проектов.
3.  **Стандартизируйте labels**: Единые имена метрик и labels across команды.

### Производительность

1.  **Кэшируйте метрики**: Используйте Prometheus remote write для долгосрочного хранения.
2.  **Алерты на SLO**: Привяжите алерты к SLO, а не к произвольным порогам.
3.  **Мониторьте Queue Time**: Если > 2 мин — добавьте раннеры.

### SRE/SysAdmin

1.  **Change Management**: Включение feature flags и изменение порогов алертов проводите по change window.
2.  **Blast Radius**: Ограничьте количество concurrent jobs при отладке метрик, чтобы не перегрузить GitLab Server.
3.  **Мониторинг инфраструктуры**: Отслеживайте CPU/RAM/диск на GitLab Server и Runner'ах через node_exporter.
4.  **Resource Quotas**: Настройте лимиты на namespace/project (concurrent jobs, artifacts size).
5.  **Runner Pools**: Разделите Runner'ы по executor'ам и тегам для изоляции workloads.
6.  **DR процедуры**: Бэкап `gitlab.rb` и `config.toml`; ability to revert feature flags.

## Особенности и ограничения (Edge Cases)

### Лимиты

| Параметр | Лимит | Примечание |
|:---|:---|:---|
| Метрики очереди | Требуют feature flag | `gitlab_ci_builds_queuing_metrics` |
| Логи пайплайна | ~4-10 MB | При превышении обрезаются |
| Артефакты | 100 MB по умолчанию | Настраивается в Settings |
| Pushgateway retention | 1 час | По умолчанию |
| Размер YAML | 2 MB | `max_yaml_size_bytes` |

### Несовместимость

| Конфликт | Описание | Решение |
|:---|:---|:---|
| Метрики очереди не экспортируются | Feature flag отключен | Включите `gitlab_ci_builds_queuing_metrics` |
| Отсутствие `deployment_tier` | DORA-метрики не считаются | Добавьте `deployment_tier: production` |
| Pushgateway переполнен | Много короткоживущих задач | Настройте retention и cleanup |
| Runner метрики не собираются | `metrics_server` не настроен | Добавьте `metrics_server = ":9252"` в `config.toml` |
| `node_filesystem_*` метрики отсутствуют | node_exporter не установлен | Установите node_exporter на хост Runner'а |

### Известные ограничения

*   **Feature flags**: Метрики очереди требуют явного включения флага; в GitLab 20.x они могут стать доступны по умолчанию.
*   **Cardinality**: Высокая кардинальность метрик (например, `trace_id` как label) приводит к memory pressure на TSDB Prometheus.
*   **Pushgateway**: Не подходит для долгоживущих метрик; retention по умолчанию 1 час.
*   **OTel интеграция**: GitLab Server отправляет трейсы только для собственных операций, не для пользовательских скриптов в пайплайнах.

## Типичные ошибки и диагностика (Troubleshooting)

| Симптом | Причина | Диагностика | Решение |
|:---|:---|:---|:---|
| Метрики очереди отсутствуют в Prometheus | Feature flag `gitlab_ci_builds_queuing_metrics` выключен | `curl /-/metrics \| grep gitlab_ci_queue` | Включите флаг в Rails console: `Feature.enable(:ci_observe_pipelines_finished)` |
| `pipelines_finished_total` не появляется | GitLab версии < 19.2 | `curl /-/metrics \| grep pipelines_finished_total` | Используйте `gitlab_ci_pipeline_time_to_finished_seconds` (требует флаг) или считайте из API |
| Runner метрики не собираются | `metrics_server` не настроен или порт закрыт | `curl runner:9252/metrics \| grep gitlab_runner` | Добавьте `metrics_server = ":9252"` в `config.toml` и перезапустите Runner |
| `node_filesystem_*` метрики отсутствуют | node_exporter не установлен на Runner хосте | `curl runner:9100/metrics \| grep node_filesystem` | Установите node_exporter на хост Runner'а |
| Дашборд показывает `no data` | Labels не совпадают между metric и query | Prometheus → Graph → проверить labels | Сравните labels метрики и expressions в Grafana |
| Алерт срабатывает на все пайплайны | Нет фильтра по `source` или `ref` | Выражение алерта | Добавьте `{source="push", ref="main"}` в PromQL |
| Pushgateway возвращает 403 | Нет доступа к сети или аутентификации | `curl -v pushgateway:9091/metrics` | Проверьте network policies и IP allowlist |
| OTel трейсы не появляются в Tempo | Неверный endpoint или атрибуты | `OTEL_LOG_LEVEL=debug` в пайплайне | Проверьте `OTEL_EXPORTER_OTLP_ENDPOINT` и `OTEL_RESOURCE_ATTRIBUTES` |
| Высокий burn rate без падений | Порог алерта слишком низкий | Анализ histograms в Grafana | Калибруйте пороги по baseline за 2–4 недели |
| Метрики исчезают после перезапуска Runner | `metrics_server` не в `config.toml` или конфиг перезаписан | `cat /etc/gitlab-runner/config.toml \| grep metrics` | Добавьте секцию `[runners.metrics]` и зафиксируйте конфиг в IaC |

## Дополнительная информация

*   **[Мониторинг и метрики GitLab CI/CD](../Advanced/monitoring_and_metrics.md)** — подробное руководство по метрикам GitLab Server и Runner'ов.
*   **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)** — SLI/SLO, трейсы, Golden Signals.
*   **[Метрики DORA](../../Core_Concepts/dora_metrics.md)** — Deployment Frequency, Lead Time, CFR, MTTR.
*   **[Capacity Planning для GitLab CI/CD](../Advanced/gitlab_capacity_planning.md)** — планирование мощности CI/CD инфраструктуры.
*   **[Управление парком раннеров](../../runner-fleet-management.md)** — мониторинг флота, автскейлинг.
*   **[GitLab Docs: Prometheus metrics](https://docs.gitlab.com/ee/administration/monitoring/prometheus/gitlab_metrics.html)** — официальный список метрик.
*   **[OpenTelemetry: инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)** — настройка OTel в проектах.

> **Критичные изменения последних версий:**
>
> *   **19.3**: `gitlab_ci_job_failure_reasons` включает label `runner_type`.
> *   **19.2**: `pipelines_finished_total` и `gitlab_ci_pipeline_time_to_finished_seconds` доступны по умолчанию.
> *   **19.0**: Улучшена интеграция с OpenTelemetry через OTLP.
> *   **18.0**: Встроенный Pushgateway для метрик от задач.
> *   **17.3**: CI/CD Catalog Components (GA).
