# Garbage Collection и внутренний GC etcd

**Актуально для:** etcd 3.5 / 3.6 / 3.7

**Garbage Collection (GC)** в etcd — это набор фоновых механизмов, удаляющих устаревшие данные (старые ревизии, истекшие leases, удалённые пользователем ключи) для предотвращения бесконечного роста базы данных. Revision GC и Key GC выполняются локально на каждом члене кластера; Lease GC инициируется лидером (primary lessor), а удаление ключей при отзыве lease реплицируется через Raft. Понимание GC критично для диагностики проблем с памятью и диском.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Revision GC** | Удаление из истории MVCC ревизий, предшествующих compacted revision. |
| **Compaction** | Логическое удаление старых ревизий: чистка `treeIndex` в памяти и удаление старых записей из BoltDB. Освободившиеся страницы переходят в Freelist; размер файла БД не уменьшается. |
| **Lease GC** | Истечение и отзыв аренд: удаление ключей, привязанных к expired lease, и метаданных самой аренды. |
| **Key GC** | Удаление ключей, удалённых пользователем, но всё ещё присутствующих в истории MVCC в виде tombstone-ревизий. |
| **TTL Expiry** | Истечение времени жизни аренды, после которого привязанные ключи удаляются автоматически. |
| **Fragmentation** | Накопление «мёртвых» страниц в BoltDB после compaction и GC: место доступно etcd для новых записей, но не возвращено файловой системе. |
| **Defrag** | Перезапись файла БД, возвращающая свободные страницы файловой системе. |

## Основные концепции

### Revision GC (компакция)

Compaction — основной механизм GC для ревизий:

1. **Запуск:** compaction выполняется локально на члене, получившем запрос: вручную через `etcdctl compact <rev>` или автоматически (`--auto-compaction-mode` / `--auto-compaction-retention`). Compaction не является операцией Raft и не реплицируется; auto-compaction выполняется каждым членом независимо. В Kubernetes компакцию выполняет kube-apiserver — по одному compactor'у на каждый endpoint etcd (флаг `--etcd-compaction-interval`, по умолчанию 5m).
2. **Mark:** все ревизии `< rev` удаляются из `treeIndex` (индекс в памяти), а старые записи удаляются из BoltDB пакетами (лимит `--compaction-batch-limit`, 1000 ревизий за пакет; в 3.5 флаг назывался `--experimental-compaction-batch-limit`, в 3.6 переименован в `--compaction-batch-limit` — старое имя deprecated, в 3.7 удалено; с 3.6 также есть `--compaction-sleep-interval` — пауза между пакетами для снижения нагрузки на диск).
3. **GC:** страницы BoltDB, освободившиеся после удаления старых ревизий, переходят в Freelist и переиспользуются для новых записей.
4. **Impact:** чтение и watch по старым ревизиям возвращают ошибку `mvcc: required revision has been compacted`.

**Важно:** compaction не уменьшает размер файла БД — место возвращается ОС только defrag'ом. Кроме того, сама compaction фрагментирует backend (оставляет разрывы в B+tree), поэтому после неё может потребоваться defrag.

**Режимы auto-compaction:**

- **periodic (по умолчанию):** retention задаёт окно истории; запись не компактируется, пока не пройдёт ~указанная длительность с момента создания (защита медленных watchers). При retention > 1h compaction выполняется каждый час, при retention ≤ 1h — с интервалом retention. В periodic-режиме число без единицы измерения означает часы: `--auto-compaction-retention=1` — это 1 час, а `--auto-compaction-retention=5m` — 5 минут.
- **revision:** etcd проверяет каждые 5 минут и компактирует до `latest revision − retention`.

```bash
# Ручная компакция до текущей ревизии
rev=$(etcdctl endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9].*')
etcdctl compact $rev
# → compacted revision 1516

# Дождаться физического удаления старых ревизий из локальной БД (флаг --physical доступен во всех поддерживаемых версиях 3.5/3.6/3.7)
etcdctl compact $rev --physical=true
```

### Lease GC

Lease GC работает независимо от revision compaction. Ключевые факты из реализации (`server/lease/lessor.go`):

**Primary lessor = Raft-лидер.** Истечение и продление leases обрабатывает только лидер (`isPrimary()`). На follower'ах expiry выставляется в «вечно» и обновляется при повышении (`Promote()` продлевает все leases). Поэтому при смене лидера истечение leases задерживается на время выборов (до election timeout).

**Цикл проверки — 500 мс.** Фоновый цикл lessor'а тикает каждые 500 мс: находит leases с `expiry ≤ now` и отправляет их в канал отзыва (`expiredC`, буфер 16). Если канал занят — проверка повторится на следующем тике.

**Grace period отсутствует.** В etcd нет «периода ожидания» после истечения TTL: lease считается истекшим, как только время expiry прошло и наступил следующий тик проверки (задержка 0–500 мс). Константа `defaultExpiredleaseRetryInterval = 3s` — это интервал перепроверки завершения отзыва, а не защита lease. В etcdserver интервал перепроверки выставляется в `ReqTimeout()` = 5s + 2 × election-timeout (7s при дефолтах).

**Rate limit на отзыв:** отзыв ограничен ~1000 leases/сек (`defaultLeaseRevokeRate`, 500 за тик). Отзывы выполняются параллельно (до `maxPendingRevokes = 16` одновременно), перед каждым отзывом lessor проверяет, что член всё ещё лидер (`ensureLeadership()` — защита от stale leader). При массовом истечении (например, после восстановления связи) отзыв отстаёт — это основная причина «GC не справляется».

**Жизненный цикл lease:**
1. Создание: `lease grant 60` → TTL = 60s, expiry = now + 60s (выставляется на лидере).
2. Keep-alive: клиент шлёт `LeaseKeepAliveRequest` по long-lived gRPC-стриму, обычно с интервалом ~TTL/3.
3. Expiry: при отсутствии keep-alive lease истекает в течение TTL + до 500 мс (тик проверки). Минимальный TTL: etcd не выдаёт аренду с TTL ниже `ceil(1.5 × election-timeout)` (при дефолтах election-timeout=1s → 2с); запрошенный меньший TTL продлевается до минимума (`minLeaseTTL` в lessor).
4. Revoke: лидер предлагает отзыв через Raft (`InternalRaftRequest{LeaseRevoke}`); после коммита отзыв применяется на всех членах — привязанные ключи удаляются как обычные deletes (создают tombstone-ревизии), а метаданные аренды удаляются из BoltDB в той же backend-транзакции.
5. Lease ID не переиспользуется: при grant ID выбирается сервером (если клиент передал 0).

**Хранение и восстановление:** leases хранятся в памяти (`leaseMap`) и персистятся в BoltDB (lease bucket: ID, TTL, remainingTTL). При перезапуске lessor восстанавливает leases из backend (не из WAL); привязки ключей восстанавливаются сканированием ключей.

**Lease checkpoint (сохранение remaining TTL):** lessor периодически (каждые 5 минут, константа `defaultLeaseCheckpointInterval`, флагом не настраивается) записывает remaining TTL в consensus log, чтобы после перезапуска или смены лидера leases не потеряли оставшееся время. **Выключен по умолчанию во всех версиях** (Alpha feature gate). Включение: 3.4/3.5 — `--experimental-enable-lease-checkpoint=true` (default false); 3.6 — `--feature-gates=LeaseCheckpoint=true` (старый experimental-флаг deprecated, но работает через внутренний маппинг); 3.7 — только `--feature-gates=LeaseCheckpoint=true` (experimental-флаги удалены). Persist remainingTTL в локальный backend: в 3.6/3.7 выполняется автоматически, когда checkpointing включён и cluster version ≥ 3.6; feature gate `LeaseCheckpointPersist` (default false) нужен только во время rolling-апгрейда 3.5→3.6 (cluster version ещё 3.5) и на 3.5.2+ через `--experimental-enable-lease-checkpoint-persist=true`. В 3.7 `LeaseCheckpointPersist=true` без `LeaseCheckpoint=true` вызывает ошибку валидации конфига.

**Влияние на производительность:** при высокой нагрузке (>100k leases) отзыв может отставать от истечения. Метрика `etcd_debugging_server_lease_expired_total` (counter) показывает число истекших аренд; gauge с общим числом активных leases etcd не экспортирует — его получают через `etcdctl lease list`. **etcd 3.7:** запросы LeaseRevoke приоритизируются при перегрузке (стабильность при пиках истечения, #20492); feature gate `FastLeaseKeepAlive` (Beta, default true) ускоряет продление leases, пропуская ожидание applied index.

### Key GC (удаление пользовательских ключей)

Когда пользователь вызывает `etcdctl del /key`:
1. Создаётся tombstone-ревизия: ключ помечается удалённым в `treeIndex`.
2. BoltDB не перезаписывает страницы сразу — старые версии значения становятся «мёртвыми».
3. Compaction удаляет из истории все ревизии ключа, предшествующие compacted revision (включая старые tombstone).
4. Defrag возвращает освободившиеся страницы ОС.

**Важно:** пока compaction не удалила старые ревизии, история ключа доступна для чтения по старой ревизии (`etcdctl get /key --rev=<old>`). Это позволяет восстановить данные; после compaction чтение по старой ревизии невозможно.

### Defrag — физическое освобождение места

Compaction и lease GC освобождают страницы только внутри BoltDB (Freelist). Чтобы вернуть место файловой системе:

```bash
# Онлайн, по одному члену (блокирует чтение и запись на этом члене на время выполнения)
etcdctl defrag --endpoints=https://10.0.0.11:2379
# → Finished defragmenting etcd member[https://10.0.0.11:2379]

# Все члены кластера (последовательно, не параллельно)
etcdctl defrag --cluster
# → Finished defragmenting etcd member[http://10.0.0.11:2379]
# → Finished defragmenting etcd member[http://10.0.0.12:2379]

# Офлайн (etcd остановлен)
etcdutl defrag --data-dir /var/lib/etcd
```

Defrag не реплицируется через кластер — применяется только к локальному узлу; указывайте все члены в `--endpoints` или используйте `--cluster`. Выполняйте поочерёдно, чтобы не потерять кворум.

## Практические сценарии

### Диагностика: GC не справляется с нагрузкой

Предварительные условия: доступ к metrics-endpoint члена (`:2379/metrics`) и etcdctl с настроенными `--endpoints`.

```bash
# 1. Скорость истечения leases (counter)
curl -s http://localhost:2379/metrics | grep etcd_debugging_server_lease_expired_total
# → устойчивый рост > ~1000/сек — отзыв отстаёт (лимит revoke ~1000 leases/с)

# 2. Размер БД: total vs in-use
curl -s http://localhost:2379/metrics | grep etcd_mvcc_db_total_size
# etcd_mvcc_db_total_size_in_bytes{...} 3221225472       # включая свободное место
# etcd_mvcc_db_total_size_in_use_in_bytes{...} 1610612736 # реальные данные
# fragmentation = (total - in_use) / total = 0.5 (50%)

# 3. Число активных leases (gauge не экспортируется)
etcdctl lease list | wc -l
# → 45000

# 4. TTL конкретной аренды
etcdctl lease timetolive 694d5765fc71500b
# → lease 694d5765fc71500b granted with TTL(60s), remaining(45s)
```

**Решение:**
- Снизить интенсивность создания/истечения leases (увеличить TTL, убрать лишние leases).
- Проверить keep-alive на стороне клиентов (K8s kubelet, контроллеры).
- Увеличить частоту compaction — уменьшить `--auto-compaction-retention` (в periodic-режиме), а не увеличить.
- Если БД растёт, несмотря на compaction, — запланировать defrag (фрагментация > 30%).
- В etcd 3.7+ запросы LeaseRevoke приоритизируются при перегрузке — апгрейд на 3.7 снижает задержки массового отзыва.

### Настройка compaction под нагрузку

```bash
# Автоматическая компакция каждые 5 минут (периодический режим)
etcd --auto-compaction-mode=periodic --auto-compaction-retention=5m

# Компакция по числу ревизий: хранить последние 100 000
etcd --auto-compaction-mode=revision --auto-compaction-retention=100000
```

**Рекомендации (из документации etcd):** частые обновления одних и тех же ключей — короткое окно (30m–1h); редкие обновления — 24h–72h; рекомендация для общего случая — 10h (сам флаг `--auto-compaction-retention` по умолчанию равен 0 — авто-компакция отключена). Для кластеров с высокой интенсивностью изменений (массовое создание/удаление ресурсов) используйте revision-режим с retention 50 000–100 000, чтобы compaction не запускалась слишком часто на пиках.

**В Kubernetes:** kube-apiserver выполняет компакцию сам (каждые 5m по умолчанию, `--etcd-compaction-interval`). Включение `--auto-compaction-retention` на стороне etcd создаёт конкурирующие компакции и может вызывать ошибки `mvcc: required revision has been compacted` на длинных watch-потоках — включайте его только если компакция не выполняется на стороне API-сервера.

### Lease checkpoint

Lease checkpoint сохраняет remaining TTL leases в consensus log, чтобы после перезапуска etcd или смены лидера leases не истекали массово и не теряли оставшееся время (предотвращение каскадного удаления ключей).

```bash
# etcd 3.4 / 3.5 — включить явно (default false)
etcd --experimental-enable-lease-checkpoint=true
# на 3.5.2+ дополнительно: персистить remainingTTL в локальный backend
etcd --experimental-enable-lease-checkpoint-persist=true

# etcd 3.6 — feature gate (старый experimental-флаг deprecated, но работает)
etcd --feature-gates=LeaseCheckpoint=true

# etcd 3.7 — только feature gate; experimental-флаги удалены
etcd --feature-gates=LeaseCheckpoint=true
# LeaseCheckpointPersist=true без LeaseCheckpoint=true → ошибка валидации
```

Интервал checkpoint'а — 5 минут по умолчанию (внутренняя константа lessor'а, не настраивается флагом).

### Восстановление после NOSPACE

При превышении `--quota-backend-bytes` (по умолчанию 2 ГБ) etcd поднимает кластерный аларм NOSPACE и переходит в режим обслуживания: разрешены только чтения и удаления.

```bash
# 1. Текущая ревизия
rev=$(etcdctl endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9].*')

# 2. Компакция
etcdctl compact $rev
# → compacted revision 1516

# 3. Defrag поочерёдно на каждом члене
etcdctl defrag --cluster

# 4. Сброс аларма
etcdctl alarm disarm
# → alarm:NOSPACE

# 5. Проверка: запись снова работает
etcdctl put newkey 123
# → OK
```

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Быстрый рост БД при стабильной нагрузке | GC не справляется с leases или compaction отстаёт | Увеличить частоту compaction (уменьшить retention); проверить keep-alive клиентов; при фрагментации > 30% — defrag |
| `etcd_debugging_server_lease_expired_total` растёт экспоненциально | Клиенты теряют keep-alive (сеть, API-server перегружен) | Проверить сеть; увеличить TTL lease; учесть лимит отзыва ~1000 leases/с |
| Чтение по старой ревизии возвращает `required revision has been compacted` | Watcher/клиент отстал от compaction | Выполнить полный GET и начать новый watch с текущей revision |
| Defrag не возвращает место | Compaction не запускался | Запустить compaction перед defrag |
| Высокое использование RAM | Много leases в памяти (`leaseMap`) | Проверить число leases через `etcdctl lease list`; оптимизировать TTL |
| `database space exceeded` / NOSPACE | Достигнут `quota-backend-bytes` | compact → defrag → `etcdctl alarm disarm` |

## Best Practices

- **Compaction перед Defrag:** всегда запускайте compaction, иначе defrag не вернёт значительного места.
- **Lease TTL ≥ 2–3× интервала keep-alive:** защита от ложного истечения при кратковременных сетевых проблемах.
- **Lease checkpoint:** выключен по умолчанию во всех версиях (Alpha). В production с длинными TTL включайте: 3.5 — `--experimental-enable-lease-checkpoint=true` (и `--experimental-enable-lease-checkpoint-persist=true` на 3.5.2+), 3.6/3.7 — `--feature-gates=LeaseCheckpoint=true`.
- **Мониторинг GC:** следите за `etcd_debugging_server_lease_expired_total` и парой `etcd_mvcc_db_total_size_in_bytes` / `etcd_mvcc_db_total_size_in_use_in_bytes`.
- **Не храните постоянные данные в leases:** lease — для временных ключей (service discovery, leader election); для постоянных данных — обычные put без lease.
- **Mass deletion:** при удалении миллионов ключей compaction может длиться секунды и нагружать CPU/диск конкретного члена — выполняйте в часы минимальной нагрузки.
- **Defrag поочерёдно:** никогда не дефрагментируйте все члены одновременно — это может привести к потере кворума.

## Edge Cases

- **Mass expiry после восстановления связи:** отзыв ограничен ~1000 leases/с; при массовом истечении ключи удаляются с задержкой, БД временно растёт.
- **Смена лидера:** истечение leases приостанавливается на время выборов (лидер — единственный primary lessor); после повышения все leases продлеваются. Без LeaseCheckpoint `Promote(electionTimeout)` выставляет expiry = now + election-timeout + полный TTL — длинные аренды фактически продлеваются до полного TTL при каждой смене лидера; с включённым LeaseCheckpoint новый лидер использует последний checkpointed remainingTTL (отставание ≤ 5 мин).
- **Compaction во время write spike:** compaction не блокирует новые записи, но делает чтение по compacted ревизиям невозможным (ошибка, а не блокировка) и создаёт нагрузку на CPU/диск члена.
- **GC и snapshot:** GC не влияет на уже созданные снапшоты (bbolt работает по copy-on-write); снапшот содержит все данные на момент создания.
- **ErrGRPCNoSpace при успешной записи:** возможен ответ `no space` для Put/Txn/LeaseGrant, хотя запись в backend всё же применена — квота проверяется и на API-слое, и на слое Apply (где поднимается аларм без блокировки транзакции).
- **Lease ID:** ID выбирается сервером, если клиент передал 0; истекшие lease ID не возвращаются в пул и не переиспользуются.

## См. также

* **[MVCC, версионирование и компакция](./mvcc_versioning_and_compaction.md)** — модель MVCC, treeIndex, BoltDB, defrag, NOSPACE.
* **[Watch и Lease: внутреннее устройство](./watch_lease_internals.md)** — watch buffer, compacted revision, keepalive.
* **[Внутреннее устройство хранения](./storage_internals.md)** — BoltDB, bbolt, CoW, Freelist.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики GC, leases и фрагментации.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — команды compact, defrag, lease.
* **[Аварийное восстановление](./emergency_recovery.md)** — восстановление из снапшота.
