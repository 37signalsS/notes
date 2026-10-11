# Ограничения целостности (Constraints)

**Актуально для:** PostgreSQL 13–18

## Определения

*   **Constraint** — правило, которое PostgreSQL проверяет при изменении данных. Нарушение → ошибка `23xxx` (SQLSTATE) и откат транзакции.
*   **NOT NULL** — запрет `NULL` в колонке. Единственное ограничение, которое нельзя записать отдельной командой `ADD CONSTRAINT` — только атрибутом колонки.
*   **UNIQUE** — уникальность значения (или комбинации) в таблице. Создаёт уникальный B-tree-индекс. `NULL` не считается равным `NULL` — несколько `NULL` допустимы (в стандарте SQL — иначе; в PostgreSQL — как описано).
*   **PRIMARY KEY** = `UNIQUE` + `NOT NULL`. Одна на таблицу; создаёт уникальный индекс. Целевой объект для `FOREIGN KEY`.
*   **FOREIGN KEY** — ссылочная целостность: значение должно существовать в родительской таблице (или быть `NULL`). Требует индекс на ссылающейся колонке (не создаётся автоматически!) — иначе `DELETE`/`UPDATE` в родителе делает Seq Scan.
*   **CHECK** — произвольное предикатное условие (`CHECK (price > 0)`). Проверяется при `INSERT`/`UPDATE`; `NULL` в условии считается проходом (трёхзначная логика).
*   **EXCLUSION** — обобщение `UNIQUE`: гарантирует, что для любых двух строк хотя бы один из указанных операторов сравнения даёт `false`/`NULL`. Требует индекс GiST (по умолчанию) или SP-GiST; классический кейс — непересечение range-типов (`&&`).
*   **DEFERRABLE** — ограничение, проверка которого откладывается до `COMMIT` (вместо проверки после каждой инструкции). Варианты: `INITIALLY IMMEDIATE` (проверка после каждой инструкции, но можно отложить явно) и `INITIALLY DEFERRED` (проверка только на коммите).
*   **NOT VALID** — флаг добавления `CHECK`/`FK` без проверки существующих строк (мгновенно, без блокировки записи на всё время сканирования). Новые/обновляемые строки проверяются сразу.
*   **VALIDATE CONSTRAINT** — достраивает проверку существующих строк. Блокирует `UPDATE`/`DELETE` на таблице (`SHARE UPDATE EXCLUSIVE`), но не блокирует чтение и запись целиком.

## Базовые концепции

### Когда проверяются ограничения

По умолчанию — **немедленно** (`NOT DEFERRABLE`): после каждой инструкции `INSERT`/`UPDATE`/`DELETE`. Это ломает два сценария:

1.  **Циклические ссылки** (таблица ссылается сама на себя, или A→B→A): вставить первую строку невозможно, пока не существует родителя.
2.  **Перестановка значений** (`UPDATE ... SET col = CASE ...` меняет местами уникальные значения): промежуточное состояние нарушает `UNIQUE`.

`DEFERRABLE` решает оба: проверка переносится на `COMMIT`, и транзакция целиком либо валидна, либо откатывается.

### `NOT VALID` + `VALIDATE CONSTRAINT` — добавление на горячей таблице

Добавление `CHECK`/`FK` на большой таблице обычным `ADD CONSTRAINT` держит `ACCESS EXCLUSIVE` на время полного сканирования — минуты-часы простоя. Разделение на два шага:

1.  `ADD CONSTRAINT ... NOT VALID` — мгновенно (`ACCESS EXCLUSIVE` на миллисекунды), проверяет только новые строки.
2.  `VALIDATE CONSTRAINT` — сканирует существующие строки под `SHARE UPDATE EXCLUSIVE`: чтение и `INSERT` не блокируются, `UPDATE`/`DELETE` — ждут.

Промежуточное состояние (ограничение `NOT VALID`) видно в `pg_constraint.convalidated = false`.

### EXCLUSION — «UNIQUE для диапазонов»

`UNIQUE` не выражает «интервалы не пересекаются». `EXCLUSION` выражает:

```sql
ALTER TABLE bookings ADD CONSTRAINT no_overlap
EXCLUDE USING gist (room_id WITH =, during WITH &&);
```

Семантика: для любых двух строк не может одновременно выполняться `room_id = room_id` И `during && during` (пересечение range). Требует GiST-индекс; для `=` нужен btree_gist (расширение), чтобы смешивать равенство и range-операторы в одном GiST-индексе.

### Сложные CHECK

*   CHECK может ссылаться только на строку, которая записывается (нельзя обращаться к другим таблицам — для этого триггеры).
*   CHECK с подзапросом запрещён; для кросс-табличных правил — триггеры или FK.
*   `CHECK (col <> '')` пропускает `NULL`; для «и не NULL, и не пусто» — `NOT NULL` + `CHECK`.

## Практические сценарии

### Предварительные требования

1.  **База с правами `CREATE`** на схему (обычно владелец или `CREATE` на schema).
2.  Для EXCLUSION: `CREATE EXTENSION btree_gist;` (см. [Расширения](./extensions_utility.md)).

### 1. Полный набор ограничений на таблице

```sql
CREATE TABLE orders (
    id            bigserial PRIMARY KEY,
    order_no      text NOT NULL UNIQUE,
    customer_id   bigint NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    price         numeric(10,2) NOT NULL CHECK (price >= 0),
    status        text NOT NULL CHECK (status IN ('new','paid','shipped','cancelled')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT orders_status_transition CHECK (
        status <> 'cancelled' OR price = 0
    )
);
-- → CREATE TABLE

-- Проверка: какие ограничения есть
SELECT conname, contype, convalidated
FROM pg_constraint WHERE conrelid = 'orders'::regclass;
-- → conname                 | contype | convalidated
-- → orders_pkey             | p       | t
-- → orders_order_no_key     | u       | t
-- → orders_customer_id_fkey | f       | t
-- → orders_price_check      | c       | t
-- → orders_status_check     | c       | t
-- → orders_status_transition| c       | t
```

### 2. DEFERRABLE для циклической ссылки (самоссылающаяся таблица)

```sql
CREATE TABLE employees (
    id        bigserial PRIMARY KEY,
    name      text NOT NULL,
    manager_id bigint REFERENCES employees(id) DEFERRABLE INITIALLY DEFERRED
);
-- → CREATE TABLE

BEGIN;
INSERT INTO employees (name, manager_id) VALUES ('CEO', NULL);
INSERT INTO employees (name, manager_id) VALUES ('CTO', 1);
COMMIT;
-- → COMMIT (проверка FK — только на коммите)

-- Без DEFERRABLE: вставка CTO до CEO → ERROR: insert or update on table
-- "employees" violates foreign key constraint
```

Переключение в рамках сессии: `SET CONSTRAINTS ALL DEFERRED;` (только для `DEFERRABLE`-ограничений; `SET CONSTRAINTS ALL IMMEDIATE` — обратно).

### 3. EXCLUSION — запрет пересечения бронирований

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
-- → CREATE EXTENSION

CREATE TABLE bookings (
    room_id  int NOT NULL,
    during   tstzrange NOT NULL,
    EXCLUDE USING gist (room_id WITH =, during WITH &&)
);
-- → CREATE TABLE

INSERT INTO bookings VALUES (101, '[2026-10-04 10:00, 2026-10-04 12:00)');
-- → INSERT 0 1

INSERT INTO bookings VALUES (101, '[2026-10-04 11:00, 2026-10-04 13:00)');
-- → ERROR: conflicting key value violates exclusion constraint "bookings_room_id_during_excl"
-- → DETAIL: Key (room_id, during)=(101, ["2026-10-04 11:00:00+00","2026-10-04 13:00:00+00")) conflicts with existing key...

-- Другая комната — ок
INSERT INTO bookings VALUES (102, '[2026-10-04 11:00, 2026-10-04 13:00)');
-- → INSERT 0 1
```

### 4. Добавление CHECK на горячей таблице без простоя

```sql
-- Шаг 1: мгновенно, без сканирования существующих строк
ALTER TABLE events
    ADD CONSTRAINT events_positive_amount CHECK (amount >= 0) NOT VALID;
-- → ALTER TABLE (мгновенно)

-- Проверка: ограничение пока не валидировано
SELECT conname, convalidated FROM pg_constraint
WHERE conrelid = 'events'::regclass AND conname = 'events_positive_amount';
-- → conname                | convalidated
-- → events_positive_amount | f

-- Шаг 2: проверка существующих строк (SHARE UPDATE EXCLUSIVE)
ALTER TABLE events VALIDATE CONSTRAINT events_positive_amount;
-- → ALTER TABLE (сканирование таблицы; INSERT/SELECT не блокируются)

-- Если в данных есть нарушения — шаг 2 упадёт; найти их заранее:
SELECT count(*) FROM events WHERE amount < 0;
-- → 0
```

### 5. Индекс для FK (часто забывают)

```sql
-- Без индекса на child-колонке DELETE в parent делает Seq Scan:
DELETE FROM customers WHERE id = 42;
-- → медленно на больших таблицах; план: Seq Scan на orders

-- Решение:
CREATE INDEX CONCURRENTLY idx_orders_customer_id ON orders (customer_id);
-- → CREATE INDEX (CONCURRENTLY — без блокировки записи)
```

### 6. Операционная поддержка: мониторинг и обслуживание

#### Мониторинг FK без индекса

Отсутствие индекса на FK-колонке вынуждает PostgreSQL выполнять Seq Scan по дочерней таблице при удалении или обновлении родительской строки. На больших таблицах это критично для производительности SRE.

```sql
-- Foreign keys without an index on the referencing column
SELECT
    c.conrelid::regclass AS child_table,
    c.conname AS fk_name,
    a.attname AS column_name
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
WHERE c.contype = 'f'
  AND NOT EXISTS (
      SELECT 1 FROM pg_index i
      WHERE i.indrelid = c.conrelid
        AND i.indisunique = false
        AND i.indisvalid = true
        AND i.indkey[0] = a.attnum
        AND array_length(i.indkey, 1) = 1
  );
-- → child_table | fk_name | column_name
--   (пустой результат — все FK проиндексированы)
```

#### Мониторинг NOT VALID и INVALID ограничений

```sql
-- Constraints added with NOT VALID that have not yet been validated
SELECT conrelid::regclass AS table_name, conname, contype
FROM pg_constraint
WHERE convalidated = false;
-- → table_name | conname | contype
```

#### Поиск нарушений существующих CHECK перед VALIDATE

Перед запуском `VALIDATE CONSTRAINT` найдите строки-нарушители, чтобы избежать простоя от failed-валидации:

```sql
-- For CHECK (amount >= 0):
SELECT count(*) FROM events WHERE NOT (amount >= 0);
-- → 0  (можно запускать VALIDATE CONSTRAINT)
```

#### pg_dump и constraints

- `PRIMARY KEY`, `UNIQUE`, `CHECK` экспортируются inline в `CREATE TABLE`.
- `FOREIGN KEY` экспортируются как отдельные `ALTER TABLE ... ADD CONSTRAINT` после `CREATE TABLE`, чтобы обеспечить корректный порядок создания таблиц.
- `EXCLUDE` экспортируется в `CREATE TABLE`/`ALTER TABLE` с указанием `USING gist`.
- `NOT VALID` constraints сохраняют статус при дампе/ресторе — в `CREATE TABLE`/`ALTER TABLE` появляется `NOT VALID`.

#### REINDEX и очистка GiST-индексов EXCLUSION

GiST-индексы (включая EXCLUDE) подвержены bloat и требуют периодического `REINDEX`:

```sql
REINDEX INDEX CONCURRENTLY bookings_room_id_during_excl;
```

#### Bulk-load оптимизации

Для bulk-загрузок отключайте FK-ограничения, затем добавляйте их с `NOT VALID` + `VALIDATE CONSTRAINT`:

```sql
-- 1. Временно удалить FK (или добавить с NOT VALID)
ALTER TABLE orders DROP CONSTRAINT orders_customer_id_fkey;

-- bulk insert ...

-- 2. Добавить обратно без проверки существующих строк
ALTER TABLE orders ADD CONSTRAINT orders_customer_id_fkey
  FOREIGN KEY (customer_id) REFERENCES customers(id) NOT VALID;

-- 3. Валидировать
ALTER TABLE orders VALIDATE CONSTRAINT orders_customer_id_fkey;
```

## Лучшие практики

1.  **FK + индекс на child-колонке** — всегда; иначе `DELETE`/`UPDATE` в родителе сканирует всю дочернюю таблицу.
2.  **`NOT VALID` → `VALIDATE CONSTRAINT`** для любых `CHECK`/`FK` на таблицах больше нескольких миллионов строк — стандартный приём zero-downtime миграций.
3.  **`DEFERRABLE INITIALLY DEFERRED`** только там, где нужно (циклические ссылки, перестановки): отложенная проверка скрывает ошибки до коммита.
4.  **EXCLUSION вместо триггеров** для «не пересекается» — атомарно, без race condition (триггеры на `SELECT`-проверке дают ложные «ок» при конкурентных вставках).
5.  **`ON DELETE` явно**: `RESTRICT` (дефолт) / `CASCADE` / `SET NULL` / `NO ACTION` (в PostgreSQL эквивалентно `RESTRICT`, но проверяется в конце инструкции, а не сразу).
6.  **CHECK вместо триггеров** для правил внутри строки — дешевле и декларативно.
7.  **Именование ограничений** (`CONSTRAINT name`) — иначе имена генерируются (`events_amount_check`) и их сложно искать в ошибках и `pg_dump`.
8.  **Очистка**: удаляйте неиспользуемые `EXCLUDE`/`UNIQUE` ограничения и их GiST-индексы (`DROP CONSTRAINT`/`DROP INDEX CONCURRENTLY`); для bulk-загрузок удаляйте FK-ограничения, загружайте данные, добавляйте FK обратно с `NOT VALID` + `VALIDATE CONSTRAINT`; `REINDEX CONCURRENTLY` GiST-индексы EXCLUDE раз в квартал для очистки bloat.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `DELETE FROM parent` медленный | FK на child-колонке без индекса → Seq Scan по всей дочерней таблице | `CREATE INDEX CONCURRENTLY` на FK-колонке |
| `VALIDATE CONSTRAINT` падает | Существующие строки нарушают constraint | Найти нарушения (`SELECT ... WHERE NOT (условие)`), исправить, повторить |
| `CHECK (col > 0)` пропускает строки с NULL | CHECK использует трёхзначную логику: `NULL` → проходит | Добавить `NOT NULL` к колонке |
| Циклическая FK — первая строка не вставляется | FK не `DEFERRABLE` → проверка сразу после INSERT | `DEFERRABLE INITIALLY DEFERRED` или `SET CONSTRAINTS ALL DEFERRED` |
| `operator class "gist__int_ops" does not exist` | Расширение `btree_gist` не установлено | `CREATE EXTENSION btree_gist;` |
| `conflicting key value violates exclusion constraint` | Пересечение range-значений в EXCLUDE | Проверить существующие записи; использовать `DEFERRABLE` + транзакцию |
| Concurrently созданный UNIQUE-индекс не используется | Индекс `INVALID` после прерванного `CREATE INDEX CONCURRENTLY` | `DROP INDEX CONCURRENTLY idx_name; CREATE INDEX CONCURRENTLY idx_name ON t(col);` |
| `pg_dump` создаёт таблицу с FK до родителя | Порядок создания не гарантирует зависимостей | pg_dump автоматически упорядочивает `ALTER TABLE ADD CONSTRAINT` |

## Пограничные случаи

*   **UNIQUE и NULL**: несколько `NULL` допустимы (PostgreSQL); для «строгой уникальности с NULL» — частичный уникальный индекс (`CREATE UNIQUE INDEX ... WHERE col IS NOT NULL`) или `COALESCE` в выражении.
*   **CHECK и NULL**: `CHECK (col > 0)` пропускает `NULL` — комбинируйте с `NOT NULL`.
*   **FK и NULL**: `NULL` в child-колонке проходит проверку (ссылка «необязательна»).
*   **DEFERRABLE + UNIQUE**: отложенная проверка уникальности тоже работает — перестановка уникальных значений в одном `UPDATE` возможна.
*   **EXCLUSION без btree_gist**: `EXCLUDE USING gist (col WITH =)` на обычном типе требует расширения `btree_gist` (класс операторов для `=` в GiST).
*   **`NOT VALID` FK и репликация**: логическая репликация не проверяет FK на subscriber (если `session_replication_role = replica`) — `NOT VALID` FK на subscriber безопасен, но `VALIDATE` на большой реплике — тяжёлая операция.
*   **Ограничения и партиционирование**: `PRIMARY KEY`/`UNIQUE` на партиционированной таблице должен включать ключ партиционирования.
*   **Concurrently созданный UNIQUE-индекс**: если `CREATE INDEX CONCURRENTLY` прерван, индекс остаётся `INVALID`. Удалить и пересоздать: `DROP INDEX CONCURRENTLY idx_name; CREATE INDEX CONCURRENTLY idx_name ON table(col);`.

## Дополнительная информация

*   [Управление параллелизмом и блокировки](./concurrency_and_locking.md) — уровни блокировок `ADD CONSTRAINT` vs `VALIDATE CONSTRAINT`.
*   [Массивы и range-типы](./arrays_and_ranges.md) — range-типы для EXCLUSION.
*   [Индексы](./indexes.md) — B-tree для `UNIQUE`/`PRIMARY KEY`, GiST для `EXCLUDE`.
*   [Схемные миграции](./schema_migrations.md) — zero-downtime паттерны с `NOT VALID`.
*   [Справочник кодов ошибок](./error_codes.md) — SQLSTATE `23xxx` (integrity constraint violation).
*   [Официальная документация: Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)
*   [Официальная документация: EXCLUDE](https://www.postgresql.org/docs/current/sql-createtable.html#SQL-CREATETABLE-EXCLUDE)
*   [Официальная документация: pg_constraint](https://www.postgresql.org/docs/current/catalog-pg-constraint.html)
*   [Официальная документация: pg_index](https://www.postgresql.org/docs/current/catalog-pg-index.html)
