# Kibana: Cases (инциденты)

> **Актуально для:** Kibana 8.19 / 9.x

Cases — общий фреймворк инцидентов для Security, Observability и Stack Management: единый объект-инцидент с алертами, комментариями, исполнителями и выгрузкой в Jira/ServiceNow. Эта заметка — устройство объекта, привилегии и рабочие операции через UI и API; методология инцидент-менеджмента — в концепциях, коннекторы — в Alerting.

## Определения

* **Case** — объект-инцидент. Ключевые поля: `title` (до 160 символов), `description` (до 30 000), `category` (до 50 символов), `tags` (до 200, каждый до 256 символов), `severity` (`critical` / `high` / `medium` / `low`), `status` (`open` / `in-progress` / `closed`), `owner`, `assignees` (не более 10, задаются по user profile uid), комментарии (каждый до 30 000 символов), `customFields` (не более 10), observables. Поле `duration` (секунды от создания до закрытия) заполняется автоматически после закрытия.
* **owner** — приложение-владелец case: `cases` (Stack Management), `observability` или `securitySolution`. Задаёт, в каком разделе Kibana действуют привилегии на case и какому разделу он виден.
* **Connector** — интеграция с внешним трекером. Допустимые значения `type`: `.none` (без интеграции), `.jira`, `.resilient` (IBM Resilient), `.servicenow` (ServiceNow ITSM), `.servicenow-sir` (ServiceNow SecOps), `.swimlane`, `.thehive` (TheHive), `.cases-webhook` (Webhook - Case Management). Это типы-идентификаторы: названия вроде «ServiceNow ITSM» или «IBM Resilient» — это `name` коннектора, а не его `type`. Выгрузка во внешнюю систему выполняется явно (push), а не автоматически.
* **Alert attachment** — привязка алертов правила к case отдельным типом комментария (`type: alert` с `alertId`, `index`, `rule`). Лимит — **1000 алертов на один case**.
* **Settings (внутри case)** — настройки, хранящиеся в теле case: `syncAlerts` (синхронизация статусов case и привязанных алертов) и `extractObservables` (автоматическое извлечение observables — IP, хешей, URL — из комментариев). Приоритет `extractObservables`: явное значение > настройка шаблона > настройка пространства > значение по умолчанию владельца (`true` для Security, `false` для Stack Management и Observability); для Observability извлечение не поддерживается и всегда `false`.
* **Case settings (настройки cases)** — настройки уровня пространства и владельца, хранящиеся отдельно от case: `closure_type`, коннектор по умолчанию, `customFields` и шаблоны. Читаются через `GET /api/cases/configure`, изменяются через `POST`/`PATCH` того же пути. Именно к ним относится суб-привилегия **Case settings**; не путать с полем `settings` внутри case.
* **Template (case template)** — шаблон case, задающий severity, category, tags, assignees, settings и connector по умолчанию; поля шаблона попадают в `extended_fields`. Управляется флагом `xpack.cases.templates.enabled`: в актуальных релизах Kibana он включён по умолчанию, в 8.19 и ранних 9.x по умолчанию `false` и требует явного включения в `kibana.yml`. Параметр `template` в API создания помечен как **Technical preview**, тогда как справочник Kibana описывает шаблоны как GA с 9.5 — расхождение статусов между API и пользовательской документацией.
* **Field library (библиотека полей)** — переиспользуемые custom fields: глобальные (видны всем case'ам) и переиспользуемые (попадают в case, созданный из шаблона, который на них ссылается). CRUD — эндпоинты `/api/cases/field_definitions`.
* **File attachment** — файл, приложенный к case (`POST /api/cases/{caseId}/files`, `multipart/form-data`). Лимиты по умолчанию: 10 MiB для изображений и 100 MiB для остальных MIME-типов; настройки `xpack.cases.files.maxSize` и `xpack.cases.files.allowedMimeTypes`.

## Основные концепции

### Один фреймворк — три владельца

В Kibana нет отдельных «security-cases» и «observability-cases»: это один объект с полем `owner`. От него зависит:

* **Раздел привилегий.** Создание и изменение case требуют привилегии `all` фичи **Cases** в разделе **Management**, **Observability** или **Security** Kibana feature privileges — в зависимости от owner case'а. Для поиска (`_find`) достаточно `read`.
* **Видимость.** Security Solution показывает cases с `owner: securitySolution`, Observability — `owner: observability` и т. д.; API с фильтром `owner` (или без него — все доступные на чтение). Cases одного решения не видны в другом: case'ы Stack Management не отображаются в Observability и Security и наоборот, и алерты привязываются только из своего решения.

Владелец указывается при создании и не меняется молча: случайный `owner` — частая причина «инцидент создан, но его не видно в нужном разделе».

### Привилегии и суб-привилегии

Фича **Cases** существует в трёх разделах Kibana feature privileges — **Management** (Stack Management), **Observability** и **Security**; нужный раздел выбирается по owner case'а. Минимальные требования к типовым действиям:

| Действие | Минимальная привилегия |
| :--- | :--- |
| Просмотр, `_find`, чтение активности и настроек | `read` Cases |
| Создание и изменение case | `all` Cases |
| Назначение исполнителей | `all` Cases + user profile: пользователь должен войти в Kibana хотя бы раз |
| Привязка алертов к case | `all` Cases + привилегия на алерты своего решения (с 9.4: Security → Alerts `read`/`all`, Observability — `read`; ранее — `read` решения, у которого есть алерты) |
| Push во внешнюю трекер | `all` Cases + `all` Actions and Connectors (Management) |
| Удаление case и комментариев | `read`/`all` Cases **+ суб-привилегия Delete** |
| Комментарии и вложения | `all` Cases + суб-привилегия **Create comments & attachments** |
| Настройки cases (closure type, коннектор по умолчанию) | `all` Cases + суб-привилегия **Case settings** |
| Повторное открытие закрытого case | `all` Cases + суб-привилегия **Re-open** |
| Управление шаблонами и библиотекой полей | `all` Cases + суб-привилегия **Manage templates** (GA с 9.5) |
| Отчётность по analytics-индексам | Elasticsearch-привилегии `read` и `view_index_metadata` на индексы cases (см. «Аналитика cases») |

Суб-привилегии выдаются через **Customize sub-feature privileges** в настройках роли: **Delete** (удаление case'ов и комментариев), **Case settings** (изменение настроек), **Create comments & attachments**, **Re-open**, **Assign users**, **Manage templates** (GA с 9.5). Без этой настройки `all` даёт полный набор (включая удаление и настройки), `read` — только просмотр. Пользователи без **Manage templates** могут выбирать и применять уже созданные шаблоны при создании и изменении case.

### Связь с alerting и автоматизацией

* Алерт правила (например, burn rate или detection rule) привязывается к case как комментарий типа `alert`; при этом case и алерт связаны в обе стороны — для case доступен список привязанных алертов (`GET /api/cases/{caseId}/alerts`, помечен как Technical preview), для алерта — список case'ов (`GET /api/cases/alerts/{alertId}`).
* `settings.syncAlerts: true` синхронизирует статусы: закрытие case'а отражается на привязанных алертах.
* Выгрузка во внешний трекер — push через connector; для него нужны привилегии `all` фичи **Actions and Connectors** (раздел Management) **плюс** `all` Cases.
* Полный цикл (алерт → case → уведомление → обогащение) автоматизируется [Workflows](./kibana_workflows.md).

### Space-scoped API

Все эндпоинты cases существуют в двух вариантах: `/api/cases/...` (Default Space) и `/s/{space_id}/api/cases/...` (указанное пространство). Во всех запросах с телом обязателен заголовок `kbn-xsrf`.

## Практические сценарии

### Создание case через API

```bash
export KBN="https://localhost:5601"
# kbn-xsrf обязателен; owner определяет раздел привилегий
curl -sk -X POST "${KBN}/api/cases" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Payment service latency spike",
    "description": "p99 latency > 2s, burn rate rule сработал на 4 окнах",
    "tags": ["payments", "latency"],
    "severity": "high",
    "owner": "observability",
    "assignees": [{ "uid": "<user-profile-uid>" }],
    "connector": { "id": "none", "name": "none", "type": ".none", "fields": null },
    "settings": { "syncAlerts": true, "extractObservables": false }
  }'
# → 200: объект case с id, version, status "open", created_at
```

Поля `title`, `description`, `owner`, `tags`, `connector`, `settings` обязательны; `severity` необязательно — задавайте его явно, чтобы не зависеть от значения по умолчанию.

### Создание case из шаблона

```bash
# 1. Список доступных шаблонов и их полей
curl -sk "${KBN}/api/cases/templates" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}"
# → [{ "id": ..., "version": ..., "name": ..., ... }]
curl -sk "${KBN}/api/cases/fields" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}"
# → применимые поля: какие custom fields требует шаблон

# 2. Создание с шаблоном
curl -sk -X POST "${KBN}/api/cases" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "DB failover in prod",
    "description": "Переключение primary, проверка репликации",
    "owner": "observability",
    "tags": [],
    "connector": { "id": "none", "name": "none", "type": ".none", "fields": null },
    "settings": { "syncAlerts": true },
    "template": { "id": "<template-id>", "version": 3 }
  }'
# → 200: case с значениями шаблона, которых нет в запросе
```

Шаблон подставляет severity, category, tags, assignees, settings, connector и значения custom fields; **любое явно переданное в запросе значение перекрывает значение шаблона**. Без `version` берётся и закрепляется последняя версия шаблона. Список шаблонов — `GET /api/cases/templates`, применимые поля шаблона — `GET /api/cases/fields` (рекомендуется запросить до создания case).

### Поиск и фильтрация

```bash
# Открытые cases с тегом payments, постранично (perPage ограничен 100)
curl -sk -G "${KBN}/api/cases/_find" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  --data-urlencode "status=open" \
  --data-urlencode "tags=payments" \
  --data-urlencode "owner=observability" \
  --data-urlencode "perPage=50"
# → { "cases": [...], "count_open_cases": ..., "count_in_progress_cases": ...,
#     "count_closed_cases": ..., "total": ... }
```

Другие фильтры `_find`: `search` (simple_query_string) и `searchFields`, `defaultSearchOperator` (`OR` по умолчанию), `severity`, `category`, `assignees` (uid профилей либо `none` — case'ы без исполнителя), `reporters`, `from`/`to` (KQL-диапазон дат), `sortField`, `sortOrder`. `perPage` по умолчанию 20, максимум 100; параметр `owner` без фильтра возвращает все case'ы, доступные пользователю на чтение.

### Чтение case и аудит активности

```bash
# Детали case. Ответ НЕ содержит комментариев — они в comments/_find
curl -sk "${KBN}/api/cases/${CASE_ID}" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}"
# → объект case: totalAlerts, totalComment, total_observables, external_service, duration

# Аудит: кто и что менял (требует read)
curl -sk -G "${KBN}/api/cases/${CASE_ID}/user_actions/_find" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  --data-urlencode "types=status" --data-urlencode "perPage=50"
# → [{ "action": ..., "type": "status", "created_by": ..., ... }]

# Все case'ы, привязанные к конкретному алерту
curl -sk "${KBN}/api/cases/alerts/${ALERT_ID}" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}"
# → [ { id, title, status, ... } ]
```

Фильтр `types` для активности: `create_case`, `status`, `severity`, `tags`, `title`, `description`, `comment`, `alert`, `attachment`, `assignees`, `connector`, `pushed`, `settings`, `action`, `user`. Активность — основа аудита «кто закрыл инцидент и почему»; комментарии читаются отдельно через `GET /api/cases/{caseId}/comments/_find`.

### Привязка алертов к case

```bash
curl -sk -X POST "${KBN}/api/cases/${CASE_ID}/comments" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "alert",
    "alertId": ["0a1b2c3d-..."],
    "index": [".alerts-observability.alerts-default"],
    "rule": { "id": "<rule-id>", "name": "High latency burn rate" },
    "owner": "observability"
  }'
# → 200: case с обновлённым totalAlerts
```

Массивы `alertId` и `index` должны быть одинаковой длины (позиция в массиве = пара алерт/индекс); пакетное добавление нескольких алертов одной пачкой — предпочтительнее нескольких вызовов (Technical preview).

### Комментарии и файлы

```bash
# Текстовый комментарий (требует all Cases и суб-привилегию Create comments & attachments)
curl -sk -X POST "${KBN}/api/cases/${CASE_ID}/comments" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "user",
    "comment": "Проверены дашборды latency: причина — деградация primary БД",
    "owner": "observability"
  }'
# → 200: case с обновлённым totalComment

# Файл (all Cases, multipart/form-data)
curl -sk -X POST "${KBN}/api/cases/${CASE_ID}/files" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -F "file=@/tmp/trace-excerpt.txt" -F "filename=trace-excerpt"
# → 200: case с добавленным файлом

# Список комментариев (read)
curl -sk -G "${KBN}/api/cases/${CASE_ID}/comments/_find" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  --data-urlencode "perPage=50"
```

Поля комментария: `type` (`user` / `alert`), `comment` (до 30 000 символов), `owner` — все обязательны. Права: чтение — `read`, изменение — `all` Cases, удаление — `all` Cases плюс суб-привилегия **Delete**. Для файла `filename` передаётся без расширения; тип и размер ограничиваются `xpack.cases.files.allowedMimeTypes` и `xpack.cases.files.maxSize`.

### Смена статуса и обновление полей

```bash
curl -sk -X PATCH "${KBN}/api/cases" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "cases": [{
      "id": "<case-id>",
      "version": "<version из ответа>",
      "status": "in-progress",
      "severity": "critical"
    }]
  }'
# → 200: массив обновлённых case'ов
```

`version` обязателен — это оптимистическая блокировка: при несовпадении (case изменён параллельно) запрос отклоняется. `closed_at` / `closed_by` заполняются при переводе в `closed`. В одном PATCH — не более 100 case'ов; больший массив отклоняется, разбейте его на пачки.

### Выгрузка во внешний трекер (push)

```bash
curl -sk -X POST "${KBN}/api/cases/${CASE_ID}/connector/${CONNECTOR_ID}/_push" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' -d '{}'
# → 200: case с заполненным external_service (внешний id инцидента)
```

Требует `all` Cases **и** `all` Actions and Connectors. ID коннекторов — `GET /api/actions/connectors`. До push'а connector должен быть корректно настроен в **Stack Management → Connectors**.

### Настройки cases: closure type и коннектор по умолчанию

```bash
# Текущие настройки (read)
curl -sk "${KBN}/api/cases/configure" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}"
# → [{ id, version, connector, closure_type, customFields, templates, ... }]

# Изменение (all Cases + суб-привилегия Case settings; version обязателен)
curl -sk -X PATCH "${KBN}/api/cases/configure/${CONFIG_ID}" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "version": "<version из GET>",
    "closure_type": "close-by-pushing",
    "connector": { "id": "<connector-id>", "name": "Jira", "type": ".jira", "fields": { "issueType": "10004", "priority": "2" } }
  }'
# → 200: обновлённая конфигурация
```

`closure_type` определяет, как закрывается case: `close-by-user` — только вручную, `close-by-pushing` — вместе с успешной выгрузкой во внешний трекер. Здесь же задаются custom fields и шаблоны. Настройки существуют отдельно для каждого owner'а: `POST /api/cases/configure` создаёт их для одного owner'а (поле `owner` в теле обязательно), `PATCH` — меняет существующие по `configurationId` и `version`. Коннектор по умолчанию автоматически подставляется при создании case'а **в UI**; в API создания case'а поля коннектора всё равно обязательны — укажите их явно.

### Массовые операции и удаление

```bash
# Массовое удаление (read/all Cases + суб-привилегия Delete);
# ids передаются query-параметром и URL-кодируются
curl -sk -X DELETE "${KBN}/api/cases?ids=%5B%22${CASE_ID}%22%5D" \
  -H "kbn-xsrf: true" -H "Authorization: ApiKey ${KIBANA_API_KEY}"
# → 204: тело ответа пустое

# Массовое обновление — см. «Смена статуса»: PATCH /api/cases, до 100 case'ов
# Поиск для отбора — _find (до 100 на страницу), повторять до полного total
```

Лимит `ids` — от 1 до 100 элементов; параметра `owner` у delete-запроса нет — права проверяются по owner'у каждого удаляемого case'а. Удаление необратимо: комментарии, алерты-вложения и файлы исчезают вместе с case, восстановить их через API нельзя. Перед массовым удалением выгрузите нужные case'ы (см. ниже) и убедитесь, что в списке нет case'ов, которые должен закрыть контроллер.

### Работа в UI

* Входы в раздел: **Stack Management → Cases**, **Security → Cases**, **Observability → Cases**; в глобальном поиске — `Security/Cases`, `Observability/Cases`. В каждом разделе видны только case'ы своего owner'а.
* Список: фильтры по assignees, category, severity, status и tags, сортировка, групповые (bulk) действия — смена атрибутов и удаление нескольких case'ов разом. Те же правила привилегий, что и в API.
* Внутри case: комментарии, алерты и вложения, смена статуса и severity, assignees, push в коннектор, закрытие/удаление/переоткрытие — каждое действие ограничено своей суб-привилегией.
* Настройки owner'а — **Stack Management → Cases → Settings** (в 9.5 страница Settings открывается из раздела Cases); шаблоны и библиотека полей вынесены на отдельную страницу **Templates**.
* Экспорт/импорт — **Stack Management → Saved Objects** (NDJSON): case'ы, комментарии, действия и вложения выгружаются как связанные объекты, а настройки owner'а (`cases-configure`) и маппинги коннекторов отдельно не выгружаются — задайте их на месте назначения. Секреты коннекторов в экспорт не входят: после импорта их вводят заново, иначе коннектор будет помечен как `isMissingSecrets`.

### Сценарий: от алерта до закрытия

1. Burn rate / detection rule сработал → **Alerts** в соответствующем разделе.
2. Создать case (вручную в разделе Cases приложения или автоматическим шагом [Workflows](./kibana_workflows.md)) с корректным `owner`, `severity` и тегами.
3. Привязать алерт (API — см. выше; в UI это действие доступно из case), назначить исполнителей (`assignees`).
4. Работа: комментарии, `status: in-progress`, при необходимости push в Jira/ServiceNow.
5. Устранение → `status: closed`; при `syncAlerts` привязанные алерты синхронизируются, `duration` фиксирует время работы.

## Аналитика cases

Для отчётности по инцидентам (сколько закрыто, время до закрытия, что менялось и кто менял) case'ы зеркалируются в отдельные индексы Elasticsearch. Это отдельный механизм от Saved Objects: на него действуют **только** Elasticsearch-привилегии, feature privileges Cases на эти индексы не распространяются.

В Kibana сосуществуют две реализации:

* **v2 (GA с 9.5) — включена по умолчанию** (`xpack.cases.analyticsV2.enabled: true`). Три кластерных индекса, общих для всех пространств: `.cases` (текущее состояние каждого case'а, `index.mode: lookup` — можно делать `LOOKUP JOIN` из ES|QL), `.cases-activity` (append-only зеркало действий: смены статуса, комментарии), `.cases-attachments` (алерты, комментарии, файлы, дашборды). Запись идёт по хукам сразу при изменении case'а; фоновая сверка добирает пропуски раз в `xpack.cases.analyticsV2.reconciliationIntervalMinutes` (по умолчанию 30 минут, минимум 5). Админ-маршруты (`GET /internal/cases/_analyticsV2/state`, `POST .../reset`, `POST .../reconcile/run_soon`) выключены по умолчанию — включаются `xpack.cases.analyticsV2.enableAdminRoutes: true`, действуют глобально по всем пространствам.
* **v1 (preview в 9.2–9.4) — выключена по умолчанию** (`xpack.cases.analytics.index.enabled: false`). Индексы создаются отдельно на каждое пространство и решение: `.internal.<type>.<solution>-<space>` c alias'ом без `.internal` — например `.internal.cases-attachments.securitysolution-default` → `.cases-attachments.securitysolution-default`; `<type>` — `cases`, `cases-comments`, `cases-attachments`, `cases-activity`.

Схема и свежесть данных зависят от версии (см. [Case analytics indices](https://www.elastic.co/docs/explore-analyze/cases/case-analytics-indices)):

* **9.5+ (GA):** общие индексы, имена полей с префиксом `case.*` (`case.status`, не `cases.status` — иначе запрос ES|QL падает); данные всех решений лежат вместе — фильтруйте по `owner` и `space_id`.
* **9.2–9.4 (preview):** поля **без** префикса (`status`, `time_to_resolve`); обновление — фоновой задачей раз в пять минут, после создания case'а данные появляются до 10 минут, после создания пространства — до часа.

```bash
# Роль для чтения аналитики (9.5+); Kibana-привилегии Cases здесь не участвуют
export ES="https://localhost:9200"
curl -sk -X POST "${ES}/_security/role/cases_analytics_reader" \
  -H 'Content-Type: application/json' -u "${ES_USER}:${ES_PASSWORD}" \
  -d '{
    "indices": [{
      "names": [".cases", ".cases-activity", ".cases-attachments"],
      "privileges": ["read", "view_index_metadata"],
      "allow_restricted_indices": true
    }]
  }'
# → {"role":{"created":true}}
```

`allow_restricted_indices: true` обязателен — индексы скрытые. Роль даёт доступ к данным **всех** пространств и решений, поэтому в запросах и дашбордах фильтруйте по `space_id` и `owner`. В версии 9.2–9.4 роль выдаётся на паттерн `.internal.cases*`.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| 403 при создании/изменении case | Нет привилегии `all` Cases в разделе, соответствующем `owner` case'а | Добавить feature privilege Cases (Management/Observability/Security) под нужным owner'ом |
| 403 на push | Нет `all` Actions and Connectors либо `all` Cases | Выдать обе привилегии — push требует их одновременно |
| Case создан, но не виден в списке раздела | Несоответствие `owner` и раздела; фильтр `_find` по owner | Проверить `owner` в объекте; в `_find` убрать фильтр или указать нужный |
| Алерт не привязывается | Превышен лимит 1000 алертов на case; неверный `type`/`index`; case другого owner'а | Проверить `totalAlerts`, массивы `alertId`/`index` одинаковой длины, owner |
| Шаблон при создании игнорируется | `xpack.cases.templates.enabled` выключен — в 8.19 и ранних 9.x по умолчанию `false` | Включить настройку в `kibana.yml`; передать `template.id` (и опц. `version`) |
| Отклонение PATCH с некорректным `version` | Устаревший `version` — case изменён параллельно | Повторить чтение (`_find`/get) и отправить актуальный `version` |
| Пустой `alertDetailsUrl`/ссылки в case-уведомлениях | Не задан `server.publicBaseUrl` | Задать публичный URL ([Эксплуатация](./kibana_production_operations.md)) |
| 403 при удалении case'а или комментария | Нет суб-привилегии **Delete** при включённом **Customize sub-feature privileges** | Включить Delete для Cases в нужном разделе (Management/Observability/Security) |
| 403 при привязке алертов | Нет `all` Cases либо нет привилегии на алерты своего решения (с 9.4: Security → Alerts, Observability) | Выдать `all` Cases плюс соответствующую привилегию алертов |
| Пользователь не назначается на case | Нет user profile — ни разу не входил в Kibana; либо нет `all` Cases / суб-привилегии **Assign users** | Попросить пользователя войти один раз; выдать `all` Cases |
| Файл не загружается в case | Превышен `xpack.cases.files.maxSize` либо MIME-тип не в `xpack.cases.files.allowedMimeTypes` | Увеличить лимит или расширить список разрешённых типов |
| PATCH / DELETE отклоняется при пачке | В одном запросе больше 100 case'ов (или больше 100 `ids` в delete) | Разбить на пачки не более 100 |
| Аналитические индексы пустые или отстают | Ещё не отработала фоновая сверка (v2 — до ~30 минут); в 9.2–9.4 — до часа после создания пространства либо выключен `xpack.cases.analytics.index.enabled` | Дождаться синхронизации; проверить настройку v1 |
| 403 от Elasticsearch на `.cases*` | Нет ES-привилегий либо не задан `allow_restricted_indices` | Роль с `read` + `view_index_metadata` и `allow_restricted_indices: true` (см. «Аналитика cases») |

## Best Practices

* **Задавайте `owner` сознательно** — это не «формальность», а раздел привилегий и видимости; выбирайте его по приложению, где команда реально работает с инцидентами.
* **Теги и severity вместо свободного текста** в title: `_find` фильтрует по `tags`/`severity`, а отчётность по инцидентам строится на этих полях.
* **`syncAlerts: true`** для любых автоматизированных сценариев — иначе закрытые case'ы оставляют алерты висеть активными.
* **Пакетная привязка алертов** (массив в одном запросе) вместо серии вызовов: меньше запросов и атомарность.
* **Триаж через Workflows, а не вручную**: создание case, тегирование и уведомление — шаги [Workflows](./kibana_workflows.md); ручной цикл оправдан только для редких тяжёлых инцидентов.
* **Проверяйте лимиты до того, как инцидент вырастет**: 1000 алертов на case, 200 тегов, `title` 160 символов, 10 исполнителей и 10 custom fields — узкие места автоматизаций и массовых операций (по 100 case'ов в одном PATCH и в одном delete).
* **Суб-привилегии вместо грубых ролей**: дежурным — Delete, Re-open и Assign users; Case settings и Manage templates оставьте владельцам процесса. Это же закрывает случайное удаление инцидента с тяжёлой историей.
* **Отчётность — через аналитику, не через feature privileges**: читатели индексов `.cases*` получают Elasticsearch-роль, а в запросах всегда фильтруют по `space_id` и `owner`, иначе роль откроет инциденты всех пространств.
* **Аудит закрытия — через активность**: `GET /api/cases/{id}/user_actions/_find` отвечает на вопрос «кто и когда изменил статус»; то же самое читается из `.cases-activity` при включённой аналитике.
* **`closure_type: close-by-pushing`** — когда выгрузка в Jira/ServiceNow означает завершение работы; `close-by-user` — когда внешний трекер ведётся параллельно и закрытие решает человек.

## Дополнительная информация

* **[Alerting: Kibana Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md)** — connectors, actions, привязка правил к case.
* **[Kibana: Workflows](./kibana_workflows.md)** — автоматизация цикла обработки инцидентов.
* **[Kibana: Security Solution](./kibana_security_solution.md)** — detection rules и алерты Security-владельца cases.
* **[Kibana: Observability](./kibana_observability.md)** — burn rate и другие правила, чьи алерты привязываются к cases.
* **[Инцидент-менеджмент (концепции)](../../Concepts/Observability_and_Monitoring/incident_management.md)** — методология работы с инцидентами.
* **[Kibana API: Cases](https://www.elastic.co/docs/api/doc/kibana/group/endpoint-cases)** — полный справочник эндпоинтов.
* **[Control access to cases](https://www.elastic.co/docs/explore-analyze/cases/control-case-access)** — привилегии, суб-привилегии и доступ к аналитическим индексам.
* **[Configure case settings](https://www.elastic.co/docs/explore-analyze/cases/configure-case-settings)** — closure type, коннекторы по умолчанию, observable types.
* **[Case templates](https://www.elastic.co/docs/explore-analyze/cases/create-case-templates)** — шаблоны case и библиотека полей.
* **[Case analytics indices](https://www.elastic.co/docs/explore-analyze/cases/case-analytics-indices)** — индексы аналитики, свежесть данных и [поля](https://www.elastic.co/docs/explore-analyze/cases/case-analytics-fields).
