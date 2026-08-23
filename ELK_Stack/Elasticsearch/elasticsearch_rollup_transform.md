# Rollup и Transform: Агрегация исторических данных

> Руководство по механизмам Rollup и Transform для агрегации и хранения исторических данных. Рассматриваются use cases, API и отличия от downsampling в TSDS.
>
> Связанные темы: ILM — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md); TSDS — [Mapping and Indexing](./elasticsearch_mapping_and_indexing.md).

## Определения

* **Rollup** — механизм периодической агрегации сырых данных в компактный rollup-индекс. Сохраняет только агрегаты (min, max, avg, sum), исходные данные удаляются.
* **Transform** — механизм создания pivot или latest-представления данных из одного индекса в другой. Может быть continuous.
* **Rollup Index** — целевой индекс для rollup, содержащий только агрегированные данные.
* **Pivot Transform** — группировка и агрегация (аналог GROUP BY в SQL)
* **Latest Transform** — последнее значение для каждого ключа (аналог DISTINCT ON)
* **Rollup Job** — фоновый процесс, выполняющий периодическую агрегацию.

## Архитектура

### Rollup Workflow

```
Raw Data (logs-per-second)
        │
        ▼ (cron schedule)
   Rollup Job
        │
        ▼
Rollup Index (logs-per-minute or logs-per-hour)
        │
        ▼ (after retention)
     Deleted
```

### Transform Workflow

```
Source Index (raw)
        │
        ▼ (continuous or batch)
   Transform
        │
        ▼
Destination Index (aggregated/pivoted)
```

## Rollup

### Создание Rollup Job

```bash
PUT _rollup/job/daily-logs-summary
{
  "index_pattern": "logs-*",
  "rollup_index": "logs-rollup-daily",
  "cron": "0 0 * * * ?",
  "page_size": 1000,
  "groups": {
    "date_histogram": {
      "field": "@timestamp",
      "calendar_interval": "1h"
    },
    "terms": {
      "fields": ["service.name", "status"]
    }
  },
  "metrics": [
    {
      "field": "response_time",
      "metrics": ["min", "max", "sum", "avg", "value_count"]
    },
    {
      "field": "bytes",
      "metrics": ["sum"]
    }
  ],
  "timeout": "120s"
}
```

### Запуск Rollup Job

```bash
# Запуск вручную
POST _rollup/job/daily-logs-summary/_start

# Остановка
POST _rollup/job/daily-logs-summary/_stop

# Статус
GET _rollup/job/daily-logs-summary/_status
```

### Поиск в Rollup данных

```bash
GET _rollup_search
{
  "index": "logs-rollup-daily",
  "size": 0,
  "aggregations": {
    "hourly": {
      "date_histogram": {
        "field": "@timestamp",
        "fixed_interval": "1d"
      },
      "aggs": {
        "avg_response": {
          "avg": {
            "field": "response_time.avg"
          }
        }
      }
    }
  }
}
```

### Структура Rollup индекса

```
logs-rollup-daily
├── @timestamp (1h granularity)
├── service.name (term)
├── status (term)
├── response_time.min (double)
├── response_time.max (double)
├── response_time.sum (double)
├── response_time.avg (double)
├── response_time.value_count (long)
└── bytes.sum (long)
```

**Важно:** Rollup-индекс хранит только агрегаты. Исходные документы невозможно восстановить.

### Ограничения Rollup

- Только числовые поля для metrics
- Только date_histogram, histogram, terms для groups
- Rollup job не может изменять существующие данные (append-only)
- Rollup-индекс read-only
- Нет поддержки nested objects

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
      "service": {
        "terms": {
          "field": "service.name"
        }
      },
      "@timestamp": {
        "date_histogram": {
          "field": "@timestamp",
          "calendar_interval": "1d"
        }
      }
    },
    "aggregations": {
      "avg_response_time": {
        "avg": {
          "field": "response_time"
        }
      },
      "total_requests": {
        "value_count": {
          "field": "_id"
        }
      },
      "max_bytes": {
        "max": {
          "field": "bytes"
        }
      }
    }
  },
  "description": "Daily summary by service"
}
```

### Latest Transform

```bash
PUT _transform/latest-status-by-host
{
  "source": {
    "index": "host-metrics-*"
  },
  "dest": {
    "index": "latest-host-status"
  },
  "frequency": "1m",
  "sync": {
    "time": {
      "field": "@timestamp",
      "delay": "30s"
    }
  },
  "latest": {
    "unique_key": ["host.name"],
    "sort": "@timestamp"
  },
  "description": "Latest metrics per host"
}
```

### Управление Transform

```bash
# Запуск
POST _transform/service-daily-summary/_start

# Остановка
POST _service-daily-summary/_stop

# Статус
GET _transform/service-daily-summary/_stats

# Обновление (create new with same ID)
PUT _transform/service-daily-summary
{
  ... updated config ...
}

# Удаление
DELETE _transform/service-daily-summary
```

## Rollup vs Transform vs TSDS

| Критерий | Rollup | Transform | TSDS |
|----------|--------|-----------|------|
| Агрегация | Да (min/max/avg) | Да (любые) | Только avg |
| Continuous | Нет (cron) | Да | Нет |
| Исходные данные | Удаляются | Сохраняются | Сохраняются |
| Масштаб | Огромный (1000x) | Умеренный | Умеренный |
| Использование | Долгосрочная аналитика | Отчеты, latest views | Метрики временных рядов |
| Overhead | Низкий | Средний | Минимальный |

## Use Cases

### Rollup: Долгосрочная аналитика

```
Raw logs: 100GB/day × 30 days = 3TB
Rollup:   1GB/day × 365 days = 365GB

Экономия: ~10x на хранение при потере granularity
```

Идеально для:
- Compliance (хранение агрегатов 1+ год)
- Capacity planning (тренды по дням/неделям)
- SLA reporting (uptime по месяцам)

### Transform: Отчеты и latest views

- Dashboard с текущим статусом всех серверов
- Отчеты по сервисам (daily summary)
- Дедупликация данных (latest only)

### TSDS: Метрики временных рядов

- Мониторинг (CPU, memory, latency)
- Downsampling через auto-rollover
- Интеграция с Kibana TSDS visualizations

## Мониторинг

### Rollup Job Status

```bash
GET _rollup/job/_stats
```

Метрики:
- `job_status`: `indexing`, `started`, `failed`, `stopped`
- `documents_processed`
- `pages_processed`
- `trigger_count`
- `search_failures`

### Transform Stats

```bash
GET _transform/_stats
```

Метрики:
- `state`: `indexing`, `started`, `stopped`, `failed`
- `documents_indexed`
- `documents_processed`
- `exponential_avg_checkpoint_duration_ms`
- `search_total`
- `index_total`

## Best Practices

1. **Используйте Rollup для данных старше 30 дней** — когда детали уже не нужны
2. **Transform для real-time отчетов** — когда нужна актуальная агрегация
3. **Настройте retention** на rollup/transform индексы через ILM
4. **Мониторьте lag** — если transform не успевает, растет отставание
5. **Тестируйте на подмножестве** — `page_size` и `frequency` подбирайте под нагрузку
6. **Используйте ILM** для автоматического создания transform/rollup индексов
7. **Бэкапьте конфиги** — храните _rollup и _transform определения в Git

## Ограничения и Gotchas

- **Rollup:** нельзя изменить существующий job — нужно создать новый
- **Transform:** destination индекс создается автоматически, маппинг определяется по pivot/latest
- **Transform:** при ошибке sync time — данные могут быть неполными
- **Rollup:** только для time-based индексов (date_histogram обязателен)
- **Производительность:** rollup job выполняет поиск по сырым данным — учитывайте нагрузку

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура и возможности.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — интеграция Rollup/Transform с ILM.
* **[Mapping and Indexing](./elasticsearch_mapping_and_indexing.md)** — TSDS для downsampling.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — расчет ресурсов для Rollup.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — мониторинг job статуса.
* **[Alerting](./elasticsearch_alerting.md)** — алертинг на ошибки jobs.
