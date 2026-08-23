# Elasticsearch: Индексирование, маппинг и структуры данных

> Эта заметка является авторитетным источником по вопросам проектирования схем данных (mapping), управления индексами и потоками данных (Data Streams) в Elasticsearch. Она охватывает как классические методы текстового поиска, так и современные возможности векторного и семантического поиска. Базовые понятия кластера (шарды, роли узлов) описаны в [обзоре Elasticsearch](./elasticsearch_overview.md); автоматизация жизненного цикла — в [ILM и политиках хранения](./elasticsearch_ilm_and_retention.md).

## Определения

* **Маппинг (Mapping)**: Определение структуры документа, типов его полей и правил их индексации. Аналог схемы таблицы в реляционных базах данных.
* **Инвертированный индекс**: Структура данных, оптимизированная для полнотекстового поиска, связывающая слова со списком документов.
* **Поток данных (Data Stream)**: Абстракция над набором скрытых индексов (`backing indices`) для эффективной обработки данных временных рядов (логов, метрик).
* **Runtime Fields**: Виртуальные поля, вычисляемые с помощью скриптов (Painless) в момент выполнения запроса. Позволяют изменять логику поиска без переиндексации.
* **Квантование (Quantization)**: Метод сжатия векторных данных (например, `int8` или `int4`), значительно снижающий потребление RAM при сохранении высокой точности k-NN поиска.
* **HNSW (Hierarchical Navigable Small World)**: Алгоритм построения графа для приближенного поиска ближайших соседей, используемый в полях типа `dense_vector`.
* **Синтетический исходник (`synthetic _source`)**: Режим хранения, при котором оригинальный JSON документа не сохраняется целиком, а восстанавливается на лету из индексированных полей (экономия места на диске до 30-50%).
* **Анализатор (Analyzer)**: Конвейер обработки текста перед индексацией: character filters → tokenizer → token filters. Определяет, какие термы попадут в инвертированный индекс.
* **Мультиполе (multi-field)**: Дополнительные представления одного поля под разными типами (`text` с сабфилдом `keyword`) — позволяют одновременно делать полнотекстовый поиск и агрегации.
* **Динамический шаблон (Dynamic Template)**: Правило в маппинге, определяющее тип автоматически создаваемых полей по имени или паттерну значения (`match_mapping_type`, `path_match`).
* **Refresh**: Перевод документов из внутреннего буфера в новый сегмент Lucene, после которого они становятся доступны для поиска. Elasticsearch работает по принципу near-real-time (NRT).

## Основные концепции

### Типы маппинга

1.  **Явный (Explicit)**: Полное описание всех полей. Рекомендуется для Production-сред для предотвращения конфликтов типов и избыточного расхода ресурсов.
2.  **Динамический (Dynamic)**: Elasticsearch автоматически создает поля при первом появлении.
    *   `dynamic: "strict"`: Новые поля вызывают ошибку (защита от "взрыва маппинга").
    *   `dynamic: "runtime"`: Новые поля добавляются как runtime-поля (не занимают место на диске, доступны для поиска).
    *   `dynamic_templates`: Массив правил для автоматических полей. Пример: все строки без явного типа делать `keyword`, а не дефолтным `text` (+keyword), что экономит место для идентификаторов:
        ```json
        "dynamic_templates": [
          { "strings_as_keywords": {
              "match_mapping_type": "string",
              "mapping": { "type": "keyword" }
          } }
        ]
        ```

### Ключевые типы полей

| Тип | Назначение | Особенности |
| :--- | :--- | :--- |
| **`text`** | Полнотекстовый поиск. | Проходит через анализаторы (tokenization). Не поддерживает сортировку/агрегации. |
| **`keyword`** | Точное совпадение. | Оптимизирован для фильтрации, агрегаций и сортировки через `doc_values`. |
| **`dense_vector`** | Векторный (k-NN) поиск. | Использует HNSW. Поддерживает квантование `int8` и `int4`. |
| **`semantic_text`** | Семантический поиск (8.15+). | Автоматически управляет эмбеддингами через Inference API, включая чанкинг текста. |
| **`wildcard`** | Поиск по маскам/regex. | Эффективнее `text` для поиска подстрок (например, в логах). |
| **`match_only_text`** | Поиск без позиций слов. | Экономит диск, если не нужен поиск по точным фразам. |

Помимо перечисленных, часто используются: `date` (с параметром `format`, по умолчанию `strict_date_optional_time||epoch_millis`), числовые `long`/`integer`/`double`, `ip`, `geo_point` (координаты для карт и фильтров по расстоянию), `flattened` (произвольный JSON как один keyword — защита от взрыва полей) и `alias` (указатель на другое поле).

### Анализ текста

Поле типа `text` проходит через конвейер анализа перед попаданием в инвертированный индекс:

1.  **Character Filters** — предобработка символов (удаление HTML-тегов `html_strip`, замена паттернов).
2.  **Tokenizer** — разбиение на термы (`standard` — по границам слов, `keyword` — весь ввод одним токеном, `ngram` — частичные совпадения).
3.  **Token Filters** — нормализация термов (`lowercase`, `stop` — стоп-слова, `stemmer` — приведение к основе).

Встроенные анализаторы: `standard` (дефолт), `simple`, `whitespace`, `keyword` (без изменений). Для неанглийских текстов используйте языковые анализаторы (`russian` включает стоп-слова и стемминг). Кастомный анализатор задается в секции `settings.analysis` (пример в сценарии 5).

### Мультиполя и параметры индексации

Стандартный паттерн для логов — одно поле с двумя представлениями:

```json
"message": {
  "type": "text",
  "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } }
}
```
Полнотекстовый поиск идет по `message`, агрегации и сортировки — по `message.keyword`. Именно эту структуру динамический маппинг создает автоматически для строк.

Ключевые параметры любого поля для управления ресурсами:

*   `index: false` — исключить поле из инвертированного индекса (недоступно для поиска, но остается в `_source`).
*   `doc_values: false` — отключить колоночное хранение (экономия диска; невозможны агрегации и сортировки).
*   `norms: false` — отключить учет длины поля для подсчета релевантности (полезно для полей, где score не важен — фильтры, метки).
*   `null_value` — подстановка значения вместо `null` для возможности поиска по нему.
*   `copy_to` — копирование значений нескольких полей в одно сводное для сквозного поиска.

### Вложенность данных: `object` vs `nested`

*   **`object`**: Структура "сплющивается" (flattened). Поиск по массиву объектов может выдавать ложноположительные результаты (связи между полями внутри одного объекта теряются).
*   **`nested`**: Каждый объект индексируется как скрытый документ. Сохраняет внутренние связи, но замедляет поиск и индексацию.

Выбор типа и ограничения:

*   Поиск по `nested` выполняется только через `nested`-запрос с указанием `path`, а агрегации — через `nested`-агрегацию; обычный `match` по вложенному полю не увидит данных.
*   Число вложенных объектов на один документ лимитируется настройкой `index.mapping.nested_objects.limit` (по умолчанию 10000) — превышение вызывает ошибку индексации.
*   Каждый nested-объект — отдельный документ Lucene: массив из 100 объектов = 101 документ. Для больших массивов это раздувает сегменты; если связи между полями не нужны, оставьте `object`.
*   В режиме `synthetic _source` массивы объектов восстанавливаются в "сплющенном" виде (поля собираются на уровне листьев) — учитывайте при чтении исходных документов.

### Предотвращение проблем

*   **Mapping Explosion**: Лимитируйте количество полей (`index.mapping.total_fields.limit`, по умолчанию 1000).
*   **Deep Nesting**: Ограничивайте глубину вложенных объектов (`index.mapping.depth.limit`).

### Процесс индексирования: Refresh, Flush и Translog

Понимание жизненного цикла документа критично для настройки задержки поиска и надежности:

1.  Документ попадает в **memory buffer** и одновременно записывается в **translog** (журнал упреждающей записи для восстановления после сбоя).
2.  **Refresh** (раз в `index.refresh_interval`, по умолчанию `1s`) создает новый сегмент Lucene из буфера — только теперь документ виден поиску. Отсюда термин near-real-time: задержка до секунды.
3.  **Flush** (при заполнении translog или раз в ~5 минут) сбрасывает сегменты на диск и очищает translog.

Практические следствия:

*   Для массовой загрузки отключите автorefresh: `"refresh_interval": "-1"`, затем вызовите `POST /index/_refresh` вручную (пример в сценарии 6).
*   Надежность записи регулируется транслогом: `"index.translog.durability": "request"` (дефолт, fsync на каждый запрос) против `async` (быстрее, но возможна потеря последних операций при падении).
*   Сегменты неизменяемы: удаление документов лишь помечает их, место освобождается при merge. Частые точечные обновления фрагментируют сегменты.

## Практические сценарии

**Предварительные требования для всех сценариев**:

```bash
export ES="https://localhost:9200"
export PASS="<пароль пользователя elastic>"
curl -u elastic:$PASS -k "$ES"   # → {"name" : "es-node-1", ..., "tagline" : "You Know, for Search"}
```

### 1. Настройка современного TSDB-индекса (8.x)

Использование `synthetic _source` и режима `time_series` для максимальной экономии ресурсов.

```bash
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_index_template/metrics-template" -H 'Content-Type: application/json' -d'
{
  "index_patterns": ["metrics-*"],
  "data_stream": {},
  "template": {
    "settings": {
      "index.mode": "time_series",
      "index.mapping.source.mode": "synthetic",
      "index.lifecycle.name": "metrics-policy"
    },
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" },
        "host.name": { "type": "keyword", "time_series_dimension": true },
        "cpu.usage": { "type": "float", "time_series_metric": "gauge" }
      }
    }
  },
  "priority": 500
}'
# → {"acknowledged":true}
```

Пояснения к настройкам: для режима `time_series` synthetic `_source` включается **автоматически начиная с версии 8.7** — явная строка `"index.mapping.source.mode": "synthetic"` приведена для читаемости и совместимости со старыми версиями. Поле `@timestamp` обязательно для любого Data Stream; dimension-поля (`host.name`) используются для маршрутизации документов по шардам (`index.routing_path` строится из них автоматически).

Сквозная проверка: первый документ создает поток с TSDB-режимом:

```bash
curl -u elastic:$PASS -k -X POST "$ES/metrics-default/_doc?refresh=true" \
-H 'Content-Type: application/json' \
-d'{ "@timestamp": "2026-08-23T12:00:00Z", "host.name": "web-01", "cpu.usage": 0.42 }'
# → {"_index":".ds-metrics-default-2026.08.23-000001","result":"created",...}

curl -u elastic:$PASS -k "$ES/_data_stream/metrics-default?filter_path=*.indices.*.index_name,*.generation"
# → {"data_streams":[{"name":"metrics-default","generation":1,
#     "indices":[{"index_name":".ds-metrics-default-2026.08.23-000001"}]}]}
```

### 2. Векторный поиск с квантованием (RAM Optimization)

Настройка поля для хранения эмбеддингов с использованием 4-битного квантования (экономия RAM в 8 раз по сравнению с `float32`).

```bash
curl -u elastic:$PASS -k -X PUT "$ES/images" -H 'Content-Type: application/json' -d'
{
  "mappings": {
    "properties": {
      "title": { "type": "text" },
      "image_vector": {
        "type": "dense_vector",
        "dims": 512,
        "index": true,
        "similarity": "cosine",
        "index_options": {
          "type": "int4_hnsw"
        }
      }
    }
  }
}'
# → {"acknowledged":true,"shards_acknowledged":true,"index":"images"}
```

Ограничения и детали квантования (проверено по документации Elastic):

*   `int4_hnsw` доступен **с версии 8.15** и требует четного числа измерений (`dims`).
*   Квантование не удаляет исходные векторы: сырые `float` значения хранятся на диске для re-rank'инга и будущих улучшений (+12.5% диска для `int4`, ~25% для `int8`).
*   Дефолт без явных `index_options`: `int8_hnsw`. Для больших моделей (dims >= 384) в новых версиях доступно бинарное квантование **BBQ**: `"type": "bbq_hnsw"` — 32-кратная экономия RAM с компенсацией точности через oversampling; для dims < 64 BBQ не поддерживается.
*   Дисковый вариант `bbq_disk` (9.2+) хранит граф вне RAM — требует подписку Enterprise.

Загрузка тестового документа и kNN-поиск:

```bash
curl -u elastic:$PASS -k -X POST "$ES/images/_doc?refresh=true" -H 'Content-Type: application/json' \
-d'{ "title": "закат над городом", "image_vector": [0.12, -0.45, "... 512 значений ..."] }'
# → {"result":"created",...}

curl -u elastic:$PASS -k "$ES/images/_search" -H 'Content-Type: application/json' -d'
{
  "knn": {
    "field": "image_vector",
    "query_vector": [0.12, -0.45],
    "k": 2,
    "num_candidates": 100
  }
}'
# → {"hits":{"total":{"value":1},"max_score":0.99,...,
#     "hits":[{"_index":"images","_id":"...","_score":0.99,
#       "_source":{"title":"закат над городом",...}}]}}
```

Параметры поиска: `k` — сколько результатов вернуть; `num_candidates` — размер пула кандидатов на шарде (больше = точнее, но медленнее; обычно 10-50x от `k`).

### 3. Использование Semantic Text (Elasticsearch 8.15+)

Автоматическая генерация эмбеддингов при индексации обычного текста.

```bash
# Предварительно настройте Inference API (например, ELSER)
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/my-semantic-index" -H 'Content-Type: application/json' -d'
{
  "mappings": {
    "properties": {
      "content": {
        "type": "semantic_text",
        "inference_id": "my-elser-model"
      }
    }
  }
}'

# Индексация документа — эмбеддинги генерируются автоматически
curl -u elastic:$PASS -k -X POST "$ES/my-semantic-index/_doc?refresh=true" \
-H 'Content-Type: application/json' \
-d'{ "content": "Kubernetes под управлением кластера упал из-за нехватки памяти на узлах" }'
# → {"_index":"my-semantic-index","result":"created",...}

# Семантический поиск: обычный текст в запросе, сравнение через inference endpoint
curl -u elastic:$PASS -k "$ES/my-semantic-index/_search" -H 'Content-Type: application/json' -d'
{
  "query": {
    "semantic": {
      "field": "content",
      "query": "падение kubernetes oom"
    }
  }
}'
# → {"hits":{"total":{"value":1},...,
#     "hits":[{"_index":"my-semantic-index","_score":..., "_source":{"content":"..."}}]}}
```

### 4. Миграция маппинга без простоя

Если нужно изменить тип существующего поля в Data Stream:
1.  **Обновить компонентный шаблон**: Создайте новую версию маппинга.
2.  **Обновить индексный шаблон**: Укажите новый компонент.
3.  **Rollover**: `POST /my-data-stream/_rollover`. Новые данные пишутся в новый индекс с новой схемой.
4.  **Reindex (опционально)**: Если старые данные нужны в новом формате, используйте `_reindex` API.

Те же шаги в командах:

```bash
# Шаги 1-2: обновление шаблонов (PUT по тому же имени перезаписывает версию)
curl -u elastic:$PASS -k -X PUT "$ES/_component_template/logs-mappings" -H 'Content-Type: application/json' -d'
{
  "template": {
    "mappings": {
      "properties": {
        "duration": { "type": "double", "ignore_malformed": true }
      }
    }
  }
}'
# → {"acknowledged":true}

# Шаг 3: ротация — новый backing-индекс получит новую схему
curl -u elastic:$PASS -k -X POST "$ES/logs-app-default/_rollover"
# → {"acknowledged":true,"shards_acknowledged":true,"new_index":".ds-logs-app-default-2026.08.24-000002"}

# Проверка схемы нового индекса
curl -u elastic:$PASS -k "$ES/.ds-logs-app-default-2026.08.24-000002/_mapping?filter_path=*.mappings.properties.duration"
# → {".ds-logs-app-default-2026.08.24-000002":{"mappings":{"properties":{"duration":{"type":"double"}}}}}
```

Для **классических индексов** (не Data Stream) смена типа поля невозможна без пересоздания — используется связка reindex + атомарное переключение алиаса:

```bash
curl -u elastic:$PASS -k -X POST "$ES/_reindex?refresh=true" -H 'Content-Type: application/json' -d'
{ "source": { "index": "orders-v1" }, "dest": { "index": "orders-v2" } }'
# → {"took":...,"created":15234,"updated":0,"failures":[]}

curl -u elastic:$PASS -k -X POST "$ES/_aliases" -H 'Content-Type: application/json' -d'
{
  "actions": [
    { "remove": { "index": "orders-v1", "alias": "orders"   } },
    { "add":    { "index": "orders-v2", "alias": "orders"   } }
  ]
}'
# → {"acknowledged":true}
```

Оба действия внутри `_aliases` выполняются атомарно — приложения продолжают работать с именем `orders` без простоя. Старый индекс удалите после проверки (`DELETE orders-v1`).

### 5. Кастомный анализатор для русского текста

Дефолтный `standard` не приводит русские слова к основе и не убирает стоп-слова — релевантность страдает. Создаем анализатор на базе языкового:

```bash
curl -u elastic:$PASS -k -X PUT "$ES/articles" -H 'Content-Type: application/json' -d'
{
  "settings": {
    "analysis": {
      "analyzer": {
        "ru_content": {
          "type": "russian",
          "stopwords": "_russian_"
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "analyzer": "ru_content",
        "fields": {
          "raw": { "type": "keyword", "ignore_above": 256 }
        }
      }
    }
  }
}'
# → {"acknowledged":true,"shards_acknowledged":true,"index":"articles"}
```

Проверка работы конвейера через `_analyze` API — обязательный шаг перед продом:

```bash
curl -u elastic:$PASS -k "$ES/articles/_analyze" -H 'Content-Type: application/json' \
-d'{ "analyzer": "ru_content", "text": "Настройка кластеров Elasticsearch" }'
# → {"tokens":[{"token":"настройк","start_offset":0,...},
#     {"token":"кластер","...},{"token":"elasticsearch","...}]}
```

В выводе видны эффекты фильтров: `lowercase` привел термы к нижнему регистру, `stemmer` усек слова до основ ("настройк", "кластер"). Поиск по запросу "настройки кластеров" теперь найдет документ благодаря совпадению основ:

```bash
curl -u elastic:$PASS -k "$ES/articles/_search?q=title:настройки%20кластеров"
# → {"hits":{"total":{"value":N},...}}
```

Мультиполе `title.raw` используется там, где стемминг мешает: сортировка по алфавиту и агрегации по точным значениям заголовков.

### 6. Быстрая загрузка данных через Bulk API

Пакетная индексация — стандарт для наполнения индексов. Формат NDJSON: строка действия, затем строка документа.

```bash
cat > /tmp/bulk.ndjson <<'EOF'
{ "index": { "_index": "products" } }
{ "name": "SSD диск 1TB", "price": 9900, "tags": ["ssd", "storage"] }
{ "index": { "_index": "products" } }
{ "name": "Кабель HDMI 2м", "price": 800, "tags": ["cable"] }
{ "create": { "_index": "products", "_id": "fixed-1" } }
{ "name": "Ноутбук", "price": 89900 }
EOF

curl -u elastic:$PASS -k -X POST "$ES/_bulk?refresh=false" \
-H 'Content-Type: application/x-ndjson' --data-binary @/tmp/bulk.ndjson
# → {"took":45,"errors":false,"items":[
#     {"index":{"_index":"products","status":201,"result":"created",...}},
#     {"index":{"_index":"products","status":201,...}},
#     {"create":{"_index":"products","_id":"fixed-1","status":201,...}}]}
```

Правила и грабли bulk:

*   **`errors: false`** означает успех всех операций; при частичных сбоях (`true`) разбирайте массив `items` — каждый элемент имеет собственный статус. Типичный сбой — конфликт версий `status: 409` при дублировании `_id`.
*   Оптимум: **5–15 МБ на запрос**; начните с 1000 документов в пакете и тестируйте на своих данных. Слишком большие пакеты давят на memory buffer очередей записи.
*   `Content-Type: application/x-ndjson` обязателен; используйте `--data-binary`, а не `-d` — последний портит переносы строк.
*   Действия `index` перезаписывает документ по `_id`; `create` требует его отсутствия (иначе `409`).

Для массовой одноразовой загрузки ускорьте процесс отключением автorefresh и реплик:

```bash
curl -u elastic:$PASS -k -X PUT "$ES/products/_settings" -H 'Content-Type: application/json' \
-d'{ "index": { "refresh_interval": "-1", "number_of_replicas": 0 } }'
# → {"acknowledged":true}

# ... загрузка ...

curl -u elastic:$PASS -k -X POST "$ES/_refresh"
# → {"_shards":{"total":2,"successful":2,"failed":0}}

# Вернуть настройки после загрузки:
curl -u elastic:$PASS -k -X PUT "$ES/products/_settings" -H 'Content-Type: application/json' \
-d'{ "index": { "refresh_interval": "1s", "number_of_replicas": 1 } }'
```

### 7. Runtime-поля: изменение схемы без переиндексации

Задача: поле `duration` было проиндексировано как строка, а нужна числовая агрегация. Вместо болезненной миграции (сценарий 4) добавляем вычисляемое поле:

```bash
curl -u elastic:$PASS -k -X PUT "$ES/logs-app-default/_mapping" -H 'Content-Type: application/json' -d'
{
  "runtime": {
    "duration_ms": {
      "type": "long",
      "script": {
        "source": "emit(Long.parseLong(doc[\"duration\"].value))"
      }
    }
  }
}'
# → {"acknowledged":true}
```

Поле не занимает место на диске и вычисляется в момент запроса:

```bash
curl -u elastic:$PASS -k "$ES/logs-app-default/_search?filter_path=aggregations" -H 'Content-Type: application/json' -d'
{
  "size": 0,
  "aggs": { "avg_duration": { "avg": { "field": "duration_ms" } } }
}'
# → {"aggregations":{"avg_duration":{"value":342.7}}}
```

Компромиссы: скорость ниже, чем у проиндексированных полей (скрипт на каждый документ), поэтому runtime — инструмент для ad-hoc анализа или редких запросов; поля, востребованные постоянно, переносите в явный маппинг через сценарий 4. Альтернатива без изменения индекса — runtime-определение прямо в теле поискового запроса (`runtime_mappings`).

### Диагностика проблем маппинга

Типичные ошибки при работе со схемами:

*   **`mapper_parsing_exception`** — значение не соответствует типу поля (строка в `long`). Проверьте фактический тип: `GET index/_mapping`. Для устойчивости задайте `"ignore_malformed": true` на поле — плохие значения попадут в метаполе `_ignored` вместо отказа документа.
*   **`strict_dynamic_mapping_exception`** — документ содержит незарегистрированное поле при `"dynamic": "strict"`. Добавьте поле в маппинг (`PUT _mapping`) или пересмотрите режим.
*   **`limit of total fields [1000] has been exceeded`** — сработал `index.mapping.total_fields.limit`, обычно из-за динамических полей в произвольном JSON. Решения: поднять лимит временно, перейти на `flattened`/`dynamic: strict`.
*   **Поле найдено в `_source`, но поиск его не видит** — поле добавлено в маппинг после индексации старых документов: маппинг применяется только к новым данным. Проверка: `GET index/_search {"query":{"exists":{"field":"new_field"}}}` вернет только новые документы.
*   **Непредсказуемые результаты по массиву объектов** — используется `object` вместо `nested` (см. раздел Вложенность).

Утилиты диагностики:

```bash
# Итоговый маппинг индекса (включая runtime-поля)
curl -u elastic:$PASS -k "$ES/products/_mapping?pretty"

# Как Elasticsearch проиндексировал конкретное значение
curl -u elastic:$PASS -k "$ES/products/_analyze" -H 'Content-Type: application/json' \
-d'{ "field": "name", "text": "SSD диск 1TB" }'
```

## Дополнительная информация

### Производительность и тюнинг

*   **Force Merge**: Для векторных индексов (HNSW) всегда выполняйте `_forcemerge?max_num_segments=1` после завершения записи. Это критически важно для качества и скорости k-NN поиска.
*   **Off-heap RAM**: Помните, что графы HNSW хранятся вне Java Heap (в page cache ОС). Убедитесь, что серверу хватает оперативной памяти сверх лимита JVM.
*   **Doc Values**: По умолчанию включены для всех полей, кроме `text`. Это основа для быстрой работы агрегаций и скриптов.
*   **Выбор квантования векторов**: `int8_hnsw` — безопасный дефолт (4x экономия RAM); `bbq_hnsw` — для крупных коллекций с dims >= 384 (32x, требует oversampling для точности); варианты `*_flat` — для малых наборов (до ~10k векторов), где полный перебор быстрее и точнее графа. Смена `type` в `index_options` возможна без переиндексации через Update Mapping API — новые сегменты будут создаваться уже в новом формате.
*   **Отключение ненужных структур**: для служебных полей-меток выключайте `norms` и, если не нужны агрегации, `doc_values` — на миллиардах документов это заметная экономия диска (см. параметры в разделе Мультиполя).

### Смотрите также

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера и роли узлов.
*   **[Elasticsearch: Жизненный цикл (ILM)](./elasticsearch_ilm_and_retention.md)** — автоматизация ротации данных.
*   **[ES|QL: Аналитический язык запросов](./elasticsearch_overview.md#использование-esql-для-аналитики)**.
*   **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — шаблоны и Data Streams.
*   **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — обработка документов перед индексацией.
*   **[Search Performance Tuning](./elasticsearch_search_tuning.md)** — оптимизация поиска.
*   **[Grok и Dissect Patterns](../grok_dissect_patterns.md)** — паттерны для парсинга логов.
