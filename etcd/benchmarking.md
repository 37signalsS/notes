# Тестирование производительности etcd

**Актуально для:** etcd 3.6.x / 3.7.x (RangeStream доступен с 3.7)

etcd критически чувствителен к задержкам диска и сети: минимальное время запроса — это RTT между участниками плюс `fdatasync` на диске. Официальная рекомендация — запускать бенчмарк при первом развёртывании кластера в новой среде и после любого изменения аппаратной конфигурации. Регулярное тестирование обнаруживает деградацию до того, как она повлияет на production.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Throughput** | Количество операций в секунду (ops/sec). |
| **Latency (p50/p99)** | Задержка выполнения операции. p99 — задержка, которую превышают 1% операций. |
| **Mixed workload** | Комбинация reads и writes в одном тесте. |
| **etcdctl check perf** | Встроенный smoke-тест: 60 секунд фиксированной write-нагрузки с бинарным результатом PASS/FAIL. |
| **benchmark** | Отдельный CLI-инструмент из состава etcd для нагрузочного тестирования (put, range, txn, lease, watch). |
| **fio** | Утилита для тестирования disk I/O (baseline диска перед бенчмаркингом etcd). |
| **Write Amplification** | Коэффициент, показывающий, сколько реальных записей на диск генерирует одна логическая запись (из-за CoW в BoltDB). |
| **RangeStream** | RPC в etcd 3.7+, который отдаёт большие результаты Range чанками вместо буферизации всего ответа. |

---

## Основные концепции

### Физические ограничения

Производительность консенсуса Raft ограничена двумя величинами:

1. **RTT между участниками** — в пределах одного ЦОД составляет сотни микросекунд; для стабильности кластера должен быть < 50 мс (при большем RTT heartbeat не успевает приходить до election-timeout).
2. **`fdatasync` на диске** — на вращающихся дисках типично ~10 мс, на SSD часто < 1 мс.

etcd компенсирует это батчингом: несколько клиентских запросов объединяются в одну Raft-запись, что даёт высокий throughput несмотря на латенть.

### Что измерять

1. **Throughput ceiling** — максимальное количество writes/sec, которое кластер обрабатывает без потери кворума.
2. **Latency under load** — p99 при 50% и 90% от ceiling.

**Ориентиры из официальной документации etcd** (3-node кластер, ключ 8 Б, значение 256 Б):

| Запросов | Соединений / клиентов | Consistency | Средний QPS | Средняя latency |
| :--- | :--- | :--- | :--- | :--- |
| 10 000 | 1 / 1 | Linearizable | 1 353 | 0.7 мс |
| 10 000 | 1 / 1 | Serializable | 2 909 | 0.3 мс |
| 100 000 | 100 / 1000 | Linearizable | 141 578 | 5.5 мс |
| 100 000 | 100 / 1000 | Serializable | 185 758 | 2.2 мс |

Linearizable reads проходят через кворум (дороже), serializable — обслуживаются любым одним участником (дешевле, но возможны устаревшие данные).

### Почему `etcdctl check perf` недостаточно

`check perf` — бинарный smoke-тест с фиксированным профилем нагрузки. Он **не даёт:**

- распределения p50/p99 latency (только slowest request и stddev);
- смешанной нагрузки (только writes);
- влияния large keys (> 1.5 MB) и high-cardinality prefixes;
- управления формой нагрузки (размер ключа/значения, mix операций).

Для этого служит инструмент `benchmark`.

### Инструмент `benchmark`

`benchmark` — отдельный бинарник из состава etcd (в архиве релиза рядом с `etcd` и `etcdctl`). Поддерживает операции `put`, `range`, `txn`, `lease`, `watch` с управляемыми `--conns`, `--clients`, `--key-size`, `--val-size`, `--total`.

---

## Практические сценарии

### Предварительные условия

- Тестовый кластер с той же аппаратной конфигурацией, что и production (диск, сеть, CPU).
- `etcdctl` и `benchmark` доступны на клиентской машине; `ETCDCTL_ENDPOINTS` указывает на кластер.
- Для K8s-кластеров: доступ к pod etcd (`oc exec` / `kubectl exec`).

### Smoke-тест (`etcdctl check perf`)

Тест длится ровно 60 секунд, пишет ключи (ключ 256 Б, значение 1024 Б) под префиксом `/etcdctl-check-perf/` и удаляет их по завершении. Префикс должен быть пустым, иначе тест откажется запускаться.

```bash
# Small load (baseline)
etcdctl check perf --load="s"
# → 60 / 60 Booooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooo! 100.00%1m0s
# → PASS: Throughput is 150 writes/s
# → PASS: Slowest request took 0.087509s
# → PASS: Stddev is 0.011084s
# → PASS

# Если FAIL:
# → FAIL: Throughput too low: 6808 writes/s
# → PASS: Slowest request took 0.228191s
# → PASS: Stddev is 0.033547s
# → FAIL
```

**Модели нагрузки и критерии PASS** (из исходного кода etcdctl; PASS при throughput ≥ 90% от rate limit, slowest request < 500 мс, stddev < 100 мс, без ошибок):

| `--load` | Клиентов | Rate limit (writes/s) | PASS при throughput ≥ |
| :--- | :--- | :--- | :--- |
| `s` (small) | 50 | 150 | 135 writes/s |
| `m` (medium) | 200 | 1 000 | 900 writes/s |
| `l` (large) | 500 | 8 000 | 7 200 writes/s |
| `xl` (xLarge) | 1 000 | 15 000 | 13 500 writes/s |

Полезные флаги: `--prefix=<prefix>` (другой префикс для тестовых ключей), `--auto-compact`, `--auto-defrag` (убрать историю ключей после теста — рекомендуется, тест создаёт большой keyspace).

В OpenShift: `oc exec -n openshift-etcd -it -c etcd $ETCD_POD -- etcdctl check perf --load='m'`.

### Baseline диска (fio)

Перед бенчмаркингом etcd проверьте диск. Требование Red Hat для control-plane: устройство должно выполнять **минимум 50 IOPS последовательной записи 8 КБ с `fdatasync` в пределах 10 мс**; для сильно нагруженных кластеров рекомендуется 500 IOPS по 8 КБ (2 мс).

```bash
# Sequential write с fdatasync (WAL-like, 8K blocks)
fio --name=seqwrite --ioengine=libaio --direct=1 --rw=write --bs=8k \
    --size=1G --numjobs=1 --fdatasync=1 --time_based --runtime=30

# Random write (BoltDB-like)
fio --name=randwrite --ioengine=libaio --direct=1 --rw=randwrite --bs=4k \
    --size=1G --numjobs=4 --fdatasync=1 --time_based --runtime=30
```

**Критерии:**
- `lat_p99` fdatasync < 10 мс (минимум); на SSD типично < 1 мс.
- Последовательная запись 8 КБ: ≥ 50 IOPS (минимум), ≥ 500 IOPS для heavy-load кластеров.
- Диск должен быть локальным; сетевые диски (iSCSI, NAS, SAN) дают непредсказуемую latency.

### Write throughput (`benchmark`)

```bash
# Запись в leader (1 клиент — baseline latency)
benchmark --endpoints=${HOST_1} --target-leader --conns=1 --clients=1 \
    put --key-size=8 --sequential-keys --total=10000 --val-size=256

# Запись в leader (100 conns / 1000 clients — ceiling)
benchmark --endpoints=${HOST_1} --target-leader --conns=100 --clients=1000 \
    put --key-size=8 --sequential-keys --total=100000 --val-size=256

# Запись во все участники (write распределяется по кластеру)
benchmark --endpoints=${HOST_1},${HOST_2},${HOST_3} --conns=100 --clients=1000 \
    put --key-size=8 --sequential-keys --total=100000 --val-size=256
```

`benchmark` пишет реальные ключи — после теста удалите их (`etcdctl del --prefix <prefix>`).

### Read latency (`benchmark`)

```bash
# Linearizable reads (через кворум)
benchmark --endpoints=${HOST_1},${HOST_2},${HOST_3} --conns=100 --clients=1000 \
    range YOUR_KEY --consistency=l --total=100000

# Serializable reads (с любого участника)
benchmark --endpoints=${HOST_1},${HOST_2},${HOST_3} --conns=100 --clients=1000 \
    range YOUR_KEY --consistency=s --total=100000
```

Сравнивайте с официальной таблицей выше: одиночное соединение ~0.7 мс (l) / ~0.3 мс (s); 100 conns — ~5.5 мс (l) / ~2.2 мс (s). Отклонения указывают на проблемы с диском, сетью или кэшем.

### Имитация K8s-нагрузки

```bash
# Создать 1000 ConfigMap с уникальными именами (имитирует K8s workload)
for i in $(seq 1 1000); do
  kubectl create configmap bench-$i --from-literal=key=value
done

# Мониторинг proposals во время нагрузки
watch -n 1 'curl -s http://localhost:2379/metrics | grep etcd_server_proposals_committed_total'

# Очистка
for i in $(seq 1 1000); do
  kubectl delete configmap bench-$i
done
```

### Определение throughput ceiling

Наращивайте `--clients`/`--conns` в `benchmark put` и следите за метриками (пороги согласованы с etcd_monitoring.md):

```bash
watch -n 1 'curl -s http://localhost:2379/metrics | grep -E "etcd_server_proposals_failed_total|etcd_server_leader_changes_seen_total"'
watch -n 1 'curl -s http://localhost:2379/metrics | grep etcd_disk_wal_fsync_duration_seconds'
```

**Ceiling достигнут, когда:**
- растёт `etcd_server_proposals_failed_total` (норма — 0);
- растёт `etcd_server_leader_changes_seen_total` (алерт в monitoring: > 3 за 15 мин);
- `etcd_disk_wal_fsync_duration_seconds` p99 выходит за 10 мс (норма p99 < 10 мс; алерт p99 > 100 мс);
- `etcd_disk_backend_commit_duration_seconds` p99 выходит за 25 мс.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `check perf` FAIL на `s` | HDD, высокий iowait, RTT между участниками > 100 мс | Перейти на NVMe; проверить `iostat -x 1`; измерить RTT |
| `prefix "/etcdctl-check-perf/" has keys` | Остались ключи от предыдущего теста | `etcdctl del --prefix /etcdctl-check-perf/` |
| PASS на `xl`, но FAIL на `l` | Разные rate limit'ы; `l` и `xl` крайне чувствительны к latency (известное поведение, etcd#13455) | Сравнивайте результаты одной модели нагрузки; искать латентность (диск/сеть) |
| Write latency растёт под нагрузкой | WAL на общем диске; CPU throttling | Выделить отдельный диск; проверить `mpstat -P ALL 1` |
| Leader flapping при нагрузке | `heartbeat-interval` слишком мал для RTT | `heartbeat-interval` ≈ 1.5×RTT; `election-timeout` ≥ 10×RTT |
| OOM при large range scan | Клиент буферизирует весь Range в памяти | RangeStream (etcd 3.7+) или `--limit` |

---

## Best Practices

- **Тестируйте при первом развёртывании** в новой среде и после каждого изменения: обновления, смены диска, изменения конфигурации.
- **Baseline:** запишите результаты `check perf` и `benchmark` в changelog. Отклонение > 20% — алерт.
- **Не тестируйте на production** без окна обслуживания: `check perf` и `benchmark` создают реальную write-нагрузку.
- **Учитывайте сеть:** при geo-распределённых кластерах измеряйте end-to-end latency (RTT между континентами до 400 мс — etcd не подходит для такой топологии без арбитра).
- **Убирайте за собой:** `--auto-compact --auto-defrag` после `check perf`; удаляйте ключи после `benchmark put`.

---

## Edge Cases

- **Thermal throttling NVMe:** при длительной нагрузке (> 10 минут) SSD может throttling. Измеряйте в течение 30+ минут.
- **Write amplification на SSD:** фрагментация CoW увеличивает write amplification и износ. Defrag делайте периодически, по мере фрагментации (а не по календарю).
- **Concurrent defrag + writes:** defrag блокирует узел; при concurrent write-нагрузке latency заметно растёт. Планируйте defrag в окнах низкой нагрузки.
- **Large keys (> 1.5 MB):** по умолчанию etcd отклоняет такие запросы (`--max-request-bytes`). При увеличении лимита ожидайте существенно более высокую latency.
- **RangeStream (etcd 3.7+):** большие Range-ответы отдаются чанками — пиковая память сервера и клиента предсказуема. В K8s v1.37 включается feature gate `EtcdRangeStream` (beta, по умолчанию вкл.).
- **`check perf` не измеряет reads:** тест пишет только ключи; для read-производительности используйте `benchmark range`.

---

## См. также

* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики производительности и пороги алертов.
* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — аппаратные требования.
* **[Лимиты и ограничения etcd](./limits_and_constraints.md)** — `--max-request-bytes`, quota.
* **[Настройка ядра](./kernel_tuning.md)** — CPU governor, параметры ядра.
* **[fio](../Linux/Diagnostics/Filesystem/fio.md)** — детали утилиты fio.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — развёртывание и бэкап кластера.
