# SQL-фичи SQLite: UPSERT, CTE, оконные функции, JSON

**Актуально для:** SQLite 3.35+ (каждая фича указана с версией появления)

## Определения

*   **UPSERT** — конструкция `INSERT ... ON CONFLICT`, выполняющая обновление или игнорирование при нарушении уникального ограничения (SQLite 3.24.0+).
*   **RETURNING** — клауза, возвращающая значения вставленных/обновлённых/удалённых строк без отдельного SELECT (SQLite 3.35.0+).
*   **CTE (Common Table Expression)** — именованный временный набор данных в предложении `WITH`; рекурсивный CTE позволяет обходить иерархии (SQLite 3.8.3+).
*   **Window function (оконная функция)** — агрегат, вычисляемый по окну строк без свёртки строк в одну (SQLite 3.25.0+).
*   **JSON1** — встроенные функции для JSON-документов (`json_extract`, `json_each` и др.); встроены в ядро с SQLite 3.38.0+.
*   **INSERT OR REPLACE** — устаревший аналог UPSERT: при конфликте строка удаляется и вставляется заново.

## Базовые концепции

### Почему это важно для DevOps/SRE

Эти фичи закрывают типовые задачи эксплуатации: идемпотентная запись конфигурации (UPSERT), аудит изменений (RETURNING), иерархии хостов/сервисов (recursive CTE), скользящие агрегаты метрик (оконные функции), гибкие схемы событий (JSON).

### Версии фич

| Фича | Версия | Год |
| :--- | :--- | :--- |
| CTE и recursive CTE | 3.8.3 | 2014 |
| UPSERT (`ON CONFLICT`) | 3.24.0 | 2018 |
| Оконные функции | 3.25.0 | 2018 |
| RETURNING, DROP COLUMN | 3.35.0 | 2021 |
| JSON встроен в ядро, операторы `->` / `->>` | 3.38.0 | 2022 |
| `unixepoch()` | 3.38.0 | 2022 |

## Практические сценарии

### 1. UPSERT — идемпотентная запись

```sql
INSERT INTO config(key, value, updated_at)
VALUES ('timeout', 30, CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE
  SET value = excluded.value,
      updated_at = CURRENT_TIMESTAMP;

-- Игнорировать конфликт
INSERT INTO config(key, value) VALUES ('timeout', 30)
ON CONFLICT(key) DO NOTHING;
```

`excluded` — псевдотаблица со значениями, которые пытались вставить. Требуется уникальный индекс или ограничение на целевой колонке (`key`).

### 2. RETURNING — аудит без второго запроса

```sql
INSERT INTO events(type, payload) VALUES ('deploy', '{"v":"1.2.3"}')
RETURNING id, created_at;
-- → 42|2026-10-03 12:00:00

UPDATE config SET value = 60 WHERE key = 'timeout' RETURNING key, value;
DELETE FROM sessions WHERE expired = 1 RETURNING user_id;
```

### 3. Рекурсивный CTE — иерархии и генерация рядов

```sql
-- Иерархия сервисов (parent_id)
WITH RECURSIVE tree(id, name, depth) AS (
  SELECT id, name, 0 FROM services WHERE parent_id IS NULL
  UNION ALL
  SELECT s.id, s.name, tree.depth + 1
  FROM services s JOIN tree ON s.parent_id = tree.id
)
SELECT * FROM tree ORDER BY depth, name;

-- Генерация временных рядов (заполнение пропусков)
WITH RECURSIVE ts(t) AS (
  SELECT 1700000000
  UNION ALL
  SELECT t + 60 FROM ts WHERE t < 1700003600
)
SELECT t FROM ts;
```

### 4. Оконные функции — скользящие агрегаты

```sql
-- Скользящее среднее за 5 последних точек
SELECT ts, value,
  avg(value) OVER (ORDER BY ts ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS ma5
FROM metrics WHERE host = 'web-01';

-- Нумерация и дедупликация (последнее событие на хост)
SELECT * FROM (
  SELECT *, row_number() OVER (PARTITION BY host ORDER BY ts DESC) AS rn
  FROM events
) WHERE rn = 1;
```

Оконные функции нельзя использовать в WHERE — только в SELECT и ORDER BY (для фильтрации оборачивайте в подзапрос).

### 5. JSON — гибкие схемы

```sql
-- Извлечение значений
SELECT json_extract(doc, '$.user.name') FROM events;
SELECT doc->>'$.user.name' FROM events;          -- оператор, 3.38+
SELECT json_type(doc, '$.items') FROM events;    -- object/array/text/...

-- Разворачивание массива в строки
SELECT value FROM events, json_each(doc, '$.items');

-- Проверка и сборка
SELECT json_valid('{"a":1}');
SELECT json_group_array(name) FROM services;
SELECT json_object('host', host, 'ts', ts) FROM events;
```

### 6. Дата и время

```sql
SELECT strftime('%Y-%m-%d %H:%M:%S', 'now');
SELECT unixepoch();                                        -- 3.38+
SELECT datetime(1700000000, 'unixepoch', 'localtime');
SELECT julianday('now') - julianday('2026-01-01');         -- разница в днях
```

### 7. INSERT OR REPLACE — устаревший upsert

```sql
INSERT OR REPLACE INTO config(key, value) VALUES ('timeout', 30);
```

Внимание: `REPLACE` удаляет старую строку и вставляет новую — срабатывают `ON DELETE` триггеры и каскады FK, колонки, не указанные в INSERT, обнуляются. Для нового кода используйте `ON CONFLICT`.

## Операции и команды

| Задача | Конструкция |
| :--- | :--- |
| Идемпотентная вставка/обновление | `INSERT ... ON CONFLICT (col) DO UPDATE SET ...` |
| Игнорировать конфликт | `ON CONFLICT (col) DO NOTHING` |
| Вернуть изменённые строки | `... RETURNING col1, col2` |
| Иерархия / ряды | `WITH RECURSIVE name(col) AS (...)` |
| Скользящий агрегат | `avg(x) OVER (ORDER BY ts ROWS BETWEEN N PRECEDING AND CURRENT ROW)` |
| Дедупликация | `row_number() OVER (PARTITION BY ... ORDER BY ... DESC)` |
| JSON-поле | `doc->>'$.path'`, `json_extract(doc, '$.path')` |
| Массив в строки | `json_each(doc, '$.path')` |

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `near "RETURNING": syntax error` | SQLite < 3.35 | Обновить SQLite или делать отдельный SELECT |
| `no such function: json_extract` | Сборка без JSON (до 3.38 или `SQLITE_OMIT_JSON`) | Обновить SQLite; проверить `PRAGMA compile_options` |
| UPSERT не обновляет строку | Нет уникального индекса на conflict target | Создать UNIQUE-индекс на колонку |
| `misuse of window function` | Оконная функция в WHERE | Перенести в подзапрос |
| `ON CONFLICT` не срабатывает с `DO UPDATE` | Конфликт по колонке без уникального ограничения | Указать колонку с UNIQUE/PK |

## Дополнительная информация

### См. также

*   [Производительность запросов и индексы](./sqlite_query_performance.md) — планировщик и статистика
*   [Обзор SQLite](../sqlite_overview.md) — архитектура
*   [Официальная документация: UPSERT](https://sqlite.org/lang_UPSERT.html)
*   [Официальная документация: Window functions](https://sqlite.org/windowfunctions.html)
*   [Официальная документация: JSON](https://sqlite.org/json1.html)
