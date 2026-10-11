# Elasticsearch: Оптимизация производительности поиска (Search Tuning)

**Актуально для:** Elasticsearch 9.5.x (9.5.5) / 8.19 LTS (8.19.23)

> Руководство по оптимизации производительности поиска в Elasticsearch. Рассматриваются архитектура поиска, кэширование, query profiling, routing, лимиты, circuit breakers, мониторинг и устранение неполадок.
>
> Связанные темы: тюнинг индексации и сегментов — [Troubleshooting индексации](./elasticsearch_troubleshooting_indexing.md); мониторинг стека — [Stack Monitoring](./elasticsearch_stack_monitoring.md); маппинг и анализаторы — [Mapping и индексирование](./elasticsearch_mapping_and_indexing.md); предвычисление агрегатов — [Rollup и Transform](./elasticsearch_rollup_transform.md).

## Определения

* **Query Cache** — node-level LRU-кэш результатов запросов, выполненных в **filter context** (bitset совпадений). Один на узел, общий для всех шардов. Не кэширует агрегации и запросы в query context.
* **Request Cache** — shard-level кэш полных ответов на запросы с `size: 0` (aggregations, counts, suggestions).
* **Fielddata** — in-memory структура для `text`-полей (aggregations/sort); на text-полях отключена по умолчанию.
* **Global Ordinals** — унифицированное отображение term → ordinal поверх doc_values сегментов; используется bucket-агрегациями по `keyword`/`ip`/`flattened`, сортировкой и `join`. Хранится в field data cache (heap).
* **Doc Values** — columnar on-disk структура для sort/aggregations/scripting; по умолчанию включена для большинства полей.
* **Norms** — нормализующие факторы для scoring (~1 байт на документ на поле); отключаются, если scoring на поле не нужен.
* **Query Profile** — детальная информация о времени выполнения каждого компонента запроса (Profile API).
* **Routing** — маршрутизация документа и запроса на конкретный шард по хешу routing-ключа; исключает scatter-gather по всем шардам.
* **PIT (Point in Time)** — лёгкий снимок состояния индекса для стабильной пагинации через `search_after`.
* **Query phase / Fetch phase** — две фазы поиска: scatter-gather по шардам (doc IDs + scores) и дозапрос полных документов.
* **Adaptive Replica Selection (ARS)** — выбор реплики с лучшим временем ответа (по умолчанию с 7.x).
* **Circuit Breaker** — механизм защиты от OOM: оценка потребления памяти операцией до её выполнения.

## Как работает поиск

1. **Query phase.** Coordinating node рассылает запрос всем шардам индекса (primary или replica — выбор через ARS с учётом allocation awareness). Каждый шард выполняет запрос локально и возвращает doc IDs и scores топ-N документов.
2. **Fetch phase.** Coordinating node объединяет и сортирует результаты, затем дозапрашивает полные документы с нужных шардов.
3. **Видимость данных.** Поиск видит данные после refresh (`index.refresh_interval`, default 1s). Для гарантированной видимости только что проиндексированного документа — `?refresh=wait_for` на запросе индексации.
4. **Терминальная статистика.** Для корректных term/phrase частот across shards существует `search_type=dfs_query_then_fetch` — редко нужен и дорог; в большинстве случаев per-shard статистики достаточно.

## Типичные Bottlenecks

### 1. High Cardinality Aggregations

```json
// Плохо: terms на unique поле
{
  "aggs": {
    "by_request_id": {
      "terms": {
        "field": "request_id",
        "size": 10000
      }
    }
  }
}
```

**Решение:**
- Уменьшить `size` или использовать `composite` aggregation
- Использовать `cardinality` вместо `terms` для count approximation
- Переместить heavy aggregations в Transform/Rollup
- Для часто агрегируемых `keyword`-полей — `eager_global_ordinals` (см. Кэширование)

### 2. Deep Pagination

```json
// Плохо: deep pagination — координирующий узел сортирует from+size документов на каждом шарде
{
  "from": 100000,
  "size": 100
}
```

Лимит: `from + size` не может превышать `index.max_result_window` (default 10000). Увеличение `max_result_window` не рекомендуется — потребление heap и CPU растёт пропорционально `from + size` на каждом шарде.

**Решение — `search_after` + PIT:**

```bash
# 1. Открыть PIT (снимок состояния индекса)
POST /my-index-000001/_pit?keep_alive=1m
# → {"id": "46ToAwMDaWR5MjR1Sj..."}

# 2. Первая страница
GET /_search
{
  "size": 100,
  "pit": { "id": "46ToAwMDaWR5MjR1Sj...", "keep_alive": "1m" },
  "sort": [
    { "@timestamp": "asc" },
    { "event.id": "asc" }
  ]
}

# 3. Следующие страницы: search_after = значения sort последнего документа предыдущей страницы
GET /_search
{
  "size": 100,
  "pit": { "id": "46ToAwMDaWR5MjR1Sj...", "keep_alive": "1m" },
  "sort": [ { "@timestamp": "asc" }, { "event.id": "asc" } ],
  "search_after": [ "2026-10-01T12:00:00.000Z", 4294967298 ],
  "track_total_hits": false
}

# 4. Закрыть PIT
DELETE /_pit
{ "id": "46ToAwMDaWR5MjR1Sj..." }
```

* `search_after` требует явного `sort`; при равных значениях sort Lucene использует внутренние doc IDs, которые различаются на репликах — поэтому в `sort` нужен уникальный tie-breaker.
* PIT сохраняет состояние индекса, поэтому порядок стабилен между страницами даже при refresh; `keep_alive` продлевается при каждом запросе с этим PIT.
* **Scroll API** (`scroll=1m`, `POST /_search/scroll`, `DELETE /_search/scroll`) официально не рекомендуется для deep pagination — используйте `search_after` + PIT. Scroll остаётся рабочим механизмом для массового экспорта (reindex и delete-by-query используют его внутри).
* Для пагинации по агрегациям — `composite` aggregation.

### 3. Wildcard в начале терма

```json
// Плохо: leading wildcard
{
  "query": {
    "wildcard": {
      "message": "*error*"
    }
  }
}
```

**Решение:**
- Использовать `match` с анализатором
- Использовать `ngram` tokenizer для partial matching
- Использовать `wildcard` field type (оптимизирован для wildcard-запросов)

### 4. Script в query

```json
{
  "query": {
    "script": {
      "script": "doc['price'].value * doc['quantity'].value > 100"
    }
  }
}
```

**Решение:**
- Предварительно вычислить значение при индексации
- Использовать `script_score` для ranking
- Использовать `runtime fields` с осторожностью (вычисляются на каждый запрос)

### 5. Nested и parent-child запросы

`nested`-запросы и `has_child`/`has_parent` требуют отдельных проходов по вложенным документам и значительно дороже обычных term/match-запросов. Если вложенная структура используется только для фильтрации — рассмотрите денормализацию (массив объектов вместо `nested`).

## Кэширование

### Query Cache (filter context)

Кэширует результаты запросов, выполненных в **filter context** (bitset совпадений). Не кэшируются: term-запросы вне filter context, запросы в query context, агрегации.

* Один кэш на узел, общий для всех шардов, LRU eviction.
* Кэширование per-segment: сегмент должен содержать ≥10000 документов и ≥3% документов шарда; merge сегментов инвалидирует закэшированные запросы.
* Запрос становится кандидатом на кэширование после нескольких повторных использований (история запросов).
* Содержимое кэша недоступно для инспекции.

```bash
# elasticsearch.yml (static, на каждом data node)
indices.queries.cache.size: 10%      # default 10% heap; допустимо и точное значение, напр. 512mb
```

```bash
# per-index (dynamic), default true
PUT /my-index/_settings
{
  "index.queries.cache.enabled": true
}
```

### Request Cache (size=0)

Кэширует полные ответы на запросы с `size: 0` — aggregations, counts, suggestions. Не кэшируются: запросы с `from/size` пагинацией, date math с `now` (динамический диапазон), запросы к часто обновляемым индексам (кэш инвалидируется при каждом refresh шарда).

```bash
# elasticsearch.yml
indices.requests.cache.size: 1%      # default 1% heap
```

```bash
# per-index (dynamic), default true
PUT /my-index/_settings
{
  "index.requests.cache.enable": true
}
```

Принудительное использование кэша для подходящего запроса: `GET /my-index/_search?request_cache=true`.

### Fielddata Cache

```bash
# elasticsearch.yml
indices.fielddata.cache.size: 30%    # default: неограничен
```

**Важно:** `text` поля не поддерживают aggregations без fielddata, а fielddata на text-полях по умолчанию отключена. Используйте `keyword` для terms aggregation; включение `fielddata: true` на text — крайняя мера (high-cardinality text быстро заполнит heap и триггерит fielddata breaker).

### Global Ordinals и eager_global_ordinals

Global ordinals строятся поверх doc_values `keyword`-полей и используются bucket-агрегациями (`terms`, `composite`, `significant_terms`), сортировкой и операциями с `join`. По умолчанию строятся лениво при первом использовании (оптимизация под скорость индексации). Для полей, по которым часто агрегируют, — строить на refresh, перенося cost на index-time:

```bash
PUT /my-index/_mapping
{
  "properties": {
    "service.name": { "type": "keyword", "eager_global_ordinals": true }
  }
}
```

Осторожно на high-cardinality полях: global ordinals живут в field data cache (heap) и могут триггерить fielddata breaker.

### Cache Statistics

```bash
GET /my-index/_stats/request_cache,query_cache,fielddata?human
GET /_nodes/stats/indices/query_cache,request_cache,fielddata
GET /_cat/fielddata?v                     # память fielddata по полям на узлах
GET /_cat/fielddata/service.name?v
```

Очистка кэшей (может нарушить in-flight поиски, использующие fielddata):

```bash
POST /_cache/clear?fielddata=true
POST /_cache/clear?request=true
POST /_cache/clear?query=true
```

## Query Profiling

### Включение Profile

```json
GET /my-index/_search
{
  "profile": true,
  "query": {
    "bool": {
      "must": [
        { "match": { "message": "error" } }
      ],
      "filter": [
        { "range": { "@timestamp": { "gte": "now-1h" } } }
      ]
    }
  },
  "aggs": {
    "by_service": {
      "terms": { "field": "service.name" }
    }
  }
}
```

### Анализ результатов

Сокращённый пример ответа (иллюстративный):

```json
{
  "profile": {
    "shards": [
      {
        "id": "[node1][my-index][0]",
        "searches": [
          {
            "query": [
              {
                "type": "BooleanQuery",
                "description": "message:error @timestamp:[123456 TO 123457]",
                "time_in_nanos": 12345678,
                "breakdown": {
                  "score": 1234567,
                  "build_scorer": 2345678,
                  "match": 3456789,
                  "next_doc": 2345678,
                  "advance": 1234567
                }
              }
            ],
            "rewrite_time": 12345,
            "collector": []
          }
        ]
      }
    ]
  }
}
```

### Интерпретация

| Метрика | Описание |
|---------|----------|
| `time_in_nanos` | Общее время выполнения |
| `next_doc` | Время итерации по документам (high = много docs) |
| `build_scorer` | Время построения scorer (high = complex query) |
| `match` | Время матчинга (high = много matches) |
| `advance` | Время пропуска документов (high = нужен filter) |

### Validate Query API

Проверить запрос без выполнения (синтаксис, поля, анализаторы):

```bash
GET /my-index/_validate/query?explain=true&rewrite=true
{
  "query": {
    "bool": {
      "filter": [
        { "term": { "level": "ERROR" } }
      ]
    }
  }
}
# → {"_shards": {"total": 1, "successful": 1, "failed": 0}, "valid": true, "explanations": [...]}
```

`?all_shards=true` — валидация на всех шардах (результат rewrite может отличаться per shard). Explain API (`GET /my-index/_explain/<doc_id>`) показывает, почему конкретный документ совпал с запросом.

## Routing

### Принцип работы

```
Без routing:
  Query → Coordinator → [Shard 0, Shard 1, ...] → Merge results

С routing (key=user123):
  Query → Coordinator → [Shard for hash(user123)] → Results
```

### Настройка Routing

```bash
# Индексация с routing
POST /my-index/_doc?routing=user123
{
  "user_id": "user123",
  "message": "..."
}

# Поиск с routing — запрос идёт только на шард, владеющий этим routing-ключом
GET /my-index/_search?routing=user123
{
  "query": {
    "term": { "user_id": "user123" }
  }
}
```

Проверить, на какие шарды попадёт запрос (отладка routing/preference):

```bash
GET /my-index/_search_shards?routing=user123
# → {"shards": [ [ {...shard 0...} ], [ {...shard 1...} ] ]}
```

### Когда использовать Routing

- Multi-tenant приложения (routing по tenant_id)
- User-centric data (routing по user_id)
- Для time-series данных выбор индекса через aliases/date math эффективнее, чем routing по `@timestamp`

### Опасности Routing

- **Hot spots** — если routing key неравномерен
- **Shard imbalance** — некоторые шарды могут быть пустыми
- **Нельзя изменить** — routing key фиксируется при индексации; смена требует reindex
- Поиск **без** routing-параметра всё равно идёт на все шарды

## Index Sorting

### Настройка

```bash
PUT /my-index
{
  "settings": {
    "index.sort.field": ["@timestamp", "service.name"],
    "index.sort.order": ["desc", "asc"]
  }
}
```

Дополнительные параметры: `index.sort.mode` (`min`/`max` для multi-valued полей), `index.sort.missing` (`_last`/`_first`).

### Преимущества

- Ускоряет range queries и сортировку по сортированным полям (возможно раннее завершение)
- Улучшает compression (документы группируются)
- Меньший размер сегментов после merge

### Ограничения

- Нельзя применить к существующему индексу (нужен reindex)
- Поля сортировки должны быть в маппинге с включёнными `doc_values`
- Наибольшую выгоду даёт, когда запросы сортируют по тем же полям (типично для time-series); для произвольных сортировок пользы нет

## Оптимизация запросов

Синтаксис и семантика самих запросов (bool, term/match, контексты query/filter, пагинация) разбираются в [Query DSL](./elasticsearch_query_dsl.md); здесь — приёмы, влияющие на скорость выполнения.

### 1. Используйте Filter Context

```json
// Хорошо: filter не вычисляет score (кэшируется)
{
  "query": {
    "bool": {
      "must": [
        { "match": { "message": "error" } }
      ],
      "filter": [
        { "term": { "level": "ERROR" } },
        { "range": { "@timestamp": { "gte": "now-1h" } } }
      ]
    }
  }
}
```

### 2. Уменьшите `_source`

```json
GET /my-index/_search
{
  "_source": ["@timestamp", "message", "level"],
  "query": { "match_all": {} }
}
```

Или исключите тяжелые поля на уровне маппинга:

```bash
PUT /my-index
{
  "mappings": {
    "_source": {
      "excludes": ["large_binary_field"]
    }
  }
}
```

Не отключайте `_source` полностью без крайней необходимости: он нужен для Get API, Update API, reindex и highlight.

### 3. Используйте `docvalue_fields` / `stored_fields` вместо `_source`

```json
GET /my-index/_search
{
  "_source": false,
  "docvalue_fields": ["@timestamp", "level"]
}
```

`docvalue_fields` работает только для полей с `doc_values`; `stored_fields` — для полей, явно помеченных `store: true` в маппинге (при указании `stored_fields` параметр `_source` по умолчанию становится `false`). Параметр `fields` (8.x+) возвращает значения doc_values/stored fields в унифицированном виде.

### 4. Выбор шард и узлов (`preference`)

```bash
GET /my-index/_search?preference=_local
```

| Значение | Поведение |
|---|---|
| `_local` | Если возможно — шарды на локальном узле, иначе стандартный выбор |
| `_only_local` | Только шарды на локальном узле |
| `_prefer_nodes:<node-id>,...` | Если возможно — указанные узлы |
| `_shards:<shard>,...` | Только указанные шарды (должен идти первым; комбинируется: `_shards:2,3\|_local`) |
| `<custom-string>` | Стабильный выбор шард для одного значения (session affinity; избегает «прыжков» между refresh-состояниями) |

По умолчанию выбор шард идёт через Adaptive Replica Selection с учётом allocation awareness.

### 5. Track total hits

```json
// Точный count (по умолчанию — точно до 10000 совпадений)
{
  "track_total_hits": true
}

// Ограниченный count (быстрее)
{
  "track_total_hits": 10000
}

// Без count (самый быстрый)
{
  "track_total_hits": false
}
```

### 6. Timeout

```bash
GET /my-index/_search?timeout=30s
{
  "query": { "match_all": {} }
}
```

При достижении timeout возвращаются частичные результаты. Нюанс: фаза rewrite (подготовка запроса) не покрывается timeout — очень долгий setup может выйти за timeout до начала итерации по документам.

### 7. `filter_path` — уменьшите ответ

```bash
GET /my-index/_search?filter_path=hits.hits._id,hits.hits._source
```

Поддерживает wildcards (`hits.hits._*`); полезно при больших ответах и медленной сети.

### 8. `min_score` и `constant_score`

```json
GET /my-index/_search
{
  "min_score": 0.5,
  "query": {
    "constant_score": {
      "filter": { "term": { "level": "ERROR" } }
    }
  }
}
```

`constant_score` оборачивает фильтр без вычисления score (boost = 1); `min_score` отсекает слабые совпадения после scoring.

### 9. Оптимизации на уровне маппинга

```bash
PUT /my-index/_mapping
{
  "properties": {
    "level": { "type": "keyword", "norms": false },
    "raw_payload": { "type": "keyword", "doc_values": false, "index": false }
  }
}
```

* `norms: false` — для полей, участвующих только в фильтрации/агрегациях (экономит ~1 байт/док/поле); отключение применяется через update mapping, удаление происходит по мере merge сегментов.
* `doc_values: false` — для полей, не участвующих в sort/aggregations/scripting (экономит диск).
* `index: false` — поле хранится, но не ищется.
* Пакетная отправка нескольких запросов — `_msearch` (один round-trip на несколько поисков).

## Лимиты поиска

| Параметр | Default | Описание |
|---|---|---|
| `index.max_result_window` | 10000 | Максимум `from + size` |
| `search.max_buckets` | 65536 | Максимум bucket-ов в одном ответе (cluster-level, dynamic) |
| `indices.query.bool.max_clause_count` | deprecated (8.0) | Лимит leaf-запросов задаётся динамически: min 1024, растёт с heap и падает с размером search thread pool (напр., ~27000 при 30GB RAM / 48 CPU). Вложенные bool-запросы не обходят лимит — он считает все leaf-запросы |
| `indices.query.bool.max_nested_depth` | 30 | Глубина вложенности запросов |
| `index.max_docvalue_fields_search` | 100 | Максимум полей в `docvalue_fields` |
| `index.max_script_fields` | 32 | Максимум script fields |
| `index.max_terms_count` | 65536 | Максимум значений в terms query |
| `index.max_regex_length` | 1000 | Максимум длины regexp |
| `index.max_inner_result_window` | 100 | `from + size` для inner hits и top hits aggregation |

## Circuit Breaker

### Типы

| Breaker | Настройка | Default | Защищает |
|---|---|---|---|
| `parent` | `indices.breaker.total.limit` | 95% heap (при `use_real_memory: true`, default) / 70% (при `false`) | Суммарный лимит всех breakers |
| `request` | `indices.breaker.request.limit` | 60% heap | Структуры данных запроса (aggregation) |
| `fielddata` | `indices.breaker.fielddata.limit` | 40% heap | Загрузка fielddata |
| `in_flight_requests` | `network.breaker.inflight_requests.limit` | 100% heap | Буферы активных входящих запросов (HTTP/transport) |
| `accounting` | `indices.breaker.accounting.limit` | 100% heap | Память, удерживаемая после завершения запроса (сегменты Lucene) |
| script compilation | `script.max_compilations_rate` | 75/5m | Rate-limit компиляции Painless/Mustache (не процент heap) |

Overhead-множители (оценка × overhead): `indices.breaker.fielddata.overhead: 1.03`, `indices.breaker.request.overhead: 1`, `network.breaker.inflight_requests.overhead: 2`, `indices.breaker.accounting.overhead: 1`.

### Настройка

```bash
# elasticsearch.yml
indices.breaker.total.use_real_memory: true   # default true (static)
indices.breaker.request.limit: 60%
indices.breaker.fielddata.limit: 40%
```

### Ошибки и мониторинг

При срабатывании breaker запрос отклоняется с HTTP 429 и `circuit_breaking_exception`; ошибка также пишется в `elasticsearch.log`:

```json
{
  "error": {
    "type": "circuit_breaking_exception",
    "reason": "[parent] Data too large, data for [<http_request>] would be [123848638/118.1mb], which is larger than the limit of [123273216/117.5mb], real usage: [120182112/114.6mb], new bytes reserved: [3666526/3.4mb]",
    "bytes_wanted": 123848638,
    "bytes_limit": 123273216,
    "durability": "TRANSIENT"
  },
  "status": 429
}
```

```bash
GET /_nodes/stats/breaker
```

Рекомендация Elastic: снижать давление на память, если usage стабильно превышает 85%. Для fielddata-триггеров — `keyword` вместо `text` + fielddata; очистка `POST _cache/clear?fielddata=true`.

## Мониторинг поиска

### Метрики

```bash
GET /my-index/_stats/search?human
GET /_nodes/stats/indices/search
```

Ключевые поля: `open_contexts`, `query_total`, `query_time_in_millis`, `query_current`, `fetch_total`, `fetch_time_in_millis`, `fetch_current`, `scroll_total`, `scroll_time_in_millis`. Отношение `query_time_in_millis / query_total` — грубый индикатор эффективности запросов (рост = запросы дороже).

### Thread pool search

```bash
GET /_cat/thread_pool/search?v
GET /_nodes/stats/thread_pool/search
```

Search thread pool: fixed, size = `int((#processors * 3) / 2) + 1`; queue — 1000 в 8.x, `1000 × size` в 9.0+ (переопределяется `thread_pool.search.queue_size`). Рост `rejected` относительно `completed` — запросы отклоняются (`es_rejected_execution_exception`).

### Длительные запросы

```bash
GET /_tasks?actions=*search&detailed     # запущенные поиски с описанием запроса
GET /_tasks/<task_id>                    # детали задачи
POST /_tasks/<task_id>/_cancel           # отмена
GET /_nodes/hot_threads                  # горячие потоки узла
```

## Slow Log

### Настройка

```bash
PUT /my-index/_settings
{
  "index.search.slowlog.threshold.query.warn": "10s",
  "index.search.slowlog.threshold.query.info": "5s",
  "index.search.slowlog.threshold.query.debug": "2s",
  "index.search.slowlog.threshold.query.trace": "500ms",
  "index.search.slowlog.threshold.fetch.warn": "1s",
  "index.search.slowlog.threshold.fetch.info": "800ms",
  "index.search.slowlog.threshold.fetch.debug": "500ms",
  "index.search.slowlog.threshold.fetch.trace": "200ms"
}
```

Все пороги по умолчанию `-1` (выключено); уровень логирования — `index.search.slowlog.level` (default `INFO`).

### Анализ

Slow log пишется на data-узлах в отдельный файл `elasticsearch_search_slowlog.log` и содержит запрос, время выполнения и разбиение по фазам. В Kibana — Stack Monitoring → Elasticsearch → Search latency; для разового анализа конкретного запроса — Profile API и `GET /_tasks?actions=*search&detailed`.

## Устранение неполадок

| Ошибка / симптом | Причина | Решение |
|---|---|---|
| `Result window is too large, from + size must be less than or equal to: [10000]` | `from + size` > `index.max_result_window` | `search_after` + PIT; не поднимать `max_result_window` |
| `too_many_clauses` | Слишком много leaf-запросов (terms, wildcard, regexp) | Уменьшить число условий; в 8.x+ лимит динамический (min 1024) — `indices.query.bool.max_clause_count` deprecated и не действует |
| HTTP 429 `circuit_breaking_exception` | JVM heap близко к лимиту breaker | `GET /_nodes/stats/breaker`; снизить нагрузку; `keyword` вместо `text`+fielddata; `POST _cache/clear?fielddata=true` |
| `es_rejected_execution_exception` (search) | Очередь search thread pool заполнена | Масштабировать data-узлы; оптимизировать запросы; `GET /_cat/thread_pool/search?v` |
| `fielddata is disabled on text fields by default` | Aggregation/sort по `text` | `keyword`-поле (или multi-field); `fielddata: true` — только как крайняя мера |
| Данные не видны сразу после индексации | `index.refresh_interval` (default 1s) | `?refresh=wait_for` при индексации; для bulk — временно увеличить refresh_interval |
| Разный порядок/состав страниц при пагинации | Нет PIT; doc IDs различаются на репликах | PIT + `search_after` |
| Медленные агрегации по high-cardinality | `terms` с `size: 10000` | `composite` aggregation; `cardinality`; `eager_global_ordinals` |
| Запрос валиден, но возвращает 0 документов | Поле проанализировано иначе, чем ожидалось (`text` vs `keyword`) | `GET /my-index/_validate/query?explain=true`; `GET /my-index/_mapping`; `_analyze` |

## Лучшие практики

### Запросы

1. **Filter context** для всех не-релевантных условий
2. **Избегайте leading wildcards** — используйте ngram analyzer или `wildcard` field type
3. **Ограничьте aggregation size** — используйте composite для deep-пагинации агрегатов
4. **`track_total_hits: false`** если точный count не нужен
5. **`search_after` + PIT** вместо `from/size` для глубоких страниц
6. **`constant_score`** для фильтров без scoring; **`min_score`** для отсечения слабых совпадений
7. **`filter_path`** для уменьшения размера ответа

### Индексы

1. **Index sorting** для time-series data с предсказуемой сортировкой
2. **Correct field types** — keyword для terms, text для full-text
3. **`norms: false`** для полей без scoring; **`doc_values: false`** для полей без sort/agg/script
4. **`eager_global_ordinals`** для часто агрегируемых keyword-полей
5. **Размер шарда** 10–50GB; `force_merge` до 1 сегмента — только на read-only индексах, в которые больше не пишут
6. **Реплики** увеличивают пропускную способность поиска (поиск выполняется на primary или replica)

### Мониторинг

1. **Slow log** — включите для выявления медленных запросов
2. **Profile API** — для анализа конкретных запросов
3. **Cache stats** — мониторьте hit/miss ratio
4. **Circuit breaker** — алертите на trips
5. **`_tasks?actions=*search&detailed`** — длительные запросы; **`_cat/thread_pool/search`** — очередь и rejects

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура и роли узлов.
* **[Query DSL](./elasticsearch_query_dsl.md)** — синтаксис запросов, контексты, пагинация.
* **[Агрегации](./elasticsearch_aggregations.md)** — агрегации и их лимиты (`search.max_buckets` и др.).
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — маппинг и анализаторы.
* **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — index sorting.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов для поиска.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — метрики поиска.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — управление жизненным циклом.
* **[Troubleshooting индексации и сегментов](./elasticsearch_troubleshooting_indexing.md)** — сегменты, merge, force_merge.
* **[Rollup и Transform](./elasticsearch_rollup_transform.md)** — предвычисление агрегатов.
