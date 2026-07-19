# pgvector: PostgreSQL как векторная база данных

## Определения

*   **pgvector:** Расширение для PostgreSQL с открытым исходным кодом, добавляющее поддержку высокоразмерных векторов и поиска по сходству (ANN). Позволяет хранить эмбеддинги рядом с реляционными данными.
*   **Векторный поиск:** Метод поиска, идентифицирующий похожие элементы на основе их математических характеристик. Векторы представляют собой числовые представления данных (текст, фото, аудио).
*   **Эмбеддинг (Embedding):** Числовое представление объекта, полученное через ML-модели.
    *   `all-MiniLM-L6-v2`: 384 измерения.
    *   `OpenAI text-embedding-3-small`: 1536 измерений.
*   **Гибридный поиск:** Сочетание полнотекстового поиска (точные термины) и векторного (семантика).
*   **RAG (Retrieval-Augmented Generation):** Паттерн, где база данных предоставляет релевантный контекст для LLM (например, GPT-4) для генерации точного ответа.

## Основные концепции

### Типы данных и оптимизация

| Тип | Описание | Применение |
| :--- | :--- | :--- |
| `vector` | 32-битные float | Стандарт для большинства моделей. |
| `halfvec` | 16-битные float | Экономит 50% RAM. Идеально для моделей OpenAI (с версии 0.5.0). |
| `bit` | Двоичные векторы | Максимальное сжатие для бинарных эмбеддингов. |
| `sparsevec` | Разреженные векторы | Для векторов с большим количеством нулей (до 1000 ненулевых элементов). |

### Метрики сравнения (Операторы)

*   **Евклидово расстояние (L2) (`<->`):** Расстояние между точками концов векторов. Аналогия: физическое расстояние между объектами.
*   **Косинусное сходство (`<=>`):** Измеряет угол между векторами. Показывает семантическую близость независимо от размера текста. Значения от 0 до 1.
*   **Внутреннее произведение (`<#>`):** Проекция одного вектора на другой. Используется, если векторы нормализованы.
*   **Расстояние Хэмминга (`<~>`):** Количество несовпадающих бит (только для типа `bit`).

### Векторные индексы

1.  **HNSW (Hierarchical Navigable Small World):**
    *   Создает многослойный граф для быстрого поиска.
    *   **Плюсы:** Высокая точность, очень быстрый поиск, поддерживает `INSERT/UPDATE`.
    *   **Минусы:** Долгое построение, требует много оперативной памяти.
2.  **IVFFlat (Inverted File):**
    *   Разделяет векторы на кластеры (списки).
    *   **Плюсы:** Быстрое построение, минимальное потребление памяти.
    *   **Минусы:** Требует пересоздания при значительном изменении объема данных, ниже точность.

## Практические сценарии

### Установка и развертывание

**Вариант 1: Из пакетов (Debian/Ubuntu)**
```bash
apt-get install postgresql-16-pgvector
```

**Вариант 2: Сборка из исходников (максимальная производительность)**
```bash
git clone --branch v0.7.0 https://github.com/pgvector/pgvector.git
cd pgvector
make
make install # требуется sudo
```

**Активация в базе данных:**
```sql
CREATE EXTENSION vector;
```

### Базовые операции и поиск

Создание таблицы:
```sql
CREATE TABLE items (
    id bigserial PRIMARY KEY,
    content text,
    embedding vector(1536) -- для OpenAI small
);
```

Поиск N наиболее похожих по косинусному сходству:
```sql
SELECT title, 1 - (embedding <=> query_vec) AS similarity
FROM items, (SELECT embedding AS query_vec FROM items WHERE id = 1) q
ORDER BY embedding <=> query_vec
LIMIT 5;
```

Фильтрация по порогу сходства:
```sql
SELECT * FROM items WHERE 1 - (embedding <=> '[0.1, 0.2, ...]') > 0.8;
```

### Гибридный поиск: Вектор + Полнотекст

**Метод 1: Взвешенное среднее (Alpha)**
```sql
SELECT title,
       (0.7 * (1 - (embedding <=> query_vec))) +
       (0.3 * ts_rank(to_tsvector('russian', content), to_tsquery('поиск'))) AS score
FROM items, (SELECT embedding AS query_vec FROM items WHERE id = 1) q
WHERE to_tsvector('russian', content) @@ to_tsquery('поиск')
ORDER BY score DESC LIMIT 10;
```

**Метод 2: Reciprocal Rank Fusion (RRF)**
*Более надежный метод, не требующий настройки весов.*
```sql
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> '[0.1, ...]') as rank
    FROM items LIMIT 100
),
keyword AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(to_tsvector(content), query) DESC) as rank
    FROM items, to_tsquery('запрос') query
    WHERE to_tsvector(content) @@ query LIMIT 100
)
SELECT id, (1.0 / (60 + COALESCE(s.rank, 101))) + (1.0 / (60 + COALESCE(k.rank, 101))) AS rrf_score
FROM semantic s FULL JOIN keyword k USING (id)
ORDER BY rrf_score DESC LIMIT 10;
```

### Настройка индексов

**Создание HNSW (рекомендуется):**
```sql
CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
-- m: связей на узел (больше = точнее, но больше памяти)
-- ef_construction: размер очереди при построении (больше = точнее, но медленнее индекс)
```

**Создание IVFFlat:**
```sql
CREATE INDEX ON items USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
-- lists: число кластеров (рекомендуется sqrt(rows) или rows/1000)

-- Настройка точности поиска:
SET ivfflat.probes = 10; -- Проверять 10 ближайших кластеров (по умолчанию 1)
```

### Мониторинг и обслуживание

**Проверка использования индекса:**
```sql
EXPLAIN ANALYZE
SELECT * FROM items ORDER BY embedding <=> '[0.1, ...]' LIMIT 5;
```

**Размер индекса:**
```sql
SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes WHERE relname = 'items';
```

## Дополнительная информация

### См. также
*   **[Полнотекстовый поиск в PostgreSQL](./Concepts/full_text_search.md)**
*   **[Обзор PostgreSQL](./overview.md)**
*   **[Официальный репозиторий pgvector](https://github.com/pgvector/pgvector)**
