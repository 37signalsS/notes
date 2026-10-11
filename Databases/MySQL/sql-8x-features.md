# Возможности SQL MySQL 8.x: оконные функции, CTE, JSON и генерируемые колонки

**Актуально для:** MySQL 8.4 LTS / 9.7 LTS / 26.x Innovation

> **Статус:** MySQL 8.0 достигла End of Life в апреле 2026 года (8.0.46). Все
> описанные ниже конструкции работают в 8.4 и позже без изменений; для новых
> развёртываний рекомендуется 8.4 LTS или 9.7 LTS.

Набор конструкций, доступных в MySQL 8.0 и отсутствовавших в 5.7: оконные функции, общие
табличные выражения, полноценный тип `JSON` с набором функций и поиска по пути,
генерируемые колонки. Для эксплуатации они важны по трём причинам: оконные функции
снимают целый класс «медленных запросов с самосоединением», `JSON` меняет схему хранения
полуструктурированных данных, а генерируемые колонки — способ проиндексировать вычисляемое
значение.

Партнёры по теме: [Индексы в MySQL](./indexing.md) — индексы на выражениях и
  генерируемых колонках; [EXPLAIN и оптимизация](./Operations/explain_and_optimization.md) —
  план исполнения оконных запросов.

## Требования и предпосылки

Все описанные конструкции доступны в MySQL 8.0 и позже. Критически важные
проверки перед внедрением:

| Проверка | Команда / способ | Ожидаемый результат |
| :--- | :--- | :--- |
| Версия сервера | `SELECT VERSION();` | `8.4.x` или выше; ниже 8.0 — конструкции недоступны |
| Поддержка оконных функций | `SHOW VARIABLES LIKE 'have_window';` | `YES` |
| Поддержка CTE | `WITH cte AS (SELECT 1) SELECT * FROM cte;` | корректный результат, без ошибки `1146` |
| Поддержка `JSON_TABLE` | `SELECT JSON_TABLE('[1,2]', '$[*]' COLUMNS (v INT PATH '$'));` | таблица со столбцом `v` |
| Поддержка `LATERAL` | `SELECT * FROM (SELECT 1) AS t, LATERAL (SELECT 1) AS l;` | без ошибки синтаксиса |
| Поддержка `MATERIALIZED` | `WITH cte AS MATERIALIZED (SELECT 1) SELECT * FROM cte;` | без ошибки синтаксиса (требуется 8.0.24+) |
| Поддержка `INVISIBLE` колонок | `CREATE TABLE t (a INT, b INT INVISIBLE); INSERT INTO t (a) VALUES (1); SELECT * FROM t;` | в结果е только `a`, `b` скрыта |
| Поддержка `MEMBER OF` | `SELECT 1 MEMBER OF ('[1,2,3]');` | `1` (требуется 8.0.17+) |
| Поддержка `JSON_SCHEMA_VALID` | `SELECT JSON_SCHEMA_VALID('{}', '{}');` | `1` (требуется 8.0.17+) |

**Совместимость с приложением:** `SELECT *` изменяет своё поведение при наличии
невидимых колонок — проверьте, что клиенты не позиционируются по индексу колонок.
Ключевые слова (`OVER`, `WINDOW`, `RANK`, `ROW_NUMBER`, `DENSE_RANK`, `RECURSIVE`,
`LATERAL`, `CUME_DIST`, `NTILE`, `FIRST_VALUE`, `INTERSECT`, `ARRAY`, `MEMBER`,
`SYSTEM`, `EMPTY`, `GROUPING`, `GROUPS`) стали зарезервированными в 8.0 — при
необходимости quote'ите их обратными кавычками.

**Версионное согласование:** при обновлении с 5.7 проверьте отсутствие
зарезервированных слов в именах объектов и изменение поведения `sql_mode`
(по умолчанию `ONLY_FULL_GROUP_BY` включён). Подробно — в
[maintenance-and-upgrades.md](./maintenance-and-upgrades.md).

## Определения

| Термин | Значение |
| :--- | :--- |
| Window function | Функция, вычисляемая по «окну» строк, определённому клаузой `OVER` |
| Partition | Разбиение окна на группы — строки с одинаковым значением выражения `PARTITION BY` |
| Frame | Подмножество окна: какие строки учитываются в вычислении (`ROWS`/`RANGE`) |
| CTE | Common Table Expression — именованный подзапрос в клаузе `WITH` |
| Recursive CTE | CTE, обращающийся к самому себе через `UNION ALL` |
| JSON path | Выражение пути к элементу JSON: `$.store.book[0].title` |
| Generated column | Колонка, значение которой вычисляется: `VIRTUAL` (не хранится) или `STORED` (хранится) |

## Базовые концепции

### Оконные функции: зачем они нужны эксплуатации

Классическая задача до MySQL 8.0 — «для каждого клиента найти три последних заказа» —
решалась самосоединением или коррелированным подзапросом. Оба варианта плохо
масштабируются: стоимость растёт с объёмом таблицы, и план исполнения показывает
`DEPENDENT SUBQUERY` или повторное чтение временной таблицы.

Оконная функция выражает это одним проходом:

```sql
SELECT o.* FROM (
  SELECT customer_id, created_at, amount,
         ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn
  FROM shop.orders
) AS o WHERE o.rn <= 3;
```

Практический вывод: **запрос с `ROW_NUMBER()` вместо самосоединения обычно на порядок
дешевле на больших объёмах**. Это первое, что стоит проверять при разборе тяжёлого
аналитического запроса.

### Состав оконных функций

| Функция | Что возвращает | Типичное применение |
| :--- | :--- | :--- |
| `ROW_NUMBER()` | Номер строки в окне, всегда уникальный | Топ-N на группу |
| `RANK()` | Ранг с пропусками: после равных значений идёт пропуск | Рейтинг с конкуренцией |
| `DENSE_RANK()` | Ранг без пропусков | Плотный рейтинг |
| `FIRST_VALUE()` | Первое значение окна | «Последняя покупка клиента» |
| `LAST_VALUE()` | Последнее значение окна | Требует явного фрейма |
| `NTH_VALUE()` | Значение на позиции `n` | Точечная выборка |
| `LEAD(expr)` | Значение из следующей строки | Интервалы между событиями |
| `LAG(expr)` | Значение из предыдущей строки | Дельта между периодами |
| `PERCENT_RANK()` | Относительный ранг `(rank-1)/(rows-1)` | Перцентили |
| `CUME_DIST()` | Доля строк с рангом не выше текущего | Кумулятивное распределение |
| `NTILE(n)` | Номер корзины из `n` равных по размеру групп | Когорты, сегменты |

Оконные функции не агрегируют строки в одну — они добавляют вычисленное значение к каждой
строке. Для сводок по-прежнему нужны `GROUP BY` или `SUM() OVER (...)`.

### Клауза OVER и фрейм

```sql
OVER (
    [PARTITION BY expr, ...]           -- разбиение на группы
    [ORDER BY expr [ASC|DESC], ...]     -- порядок внутри окна
    [frame_clause]                      -- границы фрейма
)
```

| Граница фрейма | Значение |
| :--- | :--- |
| `UNBOUNDED PRECEDING` | От начала партиции |
| `n PRECEDING` | За `n` строк до текущей |
| `CURRENT ROW` | Текущая строка |
| `n FOLLOWING` | Через `n` строк после текущей |
| `UNBOUNDED FOLLOWING` | До конца партиции |

| Модификатор фрейма | Что задаёт |
| :--- | :--- |
| `ROWS` | Границы по номерам строк (с учётом порядка) |
| `RANGE` | Границы по значениям выражения `ORDER BY` (значения учитываются как диапазон) |

`GROUPS` и `EXCLUDE` MySQL не поддерживает: парсер распознаёт их, но выдаёт ошибку — поддерживаются только `ROWS` и `RANGE` (раздел «Window Function Restrictions» руководства MySQL 8.0+).

Разница между `ROWS` и `RANGE` критична для `LAST_VALUE` и `LAG`:

```sql
-- Ошибка: без явного фрейма LAST_VALUE вернёт значение текущей строки
SELECT customer_id, created_at,
       LAST_VALUE(amount) OVER (PARTITION BY customer_id ORDER BY created_at) AS lv
FROM shop.orders;

-- Правильно: RANGE ... UNBOUNDED FOLLOWING — последнее значение всей партиции
SELECT customer_id, created_at,
       LAST_VALUE(amount) OVER (
           PARTITION BY customer_id ORDER BY created_at
           RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
       ) AS lv
FROM shop.orders;
```

> **Осторожно:** `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` с вычислением
> суммы **растёт** от первой строки к текущей. Для скользящего окна «N последних строк»
> нужен `ROWS BETWEEN n PRECEDING AND CURRENT ROW`. Это классическая ошибка,
> дающая неверные итоги без каких-либо предупреждений.

### Общие табличные выражения

```sql
WITH cte_name AS (SELECT ...)
SELECT ... FROM cte_name;
```

CTE — это не отдельная сущность: движок может выполнить запрос и подзапрос
одним проходом (слияние, `merge`), а может материализовать подзапрос во временную
таблицу. Это объясняет, почему CTE не всегда ускоряет запрос, хотя часто упрощает его.

Свойства, важные для эксплуатации:

| Свойство | Значение |
| :--- | :--- |
| Глубина рекурсии | Ограничивается `@@cte_max_recursion_depth` (по умолчанию 1000); при превышении — ошибка |
| Область видимости | Один оператор |
| Несколько CTE | Перечисляются через запятую, последующие могут ссылаться на предыдущие |
| Ссылка на несколько предыдущих | `WITH cte1 AS (...), cte2 AS (SELECT FROM cte1)` |

```sql
-- Сброс счётчика глубины рекурсии на время сложного расчёта
SET SESSION cte_max_recursion_depth = 10000;
-- → Query OK, 0 rows affected

WITH RECURSIVE seq AS (
  SELECT 1 AS n
  UNION ALL
  SELECT n + 1 FROM seq WHERE n < 1000
)
SELECT SUM(n) FROM seq;
-- → SUM(n) = 500500
```

Рекурсивные CTE удобны для обхода иерархий в одном запросе — вместо нескольких
временных таблиц.

**Управление материализацией (MySQL 8.0.24+).** По умолчанию движок сам
решает, материализовать CTE во временную таблицу или встроить её в запрос
(`merge`). Хинт явно задаёт стратегию:

```sql
WITH cte AS MATERIALIZED (SELECT ...)   -- всегда материализовать
SELECT ...;
WITH cte AS NOT MATERIALIZED (SELECT ...)   -- всегда встраивать
SELECT ...;
```

`MATERIALIZED` полезен, когда CTE ссылается несколько раз (вычислить
один раз, использовать много раз) или когда встраивание ухудшает план.
`NOT MATERIALIZED` — когда CTE маленький и встраивание даёт лучший план.
По умолчанию CTE материализуется, если на неё ссылаются более одного раза;
при одной ссылке оптимизатор предпочитает `merge`.

### LATERAL-производные таблицы (MySQL 8.0.14+)

`LATERAL` позволяет производной таблице (derived table) в `FROM` ссылаться
на колонки из предыдущих таблиц того же `FROM` — то есть коррелированный
подзапрос в `FROM`. Без `LATERAL` производная таблица не может ссылаться
на другие таблицы.

```sql
-- Коррелированная производная таблица: топ-3 заказов на клиента
SELECT c.name, o.*
FROM customers AS c,
     LATERAL (
       SELECT * FROM orders
       WHERE customer_id = c.id
       ORDER BY created_at DESC
       LIMIT 3
     ) AS o;
```

Эквивалент — оконная функция `ROW_NUMBER()`, но `LATERAL` с `LIMIT` часто
эффективнее для «топ-N на группу», когда групп много, а N мало: MySQL
может использовать индекс по `(customer_id, created_at)` и останавливать
сканирование после N строк на группу (early termination).

`LATERAL` также работает с табличными функциями, например `JSON_TABLE`:

```sql
SELECT u.id, j.*
FROM users AS u,
     LATERAL JSON_TABLE(
       u.settings, '$.tags[*]' COLUMNS (tag VARCHAR(50) PATH '$')
     ) AS j;
```

### Тип JSON

Столбец `JSON` хранит документ в **бинарном** формате: сервер может найти вложенный
элемент напрямую по ключу или индексу массива, не читая весь документ. При вставке
документ дополнительно нормализуется:

- Дубликаты ключей отбрасываются — остаётся последний слева направо.
- Лишние пробелы между ключами, значениями и элементами удаляются.

```sql
CREATE TABLE shop.events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  payload JSON NOT NULL
) ENGINE=InnoDB;

INSERT INTO shop.events (payload) VALUES
  ('{"x": 17, "x": "red"}'),
  ('{"x": 17, "x": "red", "x": [3, 5, 7]}');

SELECT payload FROM shop.events;
-- → payload
-- → {"x": 17}
-- → {"x": 17}
```

Практические следствия нормализации:

- **Порядок ключей не сохраняется.** Приложение не может полагаться на него.
- **Форматирование при выводе нормализуется** — пробелы после запятых и двоеточий
  стандартизированы. Не делайте вывод JSON эталонным для сравнения.
- **`payload = '...' ` не сравнивает текст**, а сравнивает нормализованные значения.

Операторы и функции:

| Оператор / функция | Назначение |
| :--- | :--- |
| `col->path` | Извлечь значение по пути (эквивалент `JSON_EXTRACT`) |
| `col->>path` | Извлечь и снять кавычки (эквивалент `JSON_UNQUOTE(JSON_EXTRACT(...))`) |
| `JSON_SET()` | Установить значение по пути |
| `JSON_INSERT()` | Вставить, если отсутствует |
| `JSON_REPLACE()` | Заменить существующее |
| `JSON_REMOVE()` | Удалить по пути |
| `JSON_CONTAINS()` | Проверить наличие всех пар/элементов |
| `JSON_OVERLAPS()` | Проверить наличие хотя бы одной общей пары/элемента (с MySQL 8.0.17) |
| `value MEMBER OF(json_array)` | Проверить вхождение скаляра в массив (с MySQL 8.0.17) |
| `JSON_VALID()` | Проверить корректность документа |
| `JSON_TYPE()`, `JSON_DEPTH()`, `JSON_KEYS()`, `JSON_LENGTH()` | Атрибуты документа |
| `JSON_STORAGE_SIZE()` | Размер бинарного представления |
| `JSON_PRETTY()` | Человекочитаемый вывод |
| `JSON_SCHEMA_VALID()` | Валидация по JSON Schema Draft 4 (с MySQL 8.0.17) |
| `JSON_SCHEMA_VALIDATION_REPORT()` | Детальный отчёт валидации (с MySQL 8.0.17) |
| `JSON_ARRAYAGG()`, `JSON_OBJECTAGG()` | Агрегатные функции, собирающие JSON |
| `JSON_TABLE()` | Развернуть JSON в реляционную таблицу |

### Генерируемые колонки

| Вид | Хранение | Можно индексировать | Стоимость записи |
| :--- | :--- | :--- | :--- |
| `VIRTUAL` | Не хранится, вычисляется при чтении | Да (в MySQL) | Только при записи |
| `STORED` | Хранится в строках | Да | Запись и хранение |

```sql
CREATE TABLE shop.orders (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  amount DECIMAL(12,2) NOT NULL,
  quantity INT NOT NULL,
  total DECIMAL(12,2) GENERATED ALWAYS AS (amount * quantity) STORED,
  idx_total (total)
) ENGINE=InnoDB;
```

Практический вывод: **`VIRTUAL` предпочтительнее `STORED`**, если нет причин хранить.
Индекс по виртуальной колонке означает, что значение всё равно материализуется в индексе
при каждой записи — платить придётся в любом случае.

Ограничения определения выражения:

- Не допускаются подзапросы.
- Не допускаются недетерминированные функции (например, `NOW()`, `RAND()`,
  `UUID()`), поскольку результат должен воспроизводиться при перечитывании строки.
- Ссылка на `AUTO_INCREMENT`-колонку той же таблицы запрещена.

`STORED`-колонку можно добавить на большую таблицу через
[Online Schema Change](./Operations/online-schema-change.md) — операция перестраивает
таблицу.

### Невидимые колонки (MySQL 8.0.23+)

Колонка с атрибутом `INVISIBLE` не отображается в `SELECT *` и в результатах,
но существует и хранит данные. Доступ к ней — только по явному имени.

```sql
CREATE TABLE t (
  id INT PRIMARY KEY,
  secret VARCHAR(100) INVISIBLE
);

SELECT * FROM t;              -- вернёт только id
SELECT id, secret FROM t;     -- явный доступ работает

-- Сделать видимой / невидимой
ALTER TABLE t ALTER COLUMN secret SET VISIBLE;
ALTER TABLE t ALTER COLUMN secret SET INVISIBLE;
```

Применение:

- **Плавное удаление колонки.** Сначала `SET INVISIBLE` — убедиться, что
  никто не обращается по имени, затем `DROP COLUMN`.
- **Скрытие служебных/чувствительных колонок** от `SELECT *` в приложениях,
  которые не перечисляют колонки явно.

Ограничения: невидимой может быть любая колонка, кроме тех, что входят в
`PRIMARY KEY` (первичный ключ всегда видим). Невидимые колонки всё равно
участвуют в индексах и ограничениях.

### UPSERT: INSERT ... ON DUPLICATE KEY UPDATE

«Обновить или вставить» — запись, если ключа нет, иначе обновление.

```sql
INSERT INTO inventory (sku, qty) VALUES ('A-1', 10)
ON DUPLICATE KEY UPDATE qty = qty + VALUES(qty);
```

`VALUES(col)` внутри `ON DUPLICATE KEY UPDATE` возвращает значение,
которое было бы вставлено. **С MySQL 8.0.20 `VALUES()` в этом контексте
устарела** — предпочтительнее алиас вставляемой строки:

```sql
INSERT INTO inventory (sku, qty) VALUES ('A-1', 10) AS new
ON DUPLICATE KEY UPDATE qty = inventory.qty + new.qty;
```

Альтернативы и отличия:

- `REPLACE INTO` — удаляет старую строку и вставляет новую (два запроса,
  инкремент `AUTO_INCREMENT`, срабатывают `DELETE`-триггеры). `ON DUPLICATE
  KEY UPDATE` — одно обновление, `AUTO_INCREMENT` не расходуется зря.
- `INSERT IGNORE` — игнорирует ошибки дубликата (строка не вставляется,
  но и не обновляется).

**SRE-заметка:** `ON DUPLICATE KEY UPDATE` — атомарна и безопасна при
конкурентных вставках (блокировка на уникальном ключе). Для массовых
загрузок — см. [Загрузка данных](./data-loading.md).

## Практические сценарии

### Сценарий 1. Топ-N на группу

```sql
SELECT * FROM (
  SELECT o.*,
         ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn
  FROM shop.orders AS o
) AS ranked
WHERE rn <= 3
ORDER BY customer_id, created_at DESC;
```

Сравнение с подходом через `GROUP_CONCAT` или переменные сессии: план исполнения
принципиально другой и не содержит `DEPENDENT SUBQUERY`.

Проверка плана:

```sql
EXPLAIN FORMAT=TREE
SELECT * FROM (
  SELECT o.*, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn
  FROM shop.orders AS o
) AS ranked WHERE rn <= 3;
-- → -> Aggregate: row_number  (cost=1.02..1.02 rows=1) (actual time=... rows=...)
-- →     -> Sort: t1.created_at desc, t1.customer_id  (rows=24839102) (actual ...)
-- →         -> Table scan on t1  (rows=24839102) (actual ...)
```

### Сценарий 2. Дельта между периодами и скользящее окно

```sql
SELECT
  created_at,
  amount,
  amount - LAG(amount) OVER (ORDER BY created_at)            AS delta_vs_prev,
  SUM(amount) OVER (ORDER BY created_at
                    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS rolling_7
FROM shop.revenue_daily;
```

Здесь важно именно `ROWS BETWEEN 6 PRECEDING AND CURRENT ROW`. С `RANGE` и тем же
`ORDER BY` по дате результат был бы другим.

```sql
-- Кумулятивный итог с начала периода
SELECT created_at, SUM(amount) OVER (ORDER BY created_at
                                     RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ytd
FROM shop.revenue_daily;
```

### Сценарий 3. Разделение на когорты

```sql
SELECT customer_id, first_order_date,
       NTILE(10) OVER (ORDER BY first_order_date) AS decile
FROM (
  SELECT customer_id, DATE(created_at) AS first_order_date
  FROM shop.orders
  GROUP BY customer_id, DATE(created_at)
) AS first_orders;
-- → decile 1 — самые ранние 10% клиентов, decile 10 — самые поздние
```

### Сценарий 4. Развёртка JSON в строки (JSON_TABLE)

```sql
SELECT t.order_id, item.product, item.price
FROM shop.orders_json AS o,
     JSON_TABLE(
       o.payload, '$.items[*]'
       COLUMNS (
product VARCHAR(128) PATH '$.product',
          price   DECIMAL(12,2) PATH '$.price',
          qty     INT PATH '$.quantity'
       )
     ) AS item
WHERE o.id = 42;
-- → order_id | product   | price  | qty
-- → 42       | Keyboard  | 89.90  | 1
```

`JSON_TABLE` — единственная функция MySQL 8.0, превращающая JSON в реляционную таблицу.
Именно она снимает аргумент «JSON нельзя фильтровать индексами»: данные можно вынести
в обычные колонки с обычными индексами.

Особенности:

- Поддерживаются четыре типа колонок: `name type PATH string_path`, `name type EXISTS PATH`
  (возвращает 0 или 1 — факт наличия пути, а не значение), `NESTED [PATH] path COLUMNS (...)`
  и агрегатные `FOR ORDINALITY`.
- Каждая колонка допускает `on_empty` и `on_error`.
- Сравнение имён колонок стало регистронезависимым с MySQL 8.0.27.
- Поддерживает вложенность: `NESTED PATH '$.items[*]' COLUMNS (...)` разворачивает
  массив объектов с подпунктами.

### Сценарий 5. Индексирование значения внутри JSON

Прямой индекс по выражению в колонке `JSON`:

```sql
CREATE TABLE shop.t1 (
  j JSON,
  INDEX idx_id ((JSON_VALUE(j, '$.id' RETURNING UNSIGNED)))
);
```

С MySQL 8.0.17 InnoDB поддерживает **multi-valued indexes** для массивов JSON. Оптимизатор
применяет их автоматически для запросов с `JSON_CONTAINS()`, `JSON_OVERLAPS()` и `MEMBER OF()`:

```sql
CREATE TABLE shop.customers (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  custinfo JSON,
  INDEX zips ((CAST(custinfo->'$.zipcode' AS UNSIGNED ARRAY)))
);

INSERT INTO shop.customers (custinfo) VALUES
  ('{"zipcode": [10001, 10002, 10003]}'),
  ('{"zipcode": [20001, 20002]}');
-- → 2 row(s) affected

SELECT id FROM shop.customers
WHERE JSON_CONTAINS(custinfo, '10002', '$.zipcode');
-- → EXPLAIN использует индекс zips (Key Used: zips)
-- → 1
```

Обязательные условия конструкции:

- Колонка под индексом должна иметь тип `JSON`.
- Выражение обязательно в **двойных скобках** `(( CAST(... AS ... ARRAY) ))`.
- Тип после `AS` — любой из поддерживаемых `CAST()`, кроме `BINARY`, `JSON` и `YEAR`.
  `CONVERT()` и ключевое слово `ARRAY` не поддерживают.
- Один multi-valued ключевой столбец на индекс; сам `CAST(...)` может обращаться к
  нескольким массивам документа, но они схлопываются в один плоский массив.
- Простые (не массивы) значения `CHAR`/`INT` в документе в multi-valued индекс не
  попадают.

> **Ограничение:** multi-valued индекс создаётся как функциональный индекс поверх
> скрытой виртуальной колонки. Требуемый `ALGORITHM` заранее не объявляется, поэтому на
> большой таблице сначала проверьте операцию пробным `ALTER` с явным `ALGORITHM` на копии —
> [Online Schema Change](./Operations/online-schema-change.md).

Практический совет: если JSON используется как основное хранилище данных, а не как
справочное поле, **выносите значения в обычные колонки**. Multi-valued индексы —
это компромисс, а не замена нормализации.

### Сценарий 6. Валидация JSON по схеме

```sql
SELECT JSON_SCHEMA_VALID(
  '{"type":"object","required":["id","user_id","status"],
    "properties":{"id":{"type":"integer"},
                  "user_id":{"type":"integer"},
                  "status":{"type":"string","enum":["new","paid","cancelled"]}}}',
  payload
) AS is_valid
FROM shop.events;

-- Детализация для документа, не прошедшего валидацию
SELECT JSON_PRETTY(JSON_SCHEMA_VALIDATION_REPORT(schema_doc, payload)) AS report
FROM shop.events
WHERE NOT JSON_SCHEMA_VALID(schema_doc, payload)
LIMIT 5;
```

Поддерживается JSON Schema Draft 4; обязательные атрибуты поддерживаются.

### Сценарий 7. Замена тяжёлого самосоединения

```sql
-- Худший вариант: подзапрос с корреляцией на каждой строке
SELECT o1.customer_id, o1.created_at, o1.amount,
       (SELECT MAX(o2.created_at) FROM shop.orders o2
        WHERE o2.customer_id = o1.customer_id) AS last_order_at
FROM shop.orders o1;
```

```sql
-- Эквивалент с LAST_VALUE и явным фреймом
SELECT customer_id, created_at, amount,
       LAST_VALUE(created_at) OVER (
           PARTITION BY customer_id ORDER BY created_at
           RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
       ) AS last_order_at
FROM shop.orders;
```

Оба варианта корректны. Разница в стоимости: первый выполняет сканирование на каждую
строку, второй — один проход.

### Сценарий 8. Генерируемая колонка вместо вычисления в запросе

```sql
-- Было: вычисление в каждом запросе, индексировать нельзя
SELECT id FROM orders WHERE amount * quantity > 1000;

-- Стало: индекс по вычисляемому значению
ALTER TABLE shop.orders
  ADD COLUMN is_large GENERATED ALWAYS AS (amount * quantity > 1000) VIRTUAL,
  ALGORITHM=INPLACE, LOCK=NONE,
  ADD INDEX idx_is_large (is_large);
```

Результат идемпотентен, вычисляется один раз при записи и может быть покрыт индексом.

> **Осторожность:** виртуальная колонка вычисляется при каждом чтении строки. Если
> выражение дорогое (вызов функции, каскад вычислений), `VIRTUAL` увеличит стоимость
> чтения. Для дорогих выражений используйте `STORED`.

### Сценарий 9. Рекурсивный обход иерархии

```sql
WITH RECURSIVE category_tree AS (
  -- якорь: корневые категории
  SELECT id, parent_id, name, 0 AS depth, CAST(name AS CHAR(255)) AS path
  FROM shop.categories WHERE parent_id IS NULL

  UNION ALL

  -- рекурсивная часть: дети
  SELECT c.id, c.parent_id, c.name, t.depth + 1,
         CONCAT(t.path, ' / ', c.name)
  FROM shop.categories AS c
  JOIN category_tree AS t ON c.parent_id = t.id
  WHERE t.depth < 20
)
SELECT depth, path FROM category_tree ORDER BY path;
```

Значение `path` формируется в рекурсивной части, что позволяет сортировать результат
как дерево. Ограничение глубины задаётся условием `WHERE t.depth < 20` плюс общим
пределом `cte_max_recursion_depth`.

### Сценарий 10. Управление материализацией CTE через хинты

По умолчанию оптимизация решает сама, но бывает, что встраивание ухудшает план,
а материализация — улучшает (или наоборот). Явные хинты:

```sql
-- Принудительная материализация: CTE вычисляется один раз, даже при одном использовании
WITH active_users AS MATERIALIZED (
  SELECT id, name FROM users WHERE status = 'active'
)
SELECT u.*, o.total
FROM active_users u
JOIN LATERAL (
  SELECT SUM(amount) AS total FROM orders o WHERE o.user_id = u.id
) o ON TRUE;

-- Принудительное встраивание (аналог вложенного подзапроса)
WITH recent_orders AS NOT MATERIALIZED (
  SELECT user_id, created_at FROM orders ORDER BY created_at DESC
)
SELECT * FROM recent_orders WHERE created_at > '2026-01-01';
```

`MATERIALIZED` оправдан, когда CTE дорога и используется многократно, или когда
встраивание размножает строки (LATERAL-JOIN с CTE). `NOT MATERIALIZED` — когда
CTE мелкая и встраивание позволяет использовать индексы внешних таблиц напрямую.
Проверяйте `EXPLAIN FORMAT=TREE`: материализация отображается как
`Materialize`/`materialized_from_subquery`, встраивание — скрыто.

### Сценарий 11. JSON_TABLE с вложенными структурами и `FOR ORDINALITY`

```sql
SELECT o.order_id,
       item.pos, item.product, item.price, item.qty, item.opts
FROM shop.orders_json AS o,
     JSON_TABLE(
       o.payload, '$.items[*]'
       COLUMNS (
         pos         INT          FOR ORDINALITY,
         product     VARCHAR(128) PATH '$.product',
         price       DECIMAL(12,2) PATH '$.price',
         qty         INT          PATH '$.quantity',
         NESTED PATH '$.options' COLUMNS (
           opt_name  VARCHAR(50)  PATH '$.name',
           opt_value VARCHAR(255) PATH '$.value'
         )
       )
     ) AS item;
```

`FOR ORDINALITY` добавляет скрытую счётную колонку (1, 2, 3 …) — удобна для
сохранения порядка элементов массива, которого бинарный формат JSON не гарантирует.
`NESTED PATH` разворачивает массив объектов внутри объекта, сохраняя связь
родитель—потомок.

### Сценарий 12. Невидимая колонка для плавного удаления

```sql
-- Шаг 1: сделать колонку невидимой, проверить, что приложения не ломаются
ALTER TABLE shop.users
  ALTER COLUMN middle_name SET INVISIBLE;

-- Шаг 2: мониторинг — проверить, что nobody не запрашивает middle_name по имени
-- (логи приложений, slow query log, performance_schema)

-- Шаг 3: безопасное удаление
ALTER TABLE shop.users DROP COLUMN middle_name;
```

То же шаблон适用于 добавления новой колонки без изменения `SELECT *`
существующих запросов: создать `INVISIBLE`, заполнить данные, проверить,
что приложения корректно используют явное имя, и только потом перевести в
`VISIBLE`.

### Сценарий 13. Оконные функции в подзапросах UPDATE/DELETE

Оконные функции напрямую в `UPDATE`/`DELETE` не допускаются (ограничение SQL-стандарта),
но в подзапросе для отбора строк — работают:

```sql
-- Удалить дубликаты, оставив самую позднюю запись на клиента
DELETE FROM shop.orders
WHERE id IN (
  SELECT id FROM (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn
    FROM shop.orders
  ) AS ranked
  WHERE rn > 1
);
```

Без промежуточной материализации (внутреннего подзапроса `ranked`) запрос не
выполнится — ошибка `ERROR 3593: You can't specify target table for update in FROM`.

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `LAST_VALUE` возвращает значение текущей строки | Не задан фрейм окна | Добавить `RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` |
| Скользящее окно считает неверное значение | `RANGE` вместо `ROWS` в условии с неуникальным `ORDER BY` | Заменить на `ROWS BETWEEN n PRECEDING AND CURRENT ROW` |
| `ERROR 3593: You can't specify target table for update in FROM` | Попытка изменить таблицу через подзапрос с тем же именем | Материализовать в CTE с другим именем или во временную таблицу |
| `ERROR 3636: Recursive query aborted after N iterations` | Достигнут `cte_max_recursion_depth` | Увеличить `cte_max_recursion_depth` на сессию либо уточнить условие рекурсии |
| `ERROR 3819: An unsupported expression was found in a generated column definition` | Подзапрос или недетерминированная функция в выражении | Перенести вычисление в представление или триггер; либо использовать `STORED` с допустимым выражением |
| JSON выводится в другом формате, чем записан | Нормализация документа при вставке | Сравнивать значения, а не текст; использовать `JSON_PRETTY()` для читаемого вывода |
| Порядок ключей JSON не сохраняется | Нормализация отбрасывает дубликаты и не гарантирует порядок | Не полагаться на порядок ключей; ориентироваться на ключ |
| Поиск по JSON медленный | Нет индекса по выражению | Добавить индекс на `JSON_VALUE(...)` или multi-valued index; лучше — вынести в колонку |
| `JSON_TABLE` не возвращает строк | Путь не совпадает со структурой документа | Проверить `JSON_PRETTY(payload)` и путь; учесть регистр имён (нечувствителен с 8.0.27) |

## Лучшие практики

- **Оконные функции вместо коррелированных подзапросов.** Практически всегда
  дешевле, план исполнения прозрачнее.
- **Всегда задавать фрейм явно для `LAST_VALUE` и `NTH_VALUE`.** Поведение по умолчанию
  интуитивно неожиданно.
- **`ROWS` для «N последних строк», `RANGE` для «с начала периода».** Это разные
  семантики, и путаница не даёт ошибок — только неверные числа.
- **Не хранить в JSON то, что фильтруется и сортируется.** Multi-valued индексы
  закрывают точечные случаи, но не заменяют обычные колонки с индексами.
- **Генерируемые колонки — для дешёвых идемпотентных выражений.** Дорогое выражение
  хранить `STORED`, а не вычислять `VIRTUAL` при каждом чтении.
- **Проверять план после перехода на 8.x.** Оконная функция может изменить порядок
  обработки и привести к сортировке там, где её не ожидали.

## Дополнительная информа

### Версии возможностей

| Возможность | Версия |
| :--- | :--- |
| Тип `JSON` как бинарный формат | MySQL 5.7 |
| Оконные функции, CTE, `JSON_TABLE` | MySQL 8.0 |
| Индексы на выражениях (functional indexes), invisible indexes, `sql_require_primary_key` | MySQL 8.0.13 |
| `LATERAL`-производные таблицы | MySQL 8.0.14 |
| `JSON_OVERLAPS()`, `MEMBER OF()`, `JSON_SCHEMA_VALID()`, `JSON_SCHEMA_VALIDATION_REPORT()`, multi-valued indexes для JSON | MySQL 8.0.17 |
| Алиас строки в `INSERT ... ON DUPLICATE KEY UPDATE` (вместо `VALUES()`) | MySQL 8.0.20 |
| Невидимые колонки (`INVISIBLE`) | MySQL 8.0.23 |
| Хинт `MATERIALIZED` / `NOT MATERIALIZED` для CTE | MySQL 8.0.24 |
| Регистронезависимое сравнение имён колонок в `JSON_TABLE` | MySQL 8.0.27 |
| Максимум 127 окон на `SELECT` | MySQL 8.0.28 |
| **MySQL 8.0 End of Life** | 8.0.46, апрель 2026 |

### Граничные случаи и ограничения

- **Оконные функции не снимают необходимость сортировки.** `ORDER BY` внутри `OVER`
  почти всегда приводит к сортировке даже при наличии индекса; `PARTITION BY` может
  использовать индекс и избежать её.
- **`RANK`, `DENSE_RANK` и `PERCENT_RANK` требуют `ORDER BY`** — без порядка ранга нет.
- **`ROW_NUMBER` всегда уникален**, даже при полном совпадении значений `ORDER BY`.
  Порядок среди равных в этом случае не определён и может меняться.
- **Бинарный формат JSON означает, что `JSON_SEARCH` и `LIKE` по тексту бесполезны** —
  пробегать нужно по JSON-функциям.
- **`JSON` не поддерживает прямых сравнений с подстрокой.** Для полнотекстового поиска
  по JSON нужен индекс на выражении либо внешний движок — см.
  [Индексы в MySQL](./indexing.md).
- **Рекурсивные CTE ограничены по глубине** и по тому, какие операции допустимы в
  рекурсивной части (агрегирование и оконные функции в ней не разрешены).
- **Оконные функции не допускаются в `UPDATE`/`DELETE` напрямую**, только в подзапросы
  для отбора строк (см. сценарий 13).
- **`GROUPS` и `EXCLUDE` не поддерживаются.** Парсер распознаёт `GROUPS BETWEEN`,
  `EXCLUDE NO OTHER`, `IGNORE NULLS`, `FROM LAST`, но выдаёт ошибку. Поддерживаются
  только `ROWS`/`RANGE` и `RESPECT NULLS`/`FROM FIRST`.
- **Максимум 127 окон на один `SELECT`** (с MySQL 8.0.28). При превышении — ошибка.
  Каждое отдельное окно в `OVER` учитывается; именованные окна через `WINDOW`
  также суммируются.
- **`DISTINCT` в агрегатных оконных функциях не поддерживается** (например,
  `COUNT(DISTINCT col) OVER (...)`).
- **Вложенные оконные функции не поддерживаются** — оконная функция не может
  вызываться из другой оконной функции.
- **Динамические границы фрейма не поддерживаются** — границы не могут зависеть
  от значения текущей строки.
- **Multi-valued индекс — не замена нормализации.** Он индексирует элементы массива,
  но не решает задачи фильтрации по вложенным объектам, агрегации или сортировки
  по полям внутри JSON. Для систематического использования JSON как основного
  хранилища выносите ключевые поля в отдельные колонки.
- **`JSON_TABLE` не разворачивает документы с путями, содержащими `*` или `**`.**
  Такие пути допускаются только в `JSON_EXTRACT` и подобных функциях.
- **`JSON_SCHEMA_VALID` поддерживает только Draft 4**, `$ref` и внешние ресурсы
  не поддерживаются. Регулярные выражения в схеме молча игнорируются при ошибке.
- **Невидимые колонки не могут входить в `PRIMARY KEY`.** Первичный ключ всегда
  видим. Если в таблице нет явного PK, но есть `UNIQUE NOT NULL` индекс — он
  рассматривается как неявный PK и тоже не может быть скрыт.
- **`INVISIBLE` колонки всё равно участвуют в индексах и ограничениях.**
  Скрытие влияет только на `SELECT *` и поведение оптимизатора по умолчанию.
- **Функциональные индексы (functional indexes) реализуются как скрытые
  виртуальные генерируемые колонки.** Это означает, что ограничения на
  выражения генерируемых колонок (нет подзапросов, нет недетерминированных
  функций) распространяются и на индексы на выражениях.
- **`STORED` генерируемая колонка на большой таблице — операция, перестраивающая
  таблицу.** Проверяйте через [Online Schema Change](./Operations/online-schema-change.md).
- **`MATERIALIZED`/`NOT MATERIALIZED` не применяются к рекурсивным CTE.**
  Рекурсивные CTE всегда материализуются.
- **`MERGE`/`NO_MERGE` — альтернативные хинты.** Вместо синтаксиса CTE
  можно использовать оптимизационные хинты в главном запросе:
  `SELECT /*+ MERGE(cte) NO_MERGE(cte2) */ ...`. Оба способа эквивалентны.

### Внешние ресурсы

- [MySQL 8.4 Reference: Window Functions](https://dev.mysql.com/doc/refman/8.4/en/window-functions.html)
- [MySQL 8.4 Reference: WITH (Common Table Expressions)](https://dev.mysql.com/doc/refman/8.4/en/with.html)
- [MySQL 8.4 Reference: The JSON Data Type](https://dev.mysql.com/doc/refman/8.4/en/json.html)
- [MySQL 8.4 Reference: JSON Table Functions](https://dev.mysql.com/doc/refman/8.4/en/json-table-functions.html)
- [MySQL 8.4 Reference: Functional Indexes](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)
- [MySQL 8.4 Reference: Invisible Indexes](https://dev.mysql.com/doc/refman/8.4/en/invisible-indexes.html)
- [MySQL 8.0 Release Notes (EoL announcement)](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/)

### Откат и очистка

| Действие | Как отменить | Последствия |
| :--- | :--- | :--- |
| `ALTER INDEX idx INVISIBLE` | `ALTER INDEX idx VISIBLE` | Индекс продолжает обслуживаться; оптимайзер перестаёт его использовать |
| `ALTER COLUMN c SET INVISIBLE` | `ALTER COLUMN c SET VISIBLE` | Данные не теряются; `SELECT *` возвращается к исходному виду |
| `ADD COLUMN ... GENERATED VIRTUAL` | `DROP COLUMN` | Виртуальная колонка не занимает места на диске; индекс на неё нужно удалить отдельно |
| `ADD COLUMN ... GENERATED STORED` | `DROP COLUMN` | Перестраивает таблицу; на большой — через [Online Schema Change](./Operations/online-schema-change.md) |
| `WITH cte AS MATERIALIZED (...)` | Удалить хинт | Поведение по умолчанию; проверить план через `EXPLAIN FORMAT=TREE` |
| `INSERT ... ON DUPLICATE KEY UPDATE` | `DELETE` по ключу + `INSERT` | Атомарная операция не откатывается; для отката используйте транзакцию |
| `ALTER TABLE ... ADD multi-valued index` | `DROP INDEX` | Индекс удаляется мгновенно; данные в JSON-колонке не трогаются |

### См. также
- **[Индексы в MySQL](./indexing.md)** — индексы на выражениях, multi-valued indexes,
  invisible indexes, functional indexes.
- **[EXPLAIN и оптимизация](./Operations/explain_and_optimization.md)** — `FORMAT=TREE`
  для оконных запросов, `DEPENDENT SUBQUERY`, материализация CTE.
- **[Online Schema Change](./Operations/online-schema-change.md)** — добавление
  генерируемой колонки и multi-valued индекса на большой таблице.
- **[Конфигурация MySQL](./configuration.md)** — `cte_max_recursion_depth`,
  `optimizer_switch`, `sql_mode`, `tmp_table_size`/`max_heap_table_size`.
- **[Мониторинг MySQL](./monitoring.md)** — отслеживание производительности оконных
  запросов и CTE через `performance_schema`.
- **[SQL mode](./sql-mode.md)** — `NO_BACKSLASH_ESCAPES` и `ANSI_QUOTES` при работе
  со строковыми литературалами.
- **[Работа с данными](./data-loading.md)** — массовые загрузки, совместимость с
  `INSERT ... ON DUPLICATE KEY UPDATE`.
