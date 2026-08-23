# Систематический troubleshooting etcd

Данный playbook описывает пошаговые алгоритмы диагностики типичных проблем в production. Используйте его как чеклист при получении алертов или жалоб пользователей.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Raft Index Gap** | Разница между `RAFT INDEX` (записан) и `RAFT APPLIED INDEX` (применен к MVCC). |
| **Stale Read** | Чтение устаревших данных (serializable read без ReadIndex). |
| **Split-Brain** | Сетевое разделение, при котором часть узлов теряет кворум. |
| **Gray Failure** | Узел частично работает (принимает запросы, но не отвечает на heartbeats). |
| **Data Corruption** | Повреждение данных на диске (WAL или BoltDB). |
| **NOSPACE** | Аларм, возникающий при превышении `quota-backend-bytes`. |

---

## Playbook: "etcd медленный"

### Шаг 1: Проверить диск

```bash
# Задержка fdatasync (p99)
curl -s http://localhost:2379/metrics | grep etcd_disk_wal_fsync_duration_seconds

# Ожидание I/O
iostat -x 1 5
# → %util > 90% — проблема с диском
# → await > 10 ms — диск перегружен
```

**Решение:**
- Если `await` > 10 ms — проблема с диском. Перейти на NVMe или разделить WAL/данные.
- Если `%util` = 100% — диск насыщен. Добавьте более быстрый диск.

### Шаг 2: Проверить CPU

```bash
# Нагрузка на ядра
mpstat -P ALL 1 5

# Узкие места
top -H -p $(pgrep etcd)
```

**Решение:**
- Если `%iowait` высокий — проблема с диском (вернитесь к шагу 1).
- Если `%user`/`%system` > 80% — CPU throttling. Выделите отдельные ядра (`isolcpus`).

### Шаг 3: Проверить сеть

```bash
# RTT между узлами
curl -s http://localhost:2379/metrics | grep etcd_network_peer_round_trip_time_seconds
# → p99 > 50 ms — проблема с сетью

# Потеря пакетов
ping -c 100 <peer-ip>
# → > 1% packet loss — проблема с сетью
```

**Решение:**
- Увеличить `--heartbeat-interval` и `--election-timeout`.
- Проверить firewall, MTU, switch buffers.

### Шаг 4: Проверить Watch Cache на API-сервере

```bash
# На узле control plane
kubectl get --raw /metrics | grep etcd_helper_cache
# → etcd_helper_cache_hit_count низкий, etcd_helper_cache_miss_count высокий
```

**Решение:**
- Увеличить `--watch-cache-sizes` в kube-apiserver.
- Проверить количество Events (> 10 000/мин — переполнение кэша).

---

## Playbook: "etcd теряет лидера"

### Шаг 1: Проверить лидера и кворум

```bash
etcdctl endpoint health --cluster -w table
# → Сколько узлов healthy?
# → Количество healthy >= кворум?
```

**Если нет кворума:**
- Проверить доступность портов (2379, 2380).
- Проверить TLS-сертификаты (`openssl s_client -connect host:2380`).
- Проверить firewall (`ss -tlnp | grep 2379`).

### Шаг 2: Проверить метрики лидерства

```bash
# Частота смен лидера
curl -s http://localhost:2379/metrics | grep etcd_server_leader_changes_seen_total

# Ошибки heartbeat
curl -s http://localhost:2379/metrics | grep etcd_server_heartbeat_send_failures_total
```

**Если leader changes > 3 за 15 минут:**
- Проверить `etcd_disk_wal_fsync_duration_seconds` (disk).
- Проверить `etcd_network_peer_round_trip_time_seconds` (network).

### Шаг 3: Проверить Raft Index Gap

```bash
etcdctl endpoint status --cluster -w table
# → RAFT APPLIED INDEX vs RAFT INDEX
# → Разница > 10 000 — follower отстает
```

**Решение:**
- Проверить iowait на follower'е.
- Проверить сетевые задержки.
- Увеличить `--snapshot-count` на лидере.

---

## Playbook: "etcd не стартует"

### Шаг 1: Проверить логи systemd

```bash
journalctl -u etcd -n 100 --no-pager
```

### Шаг 2: Проверить WAL

```bash
# Целостность WAL
etcdutl wal verify /var/lib/etcd/wal/

# Если поврежден — восстановить из снапшота
etcdutl snapshot restore /backup/last-good.db \
  --name node1 \
  --initial-cluster node1=... \
  --data-dir /var/lib/etcd-restored
```

### Шаг 3: Проверить data-dir

```bash
# Права доступа
ls -la /var/lib/etcd
# → Должен быть доступен пользователю etcd (chown 1001:1001)

# Свободное место
df -h /var/lib/etcd
# → Должно быть > 10% свободно
```

### Шаг 4: Проверить TLS

```bash
# Проверить срок действия сертификатов
openssl x509 -in /etc/etcd/pki/server.crt -noout -dates

# Проверить соответствие CN/SAN
openssl x509 -in /etc/etcd/pki/server.crt -noout -subject -ext subjectAltName
```

---

## Playbook: "etcd нехватка места (NOSPACE)"

### Шаг 1: Проверить алармы

```bash
etcdctl alarm list
# → member xxxxx: NOSPACE
```

### Шаг 2: Освободить место в ОС

```bash
# Удалить старые снапшоты
find /backup -name "*.db" -mtime +7 -delete

# Проверить место
df -h /var/lib/etcd
```

### Шаг 3: Компакция

```bash
# Текущая ревизия
rev=$(etcdctl endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9]*' | head -n 1)

# Компакция
etcdctl compaction $rev
```

### Шаг 4: Дефрагментация (поочередно)

```bash
etcdctl defrag --cluster
```

### Шаг 5: Сброс аларма

```bash
etcdctl alarm disarm
```

---

## Playbook: "Kubernetes API-server медленный / таймауты"

### Шаг 1: Проверить здоровье etcd

```bash
kubectl get pods -n kube-system -l component=etcd
# → Все pods Running?

# Проверить endpoint health
etcdctl endpoint health --cluster
```

### Шаг 2: Проверить Watch Cache

```bash
# На API-сервере
kubectl get --raw /metrics | grep etcd_helper_cache
# → hit rate < 80% — проблема
```

**Решение:**
- Увеличить `--watch-cache-sizes`.
- Убедиться, что `--watch-cache-enabled=true`.

### Шаг 3: Проверить Request Size

```bash
# В логах API-сервера
kubectl logs -n kube-system kube-apiserver-... | grep "request is too large"
```

**Решение:**
- Увеличить `--max-request-bytes` в etcd и kube-apiserver.
- Разбить большие ConfigMap/Secret.

### Шаг 4: Проверить etcd compaction

```bash
# В логах kube-apiserver
kubectl logs -n kube-system kube-apiserver-... | grep "compacted"
```

**Решение:**
- Увеличить `--auto-compaction-retention` в kube-apiserver (например, до 10m).
- Проверить, что etcd не перегружен.

---

## Чеклист по метрикам

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| `etcd_server_has_leader` | < 1 | Потеря лидера → проверить кворум, сеть, диск |
| `etcd_server_leader_changes_seen_total` | > 3 за 15м | Flapping → disk/network/CPU |
| `etcd_disk_wal_fsync_duration_seconds` | p99 > 100 мс | Disk bottleneck |
| `etcd_mvcc_db_total_size_in_bytes` | > 8 ГБ | Defrag + compact или масштабирование |
| `etcd_server_proposals_failed_total` | Рост | Write path overloaded |
| `etcd_server_lease_expired_total` | Всплеск | Lease GC не успевает или keep-alive сбоит |
| `etcd_network_peer_round_trip_time_seconds` | p99 > 100 мс | Network partition или high latency |

---

## См. также

* **[Мониторинг etcd](./etcd_monitoring.md)** — алерты и дашборды.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — восстановление после потери кворума.
* **[Аварийное восстановление](./emergency_recovery.md)** — `--force-new-cluster` и DR.
* **[Лимиты и ограничения](./limits_and_constraints.md)** — size limits и capacity planning.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — диагностические команды.
