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

1.  **[Обзор и моделирование данных](./cassandra-scylladb/overview.md):** Определения, Primary Key, типы данных, Secondary Indexes, SAI, Materialized Views, CDC, UDT.
2.  **[CQL: синтаксис и примеры](./cassandra-scylladb/cql-syntax.md):** DDL, DML, SELECT, BATCH, Lightweight Transactions.
3.  **[Архитектура: Cassandra vs ScyllaDB](./cassandra-scylladb/architecture.md):** Token ring, vNodes vs Tablets, gossip/Raft, snitch, storage engine, когда что выбирать.
4.  **[Установка и настройка](./cassandra-scylladb/installation.md):** Docker Compose, bare-metal, cassandra.yaml.
5.  **[Обслуживание и эксплуатация](./cassandra-scylladb/operations.md):** Compaction, Repair, жизненный цикл узлов, SSTables, управление схемой.
6.  **[Безопасность](./cassandra-scylladb/security.md):** Аутентификация, TLS/SSL, RBAC, Firewall, secrets.
7.  **[Тюнинг производительности](./cassandra-scylladb/performance.md):** JVM Heap, cassandra.yaml, ScyllaDB I/O, Tombstones, антипаттерны, нагрузочное тестирование.
8.  **[Мониторинг и observability](./cassandra-scylladb/monitoring.md):** Ключевые метрики, nodetool, Prometheus, ScyllaDB endpoint.
9.  **[Бэкап и восстановление](./cassandra-scylladb/backup-recovery.md):** Снапшоты, инкрементальный бэкап, restore.
10. **[Поиск и устранение неисправностей](./cassandra-scylladb/troubleshooting.md):** Типичные ошибки, сбор диагностики, zombie data, clock skew.
11. **[Развёртывание и масштабирование в Kubernetes](./cassandra-scylladb/kubernetes.md):** Scylla Operator, cass-operator, K8ssandra, Helm, CRD.
12. **[Клиентские драйверы](./cassandra-scylladb/drivers.md):** Пул соединений, load balancing, retry, reconnection, application.conf.
13. **[Capacity Planning](./cassandra-scylladb/capacity-planning.md):** Расчёт числа узлов, headroom compaction, repair-трафик.
14. **[Multi-DC и аварийное восстановление](./cassandra-scylladb/multi-dc-dr.md):** Несколько DC, LOCAL_QUORUM, RPO/RTO, switchover/failover.
15. **[Миграция и upgrade](./cassandra-scylladb/upgrade-migration.md):** Rolling upgrade, Cassandra → ScyllaDB (Hydra), откат.
16. **[Runbook](./cassandra-scylladb/runbook.md):** Алерты → диагностика → действие, SLO/SLI.
17. **[Вопросы для собеседования](./cassandra-scylladb/interview_qa.md):** Операционные вопросы и короткие ответы.

---

## См. также
- **[Сравнение SQL и NoSQL](./Concepts/sql_vs_nosql.md)** — архитектурные отличия.
- **[CAP-теорема и согласованность](./Concepts/cap_theorem.md)** — теоретическая база.
- **[Мониторинг СУБД](../Prometheus/Exporters/other_exporters.md)** — экспорт метрик в Prometheus.
