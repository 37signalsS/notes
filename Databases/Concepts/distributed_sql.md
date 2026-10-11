**Актуально для:** CockroachDB 25.4 / 26.2 / TiDB 8.5 LTS / YugabyteDB v2025.2 LTS, v2026.1 STS (2024–2026)

# Distributed SQL: CockroachDB, TiDB, YugabyteDB

Концептуальная основа NewSQL (шардирование ядром, консенсус, 2PC, CAP/PACELC) — в **[Сравнении SQL и NoSQL](./sql_vs_nosql.md)**. Этот файл — только практика: архитектура конкретных систем, их различия и эксплуатация.

## Определения

**Distributed SQL** — СУБД, предоставляющая стандартный SQL-интерфейс с ACID-транзакциями, при этом данные автоматически шардируются (tablets/ranges) и реплицируются между узлами через протокол консенсуса. Масштабирование горизонтальное, без клиентского шардирования.

**Range / Tablet** — непрерывный диапазон ключей (CockroachDB: range, ~512 МБ по умолчанию; TiDB: Region, ~96 МБ; YugabyteDB: tablet). Единица распределения данных и репликации.

**Raft group** — группа реплик одного range/tablet, синхронизирующая запись через Raft-консенсус. Лидер обслуживает чтение и запись; фолловеры — реплику.

**Leaseholder** — реплика,держит lease на обслуживание чтения range (CockroachDB). Чтение идёт к leaseholder, запись — к Raft-лидеру (обычно тот же узел).

**Zone config / Placement** — политика размещения реплик: сколько копий, в каких зонах/ДЦ, какие таблицы где хранить (geo-partitioning).

**HTAP** — Hybrid Transactional/Analytical Processing: одна система для OLTP и OLAP (TiDB: TiKV для OLTP + TiFlash columnar для OLAP).

## Основные концепции

### Как работает Distributed SQL

1. **SQL-слой** принимает запрос, парсит, строит план (CockroachDB: DistSQL; TiDB: TiDB Server stateless; YugabyteDB: YSQL — PostgreSQL-протокол).
2. **Координатор** определяет, какие range/tablet задействованы, и отправляет подзапросы к их лидерам.
3. **Запись:** Raft-консенсус внутри группы реплик (кворум = N/2+1) → применение к storage engine → ответ клиенту.
4. **Распределённые транзакции:** 2PC между задействованными range (CockroachDB, YugabyteDB) или Percolator-модель (TiDB: timestamp oracle + 2PC).
5. **Ребалансировка:** при добавлении узла range/tablet автоматически перемещаются (split + rebalance).

**Согласованность:** CockroachDB — всегда serializable. TiDB — snapshot isolation по умолчанию, `SERIALIZABLE` опционально. YugabyteDB: YSQL по умолчанию — **Snapshot** (аналог PostgreSQL `REPEATABLE READ`); `SERIALIZABLE` доступен опционально; с v2025.2+ (yugabyted/YBA/Aeon) `READ COMMITTED` включён по умолчанию (в более ранних версиях нужен флаг `yb_enable_read_committed_isolation=true`, иначе Read Committed падает на Snapshot).

### Сравнение систем

| Свойство | CockroachDB | TiDB | YugabyteDB |
| :--- | :--- | :--- | :--- |
| **SQL-совместимость** | PostgreSQL-протокол (wire), диалект — свой | MySQL-протокол и диалект | PostgreSQL (YSQL) + Cassandra (YCQL) |
| **Storage engine** | Pebble (RocksDB-inspired) | TiKV (RocksDB) | DocDB (RocksDB-based) |
| **Консенсус** | Raft (multi-Raft) | Raft (multi-Raft) | Raft (multi-Raft) |
| **Распределённые транзакции** | 2PC + parallel commits | Percolator (TSO + 2PC) | 2PC |
| **OLAP** | нет нативного columnar (follower reads) | TiFlash (columnar, HTAP) | нет нативного columnar |
| **Гео-размещение** | zone configs, geo-partitioning | placement rules | placement policies, xCluster |
| **Масштаб кластера** | до 300+ узлов (валидировано 2026) | десятки узлов TiKV | десятки узлов |
| **Лицензия** | BSL (enterprise features) | Apache 2.0 (ядро) | Apache 2.0 (ядро) |
| **Текущая линейка (2026)** | 25.4 Regular / 26.2 Regular | 8.5 LTS | v2025.2 LTS / v2026.1 STS |

**Версии YugabyteDB:** схема `vYYYY.M.patch` (v2026.1.2 — STS, поддержка до Dec 2027; v2025.2 — LTS, поддержка до Dec 2027, EOL Jun 2028).

### Когда выбирать Distributed SQL

**Выбирать:**
- Нужен SQL + ACID + горизонтальное масштабирование без клиентского шардирования.
- Требуется выживание потери зоны/ДЦ (Raft-кворум).
- Geo-размещение данных (регуляторика: данные резидентов в своём ДЦ).

**Не выбирать (использовать PostgreSQL + Patroni или шардирование):**
- Нагрузка укладывается в один узел (Distributed SQL добавляет latency: кворум-запись = 2 RTT внутри ДЦ).
- Нужны специфичные расширения PostgreSQL (PostGIS, pgvector — частично поддерживаются, проверяйте по матрице совместимости).
- Команда не знает Raft/консенсус — эксплуатация сложнее одиночного PostgreSQL (**[CAP и PACELC](./cap_theorem.md)**).

**Альтернативы:** Vitess (шардирование MySQL на уровне прокси), Citus (расширение PostgreSQL) — см. **[Шардирование](./sharding.md)**.

## Практические сценарии

#### Предпосылки

- **Версии СУБД** — по scope-линии выше; поведение изоляции (YugabyteDB) и синтаксис зон-конфигураций (CockroachDB) версионно-зависимы.
- **Права:** `CREATE`/`ALTER`/`CONFIGURE ZONE` (администратор) для настройки репликации; `SELECT` и право на `EXPLAIN` для проверки планов; `VIEWACTIVITY`/`VIEWACTIVITYREDACTED` для просмотра активных запросов.
- **Среда:** staging-копия кластера с репрезентативным объёмом данных — на пустом кластере `EXPLAIN ANALYZE` не покажет реальные издержки кворума.
- **Кластер:** нечётное число узлов (3/5); узлы — в одном ДЦ для latency-критичного трафика (RTT < 1 мс).

### Сценарий 1: Топология развёртывания

```
Минимум: 3 узла (кворум Raft = 2). Нечётное число узлов.

ДЦ-A (2 узла)  +  ДЦ-B (1 узел)  →  выживание потери одного ДЦ
ДЦ-A + ДЦ-B + ДЦ-C (по 1 узлу)    →  выживание потери любого ДЦ

# CockroachDB: запуск узла
cockroach start --insecure --join=node1,node2,node3 \
  --store=ssd1 --listen-addr=node1:26257 --http-addr=node1:8080

# TiDB: минимальный кластер (TiDB + TiKV + PD)
tiup playground --db 1 --kv 3 --pd 3

# YugabyteDB: 3-узловой локальный кластер
./bin/yugabyted start --base_dir=/tmp/yb --listen=127.0.0.1
```

### Сценарий 2: Geo-размещение (CockroachDB)

```sql
-- Закрепить таблицу за зоной (данные резидентов ЕС — в ЕС)
ALTER TABLE eu_customers CONFIGURE ZONE USING
    num_replicas = 5,
    constraints = '[+region=eu: 3, +region=us: 2]',
    lease_preferences = '[[+region=eu]]';

-- Проверка размещения реплик
SHOW RANGES FROM TABLE eu_customers;
```

### Сценарий 3: TiDB HTAP — OLTP + OLAP в одной системе

```sql
-- OLTP-нагрузка идёт в TiKV (rowstore)
SELECT * FROM orders WHERE user_id = 42;

-- Аналитический запрос — в TiFlash (columnar), изоляция снапшота
SELECT status, count(*), sum(amount) FROM orders
WHERE created_at > now() - interval 30 day
GROUP BY status;
-- План должен показать TiFlash: EXPLAIN ANALYZE SELECT ...
```

## Операции и команды

### Добавление узла (ребалансировка)

```bash
# CockroachDB: новый узел присоединяется, range перебалансируются автоматически
cockroach start --join=node1,node2,node3 --store=ssd2 ...
# Мониторинг перебалансировки: DB Console → Overview → Replication

# TiDB: масштабирование TiKV
tiup scale-out topology.yaml  # добавлен новый TiKV → Regions перебалансируются

# YugabyteDB
./bin/yb-ctl add_node
```

### Диагностика кластера

```sql
-- CockroachDB: состояние range и реплик
SHOW RANGES FROM TABLE orders;
SELECT * FROM [SHOW CLUSTER STATEMENTS];  -- активные запросы

-- TiDB: горячие Regions
ADMIN SHOW HOT REGIONS;
-- YugabyteDB: статус через yb-admin
./bin/yb-admin -master_addresses <masters> list_tablets
```

### Мониторинг и SRE-операции

```sql
-- CockroachDB: состояние range и реплик
SHOW RANGES FROM TABLE orders;
SELECT * FROM [SHOW CLUSTER STATEMENTS];   -- активные запросы (VIEWACTIVITY)

-- CockroachDB: репликация и кворум
SHOW ZONE CONFIGURATION FROM RANGE default;
SELECT * FROM crdb_internal.ranges;
SELECT * FROM crdb_internal.leader_statuses;  -- Raft-лидеры

-- TiDB: горячие Regions и балансировка
ADMIN SHOW HOT REGIONS;
ADMIN SHOW SCHEDULE;
SHOW STATUS LIKE 'tikv_store_status';

-- YugabyteDB: статус через yb-admin
./bin/yb-admin -master_addresses <masters> list_tablets
./bin/yb-admin -master_addresses <masters> list_live_servers
```

**Ключевые метрики (SRE):**
- `unavailable ranges` (CockroachDB) / `down_regions` (TiDB) — при >0 кластер в проблемах.
- `raft_leader` — количество leaderless ranges (0 = кворум цел).
- `leader_changes` — частая смена лидеров = нестабильная сеть/узлы.
- `uncommitted`/`pending` транзакции — прилипшие 2PC (при потере узла).
- `gc_queue` / `replication_factor` — отклонение от заданного числа реплик.
- `kv.raft_log_trailing` — разреженность лога (при дисковых бottleneck).
- `sql_connections` / `active_queries` — пиковая нагрузка и медленные запросы.

**Аварийные сценарии:**
- **Потеря узла:** кворум восстанавливается автоматически; проверить `SHOW RANGES` на `num_replicas` и `num_voters` (CockroachDB 26.2+), дождаться репликации.
- **Split brain:** impossible при соблюдении Raft-кворума; при подозрении — остановить кластер, проверить конфигурацию узлов (`--join`).
- **Размер range растёт:** `ALTER TABLE ... CONFIGURE ZONE USING range_max_bytes = ...` или ручной `SPLIT AT`/`EXPIRE`.
- **Локальный ДЦ упал:** geo-конфигурация должна выдерживать потере ДЦ (constraints по ДЦ); проверить, что `num_replicas` ≥ 2 в каждом ДЦ.

**План отката (SRE):**
- Backup перед каждой миграцией (инкрементальный, в объектное хранилище) + тест восстановления (**[Валидация бэкапов](./backup_validation.md)**).
- При неисправности кластера — восстановление из бэкапа на отдельный кластер, переключение приложения (cut-over — **[Миграция: отсечение](./migrations/migration_cutover.md)**).
- Откат схемы — стратегии отката (**[Стратегии отката](./migrations/rollback_strategies.md)**).
```

### Бэкап и восстановление

```bash
# CockroachDB: полный + инкрементальный
cockroach sql --execute="BACKUP DATABASE app TO 'nodelocal://1/backup'"
cockroach sql --execute="BACKUP DATABASE app TO 'nodelocal://1/backup' INCREMENTAL FROM 'nodelocal://1/backup'"

# TiDB: BR (Backup & Restore)
tiup br backup full --pd <pd>:2379 --storage "local:///backup"

# YugabyteDB: snapshot через yb-admin
./bin/yb-admin -master_addresses <masters> create_snapshot <table_name>
```

## Поиск и устранение неисправностей

### Проблема: retry errors (40001 / Write Conflict)

**Симптомы:** приложение получает `SQLSTATE 40001` (CockroachDB), `Write conflict` (TiDB), `TransactionAborted` (YugabyteDB) при конкурентных записях.

**Причина:** serializable-изоляция обнаруживает конфликт транзакций; клиент должен повторить транзакцию.

**Решение:**
1. Клиентская библиотека с автоматическими retry (CockroachDB: `cockroach sql` и драйверы с retry; TiDB: `tidb_retry_limit`).
2. Уменьшить размер транзакции (меньше задействованных range → меньше конфликтов).
3. TiDB: `SET GLOBAL tidb_txn_mode='pessimistic'` — пессимистичная модель ближе к MySQL-привычкам.

### Проблема: latency записи выше, чем у одиночного PostgreSQL

**Симптомы:** p99 INSERT = 5–15 мс вместо 1–2 мс.

**Причина:** запись требует кворума Raft (2 RTT внутри ДЦ) + fsync на фолловерах.

**Решение:**
1. Follower reads (CockroachDB `AS OF SYSTEM TIME follower_read_timestamp()`) для read-only трафика.
2. Убедиться, что узлы в одном ДЦ/зоне с низким RTT (< 1 мс).
3. Не распределять кластер географически без необходимости (geo = +100 мс на кворум).

### Проблема: горячий range (hot range / hot spot)

**Симптомы:** один узел загружен, остальные простаивают; `ADMIN SHOW HOT REGIONS` показывает один Region.

**Причина:** монотонный PK (sequence/auto-increment) → все новые строки в одном range.

**Решение:**
1. UUID v7 / Snowflake ID (**[Генерация идентификаторов](./id_generation.md)**) — равномерное распределение.
2. Hash-шардирование PK (`(id, shard_id)` составной PK).
3. CockroachDB: `ALTER TABLE ... SPLIT AT` для предварительного разделения.

### Проблема: потеря кворума

**Симптомы:** кластер недоступен для записи при потере 2 из 3 узлов.

**Причина:** Raft требует N/2+1 реплик. При 3 узлах выживает потеря 1.

**Решение:** 5 узлов для критичных систем (выживает 2), зоны размещения по разным ДЦ, мониторинг `raft_leader` и `unavailable ranges`.

### Проблема: несовместимость диалекта

**Симптомы:** запросы, работавшие на PostgreSQL/MySQL, падают на Distributed SQL (отсутствующие расширения, функции, хинты).

**Решение:** проверить матрицу совместимости (CockroachDB — PostgreSQL-совместимость; YugabyteDB YSQL — PostgreSQL; TiDB — MySQL) до миграции; тестовый прогон полного набора запросов (**[Database CI/CD](./migrations/database-ci-cd.md)**).

## Лучшие практики

1. **Нечётное число узлов (3/5)** и реплик — кворум Raft.
2. **Один ДЦ для latency-критичного трафика;** geo-размещение — только для регуляторики и DR.
3. **UUID v7 / Snowflake вместо sequence** — защита от горячих range.
4. **Retry на стороне клиента** — обязательная часть кода работы с serializable-изоляцией.
5. **Мониторинг:** unavailable ranges, Raft-лидеры, latency кворума, размер range.
6. **Бэкапы:** инкрементальные в объектное хранилище + тест восстановления (**[Валидация бэкапов](./backup_validation.md)**).
7. **Не мигрируйте «просто так»:** Distributed SQL оправдан, когда одиночный узел упирается в ресурсы или нужна выживаемость ДЦ.
8. **Мониторинг как инфраструктура:** unavailable ranges, leader changes, latency кворума, replication factor — без этих метрик кластер слеп. См. **[Мониторинг миграций](./migrations/monitoring.md)**.
9. **Тестировать failover и восстановление:** план отката (SRE) — не теория, а регулярная проверка.

## Дополнительная информация

### Смежные темы
- **[Сравнение SQL и NoSQL](./sql_vs_nosql.md)** — концепции NewSQL, CAP/PACELC.
- **[CAP-теорема и PACELC](./cap_theorem.md)** — теория компромиссов.
- **[Шардирование](./sharding.md)** — клиентское шардирование, Vitess, Citus.
- **[Репликация](./replication.md)** — Raft, консенсус, кворумы.
- **[Генерация идентификаторов](./id_generation.md)** — ID без горячих range.
- **[Блокировки и изоляция](../PostgreSQL/Concepts/concurrency_and_locking.md)** — serializable, SSI.
- **[etcd и Raft](../../etcd/raft_consensus.md)** — протокол консенсуса.
- **[HA: Patroni и Pacemaker](../PostgreSQL/Operations/high_availability_patroni.md)** — альтернатива Distributed SQL для одиночного PostgreSQL.
- **[Мониторинг миграций](./migrations/monitoring.md)** — метрики кластера и миграций.
- **[Миграция: отсечение](./migrations/migration_cutover.md)** — cut-over и откат.
- **[Работа с инцидентами](../../SRE/incident_response.md)** — SRE-подход к неисправностям БД.
