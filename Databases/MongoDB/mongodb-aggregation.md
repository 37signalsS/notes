# MongoDB: Агрегация (Aggregation Framework)

**Актуально для:** MongoDB 8.0.x

## Определения

**Aggregation Framework** — это мощный вычислительный движок MongoDB, построенный на концепции **конвейерной обработки** (Data Pipeline). Он позволяет трансформировать, группировать и анализировать данные на стороне сервера, возвращая приложению уже готовый результат.

*   **Pipeline (Конвейер):** Массив стадий, через которые последовательно проходят документы. Выход одной стадии является входом для следующей.
*   **Stage (Стадия):** Конкретная операция над потоком документов (фильтрация, группировка, сортировка).
*   **Expression (Выражение):** Вычислительная логика внутри стадий (арифметические действия, работа со строками, датами).
*   **Operator (Оператор):** Ключевое слово, определяющее действие (например, `$sum`, `$avg`, `$push`).

---

## Архитектура и оптимизация

### 1. Автоматическая оптимизация (Optimizer)
MongoDB перед выполнением переупорядочивает стадии для повышения эффективности:
*   **Stage Coalescing:** Объединение `$sort` и `$limit`, если они идут друг за другом (выполняется как "Top-N" сортировка).
*   **Match Forwarding:** Перемещение стадии `$match` как можно ближе к началу конвейера для использования индексов и сокращения объема данных.
*   **Projection Pushing:** Удаление ненужных полей на ранних этапах.
*   **$lookup/$unwind/$match Coalescence:** Объединение `$unwind`, следующего сразу после `$lookup`, в саму стадию `$lookup`, а также последующего `$match` по полю `as`. Это исключает создание больших промежуточных документов.

### 2. Ограничения по памяти
*   **100 MB RAM:** По умолчанию каждая стадия конвейера ограничена 100 МБ оперативной памяти.
*   **`allowDiskUse: true`:** Позволяет стадиям (например, тяжелой сортировке) сбрасывать временные данные на диск при превышении лимита RAM.
*   **Streaming vs Blocking:** Стадии вроде `$match` передают данные поточно, тогда как `$group` и `$sort` являются блокирующими (ждут получения всех документов перед началом работы).

#### Мониторинг spills и давления на память
Для SRE важно отслеживать, когда агрегации начинают сбрасывать данные на диск:
*   **`explain("executionStats")`:** В выводе для стадий `$sort`, `$group`, `$setWindowFields`, `$bucketAuto`, `$graphLookup` и `$lookup` (при использовании slot-based engine) присутствуют поля `usedDisk`, `spills`, `spilledBytes`, `spilledRecords`, `spilledDataStorageSize`, `peakTrackedMemBytes` (начиная с 8.0).
*   **Диагностическое логирование:** При превышении лимита памяти без `allowDiskUse: true` запрос завершится ошибкой `Query exceeded memory limit`. Включите `allowDiskUse` для тяжелых аналитических конвейеров или пересмотрите схему индексации.
*   **Профилировщик:** На включенном профилировщике (level `1`) в `system.profile` можно найти записи с полем `command.aggregate` и проверить `millis`, `docsExamined`, `keysExamined`.

---

## Основные и продвинутые стадии

### Базовые операции
*   **`$match`:** Фильтрация документов (аналог `WHERE`). Должна быть первой для использования индексов.
*   **`$group`:** Группировка по ключу с выполнением агрегатных функций (аналог `GROUP BY`).
*   **`$project`:** Выбор, переименование или создание новых полей.
*   **`$sort` / `$limit` / `$skip`:** Управление порядком и пагинацией.

### Продвинутые механизмы
*   **`$lookup` (JOIN):** Объединение с документами из другой коллекции. В версии 8.0 оптимизировано для работы с индексами внешних коллекций.
*   **`$facet`:** Выполнение нескольких независимых конвейеров над одним набором данных в рамках одного запроса (идеально для "фильтров + результатов" в интернет-магазинах).
*   **`$unwind`:** "Разворачивание" массива — создает по одному документу для каждого элемента массива.
*   **`$merge` / `$out`:** Запись результата агрегации в коллекцию. `$merge` позволяет обновлять существующие документы, а `$out` всегда перезаписывает коллекцию.

### Аналитические операторы (окна, графы, объединения)

*   **`$setWindowFields`:** Оконные функции (SQL-аналог `OVER()`). Вычисляет агрегаты в скользящем окне документов: `$sum`, `$avg`, `$min`, `$max`, `$movingAvg`, `$movingStdDev`, `$derivative`, `$integral`, `$documentNumber`, `$rank`, `$denseRank`, `$shift`, `$median` (8.0+). Параметры: `partitionBy` (группировка, аналог `PARTITION BY`), `sortBy` (порядок), `output.<field>.<operator>` с `window: { documents: [n, m] }` или `range: [...]`.
*   **`$graphLookup`:** Рекурсивный обход графа (аналог рекурсивного CTE `WITH RECURSIVE`). Параметры: `from`, `startWith`, `connectFromField`, `connectToField`, `as`, `maxDepth`, `depthField`, `restrictSearchWithMatch`. Применение: оргструктуры, деревья категорий, графы зависимостей.
*   **`$unionWith`:** Объединение результатов с другой коллекцией (аналог `UNION ALL`). Параметры: `coll`, `pipeline` (опциональная обработка перед объединением).
*   **`$bucketAuto`:** Автоматическое разбиение на N корзин по значению поля (аналог гистограммы). Параметры: `groupBy`, `buckets`, `output`, `granularity` (R5, R10, R20, R40, R80, powersOf2).
*   **`$bucket`:** Разбиение на корзины с явными границами (`boundaries`, `default`).

**Ограничения:**
*   `$setWindowFields` — не поддерживает `allowDiskUse`-спиллы для всех операторов; окно ограничено 100 MB на стадию.
*   `$graphLookup` — `maxDepth` по умолчанию не ограничен (риск глубокой рекурсии); результат в массиве `as` может раздуть документ (лимит 16 MB на документ).
*   `$unionWith` — не может использоваться внутри `$facet`.
*   `$bucketAuto` — `granularity` требует числового `groupBy`.

---

## Особенности версии 8.0+

*   **Block Processing:** Новый режим выполнения, при котором данные обрабатываются не по одному документу, а блоками. Это дает **кратное ускорение** (до 10-40 раз) для аналитических запросов на Time-series данных. Проверить использование block processing можно в explain output: `explain.queryPlanner.winningPlan.slotBasedPlan.stages`.
*   **Улучшенная параллелизация:** Стадии, не требующие блокировки, могут выполняться параллельно на нескольких ядрах CPU.

---

## Диагностика и наблюдаемость

### Explain plan для агрегаций
`explain()` поддерживается для `aggregate()` и возвращает три уровня детализации: `"queryPlanner"`, `"executionStats"`, `"allPlansExecution"` (по умолчанию).

**Что смотреть SRE:**
*   `executionStats.executionTimeMillis` — общее время выполнения.
*   `totalDocsExamined` vs `nReturned` — если документов examined значительно больше, чем returned, фильтр неэффективен.
*   `totalKeysExamined` vs `totalDocsExamined` — если keys examined близок к docs examined, индекс работает эффективно.
*   `executionStages.stage` — значение `COLLSCAN` означает полный перебор коллекции, `IXSCAN` — использование индекса.
*   `spills`, `spilledBytes`, `usedDisk` — признаки переполнения памяти и записи на диск.
*   `queryPlanner.winningPlan.queryPlan.stage: "EQ_LOOKUP"` — `$lookup` выполняется через slot-based engine с equality lookup.

**Ограничение:** Для конвейеров с `$out` explain можно запустить только в режиме `"queryPlanner"` или без `$out`-стадии, так как `executionStats` не возвращается для пишущих стадий.

### Профилировщик и медленные запросы
*   **`db.setProfilingLevel(1, <slowms>)`** — включает сбор статистики для операций, превышающих порог. Профилировщик записывает данные в `system.profile` и диагностический лог.
*   **Фильтр для агрегаций:** Можно ограничить профилирование только агрегационными командами через параметр `filter`: `{ op: "query", command: { aggregate: "<collection>" } }`.
*   **`slowms`:** Глобальный порог для диагностического лога (по умолчанию 100 мс). На `mongos` можно настроить отдельно, но профилировщик на `mongos` недоступен.

### $queryStats
Стадия `$queryStats` возвращает статистику выполнения запросов (формы запросов, количество выполнений, время) без внешнего профилировщика. Для использования требуется роль с привилегией `queryStatsRead` (входит в `clusterMonitor` и выше).

### Привилегии для агрегации
*   **`read` / `readWrite`** — достаточно для большинства конвейеров над коллекциями.
*   **`clusterMonitor`** — требуется для `$indexStats`, `$queryStats`, `$listClusterCatalog`.
*   **`dbAdmin`** — требуется для `$collStats`.
*   **`$out` / `$merge`** — требуют дополнительных привилегий на запись; обычно покрываются `readWrite` на целевой коллекции.

---

## Практические сценарии

### 1. Аналитика продаж по регионам
Пример конвейера с объединением коллекций и расчетом метрик:

```javascript
db.orders.aggregate([
  // 1. Фильтруем за последний месяц (замените на актуальную дату)
  { $match: { createdAt: { $gt: new Date("2026-07-17") } } },
  
  // 2. Присоединяем данные о клиенте
  {
    $lookup: {
      from: "customers",
      localField: "customerId",
      foreignField: "_id",
      as: "customer"
    }
  },
  
  // 3. Превращаем массив customer в объект
  { $unwind: "$customer" },
  
  // 4. Группируем по региону
  {
    $group: {
      _id: "$customer.region",
      totalRevenue: { $sum: "$amount" },
      avgOrderValue: { $avg: "$amount" },
      ordersCount: { $sum: 1 }
    }
  },
  
  // 5. Сортируем по выручке
  { $sort: { totalRevenue: -1 } }
], { allowDiskUse: true })
```

**Валидация:**
```javascript
// Проверка плана выполнения: убедитесь, что $match использует индекс на createdAt,
// а $lookup использует индекс на _id в коллекции customers.
db.orders.explain("executionStats").aggregate([
  { $match: { createdAt: { $gt: new Date("2026-07-17") } } },
  {
    $lookup: {
      from: "customers",
      localField: "customerId",
      foreignField: "_id",
      as: "customer"
    }
  },
  { $unwind: "$customer" },
  {
    $group: {
      _id: "$customer.region",
      totalRevenue: { $sum: "$amount" },
      avgOrderValue: { $avg: "$amount" },
      ordersCount: { $sum: 1 }
    }
  },
  { $sort: { totalRevenue: -1 } }
])
```

### 3. Скользящие средние через $setWindowFields

Скользящая средняя выручки за 7 дней и кумулятивная сумма по регионам:

```javascript
db.orders.aggregate([
  { $match: { createdAt: { $gte: new Date("2026-01-01") } } },
  { $sort: { region: 1, createdAt: 1 } },
  {
    $setWindowFields: {
      partitionBy: "$region",
      sortBy: { createdAt: 1 },
      output: {
        cumulativeRevenue: {
          $sum: "$amount",
          window: { documents: ["unbounded", "current"] }
        },
        movingAvg7d: {
          $avg: "$amount",
          window: { range: [-7 * 24 * 3600 * 1000, 0], unit: "millisecond" }
        },
        rowNum: { $documentNumber: {} }
      }
    }
  },
  { $match: { rowNum: { $lte: 100 } } }
], { allowDiskUse: true })
```

**Валидация:**
```javascript
// Проверка: movingAvg7d должен быть средним по окну, cumulative — нарастающим итогом
db.orders.explain("executionStats").aggregate([
  { $setWindowFields: {
      partitionBy: "$region",
      sortBy: { createdAt: 1 },
      output: { movingAvg7d: { $avg: "$amount", window: { documents: [-6, 0] } } }
  } }
])
// # → executionStages: $setWindowFields, usedDisk: false
```

### 4. Рекурсивный обход дерева через $graphLookup

Оргструктура: найти всех подчинённых менеджера (до 5 уровней):

```javascript
db.employees.aggregate([
  { $match: { _id: "mgr-001" } },
  {
    $graphLookup: {
      from: "employees",
      startWith: "$_id",
      connectFromField: "_id",
      connectToField: "managerId",
      as: "subordinates",
      maxDepth: 5,
      depthField: "level",
      restrictSearchWithMatch: { status: "active" }
    }
  },
  { $project: { name: 1, subordinateCount: { $size: "$subordinates" }, subordinates: 1 } }
])
```

### 5. Объединение коллекций через $unionWith

Объединить заказы из двух коллекций (архив + текущие):

```javascript
db.orders_current.aggregate([
  { $match: { status: "paid" } },
  {
    $unionWith: {
      coll: "orders_archive",
      pipeline: [ { $match: { status: "paid" } } ]
    }
  },
  { $group: { _id: null, total: { $sum: "$amount" }, count: { $sum: 1 } } }
])
```

### 6. Гистограмма через $bucketAuto

Автоматическое разбиение заказов на 5 корзин по сумме:

```javascript
db.orders.aggregate([
  {
    $bucketAuto: {
      groupBy: "$amount",
      buckets: 5,
      granularity: "R20",
      output: { count: { $sum: 1 }, avgAmount: { $avg: "$amount" } }
    }
  }
])
// # → [ { _id: { min: 0, max: 120 }, count: 45, avgAmount: 78.3 }, ... ]
```

### 2. Сложная пагинация через $facet
```javascript
db.products.aggregate([
  { $match: { category: "electronics" } },
  {
    $facet: {
      "metadata": [ { $count: "total" } ],
      "data": [ { $sort: { price: 1 } }, { $skip: 20 }, { $limit: 10 } ]
    }
  }
])
```

**Валидация:**
```javascript
// Проверка, что $sort на price использует индекс, а $skip/$limit не передают
// лишние данные через границу страниц.
db.products.explain("executionStats").aggregate([
  { $match: { category: "electronics" } },
  {
    $facet: {
      "metadata": [ { $count: "total" } ],
      "data": [ { $sort: { price: 1 } }, { $skip: 20 }, { $limit: 10 } ]
    }
  }
])
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **`Sort exceeded memory limit`** | Стадия `$sort` заняла > 100MB RAM. | Использовать индекс для сортировки или добавить `{ allowDiskUse: true }`. |
| **`Query exceeded memory limit`** | Блокирующая стадия (обычно `$group` или `$sort`) не может уложиться в 100 MB и `allowDiskUse` не установлен. | Добавить `{ allowDiskUse: true }` или уменьшить объем данных на ранних стадиях (`$match`, `$project`). |
| **Низкая скорость $lookup** | Отсутствие индекса на `foreignField`. | Создать индекс в коллекции, из которой подтягиваются данные. |
| **COLLSCAN в $match** | Поля в фильтре не проиндексированы или нарушено правило ESR. | Проверить план через `.explain("executionStats")`. |
| **Пустой результат агрегации** | Некорректные типы данных в `$lookup` (например, String vs ObjectId). | Убедиться, что `localField` и `foreignField` имеют одинаковый тип. |
| **`explain` не возвращает executionStats** | В конвейере присутствует стадия `$out`. | Запустить explain без `$out` или в режиме `"queryPlanner"`. |
| **Произвольные задержки на $group/$sort** | Отсутствие coverage индекса или слишком большой working set для WiredTiger Cache. | Проверить `explain.executionStats.executionTimeMillis`, при необходимости добавить составной индекс под `$match` + `$sort` + `$group`. |
| **`$setWindowFields` медленный** | Нет индекса под `partitionBy` + `sortBy`; окно обрабатывает весь набор. | `explain("executionStats")`: `totalDocsExamined` vs `nReturned`. | Составной индекс `{ partitionField: 1, sortField: 1 }`; уменьшить окно (`documents: [-N, 0]`). |
| **`$graphLookup` возвращает пустой массив** | Неверные `connectFromField`/`connectToField` или `startWith` не массив. | Проверить типы полей (`_id` ObjectId vs string). | Убедиться в совпадении типов; `startWith` может быть массивом для нескольких стартовых вершин. |
| **`$graphLookup` превысил лимит документа (16 MB)** | Глубокий/широкий граф: результат в `as` раздувает документ. | `$project` с `{$size: "$as"}`. | Установить `maxDepth`; использовать `restrictSearchWithMatch`; обрабатывать порциями. |
| **`$unionWith` внутри `$facet`** | `$unionWith` не поддерживается внутри `$facet`. | Ошибка `unionWith is not allowed in $facet`. | Вынести `$unionWith` из `$facet` или использовать `$lookup` с пустым `localField`. |
| **`$bucketAuto` с `granularity` ошибка** | `groupBy` не числовое или `granularity` некорректна. | Текст ошибки: `granularity must be one of...`. | Использовать числовое `groupBy`; `granularity` из R5/R10/R20/R40/R80/powersOf2. |

---

## Лучшие практики

1.  **Match early:** Отфильтровывайте данные как можно раньше.
2.  **Project early:** Не тащите через весь конвейер поля, которые не нужны в финальном результате.
3.  **Используйте индексы:** Первые стадии (`$match`, `$sort`) должны полностью покрываться индексами.
4.  **Избегайте `$unwind` на огромных массивах:** Это может вызвать "взрыв" количества документов и переполнение памяти.
5.  **Включайте `allowDiskUse` для аналитики:** Для ETL-конвейеров и фоновых отчетов всегда указывайте `{ allowDiskUse: true }`, чтобы избежать внезапных падений при росте объема данных.
6.  **Диагностируйте через explain перед продакшеном:** Запускайте `.explain("executionStats")` на репрезентативных данных и проверяйте `totalDocsExamined` vs `nReturned` и отсутствие `COLLSCAN`.
7.  **Настройте порог `slowms` и профилировщик:** Для критичных коллекций установите `db.setProfilingLevel(1, 200)` и регулярно опрашивайте `system.profile` на предмет долгих агрегаций.
8.  **Контролируйте привилегии:** Для `$queryStats`, `$indexStats` и `$listClusterCatalog` необходима роль `clusterMonitor` или выше; не выдавайте `clusterMonitor` прикладным сервисам без необходимости.

---

## Дополнительная информация

*   **[Общий обзор MongoDB](./mongodb.md)** — архитектура и WiredTiger.
*   **[Индексы в MongoDB](./mongodb-indexes.md)** — база для производительной агрегации.
*   **[Change Streams](./mongodb-change-streams.md)** — агрегация в реальном времени.
*   **[Time-series коллекции](./mongodb-time-series.md)** — использование Block Processing в 8.0.
*   **[SQL Interface](./mongodb-sql-interface.md)** — SQL-запросы транслируются в агрегации.
*   **[Kafka/CDC](./mongodb-kafka-cdc.md)** — потоковая обработка изменений.
