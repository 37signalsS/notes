# ClickHouse — Полнотекстовый поиск

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Text index (inverted index)** — тип индекса (GA начиная с 26.2) для полнотекстового поиска: строит инвертированный индекс токенов колонки и поддерживает функции `hasToken`, `hasAllTokens`, `hasAnyTokens`, `hasPhrase`. Начиная с 26.2 не требует специальной настройки. Заменяет устаревшие `tokenbf_v1` и `ngrambf_v1`.

**Токенизатор (Tokenizer)** — алгоритм разбиения текста на токены. Поддерживается 11 токенизаторов: `splitByNonAlpha`, `splitByString`, `splitByRegexp`, `asciiCJK`, `chinese`, `icu`, `japanese`, `ngrams`, `sparseGrams`, `array`, `keyValuePairs`.

**Preprocessor** — выражение, применяемое к тексту **до** токенизации (например, `lowerUTF8` для case-insensitive поиска). Применяется только на пути text-индекса; результаты могут отличаться при `SETTINGS use_skip_indexes = 0`.

**Postprocessor** — выражение, применяемое к токенам **после** токенизации. Нормализует как haystack, так и needle токены, обеспечивая согласованное сравнение.

**hasToken(col, token)** — точное совпадение токена (аналог `=` для слов). Имеет подводные камни с не-`splitByNonAlpha` токенизаторами и preprocessor/postprocessor — предпочтительно использовать `hasAnyTokens`/`hasAllTokens`.

**hasPhrase(col, phrase)** — поиск фразы (последовательности токенов) в тексте. Требует токенизаторы `splitByNonAlpha`, `splitByString`, `splitByRegexp`, `ngrams`, `asciiCJK` или `icu`.

**hasAllTokens(col, needles)** — возвращает 1, если все токены из `needles` присутствуют в `input`. Введена в v25.10.0.

**hasAnyTokens(col, needles)** — возвращает 1, если хотя бы один токен из `needles` присутствует в `input`. Введена в v25.10.0.

**tokenbf_v1 / ngrambf_v1** — устаревшие (deprecated с 26.2) типы индексов на основе Bloom-фильтров. Работают, но не развиваются.

**splitByRegexp** — токенизатор по регулярному выражению. Text-индекс для `LIKE`/`match` с `splitByRegexp` **не применяется**.

**skip index / data skipping index** — обобщённый тип индекса ClickHouse, к которому относится text index.

## Основные концепции

### Как работает text-индекс

1. При вставке текст колонки токенизируется (разбивается на токены выбранным токенизатором).
2. Для каждого токена строится инвертированный индекс: токен → список гранул, содержащих его.
3. При запросе `hasToken`/`hasPhrase`/`hasAllTokens`/`hasAnyTokens` ClickHouse сначала обращается к индексу и читает только гранулы, содержащие нужные токены.

### Архитектура индекса

Text index — это тип skip index, реализованный на уровне MergeTree. Ключевые особенности:

- **Infinite granularity:** text index использует `GRANULARITY 100000000`. Явно указанная `GRANULARITY` в DDL игнорируется — индекс всегда строится на уровне всего data part.
- **Posting lists:** для каждого токена хранится список data parts, содержащих токен. Кодеки: `none` (по умолчанию), `bitpacking`, `pfor`.
- **Dictionary:** словарь токенов с frontcoding-сжатием для уменьшения размера.
- **Cache:** заголовки индекса, posting lists и токены кэшируются в памяти. Метрики в `system.metrics`: `TextIndexHeaderCacheBytes`, `TextIndexPostingsCacheBytes`, `TextIndexTokensCacheBytes`.
- **Direct read optimization:** при включении (`query_plan_direct_read_from_text_index = 1`) ClickHouse читает данные напрямую из posting lists, минуя верификацию строк. Поддерживается для `hasToken`, `hasAllTokens`, `hasAnyTokens`.

### Токенизаторы

| Токенизатор | Разбиение | Применение |
| :--- | :--- | :--- |
| `splitByNonAlpha` | По неалфавитным ASCII-символам (слова) | Поиск по предложениям, логам |
| `splitByString(S)` | По пользовательским разделителям | Кастомные форматы (CSV, JSON с разделителями) |
| `splitByRegexp(pattern)` | По регулярному выражению | Специфические границы токенов |
| `asciiCJK` | По отдельным символам для CJK | Текст с китайскими/японскими/корейскими символами |
| `chinese(granularity)` | Сегментация китайского текста (на основе jieba) | Китайский текст; `coarse_grained` (по умолчанию) или `fine_grained` |
| `icu(locale)` | На основе ICU library | Международизированная токенизация |
| `japanese` | Японская токенизация (на основе MeCab) | Японский текст |
| `ngrams(N)` | Перекрывающиеся N-граммы (1–8) | Поиск подстрок, нечёткий поиск |
| `sparseGrams(min, max, min_cutoff)` | Переменной длины n-граммы | Более компактный вариант; min=3, max=100 по умолчанию |
| `array` | Каждый элемент массива = токен | Поиск по уже токенизированным колонкам |
| `keyValuePairs` | Пары ключ=значение | Поиск в map-колонках |

**Важно:** `LIKE`, `match`, `startsWith`, `endsWith` используют text-индекс **только** с токенизаторами `splitByNonAlpha`, `ngrams`, `sparseGrams`, `asciiCJK`. С `splitByRegexp` индекс для этих функций не применяется.

### Поддерживаемые функции

| Функция | Preprocessor | Postprocessor | Совместимые токенизаторы | Комментарий |
| :--- | :--- | :--- | :--- | :--- |
| `=` | да | да | все | Точное совпадение строки |
| `IN` | да | да | все | Проверка принадлежности к множеству |
| `hasToken` | да | да | все | Рекомендуется заменить на `hasAnyTokens`/`hasAllTokens` |
| `hasAnyTokens(col, str)` | да | да | все | Введена в v25.10.0 |
| `hasAllTokens(col, str)` | да | да | все | Введена в v25.10.0 |
| `hasPhrase` | да | да | `splitByNonAlpha`, `splitByString`, `splitByRegexp`, `ngrams`, `asciiCJK`, `icu` | v26.4.0; не поддерживает `splitByRegexp` + postprocessor |
| `startsWith` | да | да | `splitByNonAlpha`, `ngrams`, `sparseGrams`, `asciiCJK`, `array` | |
| `endsWith` | да | да | `splitByNonAlpha`, `ngrams`, `sparseGrams`, `asciiCJK`, `array` | |
| `like` | да | да | `splitByNonAlpha`, `ngrams`, `sparseGrams`, `asciiCJK` | |
| `match` | да | да | `splitByNonAlpha`, `ngrams`, `sparseGrams`, `asciiCJK` | Регулярные выражения |
| `mapContainsKey` | да | да | все | Поиск по ключу map |
| `mapContainsValue` | да | да | все | Поиск по значению map |

### Опциональные параметры text-индекса

Помимо обязательного `tokenizer`, поддерживаются:

| Параметр | Описание |
| :--- | :--- |
| `preprocessor = expression(str)` | Трансформация текста **до** токенизации (например, `lowerUTF8` для case-insensitive поиска) |
| `postprocessor = expression(str)` | Трансформация токенов **после** токенизации; нормализует haystack и needle |
| `support_phrase_search = 0 \| 1` | Экспериментальный флаг: при `1` фразовый поиск использует прямое чтение из posting lists (требует position storage) |
| `dictionary_block_size = D` | Размер блока словаря токенов (для frontcoding-сжатия) |
| `dictionary_block_frontcoding_compression = B` | Включает frontcoding-сжатие словаря |
| `posting_list_block_size = C` | Размер блока списка постингов |
| `posting_list_codec` | Кодек posting lists: `none` (по умолчанию), `bitpacking`, `pfor` |

### Почему tokenbf_v1/ngrambf_v1 deprecated

- Bloom-фильтры дают только вероятностное «возможно содержит» и не поддерживают фразовый поиск.
- Text-индекс точен, поддерживает `hasPhrase`, preprocessor/postprocessor, direct read optimization и интегрирован с оптимизатором запросов.
- Старые индексы продолжают работать, но не получают новых возможностей.

## Требования

- ClickHouse **26.2+** (text index GA).
- Таблицы на базе MergeTree (включая ReplicatedMergeTree, ReplicatedReplacingMergeTree и т.д.).
- Колонка типа `String` для индексации.
- Оцените объём индекса: text index добавляет `secondary_indices_*` данные к каждому data part.

## Практические сценарии

### Создание таблицы с text-индексом

```sql
CREATE TABLE articles
(
    id UInt64,
    title String,
    body String,
    created_at DateTime,
    INDEX idx_body body TYPE text(
        tokenizer = splitByNonAlpha,
        postprocessor = lowerUTF8()
    )
)
ENGINE = MergeTree()
ORDER BY (created_at, id);
```

> **Примечание:** `GRANULARITY` для text-индекса всегда 100000000 и не указывается явно — ClickHouse игнорирует любое явное значение.

### Поиск токена и фразы

```sql
-- Точное совпадение токена (регистрозависимо без postprocessor)
SELECT id, title FROM articles WHERE hasToken(body, 'ClickHouse');

-- Любой из токенов
SELECT id FROM articles WHERE hasAnyTokens(body, ['database', 'analytics']);

-- Все токены одновременно
SELECT id FROM articles WHERE hasAllTokens(body, ['clickhouse', 'merge']);

-- Поиск фразы (последовательность слов)
SELECT id FROM articles WHERE hasPhrase(body, 'merge tree');

-- Case-insensitive поиск через hasAllTokens (с lowerUTF8 postprocessor на индексе)
SELECT id FROM articles WHERE hasAllTokens(body, ['CLICKHOUSE', 'ANALYTICS']);

-- Регулярное выражение (использует индекс при splitByNonAlpha/ngrams/sparseGrams)
SELECT id FROM articles WHERE match(body, 'ClickHouse.*MergeTree');
```

### Case-insensitive поиск через preprocessor

Preprocessor применяется к `input` и `needle` (когда needle — строка), но **только на пути text-индекса**:

```sql
CREATE TABLE logs
(
    id UInt64,
    message String,
    ts DateTime,
    INDEX idx_message message TYPE text(
        tokenizer = splitByNonAlpha,
        preprocessor = lowerUTF8()
    )
)
ENGINE = MergeTree()
ORDER BY (ts, id);

-- Поиск без учёта регистра
SELECT count() FROM logs WHERE hasToken(message, 'error');
-- Сработает для 'Error', 'ERROR', 'error' — preprocessor lowerUTF8() нормализует и haystack, и needle
```

> **Важно:** preprocessor применяется только при использовании text-индекса. При `SETTINGS use_skip_indexes = 0` результаты могут отличаться, так как `lowerUTF8` не применяется к колонке вне индекса.

### Нечёткий поиск через n-граммы

```sql
CREATE TABLE products
(
    id UInt64,
    description String,
    INDEX idx_desc description TYPE text(tokenizer = ngrams(3))
)
ENGINE = MergeTree()
ORDER BY id;

-- Поиск подстроки даже при опечатках
SELECT id FROM products WHERE hasToken(description, 'phone');
-- Или через LIKE с ngrams-токенизатором
SELECT id FROM products WHERE description LIKE '%phone%';
```

### Многокомпонентный поиск с array-токенизатором

```sql
CREATE TABLE events
(
    id UInt64,
    tags Array(String),
    INDEX idx_tags tags TYPE text(tokenizer = array)
)
ENGINE = MergeTree()
ORDER BY id;

-- Поиск по отдельным тегам
SELECT id FROM events WHERE hasAllTokens(tags, ['production', 'error']);
```

### Миграция с ngrambf_v1/tokenbf_v1 на text

```sql
-- Было (deprecated):
-- INDEX idx_msg message TYPE ngrambf_v1(3) GRANULARITY 4

-- Стало:
ALTER TABLE logs ADD INDEX idx_msg message TYPE text(tokenizer = ngrams(3));
ALTER TABLE logs MATERIALIZE INDEX idx_msg;
```

> **Примечание:** `MATERIALIZE INDEX` для text-индекса строит индекс для существующих данных. Для больших таблиц запускать в off-peak.

## Операции и команды

### Управление text-индексами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| Добавить индекс | `ALTER TABLE t ADD INDEX idx col TYPE text(...)` | Добавление без материализации |
| Материализовать | `ALTER TABLE t MATERIALIZE INDEX idx` | Сборка индекса для существующих данных |
| Удалить индекс | `ALTER TABLE t DROP INDEX idx` | Удаление индекса (данные удаляются при следующем мёрже) |
| Проверка плана | `EXPLAIN PLAN ... SELECT ...` | Проверка применения индекса (`index_analysis` в плане) |
| Прямое чтение | `SELECT ... SETTINGS query_plan_direct_read_from_text_index = 1` | Включение direct read optimization |

### Мониторинг размера и состояния индекса

```sql
-- Размер text-индекса по таблице (через system.data_skipping_indices)
SELECT
    database,
    table,
    name,
    formatReadableSize(data_compressed_bytes) AS index_size,
    formatReadableSize(marks_bytes) AS marks_size,
    granularity
FROM system.data_skipping_indices
WHERE type = 'text'
ORDER BY data_compressed_bytes DESC;

-- Размер индекса на уровне parts
SELECT
    database,
    `table`,
    sum(secondary_indices_compressed_bytes) AS total_index_compressed,
    sum(secondary_indices_marks_bytes) AS total_index_marks,
    formatReadableSize(sum(secondary_indices_compressed_bytes)) AS readable_size
FROM system.parts
WHERE active = 1 AND `table` = 'articles'
GROUP BY database, `table`;

-- Метрики кэша text-индекса
SELECT
    metric,
    formatReadableSize(value) AS size,
    formatReadableQuantity(value) AS raw_value
FROM system.metrics
WHERE metric LIKE 'TextIndex%'
ORDER BY metric;

-- Таблицы с text-индексами
SELECT
    database,
    name AS table_name,
    skipping_indices_types
FROM system.tables
WHERE has(skipping_indices_types, 'text')
ORDER BY database, name;
```

### Проверка использования индекса в запросах

```sql
-- Проверка плана выполнения: ищем "index_analysis" в output
EXPLAIN PLAN
SELECT id FROM articles WHERE hasAllTokens(body, ['clickhouse', 'merge']);

-- Проверка direct read optimization
SELECT id FROM articles WHERE hasAllTokens(body, ['clickhouse', 'merge'])
SETTINGS query_plan_direct_read_from_text_index = 1;
```

### Распределённый поиск по кластеру

Для кластеров доступны настройки анализа индекса:

| Настройка | Описание |
| :--- | :--- |
| `distributed_index_analysis_min_parts_to_activate` | Минимальное количество parts для активации распределённого анализа индекса |
| `distributed_index_analysis_min_indexes_size_to_activate` | Минимальный размер индексов для активации |

## Валидация

### Проверка создания индекса

```sql
-- Индекс должен появиться в system.data_skipping_indices
SELECT name, type, granularity, data_compressed_bytes
FROM system.data_skipping_indices
WHERE database = 'default' AND `table` = 'articles';

-- # → idx_body | text | 100000000 | 0  (данные появятся после MATERIALIZE INDEX)
```

### Проверка использования индекса

```sql
-- План должен содержать "index_analysis" или "text index" в описании выполнения
EXPLAIN PIPE
SELECT id FROM articles WHERE hasAllTokens(body, ['clickhouse', 'merge'])
-- # → ... TextIndex... или IndexTransform ...
```

### Проверка результатов поиска

```sql
-- Точное совпадение токена
INSERT INTO articles VALUES (1, 'ClickHouse Guide', 'ClickHouse — column-oriented database', now());
SELECT hasToken(body, 'ClickHouse') FROM articles WHERE id = 1;
-- # → 1

-- Case-insensitive (с lowerUTF8 postprocessor)
SELECT hasToken(body, 'CLICKHOUSE') FROM articles WHERE id = 1;
-- # → 1  (postprocessor lowerUTF8 нормализует оба токена)
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `hasToken` не находит слово | Регистрозависимость токенизации | Использовать `postprocessor = lowerUTF8()` на индексе, либо `hasToken(lowerUTF8(body), 'clickhouse')` |
| `LIKE` не использует индекс | Токенизатор `splitByRegexp` | Использовать `splitByNonAlpha`/`ngrams`/`sparseGrams`/`asciiCJK` |
| `hasPhrase` медленный | Фраза длинная, много гранул | Включить `support_phrase_search = 1`; добавить фильтр по дате в `WHERE` |
| Индекс не применяется | Условие не в `WHERE`/`PREWHERE` | Перенести условие в `WHERE` или использовать `PREWHERE` перед text-поиском |
| `MATERIALIZE INDEX` завис | Большая таблица | Запускать в off-peak; мониторить `system.mutations`; проверять `mutations_in_flight` |
| `hasToken(..., 'FOO')` не работает | `hasToken` не text-index-aware для non-`splitByNonAlpha` | Использовать `hasAllTokens`/`hasAnyTokens` вместо `hasToken`; добавить `postprocessor = lowerUTF8()` |
| `match`/`like` не использует индекс с `ngrams` | Needle короче n-gram | Убедиться, что `needle` длиннее или равен размеру n-gram (для `ngrams(3)` — минимум 3 символа) |

## Лучшие практики

1. **`splitByNonAlpha`** — дефолтный выбор для поиска по словам в логах и документах.
2. **`ngrams(N)`** — когда нужен поиск подстрок или нечёткий поиск.
3. **`preprocessor = lowerUTF8()`** — для case-insensitive поиска; применяется к `input` и `needle`.
4. **`postprocessor = lowerUTF8()`** — альтернатива preprocessor; нормализует и haystack, и needle токены.
5. **`hasAllTokens`/`hasAnyTokens`** вместо `hasToken` — предпочтительнее для нестандартных токенизаторов и preprocessor/postprocessor.
6. **Комбинируйте с датой:** `WHERE event_time > ... AND hasAllTokens(body, ['error'])` — сначала отсекается по дате, потом по индексу.
7. **Не используйте `tokenbf_v1`/`ngrambf_v1`** в новых таблицах — deprecated с 26.2.
8. **`support_phrase_search = 1`** — для `hasPhrase` с большими датасетами, чтобы уменьшить количество сканируемых гранул.
9. **Мониторинг:** следить за ростом `TextIndexHeaderCacheBytes`/`TextIndexPostingsCacheBytes`/`TextIndexTokensCacheBytes` в `system.metrics` и `data_compressed_bytes` в `system.data_skipping_indices`.
10. **Cleanup:** перед удалением text-индекса (`DROP INDEX`) проверяйте `secondary_indices_compressed_bytes` в `system.parts` — данные удалятся при следующем мёрже.

## Дополнительная информация

### Смежные темы

- Вторичные индексы (minmax, set, bloom_filter, text) — **[Архитектура](./clickhouse-architecture.md)**.
- Оптимизация запросов и PREWHERE — **[Производительность](./clickhouse-performance.md)**.
- Сравнение с Elasticsearch — **[Альтернативы ClickHouse](./clickhouse-alternatives.md)**.
- Мониторинг и метрики — **[Мониторинг](./clickhouse-monitoring.md)**.

### Ресурсы

- [Документация: Text Indexes (Full-text Search)](https://clickhouse.com/docs/reference/engines/table-engines/mergetree-family/textindexes)
- [Документация: hasToken, hasPhrase, hasAllTokens, hasAnyTokens](https://clickhouse.com/docs/reference/functions/regular-functions/string-search-functions)
- [Документация: system.data_skipping_indices](https://clickhouse.com/docs/reference/system-tables/data_skipping_indices)
- [Документация: system.metrics](https://clickhouse.com/docs/reference/system-tables/metrics)
- [Документация: system.tokenizers](https://clickhouse.com/docs/reference/system-tables/tokenizers)
- [Документация: system.parts](https://clickhouse.com/docs/reference/system-tables/parts)
