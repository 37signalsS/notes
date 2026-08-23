# Index Templates и Data Streams

> Руководство по шаблонам индексов и Data Streams. Рассматриваются Composable Index Templates, Component Templates, Data Streams и управление жизненным циклом.
>
> Связанные темы: маппинг и индексация — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md); ILM — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md).

## Определения

* **Index Template** — шаблон, определяющий settings, mappings и aliases для новых индексов, соответствующих паттерну.
* **Composable Index Template** — современный тип шаблона (7.8+), поддерживает приоритеты и наследование.
* **Legacy Index Template** — старый тип (deprecated в 8.x).
* **Component Template** — переиспользуемый компонент (mappings, settings, aliases), включается в Composable Index Template.
* **Data Stream** — абстракция для time-series данных, автоматически создающая backing indices.
* **Backing Index** — физический индекс внутри Data Stream.
* **Index Pattern** — wildcard-паттерн для matching индексов (например, `logs-*`).
* **Priority** — приоритет Composable Template (higher wins при конфликте).

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
```

### Компоненты

| Поле | Описание |
|------|----------|
| `index_patterns` | Паттерны для matching новых индексов |
| `composed_of` | Список Component Templates |
| `priority` | Приоритет (higher wins) |
| `template` | Inline settings/mappings/aliases |
| `version` | Версия для отслеживания |
| `_meta` | Произвольные метаданные |

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

# Settings Component
PUT _component/template/logs-settings
{
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1,
      "index.lifecycle.name": "logs-policy",
      "index.lifecycle.rollover_alias": "logs"
    }
  }
}
```

### Использование в Index Template

```bash
PUT _index_template/logs
{
  "index_patterns": ["logs-*"],
  "composed_of": ["logs-mappings", "logs-settings"],
  "priority": 200
}
```

## Legacy vs Composable

### Legacy (deprecated)

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
| Приоритет | insertion order | priority field |
| Наследование | Нет | Через Component Templates |
| Overlay | Нет | Да (template overlay) |
| Статус | Deprecated | Recommended |

## Data Stream

### Что такое Data Stream

```
Data Stream "logs-app"
├── .ds-logs-app-2026.08.01-000001  (backing index)
├── .ds-logs-app-2026.08.23-000002  (backing index)
└── .ds-logs-app-2026.08.24-000003  (current write index)
```

### Создание Data Stream

```bash
# Автоматически через Index Template + write alias
PUT _index_template/logs-app
{
  "index_patterns": ["logs-app"],
  "data_stream": {},
  "composed_of": ["logs-mappings", "logs-settings"],
  "priority": 200
}

# Индексация создает Data Stream автоматически
POST logs-app/_doc
{
  "@timestamp": "2026-08-23T10:00:00Z",
  "message": "Application started",
  "service": { "name": "my-app" },
  "level": "INFO"
}
```

### Ручное создание

```bash
PUT _data_stream/logs-app
```

### Backing Index

```bash
# Список backing indices
GET _data_stream/logs-app

# Детали backing index
GET .ds-logs-app-*/
```

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
```

### Когда использовать Data Stream

| Use Case | Data Stream | Regular Index |
|----------|-------------|---------------|
| Time-series logs | ✅ | ❌ |
| Metrics (continuous) | ✅ | ❌ |
| Events (append-only) | ✅ | ❌ |
| User data (updatable) | ❌ | ✅ |
| Catalog (mutable) | ❌ | ✅ |

## ILM Integration

### Полная настройка с ILM

```bash
# 1. Создать ILM Policy
PUT _ilm/policy/logs-lifecycle
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "50GB",
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
        "actions": {
          "delete": {}
        }
      }
    }
  }
}

# 2. Component Template с ILM
PUT _component_template/logs-settings
{
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1,
      "index.lifecycle.name": "logs-lifecycle",
      "index.lifecycle.rollover_alias": "logs-app"
    }
  }
}

# 3. Index Template с Data Stream
PUT _index_template/logs-app
{
  "index_patterns": ["logs-app"],
  "data_stream": {},
  "composed_of": ["logs-mappings", "logs-settings"]
}
```

## Template Management

### Просмотр шаблонов

```bash
# Composable Templates
GET _index_template

# Конкретный template
GET _index_template/logs-app

# Component Templates
GET _component_template
```

### Обновление шаблона

```bash
PUT _index_template/logs-app
{
  "index_patterns": ["logs-*"],
  "composed_of": ["logs-mappings-v2", "logs-settings"],
  "priority": 200
}
```

### Удаление шаблона

```bash
DELETE _index_template/logs-app
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
```

### Write alias (для Data Stream rollover)

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
```

## Best Practices

### Templates

1. **Используйте Composable Templates** — Legacy deprecated
2. **Component Templates для переиспользования** — DRY для mappings/settings
3. **Priority для разрешения конфликтов** — explicit priority
4. **Простые index_patterns** — избегайте complex wildcards
5. **Version control** — храните templates в Git

### Data Streams

1. **Только для append-only данных** — не для updatable indices
2. **ILM для rollover** — автоматическое управление lifecycle
3. **Write alias** — обязателен для rollover
4. **Не индексируйте напрямую в backing index** — всегда через Data Stream alias

### Naming Convention

```
Data Streams:
  logs-{namespace}-{dataset}
  metrics-{namespace}-{dataset}

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
# Проверить matching
GET _index_template/simulate_index/logs-app-2026.08.23

# Проверить conflict resolution
GET _index_template/simulate/{template-name}
```

### Data Stream не создается

1. Проверить index template с `data_stream: {}`
2. Проверить write alias настроен
3. Проверить ILM policy существует
4. Проверить permissions для создания индексов

### Backing index не ротируется

1. Проверить rollover conditions
2. Проверить ILM policy
3. Проверить write index alias

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура индексов.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — маппинг и поля.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — rollover и lifecycle.
* **[Rollup и Transform](./elasticsearch_rollup_transform.md)** — агрегация данных.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование шардов.
* **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — обработка документов.
