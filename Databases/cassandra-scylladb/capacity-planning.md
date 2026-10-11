# Планирование ёмкости (Capacity Planning)

**Актуально для:** Apache Cassandra 4.0/5.0.x / ScyllaDB 2026.x

## Определения

| Термин | Определение |
| :--- | :--- |
| Compaction headroom | Запас места на диске для работы compaction: STCS требует до 50% свободного места, LCS — ~10% |
| RF (Replication Factor) | Число копий данных; production-стандарт `RF=3` |
| lcore | Logical core (ядро с гиперпоточностью); ScyllaDB считает ресурсы в lcore |
| storage:RAM ratio | Соотношение объёма данных на узле к RAM; не более 30:1 |
| Repair bandwidth | Сетевой трафик repair: суммарно ≈ объём данных × RF за окно обслуживания |
| RPO / RTO | Максимально допустимая потеря данных / время восстановления (теория — [Disaster Recovery](../../Concepts/disaster_recovery.md)) |
| Token ring | Непрерывное кольцо хешей; узел владеет одной или несколькими позициями (токенами) на кольце |
| vNode | Виртуальный узел — токен на кольце, принадлежащий физическому узлу |
| Tablet | Единица распределения данных в ScyllaDB: партиции детерминистически отображаются на tablet |

Общая теория планирования ёмкости — **[Capacity Planning](../../Concepts/capacity-planning.md)**; здесь — специфика Cassandra/ScyllaDB.

## Как устроена ёмкость

Capacity planning для Cassandra/ScyllaDB — **три независимых ограничения**: диск (данные + compaction), память (кэши, ratio storage:RAM) и сеть (repair/streaming + клиентский трафик). Узел ограничен самым узким из трёх; добавление узлов по одному измерению не лечит узкое место в другом.

### Диск

```
Диск на узел = (Исходные данные × RF × compaction headroom) / число узлов
```

Headroom по стратегии compaction (стратегии — в [Обслуживании](./operations.md)):

| Стратегия | Headroom | Почему |
| :--- | :--- | :--- |
| STCS | до 2× (50% свободного) | слияние SSTables схожего размера требует места для нового файла |
| LCS | ~1.1× (10% запаса) | фиксированный размер SSTables на уровнях L1+ |
| TWCS | зависит от TTL-окон | истёкшие файлы удаляются целиком, без дорогостоящего слияния |

**Важно:** При расчёте учитывайте, что `nodetool status` показывает **Load** (размер данных без headroom). Для STCS рабочий запас — не более 50% заполнения диска.

### Память

- **storage:RAM ≤ 30:1** (128 ГБ RAM → ≤ 3.8 ТБ данных на узел) — [Тюнинг](./performance.md)
- **ScyllaDB:** RAM 16 ГБ или 2 ГБ на lcore — больше из двух; production-минимум 4 ГБ или 0.5 ГБ на lcore
- **Cassandra:** heap ≤ 31 ГБ (compressed oops) и не более 50% RAM; остальное RAM — page cache ОС

### Сеть

- **Repair:** суммарный трафик ≈ объём данных × RF за окно обслуживания; на узел ≈ (данные × RF / число узлов) / окно
- **Throttling:** `nodetool setstreamthroughput` (streaming: bootstrap, repair, rebuild), `inter_dc_stream_throughput_outbound_megabits_per_sec` — между DC (дефолт 200 Мбит/с)
- **Клиентский трафик (ScyllaDB):** 1–3 соединения на ядро от каждого клиента

### CPU

- **Cassandra:** `concurrent_writes = 8 × число ядер`, `concurrent_reads = 16 × число дисков` — [Тюнинг](./performance.md)
- **ScyllaDB:** ядра не делить с другими процессами; `scylla_reactor_utilization < 0.7`

---

## Практические сценарии / Установка и настройка

### Пример расчёта числа узлов

Исходные данные: 10 ТБ, `RF=3`, STCS, диски 2 ТБ:

```
Реплицированный объём:        10 ТБ × 3 = 30 ТБ
С учётом headroom STCS (2×):  30 ТБ × 2 = 60 ТБ
Usable на узел (50% от 2 ТБ): 1 ТБ
Число узлов:                  60 ТБ / 1 ТБ = 60 узлов
Данных на узел:               30 ТБ / 60 = 500 ГБ
Проверка RAM:                 500 ГБ / 30 = 16.7 ГБ → минимум → 32 ГБ на узел
```

### Пример расчёта repair-окна

Те же 60 узлов, окно обслуживания 8 часов:

```
Трафик repair на узел: 500 ГБ / 8 ч ≈ 17 МБ/с
Дефолт stream throughput: 200 Мбит/с (25 МБ/с) → укладывается с запасом
```

Не укладывается — увеличьте окно, поднимите throttling (`nodetool setstreamthroughput`) или сегментируйте repair (Cassandra Reaper).

### Пошаговая процедура capacity planning для нового кластера

1. **Соберите требования:**
   - Объём исходных данных (raw data)
   - Ожидаемый рост в месяц/год
   - Требования к latency (p99) и throughput (RPS)
   - RPO/RTO для DR

2. **Выберите RF и стратегию compaction:**
   - Production: `RF=3` + `NetworkTopologyStrategy`
   - STCS — для write-heavy / immutable data (логи, метрики)
   - LCS — для read-heavy / frequent updates
   - TWCS — для TTL-based data (time-series, метрики с TTL)

3. **Рассчитайте диск на узел:**
   ```
   disk_per_node = (raw_data_GB × RF × headroom_factor) / node_count
   ```
   Округлите вверх до ближайшего стандартного размера диска с запасом 20%.

4. **Проверьте storage:RAM ratio:**
   - Данные на узел ≤ RAM_GB × 30
   - Если не проходит — увеличьте RAM или число узлов

5. **Рассчитайте сеть для repair:**
   - `repair_MBps_per_node = (data_per_node_GB × 1024) / (maintenance_window_hours × 3600)`
   - Сравните с `stream_throughput_outbound_megabits_per_sec / 8`
   - При нехватке — увеличьте окно или throttling

6. **Подберите CPU:**
   - Cassandra: `concurrent_writes = 8 × cores` → cores ≥ expected_writes_per_sec / 8
   - ScyllaDB: cores ≥ 2 × expected_concurrent_connections_per_client

7. **Валидируйте на тестовом кластере:**
   - Запустите `cassandra-stress` / `scylla-bench` с production-подобной нагрузкой
   - Проверьте p99 latency, GC pauses (Cassandra), reactor utilization (ScyllaDB)
   - Корректируйте параметры

### Hardware selection для on-premise / colocation

| Компонент | Рекомендация Cassandra | Рекомендация ScyllaDB |
| :--- | :--- | :--- |
| **CPU** | 8+ ядер, 2.5+ GHz (AMD EPYC / Intel Xeon) | 16+ lcores (20–60 рекомендуется), AVX2/SSE4.2 обязательны |
| **RAM** | 32–64 ГБ (heap ≤ 31 ГБ) | 16 ГБ или 2 ГБ/lcore (больше из двух); production 64–256 ГБ |
| **Диски** | NVMe SSD (для commitlog — отдельный spindle на HDD) | NVMe SSD (XFS, noatime); `scylla_io_setup` калибрует I/O |
| **Сеть** | 10 Gbps+ внутри DC | 10 Gbps+ (25 Gbps рекомендуется для repair/streaming) |
| **RAID** | RAID0 для data (репликация на уровне СУБД) | RAID0 или JBOD; ScyllaDB не требует RAID |

**Файловая система:** XFS с `noatime` — рекомендуется для обеих СУБД (проверяется `developer_mode` в ScyllaDB).

---

## Операции и команды

### Ключевые команды для оценки ёмкости

```bash
# Общий статус кластера и загрузка узлов
nodetool status
# → Load, Owns, Host ID, Status (UN/UL/DN)

# Детальная информация по узлу
nodetool info
# → Load, Token, Heap, Key Cache, Row Cache, etc.

# Использование диска по таблицам
nodetool tablestats <keyspace> <table>
# → Space used (live), Space used (total), SSTable count, Memtable size

# История compaction
nodetool compactionhistory
# → id, keyspace, table, compacted_at, bytes_in, bytes_out, rows_merged

# Статистика compaction в реальном времени
nodetool compactionstats
# → pending tasks, active compactions, throughput

# Статистика repair
nodetool netstats
# → Mode, Read/Write repair stats, streaming stats

# Процент repaired данных (Cassandra 4.0+)
nodetool repair_admin summarize-repaired
# → timestamp последнего успешного repair

# Проверка токенов / баланс (Cassandra vnodes)
nodetool ring
# → Token ranges per node, Ownership %

# Проверка tablets / баланс (ScyllaDB)
nodetool describering <keyspace> <table>
# → Tablet ranges, replicas, sizes

# Throttling streaming (bootstrap, repair, rebuild)
nodetool setstreamthroughput 100    # МБ/с (0 = без лимита)
nodetool getstreamthroughput

# Throttling compaction
nodetool setcompactionthroughput 16 # МБ/с (0 = без лимита)
nodetool getcompactionthroughput

# Throttling меж-DC streaming
nodetool setrpcthroughput 100       # Мбит/с
nodetool getrpcthroughput
```

### Команды для capacity planning в ScyllaDB

```bash
# Проверка reactor utilization (должен быть < 0.7)
curl -s http://127.0.0.1:10000/metrics | grep scylla_reactor_utilization

# Проверка I/O свойств диска (после scylla_io_setup)
cat /etc/scylla.d/io_properties.yaml

# Метрики memory / cache
curl -s http://127.0.0.1:10000/metrics | grep -E 'scylla_memory|scylla_cache'

# Метрики tablet migration / load balancer
curl -s http://127.0.0.1:10000/metrics | grep -E 'scylla_tablet|scylla_balancer'

# Scylla Manager: статус repair задач
sctool repair --status
```

### Команды для capacity planning в Cassandra

```bash
# JVM heap и GC статистика
nodetool info | grep -i heap
nodetool gcstats

# Thread pool statistics (pending / blocked / dropped)
nodetool tpstats
# → ReadStage, WriteStage, CompactionStage, MutationStage

# Key cache hit rate
nodetool info | grep -i "key cache"

# Проверка версии схемы на всех узлах (schema agreement)
nodetool describecluster

# Slow query log (настроен в cassandra.yaml)
# tail -f /var/log/cassandra/system.log | grep "Slow query"
```

---

## Поиск и устранение неисправностей

| Симптом | Вероятные причины | Действия |
| :--- | :--- | :--- |
| Диск заполнен во время compaction | нет headroom, STCS на полном диске | добавить место/узлы; пересмотреть стратегию (LCS/TWCS); `nodetool setcompactionthroughput` |
| Repair не укладывается в окно | мало времени или узкая сеть | увеличить окно; `nodetool setstreamthroughput`; сегментация repair (Reaper) |
| Неравномерный Load | дисбаланс токенов/tablets | `nodetool ring`; `nodetool move`/`relocate` (vnodes) или tablet migration (ScyllaDB) |
| Latency растёт при малой нагрузке | узел перегружен (данные/запросы) | `nodetool toppartitions` — горячие партиции; масштабирование |
| OOM / частые GC pauses (Cassandra) | heap > 31 ГБ, GC не настроен, row cache включён | heap ≤ 31 ГБ, G1 для > 12 ГБ, отключить row cache |
| ScyllaDB: reactor utilization > 0.8 | CPU-bound нагрузка, мало ядер | добавить ядра; проверить клиентские соединения (1–3 на ядро); `scylla_setup` |
| Tombstones не удаляются | `gc_grace_seconds` не выдержан, repair реже срока | repair чаще `gc_grace_seconds`; TWCS для TTL; `only_purge_repaired_tombstone` |
| Streaming завис при bootstrap | сеть, диск, недоступные seed | `nodetool status`; проверить JMX порт; seed-узлы доступны |
| PendingTasks растут (CompactionStage) | compaction не успевает за write rate | увеличить `concurrent_compactors`; LCS вместо STCS; добавить узлы |
| Read timeout / high latency | read amplification, много SSTables | major compaction (`nodetool compact`); LCS; проверить Bloom filter hit rate |

---

## Рекомендации и лучшие практики

### Планирование
- Планируйте под **три ограничения** (диск, память, сеть): узел ограничен самым узким
- Headroom зависит от стратегии compaction — считайте его **до** выбора стратегии
- Repair-трафик планируйте в окно обслуживания; throttling обязателен при работающей нагрузке
- После topology-изменений — `nodetool cleanup` на узлах, потерявших диапазлы (иначе место не освобождается)
- Перепланируйте ёмкость при смене объёма данных, RF или стратегии compaction

### Мониторинг и алертинг (DevOps/SRE)

**Ключевые метрики для Prometheus/VictoriaMetrics:**

| Метрика | PromQL | Порог warning | Порог critical |
| :--- | :--- | :--- | :--- |
| Disk usage (с headroom STCS) | `node_filesystem_avail_bytes / node_filesystem_size_bytes` | < 30% free | < 15% free |
| Disk usage (LCS) | `node_filesystem_avail_bytes / node_filesystem_size_bytes` | < 15% free | < 10% free |
| storage:RAM ratio | `nodetool_info_load_bytes / (node_memory_MemTotal_bytes / 30)` | > 0.8 | > 1.0 |
| Repair progress | `rate(cassandra_repair_repaired_bytes_total[5m])` | < expected_rate | 0 for > window |
| ScyllaDB reactor utilization | `scylla_reactor_utilization` | > 0.7 | > 0.85 |
| Cassandra GC pause (p99) | `histogram_quantile(0.99, rate(jvm_gc_pause_seconds_bucket[5m]))` | > 500ms | > 1s |
| Pending compactions | `cassandra_compaction_pending_tasks` | > 100 | > 500 |
| Stream throughput | `rate(cassandra_streaming_bytes_total[5m])` | > 80% of limit | limit reached |

**Recording rules для capacity planning (пример):**

```yaml
# /etc/prometheus/rules/cassandra_capacity.yml
groups:
  - name: cassandra_capacity_planning
    interval: 5m
    rules:
      - record: cassandra:disk_headroom:ratio
        expr: |
          1 - (node_filesystem_avail_bytes{mountpoint="/var/lib/cassandra"} / node_filesystem_size_bytes{mountpoint="/var/lib/cassandra"})
      - record: cassandra:storage_ram_ratio:ratio
        expr: |
          nodetool_info_load_bytes / (node_memory_MemTotal_bytes / 30)
      - record: cassandra:repair_burn_rate:percent_per_hour
        expr: |
          (cassandra:storage_ram_ratio:ratio offset 1h) - cassandra:storage_ram_ratio:ratio
```

### Операционные практики
- **Еженедельно:** repair (чаще `gc_grace_seconds` = 10 дней по умолчанию) в maintenance window
- **Ежемесячно:** `nodetool scrub -m VALIDATE`, `nodetool verify` — проверка целостности SSTables
- **После upgrade:** `nodetool upgradesstables` на всех узлах
- **После topology-изменений:** `nodetool cleanup` на узлах, потерявших диапазоны
- **Ежеквартально:** перезапуск `scylla_io_setup` (ScyllaDB) — диски изнашиваются, возможности меняются

### Откат изменений
- Compaction-стратегию и `gc_grace_seconds` меняют через `ALTER TABLE` (обратимо)
- Topology-операции (decommission, replace) необратимы — перед ними снапшот (см. [Бэкап и восстановление](./backup-recovery.md))
- JVM-опции / `cassandra.yaml` — rolling restart узлов

---

## Дополнительная информация

- **[Обслуживание и эксплуатация](./operations.md)** — compaction-стратегии, repair, throttling, lifecycle узлов
- **[Тюнинг производительности](./performance.md)** — железо, storage:RAM, concurrent_reads/writes, JVM, ScyllaDB I/O
- **[Мониторинг и observability](./monitoring.md)** — метрики Load, PendingTasks, compaction backlog, repair
- **[Multi-DC и аварийное восстановление](./multi-dc-dr.md)** — меж-DC трафик, RPO/RTO, switchover/failover
- **[Бэкап и восстановление](./backup-recovery.md)** — снапшоты, инкрементальные бэкапы, restore процедуры
- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — vnodes vs tablets, gossip vs Raft, JVM vs Seastar
- **[Capacity Planning (общий)](../../Concepts/capacity-planning.md)** — общая теория, Закон Литтла, USE-методология, PSI
- **[Disaster Recovery](../../Concepts/disaster_recovery.md)** — RPO/RTO теория