# Elasticsearch: Query DSL — язык запросов

**Актуально для:** Elasticsearch 9.5.x / 8.19 LTS

> Систематическое руководство по Query DSL: структура запроса, контексты выполнения (query/filter), булева логика, основные типы запросов, сортировка и пагинация. Оптимизация скорости, кэши и лимиты — в [Search Tuning](./elasticsearch_search_tuning.md); маппинг и анализаторы, от которых зависит поведение запросов, — в [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md).
>
> Связанные темы: агрегации — [Aggregations](./elasticsearch_aggregations.md); обновление документов — [Reindex и Update](./elasticsearch_reindex_updates.md); векторный и семантический поиск — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md); [ELK стек: Обзор](../elk_stack_overview.md).

## Определения

* **Query DSL** — JSON-язык запросов Elasticsearch, передаваемый в теле `GET/POST /<index>/_search` (и в `_count`, `_update_by_query`, `_reindex` и др.). Состоит из «leaf»-запросов (выполняют проверку одного условия) и «compound»-запросов (комбинируют другие запросы: `bool`, `boosting`, `dis_max`, `function_score`, `constant_score`).
* **Query context (контекст запроса)** — запрос, заданный в поле `query`. Документ должен удовлетворять условию, и каждому вычисляется релевантный score (оценка совпадения по умолчанию — BM25: `k1=1.2`, `b=0.75`, `discount_overlaps=true`).
* **Filter context (контекст фильтра)** — запрос, заданный в поле `filter` (внутри `bool`, `constant_score`, `function_score`). Условие проверяется бинарно: совпал документ или нет, score не вычисляется, результат кэшируется в [Query Cache](./elasticsearch_search_tuning.md) (bitset совпадений).
* **Score (релевантность)** — число от 0 до 1+ (может превышать 1 при boost), отражающее, насколько хорошо документ соответствует запросу в query context. Чем выше — тем выше позиция в `hits` при сортировке по `_score`.
* **Анализатор (Analyzer)** — конвейер character filters → tokenizer → token filters, превращающий текст в термы. Определяет, что «видит» инвертированный индекс; подробно — в [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md).
* **`term` vs `match`** — ключевое различие DSL: `term` ищет терм в индексе **без анализа** (точное значение), `match` **анализирует** входной текст анализатором поля и строит булев запрос из полученных токенов.

## Основные концепции

### Структура запроса

```json
GET /my-index/_search
{
  "query": { ... },        // что искать (query context)
  "aggs": { ... },         // агрегации
  "sort": [ ... ],         // порядок результатов
  "from": 0, "size": 10,   // пагинация
  "_source": ["field1"],   // какие поля вернуть
  "track_total_hits": 10000,
  "timeout": "5s",
  "min_score": 0.5
}
```

Всё тело опционально: `GET /my-index/_search` с пустым телом вернёт первые 10 документов (`match_all` под капотом). Ответ содержит `hits.total` (`value` + `relation`: `eq` — точный, `gte` — нижняя граница при `track_total_hits` с лимитом), `hits.hits[]` с `_index`, `_id`, `_score`, `_source`.

### Query context и filter context

```json
{
  "query": {
    "bool": {
      "must":   { "match": { "message": "disk full" } },   // query context: участвует в scoring
      "filter": {                                            // filter context: только проверка, кэшируется
        "range": { "@timestamp": { "gte": "now-15m" } }
      }
    }
  }
}
```

* **Правило выбора:** если результату нужен score (сравнение релевантности, top-N по совпадению) — query context; если нужен только факт «подходит/не подходит» (timestamp, уровень лога, точные идентификаторы) — filter context.
* `filter` внутри `bool` и `must_not` выполняются в filter context всегда. `must` и `should` — в query context (если сам `bool` стоит в query context).
* Выигрыш filter context двойной: не считается BM25-скоринг и результат (для логически одинаковых условий) кэшируется в query cache узла.

### Bool query

`bool` — основной compound-запрос. Четыре типа clause:

| Clause | Контекст | Семантика |
|---|---|---|
| `must` | query | Документ обязан совпасть, вклад в score |
| `should` | query | Желательное совпадение, влияет на score; обязательно ли — зависит от `minimum_should_match` |
| `filter` | filter | Обязательное совпадение, без score, кэшируется |
| `must_not` | filter | Обязательное несовпадение, без score, кэшируется |

Семантика `should` задаётся `minimum_should_match`:

* есть `should`, но **нет** ни `must`, ни `filter` → по умолчанию **1** (хотя бы один `should` обязателен);
* есть `should` и есть `must`/`filter` → по умолчанию **0** (`should` только повышает score, не фильтрует);
* в filter context (bool внутри `filter`) → по умолчанию **0**.

Явное указание снимает неоднозначность — для критичных условий всегда пишите `minimum_should_match` явно.

```json
// Обязательно: level=ERROR; желательно (с влиянием на score): все три терма
{
  "query": {
    "bool": {
      "must":     { "term": { "level": "ERROR" } },
      "filter":   { "range": { "@timestamp": { "gte": "now-1h" } } },
      "should": [
        { "match": { "message": "timeout" } },
        { "match": { "message": "connection reset" } }
      ],
      "minimum_should_match": 1
    }
  }
}
```

Лимиты: число leaf-запросов в одном `bool` ограничено динамическим пределом `indices.query.bool.max_clause_count` (min 1024, растёт с heap; подробно — [Search Tuning](./elasticsearch_search_tuning.md)), глубина вложенности — `indices.query.bool.max_nested_depth` (default 30).

### Term vs Match: почему «term по text возвращает 0 hits»

Поле `text` индексируется через анализатор: `"Disk Full"` → токены `disk`, `full`. Запрос `term` сравнивает дословно и ищет терм `"Disk Full"` — такого терма в индексе нет, 0 hits. `match` прогонит запрос через тот же анализатор и найдёт `disk OR full`.

* `term` — для `keyword`-полей, точных значений: идентификаторы, статусы, IP, `@timestamp` c `date`, enum-значения.
* `match` — для `text`-полей (полнотекстовый поиск).
* `match_phrase` — фраза с учётом порядка токенов (все токены подряд).
* Тот же принцип работает и наоборот: `match` по `keyword`-полю сравнивает ввод как есть (анализатора у `keyword` нет), поэтому регистр и пробелы значимы.

## Практические сценарии

### 1. Типовые запросы

```json
// Точное значение (filter context, без score, кэшируется)
{ "query": { "term": { "status": "failed" } } }

// Несколько точных значений (эквивалент OR)
{ "query": { "terms": { "status": ["failed", "timeout"] } } }

// Поле существует и не null
{ "query": { "exists": { "field": "user.id" } } }

// Конкретные _id (без анализа, кэшируется; эквивалент массиву term, но один leaf)
{ "query": { "ids": { "values": ["abc-123", "def-456"] } } }

// Диапазон (даты, числа); date math: now-15m, now/d; format: override date formatter
{ "query": { "range": { "@timestamp": { "gte": "now-15m", "lte": "now" } } } }

// Полнотекстовый поиск: токенизация + OR (operator по умолчанию OR)
{ "query": { "match": { "message": "disk full" } } }

// Все токены обязательны
{ "query": { "match": { "message": { "query": "disk full", "operator": "and" } } } }

// Фраза
{ "query": { "match_phrase": { "message": "disk full" } } }

// Несколько полей
{ "query": { "multi_match": { "query": "disk full", "fields": ["message", "title^2"] } } }

// Объединение: сначала OR по полям, затем требование фильтров
{ "query": { "bool": {
    "must":     [{ "match": { "message": "disk" } }],
    "must_not": [{ "term": { "host.name": "canary" } }],
    "filter":   [{ "terms": { "level": ["ERROR", "FATAL"] } }]
} } }
```

Параметры `match`, полезные в проде: `fuzziness` (допустимое расстояние Левенштейна; `AUTO` подбирает по длине терма), `minimum_should_match` (сколько токенов обязаны совпасть), `analyzer` (переопределить поисковый анализатор), `zero_terms_query` (`none` по умолчанию — если анализатор удалил все токены, вернуть 0 hits; `all` — вернуть все документы).

### 2. Нечёткий поиск и подстановки

```json
// Префикс (терм в начале; ведущий wildcard медленный — см. Troubleshooting)
{ "query": { "prefix": { "host.name": "db-" } } }

// Wildcard: * (любые символы), ? (один символ)
{ "query": { "wildcard": { "service.name": "pay*" } } }

// Регулярное выражение (по keyword; длина ограничена index.max_regex_length)
{ "query": { "regexp": { "service.name": "pay-.*-api" } } }
```

`wildcard`/`regexp`/`prefix` выполняются по индексу термов и не участвуют в relevance-скоринге (score 1 при совпадении). Лимит длины — `index.max_regex_length` (default 1000).

### 3. Сортировка и `_source`

```json
{
  "query": { "match": { "message": "disk" } },
  "sort": [
    { "@timestamp": { "order": "desc" } },
    { "_score":     { "order": "desc" } }
  ],
  "_source": ["@timestamp", "message", "host.name"],
  "script_fields": { ... }
}
```

* Сортировка возможна по полям с doc_values (`keyword`, числа, `date`), не по `text` (нужен `keyword`-subfield).
* `"sort": ["@timestamp"]` — сокращённая форма; при сортировке не по `_score` последний документ страницы между репликами может «плавать» — добавляйте уникальный tie-breaker (`_id` или уникальное поле).
* `_source: false` / `_source: { "includes": [...] }` — уменьшить ответ; `docvalue_fields` / `stored_fields` — получить значения без разбора `_source` (подробнее — [Search Tuning, «Оптимизация запросов»](./elasticsearch_search_tuning.md)).

### 4. Пагинация

```json
// Глубокая (до index.max_result_window = 10000 суммарно from+size)
{ "from": 20, "size": 10 }

// Без глубокой пагинации: непрерывная выборка (для экспорта/обхода всех документов)
{ "search_after": [ <sort-значения последнего документа предыдущей страницы> ],
  "sort": [{ "@timestamp": "asc" }, { "_id": "asc" }] }
```

* `from + size` ограничен `index.max_result_window` (default 10000); превышение → ошибка `Result window is too large`. Увеличивать `max_result_window` не рекомендуется (стоимость растёт на каждом шарде).
* Для стабильной глубокой пагинации — `search_after` + [Point in Time](./elasticsearch_search_tuning.md) (PIT фиксирует состояние индекса, порядок не «плывёт» при refresh).
* Scroll API используется внутри `reindex`/`delete_by_query` и для массового экспорта; для пользовательской пагинации официально не рекомендуется.
* `track_total_hits` (default 10000) — считать точно до 10000 совпадений; `true` — точно всегда, `false` — не считать (быстрее ответ). Подробнее — [Search Tuning](./elasticsearch_search_tuning.md).

### 5. Вложенные и дочерние документы

```json
// Поиск по nested-структуре — только через nested-запрос с path
{ "query": { "nested": {
    "path": "authors",
    "query": { "bool": { "must": [
      { "match": { "authors.name": "Kimchy" } },
      { "term": { "authors.age": 30 } }
    ] } },
    "score_mode": "avg"
} } }
```

Обычный `match` по nested-полю не увидит данных (каждый объект индексируется как отдельный скрытый документ) — см. [Mapping and Indexing, «object vs nested»](./elasticsearch_mapping_and_indexing.md). Аналогично `has_child`/`has_parent` для join-типа; оба запроса заметно дороже обычных (проход по вложенным документам).

### 6. Проверка запроса без выполнения

```bash
GET /my-index/_validate/query?explain
{ "query": { "bool": { "must": [{ "match": { "message": "disk" } }] } } }
# → {"valid": true, "explanations": [...]}
```

`_validate/query` ловит синтаксические ошибки до прогона; `_search?profile=true` — подробный профиль фаз выполнения ([Search Tuning, «Query Profiling»](./elasticsearch_search_tuning.md)).

### 7. Релевантность: boost, constant_score и function_score

Оценка `_score` по умолчанию считается по **BM25** (см. Определения: `k1=1.2`, `b=0.75`). Интуиция модели, объясняющая «почему нужный документ не первый»:

*   **Частота терма насыщается** (`k1`): 10-е вхождение слова не в 10 раз весомее 1-го — повторы перестают помогать после разумного предела.
*   **Длинные поля штрафуются** (`b`): одинаково упомянутое в коротком заголовке и в простыне текста слово весомее в заголовке.
*   **Редкие слова весомее** (IDF): терм, встречающийся в 5 документах из 100 000, различает сильнее, чем слово в половине документов.

Собственно рычаги настройки на этапе запроса:

**`boost` — вес отдельного условия** (линейно умножает вклад):

```json
GET my-index/_search
{
  "query": {
    "bool": {
      "must":   [{ "match": { "title": { "query": "database", "boost": 3 } } }],
      "filter": [{ "term":  { "status": "published" } }],
      "should": [{ "match": { "body": "elastic" } }]
    }
  }
}
```

Условие в `filter` вообще не участвует в scoring (и кэшируется) — жёсткие критерии всегда туда, а `should`/`must` оставляют для смыслового совпадения.

**`constant_score` — фиксированный скор поверх фильтра** (когда важно только «присутствие условия», но оно должно чуть поднять документ):

```json
GET my-index/_search
{
  "query": {
    "constant_score": {
      "filter":  { "range": { "published_at": { "gte": "now-30d/d" } } },
      "boost": 1.2
    }
  }
}
```

**`function_score` — ранжирование по данным документа** (свежесть, популярность, бизнес-вес), когда одного текстового совпадения мало:

```json
GET my-index/_search
{
  "query": {
    "function_score": {
      "query": { "match": { "title": "search" } },
      "functions": [
        { "filter": { "range": { "published_at": { "gte": "now-7d/d" } } }, "weight": 1.5 },
        { "field_value_factor": { "field": "votes", "factor": 0.5, "modifier": "log1p", "missing": 0 } }
      ],
      "boost_mode": "sum",
      "score_mode": "sum"
    }
  }
}
```

Как это читается:

*   **`functions`** — список функций; у каждой может быть `filter` (применяется только к совпавшим документам) и `weight`.
*   **`field_value_factor`** — монотонно трансформирует числовое поле документа: `factor` (множитель), `modifier` (`none`/`log1p`/`ln`/`sqrt`/`square`/`reciprocal` — `log1p` сглаживает выбросы), `missing` (значение, если поля нет).
*   **`score_mode`** (`multiply` по умолчанию) — как объединять функции **между собой**: `sum`, `avg`, `max`, `min`, `first`.
*   **`boost_mode`** (`multiply` по умолчанию) — как объединить результат функций с исходным BM25-скором запроса: `sum`, `replace`, `avg`, `max`, `min`. В примере `sum` — текстовый скор и «популярность» складываются, а не перемножаются.
*   **`max_boost`** — потолок множителя функций; **`min_score`** — отсечка итогового скора (документы ниже порога не возвращаются).

Случайная, но стабильная сортировка (для лент, где важна разнообразность, а не релевантность):

```json
{ "query": { "function_score": {
    "query": { "match_all": {} },
    "random_score": { "seed": 42, "field": "_seq_no" } } } }
# → тот же seed + те же данные дают тот же порядок
```

**`dis_max` — поиск по нескольким полям с выбором лучшего score:**

```json
{ "query": { "dis_max": {
    "queries": [
      { "match": { "title":   "disk full" } },
      { "match": { "message": "disk full" } }
    ],
    "tie_breaker": 0.3
} } }
```

В отличие от `bool`/`should` (который суммирует score), `dis_max` берёт **максимальный** score из совпавших запросов и прибавляет `tie_breaker` (0–1) × score от остальных. Используется, когда одно и то же слово может встречаться в нескольких текстовых полях — `should` завышает score за счёт суммирования, `dis_max` избегает этого.

**`boosting` — понижение релевантности без исключения:**

```json
{
  "query": {
    "boosting": {
      "positive":  { "match": { "message": "database" } },
      "negative":  { "term": { "service.name": "monitoring" } },
      "negative_boost": 0.3
    }
  }
}
```

Документы, где `message` содержит `database`, но также `service.name: monitoring`, получают score × `negative_boost` (0.3). Удобно «понижать шум», не выбрасывая его полностью (в отличие от `must_not`).

Ограничение: `function_score` управляется только BM25-скором запроса — **полный текстовый скор он не отключает**; для условий без влияния на порядок используйте `filter`/`constant_score`. Сортировка результатов (`"sort": ["_score"]`) — по умолчанию; поле, участвующее в `field_value_factor`, должно быть числовым с doc_values ([Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)). Влияние анализаторов и индекс-временных факторов на выдачу — в [Search Tuning](./elasticsearch_search_tuning.md); альтернатива скорингу для аналитики — [ES|QL](./esql-query-language.md) (без relevance-сортировки).

### 8. Поиск по логам: `query_string` и `simple_query_string`

`query_string` и `simple_query_string` разбирают текстовый запрос по синтаксису Lucene (операторы `AND`/`OR`/`NOT`, группировка через `()`, фразы через `"`, wildcard `*`/`?` в термах) и превращают его в DSL-запрос. Это основа поиска в Kibana Query Bar, условий алертов и Watcher.

```json
// query_string: мощный Lucene-синтаксис, но падает на синтаксических ошибках
{ "query": { "query_string": {
    "query": "level:ERROR AND (service:payment OR service:billing) AND NOT host:canary",
    "default_field": "message"
} } }

// simple_query_string: тот же синтаксис, но не падает — невалидные части становятся терм-запросами
{ "query": { "simple_query_string": {
    "query": "connection refused -timeout",
    "fields": ["message", "service.name"],
    "default_operator": "and",
    "lenient": true
} } }
```

Параметры:
* `query` (обязательно) — строка запроса в синтаксисе Lucene.
* `default_field` / `fields` — поля для поиска (по умолчанию `*` = `index.query.default_field` настройка индекса).
* `default_operator` — `OR` (по умолчанию) или `AND`: при `OR` запрос `timeout connection` найдёт документы с любым из термов; при `AND` — с обоими.
* `lenient` — если `true`, форматные ошибки (например, текст в числовом поле) игнорируются вместо падения.
* `analyze_wildcard` — если `true`, wildcard-термы (`*xxx*`) анализируются через анализатор (доступно для `query_string` и `simple_query_string`, по умолчанию `false`).

> **Продакшн-правило:** для пользовательских поисковых строк (Kibana, UI) используйте `simple_query_string` — он не ломается на ошибках ввода. Для программных условий алертов, где запрос всегда валиден, допустим `query_string`.

## Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| `term` по полю возвращает 0 hits, а значение точно | Поле `text` — значение прошло анализатор | `match` вместо `term`, либо `term` по `keyword`-subfield |
| `Result window is too large` | `from + size > index.max_result_window` (10000) | `search_after` + PIT вместо глубокого `from` |
| Медленный запрос с `wildcard`/`regexp` | Сканирование термов, ведущий `*` не использует префиксный индекс | Сократить паттерн, `prefix` вместо `*xxx`, ngram-анализатор, or-стратегии |
| `too_many_clauses ... max_clause_count` | Превышен лимит leaf-запросов bool | Сократить clauses, `terms` вместо массива `should`/`must`; лимит — [Search Tuning](./elasticsearch_search_tuning.md) |
| Нет ожидаемых документов по `@timestamp` | Некорректный формат даты или timezone | `range` с ISO-8601 или date math (`now-1h`), проверить маппинг поля |
| Счётчик `hits.total` «неправильный» | `track_total_hits` = 10000 → `relation: gte` | `"track_total_hits": true` для точного count |
| Данные «плывут» между страницами `from/size` | Refresh меняет распределение по сегментам | `search_after` + PIT |
| Запрос падает `illegal_argument_exception` по nested-полю | Запрос по nested-объекту без `nested`-запроса | Обернуть в `nested` с указанием `path` |
| `query_string` падает на синтаксической ошибке | `query_string` требует строгого Lucene-синтаксиса | `simple_query_string` вместо `query_string`, или `lenient: true` |
| `terms` слишком много значений | `index.max_terms_count` (default 65536) ограничивает число термов | Сократить список, использовать `terms_set` с `minimum_should_match` |

## Best Practices

* **Фильтры — в `filter`/`must_not`:** точные условия (id, статус, диапазоны времени) не должны участвовать в scoring — это ускоряет запрос и включает query cache.
* **`terms` вместо массива `must`/`should`** для списка точных значений — один leaf-запрос вместо N.
* **Не поднимайте `max_result_window`** — для глубокой пагинации `search_after` + PIT.
* **Ограничивайте `_source`** и `size` в ответах mass-выборок; для счётчиков — `"size": 0`.
* **`track_total_hits: false`** там, где точный счётчик не нужен (автокомплит, бесконечная лента).
* **Пишите `minimum_should_match` явно** в bool-запросах, где `should` обязателен по смыслу.
* **Валидируйте** тяжёлые запросы через `_validate/query` и `profile` перед выкладкой.
* **Используйте `constant_score` или filter context** для условий без влияния на порядок — score-вычисление лишнее.
* **Для пользовательских поисковых строк — `simple_query_string`, а не `query_string`** — последний падает на ошибках ввода (Kibana, UI).
* **`dis_max` вместо `bool`/`should`** для поиска по нескольким текстовым полям — `should` завышает score за счёт суммирования, `dis_max` берёт максимум + `tie_breaker`.
* **`ids` для точного lookup по `_id`** — один leaf-запрос вместо массива `term`.

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура, роли узлов.
* **[Search Tuning](./elasticsearch_search_tuning.md)** — тюнинг запросов, кэши, профилирование, лимиты поиска, пагинация (PIT + search_after).
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — маппинг, типы полей, анализаторы, nested/runtime-поля, векторный поиск.
* **[Aggregations](./elasticsearch_aggregations.md)** — агрегации поверх запросов.
* **[Reindex и Update](./elasticsearch_reindex_updates.md)** — массовое обновление документов по запросу.
* **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — обработка документов при индексации.
* **[Grok и Dissect Patterns](../grok_dissect_patterns.md)** — парсинг строк в логах.

### Перекрытие с существующими файлами (§0.10)

* `Elasticsearch/elasticsearch_search_tuning.md` — SSoT по тюнингу (кэш, circuit breaker, профилирование, лимиты, глубокая пагинация PIT+search_after); здесь эти темы только упоминаются со ссылкой.
* `Elasticsearch/elasticsearch_mapping_and_indexing.md` — SSoT по маппингу, типам полей и анализаторам; здесь анализаторы объясняются ровно настолько, насколько нужно для выбора `term`/`match`.
* `OpenSearch/opensearch-query-dsl-search.md` — аналогичный обзор DSL для OpenSearch (параллельная продуктовая линия); пересечение по базовой семантике DSL неизбежно и принято в базе.
