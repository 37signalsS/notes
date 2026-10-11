# Тюнинг производительности

**Актуально для:** Apache Cassandra 4.0/5.0.x / ScyllaDB 2026.x

## Определения

| Термин | Определение |
| :--- | :--- |
| Heap | Область памяти JVM, где живут объекты Cassandra; размер задаётся парой `-Xms`/`-Xmx` |
| GC pause (STW) | Пауза «stop-the-world» — сборщик мусора останавливает обработку запросов; главный источник tail latency в Cassandra |
| Key Cache | Кэш индексов SSTables на heap; попадание экономит одно обращение к диску |
| Row Cache | Кэш целых строк (off-heap, OHCProvider); выключен по умолчанию — оправдан только для горячих строк |
| Chunk Cache (file cache) | Кэш недавно читаемых блоков SSTable в виде распакованных буферов (off-heap) |
| Read amplification | Множество SSTables и tombstones, которые нужно прочитать для ответа на один запрос |
| Write amplification | Многократная перезапись данных при compaction |
| iotune | Инструмент Seastar/ScyllaDB, измеряющий возможности диска и сохраняющий результат в `io_properties.yaml` |
| Scheduling Groups | Механизм изоляции Seastar: ScyllaDB приоритизирует latency-чувствительные запросы перед compaction/streaming |

Термины Memtable, Tombstone, SSTable, gc_grace_seconds, Repair, Compaction определены в [Обслуживании и эксплуатации](./operations.md).

## Как устроена производительность

**Путь записи:** commitlog (durability) → memtable → SSTable. **Путь чтения:** memtable → Bloom filter → partition index → слияние версий строк с применением tombstones (теория — в [Обзоре](./overview.md) и [Обслуживании](./operations.md)).

**Почему тюнинг нужен:** Cassandra поставляется с консервативными дефолтами, выбранными для безопасного старта на скромном железе, а не для производительности: compaction ограничена по throughput, пулы потоков рассчитаны на малый хост, OS-настройки — какие даёт дистрибутив. Эти дефолты подходят для знакомства с СУБД, но не для production.

**Ключевое различие философий:**

| | Cassandra | ScyllaDB |
| :--- | :--- | :--- |
| Движок | JVM (Java) | Seastar (C++, shards-per-core) |
| Тюнинг | Ручной: heap, GC, пулы, кэши | Автоматический: память, I/O, планировщик |
| Планировщик I/O | OS + Cassandra-пулы | Собственный userspace I/O scheduler |
| Главный рычаг | Размер heap и GC | Не мешать авто-тюнингу; железо и клиентские соединения |

ScyllaDB тюнингует себя сама: память забирается под кэши автоматически, I/O планируется в userspace с приоритизацией. Задача оператора ScyllaDB — корректно запустить `scylla_setup`, подобрать железо и не работать против системы.

## Cassandra: JVM Heap

**Файлы конфигурации JVM** (разные по релизам):

| Файл | Когда читается | Содержит |
| :--- | :--- | :--- |
| `jvm-server.options` | Всегда | Настройки для всех поддерживаемых JDK; закомментированная пара `-Xmx`/`-Xms` |
| `jvm11-server.options` | JDK 11 (4.0/4.1/5.0) | Сборщик мусора и его настройки |
| `jvm17-server.options` | JDK 17 (только 5.0) | Сборщик мусора для JDK 17 |

**Размер heap вычисляется автоматически** скриптом `cassandra-env.sh` при каждом старте:

- **Cassandra 4.0/4.1:** `max(min(1/2 RAM, 1024MB), min(1/4 RAM, 8GB))`
- **Cassandra 5.0.4+ (CASSANDRA-20296):** половина физической RAM, кап 16G (CMS) / 31G (G1) — значение, перенесённое из 4.x, на 5.0.4+ неверно в одну из сторон

**Сборщик мусора по умолчанию:**

| Версия | Дефолт | Примечание |
| :--- | :--- | :--- |
| 4.0 / 4.1 | CMS (Concurrent Mark Sweep) | Настроенный блок G1 закомментирован в том же файле |
| 5.0+ | G1 (CASSANDRA-18027) | CMS удалён из JDK 14+ |

**Правила задания heap:**

- `-Xms` и `-Xmx` должны быть заданы **оба или ни одного** (иначе узел не стартует); альтернатива — переменные окружения `MAX_HEAP_SIZE` и `HEAP_NEWSIZE`
- Рекомендуется `Xms = Xmx`, чтобы избежать STW-пауз при ресайзе и зафиксировать heap в памяти
- Heap: не менее 2GB и не более 50% RAM системы; **< 12GB → ParNew/CMS; > 12GB → G1**; 31GB — оптимум для compressed oops
- Не задавайте `-Xmn` (young gen) при G1 — это ломает целевое время паузы

**G1-тюнинг** (раскомментировать в `jvm11-server.options` / `jvm17-server.options`):

```bash
-XX:+UseG1GC
-XX:MaxGCPauseMillis=500        # в файле по умолчанию; 200 мс — минимум JVM, 1000 мс — больше throughput
                                # всегда меньше таймаутов cassandra.yaml
-XX:InitiatingHeapOccupancyPercent=70   # экономит CPU на heap >= 16GB
# -XX:ParallelGCThreads=16      # по числу ядер; > 10 ядер — попробуйте <= полного числа ядер
# -XX:ConcGCThreads=16          # по умолчанию 1/4 от ParallelGCThreads
# -XX:G1RSetUpdatingPauseTimePercent=5   # из бенчмарков TheLastPickle для больших heap
```

**Логи и дампы:** GC-лог — `-Xlog:gc` в `gc.log`, ротация 10 файлов по 10MiB; heap dump при OOM — `CASSANDRA_HEAPDUMP_DIR` (укажите на файловую систему с местом под полный heap, иначе dump заполнит диск с `system.log`); действие при OOM — `kill -9`. Пороги логирования GC: `gc_log_threshold_in_ms: 200`, `gc_warn_threshold_in_ms: 1000`.

**Железо:** минимум production — 2 ядра и 8GB RAM; типичный сервер — 8+ ядер и 32GB+ RAM.

## Cassandra: cassandra.yaml

Параметры с верифицированными дефолтами (Cassandra 4.0):

| Параметр | Дефолт | Назначение и рекомендация |
| :--- | :--- | :--- |
| `concurrent_reads` | `32` | Правило из документации: `16 × число дисков` — чтобы операции уходили глубоко в стек и OS/диски могли их переупорядочить |
| `concurrent_writes` | `32` | Правило: `8 × число ядер` — записи почти никогда не упираются в I/O |
| `concurrent_counter_writes` | `32` | Как reads: counter-write читает текущее значение перед записью |
| `concurrent_materialized_view_writes` | `32` | Ограничено меньшим из reads/writes (есть чтение) |
| `key_cache_size_in_mb` | auto = `min(5% heap, 100MB)` | Кэш индексов; `0` — выключить; `key_cache_save_period: 14400` (4 ч) — сохранение на диск для быстрого холодного старта |
| `row_cache_size_in_mb` | `0` (выключен) | Кэш целых строк (OHCProvider, off-heap); включать только для горячих/статических строк — крайне затратен по памяти |
| `counter_cache_size_in_mb` | auto = `min(2.5% heap, 50MB)` | Снижает contention на горячих counter-ячейках |
| `file_cache_size_in_mb` | auto = `min(1/4 heap, 512MB)` | Chunk cache распакованных блоков SSTable (off-heap); `file_cache_enabled: false` в 4.0 |
| `memtable_heap_space_in_mb` / `memtable_offheap_space_in_mb` | auto = `1/4 heap` | Общий лимит memtables; при превышении записи блокируются до flush |
| `memtable_allocation_type` | `heap_buffers` | `offheap_buffers` / `offheap_objects` — вынос memtable за heap |
| `memtable_flush_writers` | `2` (одна директория) | Больше писателей — мельче и чаще flush, больше compaction overhead |
| `compaction_throughput_mb_per_sec` | `64` | **В 3.11 было 16** — не переносите старые значения; `0` — без throttling; правило: 16–32× от скорости вставки |
| `stream_throughput_outbound_megabits_per_sec` | `200` (25 MB/s) | Throttling streaming (bootstrap/repair); `inter_dc_stream_throughput_outbound_megabits_per_sec` — то же между DC |
| `stream_entire_sstables` | `true` | Zero-copy streaming целых SSTables; снижает GC на обеих сторонах |
| `concurrent_compactors` | `min(дисков, ядер)`, мин 2, макс 8 | На SSD — увеличить до числа ядер |
| `commitlog_sync` | `periodic`, `10000 мс` | `group`/`batch` — ack только после fsync commitlog (больше durability, меньше throughput) |
| `commitlog_segment_size_in_mb` | `32` | Меньше (8–16) — только при архивации сегментов |
| `prepared_statements_cache_size_mb` | auto = `1/256 heap` или `10MB` | Рост — признак, что клиент не использует bind-маркеры |
| `slow_query_log_timeout_in_ms` | `500` | Агрегированный лог медленных запросов; `0` — выключить |
| `disk_optimization_strategy` | `ssd` | `spinning` — для HDD |

**Таймауты координатора** (защита от бесконечных операций; повышать без причины вредно — таймауты маскируют проблемы ресурсов):

| Параметр | Дефолт | Параметр | Дефолт |
| :--- | :--- | :--- | :--- |
| `read_request_timeout_in_ms` | `5000` | `counter_write_request_timeout_in_ms` | `5000` |
| `range_request_timeout_in_ms` | `10000` | `cas_contention_timeout_in_ms` | `1000` |
| `write_request_timeout_in_ms` | `2000` | `truncate_request_timeout_in_ms` | `60000` |
| `request_timeout_in_ms` | `10000` | | |

**Переименование в 4.1:** `memtable_heap_space_in_mb` → `memtable_heap_space`, `memtable_offheap_space_in_mb` → `memtable_offheap_space` (значения с единицами, например `MiB`).

**Throttling на лету** (без правки конфига): `nodetool setcompactionthroughput`, `nodetool setstreamthroughput`, `nodetool setrpcthroughput` — см. [Обслуживание](./operations.md).

## Cassandra: операционная система

```bash
# Swap — выключить (Cassandra не должна свопиться)
sudo swapoff -a

# Transparent Huge Pages — выключить (деградирует GC и latency)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled

# Увеличить лимит mmap (для индексов и SSTables)
sudo sysctl -w vm.max_map_count=1048575

# Сеть: latency внутри DC должна быть < 1 мс
ping <соседний-узел>
```

Commitlog при HDD-разметке — на отдельный spindle от `data_file_directories`.

**Файловая система и диски:**

- **XFS** — рекомендуемая ФС для ScyllaDB (проверяется в `developer_mode`); детали — **[XFS](../../Linux/FileSystems/xfs.md)**
- **noatime** — монтировать с `noatime`: чтение не обновляет atime, меньше записей на диске
- **I/O scheduler** — ScyllaDB настраивает block layer утилитой `scylla-blocktune`; общая теория — **[Тюнинг файловых систем](../../Linux/FileSystems/performance_tuning.md)** и **[RAID: тюнинг производительности](../../Linux/FileSystems/RAID/raid-performance-tuning.md)**

## ScyllaDB: память и CPU

**Память — автоматически:** ScyllaDB забирает почти всю доступную память под кэши (чем больше, тем лучше). В `scylla.yaml` **нет ключа `memory:`** — ограничение задаётся ключами запуска:

```bash
# Ограничение памяти и числа ядер (ключи запуска scylla, НЕ scylla.yaml)
scylla --memory 16G     # или -m 16G
scylla --smp 8          # ограничить числом shards (по умолчанию = число ядер)
```

| Параметр | Рекомендация |
| :--- | :--- |
| RAM | 16GB или 2GB на lcore — больше из двух; production-минимум 4GB или 0.5GB на lcore |
| Максимум | 1 TiB на lcore, до 256 lcores |
| Соотношение storage:memory | не более 30:1 (128GB RAM → ≤ 3.8TB данных на узел) |
| Соединения | 1–3 соединения на ядро от каждого клиента |
| `developer_mode` | `false` (дефолт) — строгие проверки окружения: XFS + асинхронный I/O |

**Swap для ScyllaDB — рекомендуется** (в отличие от Cassandra!): размер `total_mem/3` или 16GB — меньшее из двух.

**CPU:** ScyllaDB не должна делить ядра с другими процессами; `scylla_cpuset_setup` — привязка потоков, `scylla_cpuscaling_setup` — режим `performance` вместо `powersave`. На AWS — IRQ сетевого интерфейса на CPU0, а ScyllaDB — вне CPU0 и его HT-сиблингов (для ≤ 4 CPU не применять).

## ScyllaDB: I/O и планировщик

**`scylla_setup` / `scylla_io_setup`** — бенчмаркируют диски и генерируют `/etc/scylla.d/io.conf` и `/etc/scylla.d/io_properties.yaml`, которыми питается I/O scheduler. Узлам с одинаковым железом — копировать эти файлы с существующего узла (а не перезапускать `scylla_io_setup`), чтобы настройки I/O были синхронизированы. **Перезапускайте `iotune` раз в несколько месяцев** — диски изнашиваются, и измеренные возможности меняются.

ScyllaDB имеет **собственный userspace I/O scheduler** (с 4.4): он не даёт диску перегрузиться, ставит в очередь и приоритизирует запросы — latency-чувствительные запросы обслуживаются раньше compaction/streaming. Linux I/O scheduler настраивается утилитой `scylla-blocktune` (filesystem и block layer).

```yaml
# scylla.yaml — throttling фоновых операций (backup, repair, tablet migration)
# Рекомендация: 75% от сетевой полосы узла
maintenance_io_throughput_mb_per_sec: 1373

# Throttling streaming-активности (новее)
# stream_io_throughput_mb_per_sec: 1373

# Логировать WARN на батчи больше порога (дефолт 128 KiB)
batch_size_warn_threshold_in_kb: 128
```

Seastar-опции (`scylla --help` / `scylla --help-seastar`) — менять только при доказанной необходимости:

| Опция | Дефолт | Назначение |
| :--- | :--- | :--- |
| `task-quota-ms` | `0.5` | Макс. время между опросами reactor; меньше — быстрее dispatch, дороже по CPU |
| `io-latency-goal-ms` | `1.5 × task-quota-ms` | Целевая задержка дисковых запросов; для HDD с latency 10 мс — поднять до 50+ мс |
| `max-task-backlog` | `1000` | Макс. задач в backlog, после которого I/O игнорируется |
| `idle-poll-time-us` | `200` | Время опроса перед сном; больше — больше CPU, меньше — меньше latency |
| `num-io-groups` | по NUMA | Разбиение дисковой ёмкости на группы CPU |
| `poll-mode` | off | Отключает сон reactor (100% CPU) — экономит микросекунды |

## Диагностика Tombstones

Tombstones — маркеры удаления; при чтении Cassandra вынуждена их сканировать, что замедляет запросы. Пороги (Cassandra 4.0):

| Параметр | Дефолт | Эффект |
| :--- | :--- | :--- |
| `tombstone_warn_threshold` | `1000` | Логирование предупреждения; запрос завершается |
| `tombstone_failure_threshold` | `100000` | Запрос прерывается с `TombstoneOverwhelmingException` (защита от OOM) |

**Реальный формат записи в логе** (не сокращённый):

```
WARN  [ReadStage-...] Read 0 live rows and 87051 tombstone cells for query SELECT * FROM ks.user_events WHERE user_id=...; token ... (see tombstone_warn_threshold)
```

**Диагностика:**

```bash
# Гистограммы по таблице: Tombstone Scanned Histogram, Partition Size, Cell Count
nodetool tablehistograms <keyspace> <table>

# Счётчики чтений, превысивших пороги (JMX: ColumnFamily.*)
#   TombstoneWarnings  — превысили tombstone_warn_threshold
#   TombstoneFailures  — превысили tombstone_failure_threshold
```

- В Cassandra 4.1+ параметр `client_track_warnings_enabled` возвращает предупреждения клиенту (в 4.2 включён по умолчанию)
- **ScyllaDB:** tombstone-scanned histogram не реализован (issue #7636); поле tombstones в `nodetool cfstats` показывает `0`; ScyllaDB отслеживает большие разделы в системной таблице
- Тюнинг: `gc_grace_seconds` уменьшать только при гарантии, что Repair проходит чаще этого срока; compaction-параметры (`tombstone_threshold` 0.2 и др.) — в [Обслуживании](./operations.md); для TTL-данных — TWCS (полностью истёкшие SSTables удаляются целиком)

## Антипаттерны (чего НЕЛЬЗЯ делать)

- **`ALLOW FILTERING`:** полный скан кластера. Если используется регулярно — модель данных неверна. Только для разовых административных запросов.
- **Большие разделы (десятки МБ и больше):** огромные паузы GC в Cassandra и нагрузка на диск в обеих СУБД.
- **Кросс-партиционные батчи (`BEGIN BATCH`):** только для атомарности внутри одного раздела; для разных разделов — узкое место на координаторе (ScyllaDB логирует WARN при батче > `batch_size_warn_threshold_in_kb`).
- **Листинг без Partition Key:** `SELECT * FROM table` без `WHERE` сканирует весь кластер.
- **Высокочастотные Lightweight Transactions:** Paxos масштабируется плохо; только для атомарных проверок.
- **Повышение `tombstone_failure_threshold` вместо исправления модели:** порог — защита от OOM, его рост маскирует проблему.

## Нагрузочное тестирование

```bash
# cassandra-stress — генератор нагрузки из состава Cassandra
cassandra-stress write n=1000000 -rate threads=50 -node 192.0.2.10
cassandra-stress read  n=1000000 -rate threads=50 -node 192.0.2.10
# → прогон до и после каждого изменения конфигурации
```

**scylla-bench** — генератор нагрузки для ScyllaDB (репозиторий scylla-bench на GitHub):

- Режимы: `write`, `read`, `counter_update`, `scan`, `mixed`
- Workload-ы: распределение операций и ключей (sequential, uniform, normal и др.)
- Ключевые флаги: `-concurrency` (параллельные операции), `-max-rate` (ограничение скорости), `-range-count` (дефолт = nodes × cores × 300)
- **Shard-awareness:** для корректного распределения нагрузки по shards требуется сборка из клона репозитория (используется форк gocql от ScyllaDB)
- Применение: замер пропускной способности и latency перед production, проверка тюнинга I/O (`scylla_io_setup`)

## Валидация

| Что проверяем | Команда / сигнал | Ожидание |
| :--- | :--- | :--- |
| Применился ли heap | `nodetool info` → `Heap Memory` | Совпадает с расчётом |
| Паузы GC | `nodetool gcstats`; GC-лог | Паузы < 500 мс |
| Кэши | `nodetool info` → Key Cache hit rate | Высокий hit rate на read-нагрузке |
| Tombstones | `nodetool tablehistograms` | Хвост Tombstone Scanned Histogram не растёт |
| Пулы потоков | `nodetool tpstats` | PendingTasks стабильно < 50, Dropped Messages = 0 |
| Диск | `iostat -x 1` | `%util` не в потолке, нет `await`-всплесков |
| ScyllaDB I/O | метрика `scylla_database_sstable_read_queue_overloads` | `0` |

## Поиск и устранение неисправностей

| Симптом | Вероятные причины | Действия |
| :--- | :--- | :--- |
| P99 read latency растёт | Tombstones, рост числа SSTables | `nodetool tablehistograms`, `nodetool tablestats`, логи по `tombstone_warn_threshold` |
| Паузы GC > 500 мс | Heap слишком велик / GC не настроен | GC-лог, `nodetool gcstats`; heap ≤ 31GB, G1 для > 12GB |
| Write timeouts | Backlog compaction, memtable flush блокирован, диск в потолке | `nodetool compactionstats`, метрика `MemtablePool.BlockedOnAllocation`, `iostat` |
| Read timeouts | Read queue перегружен, пулы потоков | `nodetool tpstats`, `iostat`, `scylla_database_sstable_read_queue_overloads` |
| OOM при старте/нагрузке | Heap, row cache, prepared cache | Heap dump в `CASSANDRA_HEAPDUMP_DIR`, `prepared_statements_cache_size_mb` |
| Медленный старт после рестарта | Холодный key cache | `key_cache_save_period: 14400` (сохранение кэша на диск) |
| ScyllaDB: tail latency при compaction | Диск перегружен | `scylla_io_setup` заново, `maintenance_io_throughput_mb_per_sec`, `io-latency-goal-ms` |

## Рекомендации и очистка

- **Бенчмарк до и после** каждого изменения (`cassandra-stress`); меняйте **один параметр за раз** — иначе причина регресса не определяется.
- Калибруйте пороги (`tombstone_*`, таймауты) под SLA и нагрузку — стартовые точки, не универсальные истины.
- Cassandra: swap и THP выключены, heap ≤ 31GB (compressed oops), `-Xmn` не задавать при G1.
- ScyllaDB: `scylla_setup` обязателен; не боритесь с авто-тюнингом — подбирайте железо и клиентские соединения; `iotune` раз в несколько месяцев.
- **Откат изменений:** `cassandra.yaml` — rolling restart узлов; JVM-опции — restart; ScyllaDB — поддерживающие live-update параметры правятся через `system.config` или REST API (`SIGHUP` для `scylla.yaml`).

## См. также

- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — Seastar, JVM, GC pauses.
- **[Обслуживание и эксплуатация](./operations.md)** — Compaction, Repair, throttling, tombstone compaction.
- **[Мониторинг и observability](./monitoring.md)** — метрики и пороги алертов.
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — `TombstoneOverwhelmingException`, диагностический bundle.
- **[Установка и настройка](./installation.md)** — расположение `jvm.options` и `cassandra.yaml`.
