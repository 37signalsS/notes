# Сравнение SQL, NoSQL и NewSQL

**Актуально для:** PostgreSQL 16–18 / MySQL 8.0 / MariaDB 11 / MongoDB 8.0 / Cassandra 5.x / ScyllaDB 2026.x / Redis 7.2 / CockroachDB 23.x / Neo4j 5.x (2024–2026)

## Предварительные требования (Prerequisites)

- Понимание моделей изоляции транзакций и разницы между ACID и BASE: см. **[ACID: Свойства транзакций](./acid.md)**.
- Базовое представление о CAP-теореме и PACELC: см. **[CAP-теорема и PACELC](./cap_theorem.md)**.
- Знание архитектуры хранения на диск и влияния B-Tree / LSM-Tree на I/O.
- Опыт эксплуатации СУБД в роли SRE/sysadmin: резервное копирование, мониторинг, настройка ОС и filesystem.

## Определения

- **SQL (Relational Databases)** — системы, основанные на реляционной модели данных и использующие язык запросов SQL. Данные хранятся в строго структурированных таблицах с заранее определенными связями.
  - **Примеры:** PostgreSQL, MySQL, MariaDB, MS SQL Server.
- **NoSQL (Non-relational Databases)** — "Not Only SQL". Системы, использующие гибкие модели данных (документы, графы, ключ-значение) для решения задач высокой доступности и горизонтального масштабирования.
  - **Примеры:** MongoDB (документы), Redis (кэш), Cassandra (колонки), Neo4j (графы).
- **NewSQL (Distributed SQL)** — современное поколение СУБД, которые сочетают в себе горизонтальную масштабируемость NoSQL и гарантии ACID традиционных SQL-систем.
  - **Примеры:** CockroachDB, YugabyteDB, TiDB.

## Принцип работы

### Архитектура хранения и I/O

Выбор семейства СУБД определяет базовую стратегию работы с диском и оперативной памятью:

1.  **B-Tree / B+ Tree (Традиционные SQL):**
    - Данные организованы в виде сбалансированного дерева страниц фиксированного размера.
    - **I/O профиль:** Оптимизированы для произвольного чтения (Point Queries) и поиска по диапазону. Каждое чтение требует предсказуемого количества переходов по страницам.
    - **Особенности:** In-place updates приводят к фрагментации и требуют механизмов блокировок, ограничивая параллелизм записи.
    - **Примеры:** PostgreSQL, MySQL (InnoDB), MariaDB.

2.  **LSM-Tree (Log-Structured Merge-Tree) (NoSQL: Cassandra, ScyllaDB, RocksDB):**
    - Данные сначала пишутся в оперативную память (MemTable) и в WAL. При заполнении MemTable сбрасывается на диск как неизменяемый SSTable.
    - **I/O профиль:** Исключительно последовательная запись (Sequential I/O), эффективная для SSD и NVMe.
    - **Write Amplification:** Фоновый Compaction перечитывает и переписывает SSTables, удаляя дубликаты и устаревшие данные.
    - **Чтение:** Может быть медленнее из-за проверки нескольких SSTables (фильтры Блума ускоряют поиск).

### Влияние на буферный пул и кэширование

- **SQL (B-Tree):** Индексы и часто используемые таблицы умещаются в buffer pool / InnoDB Buffer Pool. Cache hit ratio — ключевая метрика для SRE.
- **NoSQL (LSM-Tree):** MemTable находится в RAM, но при переполнении сбрасывается на диск. Bloom filters уменьшают количество ненужных чтений SSTables.
- **Key-Value (Redis):** Данные целиком в RAM. При нехватке памяти срабатывает eviction policy (`noeviction`, `allkeys-lru`, `volatile-ttl`).

### Резервное копирование и восстановление

Разные архитектуры требуют разных стратегий:

- **SQL:** Физический бэкап (`pg_basebackup`, `xtrabackup`) + WAL для PITR. Логический бэкап (`pg_dump`, `mysqldump`) — медленнее, но переносим. Секционирование позволяет selective restore по секциям.
- **NoSQL (LSM-Tree):** Снапшоты SSTables + WAL/commit log. Восстановление из снапшота быстрее, чем из логического дампа, но PITR реализован не во всех системах (например, Redis RDB/AOF).
- **NoSQL (Key-Value):** Redis — RDB снапшот (моментальный) + AOF (последовательность команд). Восстановление из AOF медленнее, но точнее.

### Настройка ОС и файловой системы

Для SRE/sysadmin важно учитывать различия на уровне ОС:

- **SQL (B-Tree):** Требуют предсказуемого latency. XFS/ext4 для data, отдельный диск для WAL/redo log. `noatime` для снижения лишних записей. Для NVMe — `discard=async`.
- **NoSQL (LSM-Tree):** Чувствительны к последовательной записи. Рекомендуется выделенный диск под commit log / WAL, отдельный — под SSTables. Ядро Linux 5.4+ для стабильности io_uring.
- **Key-Value (Redis):** Только RAM. Настройка `vm.overcommit_memory = 1` для предотвращения fork failures при RDB-снапшотах. Отдельный swap-раздел discouraged.

### Capacity Planning

- **SQL:** Ориентир — размер базы + индексный overhead (обычно 20–40%). Рост предсказуем через `pg_total_relation_size` / `information_schema.TABLES`.
- **NoSQL (LSM-Tree):** Учитывайте Write Amplification factor (обычно 3–10x). Диск может заполняться быстрее, чем ожидается по объему "логических" данных.
- **Key-Value (Redis):** `INFO memory` — ключевые метрики: `used_memory`, `used_memory_dataset`, `mem_fragmentation_ratio`. Приближение: данные × 2 (overhead для словарей и метаданных).

## Основные концепции

### Сравнительная характеристика (SQL vs NoSQL vs NewSQL)

| Критерий | SQL (Традиционные) | NoSQL | NewSQL (Distributed SQL) |
| :--- | :--- | :--- | :--- |
| **Модель данных** | Реляционная (Таблицы) | Гибкая (Документы, KV, Графы) | Реляционная (Таблицы) |
| **Транзакции** | Строгие ACID | Часто BASE (Eventual) | Строгие ACID (Распределенные) |
| **Масштабирование** | Вертикальное | Горизонтальное (Шардирование) | Горизонтальное (Автоматическое) |
| **Join-операции** | Нативные, оптимизированные | Ограничены / В приложении | Распределенные (Consensus-based) |
| **Схема** | Schema-on-write | Schema-on-read | Schema-on-write |
| **Структура хранения** | B-Tree / B+Tree | LSM-Tree / Hash Maps | LSM-Tree / B-Tree |
| **Целостность** | На стороне БД (FK, Constraints) | На стороне приложения | На стороне БД |

### Классификация NoSQL систем

NoSQL не является монолитной категорией. Разделение идет по способу организации данных:

1.  **Ключ-значение (Key-Value):** Самый простой тип. Высокая производительность, низкая функциональность запросов.
    - **Примеры:** Redis, Memcached.
    - **Применение:** Кэширование, сессии, корзины, лимитеры.
2.  **Документоориентированные (Document):** Хранение данных в форматах JSON/BSON. Индексация по любым полям.
    - **Примеры:** MongoDB, CouchDB.
    - **Применение:** Каталоги товаров, профили пользователей, CMS.
3.  **Колоночные (Wide-column / Column-family):** Хранение данных в семействах колонок. Оптимизированы для записи огромных объемов данных.
    - **Примеры:** Apache Cassandra, ScyllaDB, HBase.
    - **Практика:** **[Руководство по Cassandra и ScyllaDB](../cassandra_scylladb_guide.md)**. Моделирование данных: **[Обзор и моделирование](../cassandra-scylladb/overview.md)**.
    - **Применение:** Логи, метрики, IoT, история транзакций.
4.  **Графовые (Graph):** Узлы и ребра. Эффективны для обхода сложных связей.
    - **Примеры:** Neo4j.
    - **Практика:** **[Руководство по Neo4j](../neo4j_guide.md)**.
    - **Применение:** Соцсети, антифрод, рекомендательные движки.

### Проблема "Schema-less" в NoSQL системах

Термин "бессхемность" является упрощением. В реальности NoSQL системы используют подход **Schema-on-read**:
- **Перенос логики:** Ответственность за структуру и валидацию данных переносится с уровня БД на уровень приложения.
- **Гибкость vs Качество:** Это ускоряет разработку на ранних этапах, но может привести к "засорению" данных и сложностям при миграциях, если в приложении нет строгого контроля схем (например, через Mongoose в MongoDB).

### Механизмы NewSQL (Distributed SQL)

NewSQL решают проблему "бутылочного горлышка" вертикального масштабирования SQL через:
- **Шардирование на уровне ядра:** БД сама делит данные на куски (tablets/ranges).
- **Протоколы консенсуса:** Использование **[Raft или Paxos](../../etcd/raft_consensus.md)** для синхронизации шардов и обеспечения ACID в распределенной среде.
- **Двухфазная фиксация (2PC):** Для распределенных транзакций между разными узлами.

### Распределенные системы: CAP и PACELC

Традиционное понимание через **[CAP-теорему](./cap_theorem.md)** (выбор между согласованностью и доступностью при разделении сети) дополняется теоремой **PACELC**. Детали теории и практические примеры см. в **[CAP-теореме и PACELC](./cap_theorem.md)**.

### Технические компромиссы

При выборе типа СУБД необходимо учитывать следующие факторы:

1.  **Структурированность данных:**
    - **SQL:** Если данные имеют фиксированную структуру. Идеально для сложных связей (`JOIN`). В приложении для фото SQL выберут для ядра системы: связей между пользователями, фото, лайками и подписками.
    - **NoSQL:** Если данные неструктурированы или часто меняются (настройки, логи поведения).
2.  **Гарантии ACID (Транзакции):**
    - **SQL:** Обеспечивает выполнение группы операций как единого целого (Atomicity). SQL гарантирует целостность при каскадных удалениях или переводах средств.
    - **NoSQL:** Часто жертвует транзакциями ради скорости (**BASE**), что допустимо для хранения истории просмотров или лайков в реальном времени.
3.  **Задержка (Latency) vs Пропускная способность (Throughput):**
    - **SQL (B-Tree):** Низкая и стабильная задержка чтения при правильных индексах. Ограниченная пропускная способность записи из-за блокировок и in-place обновлений.
    - **NoSQL (LSM-Tree):** Колоссальная пропускная способность записи. Возможные скачки задержки (Latency Spikes) во время интенсивного процесса Compaction.
4.  **Эластичность (Elasticity):**
    - NoSQL и NewSQL позволяют добавлять узлы "на лету" без остановки системы (horizontal scaling).
    - Классический SQL требует сложных процедур шардирования или настройки отказоустойчивых кластеров (например, Patroni для PostgreSQL).
5.  **Сложность эксплуатации:**
    - Традиционные SQL базы хорошо изучены, имеют зрелый инструментарий.
    - NewSQL проще в масштабировании, но требуют понимания кворумов и распределенного консенсуса.

## Практические сценарии

### Сценарий 1: Проектирование схемы "Блог"

Сравним подходы при создании системы комментариев.

**SQL подход (Нормализация):**
```sql
-- Таблица постов и таблица комментариев связаны через Foreign Key
CREATE TABLE posts (id SERIAL PRIMARY KEY, title TEXT);
CREATE TABLE comments (
    id SERIAL PRIMARY KEY, 
    post_id INT REFERENCES posts(id), 
    content TEXT,
    created_at TIMESTAMP
);
-- Чтение: требует JOIN, эффективно при наличии индексов
SELECT p.title, c.content FROM posts p JOIN comments c ON p.id = c.post_id WHERE p.id = 1;
```

**NoSQL подход (Денормализация / Embedding):**
```json
// Данные хранятся как один документ. Нет JOIN-ов.
{
  "_id": "post_123",
  "title": "SQL vs NoSQL",
  "comments": [
    {"user": "alex", "text": "Great article!", "date": "2026-08-17"},
    {"user": "ivan", "text": "Needs more B-Trees", "date": "2026-08-18"}
  ]
}
// Чтение: один запрос по ID документа, максимально быстро.
// Риск: "раздувание" документа при тысячах комментариев (Document Size Limit).
```

### Сценарий 2: Выбор СУБД для сбора метрик

Сбор 500 000 событий/сек из 10 000 источников.

**SQL (PostgreSQL с partitioning):**
```sql
-- Таблица секционируется по created_at (ежедневно)
CREATE TABLE metrics (
    ts         TIMESTAMPTZ NOT NULL,
    source_id  INT NOT NULL,
    metric     TEXT NOT NULL,
    value      DOUBLE PRECISION
) PARTITION BY RANGE (ts);

-- Индекс на (source_id, ts) для быстрого поиска по источнику
CREATE INDEX ON metrics (source_id, ts);
```

**NoSQL (ClickHouse / Cassandra-style column family):**
- **ClickHouse:** Оптимизирован для OLAP. Вставка батчами, MergeTree семейство таблиц.
- **Cassandra:** Write path через commit log + memtable → SSTable. Данные распределяются по cluster по партиционному ключу.

**Для SRE:** В NoSQL проще горизонтально масштабировать запись. В SQL проще получить сложные агрегации через `JOIN` и оконные функции.

### Сценарий 3: Кэширование сессий

**Redis (Key-Value NoSQL):**
```bash
# Запись с TTL 30 минут
redis-cli SET session:user:12345 '{"uid":12345,"role":"admin"}' EX 1800

# Чтение
redis-cli GET session:user:12345

# Мониторинг: hit rate
redis-cli INFO stats | grep keyspace_hits
redis-cli INFO stats | grep keyspace_misses
```

**SQL (PostgreSQL):**
```sql
-- Создание таблицы сессий
CREATE TABLE sessions (
    sid      TEXT PRIMARY KEY,
    uid      BIGINT NOT NULL,
    payload  JSONB,
    expires  TIMESTAMPTZ NOT NULL,
    created  TIMESTAMPTZ DEFAULT now()
);

-- Индекс для очистки просроченных
CREATE INDEX ON sessions (expires) WHERE expires > now();

-- Запрос
SELECT payload FROM sessions WHERE sid = 'abc123' AND expires > now();
```

**Для SRE:** Redis дает sub-millisecond latency, но требует отдельного Redis-инстанса и политики persistence (RDB/AOF). PostgreSQL — проще в эксплуатации (резервное копирование, репликация), но медленнее на порядок.

### Сценарий 4: Мониторинг и алертинг

**SQL (PostgreSQL):**
```sql
-- Активные соединения по состоянию
SELECT state, count(*)
FROM pg_stat_activity
GROUP BY state;

-- Размер базы и индексов
SELECT pg_size_pretty(pg_database_size('mydb')) AS db_size;

-- Dead tuples — индикатор необходимости VACUUM
SELECT relname, n_dead_tup, last_vacuum
FROM pg_stat_user_tables
WHERE n_dead_tup > 10000
ORDER BY n_dead_tup DESC;

-- Рост размера по секциям (если partitioning)
SELECT child.relname, pg_size_pretty(pg_total_relation_size(child.oid))
FROM pg_inherits
JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
JOIN pg_class child ON pg_inherits.inhrelid = child.oid
WHERE parent.relname = 'metrics'
ORDER BY pg_total_relation_size(child.oid) DESC;
```

**NoSQL (Redis):**
```bash
# Использование памяти по ключам (опасно в проде — COPY expensive)
redis-cli --bigkeys

# Статистика
redis-cli INFO stats
redis-cli INFO memory
redis-cli INFO replication

# Ключевые метрики для SRE:
# used_memory_dataset / used_memory — доля данных в RAM
# mem_fragmentation_ratio — > 1.5 означает фрагментацию
# instantaneous_ops_per_sec — текущая нагрузка
```

**NoSQL (Cassandra):**
```bash
# Статус кластера
nodetool status

# Трат / чтение по таблицам
nodetool tablestats keyspace_name.table_name

# Сжатие
nodetool compactionstats

# SBE (SASI) индексы (если используются)
nodetool info
```

### Когда выбирать реляционные БД (SQL)

1. **Транзакционные системы:** Финансы, биллинг, бухгалтерия (требуется ACID).
2. **Сложные аналитические отчеты:** Где нужно объединять десятки таблиц через глубокие `JOIN`.
3. **Стабильная структура:** Когда данные хорошо ложатся в таблицы и схема меняется редко.

### Когда выбирать NoSQL системы

1. **Write-intensive нагрузка:** Сбор миллионов событий в секунду (логи, метрики, IoT).
2. **Кэширование и сессии:** Сверхбыстрый доступ в оперативной памяти (**[Redis](../redis_overview.md)**).
3. **Неструктурированные данные:** Гибкие каталоги товаров с динамическим набором атрибутов.
4. **Анализ связей:** Графовые задачи (друзья в соцсетях, цепочки поставок).

### Когда выбирать NewSQL (Distributed SQL)

1. **Геораспределенные кластеры:** Когда нужны транзакции между разными дата-центрами с минимальными задержками.
2. **Исчерпание лимитов SQL:** Когда master в PostgreSQL стал узким местом, а переход на NoSQL требует переписывания всей логики приложения.
3. **Автоматический Failover:** Нужна встроенная отказоустойчивость без сторонних утилит.

## Проверка и валидация

### Мониторинг состояния СУБД

**PostgreSQL:**
```sql
-- Активные соединения
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';

-- Транзакции в секунду (срез за интервал)
SELECT tph, tps FROM pg_stat_database WHERE datname = 'mydb';

-- Размер базы
SELECT pg_size_pretty(pg_database_size('mydb')) AS db_size;
```

**MySQL:**
```sql
-- Статус сервера
SHOW GLOBAL STATUS LIKE 'Threads_connected';
SHOW GLOBAL STATUS LIKE 'Queries';
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read_requests';
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_reads';

-- Cache hit ratio
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read%';
-- Вычисление: read_requests / (read_requests + reads)
```

**Redis:**
```bash
# Hit rate (если включен keyspace notifications)
redis-cli INFO stats | grep keyspace_hits
redis-cli INFO stats | grep keyspace_misses

# Скорость операций
redis-cli INFO stats | grep instantaneous_ops_per_sec
```

### Валидация консистентности данных

**SQL (PostgreSQL):**
```sql
-- Проверка целостности foreign keys
SELECT conname, conrelid::regclass, confrelid::regclass
FROM pg_constraint
WHERE contype = 'f'
  AND NOT EXISTS (
    SELECT 1 FROM pg_class c
    WHERE c.oid = conrelid
  );

-- Счетчики записей для сравнения с приложением
SELECT count(*) FROM orders WHERE user_id = 123;
```

**NoSQL (MongoDB):**
```javascript
// Проверка индексов
db.collection.getIndexes()

// Статистика коллекции
db.collection.stats()

// Поиск неиндексированных запросов (prodlog)
db.setProfilingLevel(2)
db.system.profile.find({ millis: { $gt: 100 } }).sort({ ts: -1 }).limit(5)
```

## Типичные ошибки и их решение

### 1. Выбор NoSQL для транзакционных денег

**Причина:** Попытка реализовать банковский перевод в системе с Eventual Consistency без понимания рисков.

**Решение:** Используйте SQL или NewSQL с ACID. Если архитектура требует NoSQL — внедрите Sagas или TCC на уровне приложения, но это существенно усложняет код.

### 2. "Горячие точки" (Hotspots) при шардировании

**Причина:** Неправильный выбор ключа (например, `timestamp` в Cassandra) приводит к перегрузке одного узла.

**Решение:** Используйте составной ключ с высокой кардинальностью или консистентное хеширование. Мониторьте `nodetool tpstats` (Cassandra) или `pg_stat_user_tables` (SQL) на предмет перекоса.

### 3. Отсутствие Partition Pruning в SQL

**Причина:** WHERE-условие не содержит ключ секционирования, или ключ используется с функцией/приведением типа.

**Решение:** Переписать запрос так, чтобы ключ секционирования присутствовал в WHERE без функций. Проверить через `EXPLAIN (ANALYZE, BUFFERS)`.

### 4. Слишком большие документы (MongoDB)

**Причина:** Хранение огромных массивов внутри одного документа ведет к деградации производительности при чтении и превышению лимита 16MB.

**Решение:** Разделите данные на подколлекции или используйте GridFS для больших бинарных объектов. Проектируйте модель данных с учетом Document Size Limit.

### 5. Фрагментация индексов в LSM-Tree

**Причина:** Интенсивная запись в Cassandra/ScyllaDB без настройки compaction приводит к большому количеству SSTables и высокой задержке чтения.

**Решение:** Настройте compaction strategy (`SizeTieredCompactionStrategy` для write-intensive, `LeveledCompactionStrategy` для read-intensive). Мониторьте `nodetool compactionstats`.

### 6. Эмуляция JOIN в приложении (NoSQL)

**Причина:** Выполнение множества запросов к MongoDB для сборки связей вручную.

**Решение:** Пересмотрите схему в пользу Embedding или перейдите на SQL, если JOIN-ы — основной паттерн доступа.

### 7. Недостаток RAM в Key-Value

**Причина:** Redis пытается записать больше данных, чем доступно RAM. При включенном swapping latency скачет до секунд.

**Решение:** Настройте `maxmemory` и `maxmemory-policy`. Мониторьте `used_memory`. Используйте `MEMORY USAGE key` для оценки размера ключей.

## Best Practices

### Выбор СУБД

- Проанализируйте паттерны доступа: если 90%+ запросов — чтение по ключу — Key-Value (Redis) или Document (MongoDB) могут подойти.
- Если требуется строгая консистентность и сложные транзакции — SQL или NewSQL.
- Для временных рядов (IoT, логи) — колоночные NoSQL (Cassandra, ScyllaDB) или TimescaleDB.
- Для графовых обходов — Neo4j или SQL с рекурсивными CTE (PostgreSQL 16+).

### Эксплуатация

- **Резервное копирование:** Тестируйте restore на отдельном стенде. Проверяйте логическую целостность после восстановления.
- **Мониторинг:** Настройте алерты на cache hit ratio (SQL), hit rate (Redis), compaction pending tasks (Cassandra), replication lag (все типы).
- **Capacity Planning:** Замеряйте рост данных ежемесячно. Для LSM-Tree учитывайте Write Amplification.
- **Обновления:** Планируйте обновление версий СУБД в окно обслуживания. Используйте логическую репликацию для отказоустойчивого перехода (PostgreSQL 10+, MySQL 8.0).

### Оптимизация

- **SQL:** Используйте prepared statements, connection pooling (PgBouncer, ProxySQL), правильные индексы. Настройте `shared_buffers` под 25% RAM (PostgreSQL).
- **NoSQL:** Для Cassandra — правильное моделирование данных (partition key + clustering key). Для Redis — pipeline/batch для снижения RTT.
- **NewSQL:** Мониторьте кворумы и latency between nodes. Настройке `lease` / `session` timeouts в зависимости от RPO/RTO.

## Дополнительная информация

### Эволюция поддержки

| Год | Событие |
|-----|---------|
| 2024 | PostgreSQL 16: параллельные vacuum, улучшенный partition-wise join. MySQL 8.4 LTS: Document Store improvements. |
| 2025 | PostgreSQL 17: ускоренная очистка памяти VACUUM. MySQL 9.0: улучшенная репликация. ScyllaDB: переход на календарное версионирование (2025.1 LTS). |
| 2026 | Новые SQL-стандарты и расширения JSON. NewSQL: CockroachDB 23.x+ — улучшенная поддержка гео-распределенных транзакций. |

### Смежные концепции
- **[CAP-теорема](./cap_theorem.md)** — теоретический фундамент распределенных систем.
- **[ACID vs BASE](./acid.md)** — модели согласованности данных.
- **[Шардирование](./sharding.md)** — методы горизонтального разделения данных.
- **[Репликация](./replication.md)** — обеспечение высокой доступности и масштабирование чтения.
- **[Индексы](./indexes.md)** — ускорение доступа к данным.
- **[Партиционирование](./partitioning.md)** — логическое разделение данных внутри одного инстанса.
- **[Проектирование схемы БД](./data_modeling.md)** — нормализация, ER-моделирование, денормализация (SQL).
- **[Distributed SQL](./distributed_sql.md)** — CockroachDB, TiDB, YugabyteDB: архитектура и эксплуатация.

### Пограничные случаи и ограничения

- **Глобальные уникальные ограничения в NoSQL:** В MongoDB уникальный индекс гарантирует уникальность только в рамках одного шарда (если не используется transactions). В Cassandra уникальность обеспечивается на уровне приложения или lightweight transactions (LWT) с накладностью на запись.
- **Согласованность в NewSQL:** CockroachDB и YugabyteDB обеспечивают serializable isolation, но это достигается за счет 2PC и кворумов. При геораспределении latency между регионами напрямую влияет на скорость записи.
- **Ограничения размера документов:** MongoDB — 16MB на документ. Neo4j — ограничения на глубину обхода графа. При проектировании учитывайте Document Size Limit и plan growth.
- **Стоимость миграции:** Переход с SQL на NoSQL (или наоборот) требует переписывания слоя данных. Оцените затраты до начала проекта. Используйте адаптеры и промежуточные слои для снижения риска.
