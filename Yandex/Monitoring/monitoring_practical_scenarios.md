# Yandex Monitoring: Практические сценарии

## 1. Отправка пользовательских метрик через API

```bash
# Получение IAM-токена
TOKEN=$(yc iam create-token)

# Folder ID
FOLDER_ID=<your_folder_id>

# Endpoint
ENDPOINT=https://monitoring.api.cloud.yandex.net/monitoring/v2/timeseries:write

# Отправка метрики
curl -sS -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "$ENDPOINT?folderId=$FOLDER_ID" \
  -d '{
    "timeseries": [
      {
        "name": "custom.http_requests_total",
        "labels": {
          "service": "checkout",
          "env": "prod",
          "status": "200"
        },
        "points": [
          {
            "ts": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'",
            "value": 42
          }
        ]
      }
    ]
  }'
```

### Рекомендации по меткам

- Используйте фиксированный набор ключей (`service`, `env`, `host`)
- Избегайте высокой кардинальности (не используйте user_id, request_id)
- Ограничьте количество уникальных значений (< 1000 на метку)

## 2. Логи → Метрики (Log-based Metrics)

Сценарий: подсчёт количества 5xx ошибок из логов Nginx.

### Шаг 1: Cloud Logging собирает логи

```yaml
# logging.yaml
log_group: nginx-access
retention_days: 7
```

### Шаг 2: Log Router направляет в функцию

```bash
# Создание триггера
yc logging log-group create \
  --name nginx-errors \
  --folder-id <folder_id>

yc functions trigger create \
  --name nginx-5xx-trigger \
  --logging-log-group-ids <log_group_id> \
  --container-name nginx-metrics-aggregator
```

### Шаг 3: Функция агрегирует и публикует метрику

```python
# aggregator.py
import json
import requests

def handler(event, context):
    # Подсчёт 5xx за окно
    error_count = sum(1 for log in event['messages']
                      if log['json'](get('status', 0) >= 500)

    # Публикация в Monitoring
    requests.post(
        'https://monitoring.api.cloud.yandex.net/monitoring/v2/timeseries:write',
        headers={'Authorization': f'Bearer {context.token}'},
        json={
            'timeseries': [{
                'name': 'custom.nginx_5xx_total',
                'labels': {'service': 'nginx', 'env': 'prod'},
                'points': [{'ts': context.trigger_deadline, 'value': error_count}]
            }]
        }
    )
```

## 3. Запросы к метрикам

### Пример 1: RPS по сервисам

```
metric("custom.http_requests_total")
| filter(service="checkout", env="prod")
| rate(1m)
| group_by(["status"])
```

### Пример 2: 99-й перцентиль латентности

```
metric("custom.http_request_duration_seconds")
| filter(service="checkout", env="prod")
| percentile(0.99, 5m)
```

### Пример 3: Использование CPU ВМ

```
metric("yandex_compute_cpu_usage")
| filter(cluster="prod", host=~"app-.*")
| avg(5m)
| max()
```

## 4. Дашборды

### Типы виджетов

| Тип | Описание |
| :--- | :--- |
| **Graph** | Временные ряды, тренды |
| **Number** | Текущее значение метрики |
| **Table** | Сводка по нескольким метрикам |
| **Alert list** | Список активных алертов |

### Переменные дашборда

- `env` — окружение (dev, stage, prod)
- `service` — имя сервиса
- `host` — конкретный хост

### Пример структуры

```yaml
dashboard: "Checkout Service"
variables:
  - name: env
    values: [dev, stage, prod]
    default: prod
  - name: service
    values: [checkout, payment, delivery]
    default: checkout

panels:
  - title: "RPS by Status"
    type: graph
    query: |
      metric("custom.http_requests_total")
      | filter(service="${service}", env="${env}")
      | rate(1m)
      | group_by(["status"])

  - title: "P99 Latency"
    type: graph
    query: |
      metric("custom.http_request_duration_seconds")
      | filter(service="${service}", env="${env}")
      | percentile(0.99, 5m)

  - title: "Error Rate"
    type: number
    query: |
      metric("custom.http_requests_total")
      | filter(service="${service}", env="${env}", status=~"5..")
      | rate(5m)
      | sum()
```

## 5. Алертинг

### Структура алерта

```yaml
alert: "High 99p Latency"
description: "P99 latency exceeds 500ms for 10 minutes"

expr: |
  metric("custom.http_request_duration_seconds")
  | filter(service="checkout", env="prod")
  | percentile(0.99, 5m)
  | gt(0.5)

for: 10m              # Окно устойчивости
labels:
  severity: critical
  team: checkout

annotations:
  summary: "High latency on checkout service"
  runbook: "https://wiki.company/runbooks/checkout-latency"

notifications:
  - channel: email
    recipients: [oncall@company.com]
  - channel: webhook
    url: https://slack.webhook/xxx
  - channel: pagerduty
    service_key: xxx

silence:
  schedule: night-maintenance
  days: [saturday, sunday]
  hours: [2, 3, 4]
```

### Рекомендации по алертингу

- Используйте окна устойчивости (`for`) для избежания ложных срабатываний
- Настраивайте гистерезис (разные пороги для срабатывания и восстановления)
- Группируйте алерты по сервису и окружению
- Добавляйте ссылки на runbooks
- Используйте метки для маршрутизации (severity, team)

## Связанные документы

- **[Основные концепции](./monitoring_concepts.md)** — определения и модель данных
- **[Дополнительные темы](./monitoring_advanced_topics.md)** — интеграция с Grafana, best practices
- **[Cloud Logging](../../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)** — сервис логов
- **[Alertmanager](../../Prometheus/alertmanager.md)** — управление оповещениями
