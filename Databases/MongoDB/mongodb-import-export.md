# Импорт/экспорт данных и bulk-операции

**Актуально для:** MongoDB 8.0.x, MongoDB Database Tools 100.x+

---

## Определения

*   **mongoimport / mongoexport** — CLI-утилиты для массового импорта/экспорта данных в форматах JSON, CSV, TSV. Часть MongoDB Database Tools.
*   **mongodump / mongorestore** — утилиты бинарного бэкапа/восстановления (BSON). См. **[Бэкап и DR](./mongodb-backup-dr.md)**.
*   **Bulk Write** — пакетная запись нескольких операций (`insertOne`, `updateOne`, `deleteOne`, `replaceOne`) в одном round-trip к серверу.
*   **Ordered vs Unordered bulk:** ordered — выполняется последовательно, останавливается на первой ошибке; unordered — параллельно, продолжает при ошибках.
*   **Insert many:** `db.collection.insertMany([...])` — пакетная вставка до 100 000 документов (лимит batch).
*   **Data migration** — перенос данных между кластерами/версиями (см. **[Миграции](../../Databases/Concepts/migrations/migration_basics.md)**).

---

## Базовые концепции

### Инструменты Database Tools

| Утилита | Формат | Назначение |
| :--- | :--- | :--- |
| `mongoimport` | JSON/CSV/TSV | Импорт в коллекцию |
| `mongoexport` | JSON/CSV | Экспорт из коллекции |
| `mongodump` | BSON (бинарный) | Бэкап (с индексами, опциями) |
| `mongorestore` | BSON | Восстановление из dump |
| `mongofiles` | GridFS | Файлы > 16 MB (см. **[GridFS](./mongodb-gridfs.md)**) |
| `mongostat` / `mongotop` | — | Мониторинг в реальном времени |

### Форматы данных

*   **Extended JSON (canonical/relaxed):** MongoDB-расширение JSON для типов BSON (`ObjectId`, `Date`, `Decimal128`, `BinData`). `mongoimport`/`mongoexport` используют relaxed mode по умолчанию.
*   **CSV:** плоский формат; требует `--fields` или `--fieldFile` для маппинга колонок.
*   **BSON:** бинарный формат; используется `mongodump`/`mongorestore` (сохраняет все типы без потерь).

### Bulk-операции

```javascript
// Инициализация bulk
const bulk = db.collection.initializeUnorderedBulkOp();  // или initializeOrderedBulkOp()

bulk.insert({ _id: 1, name: "a" });
bulk.find({ _id: 2 }).updateOne({ $set: { name: "b" } });
bulk.find({ _id: 3 }).deleteOne();

bulk.execute({ w: "majority", wtimeout: 5000 });
```

**Ordered vs Unordered:**

| | Ordered | Unordered |
| :--- | :--- | :--- |
| Порядок | Последовательно | Параллельно |
| При ошибке | Остановка | Продолжение |
| Скорость | Медленнее | Быстрее |
| Применение | Когда важен порядок | Массовая загрузка |

**Лимиты:**
*   Максимум 100 000 операций в одном bulk (драйвер разбивает на батчи).
*   Максимум 16 MB на сообщение (BSON limit) — драйвер разбивает автоматически.
*   `insertMany` — до 100 000 документов за вызов.

### Производительность bulk

*   **Unordered bulk** быстрее ordered в 2–5× при отсутствии конфликтов.
*   **Индексы:** перед массовой загрузкой удалите вторичные индексы, создайте после — быстрее в 3–10×.
*   **Write concern:** `w: 1` (не `majority`) для начальной загрузки — быстрее; `majority` для production.
*   **Journal:** `j: false` для начальной загрузки (риск при сбое).

---

## Подготовка окружения (Prerequisites)

| Требование | Минимальное значение | Рекомендуемое | Примечание |
| :--- | :--- | :--- | :--- |
| **MongoDB Server** | 4.4+ | 8.0.x | Совместимость Database Tools с версией сервера |
| **Database Tools** | 100.x+ | Актуальная 100.x | Отдельный пакет `mongodb-database-tools` |
| **Права доступа** | `readWrite` на целевую БД | Пользователь с `readWrite` + `dbAdmin` для индексов | Для `mongoimport` нужен `insert`/`update`; для `mongoexport` — `find` |
| **RAM** | 2 GB | 8+ GB | Для сортировки/буферизации больших импортов |
| **Диск** | 2× размер данных | SSD NVMe, отдельный volume | Временные файлы, сжатие, journals |
| **Сеть** | 1 Gbps | 10 Gbps | Для переноса TB данных между хостами |
| **CPU** | 2 vCPU | 8+ vCPU | Компрессия (gzip/zstd), парсинг JSON/CSV |
| **ОС** | Linux (Ubuntu 20.04+, RHEL 8+) | Linux, актуальный LTS | Database Tools не поставляются для Windows Server LTSC |
| **Файловая система** | ext4 / xfs | xfs с `noatime` | Для временных директорий импорта |

**Установка Database Tools (Linux):**
```bash
# Ubuntu/Debian (официальный репозиторий MongoDB)
wget -qO- https://www.mongodb.org/static/pgp/server-8.0.asc | sudo apt-key add -
echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt-get update && sudo apt-get install -y mongodb-database-tools

# RHEL/CentOS/Rocky
sudo yum install -y mongodb-database-tools-100.x.x
# Или скачать tar.gz с https://www.mongodb.com/try/download/database-tools
```

**Проверка версий:**
```bash
mongoimport --version
mongoexport --version
mongodump --version
mongorestore --version
# Все должны показывать 100.x.x (совместимо с MongoDB 8.0)
```

---

## Практические сценарии

### 1. Импорт JSON

```bash
# Импорт JSON-файла (массив или построчно)
mongoimport --host rs0/mongo-1:27017 \
  --username user --password pass --authenticationDatabase admin \
  --db mydb --collection users \
  --file users.json \
  --jsonArray          # если файл — массив [...]

# Без --jsonArray: файл с одним документом на строку (NDJSON)
```

**Валидация:**
```javascript
use mydb
db.users.countDocuments()
db.users.findOne()
```

### 2. Импорт CSV

```bash
# CSV с заголовком
mongoimport --host rs0/mongo-1:27017 \
  --db mydb --collection products \
  --type csv --headerline \
  --file products.csv

# CSV без заголовка — указать поля
mongoimport --host rs0/mongo-1:27017 \
  --db mydb --collection products \
  --type csv --fields "sku,name,price" \
  --file products.csv

# Типизация полей (price → double)
mongoimport ... --fields "sku,string;name,string;price,double" \
  --fieldFile fields.txt
```

### 3. Экспорт

```bash
# Экспорт в JSON
mongoexport --host rs0/mongo-1:27017 \
  --username user --password pass --authenticationDatabase admin \
  --db mydb --collection users \
  --out users.json

# Экспорт с фильтром
mongoexport ... --db mydb --collection users \
  --query '{ "age": { "$gte": 18 } }' \
  --out adults.json

# Экспорт в CSV
mongoexport ... --db mydb --collection users \
  --type csv --fields "name,email" \
  --out users.csv
```

### 4. Bulk-операции (mongosh)

```javascript
// Unordered bulk — массовая вставка
const bulk = db.events.initializeUnorderedBulkOp();
for (let i = 0; i < 10000; i++) {
  bulk.insert({ ts: new Date(), event: "click", userId: i % 1000 });
}
const result = bulk.execute({ w: 1 });
printjson(result.getBulkWriteResult());
// → { nInserted: 10000, ... }
```

```javascript
// insertMany — простой случай
const result = db.logs.insertMany(
  Array.from({ length: 1000 }, (_, i) => ({ ts: new Date(), msg: `log ${i}` })),
  { ordered: false }
);
printjson(result.insertedCount);  // → 1000
```

### 5. Массовая загрузка с оптимизацией

```javascript
// 1. Удалить индексы перед загрузкой
db.target.dropIndexes();

// 2. Загрузить unordered bulk с w:1
const bulk = db.target.initializeUnorderedBulkOp();
// ... добавить операции ...
bulk.execute({ w: 1, j: false });

// 3. Создать индексы после загрузки
db.target.createIndex({ userId: 1, ts: -1 });
```

### 6. Миграция данных между кластерами

```bash
# Экспорт из старого кластера
mongoexport --host old-cluster:27017 --db mydb --collection users --out users.json

# Импорт в новый кластер
mongoimport --host new-cluster:27017 --db mydb --collection users --file users.json
```

> Для больших объёмов используйте `mongodump`/`mongorestore` (бинарный формат, быстрее, сохраняет типы). См. **[Бэкап и DR](./mongodb-backup-dr.md)**.

### 7. Миграция через Change Streams (онлайн)

Для онлайн-миграции с минимальным даунтаймом:
1.  Сделайте `mongodump` старого кластера (снапшот).
2.  `mongorestore` в новый.
3.  Примените изменения из Change Streams старого кластера к новому (dual-write или CDC).
4.  Переключите приложение.

См. **[Change Streams](./mongodb-change-streams.md)** и **[Миграции (expand-contract)](../../Databases/Concepts/migrations/expand_contract.md)**.

### 8. Импорт TSV и кастомных разделителей

```bash
# TSV (tab-separated values)
mongoimport --host rs0/mongo-1:27017 \
  --db mydb --collection logs \
  --type tsv --headerline \
  --file access_logs.tsv

# Кастомный разделитель (pipe |) через --fields с типами
mongoimport ... --type csv --fields "id,int;message,string;ts,date(2006-01-02)" \
  --file pipe_data.txt
```

### 9. Параллельный импорт (много файлов / разделов)

```bash
# Разбить большой JSON на части и импортировать параллельно (GNU parallel)
ls data-part-*.json | parallel -j 4 mongoimport --host rs0/mongo-1:27017 \
  --username user --password pass --authenticationDatabase admin \
  --db mydb --collection events --file {}

# Или через mongosh: параллельные insertMany в разные коллекции/шарды
```

### 10. Dry-run и валидация без записи

```bash
# mongoimport --dryRun (доступен в Database Tools 100.9+) — проверить парсинг без вставки
mongoimport --host rs0/mongo-1:27017 \
  --db mydb --collection users \
  --file users.json --dryRun

# Валидация JSON перед импортом
jq empty users.json && echo "Valid JSON"

# Проверка CSV структуры
head -5 users.csv | column -t -s,
```

### 11. Экспорт больших коллекций (стриминг, сжатие, параллелизм)

```bash
# Экспорт с gzip (потоковый, не создаёт временный файл)
mongoexport --host rs0/mongo-1:27017 \
  --username user --password pass --authenticationDatabase admin \
  --db mydb --collection huge_logs \
  --query '{ "ts": { "$gte": ISODate("2026-01-01") } }' \
  --out - | gzip > huge_logs.json.gz

# Экспорт в CSV для аналитики (PostgreSQL/ClickHouse)
mongoexport ... --type csv --fields "userId,event,ts" \
  --out events.csv

# Параллельный экспорт по шардам (для шардированных коллекций)
# Подключение к каждому шарду отдельно через mongos не даёт параллелизма
# Используйте mongoexport на каждом шарде с --query по диапазону shard key
```

### 12. Bulk-операции в драйверах (Python / Node.js)

```python
# Python pymongo: unordered bulk
from pymongo import MongoClient, InsertOne, UpdateOne, DeleteOne

client = MongoClient("mongodb://user:pass@mongo-1:27017/?replicaSet=rs0&authSource=admin")
db = client["mydb"]

operations = [
    InsertOne({"event": "click", "userId": i}) for i in range(10000)
] + [
    UpdateOne({"event": "view", "userId": i}, {"$inc": {"count": 1}}) for i in range(100)
]

result = db.events.bulk_write(operations, ordered=False, bypass_document_validation=False)
print(f"Inserted: {result.inserted_count}, Modified: {result.modified_count}")
```

```javascript
// Node.js: bulkWrite с ordered: false
const { MongoClient } = require("mongodb");

const client = new MongoClient("mongodb://user:pass@mongo-1:27017/?replicaSet=rs0&authSource=admin");
await client.connect();
const db = client.db("mydb");

const operations = Array.from({ length: 10000 }, (_, i) => ({
  insertOne: { document: { event: "click", userId: i } }
}));

const result = await db.collection("events").bulkWrite(operations, { ordered: false });
console.log(`Inserted: ${result.insertedCount}`);
```

### 13. Обновление существующих документов (upsert через mongoimport)

```bash
# --mode upsert: вставить если нет, обновить если есть (по _id или уникальному индексу)
mongoimport --host rs0/mongo-1:27017 \
  --db mydb --collection users \
  --file updates.json \
  --mode upsert \
  --upsertFields "email"   # поле для поиска существующего документа
```

### 14. Восстановление из mongodump с фильтрацией (не бэкап, а точечный restore)

```bash
# mongorestore одной коллекции из dump директории
mongorestore --host rs0/mongo-1:27017 \
  --username user --password pass --authenticationDatabase admin \
  --db mydb --collection users \
  --dir /backup/mongodb-2026-10-01/mydb

# С переименованием БД/коллекции
mongorestore ... --nsFrom="old_db.*" --nsTo="new_db.*"
mongorestore ... --nsFrom="old_db.users" --nsTo="new_db.customers"

# Dry-run перед восстановлением
mongorestore ... --dryRun --dir /backup/mongodb-2026-10-01
```

---

## Операции и команды (Reference)

### mongoimport / mongoexport

| Утилита | Ключевые флаги |
| :--- | :--- |
| `mongoimport` | `--db`, `--collection`, `--file`, `--type json/csv/tsv`, `--jsonArray`, `--headerline`, `--fields`, `--fieldFile`, `--drop`, `--mode upsert`, `--upsertFields`, `--dryRun`, `--batchSize`, `--numInsertionWorkers`, `--writeConcern` |
| `mongoexport` | `--db`, `--collection`, `--out`, `--type json/csv`, `--query`, `--fields`, `--csvFieldFile`, `--sort`, `--skip`, `--limit`, `--readPreference` |

### mongodump / mongorestore (для справки — см. **[Бэкап и DR](./mongodb-backup-dr.md)**)

| Утилита | Ключевые флаги |
| :--- | :--- |
| `mongodump` | `--host`, `--db`, `--collection`, `--out`, `--archive`, `--gzip`, `--oplog`, `--query`, `--excludeCollection`, `--excludeCollectionsWithPrefix` |
| `mongorestore` | `--host`, `--db`, `--collection`, `--dir`, `--archive`, `--gzip`, `--oplogReplay`, `--nsFrom`, `--nsTo`, `--drop`, `--dryRun`, `--numInsertionWorkers`, `--writeConcern` |

### Bulk-методы (mongosh legacy API)

| Метод | Описание |
| :--- | :--- |
| `initializeOrderedBulkOp()` | Ordered bulk (остановка на ошибке) |
| `initializeUnorderedBulkOp()` | Unordered bulk (параллельно) |
| `bulk.insert(doc)` | Добавить вставку |
| `bulk.find(q).updateOne(u)` | Обновить один |
| `bulk.find(q).updateMany(u)` | Обновить все совпадения |
| `bulk.find(q).replaceOne(r)` | Заменить документ |
| `bulk.find(q).deleteOne()` | Удалить один |
| `bulk.find(q).deleteMany()` | Удалить все совпадения |
| `bulk.execute(opts)` | Выполнить с опциями write concern |

### Драйверные Bulk Write API (современные драйверы 4.x+)

| Операция | pymongo | Node.js | Java | Go |
| :--- | :--- | :--- | :--- | :--- |
| Массовая запись | `bulk_write(operations)` | `bulkWrite(ops)` | `bulkWrite(ops)` | `BulkWrite()` |
| InsertOne | `InsertOne(doc)` | `insertOne: {document}` | `InsertOneModel` | `mongo.InsertOneModel` |
| UpdateOne | `UpdateOne(filter, update)` | `updateOne: {filter, update}` | `UpdateOneModel` | `mongo.UpdateOneModel` |
| UpdateMany | `UpdateMany(filter, update)` | `updateMany: {filter, update}` | `UpdateManyModel` | `mongo.UpdateManyModel` |
| ReplaceOne | `ReplaceOne(filter, doc)` | `replaceOne: {filter, replacement}` | `ReplaceOneModel` | `mongo.ReplaceOneModel` |
| DeleteOne | `DeleteOne(filter)` | `deleteOne: {filter}` | `DeleteOneModel` | `mongo.DeleteOneModel` |
| DeleteMany | `DeleteMany(filter)` | `deleteMany: {filter}` | `DeleteManyModel` | `mongo.DeleteManyModel` |
| Ordered/Unordered | `ordered=False` в bulk_write | `ordered: false` в опциях | `ordered(false)` | `Ordered(false)` |

### Полезные команды mongosh для валидации

| Команда | Описание |
| :--- | :--- |
| `db.collection.countDocuments({})` | Подсчёт документов после импорта |
| `db.collection.stats()` | Статистика коллекции (размер, индексы) |
| `db.collection.validate({full: true})` | Проверка целостности данных и индексов |
| `db.getCollectionNames()` | Список коллекций |
| `db.currentOp()` | Текущие операции (для мониторинга долгих импортов) |

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`mongoimport` медленный** | Индексы, `w:majority`, journal | `mongostat` | Удалить индексы, `w:1`, `j:false` для начальной загрузки |
| **Duplicate key error** | Дубликат `_id` | Логи mongoimport | `--drop` (очистить коллекцию) или `--mode upsert` |
| **CSV: неверные типы** | Все поля строки | `db.collection.findOne()` | `--fieldFile` с типами |
| **Bulk > 16 MB** | Лимит BSON | Ошибка `exceeded 16MB` | Драйвер разбивает автоматически; уменьшите размер батча |
| **`insertMany` частично** | Ordered остановился на ошибке | `result.writeErrors` | Используйте `ordered: false` |
| **Extended JSON не парсится** | Неправильный формат `$oid`/`$date` | Ошибка parse | Используйте canonical/relaxed Extended JSON |
| **`mongoexport` OOM / killed** | Экспорт большой коллекции без лимита | OOM killer, `mongostat` memory | `--limit`, `--batchSize`, читать с hidden secondary |
| **Потеря типов при CSV** | CSV не хранит типы BSON | Проверка `typeof` в документе | Использовать JSON/Extended JSON или `--fieldFile` с типами |
| **`mongorestore` не создаёт индексы** | Флаг `--noIndexRestore` или версия Tools | `db.coll.getIndexes()` пуст | Убрать `--noIndexRestore`, проверить версию Tools |
| **`mongoimport` завис на шардированной коллекции** | Отсутствует shard key в документах | Ошибка "document missing shard key" | Добавить shard key в каждый документ перед импортом |
| **Неверный `_id` при импорте CSV** | Нет поля `_id` в CSV, MongoDB генерирует ObjectId | Документы без явного `_id` | Добавить колонку `_id` в CSV или использовать `--mode upsert` с `--upsertFields` |
| **Ошибка аутентификации SCRAM-SHA-256** | Старый Database Tools не поддерживает новый механизм | `Authentication failed` | Обновить Database Tools до 100.x+ для MongoDB 8.0 |
| **`mongoexport --query` не работает с Date** | Неправильный формат даты в JSON | Пустой результат | Использовать ISODate формат: `'{"ts": {"$gte": {"$date": "2026-01-01T00:00:00Z"}}}'` |
| **Параллельный `mongorestore` конфликтует** | Несколько процессов пишут в одну коллекцию | Write conflicts, duplicate key | Использовать `--nsFrom`/`--nsTo` для разделения или восстанавливать последовательно |

---

## Ограничения и Edge Cases

*   **CSV не сохраняет типы BSON** — все поля строки. Типы задаются только через `--fieldFile` или `--fields "name,type"`. Для полной сохранности типов используйте JSON/Extended JSON.
*   **`mongoimport` не поддерживает upsert по уникальному индексу, отличному от `_id`** — флаг `--upsertFields` работает только с одним полем (или составным через запятую в новых версиях).
*   **Нет транзакционности импорта** — `mongoimport` не атомарен. При сбое в середине коллекция остаётся в частично загруженном состоянии. Используйте `--drop` для идемпотентного перезапуска или временную коллекцию + `renameCollection`.
*   **`mongodump`/`mongorestore` не для production бэкапа > 500 GB** — время восстановления линейно растёт. Для TB используйте физические снапшоты (LVM/ZFS) или PBM. См. **[Бэкап и DR](./mongodb-backup-dr.md)**.
*   **`--oplog` в `mongodump` не работает через `mongos`** — флаг игнорируется. Для консистентного бэкапа шардированного кластера: подключайтесь к каждому шарду отдельно или используйте PBM.
*   **`mongoexport --query` требует ISODate для дат** — Extended JSON `$date` формат обязателен. Обычный JSON `"2026-01-01"` не сработает.
*   **Лимит 100 000 операций в bulk** — драйверы автоматически разбивают, но `bulk.execute()` в mongosh legacy API требует ручного батчинга.
*   **`mongoimport --jsonArray` требует весь файл в RAM** — для больших JSON используйте NDJSON (по одному документу на строку) без `--jsonArray`.
*   **Нет встроенного прогресс-бара / ETA** — используйте `mongostat` / `db.currentOp()` / `pv` (pipe viewer) для мониторинга.
*   **Shard key обязателен при импорте в шардированную коллекцию** — каждый документ должен содержать shard key. `mongoimport` не генерирует его автоматически.
*   **`mongorestore` не восстанавливает пользователей/роли из `admin` по умолчанию** — нужен флаг `--restoreDbUsersAndRoles` (или восстанавливать БД `admin` отдельно).
*   **Версионная совместимость Tools ↔ Server** — Database Tools N.x работают с MongoDB N и N-1. Tools 100.x для MongoDB 8.0/7.0. Не используйте Tools 8.0 для restore в 6.0.
*   **`mongoexport` не экспортирует индексы** — только данные. Индексы нужно создавать отдельно или через `mongodump`/`mongorestore`.
*   **Compression (gzip/zstd) однопоточная** — `--gzip` в `mongoexport`/`mongodump` использует один CPU core. Для больших данных параллельте на уровне коллекций/шардов.

---

## Лучшие практики (Best Practices)

1.  **`mongodump`/`mongorestore` для бэкапа**, `mongoimport`/`export` — для обмена данными с внешними системами.
2.  **Unordered bulk** для массовой загрузки (быстрее, устойчив к ошибкам).
3.  **Удаляйте индексы** перед массовой загрузкой, создавайте после.
4.  **`w:1, j:false`** для начальной загрузки (не для production-трафика).
5.  **`--drop`** при повторном импорте для идемпотентности.
6.  **Extended JSON** для сохранения типов BSON при JSON-экспорте.
7.  **Не используйте `mongoimport` для > 100 GB** — `mongorestore` быстрее и надёжнее.
8.  **Тестируйте на подмножестве** перед полной миграцией.

### SRE / DevOps / Production

9.  **Пайплайн импорта: staging → validate → swap** — загружайте в временную коллекцию (`_staging`), валидируйте (`countDocuments`, `validate`, выборка), затем атомарно `renameCollection` на production.
10. **Параллелизм по коллекциям/шардам** — запускайте `mongoimport`/`mongorestore` параллельно для независимых коллекций. Для шардированных: по одному процессу на шард.
11. **`--numInsertionWorkers` (Database Tools 100.5+)** — увеличьте до количества CPU cores для ускорения `mongoimport`/`mongorestore` (по умолчанию 1).
12. **Чтение с secondary для экспорта** — `--readPreference secondaryPreferred` в `mongoexport`/`mongodump` снимает нагрузку с Primary.
13. **Сжатие на лету (pipe)** — `mongoexport ... --out - | gzip > file.json.gz` — не создаёт временный несжатый файл на диске.
14. **Мониторинг прогресса** — `watch -n 5 'mongostat --host rs0/mongo-1:27017'` или `db.currentOp()` в mongosh для долгих операций.
15. **Валидация после импорта** — обязательно: `countDocuments`, `stats()`, `validate({full: true})`, выборка `find().limit(10)`.
16. **Идемпотентность через `--mode upsert` + `--upsertFields`** — для повторных загрузок (ETL, CDC replay) без дублей.
17. **Версионная совместимость Tools** — всегда используйте Database Tools версии, соответствующей целевому MongoDB (100.x для 8.0). Проверяйте `mongoimport --version` в CI/CD.
18. **Бэкап перед миграцией** — всегда `mongodump` (или PBM снапшот) перед крупными операциями импорта/миграции. См. **[Бэкап и DR](./mongodb-backup-dr.md)**.
19. **Dry-run в CI/CD** — `mongoimport --dryRun` в pipeline для проверки формата данных перед продакшеном.
20. **Документируйте runbook** — для каждой критичной миграции: команды, rollback-план, контакты, SLA по времени.

---

## Дополнительная информация

*   **[Бэкап и DR](./mongodb-backup-dr.md)** — `mongodump`/`mongorestore`, PBM, физические снапшоты.
*   **[GridFS](./mongodb-gridfs.md)** — файлы > 16 MB, `mongofiles`.
*   **[Change Streams](./mongodb-change-streams.md)** — онлайн-миграция, CDC.
*   **[Мониторинг](./mongodb-monitoring.md)** — `mongostat`, `mongotop`, Prometheus метрики импорта/экспорта.
*   **[Миграции (общая теория)](../../Databases/Concepts/migrations/migration_basics.md)** — expand-contract, rollback.
*   **[Администрирование](./mongodb-administration.md)** — `mongosh`-скриптинг, валидация.
*   [mongoimport](https://www.mongodb.com/docs/database-tools/mongoimport/)
*   [mongoexport](https://www.mongodb.com/docs/database-tools/mongoexport/)
*   [mongodump](https://www.mongodb.com/docs/database-tools/mongodump/)
*   [mongorestore](https://www.mongodb.com/docs/database-tools/mongorestore/)
*   [Bulk Write Operations](https://www.mongodb.com/docs/manual/core/bulk-write-operations/)
