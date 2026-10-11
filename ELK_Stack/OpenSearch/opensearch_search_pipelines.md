# Search Pipelines (OpenSearch)

**Актуально для:** OpenSearch 3.x. Процессоры с версией введения (2.8–3.3) отмечены в таблицах; поведение, появившееся в 3.3 (system-generated processors), выделено отдельно.

> Руководство по Search Pipelines в OpenSearch. Рассматриваются request, response и search phase results processors, настройка, использование, отладка и метрики.
>
> Связанные темы: OpenSearch overview — [OpenSearch Overview](./opensearch_overview.md); OpenSearch administration — [OpenSearch Administration](./opensearch_administration.md).

## Определения

* **Search Pipeline** — механизм обработки search запросов и ответов на уровне OpenSearch; упорядоченный список процессоров, хранящийся в cluster state.
* **Request Processor** — перехватывает и обрабатывает входящий запрос (query и метаданные) перед отправкой в индекс.
* **Response Processor** — перехватывает и обрабатывает ответ (результаты и метаданные запроса) перед возвратом клиенту.
* **Search Phase Results Processor** — обрабатывает результаты между фазами поиска на coordinating node (например, нормализацию и комбинацию score между query и fetch фазами).
* **System-generated Processor** — процессор, который OpenSearch создаёт автоматически на основе параметров запроса (начиная с 3.3).
* **Temporary Pipeline** — pipeline, определённый inline в теле запроса; не сохраняется и действует только для данного запроса.
* **Pipeline State** — переменные, передаваемые между процессорами (например, `original_size`, устанавливаемая процессором `oversample`).

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

Обработка request и response выполняется только на coordinating node — процессоры не работают на уровне шардов. Search phase results processor запускается между query и fetch фазами: после того как шарды вернули метаданные совпавших документов (ID и score) и до того, как coordinating node запрашивает `_source` документов.

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

Pipeline хранится в cluster state. Один pipeline может содержать несколько процессоров одного типа — для различения используйте `tag`. Обновление — это замена (PUT) pipeline целиком.

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
          "term": { "tenant_id": "tenant-123" }
        }
      }
    }
  ]
}
```

### Версия, отказоустойчивость, удаление

```bash
# Версия pipeline (возвращается в GET _search/pipeline/<name>)
PUT _search/pipeline/my-pipeline
{
  "version": 1,
  "request_processors": [ ... ]
}

# Удаление pipeline (поддерживаются wildcards: DELETE _search/pipeline/*)
DELETE _search/pipeline/my-pipeline
```

По умолчанию (`ignore_failure: false`) pipeline прерывается при отказе любого процессора. При `ignore_failure: true` OpenSearch логирует отказ и выполняет оставшиеся процессоры — проверить фактические отказы можно по метрикам (`failed` в `GET /_nodes/stats/search_pipeline`).

### Использование pipeline

```bash
# Через query-параметр search_pipeline
GET /logs-*/_search?search_pipeline=my-pipeline
{
  "query": {
    "match": { "message": "error" }
  }
}

# Через тело запроса (также поддерживается в _msearch)
GET /logs-*/_search
{
  "query": { "match": { "message": "error" } },
  "search_pipeline": "my-pipeline"
}

# Временный pipeline: определён inline, не сохраняется, действует только для этого запроса
POST /logs-*/_search
{
  "query": { "match": { "message": "error" } },
  "search_pipeline": {
    "request_processors": [
      { "filter_query": { "query": { "term": { "tenant_id": "tenant-123" } } } }
    ]
  }
}

# Pipeline по умолчанию для индекса
PUT /logs-*/_settings
{
  "index.search.default_pipeline": "my-pipeline"
}

# Отключить дефолтный pipeline для конкретного запроса
GET /logs-*/_search?search_pipeline=_none

# Удалить дефолтный pipeline из индекса (null или _none)
PUT /logs-*/_settings
{
  "index.search.default_pipeline": null
}
```

## Типы Processors

Полный список доступных типов процессоров: `GET /_nodes/search_pipelines`. Дополнительные процессоры могут предоставлять плагины. Процессоры модуля `search-pipeline-common` выборочно включаются/отключаются кластерными настройками `search.pipeline.common.request.processors.allowed`, `search.pipeline.common.response.processors.allowed` и `search.pipeline.common.search.phase.results.processors.allowed` (по умолчанию включены все; пустой список отключает все — pipelines с такими процессорами перестанут работать после рестарта ноды).

### Request Processors

| Processor | Назначение | С версии |
|-----------|------------|----------|
| `filter_query` | Добавляет фильтрующий query к запросу | 2.8 |
| `script` | Выполняет inline Painless script над полями запроса | 2.8 |
| `oversample` | Умножает параметр `size` на `sample_factor`, сохраняя исходное значение в переменной `original_size` | 2.12 |
| `neural_query_enricher` | Задаёт модель по умолчанию для neural/neural sparse поиска на уровне индекса или поля | 2.11 (neural), 2.13 (neural sparse) |
| `neural_sparse_two_phase_processor` | Ускоряет neural sparse query | 2.15 |
| `ml_inference` | Вызывает зарегистрированные ML-модели для переписывания запроса | 2.16 |
| `agentic_query_translator` | Переводит `agentic`-запросы в OpenSearch DSL и выполняет агент | 3.2 |

### Response Processors

| Processor | Назначение | С версии |
|-----------|------------|----------|
| `rename_field` | Переименовывает поле в ответе | 2.8 |
| `personalize_search_ranking` | Переранжирует результаты через Amazon Personalize | 2.9 |
| `retrieval_augmented_generation` | RAG для conversational search | 2.10 (GA в 2.12) |
| `collapse` | Дедуплицирует hits по значению поля (аналог `collapse` в запросе, но после fetch со всех шардов) | 2.12 |
| `rerank` | Переранжирует результаты cross-encoder моделью | 2.12 |
| `truncate_hits` | Отбрасывает hits после достижения целевого количества; может отменить эффект `oversample` | 2.12 |
| `sort` | Сортирует массив значений поля по возрастанию/убыванию | 2.16 |
| `ml_inference` | Добавляет в ответ поля, вычисленные ML-моделью | 2.16 |
| `split` | Разбивает строковое поле на массив подстрок по разделителю | 2.17 |
| `hybrid_score_explanation` | Детальная информация о нормализации и комбинации score в hybrid-запросах при включённом `explain` | 2.19 |
| `agentic_context` | Возвращает summary агента, сгенерированный query и memory ID для `agentic`-запроса | 3.3 |

### Search Phase Results Processors

| Processor | Назначение | С версии |
|-----------|------------|----------|
| `normalization-processor` | Перехватывает результаты query phase, нормализует и комбинирует score документов перед передачей в fetch phase | 2.10 |

### System-generated Processors (3.3)

OpenSearch создаёт автоматически на основе параметров запроса. Включается кластерной настройкой `cluster.search.enabled_system_generated_factories` (`*` или список фабрик, например `mmr_over_sample_factory`, `mmr_rerank_factory`, `semantic-highlighter`):

| Processor | Триггер | Стадия |
|-----------|---------|--------|
| `mmr_over_sample` | параметр `mmr` в `ext` | request, после user-defined |
| `knn_default_excludes` | каждый запрос к индексу с `knn_vector` и включённым `_source` | request, до user-defined — добавляет `knn_vector`-поля в `_source.excludes` |
| `mmr_rerank` | параметр `mmr` в `ext` | response, до user-defined |
| `semantic-highlighter` | `highlight` с `type: semantic` и `semantic_highlighting_batch` в `ext` | response, после user-defined |

Ограничение: не более одного system-generated процессора каждого типа на каждую стадию выполнения в одном запросе.

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

`script` — request processor (2.8). Скрипт может модифицировать только поля запроса: `from`, `size`, `explain`, `version`, `seq_no_primary_term`, `track_scores`, `track_total_hits`, `min_score`, `terminate_after`, `profile`. Модификация самого `query` через этот процессор невозможна — для фильтрации используйте `filter_query`.

```bash
# Ограничивает explain одним документом, так как explain — дорогая операция
PUT _search/pipeline/explain-one-result
{
  "description": "A pipeline to limit the explain operation to one result only",
  "request_processors": [
    {
      "script": {
        "lang": "painless",
        "source": "if (ctx._source['size'] > 1) { ctx._source['explain'] = false } else { ctx._source['explain'] = true }"
      }
    }
  ]
}
```

### Collapse Processor

`collapse` — response processor (2.12). Поля: `field` (обязательно), `context_prefix`, `tag`, `description`, `ignore_failure`. Параметры `inner_hits` и `max_concurrent_group_searches` относятся к параметру `collapse` поискового запроса, а не к процессору. Процессор применяется после fetch со всех шардов, поэтому может использоваться вместе с параметром `rescore` запроса или после процессора `rerank`. Результат будет содержать меньше hits, чем `size` — для возврата запрошенного количества используйте связку `oversample` → `collapse`/`rerank` → `truncate_hits`.

```bash
PUT _search/pipeline/collapse-duplicates
{
  "response_processors": [
    {
      "collapse": {
        "field": "user_id"
      }
    }
  ]
}
```

> **Нет процессора `remove`.** Удаление полей из ответа процессорами search pipeline не поддерживается — используйте `_source.excludes` в запросе или `rename_field` для переименования.

### Rename Field Processor

`rename_field` — response processor (2.8). Поля: `field` (обязательно), `target_field` (обязательно), `tag`, `description`, `ignore_failure`. Полезен, когда индекс и приложение используют разные имена одного поля.

```bash
PUT _search/pipeline/rename-fields
{
  "response_processors": [
    {
      "rename_field": {
        "field": "ip_address",
        "target_field": "client_ip",
        "ignore_failure": true
      }
    }
  ]
}
```

### Truncate Hits Processor

`truncate_hits` — response processor (2.12). Поля: `target_size` (максимальное количество hits, >= 0; если не задано, читает `original_size` от `oversample` и падает, если та недоступна), `context_prefix`, `tag`, `description`, `ignore_failure`. Типичный паттерн: `oversample` (request) → `rerank`/`collapse` (response) → `truncate_hits` (response) — вернуть не более запрошенного количества hits.

```bash
PUT _search/pipeline/limit-results
{
  "response_processors": [
    {
      "truncate_hits": {
        "target_size": 100
      }
    }
  ]
}
```

### Oversample Processor

`oversample` — request processor (2.12). Поля: `sample_factor` (обязательно, >= 1.0), `context_prefix`, `tag`, `description`, `ignore_failure`. Умножает `size` запроса, сохраняя исходное значение в переменной `original_size` pipeline state.

```bash
# size=5 → запросит 8 hits (5 * 1.5 = 7.5, округляется вверх)
PUT _search/pipeline/oversampling
{
  "request_processors": [
    {
      "oversample": {
        "sample_factor": 1.5
      }
    }
  ]
}
```

## Гибридный поиск с Search Pipeline

### Normalization Processor

`normalization-processor` — search phase results processor (2.10), а не response processor: он запускается между query и fetch фазами, нормализуя и комбинируя score разных query clause до fetch. Конфигурация — объект `normalization-processor` в массиве `phase_results_processors`.

* **Нормализация** (`normalization.technique`): `min_max` (по умолчанию), `l2`, `z_score`.
* **Комбинация** (`combination.technique`): `arithmetic_mean` (по умолчанию), `geometric_mean`, `harmonic_mean`. `z_score` поддерживает только `arithmetic_mean`.
* **Веса** (`combination.parameters.weights`): массив весов clause из диапазона [0.0, 1.0], сумма должна быть 1.0; по умолчанию все clause весят одинаково.
* `min_max` поддерживает фиксированные пороги `normalization.parameters.lower_bounds`/`upper_bounds` (массивы объектов с `mode`: `apply`/`clip`/`ignore` и `min_score`/`max_score`).
* `ignore_failure` для этого процессора игнорируется: при отказе pipeline всегда падает.

```bash
PUT _search/pipeline/normalize-scores
{
  "description": "Post processor for hybrid search",
  "phase_results_processors": [
    {
      "normalization-processor": {
        "normalization": {
          "technique": "min_max"
        },
        "combination": {
          "technique": "arithmetic_mean",
          "parameters": {
            "weights": [0.3, 0.7]
          }
        }
      }
    }
  ]
}
```

Нормализованные score зависят от количества результатов, возвращённых каждой clause (статистика считается по возвращённым результатам, а не по всему индексу). Рекомендация: для датасетов до 10M документов `size` в диапазоне [100, 200]; дальнейшее увеличение `size` не улучшает релевантность, но растит latency. Выбор техники: `min_max` — предсказуемый диапазон [0.0, 1.0] (score лучшего документа clause = 1.0, ровно `0.0` заменяется на `0.001`); `l2` — сохраняет отношения score внутри clause; `z_score` — только для clause с близким разбросом, при выбросе все документы ниже среднего схлопываются в `0.001`.

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

Значения в сохранённом pipeline статичны — pipeline из cluster state не подставляет значения из запроса. Для фильтрации по tenant создайте pipeline на каждого tenantа или используйте временный pipeline (см. «Использование pipeline»), если значения известны только в момент запроса.

```bash
# Pipeline для tenant-123: только его документы
PUT _search/pipeline/tenant-123-filter
{
  "request_processors": [
    {
      "filter_query": {
        "tag": "tenant-filter",
        "description": "Restrict to tenant-123 documents",
        "query": {
          "term": {
            "tenant_id": "tenant-123"
          }
        }
      }
    }
  ]
}

# Дефолтный pipeline для индекса tenant-123
PUT /tenant-123-logs/_settings
{
  "index.search.default_pipeline": "tenant-123-filter"
}
```

Ограничение периода поиска через `script`-процессор возможно только над полями запроса (`size`, `explain` и т.д.), но не над `query` — для динамической фильтрации по времени приложение должно формировать `range`-фильтр в самом запросе или использовать временный pipeline с `filter_query`.

## Мониторинг и отладка Pipeline

### Получение pipeline

```bash
# Определение одного pipeline (с версией); поддерживаются wildcards: GET _search/pipeline/my*
GET _search/pipeline/my-pipeline
# → { "my-pipeline": { "version": 1, "request_processors": [ ... ] } }

# Все pipeline кластера
GET _search/pipeline
```

### Метрики

Статистика выполнения — через Nodes Stats API (по ноде: `total_request`/`total_response` и детально по каждому pipeline и процессору):

```bash
GET /_nodes/stats/search_pipeline
```

Каждая запись содержит `count`, `time_in_millis`, `current` (выполняется сейчас) и `failed`:

```json
"search_pipeline": {
  "total_request": { "count": 5, "time_in_millis": 158, "current": 0, "failed": 0 },
  "total_response": { "count": 2, "time_in_millis": 1, "current": 0, "failed": 0 },
  "pipelines": {
    "my-pipeline": {
      "request": { "count": 3, "time_in_millis": 71, "current": 0, "failed": 0 },
      "response": { "count": 0, "time_in_millis": 0, "current": 0, "failed": 0 },
      "request_processors": [
        { "filter_query:tenant-filter": { "type": "filter_query", "stats": { "count": 1, "time_in_millis": 0, "current": 0, "failed": 0 } } }
      ],
      "response_processors": []
    }
  }
}
```

Процессоры в метриках ключируются как `type` или `type:tag` — по `failed` видно, какие процессоры отказали (актуально при `ignore_failure: true`).

### Отладка verbose_pipeline

Параметр `verbose_pipeline=true` добавляет в ответ массив `processor_results` с `processor_name`, `tag`, `duration_millis`, `status`, `input_data` и `output_data` каждого процессора — работает для дефолтного, конкретного и временного pipeline:

```bash
GET /my-index/_search?search_pipeline=my-pipeline&verbose_pipeline=true
```

## Best Practices

1. **Используйте `filter_query` для безопасности** — серверная фильтрация по tenant/role, не зависящая от клиента
2. **`ignore_failure: true`** только для необязательных процессоров; контролируйте `failed` в метриках
3. **Тестируйте pipeline** на staging перед production; проверяйте поведение через `verbose_pipeline=true`
4. **Версионируйте pipeline** — параметр `version` и хранение конфигураций в Git
5. **Мониторьте performance** — процессоры выполняются на coordinating node и добавляют latency; `time_in_millis` в метриках показывает вклад каждого процессора
6. **Ограничьте сложность script processors** — они выполняются на каждом запросе
7. **Для collapse/rerank используйте связку `oversample` → `collapse`/`rerank` → `truncate_hits`** — иначе результат будет содержать меньше hits, чем `size`
8. **Подбирайте технику нормализации под данные** — `min_max` (по умолчанию) для предсказуемого диапазона [0.0, 1.0], `l2` когда важны отношения score внутри clause, `z_score` только для clause с близким разбросом (при выбросе все документы ниже среднего схлопываются в `0.001`)

## Troubleshooting

### Pipeline не применяется

1. Проверить имя pipeline в параметре `search_pipeline` (или `index.search.default_pipeline` для дефолтного — не `default_search_pipeline`)
2. Проверить, не отключён ли дефолтный pipeline для запроса параметром `search_pipeline=_none`
3. Проверить доступность типа процессора: `GET /_nodes/search_pipelines` и кластерные настройки `search.pipeline.common.*.processors.allowed`
4. Проверить синтаксис процессоров и права доступа

### Нормализация не применяется в hybrid-поиске

1. `normalization-processor` должен быть в массиве `phase_results_processors`, а не `response_processors`/`request_processors`
2. Ключ процессора — `normalization-processor` (с дефисом), внутри — объекты `normalization` и `combination`
3. `z_score` поддерживает только `arithmetic_mean`

### Collapse возвращает меньше hits, чем size

1. Использовать `oversample` в request-части и `truncate_hits` в response-части
2. Проверить, что `truncate_hits` без `target_size` имеет доступ к `original_size` от `oversample`

### Ошибки в script-процессоре

1. Скрипт может модифицировать только поля запроса (`from`, `size`, `explain`, `version`, `seq_no_primary_term`, `track_scores`, `track_total_hits`, `min_score`, `terminate_after`, `profile`) — модификация `query` не поддерживается
2. Проверить Painless syntax
3. Использовать `ignore_failure: true` для non-critical processors и контролировать `failed` в метриках

### Медленное выполнение

1. Упростить script processors
2. Проверить complexity `filter_query`
3. Сравнить `time_in_millis` процессоров в `GET /_nodes/stats/search_pipeline`
4. Для нормализации — не увеличивать `size` сверх 100–200 для датасетов до 10M документов

## См. также

* **[OpenSearch: Обзор](./opensearch_overview.md)** — архитектура и возможности.
* **[OpenSearch Administration](./opensearch_administration.md)** — администрирование кластера.
* **[ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md)** — управление индексами.
* **[OpenSearch Dashboards](./opensearch_dashboards.md)** — визуализация данных.
*   **[Ingest Pipelines](../Elasticsearch/elasticsearch_ingest_pipelines.md)** — аналог в Elasticsearch.
*   **[Query DSL и поиск (OpenSearch)](./opensearch-query-dsl-search.md)** — запросы и агрегации, которые обрабатывают процессоры.
