# Elasticsearch: Траблшутинг индексации и сегментов

> Заметка посвящена диагностике проблем индексации: медленной записи, перегрева heap, merge throttling, роста сегментов и translog-заторов. Базовые понятия кластера (шарды, refresh, flush, translog) описаны в [обзоре Elasticsearch](./elasticsearch_overview.md); настройка жизненного цикла — в [ILM и политиках хранения](./elasticsearch_ilm_and_retention.md).

## Определения

* **Merge (Слияние)** — фоновый процесс объединения мелких сегментов Lucene в крупные. По умолчанию работает в режиме `tiered`, ограничивая скорость записи через `merge.policy.*` и `merge.scheduler.*`.
* **Merge Throttling (Ограничение слияний)** — механизм, при котором Lucene снижает приоритет merge-потоков при высокой нагрузке на индексацию, чтобы не конкурировать за I/O и CPU с записью новых документов.
* **Segment (Сегмент)** — минимальная неделимая единица хранения Lucene. Каждый шард — набор неизменяемых сегментов; при индексации новые документы попадают в буфер, а затем в новый сегмент после refresh.
* **Translog (Журнал упреждающей записи)** — WAL для гарантии durability. При переполнении (`index.translog.flush_threshold.size`) или по расписанию выполняется flush — сброс сегментов на диск и обрезка translog.
* **Indexing Buffer (Буфер индексации)** — in-memory область на шард, куда документы попадают перед refresh. При переполнении (`indices.memory.index_buffer_size`) Elasticsearch принудительно выполняет refresh или отклоняет запись (`409`).
* **Refresh Interval** — период, через который содержимое буфера становится видимым для поиска (по умолчанию `1s`). Увеличение интервала снижает количество сегментов и нагрузку на merge.
* **Circuit Breaker (Размыкатель)** — защита JVM heap от OOM. Существуют breaker'ы для запросов (`request`), aggregations (`fielddata`), parent (`in_flight_requests` + `accounting`) и accounting (`indices.breaker.total.limit`).
* **Thread Pool (Пул потоков)** — очередь задач на индексацию (`write`), поиск (`search`), merge (`merge`). При переполнении (`queue_size` + `type: fixed`) задачи отклоняются с `429`.
* **Force Merge** — принудительное слияние сегментов до заданного числа (`max_num_segments`). Для индексов, куда запись завершена, это уменьшает количество открытых файлов и ускоряет поиск.
* **Segment Replication (OpenSearch)** — репликация готовых сегментов Lucene с primary на реплики, снижающая нагрузку на CPU при индексации. В Elasticsearch аналогом является стандартная document-level репликация.

## Основные концепции

### Жизненный цикл документа и сегментов

1. Документ попадает в **memory buffer** и **translog**.
2. **Refresh** создает новый сегмент Lucene из буфера. Документ становится видимым для поиска.
3. **Merge** фоновыми потоками сливает мелкие сегменты в крупные, удаляя помеченные на удаление документы.
4. **Flush** сбрасывает сегменты на диск и обрезает translog.

Ключевое последствие: сегменты неизменяемы. Частые точечные обновления создают множество мелких сегментов, что тормозит поиск и увеличивает нагрузку на merge.

### Настройки merge и производительности

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `index.merge.policy.max_merged_segment` | Максимальный размер сегмента после merge | `5gb` — предотвращает создание гигантских сегментов, которые долго открывать |
| `index.merge.policy.segments_per_tier` | Число сегментов одного размера перед merge | `10.0` — баланс между скоростью записи и числом сегментов |
| `index.merge.policy.max_threshold` | Максимальное число сегментов на уровне до merge | Увеличьте для hot-индексов с высокой нагрузкой |
| `index.merge.scheduler.max_thread_count` | Максимум merge-потоков на шард | `1` — безопасно для HDD; `2` — для быстрых SSD/NVMe |
| `index.merge.scheduler.max_merge_count` | Общий лимит merge-заданий на узел | `6` — ограничивает суммарную нагрузку на I/O |
| `index.refresh_interval` | Частота создания новых сегментов | `30s` — `60s` для логов; `-1` для массовой загрузки |

### Мониторинг индексации

| Метрика | API | Норма |
| :--- | :--- | :--- |
| Скорость индексации | `GET _cat/nodes?v&h=name,indexing.index_total,indexing.index_time` | Зависит от hardware |
| Очередь merge | `GET _cat/thread_pool/search,merge?v` | `active` merge-потоков < `max_thread_count` |
| Размер сегментов | `GET _cat/segments/<index>?v&bytes=gb` | Количество сегментов < 50 на шард |
| Translog | `GET _nodes/stats/indices/translog` | `operations` растет, но `size` ограничен flush threshold |
| Indexing Buffer | `GET _nodes/stats/indices/jvm` | `buffer_pools.indexing.peak_usage` < лимита |
| Circuit Breaker | `GET /_nodes/stats/breakers` | `tripped` = 0; `memory_used` < `limit` |
| Write rejections | `GET _cat/nodes?v&h=name,indices.search.rejections` | 0 в стабильном состоянии |

### Типовые паттерны проблем

**Merge Storm**: фоновые merge-потоки потребляют всю I/O, замедляя запись и поиск. Проявляется в `iostat` как 100% `%util` диска и в `_cat/thread_pool` как активные `merge`-потоки.

**Indexing Buffer Overflow**: буфер переполняется из-за слишком быстрой индексации. Признак — ошибки `409` или принудительные refresh.

**Translog Overflow**: при быстрой записи translog растет быстрее, чем flush его обрезает. Признак — `translog.operations` в десятках миллионов на шард.

**Circuit Breaker Trip**: крупная агрегация или fielddata превышают лимит heap. Признак — ошибки `429` с `circuit_breaking_exception`.

**Mapping Explosion**: динамическое создание тысяч полей в произвольном JSON. Признак — ошибка `limit of total fields [1000] has been exceeded`.

## Практические сценарии

**Предварительные требования для всех сценариев**:

```bash
export ES="https://localhost:9200"
export PASS="<пароль пользователя elastic>"
curl -u elastic:$PASS -k "$ES"   # → {"name" : "es-node-1", ..., "tagline" : "You Know, for Search"}
```

### 1. Диагностика медленной индексации

Сценарий: приложение пишет логи в Elasticsearch, но задержка между отправкой и появлением документа в поиске превышает 5 секунд.

```bash
# 1. Проверить скорость индексации и очереди
curl -u elastic:$PASS -k "$ES/_cat/nodes?v&h=name,indexing.index_total,indexing.index_time,indexing.index_current"

# 2. Проверить thread pool write
curl -u elastic:$PASS -k "$ES/_cat/thread_pool/write?v"
# → queue tasks rejected active priority
```

Анализ результатов:

| Показатель | Признак проблемы | Действие |
| :--- | :--- | :--- |
| `indexing.index_time` высокий, `index_total` низкий | Медленная запись на диск | Проверьте I/O (`iostat -x 1`), увеличьте `refresh_interval` |
| `queue` в write thread pool > 0 | Переполнена очередь записи | Уменьшите размер bulk-пакетов, увеличьте `refresh_interval` |
| `rejected` > 0 | Отклонены задачи индексации | Увеличьте `indices.memory.index_buffer_size` или добавьте узлы |
| `active` много | Много параллельных записей | Ограничьте конкурентность на стороне отправителя |

```bash
# 3. Проверить hot threads на узле данных
curl -u elastic:$PASS -k "$ES/_nodes/hot_threads?threads=5&type=merge"
# → Стеки потоков merge, потребляющих CPU
```

### 2. Разрешение merge throttling

Сценарий: индексация замедлилась, `iostat` показывает 100% utilization диска, merge-потоки активны.

```bash
# 1. Оценить нагрузку merge
curl -u elastic:$PASS -k "$ES/_cat/thread_pool/merge?v"

# 2. Временно ограничить merge
curl -u elastic:$PASS -k -X PUT "$ES/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "indices.merge.scheduler.max_thread_count": 1,
    "indices.merge.scheduler.max_merge_count": 4
  }
}'
# → {"acknowledged":true}
```

Пояснения:

* `max_thread_count: 1` — одна merge-задача на шард одновременно. Для HDD это стандарт; для NVMe можно оставить `2`.
* `max_merge_count: 4` — не более 4 merge-заданий на весь узел одновременно. Это оставляет ресурсы для индексации.
* Для горячих индексов с высокой нагрузкой можно использовать `"index.merge.policy.segments_per_tier": 15.0` — большее число сегментов перед merge снижает частоту слияний.

```bash
# 3. Принудительный merge завершенных индексов (например, после миграции)
curl -u elastic:$PASS -k -X POST "$ES/old-index/_forcemerge?max_num_segments=1"
# → {"_shards":{"total":2,"successful":2,"failed":0}}
```

**Важно**: не вызывайте `_forcemerge` на индексах, куда продолжается запись. Это создает огромные сегменты, которые потом невозможно эффективно сливать.

### 3. Диагностика проблем с translog

Сценарий: индексы зависают при перезапуске узла, время восстановления шардов превышает 30 минут.

```bash
# 1. Проверить размер translog на шардах
curl -u elastic:$PASS -k "$ES/_nodes/stats/indices/translog?pretty"
```

```json
{
  "nodes": {
    "node_id": {
      "indices": {
        "translog": {
          "operations": 15234,
          "size": "2.1gb",
          "unreferenced": {
            "operations": 0,
            "size": "0b"
          }
        }
      }
    }
  }
}
```

| Показатель | Норма | Проблема |
| :--- | :--- | :--- |
| `operations` | < 100 000 на шард | > 1M — translog слишком большой, восстановление будет долгим |
| `size` | < 512 МБ | > 2 ГБ — при сбое восстанавливается долго |
| `unreferenced` | 0 | > 0 — обрезанный translog не удален |

```bash
# 2. Настроить flush threshold
curl -u elastic:$PASS -k -X PUT "$ES/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "index.translog.flush_threshold.size": "512mb",
    "index.translog.flush_threshold.period": "5m"
  }
}'
```

Пояснения:

* `flush_threshold.size: 512mb` — flush происходит, когда translog превышает 512 МБ. По умолчанию 512 МБ, но при быстрой индексации может потребоваться уменьшение.
* `flush_threshold.period: 5m` — принудительный flush каждые 5 минут, даже если translog не заполнился.
* Для production с быстрой записью рекомендуется `200mb` — `512mb`.

```bash
# 3. Проверить unreferenced translog (фрагменты, которые можно удалить)
curl -u elastic:$PASS -k -X POST "$ES/_flush"
# → {"_shards":{"total":2,"successful":2,"failed":0}}
```

### 4. Управление refresh interval

Сценарий: массовая загрузка исторических данных (100 ГБ), поиск не нужен в процессе.

```bash
# 1. Отключить автorefresh перед загрузкой
curl -u elastic:$PASS -k -X PUT "$ES/historical-logs/_settings" \
-H 'Content-Type: application/json' -d'
{
  "index": { "refresh_interval": "-1" }
}'
# → {"acknowledged":true}
```

```bash
# 2. Выполнить bulk-загрузку (пример в заметке о маппинге)
# ... загрузка завершена ...

# 3. Вернуть refresh и принудительно выполнить его
curl -u elastic:$PASS -k -X PUT "$ES/historical-logs/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "refresh_interval": "30s" } }'

curl -u elastic:$PASS -k -X POST "$ES/historical-logs/_refresh"
# → {"_shards":{"total":2,"successful":2,"failed":0}}
```

Эффект: при отключенном refresh индексация ускоряется в 2–3 раза за счет отсутствия частого создания сегментов. После загрузки возвращайте `refresh_interval` не менее `30s` — это снижает фоновую нагрузку на merge.

### 5. Диагностика и предотвращение mapping explosion

Сценарий: приложение логирует произвольный JSON, количество полей растет без контроля, индексация начинает падать с ошибками.

```bash
# 1. Проверить текущий лимит полей
curl -u elastic:$PASS -k "$ES/logs-app-default/_settings?filter_path=**.total_fields.limit"
```

```json
{
  "logs-app-default": {
    "settings": {
      "index": {
        "mapping": {
          "total_fields": {
            "limit": "1000"
          }
        }
      }
    }
  }
}
```

```bash
# 2. Временно поднять лимит (не является решением, а только обходом)
curl -u elastic:$PASS -k -X PUT "$ES/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{ "index.mapping.total_fields.limit": 5000 }'
```

Постоянное решение — перейти на `dynamic: strict` или `flattened` тип поля:

```bash
curl -u elastic:$PASS -k -X PUT "$ES/logs-app-default/_mapping" \
-H 'Content-Type: application/json' -d'
{
  "dynamic": "strict",
  "properties": {
    "metadata": {
      "type": "flattened"
    }
  }
}'
```

### 6. Диагностика circuit breaker и heap pressure

Сценарий: в логах Elasticsearch появляются `circuit_breaking_exception`, запросы падают с `429`.

```bash
# 1. Проверить статус breaker'ов
curl -u elastic:$PASS -k "$ES/_nodes/stats/breakers?pretty"
```

```json
{
  "breakers": {
    "request": {
      "limit": "1gb",
      "estimated": "200mb",
      "overhead": 1.0,
      "estimated_size_in_bytes": 209715200,
      "tripped": 0
    },
    "fielddata": {
      "limit": "1gb",
      "estimated": "900mb",
      "overhead": 1.03,
      "estimated_size_in_bytes": 92727,
      "tripped": 15
    }
  }
}
```

| Показатель | Признак проблемы | Действие |
| :--- | :--- | :--- |
| `tripped` > 0 | Breaker сработал | Найти источник через `hot_threads` и `_tasks` |
| `estimated` близок к `limit` | Давление на heap | Увеличить heap до 31 ГБ или добавить узлы |
| `fielddata.estimated` растет | Кэширование полей в heap | Отключить `doc_values` или `fielddata` на text-полях |

```bash
# 2. Найти тяжелые запросы/агрегации
curl -u elastic:$PASS -k "$ES/_tasks?detailed=true&actions=*search*,*bulk*"
```

```bash
# 3. Отключить fielddata на проблемном поле
curl -u elastic:$PASS -k -X PUT "$ES/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{
  "index": {
    "mapping": {
      "fielddata": {
        "fields": ["message"]
      }
    }
  }
}'
```

### 7. Диагностика роста сегментов

Сценарий: количество сегментов на шард превышает 100, поиск замедляется.

```bash
# 1. Посчитать сегменты на шард
curl -u elastic:$PASS -k "$ES/_cat/segments/logs-app-default?v&h=index,shard,segment,docs.count,size&s=shard"
```

| Сегментов на шард | Рекомендация |
| :--- | :--- |
| < 20 | Норма для активно пишущихся индексов |
| 20–50 | Увеличить `refresh_interval` или `segments_per_tier` |
| 50–100 | Выполнить `_forcemerge` на закрытых индексах |
| > 100 | Критично: уменьшить `refresh_interval` или `segments_per_tier` |

```bash
# 2. Принудительный merge для закрытых индексов
curl -u elastic:$PASS -k -X POST "$ES/logs-app-000001/_forcemerge?max_num_segments=1"
# → {"_shards":{"total":2,"successful":2,"failed":0}}
```

### 8. Диагностика stalled recovery и shard relocation

Сценарий: после отказа узла кластер не может восстановить реплики, шарды в состоянии `UNASSIGNED`.

```bash
# 1. Найти unassigned шарды
curl -u elastic:$PASS -k "$ES/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason&s=state:desc"

# 2. Получить объяснение планировщика
curl -u elastic:$PASS -k "$ES/_cluster/allocation/explain?pretty" \
-H 'Content-Type: application/json' -d'
{ "index": "logs-app-000001", "shard": 0, "primary": false }'
```

Типичные причины и решения:

| Причина | Решение |
| :--- | :--- |
| `NODE_LEFT` | Узел вернулся — шард восстановится сам; если нет — проверьте disk watermarks |
| `ALLOCATION_FAILED` | Недостаточно места или нарушены awareness constraints |
| `DECIDED_BY_ALLOCATOR: disk watermark` | Освободите диск или добавьте ноды; смотрите `_cat/allocation` |
| `NO_VALID_COPY` | Данные потеряны — восстановите из snapshot |
| `CLUSTER_RECOVERED` | Временное состояние, ждите восстановления |

```bash
# 3. Временно ускорить восстановление (для тестов)
curl -u elastic:$PASS -k -X PUT "$ES/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": "200mb",
    "cluster.routing.allocation.node_concurrent_recoveries": 6
  }
}'
```

### 9. Проверка health индекса после проблем

Сценарий: после сбоя индексация падала, нужно убедиться, что индекс в порядке.

```bash
# 1. Проверить здоровье индекса
curl -u elastic:$PASS -k "$ES/_cluster/health/logs-app-default?pretty"
```

```json
{
  "cluster_name": "es-prod",
  "status": "green",
  "active_primary_shards": 3,
  "active_shards": 6,
  "unassigned_shards": 0
}
```

```bash
# 2. Проверить, что все сегменты записаны на диск
curl -u elastic:$PASS -k "$ES/_cat/segments/logs-app-default?v&h=index,shard,segment,size,flush_counter&s=shard"
# → flush_counter > 0 означает, что сегмент записан на диск
```

```bash
# 3. Проверить translog
curl -u elastic:$PASS -k "$ES/logs-app-default/_stats/translog?pretty"
```

```json
{
  "indices": {
    "logs-app-default": {
      "primaries": {
        "translog": {
          "operations": 15234,
          "size": "2.1mb",
          "unreferenced": {
            "operations": 0,
            "size": "0b"
          }
        }
      }
    }
  }
}
```

### 10. Оптимизация bulk-индексации

Сценарий: приложение отправляет логи через Bulk API, но Elasticsearch отклоняет часть запросов.

```bash
# 1. Оптимальный размер bulk-запроса: 5–15 МБ
# Пример сжатого bulk:
curl -u elastic:$PASS -k -X POST "$ES/_bulk?refresh=false&compression=gzip" \
-H 'Content-Type: application/x-ndjson' --data-binary @/tmp/bulk.ndjson
```

```bash
# 2. Ограничить параллелизм на стороне отправителя
# В приложении: не более 2–3 одновременных bulk-запросов
# На стороне ES: проверить очередь write thread pool
curl -u elastic:$PASS -k "$ES/_cat/thread_pool/write?v"
```

```bash
# 3. Настроить backpressure (если источник — Filebeat/Logstash)
# В Filebeat: ограничьте workers и bulk_max_size
# В Logstash: ограничьте pipeline.workers и pipeline.batch.size
```

### 11. Диагностика merge storms при обновлении индекса

Сценарий: после массового обновления полей в индексе (update_by_query) кластер замедлился.

```bash
# 1. Найти долгие merge-задачи
curl -u elastic:$PASS -k "$ES/_tasks?detailed=true&actions=*merge*"

# 2. Ограничить merge на проблемном индексе
curl -u elastic:$PASS -k -X PUT "$ES/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{
  "index": {
    "merge": {
      "policy": {
        "max_merged_segment": "2gb",
        "segments_per_tier": 20.0
      },
      "scheduler": {
        "max_thread_count": 1,
        "max_merge_count": 2
      }
    }
  }
}'
```

```bash
# 3. После завершения обновления выполнить force merge
curl -u elastic:$PASS -k -X POST "$ES/logs-app-default/_forcemerge?max_num_segments=1&only_expunge_deletes=true"
```

### 12. Мониторинг в Prometheus

Ключевые метрики для отслеживания индексации:

```yaml
groups:
  - name: elasticsearch_indexing
    rules:
      - alert: ElasticsearchMergeQueueFull
        expr: elasticsearch_cluster_health_pending_tasks{type="merge"} > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Merge queue растет на {{ $labels.cluster }}"

      - alert: ElasticsearchIndexingRejected
        expr: rate(elasticsearch_indices_indexing_index_total[5m]) < rate(elasticsearch_indices_indexing_index_rejected_total[5m])
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Запись отклоняется на {{ $labels.cluster }}"

      - alert: ElasticsearchCircuitBreakerTripped
        expr: rate(elasticsearch_breakers_parent_tripped_total[5m]) > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Circuit breaker сработал на {{ $labels.cluster }}"

      - alert: ElasticsearchTranslogTooLarge
        expr: elasticsearch_indices_translog_size_bytes / 1024 / 1024 > 1024
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Translog > 1GB на шарде {{ $labels.shard }}"
```

## Дополнительная информация

### Типовые настройки для production

Для индексов с высокой нагрузкой на запись:

```json
{
  "settings": {
    "index.refresh_interval": "30s",
    "index.translog.durability": "request",
    "index.translog.flush_threshold.size": "512mb",
    "index.merge.policy.max_merged_segment": "5gb",
    "index.merge.policy.segments_per_tier": 10.0,
    "index.merge.scheduler.max_thread_count": 1,
    "index.merge.scheduler.max_merge_count": 6
  }
}
```

Для массовой загрузки (one-time):

```json
{
  "settings": {
    "index.refresh_interval": "-1",
    "index.number_of_replicas": 0,
    "index.translog.durability": "async"
  }
}
```

После загрузки верните настройки и выполните `_forcemerge`.

### Ограничения и лимиты

| Параметр | По умолчанию | Рекомендация |
| :--- | :--- | :--- |
| `index.refresh_interval` | `1s` | `30s` — `60s` для логов; `-1` для bulk |
| `index.translog.flush_threshold.size` | `512mb` | Оставить или уменьшить до `200mb` при быстрой записи |
| `index.merge.scheduler.max_thread_count` | 2 (SSD), 1 (HDD) | 1 для HDD, 2 для NVMe |
| `index.merge.scheduler.max_merge_count` | ` IndicesMergeScheduler#getMaxMergeCount()` (обычно 6–9) | 4–6 для production |
| `index.mapping.total_fields.limit` | 1000 | Поднять до 5000 только для schema-less JSON |
| `indices.memory.index_buffer_size` | 10% heap | Оставить по умолчанию или увеличить до 15% |

### Смотрите также

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера и lifecycle документа.
*   **[Elasticsearch: Жизненный цикл (ILM)](./elasticsearch_ilm_and_retention.md)** — автоматизация ротации данных.
*   **[Elasticsearch: Индексирование и маппинг](./elasticsearch_mapping_and_indexing.md)** — схемы данных и bulk API.
*   **[Настройка кластера Elasticsearch](../Tutorials/cluster_setup.md)** — системный тюнинг и Bootstrap Checks.
*   **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — метрики для диагностики.
*   **[Search Performance Tuning](./elasticsearch_search_tuning.md)** — оптимизация поиска.
*   **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — обработка документов.
