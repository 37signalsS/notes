# Neo4j: Драйверы для приложений

**Актуально для:** Neo4j 2025.x–2026.x, официальные драйверы 6.x. Проверенные версии: Java 6.3.0, Python 6.3.1, .NET 6.3.0, Go 6.3.0, JavaScript/TypeScript 6.2.0. Драйверы 6.x поддерживают подключение к Neo4j 4.4.x, 5.x, 2025.x и 2026.x.

## Определения

**Neo4j Drivers** — официальные библиотеки для подключения приложений к Neo4j, работающие по протоколу **Bolt**. Официально поддерживаются пять языков: Java, Python, .NET (C#), Go, JavaScript/TypeScript. Драйверы обеспечивают установку соединений, маршрутизацию в кластере, управление пулом соединений, выполнение Cypher-запросов и обработку результатов.

**Bolt** — бинарный протокол обмена данными между приложением и сервером Neo4j (по умолчанию порт 7687). Поддерживает зашифрованное (TLS) и незашифрованное соединение.

**URI-схемы подключения:**
- `bolt://` — прямое соединение, без TLS (локальная разработка)
- `bolt+s://` — прямое соединение с TLS, принимаются только сертификаты, подписанные доверенным ЦС (CA)
- `bolt+ssc://` — прямое соединение с TLS, принимаются самоподписанные (self-signed) сертификаты
- `neo4j://` — маршрутизируемое подключение (рекомендуется для кластеров), без TLS
- `neo4j+s://` — маршрутизируемое с TLS (только CA-сертификаты), рекомендуется для production
- `neo4j+ssc://` — маршрутизируемое с TLS (самоподписанные сертификаты)

**Causal Consistency (причинная согласованность)** — гарантия, что последующие чтения смогут увидеть изменения, сделанные предыдущими транзакциями (реализуется через **Bookmarks**).

## Основные концепции

Все официальные драйверы реализуют единообразный API и используют протокол Bolt для взаимодействия с сервером. Ключевые принципы работы:

- **Маршрутизация (Routing):** при использовании схемы `neo4j://` драйвер автоматически получает таблицу маршрутизации от сервера и направляет write-транзакции на leader соответствующей базы (primary-копию), а read-транзакции — на secondary и non-writer primary согласно политике маршрутизации.
- **Высокоуровневый API (`execute_query`)** — в драйверах 6.x доступен унифицированный метод для выполнения запросов с автоматическим управлением сессиями, транзакциями, ретраями и закладками (bookmarks).
- **Разделение транзакций**: операции чтения (`execute_read`) могут выполняться параллельно, операции записи (`execute_write`) требуют координации.
- **Управление пулами соединений** — драйверы автоматически поддерживают пул активных соединений, контролируют их жизненный цикл и проверяют доступность.
- **Автоматические ретраи** — retryable-ошибки (транзиентные, связанные с перегрузкой/переключением лидера) повторяются автоматически в рамках транзакционных функций.

## Практические примеры

### Python (neo4j Python Driver)

Установка:

```bash
pip install neo4j==6.3.1
```

Требуется Python 3.10 или новее (поддержка 3.7–3.9 удалена в драйвере 6.0). Имя пакета — `neo4j`; устаревшее имя `neo4j-driver` удалено в 6.0.

Базовый пример (высокоуровневый API `execute_query`):

```python
import neo4j
from neo4j import GraphDatabase

URI = "neo4j://localhost:7687"
AUTH = ("neo4j", "password123")

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    driver.verify_connectivity()

    # Создание узла
    driver.execute_query(
        "MERGE (p:Person {name: $name, email: $email})",
        name="Alice", email="alice@example.com"
    )

    # Чтение данных
    records, summary, keys = driver.execute_query(
        "MATCH (p:Person {name: $name})-[:FRIENDS_WITH]->(f) RETURN f.name AS name",
        name="Alice",
        routing_=neo4j.RoutingControl.READ
    )
    for record in records:
        print("Friend:", record["name"])
```

Работа через транзакционные функции:

```python
def create_person(tx, name, email):
    result = tx.run(
        "MERGE (p:Person {name: $name, email: $email}) RETURN p",
        name=name, email=email
    )
    return result.single()

def find_friends(tx, name):
    result = tx.run(
        "MATCH (p:Person {name: $name})-[:FRIENDS_WITH]->(friend) "
        "RETURN friend.name AS name"
    )
    return [record["name"] for record in result]

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    with driver.session() as session:
        session.execute_write(create_person, "Alice", "alice@example.com")
        friends = session.execute_read(find_friends, "Alice")
        print(f"Friends of Alice: {friends}")
```

Настройка пула соединений и его параметры разобраны в разделе [Connection Pooling](#connection-pooling-пул-соединений); минимальный пример:

```python
driver = GraphDatabase.driver(
    URI,
    auth=AUTH,
    max_connection_pool_size=200,
    max_connection_lifetime=1800,        # меньше таймаута балансировщика
    connection_acquisition_timeout=120,
)
```

Обработка ошибок:

В драйверах 6.x иерархия исключений переработана. Корневой класс — `GqlError`, от которого расходятся две ветви: `Neo4jError` (ответ сервера) и `DriverError` (проблема на стороне клиента). Это важно для маршрутизации ретраев: повторять нужно не всё подряд.

```text
GqlError
├── Neo4jError              # сервер вернул ошибку
│   ├── ClientError         # запрос некорректен — повтор бессмысленен
│   │   ├── CypherSyntaxError / CypherTypeError
│   │   ├── ConstraintError
│   │   ├── AuthError → TokenExpired
│   │   └── Forbidden
│   ├── DatabaseError       # ошибка сервера
│   └── TransientError      # retryable
│       ├── DatabaseUnavailable
│       ├── NotALeader
│       └── ForbiddenOnReadOnlyDatabase
└── DriverError             # проблема на стороне клиента
    ├── ServiceUnavailable  → RoutingServiceUnavailable, IncompleteCommit, ...
    ├── ConfigurationError  → AuthConfigurationError, CertificateConfigurationError, UnsupportedServerProduct
    ├── SessionError / TransactionError / ResultError
    └── ConnectionPoolError → ConnectionAcquisitionTimeoutError
```

```python
from neo4j.exceptions import (
    ConnectionAcquisitionTimeoutError,
    ServiceUnavailable,
    AuthError,
    TransientError,
    ClientError,
    DatabaseError,
)

try:
    with driver.session() as session:
        session.execute_write(create_person, "Alice", "alice@example.com")
except ConnectionAcquisitionTimeoutError:
    # Пул исчерпан: утечка сессий, слишком маленький max_connection_pool_size
    # либо слишком долгие транзакции
    print("Не удалось получить соединение из пула")
except ServiceUnavailable:
    print("Neo4j недоступен. Проверьте, запущен ли сервер.")
except AuthError:
    print("Ошибка аутентификации. Проверьте логин/пароль.")
except TransientError as e:
    # Драйвер уже повторил попытку внутри execute_write, если ошибка retryable
    print(f"Временная ошибка (можно повторить): {e}")
except ClientError as e:
    print(f"Ошибка запроса или прав доступа, повтор бессмысленен: {e.code} {e.message}")
except DatabaseError as e:
    print(f"Ошибка БД: {e.code} {e.message}")
```

> **Что изменилось в 6.x:** `ServiceUnavailable` больше не наследует `Neo4jError` — он перенесён в ветвь `DriverError` (клиентская ошибка). `ClientError` и `TransientError` больше не являются подклассами `DatabaseError`: раньше `except DatabaseError` мог перехватить ошибку запроса. Блоки `except` по-прежнему нужно располагать от специфичного к общему.

### Java (Neo4j Java Driver)

Установка (Maven):

```xml
<dependency>
    <groupId>org.neo4j.driver</groupId>
    <artifactId>neo4j-java-driver</artifactId>
    <version>6.3.0</version>
</dependency>
```

Пример с высокоуровневым API `ExecutableQuery`:

```java
import org.neo4j.driver.*;
import java.util.ArrayList;
import java.util.List;

// Driver реализует AutoCloseable, поэтому закрывается через try-with-resources.
// Это важно: close() вне try-with-resources не выполнится, если тело блока
// завершится исключением, и пул соединений останется открытым.
try (Driver driver = GraphDatabase.driver("neo4j://localhost:7687",
                                          AuthTokens.basic("neo4j", "password123"));
     Session session = driver.session()) {

    // Чтение. Результат нужно полностью прочитать ВНУТРИ транзакционной функции:
    // Result, возвращённый tx.run(), — ленивый поток, привязанный к транзакции,
    // и после её завершения больше не доступен. Сам Result не является
    // AutoCloseable — его нужно либо прочитать до конца, либо закрыть через consume().
    List<String> names = session.executeRead(tx -> {
        List<String> result = new ArrayList<>();
        Result rs = tx.run("MATCH (p:Person) RETURN p.name AS name LIMIT 10");
        while (rs.hasNext()) {
            result.add(rs.next().get("name").asString());
        }
        return result;
    });
    names.forEach(n -> System.out.println("Person: " + n));

    // Альтернативно: ExecutableQuery — результат буферизуется целиком,
    // поэтому его можно читать после execute().
    var eagerResult = driver.executableQuery(
        "MATCH (p:Person {name: $name}) RETURN p.name AS name"
    )
    .withParameters(Values.parameters("name", "Alice"))
    .execute();

    eagerResult.records().forEach(r ->
        System.out.println(r.get("name").asString())
    );
}
```

Транзакционные функции:

```java
import org.neo4j.driver.*;
import java.util.ArrayList;
import java.util.List;

try (Driver driver = GraphDatabase.driver("neo4j://localhost:7687",
                                          AuthTokens.basic("neo4j", "password123"));
     Session session = driver.session()) {

    // Запись
    session.executeWrite(tx -> {
        Result rs = tx.run(
            "MERGE (p:Person {name: $name, email: $email}) RETURN p",
            Values.parameters("name", "Alice", "email", "alice@example.com")
        );
        return rs.single().get("p").asNode().elementId();
    });

    // Чтение
    List<String> friends = session.executeRead(tx -> {
        List<String> result = new ArrayList<>();
        Result rs = tx.run(
            "MATCH (p:Person {name: $name})-[:FRIENDS_WITH]->(f) RETURN f.name AS name",
            Values.parameters("name", "Alice")
        );
        while (rs.hasNext()) {
            result.add(rs.next().get("name").asString());
        }
        return result;
    });
}
```

### JavaScript/TypeScript (Neo4j JS Driver)

Установка:

```bash
npm install neo4j-driver@6.2.0
```

Пример:

```javascript
const neo4j = require('neo4j-driver');

const driver = neo4j.driver(
  'neo4j://localhost:7687',
  neo4j.auth.basic('neo4j', 'password123')
);

async function main() {
  const session = driver.session({ defaultAccessMode: neo4j.session.READ });

  try {
    // Чтение
    const result = await session.executeRead(tx =>
      tx.run('MATCH (p:Person) RETURN p.name AS name LIMIT 10')
    );

    result.records.forEach(record => {
      console.log(record.get('name'));
    });

    // Запись (executeWrite)
    await session.executeWrite(tx =>
      tx.run('MERGE (p:Person {name: $name}) RETURN p', { name: 'Alice' })
    );
  } finally {
    await session.close();
    await driver.close();
  }
}

main();
```

### Go (Neo4j Go Driver)

Установка:

```bash
go get github.com/neo4j/neo4j-go-driver/v6@v6.3.0
```

Пример:

```go
package main

import (
	"context"
	"fmt"

	"github.com/neo4j/neo4j-go-driver/v6/neo4j"
)

func main() {
	ctx := context.Background()
	dbUri := "neo4j://localhost:7687"
	driver, err := neo4j.NewDriver(dbUri, neo4j.BasicAuth("neo4j", "password123", ""))
	if err != nil {
		panic(err)
	}
	defer driver.Close(ctx)

	err = driver.VerifyConnectivity(ctx)
	if err != nil {
		panic(err)
	}

	session := driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeRead})
	defer session.Close(ctx)

	result, err := session.ExecuteRead(ctx, func(tx neo4j.ManagedTransaction) (any, error) {
		res, err := tx.Run(ctx, "MATCH (p:Person) RETURN p.name AS name LIMIT 10", nil)
		if err != nil {
			return nil, err
		}
		var names []string
		for res.Next(ctx) {
			record := res.Record()
			name, _ := record.Get("name")
			names = append(names, name.(string))
		}
		return names, res.Err()
	})
	if err != nil {
		panic(err)
	}
	fmt.Println(result)
}
```

### .NET (Neo4j .NET Driver)

Установка (NuGet):

```bash
dotnet add package Neo4j.Driver --version 6.3.0
```

Пример:

```csharp
using Neo4j.Driver;

await using var driver = GraphDatabase.Driver(
    "neo4j://localhost:7687",
    AuthTokens.Basic("neo4j", "password123")
);

await driver.VerifyConnectivityAsync();

await using var session = driver.AsyncSession(o => o.WithDefaultAccessMode(AccessMode.Read));

var result = await session.ExecuteReadAsync(async tx =>
{
    var cursor = await tx.RunAsync("MATCH (p:Person) RETURN p.name AS name LIMIT 10");
    var names = new List<string>();
    await foreach (var record in cursor)
    {
        names.Add(record["name"].ToString());
    }
    return names;
});

foreach (var name in result)
{
    Console.WriteLine(name);
}
```

## Паттерны работы с драйверами

### Транзакции: executeRead vs executeWrite

Все драйверы чётко разделяют операции по типу доступа:

- **`executeRead` (Read)** — только чтение данных. В кластере может выполняться на secondary или non-writer primary, допускает параллельное выполнение. Рекомендуется для SELECT-подобных запросов.
- **`executeWrite` (Write)** — операции модификации данных (CREATE/UPDATE/DELETE/MERGE). Направляются на leader базы (primary-копию, выбранную Raft). Гарантируют согласованность записей.

Рекомендуется всегда явно указывать тип доступа (особенно при использовании `neo4j://` в кластере) для оптимальной маршрутизации нагрузки.

### Высокоуровневый API `execute_query`

В современных драйверах (6.x) предпочтителен единообразный метод `execute_query`:

- Автоматически управляет жизненным циклом сессии и транзакции
- Автоматически применяет ретраи для retryable-ошибок
- Автоматически управляет закладками (bookmarks), обеспечивая причинную согласованность между вызовами
- Упрощает код, особенно для простых запросов

При необходимости тонкой настройки (например, работа с `CALL {} IN TRANSACTIONS`) следует использовать явные транзакционные функции (`executeRead/executeWrite`) или `session.run()`.

### Управление закладками (bookmarks) и причинная согласованность

Закладки (bookmarks) позволяют гарантировать, что последующие чтения увидят результаты предыдущих записей. При использовании `execute_query` драйвер управляет ими автоматически через `BookmarkManager`; внутри одной сессии запросы причинно связаны автоматически.

Гарантия действует только между вызовами `execute_query` в одну базу. Чтобы сохранить её при смешивании `execute_query` и явных сессий, нужно передать им общий bookmark manager:

```python
bm = driver.execute_query_bookmark_manager
with driver.session(bookmark_manager=bm) as session:
    session.execute_write(...)
driver.execute_query("...", bookmark_manager_=bm)
```

### Connection Pooling (пул соединений)

Драйверы автоматически управляют пулом соединений. Пул **создаётся лениво**: создание объекта Driver не устанавливает соединение — первый коннект происходит при первом запросе. Driver потокобезопасен и должен существовать всё время работы приложения: создавать его на каждый запрос — антипаттерн, при котором каждое создание открывает собственный пул и разрывает сессии.

Настраиваемые параметры пула (значения по умолчанию подтверждены для Python и .NET драйверов 6.x; имена параметров в Java, Go и JavaScript отличаются):

| Параметр | По умолчанию | Назначение |
|---|---|---|
| `max_connection_pool_size` | 100 **на каждый хост** | Максимум соединений в пуле на один узел кластера |
| `max_connection_lifetime` | 3600 с (1 час) | Максимальное время жизни соединения до закрытия |
| `connection_acquisition_timeout` | 60 с | Сколько сессия ждёт свободное соединение из пула |
| `connection_timeout` | 30 с | Таймаут установки TCP-соединения (в Python 6.1+ покрывает и TLS handshake) |
| `connection_write_timeout` | 30 с | Таймаут передачи данных (Python, начиная с 6.0) |
| `liveness_check_timeout` | отключён | Проверка живости простаивающего соединения перед выдачей из пула |
| `max_transaction_retry_time` | 30 с (.NET) | Сколько драйвер суммарно повторяет retryable-транзакцию |

Поскольку лимит задан **на хост**, в кластере из 3 primary и 2 secondary теоретический потолок пула составляет 500 соединений. На практике драйвер открывает соединения только к тем узлам, которые присутствуют в routing table, и фактическое число зависит от топологии и нагрузки.

**Рекомендации:**
- `max_connection_lifetime` следует выставлять **немного меньше** таймаута keep-alive на сетевом оборудовании (load balancer, proxy, firewall, NAT). Иначе соединение будет молча обрываться на промежуточном оборудовании, и драйвер этого не увидит. Согласованная серверная настройка — `dbms.routing.driver.connection.max_lifetime` (по умолчанию `1h`).
- Размер пула не стоит наращивать «на всякий случай». Соединение занимает ресурсы на стороне сервера, а сам сервер может упереться в thread pool раньше, чем клиент — в пул: см. раздел про `dbms.connector.bolt.thread_pool_max_size`.
- `connection_acquisition_timeout` полезно **увеличить** (например, до 120 с) в приложениях с длинными транзакциями: иначе при пуске волны запросов сессии начнут отваливаться с `ConnectionAcquisitionTimeoutError` вместо того, чтобы дождаться соединения.

Пример настройки:

```python
driver = GraphDatabase.driver(
    URI,
    auth=AUTH,
    max_connection_pool_size=200,
    max_connection_lifetime=1800,        # меньше таймаута балансировщика
    connection_acquisition_timeout=120,
)
```

### Корректное завершение работы (graceful shutdown)

Драйвер **не закрывается деструкктором**. Начиная с 6.0 в Python закрытие через `__del__()` удалено: при попытке неявного закрытия выдаётся `ResourceWarning`. Это сделано намеренно — вызов деструктора недетерминирован, и «молчаливое» закрытие приводило к утечкам соединений.

Отсюда два практических требования:

1. **Явно закрывать Driver при остановке приложения**, в обработчике сигнала. Без этого процесс завершится, оставив открытые сокеты.
2. **Не обрывать контекст/транзакцию слишком рано.** В драйвере Go это зафиксировано явно: преждевременное завершение контекста негативно сказывается на пуле соединений и снижает производительность драйвера — соединение возвращается в пул в непредсказуемом состоянии.

```python
import signal, sys
from neo4j import GraphDatabase

driver = GraphDatabase.driver(URI, auth=AUTH)

def shutdown(signum, frame):
    driver.close()          # дождаться завершения активных сессий
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
```

В Go то же самое через `defer driver.Close(ctx)`; в .NET — `await using` (вызывает `DisposeAsync`).

### Обработка ошибок

Политика повторов единообразна для всех драйверов и определяется тем, **от кого пришла ошибка** — от сервера или от клиента:

| Категория ошибки | Примеры | Повторять? |
|---|---|---|
| Клиентская, соединение недоступно | `ServiceUnavailable` (в т.ч. `RoutingServiceUnavailable`), DNS-ошибка | Да, вручную, с экспоненциальным backoff. Таймаут исчерпан — устранять первопричину, а не повторять |
| Серверная, retryable | `TransientError` → `NotALeader`, `DatabaseUnavailable` | Драйвер повторяет **автоматически** внутри `execute_read`/`execute_write`/`execute_query` в пределах `max_transaction_retry_time` |
| Серверная, запрос некорректен | `ClientError` → `CypherSyntaxError`, `CypherTypeError`, `ConstraintError`, `Forbidden` | Нет. Повтор приведёт к тому же результату |
| Клиентская, ошибка конфигурации | `ConfigurationError`, `CertificateConfigurationError`, `UnsupportedServerProduct` | Нет. Требуется правка конфигурации или версий |
| Серверная, прочие | `DatabaseError` | Нет. Разбирать по коду и тексту ошибки |

Три практических вывода:

- **`max_transaction_retry_time` ограничивает суммарное время ретраев**, а не число попыток. По умолчанию 30 с; для транзакций с внешними вызовами внутри (HTTP-запрос, вычисление) этого может не хватить — либо, наоборот, слишком много попыток создаст давление на и так перегруженный сервер.
- **Не оборачивайте `session.run()` в собственный retry-цикл.** Неявные транзакции не дают гарантий автоматического повтора; начиная с 6.2 драйвер делает одну повторную попытку только для ошибок, помеченных сервером как идемпотентные, и это можно отключить через `disable_auto_commit_retries`. Полноценный retry даёт только транзакционная функция.
- **Ошибки внутри callback ретраятся автоматически**, поэтому транзакционная функция должна быть идемпотентной: не отправлять письма, не списывать деньги и не вызывать внешние API напрямую из тела функции. Вызывайте их после успешного `execute_write`.

Иерархия исключений для Python и корректный порядок `except` приведены в разделе [Python](#python-neo4j-python-driver).

### Безопасность подключения

- **TLS:** для production использовать `neo4j+s://` (только доверенные CA-сертификаты). `neo4j+ssc://` допустим только в тестовых/dev-средах с самоподписанными сертификатами.
- **mTLS (Mutual TLS):** поддерживается драйверами — клиентский сертификат может использоваться как второй фактор аутентификации (Enterprise). Конфигурация указывается через провайдер клиентских сертификатов в настройках драйвера.
- **Аутентификация:** поддерживаются Basic, Kerberos, Bearer (SSO/OIDC), кастомные схемы, а также ротация токенов (TokenManager) без перезапуска драйвера.

## Мониторинг, диагностика и эксплуатация

### Проверка связности (health check)

Метод `verify_connectivity()` устанавливает **read-соединение** и обменивается данными с сервером, проверяя учётные данные и совместимость версий. Физическое соединение при этом не закрывается — оно возвращается в пул и используется повторно, поэтому регулярные health check такого типа не создают churn. Это дешёвый способ отличить «сервер не отвечает» от «неверный пароль» и «несовместимая версия».

```python
with GraphDatabase.driver(URI, auth=AUTH) as driver:
    driver.verify_connectivity()
    # → соединение установлено, авторизация пройдена
```

> **Важно:** даже если `verify_connectivity()` бросил исключение, драйвер всё равно нужно закрыть через `close()`, чтобы освободить ресурсы. Это явно оговорено в docstring метода Python-драйвера: *«Even if this method raises an exception, the driver still needs to be closed via close() to free up all resources»*.

В Docker-средех этот вызов — естественный кандидат на healthcheck-команду приложения. Со стороны самого сервера проверять разумнее через `cypher-shell`:

```bash
cypher-shell -a bolt://localhost:7687 -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1"
# → 1 row, 1 ms   (значение 1 и отсутствие ошибки — успех)
```

### Сторона сервера: что важно знать при тюнинге под драйвер

Пул соединений драйвера и worker-пул сервера — **разные вещи**. Это самая частая причина неверных выводов при планировании нагрузки.

- `dbms.connector.bolt.thread_pool_max_size` задаёт количество **Bolt worker-потоков**, а не соединений. Один поток обслуживает множество соединений, поэтому число соединений на сервере по умолчанию **не ограничено** — пул клиента может вырасти до числа доступных соединений на машине.
- Собственно ограничение числа соединений — на стороне драйвера (`max_connection_pool_size`).
- Сервер сообщает клиенту подсказки через Bolt, в том числе `connection.recv_timeout_seconds`, и драйвер применяет их к socket-timeout. Видно это только в debug-логах протокола.

Практическое следствие: если на сервере упёрлись в thread pool, увеличение клиентского пула **не поможет** — соединения начнут только ждать в очереди, и вырастет `dbms.bolt.accumulated_queue_time`. Сначала увеличивайте `dbms.connector.bolt.thread_pool_max_size`.

### Метрики Bolt на стороне сервера

Доступны через Prometheus (`/metrics`), JMX, Graphite и CSV — см. [Метрики Neo4j](https://neo4j.com/docs/operations-manual/current/monitoring/metrics/reference/). Для диагностики поведения драйверов релевантны:

| Метрика | Что показывает |
|---|---|
| `dbms.bolt.connections_running` | Соединения, активно исполняющие Cypher. Приближение к `thread_pool_max_size` означает работу на пределе |
| `dbms.bolt.connections_idle` | Простаивающие соединения |
| `dbms.bolt.connections_opened` / `connections_closed` | **Накопительные** счётчики — сравнивать их абсолютные значения бессмысленно. Смотрите на *разность* между ними и на скорость (`rate()`): стабильно растущий разрыв означает соединения, которые открываются и сразу закрываются, то есть обрыв на сетевом оборудовании или по `max_connection_lifetime` |
| `dbms.bolt.accumulated_queue_time` | Суммарное время ожидания в очереди на worker-поток. Ненулевое значение — сервер на пределе (требует `internal.server.bolt.thread_pool_queue_size`) |
| `dbms.bolt.messages_received` vs `messages_started` | Большой разрыв — сообщения копятся, свободных worker-потоков нет |
| `dbms.bolt.accumulated_processing_time` | Суммарное время обработки — база для расчёта утилизации |

Полный список и пороги — в [мониторинге Neo4j](./monitoring.md) и в [документации по метрикам](https://neo4j.com/docs/operations-manual/current/monitoring/metrics/reference/).

### Логирование драйвера

Включается через конфигурацию драйвера и состоит из двух независимых уровней:

- логирование самого драйвера;
- **Bolt tracing** — поуровневая трассировка сообщений протокола. Выключена по умолчанию, конфигурируется на уровне сессии независимо от основного логирования.

Типичный фрагмент debug-вывода при успешном подключении (.NET):

```log
DEBUG [conn-localhost:7687-1] C: HELLO [{user_agent, neo4j-dotnet/6.3.0}, {routing, [{address, localhost:7687}]}]
DEBUG [conn-localhost:7687-1] C: LOGON [{scheme, basic}, {principal, neo4j}, {credentials, ******}]
DEBUG [conn-localhost:7687-1] S: SUCCESS [{server, Neo4j/2026.09.0}, {connection_id, bolt-228}, {hints, [{connection.recv_timeout_seconds, 120}]}]
INFO  Routing table is updated => RoutingTable{database=neo4j, routers=[neo4j://localhost:7687/], writers=[...], readers=[...], expiresAfter=300s}
```

Из этого вывода видно: версию драйвера (`user_agent`), факт успешной авторизации (пароль маскируется), `connection_id` для корреляции с серверными логами и **TTL таблицы маршрутизации** (здесь 300 с).

> **Осторожно с trace-уровнем.** Записи уровня `Trace` могут содержать чувствительные данные, включая учётные данные. Такие логи следует считать конфиденциальными и не выгружать в открытые системы логирования. Для диагностики обычно достаточно `Debug`.

В Python драйвер 6.x разделяет логи на под-логгеры `neo4j.pool` (пул соединений) и `neo4j.session` (сессии и ретраи транзакций) — это позволяет точечно включить трассировку только одного слоя.

В Python 6.3+ SSL-контекст, создаваемый драйвером, уважает переменную окружения `SSLKEYLOGFILE` — можно расшифровать TLS-трафик штатными средствами OpenSSL без изменения кода.

### Телеметрия драйвера

Драйвер может отправлять анонимную статистику использования, если сервер этого запросит. Управляется на стороне сервера настройкой `server.bolt.telemetry.enabled`; **на self-managed инстансах выключено по умолчанию**. Отключение со стороны клиента:

| Язык | Способ |
|---|---|
| Python | `telemetry_disabled=True` |
| JavaScript | `telemetryDisabled: true` |
| Go | `conf.TelemetryDisabled = true` |
| .NET | `conf.WithTelemetryDisabled()` |

> В официальном руководстве по Go-драйверу пример содержит опечатку (`TelemetryDisabled = false` при тексте «never send»). Поле называется `TelemetryDisabled`, поэтому отключение — это `true`; поведение в .NET-руководстве для того же поля указано корректно.

### Диагностика типовых проблем

| Симптом | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| `ConnectionAcquisitionTimeoutError` | Исчерпан пул: утечка сессий, слишком долгие транзакции или малый `max_connection_pool_size` | Проверить, что все сессии закрываются; сопоставить с `dbms.bolt.connections_running` | Закрыть утекающие сессии; увеличить `connection_acquisition_timeout`; проверить транзакции |
| `ServiceUnavailable` при нормальном `curl` на порт | URI указывает не на тот хост (например, на localhost из контейнера) | Включить debug-лог, посмотреть фактический `HELLO` | Проверить `NEO4J_URI` / hostname, доступность DNS |
| `AuthError` | Неверный пароль либо смена `dbms.security.auth_enabled` | `cypher-shell` с теми же учётными данными | Синхронизировать credentials; при `dbms.security.auth_enabled=false` убрать `auth` из драйвера |
| Редкие обрывы соединений под нагрузкой | `max_connection_lifetime` ≥ таймаута балансировщика/NAT | Сопоставить `dbms.bolt.connections_closed` и `connections_opened` | Снизить `max_connection_lifetime` относительно таймаута инфраструктуры |
| Все запросы идут на лидера, реплики простаивают | Не указан режим доступа: для `session.run()` драйвер по умолчанию считает транзакцию **write**-транзакцией | Проверить `dbms.bolt.connections_running` по узлам кластера | Задать `default_access_mode=READ` / `routing_=READ` |
| `UnsupportedServerProduct` | Нет общей версии Bolt (сильно разъехались версии драйвера и сервера) | Проверить версии | Обновить драйвер до 6.x либо сервер |
| Рост потребления памяти процесса | Соединения не закрываются: полагались на деструктор | `ResourceWarning` при `python -X dev` | Явно закрывать Driver; см. graceful shutdown |

## Эксплуатационные практики

### Ротация токенов без перезапуска

Если используются SSO/OIDC-токены с ограниченным сроком жизни, статический токен в драйвере рано или поздно перестанет работать. Для этого драйверы предоставляют **TokenManager** — объект, который драйвер опрашивает при каждой необходимости аутентификации:

- **Go:** `auth.BearerTokenManager(func(ctx) (AuthToken, *time.Time, error))`, а также `BasicTokenManager`; вращение в пределах `BasicTokenManager`.
- **.NET:** `AuthTokenManagers.Bearer(GetTokenAsync)` — возвращает `AuthTokenAndExpiration`.
- **Python:** вращение реализуется через callback-функции, возвращающие `ExpiringAuth` с относительным временем истечения.

Два жёстких ограничения:

1. **Это не механизм смены пользователя.** Менеджер токенов обязан всегда возвращать токен той же identity. Для работы от имени другого пользователя существует отдельный механизм — impersonation на уровне сессии или запроса (`impersonated_user`).
2. **Провайдер не должен обращаться к драйверу изнутри** — это приводит к дедлокам и неопределённому поведению.

Уже выполняющиеся транзакции при ротации дорабатываются без повторной аутентификации; разные транзакции одной сессии могут использовать разные токены.

### Кэширование routing table

Драйвер с URI-схемой `neo4j://` получает таблицу маршрутизации при подключении и обновляет её по TTL, который сообщает сервер (в примере выше — 300 с). Ручное управление этим процессом удалено из драйверов 5.x: параметры `update_routing_table_timeout` и `session_connection_timeout` больше не существуют, и в 6.x удалены. Keep-alive, приходящие через подсказки конфигурации, вместе с `connection_acquisition_timeout` считаются достаточными, чтобы драйвер не зависал.

Практическое следствие для сети: если между приложением и кластером стоит балансировщик, он обязан корректно обрабатывать три разных адреса — writer, reader и router. Иначе обновление routing table будет стабильно падать, а ошибка будет выглядеть как `RoutingServiceUnavailable` (подкласс `ServiceUnavailable`).

### Кастомный резолвер адресов

Если имя, указанное в URI, не совпадает с тем, что драйвер может разрешить, или требуется проброс на другой порт, используется **resolver**. Важное ограничение, одинаковое для всех драйверов: резолвер применяется **только к начальному подключению**. Адреса, приходящие из таблицы маршрутизации, через него не проходят.

```go
driver, err := neo4j.NewDriver(
    "neo4j://example.com:9999",
    neo4j.BasicAuth(dbUser, dbPassword, ""),
    func(conf *config.Config) {
        conf.AddressResolver = func(address config.ServerAddress) []config.ServerAddress {
            return []config.ServerAddress{neo4j.NewServerAddress("localhost", "7687")}
        }
    },
)
```

Резолвер не может изменить схему URI. В .NET-драйвере начиная с 6.1 резолвер может вернуть адрес с **другим портом**; в более ранних версиях это приводило к ошибке.

### Кастомная аутентификация

Помимо встроенных схем (Basic, Kerberos, Bearer, NoAuth, Custom) каждый драйвер предоставляет свой механизм подключения пользовательской схемы аутентификации: **Go** — `neo4j.CustomAuth(scheme, username, password, realm, parameters)`, **.NET** — `AuthTokens.Custom(principal, credentials, realm, scheme, parameters)`. В Python параметр `auth_callback` сессии удалён начиная с драйвера 6.0 — подключение пользовательской схемы выполняется через собственный объект `AuthToken`, передаваемый в конструктор драйвера.

Аутентификация применяется к серверу, на котором `dbms.security.auth_enabled` включён (по умолчанию `true`). Отключение аутентификации допустимо только при явном `NoAuth` / отсутствии параметра `auth` и является серьёзным риском.

### Политика обновления драйвера

Начиная с мажорной версии 6.0 драйверы **перешли с ежемесячного цикла релизов на цикл по мере готовности**. Патч-версии выходят крайне редко: исправления входят в следующую минорную версию, и рекомендация — обновляться до последней минорной версии внутри своего мажора. Внутри одного мажора ломающих изменений API не бывает.

**Практический порядок обновления:** сначала драйвер, потом сервер. Драйвер 6.x совместим и со старыми серверами (4.4, 5.x, 2025.x), и с новыми, а откатить обновление приложения проще, чем откатить обновление сервера. Драйвер 5.28 тоже форвард-совместим с серверами 2026.x, но связка «новый драйвер + старый сервер» безопаснее.

Аналогично для Python: минимальная версия интерпретатора — 3.10, `setup.py` удалён, сборка идёт через `pyproject.toml` — инструментам сборки нужно это учитывать.

## Дополнительная информация

- **[Матрица поддерживаемых версий](https://neo4j.com/developer/kb/neo4j-supported-versions/)** — сроки hotfix и совместимые версии драйверов для каждого релиза сервера.
- **[Документация драйверов](https://neo4j.com/docs/)** — руководства по Java, Python, .NET, Go и JavaScript.
- **[Протокол Bolt](https://neo4j.com/docs/bolt/current/)** — версии протокола, которые согласуются при handshake: источник расхождений при `UnsupportedServerProduct`.
- **[Управление коннекторами](https://neo4j.com/docs/operations-manual/current/configuration/connectors/)** — настройка `server.bolt.*` на стороне сервера, включая `advertised_address` для случаев за балансировщиком.

## См. также

- **[Cypher: полное руководство](./cypher_guide.md)** — CRUD, обход графа, агрегации
- **[APOC: библиотека расширений](./apoc.md)** — расширенные возможности обработки данных
- **[Установка и настройка Neo4j](./installation_and_setup.md)** — развёртывание и конфигурация сервера
- **[Архитектура и хранение](./architecture.md)** — Index-free adjacency, принципы работы графовой БД
- **[Кластеризация и высокая доступность](./clustering.md)** — primary/secondary, маршрутизация, балансировка лидерств
- **[Безопасность](./security.md)** — аутентификация, авторизация, TLS
- **[Обслуживание и эксплуатация](./operations.md)** — мониторинг, бэкап, диагностика
- **[Безопасность](./security.md)** — параметризация запросов как защита от инъекций, телеметрия в логах.
- **[Нагрузочное тестирование](./performance_testing.md)** — генерация нагрузки драйвером, маршрутизация чтений и записей.

