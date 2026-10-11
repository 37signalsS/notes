# ClickHouse — Словари (Dictionaries)

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Словарь (Dictionary)** — внешний по отношению к ClickHouse источник данных (PostgreSQL, MySQL, файл, HTTP и др.), кэшируемый в оперативной памяти (или на SSD) сервером ClickHouse и доступный через функции `dictGet*()`. Позволяет заменить дорогостоящие JOIN со справочниками на обращение к ключу в RAM.

**Layout (расположение)** — способ хранения словаря в памяти. Определяет скорость поиска и потребление RAM: `flat`, `hashed`, `complex_key_hashed`, `cache`, `ssd_cache`, `direct`, `range_hashed`, `ip_trie`.

**LIFETIME** — интервал обновления словаря. `LIFETIME(0)` — никогда не обновлять; `LIFETIME(3600)` — каждый час; `LIFETIME(MIN 300 MAX 600)` — случайный интервал в диапазоне (сглаживает нагрузку при массовом обновлении множества словарей).

**Source (источник)** — внешняя система, из которой словарь загружает данные: `POSTGRESQL`, `MYSQL`, `MYSQL8`, `CLICKHOUSE`, `ODBC`, `HTTP`, `FILE`, `EXECUTABLE`, `EXECUTABLE_POOL`, `REDIS`, `CASSANDRA`, `YTSARUS`, `MONGODB`, `YAMLREGEXPTREE`, `NULL`. Источники `FILE`, `EXECUTABLE`, `EXECUTABLE_POOL`, `HTTP`, `CLICKHOUSE` поддерживают дополнительные `SETTINGS`.

**dictGet()** — семейство функций для обращения к атрибуту словаря по ключу: `dictGet`, `dictGetOrDefault`, `dictHas`, `dictGetHierarchy`, `dictGetDescendants`.

**Invalidation query** — запрос (`<invalidate_query>` в XML-конфигурации), результат которого сравнивается при проверке обновления: если изменился — словарь перезагружается. Позволяет обновлять словарь только при реальных изменениях в источнике.

## Основные концепции

### Зачем словари

JOIN в ClickHouse выполняется через хэш-таблицы в RAM и дорог при частых обращениях к небольшим справочникам. Словарь решает проблему иначе:

- Данные справочника загружаются в RAM один раз (или на SSD для больших словарей).
- Обращение `dictGet('dict', 'attr', key)` — это поиск по ключу (O(1) для `hashed`/`flat`), а не хэш-join.
- Данные обновляются фоном по `LIFETIME` без участия запроса.

### Как работает загрузка и обновление

1. При старте сервера (или при первом обращении для SQL-созданных словарей) ClickHouse выполняет запрос к источнику и загружает данные в layout.
2. По истечении `LIFETIME` словарь помечается устаревшим; следующий запрос триггерит фоновую перезагрузку (старые данные продолжают отдаваться до завершения).
3. Если источник недоступен — словарь продолжает работать на старых данных, ошибка фиксируется в `system.dictionaries.last_exception`.

### Выбор layout

| Layout | Ключ | RAM | Скорость | Кейс |
| :--- | :--- | :--- | :--- | :--- |
| `flat` | числовой (UInt64) | массив, плотный | самая высокая | компактные числовые ключи без больших дыр |
| `hashed` | любой простой | хэш-таблица | высокая | универсальный выбор для простых ключей |
| `complex_key_hashed` | составной (Tuple) | хэш-таблица | высокая | ключи из нескольких колонок |
| `cache` | любой простой | LRU-кэш фиксированного размера | средняя | высокая кардинальность, не влезающая в RAM |
| `ssd_cache` | любой простой | кэш на SSD | ниже | очень большие словари |
| `direct` | любой | нет кэша | низкая (запрос к источнику) | редкие обращения, свежесть важнее скорости |
| `range_hashed` | ключ + диапазон | хэш + диапазоны | высокая | справочники с датами действия (тарифы, курсы) |
| `ip_trie` | IP-адрес | префиксное дерево | высокая | геолокация по IP, ASN |

**Важно:** `flat` выделяет массив под весь диапазон числовых ключей — при разреженных ключах (большие дыры) потребление RAM будет пропорционально максимальному ключу, а не числу строк. Для разреженных ключей используйте `hashed`.

### Поведение при отсутствии ключа

Если ключ не найден, `dictGet` возвращает значение атрибута по умолчанию (или `NULL` для Nullable-атрибутов). Для явной обработки отсутствия используйте `dictHas` (проверка наличия) или `dictGetOrDefault` (с явным значением по умолчанию).

## Практические сценарии

### Создание словаря из PostgreSQL

```sql
CREATE DICTIONARY default.users_dict
(
    id UInt64,
    name String,
    country LowCardinality(String),
    tier UInt8 DEFAULT 0
)
PRIMARY KEY id
SOURCE(POSTGRESQL(
    host 'pg.internal'
    port 5432
    db 'analytics'
    table 'users'
    user 'ch_reader'
    password '***'
))
LAYOUT(HASHED())
LIFETIME(MIN 300 MAX 600);
```

### Создание словаря с составным ключом

```sql
CREATE DICTIONARY default.pricing_dict
(
    region LowCardinality(String),
    product LowCardinality(String),
    price Decimal(10, 2)
)
PRIMARY KEY region, product
SOURCE(POSTGRESQL(
    host 'pg.internal'
    port 5432
    db 'analytics'
    table 'pricing'
    user 'ch_reader'
    password '***'
))
LAYOUT(COMPLEX_KEY_HASHED())
LIFETIME(MIN 600 MAX 1200);
```

### Словарь с кэшем для высокой кардинальности

```sql
CREATE DICTIONARY default.sessions_dict
(
    session_id UUID,
    user_id UInt64,
    channel LowCardinality(String)
)
PRIMARY KEY session_id
SOURCE(POSTGRESQL(
    host 'pg.internal'
    port 5432
    db 'analytics'
    table 'sessions'
    user 'ch_reader'
    password '***'
))
LAYOUT(CACHE(size_in_cells 1000000))
LIFETIME(60);
```

### Использование dictGet

```sql
-- Простой ключ
SELECT
    user_id,
    dictGet('default.users_dict', 'name', user_id) AS user_name,
    dictGet('default.users_dict', 'country', user_id) AS country
FROM events;

-- Составной ключ
SELECT
    dictGet('default.pricing_dict', 'price', tuple(region, product)) AS price
FROM sales;

-- Проверка наличия ключа
SELECT dictHas('default.users_dict', user_id) AS known_user
FROM events;

-- Со значением по умолчанию
SELECT dictGetOrDefault('default.users_dict', 'tier', user_id, 0) AS tier
FROM events;
```

### XML-конфигурация (альтернатива SQL DDL)

```xml
<!-- /etc/clickhouse-server/config.d/dictionaries.xml -->
<clickhouse>
    <dictionaries>
        <users_dict>
            <source>
                <postgresql>
                    <host>pg.internal</host>
                    <port>5432</port>
                    <db>analytics</db>
                    <table>users</table>
                    <user>ch_reader</user>
                    <password>***</password>
                </postgresql>
            </source>
            <layout>
                <hashed />
            </layout>
            <structure>
                <id>
                    <name>id</name>
                </id>
                <attribute>
                    <name>name</name>
                    <type>String</type>
                    <null_value></null_value>
                </attribute>
            </structure>
            <lifetime>
                <min>300</min>
                <max>600</max>
            </lifetime>
        </users_dict>
    </dictionaries>
</clickhouse>
```

### EXECUTABLE-источник (внешний скрипт)

Для интеграций, где нет драйвера (например, внутренние API, проприетарные системы), используйте EXECUTABLE — скрипт, читает данные и пишет в stdout:

```sql
CREATE DICTIONARY default.internal_api_dict
(
    key String,
    value String
)
PRIMARY KEY key
SOURCE(EXECUTABLE(
    path '/opt/scripts/fetch_dict.sh'
    format 'TabSeparated'
    timeout 5
    max_pool_size 4
))
LAYOUT(CACHE(size_in_cells 100000))
LIFETIME(MIN 60 MAX 120);
```

```bash
# /opt/scripts/fetch_dict.sh (пример)
#!/bin/bash
# Выполняется от имени пользователя ClickHouse
echo -e "key1\tvalue1"
echo -e "key2\tvalue2"
# → stdout читается как данные словаря
```

**Важно:**
- `timeout` — максимальное время выполнения скрипта (по умолчанию 60 сек.). При превышении — словарь помечается `FAILED`.
- `max_pool_size` — количество параллельных экземпляров скрипта (EXECUTABLE_POOL).
- Скрипт должен быть `chmod +x` и работать от имени пользователя ClickHouse.
- При зависании скрипта словарь уходит в `FAILED_AND_RELOADING` — проверяйте `last_exception` и `error_count`.

### EXECUTABLE_POOL (пул скриптов)

```sql
SOURCE(EXECUTABLE_POOL(
    path '/opt/scripts/fetch_dict.sh'
    format 'TabSeparated'
    max_pool_size 8
    timeout 10
))
```

Полезно для высоконагруженных словарей: несколько экземпляров скрипта запускаются параллельно, каждый обрабатывает свой запрос.

### Управление и мониторинг

```sql
-- Статус всех словарей
SELECT database, name, status, type, bytes_allocated, element_count,
       query_count, round(hit_rate, 4) AS hit_rate, last_exception
FROM system.dictionaries
ORDER BY bytes_allocated DESC;

-- Принудительная перезагрузка
SYSTEM RELOAD DICTIONARIES;                    -- все словари
SYSTEM RELOAD DICTIONARY default.users_dict;   -- конкретный словарь
```

Значения `status`: `NOT_LOADED`, `LOADED`, `FAILED`, `LOADING`, `MODIFYING`.

### Мониторинг (все колонки system.dictionaries)

| Колонка | Тип | Значение |
| :--- | :--- | :--- |
| `database` | String | База данных (пусто для XML-словарей) |
| `name` | String | Имя словаря |
| `uuid` | UUID | UUID словаря |
| `status` | Enum8 | См. ниже |
| `origin` | String | Путь к конфигу-файлу |
| `type` | String | Тип layout |
| `key.names` / `key.types` | Array(String) | Имена и типы ключей |
| `attribute.names` / `attribute.types` | Array(String) | Имена и типы атрибутов |
| `bytes_allocated` | UInt64 | Выделено RAM |
| `hierarchical_index_bytes_allocated` | UInt64 | RAM для иерархического индекса |
| `query_count` | UInt64 | Количество обращений с момента загрузки |
| `hit_rate` | Float64 | % попаданий в кэш (только для `cache`/`ssd_cache`) |
| `found_rate` | Float64 | % обращений, по которым ключ найден |
| `element_count` | UInt64 | Количество элементов |
| `load_factor` | Float64 | Заполнение (для `hashed` — заполнение хэш-таблицы) |
| `source` | String | Текстовое описание источника |
| `lifetime_min` / `lifetime_max` | UInt64 | LIFETIME в секундах |
| `loading_start_time` | DateTime | Начало загрузки |
| `last_successful_update_time` | DateTime | Успешное завершение обновления |
| `error_count` | UInt64 | Количество ошибок с последнего успеха |
| `loading_duration` | Float32 | Длительность загрузки (сек.) |
| `last_exception` | String | Текст последней ошибки |
| `comment` | String | Комментарий к словарю |

**Значения `status`:**
- `NOT_LOADED` — словарь не загружен
- `LOADED` — успешно загружен
- `FAILED` — ошибка загрузки
- `LOADING` — идёт загрузка
- `LOADED_AND_RELOADING` — загружен и перегружается (например, по `LIFETIME` или `SYSTEM RELOAD`)
- `FAILED_AND_RELOADING` — ошибка, но идёт повторная попытка
- `NOT_EXIST` — словарь не существует (например, DDL удалён)

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Dictionary ... is not loaded` | Словарь не загружен (источник недоступен или ошибка DDL) | `SELECT last_exception FROM system.dictionaries WHERE name = '...'`; проверить сеть и учётные данные источника |
| `last_exception` не пуст | Ошибка загрузки/обновления | Проверить `last_exception`, доступность источника, `LIFETIME` |
| `hit_rate` низкий | Словарь почти не используется или `cache` layout слишком мал | Проверить запросы; увеличить `size_in_cells` для `cache` |
| `flat` layout потребляет много RAM | Разреженные числовые ключи (дыры) | Перейти на `hashed` — `flat` выделяет массив под весь диапазон ключей |
| Данные устарели | `LIFETIME` слишком велик | Уменьшить `LIFETIME`; использовать `<invalidate_query>` для мгновенной инвалидации |
| `flat` перегружает RAM при редком использовании | `flat` выделяет массив под весь диапазон | Использовать `cache` или `direct` для редких обращений |
| `cache` layout показывает `hit_rate` ≈ 0 | `size_in_cells` слишком мал — кэш вытесняется | Увеличить `size_in_cells` или перейти на `ssd_cache` |
| `error_count` растёт, но `last_exception` пуст | Ошибка в `invalidate_query` или source-настройках | Проверить `last_exception` после ручного `SYSTEM RELOAD DICTIONARY` |
| `status = FAILED_AND_RELOADING` | Источник недоступен, идёт повторная попытка | Проверить доступность источника; при плановом отключении — `SYSTEM SUSPEND DICTIONARY` |

## Сценарии CI/CD (DevOps/SRE)

### Ansible: управление словарями как кодом

```yaml
# inventory/group_vars/clickhouse/dictionaries.yml
# Параметры подключения к источникам хранятся в Secret-менеджере, не в DDL
ch_dictionary_sources:
  - name: users_dict
    source_type: postgresql
    host: "{{ vault_pg_host }}"
    port: 5432
    db: analytics
    table: users
    user: "{{ vault_pg_user }}"
    password: "{{ vault_pg_password }}"

# templates/dictionary.sql.j2
# CREATE DICTIONARY IF NOT EXISTS {{ name }} (...) SOURCE({{ source_type }}(...)) LAYOUT(HASHED()) LIFETIME(MIN 300 MAX 600);
```

### Health check: проверка словарей в проде

```bash
# Критичные словари должны быть LOADED
clickhouse-client --query "
    SELECT name, status, error_count, last_exception
    FROM system.dictionaries
    WHERE name IN ('users_dict', 'pricing_dict', 'geo_dict')
      AND status != 'LOADED'
"
# → Пусто = все ок. Иначе — alert.

# Мониторинг через Prometheus (system.dictionaries через clickhouse-exporter)
# Алерт: error_count > 0 для критичных словарей
# Алерт: bytes_allocated > 80% max_memory_usage
```

### ETL: словари как часть пайплайна загрузки

```bash
# Пример: словарь из CSV-файла, обновляемый по расписанию
clickhouse-client --query "
    CREATE DICTIONARY default.ip_geo_dict
    (
        ip IPv4,
        country String,
        city String
    )
    PRIMARY KEY ip
    SOURCE(FILE(path '/opt/dictionaries/ip_geo.tsv' format 'TabSeparated'))
    LAYOUT(HASHED())
    LIFETIME(MIN 300 MAX 600);
"

# В пайплайне: обновить CSV → SYSTEM RELOAD DICTIONARY default.ip_geo_dict
```

### Алертинг по статусу словарей

```sql
-- Алерт: словарь не загружен более N минут
SELECT
    name,
    status,
    error_count,
    now() - last_successful_update_time AS time_since_last_update
FROM system.dictionaries
WHERE status IN ('FAILED', 'FAILED_AND_RELOADING', 'NOT_LOADED')
   OR (last_successful_update_time < now() - INTERVAL 1 HOUR AND status = 'LOADED')
```

## Лучшие практики

1. **Заменяйте JOIN на `dictGet`** для справочников, которые меняются редко (пользователи, товары, география).
2. **Выбирайте layout по ключу и кардинальности** — `flat` для плотных числовых ключей, `hashed` для универсальности, `cache` для высокой кардинальности.
3. **Используйте `LIFETIME(MIN MAX)`** вместо фиксированного интервала, чтобы сглаживать пики обновлений при множестве словарей.
4. **`LIFETIME(0)`** для неизменяемых справочников (загрузка один раз).
5. **Мониторьте `system.dictionaries`** — `status`, `last_exception`, `hit_rate`, `bytes_allocated`, `error_count`, `loading_duration`.
6. **Не храните секреты в DDL** — используйте Named Collections для параметров подключения к источнику.
7. **`<invalidate_query>`** — для источников, где важна свежесть: словарь обновляется только при изменении результата запроса.
8. **EXECUTABLE-источники** — внешние скрипты (Python, Go, bash) генерируют TSV/CSV в stdout. Используйте для интеграций с системами, которых нет вроде ODBC/MySQL-драйверов. Обязателен `timeout` и `stdout`-буферизация — при зависании скрипта словарь уходит в `FAILED_AND_RELOADING`.
9. **EXECUTABLE_POOL** — пул EXECUTABLE-источников с `max_pool_size`. Полезен для высоконагруженных словарей: несколько экземпляров скрипта запускаются параллельно, каждый обрабатывает свой запрос.
10. **`<include_from>`** — подключайте общие настройки (например, `substitutions.xml`) из одного файла во все конфиги словарей, чтобы избежать дублирования.
11. **Разрешение доступа к EXECUTABLE**: скрипты запускаются от имени пользователя ClickHouse. Проверяйте `chmod +x` и права на файлы данных (например, `/opt/dictionaries/`).
12. **`cache` layout с `size_in_cells`** — начинайте с 10% от ожидаемой кардинальности; при `hit_rate` < 0.95 увеличивайте.
13. **`ssd_cache` для словарей > 100 МБ** — RAM-кэш не вмещает, но SSD-кэш ускоряет повторные обращения.
14. **Иерархические атрибуты (`HIERARCHICAL`)** — для словарей с родитель/потомок (например, категории товаров). Используйте `dictGetHierarchy` / `dictGetDescendants`.
15. **Инъективные атрибуты (`INJECTIVE`)** — помечают атрибуты, которые не могут повторяться для разных ключей. ClickHouse может оптимизировать обновления.

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- Оптимизация JOIN — **[Производительность](./clickhouse-performance.md#оптимизация-join)**.
- Интеграция с PostgreSQL (источник словаря) — **[Интеграция PostgreSQL и ClickHouse](../PostgreSQL/Integrations/clickhouse.md#словари-dictionaries)**.

### Ресурсы

- [Документация: Dictionaries](https://clickhouse.com/docs/en/sql-reference/dictionaries)
- [Документация: dictGet](https://clickhouse.com/docs/en/sql-reference/functions/dict-functions)
- [Документация: system.dictionaries](https://clickhouse.com/docs/en/reference/system-tables/dictionaries)
- [Документация: EXECUTABLE-источник](https://clickhouse.com/docs/en/reference/statements/create/dictionary/sources/executable-file)
- [Документация: layouts](https://clickhouse.com/docs/en/reference/statements/create/dictionary/layouts/overview)
- [Документация: sources](https://clickhouse.com/docs/en/reference/statements/create/dictionary/sources/overview)
