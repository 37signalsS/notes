# Query DSL и поиск (OpenSearch)

**Актуально для:** OpenSearch 3.9.x (текущая ветка, релиз 29 сентября 2026) / 2.19.x (ветка поддержки, патчи). API поиска совместим с Elasticsearch 7.10 — особенности OpenSearch отмечены отдельно. Ветка 2.x — линия поддержки (maintenance), 3.x — активной разработки; описанные below особенности обеих веток учтены.

> Основы Query DSL в OpenSearch: структура запроса, типы query и filter, агрегации, глубокая пагинация (search_after, Point in Time), профилирование. Файл покрывает сам DSL; настройка скорости и релевантности — в [Elasticsearch Search Tuning](../Elasticsearch/elasticsearch_search_tuning.md).

## Определения

* **Query DSL** — JSON-DSL для описания поисковых запросов в OpenSearch; тело `GET|POST /<index>/_search`.
* **Query vs Filter context** — в query-контексте каждый документ получает score (`relevance_score`), в filter-контексте score не считается, результат булевый, кэшируется на уровне блоков (bitset).
* **Aggregation** — вычисление сводной статистики по совпавшим документам (счётчики, средние, гистограммы, top terms).
* **Point in Time (PIT)** — снапшот набора сегментов индекса для консистентной пагинации (с 2.4).
* **search_after** — постраничная выборка «после значения», не ограниченная глубиной; работает совместно с PIT или `sort` по tiebreaker-полю.

## Основы запроса

### Структура запроса

```bash
GET /logs-*/_search
{
  "query": { ... },
  "aggs": { ... },
  "from": 0,
  "size": 10,
  "sort": [ ... ],
  "_source": ["@timestamp", "message", "level"],
  "highlight": { "fields": { "message": {} } }
}
```

* `query` — фильтрация + score; `aggs` — агрегации по результатам query.
* `from` + `size` — глубокая пагинация ограничена `index.max_result_window` (по умолчанию `10000`: `from + size <= 10000`).
* `_source` — подмножество полей в ответе (не влияет на то, что индексируется).
* `track_total_hits` — по умолчанию `10000`: точный счётчик останавливается на 10 000; `true` — считать точно.

### bool — основа комбинирования

```bash
GET /logs-*/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "message": "connection refused" } }
      ],
      "filter": [
        { "term": { "level": "error" } },
        { "range": { "@timestamp": { "gte": "now-24h" } } }
      ],
      "must_not": [
        { "term": { "host": "canary-01" } }
      ],
      "should": [
        { "term": { "service": "payment" } },
        { "term": { "service": "billing" } }
      ],
      "minimum_should_match": 1
    }
  }
}
```

| Клауза | Контекст | Score | Назначение |
|---|---|---|---|
| `must` | query | да, + score | документы, которые обязаны совпасть |
| `filter` | filter | нет, кэшируется | постоянные ограничения (уровень, период, tenant) |
| `must_not` | filter | нет | исключения |
| `should` | query | да | желательные совпадения; без других клауз — обязательно хотя бы одно (`minimum_should_match: 1` по умолчанию в этом случае) |

Правило производительности: **всё, что не участвует в ранжировании, переносить в `filter`** — не считается score, результат кэшируется.

### Типы query

| Тип | Контекст | Поведение |
|---|---|---|
| `term` / `terms` | filter | точное значение из inverted index; для keyword-полей и констант. `term` — одно значение, `terms` — список (до 65 536) |
| `match` | query | анализирует входную строку через анализатор поля, строит bool-запрос |
| `match_phrase` | query | фраза: все токены подряд, с позициями |
| `match_bool_prefix` | query | последний токен — префикс (для автодополнения на keyword/text) |
| `multi_match` | query | `match` по нескольким полям (`fields: ["title^3", "body"]`) |
| `range` | filter | диапазон по числу/дате: `gte`, `gt`, `lte`, `lt`, `format`, `boost` |
| `bool` | оба | комбинирование клауз |
| `exists` | filter | поле присутствует: `{ "field": "user.email" }` |
| `prefix` / `wildcard` | filter | префикс/шаблон с `*`/`?`; дорогие на больших значениях |
| `regexp` | filter | регулярное выражение по терму |
| `ids` | filter | конкретные `_id` |
| `query_string` / `simple_query_string` | query | синтаксис в строке (AND/OR/NOT, поля); `simple_query_string` не падает на невалидном синтаксисе |
| `nested` | оба | запрос по объектам в nested-полях |
| `term_set` | filter | набор термов (Set-структуры; относительно новый тип) |
| `knn` / `hybrid` | query | векторный и гибридный поиск — см. [Search Pipelines](./opensearch_search_pipelines.md) |

### Compound-запросы

Кроме `bool`, Query DSL включает compound-запросы для управления релевантностью. Оценка по умолчанию — BM25 (`k1=1.2`, `b=0.75`).

| Тип | Назначение |
|---|---|
| `constant_score` | фиксированный score (по умолчанию `1.0`) поверх filter-запроса; удобно, когда важно присутствие условия, но не релевантность |
| `function_score` | ранжирование по данным документа: `field_value_factor`, `random_score`, `decay`, `script_score`; `score_mode` (how functions combine), `boost_mode` (how result combines with BM25) |
| `dis_max` | максимум score из совпавших подзапросов + `tie_breaker` (0–1) × score остальных; избегает завышения score при поиске по нескольким полям |
| `boosting` | понижение релевантности без исключения: `positive` + `negative` + `negative_boost` (0–1) |
| `score_divisor` / `script_score` | кастомные функции scoring (см. [Search Pipelines](./opensearch_search_pipelines.md) для server-side processing) |

```bash
# constant_score: фиксированный score поверх фильтра
GET /logs-*/_search
{
  "query": {
    "constant_score": {
      "filter": { "range": { "@timestamp": { "gte": "now-7d/d" } } },
      "boost": 1.5
    }
  }
}

# function_score: текстовый search + свежесть
GET /logs-*/_search
{
  "query": {
    "function_score": {
      "query": { "match": { "message": "timeout" } },
      "functions": [
        { "filter": { "range": { "@timestamp": { "gte": "now-1h" } } }, "weight": 2 },
        { "field_value_factor": { "field": "duration_ms", "factor": 0.001, "modifier": "log1p", "missing": 0 } }
      ],
      "score_mode": "sum",
      "boost_mode": "sum"
    }
  }
}

# dis_max: лучший score из нескольких полей
GET /logs-*/_search
{
  "query": {
    "dis_max": {
      "queries": [
        { "match": { "title": "error" } },
        { "match": { "message": "error" } }
      ],
      "tie_breaker": 0.3
    }
  }
}

# boosting: понижение шума
GET /logs-*/_search
{
  "query": {
    "boosting": {
      "positive": { "match": { "message": "database" } },
      "negative": { "term": { "service": "monitoring" } },
      "negative_boost": 0.3
    }
  }
}
```

Ограничения: `function_score` управляется BM25-скором запроса — полный текстовый скор он не отключает; для условий без влияния на порядок используйте `filter`/`constant_score`. Сортировка результатов (`"sort": ["_score"]`) — по умолчанию. Поле, участвующее в `field_value_factor`, должно быть числовым с doc_values (см. [Mapping и индексирование](./opensearch-mapping-and-indexing.md)).

### Проверка запроса без выполнения

```bash
GET /logs-*/_validate/query?explain
{ "query": { "bool": { "must": [{ "match": { "message": "disk" } }] } } }
# → {"valid": true, "explanations": [...]}
```

`_validate/query` ловит синтаксические ошибки до прогона; `_search?profile=true` — подробный профиль фаз выполнения (см. раздел Профилирование).

Распространённая ошибка: `term` по `text`-полю не находит документы, потому что поле проанализировано (сломано на токены). Либо задавать keyword-поле, либо использовать `match`.

### Сортировка и `_source`

```bash
GET /logs-*/_search
{
  "sort": [
    { "@timestamp": { "order": "desc" } },
    { "_shard_doc": "desc" }
  ],
  "_source": false
}
```

* Сортировка по `text`-полю запрещена (только по `keyword`/`numeric`/`date`); если `text`-поле имеет sub-field `.keyword` — сортировать по нему.
* `_shard_doc` — tiebreaker внутри PIT; без PIT используйте уникальное поле (например `_id`) как последний ключ сортировки.

## Агрегации

```bash
GET /logs-*/_search
{
  "size": 0,
  "query": { "bool": { "filter": [ { "range": { "@timestamp": { "gte": "now-24h" } } } ] } },
  "aggs": {
    "by_level": {
      "terms": { "field": "level", "size": 10 }
    },
    "avg_duration": { "avg": { "field": "duration_ms" } },
    "errors_over_time": {
      "date_histogram": {
        "field": "@timestamp",
        "fixed_interval": "1h",
        "min_doc_count": 0
      },
      "aggs": {
        "error_share": {
          "bucket_selector": {
            "buckets_path": { "total": "_count" },
            "script": "params.total > 0"
          }
        }
      }
    },
    "top_services": {
      "terms": { "field": "service", "size": 5 },
      "aggs": { "p95": { "percentiles": { "field": "duration_ms", "percents": [95] } } }
    }
  }
}
```

| Агрегация | Назначение |
|---|---|
| `terms` | топ-N значений по частоте (по умолчанию `size: 10`; accurate count ограничен `search.max_buckets`) |
| `avg` / `sum` / `min` / `max` / `stats` / `extended_stats` | метрики по числовому полю |
| `percentiles` / `percentile_ranks` | перцентили (tdigest) |
| `cardinality` | приблизительное число уникальных значений (HyperLogLog++, точность ~5% при default precision_threshold) |
| `date_histogram` | интервалы по времени (`fixed_interval: 1h`, `calendar_interval: 1d`) |
| `histogram` | интервалы по числу |
| `range` | готовые диапазоны |
| `filter` / `filters` | агрегация по подмножеству (фильтр-контекст, кэшируется) |
| `nested` | агрегация по nested-документам |
| `missing` | документы без значения поля |
| `composite` | композитные бuckets для сквозной агрегации по many-terms (пагинация через `after_key`) |

Правила:

* `size: 0` в запросе — не возвращать документы, только `aggregations` (стандарт для аналитики).
* `terms` даёт точные результаты только при `search.max_buckets` и достаточном `size`; для точного подсчёта всех значений — `composite` с пагинацией.
* Дочерние агрегации (`aggs` внутри агрегации) считаются по каждому bucket родителя — следите за `search.max_buckets` (по умолчанию 65 536), иначе запрос завершится ошибкой.

## Глубокая пагинация

### Ограничение from/size

`from + size` ограничен `index.max_result_window` (по умолчанию `10000`). Ошибка:

```
Result window is too large, from + size must be less than or equal to: [10000]
```

Поднимать `max_result_window` — затратно по памяти (coordinating node держит `from + size` hits в куче). Правильные альтернативы — `search_after` и PIT.

### search_after (без PIT)

```bash
# Первый запрос
GET /logs-*/_search
{
  "size": 100,
  "query": { "range": { "@timestamp": { "gte": "now-24h" } } },
  "sort": [
    { "@timestamp": { "order": "desc" } },
    { "_id": { "order": "desc" } }
  ]
}

# Следующие страницы: подставить sort-значения предыдущей страницы
GET /logs-*/_search
{
  "size": 100,
  "query": { "range": { "@timestamp": { "gte": "now-24h" } } },
  "sort": [
    { "@timestamp": { "order": "desc" } },
    { "_id": { "order": "desc" } }
  ],
  "search_after": ["2026-10-07T10:00:00.000Z", "abc123"]
}
```

Особенности: `search_after` — только вперёд, случайное прыжковое `from` невозможно; значения берутся из `sort` предыдущего ответа; между страницами возможна «дрейфовка» данных (документы переезжают по сегментам) — для консистентности используйте PIT.

### Point in Time + search_after

```bash
# 1. Открыть PIT (keep_alive — токен жизни, сервер продлевает при чтении)
POST /logs-*/_search/point_in_time?keep_alive=5m
# → { "pit_id": "Oi4xOTgyN..." }

# 2. Поиск с PIT: _index не указывается, sort — обязательно
POST /_search
{
  "size": 100,
  "pit": {
    "id": "Oi4xOTgyN...",
    "keep_alive": "5m"
  },
  "sort": [ { "@timestamp": { "order": "desc" } }, { "_shard_doc": "desc" } ]
}

# 3. Следующая страница
POST /_search
{
  "size": 100,
  "pit": { "id": "Oi4xOTgyN...", "keep_alive": "5m" },
  "sort": [ { "@timestamp": { "order": "desc" } }, { "_shard_doc": "desc" } ],
  "search_after": [ "2026-10-07T10:00:00.000Z", 42 ]
}

# 4. Закрыть PIT досрочно (иначе освободится по истечении keep_alive)
DELETE /_search/point_in_time
{ "pit_id": ["Oi4xOTgyN..."] }
```

Что даёт PIT: набор сегментов зафиксирован на момент открытия — все страницы видят одни и те же документы, новые индексации не попадают в выборку. `_shard_doc` — быстрый tiebreaker, добавляемый PIT; сортировка с ним не требует уникального бизнес-поля.

### Scroll

`_scroll` (снапшот сегментов + батчи) считается legacy-подходом: держит snapshot открытым, не подходит для UI-пагинации. Предпочтителен PIT + `search_after`. Scroll остаётся полезным для массовой выгрузки внутри одного скрипта.

## Профилирование

```bash
GET /logs-*/_search
{
  "profile": true,
  "query": { "bool": { "filter": [ { "range": { "@timestamp": { "gte": "now-1h" } } } ] } }
}
```

Ответ содержит `profile.shards[]` с разбором по каждой фазе:

* `rewrite_time` — время переписывания запроса;
* `collector` — сборщики (например `SimpleQueryCollector`, `MultiCollector`): `next_collector`, `collect_time`, `reduce_time` — где реально тратится время;
* `itor`-блоки — работа итераторов.

Типичный вывод: доминирует `collect_time` — индексация/фильтр-фаза дорогая; либо `reduce_time` — много совпадений и агрегация тяжёлая. `profile: true` добавляет накладные расходы — включать на диагностику, не в прод-запросы.

## Troubleshooting

### Result window is too large

1. Перейти на `search_after` + PIT вместо `from`/`size`.
2. Крайний случай — поднять `index.max_result_window` (`PUT /<index>/_settings`), понимая цену памяти.
3. Для аналитики — уменьшить `size`, агрегировать на сервере (`aggs`) вместо выборки документов.

### term по text-полю возвращает 0 hits

1. Проверить mapping: `GET /<index>/_mapping/field/<field>` — если `type: text`, `term` ищет терм после анализатора.
2. Использовать sub-field `.keyword` либо `match`.
3. Для фильтрации по точному значению в шаблоне задавать `keyword`-тип (см. [Mapping](./opensearch-mapping-and-indexing.md)).

### Агрегация падает max_buckets

1. Уменьшить `size` в `terms`, добавить фильтр/период.
2. Использовать `composite`-агрегацию с пагинацией по `after_key`.
3. Поднять `search.max_buckets` (кластерная настройка), если лимит действительно нужен.

### Неточные счётчики total

1. По умолчанию `track_total_hits: 10000` — до 10k точный счёт, дальше `relation: "gte"`.
2. Для точного значения — `"track_total_hits": true` (дороже).

### Данные «плывут» между страницами пагинации

1. Использовать PIT: без него сегменты оптимизируются (merge) между запросами, документы могут пропасть/задвоиться в выборке.
2. Закрывать PIT (`DELETE /_search/point_in_time`), не копить открытые.

## Best Practices

1. Постоянные ограничения — в `filter` (кэш, без score), релевантность — в `must`/`should`.
2. Для UI-пагинации — PIT + `search_after`, не `from`/`size` глубже первой сотни.
3. Аналитические запросы — `size: 0` + `aggs`; документы не вытягивать, если они не нужны.
4. `terms`-агрегации ограничивать `size` и фильтрами; точный перебор — `composite`.
5. `_source: false` для запросов, где нужен только score/агрегация — экономит сеть и десериализацию.
6. `profile: true` — только для диагностики конкретного запроса.
7. Сортировка — по `keyword`/`date`/числу + tiebreaker (`_id`, а в PIT — `_shard_doc`).
8. Глубокие `match`-запросы по многим полям — контролировать `bool`-сложность (`max_bool_clauses`, по умолчанию 1024).

## Граничные случаи

| Ситуация | Поведение / ограничение |
|---|---|
| `terms` с `size` в тысячи бакетов | упирается в `search.max_buckets` (65 536 по умолчанию) — ошибка `Too many buckets`. Решение: уменьшить `size`, сузить `query`, перейти на `composite` |
| `match` по `keyword`-полю | анализатора у `keyword` нет — ввод сравнивается как есть, регистр и пробелы значимы. `term` по `text`-полю возвращает 0 hits (анализатор сломал значение на токены) |
| `wildcard`/`regexp` с ведущим `*` | сканируют все термы, не используют префиксный индекс — медленно на больших индексах; предпочтительнее `prefix` или ngram-анализатор |
| `query_string` на невалидном синтаксисе | падает. Для пользовательских строк — `simple_query_string` (не падает, `lenient: true`) |
| `bool` с `should` без `must`/`filter` | `minimum_should_match` по умолчанию 1 — хотя бы один `should` обязателен. При наличии `must`/`filter` — по умолчанию 0 |
| `bool` с числом leaf-запросов выше `indices.query.bool.max_clause_count` | ошибка `too_many_clauses`. Сократить через `terms` вместо массива `should`/`must` |
| `range` по `text`-полю | не поддерживается — только по `keyword`/`numeric`/`date` |
| `nested`-запрос без `path` | ошибка — каждый nested-объект индексируется как отдельный скрытый документ; обычный `match` по nested-полю не увидит данных |
| `search_after` без `sort` | ошибка — `sort` обязателен; без PIT нужен уникальный tiebreaker (`_id`) |
| `function_score` с `field_value_factor` | поле должно быть числовым с doc_values; `missing` задаёт значение при отсутствии поля |
| `composite`-агрегация | генерирует ровно `size` корзин на запрос; под-агрегации добавляют собственные и считаются в `search.max_buckets` |
| `track_total_hits: false` | точный счётчик не вычисляется — быстрее, но `hits.total` отсутствует или `relation: gte` |
| `from + size` > `index.max_result_window` | ошибка `Result window is too large` (по умолчанию 10000). Не поднимать лимит — `search_after` + PIT |

## Дополнительная информация

* [Elasticsearch Search Tuning](../Elasticsearch/elasticsearch_search_tuning.md) — тюнинг скорости, кэши, circuit breaker.
* [Query DSL (Elasticsearch)](../Elasticsearch/elasticsearch_query_dsl.md) — основы DSL на стороне Elasticsearch: контексты запроса, bool, term/match, пагинация.
* [Агрегации (Elasticsearch)](../Elasticsearch/elasticsearch_aggregations.md) — bucket/metric/pipeline-агрегации, лимиты `search.max_buckets` и др.
* [OpenSearch: Обзор](./opensearch_overview.md) — архитектура, общий контекст.
* [Search Pipelines](./opensearch_search_pipelines.md) — обработка запросов/ответов, hybrid-поиск.
* [Mapping и индексация (OpenSearch)](./opensearch-mapping-and-indexing.md) — типы полей, от которых зависит выбор `term`/`match`.
* [ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md) — ретеншн и rollup, влияющие на индексы в wildcard-шаблонах.

### Перекрытие с существующими файлами (§0.10)

* `Elasticsearch/elasticsearch_search_tuning.md` — SSoT по тюнингу (кэш, thread pool, replica-шарды); настоящий файл покрывает сам DSL и пагинацию, тюнинг не дублирует.
* `OpenSearch/opensearch_search_pipelines.md` — SSoT по processорам и hybrid/normalization; здесь `hybrid`/`knn` только упоминаются со ссылкой.
* **Ранее** (до появления файлов ниже) фундамента Query DSL в базе не было ни в одном файле — этот файл закрывал пробел и оставался SSoT для основ DSL. Сейчас фундамент на стороне Elasticsearch закрыт отдельными файлами (список выше); настоящий файл остаётся SSoT для **OpenSearch-варианта** DSL (различия в API/лимитах продуктов сохраняются, продуктовая параллель ES/OpenSearch принята в базе).
