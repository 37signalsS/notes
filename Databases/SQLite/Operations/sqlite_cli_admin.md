# CLI и администрирование SQLite

**Актуально для:** SQLite 3.45+ / CLI 3.54.0

## Определения

*   **Dot-command** — служебная команда CLI, начинающаяся с точки (`.mode`, `.import`, `.backup` и т.д.); выполняется оболочкой, а не SQL-движком.
*   **URI filename** — строка подключения вида `file:data.db?mode=ro`, задающая режим открытия, shared cache и другие параметры.
*   **ATTACH** — подключение дополнительной БД к текущему соединению под псевдонимом; позволяет делать кросс-БД запросы.
*   **temp_store** — PRAGMA, определяющий, где хранятся временные таблицы и результаты сортировки: 0 (DEFAULT, по умолчанию сборки), 1 (FILE, на диске), 2 (MEMORY).
*   **user_version / application_id** — 32-битные поля в заголовке БД (смещения 60 и 68) для версионирования схемы и идентификации файла приложением.
*   **Expand-contract** — паттерн миграции: добавить новое → мигрировать данные → переключить приложение → удалить старое.

## Базовые концепции

### URI filenames

```bash
# Только чтение
sqlite3 "file:data.db?mode=ro"

# Чтение-запись, ошибка если файла нет
sqlite3 "file:data.db?mode=rw"

# In-memory
sqlite3 "file::memory:?cache=shared"

# Без блокировок (только для read-only носителей; опасно)
sqlite3 "file:data.db?immutable=1"

# Shared cache между соединениями
sqlite3 "file:data.db?cache=shared"
```

URI filenames нужно включить (`SQLITE_USE_URI=1` при сборке или `sqlite3_config(SQLITE_CONFIG_URI, 1)`); CLI включает их по умолчанию. В Python: `sqlite3.connect("file:data.db?mode=ro", uri=True)`.

### ATTACH — кросс-БД запросы

```sql
ATTACH DATABASE 'archive.db' AS aux;
SELECT * FROM main.events e JOIN aux.events a ON e.id = a.id WHERE a.id IS NULL;
DETACH DATABASE aux;
```

Применения: сравнение/миграция между БД, копирование данных (`INSERT INTO main.t SELECT * FROM aux.t`), тестирование.

### Временные файлы и диск

*   `PRAGMA temp_store = 2` — временные таблицы и сортировки в RAM (быстрее, но расходует память).
*   `SQLITE_TMPDIR` — переменная окружения, задающая каталог для временных файлов (полезно, когда `/tmp` мал).
*   `PRAGMA cache_spill = OFF` — запретить сброс грязных страниц в середине транзакции (спилл захватывает EXCLUSIVE-блокировку; важно для длинных транзакций).

### Версионирование схемы

```sql
PRAGMA user_version = 3;       -- версия схемы приложения
PRAGMA user_version;           -- → 3
PRAGMA application_id = 12345; -- идентификатор для file(1) и утилит
```

Паттерн: приложение при старте читает `user_version` и применяет недостающие миграции.

### Миграции схемы

Возможности `ALTER TABLE`:

*   `RENAME TABLE`, `RENAME COLUMN` (3.25.0+)
*   `ADD COLUMN` — с ограничениями: нельзя добавить PRIMARY KEY или UNIQUE; default не может быть `CURRENT_TIME`/`CURRENT_DATE`/`CURRENT_TIMESTAMP` или выражением; `NOT NULL` требует non-NULL default; при включённых FK колонка с `REFERENCES` требует default NULL
*   `DROP COLUMN` (3.35.0+)

Для сложных изменений (смена типа, удаление колонки в старых версиях) — ручная перестройка: создать новую таблицу → скопировать данные → удалить старую → переименовать. `PRAGMA legacy_alter_table = ON` возвращает старое поведение `RENAME` (для совместимости, не для нового кода). `PRAGMA writable_schema` — прямая правка `sqlite_schema`; **опасно**, приводит к повреждению (см. [восстановление](./sqlite_recovery_diagnostics.md)).

## Практические сценарии

### 1. Флаги CLI

| Флаг | Назначение |
| :--- | :--- |
| `-readonly` | Открыть БД только для чтения |
| `-ifexists` | Не создавать файл, если БД не существует |
| `-init FILE` | Выполнить файл (dot-команды/SQL) при старте |
| `-noinit` | Не читать `~/.sqliterc` |
| `-batch` | Пакетный режим (без интерактивных подсказок) |
| `-bail` | Остановиться после первой ошибки |
| `-cmd COMMAND` | Выполнить команду перед чтением stdin |
| `-csv` / `-json` / `-line` / `-column` / `-box` / `-markdown` / `-html` / `-ascii` / `-quote` / `-list` | Режимы вывода |
| `-[no]header` | Заголовки колонок |
| `-nullvalue TEXT` | Строка вместо NULL |
| `-newline SEP` | Разделитель строк |
| `-echo` | Печатать ввод перед выполнением |
| `-nofollow` | Не открывать символические ссылки на файлы БД |
| `-safe` | Safe mode (ограничение опасных операций) |
| `-deserialize` | Открыть БД через `sqlite3_deserialize()` (in-memory из файла) |
| `-append` | Дописать к существующему файлу |
| `-screenwidth N` | Ширина вывода |

### 2. Dot-команды (справочник)

**Вывод и формат:**
`.mode ?MODE? ?OPTIONS?` (режимы: `csv`, `column`, `box`, `table`, `json`, `line`, `list`, `markdown`, `html`, `ascii`, `quote`; опции `--colsep`, `--align`, `--border`, `--charlimit`), `.headers on|off`, `.nullvalue STRING`, `.once ?OPTIONS? ?FILE?`, `.output ?FILE?`, `.print STRING...`, `.changes on|off`, `.timer on|off|once`, `.stats ?ARG?`, `.scanstats on|off|est`, `.excel`, `.www`

**Навигация и метаданные:**
`.databases`, `.tables ?TABLE?`, `.indexes ?PATTERN?`, `.schema ?PATTERN?`, `.fullschema ?--indent?`, `.dbinfo ?DB?`, `.dbstat ?SCHEMA?`, `.dbtotxt`, `.version`, `.help ?-all? ?PATTERN?`, `.cd DIRECTORY`, `.open ?OPTIONS? ?FILE?`

**Импорт/экспорт и бэкап:**
`.import FILE TABLE`, `.dump ?OBJECTS?`, `.archive ...`, `.backup ?DB? FILE`, `.restore ?DB? FILE`, `.save ?OPTIONS? FILE`, `.clone NEWDB`

**Выполнение и отладка:**
`.read FILE`, `.shell CMD ARGS...` / `.system CMD ARGS...`, `.echo on|off`, `.trace ?OPTIONS?`, `.progress N`, `.parameter CMD ...`, `.limit ?LIMIT? ?VAL?`, `.connection [close] [#]`, `.session ?NAME? CMD ...`, `.testcase NAME` / `.check OPTIONS ...`

**Диагностика и восстановление:**
`.eqp on|off|full|...`, `.explain ?on|off|auto?`, `.expert`, `.intck ?STEPS?`, `.lint OPTIONS`, `.recover ?OPTIONS?`, `.imposter INDEX TABLE`, `.sha3sum ...`, `.auth ON|OFF`, `.dbconfig ?op? ?val?`, `.filectrl CMD ...`, `.vfsinfo ?AUX?`, `.vfslist`, `.vfsname ?AUX?`

**Прочее:**
`.bail on|off`, `.crlf ?on|off?`, `.exit ?CODE?` / `.quit`, `.prompt MAIN CONTINUE`, `.nonce STRING`, `.rekey` / `.hex-rekey` / `.text-rekey` (шифрование, SEE-сборки)

### 3. Импорт и экспорт данных

```bash
# Импорт CSV (таблица должна существовать)
sqlite3 data.db ".import --csv --skip 1 events.csv events"

# Экспорт в CSV
sqlite3 data.db ".mode csv" ".headers on" "SELECT * FROM events;" > events.csv

# Полный дамп (схема + данные)
sqlite3 data.db .dump > backup.sql

# Только схема
sqlite3 data.db .schema

# Дамп одной таблицы (только данные)
sqlite3 data.db ".dump --data-only events"
```

### 4. Безопасное чтение чужой БД

```bash
# Read-only, без создания файлов, без следования по symlink
sqlite3 -readonly -ifexists -nofollow "file:data.db?mode=ro" "SELECT count(*) FROM events;"

# Таймаут ожидания блокировки в CLI
sqlite3 data.db ".timeout 5000" "SELECT * FROM config;"
```

### 5. Миграция с версионированием

```bash
sqlite3 data.db <<'EOF'
PRAGMA user_version;
-- → 2  (текущая версия схемы)
BEGIN IMMEDIATE;
ALTER TABLE events ADD COLUMN severity TEXT DEFAULT 'info';
PRAGMA user_version = 3;
COMMIT;
PRAGMA user_version;
-- → 3
EOF
```

### 6. ATTACH для миграции между БД

```bash
sqlite3 new.db <<'EOF'
ATTACH 'old.db' AS src;
CREATE TABLE events AS SELECT * FROM src.events;
DETACH src;
EOF
```

## Операции и команды

| Задача | Команда |
| :--- | :--- |
| Read-only доступ | `sqlite3 -readonly "file:db?mode=ro"` |
| Пакетный скрипт | `sqlite3 -batch -bail -cmd "PRAGMA busy_timeout=5000;" db < script.sql` |
| Инициализация | `sqlite3 -init setup.sql db` |
| Импорт CSV | `sqlite3 db ".import --csv --skip 1 file.csv table"` |
| Экспорт CSV | `sqlite3 db ".mode csv" ".headers on" "SELECT ...;" > out.csv` |
| Дамп | `sqlite3 db .dump > dump.sql` |
| Таймаут блокировки | `sqlite3 db ".timeout 5000"` |
| План запроса | `sqlite3 db ".eqp on" "SELECT ...;"` |
| Подбор индексов | `sqlite3 db ".expert"` |
| Статус БД | `sqlite3 db ".dbinfo"` |
| Размеры | `sqlite3 db ".dbstat"` |

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `attempt to write a readonly database` | URI `mode=ro` или права файла | Проверить URI и `ls -l` |
| `unable to open database file` | Нет прав на директорию (нужны временные файлы) или файла | Права `0700` на директорию; `-ifexists` |
| `database is locked` в CLI | Другой процесс пишет | `.timeout 5000` |
| `.import` не находит колонки | Заголовок не пропущен | `--skip 1` |
| `.backup` зависает | Активная запись | `.timeout` перед `.backup` |
| Символическая ссылка отклонена | Флаг `-nofollow` или политика | Убрать `-nofollow` или копировать файл |

## Рекомендации SRE

*   Для инспекции чужих БД всегда `-readonly -ifexists -nofollow` — защита от случайной записи и следования по ссылкам.
*   `~/.sqliterc` с `PRAGMA busy_timeout=5000;` и `.mode column` ускоряет повседневную работу (отключается флагом `-noinit`).
*   Версионируйте схему через `PRAGMA user_version` — это стандартный, не требующий дополнительных таблиц способ.
*   `SQLITE_TMPDIR` — при больших сортировках на хостах с малым `/tmp`.
*   `ATTACH` — быстрый способ сравнить или мигрировать данные между двумя БД без дампов.

## Дополнительная информация

### См. также

*   [Обзор SQLite](../sqlite_overview.md) — архитектура
*   [Восстановление и диагностика](./sqlite_recovery_diagnostics.md) — `.recover`, `.intck`, `.dbstat`
*   [Экосистема SQLite](./sqlite_ecosystem.md) — Litestream, rqlite
*   [Официальная документация: CLI](https://sqlite.org/cli.html)
*   [Официальная документация: URI filenames](https://sqlite.org/uri.html)
