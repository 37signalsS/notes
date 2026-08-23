# Proposal Pipeline: внутренний путь записи в etcd

**Proposal Pipeline** — это детальный путь, который проходит запись от клиентского gRPC-запроса до сохранения в BoltDB. Понимание каждого этапа необходимо для диагностики latency spikes.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Proposal** | Запрос на запись, создаваемый лидером и рассылаемый по Raft. |
| **Entry** | Одна запись в Raft-логе (содержит команду MVCC). |
| **Committed Index** | Индекс последней записи, подтверждённой кворумом. |
| **Applied Index** | Индекс последней записи, применённой к BoltDB. |
| **Raft Index Gap** | Разница между Committed Index и Applied Index. |
| **Proposal Buffer** | Очередь неразрешённых proposals в памяти лидера. |
| **Linearizable Write** | Гарантия, что запись видна всем клиентам после ответа. |

---

## Основные концепции

### Полный путь записи (Write Flow)

```
Клиент → gRPC → Лидер → [Proposal Buffer] → WAL (fsync) → Репликация → Кворум → Commit → Apply → BoltDB → Ответ
```

**Этап 1: gRPC и Proposal**

1. Клиент отправляет `Put`/`Delete`/`Txn` через gRPC.
2. Лидер создаёт `Proposal` (Raft Entry) с уникальным `Index`.
3. Entry добавляется в **Proposal Buffer** (in-memory очередь).
4. Лидер возвращает клиенту acknowledgement (но НЕ завершает запись!).

**Этап 2: WAL на лидере**

5. Entry записывается в локальный WAL.
6. Вызывается `fdatasync()` — критический момент.
7. Если `fdatasync` занимает > 10 ms — начинается джиттер heartbeat, возможен split-brain.

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
15. **BoltDB** записывает данные на диск (B+ tree, CoW).
16. Applied Index увеличивается.

**Этап 6: Ответ клиенту**

17. Клиент получает ответ (ревизия, mod_revision).
18. Запись завершена.

### Parallelism в Proposal Pipeline

etcd обрабатывает proposals **последовательно** (serial apply), но с параллельными чтениями:

- **WAL writes:** Параллельные на лидере и follower'ах (каждый узел пишет в свой WAL независимо).
- **Apply:** Последовательный на каждом узле (чтобы сохранить порядок ревизий).
- **Reads:** Могут выполняться параллельно с writes (через ReadIndex).

**Важно:** Если Apply отстаёт от Commit (Raft Index Gap растёт), лидер не может скомпактировать старые ревизии, так как они ещё не применены к MVCC.

### Raft Index Gap

```bash
# Проверить gap
etcdctl endpoint status --cluster -w table
# → RAFT INDEX (записан) vs RAFT APPLIED INDEX (применен)
# → Разница > 10 000 — follower отстаёт
```

**Причины gap:**
- Медленный диск (BoltDB write latency).
- Высокая нагрузка на CPU (Protobuf serialization, hashing).
- Большие transaction (много операций в одном Txn).
- Defragmentation во время активных writes.

### Proposal Buffer Overflow

Если лидер не успевает обрабатывать proposals (например, диск перегружен):
- Buffer заполняется.
- Новые proposals отклоняются с ошибкой: `etcdserver: too many concurrent requests`.
- Клиент получает `Unavailable` или `DeadlineExceeded`.

**Защита:** Лидер ограничивает размер buffer (конфигурируется через `--max-snapshot-store-open-requests` и другие внутренние параметры).

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

# 4. Проверить proposals failed
curl -s http://localhost:2379/metrics | grep etcd_server_proposals_failed_total
```

**Интерпретация:**
- Если `fsync` > 10 ms → проблема с диском.
- Если `backend_commit` > 25 ms → проблема с BoltDB (фрагментация, медленный диск).
- Если `Index Gap` растёт → Apply отстаёт от Commit (disk/CPU bottleneck).
- Если `proposals_failed_total` растёт → buffer overflow или потеря кворума.

### Tuning proposal throughput

```bash
# Увеличить размер proposal buffer (в etcd.conf.yml)
# Внимание: это внутренние параметры, меняйте с осторожностью
max-snapshot-store-open-requests: 1000

# Уменьшить snapshot-count для более частых compaction
--snapshot-count=5000

# Увеличить лимиты дескрипторов
LimitNOFILE=65536
```

### Тестирование proposal pipeline под нагрузкой

```bash
# Запустить нагрузочный тест
etcdctl check perf --load="l"

# Параллельно мониторить метрики
watch -n 1 'curl -s http://localhost:2379/metrics | grep -E "proposals_failed|leader_changes|wal_fsync"'
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `proposals_failed_total` растёт | Buffer overflow или потеря кворума | Проверить `etcd_server_has_leader`; увеличить buffer; проверить диск |
| `wal_fsync_duration_seconds` p99 > 100 ms | Диск перегружен или HDD | Перейти на NVMe; выделить отдельный диск для WAL |
| `backend_commit_duration_seconds` высокий | BoltDB фрагментация | Defrag; проверить `db_total_size_in_use` |
| Raft Index Gap растёт | Apply отстаёт от Commit | Проверить iowait; проверить CPU throttling; уменьшить snapshot-count |
| `context deadline exceeded` на клиенте | Write path перегружен | Увеличить тайм-аут на клиенте; проверить лидерство |

---

## Best Practices

- **NVMe для WAL:** Задержка `fdatasync` < 1 ms — prerequisite.
- **Отдельный диск для WAL:** Минимизирует конкуренцию с BoltDB.
- **Monitor Index Gap:** Если gap стабильно > 5000 — проблема с производительностью.
- **Не увеличивайте `max-request-bytes` без необходимости:** Большие запросы замедляют apply.
- **Sequential writes:** etcd оптимизирован для последовательных записей. Избегайте массовых параллельных writes (> 10k RPS) на один лидер.

---

## Edge Cases

- **Large Txn:** Транзакция с 1000 операциями создаёт один большой entry. Это замедляет replication и apply. Разбивайте на меньшие транзакции.
- **Follower read:** Чтение с follower'а не проходит через proposal pipeline (читает локальный BoltDB). Но для linearizability требуется ReadIndex на лидере.
- **Proposal during leadership transfer:** Если лидер передаёт полномочия во время активного write, proposal может быть отложен. Клиент получит `leader changed` и должен retry.
- **Snapshot during write:** Создание снапшота не блокирует writes (copy-on-write в BoltDB), но создаёт дополнительную нагрузку на диск.

---

## См. также

* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — пути записи и чтения.
* **[Raft консенсус](./raft_consensus.md)** — детали консенсуса и выборов.
* **[Внутреннее устройство хранения](./storage_internals.md)** — BoltDB и CoW.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики proposal и latency.
