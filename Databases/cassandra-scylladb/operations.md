# Обслуживание и эксплуатация

**Актуально для:** Apache Cassandra 4.0/5.0.x / ScyllaDB 2026.x

## Определения

| Термин | Определение |
| :--- | :--- |
| Repair (anti-entropy) | Процесс синхронизации реплик через сравнение деревьев Меркла (Merkle trees) — выявляет и устраняет расхождения между копиями данных |
| Compaction | Процесс слияния SSTables: удаляет перезаписанные и удалённые строки, объединяет файлы, снижает read amplification |
| SSTable | Immutable файл данных на диске; записи сначала попадают в memtable (память) и commitlog, затем сбрасываются в SSTable при flush |
| Tombstone | Метка удаления; физически удаляется только после compaction и истечения `gc_grace_seconds` |
| gc_grace_seconds | Окно ожидания перед физическим удалением tombstone (дефолт 10 дней) — должно быть больше интервала между repair |
| Bootstrap | Добавление нового узла: потоковая передача данных для принадлежащих ему диапазонов токенов |
| Drain | Останов приёма записей и сброс memtables на диск — перед restart/upgrade |
| RBNO (Repair Based Node Operations) | ScyllaDB: node-операции (bootstrap, replace, rebuild, decommission, remove), использующие repair для потоковой передачи данных; включён по умолчанию с 5.4 |
| Cassandra Reaper | Внешний инструмент автоматизации repair (проект TheLastPickle), текущая версия 4.2.x |
| Scylla Manager (`scylla-manager`) | Официальный менеджер ScyllaDB: расписание repair и backup, repair-метрики; CLI `sctool` |
| sstableloader | Утилита bulk-загрузки SSTables из внешних файлов в кластер |

## Как работает обслуживание

**Путь записи:** commitlog (durability) → memtable (память) → SSTable (flush на диск). Memtable не сбрасывается на диск при каждой записи — только при заполнении или по `nodetool flush`.

**Зачем compaction:** SSTables immutable, поэтому обновления и удаления пишутся в новые файлы. Compaction сливает пересекающиеся SSTables, удаляет tombstones (после `gc_grace_seconds`) и перезаписанные строки, снижая количество файлов, которые нужно прочитать при запросе.

**Зачем repair:** hinted handoff покрывает только краткие отказы (часы), read repair — пассивен (срабатывает только на читаемых путях). Анти-энтропийный repair — единственный активный механизм полной синхронизации реплик. Каждый узел строит дерево Меркла (хеши диапазонов токенов), сравнивает с репликами и синхронизирует расходящиеся диапазоны.

**Инструменты:** **nodetool** (CLI, JMX), **scylla nodetool** (ScyllaDB 5.4+, нативная реализация, полностью совместима с legacy Java nodetool), **cqlsh** (Virtual Tables в Cassandra 5.0), **Cassandra Reaper** и **Scylla Manager** (автоматизация repair). Мониторинг состояния — в [Мониторинг и observability](./monitoring.md).

## SRE-практики: Репликация и согласованность

### Уровни согласованности (Consistency Levels)
Формула строгой согласованности: `R + W > RF`.

| Уровень | Запись | Чтение | Доступность | Использование |
| :--- | :--- | :--- | :--- | :--- |
| **ONE** | 1 реплика | 1 реплика | Максимальная | Кэши, логи, нетолерантные к stale reads |
| **TWO** | 2 реплики | 2 реплики | Высокая | Баланс между скоростью и надежностью |
| **QUORUM** | (RF/2)+1 | (RF/2)+1 | Средняя | Production-стандарт для большинства сценариев |
| **LOCAL_QUORUM** | кворум в локальном DC | кворум в локальном DC | Средняя (локально) | Геораспределенные кластеры |
| **LOCAL_ONE** | 1 реплика в локальном DC | 1 реплика в локальном DC | Высокая (локально) | Высокая доступность; данные могут быть stale |
| **EACH_QUORUM** | кворум в каждом DC | кворум в каждом DC | Низкая | Строгая согласованность между DC |
| **ALL** | Все реплики | Все реплики | Минимальная | Критичные данные, максимальная гарантия |

Полный список уровней (`ANY`, `THREE`, `SERIAL`, `LOCAL_SERIAL` — последние два только для LWT) — в [CQL: синтаксис](./cql-syntax.md).

**Рекомендации для Production:**
- **Запись:** `LOCAL_QUORUM` (золотой стандарт)
- **Чтение:** `LOCAL_QUORUM` или `ONE` (зависит от требований к свежести данных)
- **Высокая доступность:** `LOCAL_ONE` (но данные могут быть stale)

### Коэффициент репликации (Replication Factor, RF)
*   **Production:** `RF=3` (позволяет пережить отказ одного узла при `QUORUM`).
*   **Стратегия:** Всегда используйте `NetworkTopologyStrategy` для распределения данных по стойкам (Racks) и дата-центрам.

### Пример настройки Keyspace
```sql
CREATE KEYSPACE my_app WITH replication = {
    'class': 'NetworkTopologyStrategy', 
    'DC1': 3, 
    'DC2': 3
};
```

---

## Стратегии сжатия (Compaction Strategies)
Сжатие необходимо для объединения SSTables и удаления «надгробий» (Tombstones — меток удаления данных). Неправильный выбор стратегии — основная причина деградации производительности I/O. Детали тюнинга (tombstones, write amplification) — в [Тюнинг производительности](./performance.md).

1.  **STCS (SizeTieredCompactionStrategy):**
    *   **Принцип:** Объединяет SSTables схожего размера.
    *   **Плюсы:** Минимальная нагрузка на запись (Write Amplification).
    *   **Минусы:** Высокая нагрузка на чтение (Read Amplification), так как данные одной строки могут быть разбросаны по многим файлам. Требует до 50% свободного места на диске для работы.
    *   **Применение:** Тяжелая запись, логи, неизменяемые данные.

2.  **LCS (LeveledCompactionStrategy):**
    *   **Принцип:** Разделяет данные на уровни (L0, L1...). На уровнях L1+ SSTables имеют фиксированный размер и не пересекаются по ключам.
    *   **Плюсы:** Чтение требует обращения максимум к 1-2 файлам (кроме L0). Предсказуемое использование места (нужно ~10% запаса).
    *   **Минусы:** Высокая нагрузка на запись (постоянная пересортировка).
    *   **Применение:** Интенсивное чтение, частые обновления (Updates).

3.  **TWCS (TimeWindowCompactionStrategy):**
    *   **Принцип:** Группирует данные во временные окна. SSTables внутри окна сжимаются по STCS, после закрытия окна — не трогаются.
    *   **Плюсы:** Идеально работает с TTL. Целые файлы удаляются сразу после истечения срока хранения без дорогостоящего сжатия.
    *   **Применение:** Метрики, временные ряды, TTL-ориентированные данные.

**Общие параметры compaction** (значения по умолчанию, применимы ко всем стратегиям):

| Параметр | Дефолт | Назначение |
| :--- | :--- | :--- |
| `enabled` | `true` | Автоматический запуск compaction (управляется также через `nodetool enableautocompaction` / `disableautocompaction`) |
| `min_threshold` | `4` | Минимум SSTables для запуска minor compaction |
| `max_threshold` | `32` | Максимум SSTables в одной minor compaction |
| `tombstone_threshold` | `0.2` | Доля tombstones в SSTable, при которой он допускается к tombstone compaction |
| `tombstone_compaction_interval` | `86400s` (1 день) | Минимальный интервал между tombstone compaction одного SSTable |
| `unchecked_tombstone_compaction` | `false` | Разрешить tombstone compaction без проверки перекрытия с другими SSTables |
| `only_purge_repaired_tombstone` | `false` | Удалять tombstones только из repaired-данных (безопасность при incremental repair) |

**Утилита `sstableexpiredblockers`** — выводит, какие SSTables блокируют удаление полностью истёкших (только tombstones) SSTables. Полезна с TWCS: если TTL-данные не удаляются, причина обычно в старых SSTables с более ранними записями. Для TWCS есть опция `unsafe_aggressive_sstable_expiration` — снимает проверку перекрытия (применять только когда гарантировано, что данные не shadowing).

**Настройка Compaction:**
```sql
-- Установка стратегии при создании таблицы
CREATE TABLE logs (
    host text,
    timestamp timestamp,
    message text,
    PRIMARY KEY (host, timestamp)
) WITH compaction = {
    'class': 'TWCS',
    'compaction_window_unit': 'HOURS',
    'compaction_window_size': '1'
};

-- Изменение стратегии на существующей таблице
ALTER TABLE logs WITH compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': '160'
};
```

---

## Анти-энтропийное восстановление (Repair)
В децентрализованной системе данные могут рассинхронизироваться (из-за сбоев узлов или потери пакетов). Repair — процесс синхронизации реплик через сравнение деревьев Меркла.

**Типы Repair:**
- **Incremental Repair** (дефолт с Cassandra 4.0): обрабатывает только данные, помеченные как "unrepaired" с момента последнего запуска; SSTables разделяются на repaired и unrepaired наборы, которые компактятся отдельно. Быстрее, но требует регулярности — если запустить один раз и больше не запускать, старые repaired-данные будут блокировать удаление tombstones в более новых unrepaired SSTables.
- **Full Repair** (`--full`): сравнивает все данные между узлами. Создаёт высокую нагрузку на CPU/Disk.
- **Sub-range Repair** (`-st`/`-et`): запуск на подмножестве диапазонов токенов (для больших узлов и точечного восстановления).

### Cassandra: запуск Repair

```bash
# Проверка статуса последнего Repair (4.0+)
nodetool repair_admin summarize-repaired
# → самый свежий timestamp repaired-данных для диапазона (или всех replicated ranges)

# Доля repaired-данных — метрика PercentRepaired (см. [Мониторинг](./monitoring.md))

# Incremental repair keyspace (дефолт)
nodetool repair my_app

# Full repair конкретной таблицы
nodetool repair --full my_app user_events

# Primary range repair — только диапазлы, за которые узел является первичной репликой
nodetool repair -pr my_app

# Параллельный repair (до 4 job-потоков; больше — нагрузка на узел)
nodetool repair -j 4 my_app

# Preview: какие диапазлы и объём данных будут переданы, без выполнения
nodetool repair -prv my_app
```

**Опции `nodetool repair` (Cassandra 4.0/5.0):**

| Опция | Назначение |
| :--- | :--- |
| `-full` / `--full` | Полный repair всех SSTables (дефолт — incremental) |
| `-pr` / `--partitioner-range` | Только первый диапазон, возвращённый партиционером |
| `-local` / `--in-local-dc` | Только узлы в локальном DC |
| `-dc <dc>` / `--in-dc` | Конкретные DC |
| `-dcpar` / `--dc-parallel` | Repair DC параллельно |
| `-hosts <host>` / `--in-hosts` | Конкретные хосты |
| `-st` / `-et` | Начало (exclusive) и конец (inclusive) диапазона токенов |
| `-j <n>` / `--job-threads` | Потоков repair jobs (дефолт 1, макс 4) |
| `-seq` / `--sequential` | Последовательный repair |
| `-pl` / `--pull` | Односторонний repair: данные только из удалённого узла в этот |
| `-force` | Фильтровать недоступные узлы |
| `-iuk` | Игнорировать нереплицированные keyspaces (иначе repair упадёт) |
| `-prv` / `--preview` | Определить диапазлы и объём без выполнения |
| `-vd` / `--validate` | Проверить, что repaired-данные синхронны; расхождение → нужен full repair |
| `-tr` / `--trace` | Трассировка в `system_traces.events` |

**Управление incremental-сессиями (4.0+):** `nodetool repair_admin` — `list` (сессии, с `--all` — включая завершённые), `cancel --session <id>`, `cleanup` (удаление pending-данных завершённых сессий), `summarize-pending` (объём данных, ожидающих repair). В Cassandra 5.0 также `nodetool sstablerepairedset` — управление статусом repaired у SSTables.

**Auto-repair (Cassandra 5.0):** Unified Repair Solution (CEP-37) портирован в 5.0 как опциональный feature-flag `cassandra.autorepair.enable` (disabled by default) — автоматическое планирование repair.

### ScyllaDB: repair vs cluster repair

ScyllaDB разделяет repair по типу keyspace:

```bash
# Проверить тип keyspace (tablets включены или нет)
DESCRIBE KEYSPACE my_app

# vnode keyspaces (tablets отключены) — nodetool repair
nodetool repair -pr my_app

# tablet keyspaces (дефолт в новых кластерах) — nodetool cluster repair
nodetool cluster repair my_app

# Смешанный кластер: repair -pr на ВСЕХ узлах + cluster repair на ЛЮБОМ узле
nodetool repair -pr
nodetool cluster repair
```

- `nodetool repair` работает **только с vnode keyspaces**; на tablet keyspace завершается ошибкой `std::invalid_argument`
- `nodetool cluster repair` работает **только с tablet keyspaces**; опции: `--tablet-tokens` (выбор tablet по токену), `--incremental-mode disabled|incremental|full` (incremental repair для tablets — disabled по умолчанию), `keyspace`
- Опции `nodetool repair` (ScyllaDB): `-dc`, `-local`, `-hosts`, `-pr`, `-st`, `-et`, `keyspace`, `table`
- **Запускать регулярно** — чаще `gc_grace_seconds` (дефолт 10 дней), например еженедельно; `nodetool repair -pr` на каждом узле последовательно
- **Настоятельно не рекомендуется** выполнять во время repair операции обслуживания (add/remove/decommission/replace/rebuild) или изменения схемы (CREATE/DROP/TRUNCATE/ALTER) — repair в эти моменты с высокой вероятностью завершится ошибкой

### Автоматизация repair

**Cassandra Reaper** (TheLastPickle, текущая версия 4.2.x, активно поддерживается):
- Расписание и адаптивные графики repair, параллелизм, сегментация
- Метрики: percent-repaired, `unfulfilledRepairSchedule`, Prometheus-эндпоинт
- Поддержка Cassandra 4.0/5.0 и ScyllaDB; CLI `spreaper`

**Scylla Manager** (`sctool repair`):
- Repair-task создаётся автоматически при создании кластера (еженедельно); отдельная лёгкая **tablet repair task** (incremental, устойчива к изменениям топологии)
- `sctool repair --parallel` (параллелизм; по умолчанию full), `--intensity` (диапазонов на узел; дефолт 1, `0` — авто по памяти), `--window` (окно обслуживания), glob-паттерны для keyspaces/tables, retries, pause/resume
- Regular и tablet tasks параллельно только когда regular task использует `--keyspace-replication=vnodes`

**Best Practices:**
1.  **Регулярность:** Repair чаще, чем `gc_grace_seconds` (по умолчанию 10 дней), чтобы избежать воскрешения удалённых данных (Zombie data).
2.  **Инструменты:** Reaper (Cassandra) или Scylla Manager (ScyllaDB) для автоматизации. Запуск `nodetool repair` вручную на всём кластере сразу — риск отказа системы.
3.  **Команда:** `nodetool repair -pr` (Primary Range) — восстанавливает только данные, за которые узел является основным. Самый эффективный способ пройтись по всему кластеру, не выполняя лишнюю работу.
4.  **Window:** Запускайте Repair в часы минимальной нагрузки.

---

## Жизненный цикл узла (Node lifecycle)

Операции в Kubernetes (bootstrap, decommission, restart через оператор) — в [Развёртывание в Kubernetes](./kubernetes.md). Ниже — bare-metal.

**Добавление узла (bootstrap):** новый узел с `auto_bootstrap: true` (дефолт) автоматически получает свои диапазоны токенов (vnodes: `num_tokens`, дефолт 16 с Cassandra 4.0) и потоково загружает данные. После bootstrap на узлах, потерявших диапазлы, запустить `nodetool cleanup` — Cassandra/ScyllaDB **не удаляют данные автоматически** при изменении топологии.

**Удаление узла:**
```bash
nodetool decommission      # живой узел: данные стримятся с него самого
nodetool removenode <host_id>  # мёртвый узел: данные стримятся с оставшихся реплик
nodetool assassinate <ip>      # принудительное удаление по IP (крайний случай)
```
`removenode` без аргументов показывает статус текущего удаления; с ID — удаляет; `removenode force` завершает зависшее удаление. ScyllaDB: указывайте **host ID**, а не IP (IP deprecated для replace/remove).

**Замена узла (replace):** `nodetool replace` на новом узле с тем же IP/host ID — стримит данные вместо мёртвого узла. `replace_address` может использоваться и без bootstrap для восстановления узла с частично повреждённым диском (CASSANDRA-10134).

**Rebuild (новый DC):** `nodetool rebuild <source-dc-name>` — стримит данные из указанного DC (аналог bootstrap). ScyllaDB: только для vnode keyspaces; для tablets — `nodetool cluster repair`.

**Перемещение токенов:** `nodetool move <new_token>` — только при `num_tokens: 1` (иначе ошибка); эффективнее decommission+bootstrap; после move — `nodetool cleanup`. `nodetool relocate` (4.0+) — перенос конкретных диапазлов токенов.

**Drain перед restart/upgrade:**
```bash
nodetool drain   # остановить приём записей, сбросить memtables на диск
```

**Rolling restart** (по очереди, узел за узлом):
```bash
nodetool drain && sudo systemctl stop cassandra
# ...обновление конфигурации / перезагрузка ОС...
sudo systemctl start cassandra
# дождаться UN в nodetool status, затем следующий узел
```

**Rolling upgrade** (Cassandra/ScyllaDB): см. [Миграция и upgrade](./upgrade-migration.md#практические-сценарии) — drain → stop → upgrade пакетов → start → `UN` → повторить; `upgradesstables` — **только после upgrade всех узлов**. Флаги `upgradesstables` (`-j`, `-a`) и throttling — в [Обслуживании SSTables](#обслуживание-sstables).

**После topology-изменений** (bootstrap, move, replace, rebuild, decommission): `nodetool cleanup` на узлах, потерявших диапазлы — иначе старые данные продолжают занимать место и учитываться в load.

---

## Обслуживание SSTables

```bash
# Перезаписать SSTables в текущем формате версии (после upgrade, при смене
# опций сжатия или шифрования at-rest — вместо ожидания compaction)
nodetool upgradesstables my_app            # keyspace
nodetool upgradesstables -j 4 my_app       # 4 SSTable одновременно (0 = все compaction-потоки)
nodetool upgradesstables -a -- my_app      # включая уже в новом формате

# Поиск и исправление повреждённых SSTables
nodetool scrub -m VALIDATE my_app          # read-only: найти повреждения, карантин без исправления
nodetool scrub -m SEGREGATE my_app         # разобрать out-of-order строки/партиции в отдельные SSTables
nodetool scrub -m SKIP my_app              # пропустить повреждённые строки (риск потери данных!)
nodetool scrub -m ABORT my_app             # прервать на первой ошибке (дефолт)
nodetool dropquarantinedsstables my_app    # удалить помещённые в карантин SSTables

# Проверка контрольных сумм
nodetool verify my_app                     # быстрая проверка чексумм
nodetool verify -e my_app                  # расширенная: проверка данных каждой ячейки
nodetool verify -q my_app                  # quick: не читать все данные
nodetool verify -t my_app                  # проверить, что все токены в SSTables принадлежат узлу
nodetool verify -c my_app                  # проверить актуальность версии SSTables
nodetool verify -r my_app                  # изменить repair-статус повреждённых SSTables
nodetool verify -d my_app                  # вызвать disk failure policy при повреждении

# Удаление tombstones и перезаписанных ячеек (4.0+)
nodetool garbagecollect my_app             # гранулярность ROW (дефолт): удалённые партиции и строки
nodetool garbagecollect -g CELL my_app     # CELL: дополнительно перезаписанные/удалённые ячейки
nodetool garbagecollect -j 0 my_app        # 0 = все compaction-потоки

# Загрузка новых SSTables без restart
nodetool refresh my_app user_events        # ScyllaDB: из директории upload
nodetool import my_app user_events         # Cassandra 4.0+: refresh deprecated в пользу import (CASSANDRA-6719)

# Принудительная (major) compaction
nodetool compact my_app                    # major compaction keyspace
nodetool compact -s my_app                 # не создавать один большой файл
nodetool compact -st <t1> -et <t2> my_app  # диапазон токенов
nodetool compact --user-defined -- /path/to/sstables  # user-defined compaction конкретных файлов

# Сброс memtables на диск
nodetool flush my_app                      # конкретная keyspace/таблица

# Диагностика SSTables
nodetool sstabledump /path/to/sstable      # содержимое SSTable (JSON)
nodetool sstablemetadata /path/to/sstable  # метаданные SSTable
nodetool compactionhistory                 # история compaction
nodetool sstableexpiredblockers my_app     # какие SSTables блокируют удаление истёкших (TWCS)
```

**Режимы scrub:** `ABORT` (дефолт) — прервать на первой ошибке; `SKIP` — пропустить повреждённые строки/партиции (может вызвать потерю данных при сильном повреждении); `SEGREGATE` — отсортировать out-of-order данные в отдельные SSTables; `VALIDATE` — read-only, повреждённые SSTables перемещаются в поддиректорию `quarantine`. Режимы карантина: `INCLUDE` (дефолт), `EXCLUDE`, `ONLY`. Опция `--drop-unfixable-sstables` (только с `SEGREGATE`) — удалять неисправимые SSTables вместо прерывания.

**Рекомендуемый порядок при повреждении SSTable:** 1) `nodetool scrub -m VALIDATE` — идентифицировать и поместить в карантин; 2) восстановить из реплики или `nodetool repair`; 3) `nodetool dropquarantinedsstables` — удалить карантин. Альтернатива для out-of-order повреждений: `nodetool scrub -m SEGREGATE --drop-unfixable-sstables`.

---

## Пропускная способность (throttling)

Ограничение скорости операций, чтобы обслуживание не вытесняло продакшн-нагрузку (значения в Мбит/с; дефолты — в `cassandra.yaml`):

```bash
nodetool setstreamthroughput 100    # потоковая передача (bootstrap, repair, rebuild)
nodetool getstreamthroughput
nodetool setcompactionthroughput 16   # compaction
nodetool getcompactionthroughput
nodetool setrpcthroughput 100         # межузловой RPC (между DC)
nodetool getrpcthroughput
nodetool setbatchlogreplaythrottle 100  # replay batchlog
```

---

## Bulk-загрузка (sstableloader)

Загрузка SSTables из внешних источников (другой кластер, бэкапы, офлайн-генерация) без прохождения через commitlog/memtable:

```bash
sstableloader -d <node_ip> /path/to/sstables
```

Утилита потоково передаёт SSTables на нужные реплики по токенам. Подходит для начальной загрузки больших объёмов и миграции; для CSV — `COPY FROM` в cqlsh (см. [CQL: синтаксис](./cql-syntax.md)).

---

## Настройка gc_grace_seconds

```sql
-- Просмотр текущего значения
DESCRIBE TABLE user_events;
-- → gc_grace_seconds: 864000 (10 дней по умолчанию)

-- Уменьшение (только если Repair запускается чаще!)
ALTER TABLE user_events WITH gc_grace_seconds = 86400;  -- 1 день
```

---

## Управление схемой (schema management)

**Просмотр схемы:**

```bash
cqlsh -e "DESCRIBE SCHEMA;"              # полная схема кластера (DDL всех keyspaces)
cqlsh -e "DESCRIBE KEYSPACE my_app;"     # схема одной keyspace
nodetool describecluster                 # версия схемы на всех узлах (schema agreement)
```

**Практики:**

- **Схема в Git:** DDL (CREATE KEYSPACE/TABLE, ALTER TABLE) хранится в системе контроля версий и применяется через миграции — теория и инструменты (Flyway, Liquibase) — **[Миграции: основы](../Concepts/migrations/migration_basics.md)** и **[Миграции: практики](../Concepts/migrations/migration_practices.md)**
- **Schema agreement:** после `ALTER`/`CREATE` дождаться, пока все узлы получат новую версию схемы (`nodetool describecluster` — одна версия); во время распространения возможны временные расхождения
- **Изменения без простоя:** `ALTER TABLE` (добавление колонок, изменение опций) выполняется онлайн; опасные операции (DROP, TRUNCATE) — только после бэкапа
- **Не менять схему во время rolling upgrade** (см. [Миграция и upgrade](./upgrade-migration.md))

---

## Валидация операций

| Операция | Проверка успешности |
| :--- | :--- |
| Repair | `nodetool repair_admin summarize-repaired` (Cassandra 4.0+); метрика `PercentRepaired` (см. [Мониторинг](./monitoring.md)); Scylla Manager: `scylla_manager_repair_progress` |
| Compaction | `nodetool compactionstats` — нет pending; `nodetool tablestats` — снизилось число SSTables |
| Topology change | `nodetool status` — все узлы `UN`; после bootstrap/move/replace — `nodetool cleanup` выполнен |
| Upgrade | `nodetool version` — новая версия на всех узлах; `nodetool upgradesstables` завершён |
| Scrub/verify | В выводе нет ошибок; повреждённые SSTables в `quarantine` (scrub) |
| Drain | Команда завершается до остановки сервиса; в логах — flush memtables |

## Поиск и устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Repair завершается ошибкой «Repair session failed» | Сеть, диск, недоступные узлы | `nodetool status` (см. [Мониторинг](./monitoring.md)); повторить; ScyllaDB: не выполнять topology-операции во время repair |
| `nodetool repair` на tablet keyspace падает с `std::invalid_argument` | ScyllaDB: `nodetool repair` только для vnode keyspaces | `nodetool cluster repair` (проверить тип: `DESCRIBE KEYSPACE`) |
| Tombstones не удаляются после TTL | Старые SSTables с более ранними данными блокируют удаление | `nodetool sstableexpiredblockers`; repair; `only_purge_repaired_tombstone` |
| `nodetool scrub` прерывается (ABORT) | Повреждённые SSTables | `scrub -m VALIDATE` → восстановить из реплики/repair → `dropquarantinedsstables`; или `SEGREGATE` |
| Место на диске не освобождается после добавления узла | Данные старых диапазлов не удаляются автоматически | `nodetool cleanup` на узлах, потерявших диапазлы |
| `nodetool move` не работает | `num_tokens > 1` (vnodes) | `move` только при `num_tokens: 1`; иначе `nodetool relocate` (4.0+) |
| `nodetool refresh` не найден / deprecated | Cassandra 4.0+ | `nodetool import` (CASSANDRA-6719); ScyllaDB: `refresh` поддерживается |
| nodetool-команда зависает | JMX-порт/аутентификация | Проверить JMX (см. [Безопасность](./security.md)); `nodetool -h <host> -p <jmx_port>` |

## Рекомендации и очистка

**Календарь обслуживания (стартовая точка):**
- **Еженедельно:** repair (чаще `gc_grace_seconds`) — в окно минимальной нагрузки
- **Ежемесячно:** `nodetool scrub -m VALIDATE`, `nodetool verify` — проверка целостности SSTables
- **После upgrade:** `nodetool upgradesstables` на всех узлах
- **После topology-изменений:** `nodetool cleanup`

**Правила:**
- Обслуживание — в maintenance window; throttling (`setstreamthroughput`, `setcompactionthroughput`) при работающей нагрузке
- ScyllaDB: не совмещать repair с add/remove/decommission/replace/rebuild и изменениями схемы
- Scrub/verify создают снапшот по умолчанию (`--no-snapshot` отключает) — удаляйте старые снапшоты
- Мониторьте состояние во время операций (см. [Мониторинг](./monitoring.md))

**Очистка:**
```bash
nodetool clearsnapshot            # удалить все снапшоты (в т.ч. после scrub/verify)
nodetool clearsnapshot <tag>      # удалить снапшот с тегом
nodetool dropquarantinedsstables my_app   # удалить карантинированные SSTables
```
Reaper: purge старых repair runs (настройка retention). Scylla Manager: автоматическая очистка завершённых repair-задач.

**Откат изменений:** compaction-стратегию и `gc_grace_seconds` меняют через `ALTER TABLE` (обратимо); topology-операции (decommission, replace) необратимы — перед ними снапшот (см. [Бэкап и восстановление](./backup-recovery.md)).

---

## См. также
- **[CQL: синтаксис и примеры](./cql-syntax.md)** — запросы, BATCH, LWT.
- **[Тюнинг производительности](./performance.md)** — Tombstones, антипаттерны.
- **[Мониторинг и observability](./monitoring.md)** — метрики Compaction и Repair, nodetool.
- **[Бэкап и восстановление](./backup-recovery.md)** — снапшоты, restore.
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — диагностика кластера.
- **[Развёртывание в Kubernetes](./kubernetes.md)** — операции через оператор.
- **[Безопасность](./security.md)** — JMX-аутентификация для nodetool.
- **[Архитектура](./architecture.md)** — vnodes vs tablets.
