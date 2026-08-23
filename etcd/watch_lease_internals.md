# Watch и Lease: внутреннее устройство

**Watch** и **Lease** — два ключевых механизма etcd для real-time событий и временных данных. Понимание их внутреннего устройства необходимо для отладки production-проблем.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Watch Buffer** | Очередь событий на сервере для каждого активного watcher. Ограниченный размер. |
| **Progress Notification** | Периодическое пустое уведомление о том, что watcher все еще подключен и revision актуальна. |
| **Compacted Revision** | Ревизия, которая была удалена компакцией. Попытка чтения/watch по такой ревизии возвращает ошибку. |
| **Watcher Group** | Внутренняя структура, объединяющая watcher'ов на один ключ/префикс для оптимизации. |
| **Lease GC** | Фоновый процесс (garbage collection), который удаляет метаданные истекших аренд. |
| **KeepAlive Stream** | Долгоживущий gRPC-стрим для продления аренды. |
| **Grace Period** | Дополнительное время (обычно 1–2 секунды) после истечения TTL, в течение которого lease еще не удален. |

---

## Основные концепции

### Watch: буфер и overflow

Каждый активный watcher имеет серверный буфер событий.

**Размер буфера:**
- Ограничен (конфигурируется через `--max-watchers` и `--watcher-buffer-size` в коде, но не exposed как флаг).
- При переполнении сервер закрывает стрим с ошибкой: `etcdserver: mvcc: watch store is out of space`.

**Что происходит при overflow:**
1. Сервер закрывает gRPC-стрим.
2. Клиент должен переподключиться с `--rev=<last_seen_revision>`.
3. Клиент получает все события, произошедшие после last_seen_revision.

**Best Practice:** На стороне клиента (Kubernetes API-server watch) буфер должен быть достаточно большим, чтобы выдерживать пиковые нагрузки. В K8s watch cache имеет размер ~5–10 минут событий.

### Watch progress notifications

`--progress-notify` заставляет сервер отправлять пустые `WATCH` события (без ключа/значения) каждые `--heartbeat-interval` (по умолчанию 100 мс).

**Зачем нужно:**
- Клиент может обнаружить split-brain или сетевой partition, если перестает получать heartbeat.
- Полезно для отладки: видно, что соединение живо, даже если нет событий.

```bash
# Включить progress notifications
etcdctl watch /config/ --prefix --progress-notify
# → WATCH: /config/app: value1
# → WATCH: (progress)  # пустое уведомление каждые 100 мс
```

### Compacted revision и resume

Если watcher отстает от compaction:
- **Error:** `mvcc: required revision has been compacted`.
- **Action:** Клиент должен выполнить полный `GET` всех ресурсов, а затем начать новый `WATCH` с текущей ревизии.

**Пример (Kubernetes):**
```go
// Псевдокод клиента
watcher, err := client.Watch(ctx, "/pods/", clientv3.WithRev(lastRev))
if err != nil && strings.Contains(err.Error(), "compacted") {
    // Fallback: full list + new watch
    resp, _ := client.Get(ctx, "/pods/", clientv3.WithPrefix())
    lastRev = resp.Header.Revision
    watcher, _ = client.Watch(ctx, "/pods/", clientv3.WithRev(lastRev))
}
```

### Lease: хранение и GC

**Leases хранятся НЕ в BoltDB:**
- Leases хранятся в памяти в B-дереве (`lease.ttl`).
- Метаданные (key → lease ID) хранятся в BoltDB.
- При перезапуске etcd восстанавливает leases из WAL.

**TTL vs Expire Time:**
- **TTL:** Задается при создании (`lease grant 60`).
- **Expire Time:** Текущее время + TTL.
- **Grace Period:** 1–2 секунды после expire time. За это время lease еще не считается истекшим.

**GC процесс:**
1. Фоновый goroutine проверяет leases каждые 100–200 мс.
2. Если `expire time + grace period < now`, lease помечается как expired.
3. Ключи, привязанные к этому lease, удаляются из BoltDB.
4. Lease ID возвращается в пул для повторного использования.

**Impact:**
- Expired leases не удаляются мгновенно. При высокой нагрузке на K8s (>100k leases) GC может отставать.
- Метрика `etcd_server_lease_expired_total` показывает количество истекших аренд.

### KeepAlive stream internals

**Как работает keep-alive:**
1. Клиент создает long-lived gRPC-стрим.
2. Клиент отправляет `LeaseKeepAliveRequest` с `ID`.
3. Сервер отвечает `TTL`.
4. Если TTL < порога (обычно TTL/3), сервер автоматически продлевает lease.

**При разрыве TCP:**
- Если соединение разорвано, сервер обнаруживает это по keepalive timeout (обычно 10–20 секунд).
- Lease истекает через `TTL + grace period` после последнего успешного keep-alive.
- **Важно:** Если K8s kubelet имеет высокий `--node-status-update-frequency`, но lease TTL слишком короткий (< 10s), возможны ложные истечения при временных network glitches.

---

## Практические сценарии

### Диагностика проблем с Watch

```bash
# 1. Посмотреть active watchers на сервере (через metrics)
curl -s http://localhost:2379/metrics | grep etcd_server_watcher_total
# etcd_server_watcher_total 15420

# 2. Проверить, есть ли overflow
curl -s http://localhost:2379/metrics | grep etcd_server_watch_requests_total
# etcd_server_watch_requests_total{status="success"} 15000
# etcd_server_watch_requests_total{status="compact"} 3  # ← overflow / compacted

# 3. Проверить compacted revision
etcdctl compaction <rev>
etcdctl get /key --rev=<old_rev>
# → mvcc: required revision has been compacted
```

### Диагностика проблем с Lease

```bash
# 1. Посмотреть все active leases
etcdctl lease list
# → 694d5765fc71500b

# 2. Проверить TTL конкретного lease
etcdctl lease timetolive 694d5765fc71500b
# → lease 694d5765fc71500b granted with TTL(60s), remaining(45s)

# 3. Мониторинг метрик
curl -s http://localhost:2379/metrics | grep etcd_server_lease
# etcd_server_lease_expired_total 1250
# etcd_server_lease_object_count 45000
```

### Настройка Lease TTL для K8s

```bash
# Kube-controller-manager flags
--node-status-update-frequency=10s
--node-monitor-grace-period=40s
--node-monitor-period=5s

# Lease TTL для node lease (автоматически в K8s)
# TTL = node-status-update-frequency * 3 (обычно 30s)
# Если kubelet не отправляет keepalive 3 раза подряд → node NotReady
```

**Best Practice:** Lease TTL должен быть в 2–3 раза больше, чем heartbeat интервал. Для K8s node lease: TTL ≥ 30s (при update frequency 10s).

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `watch store is out of space` | Клиент не успевает обрабатывать события | Увеличить буфер на стороне клиента; переподключиться с `--rev`; уменьшить `--auto-compaction-retention` |
| `required revision has been compacted` | Watcher отстал от compaction | Выполнить полный GET; начать новый WATCH с текущей revision |
| Lease истекает мгновенно | Нет keep-alive; разрыв соединения; TTL слишком короткий | Проверить сеть между kubelet и API-server; увеличить TTL |
| `etcdserver: lease not found` | Попытка продлить несуществующий lease | Проверить `etcdctl lease list`; возможно lease уже истек |
| Высокий `etcd_server_lease_expired_total` | Проблемы с keep-alive (сеть, API-server перегружен) | Проверить `etcd_helper_cache_hit_count` на API-server; увеличить watch-cache-sizes |

---

## Best Practices

- **Watch + Prefix:** Используйте `--prefix` вместо множества отдельных watch на один ключ. Это снижает нагрузку на сервер (watcher groups).
- **Progress Notify:** Включайте `--progress-notify` для долгоживущих watcher'ов, чтобы детектировать partition.
- **Lease TTL ≥ 3× heartbeat:** Для K8s lease TTL должен превышать интервал обновления в 3 раза.
- **Не используйте lease для постоянных данных:** Lease — для временных ключей. Для постоянных данных используйте обычные put без lease.
- **Watch buffer на клиенте:** В K8s watch cache в kube-apiserver должен быть > 5 минут событий.

---

## Edge Cases

- **Compaction во время watch:** Если компакция происходит во время активного watch, сервер отправляет `COMPACT` событие, после которого watcher должен переподключиться.
- **Multiple watchers на один key:** Сервер группирует watcher'ов в одну группу. При изменении ключа событие отправляется всем членам группы один раз (fan-out).
- **Lease reuse:** После истечения lease ID возвращается в пул. Если новый lease получит тот же ID (маловероятно, но возможно), старые ключи уже удалены.
- **Watch from revision 0:** Поддерживается. Клиент получит все события, начиная с самой первой ревизии (если не compacted).

---

## См. также

* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — пути записи и чтения.
* **[MVCC, версионирование и компакция](./mvcc_versioning_and_compaction.md)** — revision и compaction.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — команды для watch и lease.
