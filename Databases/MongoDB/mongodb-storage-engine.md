# MongoDB: Движок хранения WiredTiger

**Актуально для:** MongoDB 8.0.x

---

## Определения

**WiredTiger** — современный, высокопроизводительный движок хранения данных, являющийся стандартом в MongoDB с версии 3.2. Он спроектирован для максимально эффективного использования многоядерных процессоров и больших объемов оперативной памяти. Начиная с MongoDB 4.0, MMAPv1 полностью удалён из кодовой базы.

*   **MVCC (Multi-Version Concurrency Control):** Механизм управления конкурентным доступом. Читатели получают согласованный "снимок" данных на момент начала операции, не блокируя при этом писателей. Это обеспечивает атомарность на уровне документов без тяжелых блокировок.
*   **WiredTiger Cache:** Область оперативной памяти, где движок хранит рабочие данные и индексы в несжатом виде для максимально быстрого доступа. Размер по умолчанию — максимум из `50% (RAM - 1GB)` или `0.256 GB`.
*   **WAL (Write-Ahead Logging):** Метод журналирования, при котором все изменения сначала записываются в последовательный журнал на диске, а затем применяются к основным файлам данных. В WiredTiger журнал хранится в оперативной памяти и сбрасывается на диск при накоплении 128 kB или по истечении `commitIntervalMs`.
*   **Dirty Cache (Грязный кэш):** Объем данных в WiredTiger Cache, которые были изменены, но еще не сброшены на диск во время чекпоинта.
*   **Journal Compressor:** Алгоритм сжатия, применяемый к данным журнала перед записью на диск. По умолчанию — Snappy.
*   **Block Compressor:** Алгоритм сжатия данных коллекций и индексов на уровне блоков.
*   **Working Set:** Объем данных и индексов, к которым приложение обращается наиболее часто. В идеале должен целиком помещаться в WiredTiger Cache.
*   **Page Fault:** Ситуация, когда запрашиваемые данные отсутствуют в WiredTiger Cache и должны быть прочитаны с диска, что вызывает рост latency.

---

## Архитектура и механизмы

### 1. Управление памятью

WiredTiger использует **двухуровневое кэширование**:
1.  **WiredTiger Cache:** Хранит данные в несжатом виде. По умолчанию занимает `max(50% (RAM - 1GB), 0.256 GB)`.
2.  **Filesystem Cache:** Использует оставшуюся свободную память ОС для хранения сжатых блоков данных с диска. Это снижает нагрузку на ввод-вывод при повторном чтении.

**Критическое замечание для контейнеров (K8s/Docker):** Если не ограничить `cacheSizeGB`, MongoDB может попытаться занять память исходя из ресурсов хоста, а не лимитов контейнера, что приведет к немедленному **OOM Kill**.

### 2. Структура данных на диске

WiredTiger хранит данные в виде файлов с расширением `.wt` в директории `dbPath` (по умолчанию `/var/lib/mongodb`):

```
/var/lib/mongodb/
├── collection-*.wt          # Данные коллекций
├── index-*.wt               # Данные индексов
├── journal/
│   ├── j._0                 # Файлы журнала (до ~100MB каждый)
│   └── ...
├── diagnostic.data/         # Диагностические данные (если включено)
├── mongod.lock              # Файл блокировки
├── WiredTiger               # Метаданные движка
├── WiredTiger.lock
├── WiredTiger.turtle        # Конфигурация коллекций и индексов
└── storage.bson             # Конфигурация хранилища
```

**Важно:** Директория `journal/` должна находиться на быстром диске (NVMe). Размер каждого файла журнала ограничен ~100 MB.

### 3. Чекпоинты (Checkpoints)

Каждые 60 секунд (по умолчанию) WiredTiger выполняет чекпоинт:
*   Сбрасывает все "грязные" страницы из кэша в файлы данных на диск.
*   Создает точку восстановления. В случае сбоя база восстановится из последнего чекпоинта + данных из журнала (Journal).
*   **Влияние на I/O:** Чекпоинты могут вызывать всплески (spikes) дисковой нагрузки.
*   **В MongoDB 8.0** процесс чекпоинта стал более плавным, но для SRE важно мониторить `wiredTiger.transaction.checkpoint amount written`.

### 4. Журналирование (Journaling)

Журнал обеспечивает устойчивость данных (Durability) между чекпоинтами:
*   Данные журнала буферизируются в оперативной памяти и сбрасываются на диск при накоплении 128 kB или по истечении `commitIntervalMs` (по умолчанию 100 мс).
*   Также сброс происходит при запросе `writeConcern: majority` или `j: true`.
*   Файлы журнала (`Journal`) хранятся в директории `journal/` и автоматически удаляются после успешного чекпоинта.
*   **Journal Compressor:** По умолчанию используется Snappy. Можно изменить через `storage.wiredTiger.engineConfig.journalCompressor`.

### 5. Сжатие данных

WiredTiger поддерживает сжатие на уровне блоков для коллекций и индексов:
*   **Snappy (Default):** Оптимальный баланс между коэффициентом сжатия и нагрузкой на CPU.
*   **Zstandard (zstd):** Обеспечивает лучшее сжатие (до 30% эффективнее Snappy), но требует больше ресурсов CPU.
*   **Prefix Compression:** Используется для индексов, сжимая общие префиксы ключей. Управляется через `storage.wiredTiger.indexConfig.prefixCompression`.
*   **Columnar Compression:** Для Time-series коллекций (начиная с 5.2). Кодирует значения полей отдельно (delta, RLE, simple-8b), что дает экономию до 90% на временных рядах.
*   **Direct Columnar Compression (8.0+):** Новая технология сжатия, оптимизированная для колоночного представления данных в Time-series коллекциях.

### 6. Шифрование данных (Encryption at Rest)

*   **Enterprise Edition:** Нативное шифрование WiredTiger. Ключи хранятся в KMS (локальном или внешнем через KMIP).
*   **Community Edition:** Через dm-crypt/LUKS или шифрование на уровне файловой системы. Прозрачно для MongoDB, но влияет на I/O latency.
*   **Queryable Encryption (FLE 2.0):** В MongoDB 8.0 добавлена поддержка range-запросов. Не поддерживается в sharded clusters.

---

## Конфигурационные параметры

### Основные параметры WiredTiger

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `storage.wiredTiger.engineConfig.cacheSizeGB` | `max(50% (RAM - 1GB), 0.256 GB)` | Размер WiredTiger Cache. Для контейнеров — по лимиту RAM пода. |
| `storage.wiredTiger.engineConfig.directoryForIndexes` | `false` | `true` для разделения данных и индексов на разные директории/диски. |
| `storage.wiredTiger.collectionConfig.blockCompressor` | `snappy` | Алгоритм сжатия коллекций: `snappy`, `zstd`, `none`. |
| `storage.wiredTiger.engineConfig.journalCompressor` | `snappy` | Алгоритм сжатия журнала: `snappy`, `zstd`, `none`. |
| `storage.wiredTiger.indexConfig.prefixCompression` | `true` | Включение префиксного сжатия для индексов. |

### Параметры журналирования

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `storage.journal.enabled` | `true` (всегда включено в 8.0) | Журналирование. Параметр удалён в 8.0, журнал всегда активен. |
| `storage.journal.commitIntervalMs` | `100` | Интервал сброса журнала на диск в миллисекундах. |

### Параметры файловой системы и хранилища

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `storage.dbPath` | `/var/lib/mongodb` | Директория данных MongoDB. |
| `storage.directoryPerDB` | `false` | Создание отдельной директории для каждой базы данных. |
| `storage.journal.enabled` | `true` | Журналирование включено по умолчанию. |

---

## Практические сценарии

### 1. Настройка `mongod.conf` для production

```yaml
# /etc/mongod.conf
storage:
  dbPath: /var/lib/mongodb
  journal:
    enabled: true
  wiredTiger:
    engineConfig:
      cacheSizeGB: 8  # 50% от RAM, но не более 64GB
      directoryForIndexes: false  # true для разделения данных и индексов
      journalCompressor: snappy  # snappy/zstd/none
    collectionConfig:
      blockCompressor: zstd  # snappy/zstd/none
    indexConfig:
      prefixCompression: true

net:
  port: 27017
  bindIp: 127.0.0.1,10.0.5.42
  tls:
    mode: disabled  # requireTLS для production

replication:
  replSetName: rs0

systemLog:
  destination: file
  path: /var/log/mongodb/mongod.log
  logAppend: true
  logRotate: rename
  timeStampFormat: iso8601-utc

processManagement:
  fork: false
  pidFilePath: /var/run/mongodb/mongod.pid
```

**Валидация:**
```bash
mongosh --eval "db.getCmdLineOpts()"
# → Проверка, что параметры совпадают с ожидаемыми
```

### 2. Тюнинг кэша для Kubernetes

В манифесте или `mongod.conf` необходимо всегда учитывать лимиты RAM:
```yaml
storage:
  wiredTiger:
    engineConfig:
      # Если лимит пода 4ГБ, кэш должен быть ~1.5ГБ
      cacheSizeGB: 1.5
```

### 3. Оптимизация дискового I/O

Для высоконагруженных систем рекомендуется разделять данные и индексы по разным директориям (можно примонтировать разные диски):
```yaml
storage:
  wiredTiger:
    engineConfig:
      directoryForIndexes: true
```

### 4. Проверка состояния кэша в mongosh

```javascript
db.serverStatus().wiredTiger.cache["tracked dirty bytes in the cache"] // # → Текущий объем грязных данных
db.serverStatus().wiredTiger.cache["bytes currently in the cache"] // # → Общая загрузка кэша
db.serverStatus().wiredTiger.cache["bytes read into cache"] // # → Чтение с диска
db.serverStatus().wiredTiger.cache["pages written from cache"] // # → Запись на диск
```

### 5. Мониторинг чекпоинтов

```javascript
db.serverStatus().wiredTiger.transaction["checkpoint amount written"] // # → Объем данных, сброшенных за последний чекпоинт
db.serverStatus().wiredTiger.transaction["checkpoint min time between checkpoints (usecs)"] // # → Минимальный интервал между чекпоинтами
```

### 6. Управление кэшем под высокой нагрузкой (SRE Guide)

WiredTiger начинает вытеснять данные из памяти по достижении определенных порогов:
*   **`eviction_trigger`**: % заполнения кэша, при котором фоновые потоки начинают агрессивную очистку (по умолчанию 95%).
*   **`eviction_target`**: целевой % заполнения после очистки (по умолчанию 80%).

**Рекомендация SRE:** Если вы видите рост задержек при записи, снизьте пороги в `mongod.conf`:
```yaml
storage:
  wiredTiger:
    engineConfig:
      configString: "eviction=(low=70,high=90)"
```

### 7. Работа с тикетами (Read/Write Tickets)

Тикеты ограничивают количество параллельных операций внутри движка:
*   Проверить текущее состояние: `db.serverStatus().wiredTiger.concurrentTransactions`.
*   **Проблема:** Если `available` стремится к 0 — запросы встают в очередь (Queue), что вызывает лавинообразный рост latency.
*   **Решение:** Не увеличивайте количество тикетов бездумно. Обычно это симптом медленных дисков или отсутствия индексов.

### 8. Планирование容量 (Capacity Planning)

Оценивайте размер данных на диске:
```bash
# Размер данных и индексов
mongosh --eval "db.stats()"
# → dataSize, indexSize, storageSize

# Свободное место на диске
df -h /var/lib/mongodb
```

**Рекомендации:**
*   Свободное место должно быть не менее **20%** от размера данных для чекпоинтов и временных файлов.
*   Для индексов резервируйте дополнительно **10-30%** от размера данных.
*   Размер журнала: ~100 MB на файл, до 3-5 файлов при пиковой нагрузке.

---

## Устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий I/O Wait каждые 60с** | Тяжелые чекпоинты. | `iostat -x 1`, `mongotop` | Использовать быстрые диски (NVMe) или увеличить RAM. |
| **Cache Pressure (Медленное чтение)** | Working Set больше, чем `cacheSizeGB`. | `db.serverStatus().wiredTiger.cache` | Увеличить объем RAM или оптимизировать индексы. |
| **Dirty Cache > 5%** | Запись идет быстрее, чем вытеснение (Eviction). | `db.serverStatus().wiredTiger.cache` | Проверить производительность диска. Снизить нагрузку или масштабироваться. |
| **OOM Kill** | Кэш WiredTiger + накладные расходы на соединения превысили лимит памяти. | `dmesg`, `mongostat` | Снизить `cacheSizeGB` или ограничить количество соединений (`maxIncomingConnections`). |
| **Page Fault (роет latency)** | Данные не помещаются в WiredTiger Cache. | `db.serverStatus().wiredTiger.cache` | Увеличить RAM или оптимизировать запросы. |
| **Журнал переполнен** | Слишком большие транзакции или медленный диск. | `db.serverStatus().wiredTiger.cache` | Увеличить скорость диска, уменьшить размер транзакций. |
| **Фрагментация данных** | Частые вставки/удаления без compact. | `db.collection.stats().wiredTiger.block-manager` | Выполнить `db.runCommand({ compact: 'collection' })` в maintenance window. |
| **Повреждение WiredTiger метаданных** | Аварийное отключение или ошибки диска. | Логи mongod | Выполнить `mongod --repair` или восстановить из бэкапа. |

### Диагностические команды

```bash
# Проверка статуса кластера
mongosh --eval "rs.status()"

# Проверка использования кэша
mongosh --eval "db.serverStatus().wiredTiger.cache"

# Проверка активных операций
mongosh --eval "db.currentOp({ active: true, secs_running: { $gt: 5 } })"

# Проверка чекпоинтов
mongosh --eval "db.serverStatus().wiredTiger.transaction"

# Анализ I/O по коллекциям
mongotop --host rs0/mongo-1:27017 --rowcount 60

# Реальное время (ops/sec, память, очереди)
mongostat --host rs0/mongo-1:27017 --rowcount 60
```

---

## Лучшие практики (SRE)

### Работа с кэшем

1.  **Всегда задавайте `cacheSizeGB` явно:** В контейнерах MongoDB использует всю RAM хоста, если лимит не задан. Это приводит к OOM Kill.
2.  **Мониторинг Cache Eviction:** Следите за метрикой `wiredTiger.cache.evictions` в `db.serverStatus()`. Рост этого значения при отсутствии пиковых нагрузок указывает на недостаток RAM.
3.  **Working Set в RAM:** Убедитесь, что Working Set помещается в WiredTiger Cache. Иначе происходит Cache Eviction и рост latency.
4.  **Эвакуация при высокой нагрузке:** Для SRE важно мониторить `wiredTiger.transaction.checkpoint amount written` и `iostat` во время чекпоинтов.

### Работа с дисками

5.  **Файловая система:** Используйте **XFS**. WiredTiger работает эффективнее с XFS, чем с ext4.
6.  **Журнал на быстром диске:** Размещение Journal на быстром SSD снижает latency записи. На HDD journal commit (каждые 100 мс) создает дополнительную нагрузку.
7.  **Разделение данных и индексов:** Для высоконагруженных систем используйте `directoryForIndexes: true` и монтируйте разные диски.
8.  **NVMe для production:** Чекпоинты и фоновые операции создают всплески I/O. На HDD это критично — используйте только SSD/NVMe.

### Мониторинг и алертинг

9.  **Ключевые метрики:**
    *   `db.serverStatus().wiredTiger.cache` — использование кэша, evictions, dirty bytes.
    *   `db.serverStatus().wiredTiger.transaction` — чекпоинты, amount written.
    *   `db.serverStatus().wiredTiger.concurrentTransactions` — доступность тикетов.
    *   `mongostat` — ops/sec, блокировки, очереди, flushes.
    *   `mongotop` — I/O по коллекциям.
10. **SRE алерты:**
    *   WiredTiger Cache > 90% — предупреждение.
    *   `wiredTiger.cache.evictions` растет при отсутствии пиков — критично.
    *   Dirty Cache > 5% при стабильной нагрузке — предупреждение.
    *   Checkpoint spikes > 500MB/сек — предупреждение.

### Безопасность

11. **Шифрование на диске:** В Enterprise Edition используйте нативное шифрование WiredTiger. В Community — dm-crypt/LUKS.
12. **Права на файлы:** Директория `/var/lib/mongodb` должна принадлежать пользователю `mongodb:mongodb` с правами `700`.
13. **SELinux/AppArmor:** На RHEL/CentOS настройте политики SELinux для доступа к `dbPath` и журналу.

---

## Граничные случаи

### 1. Контейнеры и OOM Kill

MongoDB в контейнере (K8s/Docker) использует память хоста, если `cacheSizeGB` не задан явно. Это приводит к OOM Kill.

**Решение:** Всегда задавайте `storage.wiredTiger.engineConfig.cacheSizeGB` в `mongod.conf` или через флаг `--wiredTigerCacheSizeGB`. Для контейнера с лимитом 4GB → `cacheSizeGB: 1.5`.

### 2. Большие транзакции и `TransactionTooLargeForCache`

Объем данных в транзакции не должен превышать capacity WiredTiger Cache. Начиная с MongoDB 6.2, сервер не retry такую транзакцию автоматически.

**Решение:** Разбить транзакцию на более мелкие этапы. Увеличить `cacheSizeGB` или добавить RAM.

### 3. Фрагментация и compact

Compact может занимать часы для больших коллекций (>100GB). На HDD это критично. Для SSD/NVMe compact выполняется быстрее, но все равно создает всплеск I/O.

**Решение:** Выполняйте compact в maintenance window. Мониторьте через `db.currentOp()`. На SSD/NVMe фрагментация менее критична — compact может не требоваться.

### 4. Журнал на отдельном диске

Размещение Journal на быстром SSD снижает latency записи. На HDD journal commit (каждые 100 мс) создает дополнительную нагрузку.

**Решение:** Для production используйте NVMe для данных и Journal. На контейнерах (K8s/Docker) используйте fast local SSD для `dbPath`.

### 5. Восстановление после потери > 50% узлов в Replica Set

При потере кворума (большинства узлов) Replica Set не может выбрать Primary. Данные остаются доступны для чтения, но запись невозможна.

**Решение:** Используйте force reconfig для восстановления кворума на оставшихся узлах. Добавьте новые узлы обратно. Восстановите данные с бэкапа если необходимо.

---

## Чистка и восстановление после инцидентов

### Восстановление после `mongod --repair`

```bash
# Остановка mongod
systemctl stop mongod

# Проверка диска
df -h /var/lib/mongodb
# → Достаточно свободного места (минимум 2x от размера данных)

# Запуск repair
mongod --dbpath /var/lib/mongodb --repair
# → Восстановление данных из Journal и файлов

# Запуск mongod
systemctl start mongod

# Валидация
mongosh --eval "db.serverStatus().wiredTiger.cache"
# → Нормальное использование кэша
```

**Предупреждение:** `mongod --repair` может привести к потере последних изменений, не записанных в Journal. Используйте только как последний resort.

### Очистка временных файлов после сбоя

```bash
# Проверка временных файлов
ls -la /var/lib/mongodb/tmp/
# → Временные файлы от сбоев

# Очистка (только если mongod остановлен)
rm -f /var/lib/mongodb/tmp/*
```

### Проверка целостности данных

```javascript
// Валидация всех баз
db.validate()
// → { "valid" : true, "errors" : [ ], ... }

// Валидация конкретной коллекции
db.collection.validate()
// → { "valid" : true, "wiredTiger" : { ... } }
```

---

## Дополнительная информация

*   **[Общий обзор MongoDB](./mongodb.md)** — основы и системные требования.
*   **[Администрирование](./mongodb-administration.md)** — мониторинг и конфигурация.
*   **[Индексы в MongoDB](./mongodb-indexes.md)** — хранение B-Tree структур.
*   **[Репликация](./mongodb-replication.md)** — Replica Set, Oplog, кворум.
*   **[Шардирование](./mongodb-sharding.md)** — распределение данных, CWWC, Config Shard.
*   **[Транзакции и согласованность](./mongodb-transactions.md)** — ACID в NoSQL.
*   **[Безопасность](./mongodb-security.md)** — RBAC, TLS, шифрование.
*   **[Time-series коллекции](./mongodb-time-series.md)** — специфика сжатия в 8.0.
