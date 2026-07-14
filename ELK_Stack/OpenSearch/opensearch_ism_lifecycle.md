# Управление жизненным циклом индексов (ISM) в OpenSearch

## Определения

**Index State Management (ISM)** — плагин OpenSearch, позволяющий автоматизировать задачи по управлению индексами (ротация, сжатие, удаление) на основе политик. Это аналог **Index Lifecycle Management (ILM)** в экосистеме Elasticsearch.

**Rollover (Ротация)** — процесс создания нового индекса для записи при выполнении определенных условий (размер, возраст, количество документов).

**Force Merge** — операция объединения сегментов индекса для уменьшения их количества и повышения производительности чтения.

## Основные концепции

### Фазы жизненного цикла индекса

Политика ISM обычно состоит из последовательных состояний (фаз), через которые проходит индекс:

1. **Горячая фаза (Hot)**:
   - Индексы активно используются для записи (индексации).
   - Обычно хранятся на быстрых дисках (SSD/NVMe).
   - Основная задача: выполнение **Rollover**.
2. **Тёплая фаза (Warm)**:
   - Индекс закрыт для записи, но доступен для частого поиска.
   - Оптимизация: уменьшение количества реплик (`replica_count`), выполнение `force_merge`.
   - Хранение на более дешевых HDD.
3. **Холодная фаза (Cold)**:
   - Данные используются редко (архив).
   - Индекс может быть мигрирован в объектное хранилище (S3/MinIO) через механизм **Cold Storage**.
4. **Удаление (Delete)**:
   - Окончательная очистка данных по истечении срока хранения.

---

## Практические сценарии

### 1. Политика долгосрочного хранения (3 года)

Сценарий для критически важных логов (например, `info-logs-*`), требующих хранения в течение 1095 дней.

```json
PUT /_plugins/_ism/policy/delete_info_1095d
{
  "policy": {
    "policy_id": "delete_info_1095d",
    "description": "Hot - Warm - Cold - Delete (3 года)",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "rollover": {
              "min_size": "50gb",
              "min_primary_shard_size": "10gb"
            }
          }
        ],
        "transitions": [
          {
            "state_name": "warm",
            "conditions": {
              "min_index_age": "7d"
            }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          {
            "replica_count": {
              "number_of_replicas": 1
            }
          },
          {
            "force_merge": {
              "max_num_segments": 1
            }
          },
          {
            "read_only": {}
          }
        ],
        "transitions": [
          {
            "state_name": "cold",
            "conditions": {
              "min_index_age": "30d"
            }
          }
        ]
      },
      {
        "name": "cold",
        "actions": [
          {
            "retry": {
              "count": 3,
              "backoff": "exponential",
              "delay": "1h"
            },
            "cold_migration": {}
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "1095d"
            }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          {
            "delete": {}
          }
        ]
      }
    ],
    "ism_template": {
      "index_patterns": ["info-logs-*"],
      "priority": 80
    }
  }
}
```

### 2. Политика кратковременного хранения (1 день)

Сценарий для отладочных логов (`debug-*`), которые занимают много места и не требуются для долгого хранения.

```json
PUT /_plugins/_ism/policy/delete_debug_1d
{
  "policy": {
    "policy_id": "delete_debug_1d",
    "description": "Удаление debug логов через 1 день",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "1d"
            }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          {
            "delete": {}
          }
        ]
      }
    ],
    "ism_template": {
      "index_patterns": ["debug-logs-*"],
      "priority": 100
    }
  }
}
```

### 3. Сжатие и архивация (Snapshot)

Если перед удалением данные необходимо сохранить во внешнем хранилище (S3/MinIO), в холодную фазу добавляется действие `snapshot`:

```json
{
  "name": "cold",
  "actions": [
    {
      "snapshot": {
        "repository": "my-s3-repository",
        "snapshot": "logs-archive-{{ctx.index}}"
      }
    }
  ]
}
```

---

## Дополнительная информация

### См. также

- **[Администрирование OpenSearch](./opensearch_administration.md)** — управление кластером и безопасность.
- **[Конвейер логов (Tutorial)](../Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)** — настройка сбора данных через Fluent Bit и Kafka.
