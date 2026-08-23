# Elasticsearch: Жизненный цикл индексов (ILM) и политики хранения

> Заметка посвящена автоматизации хранения временных рядов в Elasticsearch: политикам ILM, упрощенному Data Stream Lifecycle (DLM), downsampling'у метрик и резервному копированию по расписанию (SLM). Базовые понятия кластера (шарды, роли узлов, watermarks) описаны в [обзоре Elasticsearch](./elasticsearch_overview.md).

## Определения

* **ILM (Index Lifecycle Management)** — подсистема Elasticsearch для полной автоматизации управления индексами через набор фаз и действий.
* **DLM (Data Stream Lifecycle)** — упрощенный механизм управления жизненным циклом, ориентированный специально на потоки данных (Data Streams). Позволяет настраивать хранение (`retention`) и перенос в `frozen` без создания сложных политик ILM.
* **Ротация (Rollover)** — процесс закрытия текущего индекса для записи и создания нового при достижении определенных условий (размер, возраст, количество документов).
* **Data Tier (Уровень данных)** — логическая роль узла в хранении данных (`hot`, `warm`, `cold`, `frozen`), определяющая тип оборудования и стоимость хранения.
* **Downsampling** — технология уменьшения объема данных временных рядов (TSDS) путем агрегации старых метрик в более крупные временные интервалы (бакеты), сохраняя статистическую значимость (`min`, `max`, `sum`, `count`).
* **Searchable Snapshot (Поисковый снимок)** — технология, позволяющая выполнять поисковые запросы напрямую по данным, хранящимся в объектном хранилище (S3/GCS), без необходимости их полного восстановления на локальный диск.
* **Data Stream (Поток данных)** — именованная сущность только для записи, скрывающая за собой набор backing-индексов (`.ds-<имя>-<дата>-<номер>`). Запись всегда идет в последний backing-индекс; ILM/DLM управляют ими автоматически. Требует шаблона с `"data_stream": {}` и поля `@timestamp`.
* **TSDS (Time Series Data Stream)** — специализированный поток данных для метрик: поля размечаются как `time_series_dimension` (измерения) и `time_series_metric` (`gauge`, `counter`). Только TSDS поддерживают downsampling.
* **min_age** — порог времени, определяющий готовность индекса к переходу в следующую фазу. Отсчитывается от даты создания/ротации backing-индекса, а **не** от момента входа в предыдущую фазу.
* **SLM (Snapshot Lifecycle Management)** — подсистема автоматизации снапшотов по расписанию (аналог ILM для резервного копирования): политика задает cron-расписание, репозиторий и retention самих снимков.

## Основные концепции

### Фазы жизненного цикла

В современной архитектуре (8.x+) жизненный цикл делится на пять фаз. Переход между фазами определяется параметром `min_age` (время с момента ротации).

| Фаза | Характеристики | Ключевые действия |
| :--- | :--- | :--- |
| **Hot** | Активная запись и поиск. | **Rollover**: создание нового индекса. **Downsample**: агрегация метрик (8.15+). |
| **Warm** | Запись закрыта, поиск частый. | **Shrink**: уменьшение числа шард. **Force Merge**: оптимизация сегментов. **Migrate**: перенос на `warm` узлы. |
| **Cold** | Поиск редкий, данные статичны. | **Searchable Snapshot**: (Fully Mounted) — снимок становится основной копией данных. |
| **Frozen** | Архивный поиск. | **Searchable Snapshot**: (Partially Mounted) — данные в облаке, на диске только кэш. |
| **Delete** | Данные не нужны. | **Delete**: окончательное удаление. |

Важные детали механики:

* **Лицензирование фаз**: Hot/Warm/Delete доступны в бесплатном уровне. Фазы Cold и Frozen используют Searchable Snapshots и требуют подписки Enterprise.
* **Семантика `min_age`**: время отсчитывается от даты создания (для Data Streams — от ротации) backing-индекса, а не от входа в фазу. Поэтому `warm.min_age: 0ms` в примере ниже означает "сразу после ротации", а `delete.min_age: 30d` — 30 дней с момента создания индекса, независимо от того, когда он попал в warm.
* **Интервал проверки**: ILM/DLM не выполняют действия мгновенно — политика проверяется раз в 10 минут (`indices.lifecycle.poll_interval`). Для тестов уменьшите: `PUT /_cluster/settings {"transient": {"indices.lifecycle.poll_interval": "1m"}}`.
* **Прочие действия**: помимо перечисленных в таблице, политики поддерживают `allocate` (число реплик/атрибуты размещения), `set_priority` (приоритет восстановления после сбоя), `readonly`, `wait_for_snapshot`.

### Рекомендации по размеру шард

Для стабильности кластера и производительности ILM следует придерживаться правила: **целевой размер основного шарда — 50 ГБ**.
*   Используйте `max_primary_shard_size: "50gb"` в качестве основного триггера ротации.
*   Избегайте "раздувания шардов" (shard bloat) — ситуации с тысячами мелких индексов по несколько мегабайт, что перегружает Master-узел.

### Data Stream Lifecycle (DLM) vs ILM

Начиная с версий 8.12+, для стандартных логов рекомендуется использовать **DLM** из-за простоты:
*   **ILM**: Максимальная гибкость (shrink, force merge, сложные условия). Требует политики и шаблона.
*   **DLM**: Настраивается одной командой API. Автоматически управляет ротацией и удалением. Идеально для большинства observability-задач.
*   **DLM в шаблоне**: Конфигурация lifecycle может задаваться компонент-шаблоном (секция `template.lifecycle` с `data_retention` и массивом `downsampling`) — тогда новые потоки наследуют её автоматически. Рабочий пример — сценарий 5 ниже.
*   **Совместимость**: Политика DLM не смешивается с ILM на одном потоке; миграция выполняется через `PUT /_data_stream/<имя>/_lifecycle` либо удалением ILM-настройки из шаблона.

## Практические сценарии

**Предварительные требования для всех сценариев** (аналогичны [обзору](./elasticsearch_overview.md)):

```bash
export ES="https://localhost:9200"
export PASS="<пароль пользователя elastic>"
# Проверка доступности:
curl -u elastic:$PASS -k "$ES"   # → {"name" : "es-node-1", ..., "tagline" : "You Know, for Search"}
```

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

# Ручная ротация (не дожидаясь триггеров 50gb/30d)
curl -u elastic:$PASS -k -X POST "$ES/logs-app-000001/_rollover"
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

* **Работает только для TSDS**: индексы должны быть созданы как time series data stream (маппинг с `time_series_dimension` и `time_series_metric`). Для обычных индексов используйте transform или rollup.
* **Исходный индекс заменяется**: downsampled-индекс наследует tier, число шардов и реплик исходного; оригинал удаляется после успеха. Внутри одного потока на период времени существует ровно один индекс.
* **Что сохраняется**: для каждого метрика-поля (`gauge`) значения агрегируются в `aggregate_metric_double` (`min`, `max`, `sum`, `value_count`); dimension-поля копируются без изменений. Запросы `_search` и агрегации работают по объединенному потоку без изменения клиента.
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

Инструменты восстановления:

```bash
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
```

**Типичные ошибки:**
*   **"index.lifecycle.rollover_alias does not point to index"**: Вы используете старый подход с алиасами. Рекомендуется перейти на **Data Streams**.
*   **Insufficient disk space**: ILM не выполнит `shrink` или `migrate`, если на узлах превышен порог `high watermark` (обычно 90%). Пороги и диагностика — в [руководстве по кластеру](../Tutorials/cluster_setup.md).
*   **ILM Status is STOPPED**: Проверьте статус через `GET /_ilm/status`. Запустите при необходимости: `POST /_ilm/start`.
*   **Шаг завис в `WAITING` без видимой ошибки**: Проверьте соответствие условиям триггера (`max_age`/`max_primary_shard_size`) через `_ilm/explain`; помните про интервал опроса 10 минут.
*   **Молчаливые сбои ротации**: Горячий индекс растет неограниченно — проверьте `_ilm/explain` на `step: ERROR`. Для превентивного контроля настройте алертинг на метрику ошибок ILM или используйте механизм `error_notification` (реализован в ISM OpenSearch, см. [сравнение](../OpenSearch/opensearch_ism_lifecycle.md)).

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
#     "lifecycle":{"enabled":true,"data_retention":"300000000000ns"}}]}
```

Пояснения: `data_retention` отсчитывается от ротации backing-индекса; по истечении срока индекс удаляется автоматически, реплики при этом игнорируются (поток может оставаться green). Для новых потоков ту же настройку задают в компонент-шаблоне:

```json
PUT /_component_template/logs-dlm
{
  "template": {
    "lifecycle": {
      "data_retention": "30d",
      "downsampling": [
        { "after": "7d", "fixed_interval": "1h" },
        { "after": "30d", "fixed_interval": "24h" }
      ]
    }
  }
}
```

Массив `downsampling` работает только для TSDS; интервалы должны быть кратны друг другу. Очистка тестовой настройки: `DELETE /_data_stream/logs-app-default/_lifecycle`.

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
  "retention": { "expire_after": "14d", "max_count": 30 }
}'
# → {"acknowledged":true}

# Не ждать первого запуска по расписанию — выполнить немедленно
curl -u elastic:$PASS -k -X PUT "$ES/_slm/policy/daily-backup/_execute"
# → {"snapshot_name":"daily-backup-snap-2026.08.23"}

# Статистика выполнения политики
curl -u elastic:$PASS -k "$ES/_slm/stats?pretty"
# → {"retention_runs":...,"policy_stats":[{"policy":"daily-backup","snapshots_taken":1,"snapshots_failed":0,...}]}
```

Ключевые поля: `schedule` — cron из 6 полей (сек мин час день месяц день_недели); `name` поддерживает date math (`{now/d}` — дата без времени); `retention` чистит старые снимки силами SLM-ретеншн-задачи (по умолчанию каждые 15 минут). Восстановление данных из снимка — см. сценарий снапшотов в обзоре.

## Дополнительная информация

### Searchable Snapshots и уровни хранения

*   **Cold Tier**: Данные хранятся в S3, но индекс "смонтирован" полностью. Реплики не нужны, так как S3 гарантирует сохранность. Экономия 50% ресурсов.
*   **Frozen Tier**: Локально хранится только кэш самых частых запросов. Подходит для хранения данных годами.
*   *Лицензия*: Searchable Snapshots (а значит фазы Cold/Frozen) требуют подписки Enterprise. Downsampling доступен в Basic (Free).
*   *Экономика*: Frozen tier хранит петабайты по цене объектного хранилища; первый холодный запрос к кэшируемым блокам медленный (сеть), повторные — из локального кэша. Планируйте размер кэша через `xpack.searchable.snapshot.shared_cache.size`.

### Смотрите также

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера и уровни данных (Data Tiers).
*   **[Elasticsearch: Индексирование и маппинг](./elasticsearch_mapping_and_indexing.md)** — детально о структуре Data Streams.
*   **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — Data Streams для time-series.
*   **[Capacity Planning](./elasticsearch_capacity_planning.md)** — расчет ресурсов для ILM.
*   **[Rollup и Transform](./elasticsearch_rollup_transform.md)** — downsampling и агрегация.
*   **[Disaster Recovery](./elasticsearch_disaster_recovery.md)** — SLM для backup.
*   **[Официальная документация: ILM Actions](https://www.elastic.co/guide/en/elasticsearch/reference/current/ilm-actions.html)**.
