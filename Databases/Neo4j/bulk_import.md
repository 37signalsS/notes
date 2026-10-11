# Neo4j: Массовый импорт и начальная загрузка

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS

## Определения

| Термин | Значение |
| :--- | :--- |
| **Bulk import** | Офлайн-команда `neo4j-admin database import`, записывающая CSV или Parquet напрямую в store-файлы, минуя транзакции и запросы. |
| **Full import** | Режим импорта в несуществующую или пустую базу. |
| **Incremental import** | Режим дозагрузки, когда импорт не помещается в один заход и выполняется серией smaller imports. |
| **Data source** | Группа файлов со своим заголовком; узлы и связи могут иметь по несколько источников. |
| **Header** | Первая строка файла, описывающая поля. Поля, не описанные в заголовке, не читаются. |
| **Seed** | Дамп или полный бэкап, из которого создаётся база в кластере. |
| **Neo4j Data Importer** | Отдельный официальный инструмент (десктоп/CLI) для загрузки CSV в Neo4j поверх работающего сервера. |
| **Store-файлы (Store files)** | Внутренние файлы Neo4j (`neostore.nodestore.db`, `neostore.relationshipstore.db`, `neostore.propertystore.db`, индексы), в которые импортер пишет напрямую. |
| **Off-heap память (Off-heap memory)** | Память вне JVM heap, используемая импортером для сортировки, построения индексов и буферизации I/O. Управляется `--max-off-heap-memory`. |
| **High-parallel I/O** | Режим параллельного ввода-вывода для ускорения чтения источников и записи store-файлов на SSD/RAID/сетевые тома. |

## Архитектура и принцип работы импорта

### Почему импорт вынесен из Cypher

Транзакционная вставка через Cypher проходит полный путь: план, блокировки, запись в transaction log, checkpoint, обновление индексов. На десятках миллионов узлов это стоимость на порядок выше, чем прямая запись в store-файлы. Bulk import эту цепочку разрывает: он пишет файлы напрямую, поэтому и требует остановленного сервера и пустой целевой базы.

Официальные условия применения:

- производительность критична, объём данных — миллионы и миллиарды сущностей;
- база может быть выведена из работы, есть прямой доступ к одному из серверов;
- целевая база не существует или пуста;
- обновление графа большим объёмом данных — incremental import может быть производительнее транзакционной вставки;
- данные чистые: узлы не дублируются, у связей существуют начало и конец.

Последний пункт — не формальность. Импорт оптимизирован под данные без ошибок, и очистка источника до загрузки даёт больше, чем любые флаги толерантности.

### Внутренняя механика полного импорта

Импорт выполняется в нескольких этапах, каждый из которых может быть наблюден в логе:

1. **Чтение и валидация заголовков** — определение типов свойств, меток, типов связей.
2. **Чтение узлов (Node import)** — парсинг CSV/Parquet, назначение внутренних ID, запись в `neostore.nodestore.db` и `neostore.propertystore.db`. При `--normalize-types` (по умолчанию) все целые приводятся к 64-битным `long`.
3. **Построение индексов узлов** — если задан `--schema`, создаются RANGE/LOOKUP/POINT/TEXT/FULL-TEXT/VECTOR индексы и ограничения уникальности/существования/типа. Только для формата `block` (Enterprise Edition).
4. **Чтение связей (Relationship import)** — парсинг, разрешение `START_ID`/`END_ID` во внутренние ID, запись в `neostore.relationshipstore.db` и свойства связей.
5. **Построение индексов связей** — аналогично узлам, если задано в `--schema`.
6. **Постобработка (Post-processing)** — финализация store-файлов, расчёт статистики, запись метаданных базы.

> **Ключевой момент:** Импорт **не пишет** в транзакционный журнал (WAL). Восстановление после сбоя во время импорта невозможно — нужно начинать заново. Поэтому `--dry-run` обязателен перед production-запуском.

### Инкрементальный импорт

Режим `incremental` добавляет данные в **уже существующую** базу. Этапы:

1. Чтение новых узлов, проверка на дубликаты (требует `--skip-duplicate-nodes=true` для идемпотентности).
2. Чтение новых связей, разрешение ID против уже загруженных узлов.
3. Обновление индексов (если они есть) — добавление новых записей.

Инкрементальный импорт **не поддерживает** создание новых индексов/ограничений через `--schema` до версии 2025.02; для `block`-формата поддержка добавлена в 2025.02.

### Формат `block` и Enterprise Edition

С 2026.09 (5.26 LTS) формат `block` является рекомендуемым и по умолчанию для Enterprise Edition. Особенности для импорта:

- `--schema` работает **только** с `block`-форматом.
- Индексы создаются **во время** импорта, а не после — это исключает второй проход по данным.
- Инкрементальный импорт в `block` поддерживает `--schema` с 2025.02.
- `high_limit` / `standard` deprecated с 5.23 — миграция в `block` перед импортом рекомендуется.

### Сравнение способов загрузки

| Способ | Сервер работает | Формат | Когда выбирать |
| :--- | :--- | :--- | :--- |
| `neo4j-admin database import` | Нет | CSV, Parquet | Начальная загрузка, большие объёмы |
| `LOAD CSV` | Да | CSV | Небольшие и средние загрузки, часть процесса миграции |
| `apoc.load.json`, `apoc.import.*` | Да | JSON, CSV | Загрузка в кластере, чтение из импортируемых каталогов |
| Neo4j Data Importer | Да | CSV | Интерактивная загрузка, прототипирование, подбор схемы |

`LOAD CSV` разобран в [руководстве по Cypher](./cypher_guide.md#импорт-данных), файловый доступ через APOC — в [APOC](./apoc.md#загрузка-json).

### Как устроен входной формат

Файлы читаются как один большой файл на источник: несколько файлов можно указать через `--nodes` или `--relationships`, порядок сохраняется. Обязательные условия:

- разделитель по умолчанию — запятая, другой задаётся `--delimiter`; **все файлы должны использовать один и тот же разделитель**;
- первый указанный файл каждого источника — заголовок;
- кодировка UTF-8;
- лишние пробелы в начале и конце строк обрезаются по умолчанию — экранируйте значение кавычками, чтобы сохранить их;
- один символ может быть разделителем массивов: `--array-delimiter`, значение по умолчанию `;`;
- списки файлов можно задавать шаблоном: `--path-pattern-style=regex|glob|none`.

Формат узлов — `[<label>[:<label>]…=]<files>…`, формат связей — `[<type>=]<files>…`.

### Память импорта

У процесса импорта две независимые области памяти:

| Область | Управление |
| :--- | :--- |
| JVM heap процесса администратора | Обычные настройки из конфигурации инструментов `neo4j-admin` |
| Off-heap рабочая память | Параметр `--max-off-heap-memory` |

**Настройка `server.memory.pagecache.size` на импорт не влияет** — импортер использует `--max-off-heap-memory`. Если параметр не задан, бюджет выводится из доступных системных ресурсов. В dry-run и verbose-выводе effective off-heap бюджет показан как `Configured max memory`. Значение принимает и числа, и размеры, и долю свободной памяти: `--max-off-heap-memory=20G`, `--max-off-heap-memory=70%`.

## Предварительные требования (Prerequisites)

Перед запуском массового импорта убедитесь в выполнении всех условий:

| Требование | Проверка | Примечание |
| :--- | :--- | :--- |
| **Neo4j остановлен** | `systemctl is-active neo4j` → `inactive` | Импорт требует эксклюзивного доступа к store-файлам |
| **Права на каталоги** | `ls -ld /var/lib/neo4j/data /var/lib/neo4j/logs` | Владелец `neo4j:neo4j`, права `rwx` |
| **Свободное дисковое место** | `df -h /var/lib/neo4j/data` | Минимум **2.5× от размера исходных CSV** (источники + временные файлы + итоговая база) |
| **Off-heap память** | `free -g` | Рекомендуется ≥ 50% от размера исходных данных; задавайте явно через `--max-off-heap-memory` |
| **CPU** | `nproc` | `--threads` не должен превышать доступных процессоров |
| **Формат хранилища** | `neo4j-admin database info neo4j` | Для `--schema` требуется формат `block` (Enterprise Edition) |
| **Чистота данных** | Скрипт валидации CSV | Нет дубликатов ID, все `START_ID`/`END_ID` существуют, единый разделитель |

> **Важно:** Импорт не использует WAL. При сбое (OOM, диск, kill) **восстановление невозможно** — нужно удалять целевую директорию и начинать заново. Всегда делайте `--dry-run` перед production-запуском.

## Практические сценарии

### Подготовка файлов

```bash
# Узлы: :ID — идентификатор для связей, :LABEL — метка
# header: first line of nodes.csv
# id:ID,name:STRING,email:STRING,created_at:LONG
head -3 nodes.csv
# → id:ID,name:STRING,email:STRING,created_at:LONG
#   n1,Alice,alice@example.com,1600000000
#   n2,Bob,bob@example.com,1600000001

# Связи: :START_ID и :END_ID ссылаются на :ID узлов
head -3 relationships.csv
# → :START_ID,:END_ID,type:STRING,since:LONG
#   n1,n2,KNOWS,1600000000
#   n2,n1,KNOWS,1600000001
```

Типы в заголовке приводят значения к типам Cypher: без них импортер выведет тип из содержимого. С параметром `--normalize-types` (по умолчанию включён) скалярные значения приводятся к эквивалентным типам Cypher — например, все целые к 64-битным `long`.

### Полный импорт

Сервер остановлен. Каталоги `server.directories.data` и `server.directories.logs` доступны на запись пользователю, от имени которого запускается команда.

```bash
sudo -u neo4j /var/lib/neo4j/bin/neo4j-admin database import full \
  --nodes=Person=persons.csv \
  --relationships=KNOWS=knows.csv \
  --overwrite-destination=true \
  neo4j
```

```plain
The importer supports a CSV (comma separated value) or Parquet...
Nodes imported:            1000000
Relationships imported:     4999000
Nodes that are missing relationships  0
Skipped nodes:              0
Skipped relationships:      0
...
Import done in 3m 12s
```

База с именем `neo4j` существует по умолчанию. **Если целевой базы не существует, её нужно создать после импорта:**

```cypher
CREATE DATABASE mydatabase;
```

### Ключевые параметры

| Параметр | Назначение | По умолчанию |
| :--- | :--- | :--- |
| `--nodes`, `--relationships` | Файлы узлов и связей с указанием меток и типов | — |
| `--bad-tolerance=<num>` | Сколько плохих записей допустить до прерывания импорта. Высокое значение снижает производительность | `-1` (изменено в 2025.12) |
| `--skip-duplicate-nodes` | Пропускать узлы с одинаковым ID/группой; первый встреченный импортируется | `false` |
| `--skip-bad-relationships` | Пропускать связи, ссылающиеся на несуществующие ID узлов | `false` |
| `--strict` | Строгая проверка ссылок связей на несуществующие узлы; находит все, но медленнее | `false` |
| `--normalize-types` | Приведение значений к типам Cypher | `true` |
| `--trim-strings` | Обрезка пробелов у строк | `false` |
| `--ignore-extra-columns` | Игнорировать столбцы, не описанные в заголовке | `false` |
| `--threads=<num>` | Число рабочих потоков; по умолчанию — число процессоров, доступных JVM. Не должен превышать число процессоров | по умолчанию CPU |
| `--high-parallel-io=on\|off\|auto` | Разрешить параллельный ввод-вывод. Типично `on` для SSD, больших RAID и сетевого хранилища | `auto` |
| `--overwrite-destination` | Удалить существующие файлы базы перед импортом | `false` |
| `--max-off-heap-memory=<size>` | Бюджет off-heap памяти импорта | из системных ресурсов |
| `--dry-run` | Прогон без записи | — |
| `--schema=<path>` | Файл с Cypher-командами для создания индексов и ограничений | — |
| `--expand-commands` | Разрешить подстановку команд в JVM-параметры (нужно в контейнерах) | — |

### Индексы и ограничения во время импорта

Создавать индексы после импорта на миллионах записей — лишний проход. Параметр `--schema` принимает Cypher-скрипт, который выполняется в процессе импорта:

```bash
cat > schema.cypher <<'EOF'
CREATE INDEX person_email IF NOT EXISTS FOR (p:Person) ON (p.email);
CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE;
EOF

sudo -u neo4j /var/lib/neo4j/bin/neo4j-admin database import full \
  --nodes=Person=persons.csv \
  --relationships=KNOWS=knows.csv \
  --schema=schema.cypher \
  neo4j
```

Ограничения этого механизма:

- только формат `block` (Enterprise Edition);
- `CREATE INDEX|CONSTRAINT` для full import поддерживается начиная с Neo4j 5.24 (Cypher 5 и 25), для incremental import — с 2025.02;
- **full import не поддерживает `DROP`** индексов и ограничений — `DROP` доступен в incremental import;
- поддерживаемые типы индексов: `RANGE`, `LOOKUP`, `POINT`, `TEXT`, `FULL-TEXT`, `VECTOR`;
- поддерживаемые типы ограничений: уникальности, существования свойства, типа свойства, key-ограничения.

Для остальных форматов и более ранних версий индексы и ограничения создаются вручную после импорта.

### Прерывание и продолжение импорта (Enterprise Edition)

Импорт, остановленный или упавший до завершения, можно продолжить с более близкой точки остановки — с этапа связывания связей или постобработки. Возобновление **не поддерживается для формата `block`**.

### Инкрементальная дозагрузка

Когда объём не помещается в один заход:

```bash
sudo -u neo4j /var/lib/neo4j/bin/neo4j-admin database import incremental \
  --nodes=Person=persons-chunk-2.csv \
  --relationships=KNOWS=knows-chunk-2.csv \
  --skip-duplicate-nodes=true \
  neo4j
```

### Наблюдение за прогрессом

Подробный лог прогресса доступен для обеих команд импорта начиная с Neo4j 2026.03. Отдельная страница документации описывает разбор логов импорта; на практике достаточно отслеживать рост каталога целевой базы и вывод команды.

### Импорт в кластере

Массовый импорт выполняется на одном сервере — операция офлайн, и все узлы кластера держат копии базы. Дальнейшие варианты:

- **seed:** создать базу в кластере из дампа или полного бэкапа — процедура и топология описаны в [кластеризации](./clustering.md#бэкап-восстановление-и-seed-в-кластере);
- **копирование базы:** `neo4j-admin database copy` переносит базу между серверами кластера; этим же механизмом шардируют существующую базу.

**Важно для CDC: изменение данных, сделанное через `neo4j-admin database import`, не попадает в поток изменений.** Импортированный граф считается исходным состоянием, а не серией изменений — это отличается от транзакционной вставки, которую видят потребители CDC.

## Операции и команды (Operations and Commands)

### Справочник команд `neo4j-admin database import`

| Команда | Описание |
| :--- | :--- |
| `neo4j-admin database import full [options] <database>` | Полный импорт в пустую/несуществующую базу |
| `neo4j-admin database import incremental [options] <database>` | Инкрементальная дозагрузка в существующую базу |
| `neo4j-admin database import --help` | Справка по всем параметрам |

### Полный синтаксис full import

```bash
neo4j-admin database import full \
  --nodes=<label>=<file1>,<file2>... \
  --relationships=<type>=<file1>,<file2>... \
  [--delimiter=<char>] \
  [--array-delimiter=<char>] \
  [--quote=<char>] \
  [--skip-duplicate-nodes[=true|false]] \
  [--skip-bad-relationships[=true|false]] \
  [--strict[=true|false]] \
  [--bad-tolerance=<num>] \
  [--normalize-types[=true|false]] \
  [--trim-strings[=true|false]] \
  [--ignore-extra-columns[=true|false]] \
  [--threads=<num>] \
  [--high-parallel-io=on|off|auto] \
  [--max-off-heap-memory=<size>] \
  [--schema=<path>] \
  [--overwrite-destination[=true|false]] \
  [--dry-run] \
  [--expand-commands] \
  [--verbose] \
  <database>
```

### Полный синтаксис incremental import

```bash
neo4j-admin database import incremental \
  --nodes=<label>=<file1>,<file2>... \
  --relationships=<type>=<file1>,<file2>... \
  [--skip-duplicate-nodes[=true|false]] \
  [--skip-bad-relationships[=true|false]] \
  [--bad-tolerance=<num>] \
  [--normalize-types[=true|false]] \
  [--threads=<num>] \
  [--high-parallel-io=on|off|auto] \
  [--max-off-heap-memory=<size>] \
  [--expand-commands] \
  [--verbose] \
  <database>
```

### Параметры формата и парсинга

| Параметр | Описание | По умолчанию | Пример |
| :--- | :--- | :--- | :--- |
| `--delimiter` | Разделитель полей в CSV | `,` | `--delimiter='\t'` |
| `--array-delimiter` | Разделитель элементов массива | `;` | `--array-delimiter='|'` |
| `--quote` | Символ кавычки для экранирования | `"` | `--quote="'"` |
| `--trim-strings` | Обрезать пробелы у строковых значений | `false` | `--trim-strings=true` |
| `--ignore-extra-columns` | Игнорировать столбцы без описания в заголовке | `false` | `--ignore-extra-columns=true` |
| `--path-pattern-style` | Стиль шаблонов путей к файлам | `none` | `--path-pattern-style=glob` |

### Параметры производительности

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `--threads` | Число рабочих потоков | `= nproc` (не больше физических ядер) |
| `--max-off-heap-memory` | Бюджет off-heap памяти | `50-70% RAM` или фиксированно `20G`, `30G` |
| `--high-parallel-io` | Параллельный I/O | `on` для SSD/NVMe/RAID, `off` для HDD |
| `--bad-tolerance` | Допуск плохих записей | `-1` (нет лимита, изменено в 2025.12) |

### Параметры целостности

| Параметр | Описание | Когда использовать |
| :--- | :--- | :--- |
| `--skip-duplicate-nodes` | Пропускать дубликаты ID (берётся первый) | Инкрементальный импорт, идемпотентность |
| `--skip-bad-relationships` | Пропускать связи к несуществующим узлам | Грязные данные, оценка масштаба проблемы |
| `--strict` | Полная проверка всех ссылок связей | Финальный production-запуск после очистки |
| `--normalize-types` | Приведение скаляров к типам Cypher | Всегда `true` для предсказуемости |

## Проверка и валидация результата (Validation)

После импорта **обязательно** выполните проверки перед стартом приложения:

### 1. Проверка консистентности store-файлов

```bash
# База должна быть остановлена
neo4j-admin database check neo4j
# Код возврата 0 = ошибок нет
```

### 2. Проверка количества сущностей

```bash
# Через Cypher (после CREATE DATABASE и старта сервера)
MATCH (n) RETURN count(n) AS nodes;
MATCH ()-[r]->() RETURN count(r) AS relationships;
```

### 3. Информация о store (store-info)

```bash
neo4j-admin database info neo4j
```

Ожидаемый вывод содержит:
- `Node count`, `Relationship count`, `Property count`
- `Store sizes` — размеры файлов
- `Format` — должен быть `block` (для Enterprise 2026.09+)

### 4. Состояние индексов

```cypher
SHOW INDEXES YIELD name, state, populationPercent
WHERE state <> 'ONLINE'
RETURN name, state, populationPercent;
```

Все индексы должны быть `ONLINE` (populationPercent = 100). `POPULATING` — фоновое заполнение ещё идёт.

### 5. Проверка ограничений

```cypher
SHOW CONSTRAINTS YIELD name, type, state
RETURN name, type, state;
```

Все ограничения должны быть `ONLINE`.

### 6. Тестовый запрос производительности

```cypher
PROFILE MATCH (n:Person) WHERE n.email = 'test@example.com' RETURN n;
```

План должен показывать `IndexSeek` или `NodeIndexSeek`, а не `AllNodesScan`.

## Автоматизация и SRE-операции (Automation)

### Production-скрипт импорта с pre-checks и валидацией

```bash
#!/usr/bin/env bash
# /usr/local/bin/neo4j-bulk-import.sh
set -euo pipefail

IMPORT_DIR="/data/import"
DATA_DIR="/var/lib/neo4j/data"
LOG_FILE="/var/log/neo4j-import.log"
MIN_FREE_GB=100
OFF_HEAP_GB=32
THREADS=$(nproc)

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"; }

# 1. Pre-flight checks
log "=== PRE-FLIGHT CHECKS ==="
log "Checking Neo4j status..."
systemctl is-active --quiet neo4j && { log "ERROR: Neo4j is running, stop it first"; exit 1; }

log "Checking disk space on $DATA_DIR..."
FREE_GB=$(df -BG "$DATA_DIR" | awk 'NR==2 {print $4}' | sed 's/G//')
[ "$FREE_GB" -ge "$MIN_FREE_GB" ] || { log "ERROR: Only ${FREE_GB}GB free, need ${MIN_FREE_GB}GB"; exit 1; }

log "Checking import files exist..."
[ -f "$IMPORT_DIR/nodes.csv" ] || { log "ERROR: nodes.csv not found"; exit 1; }
[ -f "$IMPORT_DIR/relationships.csv" ] || { log "ERROR: relationships.csv not found"; exit 1; }

log "Validating CSV headers (first line)..."
head -1 "$IMPORT_DIR/nodes.csv" | grep -q ':ID' || { log "ERROR: nodes.csv missing :ID column"; exit 1; }
head -1 "$IMPORT_DIR/relationships.csv" | grep -q ':START_ID' || { log "ERROR: relationships.csv missing :START_ID"; exit 1; }
head -1 "$IMPORT_DIR/relationships.csv" | grep -q ':END_ID' || { log "ERROR: relationships.csv missing :END_ID"; exit 1; }

log "Checking delimiter consistency..."
# Простая проверка: одинаковое число полей в первых 100 строках
awk -F, 'NR<=100 {print NF}' "$IMPORT_DIR/nodes.csv" | sort -u | wc -l | grep -q '^1$' || { log "WARN: Inconsistent column count in nodes.csv"; }

# 2. Dry-run
log "=== DRY RUN ==="
if ! sudo -u neo4j /var/lib/neo4j/bin/neo4j-admin database import full \
     --nodes=Person="$IMPORT_DIR/nodes.csv" \
     --relationships=KNOWS="$IMPORT_DIR/relationships.csv" \
     --max-off-heap-memory="${OFF_HEAP_GB}G" \
     --threads="$THREADS" \
     --high-parallel-io=on \
     --dry-run \
     neo4j >> "$LOG_FILE" 2>&1; then
  log "ERROR: Dry-run failed"
  exit 1
fi
log "Dry-run successful"

# 3. Actual import
log "=== FULL IMPORT ==="
START=$(date +%s)
if ! sudo -u neo4j /var/lib/neo4j/bin/neo4j-admin database import full \
     --nodes=Person="$IMPORT_DIR/nodes.csv" \
     --relationships=KNOWS="$IMPORT_DIR/relationships.csv" \
     --max-off-heap-memory="${OFF_HEAP_GB}G" \
     --threads="$THREADS" \
     --high-parallel-io=on \
     --overwrite-destination=true \
     --schema="$IMPORT_DIR/schema.cypher" \
     neo4j >> "$LOG_FILE" 2>&1; then
  log "ERROR: Import failed"
  exit 1
fi
DURATION=$(( $(date +%s) - START ))
log "Import completed in ${DURATION}s"

# 4. Validation
log "=== VALIDATION ==="
if ! neo4j-admin database check neo4j >> "$LOG_FILE" 2>&1; then
  log "ERROR: Consistency check failed"
  exit 1
fi
log "Consistency check passed"

# 5. Metrics (Prometheus Pushgateway example)
# curl -X POST --data "neo4j_import_duration_seconds $DURATION" http://pushgateway:9091/metrics/job/neo4j-import
# curl -X POST --data "neo4j_import_nodes $(grep 'Nodes imported:' $LOG_FILE | tail -1 | awk '{print $3}')" http://pushgateway:9091/metrics/job/neo4j-import

log "=== IMPORT SUCCESSFUL ==="
```

### Ключевые элементы SRE-автоматизации

- **Dead Man's Switch** — алерт на отсутствие успешного импорта в ожидаемое окно (не на ошибку, а на отсутствие успеха).
- **Метрики** — `import_duration_seconds`, `import_nodes_count`, `import_relationships_count`, `import_off_heap_peak_bytes`.
- **Валидация в том же цикле** — импорт не считается успешным, пока не пройден `neo4j-admin database check`.
- **Pre-flight checks** — диск, память, права, остановленный сервер, чистота заголовков CSV.
- **Dry-run обязателен** — отсекает ошибки парсинга до записи store-файлов.

### Планирование окна импорта

| Размер данных | Оценка времени (SSD, 32G off-heap, 16 CPU) | Окно простоя |
| :--- | :--- | :--- |
| 10M узлов / 50M связей | 15-30 мин | 1 час |
| 100M узлов / 500M связей | 2-4 часа | 6 часов |
| 1B узлов / 5B связей | 12-24 часа | 36 часов |

> Оценки зависят от сложности схемы, числа индексов, типа хранилища. Всегда прогоняйте на копии данных.

## Ограничения и граничные случаи (Edge Cases)

| Ограничение | Детали | Обход |
| :--- | :--- | :--- |
| **Нет WAL / нет отката** | Сбой = полная перезапись | `--dry-run`, бэкап пустой базы перед стартом |
| **`--schema` только `block`** | Community / `aligned` / `high_limit` / `standard` — не поддерживают | Мигрируйте формат перед импортом (`neo4j-admin database migrate --to-format=block`) |
| **Нет `DROP` в full import** | Нельзя удалить индексы/ограничения через `--schema` в full import | Используйте incremental import для DROP, либо создавайте после |
| **Нет resume для `block`** | Прерванный импорт в `block` нельзя продолжить | Планируйте окно с запасом; используйте incremental для крупных загрузок |
| **ID должны быть уникальны глобально** | `:ID` у узлов должен быть уникален по всем меткам | Генерируйте UUID или используйте составные ключи |
| **Parquet: типы строгие** | Схема Parquet должна совпадать с заголовком CSV-логики | Используйте `neo4j-admin database import --help` для проверки совместимости |
| **Нет транзакционности** | Частичный импорт не откатывается | Идемпотентность через `--skip-duplicate-nodes` + incremental |
| **Память вне JVM** | `--max-off-heap-memory` не учитывает page cache | Резервируйте RAM: off-heap + page cache + OS < физическая память |

## Устранение неполадок (Troubleshooting)

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `Permission denied` на каталог данных | Команда падает сразу | Нет прав на `server.directories.data` или `server.directories.logs` | Запускать от пользователя `neo4j` либо дать права на каталоги |
| `Neo.ClientError.Schema.ConstraintValidationFailed` | Импорт прерван на связях | Связи ссылаются на несуществующие узлы | Чистить источник; для оценки масштаба — `--skip-bad-relationships` вместе с `--bad-tolerance`, затем разбирать лог пропущенного |
| Импорт идёт медленно, растёт off-heap | Низкая скорость, высокая нагрузка на диск | Не хватает бюджета off-heap либо параллельный ввод-вывод отключён | `--max-off-heap-memory`, проверить `--high-parallel-io` (для SSD — `on`), не выходить за пределы числа процессоров в `--threads` |
| Ошибка разбора полей | `Could not parse` по конкретному столбцу | Разделитель в данных не совпадает с `--delimiter`, либо строковые значения не экранированы | Единый разделитель для всех файлов; экранировать значения кавычками |
| `--array-delimiter` конфликтует | Ошибка валидации параметра | Разделитель массивов совпал с `--delimiter` | Задать разные символы; по умолчанию `;` и `,` |
| Импорт не ускоряет работу приложения | Данные вставлены, запросы всё равно медленные | Не хватает page cache для нового объёма | Пересчитать `server.memory.pagecache.size` по формуле `1.2 × (данные + индексы)`, см. [архитектуру](./architecture.md) |
| Импорт в кластере «пропал» | Базы нет в `SHOW DATABASES` | Не выполнен `CREATE DATABASE` | Создать базу в `system` |
| `OutOfMemoryError: Direct buffer memory` | JVM падает с OOM в off-heap | `--max-off-heap-memory` превышает доступную физическую память | Уменьшить `--max-off-heap-memory`; оставить ≥ 20% RAM под OS и page cache |
| `FileNotFoundException` на временные файлы | Ошибка в середине импорта | Нет места на диске для временных файлов импортера | Проверить `df -h`; импортер пишет временные файлы в рабочую директорию — задайте `TMPDIR` на большой раздел |
| Дубликаты ID не пропускаются | `--skip-duplicate-nodes=true` но дубликаты всё равно вызывают ошибку | Дубликаты в **разных** файлах одного источника обрабатываются, а в разных источниках — нет | Объедините файлы источника в один либо используйте `--nodes=Label=file1,file2` в одном параметре |
| Индексы не создаются через `--schema` | Импорт проходит, но `SHOW INDEXES` пуст | Формат хранилища не `block` (Community / `aligned` / `high_limit` / `standard`) | `neo4j-admin database migrate --to-format=block neo4j` перед импортом (требует Enterprise) |
| Parquet: `Schema mismatch` | Ошибка при чтении Parquet | Типы колонок в Parquet не совпадают с ожидаемыми типами импортера | Проверьте схему Parquet: `parquet-tools schema file.parquet`; приведите типы к STRING/LONG/DOUBLE/BOOLEAN |
| Инкрементальный импорт не видит существующие узлы | `--skip-duplicate-nodes` не работает | База была создана в другом кластере / имеет другой `storeId` | Инкрементальный импорт работает только в одной и той же инстанции базы; для миграции используйте бэкап/восстановление |
| `--strict` находит ошибки, которые `--skip-bad-relationships` пропускал | Разное поведение флагов | `--strict` проверяет **все** связи до начала импорта; `--skip-bad-relationships` пропускает на лету | Используйте `--strict` для финальной валидации после очистки данных |
| `neo4j-admin database check` выдает ошибки после импорта | `inconsistencies-*.report` с ошибками | Импорт прервался (OOM, диск, kill) и store-файлы повреждены | Удалите целевую директорию базы и начните заново; восстановление невозможно (нет WAL) |

## Лучшие практики

- **Чистите данные до импорта.** Импорт оптимизирован под отсутствие ошибок; `--bad-tolerance` — это диагностический инструмент, а не стратегия.
- **Держите CSV на локальном диске**, а не на сетевом хранилище: импорт интенсивно читает ввод и пишет store-файлы.
- **Не смешивайте разделители** между файлами одного запуска — это самая частая ошибка разбора.
- **Экранируйте значения с пробелами и запятыми** кавычками: `--array-delimiter` управляет только массивами.
- **Создавайте индексы через `--schema`**, а не после импорта — второй проход по миллионам записей стоит дорого.
- **Фиксируйте `--normalize-types` явно**, если важна предсказуемость типов: по умолчанию все целые становятся 64-битными `long`.
- **Настраивайте `--max-off-heap-memory` явно**, а не полагайтесь на вывод из системных ресурсов — иначе поведение меняется при смене хоста.
- **Планируйте место:** импорт пишет во временные файлы, поэтому нужен запас сверх итогового размера базы.
- **Проверяйте результат до старта приложения:** количество узлов и связей, `store-info`, затем индексы в состоянии `ONLINE`.

## Дополнительная информация

- **[Документация: Import](https://neo4j.com/docs/operations-manual/current/import/)** — условия применения, режимы, требования к файлам, память импорта.
- **[Документация: Full import](https://neo4j.com/docs/operations-manual/current/import/full-import/)** — полный синтаксис и справочник параметров.
- **[Документация: Create or drop indexes during import](https://neo4j.com/docs/operations-manual/current/import/create-drop-indexes/)** — `--schema`, поддерживаемые типы индексов и ограничений.
- **[Neo4j Data Importer](https://neo4j.com/docs/data-importer/current/)** — отдельный инструмент для загрузки в работающий сервер.
- **[Миграции схемы](./schema_migrations.md)** — что делать с индексом, созданным при импорте, дальше.
- **[Cypher: полное руководство](./cypher_guide.md)** — `LOAD CSV` для небольших загрузок.

## См. также

- **[Архитектура и хранение](./architecture.md)** — store-файлы, форматы, page cache после импорта.
- **[Бэкап и восстановление](./backup_and_restore.md)** — дамп и load, проверка консистентности.
- **[Кластеризация и высокая доступность](./clustering.md)** — seed базы в кластере, `neo4j-admin database copy`.
- **[APOC](./apoc.md)** — загрузка JSON, файловый доступ.
- **[Обслуживание и эксплуатация](./operations.md)** — расчёт памяти под новый объём базы.