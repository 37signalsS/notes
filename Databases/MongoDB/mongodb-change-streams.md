# MongoDB: Change Streams (Потоки изменений)

**Актуально для:** MongoDB 8.0.x

---

## Определения

**Change Streams** — механизм отслеживания изменений данных в реальном времени на уровне коллекции, базы данных или всего кластера. Предоставляет приложениям доступ к потоку событий через курсор, построенный поверх **Oplog** и **Resume Tokens**. Является стандартным инструментом для CDC (Change Data Capture), Event Sourcing и синхронизации с внешними системами.

*   **Change Stream:** Курсор, возвращающий последовательность событий изменений в порядке их применения.
*   **Event (Уведомление):** Один документ в потоке, описывающий конкретное изменение (insert, update, delete, replace, drop, invalidate).
*   **Resume Token:** Уникальный идентификатор позиции в потоке, содержащий Oplog timestamp и индекс записи. Позволяет возобновить чтение ровно с того места, где поток остановился.
*   **Cursor (Курсор):** Объект, возвращаемый методом `watch()`. Управляет подключением к Oplog и доставкой событий приложению.
*   **Pipeline:** Агрегационный конвейер, передаваемый в `watch()`, который фильтрует и трансформирует события на сервере перед отправкой клиенту.
*   **Oplog:** Первоисточник данных для Change Streams. Размер Oplog (`oplogSizeMB`) определяет максимальное расстояние назад для возобновления потока.
*   **Invalidate Event:** Событие типа `invalidate`, которое автоматически закрывает поток (например, при удалении коллекции, переименовании или падении Replica Set).
*   **Pre-image (Пред-образ):** Состояние документа до изменения. Записывается в `config.system.preimages` при включении `changeStreamPreAndPostImages`.
*   **Post-image (Пост-образ):** Состояние документа после изменения. Включается опцией `fullDocument` в `watch()`.
*   **Token Store (Хранилище токенов):** Внешнее хранилище (Redis, PostgreSQL, файловая система), куда приложение сохраняет последний Resume Token для возможности возобновления.
*   **Sharded Cluster Watch:** Наблюдение за всеми несистемными коллекциями во всех базах данных кластера через `Mongo().watch()`.
*   **Database Watch:** Наблюдение за всеми несистемными коллекциями одной базы данных через `db.watch()`.
*   **Collection Watch:** Наблюдение за изменениями одной коллекции через `db.collection.watch()`.
*   **Eventual Consistency (Eventual Consistency):** Гарантирует, что при правильном возобновлении по токену приложение в итоге получит все события, даже если временно теряло связь.
*   **Cursor Timeout (Таймаут курсора):** Бездействующий курсор Change Stream автоматически закрывается сервером. Время ожидания по умолчанию — 10 минут для `getMore`. Требует периодического опроса или увеличения `cursorTimeoutMillis`.
*   **Transaction Awareness:** Change Streams видит операции внутри транзакций только после фиксации (commit). При abort операции не появляются в потоке.

---

## Базовые концепции

### Архитектура Change Streams

```
Приложение → watch(pipeline, options) → Change Stream Cursor → Oplog (local.oplog.rs)
                                        ↓
                                    Resume Token ← _id события
                                        ↓
                                    Token Store (Redis/DB)
                                        ↓
                                    При перезапуске → resumeAfter(token)
```

**Уровни подписки:**

1.  **Collection:** `db.coll.watch(pipeline, options)` — наиболее частый сценарий. Видит изменения только в указанной коллекции.
2.  **Database:** `db.watch(pipeline, options)` — видит изменения во всех несистемных коллекциях базы данных. Не работает для `admin`, `local`, `config`.
3.  **Cluster:** `Mongo().watch(pipeline, options)` — глобальное наблюдение. Требует привилегий `clusterAdmin` или `anyAction` на кластере.

**Важно:** На уровне базы данных и кластера Change Streams не включает системные коллекции. Также исключаются изменения в `config`, `local`, `admin`.

### Жизненный цикл Change Stream

1.  **Создание курсора:** Приложение вызывает `watch()` с pipeline и options.
2.  **Чтение Oplog:** Сервер читает Oplog начиная с указанной позиции (начало или Resume Token).
3.  **Фильтрация:** Pipeline применяется к каждому событию. Не прошедшие фильтр события не отправляются клиенту.
4.  **Генерация токена:** Каждое событие содержит Resume Token в поле `_id`.
5.  **Передача события:** Событие отправляется клиенту.
6.  **Сохраниние токена:** Приложение сохраняет токен в надежное хранилие.
7.  **Повтор или пауза:** Приложение обрабатывает событие и запрашивает следующее.
8.  **Возобновление:** При перезапуске приложение передает `resumeAfter: <token>` и продолжает с того же места.
9.  **Закрытие:** Поток закрывается при `invalidate` событии, таймауте курсора или ошибке.

### Взаимодействие с другими подсистемами

| Подсистема | Взаимодействие с Change Streams |
| :--- | :--- |
| **Oplog** | Первоисточник данных. Change Streams читает Oplog напрямую. Размер Oplog определяет максимальное расстояние для возобновления. |
| **WiredTiger** | События Change Streams могут включать `fullDocument`, что требует чтения документа из кэша или диска (при `updateLookup`). |
| **Replica Set** | Change Streams работает на Primary. При failover поток может быть прерван. Resume Token позволяет возобновить на новом Primary. |
| **Sharding** | На шардированном кластере Change Streams через `mongos` агрегирует события со всех шардов. Порядок событий между шардами не гарантирован. |
| **Transactions** | Внутри транзакции операции видны в Change Stream только после commit. Aborted транзакции не генерируют событий. |
| **Pre-images** | При включении `changeStreamPreAndPostImages`, pre-images записываются в `config.system.preimages`. Это увеличивает нагрузку на запись. |

### Resume Token: структура и гарантии

Resume Token является BSON-документом, содержащим:
- `_data` (Binary): Внутренний идентификатор операции в Oplog.
- `clusterTime` (Timestamp): Логическое время кластера (Cluster Time) на момент события.
- `txnNumber` (Number): Номер транзакции, если операция была внутри транзакции.
- `lsid` (Binary): Идентификатор логической сессии.

**Гарантии Change Streams:**
- **Exactly-once delivery (at-least-once на практике):** При использовании Resume Token и идемпотентной обработки достигается семантика "ровно один раз".
- **Monotonic reads:** События доставляются в порядке их применения к Primary. При возобновлении по токену приложение не получит уже обработанные события.
- **No gaps:** При корректном сохранении токенов пропусков событий быть не должно.

### Change Streams и Pre/Post Images (MongoDB 6.0+)

**Pre-images (до версии 6.0 недоступны):**
- Включаются опцией `changeStreamPreAndPostImages: { enabled: true }` через `collMod`.
- Требуют места на диске (документы хранятся в `config.system.preimages`).
- Pre-image доступна для `update` и `delete` (если документ существовал до операции).
- Pre-image автоматически удаляется через TTL (configurable).

**Post-images:**
- Включаются опцией `fullDocument` в `watch()`.
- Значения: `"whenAvailable"` — возвращает пост-образ если доступен, `"required"` — возвращает всегда, иначе ошибка.
- Для `update` post-image может быть более новым, чем на момент события (при `updateLookup`).

---

## Практические сценарии

### 1. Включение Pre/Post Images для коллекции

```javascript
db.runCommand({
  collMod: "orders",
  changeStreamPreAndPostImages: { enabled: true }
})
// → { "ok" : 1 }
```

**Валидация:**
```javascript
db.getCollectionInfos({ name: "orders" })
// → проверка options.changeStreamPreAndPostImages.enabled: true
```

### 2. Надежный потребитель Change Streams (Node.js)

Пример с сохранением позиции, идемпотентностью и обработкой ошибок:

```javascript
async function watchOrders(collection, tokenStore) {
  const pipeline = [
    { $match: { "operationType": "insert", "fullDocument.status": "paid" } }
  ];

  let resumeToken = await tokenStore.getLastToken();
  const options = {
    resumeAfter: resumeToken,
    fullDocument: "whenAvailable",
    batchSize: 100
  };

  const changeStream = collection.watch(pipeline, options);

  changeStream.on("change", async (event) => {
    try {
      await processOrder(event);
      // Сохраняем токен ТОЛЬКО после успешной обработки
      await tokenStore.save(event._id);
    } catch (err) {
      console.error("Ошибка обработки:", err);
      // Приложение может повторить позже с тем же токеном
    }
  });

  changeStream.on("error", (err) => {
    console.error("Критическая ошибка потока:", err);
    // Пересоздание потока с последним сохраненным токеном
    changeStream.close();
    watchOrders(collection, tokenStore);
  });

  changeStream.on("close", () => {
    console.log("Поток закрыт");
  });
}
```

### 3. Возобновление после `invalidate` событий

После события `invalidate` (удаление коллекции, падение узла) поток закрывается. Используйте `startAfter` для создания нового потока:

```javascript
let cursor = db.orders.watch([], { fullDocument: "updateLookup" });

while (cursor.hasNext()) {
  let event = cursor.next();
  if (event.operationType === "invalidate") {
    let token = event._id;
    cursor.close();

    // Создаем новый поток после invalidate
    let newCursor = db.orders.watch(
      [],
      { startAfter: token, fullDocument: "updateLookup" }
    );
    // → Новый поток продолжает получать события
    break;
  }
}
```

**Различие `resumeAfter` и `startAfter`:**
- `resumeAfter`: Нельзя использовать после `invalidate`. Требует, чтобы Oplog еще содержал операцию по токену.
- `startAfter`: Можно использовать после `invalidate`. Создает новый поток, начиная с указанного токена.

### 4. Мониторинг Change Streams

```javascript
// Общая статистика WiredTiger и системная информация
db.serverStatus()
// → wiredTiger.cache, transactions, memory, connections

// Проверка Oplog Window
rs.printReplicationInfo()
// → logSizeMB, usedMB, timeDiff (секунды)

// Активные операции (включая change stream cursors)
db.currentOp({ "active": true, "secs_running": { "$gt": 30 } })
// → Поиск зависших или долгих операций

// Проверка pre-images
db.getSiblingDB("config").system.preimages.stats()
// → Количество pre-images, размер, использование диска

// Проверка токенов и их объема
db.getSiblingDB("config").system.preimages.find().count()
// → Количество pre-image записей
```

**SRE алерты для Change Streams:**
- Oplog Window < 1h — критично (Change Streams не смогут возобновить на старые токены).
- `wiredTiger.cache` usage > 90% — предупреждение (fullDocument updateLookup увеличивает нагрузку).
- Количество `config.system.preimages` растет без TTL очистки — предупреждение.
- Replica Set без PRIMARY — критично (Change Streams прерываются).

### 5. Change Streams в шардированном кластере

```javascript
// Подключение через mongos
const changeStream = mongos
  .db("shop_db")
  .collection("orders")
  .watch(pipeline, { fullDocument: "updateLookup" });

// Проверка, что кластер шардирован
mongos.getDBNames()
// → Список баз, включая shop_db

// Проверка статуса шардирования коллекции
sh.status()
// → shop_db.orders должен быть в списке распределенных коллекций
```

**Особенности шардированных кластеров:**
- `mongos` агрегирует события со всех шардов.
- Порядок событий между шардами не гарантирован.
- При добавлении шарда новые события появляются в потоке без перерыва.
- `StaleConfig` на `mongos` может временно нарушить поток. Обычно исправляется автоматически.

### 6. Интеграция с CDC-пайплайном

Пример минимального CDC-агента на Python:

```python
from pymongo import MongoClient

client = MongoClient("mongodb://mongo-1:27017,mongo-2:27017/?replicaSet=rs0")
db = client["shop_db"]
collection = db["orders"]

pipeline = [
  { "$match": { "operationType": { "$in": ["insert", "update", "delete"] } } }
]

with collection.watch(pipeline, fullDocument="whenAvailable") as stream:
  for event in stream:
    token = event["_id"]
    # Отправка события в очередь или напрямую в целевое хранилище
    process_event(event)

    # Сохранение токена в надежное хранилие
    save_token(token)
```

### 7. Влияние Rolling Upgrade на Change Streams

```bash
# Перед upgrade: убедитесь, что все потребители сохранили токены
mongosh --eval "rs.printSecondaryReplicationInfo()"
# → secondaryLagSec должен быть 0

# Обновляйте узлы последовательно, начиная с Secondary
systemctl stop mongod
yum update mongodb-org
systemctl start mongod

# После upgrade всех узлов и проверки стабильности — переключите FCV
mongosh --eval "db.adminCommand({ setFeatureCompatibilityVersion: '8.0' })"
```

**Важно:** Потребители Change Streams будут возобновлять работу с последнего сохраненного токена. Если Oplog Window покрывает время upgrade — данных не потеряется.

### 8. Обработка больших событий (8.0+)

```javascript
// $changeStreamSplitLargeEvent разбивает события, превышающие 16MB BSON
pipeline = [
  { "$changeStreamSplitLargeEvent": {} },
  { "$match": { "operationType": "update" } }
];

db.large_collection.watch(pipeline, { fullDocument: "whenAvailable" })
// → Каждое большое событие приходит фрагментами
```

**Примечание:** Фрагменты одного события могут доставляться в разных батчах. Приложение должно собирать их по общему идентификатору события.

### 9. Стратегии хранения Resume Tokens

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Redis** | Быстрое ключ-значение хранилище. Подходит для высоконагруженных потребителей. | Микросервисы, высокий throughput |
| **PostgreSQL** | Реляционная БД для хранения токенов с историей. | Enterprise-системы, аудит |
| **Файловая система** | Локальный файл или NFS. | Отдельный инстанс, низкая нагрузка |
| **MongoDB** | Хранение токенов в специальной коллекции. | Простота, но требует отдельного механизма |

### 10. Тестирование восстановления после сбоя

```bash
# Симуляция падения приложения
pkill -f "node change-stream-consumer.js"

# Проверка последнего токена в хранилище
redis-cli GET "change-stream:orders:last_token"
# → Должен вернуть сохраненный BSON токен

# Перезапуск приложения
node change-stream-consumer.js
# → Должно возобновить с сохраненного токена

# Проверка: нет ли пропущенных событий
# Сравните количество обработанных событий с количеством изменений в БД
mongosh --eval "db.orders.countDocuments()"
```

---

## Операции и команды

### Уровни наблюдения и методы

| Уровень / Метод | Описание |
| :--- | :--- |
| `db.collection.watch(pipeline, options)` | Наблюдение за коллекцией. Самый частый сценарий. |
| `db.watch(pipeline, options)` | Наблюдение за базой данных. Исключает системные коллекции. |
| `Mongo().watch(pipeline, options)` | Наблюдение за кластером. Требует `clusterAdmin`. |

### Опции `watch()`

| Опция | Тип | Значение по умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `resumeAfter` | document | — | Возобновляет поток после указанного Resume Token. Взаимоисключающее с `startAfter` и `startAtOperationTime`. |
| `startAfter` | document | — | Создает новый поток после указанного Resume Token. Поддерживает возобновление после `invalidate`. Взаимоисключающее с `resumeAfter` и `startAtOperationTime`. |
| `startAtOperationTime` | Timestamp | — | Начинает поток с указанного времени Cluster Time. Должно быть в пределах Oplog. Взаимоисключающее с `resumeAfter` и `startAfter`. |
| `fullDocument` | string | `"none"` | `"updateLookup"` — возвращает актуальный документ из БД. `"whenAvailable"` — возвращает пост-образ если доступен. `"required"` — возвращает пост-образ, иначе ошибка. |
| `fullDocumentBeforeChange` | string | `"none"` | `"whenAvailable"` — возвращает пред-образ если доступен. `"required"` — возвращает пред-образ, иначе ошибка. |
| `batchSize` | int | 101 / 16 MiB | Максимальное количество документов в батче. Уменьшение снижает latency, но увеличивает количество запросов. |
| `maxAwaitTimeMS` | int | `cursorTimeoutMillis` | Максимальное время ожидания следующего события. |

### Pipeline stages для Change Streams

Change Streams поддерживает ограниченный набор стадий агрегации:

| Стадия | Описание |
| :--- | :--- |
| `$match` | Фильтрация событий. Должна быть первой стадией для server-side фильтрации. |
| `$project` | Выбор полей из события. |
| `$addFields` | Добавление вычисляемых полей. |
| `$replaceRoot` / `$replaceWith` | Замена корневого документа. |
| `$redact` | Управление доступом к событиям. |
| `$set` | Обновление полей события. |
| `$unset` | Удаление полей из события. |
| `$changeStreamSplitLargeEvent` | Разбиение событий, превышающих 16MB BSON, на фрагменты (MongoDB 8.0+). |

### Системные коллекции Change Streams

| Коллекция | Назначение |
| :--- | :--- |
| `config.system.preimages` | Хранит pre-images документов при включенном `changeStreamPreAndPostImages`. Требует мониторинга размера и TTL очистки. |
| `local.oplog.rs` | Oplog, откуда Change Streams читает изменения. |

---

## Устранение неполадок

### Runbook: Resume Token устарел (ChangeStreamHistoryLost)

**Ситуация:** Resume Token старше самой ранней записи в Oplog. Change Stream не может возобновить работу.

**Шаги:**
1. Проверьте Oplog Window:
   ```bash
   mongosh --eval "rs.printReplicationInfo()"
   # → timeDiff должен покрывать время с момента последнего сохраненного токена
   ```
2. Если Oplog Window слишком мал — увеличьте размер Oplog:
   ```javascript
   db.adminCommand({ replSetResizeOplog: 1, size: 50000 })
   # → Размер в МБ. Рекомендуется минимум 24 часа изменений.
   ```
3. Если данные не потеряны — начните новый Change Stream с момента earliest Oplog:
   ```javascript
   db.collection.watch(pipeline, {
     startAtOperationTime: new Timestamp(1609459200, 1)
   })
   ```
4. Если данные могли быть утеряны — выполните полную синхронизацию с бэкапа.

### Runbook: Поток закрывается после `invalidate`

**Ситуация:** Change Stream получает событие `invalidate` и закрывается.

**Шаги:**
1. Определите причину `invalidate`:
   ```bash
   mongosh --eval "rs.status()"
   # → Проверка состояния Replica Set

   mongosh --eval "db.getCollectionInfos()"
   # → Проверка, существует ли коллекция
   ```
2. Если коллекция удалена — пересоздайте и начните новый поток.
3. Если коллекция существует — используйте `startAfter` для возобновления:
   ```javascript
   db.collection.watch(pipeline, {
     startAfter: lastInvalidateToken,
     fullDocument: "whenAvailable"
   })
   ```
4. Проверьте права доступа: убедитесь, что пользователь имеет привилегию `find` на коллекции.

### Runbook: События не доставляются

**Ситуация:** Change Stream создан, но события не поступают.

**Шаги:**
1. Проверьте статус Replica Set:
   ```bash
   mongosh --eval "rs.status()"
   # → Нет ли PRIMARY? Нет ли разбиения?
   ```
2. Проверьте права доступа:
   ```bash
   mongosh --eval "db.runCommand({ connectionStatus: 1 })"
   # → authenticatedRoles должен включать changeStream привилегии
   ```
3. Проверьте Oplog Window:
   ```bash
   mongosh --eval "rs.printReplicationInfo()"
   # → Если коллекция пустая или Oplog пустой — нет событий
   ```
4. Проверьте pipeline: убедитесь, что фильтр не исключает все события.
5. Проверьте, что изменения действительно происходят:
   ```bash
   mongosh --eval "db.collection.find().count()"
   # → Если 0 — нет данных для отслеживания
   ```

### Runbook: Высокая задержка событий

**Ситуация:** События доставляются с задержкой более 1 секунды.

**Шаги:**
1. Проверьте задержку репликации:
   ```bash
   mongosh --eval "rs.printSecondaryReplicationInfo()"
   # → secondaryLagSec должен быть 0
   ```
2. Проверьте нагрузку на Primary:
   ```bash
   mongostat --host rs0/primary:27017
   # → qr, qw, % locked
   ```
3. Проверьте размер батча:
   ```javascript
   // Уменьшите batchSize для снижения задержки
   db.collection.watch(pipeline, { batchSize: 10 })
   ```
4. Проверьте, что pipeline не содержит тяжелых операций:
   ```javascript
   // Используйте простейший $match на сервере
   ```
5. Проверьте сеть между потребителем и кластером:
   ```bash
   ping primary-host
   mtr --tcp --port 27017 primary-host
   ```

### Runbook: `fullDocument: "updateLookup"` возвращает null

**Ситуация:** При использовании `updateLookup` поле `fullDocument` равно `null` для операций `delete` или быстрых последовательных `update`.

**Решение:**
1. Переключитесь на Pre/Post Images:
   ```javascript
   db.runCommand({
     collMod: "collection_name",
     changeStreamPreAndPostImages: { enabled: true }
   })
   ```
2. Используйте `fullDocument: "whenAvailable"` и `fullDocumentBeforeChange: "whenAvailable"`:
   ```javascript
   db.collection.watch(pipeline, {
     fullDocument: "whenAvailable",
     fullDocumentBeforeChange: "whenAvailable"
   })
   ```
3. Это гарантирует, что событие всегда содержит `fullDocument` (или `fullDocumentBeforeChange`), даже при удалении документа.

### Runbook: Рост `config.system.preimages`

**Ситуация:** Размер `config.system.preimages` растет, места на диске не хватает.

**Шаги:**
1. Проверьте размер pre-images:
   ```bash
   mongosh --eval "db.getSiblingDB('config').system.preimages.stats()"
   # → dataSize, count
   ```
2. Проверьте TTL индекс:
   ```bash
   mongosh --eval "db.getSiblingDB('config').system.preimages.getIndexes()"
   # → Должен быть TTL индекс на expireAt
   ```
3. Если TTL не настроен — настройте:
   ```javascript
   db.getSiblingDB("config").system.preimages.createIndex(
     { expireAt: 1 },
     { expireAfterSeconds: 0, background: true }
   )
   ```
4. Проверьте, что `changeStreamPreAndPostImages` включен только на необходимых коллекциях.

### Runbook: Change Stream прерывается при failover

**Ситуация:** Change Stream разрывается при падении Primary.

**Шаги:**
1. Приложение должно автоматически переподключиться с `resumeAfter`.
2. Проверьте, что Oplog Window покрывает время простоя:
   ```bash
   mongosh --eval "rs.printReplicationInfo()"
   ```
3. Если Oplog Window недостаточен — начните новый поток с текущего момента:
   ```javascript
   db.collection.watch(pipeline, {
     startAtOperationTime: new Timestamp(Date.now() / 1000, 0)
   })
   ```
4. Данные за период простоя потребуют повторной синхронизации или восстановления из бэкапа.

---

## Ограничения и особенности

### 1. Oplog Window и возобновление

Change Streams зависит от Oplog. Если Resume Token старше самой старой записи в Oplog — поток не сможет возобновить. Мониторьте `rs.printReplicationInfo().timeDiff`.

### 2. Получение `fullDocument` через `updateLookup`

При использовании `fullDocument: "updateLookup"` MongoDB выполняет дополнительный `find` на Primary для получения актуального документа. Это создает дополнительную нагрузку на чтение. Для высоконагруженных систем используйте Pre/Post Images.

### 3. Sharded Cluster: порядок событий

На шардированном кластере события от разных шардов могут доставляться не в строгом порядке. Если порядок критичен — используйте `clusterTime` в событии для сортировки на стороне потребителя.

### 4. `invalidate` и невозможность `resumeAfter`

После события `invalidate` использовать `resumeAfter` нельзя. Требуется `startAfter` или полное пересоздание потока.

### 5. Пайплайн и Resume Token

При возобновлении потока с Resume Token используйте **тот же pipeline и те же опции**, что и при создании исходного потока. Изменение pipeline или options может привести к непредсказуемому поведению или потере событий.

### 6. Производительность и WiredTiger Cache

Change Streams увеличивает нагрузку на Primary:
- Чтение Oplog добавляет I/O.
- `updateLookup` и Pre/Post Images добавляют чтение документов.
- Pipeline с `$match` на сервере снижает нагрузку (server-side filtering).

### 7. Change Streams и Initial Sync

При добавлении нового узла в Replica Set и запуске initial sync, Oplog на целевом узле усекается. Это не влияет на Change Streams на Primary, но если потребитель был подключен к узлу, который стал Secondary — поток будет прерван.

### 8. Change Streams и FCV

Изменение FCV может влиять на доступность определенных функций Change Streams (например, `$changeStreamSplitLargeEvent` доступен только при FCV 8.0).

### 9. Жизненный цикл курсора

Бездействующий курсор Change Stream автоматически закрывается после таймаута (по умолчанию 10 минут). Приложение должно опрашивать поток хотя бы раз в несколько минут или использовать `no_cursor_timeout` (если поддерживается драйвером).

### 10. Pre-images и диск

Pre-images хранятся в `config.system.preimages`. При высокой нагрузке на обновления/удаления размер этой коллекции может расти быстро. Обеспечьте TTL и мониторинг.

---

## Лучшие практики (SRE)

### Надежность и возобновляемость

1.  **Всегда сохраняйте Resume Token:** Токен должен сохраняться в надежное хранилище только после успешной обработки события. Никогда не сохраняйте до обработки.
2.  **Используйте `startAfter` для `invalidate`:** После закрытия потока используйте `startAfter`, а не `resumeAfter`. Это позволяет возобновить после любого события, включая `invalidate`.
3.  **Идемпотентность:** Обработка событий должна быть идемпотентной. Используйте уникальные идентификаторы операций (`lsid`, `txnNumber`, `clusterTime`) для дедупликации.
4.  **Тот же pipeline и options:** При возобновлении потока используйте идентичный pipeline и опции. Изменение filter или `fullDocument` может привести к потере событий.
5.  **Обработка ошибок:** Реализуйте экспоненциальный backoff при ошибках сети. Ограничьте количество попыток, чтобы избежать thundering herd.

### Производительность

6.  **Server-side filtering:** Передавайте `pipeline` прямо в `watch()`. Это снижает нагрузку на сеть и WiredTiger Cache.
7.  **Минимизируйте `fullDocument`:** Если вам не нужны полные документы — не используйте `fullDocument: "updateLookup"`. Для post-images используйте Pre/Post Images с `"whenAvailable"`.
8.  **Batch Size:** Подбирайте `batchSize` под workload. Для low-latency систем уменьшайте до 10-50. Для high-throughput можно увеличить до 500-1000.
9.  **Мониторинг pre-images:** Отслеживайте размер `config.system.preimages`. Убедитесь, что TTL работает. Если pre-images не нужны — отключите `changeStreamPreAndPostImages`.

### Мониторинг и алертинг

10. **Ключевые метрики:**
    *   Oplog Window (`rs.printReplicationInfo().timeDiff`) — минимум 24 часа.
    *   Количество pre-images (`db.getSiblingDB("config").system.preimages.count()`).
    *   Задержка репликации (`rs.printSecondaryReplicationInfo()`).
    *   WiredTiger Cache usage (`db.serverStatus().wiredTiger.cache`).
    *   Количество активных Change Stream cursors (`db.currentOp()` с фильтром по `command.aggregate` и `pipeline.$changeStream`).
11. **Алерты:**
    *   Replica Set без PRIMARY — критично.
    *   Oplog Window < 1h — критично.
    *   WiredTiger Cache > 90% — предупреждение.
    *   `config.system.preimages` растет без TTL очистки — предупреждение.
    *   Change Stream курсор активен > 24h без изменений — предупреждение.

### Безопасность

12. **RBAC:** Для `db.collection.watch()` требуется роль с привилегией `find` на коллекции и `changeStream` на уровне БД. Для `db.watch()` — `changeStream` на БД. Для `Mongo().watch()` — `clusterAdmin` или `anyAction`.
13. **Мониторинг токенов:** Resume Tokens содержат sensitive данные о временных метках и сессиях. Не храните их в открытом виде.
14. **Аудит:** В Enterprise Edition настройте Audit Log для отслеживания создания Change Streams и доступа к данным.

---

## Гранicные случаи

### 1. `fullDocument: "updateLookup"` и быстрые удаления

При быстром удалении документа сразу после `update`, `updateLookup` может вернуть `null`. Это происходит, потому что find на Primary не находит документ.

**Решение:** Используйте Pre/Post Images:
```javascript
db.runCommand({ collMod: "coll", changeStreamPreAndPostImages: { enabled: true } })
db.coll.watch(pipeline, { fullDocument: "whenAvailable", fullDocumentBeforeChange: "whenAvailable" })
```

### 2. Resume Token после `invalidate`

После события `invalidate` (удаление коллекции, переименование) поток закрывается. Resume Token этого события нельзя использовать с `resumeAfter`.

**Решение:** Используйте `startAfter`:
```javascript
db.new_collection.watch(pipeline, { startAfter: invalidateToken })
```

### 3. Change Streams на пустой коллекции

Change Stream создается успешно, но событий нет. При первой вставке событие приходит мгновенно.

**Решение:** Это нормальное поведение. Убедитесь, что приложение корректно обрабатывает отсутствие событий в начале работы.

### 4. Sharded Cluster: события из разных шардов

На шардированном кластере события могут доставляться не в строгом порядке Oplog timestamp между шардами.

**Решение:** Используйте `clusterTime` для сортировки на стороне потребителя, если порядок критичен.

### 5. Pre-images накапливаются без TTL

Если TTL индекс на `config.system.preimages` не создан — коллекция будет бесконечно расти.

**Решение:** Создайте TTL индекс:
```javascript
db.getSiblingDB("config").system.preimages.createIndex(
  { expireAt: 1 },
  { expireAfterSeconds: 0 }
)
```

### 6. Change Stream и Rolling Restart

При Rolling Upgrade Change Stream может быть прерван на несколько секунд при переходе Primary. Resume Token позволяет возобновить без потери данных.

**Решение:** Убедитесь, что Oplog Window покрывает максимальное время upgrade (обычно < 5 минут). При необходимости увеличьте Oplog перед началом работ.

### 7. `startAtOperationTime` и Oplog границы

`startAtOperationTime` требует, чтобы указанный Timestamp был в пределах Oplog. Если время слишком старое — поток не запустится.

**Решение:** Используйте `rs.printReplicationInfo()` для проверки временных границ Oplog. Для стартовой позиции используйте ближайшее доступное время.

### 8. Large Events и `$changeStreamSplitLargeEvent` (8.0+)

События, превышающие 16MB BSON (например, вставка большого документа), могут не помещаться в один батч.

**Решение:** Используйте `$changeStreamSplitLargeEvent`:
```javascript
db.collection.watch([
  { "$changeStreamSplitLargeEvent": {} },
  { "$match": { "operationType": "insert" } }
])
```
Приложение должно собирать фрагменты по идентификатору события.

### 9. Change Stream и транзакции

Изменения внутри транзакции видны в Change Stream только после commit. Aborted транзакции не генерируют событий. Это означает, что потребитель не увидит промежуточных состояний.

**Решение:** Это гарантированное поведение. Приложение не должно ожидать событий от aborted транзакций.

### 10. Курсор бездействует и таймаут

Курсор Change Stream автоматически закрывается после 10 минут бездействия. Приложение, которое не опрашивает поток в течение этого времени, потеряет курсор.

**Решение:** Регулярно опрашивайте поток. Используйте heartbeat или keepalive механизм. При длительном ожидания снижайте `maxAwaitTimeMS` до 30-60 секунд.

---

## Чистка и восстановление после инцидентов

### Восстановление после потери Resume Token

Если хранилище токенов потеряно или повреждено:
1. Определите момент времени последнего известного токена.
2. Используйте `startAtOperationTime` для создания нового потока:
   ```javascript
   db.collection.watch(pipeline, {
     startAtOperationTime: new Timestamp(1609459200, 1)
   })
   ```
3. Если данные за промежуток критичны — восстановите их из бэкапа.

### Очистка `config.system.preimages`

```bash
# Проверка размера pre-images
mongosh --eval "db.getSiblingDB('config').system.preimages.stats()"
# → dataSize, count

# Проверка TTL индекса
mongosh --eval "db.getSiblingDB('config').system.preimages.getIndexes()"
# → Должен быть TTL индекс на expireAt

# Ручная очистка (если TTL не настроен)
mongosh --eval "db.getSiblingDB('config').system.preimages.deleteMany({ expireAt: { $lt: new Date() } })"
# → Количество удаленных записей
```

### Проверка зависших Change Stream cursors

```javascript
// Поиск долгих change stream операций
db.currentOp({
  "active": true,
  "secs_running": { "$gt": 3600 },
  "command.aggregate": { $exists: true },
  "command.pipeline": { $elemMatch: { "$changeStream": { $exists: true } } }
})
// → Проверка, какие потоки зависли и почему
```

### Восстановление после сбоя `mongos` (шардированный кластер)

После перезапуска `mongos` Change Stream автоматически возобновляется при следующем запросе `getMore`. Если `mongos` потерял состояние — потребитель должен переподключиться.

```bash
# Проверка статуса mongos
mongosh --port 27017 --eval "db.isdbgrid()"
# → true

# Проверка routing table
mongosh --port 27017 --eval "db.getSiblingDB('config').databases.find()"
# → Список баз и коллекций

# Если routing table поврежден — перезапустите mongos
systemctl restart mongos
```

---

## Дополнительная информация

*   **[Общий обзор MongoDB](./mongodb.md)** — архитектура и Oplog.
*   **[Репликация в MongoDB](./mongodb-replication.md)** — Oplog, Oplog Window, FCV, Initial Sync, elections, Flow Control.
*   **[Высокая доступность](./high_availability.md)** — Replica Set, отказоустойчивость, Read Preference, Prometheus алерты.
*   **[Администрирование и обслуживание](./mongodb-administration.md)** — мониторинг, бэкапы, Rolling Upgrade, Oplog management.
*   **[Агрегация (Aggregation Framework)](./mongodb-aggregation.md)** — pipeline stages, explain(), query optimization.
*   **[Транзакции в MongoDB](./mongodb-transactions.md)** — ACID, snapshot isolation, abort, config.transactions.
*   **[Шардирование](./mongodb-sharding.md)** — mongos, CWWC, Config Shard, Stale Config, Range Deleter.
*   **[Безопасность](./mongodb-security.md)** — RBAC, привилегии для `watch()`, роли.
*   **[Индексы](./mongodb-indexes.md)** — ESR правило, explain(), покрытие индексов.
*   **[Решардинг (Live Resharding)](./mongodb-resharding.md)** — конфликты транзакций с Critical Section.
