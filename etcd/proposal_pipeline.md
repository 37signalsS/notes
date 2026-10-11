# Proposal Pipeline: внутренний путь записи в etcd

**Актуально для:** etcd 3.7.x

**Proposal Pipeline** — это детальный путь, который проходит запись от клиентского gRPC-запроса до сохранения в BoltDB. Понимание каждого этапа необходимо для диагностики latency spikes.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Proposal** | Запрос на запись, создаваемый лидером и рассылаемый по Raft. |
| **Entry** | Одна запись в Raft-логе (содержит команду MVCC). |
| **Committed Index** | Индекс последней записи, подтверждённой кворумом. |
| **Applied Index** | Индекс последней записи, применённой к BoltDB. |
| **Raft Index Gap** | Разница между Committed Index и Applied Index. |
| **Proposal Buffer** | Очередь принятых лидером proposals, ещё не применённых к MVCC (pending proposals). |
| **maxGapBetweenApplyAndCommitIndex** | Хардкодный лимит etcdserver (5000): максимальная разница между committed и applied index. При достижении — отклонение записей. |
| **Linearizable Write** | Гарантия, что запись видна всем клиентам после ответа. |

**Prerequisites:** работающий кластер etcd (3.6+/3.7), доступ к client-эндпоинту (`:2379`) и к `/metrics`, `etcdctl` для проверки raft-позиций.

---

## Основные концепции

### Полный путь записи (Write Flow)

```
Клиент → gRPC → (follower → forward) → Лидер → WAL (fsync) → AppendEntries → Кворум ACK → Commit → Apply (MVCC + BoltDB) → Ответ клиенту
```

**Этап 1: gRPC и Proposal**

1. Клиент отправляет `Put`/`Delete`/`Txn` через gRPC. Запрос можно отправить на любой узел: запись, пришедшая на follower, автоматически перенаправляется на лидера (forwarding); сериализуемые (serializable) чтения обрабатываются любым узлом.
2. Лидер создаёт `Proposal` (Raft Entry) с уникальным `Index`.
3. Entry добавляется в очередь pending proposals (in-memory).
4. Клиент НЕ получает ответ на этом этапе: gRPC-вызов блокируется до применения записи (этап 5). Раннего acknowledgement в etcd нет — ответ приходит только после Apply.

**Этап 2: WAL на лидере**

5. Entry записывается в локальный WAL.
6. Вызывается `fdatasync()` — критический момент.
7. Если `fdatasync` занимает > 10 ms — джиттер heartbeat; при систематическом отставании лидер пропускает heartbeat'ы и может потерять лидерство (выборы, рост `etcd_server_leader_changes_seen_total`). Split-brain в Raft невозможен по построению: за один term существует только один лидер.

**Этап 3: Репликация**

8. Лидер параллельно рассылает `AppendEntries` всем follower'ам.
9. Follower'ы записывают entry в свой WAL и вызывают `fdatasync`.
10. Follower'ы отправляют `ACK` лидеру.

**Этап 4: Commit (Консенсус)**

11. Лидер ждёт ACK от кворума (`(N/2) + 1`).
12. Как только кворум набран, entry помечается **Committed**.
13. Лидер отправляет `Commit` всем узлам (включая себя).

**Этап 5: Apply (MVCC)**

14. **treeIndex** обновляется в памяти (новая ревизия, ключ → версия).
15. Изменения буферизуются в backend и сбрасываются в **BoltDB** (B+ tree, CoW) пакетами: не чаще чем раз в 100 ms или при накоплении 10 000 операций (`--backend-batch-interval`, `--backend-batch-limit`). Latency этого коммита — метрика `etcd_disk_backend_commit_duration_seconds`.
16. Applied Index увеличивается.

**Этап 6: Ответ клиенту**

17. Клиент получает ответ (ревизия, mod_revision).
18. Запись завершена.

### Parallelism в Proposal Pipeline

etcd обрабатывает proposals **последовательно** (serial apply), но с параллельными чтениями:

- **WAL writes:** Параллельные на лидере и follower'ах (каждый узел пишет в свой WAL независимо).
- **Apply:** Последовательный на каждом узле (чтобы сохранить порядок ревизий).
- **Reads:** Могут выполняться параллельно с writes (через ReadIndex).

**Важно:** Если Apply отстаёт от Commit (Raft Index Gap растёт), усечение Raft-лога ограничено applied index — записи не могут быть удалены из лога до применения. MVCC-компакция (`--auto-compaction-retention`) — отдельный механизм, см. [Сборка мусора и компакция](./garbage_collection.md).

### Raft Index Gap

```bash
# Проверить gap
etcdctl endpoint status --cluster -w table
# → RAFT INDEX (записан) vs RAFT APPLIED INDEX (применен)
# → Разница стабильно > 1000 — apply отстаёт; приближение к 5000 — критично
```

**Причины gap:**
- Медленный диск (WAL fsync, BoltDB write latency).
- Высокая нагрузка на CPU (Protobuf serialization, hashing).
- Большие транзакции (много операций в одном Txn) и тяжёлые range/delete-range запросы.
- Defragmentation во время активных writes (defrag блокирует apply на узле).

### Отклонение proposals (apply отстаёт от commit)

Если лидер не успевает применять записи (медленный диск, defrag, тяжёлые запросы), разница между committed и applied index растёт. Лимит — **хардкодная константа etcdserver `maxGapBetweenApplyAndCommitIndex = 5000`** (введена в 2016 г., PR etcd-io/etcd#5927; запрос на конфигурируемый флаг отклонён как «working as designed» — issue etcd-io/etcd#18175):

- При gap ≥ 5000 новые **mutable-запросы** (`Put`/`Delete`/`Txn`) отклоняются с ошибкой `etcdserver: too many requests` (gRPC `ResourceExhausted`).
- **Immutable-запросы** (чтения) при этом могут продолжать работать; но если apply тормозит из-за defrag — блокируются все запросы.
- Клиент также может получить `context deadline exceeded`, если запись висит в очереди дольше клиентского тайм-аута.

**Мониторинг:** `etcd_server_proposals_pending` (устойчивый рост — запись не успевает коммититься; алерт в [мониторинге](./etcd_monitoring.md) при > 100) и `etcd_server_slow_apply_total` (спайки — apply тормозит).

**Важно:** размер backlog увеличить флагом нельзя — единственное лечение — устранить причину отставания apply (диск, CPU, defrag, тяжёлые запросы).

---

## Практические сценарии

### Диагностика высокой latency записи

```bash
# 1. Проверить WAL fsync latency
curl -s http://localhost:2379/metrics | grep etcd_disk_wal_fsync_duration_seconds

# 2. Проверить Backend commit latency
curl -s http://localhost:2379/metrics | grep etcd_disk_backend_commit_duration_seconds

# 3. Проверить Raft Index Gap
etcdctl endpoint status --cluster -w table

# 4. Проверить proposals failed / pending / slow apply
curl -s http://localhost:2379/metrics | grep -E "etcd_server_proposals_failed_total|etcd_server_proposals_pending|etcd_server_slow_apply_total"
```

**Интерпретация:**
- Если `fsync` p99 > 10 ms → проблема с диском (WAL).
- Если `backend_commit` p99 > 25 ms → проблема с BoltDB (фрагментация, медленный диск).
- Если `Index Gap` растёт → Apply отстаёт от Commit (disk/CPU bottleneck); приближение к 5000 — риск отклонения записей.
- Если `proposals_failed_total` растёт → отклонение из-за gap ≥ 5000 или потеря кворума.
- Если `proposals_pending` устойчиво > 100 → запись не успевает коммититься (диск/сеть/кворум).
- Если `slow_apply_total` растёт → apply тормозит (дефрагментация, тяжёлые транзакции).

### Tuning proposal throughput

Размер proposal backlog конфигурировать нельзя (хардкодный лимит 5000). Настраиваемые рычаги:

```bash
# Размер одного запроса (default 1.5 MB) — большие запросы = большие Raft-entry
--max-request-bytes=33554432

# Число операций в одной Txn (default 128) — больше операций в entry замедляет apply
--max-txn-ops=256

# Частота снапшотов Raft (default 10 000 в 3.6+). НЕ инструмент compaction:
# compaction настраивается через --auto-compaction-retention / --auto-compaction-mode.
# Снижать ниже 10 000 не рекомендуется — чаще снапшоты = больше нагрузки на диск.
--snapshot-count=10000

# Интервал и лимит пакетного коммита в BoltDB (default 100 ms / 10 000 ops)
--backend-batch-interval=100ms
--backend-batch-limit=10000

# Лимиты дескрипторов (systemd)
LimitNOFILE=65536
```

### Тестирование proposal pipeline под нагрузкой

```bash
# Нагрузочный тест (60 секунд). Модели: s (50 клиентов, 10k put/s),
# m (200, 100k), l (500, 1M), xl (1000, 3M)
etcdctl check perf --load="l" --auto-compact=true --auto-defrag=true

# Критерии PASS: throughput ≥ 90% от целевого, самый медленный запрос < 500 ms,
# стандартное отклонение < 100 ms
# → PASS: Throughput is 8123 writes/s

# Параллельно мониторить метрики
watch -n 1 'curl -s http://localhost:2379/metrics | grep -E "proposals_failed|proposals_pending|leader_changes|wal_fsync"'
```

Для замера реальной пропускной способности (а не пороговой проверки) — утилита `benchmark`, см. [бенчмаркинг](./benchmarking.md).

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `proposals_failed_total` растёт | Gap apply-commit ≥ 5000 или потеря кворума | Проверить `etcd_server_has_leader` и `etcd_server_proposals_pending`; найти причину тормозящего apply (диск, defrag, тяжёлые Txn) |
| `wal_fsync_duration_seconds` p99 > 100 ms | Диск перегружен или HDD | Перейти на NVMe; выделить отдельный диск для WAL |
| `backend_commit_duration_seconds` высокий | BoltDB фрагментация | Defrag (вне пиков, см. [Maintenance API](./maintenance_api.md)); проверить `db_total_size_in_use` |
| Raft Index Gap растёт | Apply отстаёт от Commit | Проверить iowait, CPU throttling, расписание defrag; тяжёлые range/delete-range запросы |
| `etcdserver: too many requests` | Gap apply-commit достиг 5000 | Устранить причину медленного apply; снизить нагрузку; «буфер» увеличить нельзя — лимит хардкодный |
| `context deadline exceeded` на клиенте | Write path перегружен | Увеличить тайм-аут на клиенте; проверить лидерство |

---

## Best Practices

- **NVMe для WAL:** Задержка `fdatasync` < 1 ms — prerequisite.
- **Отдельный диск для WAL:** Минимизирует конкуренцию с BoltDB.
- **Monitor Index Gap:** Gap стабильно > 1000 — разбираться; приближение к 5000 — записи начнут отклоняться.
- **Не увеличивайте `--max-request-bytes` и `--max-txn-ops` без необходимости:** Большие entry'и замедляют replication и apply.
- **Замеряйте пропускную способность** через `benchmark`/`check perf` в своей среде: универсального лимита RPS нет — он определяется диском и сетью (эталонные замеры — в [бенчмаркинге](./benchmarking.md)).
- **Defrag — вне пиков и по одному узлу:** defrag на лидере блокирует apply и может вызвать отклонение записей (`too many requests`).

---

## Edge Cases

- **Large Txn:** По умолчанию etcd ограничивает транзакцию 128 операциями (`--max-txn-ops`); Txn с 1000 операциями будет отклонён с `etcdserver: too many operations in txn request`. Если лимит повышен — большой entry замедляет replication и apply. Разбивайте на меньшие транзакции.
- **Follower read:** Чтение с follower'а не проходит через proposal pipeline (читает локальный BoltDB). Но для linearizability требуется ReadIndex на лидере.
- **Proposal during leadership transfer:** Если лидер передаёт полномочия во время активного write, proposal может быть отложен. Клиент получит `leader changed` и должен retry.
- **Snapshot during write:** Создание снапшота не блокирует writes (copy-on-write в BoltDB), но создаёт дополнительную нагрузку на диск.

---

## См. также

* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — пути записи и чтения.
* **[Raft консенсус](./raft_consensus.md)** — детали консенсуса и выборов.
* **[Внутреннее устройство хранения](./storage_internals.md)** — BoltDB и CoW.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики proposal и latency.
* **[Лимиты и ограничения](./limits_and_constraints.md)** — `--max-request-bytes`, `--max-txn-ops`, quota.
* **[Бенчмаркинг](./benchmarking.md)** — замер пропускной способности.
* **[Сборка мусора и компакция](./garbage_collection.md)** — MVCC-компакция (не путать со снапшотами).
* **[Maintenance API](./maintenance_api.md)** — defrag и алармы.
