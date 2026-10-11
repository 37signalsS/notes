# Elasticsearch: Индексирование, маппинг и структуры данных

**Актуально для:** Elasticsearch 8.x / 9.x

> Эта заметка является авторитетным источником по вопросам проектирования схем данных (mapping), управления индексами и потоков данных (Data Streams) в Elasticsearch. Она охватывает как классические методы текстового поиска, так и современные возможности векторного и семантического поиска. Базовые понятия кластера (шарды, роли узлов) описаны в [обзоре Elasticsearch](./elasticsearch_overview.md); автоматизация жизненного цикла — в [ILM и политиках хранения](./elasticsearch_ilm_and_retention.md).

## Определения

* **Маппинг (Mapping)**: Определение структуры документа, типов его полей и правил их индексации. Аналог схемы таблицы в реляционных базах данных.
* **Инвертированный индекс**: Структура данных, оптимизированная для полнотекстового поиска, связывающая слова со списком документов.
* **Doc values**: Колоночное хранилище значений полей на диске (по умолчанию включено для всех типов, кроме `text`). Основа агрегаций, сортировок и скриптов.
* **Поток данных (Data Stream)**: Абстракция над набором скрытых индексов (`backing indices`) для эффективной обработки данных временных рядов (логов, метрик). Каждый документ обязан содержать поле `@timestamp` (тип `date` или `date_nanos`).
* **TSDS (Time Series Data Stream)**: Специализированный поток данных (`index.mode: time_series`) для метрик: поля размечаются как `time_series_dimension` (измерения) и `time_series_metric` (`gauge`, `counter`, `histogram`). Документы получают автоматически генерируемое метаполе `_tsid`, маршрутизация идёт по измерениям, внутренние сегменты сортируются по `_tsid` и `@timestamp`.
* **LogsDB**: Режим индекса (`index.mode: logsdb`, GA с 8.17) для логов; в бенчмарках занимает ~2.5x меньше места, чем обычный Data Stream. Использует synthetic `_source` при наличии подписки.
* **Runtime Fields**: Виртуальные поля, вычисляемые с помощью скриптов (Painless) в момент выполнения запроса либо читаемые напрямую из `_source` (без скрипта). Позволяют изменять логику поиска без переиндексации.
* **Квантование (Quantization)**: Метод сжатия векторных данных (`int8`, `int4`, `bbq`), снижающий потребление RAM ценой некоторой потери точности поиска.
* **HNSW (Hierarchical Navigable Small World)**: Алгоритм построения графа для приближенного поиска ближайших соседей, используемый в полях типа `dense_vector`. Граф хранится off-heap (в page cache ОС).
* **Синтетический исходник (`synthetic _source`)**: Режим хранения, при котором оригинальный JSON документа не сохраняется целиком, а восстанавливается на лету из индексированных полей. Требует подписки (Platinum+); для TSDS включён по умолчанию с 8.7.
* **Анализатор (Analyzer)**: Конвейер обработки текста перед индексацией: character filters → tokenizer → token filters. Определяет, какие термы попадут в инвертированный индекс.
* **Мультиполе (multi-field)**: Дополнительные представления одного поля под разными типами (`text` с сабфилдом `keyword`) — позволяют одновременно делать полнотекстовый поиск и агрегации.
* **Динамический шаблон (Dynamic Template)**: Правило в маппинге, определяющее тип автоматически создаваемых полей по имени или паттерну значения (`match_mapping_type`, `path_match`).
* **Refresh**: Перевод документов из внутреннего буфера в новый сегмент Lucene, после которого они становятся доступны для поиска. Elasticsearch работает по принципу near-real-time (NRT).
* **Translog**: Журнал упреждающей записи (WAL) на диске; гарантирует durability и используется при восстановлении шарда после сбоя.

## Основные концепции

### Типы маппинга

1.  **Явный (Explicit)**: Полное описание всех полей. Рекомендуется для Production-сред для предотвращения конфликтов типов и избыточного расхода ресурсов.
2.  **Динамический (Dynamic)**: Elasticsearch автоматически создает поля при первом появлении. Режим задаётся параметром `dynamic`:
    *   `true` (дефолт): новые поля добавляются в маппинг.
    *   `"strict"`: новые поля вызывают ошибку (защита от "взрыва маппинга").
    *   `"runtime"`: новые поля добавляются как runtime-поля (не занимают место на диске, доступны для поиска; не поддерживается для columnar-индексов).
    *   `false`: новые поля игнорируются (не индексируются и не ищутся, но остаются в `_source`; на columnar-индексах такие поля теряются полностью).
    *   `dynamic_templates`: массив правил для автоматических полей. Пример: все строки без явного типа делать `keyword`, а не дефолтным `text` (+keyword), что экономит место для идентификаторов:
        ```json
        "dynamic_templates": [
          { "strings_as_keywords": {
              "match_mapping_type": "string",
              "mapping": { "type": "keyword" }
          } }
        ]
        ```
    *   Динамическое добавление полей работает, пока не достигнут `index.mapping.total_fields.limit`; при превышении запрос по умолчанию падает, если не задано `"index.mapping.total_fields.ignore_dynamic_beyond_limit": true` — тогда поля за лимитом не добавляются (как при `dynamic: false`) и попадают в метаполе `_ignored`.

### Ключевые типы полей

| Тип | Назначение | Особенности |
| :--- | :--- | :--- |
| **`text`** | Полнотекстовый поиск. | Проходит через анализаторы (tokenization). Не поддерживает сортировку/агрегации. |
| **`keyword`** | Точное совпадение. | Оптимизирован для фильтрации, агрегций и сортировки через `doc_values`. |
| **`match_only_text`** | Логи: полнотекстовый поиск без scoring. | С 7.14; экономит ~10% места (`index_options: docs`, `norms: false`); score всегда 1.0; анализатор не настраивается (только `standard`); `span`-запросы не поддерживаются, `match_phrase` медленнее (проверка по `_source`). |
| **`dense_vector`** | Векторный (k-NN) поиск. | Использует HNSW. Поддерживает квантование `int8`, `int4`, `bbq`. Однозначное поле (массив значений не хранит). |
| **`semantic_text`** | Семантический поиск. | Preview 8.15, GA 9.0. Автоматически управляет эмбеддингами через Inference API, включая чанкинг текста. |
| **`wildcard`** | Поиск по маскам/regex. | Эффективнее `text` для поиска подстрок (например, в логах). |

Помимо перечисленных, часто используются: `date` (с параметром `format`, по умолчанию `strict_date_optional_time||epoch_millis`), числовые `long`/`integer`/`double`, `ip`, `geo_point` (координаты для карт и фильтров по расстоянию), `flattened` (произвольный JSON как один keyword — защита от взрыва полей) и `alias` (указатель на другое поле).

Полезное поведение динамического маппинга: массив float-элементов длиной от 128 до 4096 автоматически маппится как `dense_vector` с similarity `cosine` — явно задавайте тип, если это не вектора.

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
*   `ignore_above` — строки/массивы длиннее лимита не индексируются (для `keyword` в примере выше — 256 символов).

### Вложенность данных: `object` vs `nested`

*   **`object`**: Структура "сплющивается" (flattened). Поиск по массиву объектов может выдавать ложноположительные результаты (связи между полями внутри одного объекта теряются).
*   **`nested`**: Каждый объект индексируется как скрытый документ. Сохраняет внутренние связи, но замедляет поиск и индексацию.

Выбор типа и ограничения:

*   Поиск по `nested` выполняется только через `nested`-запрос с указанием `path`, а агрегации — через `nested`-агрегацию; обычный `match` по вложенному полю не увидит данных.
*   Число вложенных объектов на один документ лимитируется настройкой `index.mapping.nested_objects.limit` (по умолчанию 10000) — превышение вызывает ошибку индексации.
*   Каждый nested-объект — отдельный документ Lucene: массив из 100 объектов = 101 документ. Для больших массивов это раздувает сегменты; если связи между полями не нужны, оставьте `object`.
*   В режиме `synthetic _source` массивы объектов восстанавливаются в "сплющенном" виде (поля собираются на уровне листьев) — учитывайте при чтении исходных документов.

### Лимиты маппинга (предотвращение mapping explosion)

| Настройка | Дефолт | Назначение |
| :--- | :--- | :--- |
| `index.mapping.total_fields.limit` | 1000 | Максимум полей (объекты, алиасы и runtime-поля тоже считаются). |
| `index.mapping.depth.limit` | 20 | Максимальная глубина вложенности (число внутренних объектов). |
| `index.mapping.nested_fields.limit` | 50 (8.x) / 100 (текущие версии) | Число distinct nested-маппингов на индекс. |
| `index.mapping.nested_objects.limit` | 10000 | Число nested-объектов в одном документе. |
| `index.mapping.dimension_fields.limit` | 32768 | Число TSDS-измерений (`time_series_dimension`) на индекс. |

Превышение `total_fields.limit` даёт ошибку `limit of total fields [1000] has been exceeded`; поведение настраивается через `index.mapping.total_fields.ignore_dynamic_beyond_limit` (см. раздел «Типы маппинга»).

### Векторные поля и квантование (`dense_vector`)

Параметры поля:

*   `dims` — число измерений (максимум 4096; если не задано, берётся из длины первого проиндексированного вектора).
*   `index: true` (дефолт) — индексация для приближенного kNN; `false` — только точный scoring через `dense_vector`-запрос или `script_score`.
*   `similarity` — метрика: `cosine` (дефолт для float; векторы автоматически нормализуются при индексации), `l2_norm`, `dot_product`, `max_inner_product`; для `element_type: bit` — только `l2_norm`.
*   `element_type` — `float` (дефолт), `byte` (значения −128…127; длина векторов запроса и документа должна совпадать), `bit` (8.15+, расстояние Хэмминга).
*   `index_options` — алгоритм и квантование: `hnsw`, `int8_hnsw`, `int4_hnsw`, `bbq_hnsw`, `bbq_flat`, `bbq_disk`, `flat`, `int8_flat`, `int4_flat`. Параметры графа: `m` (дефолт 16 — связность графа) и `ef_construction` (дефолт 100 — качество построения); `confidence_interval` (0.90–1.0, дефолт `1/(dims+1)`) — для `int8`/`int4` вариантов.

Квантование и дефолтный тип индекса по версиям (для `element_type: float`):

| Версия | Дефолтный `index_options.type` |
| :--- | :--- |
| 8.14 – 9.0 | `int8_hnsw` (4x экономия RAM) |
| 9.1+ | `bbq_hnsw` для `dims >= 384`, иначе `int8_hnsw` |
| 9.4+ | `bbq_disk`, когда доступен по текущей лицензии |

*   `int4_hnsw` — с 8.15, 8x экономия, требует чётного числа измерений.
*   `bbq` (Better Binary Quantization) — 32x экономия; введён в 8.16 (для клиентов Elastic), GA в 9.0/8.18; поддерживает `dims >= 64`; для компенсации потери точности применяется oversampling и rescoring при поиске.
*   `bbq_disk` — GA с 9.2, требует подписку Enterprise; хранит сжатые вектора на диске вместо RAM (для больших коллекций с низким бюджетом памяти); с 9.5 доступен `auto_calibrate: true` (автоподбор кодирования и oversampling по сегментам).
*   Квантование не удаляет исходные вектора: сырые `float` значения хранятся на диске для re-rank'инга и будущих улучшений — диск растёт на ~25% для `int8`, ~12.5% для `int4`, ~3.1% для `bbq`.
*   Смена `type` в `index_options` возможна без переиндексации через Update Mapping API — новые сегменты создаются в новом формате (старые конвертируются при merge).

### Semantic Text (`semantic_text`)

Поле автоматически генерирует эмбеддинги при индексации текста через Inference API:

*   Preview в 8.15, **GA с 9.0**. Если `inference_id` не задан, используется преднастроенный endpoint `.elser-2-elasticsearch`.
*   `search_inference_id` — отдельный endpoint для поиска (если не задан, используется `inference_id`).
*   `chunking_settings` — стратегия чанкинга (`strategy`, `max_chunk_size`, `overlap`); переопределяет настройки endpoint'а.
*   `index_options` — квантование эмбеддингов (например, `{"dense_vector": {"type": "bbq_disk"}}`); с 9.1 новые индексы с плотными эмбеддингами `dims >= 64` автоматически квантуются в `bbq_hnsw`.
*   Может быть мультиполем для `text`; поддерживает запросы `match`, `sparse_vector`, `knn` и `semantic`.
*   Ограничения: не поддерживается внутри `nested`-полей и в dynamic templates.

### Runtime-поля

*   Значение вычисляется скриптом (Painless) в момент запроса или читается из `_source` без скрипта — поле не занимает место на диске.
*   Объявляются в секции `runtime` маппинга (`PUT /index/_mapping`) или прямо в теле поискового запроса (`runtime_mappings`) — для ad-hoc анализа без изменения индекса.
*   Скорость ниже, чем у проиндексированных полей (скрипт на каждый документ) — инструмент для редких запросов; востребованные постоянно поля переносите в явный маппинг.

### Data Streams, TSDS и LogsDB

*   **Data Stream**: требует шаблона с `"data_stream": {}`; каждый документ обязан содержать `@timestamp` (`date`/`date_nanos`); при явном `_id` — first-write-wins; обновление/удаление — через `_update_by_query`/`_delete_by_query`.
*   **TSDS** (`index.mode: time_series`): помимо `@timestamp` требуется хотя бы одно dimension-поле (`time_series_dimension: true`); кастомные `_id` не поддерживаются, дубликаты data points отклоняются; маршрутизация по измерениям (`index.routing_path` строится из dimension-полей автоматически) гарантирует, что точки одной серии попадают в один шард; сегменты внутренне сортируются по `_tsid` и `@timestamp`; с 9.3 включены docvalue skippers (меньше диска, быстрее ingest), с 9.4 по умолчанию отключены sequence numbers (до 2x экономии места).
*   **LogsDB** (`index.mode: logsdb`, GA 8.17): ~2.5x меньше диска для логов; использует synthetic `_source` при наличии подписки; `index.mapping.synthetic_source_keep` по умолчанию `arrays` (сохраняет порядок и дубликаты в многозначных полях).

### Synthetic `_source`

*   Восстанавливает документ на лету из проиндексированных полей; **требует подписки** (Platinum+). Для TSDS включён по умолчанию **с 8.7** (до 8.7 `_source` хранился явно).
*   Настройка: с 8.18 — index setting `"index.mapping.source.mode": "synthetic"` (значения `stored`/`synthetic`/`disabled`); до 8.18 — `mappings._source.mode` (конфигурация через маппинг deprecated с 8.18).
*   `_source` нельзя отключить для индексов с `index.mode` `logsdb` или `time_series`.
*   Модификации при чтении: массивы перемещаются к leaf-полям; точки в именах полей интерпретируются как вложенные объекты (если у объекта не включён `subobjects: false`). Точность восстановления многозначных полей управляется `index.mapping.synthetic_source_keep` (`none`/`arrays`; дефолт `arrays` для logsdb, иначе `none`).
*   Чтение `_source` медленнее, чем у хранимого — экономия диска оплачивается скоростью Get/Search по `_source`.

### Процесс индексирования: Refresh, Flush и Translog

Понимание жизненного цикла документа критично для настройки задержки поиска и надежности:

1.  Документ попадает в **memory buffer** и одновременно записывается в **translog** (журнал упреждающей записи на диске для восстановления после сбоя).
2.  **Refresh** (раз в `index.refresh_interval`, по умолчанию `1s`) создает новый сегмент Lucene из буфера — только теперь документ виден поиску. Отсюда термин near-real-time: задержка до секунды.
3.  **Flush** (Lucene commit) выполняется автоматически при достижении translog порога `index.translog.flush_threshold_size` — дефолт **10 ГБ с версии 8.8** (ранее 512 МБ), причём реальный порог никогда не превышает 1% диска. Сегменты сбрасываются на диск, translog обрезается. В исходном коде текущих версий также задана минимальная периодичность flush — `index.translog.flush_threshold_age` (дефолт `1m`; в документации 8.x не перечислена). Ручной flush: `POST /index/_flush`.

Практические следствия:

*   Для массовой загрузки отключите автorefresh: `"refresh_interval": "-1"`, затем вызовите `POST /index/_refresh` вручную (пример в сценарии 6).
*   Надежность записи регулируется транслогом: `"index.translog.durability": "request"` (дефолт, fsync на каждый запрос) против `async` (fsync раз в `index.translog.sync_interval`, дефолт 5s — быстрее, но возможна потеря последних операций при падении).
*   Восстановление шарда после сбоя читает translog: `index.translog.retention.size` (дефолт 512mb) и `index.translog.retention.age` (дефолт 12h) определяют, как долго хранятся файлы для наверстывания реплик.
*   Сегменты неизменяемы: удаление документов лишь помечает их, место освобождается при merge. Частые точечные обновления фрагментируют сегменты.

## Практические сценарии

**Предварительные требования для всех сценариев**:

```bash
export ES="https://localhost:9200"
export PASS="<пароль пользователя elastic>"
curl -u elastic:$PASS -k "$ES"   # → {"name" : "es-node-1", ..., "tagline" : "You Know, for Search"}
```

### 1. Настройка современного TSDB-индекса (8.x)

Использование режима `time_series` для максимальной экономии ресурсов (synthetic `_source` включается автоматически).

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

Пояснения к настройкам: для режима `time_series` synthetic `_source` включается **автоматически начиная с версии 8.7** — явная строка `"index.mapping.source.mode": "synthetic"` избыточна для TSDS, но приведена для читаемости и для явного включения режима на обычных индексах (с 8.18 это index setting; до 8.18 — `mappings._source.mode`). Поле `@timestamp` обязательно для любого Data Stream; dimension-поля (`host.name`) используются для маршрутизации документов по шардам (`index.routing_path` строится из них автоматически). Synthetic `_source` требует подписки.

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
          "type": "int4_hnsw",
          "m": 16,
          "ef_construction": 100
        }
      }
    }
  }
}'
# → {"acknowledged":true,"shards_acknowledged":true,"index":"images"}
```

Ограничения и детали квантования (проверено по документации Elastic):

*   `int4_hnsw` доступен **с версии 8.15** и требует четного числа измерений (`dims`).
*   Квантование не удаляет исходные векторы: сырые `float` значения хранятся на диске для re-rank'инга и будущих улучшений (+12.5% диска для `int4`, ~25% для `int8`, ~3.1% для `bbq`).
*   Дефолтный тип индекса зависит от версии и размерности — см. таблицу в разделе «Векторные поля и квантование» (8.14–9.0: `int8_hnsw`; 9.1+: `bbq_hnsw` для `dims >= 384`; 9.4+: `bbq_disk` при доступной лицензии).
*   `bbq_hnsw`/`bbq_flat` — бинарное квантование (32x экономии RAM, `dims >= 64`), GA с 9.0/8.18; для компенсации точности используйте oversampling/rescoring при поиске. Дисковый вариант `bbq_disk` (GA 9.2, подписка Enterprise) хранит граф вне RAM.

Загрузка тестового документа и kNN-поиск:

```bash
curl -u elastic:$PASS -k -X POST "$ES/images/_doc?refresh=true" -H 'Content-Type: application/json' \
-d'{ "title": "закат над городом", "image_vector": [0.12, -0.45, "... 512 значений ..."] }'
# → {"result":"created",...}

curl -u elastic:$PASS -k "$ES/images/_search" -H 'Content-Type: application/json' -d'
{
  "knn": {
    "field": "image_vector",
    "query_vector": [0.12, -0.45, "... 512 значений ..."],
    "k": 2,
    "num_candidates": 100
  }
}'
# → {"hits":{"total":{"value":1},"max_score":0.99,...,
#     "hits":[{"_index":"images","_id":"...","_score":0.99,
#       "_source":{"title":"закат над городом",...}}]}}
```

Параметры поиска: `k` — сколько результатов вернуть (опционален с 9.5, иначе по умолчанию равен `size` запроса); `num_candidates` — размер пула кандидатов на шарде (дефолт `min(1.5 * k, 10000)`, максимум 10000; больше = точнее, но медленнее); `filter` — pre-filter документов (при малом числе отфильтрованных документов Lucene переключается на brute force); `visit_percentage` (9.2+, только `bbq_disk`) — доля векторов на шарде, при задании игнорируется `num_candidates`.

### 3. Использование Semantic Text (Elasticsearch 9.0 GA / 8.15 preview)

Автоматическая генерация эмбеддингов при индексации обычного текста.

```bash
# Предварительно настройте Inference API (например, ELSER);
# при отсутствии inference_id используется преднастроенный endpoint .elser-2-elasticsearch
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/my-semantic-index" -H 'Content-Type: application/json' -d'
{
  "mappings": {
    "properties": {
      "content": {
        "type": "semantic_text",
        "inference_id": "my-elser-model",
        "chunking_settings": {
          "strategy": "word",
          "max_chunk_size": 300,
          "overlap": 50
        }
      }
    }
  }
}'

# Индексация документа — эмбеддинги и чанкинг выполняются автоматически
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

Ограничения: `semantic_text` не поддерживается внутри `nested`-полей и в dynamic templates; для мультимодального ввода (изображения, аудио, PDF) используйте тип `semantic`.

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
#     {"token":"кластер","...},{"token":"elasticsearch","..."}]}
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

## Диагностика и устранение проблем

Типичные ошибки при работе со схемами:

*   **`mapper_parsing_exception`** — значение не соответствует типу поля (строка в `long`). Проверьте фактический тип: `GET index/_mapping`. Для устойчивости задайте `"ignore_malformed": true` на поле — плохие значения попадут в метаполе `_ignored` вместо отказа документа.
*   **`strict_dynamic_mapping_exception`** — документ содержит незарегистрированное поле при `"dynamic": "strict"`. Добавьте поле в маппинг (`PUT _mapping`) или пересмотрите режим.
*   **`limit of total fields [1000] has been exceeded`** — сработал `index.mapping.total_fields.limit`, обычно из-за динамических полей в произвольном JSON. Решения: поднять лимит временно, перейти на `flattened`/`dynamic: strict`, либо задать `index.mapping.total_fields.ignore_dynamic_beyond_limit: true` (поля за лимитом попадут в `_ignored` вместо отказа).
*   **Поле найдено в `_source`, но поиск его не видит** — поле добавлено в маппинг после индексации старых документов: маппинг применяется только к новым данным. Проверка: `GET index/_search {"query":{"exists":{"field":"new_field"}}}` вернет только новые документы.
*   **Непредсказуемые результаты по массиву объектов** — используется `object` вместо `nested` (см. раздел «Вложенность данных»).
*   **`vector length must be [X], but was [Y]`** — размерность загружаемого вектора не совпадает с `dims` в маппинге; проверьте модель эмбеддингов.

Утилиты диагностики:

```bash
# Итоговый маппинг индекса (включая runtime-поля)
curl -u elastic:$PASS -k "$ES/products/_mapping?pretty"

# Как Elasticsearch проиндексировал конкретное значение
curl -u elastic:$PASS -k "$ES/products/_analyze" -H 'Content-Type: application/json' \
-d'{ "field": "name", "text": "SSD диск 1TB" }'

# Размер translog на шардах (должен быть ограничен flush threshold)
curl -u elastic:$PASS -k "$ES/products/_stats/translog?filter_path=**.translog"
```

## Дополнительная информация

### Производительность и тюнинг

*   **Force Merge**: Для векторных индексов (HNSW) выполняйте `_forcemerge?max_num_segments=1` после завершения записи — поиск проверяет один общий граф вместо нескольких сегментных. **Только на read-only индексах**: force merge на пишущихся индексах создаёт сегменты >5 ГБ, не участвующие в обычных merge, — растут soft-deleted документы и занимаемое место.
*   **Off-heap RAM**: Графы HNSW хранятся вне Java Heap (в page cache ОС). Убедитесь, что серверу хватает оперативной памяти сверх лимита JVM.
*   **Doc Values**: По умолчанию включены для всех полей, кроме `text`. Это основа для быстрой работы агрегаций и скриптов.
*   **Выбор квантования векторов**: `int8_hnsw` — безопасный дефолт (4x экономия RAM); `int4_hnsw` — 8x при чётных `dims`; `bbq_hnsw` — 32x для крупных коллекций (с 9.1 дефолт для `dims >= 384`), требует oversampling для точности; варианты `*_flat` — полный перебор для малых наборов, где он быстрее и точнее графа. Смена `type` в `index_options` возможна без переиндексации через Update Mapping API — новые сегменты будут создаваться уже в новом формате.
*   **Отключение ненужных структур**: для служебных полей-меток выключайте `norms` и, если не нужны агрегации, `doc_values` — на миллиардах документов это заметная экономия диска (см. параметры в разделе Мультиполя).
*   **Индексация векторов** — дорогая операция (построение графа на каждый сегмент): увеличьте таймауты клиента для index/bulk-запросов и не забывайте про `ef_construction` (дефолт 100) как рычаг качества графа.

### Граничные случаи

*   **`dense_vector` однозначен**: в отличие от большинства типов, поле хранит ровно один вектор; массив векторов не поддерживается.
*   **`byte`-вектора**: значения только в диапазоне −128…127; длина вектора запроса и документа должна совпадать, иначе результаты неточны.
*   **`dims` максимум 4096**; при отсутствии `dims` размерность фиксируется по первому проиндексированному вектору.
*   **Маппинг только добавляется**: существующее поле нельзя перетипизировать или удалить через `PUT _mapping` — только reindex в новый индекс (сценарий 4).
*   **HNSW — приближенный поиск**: результат не гарантирует точных k ближайших соседей; точность растёт с `num_candidates` ценой latency.
*   **TSDS**: кастомные `_id` не поддерживаются, дубликаты data points отклоняются; `_source` отключить нельзя.
*   **Columnar-индексы**: `dynamic: false` теряет новые поля полностью (не попадают даже в `_source`); `dynamic: runtime` не поддерживается.
*   **kNN в CCS**: опция `ccs_minimize_roundtrips` не поддерживается при kNN-поиске через cross-cluster search.
*   **`match_only_text`**: `span`-запросы не поддерживаются; `match_phrase` работает медленнее `text` (проверка по `_source`).
*   **Synthetic `_source`**: при чтении массивы перемещаются к leaf-полям, а точки в именах полей трактуются как вложенные объекты (кроме объектов с `subobjects: false`).

### Cleanup

```bash
# Удалить тестовые индексы и потоки (для data stream удаляются и backing-индексы)
curl -u elastic:$PASS -k -X DELETE "$ES/images" "$ES/articles" "$ES/products"
curl -u elastic:$PASS -k -X DELETE "$ES/_data_stream/metrics-default"

# Удалить шаблоны, созданные в сценариях
curl -u elastic:$PASS -k -X DELETE "$ES/_index_template/metrics-template"
curl -u elastic:$PASS -k -X DELETE "$ES/_component_template/logs-mappings"

# Вернуть настройки индекса после экспериментов (если не удаляли индекс)
curl -u elastic:$PASS -k -X PUT "$ES/products/_settings" -H 'Content-Type: application/json' \
-d'{ "index": { "refresh_interval": "1s", "number_of_replicas": 1 } }'

# Удалить временный файл bulk-загрузки
rm /tmp/bulk.ndjson
```

### Смотрите также

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера и роли узлов.
*   **[Elasticsearch: Жизненный цикл (ILM)](./elasticsearch_ilm_and_retention.md)** — автоматизация ротации данных.
*   **[ES|QL: Аналитический язык запросов](./elasticsearch_overview.md#использование-esql-для-аналитики)**.
*   **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — шаблоны и Data Streams.
*   **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — обработка документов перед индексацией.
*   **[Search Performance Tuning](./elasticsearch_search_tuning.md)** — оптимизация поиска.
*   **[Grok и Dissect Patterns](../grok_dissect_patterns.md)** — паттерны для парсинга логов.
