# Neo4j: Обслуживание и эксплуатация

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS

## Определения

| Термин | Значение |
| :--- | :--- |
| **DBMS** | Экземпляр Neo4j, управляющий одной или несколькими базами данных. |
| **Page cache** | Кэш в RAM, в котором хранятся store-файлы графа и индексы для быстрого чтения. |
| **Checkpoint** | Момент в логе транзакций, начиная с которого возможно восстановление после сбоя. |
| **Transaction log (WAL)** | Журнал упреждающей записи всех изменений; используется для crash recovery и PITR. |
| **Store files** | Бинарные файлы на диске, содержащие узлы, связи, свойства и индексы графа. |
| **Heap** | Память JVM для Java-объектов Neo4j (планы запросов, состояние транзакций). |
| **Off-heap** | Память, выделенная напрямую из ОС, минуя GC: сетевые буферы, состояние транзакций. |
| **Causal consistency** | Гарантия, что все серверы кластера согласованы по порядку транзакций. |

## Базовые понятия: процесс, служба, жизненный цикл

Neo4j работает как отдельный процесс JVM, управляемый через `systemd` (юнит `neo4j.service`). Процесс читает конфигурацию из `neo4j.conf`, открывает служебную базу `system` и одну или несколько пользовательских баз. При старте движок replay'ит незавершённые транзакции из WAL, после чего сервер принимает подключения на Bolt (7687) и HTTP (7474).

**Жизненный цикл одной транзакции:**
1. Клиент отправляет Cypher через Bolt.
2. Парсер проверяет права, планировщик строит план.
3. План исполняется: читаются страницы из page cache или диска.
4. Изменения пишутся в transaction log (WAL).
5. При `COMMIT` запись в WAL подтверждается, Transaction ID назначается.
6. Checkpoint периодически сбрасывает отложенные страницы из page cache в store-файлы.
7. После checkpoint старые transaction logs можно удалить.

## Предварительные требования

- **ОС:** Linux с systemd (Ubuntu 22.04/24.04 LTS, RHEL/Rocky 9+)
- **Java:** OpenJDK 21 (включён в пакет Neo4j)
- **Память:** минимум 2 ГБ RAM, рекомендуется 8+ ГБ для production
- **Диск:** минимум 10 ГБ свободного места; SSD рекомендуется для write-heavy нагрузок
- **Сеть:** Bolt (7687), HTTP (7474), HTTPS (7473) — по умолчанию слушает только `localhost`
- **Пользователь:** сервер работает от имени системного пользователя `neo4j`

## Файловая структура и каталоги

Пути зависят от способа установки. Для пакетов Debian/RPM:

| Каталог | Назначение | Параметр |
| :--- | :--- | :--- |
| `/etc/neo4j` | `neo4j.conf`, certificates | `server.directories.conf` |
| `/var/lib/neo4j/data` | Store-файлы, transaction logs | `server.directories.data` |
| `/var/lib/neo4j/logs` | `neo4j.log`, `debug.log`, `query.log` | `server.directories.logs` |
| `/var/lib/neo4j/plugins` | APOC, GDS, пользовательские плагины | — |
| `/var/lib/neo4j/certificates` | TLS-сертификаты Bolt и HTTPS | — |
| `/var/lib/neo4j/metrics` | CSV-метрики (если включены) | `server.directories.metrics` |
| `/var/lib/neo4j/import` | `LOAD CSV` — только отсюда | `server.directories.import` |

Для tar.gz и Docker пути относительно `<NEO4J_HOME>`:

| Каталог | Назначение |
| :--- | :--- |
| `<NEO4J_HOME>/conf` | Конфигурация |
| `<NEO4J_HOME>/data` | Данные и логи |
| `<NEO4J_HOME>/logs` | Журналы |
| `<NEO4J_HOME>/plugins` | Плагины |

Проверить фактическое расположение изнутри сервера:

```cypher
CALL dbms.listConfig()
YIELD name, value
WHERE name IN ['server.directories.logs','server.directories.data','server.directories.conf']
RETURN name, value
```

## Управление памятью

### Слои памяти процесса Neo4j

Neo4j не «занимает кусок RAM» — память расходуется по нескольким независимым слоям, и ошибка в
одном слое маскирует проблему в другом. Полный перечень:

| Слой | Назначение | Управление |
| :--- | :--- | :--- |
| **OS memory** | Процессы ОС, файловый кэш ядра | Нельзя задать явно — это остаток после остальных слоёв |
| **JVM heap** | Java-объекты Neo4j: план запроса, состояние транзакций, кэш запросов | `server.memory.heap.initial_size` / `.max_size` |
| **Native (off-heap)** | Прямые выделения мимо GC: сетевые буферы, off-heap состояние транзакций | `dbms.tx_state.max_off_heap_memory` |
| **DBMS** | Глобальные компоненты: Bolt server, сервис логирования, метрик | `server.bolt.thread_pool_max_size` и др. |
| **Database** | Накладные расходы на каждую базу в мультидатасетной конфигурации | Учитывается вручную |
| **Transaction** | Незакоммиченные данные, результат, промежуточные состояния запроса | `dbms.memory.transaction.total.max` |
| **Page cache** | Кэш store-файлов и индексов | `server.memory.pagecache.size` |
| **Network buffers** | Прямые byte-буферы для приёма/отправки данных | Размер фиксирован, буферы переиспользуются |
| **JVM overhead** | Thread stacks, Metaspace, Code cache | Через параметры JVM |

Ключевое различие: **page cache — не часть кучи**. Данные графа и индексы читаются через page
cache напрямую с диска, минуя JVM heap. Из этого следует практическое правило: если `MATCH` идёт
долго, а heap пуст — проблема в page cache, и наоборот.

### Слои конфигурации

В Neo4j 5 пространства имён параметров отражают их область действия, и это важно при правке
кластера:

- `server.*` — только для конкретного сервера, может различаться между серверами кластера;
- `dbms.*` и `db.*` — должны быть **одинаковы во всех** `neo4j.conf` кластера;
- `initial.*` — действуют только при инициализации.

> Перенос параметра из пространства `dbms.*` в `server.*` (или наоборот) — смысловая ошибка, а не
> стилистическая: значение либо станет применяться только к одному серверу, либо перестанет
> применяться вовсе.

### Расчёт памяти: `memory-recommendation`

Neo4j не требует подбирать доли RAM вручную. Встроенная команда измеряет реальные объёмы
store-файлов и индексов и выдаёт рекомендацию:

```bash
neo4j-admin server memory-recommendation
```

```
# Total size of lucene indexes in all databases: 6690m
# Total size of data and native indexes in all databases: 17050m
```

В выводе различаются **два независимых объёма**, и их нельзя складывать:

- **data and native indexes** — store-файлы и нативные индексы. Это то, что обслуживает
  `server.memory.pagecache.size`.
- **lucene indexes** — полнотекстовые индексы. Они хранятся иначе и не занимают page cache.

Полная рекомендация состоит из нескольких строк (heap, page cache, запас), сгенерированных
командой. Дальше значения корректируются под конкретную нагрузку.

### Правила выбора значений

**1. Всегда задавайте `initial_size` равным `max_size`.** Это официальная рекомендация. Разные
значения заставляют JVM расширять кучу в рантайме, и каждый expand — это Full GC на всё
процессорное время. Кроме того, после expand куча никогда не сжимается обратно, поэтому
одноразовый всплеск памяти навсегда поднимает планку.

```conf
# Always set initial and max to the same value
server.memory.heap.initial_size=4G
server.memory.heap.max_size=4G
```

**2. Page cache = размер данных и нативных индексов + 20% на рост.** Официальная формула
capacity planning:

```
server.memory.pagecache.size = 1.2 * (объём data + native indexes)
```

Для примера выше: `1.2 * 17 050m ≈ 20G`.

```conf
server.memory.pagecache.size=20G
```

**3. Под ОС оставляйте хотя бы 1 ГБ**, и тем больше, чем больше RAM на сервере — на серверах с
большим объёмом памяти доля ОС может быть существенно больше гигабайта. Если ОС не хватает, она
начинает свопить, а своп для выделенного сервера Neo4j означает катастрофическую
деградацию.

**4. Никогда не задавайте page cache равным всему объёму памяти.** Оставьте запас минимум на
heap и ОС — иначе GC не сможет расширить кучу под нагрузкой.

**5. Отключите swap на выделенном сервере:**

```conf
# In /etc/fstab — comment out or remove the swap entry for the data partition
# /dev/swapfile none swap sw 0 0
```

```bash
sudo swapoff -a
```

### Лимиты памяти транзакций

Отдельный от heap механизм ограничивает суммарную память транзакций, не затрагивая саму базу.
При достижении лимита завершается **только** транзакция — здоровье базы не страдает.

| Параметр | Область действия |
| :--- | :--- |
| `dbms.memory.transaction.total.max` | Глобальный лимит на все транзакции сервера |
| `db.memory.transaction.total.max` | Лимит на одну базу |
| `db.memory.transaction.max` | Лимит на одну транзакцию |
| `dbms.tx_state.max_off_heap_memory` | Бюджет off-heap состояния транзакций |

```conf
# Cap total transaction memory; prevents OOM under heavy transactional load
dbms.memory.transaction.total.max=2G
```

Текущее потребление видно в рантайме:

```cypher
CALL dbms.listPools()
SHOW TRANSACTIONS
```

> Эти лимиты — защита от OOM, а не способ ускорить систему. Если транзакция упирается в лимит,
> сначала ищите запрос, который её вызывает: обычно это `UNWIND` по очень большому списку или
> раскрытие переменной длины, где один и тот же объект учитывается многократно. Оценка
> используется, поэтому способна ошибаться в обе стороны.

### Docker: память в контейнере

В Docker те же параметры задаются переменными окружения, где точка заменяется на
подчёркивание:

```yaml
services:
  neo4j:
    image: neo4j:2026.09.0-enterprise
    environment:
      - NEO4J_server_memory_heap_initial__size=4G
      - NEO4J_server_memory_heap_max__size=4G
      - NEO4J_server_memory_pagecache_size=12G
    mem_limit: 20g
```

**`mem_limit` должен превышать сумму heap + page cache с запасом** — ровно на ту же величину,
которую вы оставили ОС. Урезанный лимит памяти контейнера не вызывает ошибки конфигурации:
Neo4j стартует, а упирается в OOM Kill уже под нагрузкой, где диагностика hardest всего.

## Checkpointing и транзакционные журналы

Checkpoint — это момент в логе транзакций, начиная с которого возможно восстановление после
сбоя. Процесс сбрасывает отложенные страницы из page cache в store-файлы, после чего старые
транзакционные журналы можно удалить. Именно checkpoint, а не размер базы, определяет, как долго
сервер восстанавливается после падения.

### Политика checkpoint

| Политика | Описание |
| :--- | :--- |
| `PERIODIC` | По умолчанию. Срабатывает при достижении `db.checkpoint.interval.tx` **или** `db.checkpoint.interval.time` |
| `VOLUME` | Срабатывает при достижении `db.checkpoint.interval.volume` |
| `CONTINUOUS` | Enterprise Edition. Игнорирует интервальные параметры, работает постоянно |
| `VOLUMETRIC` | Enterprise Edition. Подбирает частоту так, чтобы не отставать от `db.tx_log.rotation.retention_policy` |

```conf
# Checkpoint every 10 minutes or every 50000 transactions, whichever comes first
db.checkpoint=PERIODIC
db.checkpoint.interval.time=10m
db.checkpoint.interval.tx=50000
```

Дефолты: `db.checkpoint.interval.time=15m`, `db.checkpoint.interval.tx=100000`,
`db.checkpoint.interval.volume=250.00MiB`.

### Лимит IOPS и буфер сброса

Checkpoint конкурирует с коммитами за полосу записи. Поэтому по умолчанию он ограничен
600 IOPS (одна IO — это 8 KiB последовательной записи), оставляя остальную полосу под случайные
чтения, важные для отклика на запросы, когда база не помещается в память:

| Параметр | По умолчанию | Комментарий |
| :--- | :--- | :--- |
| `db.checkpoint.iops.limit` | `600` | `-1` снимает ограничение полностью |
| `server.memory.pagecache.flush.buffer.enabled` | выкл. | Батчевая запись, дружественная к размеру блока диска |
| `server.memory.pagecache.flush.buffer.size_in_pages` | — | Размер батча в страницах |

```conf
# Only if there is IOPS budget headroom; raising it slows down commits
db.checkpoint.iops.limit=1200
```

Параметр advisory: в Community Edition он игнорируется, в Enterprise соблюдается по мере
возможностей. Компромисс односторонний — ниже лимит, короче checkpoint, но дольше recovery
после сбоя.

**Диагностика.** Ключевой признак недонастроенного checkpoint — рост числа файлов
транзакционного журнала. Отслеживайте метрику длительности checkpoint: если она приближается к
интервалу между checkpoint'ами, следующий checkpoint не успевает завершиться до начала
следующего, и логи копятся неограниченно.

### Ротация и хранение журналов

```conf
# One transaction log file per 256 MiB
db.tx_log.rotation.size=256MiB
# Keep logs from the last 7 days, within 4G total
db.tx_log.rotation.retention_policy=7 days 4G
```

Допустимые типы ограничения: `files`, `size`, `txs`, `entries`, `hours`, `days`, плюс
необязательное ограничение объёма. `db.tx_log.rotation.retention_policy=false|keep_none`
оставляет только последний непустой лог, `true|keep_all` хранит все.

**Размер retention policy ограничивает глубину point-in-time recovery и длину цепочки
дифференциальных бэкапов.** Журналы, удалённые раньше, чем появился нужный бэкап, делают
восстановление на эту точку невозможным. Увеличение окна хранения — это одновременно и
увеличение допустимого RPO, и рост потребления диска.

## Управление службой и ограничения ресурсов

### systemd: юнит и основные команды

Neo4j поставляется с юнитом `neo4j.service`. Стандартное управление:

```bash
sudo systemctl start neo4j
sudo systemctl stop neo4j
sudo systemctl restart neo4j
sudo systemctl status neo4j
```

Проверка работоспособности:

```bash
# HTTP-ответ от сервера
curl -s http://localhost:7474
# → {"bolt_routing":"neo4j://localhost:7687","transaction":"http://localhost:7474/db/{databaseName}/tx",...}

# Cypher-проверка
echo "RETURN 1 AS test;" | cypher-shell -u neo4j -p <password>
# → +------+
#    | test |
#    +------+
#    | 1    |
#    +------+
```

### Корректная остановка (graceful shutdown)

Остановка выполняется через службу или сигнал процессу — специальной настройки «выключить сервер» в Neo4j нет. Механизм остановки дожидается завершения активных транзакций, и на это есть отдельный параметр:

```properties
# neo4j.conf
db.shutdown_transaction_end_timeout=10s
```

Значение по умолчанию — **10 секунд**: это максимальное время ожидания завершения работающих транзакций перед тем, как инициированная остановка базы продолжится. Если в момент остановки висит длинная транзакция, она будет прервана по истечении этого срока.

```bash
# Корректная остановка: дождаться завершения транзакций
sudo systemctl stop neo4j

# Проверить, что перед остановкой не осталось длинных транзакций
echo "SHOW TRANSACTIONS YIELD transactionId, elapsedTime, currentQuery RETURN transactionId, elapsedTime LIMIT 10;" \
  | cypher-shell -u neo4j -p <password>
```

Два смежных параметра:

- `server.panic.shutdown_on_panic` — управляет тем, завершается ли процесс при аварии сервера (невосстановимой ошибке) или продолжает работать. После panic значительная часть функциональности обычно потеряна.
- `db.lock.acquisition.timeout` — сколько запрос ждёт блокировку; при остановке этот параметр стоит держать меньше `db.shutdown_transaction_end_timeout`, иначе остановка будет упираться в таймауты блокировок.

В кластере остановка одного сервера безопасна, если кворум сохраняется; порядок вывода серверов из кластера — в [кластеризации](./clustering.md).

### Жёсткая изоляция службы (systemd hardening)

Для выделенного сервера рекомендуемые флаги в `/etc/systemd/system/neo4j.service`:

```ini
[Service]
User=neo4j
Group=neo4j
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
RestrictNamespaces=true
LockMemory=true
LimitNOFILE=65536
```

`LockMemory` требует отключения overcommit в ОС:

```bash
echo 0 | sudo tee /proc/sys/vm/overcommit_memory
```

> **Внимание:** `LockMemory` и отключенный overcommit — условие работы `mlockall` в JVM, которое
> предотвращает своппинг heap'а. Без этого страницы кучи могут быть выгружены на диск, что
> приводит к паузам в десятки секунд.

### Ограничения открытых файлов

Neo4j держит открытыми store-файлы, сокеты и journal-файлы. Минимум:

```bash
# Проверить текущий лимит
sudo systemctl show neo4j | grep LimitNOFILE
# → LimitNOFILE=65536

# Установить в юните
sudo systemctl edit neo4j
# → [Service]
#   LimitNOFILE=65536
```

### Файловые системы и монтирование

- **EXT4 и XFS** поддерживаются официально. XFS может дать прирост до 10 % на отдельных
  workloads, но расходует до 2× больше дискового пространства против EXT4, поэтому
  **официально рекомендуется EXT4**.
- **NFS и NAS не поддерживаются и не рекомендуются** в качестве хранилища базы данных.
  Обоснование то же, что и у файловых систем: база создаёт высокую и длительную нагрузку на
  хранилище, и поведение сетевой ФС на таких паттернах не отвечает требованиям.
- **Разделяйте устройства:** база данных и журналы транзакций рекомендуется размещать на
  разных физических устройствах — запросы дают много мелких случайных чтений, коммиты —
  мало последовательных записей.
- **Монтирование:** `noatime,nodiratime` — отключение обновления времени доступа к файлам
  и каталогам, убирает лишние записи метаданных и улучшает производительность записи.
- **Inode density:** на стандартном XFS inode хватает; при импорте десятков миллионов узлов
  проверьте `-i` параметр.
- **SSD:** рабочий набор должен помещаться в RAM — это первая линия защиты от износа SSD.
  При высокой доле записи помогает over-provisioning: SSD объёмом минимум на 20 % больше
  фактически необходимого.
- **Квота:** ограничьте место под `data/transactions` отдельной квотой — это защита от
  заполнения диска при сбое checkpoint.

```bash
# Пример /etc/fstab
/dev/vg0/neo4j-data /var/lib/neo4j/data ext4 noatime,nodiratime 0 2
```

Требования к хранилищу в Kubernetes описаны отдельно — см. [Kubernetes](./kubernetes_deployment.md#хранилище-тип-тома-определяет-пригодность).

### Очистка и ротация

- **Логи:** ротация по размеру (20 MB) и количеству (7 файлов) настроена в `user-logs.xml`.
- **Метрики CSV:** ротация 30 секунд, 7 файлов, 10 MiB на файл, ZIP-сжатие.
- **GC-логи:** включаются отдельно, ротируются параметрами JVM.

```bash
# Принудительная ротация логов
sudo systemctl kill --signal=SIGUSR1 neo4j
```

## Диагностика

> Диагностика по одному источнику почти всегда даёт неполную картину. Форматы, уровни и разбор
> записей журналов — в [мониторинге](./monitoring.md), проверка целостности и процедуры отката —
> в [бэкапе и восстановлении](./backup_and_restore.md). Здесь — запросы и проверки, которые
> выполняются на живой базе.

### Текущая активность

```cypher
-- Longest running transactions and queries
SHOW TRANSACTIONS
YIELD transactionId, currentQuery, elapsedTime, status, currentQueryAllocatedBytes, pageFaults
RETURN transactionId, elapsedTime, currentQueryAllocatedBytes, pageFaults, status, currentQuery
ORDER BY elapsedTime DESC
LIMIT 10;
```

```cypher
-- Memory pools: shows which database consumed the transaction memory budget
CALL dbms.listPools()
```

Прерывание выполняется управляющими командами, а не процедурами `dbms.killTransaction`, которые
удалены начиная с Neo4j 5:

```cypher
-- Terminate one transaction
SHOW TRANSACTIONS
YIELD transactionId AS txId
TERMINATE TRANSACTION txId
YIELD message
RETURN txId, message;
```

Для этого нужна привилегия `TERMINATE TRANSACTION`; на просмотр — `SHOW TRANSACTION`.

### Проверка конфигурации на работающем сервере

```cypher
-- Effective values of the checkpointing settings
SHOW SETTINGS
YIELD name, value
WHERE name STARTS WITH 'db.checkpoint'
RETURN name, value
ORDER BY name;
```

```plain
+---------------------------------+-----------+------------------+
| name                            | value     | message          |
+---------------------------------+-----------+------------------+
| "db.checkpoint"                 | "PERIODIC"| "requires restart" |
| "db.checkpoint.interval.time"   | "15m"     | "requires restart" |
| "db.checkpoint.interval.tx"     | "100000"  | "requires restart" |
| "db.checkpoint.interval.volume" | "250.00MiB"| "requires restart" |
| "db.checkpoint.iops.limit"      | "600"     | ""               |
+---------------------------------+-----------+------------------+
```

Колонка `message` показывает, что изменение потребует перезапуска. Валидация значения:

```cypher
SHOW SETTINGS
YIELD name, value
WHERE name STARTS WITH 'db.checkpoint'
CALL dbms.checkConfigValue(name, value)
YIELD valid, message
RETURN name, value, valid, message;
```

`SHOW SETTINGS` возвращает настройки **того сервера**, к которому подключён клиент. Чтобы
проверить конкретный узел кластера, подключайтесь к нему напрямую по `bolt://`.

### Кэш запросов

```cypher
-- Drop cached plans; needed after a plan-invalidating change, e.g. obfuscate_literals
CALL db.clearQueryCaches()
```

```bash
# Transaction log volume — a growing count means checkpoints are falling behind
du -sh /var/lib/neo4j/data/transactions/

# Database size
du -sh /var/lib/neo4j/data/databases/neo4j/

# Listening ports
ss -tlnp | grep -E '7687|7474|6362|2004'
```

### Проверка состояния файлов

```bash
# Целостность store-файлов (работает в Community)
neo4j-admin database check neo4j

# Проверка бэкапа без восстановления
neo4j-admin database check --from-path=/backups/neo4j/ neo4j

# Информация о формате хранения
cypher-shell -u neo4j -p <password> "SHOW DATABASES YIELD name, store RETURN name, store"
```

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **OOM Kill процесса** | Сервер исчезает без записи в лог | `mem_limit` контейнера или RAM меньше суммы heap + page cache + ОС | Увеличьте память; сверьтесь с `memory-recommendation`. Логи контейнера: `docker logs` |
| **`OutOfMemoryError` в heap** | Запрос падает, база жива | Запрос или транзакция превышает лимит | Проверьте `SHOW TRANSACTIONS` по `currentQueryAllocatedBytes`; снизьте `dbms.memory.transaction.total.max`, чтобы отсечь виновника раньше; включите `gc.log` |
| **Медленные запросы** | Высокий `DbHits` в PROFILE, `planning` близок к общему времени | Индекс не используется либо план не кэшируется | См. [оптимизацию запросов](./query_optimization.md). Разделить текст запроса и параметры — планы переиспользуются |
| **`Transaction rolled back`** | Транзакция откатывается | Долгая транзакция, contention, превышен лимит памяти | Уменьшить батч, `CALL { } IN TRANSACTIONS`; проверить `waiting` в `query.log` |
| **Page cache hit ratio падает** | Медленные чтения, растёт `page faults` | `usage_ratio` близок к 1.0 | Увеличить `server.memory.pagecache.size` по формуле `1.2 * (данные + индексы)` |
| **Растёт число файлов журнала** | Диск заполняется `data/transactions` | Checkpoint не успевает за коммитами | Поднять `db.checkpoint.iops.limit`; перейти на более частые checkpoint'ы или `CONTINUOUS` |
| **Рост `neo4j.log` без событий** | Лог растёт, нагрузки нет | Избыточный уровень логирования, не ротируется | Проверить размер ротации в `user-logs.xml`; снизить `Root level` до `WARN` |
| **`Connection refused` на 7687** | Клиенты не подключаются | Сервис остановлен, порт занят | `systemctl status neo4j`, `ss -tlnp \| grep 7687` |
| **`Authentication rate limit` при старте** | Массовые отказы входа | Слишком частые попытки | `dbms.security.auth_enabled` и лимиты входа; см. [безопасность](./security.md) |
| **Данные не видны** | `MATCH (n) RETURN n` пуст | Открыта другая база | `SHOW DATABASES`, затем `USE database_name` |
| **Restore не находит цепочку** | Ошибка `not found` | Полный и дифференциальный бэкапы в разных папках | Поместить всю цепочку в одну директорию; проверить `--inspect-path` |
| **После restore базы нет в `SHOW DATABASES`** | Каталоги на диске есть, базы нет | Не выполнен `CREATE DATABASE` | Выполнить `CREATE DATABASE mydatabase` в `system` |
| **Нет входа после restore** | Данные на месте, аутентификация не работает | Не применён `restore_metadata.cypher` | Выполнить скрипт в базе `system` |
| **`sample_limit exceeded`** | Prometheus жалуется на объём | Слишком много серий (много баз, кардинальность лейблов) | Увеличить `sample_limit` либо отключить метрики высокой кардинальности |

### Чек-лист эксплуатации

**Память**
- [ ] `server.memory.heap.initial_size` равен `server.memory.heap.max_size`
- [ ] `server.memory.pagecache.size` ≥ 1.2 × (данные + нативные индексы) по `memory-recommendation`
- [ ] `page_cache_usage_ratio` не достигает 1.0
- [ ] `page_cache_hit_ratio` выше 0.98 устойчиво
- [ ] Swap выключен на выделенном сервере
- [ ] `mem_limit` контейнера выше суммы heap + page cache с запасом

**Checkpoint и журналы**
- [ ] `db.checkpoint.iops.limit` соответствует IOPS-бюджету диска
- [ ] Длительность checkpoint не приближается к интервалу между checkpoint'ами
- [ ] `data/transactions` не растёт со временем
- [ ] `db.tx_log.rotation.retention_policy` покрывает требуемое окно PITR

**Бэкап**
- [ ] Бэкап выполняется от пользователя `neo4j`
- [ ] Полный и дифференциальный бэкапы лежат в одной директории
- [ ] `--temp-path` указывает на диск с запасом
- [ ] Ротация старых артефактов настроена
- [ ] Восстановление проверено на изолированном стенде не реже, чем раз в период максимального интервала бэкапов
- [ ] `neo4j-admin database check` на последнем бэкапе проходит
- [ ] `restore_metadata.cypher` отрабатывает, пользователи и роли восстановлены

**Метрики и логи**
- [ ] `server.metrics.prometheus.endpoint` не слушает наружу без прокси с TLS
- [ ] Мониторингятся `hit_ratio`, `usage_ratio`, `heap_used`, `check_point_duration`, `last_committed_tx_id`
- [ ] `db.logs.query.enabled=INFO` с осмысленным `db.logs.query.threshold`
- [ ] Ротация логов настроена, объём `query.log` под контролем
- [ ] Свободное место отслеживается на всех носителях, куда пишет Neo4j

**Запросы**
- [ ] Свойства в `WHERE` проиндексированы, направление связей указано
- [ ] Параметры вместо хардкода — планы переиспользуются
- [ ] `DbHits` типичных запросов в ожидаемом диапазоне
- [ ] Нет запросов, удерживающих блокировки дольше нескольких сотен миллисекунд

## Ограничения и крайние случаи

- **Векторные индексы** (Enterprise) загружаются в OS memory, а не в page cache. При наличии
  векторного поиска зарезервируйте для ОС дополнительную память.
- **Checkpoint IOPS limit advisory:** в Community Edition параметр игнорируется; в Enterprise
  соблюдается по мере возможностей. Это означает, что на Community tuning checkpoint'а
  ограничивается только изменением интервалов.
- **Page cache hit ratio vs usage ratio:** низкий `hit_ratio` означает «много промахов», но
  `usage_ratio = 1.0` — это прямая рекомендация увеличить page cache, причём до того, как
  производительность упадёт. Мониторить нужно обе метрики.
- **Дифференциальные бэкапы несамостоятельны:** восстановление требует наличия полного
  артефакта в той же директории. Разделение цепочки по разным путям делает восстановление
  невозможным.
- **`last_committed_tx_id` как метрика живости:** в кластере должна быть одной непрерывно
  растущей линией. Если одна из линий вышла на плато или отстаёт, экземпляр перестал
  реплицировать данные.
- **Store format migration:** переход на `block` формат (рекомендуемый для EE) — операция офлайн,
  I/O-интенсивна (100 ГБ — от 10 минут до более часа), требует места примерно на один размер
  базы и пересоздаёт индексы при первом старте.
- **Transaction memory estimation:** оценка heap'а транзакций — это conservative estimate;
  `UNWIND` по большому списку или раскрытие переменной длины могут привести к overestimation.
  Если запрос завершается с `OutOfMemoryError` при низком потреблении, попробуйте отключить
  лимит на тестовом стенде.

## Лучшие практики

- **Задавайте память явно, не полагаясь на эвристику.** Без явных `server.memory.*` Neo4j
  вычисляет значения сам при старте, и результат меняется от версии к версии. Явная конфигурация
  делает поведение предсказуемым при обновлении.
- **Не меняйте `initial_size` и `max_size` по отдельности.** Расхождение означает Full GC на
  каждом расширении кучи.
- **Отключайте `VERBOSE` на нагруженных базах.** Переходите на `INFO` с порогом — вы получите
  те же ответы на вопрос «что тормозит» при многократно меньшем объёме.
- **Держите `query.log` и `security.log` включёнными, но не оставляйте `security.log` в режиме
  «все успешные входы»** при большом потоке приложений: `dbms.security.log_successful_authentication=false`
  оставляет только неуспешные попытки.
- **Не выставляйте эндпоинт метрик в сеть.** Порт 2004 не аутентифицирован.
- **Бэкап проверяйте, а не только создавайте.** Главный индикатор здоровья бэкап-системы —
  не наличие файлов, а прошедшие успешно restore-тесты.
- **Восстанавливайте в новую базу, а не поверх существующей** — так проверка не зависит от
  боевого окружения, а исходная база остаётся доступной для сравнения.
- **Планируйте миграцию формата как операцию с окном простоя**, а не как фоновую задачу.
- **Используйте метки транзакций.** `tx.setMetaData({app: ..., type: ...})` кладёт в `query.log`
  имя приложения, и поиск источника нагрузки становится точным, а не приблизительным.
- **Фиксируйте `neo4j.conf` в репозитории.** Конфигурация — часть состояния системы; её
  воспроизводимость важнее её удобства редактирования на месте.

## См. также

- **[Обзор Neo4j](./overview.md)** — редакции и лицензии, версии и поддержка, модель данных, форматы хранения, порты, версии Cypher и рантаймы, когда использовать, сравнение с альтернативами.
- **[Архитектура и хранение](./architecture.md)** — Index-free adjacency, store files, транзакционный движок, WAL.
- **[Установка и настройка](./installation_and_setup.md)** — Ubuntu APT, Docker, Docker Compose, APOC, начальная конфигурация.
- **[Cypher: полное руководство](./cypher_guide.md)** — CRUD, моделирование данных, обход графа, агрегации, импорт из CSV.
- **[Оптимизация запросов](./query_optimization.md)** — EXPLAIN/PROFILE, индексы, правила эффективных запросов.
- **[APOC: библиотека расширений](./apoc.md)** — установка, конфигурация, типичные сценарии.
- **[Драйверы](./drivers.md)** — Python, Java, JavaScript/TypeScript.
- **[Бэкап и восстановление](./backup_and_restore.md)** — офлайн- и онлайн-бэкап, restore, PITR, проверка.
- **[Мониторинг и логи](./monitoring.md)** — журналы, `query.log`, метрики, Prometheus, дашборды и алерты.
- **[Диагностика на уровне JVM](./jvm_diagnostics.md)** — слои памяти процесса, GC, NMT, дампы, лимиты контейнера.
- **[Kubernetes](./kubernetes_deployment.md)** — Helm-чарт, типы томов, режимы обслуживания, обновление.
- **[Обновление версии и миграция](./upgrade_and_migration.md)** — модель версий, LTS-чекпоинты, breaking changes, откат.
- **[Массовый импорт и начальная загрузка](./bulk_import.md)** — `neo4j-admin database import`, режимы, требования к данным.
- **[Мультитенантность и composite databases](./multi_tenancy.md)** — изоляция баз, лимиты, федерация графов.
- **[Нагрузочное тестирование](./performance_testing.md)** — что измерять и что ломает тест в Neo4j.
- **[Кластеризация и HA](./clustering.md)** — primary/secondary, топология, маршрутизация, DR.
- **[Безопасность](./security.md)** — RBAC, TLS, защита запросов от инъекций.
