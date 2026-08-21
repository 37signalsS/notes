# Cassandra и ScyllaDB: обзор и моделирование данных

## Определения

**Wide-column (Колоночные семейства)** — тип NoSQL баз данных, где данные хранятся в строках с переменным набором столбцов. В отличие от реляционных БД, каждая строка может иметь тысячи столбцов, а физическое хранение оптимизировано для быстрого чтения и записи по ключу раздела.

**Apache Cassandra** — децентрализованная распределенная СУБД на базе Java, использующая архитектуру без мастера (Peer-to-Peer) и модель данных Google Bigtable.

**ScyllaDB** — высокопроизводительный клон Cassandra, написанный на C++ (фреймворк Seastar). Совместим с Cassandra по протоколу CQL, но обеспечивает в 3-10 раз большую пропускную способность за счет архитектуры Shard-per-core и отсутствия пауз Garbage Collector.

**CQL (Cassandra Query Language)** — SQL-подобный язык запросов для взаимодействия с кластером. Является основным интерфейсом для работы с данными в обеих СУБД. Синтаксис и примеры — **[CQL: синтаксис и примеры](./cql-syntax.md)**.

**LSM-Tree (Log-Structured Merge-Tree)** — структура данных, лежащая в основе хранения Cassandra/ScyllaDB. Данные сначала записываются в MemTable (оперативная память) и WAL (журнал транзакций), затем сбрасываются на диск как неизменяемые SSTable-файлы. Фоновый процесс Compaction объединяет SSTables, удаляя дубликаты и устаревшие записи. Подробнее — **[SQL vs NoSQL: LSM-Tree](../Concepts/sql_vs_nosql.md)**.

**Gossip-протокол** — механизм децентрализованного обмена информацией о состоянии узлов кластера. Каждый узел периодически опрашивает случайных соседей, распространяя метаданные о доступности, загрузке и состоянии JVM других узлов.

**Tombstone (Надгробие)** — маркер, обозначающий удаление данных. Физическое удаление происходит позже, при Compaction. Пока Tombstone не удален, он учитывается при чтении, что может замедлять запросы.

---

## Навигация по разделам

1.  **[Архитектура: Cassandra vs ScyllaDB](./architecture.md):** Сравнение JVM vs Seastar, vNodes vs Tablets, когда что выбирать.
2.  **[CQL: синтаксис и примеры](./cql-syntax.md):** DDL, DML, SELECT, BATCH, Lightweight Transactions.
3.  **[Установка и настройка](./installation.md):** Docker Compose,裸-metal, cassandra.yaml.
4.  **[Обслуживание и эксплуатация](./operations.md):** Compaction Strategies, Repair, gc_grace_seconds.
5.  **[Безопасность](./security.md):** Аутентификация, TLS/SSL, RBAC, Firewall.
6.  **[Тюнинг производительности](./performance.md):** JVM Heap, Scylla I/O, Tombstones, антипаттерны.
7.  **[Мониторинг и observability](./monitoring.md):** Ключевые метрики, nodetool, Prometheus, ScyllaDB endpoint.
8.  **[Бэкап и восстановление](./backup-recovery.md):** Снапшоты, инкрементальный бэкап, restore.
9.  **[Поиск и устранение неисправностей](./troubleshooting.md):** Типичные ошибки, сбор диагностики.
10. **[Масштабирование в Kubernetes](./kubernetes.md):** Scylla Operator, CRD, Helm.

---

## Моделирование данных (Data Modeling)

В Wide-column хранилищах модель данных строится строго под конкретные запросы (**Query-driven modeling**). Использование `JOIN` и сложных подзапросов невозможно.

### Составной первичный ключ (Primary Key)
```sql
PRIMARY KEY (partition_key, clustering_column1, clustering_column2)
```

1.  **Partition Key (Ключ раздела):**
    *   **Функция:** Определяет, на какой узел попадут данные (через Consistent Hashing).
    *   **Best Practice:** Высокая кардинальность. Избегайте "горячих разделов" (например, использование `date` без `id` приведет к записи всех данных за день в один узел).
2.  **Clustering Columns (Колонки кластеризации):**
    *   **Функция:** Определяют физический порядок сортировки данных внутри раздела.
    *   **Best Practice:** Используются для Range-запросов (`WHERE sensor_id = 1 AND timestamp > '2026-01-01'`).

### Пример создания таблицы
```sql
CREATE TABLE sensor_data (
    sensor_id uuid,
    event_time timestamp,
    value double,
    status text,
    PRIMARY KEY (sensor_id, event_time)
) WITH CLUSTERING ORDER BY (event_time DESC);
```

### Типы данных в CQL

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| `text` / `ascii` | Строки | `'hello'` |
| `int` / `bigint` / `varint` | Целые числа | `42`, `1000000000000` |
| `float` / `double` / `decimal` | Числа с плавающей точкой | `3.14` |
| `boolean` | Логический тип | `true` |
| `uuid` / `timeuuid` | Уникальные идентификаторы | `550e8400-e29b-41d4-a716-446655440000` |
| `timestamp` | Дата и время | `'2026-01-15 10:30:00+0000'` |
| `inet` | IP-адрес | `'192.168.1.1'` |
| `counter` | Атомарный счетчик | `0` |
| `list` / `set` / `map` | Коллекции | `['a', 'b']`, `{'x', 'y'}` |
| `tuple` | Кортеж фиксированного типа | `(1, 'text')` |
| `udt` | Пользовательский тип данных | `(name text, value int)` |

### Вторичные индексы (Secondary Indexes)

Вторичные индексы позволяют запросы по колонкам, не входящим в Primary Key. Однако в распределенных системах они имеют ограничения:

```sql
CREATE INDEX idx_status ON sensor_data (status);
-- Теперь можно:
SELECT * FROM sensor_data WHERE status = 'active';
```

**Ограничения:**
- На кластере с большим количеством узлов вторичные индексы могут вызвать рассылку запроса ко всем узлам (distributed query), что снижает производительность.
- Не подходят для колонок с высокой кардинальностью (много уникальных значений) на больших таблицах.
- Альтернатива: **materialized views** или проектирование дополнительных таблиц с нужным Partition Key.

### Materialized Views

Автоматически поддерживаемые представления, материализирующие данные в другой таблице с другим ключом:

```sql
CREATE MATERIALIZED VIEW sensor_by_status AS
    SELECT * FROM sensor_data
    WHERE sensor_id IS NOT NULL AND event_time IS NOT NULL AND status IS NOT NULL
    PRIMARY KEY (status, sensor_id, event_time);
```

**Особенности:**
- Данные дублируются: каждое изменение исходной таблицы автоматически отражается во view.
- Высокая нагрузка на запись (Write Amplification) из-за дублирования.
- Не подходят для частых обновлений исходной таблицы.

### Пользовательские типы данных (UDT)

UDT позволяют создавать структурированные колонки:

```sql
CREATE TYPE address (
    street text,
    city text,
    zip_code text,
    country text
);

CREATE TABLE users (
    user_id uuid PRIMARY KEY,
    name text,
    home address,
    work address
);
```

---

## См. также
- **[Сравнение SQL и NoSQL](../Concepts/sql_vs_nosql.md)** — архитектурные отличия.
- **[CAP-теорема и согласованность](../Concepts/cap_theorem.md)** — теоретическая база.
- **[Мониторинг СУБД](../../Prometheus/Exporters/other_exporters.md)** — экспорт метрик в Prometheus.
