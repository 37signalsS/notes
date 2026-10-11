# Troubleshooting: Decision Tree и Incident Response

**Актуально для:** MongoDB 8.0.x (standalone, Replica Set, Sharded Cluster)

---

## Определения

*   **Decision Tree** — алгоритм диагностики: от симптома к корневой причине через последовательные проверки.
*   **Incident Response** — процедура реагирования на инцидент: обнаружение → локализация → митигация → восстановление → постмортем.
*   **Golden Signals** — latency, traffic, errors, saturation — четыре сигнала, на которые смотрят в первую очередь (см. **[Мониторинг](./mongodb-monitoring.md)**).
*   **USE-метод** — Utilization, Saturation, Errors — для ресурсов (CPU, RAM, диск, сеть).
*   **Postmortem (без поиска виноватых)** — анализ инцидента после разрешения: что случилось, почему, как предотвратить.

---

## Требования и предварительная подготовка

Для эффективной диагностики инцидентов необходимы:

*   **Доступ к узлам:** SSH-доступ ко всем узлам Replica Set / Sharded Cluster с правами `mongodb`-пользователя или `root`.
*   **Установленные утилиты:** `mongosh` (8.0+), `mongostat`, `mongotop`, системные `vmstat`, `iostat`, `free`, `df`, `ss`, `nc`.
*   **Мониторинг:** Prometheus + `mongodb_exporter` для метрик (см. [Мониторинг](./mongodb-monitoring.md)); Grafana-дашборды с Golden Signals.
*   **Логи:** доступ к `/var/log/mongodb/mongod.log` с возможностью `tail -f` и фильтрации.
*   **Runbooks:** документированные процедуры для типовых инцидентов (failover, disk full, lag, connection storm).
*   **Бэкапы:** проверенный резервный копирования и восстановления (см. [Backup & DR](./mongodb-backup-dr.md)).
*   **Chaos Engineering:** регулярные тесты отказоустойчивости в staging-окружении (убийство Primary, остановка mongod).
*   **Контакты:** on-call-список, окно инцидентов, каналы коммуникации (chat/phone).

---

## Базовые концепции

### Decision Tree: от симптома к причине

```
СИМПТОМ
├─ Приложение не подключается
│  ├─ MongoServerSelectionError → нет Primary / сеть / auth
│  │  ├─ db.hello() → нет Primary? → Replica Set (см. ниже)
│  │  ├─ ping host:port → сеть / firewall
│  │  └─ auth failed → credentials / authSource / authMechanism
│  └─ Connection pool exhausted → maxPoolSize / долгие операции
│
├─ Медленные запросы
│  ├─ COLLSCAN → нет индекса (см. [Индексы](./mongodb-indexes.md))
│  ├─ Cache miss → working set > cacheSizeGB (см. [Capacity Planning](./mongodb-capacity-planning.md))
│  ├─ Disk I/O → iostat, checkpoint spikes
│  └─ Lock contention → db.currentOp(), globalLock
│
├─ Записи не проходят / ошибки записи
│  ├─ NotPrimary / PrimarySteppedDown → failover (см. [Высокая доступность](./high_availability.md))
│  ├─ WriteConcernError → wtimeout / недоступные secondaries
│  ├─ DuplicateKey → дубликат _id / уникальный индекс
│  └─ Document exceeds 16MB → GridFS (см. [GridFS](./mongodb-gridfs.md))
│
├─ Replica Set нездоров
│  ├─ Нет Primary → кворум / electionTimeout / приоритеты
│  ├─ Replication lag → slow op / network / secondary busy
│  └─ Oplog Window мал → размер oplog
│
├─ Sharded Cluster проблемы
│  ├─ Balancer активен → влияет на latency
│  ├─ Chunk migration ошибки → версии / диск
│  └─ Query routing → mongos / config servers
│
└─ Ресурсы (USE)
   ├─ CPU 100% → COLLSCAN / агрегации / конкуренция
   ├─ RAM → cache evictions / OOM
   ├─ Disk full → рост данных / oplog / journal
   └─ Network → bandwidth / connections
```

### Incident Response: фазы

| Фаза | Действия |
| :--- | :--- |
| **1. Обнаружение** | Алерт (Prometheus/Grafana), жалоба пользователя, `mongostat` |
| **2. Локализация** | Golden Signals → какой компонент? `db.currentOp()`, `mongostat`, логи |
| **3. Митигация** | Kill op, failover, scale up, отключить balancer, rollback релиза |
| **4. Восстановление** | Восстановить SLO, проверить репликацию, бэкап |
| **5. Постмортем** | Timeline, root cause, action items, предотвращение |

### Ключевые диагностические команды

```javascript
// Текущие операции (что зависло)
db.currentOp({ "secs_running": { "$gt": 5 } })

// Прервать операцию
db.killOp(opid)

// Состояние сервера
db.serverStatus()

// Репликация
rs.status()
rs.printSecondaryReplicationInfo()
rs.printReplicationInfo()

// Шардирование
sh.status()
sh.isBalancerRunning()

// Профилирование (медленные запросы)
db.setProfilingLevel(1, { slowms: 50 })
db.system.profile.find().sort({ millis: -1 }).limit(10)
```

```bash
# ОС
vmstat 1 5          # CPU, memory, swap, io
iostat -x 1 5       # disk
free -h             # RAM
df -h               # disk
ss -s               # sockets

# MongoDB
mongostat --host rs0/mongo-1:27017 --rowcount 60
mongotop --host rs0/mongo-1:27017 --rowcount 60
```

---

## Практические сценарии

### 1. Приложение не подключается

```bash
# 1. Пинг порта
nc -zv mongo-1 27017

# 2. Проверка Replica Set
mongosh "mongodb://mongo-1:27017/?replicaSet=rs0" --eval "db.hello()"

# 3. Проверка аутентификации
mongosh "mongodb://user:pass@mongo-1:27017/admin?authSource=admin" \
  --eval "db.runCommand({connectionStatus:1})"

# 4. Проверка пула (драйвер)
# См. [Connection Strings](./mongodb-connection-strings.md)
```

**Решение:**
*   `MongoServerSelectionError` → нет Primary или сеть. Проверить `rs.status()`, firewall, `directConnection`.
*   `auth failed` → проверить `authSource`, `authMechanism`, пароль, `SCRAM-SHA-256`.
*   Pool exhausted → уменьшить `maxPoolSize`, проверить долгие операции (`db.currentOp()`).

### 2. Медленные запросы

```javascript
// 1. Найти медленные операции
db.currentOp({ "secs_running": { "$gt": 5 } })

// 2. Профилирование
db.setProfilingLevel(1, { slowms: 50 })
db.system.profile.find().sort({ millis: -1 }).limit(10).pretty()

// 3. План запроса
db.collection.find({...}).explain("executionStats")
// → planSummary: "COLLSCAN" — нет индекса
// → totalDocsExamined >> nReturned — неэффективный индекс
```

**Решение:**
*   `COLLSCAN` → создать индекс (ESR-правило, см. **[Индексы](./mongodb-indexes.md)**).
*   `totalDocsExamined` >> `nReturned` → пересмотреть индекс (compound, covered query).
*   Cache miss → увеличить `cacheSizeGB` (см. **[Capacity Planning](./mongodb-capacity-planning.md)**).

### 3. Нет Primary в Replica Set

```javascript
rs.status()
// → members: [{ state: 2 (SECONDARY) }, ...] — нет state: 1 (PRIMARY)

// Проверить кворум
rs.conf()
// → members[].votes, members[].priority

// Логи
tail -f /var/log/mongodb/mongod.log | grep -i election
```

**Причины:**
*   Потерян кворум (недоступно > половины голосующих узлов).
*   `electionTimeoutMillis` слишком велико (по умолчанию 10с).
*   Все secondaries имеют `priority: 0`.
*   Сетевой раздел (split-brain).

**Решение:** см. **[Высокая доступность](./high_availability.md)**.

### 4. Replication lag

```javascript
rs.printSecondaryReplicationInfo()
// → syncedTo: ... (лаг в секундах)

// На secondary: что тормозит
db.currentOp({ "secs_running": { "$gt": 5 } })
```

**Причины:** долгие операции на secondary, сеть, недостаток ресурсов, `secondaryDelaySecs`.

**Решение:** оптимизировать операции, проверить сеть, увеличить ресурсы secondary.

### 5. Disk full

```bash
df -h /var/lib/mongodb
du -sh /var/lib/mongodb/*
```

```javascript
// Размер БД
db.stats()

// Oplog размер
rs.printReplicationInfo()
```

**Решение:**
*   Очистить данные (TTL, архивация, time-series).
*   Увеличить диск.
*   Уменьшить oplog (если он занимает место): `rs.resizeOplog()`.

### 6. CPU 100%

```bash
vmstat 1 5
mongostat --host rs0/mongo-1:27017 --rowcount 60
```

```javascript
// Что грузит CPU
db.currentOp({ "secs_running": { "$gt": 1 } })
db.system.profile.find().sort({ millis: -1 }).limit(10)
```

**Причины:** COLLSCAN, сложные агрегации, высокая конкуренция, сжатие/шифрование.

**Решение:** индексы, оптимизация агрегаций (`$match` early, `allowDiskUse`), масштабирование.

### 7. Connection saturation

```javascript
db.serverStatus().connections
// → { current: 9800, available: 200, totalCreated: 500000 }
```

**Причина:** `maxPoolSize` драйвера × N инстансов > `net.maxIncomingConnections`.

**Решение:** см. **[Connection Strings](./mongodb-connection-strings.md)**.

### 8. Sharded Cluster: balancer влияет на latency

```javascript
sh.isBalancerRunning()
sh.status()

// Остановить balancer (на время инцидента)
sh.stopBalancer()
// Возобновить
sh.startBalancer()
```

**Решение:** остановить balancer на время пика, настроить balancer window (`balancer.activeWindow`).

---

## Устранение неполадок

| Симптом | Первая проверка | Команда |
| :--- | :--- | :--- |
| Не подключается | Порт, сеть, Primary | `nc -zv`, `db.hello()` |
| Медленно | COLLSCAN, cache, disk | `explain()`, `iostat`, `serverStatus().wiredTiger` |
| Ошибка записи | Primary, write concern | `rs.status()`, `db.serverStatus().writeConcern` |
| Lag | Secondary busy, сеть | `rs.printSecondaryReplicationInfo()` |
| Disk full | Рост данных, oplog | `df -h`, `db.stats()`, `rs.printReplicationInfo()` |
| CPU 100% | COLLSCAN, агрегации | `currentOp()`, `system.profile` |
| Connections full | Пул драйвера | `serverStatus().connections` |

---

## Ограничения и Edge Cases

*   **`db.currentOp()` не показывает блокировки на уровне документа:** WiredTiger использует оптимистичные блокировки; конфликт проявляется как `WriteConflictError`, а не как видимая операция. Проверяйте `serverStatus().wiredTiger.concurrentTransactions`.
*   **`killOp` не отменяет операции в WiredTiger:** команда отправляет сигнал, но операция может завершиться только после фиксации транзакции. При `maxTimeMS` превышении операция отменяется сама.
*   **Профилирование влияет на производительность:** включение `db.setProfilingLevel(2)` добавляет overhead на каждую запись в `system.profile`. Используйте `slowms: 100` и отключайте после отладки.
*   **`rs.status()` недоступен на Secondary при сильной нагрузке:** узел может отвечать на `db.hello()`, но не на `rs.status()`. Используйте `mongod --eval "rs.status()"` локально.
*   **Split-brain:** при сетевом разделе оба узла могут стать Primary. Предотвращается через `settings.electionTimeoutMillis`, кворум и `hidden: true`/`priority: 0` для secondaries.
*   **Initial Sync failure:** при добавлении нового secondary может не успеть синхронизироваться (опlog window мал, медленная сеть). Проверяйте `db.currentOp()` на secondary, логи `Initial Sync`.
*   **`sh.stopBalancer()` временно:** balancer автоматически включается через `balancer.activeWindow`. Используйте `sh.setBalancerState(0)` для постоянного отключения (только для отладки).
*   **Логи переполняются:** `mongod.log` растёт неограниченно. Используйте logrotate (`/etc/logrotate.d/mongodb`) или включите `system.logRotate: reopen` с `logappend: false`.
*   **`mongosh` версии:** устаревший `mongosh` не поддерживает новые команды (например, `rs.conf()` в 8.0). Обновляйте вместе с `mongodb-org`.
*   **Сетевые таймауты:** `MongoServerSelectionError` с `serverSelectionTimeoutMS` (по умолчанию 30с) может masquerade как «нет Primary». Увеличивайте таймаут при медленной сети.
*   **`db.fsyncLock()` блокирует запись:** используется только для бэкапов на hidden secondary (см. [Backup & DR](./mongodb-backup-dr.md)). Никогда не запускайте на production Primary.

---

## Лучшие практики (SRE)

1.  **Golden Signals first:** latency, traffic, errors, saturation — до глубокого анализа.
2.  **Decision Tree:** двигайтесь от симптома к причине по дереву, не хаотично.
3.  **`db.currentOp()`** — первая команда при зависании.
4.  **Профилирование** включайте заранее (`slowms: 50`), не после инцидента.
5.  **Постмортем без поиска виноватых:** timeline → root cause → action items.
6.  **Runbook:** документируйте типовые инциденты (failover, disk full, lag).
7.  **Тестируйте отказоустойчивость:** chaos engineering (убейте Primary в staging).
8.  **Алерты actionability:** каждый алерт — на действие (см. [Мониторинг](./mongodb-monitoring.md)).
9.  **Бэкапы проверяйте регулярно:** тестовое восстановление — единственный способ знать, что бэкап работает.
10. **`terraform plan` перед любыми изменениями:** drift detection как рутина.
11. **Изменения только через IaC:** ручные изменения на узлах приводят к drift (см. [Terraform + Ansible](./mongodb-terraform.md)).
12. **Капитальный ремонт:** останавливайте `mongod` только через `db.fsyncLock()` + `db.shutdownServer()` на secondary, never `kill -9`.
13. **Мониторинг oplog window:** `rs.printReplicationInfo()` — если window < 4 часа, увеличивайте `oplogSizeMB` (см. [Репликация](./mongodb-replication.md)).
14. **Chaos Engineering:** раз в квартал в staging — убить Primary, остановить mongod, заполнить диск.
15. **On-call rotation:** каждый инцидент должен быть разобран в течение 24-48 часов.

---

## Восстановление и откат

| Ситуация | Действие |
| :--- | :--- |
| **Потеря Primary** | Ждём выборов (по умолчанию 10с). Если кворум есть — автоматически избирается новый Primary. Если нет — восстанавливаем конфигурацию RS через `rs.reconfig()`. |
| **Потеря кворума (2 из 3 узлов недоступны)** | Остановить запись на приложении. Восстановить узлы, дождаться кворума. `rs.stepDown()` на оставшемся Primary для принудительных выборов. |
| **Потеря всех данных (disk failure)** | Восстановить из бэкапа (см. [Backup & DR](./mongodb-backup-dr.md)). При W=1 и `journal` — возможно восстановление до последней фиксации. |
| **Drift между IaC и реальностью** | `terraform plan` показывает расхождение. Применить через `terraform apply` или `ansible --diff`. Удалить ручные изменения. |
| **Откат релиза MongoDB** | Остановить `mongod`, вернуть предыдущую версию пакета (`yum downgrade mongodb-org`), перезапустить. Проверить `rs.status()`. |
| **Откат приложения** | Откатить драйвер/код. Проверить `db.currentOp()` на long-running operations. При `WriteConflictError` — увеличить `wtimeout`. |
| **Полный отказ кластера** | Восстановление из бэкапа на чистом кластере. Проверить `rs.initiate()` и `sh.initiate()`. Использовать `mongorestore` для точечного восстановления. |

---

## Дополнительная информация

*   **[Мониторинг](./mongodb-monitoring.md)** — метрики, алерты, SLO.
*   **[Высокая доступность](./high_availability.md)** — failover, election.
*   **[Индексы](./mongodb-indexes.md)** — COLLSCAN, ESR-правило.
*   **[Capacity Planning](./mongodb-capacity-planning.md)** — ресурсы, USE.
*   **[Connection Strings](./mongodb-connection-strings.md)** — пул, connection storm.
*   **[GridFS](./mongodb-gridfs.md)** — файлы > 16 MB.
*   **[Шардирование](./mongodb-sharding.md)** — balancer, chunk migration.
*   [MongoDB Troubleshooting](https://www.mongodb.com/docs/manual/administration/analyzing-mongodb-performance/)
*   [MongoDB Incident Response](https://www.mongodb.com/docs/manual/administration/)
