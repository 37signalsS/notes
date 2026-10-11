# Index Templates (OpenSearch)

**Актуально для:** OpenSearch 2.x / 3.x. Composable templates (`_index_template`) — основной API; legacy-шаблоны (`_template`) сохранены только для обратной совместимости. `context` (index context) — экспериментальная функция с 2.17.

> Шаблоны индексов в OpenSearch: composable и component templates, приоритеты, симуляция, data streams. Шаблон применяется только к **новым** индексам и data streams — уже созданные не изменяются. Общая теория composable-шаблонов и data streams (совместима с Elasticsearch) — в [Elasticsearch: Index Templates](../Elasticsearch/elasticsearch_index_templates.md).

## Определения

* **Index template** — шаблон, автоматически применяющий `settings`, `mappings` и `aliases` ко всем новым индексам и data streams, чьё имя совпадает с `index_patterns`.
* **Component template** — переиспользуемый фрагмент шаблона (mappings/settings/aliases), подключаемый через `composed_of`; сам по себе к индексам не применяется.
* **`index_patterns`** — список wildcard-выражений, сопоставляемых с именами индексов и data streams (`logs-*`, `metrics-2026.*`). В паттерне не допускаются символы `:`, `"`, `+`, `/`, `\`, `|`, `?`, `#`, `>`, `<`.
* **`priority`** — приоритет шаблона; при совпадении нескольких шаблонов применяется только шаблон с наибольшим `priority`. По умолчанию `0`.
* **Data stream** — поток append-only индексов (скрытые backing-индексы `.ds-*`) для time-series данных; создаётся из шаблона с `data_stream`.
* **Legacy template** — старый API `_template`; не поддерживает component templates и `data_stream`, deprecated.
* **Index context** — экспериментальная привязка индекса/шаблона к предопределённому набору настроек и маппингов по use-case (`context`, 2.17+).

## Как работает применение шаблона

1. При создании индекса или data stream OpenSearch находит все шаблоны, чей `index_patterns` совпадает с именем.
2. Из совпавших применяется **только один** — с наибольшим `priority`; остальные игнорируются, а не сливаются. Шаблоны с совпадающими паттернами и одинаковым `priority` недопустимы: создание второго отклоняется с `400` (OpenSearch не может определить, какой применять). Поэтому `priority` задают явно.
3. Внутри выбранного шаблона последовательно применяются component templates из `composed_of` **в порядке перечисления**, затем — `settings`, `mappings`, `aliases` самого шаблона: они имеют наивысший приоритет. Для `mappings`, `dynamic_templates` и `_meta` применяется рекурсивное слияние — совпавшие ключи перезаписываются более поздним источником, новые добавляются.
4. Значения из запроса создания индекса (`PUT /<index>`) перекрывают значения шаблона.
5. Шаблон применяется один раз — при создании; изменение шаблона существующие индексы не меняет.

Порядок наложений (от низкого к высокому):

```
component templates в порядке composed_of → inline-блок template шаблона →
настройки, переданные в самом запросе PUT /<index>
```

## Component Template

```bash
# Общий маппинг логов
PUT _component_template/logs-mapping
{
  "template": {
    "mappings": {
      "dynamic": "strict",
      "properties": {
        "@timestamp": { "type": "date" },
        "level":      { "type": "keyword" },
        "service":    { "type": "keyword" },
        "message": {
          "type": "text",
          "fields": { "keyword": { "type": "keyword", "ignore_above": 2048 } }
        }
      }
    }
  },
  "version": 1
}

# Общие настройки хранения
PUT _component_template/logs-settings
{
  "template": {
    "settings": {
      "number_of_shards": 2,
      "number_of_replicas": 1,
      "index.refresh_interval": "5s"
    }
  },
  "version": 1
}
# → {"acknowledged":true}
```

Component template действует только там, где его перечислили в `composed_of`: создание компонента не привязывает его к уже существующим шаблонам. Обновление компонента затрагивает все ссылающиеся шаблоны, но применяется только к индексам, созданным **после** обновления. Удаление компонента убирает его значения из ссылающихся шаблонов — переопределённые самим шаблоном значения остаются.

**Привязка ISM-политики.** Автоматическое управление жизненным циклом задаётся не настройкой шаблона, а блоком `ism_template` внутри самой ISM-политики (`index_patterns` + `priority`). Настройка шаблона, привязывавшая политику (`opendistro.index_state_management.policy_id` и её вариант `plugins.index_state_management.policy_id`), объявлена устаревшей. Ключ Elasticsearch ILM `index.lifecycle.name` OpenSearch **игнорирует молча** — индекс останется неуправляемым без ошибки. Механика и примеры — в [ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md).

## Index Template

```bash
PUT _index_template/logs
{
  "index_patterns": ["logs-*"],
  "composed_of": ["logs-mapping", "logs-settings"],
  "priority": 100,
  "version": 3,
  "_meta": { "description": "Standard logs template", "owner": "platform" },
  "template": {
    "aliases": { "logs-current": {} },
    "settings": {
      "index.number_of_replicas": 2
    }
  }
}
```

Полный набор полей:

| Поле | Назначение |
|---|---|
| `index_patterns` | имена индексов/data streams, к которым применяется шаблон (обязательно) |
| `composed_of` | имена component templates, применяемые по порядку |
| `priority` | разрешение конфликтов (по умолчанию `0`) |
| `template` | inline `settings` / `mappings` / `aliases` |
| `data_stream` | объект `{...}` — шаблон для data stream (см. ниже) |
| `version`, `_meta` | версионирование и метаданные (для GitOps) |
| `context` | экспериментально (2.17+): use-case пресет настроек/маппингов, наивысший приоритет |

Query-параметры запроса: `create=true` — не перезаписывать существующий шаблон (по умолчанию `false`); `cluster_manager_timeout` — таймаут подключения к cluster manager (по умолчанию `30s`).

Ключи `allow_auto_create` и `ignore_missing_component_templates` из Elasticsearch в composable index-шаблонах OpenSearch **не поддерживаются** — парсер принимает только поля из таблицы выше.

## Управление и симуляция

```bash
# Просмотр
GET _index_template/logs
GET _index_template/logs*          # wildcard по именам шаблонов
GET _component_template/logs-*
HEAD _index_template/logs          # 200 — есть, 404 — нет
GET _cat/templates?v               # компактный список

# Симуляция: что применится к новому индексу с таким именем
POST /_index_template/_simulate_index/logs-2026.10.07

# Симуляция: итог конкретного шаблона (включая composed_of) без создания
POST /_index_template/_simulate/logs

# Симуляция нового определения без сохранения (тело = определение шаблона)
POST /_index_template/_simulate
{
  "index_patterns": ["logs-*"],
  "composed_of": ["logs-mapping"],
  "priority": 100
}

# Удаление
DELETE _index_template/logs
DELETE _component_template/logs-mapping
```

Ответ `_simulate*` содержит итоговый `template` (resolved settings/mappings/aliases) и массив `overlapping` — другие совпавшие шаблоны, которые **не** были применены. Это основной инструмент отладки приоритетов.

Права Security для composable-шаблонов: `indices:admin/index_template/put` (создание/обновление), `.../get`, `.../delete`, `.../simulate`, `.../simulate_index`. Для legacy-шаблонов — `indices:admin/template/*`.

## Data Stream Template

```bash
PUT _index_template/nginx-logs
{
  "index_patterns": ["nginx-logs"],
  "data_stream": {},
  "composed_of": ["logs-mapping", "logs-settings"],
  "priority": 100
}

# Создание data stream (создаёт первый backing-индекс .ds-nginx-logs-000001)
PUT _data_stream/nginx-logs
```

Особенности:

* `data_stream` — объект. По умолчанию поле времени — `@timestamp`; переопределяется через `"data_stream": { "timestamp_field": { "name": "<field>" } }`. Каждый документ обязан содержать это поле, иначе отклоняется.
* `index_patterns` data-stream-шаблона может содержать wildcard (например `logs-*`), но шаблон **монопольно** закрепляет эти паттерны: пока он существует, создание обычного индекса с подходящим именем падает с ошибкой ``cannot create index with name [...], because it matches with template [...] that creates data streams only``. Выбирайте паттерн, не пересекающийся с обычными индексами.
* Backing-индексы скрыты и имеют префикс `.ds-` (например `.ds-nginx-logs-000001`); точная структура имени — деталь реализации, опираться на неё не следует.
* Data stream **append-only**: принимаются только операции `create`. Обновление/удаление документа и `index`, перезаписывающий документ, адресованные имени потока, отклоняются — адресуйте backing-индекс напрямую.
* Rolling over — вручную `POST nginx-logs/_rollover` или автоматически через ISM-политику; отдельный `rollover_alias` для data stream не нужен. См. [ISM](./opensearch_ism_lifecycle.md).

Управление:

```bash
GET _data_stream/nginx-logs        # имя, timestamp-поле, backing-индексы, generation, template, status
GET _data_stream/nginx-logs/_stats
DELETE _data_stream/nginx-logs     # удаляет и все backing-индексы (необратимо)

# Добавить/удалить backing-индексы (операция только над метаданными):
# миграция обычного индекса в поток или отсоединение без удаления данных
POST /_data_stream/_modify
{
  "actions": [
    { "add_backing_index": { "data_stream": "nginx-logs", "index": "legacy-nginx-2023" } }
  ]
}
```

Backing-индекс, восстановленный из снапшота, подключают к data stream параметром `attach_to_data_stream: true` в Restore Snapshot API (см. [Snapshots и Disaster Recovery](./opensearch-disaster-recovery.md)).

## Troubleshooting

### Шаблон не применился к индексу

1. Проверить совпадение имени: `POST /_index_template/_simulate_index/<имя индекса>` — покажет применённый шаблон и `overlapping`.
2. Проверить `priority`: применяется единственный шаблон с наибольшим приоритетом, остальные не сливаются.
3. **Шаблон действует только на новые индексы.** Для существующих — `PUT /<index>/_settings` и `PUT /<index>/_mapping` вручную либо reindex.
4. `GET _index_template/<name>` — убедиться, что шаблон существует и не удалён.

### Ошибка 400 при создании шаблона: overlapping index patterns

1. Совпадающие паттерны двух шаблонов с одинаковым `priority` недопустимы — задать разные `priority`.
2. Проверить пересечение с существующими шаблонами: `GET _index_template`.

### Маппинг из component template не тот

1. Порядок `composed_of`: более поздний component template перекрывает предыдущие; inline-блок шаблона перекрывает всё.
2. `mappings`/`dynamic_templates`/`_meta` сливаются рекурсивно — совпавшие ключи перезаписываются, новые добавляются.
3. Конфликтующие `properties` одного поля в разных компонентах — оставить определение в одном компоненте.

### Индекс создался без шаблонных настроек

1. Настройки из `PUT /<index>` имеют приоритет над шаблоном — проверить запрос создания.
2. Некоторые настройки неизменяемы после создания (`number_of_shards`) — изменяются только reindex/shrink/split.

### ISM-политика не привязалась к новым индексам

1. Привязка выполняется блоком `ism_template` в самой политике; устаревшая настройка шаблона (`...index_state_management.policy_id`) и ключ ILM `index.lifecycle.name` для OpenSearch не работают.
2. Привязка действует только на индексы, созданные после появления привязки; существующие — через `POST /_plugins/_ism/add/<index>`. См. [ISM](./opensearch_ism_lifecycle.md).

### Ошибка «...matches with template [...] that creates data streams only»

1. Существует data-stream-шаблон, чей `index_patterns` совпадает с именем обычного индекса. Сузить паттерн data-stream-шаблона или переименовать индекс.

### Legacy `_template` vs `_index_template`

1. Использовать только `_index_template`; `_template` deprecated и не поддерживает component templates и `data_stream`.
2. При совпадении обеих форм приоритет у composable-шаблона.
3. При миграции — воспроизвести legacy-содержимое как composable-шаблон и удалить legacy.

## Best Practices

1. Разложить схему на component templates (mapping / settings / lifecycle) и собирать ими индексы через `composed_of` — переиспользование вместо копипасты.
2. Задавать `priority` явно; помнить, что применяется один шаблон, а совпадающие паттерны с равным приоритетом отклоняются.
3. Версионировать шаблоны (`version`, `_meta`) и хранить определения в Git; применять через CI.
4. Перед выкатом — `_simulate_index` на реальное имя нового индекса.
5. Шаблон — единственное место задания `number_of_shards` и привязки lifecycle; вручную при создании — только исключения.
6. Не плодить шаблоны с пересекающимися паттернами без различающихся приоритетов.
7. Для time-series — data stream + ISM вместо ручных алиасов ротации.

## Дополнительная информация

* [Index Templates (Elasticsearch)](../Elasticsearch/elasticsearch_index_templates.md) — общая теория composable-шаблонов и data streams.
* [ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md) — `ism_template`, rollover, ротация.
* [Mapping и индексация (OpenSearch)](./opensearch-mapping-and-indexing.md) — какие `mappings` закладывать в шаблоны.
* [Ingest Pipelines (OpenSearch)](./opensearch-ingest-pipelines.md) — `default_pipeline`/`final_pipeline` в settings шаблона.
* [Snapshots и Disaster Recovery](./opensearch-disaster-recovery.md) — `attach_to_data_stream` при restore.
