# Kibana: Observability

> **Актуально для:** Kibana 8.19 / 9.x (Applications, Synthetics, SLO; Log Explorer и Logs Stream удалены в 9.0)

Раздел Observability в Kibana закрывает три сигнала — логи, метрики и трейсы — плюс синтетические проверки и SLO. Эта заметка — о выборе инструмента, устройстве SLO, burn rate правилах, private locations и работе через API; теория SLO и методология алертинга вынесены в базовые материалы стека.

## Определения

* **Applications (ранее APM)** — приложение в Kibana для трейсов, сервисов и транзакций: service inventory, Waterfall, errors. В 9.x UI называется **Applications**; APM-правила создаются именно там.
* **Discover** — основной инструмент исследования логов и любых событий; сохранённая Discover session используется на дашбордах и в отчётах.
* **SLO (Service Level Objective)** — целевое значение SLI; в Kibana хранится как объект с SLI-запросом и целевым уровнем, состояние хранится в системных индексах `.slo-observability.sli*` и `.slo-observability.summary*` (переопределить на уровне правила нельзя).
* **Burn rate rule** — правило, срабатывающее, когда скорость расхода error budget превышает порог: считает ошибки, делённые на error budget, в двух окнах — длинном и коротком (равном 1/12 длинного).
* **Synthetics** — синтетические проверки HTTP/TCP/ICMP и browser journey; приёмник устаревшего Uptime (deprecated с 8.15: приложение скрыто без свежих Heartbeat-данных, показывается через Advanced Settings `observability:enableLegacyUptimeApp`; лёгкие мониторы по-прежнему может писать Heartbeat или интеграция Uptime Monitors).
* **Alerts** — централизованный список алертов Observability/Security с фильтрами по severity, groups и статусу.

## Основные концепции

### Какой инструмент для какого сигнала

| Задача | Инструмент Kibana | Примечание |
| :--- | :--- | :--- |
| Исследование логов, ad-hoc расследования | **Discover** (KQL / ES\|QL) | Log Explorer и Logs Stream **удалены в 9.0** — их функцию берёт Discover (с сохранёнными session и background search) |
| Метрики инфраструктуры и сервисов | **Infrastructure / Metrics** | Правила: metric threshold, log threshold |
| Трейсы и APM | **Applications** | Правила: latency, error count, failed transaction rate, APM anomaly |
| Синтетические мониторы | **Synthetics** | Uptime устарел с 8.15 → Synthetics |
| Контроль надёжности | **Observability → SLOs** | SLO + burn rate rule |
| Триаж и реагирование | **Alerts**, Cases, [Workflows](./kibana_workflows.md) | Обогащение и автоматический триаж |

Правила всех этих типов, их `rule_type_id` и consumers — в [Alerting: Kibana Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md) (раздел «Observability rules»). Дублировать таблицу здесь не нужно.

### SLO: требования и устройство

Чтобы создавать SLO и burn rate правила, требуется:

1. Соответствующая лицензия (subscription).
2. Кластер Elasticsearch с нодами, имеющими роли **`transform`** и **`ingest`** — SLO используют transform для пересчёта SLI.
3. Настроенный доступ к SLO (SLO access).

При создании SLO через UI автоматически создаётся **правило burn rate по умолчанию** — с дефолтной конфигурацией и **без connector'а**: для получения уведомлений connector нужно добавить отдельно.

Burn rate правило:

* По умолчанию **4 окна** (windows) — по одному на группу severity; каждое окно задаётся длительностью lookback и порогом burn rate.
* Для каждого окна короткое окно = **1/12 длинного** (например, при long = 1h короткое = 5m) — оно ускоряет восстановление.
* Burn rate = error rate / error budget; алерт срабатывает, когда **оба** окна превысили порог.

### Устройство SLO: что создаёт Kibana

Один SLO — это не только объект в UI, а набор системных ресурсов, которые Kibana создаёт и поддерживает в Elasticsearch:

| Ресурс | Имя / расположение | Назначение |
| :--- | :--- | :--- |
| SLO definition | Saved Object в `.kibana` | Определение SLO: SLI, objective, окно, budgeting method |
| Rollup-трансформ | `slo-{slo.id}-{slo.revision}` | Свёртка SLI-данных в компактный набор документов |
| Rollup ingest pipeline | `slo-observability.sli.pipeline-{slo.id}-{slo.revision}` | Обработка данных rollup'а |
| Итоговый трансформ | `slo-summary-{slo.id}-{slo.revision}` | Текущие значения SLI и error budget для поиска и фильтрации |
| Summary ingest pipeline | `slo-observability.summary.pipeline-{slo.id}-{slo.revision}` | Обработка итоговых данных |
| Индексы | `.slo-observability.sli*`, `.slo-observability.summary*` | Данные SLI и саммари (те же индексные паттерны читает burn rate правило) |

* Изменение SLI-параметров, `objective` или time window поднимает **revision** SLO: трансформы и pipelines переустанавливаются, ранее агрегированные данные SLO удаляются. Правки `name`, `description`, `tags` revision не затрагивают.
* Внутренние ассеты (трансформы, ingest pipelines, шаблоны и индексы `.slo-observability.*`) не редактируются вручную и не переопределяются через index templates — это прямой путь к неверному расчёту SLI.
* Надёжность SLO = здоровье трансформ: при сбое Kibana показывает сообщение «The following transform is in an unhealthy state» со списком трансформов; исходные проблемы обычно — недоступные шарды или отсутствующие роли `transform`/`ingest`.

## Практические сценарии

### Создание и управление SLO через API

API удобен для GitOps и массового заведения SLO. Путь без `/s/{spaceId}` работает в default space; для своего space подставьте свой идентификатор в путь. Требуются `all`-привилегии фичи **SLOs** раздела Observability, для операций изменения — `write`, для чтения — `read`:

```bash
export KBN="https://localhost:5601"
curl -sk -X POST "${KBN}/api/observability/slos" \
  -H 'kbn-xsrf: true' -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "My Service Availability",
    "description": "Availability of my web service measured by successful HTTP responses",
    "budgetingMethod": "occurrences",
    "timeWindow": { "type": "rolling", "duration": "30d" },
    "objective": { "target": 0.99 },
    "indicator": {
      "type": "sli.kql.custom",
      "params": {
        "index": "logs-*",
        "timestampField": "@timestamp",
        "filter": "field.environment : \"production\" and service.name : \"my-service\"",
        "good": "request.status_code : \"2xx\"",
        "total": "request.status_code : *"
      }
    },
    "settings": { "frequency": "5m", "syncDelay": "5m" },
    "tags": ["production", "web-service"]
  }'
# → 200 {"id":"8853df00-ae2e-11ed-90af-09bb6422b258"}
```

* `budgetingMethod` — `occurrences` или `timeslices`; для timeslices дополнительно задаются `objective.timesliceTarget` и `objective.timesliceWindow`.
* `timeWindow.type` — `rolling` (`duration`: `7d`, `30d`, `90d`) или `calendarAligned` (`duration`: `1w`, `1M`).
* `settings.frequency` — период пересчёта SLI (1m–59m, дефолт `1m`); `settings.syncDelay` — задержка относительно сырых данных (1m–359m, дефолт `1m`, должна быть больше refresh interval индекса-источника). Увеличение `syncDelay` откладывает и срабатывание алертов.
* Типы индикаторов: `sli.kql.custom` (KQL good/total), APM availability/latency, custom metric, histogram, timeslice metric.
* Burn rate правило при API-создании **не формируется** — автоматически оно создаётся только при создании SLO через UI; добавьте его отдельно (см. «Создание burn rate правила»).

Операции жизненного цикла (все — с заголовком `kbn-xsrf`; space-варианты путей — `/s/{spaceId}/api/observability/slos/...`):

| Задача | Запрос |
| :--- | :--- |
| Список SLO (постраничный) | `GET /api/observability/slos` |
| Один SLO | `GET /api/observability/slos/{sloId}` |
| Изменение определения | `PUT /api/observability/slos/{sloId}` |
| Удаление SLO вместе с rollup/summary-данными | `DELETE /api/observability/slos/{sloId}` |
| Массовое удаление | `POST /api/observability/slos/_bulk_delete`, статус — `GET /api/slo/_bulk_delete/{taskId}` |
| Сброс error budget / окна и пересборка | `POST /api/observability/slos/{sloId}/_reset` |
| Отключение / включение | `POST /api/observability/slos/{sloId}/disable`, `POST /api/observability/slos/{sloId}/enable` |
| Инвентаризация определений | `GET /internal/observability/slos/_definitions` |

Изменение через `PUT` определения SLI, objective или окна приводит к bump'у revision и пересборке трансформов с удалением старых агрегатов (см. «Устройство SLO»).

### Создание burn rate правила

1. **Observability → Alerts → Manage Rules → Create rule**.
2. Выбрать тип **SLO burn rate**, затем конкретный SLO.
3. Задать окна: `Lookback (hours)`, `Burn rate threshold`, `Action Group` (severity).
4. Задать интервал проверки (например, 1 minute).
5. Добавить действия (connector: email, Slack, Jira, webhook) и сохранить.

Создать то же самое можно из **Observability → SLOs** — «...» напротив SLO → **Create new alert rule**.

### Идентификация типа правила через API

`rule_type_id` для burn rate правила в этой заметке не фиксируется — идентификаторы меняются между минорами. Получите актуальный список:

```bash
curl -sk -u elastic:$PASSWORD "${KBN}/api/alerting/rule_types" -H 'kbn-xsrf: true'
# → массив {"id":"...","name":"...","producer":"...","consumer":"..."}
# отфильтруйте по name/consumer (Observability) и используйте поле id
```

Дальше правило создаётся стандартным `POST /api/alerting/rule` — параметры и примеры в [Alerting](../Elasticsearch/elasticsearch_alerting.md).

### Переменные действия (action variables) burn rate правила

| Переменная | Содержимое |
| :--- | :--- |
| `context.alertDetailsUrl` | Ссылка на страницу алерта; **пустая строка**, если не задан `server.publicBaseUrl` |
| `context.burnRateThreshold` | Порог burn rate |
| `context.longWindow` / `context.shortWindow` | Длительность окна и соответствующее значение burn rate |
| `context.grouping` | Объект групп, по которым пришли данные (GA с 9.1) |
| `context.reason` | Краткое описание причины алерта |
| `context.sloId` / `context.sloInstanceId` / `context.sloName` | Идентификатор и имя SLO (инстанса) |
| `context.timestamp` | Время обнаружения алерта |
| `context.viewInAppUrl` | Ссылка на страницу деталей SLO |

Общие для всех правил переменные (`kibana.basePath`, `rule.id`, `rule.name`, tags и др.) — в [Rule action variables](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-action-variables).

### Триаж

1. **Observability → Alerts** — фильтр по severity, groups (например, `service.name`), статусу (active / acknowledged / recovered).
2. Подтверждение (`acknowledge`) и eskalation — через [Cases](./kibana_cases.md); полный цикл автоматизации — через [Workflows](./kibana_workflows.md).
3. Для лог-алертов (log threshold) — переход прямо к Discover с фильтром условия правила: это быстрый способ увидеть вызвавшие события.

### Создание Synthetics-монитора через API

Мониторы создаются с привилегией `all` фичи **Synthetics** (раздел Observability). Размещение задаётся через `locations` (публичные, размещаемые Elastic), `private_locations` (ваши агенты `elastic-synthetics`) или обоими — минимум один обязателен:

```bash
export KBN="https://localhost:5601"
# HTTP-монитор: url + хотя бы одна location
curl -sk -X POST "${KBN}/api/synthetics/monitors" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "http",
    "name": "Website Availability",
    "url": "https://example.com",
    "tags": ["website", "availability"],
    "locations": ["united_kingdom"],
    "schedule": 5
  }'
# → 200; возможен массив warnings (некритичные замечания к конфигурации)
```

* Типы: `http` (обязателен `url`), `tcp`/`icmp` (обязателен `host`), `browser` (обязателен `inline_script` — journey на Playwright).
* `schedule` — минуты из набора `1, 3, 5, 10, 15, 30, 60, 120, 240`; дефолт `3` для HTTP/TCP/ICMP и `10` для browser.
* `alert` по умолчанию `{ "status": { "enabled": true }, "tls": { "enabled": true } }` — статусные и TLS-алерты включены сразу.
* `retest_on_failure: true` (повторный прогон при переходе up → down) снижает шум от транзиентных сбоев: до создания ошибки/алерта монитор прогоняется повторно.
* `timeout` (секунды) для browser-мониторов применяется **только на private locations**; без них Kibana вернёт warning в ответе, а минимальный timeout browser-монитора — 30 секунд.
* Списки доступных публичных и приватных локаций: команда `elastic-synthetics locations` с URL Kibana либо UI **Synthetics → Management / Settings → Private locations**.

### Private location: требования, ресурсы и создание через API

Private location выполняет мониторы на вашей инфраструктуре вместо публичной площадки Elastic. Требования и ограничения (документация Synthetics):

* Fleet Server + Elastic Agent, **enrolled в Fleet** — standalone-агенты для private locations не поддерживаются.
* **Одна agent policy — один Elastic Agent**: классическая private location не балансирует прогоны, и запуск одной policy на нескольких агентах даёт пропуски или дубли тестов. Масштабирование такой локации — добавлением ресурсов агента, а не агентов.
* Прямое соединение агента с Elasticsearch: вывод через Logstash и собственные ingest pipelines для этого трафика не поддерживаются и ломают Synthetics.
* Для browser-мониторов в контейнере обязателен образ **`elastic-agent-complete`** (обычный Elastic Agent умеет только TCP/ICMP/HTTP); контейнеру нужны capabilities `NET_RAW` и `SETUID`.
* С 9.4 agent policy должна находиться **в том же Kibana space**, что и private location; cross-space policy не поддерживаются — на каждый space своя policy.
* Лимиты агента по умолчанию: 2 параллельных browser-прогона и неограниченное число lightweight-проверок; настраиваются переменными окружения `SYNTHETICS_LIMIT_BROWSER`, `SYNTHETICS_LIMIT_HTTP`, `SYNTHETICS_LIMIT_TCP`, `SYNTHETICS_LIMIT_ICMP`. Ориентир ресурсов: минимум 2 GiB + 2 vCPU на browser-инстанс, 512 MiB + 2 vCPU на lightweight-часть.

Создание private location через API (`all`-привилегии фич **Synthetics and Uptime** раздела Observability; `agentPolicyId` — из Fleet):

```bash
curl -sk -X POST "${KBN}/api/synthetics/private_locations" \
  -H 'kbn-xsrf: true' -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "label": "dc1",
    "agentPolicyId": "57ca9e10-e1a4-11f0-9f2a-5b3f2a1d4e20",
    "geo": { "lat": 55.75, "lon": 37.61 },
    "tags": ["dc1"]
  }'
# → 200; 400, если label или agentPolicyId уже заняты
```

* `label` и `agentPolicyId` обязательны и уникальны; опциональные `tags`, `geo` (WGS84) и `spaces` (массив space'ов, в которых location доступна; без него — все spaces).
* Агенты на policy подтягивают назначенные мониторы автоматически. Сломанные интеграции мониторов (статус `missing_package_policy`) подсвечиваются значком unhealthy monitors на вкладке **Synthetics → Settings → Private locations**, массовое восстановление — **Reset monitors**.
* Ошибки в конфигурации монитора приходят в ответ API как массив `warnings` (некритичные замечания).

### Работа с логами в 9.x: Discover и log sources

С удалением Log Explorer и Logs Stream в 9.0 вся работа с логами идёт через **Discover** (с сохранёнными session и background search). Два момента, характерных для Observability:

* **`observability:logSources`** (Advanced Settings) — какие индексные шаблоны считаются источниками логов: дефолт `logs-*-*, logs-*, filebeat-*`. Значение влияет, в частности, на источники, по которым опрашиваются **log threshold rules**; шаблоны без логов дают деградацию функциональности.
* **Log threshold** — главное правило для логов: условие на счётчик событий с группировкой; переход из алерта прямо в Discover с применённым фильтром — штатный путь расследования (см. «Триаж»).

### Разбор инцидента в Applications

1. **Observability → Applications** — service inventory: сортировка по throughput/error rate, фильтр по environment.
2. Открыть сервис → вкладка транзакций: сравнить latency по transaction type/name, выбрать аномальный тип.
3. Конкретная транзакция → **Waterfall**: локализовать медленный/падающий span (внешний вызов, БД, downstream-сервис).
4. Вкладка errors: стек-трейс, кластеризация ошибок; привязать разбор к инциденту через [Cases](./kibana_cases.md).
5. Для повторяющихся проблем — latency / error count / failed transaction rate правила (тип и `rule_type_id` — в [Alerting](../Elasticsearch/elasticsearch_alerting.md)); эскалация — через [Workflows](./kibana_workflows.md).

Как устроены сами трассировки (агенты, APM Server, спаны, корреляция с логами, RUM) — в [Elastic APM: распределённые трассировки и RUM](../elastic-apm-tracing.md).

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Нельзя создать SLO / правило | Нет нод с ролью `transform` или `ingest`, нет лицензии, не настроен SLO access | Проверить роли нод (`GET _cat/nodes?v` — колонка `node.role`), лицензию, настройки доступа |
| Aлерт приходит, но `context.alertDetailsUrl` пуст | Не задан `server.publicBaseUrl` | Задать публичный URL ([Эксплуатация](./kibana_production_operations.md)) |
| Burn rate правило создано, уведомлений нет | Правило создано по умолчанию **без connector'а** | Добавить action/connector в правило |
| Правило «не видит» ошибки в окне | Слишком короткое окно/интервал проверки, нет данных за период | Увеличить lookback, проверить наличие SLI-данных в `.slo-observability.sli*` |
| Aлерт мгновенно восстанавливается | Короткое окно (1/12) очищается быстрее, чем длинное — это штатное поведение | Оценивать инцидент по длинному окну |
| Не найден Log Explorer / Logs Stream | Удалены в 9.0 | Использовать Discover (с background search) |
| Log threshold не «видит» новые индексы | Шаблон не входит в `observability:logSources` (дефолт `logs-*-*, logs-*, filebeat-*`) | Добавить шаблон в Advanced Settings; учесть влияние на существующие log threshold правила |
| Browser-монитор создан, но `timeout` не действует | Timeout для browser применяется только на private locations (Kibana возвращает warning) | Настроить private location либо отказаться от timeout для публичных локаций |
| Synthetics-монитор не проходит в выбранные локации | Нет ни `locations`, ни `private_locations`; не настроены агенты `elastic-synthetics` | Указать хотя бы одну локацию; приватные — **Synthetics → Settings → Private locations** |
| SLO создан через API, но алертов нет | Burn rate правило автоматически создаётся только при создании SLO через UI | Создать burn rate правило отдельно и добавить connector |
| Kibana: «The following transform is in an unhealthy state», SLO без данных | Сбой трансформов `slo-*` / `slo-summary-*`, недоступны шарды, нет нод с ролями `transform`/`ingest` | `GET _transform?expand_wildcards=all`, здоровье кластера; внутренние ассеты SLO не удалять и не править вручную |
| Мониторы private location не выполняются, статус `missing_package_policy` | Agent не enrolled в Fleet, несколько агентов на одной policy, policy в другом space (с 9.4) | Один агент на policy, policy и location в одном space; в UI — **Reset monitors** |
| Browser-мониторы на private location падают по ресурсам | Мало CPU/RAM: дефолт — 2 параллельных browser-прогона на агента, на browser-инстанс нужно ~2 GiB + 2 vCPU | Увеличить ресурсы агента или поднять `SYNTHETICS_LIMIT_BROWSER`/число прогонов |

## Best Practices

* **Multi-window burn rate**: используйте все 4 окна — короткое ловит всплески, длинное подтверждает тренд; методология — в [Рекомендации по алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).
* **SLO как контракт команды**: определение SLI/SLO и error budget — в [Концепциях SRE](../../Concepts/sre_concepts_main.md); в Kibana SLO — лишь реализация.
* **Одна точка правды для правил**: Observability-правила описываются в [Alerting](../Elasticsearch/elasticsearch_alerting.md), здесь — только их применение.
* **Сбор данных**: трейсы и метрики удобнее всего доставлять через [Fleet и Elastic Agent](../Elasticsearch/elastic_agent_and_fleet.md) и OpenTelemetry.
* **Не плодите SLO**: один SLO — на значимый пользовательский путь; количество правил держите в рамках, чтобы не потерять сигнал в триаже.
* **Внутренние ассеты SLO не трогать**: трансформы, ingest pipelines и индексы `.slo-observability.*` управляются Kibana — правки и переопределение index templates ломают расчёт SLI; инвентаризацию ведите через API definitions.
* **Private location — ресурсами, не числом policy**: одна policy на одного агента, browser-мониторы только на `elastic-agent-complete`, capacity наращивайте ресурсами агента (см. лимиты `SYNTHETICS_LIMIT_*`).

## Дополнительная информация

* **[Kibana: Обзор](./kibana_overview.md)** — разделы Kibana и их назначение.
* **[Kibana: Cases](./kibana_cases.md)** — инциденты: привязка алертов, статусы, выгрузка в тикет-системы.
* **[Kibana: Поиск, визуализация и управление](./kibana_search_and_visualization.md)** — Discover, ES\|QL, session, дашборды.
* **[Alerting: Kibana Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md)** — типы правил Observability, connectors.
* **[Fleet и Elastic Agent](../Elasticsearch/elastic_agent_and_fleet.md)** — сбор логов, метрик и трейсов.
* **[Elastic APM: распределённые трассировки и RUM](../elastic-apm-tracing.md)** — архитектура APM, корреляция логов и трасс, RUM.
* **[Концепции SRE: SLA, SLO, SLI](../../Concepts/sre_concepts_main.md)** — методология.
* **[Рекомендации по алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)** — multi-window burn rate, alert fatigue.
