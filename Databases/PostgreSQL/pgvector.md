# pgvector: векторный поиск в PostgreSQL

**Актуально для:** pgvector 0.8.7 (релиз 2026-10-01) / PostgreSQL 13–18

pgvector — расширение с открытым исходным кодом для PostgreSQL, добавляющее поддержку векторов фиксированной размерности и поиска по сходству: точный (exact nearest neighbor) и приблизительный (Approximate Nearest Neighbor, ANN). Векторы хранятся в обычных таблицах вместе с метаданными, участвуют в транзакциях ACID и записываются в WAL — расширение работает поверх стандартного PostgreSQL, репликация и point-in-time recovery поддерживаются штатно, отдельная СУБД не требуется.

## Определения

*   **Векторный поиск:** поиск элементов, близких в многомерном пространстве, по расстоянию между векторами.
*   **Эмбеддинг:** числовое представление объекта (текста, изображения, аудио) в виде вектора фиксированной размерности. Типичные размерности: 384, 768, 1536 — зависят от модели (пример иллюстративный).
*   **ANN (Approximate Nearest Neighbor):** индексный поиск, который жертвует частью точности (recall) ради скорости. Без индекса pgvector выполняет точный поиск с полным recall.
*   **HNSW / IVFFlat:** два типа ANN-индексов pgvector — графовый (Hierarchical Navigable Small World) и кластерный (Inverted File).
*   **Итеративное сканирование (Iterative Index Scan, 0.8.0):** индекс продолжает сканирование, пока не найдено достаточно строк, соответствующих фильтрам `WHERE`. Решает проблему пустых результатов при фильтрации.
*   **Гибридный поиск:** сочетание полнотекстового поиска (точные термины) и векторного поиска (сходство) в одном запросе.
*   **Квантование:** снижение точности хранения или индекса (`halfvec`, бинарное) для уменьшения рабочего набора и размера индексов.
*   **Сценарии использования:** поиск по сходству, рекомендательные системы, дедупликация, семантический поиск, поиск по изображениям и аудио.

## Базовые концепции

### Типы данных

| Тип | Хранение (байт) | Макс. размерность: хранение / индекс | Применение |
| :--- | :--- | :--- | :--- |
| `vector` | `4 * dims + 8` | 16 000 / 2 000 | Стандарт для большинства моделей; максимальная точность. |
| `halfvec` (0.7.0) | `2 * dims + 8` | 16 000 / 4 000 | Половинная точность (float16): вдвое меньше RAM и диска при минимальной потере точности. |
| `bit` | `dims / 8 + 8` | — / 64 000 | Бинарные векторы: максимальное сжатие (1 бит на измерение). |
| `sparsevec` (0.7.0) | `8 * nonzero + 16` | 16 000 / 1 000 ненулевых | Разреженные векторы: много нулевых элементов. Формат: `'{1:1,3:2,5:3}/5'`, индексы с 1. |

Все элементы должны быть конечными (нет `NaN`, `Infinity`, `-Infinity`). Для моделей с разной размерностью используйте `vector` без ограничения (`embedding vector`) и индексируйте выражением по `model_id` — см. пограничные случаи.

### Операторы расстояния

| Оператор | Расстояние | Примечания |
| :--- | :--- | :--- |
| `<->` | L2 (евклидово) | Аналогия: физическое расстояние между точками. Подходит для изображений и аудио. |
| `<#>` | скалярное произведение | Возвращает **отрицательное** значение (Postgres поддерживает только ASC-сканы): `(embedding <#> '...') * -1`. Самый быстрый оператор для нормализованных векторов (длина = 1). |
| `<=>` | косинусное | Семантическая близость независимо от длины вектора. Расстояние 0–2; сходство = `1 - расстояние`. Самый частый выбор. |
| `<+>` | L1 (taxicab) | Добавлен в 0.7.0. |
| `<~>` | Хэмминга | Только для `bit`: число несовпадающих бит. |
| `<%>` | Жаккара | Только для `bit`: сравнение множеств. |

### Индексы: HNSW vs IVFFlat

1.  **HNSW (Hierarchical Navigable Small World):**
    *   **Принцип:** многослойный граф для быстрого перемещения между узлами.
    *   **Плюсы:** лучший компромисс скорости и recall, индекс создаётся без данных (нет фазы обучения), поддерживает `INSERT/UPDATE` без перестроения.
    *   **Минусы:** долгое построение, больше памяти при построении и хранении. Параметры: `m` — макс. связей на слой (по умолчанию 16), `ef_construction` — размер динамического списка кандидатов при построении (по умолчанию 64).
    *   **Важно:** индексу **не** обязательно целиком помещаться в RAM (как и другим индексам, производительность выше, когда он в кэше); `VACUUM` для HNSW может идти долго — см. обслуживание.
2.  **IVFFlat (Inverted File):**
    *   **Принцип:** векторы делятся на кластеры (списки); при поиске проверяются только ближайшие к запросу центроиды.
    *   **Плюсы:** быстрое построение, меньше памяти.
    *   **Минусы:** ниже recall при прочих равных; индекс, созданный на малом объёме данных для заданного числа `lists`, даёт мало результатов — пересоздавайте после наполнения таблицы. Параметр `lists` — число кластеров.

### Стратегия фильтрации (`WHERE` + ANN)

Фильтрация в ANN-запросе применяется **после** сканирования индекса: при совпадении 10% строк и `hnsw.ef_search = 40` в среднем найдётся только ~4 строки. Порядок решений:

1.  **Индекс на колонке фильтра** (B-tree, GiST, GIN) — даёт быстрый **точный** поиск при низкой селективности фильтра. Для нескольких колонок — составной индекс.
2.  **Итеративное сканирование** (0.8.0+) — при умеренной селективности; автоматически сканирует больше индекса.
3.  **Partial index** — когда фильтр по нескольким различным значениям: `CREATE INDEX ... WHERE (category_id = 123)`.
4.  **Партиционирование** — когда фильтр по множеству значений (список/хэш).

## Предварительные требования

*   PostgreSQL 13+ (поддержка PostgreSQL 12 прекращена в pgvector 0.8.0).
*   Для сборки из исходников: заголовки сервера (`postgresql-server-dev-18` в Debian/Ubuntu, замените `18` на вашу версию) и `pg_config`.
*   Для пакетной установки в Debian/Ubuntu: подключённый [PostgreSQL APT Repository (PGDG)](https://wiki.postgresql.org/wiki/Apt) — пакеты `postgresql-*-pgvector` поставляются оттуда, а не из базовых репозиториев дистрибутива.

## Практические сценарии

### Установка

**Пакеты (Debian/Ubuntu, PGDG):**
```bash
sudo apt install postgresql-18-pgvector
# → установлен пакет расширения; замените 18 на вашу версию PostgreSQL
```

**Пакеты (RHEL/CentOS/Fedora, PostgreSQL Yum Repository):**
```bash
sudo dnf install pgvector_18
# → установлен пакет расширения; замените 18 на вашу версию
```

**Сборка из исходников (максимальная оптимизация под CPU):**
```bash
git clone --branch v0.8.7 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
# → расширение собрано и установлено
```
*   Если на машине несколько PostgreSQL: `export PG_CONFIG=/path/to/pg_config`, затем `sudo --preserve-env=PG_CONFIG make install`.
*   С 0.7.0 расстояния используют CPU dispatching на Linux x86-64. По умолчанию сборка идёт с `-march=native`: бинарник может дать `Illegal instruction` на другой машине — для переносимости собирайте с `make OPTFLAGS=""`.
*   Docker-развёртывание (образы `pgvector/pgvector:pg18-trixie`, `--shm-size` для параллельных построек) — см. [Развёртывание в Docker](./Operations/docker_deployment.md).

**Активация в базе данных (один раз в каждой БД):**
```sql
CREATE EXTENSION IF NOT EXISTS vector;
-- → расширение vector установлено
```

### Работа с данными

**Создание таблицы:**
```sql
CREATE TABLE knowledge_base (
    id bigserial PRIMARY KEY,
    category text,
    content text,
    embedding vector(1536) -- размерность зависит от модели; пример иллюстративный
);
-- → таблица создана
```

**Вставка и массовая загрузка:**
```sql
INSERT INTO knowledge_base (category, content, embedding)
VALUES ('sre_docs', 'документ', '[0.1, 0.2, ...]');

-- Массовая загрузка (быстрее поочерёдных INSERT)
COPY knowledge_base (category, content, embedding) FROM STDIN WITH (FORMAT BINARY);

-- Upsert
INSERT INTO knowledge_base (id, embedding) VALUES (1, '[1,2,3]')
ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding;
```

### Поиск

**N ближайших по косинусному сходству:**
```sql
SELECT content, 1 - (embedding <=> query_vec) AS similarity
FROM knowledge_base, (SELECT embedding AS query_vec FROM knowledge_base WHERE id = 1) q
ORDER BY embedding <=> query_vec
LIMIT 5;
-- → 5 строк с полем similarity (0..1), отсортированных по убыванию сходства
```

**Строки в пределах расстояния:**
```sql
SELECT * FROM knowledge_base WHERE embedding <-> '[0.1, 0.2, ...]' < 0.5;
-- → строки, чьё L2-расстояние до эталона меньше 0.5
```

**Фильтрация по порогу сходства:**
```sql
SELECT * FROM knowledge_base WHERE 1 - (embedding <=> '[0.1, 0.2, ...]') > 0.8;
-- → строки с косинусным сходством выше 0.8 (точный поиск без ORDER BY/LIMIT)
```

### Гибридный поиск (Reciprocal Rank Fusion)

Рекомендуемый метод объединения рангов полнотекстового и векторного поиска без ручного подбора весов:
```sql
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> '[0.1, ...]') AS rank
    FROM knowledge_base LIMIT 100
),
keyword AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(to_tsvector('russian', content), to_tsquery('запрос')) DESC) AS rank
    FROM knowledge_base
    WHERE to_tsvector('russian', content) @@ to_tsquery('запрос') LIMIT 100
)
SELECT id, (1.0 / (60 + COALESCE(s.rank, 101))) + (1.0 / (60 + COALESCE(k.rank, 101))) AS rrf_score
FROM semantic s FULL JOIN keyword k USING (id)
ORDER BY rrf_score DESC LIMIT 10;
-- → до 10 строк с объединённым скором RRF
```

### Создание и тюнинг индексов

**HNSW (рекомендуется для Production):**
```sql
-- В production создавайте конкурентно, чтобы не блокировать записи:
CREATE INDEX CONCURRENTLY ON knowledge_base USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
-- m: макс. связей на слой (по умолчанию 16); больше = точнее, но RAM и время построения выше.
-- ef_construction: список кандидатов при построении (по умолчанию 64); больше = точнее, медленнее построение.
-- Начинайте с дефолтов; меняйте только при низком recall.
```

**IVFFlat (для экономии ресурсов):**
```sql
CREATE INDEX ON knowledge_base USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 1000);
-- lists: число кластеров. Ориентир: rows/1000 (до 1M строк) или sqrt(rows) (свыше 1M).
-- Создавайте на наполненной таблице: при малом объёме данных список кластеров избыточен.

SET ivfflat.probes = 10;
-- probes: число проверяемых кластеров (по умолчанию 1). Ориентир: sqrt(lists).
-- probes = lists даёт точный поиск — planner перестанет использовать индекс.
```

**Настройки поиска (настройки сессии, `SET LOCAL` — на один запрос):**
```sql
BEGIN;
SET LOCAL hnsw.ef_search = 100;   -- список кандидатов при поиске (по умолчанию 40); больше = точнее, медленнее
SET LOCAL ivfflat.probes = 10;
SELECT ...;
COMMIT;
```

**Параллельное построение (ускоряет `CREATE INDEX`):**
```sql
SET maintenance_work_mem = '8GB';        -- граф HNSW строится значительно быстрее, если помещается целиком
SET max_parallel_maintenance_workers = 7; -- по умолчанию 2; для больших значений поднимите max_parallel_workers (по умолчанию 8)
```
*   Не ставьте `maintenance_work_mem` выше доступной RAM сервера. При превышении вы увидите: `NOTICE: hnsw graph no longer fits into maintenance_work_mem after 100000 tuples` — построение заметно замедлится.
*   В Docker `--shm-size` должен быть не меньше `maintenance_work_mem` для параллельных HNSW-строек.

**Прогресс построения (PostgreSQL 12+):**
```sql
-- HNSW (фазы: initializing, loading tuples):
SELECT phase, round(100.0 * blocks_done / nullif(blocks_total, 0), 1) AS pct FROM pg_stat_progress_create_index;
-- IVFFlat (фазы: initializing, performing k-means, assigning tuples, loading tuples):
SELECT phase, round(100.0 * tuples_done / nullif(tuples_total, 0), 1) AS pct FROM pg_stat_progress_create_index;
-- → текущая фаза и процент (столбец % заполняется только на фазе loading tuples)
```

### Итеративное сканирование (0.8.0+)

Индекс автоматически сканирует больше данных, пока не найдёт достаточно строк (или не достигнет лимита). Порядок результатов: `strict_order` — строго по расстоянию; `relaxed_order` — чуть лучше recall, порядок может нарушаться (для строгого порядка оберните в материализованный CTE и добавьте `+ 0` — требуется для PostgreSQL 17+):
```sql
SET hnsw.iterative_scan = relaxed_order;  -- или ivfflat.iterative_scan = relaxed_order

WITH relaxed_results AS MATERIALIZED (
    SELECT id, embedding <=> '[1,2,3]' AS distance FROM knowledge_base WHERE category = 'sre_docs' ORDER BY distance LIMIT 5
) SELECT * FROM relaxed_results ORDER BY distance + 0;
```

**Лимиты итеративного сканирования:**
```sql
SET hnsw.max_scan_tuples = 20000;      -- макс. посещённых кортежей (по умолчанию 20000; приближённо, не влияет на начальный скан)
SET hnsw.scan_mem_multiplier = 2;      -- макс. память как кратное work_mem (по умолчанию 1); увеличьте, если рост max_scan_tuples не помог
SET ivfflat.max_probes = 100;          -- макс. проб (если меньше ivfflat.probes, используется probes)
```

### Квантование и масштабирование

**Полуточная индексация (индекс меньше, чем таблица):**
```sql
CREATE INDEX ON knowledge_base USING hnsw ((embedding::halfvec(1536)) halfvec_l2_ops);
SELECT * FROM knowledge_base ORDER BY embedding::halfvec(1536) <-> '[1,2,3]' LIMIT 5;
```

**Бинарное квантование + re-ranking (для больших масштабов):**
```sql
CREATE INDEX ON knowledge_base USING hnsw ((binary_quantize(embedding)::bit(1536)) bit_hamming_ops);

-- Поиск по квантованному индексу, re-rank по исходным векторам для recall:
SELECT * FROM (
    SELECT * FROM knowledge_base
    ORDER BY binary_quantize(embedding)::bit(1536) <~> binary_quantize('[1,-2,3]') LIMIT 20
) ORDER BY embedding <=> '[1,-2,3]' LIMIT 5;
```

**Масштабирование:** вертикально (RAM/CPU/диск + тюнинг параметров); горизонтально — реплики для чтения или шардирование (Citus, PgDog и др.).

### Мониторинг

```sql
-- Размер индекса:
SELECT pg_size_pretty(pg_relation_size('knowledge_base_embedding_hnsw_idx'));

-- Использование индекса и план запроса (ищите "Index Scan using ..."):
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM knowledge_base ORDER BY embedding <=> '[0.1, ...]' LIMIT 5;

-- Мониторинг recall: сравнение ANN-поиска с точным (индекс выключен):
BEGIN;
SET LOCAL enable_indexscan = off;
SELECT ...;
COMMIT;
```
Латентность и частоту ANN-запросов отслеживайте через `pg_stat_statements` (см. [Наблюдаемость](./Operations/observability.md)).

### Обслуживание: VACUUM и REINDEX

`VACUUM` для HNSW может выполняться долго; ускорьте его предварительным переиндексированием:
```sql
REINDEX INDEX CONCURRENTLY knowledge_base_embedding_hnsw_idx;
VACUUM knowledge_base;
```

### Мультитенантность

Общий ANN-индекс на несколько арендаторов снижает recall и скорость для остальных. Для изоляции используйте партиционирование по списку или отдельные таблицы:
```sql
CREATE TABLE items (customer_id int, embedding vector(3)) PARTITION BY LIST(customer_id);
```

### Обновление расширения

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
-- → текущая версия в базе, например 0.8.6
ALTER EXTENSION vector UPDATE;
-- → расширение обновлено до установленной в системе версии
```
Установите новую версию тем же способом, что и исходная (пакет/исходники), затем выполните `ALTER EXTENSION` в каждой базе. Версии 0.8.2–0.8.7 исправляют ошибки построения и vacuum-индексов (в т.ч. buffer overflow при параллельной HNSW-строе и повреждение индекса при vacuum) — обновление до 0.8.7 рекомендуется.

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Низкий recall** | Малые `hnsw.ef_search` (40 по умолчанию) / `ivfflat.probes` (1). | `SET hnsw.ef_search = 100;` или `SET ivfflat.probes = 10;`; включите итеративное сканирование. |
| **Мало результатов после добавления HNSW** | Лимит `ef_search`; dead tuples; фильтры; `NULL`-векторы не индексируются. | Рост `ef_search`, итеративное сканирование, `VACUUM`; проверьте векторы на `NULL`. |
| **Мало результатов после добавления IVFFlat** | Индекс создан на малом объёме данных для числа `lists`. | `DROP INDEX` и пересоздание после наполнения таблицы. |
| **Медленный поиск** | Индекс не помещается в кэш (`shared_buffers`/OS cache). | Сравните `pg_relation_size` индекса с RAM; используйте `halfvec`/квантование. |
| **OOM при создании индекса** | `maintenance_work_mem` выше доступной RAM. | Уменьшите параметр или `max_parallel_maintenance_workers`. |
| **Индекс не используется** | `ORDER BY` должен быть оператором расстояния ASC + `LIMIT`, а не выражением (`ORDER BY 1 - (embedding <=> ...) DESC` — не использует индекс); маленькая таблица — seq scan дешевле. | Перепишите `ORDER BY`; для отладки: `SET LOCAL enable_seqscan = off`. |
| **Параллельное сканирование не выбирается** | Planner не учитывает out-of-line хранение TOAST в оценке стоимости. | `SET LOCAL min_parallel_table_scan_size = 1; SET LOCAL parallel_setup_cost = 1;` или `ALTER TABLE ... ALTER COLUMN embedding SET STORAGE PLAIN;`. |
| **VACUUM HNSW долгий** | Специфика graph-индекса. | `REINDEX INDEX CONCURRENTLY` перед `VACUUM`. |

## Пограничные случаи

*   **`NULL`-векторы не индексируются**; нулевые векторы — не индексируются для косинусного расстояния.
*   **Лимит таблицы:** 32 ТБ для не партиционированной таблицы; партиционированная — тысячи партиций такого размера.
*   **Разные размерности в одной колонке:** `embedding vector` без `n`, индексы — выражением и partial: `CREATE INDEX ON embeddings USING hnsw ((embedding::vector(3)) vector_l2_ops) WHERE (model_id = 123)`.
*   **`probes = lists`** для IVFFlat превращает поиск в точный — planner не будет использовать индекс.
*   **`-march=native`:** собранный бинарник может дать `Illegal instruction` на другой машине — для переносимости `make OPTFLAGS=""`.
*   **Docker:** `--shm-size` должен быть не меньше `maintenance_work_mem` для параллельных HNSW-строек.

## Лучшие практики

1.  **Нормализация:** для нормализованных векторов (длина = 1) используйте `<#>` — быстрее косинусного расстояния; нормализуйте через `l2_normalize()` (0.7.0).
2.  **Размер рабочего набора:** `halfvec` вместо `vector` для таблиц, half-precision/бинарное квантование для индексов (с re-ranking для recall).
3.  **Загрузка:** `COPY ... WITH (FORMAT BINARY)` для массовой вставки; индексы создавайте **после** загрузки данных, в production — `CREATE INDEX CONCURRENTLY`.
4.  **Фильтры:** сначала индекс на колонке фильтра (B-tree и др.), потом ANN-индекс; partial index для нескольких значений, партиционирование для множества.
5.  **Параметры HNSW:** начинайте с дефолтов (`m = 16`, `ef_construction = 64`); меняйте только при низком recall.
6.  **Recall:** регулярно сверяйте ANN-результаты с точным поиском (`SET LOCAL enable_indexscan = off`).
7.  **Очистка:** удаление расширения — `DROP EXTENSION vector;` (в каждой базе, где он установлен).

## Дополнительная информация

*   **[Полнотекстовый поиск (FTS) в PostgreSQL](./Concepts/full_text_search.md)** — вторая половина гибридного поиска
*   **[Обзор PostgreSQL](./overview.md)**
*   **[Архитектура PostgreSQL](./Concepts/architecture.md)** — влияние WAL и Checkpoint на вставку векторов
*   **[Развёртывание в Docker](./Operations/docker_deployment.md)** — образы `pgvector/pgvector`
*   **[Память агентов](./Operations/agent-memory.md)** — критерии выноса векторного поиска в отдельный инстанс
*   **[Официальный репозиторий pgvector](https://github.com/pgvector/pgvector)** и [CHANGELOG](https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md)
