# Yandex Monitoring: Практические сценарии

## 1. Определения

**Custom Metrics API** — HTTP API Yandex Monitoring для отправки пользовательских метрик. Endpoint: `https://monitoring.api.cloud.yandex.net/monitoring/v2/timeseries:write`.

**Query Language** — встроенный язык запросов Yandex Monitoring для фильтрации, агрегации и визуализации метрик. Синтаксис: цепочка операторов через `|`.

**Log Router** — компонент Cloud Logging для маршрутизации логов в целевые системы (Cloud Functions, Data Streams, другие log groups).

## 2. Базовые концепции

### Аутентификация API

Все запросы к API требуют IAM-токена:

```bash
# Получение токена
TOKEN=$(yc iam create-token)

# Folder ID — обязательный параметр для всех операций
FOLDER_ID=$(yc config get folder-id)
```

### Структура запроса метрик

Базовый синтаксис: `metric("имя") | filter(...) | агрегация(окно) | группировка`

| Оператор | Описание | Пример |
| :--- | :--- | :--- |
| `metric()` | Выбор метрики | `metric("yandex_compute_cpu_usage")` |
| `filter()` | Фильтрация по меткам | `filter(service="checkout", env="prod")` |
| `rate()` | Скорость изменения (для Counter) | `rate(1m)` |
| `avg()`, `sum()`, `min()`, `max()` | Агрегация за окно | `avg(5m)` |
| `percentile()` | Оценка перцентиля | `percentile(0.99, 5m)` |
| `group_by()` | Группировка по меткам | `group_by(["status"])` |
| `gt()`, `lt()`, `gte()`, `lte()` | Пороговые сравнения | `gt(0.5)` |

> **Концепции метрик и агрегаций:** [Модель данных](./monitoring_concepts.md#2-базовые-концепции)

### Виджеты дашбордов

| Тип | Назначение | Пример |
| :--- | :--- | :--- |
| **Graph** | Временные ряды, тренды | RPS, латентность, CPU |
| **Number** | Текущее значение | Количество ошибок сейчас |
| **Table** | Сводка по нескольким метрикам | Состояние всех хостов |
| **Alert list** | Список активных алертов | Оперативная сводка |

## 3. Практические сценарии

### 3.1. Отправка пользовательских метрик через API

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

> **Рекомендации по меткам:** [Кардинальность меток](./monitoring_concepts.md#кардинальность-меток)

### 3.2. Логи → Метрики (Log-based Metrics)

Сценарий: подсчёт количества 5xx ошибок из логов Nginx.

**Шаг 1:** Cloud Logging собирает логи

```yaml
# logging.yaml
log_group: nginx-access
retention_days: 7
```

**Шаг 2:** Log Router направляет в функцию

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

**Шаг 3:** Функция агрегирует и публикует метрику

```python
# aggregator.py
import json
import requests

def handler(event, context):
    # Подсчёт 5xx за окно
    error_count = sum(1 for log in event['messages']
                      if log['json'].get('status', 0) >= 500)

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

### 3.3. Запросы к метрикам

**RPS по сервисам:**

```
metric("custom.http_requests_total")
| filter(service="checkout", env="prod")
| rate(1m)
| group_by(["status"])
```

**99-й перцентиль латентности:**

```
metric("custom.http_request_duration_seconds")
| filter(service="checkout", env="prod")
| percentile(0.99, 5m)
```

**Использование CPU ВМ:**

```
metric("yandex_compute_cpu_usage")
| filter(cluster="prod", host=~"app-.*")
| avg(5m)
| max()
```

### 3.4. Дашборды

**Переменные дашборда:**

| Переменная | Значения | Назначение |
| :--- | :--- | :--- |
| `env` | `dev`, `stage`, `prod` | Фильтрация по окружению |
| `service` | `checkout`, `payment`, `delivery` | Фильтрация по сервису |
| `host` | произвольное | Конкретный хост |

**Пример структуры дашборда:**

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

> **Best practices дашбордов:** [Best Practices](./monitoring_advanced_topics.md#best-practices)

### 3.5. Алертинг

**Структура алерта:**

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

> **Рекомендации по алертингу:** [Best Practices](./monitoring_advanced_topics.md#best-practices)

## 4. Дополнительная информация

### Интеграция с другими сервисами

- **[Compute Cloud](../Compute-Cloud.md)** — мониторинг ВМ через автоматические метрики `yandex_compute_*`
- **[Managed Databases](../Managed-Databases.md)** — метрики БД (`yandex_mdb_*`), детальные метрики диска (Q4 2025)
- **[VPC](../VPC.md)** — сетевые метрики трафика и security groups
- **[Cloud Logging](https://yandex.cloud/ru/services/logging)** — источник для log-based метрик

### Связанные концепции

- Модель данных и типы метрик — [Основные концепции](./monitoring_concepts.md#2-базовые-концепции)
- Интеграция с Grafana — [Дополнительные темы](./monitoring_advanced_topics.md#интеграция-с-grafana)
- Методологии RED/USE — [Методологии мониторинга](./monitoring_concepts.md#методологии-мониторинга)
