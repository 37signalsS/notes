# Rollup и Transform: Агрегация исторических данных

**Актуально для:** Elasticsearch 8.x / 9.x (Rollup — legacy: deprecated в 8.11.0)

> **Статус:** Rollup deprecated в 8.11.0 и будет удалён в будущей версии. Для новых развёртываний используйте [downsampling в TSDS](./elasticsearch_ilm_and_retention.md) — автоматическую свёртку метрик временных рядов. Раздел Rollup ниже документирует поддержку уже существующих job-ов.

> Руководство по механизмам Rollup и Transform для агрегации и хранения исторических данных. Рассматриваются use cases, API, ограничения и отличия от downsampling в TSDS.
>
> Связанные темы: ILM — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md); TSDS и маппинг — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md).

## Определения

* **Rollup** — механизм периодической агрегации сырых данных в компактный rollup-индекс. Сохраняет только агрегаты (min, max, sum, avg, value_count); исходные данные при этом **не удаляются** (удаление — отдельный шаг, обычно через ILM).
* **Rollup Job** — фоновая задача кластера, выполняющая периодическую агрегацию по расписанию cron. Job создаётся в состоянии `stopped` и запускается через `_start`.
* **Rollup Index** — целевой индекс для rollup, содержащий только агрегированные документы. Поиск в нём — только через `_rollup_search`.
* **Transform** — механизм создания pivot- или latest-представления данных из одного индекса в другой. Исходный индекс остаётся нетронутым; destination-индекс — обычный индекс, доступный стандартным поиском.
* **Pivot Transform** — группировка и агрегация (аналог GROUP BY в SQL).
* **Latest Transform** — последнее значение для каждого ключа (аналог DISTINCT ON).
* **Checkpoint** — единица работы continuous transform: проверка изменений в source с момента предыдущего checkpoint и обновление destination. Batch transform выполняет один checkpoint.
* **Retention Policy** — политика transform, удаляющая из destination-индекса документы старше `max_age` по заданному date-полю.
* **Downsampling** — свёртка backing-индексов TSDS в интервалы (gauge → `aggregate_metric_double` с min/max/sum/value_count; counter → last_value). Преемник rollup для метрик.

## Предварительные требования

* Rollup и Transform — встроенные функции Elasticsearch, включены по умолчанию; дополнительных настроек не требуют.
* **Node roles:** transform-задачи выполняются на узлах с ролью `transform` (при явном задании `node.roles` роль должна быть указана); rollup job — фоновая задача кластера.
* **Привилегии** (при включённом security):
  * Rollup: cluster `manage_rollup` (создание/изменение/удаление), `read_rollup` (чтение); чтение source-индексов.
  * Transform: cluster `manage_transform` (роль `transform_admin`), `read_transform`; source-индексы: `read`, `view_index_metadata`; destination: `read`, `index` (и `delete`, если настроена `retention_policy`).
  * Встроенные роли: `transform_admin`, `transform_user` (заменили `data_frame_transforms_admin`/`data_frame_transforms_user`).
* **Не правьте** внутренние индексы `.transform-internal*` напрямую — только через API.

## Как работает

### Rollup Workflow

```
Raw Data (logs-per-second)
        │
        ▼ (cron schedule — job активируется, продолжает с прошлого запуска)
   Rollup Job
        │
        ▼
Rollup Index (logs-per-hour) — только агрегаты
        │
        ▼ (удаление source — отдельный шаг, ILM)
   Source deleted
```

Job работает в фоне непрерывно, но обрабатывает данные только при срабатывании cron. Интервал `date_histogram` определяет гранулярность хранения: данные сворачиваются в бакеты этого размера, и запросы с более мелким интервалом невозможны.

### Transform Workflow

```
Source Index (raw)
        │
        ▼ (batch: один checkpoint | continuous: checkpoint каждые frequency)
   Transform
        │
        ▼
Destination Index (aggregated / entity-centric / latest)
```

### Checkpoints

Continuous transform на каждом checkpoint:
1. Проверяет изменения в source (по `frequency`). Если предыдущий checkpoint ещё идёт — проверка прерывается и повторится в следующий интервал.
2. Определяет, какие сущности (ключи group_by) или временные бакеты изменились с прошлого checkpoint.
3. Обновляет destination только по изменённым сущностям (change detection), а не полным пересчётом.

При сбое узла transform перезапускается с последней сохранённой позиции курсора. Рекомендуемое поле синхронизации — `event.ingested` (ECS): время попадания документа в индекс, а не произвольное date-поле.

## Rollup (legacy, deprecated 8.11)

### Создание Rollup Job

```bash
PUT _rollup/job/sensor
{
  "index_pattern": "sensor-*",
  "rollup_index": "sensor_rollup",
  "cron": "*/30 * * * * ?",
  "page_size": 1000,
  "groups": {
    "date_histogram": {
      "field": "timestamp",
      "fixed_interval": "1h",
      "delay": "7d"
    },
    "terms": {
      "fields": ["node"]
    }
  },
  "metrics": [
    { "field": "temperature", "metrics": ["min", "max", "sum"] },
    { "field": "voltage", "metrics": ["avg"] }
  ]
}
# → {"acknowledged": true}
```

Параметры конфигурации:

| Параметр | Описание |
|---|---|
| `index_pattern` | Шаблон source-индексов (обязателен) |
| `rollup_index` | Целевой индекс (обязателен) |
| `cron` | Расписание активации job (обязателен, синтаксис как у Watcher) |
| `page_size` | Размер страницы при постраничном обходе; default 1000 |
| `timeout` | Таймаут операций поиска/индексации; default 20s |
| `groups.date_histogram` | **Обязателен.** `field`, `fixed_interval` или `calendar_interval`, `delay` (обрабатывать только данные старше delay — для исторических job), `time_zone` (default UTC) |
| `groups.terms` | `fields` — массив keyword/числовых полей для terms-агрегаций |
| `groups.histogram` | `fields` + `interval` — один интервал на все поля группы |
| `metrics` | Массив `{field, metrics[]}`; только числовые поля; метрики: `min`, `max`, `sum`, `avg`, `value_count` |

Без `metrics` в каждом бакете сохраняется только `doc_count`. Порядок и комбинации групп в запросах не важны: любые сконфигурированные поля можно комбинировать в любых агрегациях при поиске.

**Cron vs interval:** cron управляет тем, как часто job активируется (например, раз в сутки в полночь — обработает последние 24 часа), а `fixed_interval` — гранулярностью хранения. Job при каждом запуске продолжает с того места, где остановился.

**Fixed vs calendar intervals:** рекомендуется `fixed_interval` (`60m` вместо `1h`, `24h` вместо `1d`) — фиксированные интервалы проще для запросов; calendar-единицы (`1h`, `1d`, `1w`, `1M`) привязаны к календарю и ограничивают кратность запросов.

### Управление Rollup Job

```bash
# Запуск (job создаётся в состоянии stopped)
POST _rollup/job/sensor/_start

# Остановка
POST _rollup/job/sensor/_stop

# Конфигурация + stats + status (только активные job: started и stopped)
GET _rollup/job/sensor
GET _rollup/job

# Удаление (job нельзя изменить — только удалить и создать новый)
DELETE _rollup/job/sensor
```

### Поиск в rollup-данных

```bash
GET sensor_rollup/_rollup_search
{
  "size": 0,
  "aggregations": {
    "hourly": {
      "date_histogram": { "field": "timestamp", "fixed_interval": "1d" },
      "aggs": {
        "nodes": {
          "terms": { "field": "node" },
          "aggs": {
            "max_temperature": { "max": { "field": "temperature" } },
            "avg_voltage": { "avg": { "field": "voltage" } }
          }
        }
      }
    }
  }
}
```

`_rollup_search` принимает стандартный Query DSL и переписывает его под структуру rollup-документов; ответ переписывается обратно. Хиты не возвращаются — только агрегации (`size` должен быть 0 или отсутствовать).

**Объединение live и rolled данных** — live-индексы указываются вместе с rollup-индексом; при перекрытии бакетов приоритет у live-данных:

```bash
GET sensor-1,sensor_rollup/_rollup_search
{
  "size": 0,
  "aggregations": {
    "max_temperature": { "max": { "field": "temperature" } }
  }
}
```

**Ограничения `_rollup_search`:**
* Только один rollup-индекс на запрос (шаблон, матчующий >1 rollup-индекс, даёт исключение); `_all` и пустой index запрещены.
* Интервал агрегации должен быть >= сконфигурированного и **целым кратным** ему (job с `3d` → запросы `3d`, `6d`, но не `2d`).
* Можно агрегировать только то, что сохранено в job (поле без `avg`-метрики → ошибка 400).
* Разрешены запросы: `term`, `terms`, `range`, `match_all` и составные (`bool`, `boosting`, `constant_score`) — только по полям, сохранённым как groups.
* Недоступны: `highlighter`, `suggestors`, `post_filter`, `profile`, `explain`.

### Capabilities API

Перед созданием job проверьте, какие поля и агрегации доступны:

```bash
# Что можно свернуть в index-pattern (поля, типы агрегаций)
GET _rollup/data/sensor-*/_rollup_caps

# Что сохранено в конкретном rollup-индексе (какие job-ы и их возможности)
GET sensor_rollup/_rollup/data/
```

### Структура rollup-индекса

```
sensor_rollup
├── timestamp (date_histogram, 1h granularity, UTC)
├── node (terms)
├── temperature.min / .max / .sum (double)
├── voltage.avg (double)
└── doc_count (long)
```

**Важно:** rollup-индекс хранит только агрегаты. Исходные документы невозможно восстановить. Среднее не пересчитывается: нельзя усреднять шесть 10-минутных средних для получения часового среднего — для переагрегации по более крупным интервалам храните `sum` + `value_count`.

### Ограничения Rollup

* `date_histogram` обязателен — rollup только для time-based данных.
* Groups: только `date_histogram`, `terms`, `histogram`; metrics — только числовые поля.
* High-cardinality fields в `terms` существенно снижают сжатие — включайте осознанно.
* Job нельзя изменить — удаление и пересоздание.
* Heterogeneous mappings: с 6.4.0 лучшая практика — один job на все типы документов в шаблоне.
* Нет nested objects; нет поддержки произвольных агрегаций при поиске.

## Transform

### Pivot Transform

```bash
PUT _transform/service-daily-summary
{
  "source": {
    "index": "logs-*"
  },
  "dest": {
    "index": "service-summary-daily"
  },
  "frequency": "10m",
  "sync": {
    "time": {
      "field": "@timestamp",
      "delay": "60s"
    }
  },
  "pivot": {
    "group_by": {
      "service": { "terms": { "field": "service.name" } },
      "@timestamp": {
        "date_histogram": { "field": "@timestamp", "calendar_interval": "1d" }
      }
    },
    "aggregations": {
      "avg_response_time": { "avg": { "field": "response_time" } },
      "total_requests": { "value_count": { "field": "_id" } },
      "max_bytes": { "max": { "field": "bytes" } }
    }
  },
  "description": "Daily summary by service"
}
# → {"acknowledged": true}
```

* `source`: `index` (строка или массив), `query` (фильтр), `runtime_mappings`.
* `dest`: `index`, `pipeline` (ingest pipeline, применяемый к трансформированным документам).
* `pivot.group_by`: `terms`, `date_histogram`, `histogram`, `geotile_grid`.
* `pivot.aggregations`: метрические агрегации (`avg`, `min`, `max`, `sum`, `value_count`, `cardinality`, `stats`, `extended_stats`, `weighted_avg`), pipeline-агрегации (`bucket_script`) и `filter`.
* Transform создаётся в остановленном состоянии — запускайте через `_start`.

### Latest Transform

```bash
PUT _transform/latest-status-by-host
{
  "source": { "index": "host-metrics-*" },
  "dest": { "index": "latest-host-status" },
  "frequency": "1m",
  "sync": {
    "time": { "field": "@timestamp", "delay": "30s" }
  },
  "latest": {
    "unique_key": ["host.name"],
    "sort": "@timestamp"
  },
  "description": "Latest metrics per host"
}
```

* `unique_key` (обязателен): массив из одного или более полей группировки.
* `sort` (обязателен): date-поле, определяющее «последний» документ.
* Поля source с именами, начинающимися с `_`, в latest transform не попадают в destination (считаются внутренними).

### Retention Policy

```bash
PUT _transform/last-log-from-clientip
{
  "source": { "index": "kibana_sample_data_logs" },
  "latest": { "unique_key": ["clientip"], "sort": "timestamp" },
  "frequency": "1m",
  "dest": { "index": "last-log-from-clientip" },
  "sync": { "time": { "field": "timestamp", "delay": "60s" } },
  "retention_policy": {
    "time": {
      "field": "timestamp",
      "max_age": "30d"
    }
  },
  "settings": { "max_page_search_size": 500 }
}
```

`retention_policy.time.field` — date-поле для расчёта возраста документа; `max_age` — документы старше удаляются из destination. Требует привилегии `delete` на destination-индекс.

### Настройки (settings)

| Параметр | Описание |
|---|---|
| `max_page_search_size` | Бакетов за операцию search/index; default 500 (pivot) / 5000 (latest), min 10, max 65536; не должен превышать `index.max_terms_count` (default 65536) |
| `dates_as_epoch_millis` | `true` — даты как epoch millis, `false` (default) — ISO-строки |
| `use_point_in_time` | `true` (default) — PIT-поиск для консистентности; `false` — обходной путь при PIT-overload (см. Граничные случаи) |
| `deduce_mappings` | Авто-вывод маппинга destination |

### Управление Transform

```bash
# Запуск / остановка
POST _transform/service-daily-summary/_start
POST _transform/service-daily-summary/_stop

# Статистика (state, documents_processed, checkpoint_duration и т.д.)
GET _transform/service-daily-summary/_stats
GET _transform/_stats

# CAT-представление (indexing / started / stopped / failed)
GET _cat/transforms

# Preview: до 100 документов + сгенерированные mappings/settings destination
# (объект generated_dest_index в ответе)
POST _transform/service-daily-summary/_preview

# Обновление: description, dest, frequency, _meta, retention_policy, settings,
# source, sync. Всё кроме description вступает в силу со следующего checkpoint.
# Нельзя превратить batch в continuous и наоборот — только клонирование.
POST _transform/service-daily-summary/_update
{ "frequency": "15m", "sync": { "time": { "field": "@timestamp", "delay": "120s" } } }

# Немедленная обработка новых данных без ожидания frequency
# (query-параметр defer=true откладывает запуск на sync delay)
POST _transform/service-daily-summary/_schedule_now

# Сброс: удаляет destination, если он создан transform, и обнуляет checkpoint.
# Требует остановки (или force=true).
POST _transform/service-daily-summary/_reset

# Обновление legacy-формата конфигурации (query-параметр dry_run=true — только проверка)
POST _transform/_upgrade

# Удаление (query-параметры: delete_dest_index=true, force=true)
DELETE _transform/service-daily-summary
```

**Обновление vs пересоздание:** rollup job изменить нельзя (только delete + create); transform — можно через `_update`, но только для непрерывных свойств, и batch↔continuous не конвертируются.

### Ограничения Transform

* **Data streams не поддерживаются** как destination (append-only, transform пишет обновления).
* **ILM не рекомендуется** как управление destination: transform обновляет документы в текущем индексе и не может удалять документы из индексов, уже перекрученных ILM → дубликаты при rollover. Для time-based destination используйте процессор `date_index_name` с `group_by` на `date_histogram`.
* Deduced mappings для полей из `scripted_metrics`/`bucket_scripts` используют dynamic mappings — могут не совпадать с данными; проверьте через `_preview` (`generated_dest_index`) или создайте destination заранее через create index API (index template не перезаписывает deduced mappings).
* Скрипты: маппинг для scripted-полей не выводится (создавайте вручную); scripted-поля увеличивают runtime; warning, если все `group_by` — со скриптами.
* Time-поле синхронизации должно быть **индексированным**, не runtime — иначе transform сильно замедляется.
* `frequency`: min 1s, max 1h, default 1m; повторы при сбоях происходят с интервалом `frequency`.
* `sync.time.delay` должен быть >= `refresh_interval` source-индекса (default 60s).
* Batch transform: composite aggregation без search context — изменения source во время прогона могут не попасть в результат.
* Continuous transform: сущность обновляется, только если её time-поле изменилось и попало в окно проверки; при удалении source-индексов сущности из удалённых индексов остаются в destination (пересоздайте transform или включите max-ingest-timestamp в агрегацию).
* Удаление transform **не удаляет** destination-индекс и Kibana data view.
* `date_nanos`: агрегации — с миллисекундной точностью.
* CCS поддерживается, если remote-кластер поддерживает нужные поиск/агрегации.
* Kibana: transform видны во всех Spaces; страница управления показывает до 1000 transform.

## Rollup vs Transform vs Downsampling (TSDS)

| Критерий | Rollup (deprecated 8.11) | Transform | Downsampling (TSDS) |
|---|---|---|---|
| Механизм | Фоновый job, активация по cron | Pivot/latest; batch или continuous (change detection) | Автоматически: ILM action `downsample` или API `POST /<source>/_downsample/<target>` |
| Агрегации | min, max, sum, avg, value_count (числовые) | Любые метрические + pipeline (`bucket_script`) | gauge: min/max/sum/value_count → `aggregate_metric_double`; counter: last_value (метод `last_value` — preview с 9.3) |
| Группировка | date_histogram (обязателен), terms, histogram | terms, date_histogram, histogram, geotile_grid | По `_tsid` (time series dimensions) |
| Исходные данные | Сохраняются (удаление — отдельный шаг, ILM) | Сохраняются | Source-индекс удаляется при ILM-downsample (backing index) |
| Destination | Только агрегаты; поиск через `_rollup_search` | Обычный индекс; стандартный поиск; обновляемый | `downsample-<original>-<uuid>`; source должен быть read-only (`index.blocks.write: true`) |
| Live + исторические в одном запросе | Да (`_rollup_search`, приоритет live) | Нет | Нет |
| Настройка retention | Внешняя (ILM на source/rollup) | Встроенная `retention_policy` | ILM delete phase |
| Статус | Deprecated 8.11, будет удалён | GA | GA, рекомендуемый подход для метрик |

## Use Cases

### Rollup: долгосрочная аналитика (legacy)

```
Raw logs: 100GB/day × 30 days = 3TB
Rollup:   1GB/day × 365 days = 365GB

Экономия порядка ~10x на хранении при потере гранулярности
```

Подходит для: compliance (агрегаты 1+ год), capacity planning (тренды по дням/неделям), SLA-отчёты (uptime по месяцам). **Для новых развёртываний — downsampling TSDS.**

### Transform: entity-centric отчёты и latest views

* Дашборд текущего статуса всех серверов (latest transform по `host.name`).
* Отчёты по сервисам/клиентам (pivot: суммарные метрики за период по каждой сущности).
* Дедупликация: последнее значение на ключ (unique_key + sort).
* «Лучшие клиенты»-аналитика: pivot с `sum`/`avg`/`cardinality` по `customer_id`.

### Downsampling TSDS: метрики временных рядов

* Мониторинг (CPU, memory, latency) с автоматической свёрткой через ILM (`downsample` action в hot/warm/cold; в hot требуется `rollover`).
* Ручная свёртка: `POST /metrics-000001/_downsample/metrics-hourly` с `fixed_interval`, `force_merge_index` (default true), `sampling_method` (`aggregate` default | `last_value`).
* `aggregate_metric_double` участвует в max/min/sum/value_count/avg без потери точности.

## Мониторинг и алертинг

### Rollup Job

```bash
GET _rollup/job/sensor
```

Ответ содержит `config`, `status.job_state` (`started`, `stopped`, `indexing`, `failed`) и `stats`:

* `pages_processed`, `documents_processed`, `rollups_indexed`
* `trigger_count` — сколько раз cron активировал job
* `search_failures`, `index_failures` — ошибки поиска/индексации
* `search_total`, `search_time_in_ms`, `index_total`, `index_time_in_ms`

### Transform Stats

```bash
GET _transform/_stats
```

* `state`: `indexing` (активно пишет), `started` (работает, не пишет), `stopped`, `failed`
* `documents_indexed`, `documents_processed`
* `checkpoint_duration`, `exponential_avg_checkpoint_duration_ms` — длительность checkpoint (экспоненциальное среднее)
* `search_total`, `index_total`, `search_time_in_ms`, `index_time_in_ms`
* `checkpoints` — массив с номерами и временем checkpoint-ов

### Алертинг

В Kibana Alerting есть rule type **Transform rules** (Beta — проверка здоровья continuous transform) — см. [Alerting](./elasticsearch_alerting.md). Для rollup/transform job-ов алертуйте на `state: failed`, рост `search_failures`/`index_failures` и аномальный рост `checkpoint_duration`.

## Best Practices

1. **Для новых развёртываний — downsampling TSDS**, не rollup (deprecated 8.11).
2. **Rollup: проектируйте groups под будущие запросы** — порядок и комбинации полей не важны, важно только, какие поля и типы агрегаций понадобятся.
3. **Rollup: `fixed_interval` вместо `calendar_interval`** — предсказуемая кратность запросов.
4. **Rollup: для переагрегации храните `sum` + `value_count`** — средние не складываются.
5. **Rollup: cron в off-peak**, `page_size` подбирайте под нагрузку; job выполняет поиск по сырым данным — учитывайте нагрузку на кластер.
6. **Transform: `sync.time.field` = `event.ingested`** (ECS), `delay` >= `refresh_interval` source.
7. **Transform: `frequency` «little and often»** (default 1m) — каждый checkpoint несёт overhead; повторы тоже идут с этим интервалом.
8. **Transform: `retention_policy` вместо ILM** на destination-индексе; для time-based destination — процессор `date_index_name`.
9. **Тестируйте конфигурацию перед запуском**: transform — через `_preview` (показывает `generated_dest_index`), rollup — через capabilities API.
10. **Мониторьте lag**: если transform не успевает, растёт `checkpoint_duration` и отставание; rollup — `trigger_count` vs ожидаемому расписанию.
11. **Бэкапьте конфиги** `_rollup`/`_transform` в Git; не правьте `.transform-internal*` напрямую.

## Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| Rollup job `failed` | Ошибка поиска/индексации (`search_failures`/`index_failures` в stats) | Проверьте поле/маппинг в конфиге; перезапустите `_start` после исправления |
| Rollup search 400: field/aggregation not possible | Поле или метрика не сконфигурированы в job | Добавьте в job (пересоздание) или проверьте через `_rollup_caps` |
| Rollup search 400: interval | Интервал запроса мельче сконфигурированного или не кратен ему | Запрос с интервалом >= и кратным `fixed_interval` |
| Rollup search: нет данных | `size` != 0, или запрос по полю не из groups | `size: 0`; запросы только по group-полям |
| Transform `failed` | Circuit breaker (размер страницы снижен до минимума), нехватка прав, конфликт маппинга destination | `_cat/transforms` и логи; устраните причину и `_start`; для удаления failed transform — `_stop?force=true` затем `DELETE` |
| Transform не видит новые документы | `sync.time.delay` меньше задержки доступности документа в поиске | Увеличьте `delay` (>= `refresh_interval` source) |
| В destination остались сущности из удалённых индексов | Continuous transform не отслеживает удаление source-индексов | Пересоздайте transform или включите max-ingest-timestamp в агрегацию |
| Дубликаты в destination | ILM rollover на destination-индексе | Уберите ILM с destination; используйте `retention_policy` или `date_index_name` |
| «Found task for transform [...], but no configuration for it» | SLO-transform: вводящее в заблуждение сообщение | **Не удаляйте** transform — сбросьте SLO (Kibana Observability > SLOs > Reset) |
| PIT-overload при большом числе transform | Асинхронное закрытие PIT накапливается | `settings: { "use_point_in_time": false }` как обходной путь; обновление до 8.18.8 / 8.19.5 / 9.0.8 / 9.1.5 / 9.2.0+ |
| Preview показывает неожиданные типы полей | Deduced mappings для scripted-полей — dynamic | Создайте destination с явным маппингом через create index API до запуска |

## Граничные случаи

* **Rollup job создаётся в `stopped`** — не забудьте `_start`; то же для transform.
* **Rollup: среднее не переагрегируется** — шесть 10-минутных avg не дают часовой avg; используйте sum/value_count.
* **Rollup: один job на шаблон** — heterogeneous mappings обрабатываются одним job с 6.4.0.
* **Rollup: `delay` в date_histogram** — job обрабатывает только данные старше delay (режим «только исторические»).
* **Transform: первый checkpoint ресурсоёмок** при большом объёме истории — оптимизируйте поиск/агрегации и фильтруйте `source.query`.
* **Transform: underscore-поля** (`_*`) опускаются в latest transform.
* **Transform: `max_page_search_size` > `index.max_terms_count`** (65536) → transform упадёт; при circuit breaker размер страницы снижается до минимума, затем — `failed`.
* **Transform: Kibana показывает до 1000 transform**; API — все.
* **Rollup и transform не взаимозаменяемы с downsampling**: rollup/transform работают с обычными индексами, downsampling — только с TSDS (маппинг `time_series_dimension`/`time_series_metric`).

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура и роли узлов (включая `transform`).
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — downsampling TSDS, ILM `downsample` action, интеграция с Rollup/Transform.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — TSDS-маппинг для downsampling.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — расчёт ресурсов для Rollup.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — мониторинг job статуса.
* **[Alerting](./elasticsearch_alerting.md)** — алертинг на ошибки jobs (Transform rules).
