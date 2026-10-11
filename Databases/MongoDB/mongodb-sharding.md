# MongoDB: Шардирование

**Актуально для:** MongoDB 8.0.x

## Определения

**Шардирование (Sharding)** — метод горизонтального масштабирования (Scale-Out), при котором данные распределяются по нескольким физическим узлам или Replica Sets, называемым **шардами**. В отличие от репликации, шардирование позволяет увеличивать не только отказоустойчивость, но и общую пропускную способность записи и объем хранимых данных.

*   **Shard (Шард):** Узел, содержащий часть данных кластера. В Production-средах каждый шард обязан быть Replica Set.
*   **Config Servers (CSRS):** Специальная Replica Set, хранящая метаданные кластера. В MongoDB 8.0+ поддерживает концепцию **Config Shard** для малых кластеров (≤3 шардов), когда config server объединён с шардом в одной Replica Set.
*   **Mongos (Маршрутизатор):** Прокси-слой, который принимает запросы от приложения, определяет местоположение данных через Config Servers и направляет запрос на нужный шард.
*   **Chunk (Чанк):** Непрерывный диапазон данных внутри коллекции, распределяемый по шардам. Размер по умолчанию в версии 8.0 — 128 МБ.
*   **Balancer (Балансировщик):** Фоновый процесс, который перемещает чанки между шардами для обеспечения равномерного распределения данных.
*   **Zone (Зона):** Логическая группа шардов, объединённых для размещения диапазонов ключа шардирования (например, по регионам или типам хранилищ).
*   **Cluster Wide Write Concern (CWWC):** Настройка, обязательная с MongoDB 5.1+ для добавления шардов и операций с metadata. Минимальное значение — `majority`.
*   **Jumbo Chunk:** Чанк, превышающий максимальный размер миграции (64 МБ по умолчанию) и не поддающийся автоматическому разделению.
*   **Range Deleter:** Фоновый процесс, удаляющий документы с донорского шарда после завершения миграции чанка.

Подробная теория общих принципов: **[Шардирование в БД](../Concepts/sharding.md)**.

---

## Архитектура и механизмы

### Компоненты кластера

| Компонент | Роль | Порядок запуска | Порты по умолчанию |
| :--- | :--- | :--- | :--- |
| **Config Servers (CSRS)** | Хранят метаданные кластера, routing table, распределительные блокировки | Первыми | 27019 |
| **Mongos** | Маршрутизатор запросов, кэширует routing table | После CSRS | 27017 |
| **Shard (Replica Set)** | Хранит подмножество данных | После CSRS | 27018 (кастомный) |

### Config Shard vs Dedicated Config Server (MongoDB 8.0+)

Начиная с версии 8.0, кластер может использовать два режима для Config Servers:

*   **Dedicated Config Server:** Классическая конфигурация, где config server работает как отдельная Replica Set только для метаданных. Требует минимум 3 узла.
*   **Config Shard:** Config server объединён с шардом в одной Replica Set. Подходит для кластеров с ≤3 шардами. Уменьшает количество необходимых узлов.
*   **Переключение режима:** Команды `transitionFromDedicatedConfigServer` и `transitionToDedicatedConfigServer` позволяют переключаться между режимами без остановки кластера.

### Маршрутизация запросов
- **Targeted Query (Целевой запрос):** Содержит ключ шардирования. `mongos` направляет его на один конкретный шард. Самый эффективный метод.
- **Scatter-Gather (Широковещательный):** Не содержит ключа шардирования. `mongos` опрашивает все шарды и собирает результат. Крайне неэффективно для больших кластеров.

### Поведение балансировщика и автосплита (MongoDB 6.0.3+)

*   **Автосплит отключён:** Начиная с MongoDB 6.0.3, автоматическое разделение чанков не выполняется. Команды `sh.enableAutoSplit()` и `sh.disableAutoSplit()` существуют, но не влияют на поведение. Используйте ручной пресплит (`presplitHashedZones` или `sh.splitAt()`) перед массовой загрузкой данных.
*   **Балансировщик:** Перемещает чанки на основе политик balancing. Для управления окном обслуживания используйте `db.settings` с `activeWindow`.
*   **Range Deleter:** Фоновый процесс, удаляющий данные с донорского шарда после завершения миграции. Мониторится через `$currentOp`.

### Cluster Wide Write Concern (CWWC)

С MongoDB 5.1+ при добавлении шардов, запуске/перезапуске `shardsvr` или операциях с метаданными кластера должно быть установлено CWWC. Минимальное значение — `{ w: "majority" }`. Если CWWC не установлен и `writeConcern` на шарде по умолчанию `{ w: 1 }`, шард не запустится или не сможет быть добавлен в кластер.

### Выбор ключа шардирования (Shard Key)

Выбор ключа — необратимая (до версии 5.0) или дорогостоящая операция. Критерии:
*   **Кардинальность:** Количество уникальных значений ключа должно быть высоким.
*   **Частота (Frequency):** Значения ключа должны быть распределены равномерно.
*   **Направление роста:** Монотонно растущие ключи (например, `ObjectId`) при Ranged-шардировании создают "горячий шард". Используйте **Hashed Sharding**.
*   **Локальность данных:** Связанные документы (например, заказ и его позиции) должны попадать на один шард для избежания Cross-shard JOIN.

### Зонирование (Zone Sharding)

Zone Sharding позволяет привязывать диапазоны ключа шардирования к конкретным шардам или группам шардов. Используется для:
*   Соответствия требованиям георасположения данных (GDPR, data residency).
*   Разделения хранилищ по производительности (Tiered Storage: SSD vs HDD).
*   Изоляции "горячих" диапазонов на выделенных узлах.

Команды: `sh.addShardToZone()`, `sh.addTagRange()`, `sh.updateZoneKeyRange()`.

---

## Практические сценарии

### 1. Пошаговая настройка кластера (Manual Setup)

**Предварительные требования:**
*   ОС: Linux (Ubuntu 22.04+/RHEL 8+). macOS/Windows — только для разработки.
*   Сеть: Порты 27017 (mongos/mongod), 27018 (shardsvr), 27019 (configsvr) открыты только внутри доверенного сегмента (VLAN/VPC). Запретить доступ из интернета.
*   DNS: Все узлы должны разрешать имена друг друга (или использовать IP в строке подключения).
*   CWWC: Установить `clusterWideWriteConcern: { w: "majority" }` в `mongod.conf` перед добавлением шардов (MongoDB 5.1+).
*   Хранилище: Рекомендуется NVMe SSD для CSRS и WiredTiger cache. Конфигурация `storage.wiredTiger.engineConfig.cacheSizeGB` — 50% от RAM, но не более 64 GB на узел.

**Шаг 1: Настройка Config Server Replica Set (CSRS)**
```bash
# На каждом узле CSRS
mongod --configsvr --replSet configRS --port 27019 --dbpath /data/configdb --bind_ip 127.0.0.1,<internal-ip>
```
```javascript
// Инициализация в mongosh (подключение к cfg1:27019)
rs.initiate({
  _id: "configRS",
  configsvr: true,
  members: [{ _id: 0, host: "cfg1:27019" }, { _id: 1, host: "cfg2:27019" }, { _id: 2, host: "cfg3:27019" }]
})
// → { "ok" : 1 }
```
```bash
# Проверка статуса
mongosh --port 27019 --eval "rs.status()"
# → Должен показать STATE: PRIMARY/SECONDARY для всех членов
```

**Шаг 2: Настройка Shard Replica Sets**
```bash
# На каждом узле шарда
mongod --shardsvr --replSet shard1RS --port 27018 --dbpath /data/shard1 --bind_ip 127.0.0.1,<internal-ip>
```
```javascript
// Инициализация шарда (подключение к s1-n1:27018)
rs.initiate({
  _id: "shard1RS",
  members: [{ _id: 0, host: "s1-n1:27018" }, { _id: 1, host: "s1-n2:27018" }, { _id: 2, host: "s1-n3:27018" }]
})
// → { "ok" : 1 }
```
```bash
# Проверка
mongosh --port 27018 --eval "rs.status()"
# → Все члены в состоянии PRIMARY/SECONDARY, version: 1
```

**Шаг 3: Запуск Mongos**
```bash
mongos --configdb configRS/cfg1:27019,cfg2:27019,cfg3:27019 --port 27017 --bind_ip 127.0.0.1,<internal-ip>
```
```bash
# Проверка маршрутизации
mongosh --port 27017 --eval "db.isdbgrid()"
# → true
```

**Шаг 4: Добавление шардов в кластер (через mongos)**
```javascript
sh.addShard("shard1RS/s1-n1:27018,s1-n2:27018,s1-n3:27018")
// → { "ok" : 1 }

sh.enableSharding("shop_db")
// → { "ok" : 1 }

// Создание индекса для ключа шардирования (обязательно перед shardCollection)
db.users.createIndex({ user_id: 1 })

// Шардирование коллекции
sh.shardCollection("shop_db.users", { user_id: 1 })
// → { "ok" : 1 }

// Проверка статуса
sh.status()
// → Должен показать shard1RS в списке шардов и коллекцию shop_db.users в распределённых
```

### 2. Распределение коллекции и управление чанками (8.0+)

В MongoDB 8.0 рекомендуется использовать `sh.shardAndDistributeCollection()` для немедленного распределения данных при шардировании.

```javascript
// Быстрое шардирование и распределение (MongoDB 8.0+)
sh.shardAndDistributeCollection("shop_db.orders", { _id: "hashed" })
// → { "ok" : 1 }
// Данные немедленно распределяются по всем шардам без ожидания balancer.

// Ручное разделение чанка (Pre-splitting перед массовой загрузкой)
sh.splitAt("shop_db.users", { "user_id": 1000000 })
// → { "ok" : 1 }

// Проверка распределения данных
sh.status()
// → Показывает количество чанков на каждом шарде
```

**Пресплит для пустой коллекции:**
```javascript
// Определение зон
sh.addShardToZone("shard1RS", "zone_east")
sh.addShardToZone("shard2RS", "zone_west")

// Создание диапазонов
sh.addTagRange("shop_db.users", { user_id: MinKey() }, { user_id: 1000000 }, "zone_east")
sh.addTagRange("shop_db.users", { user_id: 1000000 }, { user_id: MaxKey() }, "zone_west")

// Шардирование с пресплитом по зонам
sh.shardCollection("shop_db.users", { user_id: 1 }, { presplitHashedZones: false })
// → Чанки создаются в соответствии с диапазонами зон
```

### 3. Управление балансировщиком (SRE-задачи)

```javascript
// Проверка текущего состояния
sh.getBalancerState()    // → true/false
sh.isBalancerRunning()   // → true/false

// Статус балансировки конкретной коллекции
sh.balancerCollectionStatus("shop_db.orders")
// → { inBalancerRound: false, chunksMigrated: 0, ... }

// Настройка окна обслуживания (Maintenance Window)
db.settings.updateOne(
   { _id: "balancer" },
   { $set: { activeWindow: { start: "02:00", stop: "06:00" } } },
   { upsert: true }
)
// → { "acknowledged" : true, "matchedCount" : 1, ... }

// Принудительная ребалансировка после добавления шарда (8.0+)
sh.reshardCollection("shop_db.orders", { _id: "hashed" }, { forceRedistribution: true })
// → { "ok" : 1 }
// Внимание: отключает balancer на время операции. Мониторьте через $currentOp.
```

### 4. Переключение на Config Shard (MongoDB 8.0+)

```javascript
// Проверка текущего режима
sh.isConfigShardEnabled()
// → { enabled: false } — dedicated config server
// → { enabled: true } — config shard

// Переключение Dedicated Config Server → Config Shard
db.adminCommand({ transitionFromDedicatedConfigServer: 1 })
// → { "ok" : 1 }

// Обратное переключение (например, перед добавлением >3 шардов)
db.adminCommand({ transitionToDedicatedConfigServer: 1 })
// → { "ok" : 1 }
```

### 5. Перемещение и удаление шардов

```javascript
// Добавление нового шарда
sh.addShard("shard2RS/s2-n1:27018,s2-n2:27018,s2-n3:27018")
// → { "ok" : 1 }

// Проверка статуса миграции данных
sh.status()

// Удаление шарда (после миграции всех его чанков)
sh.removeShard("shard1RS")
// → { "state" : "ongoing", "remaining" : { "chunks": 0, "dbs": 0 } }
// Повторять until state: "completed"

// Перемещение нешардированной коллекции (8.0+)
db.adminCommand({
  moveCollection: "shop_db.logs",
  toShard: "shard2RS"
})
// → { "ok" : 1 }
```

---

## Продвинутые возможности v8.0+

### Resharding (Живой решардинг)

Подробное описание механизма, ограничений и практических сценариев: **[Решардинг (Live Resharding)](./mongodb-resharding.md)** (MongoDB 5.0+). В 8.0 добавлена опция `forceRedistribution` для перераспределения данных на том же ключе и `numSamplesPerChunk` для управления семплированием чанков.

### Zone Sharding (Зонирование)
Привязка диапазонов ключа к конкретным шардам или группам шардов. Используется для:
*   Соответствия требованиям георасположения данных (GDPR, data residency).
*   Разделения хранилищ по производительности (Tiered Storage: SSD vs HDD).
*   Изоляции "горячих" диапазонов на выделенных узлах.

Команды: `sh.addShardToZone()`, `sh.addTagRange()`, `sh.updateZoneKeyRange()`.

### unshardCollection (8.0+)
Позволяет "рашардировать" коллекцию обратно на один шард. Полезно для:
*   Удаления шарда из кластера (миграция данных на оставшиеся шарды + `unshardCollection` для освобождения места).
*   Архивации неактивных коллекций.

### moveCollection (8.0+)
Перемещение нешардированной коллекции между шардами без ручного копирования данных.

---

## Диагностика и устранение неисправностей

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Jumbo Chunks** | Чанк нельзя разбить: слишком много документов с одним значением ключа. | `db.getSiblingDB("config").chunks.find({ jumbo: true })` | Использовать `refineCollectionShardKey` для добавления поля с высокой кардинальностью. Вручную очистить флаг `jumbo` через `db.getSiblingDB("config").chunks.update(...)` после разделения. |
| **Balancer Stalls** | Долгая фиксация (Replica Lag) или конфликт миграций. | `db.getSiblingDB("admin").aggregate([{ $currentOp: { allUsers: true, localOps: false } }, { $match: { type: "op", "command.reshardCollection": { $exists: true } } }])` | Убедиться, что `secondary` узлы успевают за `primary`. Проверить `w:majority` на записях. Увеличить `oplogSize`. |
| **Stale Config** | Устаревший routing table на mongos или шарде. | Логи `mongos`: `StaleConfig error` | Автоматически исправляется retry. При устойчивых ошибках: `db.getSiblingDB("admin").aggregate([{ $currentOp: ... }])` и перезапуск mongos. |
| **CWWC Error при добавлении шарда** | CWWC не установлен или значение ниже `majority`. | Логи: `Cluster Wide Write Concern must be set` | Установить `clusterWideWriteConcern: { w: "majority" }` в `mongod.conf` на всех шардах и перезапустить. |
| **MoveCollection Failure** | Нехватка места на целевом шарде. | `db.serverStatus().wiredTiger.cache` | Использовать `moveCollection` (8.0+) для переноса нешардированных данных. Проверить `storage.totalSize` на целевом шарде. |
| **Range Deleter Lag** | Медленное удаление данных с донорского шарда после миграции. | `db.getSiblingDB("admin").aggregate([{ $currentOp: { allUsers: true, localOps: false } }, { $match: { op: "none", "command.deleteRange": { $exists: true } } }])` | Увеличить `wiredTiger.concatenatedCompression` или `blockCompressor`. Проверить I/O wait на доноре. |
| **Migration Conflicts** | Один шард участвует в нескольких миграциях одновременно. | Логи шарда: `aborting migration because recipient is doing another migration` | Нормальное поведение. Балансировщик повторит попытку. Убедиться, что `maxChunkSize` не слишком мал (по умолчанию 128 МБ). |

---

## Лучшие практики (Best Practices 2026)

### Проектирование кластера
*   **Config Shard для малых кластеров:** Используйте Config Shard при ≤3 шардах. Переключитесь на Dedicated Config Server перед масштабированием >3 шардов или при использовании Queryable Encryption.
*   **Pre-splitting:** Всегда делайте ручной сплит (`presplitHashedZones` или `sh.splitAt()`) перед импортом миллионов строк. Автосплит отключён с 6.0.3.
*   **Shard Key во всех запросах:** Убедитесь, что приложение всегда передает Shard Key в фильтрах. Отсутствие ключа приводит к Scatter-Gather.
*   **Индекс перед шардированием:** Создавайте индекс для ключа шардирования перед `sh.shardCollection()`, если коллекция не пуста.

### Операционная стабильность
*   **CWWC:** Устанавливайте `clusterWideWriteConcern: { w: "majority" }` на всех шардах. Это обязательное требование с 5.1+.
*   **Сеть:** Порты 27017/27018/27019 открыты только внутри доверенного сегмента (VLAN/VPC). Используйте `bind_ip` для ограничения интерфейсов.
*   **WiredTiger Cache:** Устанавливайте `storage.wiredTiger.engineConfig.cacheSizeGB` = 50% RAM, но не более 64 GB. На контейнерах (K8s/Docker) всегда явно задавайте лимит, иначе MongoDB будет использовать всю RAM хоста.
*   **Мониторинг Skew:** Настройте алерты на отклонение размера данных или количества чанков между шардами более чем на 20-30%.
*   **Balancer Window:** Настройте `activeWindow` для балансировщика в нерабочее время, если кластер под высокой нагрузкой.

### Отказоустойчивость
*   **PSS-топология:** В шардированных кластерах арбитры не рекомендуются. Используйте 3 узла с voting: 2 data-bearing + 1 hidden/priority 0, или 3 data-bearing.
*   **Резервное копирование:** Используйте `mongodump` на каждом шарде отдельно или Filesystem Snapshot (LVM/ZFS) с остановкой балансировщика. Не бэкапите отдельный mongos.
*   **План отката:** Перед `reshardCollection` всегда имейте план возврата к старой схеме (дамп коллекции или `forceRedistribution: false`).

### Миграции и решардинг
*   **forceRedistribution:** Используйте для быстрого перераспределения данных после добавления шарда. В 50+ раз быстрее последовательных миграций чанков.
*   **refineCollectionShardKey:** При Jumbo Chunks добавляйте суффиксное поле (например, `{ user_id: 1, region: 1 }`), а не полностью меняйте ключ.
*   **Ограничения:** Не шардируйте коллекции с размером < 1 ГБ. Не используйте `unique: true` с hashed ключом. Не шардируйте Time Series коллекции по `timeField` — используйте `metaField`.

---

Для изменения ключа шардирования без остановки сервиса используйте механизм **[Live Resharding](./mongodb-resharding.md)** (MongoDB 5.0+).

## Команды администрирования (Reference)

| Команда / Метод | Версия | Описание |
| :--- | :--- | :--- |
| `sh.shardCollection()` | Все | Включает шардирование для коллекции. |
| `sh.shardAndDistributeCollection()` | 8.0+ | Шардирует коллекцию и сразу перераспределяет данные. |
| `sh.reshardCollection()` | 5.0+ | Изменяет ключ шардирования без остановки записи. |
| `sh.unshardCollection()` | 8.0+ | Возвращает коллекцию на один шард. |
| `sh.moveCollection()` | 8.0+ | Перемещает нешардированную коллекцию между шардами. |
| `sh.addShard()` | Все | Добавляет шард в кластер. |
| `sh.removeShard()` | Все | Удаляет шард (после миграции всех чанков). |
| `sh.splitAt()` | Все | Вручную делит чанк по указанному значению ключа. |
| `sh.enableSharding()` | Все | Включает шардирование для базы данных (необязательно с 6.0). |
| `sh.getBalancerState()` | Все | Проверяет, включен ли балансировщик. |
| `sh.disableBalancing()` | Все | Отключает балансировку для конкретной коллекции. |
| `sh.enableBalancing()` | Все | Включает балансировку для коллекции. |
| `sh.addShardToZone()` | Все | Привязывает шард к зоне. |
| `sh.addTagRange()` | Все | Создаёт диапазон ключа в зоне. |
| `sh.refineCollectionShardKey()` | 5.0+ | Добавляет суффикс к существующему ключу (для Jumbo Chunks). |
| `transitionFromDedicatedConfigServer` | 8.0+ | Переключает config server в режим Config Shard. |
| `transitionToDedicatedConfigServer` | 8.0+ | Переключает config server в Dedicated Config Server. |

## Дополнительная информация

*   **[Общий обзор MongoDB](./mongodb.md)** — основы архитектуры.
*   **[Репликация в MongoDB](./mongodb-replication.md)** — база для каждого шарда.
*   **[Администрирование](./mongodb-administration.md)** — мониторинг и бэкапы.
*   **[Решардинг (Live Resharding)](./mongodb-resharding.md)** — изменение ключа без простоя.
*   **[Шардирование в БД (общая теория)](../Concepts/sharding.md)** — принципы горизонтального масштабирования.
