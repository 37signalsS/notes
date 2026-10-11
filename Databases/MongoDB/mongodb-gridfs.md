# GridFS: Хранение больших файлов в MongoDB

**Актуально для:** MongoDB 8.0.x (GridFS спецификация стабильна с 2.x)

---

## Определения

**GridFS** — спецификация хранения файлов, превышающих лимит документа BSON (16 MB), в виде набора чанков (chunks) в двух коллекциях: `fs.files` (метаданные) и `fs.chunks` (содержимое, по 255 KB по умолчанию).

*   **Chunk (чанк):** фрагмент файла фиксированного размера (по умолчанию 255 KB). Каждый чанк — отдельный документ в `fs.chunks` с полями `files_id`, `n` (порядковый номер), `data` (BinData).
*   **fs.files:** коллекция метаданных файла: `filename`, `length`, `chunkSize`, `uploadDate`, `md5`, `contentType`, произвольные метаданные.
*   **fs.chunks:** коллекция чанков. Индекс `{files_id: 1, n: 1}` обеспечивает последовательное чтение.
*   **mongofiles:** CLI-утилита для работы с GridFS (put/get/list/delete/search).
*   **Bucket:** логическое пространство GridFS. По умолчанию `fs` (коллекции `fs.files`, `fs.chunks`). Можно создать именованный bucket: `mybucket.files`, `mybucket.chunks`.

---

## Базовые концепции

### Как работает GridFS

```
Файл (например, 10 MB)
   │
   ├─► fs.files: 1 документ (метаданные)
   │     { _id, filename, length: 10485760, chunkSize: 261120,
   │       uploadDate, md5, contentType, metadata: {...} }
   │
   └─► fs.chunks: ~40 документов (по 255 KB)
         { _id, files_id, n: 0, data: BinData(...) }
         { _id, files_id, n: 1, data: BinData(...) }
         ...
```

**Запись:** драйвер разбивает файл на чанки, пишет в `fs.chunks`, затем вставляет метаданные в `fs.files`. **Чтение:** драйвер читает `fs.files`, затем последовательно забирает чанки по индексу `{files_id, n}`.

### Когда GridFS уместен

| Сценарий | GridFS? | Почему |
| :--- | :--- | :--- |
| Файлы > 16 MB | Да | Лимит документа BSON |
| Файлы < 16 MB, много мелких | Нет | Обычный документ с `BinData` эффективнее |
| Нужна репликация/шардирование файлов | Да | GridFS наследует Replica Set / Sharding |
| Нужен CDN, range-запросы, потоковое видео | Нет | S3/объектное хранилище лучше |
| Метаданные + файл в одной транзакции | Да | Атомарность с метаданными |
| Частое обновление файлов | Нет | GridFS не поддерживает обновление чанков — только удаление и перезапись |

### GridFS vs S3/объектное хранилище

| Критерий | GridFS | S3 |
| :--- | :--- | :--- |
| Лимит размера | Нет (чанки) | 5 TB |
| Range-запросы | Да (чанки) | Да (HTTP Range) |
| CDN | Нет | Да |
| Стоимость | RAM/диск MongoDB | Дешевле за GB |
| Транзакции с метаданными | Да | Нет |
| Шардирование | Да (через MongoDB) | Встроено |
| Потоковое видео | Нет | Да |

**Правило:** если файлы > 16 MB и нужны транзакции/репликация/шардирование в MongoDB — GridFS. Если файлы отдаются пользователям через веб — S3 + метаданные в MongoDB.

### Шардирование GridFS

```javascript
// Шардировать fs.chunks по files_id (равномерное распределение)
sh.enableSharding("mydb")
sh.shardCollection("mydb.fs.chunks", { files_id: 1, n: 1 })

// fs.files обычно не шардируют (мало документов)
```

> **Важно:** шардируйте `fs.chunks`, а не `fs.files`. Индекс `{files_id: 1, n: 1}` — compound shard key, обеспечивающий и последовательное чтение, и распределение.

---

## Подготовка окружения (Prerequisites)

| Требование | Минимальное значение | Рекомендуемое | Примечание |
| :--- | :--- | :--- | :--- |
| **MongoDB** | 4.4+ | 8.0.x | GridFS спецификация стабильна с 2.x |
| **Драйвер** | Совместимый с MongoDB | Официальный драйвер | pymongo `gridfs`, Node.js `GridFSBucket`, Java `GridFSBucket` |
| **mongofiles** | MongoDB Database Tools | Актуальная версия | Входит в `mongodb-database-tools` пакет |
| **RAM** | 2 GB | 4+ GB | Для кэширования чанков при стриминге |
| **Диск** | 2× размер файлов | SSD, отдельный volume | `fs.chunks` — основной потребитель места |
| **Сеть** | 1 Gbps | 10 Gbps | Для больших файлов — пропускная способность |
| **CPU** | 2 vCPU | 4+ vCPU | Для компрессии/декомпрессии потока |

---

## Практические сценарии

### 1. Загрузка файла (mongofiles)

```bash
# Загрузить файл с аутентификацией
mongofiles --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin put /path/to/video.mp4

# Загрузить с типом контента и метаданными (через драйвер)
```

**Валидация:**
```bash
# Список файлов
mongofiles --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin list
# → video.mp4    10485760

# Поиск
mongofiles --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin search video
```

### 2. Чтение файла (mongofiles)

```bash
# Скачать с аутентификацией
mongofiles --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin get video.mp4 -o /tmp/video.mp4

# Сравнить контрольные суммы
md5sum /path/to/video.mp4 /tmp/video.mp4
# → одинаковые md5
```

### 3. Python (pymongo + gridfs)

```python
from pymongo import MongoClient
from gridfs import GridFS

# Подключение к Replica Set с аутентификацией
client = MongoClient("mongodb://user:pass@mongo-1:27017/?replicaSet=rs0&authSource=admin")
db = client["mydb"]
fs = GridFS(db)  # bucket "fs"

# Запись с метаданными
with open("video.mp4", "rb") as f:
    file_id = fs.put(f, filename="video.mp4",
                     content_type="video/mp4",
                     metadata={"owner": "user1", "tags": ["demo"]})

# Чтение
file = fs.get(file_id)
data = file.read()
print(file.filename, file.length, file.content_type)

# Поиск по имени
for f in fs.find({"filename": "video.mp4"}):
    print(f._id, f.filename, f.uploadDate)

# Удаление
fs.delete(file_id)
```

### 4. Node.js (GridFSBucket)

```javascript
const { MongoClient, GridFSBucket } = require("mongodb");
const fs = require("fs");

const client = new MongoClient("mongodb://user:pass@mongo-1:27017/?replicaSet=rs0&authSource=admin");
await client.connect();
const db = client.db("mydb");
const bucket = new GridFSBucket(db, { bucketName: "fs" });

// Запись (streaming)
const uploadStream = bucket.openUploadStream("video.mp4", {
  contentType: "video/mp4",
  metadata: { owner: "user1" },
});
fs.createReadStream("video.mp4").pipe(uploadStream);
await new Promise((res) => uploadStream.on("finish", res));

// Чтение (streaming)
const downloadStream = bucket.openDownloadStream(uploadStream.id);
downloadStream.pipe(fs.createWriteStream("/tmp/video.mp4"));
```

### 5. Range-запросы (частичное чтение)

```python
# Прочитать байты 1MB..2MB (GridFS поддерживает range через seek/read чанков)
file = fs.get(file_id)
file.seek(1048576)       # перейти к позиции
chunk = file.read(1048576)  # прочитать 1MB
```

> Драйверы читают только нужные чанки — не весь файл. Это ключевое преимущество GridFS над хранением файла в одном поле.

### 6. Именованный bucket

```python
from gridfs import GridFS
fs = GridFS(db, collection="mybucket")  # → mybucket.files, mybucket.chunks
```

### 7. Удаление файла

```bash
mongofiles --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin delete video.mp4
```

```python
fs.delete(file_id)  # удаляет и fs.files, и все fs.chunks
```

### 8. Валидация целостности GridFS

```bash
# 1. Проверить, что все чанки имеют соответствующую запись в fs.files
mongosh --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin --eval '
db.fs.chunks.aggregate([
  { $lookup: { from: "fs.files", localField: "files_id", foreignField: "_id", as: "file" } },
  { $match: { file: { $size: 0 } } },
  { $count: "orphan_chunks" }
])'
# # → { "orphan_chunks" : 0 } — нет осиротевших чанков

# 2. Проверить контрольные суммы (md5 в fs.files)
mongosh --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin --eval '
db.fs.files.find({md5: {$exists: true}}).forEach(function(f) {
  var calc = db.runCommand({filemd5: f._id, root: "fs"});
  if (calc.md5 !== f.md5) print("MISMATCH:", f.filename, calc.md5, f.md5);
})'
# # → нет вывода = все md5 совпадают

# 3. Проверить размеры: sum(chunks.data.length) == fs.files.length
mongosh --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin --eval '
db.fs.files.find().forEach(function(f) {
  var total = db.fs.chunks.aggregate([
    { $match: { files_id: f._id } },
    { $group: { _id: null, sum: { $sum: { $strLenCP: "$data" } } } }
  ]).toArray()[0]?.sum || 0;
  if (total !== f.length) print("SIZE MISMATCH:", f.filename, total, f.length);
})'
```

### 9. Очистка осиротевших чанков и старых файлов

```bash
# Удалить осиротевшие чанки (нет записи в fs.files)
mongosh --host rs0/mongo-1:27017 --username user --password pass \
  --authenticationDatabase admin --eval '
var orphans = db.fs.chunks.aggregate([
  { $lookup: { from: "fs.files", localField: "files_id", foreignField: "_id", as: "file" } },
  { $match: { file: { $size: 0 } } },
  { $project: { _id: 1 } }
]).toArray();
db.fs.chunks.deleteMany({ _id: { $in: orphans.map(function(o) { return o._id; }) } });
print("Deleted:", orphans.length);
'
```

```python
# Python: удаление файлов старше 30 дней
from datetime import datetime, timedelta
cutoff = datetime.utcnow() - timedelta(days=30)
old_files = fs.find({"uploadDate": {"$lt": cutoff}})
for f in old_files:
    fs.delete(f._id)
    print(f"Deleted: {f.filename} ({f.uploadDate})")
```

### 10. Настройка производительности (chunkSize)

```python
# Увеличить chunkSize для больших файлов (по умолчанию 255 KB)
# Большие чанки = меньше документа, меньше накладных расходов, но больше память на чтение
fs = GridFS(db, chunk_size=1024*1024)  # 1 MB чанки

# Для маленьких файлов (< 1 MB) можно уменьшить
fs = GridFS(db, chunk_size=64*1024)  # 64 KB чанки
```

```javascript
// Node.js: настройка chunkSize через GridFSBucket
const bucket = new GridFSBucket(db, {
  bucketName: "fs",
  chunkSizeBytes: 1024 * 1024  // 1 MB
});
```

---

## Операции и команды (Reference)

| Команда mongofiles | Описание | Пример |
| :--- | :--- | :--- |
| `put <file>` | Загрузить файл | `mongofiles -h rs0/mongo-1:27017 -u user -p pass --authenticationDatabase admin put /path/file` |
| `get <filename> [-o <path>]` | Скачать файл | `mongofiles ... get file.mp4 -o /tmp/file.mp4` |
| `list [prefix]` | Список файлов (опционально префикс) | `mongofiles ... list video` |
| `search <string>` | Поиск по имени (substring) | `mongofiles ... search video` |
| `delete <filename>` | Удалить файл (по имени) | `mongofiles ... delete file.mp4` |

| Флаги mongofiles | Описание |
| :--- | :--- |
| `--host` | Connection string (Replica Set URI) |
| `--username` / `--password` | Аутентификация |
| `--authenticationDatabase` | БД для аутентификации (обычно `admin`) |
| `--db` | Целевая БД (по умолчанию `test`) |
| `--prefix` / `--bucket` | Именованный bucket (коллекции `prefix.files`, `prefix.chunks`) |
| `--local` / `--remote` | Для `put`/`get` — локальный/удалённый путь |
| `--replace` | Перезаписать при `put` если файл существует |

| Операция драйвера | pymongo (GridFS) | Node.js (GridFSBucket) |
| :--- | :--- | :--- |
| Запись | `fs.put(data, **kwargs)` | `bucket.openUploadStream(name)` |
| Чтение | `fs.get(id).read()` | `bucket.openDownloadStream(id)` |
| Поиск | `fs.find({...})` | `bucket.find({...})` |
| Удаление по _id | `fs.delete(id)` | `bucket.delete(id)` |
| Удаление по имени | `fs.delete(fs.find_one({"filename": "x"})._id)` | `bucket.delete(bucket.find({"filename": "x"}).next()._id)` |
| Открыть на чтение (stream) | `fs.get(id)` → file-like object | `bucket.openDownloadStream(id)` |
| Открыть на запись (stream) | `fs.new_file(filename=...)` → file-like | `bucket.openUploadStream(name)` |
| Инфо о файле | `fs.get(id)` → атрибуты: length, chunkSize, md5, metadata | `bucket.find({_id: id}).next()` |

| Административные команды | Описание |
| :--- | :--- |
| `db.fs.files.stats()` | Статистика коллекции метаданных |
| `db.fs.chunks.stats()` | Статистика коллекции чанков (размер, индексы) |
| `db.fs.chunks.getIndexes()` | Проверка индекса `{files_id: 1, n: 1}` |
| `db.runCommand({filemd5: <id>, root: "fs"})` | Вычислить md5 файла по чанкам |
| `db.fs.files.createIndex({"metadata.owner": 1})` | Индекс для поиска по метаданным |

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Файл > 16 MB не записывается в поле** | Лимит BSON | Ошибка `BSONObj size: ... is invalid` | Использовать GridFS |
| **Медленное чтение** | Нет индекса `{files_id, n}` | `db.fs.chunks.getIndexes()` | Создать индекс (обычно создаётся автоматически) |
| **Файл повреждён** | Прерванная запись (чанки без fs.files) | `db.fs.chunks.countDocuments({files_id: id})` vs `fs.files` | Удалить осиротевшие чанки |
| **Дубликаты имён** | GridFS не запрещает одинаковые filename | `fs.find({filename: "x"})` → несколько | Использовать `_id` для однозначной идентификации |
| **fs.chunks растёт** | Нет TTL/очистки | `db.fs.chunks.stats()` | Политика удаления, архивация |
| **md5 не совпадает** | Повреждение при передаче/записи | `db.runCommand({filemd5: id, root: "fs"})` vs `fs.files.md5` | Перезагрузить файл, проверить сеть/диск |
| **OutOfMemory при чтении большого файла** | Драйвер загружает весь файл в память | Использование `.read()` без стриминга | Использовать streaming API (`fs.get(id)` → итератор / `openDownloadStream`) |
| **Медленный `mongofiles put`** | Малый chunkSize, нет компрессии | Время загрузки >> ожидаемое | Увеличить chunkSize (1 MB), использовать `--gzip` (если поддерживается) |
| **Шардирование не работает** | Шардируют `fs.files` вместо `fs.chunks` | `sh.status()` — чанки на одном шарде | `sh.shardCollection("db.fs.chunks", {files_id: 1, n: 1})` |
| **Bucket не найден** | Неправильный префикс bucket | `db.getCollectionNames()` — нет `<bucket>.files` | Указать `--prefix` в mongofiles или `collection` в драйвере |

**Очистка осиротевших чанков:**
```javascript
// Найти чанки без записи в fs.files
db.fs.chunks.aggregate([
  { $lookup: { from: "fs.files", localField: "files_id",
               foreignField: "_id", as: "file" } },
  { $match: { file: { $size: 0 } } }
])
// Удалить найденные
```

---

## Ограничения и Edge Cases

*   **Нет частичного обновления** — GridFS не поддерживает обновление отдельных чанков. Изменение файла = удаление старого + запись нового (новый `_id`).
*   **Нет встроенного TTL** — MongoDB TTL-индексы работают только на поле даты в `fs.files`. Чанки в `fs.chunks` удаляются каскадно при удалении файла, но сами по себе не имеют TTL.
*   **`filename` не уникален** — несколько файлов могут иметь одинаковое `filename`. Всегда используйте `_id` для операций.
*   **md5 считается при загрузке** — драйвер вычисляет md5 на клиенте. Для больших файлов это нагрузка на CPU клиента. Можно отключить (driver-specific).
*   **ChunkSize фиксирован на файл** — нельзя менять chunkSize в середине файла. Все чанки одного файла одного размера (кроме последнего).
*   **Память при чтении** — `.read()` загружает весь файл в RAM. Для файлов > RAM используйте streaming (`seek` + `read` в цикле или потоковый API).
*   **Шардирование только `fs.chunks`** — `fs.files` обычно не шардируют (мало документов). Шардинг `fs.files` по `filename` может быть полезен при миллионах файлов.
*   **Бэкап GridFS** — `mongodump` бэкапит обе коллекции. Для PITR нужен oplog. PBM бэкапит GridFS как обычные коллекции. См. **[Бэкап и DR](./mongodb-backup-dr.md)**.
*   **ACID транзакции** — запись файла (чанки + метаданные) не атомарна на уровне MongoDB (две коллекции). Используйте драйвер, который делает это в одной сессии, или принимайте eventual consistency.
*   **Метрики Prometheus** — `mongodb_gridfs_files_total`, `mongodb_gridfs_chunks_total`, `mongodb_gridfs_bytes_total` (через mongodb_exporter). См. **[Мониторинг](./mongodb-monitoring.md)**.
*   **Docker/контейнеры** — при монтировании volumes для MongoDB данные GridFS попадают в тот же volume. Размер диска планируйте с запасом 2-3× от размера файлов.

---

## Лучшие практики (Best Practices)

1.  **GridFS только для файлов > 16 MB** или когда нужны транзакции/шардирование. Для мелких файлов — `BinData` в документе.
2.  **Шардируйте `fs.chunks`** по `{files_id: 1, n: 1}`, если GridFS в шардированном кластере.
3.  **Храните метаданные** в `metadata` поле `fs.files` — это позволяет искать файлы без чтения содержимого.
4.  **Используйте `_id`**, а не `filename`, для однозначной идентификации (имена могут дублироваться).
5.  **Streaming API** драйвера для больших файлов — не загружайте весь файл в память приложения.
6.  **Range-запросы** через `seek()`/чанки — не читайте весь файл, если нужен фрагмент.
7.  **Не используйте GridFS для потокового видео/CDN** — S3 + CloudFront дешевле и быстрее.
8.  **Мониторьте размер `fs.chunks`** — это основное потребление диска.

### SRE / DevOps / Production

9.  **ChunkSize по профилю файлов** — 255 KB (default) для общих файлов; 1 MB для больших бэкапов/видео; 64 KB для множества мелких файлов. Тестируйте на своей нагрузке.
10. **Индексы на метаданных** — создавайте индексы на часто используемых полях `metadata.*` (например, `metadata.owner`, `metadata.tags`).
11. **Регулярная очистка** — настройте cron/job для удаления старых файлов и осиротевших чанков (см. сценарии 9).
12. **Мониторинг через mongodb_exporter** — собирайте метрики `mongodb_gridfs_files_total`, `mongodb_gridfs_chunks_total`, `mongodb_gridfs_bytes_total`. Настройте алерты на рост.
13. **Бэкап с PBM** — PBM бэкапит GridFS коллекции автоматически. Проверяйте восстановление GridFS файлов в DR-тестах. См. **[Бэкап и DR](./mongodb-backup-dr.md)**.
14. **Чтение с secondary** — для некритичных чтений используйте `readPreference: secondaryPreferred` (drivers), чтобы не нагружать Primary.
15. **Сжатие на уровне приложения** — сжимайте файлы перед загрузкой (gzip/zstd), если они хорошо сжимаются (логи, JSON, текст). GridFS не сжимает чанки сам.
16. **Именованные buckets по доменам** — `images.files`, `backups.files`, `logs.files` — изоляция по типам, разные retention policies, разные chunkSize.
17. **Валидация после загрузки** — всегда проверяйте md5 (`filemd5` команда) и размер после `put`.
18. **Ограничение одновременных загрузок** — большие файлы потребляют память и сеть. Используйте семафоры/очереди в приложении.
19. **Replica Set обязателен** — GridFS в standalone не даёт отказоустойчивости. Всегда RS минимум 3 узла.
20. **Оптимизация чтения** — для последовательного чтения большой части файла увеличьте `batchSize` курсора или используйте драйверный `readChunkSize`.

---

## Дополнительная информация

*   **[Моделирование данных](./mongodb-modeling.md)** — когда документ, когда GridFS.
*   **[Шардирование](./mongodb-sharding.md)** — шардирование `fs.chunks`.
*   **[Импорт/экспорт](./mongodb-import-export.md)** — массовая загрузка данных.
*   **[Администрирование](./mongodb-administration.md)** — лимит 16 MB, `mongofiles`.
*   **[Мониторинг](./mongodb-monitoring.md)** — mongodb_exporter, метрики GridFS.
*   **[Бэкап и DR](./mongodb-backup-dr.md)** — бэкап GridFS коллекций, PITR.
*   [GridFS Specification](https://www.mongodb.com/docs/manual/core/gridfs/)
*   [mongofiles](https://www.mongodb.com/docs/database-tools/mongofiles/)
