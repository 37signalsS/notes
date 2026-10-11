# Массивы и range-типы в PostgreSQL

**Актуально для:** PostgreSQL 14–18

## Определения

*   **Массив (`array`)** — тип, хранящий упорядоченный набор значений одного типа в одной колонке: `integer[]`, `text[]`, `timestamptz[]`. Доступ по индексу (с 1, не с 0), срезы, операторы `ANY`/`ALL`, агрегат `array_agg`, разворачивание `unnest`.
*   **Range-тип (`range`)** — тип, хранящий интервал `[lower, upper)` с границами: `int4range`, `int8range`, `numrange`, `tsrange`, `tstzrange`, `daterange`. Операторы пересечения `&&`, включения `@>`, `<@`, смежности `-|-`.
*   **Multirange-тип (`multirange`)** — упорядоченный набор непересекающихся непустых range-значений (введён в PG 14): `int4multirange`, `int8multirange`, `nummultirange`, `tsmultirange`, `tstzmultirange`, `datemultirange`. Поддерживает те же операторы GiST-индексации, что и range, плюс `+`, `*` (пересечение), `-` (разность) и кросс-тип сравнение range↔multirange.
*   **`ANY (array)`** — предикат: `x = ANY (ARRAY[1,2,3])` эквивалентен `x IN (1,2,3)`, но работает с колонкой-массивом и параметрами.
*   **`unnest`** — разворачивает массив в строки (set-returning function); в `FROM` — в строки, в `SELECT` — с `WITH ORDINALITY` сохраняет порядок.
*   **GIN-индекс на массиве** — инвертированный индекс: ускоряет `@>`, `<@`, `&&` (пересечение). B-Tree не индексирует элементы массива.
*   **GiST-индекс на range** — ускоряет `&&`, `@>`, `<@`, `-|-` (смежность). Ключевой индекс для расписаний и бронирования.

## Базовые концепции

### Когда массивы оправданы

Массив — денормализация «многие-ко-многим» в одну колонку. Оправдан, когда:

*   Набор мал и читается целиком (теги, роли, список ID).
*   Не нужен JOIN по элементам и не нужны ограничения на элемент (FK на элемент массива невозможен).
*   Важна атомарность записи всего набора.

Если нужны JOIN, FK, агрегации по элементам — нормализуйте в отдельную таблицу. Массивы нарушают 1НФ; это осознанный tradeoff.

### Range-типы: модель интервалов

Range хранит пару границ с флагами включения: `[1, 5)` — lower включён, upper исключён. Пустой range — `empty`. Бесконечные границы — `(,` / `,)`.

Ключевые операторы:

| Оператор | Смысл | Пример |
| :--- | :--- | :--- |
| `=` | сравнение диапазонов | `[1,5) = [1,5)` → true |
| `&&` | пересечение | `[1,5) && [4,8)` → true |
| `@>` | содержит | `[1,10) @> [2,3)` → true |
| `<@` | содержится в | `[2,3) <@ [1,10)` → true |
| `-|-` | смежность | `[1,5) -|- [5,9)` → true |
| `<<` | строго левее | `[1,2) << [3,4)` → true |
| `>>` | строго правее | `[3,4) >> [1,2)` → true |
| `&<` | не выходит правее | `[1,20) &< [18,20)` → true |
| `&>` | не выходит левее | `[7,20) &> [5,10)` → true |

### Multirange-типы

Multirange — упорядоченный набор непересекающихся непустых range-значений. Применяются, когда один интервал недостаточен для описания нескольких дискретных периодов (например, рабочее время с перерывом). Multirange поддерживает те же операторы GiST-индексации, что и range, плюс кросс-тип сравнение range↔multirange.

```sql
-- Создание multirange из двух range (рабочее время с перерывом)
SELECT tstzmultirange('[2026-10-04 09:00, 2026-10-04 12:00)'::tstzrange,
                     '[2026-10-04 13:00, 2026-10-04 17:00)'::tstzrange);
-- → {"[2026-10-04 09:00, 2026-10-04 12:00)","[2026-10-04 13:00, 2026-10-04 17:00)"}::tstzmultirange

-- Пересечение multirange с range
SELECT '[2026-10-04 10:00, 2026-10-04 14:00)'::tstzrange && '{"[2026-10-04 09:00, 2026-10-04 12:00)","[2026-10-04 13:00, 2026-10-04 17:00)"}'::tstzmultirange;
-- → true

-- Объединение непересекающихся multirange (оператор + не требует пересечения)
SELECT '{[5,10)}'::int4multirange + '{[15,20)}'::int4multirange;
-- → {[5,10), [15,20)}

-- Пересечение multirange
SELECT '{[5,15)}'::int4multirange * '{[10,20)}'::int4multirange;
-- → {[10,15)}

-- Разворачивание multirange в набор range
SELECT unnest('{[1,2), [3,4)}'::int4multirange);
-- → [1,2)
-- → [3,4)
```

### Индексация

*   **Массивы** — GIN. Стандартный класс операторов `array_ops` (для любых массивов, поддерживает `&&`, `@>`, `<@`, `=`); `array_nan_ops` — как `array_ops`, но считает `NaN` равными (нужен для массивов с плавающей точкой). Для `int[]` через расширение `intarray` доступен специализированный `gin__int_ops`, быстрее на целочисленных массивах и с дополнительными операторами (`|`, `&`, `@@`).
*   **Range** — GiST. Ускоряет `=`, `&&`, `@>`, `<@`, `<<`, `>>`, `-|-`, `&<`, `&>`. Для исключения пересечений — EXCLUSION-ограничение с GiST (см. [Ограничения](./constraints.md)).
*   **Multirange** — GiST. Поддерживает те же операторы, что и range, плюс кросс-тип сравнение range↔multirange.

## Практические сценарии

### Предварительные требования

1.  **PostgreSQL 14+** (range-типы и GIN/GiST — в стандартной поставке; multirange — с PG 14).
2.  **Права**: `CREATE` в схеме для индексов.
3.  **Расширения** (по необходимости):
    *   `intarray` — для GIN `gin__int_ops` на `integer[]` (trusted-расширение, см. [Расширения](./extensions_utility.md)).
    *   `btree_gist` — для `EXCLUDE USING gist (col WITH =)` на обычных типах (см. [Ограничения](./constraints.md)).

### 1. Массивы: создание, запись, поиск

```sql
CREATE TABLE articles (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title text NOT NULL,
    tags text[] NOT NULL DEFAULT '{}',
    views bigint[] NOT NULL DEFAULT '{}'   -- просмотры по дням
);

INSERT INTO articles (title, tags) VALUES
    ('PostgreSQL arrays', ARRAY['db','postgres','sql']),
    ('Range types',       ARRAY['db','postgres']);

-- Поиск по элементу: статьи с тегом 'postgres'
SELECT title FROM articles WHERE 'postgres' = ANY (tags);
-- → PostgreSQL arrays
-- → Range types

-- Поиск по вхождению подмножества: статьи с обоими тегами
SELECT title FROM articles WHERE tags @> ARRAY['db','sql'];
-- → PostgreSQL arrays
```

### 2. Массивы: агрегация и разворачивание

```sql
-- Собрать ID в массив
SELECT array_agg(id ORDER BY id) AS id_list FROM articles;
-- → {1,2}

-- Развернуть массив в строки с сохранением порядка
SELECT ord, tag
FROM articles, unnest(tags) WITH ORDINALITY AS u(tag, ord)
WHERE id = 1;
-- → ord | tag
-- → 1   | db
-- → 2   | postgres
-- → 3   | sql

-- Индексация: GIN на массиве
CREATE INDEX idx_articles_tags ON articles USING gin (tags);
```

### 3. Range-типы: бронирование без пересечений

```sql
CREATE TABLE bookings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room int NOT NULL,
    during tstzrange NOT NULL,
    EXCLUDE USING gist (room WITH =, during WITH &&)   -- см. Ограничения
);

INSERT INTO bookings (room, during) VALUES
    (1, '[2026-10-04 10:00, 2026-10-04 12:00)');

-- Пересечение: найдёт конфликт
SELECT id FROM bookings
WHERE room = 1 AND during && '[2026-10-04 11:00, 2026-10-04 13:00)';
-- → 1

-- GiST-индекс (создаётся автоматически EXCLUDE; явно — для чистого поиска)
CREATE INDEX idx_bookings_during ON bookings USING gist (during);
```

### 4. Range-типы: арифметика и границы

```sql
-- Границы и пустой range
SELECT lower('[1,5)'::int4range), upper('[1,5)'::int4range),
       isempty('empty'::int4range);
-- → 1 | 5 | t

-- Объединение пересекающихся range
SELECT '[1,5)'::int4range + '[4,8)'::int4range;
-- → [1,9)

-- Смежность (без пересечения, но границы соприкасаются)
SELECT '[1,5)'::int4range -|- '[5,9)'::int4range;
-- → t
```

### 5. Multirange-типы: сложные интервалы

```sql
CREATE TABLE shifts (
    employee int NOT NULL,
    workday date NOT NULL,
    active tstzmultirange NOT NULL,
    PRIMARY KEY (employee, workday)
);

-- Индекс для пересечения
CREATE INDEX idx_shifts_active ON shifts USING gist (active);

-- Вставка: сотрудник работает с 9:00 до 12:00 и с 13:00 до 17:00
INSERT INTO shifts (employee, workday, active) VALUES
    (1, '2026-10-04',
     tstzmultirange('[2026-10-04 09:00, 2026-10-04 12:00)'::tstzrange,
                    '[2026-10-04 13:00, 2026-10-04 17:00)'::tstzrange));

-- Найти сотрудников, работающих в пересекающийся период
SELECT employee FROM shifts
WHERE active && tstzrange('[2026-10-04 11:30, 2026-10-04 14:00)'::tstzrange);
-- → 1

-- Развернуть multirange в отдельные range для анализа
SELECT employee, unnest(active) AS work_period
FROM shifts WHERE employee = 1;
-- → 1 | [2026-10-04 09:00, 2026-10-04 12:00)
-- → 1 | [2026-10-04 13:00, 2026-10-04 17:00)
```

### 6. Операционная поддержка: мониторинг и обслуживание

#### GIN-индексы: fastupdate и очистка pending list

GIN-индекс по умолчанию использует **fastupdate**: новые записи сначала накапливаются в pending list, затем пакетно сливаются в основной индекс. Это ускоряет вставки, но большой pending list замедляет поиск (он сканируется дополнительно) и при превышении `gin_pending_list_limit` (по умолчанию 1 МБ) вызывает синхронную очистку с паузой вставки.

```sql
-- Принудительная очистка pending list для конкретного GIN-индекса
SELECT gin_clean_pending_list('idx_articles_tags');
-- → 1  (количество удалённых страниц pending list)
```

Для bulk-загрузок оптимальнее временно отключить fastupdate:

```sql
CREATE INDEX idx_articles_tags_bulkinsert ON articles USING gin (tags) WITH (fastupdate = off);
```

Альтернативный подход для больших загрузок — удалить индекс и пересоздать после загрузки:

```sql
DROP INDEX CONCURRENTLY idx_articles_tags;
-- bulk insert ...
CREATE INDEX CONCURRENTLY idx_articles_tags ON articles USING gin (tags);
```

#### Мониторинг использования индексов

```sql
-- Использование GIN/GiST-индексов
SELECT s.schemaname, s.tablename, s.indexrelname, s.idx_tup_read, s.idx_tup_fetch
FROM pg_stat_user_indexes s
JOIN pg_class c ON s.indexrelid = c.oid
JOIN pg_am a ON c.relam = a.oid
WHERE a.amname IN ('gin', 'gist')
ORDER BY s.idx_tup_read DESC;
```

#### REINDEX и очистка

GiST и GIN-индексы подвержены bloat. Для онлайн-дефрагментации:

```sql
REINDEX INDEX CONCURRENTLY idx_bookings_during;
```

#### Бэкап и репликация

Массивы и range-типы — нативные типы PostgreSQL. `pg_dump`/`pg_basebackup` обрабатывают их без специальной конфигурации. Однако `EXCLUDE` constraints с GiST создают дополнительный WAL-объём при каждом INSERT/UPDATE — учитывайте это при планировании репликации.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| GIN-индекс не используется для `@>`/`&&` | Запрос использует выражение вместо колонки (например, `lower(tags) @> ...`) | Убрать функцию или создать expression index |
| `operator class "gin__int_ops" does not exist` | Расширение `intarray` не установлено или схема не в `search_path` | `CREATE EXTENSION intarray;` в нужной базе |
| Медленные запросы после bulk-загрузки | Накоплен pending list GIN-индекса | `SELECT gin_clean_pending_list('idx_name');` или `VACUUM` |
| Медленные INSERT/UPDATE с EXCLUDE + GiST | GiST-индекс блокирует запись синхронно | Установить `fillfactor` для GiST: `CREATE INDEX ... USING gist ... WITH (fillfactor = 70)` |
| `range construct error` | Границы range переданы в неправильном порядке (lower > upper) | Использовать конструктор: `int4range(1, 10)` вместо строкового литерала |
| `EXCLUDE` violation на INSERT | Пересечение интервалов обнаружено | Проверить существующие записи; использовать `DEFERRABLE INITIALLY DEFERRED` для транзакционной обработки |
| `cannot cast type ... to ...` при COPY | Массив/range передан в неверном формате | Использовать явное приведение: `'{"a","b"}'::text[]`, `'[1,5)'::int4range` |
| `unnest()` не сохраняет порядок | Обычный `unnest` не гарантирует порядок элементов | Использовать `unnest(...) WITH ORDINALITY` |

## Лучшие практики

1.  **Массивы вместо JSONB** для однородных списков скаляров: компактнее, быстрее GIN, есть `ANY`. JSONB — для иерархий и разнородных ключей.
2.  **GIN на массиве** обязателен, если есть `@>`/`&&`/`= ANY` в WHERE; без индекса — последовательное сканирование.
3.  **Range + EXCLUSION** — стандартный паттерн бронирования/расписания; исключает пересечения на уровне БД, без триггеров.
4.  **`unnest ... WITH ORDINALITY`** — когда порядок элементов важен (обычный `unnest` порядок не гарантирует).
5.  **Не злоупотребляйте массивами**: если часто нужны JOIN по элементам, UPDATE отдельных элементов или FK — нормализуйте. Массив — для «читай весь список целиком».
6.  **`intarray`** для `integer[]` — операторы `&&`, `@>`, `|` (объединение) и GIN-оптимизация `gin__int_ops`; стандартный GIN тоже работает, но `intarray` быстрее на целочисленных массивах.
7.  **Очистка**: удаляйте неиспользуемые GIN/GiST-индексы (`DROP INDEX [CONCURRENTLY] idx_name`) и расширения (`DROP EXTENSION intarray CASCADE`); для bulk-загрузок временно удаляйте GIN-индексы и пересоздаёнте после.
8.  **Multirange** вместо массива range-значений — когда нужно несколько дискретных интервалов в одной колонке; GiST-индексируется как range.

## Пограничные случаи

*   **Индексация с 1**: `tags[1]` — первый элемент; `tags[0]` — NULL (не ошибка).
*   **NULL в массиве**: `ARRAY[NULL, 1]` — NULL-элемент допустим; `= ANY` с NULL-элементом не даёт совпадений.
*   **Пустой массив vs NULL**: `'{}'::int[]` — пустой (не NULL); `NULL` — неизвестно. `= ANY(NULL)` — NULL.
*   **Range с `NULL`-границами**: `[NULL, 5)` недопустим; используйте `(,5)` для бесконечного lower.
*   **`&&` на непересекающихся, но смежных range** — false; смежность проверяется `-|-`.
*   **Многомерные массивы** — поддерживаются, но редко нужны; `array_agg` даёт одномерный.
*   **Multirange с пустыми range** — `{}`::int4multirange` и `multirange()` — пустой multirange (не NULL), содержит ноль range-значений.
*   **`+` для multirange** — не требует пересечения или смежности; разность `-` может вернуть multirange с пробелами, что недопустимо для обычного range (оператор `+` для range не работает с дискретными интервалами).

## Дополнительная информация

*   [Индексы](./indexes.md) — GIN/GiST, operator class.
*   [Ограничения](./constraints.md) — EXCLUSION с GiST для range.
*   [Расширения](./extensions_utility.md) — установка `intarray`, `btree_gist`.
*   [JSON и NoSQL возможности](./json_support.md) — когда JSONB вместо массива.
*   [Полнотекстовый поиск](./full_text_search.md) — GIN для tsvector.
*   [Официальная документация: массивы](https://www.postgresql.org/docs/current/arrays.html)
*   [Официальная документация: range-типы](https://www.postgresql.org/docs/current/rangetypes.html)
*   [Официальная документация: multirange-типы](https://www.postgresql.org/docs/current/rangetypes.html)
*   [Официальная документация: GIN](https://www.postgresql.org/docs/current/gin.html)
*   [Официальная документация: intarray](https://www.postgresql.org/docs/current/intarray.html)
