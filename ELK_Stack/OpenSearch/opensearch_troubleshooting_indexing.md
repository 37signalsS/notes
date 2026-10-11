# OpenSearch: Траблшутинг индексации и сегментов

**Актуально для:** OpenSearch 3.9.x

> Заметка посвящена диагностике проблем индексации в OpenSearch: медленной записи, перегрева heap, ограничения слияний, роста сегментов и Segment Replication. Базовые понятия кластера (шарды, refresh, translog, роли узлов) описаны в [обзоре OpenSearch](./opensearch_overview.md); лимиты шардов и sizing — в [capacity planning](./opensearch_capacity_planning.md); ISM — в [жизненном цикле индексов (ISM)](./opensearch_ism_lifecycle.md); оперативная диагностика (allocation/explain, recovery, watermarks) — в [администрировании](./opensearch_administration.md).

## Определения

* **Merge (Слияние)** — фоновый процесс объединения мелких сегментов Lucene в крупные. В OpenSearch используется планировщик `ConcurrentMergeScheduler`, ограничивающий параллельные merge через `max_thread_count` и `max_merge_count`.
* **Merge Throttling (Ограничение слияний)** — механизм защиты от merge storm: когда число одновременных merge превышает `max_merge_count`, потоки индексации блокируются до завершения merge. Настраивается через `index.merge.scheduler.*` (индекс) и `indices.merge.scheduler.*` (кластер).
* **Segment (Сегмент)** — минимальная неделимая единица хранения Lucene. Каждый шард — набор неизменяемых сегментов.
* **Translog (Журнал упреждающей записи)** — WAL для гарантии durability. При переполнении (`index.translog.flush_threshold.size`) или по расписанию (`index.periodic_flush_interval`) выполняется flush — сброс сегментов на диск и обрезка translog.
* **Segment Replication (SegRep)** — репликация готовых сегментов Lucene с primary на реплики вместо повторной индексации (experimental с 2.3, GA с 2.7). Снижает нагрузку на CPU на репликах (прирост throughput до +25% по бенчмаркам проекта), но увеличивает сетевой трафик.
* **Indexing Buffer (Буфер индексации)** — область heap на узел, общая для всех активно индексирующих шардов (`indices.memory.index_buffer_size`, по умолчанию 10% heap, минимум 48 МБ). При переполнении OpenSearch принудительно делает refresh крупнейших шардов; при превышении 150% бюджета — включает throttling записи (shard indexing backpressure).
* **Refresh Interval** — период создания новых сегментов Lucene из буфера (по умолчанию `1s`). Увеличение интервала снижает количество сегментов. Оптимизация search-idle: индексы, к которым не было поисковых запросов 30 секунд, не обновляются вообще.
* **Circuit Breaker (Размыкатель)** — защита JVM heap от OOM. Брейкеры: `parent` (суммарный, 95% heap), `request` (60%), `fielddata` (40%), `accounting`, `in_flight_requests`. Таблица лимитов и настроек — в [администрировании](./opensearch_administration.md).
* **Thread Pool (Пул потоков)** — очередь задач на индексацию (`write`), поиск (`search`), merge (`merge`). При переполнении очереди задачи отклоняются с `429`. Размер очереди задаётся в `opensearch.yml` (`thread_pool.write.queue_size`) и не меняется динамически.
* **Force Merge** — принудительное слияние сегментов до заданного числа (`max_num_segments`). Для индексов, куда запись завершена, уменьшает количество открытых файлов.
* **Remote Store Stats** — API для наблюдения за загрузкой сегментов и translog в remote-backed storage (`GET _remotestore/stats/<index>`, с 2.8). Показывает lag, скорость upload/download и число отклонений из-за backpressure.

## Основные концепции

### Жизненный цикл документа и сегментов

1. Документ попадает в **memory buffer** и **translog**.
2. **Refresh** создает новый сегмент Lucene из буфера. Документ становится видимым для поиска.
3. **Merge** сливает мелкие сегменты в крупные, удаляя помеченные на удаление документы.
4. **Flush** сбрасывает сегменты на диск и обрезает translog.

С включенной Segment Replication merge выполняется только на primary: новые сегменты копируются на реплики целиком. Это снижает CPU-нагрузку на data-узлах, но увеличивает сетевой трафик и время видимости документа на репликах.

### Настройки merge и производительности

| Параметр | Назначение | По умолчанию / рекомендация |
| :--- | :--- | :--- |
| `index.merge.policy.max_merged_segment` | Максимальный размер сегмента после merge | `5gb` |
| `index.merge.policy.segments_per_tier` | Число сегментов одного размера перед merge | `10.0` (для горячих индексов — `15.0`) |
| `index.merge.scheduler.max_thread_count` | Максимум merge-потоков на шард | `max(1, min(4, процессоры/2))` для SSD; `1` для HDD |
| `index.merge.scheduler.max_merge_count` | Общий лимит одновременных merge на узел | `max_thread_count + 5` (`6` для HDD) |
| `index.refresh_interval` | Частота создания новых сегментов | `1s`; `30s`–`60s` для логов; `-1` для bulk |
| `index.translog.flush_threshold.size` | Порог сброса translog | `512mb` (для чистой индексации — до 25% heap) |
| `index.periodic_flush_interval` | Периодический flush по времени | `-1` (выключен; flush по размеру translog) |

Настройки `indices.merge.scheduler.*` — динамические настройки уровня кластера; `index.merge.scheduler.*` — динамические настройки конкретного индекса. Оба уровня обновляются через `PUT _cluster/settings` и `PUT <index>/_settings` соответственно.

### Мониторинг индексации

| Метрика | API | Норма |
| :--- | :--- | :--- |
| Скорость индексации | `GET _cat/nodes?v&h=name,indexing.index_total,indexing.index_time` | Зависит от hardware |
| Очередь и отказы записи | `GET _cat/thread_pool/write?v&h=name,active,queue,rejected` | `rejected` = 0 |
| Очередь merge | `GET _cat/thread_pool/merge?v` | `active` ≤ `max_thread_count` |
| Размер сегментов | `GET _cat/segments/<index>?v&bytes=gb` | Сегментов < 50 на шард |
| Translog | `GET _nodes/stats/indices/translog` | `size` < `flush_threshold` |
| Circuit Breaker | `GET _nodes/stats/breakers` | `tripped` = 0 |
| Давление индексации | `GET _nodes/stats/shard_indexing_pressure` | `rejected` = 0 |
| Segment Replication lag | `GET _cat/segment_replication?v` | `checkpoints_behind` = 0 |

### Типовые паттерны проблем

**Merge Storm**: фоновые merge-потоки потребляют всю I/O, индексация блокируется ожиданием merge. Проявляется в `iostat` как 100% `%util` и активные merge-потоки в `_cat/thread_pool/merge`.

**Indexing Buffer Overload**: буфер на узле переполняется из-за быстрой индексации. Признак — принудительные refresh крупнейших шардов (рост `active` в `_cat/thread_pool/refresh`) и, при превышении 150% бюджета, throttling записи с отказами `429`.

**Translog Overflow**: translog растет быстрее, чем flush его обрезает. Признак — `translog.operations` в миллионах на шард, долгое восстановление после сбоя.

**Circuit Breaker Trip**: крупная агрегация или fielddata превышают лимит heap. Признак — ошибки `429` с `circuit_breaking_exception`.

**Mapping Explosion**: динамическое создание тысяч полей. Признак — ошибка `limit of total fields has been exceeded`.

**SegRep Lag**: реплики отстают от primary. Признак — растущий `checkpoints_behind` в `_cat/segment_replication`; при включенном backpressure — отказы записи.

**Write Rejections (429)**: очередь write-пула переполнена. Причины — слишком крупные или частые bulk, heap > 95%, сработавший breaker, проблемы на primary-шарде.

## Практические сценарии

**Предварительные требования для всех сценариев**:

```bash
export OS="https://localhost:9200"
export PASS="<пароль пользователя admin>"
curl -ku admin:$PASS -k "$OS"   # → {"name" : "opensearch-dev", ..., "tagline" : "The OpenSearch Project"}
```

Флаг `-k` нужен для демо-сертификатов локального кластера; в production используйте собственный PKI без `-k`. Те же запросы можно выполнять в Dev Tools OpenSearch Dashboards без curl и базовой авторизации.

### 1. Диагностика медленной индексации

Сценарий: приложение пишет логи, задержка между отправкой и поиском превышает 5 секунд.

```bash
# 1. Проверить скорость индексации
curl -ku admin:$PASS -k "$OS/_cat/nodes?v&h=name,indexing.index_total,indexing.index_time,indexing.index_current"

# 2. Проверить write thread pool
curl -ku admin:$PASS -k "$OS/_cat/thread_pool/write?v"
# → node_name name active queue rejected
```

| Показатель | Признак проблемы | Действие |
| :--- | :--- | :--- |
| `indexing.index_time` высокий, `index_total` низкий | Медленная запись на диск | Проверьте I/O (`iostat -x 1`), увеличьте `refresh_interval` |
| `queue` > 0 | Переполнена очередь записи | Уменьшите размер и конкурентность bulk, увеличьте `refresh_interval` |
| `rejected` > 0 | Отклонены задачи | Смотрите сценарий 9 (отказы записи) |
| `active` много | Много параллельных записей | Ограничьте конкурентность отправителя (2–4 потока на data-узел) |

```bash
# 3. Hot threads: type принимает только cpu, wait, block (merge-потоки ищите в выводе по имени)
curl -ku admin:$PASS -k "$OS/_nodes/hot_threads?threads=5"
curl -ku admin:$PASS -k "$OS/_nodes/hot_threads?threads=5&type=wait"

# 4. Давление индексации на уровне шардов (кто и почему отклоняет запись)
curl -ku admin:$PASS -k "$OS/_nodes/stats/shard_indexing_pressure?pretty"
```

### 2. Разрешение merge throttling

Сценарий: индексация замедлилась, `iostat` показывает 100% utilization диска, merge-потоки активны.

```bash
# 1. Оценить нагрузку merge
curl -ku admin:$PASS -k "$OS/_cat/thread_pool/merge?v"

# 2. Временно ограничить merge (динамические кластерные настройки)
curl -ku admin:$PASS -k -X PUT "$OS/_cluster/settings" \
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

* `max_thread_count: 1` — одна merge-задача на шард одновременно. Стандарт для HDD; для NVMe можно оставить дефолт (`min(4, процессоры/2)`).
* `max_merge_count: 4` — не более 4 merge-заданий на весь узел одновременно; при превышении индексация блокируется.
* Для горячих индексов с высокой нагрузкой используйте `"index.merge.policy.segments_per_tier": 15.0` — merge запускается реже.

```bash
# 3. Принудительный merge для завершенных индексов
curl -ku admin:$PASS -k -X POST "$OS/old-index/_forcemerge?max_num_segments=1"
# → {"_shards":{"total":2,"successful":2,"failed":0}}
```

**Важно**: не вызывайте `_forcemerge` на индексах, куда продолжается запись — это создает сегменты, которые придется мерджить заново.

### 3. Диагностика проблем с translog

Сценарий: индексы зависают при перезапуске узла, восстановление шардов занимает долго.

```bash
# 1. Проверить размер translog
curl -ku admin:$PASS -k "$OS/_nodes/stats/indices/translog?pretty"
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
# 2. Настроить порог flush (динамическая настройка индекса, не кластера)
curl -ku admin:$PASS -k -X PUT "$OS/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{
  "index": {
    "translog.flush_threshold.size": "512mb"
  }
}'

# 3. Включить периодический flush (по умолчанию выключен: -1)
curl -ku admin:$PASS -k -X PUT "$OS/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "periodic_flush_interval": "5m" } }'

# 4. Принудительный flush для очистки unreferenced translog
curl -ku admin:$PASS -k -X POST "$OS/_flush"
```

Компромисс: увеличение `flush_threshold.size` (для чистой индексации — до 25% heap) снижает частоту flush и ускоряет запись, но увеличивает время восстановления шарда после сбоя — translog длиннее.

### 4. Управление refresh interval

Сценарий: массовая загрузка исторических данных, поиск не нужен в процессе.

```bash
# 1. Отключить автorefresh
curl -ku admin:$PASS -k -X PUT "$OS/historical-logs/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "refresh_interval": "-1" } }'
# → {"acknowledged":true}

# 2. После загрузки вернуть refresh
curl -ku admin:$PASS -k -X PUT "$OS/historical-logs/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "refresh_interval": "30s" } }'

curl -ku admin:$PASS -k -X POST "$OS/historical-logs/_refresh"
```

С `refresh_interval: -1` документы не видны поиску до явного `_refresh`. Учтите search-idle оптимизацию: индексы без поисковых запросов 30 секунд не refresh'атся и так — отключать refresh имеет смысл только при интенсивной записи.

### 5. Диагностика Segment Replication lag

Сценарий: реплики отстают от primary, поиск на репликах возвращает устаревшие данные.

```bash
# 1. Проверить lag реплик
curl -ku admin:$PASS -k "$OS/_cat/segment_replication?v"
```

```text
shardId          target_node     target_host checkpoints_behind bytes_behind current_lag last_completed_lag rejected_requests
[logs-000001][0] opensearch-data-2 10.0.1.11  0                0b           0s          7ms                0
[logs-000001][1] opensearch-data-1 10.0.1.10  12               1.2gb        30s         2m                 45
```

| Колонка | Значение |
| :--- | :--- |
| `checkpoints_behind` | На сколько чекпоинтов refresh реплика отстает от primary (> 0 — лаг) |
| `bytes_behind` | Отставание в байтах |
| `current_lag` | Время ожидания текущего копирования |
| `last_completed_lag` | Время последнего завершенного копирования |
| `rejected_requests` | Число отклонений записи из-за backpressure в группе репликации |

```bash
# 2. Включить backpressure (по умолчанию выключен)
curl -ku admin:$PASS -k -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "segrep.pressure.enabled": true
  }
}'
```

Настройки backpressure (динамические, node-scope; точные дефолты на своей версии: `GET _cluster/settings?include_defaults=true&filter_path=**.segrep.*`):

| Настройка | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `segrep.pressure.enabled` | `false` | Включает механизм |
| `segrep.pressure.time.limit` | `5m` | Лаг времени, после которого primary начинает отклонять запись |
| `segrep.pressure.checkpoint.limit` | `4` | Лаг чекпоинтов (действует совместно с time.limit) |
| `segrep.pressure.replica.stale.limit` | `0.5` | Доля stale-реплик в группе, при которой включается backpressure |

Особенности SegRep:

* Копирование сегментов троттлится настройками recovery — `indices.recovery.max_bytes_per_sec` (по умолчанию `40mb`) не резервируется только для восстановления шардов, а делит бюджет с SegRep.
* SegRep не поддерживает `wait_for` в API `_refresh`.
* При хроническом лаге проверьте сеть между узлами (`ping`, `iperf3`) и диск на primary (merge должен успевать создавать сегменты).

### 6. Диагностика circuit breaker и heap pressure

Сценарий: в логах `circuit_breaking_exception`, запросы падают с `429`.

```bash
# 1. Проверить breaker'ы
curl -ku admin:$PASS -k "$OS/_nodes/stats/breakers?pretty"
```

```json
{
  "breakers": {
    "parent": { "limit": "14.5gb", "estimated": "13.9gb", "tripped": 3 },
    "request": { "limit": "9.2gb", "estimated": "200mb", "tripped": 0 },
    "fielddata": { "limit": "6.1gb", "estimated": "5.8gb", "tripped": 15 }
  }
}
```

| Показатель | Признак проблемы | Действие |
| :--- | :--- | :--- |
| `tripped` > 0 | Breaker сработал | Найти источник через `_nodes/hot_threads` и `_tasks?detailed=true&actions=*search*` |
| `estimated` близок к `limit` | Давление на heap | Проверьте `heap.percent` в `_cat/nodes`; sizing — в [capacity planning](./opensearch_capacity_planning.md) |
| `fielddata.estimated` растет | Кэширование полей | Смотрите `_cat/fielddata`; используйте `.keyword`-подполя вместо fielddata |

```bash
# 2. Найти тяжелые запросы
curl -ku admin:$PASS -k "$OS/_tasks?detailed=true&actions=*search*,*bulk*"

# 3. Размер fielddata по полям
curl -ku admin:$PASS -k "$OS/_cat/fielddata?v"
```

Fielddata на `text`-полях отключена по умолчанию — сортировка и агрегации по анализированному тексту требуют её включения (`"fielddata": true` в маппинге), что является «memory bomb». Правильное решение — агрегировать и сортировать по `.keyword`-подполю. Если fielddata всё же включена и давит на heap, отключите её обновлением маппинга:

```bash
curl -ku admin:$PASS -k -X PUT "$OS/logs-app-default/_mapping" \
-H 'Content-Type: application/json' -d'
{
  "properties": {
    "message": { "type": "text", "fielddata": false }
  }
}'
```

### 7. Диагностика mapping explosion

Сценарий: приложение логирует произвольный JSON, индексация падает с ошибкой лимита полей.

```bash
# 1. Проверить лимит полей
curl -ku admin:$PASS -k "$OS/logs-app-default/_settings?filter_path=**.total_fields.limit"

# 2. Временно поднять лимит (настройка динамическая в OpenSearch)
curl -ku admin:$PASS -k -X PUT "$OS/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{ "index.mapping.total_fields.limit": 5000 }'

# 3. Остановить рост: запретить создание новых полей
curl -ku admin:$PASS -k -X PUT "$OS/logs-app-default/_settings" \
-H 'Content-Type: application/json' -d'
{ "index.mapper.dynamic": false }'

# 4. Постоянное решение: flat_object тип для произвольного JSON
curl -ku admin:$PASS -k -X PUT "$OS/logs-app-default/_mapping" \
-H 'Content-Type: application/json' -d'
{
  "dynamic": "strict",
  "properties": {
    "metadata": { "type": "flat_object" }
  }
}'
```

Если индекс уже «взорвался»: создайте новый индекс с явным маппингом и лимитами, переиндексируйте данные через `_reindex` со скриптом удаления лишних полей, переключите алиас, удалите старый индекс. Поднять лимит — временная мера; каждое поле потребляет heap.

### 8. Диагностика stalled recovery

Сценарий: после отказа узла реплики не восстанавливаются.

```bash
# 1. Найти unassigned шарды
curl -ku admin:$PASS -k "$OS/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason&s=state:desc"

# 2. Активные восстановления
curl -ku admin:$PASS -k "$OS/_cat/recovery?v&active_only=true"

# 3. Получить объяснение
curl -ku admin:$PASS -k "$OS/_cluster/allocation/explain?pretty" \
-H 'Content-Type: application/json' -d'
{ "index": "logs-app-000001", "shard": 0, "primary": false }'
```

Типичные причины:

| Причина | Решение |
| :--- | :--- |
| `NODE_LEFT` | Узел вернулся — ждите восстановления |
| `DECIDED_BY_ALLOCATOR: disk watermark` | Освободите диск (механика watermarks — в [администрировании](./opensearch_administration.md)) |
| `NO_VALID_COPY` | Данные потеряны — восстановите из snapshot |
| `CLUSTER_RECOVERED` | Временное состояние |

```bash
# 4. Ускорить восстановление (дефолты: 40mb/s и 2 параллельных recovery на узел)
curl -ku admin:$PASS -k -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": "200mb",
    "cluster.routing.allocation.node_concurrent_recoveries": 6
  }
}'
```

### 9. Диагностика отклонений записи (429)

Сценарий: отправитель получает `429` с `EsRejectedExecutionException` или `too_many_requests`.

```bash
# 1. Очередь и отказы write-пула
curl -ku admin:$PASS -k "$OS/_cat/thread_pool/write?v&h=name,active,queue,rejected"

# 2. Давление индексации по шардам (coordinating/primary/replica)
curl -ku admin:$PASS -k "$OS/_nodes/stats/shard_indexing_pressure?pretty"

# 3. Heap и breaker'ы
curl -ku admin:$PASS -k "$OS/_cat/nodes?v&h=name,heap.percent,ram.percent,cpu"
curl -ku admin:$PASS -k "$OS/_nodes/stats/breakers?filter_path=**.tripped"
```

Причины отказов записи:

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| Очередь write-пула заполнена | `queue` > 0, `rejected` растет | Уменьшите размер bulk (3–5 МБ) и конкурентность (2–4 потока на узел); увеличьте `refresh_interval` |
| Heap > 95% или breaker | `heap.percent`, `tripped` > 0 | Снизить нагрузку, найти тяжелые запросы, увеличить heap/узлы |
| Shard indexing backpressure | `shard_indexing_pressure` с `rejected` | SegRep лаг (сценарий 5) или медленный flush |
| Проблемы на primary-шарде | Ошибки в логах узла с primary | Проверьте диск и логи конкретного узла |

Размер очереди write-пула задается только в `opensearch.yml` (`thread_pool.write.queue_size`) и не меняется динамически — хронические rejections решаются снижением нагрузки или масштабированием, а не ростом очереди. Добавьте экспоненциальный retry в отправителе.

### 10. Проверка health индекса после проблем

```bash
# 1. Health индекса
curl -ku admin:$PASS -k "$OS/_cluster/health/logs-app-default?pretty"

# 2. Сегменты на диск
curl -ku admin:$PASS -k "$OS/_cat/segments/logs-app-default?v&h=index,shard,segment,size&s=shard"

# 3. Translog
curl -ku admin:$PASS -k "$OS/logs-app-default/_stats/translog?pretty"
```

### 11. Оптимизация bulk-индексации

```bash
# 1. Оптимальный размер: 3–5 МБ, сжатие через Content-Encoding
gzip -c /tmp/bulk.ndjson > /tmp/bulk.ndjson.gz
curl -ku admin:$PASS -k -X POST "$OS/_bulk" \
-H 'Content-Type: application/x-ndjson' -H 'Content-Encoding: gzip' \
--data-binary @/tmp/bulk.ndjson.gz

# 2. Проверить очередь
curl -ku admin:$PASS -k "$OS/_cat/thread_pool/write?v"

# 3. Ограничить параллелизм отправителя
# В приложении: 2–4 одновременных bulk-запроса на data-узел, замер и постепенный рост
```

Тело bulk-запроса должно заканчиваться символом новой строки — иначе `400` с `The bulk request must be terminated by a newline`. Сжатие gzip работает через заголовок `Content-Encoding: gzip` (query-параметра `compression` в API нет); для ответов — `Accept-Encoding: gzip`.

### 12. Мониторинг в Prometheus

Официальный плагин [opensearch-prometheus-exporter](https://github.com/opensearch-project/opensearch-prometheus-exporter) устанавливается на каждый узел и отдает метрики с префиксом `opensearch_`:

```bash
# Установка (версия плагина соответствует версии OpenSearch)
./bin/opensearch-plugin install https://github.com/opensearch-project/opensearch-prometheus-exporter/releases/download/3.9.0.0/prometheus-exporter-3.9.0.0.zip

# Метрики доступны по адресу
curl -ku admin:$PASS -k "$OS/_prometheus/metrics"
```

```yaml
# prometheus.yml
- job_name: opensearch
  scrape_interval: 10s
  metrics_path: "/_prometheus/metrics"
  static_configs:
    - targets: ["os-dt-01:9200", "os-dt-02:9200", "os-dt-03:9200"]
```

Полезные настройки плагина (в `opensearch.yml`): `prometheus.indices: false` — отключить детальные метрики индексов (высокая кардинальность); `prometheus.nodes.filter: "_all"` — отдавать метрики всех узлов с любого узла.

Алерты по верифицированным метрикам экспортёра:

```yaml
groups:
  - name: opensearch_indexing
    rules:
      - alert: OpenSearchIndexingThrottled
        expr: opensearch_indices_indexing_is_throttled_bool > 0
        for: 5m
        labels:
          severity: warning

      - alert: OpenSearchHighHeapUsage
        expr: opensearch_jvm_mem_heap_used_percent > 75
        for: 10m
        labels:
          severity: warning

      - alert: OpenSearchClusterNotGreen
        expr: opensearch_cluster_status != 0
        for: 5m
        labels:
          severity: critical
```

**Важно**: экспортёр не документирует метрики thread pool (rejections, queue) и Segment Replication — для них используйте API: `_cat/thread_pool/write`, `_nodes/stats/shard_indexing_pressure`, `_cat/segment_replication`. Полный список метрик можно получить непосредственно с эндпоинта: `curl -s "$OS/_prometheus/metrics" | grep -oP '^opensearch_\w+' | sort -u`.

## Troubleshooting

Сводная таблица типичных ошибок индексации:

| Ошибка / симптом | Причина | Решение |
| :--- | :--- | :--- |
| `429` `too_many_requests` / `EsRejectedExecutionException` | Переполнена очередь write-пула | Сценарий 9: bulk 3–5 МБ, 2–4 потока, `refresh_interval` |
| `429` `circuit_breaking_exception` | Breaker сработал (агрегация, fielddata, parent) | Сценарий 6: найти тяжелый запрос, `.keyword` вместо fielddata |
| `400` `limit of total fields has been exceeded` | Mapping explosion | Сценарий 7: `flat_object`, `dynamic: strict`, лимит полей |
| `400` `The bulk request must be terminated by a newline` | Нет `\n` в конце NDJSON | Добавить завершающую новую строку в файл |
| Индексация медленная, `iostat` 100% | Merge storm | Сценарий 2: `max_thread_count: 1`, `segments_per_tier: 15` |
| Долгое восстановление после сбоя | Большой translog | Сценарий 3: `flush_threshold.size`, периодический flush |
| Реплики отстают, `rejected_requests` > 0 | SegRep лаг / сеть | Сценарий 5: `segrep.pressure.enabled`, `max_bytes_per_sec` |
| Документы не видны поиску | `refresh_interval: -1` или search-idle | Явный `POST /<index>/_refresh` |
| `400` `json_parse_exception` / `Not in GZIP format` при сжатом bulk | Тело не gzip или нет заголовка | `Content-Encoding: gzip` + `gzip -c` |

## Best Practices

* **Bulk**: 3–5 МБ на запрос, gzip (`Content-Encoding`), 2–4 параллельных потока на data-узел; замер перед ростом.
* **refresh_interval**: `30s` для логов; `-1` только на время массовой загрузки, затем вернуть.
* **Force merge**: только на индексах без записи (лучше — на `read_only`/закрытых); регулярная ротация через ISM делает его редко нужным.
* **Настройки через шаблоны индексов**: `refresh_interval`, `translog`, merge — задавайте в index template, не на живых индексах по одному.
* **Наблюдение**: `rejected` в `_cat/thread_pool/write` и `tripped` в `_nodes/stats/breakers` должны быть нулевыми; алерты — на throttling, heap и статус кластера.
* **SegRep**: включайте для индексов с репликами и высокой записью; помните про общий бюджет `indices.recovery.max_bytes_per_sec` и отсутствие `wait_for` в `_refresh`.
* **Перед изменением лимитов** (полей, breaker'ов, merge) — замерьте базовые метрики, меняйте по одному параметру, наблюдайте 15–30 минут.

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
| `index.translog.flush_threshold.size` | `512mb` | `200mb` — `512mb`; до 25% heap для чистой индексации |
| `index.merge.scheduler.max_thread_count` | `max(1, min(4, процессоры/2))` (SSD), `1` (HDD) | 1 для HDD, дефолт для NVMe |
| `index.merge.scheduler.max_merge_count` | `max_thread_count + 5` (`6` для HDD) | 4–6 при merge storm |
| `index.mapping.total_fields.limit` | `1000` | Поднять только для schema-less JSON |
| `cluster.max_shards_per_node` | `1000` | 20–25 шардов на 1 ГБ heap |
| `indices.memory.index_buffer_size` | `10%` heap (мин. 48 МБ) | До 25% для чистой индексации |
| `indices.recovery.max_bytes_per_sec` | `40mb` | 200mb+ при восстановлении |

### Смотрите также

*   **[OpenSearch: Обзор](./opensearch_overview.md)** — архитектура кластера.
*   **[OpenSearch: Администрирование](./opensearch_administration.md)** — breaker'ы, watermarks, recovery, hot_threads.
*   **[OpenSearch: Capacity Planning](./opensearch_capacity_planning.md)** — sizing узлов и шардов.
*   **[OpenSearch: ISM жизненный цикл](./opensearch_ism_lifecycle.md)** — автоматизация ротации.
*   **[Elasticsearch: Траблшутинг индексации](../Elasticsearch/elasticsearch_troubleshooting_indexing.md)** — сравнение подходов.
*   **[Query DSL и поиск](./opensearch-query-dsl-search.md)** — ошибки result window, term-запросов, счётчиков total.
*   **[Mapping и индексация](./opensearch-mapping-and-indexing.md)** — strict_dynamic_mapping, mapper_parsing_exception, mapping explosion.
*   **[Ingest Pipelines](./opensearch-ingest-pipelines.md)** — отказы документов из-за процессоров pipeline.
