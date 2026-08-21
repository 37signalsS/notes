# Cassandra и ScyllaDB: Wide-column хранилища

## Определения

**Wide-column (Колоночные семейства)** — тип NoSQL баз данных, где данные хранятся в строках с переменным набором столбцов. В отличие от реляционных БД, каждая строка может иметь тысячи столбцов, а физическое хранение оптимизировано для быстрого чтения и записи по ключу раздела.

**Apache Cassandra** — децентрализованная распределенная СУБД на базе Java, использующая архитектуру без мастера (Peer-to-Peer) и модель данных Google Bigtable.

**ScyllaDB** — высокопроизводительный клон Cassandra, написанный на C++ (фреймворк Seastar). Совместим с Cassandra по протоколу CQL, но обеспечивает в 3-10 раз большую пропускную способность за счет архитектуры Shard-per-core и отсутствия пауз Garbage Collector.

**CQL (Cassandra Query Language)** — SQL-подобный язык запросов для взаимодействия с кластером. Является основным интерфейсом для работы с данными в обеих СУБД.

**LSM-Tree (Log-Structured Merge-Tree)** — структура данных, лежащая в основе хранения Cassandra/ScyllaDB. Данные сначала записываются в MemTable (оперативная память) и WAL (журнал транзакций), затем сбрасываются на диск как неизменяемые SSTable-файлы. Фоновый процесс Compaction объединяет SSTables, удаляя дубликаты и устаревшие записи.

**Gossip-протокол** — механизм децентрализованного обмена информацией о состоянии узлов кластера. Каждый узел периодически опрашивает случайных соседей, распространяя метаданные о доступности, загрузке и состоянии JVM других узлов.

**Tombstone (Надгробие)** — маркер, обозначающий удаление данных. Физическое удаление происходит позже, при Compaction. Пока Tombstone не удален, он учитывается при чтении, что может замедлять запросы.

---

## Навигация по разделам

Детальное изучение конкретных аспектов Cassandra/ScyllaDB:

1.  **[Обзор и моделирование данных](./cassandra-scylladb/overview.md):** Определения, Primary Key, типы данных, Secondary Indexes, Materialized Views, UDT.
2.  **[CQL: синтаксис и примеры](./cassandra-scylladb/cql-syntax.md):** DDL, DML, SELECT, BATCH, Lightweight Transactions.
3.  **[Архитектура: Cassandra vs ScyllaDB](./cassandra-scylladb/architecture.md):** Seastar vs JVM, vNodes vs Tablets, когда что выбирать.
4.  **[Установка и настройка](./cassandra-scylladb/installation.md):** Docker Compose,裸-metal, cassandra.yaml.
5.  **[Обслуживание и эксплуатация](./cassandra-scylladb/operations.md):** Compaction Strategies, Repair, gc_grace_seconds.
6.  **[Безопасность](./cassandra-scylladb/security.md):** Аутентификация, TLS/SSL, RBAC, Firewall.
7.  **[Тюнинг производительности](./cassandra-scylladb/performance.md):** JVM Heap, Scylla I/O, Tombstones, антипаттерны.
8.  **[Мониторинг и observability](./cassandra-scylladb/monitoring.md):** Ключевые метрики, nodetool, Prometheus, ScyllaDB endpoint.
9.  **[Бэкап и восстановление](./cassandra-scylladb/backup-recovery.md):** Снапшоты, инкрементальный бэкап, restore.
10. **[Поиск и устранение неисправностей](./cassandra-scylladb/troubleshooting.md):** Типичные ошибки, сбор диагностики.
11. **[Масштабирование в Kubernetes](./cassandra-scylladb/kubernetes.md):** Scylla Operator, CRD, Helm.

---

## См. также
- **[Сравнение SQL и NoSQL](./Concepts/sql_vs_nosql.md)** — архитектурные отличия.
- **[CAP-теорема и согласованность](./Concepts/cap_theorem.md)** — теоретическая база.
- **[Мониторинг СУБД](../Prometheus/Exporters/other_exporters.md)** — экспорт метрик в Prometheus.
