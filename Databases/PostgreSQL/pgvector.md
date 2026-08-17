# pgvector: PostgreSQL как векторная база данных

## Определения

**pgvector** — расширение с открытым исходным кодом для PostgreSQL, добавляющее поддержку высокоразмерных векторов и поиска по сходству (Approximate Nearest Neighbor, ANN). Оно превращает стандартную реляционную БД в мощное хранилище для AI-приложений, позволяя хранить эмбеддинги рядом с метаданными и бизнес-логикой.

*   **Векторный поиск:** Метод поиска, идентифицирующий похожие элементы на основе их математических характеристик (близости в многомерном пространстве). Векторы представляют собой числовые представления данных (текст, фото, аудио).
*   **Эмбеддинг (Embedding):** Числовое представление объекта, полученное через ML-модели.
    *   *Пример:* `all-MiniLM-L6-v2` (384 измерения), `OpenAI text-embedding-3-small` (1536 измерений).
*   **Сценарии использования:** MVP, AI-стартапы, RAG-системы (Retrieval-Augmented Generation), рекомендательные движки и поиск по изображениям.
*   **Итеративное сканирование (Iterative Index Scan):** Ключевая функция **pgvector 0.8.0**, позволяющая индексу продолжать поиск, пока не будет найдено достаточное количество строк, соответствующих фильтрам `WHERE`. Это решает проблему «пустых результатов» при строгой фильтрации.
*   **Гибридный поиск:** Сочетание полнотекстового поиска (точные термины) и векторного поиска (семантический смысл).
*   **RAG (Retrieval-Augmented Generation):** Паттерн, где база данных предоставляет релевантный контекст для LLM (например, GPT-4 или Claude 3.5) для генерации точного ответа на основе частных данных.

## Базовые концепции

### Типы данных и оптимизация хранения

| Тип | Описание | Особенности и применение |
| :--- | :--- | :--- |
| `vector` | 32-битные float | Стандарт для большинства моделей. Максимум 16,000 измерений. Высокая точность, высокое потребление RAM. |
| `halfvec` | 16-битные float | **Квантование (v0.5.0):** Экономит 50% RAM и диска. Идеально для моделей OpenAI и HuggingFace. |
| `bit` | Двоичные векторы | Максимальное сжатие (1 бит на измерение) для бинарных эмбеддингов. |
| `sparsevec` | Разреженные векторы | Для векторов с большим количеством нулей (до 100,000 измерений, до 1000 ненулевых). |

### Метрики сравнения (Операторы)

*   **Косинусное сходство (`<=>`):** Измеряет угол между векторами. Показывает семантическую близость независимо от размера текста. Значения от 0 (идентичны) до 2 (противоположны). *Самый частый выбор для RAG.*
*   **Евклидово расстояние (L2) (`<->`):** Расстояние между точками концов векторов. Аналогия: физическое расстояние. *Подходит для поиска по изображениям и аудио.*
*   **Внутреннее произведение (`<#>`):** Проекция одного вектора на другой. Используется, если векторы нормализованы (длина = 1). *Самый быстрый оператор для нормализованных данных.*
*   **Расстояние Хэмминга (`<~>`):** Количество несовпадающих бит (только для типа `bit`).
*   **Jaccard Distance (`<%>`):** Для сравнения множеств через двоичные векторы.

### Векторные индексы: HNSW vs IVFFlat

1.  **HNSW (Hierarchical Navigable Small World):**
    *   **Принцип:** Создает многослойный граф для быстрого перемещения между узлами.
    *   **Плюсы:** Очень высокая точность (Recall), экстремально быстрый поиск, поддерживает `INSERT/UPDATE` без деградации и перестроения.
    *   **Минусы:** Долгое построение, требует много оперативной памяти (Shared Buffers). Индекс должен целиком помещаться в RAM для высокой производительности.
2.  **IVFFlat (Inverted File):**
    *   **Принцип:** Разделяет векторы на кластеры (списки). При поиске проверяются только ближайшие центроиды.
    *   **Плюсы:** Быстрое построение, минимальное потребление памяти.
    *   **Минусы:** Требует пересоздания (`REINDEX`) при значительном изменении объема данных, ниже точность при росте базы (требуется тюнинг `probes`).

## Практические сценарии

### Установка и развертывание

**Вариант 1: Из пакетов (Debian/Ubuntu)**
Для PostgreSQL 18 (актуально для 2026 года):
```bash
apt-get update && apt-get install postgresql-18-pgvector
```

**Вариант 2: Сборка из исходников (максимальная оптимизация под архитектуру CPU)**
```bash
git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```
*Примечание: сборка с флагами оптимизации (например, AVX-512) может ускорить расчет расстояний на 20-30%.*

**Активация в базе данных:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Базовые операции и поиск

**Создание таблицы:**
```sql
CREATE TABLE knowledge_base (
    id bigserial PRIMARY KEY,
    category text,
    content text,
    embedding vector(1536) -- размерность для OpenAI text-embedding-3-small
);
```

**Поиск N наиболее похожих по косинусному сходству:**
```sql
SELECT content, 1 - (embedding <=> query_vec) AS similarity
FROM knowledge_base, (SELECT embedding AS query_vec FROM knowledge_base WHERE id = 1) q
ORDER BY embedding <=> query_vec
LIMIT 5;
```

**Фильтрация по порогу сходства:**
```sql
SELECT * FROM knowledge_base WHERE 1 - (embedding <=> '[0.1, 0.2, ...]') > 0.8;
```

**Поиск с фильтрацией (Iterative Scan, v0.8.0+):**
Индексы теперь поддерживают итеративное сканирование, что критично для комбинированных запросов.
```sql
SELECT content FROM knowledge_base 
WHERE category = 'sre_docs' 
ORDER BY embedding <=> '[0.1, 0.2, ...]' 
LIMIT 5;

-- Тюнинг итеративного поиска
SET hnsw.iterative_scan = relaxed_order;
```

### Гибридный поиск

**Метод 1: Взвешенное среднее (Alpha)**
```sql
SELECT content,
       (0.7 * (1 - (embedding <=> query_vec))) +
       (0.3 * ts_rank(to_tsvector('russian', content), to_tsquery('индексы'))) AS score
FROM knowledge_base, (SELECT embedding AS query_vec FROM knowledge_base WHERE id = 1) q
WHERE to_tsvector('russian', content) @@ to_tsquery('индексы')
ORDER BY score DESC LIMIT 10;
```

**Метод 2: Reciprocal Rank Fusion (RRF)**
*Рекомендуемый метод, объединяющий ранги без ручного подбора весов.*
```sql
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> '[0.1, ...]') as rank
    FROM knowledge_base LIMIT 100
),
keyword AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(to_tsvector('russian', content), to_tsquery('запрос')) DESC) as rank
    FROM knowledge_base
    WHERE to_tsvector('russian', content) @@ to_tsquery('запрос') LIMIT 100
)
SELECT id, (1.0 / (60 + COALESCE(s.rank, 101))) + (1.0 / (60 + COALESCE(k.rank, 101))) AS rrf_score
FROM semantic s FULL JOIN keyword k USING (id)
ORDER BY rrf_score DESC LIMIT 10;
```

### Настройка и тюнинг индексов

**Создание HNSW (рекомендуется для Production):**
```sql
-- PostgreSQL 18: AIO ускоряет фазу построения и поиска при высокой конкуренции за IO
CREATE INDEX ON knowledge_base USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 128);
-- m: число связей на узел (16-64). Больше = выше точность и потребление RAM.
-- ef_construction: размер очереди при построении. Больше = выше точность, медленнее индекс.
```

**Создание IVFFlat (для экономии ресурсов):**
```sql
CREATE INDEX ON knowledge_base USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
-- lists: число кластеров. Рекомендация: sqrt(rows) или rows/1000.

-- Настройка точности поиска:
SET ivfflat.probes = 10; -- Проверять 10 ближайших кластеров (по умолчанию 1).
```

### Мониторинг и обслуживание

**Проверка использования индекса:**
```sql
EXPLAIN ANALYZE
SELECT * FROM knowledge_base ORDER BY embedding <=> '[0.1, ...]' LIMIT 5;
-- В выводе ищите "Index Scan using ... on knowledge_base"
```

**Размер индекса:**
```sql
SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes WHERE relname = 'knowledge_base';
```

**Параллельная сборка (PG 15+):**
```sql
SET maintenance_work_mem = '2GB';
SET max_parallel_maintenance_workers = 4; -- Ускоряет CREATE INDEX
```

### Решение проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Низкая точность (Recall)** | Слишком малые `ef_search` или `probes`. | Увеличьте `SET hnsw.ef_search = 100;` или `SET ivfflat.probes = 10;`. |
| **Медленный поиск** | Индекс не помещается в RAM. | Проверьте размер индекса и `shared_buffers`. Используйте `halfvec` или `bit`. |
| **OOM при создании индекса** | Нехватка `maintenance_work_mem`. | Увеличьте параметр или уменьшите `max_parallel_maintenance_workers`. |
| **Пустые результаты с WHERE** | Особенности ANN в старых версиях. | Обновите pgvector до >= 0.8.0 для поддержки Iterative Scan. |

## Дополнительная информация

### Рекомендации (Best Practices)
1.  **Нормализация:** Если векторы нормализованы (длина=1), используйте `<#>` (внутреннее произведение) — это значительно быстрее расчёта косинусного сходства.
2.  **RAM:** HNSW — это In-memory индекс по своей сути. Если он «вымывается» на диск, производительность падает в десятки раз.
3.  **Квантование:** Переход на `halfvec` (float16) — это «бесплатный» способ сэкономить 50% ресурсов с потерей точности менее 1%.
4.  **Batch Load:** При вставке миллионов строк сначала загрузите данные, а затем создавайте индекс.

### См. также
*   **[Полнотекстовый поиск (FTS) в PostgreSQL](./Concepts/full_text_search.md)**
*   **[Обзор PostgreSQL](./overview.md)**
*   **[Официальный репозиторий pgvector](https://github.com/pgvector/pgvector)**
*   **[Архитектура PostgreSQL](./Concepts/architecture.md)** — влияние WAL и Checkpoint на вставку векторов.
