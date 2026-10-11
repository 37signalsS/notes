# Kibana: Security Solution

> **Актуально для:** Kibana 8.19 / 9.x (Security app, detection rules API)

Движок детекции Elastic Security живёт в Kibana, но управляется отдельным API (`/api/detection_engine/*`), а не общим `/api/alerting/rule`. Эта заметка — об этих правилах, алертах и исключениях; общий фреймворк Kibana Alerting — в [Alerting](../Elasticsearch/elasticsearch_alerting.md).

## Определения

* **Detection rule** — правило детекции в Security app (Security → Rules). В отличие от обычных правил Kibana, его тип задаётся полем `type` (`query`, `threshold`, `eql` и т.д.), а не `rule_type_id`.
* **Alert (alert-as-data)** — результат срабатывания правила, сохранённый как документ индекса `.alerts-security.alerts-<space>`; доступен в Discover, дашбордах и Timeline.
* **Exception list** — набор исключений (значения полей/индексы), подавляющий срабатывания; список можно привязать к одному правилу или разделить между правилами.
* **Prebuilt rules** — поставляемый Elastic набор правил (репозиторий [elastic/detection-rules](https://github.com/elastic/detection-rules)); устанавливается и обновляется через API или UI.
* **Suppression (alert suppression)** — группировка срабатываний в один алерт за окно времени; снижает шум без потери покрытия.
* **Gap (пробел выполнения)** — период, когда правило не выполнялось (остановка Kibana, ошибка, пропуск расписания); находится во вкладке Rule Monitoring и закрывается разовым прогоном.
* **Manual run / Fill gaps** — разовые прогоны правила за указанный период: ручная проверка покрытия и закрытие gaps.
* **MITRE ATT&CK mapping** — таксономия техник, которой размечены правила; используется для оценки покрытия.
* **Case / Timeline** — инцидент и рабочий стол расследования; алерты и доказательства прикрепляются к Case.

## Основные концепции

### Позиция в стеке

Security detection rules используют **фреймворк** Kibana alerting (расписания, connectors, исполнение на background task), но работают с consumer `siem` и своим индексом алертов. Это значит:

* типы правил, connectors и action variables общего фреймворка — в [Alerting](../Elasticsearch/elasticsearch_alerting.md);
* статус/выполнение правила (`GET /api/alerting/rule/{id}`) там же — по нему видно ошибки исполнения;
* статус самих алертов (open / acknowledged / closed) меняется через detection API (см. «Практика»), а не через alerting API.

### Авторизация выполнения

Kibana использует API key для авторизации выполнения правила при каждом запуске: запрос к source-индексам, запись алертов в индекс алертов, выполнение actions (уведомления). На stack при создании или изменении правила Elastic Security генерирует Elasticsearch API key — это снимок текущих привилегий, а право собственности переходит к тому, кто последним отредактировал правило. Правило продолжает выполняться с привилегиями своего редактора, даже когда тот не в сессии; индексы, на которые смотрит правило, должны быть доступны именно этому пользователю.

Следствие для эксплуатации: если правило отредактировал пользователь без нужных привилегий (или привилегии у него отобрали после увольнения/смены роли), правило может перестать выполняться и молча не создавать алерты. Лечение — пользователь с нужными привилегиями открывает и пересохраняет правило (API key пересоздаётся); на stack его можно также обновить напрямую, без изменения конфигурации правила. Текущие привилегии: `GET /api/detection_engine/privileges`.

### Типы правил

По данным документации (Rule type guides):

| Что детектируем | Тип правила (`type` в API) |
| :--- | :--- |
| Агрегированные, вычисленные условия | `esql` (ES\|QL) |
| Известное значение/паттерн/условие | `query`, `saved_query` (KQL/Lucene) |
| Упорядоченная последовательность событий или их отсутствие | `eql` (Event correlation) |
| Совпадение с известным threat-индикатором | `threat_match` (Indicator match) |
| Превышение счётчика значений поля | `threshold` |
| Аномалии поведения без фиксированного паттерна | `machine_learning` |
| Поле, встретившееся впервые | `new_terms` |

### Требования

1. **Лицензия.** Базовое создание правил доступно в тирах Security; **прямое редактирование prebuilt rules — Enterprise (Elastic Stack 9.1+)** либо Security Analytics Complete на Serverless. Альтернатива без Enterprise — дублировать prebuilt rule и править копию.
2. **Постоянный ключ шифрования.** Из вызова в Security app: «A new encryption key is generated for saved objects each time you start Kibana. Without a persistent key, you cannot delete or modify rules after Kibana restarts.» → задать в `kibana.yml`:

```yaml
xpack.encryptedSavedObjects.encryptionKey: "<не менее 32 символов>"
```

3. **Привилегии пользователя** — проверяются через `GET /api/detection_engine/privileges` (и `GET /api/detection_engine/index` — имя индекса алертов).
4. Для ML-правил — доступные anomaly detection jobs, для `threat_match` — загруженные threat intel индексы.
5. **Источники данных.** Правило (кроме ML) ищет данные в index patterns (`logs-*`, `filebeat-*`) или в data views; ES|QL-правила data views не поддерживают — индексы указываются прямо в команде `FROM`. Источники, доступные Security app по умолчанию, задаются advanced setting `securitySolution:defaultIndex` (`apm-*-transaction*`, `auditbeat-*`, `endgame-*`, `filebeat-*`, `logs-*`, `packetbeat-*`, `winlogbeat-*`). Доступ к индексам проверяется для пользователя, создавшего/изменившего правило (см. «Авторизация выполнения»).

### Хранение алертов

* Текущий индекс: `.alerts-security.alerts-<space_id>` (для `default` — `.alerts-security.alerts-default`); переопределяется настройками Security app, получить актуальное имя — `GET /api/detection_engine/index`.
* Поле workflow-статуса: `kibana.alert.workflow_status` (`open` / `acknowledged` / `closed`).
* Старые индексы `.siem-signals-*` мигрируются отдельными API: `GET /api/detection_engine/signals/migration_status`, `POST /api/detection_engine/signals/migration` (завершение — `signals/finalize_migration`).
* При закрытии алерта можно передать `reason` — причина сохраняется в поле `kibana.alert.workflow_reason` и используется для фильтрации; список вариантов — advanced setting `securitySolution:alertCloseReasons`. Переоткрытие алерта очищает это поле.
* `.alerts-*` — системные индексы: их маппинг нельзя менять вручную (приводит к сбоям выполнения правил и индексации алертов); новые поля добавляются через runtime fields.
* Очистка старых алертов — **Stack Management → Alerts and Insights → Rules → Settings → Clean up alert history** (GA с 9.4, preview в 9.1–9.3): удаляет active/inactive алерты старше заданного порога (минимум — 1 день), алерты, привязанные к cases, не трогает. Требуется привилегия Kibana: Management → Rule Settings → **Alert deletion** = `All`; перед запуском сделайте snapshot кластера — удаление необратимо.

### Расписание, окно поиска и лимиты

* `interval` — частота выполнения правила, default `5m`; `from` — окно поиска от момента старта прогона, default `now-6m`: окно на минуту шире интервала, запас для запоздавших событий.
* `enabled` — default `true`. Практика: создавать правило с `enabled: false`, проверять preview/прогон и только потом включать.
* `max_signals` — максимум алертов за один прогон правила, default `100`. Общий потолок всех правил задаёт настройка фреймворка `xpack.alerting.rules.run.alerts.max` (см. [Alerting](../Elasticsearch/elasticsearch_alerting.md)) — при разборе «недостающих» алертов проверяйте оба значения.
* Остановка Kibana, недоступность task manager и тяжёлые прогоны порождают **gaps** — периоды невыполнения; по данным документации 9.x данные о gaps хранятся 90 дней.

## Практические сценарии

Все запросы требуют заголовка `kbn-xsrf: true`; базовый URL — `/api/detection_engine`.

### Установка и обновление prebuilt rules

```bash
# установить/обновить все prebuilt rules и Timelines
curl -sk -u elastic:$PASSWORD -X PUT "${KBN}/api/detection_engine/rules/prepackaged" \
  -H 'kbn-xsrf: true'
# → { "rules_installed": 112, "rules_updated": 0, "timelines_installed": 5, "timelines_updated": 2 }

# состояние установки
curl -sk -u elastic:$PASSWORD "${KBN}/api/detection_engine/rules/prepackaged/_status" \
  -H 'kbn-xsrf: true'
```

Обновления prebuilt rules приходят и через UI (вкладка **Rule Updates** на странице Detection rules): автоматические обновления поддерживаются для текущего и двух предыдущих минорных релизов Elastic Security; на более старых версиях обновления нужно ставить вручную либо апгрейдиться.

### Создание правила

```bash
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/rules" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' -d '{
  "type": "query",
  "name": "MS Office child process",
  "description": "Process started by MS Office program - possible payload",
  "rule_id": "process_started_by_ms_office_program",
  "interval": "1h",
  "from": "now-70m",
  "language": "kuery",
  "query": "process.parent.name:EXCEL.EXE or process.parent.name:WINWORD.EXE",
  "severity": "low",
  "risk_score": 50,
  "enabled": false,
  "tags": ["child process", "ms office"]
}'
# → { "id": "...", "rule_id": "...", "type": "query", ... }
```

Обязательные поля: `name`, `description`, `risk_score`, `severity`, `type` и поля конкретного типа (для `query` — `query` и `language`). Необязательны, но важны: `interval` (default `5m`), `from` (default `now-6m`), `enabled` (default `true`), `max_signals` (default `100`). `rule_id` — стабильный внешний идентификатор (не привязан к пространству, переживает пересоздание правила) — задавайте его осознанно, он же ключ для export/import и bulk-операций; `severity` — `low|medium|high|critical`, `risk_score` — 0–100.

### Suppression: пример

```bash
# добавить правилу подавление шума: один алерт на пару user.name+host.name за 5 минут
curl -sk -u elastic:$PASSWORD -X PATCH "${KBN}/api/detection_engine/rules?id=<uuid>" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' -d '{
  "alert_suppression": {
    "group_by": ["user.name", "host.name"],
    "duration": {"value": 5, "unit": "m"},
    "missing_fields_strategy": "suppress"
  }
}'
```

* `group_by` — 1–3 поля группировки; события с одинаковыми значениями сворачиваются в один алерт.
* `duration` — окно подавления, единицы `s` / `m` / `h`; без явного окна подавление действует в рамках одного прогона правила (per rule execution), с `duration` — в рамках заданного окна на группу (per time period).
* `missing_fields_strategy` — `suppress` (документ без поля группировки тоже попадает в группу) или `doNotSuppress` (для таких документов создаётся отдельный алерт).
* Подавление не «съедает» события: исходные события доступны через Timeline у подавленного алерта; поле `kibana.alert.suppression.docs_count` показывает, сколько событий свёрнуто. Требует соответствующей платной подписки (в 8.19 — Platinum или выше); при таймаутах правил с подавлением — укорачивайте `from` или отключайте suppression.

### Чтение, поиск, изменение

```bash
# прочитать по id или rule_id
curl -sk -u elastic:$PASSWORD "${KBN}/api/detection_engine/rules?id=<uuid>" -H 'kbn-xsrf: true'

# постраничный список (по умолчанию первая страница, 20 правил)
curl -sk -u elastic:$PASSWORD \
  "${KBN}/api/detection_engine/rules/_find?page=1&per_page=5&sort_field=enabled&sort_order=asc&filter=alert.attributes.name:windows" \
  -H 'kbn-xsrf: true'

# частичное обновление
curl -sk -u elastic:$PASSWORD -X PATCH "${KBN}/api/detection_engine/rules?id=<uuid>" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' -d '{"severity": "high"}'

# удалить (один из параметров обязателен)
curl -sk -u elastic:$PASSWORD -X DELETE "${KBN}/api/detection_engine/rules?id=<uuid>" -H 'kbn-xsrf: true'
curl -sk -u elastic:$PASSWORD -X DELETE "${KBN}/api/detection_engine/rules?rule_id=process_started_by_ms_office_program" -H 'kbn-xsrf: true'
```

Полный `PUT .../rules` — полное обновление (UpdateRule), `PATCH` — частичное (PatchRule).

### Массовые операции, экспорт/импорт

```bash
# массовые операции: enable|disable|delete|duplicate|export|run|fill_gaps|edit
# цель задаётся ids: [...] (только id-UUID, не rule_id) или query: 'alert.attributes.tags: "test"'
# edit — массовое изменение полей (tags, index patterns, schedule и т.п.),
# run — разовый прогон за период, fill_gaps — закрытие gaps за период
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/rules/_bulk_action" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' -d '{"action": "enable", "ids": ["<uuid1>", "<uuid2>"]}'

# экспорт всех правил в ndjson (включая actions и exception lists)
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/rules/_export?exclude_export_details=false" \
  -H 'kbn-xsrf: true' -o rules.ndjson

# экспорт подмножества — тело JSON с rule_id (не id)
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/rules/_export" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' \
  -d '{"objects": [{"rule_id": "process_started_by_ms_office_program"}]}' -o subset.ndjson

# импорт (multipart/form-data, поле с файлом .ndjson)
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/rules/_import" \
  -H 'kbn-xsrf: true' -F "file=@rules.ndjson"

# импорт с перезаписью существующих правил (GitOps-обновление)
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/rules/_import?overwrite=true&overwrite_exceptions=true" \
  -H 'kbn-xsrf: true' -F "file=@rules.ndjson"
```

Экспорт/импорт ndjson — рабочий способ держать правила в Git и переносить между кластерами.

### Алерты: статус, теги, исполнение

```bash
# закрыть алерты по списку id
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/signals/status" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' \
  -d '{"signal_ids": ["<alert-id>"], "status": "closed"}'

# поиск алертов по произвольному query
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/signals/search" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' \
  -d '{"query": {"bool": {"filter": [{"term": {"kibana.alert.workflow_status": "open"}}]}}, "size": 10}'
```

Связанные endpoint'ы: `signals/tags`, `signals/assignees`, `attacks/*` (новая модель incidents).

* `signal_ids` — значения `_id` документа алерта или поле `kibana.alert.uuid`.
* Статусы: `open`, `acknowledged`, `closed`; API также принимает `in-progress`.
* При `status: "closed"` тело может содержать `reason` — причина закрытия (см. «Хранение алертов»).

### Исключения

```bash
# элемент исключения для конкретного правила
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/rules/<uuid>/exceptions" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' -d '{
  "list_id": "exception-list-1",
  "namespace_type": "single",
  "items": [{"type": "simple", "entries": [{"field": "user.name", "operator": "included", "value": ["svc-backup"]}]}]
}'

# управление общими списками
# GET/POST/PUT/DELETE /api/exception_lists , /api/exception_lists/items , GET /api/exception_lists/_find
```

Исключения применяются к данным (match по полям события) и не требуют пересоздания правила.

### Валидация и мониторинг выполнения

```bash
# предпросмотр правила на историческом диапазоне — тело: JSON правила + параметры окна,
# алерты не создаются, в ответе — длительность, errors и warnings прогона
curl -sk -u elastic:$PASSWORD -X POST "${KBN}/api/detection_engine/rules/preview" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' -d '{
  "type": "query",
  "name": "preview",
  "description": "preview run",
  "risk_score": 25,
  "severity": "low",
  "language": "kuery",
  "query": "process.name : *",
  "index": ["logs-*"],
  "from": "now-24h",
  "to": "now",
  "invocationCount": 1,
  "timeframeEnd": "2026-10-08T12:00:00.000Z"
}'
# → { "previewId": "...", "logs": [{ "duration": 45, "errors": [], "warnings": [] }] }

# убедиться, что правило создано и включено
curl -sk -u elastic:$PASSWORD \
  "${KBN}/api/detection_engine/rules/_find?filter=alert.attributes.name:preview" -H 'kbn-xsrf: true'

# статус выполнения и ошибки — общий фреймворк alerting (см. Alerting)
curl -sk -u elastic:$PASSWORD "${KBN}/api/alerting/rule/<rule-uuid>" -H 'kbn-xsrf: true'
# → execution_status и ошибки последнего запуска правила
```

В UI выполнение смотрится на вкладках страницы правила: **Execution results** (последние запуски, ошибки, Manual runs) и **Rule Monitoring** (gaps, статусы закрытия gaps: Filled / Partially filled / Unfilled). Gaps закрываются bulk-действием `fill_gaps` (или ручным `run` за нужный период); автоматический прогон по расписанию при этом не меняется.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| После рестарта Kibana нельзя удалить/изменить правила | Каждый старт генерирует новый ключ шифрования saved objects | Задать постоянный `xpack.encryptedSavedObjects.encryptionKey` в `kibana.yml` и перезапустить все ноды Kibana |
| `_find` возвращает пусто при известных правилах | Неверный синтаксис фильтра | Фильтр вида `filter=alert.attributes.name:windows` (по атрибутам saved object правила) |
| 403 на любой endpoint | Недостаточно привилегий в пространстве | `GET /api/detection_engine/privileges`, проверить роли Security Solution |
| Алерты не создаются | Правило выключено, нет данных source-индекса, ошибка исполнения | Статус и ошибки — в UI Rules или `GET /api/alerting/rule/{id}` (общий фреймворк) |
| Правило «взрывается» количеством алертов | Нет suppression/исключений | Настроить alert suppression, exceptions, сузить `from`/`interval`, threshold |
| Prebuilt rules не обновляются | Нет доступа к пакету правил (air-gapped) | Обновление без интернета — раздел [Prebuilt rules](https://www.elastic.co/docs/solutions/security/detect-and-alert/prebuilt-rules) |
| Тонкие правила не срабатывают после миграции индекса | Ссылки на устаревший индекс `.siem-signals-*` | Использовать индекс из `GET /api/detection_engine/index`, миграцию — `signals/migration_status` |
| Редактирование prebuilt rule недоступно | Требуется Enterprise (9.1+) | Дублировать правило и править копию, либо обновлять лицензию |
| Правило молча перестало создавать алерты после смены редактора/роли | Выполняется по API key-снимку последнего редактора; у того больше нет нужных привилегий | Пересохранить правило пользователем с привилегиями (API key пересоздаётся), привилегии — `GET /api/detection_engine/privileges` |
| После простоя Kibana в правилах появились gaps (периоды без выполнения) | Правило не выполнялось, пока Kibana/task manager были недоступны | Вкладка Rule Monitoring → Gaps, bulk `fill_gaps` или ручной `run` за период |
| Совпадений много, а алертов меньше ожидаемого | Лимит `max_signals` (default 100) или общий потолок `xpack.alerting.rules.run.alerts.max` | Проверить оба значения; увеличивать осознанно — растёт нагрузка на Elasticsearch |
| Ошибки выполнения/индексации после правок `.alerts-*` | Маппинг системного индекса алертов изменён вручную | Вернуть исходный маппинг; новые поля — через runtime fields |
| В UI не приходят обновления prebuilt rules | Автообновления поддерживаются для текущего и двух предыдущих минорных релизов | Апгрейд Elastic Security либо ручная установка обновлений (air-gapped — раздел [Prebuilt rules](https://www.elastic.co/docs/solutions/security/detect-and-alert/prebuilt-rules)) |
| Правки prebuilt rule исчезли после обновления или даунгрейда | На Basic–Platinum обновления перезаписывают модификации правил | Дублировать правило и править копию; Enterprise выполняет merge конфликтов на вкладке Rule Updates |
| Импорт ndjson создал дубли вместо обновления | `_import` по умолчанию не перезаписывает существующие правила | `POST .../_import?overwrite=true` (+ `overwrite_exceptions=true` для списков исключений) |

## Best Practices

* **Путь внедрения:** install prebuilt rules → monitor rule executions → tune (exceptions, suppression, snooze). Именно такой порядок рекомендует документация Security: сначала покрытие, потом шум.
* **Exceptions вместо отключения:** отключённое правило теряет все срабатывания; исключение убирает известно-ложные события и сохраняет обнаружение остальных.
* **GitOps для правил:** регулярный `POST _export` в репозиторий, импорт на новых средах через `POST _import`; репозиторий Elastic как источник истины для prebuilt — [elastic/detection-rules](https://github.com/elastic/detection-rules).
* **MITRE ATT&CK** — метрика покрытия: следите, какие техники не закрыты, а не только сколько правил включено.
* **Не плодите правила вручную:** сначала ищите готовое в prebuilt, затем адаптируйте.
* **Preview перед включением:** `POST /api/detection_engine/rules/preview` прогоняет запрос на историческом диапазоне без создания алертов — так настраивают query/threshold до `enabled: true`.
* **Стабильный `rule_id` как ключ:** он переживает пересоздание правила и не привязан к пространству — на нём строится GitOps-цикл (export/import, bulk-операции); `id` (UUID) пространственно-зависим.
* **Держите prebuilt rules в окне автообновлений:** обновления «дотягиваются» автоматически только для текущего и двух предыдущих минорных релизов — дрейф отставших правил дороже при апгрейде.
* **Suppression — первый уровень борьбы с шумом:** группировка за окно времени (`alert_suppression`) снижает объём алертов без изменения query; закрытие подавленного алерта меняет поведение подавления — эффект проверяйте в Rule preview.
* **Алерты как данные:** `.alerts-security.alerts-*` — обычный индекс, на нём можно строить дашборды (Discover/ES\|QL), но маппинг `.alerts-*` служебный и не правится вручную (новые поля — runtime fields), нужна аккуратность с привилегиями и retention.
* **Цикл закрытия:** статус алерта (open → acknowledged → closed) + Case; автоматизация цикла — через [Workflows](./kibana_workflows.md).

## Дополнительная информация

* **[Alerting: Kibana Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md)** — общий фреймворк правил, connectors, action variables.
* **[Kibana: Cases](./kibana_cases.md)** — инциденты: owner, статусы, привязка алертов, выгрузка в тикет-системы.
* **[Security: Advanced](../Elasticsearch/elasticsearch_security_advanced.md)** — TLS, RBAC, аудит Elasticsearch.
* **[Kibana: Эксплуатация](./kibana_production_operations.md)** — роли нод, прокси, диагностика.
* **[Kibana: Workflows](./kibana_workflows.md)** — автоматизация триажа алертов и Cases.
* **[Kibana: Поиск, визуализация и управление](./kibana_search_and_visualization.md)** — Discover и дашборды по данным алертов.
* **[Rule type guides](https://www.elastic.co/docs/solutions/security/detect-and-alert/rule-types)** — официальный гид по типам правил.
* **[Detection rule concepts](https://www.elastic.co/docs/solutions/security/detect-and-alert/detection-rule-concepts)** — авторизация выполнения (API key), источники данных, exceptions, notifications.
* **[Using the API](https://www.elastic.co/docs/solutions/security/detect-and-alert/using-the-api)** — таблица endpoint'ов detections API для CI/CD и bulk-операций.
* **[Suppress detection alerts](https://www.elastic.co/docs/solutions/security/detect-and-alert/alert-suppression)** — полная механика suppression, массивы полей, поведение при закрытии.
* **[Fill rule execution gaps](https://www.elastic.co/docs/solutions/security/detect-and-alert/fill-rule-gaps)** — gaps и их закрытие: ручное и автоматическое.
* **[Update prebuilt rules](https://www.elastic.co/docs/solutions/security/detect-and-alert/update-prebuilt-rules)** — вкладка Rule Updates, merge-конфликты (Enterprise), окно автообновлений.
