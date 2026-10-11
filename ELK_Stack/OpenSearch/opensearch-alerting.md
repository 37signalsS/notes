# Alerting (OpenSearch)

**Актуально для:** OpenSearch 2.x / 3.x

> Мониторинг данных и отправка уведомлений при срабатывании условий: типы мониторов, триггеры, действия, Notifications plugin, работа с алертами. Alerting plugin происходит от Open Distro for Elasticsearch Alerting и по назначению близок к Elasticsearch Watcher. Общая концепция alerting и сравнение с Watcher — в [Elasticsearch Alerting](../Elasticsearch/elasticsearch_alerting.md); аномалии — Anomaly Detection, оповещения по ним — тот же Alerting.

## Определения

* **Monitor** — задание по расписанию: выполняет запрос к индексам или к API кластера, результат передаётся триггерам. API — `_plugins/_alerting/monitors`.
* **Trigger** — условие над результатом монитора (Painless); при истине создаётся alert и запускаются действия.
* **Alert** — событие триггера. Состояния: `ACTIVE` (идёт, не подтверждён), `ACKNOWLEDGED` (подтверждён, причина не устранена), `COMPLETED` (условие больше не выполняется), `ERROR` (сбой триггера или действия), `DELETED` (удалён монитор/триггер). Подробнее — в разделе [Работа с алертами](#работа-с-алертами).
* **Action** — что делать при срабатывании: шаблон сообщения (Mustache) + канал уведомления. Каналом служит конфигурация Notifications (поле действия исторически называется `destination_id`).
* **Destination** — устаревший (до 2.0) механизм хранения каналов; заменён каналами Notifications plugin. См. [Destinations (устарело)](#destinations-устарело).
* **Notifications plugin** — отдельный плагин, управляющий каналами уведомлений (типы: slack, chime, webhook, smtp_account, ses_account, email, email_group, sns, microsoft_teams). Общий для Alerting, Anomaly Detection, ISM.
* **Composite monitor (workflow)** — запуск нескольких мониторов как одного workflow с единой алерт-логикой; API — `_plugins/_alerting/workflows`.

## Как это работает

1. Monitor запускается по расписанию (`period` или cron) как периодическое задание **на data-нодах** кластера.
2. Каждый запуск выполняет extraction query (`inputs[].search` или `inputs[].uri`) за интервал `[period_start, period_end]` и кладёт результат в `ctx.results[0]`.
3. Для каждого триггера вычисляется Painless-условие над `ctx.results[0]`. Первый истинный триггер переводит монитор в состояние «сработал».
4. Создаётся alert (в этой же или следующей итерации, в зависимости от дедупликации) и выполняются действия — уведомления через канал Notifications.
5. Состояние alert пересчитывается на **каждом** запуске монитора: условие выполняется — `ACTIVE`; перестало выполняться — `COMPLETED`; удалён монитор/триггер — `DELETED`.

Важная причина пропущенных срабатываний: монитор считает документы по их `@timestamp` в окне запуска. Если документы индексируются с задержкой (после закрытия окна), в extraction query они не попадут и alert не сработает. Расширяйте окно (`gte` с запасом) или используйте ingest-time надёжнее, чем event-time.

## Типы мониторов

| Тип (`monitor_type`) | Что делает | Когда применять |
|---|---|---|
| `query_level_monitor` | Запускает запрос, оценивает условие по результату целиком; один активный алерт на монитор | Пороговые условия: «> 100 ошибок за 5 минут» |
| `bucket_level_monitor` | Агрегирует результат по бакетам (terms/date_histogram), условие на каждый бакет; дедупликация через `ctx.dedupedAlerts` | «Ошибка в конкретном сервисе» с разбивкой |
| `doc_level_monitor` (input `doc_level_input`) | Находит отдельные документы по условиям — алерт на документ, доступ через `ctx.alerts` | Аудит, Security Analytics: «лог подозрительного действия» |
| `ppl_monitor` | Запрос на Piped Processing Language (PPL); результат в `ctx.ppl_query_results` | Привычный PPL-синтаксис (Observability), до 10 триггеров |
| `cluster_metrics_monitor` | Не по индексам, а API кластера (`_cluster/health` и др.) через input `uri` | Красный кластер, деградация шардов |
| Composite / workflow | Несколько мониторов в одном workflow (`workflow_type: composite`) | Сложные корреляции, единый алерт по нескольким условиям |

Общий лимит: **1000 мониторов** на кластер (`plugins.alerting.monitor.max_monitors`). Уровень важности `severity` — строка от `"1"` (высший) до `"5"` (низший).

## Создание монитора

### Query-level монитор

```bash
POST _plugins/_alerting/monitors
{
  "type": "monitor",
  "name": "High error rate",
  "monitor_type": "query_level_monitor",
  "enabled": true,
  "schedule": {
    "period": { "interval": 5, "unit": "MINUTES" }
  },
  "inputs": [
    {
      "search": {
        "indices": ["logs-*"],
        "query": {
          "size": 0,
          "query": {
            "bool": {
              "filter": [
                { "range": { "@timestamp": { "gte": "now-5m" } } },
                { "term": { "level": "error" } }
              ]
            }
          },
          "aggregations": {
            "by_service": { "terms": { "field": "service", "size": 20 } }
          }
        }
      }
    }
  ],
  "triggers": [
    {
      "name": "too-many-errors",
      "severity": "1",
      "condition": {
        "script": {
          "source": "ctx.results[0].aggregations.by_service.buckets.size() > 0 && ctx.results[0].aggregations.by_service.buckets[0].doc_count > 100",
          "lang": "painless"
        }
      },
      "actions": [
        {
          "name": "notify-slack",
          "destination_id": "<channel-config_id>",
          "message_template": {
            "source": "{{ctx.monitor.name}}: {{ctx.results.0.aggregations.by_service.buckets.0.doc_count}} errors in 5m"
          },
          "subject_template": {
            "source": "Errors in {{ctx.results.0.aggregations.by_service.buckets.0.key}}"
          }
        }
      ]
    }
  ]
}
# → { "_id": "..." }
```

Разбор полей:

* `schedule.period` — интервал (`interval` + `unit`: MINUTES, HOURS, DAYS…); для отдельных типов поддерживается cron-расписание.
* `inputs[].search.query` — обычный Query DSL (см. [Query DSL](./opensearch-query-dsl-search.md)); результат попадает в `ctx.results[0]`. Используйте `size: 0` вместе с `aggregations`, когда условие оценивает метрику, а не документы.
* `condition.script.source` — Painless-выражение над `ctx.results[0]`; истина → alert. Для списков используйте `.size()`, а не `.length`.
* `severity` — строковый уровень `"1"`…`"5"` (1 — высший).
* `actions[].destination_id` — id канала Notifications (значение = `config_id` канала).
* `actions[].message_template` / `actions[].subject_template` — шаблоны (Mustache) тела и темы; поля `source` и опциональный `lang: "mustache"`. Поля `title` у `message_template` **нет** — тема задаётся через `subject_template`.

### Переменные контекста

Доступность зависит от контекста: Painless-условие использует `[0]`, Mustache-шаблон — доступ через точку (`.0`).

| Переменная | Контекст | Содержимое |
|---|---|---|
| `ctx.results[0]` / `{{ctx.results.0}}` | оба | результат extraction query (hits/агрегации). Пусто, если запрос не удался — см. `ctx.error` |
| `ctx.periodStart` / `ctx.periodEnd` | оба | границы окна текущего запуска |
| `ctx.error` | оба | текст ошибки выполнения, иначе `null` |
| `ctx.monitor` | оба | имя, id, `type`, `enabled`, `schedule`, `inputs` монитора |
| `ctx.trigger` | оба | имя, id, `severity`, `condition`, `actions` триггера |
| `ctx.alert` | условие | текущий активный алерт (`id`, `version`, `isAcknowledged`); `null`, если нет — только query-level |
| `ctx.newAlerts` / `ctx.dedupedAlerts` / `ctx.completedAlerts` | условие | новые / уже существующие (dedup) / закрываемые алерты — bucket-level |
| `ctx.alerts` | условие | алерты по документам — doc-level (доступ к `sample_documents`, `finding_ids`) |
| `ctx.ppl_query_results` / `{{ctx.ppl_query_results.size}}` | оба | строки результата PPL-монитора (массив map) |

### Монитор кластерных метрик

```bash
POST _plugins/_alerting/monitors
{
  "name": "Cluster health red",
  "type": "monitor",
  "monitor_type": "cluster_metrics_monitor",
  "enabled": true,
  "schedule": { "period": { "unit": "MINUTES", "interval": 1 } },
  "inputs": [
    {
      "uri": {
        "api_type": "CLUSTER_HEALTH",
        "path": "_cluster/health/",
        "path_params": "",
        "url": "http://localhost:9200/_cluster/health/"
      }
    }
  ],
  "triggers": [
    {
      "name": "red-status",
      "severity": "1",
      "condition": { "script": { "source": "ctx.results[0].status == 'red'", "lang": "painless" } },
      "actions": [ ... ]
    }
  ]
}
```

Список доступных `api_type` и полей ответа для cluster metrics ограничен allow-list файлом `supported_json_payloads.json` плагина.

### PPL-монитор

PPL-мониторы используют объекты `ppl_trigger` (не Painless-условия), типов `number_of_results` и `custom`. Результат доступен в `ctx.ppl_query_results`.

```bash
POST _plugins/_alerting/monitors
{
  "name": "PPL Error Rate Monitor",
  "type": "monitor",
  "monitor_type": "ppl_monitor",
  "enabled": true,
  "schedule": { "period": { "unit": "MINUTES", "interval": 5 } },
  "inputs": [
    {
      "ppl_input": {
        "query": "source = application_logs | where level = 'ERROR' | stats count() as error_count by service",
        "query_language": "ppl"
      }
    }
  ],
  "triggers": [
    {
      "ppl_trigger": {
        "name": "Too many errors",
        "severity": "1",
        "type": "number_of_results",
        "num_results_condition": ">",
        "num_results_value": 1,
        "actions": [
          {
            "name": "Notify ops channel",
            "destination_id": "<channel-config_id>",
            "message_template": {
              "source": "Monitor {{ctx.monitor.name}} detected {{ctx.ppl_query_results.size}} services with errors."
            },
            "subject_template": { "source": "Alert: High Error Rate Detected" }
          }
        ]
      }
    }
  ]
}
```

## Уведомления

### Destinations (устарело)

> **Статус:** Destinations объявлены устаревшими в OpenSearch 2.0 и заменены каналами Notifications.
> Операции создания, обновления и удаления destinations удалены в том же релизе; существующие destinations
> автоматически мигрированы в каналы. Работают только операции чтения — для записей, которые не мигрировали.
> Для новых конфигураций используйте Notifications plugin.

```bash
# Только чтение (для не мигрировавших записей)
GET _plugins/_alerting/destinations
GET _plugins/_alerting/destinations/<id>
```

`POST`/`PUT`/`DELETE` для `_plugins/_alerting/destinations` в 2.x/3.x недоступны.

### Каналы Notifications (актуальный способ)

Конфигурации каналов хранятся отдельно и переиспользуются всеми плагинами (Alerting, Anomaly Detection, ISM):

```bash
# Создание конфигурации канала
POST _plugins/_notifications/configs
{
  "config": {
    "name": "ops-slack",
    "description": "Ops notifications",
    "config_type": "slack",
    "is_enabled": true,
    "slack": { "url": "https://hooks.slack.com/services/T000/B000/XXXX" }
  }
}
# → { "config_id": "..." }

# Тест канала
POST _plugins/_notifications/feature/test/<config_id>

# Список / получение по id
GET _plugins/_notifications/configs
GET _plugins/_notifications/configs/<config_id>

# Список поддерживаемых типов
GET _plugins/_notifications/features
```

Типы `config_type`: `slack`, `chime`, `webhook`, `smtp_account` (SMTP для e-mail), `ses_account`, `email`, `email_group`, `sns`, `microsoft_teams`. В действиях монитора канал задаётся тем же полем **`destination_id`**, значением которого служит `config_id` канала Notifications — историческое имя поля сохранилось после миграции destinations → channels. Поле `is_enabled` по умолчанию `true`; повторный `config_id` даёт `409 Conflict` (обновление — через `PUT`).

## Composite-мониторы (workflows)

Composite-монитор выполняет **delegate-мониторы** последовательно (по `order`) и генерирует **chained alert**, когда условия связанных audit-алертов выполняются. До 25 delegate-мониторов; query-level мониторы не могут участвовать в chained findings.

```bash
POST _plugins/_alerting/workflows
{
  "type": "workflow",
  "name": "scale_up",
  "workflow_type": "composite",
  "enabled": true,
  "schedule": { "period": { "interval": 1, "unit": "MINUTES" } },
  "inputs": [
    {
      "composite_input": {
        "sequence": {
          "delegates": [
            { "order": 1, "monitor_id": "grsbCIcBvEHfkjWFeCqb" },
            { "order": 2, "monitor_id": "agasbCIcBvEHfkjWFeCqa" }
          ]
        }
      }
    }
  ],
  "triggers": [
    {
      "chained_alert_trigger": {
        "id": "m1ANDm2",
        "name": "both firing",
        "severity": "1",
        "condition": {
          "script": {
            "source": "(monitor[id=grsbCIcBvEHfkjWFeCqb] && monitor[id=agasbCIcBvEHfkjWFeCqa])",
            "lang": "painless"
          }
        }
      },
      "actions": [ ... ]
    }
  ]
}
```

Порядок мониторов в Painless-условии не задаёт последовательность выполнения — её задаёт `delegates.order`. Логические операторы: `&&`, `||`, `!`, приоритет — скобками.

```bash
# Ручной прогон workflow
POST _plugins/_alerting/workflows/<workflow_id>/_execute

# Chained-алерты workflow (плюс связанные audit-алерты)
GET _plugins/_alerting/workflows/alerts?workflowIds=<id>&getAssociatedAlerts=true
```

## Работа с алертами

```bash
# Все алерты (фильтры и пагинация через query-параметры)
GET _plugins/_alerting/monitors/alerts?size=20&alertState=ACTIVE

# Алерты конкретного монитора
GET _plugins/_alerting/monitors/alerts?monitorId=<monitor_id>

# Подтвердить (acknowledge) — несколько id одним вызовом
POST _plugins/_alerting/monitors/<monitor_id>/_acknowledge/alerts
{
  "alerts": ["eQURa3gBKo1jAh6qUo49", "..."]
}
# → { "success": ["..."], "failed": [] }

# Управление монитором
GET    _plugins/_alerting/monitors/<monitor_id>
PUT    _plugins/_alerting/monitors/<monitor_id>      # обновление (version)
DELETE _plugins/_alerting/monitors/<monitor_id>
POST   _plugins/_alerting/monitors/_search            # поиск мониторов (Query DSL)

# Статистика подсистемы
GET _plugins/_alerting/stats

# Ручной прогон (диагностика); ?dryrun=true — без создания алертов и действий
POST _plugins/_alerting/monitors/<monitor_id>/_execute?dryrun=true
```

Query-параметры `GET _plugins/_alerting/monitors/alerts`: `sortString`, `sortOrder`, `size` (default 20), `startIndex`, `searchString`, `severityLevel`, `alertState`, `monitorId`, `workflowIds` (только 2.9+). Ответ содержит `alerts[]` (с полями `monitor_id`, `trigger_id`, `state`, `severity`, `error_message`, `alert_history`) и `totalAlerts`.

Жизненный цикл alert:

1. Действия выполнены успешно → alert создаётся в `ACTIVE` (в индексе `.opendistro-alerting-alerts`).
2. Сбой действия или триггера → alert создаётся в `ERROR`.
3. Пользователь подтверждает → `ACKNOWLEDGED` (уведомления прекращаются, если действие по триггеру зависит от состояния; применяется также для починки `ERROR`).
4. Условие триггера перестало выполняться → `COMPLETED`; монитор/триггер удалён → `DELETED`. Оба состояния переносят alert в `.opendistro-alerting-alert-history-*`.

Управление через Dashboards: `Alerting → Monitors → Create monitor`. В OpenSearch Dashboards 3.x есть **Unified alerts view** (`Observability → Alerts`): единый список алертов мониторов и Prometheus-правил с состояниями `active`, `pending`, `acknowledged`, `silenced`, `resolved`, `error` и уровнями `critical`, `high`, `medium`, `low`, `info`; из него можно подтверждать активные OpenSearch-алерты (Prometheus-часть доступна только для чтения).

## Хранение и настройки

| Индекс / alias | Назначение |
|---|---|
| `.opendistro-alerting-config` | определения мониторов, триггеров, действий |
| `.opendistro-alerting-alerts` | активные алерты |
| `.opendistro-alerting-alert-history-*` | завершённые (`COMPLETED`/`DELETED`) алерты |
| `.opendistro-alerting-alert-history-write` | write-alias истории (основа для rollover) |

Ключевые настройки (динамические, `PUT _cluster/settings`):

| Настройка | Default | Назначение |
|---|---|---|
| `plugins.alerting.monitor.max_monitors` | 1000 | максимум мониторов на кластер |
| `plugins.alerting.monitor.max_triggers` | 10 (макс. 50) | триггеров на монитор |
| `plugins.alerting.monitor.max_ppl_triggers` | 10 (макс. 10) | триггеров на PPL-монитор |
| `plugins.alerting.max_actionable_alert_count` | 50 | макс. число actionable alerts |
| `plugins.alerting.alert_history_enabled` | true | включить историю алертов |
| `plugins.alerting.alert_history_rollover_period` | 12h | период проверки rollover истории |
| `plugins.alerting.alert_history_max_age` | 30d | макс. возраст документа в индексе истории |
| `plugins.alerting.alert_history_max_docs` | 1000 | макс. алертов в индексе истории |
| `plugins.alerting.alert_history_retention_period` | 60d | срок хранения истории до автоудаления |

Настройка требует прав на Cluster Settings API; роль `alerting_full_access` покрывает операции с мониторами, но не управление cluster settings.

## Troubleshooting

### Монитор не срабатывает

1. `GET _plugins/_alerting/monitors/<id>` — `enabled: true`, schedule корректен.
2. `POST _plugins/_alerting/monitors/<id>/_execute?dryrun=true` — ручной прогон: в ответе видно `input_results` и результат каждого триггера (`triggered`), без создания алертов.
3. Условие смотрит на `ctx.results[0].*` — при `size: 0` в запросе документы отсутствуют, нужны агрегации; пути к агрегациям должны совпадать с запросом (в ответе ключ `aggregations`, даже если в запросе был `aggs`).
4. Время: расписание в UTC; окно `[period_start, period_end]` — расширяйте `gte` с запасом при задержке индексации.

### Алерт в состоянии Error

1. Причина видна в поле `error_message` alert и в `ctx.error`: ошибка компиляции Painless, null-обращение (отсутствующая агрегация).
2. Проверить действие: недоступный канал/webhook, истёкший токен Slack → алерт остаётся `ERROR`.

### Уведомления не приходят

1. `destination_id` (значение — `config_id` канала) указан верно; проверить тест: `POST _plugins/_notifications/feature/test/<config_id>`.
2. Security: права на `_plugins/_alerting/*` и `_plugins/_notifications/*` (роли `alerting_full_access` / `notifications_full_access`).
3. Сетевой egress с нод — outbound к Slack/webhook закрыт firewall'ом.
4. Пустой `message_template` — канал может отклонить уведомление с пустым телом.

### Дублирующиеся алерты

1. Bucket-level мониторы дедуплицируют алерты (`ctx.dedupedAlerts`) — активный алерт по бакету не создаётся заново, пока условие выполняется.
2. Для query-level активный алерт живёт до acknowledge/completed; «спам» обычно означает флапающее условие — сузить окно или добавить гистерезис в условие.
3. Чрезмерное число actionable alerts ограничено `plugins.alerting.max_actionable_alert_count` (по умолчанию 50).

### Лимит мониторов и триггеров

1. Ошибка при 1001-м мониторе: поднять `plugins.alerting.monitor.max_monitors` (Cluster Settings API) либо объединить мониторы в composite workflow.
2. Ошибка при превышении числа триггеров: `plugins.alerting.monitor.max_triggers` (default 10, максимум 50) и `plugins.alerting.monitor.max_ppl_triggers` (максимум 10).

## Best Practices

1. Запускать мониторы на данных с `size: 0` + агрегации — условие должно читать метрику, а не документы.
2. Согласовать severity-шкалу с дежурством (например `"1"` — page, `"2"` — ticket); severity — строка от `"1"` (высший) до `"5"`.
3. Каналы уведомлений — через Notifications plugin (`config_id`), переиспользовать между Alerting/Anomaly Detection, тестировать `feature/test` перед выкаткой.
4. Условия — с запасом на пустой результат (проверки `ctx.results[0]... != null` и `.size() > 0`), иначе `ERROR` вместо тихого пропуска.
5. Алерты подтверждать (acknowledge), а не закрывать удалением — состояние и история сохраняются.
6. Пороговые мониторы не дублировать: одно условие — один монитор; пересекающиеся мониторы создают шум.
7. Комбинировать с Anomaly Detection: детектор ловит аномалию, Alerting сообщает о ней.
8. Хранить определения мониторов как код (`_search`/`PUT` через CI), а не только через UI.
9. Для корреляций (A и B одновременно) использовать composite workflow, а не самодельную логику в одном мониторе.

## Дополнительная информация

* [Elasticsearch Alerting](../Elasticsearch/elasticsearch_alerting.md) — общая теория alerting, сравнение с Watcher.
* [OpenSearch: Обзор](./opensearch_overview.md) — место Alerting в экосистеме.
* [Query DSL и поиск (OpenSearch)](./opensearch-query-dsl-search.md) — запросы в `inputs[].search`.
* [ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md) — ISM-алерты (отдельный механизм: уведомления по ошибкам политик, без монитора).
* [OpenSearch Alerting API](https://docs.opensearch.org/latest/observing-your-data/alerting/api/) — справочник по endpoint'ам.
