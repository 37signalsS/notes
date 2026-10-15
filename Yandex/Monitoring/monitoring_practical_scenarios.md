# Yandex Monitoring: Практические сценарии

## 1. Определения

**Custom Metrics API** — HTTP API Yandex Monitoring для отправки пользовательских метрик. Endpoint: `https://monitoring.api.cloud.yandex.net/monitoring/v2/timeseries:write`.

**Query Language** — встроенный язык запросов Yandex Monitoring для фильтрации, агрегации и визуализации метрик. Синтаксис: цепочка операторов через `|`.

**Log Router** — компонент Cloud Logging для маршрутизации логов в целевые системы (Cloud Functions, Data Streams).

## 2. Базовые концепции

### Аутентификация API

Все запросы к API требуют IAM-токена:

```bash
# Получение токена
TOKEN=$(yc iam create-token)

# Folder ID — обязательный параметр
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

Подробное описание модели данных и агрегаций приведено в файле **[Основные концепции](./monitoring_concepts.md)**.

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
FOLDER_ID=<folder_id>
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

### 3.2. Метрики на основе логов (Log-based Metrics)

Сценарий: подсчёт количества 5xx ошибок из логов Nginx через Cloud Functions.

1. Cloud Logging собирает логи.
2. Log Router направляет события в Cloud Function.
3. Функция агрегирует данные и публикует метрику в Monitoring.

```python
# Пример функции для агрегации
import requests

def handler(event, context):
    error_count = sum(1 for log in event['messages'] 
                      if log['json'].get('status', 0) >= 500)
    
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

### 3.3. Примеры запросов

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

### 3.4. Настройка алертов

Пример конфигурации алерта для критического уровня ошибок:

```yaml
alert: "High Error Rate"
expr: |
  metric("custom.http_requests_total")
  | filter(service="checkout", env="prod", status=~"5..")
  | rate(5m)
  | sum()
  | gt(10)
for: 5m
labels:
  severity: critical
annotations:
  summary: "Too many 5xx errors on checkout service"
```

### 3.5. Чтение логов из группы Cloud Logging

```bash
# Чтение логов из группы за последний час (только ERROR/WARN)
yc logging read \
  --group-name <group_name> \
  --since 1h \
  --levels ERROR,WARN \
  --format json | \
  jq -r '.[] | "\(.timestamp) \(.level) \(.message)"'

# Подписка на логи в реальном времени
yc logging read \
  --group-name <group_name> \
  --since 5m \
  --follow
# note: --since принимает относительные окна (1h, 30m)
```

## 4. Дополнительная информация

### Связанные темы

- **[Основные концепции](./monitoring_concepts.md)** — модель данных и типы метрик.
- **[Дополнительные темы](./monitoring_advanced_topics.md)** — Grafana и Best Practices.
- **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — RED, USE и Four Golden Signals.
