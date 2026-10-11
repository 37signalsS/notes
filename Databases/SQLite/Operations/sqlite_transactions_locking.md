# Транзакции, блокировки и коды ошибок SQLite

**Актуально для:** SQLite 3.45+

## Определения

*   **BEGIN DEFERRED** — транзакция, которая не захватывает блокировки до первого чтения/записи (режим по умолчанию).
*   **BEGIN IMMEDIATE** — транзакция, сразу захватывающая RESERVED-блокировку записи; `SQLITE_BUSY` возвращается сразу, а не в момент COMMIT.
*   **BEGIN EXCLUSIVE** — транзакция с EXCLUSIVE-блокировкой: блокирует всех читателей и писателей.
*   **SAVEPOINT** — вложенная точка сохранения внутри транзакции; откат к ней не отменяет всю транзакцию.
*   **SERIALIZABLE** — уровень изоляции по умолчанию в SQLite.
*   **SQLITE_BUSY (5)** — конфликт с другим соединением (обычно другим процессом).
*   **SQLITE_LOCKED (6)** — конфликт внутри того же соединения или между соединениями с shared cache.
*   **Shared cache** — режим разделяемого кэша страниц между соединениями одного процесса (`file:db?cache=shared`).
*   **SQLITE_THREADSAFE** — compile-time опция: 0 (single-thread), 1 (serialized, по умолчанию), 2 (multi-thread).

## Базовые концепции

### Режимы BEGIN

| Режим | Когда захватывает блокировку | Когда использовать |
| :--- | :--- | :--- |
| `BEGIN` (DEFERRED) | При первом чтении/записи | По умолчанию; риск `SQLITE_BUSY` в момент COMMIT |
| `BEGIN IMMEDIATE` | Сразу при BEGIN | Check-then-write паттерны; атомарные операции; предсказуемая обработка BUSY |
| `BEGIN EXCLUSIVE` | Сразу, EXCLUSIVE | Миграции, VACUUM-подобные операции; блокирует всех |

Ключевое следствие: в DEFERRED-транзакции `SQLITE_BUSY` может прийти на `COMMIT`, после того как приложение уже выполнило работу. `BEGIN IMMEDIATE` переносит конфликт на начало транзакции, где его просто обработать (повтор).

### Изоляция

SQLite предоставляет SERIALIZABLE-изоляцию. Читатели в WAL-режиме видят снапшот на момент начала транзакции (детали — в [WAL-файле](./sqlite_sre_operations.md)). `PRAGMA read_uncommitted` меняет поведение только для соединений с shared cache: разрешает грязное чтение между ними. Для обычных соединений она не действует.

### Один писатель

В любой момент времени только одно соединение может писать (WAL: RESERVED/WAL_WRITE lock). Это фундаментальное ограничение: десятки одновременных писателей — сценарий для клиент-серверной СУБД.

### BUSY vs LOCKED

Разница принципиальна (подтверждена документацией sqlite.org/rescode.html):

*   `SQLITE_BUSY` — конфликт с **другим** соединением, обычно в другом процессе. Обрабатывается `busy_timeout` / `busy_handler` / повтором.
*   `SQLITE_LOCKED` — конфликт **внутри того же** соединения (например, `DROP TABLE` при активном чтении этой таблицы на том же соединении) или между соединениями с shared cache. `busy_timeout` **не** помогает; нужно перестроить логику (закрыть курсоры, не делать DDL в открытых транзакциях).

### Потоки и потокобезопасность

| SQLITE_THREADSAFE | Режим | Смысл |
| :--- | :--- | :--- |
| 0 | Single-thread | Мьютексы вырезаны; нельзя использовать из нескольких потоков |
| 1 | Serialized (по умолчанию) | Безопасно использовать одно соединение из нескольких потоков |
| 2 | Multi-thread | Безопасно, если одно соединение не используется двумя потоками одновременно |

*   Проверить сборку: `PRAGMA compile_options;` → строка `THREADSAFE=N`; в C — `sqlite3_threadsafe()`.
*   Изменить в рантайме: `sqlite3_config(SQLITE_CONFIG_SERIALIZED / MULTITHREAD / SINGLETHREAD)`; на уровне соединения — флаги `SQLITE_OPEN_FULLMUTEX` / `SQLITE_OPEN_NOMUTEX`.
*   `PRAGMA threads` — максимальное число рабочих потоков для параллельных операций (сортировка); `0` отключает.

### Shared cache

```python
# URI с разделяемым кэшем (URI filenames должны быть включены)
sqlite3.connect('file:data.db?cache=shared', uri=True)
```

Shared cache даёт разделяемый кэш страниц между соединениями одного процесса, но добавляет table-level блокировки (расширенный код `SQLITE_LOCKED_SHAREDCACHE`). По умолчанию выключен.

## Практические сценарии

### 1. Check-then-write через BEGIN IMMEDIATE

```sql
BEGIN IMMEDIATE;
SELECT value FROM config WHERE key = 'timeout';
-- приложение вычисляет новое значение
UPDATE config SET value = 60 WHERE key = 'timeout';
COMMIT;
```

Если `BEGIN IMMEDIATE` вернул `SQLITE_BUSY` — другой писатель активен; повторите после паузы. Гарантия: после успешного `BEGIN IMMEDIATE` до `COMMIT` других `SQLITE_BUSY` не будет.

### 2. Обработка SQLITE_BUSY (Python)

```python
import sqlite3, time

def with_retry(db, fn, attempts=5, base_delay=0.05):
    for attempt in range(attempts):
        try:
            return fn(db)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if ("locked" in msg or "busy" in msg) and attempt < attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
            else:
                raise
```

### 3. busy_timeout на каждом соединении

```sql
PRAGMA busy_timeout = 5000;  -- 5 секунд ожидания перед SQLITE_BUSY
```

В Python: `sqlite3.connect(path, timeout=5)`. Устанавливайте сразу после открытия соединения (см. [эксплуатацию](./sqlite_sre_operations.md)).

### 4. SAVEPOINT — вложенные транзакции

```sql
BEGIN;
SAVEPOINT sp1;
INSERT INTO log(msg) VALUES ('step1');
-- при ошибке:
ROLLBACK TO sp1;   -- откат только до sp1, транзакция жива
RELEASE sp1;       -- подтверждение sp1
COMMIT;
```

### 5. Проверка потокобезопасности сборки

```bash
sqlite3 :memory: "PRAGMA compile_options;" | grep THREADSAFE
# → THREADSAFE=2
```

## Операции и команды

### Коды результатов (primary result codes)

| Код | Число | Смысл |
| :--- | :--- | :--- |
| `SQLITE_OK` | 0 | Успех |
| `SQLITE_ERROR` | 1 | Общая ошибка |
| `SQLITE_INTERNAL` | 2 | Внутренняя ошибка SQLite |
| `SQLITE_PERM` | 3 | Нет прав |
| `SQLITE_ABORT` | 4 | Операция прервана callback |
| `SQLITE_BUSY` | 5 | Занято другим соединением/процессом |
| `SQLITE_LOCKED` | 6 | Заблокировано в этом соединении/shared cache |
| `SQLITE_NOMEM` | 7 | Не хватает памяти |
| `SQLITE_READONLY` | 8 | Попытка записи в read-only |
| `SQLITE_INTERRUPT` | 9 | Прервано явно |
| `SQLITE_IOERR` | 10 | Ошибка ввода-вывода |
| `SQLITE_CORRUPT` | 11 | Повреждение БД (`database disk image is malformed`) |
| `SQLITE_NOTFOUND` | 12 | Не найдено (внутренние API) |
| `SQLITE_FULL` | 13 | БД или диск полон |
| `SQLITE_CANTOPEN` | 14 | Не удалось открыть файл |
| `SQLITE_PROTOCOL` | 15 | Нарушение протокола блокировок |
| `SQLITE_EMPTY` | 16 | БД пуста (внутренние API) |
| `SQLITE_SCHEMA` | 17 | Схема изменилась — переподготовьте запрос |
| `SQLITE_TOOBIG` | 18 | Строка/индекс слишком велик |
| `SQLITE_CONSTRAINT` | 19 | Нарушение ограничения (UNIQUE, NOT NULL, FK...) |
| `SQLITE_MISMATCH` | 20 | Несовпадение типа (datatype mismatch) |
| `SQLITE_MISUSE` | 21 | API вызван некорректно |
| `SQLITE_NOLFS` | 22 | Нет large-file support |
| `SQLITE_AUTH` | 23 | Авторизация запрещает |
| `SQLITE_FORMAT` | 24 | Ошибка формата |
| `SQLITE_RANGE` | 25 | Параметр вне диапазона (bind) |
| `SQLITE_NOTADB` | 26 | Файл не является БД |
| `SQLITE_NOTICE` | 27 | Уведомление (например, recover) |
| `SQLITE_WARNING` | 28 | Предупреждение |
| `SQLITE_ROW` | 100 | Есть следующая строка |
| `SQLITE_DONE` | 101 | Выполнено, строк больше нет |

Расширенные коды (extended result codes) уточняют причину: `SQLITE_BUSY_TIMEOUT`, `SQLITE_BUSY_RECOVERY`, `SQLITE_BUSY_SNAPSHOT`, `SQLITE_LOCKED_SHAREDCACHE`, `SQLITE_LOCKED_VTAB`, `SQLITE_CORRUPT_INDEX`, `SQLITE_CORRUPT_SEQUENCE`, `SQLITE_CORRUPT_VTAB`, семейство `SQLITE_IOERR_*` (`READ`, `WRITE`, `FSYNC`, `DELETE`, `SHMLOCK`, `SHMOPEN`, `CORRUPTFS` и др.). Включаются на соединении через `sqlite3_extended_result_codes()`.

## Устранение неполадок

| Ошибка (текст) | Код | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `database is locked` | SQLITE_BUSY | Другой процесс пишет; превышен busy_timeout | `busy_timeout=5000+`; WAL; `BEGIN IMMEDIATE`; повтор |
| `database table is locked` | SQLITE_LOCKED | DDL/запись в той же транзакции, где открыт курсор | Закрыть курсоры; DDL вне транзакции |
| `disk I/O error` | SQLITE_IOERR | ФС/диск, права, нехватка места | `dmesg`, `df -h`, права на директорию |
| `database disk image is malformed` | SQLITE_CORRUPT | Повреждение файла БД | [Восстановление](./sqlite_recovery_diagnostics.md): `.recover`, бэкап |
| `database or disk is full` | SQLITE_FULL | Место на диске / лимит файла | `df -h`; очистить WAL/VACUUM |
| `unable to open database file` | SQLITE_CANTOPEN | Путь, права, директория не writable | `ls -l`; права `0700` на директорию |
| `database schema has changed` | SQLITE_SCHEMA | Схема изменилась между prepare и step | Переподготовить (re-prepare) запрос |
| `attempt to write a readonly database` | SQLITE_READONLY | URI `mode=ro`, права файла | Проверить URI/права |

## Рекомендации SRE

*   Для критичных операций используйте `BEGIN IMMEDIATE` — предсказуемая обработка конфликтов вместо сюрпризов на COMMIT.
*   `busy_timeout` ставьте на каждое соединение сразу после открытия.
*   `SQLITE_LOCKED` не лечится таймаутом — это архитектурная проблема в коде приложения.
*   Проверяйте `THREADSAFE` сборки перед использованием SQLite из пула потоков.
*   Полный диск обычно даёт `SQLITE_FULL`, а не `SQLITE_IOERR` — мониторьте место отдельно.

## Дополнительная информация

### См. также

*   [WAL, конкурентность и эксплуатация](./sqlite_sre_operations.md) — блокировки WAL и busy_timeout
*   [Восстановление и диагностика](./sqlite_recovery_diagnostics.md) — обработка SQLITE_CORRUPT
*   [Официальная документация: Result codes](https://sqlite.org/rescode.html)
*   [Официальная документация: Threading](https://sqlite.org/threadsafe.html)
