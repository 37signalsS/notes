# Search Pipelines (OpenSearch)

> Руководство по Search Pipelines в OpenSearch. Рассматриваются request/response processors, настройка и использование.
>
> Связанные темы: OpenSearch overview — [OpenSearch Overview](../OpenSearch/opensearch_overview.md); OpenSearch administration — [OpenSearch Administration](../OpenSearch/opensearch_administration.md).

## Определения

* **Search Pipeline** — механизм обработки search запросов и ответов на уровне OpenSearch.
* **Request Processor** — обрабатывает входящий запрос перед выполнением поиска.
* **Response Processor** — обрабатывает ответ после выполнения поиска.
* **Phase** — этап обработки (request или response).
* **Conditional Execution** — условное применение процессора.

## Архитектура

### Поток данных

```
Client Request
      │
      ▼
┌─────────────────┐
│ Search Pipeline │
│  (Request Phase)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Search Execution│
│  (Lucene Query) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Search Pipeline │
│ (Response Phase)│
└────────┬────────┘
         │
         ▼
  Client Response
```

### Структура Pipeline

```json
{
  "description": "Search pipeline for logs",
  "request_processors": [
    {
      "filter_query": {
        "query": {
          "term": { "tenant_id": "tenant-123" }
        }
      }
    }
  ],
  "response_processors": [
    {
      "rename_field": {
        "field": "old_name",
        "target_field": "new_name"
      }
    }
  ]
}
```

## Создание Search Pipeline

### Простой pipeline

```bash
PUT _search/pipeline/my-pipeline
{
  "description": "Basic search pipeline",
  "request_processors": [
    {
      "filter_query": {
        "tag": "tenant-filter",
        "description": "Filter by tenant",
        "ignore_failure": false,
        "query": {
          "term": { "tenant_id": "{{tenant_id}}" }
        }
      }
    }
  ]
}
```

### Использование pipeline

```bash
# Через параметр search_pipeline
GET /logs-*/_search?search_pipeline=my-pipeline
{
  "query": {
    "match": { "message": "error" }
  }
}

# Глобальный pipeline для индекса
PUT /logs-*/_settings
{
  "index.search.default_search_pipeline": "my-pipeline"
}
```

## Типы Processors

### Request Processors

| Processor | Назначение |
|-----------|------------|
| `filter_query` | Добавляет filter к запросу |
| `script` | Выполняет Painless script для модификации запроса |
| `oversampler` | Увеличивает выборку для более точной агрегации |

### Response Processors

| Processor | Назначение |
|-----------|------------|
| `rename_field` | Переименовывает поле в ответе |
| `remove` | Удаляет поле из ответа |
| `collapse` | Сворачивает дубликаты |
| `truncate_hits` | Ограничивает количество hits |
| `script` | Выполняет Painless script для модификации ответа |
| `sort_response` | Сортирует hits в ответе |

### Filter Query Processor

```bash
PUT _search/pipeline/filtered-search
{
  "request_processors": [
    {
      "filter_query": {
        "query": {
          "bool": {
            "must": [
              { "term": { "status": "active" } },
              { "range": { "@timestamp": { "gte": "now-7d" } } }
            ]
          }
        },
        "tag": "pre-filter",
        "description": "Apply default filters",
        "ignore_failure": true
      }
    }
  ]
}
```

### Script Processor

```bash
PUT _search/pipeline/script-processing
{
  "request_processors": [
    {
      "script": {
        "lang": "painless",
        "source": """
          if (ctx.query != null && ctx.query.bool != null) {
            ctx.query.bool.filter.add([
              'range': [
                '@timestamp': [
                  'gte': 'now-' + params.lookback
                ]
              ]
            ])
          }
        """,
        "params": {
          "lookback": "7d"
        }
      }
    }
  ]
}
```

### Collapse Processor

```bash
PUT _search/pipeline/collapse-duplicates
{
  "response_processors": [
    {
      "collapse": {
        "field": "user_id",
        "inner_hits": {
          "name": "latest",
          "size": 1,
          "sort": [{ "@timestamp": "desc" }]
        },
        "max_concurrent_group_searches": 4
      }
    }
  ]
}
```

### Remove Processor

```bash
PUT _search/pipeline/remove-sensitive
{
  "response_processors": [
    {
      "remove": {
        "field": ["ssn", "salary", "bank_account"]
      }
    }
  ]
}
```

### Rename Field Processor

```bash
PUT _search/pipeline/rename-fields
{
  "response_processors": [
    {
      "rename_field": {
        "field": "ip_address",
        "target_field": "client_ip",
        "ignore_failure": true,
        "override": false
      }
    }
  ]
}
```

### Truncate Hits Processor

```bash
PUT _search/pipeline/limit-results
{
  "response_processors": [
    {
      "truncate_hits": {
        "fields": ["detailed_logs"],
        "length": 1000
      }
    }
  ]
}
```

## Гибридный поиск с Search Pipeline

### Normalization Processor

```bash
PUT _search/pipeline/normalize-scores
{
  "response_processors": [
    {
      "normalization": {
        "technique": "min_max"
      }
    }
  ]
}
```

### Использование с Hybrid Search

```bash
GET /my-index/_search?search_pipeline=normalize-scores
{
  "query": {
    "hybrid": {
      "queries": [
        {
          "match": { "text": "search query" }
        },
        {
          "knn": {
            "vector_field": {
              "vector": [1.0, 2.0, 3.0],
              "k": 10
            }
          }
        }
      ]
    }
  }
}
```

## Multi-Tenant Pipeline

### Автоматическая фильтрация по tenant

```bash
PUT _search/pipeline/tenant-filter
{
  "request_processors": [
    {
      "filter_query": {
        "query": {
          "term": {
            "tenant_id": "{{tenant_context.tenant_id}}"
          }
        }
      }
    },
    {
      "script": {
        "source": """
          if (ctx.query != null) {
            ctx.query.bool.filter.add([
              'range': [
                '@timestamp': [
                  'gte': 'now-' + params.retention_days + 'd'
                ]
              ]
            ])
          }
        """,
        "params": {
          "retention_days": "30"
        }
      }
    }
  ]
}
```

## Мониторинг Pipeline

### Статистика выполнения

```bash
GET _search/pipeline/my-pipeline
```

### Логирование

```yaml
# opensearch.yml
logger.org.opensearch.searchpipelines: DEBUG
```

## Best Practices

1. **Используйте filter_query для безопасности** — автоматическая фильтрация по tenant/role
2. **ignore_failure: true** для необязательных процессоров
3. **Тестируйте pipeline** на staging перед production
4. **Версионируйте pipeline** — храните конфигурации в Git
5. **Мониторьте performance** — pipeline добавляет latency
6. **Ограничьте сложность script processors** — они выполняются на каждом запросе

## Troubleshooting

### Pipeline не применяется

1. Проверить имя pipeline в параметре `search_pipeline`
2. Проверить права доступа к pipeline
3. Проверить синтаксис процессоров

### Медленное выполнение

1. Упростить script processors
2. Проверить complexity filter_query
3. Использовать `ignore_failure: true` для non-critical processors

### Ошибки в script

1. Проверить Painless syntax
2. Добавить null checks
3. Использовать `params` вместо hardcoded values

## См. также

* **[OpenSearch: Обзор](./opensearch_overview.md)** — архитектура и возможности.
* **[OpenSearch Administration](./opensearch_administration.md)** — администрирование кластера.
* **[ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md)** — управление индексами.
* **[OpenSearch Dashboards](./opensearch_dashboards.md)** — визуализация данных.
* **[Ingest Pipelines](../Elasticsearch/elasticsearch_ingest_pipelines.md)** — аналог в Elasticsearch.
