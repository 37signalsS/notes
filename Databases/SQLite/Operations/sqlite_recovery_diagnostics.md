# Восстановление и диагностика SQLite

**Актуально для:** SQLite 3.33+ (partial `integrity_check`); `.recover` — 3.29+

## Определения

*   **integrity_check** — низкоуровневая проверка формата и консистентности файла БД: последовательность записей в таблицах/индексах, отсутствие страниц, ошибки ограничений UNIQUE/CHECK/NOT NULL, целостность freelist.
*   **quick_check** — ускоренная подмножество-проверка; работает значительно быстрее.
*   **foreign_key_check** — проверка нарушений внешних ключей (integrity_check FK **не** проверяет).
*   **.recover** — dot-команда CLI, восстанавливающая данные напрямую из страниц файла, даже если БД повреждена (в отличие от `.dump`, которая останавливается на первой ошибке).
*   **lost_and_found** — таблица, в которую `.recover` помещает строки, не удающиеся отнести ни к одной таблице.
*   **dbstat** — eponymous virtual table с постраничной статистикой размещения данных (требуется `SQLITE_ENABLE_DBSTAT_VTAB`).
*   **sqlite3_analyzer** — утилита анализа заполнения БД на основе dbstat; объявлена deprecated в draft-документации 3.54.0 (замена — команда `.diskused`, может отсутствовать в сборках).
*   **data_version** — PRAGMA, значение которого меняется при коммитах **других** соединений; используется для инвалидации кэшей.

## Базовые концепции

### Что проверяет integrity_check

Согласно документации sqlite.org/pragma.html, `integrity_check` ищет:

*   Записи таблиц/индексов, нарушающие последовательность
*   Некорректно отформатированные записи
*   Отсутствующие страницы
*   Отсутствующие или избыточные записи индексов
*   Ошибки ограничений UNIQUE, CHECK, NOT NULL
*   Целостность freelist
*   Секции файла, используемые дважды или не используемые вовсе

**Не проверяет**: внешние ключи (используйте `foreign_key_check`). Возвращает максимум N ошибок (по умолчанию 100). Частичная проверка по таблице: `PRAGMA integrity_check('tablename')` (3.33.0+).

### Как возникает повреждение

Основные причины (sqlite.org/howtocorrupt.html):

*   Баги файловой системы и ОС (некорректный `fsync`, сбой питания)
*   Отмена POSIX-блокировок: `close()` любого файлового дескриптора БД в процессе снимает **все** advisory locks процесса — включая EXCLUSIVE-блокировку `VACUUM` (howtocorrupt §2.2)
*   Сетевые ФС (NFS/SMB) с некорректной реализацией блокировок
*   Одновременная запись из нескольких процессов на сетевой ФС
*   Аппаратные сбои, битые сектора
*   Использование `PRAGMA writable_schema` (прямая правка `sqlite_schema`)
*   Баги SQLite (например, WAL-reset bug — см. [эксплуатацию](./sqlite_sre_operations.md))

### .recover vs .dump

| | `.dump` | `.recover` |
| :--- | :--- | :--- |
| Механизм | Чтение через SQL-интерфейс | Реконструкция по страницам файла |
| При повреждении | Останавливается на первой ошибке | Восстанавливает все неповреждённые части |
| Потерянные строки | Нет | Помещает в `lost_and_found` |

### wal_checkpoint: возвращаемые значения

`PRAGMA wal_checkpoint;` возвращает три колонки: `busy`, `log`, `checkpointed`.

```sql
PRAGMA wal_checkpoint;
-- → 0|3|3
--   busy=0 (чекпоинт завершён), log=3 (фреймов в WAL), checkpointed=3 (перенесено)
```

`busy=1` — чекпоинт не завершён из-за блокировок (длинные чтения); повторите позже.

### PRAGMA data_version

Значение меняется, когда **другое** соединение коммитит изменения; коммиты своего соединения не меняют его. Используется для детекта внешних изменений (инвалидация кэша в приложении):

```sql
PRAGMA data_version;
-- → 2
```

## Практические сценарии

### 1. Диагностика повреждения

```bash
# Быстрая проверка
sqlite3 data.db "PRAGMA quick_check;"
# → ok

# Полная проверка
sqlite3 data.db "PRAGMA integrity_check;"
# → ok
# или список ошибок, например:
# → Page 12 is never used
# → Rowid missing from index idx_events

# Проверка внешних ключей (integrity_check их не проверяет!)
sqlite3 data.db "PRAGMA foreign_key_check;"
# → events|42|hosts|0   (таблица|rowid|родительская таблица|fk-индекс)

# Инкрементальная проверка (CLI)
sqlite3 data.db ".intck"
```

### 2. Восстановление через .recover

```bash
# Реконструкция в SQL-скрипт
sqlite3 corrupt.db .recover > recovered.sql

# Сборка новой БД из скрипта
sqlite3 recovered.db < recovered.sql

# Извлечь также страницы из freelist (осторожно: могут вернуться удалённые записи)
sqlite3 corrupt.db ".recover --ignore-freelist" > recovered.sql

# Другое имя для потерянных строк
sqlite3 corrupt.db ".recover --lost-and-found orphaned_rows" > recovered.sql

# Не восстанавливать rowid, не являющиеся INTEGER PRIMARY KEY
sqlite3 corrupt.db ".recover --no-rowids" > recovered.sql
```

Строки, не относящиеся ни к одной таблице, попадают в `lost_and_found` (колонки: `rootpgno`, `pgno`, `nfield`, `id`, `c0`, `c1`, ...). Строки из одного B-tree обычно группируются по `rootpgno`.

### 3. Анализ размещения данных (dbstat)

```sql
-- Размер по таблицам и индексам
SELECT name, sum(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY 2 DESC;

-- Эффективность упаковки (ближе к 100% — плотнее)
SELECT sum(pgsize - unused) * 100.0 / sum(pgsize) AS efficiency
FROM dbstat WHERE name = 'events';

-- Средний fan-out внутренних страниц (глубина B-tree)
SELECT avg(ncell) FROM dbstat WHERE name = 'events' AND pagetype = 'internal';

-- Агрегированный режим: одна строка на B-tree (3.31+)
SELECT pageno, (pgsize - unused) * 100.0 / pgsize AS efficiency
FROM dbstat('main', 1) WHERE name = 'events';
```

В CLI: `sqlite3 data.db ".dbstat"`. Требуется `SQLITE_ENABLE_DBSTAT_VTAB` (проверить через `PRAGMA compile_options`).

Утилита `sqlite3_analyzer` (TCL-скрипт поверх dbstat) объявлена deprecated в draft-документации 3.54.0; замена — `.diskused`, которая может отсутствовать в текущих сборках (проверяйте `.help`).

### 4. Мониторинг чекпоинта и внешних изменений

```bash
# Результат чекпоинта: busy|log|checkpointed
sqlite3 data.db "PRAGMA wal_checkpoint(TRUNCATE);"
# → 0|128|128

# Детект изменений другими процессами (для кэшей приложения)
sqlite3 data.db "PRAGMA data_version;"
# → 7
```

## Операции и команды

| Задача | Команда |
| :--- | :--- |
| Быстрая проверка | `PRAGMA quick_check;` |
| Полная проверка | `PRAGMA integrity_check;` |
| Частичная проверка (3.33+) | `PRAGMA integrity_check('table');` |
| Проверка FK | `PRAGMA foreign_key_check;` |
| Инкрементальная проверка | `sqlite3 db ".intck"` |
| Восстановление | `sqlite3 corrupt.db .recover > data.sql` |
| Размеры по объектам | `SELECT name, sum(pgsize) FROM dbstat GROUP BY name;` |
| Размеры в CLI | `sqlite3 db ".dbstat"` |
| Чекпоинт с результатом | `PRAGMA wal_checkpoint;` → `busy\|log\|checkpointed` |
| Версия данных | `PRAGMA data_version;` |

## Устранение неполадок

| Вывод integrity_check | Значение | Действие |
| :--- | :--- | :--- |
| `ok` | Целостна | — |
| `Page N is never used` | Дыра в файле (freelist/неиспользуемые страницы) | Обычно не критично; проверить freelist, VACUUM |
| `Rowid missing from index` / `duplicate rowid` | Расхождение индекса и таблицы | Восстановление из бэкапа или `.recover` |
| `freelist count is wrong` | Повреждён freelist | `.recover` или бэкап |
| `database disk image is malformed` (при открытии) | Повреждён заголовок/структура | `.recover`; если не помогает — бэкап |

## Рекомендации SRE

*   `quick_check` — в health-check/мониторинг (быстро); `integrity_check` — по расписанию (медленнее, полнее).
*   `foreign_key_check` — отдельно, если схема использует FK (integrity_check их не проверяет).
*   `.recover` — первая линия при повреждении; всегда проверяйте восстановленную БД через `integrity_check` перед возвратом в продакшен.
*   `wal_checkpoint` с `busy=1` — сигнал длинных чтений, блокирующих чекпоинт (см. [эксплуатацию](./sqlite_sre_operations.md)).
*   `PRAGMA data_version` — дешёвый способ инвалидировать кэш приложения при внешних изменениях.

## Дополнительная информация

### См. также

*   [WAL, конкурентность и эксплуатация](./sqlite_sre_operations.md) — чекпоинты и WAL-reset bug
*   [Транзакции, блокировки и коды ошибок](./sqlite_transactions_locking.md) — SQLITE_CORRUPT и другие коды
*   [Официальная документация: Recovery](https://sqlite.org/recovery.html)
*   [Официальная документация: DBSTAT](https://sqlite.org/dbstat.html)
*   [Официальная документация: How To Corrupt](https://sqlite.org/howtocorrupt.html)
