# JSON в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS (+ 13.1: операторы `->`/`->>`, `FORMAT JSON` в `JSON_TABLE`)

## Определения

*   **JSON в MariaDB** — поддержка формата JSON. **Важное отличие от MySQL:** в MariaDB нет нативного бинарного типа JSON. JSON хранится как `LONGTEXT` с ограничением `CHECK (JSON_VALID(col))`. Валидность проверяется при записи, но данные хранятся в текстовом виде.
*   **JSON-функции** — набор функций для создания, извлечения и модификации JSON. Доступны с MariaDB 10.2.
*   **`JSON_TABLE`** — функция, преобразующая JSON-массив в реляционную таблицу (табличный вывод). Доступна с MariaDB 10.6 (MDEV-17399).
*   **JSON-операторы `->` и `->>`** — сокращённый синтаксис извлечения значений из JSON. Доступны с MariaDB 13.1+ (в 10.x–12.x используйте функции `JSON_EXTRACT` / `JSON_UNQUOTE`).
*   **`JSON_VALID()`** — функция проверки валидности JSON. Используется в `CHECK`-ограничениях для эмуляции JSON-типа.
*   **Generated Column** — вычисляемый столбец, который можно индексировать. Используется для индексации значений внутри JSON (аналог функциональных индексов MySQL 8.0.13+).
*   **`JSON_QUERY(json, path)`** — извлекает объект или массив по пути, возвращая `NULL`, если путь не найден или значение скалярное. Часть SQL/JSON standard (MariaDB 10.6+).
*   **`JSON_VALUE(json, path)`** — извлекает скалярное значение по пути, возвращая `NULL`, если путь не найден или значение является объектом/массивом. Часть SQL/JSON standard (MariaDB 10.6+).
*   **`JSON_EXISTS(json, path)`** — проверяет существование элемента по пути; возвращает `1`/`0`/`NULL`. Часть SQL/JSON standard (MariaDB 10.6+).
*   **`JSON_ARRAYAGG(expr)`** — агрегатная функция, объединяющая значения столбца в JSON-массив.
*   **`JSON_OBJECTAGG(key, value)`** — агрегатная функция, объединяющая пары ключ-значение в JSON-объект.
*   **`JSON_SEARCH(json, return, search_str)`** — ищет строку в JSON и возвращает путь к найденному элементу.
*   **`JSON_QUOTE(str)`** — экранирует строку как JSON-строковое значение (добавляет кавычки и escape-символы).
*   **`JSON_SCHEMA_VALID(schema, json)`** — проверяет JSON-документ против JSON Schema.
*   **`JSON_LOOSE(json)`** — сериализует JSON без пробелов (компактный вывод без изменения данных), полезно для хранения в `LONGTEXT`.

## Предварительные требования

*   **MariaDB 10.2+** — базовые JSON-функции (`JSON_EXTRACT`, `JSON_SET`, `JSON_OBJECT`, `JSON_ARRAY` и др.).
*   **MariaDB 10.6+** — `JSON_TABLE`, `JSON_QUERY`, `JSON_VALUE`, `JSON_EXISTS`.
*   **MariaDB 10.9+** — расширенный JSONPath: отрицательные индексы (`[-N]`), `last`-ключевое слово, диапазоны (`[M to N]`).
*   **MariaDB 13.1+** — операторы `->` и `->>`; поддержка `FORMAT JSON` в `JSON_TABLE` для извлечения вложенных объектов/массивов.
*   **Столбцы с JSON** требуют `CHECK (JSON_VALID(col))` — MariaDB не проверяет валидность автоматически, в отличие от MySQL.

## Базовые концепции

### Хранение JSON

Поскольку MariaDB не имеет бинарного JSON-типа, рекомендуемый паттерн создания таблицы с JSON:

```sql
CREATE TABLE events (
  id INT PRIMARY KEY AUTO_INCREMENT,
  payload LONGTEXT
    CHECK (JSON_VALID(payload))
);
```

**Отличия от MySQL:**

*   MySQL: нативный тип `JSON`, бинарное хранение, автоматическая валидность.
*   MariaDB: `LONGTEXT` + `CHECK (JSON_VALID(...))`, текстовое хранение, валидность через CHECK-ограничение.

**Почему текстовое хранение важно для SRE:** каждый `INSERT`/`UPDATE` с `CHECK (JSON_VALID())` требует полного парсинга JSON. При высокой частоте записи это становится узким местом. Размер `LONGTEXT` не ограничен `max_allowed_packet` при хранении, но `max_allowed_packet` влияет на отправку JSON клиентом.

### Функции JSON

| Функция | Назначение | Версия |
| :--- | :--- | :--- |
| `JSON_ARRAY(...)` | Создать JSON-массив | 10.2+ |
| `JSON_OBJECT(...)` | Создать JSON-конструктор | 10.2+ |
| `JSON_EXTRACT(json, path)` | Извлечь значение по пути | 10.2+ |
| `JSON_UNQUOTE(str)` | Убрать кавычки со строки JSON | 10.2+ |
| `JSON_SET(json, path, val)` | Установить значение по пути | 10.2+ |
| `JSON_INSERT(json, path, val)` | Вставить значение, если путь не существует | 10.2+ |
| `JSON_REPLACE(json, path, val)` | Заменить значение, если путь существует | 10.2+ |
| `JSON_REMOVE(json, path)` | Удалить значение по пути | 10.2+ |
| `JSON_APPEND(json, path, val)` | Добавить значение к массиву/объекту | 10.2+ |
| `JSON_CONTAINS(json, val)` | Проверить наличие значения | 10.2+ |
| `JSON_CONTAINS_PATH(json, path)` | Проверить наличие пути | 10.2+ |
| `JSON_KEYS(json)` | Ключи JSON-объекта | 10.2+ |
| `JSON_LENGTH(json)` | Длина массива/объекта | 10.2+ |
| `JSON_TYPE(json)` | Тип значения | 10.2+ |
| `JSON_VALID(json)` | Проверка валидности | 10.2+ |
| `JSON_PRETTY(json)` | Форматированный вывод | 10.2+ |
| `JSON_DEPTH(json)` | Глубина JSON | 10.2+ |
| `JSON_QUOTE(str)` | Экранировать строку как JSON | 10.2+ |
| `JSON_SEARCH(json, return, str)` | Найти путь к строке | 10.2+ |
| `JSON_OVERLAPS(json1, json2)` | Проверить пересечение JSON-документов | 10.2+ |
| `JSON_MERGE(...)` | Объединить JSON-документы (устаревшая) | 10.2+ |
| `JSON_MERGE_PATCH(json1, json2)` | MERGE с заменой значений (RFC 7396) | 10.2+ |
| `JSON_MERGE_PRESERVE(json1, json2)` | MERGE с сохранением массивов | 10.2+ |
| `JSON_COMPACT(json)` | Удалить лишние пробелы из JSON | 10.2+ |
| `JSON_LOOSE(json)` | Сериализовать JSON без пробелов | 10.2+ |
| `JSON_ARRAYAGG(expr)` | Агрегировать значения в JSON-массив | 10.2+ |
| `JSON_OBJECTAGG(key, val)` | Агрегировать пары в JSON-объект | 10.2+ |
| `JSON_QUERY(json, path)` | Извлечь объект/массив по пути | 10.6+ |
| `JSON_VALUE(json, path)` | Извлечь скаляр по пути | 10.6+ |
| `JSON_EXISTS(json, path)` | Проверить существование пути | 10.6+ |
| `JSON_SCHEMA_VALID(schema, json)` | Проверить JSON против JSON Schema | 10.2+ |
| `JSON_TABLE(...)` | Преобразовать JSON в таблицу | 10.6+ |

> **Примечание:** `JSON_MERGE()` помечена как устаревшая — используйте `JSON_MERGE_PATCH()` или `JSON_MERGE_PRESERVE()`.

### Пути (path) в JSON

Путь указывается в формате `$.key[0].subkey`. MariaDB поддерживает подмножество JSONPath, близкое к синтаксису MySQL:

*   `$` — корень документа.
*   `.key` — поле объекта.
*   `."key name"` — поле с пробелами или специальными символами (10.2+, рекомендуется для имен с `.` и т.п.).
*   `[n]` — элемент массива по индексу (счёт с нуля).
*   `[-N]` — элемент с конца массива (с 10.9+).
*   `[last-N]` — n-й элемент с конца (с 10.9+).
*   `[M to N]` — диапазон элементов массива (с 10.9+). Возвращает массив, если найдено несколько значений, или `NULL` при невозможном диапазоне (`M > N`).
*   `.*` — все значения объекта.
*   `[*]` — все элементы массива.
*   `**` — рекурсивный wildcard (нерекурсивный поиск по всем уровням). **Важно:** `**` не может быть последним шагом пути — должен следовать за селектором массива или объекта.

**Различие `JSON_EXTRACT` / `JSON_QUERY` / `JSON_VALUE`:**

*   `JSON_EXTRACT(json, path)` возвращает значение как JSON-текст (с кавычками для строк).
*   `JSON_QUERY(json, path)` возвращает объект/массив как JSON-текст; возвращает `NULL`, если значение скалярное.
*   `JSON_VALUE(json, path)` возвращает скалярное значение как SQL-тип; возвращает `NULL`, если значение объект/массив.

## Практические сценарии

### 1. Создание и извлечение JSON

```sql
-- Создание JSON
SELECT JSON_OBJECT('id', 1, 'name', 'Alice');
-- → {"id": 1, "name": "Alice"}

SELECT JSON_ARRAY(1, 'two', 3.0);
-- → [1, "two", 3.0]

-- Извлечение значения
SELECT JSON_EXTRACT('{"name": "Alice", "age": 30}', '$.name');
-- → "Alice"

-- Извлечение без кавычек
SELECT JSON_UNQUOTE(JSON_EXTRACT('{"name": "Alice"}', '$.name'));
-- → Alice

-- Проверка валидности
SELECT JSON_VALID('{"a": 1}');  -- → 1
SELECT JSON_VALID('{"a": 1');   -- → 0

-- Экранирование строки для JSON
SELECT JSON_QUOTE('O''Brien');
-- → "O\"Brien"
```

### 2. Хранение и запрос JSON в таблице

```sql
CREATE TABLE user_profiles (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  profile LONGTEXT CHECK (JSON_VALID(profile)),
  INDEX idx_user (user_id)
);

-- Вставка
INSERT INTO user_profiles (user_id, profile) VALUES
  (1, '{"city": "Moscow", "lang": "ru", "prefs": {"theme": "dark"}}');

-- Извлечение поля
SELECT user_id,
  JSON_UNQUOTE(JSON_EXTRACT(profile, '$.city')) AS city
FROM user_profiles;

-- Фильтрация по значению JSON
SELECT * FROM user_profiles
  WHERE JSON_EXTRACT(profile, '$.city') = '"Moscow"';

-- Модификация
UPDATE user_profiles
  SET profile = JSON_SET(profile, '$.lang', 'en')
  WHERE user_id = 1;
```

### 3. Индексация значений внутри JSON (Generated Column)

Поскольку JSON хранится как текст, прямой индекс по пути JSON невозможен. Для ускорения фильтрации создайте вычисляемый (generated) столбец и проиндексируйте его:

```sql
ALTER TABLE user_profiles
  ADD COLUMN city VARCHAR(100)
    AS (JSON_UNQUOTE(JSON_EXTRACT(profile, '$.city'))) STORED,
  ADD INDEX idx_city (city);

-- Теперь фильтрация использует индекс
EXPLAIN SELECT * FROM user_profiles WHERE city = 'Moscow';
-- → type = ref, key = idx_city
```

### 4. JSON_TABLE (MariaDB 10.6+)

Преобразование JSON-массива в таблицу:

```sql
-- Развернуть JSON-массив в строки
SELECT * FROM JSON_TABLE(
  '[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]',
  '$[*]' COLUMNS (
    id INT PATH '$.id',
    name VARCHAR(50) PATH '$.name'
  )
) AS jt;

-- JSON_TABLE с FORMAT JSON (MariaDB 13.1.1+) — извлечение вложенного объекта
SELECT * FROM JSON_TABLE(
  '{"items": [{"id": 1, "tags": ["a", "b"]}]}',
  '$.items[*]' COLUMNS (
    item JSON FORMAT JSON PATH '$'
  )
) AS jt;

-- JSON_TABLE с NESTED PATH — вложенные массивы
SELECT * FROM JSON_TABLE(
  '{"orders": [{"id": 1, "items": [{"sku": "A1"}, {"sku": "B2"}]}]}',
  '$.orders[*]' COLUMNS (
    order_id INT PATH '$.id',
    NESTED PATH '$.items[*]' COLUMNS (
      sku VARCHAR(50) PATH '$.sku'
    )
  )
) AS jt;
```

### 5. SQL/JSON standard функции (MariaDB 10.6+)

`JSON_QUERY`, `JSON_VALUE` и `JSON_EXISTS` являются частью SQL/JSON standard и позволяют более точно извлекать данные из JSON по сравнению с `JSON_EXTRACT`:

```sql
SET @json = '{"customer": {"name": "Alice", "contacts": [{"type": "email", "value": "alice@test.com"}, {"type": "phone", "value": "555-0100"}]}, "paid": 1500}';

-- JSON_VALUE — извлечь скаляр (строка без кавычек)
SELECT JSON_VALUE(@json, '$.customer.name') AS customer_name;
-- → Alice

SELECT JSON_VALUE(@json, '$.paid') AS paid;
-- → 1500

-- JSON_QUERY — извлечь объект или массив (с кавычками-обёрткой JSON)
SELECT JSON_QUERY(@json, '$.customer') AS customer_obj;
-- → {"name": "Alice", "contacts": [...]}

SELECT JSON_QUERY(@json, '$.customer.contacts[0]') AS first_contact;
-- → {"type": "email", "value": "alice@test.com"}

-- JSON_VALUE возвращает NULL для объектов/массивов
SELECT JSON_VALUE(@json, '$.customer');
-- → NULL

-- JSON_QUERY возвращает NULL для скаляров
SELECT JSON_QUERY(@json, '$.paid');
-- → NULL

-- JSON_EXISTS — проверка существования пути
SELECT JSON_EXISTS(@json, '$.customer.name') AS has_name;  -- → 1
SELECT JSON_EXISTS(@json, '$.customer.phone') AS has_phone; -- → 0

-- Комбинация JSON_EXISTS и JSON_VALUE в WHERE
SELECT JSON_VALUE(profile, '$.city') AS city
FROM user_profiles
WHERE JSON_EXISTS(profile, '$.prefs.theme');
```

### 6. Агрегация в JSON (MariaDB 10.2+)

```sql
-- JSON_ARRAYAGG — собрать значения в массив
SELECT user_id,
  JSON_ARRAYAGG(JSON_EXTRACT(profile, CONCAT('$.prefs.', key))) AS prefs
FROM user_profiles
  CROSS JOIN JSON_TABLE(
    '["theme", "lang"]', '$[*]' COLUMNS (key VARCHAR(50) PATH '$')
  ) AS jt
GROUP BY user_id;

-- JSON_OBJECTAGG — собрать пары ключ-значение в объект
SELECT user_id,
  JSON_OBJECTAGG(
    JSON_UNQUOTE(JSON_EXTRACT(profile, '$.lang')),
    JSON_EXTRACT(profile, '$.city')
  ) AS data
FROM user_profiles
GROUP BY user_id;
```

### 7. Поиск и модификация JSON

```sql
-- JSON_SEARCH — найти путь к строке
SET @json = '[{"name": "Alice"}, {"name": "Bob"}]';
SELECT JSON_SEARCH(@json, 'one', 'Alice');
-- → "$[0].name"

SELECT JSON_SEARCH(@json, 'all', 'name');
-- → ["$[0].name", "$[1].name"]

-- Слияние объектов (MERGE_PATCH — заменяет значения)
SELECT JSON_MERGE_PATCH('{"a": 1, "b": 2}', '{"b": 3, "c": 4}');
-- → {"a": 1, "b": 3, "c": 4}

-- Добавление элемента в массив
SELECT JSON_ARRAY_APPEND('[1, 2]', '$', 3);
-- → [1, 2, 3]

-- Добавление ключа в объект
SELECT JSON_SET('{}', '$.id', 1, '$.status', 'new');
-- → {"id": 1, "status": "new"}
```

### 8. JSON-операторы (MariaDB 13.1+)

```sql
-- Оператор -> (эквивалент JSON_EXTRACT, возвращает JSON)
SELECT '{"name": "Alice"}' -> '$.name';
-- → "Alice"

-- Оператор ->> (эквивалент JSON_UNQUOTE(JSON_EXTRACT(...)))
SELECT '{"name": "Alice"}' ->> '$.name';
-- → Alice

-- Цепочка операторов
SELECT profile ->> '$.prefs.theme' AS theme
FROM user_profiles
WHERE JSON_EXISTS(profile, '$.prefs.theme');
```

**Важно:** операторы `->` и `->>` доступны только в MariaDB 13.1+. В 10.x–12.x используйте `JSON_EXTRACT` / `JSON_UNQUOTE`.

### 9. JSON Schema Validation (MariaDB 10.2+)

```sql
-- Проверка JSON против схемы
SET @schema = '{"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}';
SET @doc1 = '{"age": 30}';
SET @doc2 = '{"name": "Alice"}';

SELECT JSON_SCHEMA_VALID(@schema, @doc1); -- → 1 (валиден)
SELECT JSON_SCHEMA_VALID(@schema, @doc2); -- → 0 (age обязательно)
```

## Устранение неполадок (Troubleshooting)

### `Invalid JSON text` при вставке

*   **Причина:** вставляемое значение не является валидным JSON.
*   **Диагностика:** `SELECT JSON_VALID('...')` — проверьте значение.
*   **Решение:** исправьте формат JSON; убедитесь, что `CHECK`-ограничение `JSON_VALID` присутствует.

### Фильтрация по JSON медленная

*   **Причина:** `JSON_EXTRACT` в `WHERE` не использует индекс — выполняется полный скан таблицы с разбором JSON.
*   **Решение:** создайте Generated Column с индексом (см. сценарий 3).

### `JSON_TABLE` недоступна

*   **Причина:** версия MariaDB < 10.6.
*   **Решение:** обновитесь до 10.6+ или используйте `JSON_EXTRACT` с обработкой в приложении.

### `JSON_QUERY` возвращает `NULL` для скаляра

*   **Причина:** `JSON_QUERY` возвращает объект/массив; для скаляров возвращает `NULL`.
*   **Решение:** используйте `JSON_VALUE` для скаляров, `JSON_EXTRACT` или `->` для общего случая.

### `CHECK (JSON_VALID(...))` сильно замедляет вставку

*   **Причина:** каждая вставка требует полного парсинга JSON.
*   **Диагностика:** `EXPLAIN ANALYZE INSERT ...` — проверьте время на `CHECK`.
*   **Решение:** для write-heavy таблиц рассмотрите валидацию на уровне приложения; либо используйте очередь с пакетной валидацией. Опцию `CHECK` можно отключить только через `ALTER TABLE ... DROP CONSTRAINT`.

### `JSON_MERGE` работает не так, как ожидалось

*   **Причина:** `JSON_MERGE()` имеет неоднозначное поведение объединения массивов. В MariaDB 10.2+ предпочтительнее `JSON_MERGE_PATCH` (RFC 7396, заменяет значения) или `JSON_MERGE_PRESERVE` (сохраняет массивы).
*   **Решение:** используйте явную функцию вместо устаревшего `JSON_MERGE()`.

### `JSON_SEARCH` не находит строку

*   **Причина:** `JSON_SEARCH` ищет только строковые значения (не числа, не булевы). Путь должен быть корректным JSONPath.
*   **Решение:** используйте `JSON_EXTRACT`/`JSON_VALUE` для нестроковых значений; убедитесь, что `escape_char` указан при спецсимволах.

## Лучшие практики (Best Practices)

1. **Всегда добавляйте `CHECK (JSON_VALID(...))`** к JSON-столбцам — MariaDB не проверяет валидность автоматически (в отличие от MySQL).
2. **Индексируйте часто фильтруемые JSON-поля** через Generated Column.
3. **Не храните большие JSON-документы** (> 1MB) — текстовое хранение неэффективно; нормализуйте данные в реляционные таблицы.
4. **Используйте `JSON_TABLE`** (10.6+) для разворачывания массивов вместо обработки в приложении.
5. **Учитывайте версию:** операторы `->`/`->>` — только 13.1+; `JSON_TABLE` — только 10.6+; `FORMAT JSON` в `JSON_TABLE` — только 13.1.1+.
6. **Используйте `JSON_QUERY`/`JSON_VALUE`/`JSON_EXISTS`** вместо `JSON_EXTRACT` для нового кода — они точнее выражают намерение и соответствуют SQL/JSON standard.
7. **Не используйте устаревший `JSON_MERGE()`** — заменяйте на `JSON_MERGE_PATCH` или `JSON_MERGE_PRESERVE`.
8. **Ограничивайте `max_allowed_packet`** для JSON-операций: великие документы могут превышать лимит при отправке клиентом.

### Очистка и откат

*   **Удаление JSON-столбца:** `ALTER TABLE t DROP COLUMN json_col` — удаляет столбец и все связанные generated индексы.
*   **Удаление Generated Column с индексом:** сначала `DROP INDEX`, затем `DROP COLUMN` (или `ALTER TABLE ... DROP COLUMN` удаляет оба).
*   **Откат модификаций JSON:** если нужно отменить изменения в JSON-документе, используйте `JSON_REMOVE` для удаления добавленных ключей, либо храните предыдущее значение в отдельном столбце before update.

## Особенности и ограничения (Edge Cases)

*   **Текстовое хранение + парсинг на каждую операцию:** MariaDB парсит JSON при каждом `JSON_EXTRACT`/`JSON_SET`, что медленнее бинарного хранилища MySQL. Для read-heavy нагрузки выгоднее denormalizовать нужные поля в отдельные колонки.
*   **Порядок ключей в объекте:** порядок ключей в JSON-объекте может меняться при модификации (`JSON_SET`, `JSON_MERGE`). Не полагайтесь на порядок ключей при сравненнии.
*   **`JSON_EXTRACT` для объектов/массивов:** возвращает значение как JSON-текст (с кавычками для строк), что отличается от `JSON_VALUE` (скаляр без кавычек) и `JSON_QUERY` (объект/массив).
*   **Отрицательные индексы массива:** доступны только с MariaDB 10.9+. До 10.9 используйте `JSON_LENGTH(json, '$.arr') - 1` для доступа к последнему элементу.
*   **`JSON_SEARCH` ищет только строки:** числа, булевы значения и `NULL` не находятся функцией `JSON_SEARCH`.
*   **`JSON_MERGE` устарела:** в новых версиях может быть удалена. Используйте `JSON_MERGE_PATCH` или `JSON_MERGE_PRESERVE`.
*   **Размер JSON через `group_concat_max_len`:** агрегатные функции `JSON_ARRAYAGG`/`JSON_OBJECTAGG` ограничены системной переменной `group_concat_max_len`. Увеличивайте её для больших документов.
*   **`JSON_COMPACT`** удаляет только лишние пробелы из JSON — значения `null` и структура данных не изменяются.

## Дополнительная информация

### См. также

* **[Движки хранения](storage_engines.md)** — ColumnStore для аналитики на JSON-подобных данных.
* **[Индексы](indexing.md)** — Generated Column и индексация.
* **[MySQL: JSON](../MySQL/sql-8x-features.md)** — отличия MySQL (нативный бинарный JSON).
* **[Обзор MariaDB](overview.md)** — общая таблица отличий схем данных (JSON как LONGTEXT vs бинарный JSON в MySQL).

### Внешние ресурсы

* [MariaDB JSON Functions](https://mariadb.com/docs/server/reference/sql-functions/special-functions/json-functions/)
* [MariaDB JSON_TABLE](https://mariadb.com/docs/server/reference/sql-functions/special-functions/json-functions/json_table/)
* [MariaDB JSON Arrow Operators](https://mariadb.com/docs/server/reference/sql-functions/special-functions/json-functions/json-arrow-operators/)
* [MariaDB JSONPath Expressions](https://mariadb.com/docs/server/reference/sql-functions/special-functions/json-functions/jsonpath-expressions/)
* [MariaDB JSON_QUERY / JSON_VALUE / JSON_EXISTS](https://mariadb.com/docs/server/reference/sql-functions/special-functions/json-functions/json_query/)
* [MariaDB JSON Overview](https://mariadb.com/docs/server/reference/sql-functions/special-functions/json-functions/)
* [MDEV-17399: JSON_TABLE](https://jira.mariadb.org/browse/MDEV-17399)
* [MDEV-13594: JSON Arrow Operators](https://jira.mariadb.org/browse/MDEV-13594)
