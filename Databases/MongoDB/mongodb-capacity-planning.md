# Capacity Planning для MongoDB

**Актуально для:** MongoDB 8.0.x / 8.3.x (standalone, Replica Set, Sharded Cluster)

> **Совет по версии:** последний стабильный релиз MongoDB — 8.3 (май 2026); линия 8.0 активно патчится (8.0.29, август 2026). Параметры, описанные ниже, не менялись в 8.x: `cacheSizeGB`, `journal.commitIntervalMs`, `checkpoint` интервал 60с, `oplogMinRetentionHours`. Общая методология — **[Capacity Planning](../../../Concepts/capacity-planning.md)**.

---

## Определения

*   **Capacity Planning** — прогнозирование ресурсов (CPU, RAM, диск, сеть) для поддержания производительности при росте нагрузки. Цель — масштабировать до исчерпания ресурсов, а не после.
*   **Working set (рабочий набор)** — объём данных и индексов, к которым приложение обращается чаще всего. Ключевой параметр для sizing RAM: working set должен помещаться в **WiredTiger Cache** (аналог `innodb_buffer_pool_size` в MySQL).
*   **WiredTiger Cache** — область RAM, где WiredTiger хранит несжатые данные и индексы. По умолчанию `max(50% (RAM - 1GB), 0.256GB)`. Hit ratio цели — > 99%. Проверка: `db.serverStatus().wiredTiger.cache["maximum bytes configured"]`.
*   **Cache Eviction** — вытеснение страниц из WiredTiger Cache при его переполнении. Рост evictions при стабильной нагрузке = working set > cacheSizeGB.
*   **IOPS** — операций ввода-вывода в секунду. Ключевой параметр для sizing диска: чекпоинты (каждые 60с), Journal (каждые 100мс), чтение при cache miss.
*   **Throughput** — пропускная способность: ops/sec (insert/query/update/delete).
*   **Headroom** — запас ресурсов (30–50%) для пиков и роста.
*   **Saturation (насыщение)** — доля использования ресурса. Методология USE: **[Мониторинг](./mongodb-monitoring.md)**.

---

## Базовые концепции

### Четыре ресурса (MongoDB-специфика)

| Ресурс | Ключевой параметр | Метрика | Цель |
| :--- | :--- | :--- | :--- |
| **CPU** | ядра | `serverStatus.cpu`, `mongostat` %CPU | < 70% sustained |
| **RAM** | `cacheSizeGB` | WiredTiger cache hit ratio, evictions | hit ratio > 99%, evictions = 0 |
| **Диск** | IOPS, latency | `iostat -x 1`, checkpoint spikes | latency < 10мс (NVMe), %util < 70% |
| **Сеть** | bandwidth, connections | `serverStatus.network`, `connections` | < 70% bandwidth, connections < 80% лимита |

### Формулы sizing

**RAM:**
```
cacheSizeGB ≈ working_set_size × 1.2 (запас)
Total RAM = cacheSizeGB + OS (1–2 GB) + connections overhead + filesystem cache
```
> WiredTiger использует **двухуровневое кэширование**: WiredTiger Cache (несжатые данные) + Filesystem Cache (сжатые блоки с диска). Оставляйте RAM для filesystem cache — это бесплатно ускоряет чтение.

**Диск (write-нагрузка):**
```
Required IOPS ≈ (writes_per_sec × 2) + (reads_per_sec × (1 - cache_hit_ratio))
```
Основные потребители write IOPS: Journal (commit каждые 100мс), Checkpoints (каждые 60с), Oplog (репликация).

**CPU:**
```
Required cores ≈ peak_ops_per_sec × avg_cpu_per_op × 1.5 (headroom)
```

**Сеть:**
```
Required bandwidth ≈ peak_ops_per_sec × avg_doc_size × (1 + replication_factor)
```

### Когда масштабировать

*   Cache hit ratio < 99% постоянно или рост `wiredTiger.cache.evictions` → увеличить RAM / `cacheSizeGB`.
*   `iostat %util > 70%` или checkpoint spikes → быстрее диск (NVMe) или больше IOPS.
*   CPU > 70% sustained → оптимизировать запросы (COLLSCAN) или добавить ядра.
*   `connections.current` ≈ `maxIncomingConnections` → уменьшить `maxPoolSize` драйвера или увеличить лимит.
*   Диск заполнен > 70% → больше места, архивация (TTL, time-series), или шардирование.

### Контейнеры и VM: sizing памяти

По умолчанию WiredTiger берёт **50% от физической RAM хоста** (минус 1 ГБ), даже если контейнер имеет жёсткий лимит. В Docker/Kubernetes это приводит к OOM-киллам при переполнении узла. Правила:

*   **Контейнер с лимитом RAM** — задавайте `cacheSizeGB` вручную: `cacheSizeGB ≈ 0.5 × memory_limit` (оставьте место для OS, journal, oplog, драйвера).
*   **Без лимитов** — MongoDB 8.x читает cgroup limits, но при неопределённости задавайте значение явно.
*   **Совместное размещение** (MongoDB + приложение на одном узле) — `cacheSizeGB` ≤ 30–40% RAM.
*   Проверка: `db.serverStatus().wiredTiger.cache["maximum bytes configured"]` / 1073741824 → должно соответствовать заданному `cacheSizeGB`.

### Sizing oplog (репликация)

Oplog — основа PITR и репликации. Параметры:

```
replication.oplogSizeMB       # размер oplog (по умолчанию: 5% свободного места, мин 990 МБ, макс 50 ГБ)
storage.oplogMinRetentionHours # минимум retention (по умолчанию 0 — auto-truncate)
```

**Расчёт:**
```
oplogSizeMB ≈ write_throughput_MBs_per_sec × oplog_window_hours × 3600 × 1.2 (запас)
```

*   Oplog Window должен быть ≥ `RPO + время обнаружения инцидента`.
*   При росте oplog — `rs.resizeOplog(sizeMB)` (динамически, без остановки).
*   `oplogMinRetentionHours` полезен, когда oplog переписывается быстрее, чем бэкапы делают снапшоты — предотвращает lost recovery point.

### Sizing для шардированного кластера

*   Каждый шард — отдельный Replica Set с теми же правилами sizing (RAM, диск, oplog).
*   Config servers (CSRS) — минимум 3 узла, каждый с `cacheSizeGB` по расчёту под свой working set (обычно мал — только метаданные шардинга).
*   `mongos` — не требует дисков для данных, но потребляет RAM/CPU для маршрутизации; рекомендуется отдельный узел или размещение на application-инстансах.
*   Общее правило: **шардируйте только после вертикального масштабирования** (RAM/CPU/диск исчерпаны).

---

## Практические сценарии

### 1. Оценка текущего потребления

```javascript
// RAM: WiredTiger cache
db.serverStatus().wiredTiger.cache
// → "bytes currently in the cache", "maximum bytes configured", "evictions"

// Hit ratio (оценка): 1 - bytes_read_into_cache / bytes_requested
db.serverStatus().wiredTiger.cache["bytes read into cache"]
db.serverStatus().wiredTiger.cache["bytes requested from the cache"]

// CPU и память
db.serverStatus().cpu
db.serverStatus().mem
// → { resident, virtual, supported, mapped }

// Соединения
db.serverStatus().connections
// → { current, available, totalCreated, active }

// Сеть
db.serverStatus().network
// → { bytesIn, bytesOut, numRequests }

// Операции
db.serverStatus().opcounters
// → { insert, query, update, delete, getmore, command }
```

```bash
# ОС
vmstat 1 5          # CPU, memory, swap, io
iostat -x 1 5       # disk utilization, await, %util
free -h             # RAM
df -h               # disk space
mongostat --host rs0/mongo-1:27017 --rowcount 60  # ops/sec, queues, flushes
```

### 2. Оценка working set

```javascript
// Размер данных и индексов по БД
db.stats()
// → dataSize, indexSize, storageSize

// Размер коллекции
db.collection.stats()
// → size, storageSize, totalIndexSize

// Оценка working set: если "bytes currently in the cache" стабильно
// близко к "maximum bytes configured" и evictions > 0 —
// working set больше cacheSizeGB
```

**Практическая оценка:** замерьте `wiredTiger.cache["bytes currently in the cache"]` в пиковые часы. Это и есть working set в несжатом виде.

### 3. Прогноз роста

```bash
# Рост данных за период
# Замерьте размер dbPath сейчас и через месяц
du -sh /var/lib/mongodb

# Прогноз: size_next_year = size_now × (1 + monthly_growth)^12
```

```javascript
// Рост коллекций (размер + индексы)
db.collection.stats().size
db.collection.stats().totalIndexSize
```

### 4. Sizing для новой нагрузки

**Исходные данные:** 100 GB working set, 5000 ops/sec, 80% read / 20% write, 500 соединений, avg doc 2 KB.

**RAM:**
```
cacheSizeGB = 100 GB × 1.2 = 120 GB
OS + connections overhead = 4 GB
Total RAM ≈ 128–192 GB (округлить; оставьте ~20% под filesystem cache)
```

**CPU:**
```
peak ops/sec ≈ 5000
Required cores = 5000 × 0.002 (средний CPU на op) × 1.5 ≈ 15 → 16–32 ядра
```

**Диск:**
```
Write IOPS ≈ 5000 × 0.2 × 2 = 2000 IOPS
+ Checkpoint spikes (каждые 60с)
→ NVMe SSD (3000+ IOPS)
```

**Сеть:**
```
5000 ops/sec × 2 KB = 10 MB/s = 80 Mbps → 1 GbE достаточно
+ репликация (×2 для 3-узлового RS) → 240 Mbps
```

### 5. Бенчмаркинг (проверка sizing)

Для измерения реального throughput и latency используйте:

*   **YCSB (Yahoo! Cloud Serving Benchmark)** — стандартный бенчмарк для NoSQL, есть MongoDB binding.
*   **fio** — для проверки дисковой подсистемы (IOPS, latency) до развёртывания MongoDB.
*   **mongoperf** — утилита MongoDB для теста I/O производительности WiredTiger.

```bash
# fio: тест случайной записи (аналог write IOPS MongoDB)
fio --name=randwrite --ioengine=libaio --iodepth=32 \
  --rw=randwrite --bs=4k --direct=1 --size=4G --numjobs=4 \
  --runtime=60 --group_reporting

# mongoperf: тест WiredTiger I/O
mongoperf --fileSizeMB 4096 --syncDelay 0
```

> Общая методология бенчмаркинга: **[Benchmarking](../../../Databases/Concepts/benchmarking.md)** (YCSB, connection pool, capacity planning).

### 6. Мониторинг насыщения (алерты)

```yaml
# Prometheus алерты (см. mongodb-monitoring.md)
- alert: MongoDBCacheEvictions
  expr: rate(mongodb_wiredtiger_cache_evictions[5m]) > 0
  for: 10m

- alert: MongoDBHighIOWait
  expr: rate(node_disk_io_time_seconds_total[5m]) > 0.7

- alert: MongoDBDiskFull
  expr: node_filesystem_avail_bytes{mountpoint="/var/lib/mongodb"} /
    node_filesystem_size_bytes{mountpoint="/var/lib/mongodb"} < 0.3

- alert: MongoDBOplogWindowTooSmall
  expr: mongodb_oplog_window_seconds < 7200   # < 2 часов
  for: 15m
```

### 7. Sizing пула соединений

Каждое соединение на сервере потребляет:

*   ~1 МБ RAM (стек потока + WiredTiger session),
*   1 файловый дескриптор,
*   Ограничение: `wiredTiger.sessionMax` (по умолчанию 16000) и `wiredTiger.reservedSessionMax` (1000).

**Формула:**
```
maxIncomingConnections ≥ driver_maxPoolSize × app_instances + reserved (≥ 1000)
```

*   `net.maxIncomingConnections` — лимит входящих соединений (по умолчанию 128).
*   При `connections.current ≈ maxIncomingConnections` — соединения обрываются; увеличивайте лимит или уменьшайте `maxPoolSize`.
*   Connection pooling (HikariCP, PyMongo, node-mongo) — обязательно; без пула каждое соединение открывается/закрывается при каждом запросе.
*   Sizing пула: **[Connection Strings](./mongodb-connection-strings.md)**.

### 8. Параметры WiredTiger (справка)

| Параметр | По умолчанию | Где задаётся | Комментарий |
| :--- | :--- | :--- | :--- |
| `storage.wiredTiger.engineConfig.cacheSizeGB` | `max(0.5 × (RAM - 1ГБ), 0.256)` | mongod.conf / `--wiredTigerCacheSizeGB` | Диапазон 0.256–10000 ГБ |
| `storage.wiredTiger.engineConfig.cacheSizePct` | 50 | `--wiredTigerCacheSizePct` | Процент от RAM; взаимно исключает `cacheSizeGB` |
| `storage.wiredTiger.engineConfig.journalCompressor` | `snappy` | mongod.conf | `none`/`snappy`/`zlib`/`zstd`; записи ≤ 128 байт не сжимаются |
| `storage.journal.commitIntervalMs` | 100 | mongod.conf | Интервал fsync journal |
| `storage.wiredTiger.engineConfig.directoryForIndexes` | false | mongod.conf | Разносить индексы на отдельный диск |
| `storage.wiredTiger.engineConfig.maxCacheOverflowFileSizeGB` | 0 (неограничено) | mongod.conf | **Устарел, не влияет на работу** (MongoDB 8.x) |
| `replication.oplogSizeMB` | 5% свободного места (мин 990 МБ, макс 50 ГБ) | `rs.resizeOplog()` | Изменяется динамически |
| `storage.oplogMinRetentionHours` | 0 (auto-truncate) | mongod.conf / `--oplogMinRetentionHours` | Минимальное удержание oplog |

---

## Устранение неполадок

### Cache hit ratio < 99% / рост evictions

*   **Причина:** working set > `cacheSizeGB`.
*   **Диагностика:** `db.serverStatus().wiredTiger.cache` — `evictions` растёт, `bytes currently in the cache` ≈ `maximum bytes configured`.
*   **Решение:** увеличить `cacheSizeGB` / RAM; оптимизировать запросы (меньше чтения); архивировать старые данные (TTL, time-series).

### Высокий I/O wait

*   **Причина:** диск не справляется с чекпоинтами/Journal.
*   **Диагностика:** `iostat -x 1` — `%util > 70%`, `await` высокий; `mongotop` — горячие коллекции.
*   **Решение:** NVMe; разнести данные и индексы (`directoryForIndexes: true`); увеличить RAM (меньше cache miss).

### CPU на 100%

*   **Причина:** COLLSCAN (нет индексов), сложные агрегации, высокая конкуренция.
*   **Диагностика:** `mongostat` — %CPU; `db.currentOp()`; `system.profile` — `planSummary: "COLLSCAN"`.
*   **Решение:** создать индексы (ESR-правило); оптимизировать агрегации (`allowDiskUse`, `$match` early); добавить ядра.

### Connection saturation

*   **Причина:** `maxPoolSize` драйвера × N инстансов > `maxIncomingConnections`.
*   **Диагностика:** `db.serverStatus().connections` — `current` ≈ `available + current`.
*   **Решение:** уменьшить `maxPoolSize` (см. **[Connection Strings](./mongodb-connection-strings.md)**); увеличить `net.maxIncomingConnections`; connection pooling.

### Oplog Window < RPO

*   **Причина:** oplog переписывается быстрее, чем бэкапы делают снапшоты, или oplog_sizeMB слишком мал.
*   **Диагностика:** `rs.printReplicationInfo()` — `log length start to end` в секундах; сравнить с RPO.
*   **Решение:** увеличить `rs.resizeOplog(sizeMB)`; включить `storage.oplogMinRetentionHours`; увеличить частоту full backup.

### OOM при росте working set

*   **Причина:** `cacheSizeGB` фиксирован, а working set растёт; или контейнер без лимита и WiredTiger забирает всю RAM хоста.
*   **Диагностика:** `db.serverStatus().wiredTiger.cache` — `evictions` растёт; `db.serverStatus().mem` — `resident` приближается к лимиту.
*   **Решение:** задать `cacheSizeGB` явно (особенно в K8s/Docker); увеличить RAM; архивировать старые данные (TTL, time-series); шардировать.

---

## Лучшие практики (Best Practices)

1.  **Working set в RAM:** `cacheSizeGB` ≥ working set. Это правило №1 для MongoDB.
2.  **Headroom 30–50%:** планируйте с запасом под пики и рост.
3.  **Мониторьте насыщение (USE)** — алерты до исчерпания ресурсов.
4.  **Прогнозируйте рост** — замеряйте размер данных ежемесячно.
5.  **NVMe для write-нагрузки** — Journal и чекпоинты чувствительны к IOPS.
6.  **Задавайте `cacheSizeGB` явно** — особенно в контейнерах (иначе OOM при переполнении узла).
7.  **Не завышайте `maxPoolSize`** — каждое соединение потребляет RAM и файловые дескрипторы на сервере.
8.  **Sizing oplog под RPO** — `oplogSizeMB` и `oplogMinRetentionHours` должны покрывать RPO + время обнаружения.
9.  **Бенчмарк перед продом** — YCSB/fio на репрезентативной нагрузке.
10. **Шардирование — последнее средство:** сначала вертикальное масштабирование (RAM/CPU/диск), потом горизонтальное.

---

## Дополнительная информация

*   **[Движок WiredTiger](./mongodb-storage-engine.md)** — кэширование, чекпоинты, `cacheSizeGB`.
*   **[Мониторинг](./mongodb-monitoring.md)** — USE-методология, алерты.
*   **[Connection Strings](./mongodb-connection-strings.md)** — sizing пула.
*   **[Capacity Planning (общая теория)](../../../Concepts/capacity-planning.md)** — методология.
*   **[Benchmarking (общая теория)](../../../Databases/Concepts/benchmarking.md)** — YCSB, connection pool.
*   **[Capacity Planning MariaDB](../../MariaDB/capacity_planning.md)** — аналогичная тема для MariaDB.
*   [MongoDB Capacity Planning](https://www.mongodb.com/docs/manual/administration/capacity-planning/)
*   [WiredTiger Cache Sizing](https://www.mongodb.com/docs/manual/reference/configuration-options/#mongodb-setting-storage.wiredTiger.engineConfig.cacheSizeGB)
*   [MongoDB Configuration Options](https://www.mongodb.com/docs/manual/reference/configuration-options/)
