# Neo4j: Cypher — полное руководство

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS

## Определения

| Термин | Значение |
| :--- | :--- |
| **Cypher** | Декларативный язык запросов к графам Neo4j с ASCII-art синтаксисом описания паттернов. |
| **Pattern** | Шаблон поиска в графе, описывающий узлы, связи и направление обхода. |
| **Clause** | Часть запроса: `MATCH`, `WHERE`, `RETURN`, `WITH`, `ORDER BY`, `LIMIT`, `SKIP`, `UNWIND`. |
| **Label** | Именованное множество узлов; используется для индексации и ограничения пространства поиска. |
| **Relationship type** | Тип связи; задаёт семантику и направление обхода. |
| **Property** | Пара ключ-значение на узле или связи; типы: scalar, list, map. |
| **ElementId** | Строковый идентификатор узла или связи, уникальный в пределах базы. Не переиспользуется. |
| **Internal ID** | Внутренний числовой идентификатор; переиспользуется после удаления. Не хранить в приложениях. |
| **Runtime** | Механизм исполнения плана: `slotted`, `pipelined`, `parallel`. |
| **Planner** | Стратегия построения плана: `COST` (по умолчанию), `IDP`, `DP`. |
| **DbHits** | Обращения к engine в `PROFILE`; первичная метрика стоимости запроса. |
| **Subquery** | Вложенный запрос в `CALL { … }`, выполненный как отдельная операция с собственными параметрами. |
| **Query hint** | Директива оптимизатору: `USING INDEX`, `USING SCAN`, `USING JOIN`, `CYPHER runtime=…`. |
| **Parameter** | Переменная запроса (`$name`), передаваемая отдельно от текста; обеспечивает переиспользование плана. |
| **Transaction function** | Блок `CALL { … } IN TRANSACTIONS …` для пакетной обработки без APOC. |
| **Cypher 5** | Замороженный набор семантики Cypher; совместим со всеми запросами, написанными до 2025.06. |
| **Cypher 25** | Активная ветвь языка; добавляет синтаксис и изменяет семантику некоторых конструкций. |

## Версии языка Cypher и совместимость

С Neo4j 2025.06 язык Cypher версионируется отдельно от сервера. Это влияет на совместимость запросов и поведение оптимизатора.

**Cypher 5** — замороженный набор семантики, получает только исправления и оптимизации. Совместим со всеми запросами, написанными для Neo4j 2025.05 и ранее.

**Cypher 25** — активная ветвь; добавляет синтаксис и изменяет семантику существующих конструкций (например, `IS [NOT] LABELED`, правила разрешения свойств в `MERGE`).

```cypher
// Явное переопределение версии языка для конкретного запроса
CYPHER 5 MATCH (n:Person) RETURN count(n);
// → выполняется на семантике Cypher 5 независимо от настройки базы
```

**Важно для миграций.** Значение языка фиксируется в момент создания базы. Один и тот же запрос может вести себя по-разному на старой и новой базе. Глобальное значение задаётся через `db.query.default_language` в `neo4j.conf`.

```cypher
-- Проверить язык базы
SHOW DATABASES YIELD name, defaultLanguage;

-- Изменить язык базы (требует перезапуска)
ALTER DATABASE neo4j SET DEFAULT LANGUAGE CYPHER_25;
```

## CRUD-операции

### CREATE — создание узлов и связей

```cypher
// Одиночный узел с параметрами
CREATE (p:Person {name: $name, email: $email, age: $age})
RETURN p;

// Несколько узлов и связей за одну операцию
CREATE
  (a:Person {name: 'Alice', age: 30}),
  (b:Person {name: 'Bob', age: 25}),
  (c:Company {name: 'TechCorp'}),
  (a)-[:WORKS_AT {since: 2019, role: 'Engineer'}]->(c),
  (b)-[:WORKS_AT {since: 2021, role: 'Designer'}]->(c),
  (a)-[:FRIENDS_WITH {since: 2020}]->(b)
RETURN a, b, c;
```

**DevOps-контекст:** при массовом импорте создавайте узлы пачками внутри `CALL { } IN TRANSACTIONS OF 10000 ROWS` — это ограничивает размер одной транзакции и защищает от OOM.

### MERGE — создание или поиск

`MERGE` ищет существующий паттерн и создаёт его, только если не найдено. `ON CREATE SET` и `ON MATCH SET` позволяют выполнять разные действия в зависимости от результата.

```cypher
MERGE (p:Person {name: $name})
ON CREATE SET p.createdAt = datetime(), p.role = 'Admin'
ON MATCH SET p.lastSeen = datetime()
RETURN p;
```

**Внимание:** `MERGE` на свойствах, которые не индексированы, выполняет полное сканирование узлов с меткой. В production индексируйте все свойства, используемые в `MERGE` как anchor points.

### MATCH + WHERE — поиск

```cypher
// Параметризованный запрос с индексным поиском
MATCH (p:Person {email: $email})-[:WORKS_AT]->(c:Company)
RETURN p.name, c.name;

// Фильтрация и сортировка
MATCH (p:Person) WHERE p.age > 25
RETURN p.name, p.age
ORDER BY p.age DESC;
```

### SET — изменение свойств и меток

```cypher
// Обновление свойств и добавление метки
MATCH (p:Person {name: $name})
SET p.age = 31, p.city = 'New York', p:Employee
RETURN p;

// Удаление свойства (присвоение NULL)
MATCH (p:Person {name: $name})
REMOVE p.tempProperty;

// Удаление всех свойств
MATCH (p:Person {name: $name})
REMOVE p.age, p.email;

// Динамическое удаление свойства (Cypher 25)
MATCH (p:Person {name: $name})
SET p[$propKey] = null;
```

### DELETE — удаление

```cypher
// Удаление узла без связей
MATCH (p:Person {name: $name}) DELETE p;

// Удаление узла со всеми связями (осторожно!)
MATCH (p:Person {name: $name}) DETACH DELETE p;

// Удаление конкретной связи
MATCH (a:Person {name: $nameA})-[r:FRIENDS_WITH]->(b:Person {name: $nameB})
DELETE r;

// Безопасное массовое удаление с пагинацией
MATCH (n:OldLabel) WITH n LIMIT 10000 DETACH DELETE n;
```

**Важно:** `DETACH DELETE` удаляет узел и все его связи одной операцией. На больших hub-узлах это может вызвать contention и долгие транзакции. Для регулярной очистки используйте пакетный режим.

## Моделирование данных

### Типичные паттерны

**Социальная сеть:**
```cypher
CREATE (alice:Person {name: 'Alice', age: 30})
CREATE (bob:Person {name: 'Bob', age: 25})
CREATE (alice)-[:FRIENDS_WITH {since: 2020}]->(bob)
```

**Сеть зависимостей инфраструктуры:**
```cypher
CREATE (app:Service {name: 'payment-api'})
CREATE (db:Database {name: 'payments-db', type: 'PostgreSQL'})
CREATE (cache:Cache {name: 'redis-cache'})
CREATE (app)-[:CONNECTS_TO {port: 5432}]->(db)
CREATE (app)-[:CONNECTS_TO {port: 6379}]->(cache)
```

**Схема с ограничениями:**
```cypher
// Уникальность email (доступно в CE и EE)
CREATE CONSTRAINT FOR (p:Person) REQUIRE p.email IS UNIQUE;

// Составной уникальный ключ (Node Key, только EE)
CREATE CONSTRAINT FOR (p:Person) REQUIRE (p.firstName, p.lastName) IS NODE KEY;

// Обязательное наличие поля (только EE)
CREATE CONSTRAINT FOR (p:Person) REQUIRE p.name IS NOT NULL;

// Ограничение типа свойства (только EE)
CREATE CONSTRAINT FOR (p:Person) REQUIRE p.age IS INTEGER;
```

## Обход графа (Traversals)

### Переменная длина (variable-length)

```cypher
// Друзья друзей (ровно 2 уровня)
MATCH (a:Person {name: 'Alice'})-[:FRIENDS_WITH*2]->(friend)
RETURN DISTINCT friend.name;

// Все пути длиной от 1 до 3
MATCH path = (a:Person {name: 'Alice'})-[:FRIENDS_WITH*1..3]->(friend)
RETURN path, length(path) AS depth;

// Неограниченная глубина — осторожно!
MATCH path = (a:Person {name: 'Alice'})-[:FRIENDS_WITH*]->(friend)
RETURN path LIMIT 25;
```

### Кратчайший путь

```cypher
// Кратчайший путь (по числу связей)
MATCH path = shortestPath(
  (a:Person {name: 'Alice'})-[*]-(b:Person {name: 'Diana'})
)
RETURN path, length(path) AS hops;

// Все кратчайшие пути с лимитом
MATCH path = allShortestPaths(
  (a:Person {name: 'Alice'})-[*]-(b:Person {name: 'Diana'})
)
RETURN path;
```

### Направленность обхода

```cypher
// Только исходящие связи (быстрее — половина пространства поиска)
MATCH (a:Person {name: 'Alice'})-[:FRIENDS_WITH]->(friend)
RETURN friend.name;

// В обе стороны (медленнее — двойное пространство)
MATCH (a:Person {name: 'Alice'})-[:FRIENDS_WITH]-(friend)
RETURN friend.name;
```

**Правило:** если направление известно — всегда указывайте его. Это сокращает пространство поиска вдвое.

### Поиск по глубине (Blast Radius)

```cypher
// Все сущности, достижимые за 3 перехода от payment-api
MATCH (s:Service {name: 'payment-api'})<-[:DEPENDS_ON*1..3]-(dependent)
RETURN dependent.name, dependent.type;

// Ограничение результатов
MATCH (s:Service {name: 'payment-api'})<-[:DEPENDS_ON*1..3]-(dependent)
RETURN dependent.name, dependent.type
LIMIT 100;
```

## Агрегации и аналитика

### Базовые агрегации

```cypher
// Подсчёт узлов по меткам
MATCH (p:Person) RETURN count(p) AS totalPeople;

// Группировка и подсчёт
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
RETURN c.name, count(p) AS employees
ORDER BY employees DESC;

// Сбор связанных данных в список
MATCH (p:Person)-[:FRIENDS_WITH]->(friend:Person)
RETURN p.name, collect(friend.name) AS friends;

// Статистические функции
MATCH (p:Person)
RETURN avg(p.age) AS avgAge,
       min(p.age) AS minAge,
       max(p.age) AS maxAge;

// Степень узла (количество связей)
MATCH (p:Person)
RETURN p.name, size((p)-[:FRIENDS_WITH]-()) AS degree
ORDER BY degree DESC LIMIT 10;
```

### Оконные функции (Cypher 25)

```cypher
// Ранжирование сотрудников по зарплате внутри компании
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
RETURN c.name AS company,
       p.name AS employee,
       p.salary AS salary,
       rank() OVER (PARTITION BY c.company ORDER BY p.salary DESC) AS rank;

-- Накопленная сумма
MATCH (p:Person)
RETURN p.name,
       sum(p.salary) OVER (ORDER BY p.startDate ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulativeSalary;
```

## Условная логика

### CASE

```cypher
MATCH (p:Person)
RETURN p.name,
       CASE
         WHEN p.age < 30 THEN 'junior'
         WHEN p.age < 50 THEN 'middle'
         ELSE 'senior'
       END AS level;

-- Простой CASE
MATCH (p:Person)
RETURN p.name,
       CASE p.role
         WHEN 'Admin' THEN 'Administrator'
         WHEN 'Engineer' THEN 'Developer'
         ELSE 'Other'
       END AS roleName;
```

### FOREACH

```cypher
// Установка нескольких свойств по условию
MATCH (p:Person {name: $name})
FOREACH (ignore IN CASE WHEN p.archived THEN [1] ELSE [] END |
  SET p.archivedAt = datetime()
);

// Добавление связей из списка
MATCH (p:Person {name: $name})
UNWIND $tagNames AS tagName
MERGE (t:Tag {name: tagName})
MERGE (p)-[:HAS_TAG]->(t);
```

## Работа со списками и картами

### UNWIND

```cypher
// Развёртывание списка в строки
UNWIND ['Alice', 'Bob', 'Charlie'] AS name
RETURN name;

// UNWIND с параметром (типичный паттерн для драйверов)
UNWIND $personNames AS personName
MERGE (p:Person {name: personName})
RETURN p;

// UNWIND с индексом
UNWIND $items AS item
WITH item, index($items) AS idx
RETURN idx, item;
```

### List comprehensions

```cypher
// Собрать имена друзей
MATCH (p:Person {name: 'Alice'})-[:FRIENDS_WITH]->(f:Person)
RETURN [friend IN f | friend.name] AS friendNames;

// С фильтрацией
MATCH (p:Person)
RETURN [f IN (p)-[:FRIENDS_WITH]-() | f.name] AS closeFriends;
```

### Pattern comprehension

```cypher
// Подсчёт связей через pattern comprehension
MATCH (p:Person)
RETURN p.name, size([(p)-[:FRIENDS_WITH]->(f) | f]) AS friendCount;

// Сбор имён через pattern comprehension
MATCH (p:Person)
RETURN p.name, [(p)-[:WORKS_AT]->(c) | c.name] AS companies;
```

### Map projections

```cypher
// Выборочные свойства в map
MATCH (p:Person {name: 'Alice'})
RETURN p {.name, .age, .email} AS profile;

// С вычисляемым свойством
MATCH (p:Person)
RETURN p {.name, fullName: p.firstName + ' ' + p.lastName} AS profile;
```

## Подзапросы (Subqueries)

```cypher
// Подзапрос с `CALL { }`
MATCH (p:Person {name: $name})
CALL {
  WITH p
  MATCH (p)-[:FRIENDS_WITH]->(f:Person)
  RETURN count(f) AS friendCount
}
RETURN p.name, friendCount;

// Несколько подзапросов
MATCH (p:Person {name: $name})
CALL {
  WITH p
  MATCH (p)-[:WORKS_AT]->(c:Company)
  RETURN c.name AS company
}
CALL {
  WITH p
  MATCH (p)-[:LIVES_IN]->(city)
  RETURN city.name AS city
}
RETURN p.name, company, city;
```

## Временные типы и функции

```cypher
// Текущие значения
RETURN date() AS today, datetime() AS now, localdatetime() AS localNow;

// Создание конкретных значений
RETURN date('2026-09-30') AS d,
       datetime('2026-09-30T12:00:00+03:00') AS dt;

// Извлечение компонентов
MATCH (p:Person)
RETURN p.name,
       year(p.birthDate) AS birthYear,
       month(p.birthDate) AS birthMonth;

// Арифметика с датами
MATCH (p:Person)
RETURN p.name,
       duration.between(p.birthDate, date()) AS age;

// Duration
RETURN duration({days: 7, hours: 3}) AS d,
       duration.inDays(date('2026-01-01'), date('2026-09-30')) AS daysPassed;
```

## Строковые функции

```cypher
// Базовые операции
RETURN 'Hello' + ' ' + 'World' AS greeting,
       upper('hello') AS upper,
       lower('HELLO') AS lower,
       trim('  spaces  ') AS trimmed,
       replace('hello world', 'world', 'Neo4j') AS replaced;

// split / join
RETURN split('a,b,c', ',') AS parts,
       join(['a', 'b', 'c'], ',') AS joined;

// substring
RETURN substring('Neo4j', 0, 4) AS sub;

// Регулярные выражения
RETURN 'Neo4j 2026.09' =~ 'Neo4j.*' AS matches,
       'Neo4j 2026.09' =~ '\\d{4}\\.\\d{2}' AS hasVersion;

// Поиск в строке
RETURN 'Neo4j' CONTAINS '4j' AS contains,
       'Neo4j' STARTS WITH 'Neo' AS startsWith,
       'Neo4j' ENDS WITH '4j' AS endsWith;

// Длина строки
RETURN length('Neo4j') AS len;
```

## Строки с экранированием и многострочные литералы

```cypher
// Многострочный строковый литерал
RETURN '''
Line 1
Line 2
Line 3
''' AS multiline;

// Экранирование одинарных кавычек внутри строки
RETURN 'It''s a string with escaped quote' AS escaped;
```

## Типы данных и проверка

```cypher
// Проверка типов
MATCH (p:Person)
RETURN p.name,
       type(p.age) = 'INTEGER' AS isInteger,
       p.age IS NULL AS isNull,
       p.email IS NOT NULL AS hasEmail;

-- IS [NOT] NULL / EMPTY / TYPED
-- IS NULL / IS NOT NULL — работает с любым типом
-- IS EMPTY / IS NOT EMPTY — только для строк и списков
-- type(x) = 'INTEGER' — проверка конкретного типа

-- Приведение типов
RETURN toInteger('42') AS int,
       toFloat('3.14') AS float,
       toString(42) AS str,
       toBoolean('true') AS bool;
```

## Агрегации с фильтрацией (Cypher 25)

```cypher
// Подсчёт по условию внутри агрегации
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
RETURN c.name AS company,
       count(p) AS totalEmployees,
       count(p) FILTER (p.role = 'Engineer') AS engineers,
       avg(p.salary) FILTER (p.role = 'Engineer') AS avgEngineerSalary;
```

## Иерархические запросы (path expand)

```cypher
// Обход до глубины 3 с возвратом только листьев
MATCH path = (root:Service {name: 'payment-api'})-[:DEPENDS_ON*1..3]->(leaf)
WHERE NONE(x IN nodes(path)[0..-1] WHERE (leaf)-[:DEPENDS_ON]->(x))
RETURN leaf.name AS leafService;

-- NONE / ANY / ALL — предикаты над списками
-- nodes(path) — список узлов пути
-- [0..-1] — все кроме последнего элемента
```

## Оптимизация запросов в Cypher

### Параметризация

Всегда передавайте значения как параметры (`$name`), а не как литералы. Это позволяет переиспользовать план запроса между вызовами.

```cypher
// Правильно: план переиспользуется
MATCH (p:Person {email: $email}) RETURN p;

// Неправильно: каждый уникальный email — новый план
MATCH (p:Person {email: 'alice@example.com'}) RETURN p;
```

### Направление связей

Указывайте направление обхода, когда это возможно:

```cypher
// Правильно: ищет только исходящие связи
MATCH (a:Person)-[:FRIENDS_WITH]->(b:Person) RETURN a, b;

// Неправильно: проверяет обе стороны
MATCH (a:Person)-[:FRIENDS_WITH]-(b:Person) RETURN a, b;
```

### WITH — фильтрация до обхода

```cypher
// Правильно: ограничиваем набор перед обходом
MATCH (p:Person) WHERE p.active = true
WITH p
MATCH (p)-[:FRIENDS_WITH]->(f:Person)
RETURN p.name, collect(f.name) AS friends;

// Неправильно: обход по всем узлам с меткой
MATCH (p:Person)-[:FRIENDS_WITH]->(f:Person)
WHERE p.active = true
RETURN p.name, collect(f.name) AS friends;
```

### OPTIONAL MATCH

```cypher
// LEFT JOIN-подобная операция
MATCH (p:Person {name: $name})
OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
RETURN p.name, c.name;
```

**Предупреждение:** каждый `OPTIONAL MATCH` может умножить количество строк. Избегайте их в циклах и используйте `WITH` для ограничения набора перед `OPTIONAL MATCH`.

## Подсказки оптимизатору (Query Hints)

```cypher
// Принудительно использовать конкретный индекс
MATCH (p:Person {email: $email})
USING INDEX p:Person(email)
RETURN p;

// Принудительно сканировать узел (иногда быстрее для малых выборок)
MATCH (p:Person)
USING SCAN p:Person
WHERE p.age > 25
RETURN p;

// Указать планировщик и рантайм (для сравнения в EXPLAIN/PROFILE)
EXPLAIN CYPHER planner=cost runtime=pipelined
MATCH (a:Person)-[:FRIENDS_WITH]->(b:Person)
RETURN a, b;

-- Внимание: query hints — не догма. Они полезны для отладки, но в production
-- правильные индексы и параметризация работают надежнее ручных подсказок.
-- Избегайте хардкода hints: при изменении данных оптимальный план может смениться.
```

## Встроенные процедуры и функции

### Справочные запросы к схеме

```cypher
-- Список всех баз данных
SHOW DATABASES;

-- Список индексов с состоянием
SHOW INDEXES YIELD name, type, labelsOrTypes, properties, state, population, sizeBytes;

-- Список ограничений
SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties, ownedIndex;

-- Список зарегистрированных процедур
SHOW PROCEDURES YIELD name, signature, admin, rolesExecution
WHERE name STARTS WITH 'dbms.'
RETURN name, signature;

-- Список функций
SHOW FUNCTIONS YIELD name, signature;
```

### Управление базой данных

```cypher
-- Создание базы (Enterprise Edition)
CREATE DATABASE analytics;

-- Удаление базы (Enterprise Edition)
DROP DATABASE analytics;

-- Остановка/запуск базы
STOP DATABASE analytics;
START DATABASE analytics;

-- Просмотр информации о базе
SHOW DATABASES YIELD name, store, status, defaultLanguage, currentSize, transactionLog;
```

### Информация о store-файлах

```cypher
-- Размер базы и allocation
CALL dbms.listDatabases() YIELD name, currentSize, transactionLog, schema
RETURN name, currentSize, schema;

-- Проверка формата хранения
SHOW DATABASES YIELD name, store;
```

## Пакетная обработка

### CALL { } IN TRANSACTIONS

Начиная с Neo4j 5.21 доступна встроенная пакетная обработка `CALL { … } IN TRANSACTIONS` (CIT). С Neo4j 2026.04 и Cypher 25 `apoc.periodic.iterate` объявлен устаревшим; CIT становится стандартным способом batch-операций.

```cypher
// Обработка пачками по 10000 записей
MATCH (p:Person) WHERE p.processed IS NULL
CALL {
  WITH p
  SET p.processed = true, p.processedAt = datetime()
} IN TRANSACTIONS OF 10000 ROWS
RETURN count(*) AS processed;
```

**Варианты:**
- `IN TRANSACTIONS OF 10000 ROWS` — фиксированный размер батча
- `IN CONCURRENT TRANSACTIONS` — параллельная обработка (требует EE для полного параллелизма)

```cypher
// Пакетное удаление
MATCH (n:OldLabel)
CALL (n) {
  DETACH DELETE n
} IN TRANSACTIONS OF 1000 ROWS
RETURN count(*) AS deleted;
```

## Импорт данных

### LOAD CSV

```cypher
// Загрузка CSV с заголовками из каталога import
LOAD CSV WITH HEADERS FROM 'file:///people.csv' AS row
MERGE (p:Person {id: toInteger(row.id)})
SET p.name = row.name,
    p.email = row.email,
    p.age = toInteger(row.age);

// CSV через HTTP (Enterprise Edition)
LOAD CSV WITH HEADERS FROM 'https://example.com/data.csv' AS row
CREATE (n:Import {name: row.name});

// Пакетная вставка через CALL { }
LOAD CSV WITH HEADERS FROM 'file:///large_dataset.csv' AS row
CALL {
  WITH row
  MERGE (p:Person {id: toInteger(row.id)})
  SET p.name = row.name
} IN TRANSACTIONS OF 10000 ROWS;
```

**Пути к файлам:** по умолчанию Neo4j ищет файлы в директории `import/` (обычно `/var/lib/neo4j/import/`). Для чтения из внешних директорий:

```conf
# В neo4j.conf
dbms.directories.import=import
dbms.security.allow_csv_import_from_file_urls=true
```

## Управление транзакциями

```cypher
// Явное управление (редко нужно в драйверах)
BEGIN
CREATE (p:Person {name: 'Alice'})
COMMIT;

-- ROLLBACK прерывает текущую транзакцию
BEGIN
CREATE (p:Person {name: 'Alice'})
ROLLBACK;
```

**На практике:** драйверы управляют транзакциями автоматически через `execute_read`/`execute_write` (Python) или `session.executeRead`/`session.executeWrite` (Java/JS/.NET/Go). Явный `BEGIN`/`COMMIT` используется только в `cypher-shell` или при сложных batch-операциях.

## Управление запросами и кэшем

```cypher
-- Очистка кэша планов запросов
CALL db.clearQueryCaches();

-- Проверка текущих транзакций
SHOW TRANSACTIONS
YIELD transactionId, currentQuery, elapsedTime, status, currentQueryAllocatedBytes, pageFaults
RETURN transactionId, elapsedTime, status, currentQuery
ORDER BY elapsedTime DESC
LIMIT 10;

-- Прерывание транзакции
SHOW TRANSACTIONS YIELD transactionId AS txId WHERE txId = $id
TERMINATE TRANSACTION txId
YIELD message
RETURN txId, message;
```

## Устранение неполадок Cypher

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий DbHits** | `PROFILE` показывает тысячи DbHits | Отсутствует индекс на стартовом узле | Создать индекс на свойство из `MATCH (n:Label {prop: $val})` |
| **NodeByLabelScan** | `PROFILE` показывает полное сканирование | Нет индекса или не используется anchor point | Добавить индекс или уточнить паттерн |
| **Transaction rolled back** | Транзакция откатывается | Долгая транзакция, contention, превышен лимит памяти | Уменьшить батч, `CALL { } IN TRANSACTIONS` |
| **Медленный запрос** | Высокое время планирования + выполнения | Непараметризованный запрос, хардкод значений | Параметризовать запрос; план кэшируется по тексту |
| **Non-repeatable read** | Данные изменились внутри транзакции | Уровень изоляции read-committed | Повторное чтение; для strict consistency — перезапуск транзакции |
| **OutOfMemoryError** | Запрос падает, база жива | Транзакция превышает лимит памяти | Снизить `dbms.memory.transaction.total.max`, уменьшить батчи |
| **Deadlock** | Транзакция откатывается с deadlock | Конкурентная запись на одни узлы/связи | Перезапуск транзакции; упорядочить операции записи |
| **Ошибка "Procedure not found"** | APOC-процедура не находится | Несовместимая версия APOC | Сверить APOC и Neo4j по году и месяцу |
| **Query timeout** | Запрос прерывается по таймауту | `db.transaction.timeout` превышен | Увеличить таймаут или оптимизировать запрос |
| **Index not online** | Индекс в состоянии `POPULATING` долго | Большая база, недостаточно ресурсов | Дождаться завершения; проверить `SHOW INDEXES` |

## Лучшие практики

- **Параметризуйте все запросы.** Хардкод значений (`'alice@example.com'` вместо `$email`) приводит к переполнению кэша планов и дополнительной нагрузке на планировщик.
- **Индексируйте anchor points.** Каждый `MATCH (n:Label {prop: $val})` должен иметь индекс на `prop`. Без индекса запрос сканирует все узлы с меткой.
- **Указывайте направление связей.** `(a)-[:TYPE]->(b)` вдвое эффективнее `(a)-[:TYPE]-(b)`.
- **Ограничивайте обходы.** Всегда задавайте верхнюю границу для переменной длины: `*1..5` вместо `*`.
- **Используйте `CALL { } IN TRANSACTIONS` для batch.** Одна транзакция на весь датасет — путь к OOM и contention.
- **Не удаляйте и не пересоздавайте индексы часто.** Каждое создание индекса — I/O-интенсивная операция на всю базу.
- **Проверяйте планы в `PROFILE` на репрезентативных объёмах.** Тестовые данные на 100 узлах не покажут проблем, которые появятся на миллионах.
- **Не храните внутренние ID (`id()`).** Используйте `elementId()` или бизнес-ключи; внутренние ID переиспользуются после удаления.
- **Не смешивайте Cypher 5 и Cypher 25 без необходимости.** Создавайте новые базы на Cypher 25, старые мигрируйте постепенно.
- **Для DFS используйте `shortestPath`/`allShortestPaths`.** Не пишите обход вручную через `UNWIND range()` — встроенные алгоритмы используют оптимизированные структуры.
- **Ограничивайте результаты на каждом уровне.** Вложенные `MATCH` без `LIMIT` могут раскрывать декартово произведение.
- **Планируйте миграцию формата как операцию с окном простоя.** 100 ГБ — от 10 минут до более часа; тестируйте на копии.

## См. также

- **[Обзор Neo4j](./overview.md)** — редакции и лицензии, версии и поддержка, модель данных, форматы хранения, порты, версии Cypher и рантаймы, когда использовать, сравнение с альтернативами.
- **[Установка и настройка](./installation_and_setup.md)** — Ubuntu APT, Docker, Docker Compose, порты, начальная конфигурация.
- **[Архитектура и хранение](./architecture.md)** — Index-free adjacency, store files, транзакционный движок, WAL.
- **[Обслуживание и эксплуатация](./operations.md)** — память, checkpoint, WAL, диагностика, метрики.
- **[Оптимизация запросов](./query_optimization.md)** — EXPLAIN/PROFILE, индексы, правила эффективных запросов.
- **[APOC: библиотека расширений](./apoc.md)** — установка, конфигурация, типичные сценарии.
- **[Драйверы](./drivers.md)** — Python, Java, JavaScript/TypeScript.
- **[Бэкап и восстановление](./backup_and_restore.md)** — офлайн- и онлайн-бэкап, restore, PITR, проверка.
- **[Мониторинг и логи](./monitoring.md)** — журналы, query.log, метрики, Prometheus.
- **[Кластеризация и HA](./clustering.md)** — primary/secondary, топология, маршрутизация, DR.
- **[Безопасность](./security.md)** — RBAC, TLS.
- **[Антипаттерны моделирования графа](./data_modeling_antipatterns.md)** — гиперрёбра, мульти-лейблы, суперноды как следствие структуры данных.
- **[Миграции схемы и эволюция модели данных](./schema_migrations.md)** — версионирование изменений модели, expand/contract, Neo4j-Migrations.
- **[Безопасность](./security.md)** — параметризация как граница защиты, идентификаторы и белые списки.

