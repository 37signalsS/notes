# OpenSearch: Траблшутинг индексации и сегментов

> Заметка посвящена диагностике проблем индексации в OpenSearch: медленной записи, перегрева heap, ограничения слияний, роста сегментов и Segment Replication. Базовые понятия кластера (шарды, refresh, translog, роли узлов) описаны в [обзоре OpenSearch](./opensearch_overview.md); ISM — в [жизненном цикле индексов (ISM)](./opensearch_ism_lifecycle.md).

## Определения

* **Merge (Слияние)** — фоновый процесс объединения мелких сегментов Lucene в крупные. В OpenSearch используется планировщик `ConcurrentMergeScheduler`, ограничивающий параллельные merge через `max_thread_count` и `max_merge_count`.
* **Merge Throttling (Ограничение слияний)** — механизм снижения приоритета merge при высокой нагрузке на индексацию, чтобы не конкурировать за I/O и CPU. Настраивается через `indices.merge.scheduler.*`.
* **Segment (Сегмент)** — минимальная неделимая единица хранения Lucene. Каждый шард — набор неизменяемых сегментов.
* **Translog (Журнал упреждающей записи)** — WAL для гарантии durability. При переполнении или по расписанию выполняется flush — сброс сегментов на диск и обрезка translog.
* **Segment Replication (SegRep)** — репликация готовых сегментов Lucene с primary на реplikи вместо повторной индексации. Снижает нагрузку на CPU на репликах, но увеличивает сетевой трафик. GA начиная с OpenSearch 2.7.
* **Indexing Buffer (Буфер индексации)** — in-memory область на шард. При переполнении (`indices.memory.index_buffer_size`) Elasticsearch принудительно выполняет refresh или отклоняет запись.
* **Refresh Interval** — период создания новых сегментов Lucene из буфера (по умолчанию `1s`). Увеличение интервала снижает количество сегментов.
* **Circuit Breaker (Размыкатель)** — защита JVM heap от OOM. В OpenSearch используются breaker'ы `request`, `fielddata`, `accounting` и `in_flight_requests`.
* **Thread Pool (Пул потоков)** — очередь задач на индексацию (`write`), поиск (`search`), merge (`merge`). При переполнении (`queue_size`) задачи отклоняются.
* **Force Merge** — принудительное слияние сегментов до заданного числа (`max_num_segments`). Для индексов, куда запись завершена, уменьшает количество открытых файлов.
* **Remote Store Stats** — API для наблюдения за загрузкой сегментов в объектное хранилище (`GET /_plugins/_remote_store/stats`). Позволяет отслеживать lag и backpressure при Remote-Backed Storage.

## Основные концепции

### Жизненный цикл документа и сегментов

1. Документ попадает в **memory buffer** и **translog**.
2. **Refresh** создает новый сегмент Lucene из буфера. Документ становится видимым для поиска.
3. **Merge** сливает мелкие сегменты в крупные, удаляя помеченные на удаление документы.
4. **Flush** сбрасывает сегменты на диск и обрезает translog.

В OpenSearch 2.x с включенной Segment Replication merge на primary-узле создает новые сегменты, которые затем копируются на реплики. Это снижает CPU-нагрузку на data-узлах, но увеличивает сетевой трафик.

### Настройки merge и производительности

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `index.merge.policy.max_merged_segment` | Максимальный размер сегмента после merge | `5gb` |
| `index.merge.policy.segments_per_tier` | Число сегментов одного размера перед merge | `10.0` |
| `index.merge.scheduler.max_thread_count` | Максимум merge-потоков на шард | `1` (HDD), `2` (NVMe) |
| `index.merge.scheduler.max_merge_count` | Общий лимит merge-заданий на узел | `6` |
| `index.refresh_interval` | Частота создания новых сегментов | `30s` — `60s` для логов; `-1` для bulk |
| `index.translog.flush_threshold.size` | Порог сброса translog | `512mb` |

### Мониторинг индексации

| Метрика | API | Норма |
| :--- | :--- | :--- |
| Скорость индексации | `GET _cat/nodes?v&h=name,indexing.index_total,indexing.index_time` | Зависит от hardware |
| Очередь merge | `GET _cat/thread_pool/merge?v` | `active` < `max_thread_count` |
| Размер сегментов | `GET _cat/segments/<index>?v&bytes=gb` | Сегментов < 50 на шард |
| Translog | `GET _nodes/stats/indices/translog` | `size` < `flush_threshold` |
| Circuit Breaker | `GET /_nodes/stats/breakers` | `tripped` = 0 |
| Write rejections | `GET _cat/nodes?v&h=name,indices.search.rejections` | 0 в стабильном состоянии |
| Segment Replication lag | `GET _cat/segment_replication?v` | Лаг < 10 секунд |

### Типовые паттерны проблем

**Merge Storm**: фоновые merge-потоки потребляют всю I/O. Проявляется в `iostat` как 100% `%util` и активные merge-потоки в `_cat/thread_pool`.

**Indexing Buffer Overflow**: буфер переполняется из-за быстрой индексации. Признак — ошибки `409` или принудительные refresh.

**Translog Overflow**: translog растет быстрее, чем flush его обрезает. Признак — `translog.operations` в миллионах на шард.

**Circuit Breaker Trip**: крупная агрегация или fielddata превышают лимит heap. Признак — ошибки `429` с `circuit_breaking_exception`.

**Mapping Explosion**: динамическое создание тысяч полей. Признак — ошибка `limit of total fields has been exceeded`.

**SegRep Lag**: реплики отстают от primary. Признак — растущий лаг в `_cat/segment_replication`.

## Практические сценарии

**Предварительные требования для всех сценариев**:

```bash
export OS="https://localhost:9200"
export PASS="<пароль пользователя admin>"
curl -ku admin:$PASS "$OS"   # → {"name" : "opensearch-dev", ..., "tagline" : "The OpenSearch Project"}
```

### 1. Диагностика медленной индексации

Сценарий: приложение пишет логи, задержка между отправкой и поиском превышает 5 секунд.

```bash
# 1. Проверить скорость индексации
curl -ku admin:$PASS "$OS/_cat/nodes?v&h=name,indexing.index_total,indexing.index_time,indexing.index_current"

# 2. Проверить write thread pool
curl -ku admin:$PASS "$OS/_cat/thread_pool/write?v"
# → queue tasks rejected active priority
```

| Показатель | Признак проблемы | Действие |
| :--- | :--- | :--- |
| `indexing.index_time` высокий, `index_total` низкий | Медленная запись на диск | Проверьте I/O (`iostat -x 1`), увеличьте `refresh_interval` |
| `queue` > 0 | Переполнена очередь записи | Уменьшите размер bulk, увеличьте `refresh_interval` |
| `rejected` > 0 | Отклонены задачи | Увеличьте `indices.memory.index_buffer_size` или добавьте узлы |
| `active` много | Много параллельных записей | Ограничьте конкурентность отправителя |

```bash
# 3. Проверить hot threads
curl -ku admin:$PASS "$OS/_nodes/hot_threads?threads=5&type=merge"
```

### 2. Разрешение merge throttling

Сценарий: индексация замедлилась, `iostat` показывает 100% utilization диска, merge-потоки активны.

```bash
# 1. Оценить нагрузку merge
curl -ku admin:$PASS "$OS/_cat/thread_pool/merge?v"

# 2. Временно ограничить merge
curl -ku admin:$PASS -X PUT "$OS/_cluster/settings" \
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
* `max_merge_count: 4` — не более 4 merge-заданий на весь узел одновременно.
* Для горячих индексов с высокой нагрузкой используйте `"index.merge.policy.segments_per_tier": 15.0`.

```bash
# 3. Принудительный merge для завершенных индексов
curl -ku admin:$PASS -X POST "$OS/old-index/_forcemerge?max_num_segments=1"
# → {"_shards":{"total":2,"successful":2,"failed":0}}
```

**Важно**: не вызывайте `_forcemerge` на индексах, куда продолжается запись.

### 3. Диагностика проблем с translog

Сценарий: индексы зависают при перезапуске узла, восстановление шардов занимает долго.

```bash
# 1. Проверить размер translog
curl -ku admin:$PASS "$OS/_nodes/stats/indices/translog?pretty"
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
| `operations` | < 100 000 на шард | > 1M — долгое восстановление |
| `size` | < 512 МБ | > 2 ГБ — долгий flush при сбое |
| `unreferenced` | 0 | > 0 — обрезанный translog не удален |

```bash
# 2. Настроить flush threshold
curl -ku admin:$PASS -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "index.translog.flush_threshold.size": "512mb",
    "index.translog.flush_threshold.period": "5m"
  }
}'
```

```bash
# 3. Принудительный flush для очистки unreferenced translog
curl -ku admin:$PASS -X POST "$OS/_flush"
```

### 4. Управление refresh interval

Сценарий: массовая загрузка исторических данных, поиск не нужен в процессе.

```bash
# 1. Отключить автorefresh
curl -ku admin:$PASS -X PUT "$OS/historical-logs/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "refresh_interval": "-1" } }'
# → {"acknowledged":true}

# 2. После загрузки вернуть refresh
curl -ku admin:$PASS -X PUT "$OS/historical-logs/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "refresh_interval": "30s" } }'

curl -ku admin:$PASS -X POST "$OS/historical-logs/_refresh"
```

### 5. Диагностика Segment Replication lag

Сценарий: реплики отстают от primary, поиск возвращает устаревшие данные.

```bash
# 1. Проверить lag реплик
curl -ku admin:$PASS "$OS/_cat/segment_replication?v"
```

```text
index       shard target_node       source_node state   lag_in_millis
logs-000001 0     opensearch-data-2 opensearch-data-1 SYNCED  125
logs-000001 1     opensearch-data-1 opensearch-data-2 SYNCED  89
```

| `state` | Значение | Действие |
| :--- | :--- | :--- |
| `SYNCED` | Реплика актуальна | Норма |
| `SYNCING` | Идет копирование сегмента | Мониторить lag |
| `FAILED` | Ошибка репликации | Проверить сеть и логи |

```bash
# 2. Включить backpressure (OpenSearch 2.10+)
curl -ku admin:$PASS -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "plugins.index_state_management.segment_replication.backpressure.enabled": true
  }
}'
```

### 6. Диагностика circuit breaker и heap pressure

Сценарий: в логах `circuit_breaking_exception`, запросы падают с `429`.

```bash
# 1. Проверить breaker'ы
curl -ku admin:$PASS "$OS/_nodes/stats/breakers?pretty"
```

```json
{
  "breakers": {
    "request": {
      "limit": "1gb",
      "estimated": "200mb",
      "tripped": 0
    },
    "fielddata": {
      "limit": "1gb",
      "estimated": "900mb",
      "tripped": 15
    }
  }
}
```

| Показатель | Признак проблемы | Действие |
| :--- | :--- | :--- |
| `tripped` > 0 | Breaker сработал | Найти источник через `hot_threads` |
| `estimated` близок к `limit` | Давление на heap | Увеличить heap до 31 ГБ |
| `fielddata.estimated` растет | Кэширование полей | Отключить fielddata на text-полях |

```bash
# 2. Найти тяжелые запросы
curl -ku admin:$PASS "$OS/_tasks?detailed=true&actions=*search*,*bulk*"

# 3. Отключить fielddata
curl -ku admin:$PASS -X PUT "$OS/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{
  "index": {
    "mapping": {
      "fielddata": { "fields": ["message"] }
    }
  }
}'
```

### 7. Диагностика mapping explosion

Сценарий: приложение логирует произвольный JSON, индексация падает с ошибкой лимита полей.

```bash
# 1. Проверить лимит полей
curl -ku admin:$PASS "$OS/logs-app-default/_settings?filter_path=**.total_fields.limit"

# 2. Временно поднять лимит
curl -ku admin:$PASS -X PUT "$OS/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{ "index.mapping.total_fields.limit": 5000 }'

# 3. Постоянное решение: flattened тип для произвольного JSON
curl -ku admin:$PASS -X PUT "$OS/logs-app-default/_mapping" \
-H 'Content-Type: application/json' -d'
{
  "dynamic": "strict",
  "properties": {
    "metadata": { "type": "flattened" }
  }
}'
```

### 8. Диагностика stalled recovery

Сценарий: после отказа узла реплики не восстанавливаются.

```bash
# 1. Найти unassigned шарды
curl -ku admin:$PASS "$OS/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason&s=state:desc"

# 2. Получить объяснение
curl -ku admin:$PASS "$OS/_cluster/allocation/explain?pretty" \
-H 'Content-Type: application/json' -d'
{ "index": "logs-app-000001", "shard": 0, "primary": false }'
```

Типичные причины:

| Причина | Решение |
| :--- | :--- |
| `NODE_LEFT` | Узел вернулся — ждите восстановления |
| `DECIDED_BY_ALLOCATOR: disk watermark` | Освободите диск |
| `NO_VALID_COPY` | Данные потеряны — восстановите из snapshot |
| `CLUSTER_RECOVERED` | Временное состояние |

```bash
# 3. Ускорить восстановление
curl -ku admin:$PASS -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": "200mb",
    "cluster.routing.allocation.node_concurrent_recoveries": 6
  }
}'
```

### 9. Проверка health индекса после проблем

```bash
# 1. Health индекса
curl -ku admin:$PASS "$OS/_cluster/health/logs-app-default?pretty"

# 2. Сегменты на диск
curl -ku admin:$PASS "$OS/_cat/segments/logs-app-default?v&h=index,shard,segment,size&s=shard"

# 3. Translog
curl -ku admin:$PASS "$OS/logs-app-default/_stats/translog?pretty"
```

### 10. Оптимизация bulk-индексации

```bash
# 1. Оптимальный размер: 3–5 МБ с gzip
curl -ku admin:$PASS -X POST "$OS/_bulk?compression=gzip" \
-H 'Content-Type: application/x-ndjson' --data-binary @/tmp/bulk.ndjson

# 2. Проверить очередь
curl -ku admin:$PASS "$OS/_cat/thread_pool/write?v"

# 3. Ограничить параллелизм отправителя
# В приложении: не более 2–3 одновременных запросов
```

### 11. Мониторинг в Prometheus

```yaml
groups:
  - name: opensearch_indexing
    rules:
      - alert: OpenSearchMergeQueueFull
        expr: opensearch_cluster_health_pending_tasks{type="merge"} > 10
        for: 5m
        labels:
          severity: warning

      - alert: OpenSearchIndexingRejected
        expr: rate(opensearch_indices_indexing_index_total[5m]) < rate(opensearch_indices_indexing_index_rejected_total[5m])
        for: 2m
        labels:
          severity: critical

      - alert: OpenSearchCircuitBreakerTripped
        expr: rate(opensearch_breakers_parent_tripped_total[5m]) > 0
        for: 1m
        labels:
          severity: warning

      - alert: OpenSearchSegmentReplicationLag
        expr: opensearch_segment_replication_lag_millis > 10000
        for: 5m
        labels:
          severity: warning

      - alert: OpenSearchTranslogTooLarge
        expr: opensearch_indices_translog_size_bytes / 1024 / 1024 > 1024
        for: 10m
        labels:
          severity: warning
```

## Дополнительная информация

### Типовые настройки для production

Для индексов с высокой нагрузкой:

```json
{
  "settings": {
    "index.refresh_interval": "30s",
    "index.translog.flush_threshold.size": "512mb",
    "index.merge.policy.max_merged_segment": "5gb",
    "index.merge.policy.segments_per_tier": 10.0,
    "index.merge.scheduler.max_thread_count": 1,
    "index.merge.scheduler.max_merge_count": 6,
    "index.translog.durability": "request"
  }
}
```

Для массовой загрузки:

```json
{
  "settings": {
    "index.refresh_interval": "-1",
    "index.number_of_replicas": 0,
    "index.translog.durability": "async"
  }
}
```

### Ограничения и лимиты

| Параметр | По умолчанию | Рекомендация |
| :--- | :--- | :--- |
| `index.refresh_interval` | `1s` | `30s` — `60s` для логов |
| `index.translog.flush_threshold.size` | `512mb` | `200mb` — `512mb` |
| `index.merge.scheduler.max_thread_count` | 2 (SSD), 1 (HDD) | 1 для HDD, 2 для NVMe |
| `index.merge.scheduler.max_merge_count` | 6–9 | 4–6 |
| `index.mapping.total_fields.limit` | 1000 | Поднять только для schema-less JSON |
| `cluster.max_shards_per_node` | 1000 (до 2.15), до 4000 (2.17+) | 20–25 на 1 ГБ heap |

### Смотрите также

*   **[OpenSearch: Обзор](./opensearch_overview.md)** — архитектура кластера.
*   **[OpenSearch: Администрирование](./opensearch_administration.md)** — безопасность и шарды.
*   **[OpenSearch: ISM жизненный цикл](./opensearch_ism_lifecycle.md)** — автоматизация ротации.
*   **[Elasticsearch: Траблшутинг индексации](../Elasticsearch/elasticsearch_troubleshooting_indexing.md)** — сравнение подходов.
