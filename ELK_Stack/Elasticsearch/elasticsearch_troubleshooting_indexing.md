# Elasticsearch: Траблшутинг индексации и сегментов

**Актуально для:** Elasticsearch 8.x / 9.x

> Заметка посвящена диагностике проблем индексации: медленной записи, перегрева heap, merge throttling, роста сегментов и translog-заторов. Базовые понятия кластера (шарды, refresh, flush, translog) описаны в [обзоре Elasticsearch](./elasticsearch_overview.md); настройка жизненного цикла — в [ILM и политиках хранения](./elasticsearch_ilm_and_retention.md).

## Определения

* **Merge (Слияние)** — фоновый процесс объединения мелких сегментов Lucene в крупные. Политика слияний по умолчанию — `TieredMergePolicy` (настройки `index.merge.policy.*`); для time-based данных (data streams) с 8.8 используется `LogByteSizeMergePolicy` с merge factor 32. Выполнением управляет merge scheduler (`index.merge.scheduler.*`), merges выполняются в выделенном `merge` thread pool.
* **Merge Throttling (Ограничение слияний)** — механизм, при котором Lucene снижает приоритет merge-потоков при высокой нагрузке на индексацию, чтобы не конкурировать за I/O и CPU с записью новых документов. Merges дополнительно throttled по диску: всплески сглаживаются, чтобы не влиять на throughput индексации.
* **Segment (Сегмент)** — минимальная неделимая единица хранения Lucene. Каждый шард — набор неизменяемых сегментов; при индексации новые документы попадают в буфер, а затем в новый сегмент после refresh.
* **Translog (Журнал упреждающей записи)** — WAL для гарантии durability. Flush (Lucene commit + новая генерация translog) выполняется автоматически при превышении `index.translog.flush_threshold_size` (дефолт **10 ГБ с 8.8**, ранее 512 МБ) или по возрасту `index.translog.flush_threshold_age` (дефолт **1 минута с 8.8**, final-настройка — задаётся при создании индекса). Размер translog никогда не превышает 1% диска.
* **Indexing Buffer (Буфер индексации)** — in-memory область на узле, разделяемая между всеми шардами (`indices.memory.index_buffer_size`, static, дефолт 10% heap). При заполнении буфера документы записываются в сегмент на диск (по сути — refresh); ошибок при этом не возникает.
* **Refresh Interval** — период, через который содержимое буфера становится видимым для поиска (по умолчанию `1s`). Увеличение интервала снижает количество сегментов и нагрузку на merge. Нюанс: авто-refresh раз в 1s применяется только к индексам, получавшим хотя бы один поисковый запрос за последние 30 секунд.
* **Circuit Breaker (Размыкатель)** — защита JVM heap от OOM. Breaker'ы: `request` (структуры данных запроса, aggregations; лимит 60% heap), `fielddata` (загрузка fielddata; 40% heap), `in_flight_requests` (буферы активных входящих запросов; 100% heap), `accounting` (память, удерживаемая после завершения запроса — например, память сегментов Lucene; 100% heap) и родительский `parent` (`indices.breaker.total.limit`; 95% heap при `indices.breaker.total.use_real_memory: true`, дефолт). Подробности — в [Search Tuning](./elasticsearch_search_tuning.md).
* **Thread Pool (Пул потоков)** — очередь задач на индексацию (`write`: fixed, size = число процессоров, queue_size 10000 в 8.x), поиск (`search`: fixed, size = int(cores×3/2)+1, queue_size 1000), merge (`merge`: fixed, size 1, очередь без ограничений). При переполнении bounded-очереди задачи отклоняются с `429` (`es_rejected_execution_exception`). Настройки thread pool — static (elasticsearch.yml).
* **Force Merge** — принудительное слияние сегментов до заданного числа (`max_num_segments`). Для индексов, куда запись завершена, это уменьшает количество открытых файлов и ускоряет поиск. Выполнять только на read-only (или закрытых) индексах.
* **Segment Replication (OpenSearch)** — репликация готовых сегментов Lucene с primary на реплики, снижающая нагрузку на CPU при индексации. В Elasticsearch аналогом является стандартная document-level репликация.

## Основные концепции

### Жизненный цикл документа и сегментов

1. Документ попадает в **memory buffer** и **translog**.
2. **Refresh** создает новый сегмент Lucene из буфера. Документ становится видимым для поиска.
3. **Merge** фоновыми потоками сливает мелкие сегменты в крупные, удаляя помеченные на удаление документы.
4. **Flush** сбрасывает сегменты на диск и обрезает translog.

Ключевое последствие: сегменты неизменяемы. Частые точечные обновления создают множество мелких сегментов, что тормозит поиск и увеличивает нагрузку на merge.

### Настройки merge и производительности

| Параметр | Назначение | Дефолт / рекомендация |
| :--- | :--- | :--- |
| `index.merge.policy.max_merged_segment` | Максимальный размер сегмента после merge | `5gb` — предотвращает создание гигантских сегментов, которые долго открывать |
| `index.merge.policy.segments_per_tier` | Число сегментов одного размера перед merge | `10.0` — баланс между скоростью записи и числом сегментов |
| `index.merge.policy.max_merge_at_once` | Число сегментов, сливаемых за один обычный merge | `10` (для явного force merge — `max_merge_at_once_explicit`, дефолт `30`) |
| `index.merge.policy.floor_segment` | Сегменты меньше этого размера округляются до него | `2mb` — защита от длинного хвоста мелких сегментов |
| `index.merge.policy.reclaim_deletes_weight` | Вес удалённых документов при выборе merge | `2.0` |
| `index.merge.scheduler.max_thread_count` | Число merge-потоков на одном шарде | Дефолт — половина процессоров JVM (min 1), хорошо для SSD; `1` для HDD |
| `index.merge.scheduler.max_merge_count` | Лимит merge-заданий, выполняемых или ожидающих на одном шарде | Дефолт — `max_thread_count + 5` |
| `indices.merge.disk.watermark.high` | Порог занятости диска, выше которого не стартуют новые merges | `95%` |
| `index.refresh_interval` | Частота создания новых сегментов | `30s` — `60s` для логов; `-1` для массовой загрузки |

### Мониторинг индексации

| Метрика | API | Норма |
| :--- | :--- | :--- |
| Скорость индексации | `GET _cat/nodes?v&h=name,indexing.index_total,indexing.index_time` | Зависит от hardware |
| Очередь merge | `GET _cat/thread_pool/merge?v&h=name,active,queue,rejected` | `rejected` = 0; `active` ≤ `max_thread_count` на шард |
| Размер сегментов | `GET _cat/segments/<index>?v&bytes=gb` | Количество сегментов < 50 на шард |
| Translog | `GET _nodes/stats/indices` (секция `translog`) | `size` до 10 ГБ (flush threshold) — норма для 8.8+ |
| Heap и буфер | `GET _cat/nodes?v&h=name,heap.percent,ram.percent` | `heap.percent` < 75%; буфер индексации — 10% heap на узел, разделяемый между шардами |
| Circuit Breaker | `GET /_nodes/stats/breaker` | `tripped` = 0; `estimated_size` < `limit_size` |
| Write rejections | `GET _cat/thread_pool/write?v&h=name,queue,active,rejected,completed` | `rejected` = 0 в стабильном состоянии |

### Типовые паттерны проблем

**Merge Storm**: фоновые merge-потоки потребляют всю I/O, замедляя запись и поиск. Проявляется в `iostat` как 100% `%util` диска и в `_cat/thread_pool/merge` как активные `merge`-потоки.

**Indexing Buffer Pressure**: при быстрой индексации буфер заполняется быстрее, чем успевает сбрасываться в сегменты. Признак — рост `indexing.index_current` и частые refresh; сам по себе переполнение буфера ошибок не вызывает — ES принудительно записывает буфер в сегмент.

**Translog Growth**: при быстрой записи translog растёт до порога flush (10 ГБ или 1 минута с 8.8). Проблема не в размере как таковом, а в времени восстановления шарда: чем старше незакоммиченные операции, тем дольше replay при recovery.

**Circuit Breaker Trip**: крупная агрегация или fielddata превышают лимит heap. Признак — ошибки `429` с `circuit_breaking_exception`.

**Mapping Explosion**: динамическое создание тысяч полей в произвольном JSON. Признак — ошибка `Limit of total fields [1000] has been exceeded`.

**Write Rejections (429)**: переполнена bounded-очередь `write` thread pool (queue_size 10000 в 8.x). Признак — `es_rejected_execution_exception` в ответах bulk и в логах; `rejected` > 0 в `_cat/thread_pool/write`.

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
| `rejected` > 0 | Отклонены задачи индексации | Уменьшите конкурентность на стороне отправителя или добавьте узлы; увеличение `write` pool обычно снижает throughput. `indices.memory.index_buffer_size` — static-настройка (elasticsearch.yml + restart), меняйте её только после анализа heap |
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

# 2. Временно ограничить merge на проблемном индексе (это index-level настройки)
curl -u elastic:$PASS -k -X PUT "$ES/<индекс>/_settings" \
-H 'Content-Type: application/json' -d'
{
  "index": {
    "merge": {
      "scheduler": {
        "max_thread_count": 1,
        "max_merge_count": 6
      }
    }
  }
}'
# → {"acknowledged":true}
```

Пояснения:

* `max_thread_count: 1` — один merge-поток на шард одновременно. Для HDD это стандарт; дефолт (половина процессоров, min 1) хорошо работает на SSD/NVMe.
* `max_merge_count` — лимит merge-заданий, выполняемых или ожидающих на одном шарде; дефолт `max_thread_count + 5`. Значение должно быть ≥ `max_thread_count`, иначе ES приведёт `max_thread_count` к `max_merge_count` при открытии индекса и запишет warning в лог.
* Merges не начинаются при занятости диска выше `indices.merge.disk.watermark.high` (дефолт `95%`) — проверьте `_cat/allocation`, если merges остановились.
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

| Показатель | Норма (8.8+) | Проблема |
| :--- | :--- | :--- |
| `operations` | Растёт до flush (порог 10 ГБ или 1 минута) | Миллионы операций с большим возрастом — replay при recovery будет долгим |
| `size` | До 10 ГБ (flush threshold) и ≤ 1% диска | Постоянно на пороге при малой записи — проверьте `flush_threshold_age` |
| `unreferenced` | 0 | > 0 — обрезанный translog не удален |

```bash
# 2. Ускорить recovery: сбрасывать translog чаще (динамическая index-level настройка)
curl -u elastic:$PASS -k -X PUT "$ES/<индекс>/_settings" \
-H 'Content-Type: application/json' -d'
{
  "index": {
    "translog.flush_threshold_size": "1gb"
  }
}'
# → {"acknowledged":true}
```

Пояснения:

* `translog.flush_threshold_size` — flush при превышении размера translog. Дефолт **10 ГБ с 8.8** (ранее 512 МБ); реальный порог никогда не превышает 1% диска. Понижение порога (как в примере) сокращает время replay при recovery ценой более частых flush (больше I/O); для быстрой записи обычно оставляют дефолт.
* `translog.flush_threshold_age` — flush не реже чем раз в `1m` (дефолт с 8.8). Это **final**-настройка: задаётся только при создании индекса, на живом индексе не меняется.
* Долгое восстановление шарда лечится именно порогами flush. `index.translog.retention.size` (дефолт 512mb) и `index.translog.retention.age` (дефолт 12h) управляют тем, как долго незакоммиченные операции хранятся для peer recovery реплик.
* Настройка применяется на уровне индекса (`PUT /<индекс>/_settings`), а не через cluster settings.
* Механика refresh/flush/translog подробно описана в [Индексировании и маппинге](./elasticsearch_mapping_and_indexing.md#процесс-индексирования-refresh-flush-и-translog).

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

Эффект: refresh — дорогая операция, и при отключении интервала не создаются мелкие сегменты во время bulk-загрузки, что снижает нагрузку на merge и I/O. После загрузки возвращайте `refresh_interval` не менее `30s` — это снижает фоновую нагрузку на merge. Не забудьте вернуть интервал: с `-1` документы не будут видны в поиске до явного `_refresh`.

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
# → {"acknowledged":true}
```

При повышении лимита рекомендуется также поднять `indices.query.bool.max_clause_count` (лимиты кластерных запросов). Постоянное решение — одна из стратегий:

* `dynamic: strict` — новые поля отклоняются явной ошибкой (подходит, когда схема известна);
* `flattened` — весь объект с произвольным набором ключей индексируется как одно поле;
* `index.mapping.total_fields.ignore_dynamic_beyond_limit: true` — поля за лимитом не добавляются в маппинг, а попадают в метаполе `_ignored` (индексация не падает).

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
# → {"acknowledged":true}
```

### 6. Диагностика circuit breaker и heap pressure

Сценарий: в логах Elasticsearch появляются `circuit_breaking_exception`, запросы падают с `429`.

```bash
# 1. Проверить статус breaker'ов
curl -u elastic:$PASS -k "$ES/_nodes/stats/breaker?pretty"
```

```json
{
  "breakers": {
    "request": {
      "limit_size_in_bytes": 6442450944,
      "limit_size": "6gb",
      "estimated_size_in_bytes": 209715200,
      "estimated_size": "200mb",
      "overhead": 1.0,
      "tripped": 0
    },
    "fielddata": {
      "limit_size_in_bytes": 4294967296,
      "limit_size": "4gb",
      "estimated_size_in_bytes": 92727,
      "estimated_size": "90.5kb",
      "overhead": 1.03,
      "tripped": 15
    }
  }
}
```

| Показатель | Признак проблемы | Действие |
| :--- | :--- | :--- |
| `tripped` > 0 | Breaker сработал | Найти источник через `hot_threads` и `_tasks` |
| `estimated_size` близок к `limit_size` | Давление на heap | Увеличить heap до 31 ГБ (compressed oops) или добавить узлы |
| `fielddata.estimated_size` растёт | Fielddata загружен в heap | Агрегации/sort переносить на `keyword`-подполя; очистить кэш (шаг 3) |

```bash
# 2. Найти тяжелые запросы/агрегации
curl -u elastic:$PASS -k "$ES/_tasks?detailed=true&actions=*search*,*bulk*"
```

```bash
# 3. Очистить fielddata-кэш (выгружает fielddata из heap)
curl -u elastic:$PASS -k -X POST "$ES/logs-app-default/_cache/clear?fielddata=true"
# → {"_shards":{"total":2,"successful":2,"failed":0}}
```

Пояснения:

* Дефолты breaker'ов: `indices.breaker.request.limit` — 60% heap, `indices.breaker.fielddata.limit` — 40% heap, `network.breaker.inflight_requests.limit` — 100% heap, `indices.breaker.accounting.limit` — 100% heap, `indices.breaker.total.limit` — 95% heap (при `indices.breaker.total.use_real_memory: true`, дефолт; иначе 70%).
* `fielddata` на text-полях отключён по умолчанию и включается только через PUT mapping (`"fielddata": true` на конкретном text-поле) — настройки уровня индекса для этого не существует. text-поля не поддерживают `doc_values`, поэтому для агрегаций и сортировки используйте `keyword`-подполе (multi-field).
* Fielddata, однажды загруженный, остаётся в heap на время жизни сегмента; очистка кэша (шаг 3) выгружает его, но следующая агрегация загрузит снова.

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
| 50–100 | Выполнить `_forcemerge` на read-only/закрытых индексах |
| > 100 | Критично: увеличить `refresh_interval` или `segments_per_tier`, затем force merge на закрытом индексе |

```bash
# 2. Принудительный merge для завершённых (read-only) индексов
curl -u elastic:$PASS -k -X PUT "$ES/logs-app-000001/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "blocks": { "read_only": true } } }'
# → {"acknowledged":true}

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
# → {"acknowledged":true}
```

Пояснения:

* `indices.recovery.max_bytes_per_sec` — дефолт `40mb` (40 МиБ/с на узел; на cold/frozen узлах масштабируется с памятью до 250 МиБ/с). Лимит применяется к каждому узлу отдельно.
* `cluster.routing.allocation.node_concurrent_recoveries` — дефолт `2` (одновременных peer-recovery на узел); `cluster.routing.allocation.node_initial_primaries_recoveries` — дефолт `4`.
* После восстановления верните значения к дефолтам (`"indices.recovery.max_bytes_per_sec": null`), иначе recovery будет постоянно насыщать сеть.

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
# 2. Проверить, что сегменты синхронизированы с диском
curl -u elastic:$PASS -k "$ES/_cat/segments/logs-app-default?v&h=index,shard,segment,docs.count,size,committed,searchable&s=shard"
# → committed=true означает, что сегмент synced на диск и переживёт жёсткую перезагрузку;
#   searchable=false — сегмент записан, но требует refresh для поиска
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
# Пример bulk с gzip-сжатием тела (сжатие — через HTTP-заголовок, а не query-параметр):
gzip -c /tmp/bulk.ndjson > /tmp/bulk.ndjson.gz
curl -u elastic:$PASS -k -X POST "$ES/_bulk?refresh=false" \
-H 'Content-Type: application/x-ndjson' -H 'Content-Encoding: gzip' --data-binary @/tmp/bulk.ndjson.gz
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

Ключевые метрики для отслеживания индексации. Ниже — имена метрик exporter'а [prometheus-community/elasticsearch_exporter](https://github.com/prometheus-community/elasticsearch_exporter); x-pack monitoring exporter использует другие имена — сверьтесь с его документацией.

Полезные метрики: `elasticsearch_indices_indexing_index_total` (всего index-операций), `elasticsearch_indices_indexing_index_time_seconds_total`, `elasticsearch_indices_indexing_throttle_time_seconds_total` и `elasticsearch_indices_indexing_is_throttled` (throttling индексации), `elasticsearch_thread_pool_rejected_count` / `elasticsearch_thread_pool_queue_count` / `elasticsearch_thread_pool_active_count` (по пулам, включая `write` и `merge`), `elasticsearch_breakers_tripped` / `elasticsearch_breakers_estimated_size_bytes` / `elasticsearch_breakers_limit_size_bytes`, `elasticsearch_indices_translog_size_in_bytes` и `elasticsearch_indices_translog_operations`, `elasticsearch_indices_merges_total` и `elasticsearch_indices_merges_total_throttled_time_seconds_total`, `elasticsearch_indices_refresh_total`, `elasticsearch_indices_segments_count`, `elasticsearch_cluster_health_number_of_pending_tasks`, `elasticsearch_jvm_memory_used_bytes` / `elasticsearch_jvm_memory_max_bytes`.

```yaml
groups:
  - name: elasticsearch_indexing
    rules:
      - alert: ElasticsearchWriteRejected
        expr: rate(elasticsearch_thread_pool_rejected_count[5m]) > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Запись отклоняется (thread pool rejections) на {{ $labels.cluster }}"

      - alert: ElasticsearchCircuitBreakerTripped
        expr: rate(elasticsearch_breakers_tripped[5m]) > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Circuit breaker сработал на {{ $labels.cluster }}"

      - alert: ElasticsearchIndexingThrottled
        expr: elasticsearch_indices_indexing_is_throttled == 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Индексация throttled (merge отстаёт от записи) на {{ $labels.cluster }}"

      - alert: ElasticsearchTranslogNearFlushThreshold
        expr: elasticsearch_indices_translog_size_in_bytes > 8 * 1024 * 1024 * 1024
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Translog близок к порогу flush (10 ГБ) на {{ $labels.cluster }}"
```

## Дополнительная информация

### Типовые настройки для production

Для индексов с высокой нагрузкой на запись:

```json
{
  "settings": {
    "index": {
      "refresh_interval": "30s",
      "translog": {
        "durability": "request",
        "flush_threshold_size": "10gb"
      },
      "merge": {
        "policy": {
          "max_merged_segment": "5gb",
          "segments_per_tier": 10.0
        },
        "scheduler": {
          "max_thread_count": 1,
          "max_merge_count": 6
        }
      }
    }
  }
}
```

Для массовой загрузки (one-time):

```json
{
  "settings": {
    "index": {
      "refresh_interval": "-1",
      "number_of_replicas": 0,
      "translog": {
        "durability": "async"
      }
    }
  }
}
```

Пояснения:

* `durability: async` при bulk-загрузке ускоряет запись, но при сбое теряются все операции с момента последнего `sync_interval` (дефолт 5s) — используйте только для данных, которые можно перезагрузить.
* `flush_threshold_size: 10gb` и `max_merge_count: 6` (= дефолт `max_thread_count + 5` при `max_thread_count: 1`) совпадают с дефолтами 8.8+ и приведены для явности.
* После загрузки верните настройки (`"index.refresh_interval": null` сбрасывает к дефолту) и выполните `_forcemerge` — только на read-only индексе.

### Ограничения и лимиты

| Параметр | По умолчанию | Рекомендация |
| :--- | :--- | :--- |
| `index.refresh_interval` | `1s` (только для индексов с поисковыми запросами за последние 30s) | `30s` — `60s` для логов; `-1` для bulk |
| `index.translog.flush_threshold_size` | `10gb` (с 8.8; ранее `512mb`) | Оставить по умолчанию; понижение увеличивает частоту flush |
| `index.translog.flush_threshold_age` | `1m` (с 8.8, final-настройка) | Задаётся при создании индекса; не меняется на живом индексе |
| `index.merge.scheduler.max_thread_count` | половина процессоров JVM (min 1) | `1` для HDD; дефолт хорошо работает на SSD/NVMe |
| `index.merge.scheduler.max_merge_count` | `max_thread_count + 5` (на шард) | Оставить по умолчанию; значение ≥ `max_thread_count` |
| `indices.merge.disk.watermark.high` | `95%` | Следить через `_cat/allocation`: выше порога merges не стартуют |
| `indices.recovery.max_bytes_per_sec` | `40mb` на узел | Повышать временно при recovery; вернуть к дефолту после |
| `cluster.routing.allocation.node_concurrent_recoveries` | `2` | Повышать временно при recovery |
| `index.mapping.total_fields.limit` | 1000 | Поднять до 5000 только для schema-less JSON; вместе с ним — `indices.query.bool.max_clause_count` |
| `indices.memory.index_buffer_size` | 10% heap (static, на узел, разделяется между шардами) | Оставить по умолчанию; при тяжёлой индексации — до 512 МБ буфера на активный шард |

### Граничные случаи

* **Force merge на пишущемся индексе** — создаёт гигантские сегменты, которые потом не сливаются; `_forcemerge` только на read-only или закрытых индексах. Сегменты больше 5 ГБ не участвуют в обычных merge.
* **Translog и 1% диска** — даже при `flush_threshold_size: 10gb` реальный порог ограничен 1% диска; на маленьких дисках flush будет происходить чаще.
* **Refresh без поиска** — индексы, не получавшие поисковых запросов 30+ секунд, не refreshatся каждую секунду (оптимизация throughput); документы появятся в поиске после первого запроса или явного `_refresh`.
* **`write` thread pool** — очередь 10000 в 8.x; увеличение размера pool обычно снижает общий throughput индексации, лучше уменьшить конкурентность клиента или добавить узлы.
* **Recovery и translog** — при восстановлении шарда replay идёт последовательно; 1 минута индексации на одном шарде может восстанавливаться значительно дольше минуты на узле с десятками шардов (recovery не полностью параллелен).
* **Merge и диск** — merges требуют временного дискового пространства; при занятости выше `indices.merge.disk.watermark.high` (95%) новые merges не стартуют, а индексация может быть throttled, пока merge не догонит запись.

### Cleanup — возврат настроек и удаление тестовых артефактов

```bash
# 1. Вернуть index-level настройки к дефолтам (null = дефолт)
curl -u elastic:$PASS -k -X PUT "$ES/historical-logs/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "refresh_interval": null, "translog.flush_threshold_size": null } }'
# → {"acknowledged":true}

# 2. Вернуть cluster-level настройки recovery
curl -u elastic:$PASS -k -X PUT "$ES/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{ "persistent": {
  "indices.recovery.max_bytes_per_sec": null,
  "cluster.routing.allocation.node_concurrent_recoveries": null
} }'
# → {"acknowledged":true}

# 3. Снять read-only после force merge
curl -u elastic:$PASS -k -X PUT "$ES/logs-app-000001/_settings" \
-H 'Content-Type: application/json' -d'
{ "index": { "blocks": { "read_only": false } } }'
# → {"acknowledged":true}

# 4. Удалить тестовые индексы и локальные файлы
curl -u elastic:$PASS -k -X DELETE "$ES/logs-app-default"
# → {"acknowledged":true}
rm -f /tmp/bulk.ndjson /tmp/bulk.ndjson.gz
```

Проверка: `GET _cluster/settings?include_defaults=true&filter_path=**.max_bytes_per_sec` не должен показывать переопределение; `GET <индекс>/_settings` — явно заданных `refresh_interval`/`flush_threshold_size` быть не должно (значение отсутствует = дефолт).

### Смотрите также

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера и lifecycle документа.
*   **[Elasticsearch: Жизненный цикл (ILM)](./elasticsearch_ilm_and_retention.md)** — автоматизация ротации данных.
*   **[Elasticsearch: Индексирование и маппинг](./elasticsearch_mapping_and_indexing.md)** — схемы данных и bulk API.
*   **[Настройка кластера Elasticsearch](../Tutorials/cluster_setup.md)** — системный тюнинг и Bootstrap Checks.
*   **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — метрики для диагностики.
*   **[Search Performance Tuning](./elasticsearch_search_tuning.md)** — оптимизация поиска.
*   **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — обработка документов.
