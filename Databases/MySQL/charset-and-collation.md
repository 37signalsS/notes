# Кодировки и сортировки в MySQL: character set, collation

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation

> **Статус:** MySQL 8.0 достиг End of Life в апреле 2026 (выпуск 8.0.46).
> Описанное применимо к 8.0, но для новых инсталляций и обновлений —
> MySQL 8.4 LTS.

Тема выглядит узкой, но это один из главных источников аварий: ошибка
`Illegal mix of collations` возникает в самый неподходящий момент — при
миграции, при добавлении внешней таблицы или при неожиданном сравнении
строк из разных колонок. Здесь только то, что нужно, чтобы выбрать кодировку
один раз правильно и диагностировать несовместимость, когда она возникла.

Партнёры по теме: [Индексы в MySQL](./indexing.md) — длина ключа индекса
зависит от кодировки; [SQL mode](./sql-mode.md) — строгий режим ловит часть
проблем на записи; [Online Schema Change](./Operations/online-schema-change.md) —
перекодировка большой таблицы; [Часовые пояса](./timezone.md) — вторая
серверная настройка уровня сервера/сессии.

## Определения

| Термин | Значение |
| :--- | :--- |
| Character set (кодировка) | Набор символов и метод их кодирования в байты. Определяет, какие символы вообще можно записать |
| Collation (сортировка) | Правила сравнения, сортировки и регистронезависимости **внутри** кодировки |
| `Maxlen` | Максимальное число байт на один символ в кодировке. Главный параметр для расчёта размера |
| `PAD SPACE` / `NO PAD` | Считаются ли конечные пробелы значимыми при сравнении |
| `ai` / `as` | Accent-Insensitive / Accent-Sensitive — чувствительность к диакритике |
| `ci` / `cs` | Case-Insensitive / Case-Sensitive — чувствительность к регистру |
| Coercibility | Правило разрешения конфликта при сравнении выражений с разными collation |

## Базовые концепции

### utf8mb4, utf8mb3 и utf8 — почему это разные вещи

| Кодировка | Байт на символ | Диапазон | Статус |
| :--- | :--- | :--- | :--- |
| `utf8mb4` | 1–4 | BMP и дополнительные плоскости | Рекомендуема, значение по умолчанию на 8.0 |
| `utf8mb3` | 1–3 | Только BMP | Объявлена устаревшей в MySQL 8.0 |
| `utf8` | — | — | Устаревший псевдоним `utf8mb3` |
| `ucs2` | 2 | Только BMP | Объявлена устаревшей в MySQL 8.0.28 |
| `utf16`, `utf16le`, `utf32` | 2–4 | BMP и дополнительные плоскости | Не объявлены устаревшими, но на практике не используются |

Историческая причина путаницы: в MySQL 5.x `utf8` означал 3-байтовый UTF-8, потому что
таков был Unicode на момент появления. UTF-8 с 4 байтами на символ (для символов
вне BMP — эмодзи, часть иероглифов, музыкальные символы) стал отдельной
кодировкой `utf8mb4`. Имя `utf8` осталось за старой, узкой версией.

Практические следствия:

- Символ вне BMP (например, эмодзи) в колонке `utf8mb3` **не сохранится**.
- С **MySQL 8.0.28** в `INFORMATION_SCHEMA` и в выводе `SHOW` вместо `utf8`
  показывается `utf8mb3` — это убирает часть путаницы, но ломает скрипты,
  которые парсят вывод `SHOW`.
- `utf8` объявлен устаревшим псевдонимом `utf8mb3`; в будущем ожидается его превращение
  в псевдоним `utf8mb4`. Планировать новые проекты только на `utf8mb4`.
- У `utf16le` поддержка коллаций ограничена (`utf16le_general_ci` и
  `utf16le_bin`), у `ucs2` сравнение побайтовое.

### Значения по умолчанию

```sql
SHOW VARIABLES LIKE 'character_set_server';
SHOW VARIABLES LIKE 'collation_server';
-- → character_set_server = utf8mb4
-- → collation_server      = utf8mb4_0900_ai_ci

SHOW CHARACTER SET LIKE 'utf%';
-- → Charset | Description    | Default collation | Maxlen
-- → utf8mb3  | UTF-8 Unicode  | utf8mb3_general_ci|      3
-- → utf8mb4  | UTF-8 Unicode  | utf8mb4_0900_ai_ci|      4
```

Значения `character_set_server` и `collation_server` используются **только** как
умолчания для `CREATE DATABASE` без явного указания кодировки — они не влияют на
кодировку существующих таблиц. Переменные можно менять динамически (`SET GLOBAL`),
но это не меняет кодировку уже созданных объектов.

```ini
[mysqld]
character_set_server = utf8mb4
collation_server      = utf8mb4_0900_ai_ci
```

### PAD SPACE против NO PAD — подводный камень при миграции

Это самый недооценённый аспект. Поведение колонок при сравнении меняется при смене
collation, и запросы, которые годами возвращали результат, начинают возвращать другое.

| Collations на основе UCA 9.0.0 и выше | Collations на основе более ранних версий UCA |
| :--- | :--- |
| `NO PAD` | `PAD SPACE` |

Следствие: при `NO PAD` строки `'a'` и `'a '` считаются **разными**; при `PAD SPACE` —
одинаковыми.

Важно: правило `PAD SPACE`/`NO PAD` применяется к **колонкам и выражениям с коллацией**,
а не к сравнению двух строковых литералов. Литералы сравниваются с использованием
`collation_connection`. Поэтому пример строится на сравнении колонки с литералом:
```sql
-- Колонка с PAD SPACE (старая коллация)
CREATE TABLE t_pad (c CHAR(10) COLLATE utf8mb4_bin);
INSERT INTO t_pad VALUES ('a');

SELECT c = 'a ' AS pad_equal FROM t_pad;
-- → pad_equal = 1   (конечный пробел игнорируется)

-- Колонка с NO PAD (новая коллация)
CREATE TABLE t_nopad (c CHAR(10) COLLATE utf8mb4_0900_bin);
INSERT INTO t_nopad VALUES ('a');

SELECT c = 'a ' AS pad_equal FROM t_nopad;
-- → pad_equal = 0   (конечный пробел значим)

-- То же через приведение литерала к коллации колонки
SELECT 'a' = 'a ' COLLATE utf8mb4_bin AS pad_equal;
-- → pad_equal = 1
SELECT 'a' = 'a ' COLLATE utf8mb4_0900_bin AS pad_equal;
-- → pad_equal = 0
```
Практическое следствие для индексов: при `PAD SPACE` значение `'a'` и `'a '` хранят
один и тот же индексный ключ, поэтому `WHERE c = 'a'` находит обе строки; при `NO PAD` —
это разные ключи и разные строки. Уникальный индекс при `PAD SPACE`
считает `'a'` и `'a '` конфликтующими.
Обратите внимание на две особенности именно бинарных коллаций:

- `utf8mb4_bin` имеет `PAD_ATTRIBUTE = PAD SPACE`.
- `utf8mb4_0900_bin` (появился в MySQL 8.0.17) имеет `PAD_ATTRIBUTE = NO PAD`.

То есть **два похожих по названию `_bin`-collations ведут себя по-разному** при сравнении
строк с конечными пробелами. Проверяйте атрибут, а не выбирайте по имени.
```sql
SELECT COLLATION_NAME, PAD_ATTRIBUTE, ID
FROM INFORMATION_SCHEMA.COLLATIONS
WHERE CHARACTER_SET_NAME = 'utf8mb4' AND COLLATION_NAME LIKE '%bin';
-- → COLLATION_NAME     | PAD_ATTRIBUTE | ID
-- → utf8mb4_bin        | PAD SPACE     | 46
-- → utf8mb4_0900_bin   | NO PAD        | 309
```

Проверить все коллации конкретного семейства:

```sql
SELECT COLLATION_NAME, PAD_ATTRIBUTE, IS_DEFAULT
FROM INFORMATION_SCHEMA.COLLATIONS
WHERE CHARACTER_SET_NAME = 'utf8mb4'
ORDER BY ID LIMIT 15;
-- → utf8mb4_general_ci  | PAD SPACE | NULL
-- → utf8mb4_bin         | PAD SPACE | NULL
-- → ...
-- → utf8mb4_0900_ai_ci  | NO PAD    | Yes
```

### general_ci против unicode_ci — точность против скорости

Коллации на UCA поддерживают **expansions** (один символ равен комбинации
других) и **contractions**; `general_ci` сравнивает символы один к одному:

- `utf8mb4_general_ci` быстрее `utf8mb4_unicode_ci`, но менее точен.
- В `general_ci` `ß` = `s`, в `unicode_ci` и `0900`-коллациях `ß` = `ss`
  (немецкий словарный порядок).
- В `general_ci` все дополнительные символы (вне BMP) имеют один вес
  (`0xfffd`) и сравниваются равными — `COUNT(DISTINCT)` и уникальные
  индексы ведут себя неожиданно.
- Коллации на UCA 9.0.0 и выше быстрее коллаций на более ранних UCA.

Прямое следствие для миграции: перевод колонки с `utf8mb4_general_ci` на
`utf8mb4_0900_ai_ci` меняет **семантику равенства** — пары, которые были
различными (`ß` и `ss`), становятся равными. Уникальные индексы после
конвертации могут начать отклонять ранее допустимые дубликаты. Проверяйте
на копии данных до cut-over.

### Как выбрать collation

| Задача | Рекомендуемая collation | Комментарий |
| :--- | :--- | :--- |
| Общий случай, поиск без учёта регистра | `utf8mb4_0900_ai_ci` | Значение по умолчанию на 8.0; 0900-коллации быстрее коллаций на UCA < 9.0.0 |
| Нужна чувствительность к регистру | `utf8mb4_0900_as_cs` | Точное сравнение букв |
| Логины, токены, хеши | `utf8mb4_bin` или `utf8mb4_0900_bin` | Сравнение по кодам символов без приведения регистра; различаются pad-атрибутом и весами |
| Упорядованение по русскому языку | `utf8mb4_ru_0900_ai_ci` | Языковая специфика порядка |
| Устаревшая таблица, перенос без риска | оставить текущую | `utf8mb4_general_ci` быстрее `utf8mb4_unicode_ci`, но менее точен и имеет `PAD SPACE` |

Обозначения в имени: `utf8mb4` + `_ru` (язык) + `_0900` (версия UCA) +
`_ai` (диакритика не значима) + `_ci` (регистр не значим).

`LOWER()` и `UPPER()` приводят регистр **по collation своего аргумента** —
ещё один способ случайно изменить поведение запроса при смене collation.

**Что неявно задаёт `BINARY`:** атрибут `BINARY` для строк в MySQL 8.0
объявлен устаревшим и неоднозначным — у кодировки `utf8mb4` несколько
`_bin`-collations, поэтому `BINARY` не указывает ни на одну конкретно.
Если требуется побайтовое сравнение, указывайте явную `_bin`-collation.

### Уровни применения кодировки

```
Сервер            character_set_server / collation_server   (только умолчание для CREATE DATABASE)
  └─ База данных  CHARACTER SET / COLLATE в CREATE DATABASE
       └─ Таблица  DEFAULT CHARACTER SET / COLLATE в CREATE TABLE
            └─ Колонка  CHARACTER SET / COLLATE в определении колонки
                 └─ Строковый литерал  _utf8mb4'...' introducer
```

Для литералов introducer записывается с подчёркиванием: `_utf8mb4'текст'`.

Проверить фактические значения на каждом уровне:

```sql
SHOW CREATE DATABASE shop\G
SHOW CREATE TABLE shop.orders\G

SELECT TABLE_NAME, TABLE_COLLATION
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'shop';
-- → TABLE_NAME | TABLE_COLLATION
-- → orders     | utf8mb4_0900_ai_ci
```

Отдельно про `character_set_database` / `collation_database`: сервер устанавливает их
автоматически при смене текущей базы (`USE`); они не настраиваются вручную. Роли —
умолчание для `LOAD DATA` без `CHARACTER SET` и для строковых параметров
хранимых процедур, созданных в этой базе.

## Практические сценарии

### Сценарий 1. Диагностика «Illegal mix of collations»

Ошибка 1267 возникает при сравнении строк с несовместимыми collation.

```sql
SELECT a.name FROM users a JOIN external_users b ON a.name = b.name;
-- → ERROR 1267 (HY000): Illegal mix of collations (utf8mb4_0900_ai_ci,IMPLICIT) and (utf8mb4_general_ci,COERCIBLE) for operation '='
```

Разбор текста ошибки: слева — collation левого операнда с признаком `IMPLICIT`,
справа — правого с признаком `COERCIBLE`. Прямой запрос коллаций:

```sql
SELECT COLLATION('test') AS literal_collation,
       COLLATION(_utf8mb4'test' COLLATE utf8mb4_bin) AS explicit_collation;
-- → utf8mb4_0900_ai_ci | utf8mb4_bin
```

Определить collation колонок, участвующих в сравнении:

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME IN ('users', 'external_users')
  AND COLUMN_NAME = 'name';
-- → TABLE_SCHEMA | TABLE_NAME       | COLUMN_NAME | COLLATION_NAME
-- → shop         | users            | name        | utf8mb4_0900_ai_ci
-- → ext          | external_users   | name        | utf8mb4_general_ci
```

Быстрые решения по возрастанию стоимости:

```sql
-- 1. Явная COLLATE в запросе (быстро, но не лечит причину)
SELECT a.name FROM users a JOIN external_users b
  ON a.name = b.name COLLATE utf8mb4_0900_ai_ci;

-- 2. Привести внешнюю таблицу к общей кодировке (правильно)
ALTER TABLE ext.external_users
  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

> **Осторожно:** `CONVERT TO CHARACTER SET` — перекодировка данных **и** изменение
> кодировки колонок, а не только сравнения. На большой таблице — перестройка
> (см. [Online Schema Change](./Operations/online-schema-change.md)).

### Сценарий 2. Создание новой базы с правильной кодировкой

```sql
CREATE DATABASE shop
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
-- → Query OK, 1 row affected
```

```sql
-- Проверка
SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
FROM INFORMATION_SCHEMA.SCHEMATA
WHERE SCHEMA_NAME = 'shop';
-- → DEFAULT_CHARACTER_SET_NAME | DEFAULT_COLLATION_NAME
-- → utf8mb4                   | utf8mb4_0900_ai_ci
```

Явно задавать кодировку в `CREATE DATABASE` — обязательная практика: полагаться на
`character_set_server` значит зависеть от конфигурации конкретного сервера.

### Сценарий 3. Перекодировка существующей таблицы

```sql
-- Перекодировать данные и изменить collation всех строковых колонок
ALTER TABLE shop.orders
  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci,
  ALGORITHM=COPY;
-- → Query OK, 0 rows affected (1823.44 sec)
```

Разница между двумя формами, которые путают чаще всего:

| Форма | Что меняет | Данные |
| :--- | :--- | :--- |
| `ALTER TABLE t DEFAULT CHARACTER SET utf8mb4` | Только умолчание для **новых** колонок | Не трогает существующие |
| `ALTER TABLE t CONVERT TO CHARACTER SET utf8mb4` | Кодировку **всех** колонок | Перекодирует |
| `ALTER TABLE t MODIFY COLUMN c VARCHAR(100) CHARACTER SET utf8mb4` | Кодировку **одной** колонки | Перекодирует только её |

Для разовой конвертации значений **внутри запроса** (без изменения схемы) —
`CONVERT(expr USING charset)`:

```sql
SELECT CONVERT(name USING utf8mb4) FROM ext.legacy_table;
```

Порядок работы для большой таблицы:

```
1. Снять резервную копию
2. Проверить семантику равенства на копии (см. «general_ci против unicode_ci»)
3. Перекодировать теневую таблицу (gh-ost или pt-online-schema-change)
4. Проверить pt-table-checksum
5. Cut-over в окне обслуживания
```

> **Репликация:** `ALTER TABLE ... CONVERT TO` — DDL, реплицируется на реплики как
> обычное изменение схемы. Планируйте окно перекодировки на всю топологию и проверяйте
> совместимость collation на репликах до cut-over.

После **апгрейда версии сервера** проверяйте таблицы, созданные старой версией:
`CHECK TABLE ... FOR UPGRADE` (или `mysqlcheck --check-upgrade`) находит таблицы,
чьи индексы требуют перестройки из-за изменений правил collation между версиями.

### Сценарий 4. Ошибка «Specified key was too long»

```sql
CREATE TABLE shop.articles (body VARCHAR(1000), INDEX idx_body (body));
-- → ERROR 1071 (42000): Specified key was too long; max key length is 3072 bytes
```

Причина — лимит длины ключа индекса, зависящий от кодировки и формата строки InnoDB.
| Параметр | Значение |
| :--- | :--- |
| `DYNAMIC`, `COMPRESSED` | 3072 байт |
| `REDUNDANT`, `COMPACT` | 767 байт |
| `innodb_page_size = 8KB` | 1536 байт (масштабируется от 3072 для 16KB) |
| `innodb_page_size = 4KB` | 768 байт |
| MyISAM, префикс индекса | 1000 байт |
| Максимум колонок в составном индексе | 16 |

Расчёт: `VARCHAR(N)` в `utf8mb4` занимает до `N × 4` байт в ключе.
`VARCHAR(768)` — ровно 3072 байт, предел; `VARCHAR(769)` — уже ошибка.

> **Оговорка о единицах измерения:** пределы измеряются в **байтах**, но в `CREATE TABLE`
> длина префикса указывается в **символах** для небинарных строк и в байтах для
> бинарных. Путаница между единицами — типичная причина непонимания ошибки.

Решения:

```sql
-- 1. Префиксный индекс (работает, но ухудшает точность выборки)
CREATE TABLE shop.articles (body VARCHAR(1000), INDEX idx_body (body(191)));

-- 2. Использовать хеш-колонку (частый приём для длинных строк)
CREATE TABLE shop.articles (
    body VARCHAR(1000),
    body_hash BINARY(32),
    INDEX idx_body_hash (body_hash)
);

-- 3. Привести таблицу к DYNAMIC (значение по умолчанию на 8.0)
-- Проверить текущий формат:
SELECT NAME, ROW_FORMAT FROM INFORMATION_SCHEMA.INNODB_TABLES
WHERE NAME = 'shop/articles';
```

Переменная `innodb_large_prefix`, управлявшая этим лимитом в 5.x, объявлена устаревшей
в **MySQL 5.7.7** (вместе с `innodb_file_format` и родственными опциями) и **удалена в
MySQL 8.0.0** — в `my.cnf` её указывать нельзя.
### Сценарий 5. Разница регистра при сравнении

```sql
-- Умолчание utf8mb4_0900_ai_ci: регистр не важен
SELECT 'ABC' = 'abc' AS equal_ignoring_case;
-- → 1

-- Явная чувствительность к регистру
SELECT 'ABC' = 'abc' COLLATE utf8mb4_0900_as_cs AS equal_sensitive;
-- → 0
```

Индексы наследуют collation колонки. Если в условии указана другая collation, индекс
перестаёт использоваться:

```sql
CREATE TABLE users (name VARCHAR(64) COLLATE utf8mb4_0900_ai_ci, INDEX idx_name (name));

EXPLAIN SELECT * FROM users WHERE name = 'Alice';
-- → key: idx_name  (индекс используется)

EXPLAIN SELECT * FROM users WHERE name = 'Alice' COLLATE utf8mb4_bin;
-- → key: NULL  type: ALL  (полное сканирование!)
```

Практическое правило: **не указывайте `COLLATE` в условии по колонке**, если индекс
по этой колонке нужен. Для регистронезависимого сравнения — `LOWER(col) = LOWER(?)`
и индекс на выражение (функциональный индекс — с MySQL 8.0.13, см. [Индексы](./indexing.md)).

### Сценарий 6. Настройка кодировки на стороне клиента

```bash
mysql --default-character-set=utf8mb4 -u app -p shop
# → подключение с заявленной кодировкой utf8mb4
```

```sql
SHOW VARIABLES LIKE 'character_set%';
-- → character_set_client    = utf8mb4   ← что клиент заявил
-- → character_set_connection= utf8mb4   ← с чем работает соединение
-- → character_set_database  = utf8mb4   ← кодировка текущей базы (устанавливает сервер)
-- → character_set_results   = utf8mb4   ← в какой кодировке возвращать результат
-- → character_set_system    = utf8mb3   ← всегда utf8mb3; менять нельзя
```

`character_set_system` всегда `utf8mb3` и не настраивается (до 8.0.28
отображался как `utf8`) — ограничение сервера, а не ошибка конфигурации.

`SET NAMES` устанавливает **три** переменные кодировки и `collation_connection`
в коллацию по умолчанию для указанной кодировки:

```sql
SET NAMES utf8mb4;
-- эквивалентно трём SET: character_set_client, character_set_results,
-- character_set_connection + collation_connection в дефолт кодировки

SET NAMES utf8mb4 COLLATE utf8mb4_bin;   -- вариант с явной коллацией
```

Существует и `SET CHARACTER SET <charset>` — она, в отличие от `SET NAMES`,
устанавливает `character_set_connection` и `collation_connection` в умолчания
**текущей базы** (`character_set_database` / `collation_database`).
В конфигурации клиента: `[client] default-character-set = utf8mb4`.
Клиентские программы (`mysql`, `mysqladmin`, `mysqlcheck` и др.) без явного указания
используют встроенную кодировку по умолчанию — обычно `utf8mb4`, — либо определяют
её по `LANG`/`LC_ALL` (Unix) или кодовой странице (Windows). В `mysql`-клиенте при
включённом auto-reconnect (не рекомендуется) лучше команда `charset`, а не `SET NAMES`:
`charset koi8r` отправляет `SET NAMES` и меняет кодировку для повторных подключений.

**Коннекторы приложений** — кодировку соединения задают на уровне драйвера, и это
влияет на экранирование и метаданные, а не только на передачу строк:

- **JDBC (Connector/J 8.0.26+):** приоритет `connectionCollation` →
  `characterEncoding` → `UTF8` (= `utf8mb4`); `characterEncoding=UTF-8`
  мапится на `utf8mb4`. В 8.0.25 и старше кодировка определялась
  автоматически, если свойства не заданы.
- **PHP mysqli:** `$mysqli->set_charset('utf8mb4')` задаёт кодировку
  соединения и, в отличие от `SET NAMES`, влияет на `real_escape_string()`.
  Строка `'UTF-8'` (с дефисом) — не имя кодировки MySQL, вызовет ошибку.
- **PHP PDO:** `charset=utf8mb4` в DSN: `new PDO('mysql:...;charset=utf8mb4', ...)`.

Несоответствие между тем, что заявил клиент, и тем, что может храниться в базе, даёт
ошибку `Incorrect string value`. Явно задавайте кодировку подключения.

**Смешанные версии (клиент 8.0 → сервер 5.7):** клиент 8.0 запрашивает
`utf8mb4_0900_ai_ci` как коллацию по умолчанию; сервер 5.7 её не знает,
`collation_connection` становится `utf8mb4_general_ci`.

Некоторые кодировки нельзя использовать как клиентские: `character_set_client` не
принимает `ucs2`, `utf16`, `utf16le`, `utf32` — `ERROR 1231 (42000)`.

### Сценарий 7. Инвентаризация кодировок в инфраструктуре

```sql
-- Какие кодировки в схеме
SELECT TABLE_SCHEMA, TABLE_COLLATION, COUNT(*) AS tables
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys')
GROUP BY TABLE_SCHEMA, TABLE_COLLATION;
-- → TABLE_SCHEMA | TABLE_COLLATION        | tables
-- → shop         | utf8mb4_0900_ai_ci     |    42
-- → legacy       | utf8mb3_general_ci     |     7   ← кандидаты на миграцию

-- Колонки, отличные от кодировки таблицы
SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME,
       c.CHARACTER_SET_NAME, c.COLLATION_NAME, t.TABLE_COLLATION
FROM INFORMATION_SCHEMA.COLUMNS c
JOIN INFORMATION_SCHEMA.TABLES t
  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE c.TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys')
  AND c.COLLATION_NAME IS NOT NULL
  AND c.COLLATION_NAME <> t.TABLE_COLLATION
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME
LIMIT 20;
-- → найденные расхождения — источник будущих «Illegal mix of collations»
```

Такой отчёт стоит выполнять **до** миграции схемы: он показывает объём работы
и неожиданные колонки в неочевидных таблицах.

### Сценарий 8. Сортировка русского текста

```sql
-- Порядок по русской локали
SELECT name FROM products ORDER BY name COLLATE utf8mb4_ru_0900_ai_ci;

-- Сравнение с учётом диакритики (важно для имён: «Андрей» ≠ «Андрeй»)
SELECT 'Ёлка' = 'Елка' COLLATE utf8mb4_0900_ai_ci AS ai_equal;
-- → 1
SELECT 'Ёлка' = 'Елка' COLLATE utf8mb4_0900_as_cs AS as_equal;
-- → 0
```

Смена collation колонки для правильной сортировки русского текста — это полная
перекодировка, а не изменение метаданных.

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `ERROR 1267: Illegal mix of collations ... for operation '='` | Колонки сравниваемых сторон имеют разные collation | Найти колонки через `INFORMATION_SCHEMA.COLUMNS`; привести одну сторону через `CONVERT TO CHARACTER SET` |
| `ERROR 1267 ... for operation 'like'` | Тот же конфликт в `LIKE` | То же решение |
| `ERROR 1267` в `GROUP BY` / `ORDER BY` / `UNION` | Тот же конфликт collation при агрегации или сортировке | То же решение: привести стороны или указать `COLLATE` |
| `ERROR 1071: Specified key was too long` | `VARCHAR` × 4 байта превышает лимит ключа | Сократить колонку, использовать префикс или хеш-колонку; проверить `ROW_FORMAT` |
| `ERROR 1170: BLOB/TEXT column used in key specification without a key length` | Индекс по `TEXT` без префикса | Указать префикс: `INDEX idx (body(191))` |
| `ERROR 1366: Incorrect string value` | Значение содержит символ вне диапазона кодировки (`utf8mb3` и 4-байтовый символ) | Перевести колонку и базу на `utf8mb4` |
| `ERROR 1231 (42000): Variable 'character_set_client' can't be set to the value of 'ucs2'` | `ucs2`/`utf16`/`utf16le`/`utf32` недопустимы как клиентские кодировки | Использовать другую кодировку подключения |
| `ERROR 1273 (HY000): Unknown collation: 'utf8mb4_0900_ai_ci'` | Коллация не существует в этой версии (например, 0900-коллация на сервере 5.7) | Указать существующую коллацию либо обновить сервер |
| Кодировка в `SHOW` отображается как `utf8`, а в I_S — как `utf8mb3` | Поведение MySQL начиная с 8.0.28 | Ожидаемо; не полагаться на разбор вывода `SHOW` |
| Символы сохраняются, но сортировка «неправильная» | Collocation отличается от языковой | Применить языковую коллацию: `utf8mb4_ru_0900_ai_ci` |
| Сравнение строк ведёт себя по-разному до и после миграции | Смена `PAD SPACE` на `NO PAD` или смена семейства коллаций (`general_ci` → `0900_ai_ci`) | Проверить `PAD_ATTRIBUTE` и семантику равенства; учесть в тестах сравнения с конечными пробелами |
| Уникальный индекс начал отклонять ранее допустимые значения | Смена правил сравнения при конвертации collation (`ß` = `s` → `ß` = `ss`) | Проверить семантику равенства на копии до конвертации; при необходимости — пересмотреть ограничения |
| `BINARY`-атрибут трактуется неожиданно | У `utf8mb4` несколько `_bin`-collations; атрибут `BINARY` объявлен устаревшим | Указать явную `_bin`-collation |
| `EXPLAIN` показывает полное сканирование при точном условии по колонке | `COLLATE` в условии не совпадает с collation колонки | Убрать `COLLATE` из условия либо добавить индекс на выражение |
| `CHECK TABLE ... FOR UPGRADE` / `mysqlcheck --check-upgrade` сообщает о таблице после апгрейда | Изменились правила collation между версиями, индексы требуют перестройки | Перестроить таблицу (`ALGORITHM=COPY` или dump/reload) |

## Лучшие практики

- **Всегда явно задавайте `CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci` в
  `CREATE DATABASE`.** Не полагаться на `character_set_server`.
- **`utf8mb4` и никаких других вариантов** для новых проектов. `utf8mb3` и `ucs2`
  объявлены устаревшими.
- **Не смешивать `VARCHAR` с `CHAR` в условиях сравнения** без явного приведения: правила
  pad-атрибута различаются.
- **Не указывать `COLLATE` в условии по колонке с индексом** — индекс перестанет
  использоваться.
- **Проверять `PAD_ATTRIBUTE` при миграции** коллаций, а не только имя.
- **Проверять семантику равенства** (`ß` = `s` против `ß` = `ss`) при смене
  семейства коллаций — уникальные индексы ведут себя иначе.
- **Снимать инвентаризацию кодировок перед миграцией схемы** — «неправильная»
  collation в неожиданной таблице — главный источник сюрпризов.
- **Задавать кодировку в коннекторе** (`mysqli_set_charset`, `characterEncoding`),
  а не только `SET NAMES` — экранирование зависит от кодировки соединения.
- **При дампе баз в `utf8mb4` — `--default-character-set=utf8mb4`**: значения
  конвертируются в кодировку, заданную этой опцией.
- **После апгрейда — `mysqlcheck --check-upgrade`**: находит таблицы, чьи
  индексы требуют перестройки из-за изменений collation.
- **`character_set_system` всегда `utf8mb3` и не настраивается.** Это ограничение сервера,
  а не ошибка конфигурации.

## Дополнительная информация

### Граничные случаи и ограничения

- **JSON-значения** обрабатываются в `utf8mb4` / `utf8mb4_bin` независимо от
  кодировки таблицы: сравнение JSON case-sensitive.
- **`utf8mb4_0900_bin` появился в MySQL 8.0.17** и отличается от `utf8mb4_bin` по
  весам (байты кодировки utf8mb4 против кодовых точек) и pad-атрибуту. Порядок
  сортировки одинаковый, скорость сортировки у `0900_bin` значительно выше.
- **`COLLATE` на строковом литерале** имеет наивысший coercibility-приоритет.
- **`ucs2`** объявлена устаревшей в MySQL 8.0.28 (поддержка снимается
  постепенно); `utf16`, `utf16le`, `utf32` устаревшими **не** объявлены.
- **Устаревшие collation идентификаторы** (например, `utf8mb3_general_ci`) продолжают
  работать в 8.x, но переход на 8.0-коллации меняет поведение сравнений.
- **`WEIGHT_STRING()`** — отладочный инструмент: веса строки в коллации.

### Внешние ресурсы

- [MySQL Reference Manual: Character Sets, Collations, Unicode](https://dev.mysql.com/doc/refman/8.4/en/charset.html)
- [MySQL Reference Manual: Unicode Character Sets](https://dev.mysql.com/doc/refman/8.4/en/charset-unicode-sets.html)
- [MySQL Reference Manual: Server Character Set and Collation](https://dev.mysql.com/doc/refman/8.4/en/charset-server.html)
- [MySQL Reference Manual: Connection Character Sets and Collations](https://dev.mysql.com/doc/refman/8.4/en/charset-connection.html)
- [MySQL Reference Manual: InnoDB Limits](https://dev.mysql.com/doc/refman/8.4/en/innodb-limits.html)
- [MySQL Reference Manual: Column Indexes](https://dev.mysql.com/doc/refman/8.4/en/column-indexes.html)

### См. также

- **[Индексы в MySQL](./indexing.md)** — функциональные индексы и решение
  проблемы с индексом при смене collation.
- **[SQL mode](./sql-mode.md)** — строгий режим и `NO_ZERO_DATE`.
- **[Online Schema Change](./Operations/online-schema-change.md)** — перекодировка
  большой таблицы без простоя.
- **[Часовые пояса](./timezone.md)** — `time_zone`, `log_timestamps`, `TIMESTAMP`.
- **[Конфигурация MySQL](./configuration.md)** — `character_set_server` и
  `collation_server` в my.cnf.
- **[Загрузка данных](./data-loading.md)** — `--default-character-set` при
  `LOAD DATA` и `mysqlimport`, ошибки `Illegal mix of collations`.
- **[Charset & Collation в MariaDB](../MariaDB/charset_and_collation.md)** —
  отличия ветки MariaDB (UCA 14.0.0-коллации).
- **[Конструкция CHAR и VARCHAR](https://dev.mysql.com/doc/refman/8.4/en/char.html)**
  — pad-атрибут в сравнениях.
