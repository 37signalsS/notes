# pgvector: PostgreSQL как векторная база данных

## Определения

**pgvector** — открытое расширение для PostgreSQL, добавляющее поддержку высокоразмерных векторов (embeddings) и векторного поиска непосредственно в реляционной СУБД. Позволяет хранить, обрабатывать и анализировать векторные данные без необходимости использования специализированных векторных СУБД.

**Векторный поиск** — метод поиска информации, который идентифицирует похожие элементы в наборе данных на основе их математических характеристик (векторов/embeddings). Векторы представляют собой высокоразмерные числовые представления исходных данных (текст, изображения, аудио).

**Embedding (эмбеддинг)** — числовое векторное представление данных, полученное с помощью моделей глубокого обучения. Размерность вектора зависит от используемой модели:

| Модель | Размерность вектора |
| :--- | :--- |
| all-MiniLM-L6-v2 | 384 |
| OpenAI embedding-3-small | 1536 |

**Полнотекстовый поиск** — встроенная возможность PostgreSQL для поиска документов на естественном языке с использованием типов данных `tsvector` и `tsquery`. Поддерживает сортировку по релевантности и лингвистическую обработку.

**Гибридный поиск** — комбинированный подход, сочетающий полнотекстовый поиск (для точных терминов, чисел, имён собственных) и векторный поиск (для семантической схожести). Стратегия: сначала фильтрация по ключевым словам, затем ранжирование по векторам.

**RAG (Retrieval-Augmented Generation)** — паттерн, при котором пользовательский запрос кодируется в вектор, PostgreSQL возвращает N релевантных фрагментов, которые вместе с запросом передаются в LLM для генерации ответа на основе контекста.

---

## Основные концепции

### Метрики сравнения векторов

pgvector поддерживает три основные метрики:

| Метрика | Оператор | Описание |
| :--- | :--- | :--- |
| Евклидово расстояние (L2) | `<->` | Измеряет расстояние между точками, в которых заканчиваются векторы. Аналогия: как далеко экран находится от лица. |
| Косинусное сходство | `<=>` | Измеряет угол между векторами. Показывает, насколько нужно «повернуться», чтобы совпасть с целевым вектором. Значения: 0–1. |
| Внутреннее произведение (Inner Product) | `<#>` | Проекция одного вектора на другой. Измеряет и расстояние, и угол. Зависит от длины меньшего вектора. |

Дополнительно поддерживается манхэттенское расстояние (L1).

### Тип данных vector

Расширение pgvector добавляет тип данных `vector` с указанием размерности:

```sql
-- Вектор размерности 384 (all-MiniLM-L6-v2)
embedding vector(384)

-- Вектор размерности 1536 (OpenAI embedding-3-small)
embedding vector(1536)
```

### Установка и развёртывание

Установка pgvector из исходников на Ubuntu:

```bash
# Клонирование репозитория
git clone https://github.com/pgvector/pgvector.git
cd pgvector

# Сборка и установка
make
sudo make install

# Установка зависимостей для демо-скриптов
# Активация виртуального окружения Python
source venv/bin/activate
```

Активация расширения в конкретной базе данных (extension действует только в рамках одной БД):

```sql
CREATE EXTENSION vector;

-- Проверка установленных расширений
SELECT * FROM pg_extension WHERE extname = 'vector';
```

---

## Практические сценарии

### Когда использовать pgvector

- **Небольшие и средние объёмы данных** — до сотен тысяч записей
- **Проект уже на PostgreSQL** — нет необходимости в дополнительной СУБД
- **Прототипирование RAG-систем** — быстрое развёртывание без сложной инфраструктуры
- **Совмещение OLTP и векторного поиска** — транзакционные данные + embeddings в одной БД
- **Локальные проекты** — можно развернуть даже на локальной машине или Android-устройстве

### Когда рассматривать специализированные векторные СУБД

- **Большие объёмы данных** — миллионы и более векторов
- **Высокие требования к производительности** — когда pgvector не справляется
- **Специфичные алгоритмы индексирования** — требуются продвинутые ANN-алгоритмы

Рекомендация: сначала попробовать pgvector; если производительности не хватает — переходить на специализированные решения.

### Векторный поиск: базовые запросы

Поиск N наиболее похожих статей по косинусному сходству:

```sql
SELECT a.title, a.body,
       1 - (a.embedding <=> query.embedding) AS similarity
FROM articles a
CROSS JOIN (SELECT embedding FROM articles WHERE id = 1) query
ORDER BY a.embedding <=> query.embedding
LIMIT 3;
```

Фильтрация по порогу косинусного сходства:

```sql
SELECT title, body
FROM articles
WHERE 1 - (embedding <=> (SELECT embedding FROM articles WHERE id = 1)) > 0.4;
```

Поиск по евклидову расстоянию:

```sql
SELECT title, body,
       embedding <-> (SELECT embedding FROM articles WHERE id = 1) AS distance
FROM articles
ORDER BY distance
LIMIT 5;
```

### Гибридный поиск: векторный + полнотекстовый

Полнотекстовый поиск встроен в PostgreSQL по умолчанию:

```sql
-- Полнотекстовый поиск
SELECT title, body
FROM articles
WHERE to_tsvector('russian', body) @@ to_tsquery('russian', 'индекс & поиск');
```

Гибридный запрос с весами (альфа-параметр):

```sql
WITH vector_search AS (
    SELECT id, title, body,
           1 - (embedding <=> query_vec) AS vector_score
    FROM articles
    CROSS JOIN (SELECT embedding AS query_vec FROM articles WHERE id = 1) q
),
fulltext_search AS (
    SELECT id, title, body,
           ts_rank(to_tsvector('russian', body), query) AS ft_score
    FROM articles,
         to_tsquery('russian', 'индекс & поиск') query
    WHERE to_tsvector('russian', body) @@ query
),
combined AS (
    SELECT COALESCE(v.id, f.id) AS id,
           COALESCE(v.title, f.title) AS title,
           COALESCE(v.vector_score, 0) * 0.7 + COALESCE(f.ft_score, 0) * 0.3 AS hybrid_score
    FROM vector_search v
    FULL JOIN fulltext_search f ON v.id = f.id
)
SELECT id, title, hybrid_score
FROM combined
ORDER BY hybrid_score DESC
LIMIT 5;
```

Гибридный поиск с обязательным полнотекстовым условием (сначала фильтрация по ключевым словам, затем ранжирование по векторам — эффективно на больших датасетах):

```sql
WITH user_query AS (
    SELECT embedding AS query_vec FROM articles WHERE id = 1
)
SELECT id, title, body,
       1 - (embedding <=> query_vec) AS relevance
FROM articles, user_query
WHERE to_tsvector('russian', body) @@ to_tsquery('russian', 'индекс')
ORDER BY relevance
LIMIT 5;
```

### RAG-система на PostgreSQL

Базовый RAG-запрос — получение контекста из таблицы FAQ:

```sql
WITH user_query AS (
    SELECT embedding AS query_vec FROM faq WHERE id = 2
),
relevant_docs AS (
    SELECT question, answer, category,
           1 - (embedding <=> query_vec) AS relevance
    FROM faq, user_query
    WHERE 1 - (embedding <=> query_vec) > 0.5
    ORDER BY relevance DESC
    LIMIT 3
)
SELECT string_agg(
    'Вопрос: ' || question || E'\nОтвет: ' || answer || E'\n---\n',
    ''
) AS context
FROM relevant_docs;
```

RAG с фильтрацией по метаданным (добавить условие `WHERE category = '...'`):

```sql
WITH user_query AS (
    SELECT embedding AS query_vec FROM faq WHERE id = 2
)
SELECT question, answer, category,
       1 - (embedding <=> query_vec) AS relevance
FROM faq, user_query
WHERE category = 'indexing'
  AND 1 - (embedding <=> query_vec) > 0.5
ORDER BY relevance DESC;
```

### Векторные индексы

Два основных типа индексов для векторного поиска:

#### IVFFlat (Inverted File with Flat Quantization)

Быстрый, экономичный по памяти, менее точный. Подходит для больших наборов данных.

```sql
-- Создание индекса IVFFlat
CREATE INDEX idx_articles_ivfflat ON articles
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Параметр lists:
-- до 1 млн строк: sqrt(количество строк)
-- более 1 млн строк: количество строк / 1000
```

Управление качеством поиска через `probes` (сколько кластеров просматривать):

```sql
-- По умолчанию: 1 кластер
SET ivfflat.probes = 10;  -- Больше кластеров = точнее, но медленнее
```

#### HNSW (Hierarchical Navigable Small World)

Быстрее при запросах, точнее, но требует больше памяти.

```sql
-- Создание индекса HNSW
CREATE INDEX idx_articles_hnsw ON articles
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- m — число связей каждого узла (по умолчанию 16)
-- ef_construction — размер очереди при построении (по умолчанию 64)
```

Большие значения параметров = точнее, но дольше строить индекс.

**Важно:** два индекса разных типов на одном столбце могут конкурировать. Рекомендуется подбирать один тип и тестировать на конкретных данных.

#### Индекс для полнотекстового поиска

```sql
CREATE INDEX idx_articles_fts ON articles
USING gin (to_tsvector('russian', body));
```

#### Проверка использования индексов

```sql
-- Просмотр индексов таблицы
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'articles';

-- Размер индексов
SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes
WHERE relname = 'articles';

-- План выполнения (для тестирования: SET enable_seqscan = off;)
EXPLAIN ANALYZE
SELECT * FROM articles ORDER BY embedding <=> (SELECT embedding FROM articles WHERE id = 1) LIMIT 5;
```

### Вспомогательная функция для генерации случайных векторов

```sql
CREATE OR REPLACE FUNCTION random_vector(dim int)
RETURNS vector AS $$
SELECT array_to_string(
    ARRAY(SELECT random() FROM generate_series(1, dim)),
    ','
)::vector;
$$ LANGUAGE SQL;
```

---

## Дополнительная информация

### См. также

- **[PostgreSQL: Обзор](./overview.md)** — основной обзор PostgreSQL, OLTP, архитектура
- **[ClickHouse](../clickhouse.md)** — OLAP-система для больших объёмов данных
- **[GitHub: pgvector/pgvector](https://github.com/pgvector/pgvector)** — официальный репозиторий расширения
