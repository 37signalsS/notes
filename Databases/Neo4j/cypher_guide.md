# Neo4j: Cypher — полное руководство

## CRUD-операции

```cypher
// === CREATE ===
CREATE (p:Person {name: 'Charlie', email: 'charlie@example.com', age: 28})
RETURN p;

// Создание нескольких узлов и связей
CREATE
  (a:Person {name: 'Alice', age: 30}),
  (b:Person {name: 'Bob', age: 25}),
  (c:Company {name: 'TechCorp'}),
  (a)-[:WORKS_AT {since: 2019, role: 'Engineer'}]->(c),
  (b)-[:WORKS_AT {since: 2021, role: 'Designer'}]->(c),
  (a)-[:FRIENDS_WITH {since: 2020}]->(b)
RETURN a, b, c;

// === MERGE (создание или поиск) ===
MERGE (p:Person {name: 'Diana'})
ON CREATE SET p.createdAt = datetime(), p.role = 'Admin'
ON MATCH SET p.lastSeen = datetime()
RETURN p;

// === MATCH + WHERE ===
MATCH (p:Person) WHERE p.age > 25
RETURN p.name, p.age
ORDER BY p.age DESC;

// === UPDATE ===
MATCH (p:Person {name: 'Alice'})
SET p.age = 31, p.city = 'New York', p:Employee
RETURN p;

// === DELETE ===
// Удаление узла без связей
MATCH (p:Person {name: 'Charlie'}) DELETE p;

// Удаление узла со всеми связями (осторожно!)
MATCH (p:Person {name: 'Charlie'}) DETACH DELETE p;

// Удаление конкретной связи
MATCH (a:Person {name: 'Alice'})-[r:FRIENDS_WITH]->(b:Person {name: 'Bob'})
DELETE r;

// Массовое удаление (с пагинацией для безопасности)
MATCH (n:OldLabel) WITH n LIMIT 10000 DETACH DELETE n;
```

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
// Уникальность email
CREATE CONSTRAINT FOR (p:Person) REQUIRE p.email IS UNIQUE;

// Составной уникальный ключ (Node Key)
CREATE CONSTRAINT FOR (p:Person) REQUIRE (p.firstName, p.lastName) IS NODE KEY;

// Обязательное наличие поля (Enterprise)
CREATE CONSTRAINT FOR (p:Person) REQUIRE p.name IS NOT NULL;
```

## Обход графа (Traversals)

```cypher
// Нахождение друзей друзей (2 уровня)
MATCH (a:Person {name: 'Alice'})-[:FRIENDS_WITH*1..2]->(friend)
RETURN DISTINCT friend.name;

// Кратчайший путь между двумя узлами
MATCH path = shortestPath(
  (a:Person {name: 'Alice'})-[*]-(b:Person {name: 'Diana'})
)
RETURN path, length(path) AS hops;

// Все пути длины до 5
MATCH path = (start:Person {name: 'Alice'})-[*..5]->(end:Person)
WHERE start <> end
RETURN path LIMIT 10;

// Поиск Blast Radius (радиус поражения) в инфраструктуре
MATCH (s:Service {name: 'payment-api'})<-[:DEPENDS_ON*1..3]-(dependent)
RETURN dependent.name, dependent.type;
```

## Агрегации и аналитика

```cypher
// Подсчёт узлов по меткам
MATCH (p:Person) RETURN count(p) AS totalPeople;

// Группировка и подсчёт
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
RETURN c.name, count(p) AS employees
ORDER BY employees DESC;

// Сбор связанных данных в список (COLLECT)
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

## Импорт данных из CSV

```cypher
// Загрузка CSV с заголовками
LOAD CSV WITH HEADERS FROM 'file:///people.csv' AS row
MERGE (p:Person {id: toInteger(row.id)})
SET p.name = row.name,
    p.email = row.email,
    p.age = toInteger(row.age);

// CSV через HTTP
LOAD CSV WITH HEADERS FROM 'https://example.com/data.csv' AS row
CREATE (n:Import {name: row.name});

// Пакетная вставка с периодическим обновлением
LOAD CSV WITH HEADERS FROM 'file:///large_dataset.csv' AS row
CALL {
  WITH row
  MERGE (p:Person {id: toInteger(row.id)})
  SET p.name = row.name
} IN TRANSACTIONS OF 10000 ROWS;
```

**Пути к файлам CSV:** по умолчанию Neo4j ищет файлы в директории `import/` (обычно `/var/lib/neo4j/import/`). Убедитесь, что файлы размещены там, или включите чтение из внешних директорий:

```conf
# В neo4j.conf
dbms.directories.import=import
dbms.security.allow_csv_import_from_file_urls=true
```

## См. также
- **[Обзор Neo4j](./overview.md)** — определения и место в экосистеме.
- **[Оптимизация запросов](./query_optimization.md)** — EXPLAIN/PROFILE, индексы, правила эффективных запросов.
- **[APOC: библиотека расширений](./apoc.md)** — расширенные возможности импорта и обработки.
- **[Драйверы](./drivers.md)** — Python, Java, JavaScript/TypeScript.
