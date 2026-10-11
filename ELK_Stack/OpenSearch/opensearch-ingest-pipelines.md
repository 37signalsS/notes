# Ingest Pipelines (OpenSearch)

**Актуально для:** OpenSearch 2.x / 3.x.

> Ingest pipelines в OpenSearch: процессоры, преобразование документов до индексации, симуляция, привязка к индексу. Процессоры выполняются на ingest-нодах внутри кластера; для внешней обработки перед отправкой — Logstash / Data Prepper / Filebeat, см. [цепочку сбора логов](../Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md).

## Определения

* **Ingest pipeline** — упорядоченный список процессоров, выполняемых над документом между получением запроса и индексацией; хранится в cluster state как любой другой resource.
* **Processor** — отдельный шаг обработки (grok, rename, date, script...); порядок значим — каждый процессор получает выход предыдущего.
* **Ingest node** — узел с ролью `ingest` (или data-узел, которому она добавлена). Pipeline выполняет узел, получивший запрос, только если у него есть роль `ingest`; иначе обработка поручается узлу с этой ролью.
* **`default_pipeline` / `final_pipeline` / `system_pipeline`** — специальные привязки: `default_pipeline`/`final_pipeline` задаются на индексе, `system_pipeline` — системная привязка. Для одного index-запроса применяется не более трёх pipeline в порядке default → final → system.
* **`_none`** — зарезервированное имя «no-op» pipeline: `"index.default_pipeline": "_none"` отключает default pipeline для индекса.
* **Simulate** — запуск pipeline над тестовыми документами без реальной индексации (обязательный шаг отладки).
* **Data Prepper** — внешний (не внутри кластера) компонент обработки; ingest pipeline — встроенный, для простых преобразований и ML/vector-процессоров.

## Предварительные требования

* Кластер с хотя бы одним узлом, имеющим роль `ingest` (или эта роль добавлена data-узлам). Проверка: `GET _nodes/ingest`.
* Права на управление pipeline (см. раздел «Управление pipeline»).
* Для процессоров из плагинов/модулей — соответствующий плагин в сборке: `attachment` (ingest-attachment), `ml_inference` (ML Commons), `ip2geo` / `geojson-feature` (geospatial), `text_image_embedding` (neural-search).

## Как работает Ingest

Pipeline выполняется целиком на ingest-узле до того, как документ маршрутизируется и попадает на шард. Несколько аспектов, определяющих поведение:

* **Хранение.** Определения pipeline лежат в cluster state, а не в индексах. Отсюда: они входят в snapshot только при `include_global_state: true` и привязаны к cluster manager — управление ими меняет метаданные кластера.
* **Цепочка из трёх pipeline.** При обработке index-запроса OpenSearch применяет максимум три pipeline: `default_pipeline` (или pipeline, заданный в запросе), затем `final_pipeline`, затем `system_pipeline`. Системный pipeline включается настройкой `cluster.ingest.system_pipeline_enabled` (по умолчанию `true`) и не предназначен для управления пользователем.
* **Ingest metadata.** На входе документа добавляется поле `_ingest.timestamp` (время получения на ingest-узле). Его можно сохранить в документе через процессор `set` со значением `{{{_ingest.timestamp}}}`.
* **Обратная реакция на ошибку.** По умолчанию отказ любого процессора прерывает весь pipeline и документ не индексируется; поведение переопределяется параметрами `ignore_failure` и `on_failure` (см. «Обработка ошибок»).
* **Batch-enabled процессоры.** Часть процессоров (например, `text_embedding`, `sparse_encoding`) умеет обрабатывать несколько документов как батч — при индексации через Bulk API с параметром `batch_size`. Остальные процессоры работают по одному документу за проход.

## Порядок применения pipeline

```
POST /<index>/_doc?pipeline=<name>     ← pipeline из запроса (наивысший приоритет)
            │
            ▼ (если не задан)
index.default_pipeline                  ← настройка индекса
            │
            ▼
index.final_pipeline                    ← выполняется после остальных
            │
            ▼
cluster.ingest.system_pipeline          ← системный (если включён)
            │
            ▼
      индексация документа
```

* Request-level `?pipeline=` имеет приоритет над `default_pipeline`.
* `final_pipeline` выполняется после всех остальных — последний шанс нормализации; если `default_pipeline`/`final_pipeline` указывают на несуществующий pipeline, index-запросы **падают**.
* Отключить default pipeline: `"index.default_pipeline": "_none"`.
* Search pipeline (`index.search.default_pipeline`) — отдельный механизм, обрабатывает запросы поиска, а не индексации; см. [Search Pipelines](./opensearch_search_pipelines.md).

## Управление pipeline

```bash
# Создать / обновить (PUT — полная замена определения)
PUT _ingest/pipeline/nginx-normalize
{
  "description": "Normalize nginx access logs",
  "version": 2,
  "processors": [
    {
      "grok": {
        "field": "message",
        "patterns": ["%{IPORHOST:client_ip} %{USER:ident} %{USER:auth} \\[%{HTTPDATE:ts}\\] \"%{WORD:method} %{URIPATH:uri} HTTP/%{NUMBER:http_version}\" %{NUMBER:status:int} %{NUMBER:bytes:int}"]
      }
    },
    { "date": { "field": "ts", "target_field": "@timestamp", "formats": ["dd/MMM/yyyy:HH:mm:ss Z"] } },
    { "remove": { "field": ["message", "ts"] } }
  ]
}
# → {"acknowledged":true}

# Прочитать
GET _ingest/pipeline/nginx-normalize
GET _ingest/pipeline/            # все pipeline

# Удалить
DELETE _ingest/pipeline/nginx-normalize
DELETE _ingest/pipeline/*        # поддерживаются wildcards
```

Поля тела запроса:

| Поле | Обязательное | Описание |
|---|---|---|
| `processors` | Да | Массив процессоров; выполняются последовательно в указанном порядке |
| `description` | Нет | Описание pipeline |
| `version` | Нет | Числовой номер версии определения (возвращается в ответе как `_version`) |
| `on_failure` | Нет | Список процессоров, выполняемых при отказе всего pipeline |

Query-параметры: `cluster_manager_timeout` (по умолчанию 30s), `timeout` (по умолчанию 30s).

**Отличия от Elasticsearch:** OpenSearch не поддерживает в теле pipeline ключ `_meta` и не предоставляет параметр `if_version` (optimistic concurrency control) — обновление pipeline всегда перезаписывает определение. Неизвестные/неподдерживаемые параметры приводят к ошибке парсинга (`OpenSearchParseException`).

Права (OpenSearch Security):

* создание/обновление — `cluster:admin/ingest/pipeline/put`;
* чтение — `cluster:admin/ingest/pipeline/get`;
* удаление — `cluster:admin/ingest/pipeline/delete`;
* симуляция — `cluster:admin/ingest/pipeline/simulate`;
* список grok-паттернов — `cluster:admin/ingest/processor/grok/get`.

Права выдаются в `roles_mapping` группе администраторов; без них запросы к `_ingest/pipeline/*` возвращают `403`.

## Доступ к данным документа

В процессорах, поддерживающих шаблоны (Mustache), поля документа подставляются через `{{field}}`; для вложенных полей — `{{a.b}}`. Двойные фигурные скобки экранируют HTML — для «сырых» значений и дат используют тройные `{{{field}}}`.

```bash
# Сохранить время получения документа на ingest-узле
PUT _ingest/pipeline/keep-timestamp
{
  "processors": [
    { "set": { "field": "ingest_time", "value": "{{{_ingest.timestamp}}}" } }
  ]
}

# Динамическое поле из нескольких источников
{ "set": { "field": "full_name", "value": "{{first}} {{last}}" } }
```

В процессоре `script` доступ к документу идёт через `ctx`: чтение `ctx.field`, запись `ctx.field = value`. Проверка на отсутствие поля — через null-safe оператор `?.` (например, `ctx.app?.env == 'debug'`), чтобы избежать `NullPointerException` на вложенных полях.

## Симуляция

```bash
# Симуляция конкретного pipeline
POST _ingest/pipeline/nginx-normalize/_simulate
{
  "docs": [
    { "_source": { "message": "10.0.0.1 - - [07/Oct/2026:12:00:00 +0000] \"GET / HTTP/1.1\" 200 1234" } }
  ]
}
# → docs[].doc._source: разобранные client_ip, method, status, @timestamp...

# Симуляция ПОСЛЕДНЕГО созданного pipeline (без имени)
POST _ingest/pipeline/_simulate
{
  "docs": [ { "_source": { "level": "ERROR" } } ]
}

# Inline-пайплайн без сохранения (проверка набора процессоров)
POST _ingest/pipeline/_simulate
{
  "pipeline": { "processors": [ { "lowercase": { "field": "level" } } ] },
  "docs": [ { "_source": { "level": "ERROR" } } ]
}
```

Тело: `docs` — обязательный массив; каждый элемент содержит `_source` (обязательное), а также `_id` и `_index`. Опционально задаётся `pipeline`. Query-параметр `verbose` (`true`) показывает результат применения каждого процессора по шагам. Симуляция возвращает `doc.error` при отказе процессора — показывает, на каком шаге и почему падает реальный документ.

## Процессоры

Стандартные процессоры, поставляемые с OpenSearch (доступность на конкретном кластере — `GET /_nodes/ingest?filter_path=nodes.*.ingest.processors`):

| Группа | Процессоры |
|---|---|
| Разбор текста | `grok`, `dissect`, `csv`, `json`, `kv`, `user_agent`, `fingerprint` |
| Преобразование значений | `convert`, `date`, `date_index_name`, `lowercase`, `uppercase`, `trim`, `gsub`, `split`, `join`, `sort`, `copy`, `rename`, `set`, `append`, `bytes`, `urldecode` |
| Структура документа | `remove`, `remove_by_pattern`, `dot_expander`, `html_strip` |
| Сетевые / гео | `community_id`, `geoip`, `ip2geo`, `geojson-feature` |
| Логика | `script` (Painless), `fail`, `drop`, `foreach`, `pipeline` (вложенный), `condition`-логика через `if` у любого процессора |
| ML / векторы | `ml_inference`, `text_embedding`, `text_chunking`, `sparse_encoding`, `text_image_embedding` |

Ключевые особенности:

* **`if` / `tag` / `description` / `ignore_failure` / `on_failure`** доступны у любого процессора: условный запуск, идентификация в ошибках, описание и обработка отказа.
* **`script`** — Painless над `ctx`; основной способ обогащения вычисляемыми полями.
* **`pipeline`** — вызов другого pipeline (модульность, переиспользование).
* **`geoip` и `ip2geo` — разные процессоры.** `geoip` работает со статической базой MaxMind, встроенной в кластер. `ip2geo` (появился в 2.10) — отдельный процессор: работает через управляемый data source (system index), требует плагина `opensearch-geospatial` и настраивается через `_plugins/geospatial/ip2geo/datasource`, параметры — `field` (обязателен), `datasource` (обязателен), `target_field` (по умолчанию `ip2geo`), `properties`, `ignore_missing`.
* **Batch-enabled только два процессора** — `text_embedding` и `sparse_encoding`; они обрабатывают батч документов при индексации через Bulk API с параметром `batch_size`. Все остальные процессоры работают по одному документу.
* **Enrich-процессора в OpenSearch нет** (в отличие от Elasticsearch `enrich` processor). Обогащение справочником: `script`-процессором по закэшированным данным, lookup на стороне Logstash (`translate` filter), либо денормализация при подготовке данных.
* **Нет процессора `terminate`** (в отличие от Elasticsearch). Прервать обработку можно процессором `fail` (с ошибкой) или `drop` (отбросить документ без ошибки).

```bash
# Процессор с условием
PUT _ingest/pipeline/errors-only
{
  "processors": [
    {
      "drop": {
        "if": "ctx.level != 'error' && ctx.level != 'fatal'",
        "ignore_failure": true
      }
    },
    { "set": { "field": "escalated", "value": true, "if": "ctx.http?.status_code != null && ctx.http.status_code >= 500" } }
  ]
}
```

## Обработка ошибок

По умолчанию отказ процессора прерывает весь pipeline, и документ не индексируется. Управление поведением:

* **`ignore_failure: true`** у процессора — отказ игнорируется, pipeline продолжается со следующего процессора. Применяют только там, где потеря шага безопасна.
* **`on_failure`** у процессора — список процессоров, выполняемых сразу после отказа этого процессора. Если `on_failure` задан (пусть и пустым списком), OpenSearch выполняет остальные процессоры pipeline, а не прерывает его.
* **`on_failure`** на уровне всего pipeline (в теле определения) — вызывается при отказе любого процессора, если у того нет собственного `on_failure`.

```bash
# Fallback для необязательного поля
{
  "date": {
    "field": "timestamp_field",
    "formats": ["yyyy-MM-dd HH:mm:ss"],
    "target_field": "@timestamp",
    "on_failure": [
      { "set": { "field": "ingest_error", "value": "failed" } }
    ]
  }
}
```

## Привязка к индексу

```bash
# Через запрос
POST /service-logs/_doc?pipeline=nginx-normalize
{ "message": "10.0.0.1 - - [07/Oct/2026:12:00:00 +0000] \"GET / HTTP/1.1\" 200 1234" }

# Автоматически для всех записей в индекс
PUT /service-logs/_settings
{
  "index.default_pipeline": "nginx-normalize",
  "index.final_pipeline": "common-normalize"
}

# В шаблоне — новые индексы получают pipeline сразу (см. Index Templates)
# "template": { "settings": { "index.default_pipeline": "nginx-normalize" } }

# Bulk: pipeline задаётся на уровне индекса в action-строке или query-параметром запроса
POST _bulk?pipeline=nginx-normalize
```

## Настройки и производительность

Кластерные настройки (динамические, меняются через `PUT /_cluster/settings`):

| Настройка | По умолчанию | Назначение |
|---|---|---|
| `cluster.ingest.max_number_processors` | `Integer.MAX_VALUE` | Максимально допустимое число процессоров в одном pipeline. Считаются и процессоры, и процессоры из `on_failure`; превышение при создании pipeline → `IllegalStateException` |
| `cluster.ingest.system_pipeline_enabled` | `true` | Включает системный pipeline |
| `ingest.common.processors.allowed` | не задано (все разрешены) | Список разрешённых процессоров модуля ingest-common; явный пустой список `[]` отключает их все. Отключение ранее работавшего процессора ломает использующие его pipeline после перезапуска узла |
| `ingest.useragent.processors.allowed` | не задано (все разрешены) | Список разрешённых процессоров модуля ingest-user-agent |
| `ingest.user_agent.cache_size` | `1000` | Размер кэша разобранных User-Agent (LRU) |
| `ingest.grok.watchdog.interval` | `1s` | Период проверки «зависших» grok-выражений |
| `ingest.grok.watchdog.max_execution_time` | `1s` | Порог выполнения grok, после которого срабатывает watchdog |

Практика по производительности: держать число процессоров в pipeline минимальным и избегать тяжёлых `script` и `grok` по множеству паттернов; большие объёмы `grok`-обработки выносить на агент/Logstash; для векторов использовать batch-enabled процессоры через Bulk API с `batch_size`; при высокой ingest-нагрузке выделять отдельные ingest-узлы, чтобы обработка не конкурировала с data-узлами.

## Troubleshooting

### Document rejected / pipeline failed

1. `GET _ingest/pipeline/<name>` — проверить синтаксис.
2. `POST _ingest/pipeline/<name>/_simulate` с проблемным документом — в ответе `doc.error` покажет процессор и исключение.
3. Типовые причины: grok-паттерн не совпал (`illegal_argument_exception` — grok ожидает совпадения), `date` не смог разобрать строку (задать `formats`), `convert` получил нечисловое значение, достигнут `cluster.ingest.max_number_processors` (`IllegalStateException`).
4. Для необязательных шагов — `ignore_failure: true`; для динамических данных — `if`-условие.

### Индекс перестал принимать записи после правки

1. Проверить `index.default_pipeline`/`index.final_pipeline`: ссылка на удалённый pipeline ломает все index-запросы.
2. `PUT /<index>/_settings` с `"index.default_pipeline": "_none"` или восстановить pipeline.
3. Найти виновника: временно включить симуляцию на копии документа или отвязать pipeline, чтобы подтвердить причину.

### `403` при работе с pipeline

1. Причина — отсутствие соответствующего `cluster:admin/ingest/pipeline/*` права (put/get/delete/simulate) у роли.
2. Проверить `roles_mapping` и выдать нужное право административной группе.

### Медленная индексация

1. Убрать тяжёлые `script`-процессоры, сократить число процессоров, проверить `time` в ingest stats (`GET _nodes/stats/ingest`).
2. Тяжёлые преобразования (`grok` по многим паттернам, `ip2geo` — обращение к data source) перенести на сторону агента/Logstash.
3. Проверить, не дублируется ли обработка: один и тот же документ не должен проходить pipeline дважды (например, через `pipeline`-процессор и `default_pipeline`).

### Отказ отдельного документа в bulk

1. В ответе `_bulk` у элемента `status: 400` и `error.type` с указанием процессора.
2. Ошибочные элементы не блокируют остальные; логировать их и переиндексировать после исправления.

### Диагностика отказов pipeline

Метрики по каждому pipeline и процессору: `GET /_nodes/stats/ingest?filter_path=nodes.*.ingest`. В ответе — `count`/`failed`/`time_in_millis` по pipeline и по каждому процессору; процессоры без `tag` отображаются обезличенно, поэтому `tag` полезен для точной идентификации проблемного шага.

## Best Practices

1. Проектировать pipeline в режиме simulate: сначала `_simulate` на выборке документов, потом привязка к индексу.
2. `default_pipeline` — основной механизм автоматизации; `?pipeline=` в запросе — только для явных сценариев.
3. `final_pipeline` — для гарантированной нормализации (типизация, удаление служебных полей), независимо от того, какой pipeline указал клиент.
4. Версионировать pipeline (`version` в определении) и хранить в Git; обновление — PUT-заменой (optimistic concurrency в OpenSearch для pipeline отсутствует).
5. `ignore_failure: true` — только там, где отказ безопасен; контролировать фактические отказы по ingest-метрикам (`GET _nodes/stats/ingest` → `failed`).
6. Тяжёлую обогащающую логику (внешние справочники, GeoIP-базы) выносить в Logstash/Data Prepper, оставляя ingest pipeline для простых преобразований.
7. Не создавать десятки микро-pipeline ради абстракции — каждый шаг добавляет проход по документу; `pipeline`-процессор использовать для реально переиспользуемых блоков.

## Дополнительная информация

* [Ingest Pipelines (Elasticsearch)](../Elasticsearch/elasticsearch_ingest_pipelines.md) — аналог с enrich-процессором; общая теория процессоров и API.
* [Index Templates (OpenSearch)](./opensearch-index-templates.md) — `default_pipeline` в шаблоне.
* [Цепочка сбора логов Fluent Bit → Kafka → Vector → OpenSearch](../Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md) — обработка на стороне агентов.
* [Search Pipelines](./opensearch_search_pipelines.md) — зеркальный механизм для фазы поиска.
* [Grok/Dissect паттерны](../grok_dissect_patterns.md) — справочник паттернов для grok.
