# Neo4j: Драйверы для приложений

Neo4j предоставляет официальные драйверы для основных языков программирования. Все драйверы используют протокол Bolt для взаимодействия с сервером.

## Python (neo4j Python Driver)

```bash
pip install neo4j
```

```python
from neo4j import GraphDatabase

# Подключение
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password123"))

# Запись данных
def create_person(tx, name, email):
    result = tx.run(
        "MERGE (p:Person {name: $name, email: $email}) RETURN p",
        name=name, email=email
    )
    return result.single()

# Чтение данных
def find_friends(tx, name):
    result = tx.run(
        """MATCH (p:Person {name: $name})-[:FRIENDS_WITH]->(friend)
           RETURN friend.name AS name""",
        name=name
    )
    return [record["name"] for record in result]

# Использование sessions
with driver.session() as session:
    session.execute_write(create_person, "Alice", "alice@example.com")
    friends = session.execute_read(find_friends, "Alice")
    print(f"Friends of Alice: {friends}")

driver.close()
```

## Java (Neo4j Java Driver)

```xml
<dependency>
    <groupId>org.neo4j.driver</groupId>
    <artifactId>neo4j-java-driver</artifactId>
    <version>5.x.x</version>  <!-- Версия совместима с Neo4j 2026.x -->
</dependency>
```

```java
import org.neo4j.driver.*;

Driver driver = GraphDatabase.driver("bolt://localhost:7687", AuthTokens.basic("neo4j", "password123"));

try (Session session = driver.session()) {
    // Запись
    session.executeWrite(tx -> {
        Result result = tx.run(
            "MERGE (p:Person {name: $name, email: $email}) RETURN p",
            Parameters.parameters("name", "Alice", "email", "alice@example.com")
        );
        return result.single();
    });

    // Чтение
    Result result = session.executeRead(tx ->
        tx.run("MATCH (p:Person)-[:FRIENDS_WITH]->(f) RETURN f.name AS name")
    );

    while (result.hasNext()) {
        Record record = result.next();
        System.out.println("Friend: " + record.get("name").asString());
    }
}

driver.close();
```

## JavaScript/TypeScript (Neo4j JS Driver)

```bash
npm install neo4j-driver
```

```javascript
const neo4j = require('neo4j-driver');

const driver = neo4j.driver(
  'bolt://localhost:7687',
  neo4j.auth.basic('neo4j', 'password123')
);

const session = driver.session();

// Создание узла
await session.executeWrite(tx =>
  tx.run('MERGE (p:Person {name: $name}) RETURN p', { name: 'Alice' })
);

// Чтение
const result = await session.executeRead(tx =>
  tx.run('MATCH (p:Person) RETURN p.name AS name LIMIT 10')
);

result.records.forEach(record => {
  console.log(record.get('name'));
});

await session.close();
await driver.close();
```

## Паттерны работы с драйверами

### Транзакции: executeRead vs executeWrite

Все драйверы разделяют операции на **read** (только чтение, могут выполняться параллельно) и **write** (запись, требуют координации):

```python
# Python: read-транзакция
def get_statistics(tx):
    result = tx.run("MATCH (p:Person) RETURN count(p) AS total")
    return result.single()["total"]

with driver.session() as session:
    total = session.execute_read(get_statistics)
```

### Connection Pooling

Драйверы управляют пулом соединений автоматически. Рекомендации:
- **Размер пула:** по умолчанию 100 соединений; для высоконагруженных приложений — до 200-300.
- **Max Connection Lifetime:** обновляйте соединения каждые 60 минут для избежания утечек.

```python
# Python: настройка пула
driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "password123"),
    max_connection_pool_size=200,
    max_connection_lifetime=3600
)
```

### Обработка ошибок

```python
from neo4j.exceptions import (
    ServiceUnavailable,
    AuthError,
    TransientError,
    DatabaseError
)

try:
    with driver.session() as session:
        session.execute_write(create_person, "Alice", "alice@example.com")
except ServiceUnavailable:
    print("Neo4j недоступен. Проверьте, запущен ли сервер.")
except AuthError:
    print("Ошибка аутентификации. Проверьте логин/пароль.")
except TransientError as e:
    print(f"Временная ошибка (можно повторить): {e}")
except DatabaseError as e:
    print(f"Ошибка БД (требуется investigation): {e}")
```

## См. также
- **[Cypher: полное руководство](./cypher_guide.md)** — CRUD, обход графа, агрегации.
- **[APOC: библиотека расширений](./apoc.md)** — расширенные возможности обработки данных.
- **[Установка и настройка](./installation_and_setup.md)** — развёртывание Neo4j.
