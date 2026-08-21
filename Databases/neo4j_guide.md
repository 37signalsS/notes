# Neo4j: Графовая база данных

Документация декомпозирована в тематические файлы.

## Разделы

- **[Обзор и определения](./Neo4j/overview.md)** — версия, LPG vs RDF, когда использовать, сравнение с альтернативами.
- **[Архитектура и хранение](./Neo4j/architecture.md)** — Index-free adjacency, store files, транзакционный движок, WAL.
- **[Установка и настройка](./Neo4j/installation_and_setup.md)** — Ubuntu APT, Docker, Docker Compose, APOC, начальная конфигурация.
- **[Cypher: полное руководство](./Neo4j/cypher_guide.md)** — CRUD, моделирование данных, обход графа, агрегации, импорт из CSV.
- **[Оптимизация запросов](./Neo4j/query_optimization.md)** — EXPLAIN/PROFILE, индексы, правила эффективных запросов.
- **[APOC: библиотека расширений](./Neo4j/apoc.md)** — установка, конфигурация, типичные сценарии.
- **[Драйверы](./Neo4j/drivers.md)** — Python, Java, JavaScript/TypeScript.
- **[Обслуживание и эксплуатация](./Neo4j/operations.md)** — память, бэкап/восстановление, диагностика, метрики.
- **[Кластеризация и HA](./Neo4j/clustering.md)** — Causal Clustering, AuraDB.
- **[Безопасность](./Neo4j/security.md)** — RBAC, TLS.
- **[Graph Data Science](./Neo4j/graph_data_science.md)** — GDS плагин, алгоритмы, экосистема.

## См. также
- **[Сравнение SQL и NoSQL](./Concepts/sql_vs_nosql.md)** — место графовых БД в экосистеме.
- **[Индексы в базах данных](./Concepts/indexes.md)** — общая теория структур данных.
- **[Официальная документация Cypher](https://neo4j.com/docs/cypher-manual/current/)**
