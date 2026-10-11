# Клиентские драйверы и конфигурация

**Актуально для:** Apache Java Driver 4.19.x (с 4.18 поддерживается Apache Software Foundation) / ScyllaDB Java Driver 4.19.x (com.scylladb) / cassandra-driver (Python) 3.30.x / gocql (Go) 2.1.x

## Определения

| Термин | Определение |
| :--- | :--- |
| **CqlSession** | Основной объект драйвера: пул соединений ко всем узлам кластера, метаданные схемы и топологии. Один session на приложение (не на запрос) |
| **Native protocol** | Бинарный асинхронный протокол Cassandra (версии V3–V5). Порт 9042. Мультиплексирует до 32768 запросов на одно TCP-соединение через stream id |
| **Load balancing policy (LBP)** | Политика выбора узлов: какие узлы подключать (distance) и в каком порядке пробовать их при выполнении запроса (query plan) |
| **Token-aware routing** | Маршрутизация запроса на реплику-владельца данных (по routing key) — исключает лишний hop через координатор |
| **Distance (LOCAL/REMOTE/IGNORED)** | Классификация узла политикой: LOCAL/REMOTE — активные соединения, IGNORED — драйвер не подключается |
| **Retry policy** | Политика повторов при ошибках координатора (Unavailable/ReadTimeout/WriteTimeout). Применяется **только к идемпотентным запросам** |
| **Reconnection policy** | Интервалы переподключения к узлу при обрыве соединений (пулы и control connection) |
| **Execution profile** | Именованный набор опций драйвера (таймаут, consistency, retry policy) — позволяет разный SLA для разных запросов в одном session |
| **Idempotence** | Свойство запроса: повторное выполнение не меняет результат. Без него драйвер не ретраит запрос (риск дублирования записи) |
| **Heartbeat** | Keepalive на уровне драйвера: фиктивный запрос при простое соединения, чтобы сетевое оборудование не дропило idle-соединения |
| **Control connection** | Служебное соединение к произвольному узлу для административных запросов (метаданные схемы, топология) |
| **Query plan** | Упорядоченный список узлов для запроса; драйвер пробует узлы по порядку согласно retry/speculative policy |

## Как работает драйвер

**Мультиплексирование, а не пул как в JDBC.** Драйвер держит **один пул соединений на узел** (не один коннекшн на запрос). Каждое TCP-соединение обслуживает до 32768 одновременных запросов (stream id). Это принципиально отличается от JDBC-пула: «настроить как пул» — типичная ошибка.

**Три политики определяют поведение:**

1. **LBP** — какие узлы использовать и в каком порядке;
2. **Retry policy** — что делать при ошибке координатора;
3. **Reconnection policy** — как восстанавливать соединения.

**Load balancing (верифицировано по документации Java Driver 4.17):**

- **`DefaultLoadBalancingPolicy`** (дефолт) — token-aware + DC-aware + механизм избегания медленных реплик. Требует явно заданный `local-datacenter` (программно или в конфиге). Подключается **только к локальному DC** (REMOTE-узлам не подключается по умолчанию) — чтобы не генерировать cross-DC трафик.
- **`DcInferringLoadBalancingPolicy`** — как Default, но local DC выводится из contact points; для ETL-инструментов, не для приложений.
- **`BasicLoadBalancingPolicy`** — без slow-replica avoidance; единственная политика, работающая без local DC (datacenter-agnostic) — риск всплесков cross-DC трафика; точка опоры для кастомных политик.

**Token-aware routing:** запрос направляется в первую очередь на реплику, владеющую данными. Routing key вычисляется:
- **BoundStatement** (prepared statement) — автоматически, если связаны **все** компоненты partition key; если часть компонентов захардкожена в тексте запроса — routing key не вычисляется (только keyspace);
- **SimpleStatement** — **никогда** автоматически: routing keyspace и routing key нужно задавать вручную (`setRoutingKeyspace`, `setRoutingKey`);
- **Batch** — из дочерних statements (первый непустой routing key).

**Cross-DC failover (драйвер 4.10+):** по умолчанию выключен. Включается опцией `dc-failover.max-nodes-per-remote-dc` (дефолт `0`): указанное число узлов каждого remote DC получает distance REMOTE и попадает в query plan после локальных. Вторая опция — `allow-for-local-consistency-levels` (дефолт `false`): LOCAL_* уровни при failover могут приобрести другую семантику (QUORUM в DC с RF=3 — это 2 реплики, в DC с RF=1 — 1), поэтому по умолчанию failover для LOCAL_* уровней запрещён. Рекомендуемая альтернатива — failover на уровне инфраструктуры (load balancer) или приложения.

**Retry policy (верифицировано по документации):**

- **`DefaultRetryPolicy`** (дефолт) — максимум **один** повтор, только для идемпотентных запросов, только когда вероятность успеха высока:
  - `onUnavailable` → повтор на **следующем** узле query plan (первый координатор мог быть изолирован от кластера, но жить для клиента);
  - `onReadTimeout` → повтор на **том же** узле, только если достаточно реплик ответило, но данных среди них не было (координатор выбрал мёртвую реплику, к моменту таймаута она уже помечена down);
  - `onWriteTimeout` → повтор только для `BATCH_LOG` (координатор писал batchlog в подмножество узлов локального DC);
  - `onRequestAborted` / `onErrorResponse` → повтор на следующем узле при закрытии соединения (ClosedConnectionException, HeartbeatException); остальные ошибки — rethrow.
- **Hard-coded правила (вне RetryPolicy):** ошибка **до** записи в сеть (пул насыщен, узел упал после заимствования коннекшна) → прозрачный переход на следующий узел; необходимость re-prepare statement → повтор на том же узле; узел в состоянии bootstrap → следующий узел.
- **Всегда rethrow (без повторов):** `QueryValidationException` и подклассы, `FunctionFailureException`, `ProtocolError`.
- **`ConsistencyDowngradingRetryPolicy`** — понижает consistency level при невозможности достичь запрошенного. **Опасен:** запись с downgraded до ONE может остаться невидимой для последующего чтения на QUORUM; может нарушить locality (LOCAL_QUORUM → ONE уйдёт в другой DC). Только когда приложение осознанно терпит деградацию гарантий.

**Idempotence — gate для ретраев.** Retry policy вызывается **только для идемпотентных statements**. Неидемпотентный запрос (например, `INSERT` без условия, counter-инкремент) при таймауте **не ретраится** — драйвер сразу rethrow, чтобы не создать дубликат. Идемпотентные запросы (точечные чтения, upsert с фиксированным timestamp, `INSERT ... IF NOT EXISTS`) нужно помечать явно (`setIdempotent(true)`), чтобы ретраи работали.

**Reconnection:** `ExponentialReconnectionPolicy` (дефолт: `base-delay = 1s`, `max-delay = 60s` — экспоненциальный backoff) или `ConstantReconnectionPolicy`. Применяется к пулам соединений и control connection. `advanced.reconnect-on-init = false` (дефолт): при неудаче первого подключения session бросает ошибку сразу; `true` — retry до появления contact point (полезно для контейнеров, но `build()` блокируется до готовности).

**Конфигурация (Typesafe Config / HOCON):** драйвер читает `reference.conf` (дефолты, внутри JAR) → `application.conf` (classpath) → system properties. Hot reload: конфиг перечитывается каждые `basic.config-reload-interval = 5 минут` (изменяемые опции применяются на лету; protocol version и политики — нет). System properties (`-Ddatastax-java-driver...`) — только для dev/временных правок.

**Версии драйверов:** Java driver 4.x — для Cassandra 3.11/4.0/5.0 и ScyllaDB; ScyllaDB ведёт форк в группе Maven `com.scylladb` (версия 4.19.x). С 4.18 драйвер поддерживается Apache Software Foundation (`org.apache.cassandra:java-driver-core`). Python: `cassandra-driver` 3.30.x (явные классы политик). Go: `gocql` 2.1.x (Apache-форк, `github.com/apache/cassandra-gocql-driver/v2`) и `scylla-go-driver` (альфа, shard-aware routing). Матрицу совместимости driver ↔ сервер проверяйте в документации драйвера.

## Предварительные требования

**Сеть:**
- Порт 9042/tcp (native transport) открыт на всех узлах кластера и доступен с хоста приложения.
- Clock skew между клиентским хостом и узлами кластера < 5 секунд (сервер отклоняет запрос при рассинхроне).
- MTU >= 1500; для cross-DC — учтите задержки и потери пакетов.

**Java:**
- Apache Java Driver 4.19.x — JDK 8 или выше (рекомендуется JDK 11+).
- ScyllaDB Java Driver 4.19.x (`com.scylladb:java-driver-core`) — JDK 11 или выше.

**Python:**
- `cassandra-driver` 3.30.x — CPython 3.7+.

**Go:**
- `gocql` 2.1.x — Go 1.13+.
- `scylla-go-driver` (альфа) — Go 1.18+.

**ScyllaDB (дополнительно):**
- Для shard-aware routing в Go требуется сборка `scylla-go-driver` из исходников или использование форка gocql от ScyllaDB.
- Таблеты (tablets) поддерживаются драйверами начиная с: Java 4.18.0, Go 1.13.0, Python 3.26.5.

## Установка и настройка

**Java (Apache / ScyllaDB fork):**

```xml
<!-- Apache Java Driver -->
<dependency>
  <groupId>org.apache.cassandra</groupId>
  <artifactId>java-driver-core</artifactId>
  <version>4.19.3</version>
</dependency>

<!-- ScyllaDB Java Driver (fork) -->
<dependency>
  <groupId>com.scylladb</groupId>
  <artifactId>java-driver-core</artifactId>
  <version>4.19.2.0</version>
</dependency>
```

```bash
# JVM-опции для драйвера (если нужны)
_JAVA_OPTIONS="-Ddatastax-java-driver.basic.load-balancing-policy.local-datacenter=dc1"
```

**Python:**

```bash
pip install cassandra-driver==3.30.1
```

```python
from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy, TokenAwarePolicy

cluster = Cluster(
    contact_points=["10.0.1.1", "10.0.1.2"],
    load_balancing_policy=TokenAwarePolicy(
        DCAwareRoundRobinPolicy(local_dc="dc1")
    ),
    connect_timeout=5,
)
```

**Go (gocql):**

```bash
go get github.com/apache/cassandra-gocql-driver/v2
```

```go
import (
    "github.com/apache/cassandra-gocql-driver/v2"
)
```

**ScyllaDB Go Driver (альфа):**

```bash
go get github.com/scylladb/scylla-go-driver
```

## Валидация подключения

### Проверка на стороне драйвера (Java)

```java
// Минимальный smoke-test: открыть session и выполнить запрос
try (CqlSession session = CqlSession.builder()
    .addContactPoint(new InetSocketAddress("10.0.1.1", 9042))
    .withLocalDatacenter("dc1")
    .withKeyspace("system")
    .build()) {
    ResultSet rs = session.execute("SELECT release_version FROM local");
    Row row = rs.one();
    System.out.println("Cassandra version: " + row.getString("release_version"));
}
# → Cassandra version: 5.0.9
```

### Проверка метрик пула

```hocon
datastax-java-driver.advanced.metrics.node.enabled = [
  "pool.open-connections",
  "pool.available-streams",
  "pool.in-flight",
  "pool.orphaned-streams",
  "pool.connection-errors"
]
```

После запуска приложения проверьте:
- `pool.open-connections` >= `pool.local.size` (дефолт 1) — соединения открыты.
- `pool.available-streams` не стабильно около 0 — иначе пул насыщен.
- `pool.orphaned-streams` = 0 — иначе есть проблемы с сетью/таймаутами.

### Проверка token-aware routing

```bash
# Включите CQL tracing на сервере (одноразово)
CONSISTENCY QUORUM;
TRACING ON;
SELECT * FROM my_app.user_events WHERE user_id = uuid() AND event_time = uuid();
TRACING OFF;
# В выводе tracing убедитесь, что coordinator совпадает с репликой-владельцем token
```

Если coordinator != реплика-владелец — проверьте, что все компоненты partition key передаются через bind-маркеры (prepared statement), а не хардкодятся в тексте запроса.

## Эксплуатация и команды

### Обновление метаданных схемы без перезапуска

```java
// Применение новой схемы (driver переподключится автоматически при изменении schema)
session.execute("ALTER TABLE my_app.user_events ADD last_seen timestamp");
```

Драйвер слушает CQL Events и обновляет `CqlSession` метаданные. Control connection восстанавливается автоматически при сбое.

### Сброс пулов соединений (Java 4.10+)

```java
// Полезно при масштабировании кластера или изменении snitch
session.getMetrics().getConnectionTracker().drain();
// Или полная переинициализация session при изменении конфигурации
```

### Ожидание готовности кластера (init)

```java
CqlSession session = CqlSession.builder()
    .addContactPoint(new InetSocketAddress("10.0.1.1", 9042))
    .withLocalDatacenter("dc1")
    .withConfigLoader(DriverConfigLoader.fromFile(Paths.get("/etc/myapp/application.conf")))
    .build();
```

При `advanced.reconnect-on-init = true` драйвер будет ждать доступности contact points (полезно для контейнеров/оркестраторов). По умолчанию `false` — при неудаче первого подключения `build()` бросает ошибку сразу.

### Мониторинг через JMX (опционально)

```bash
# Проверка MBean драйвера (если application использует JMX)
jconsole <pid> | org.apache.cassandra.driver
```

## Особенности и крайние случаи

**Clock skew > 5 секунд:**
Сервер отклоняет запрос с `ServerError: Clock skew too important`. NTP-синхронизация обязательна на всех хостах (клиентских и серверных). Для Docker-контейнеров — `--cap-add SYS_TIME` не рекомендуется; используйте внешний NTP-сервер или host-network.

**Schema disagreement:**
Если драйвер видит `SchemaAgreementException` после ALTER TABLE — подождите распространения schema через gossip (обычно < 1 секунды). При частых `SchemaAgreementException` проверяйте `schema_agreement_wait_timeout` (дефолт 10 с) или увеличивайте запас.

**Большие result set (пагинация):**
По умолчанию driver выбирает `fetchSize` автоматически. Для полных table scan задавайте `setFetchSize(5000)`; без пагинации координатор может выгрузиться в OOM.

**Driver warmup:**
Первый запрос после старта приложения медленнее: драйвер подготавливает schema, открывает соединения, вычисляет token map. Для production-grade latency используйте readiness probe (подождите `pool.open-connections == pool.local.size`).

**Cross-DC трафик при LOCAL_* уровнях:**
Если включён `dc-failover` с `allow-for-local-consistency-levels = true`, запрос `LOCAL_QUORUM` при падении локального DC может уйти в remote DC и вернуть устаревшие данные. Это ожидаемое поведение при деградации, но для strict locality выключите `allow-for-local-consistency-levels`.

**Идемпотентность и batch:**
`BATCH` считается неидемпотентным по умолчанию. Если batch содержит только идемпотентные операции (например, upsert с условием), пометьте весь batch:
```java
BatchStatement batch = BatchStatement.builder(DefaultBatchType.LOGGED)
    .addStatement(insert1)
    .addStatement(insert2)
    .setIdempotent(true)
    .build();
```

## Практические сценарии

### application.conf (Java driver)

```hocon
datastax-java-driver {
  basic.contact-points = [ "10.0.1.1:9042", "10.0.1.2:9042" ]
  basic.load-balancing-policy {
    class = DefaultLoadBalancingPolicy
    local-datacenter = dc1          # ОБЯЗАТЕЛЬНО для Default/DcInferring
  }
  basic.request {
    timeout = 12 seconds            # дефолт; должен быть > серверных таймаутов
    consistency = LOCAL_QUORUM
  }
  advanced.connection {
    max-requests-per-connection = 1024   # дефолт; не повышать без измерений
    pool {
      local.size = 1                # дефолт; ~80K req/s/connection — потолок одного коннекшна
      remote.size = 1
    }
  }
  advanced.heartbeat {
    interval = 30 seconds           # дефолт
    timeout = 500 milliseconds
  }
  advanced.reconnection-policy {
    class = ExponentialReconnectionPolicy
    base-delay = 1 second
    max-delay = 60 seconds
  }
  advanced.retry-policy.class = DefaultRetryPolicy
  profiles {
    oltp {
      basic.request.timeout = 100 milliseconds
      basic.request.consistency = LOCAL_ONE
    }
    olap {
      basic.request.timeout = 5 seconds
      basic.request.consistency = QUORUM
    }
  }
}
```

### Java: session и prepared statement

```java
CqlSession session = CqlSession.builder()
    .addContactPoint(new InetSocketAddress("10.0.1.1", 9042))
    .withLocalDatacenter("dc1")               // обязательно
    .withKeyspace("my_app")
    .build();

// Prepared statement: routing key вычисляется автоматически,
// если связаны ВСЕ компоненты partition key
PreparedStatement ps = session.prepare(
    "SELECT * FROM my_app.user_events WHERE user_id = :uid AND event_time = :et");
BoundStatement bs = ps.bind()
    .set("uid", userId, UUID.class)
    .set("et", eventTime, UUID.class)
    .setIdempotent(true);                     // разрешить retry policy ретраить
session.execute(bs);

// Execution profile для другого SLA
SimpleStatement s = SimpleStatement.builder("SELECT name FROM my_app.users WHERE id = 1")
    .setExecutionProfileName("oltp")
    .build();
```

**SimpleStatement без routing info:** токенизация не работает — запрос пойдёт на случайный узел локального DC. Для административных разовых запросов это нормально; для горячего пути — всегда prepared statement с bind-маркерами всех компонентов PK.

### Python (cassandra-driver 3.x API)

```python
from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy, TokenAwarePolicy

cluster = Cluster(
    contact_points=["10.0.1.1", "10.0.1.2"],
    load_balancing_policy=TokenAwarePolicy(
        DCAwareRoundRobinPolicy(local_dc="dc1")
    ),
    connect_timeout=5,
)
session = cluster.connect("my_app")
# default_consistency_level, retry policy и пул задаются на Cluster/Session
```

Python-драйвер 3.x использует явные вложенные политики (TokenAwarePolicy оборачивает DCAwareRoundRobinPolicy) — другая модель, чем `DefaultLoadBalancingPolicy` в Java driver 4+.

### Мониторинг пула (метрики драйвера)

```hocon
datastax-java-driver.advanced.metrics.node.enabled = [
  "pool.open-connections",      # число открытых коннекшнов к узлу
  "pool.available-streams",     # свободные stream id; ≈ 0 — пул насыщен
  "pool.in-flight",             # запросы в полёте
  "pool.orphaned-streams"       # «осиротевшие» stream id
]
```

Метрики по умолчанию **выключены** — включите явно. `pool.available-streams` часто около 0 — сигнал насыщения: добавьте соединений (`pool.local.size`) или снизьте concurrency.

## Поиск и устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `NoHostAvailableException` | Ни один узел недоступен: contact points, firewall 9042, DC в LBP не совпадает с DC узлов, пул исчерпан (`BusyPoolException` как inner) | `nodetool status`; проверить `local-datacenter`; `ss -lntp \| grep 9042`; увеличить connections (см. [Troubleshooting](./troubleshooting.md)) |
| `DriverTimeoutException` | Координатор не ответил в течение `basic.request.timeout` (клиентский таймаут) | Отличать от серверного `ReadTimeoutException`; проверить latency координатора, GC, пулы; таймаут драйвера должен быть **больше** серверных (`read_request_timeout` 5s + запас) |
| `ReadTimeoutException` / `WriteTimeoutException` | Серверный таймаут: координатор не дождался реплик | Диагностика сервера — [Troubleshooting](./troubleshooting.md); запись при WriteTimeout **не потеряна** (hint); повтор безопасен только для идемпотентных запросов |
| Ретраи не работают | Запрос не помечен идемпотентным | `setIdempotent(true)` для безопасных запросов; counter-обновления и неусловные INSERT не ретраятся по дизайну |
| `pool.available-streams` ≈ 0 | Пул насыщен: concurrency выше, чем `max-requests-per-connection × connections` | Поднять `pool.local.size` (hot-reload), снизить concurrency клиента; ~80K req/s/connection — потолок одного коннекшна |
| Heartbeat failures в логах | Сетевое оборудование дропает idle-соединения | Heartbeat включён по умолчанию (30s); проверить firewall/ NAT timeouts; при необходимости поднять `heartbeat.interval` |
| Cross-DC трафик при LOCAL_* запросах | `dc-failover` включён с `allow-for-local-consistency-levels = true`, или LBP без local-datacenter | Выключить dc-failover для LOCAL_* уровней; всегда задавать `local-datacenter` |
| Конфиг не применяется | Опция не поддерживает hot reload (protocol version, политики) | Перезапуск приложения; проверить иерархию: system properties > application.conf > reference.conf |
| Дубликаты записей после таймаута | Ретраю неидемпотентный INSERT на уровне приложения | Идемпотентность на стороне приложения (условная вставка, фиксированный timestamp) или `IF NOT EXISTS` (LWT — дорого) |

## Рекомендации

- **Всегда задавать `local-datacenter`** для `DefaultLoadBalancingPolicy` — иначе session не инициализируется; приложение должно быть collocated с одним DC.
- **Prepared statements с bind-маркерами** — routing key вычисляется автоматически, запрос идёт на реплику-владельца; рост `prepared_statements_cache` на сервере (метрика `scylla_cql_prepared_cache_evictions`) — признак, что клиент готовит запрос на каждый вызов.
- **Не трогайте pooling defaults без измерений**: `max-requests-per-connection = 1024`, `pool.local.size = 1` — документированные дефолты; повышение `max-requests-per-connection` выше 1024 не даёт выигрыша (сервер всё равно обслуживает ограниченное число запросов).
- **Таймауты:** `basic.request.timeout` (12s дефолт) > серверных таймаутов (read 5s / write 2s) + запас на сеть; для OLTP — execution profile с коротким таймаутом.
- **Idempotence:** помечайте безопасные запросы — иначе retry policy молча не работает.
- **Execution profiles** вместо правки опций на каждом запросе; derived profiles кэшируйте (каждый `withXxx` создаёт копию).
- **Не используйте `ConsistencyDowngradingRetryPolicy`** без осознанного решения о деградации гарантий.
- **Мониторьте метрики пула** (`pool.available-streams`, `pool.open-connections`) — они выключены по умолчанию.
- **Конфиг в одном месте:** production-конфигурация — `application.conf` в classpath, не system properties.

## См. также

- **[Поиск и устранение неисправностей](./troubleshooting.md)** — серверные исключения (NoHostAvailable, Unavailable, Timeouts).
- **[Тюнинг производительности](./performance.md)** — серверные таймауты и пулы потоков.
- **[Мониторинг и observability](./monitoring.md)** — метрики prepared-statements cache и CQL-нагрузки.
- **[Развёртывание в Kubernetes](./kubernetes.md)** — discovery Service как contact point для драйвера.
- **[Мulti-DC и аварийное восстановление](./multi-dc-dr.md)** — LOCAL_* уровни и cross-DC failover.
- Официальная документация: [Java Driver manual](https://docs.datastax.com/en/developer/java-driver/latest/manual/core/), [Apache Java Driver](https://apache.github.io/cassandra-java-driver/), [ScyllaDB CQL drivers](https://docs.scylladb.com/stable/drivers/cql-drivers.html).
