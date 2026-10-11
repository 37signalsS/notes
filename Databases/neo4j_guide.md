# Neo4j: Графовая база данных

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS

Документация декомпозирована в тематические файлы; каждый файл несёт собственную строку области применения. Ключевая дата планирования: поддержка LTS 5.26 — до июня 2028.

## Разделы

- **[Обзор и определения](./Neo4j/overview.md)** — редакции и лицензии, версии и поддержка, модель данных, форматы хранения, порты, версии Cypher и рантаймы, когда использовать, сравнение с альтернативами.
- **[Архитектура и хранение](./Neo4j/architecture.md)** — Index-free adjacency, store files, транзакционный движок, WAL.
- **[Установка и настройка](./Neo4j/installation_and_setup.md)** — Ubuntu APT, RHEL/DNF, Docker, Docker Compose, APOC, начальная конфигурация, hardening.
- **[Cypher: полное руководство](./Neo4j/cypher_guide.md)** — CRUD, моделирование данных, обход графа, агрегации, импорт из CSV.
- **[Оптимизация запросов](./Neo4j/query_optimization.md)** — EXPLAIN/PROFILE, индексы, правила эффективных запросов, разбор инцидента.
- **[APOC: библиотека расширений](./Neo4j/apoc.md)** — установка, конфигурация, типичные сценарии.
- **[Драйверы](./Neo4j/drivers.md)** — Python, Java, JavaScript/TypeScript, Go, .NET.
- **[Обслуживание и эксплуатация](./Neo4j/operations.md)** — память, чекпоинты, systemd, диагностика, остановка.
- **[Бэкап и восстановление](./Neo4j/backup_and_restore.md)** — офлайн- и онлайн-бэкап, restore, PITR, проверка.
- **[Мониторинг и логи](./Neo4j/monitoring.md)** — журналы, `query.log`, метрики, Prometheus, дашборды и алерты.
- **[Диагностика на уровне JVM](./Neo4j/jvm_diagnostics.md)** — слои памяти процесса, GC, NMT, дампы кучи.
- **[Кластеризация и HA](./Neo4j/clustering.md)** — primary/secondary, топология, маршрутизация, кросс-кластерная репликация, DR.
- **[Обновление версии и миграция](./Neo4j/upgrade_and_migration.md)** — модель версий, LTS-чекпоинты, breaking changes, откат.
- **[Kubernetes](./Neo4j/kubernetes_deployment.md)** — Helm-чарт, типы томов, режимы обслуживания, обновление.
- **[Мультитенантность и composite databases](./Neo4j/multi_tenancy.md)** — стратегии изоляции, лимиты, федерация графов.
- **[Массовый импорт и начальная загрузка](./Neo4j/bulk_import.md)** — `neo4j-admin database import`, режимы, требования к данным.
- **[Миграции схемы и эволюция модели данных](./Neo4j/schema_migrations.md)** — версионирование, Neo4j-Migrations, expand/contract.
- **[CDC и интеграция с потоками](./Neo4j/cdc_integration.md)** — Change Data Capture, Kafka Connector, Debezium.
- **[Безопасность](./Neo4j/security.md)** — RBAC, TLS, защита запросов от инъекций.
- **[Антипаттерны моделирования графа](./Neo4j/data_modeling_antipatterns.md)** — суперноды, гиперрёбра, мульти-лейблы, обходы без границ.
- **[Нагрузочное тестирование](./Neo4j/performance_testing.md)** — что измерять и что ломает тест в Neo4j.
- **[Graph Data Science](./Neo4j/graph_data_science.md)** — GDS плагин, алгоритмы, экосистема.

## См. также
- **[Сравнение SQL и NoSQL](./Concepts/sql_vs_nosql.md)** — место графовых БД в экосистеме.
- **[Индексы в базах данных](./Concepts/indexes.md)** — общая теория структур данных.
- **[Репликация: теория](./Concepts/replication.md)** — общие принципы репликации в БД.
- **[Prometheus: обзор](../../Prometheus/overview.md)** — сбор метрик с эндпоинта Neo4j `/metrics`.
- **[Официальная документация Cypher](https://neo4j.com/docs/cypher-manual/current/)**
- **[Operations Manual](https://neo4j.com/docs/operations-manual/current/)** — установка, эксплуатация, мониторинг.
