# Архитектура: Cassandra vs ScyllaDB

**Актуально для:** Apache Cassandra 4.0/5.0.x / ScyllaDB 2025.2–2026.x

## Определения

| Термин | Определение |
| :--- | :--- |
| **Token ring** | Непрерывное кольцо хешей; узел владеет одной или несколькими позициями (токенами) на кольце |
| **Token** | Одна позиция на кольце; хеш ключа партиции определяет владельца данных |
| **vNode (virtual node)** | Токен на кольце, принадлежащий физическому узлу; один физический узел владеет несколькими vNodes |
| **Tablet** | Единица распределения данных в ScyllaDB: партиции таблицы детерминистически отображаются на tablet, у tablet есть реплики на разных узлах |
| **Gossip** | Протокол распространения состояния кластера: каждую секунду узел обменивается состоянием с случайным узлом |
| **Snitch** | Компонент, сообщающий кластеру сетевую топологию (DC/Rack) для маршрутизации запросов и размещения реплик |
| **Partitioner** | Функция хеширования ключа партиции; дефолт — `Murmur3Partitioner` (обе СУБД) |
| **Coordinator** | Узел, принявший клиентский запрос и координирующий чтение/запись на репликах |
| **Memtable** | В памяти отсортированный буфер записей; одна активная memtable на таблицу |
| **SSTable (SStable)** | Неизменяемый отсортированный файл данных на диске (Sorted String Table) |
| **Commit log** | Write-ahead log: каждая запись сначала попадает в commit log, затем в memtable |
| **LSM-tree** | Log-Structured Merge tree: модель хранения с append-only записью и фоновым слиянием (compaction) |
| **Seastar** | C++-фреймворк ScyllaDB: share-nothing, shard-per-core, асинхронный I/O |
| **Shard** | Логическое ядро ScyllaDB: каждое ядро CPU владеет своими данными и пулом памяти |
| **DMA** | Direct Memory Access: прямой ввод-вывод между диском и памятью без участия CPU |
| **Raft** | Алгоритм консенсуса: ScyllaDB использует его для schema и топологии (mandatory с 2025.2) |
| **Phi Accrual Failure Detector** | Адаптивный детектор отказов Cassandra: решение UP/DOWN принимает каждый узел локально |
| **Consistent hashing** | Хеширование, при котором добавление узла перемещает лишь малую долю ключей |

Термины Compaction, Repair, Hinted handoff, Read repair, Tombstone определены в [Обслуживании и эксплуатации](./operations.md); кэши и пороги — в [Тюнинге производительности](./performance.md).

## Общая концепция

Обе СУБД — распределённые wide-column NoSQL-хранилища с общей родословной:

- **Amazon Dynamo** — разделение данных (consistent hashing), multi-master репликация, tunable consistency, gossip-членство и детектирование отказов
- **Google Bigtable / LSM-tree** — модель хранения: memtable + неизменяемые SSTable, append-only запись, фоновый compaction
- Cassandra изначально создана в Facebook на основе SEDA (staged event-driven architecture); ScyllaDB переписана на C++ с фреймворком Seastar

**Модель данных (одинаковая):** keyspace → table → partition (partition key) → row (partition key + clustering columns) → column. Обе СУБД **не поддерживают**: cross-partition транзакции, распределённые JOIN, внешние ключи — это сознательный выбор ради горизонтального масштабирования. Схема изменяется онлайн, без блокировки рабочей нагрузки.

**Различение принципиально:** Cassandra — JVM-процесс с потоками и GC; ScyllaDB — нативный процесс с шардами и без GC. Это определяет всё остальное: от поведения под нагрузкой до способов тюнинга.

## Как работает кластер

### Разделение данных

**Cassandra — token ring и vNodes.** Ключ партиции хешируется (`Murmur3Partitioner`) в токен; владелец определяется обходом кольца по часовой стрелке до `RF` различных узлов. Каждый физический узел владеет несколькими vNodes (`num_tokens`):

- В Cassandra 2.x использовался случайный аллокатор, требовавший **256 токенов** на узел для баланса
- С 3.x добавлен детерминированный аллокатор, балансирующий кольцо при малом числе токенов
- **С 4.0 дефолт `num_tokens: 16`** — не 256

Плюсы vNodes: при добавлении/удалении узла данные перераспределяются равномерно; при отказе узла нагрузка ложится на многих соседей. Минусы: каждый токен добавляет до `2 × (RF − 1)` соседей на кольце (растёт вероятность недоступности части диапазона), растёт число дискретных операций repair.

**ScyllaDB — tablets (дефолт).** Таблица делится на tablets; каждая партиция детерминистически отображается на один tablet; у tablet `RF` реплик на разных узлах, tablets балансируются и между шардами внутри узла:

- **Load balancer** автономно перемещает tablets между узлами и шардами в фоне, без прерывания обслуживания, на основе реальных размеров на диске
- При росте таблицы tablet **делится** пополам; половины мигрируют независимо; при уменьшении — **сливается**
- Число tablets управляется опциями: keyspace `initial`, table `min_tablet_count`/`max_tablet_count`/`min_per_shard_tablet_count`/`expected_data_size_in_gb`/`pow2_count`, конфиг `tablets_initial_scale_factor`; `tablets_per_shard_goal` — мягкий лимит
- Миграция — **file-based streaming**: передаются целые SStables без (де)сериализации фрагментов, меньше CPU и сети
- **Cleanup автоматический и per-tablet** — не переписывает SStables на оставшихся узлах (в Cassandra `nodetool cleanup` обязателен после topology-изменений)
- Включение: `tablets_mode_for_new_keyspaces` (дефолт — tablets для новых keyspaces); opt-out: `CREATE KEYSPACE ... WITH tablets = {'enabled': false}`. **Нельзя ALTER keyspace для переключения tablets** — только DROP и recreate
- Ограничения: нельзя уменьшать число шард после рестарта; resharding на рестарте не выполняется; materialized views и secondary indexes требуют RF-rack-valid keyspace

### Членство кластера: gossip и Raft

**Cassandra — gossip + failure detector.** Каждую секунду каждый узел: обновляет heartbeat-состояние, обменивается состоянием со случайным узлом, с вероятностью пробует недостижимые узлы, и — если обмен не состоялся — с seed-узлом. Gossip переносит токены и версию схемы; состояние версионируется `(generation, version)`. Seed-узлы — единственные, кто может войти в кольцо, не видя других seed; после bootstrap они становятся «горячими точками» gossip.

- **Phi Accrual Failure Detector** решает UP/DOWN локально на каждом узле; решение **не** распространяется gossip — узел считается UP только после успешного обмена по реальному каналу
- Узел **никогда не удаляется** из состояния gossip без явной операции (`decommission`) или bootstrap с `replace_address_first_boot` — чтобы временный отказ не вызывал перебалансировку

**ScyllaDB — gossip для membership + Raft для schema и топологии.** Gossip по-прежнему переносит heartbeat и membership, но schema-изменения (CREATE/ALTER/DROP) и topology-операции фиксируются в реплицированном Raft-логе и применяются на всех узлах **в одинаковом порядке**:

- **Quorum обязателен**: без кворума недоступны schema и topology-изменения; DML продолжает работать
- Рекомендация — **3 DC на кластер** (в 2-DC с равным числом узлов отказ одного DC теряет кворум; третий DC может быть одним узлом с `join_ring=false`)
- Consistent topology changes **mandatory с 2025.2**; проверка: `SELECT upgrade_state FROM system.topology;` → `done`, либо `curl -X GET "http://127.0.0.1:10000/storage_service/raft_topology/upgrade"`
- Следствие: **bootstrap нескольких узлов одновременно** возможен (при gossip-топологии — нет)

### Snitch — топология сети

Snitch выполняет две функции: маршрутизирует запросы эффективно и размещает реплики в разных failure-доменах (DC/Rack). Динамический snitch поверх статического отслеживает latency чтения (`dynamic_snitch_update_interval: 100ms`, `dynamic_snitch_reset_interval: 10m`, `dynamic_snitch_badness_threshold: 0.2` — переключается на другую реплику, если pinned-хост медленнее на 20%).

| Snitch | Когда применять |
| :--- | :--- |
| **GossipingPropertyFileSnitch** | Дефолт для production: DC/Rack из `cassandra-rackdc.properties`, распространяются gossip |
| **SimpleSnitch** | Только single-DC (порядок стратегии = близость) |
| **PropertyFileSnitch** | DC/Rack явно в `cassandra-topology.properties` (legacy) |
| **RackInferringSnitch** | DC/Rack из 2-го/3-го октетов IP — пример для написания своего snitch |

### Репликация и согласованность

- **NetworkTopologyStrategy** — production-стандарт: отдельный RF на DC, реплики размещаются по разным Rack (если Rack ≥ RF — каждая реплика в своём Rack). **SimpleStrategy — только для тестов**: игнорирует DC/Rack
- **RF (Replication Factor)** — число копий партиции; production-рекомендация `RF=3`
- Запись **всегда отправляется на все реплики** независимо от consistency level; уровень задаёт, сколько ответов дождаться
- Строгая читаемость: `R + W > RF` (например, QUORUM/QUORUM при RF=3)
- Конфликты разрешаются **last-write-wins** (LWW-Element-Set CRDT): каждая мутация имеет тайметстамп, поэтому **NTP обязателен на всех узлах**
- Сходимость реплик: read repair (в пути чтения), hinted handoff (в пути записи), anti-entropy repair с Merkle-деревьями (полный, sub-range, incremental) — команды и практики в [Обслуживании](./operations.md)

## Storage engine (обе СУБД)

LSM-tree: запись оптимизирована, чтение платит Bloom-фильтрами и слиянием SSTables при compaction (write amplification — плата за запись).

**Путь записи:** commit log (диск, append-only) → memtable (память, отсортировано) → flush → SSTable (диск, неизменяемый).

- **Commit log** общий для всех таблиц; сегменты по `commitlog_segment_size_in_mb: 32`; `commitlog_sync: periodic` (дефолт, fsync каждые `commitlog_sync_period_in_ms: 10000`) или `batch` (fsync перед ack — тогда commit log на отдельном диске); `commitlog_total_space_in_mb` дефолт 8192; опциональное сжатие (LZ4/Snappy/Deflate/Zstd). Перед остановкой — `nodetool drain`: сбрасывает memtables и избавляет от replay commit log при старте
- **Memtable**: одна активная на таблицу; flush по порогу памяти (`memtable_cleanup_threshold`) или при заполнении commit log; при превышении порога запись блокируется до завершения flush
- **SSTable-компоненты**: `Data.db` (данные), `Partitions.db`/`Rows.db` (индексы, Big Trie — CEP-25), `Index.db`, `Summary.db` (выборка каждой 128-й записи Index), `Filter.db` (Bloom-фильтр ключей), `CompressionInfo.db`, `Statistics.db` (метаданные: timestamps, tombstones, TTL, compaction, repair), `Digest.crc32`, `TOC.txt`, `SAI*.db` (при SAI)
- Данные в SSTable отсортированы в **порядке токенов**, строки внутри партиции — в порядке clustering columns
- Cassandra 5.0: новый **BTI-формат** (trie-indexed SSTables), включается `sstable: selected_format: bti`; версия BigFormat для 5.0 — `oa`
- ScyllaDB: SStable 3.x; compaction-стратегия по умолчанию — **ICS** (Incremental)

## Архитектура Cassandra (JVM)

- **SEDA, thread-per-request:** каждый запрос занимает поток из пула; стадии (mutation, read, compaction) обрабатываются отдельными пулами потоков. При большом числе параллельных запросов — конкуренция за потоки
- **GC pauses:** сборщик мусора периодически останавливает обработку. Поддерживаются **CMS (дефолт 4.0/4.1) и G1 (дефолт 5.0)**; **ZGC не поддерживается**. Heap вычисляется автоматически: `min(1/2 RAM, CMS ? 16G : 31G)` — детали и тюнинг в [Тюнинге производительности](./performance.md)
- **Java:** запуск под Java 11 и Java 17; бинарные релизы собраны Java 11
- **vNodes:** перебалансировка при добавлении узла — стриминг диапазлов токенов, относительно медленный процесс; после topology-изменений обязателен `nodetool cleanup`

## Архитектура Seastar (ScyllaDB)

Seastar — фреймворк высокопроизводительных C++-приложений, модель **share-nothing**: каждое ядро работает как независимый узел.

- **Shard-per-core:** данные разделены между ядрами; запрос маршрутизируется на ядро-владелец данных. Отсутствие блокировок между ядрами
- **Изолированная память:** у каждого ядра собственный пул памяти — нет конкуренции за кэши и GC
- **DMA и userspace I/O scheduler (с 4.4):** прямой ввод-вывод между диском и памятью; очередь и приоритизация в userspace — latency-чувствительные запросы обслуживаются раньше compaction/streaming (Scheduling Groups). Linux block layer настраивается `scylla-blocktune`
- **Тюнинг:** память, I/O и планировщик настраиваются автоматически (`scylla_setup`/`iotune`); Seastar-опции (`task-quota-ms`, `io-latency-goal-ms`) — только при доказанной необходимости, см. [Тюнинг](./performance.md)
- **Требования:** SSE4.2 (иначе не стартует); рекомендуется 20–60 logical cores; память 16 GB или 2 GB/lcore (больше из); диск/RAM ≤ 30:1; сеть 10 Gbps+

## Сравнительная характеристика

| Аспект | Cassandra 4.0/5.0 | ScyllaDB 2025.2–2026.x |
| :--- | :--- | :--- |
| Рантайм | JVM (Java 11/17) | Нативный C++ (Seastar) |
| Модель выполнения | SEDA, thread-per-request | Shard-per-core, share-nothing, async |
| Память | JVM heap + off-heap, GC pauses | Пулы на ядро, DMA, без GC |
| Разделение данных | vNodes (`num_tokens`, дефолт 16 с 4.0) | Tablets (дефолт), автоматический load balancer |
| Топология | Gossip; bootstrap/decommission по одному | Raft (mandatory 2025.2+); concurrent bootstrap |
| Schema-изменения | Gossip (schema version sync) | Raft log, применение в одинаковом порядке |
| Перебалансировка | Стриминг диапазлов, медленно; cleanup вручную | File-based streaming целых SStables; cleanup автоматический |
| I/O | OS scheduler + пулы Cassandra | Userspace I/O scheduler (с 4.4), Scheduling Groups |
| GC | CMS (4.0/4.1) / G1 (5.0) | Нет |
| Тюнинг | Ручной: heap, GC, кэши | Автоматический: память, I/O; Seastar-опции при необходимости |

## Когда выбирать

**ScyllaDB предпочтительнее когда:**
- Критичны предсказуемая низкая задержка и низкие хвосты (tail latency) при высокой нагрузке
- Нужна максимальная пропускная способность на тот же железо (меньше узлов на ту же нагрузку)
- Важна автоматическая перебалансировка (tablets) и безопасные concurrent topology-операции (Raft)
- Multi-DC кластер, где важна устойчивость schema/топологии к отказам (Raft quorum)

**Cassandra предпочтительнее когда:**
- Нужна максимальная совместимость с существующим кодом, драйверами и интеграциями (более широкая экосистема инструментов)
- Команда экспертируется в JVM и Java-экосистеме
- Требуется работа с устаревшими версиями драйверов или миграция с legacy-Cassandra

Совместимость: ScyllaDB совместима с Cassandra по CQL и драйверам; миграционные инструменты — в документации ScyllaDB (ScyllaDB Migrator).

## Поиск и устранение неисправностей

| Симптом | Архитектурная причина | Действие |
| :--- | :--- | :--- |
| Неравномерная нагрузка на узлах (Cassandra) | Дисбаланс токенов, `num_tokens` подобран плохо | `nodetool ring` / `nodetool status` — проверка диапазонов; пересмотр `num_tokens` только для нового кластера |
| Долгая перебалансировка после добавления узла (Cassandra) | vnode bootstrap стримит диапазлы | Дождаться bootstrap; `nodetool cleanup` на узлах, потерявших диапазлы |
| Паузы в обработке запросов (Cassandra) | GC pauses при большом heap | GC-логи, heap-формула — [Тюнинг](./performance.md) |
| Узел не присоединяется к кластеру | Seed-узлы недоступны, разное `cluster_name` | Проверить seeds и `cluster_name` — [Troubleshooting](./troubleshooting.md) |
| Schema/topology операции зависли (ScyllaDB) | Потерян Raft quorum | Восстановить кворум узлов; DML при этом продолжает работать; проверить `SELECT upgrade_state FROM system.topology;` |
| Нельзя включить tablets на существующем keyspace | Ограничение ScyllaDB | ALTER keyspace не поддерживается — DROP + recreate с `tablets = {'enabled': true}` |
| Ошибки MV/secondary index на tablet keyspace (ScyllaDB) | Keyspace не RF-rack-valid | Привести keyspace к RF-rack-valid (см. документацию ScyllaDB) |

## Рекомендации

- **Seed-узлы:** 2–3 на DC, не все узлы; после bootstrap seed-узлы — горячие точки gossip
- **NTP на всех узлах** — корректность LWW-разрешения конфликтов зависит от часов
- **NetworkTopologyStrategy всегда** (даже single-DC) — SimpleStrategy только для тестов; `RF=3` в production
- **GossipingPropertyFileSnitch** для production; DC/Rack задать в `cassandra-rackdc.properties`
- **`num_tokens` не менять** после развёртывания — перебалансировка всего кольца
- **ScyllaDB:** запускать `scylla_setup` на каждом узле; Seastar-опции не трогать без доказанной необходимости; для Raft-устойчивости — 3 DC (третий может быть одним узлом с `join_ring=false`)
- **`nodetool drain`** перед остановкой узла Cassandra — сброс memtables, быстрый старт без replay commit log

## См. также

- **[Обзор и моделирование данных](./overview.md)** — модель данных, CQL, типы данных, сценарии
- **[Обслуживание и эксплуатация](./operations.md)** — bootstrap, repair, compaction, topology-операции
- **[Тюнинг производительности](./performance.md)** — JVM Heap, cassandra.yaml, ScyllaDB I/O
- **[Мониторинг и observability](./monitoring.md)** — метрики, nodetool, Prometheus
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — ошибки подключения, таймауты, tombstones
