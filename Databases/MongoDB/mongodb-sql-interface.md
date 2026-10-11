# MongoDB: SQL Interface и BI Connector

**Актуально для:** MongoDB 8.0.x (последний патч 8.0.34, 24 сентября 2026 года), MongoDB SQL Interface (MongoSQL 2.0.0), MongoDB Connector for BI 2.14.x (EOL September 2026)

---

## Определения

*   **MongoDB SQL Interface:** Нативный SQL-доступ к MongoDB (Enterprise Advanced и Atlas), появившийся в 2025 году как замена BI Connector. Выполняет MongoSQL (диалект, совместимый с SQL-92) через нативные операции MongoDB. **Read-only**.
*   **MongoSQL:** SQL-диалект MongoDB для SQL Interface. Совместим с SQL-92; другие диалекты (T-SQL, PL/SQL) не поддерживаются.
*   **MongoDB Connector for BI (`mongosqld`):** Legacy-компонент для SQL-доступа к MongoDB (on-premises и Atlas). Достиг end-of-life (EOL) — поддержка прекращается **September 2026**. Для новых проектов использовать SQL Interface.
*   **DRDL (Document Relational Mapping Definition Language):** Язык описания схемы BI Connector, маппящий MongoDB-коллекции на реляционные таблицы (файл `.drdl`).
*   **`mongosqld`:** Демон BI Connector, принимающий SQL-подключения (порт 3307 по умолчанию) и транслирующий их в агрегации MongoDB.

---

## Базовые концепции

### Зачем SQL к MongoDB

*   BI-инструменты (Tableau, Power BI, Looker) и legacy-отчёты говорят на SQL.
*   Аналитики не хотят изучать Aggregation Framework.
*   SQL Interface/BI Connector — слой трансляции SQL → MongoDB-операций, а не отдельный движок хранения.

### Архитектура

**SQL Interface (текущий подход):**
```
BI-инструмент (Tableau/Power BI)
   │  JDBC/ODBC (MongoSQL)
   ▼
MongoDB SQL Interface (на кластере / Enterprise Advanced)
   │  Использует JSON-схему (mongodb-schema-manager CLI)
   │  нативные операции find/aggregate
   ▼
MongoDB (WiredTiger)
```

**BI Connector (legacy):**
```
BI-инструмент
   │  MySQL-протокол (порт 3307)
   ▼
mongosqld (BI Connector) + schema.drdl
   │  агрегации
   ▼
MongoDB
```

### Ключевые различия

| Критерий | SQL Interface | BI Connector (legacy) |
| :--- | :--- | :--- |
| **Статус** | Текущий (GA — с сентября 2025 года) | EOL September 2026 |
| **Производительность** | Нативные операции MongoDB | Трансляция через DRDL-схему |
| **Схема** | Явная JSON-схема (mongodb-schema-manager CLI) | Явный DRDL-файл |
| **Доступ** | Read-only | Read-only |
| **Диалект** | MongoSQL (SQL-92) | MySQL-совместимый (SQL-99) |
| **Платформа** | Enterprise Advanced, Atlas Dedicated (M10+) | Enterprise, Atlas, on-prem |
| **Протокол** | JDBC / ODBC | MySQL wire protocol (порт 3307) |

---

## Практические сценарии

### 1. Подключение через SQL Interface (Enterprise Advanced / Atlas)

**Требования (предварительно):**
*   Кластер MongoDB **6.0 или выше** (поддержка начинается с 6.0; рекомендуется 8.0.x).
*   **Enterprise Advanced** (on-premises) или **Atlas Dedicated** (M10 и выше). Community Edition не поддерживается.
*   Отсутствие изменений в конфигурации сервера — SQL Interface не требует перезапуска `mongod`.

**На стороне Enterprise Advanced (on-premises):**
```bash
# 1. Скачать MongoDB SQL Schema Builder CLI (отдельная загрузка, не входит в дистрибутив)
#    Бинарь: mongodb-schema-manager (версия 2.0.0+)

# 2. Сгенерировать JSON-схему для БД sales_db (анализирует КАЖДЫЙ документ,
#    не выборочно; схема не обновляется автоматически)
mongodb-schema-manager \
  --uri "mongodb://<user>:<pass>@mongo1:27017/?authSource=admin" \
  --db sales_db \
  --out /etc/mongodb/sql-schema/sales_db.json
# # → Готовая JSON Schema (файл sales_db.json), описывающая типы,
# #   вложенность, полиморфизм и разреженность полей.
```

**На стороне Atlas Dedicated (M10+):**
*   Включить SQL Interface можно в настройках кластера (Atlas UI или Atlas Administration API) — отдельно для каждого кластера.
*   Схемы управляются через `mongodb-schema-manager` CLI (тот же инструмент, что и для EA).
*   Для Atlas Data Federation схемы генерируются в Atlas UI или через `mongosh` (path sampling, а не полный анализ).

**Подключение SQL-клиентом (JDBC/ODBC драйвер MongoDB SQL):**
```bash
# Пример строки подключения (JDBC):
# jdbc:mongodb://mongo1:27017,sales_db?sqlInterface=true
```

**Пример MongoSQL-запроса:**
```sql
SELECT customer.region, SUM(order.amount) AS total
FROM sales_db.orders AS order
JOIN sales_db.customers AS customer
  ON order.customerId = customer._id
WHERE order.createdAt > TIMESTAMP('2026-01-01')
GROUP BY customer.region
ORDER BY total DESC;
```

### 2. Миграция с BI Connector на SQL Interface

**Шаг 1: Оценка готовности** — MongoDB предоставляет **MongoSQL Transition Readiness Tool**: анализирует историю запросов BI Connector, генерирует отчёт с рекомендациями и подсвечивает запросы, требующие изменения синтаксиса.

**Шаг 2: Подготовка инфраструктуры (Enterprise Advanced):**
*   Скачать и установить **MongoDB SQL Schema Builder CLI** (отдельная загрузка, версия 2.0.0+).
*   Запустить `mongodb-schema-manager` для генерации JSON-схем по всем нужным БД.
*   Схема генерируется один раз, не обновляется автоматически — планировать регенерацию при изменении структуры данных.

**Шаг 3: Адаптация схемы и запросов** — архитектура SQL Interface отличается от BI Connector:
*   DRDL-схема не переносится — SQL Interface работает с JSON-схемой, сгенерированной CLI.
*   Типы в MongoSQL отличаются от MySQL-типов BI Connector (например, `DATE` не поддерживается, используйте `TIMESTAMP`).
*   Часть запросов требует переписывания под MongoSQL (SQL-92).

**Шаг 4: Переключение BI-инструмента** на новый JDBC/ODBC-драйвер SQL Interface.

**Шаг 5: Вывод `mongosqld` из эксплуатации** после September 2026 (EOL).

### 3. Legacy: BI Connector (mongosqld) — до EOL

> **Статус:** BI Connector достиг EOL в сентябре 2026 года. Поддержка и обновления безопасности прекращаются. Для новых проектов — только SQL Interface.

**Требования:**
*   MongoDB Enterprise (Community Edition не включает `mongosqld`; для проверки версии: `mongod --version` — должен быть `modules: enterprise`).
*   Отдельная загрузка BI Connector (не входит в дистрибутив MongoDB Enterprise).

```bash
# Генерация DRDL-схемы из коллекции
mongodrdl --host mongo1:27017 --db sales_db --out schema.drdl
# # → Generated schema.drdl with N tables

# Запуск mongosqld (по умолчанию слушает 127.0.0.1:3307)
mongosqld --schema schema.drdl --mongo-uri "mongodb://mongo1:27017/?replicaSet=rs0" \
  --addr 0.0.0.0:3307
# # → [main] INFO: Listening on 0.0.0.0:3307

# Подключение MySQL-клиентом
mysql -h 127.0.0.1 -P 3307 -u bi_user -p
# mysql> SELECT region, SUM(amount) FROM sales_db.orders GROUP BY region;
```

**DRDL-файл (пример):**
```yaml
# schema.drdl
databases:
  - name: sales_db
    collections:
      - name: orders
        tables:
          - name: orders
            pipeline: []
            columns:
              - name: _id
                mongoName: _id
                type: objectid
              - name: amount
                mongoName: amount
                type: double
              - name: customerId
                mongoName: customerId
                type: objectid
```

**Конфигурация через YAML-файл (mongosqld.conf):**
```yaml
systemLog:
  path: '/var/log/mongosqld/mongosqld.log'
  verbosity: 2
mongodb:
  net:
    uri: "mongo.example.com:27017"
  auth:
    username: "root"
    password: "changeme"
net:
  bindIp: '192.0.2.14'
  port: 3307
  ssl:
    mode: "allowSSL"
    PEMKeyFile: "/vagrant/certificates/mongosqld-server.pem"
    CAFile: "/vagrant/certificates/ca.crt"
schema:
  sample:
    namespaces: "inventory.*"
```

**Известные уязвимости (BI Connector):**
*   **CVE-2026-81490** (сентябрь 2026) — DoS через создание вида, чьё вычисление всегда завершается ошибкой. `mongosqld` исчерпывает попытки сэмплирования и останавливается без валидной схемы, блокируя SQL-клиентов. Митигация: ограничить привилегии на создание вида, удалить вредоносные view, перезапустить `mongosqld`.

### 4. Мониторинг SQL-нагрузки

```javascript
// Активные SQL-сессии (SQL Interface)
use admin
db.adminCommand({ currentOp: 1, "command.sql": { $exists: true } })

// Профилирование медленных SQL-запросов (они логируются как агрегации)
db.setProfilingLevel(1, { slowms: 100 })
db.system.profile.find({ "command.sql": { $exists: true } }).sort({ millis: -1 }).limit(5)
```

**Особенности логирования:**
*   SQL Interface не имеет отдельного лог-файла — все SQL-запросы проходят через стандартный MongoDB slow op log и `system.profile` как агрегации.
*   Порог slowms рекомендуется установить в 100 мс для аналитических нагрузок (по умолчанию 100 мс).
*   Для отладки трансляции SQL → MQL можно включить подробные логи через `setParameter` (см. [Мониторинг](./mongodb-monitoring.md)).

---

## Лучшие практики

*   **Схема — явная, а не автоматическая:** Генерируйте JSON-схему через `mongodb-schema-manager` после каждого значимого изменения структуры данных. Автоматическое обновление схемы отсутствует — пренебрежение приводит к несоответствию типов и ошибкам трансляции.
*   **Глубокая вложенность — через схему:** Для массивов и вложенных документов указывайте в JSON-схеме нужную структуру (включая `items`, `properties`), чтобы MongoSQL мог корректно обрабатывать `UNNEST`-подобные операции.
*   **Индексы под SQL-фильтры:** Каждый `WHERE` и `ORDER BY` в MongoSQL должен иметь покрывающий индекс. Проверяйте сгенерированную агрегацию через `explain()` — отсутствие индекса приводит к COLLSCAN и падению производительности (см. [Индексы](./mongodb-indexes.md)).
*   **Типы дат:** MongoSQL не поддерживает `DATE` — используйте `TIMESTAMP` (BSON Timestamp) или `CAST()` для преобразования. Дата в запросе должна быть в формате ISO-8601: `TIMESTAMP('2026-01-01T00:00:00.000Z')`.
*   **Планируйте миграцию заранее:** BI Connector достиг EOL в сентябре 2026 года. После этой даты обновления безопасности и поддержка прекращаются. Начинайте миграцию не менее чем за 3–6 месяцев до EOL.
*   **Ограничение доступа:** SQL Interface — read-only, но подключение через JDBC/ODBC всё равно требует валидных учётных данных MongoDB. Используйте отдельную БД/роль с минимальными привилегиями для BI-инструментов.
*   **Шардирование:** SQL Interface поддерживает sharded clusters; убедитесь, что JSON-схема покрывает все шарды. BI Connector требовал подключения через `mongos`.

---

## Устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`SQL Interface not enabled`** | Фича не включена или редакция не Enterprise Advanced. | `db.adminCommand({ getParameter: 1, sqlInterface: 1 })`. | Включить SQL Interface; проверить редакцию (Enterprise Advanced / Atlas). |
| **BI Connector: `unknown option snmp-master`-подобные ошибки** | Community Edition — `mongosqld` недоступен. | `mongod --version` (должно быть `modules: enterprise`). | Установить MongoDB Enterprise. |
| **Запрос возвращает пустой результат** | DRDL-схема не соответствует структуре документов (поле переименовано/вложено). | Сравнить `schema.drdl` с `db.collection.findOne()`. | Перегенерировать DRDL (`mongodrdl`). |
| **Медленные SQL-запросы** | Отсутствие индексов под фильтры/сортировку. | `explain()` на сгенерированной агрегации; `system.profile`. | Создать индексы по `WHERE`/`ORDER BY`-полям (см. [Индексы](./mongodb-indexes.md)). |
| **`Unsupported SQL dialect`** | Клиент использует T-SQL/PL/SQL-специфику. | Логи SQL Interface. | Переписать запрос на MongoSQL (SQL-92). |
| **BI Connector не стартует после обновления** | Несовместимость версии mongosqld с сервером. | `mongosqld --version` vs `mongod --version`. | Обновить BI Connector до 2.14.x (последняя линия перед EOL). |

---

## Ограничения и Edge Cases

*   **Read-only:** И SQL Interface, и BI Connector — только для чтения. Запись возможна только через драйверы MongoDB.
*   **EOL BI Connector:** После September 2026 обновления безопасности и поддержка прекращаются. Планировать миграцию заранее.
*   **MongoSQL ≠ полный SQL:** Нет хранимых процедур, триггеров, DDL (`CREATE TABLE`). Только `SELECT`-подобные операции (включая `SELECT DISTINCT`, `GROUP BY`, `HAVING`, `ORDER BY`, `OFFSET`, `LIMIT`).
*   **Совместимость с SQL-92:** MongoSQL основан на SQL-92, но **не является полностью совместимым**:
    *   Тип `DATE` не поддерживается — используйте `TIMESTAMP`.
    *   `INTERVAL` и арифметика датированных интервалов не поддерживаются.
    *   MongoDB Vector Search и MongoDB Search не доступны через SQL.
*   **Вложенные документы:** Глубоко вложенные массивы требуют `$unwind`-логики; в MongoSQL — через `UNNEST`-подобные конструкции (см. `OUTER` параметр в `UNNEST`). Проверяйте синтаксис в [документации MongoSQL](https://www.mongodb.com/docs/sql-interface/language-reference/).
*   **Шардированные кластеры:** SQL Interface поддерживает sharded clusters; BI Connector требовал `mongos`-подключение.
*   **Совместимость драйверов:** SQL Interface компоненты остаются совместимы с версией MongoDB-сервера в течение **3 лет** после её EOL (см. [MongoDB Software Lifecycle](https://www.mongodb.com/docs/manual/release-notes/)).
*   **Типовая браковка (Type Bracketing):** С версии MongoSQL 2.0.0 (сентябрь 2026) сравнения поля с литералом (например, `WHERE x > 20`) транслируются в MongoDB match-язык с типовой браковкой вместо `$expr`. Это меняет поведение запросов, возвращавших ранее неполные результаты (например, `WHERE employeeId IN (...)`).
*   **Функции высшего порядка:** MongoSQL 2.0.0 добавляет поддержку `MAP`, `FILTER`, `REDUCE` для работы с массивами.

---

## Дополнительная информация

*   **[Агрегация](./mongodb-aggregation.md)** — SQL-запросы транслируются в агрегации.
*   **[Индексы](./mongodb-indexes.md)** — производительность SQL-запросов.
*   **[Мониторинг](./mongodb-monitoring.md)** — профилирование SQL-нагрузки.
*   **[Обзор MongoDB](./mongodb.md)** — редакции Community/Enterprise.
