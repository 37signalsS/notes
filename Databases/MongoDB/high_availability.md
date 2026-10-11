# Высокая доступность MongoDB (High Availability)

**Актуально для:** MongoDB 8.0+, Replica Sets, Sharded Clusters, Kubernetes Operator

---

## Определения

**Replica Set (Набор реплик)** — группа инстансов `mongod`, хранящих идентичный набор данных. Обеспечивает автоматический failover и избыточность. Минимальная рекомендуемая конфигурация — 3 узла данных (без арбитров).

**Primary (Лидер)** — единственный узел в Replica Set, принимающий операции записи. Все изменения фиксируются в Oplog.

**Secondary (Вторичный)** — узлы, копирующие Oplog лидера и применяющие изменения локально. Могут обслуживать read-запросы в зависимости от Read Preference.

**Oplog (Operations Log)** — специальная capped-коллекция, хранящая историю всех изменений данных. Является фундаментом логической репликации.

**Arbiter (Арбитр)** — узел, который не хранит данные и не может стать Primary. Единственная задача — участие в голосовании для обеспечения кворума. Используется только в крайних случаях для экономии ресурсов.

**Sharded Cluster (Шардированный кластер)** — архитектура, распределяющая данные по нескольким Replica Sets (шардам). Обеспечивает горизонтальное масштабирование и HA на уровне данных.

**Config Server (CSRS)** — специальный Replica Set (3 узла), хранящий метаданные шардированного кластера (какие шарды существуют, распределение чанков). В MongoDB 8.0+ доступен режим **Config Shard**, когда узел одновременно выполняет роли config server и шарда (встроенный config server); классический dedicated config server — отдельная Replica Set. Команды переключения: `transitionFromDedicatedConfigServer`, `transitionToDedicatedConfigServer`.

**mongos (Router)** — легковесный прокси, который принимает запросы от приложений и направляет их к соответствующим шардам. Приложения подключаются к mongos, а не напрямую к шардам. Порт по умолчанию — 27017 (такой же, как и у mongod).

**Write Concern (WC)** — гарантия записи. Определяет условия, при которых запись считается успешной: подтверждение от Primary (w:1), большинства (w:majority), конкретного числа узлов (w:N).

**Read Preference (RP)** — политика чтения. Определяет, откуда клиент читает данные: primary, secondary, nearest, etc.

**Replica Set Protocol Version (pv)** — версия протокола репликации. Значение `1` (по умолчанию) — исходный протокол; `2` — modern protocol (MongoDB 4.0+, exhaust-режим). Проверяется через `rs.conf().protocolVersion` и переключается через `db.adminCommand({ replSetProtocolVersion: 1|2 })`.

**Transient Primary** — узел, временно выполняющий роль Primary во время выборов, но не имеющий подтверждённых записей с `w: "majority"`. Клиенты, подключенные к такому узлу, могут получить устаревшие данные; при реальном failover этот узел откатит неподтверждённые операции.

**maxStalenessSeconds** — максимальная допустимая устарелость данных при чтении с Secondary. Минимальное значение — 90 секунд. Определяет, какой Secondary может быть выбран для чтения: узел отклоняется, если клиент оценивает его лаг выше этого порога.

**Flow Control** — механизм, ограничивающий скорость записи на Primary для поддержания replication lag ниже порога `flowControlTargetLagSeconds` (по умолчанию ~0.5 с). По умолчанию включён (`enableFlowControl: true`).

---

## Предварительные требования

### Аппаратные требования

| Компонент | Минимальный | Рекомендуемый |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядер |
| **RAM** | 4 ГБ | 16+ ГБ (WiredTiger cache = 50% RAM) |
| **Диск** | 50 ГБ SSD | NVMe SSD (минимум 100 ГБ) |
| **Сеть** | 100 Мбит/с | 1 Гбит/с (между узлами Replica Set) |

### Программные требования

- **MongoDB Server** — версия 8.0+ (рекомендуется 8.0 LTS)
- **MongoDB Shell (mongosh)** — версия 2.0+
- **MongoDB Kubernetes Operator** — версия 2.0+ (для K8s)
- **NTP/Chrony** — синхронизация времени (дрейф < 100 мс)

### Сетевые требования

- Все узлы Replica Set должны иметь прямую сетевую связность
- Порты: `27017` (mongod / mongos), `27018` (mongod в роли shardsvr), `27019` (mongod в роли configsvr)
- Минимальная задержка между узлами: **< 10 мс** (в пределах одного дата-центра)

---

## Основные концепции

### Архитектура Replica Set

```
┌─────────────────────────────────────────────────────────────┐
│              Replica Set (rs0)                               │
├─────────────────────────────────────────────────────────────┤
│  Primary (Priority: 2)                                       │
│  - Принимает записи                                          │
│  - Фиксирует изменения в Oplog                               │
│                                                              │
│  Secondary 1 (Priority: 1)                                   │
│  - Реплицирует Oplog                                          │
│  - Может обслуживать read-запросы                            │
│                                                              │
│  Secondary 2 (Priority: 0, Hidden: true)                     │
│  - Реплицирует Oplog                                          │
│  - Не виден клиентам (аналитика, бэкапы)                     │
└─────────────────────────────────────────────────────────────┘
```

### Процесс failover

1. **Обнаружение:** Secondary не получают heartbeat от Primary в течение `electionTimeoutMillis` (по умолчанию 10 секунд)
2. **Выборы:** Оставшиеся узлы инициируют выборы нового Primary
3. **Голосование:** Узлы голосуют за кандидата с наиболее актуальным Oplog
4. **Промоушн:** Новый Primary начинает принимать записи
5. **Обновление клиентов:** Драйвер MongoDB автоматически обнаруживает нового Primary и перенаправляет write-запросы

**Время failover:** обычно **10-30 секунд** в зависимости от конфигурации и загрузки.

### Replica Set Protocol Version

MongoDB поддерживает два протокола репликации (определяются через `rs.conf().protocolVersion`):

| Протокол | Описание | Статус |
| :--- | :--- | :--- |
| **pv: 1** | Исходный протокол. Primary отправляет опросы Secondary, ожидая подтверждения. | Устаревший (deprecated) |
| **pv: 2** | Modern protocol. Использует exhaust-режим: Primary отправляет непрерывный поток Oplog-записей. Снижает латентность и риск потери данных при `w: 1` при failover. | Рекомендуется (по умолчанию с MongoDB 4.0+) |

**Переключение протокола:**
```javascript
// Проверить текущий протокол
rs.conf().protocolVersion  // → 1 или 2

// Переключить на modern protocol (только на Primary)
db.adminCommand({ replSetProtocolVersion: 2 })
```

**Важно:** Все узлы Replica Set должны использовать одинаковую версию протокола. При обновлении с pv:1 на pv:2 выполните rolling upgrade, убедившись, что все узлы совместимы.

### Flow Control

По умолчанию включён (`enableFlowControl: true`). Ограничивает скорость записи на Primary, чтобы поддерживать replication lag ниже `flowControlTargetLagSeconds` (по умолчанию ~0.5 секунды). Когда лаг приближается к порогу, writes получают "tickets" перед захватом блокировок. Отключается через `setParameter` или `mongod.conf`:
```yaml
# mongod.conf
replication:
  enableFlowControl: false
```

### Write Concern (WC)

| Уровень | Описание | Риск потери данных | Применение |
| :--- | :--- | :--- | :--- |
| **w: 1** | Подтверждение только от Primary | Высокий | Быстрые операции, не критичные данные |
| **w: majority** | Подтверждение от большинства узлов | Низкий | Стандарт для production |
| **w: N** | Подтверждение от N узлов | Зависит от N | Критичные операции |
| **w: 0** | Не ждать подтверждения | Максимальный | Bulk operations, не критичные |

**Рекомендация:** Используйте `w: "majority"` для всех критичных операций. Это гарантирует, что данные не потеряются при сбое Primary.

### Read Preference (RP)

| Режим | Описание | Задержка | Применение |
| :--- | :--- | :--- | :--- |
| **primary** | чтение только от Primary | Минимальная | Актуальные данные, транзакции |
| **primaryPreferred** | Primary, если доступен, иначе Secondary | Минимальная | Graceful degradation |
| **secondary** | Только от Secondary | Средняя | Аналитика, отчеты |
| **secondaryPreferred** | Secondary, если доступны, иначе Primary | Средняя | Аналитика с fallback |
| **nearest** | От ближайшего узла (по RTT) | Минимальная | Глобально распределенные кластеры |

**Важно:** При чтении от Secondary используйте `readConcern: "majority"` для гарантии актуальности данных.

**maxStalenessSeconds** — максимальная допустимая устарелость данных при чтении с Secondary. Минимальное значение — **90 секунд**. Определяет, какой Secondary может быть выбран для чтения: узел отклоняется, если клиент оценивает его лаг выше этого порога. Используется с `secondary`, `secondaryPreferred`, `nearest` и `primaryPreferred`.

```javascript
// чтение с Secondary, но не старше 2 минут
db.collection.find({}).readPref("secondary", {}, 120)
```

> **Hedged reads в MongoDB 8.0 — deprecated (устаревшие).** В версиях 4.4–7.0 режим `nearest` мог использовать hedged reads — драйвер отправлял одинаковый запрос на два узла и использовал ответ пришедший первым (снижал p99 latency в гео-распределённых кластерах). Начиная с MongoDB 8.0 hedged reads помечены как **deprecated**: по умолчанию запросы с `readPreference: "nearest"` больше не используют их. При явном указании hedged read MongoDB выполнит её и залогирует предупреждение; параметры `readHedgingMode` (драйверы) и `hedge` остаются доступны, но рекомендуются к удалению. Поддержка `hedge` будет полностью удалена в PyMongo 5.0. Если вы используете `readPreference: "nearest"` — в 8.0 это просто выбор ближайшего узла без дублирования запроса. Для снижения latency в гео-распределённых кластерах используйте правильное размещение шардов и `localLimitMS` в connection string. См. **[Connection Strings](./mongodb-connection-strings.md)**.

### Sharding для HA

Шардирование распределяет данные по нескольким Replica Sets, обеспечивая:
- **Горизонтальное масштабирование** — добавление шардов для ростаcapacity
- **HA на уровне данных** — отказ одного шарда не влияет на остальные
- **Гео-распределение** — размещение шардов в разных регионах

**Компоненты:**
1. **Shard** — Replica Set, хранящий часть данных
2. **Config Server** — Replica Set (3 узла), хранящий метаданные кластера
3. **mongos** — прокси, направляющий запросы к шардам

---

## Практические сценарии

### Сценарий 1: Создание Replica Set

```javascript
// Подключение к первому узлу
mongosh "mongodb://mongo-1:27017/?replicaSet=rs0"

// Инициализация Replica Set
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongo-1:27017", priority: 2 },
    { _id: 1, host: "mongo-2:27017", priority: 1 },
    { _id: 2, host: "mongo-3:27017", priority: 0, hidden: true }
  ]
})

// Проверка статуса
rs.status()
```

### Сценарий 2: Настройка Write Concern и Read Preference

```javascript
// Установка глобального Write Concern
db.setWriteConcern({ w: "majority", j: true, wtimeout: 5000 })

// Чтение с гарантией актуальности
db.collection.find({}).readConcern("majority")

// Настройка Read Preference для приложения
mongoose.connect("mongodb://mongo-1:27017,mongo-2:27017/production?replicaSet=rs0", {
  readPreference: "secondaryPreferred",
  readConcern: "majority"
})
```

### Сценарий 3: Создание Sharded Cluster (Dedicated Config Server)

**Порядок:** сначала config server replica set (CSRS), потом шарды, потом mongos.

```javascript
// На config server (3 узла, порт 27019 по умолчанию)
mongosh --host config-1:27019

// Инициализация config server replica set (обязательно configsvr: true)
rs.initiate({
  _id: "configRs",
  configsvr: true,
  members: [
    { _id: 0, host: "config-1:27019" },
    { _id: 1, host: "config-2:27019" },
    { _id: 2, host: "config-3:27019" }
  ]
})

// Запуск mongos (порт 27017, как у mongod)
mongos --configdb configRs/config-1:27019,config-2:27019,config-3:27019

// Добавление шардов (каждый шард — Replica Set)
sh.addShard("rs0/mongo-1:27017,mongo-2:27017,mongo-3:27017")
sh.addShard("rs1/mongo-4:27017,mongo-5:27017,mongo-6:27017")
```

**Для MongoDB 8.0+ — Config Shard (встроенный config server):** если кластер содержит ≤3 шарда, можно объединить config server с шардом в одной Replica Set, сократив количество узлов. Переключение между режимами без остановки кластера: `transitionFromDedicatedConfigServer` / `transitionToDedicatedConfigServer`. Подробности в **[Шардирование MongoDB](./mongodb-sharding.md)**.

### Сценарий 4: mongod.conf и Cluster Wide Write Concern (CWWC)

**mongod.conf** — основной конфигурационный файл. Роль узла задаётся секцией `sharding`:

```yaml
# mongod.conf — Shard server (шард)
storage:
  dbPath: /var/lib/mongodb/shard1
systemLog:
  destination: file
  path: /var/log/mongodb/mongod.log
  logAppend: true
net:
  port: 27018
  bindIp: 0.0.0.0
replication:
  replSetName: shard1
sharding:
  clusterRole: shardsvr

# mongod.conf — Config server (dedicated)
storage:
  dbPath: /var/lib/mongodb/config
net:
  port: 27019
replication:
  replSetName: configRs
sharding:
  clusterRole: configsvr

# mongod.conf — mongos (маршрутизатор)
net:
  port: 27017
sharding:
  configDB: configRs/config-1:27019,config-2:27019,config-3:27019
```

**Cluster Wide Write Concern (CWWC)** — mandatory since MongoDB 5.1+ for sharded clusters. Mongos polls config servers and applies CWWC to forwarded requests. If CWWC is unset and a shard's default write concern is `{ w: 1 }`, the shard **will not start** and `addShard` will fail. Minimum required value: `{ w: "majority" }`. Once set via `setDefaultRWConcern`, the write concern **cannot be unset** (MongoDB 5.0+). Sharding administrative commands (`addShard`, `enableSharding`) always use `w: "majority"` regardless of the configured global default, with a minimum `wtimeout` of 60000 ms.

```javascript
// Установка CWWC (выполняется от имени администратора через mongos)
db.adminCommand({ setDefaultRWConcern: 1, defaultWriteConcern: { w: "majority" } })
```

**Валидация:**
```bash
# Проверка, что CWWC установлен (helper-метод mongosh)
mongosh --host mongos-1:27017 --eval "db.getDefaultRWConcern()"
# → { defaultWriteConcern: { w: "majority" }, ... }
```

### Сценарий 5: Мониторинг состояния кластера

```javascript
// Проверка статуса Replica Set
rs.status()

// Проверка статуса репликации
rs.printSecondaryReplicationInfo()

// Проверка Oplog
db.getReplicationInfo()

// Проверка конфигурации (sharded cluster)
sh.status()
```

### Сценарий 6: Failover и восстановление

```javascript
// Принудительный failover (плановое переключение)
rs.stepDown(60)  # Отставка Primary на 60 секунд

// Проверка нового Primary
rs.isMaster()

// Принудительное переизбрание (если Primary недоступен)
rs.reconfig(config, { force: true })
```

**Валидация:**
```bash
# Проверка статуса после failover
mongosh --eval "rs.status()"
# → members[0].stateStr: "PRIMARY", остальные: "SECONDARY"

# Проверка oplog после восстановления
mongosh --eval "db.getReplicationInfo()"
# → logSizeMB: 2048, timeDiff: 86400

# Проверка протокола Replica Set (pv)
mongosh --eval "rs.conf().protocolVersion"
# → 2 (modern protocol)

# Проверка, что узел использует exhaust-режим репликации
mongosh --eval "db.serverStatus().repl"
```

### Сценарий 7: Проверка протокола Replica Set и modern protocol

**Проверка текущего протокола:**
```javascript
// Текущий протокол Replica Set
rs.conf().protocolVersion  // → 1 или 2

// Проверка, что все узлы используют одинаковый протокол
rs.status().members.forEach(m => print(m.host, m.protocolVersion))

// Проверка exhaust-режима на Secondary
db.serverStatus().repl
```

**Переключение на modern protocol (pv:2):**
```javascript
// Выполняется на Primary
db.adminCommand({ replSetProtocolVersion: 2 })
// → { ok: 1 }

// Проверка после переключения
rs.conf().protocolVersion  // → 2
```

**Важно:**
- Все узлы Replica Set должны использовать одинаковую версию протокола
- Переключение требует rolling upgrade: убедитесь, что все узлы совместимы с pv:2
- Modern protocol (pv:2) снижает replication lag и риск потери данных при `w: 1` failover
- Откат на pv:1 возможен через `db.adminCommand({ replSetProtocolVersion: 1 })`

### Сценарий 8: Диагностика выборов (Elections)

**Проверка состояния выборов:**
```javascript
// Проверка статуса Replica Set
rs.status()

// Проверка конфигурации (приоритеты, votes)
rs.conf()

// Проверка логов выборов
// mongod.log: grep -i "election" /var/log/mongodb/mongod.log

// Проверка, сколько узлов готово к выборам
rs.status().members.filter(m => m.stateStr === "SECONDARY" && m.priority > 0).length
```

**Типичные проблемы выборов:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Выборы не начинаются | `electionTimeoutMillis` слишком велико | Уменьшить до 10-15 сек |
| Выборы зависли | Нет кворума (нечётное число узлов) | Использовать 3 узла данных |
| Все Secondaries имеют `priority: 0` | Нет кандидатов на Primary | Установить `priority > 0` хотя бы одному Secondary |
| Выборы длятся долго | Низкая производительность Oplog | Оптимизировать диск и сеть |
| `replSetAbortPrimaryCatchUp` | Новый Primary долго догоняет Oplog | Принудительное завершение catchup |

### Сценарий 9: Мониторинг и алертинг Replica Set

**Ключевые метрики для мониторинга:**
- `rs.printSecondaryReplicationInfo()` — задержка репликации
- `db.serverStatus().wiredTiger.cache` — использование кэша
- `db.getReplicationInfo()` — размер и покрытие oplog

**Пример алертов (Prometheus + mongodb_exporter):**
```yaml
groups:
- name: mongodb_ha
  rules:
  - alert: MongoDBReplicationLag
    expr: mongodb_rs_optime_lag_seconds > 10
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Replication lag на {{ $labels.instance }}"
      description: "Задержка репликации {{ $value }}с"

  - alert: MongoDBPrimaryDown
    expr: mongodb_rs_members_state{state="1"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Нет PRIMARY в {{ $labels.replica_set }}"
      description: "Кворум потерян или выборы зависли"

  - alert: MongoDBOplogWindowTooSmall
    expr: mongodb_oplog_window_seconds < 3600
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Oplog Window < 1ч на {{ $labels.instance }}"
      description: "Вторичный узел не сможет отставать более 1 часа"
```

### Сценарий 10: Multi-region (гео-распределённое) развёртывание

Два паттерна: **cross-region Replica Set** (один RS в нескольких регионах) и **zone sharding** (шарды привязаны к регионам).

**Паттерн A: Cross-region Replica Set (3 региона)**

```javascript
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongo-eu-1:27017", priority: 2, tags: { region: "eu" } },
    { _id: 1, host: "mongo-us-1:27017", priority: 1, tags: { region: "us" } },
    { _id: 2, host: "mongo-ap-1:27017", priority: 0, hidden: true, tags: { region: "ap" } }
  ],
  settings: {
    electionTimeoutMillis: 30000,  // ↑ для cross-region (по умолчанию 10с)
    heartbeatIntervalMillis: 2000
  }
})
```

**Паттерн B: Zone sharding (данные привязаны к региону)**

```javascript
// 1. Добавить шарды в разных регионах
sh.addShard("rs-eu/eu-mongo-1:27017,eu-mongo-2:27017,eu-mongo-3:27017")
sh.addShard("rs-us/us-mongo-1:27017,us-mongo-2:27017,us-mongo-3:27017")

// 2. Создать зоны и привязать к шардам
sh.addShardToZone("rs-eu", "EU")
sh.addShardToZone("rs-us", "US")

// 3. Настроить shard key с полем региона
sh.shardCollection("sales_db.orders", { region: 1, _id: 1 })

// 4. Привязать диапазоны к зонам
sh.addTagRange("sales_db.orders", { region: "EU", _id: MinKey }, { region: "EU", _id: MaxKey }, "EU")
sh.addTagRange("sales_db.orders", { region: "US", _id: MinKey }, { region: "US", _id: MaxKey }, "US")

// 5. mongos в каждом регионе — приложение подключается к локальному mongos
```

**Read Preference для multi-region:**

```javascript
// Чтение с ближайшего узла (без hedged reads в 8.0)
mongoose.connect(uri, {
  readPreference: "nearest",
  localThresholdMS: 15  // окно выбора "ближайшего" (мс)
})

// Чтение с Secondary в конкретном регионе (через tags)
mongoose.connect(uri, {
  readPreference: "secondaryPreferred",
  readPreferenceTags: { region: "eu" }
})
```

**Валидация:**
```javascript
// Проверка зон
sh.status()
// # → shard rs-eu: zones: [ "EU" ], shard rs-us: zones: [ "US" ]

// Проверка размещения чанков
sh.getBalancerState()
// # → true

// Проверка latency между регионами
mongosh --host mongo-eu-1 --eval "db.adminCommand({ping: 1})"
```

**Таблица выбора паттерна:**

| Критерий | Cross-region RS | Zone sharding |
| :--- | :--- | :--- |
| Данные | Полная копия в каждом регионе | Данные разделены по регионам |
| RPO | Низкий (синхронная репликация majority) | Зависит от шарда |
| Write latency | Высокая (cross-region majority) | Низкая (локальный шард) |
| Failover | Автоматический (выборы) | Автоматический (внутри шарда) |
| Compliance (data residency) | Не удовлетворяет | Удовлетворяет (данные в регионе) |

### Сценарий 11: Плановое обслуживание с zero downtime

```bash
# 1. Проверка статуса перед обслуживанием
mongosh --eval "rs.status()"
# → Все члены healthy, PRIMARY активен

# 2. Перевод одного Secondary в maintenance mode (priority: 0)
mongosh --eval "cfg = rs.conf(); cfg.members[1].priority = 0; rs.reconfig(cfg)"
# → Узел не будет участвовать в выборах

# 3. Проведение обслуживания (обновление ОС, дисков и т.д.)

# 4. Возврат приоритета
mongosh --eval "cfg = rs.conf(); cfg.members[1].priority = 1; rs.reconfig(cfg)"
# → Узел снова participates в выборах

# 5. Проверка синхронизации
mongosh --eval "rs.printSecondaryReplicationInfo()"
# → secondaryLagSec: 0 (или близко к 0)
```

## Диагностика и устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Диагностические команды | Решение |
| :--- | :--- | :--- | :--- |
| **Replica Set не имеет Primary** | Потеря кворума, сетевые проблемы | `rs.status()` | Проверить доступность узлов, восстановить кворум |
| **Высокий Replica Lag** | Нехватка ресурсов, медленная сеть | `rs.printSecondaryReplicationInfo()`, `db.getReplicationInfo()` | Увеличить `oplogSize`, оптимизировать сеть |
| **Выборы лидера зависли** | Network Partition, медленные диски | `rs.status()` | Проверить сеть, увеличить `electionTimeoutMillis` |
| **Rollback после failover** | Primary упал до репликации данных | `rs.printReplicationInfo()` | Использовать `w: "majority"`, мониторить Oplog |
| **Oplog переполнен** | Secondary долго не доступен | `db.getReplicationInfo()` | Увеличить `oplogSize`, мониторить Oplog Window |
| **mongos не находит шарды** | Config server недоступен | `sh.status()` | Проверить connectivity к config server |
| **Чтение возвращает устаревшие данные** | Неправильный Read Preference | `db.getReadPref()` | Использовать `readConcern: "majority"` |
| **Split-Brain в Replica Set** | Потеря кворума при Partition | `rs.status()` | Восстановить кворум, перезапустить узел |
| **OOM при выполнении агрегаций** | WiredTiger cache превышает лимит RAM | `db.serverStatus().wiredTiger.cache` | Уменьшить `storage.wiredTiger.engineConfig.cacheSizeGB` |
| **Жесткий диск заполнен** | Логи или бекапы заполнили раздел | `db.serverStatus().oplog` | Настроить ротацию логов, увеличить диск или вынести бэкапы |
| **Сеть между Secondary и Primary нестабильна** | Пакетные потери или джиттер > 100мс | `ping`, `traceroute`, `rs.printSecondaryReplicationInfo()` | Проверить switch/route, увеличить `electionTimeoutMillis` |

## Справочник команд (Operations Reference)

| Команда / Действие | Описание |
| :--- | :--- |
| `rs.status()` | Проверка статуса Replica Set: состояние узлов, health, версия. |
| `rs.printSecondaryReplicationInfo()` | Задержка репликации (Replica Lag) по вторичным узлам. |
| `db.getReplicationInfo()` | Размер и временное покрытие Oplog. |
| `db.getReadPref()` | Текущая политика чтения (Read Preference). |
| `db.getSiblingDB("admin").aggregate([...])` | Диагностика текущих операций (stale config, blocking operations). |
| `sh.status()` | Статус шардированного кластера: шарды, балансировщик, версия. |
| `db.isdbgrid()` | Проверка: подключён ли клиент к mongos (sharded) или напрямую. |
| `rs.conf()` | Текущая конфигурация Replica Set (members, settings, votes). |
| `rs.reconfig(cfg, {force: true})` | Принудительное обновление конфигурации (только при недоступном Primary). |
| `rs.stepDown(seconds)` | Плановый отвод Primary (failover testing). |
| `rs.freeze(seconds)` | Заморозка узла для участия в выборах (обслуживание без потери кворума). |
| `db.setWriteConcern({w: "majority", j: true})` | Установка Write Concern для текущей сессии. |
| `db.setReadConcern("majority")` | Установка Read Concern для текущей сессии. |
| `db.serverStatus().wiredTiger.cache` | Проверка использования WiredTiger cache (bytes currently in cache). |
| `db.adminCommand({ replSetResizeOplog: 1, size: 50000 })` | Динамическое изменение размера Oplog (MongoDB 4.4+). |
| `db.adminCommand({ replSetMaintenance: 1|0 })` | Включение/выключение режима обслуживания (RECOVERING). |
| `db.adminCommand({ replSetAbortPrimaryCatchUp: 1 })` | Принудительное завершение catchup нового Primary. |
| `db.adminCommand({ replSetProtocolVersion: 1|2 })` | Переключение протокола Replica Set (pv:1 — устаревший, pv:2 — modern). |
| `db.adminCommand({ setDefaultRWConcern: 1, defaultWriteConcern: { w: "majority" } })` | Установка Cluster Wide Write Concern (CWWC). |
| `db.getDefaultRWConcern()` | Проверка текущего CWWC (helper-метод mongosh). |
| `db.adminCommand({ setFeatureCompatibilityVersion: "8.0" })` | Установка Feature Compatibility Version после обновления. |
| `db.hello()` | Проверка роли узла и состояния Replica Set (рекомендуется вместо устаревшего `rs.isMaster()`). |
| `rs.isMaster()` | Проверка, является ли узел Primary. **Устаревш** (deprecated), используйте `db.hello()`. |
| `rs.syncFrom(host)` | Принудительное изменение источника репликации для Secondary. |
| `db.serverStatus().repl` | Статус репликации: optimes, дата members, протокол. |
| `db.currentOp()` | Список выполняющихся операций в реальном времени. |
| `db.killOp(opId)` | Завершение длительной операции. |
| `db.fsyncLock()` / `db.fsyncUnlock()` | Блокировка/разблокировка записи для физического бэкапа. |
| `mongodump / mongorestore` | Логическое резервное копирование и восстановление. |
| `mongos --configdb ...` | Запуск mongos с указанием Config Server Replica Set. |
| `sh.getBalancerState()` | Проверка, включён ли балансировщик. |
| `sh.isBalancerRunning()` | Проверка, запущен ли балансировщик в данный момент. |
| `sh.stopBalancer()` / `sh.startBalancer()` | Остановка/запуск балансировщика. |

## Лучшие практики (Best Practices)

### Проектирование кластера
1. **Используйте 3 узла данных (без арбитров):** Арбитры — это крайняя мера для экономии ресурсов. 3 узла данных обеспечивают кворум и HA.

2. **Resource Limits и WiredTiger Cache:** Всегда задавайте `requests` и `limits` для CPU и памяти. WiredTiger cache должен быть установлен в 50% от лимита RAM пода. Без лимитов MongoDB займёт всю RAM хоста.

3. **Pod Anti-Affinity (Kubernetes):** Разносите поды по разным физическим узлам с `topologyKey: kubernetes.io/hostname`. Это защищает от одновременного отказа узла.

4. **StorageClass:** Используйте StorageClass с поддержкой `fsGroup`, `ReadWriteOnce`, и SSD-накопителями. Для production предпочитайте NVMe с IOPS > 5000.

### Операционная стабильность
5. **Используйте `w: "majority"`:** Гарантирует, что данные не потеряются при сбое. Для критичных операций добавляйте `j: true` (journal).

6. **Мониторинг Oplog Window:** Oplog должен позволять Secondary находиться в офлайне не менее 24 часов. Размер по умолчанию — 5% свободного места диска. Для production рекомендуется ручная установка `oplogSizeMB`.

7. **Настройка алертов:** Мониторите `rs.status()`, `replication lag`, `oplog window`, `state of members`. Пороги: `replica lag > 10s`, `oplog window < 1h`, `members state != PRIMARY/SECONDARY`.

8. **Тестирование failover:** Минимум раз в квартал выполняйте controlled failover: `rs.stepDown()`. Документируйте время переключения (RTO).

### Резервное копирование и восстановление
9. **Backup стратегия:** Используйте `mongodump` для логических бэкапов или снапшоты дисков для физических бэкапов. Тестируйте восстановление минимум раз в квартал. Храните бэкапы в отдельном namespace/кластере.

10. **Hidden/Delayed Secondary:** Для аналитики и бэкапов используйте скрытые и/или задержанные вторичные узлы. Это не влияет на производительность Primary.

### Безопасность и сеть
11. **Сетевая сегментация:** Порты 27017 (mongod / mongos), 27018 (shardsvr), 27019 (configsvr) должны быть открыты только внутри доверенного сегмента (VLAN/VPC). Запретить доступ из интернета.

12. **TLS/mTLS:** Включайте TLS для внутреннего трафика. Используйте cert-manager для автоматической ротации сертификатов.

13. **Аудит:** Включите `auditLog` в `additionalMongodConfig` для отслеживания всех операций доступа.

### Kubernetes-специфичные практики
14. **MongoDB Kubernetes Operator:** Для K8s используйте официальный Operator для автоматического управления Replica Sets и Sharded Clusters.

15. **Pod Disruption Budget:** Создайте PDB для обеспечения минимального количества готовых подов при плановых работах:
    ```yaml
    apiVersion: policy/v1
    kind: PodDisruptionBudget
    metadata:
      name: mongodb-pdb
    spec:
      minAvailable: 2
      selector:
        matchLabels:
          app: mongodb
    ```

16. **Readiness Probe:** Используйте кастомную readiness probe, проверяющую `rs.status()`. Стандартная TCP проверка может считаться успешной, пока узел не готов к приему writes.

### Отказоустойчивость
17. **Гео-распределение:** Для глобальных приложений размещайте узлы в разных регионах. Используйте `priority` для контроля, какой регион должен быть Primary.

18. **Избегайте арбитров в production:** Арбитры не хранят данные и не могут стать Primary. Используйте 3 узла данных вместо 2 + арбитр.

### Runbook и реагирование
19. **Документируйте процедуры:** Для каждого сценария (failover, restore, scale) должен быть пошаговый runbook. Храните его в Wiki или Git.

20. **On-call rotation:** Дежурный инженер должен иметь доступ ко всем компонентам кластера и знать процедуры escalation.

21. **Постмортем:** После каждого инцидента проводите анализ (postmortem) с фиксацией причин и мер по предотвращению рецидива.

22. **Chaos Engineering:** Регулярно тестируйте устойчивость кластера к отказам (kill pod, partition network, disk full). ИспользуйтеChaos Monkey или аналогичные инструменты.

---

## Граничные случаи и ограничения (Edge Cases)

- **Гео-распределенный кластер:** При задержке > 100 мс между регионами увеличийте `electionTimeoutMillis` до 20-30 секунд. Используйте асинхронную репликацию для cross-region.

- **Cross-region Write Concern:** `w: "majority"` в cross-region RS требует подтверждения от узлов в разных регионах — write latency = RTT до самого медленного узла majority. Для снижения latency: `w: 1` + `journal: true` (риск потери при сбое Primary) или размещение Primary в "главном" регионе с `priority`.

- **Zone sharding и балансировщик:** Balancer мигрирует чанки между шардами; при zone-ограничениях миграция только внутри зоны. Убедитесь, что `sh.getBalancerState()` = true и нет активных миграций (`sh.isBalancerRunning()`).

- **Hedged reads удалены (8.0):** В гео-распределённых кластерах `readPreference: "nearest"` выбирает ближайший узел без дублирования запроса. Для снижения p99 используйте `localThresholdMS` и размещение mongos в каждом регионе.

- **Oplog Window:** Secondary, который отстал больше чем Oplog Window, требует полной синхронизации (initial sync). Это может занять часы для больших баз.

- **Split-Brain при 2 узлах:** Группа из 2 узлов не может формировать кворум при потере одного узла. Используйте минимум 3 узла.

- **Write Concern и латентность:** `w: "majority"` добавляет задержку (один network hop). Для критичных операций это оправдано, для остальных — используйте `w: 1`.

- **Sharding и hotspots:** Неправильный выбор shard key приводит к неравномерному распределению данных. Используйте Highly-кардинальные ключи.

- **Rollback данных:** При сбое Primary, который не успел реплицировать данные, MongoDB может откатить изменения. Используйте `w: "majority"` для предотвращения.

- **MongoDB Operator:** Для K8s используйте официальный Operator. Он автоматически управляет Replica Sets, но требует понимания внутренней логики для troubleshooting.

- **Protocol Version mismatch:** Если узлы Replica Set используют разные протоколы (pv:1 и pv:2), репликация может работать некорректно. Все узлы должны иметь одинаковый `protocolVersion`. Проверяйте через `rs.conf().protocolVersion` и `rs.status().members[].protocolVersion`.

- **maxStalenessSeconds и lag:** При использовании `maxStalenessSeconds` с `secondary`/`nearest`, узел с лагом больше 90 секунд (минимум) отклоняется. Убедитесь, что `replication lag` стабильно ниже порога.

- **Transient Primary и откат:** В редких случаях два узла могут считать себя Primary. Только один сможет подтверждать `w: "majority"`. Клиенты, подключённые к "фантомному" Primary, могут получить устаревшие данные. При реальном failover этот узел откатит неподтверждённые операции (rollback).

- **CWWC и downgrade:** При понижении `featureCompatibilityVersion` с 4.4 до 4.2 все cluster-wide read/write concern defaults теряются. mongos может продолжать применять устаревшие настройки до 30 секунд.

- **Flow Control и high throughput:** При очень высокой нагрузке Flow Control может ограничивать throughput. Отключите его только если понимаете риски: `replication: enableFlowControl: false` в `mongod.conf`.

- **Protocol Version upgrade (pv:1 → pv:2):** Требует rolling upgrade. Убедитесь, что все узлы поддерживают pv:2 (MongoDB 4.0+). Проверьте совместимость драйверов: не все старые драйверы поддерживают modern protocol.

---

## Дополнительная информация

### Связь с другими концепциями

- **[Репликация MongoDB](./mongodb-replication.md)** — механизмы Replica Set, Oplog, Write Concern, Read Concern
- **[Шардирование MongoDB](./mongodb-sharding.md)** — распределение данных по шардам, Config Server
- **[MongoDB Kubernetes Operator](./mongodb_operator.md)** — автоматизация управления кластером в K8s
- **[Обзор High Availability](../../Concepts/High_Availability/ha_overview.md)** — RTO/RPO, Active-Active, Active-Passive
- **[Disaster Recovery](../../Concepts/disaster_recovery.md)** — стратегии DR, бэкапы, восстановление

### Полезные ссылки

- [MongoDB Replication](https://www.mongodb.com/docs/manual/replication/)
- [MongoDB Sharding](https://www.mongodb.com/docs/manual/sharding/)
- [MongoDB Kubernetes Operator](https://www.mongodb.com/docs/kubernetes-operator/stable/)
- [MongoDB Backup](https://www.mongodb.com/docs/manual/core/backups/)

### Чек-лист для MongoDB HA

- [ ] Replica Set имеет 3 узла данных (без арбитров)
- [ ] `w: "majority"` используется для критичных операций
- [ ] Настроен мониторинг: `rs.status()`, `replication lag`, `oplog window`
- [ ] Тестирован failover: `rs.stepDown()`
- [ ] Настроены алерты на потерю кворума и смену Primary
- [ ] Secondary используются для аналитики (read preference)
- [ ] Гео-распределение настроено (если требуется)
- [ ] Backup стратегия определена и протестирована
- [ ] Конфигурация хранится в Git
- [ ] Документированы процедуры восстановления
- [ ] Protocol Version установлен в pv:2 (modern protocol)
- [ ] Feature Compatibility Version обновлён до 8.0 после апгрейда
- [ ] Cluster Wide Write Concern (CWWC) установлен для шардированных кластеров
- [ ] maxStalenessSeconds настроен для чтения с Secondary (если используется)
- [ ] Flow Control включён (по умолчанию)
- [ ] Отключены устаревшие методы: `rs.isMaster()` → `db.hello()`, `getClusterWideWriteConcern` → `db.getDefaultRWConcern()`