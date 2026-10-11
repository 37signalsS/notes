# Поддержка JSON в PostgreSQL

**Актуально для:** PostgreSQL 15–18

## Определения

- **JSON (JavaScript Object Notation)**: Текстовый формат обмена данными. В PostgreSQL представлен двумя типами: `json` (текстовый) и `jsonb` (бинарный).
- **jsonb (Binary JSON)**: Основной тип данных для JSON в PostgreSQL. Хранит данные в декомпозированном бинарном формате, что позволяет избежать повторного парсинга при чтении и поддерживает индексацию.
- **JsonPath**: Язык запросов (стандарт SQL/JSON), позволяющий выполнять сложную фильтрацию и поиск внутри JSON-структур с использованием синтаксиса, похожего на JavaScript.
- **TOAST (The Oversized Attribute Storage Technique)**: Механизм для хранения атрибутов размером > 2 КБ. Для `jsonb` это критично: при обновлении одного ключа в TOAST-документе PostgreSQL вынужден декомпрессировать и переписать весь документ целиком.
- **Compression (LZ4 / PGLZ)**: Алгоритмы сжатия данных в TOAST. С PostgreSQL 14+ доступно сжатие **LZ4** для `jsonb` (требуется компиляция с `--with-lz4`). По умолчанию используется **PGLZ**; LZ4 значительно быстрее при декомпрессии, что критично для тяжелых документов.
- **JEntry**: Внутренний указатель в структуре `jsonb`, определяющий тип и смещение каждого элемента, что обеспечивает доступ за O(1) к ключам верхнего уровня.

## Базовые концепции

### Сравнение json и jsonb

| Характеристика | `json` | `jsonb` |
| :--- | :--- | :--- |
| **Хранение** | Точная копия текста | Бинарная иерархия |
| **Порядок ключей** | Сохраняется | Не сохраняется (сортируется по длине и значению) |
| **Дубликаты ключей** | Сохраняются | Удаляются (остается последний) |
| **Скорость вставки** | Высокая | Ниже (требуется бинаризация) |
| **Скорость чтения** | Низкая (парсинг при каждом вызове) | Высокая |
| **Индексация** | Нет | **GIN**, B-Tree (через выражения) |

### Механика хранения и MVCC

PostgreSQL обрабатывает `jsonb` как единый атомарный объект. Это порождает две основные проблемы производительности:
1. **Write Penalty (MVCC)**: Любой `UPDATE` (даже через `jsonb_set`) создает новую версию всей строки таблицы. Если JSON-документ весит 1 МБ, обновление одного флага приведет к записи 1 МБ в WAL.
2. **Read Penalty (TOAST)**: Если документ вынесен в TOAST, планировщик не может прочитать только один ключ. СУБД должна извлечь все чанки, склеить их и декомпрессировать.

**Решение**: Выносите часто обновляемые поля (статусы, счетчики) в обычные реляционные колонки. Для больших `jsonb`-документов учитывайте TOAST, сжатие, WAL и отдельные настройки таблицы.

## Индексация

### 1. GIN (Generalized Inverted Index)
- **`jsonb_ops` (default)**: Индексирует ключи, значения и элементы массивов. Поддерживает операторы `@>`, `?`, `?&`, `?|`.
- **`jsonb_path_ops`**: Индексирует только полные пути (хеши путей). Занимает меньше места и работает быстрее, но поддерживает только оператор `@>`.

### 2. Функциональные B-Tree индексы
Используются для точного поиска по конкретному полю.
```sql
CREATE INDEX idx_orders_user_id ON orders ((data->>'user_id'));
```

### 3. Индексы на JsonPath (PG 12+)
Индексация выражений JsonPath позволяет ускорить сложные поисковые запросы.

## Практические сценарии

### 1. Продвинутый JsonPath

Синтаксис: `column @@ 'jsonpath_expression'`.
```sql
-- Найти пользователей из Москвы старше 25 лет
SELECT * FROM profiles 
WHERE data @@ '$.address.city == "Moscow" && $.age > 25';

-- Использование методов (.type(), .size())
SELECT data->'tags' FROM articles 
WHERE data @@ '$.tags.size() > 5';
```

**Ожидаемый результат:**
```text
 id |    name    |               data
----+------------+---------------------------------
  1 | Ivan       | {"address": {"city": "Moscow"}, "age": 30}
  3 | Petr       | {"address": {"city": "Moscow"}, "age": 28}
```

### 2. Трансформация данных через JSON_TABLE (PG 17)

Позволяет развернуть вложенные массивы JSON в плоскую таблицу для последующих JOIN.
```sql
SELECT orders.id, jt.item_name, jt.price
FROM orders,
     JSON_TABLE(orders.data, '$.items[*]'
       COLUMNS (
         item_name text PATH '$.product_name',
         price numeric PATH '$.price'
       )
     ) AS jt
WHERE jt.price > 1000;
```

**Ожидаемый результат:**
```text
 id | item_name |  price
----+-----------+--------
 10 | Laptop    | 1500.00
 10 | Mouse     |  50.00
 11 | Phone     | 1200.00
```

### 3. Безопасное извлечение скалярных значений (PG 17)

`JSON_VALUE` автоматически приводит типы и обрабатывает ошибки.
```sql
SELECT JSON_VALUE(data, '$.user.id' RETURNING int DEFAULT 0 ON ERROR) 
FROM events;
```

**Ожидаемый результат:**
```text
 json_value
------------
        42
         0
```

### 4. Модификация и Сабскриптинг

С PostgreSQL 14 доступен синтаксис квадратных скобок:
```sql
-- Обновление глубоко вложенного значения
UPDATE users 
SET data['profile']['settings']['theme'] = '"dark"'::jsonb
WHERE id = 1;
```

**Ожидаемый результат:**
```text
UPDATE 1
-- Проверка:
SELECT data['profile']['settings']['theme'] FROM users WHERE id = 1;
 "dark"
```

## Диагностика и обслуживание

### Мониторинг для SRE

Для sysadmin критично отслеживать потребление ресурсов таблицами с JSON.

```sql
-- Размер таблицы с TOAST и индексами
SELECT pg_size_pretty(pg_total_relation_size('orders'));

-- Размер TOAST-таблицы отдельно (важно для JSON)
SELECT pg_size_pretty(pg_relation_size('orders_toast'));

-- Количество мертвых кортежей в TOAST
SELECT relname, n_dead_tup, last_autovacuum
FROM pg_stat_user_tables
WHERE relname LIKE '%toast%';

-- WAL-генерация: количество записей на транзакцию
SELECT wal_records, wal_bytes, wal_fpi
FROM pg_stat_database
WHERE datname = 'mydb';

-- Активные долгие транзакции (держат WAL и MVCC версии)
SELECT pid, now() - xact_start AS xact_duration, state, query
FROM pg_stat_activity
WHERE state != 'idle'
  AND now() - xact_start > interval '5 minutes';

-- Статус архивации WAL (важно для бэкапов JSON-интенсивных таблиц)
SELECT archived_count, failed_count, last_archived_wal, last_archived_time
FROM pg_stat_archiver;
```

**Ожидаемый результат:**
```text
 pg_size_pretty
----------------
 1.2 GB

 pg_size_pretty
----------------
 340 MB
```

### Борьба с Bloat (Раздуванием)

Если таблица с JSON интенсивно обновляется, стандартный `AUTOVACUUM` может не справляться.
- **Симптом**: Размер таблицы растет непропорционально количеству строк.
- **Диагностика**: Используйте расширение `pgstattuple` для проверки `free_percent`.
- **Решение**: Регулярный `REINDEX CONCURRENTLY` или использование **pg_repack** для онлайн-очистки.

### Оптимизация TOAST

Для больших документов (> 2 КБ) используйте LZ4:
```sql
-- Проверить текущий алгоритм сжатия
SELECT attname, attcompression FROM pg_attribute 
WHERE attrelid = 'my_table'::regclass;

-- Смена на LZ4 (для новых данных)
ALTER TABLE my_table ALTER COLUMN data SET COMPRESSION lz4;

-- Глобальный default (требует перезагрузки конфигурации)
ALTER SYSTEM SET default_toast_compression = 'lz4';
SELECT pg_reload_conf();
```

## Лучшие правила (Security & Performance)

1. **Используйте `jsonb` по умолчанию**: Тип `json` нужен только если критично сохранение исходного форматирования или порядка ключей.
2. **Нормализуйте горячие данные**: Поля, участвующие в `JOIN` или часто обновляемые, **обязаны** быть обычными колонками.
3. **Ограничивайте вложенность**: Глубина более 5-7 уровней усложняет написание запросов и их поддержку.
4. **Валидация на входе**: Используйте `CHECK (jsonb_typeof(data) = 'object')` или расширение `pg_jsonschema` для валидации JSON-схем.
5. **Следите за типами**: Помните, что `->>` возвращает `text`. Для расчетов всегда делайте явное приведение: `(data->>'price')::numeric`.

## Лучшие практики и очистка

### Рекомендации для SRE/Sysadmin

1. **Дисковая подсистема**: Отдельный диск/раздел для таблиц с большими JSON. TOAST-таблицы могут занимать значительное место; мониторьте их рост отдельно через `pg_relation_size('table_toast')`.
2. **Синхронизация времени**: NTP обязателен. Логическая репликация и `commit_timestamp` ломаются при рассинхронизации часов.
3. **Мониторинг**: `pg_stat_user_tables`, `pg_stat_archiver`, `pg_stat_bgwriter` — базовый набор. Для JSON-интенсивных таблиц добавьте `pg_total_relation_size` в Grafana/Zabbix.
4. **WAL**: JSON-обновления генерируют много WAL. Настройте `max_wal_size` >= 2GB для OLTP, >= 10GB для analytics. Регулярно проверяйте `pg_stat_archiver.failed_count`.
5. **Autovacuum**: Для JSON-тяжелых таблиц снизьте `autovacuum_vacuum_scale_factor` до 0.01–0.05. Мониторьте `n_dead_tup` в `pg_stat_user_tables`.
6. **GIN индексы**: Регулярно проверяйте их размер (`pg_size_pretty(pg_relation_size('idx_name'))`). При раздувании используйте `REINDEX CONCURRENTLY`.
7. **Сжатие TOAST**: Если PostgreSQL скомпилирован с `--with-lz4`, включите `default_toast_compression = lz4` для JSON-интенсивных таблиц.
8. **Безопасность**: `ssl = on` в production. Для JSON-полей с персональными данными рассмотрите маскирование (см. **[Анонимизация и маскирование](../Operations/anonymization.md)** — включая собственные маскирующие функции для JSONB).

### Откат и очистка

- **Сброс параметров TOAST**: `ALTER TABLE my_table ALTER COLUMN data SET COMPRESSION pglz;`
- **Удаление JSON индекса**: `DROP INDEX idx_orders_user_id;` — при необходимости замените на составной индекс.
- **Очистка мертвых кортежей**: `VACUUM (VERBOSE) orders;` или `pg_repack -t orders`.
- **Восстановление после сбоя конфигурации**: запуск через `postgres -D $PGDATA -c config_file=/path/to/fallback.conf`
- **Бэкап перед изменениями**: `pg_dump --table orders --format=custom orders.dump` — обязательно перед `REINDEX` или изменением compression.

## Дополнительная информация

### Сравнение с MongoDB

| Характеристика | PostgreSQL (`jsonb`) | MongoDB |
| :--- | :--- | :--- |
| **Транзакции** | Полный ACID (Multi-table) | ACID на уровне документа |
| **Схема** | Гибридная (SQL + NoSQL) | Schema-less (Dynamic) |
| **JOIN** | Полноценные SQL JOIN | Ограниченно ($lookup) |

### Сравнение версий

| Версия | Ключевые изменения в поддержке JSON |
|--------|-------------------------------------|
| PG 15  | Улучшения в SQL/JSON функциях, оптимизация GIN для jsonb_path_ops |
| PG 16  | Улучшения в планировщике для jsonb, новые JsonPath методы |
| PG 17  | **JSON_TABLE()**, **JSON_VALUE()**, **JSON_QUERY()**, **JSON_EXISTS()** (SQL/JSON standard), конструкторы JSON |
| PG 18  | Улучшения в executor для jsonb, оптимизации TOAST decompression |

### Смежные темы
- Индексы: **[Индексы в PostgreSQL](./indexes.md)**
- Оптимизация: **[Performance Tuning](../Operations/performance_tuning.md)**
- Полнотекстовый поиск: **[FTS в PostgreSQL](./full_text_search.md)**
- Восстановление после сбоев: **[Corruption Recovery](./corruption_recovery.md)**
