# Миграция и upgrade

**Актуально для:** Apache Cassandra 4.0/5.0.x / ScyllaDB 2026.x

## Определения

| Термин | Определение |
| :--- | :--- |
| Rolling upgrade | Upgrade по одному узлу за раз: кластер остаётся доступным на протяжении всего процесса |
| Drain | Останов приёма записей и сброс memtables на диск перед остановкой узла (`nodetool drain`) |
| `upgradesstables` | Перезапись SSTables в формате текущей версии — после upgrade **всех** узлов кластера |
| Schema agreement | Состояние, когда все узлы кластера имеют одинаковую версию схемы (`nodetool describecluster`) |
| ScyllaDB Hydra | Spark-приложение для миграции данных в ScyllaDB из CQL-источников (Cassandra) и DynamoDB (бывший ScyllaDB Migrator) |
| sstableloader | Утилита bulk-загрузки SSTables из внешних файлов в кластер (см. [Обслуживание](./operations.md)) |

## Как устроен upgrade

**Принцип rolling upgrade:** кластер работает во время upgrade — узлы обновляются по очереди, каждый возвращается в состояние `UN` перед переходом к следующему. Смешанная версионность допустима в процессе, но не как постоянное состояние.

Между мажорными версиями эволюционирует формат SSTable (Cassandra 5.0 — trie-indexed BTI, BigFormat `oa`; ScyllaDB — SSTable 3.x). `upgradesstables` перезаписывает SSTables в формате текущей версии — поэтому его смысл, флаги (`-j`, `-a`) и throttling описаны в [Обслуживании SSTables](./operations.md#обслуживание-sstables), а детали формата — в [Архитектуре](./architecture.md).

**Правила:**

1. **Бэкап перед upgrade** — снапшот (`nodetool snapshot`) на каждом узле (см. [Бэкап](./backup-recovery.md)).
2. **Порядок версий:** upgrade между мажорными версиями выполняется последовательно через промежуточные мажорные версии (например, 3.11 → 4.0 → 5.0). Точную матрицу поддерживаемых путей проверяйте в официальном upgrade guide перед планированием.
3. **`upgradesstables` — только после upgrade ВСЕХ узлов**, иначе SSTables будут перезаписаны в новом формате, который старые узлы не прочитают.
4. **Не менять схему во время rolling upgrade** — дождаться schema agreement (`nodetool describecluster`).
5. **Конфигурация:** новые параметры `cassandra.yaml`/`scylla.yaml` вносить после остановки узла; удалённые параметры (например, Thrift-опции в 4.0) нельзя добавлять обратно — узел не запустится.

## Предпосылки и подготовка

**Версии (см. строку версии):** Apache Cassandra 4.0.21 / 5.0.9 — upgrade 4.x → 5.0 официально протестирован как **online upgrade** (минимум простоев); ScyllaDB 2026.3 — последний релиз (LTS-ветка 2026.1). ScyllaDB: **все узлы кластера должны быть на одной версии перед переходом на следующую** (мажоры нельзя пропускать — 2025.1 → 2026.1 допустимо, а прямого 2025 → 2027 нет; миноры внутри 2025.4+ можно пропускать).

**Бэкапы (обязательно, до начала rolling upgrade):**
- Снапшот на каждом узле: `nodetool snapshot -t upgrade_<tag> <keyspace>...` — твёрдые ссылки на данные, мгновенно (см. [Бэкап](./backup-recovery.md)).
- Бэкап конфигурационных файлов (`cassandra.yaml` / `scylla.yaml`) — нужен для rollback.
- ScyllaDB: `sctool backup` (Scylla Manager) либо snapshot — см. [Бэкап](./backup-recovery.md).

**Предварительная проверка кластера** (на каждом узле / по всему кластеру):
- `nodetool status` — все узлы `UN`, нет `DN`/`LEAVING`/`JOINING` (нет pending topology ops).
- `nodetool describecluster` — одна версия schema (совпадают `Schema versions`), нет активных `range slices`.
- `nodetool compactionstats` и `nodetool tpstats` — нет долгих pending compaction/flush/repair.
- `nodetool info` / `nodetool ring` — load примерно равномерен.
- NTP синхронизирован (см. [Архитектура](./architecture.md)) — LWW-разрешение конфликтов зависит от часов.

**Инструменты и рантайм:**
- `nodetool` — для ScyllaDB совместима с Java-`nodetool` через нативный `scylla nodetool` (5.4+, см. [Обслуживание](./operations.md#определения)); `cqlsh`.
- Cassandra 5.0 — Java 17 (G1 по умолчанию); 4.0/4.1 — Java 11–17 (CMS/G1); запуск на Java 11 и 17 (см. [Архитектура](./architecture.md)).

**Ограничения во время upgrade:** не менять схему и не выполнять topology-операции (add/remove/decommission/replace/rebuild) — см. [Жизненный цикл узла](./operations.md#жизненный-цикл-узла-node-lifecycle).

## Практические сценарии

### Rolling upgrade Cassandra

На каждом узле по очереди:

```bash
# 1. Остановить приём записей и сбросить memtables
nodetool drain

# 2. Остановить сервис
sudo systemctl stop cassandra

# 3. Обновить бинари/пакеты до новой версии
# (apt/yum или замена tarball; проверить новые параметры конфигурации в release notes)

# 4. Запустить и дождаться UN
sudo systemctl start cassandra
nodetool status   # → узел UN перед переходом к следующему
```

После upgrade **всех** узлов кластера:

```bash
# Перезаписать SSTables в новом формате (на каждом узле)
nodetool upgradesstables
```

### Rolling upgrade ScyllaDB

ScyllaDB upgrade — rolling, без простоя. До начала: снапшот + бэкап `/etc/scylla.yaml` (см. [Бэкап](./backup-recovery.md)); убедиться, что все узлы в `UN` и схема сошлась (см. [Предпосылки](./upgrade-migration.md#предпосылки-и-подготовка)).

На каждом узле по очереди:

```bash
# 1. Бэкап конфигурации
cp /etc/scylla.yaml /etc/scylla.yaml.bak.upgrade

# 2. Graceful stop: сбросить memtables, остановить сервис
nodetool drain            # сбросить memtables в SSTables
sudo systemctl stop scylla-server

# 3. Обновить пакеты ScyllaDB до целевой версии (apt/yum)
sudo apt-get install scylla      # либо: yum update scylla

# 4. Запустить и дождаться полного входа в кластер
sudo systemctl start scylla-server
nodetool status                 # → все узлы UN
nodetool version                # → целевая версия (одинаково на всех узлах)

# После upgrade ВСЕХ узлы кластера (на каждом узле):
nodetool upgradesstables        # перезаписать SSTables; -j/-a — в [Обслуживание SSTables](./operations.md#обслуживание-sstables)
```

Проверка: `nodetool version` одинаков на всех узлах; в `/var/log/scylla/scylla.log` — без ошибок старта.

> **Откат (downgrade):** возможен только пока не все узлы проапгрейжены — graceful stop → downgrade пакетов → восстановить `/etc/scylla.yaml` → start → validate. После upgrade финального узла откат невозможен — только restore из бэкапа (см. [Бэкап](./backup-recovery.md)).

### Миграция Cassandra → ScyllaDB

**ScyllaDB Hydra** (бывший ScyllaDB Migrator) — Spark-приложение для переноса данных:

- Источники: CQL-совместимые кластеры (Cassandra) и DynamoDB; приёмник — ScyllaDB.
- Работает как Spark-job: читает источник и пишет в ScyllaDB с распределённой параллельностью.
- Документация: migrator.docs.scylladb.com.

**Альтернативы для начальной загрузки:** `sstableloader` (bulk-загрузка SSTables, см. [Обслуживание](./operations.md)) и `COPY FROM` в cqlsh для CSV (см. [CQL](./cql-syntax.md)).

**Перед миграцией:** проверьте совместимость версий CQL/протокола и особенности (tablets vs vnodes, RBNO) — см. [Архитектуру](./architecture.md).

### Откат upgrade

Откат к предыдущей версии — downgrade по тому же rolling-принципу, но **только если новая версия не перезаписала SSTables** (`upgradesstables` не выполнен) и схема не изменена. Если `upgradesstables` выполнен — откат требует restore из бэкапа. Поэтому: снапшот перед upgrade обязателен.

**Cassandra:** upgrade 4.x → 5.0 — online upgrade (обратим до `upgradesstables`), в этом помогает `sstableupgrade`/`upgradesstables`. **Cassandra 3.x находится в EOL** (3.0/3.11) — прямого upgrade 3.11 → 5.0 нет, путь 3.11 → 4.0 → 5.0 (см. теорию в [Миграции: основы](../Concepts/migrations/migration_basics.md)). **ScyllaDB:** см. callout в сценарии rolling upgrade выше — downgrade только до тех пор, пока не все узлы апгрейжены.

## Валидация

| Что проверяем | Команда / сигнал | Ожидание |
| :--- | :--- | :--- |
| Версия на всех узлах | `nodetool version` | новая версия на всех узлах |
| Схема сошлась | `nodetool describecluster` | одна версия схемы |
| Кластер здоров | `nodetool status` | все узлы `UN` |
| SSTables обновлены | `nodetool upgradesstables` завершён | нет pending compaction (`nodetool compactionstats`) |
| Нагрузка в норме | мониторинг (см. [Мониторинг](./monitoring.md)) | latency/timeouts на уровне до upgrade |

## Поиск и устранение неисправностей

| Симптом | Вероятные причины | Действия |
| :--- | :--- | :--- |
| Узел не стартует после upgrade | удалённый параметр в конфиге, несовместимость | первая ошибка в логе; сверить конфиг с release notes (см. [Troubleshooting](./troubleshooting.md)) |
| Schema disagreement после upgrade | схема ещё распространяется по gossip | подождать; если не сходится — логи узлов с отличающейся версией схемы |
| `upgradesstables` зависает / долгий | большой объём SSTables | прогресс: `nodetool compactionstats`; throttling `nodetool setcompactionthroughput` |
| Ошибки чтения после частичного upgrade | SSTables в новом формате, а часть узлов старая | завершить rolling upgrade на всех узлах; `upgradesstables` — только после этого |
| Миграция Hydra медленная | недостаточно executors Spark, узкий канал | масштабировать Spark-кластер; throttling не выключать |
| Узел не стартует после ScyllaDB upgrade | не восстановлен `/etc/scylla.yaml` (опции removed/renamed), несовместимость пакетов | сверить конфиг с release notes; восстановить `.bak.upgrade`; первая ошибка — в `/var/log/scylla/scylla.log` (см. [Troubleshooting](./troubleshooting.md)) |
| Откат невозможен | `upgradesstables` выполнен на всех узлах / изменена схема | restore из snapshot, сделанного до upgrade (см. [Бэкап](./backup-recovery.md)) |

## Рекомендации

- **Бэкап (снапшот) перед каждым upgrade** — единственный надёжный откат после `upgradesstables`.
- **Один узел за раз**, дождаться `UN` перед следующим; не менять схему в процессе.
- **`upgradesstables` — после ВСЕХ узлов**, с throttling при работающей нагрузке.
- **Проверяйте матрицу upgrade-путей** в официальном guide перед планированием — не все переходы между мажорными версиями поддерживаются напрямую.
- **Cassandra → ScyllaDB:** ScyllaDB Hydra для данных; схему переносят отдельно (CQL DDL), проверяя совместимость типов и опций.
- **Теория миграций (expand/contract, rollback)** — [Миграции](../Concepts/migrations/migration_basics.md), [Expand-Contract](../Concepts/migrations/expand_contract.md).

## См. также

- **[Обслуживание и эксплуатация](./operations.md)** — rolling upgrade, drain, upgradesstables.
- **[Бэкап и восстановление](./backup-recovery.md)** — снапшот перед upgrade.
- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — различия при миграции.
- **[Troubleshooting](./troubleshooting.md)** — диагностика узла после upgrade.
- **[Миграции: основы](../Concepts/migrations/migration_basics.md)** — теория миграций БД.
