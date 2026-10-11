# Mapping и индексация (OpenSearch)

**Актуально для:** OpenSearch 2.x / 3.x. Типы mapping удалены в 2.0 (один индекс — одна роль, без `_type`).

> Как OpenSearch описывает структуру документов: типы полей, параметры mapping, dynamic и explicit mapping, dynamic templates, метаполя, лимиты схемы и переиндексация. Общие принципы совместимы с Elasticsearch; OpenSearch-специфика — `flat_object`, свой список типов, `strict_allow_templates` / `false_allow_templates` и API-пути.

## Определения

* **Mapping** — схема индекса: тип, анализатор и параметры каждого поля. Задаётся при создании индекса или дополняется позже.
* **Dynamic mapping** — автосоздание полей при индексации документа с неизвестным полем (по умолчанию `dynamic: true`).
* **Explicit mapping** — явное описание полей в `mappings.properties`; рекомендуемый подход для production.
* **Dynamic templates** — правила, по которым поля, добавляемые динамически, получают нужный mapping по имени, пути или JSON-типу.
* **Mapping explosion** — деградация кластера из-за огромного числа полей (тысячи subfields), каждый из которых создаёт собственные структуры данных; основная причина, по которой логи с «плоскими» динамическими ключами маппят в `flat_object` или `keyword`.
* **`flat_object`** — тип (с 2.7), хранящий весь JSON-объект как строку: subfields доступны через dot-нотацию, но не индексируются (не создаётся inverted index по subfields).
* **Multi-field** — несколько представлений одного значения: например `text` + sub-field `keyword` для сортировки и агрегаций.
* **Метаполя** — служебные поля документа (`_source`, `_id`, `_index`, `_routing`, `_ignored`), которыми управляет OpenSearch, а не mapping.

## Типы полей

OpenSearch группирует поддерживаемые типы по назначению и структуре данных:

| Категория | Типы |
|---|---|
| Ядро | `alias`, `boolean`, `binary` (Base64) |
| Строки | `text`, `match_only_text`, `keyword`, `constant_keyword`, `icu_collation_keyword`, `wildcard`, `token_count`, `version` |
| Числа | `byte`, `short`, `integer`, `long`, `unsigned_long`, `half_float`, `float`, `double`, `scaled_float` |
| Даты | `date` (мс), `date_nanos` (нс) |
| IP | `ip` (IPv4/IPv6) |
| Гео / декартовы координаты | `geo_point`, `geo_shape`, `xy_point`, `xy_shape` |
| Диапазоны | `integer_range`, `long_range`, `double_range`, `float_range`, `ip_range`, `date_range` |
| Объекты | `object`, `nested`, `flat_object`, `join` (parent/child) |
| Автодополнение | `completion`, `search_as_you_type` |
| Векторный поиск | `knn_vector` (dense), `sparse_vector` (neural sparse) |
| Специализированные | `semantic`, `rank_feature`, `rank_features`, `percolator`, `star_tree`, `derived` |

Особенности отдельных типов:

* **`match_only_text`** (2.12+) — вариант `text` для полнотекстового поиска: не хранит позиции, частоты и нормы, отключает скоринг (все совпадения получают constant score `1.0`), экономит место. Поддерживает все типы запросов, кроме `interval` и `span`.
* **`scaled_float`** — хранит значение как `long` со множителем `scaling_factor` (например, `"scaling_factor": 100` для двух знаков после запятой); экономит место точнее, чем `float`.
* **`icu_collation_keyword`** — `keyword` с правилами collation для языко-зависимой сортировки.
* **`constant_keyword`** — одно и то же значение для всех документов индекса (эффективная фильтрация по высокоспецифичному признаку).
* **`knn_vector`** — требует `"settings": { "index": { "knn": true } }` и параметров `dimension` / `method`; пример создания векторного индекса — в [обзоре OpenSearch](./opensearch_overview.md).
* **`derived`** — поле, вычисляемое скриптом из других полей на этапе поиска, без хранения значения.

### text vs keyword — центральное различие

```json
{
  "message": { "type": "text" },
  "level":   { "type": "keyword" }
}
```

* `text` — значение проходит анализатор (нормализация, стемминг, стоп-слова), подходит для `match`/полнотекстового поиска; **нельзя** сортировать, агрегировать и фильтровать через `term` по исходной строке.
* `keyword` — значение индексируется как есть; подходит для `term`/`terms`, сортировки, агрегаций, точных фильтров; если задан `ignore_above`, значения длиннее этого порога не индексируются (но остаются в `_source`).

Практический шаблон — multi-field:

```json
{
  "properties": {
    "message": {
      "type": "text",
      "fields": {
        "keyword": { "type": "keyword", "ignore_above": 1024 }
      }
    }
  }
}
```

Поиск — по `message` (`match`), сортировка/фильтр/агрегация — по `message.keyword`.

## Параметры mapping

Поведение поля настраивают параметрами. Наиболее значимые:

| Параметр | По умолчанию | Назначение |
|---|---|---|
| `index` | `true` | Включать поле в inverted index (поиск). `false` — поле хранится, но не ищется |
| `doc_values` | `true` (кроме `text`) | Колоночное представление на диске для сортировки, агрегаций, скриптов |
| `store` | `false` | Дополнительно хранить значение отдельно от `_source` для быстрого fetch |
| `coerce` | `true` | Приводить «грязные» значения к типу (строку `"5"` к `integer`) |
| `ignore_malformed` | `false` | Пропускать значения, не парсящиеся в тип, вместо отказа всего документа |
| `ignore_above` | нет | Не индексировать `keyword`-значения длиннее N символов |
| `null_value` | `null` | Подставлять значение вместо явного `null`, чтобы поле было искомым |
| `copy_to` | нет | Копировать значение в другое (обычно сводное `keyword`) поле |
| `format` | зависит от типа | Явный формат для `date` (например `epoch_millis`, `yyyy-MM-dd`) |
| `analyzer` / `search_analyzer` / `normalizer` | `standard` | Анализатор индексации/поиска; `normalizer` — для `keyword` |
| `similarity` | `BM25` | Алгоритм скоринга для `text` |

Комбинация `index` и `doc_values` определяет возможности поля: `index: true` + `doc_values: true` — поиск и агрегации; `index:false` + `doc_values:false` — поле недоступно для запросов (только в `_source`). Для полей, которые нужны исключительно для сортировки/агрегации, оставляют `index: false, doc_values: true` — экономия инвертированного индекса.

`fielddata` на `text` не включают: он строит структуру в heap на каждый запрос. Вместо него — sub-field `keyword`.

## Dynamic mapping

При индексации документа с неизвестным полем OpenSearch создаёт mapping автоматически по JSON-типу примера:

| JSON-тип | Тип поля OpenSearch |
|---|---|
| `null` | поле не создаётся |
| `true` / `false` | `boolean` |
| целое число | `long` |
| дробное число | `float` |
| объект `{}` | `object` |
| массив `[]` | тип по первому не-null элементу (отдельного array-типа нет) |
| строка | `text` + `keyword` sub-field, **либо** `date`, если строка совпала с форматом даты (при `date_detection`), **либо** число, если включён `numeric_detection` |

Это единственные типы, определяемые автоматически; всё остальное задаётся явно.

### Детекция дат и чисел

* **`date_detection`** (по умолчанию `true`) — строки, совпавшие с `dynamic_date_formats` (default `["strict_date_optional_time", "yyyy/MM/dd HH:mm:ss Z||yyyy/MM/dd Z"]`), становятся `date`. Отключается `"date_detection": false`; форматы настраиваются `"dynamic_date_formats"`.
* **`numeric_detection`** (по умолчанию `false`) — строки-числа (`"19.99"`) маппятся как `float`/`long`. Рекомендуется вместо этого использовать explicit mapping.

### Управление автодобавлением полей

```json
{
  "mappings": {
    "dynamic": "strict",
    "properties": { ... }
  }
}
```

| Значение | Поведение |
|---|---|
| `true` (по умолчанию) | новые поля маппятся динамически |
| `false` | новые поля индексируются в `_source`, но не маппятся (не ищутся) |
| `strict` | документ с немаппленным полем отклоняется (`strict_dynamic_mapping_exception`) |
| `strict_allow_templates` (2.16+) | поля, совпавшие с dynamic template, добавляются; остальные отклоняются, как при `strict` |
| `false_allow_templates` (3.x) | совпавшие с template добавляются; остальные не маппятся (как `false`) |

`strict_allow_templates` и `false_allow_templates` позволяют разрешить только заранее описанные поля, не открывая схему целиком. Значение `dynamic` можно задавать и объекту (для его поддерева); вложенные объекты наследуют его от родителя.

### Dynamic templates

Правила сопоставления динамически добавляемых полей: по имени (`match`/`unmatch`), по пути (`path_match`/`path_unmatch`) и по JSON-типу (`match_mapping_type`); `match_pattern: regex` включает регулярные выражения в `match` (по умолчанию `simple`). Параметры `match`, `unmatch`, `match_mapping_type` по умолчанию `null`.

```bash
PUT /service-logs
{
  "mappings": {
    "dynamic_templates": [
      {
        "strings_as_keyword": {
          "match_mapping_type": "string",
          "mapping": {
            "type": "text",
            "fields": {
              "keyword": { "type": "keyword", "ignore_above": 1024 }
            }
          }
        }
      },
      {
        "status_fields_as_short": {
          "match_mapping_type": "string",
          "path_match": "status*",
          "mapping": { "type": "short" }
        }
      },
      {
        "nested_labels_as_flat": {
          "match_mapping_type": "object",
          "match": "*",
          "mapping": { "type": "flat_object" }
        }
      }
    ],
    "properties": { ... }
  }
}
```

Порядок: шаблоны проверяются сверху вниз, применяется первое совпадение.

## Explicit mapping

```bash
PUT /service-logs
{
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "@timestamp": { "type": "date" },
      "level":      { "type": "keyword" },
      "service":    { "type": "keyword" },
      "host":       { "type": "keyword" },
      "duration_ms": { "type": "float" },
      "client_ip":  { "type": "ip" },
      "message": {
        "type": "text",
        "analyzer": "standard",
        "fields": { "keyword": { "type": "keyword", "ignore_above": 2048 } }
      },
      "tags":  { "type": "keyword" },
      "http": {
        "properties": {
          "status_code": { "type": "integer" },
          "method":      { "type": "keyword" },
          "path":        { "type": "keyword" }
        }
      }
    }
  }
}
# → {"acknowledged":true,"shards_acknowledged":true,"index":"service-logs"}
```

Правила:

* **Тип существующего поля изменить нельзя** — только параметры (`analyzer`, `ignore_above`, `format`, `copy_to` и т.д.). Смена типа — reindex в новый индекс.
* Добавлять новые поля в `properties` существующего mapping можно.
* Удалять поля из mapping нельзя (старые значения остаются в сегментах до merge/reindex).
* Массив: передавайте массив значений одного типа; тип берётся из первого не-null элемента. Пустой массив — валидное поле с нулём элементов.

```bash
# Дополнение mapping новым полем
PUT /service-logs/_mapping
{
  "properties": {
    "trace_id": { "type": "keyword" }
  }
}

# Просмотр mapping
GET /service-logs/_mapping
GET _mapping                                  # все индексы
GET /service-logs/_mapping/field/message.keyword
```

## flat_object против mapping explosion

```json
{
  "mappings": {
    "properties": {
      "labels": { "type": "flat_object" }
    }
  }
}
```

* Весь объект хранится как строка; subfields доступны через dot-нотацию. Инвертированный индекс по subfields не создаётся: чтение дёшево, число полей в индексе не растёт.
* Поддерживаются точные запросы по subfields: `term`, `terms`, `terms_set`, `prefix`, `range`, `match`, `multi_match`, `query_string`, `simple_query_string`, `exists`, `wildcard`.
* Не поддерживаются: типо-зависимый парсинг, числовые операции (сравнение/сортировка), text analysis, highlighting, агрегации по subfields через dot-нотацию. Доступ к значениям subfields через Painless в 2.7 не поддерживался.
* Ограничение на длину значения в dot-нотации — 2²⁴ − 1.
* Когда применять: значение и subfields в основном читаются, а не используются как критерий поиска; ключи динамические и их может быть тысячи.
* Когда не применять: нужен быстрый точный поиск/агрегация по конкретным subfields — маппить их явно.

Альтернативы: `copy_to` для сбора значений в одно `keyword`-поле; `ignore_above` для защиты от слишком длинных keyword-значений; `dynamic: strict` для жёсткого контроля схемы.

## Метаполя документа

* **`_source`** — исходный JSON документа. Отключается `"mappings": { "_source": { "enabled": false } }`; при отключении перестают работать `_reindex`, `_update`, `_update_by_query`, `get`, а также отладка запросов и агрегаций по исходному документу. Поля можно прореживать на входе через `includes`/`excludes` (в `_source` не попадут, но останутся индексируемыми). `index.derived_source.enabled` (более новые версии) позволяет не хранить `_source`, а реконструировать его при необходимости.
* **`_meta`** — произвольные метаданные mapping (owner, версия приложения, категория); задаются при создании индекса или через `PUT /<index>/_mapping`, возвращаются в `GET /<index>/_mapping`.
* **`_ignored`** — список полей, значения которых были пропущены из-за `ignore_malformed: true`. Заполняется только при включённом `ignore_malformed`; ищется через `term`/`terms`/`exists`.
* **`_id`**, **`_index`**, **`_routing`**, **`_version`**, **`_seq_no`**, **`_primary_term`** — идентификация, маршрутизация и управление версиями. `_id`/`_index` неизменяемы после индексации.

## Ограничения mapping (защита от mapping explosion)

Индексные настройки (все динамические, меняются через `PUT /<index>/_settings`):

| Настройка | По умолчанию | Назначение |
|---|---|---|
| `index.mapping.total_fields.limit` | `1000` | Максимум полей в индексе, включая object-маппинги и field aliases |
| `index.mapping.depth.limit` | `20` | Максимальная глубина вложенности полей |
| `index.mapping.nested_fields.limit` | `50` | Число разных `nested`-полей в индексе |
| `index.mapping.nested_objects.limit` | `10000` | Максимум nested JSON-объектов в одном документе (суммарно) |
| `index.mapping.field_name_length.limit` | `50000` | Максимальная длина имени поля |
| `index.mapper.dynamic` | `true` | Глобально разрешать/запретить динамическое добавление полей |

Диагностика роста числа полей: `GET /<index>/_mapping`, `GET /_cluster/stats`, `GET /_cat/indices?v&h=index,docs.count,store.size&s=store.size:desc`.

## Индексация документов

```bash
# Индексация с автогенерируемым _id
POST /service-logs/_doc
{
  "@timestamp": "2026-10-07T12:00:00Z",
  "level": "error",
  "service": "payment",
  "message": "connection refused",
  "http": { "status_code": 502, "method": "GET", "path": "/api/pay" }
}
# → {"result":"created","_id":"...","_version":1}

# Индексация с явным _id (PUT идемпотентен: повторная запись обновит документ)
PUT /service-logs/_doc/1
{ "level": "info", "message": "started" }

# Bulk — основа массовой индексации
POST _bulk
{ "index": { "_index": "service-logs" } }
{ "@timestamp": "2026-10-07T12:00:01Z", "level": "info", "message": "ok" }
{ "index": { "_index": "service-logs" } }
{ "@timestamp": "2026-10-07T12:00:02Z", "level": "error", "message": "failed" }
```

Ключевые моменты:

* **`refresh_interval`** — по умолчанию `1s`: документ виден в поиске через секунду после индексации. Для идемпотентных пайплайнов — `?refresh=wait_for`; для массовой загрузки — `"-1"` на время + восстановить.
* **Optimistic concurrency** — `?if_seq_no=<n>&if_primary_term=<n>` (значения из `_seq_no`/`_primary_term` предыдущего ответа). Конфликт версий возвращает `409` `version_conflict_engine_exception`. `X-Opaque-Id` — это заголовок трассировки, а не управление версиями.
* **Отклонённые документы** — bulk возвращает поэлементные ошибки: `mapper_parsing_exception` (несоответствие типа), `strict_dynamic_mapping_exception` (`dynamic: strict`), `illegal_argument_exception` (например невалидный `ip`).
* **Валидация `ip`/чисел** — параметр `ignore_malformed: true` на поле позволяет пропускать битые значения (они попадут в `_ignored`), а не отклонять весь документ.

```bash
# Ошибки bulk: тело ответа, items[].status / items[].error.type
POST _bulk
{ "index": { "_index": "service-logs" } }
{ "level": 12345 }
# → items[0].error.type = "mapper_parsing_exception"
```

## Смена mapping и переиндексация

Тип существующего поля изменить нельзя, поэтому смена схемы — это создание нового индекса с целевым mapping, копирование данных и переключение алиаса:

```bash
# 1. Создать новый индекс с нужным mapping
PUT /service-logs-v2
{
  "mappings": {
    "properties": {
      "duration_ms": { "type": "double" },
      "http": {
        "properties": { "status_code": { "type": "short" } }
      }
    }
  }
}

# 2. Переиндексировать данные
POST /_reindex
{
  "source": { "index": "service-logs" },
  "dest":   { "index": "service-logs-v2" }
}
# → {"created":... , "version_conflicts":0, "failures":[]}
```

Параметры `_reindex`:

| Параметр | Значение |
|---|---|
| `wait_for_completion` | `false` — асинхронно; запрос возвращает `task`, прогресс через `GET /_tasks/<task>` |
| `requests_per_second` | троттлинг (по умолчанию `-1` — без ограничений); изменение на ходу — `POST /_reindex/<task>/_rethrottle?requests_per_second=200` |
| `slices` | число параллельных подзадач; `auto` — автоматически |
| `max_docs` | ограничение числа документов |
| `conflicts` | `proceed` — не останавливаться на конфликтах версий |
| тело `source.query` | фильтр копируемых документов |
| тело `source._source` | список копируемых полей |
| тело `script` | трансформация/удаление полей на лету |
| тело `dest.op_type: "create"` | только создание; обязателен при записи в data stream |
| тело `dest.pipeline` | ingest pipeline на принимающей стороне |

Ограничения: `_source` в источнике должен быть включён; целевой индекс создаётся заранее (settings/mappings не копируются автоматически); большие переиндексации — ресурсоёмкая операция, для продакшена — троттлинг и, при необходимости, временное `number_of_replicas: 0`.

**`_update_by_query`** переписывает документы, попавшие под запрос, без смены индекса — удобно, чтобы применить новые параметры mapping или изменить значения/удалить поля по условию:

```bash
POST /service-logs/_update_by_query
{
  "query": { "term": { "level": "error" } },
  "script": { "source": "ctx._source.escalated = true" }
}
```

Подробно про `_reindex` / `_update_by_query` (Task API, троттлинг, slices, cross-cluster) — в [Reindex, Update и Delete by Query (Elasticsearch)](../Elasticsearch/elasticsearch_reindex_updates.md) (общая теория, ES-специфика вынесена отдельно).

## Troubleshooting

### strict_dynamic_mapping_exception

1. Поле отсутствует в mapping, а `dynamic: "strict"` (или `strict_allow_templates` при несовпадении с шаблоном).
2. Решение: добавить поле в `properties`, добавить dynamic template, либо перейти на `dynamic: true`/`false` осознанно.

### mapper_parsing_exception

1. Значение не соответствует типу поля (строка в `integer`, невалидная дата).
2. Проверить `GET /<index>/_mapping` и формат значения; для дат — задать `format` в mapping.
3. Для «битых» значений — `ignore_malformed: true` на поле (значения попадут в `_ignored`).

### Mapping explosion / рост heap

1. `GET /<index>/_mapping` — оценить число полей; смотреть `limit of total fields [...] has been exceeded`.
2. Динамические ключи (метрики из логов, атрибуты) — `flat_object`, либо explicit mapping + `dynamic: false`.
3. Длинные строки в `keyword` — `ignore_above`.
4. Экстренная остановка роста: `index.mapper.dynamic: false` (прекратить добавление новых полей). Постоянное решение — новый индекс с явным mapping и лимитами, `_reindex` с фильтрацией полей, переключение алиаса.

### term-запрос по строке возвращает 0 hits

1. Поле `text` — использовать `.keyword` sub-field или `match`. См. [Query DSL](./opensearch-query-dsl-search.md).

### Bulk вернул HTTP 200, но данные не проиндексированы

1. Проверить `errors: true` и `items[].error.type` — ошибки поэлементные, HTTP-статус запроса не отражает судьбу документов.

## Best Practices

1. Explicit mapping для production; `dynamic: strict` там, где схема известна полностью.
2. Всё, что сортируется/агрегируется/фильтруется точным совпадением — `keyword` (или multi-field `*.keyword`).
3. Динамические ключи — `flat_object` или шаблон с `ignore_above`, чтобы не допустить mapping explosion.
4. `ip` для сетевых адресов (валидация + компактное хранение), `date` с явным `format` для нестандартных форматов.
5. Массовую загрузку — через `_bulk` с отключённым `refresh_interval`, восстановив его после.
6. Смену типа — только через reindex нового индекса + переключение алиаса; заранее проектировать mapping под известные сценарии запросов.
7. Проверять отклонённые документы в ответе bulk, а не считать запрос успешным по HTTP-статусу.
8. Заполнять `_meta` (owner, версия) и версионировать mapping вместе с шаблонами — упрощает сопровождение и миграции.

## Дополнительная информация

* [Query DSL и поиск (OpenSearch)](./opensearch-query-dsl-search.md) — как искать по замапленным полям.
* [Index Templates (OpenSearch)](./opensearch-index-templates.md) — автоматическое применение mapping к новым индексам.
* [Ingest Pipelines (OpenSearch)](./opensearch-ingest-pipelines.md) — преобразование данных до индексации.
* [ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md) — ротация индексов при изменении схемы.
* [Reindex, Update и Delete by Query (Elasticsearch)](../Elasticsearch/elasticsearch_reindex_updates.md) — общая теория массовых операций.
* [Elasticsearch Mapping](../Elasticsearch/elasticsearch_mapping_and_indexing.md) — аналог в Elasticsearch (общие принципы).
