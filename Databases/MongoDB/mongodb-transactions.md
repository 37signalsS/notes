# MongoDB: Транзакции и согласованность

**Актуально для:** MongoDB 8.0.x

---

## Определения

**Транзакции в MongoDB** обеспечивают выполнение набора операций над документами в нескольких коллекциях или базах данных с соблюдением принципов ACID (Atomicity, Consistency, Isolation, Durability).

*   **ACID:** Атомарность (все или ничего), Согласованность (переход из одного валидного состояния в другое), Изоляция (транзакции не мешают друг другу), Устойчивость (результат сохраняется после сбоя).
*   **Snapshot Isolation (Изоляция снимка):** Режим, при котором транзакция видит данные на момент своего начала. Это предотвращает чтение "грязных" или частично обновленных данных.
*   **Causal Consistency (Причинная согласованность):** Модель, гарантирующая, что операции, связанные причинно-следственной связью, видны всем участникам сессии в правильном порядке.
*   **Cluster Time:** Глобальный логический счетчик времени, используемый для синхронизации операций во всем кластере.
*   **Callback API:** Высокоуровневый API драйвера, который автоматически incorporates retry-логику для [`TransientTransactionError`](https://www.mongodb.com/docs/v8.0/core/transactions-in-applications.md#std-label-transient-transaction-error) и [`UnknownTransactionCommitResult`](https://www.mongodb.com/docs/v8.0/core/transactions-in-applications.md#std-label-unknown-transaction-commit-result). Рекомендуется для большинства приложений.
*   **Core API:** Низкоуровневый API, требующий явного вызова `startTransaction()` и `commitTransaction()`. Не включает retry-логику автоматически; приложение должно обрабатывать ошибки самостоятельно.
*   **Transaction Lifetime Limit:** По умолчанию 60 секунд. После истечения этого лимита фоновая задача прерывает активную транзакцию. Настраивается через `transactionLifetimeLimitSeconds` в `mongod.conf`.
*   **TransactionTooLargeForCache:** Ошибка, возникающая когда объем данных в транзакции превышает capacity WiredTiger Cache. Начиная с MongoDB 6.2, сервер не retry такую транзакцию автоматически.
*   **Retryable Writes:** Возможность драйвера повторять операцию записи с тем же `lsid` и `txnNumber` после временного сбоя (сеть, failover). Включены по умолчанию для MongoDB 4.0+.

---

## Базовые концепции

### Многодокументные транзакции

В отличие от атомарных операций над одним документом (которые эффективнее), многодокументные транзакции позволяют:
*   Обновлять данные в разных коллекциях.
*   Использовать сессии для управления состоянием.
*   Выполнять откат (Abort) при ошибке.

**Поддержка:** Replica Set (с 4.0), Sharded Cluster (с 4.2).

### Уровни изоляции и гарантии

Для работы транзакций MongoDB использует специфические настройки Read/Write Concern:
*   **Read Concern `snapshot`:** Обязателен внутри транзакции. Обеспечивает чтение из согласованного снимка данных.
*   **Write Concern `majority`:** Рекомендуется для фиксации транзакции. Гарантирует, что данные не будут откачены при сбое Primary.

> **Важно:** Детали настройки Read/Write Concern по умолчанию описаны в [Репликация в MongoDB](./mongodb-replication.md) и [Высокая доступность](./high_availability.md).

### Причинная согласованность (Causal Consistency)

Гарантии в рамках клиентской сессии (Client Session):
1.  **Read your own writes:** Вы всегда читаете то, что сами только что записали.
2.  **Monotonic reads:** Данные никогда не "откатываются" назад во времени для клиента.
3.  **Monotonic writes:** Ваши записи применяются строго по порядку.
4.  **Writes follow reads:** Порядок соблюдается даже если запись зависит от результата предыдущего чтения.

### Callback API vs Core API

**Callback API** (рекомендуется):
*   Автоматически retry при `TransientTransactionError` и `UnknownTransactionCommitResult`.
*   Упрощает код: одна функция `with_transaction()` обрабатывает start, commit, abort.
*   Начиная с MongoDB 6.2, не retry при `TransactionTooLargeForCache`.
*   Начиная с MongoDB 8.0.11, не retry `upsert` при duplicate key error внутри multidocument транзакции.

**Core API**:
*   Требует явного вызова `session.startTransaction()`, `session.commitTransaction()`, `session.abortTransaction()`.
*   Приложение должно самостоятельно обрабатывать retry-логику для transient ошибок.
*   Подходит для сложных сценариев с кастомной обработкой ошибок.

### Жизненный цикл транзакции

1. Клиент открывает сессию (`startSession()`).
2. Драйвер устанавливает transaction-level read concern, write concern, read preference.
3. Сервер назначает уникальный `txnNumber` и создает запись в `config.transactions`.
4. Операции внутри транзакции получают `lsid` (logical session ID) и `txnNumber`.
5. При `commitTransaction()` сервер проверяет, что все записи достигли `majority` (при `w: "majority"`).
6. При успехе сервер фиксирует транзакцию в Oplog и возвращает успех клиенту.
7. При ошибке серзин может автоматически abort транзакцию или передать управление драйверу для retry.

---

## Практические сценарии

### 1. Транзакция: Перевод средств (Node.js/mongosh)

Пример атомарного обновления двух документов:

```javascript
const session = db.getMongo().startSession();
session.startTransaction({
  readConcern: { level: "snapshot" },
  writeConcern: { w: "majority" }
});

try {
  const accounts = session.getDatabase("bank").collection("accounts");
  
  // 1. Списание
  accounts.updateOne(
    { accountId: "A", balance: { $gte: 100 } },
    { $inc: { balance: -100 } },
    { session }
  );

  // 2. Зачисление
  accounts.updateOne(
    { accountId: "B" },
    { $inc: { balance: 100 } },
    { session }
  );

  session.commitTransaction();
} catch (error) {
  session.abortTransaction();
  console.error("Транзакция отменена:", error);
} finally {
  session.endSession();
}
```

### 2. Использование Causal Consistency в приложении

Позволяет распределять чтение на Secondary без риска увидеть устаревшие данные сразу после своей записи:

```javascript
const session = client.startSession({ causalConsistency: true });
// Все операции в session будут использовать operationTime для синхронизации
```

### 3. Валидация транзакции через explain

Проверка, что операции внутри транзакции используют индексы:

```javascript
const session = client.startSession();
session.startTransaction({
  readConcern: { level: "snapshot" },
  writeConcern: { w: "majority" }
});

const coll = session.getDatabase("hr").collection("employees");
const explain = coll.find({ employeeId: 3 }).session(session).explain("executionStats");

// Проверить: stage должен быть "IXSCAN", а не "COLLSCAN"
printjson(explain.queryPlanner.winningPlan);
```

### 4. Мониторинг активных транзакций

```javascript
// Поиск всех активных транзакций в кластере
db.getSiblingDB("admin").aggregate([
  { $currentOp: { allUsers: true, localOps: false } },
  { $match: { type: "op", "command.startTransaction": { $exists: true } } }
])

// Проверка конкретной транзакции по lsid
db.getSiblingDB("config").transactions.find({ "lsid": { $exists: true } })
```

### 5. Изменение лимита времени транзакции

```yaml
# В mongod.conf
setParameter:
  transactionLifetimeLimitSeconds: 120  # По умолчанию 60
```

```javascript
// Проверка текущего значения
db.getSiblingDB("admin").aggregate([
  { $serverStatus: 1 },
  { $project: { transactionLifetimeLimitSeconds: "$transactions.transactionLifetimeLimitSeconds" } }
])
```

---

## Операции и команды

### Управление транзакциями

| Команда / Метод | Описание |
| :--- | :--- |
| `client.startSession()` | Создать клиентскую сессию |
| `session.startTransaction({ readConcern, writeConcern, readPreference })` | Начать транзакцию с опциями |
| `session.withTransaction(callback)` | Callback API: автоматический start/commit/abort с retry |
| `session.commitTransaction()` | Фиксировать транзакцию |
| `session.abortTransaction()` | Откатить транзакцию |
| `session.endSession()` | Завершить сессию и освободить ресурсы |

### Мониторинг транзакций

| Команда / Метод | Что показывает |
| :--- | :--- |
| `db.getSiblingDB("admin").aggregate([{ $currentOp: { allUsers: true } }, { $match: { "command.startTransaction": { $exists: true } } }])` | Активные транзакции |
| `db.getSiblingDB("config").transactions.find()` | Все активные транзакции в кластере |
| `db.serverStatus().transactions` | Метрики: `totalCommitted`, `totalAborted`, `totalStarted`, `totalLive` |
| `db.serverStatus().wiredTiger.cache` | Использование кэша (важно для `TransactionTooLargeForCache`) |
| `rs.printSecondaryReplicationInfo()` | Lag secondary при распределенных транзакциях |
| `db.getReplicationInfo()` | Размер и временное покрытие Oplog |

### Параметры конфигурации

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `transactionLifetimeLimitSeconds` | 60 | Максимальное время жизни транзакции |
| `maxTransactionLockRequestTimeoutMillis` | 5 | Таймаут ожидания блокировки в миллисекундах |
| `allowTransactionalRestarts` | true | Разрешить драйверу перезапускать транзакции при transient ошибках |

---

## Ограничения и особенности v8.0+

*   **Время жизни (60 сек):** По умолчанию транзакция не может длиться дольше 1 минуты. Это настраивается через `transactionLifetimeLimitSeconds`, но длительные транзакции перегружают WiredTiger Cache.
*   **Объем данных:** Общий размер операций в транзакции не должен превышать лимит Oplog (хотя в новых версиях транзакции могут разбиваться на части).
*   **Блокировки:** MongoDB использует оптимистичную блокировку. Если две транзакции пытаются изменить один документ одновременно, возникнет **Write Conflict**, и одну из транзакций придется повторить.
*   **Retryable Writes:** Начиная с MongoDB 8.0.11, `upsert` внутри multidocument транзакции НЕ retry при duplicate key error. Это изменение поведения по сравнению с предыдущими версиями.
*   **TransactionTooLargeForCache:** Начиная с MongoDB 6.2, сервер не retry транзакцию при этой ошибке. Приложение должно самостоятельно уменьшить объем операций.

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`WriteConflict`** | Конкурентный доступ к документу. | Логи mongod, `db.currentOp()` | Приложение должно реализовывать логику повтора (Retry) для транзакций. |
| **`TransientTransactionError`** | Ошибка сети или смена лидера во время транзакции. | `errorLabels` в результате операции | Безопасно повторить всю транзакцию с начала. Callback API делает это автоматически. |
| **`TransactionTooLarge`** / **`TransactionTooLargeForCache`** | Попытка изменить слишком много данных за раз. | `db.serverStatus().wiredTiger.cache` | Разбить транзакцию на более мелкие этапы. Увеличить `cacheSizeGB`. |
| **`StaleConfig`** | В шардированном кластере метаданные на `mongos` устарели. | Логи mongos | Ошибка обычно обрабатывается драйвером автоматически (Retry). |
| **`Transaction exceeded lifetime limit`** | Транзакция работает дольше `transactionLifetimeLimitSeconds`. | `db.serverStatus().transactions` | Увеличить лимит или оптимизировать приложение для сокращения времени транзакции. |
| **`WriteConcernError` / `WTimeout`** | Запись не достигла `majority` за `wtimeout`. | `getLastError()` | Увеличить `wtimeout` или проверить replication lag. |
| **`Abort due to conflict with resharding`** | Транзакция блокирует Critical Section решардинга. | `db.currentOp()` | Завершить долгие транзакции или увеличить `reshardingCriticalSectionTimeoutMillis`. |
| **`NotMaster` / `NotPrimaryNoSecondaryOk`** | Failover во время транзакции. | Логи приложения | Приложение должно retry с новым Primary. |
| **Высокое потребление RAM** | Columnar cache или множество активных транзакций. | `db.serverStatus().wiredTiger.cache` | Увеличить `cacheSizeGB` или добавить RAM. |
| **Ошибка upgrade/downgrade** | Присутствие активных транзакций при downgrade. | Версия FCV | Завершить все транзакции перед downgrade. |

---

## Лучшие практики (Best Practices)

1.  **Транзакции — последний рубеж:** Сначала попробуйте решить задачу через вложенные документы (Embedding) для обеспечения атомарности на уровне одного документа.
2.  **Минимальный размер:** Делайте транзакции максимально короткими, чтобы не блокировать ресурсы и не раздувать Oplog.
3.  **Индексация:** Убедитесь, что все операции `update/delete` в транзакции используют индексы. Поиск по коллекции (COLLSCAN) внутри транзакции недопустим.
4.  **Обработка ошибок:** Всегда используйте драйверы с поддержкой **Retryable Writes** и **Retryable Reads**.
5.  **Callback API:** Предпочитайте Callback API Core API для автоматической retry-логики.
6.  **Write Concern:** Используйте `w: "majority"` для всех операций внутри транзакции. Для критичных данных добавляйте `j: true`.
7.  **Read Preference:** Внутри транзакции используйте `readPreference: "primary"` для избежания stale reads.
8.  **Мониторинг:** Следите за `db.serverStatus().transactions.totalLive` и `db.serverStatus().wiredTiger.cache` для early detection проблем.
9.  **Capacity Planning:** Оценивайте размер данных транзакции как `ops_per_sec * avg_doc_size * txn_duration_seconds`. Убедитесь, что Working Set помещается в WiredTiger Cache.
10. **Runbook:** Для production-кластеров создайте runbook с процедурами обработки `TransientTransactionError`, `TransactionTooLarge`, и длительных транзакций.

---

## Гранicные случаи

### 1. Долгие-running транзакции и WiredTiger Cache

Транзакции удерживают snapshot данных в памяти. Долгие транзакции (> 30 секунд) при высокой нагрузке могут привести к:
*   Росту `wiredTiger.cache.evictions`
*   Увеличению latency для других операций
*   `TransactionTooLargeForCache` при превышении лимита кэша

**Решение:** Оптимизируйте приложение для сокращения времени транзакции. Увеличьте `cacheSizeGB`. Мониторьте `db.serverStatus().transactions.totalLive`.

### 2. Distributed Transactions и Cross-shard Latency

В шардированном кластере транзакции координируются через mongos. Каждая операция внутри транзакции требует round-trip до соответствующего шарда. При высокой latency между datacenters это может привести к:
*   Превышению `transactionLifetimeLimitSeconds`
*   `TransactionTooLargeForCache` из-за накопления snapshot'ов на Secondary

**Решение:** Размещайте связанные данные на одном шарде (если возможно). Используйте `readPreference: "primary"` внутри транзакций. Для геораспределенных кластеров рассмотрите уменьшение `transactionLifetimeLimitSeconds` с соответствующим увеличением `wtimeout`.

### 3. Transaction Conflict с Resharding

Долгие-running транзакции блокируют Critical Section финальной фазы решардинга. MongoDB 8.0 вводит `reshardingCriticalSectionTimeoutMillis` для управления этим конфликтом.

**Решение:** Завершите долгие транзакции через `db.currentOp()` и `db.killOp()` перед запуском решардинга. Увеличьте `reshardingCriticalSectionTimeoutMillis` если необходимо. Детали описаны в [Решардинг в MongoDB](./mongodb-resharding.md).

### 4. Upsert в multidocument транзакции (MongoDB 8.0.11+)

Начиная с 8.0.11, `upsert` внутри multidocument транзакции не retry при duplicate key error. Это изменение поведения по сравнению с предыдущими версиями, где сервер мог автоматически повторить операцию.

**Решение:** Приложение должно самостоятельно обрабатывать `DuplicateKeyError` внутри транзакций, особенно при использовании `upsert`.

### 5. Snapshot Isolation и Rollback

Snapshot Isolation защищает от чтения частично обновленных данных, но не предотвращает rollback записей при сбое Primary, если использовался `w: 1`. Для гарантии, что данные не будут откачены, используйте `w: "majority"`.

### 6. Causal Consistency и Secondary Reads

Causal Consistency позволяет читать от Secondary сразу после своей записи, но только если:
1.  Сессия создана с `causalConsistency: true`
2.  Все операции используют одну и ту же сессию
3.  Secondary не отстает от Primary более чем на `maxStalenessSeconds`

**Решение:** Для критичных операций используйте `readPreference: "primary"` внутри транзакций. Для read-heavy нагрузок с Causal Consistency мониторьте replication lag через `rs.printSecondaryReplicationInfo()`.

### 7. Transaction Recovery после сбоя mongod

При неожиданном завершении `mongod` активные транзакции abortятся. При восстановлении сервер автоматически освободит все блокировки, удерживаемые этими транзакциями. Повреждение данных маловероятно благодаря журналированию (Journal) и WAL.

**Проверка после восстановления:**
```javascript
// Проверка количества активных транзакций
db.serverStatus().transactions.totalLive  # Должно быть 0 или близко к 0

// Проверка состояния Replica Set
rs.status()  # Все члены должны быть PRIMARY/SECONDARY
```

---

## Чистка и восстановление после инцидентов

### Проверка битых/зависших транзакций

```javascript
// Поиск зависших транзакций (работает дольше 60 секунд)
db.getSiblingDB("admin").aggregate([
  { $currentOp: { allUsers: true, localOps: false } },
  { $match: { 
    type: "op", 
    "command.startTransaction": { $exists: true },
    "secs_running": { $gt: 60 }
  } },
  { $project: { 
    lsid: 1, 
    secs_running: 1, 
    command: 1,
    client: 1 
  }}
])

// Завершение зависшей транзакции
db.killOp({ op: <op_id> })
```

### Очистка после массового abort транзакций

После сбоя, приведшего к массовому abort'у транзакций, проверьте:
1.  **Блокировки:** `db.currentOp()` — нет ли зависших операций с `waitingForLock`.
2.  **WiredTiger Cache:** `db.serverStatus().wiredTiger.cache` — нормализовался ли процент использования.
3.  **Replication:** `rs.printSecondaryReplicationInfo()` — нет ли лага после восстановления.

### Восстановление после TransactionTooLargeForCache

1.  Увеличьте `storage.wiredTiger.engineConfig.cacheSizeGB` в `mongod.conf`.
2.  Перезапустите `mongod`.
3.  Пересмотрите приложение для уменьшения размера транзакций.
4.  Проверьте `db.serverStatus().transactions.totalAborted` — должен расти после изменений.

### Очистка metadata в config.transactions

После завершения транзакции MongoDB автоматически очищает запись из `config.transactions`. При подозрении на "зависшие" записи:

```javascript
// Только для диагностики (read-only)
db.getSiblingDB("config").transactions.find({ 
  "startTimestamp": { $lt: new Date(Date.now() - 3600000) } 
})
// Если записи старше transactionLifetimeLimitSeconds остались — проверьте логи mongod
```

---

## Дополнительная информация

*   **[Общий обзор MongoDB](./mongodb.md)** — архитектура и движок хранения.
*   **[Репликация в MongoDB](./mongodb-replication.md)** — механизмы кворума, Oplog, Read/Write Concern.
*   **[Высокая доступность](./high_availability.md)** — Replica Set, отказоустойчивость, Read Preference.
*   **[Шардирование](./mongodb-sharding.md)** — распределенные транзакции, Cluster Wide Write Concern, Critical Section.
*   **[Решардинг](./mongodb-resharding.md)** — конфликты транзакций с Critical Section, `transactionLifetimeLimitSeconds`.
*   **[Движок WiredTiger](./mongodb-storage-engine.md)** — кэширование, чекпоинты, `cacheSizeGB`.
*   **[Моделирование данных](./mongodb-modeling.md)** — как избежать частых транзакций через правильную схему.
*   **[Индексы](./mongodb-indexes.md)** — compound index, стратегии индексирования для транзакций.
*   **[Администрирование](./mongodb-administration.md)** — бэкапы, мониторинг, обновление.
