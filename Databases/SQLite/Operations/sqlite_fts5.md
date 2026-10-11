# Полнотекстовый поиск FTS5 в SQLite

**Актуально для:** SQLite 3.9+ (FTS5); требуется сборка с `ENABLE_FTS5` (включён в официальных сборках)

## Определения

*   **FTS5** — виртуальный модуль полнотекстового поиска: инвертированный индекс по токенам текстовых колонок.
*   **MATCH** — оператор полнотекстового поиска по FTS5-таблице.
*   **Tokenizer** — разбиватель текста на токены: `unicode61` (по умолчанию, Unicode), `porter` (стемминг, английский), `trigram` (поиск по подстрокам).
*   **rank** — скрытая колонка FTS5-таблицы с релевантностью (по умолчанию — значение `bm25()`).
*   **bm25()** — функция ранжирования Okapi BM25; меньшее (более отрицательное) значение — лучшее совпадение.
*   **Content mode** — режим хранения: обычная FTS5-таблица, external content (данные в обычной таблице), contentless (только индекс).

## Базовые концепции

### Как устроен FTS5

FTS5 хранит инвертированный индекс: токен → список документов (rowid), содержащих его. Поиск по токену — O(log n) вместо полного сканирования с `LIKE '%x%'`. Сегменты индекса периодически мержатся; команда `optimize` принудительно сливает сегменты.

### Tokenizers

*   `unicode61` — по умолчанию; разбивает по границам Unicode, опционально складывает диакритику (`remove_diacritics 1`).
*   `porter` — стемминг по алгоритму Портера (только английский язык).
*   `trigram` — индексирует триграммы; поддерживает поиск по подстрокам и операторы `LIKE`/`GLOB` в FTS5-запросах.

### Content modes

*   Обычная: данные хранятся в самой FTS5-таблице.
*   External content (`content='table'`): данные остаются в обычной таблице, FTS5 — только индекс; синхронизация через триггеры.
*   Contentless (`content=''`): только индекс, без текста; возвращает только rowid.

## Практические сценарии

### 1. Создание и поиск

```sql
CREATE VIRTUAL TABLE docs USING fts5(title, body);

INSERT INTO docs(title, body) VALUES
  ('SQLite', 'Small, fast, reliable database'),
  ('PostgreSQL', 'Advanced open source database');

-- Три эквивалентных способа поиска
SELECT * FROM docs WHERE docs MATCH 'database';
SELECT * FROM docs WHERE docs = 'database';
SELECT * FROM docs('database');
```

### 2. Синтаксис запросов

```sql
-- Фраза
SELECT * FROM docs WHERE docs MATCH '"small database"';

-- Префикс
SELECT * FROM docs WHERE docs MATCH 'data*';

-- Булевы операторы
SELECT * FROM docs WHERE docs MATCH 'sqlite AND database';
SELECT * FROM docs WHERE docs MATCH 'sqlite OR postgres';
SELECT * FROM docs WHERE docs MATCH 'sqlite NOT postgres';

-- Близость (NEAR): термины в пределах 5 токенов друг от друга
SELECT * FROM docs WHERE docs MATCH 'NEAR(sqlite database, 5)';

-- Фильтр по колонке
SELECT * FROM docs WHERE docs MATCH 'title:sqlite';
```

### 3. Ранжирование

```sql
-- Сортировка по релевантности (ORDER BY rank быстрее, чем ORDER BY bm25())
SELECT title, bm25(docs) AS score
FROM docs WHERE docs MATCH 'database'
ORDER BY rank;

-- Веса колонок: совпадения в title важнее body
SELECT title, bm25(docs, 10.0, 5.0) AS score
FROM docs WHERE docs MATCH 'database'
ORDER BY score;
```

### 4. Подсветка и сниппеты

```sql
-- Подсветка совпадений в колонке 0 (title)
SELECT highlight(docs, 0, '<b>', '</b>') FROM docs WHERE docs MATCH 'database';

-- Фрагмент текста вокруг совпадения (колонка 1, до 10 токенов)
SELECT snippet(docs, 1, '<b>', '</b>', '...', 10) AS preview
FROM docs WHERE docs MATCH 'database';
```

### 5. External content — поиск по существующей таблице

```sql
CREATE TABLE articles(id INTEGER PRIMARY KEY, title TEXT, body TEXT);

CREATE VIRTUAL TABLE articles_fts USING fts5(
  title, body,
  content='articles',
  content_rowid='id'
);

-- Триггеры синхронизации
CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
-- (аналогично UPDATE и DELETE)

-- Первичное заполнение индекса
INSERT INTO articles_fts(articles_fts) VALUES('rebuild');
```

### 6. Обслуживание

```sql
-- Слияние сегментов индекса (ускоряет поиск, уменьшает файл)
INSERT INTO docs(docs) VALUES('optimize');

-- Проверка целостности индекса
INSERT INTO docs(docs) VALUES('integrity-check');

-- Полная перестройка
INSERT INTO docs(docs) VALUES('rebuild');
```

## Операции и команды

| Задача | Команда |
| :--- | :--- |
| Создать FTS5-таблицу | `CREATE VIRTUAL TABLE t USING fts5(col1, col2);` |
| Поиск | `WHERE t MATCH 'query'` / `WHERE t = 'query'` / `t('query')` |
| Ранжирование | `ORDER BY rank` / `bm25(t[, weights...])` |
| Подсветка | `highlight(t, col, '<b>', '</b>')` |
| Сниппет | `snippet(t, col, '<b>', '</b>', '...', N)` |
| Слияние сегментов | `INSERT INTO t(t) VALUES('optimize');` |
| Проверка индекса | `INSERT INTO t(t) VALUES('integrity-check');` |
| Перестройка | `INSERT INTO t(t) VALUES('rebuild');` |

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `no such module: fts5` | Сборка без `ENABLE_FTS5` | Проверить `PRAGMA compile_options;`; использовать официальную сборку |
| Поиск не находит русские слова | `porter` tokenizer работает только для английского | Использовать `unicode61` (без стемминга) или кастомный tokenizer |
| `MATCH` возвращает неожиданные строки | Спецсимволы запроса (`"`, `*`, `NEAR`) | Экранировать кавычки; проверять синтаксис запроса |
| Индекс растёт после DELETE | Сегменты не сжаты | `INSERT INTO t(t) VALUES('optimize');` |
| External content не синхронизируется | Нет триггеров | Добавить триггеры INSERT/UPDATE/DELETE; `rebuild` |

## Рекомендации SRE

*   FTS5 заменяет `LIKE '%x%'` в логах, событиях, документации на edge-устройствах — без внешнего поискового движка.
*   Для поиска по подстрокам (не по словам) используйте `tokenize='trigram'`.
*   Для русского языка: `unicode61` без стемминга; стемминг — только через кастомный tokenizer.
*   External content + триггеры — стандартный паттерн для поиска по большим таблицам без дублирования данных.

## Дополнительная информация

### См. также

*   [Производительность запросов и индексы](./sqlite_query_performance.md) — когда FTS5 эффективнее B-tree индекса
*   [SQL-фичи SQLite](./sqlite_sql_features.md) — JSON и другие встроенные функции
*   [Официальная документация: FTS5](https://sqlite.org/fts5.html)
