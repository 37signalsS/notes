# MongoDB: Репликация

**Актуально для:** MongoDB 8.0.x

---

## Определения

**Репликация в MongoDB** — механизм асинхронного копирования данных между узлами Replica Set для обеспечения отказоустойчивости, избыточности и масштабирования чтения. Фундамент всех production-развертываний MongoDB.

*   **Replica Set (Набор реплик):** Группа инстансов `mongod`, хранящих идентичный набор данных. Минимальная рекомендуемая конфигурация — 3 узла данных (без арбитров).
*   **Primary (Лидер):** Единственный узел, принимающий операции записи. Все изменения фиксируются в Oplog. Может быть только один узел, способный подтверждать записи с `w: "majority"`.
*   **Secondary (Вторичный):** Узлы, копирующие Oplog лидера и применяющие изменения локально. Могут участвовать в выборах и обслуживать read-запросы в зависимости от `readPreference`.
*   **Arbiter (Арбитр):** Узел, который не хранит данные и не может стать Primary. Его единственная задача — участие в голосовании для обеспечения кворума. Используется только в крайних случаях для экономии ресурсов.
*   **Oplog (Operations Log):** Специальная capped-коллекция `local.oplog.rs`, хранящая историю всех изменений данных. Является фундаментом логической репликации.
*   **Quorum (Кворум):** Большинство голосующих узлов (`N/2 + 1`), необходимых для выбора Primary и подтверждения записей уровня `majority`.
*   **Initial Sync (Начальная синхронизация):** Процесс полной копии данных на новый узел при добавлении в Replica Set или при принудительном resync.
*   **Flow Control:** Механизм, ограничивающий скорость записи на Primary для поддержания replication lag ниже порогового значения.
*   **Mirrored Reads:** Функция, при которой Primary зеркалирует часть read-запросов на electable вторичные узлы для прогрева кэша перед возможным failover.

---

## Базовые концепции

### Архитектура Replica Set

```
┌─────────────────────────────────────────────────────────────┐
│              Replica Set (rs0)                               │
├─────────────────────────────────────────────────────────────┤
│  Primary (Priority: 2)                                       │
│  - Принимает записи                                          │
│  - Фиксирует изменения в Oplog                               │
│  - Отправляет heartbeats другим узлам                        │
│                                                              │
│  Secondary 1 (Priority: 1)                                   │
│  - Реплицирует Oplog от Primary или другого Secondary         │
│  - Может обслуживать read-запросы                            │
│                                                              │
│  Secondary 2 (Priority: 0, Hidden: true)                     │
│  - Реплицирует Oplog                                          │
│  - Не виден клиентам (аналитика, бэкапы)                     │
└─────────────────────────────────────────────────────────────┘
```

### Механизмы репликации

#### Heartbeats и обнаружение сбоев
Все узлы Replica Set обмениваются **heartbeats** каждые 2 секунды. Если Primary не получает heartbeat от узла в течение `electionTimeoutMillis` (по умолчанию 10 секунд), узел помечается как недоступный.

#### Выборы (Elections)
Когда Primary недоступен более `electionTimeoutMillis`, eligible Secondary инициируют выборы. Узлы голосуют за кандидата с наиболее актуальным Oplog. Медианное время выборов не превышает 12 секунд при стандартных настройках.

#### Streaming Replication
Начиная с MongoDB 4.4, репликация использует протокол **exhaust** — источник отправляет непрерывный поток записей Oplog. Это снижает латентность и риск потери данных при `w: 1` при failover. Отключить streaming можно параметром `oplogFetcherUsesExhaust: false`.

#### Многопоточная репликация
MongoDB применяет записи из Oplog параллельно, группируя их по document ID. Это обеспечивает порядок применения операций к одному документу, но позволяет распараллеливать применение к разным документам.

### Oplog: структура и управление

**Размещение:** `local.oplog.rs` на каждом узле Replica Set.

**Размер по умолчанию:** Для WiredTiger — 5% свободного места диска (минимум ~1 ГБ, максимум ~50 ГБ). Для точного расчета используйте формулу:

```
oplogSizeMB >= (объём изменений за 24ч) + (объём данных коллекции + индексов)
```

**Динамическое изменение размера:** Начиная с MongoDB 4.4, изменяйте размер Oplog без перезагрузки:

```javascript
db.adminCommand({ replSetResizeOplog: 1, size: 50000 }) // Размер в МБ
```

**Oplog Window:** Временной интервал между самой новой и самой старой записью в Oplog. Определяет, как долго Secondary может находиться в офлайне без полной пересинхронизации.

**Мониторинг Oplog Window:**
```javascript
db.getReplicationInfo()
// Возвращает: logSizeMB, usedMB, timeDiff (секунды)
```

**Важно:** При initial sync MongoDB усекает Oplog на целевом узле. Это может повлиять на Change Streams и другие процессы, зависящие от Oplog.

### Flow Control
По умолчанию включен (`enableFlowControl: true`). Ограничивает скорость записи на Primary, чтобы поддерживать replication lag ниже `flowControlTargetLagSeconds` (по умолчанию ~0.5 секунды). Когда лаг приближается к порогу, writes получают "tickets" перед захватом блокировок.

### Mirrored Reads
По умолчанию включен (`mirrorReads.samplingRate: 0.01`). Primary зеркалирует 1% поддерживаемых read-запросов (`find`, `count`, `distinct`, `findAndModify`, `update`) на electable вторичные узлы для прогрева кэша.

### Initial Sync Source Selection
Источник для initial sync выбирается по параметру `initialSyncSourceReadPreference` (задается при запуске `mongod`):
- `primaryPreferred` (по умолчанию для voting members): предпочитает Primary, при недоступности —Secondary
- `primary`: только Primary
- `secondary` / `secondaryPreferred`: только Secondary

При выборе источника выполняется два прохода по списку узлов с критериями: состояние PRIMARY/SECONDARY, доступность, отсутствие delay, близость по Oplog, совпадение настроек индексов и т.д.

### Типы вторичных узлов (Special Members)
1.  **Priority 0:** Узел не может стать Primary. Используется для резервных копий или в удаленных ЦОД.
2.  **Hidden (Скрытый):** Узел не виден клиентам и не может стать Primary. Идеален для аналитики или создания бэкапов через `mongodump`.
3.  **Delayed (Задержанный):** Узел реплицирует данные с фиксированной задержкой (например, 1 час). Защищает от человеческих ошибок (случайное удаление данных). *Всегда имеет Priority 0.*

### Write Concern (Гарантия записи)
Определяет условия, при которых запись считается успешной для приложения.

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **`w`** | `majority` (default) | Подтверждение, когда большинство голосующих узлов записали данные в Oplog. |
| **`w: 1`** | `1` | Подтверждение только от Primary. Риск потери при откате (Rollback). |
| **`j`** (journal) | `true` | Дожидаться записи в Journal на диске (гарантия устойчивости к сбою питания). |

### Read Concern (Уровень изоляции)
| Уровень | Гарантия |
| :--- | :--- |
| **`local`** | Возвращает последние данные с узла без гарантии их выживания при сплит-брейне. |
| **`majority`** | Гарантирует, что прочитанные данные уже подтверждены большинством и не будут откачены. |
| **`snapshot`** | Используется в многодокументных транзакциях для обеспечения согласованности снимка. |

---

## Практические сценарии

### 1. Развертывание Replica Set (3 узла данных)

Инициализация кластера из трех узлов через `mongosh`:

```javascript
rs.initiate({
  _id: "rs0",
  version: 1,
  members: [
    { _id: 0, host: "mongo-1:27017", priority: 2 },      // Предпочтительный лидер
    { _id: 1, host: "mongo-2:27017", priority: 1 },
    { _id: 2, host: "mongo-3:27017", priority: 1 }
  ]
})
```

**Валидация:**
```bash
mongosh --eval "rs.status()"
# → stateStr: "PRIMARY" у одного узла, "SECONDARY" у остальных
# → health: 1 у всех членов

mongosh --eval "rs.conf().members.forEach(m => print(m.host, m.priority))"
# → вывод конфигурации для проверки приоритетов
```

### 2. Добавление скрытого узла для аналитики

```javascript
rs.add({
  host: "mongo-analytics:27017",
  priority: 0,
  hidden: true,
  buildIndexes: true
})
```

**Валидация:**
```bash
mongosh --eval "rs.status().members.find(m => m.host.includes('analytics')).stateStr"
# → SECONDARY

mongosh --eval "db.getReadPref()"
# → primary (скрытый узел не виден клиентам)
```

### 3. Добавление задержанного узла (защита от человеческих ошибок)

```javascript
rs.add({
  host: "mongo-delayed:27017",
  priority: 0,
  hidden: true,
  secondaryDelaySecs: 3600  // Задержка 1 час
})
```

### 4. Настройка Write Concern и Read Concern по умолчанию

```javascript
// Глобальный Write Concern для текущей сессии
db.setWriteConcern({ w: "majority", j: true, wtimeout: 5000 })

// Read Concern для текущей сессии
db.setReadConcern("majority")

// Чтение с гарантией актуальности
db.collection.find({}).readConcern("majority")
```

### 5. Initial Sync (логический)

При добавлении нового узла MongoDB автоматически запускает initial sync. Для принудительного resync:

```bash
# Остановить mongod, удалить данные, запустить снова
systemctl stop mongod
rm -rf /var/lib/mongodb/*
systemctl start mongod
```

**Процесс логического initial sync:**
1. Клонирование всех баз данных (кроме `local`) с построением индексов параллельно
2. Применение записей Oplog, накопленных во время клонирования
3. Применение всех изменений для приведения данных к текущему состоянию

**Валидация initial sync:**
```bash
# Проверка состояния в процессе синхронизации
mongosh --eval "rs.status().members.find(m => m.host.includes('new')).stateStr"
# → STARTUP2 во время синхронизации, SECONDARY после завершения

# Проверка lag после завершения
mongosh --eval "rs.printSecondaryReplicationInfo()"
# → secondaryLagSec: 0 или близко к 0

# Проверка Oplog window
mongosh --eval "db.getReplicationInfo()"
# → timeDiff должен покрывать время с момента запуска initial sync
```

### 6. Initial Sync на Enterprise (file copy based)

Требуется MongoDB Enterprise. Включается параметром при запуске:

```bash
mongod --replication.replSetName rs0 --initialSyncMethod fileCopyBased
```

**Особенности:**
- Заменяет базу `local` на целевом узле
- Быстрее логической синхронизации для больших наборов данных
- Во время синхронизации нельзя делать бэкапы и писать в `local`
- Может привести к неточным counts без query predicate

### 7. Переконфигурация Replica Set (добавление/удаление членов)

```javascript
// Получить текущую конфигурацию
cfg = rs.conf()

// Добавить нового члена
cfg.members.push({ _id: 3, host: "mongo-4:27017", priority: 1 })
rs.reconfig(cfg)

// Удалить члена
cfg = rs.conf()
cfg.members = cfg.members.filter(m => m._id !== 3)
rs.reconfig(cfg)

// Изменить приоритет существующего члена
cfg = rs.conf()
cfg.members[1].priority = 2
rs.reconfig(cfg)
```

**Валидация:**
```bash
mongosh --eval "rs.status().members.forEach(m => print(m.host, m.stateStr, m.optimeDate))"
# → проверка статуса всех членов после reconfig
```

### 8. Принудительная переконфигурация (Force Reconfig)

Используется только когда Primary недоступен и кворум потерян. Требуется подключение к оставшемуся узлу:

```javascript
cfg = {
  _id: "rs0",
  version: 2,
  members: [
    { _id: 0, host: "mongo-1:27017", priority: 2 },
    { _id: 1, host: "mongo-2:27017", priority: 1 }
  ]
}
rs.reconfig(cfg, { force: true })
```

**Важно:** Force reconfig может изменить Default Write Concern. Убедитесь, что CWWC (default write concern) установлен до reconfig, или используйте `setDefaultRWConcern`.

**Валидация:**
```bash
mongosh --eval "rs.isMaster()"
# → Проверка, что узел считает себя PRIMARY

mongosh --eval "rs.status()"
# → Проверка состояния оставшихся членов
```

### 9. Плановое обслуживание (stepDown и freeze)

```javascript
// Перевод текущего Primary в Secondary на 60 секунд
rs.stepDown(60)

// Проверка нового Primary
rs.isMaster()

// Заморозка узла для обслуживания без потери кворума
rs.freeze(300)  // Не будет участвовать в выборах 5 минут
```

**Валидация:**
```bash
mongosh --eval "rs.status().members[0].stateStr"
# → PRIMARY (новый лидер)

mongosh --eval "rs.printSecondaryReplicationInfo()'
# → secondaryLagSec: 0 (или близко к 0)
```

### 10. Режим обслуживания (maintenance mode)

```javascript
// Включение maintenance mode (узел переходит в RECOVERING)
db.adminCommand({ replSetMaintenance: 1 })

// Выключение maintenance mode
db.adminCommand({ replSetMaintenance: 0 })
```

**Валидация:**
```bash
mongosh --eval "rs.status().members.find(m => m.host.includes('maintenance')).stateStr"
# → RECOVERING во время обслуживания, SECONDARY после выключения
```

### 11. Отмена выборов (abort catchup)

Если новый elected primary долго не завершает catchup:

```javascript
db.adminCommand({ replSetAbortPrimaryCatchUp: 1 })
```

---

## Операции и команды

| Команда / Действие | Описание |
| :--- | :--- |
| `rs.status()` | Проверка статуса Replica Set: состояние узлов, health, версия, optime. |
| `rs.conf()` | Текущая конфигурация Replica Set (members, settings, votes). |
| `rs.reconfig(cfg, {force: true})` | Принудительное обновление конфигурации (только при недоступном Primary). |
| `rs.initiate(cfg)` | Инициализация нового Replica Set. |
| `rs.add(hostConfig)` | Добавление нового члена в Replica Set. |
| `rs.remove(host)` | Удаление члена из Replica Set. |
| `rs.stepDown(seconds)` | Плановый отвод Primary (failover testing). |
| `rs.stepDown(seconds, {force: true})` | Принудительный stepDown (даже если есть Secondary с более высокой priority). |
| `rs.freeze(seconds)` | Заморозка узла для участия в выборах (обслуживание без потери кворума). |
| `rs.isMaster()` | Проверка, является ли узел Primary (deprecated, используйте `db.hello()`). |
| `db.hello()` | Проверка роли узла и состояния Replica Set. |
| `rs.printSecondaryReplicationInfo()` | Задержка репликации (Replica Lag) по вторичным узлам. |
| `rs.printReplicationInfo()` | Информация об Oplog с точки зрения Primary. |
| `db.getReplicationInfo()` | Размер и временное покрытие Oplog. |
| `db.getReadPref()` | Текущая политика чтения (Read Preference). |
| `db.setWriteConcern({w: "majority", j: true})` | Установка Write Concern для текущей сессии. |
| `db.setReadConcern("majority")` | Установка Read Concern для текущей сессии. |
| `db.serverStatus().wiredTiger.cache` | Проверка использования WiredTiger cache. |
| `db.serverStatus({ mirroredReads: 1 })` | Проверка метрик mirrored reads. |
| `db.serverStatus().repl` | Проверка статуса репликации: optimes, дата members. |
| `db.currentOp()` | Список выполняющихся операций в реальном времени. |
| `db.killOp(opId)` | Завершение длительной операции. |
| `db.fsyncLock()` | Блокировка записи для физического бэкапа. |
| `db.fsyncUnlock()` | Снятие блокировки записи. |
| `db.adminCommand({ replSetResizeOplog: 1, size: 50000 })` | Динамическое изменение размера Oplog. |
| `db.adminCommand({ replSetMaintenance: 1 })` | Включение режима обслуживания (RECOVERING). |
| `db.adminCommand({ replSetMaintenance: 0 })` | Выключение режима обслуживания. |
| `db.adminCommand({ replSetAbortPrimaryCatchUp: 1 })` | Принудительное завершение catchup нового Primary. |
| `db.adminCommand({ setDefaultRWConcern: { w: "majority", r: "majority" } })` | Установка Default Read/Write Concern для Replica Set. |
| `mongodump --oplog` | Логический бэкап с захватом Oplog для point-in-time recovery. |
| `mongorestore --oplogReplay` | Восстановление с применением Oplog. |

---

## Устранение неполадок

### Runbook: Force Reconfig при потере кворума

**Ситуация:** Большинство узлов недоступны, нет Primary, кворум потерян.

**Шаги:**
1. Подключитесь к оставшемуся доступному узлу:
   ```bash
   mongosh --host mongo-remaining:27017
   ```
2. Получите текущую конфигурацию и удалите недоступных членов:
   ```javascript
   cfg = rs.conf()
   cfg.members = cfg.members.filter(m => ["mongo-1:27017", "mongo-2:27017", "mongo-3:27017"].includes(m.host))
   cfg.version++
   rs.reconfig(cfg, { force: true })
   ```
3. Проверьте статус:
   ```bash
   mongosh --eval "rs.status()"
   # → Должен быть один PRIMARY, остальные (если есть) — SECONDARY
   ```
4. После восстановления недоступных узлов добавьте их обратно:
   ```javascript
   rs.add("mongo-1:27017")
   rs.add("mongo-2:27017")
   ```

**Предупреждение:** Force reconfig может изменить Default Write Concern. Установите его явно:
```javascript
db.adminCommand({ setDefaultRWConcern: { w: "majority", r: "majority" } })
```

### Runbook: Восстановление после failed initial sync

**Ситуация:** Secondary застрял в `STARTUP2`, initial sync падает с ошибкой.

**Шаги:**
1. Проверьте статус узла:
   ```bash
   mongosh --eval "rs.status().members.find(m => m.host.includes('stuck'))"
   # → stateStr: STARTUP2, might be "initial sync" in logs
   ```
2. Проверьте свободное место на диске (включая `local` базу):
   ```bash
   df -h /var/lib/mongodb
   # → Достаточно места для Oplog и данных
   ```
3. Проверьте сетевое подключение к источнику:
   ```bash
   nc -zv mongo-source 27017
   # → Должен быть доступен
   ```
4. При необходимости удалите данные и запустите заново:
   ```bash
   systemctl stop mongod
   rm -rf /var/lib/mongodb/*
   systemctl start mongod
   ```

### Runbook: Очистка файлов отката (Rollback)

**Ситуация:** После failover Primary откатил изменения, созданы файлы в `data/rollback/`.

**Шаги:**
1. Проверьте наличие файлов отката:
   ```bash
   ls -la /var/lib/mongodb/rollback/
   ```
2. Проанализируйте откатанные операции:
   ```bash
   mongorestore --dir /var/lib/mongodb/rollback/ --dryRun
   ```
3. Если данные нужны — примените их вручную или через `mongorestore`.
4. После анализа файлы отката можно удалить:
   ```bash
   rm -rf /var/lib/mongodb/rollback/*
   ```

### Runbook: Сетевой partition и split-brain

**Ситуация:** Два узла считают себя Primary (transient primary), кворум потерян.

**Шаги:**
1. Определите, какой узел имеет реальный кворум:
   ```bash
   mongosh --eval "rs.status().members.filter(m => m.stateStr === 'PRIMARY')"
   ```
2. Только узел с `majority` writes является настоящим Primary.
3. Отключите "фантомный" Primary (если он записывает данные, они будут откачены):
   ```bash
   # На фантомном Primary
   mongod --shutdown
   ```
4. Восстановите сетевую связность или перезапустите узел.

### Типичные проблемы и решения

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Secondary застрял в STARTUP2** | Failed initial sync, нет места на диске | `rs.status()`, логи mongod | Проверить `df -h`, сеть, при необходимости удалить данные и перезапустить |
| **Высокий Replica Lag** | Нехватка ресурсов, медленная сеть, включен `secondaryDelaySecs` | `rs.printSecondaryReplicationInfo()`, `db.getReplicationInfo()` | Увеличить `oplogSize`, оптимизировать сеть, проверить `secondaryDelaySecs` |
| **Бесконечные выборы** | Нестабильная сеть, отсутствие кворума | `rs.status()` | Проверить доступность узлов, увеличить `electionTimeoutMillis`, убедиться что количество голосующих узлов нечетное |
| **Rollback (Откат)** | Primary упал до репликации данных, подтвержденных с `w: 1` | Файлы в `data/rollback/` | Использовать `w: "majority"`. Проанализировать и применить файлы отката при необходимости. |
| **Oplog переполнен** | Secondary долго не доступен, oplog window слишком мал | `db.getReplicationInfo()` | Увеличить `oplogSize`, мониторить Oplog Window, убедиться что Secondary может догнать Primary |
| **Initial sync падает с ошибкой** | Недостаточно места в `local`, разрыв связи | Логи mongod, `rs.status()` | Проверить `df -h`, сетевую связность, увеличить `initialSyncTransientErrorRetryPeriodSeconds` |
| **Split-Brain** | Network partition, потеря кворума | `rs.status()` | Восстановить кворум, отключить фантомный Primary, проверить сеть |
| **Не удается force reconfig** | Primary все еще доступен, или CWWC мешает | Логи mongod | Использовать `setDefaultRWConcern` перед reconfig, убедиться что Primary действительно недоступен |

---

## Лучшие практики (SRE)

1.  **Используйте `majority`:** В MongoDB 8.0 это значение по умолчанию, не снижайте его без крайней необходимости. Для критичных операций добавляйте `j: true` (journal).
2.  **Следите за Oplog Window:** Размер Oplog должен позволять Secondary находиться в офлайне не менее 24-48 часов. Если окно падает до 1-2 часов — это критический риск потери данных.
3.  **Гео-распределение:** Размещайте узлы в разных зонах доступности. Используйте `priority` для контроля, какой регион должен быть основным. При задержке > 100 мс между регионами увеличивайте `electionTimeoutMillis` до 20-30 секунд.
4.  **Минимальное количество:** Для полноценной работы всегда используйте минимум 3 узла данных. Арбитры — это крайняя мера для экономии ресурсов.
5.  **Фиксируйте версии:** Используйте `apt-mark hold mongodb-org` (Ubuntu) или `yum versionlock mongodb-org` (RHEL).
6.  **Динамический Oplog:** Начиная с v4.4, изменяйте размер Oplog без перезагрузки через `replSetResizeOplog`.
7.  **Тестирование failover:** Минимум раз в квартал выполняйте controlled failover: `rs.stepDown()`. Документируйте время переключения (RTO).
8.  **Flow Control:** Оставляйте включенным (`enableFlowControl: true`). Он автоматически ограничивает скорость записи для поддержания лага на низком уровне.
9.  **Initial Sync планирование:** Выполняйте initial sync в периоды низкой нагрузки. Убедитесь, что Oplog Window покрывает время синхронизации.
10. **Backup стратегия:** Используйте `mongodump --oplog` для логических бэкапов. Храните бэкапы отдельно от кластера.
11. **Сетевая сегментация:** Порты 27017 (mongod), 27018 (mongos), 27019 (configsvr) должны быть открыты только внутри доверенного сегмента (VLAN). Запретить доступ из интернета.
12. **TLS:** Включайте TLS для внутреннего трафика репликации.
13. **Runbook:** Для каждого сценария (failover, restore, force reconfig, initial sync failure) должен быть пошаговый runbook.
14. **Разделение прав:** Используйте `keyFile` только для внутренней связи, а для администрирования — выделенных пользователей с RBAC.
15. **Версионность FCV:** После Rolling Upgrade установите Feature Compatibility Version:
    ```javascript
    db.adminCommand({ setFeatureCompatibilityVersion: "8.0" })
    ```

---

## Граничные случаи и ограничения

*   **Гео-распределенный кластер:** При задержке > 100 мс между регионами увеличивайте `electionTimeoutMillis` до 20-30 секунд. Учитывайте, что `w: "majority"` может требовать подтверждения от удаленного узла.
*   **Oplog Window и Initial Sync:** Secondary, который отстал больше чем Oplog Window, требует полной синхронизации. Это может занять часы для больших баз. Планируйте maintenance с учетом размера Oplog.
*   **Split-Brain при 2 узлах:** Группа из 2 узлов не может формировать кворум при потере одного узла. Используйте минимум 3 узла.
*   **Write Concern и латентность:** `w: "majority"` добавляет задержку (один network hop). Для критичных операций это оправдано, для остальных — используйте `w: 1` с пониманием рисков.
*   **Rollback данных:** При сбое Primary, который не успел реплицировать данные, MongoDB может откатить изменения. Используйте `w: "majority"` для предотвращения.
*   **Initial Sync на NVMe:** На кластерах с NVMe initial sync занимает больше времени и создает повышенную нагрузку на Primary. Выполняйте в периоды низкой нагрузки.
*   **File Copy Based Initial Sync:** Доступен только в MongoDB Enterprise. Может привести к неточным counts без query predicate.
*   **Delayed Member edge cases:** Delayed member всегда имеет Priority 0 и не может стать Primary. Убедитесь, что `secondaryDelaySecs` меньше Oplog Window.
*   **Арбитры:** Не хранят данные и не могут стать Primary. При сбое двух узлов (2 данных + 1 арбитр) кластер теряет кворум. Используйте 3 узла данных вместо 2 + арбитр в production.
*   **Transient Primary:** В редких случаях два узла могут считать себя Primary, но только один сможет подтверждать `w: "majority"`. Клиенты, подключенные к "фантомному" Primary, могут получить устаревшие данные.
*   **Сброс Oplog при initial sync:** На целевом узле Oplog усекается во время initial sync. Это влияет на Change Streams. Убедитесь, что Change Streams не критичны во время добавления новых узлов.

---

## Чистка и восстановление после инцидентов

### Очистка после неудачного initial sync
```bash
# Остановка узла
systemctl stop mongod

# Удаление частичных данных
rm -rf /var/lib/mongodb/*

# Проверка диска перед перезапуском
df -h /var/lib/mongodb
# → Минимум 20% свободного места сверх размера данных

# Перезапуск
systemctl start mongod

# Проверка статуса
mongosh --eval "rs.status()"
```

### Очистка файлов отката (Rollback)
```bash
# Проверка наличия
ls -la /var/lib/mongodb/rollback/

# Анализ содержимого
mongorestore --dir /var/lib/mongodb/rollback/ --dryRun

# Удаление после подтверждения
rm -rf /var/lib/mongodb/rollback/*
```

### Восстановление кворума
```bash
# Подключение к оставшемуся узлу
mongosh --host surviving-node:27017

# Force reconfig с оставшимися узлами
cfg = rs.conf()
cfg.members = cfg.members.filter(m => reachable_hosts.includes(m.host))
cfg.version++
rs.reconfig(cfg, { force: true })

# Проверка
mongosh --eval "rs.status()"
```

---

## Дополнительная информация

*   **[Общий обзор MongoDB](./mongodb.md)** — архитектура и WiredTiger.
*   **[Моделирование данных](./mongodb-modeling.md)** — Embedding vs Referencing, валидация схем.
*   **[Высокая доступность MongoDB](./high_availability.md)** — детальный разбор HA архитектур, Write Concern, Read Preference, Prometheus алерты, Kubernetes практики.
*   **[Транзакции в MongoDB](./mongodb-transactions.md)** — использование репликации для ACID.
*   **[Change Streams](./mongodb-change-streams.md)** — отслеживание изменений через Oplog.
*   **[Шардирование](./mongodb-sharding.md)** — объединение Replica Sets в горизонтальный кластер.
*   **[Администрирование](./mongodb-administration.md)** — бэкапы и обновление версий.
*   **[Установка на Ubuntu](./installation_ubuntu.md)** — пошаговый процесс деплоя.
*   [MongoDB Replication](https://www.mongodb.com/docs/v8.0/replication/)
*   [MongoDB Oplog](https://www.mongodb.com/docs/v8.0/core/replica-set-oplog/)
*   [MongoDB Initial Sync](https://www.mongodb.com/docs/v8.0/core/replica-set-sync/)
*   [MongoDB Elections](https://www.mongodb.com/docs/v8.0/core/replica-set-elections/)
*   [MongoDB Rollbacks](https://www.mongodb.com/docs/v8.0/core/replica-set-rollbacks/)

---

## Справочник состояний членов Replica Set

| State | Строка состояния | Описание |
| :--- | :--- | :--- |
| 0 | STARTUP | Начальное состояние, не завершена инициализация. |
| 1 | PRIMARY | Узел является Primary, принимает записи. |
| 2 | SECONDARY | Узел реплицирует данные, может обслуживать reads. |
| 3 | RECOVERING | Узел восстанавливается (например, maintenance mode). |
| 5 | STARTUP2 | Initial sync или применение конфигурации. |
| 6 | UNKNOWN | Узел недоступен для связи. |
| 7 | ARBITER | Узел является арбитром. |
| 8 | DOWN | Узел считается недоступным. |
| 9 | ROLLBACK | Узел выполняет откат изменений. |
| 10 | REMOVED | Узел удален из Replica Set. |
