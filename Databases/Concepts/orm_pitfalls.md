**Актуально для:** Hibernate 6.6 / 7.x, SQLAlchemy 2.0 / 2.1, Django 5.2 LTS / 6.x, HikariCP 6.x / 7.x (2024–2026)

# ORM-подводные камни: N+1, загрузка и управление соединениями

## Определения

**ORM (Object-Relational Mapping)** — технология, отображающая таблицы БД на объекты языка программирования и генерирующая SQL из кода приложения (Hibernate, SQLAlchemy, Django ORM, Entity Framework, ActiveRecord).

**Проблема N+1** — антипаттерн доступа к данным, при котором на получение списка из N связанных объектов выполняется 1 запрос на список + N запросов на каждый элемент (вместо одного `JOIN`). Главный источник деградации производительности в ORM-приложениях.

**Lazy loading (ленивая загрузка)** — связанные данные загружаются из БД только при первом обращении к свойству объекта. По умолчанию во многих ORM — основная причина N+1.

**Eager loading (жадная загрузка)** — связанные данные загружаются сразу, в том же запросе (`JOIN` или отдельный `IN`-запрос).

**Identity Map** — кэш ORM внутри сессии: повторное чтение одной и той же строки в рамках сессии возвращает тот же объект без обращения к БД.

**Unit of Work / Dirty Checking** — ORM отслеживает изменения объектов сессии и при коммите транзакции генерирует только необходимые `UPDATE` (сравнение текущего состояния с загруженным).

**Session (сессия)** — единица работы ORM: короткоживущий контекст, связанный с одной транзакцией БД. Владеет identity map и очередью изменений.

**Connection Pool** — пул соединений к БД (HikariCP, pgBouncer, ProxySQL). Размер пула — отдельная настройка от ORM-сессий; см. **[Connection Pooling](../../Networking/Concepts/connection_pooling.md)**.

**Предварительные требования:** работающее ORM-приложение; доступ к БД с правом просмотра `pg_stat_activity` (PostgreSQL) / `SHOW PROCESSLIST` (MySQL/MariaDB); доступ к конфигурации пула соединений приложения.

## Основные концепции

### Как возникает N+1

```python
# SQLAlchemy 2.x: lazy loading по умолчанию
posts = session.execute(select(Post)).scalars().all()   # 1 запрос: SELECT * FROM posts
for post in posts:
    print(post.author.name)                               # N запросов: SELECT * FROM users WHERE id = ?
```

Итого: 1 + N запросов. При 1000 постов — 1001 обращение к БД, round-trip latency доминирует над временем самих запросов.

**Дефолтные стратегии загрузки (JPA / Jakarta Persistence):** `@ManyToOne` и `@OneToOne` по умолчанию `EAGER`, `@OneToMany` и `@ManyToMany` — `LAZY`. Стратегию `EAGER` нельзя переопределить на уровне запроса: если забыть `JOIN FETCH` для EAGER-ассоциации, Hibernate догрузит её отдельным secondary select для каждой сущности — скрытый N+1. Спецификация («very strongly recommended» для новых приложений): явно указывать `fetch = LAZY` на to-one ассоциациях.

**Почему это плохо:**
- Latency: N × RTT вместо 1 × RTT.
- Нагрузка: N простых запросов по PK дешевле одного JOIN, но при большом N суммарная нагрузка выше, а пул соединений может исчерпаться.
- Скрытость: в коде нет явных запросов — проблема проявляется только в логах/метриках.

### Способы устранения N+1

| Способ | Механизм | Когда применять |
| :--- | :--- | :--- |
| **JOIN FETCH / eager load** | Один запрос с `JOIN` | Связь 1:N небольшая, нужен фильтр/сортировка по связанной таблице |
| **Batch / `IN`-загрузка** | 1 запрос на список + 1 запрос `WHERE id IN (...)` | Связей много, `JOIN` раздувает строки (cardinality explosion) |
| **Subselect loading** | Один подзапрос для всех связей (перезапуск исходного запроса) | Hibernate: коллекции при `@Fetch(FetchMode.SUBSELECT)` |
| **DTO-проекция** | `SELECT` только нужных колонок | Отчёты, API-ответы; не загружать целые сущности |
| **Native SQL** | Ручной запрос | Сложная аналитика, оконные функции (**[Продвинутый SQL](./advanced_sql.md)**) |

**Cardinality explosion:** `JOIN` при `1:N` с коллекцией дублирует строки родителя (пост × комментариев). Для коллекций предпочтительна batch-загрузка (`IN`), а не `JOIN`.

**Ограничения JOIN FETCH (Hibernate 6.x):**
- **`MultipleBagFetchException`:** в одном запросе нельзя `JOIN FETCH` две и более коллекции типа `List` (bag) — `org.hibernate.loader.MultipleBagFetchException: cannot simultaneously fetch multiple bags` (при декартовом произведении нельзя определить, какие дубликаты — настоящие элементы коллекции). Решения: `Set` вместо `List` (исключение уйдёт, но декартово произведение останется), `@OrderColumn`, или отдельный запрос на каждую коллекцию — identity map сольёт результаты в те же объекты.
- **Пагинация + `JOIN FETCH` коллекции:** `setFirstResult`/`setMaxResults` (Spring `Pageable`) применяются не в SQL, а в памяти — WARN `HHH000104` (5.x) / `HHH90003004` (6.x): «firstResult/maxResults specified with collection fetch; applying in memory!». В RAM загружается вся таблица — риск OOM на больших таблицах. Решение: two-query pattern (пагинированный запрос по ID, затем batch/`IN`-загрузка коллекций) или `@BatchSize`.

### Управление сессиями и транзакциями

**Правило «session-per-request»:** одна сессия = один HTTP-запрос = одна транзакция. Сессия открывается в начале запроса, коммитится/откатывается в конце, закрывается.

**Типичные ошибки:**
- **Долгоживущая сессия** (session-per-application): identity map растёт, dirty checking становится O(N), блокировки удерживаются долго.
- **Открытая сессия в представлении (Open Session in View):** lazy loading продолжается во время рендеринга — скрытые N+1 и длинные транзакции.
- **Смешение read-only и write в одной транзакции:** read-only запросы удлиняют write-транзакцию.

### Размер пула соединений

ORM-сессии ≠ соединения БД. Пул соединений — отдельный ресурс:

- **HikariCP (Java):** `maximumPoolSize` по умолчанию **10**, `minimumIdle` по умолчанию равен `maximumPoolSize`.
- **Формула throughput** (от проекта PostgreSQL, цитируется в [wiki HikariCP](https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing)): `connections = (core_count × 2) + effective_spindle_count`. `core_count` — без HT-потоков; `effective_spindle_count` = 0, если активный набор целиком в кеше, и стремится к числу spindle при падении hit rate; для SSD формула не анализировалась.
- **Формула защиты от дедлока** (wiki HikariCP): `pool_size = Tn × (Cm − 1) + 1`, где `Tn` — макс. потоков, `Cm` — макс. одновременных соединений на поток.
- **PostgreSQL:** каждое соединение — отдельный процесс (~5–10 МБ). 1000 соединений — это уже проблема; для web-приложений пул 10–50 типичен, дальше — **pgBouncer** в режиме transaction pooling (**[pgBouncer](../PostgreSQL/Operations/pgbouncer_setup.md)**).

**Взаимодействие с ProxySQL:** ORM-приложения часто выполняют `SET`-инструкции при выдаче соединения из пула (например, `SET time_zone`, `SET sql_mode`). ProxySQL воспринимает это как признак «пиннинга» и перестаёт переиспользовать соединение — см. **[ProxySQL connection pool](../MariaDB/proxysql.md)**.

## Практические сценарии

### Сценарий 1: Обнаружение N+1

**PostgreSQL — включить лог медленных запросов:**
```sql
ALTER SYSTEM SET log_min_duration_statement = 100;  -- лог запросов > 100 мс
SELECT pg_reload_conf();
-- В логе: повторяющиеся SELECT ... WHERE user_id = $1 с разными параметрами → N+1
```

**Django — django-debug-toolbar или `connection.queries`:**
```python
from django.db import connection
# после запроса (connection.queries заполняется только при DEBUG=True):
len(connection.queries)  # → количество SQL-запросов; рост линейно с числом объектов = N+1
```

**Hibernate — статистика:**
```properties
# application.properties
spring.jpa.properties.hibernate.generate_statistics=true
# + уровень org.hibernate.stat=DEBUG: сводка по сессии — число JDBC-стейтментов,
#   фетчей сущностей и коллекций, флашей. В тестах — Statistics API:
#   sessionFactory.getStatistics().getQueryExecutionCount() /
#   .getEntityFetchCount() / .getPrepareStatementCount();
#   entityFetchCount > 0 при загрузке списка = N+1
# Медленные запросы (6.2+): hibernate.log_slow_query=100 (мс);
# в 5.4.5–6.1 свойство называлось hibernate.session.events.log.LOG_QUERIES_SLOWER_THAN_MS
```

**SQLAlchemy — echo:**
```python
engine = create_engine("postgresql://...", echo=True)  # все SQL в stdout
```

### Сценарий 2: Исправление N+1

**Hibernate — `JOIN FETCH`:**
```java
@Query("SELECT p FROM Post p JOIN FETCH p.author WHERE p.status = :status")
List<Post> findWithAuthor(@Param("status") String status);
// → 1 запрос с JOIN вместо 1 + N
```

**Hibernate — batch size для коллекций:**
```java
@OneToMany(mappedBy = "post")
@BatchSize(size = 50)   // загрузка коллекций порциями по 50: 1 + ceil(N/50) запросов
private List<Comment> comments;
```

```properties
# Глобальный batch fetch для всех коллекций (аналог @BatchSize для всего приложения)
spring.jpa.properties.hibernate.default_batch_fetch_size=50
# JDBC-батчинг INSERT/UPDATE при flush: работает только с ID-генератором,
# не требующим SELECT следующего значения (SEQUENCE/TABLE; с IDENTITY — не работает,
# см. [Генерация идентификаторов](./id_generation.md))
spring.jpa.properties.hibernate.jdbc.batch_size=30
spring.jpa.properties.hibernate.order_inserts=true
spring.jpa.properties.hibernate.order_updates=true
# MySQL/MariaDB: Connector/J переписывает executeBatch() в multi-values INSERT
# (default false — док-во Connector/J, Performance Extensions)
spring.datasource.url=jdbc:mysql://db:3306/app?rewriteBatchedStatements=true
```

**SQLAlchemy — `selectinload`:**
```python
posts = session.execute(
    select(Post).options(selectinload(Post.comments))
).scalars().all()
# → 1 запрос на posts + 1 запрос WHERE post_id IN (...)
```

**Django — `select_related` (FK, 1:1) и `prefetch_related` (M2M, reverse FK):**
```python
posts = Post.objects.select_related("author").prefetch_related("comments").all()
# → 2 запроса вместо 1 + N
```

### Сценарий 3: DTO-проекция вместо целых сущностей

```sql
-- ORM генерирует SELECT * — загружает все колонки, включая большие (jsonb, bytea)
-- Проекция: только нужное
SELECT id, title, created_at FROM posts WHERE user_id = :uid ORDER BY created_at DESC LIMIT 20;
```

```python
# SQLAlchemy 2.x: только колонки
rows = session.execute(select(Post.id, Post.title, Post.created_at).where(...)).all()
```

### Сценарий 4: Настройка пула соединений

```yaml
# Spring Boot / HikariCP
spring.datasource.hikari:
  maximumPoolSize: 20        # по умолчанию 10; формула: (cores × 2) + spindles
  minimumIdle: 20            # по умолчанию = maximumPoolSize
  connectionTimeout: 30000   # мс ожидания свободного соединения
  maxLifetime: 1800000       # 30 мин; должен быть меньше wait_timeout БД
  leakDetectionThreshold: 60000  # логировать соединения, не возвращённые в пул > 60 с
```

```ini
# SQLAlchemy / psycopg2
engine = create_engine(
    "postgresql+psycopg2://...",
    pool_size=20,              # постоянных соединений
    max_overflow=10,           # дополнительных сверх pool_size
    pool_timeout=30,           # секунд ожидания
    pool_recycle=1800,         # пересоздавать соединения старше 30 мин (обход idle-таймаутов)
)
```

## Операции и команды

### Мониторинг пула и сессий

```sql
-- PostgreSQL: активные соединения по состоянию
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;
-- → active | idle | idle in transaction | idle in transaction (aborted)

-- Долгие «idle in transaction» — незакоммиченные ORM-транзакции (утечка сессии)
SELECT pid, now() - xact_start AS xact_age, query
FROM pg_stat_activity WHERE state = 'idle in transaction' ORDER BY xact_age DESC;
```

```sql
-- MySQL/MariaDB: утечки соединений
SHOW PROCESSLIST;
-- → много Sleep-соединений от одного хоста = пул больше, чем нужно, или утечки
SHOW STATUS LIKE 'Threads_connected';
```

### Проверка сгенерированного SQL

```bash
# Hibernate: лог SQL с параметрами
# logging.level.org.hibernate.SQL=DEBUG
# logging.level.org.hibernate.orm.jdbc.bind=TRACE

# Django: запросы в консоли при DEBUG=True (только dev!)
# SQLAlchemy: echo=True
```

## Поиск и устранение неисправностей

### Проблема: `LazyInitializationException` (Hibernate) / `DetachedInstanceError`

**Симптомы:** обращение к lazy-свойству вне транзакции выбрасывает исключение.

**Причина:** сессия закрыта до обращения к связанным данным (типичный случай — сериализация сущности в JSON после закрытия сессии).

**Решение:**
1. `JOIN FETCH` / `select_related` — загрузить данные внутри транзакции.
2. DTO-проекция — не возвращать сущности за пределы транзакции.
3. Не использовать Open Session in View как постоянное решение (скрывает N+1).

### Проблема: исчерпание пула соединений

**Симптомы:** `Connection is not available, request timed out` (HikariCP), `too many connections` (MySQL), `FATAL: sorry, too many clients` (PostgreSQL).

**Причины:**
1. Утечки: сессии/соединения не возвращаются в пул (отсутствие `close()`/`try-with-resources`).
2. Пул больше, чем `max_connections` БД: сумма пулов всех сервисов > лимита БД.
3. Долгие транзакции удерживают соединения.

**Решение:**
1. `leakDetectionThreshold` (HikariCP) / `pool_recycle` + логирование — найти утечку.
2. Бюджет соединений: `сумма(maxPoolSize по сервисам) < max_connections − резерв`.
3. pgBouncer в transaction mode для PostgreSQL — разрывает связь «сессия приложения = соединение БД».

### Проблема: dirty checking тормозит коммит

**Симптомы:** коммит транзакции занимает секунды при тысячах объектов в сессии; CPU в приложении высокий.

**Причина:** identity map сессии разросся; ORM сравнивает все поля всех объектов при flush.

**Решение:**
1. Короткие сессии (session-per-request), `session.clear()` после пакетной обработки.
2. Для массовых операций — DML-запросы (`UPDATE ... WHERE`), а не загрузка объектов.
3. `@DynamicUpdate` (Hibernate) — `UPDATE` только изменённых колонок.

### Проблема: ORM «съедает» производительность на простых CRUD

**Симптомы:** простой `SELECT` по PK занимает 5–10 мс вместо 0.2 мс.

**Причина:** избыточная загрузка колонок, лишние раунд-трипы (version check при optimistic locking), логирование SQL в production.

**Решение:** проекции, `readOnly`-транзакции для чтения, отключение SQL-логов в production.

## Лучшие практики

1. **Запрещайте lazy loading в API-слое:** все данные для ответа загружаются явно (`JOIN FETCH`/`select_related`/`prefetch_related`).
2. **Логируйте SQL в staging, не в production:** N+1 ловят на нагрузочных тестах (**[Нагрузочное тестирование](../../Testing/performance_testing_methodology.md)**) и по метрикам latency.
3. **DTO вместо сущностей за пределами транзакции.**
4. **Бюджет соединений:** считайте `сумма пулов < max_connections`; для PostgreSQL — pgBouncer.
5. **`maxLifetime` пула < `wait_timeout`/`idle_in_transaction_session_timeout` БД** (MySQL `wait_timeout` по умолчанию `28800` с = 8 часов) — иначе БД закроет соединение раньше пула и пул вернёт «мёртвое» соединение.
6. **Массовые операции — DML, не объекты:** `UPDATE ... WHERE` вместо загрузки тысяч сущностей.
7. **Оптимистичная блокировка (`@Version`)** вместо пессимистичной, где возможно (**[Блокировки](../PostgreSQL/Concepts/concurrency_and_locking.md)**).
8. **ORM не заменяет знание SQL:** тяжёлые аналитические запросы — нативный SQL или **[оконные функции](./advanced_sql.md)**.

## Дополнительная информация

### Смежные темы
- **[Connection Pooling](../../Networking/Concepts/connection_pooling.md)** — пулы соединений: режимы, sizing.
- **[pgBouncer: установка и настройка](../PostgreSQL/Operations/pgbouncer_setup.md)** — transaction pooling для PostgreSQL.
- **[pgBouncer: эксплуатация](../PostgreSQL/Operations/pgbouncer_operations.md)** — мониторинг, пулы, ошибки.
- **[ProxySQL](../MariaDB/proxysql.md)** — пулинг и пиннинг соединений MySQL/MariaDB.
- **[Продвинутый SQL](./advanced_sql.md)** — оконные функции и рекурсивные CTE, когда ORM не справляется.
- **[Генерация идентификаторов](./id_generation.md)** — стратегии PK и их влияние на ORM (identity vs sequence).
- **[Блокировки и дедлоки](../PostgreSQL/Concepts/concurrency_and_locking.md)** — изоляция транзакций.
- **[Нагрузочное тестирование](../../Testing/performance_testing_methodology.md)** — выявление N+1 под нагрузкой.
- **[HikariCP: About Pool Sizing](https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing)** — формулы sizing пула (источник формул выше).
- **[MySQL Connector/J: `rewriteBatchedStatements`](https://dev.mysql.com/doc/connector-j/en/connector-j-connp-props-performance-extensions.html)** — батчинг INSERT в multi-values (default `false`).
