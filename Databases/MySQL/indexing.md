# Индексы в MySQL

**Актуально для:** MySQL 8.0.x / 8.4 LTS

Специфичные для MySQL структуры данных и стратегии индексирования. Общие теоретические основы (B-Tree, Hash, селективность, кардинальность) описаны в руководстве **[Индексы баз данных](../Concepts/indexes.md)**.

---

## Определения

**B-Tree (B+Tree) Index** — стандартный тип индекса в InnoDB. Хранит данные в отсортированном виде, позволяя выполнять поиск по точному значению, диапазону и префиксу.

**Full-text Index** — специализированная инвертированная структура для быстрого текстового поиска в больших объемах данных. Поддерживает лингвистический анализ и ранжирование результатов.

**Spatial Index (R-Tree)** — индекс для пространственных данных (координат, полигонов). Позволяет эффективно решать задачи типа «найти все точки внутри области».

**Functional Index** — индекс, построенный на основе выражения или функции. В MySQL до 8.0.13 реализовывался через виртуальные колонки, начиная с 8.0.13 — напрямую как функциональный индекс.

**Multi-Valued Index** — вторичный индекс для массивов внутри JSON-колонок (MySQL 8.0.17+). В отличие от обычного индекса (1:1), имеет соотношение N:1 — одно значение в индексе может ссылаться на несколько записей.

**Descending Index** — индекс, ключи которого хранятся в порядке убывания (MySQL 8.0.12+). Ранее (до 8.0) ключевое слово `DESC` в определении индекса игнорировалось.

**Covering Index** — индекс, содержащий все столбцы, необходимые для выполнения запроса. СУБД выполняет **Index Only Scan**, не обращаясь к основной таблице.

**Composite Index** — составной индекс, построенный на двух и более колонках. Порядок колонок определяет, какие запросы могут его использовать (правило левого префикса).

**Индексная селективность (Index Selectivity)** — отношение количества уникальных значений в индексированном столбце к общему числу строк. Высокая селективность (близкая к 1.0) делает индекс наиболее эффективным.

**Page Split** — операция разделения переполненной страницы B-Tree на две при вставке нового ключа. Происходит при заполнении страницы на 100%. Вызывает фрагментацию и снижение производительности.

**Invisible Index** — индекс, существующий в базе, но невидимый для оптимизатора. Позволяет безопасно тестировать необходимость индекса в production без блокировок и риска деградации.

**Skip Scan** — стратегия доступа к индексу (MySQL 8.0.13+), позволяющая использовать индекс для условий, где левый префикс составного индекса отсутствует. Полезен для колонок с низкой кардинальностью.

**Index Merge** — оптимизация, при которой MySQL объединяет несколько индексов для выполнения одного запроса (intersection, union, sort-union). Используется, когда один индекс не покрывает все условия `WHERE`.

---

## Архитектура хранения индексов в InnoDB

InnoDB хранит индексы в табличных пространствах (`ibdata1` + файлы `*.ibd` в режиме `file-per-table`) в виде B+Tree страниц по 16 KB.

**Структура B+Tree в InnoDB:**
*   **Уровень листьев (Leaf Level):** содержит указатели на строки таблицы (PK) или на PK для вторичных индексов. Данные в листьях связаны двусвязным списком, что позволяет выполнять `ORDER BY ... ASC/DESC` без дополнительной сортировки при совпадении порядка индекса.
*   **Внутренние уровни:** содержат только ключи и указатели на дочерние страницы. Используются для навигации к листьям.
*   **Fill Factor:** InnoDB заполняет страницы на ~15% свободного места (`innodb_fill_factor`, по умолчанию 100 для индексов, но каждый page оставляет ~15% свободного места для будущих вставок).

**SRE-важность:** Понимание страничной структуры объясняет, почему массовые `INSERT` с автоинкрементом вызывают page splits на конце индекса, а `UPDATE` случайных строк — внутри дерева, что приводит к фрагментации.

---

## Базовые концепции

### 1. B-Tree и его особенности в InnoDB

В MySQL InnoDB B-Tree индексы всегда **кластерные** (Clustered Index) для первичного ключа.

**Кластерный индекс:** Данные таблицы хранятся прямо в листьях B-Tree. Первичный ключ определяет физический порядок строк на диске. Если первичный ключ не задан явно, InnoDB создает скрытый 6-байтный индекс.

**Вторичные индексы (Secondary Indexes):** Хранят в листьях не адрес строки, а значение первичного ключа. Это приводит к двойному поиску (Double Lookup) при обращении к неиндексированным полям, если не используется **Covering Index**.

```sql
-- Пример: кластерный индекс по первичному ключу
CREATE TABLE orders (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,  -- кластерный индекс
    user_id INT,
    total DECIMAL(10,2),
    created_at DATETIME,
    INDEX idx_user (user_id)              -- вторичный индекс (хранит id)
);
```

**Double Lookup — как это работает:**
1. Optimizer находит значение `user_id` во вторичном индексе `idx_user`.
2. Из индекса извлекает значение первичного ключа (`id`).
3. Выполняет поиск по кластерному индексу для получения полной строки.

**Covering Index устраняет Double Lookup:**
```sql
-- Этот запрос использует только idx_user + кластерный индекс
SELECT user_id, total FROM orders WHERE user_id = 5;
-- Если добавить covering index:
CREATE INDEX idx_user_total ON orders (user_id, total);
-- Теперь запрос выполняется полностью из индекса (Index Only Scan)
```

**Index Merge (MySQL 8.0+):**
Иногда оптимизатор объединяет несколько индексов для одного запроса (`index_merge`). Это лучше, чем полное сканирование, но обычно хуже, чем один хорошо спроектированный составной индекс.

```sql
-- Запрос с двумя equality-условиями
SELECT * FROM orders WHERE user_id = 5 AND status = 'pending';
-- Если есть отдельные индексы idx_user и idx_status, MySQL может:
-- 1. Intersection: взять пересечение PK из обоих индексов
-- 2. Union: объединить результаты (для OR)
-- 3. Sort-Union: объединить и отсортировать
```

**SRE-заметка:** Index Merge — компромисс. Для горячих запросов проектируйте составной индекс вместо зависимости от Index Merge.

### 2. Порядок колонок в составных индексах (Composite Index)

Составной индекс `(A, B, C)` работает по **правилу левого префикса**:

| Запрос (WHERE)                | Индекс `(A, B, C)` используется? |
|-------------------------------|-----------------------------------|
| `WHERE A = 1`                 | Да (полный префикс)               |
| `WHERE A = 1 AND B = 2`       | Да (полный префикс)               |
| `WHERE A = 1 AND B = 2 AND C = 3` | Да (полный ключ)             |
| `WHERE B = 2`                 | Нет (нет левого префикса)         |
| `WHERE B = 2 AND C = 3`       | Нет                               |
| `WHERE A = 1 AND C = 3`       | Только часть A используется        |
| `WHERE A > 1 AND A < 10`      | Да (диапазон по первой колонке)    |
| `WHERE A = 1 AND B > 2 AND B < 10` | Да (диапазон по B в пределах A) |

**Принцип упорядочения колонок:**
1. Колонки изequality-условий (`=`, `IN`) идут первыми.
2. Колонки из range-условий (`>`, `<`, `BETWEEN`, `LIKE 'abc%'`) идут после equality-колонок.
3. Используйте `ORDER BY` для определения порядка сортировки.

```sql
-- Запрос: SELECT * FROM orders WHERE status = 'active' AND total > 100 ORDER BY created_at;
-- Лучший составной индекс:
CREATE INDEX idx_status_total_created ON orders (status, total, created_at);
-- status (equality) → total (range) → created_at (ORDER BY)
```

### 3. Adaptive Hash Index (AHI)

Внутренний механизм InnoDB. MySQL автоматически создает хеш-индексы для страниц B-Tree, к которым происходит наиболее частое обращение.

- **Цель:** Превратить поиск по дереву ($O(\log n)$) в поиск по хеш-таблице ($O(1)$) в памяти.
- **Версионные изменения:**
  - MySQL 8.0: включен по умолчанию (`innodb_adaptive_hash_index=ON`).
  - MySQL 8.4 LTS: отключен по умолчанию (`innodb_adaptive_hash_index=OFF`) — Oracle признал, что AHI приносит пользу далеко не всем рабочим нагрузкам и может вредить на многоядерных системах.
- **SRE-заметка:** При очень высокой нагрузке на запись или на многоядерных системах AHI может стать источником конфликтов (mutex contention). Рекомендуется тестирование с включенным и выключенным AHI на реальной нагрузке. Отключается параметром `innodb_adaptive_hash_index=OFF`.

### 4. Full-text Index (Полнотекстовый поиск)

Используется для поиска слов в колонках `CHAR`, `VARCHAR` или `TEXT`.

**Механика:** Создает инвертированный индекс (Inverted Index), где ключами являются отдельные слова, а значениями — списки документов (строк), где они встречаются.

**Режимы:**
- `NATURAL LANGUAGE MODE`: Поиск по смыслу, ранжирование по релевантности.
- `BOOLEAN MODE`: Поддержка операторов `+` (обязательно), `-` (исключить), `*` (wildcard).
- `WITH QUERY EXPANSION`: Двухэтапный поиск — сначала находится релевантный набор, затем по нему проводится второй поиск для расширения результатов.

**Ограничения и настройки:**
- В InnoDB стоп-слова и минимальная длина слова настраиваются через `innodb_ft_min_token_size` (по умолчанию 3, т.е. слова короче 3 символов индексируются, если установлено 0).
- Максимальная длина ключевого слова определяется `innodb_ft_max_token_size`.
- Нестандартный разбор текста возможен через `ngram` или `mecab` parser:
```sql
-- Включение ngram-парсера для поддержки CJK-текстов
ALTER TABLE articles ADD FULLTEXT INDEX ft_body (body) WITH PARSER ngram;
```

### 5. Spatial Index (R-Tree)

Для работы с типами `GEOMETRY`, `POINT`, `POLYGON`.

**Архитектура:** Использует структуру **R-Tree** (Rectangle Tree), которая группирует объекты по их минимальным охватывающим прямоугольникам (MBR).

**Применение:** Операции `ST_Contains`, `ST_Within`, `ST_Distance`, `ST_Intersects`.

**Требования:**
- Колонка должна быть `NOT NULL`.
- Для эффективной работы в MySQL 8.0+ необходим объявленный `SRID` (Spatial Reference System ID).
- Пространственные индексы поддерживаются только для InnoDB.
- Ключевое слово `ASC`/`DESC` запрещено в определении пространственного индекса (MySQL 8.0.12+).

### 6. Индексы на виртуальных колонках (JSON)

MySQL не позволяет индексировать весь JSON-документ целиком, но позволяет индексировать отдельные его поля.

**Механизм:** Создается виртуальная колонка, которая извлекает значение из JSON, и на эту колонку вешается обычный B-Tree индекс. Начиная с MySQL 8.0.13, можно создавать функциональный индекс напрямую без явной виртуальной колонки.

```sql
-- Способ 1: Через виртуальную колонку (MySQL 5.7+, 8.0+)
ALTER TABLE users ADD COLUMN user_name VARCHAR(50)
    AS (JSON_UNQUOTE(data->>'$.name')) VIRTUAL;
CREATE INDEX idx_user_name ON users (user_name);

-- Способ 2: Функциональный индекс напрямую (MySQL 8.0.13+)
CREATE INDEX idx_user_name ON users ((CAST(data->>'$.name' AS CHAR(50))));
```

**Преимущество:** Индекс занимает место, но сама виртуальная колонка в таблице (Virtual Column) не потребляет место на диске.

**Ограничения:**
- Функциональный индекс не используется, если выражение в `WHERE` не совпадает с выражением в определении индекса (включая скобки и пробелы).
- Невозможно создать covering index для функционального индекса напрямую — обращение к колонке требует дополнительного чтения кластерного индекса.

### 7. Multi-Valued Indexes (MySQL 8.0.17+)

Специализированные индексы для эффективного поиска по массивам внутри JSON-колонок.

**Механика:** Для каждого элемента JSON-массива создается отдельная запись в индексе. Все записи ссылаются на одну строку таблицы (соотношение N:1).

```sql
-- Создание таблицы с JSON-массивом
CREATE TABLE customers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100),
    data JSON
);

-- Создание multi-valued индекса на массив zip-кодов
CREATE INDEX idx_zipcodes ON customers (
    (CAST(data->'$.zipcode' AS UNSIGNED ARRAY))
);

-- Запросы, использующие multi-valued индекс:
SELECT * FROM customers WHERE 94477 MEMBER OF(data->'$.zipcode');
SELECT * FROM customers WHERE JSON_CONTAINS(data->'$.zipcode', '94536');
SELECT * FROM customers WHERE JSON_OVERLAPS(data->'$.zipcode', '[94477, 94536]');
```

**Ограничения:**
- Только один multi-valued ключевой компонент допускается в составном индексе.
- Multi-valued индекс не может быть primary key, не поддерживает `ASC`/`DESC`.
- Не может быть covering index.
- Максимальное количество значений на запись ограничено размером страницы undo-лога (65221 байт).
- Не поддерживает range scans и index-only scans.
- Онлайн-создание multi-valued индекса не поддерживается (требуется блокировка таблицы или `ALGORITHM=COPY`).

### 8. Descending Indexes (MySQL 8.0.12+)

В MySQL 8.0+ ключевое слово `DESC` в определении индекса хранит ключи в порядке убывания на диске. Ранее (до 8.0) `DESC` игнорировался, и индекс всегда хранился по возрастанию.

**Значение:** Для запросов с `ORDER BY column DESC` нативный descending index позволяет выполнять сканирование в прямом направлении, что эффективнее обратного сканирования ascending-индекса.

```sql
-- Индекс для efficient сортировки по убыванию
CREATE INDEX idx_created_desc ON events (created_at DESC);

-- Составной индекс со смешанным порядком сортировки
CREATE INDEX idx_cust_total_desc ON orders (customer_id ASC, total DESC);
-- Подходит для: ORDER BY customer_id ASC, total DESC
```

**Проверка использования:** В `EXPLAIN` отсутствует `Using filesort`, если индекс соответствует порядку `ORDER BY`.

### 10. Skip Scan (MySQL 8.0.13+)

Стратегия доступа, позволяющая использовать индекс, когда левый префикс составного индекса отсутствует в условии `WHERE`.

**Механика:** InnoDB сканирует индекс многократно, пропуская лидирующие колонки. Эффективен для колонок с низкой кардинальностью (few distinct values).

```sql
-- Составной индекс (a, b, c)
CREATE INDEX idx_abc ON t (a, b, c);

-- Запрос WHERE b = 2 не использует левый префикс, но Skip Scan может помочь:
SELECT * FROM t WHERE b = 2;
-- Вместо full scan: сканирует индекс по уникальным значениям a
```

**Ограничения:**
*   Доступен только для InnoDB.
*   Не всегда быстрее full scan — зависит от кардинальности колонки `a`.
*   В `EXPLAIN` отображается как `type = index` или `range` с `key = idx_abc`.

### 11. Loose Index Scan (GROUP BY / DISTINCT)

Метод доступа для `GROUP BY` и `DISTINCT`, использующий упорядоченность B-Tree индекса: вместо сканирования всех ключей MySQL переходит от одной группы к следующей, читая минимальное число ключей.

**Механика:** при отсутствии WHERE читается столько ключей, сколько групп (может быть намного меньше всех ключей). При наличии range-предикатов — первый ключ каждой группы, удовлетворяющей условию.

**Условия применимости (все должны выполняться):**
*   Запрос по одной таблице.
*   `GROUP BY` именует только колонки, образующие **левый префикс** индекса, и никакие другие колонки.
*   Единственные агрегатные функции в SELECT — `MIN()` и `MAX()`, все на одной колонке, **немедленно следующей** за колонками `GROUP BY` в индексе.
*   Остальные части индекса, упомянутые в запросе, должны быть константами (равенства с константами), кроме аргумента `MIN()`/`MAX()`.
*   Полные значения колонок проиндексированы, не префиксы (префиксный индекс `INDEX(c1(10))` не подходит).

**Дополнительно поддерживается** (без `GROUP BY`/`DISTINCT` в запросе): `AVG(DISTINCT)`, `SUM(DISTINCT)`, `COUNT(DISTINCT)` (последний — с несколькими колонками).

```sql
-- Индекс idx(c1, c2, c3) на t1(c1, c2, c3, c4)
-- Loose Index Scan применим:
SELECT c1, c2 FROM t1 GROUP BY c1, c2;
SELECT DISTINCT c1, c2 FROM t1;
SELECT c1, MIN(c2) FROM t1 GROUP BY c1;
SELECT c1, c2 FROM t1 WHERE c1 < const GROUP BY c1, c2;
SELECT MAX(c3), MIN(c3), c1, c2 FROM t1 WHERE c2 > const GROUP BY c1, c2;
SELECT c1, c2 FROM t1 WHERE c3 = const GROUP BY c1, c2;

-- НЕ применим:
SELECT c1, SUM(c2) FROM t1 GROUP BY c1;          -- SUM, а не MIN/MAX
SELECT c1, c2 FROM t1 GROUP BY c2, c3;           -- не левый префикс
SELECT c1, c3 FROM t1 GROUP BY c1, c2;           -- c3 не в индексе после префикса
```

**Диагностика:** в `EXPLAIN` в колонке `Extra` появляется `Using index for group-by`.

**Альтернатива — Tight Index Scan:** когда условия Loose Index Scan не выполняются (например, есть разрыв в префиксе, но он задан константой), оптимизатор использует range-сканирование с последующей группировкой. В EXPLAIN — `Using index` (без "for group-by").

**SRE-заметка:** Loose Index Scan — причина, по которой `SELECT DISTINCT indexed_col` или `COUNT(DISTINCT ...)` на индексированной колонке выполняется мгновенно даже на больших таблицах. Если такой запрос внезапно стал медленным — проверьте, не исчез ли индекс (не переведён ли в INVISIBLE) и не изменился ли план.

### 9. Online DDL и индексы

InnoDB поддерживает онлайн DDL для большинства операций с индексами, что позволяет читать и писать данные во время создания или удаления индекса.

```sql
-- Создание индекса онлайн (без блокировки таблицы)
CREATE INDEX idx_email ON users (email) ALGORITHM=INPLACE, LOCK=NONE;

-- Удаление индекса онлайн
DROP INDEX idx_email ON users ALGORITHM=INPLACE, LOCK=NONE;
```

**Ограничения онлайн DDL:**
- `FULLTEXT` индексы выполняются `ALGORITHM=INPLACE`, но **не разрешают параллельный DML** — запись блокируется на время операции. Первый `FULLTEXT`-индекс перестраивает таблицу, если нет пользовательской колонки `FTS_DOC_ID`; последующие добавляются без перестройки.
- `SPATIAL` индексы также выполняются `ALGORITHM=INPLACE` без параллельного DML.
- Multi-valued индексы создаются как функциональные индексы поверх скрытой виртуальной колонки; применимый алгоритм проверяется пробным `ALTER` с явным `ALGORITHM` на копии таблицы — [Online Schema Change](./Operations/online-schema-change.md).
- При `ALGORITHM=COPY` таблица блокируется на время операции.

---

## Практические сценарии

### Сценарий 1: Проектирование индексов для типичного CRUD-приложения

**Контекст:** Интернет-магазин с таблицами `users`, `orders`, `products`.

**Шаг 1: Анализ самых частых запросов**
```sql
-- Частые запросы:
SELECT * FROM orders WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC;
SELECT * FROM products WHERE category_id = ? AND price BETWEEN ? AND ?;
SELECT * FROM users WHERE email = ?;
```

**Шаг 2: Создание оптимальных индексов**
```sql
-- orders: составной индекс под основной запрос
CREATE INDEX idx_orders_user_status_created ON orders (user_id, status, created_at DESC);

-- products: составной индекс с range-колонкой
CREATE INDEX idx_products_category_price ON products (category_id, price);

-- users: уникальный индекс для логина
CREATE UNIQUE INDEX uniq_users_email ON users (email);
```

**Шаг 3: Валидация через EXPLAIN**
```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 5 AND status = 'pending' ORDER BY created_at DESC\G
-- Ожидаемый результат:
-- key: idx_orders_user_status_created
-- rows: < число строк по user_id=5 >
-- Extra: (без "Using filesort" и "Using temporary")
```

### Сценарий 2: Полнотекстовый поиск по статьям

**Шаг 1: Создание таблицы с full-text индексом**
```sql
CREATE TABLE articles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255),
    body TEXT,
    FULLTEXT INDEX ft_title_body (title, body)
) ENGINE=InnoDB;
```

**Шаг 2: Запросы в разных режимах**
```sql
-- Натуральный поиск (релевантность)
SELECT *, MATCH(title, body) AGAINST('MySQL индексы' IN NATURAL LANGUAGE MODE) AS score
FROM articles
WHERE MATCH(title, body) AGAINST('MySQL индексы' IN NATURAL LANGUAGE MODE)
ORDER BY score DESC;
-- → result: строки с релевантностью, отсортированные по score

-- Булевый поиск
SELECT * FROM articles
WHERE MATCH(title, body) AGAINST('+MySQL +оптимизация -Oracle' IN BOOLEAN MODE);
-- → result: статьи, содержащие "MySQL" и "оптимизация", но не "Oracle"

-- Поиск с подстановочными знаками
SELECT * FROM articles
WHERE MATCH(title, body) AGAINST('оптим*' IN BOOLEAN MODE);
-- → result: "оптимизация", "оптимальный", "оптимизатор"
```

**Шаг 3: Валидация**
```sql
-- Проверка, что full-text индекс используется
EXPLAIN SELECT * FROM articles WHERE MATCH(title, body) AGAINST('MySQL' IN NATURAL LANGUAGE MODE)\G
-- key: ft_title_body
-- rows: < число найденных >
```

**Ограничения и типичные ошибки:**
- Слова короче `innodb_ft_min_token_size` (по умолчанию 3) не индексируются.
- Стоп-слова исключаются из индекса — запросы с ними возвращают 0 результатов.
- Кириллические слова могут не разбиваться корректно без настройки `ngram` parser.

### Сценарий 3: Индексация JSON-массивов (Multi-Valued Index)

**Шаг 1: Создание индекса**
```sql
CREATE TABLE products (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255),
    attributes JSON,
    INDEX idx_tags ((CAST(attributes->'$.tags' AS CHAR(50) ARRAY)))
);
```

**Шаг 2: Запросы, активирующие multi-valued индекс**
```sql
-- Проверка принадлежности элемента массива
SELECT * FROM products WHERE 'electronics' MEMBER OF(attributes->'$.tags');
-- → result: все продукты с тегом "electronics"

-- Проверка вхождения значения
SELECT * FROM products WHERE JSON_CONTAINS(attributes->'$.tags', '"sale"');
-- → result: все продукты со тегом "sale"

-- Проверка пересечения массивов
SELECT * FROM products WHERE JSON_OVERLAPS(attributes->'$.tags', '["new", "featured"]');
-- → result: продукты с любым из указанных тегов
```

**Валидация:**
```sql
EXPLAIN SELECT * FROM products WHERE 'electronics' MEMBER OF(attributes->'$.tags')\G
-- key: idx_tags
-- Extra: (без "Using where" для поиска по индексу)
```

**Типичные ошибки:**
- Запрос `WHERE attributes->'$.tags' = '"electronics"'` (сравнение всего массива) — multi-valued индекс НЕ используется.
- Запрос `WHERE JSON_EXTRACT(attributes, '$.tags[0]') = 'electronics'` — тоже не использует multi-valued индекс.
- Только `MEMBER OF()`, `JSON_CONTAINS()`, `JSON_OVERLAPS()` активируют multi-valued индекс.

### Сценарий 4: Пагинация через Seek Method вместо OFFSET

**Проблема:**
```sql
-- Медленно: OFFSET пропускает 100000 строк
SELECT * FROM messages ORDER BY id DESC LIMIT 20 OFFSET 100000;
-- → result: ~5-10 секунд на большом объеме данных
```

**Решение:**
```sql
-- Быстро: Seek Method использует индекс
SELECT * FROM messages
WHERE id < :last_seen_id   -- значение id последней строки предыдущей страницы
ORDER BY id DESC
LIMIT 20;
-- → result: <10ms, независимо от глубины пагинации
```

**Валидация:**
```sql
EXPLAIN SELECT * FROM messages WHERE id < 500000 ORDER BY id DESC LIMIT 20\G
-- type: range (не ALL)
-- key: PRIMARY (или индекс по id)
-- Extra: (без "Using filesort")
```

### Сценарий 5: Проверка неявного приведения типов

**Проблема:**
```sql
-- Столбец phone имеет тип VARCHAR(20)
-- Запрос передает число:
SELECT * FROM users WHERE phone = 12345;
-- Оптимизатор применит функцию CAST к каждому значению phone,
-- что делает индекс бесполезным.
```

**Диагностика:**
```sql
EXPLAIN SELECT * FROM users WHERE phone = 12345\G
-- key: NULL (индекс не используется!)
-- Extra: Using where (условие фильтрации без индекса)
```

**Решение:**
```sql
SELECT * FROM users WHERE phone = '12345';
-- → result: индекс по phone используется корректно
```

### Сценарий 6: Невидимые индексы (Invisible Indexes) для безопасного удаления

**Контекст:** Необходимо удалить индекс, но не уверены вimpact на производительность.

**Шаг 1: Пометить индекс как невидимый**
```sql
ALTER TABLE orders ALTER INDEX idx_old INVISIBLE;
```

**Шаг 2: Мониторинг производительности в течение 1-7 дней**
```sql
-- Проверка использования индекса (индекс не должен появляться в EXPLAIN)
EXPLAIN SELECT * FROM orders WHERE ...;

-- Мониторинг через performance_schema (MySQL 8.0+)
SELECT * FROM performance_schema.table_io_waits_summary_by_index_usage
WHERE OBJECT_SCHEMA = 'your_db' AND OBJECT_NAME = 'orders';
```

**Шаг 3: Решение**
```sql
-- Если нагрузка не выросла — безопасно удалять:
ALTER TABLE orders ALTER INDEX idx_old INVISIBLE;  -- оставляем невидимым
-- или
DROP INDEX idx_old ON orders;  -- удалить навсегда

-- Если нагрузка выросла — вернуть видимость:
ALTER TABLE orders ALTER INDEX idx_old VISIBLE;
```

### Сценарий 7: Пространственный индекс для геопоиска

```sql
-- Создание таблицы с пространственными данными
CREATE TABLE stores (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100),
    location POINT NOT NULL SRID 4326,
    SPATIAL INDEX idx_location (location)
) ENGINE=InnoDB;

-- Вставка данных
INSERT INTO stores (name, location) VALUES
    ('Магазин А', ST_GeomFromText('POINT(37.6173 55.7558)', 4326)),
    ('Магазин Б', ST_GeomFromText('POINT(37.5871 55.7340)', 4326));

-- Поиск магазинов в радиусе 5 км от точки (55.75, 37.60)
SELECT name, ST_Distance_Sphere(location, ST_GeomFromText('POINT(37.60 55.75)', 4326)) AS distance_m
FROM stores
WHERE ST_Distance_Sphere(location, ST_GeomFromText('POINT(37.60 55.75)', 4326)) < 5000
ORDER BY distance_m;
-- → result: магазины в пределах 5 км, отсортированные по расстоянию

-- Поиск магазинов в прямоугольной области
SELECT * FROM stores
WHERE ST_Contains(
    ST_GeomFromText('POLYGON((37.58 55.73, 37.62 55.73, 37.62 55.76, 37.58 55.76, 37.58 55.73))', 4326),
    location
);
```

---

## Эксплуатация и автоматизация

### Безопасное добавление индексов в production

Индекс создается через `ALTER TABLE`, что может вызывать блокировки. Для SRE критично выбрать правильный алгоритм.

**Решение 1: Online DDL (MySQL 8.0+)**
```sql
-- Без блокировки записи (LOCK=NONE)
ALTER TABLE orders ADD INDEX idx_status (status), ALGORITHM=INPLACE, LOCK=NONE;
-- → result: таблица доступна для чтения и записи
```

**Решение 2: pt-online-schema-change (Percona Toolkit)**
```bash
# Для таблиц >100 GB или когда InnoDB Online DDL вызывает репликационный lag
pt-online-schema-change \
  --alter "ADD INDEX idx_email (email)" \
  D=mydb,t=users \
  --execute
# → result: таблица копируется порциями, минимальное влияние на production
```

**Решение 3: gh-ost (GitHub Online Schema Transitions)**
```bash
gh-ost \
  --alter "ADD INDEX idx_email (email)" \
  --database=mydb \
  --table=users \
  --execute
# → result: триггерless подход, минимальная нагрузка
```

**SRE-runbook:**
1. Создать индекс в staging с `ALGORITHM=INPLACE, LOCK=NONE`.
2. Проверить `EXPLAIN` на регрессию планов.
3. Замерить длительность создания на production копии (`SHOW PROCESSLIST`, `information_schema.INNODB_TRX`).
4. Применить в production в окно низкой нагрузки.
5. Мониторить `Created_tmp_disk_tables`, `Innodb_row_lock_time_avg`.

---

### Интеграция с CI/CD

Проверка планов запросов должна быть частью пайплайна:

```sql
-- Паттерн для автоматизации: убедиться что используется индекс
EXPLAIN SELECT * FROM orders WHERE user_id = ? AND status = ?\G
-- Ожидание: key IS NOT NULL AND type IN ('ref', 'eq_ref', 'const')
```

**Gate-чек:**
- `type = ALL` → FAIL (full table scan)
- `Extra LIKE '%Using filesort%'` → WARN (проверить necessity сортировки)
- `Extra LIKE '%Using temporary%'` → FAIL (кроме случаев с доказанной эффективностью)

---

### Мониторинг и алерты

**Ключевые метрики для алертов:**

| Метрика | Источник | Порог | Действие |
|---------|----------|-------|----------|
| `Innodb_buffer_pool_reads` | `SHOW GLOBAL STATUS` | Рост >20% за час | Проверить отсутствие индексов (Buffer Pool miss ratio) |
| `Created_tmp_disk_tables` | `SHOW GLOBAL STATUS` | >10% от `Created_tmp_tables` | Проверить сортировки и GROUP BY без индексов |
| `Innodb_row_lock_time_avg` | `SHOW GLOBAL STATUS` | >50ms | Проверить отсутствие индексов в UPDATE/DELETE |
| `Table_locks_waited` | `SHOW GLOBAL STATUS` | >0 за период | Проверить MyISAM/Archive таблицы |
| Размер `INDEX_LENGTH` / `DATA_LENGTH` | `information_schema.TABLES` | ratio > 2.0 | Проверить фрагментацию |

**Дашборд Prometheus + Grafana (exporter v0.20.0+):**
```yaml
# Пример метрик mysqld_exporter
- name: mysql_global_status_created_tmp_disk_tables
  query: Created_tmp_disk_tables
- name: mysql_global_status_innodb_row_lock_time_avg
  query: Innodb_row_lock_time_avg
- name: mysql_global_status_innodb_buffer_pool_reads
  query: Innodb_buffer_pool_reads
```

**Percona Monitoring and Management (PMM):**
- Дашборд `MySQL > Performance > Query Analytics` показывает `Filesort` и `Temporary tables` без указания индексов.
- Дашборд `MySQL > InnoDB Metrics` показывает `adaptive_hash_index` эффективность.

---

### Влияние индексов на бэкапы и репликацию

**Бэкапы:**
*   `mysqldump`: логический дамп. Размер зависит от `DATA_LENGTH + INDEX_LENGTH`. Чем больше индексов, тем больше дамп и дольше восстановление.
*   `xtrabackup`: физический бэкап. Копирует `ibd` файлы целиком. Большое количество индексов увеличивает размер бэкапа и время восстановления.
*   Стратегия: в production отключайте ненужные индексы перед массовой загрузкой данных, восстанавливайте после.

**Репликация:**
*   Каждая запись (`INSERT/UPDATE/DELETE`) обновляет все связанные индексы и записывает изменения в binary log.
*   Избыточные индексы увеличивают размер binary log и нагрузку на slave.
*   `ROW` формат binlog (рекомендуется) содержит измененные строки целиком. Чем больше индексов, тем больше overhead.

---

### Влияние индексов на репликацию и replication lag

Каждая запись (`INSERT/UPDATE/DELETE`) обновляет все связанные индексы и записывает изменения в binary log. Избыточные индексы увеличивают размер binary log и нагрузку на slave, что может привести к репликационному отставанию (replication lag).

**Диагностика:**
```sql
-- Размер binlog
SHOW MASTER STATUS\G
-- → result: File, Position, Binlog_Do_DB, Binlog_Ignore_DB

-- Размер индексов
SELECT TABLE_SCHEMA, TABLE_NAME, 
       ROUND(INDEX_LENGTH / 1024 / 1024, 2) AS idx_mb
FROM information_schema.TABLES
WHERE TABLE_SCHEMA NOT IN ('mysql', 'sys', 'performance_schema', 'information_schema')
ORDER BY idx_mb DESC;
```

**Рекомендация:** На slave можно отключать неиспользуемые индексы (если slave используется только для чтения и reporting), но только после тестирования.

### Проверка использования индексов через EXPLAIN

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 5;
```

**Ключевые колонки EXPLAIN:**

| Колонка    | На что смотреть |
|------------|-----------------|
| `type`     | `system` > `const` > `eq_ref` > `ref` > `range` > `index` > `ALL` (от лучшего к худшему) |
| `key`      | Выбранный индекс (NULL если индекс не используется) |
| `key_len`  | Длина используемой части составного индекса (короче = используется не весь индекс) |
| `rows`     | Оценочное количество строк, которые будут проверены |
| `filtered` | Процент строк, прошедших фильтрацию после использования индекса |
| `Extra`    | Дополнительная информация: `Using index` (covering), `Using filesort`, `Using temporary` |

**Важные значения Extra:**
- `Using index` — запрос выполняется через covering index (ideal).
- `Using where` — дополнительная фильтрация после чтения индекса.
- `Using filesort` — сортировка не может быть выполнена через индекс (плохо).
- `Using temporary` — используется временная таблица (плохо для производительности).

**EXPLAIN ANALYZE (MySQL 8.0.18+)** — показывает реальное время выполнения (не оценку):
```sql
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 5 ORDER BY created_at DESC LIMIT 10\G
-- → result: actual execution plan с реальными временами и row counts
```

**SRE-применение:** Используйте `EXPLAIN ANALYZE` в CI/CD для критичных запросов. Сравнивайте actual time с budget. Если actual > budget — FAIL сборка.

### Анализ избыточных и неиспользуемых индексов

Индексы замедляют `INSERT/UPDATE/DELETE`. Рекомендуется удалять неиспользуемые индексы.

```sql
-- Неиспользуемые индексы (никогда не участвовали в запросах)
SELECT * FROM sys.schema_unused_indexes
WHERE object_schema NOT IN ('mysql', 'sys', 'performance_schema', 'information_schema');

-- Избыточные индексы (покрытие одним индексом другого)
SELECT * FROM sys.schema_redundant_indexes
WHERE table_schema NOT IN ('mysql', 'sys', 'performance_schema', 'information_schema');
```

**Пример вывода schema_redundant_indexes:**
```
+-----------+------------+-----------------+--------------------+---------------------+
| table     | redundant  | dominated       | dominated_index    | dominant_index      |
+-----------+------------+-----------------+--------------------+---------------------+
| orders    | idx_user   | idx_user_status | idx_user_status    | idx_user (user_id)  |
+-----------+------------+-----------------+--------------------+---------------------+
-- idx_user (user_id) полностью покрывается idx_user_status (user_id, status)
```

### Мониторинг через performance_schema

```sql
-- Индексы, которые использовались/не использовались за текущий период
SELECT
    OBJECT_SCHEMA,
    OBJECT_NAME,
    INDEX_NAME,
    COUNT_READ,
    COUNT_WRITE,
    COUNT_FETCH
FROM performance_schema.table_io_waits_summary_by_index_usage
WHERE OBJECT_SCHEMA = 'your_database'
  AND INDEX_NAME IS NOT NULL
ORDER BY COUNT_READ DESC;
-- → result: статистика использования каждого индекса
```

### Фрагментация индексов

При частых обновлениях B-Tree дерево становится разреженным.

**Признаки:**
- Индекс занимает значительно больше места, чем данные.
- Медленные range-scan запросы при малом количестве строк.

**Диагностика:**
```sql
-- Проверка размера индексов
SELECT
    TABLE_NAME,
    INDEX_LENGTH,
    DATA_LENGTH,
    ROUND(INDEX_LENGTH / DATA_LENGTH, 2) AS index_data_ratio
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'your_database'
  AND TABLE_NAME = 'orders';
-- → result: ratio > 1.0 указывает на избыточную фрагментацию
```

**Лечение:**
```sql
-- Пересоздание таблицы и индексов (InnoDB)
OPTIMIZE TABLE orders;
-- → result: таблица пересоздана, фрагментация устранена

-- В MySQL 8.0.29+ можно использовать ALTER TABLE ... FORCE:
ALTER TABLE orders FORCE;
```

**Важно:** `OPTIMIZE TABLE` может выполняться онлайн (с `ALGORITHM=INPLACE`) или с блокировкой таблицы — зависит от версии MySQL и размера таблицы. На больших таблицах используйте `pt-online-schema-change` из Percona Toolkit для безблокировочного оптимизации.

### Статистика индексов

InnoDB автоматически обновляет статистику индексов, но на больших таблицах или после массовых вставок/удалений рекомендуется принудительное обновление.

```sql
-- Принудительное обновление статистики
ANALYZE TABLE orders;
-- → result: статистика обновлена, cardinality пересчитана

-- Проверка cardinality через SHOW INDEX
SHOW INDEX FROM orders;
-- → result: Cardinality — оценка количества уникальных значений
```

**Когда нужно ANALYZE TABLE:**
- После массовой загрузки данных (`LOAD DATA INFILE`, пакетные `INSERT`).
- После удаления значительного объема данных (`DELETE` более 10-20% строк).
- Если оптимизатор выбирает неоптимальный план ( seen в `EXPLAIN` ).
- Периодически в production (раз в 1-7 дней на активно обновляемых таблицах).

---

## Поиск и устранение неисправностей

### Неиспользуемый индекс

**Симптом:** Запрос выполняется через `ALL` (full table scan) вместо использования индекса.

**Диагностика:**
```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 5\G
-- type: ALL
-- key: NULL
```

**Типичные причины:**
1. **Неявное приведение типов:** Столбец `VARCHAR`, запрос с `INT`.
2. **Функция над колонкой:** `WHERE YEAR(created_at) = 2024` — индекс по `created_at` не используется.
3. **Неправильный порядок в составном индексе:** Запрос `WHERE B = 1` не использует индекс `(A, B)`.
4. **Слишком высокая селективность:** Optimizer выбирает full scan, если запрос возвращает более 20-30% строк.

**Решения:**
```sql
-- 1. Убрать функцию из условия
-- Плохо: WHERE YEAR(created_at) = 2024
-- Хорошо: WHERE created_at >= '2024-01-01' AND created_at < '2025-01-01'
-- Или: создать функциональный индекс CREATE INDEX idx_year ON orders ((YEAR(created_at)))

-- 2. Проверить типы данных
SHOW CREATE TABLE orders\G
-- Убедиться, что типы в запросе совпадают с типами столбцов

-- 3. Обновить статистику
ANALYZE TABLE orders;
```

### Файловая сортировка (Using filesort)

**Симптом:** `EXPLAIN` показывает `Extra: Using filesort`.

**Причина:** Запрос требует сортировки, которую невозможно выполнить через индекс.

**Решения:**
```sql
-- Создать индекс, соответствующий ORDER BY
-- Плохо: индекс (A, B), запрос ORDER BY B DESC
-- Хорошо: индекс (A, B DESC)

-- Или: убрать сортировку, если она не критична
-- Или: увеличить sort_buffer_size (если сортировка неизбежна)
```

### Временная таблица (Using temporary)

**Симптом:** `EXPLAIN` показывает `Extra: Using temporary`.

**Типичные причины:**
- `GROUP BY` по колонке, не покрытой индексом.
- `DISTINCT` с `GROUP BY` по разным колонкам.
- Подзапросы с `IN (SELECT ...)`.

**Решения:**
```sql
-- Для GROUP BY: создать индекс, покрывающий GROUP BY + SELECT
-- Для DISTINCT: попробовать переписать через JOIN

-- Проверка размера временных таблиц
SHOW GLOBAL STATUS LIKE 'Created_tmp%';
-- → result: Created_tmp_disk_tables > Created_tmp_tables / 10 = проблема
```

### Page Split и фрагментация

**Симптом:** Медленные вставки, рост размера таблицы без роста данных.

**Причина:** Автоматический инкрементный primary key ведет к вставкам в конец B-Tree, но `UPDATE` изменяющих строк вызывает page splits.

**Решения:**
```sql
-- 1. Анализ fragmentации
SELECT
    TABLE_NAME,
    DATA_FREE,
    ROUND(DATA_FREE / (DATA_LENGTH + INDEX_LENGTH) * 100, 2) AS frag_pct
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'your_database' AND DATA_FREE > 0;
-- → result: frag_pct > 10% = значительная фрагментация

-- 2. OPTIMIZE TABLE (online на MySQL 8.0+ с ALGORITHM=INPLACE)
OPTIMIZE TABLE orders;

-- 3. Профилактика: для VLDB таблиц используйте UUID или compound PK вместо auto-increment PK
-- или SET innodb_autoinc_lock_mode = 2 (consecutive mode, MySQL 8.0 default)
```

### Медленный CREATE INDEX на больших таблицах

**Решения:**
```sql
-- 1. Использовать онлайн-DDL (MySQL 5.6+, InnoDB):
CREATE INDEX idx_email ON users (email) ALGORITHM=INPLACE, LOCK=NONE;
-- → result: таблица доступна для чтения и записи во время создания индекса

-- 2. Для очень больших таблиц (>100GB) — pt-online-schema-change:
-- pt-online-schema-change --alter "ADD INDEX idx_email (email)" D=mydb,t=users

-- 3. Для MySQL 8.0.27+ — параллельное построение индекса:
ALTER TABLE users ADD INDEX idx_email (email), ALGORITHM=INPLACE, LOCK=NONE;
-- InnoDB использует временные файлы для ускорения построения
```

---

## Лучшие практики

### Проектирование индексов

1. **Именование:** Используйте префиксы `idx_` (обычный), `uniq_` (уникальный), `ft_` (полнотекстовый), `sp_` (пространственный). Пример: `idx_orders_user_status`.
2. **Не индексируйте всё:** Каждый индекс замедляет запись. Начинайте с первичных ключей, внешних ключей и столбцов из самых частых и тяжелых запросов.
3. **Правило левого префикса:** Порядок колонок в составном индексе определяет, какие запросы его используют. Equality-колонки первыми, range — после.
4. **Covering Index:** Добавляйте в конец составного индекса колонки из `SELECT` для Index Only Scan.
5. **Удаляйте избыточность:** Если индекс `(A, B)` покрывает индекс `(A)` — последний избыточен.
6. **Избегайте индексов на низкоселективные колонки:** Безлимитные `WHERE status = 'active'` на таблице с 2 статусами не эффективны.
7. **Тестируйте на production-объеме данных:** Размер таблицы влияет на выбор оптимизатора. Тесты на 1M строк не отражают поведение на 1B.

### Обслуживание индексов

1. **Мониторинг:** Регулярно проверяйте `sys.schema_unused_indexes` и `sys.schema_redundant_indexes`. Автоматизируйте через cron или monitoring agent.
2. **Статистика:** Выполняйте `ANALYZE TABLE` после массовых вставок/удалений. В MySQL 8.0.29+ можно использовать `ANALYZE TABLE AUTO` для инкрементального обновления.
3. **Фрагментация:** Контролируйте `DATA_FREE` через `information_schema.TABLES`. `OPTIMIZE TABLE` при фрагментации >10%.
4. **AHI:** В MySQL 8.4+ отключен по умолчанию. Включайте только после бенчмаркинга на реальной нагрузке.
5. **Capacity Planning:** Отслеживайте рост `INDEX_LENGTH` относительно `DATA_LENGTH`. Предупреждайте алертом при ratio > 2.0.

### Безопасное удаление индексов

1. Пометить индекс `INVISIBLE`.
2. Мониторить производительность 1-7 дней через `performance_schema.table_io_waits_summary_by_index_usage`.
3. Если метрики в норме — `DROP INDEX`.
4. Если деградация — вернуть `VISIBLE`.
5. **SRE:** Документируйте причину удаления в runbook и changelog.

### Версионные особенности

| Фича | MySQL 8.0 | MySQL 8.4 LTS |
|-------|-----------|---------------|
| `innodb_adaptive_hash_index` | ON (default) | OFF (default) |
| `innodb_change_buffering` | all (default) | none (default) |
| `innodb_flush_method` | fsync (default) | O_DIRECT (default) |
| `innodb_io_capacity` | 200 (default) | 10000 (default) |
| Descending Indexes | Supported (8.0.12+) | Supported |
| Multi-Valued Indexes | Supported (8.0.17+) | Supported |
| Functional Indexes | Supported (8.0.13+) | Supported |
| Skip Scan | Supported (8.0.13+) | Supported |
| Invisible Indexes | Supported (8.0.0+) | Supported |

---

## Граничные случаи и ограничения

### 1. Ограничения Online DDL

*   `FULLTEXT` и `SPATIAL` индексы выполняются `ALGORITHM=INPLACE`, но блокируют запись на время операции (параллельный DML не разрешён).
*   Multi-valued индексы — это функциональные индексы поверх скрытой виртуальной колонки; применимый `ALGORITHM` проверяется пробным `ALTER` на копии таблицы.
*   На очень больших таблицах (>500 GB) `ALGORITHM=INPLACE` может вызвать репликационный lag на slave из-за большого объема изменений в redo log.

### 2. Влияние индексов на репликацию

*   Каждая DML-операция обновляет все индексы и пишет в binary log. Избыточные индексы увеличивают размер binlog.
*   `ROW` формат binlog (рекомендуется) содержит измененные строки целиком. Чем больше индексов, тем больше overhead.
*   На slave можно отключать неиспользуемые индексы (только для read-only workloads), но это требует тестирования.

### 3. Влияние индексов на бэкапы

*   `mysqldump`: логический дамп. Размер зависит от `DATA_LENGTH + INDEX_LENGTH`. Больше индексов → больше дамп → дольше восстановление.
*   `xtrabackup`: физический бэкап. Копирует `ibd` файлы целиком. Большое количество индексов увеличивает размер бэкапа.
*   Стратегия: отключайте ненужные индексы перед массовой загрузкой данных, восстанавливайте после.

### 4. Ограничения функциональных индексов

*   Функциональный индекс не используется, если выражение в `WHERE` не совпадает точно с выражением в определении индекса (включая скобки и пробелы).
*   Невозможно создать covering index для функционального индекса напрямую — обращение к колонке требует дополнительного чтения кластерного индекса.

### 5. Ограничения Multi-Valued Indexes

*   Не может быть primary key, не поддерживает `ASC`/`DESC`.
*   Не может быть covering index.
*   Максимальное количество значений на запись ограничено размером страницы undo-лога (65221 байт).
*   Не поддерживает range scans и index-only scans.

### 6. Ограничения Spatial Indexes

*   Колонка должна быть `NOT NULL`.
*   Ключевое слово `ASC`/`DESC` запрещено в определении пространственного индекса (MySQL 8.0.12+).

### 7. Skip Scan ограничения

*   Не всегда быстрее full scan — зависит от кардинальности колонки, выступающей в роли лидирующей.
*   В `EXPLAIN` отображается как `type = index` или `range`, что может быть неочевидно для диагностики.

### 8. Фрагментация при массовых операциях

*   Массовый `DELETE` не освобождает место на диске — только помечает страницы как свободные (`DATA_FREE` растет).
*   `OPTIMIZE TABLE` пересоздает таблицу и индексы, но требует вдвое больше места на диске на время операции.
*   На replication slave массовое `DELETE` + `OPTIMIZE TABLE` может вызвать lag.

---

## Дополнительная информация

### См. также
- **[Оптимизатор MySQL: ICP, MRR, BKA](./optimizer_mechanisms.md)** — как MySQL эффективно использует индексы.
- **[Настройка производительности MySQL](./configuration.md)** — тюнинг `innodb_buffer_pool_size`.
- **[Блокировки и Deadlocks](./locking_and_deadlocks.md)** — влияние отсутствия индексов на блокировки.
- **[Мониторинг MySQL](./monitoring.md)** — Performance Schema, InnoDB Metrics.
- **[Глубокое погружение в Storage Engines MySQL](./Operations/storage_engines_deep_dive.md)** — InnoDB, MyRocks, Archive, их влияние на индексацию.
- **[Репликация MySQL](./replication/overview.md)** — влияние индексов на binlog и replication lag.
- **[Бэкапы MySQL](./backup_and_recovery/overview.md)** — влияние индексов на размер и скорость бэкапов.

### Связанные темы
- **[Индексы в базах данных](../Concepts/indexes.md)** — общие теоретические основы (B-Tree, Hash, селективность, кардинальность).
- **[Ключевые концепции производительности](../Concepts/database_performance_concepts.md)** — влияние индексов на IOPS и CPU.
