# Тестирование производительности etcd

**etcd** критически чувствителен к задержкам диска и сети. Регулярное тестирование производительности позволяет обнаружить деградацию до того, как она повлияет на production. Данный документ описывает практические методы бенчмаркинга и интерпретацию результатов.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Throughput** | Количество операций в секунку (ops/sec). |
| **Latency (p50/p99)** | Задержка выполнения операции. p99 — задержка, которую превышают 1% операций. |
| **Mixed workload** | Комбинация reads и writes в одном тесте. |
| **etcdctl check perf** | Встроенный в etcdctl инструмент для быстрого smoke-теста производительности. |
| **fio** | Утилита для тестирования disk I/O (используется для baseline диска). |
| **Write Amplification** | Коэффициент, показывающий, сколько реальных записей на диск генерирует одна логическая запись (из-за CoW в BoltDB). |

---

## Основные концепции

### Что измерять

В production необходимо измерять два показателя:
1. **Throughput ceiling** — максимальное количество writes/sec, которое кластер может обработать без потери кворума.
2. **Latency under load** — p99 latency при 50% и 90% от ceiling.

**Ожидаемые значения для 3-node NVMe кластера (2026):**
- **Throughput:** 10 000–15 000 writes/sec (single key, 1 KB value).
- **Latency (p99):** < 10 мс при 50% load, < 25 мс при 90% load.
- **Read latency:** < 2 мс (linearizable), < 1 мс (serializable).

### Почему `etcdctl check perf` недостаточно

`etcdctl check perf` — это binary pass/fail тест с фиксированными порогами. Он полезен для:
- Быстрой проверки после обновления.
- Baseline сравнения.

Но он **не дает:**
- p50/p99 latency.
- Поведения под смешанной нагрузкой.
- Влияния large keys (> 1.5 MB).
- Влияния high cardinality prefixes.

### fio: baseline диска

Перед бенчмаркингом etcd обязательно проверьте диск:

```bash
# Sequential write (WAL-like)
fio --name=seqwrite --ioengine=libaio --direct=1 --rw=write --bs=4k \
    --size=1G --numjobs=1 --fsync=1 --time_based --runtime=30

# Random write (BoltDB-like)
fio --name=randwrite --ioengine=libaio --direct=1 --rw=randwrite --bs=4k \
    --size=1G --numjobs=4 --fsync=1 --time_based --runtime=30
```

**Критические пороги для NVMe:**
- `lat_avg` < 1 мс.
- `lat_p99` < 5 мс.
- IOPS > 50 000 (4K random write).

---

## Практические сценарии

### Быстрый smoke-тест (`etcdctl check perf`)

```bash
# Small load (baseline)
etcdctl check perf --load="s"
# → PASS: Throughput is 150 writes/s

# Если FAIL на s:
# - Диск не NVMe (HDD)
# - Высокий iowait (> 20%)
# - Сеть между участниками > 100 мс RTT
```

### Бенчмарк mixed workload

Используйте `etcdctl` в цикле или `hey`/`wrk` для gRPC:

```bash
# 1000 writes + 9000 reads (10% writes)
for i in $(seq 1 1000); do
  etcdctl put /bench/key-$i "value-$i"
done

# Измерение read latency
time etcdctl get /bench/key-500 --hex

# Измерение write latency
time etcdctl put /bench/key-new "value"
```

**Интерпретация:**
- Если write latency > 10 мс — проблема с `fdatasync` или Raft replication.
- Если read latency > 5 мs — проблема с BoltDB cache или disk read.

### Нагрузочный тест через Kubernetes

```bash
# Создать 10 000 ConfigMap (имитирует K8s workload)
kubectl create configmap test --from-literal=key=value --dry-run=client -o yaml | \
  awk '{print $1}' | head -n 10000 | \
  xargs -I {} kubectl create configmap {} --from-literal=key=value

# Следить за метриками
watch -n 1 'curl -s http://localhost:2379/metrics | grep etcd_server_proposals_committed_total'
```

### Определение throughput ceiling

```bash
# Мониторинг leader changes во время нагрузки
watch -n 1 'curl -s http://localhost:2379/metrics | grep etcd_server_leader_changes_seen_total'

# Мониторинг fsync latency
watch -n 1 'curl -s http://localhost:2379/metrics | grep etcd_disk_wal_fsync_duration_seconds'
```

**Ceiling reached, когда:**
- `etcd_server_leader_changes_seen_total` растет быстро (> 5 за 5 минут).
- `etcd_disk_wal_fsync_duration_seconds` p99 > 20 мс.
- `etcd_server_proposals_failed_total` растет.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `check perf` FAIL на `s` | HDD, высокий iowait, плохая сеть | Перейти на NVMe; проверить `iostat -x 1` |
| Write latency растет под нагрузкой | WAL на общем диске; CPU throttling | Выделить отдельный диск; проверить `mpstat -P ALL 1` |
| Leader flapping при нагрузке | `heartbeat-interval` слишком мал для RTT | Увеличить `election-timeout` и `heartbeat-interval` |
| OOM при large range scan | Клиент буферизирует весь Range в памяти | Использовать `RangeStream` (v3.7+) или `--limit` |

---

## Best Practices

- **Тестируйте после каждого изменения:** После обновления, смены диска, изменения конфигурации.
- **Baseline:** Запишите `check perf` результаты в changelog. Любое отклонение > 20% — алерт.
- **Не тестируйте на production:** Используйте staging-кластер с такой же аппаратной конфигурацией.
- **Учитывайте Network:** При geo-распределенных кластерах измеряйте end-to-end latency (не только disk).

---

## Edge Cases

- **Thermal throttling NVMe:** При длительной нагрузке (> 10 минут) SSD может throttling. Измеряйте в течение 30+ минут.
- **Write amplification на SSD:** Высокая фрагментация CoW увеличивает write amplification, сокращая срок служки SSD. Defrag раз в месяц.
- **Concurrent defrag + writes:** Defrag блокирует узел. При concurrent write-нагрузке latency может spike на 100%.
- **Large keys (> 1.5 MB):** По умолчанию etcd отклоняет такие ключи. Если увеличили `--max-request-bytes`, ожидайте латентность в десятки раз выше.

---

## См. также

* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики производительности.
* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — аппаратные требования.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — hardware baseline (fio).
