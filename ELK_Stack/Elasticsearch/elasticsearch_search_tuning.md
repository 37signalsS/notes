# Search Performance Tuning

> Руководство по оптимизации производительности поиска в Elasticsearch. Рассматриваются кэширование, query profiling, routing и оптимизация запросов.
>
> Связанные темы: тюнинг индексации — [Troubleshooting](./elasticsearch_troubleshooting_indexing.md); мониторинг — [Stack Monitoring](./elasticsearch_stack_monitoring.md).

## Определения

* **Query Cache** — кэш результатов aggregation и global ordinals (автоматический).
* **Request Cache** — кэш результатов search запросов (size=0, только aggregations).
* **Fielddata** — в-memory структура для text полей (используется в aggregations/sort).
* **Query Profile** — детальная информация о времени выполнения каждого компонента запроса.
* **Routing** — маршрутизация запроса на конкретный шард для избежания scatter-gather.
* **Shard Request Cache** — кэш на уровне шарда (для size=0 queries).
* **Circuit Breaker** — механизм защиты от OOM при больших запросах.

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

### 2. Deep Pagination

```json
// Плохо: deep pagination
{
  "from": 100000,
  "size": 100
}
```

**Решение:**
- Использовать `search_after` для deep pagination
- Использовать `scroll` для export (но не для real-time)
- Увеличить `max_result_window` (не рекомендуется)

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
- Использовать `wildcard` field type

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
- Использовать `runtime fields` с осторожностью

## Кэширование

### Request Cache

```json
// Включить request cache (по умолчанию включен)
PUT /my-index/_settings
{
  "index.requests.cache.enable": true
}
```

Работает для:
- `size: 0` queries
- Aggregations
- Не работает для `from/size` pagination

### Shard Request Cache

```bash
# Размер кэша (по умолчанию 1% heap)
indices.requests.cache.size: 2%
```

### Query Cache (автоматический)

Кэширует:
- Aggregation results
- Global ordinals
- Фильтры (filter context)

```bash
# Размер query cache (по умолчанию 10% heap)
indices.queries.cache.size: 15%
```

### Fielddata Cache

```bash
# Лимит fielddata (по умолчанию неограничен)
indices.fielddata.cache.size: 30%
```

**Важно:** `text` поля не поддерживают aggregations без fielddata. Используйте `keyword` для terms aggregation.

### Cache Statistics

```bash
GET /my-index/_stats/request_cache
GET /my-index/_stats/query_cache
GET /my-index/_stats/fielddata
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
        { "match": { "message": "error" } },
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
            "collector": [...]
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

# Поиск с routing
GET /my-index/_search?routing=user123
{
  "query": {
    "term": { "user_id": "user123" }
  }
}
```

### Когда использовать Routing

- Time-based indices с фильтром по @timestamp
- Multi-tenant приложения (routing по tenant_id)
- User-centric data (routing по user_id)

### Опасности Routing

- **Hot spots** — если routing key неравномерен
- **Shard imbalance** — некоторые шарды могут быть пустыми
- **Нельзя изменить** — routing key фиксируется при индексации

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

### Преимущества

- Ускоряет range queries по сортированным полям
- Улучшает compression (документы группируются)
- Уменьшает segment size после merge

### Ограничения

- Нельзя применить к существующему индексу (нужен reindex)
- Работает только для time-series data
- Первичный sort field должен быть в маппинге

## Search Optimizations

### 1. Используйте Filter Context

```json
// Хорошо: filter не вычисляет score (кэшируется)
{
  "query": {
    "bool": {
      "must": [
        { "match": { "message": "error" } }  // query context
      ],
      "filter": [
        { "term": { "level": "ERROR" } },    // filter context
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
  "query": { ... }
}
```

Или исключите тяжелые поля:

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

### 3. Используйте `docvalue_fields` вместо `_source`

```json
GET /my-index/_search
{
  "_source": false,
  "docvalue_fields": ["@timestamp", "level"]
}
```

### 4. Pre-filter shards

```json
GET /my-index/_search?preference=_local_shards
```

### 5. Track total hits

```json
// Точный count (по умолчанию до 10000)
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

```json
GET /my-index/_search?timeout=30s
{
  "query": { ... }
}
```

## Circuit Breaker

### Типы

| Breaker | Защищает | Default |
|---------|----------|---------|
| `request` | Aggregations | 60% heap |
| `fielddata` | Fielddata | 40% heap |
| `in_flight_requests` | Network buffers | 100% heap |
| `parent` | All | 95% heap |
| `script` | Script compilation | 75% (15m) |

### Настройка

```bash
# elasticsearch.yml
indices.breaker.request.limit: 60%
indices.breaker.fielddata.limit: 40%
indices.breaker.total.use_real_memory: true
```

### Мониторинг

```bash
GET /_nodes/stats/breaker
```

## Best Practices

### Запросы

1. **Filter context** для всех не-релевантных условий
2. **Избегайте leading wildcards** — используйте ngram analyzer
3. **Ограничьте aggregation size** — используйте composite для deep
4. **track_total_hits: false** если точный count не нужен
5. **Используйте routing** для user-specific queries

### Индексы

1. **Index sorting** для time-series data
2. **Correct field types** — keyword для terms, text для full-text
3. **Disable _source/_fielddata** если не нужны
4. **Размер шарда** 10-50GB для оптимальной производительности

### Мониторинг

1. **Slow log** — включите для выявления медленных запросов
2. **Profile API** — для анализа конкретных запросов
3. **Cache stats** — мониторьте hit/miss ratio
4. **Circuit breaker** — алертите на trips

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

### Анализ

```bash
GET /_search?q=*&sort=@timestamp:desc&size=10
```

Slow log записывает запросы, превышающие пороги, в отдельный лог-файл.

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура и роли узлов.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — маппинг и анализаторы.
* **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — index sorting.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов для поиска.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — метрики поиска.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — управление жизненным циклом.
