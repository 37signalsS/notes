# Elasticsearch: Aggregations — агрегативная аналитика

**Актуально для:** Elasticsearch 9.5.x / 8.19 LTS

> Систематическое руководство по агрегациям Elasticsearch: bucket- и metric-агрегации, pipeline-агрегации, вложенность, лимиты и производительность. Выбор запроса, с которого начинается агрегация, — в [Query DSL](./elasticsearch_query_dsl.md); тяжёлые агрегации, кэши и circuit breaker — в [Search Tuning](./elasticsearch_search_tuning.md); предвычисление истории — в [Rollup и Transform](./elasticsearch_rollup_transform.md).
>
> Связанные темы: маппинг полей, по которым агрегируют (`keyword`, doc_values) — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md); ES|QL как альтернатива для аналитики — [ES|QL](./esql-query-language.md).

## Определения

* **Aggregation (агрегация)** — вычисление сводной статистики по выборке документов. Задаётся в теле `_search` в блоке `aggs`/`aggregations` (или отдельно через `_search` с `"size": 0`, `_count` агрегациям не нужен). Результат возвращается в объекте `aggregations` ответа.
* **Bucket aggregation (bucket-агр.)** — группирует документы по критерию (значение поля, диапазон, интервал даты) и возвращает набор «корзин» (`buckets`), каждая со `doc_count`. Каждая корзина — срез, по которому можно считать метрики или вкладывать следующую агрегацию.
* **Metric aggregation (метрика)** — вычисляет одно значение (или набор значений) по набору документов: `min`, `max`, `avg`, `sum`, `stats`, `extended_stats`, `value_count`, `cardinality`, `percentiles`, `percentile_ranks`, `top_hits`.
* **Pipeline aggregation** — агрегация над результатами другой агрегации (не над документами): parent pipeline (`derivative`, `cumulative_sum`, `bucket_script`, `moving_fn`) считается поверх корзин соседней/родительской агрегации, sibling pipeline (`avg_bucket`, `max_bucket`, `percentile_bucket`) считает сводку по одноимённым метрикам соседних корзин. Выполняется в reduce-фазе на координаторе после всех остальных. `moving_avg` удалён из Elasticsearch в 8.0 (deprecated с 6.4) — его функциональность даёт `moving_fn`.
* **Multi-bucket vs multi-value** — multi-bucket агрегация (`terms`, `histogram`, `date_histogram`, `range`, `filters`, `composite`, `significant_terms`) возвращает список корзин; multi-value (`stats`, `extended_stats`) возвращает несколько значений одной агрегации одним объектом.
* **Sub-aggregation (вложенная агрегация)** — агрегация внутри корзины другой агрегации. Глубина вложенности ограничена настройкой `search.aggs.max_nested_depth` (default 50, максимум 1000); каждый уровень также умножает объём данных, обрабатываемых в reduce-фазе и через request circuit breaker.
* **`doc_count_error_upper_bound`** — верхняя граница ошибки подсчёта документов в корзине `terms` из-за распределённого выполнения. Ошибка рассчитывается только при сортировке по убыванию `doc_count` (по умолчанию); пер-букетная ошибка включается параметром `show_term_doc_count_error`. Ноль — ни на одном шарде не нашлось корзин, не поместившихся в `shard_size`, — отбор топа точен.

## Основные концепции

### Как выполняются агрегации

Запрос с агрегацией выполняется в три фазы:

1. **Query-фаза (scatter):** на каждом шарде формируется набор документов по `query` (для агрегаций обычно `match_all`, поэтому `size: 0` — не возвращать hits вообще).
2. **Агрегирование на шарде:** каждая корзина считается локально по документам шарда. Bucket-агрегации возвращают по `shard_size` кандидатов (у `terms` — см. ниже), метрики — точные значения по шарду.
3. **Reduce-фаза (gather):** координатор сливает частичные результаты со всех шардов: корзины `terms` сортируются по суммарному `doc_count`, ошибки складываются, pipeline-агрегации считаются поверх уже слитых данных.

Следствие: **любая агрегация распределена, а значит — потенциально приблизительна** (bucket-агрегации с `size`) или ограничена памятью (metric-агрегации по высококардинальным полям). Точность и стоимость — всегда компромисс.

### Лимиты и защита

| Лимит | Default | Что защищает |
|---|---|---|
| `search.max_buckets` | 65536 | Максимум корзин в одном ответе агрегаций (cluster-level, dynamic) |
| `index.max_inner_result_window` | 100 | `from + size` для `top_hits` и inner hits |
| `search.aggs.max_nested_depth` | 50 (макс. 1000) | Глубина вложенности агрегаций в одном запросе |
| request circuit breaker | 60% heap | Память на структуры запроса (включая агрегации) — при превышении HTTP 429 `circuit_breaking_exception` |
| fielddata circuit breaker | 40% heap | Fielddata на `text`-полях (включается только вручную) |

`search.max_buckets` — самый частый лимит на практике: `terms` с `size: 100000` × несколько полей упирается в 65536 и падает `Too many buckets`. Решение — сократить `size`, сузить `query`, перейти на `composite` (постраничный обход корзин) или предвычисление ([Transform/Rollup](./elasticsearch_rollup_transform.md)).

### Terms-агрегация: размер, точность, сортировка

```json
GET /logs-*/_search
{
  "size": 0,
  "aggs": {
    "by_host": {
      "terms": {
        "field": "host.name",
        "size": 20,
        "order": { "_count": "desc" }
      },
      "aggs": {
        "avg_duration": { "avg": { "field": "event.duration" } }
      }
    }
  }
}
```

* **`size` (default 10)** — сколько корзин вернуть. Это не «топ-10 за всю историю», а топ-10 кандидатов, собранная по частичным данным шардов.
* **`shard_size` (default `size * 1.5 + 10`)** — сколько кандидатов каждый шард отправляет координатору. Увеличивать `shard_size` дешевле, чем `size`: это повышает точность отбора топа, но не раздувает ответ. Если задан меньше `size` — Elasticsearch принудительно поднимает до `size`.
* **Точность:** даже при большом `shard_size` `doc_count` может быть приблизительным — терм, редкий на каждом шарде, но суммарно частый, может не попасть в кандидаты. `doc_count_error_upper_bound` и `sum_other_doc_count` (> 0 — часть документов отброшена) сообщают о масштабе ошибки. Для точности — поднять `shard_size`, сузить индексы или перейти на `composite`.
* **Сортировка по умолчанию** — по убыванию `doc_count`; сортировка по метрике (`order: { "avg_duration": "desc" }`) требует вложенной метрики и считается в reduce-фазе.
* **`text`-поля не агрегируются** без включённого fielddata (по умолчанию отключён из-за памяти) — используйте `keyword`-subfield. Подробнее — [Search Tuning](./elasticsearch_search_tuning.md).

### Date histogram: интервалы времени

```json
{
  "aggs": {
    "per_hour": {
      "date_histogram": {
        "field": "@timestamp",
        "fixed_interval": "1h",        // фиксированные интервалы: 1s/1m/1h/1d...
        "min_doc_count": 0             // показывать пустые интервалы (для графиков)
      }
    }
  }
}
```

* `calendar_interval` — календарные интервалы (`1M`, `1y`, `1d` с учётом перехода на летнее время), `fixed_interval` — фиксированные по длительности (`30m`, `2h`). Указывать ровно один из двух.
* `format` — формат ключа корзины (`"epoch_millis"`, `"yyyy-MM-dd"`), `time_zone` — сдвиг, `offset` — сдвиг границы интервала.
* `extended_bounds`/`min_doc_count: 0` — заполнить пустые интервалы на графике вместо пропусков.

## Предварительные требования

* **Маппинг:** агрегируемое поле должно иметь doc_values — `keyword`, числовой тип или `date` (включены по умолчанию). Для строковых полей логов агрегируют по `*.keyword`-сабфилду; `text` без fielddata не агрегируется ([Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)).
* **Time field:** для `date_histogram` поле `@timestamp` должно быть `date` в шаблоне индекса; если тип другой — переформатировать можно runtime field без переиндексации ([Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)).
* **Права доступа:** на чтение индекса (привилегия `read`) для `_search` с агрегацией; cluster-привилегия `monitor` — для диагностики (`GET _nodes/stats/breaker`, `_cat/fielddata`).
* **Интерфейс:** примеры ниже рассчитаны на Kibana Dev Tools; через curl — `curl -H 'Content-Type: application/json' ... -d '<body>'`.

## Практические сценарии

### 1. Сводка по полю: топ, метрики и вложенность

```bash
GET /orders/_search
{
  "size": 0,
  "query": { "range": { "created_at": { "gte": "now-7d" } } },
  "aggs": {
    "by_status": {
      "terms": { "field": "status", "size": 10 },
      "aggs": {
        "avg_amount":  { "avg":   { "field": "amount" } },
        "max_amount":  { "max":   { "field": "amount" } },
        "total_amount": { "sum":  { "field": "amount" } },
        "big_orders":  { "filter": { "range": { "amount": { "gte": 1000 } } },
                         "aggs": { "count": { "value_count": { "field": "amount" } } } }
      }
    },
    "amount_stats": { "stats": { "field": "amount" } },
    "p95_latency":  { "percentiles": { "field": "latency", "percents": [50, 95, 99] } }
  }
}
# → aggregations.by_status.buckets[0] = { "key": "paid", "doc_count": 1200,
#     "avg_amount": {...}, "big_orders": { "doc_count": 50, ... } },
#   aggregations.amount_stats = { "min":..., "max":..., "avg":..., "sum":..., "count":... }
```

`stats` возвращает пять значений (`min`, `max`, `avg`, `sum`, `count`) одним объектом; `extended_stats` добавляет `std_deviation` и др. `percentiles` использует TDigest — приблизителен на хвостах (точность падает после ~99-го перцентиля).

### 2. Фильтрация внутри агрегации: filter / filters

```json
{
  "aggs": {
    "errors_last_hour": {
      "filter": { "term": { "level": "ERROR" } },
      "aggs": { "per_host": { "terms": { "field": "host.name", "size": 10 } } }
    },
    "by_level": {
      "filters": {
        "filters": {
          "errors":   { "term": { "level": "ERROR" } },
          "warnings": { "term": { "level": "WARN" } }
        }
      }
    }
  }
}
```

`filter` (одно условие) и `filters` (именованный набор, либо `others` для всего остального) считаются в filter context — дёшево и кэшируемо. Это предпочтительный способ «метрика по срезу», если срез один и тот же во многих запросах.

### 3. Диапазоны и гистограммы

```json
{
  "aggs": {
    "latency_buckets": {
      "range": {
        "field": "latency",
        "ranges": [
          { "to": 100 },                       // 0–100
          { "from": 100, "to": 500 },          // 100–500
          { "from": 500 }                      // 500+
        ]
      }
    },
    "response_histogram": {
      "histogram": { "field": "size_bytes", "interval": 1024, "min_doc_count": 0 }
    }
  }
}
```

`histogram` — числовые интервалы (аналог `date_histogram` для чисел); `interval` задаёт ширину корзины. `range` — произвольные именованные диапазоны, удобно для SLA-слоёв (0–100 мс / 100–500 мс / 500+ мс).

### 4. Уникальные значения: cardinality

```json
{
  "aggs": {
    "unique_users": {
      "cardinality": { "field": "user.id", "precision_threshold": 10000 }
    }
  }
}
```

* Алгоритм HyperLogLog++ — **приблизительный** подсчёт уникальных.
* `precision_threshold` (**default 3000**, максимум 40000, выше — эффект как от 40000): ниже порога значения ожидаемо точные, выше — возможны отклонения в несколько процентов. Память растёт пропорционально порогу.
* Для точного уникального счётчика на малых данных — `terms` + `value_count` (с ограничением `size`) или `composite`.
* Комбинация двух полей — через runtime field (`emit(doc['a'].value + ' ' + doc['b'].value)`) и агрегацию по нему.

### 5. Обход большого числа корзин: composite

```json
// Первый запрос
POST /logs-*/_search
{
  "size": 0,
  "aggs": {
    "all_hosts": {
      "composite": {
        "size": 1000,
        "sources": [
          { "host":  { "terms":  { "field": "host.name", "order": "asc" } } },
          { "level": { "terms":  { "field": "level", "order": "asc" } } }
        ]
      }
    }
  }
}

// Следующие: подставить after_key из предыдущего ответа
{ "aggs": { "all_hosts": { "composite": { "size": 1000, "sources": [...],
  "after": { "host": "web-01", "level": "ERROR" } } } } }
```

`composite` — постраничный обход корзин с гарантированным порядком (`after_key` в ответе) вместо одномоментного `terms` с огромным `size`. На один запрос composite создаёт ровно `size` корзин своего уровня (под-агрегации добавляют собственные и учитываются в `search.max_buckets`). Идеален для выгрузки «все значения поля» (в связке с `scheduled task`/витриной) и для `date_histogram` с произвольным порядком.

### 6. Топ-N документов каждой корзины: top_hits

```json
{
  "aggs": {
    "by_service": {
      "terms": { "field": "service.name", "size": 10 },
      "aggs": {
        "worst": {
          "top_hits": {
            "size": 3,
            "sort": [{ "event.duration": { "order": "desc" } }],
            "_source": ["@timestamp", "service.name", "event.duration"]
          }
        }
      }
    }
  }
}
```

`top_hits` возвращает не значения, а сами документы (по аналогии с `hits`). Ограничен `index.max_inner_result_window` (`from + size` ≤ 100) — это выборка, не пагинация.

### 7. Pipeline-агрегации: динамика по времени

```json
{
  "aggs": {
    "per_day": { "date_histogram": { "field": "@timestamp", "calendar_interval": "1d" },
                 "aggs": {
                   "requests": { "sum": { "field": "requests" } },
                   "growth":   { "derivative": { "buckets_path": "requests", "gap_policy": "skip" } },
                   "total":    { "cumulative_sum": { "buckets_path": "requests" } },
                   "smooth":   { "moving_fn": { "buckets_path": "requests", "window": 7,
                                                "script": "MovingFunctions.unweightedAvg(values)" } }
                 } }
  }
}
```

Pipeline считает метрики **над корзинами**: `derivative` — прирост к предыдущей корзине, `cumulative_sum` — накопительный итог, `bucket_script` — произвольная формула между корзинами, `moving_fn` — скользящее окно по серии (в `script` доступна переменная `values`; предустановленные функции `MovingFunctions.*`: `unweightedAvg`, `linearWeightedAvg`, `ewma`, `holt`, `holtWinters`, `min`/`max`/`sum`/`stdDev`). Sibling-агрегации (`avg_bucket`, `max_bucket`, `percentile_bucket`) сворачивают одноимённые метрики соседних корзин — например, среднее по дням поверх `requests`. `gap_policy`: `skip` — пропустить пустую корзину, `insert_zeros` — считать её нулём. `moving_fn`, как и `derivative` с `cumulative_sum`, вкладывается внутрь `histogram`/`date_histogram`; pipeline-агрегации не выполняются на шардах — считаются в reduce-фазе, поэтому их стоимость растёт с числом корзин.

### 8. SLI и полнота данных: percentile_ranks и missing

```bash
GET /logs-*/_search
{
  "size": 0,
  "query": { "range": { "@timestamp": { "gte": "now-1h" } } },
  "aggs": {
    "sla": {
      "percentile_ranks": { "field": "event.duration", "values": [100000000, 500000000] }
    },
    "no_service": { "missing": { "field": "service.name" } }
  }
}
# → aggregations.sla.values = { "100000000.0": 0.91, "500000000.0": 0.98 },
#   aggregations.no_service = { "doc_count": 42 }
```

* `percentile_ranks` — доля документов со значением **не выше** указанного: прямой способ посчитать SLI «доля запросов в пределах SLA». Здесь `event.duration` в наносекундах (ECS): 100000000 — 100 мс, 500000000 — 500 мс; в ответе — доля запросов, уложившихся в каждый порог. Использует тот же TDigest, что и `percentiles`, — точность на хвостах приблизительная.
* `missing` — bucket-агрегация, возвращающая `doc_count` документов **без значения** поля. Проверка покрытия полей: сколько логов пришло без `service.name`, `host.name` и т.д. — типичная проблема ингеста, которую графики по корзинам не показывают.

### 9. Новые сигнатуры ошибок: significant_terms

```bash
GET /logs-*/_search
{
  "size": 0,
  "query": {
    "bool": { "filter": [
      { "range": { "@timestamp": { "gte": "now-15m" } } },
      { "term": { "log.level": "ERROR" } }
    ] }
  },
  "aggs": {
    "new_signatures": {
      "significant_terms": {
        "field": "error.type",
        "min_doc_count": 5,
        "background_filter": { "range": { "@timestamp": { "gte": "now-7d" } } }
      }
    }
  }
}
# → aggregations.new_signatures.buckets[] =
#     { "key": "TimeoutError", "doc_count": 132, "bg_count": 4120, "score": 0.41 }
```

* **Foreground** — документы под `query` (ошибки за 15 минут), **background** — набор для сравнения статистики: по умолчанию весь индекс, `background_filter` сужает его (здесь — 7 дней). Возвращаются термы, необычно частые в foreground относительно background: именно так ищут новые сигнатуры ошибок, всплывшие в последнем релизе.
* `min_doc_count` (**default 3**) — не опускать до 1: единичные вхождения дают опечатки и случайные значения. Высокая кардинальность поля делает агрегацию дорогой — сузить `background_filter`, поднять `min_doc_count` или ограничить выборку через `sampler`.
* Документованная практика — два прохода: сначала получить короткий список значимых термов, затем вторым запросом с `terms`-фильтром по ним собрать детали (`top_hits`, `date_histogram`).

## Валидация

* **`_shards.failed == 0`** в ответе — иначе агрегации посчитаны по неполному набору шардов (частичный результат возвращается по умолчанию, см. Troubleshooting).
* **`doc_count_error_upper_bound == 0` и `sum_other_doc_count == 0`** — критерий точности для отчётов; ненулевые значения означают, что топ-N отобран приблизительно (поднять `shard_size` или перейти на `composite`).
* **Взаимная сверка агрегатов:** `sum` по корзинам `terms` и `stats.sum` той же агрегации при одинаковом `query` должны совпадать; расхождение — признак разных условий отбора или отброшенных корзин.
* **Стабильность:** повторный запуск того же запроса по неизменённым данным даёт тот же топ; «прыгающий» топ — распределённая оценка `terms` (см. Troubleshooting).
* **Стоимость и память:** `GET /logs-*/_stats/request_cache` (попадание в shard request cache при `size: 0`) и `GET _nodes/stats/breaker` — usage request breaker не у самого лимита.

## Troubleshooting

| Ошибка / симптом | Причина | Решение |
|---|---|---|
| `Too many buckets` (`search.max_buckets`) | Суммарное число корзин > 65536 | Уменьшить `size`, сузить `query`, `composite`, предвычисление ([Transform](./elasticsearch_rollup_transform.md)) |
| `fielddata is disabled on text fields by default` | Агрегация по `text`-полю | `keyword`-sub-field (или multi-field); включение fielddata — крайняя мера |
| `circuit_breaking_exception` (HTTP 429) | Структуры агрегации не влезли в request breaker (60% heap) | Сократить корзины/глубину, добавить data-узлы, поднять лимит осознанно ([Search Tuning](./elasticsearch_search_tuning.md)) |
| `doc_count` в `terms` меньше ожидаемого | Распределённая оценка: терм не попал в `shard_size`-кандидаты | Поднять `shard_size`, сузить индексы, `composite` для полноты |
| `sum_other_doc_count > 0` | Часть документов отброшена при `size` | Это норма при top-N; для полного набора — `composite` |
| Топ меняется между запусками | Обновление данных + приблизительный отбор | `shard_size`, стабильный `query`, предвычисление |
| Медленные агрегации по `now` | Date math с `now` не кэшируется request cache | Фиксированный интервал (отсечка по часам) вместо `now` в каждом запросе |
| `percentiles` возвращает NaN / странные значения | Мало данных в выборке или поле не числовое | Проверить маппинг, `value_count` рядом |
| Ответ с `_shards.failed > 0`, значения занижены | Недоступна часть шардов или сработали таймауты шардов; при `allow_partial_search_results: true` (default) частичный результат возвращается как обычный | Смотреть `_shards.failures`; для отчётов без частичных данных — `"allow_partial_search_results": false` в запросе (cluster default — `search.default_allow_partial_results`) |
| Запрос падает конфликтом типов поля по `logs-*` | Часть индексов паттерна маппит поле иначе | `GET /logs-*/_mapping/field/<field>`, привести маппинг ([Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)) |
| Корзина по полю пуста, хотя данные есть | Поле отсутствует в маппинге части индексов паттерна — эти документы не участвуют в агрегации | Проверить `_mapping/field`; полноту заполнения — `missing`-агрегацией |
| Запрос отклонён из-за глубокой вложенности агрегаций | Превышен `search.aggs.max_nested_depth` (dynamic, default 50, максимум 1000) | Уменьшить вложенность или осознанно поднять лимит |
| Синхронный `_search` с агрегацией не успевает (обрыв на прокси, таймаут клиента) | Тяжёлый запрос не укладывается в ожидание вызывающей стороны | `POST /logs-*/_async_search?wait_for_completion_timeout=60s`, добрать результат через `GET _async_search/<id>`; ответ хранится `keep_alive` (default 5d, удаление — `DELETE _async_search/<id>`), лимит размера — `search.max_async_search_response_size` (default 10mb) |

## Best Practices

* **`size: 0`** для чисто аналитических запросов — не транспортировать hits, ответ попадает в shard request cache (не кэшируется при `from/size`).
* **`keyword` вместо `text`** для всех агрегируемых полей; doc_values включены по умолчанию для `keyword`/чисел/`date`.
* **Один `query` на запрос** — сузить документы до нужного среза ДО агрегации; вложенный `filter` внутри `aggs` — для срезов, отличных от общего query.
* **Не гоняйте `terms` с `size` > сотен-тысяч** — упрётесь в `max_buckets` и reduce-память; `composite` для полного обхода.
* **Кардинальность:** `cardinality` с подобранным `precision_threshold` (3000–10000), не `terms` с бесконечным `size`.
* **Тяжёлые/редкие агрегации** — в отдельные запросы (не в основной поиск), либо предвычисление ([Transform](./elasticsearch_rollup_transform.md), [downsampling TSDS](./elasticsearch_ilm_and_retention.md)).
* **Мониторинг:** `GET _nodes/stats/breaker` (request/fielddata), медленные запросы — в slow log; объём ответа — по `took`.
* **Проверяйте `doc_count_error_upper_bound`** в проде: ненулевое значение у критичного отчёта — сигнал поднять `shard_size` или сменить стратегию; `_shards.failed` — сигнал не доверять цифрам вообще.
* **Долгие разовые агрегации** — `_async_search` вместо синхронного `_search`; ответ сузить до агрегатов через `filter_path=aggregations` ([Search Tuning](./elasticsearch_search_tuning.md)).
* **`significant_terms`** — два прохода (список → детали), дорогие под-агрегации — под `sampler`; `min_doc_count` держать ≥ 3.
* Для аналитики «вместо группировки в Kibana» — рассмотрите ES|QL: конвейерный синтаксис поверх columnar engine ([ES|QL](./esql-query-language.md)).

## См. также

* **[Query DSL](./elasticsearch_query_dsl.md)** — запрос, с которого начинается агрегация.
* **[Search Tuning](./elasticsearch_search_tuning.md)** — производительность агрегаций, кэши, circuit breaker, профилирование.
* **[Rollup и Transform](./elasticsearch_rollup_transform.md)** — предвычисление агрегатов для истории.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — типы полей и doc_values, от которых зависит возможность агрегации.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — downsampling TSDS как предвычисленные агрегаты метрик.
* **[ES|QL](./esql-query-language.md)** — `STATS` и `PERCENTILE` как альтернативный синтаксис агрегативной аналитики.
* **[Алертинг](./elasticsearch_alerting.md)** — index-threshold правила: свёртка (count/avg/sum/min/max, top по терму) поверх тех же данных.
* **[Kibana: поиск и визуализация](../Kibana/kibana_search_and_visualization.md)** — lens-визуализации поверх агрегаций.

### Перекрытие с существующими файлами (§0.10)

* `Elasticsearch/elasticsearch_search_tuning.md` — SSoT по тюнингу поиска: секции «High Cardinality Aggregations», «Circuit Breaker», «Лимиты поиска» и «Лучшие практики» покрывают агрегации с точки зрения производительности; настоящий файл покрывает семантику, API и типы агрегаций, тюнинг не дублирует (ссылки).
* `Elasticsearch/elasticsearch_rollup_transform.md` — SSoT по предвычислению истории (Rollup/Transform); здесь предвычисление только упоминается как решение для тяжёлых агрегаций.
* `Elasticsearch/elasticsearch_mapping_and_indexing.md` — SSoT по маппингу, `keyword`, doc_values, fielddata; настоящий файл ссылается.
* `Elasticsearch/esql-query-language.md` — эталонный файл по синтаксису ES|QL, включая `STATS`; здесь ES|QL только упоминается как альтернатива для аналитики.
* `Elasticsearch/elasticsearch_alerting.md` — эталонный файл по правилам алертинга; index-threshold там описан своими терминами (`aggType`/`groupBy`), семантика агрегаций — в настоящем файле, дублирования примеров нет.
* `OpenSearch/opensearch-query-dsl-search.md` — раздел «Агрегации» в обзоре DSL для OpenSearch; пересечение по базовым примерам `terms`/`date_histogram` неизбежно (параллельная продуктовая линия, принятая в базе).
