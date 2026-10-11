# Alerting: Kibana Alerting и Watcher

**Актуально для:** Kibana 9.5.x / 8.19 LTS

> Руководство по системам алертинга в Elastic Stack: Kibana Alerting (GA-система, правила, connectors, actions) и Watcher (legacy, Platinum). Рассматриваются типы правил, жизненный цикл, хранение алертов, настройка и лучшие практики.
>
> Связанные темы: Stack Monitoring — [Stack Monitoring](./elasticsearch_stack_monitoring.md); Kibana — [Kibana Search and Visualization](../Kibana/kibana_search_and_visualization.md); безопасность — [Security Advanced](./elasticsearch_security_advanced.md).

## Определения

* **Kibana Alerting** — встроенная система алертинга Kibana. Правила (rules) проверяют данные по расписанию, создают алерты (alerts) при выполнении условий и запускают actions через connectors. Доступна на всех деплоях (большинство rule types — Basic-лицензия).
* **Watcher** — legacy-система алертинга Elasticsearch (JSON-based, низкоуровневый контроль input/condition/transform/action). Требует Platinum-лицензии.
* **Rule** — определение условия алерта: условия (params), расписание (schedule) и actions. Состоит из неизменяемых после создания `rule_type_id` и `consumer`.
* **Rule type** — реализация условия, зарегистрированная плагином Kibana (например, `.index-threshold`). Скрывает детали запроса и экспонирует параметры.
* **Consumer** — feature, которому принадлежит правило (`alerts` — default, `stackAlerts`, `metrics`, `infrastructure`, `apm`, `uptime`, `siem`, `ml`). Определяет, где видны алерты: правила Observability/Security не видны в Stack Management > Rules.
* **Alert** — отслеживаемое вхождение условия правила (например, каждый хост с CPU > 0.9 — отдельный alert). Статусы: `active`, `recovered`, `flapping`; triage-статус (`kibana.alert.workflow_status`): `open`, `acknowledged`, `closed`.
* **Action** — что делать при срабатывании: вызов connector'а. Запускается согласно action frequency.
* **Connector** — сохранённый объект с настройками подключения к внешней системе (Slack, Email, PagerDuty, Webhook и др.). Один connector могут использовать несколько правил.
* **Action group** — именованная группа действий rule type (например, `threshold met`, `query matched`, `recovered`). Доступные группы определяет rule type.
* **Action frequency** — когда запускается action: `notify_when` = `onActionGroupChange` | `onActiveAlert` | `onThrottleInterval`, опционально `throttle` (интервал) и `summary` (alert summaries).
* **Alert store** — системные индексы `.alerts-*`, где хранятся алерты (alerts-as-data).
* **Task Manager** — подсистема Kibana, выполняющая правила и actions как persistent background tasks на всех инстансах Kibana.
* **Flapping** — быстрое переключение алерта между active/recovered; детектируется по умолчанию, actions на смену статуса не запускаются.
* **Watch** — определение в Watcher: trigger, input, condition, transform (опц.), actions.
* **Throttle period** (Watcher) — период подавления повторного выполнения action.
* **Ack** (Watcher) — ручное подтверждение watch'а, подавляющее actions до сброса условия.

## Архитектура и модель выполнения

```
┌──────────────────────────────────────────────────────────────┐
│                          Kibana (5601)                        │
│                                                                │
│  ┌──────────┐   ┌───────────────┐   ┌──────────────────────┐ │
│  │   Rules  │──▶│ Task Manager  │──▶│      Actions         │ │
│  │ (params, │   │ (persistent   │   │ (frequency, groups)  │ │
│  │ schedule)│   │  background   │   └──────────┬───────────┘ │
│  └──────────┘   │   tasks)      │              │             │
│        │        └───────────────┘              ▼             │
│        │                                      ▼             │
│        │        ┌───────────────────────┐  ┌──────────────┐ │
│        │        │   Connectors          │  │  Connectors  │ │
│        │        │ (Slack, Email, PD, …) │  │ (webhook…)   │ │
│        │        └───────────────────────┘  └──────────────┘ │
│        ▼                                                      │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Alert Store: .alerts-<context>.alerts-<space-id>    │    │
│  │  (ILM: .alerts-ilm-policy — rollover 30d / 50GB)     │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
         │  правила выполняют запросы к данным
         ▼
┌─────────────────┐
│  Elasticsearch  │  (источник данных и хранилище алертов;
│                 │   условия вычисляет Kibana, не ES)
└─────────────────┘
```

### Модель выполнения (Task Manager)

* Правила и actions выполняются как persistent background tasks, распределённые между всеми инстансами Kibana. Каждый инстанс опрашивает индекс задач с интервалом `xpack.task_manager.poll_interval` (default 500ms, минимум 100ms) и выполняет до `xpack.task_manager.max_workers` (default 10, максимум 100) задач одновременно.
* Задачи правил — recurring: после выполнения перепланируются на следующий check interval. Задачи actions — одноразовые: удаляются после выполнения.
* Определения задач хранятся в индексе `.kibana_task_manager`. **В production у индекса должен быть минимум 1 replica — при потере индекса все запланированные алерты и actions теряются.**
* Правила выполняются от имени встроенного API key, создаваемого при создании правила. Key ротируется при update/enable/disable правила; инвалидация старых ключей — фоновая задача (`xpack.alerting.invalidateApiKeysTask.interval`, default 5m).
* **API keys требуют TLS на HTTP-интерфейсе Kibana — прокси недостаточен.** Это обязательное предварительное требование для алертинга.
* Для connectors с secrets требуется `xpack.encryptedSavedObjects.encryptionKey` в `kibana.yml` (иначе правила с actions не работают).

## Лицензирование и предварительные требования

| Компонент | Лицензия | Примечание |
|---|---|---|
| Kibana Alerting (stack rules: `.index-threshold`, `.es-query`) | Basic | Доступна на всех деплоях |
| Observability-правила (metrics, APM, uptime, logs threshold) | Basic | Создание в соответствующих UI |
| ML-правила (anomaly detection), SLO-правила | Platinum / Enterprise | Только платные тиры |
| Watcher | Platinum | X-Pack; email/webhook/slack/pagerduty/jira actions |
| Connectors (Slack, Email, PagerDuty, Webhook, Index, Server log) | Basic | Часть integration-connectors — платные |

Предварительные требования:

1. TLS на HTTP-интерфейсе Kibana (для API keys правил).
2. `xpack.encryptedSavedObjects.encryptionKey` в `kibana.yml` (для secrets connectors).
3. Для Watcher: Platinum-лицензия и настройка `xpack.notification.email` (для email actions).
4. Привилегии Kibana: для создания stack-правил — feature privilege `all` для Stack Rules; для чтения алертов — `read` (Stack Alerts / Observability Alerts).

## Типы правил

Полный список доступных rule types: `GET /api/alerting/rule_types` (возвращает ID, параметры и action groups каждого типа).

### Stack rules (Stack Management > Rules)

| Тип | `rule_type_id` | Условие |
|---|---|---|
| Elasticsearch query | `.es-query` | Произвольный запрос (Query DSL, ES|QL, KQL или Lucene), число совпадений сравнивается с порогом |
| Index threshold | `.index-threshold` | Агрегация числового поля (count, average, sum, min, max) за time window, сравнение с порогом; группировка `all` или `top` по терму |
| Transform rules | (Beta) | Проверка здоровья continuous transform |
| Tracking containment | — | Документы в границах из boundary-индекса (платный) |

### Observability rules (создаются в Observability/Applications UI)

| Домен | Типы правил | Consumer |
|---|---|---|
| Metrics | Metric threshold (`metrics.alert.threshold`), log threshold | `metrics`, `infrastructure` |
| APM | APM Anomaly, Error count threshold, Failed transaction rate threshold, Latency threshold | `apm` |
| Uptime | Monitor status, TLS certificate, ICMP, latency — ID по паттерну `xpack.uptime.alerts.actionGroups.<type>` (например, `xpack.uptime.alerts.actionGroups.tls`) | `uptime` |
| Logs | Log threshold, log category | `logs` |

Индексы для observability-правил определяются настройками приложения (например, Metrics indices на странице Settings Infrastructure), а не параметрами правила.

### Machine learning и Security rules

* **ML rules** (Beta) — проверка результатов anomaly detection jobs; создаются в ML app.
* **Security rules** — pre-built и custom detection rules; создаются только в Security app, алерты видны только в Elastic Security (consumer `siem`).

### Experimental alerting system (ES|QL, 9.5+)

С 9.5 доступна экспериментальная система алертинга на ES|QL: каждое совпадение записывается как rule event, события группируются в alert episodes. Action policies поддерживают frequency: on status change, at most once every <interval>, on status change + repeat at interval. Статус: Experimental — не использовать в production.

## Создание правил (API)

Базовый endpoint: `POST /api/alerting/rule` (Kibana, порт 5601). Для не-default Kibana Space: `/s/<space_id>/api/alerting/rule`. Обязательные поля: `name`, `rule_type_id`, `consumer`, `schedule`, `params`. Поля `rule_type_id` и `consumer` неизменяемы после создания — для изменения нужно удалить и создать правило заново.

### 1. Index threshold

```bash
POST /api/alerting/rule
{
  "name": "High Error Rate",
  "rule_type_id": ".index-threshold",
  "consumer": "stackAlerts",
  "enabled": true,
  "tags": ["production"],
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
    "timeWindowUnit": "m",
    "alertOnNoData": false,
    "alertOnGroupDisappear": false
  },
  "actions": [
    {
      "id": "<slack-connector-id>",
      "group": "threshold met",
      "params": {
        "message": "High error count for {% raw %}{{context.group}}{% endraw %}: {% raw %}{{context.value}}{% endraw %}"
      },
      "frequency": {
        "notify_when": "onActionGroupChange"
      }
    }
  ],
  "schedule": { "interval": "1m" }
}
```

Параметры: `aggType` — `count` | `average` | `sum` | `min` | `max` (для агрегаций, кроме count, требуется `aggField`); `groupBy` — `all` (одна группа) или `top` (группировка по `termField`, до `termSize` значений); `thresholdComparator` — `>` | `>=` | `<` | `<=` | `between` | `not between` (для between/not between `threshold` — массив из двух значений); `alertOnNoData` — алерт при отсутствии данных; `alertOnGroupDisappear` — алерт при исчезновении группы.

### 2. Elasticsearch query (DSL / KQL / Lucene / ES|QL)

```bash
POST /api/alerting/rule
{
  "name": "Critical Errors",
  "rule_type_id": ".es-query",
  "consumer": "stackAlerts",
  "params": {
    "searchType": "esQuery",
    "index": ["logs-*"],
    "timeField": "@timestamp",
    "size": 100,
    "esQuery": "{\"size\":0,\"query\":{\"bool\":{\"must\":[{\"term\":{\"level\":\"CRITICAL\"}},{\"range\":{\"@timestamp\":{\"gte\":\"now-5m\"}}}]}}}",
    "thresholdComparator": ">",
    "threshold": [0],
    "timeWindowSize": 5,
    "timeWindowUnit": "m"
  },
  "actions": [
    {
      "id": "<pagerduty-connector-id>",
      "group": "query matched",
      "params": {
        "severity": "critical",
        "description": "Critical errors detected"
      },
      "frequency": { "notify_when": "onActionGroupChange" }
    }
  ],
  "schedule": { "interval": "1m" }
}
```

`searchType`: `esQuery` (Query DSL — используются только поля `query`, `fields`, `_source`, `runtime_mappings`), `esqlQuery` (ES|QL, GA в правиле с 9.2), `kql`, `lucene` (для KQL/Lucene задаётся data view вместо `index`). Для DSL/KQL/Lucene задаются `groupBy`/`termField`/`termSize` и агрегация; для ES|QL — time field и группировка.

### 3. Metrics threshold (Observability)

```bash
POST /api/alerting/rule
{
  "name": "High CPU Usage",
  "rule_type_id": "metrics.alert.threshold",
  "consumer": "metrics",
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
    "groupBy": "host.name",
    "aggregation": "avg",
    "timeSize": 5,
    "timeUnit": "m",
    "alertOnNoData": false,
    "alertOnGroupDisappear": false
  },
  "actions": [
    {
      "id": "<slack-connector-id>",
      "group": "threshold met",
      "params": {
        "message": "High CPU on {% raw %}{{context.group}}{% endraw %}: {% raw %}{{context.value}}{% endraw %}"
      },
      "frequency": { "notify_when": "onActionGroupChange" }
    }
  ],
  "schedule": { "interval": "1m" }
}
```

Индексный паттерн не задаётся — он выводится из настроек Metrics indices (Infrastructure > Settings). Поле `system.cpu.total.norm.pct` дробное (0.9 = 90%).

### 4. APM и Uptime правила

APM-правила (Anomaly, Error count threshold, Failed transaction rate threshold, Latency threshold) и Uptime-правила (monitor status, TLS, ICMP, latency) создаются в соответствующих Kibana-приложениях (Applications / Observability), а не через stack API. Их `rule_type_id` (например, `xpack.uptime.alerts.actionGroups.tls`) и параметры возвращает `GET /api/alerting/rule_types`.

### Дополнительные параметры правила

* `alert_delay` — задержка создания алерта (например, `"5m"`), позволяет дождаться самовосстановления.
* `flapping` — настройка детектирования flapping для правила (глобальные настройки — Rules > Settings > Alert flapping detection, включено по умолчанию).
* `tags` — теги для фильтрации в UI и API.

## Actions и connectors

### Action frequency

Frequency задаётся **на каждом action** (rule-level `notify_when`/`throttle` deprecated: при редактировании правила в UI они конвертируются в per-action значения):

| `notify_when` | Поведение |
|---|---|
| `onActionGroupChange` | Action запускается при изменении статуса алерта (active ↔ recovered) |
| `onActiveAlert` | Action запускается при активации и на каждом check interval, пока условие выполняется |
| `onThrottleInterval` | Action запускается при активации и с интервалом `throttle`, пока условие выполняется |

Дополнительно: `throttle` — интервал повторных уведомлений (`"1h"`); `summary: true` — alert summaries (поддерживается частью rule types: вместо уведомления на каждый алерт — сводка за интервал).

### Connector API

```bash
# Создать
POST /api/actions/connector
# Список
GET /api/actions/connector
# Получить / обновить / удалить
GET|PUT|DELETE /api/actions/connector/<connector-id>
# Типы connectors (список доступных .slack, .email, …)
GET /api/actions/connector_types
# Тест connector'а (проверка connectivity и credentials)
POST /api/actions/connector/<connector-id>/_execute
```

### Типы connectors

| `connector_type_id` | Назначение | Ключевые поля |
|---|---|---|
| `.slack` | Slack (webhook или bot token) | `secrets.webhookUrl` (webhook); v2 — bot token с actions: post message, search messages, list channels, resolve channel ID, lookup user |
| `.email` | Email (Gmail, Outlook, Amazon SES, custom SMTP) | `config.service`, `from`, `host`, `port`, `secure`; `secrets.user`, `secrets.password` (app password при 2FA) |
| `.pagerduty` | PagerDuty events v2 | `secrets.routingKey` |
| `.webhook` | Произвольный HTTP | `config.url`, `method`, `headers`; `secrets` — отдельно |
| `.index` | Запись алерта в индекс ES | `config.index` |
| `.server-log` | Запись в лог Kibana | — |
| `.servicenow`, `.jira`, `.opsgenie`, `.teams`, `.ibm-resilient` | ITSM/тикет-системы | см. документацию connector'а |
| Integration-connectors (Datadog, Zendesk, Kubernetes, …) | Внешние интеграции | см. `GET /api/actions/connector_types` |

### Примеры connectors

```bash
# Slack (webhook)
POST /api/actions/connector
{
  "name": "Slack Alerts",
  "connector_type_id": ".slack",
  "secrets": {
    "webhookUrl": "https://hooks.slack.com/services/xxx/yyy/zzz"
  }
}

# Email (custom SMTP)
POST /api/actions/connector
{
  "name": "Email Alerts",
  "connector_type_id": ".email",
  "config": {
    "service": "other",
    "from": "alerts@company.com",
    "host": "smtp.company.com",
    "port": 587,
    "secure": false
  },
  "secrets": {
    "user": "alerts@company.com",
    "password": "app-password"
  }
}

# PagerDuty
POST /api/actions/connector
{
  "name": "PagerDuty",
  "connector_type_id": ".pagerduty",
  "secrets": {
    "routingKey": "your-routing-key"
  }
}

# Webhook (secrets хранятся отдельно от config, а не интерполируются в headers)
POST /api/actions/connector
{
  "name": "Custom Webhook",
  "connector_type_id": ".webhook",
  "config": {
    "url": "https://api.company.com/alerts",
    "method": "POST",
    "headers": { "Content-Type": "application/json" }
  },
  "secrets": {
    "token": "your-token"
  }
}

# Index (запись алерта в индекс)
POST /api/actions/connector
{
  "name": "Index Alerts",
  "connector_type_id": ".index",
  "config": { "index": "alerts-history" }
}

# Server log
POST /api/actions/connector
{
  "name": "Kibana Log",
  "connector_type_id": ".server-log"
}
```

## Управление правилами

### Lifecycle API

| Операция | Endpoint |
|---|---|
| Создать | `POST /api/alerting/rule` |
| Список / поиск | `GET /api/alerting/rule`, `GET /api/alerting/rules/_find` |
| Получить | `GET /api/alerting/rule/<rule-id>` |
| Обновить | `PUT /api/alerting/rule/<rule-id>` (полное тело; 409 Conflict — кто-то изменил правило, перечитать и повторить) |
| Удалить | `DELETE /api/alerting/rule/<rule-id>` |
| Включить / выключить | `POST /api/alerting/rule/<rule-id>/_enable` / `_disable` |
| Mute всех алертов правила | `POST /api/alerting/rule/<rule-id>/_mute_all` / `_unmute_all` |
| Mute одного алерта | `POST /api/alerting/rule/<rule-id>/alert/<alert-id>/_mute` / `_unmute` |
| Snooze (расписание пауз) | `POST /api/alerting/rule/<rule-id>/snooze_schedule`; удаление — `DELETE /api/alerting/rule/<rule-id>/snooze_schedule/<schedule-id>` |
| Ротация API key правила | `POST /api/alerting/rule/<rule-id>/_update_api_key` |
| Типы правил | `GET /api/alerting/rule_types` |
| Состояние правила (internal) | `GET /internal/alerting/rule/<rule-id>/state` |

Mute и snooze — механизмы maintenance windows: mute подавляет actions для алертов правила, snooze задаёт расписание пауз (например, окно обслуживания). Acknowledge алерта (триаж, `kibana.alert.workflow_status: acknowledged`) доступен с 9.4 в UI Alerts.

## Alert store

### Индексы

* Алиас: `.alerts-<context>.alerts-<space-id>` — например, `.alerts-default` (default context, default space), `.alerts-security.alerts-default` (security). Алиас указывает на все алерты space'а — рекомендуется для запросов.
* Внутренний индекс: `.internal.alerts-<context>.alerts-default-000001`.
* ILM-политика `.alerts-ilm-policy`: rollover через 30 дней или при 50 GB. Маппинги — component templates `.alerts-framework-mappings`, `.alerts-ecs-mappings`, `.alerts-legacy-alert-mappings`.
* Индексы — системные: не изменяйте маппинги (сломает выполнение правил); для пользовательских полей используйте runtime fields.
* Legacy: в 7.x существовали отдельные `.alerts-*` (active) и `.alerts-history-*`; в alerts-as-data (8.x+) все алерты (active и recovered) хранятся в одних индексах `.alerts-*`.

### Поля alert-документа

| Поле | Значение |
|---|---|
| `kibana.alert.rule.name` / `.id` / `.rule_type_id` / `.consumer` | Имя / ID / тип / consumer правила |
| `kibana.alert.uuid` | UUID алерта |
| `kibana.alert.status` | Системный статус: `active`, `recovered`, `flapping` |
| `kibana.alert.workflow_status` | Triage: `open`, `acknowledged`, `closed` |
| `kibana.alert.severity` / `kibana.alert.risk_score` | Severity (low/medium/high/critical) и risk score (0–100) — где применимо |
| `kibana.alert.instance.id` | ID alert instance в рамках выполнения правила |
| `kibana.alert.threshold.value` | Порог, который был превышен |
| `@timestamp` | Время создания алерта |

### Запросы

```bash
# Активные алерты
GET .alerts-*/_search
{
  "query": { "term": { "kibana.alert.status": "active" } }
}

# Алерты по правилу (с сортировкой по времени)
GET .alerts-*/_search
{
  "query": { "term": { "kibana.alert.rule.name": "High Error Rate" } },
  "sort": [{ "@timestamp": "desc" }],
  "size": 100
}

# Топ-10 правил по числу открытых алертов (ES|QL)
FROM .alerts-*
| WHERE kibana.alert.workflow_status == "open"
| STATS count = COUNT(*) BY kibana.alert.rule.name
| SORT count DESC
| LIMIT 10

# Число срабатываний по правилам за сутки
GET .alerts-*/_search
{
  "size": 0,
  "query": { "range": { "@timestamp": { "gte": "now-1d" } } },
  "aggs": {
    "by_rule": { "terms": { "field": "kibana.alert.rule.name", "size": 20 } }
  }
}
```

## Watcher (legacy, Platinum)

### Настройки

`elasticsearch.yml` (secure settings — в keystore):

```yaml
# Отключить Watcher на узле (static)
xpack.watcher.enabled: true
# Шифрование чувствительных данных в watch'ах (static; требует encryption_key)
xpack.watcher.encrypt_sensitive_data: false
# xpack.watcher.encryption_key: <путь к файлу с ключом>  (secure setting)
# Глобальный throttle по умолчанию (dynamic)
xpack.watcher.execution.default_throttle_period: 15m

# Email-аккаунт для email actions (динамические настройки)
xpack.notification.email.account:
  company_account:
    profile: standard
    smtp:
      auth: true
      starttls.enable: true
      host: smtp.company.com
      port: 587
      user: watcher@company.com
      # пароль — secure setting:
      # bin/elasticsearch-keystore add xpack.notification.email.account.company_account.smtp.secure_password
xpack.notification.email.default_account: company_account
# Разрешённые получатели (default ["*"] — все)
xpack.notification.email.allowed_recipients: ["*@company.com"]
# Санитизация HTML в email (по умолчанию включена)
xpack.notification.email.html.sanitization.enabled: true
```

### Структура watch

```json
{
  "trigger": { "schedule": { "interval": "10m" } },
  "input": { "search": { "request": { "indices": ["logs-*"], "body": { "size": 0, "query": { "match_all": {} } } } } },
  "condition": { "compare": { "ctx.payload.hits.total": { "gt": 100 } } },
  "transform": { "search": { "request": { "indices": ["logs-*"], "body": { "size": 10, "query": { "match_all": {} } } } } },
  "actions": {
    "log_alert": { "logging": { "text": "..." } },
    "email_admin": { "email": { "to": "admin@company.com", "subject": "Alert" } }
  }
}
```

Компоненты: `trigger` (schedule: interval, daily, weekly, monthly, yearly, cron); `input` — `search`, `simple`, `http`, `chain`; `condition` — `compare`, `array_compare`, `script`, `always`, `never`; `transform` (опц.) — `search`, `simple`, `script`, `chain`; `actions` — `email`, `webhook`, `index`, `logging`, `slack`, `pagerduty`, `jira`.

### Создание watch

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
      "throttle_period": "15m",
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
# Запуск вручную (record_execution=true — записать выполнение в историю)
POST _watcher/watch/high-error-rate/_execute?record_execution=true
# Принудительное выполнение actions без условия (тестирование)
POST _watcher/watch/high-error-rate/_execute
{ "action_modes": { "_all": "force_execute" } }

# Статус Watcher (watch_count, queued_watches, ...)
GET _watcher/stats

# Активация / деактивация
PUT _watcher/watch/high-error-rate/_activate
PUT _watcher/watch/high-error-rate/_deactivate

# Получить watch (включая _status с состоянием actions)
GET _watcher/watch/high-error-rate

# Удаление (из .watches; записи истории не удаляются)
DELETE _watcher/watch/high-error-rate

# Настройки индекса .watches (replicas, routing)
GET _watcher/settings
PUT _watcher/settings
{ "index.number_of_replicas": 1 }
```

### Ack и throttle

* `throttle_period` на action — Watcher не выполняет action повторно в течение периода (отсчёт: `now - throttling period`).
* **Ack watch API** — ручное подтверждение: `POST _watcher/watch/<id>/_ack` (или `/action1,action2` для выбора). Ack'нутый action остаётся подавленным, пока условие watch'а не перестанет выполняться (состояние `acked` → `awaits_successful_execution`). Состояния: `awaits_successful_execution` → `ackable` (условие выполнилось) → `acked`.
* Watcher поддерживает только асинхронную (pull-модель) проверку условий — синхронной репликации/алертинга нет.

### История выполнения

Записи выполнения хранятся в `.watcher-history-*` (по одной записи на выполнение). Удаление watch'а не удаляет его историю. Для retention настраивайте ILM на `.watcher-history-*`.

## Kibana Alerting vs Watcher

| Критерий | Kibana Alerting | Watcher |
|---|---|---|
| Выполнение | Kibana (Task Manager, распределённо) | Elasticsearch (internal cluster tasks) |
| UI | Stack Management > Rules, Alerts | Нет (API only; Watcher UI удалён) |
| Условия | Rule types (предопределённые + ES|QL/KQL/DSL) | Произвольные JSON (input/condition/transform) |
| Actions | Connectors (многократное использование, secrets) | Встроенные (email, webhook, slack, pagerduty, jira, index, logging) |
| Тriage алертов | Mute, snooze, acknowledge (9.4+), workflow_status | Ack watch API |
| Хранение алертов | `.alerts-*` (alerts-as-data, ILM 30d/50GB) | `.watcher-history-*` |
| Лицензия | Basic (большинство типов) | Platinum |
| Рекомендация | Да — для новых сценариев | Legacy — для существующих и низкоуровневых сценариев |

**Миграция Stack Monitoring:** Watcher-based «cluster alerts» Stack Monitoring пересозданы как правила Kibana Alerting. Настройка `monitoring.cluster_alerts.email_notifications.email_address` больше не работает — измените Stack Monitoring rule и выберите connector в Actions.

## Use Cases

1. **Ops-алертинг на метрики кластера** — index threshold по `.monitoring-es-*` (heap, CPU, disk) или metrics threshold; критичное — PagerDuty, warning — Slack.
2. **Error rate / latency сервисов** — `.es-query` по логам или APM latency threshold; группировка по `service.name`.
3. **Доступность сервисов** — Uptime monitor status rules (down/up, TLS certificate expiration).
4. **DR и capacity** — алерты на unassigned shards, red/yellow cluster status, заполнение диска (см. [Stack Monitoring](./elasticsearch_stack_monitoring.md) и [Disaster Recovery](./elasticsearch_disaster_recovery.md)).
5. **Аудит и compliance** — запись алертов в индекс через `.index` connector для долгосрочного хранения и отчётности.

## Операции и команды (API)

### Kibana Alerting API (Kibana :5601)

| Операция | Метод | Endpoint |
|---|---|---|
| Create rule | POST | `/api/alerting/rule` |
| List / find rules | GET | `/api/alerting/rule`, `/api/alerting/rules/_find` |
| Get / update / delete rule | GET / PUT / DELETE | `/api/alerting/rule/<id>` |
| Enable / disable | POST | `/api/alerting/rule/<id>/_enable`, `/_disable` |
| Mute all / unmute all | POST | `/api/alerting/rule/<id>/_mute_all`, `/_unmute_all` |
| Mute / unmute alert | POST | `/api/alerting/rule/<rule-id>/alert/<alert-id>/_mute`, `/_unmute` |
| Snooze schedule | POST / DELETE | `/api/alerting/rule/<id>/snooze_schedule`, `/api/alerting/rule/<id>/snooze_schedule/<schedule-id>` |
| Rotate rule API key | POST | `/api/alerting/rule/<id>/_update_api_key` |
| Rule types | GET | `/api/alerting/rule_types` |
| Rule state (internal) | GET | `/internal/alerting/rule/<id>/state` |

### Connectors API (Kibana :5601)

| Операция | Метод | Endpoint |
|---|---|---|
| Create / list | POST / GET | `/api/actions/connector` |
| Get / update / delete | GET / PUT / DELETE | `/api/actions/connector/<id>` |
| Connector types | GET | `/api/actions/connector_types` |
| Test connector | POST | `/api/actions/connector/<id>/_execute` |

### Watcher API (Elasticsearch :9200)

| Операция | Метод | Endpoint |
|---|---|---|
| Create / update / get / delete watch | PUT / GET / DELETE | `_watcher/watch/<id>` |
| Execute watch | POST | `_watcher/watch/<id>/_execute` |
| Activate / deactivate | PUT | `_watcher/watch/<id>/_activate`, `/_deactivate` |
| Ack watch | POST | `_watcher/watch/<id>/_ack` |
| Watcher stats | GET | `_watcher/stats` |
| Watcher index settings | GET / PUT | `_watcher/settings` |

### Настройки (kibana.yml / elasticsearch.yml)

| Настройка | Default | Назначение |
|---|---|---|
| `xpack.alerting.rules.run.timeout` | `5m` | Таймаут выполнения правила; превысившие правила отменяются (alerts/actions отбрасываются при `cancelAlertsOnRuleTimeout: true`) |
| `xpack.alerting.rules.run.ruleTypeOverrides` | — | Переопределение timeout/limits по rule type (например, `.index-threshold`: `10m`) |
| `xpack.alerting.rules.run.alerts.max` | `1000` | Макс. алертов за выполнение правила |
| `xpack.alerting.rules.run.actions.max` | — | Макс. actions за выполнение (per connector type — `connectorTypeOverrides`) |
| `xpack.alerting.rules.maxScheduledPerMinute` | `32000` | Макс. правил в минуту (400 правил с интервалом 1m или 2000 с 5m) |
| `xpack.alerting.rules.minimumScheduleInterval.value` / `.enforce` | `1m` / `false` | Минимальный интервал правил (рекомендуемый — 1m); `enforce: true` запрещает создание правил с меньшим интервалом |
| `xpack.alerting.cancelAlertsOnRuleTimeout` | `true` | Отбрасывать alerts/actions при таймауте правила |
| `xpack.alerting.invalidateApiKeysTask.interval` / `.removalDelay` | `5m` | Периодичность инвалидации API keys правил |
| `xpack.task_manager.poll_interval` | `500ms` | Интервал опроса задач (мин. 100ms) |
| `xpack.task_manager.max_workers` | `10` | Макс. одновременных задач на инстанс Kibana (макс. 100) |
| `xpack.task_manager.max_attempts` | `3` | Повторные попытки неудавшейся задачи |
| `xpack.actions.responseTimeout` | — | Таймаут запросов к внешним ресурсам |
| `xpack.actions.maxAttempts` | — | Повторы action (1–10) |
| `xpack.actions.queued.max` | `1000000` | Макс. queued actions |
| `xpack.actions.run.connectorTypeOverrides` | — | Переопределение maxAttempts по connector type |
| `xpack.watcher.enabled` | `true` | Watcher на узле (static) |
| `xpack.watcher.execution.default_throttle_period` | — | Глобальный throttle Watcher (dynamic) |

### Проверка работоспособности

```bash
# 1. Правило создано и включено
GET /api/alerting/rule/<rule-id>
# → "enabled": true, "execution_status": { "last_run": { ... } }

# 2. Connector работает
POST /api/actions/connector/<connector-id>/_execute
# → 200 и ответ целевой системы

# 3. Алерты пишутся в alert store
GET .alerts-*/_search
{ "query": { "term": { "kibana.alert.rule.name": "<rule-name>" } } }

# 4. Watcher выполняется
GET _watcher/stats
# → "stats": { "watch_count": N, ... }
GET _watcher/watch/<watch-id>
# → "_status": { "state": { "active": true }, "actions": { ... } }
```

Если правила не выполняются вовсе или отстают от расписания — проверьте подсистему исполнения: `GET /api/task_manager/_health` (интерпретация полей — в [Эксплуатации Kibana](../Kibana/kibana_production_operations.md)).

## Troubleshooting

| Проблема | Причина | Решение |
|---|---|---|
| Правило не срабатывает | `enabled: false`; неверный `schedule.interval`; условие не выполняется на исторических данных | Проверить `GET /api/alerting/rule/<id>`; проверить params на исторических данных через Discover/ES|QL |
| Правило выполняется, но алертов нет | `alertOnNoData: false` и данных нет; группа исчезла; алерт muted/snoozed | Проверить mute/snooze; включить `alertOnNoData` при необходимости |
| Actions не отправляются | Connector удалён/не настроен; неверные credentials; нет network connectivity; secrets не зашифрованы (нет `xpack.encryptedSavedObjects.encryptionKey`) | `POST /api/actions/connector/<id>/_execute`; проверить логи Kibana (`[actions]`) |
| Правило падает по таймауту | Тяжёлый запрос > 5m | Увеличить `xpack.alerting.rules.run.timeout` или `ruleTypeOverrides`; оптимизировать запрос. В логах: `Cancelling task alerting:.index-threshold ... as it expired` |
| Правила с малым интервалом бегут с опозданием | Интервал < `xpack.task_manager.poll_interval` | Увеличить интервал правила (рекомендуется ≥ 1m) или настроить Task Manager |
| Много правил — дрейф расписания | Task Manager перегружен | `xpack.alerting.rules.maxScheduledPerMinute`, `minimumScheduleInterval.enforce: true`, масштабировать Kibana горизонтально (+20% запаса) |
| Ошибка API key правила | Key истёк/не принадлежит пользователю | `POST /api/alerting/rule/<id>/_update_api_key` |
| 409 Conflict при обновлении | Правило изменено параллельно | Перечитать `GET`, слить изменения, повторить `PUT` |
| Алерты observability/security не видны в Stack Management > Rules | Алерты видны только в приложении-производителе (consumer) | Искать в Observability / Security app |
| Watcher email не отправляется | Не настроен `xpack.notification.email.account` / `default_account` | Настроить email-аккаунт и `default_account`; пароль — в keystore |
| Watcher action не повторяется | `throttle_period` или ack подавляет выполнение | Проверить `GET _watcher/watch/<id>` → `_status.actions.<id>.ack.state`; сброс — ack API или ожидание сброса условия |
| Кластер/Kibana не отвечает из-за алертинга | Экстренная ситуация | Временно: `xpack.task_manager.capacity: 5`, `xpack.task_manager.poll_interval: 1h` (крайняя мера, throttles все background tasks) |

Диагностика: логи Kibana с тегами `[alerting]` и `[actions]`; event log `.kibana-event-log*` (`event.provider: "alerting"`, `event.action: "execute"` — требует `read` на `.kibana-event-log*` или superuser); задачи в логах Task Manager именуются `alerting:<rule_type_id>` и `actions:<connector_type_id>`.

## Best Practices

1. **Группируйте алерты** — `groupBy` по `host.name`/`service.name` вместо глобального порога: один алерт на сущность, а не один на правило.
2. **Пороги на baseline** — настраивайте по историческим данным, не произвольно; используйте warning + critical уровни.
3. **Контекст в message** — включайте `{% raw %}{{context.group}}{% endraw %}`, `{% raw %}{{context.value}}{% endraw %}`, ссылки на дашборды для диагностики.
4. **Frequency для снижения шума** — `onActionGroupChange` для однократного уведомления, `onThrottleInterval` + `throttle` для регулярных напоминаний, alert summaries для сводок.
5. **`alert_delay`** для кратковременных всплесков — алерт создаётся только если условие держится дольше delay.
6. **Maintenance windows** — mute/snooze вместо отключения правил.
7. **Не ставьте интервал < 1m** — `xpack.alerting.rules.minimumScheduleInterval.enforce: true`; правила с интервалом меньше poll_interval Task Manager бегут с опозданием.
8. **Реплика `.kibana_task_manager`** — минимум 1 replica в production; потеря индекса = потеря всех расписаний.
9. **Тестируйте** — `_execute` для connector'ов; правила проверяйте на исторических данных; Watcher — `_execute` с `action_modes: force_execute`.
10. **Откат и очистка** — отключить правило: `_disable` (конфиг сохраняется); удалить: `DELETE /api/alerting/rule/<id>`; удалить connector: `DELETE /api/actions/connector/<id>` (проверьте, что ни одно правило его не использует); очистить алерты — ILM на `.alerts-*` (30d/50GB по умолчанию); для Watcher — `DELETE _watcher/watch/<id>` + ILM на `.watcher-history-*`.

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
└── Info (Email / Index connector)
    ├── Daily Report
    └── Weekly Summary
```

## Ограничения

* Kibana Alerting вычисляет условия в Kibana, а не в Elasticsearch — тяжёлые запросы потребляют ресурсы Kibana и ограничены таймаутом (5m по умолчанию).
* `rule_type_id` и `consumer` неизменяемы после создания правила.
* Алерты observability/security-правил не видны в Stack Management > Rules — только в приложении-производителе.
* Watcher: email actions требуют настроенного `xpack.notification.email`; watch выполняется с привилегиями пользователя, который его сохранил; Watcher не реплицирует конфигурацию между кластерами (watches хранятся в `.watches`).
* CCR не реплицирует Watcher-алерты и system indices (`.security`, `.kibana`) — см. [Cross-Cluster](./elasticsearch_ccr_ccs.md).
* Experimental alerting system (ES|QL, 9.5) — не для production.

## См. также

* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — Alerting UI в Kibana.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — метрики для алертинга; миграция Watcher-алертов мониторинга на Kibana rules.
* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — Watcher API.
* **[Security Advanced](./elasticsearch_security_advanced.md)** — аудит действий.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов.
* **[CCR/CCS](./elasticsearch_ccr_ccs.md)** — что не реплицируется между кластерами.
* Официальная документация: [Kibana alerting](https://www.elastic.co/docs/explore-analyze/alerting/alerts), [Watcher](https://www.elastic.co/docs/explore-analyze/alerting/watcher), [Connectors](https://www.elastic.co/docs/reference/kibana/connectors-kibana).
