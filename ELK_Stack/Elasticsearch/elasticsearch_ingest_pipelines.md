# Ingest Pipelines: Обработка документов перед индексацией

> Систематическое руководство по Ingest Node и пайплайнам обработки документов в Elasticsearch. Рассматриваются процессоры, обработка ошибок, тестирование и выбор между Ingest Node, Logstash и внешними обработчиками.
>
> Связанные темы: парсинг в Logstash — [Logstash Pipelines](../Logstash/logstash_pipelines.md); маппинг и индексация — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md); ILM — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md); [Grok и Dissect Patterns](../grok_dissect_patterns.md); [ELK стек: Обзор](../elk_stack_overview.md).

## Определения

* **Ingest Node** — узел Elasticsearch с ролью `ingest` (по умолчанию все узлы), который выполняет предварительную обработку документов через pipelines перед индексацией.
* **Pipeline** — последовательность процессоров (`processors`), применяемых к документу. Определяется через API `PUT _ingest/pipeline/<id>`.
* **Processor** — единица обработки, выполняющая одно действие над документом (парсинг, обогащение, преобразование полей).
* **Ingest Attachment** — плагин для индексации содержимого файлов (PDF, DOCX) через Apache Tika.
* **Simulate API** — эндпоинт `_ingest/pipeline/_simulate` для тестирования пайплайнов без реальной записи.

## Архитектура

### Как работает Ingest

```
Пользователь/Beats → [HTTP API] → [Ingest Node] → [Data Node] → Индексация
                                  ↓
                            Pipeline процессоры
```

Ingest Node перехватывает bulk-запросы, применяет указанный пайплайн (или стандартный), затем передает обработанные документы на Data Node.

### Назначение пайплайна

```bash
# Глобальный для индекса (default_pipeline)
PUT /my-index
{
  "settings": {
    "default_pipeline": "my-pipeline"
  }
}

# Через параметр запроса
POST /my-index/_doc?pipeline=my-pipeline
{ "message": "..." }

# В Bulk API
POST /_bulk?pipeline=my-pipeline
{ "index": { "_index": "my-index" } }
{ "message": "..." }
```

## Основные процессоры

### Парсинг и разбор

| Процессор | Назначение | Когда использовать |
|-----------|------------|-------------------|
| `grok` | Регулярные выражения для структурирования строк | Сложные логи с вариативным форматом |
| `dissect` | Шаблонное разбиение строк по разделителям | Формат фиксирован (syslog, CSV) — быстрее grok |
| `csv` | Парсинг CSV-данных | Данные в CSV формате |
| `json` | Парсинг JSON-строки в поле | Вложенный JSON как строка |
| `kv` | Key-Value парсинг | `key1=value1, key2=value2` |
| `dot_expander` | Раскрытие точечной нотации | `{"a.b": 1}` → `{"a":{"b":1}}` |

### Преобразование полей

```json
{
  "set": {
    "field": "status",
    "value": "{% raw %}{{level}}{% endraw %}"
  },
  "copy": {
    "from": "message",
    "to": "original_message"
  },
  "rename": {
    "field": "old_field",
    "target_field": "new_field"
  },
  "remove": {
    "field": ["temp_field", "debug_info"]
  },
  "lowercase": {
    "field": "hostname"
  },
  "trim": {
    "field": "message"
  }
}
```

### Работа с датами

```json
{
  "date": {
    "field": "timestamp",
    "target_field": "@timestamp",
    "formats": ["ISO8601", "dd/MMM/yyyy:HH:mm:ss Z"],
    "timezone": "Europe/Moscow",
    "locale": "en"
  }
}
```

**Важно:** Порядок форматов влияет на результат — Elasticsearch пробует последовательно. ISO8601 обычно первый.

### Обогащение (Enrichment)

```json
{
  "geoip": {
    "field": "client_ip",
    "target_field": "geo",
    "properties": ["city_name", "country_name", "location"],
    "ignore_missing": true
  },
  "user_agent": {
    "field": "agent_string",
    "target_field": "user_agent",
    "ignore_missing": true
  },
  "enrich": {
    "policy_name": "ip-enrichment-policy",
    "field": "source.ip",
    "target_field": "threat_intel"
  }
}
```

**Enrich Processor** требует предварительно созданной enrich policy и enrich index — данные подтягиваются из специального индекса во время индексации.

### Условная обработка

```json
{
  "if": "ctx.level == 'ERROR'",
  "then": [
    {
      "set": {
        "field": "priority",
        "value": "high"
      }
    }
  ],
  "else": [
    {
      "set": {
        "field": "priority",
        "value": "normal"
      }
    }
  ]
}
```

Также поддерживаются Painless-скрипты:

```json
{
  "script": {
    "lang": "painless",
    "source": "ctx.duration_ms = ctx.duration_ns / 1000000;"
  }
}
```

## Пример: полный пайплайн для веб-логов

```bash
PUT _ingest/pipeline/apache-logs
{
  "description": "Parse Apache combined log format",
  "processors": [
    {
      "grok": {
        "field": "message",
        "patterns": [
          "{% raw %}\\[%{HTTPDATE:timestamp}\\] \"%{WORD:method} %{URIPATH:path} %{DATA:protocol}\" %{INT:status} %{INT:bytes} %{QS:referrer} %{QS:user_agent}{% endraw %}"
        ],
        "pattern_definitions": {
          "QS": "\"?.*\"?"
        },
        "ignore_failure": true
      }
    },
    {
      "date": {
        "field": "timestamp",
        "target_field": "@timestamp",
        "formats": ["dd/MMM/yyyy:HH:mm:ss Z"],
        "ignore_failure": true
      }
    },
    {
      "convert": {
        "field": "status",
        "type": "integer",
        "ignore_failure": true
      }
    },
    {
      "convert": {
        "field": "bytes",
        "type": "long",
        "ignore_failure": true
      }
    },
    {
      "user_agent": {
        "field": "user_agent",
        "ignore_missing": true,
        "ignore_failure": true
      }
    },
    {
      "remove": {
        "field": ["message", "timestamp"],
        "ignore_failure": true
      }
    }
  ],
  "on_failure": [
    {
      "set": {
        "field": "_ingest.failure",
        "value": "{% raw %}{{ _ingest.on_failure_processor_type }}{% endraw %}"
      }
    },
    {
      "set": {
        "field": "_ingest.parse_status",
        "value": "failed"
      }
    }
  ]
}
```

## Тестирование пайплайнов

```bash
POST _ingest/pipeline/apache-logs/_simulate
{
  "docs": [
    {
      "_index": "logs",
      "_id": "1",
      "_source": {
        "message": "[25/Aug/2026:14:30:00 +0300] \"GET /api/users HTTP/1.1\" 200 1234 \"-\" \"Mozilla/5.0\""
      }
    }
  ]
}
```

## Обработка ошибок

### Механика `on_failure`

Каждый процессор может иметь `on_failure` блок. Если он не указан и `ignore_failure` не `true`, весь документ падает с ошибкой.

```json
{
  "grok": {
    "field": "message",
    "patterns": ["%{TIMESTAMP_ISO8601:ts} %{LOGLEVEL:level}"],
    "on_failure": [
      {
        "set": {
          "field": "parse_error",
          "value": "{% raw %}{{ _ingest.on_failure_message }}{% endraw %}"
        }
      }
    ]
  }
}
```

### DLQ (Dead Letter Queue) для ingest

Документы, не прошедшие обработку, можно маршрутизировать в отдельный индекс через `on_failure` на уровне пайплайна.

## Производительность и масштабирование

### Ingest Node vs Logstash

| Критерий | Ingest Node | Logstash |
|----------|-------------|----------|
| Простота развертывания | Встроен в ES | Отдельный сервис |
| Потребление ресурсов | Минимальное (часть JVM) | Собственная JVM |
| Буферизация | Нет (synchronous) | PQ (persistent queue) |
| Сложная логика | Ограничена процессорами | Полная (Ruby, плагины) |
| Внешние источники | Enrich из индексов | Любые (JDBC, HTTP, Kafka) |
| Масштабирование | Вместе с ES кластером | Независимое |

### Когда использовать Ingest Node

- Простой парсинг и обогащение
- Нет необходимости в буферизации
- Минимальная инфраструктура — приоритет
- Beats → Elasticsearch напрямую

### Когда использовать Logstash

- Сложная трансформация данных
- Интеграция с внешними системами (Kafka, JDBC, S3)
- Необходимость буферизации при пиках
- Сложная обработка ошибок с DLQ

## Паттерны и Best Practices

1. **Используйте `ignore_failure: true`** для необязательных процессоров (geoip, user_agent)
2. **`dissect` вместо `grok`** для фиксированных форматов — в 10-100 раз быстрее
3. **Тестируйте через `_simulate`** перед применением в production
4. **Версионируйте пайплайны** — храните конфигурации в Git
5. **Мониторьте ingest pipeline** через `_nodes/stats/ingest` — метрики времени обработки
6. **Ограничьте размер Painless-скриптов** — они выполняются в той же JVM, могут влиять на latency

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера, роли узлов.
* **[Logstash: Обзор](../Logstash/logstash_overview.md)** — альтернатива Ingest Pipelines для сложной обработки.
* **[Logstash: Конвейеры и фильтры](../Logstash/logstash_pipelines.md)** — grok, dissect, mutate фильтры.
* **[Grok и Dissect Patterns](../grok_dissect_patterns.md)** — коллекция паттернов для парсинга.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — маппинг и структуры данных.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — жизненный цикл индексов.
