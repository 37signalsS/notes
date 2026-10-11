# Elastic Common Schema (ECS)

**Актуально для:** ECS 9.5.x (спецификация, версионируется отдельно от стека; major-версии ECS планируются синхронно с major-релизами Elastic Stack)

> Справка по Elastic Common Schema: назначение, принципы именования и типизации, миграция и настройка ECS-совместимости в компонентах стека. Определение ECS в контексте стека — в [ELK стек: Обзор](./elk_stack_overview.md); ECS-режим Logstash — в [Logstash: Обзор](./Logstash/logstash_overview.md); ECS-имена в grok — в [Grok и Dissect Patterns](./grok_dissect_patterns.md).
>
> Связанные темы: индексация и маппинг — [Mapping and Indexing](./Elasticsearch/elasticsearch_mapping_and_indexing.md); шаблоны и data streams — [Index Templates](./Elasticsearch/elasticsearch_index_templates.md); сбор в Beats — [Filebeat Overview](./filebeat_overview.md); парсинг строк — [Grok и Dissect Patterns](./grok_dissect_patterns.md).

## Определения

* **ECS (Elastic Common Schema)** — открытая (Apache 2.0) спецификация имён полей, их типов в Elasticsearch и описаний для событий логов, метрик, трейзов и security-событий. Цель — единообразие данных из разных источников, чтобы дашборды, правила детектирования и запросы работали для любого источника без переименований.
* **Field set (набор полей)** — логическая группа родственных полей с общим префиксом: `source.*` (источник события), `destination.*`, `host.*`, `process.*`, `event.*`, `error.*`, `http.*`, `network.*`, `user.*` и др. Каждый field set документирует назначение полей и их типы.
* **Custom field (кастомное поле)** — поле вне спецификации. ECS — permissive-схема: непокрытые данные добавляются своими именами (соглашение — точка вместо подчёркивания: `myapp.order_id`), это не нарушение. Конфликт имён с будущими ECS-полями — единственная цена свободы; стратегии снижения риска — в сценарии 3.
* **`ecs.version`** — поле события, фиксирующее версию ECS, по которой событие нормализовано; используется для проверки совместимости при чтении данных. Guidelines предписывают его использовать (Use the `ecs.version` field); агенты и шаблоны выставляют автоматически.
* **Text multi-field convention** — соглашение ECS о полнотекстовом поиске: каноническое поле индексируется как `keyword`, полнотекстовый поиск вынесен в multi-field `<field>.text` (обратное к дефолту Elasticsearch, где каноническое поле — `text`, а `keyword` лежит в `<field>.keyword`). Исключения — `message` и `error.message`: они индексируются как `match_only_text` (семейство `text`, без multi-field; полнотекстовый поиск — прямо по полю). Миграция `text` → `match_only_text` стала GA в ECS 8.0.0.
* **Data stream имя `<type>-<dataset>-<namespace>`** — соглашение об именовании потоков данных, связанное с ECS: `logs-generic-default`, `metrics-system-default`, `logs-nginx-access-prod`; поля `data_stream.type/dataset/namespace` в событии согласованы с именем индекса.
* **Field Level (уровень поля)** — классификация важности поля: **core** (базовые поля, ожидаются в большинстве событий; на них пишется анализ-контент — поиски, визуализации, алерты) и **extended** (дополнительные детали, не обязательны; применимы к более узким сценариям и склонны к изменениям со временем). Уровень указывается в справочнике полей.
* **Field Maturity (статус зрелости)** — **alpha** (экспериментальное, может измениться или исчезнуть без предупреждения), **beta** (стабилизируется, возможны правки допустимых значений и семантики), **GA** (стабильное, обратно совместимое; значение по умолчанию). Введено в ECS 9.4; статус документируется на странице field set.
* **OTel Alignment Badge** — маркер отношения ECS-поля к семантическим конвенциям OpenTelemetry (семь категорий: `match`, `equivalent`, `related`, `conflict`, `OTLP`, `metric`, `n/a` — таблица в разделе «ECS и OpenTelemetry»). Маппинг хранится в schema-файлах ECS и порождает инструменты совместимости (например, field aliases в Elasticsearch).

## Основные концепции

### Зачем нужна общая схема

Без общей схемы каждый источник привносит свои имена (`src_ip`, `client_ip`, `remote_addr`, `source.ip` — одно и то же), и каждый дашборд/правило приходится писать под источник. ECS решает это:

* **Корреляция** — `source.ip` из firewall-лога и `source.ip` из proxy-лога — одно поле: `host.name`, `process.name`, `user.name` коррелируются между событиями напрямую.
* **Переиспользование контента** — правила Security, линзы Kibana, алертинг пишутся один раз и работают на любом ECS-совместимом источнике.
* **Экосистема совместима** — Beats, Elastic Agent/Integrations, Logstash-плагины пишут ECS по умолчанию; данные интеграций Elastic уже замаплены в ECS.
* **Лёгкость запоминания и вывода** — один набор имён вместо набора на источник: имена проще запомнить, а имя несуществующего поля — вывести из правил именования.
* **Защита инвестиций (future-proofing)** — будущий анализ-контент Elastic (поиски, дашборды, правила, ML-джобы) работает в среде без модификаций.

### Типизация и соглашения (Conventions)

| Правило | Суть |
|---|---|
| Целые числа | По умолчанию `long` (если иное не задано схемой) |
| Идентификаторы и коды | `keyword`, не integer: generic-поля вроде `error.code` не гарантируют числовые значения; исключения — поля с явно числовым смыслом вроде `http.response.status_code` |
| Текстовые поля | По умолчанию `keyword`; полнотекстовый поиск — в `<field>.text` (исключения: `message`, `error.message` — `match_only_text` без multi-field) |
| Multi-fields | Определяются в ECS index template; ручное переопределение маппинга поля ECS не рекомендуется |
| Массивы | Любое поле ECS может быть массивом (повторяющиеся элементы одного типа) |

Практическое следствие соглашения про keyword: фильтрация и агрегации по ECS-полям дёшевы (doc_values), а полнотекстовый поиск там, где он реально нужён, включается явно через `field.text`.

### Соглашения об именовании

Официальные правила имён ECS (применяются и к кастомным полям):

* имена в нижнем регистре; слова соединяются подчёркиванием; без спецсимволов, кроме подчёркивания;
* настоящее время (кроме полей, описывающих историческую информацию);
* единственное/множественное число отражает содержимое (`requests_per_sec`, не `request_per_sec`);
* префикс (field set) для всех полей, кроме базовых; вложенность точками;
* при приёме через API поля — вложенные JSON-объекты, а не строки с точками (Beats и Logstash делают вложенность автоматически);
* от общего к частному (структура `host.*` — от общего хоста к конкретике внутри);
* без повторов слов: `host.host_ip` → `host.ip` (исключения допускаются, когда сломать устоявшуюся convention хуже — например, `host.hostname`);
* без аббревиатур, где возможно (исключения — устоявшиеся: `ip`, `os`, `geo`).

Нюанс типов: дефолт ECS можно заменить типом из того же семейства (`keyword` → `wildcard`, `text` → `match_only_text`), если задача требует; отличия производительности и хранения нужно понимать до замены. Пример из схемы: `error.stack_trace` — `wildcard` с multi-field `error.stack_trace.text` (`match_only_text`).

### Версионирование и статус полей

* ECS версионируется по **Semantic Versioning**; major-версии планируются синхронно с major-релизами Elastic Stack (текущая линейка спецификации — 9.x, документация ECS 9.5.0).
* Поля несут статус зрелости — **alpha / beta / GA** (введены в ECS 9.4): alpha/beta-поля могут измениться или исчезнуть, GA-поля стабильны. Статус документируется на странице field set.
* Обратная совместимость: добавление полей — minor; ломающие изменения — major.

Критерии статусов (design principles ECS):

* **Alpha** — определение поля в процессе, паттерны использования не изучены, данные не валидированы на реальных нагрузках; гарантий обратной совместимости нет — не использовать в production-алертах и долгоживущих дашбордах.
* **Beta** — определение полно, паттерны изучены, данные валидированы; имя и тип маловероятно изменятся, возможны правки допустимых значений и семантики; подходит для дашбордов, правил детектирования и интеграций с пониманием возможных минорных миграций.
* **GA** — значение по умолчанию; обратно совместимо, ломающие изменения только в major-версиях.

**Что нового в линейке 9.x:**

* **9.2–9.4** — семейство `entity.*` (beta в 9.2, расширение в 9.3, `entity.attributes.*`/`entity.lifecycle.last_activity`/`entity.relationships.*` и переиспользуемый field set `entity_reference` в 9.4, RFC 0054); в 9.4 — статусы зрелости полей (атрибут `alpha`, взаимоисключающий с `beta`) и лимит `total_fields.limit` в composable-шаблоне повышен с 2000 до 2500.
* **9.5** — новые поля `vulnerability.status` (значения: `open`, `fixed`, `reopened`, `unknown`) и `host.tags`.

### ECS и OpenTelemetry

В **апреле 2023 Elastic передала ECS в OpenTelemetry** (CNCF); совместно заявлено о намерении конвергировать ECS и OTel Semantic Conventions в единую схему. Это направленное решение об эволюции обоих стандартов, а не мгновенное слияние: ECS продолжает развиваться и поддерживаться, данные в текущем формате читаются без изменений.

* В schema-файлах ECS ([github.com/elastic/ecs/tree/main/schemas](https://github.com/elastic/ecs/tree/main/schemas); маппинг добавлен в ECS 9.0.0) содержится явный **маппинг ECS-полей на OTel-атрибуты**; он же порождает инструменты совместимости (например, field aliases в Elasticsearch). Отношение поля к SemConv — одна из семи категорий:

| Badge | Суть |
|---|---|
| `match` | Имя ECS-поля совпадает с именем SemConv-атрибута, семантика (практически) одинакова |
| `equivalent` | Имя отличается, семантика та же; совместимость достижима через aliasing (field alias Elasticsearch) |
| `related` | Имя отличается, семантика связанная, но другая; aliasing недостаточен |
| `conflict` | Имя ECS-поля совпадает с namespace/атрибутом OTel SemConv, но семантика существенно отличается |
| `OTLP` | У ECS-поля есть соответствие в определении протокола OpenTelemetry (OTLP) |
| `metric` | Для ECS-поля определён соответствующий metric в OTel SemConv |
| `n/a` | Поле неприменимо в контексте OTel или не будет выравиваться из-за концептуального конфликта |

Подробности выравнивания: [OTel Alignment Overview](https://www.elastic.co/docs/reference/ecs/ecs-otel-alignment-overview) и [Field & Attributes Alignment](https://www.elastic.co/docs/reference/ecs/ecs-otel-alignment-details).
* Для пользователей это означает: инвестиции в имена ECS не теряются, путь к будущей объединённой схеме — через маппинг, а не через переименование вручную.

### ECS в компонентах стека

* **Beats / Elastic Agent**: источники по умолчанию пишут ECS-поля; для ручной нормализации в Filebeat используются processоры (`rename` для приведения имён к ECS и др.).
* **Logstash**: режим `ecs_compatibility` — `disabled` / `v1` / `v8`; с 8.x дефолт процесса — `v8` (отключение: `pipeline.ecs_compatibility: disabled` в `pipelines.yml`/`logstash.yml` либо на уровне плагина `ecs_compatibility => disabled`). Режим меняет целевые имена результата (например, geoip пишет в `[source][geo]`/`[client][geo]`), требует явного `target` у ряда плагинов, влияет на `data_stream => "auto"` (запись в data streams `<type>-<dataset>-<namespace>`).
* **Grok в Logstash и ingest-процессоре Elasticsearch**: при `ecs_compatibility => "v1"` паттерны выдают ECS-имена.
* **Elasticsearch ingest**: процессоры (geoip, user_agent, convert, dot_expander и др.) ориентированы на ECS-структуру; `reroute` работает с data stream-схемой, согласованной с ECS.
* **ECS index template**: типовые шаблоны (integrations, data streams) содержат маппинг ECS-полей; динамический маппинг подхватывает кастомные поля автоматически.

## Практические сценарии

### 1. Минимальное ECS-событие

```json
{
  "@timestamp": "2026-10-07T12:00:00.000Z",
  "message": "GET /api/health 200 12ms",
  "ecs": { "version": "9.5.0" },
  "event": { "kind": "event", "category": ["web"], "type": ["access"], "outcome": "success" },
  "host": { "name": "web-01" },
  "source": { "ip": "10.0.4.17" },
  "http": { "request": { "method": "GET" }, "response": { "status_code": 200 } },
  "url": { "path": "/api/health" },
  "process": { "name": "nginx" }
}
```

Единственное обязательное поле — `@timestamp` (Required field for all events; для data streams добавляются требования к имени потока и полям `data_stream.*`). `ecs.version` guidelines предписывают использовать как маркер версии схемы, а агенты и шаблоны выставляют его автоматически. `@timestamp`, `event.*`, `ecs.version` — базовый набор, по которому работают шаблоны и визуализации.

### 2. Переименование своих полей в ECS

```yaml
# filebeat.yml — привести legacy-имена к ECS
processors:
  - rename:
      fields:
        - from: "src_ip"
          to: "source.ip"
        - from: "user_agent_str"
          to: "user_agent.original"
      ignore_missing: true
      fail_on_error: false
```

```ruby
# Logstash: приведение к ECS
filter {
  if [client_ip] {
    mutate { rename => { "client_ip" => "[source][ip]" } }
  }
}
```

Ключевой принцип: маппить в **точные имена ECS** (включая типы: IP — `ip`, статус — `long`, идентификаторы — `keyword`), а не в похожие (`source.ip_address` уже не ECS).

### 3. Кастомные поля: стратегии снижения риска конфликта

Кастомные поля — норма для ECS (permissive-схема), но при добавлении полей в будущих версиях ECS возможен конфликт имён. Официальные стратегии снижения риска:

1. **`labels`** — если пары key/value укладываются в `keyword`, кладите их в готовое ECS-поле `labels` (объект, значения хранятся как keyword, вложенные объекты не поддерживаются):

```json
{ "labels": { "foo_id": "beef42", "env": "production" }, "message": "..." }
```

2. **Proper names (имена собственные)** — ECS старается не использовать имена инструментов, проектов и компаний, поэтому вложение в пространство с собственным именем (так делают Beats-модули) относительно безопасно:

```json
{ "http": { "request": { "method": "get" }, "response": { "status_code": 200 } },
  "url": { "original": "/favicon.ico" },
  "haproxy": { "frontend_name": "myfrontend", "backend_name": "mybackend_prod", "backend_queue": 0 } }
```

3. **Capitalization** — ECS не использует заглавных букв в именах, поэтому кастомное поле с заглавной буквы (`Proxy.FrontendName`) гарантированно не столкнётся с будущим ECS-полем `proxy.*`. Бонус: общее имя (`Proxy.*`) позволяет коррелировать разные источники. При появлении настоящего ECS-поля — миграция в два приёма: некоторое время пишутся оба варианта, потом кастомное удаляется:

```json
{ "http": { "request": { "method": "get" } },
  "Proxy": { "FrontendName": "myfrontend", "BackendName": "mybackend_prod" },
  "proxy": { "frontend_name": "myfrontend", "backend_name": "mybackend_prod" } }
```

Дополнительно: подчёркнутая (`user_firstname`) и точечная (`user.firstname`) записи могут сосуществовать в одном документе, пока нет конфликта — точечная создаёт объект, подчёркнутая — плоское поле.

### 4. Проверка, что данные соответствуют схеме

```bash
# Версия ECS в шаблоне индекса
GET _index_template/logs-generic-default
# → ... "mappings": { "dynamic_templates": ..., "_meta": { "ecs": ... } }

# Значение ecs.version в событиях
GET logs-*/_search { "size": 0,
  "aggs": { "ecs_ver": { "terms": { "field": "ecs.version" } } } }

# Как Elasticsearch реально замапил поле (keyword или text?)
GET logs-*/_mapping/field/source.ip,message,http.response.status_code
```

Ожидание для ECS-индекса: `source.ip` → `ip`, `http.response.status_code` → `long`, `host.name` → `keyword`, `message` → `match_only_text`, `url.path` → `keyword`.

### 5. Миграция на новую major-версию ECS

1. Проверить changelog целевой версии: какие поля добавлены/переименованы/помечены deprecated. Например, переход ECS 8→9 удалил deprecated-поля (`process.pgid`, `service.node.role`, inherited users) — в новых событиях они просто перестают появляться.
2. Обновить агентов/интеграции (нормализация происходит на источнике — дешевле всего).
3. Для исторических данных — либо читать как есть (старый `ecs.version` остаётся в событиях), либо переименовать пакетно через `update_by_query` ([Reindex и Update](./Elasticsearch/elasticsearch_reindex_updates.md)) при конфликтующих переименованиях.
4. Обновить правила/линзы, использующие переименованные поля.

### 6. Логи приложения: JSON-вывод под ECS

Исходная точка — приложение, которое пишет структурированные JSON-логи (как заставить писать JSON — в [Структурированном логировании](../Linux/SystemAdministration/Logging/structured_logging.md)). Целевой документ ECS:

```json
{
  "@timestamp": "2026-10-07T09:14:02.315Z",
  "message": "payment declined",
  "log": { "level": "error" },
  "service": { "name": "payments-api" },
  "trace": { "id": "4bf92f3577b34da6a3ce929d0e0e4736" },
  "span": { "id": "00f067aa0ba902b7" },
  "host": { "name": "app-1" }
}
```

Два пути, оба корректны (порядок по возрастанию предпочтения):

1.  **Писать ECS сразу в источнике** — библиотеки **ecs-logging** для вашего стека (Java, Python, Node.js и др.) или маппинг полей в коде. Если приложение подключено к [Elastic APM](elastic-apm-tracing.md), `trace.id`/`span.id` добавляются автоматически (log correlation) — это самый дешёвый и надёжный вариант.
2.  **Нормализовать на приёме** — распарсить JSON на стороне Filebeat, а имена и время привести к ECS ingest-пайплайном.

Сбор строки (filestream раскрывает JSON в корень документа):

```yaml
filebeat.inputs:
  - type: filestream
    id: app-json
    paths:
      - /var/log/payments-api/*.log
    parsers:
      - ndjson:
          target: ""           # поля JSON — на верхний уровень документа
          overwrite_keys: true
```

После разбора документ содержит исходные поля приложения (`ts`, `level`, `service`, `trace_id`, `span_id`, `message`); нормализация — пайплайном:

```bash
curl -s -u elastic:$PASS -k -X PUT "$ES/_ingest/pipeline/app-ecs?pretty" -H 'Content-Type: application/json' -d '{
  "processors": [
    { "date":    { "field": "ts", "target_field": "@timestamp",
                   "formats": ["ISO8601"], "on_failure": [{ "tag": "date-fail" }] } },
    { "rename":  { "field": "level",    "target_field": "log.level",  "ignore_missing": true } },
    { "rename":  { "field": "service",  "target_field": "service.name", "ignore_missing": true } },
    { "rename":  { "field": "trace_id", "target_field": "trace.id",   "ignore_missing": true } },
    { "rename":  { "field": "span_id",  "target_field": "span.id",    "ignore_missing": true } },
    { "set":     { "field": "ecs.version", "value": "9.5.0" } }
  ]
}'
# → {"acknowledged":true}
```

Привязать пайплайн как `default_pipeline` в index template — тогда он применяется ко всем писателям ([Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md)).

Ключевые правила:

*   **`@timestamp`** должен получать разобранное время события (`date`-процессор из `ts`), а не момент чтения — иначе все события придут со временем чтения ([Логи: временные метки](log-timestamps-and-late-events.md)).
*   **Имена — точные ECS** (`log.level`, `service.name`, `trace.id`), без самодельных вариаций: поле `level` или `svc` — это не ECS, и штатные визуализации/правила их не увидят (см. сценарий 2).
*   Если вместо JSON приложение пишет плоский текст — сначала разобрать grok-ом ([Grok и Dissect Patterns](./grok_dissect_patterns.md)); для готовых полей `trace.id`/`span.id` из APM-корреляции ничего парсить не нужно ([Elastic APM](elastic-apm-tracing.md)).
*   Готовые агенты (Filebeat, Elastic Agent) уже выставляют `host.*`, `agent.*`, `ecs.version` — добавлять их руками не нужно; проверяйте итог сценарием 4.

## Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| Правило Kibana/линза не находит поле | Источник пишет legacy-имя (`src_ip` вместо `source.ip`) | Маппинг на источнике (rename-процессор Filebeat/Logstash/ingest) |
| Агрегация падает `fielddata is disabled` или фильтр не матчитит | Поле замаплено иначе, чем в ECS (`text` вместо `keyword`) | Проверить `GET .../_mapping/field/<field>`; привести к ECS-типу миграцией маппинга |
| `ecs.version` отсутствует/разный в разных событиях | Смешанные источники с разными режимами (`ecs_compatibility: disabled` у части) | Привести все конвейеры к единому режиму, историю — читать с учётом версии |
| Поле-массив в ECS не работает в rules | Правило ожидает scalar, источник кладёт массив | Исправить на источнике (дедупликация) либо нормализовать ingest-процессором |
| Data stream отклоняет запись | Имя не соответствует `<type>-<dataset>-<namespace>` или расходится с `data_stream.*` в событии | Исправить имя/поля ([Index Templates](./Elasticsearch/elasticsearch_index_templates.md)) |
| Kibana-линза «ломается» после обновления интеграции | Поле перешло в beta/новый статус или переименовано в новой версии ECS | Проверить changelog ECS, обновить визуализацию |
| Индекс отказывает в записи: `Limit of total fields [2500] in this index has been exceeded` | Слишком много уникальных кастомных полей (динамический маппинг) | Свернуть метки в `labels.*`, дать полям префиксы (см. сценарий 3), осознанно поднять `index.mapping.total_fields.limit` |

## Best Practices

* **Пишите в ECS с источника** (агент, Logstash, ingest) — не откладывайте нормализацию на чтение: каждый потребитель не должен знать легенду имён.
* **Используйте точные имена и типы ECS**, а не свои вариации; кастомные поля — только для того, чего в ECS нет, и без подчёркиваний в именах. Для разовых key/value-меток — готовое поле `labels` (см. сценарий 3).
* **Не переопределяйте маппинг ECS-полей** в шаблонах — типы спецификации продуманы под мониторинг (keyword-first); полнотекстовый поиск добавляйте multi-field `.text`, а не заменой типа.
* **Фиксируйте `ecs.version`** в событиях — это единственный способ отличить данные разных эпох схемы при чтении.
* **Следите за статусом полей**: не стройте критичные правила на alpha/beta-полях без плана миграции.
* **При миграциях ECS** — сначала источники, потом исторические данные, потом правила; порядок обратного чтения (правила → история → источники) создаёт окно несогласованности.
* **Для новых интеграций** предпочитайте официальные Elastic Integrations: они уже пишут ECS и управляются через Fleet ([Elastic Agent и Fleet](./Elasticsearch/elastic_agent_and_fleet.md)).

## См. также

* **[ELK стек: Обзор](./elk_stack_overview.md)** — место ECS в архитектуре стека, конвергенция с OTel.
* **[Logstash: Обзор](./Logstash/logstash_overview.md)** — режим `ecs_compatibility`, примеры конфигураций в ECS.
* **[Grok и Dissect Patterns](./grok_dissect_patterns.md)** — ECS-имена в grok-паттернах.
* **[Filebeat Overview](./filebeat_overview.md)** — сбор и processоры нормализации.
* **[Mapping and Indexing](./Elasticsearch/elasticsearch_mapping_and_indexing.md)** — типы полей, multi-fields, динамический маппинг.
* **[Index Templates](./Elasticsearch/elasticsearch_index_templates.md)** — шаблоны, data streams `<type>-<dataset>-<namespace>`.
* **[Elastic Agent и Fleet](./Elasticsearch/elastic_agent_and_fleet.md)** — централизованное управление сбором, интеграции с ECS-маппингом.

### Перекрытие с существующими файлами (§0.10)

* `ELK_Stack/elk_stack_overview.md` — определение ECS и упоминание конвергенции с OTel (строки 16, 57); настоящий файл развёрнутая справка по самой схеме, overview даёт только определение и ссылку сюда.
* `ELK_Stack/Logstash/logstash_overview.md` — SSoT по настройке `ecs_compatibility` в Logstash (дефолт `v8`, отключение, влияние на плагины); здесь ECS-режим только описан со ссылкой.
* `ELK_Stack/grok_dissect_patterns.md` — упоминание `ecs_compatibility => "v1"` для grok-имён; детали — в Grok-файле, здесь — общий контекст.
* `ELK_Stack/filebeat_overview.md` — processоры Filebeat (`rename` для ECS); здесь лишь пример со ссылкой.
* `Elasticsearch/elasticsearch_index_templates.md` — SSoT по шаблонам и data stream-именам; настоящий файл ссылается на соглашение `<type>-<dataset>-<namespace>` как на часть ECS-контракта.
* `ELK_Stack/log-timestamps-and-late-events.md` — SSoT по семантике `@timestamp`, `event.created`, `event.ingested`; здесь поле только упомянуто как обязательное.
* `ELK_Stack/elastic-apm-tracing.md` — SSoT по корреляции логов и трасс (`trace.id`/`span.id`); здесь поля приведены в примере.
* `Linux/SystemAdministration/Logging/structured_logging.md` — SSoT по форматам структурированного логирования; здесь — приём JSON-логов в ECS.
* `ELK_Stack/Elasticsearch/elasticsearch_ingest_pipelines.md` — SSoT по ingest-процессорам (`date`/`rename`/`set`); здесь — пример ECS-пайплайна.
