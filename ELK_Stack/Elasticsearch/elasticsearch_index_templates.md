# Index Templates и Data Streams

**Актуально для:** Elasticsearch 8.x / 9.x

> Руководство по шаблонам индексов и Data Streams. Рассматриваются Composable Index Templates, Component Templates, Data Streams и управление жизненным циклом.
>
> Связанные темы: маппинг и индексация — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md); ILM и DLM — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md).

## Определения

* **Index Template** — шаблон, определяющий settings, mappings и aliases для новых индексов, соответствующих паттерну.
* **Composable Index Template** — современный тип шаблона (7.8+), поддерживает приоритеты и наследование через Component Templates.
* **Legacy Index Template** — старый тип (`PUT _template/...`), deprecated начиная с 7.8; продолжает работать, но при совпадении приоритет имеет Composable Template.
* **Component Template** — переиспользуемый блок (mappings, settings, aliases), включается в Composable Index Template через `composed_of`.
* **Data Stream** — именованная абстракция для append-only time-series данных: единая точка записи и чтения над набором скрытых backing indices.
* **Backing Index** — физический скрытый индекс внутри Data Stream, именуется `.ds-<имя>-<дата>-<generation>`.
* **Write Index** — последний backing index Data Stream, в который выполняется запись; запись в остальные backing indices невозможна.
* **Generation** — порядковый номер backing index (000001, 000002, ...), инкрементируется при rollover.
* **Index Pattern** — wildcard-паттерн для matching индексов (например, `logs-*`).
* **Priority** — приоритет Composable Template: при конфликте нескольких шаблонов побеждает higher wins.

## Предварительные требования

```bash
export ES="https://localhost:9200"
export PASS="<пароль пользователя elastic>"
# Проверка доступности:
curl -u elastic:$PASS -k "$ES"   # → {"name" : "es-node-1", ..., "tagline" : "You Know, for Search"}
```

* Работающий кластер Elasticsearch 8.x / 9.x.
* Привилегии: `manage_index_templates` (или `manage` cluster) для управления шаблонами; `view_index_metadata` или `manage` index для чтения Data Streams.
* Примеры используют curl с basic-аутентификацией; при отключённом security уберите `-u` и `-k`.

## Как работают шаблоны

Шаблон применяется в момент создания индекса — явно (`PUT <index>`) или неявно (первая индексация документа в несуществующий индекс). Порядок разрешения конфигурации (от старшего к младшему):

1. Settings, переданные явно в запросе создания индекса.
2. Settings из Composable Index Template.
3. Settings из Component Templates — в порядке перечисления в `composed_of`, более поздние переопределяют более ранние.
4. Если ни один Composable Template не совпал — может примениться Legacy Template.
5. При совпадении нескольких Composable Templates побеждает шаблон с наибольшим `priority`.

Ключевое следствие: обновление шаблона не меняет существующие индексы — конфигурация применяется только к новым. Для Data Stream новая конфигурация появляется на следующем backing index после rollover.

### Коллизии со встроенными шаблонами

Elasticsearch поставляется со встроенными шаблонами (priority 100) для паттернов `logs-*-*`, `metrics-*-*`, `synthetics-*-*`, `profiling-*`, `security_solution-*-*` и других — они используются Elastic Agent и Fleet. Fleet-шаблоны имеют priority до 200. Правила для собственных шаблонов:

* Если используется Fleet/Elastic Agent — назначайте priority < 100 или непересекающийся паттерн.
* Если Fleet не используется — для паттерна `logs-*` назначайте priority 501+, чтобы перебить встроенный `logs-*-*`.
* Не используйте `@` в именах собственных шаблонов — коллизии с встроенными и Fleet-шаблонами.
* Начиная с 9.1 Fleet использует индексы `fleet-synced-integrations*` — избегайте этого имени.
* Отключить все встроенные шаблоны: `PUT /_cluster/settings {"persistent": {"stack.templates.enabled": false}}` (не рекомендуется).

## Composable Index Template

### Структура

```bash
PUT _index_template/my-template
{
  "index_patterns": ["logs-*", "metrics-*"],
  "composed_of": ["mappings-component", "settings-component"],
  "priority": 200,
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1
    },
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" }
      }
    },
    "aliases": {
      "all-logs": {}
    }
  },
  "version": 1,
  "_meta": {
    "description": "Template for application logs"
  }
}
# → {"acknowledged":true}
```

### Поля

| Поле | Описание |
|------|----------|
| `index_patterns` | Паттерны для matching новых индексов |
| `composed_of` | Список Component Templates |
| `priority` | Приоритет (higher wins) |
| `template` | Inline settings/mappings/aliases; переопределяет компоненты |
| `data_stream` | Пустой объект `{}` — шаблон создаёт Data Stream вместо обычного индекса |
| `version` | Версия для отслеживания (не влияет на применение) |
| `_meta` | Произвольные метаданные |
| `ignore_missing_component_templates` | Игнорировать отсутствующие компоненты в `composed_of` |

### Matching Priority

```
Template A: index_patterns=logs-*, priority=200
Template B: index_patterns=*-prod, priority=100

Index "logs-api-prod":
- Matches both templates
- Template A (priority=200) wins
- Template B ignored
```

## Component Template

### Примеры

```bash
# Mappings Component
PUT _component_template/logs-mappings
{
  "template": {
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" },
        "message": { "type": "text" },
        "service": {
          "properties": {
            "name": { "type": "keyword" },
            "version": { "type": "keyword" }
          }
        },
        "level": { "type": "keyword" }
      }
    }
  }
}
# → {"acknowledged":true}

# Settings Component для Data Stream (без rollover_alias — rollover управляется автоматически)
PUT _component_template/logs-settings
{
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1,
      "index.lifecycle.name": "logs-policy"
    }
  }
}
# → {"acknowledged":true}
```

Настройка `index.lifecycle.rollover_alias` требуется только для обычных индексов с ILM-rollover; для Data Stream её задавать не нужно — ротация backing indices управляется самим Data Stream.

### Использование в Index Template

```bash
PUT _index_template/logs
{
  "index_patterns": ["logs-*"],
  "composed_of": ["logs-mappings", "logs-settings"],
  "priority": 200
}
# → {"acknowledged":true}
```

## Legacy vs Composable

### Legacy (deprecated с 7.8)

```bash
PUT _template/legacy-template
{
  "index_patterns": ["logs-*"],
  "settings": { ... },
  "mappings": { ... }
}
```

### Composable (рекомендуется)

```bash
PUT _index_template/composable-template
{
  "index_patterns": ["logs-*"],
  "composed_of": ["mappings-comp", "settings-comp"],
  "priority": 200,
  "template": { ... }
}
```

### Отличия

| Критерий | Legacy | Composable |
|----------|--------|------------|
| Приоритет | insertion order (merge совпавших) | priority field |
| Наследование | Нет | Через Component Templates |
| Overlay | Нет | Да (template overlay) |
| Data Streams | Не поддерживает | Поддерживает (`data_stream: {}`) |
| Статус | Deprecated (7.8+) | Recommended |

## Data Stream

### Что такое Data Stream

```
Data Stream "logs-app"
├── .ds-logs-app-2026.08.01-000001  (backing index)
├── .ds-logs-app-2026.08.23-000002  (backing index)
└── .ds-logs-app-2026.08.24-000003  (current write index)
```

Требования к Data Stream:

* Обязательно совпадение имени потока с `index_patterns` шаблона, содержащего `"data_stream": {}`.
* Каждый документ должен содержать поле `@timestamp` (тип `date` или `date_nanos`); если шаблон не задаёт маппинг — Elasticsearch маппит `@timestamp` как `date` с настройками по умолчанию.
* Backing indices скрыты и создаются автоматически; один шаблон может обслуживать несколько Data Streams.

### Создание Data Stream

```bash
# Автоматически через Index Template + первая индексация
PUT _index_template/logs-app
{
  "index_patterns": ["logs-app"],
  "data_stream": {},
  "composed_of": ["logs-mappings", "logs-settings"],
  "priority": 200
}
# → {"acknowledged":true}

# Индексация создает Data Stream автоматически
POST logs-app/_doc
{
  "@timestamp": "2026-08-23T10:00:00Z",
  "message": "Application started",
  "service": { "name": "my-app" },
  "level": "INFO"
}
# → {"_index":".ds-logs-app-2026.08.23-000001","result":"created",...}
```

Ручное создание (шаблон должен существовать):

```bash
PUT _data_stream/logs-app
# → {"acknowledged":true}
```

### Ограничения записи

* Только append: обновление и удаление документов — через `POST /<data-stream>/_update_by_query` и `POST /<data-stream>/_delete_by_query`.
* Документ с явным `_id`: `PUT /<data-stream>/_create/<_id>` (поддерживается только `op_type=create`); в bulk — только action `create`.
* Запись идёт только в write index; прямая индексация в старые backing indices невозможна.
* Над write index нельзя выполнять clone, delete, shrink, split.
* Если нужен last-write-wins по одному `_id` — используйте обычный индекс с write alias, а не Data Stream.

### Rollover

```bash
# Manual rollover
POST logs-app/_rollover
{
  "conditions": {
    "max_age": "1d",
    "max_size": "50gb",
    "max_docs": 100000000
  }
}
# → {"acknowledged":true,"shards_acknowledged":true,"new_index":".ds-logs-app-2026.08.24-000002"}
```

В продакшене rollover обычно автоматизируется ILM/DLM — см. следующий раздел.

### Чтение и управление

```bash
# Информация о потоке: backing indices, generation, статус, применённые template и ILM policy
GET _data_stream/logs-app
# → {"data_streams":[{"name":"logs-app","timestamp_field":{"name":"@timestamp"},
#     "indices":[{"index_name":".ds-logs-app-2026.08.23-000001",...}],
#     "generation":1,"status":"GREEN","template":"logs-app","ilm_policy":"logs-policy",...}]}

# Статистика (docs, store size)
GET _data_stream/logs-app/_stats?human=true

# Удаление потока (удаляет все backing indices)
DELETE _data_stream/logs-app
# → {"acknowledged":true}
```

Дополнительные API (детали — в документации Elastic):

* `POST /_data_stream/_modify` — атомарные операции над backing indices (`add_backing_index`, `remove_backing_index`), например для подключения индекса, восстановленного из снапшота.
* `POST /_data_stream/_promote/<name>` — превращает CCR-реплицированный Data Stream в обычный (локально записываемый).
* `POST /_data_stream/_migrate/<alias>` — конвертирует индексный alias с write index в Data Stream; индексы alias становятся скрытыми backing indices.
* `PUT /<data-stream>/_mapping` — добавление новых полей во все backing indices (query-параметр `write_index_only=true` — только в write index). Изменение типа существующего поля требует reindex — см. [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md), сценарий 4.
* `POST /<data-stream>/_open` — переоткрыть закрытые backing indices (закрытые индексы не ищутся).

### Когда использовать Data Stream

| Use Case | Data Stream | Regular Index |
|----------|-------------|---------------|
| Time-series logs | ✅ | ❌ |
| Metrics (continuous) | ✅ | ❌ |
| Events (append-only) | ✅ | ❌ |
| User data (updatable) | ❌ | ✅ |
| Catalog (mutable) | ❌ | ✅ |

## Интеграция с ILM и DLM

Полные детали политик ILM, DLM, downsampling и SLM — в [ILM и политики хранения](./elasticsearch_ilm_and_retention.md). Здесь — только сторона шаблонов.

```bash
# 1. ILM Policy (пример Hot-Warm-Delete; детали — в файле ILM)
PUT _ilm/policy/logs-lifecycle
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_primary_shard_size": "50gb",
            "max_age": "30d"
          },
          "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "30d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 },
          "set_priority": { "priority": 50 }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": { "delete": {} }
      }
    }
  }
}
# → {"acknowledged":true}

# 2. Component Template с ILM
PUT _component_template/logs-settings
{
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1,
      "index.lifecycle.name": "logs-lifecycle"
    }
  }
}
# → {"acknowledged":true}

# 3. Index Template с Data Stream
PUT _index_template/logs-app
{
  "index_patterns": ["logs-app"],
  "data_stream": {},
  "composed_of": ["logs-mappings", "logs-settings"]
}
# → {"acknowledged":true}
```

Ключевые моменты:

* `index.lifecycle.name` — привязывает политику ILM к backing indices; применённая политика видна в поле `ilm_policy` ответа `GET _data_stream/<name>`.
* `index.lifecycle.rollover_alias` — только для обычных индексов с ручным ILM-rollover; для Data Stream не задаётся.
* Альтернатива ILM — DLM (введён в 8.11, tech preview, сейчас GA): настраивается одной командой `PUT /_data_stream/<name>/_lifecycle` или секцией `template.lifecycle` в шаблоне; см. [ILM и политики хранения](./elasticsearch_ilm_and_retention.md).
* ILM проверяет условия не мгновенно, а раз в 10 минут (`indices.lifecycle.poll_interval`).

## Управление шаблонами

### Просмотр

```bash
# Composable Templates
GET _index_template

# Конкретный template
GET _index_template/logs-app

# Component Templates
GET _component_template
```

### Обновление и удаление

```bash
# PUT по тому же имени перезаписывает шаблон (применяется к новым индексам)
PUT _index_template/logs-app
{
  "index_patterns": ["logs-*"],
  "composed_of": ["logs-mappings-v2", "logs-settings"],
  "priority": 200
}
# → {"acknowledged":true}

DELETE _index_template/logs-app
# → {"acknowledged":true}
```

Шаблон, используемый Data Stream, удалить нельзя — сначала удалите поток.

### Симуляция (валидация до применения)

```bash
# Что будет применено к конкретному имени индекса (разрешение приоритетов)
POST _index_template/_simulate_index/logs-app-2026.08.23

# Что применит существующий шаблон
POST _index_template/_simulate/logs-app

# Тест новой конфигурации без создания шаблона (тело = определение шаблона)
POST _index_template/_simulate
{
  "index_patterns": ["logs-*"],
  "composed_of": ["logs-mappings"],
  "priority": 200
}
```

### Проверка применения шаблона

```bash
# Settings и mappings созданного индекса
GET logs-app-2026.08.23/_settings
GET logs-app-2026.08.23/_mapping

# Для Data Stream — состав потока
GET _data_stream/logs-app
```

## Index Aliases

### Создание alias

```bash
POST /_aliases
{
  "actions": [
    {
      "add": {
        "index": "logs-2026.08",
        "alias": "logs-current"
      }
    }
  ]
}
# → {"acknowledged":true}
```

### Write alias (для rollover обычных индексов)

```bash
POST /_aliases
{
  "actions": [
    {
      "add": {
        "index": "logs-2026.08.23",
        "alias": "logs-app",
        "is_write_index": true
      }
    }
  ]
}
# → {"acknowledged":true}
```

### Alias с фильтром

```bash
POST /_aliases
{
  "actions": [
    {
      "add": {
        "index": "logs-*",
        "alias": "logs-errors",
        "filter": {
          "term": { "level": "ERROR" }
        }
      }
    }
  ]
}
# → {"acknowledged":true}
```

Aliases, объявленные в шаблоне (`template.aliases`), автоматически создаются на каждом новом индексе, созданном по шаблону.

## Best Practices

### Templates

1. **Используйте Composable Templates** — Legacy deprecated с 7.8.
2. **Component Templates для переиспользования** — DRY для mappings/settings.
3. **Priority для разрешения конфликтов** — explicit priority; учитывайте встроенные шаблоны (см. раздел про коллизии).
4. **Простые index_patterns** — избегайте complex wildcards.
5. **Version control** — храните templates в Git.
6. **Симуляция перед применением** — `_simulate_index` для проверки разрешения приоритетов.

### Data Streams

1. **Только для append-only данных** — не для updatable indices.
2. **ILM/DLM для rollover** — автоматическое управление lifecycle.
3. **Не индексируйте напрямую в backing index** — всегда через Data Stream.
4. **`@timestamp` обязателен** — в каждом документе.

### Naming Convention

```
Data Streams:
  <type>-<dataset>-<namespace>
  Примеры: logs-generic-default, metrics-system-default, logs-nginx-access-prod

Component Templates:
  {namespace}-mappings
  {namespace}-settings
  {namespace}-aliases

Index Templates:
  {namespace}-{dataset}
```

## Troubleshooting

### Template не применяется

```bash
# Что применится к индексу с таким именем (видны все совпавшие шаблоны)
POST _index_template/_simulate_index/logs-app-2026.08.23

# Проверить conflict resolution конкретного шаблона
POST _index_template/_simulate/logs-app

# Проверить, что индекс уже не существует (шаблон применяется только при создании)
GET _cat/indices/logs-*
```

Типичные причины: шаблон создан после индекса; более высокий priority у другого шаблона (в т.ч. встроенного Fleet); паттерн не совпадает; компонент в `composed_of` отсутствует (без `ignore_missing_component_templates`).

### Data Stream не создается

1. Проверить index template с `data_stream: {}` и совпадение имени потока с `index_patterns`.
2. Проверить наличие `@timestamp` в документе.
3. Проверить, что ILM policy существует (если задан `index.lifecycle.name`).
4. Проверить привилегии для создания индексов (`manage_index_templates`, auto-create).

### Backing index не ротируется

1. Проверить привязку политики: `GET _data_stream/<name>` → поле `ilm_policy`.
2. Проверить условия rollover в политике (`GET _ilm/policy/<name>`).
3. Учесть интервал проверки ILM — 10 минут (`indices.lifecycle.poll_interval`).
4. Для обычных индексов — проверить write alias и `index.lifecycle.rollover_alias`.

### Шаблон не удаляется

Шаблон, используемый существующим Data Stream, удалить нельзя: сначала `DELETE _data_stream/<name>`, затем `DELETE _index_template/<name>`.

## Граничные случаи

* **Обновление шаблона не ретроспективно**: существующие индексы сохраняют старую конфигурацию; для Data Stream новая схема появляется после rollover (миграция маппинга — см. [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md), сценарий 4).
* **Явные settings при создании индекса** переопределяют settings шаблона.
* **Порядок `composed_of` важен**: при конфликте настроек побеждает более поздний компонент.
* **Закрытые backing indices** не участвуют в поиске, пока не переоткрыты (`POST /<data-stream>/_open`).
* **Reindex в Data Stream** возможен только с `"op_type": "create"` — поток append-only.
* **Один шаблон — много потоков**: один и тот же шаблон могут использовать несколько Data Streams с разными именами.

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура индексов.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — маппинг и поля; TSDS-режим; миграция маппинга.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — ILM, DLM, rollover, downsampling, SLM.
* **[Rollup и Transform](./elasticsearch_rollup_transform.md)** — агрегация данных.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование шардов.
* **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — обработка документов.
