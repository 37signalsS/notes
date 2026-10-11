# Cassandra и ScyllaDB: вопросы и ответы для собеседования (DevOps / SRE / Sysadmin)

**Актуально для:** Apache Cassandra 4.0/5.0.x / ScyllaDB 2026.x

## Определения

*   **Q&A-шпаргалка** — сборник типовых вопросов с короткими ответами и ссылками на глубокий разбор в тематических файлах; не заменяет практику, а проверяет её.
*   **Операционный вопрос** — вопрос про эксплуатацию (бэкап, failover, тюнинг, инциденты), а не про написание запросов: фокус этого файла.
*   **Короткий ответ** — 2–5 строк: суть + ключевой параметр/команда; детали — по ссылке.

## Как устроен вопросник

Интервьюер проверяет четыре слоя:

1.  **Архитектура** — как работают Cassandra/ScyllaDB внутри (LSM-Tree, gossip, vnodes/tablets).
2.  **Эксплуатация** — что делать в production (repair, backup, upgrade, инциденты).
3.  **Производительность** — тюнинг, диагностика, антипаттерны.
4.  **Сценарии** — «что будет, если…» и «как диагностировать…».

Правило ответа: **сначала суть, потом параметр/команда, потом границы применимости**. Например: «`nodetool repair -pr` синхронизирует только диапазоны, за которые узел первичная реплика — запускается на каждом узле последовательно; repair должен проходить чаще `gc_grace_seconds`».

## Архитектура и модель данных

**Q: Чем Cassandra отличается от ScyllaDB?**
Cassandra — JVM (Java), ScyllaDB — C++ на фреймворке Seastar с архитектурой shard-per-core: каждый shard привязан к ядру CPU, I/O обрабатывается в userspace. ScyllaDB совместима с Cassandra по протоколу CQL и обеспечивает в 3–10 раз большую пропускную способность без пауз Garbage Collector. [Архитектура](./architecture.md)

**Q: Что такое LSM-Tree и как он влияет на запись?**
Log-Structured Merge-Tree: запись сначала фиксируется в commitlog (WAL, durability) и memtable (память), затем сбрасывается в immutable SSTable. Запись последовательная и быстрая; чтение требует слияния версий из нескольких SSTables — отсюда read amplification. [Обзор](./overview.md)

**Q: Как устроен Primary Key?**
`PRIMARY KEY (partition_key, clustering_columns)`: partition key определяет узел через consistent hashing (Murmur3Partitioner), clustering columns задают физический порядок сортировки внутри раздела. Модель строится под запрос (query-driven modeling): одна таблица = один тип запроса. [Обзор](./overview.md)

**Q: Что такое vNodes и Tablets?**
Механизмы распределения диапазонов токенов. Cassandra: vNodes — каждый узел получает `num_tokens` (дефолт 16 с 4.0) псевдослучайных токенов. ScyllaDB: Tablets (дефолт в новых кластерах) — динамическое перераспределение без ручной перебалансировки. [Архитектура](./architecture.md)

**Q: Зачем нужен snitch?**
Сообщает кластеру сетевую топологию (DC/rack) для маршрутизации реплик и выбора координатора. Production-стандарт — `GossipingPropertyFileSnitch`. [Обзор](./overview.md)

**Q: Почему большие партиции — проблема?**
Десятки МБ и больше: долгие паузы GC в Cassandra и нагрузка на диск в ScyllaDB. Держите partition < 100 МБ и < 100K строк; для временных рядов добавляйте бакет (например, день) в partition key. [Обзор](./overview.md), [Тюнинг](./performance.md)

**Q: Чем Materialized Views отличаются от отдельных таблиц под запрос?**
MV автоматически материализуют данные с другим ключом, но каждое изменение исходной таблицы дублируется (write amplification) — не подходят для частых обновлений. Альтернатива — отдельные таблицы, обновляемые приложением. [Обзор](./overview.md)

**Q: Что такое SAI?**
Storage Attached Index — механизм индексации, появившийся в Cassandra 5.0: индекс хранится вместе с SSTable (в отличие от классических вторичных индексов, которые рассылают запрос по кластеру). Синтаксис и ограничения — в официальной документации Cassandra 5.0; классические вторичные индексы и их ограничения — в [Обзоре](./overview.md).

## Согласованность и репликация

**Q: Что такое tunable consistency?**
Уровень согласованности задаётся per-запрос — от `ONE` (1 реплика) до `ALL` (все реплики). Строгая согласованность при формуле `R + W > RF`. Production-стандарт — `LOCAL_QUORUM` для чтения и записи. [Обзор](./overview.md), [Обслуживание](./operations.md)

**Q: Чем LOCAL_QUORUM отличается от QUORUM и EACH_QUORUM?**
`QUORUM` — кворум по всему кластеру (latency растёт с числом DC); `LOCAL_QUORUM` — кворум только в локальном DC (нет меж-DC latency); `EACH_QUORUM` — кворум в каждом DC (строгая меж-DC согласованность, низкая доступность). [Обслуживание](./operations.md)

**Q: Что такое Lightweight Transactions и почему они дорогие?**
LWT — compare-and-set на базе Paxos (`IF` в CQL, уровни `SERIAL`/`LOCAL_SERIAL`). Гарантирует атомарность проверки, но масштабируется плохо — только для редких атомарных проверок, не для частых операций. [CQL](./cql-syntax.md), [Тюнинг](./performance.md)

**Q: Что такое hinted handoff и когда он не помогает?**
Координатор сохраняет мутацию для недоступной реплики и доставляет при восстановлении; хранится не дольше `max_hint_window` (дефолт 3 часа). Если узел был down дольше — hints удаляются, консистентность восстанавливается только repair. [Troubleshooting](./troubleshooting.md)

**Q: Что такое read repair?**
Пассивный механизм: при чтении координатор сравнивает версии строк с реплик и в фоне синхронизирует расхождения. Покрывает только читаемые пути — полный repair всё равно обязателен. [Обслуживание](./operations.md)

## Compaction, tombstones и repair

**Q: Зачем нужен compaction?**
SSTables immutable: обновления и удаления пишутся в новые файлы. Compaction сливает пересекающиеся SSTables, удаляет tombstones (после `gc_grace_seconds`) и перезаписанные строки, снижая read amplification. [Обслуживание](./operations.md)

**Q: Чем отличаются STCS, LCS и TWCS?**
STCS — слияние SSTables схожего размера (минимальная write amplification, высокая read amplification, до 50% свободного места). LCS — уровни с фиксированным размером SSTables (чтение 1–2 файлов, высокая write amplification, ~10% запаса). TWCS — временные окна, идеальна с TTL: истёкшие файлы удаляются целиком. [Обслуживание](./operations.md)

**Q: Что такое tombstone и почему он замедляет чтение?**
Маркер удаления; физически удаляется при compaction после `gc_grace_seconds`. Пока жив — сканируется при чтении. Пороги: `tombstone_warn_threshold` 1000 (логирование) и `tombstone_failure_threshold` 100000 (`TombstoneOverwhelmingException` — защита от OOM). [Обзор](./overview.md), [Тюнинг](./performance.md)

**Q: Зачем нужен repair и как часто?**
Анти-энтропийная синхронизация реплик через деревья Меркла — единственный активный механизм полной консистентности (hinted handoff покрывает часы, read repair — пассивен). Запускать чаще `gc_grace_seconds` (дефолт 10 дней), например еженедельно; иначе возможны zombie data. [Обслуживание](./operations.md)

**Q: Чем incremental repair отличается от full?**
Incremental (дефолт с Cassandra 4.0) обрабатывает только «unrepaired» данные, SSTables делятся на repaired/unrepaired наборы — быстрее, но требует регулярности. Full (`--full`) сравнивает всё — высокая нагрузка на CPU/диск. [Обслуживание](./operations.md)

**Q: Что делает `nodetool repair -pr`?**
Primary range repair — только диапазоны, за которые узел является первичной репликой. Самый эффективный способ пройти весь кластер без лишней работы: запускается на каждом узле последовательно. [Обслуживание](./operations.md)

**Q: ScyllaDB: `nodetool repair` или `nodetool cluster repair`?**
Зависит от типа keyspace: `nodetool repair` — только vnode keyspaces, `nodetool cluster repair` — только tablet keyspaces (дефолт в новых кластерах). Проверить тип: `DESCRIBE KEYSPACE`. На tablet keyspace `nodetool repair` завершается ошибкой `std::invalid_argument`. [Обслуживание](./operations.md)

**Q: Что такое `gc_grace_seconds` и почему его нельзя уменьшать вслепую?**
Окно ожидания перед физическим удалением tombstone (дефолт 10 дней) — страховка против воскрешения удалённых данных на узле, который был down. Уменьшать только при гарантии, что repair проходит чаще этого срока. [Обслуживание](./operations.md)

## Производительность и тюнинг

**Q: Какой размер heap для Cassandra?**
Не более 50% RAM и ≤ 31GB (compressed oops); < 12GB — CMS (4.0/4.1), > 12GB — G1; 5.0+ — только G1 (CMS удалён из JDK 14+). `-Xms = -Xmx`, `-Xmn` при G1 не задавать. Большой heap — долгие GC-паузы, главный источник tail latency. [Тюнинг](./performance.md)

**Q: Почему Cassandra не свопится, а ScyllaDB — наоборот?**
Cassandra: swap выключается (`swapoff -a`) — свопинг разрушает latency и GC. ScyllaDB: swap рекомендуется (`total_mem/3` или 16GB — меньшее из двух) как страховка от OOM при пиках. [Тюнинг](./performance.md)

**Q: Что такое THP и почему его выключают?**
Transparent Huge Pages — механизм ядра; деградирует GC и latency Cassandra. `echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled`. [Тюнинг](./performance.md)

**Q: Как настраиваются concurrent_reads/writes?**
Правило из документации: `concurrent_reads = 16 × число дисков` (чтобы операции уходили глубоко в стек I/O и OS мог их переупорядочить), `concurrent_writes = 8 × число ядер` (записи почти никогда не упираются в I/O). [Тюнинг](./performance.md)

**Q: Что такое `scylla_setup` и `iotune`?**
Утилиты ScyllaDB: бенчмаркируют диски и генерируют `/etc/scylla.d/io.conf` и `/etc/scylla.d/io_properties.yaml`, которыми питается userspace I/O scheduler. Узлам с одинаковым железом — копировать файлы с существующего узла; перезапускать `iotune` раз в несколько месяцев (диски изнашиваются). [Тюнинг](./performance.md)

**Q: Какие правила подбора железа для ScyllaDB?**
RAM 16GB или 2GB на lcore (больше из двух); соотношение storage:RAM ≤ 30:1; ядра не делить с другими процессами; 1–3 соединения на ядро от каждого клиента. [Тюнинг](./performance.md)

**Q: Почему `ALLOW FILTERING` — антипаттерн?**
Полный скан кластера: координатор опрашивает все узлы и фильтрует строки на лету. Регулярное использование — признак неверной модели данных; только для разовых административных запросов. [Тюнинг](./performance.md)

**Q: Как нагружать кластер перед production?**
`cassandra-stress` (в составе Cassandra) для базовых прогонов; `scylla-bench` для ScyllaDB (режимы write/read/counter_update/scan/mixed, флаги `-concurrency`, `-max-rate`; требует сборки из клона репозитория для shard-awareness). Прогон до и после каждого изменения конфигурации, один параметр за раз. [Тюнинг](./performance.md)

**Q: Что такое `compaction_throughput_mb_per_sec` и почему старые значения опасны?**
Throttling compaction (дефолт 64 МБ/с в 4.0; **в 3.11 было 16** — не переносите старые значения при upgrade). `0` — без throttling. Правило: 16–32× от скорости вставки. [Тюнинг](./performance.md)

## Мониторинг

**Q: Какие сигналы алертят первыми?**
Pending Tasks (пулы потоков, < 50), Dropped Messages (0), coordinator timeouts/unavailable (0), compaction backlog, TombstoneWarnings, свободное место на диске, `scylla_database_sstable_read_queue_overloads` (ScyllaDB, 0). [Мониторинг](./monitoring.md)

**Q: Чем отличается экспорт метрик Cassandra и ScyllaDB?**
ScyllaDB — нативный HTTP-эндпоинт (порт 9180, `/metrics`), метрики per-shard (агрегировать `sum by (instance)`). Cassandra — JMX MBeans (порт 7199) через JMX Exporter как Java-агент; обязателен whitelist — полный скрап грузит CPU. Cassandra 5.0 — дополнительно Virtual Tables (CQL) для разовых запросов. [Мониторинг](./monitoring.md)

**Q: Что показывает `nodetool tpstats`?**
Active/Pending/Completed/Blocked по пулам потоков и Dropped Messages (за всё время и за последние 5 минут). Рост PendingTasks и Dropped > 0 — первые признаки перегрузки. [Мониторинг](./monitoring.md)

**Q: Что такое ScyllaDB Monitoring Stack?**
Официальный стек (репозиторий scylladb/scylla-monitoring): Prometheus + Grafana + Alertmanager + Loki, готовые дашборды и правила алертов; компонент Advisor анализирует CQL-нагрузку (ALLOW FILTERING, консистентность ALL/ANY, запросы без token-awareness, non-prepared запросы). [Мониторинг](./monitoring.md)

**Q: Зачем конвертировать latency в правилах JMX Exporter?**
Метрики Cassandra — в **микросекундах**; без `valueFactor: 0.000001` в правилах JMX Exporter Grafana покажет завышенные задержки. [Мониторинг](./monitoring.md)

## Бэкапы

**Q: Как устроен бэкап Cassandra?**
`nodetool snapshot` — hardlinks SSTables (быстро, без остановки); инкрементальный бэкап — новые SSTables после flush; PITR — архивация сегментов commitlog. Снапшоты лежат на том же диске — не заменяют offsite-бэкап. [Бэкап](./backup-recovery.md)

**Q: Чем ScyllaDB Manager отличается от Medusa?**
ScyllaDB Manager (`sctool`) — официальный менеджер ScyllaDB: расписание repair и backup. Medusa — инструмент бэкапа для Cassandra (и ScyllaDB). [Бэкап](./backup-recovery.md)

**Q: Как проверить, что бэкап рабочий?**
Только восстановлением на стенде: snapshot/restore + smoke-тест. Бэкап без проверенного восстановления не является бэкапом. [Бэкап](./backup-recovery.md)

## Исключения и troubleshooting

**Q: NoHostAvailableException или UnavailableException — в чём разница?**
`NoHostAvailableException` — client-side: драйвер не достучался ни до одного узла (узлы down, порт 9042, firewall, неверные contact points или DC в LBP). `UnavailableException` — server-side: координатор получил запрос, но живых реплик меньше, чем требует consistency level. [Troubleshooting](./troubleshooting.md)

**Q: WriteTimeoutException — потеряна ли запись?**
Не обязательно: координатор мог сохранить hint для недоступной реплики. Проверить `nodetool statushandoff` / `nodetool listpendinghints`. Повторять запись безопасно только для идемпотентных запросов. [Troubleshooting](./troubleshooting.md), [Драйверы](./drivers.md)

**Q: Что такое TombstoneOverwhelmingException?**
Запрос просканировал больше `tombstone_failure_threshold` (100000) tombstones — защита от OOM. Решение — исправить модель данных (TWCS для временных рядов) и repair, а не повышать порог. [Troubleshooting](./troubleshooting.md), [Тюнинг](./performance.md)

**Q: Узел не стартует — с чего диагностировать?**
Первая ошибка ERROR/FATAL в логе (`system.log` / `journalctl -u scylla-server`): seed-узлы/`cluster_name`, `listen_address`/`rpc_address`, занятые порты (7000/7001/9042/7199), права на каталоги, место на диске, `ConfigurationException`. `nodetool describecluster` — schema disagreement (несколько версий схемы). [Troubleshooting](./troubleshooting.md)

**Q: Что собрать для эскалации в ScyllaDB?**
`scylla-doctor` на каждом узле (`.vitals.json` + архив логов), `scyllatop` (не `top`: ScyllaDB многопоточна per-shard), при проблемах с производительностью — `system.large_partitions`, при проблемах с консистентностью — `system_distributed.repair_history`. [Troubleshooting](./troubleshooting.md)

## Клиентские драйверы

**Q: Почему пул соединений драйвера — первый рычаг производительности?**
Драйвер мультиплексирует запросы по stream id: одно TCP-соединение обслуживает до 32768 одновременных запросов, но ограничено `max-requests-per-connection` (дефолт 1024) и `pool.local.size` (дефолт 1) — ≈80K req/s на соединение. Исчерпание пула — `BusyPoolException`. [Драйверы](./drivers.md)

**Q: Что такое token-aware load balancing?**
Драйвер направляет запрос сразу на реплику-владельца данных, избегая лишнего hop через координатор. В Java driver 4.x включён по умолчанию (`DefaultLoadBalancingPolicy` = token-aware + DC-aware + slow-replica avoidance); обязателен параметр `local-datacenter`. [Драйверы](./drivers.md)

**Q: Зачем idempotence для retry?**
`DefaultRetryPolicy` повторяет запрос максимум 1 раз и только для идемпотентных запросов. Неидемпотентный (counter-инкремент, неусловный INSERT) при таймауте не ретраится — драйвер сразу rethrow, чтобы не создать дубликат. `ConsistencyDowngradingRetryPolicy` опасен: понижает consistency level. [Драйверы](./drivers.md)

**Q: Как драйвер переподключается к упавшему узлу?**
`ExponentialReconnectionPolicy` (дефолт): экспоненциальный backoff, `base-delay = 1s`, `max-delay = 60s`. `reconnect-on-init = false` (дефолт): при неудаче первого подключения session бросает ошибку сразу. [Драйверы](./drivers.md)

**Q: Почему SimpleStatement не маршрутизируется на реплику?**
Routing key вычисляется автоматически только для BoundStatement (prepared), если связаны все компоненты partition key. Для SimpleStatement routing keyspace/key задаются вручную — иначе запрос идёт на случайный узел локального DC. [Драйверы](./drivers.md)

## ScyllaDB-специфика

**Q: Почему ScyllaDB быстрее Cassandra?**
Seastar: shard-per-core (shard привязан к ядру, нет shared memory и блокировок между shards), userspace I/O scheduler с приоритизацией latency-чувствительных запросов перед compaction/streaming, отсутствие GC (C++). Совместимость по CQL-протоколу. [Архитектура](./architecture.md)

**Q: Что такое RBNO?**
Repair Based Node Operations — node-операции (bootstrap, replace, rebuild, decommission, remove), использующие repair для потоковой передачи данных; включён по умолчанию с ScyllaDB 5.4. [Обслуживание](./operations.md)

**Q: Что такое scylla-doctor?**
Инструмент проверки узла: системные требования, конфигурация и тюнинг; выводит `.vitals.json` и архив логов — первый артефакт для эскалации в ScyllaDB. [Troubleshooting](./troubleshooting.md)

**Q: Что проверяет `developer_mode` в ScyllaDB?**
Строгие проверки окружения (дефолт `false` — проверки включены): файловая система XFS и асинхронный I/O. Отключение (`true`) снимает проверки — только для dev. [Тюнинг](./performance.md)

## Операции, миграция и capacity

**Q: Как добавить узел в кластер?**
Bootstrap: новый узел с `auto_bootstrap: true` (дефолт) получает свои диапазоны токенов и стримит данные. После — `nodetool cleanup` на узлах, потерявших диапазлы (данные не удаляются автоматически). [Обслуживание](./operations.md)

**Q: Чем decommission отличается от removenode?**
`decommission` — живой узел: данные стримятся с него самого. `removenode <host_id>` — мёртвый узел: данные стримятся с оставшихся реплик. ScyllaDB: указывать host ID, не IP. [Обслуживание](./operations.md)

**Q: Как оценить число узлов?**
Ёмкость = данные × RF × headroom compaction (STCS — до 2×, LCS — ~1.1×) / размер диска; плюс соотношение storage:RAM ≤ 30:1. Формулы и примеры — [Capacity planning](./capacity-planning.md).

**Q: Как мигрировать Cassandra → ScyllaDB?**
ScyllaDB Hydra (бывший ScyllaDB Migrator) — Spark-приложение для переноса данных из CQL-источников (Cassandra) и DynamoDB в ScyllaDB. [Миграция и upgrade](./upgrade-migration.md)

**Q: Как upgrade Cassandra 3.11 → 5.0?**
Rolling upgrade по узлам: `nodetool drain` → stop → обновить бинари → start → дождаться UN; `nodetool upgradesstables` — только после upgrade ВСЕХ узлов. Путь по мажорным версиям — через промежуточный upgrade (3.11 → 4.0 → 5.0); точная матрица — в официальном upgrade guide. [Миграция и upgrade](./upgrade-migration.md)

**Q: Что такое RPO/RTO для Cassandra/ScyllaDB?**
RPO — максимально допустимая потеря данных (определяется репликацией и частотой бэкапов), RTO — время восстановления. Multi-DC: асинхронная репликация между DC + бэкап offsite. [Multi-DC и DR](./multi-dc-dr.md)

## См. также

- **[Обзор и моделирование данных](./overview.md)** — теория и модель данных.
- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — внутренняя архитектура.
- **[Обслуживание и эксплуатация](./operations.md)** — compaction, repair, жизненный цикл узлов.
- **[Тюнинг производительности](./performance.md)** — JVM, I/O, антипаттерны.
- **[Мониторинг и observability](./monitoring.md)** — метрики и алерты.
- **[Бэкап и восстановление](./backup-recovery.md)** — снапшоты, PITR, restore.
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — исключения и диагностика.
- **[Клиентские драйверы](./drivers.md)** — пулы, LBP, retry.
- **[Capacity planning](./capacity-planning.md)** — расчёт ёмкости.
- **[Multi-DC и аварийное восстановление](./multi-dc-dr.md)** — несколько DC, DR.
- **[Миграция и upgrade](./upgrade-migration.md)** — upgrade, Cassandra → ScyllaDB.
- **[Runbook](./runbook.md)** — алерты → диагностика → действие.
