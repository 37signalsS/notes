# Garbage Collection и внутренний GC etcd

**Garbage Collection (GC)** в etcd — это фоновый процесс, который удаляет устаревшие данные (старые ревизии, истекшие leases, неиспользуемые ключи) для предотвращения бесконечного роста базы данных. Понимание GC критично для диагностики проблем с памятью и диском.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Revision GC** | Удаление старых ревизий, предшествующих compacted revision. |
| **Lease GC** | Удаление метаданных истекших аренд и привязанных к ним ключей. |
| **Key GC** | Удаление ключей, которые были удалены пользователем, но всё ещё присутствуют в истории MVCC. |
| **Compaction** | Процесс, который помечает ревизии как удалённые и запускает GC. |
| **TTL Expiry** | Истечение времени жизни аренды, после которого ключи автоматически удаляются. |
| **Fragmentation** | Накопление "мертвых" страниц в BoltDB после compaction и GC. |

---

## Основные концепции

### Revision GC (Компакция)

Compaction — это основной механизм GC для ревизий:

1. **Запуск:** Лидер или API-сервер запускает compaction через `etcdctl compaction <rev>` или автоматически (`--auto-compaction-retention=5m`).
2. **Mark:** Все ревизии `< rev` помечаются как удалённые в `treeIndex`.
3. **GC:** Фоновый процесс удаляет метаданные старых ревизий из памяти.
4. **Impact:** Чтение по старым ревизиям возвращает ошибку `mvcc: required revision has been compacted`.

**Важно:** Compaction не удаляет данные из BoltDB физически — только помечает страницы как свободные (Freelist).

### Lease GC

Lease GC работает независимо от revision compaction:

**Жизненный цикл lease:**
1. Создание: `lease grant 60` → TTL = 60s, expire_time = now + 60s.
2. Keep-alive: Клиент отправляет `LeaseKeepAliveRequest` каждые ~10s.
3. Expiry: Если keep-alive не поступает, через `TTL + grace_period` lease помечается как expired.
4. GC: Фоновый goroutine проверяет expired leases каждые 100-200ms.
5. Удаление: Ключи, привязанные к expired lease, удаляются из BoltDB. Lease ID возвращается в пул.

**Grace Period:**
- После истечения TTL lease ещё не удаляется сразу.
- Grace period = 1-2 секунды (защита от сетевых миганий).
- За это время новый keep-alive может спасти lease.

**Влияние на производительность:**
- При высокой нагрузке (>100k leases) GC может отставать.
- Метрика `etcd_server_lease_expired_total` показывает количество истекших аренд.
- Если GC отстаёт, BoltDB заполняется "мертвыми" записями ключей.

### Key GC (Удаление пользовательских ключей)

Когда пользователь вызывает `etcdctl del /key`:
1. Ключ помечается как удалённый в `treeIndex` (создаётся новая tombstone-ревизия).
2. BoltDB не удаляет страницу сразу — она становится "мертвой".
3. После compaction tombstone-ревизии удаляются из истории.
4. Defrag возвращает страницы ОС.

**Важно:** Пока compaction не удалил tombstone, ключ всё ещё присутствует в истории. Это позволяет восстановить данные по старой ревизии.

---

## Практические сценарии

### Диагностика: GC не справляется с нагрузкой

```bash
# 1. Проверить метрику expired leases
curl -s http://localhost:2379/metrics | grep etcd_server_lease_expired_total
# → Рост > 1000/сек — GC отстаёт

# 2. Проверить размер БД
curl -s http://localhost:2379/metrics | grep etcd_mvcc_db_total_size_in_bytes
# → Быстрый рост несмотря на compaction

# 3. Проверить количество активных leases
curl -s http://localhost:2379/metrics | grep etcd_server_lease_object_count
# → > 500 000 — высокая нагрузка на GC
```

**Решение:**
- Увеличить `--auto-compaction-retention` (чаще compaction).
- Проверить keep-alive на стороне клиента (K8s kubelet).
- Увеличить `--lease-checkpoint-interval` (etcd 3.4+).

### Lease Checkpoint (v3.4+)

Lease checkpoint позволяет сохранять TTL lease в BoltDB периодически, чтобы после перезапуска etcd не терять leases:

```bash
# Включить lease checkpoint (в etcd.conf.yml или флагами)
--lease-checkpoint-interval=30s  # каждые 30 секунд
--lease-checkpoint-persist=true  # сохранять в BoltDB
```

**Benefit:** После перезапуска etcd leases не истекают массово, что предотвращает каскадное удаление ключей.

### Настройка compaction для высокой нагрузки

```bash
# Автоматическая компакция каждые 5 минут (K8s standard)
etcd --auto-compaction-mode=periodic --auto-compaction-retention=5m

# Или по количеству ревизий (сохранять последние 100 000)
etcd --auto-compaction-mode=revision --auto-compaction-retention=100000
```

**Рекомендация:** Для кластеров с > 5000 узлов используйте `revision` mode с retention = 50 000–100 000. Это предотвращает слишком частые compaction при пиковых нагрузках.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Быстрый рост БД при стабильной нагрузке | GC не справляется с leases или compaction отстаёт | Увеличить частоту compaction; проверить lease keep-alive |
| `etcd_server_lease_expired_total` растёт экспоненциально | Клиенты теряют keep-alive (сеть, API-server перегружен) | Проверить сеть; увеличить TTL lease |
| Ключи "оживают" после compaction | Клиент кэширует старые revision | Клиент должен переподключиться с текущей revision |
| Defrag не возвращает место | Compaction не запускался | Запустить compaction перед defrag |
| Высокое использование RAM | Много leases в памяти | Проверить `etcd_server_lease_object_count`; оптимизировать TTL |

---

## Best Practices

- **Compaction перед Defrag:** Всегда запускайте compaction, иначе defrag не вернёт значительного места.
- **Lease TTL ≥ 3× keep-alive interval:** Для K8s node lease TTL должен быть ≥ 30s (при update frequency 10s).
- **Lease Checkpoint:** Включайте `--lease-checkpoint-persist=true` для production.
- **Мониторинг GC:** Следите за `etcd_server_lease_expired_total` и `etcd_mvcc_db_total_size_in_use_in_bytes`.
- **Не храните постоянные данные в leases:** Lease — для временных ключей (service discovery, leader election).

---

## Edge Cases

- **Mass key deletion:** При удалении миллионов ключей compaction может заблокировать кластер на несколько секунд. Выполняйте в часы минимальной нагрузки.
- **Lease reuse:** После истечения lease ID возвращается в пул. Если новый lease получит тот же ID (маловероятно), старые ключи уже удалены.
- **Compaction во время write spike:** Compaction блокирует чтение по старым ревизиям, но не блокирует записи. Однако создаёт нагрузку на CPU/диск.
- **GC и snapshot:** GC не влияет на уже созданные снапшоты. Они содержат все данные на момент создания.

---

## См. также

* **[MVCC, версионирование и компакция](./mvcc_versioning_and_compaction.md)** — compaction и defrag.
* **[Watch и Lease: внутреннее устройство](./watch_lease_internals.md)** — lease GC и keepalive.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики GC и leases.
