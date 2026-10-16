# Elasticsearch: Жизненный цикл индексов (ILM) и политики хранения

**Актуально для:** Elasticsearch 8.x / 9.x

> Заметка посвящена автоматизации хранения временных рядов в Elasticsearch: политикам ILM, упрощенному Data Stream Lifecycle (DLM), downsampling'у метрик и резервному копированию по расписанию (SLM). Базовые понятия кластера (шарды, роли узлов, watermarks) описаны в [обзоре Elasticsearch](./elasticsearch_overview.md).

## Определения

* **ILM (Index Lifecycle Management)** — подсистема Elasticsearch для полной автоматизации управления индексами через набор фаз и действий.
* **DLM (Data Stream Lifecycle)** — упрощенный механизм управления жизненным циклом, ориентированный специально на потоки данных (Data Streams). Позволяет настраивать хранение (`retention`), downsampling (агрегацию метрик), tail merging и перенос в `frozen` (через `frozen_after`, 9.5+) без создания сложных политик ILM. Введён в 8.11 как tech preview, достиг GA в 9.5.
* **Ротация (Rollover)** — процесс закрытия текущего индекса для записи и создания нового при достижении определенных условий (размер, возраст, количество документов).
* **Data Tier (Уровень данных)** — логическая роль узла в хранении данных (`hot`, `warm`, `cold`, `frozen`), определяющая тип оборудования и стоимость хранения.
* **Downsampling** — технология уменьшения объема данных временных рядов (TSDS) путем агрегации старых метрик в более крупные временные интервалы (бакеты), сохраняя статистическую значимость (`min`, `max`, `sum`, `value_count`, `avg`).
* **Searchable Snapshot (Поисковый снимок)** — технология, позволяющая выполнять поисковые запросы напрямую по данным, хранящимся в снапшот-репозитории (файловая система или S3-совместимое хранилище). В cold tier индекс монтируется полностью (вся копия данных на локальном диске), в frozen — частично (на диске только кэш часто запрашиваемых данных).
* **Data Stream (Поток данных)** — именованная сущность только для записи, скрывающая за собой набор backing-индексов (`.ds-<имя>-<дата>-<номер>`). Запись всегда идет в последний backing-индекс; ILM/DLM управляют ими автоматически. Требует шаблона с `"data_stream": {}` и поля `@timestamp`.
* **TSDS (Time Series Data Stream)** — специализированный поток данных для метрик: поля размечаются как `time_series_dimension` (измерения) и `time_series_metric` (`gauge`, `counter`). Только TSDS поддерживают downsampling.
* **min_age** — порог времени, определяющий готовность индекса к переходу в следующую фазу. Отсчитывается от даты создания/ротации backing-индекса, а **не** от момента входа в предыдущую фазу.
* **SLM (Snapshot Lifecycle Management)** — подсистема автоматизации снапшотов по расписанию (аналог ILM для резервного копирования): политика задает cron-расписание, репозиторий и retention самих снимков.
* **Tail merging** — слияние только «хвоста» мелких сегментов, применяемое DLM вместо полного force merge: дешевле по ресурсам и фокусируется на самых свежих данных.

## Основные концепции

### Фазы жизненного цикла

Жизненный цикл делится на пять фаз. Переход между фазами определяется параметром `min_age` (время с момента ротации).

| Фаза | Характеристики | Ключевые действия |
| :--- | :--- | :--- |
| **Hot** | Активная запись и поиск. | **Rollover**: создание нового индекса. **Downsample**: агрегация метрик. |
| **Warm** | Запись закрыта, поиск частый. | **Shrink**: уменьшение числа шардов. **Force Merge**: оптимизация сегментов. **Migrate**: перенос на `warm` узлы. |
| **Cold** | Поиск редкий, данные статичны. | **Searchable Snapshot**: (Fully Mounted) — снапшот становится основной копией данных. |
| **Frozen** | Архивный поиск. | **Searchable Snapshot**: (Partially Mounted) — данные в репозитории, на диске только кэш. |
| **Delete** | Данные не нужны. | **Delete**: окончательное удаление. |

Важные детали механики:

* **Лицензирование фаз**: Hot/Warm/Delete доступны в бесплатном уровне. Фазы Cold и Frozen используют Searchable Snapshots и требуют подписки Enterprise.
* **Семантика `min_age`**: время отсчитывается от даты создания (для Data Streams — от ротации) backing-индекса, а не от входа в фазу. Поэтому `warm.min_age: 0ms` в примере ниже означает "сразу после ротации", а `delete.min_age: 30d` — 30 дней с момента создания индекса, независимо от того, когда он попал в warm. `min_age` в hot-фазе игнорируется — фаза начинается сразу (указывайте `0ms` или опускайте).
* **Интервал проверки**: ILM/DLM не выполняют действия мгновенно. ILM проверяет политику раз в 10 минут (`indices.lifecycle.poll_interval`), DLM — раз в 5 минут (`data_streams.lifecycle.poll_interval`). Для тестов уменьшите: `PUT /_cluster/settings {"transient": {"indices.lifecycle.poll_interval": "1m"}}`.
* **Порядок действий фиксирован**: ILM выполняет действия внутри фазы в фиксированном порядке, независимо от порядка в JSON. Для hot-фазы: `set_priority` → `unfollow` → `rollover` → `readonly` → `downsample` → `shrink` → `forcemerge` → `searchable_snapshot` → `allocate` → `migrate`.
* **Порционное выполнение**: ILM запускается периодически и выполняет шаги до точки, где дальнейшее выполнение небезопасно (например, идёт релокация шардов); при следующем запуске выполнение продолжается с того же места. Переход между фазами может занять несколько циклов опроса.

### Действия ILM

| Действие | Фазы | Ключевые опции | Назначение |
| :--- | :--- | :--- | :--- |
| `set_priority` | все | `priority` | приоритет восстановления индекса после перезапуска узла |
| `unfollow` | все | — | конвертирует CCR-follower в обычный индекс; ILM выполняет автоматически перед `rollover`, `shrink` и `searchable_snapshot` |
| `rollover` | hot | `max_size`, `max_primary_shard_size`, `max_age`, `max_docs`, `max_primary_docs` | ротация при выполнении любого из условий |
| `readonly` | hot, warm, cold | — | запрет записи в индекс |
| `downsample` | hot, warm, cold | `fixed_interval` (обязательная), `force_merge_index` (default `true` в 9.3, `false` в 9.4+; в 8.x downsampling force-merged implicitly — опции не существовала), `sampling_method` (`aggregate`/`last_value`, default `aggregate`, GA с 9.3) | агрегация TSDS-метрик |
| `shrink` | hot, warm | `number_of_shards` **или** `max_primary_shard_size` (взаимоисключающи) | уменьшение числа первичных шардов |
| `forcemerge` | hot, warm | `max_num_segments` (обязательная), `index_codec` (`best_compression` — ZSTD) | слияние сегментов |
| `searchable_snapshot` | hot, cold, frozen | `snapshot_repository` (обязательная), `replicate_for`, `force_merge_index` (default `true`), `total_shards_per_node` | снапшот + монтирование как searchable snapshot |
| `allocate` | warm, cold | `number_of_replicas`, `total_shards_per_node`, `include`, `exclude`, `require` | размещение шардов и число реплик |
| `migrate` | warm, cold | `enabled` (default `true`) | перенос на tier текущей фазы (`index.routing.allocation.include._tier_preference`); ILM внедряет автоматически |
| `wait_for_snapshot` | delete | `policy` (обязательная — имя SLM-политики) | дождаться успешного снапшота SLM перед удалением |
| `delete` | delete | `delete_searchable_snapshot` | удаление индекса (и смонтированного снапшота) |

Дополнительные ограничения:

* Действия `downsample`, `shrink`, `forcemerge` и `readonly` в hot-фазе требуют наличия действия `rollover` — иначе ILM отклонит политику.
* `allocate` не допускается в hot-фазе (начальное размещение задаётся вручную или через шаблоны); `migrate` не допускается в hot и frozen.
* `allocate` требует указать хотя бы одну опцию (`number_of_replicas` или `include`/`exclude`/`require`) — пустое действие невалидно.
* `searchable_snapshot` нельзя выполнить на write-индексе data stream (сначала ротируйте); не размещайте действие одновременно в hot и cold — индексы перестанут мигрировать в cold; если действие в hot, последующие фазы не могут содержать `shrink`/`forcemerge`.

### Рекомендации по размеру шарда

Для стабильности кластера и производительности ILM следует придерживаться правила: **целевой размер основного шарда — 50 ГБ**.
*   Используйте `max_primary_shard_size: "50gb"` в качестве основного триггера ротации.
*   ILM неявно ротирует индекс (или data stream), когда один из шардов достигает 200M документов — даже если условия rollover не заданы. Шард обычно достигает 50 ГБ раньше 200M документов, но для компактных данных это не так.
*   Избегайте "раздувания шардов" (shard bloat) — ситуации с тысячами мелких индексов по несколько мегабайт, что перегружает Master-узел.

### Data Stream Lifecycle (DLM) vs ILM

Для стандартных логов рекомендуется использовать **DLM** из-за простоты:
*   **ILM**: Максимальная гибкость (shrink, force merge, сложные условия). Работает с обычными индексами и data streams. Требует политики и шаблона.
*   **DLM**: Настраивается одной командой API. Автоматически управляет ротацией (условия по умолчанию — кластерная настройка `cluster.lifecycle.default.rollover`), tail merging'ом (слияние только хвоста мелких сегментов вместо полного force merge), downsampling'ом, переносом в frozen (`frozen_after`, 9.5+) и удалением. Идеально для большинства observability-задач.
*   **DLM работает только с data streams** — для обычных индексов используйте ILM.
*   **DLM в шаблоне**: Конфигурация lifecycle может задаваться компонент-шаблоном (секция `template.lifecycle` с `data_retention`, массивом `downsampling` и `frozen_after`) — тогда новые потоки наследуют её автоматически. Рабочий пример — сценарий 5 ниже.
*   **Совместимость с ILM**: Политика DLM не смешивается с ILM на одном потоке. Если backing-индекс имеет ILM-политику, а поток также управляется DLM, приоритет ILM задаётся настройкой `index.lifecycle.prefer_ilm` (default `true`); установите `false`, чтобы DLM управлял индексом. Миграция выполняется через `PUT /_data_stream/<имя>/_lifecycle` либо удалением ILM-настройки из шаблона.

## Практические сценарии

### Предварительные требования для всех сценариев

(аналогичны [обзору](./elasticsearch_overview.md)):

```bash
export ES="https://localhost:9200"
export PASS="<пароль пользователя elastic>"
# Проверка доступности:
curl -u elastic:$PASS -k "$ES"   # → {"name" : "es-node-1", ..., "tagline" : "You Know, for Search"}
```

Для сценариев с cold/frozen tier и SLM дополнительно: зарегистрированный снапшот-репозиторий (`path.repo` на всех master/data узлах, механика — в [обзоре](./elasticsearch_overview.md)) и узлы с ролью `data_frozen` (для frozen tier).

### 1. Настройка политики ILM для логов (Hot-Warm-Delete)

Сценарий: ротация при 50 ГБ, оптимизация в Warm (1 шард, 1 сегмент), удаление через 30 дней.

```bash
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_ilm/policy/logs-policy" -H 'Content-Type: application/json' -d'
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": { "max_primary_shard_size": "50gb", "max_age": "30d" }
        }
      },
      "warm": {
        "min_age": "0ms",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 }
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": { "delete": {} }
      }
    }
  }
}'
# → {"acknowledged":true}
```

Проверка применения политики и принудительная ротация для теста:

```bash
# Статус политики на индексе
curl -u elastic:$PASS -k "$ES/my-index/_ilm/explain?pretty"
# → {"indices":{"my-index":{"index":"my-index","managed":true,"policy":"logs-policy",
#     "lifecycle_date":"2026-08-23T10:00:00Z","phase":"hot","phase_time_ms":...,
#     "action":"rollover","action_time_ms":...,"step":"check-rollover-ready",...}}}

# Ручная ротация (не дожидаясь триггеров 50gb/30d).
# Цель ротации — data stream или write-алиас, но не backing-индекс.
curl -u elastic:$PASS -k -X POST "$ES/logs-app-default/_rollover"
# → {"acknowledged":true,"shards_acknowledged":true,"new_index":"logs-app-000002"}
```

### 2. Настройка Downsampling для метрик

Позволяет хранить детальные метрики 7 дней, а затем сжимать их, экономя до 90% места.

```json
"phases": {
  "warm": {
    "min_age": "7d",
    "actions": {
      "downsample": {
        "fixed_interval": "1h"
      }
    }
  }
}
```
*Данные после Downsampling полностью query-compatible с оригинальными индексами.*

Требования и механика действия:

* **Работает только для TSDS**: индексы должны быть созданы как time series data stream (маппинг с `time_series_dimension` и `time_series_metric`). Для обычных индексов используйте [transform](./elasticsearch_rollup_transform.md) (rollup deprecated с 8.11 — см. [Rollup и Transform](./elasticsearch_rollup_transform.md)).
* **Исходный индекс заменяется**: downsampled-индекс (`downsample-<имя>-<uuid>`) наследует tier, число шардов и реплик исходного; оригинал удаляется после успеха. Для backing-индекса data stream downsampled-индекс становится backing-индексом того же потока. Внутри одного потока на период времени существует ровно один индекс.
* **Что сохраняется**: для каждого метрика-поля (`gauge`) значения агрегируются в `aggregate_metric_double` (`min`, `max`, `sum`, `value_count`, `avg`); dimension-поля копируются без изменений. Запросы `_search` и агрегации работают по объединенному потоку без изменения клиента.
* **Повторный downsampling** уже downsampled-индекса поддерживается; интервал должен быть кратен интервалу исходного индекса.
* **Ручной API** `POST /<index>/_downsample/<target>` требует, чтобы исходный индекс был в read-only; ILM выполняет это автоматически.
* Проверка результата:
  ```bash
  curl -u elastic:$PASS -k "$ES/_cat/indices/.ds-metrics-*?v&h=index,status,docs.count,store.size&s=index"
  # → .ds-metrics-app-2026.08.16-000001 downsampled ... 86400 4.2mb   (было ~40mb)
  ```

### 3. Привязка политики к Data Stream

Используйте компонентные шаблоны для модульности:

```bash
# Создание настроек
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_component_template/logs-lifecycle" -H 'Content-Type: application/json' -d'
{
  "template": {
    "settings": { "index.lifecycle.name": "logs-policy" }
  }
}'

# Создание итогового шаблона
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_index_template/app-logs" -H 'Content-Type: application/json' -d'
{
  "index_patterns": ["logs-app-*"],
  "data_stream": {},
  "composed_of": ["logs-lifecycle", "logs-mappings"],
  "priority": 500
}'
# → {"acknowledged":true}
```

Сквозная проверка: первый документ создает поток, политика подхватывается автоматически (компонент-шаблон `logs-mappings` с маппингом предполагается созданным — схемы полей описаны в [заметке о маппинге](./elasticsearch_mapping_and_indexing.md)):

```bash
curl -u elastic:$PASS -k -X POST "$ES/logs-app-default/_doc?refresh=true" \
-H 'Content-Type: application/json' -d'{ "@timestamp": "2026-08-23T12:00:00Z", "message": "test" }'
# → {"_index":".ds-logs-app-default-2026.08.23-000001","result":"created",...}

curl -u elastic:$PASS -k "$ES/_data_stream/logs-app-default?pretty"
# → {"data_streams":[{"name":"logs-app-default","timestamp_field":{"name":"@timestamp"},
#     "indices":[{"index_name":".ds-logs-app-default-2026.08.23-000001",...}],
#     "lifecycle":{"enabled":true,"policy":"logs-policy"},...}]}
```

### 4. Диагностика и решение проблем

Если индексы не удаляются или не перемещаются:

```bash
# Выяснить причину остановки ILM для конкретного индекса
curl -u elastic:$PASS -k -X GET "https://localhost:9200/my-index/_ilm/explain?pretty"
# → {"indices":{"my-index":{"managed":true,"phase":"warm","action":"shrink",
#     "step":"ERROR","failed_step":"shrink","failure_reason":...,
#     "step_info":{"type":"illegal_argument_exception","reason":...}}}}
```

Управление политиками и инструменты восстановления:

```bash
# Список политик / одна политика
curl -u elastic:$PASS -k "$ES/_ilm/policy"                    # → {"logs-policy":{...}}
curl -u elastic:$PASS -k "$ES/_ilm/policy/logs-policy?pretty"

# Удаление политики (только если не назначена индексам)
curl -u elastic:$PASS -k -X DELETE "$ES/_ilm/policy/logs-policy"
# → {"acknowledged":true}

# Повторить упавший шаг после устранения причины (например, освободили диск)
curl -u elastic:$PASS -k -X POST "$ES/my-index/_ilm/retry"
# → {"acknowledged":true}

# Экспертный API: принудительно переместить индекс в заданный шаг (для тестов)
curl -u elastic:$PASS -k -X POST "$ES/my-index/_ilm/move" \
-H 'Content-Type: application/json' -d'
{
  "current_step": { "phase": "warm", "action": "complete", "name": "complete" },
  "next_step":    { "phase": "delete", "action": "complete", "name": "complete" }
}'
# → {"acknowledged":true}

# Статус/остановка/запуск ILM на кластере
curl -u elastic:$PASS -k "$ES/_ilm/status"          # → {"state":"RUNNING",...}
curl -u elastic:$PASS -k -X POST "$ES/_ilm/stop"    # → {"acknowledged":true}
curl -u elastic:$PASS -k -X POST "$ES/_ilm/start"   # → {"acknowledged":true}
```

**Типичные ошибки:**
*   **"index.lifecycle.rollover_alias does not point to index"**: Вы используете старый подход с алиасами. Рекомендуется перейти на **Data Streams**.
*   **Insufficient disk space**: ILM не выполнит `shrink` или `migrate`, если на узлах превышен порог `high watermark` (обычно 90%). Пороги и диагностика — в [руководстве по кластеру](../Tutorials/cluster_setup.md).
*   **ILM Status is STOPPED**: Проверьте статус через `GET /_ilm/status`. Запустите при необходимости: `POST /_ilm/start`.
*   **Шаг завис в `WAITING` без видимой ошибки**: Проверьте соответствие условиям триггера (`max_age`/`max_primary_shard_size`) через `_ilm/explain`; помните про интервал опроса 10 минут.
*   **Молчаливые сбои ротации**: Горячий индекс растёт неограниченно — проверьте `_ilm/explain` на `step: ERROR`. Для превентивного контроля настройте алертинг на метрику ошибок ILM или используйте механизм `error_notification` (реализован в ISM OpenSearch, см. [сравнение](../OpenSearch/opensearch_ism_lifecycle.md)).
*   **DLM frozen transition не запускается**: Проверьте, что `repositories.default_repository` задан (`GET _cluster/settings`), `dlm.frozen_transitions.enabled: true` и лицензия Enterprise. Ошибки видны в `GET /<index>/_lifecycle/explain` (поле `error`).
*   **DLM downsampling stuck**: `GET /<index>/_lifecycle/explain` покажет ошибку; проверьте, что индекс является TSDS и `downsampling.after` меньше `data_retention`. Лимит параллельных downsampling — `data_streams.lifecycle.downsampling.max_indices_in_progress` (default 10); избыточные индексы откладываются с предупреждением.

### 5. Быстрый старт: retention для Data Stream через DLM

Сценарий: логи приложения хранятся 30 дней, без создания политик и шаблонов. Рекомендуемый подход для типовых observability-задач.

```bash
# 1. Установить retention на существующий поток одной командой
curl -u elastic:$PASS -k -X PUT "$ES/_data_stream/logs-app-default/_lifecycle" \
-H 'Content-Type: application/json' -d'
{ "data_retention": "30d" }'
# → {"acknowledged":true}

# 2. Проверить конфигурацию
curl -u elastic:$PASS -k "$ES/_data_stream/logs-app-default?filter_path=*.lifecycle&pretty"
# → {"data_streams":[{"name":"logs-app-default",
#     "lifecycle":{"enabled":true,"data_retention":"30d",
#     "effective_retention":"30d","retention_determined_by":"data_stream_configuration"}}]}
```

Пояснения: `data_retention` отсчитывается от ротации backing-индекса (а точнее — от `generation_time`, который равен времени с ротации, или `index.lifecycle.origination_date`, если задан; см. [диагностику](#4-диагностика-и-решение-проблем)); по истечении срока индекс удаляется автоматически, реплики при этом игнорируются (поток может оставаться green). Бесконечное хранение — пустое тело: `PUT /_data_stream/<имя>/_lifecycle` с `{}`.

**Эффективный retention** вычисляется из трёх источников (precedence: `data_retention` → `default_retention` → `max_retention`):

| `data_streams.lifecycle.retention.default` | `data_streams.lifecycle.retention.max` | `data_retention` | `effective_retention` | Retention determined by |
| :--- | :--- | :--- | :--- | :--- |
| Не задан | Не задан | Не задан | ∞ (вечно) | `data_stream_configuration` |
| — | 12m | 30d | 30d | `data_stream_configuration` |
| 30d | — | — | 30d | `default_retention` |
| — | 30d | — | 30d | `max_retention` |

Глобальные настройки `retention.default` и `retention.max` задаются через API: `PUT _cluster/settings {"persistent": {"data_streams.lifecycle.retention.default": "7d", "data_streams.lifecycle.retention.max": "365d"}}`. Проверить эффективный retention можно через `GET _data_stream/<имя>` (поле `effective_retention`, `retention_determined_by`). Для новых потоков ту же настройку задают в компонент-шаблоне:

```json
PUT /_component_template/logs-dlm
{
  "template": {
    "lifecycle": {
      "data_retention": "30d",
      "frozen_after": "7d",
      "downsampling": [
        { "after": "1d", "fixed_interval": "10m" },
        { "after": "7d", "fixed_interval": "1h" }
      ]
    }
  }
}
```

Массив `downsampling` работает только для TSDS; интервалы должны быть кратны друг другу (каждый последующий — кратный предыдущему); downsampling запускается после окончания time series end time индекса. Порядок `downsampling.after` строго возрастает. `frozen_after` (GA с 9.5) конвертирует backing-индексы старше указанного срока в partially mounted searchable snapshots на frozen tier — требует зарегистрированного **default snapshot repository** (`repositories.default_repository`); удаление по retention продолжает работать и после заморозки. `downsampling_method` (`aggregate`/`last_value`, default `aggregate`) — preview с 9.3, задаётся на верхнем уровне lifecycle рядом с `data_retention`, требует определённый массив `downsampling`.

Ограничения порядка значений для `frozen_after`: он должен быть меньше `data_retention` и больше любого `downsampling.after` — иначе API отклонит конфигурацию. Проверить статус DLM для конкретного backing-индекса: `GET /<index>/_lifecycle/explain`. Очистка тестовой настройки: `DELETE /_data_stream/logs-app-default/_lifecycle`.

### 6. Автоматическое резервное копирование по расписанию (SLM)

Сценарий: ежедневный снапшот всех индексов с хранением последних 14 копий. Механика регистрации репозитория (`path.repo`, `PUT _snapshot/...`) описана в [обзоре](./elasticsearch_overview.md) — здесь только автоматизация.

```bash
# Политика: ежедневно в 01:30, снимки старше 14 дней удаляются автоматически
curl -u elastic:$PASS -k -X PUT "$ES/_slm/policy/daily-backup" \
-H 'Content-Type: application/json' -d'
{
  "schedule": "0 30 1 * * ?",
  "name": "<snap-{now/d}>",
  "repository": "local-backup",
  "config": { "indices": "*", "ignore_unavailable": true, "include_global_state": false },
  "retention": { "expire_after": "14d", "min_count": 7, "max_count": 30 }
}'
# → {"acknowledged":true}

# Не ждать первого запуска по расписанию — выполнить немедленно
curl -u elastic:$PASS -k -X PUT "$ES/_slm/policy/daily-backup/_execute"
# → {"snapshot_name":"daily-backup-snap-2026.08.23"}

# Статистика выполнения политики
curl -u elastic:$PASS -k "$ES/_slm/stats?pretty"
# → {"retention_runs":...,"policy_stats":[{"policy":"daily-backup","snapshots_taken":1,"snapshots_failed":0,...}]}
```

Ключевые поля: `schedule` — cron из 6 полей (сек мин час день месяц день_недели); `name` поддерживает date math (`{now/d}` — дата без времени); `config.indices` — индексы/data streams (multi-target syntax); `config.ignore_unavailable` (default **false**) — не падать при отсутствии индекса; `config.include_global_state` (default **true**) — включать cluster state (persistent settings, шаблоны, ingest pipelines, ILM-политики, feature states); `retention` — `expire_after` (возраст), `min_count` (минимум копий — сохраняются даже если истекли), `max_count` (максимум копий).

Retention-задача запускается отдельно от расписания снапшотов: кластерная настройка `slm.retention_schedule` (default `0 30 1 * * ?` — ежедневно 1:30 UTC), лимит времени удаления — `slm.retention_duration` (default `1h`). Ручной запуск: `POST _slm/_execute_retention`. История выполнений пишется в `slm-history-*` (`slm.history_index_enabled`, default `true`).

Управление политиками и планировщиком:

```bash
curl -u elastic:$PASS -k "$ES/_slm/policy"                        # список политик
curl -u elastic:$PASS -k -X DELETE "$ES/_slm/policy/daily-backup" # удаление политики
curl -u elastic:$PASS -k "$ES/_slm/status"                        # → {"state":"RUNNING",...}
curl -u elastic:$PASS -k -X POST "$ES/_slm/stop"                  # остановить планировщик
curl -u elastic:$PASS -k -X POST "$ES/_slm/start"                 # запустить планировщик
```

Восстановление данных из снапшота — см. сценарий снапшотов в обзоре и [Disaster Recovery](./elasticsearch_disaster_recovery.md).

### 7. ILM для одноузлового кластера с Vector

Сценарий: single-node Elasticsearch с PVC 50 ГБ, куда Vector пишет логи по write alias `vector-logs`. Без ILM диск переполнится за несколько недель. Для одноузловой конфигурации пропускаются фазы `shrink` и `freeze` — используется только hot → delete.

#### 1. Политика ILM

Ротация при 20 ГБ или 7 дней. Порог 20 ГБ (меньше общей рекомендации 50 ГБ — см. [Capacity Planning](./elasticsearch_capacity_planning.md)) выбран для single-node с ограниченным PVC: меньшие индексы проще управлять на одном узле, а перезапуск ILM на большом индексе более дорогой. Удаление через 30 дней после ротации:

```bash
curl -X PUT "http://elasticsearch:9200/_ilm/policy/vector-logs" \
  -H "Content-Type: application/json" \
  -d '{
    "policy": {
      "phases": {
        "hot": {
          "min_age": "0ms",
          "actions": {
            "rollover": {
              "max_primary_shard_size": "20gb",
              "max_age": "7d"
            },
            "set_priority": { "priority": 100 }
          }
        },
        "delete": {
          "min_age": "30d",
          "actions": { "delete": {} }
        }
      }
    }
  }'
```

`min_age: "0ms"` в hot-фазе игнорируется ILM — фаза начинается сразу (см. детали в [Действиях ILM](#действия-ilm)).

#### 2. Шаблон индекса

`number_of_replicas: 0` обязательно для single-node — при replicas=1 статус кластера будет `yellow` (реплике нет куда распределяться — см. [обзор](./elasticsearch_overview.md), таблица Troubleshooting). `number_of_shards: 1` оптимально для небольших объёмов:

```bash
curl -X PUT "http://elasticsearch:9200/_index_template/vector-logs" \
  -H "Content-Type: application/json" \
  -d '{
    "index_patterns": ["vector-*"],
    "template": {
      "settings": {
        "index.lifecycle.name": "vector-logs",
        "index.lifecycle.rollover_alias": "vector-logs",
        "number_of_replicas": 0,
        "number_of_shards": 1
      },
      "mappings": {
        "properties": {
          "@timestamp": {"type": "date"},
          "message": {"type": "text"},
          "level": {"type": "keyword"},
          "kubernetes.namespace": {"type": "keyword"},
          "kubernetes.pod.name": {"type": "keyword"}
        }
      }
    }
  }'
```

`index.lifecycle.rollover_alias` требуется только для обычных индексов с ILM-rollover (а не для Data Streams); для Data Stream ротация управляется автоматически — см. [Index Templates](./elasticsearch_index_templates.md).

#### 3. Bootstrap write alias

ILM требует write alias на начальный индекс. Vector пишет в alias `vector-logs`, ILM создаёт `vector-logs-000002`, `vector-logs-000003` и т.д. при rollover:

```bash
curl -X PUT "http://elasticsearch:9200/vector-logs-000001" \
  -H "Content-Type: application/json" \
  -d '{
    "aliases": {
      "vector-logs": {
        "is_write_index": true
      }
    }
  }'
```

#### 4. Bootstrap как Kubernetes Job

Для Kubernetes инкапсулируйте шаги 1–3 в Job с идемпотентностью (`|| true` на создание начального индекса — повторный запуск после пересборки кластера не падает, если индекс уже существует):

```bash
#!/bin/bash
set -e

ES_URL="http://elasticsearch-master.observability.svc.cluster.local:9200"

until curl -sf "$ES_URL/_cluster/health?wait_for_status=yellow"; do
  echo "ожидание elasticsearch..."
  sleep 5
done

curl -sf -X PUT "$ES_URL/_ilm/policy/vector-logs" \
  -H "Content-Type: application/json" \
  --data-binary @/bootstrap/ilm-policy.json

curl -sf -X PUT "$ES_URL/_index_template/vector-logs" \
  -H "Content-Type: application/json" \
  --data-binary @/bootstrap/index-template.json

# || true — идемпотентность: индекс уже может существовать после пересборки кластера
curl -sf -X PUT "$ES_URL/vector-logs-000001" \
  -H "Content-Type: application/json" \
  --data-binary @/bootstrap/initial-index.json \
  || true

echo "Bootstrap завершён"
```

#### 5. Мониторинг ILM

```bash
# Фаза и возраст каждого индекса
curl http://elasticsearch:9200/vector-*/_ilm/explain?filter_path=indices.*.phase,indices.*.age
# → {"indices":{"vector-logs-000001":{"phase":"hot","age":"..."}}}

# Индексы с ошибками ILM (step_info присутствует только при ошибке)
curl http://elasticsearch:9200/vector-*/_ilm/explain | jq '.indices | to_entries[] | select(.value.step_info != null)'

# Ручной rollover (для теста или экстренной ротации)
curl -X POST "http://elasticsearch:9200/vector-logs/_rollover"
# → {"acknowledged":true,...,"new_index":"vector-logs-000002"}

# Перезапуск застрявшего шага ILM (например, после освобождения диска)
curl -X POST "http://elasticsearch:9200/vector-logs-000001/_ilm/retry"
# → {"acknowledged":true}
```

ILM проверяет условия не мгновенно, а раз в 10 минут (`indices.lifecycle.poll_interval` — см. [Настройки](#настройки)).

#### 6. Ориентиры по шардам для single-node

| Объём данных | Шарды | Размер шарда |
|:---:|:---:|:---:|
| < 5 ГБ/день | 1 | < 10 ГБ |
| 5–20 ГБ/день | 1–3 | 10–30 ГБ |
| > 50 ГБ/день | 3–6 | 20–50 ГБ |

Избыточное количество шардов — частая ошибка: каждый шард потребляет файловые дескрипторы и heap. Для single-node с небольшим ingest лучше перестраховать в сторону меньшего числа шардов с большим rollover threshold.

## Настройки

### Кластерные и индексные настройки ILM

| Настройка | Default | Описание |
| :--- | :--- | :--- |
| `indices.lifecycle.poll_interval` | `10m` | интервал проверки ILM-политик (dynamic) |
| `index.lifecycle.name` | — | имя ILM-политики (индексная настройка, задаётся в шаблоне) |
| `index.lifecycle.rollover_alias` | — | write-алиас для ротации; нужен только для alias-based rolling, не для data streams |
| `index.lifecycle.origination_date` | — | epoch-ms дата, от которой считается возраст индекса (для backfill-данных) |
| `index.lifecycle.step.wait_time_threshold` | `12h` | сколько ILM ждёт возможности выполнить шаг (например, реаллокацию после shrink), прежде чем откатить попытку |
| `indices.lifecycle.history_index_enabled` | `true` | писать историю ILM-событий в `ilm-history-*` (dynamic) |
| `thread_pool.forcemerge.size` | — | размер threadpool force merge (увеличивать при backlog задач) |

### Настройки DLM

| Настройка | Default | Описание |
| :--- | :--- | :--- |
| `data_streams.lifecycle.poll_interval` | `5m` | интервал проверки DLM (dynamic) |
| `data_streams.lifecycle.downsampling.max_indices_in_progress` | `10` | максимум backing-индексов на поток, отправляемых на downsampling за один цикл (dynamic, GA с 9.5) |
| `data_streams.lifecycle.retention.default` | — | retention по умолчанию для потоков без `data_retention` (dynamic) |
| `data_streams.lifecycle.retention.max` | — | максимальный retention; переопределяет слишком большие значения `data_retention` (dynamic) |
| `cluster.lifecycle.default.rollover` | `max_age=auto,max_primary_shard_size=50gb,min_docs=1,max_primary_shard_docs=200000000` | условия ротации по умолчанию для DLM (dynamic; `max_age=auto` вычисляется из retention) |
| `repositories.default_repository` | — | репозиторий снапшотов по умолчанию, используемый DLM для frozen tier переходов (см. ниже) |
| `dlm.frozen_transitions.enabled` | `true` | включить/выключить frozen tier переходы DLM (dynamic) |
| `dlm.frozen.transition.poll_interval` | `5m` | интервал проверки конвертируемых в frozen backing-индексов мастером (static, min `1m`) |
| `dlm.frozen.transition.thread_pool.size` | min(2*CPU, 100) | максимум параллельных конвертаций на узле (static) |
| `dlm.frozen.transition.thread_pool.queue_size` | min(20*CPU, 1000) | размер очереди на конвертацию (static) |
| `dlm.frozen.cleanup.poll_interval` | `1d` | частота очистки orphaned-артефактов (клонов, снапшотов) после прерванных конвертаций (static, min `1h`) |

### Настройки DLM: индексные

| Настройка | Default | Описание |
| :--- | :--- | :--- |
| `index.lifecycle.prefer_ilm` | `true` | если `true` и backing-индекс управляется ILM, ILM имеет приоритет над DLM; `false` — DLM управляет индексом (dynamic) |
| `index.dlm.frozen.created` | — | внутренний маркер индексов, созданных DLM during frozen конвертации (только для диагностики) |

### Настройки SLM

| Настройка | Default | Описание |
| :--- | :--- | :--- |
| `slm.retention_schedule` | `0 30 1 * * ?` (1:30 UTC) | расписание retention-задачи |
| `slm.retention_duration` | `1h` | лимит времени удаления старых снапшотов |
| `slm.history_index_enabled` | `true` | писать историю выполнений в `slm-history-*` |

## Граничные случаи

* **Downsample выполняется до allocate/migrate**: ILM запускает downsample, пока индекс ещё находится в tier предыдущей фазы (исходный индекс остаётся в hot, даже если downsample задан в warm); downsampled-индекс мигрирует в целевой tier после завершения.
* **Force merge и read-only**: в 7.x ILM forcemerge переводил индекс в read-only; в 8.x это поведение удалено — индекс остаётся записываемым. Для запрета записи используйте действие `readonly`.
* **Неявный rollover**: при 200M документов на шард даже без явных условий rollover.
* **Rollover блокирует последующие фазы**: rollover завершается только при выполнении условия; delete-фаза с `min_age: 1d` удалит индекс через день после ротации, а не после создания.
* **Shrink**: `number_of_shards` должен быть делителем числа шардов исходного индекса; конфликтует с `max_primary_shard_size`; ошибка, если исходный индекс уже одношардный. Нельзя shrink'ить write-индекс.
* **ILM ждёт до 12 часов** (`index.lifecycle.step.wait_time_threshold`) при невозможности реаллокации шардов после shrink; по истечении удаляет shrunken-индекс и повторяет попытку.
* **`index_codec: best_compression`**: ILM закрывает и открывает индекс перед force merge — индекс недоступен на время операции.
* **`index.lifecycle.origination_date`**: для backfill-данных — изменяет точку отсчёта расчёта возраста (иначе старые данные сразу попадут в delete-фазу).
* **Ручной монтир снапшотов**, созданных ILM-политикой, мешает автоматическому управлению ILM — возможны проблемы с данными и обработкой снапшотов.
*   **ILM `error_notification`** в Elasticsearch отсутствует (реализован в ISM OpenSearch) — контролируйте ошибки через алертинг на метрики ILM.
*   **9.4+**: `allocate` с `number_of_replicas` явно удаляет `auto_expand_replicas` из настроек индекса.
*   **Merges рекомендуется выполнять на SSD**, не HDD; force merge — ресурсоёмкая операция, не выполняйте её до завершения всех модификаций индекса (relocating shards не мерджатся — операция best effort).
*   **DLM: `frozen_after` порядок значений**: `frozen_after` < `data_retention` и > любого `downsampling.after`; иначе API отклоняет конфигурацию. Изменение `frozen_after` после `generation_time` не останавливает уже назначенную конвертацию.
*   **DLM: downsampling только для TSDS**: обычные логи не даунсэмплятся — используйте [Rollup и Transform](./elasticsearch_rollup_transform.md) для агрегации не-TSDS данных.
*   **DLM: tail merging вместо force merge**: DLM автоматически выполняет tail merging (слияние хвоста сегментов) после ротации — не нужно добавлять явный `forcemerge` в ILM-политику для data streams.

## Best Practices

* Целевой размер шарда 50 ГБ; основной триггер ротации — `max_primary_shard_size`.
* DLM для типовых логов/метрик; ILM — когда нужны shrink, force merge, сложные условия или обычные индексы.
* `wait_for_snapshot` в delete-фазе — гарантия наличия снапшота перед удалением индекса.
* `delete_searchable_snapshot: false` в delete-действии, если снапшот нужно сохранить (retention снапшота работает через ILM, не SLM).
* Мониторинг: алертинг на ошибки ILM и DLM (`GET /_ilm/status`, `_ilm/explain`, `_lifecycle/explain` для DLM). Для DLM — проверять статус через `GET /<index>/_lifecycle/explain` на наличие `error` и `managed_by_lifecycle: true`.
* Force merge размещайте в warm-фазе (не в hot, чтобы не влиять на ингест); merges — на SSD.
*   **Гoverning retention**: задавайте `data_streams.lifecycle.retention.max` на уровне кластера, чтобы ограничить максимальный срок хранения для всех потоков. Используйте `cluster.lifecycle.default.rollover` для единообразной политики ротации.
* Frozen tier (9.5+) через `frozen_after` — экономия до 10x на долгосрочном хранилии метрик; требует Enterprise license и default snapshot repository (`repositories.default_repository`).

## Cleanup

```bash
# Удалить ILM-политику (только если не назначена индексам)
curl -u elastic:$PASS -k -X DELETE "$ES/_ilm/policy/logs-policy"
# → {"acknowledged":true}

# Убрать ILM-политику из шаблона — удалите "index.lifecycle.name" из компонент-шаблона и обновите его

# Удалить тестовые индексы/потоки
curl -u elastic:$PASS -k -X DELETE "$ES/logs-app-*"

# DLM: удалить retention/downsampling/frozen_after из потока и шаблона
curl -u elastic:$PASS -k -X DELETE "$ES/_data_stream/logs-app-default/_lifecycle"
# → {"acknowledged":true}

# SLM: удалить политику и тестовые снапшоты
curl -u elastic:$PASS -k -X DELETE "$ES/_slm/policy/daily-backup"
curl -u elastic:$PASS -k -X DELETE "$ES/_snapshot/local-backup/daily-backup-snap-*"
```

## Дополнительная информация

### Searchable Snapshots и уровни хранения

*   **Cold Tier (Fully Mounted)**: все шарды снапшота кэшируются в кластере; производительность поиска сравнима с обычным индексом; данные на диске сохраняются между рестартами (не перекачиваются заново). Реплики не нужны — сохранность гарантирует репозиторий. Индексы с префиксом `restored-`.
*   **Frozen Tier (Partially Mounted)**: локально — только кэш недавно запрашиваемых данных фиксированного размера, общий для шардов на одном узле; при промахе кэша данные догружаются из репозитория. Индексы с префиксом `partial-`. Подходит для хранения данных годами.
*   **Конвертация в frozen через DLM (9.5+)**: когда backing-индекс старше `frozen_after`, DLM выполняет атомарную конвертацию: (1) помечает индекс read-only + flush; (2) клонирует с нулевыми репликами (`dlm-clone-*`); (3) force-merges до одного сегмента; (4) снимает снапшот (`dlm-frozen-*`) в **default snapshot repository** (`repositories.default_repository`); (5) монтирует как partially mounted searchable snapshot на frozen tier; (6) атомарно заменяет оригинал и удаляет его. Если default repository не настроен — DLM пишет warning и данные остаются на hot до конфигурации репозитория.
*   **Default snapshot repository**: настраивается через `PUT _cluster/settings {"persistent": {"repositories.default_repository": "my-repo"}}`. DLM использует его для всех frozen конвертаций в кластере. Репозиторий должен быть зарегистирован (см. [обзор](./elasticsearch_overview.md)) и не read-only. На ECH предзаполнен `found-snapshots`. После заморозки retention продолжает удалять индексы по `data_retention`.
*   **Настройки кэша**: `xpack.searchable.snapshot.shared_cache.size` — размер shared cache (процент или байты; default — 90% диска на узлах dedicated frozen tier, иначе `0b`); `xpack.searchable.snapshot.shared_cache.size.max_headroom` — default `100GB` (только при заданном проценте). Настройки только на узлах с ролью `data_frozen` (один data path).
*   **Скорость восстановления** ограничена `max_restore_bytes_per_sec` репозитория и `indices.recovery.max_bytes_per_sec`.
*   *Лицензия*: Searchable Snapshots (а значит фазы Cold/Frozen) требуют подписки Enterprise. Downsampling доступен в Basic (Free).
*   *Экономика*: Frozen tier хранит петабайты по цене хранилища снапшотов; первый холодный запрос к кэшируемым блокам медленный (сеть), повторные — из локального кэша. Планируруйте размер кэша через `xpack.searchable.snapshot.shared_cache.size`.

### Смотрите также

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера и уровни данных (Data Tiers).
*   **[Elasticsearch: Индексирование и маппинг](./elasticsearch_mapping_and_indexing.md)** — детально о структуре Data Streams.
*   **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — Data Streams для time-series.
*   **[Capacity Planning](./elasticsearch_capacity_planning.md)** — расчет ресурсов для ILM.
*   **[Rollup и Transform](./elasticsearch_rollup_transform.md)** — downsampling и агрегация.
*   **[Disaster Recovery](./elasticsearch_disaster_recovery.md)** — SLM для backup.
*   **[Официальная документация: ILM Actions](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions)**
*   **[Официальная документация: Data Stream Lifecycle (DLM)](https://www.elastic.co/docs/manage-data/lifecycle/data-stream)**
*   **[Официальная документация: SLM](https://www.elastic.co/docs/reference/elasticsearch/snapshot-restore/snapshot-lifecycle-api-put)**.
