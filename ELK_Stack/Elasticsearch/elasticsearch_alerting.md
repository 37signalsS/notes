# Alerting: Kibana Alerting и Watcher

> Руководство по системам алертинга в Elastic Stack. Рассматриваются Kibana Alerting, Watcher, типы правил, actions и лучшие практики.
>
> Связанные темы: Stack Monitoring — [Stack Monitoring](./elasticsearch_stack_monitoring.md); Kibana — [Kibana Search and Visualization](../Kibana/kibana_search_and_visualization.md).

## Определения

* **Kibana Alerting** — современная система алертинга, встроенная в Kibana. Поддерживает различные типы правил и actions.
* **Watcher** — legacy система алертинга Elasticsearch (JSON-based, более гибкая, но сложная в управлении).
* **Rule** — определение условия алерта (что мониторить, когда срабатывать).
* **Action** — что делать при срабатывании (email, webhook, Slack, etc.)
* **Connector** — настройка подключения к внешней системе для actions.
* **Alert** — экземпляр сработавшего правила.
* **Monitor** (Synthetics) — мониторинг доступности сервисов.

## Архитектура Kibana Alerting

```
┌─────────────────────────────────────────────────────────┐
│                      Kibana                              │
│  ┌─────────┐    ┌─────────┐    ┌─────────────────────┐ │
│  │  Rules  │───▶│ Actions │───▶│   Connectors        │ │
│  │         │    │         │    │ (Slack, Email, etc) │ │
│  └─────────┘    └─────────┘    └─────────────────────┘ │
│       │                                                  │
│       ▼                                                  │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Alert Store (.alerts-*)             │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ Elasticsearch   │ (evaluates conditions)
└─────────────────┘
```

## Типы правил Kibana Alerting

### 1. Index Threshold

Срабатывает при превышении порога по данным индекса.

```bash
POST kibana/api/alerts/rule
{
  "name": "High Error Rate",
  "rule_type_api_name": "indexThreshold",
  "enabled": true,
  "consumer": "alerts",
  "params": {
    "index": ["logs-*"],
    "timeField": "@timestamp",
    "aggType": "count",
    "groupBy": "top",
    "termField": "service.name",
    "termSize": 10,
    "thresholdComparator": ">",
    "threshold": [100],
    "timeWindowSize": 5,
    "timeWindowUnit": "m"
  },
  "actions": [
    {
      "group": "threshold met",
      "id": "slack-connector-id",
      "params": {
        "message": "High error count detected for {% raw %}{{context.group}}{% endraw %}: {% raw %}{{context.value}}{% endraw %}"
      }
    }
  ],
  "schedule": {
    "interval": "1m"
  }
}
```

### 2. Elasticsearch Query

Срабатывает при выполнении произвольного ES запроса.

```bash
POST kibana/api/alerts/rule
{
  "name": "Critical Errors",
  "rule_type_api_name": "esQuery",
  "enabled": true,
  "params": {
    "index": ["logs-*"],
    "timeField": "@timestamp",
    "esQuery": "{\"size\":0,\"query\":{\"bool\":{\"must\":[{\"term\":{\"level\":\"CRITICAL\"}},{\"range\":{\"@timestamp\":{\"gte\":\"now-5m\"}}}]}}}",
    "thresholdComparator": ">",
    "threshold": [0]
  },
  "actions": [
    {
      "group": "query matched",
      "id": "pagerduty-connector-id",
      "params": {
        "severity": "critical",
        "description": "Critical errors detected"
      }
    }
  ],
  "schedule": {
    "interval": "1m"
  }
}
```

### 3. ES|QL Query

Использует ES|QL для определения условия.

```bash
POST kibana/api/alerts/rule
{
  "name": "High Latency Services",
  "rule_type_api_name": "esqlQuery",
  "enabled": true,
  "params": {
    "index": "logs-*",
    "timeField": "@timestamp",
    "esqlQuery": "FROM logs-* | STATS avg_latency = AVG(response_time) BY service.name | WHERE avg_latency > 1000",
    "thresholdComparator": ">",
    "threshold": [0]
  },
  "actions": [
    {
      "group": "query matched",
      "id": "slack-connector-id",
      "params": {
        "message": "High latency: {% raw %}{{context.rows}}{% endraw %}"
      }
    }
  ],
  "schedule": {
    "interval": "5m"
  }
}
```

### 4. APM

Мониторинг производительности приложений.

```bash
POST kibana/api/alerts/rule
{
  "name": "High APM Latency",
  "rule_type_api_name": "apm",
  "enabled": true,
  "params": {
    "serviceName": "my-service",
    "transactionType": "request",
    "transactionName": "GET /api/users",
    "metric": "transaction.duration.p95",
    "threshold": 500,
    "comparator": ">",
    "windowSize": 5,
    "windowUnit": "m"
  },
  "actions": [
    {
      "group": "threshold met",
      "id": "slack-connector-id",
      "params": {
        "message": "APM latency high for {% raw %}{{context.transactionName}}{% endraw %}"
      }
    }
  ],
  "schedule": {
    "interval": "1m"
  }
}
```

### 5. Infrastructure

Мониторинг инфраструктуры (CPU, memory, disk).

```bash
POST kibana/api/alerts/rule
{
  "name": "High CPU Usage",
  "rule_type_api_name": "metrics",
  "enabled": true,
  "params": {
    "criteria": [
      {
        "metric": "system.cpu.total.norm.pct",
        "comparator": ">",
        "threshold": [0.9],
        "warningComparator": ">",
        "warningThreshold": [0.8]
      }
    ],
    "sourceId": "default",
    "filterQuery": "host.name: web-*",
    "warningFilterQuery": "host.name: web-*",
    "groupBy": "host.name",
    "warningGroupBy": "host.name",
    "aggregation": "avg",
    "timeSize": 5,
    "timeUnit": "m"
  },
  "actions": [
    {
      "group": "threshold met",
      "id": "slack-connector-id",
      "params": {
        "message": "High CPU on {% raw %}{{context.group}}{% endraw %}: {% raw %}{{context.value}}{% endraw %}"
      }
    }
  ],
  "schedule": {
    "interval": "1m"
  }
}
```

### 6. Uptime / Synthetics

Мониторинг доступности сервисов.

```bash
POST kibana/api/alerts/rule
{
  "name": "Service Down",
  "rule_type_api_name": "monitoring_alerts",
  "enabled": true,
  "params": {
    "duration": "3m",
    "severity": "critical"
  },
  "actions": [
    {
      "group": "threshold met",
      "id": "pagerduty-connector-id",
      "params": {
        "severity": "critical",
        "description": "Service is down"
      }
    }
  ],
  "schedule": {
    "interval": "1m"
  }
}
```

## Connectors (Actions)

### Slack

```bash
POST kibana/api/actions/connector
{
  "name": "Slack Alerts",
  "connector_type_id": ".slack",
  "config": {
    "webhookUrl": "https://hooks.slack.com/services/xxx/yyy/zzz"
  },
  "secrets": {}
}
```

### Email

```bash
POST kibana/api/actions/connector
{
  "name": "Email Alerts",
  "connector_type_id": ".email",
  "config": {
    "service": "gmail",
    "from": "alerts@company.com",
    "hasAuth": true
  },
  "secrets": {
    "user": "alerts@company.com",
    "password": "app-password"
  }
}
```

### PagerDuty

```bash
POST kibana/api/actions/connector
{
  "name": "PagerDuty",
  "connector_type_id": ".pagerduty",
  "config": {
    "apiUrl": "https://events.pagerduty.com/v2/enqueue"
  },
  "secrets": {
    "routingKey": "your-routing-key"
  }
}
```

### Webhook

```bash
POST kibana/api/actions/connector
{
  "name": "Custom Webhook",
  "connector_type_id": ".webhook",
  "config": {
    "url": "https://api.company.com/alerts",
    "method": "POST",
    "headers": {
      "Authorization": "Bearer {{secret.token}}",
      "Content-Type": "application/json"
    }
  },
  "secrets": {
    "token": "your-token"
  }
}
```

### Index (запись алерта в индекс)

```bash
POST kibana/api/actions/connector
{
  "name": "Index Alerts",
  "connector_type_id": ".index",
  "config": {
    "index": "alerts-history"
  }
}
```

## Watcher (Legacy)

### Структура Watcher

```json
{
  "trigger": { "schedule": { "interval": "10m" } },
  "input": { "search": { "request": { ... } } },
  "condition": { "compare": { "ctx.payload.hits.total": { "gt": 100 } } },
  "actions": {
    "log_alert": { "logging": { "text": "..." } },
    "email_admin": { "email": { "to": "admin@company.com", "subject": "Alert" } }
  }
}
```

### Создание Watcher

```bash
PUT _watcher/watch/high-error-rate
{
  "trigger": { "schedule": { "interval": "5m" } },
  "input": {
    "search": {
      "request": {
        "indices": ["logs-*"],
        "body": {
          "size": 0,
          "query": {
            "bool": {
              "must": [
                { "term": { "level": "ERROR" } },
                { "range": { "@timestamp": { "gte": "now-5m" } } }
              ]
            }
          }
        }
      }
    }
  },
  "condition": {
    "compare": {
      "ctx.payload.hits.total": { "gt": 100 }
    }
  },
  "actions": {
    "log_error": {
      "logging": {
        "text": "High error rate detected: {% raw %}{{ctx.payload.hits.total}}{% endraw %} errors in last 5 minutes"
      }
    },
    "email_admin": {
      "email": {
        "to": ["admin@company.com"],
        "subject": "High Error Rate Alert",
        "body": "Detected {% raw %}{{ctx.payload.hits.total}}{% endraw %} errors in the last 5 minutes"
      }
    }
  }
}
```

### Управление Watcher

```bash
# Запуск вручную
POST _watcher/watch/high-error-rate/_execute

# Статус
GET _watcher/stats

# Остановка
PUT _watcher/watch/high-error-rate/_deactivate

# Активация
PUT _watcher/watch/high-error-rate/_activate

# Удаление
DELETE _watcher/watch/high-error-rate
```

## Kibana Alerting vs Watcher

| Критерий | Kibana Alerting | Watcher |
|----------|-----------------|---------|
| UI | Да (Kibana) | Нет (API only) |
| Управление | Централизовано | Децентрализовано |
| Типы правил | Предопределенные | Любые (JSON) |
| Actions | Connectors | Встроенные |
| Масштабирование | Легко | Сложнее |
| Версионирование | Через Kibana | Вручную |
| Рекомендация | Да (для новых) | Legacy |

## Мониторинг алертов

### Alert Store

```bash
# Список активных алертов
GET .alerts-*/_search
{
  "query": {
    "term": { "alert.attributes.executionStatus.status": "active" }
  }
}

# История алертов
GET .alerts-history-*/_search
{
  "sort": [{ "@timestamp": "desc" }],
  "size": 100
}

# Алерты по правилу
GET .alerts-history-*/_search
{
  "query": {
    "term": { "kibana.alert.rule.name": "High Error Rate" }
  }
}
```

### Метрики алертов

```bash
# Количество срабатываний по правилам
GET .alerts-history-*/_search
{
  "size": 0,
  "aggs": {
    "by_rule": {
      "terms": { "field": "kibana.alert.rule.name", "size": 20 }
    }
  }
}
```

## Best Practices

### Проектирование правил

1. **Группируйте алерты** — используйте `groupBy` для избежания alert fatigue
2. **Устанавливайте пороги** — на основе baseline, не произвольно
3. **Добавляйте контекст** — в message включайте информацию для диагностики
4. **Используйте severity** — warning для предупреждений, critical для инцидентов
5. **Тестируйте правила** — проверяйте на исторических данных

### Alert Fatigue Prevention

1. **Подавление (suppression)** — не отправлять дубликаты в течение N минут
2. **Группировка** — один алерт на группу серверов
3. **Maintenance windows** — отключать алерты во время обслуживания
4. **Пороги** — избегать слишком чувствительных правил

### Пример: Подавление дубликатов

```bash
POST kibana/api/alerts/rule
{
  "name": "High Memory",
  "params": {
    "criteria": [...],
    "groupBy": "host.name",
    "alertOnNoData": false,
    "alertOnGroupDisappear": false
  },
  "actions": [
    {
      "group": "threshold met",
      "id": "slack-connector-id",
      "params": { "message": "..." },
      "frequency": {
        "notifyWhen": "onActionGroupChange",
        "throttle": "1h"
      }
    }
  ]
}
```

### Организация правил

```
Production Alerts
├── Critical (PagerDuty)
│   ├── Cluster Red
│   ├── Service Down
│   └── Data Loss
├── Warning (Slack)
│   ├── High Heap
│   ├── High Latency
│   └── Disk Space
└── Info (Email)
    ├── Daily Report
    └── Weekly Summary
```

## Troubleshooting

### Правило не срабатывает

1. Проверить `enabled: true`
2. Проверить `schedule.interval`
3. Проверить условие на исторических данных
4. Проверить логи Kibana: `kibana.log`

### Actions не отправляются

1. Проверить connector конфигурацию
2. Проверить credentials
3. Проверить network connectivity
4. Проверить логи Kibana

### Слишком много алертов

1. Увеличить пороги
2. Добавить подавление
3. Использовать groupBy
4. Настроить maintenance windows

## См. также

* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — Alerting UI в Kibana.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — метрики для алертинга.
* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — Watcher API.
* **[Security Advanced](./elasticsearch_security_advanced.md)** — аудит действий.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов.
