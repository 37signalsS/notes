# Watch и Lease: внутреннее устройство

**Актуально для:** etcd 3.5.x / 3.6.x / 3.7.x

**Watch** и **Lease** — два ключевых механизма etcd для real-time событий и временных данных. Понимание их внутреннего устройства необходимо для отладки production-проблем. Константы и механизмы верифицированы по исходному коду etcd (`server/mvcc/watchable_store.go`, `server/mvcc/watcher_group.go`, `server/lease/lessor.go`, `client/v3/lease.go`) для версий 3.5.34, 3.6.15 и 3.7.2 — они идентичны во всех трёх ветках.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Watch Buffer** | Буферизованный канал `WatchResponse` длиной `chanBufLen = 128` на каждый watcher (константа в `server/mvcc/watchable_store.go`). |
| **Victim** | Watcher, чей канал заполнен (клиент не успевает читать). Переводится в `victim`-состояние и периодически ретраится, а не закрывается. |
| **Progress Notification** | Периодическое пустое уведомление о том, что стрим жив и revision актуальна. Интервал — `--experimental-watch-progress-notify-interval` (дефолт 10m). |
| **Compacted Revision** | Ревизия, удалённая компакцией. Watcher, отставший от неё, получает ответ с полем `CompactRevision` и отменяется сервером. |
| **Watcher Group** | Структура (`watcherGroup`), объединяющая watcher'ов на один ключ/префикс для fan-out и оптимизации синхронизации. |
| **Lease GC** | Фоновый отзыв истекших аренд на лидере, ограниченный по скорости (`leaseRevokeRate`, дефолт 1000 аренд/с). |
| **KeepAlive Stream** | gRPC bidirectional stream (`/etcdserverpb.Lease/LeaseKeepAlive`) для продления аренды. |

---

## Основные концепции

### Watch: буфер и slow watcher

Каждый watcher получает буферизованный канал `make(chan WatchResponse, chanBufLen)`, где `chanBufLen = 128`. Это единственный «буфер» на watcher — отдельного флага `--watcher-buffer-size` или `--max-watchers` в etcd **нет**.

**Что происходит, когда клиент не успевает читать (канал заполнен):**

1. `w.send()` не может записать в канал → watcher помечается `w.victim = true` и перемещается в пакет `victims` (массив `watcherBatch`), исключается из synced-группы.
2. Инкрементируется gauge `etcd_debugging_mvcc_slow_watcher_total` («Total number of unsynced slow watchers»).
3. Отдельный горутина `syncVictimsLoop()` каждые 10 мс пытается повторно отправить подготовленные ответы victim-ам. Если канал всё ещё заполнен — watcher остаётся victim и ретраится дальше.
4. Watcher'ы из unsynced-группы догоняют события, перечитывая их из BoltDB (пакетами по `maxWatchersPerSync = 512`).

**Стрим при этом НЕ закрывается.** Ошибки `etcdserver: mvcc: watch store is out of space` в etcd **не существует** — это распространённое заблуждение. Медленный watcher не теряется, а «замораживается» и догоняет, когда клиент освободит канал.

**Resync:** `watchResyncPeriod = 100 * time.Millisecond` — период, с которым synced-watchers получают подтверждение текущей revision (не путать с progress-notify).

**Best Practice:** на стороне клиента (Kubernetes API-server watch) важно, чтобы обработчик событий успевал читать канал; при отставании растёт `etcd_debugging_mvcc_slow_watcher_total` — это первый сигнал перегрузки потребителя.

### Watch progress notifications

`--progress-notify` заставляет сервер периодически присылать пустой `WatchResponse` (без событий, только `Revision`) — подтверждение, что стрим жив и клиент на текущей ревизии. В `etcdctl` это выглядит как `progress notify: <revision>`.

**Интервал** задаётся серверным флагом `--experimental-watch-progress-notify-interval`, дефолт **10 минут** (не `--heartbeat-interval`, который относится к Raft и равен 100 мс). В конфигурационном файле значение указывается целым числом наносекунд (например, `600000000000` для 10m) из-за ограничения Go stdlib при парсинге длительностей.

**Зачем нужно:**
- Клиент обнаруживает сетевой partition / split-brain, если перестаёт получать progress-уведомления в ожидаемом интервале.
- Полезно для отладки: видно, что соединение живо, даже если событий нет.

```bash
# Включить progress notifications (etcdctl)
etcdctl watch /config/ --prefix --progress-notify
# → /config/app: value1
# → progress notify: 12345   # пустое уведомление каждые 10m (по умолчанию)
```

### Compacted revision и resume

Если watcher отстал от компакции (`w.minRev < compactionRev`), сервер в `watcherGroup.chooseAll()` отправляет ему специальный ответ:

```go
case w.ch <- WatchResponse{WatchID: w.id, CompactRevision: compactRev}:
    w.compacted = true
    wg.delete(w)   // watcher удаляется из группы
```

То есть сервер **отправляет `WatchResponse` с установленным полем `CompactRevision`** (а не отдельное «COMPACT-событие») и отменяет watcher. Клиент должен:

1. Выполнить полный `GET` всех ресурсов (list).
2. Начать новый `WATCH` с текущей ревизии из `resp.Header.Revision`.

**Пример (Kubernetes, псевдокод):**
```go
watcher, err := client.Watch(ctx, "/pods/", clientv3.WithRev(lastRev))
// при получении ответа с CompactRevision != 0:
resp, _ := client.Get(ctx, "/pods/", clientv3.WithPrefix())
lastRev = resp.Header.Revision
watcher, _ = client.Watch(ctx, "/pods/", clientv3.WithRev(lastRev))
```

Ошибка `mvcc: required revision has been compacted` возникает, когда клиент пытается начать watch/GET **с** уже скомпактированной ревизии (а не когда отстаёт во время watch).

### Lease: хранение и GC

**Leases хранятся в памяти и персистятся в BoltDB:**
- Leases хранятся в памяти в `leaseMap`.
- Персистятся только **ID lease и время истечения** (lease bucket в BoltDB); привязки key → lease ID **не** персистятся отдельно — при восстановлении они восстанавливаются сканированием всех ключей в kv.
- При перезапуске etcd восстанавливает leases из backend (BoltDB).

**TTL vs Expire Time:**
- **TTL:** задаётся при создании (`lease grant 60`).
- **Expire Time:** текущее время + TTL, выставляется на **primary lessor** (Raft-лидере).
- **Минимальный TTL:** `MinLeaseTTL = ceil(1.5 × election-timeout)` (формула в `server/etcdserver/server.go`: `minTTL := time.Duration((3*cfg.ElectionTicks)/2) * heartbeat`). При дефолтах (`heartbeat-interval=100ms`, `election-ticks=10`, т.е. election-timeout=1s) это **2 секунды**; запрошенный TTL ниже минимума продлевается до минимума.
- **Максимальный TTL:** `MaxLeaseTTL = 9 000 000 000` секунд (~285 лет); превышение возвращает `etcdserver: too large lease TTL` (`ErrLeaseTTLTooLarge`).

**GC процесс (детали — в [Garbage Collection](./garbage_collection.md)):**
1. Фоновый цикл `runLoop()` lessor'а проверяет leases каждые **500 мс** (только на лиде; `isPrimary()`).
2. Если `expire time ≤ now`, lease отправляется на отзыв. Скорость отзыва ограничена `leaseRevokeRate` (дефолт **1000 аренд/с**, настраивается через `--lease-revoke-rate`).
3. Отзыв реплицируется через Raft: на каждом члене удаляются привязанные ключи и метаданные аренды из BoltDB.
4. Если приёмник `expiredC` занят (канал буферизован на 16), отзыв ретраится через `expiredLeaseRetryInterval` (дефолт **3 секунды**).
5. Lease ID не переиспользуется — ID выбирается сервером при grant.

**Impact:**
- Expired leases не удаляются мгновенно: отзыв ограничен ~1000 аренд/с, при массовом истечении GC отстаёт (канал `expiredC` размером 16 быстро заполняется).
- Метрика `etcd_debugging_server_lease_expired_total` (counter) показывает количество истекших аренд.

**Checkpointing (сохранение remainingTTL):** оставшийся TTL сохраняется в consensus-log каждые **5 минут** (`defaultLeaseCheckpointInterval`), скоростью `leaseCheckpointRate = 1000/с`, пакетами до `maxLeaseCheckpointBatchSize = 1000`. В etcd **3.6+** persist remainingTTL в backend включён всегда (`shouldPersistCheckpoints()` возвращает true при cluster version ≥ 3.6); в 3.5 требуется `--experimental-enable-lease-checkpoint=true`. Это позволяет при переходе лидерства не «сбрасывать» TTL к полному значению.

**Promote:** при повышении нового лидера (promote lessor) он продлевает TTL **всех** leases, добавляя к текущему remainingTTL предыдущий полный TTL — чтобы компенсировать время, пока lease не обслуживался на непервичном lessor'е.

### KeepAlive stream internals

**Как работает keep-alive (clientv3, `client/v3/lease.go`):**
1. Клиент создаёт long-lived gRPC-стрим (`LeaseKeepAlive`).
2. Клиент отправляет `LeaseKeepAliveRequest` с `ID`. **Интервал отправки — TTL/3**: после каждого ответа `nextKeepAlive = now + (TTL × 1s) / 3.0`. То есть продление инициирует **клиент**, а не сервер.
3. Сервер отвечает `TTL` (remaining TTL в секундах; для истёкшей аренды — `-1`).
4. **Deadline** keepalive-канала = полный TTL (`ka.deadline = now + TTL`). Отдельный `deadlineLoop()` закрывает («reap») каналы, не получившие ответа в течение TTL.
5. До получения первого ответа (когда реальный TTL ещё неизвестен) дедлайн первого keep-alive равен `firstKeepAliveTimeout = DialTimeout + 1 s`; при нулевом `DialTimeout` клиент подставляет `defaultTTL = 5 * time.Second`.

**API clientv3:**
- `KeepAlive(ctx, id)` — возвращает канал ответов; канал закрывается при истечении/отзыве аренды. При остановке авто-продления возвращает `ErrKeepAliveHalted` (автопродление сломано, но `KeepAliveOnce` продолжает работать).
- `KeepAliveOnce(ctx, id)` — однократное продление.

**При разрыве TCP:**
- Lease истекает через TTL после последнего успешного keep-alive (проверка — каждые 500 мс на лидере). Отдельного «keepalive timeout 10–20 секунд» на сервере нет — срок определяется TTL аренды.
- **Важно:** если kubelet имеет высокий `--node-status-update-frequency`, но lease TTL слишком короткий, возможны ложные истечения при временных network glitches (см. раздел про K8s node lease).

---

## Практические сценарии

### Диагностика проблем с Watch

```bash
# 1. Число активных watchers и watch-стримов
curl -s http://localhost:2379/metrics | grep -E "etcd_debugging_mvcc_(watcher|watch_stream)_total"
# etcd_debugging_mvcc_watcher_total 15420      # Total number of watchers
# etcd_debugging_mvcc_watch_stream_total 312   # Total number of watch streams

# 2. Есть ли медленные (отставшие) watchers — ключевой сигнал перегрузки потребителя
curl -s http://localhost:2379/metrics | grep etcd_debugging_mvcc_slow_watcher_total
# etcd_debugging_mvcc_slow_watcher_total 0     # >0 — клиенты не успевают читать

# 3. Число входящих watch-запросов (новых и переустановленных)
curl -s http://localhost:2379/metrics | grep etcd_debugging_store_watch_requests_total
# etcd_debugging_store_watch_requests_total 15000

# 4. Отложенные события в буферах (сколько событий ждут чтения клиентами)
curl -s http://localhost:2379/metrics | grep etcd_debugging_mvcc_pending_events_total

# 5. Проверить compacted revision
etcdctl compact <rev>
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
curl -s http://localhost:2379/metrics | grep -E "etcd_debugging_(server_lease_expired|lease_(granted|renewed|revoked))_total"
# etcd_debugging_server_lease_expired_total 1250
# etcd_debugging_lease_granted_total 5000
# etcd_debugging_lease_renewed_total 48000
# etcd_debugging_lease_revoked_total 1200

# 4. Распределение TTL (гистограмма)
curl -s http://localhost:2379/metrics | grep etcd_debugging_lease_ttl_total

# Число активных leases (etcd не экспортирует gauge с их количеством)
etcdctl lease list | wc -l
# → 45000
```

### Настройка Lease TTL для K8s node lease

kubelet использует объекты `Lease` в namespace `kube-node-lease` для heartbeat'а (вместо частой записи `.status` в API). Механизм (K8s 1.34, верифицировано по исходникам `pkg/kubelet/kubelet.go`, `pkg/kubelet/apis/config/v1beta1/defaults.go`, `pkg/controller/nodelifecycle/config/v1alpha1/defaults.go`):

```bash
# kubelet defaults:
#   NodeLeaseDurationSeconds = 40        # TTL node lease
#   NodeStatusUpdateFrequency = 10s      # частота обновления .status
#   nodeLeaseRenewIntervalFraction = 0.25  # → продление каждые 40s × 0.25 = 10s

# kube-controller-manager (NodeLifecycleController) defaults:
#   NodeMonitorGracePeriod = 50s   # (> HTTP2_PING_TIMEOUT 30s + HTTP2_READ_IDLE_TIMEOUT 15s)
#   NodeStartupGracePeriod = 60s
#   PodEvictionTimeout = 5m
```

kubelet обновляет `spec.renewTime` в объекте Lease каждые 10 секунд (25% от TTL). Node controller помечает node `Unknown`, если lease не продлевался в течение `NodeMonitorGracePeriod` (50s), и эвиктирует поды через `PodEvictionTimeout` (5m).

**Best Practice:** Lease TTL должен быть в 2–3 раза больше интервала продления. Для K8s node lease: TTL 40s при продлении каждые 10s — запас ~4 промежутка до истечения.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Растёт `etcd_debugging_mvcc_slow_watcher_total` | Клиент не успевает читать события (канал watcher'а заполнен) | Ускорить обработчик событий на клиенте; уменьшить объём watch (фильтры); переподключиться с `--rev=<last_seen_revision>` |
| `required revision has been compacted` | Watcher отстал от компакции (или старт с скомпактированной rev) | Выполнить полный GET; начать новый WATCH с текущей revision |
| `watch was canceled (...)` | Watcher отменён сервером (отстал от компакции) | Переподключиться с последней известной ревизии (`--rev=<revision>`) |
| Lease истекает раньше ожидаемого | Нет keep-alive; разрыв соединения; TTL слишком короткий | Проверить сеть между kubelet и API-server; увеличить TTL; убедиться, что TTL ≥ `MinLeaseTTL` (2s при дефолтах) |
| `etcdserver: lease not found` | Попытка продлить несуществующую/истёкшую аренду | Проверить `etcdctl lease list`; возможно lease уже истек |
| `etcdserver: too large lease TTL` | TTL > `MaxLeaseTTL` (9 000 000 000 с) | Уменьшить TTL |
| Высокий `etcd_debugging_server_lease_expired_total` | Проблемы с keep-alive (сеть, API-server перегружен) | Проверить `etcd_lease_object_counts` на API-server; нагрузку на Watch; число leases через `etcdctl lease list` |

---

## Best Practices

- **Watch + Prefix:** Используйте `--prefix` вместо множества отдельных watch на один ключ. Watcher'ы на один ключ/префикс группируются в `watcherGroup` (fan-out одним событием), что снижает нагрузку на сервер.
- **Progress Notify:** Включайте `--progress-notify` для долгоживущих watcher'ов, чтобы детектировать partition (интервал — `--experimental-watch-progress-notify-interval`, дефолт 10m).
- **Lease TTL ≥ 2–3× heartbeat:** Для K8s node lease TTL (40s) превышает интервал продления (10s) в 4 раза.
- **Не используйте lease для постоянных данных:** Lease — для временных ключей. Для постоянных данных используйте обычные put без lease.
- **Мониторьте slow watchers:** `etcd_debugging_mvcc_slow_watcher_total > 0` — ранний сигнал того, что потребитель событий (например, kube-apiserver) отстаёт.
- **Watch требует лидера:** watch-стрим работает только при наличии лидера (клиент может использовать `clientv3.WithRequireLeader`).

---

## Edge Cases

- **Compaction во время watch:** если компакция происходит во время активного watch и watcher отстал (`minRev < compactionRev`), сервер отправляет `WatchResponse` с полем `CompactRevision` и отменяет watcher; клиент должен переподключиться с текущей ревизии.
- **Multiple watchers на один key:** сервер группирует watcher'ов в `watcherGroup`. При изменении ключа событие отправляется всем членам группы (fan-out).
- **Lease ID:** ID выбирается сервером, если клиент передал 0 (`NoLease = LeaseID(0)`); истекшие lease ID не возвращаются в пул и не переиспользуются.
- **Watch from revision 0:** `startRev == 0` трактуется как **текущая** ревизия (`synced := startRev > currentRev || startRev == 0`), а не «все события с первой ревизии». Чтобы читать с конкретной ревизии — укажите `--rev=<N>` явно.
- **Non-primary lessor:** renew/grant на не-лидере возвращает `ErrNotPrimary` (clientv3 переадресует на лидера).
- **Физические часы:** TTL — физический интервал; сервер и клиент меряют время своими часами. Сервер может отозвать lease, пока клиент считает его своим (см. [«Notes on the usage of lock and lease»](https://etcd.io/docs/v3.5/learning/why/) — mutual exclusion реализуется через валидацию revision, а не через lease).

---

## См. также

* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — пути записи и чтения.
* **[MVCC, версионирование и компакция](./mvcc_versioning_and_compaction.md)** — revision и compaction.
* **[Garbage Collection](./garbage_collection.md)** — компакция и удаление старых ревизий.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — команды для watch и lease.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики и алерты.
