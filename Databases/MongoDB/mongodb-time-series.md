# MongoDB: Time-series коллекции

**Актуально для:** MongoDB 8.0.x

---

## Определения

**Time-series коллекции** — специализированный тип коллекций в MongoDB, оптимизированный для высокоскоростной записи и эффективного хранения последовательностей данных во времени (метрики, логи, события IoT, финансовые котировки). Фундамент для сценариев мониторинга и observability.

*   **Measurement (Измерение):** Документ, содержащий все метрики в определенный момент времени. Состоит из `timeField`, `metaField` и изменяющихся полей-значений.
*   **Bucketing (Баккетизация):** Внутренний механизм MongoDB, объединяющий несколько measurement из одного источника в один баккет (WiredTiger-запись) для снижения метаданных и ускорения I/O.
*   **Meta Field:** Поле с идентификатором источника данных (например, `sensorId`, `hostname`). По этому полю происходит группировка в баккеты. Кардинальность `metaField` напрямую влияет на количество баккетов и производительность.
*   **Granularity:** Ожидаемая частота записей для одного источника: `seconds` (по умолчанию), `minutes`, `hours`. Определяет максимальный временной диапазон внутри одного баккета.
*   **Bucket Span:** Максимальный временной интервал, который может покрывать один баккет: для `seconds` — 1 час, для `minutes` — 24 часа, для `hours` — 30 дней.
*   **Columnar Storage:** Физическое хранение значений полей рядом друг с другом. В MongoDB 8.0 для TS-коллекций реализовано через Direct Columnar Compression, дающее экономию до 90% по сравнению с обычными коллекциями.
*   **Block Processing:** Режим выполнения агрегаций над целыми блоками данных одновременно (векторизация), дающий ускорение до 40x для аналитических запросов. Детали реализации описаны в [Агрегация Framework](./mongodb-aggregation.md).
*   **TTL (Time-To-Live):** Автоматическое удаление measurement по истечении времени через `expireAfterSeconds`. Удаление происходит на уровне баккетов фоновой задачей каждые 60 секунд.
*   **Custom Bucketing:** Начиная с MongoDB 6.3, можно использовать `bucketMaxSpanSeconds` и `bucketRoundingSeconds` вместо `granularity` для точного контроля границ баккетов.

---

## Базовые концепции

### Внутреннее представление данных

MongoDB treats time-series коллекции как writable non-materialized views, backed by внутренней системной коллекцией. При вставке данных MongoDB автоматически организует их в оптимизированный формат хранения:

```
Пользовательская вставка:
  { timestamp: ISODate(...), metadata: { sensorId: 1 }, temp: 25.4 }

Внутреннее представление (buckets collection):
  {
    _id: ...,
    control: { version: 2, range: [minTime, maxTime], sensorId: 1 },
    data: [
      { timestamp: ..., temp: 25.4 },
      ...
    ],
    meta: { sensorId: 1 }
  }
```

Прямое взаимодействие с внутренней buckets-коллекцией запрещено и может привести к повреждению данных.

### Жизненный цикл записи

1. Клиент отправляет bulk/insertMany с measurement, упорядоченными по `metaField`.
2. СУБД группирует measurement по `metaField` и временным границам в баккеты.
3. Данные сжимаются колоночно (Direct Columnar Compression).
4. Изменения фиксируются в Journal и реплицируются через Oplog.
5. При превышении лимитов (1000 документов или 16 МБ) создается новый баккет.

### Жизненный цикл TTL-удаления

1. Фоновая задача проверяет истекшие measurement каждые 60 секунд.
2. Когда все measurement внутри баккета истекли, сам баккет помечается для удаления.
3. Удаление происходит асинхронно; задержка может достигать нескольких минут при высокой нагрузке.
4. Начиная с MongoDB 8.0, TTL поддерживает данные с timestamp до 1970 года (исправлена проблема с epoch).

---

## Практические сценарии

### 1. Создание коллекции для инфраструктурного мониторинга

```javascript
db.createCollection("host_metrics", {
   timeseries: {
      timeField: "ts",
      metaField: "host",
      granularity: "seconds"
   },
   expireAfterSeconds: 604800 // Хранить данные 7 дней
})
```

### 2. Создание коллекции для финансовых котировок

```javascript
db.createCollection("stock_prices", {
   timeseries: {
      timeField: "timestamp",
      metaField: "ticker",
      granularity: "seconds"
   },
   expireAfterSeconds: 31536000 // Хранить данные 1 год
})
```

### 3. Изменение TTL на существующей коллекции

```javascript
db.runCommand({
   collMod: "host_metrics",
   expireAfterSeconds: 1209600 // Изменить на 14 дней
})
```

### 4. Проверка параметров коллекции

```javascript
db.runCommand({ listCollections: 1, filter: { name: "host_metrics" } })
```

### 5. Изменение granularity через collMod (требуется MongoDB 6.3+)

```javascript
db.runCommand({
   collMod: "host_metrics",
   timeseries: {
      bucketMaxSpanSeconds: 3600,
      bucketRoundingSeconds: 3600
   }
})
```

### 6. Валидация производительности агрегаций

```javascript
db.host_metrics.explain("executionStats").aggregate([
   {
      $group: {
         _id: "$host",
         avgCpu: { $avg: "$cpu" },
         maxCpu: { $max: "$cpu" }
      }
   }
])
// Проверить наличие Block Processing в winningPlan
```

### 7. Шардирование временных рядов (MongoDB 8.0+)

```javascript
sh.shardCollection("iot_db.sensor_data", { "metadata.sensorId": 1 })
```

> **Важно:** Начиная с MongoDB 8.0, использование `timeField` в качестве шard key deprecated. Шардирование по `timeField` создает "горячие" шарды.

---

## Операции и команды

### Управление коллекцией

| Команда | Описание |
| :--- | :--- |
| `db.createCollection(name, { timeseries: {...}, expireAfterSeconds: N })` | Создать TS-коллекцию |
| `db.runCommand({ collMod: "name", timeseries: {...} })` | Изменить параметры баккетизации |
| `db.runCommand({ collMod: "name", expireAfterSeconds: N })` | Изменить или отключить TTL (`"off"`) |
| `db.runCommand({ listCollections: 1, filter: { name: "name" } })` | Проверить текущие параметры |
| `db.collection.drop()` | Удалить TS-коллекцию (нельзя downgrade без удаления) |

### Мониторинг и диагностика

| Команда / Метод | Что показывает |
| :--- | :--- |
| `db.serverStatus().wiredTiger.cache` | Использование кэша, hit ratio |
| `db.serverStatus().wiredTiger.perf` | Перформанс-метрики WiredTiger |
| `db.host_metrics.stats()` | Статистика коллекции: размер, индексы, баккеты |
| `db.serverStatus().oplog` | Состояние Oplog (для реплицированных развертываний) |
| `rs.printSecondaryReplicationInfo()` | lag и oplog window на вторичных узлах |
| `db.serverStatus().metrics` | Внутренние метрики, включая time series |

---

## Ограничения и особенности

### Изменение и удаление документов

- Операции `update` могут изменять только поля внутри `metaField`. Изменение остальных полей measurement ограничено.
- Фильтр в `delete` должен включать `metaField` для точного указания measurement.
- Bulk-операции (`bulkWrite`) с mixed-типами (insert + update + delete) в MongoDB 8.0 работают внутри одной TS-коллекции.

### Индексы

- MongoDB 6.3+ автоматически создает compound index `{ metaField: 1, timeField: 1 }`.
- Дополнительные индексы замедляют запись; создавайте только для частых query-паттернов.
- `distinct` на TS-коллекциях неэффективен; используйте `$group` с compound index.

### Шардирование

- Zone sharding не поддерживается для TS-коллекций; балансировщик распределяет данные равномерно по всем шардам.
- При использовании `metaField` как shard key убедитесь в достаточной кардинальности для равномерного распределения.

### Обратная совместимость

- TS-коллекции являются backwards-incompatible feature: перед downgrade MongoDB ниже 6.0 или 5.3 необходимо удалить все TS-коллекции.

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Медленная запись** | Слишком много индексов или неверная `granularity` | `db.collection.explain("executionStats").insert(...)` | Скорректировать `granularity` через `collMod`. Убрать лишние индексы. |
| **Раздувание объема** | Высокая кардинальность `metaField` или отсутствие сжатия | `db.collection.stats().wiredTiger.block-manager` | Вынести общие признаки в `metaField`. Проверить `cacheSizeGB`. |
| **Данные не удаляются по TTL** | TTL-монитор не успевает за потоком | `db.serverStatus().metrics` | Увеличить размер баккета (`granularity: hours`), использовать шардирование для распределения TTL-нагрузки. |
| **Hot Shard при шардировании** | Использование `timeField` как shard key | `db.printShardingStatus()` | Перешардировать на `metaField`. |
| **Ошибки при bulkWrite** | Несогласованный порядок полей в документах | Логи mongod | Привести к consistent field order. |
| **Высокое потребление RAM** | Columnar cache не умещается в WiredTiger Cache | `db.serverStatus().wiredTiger.cache` | Увеличить `cacheSizeGB` (до 50% RAM) или добавить RAM. |
| **Ошибка upgrade/downgrade** | Присутствие TS-коллекций при downgrade | Версия FCV | Удалить TS-коллекции перед downgrade. |

---

## Лучшие практики

1.  **Всегда используйте `metaField`:** Без него баккетизация неэффективна, и вы получите обычную коллекцию в "обертке" TS.
2.  **Выбирайте `granularity` точно:** Если данные приходят раз в час, а стоит `seconds`, будет создано слишком много полупустых баккетов. Используйте `bucketMaxSpanSeconds` для кастомных интервалов.
3.  **Bulk inserts с одинаковым `metaField`:** Вставляйте measurement одного источника одним `insertMany` с `ordered: false`. Это снижает стоимость операции до одного insert на источник.
4.  **Consistent field order:** Все measurement должны иметь одинаковый порядок полей. Это критично для Columnar Compression.
5.  **Округляйте числовые значения:** Избегайте лишних знаков после запятой в метриках — это улучшает коэффициент сжатия.
6.  **Избегайте пустых полей:** Пропустите поля с пустыми массивами/объектами в measurement — это вызывает schema change и снижает сжатие.
7.  **Мониторьте TTL backlog:** Следите за размером не удаленных по TTL данных. Рост backlog при отсутствии пиков нагрузки означает нехватку IOPS или CPU.
8.  **Автоматический индекс:** Начиная с 6.3, compound index создается автоматически. Не дублируйте его вручную.
9.  **Используйте `$group` вместо `distinct`:** `distinct` неэффективен для TS-коллекций из-за их внутренней структуры.
10. **Capacity planning:** Оценивайте размер данных как `measurements_per_second * avg_size * retention_seconds * sources`. Учитывайте 90% экономию места от Columnar Compression.

---

## Гранicные случаи

### 1. Временные метки до 1970 года

В версиях до 8.0 TTL-удаление не работало для timestamp до 1970-01-01 (epoch). В MongoDB 8.0 это исправлено (SERVER-97368). Если вы храните исторические данные с timestamp до 1970, убедитесь что развертывание обновлено до 8.0.x.

### 2. Oversized writes

Вставка measurement, превышающих 16 МБ, приводит к ошибке. В MongoDB 8.0 улучшена обработка oversized writes (SERVER-108565), но ограничение документа остается. Для больших payload используйте GridFS или разбейте measurement на части.

### 3. High cardinality `metaField`

Если `metaField` имеет экстремально высокую кардинальность (миллионы уникальных значений), баккетизация теряет эффективность. В этом случае рассмотрите:
- Агрегацию `metaField` (например, добавить `region` или `datacenter` для группировки)
- Уменьшение retention period
- Использование нескольких TS-коллекций с разными `metaField`

### 4. Replication и Columnar Cache

При репликации TS-данных secondary узлы должны применять сжатие independently. Рост `wiredTiger.cache.evictions` на secondary при отсутствии нагрузки на primary может указывать на недостаток RAM. Рекомендуется равномерное распределение RAM между узлами.

### 5. `timeField` в `metaField`

MongoDB автоматически переупорядочивает поля внутри `metaField`. Запросы на скалярные подполя (`metaField.sensorId`) работают эффективнее, чем на весь объект `metaField`.

---

## Чистка и восстановление после инцидентов

### Проверка битых баккетов

```javascript
// Поиск баккетов с невалидными measurement (требует доступа к внутренней коллекции)
// Внимание: внутренние коллекции предназначены только для чтения
db.getSiblingDB("config").db.getCollectionNames().forEach(function(coll) {
   if (coll.indexOf("system.buckets") !== -1) {
      print(coll);
   }
});
```

### Очистка orphaned баккетов

После принудительного завершения `mongod` или сбоя replication могут остаться баккеты, не соответствующие текущим measurement. При наличии подозрений на битые данные:

```bash
# Валидация данных (read-only)
mongod --dbpath /var/lib/mongodb --repair
```

### Восстановление после сбоя TTL

Если фоновый TTL-процесс падал из-за переполнения WiredTiger Cache:
1. Увеличьте `cacheSizeGB` в `mongod.conf`.
2. Перезапустите `mongod`.
3. Проверьте `db.serverStatus().metrics.ttl` для восстановления фоновой задачи.

### Очистка storage после удаления TS-коллекции

```bash
# Рекомендуется выполнить compact после массового удаления TS-данных
mongosh --eval "db.runCommand({ compact: 'host_metrics' })"
```

---

## Дополнительная информация

*   **[Общий обзор MongoDB](./mongodb.md)** — основы, архитектура, системные требования.
*   **[Движок WiredTiger](./mongodb-storage-engine.md)** — детали сжатия, Columnar Compression, кэширование.
*   **[Агрегация Framework](./mongodb-aggregation.md)** — Block Processing, оконные функции.
*   **[Шардирование](./mongodb-sharding.md)** — масштабирование TS-кластеров, метрики шардов.
*   **[Индексы](./mongodb-indexes.md)** — compound index, стратегии индексирования.
*   **[Администрирование](./mongodb-administration.md)** — бэкапы, мониторинг, обновление.
*   **[Высокая доступность](./high_availability.md)** — Replica Set, отказоустойчивость.
*   **[Установка MongoDB на Ubuntu](./installation_ubuntu.md)**
