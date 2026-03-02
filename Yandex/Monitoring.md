# Yandex Monitoring

## Определения

**Yandex Monitoring** — сервис для сбора, хранения и визуализации метрик производительности и доступности ресурсов Yandex Cloud и пользовательских приложений.

**Метрика** — именованный временной ряд числовых данных, описывающих состояние системы (CPU, память, латентность, ошибки).

**Cloud Logging** — сервис централизованного сбора и анализа логов. Интегрируется с Monitoring для создания метрик на основе логов.

---

## Основные концепции

### Модель данных

**Метрика состоит из:**
- **Имя** — уникальный идентификатор (например, `yandex_compute_cpu_usage`)
- **Метки (labels)** — пары ключ-значение для фильтрации и группировки (`service=checkout`, `env=prod`)
- **Точки (points)** — пары timestamp + value
- **Тип**:
  - **Gauge** — снимок состояния (температура, использование памяти)
  - **Counter** — монотонно растущий счётчик (число запросов)
  - **Histogram/Summary** — распределение значений (латентность)

**Агрегации:**
- `sum`, `avg`, `min`, `max` — базовые агрегации
- `rate`, `delta` — для счётчиков (изменение за интервал)
- `percentile`, `quantile` — для латентности (p50, p95, p99)

### Источники метрик

| Источник | Тип | Описание |
| :--- | :--- | :--- |
| **Yandex Cloud сервисы** | Автоматически | Compute, Databases, Kubernetes, Load Balancer |
| **Custom Metrics API** | Push | Пользовательские метрики через HTTP API |
| **Prometheus-compatible** | Push/Pull | Интеграция через Managed Service for Prometheus |
| **Log-based metrics** | Derived | Метрики из логов через Cloud Logging |

### Сравнение: Monitoring vs Logging

| Аспект | Monitoring | Logging |
| :--- | :--- | :--- |
| **Данные** | Агрегированные метрики (числа) | Детальные события (текст/JSON) |
| **Назначение** | Тренды, алерты, дашборды | Расследование инцидентов, аудит |
| **Хранение** | Долгосрочное (месяцы) | Краткосрочное (дни/недели) |
| **Запросы** | Агрегации, оконные функции | Полнотекстовый поиск, парсинг |

> **Рекомендация:** Используйте совместно — Monitoring для обнаружения аномалий, Logging для диагностики причин.

---

## Практические сценарии

### Отправка пользовательских метрик через API

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

**Рекомендации по меткам:**
- Используйте фиксированный набор ключей (`service`, `env`, `host`)
- Избегайте высокой кардинальности (не используйте user_id, request_id)
- Ограничьте количество уникальных значений (< 1000 на метку)

### Логи → Метрики (Log-based Metrics)

Сценарий: подсчёт количества 5xx ошибок из логов Nginx.

**Шаг 1: Cloud Logging собирает логи**

```yaml
# logging.yaml
log_group: nginx-access
retention_days: 7
```

**Шаг 2: Log Router направляет в функцию**

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

**Шаг 3: Функция агрегирует и публикует метрику**

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

### Запросы к метрикам

**Пример 1: RPS по сервисам**

```
metric("custom.http_requests_total")
| filter(service="checkout", env="prod")
| rate(1m)
| group_by(["status"])
```

**Пример 2: 99-й перцентиль латентности**

```
metric("custom.http_request_duration_seconds")
| filter(service="checkout", env="prod")
| percentile(0.99, 5m)
```

**Пример 3: Использование CPU ВМ**

```
metric("yandex_compute_cpu_usage")
| filter(cluster="prod", host=~"app-.*")
| avg(5m)
| max()
```

### Дашборды

**Типы виджетов:**
- **Graph** — временные ряды, тренды
- **Number** — текущее значение метрики
- **Table** — сводка по нескольким метрикам
- **Alert list** — список активных алертов

**Переменные дашборда:**
- `env` — окружение (dev, stage, prod)
- `service` — имя сервиса
- `host` — конкретный хост

**Пример структуры:**

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

### Алертинг

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

**Рекомендации по алертингу:**
- Используйте окна устойчивости (`for`) для избежания ложных срабатываний
- Настраивайте гистерезис (разные пороги для срабатывания и восстановления)
- Группируйте алерты по сервису и окружению
- Добавляйте ссылки на runbooks
- Используйте метки для маршрутизации (severity, team)

### Интеграция с Grafana

**Вариант 1: Yandex Monitoring как источник данных**

1. Установите плагин Yandex Monitoring
2. Добавьте datasource с IAM-аутентификацией
3. Используйте Query Editor для запросов

**Вариант 2: Managed Service for Prometheus**

1. Разверните MSP в Yandex Cloud
2. Настройте скрейпинг метрик
3. Подключите Prometheus как datasource в Grafana

---

## Дополнительная информация

### Связанные документы

- **[Compute Cloud](./Compute-Cloud.md)** — метрики ВМ
- **[Managed Databases](./Managed-Databases.md)** — метрики БД
- **[VPC](./VPC.md)** — сетевые метрики
- **[Prometheus](../Prometheus/overview.md)** — альтернативная система мониторинга

### Интеграции

- **[Kubernetes](../Kubernetes/)** — метрики кластеров и подов
- **[Grafana](../Grafana/grafana_overview.md)** — визуализация и дашборды
- **[Alertmanager](../Prometheus/alertmanager.md)** — управление оповещениями

### Best Practices

**Метрики:**
- Следуйте методологии RED (Rate, Errors, Duration) для сервисов
- Используйте USE (Utilization, Saturation, Errors) для инфраструктуры
- Избегайте высокой кардинальности меток

**Алерты:**
- Настраивайте многоуровневую эскалацию (warning → critical → page)
- Добавляйте контекст в уведомления (сервис, окружение, ссылка на дашборд)
- Регулярно пересматривайте пороги и окна

**Дашборды:**
- Создавайте иерархию: общий → сервис → хост
- Используйте переменные для фильтрации
- Документируйте метрики и пороги

### Актуальная информация (2025–2026)

- **Q4 2025:** Добавлена вкладка Alerts для Managed Service for Prometheus
- **Q4 2025:** Детальные метрики диска для Managed Databases
- **Мониторинг по умолчанию:** все сервисы YC публикуют метрики автоматически
