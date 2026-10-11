# Механизмы оптимизатора MySQL: ICP, MRR и BKA

**Актуально для:** MySQL 8.0 LTS / 8.4 LTS / 9.x Innovation

## Определения

**Index Condition Pushdown (ICP)** — оптимизация, при которой часть условий `WHERE`, относящихся к индексу, передаётся напрямую в движок хранения (InnoDB). Это позволяет фильтровать строки на уровне движка до чтения полных данных из таблицы.

**Multi-Range Read (MRR)** — стратегия оптимизации дискового ввода-вывода. MRR собирает идентификаторы строк (Primary Keys) из вторичного индекса, сортирует их и извлекает полные строки из таблицы последовательно, превращая случайное чтение (Random I/O) в последовательное (Sequential I/O).

**Batched Key Access (BKA)** — алгоритм соединения таблиц, объединяющий Nested-Loop Join и MRR. Он накапливает ключи из внешней таблицы в буфере и отправляет их пакетом в MRR для быстрого извлечения соответствующих строк из внутренней таблицы.

**optimizer_switch** — динамический параметр, управляющий включением и отключением оптимизационных стратегий. Принимает значения `on`, `off`, `default`. Изменения на уровне сессии вступают в силу немедленно без перезапуска сервера.

**cost-based optimizer** — режим оптимизатора, принимающий решения на основе оценки стоимости операций. Для MRR доступен режим `mrr_cost_based=on/off`, который может давать неверные оценки на системах с высокой задержкой диска.

**read_rnd_buffer_size** — per-connection буфер, используемый MRR для сортировки Primary Keys перед пакетным чтением строк. Выделяется по требованию на запрос, не глобально.

**join_buffer_size** — per-connection буфер для неупорядоченных соединений (BNLJ, BKA). Выделяется для каждого соединения, которое не может использовать индекс для JOIN.

**Hash Join** — алгоритм соединения таблиц, представленный в MySQL 8.0.20+. В некоторых сценариях заменяет или дополняет BKA, особенно при равномерном распределении данных и достаточном объёме `join_buffer_size`.

## Основные концепции

### Архитектура и принцип работы

MySQL Optimizer принимает решения на этапе планирования запроса, до его выполнения. ICP, MRR и BKA — это стратегии уровня доступа к данным, которые оптимизатор применяет при построении плана:

1. **Index Condition Pushdown (ICP):**
   - **Как работает:** При Range Scan по вторичному индексу MySQL обычно извлекает адрес строки (PK), читает полную строку из кластерного индекса и только потом проверяет остальные условия `WHERE`. С ICP движок проверяет все условия, которые можно вычислить по полям индекса, *до* обращения к таблице.
   - **Жизненный цикл:** Включён по умолчанию с MySQL 5.6. Не требует ручной настройки в большинстве случаев.
   - **SRE-эффект:** Резкое снижение количества обращений к основному кластерному индексу и уменьшение нагрузки на шину данных между сервером и InnoDB.
   - **Условие срабатывания:** Только для вторичных индексов. Условия должны использовать только поля индекса (без функций, не должны требовать доступа к столбцам, не входящим в индекс).

2. **Multi-Range Read (MRR):**
   - **Как работает:** При сканировании диапазона по вторичному индексу PK разбросаны по диску хаотично. MRR выполняет:
     1. Сканирует индекс и собирает PK в буфер `read_rnd_buffer_size`.
     2. Сортирует PK в буфере по их физическому расположению на диске.
     3. Читает строки из таблицы последовательно.
   - **Жизненный цикл:** Включён по умолчанию в MySQL 8.0+, но в режиме `mrr_cost_based=on` оптимизатор часто отклоняет его использование из-за неверной оценки стоимости сортировки.
   - **SRE-эффект:** На HDD даёт кратный прирост скорости. На SSD снижает нагрузку на контроллер и выравнивает IOPS.
   - **Зависимость:** Требует включённого MRR.

3. **Batched Key Access (BKA):**
   - **Как работает:** BKA улучшает производительность соединений, когда индекс внутренней таблицы не помещается в Buffer Pool.
     1. Строки из внешней таблицы накапливаются в `join_buffer_size`.
     2. Ключи сортируются и передаются в интерфейс MRR.
     3. MRR выполняет пакетное извлечение данных из внутренней таблицы.
   - **Жизненный цикл:** Зависит от MRR. В MySQL 8.0.20+ взаимодействует с Hash Join — для больших неиндексированных соединений Hash Join может быть эффективнее.
   - **SRE-эффект:** Минимизирует скачки latency при соединениях больших таблиц.

### Версионные особенности и изменения

| Версия | Изменение |
| :--- | :--- |
| MySQL 5.6 | ICP представлен, включён по умолчанию |
| MySQL 5.7 | BKA представлен |
| MySQL 8.0.12 | Улучшена оценка стоимости для ICP/MRR |
| MySQL 8.0.18 | `EXPLAIN ANALYZE` — реальные метрики выполнения |
| MySQL 8.0.20 | Hash Join представлен как альтернатива BKA |
| MySQL 8.0.29 | Исправлены проблемы с INSTANT ADD/DROP COLUMN в контексте оптимизатора |
| MySQL 8.4 | `mysqlpump` удалён; `optimizer_switch` управляется через `SET PERSIST` |

### Когда эти механизмы НЕ работают или вредны

| Механизм | Почему может не сработать | Почему может навредить |
| :--- | :--- | :--- |
| **ICP** | Условия используют функции или столбцы, не входящие в индекс; Storage engine не InnoDB (например, MyISAM); `type=ALL` (full table scan) | Нет значительного вреда; всегда безопасен при наличии вторичного индекса |
| **MRR** | `mrr_cost_based=on` и оптимизатор неверно оценил сортировку как дешевле Random I/O; слишком маленький `read_rnd_buffer_size` для большого Range Scan | Для очень маленьких Range Scan (<100 строк) сортировка PK добавляет overhead без пользы |
| **BKA** | Внутренняя таблица имеет подходящий индекс для Nested Loop; Hash Join выбран оптимизатором (MySQL 8.0.20+); `join_buffer_size` слишком мал | Для малых таблиц, помещающихся в Buffer Pool, BKA не даёт преимуществ |

### Взаимодействие с Hash Join

MySQL 8.0.20+ представил Hash Join для соединений больших таблиц без индексов. BKA и Hash Join могут конкурировать:

- **BKA** эффективен, когда внутренняя таблица имеет индекс на поле соединения.
- **Hash Join** эффективен, когда нет индекса, но `join_buffer_size` позволяет вместить хеш-таблицу.
- **Конфигурация:** `optimizer_switch='hashjoin=on'` включён по умолчанию в 8.0.20+. BKA при этом может игнорироваться оптимизатором.

### Взаимодействие с репликацией

Эти механизмы не влияют на логику бинарного логирования, так как работают на уровне чтения плана выполнения. Однако:

- **MRR** увеличивает количество `rows_examined` в Performance Schema, что может повлиять на мониторинг.
- **ICP** может изменить количество строк, передаваемых в Join, но не изменяет результат запроса.

### Взаимодействие с другими буферами

| Параметр | Влияние на ICP/MRR/BKA | Рекомендация |
| :--- | :--- | :--- |
| `innodb_buffer_pool_size` | Если данные в Buffer Pool, MRR/BKA дают меньший эффект (уже sequential из Buffer Pool) | Оценивайте эффективность на реальной нагрузке, а не только на холодных данных |
| `sort_buffer_size` | Сортируются данные для ORDER BY/GROUP BY, не связан напрямую с MRR | Отдельный параметр; не увеличивайте без необходимости |
| `tmp_table_size` / `max_heap_table_size` | Временные таблицы для подзапросов влияют на общий план, но не на ICP/MRR напрямую | Настройте для избежания disk-based temp tables |
| `thread_cache_size` | Каждый поток потребляет `read_rnd_buffer_size` + `join_buffer_size` | Учитывайте при расчете общего RAM |

### Моделирование потребления памяти

MRR и BKA используют per-connection буферы:

```
MRR RAM (per connection) ≈ read_rnd_buffer_size
BKA RAM (per connection) ≈ join_buffer_size

Total peak RAM for optimizer buffers ≈ (read_rnd_buffer_size + join_buffer_size) × max_connections
```

**Пример:** Для сервера с 200 соединениями:
```
read_rnd_buffer_size = 4M
join_buffer_size = 8M
Total = (4 + 8) MB × 200 = 2.4 GB
```

## Практические сценарии

### Сценарий 1: Глобальная конфигурация optimizer_switch (MySQL 8.4+)

MySQL 8.4 поддерживает `SET PERSIST` для динамического сохранения параметров:

```sql
-- Проверка текущего состояния
SHOW VARIABLES LIKE 'optimizer_switch';

-- Установка для текущей сессии (не требует перезапуска)
SET SESSION optimizer_switch='mrr=on,mrr_cost_based=off,batched_key_access=on,index_condition_pushdown=on';

-- Постоянное сохранение (MySQL 8.4+)
SET PERSIST optimizer_switch='mrr=on,mrr_cost_based=off,batched_key_access=on,index_condition_pushdown=on';

-- Проверка сохранённого значения
SHOW VARIABLES LIKE 'optimizer_switch';
```

**Вариация для MySQL 8.0 (до 8.4):**
```ini
# my.cnf — требует перезапуска
[mysqld]
optimizer_switch = "mrr=on,mrr_cost_based=off,batched_key_access=on,index_condition_pushdown=on"
```

### Сценарий 2: Диагностика активации ICP/MRR/BKA в запросе

```sql
-- 1. Получить план выполнения
EXPLAIN FORMAT=JSON
SELECT o.id, o.total, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.order_date BETWEEN '2026-01-01' AND '2026-01-31'
  AND o.status = 'completed';

-- 2. Ищем в выводе JSON:
-- "using_index_condition": true  → ICP активен
-- "using_mrr": true              → MRR активен
-- "using_join_buffer": "Batched Key Access" → BKA активен

-- 3. Проверка через Performance Schema
SELECT
  event_name,
  count_star,
  sum_timer_wait / 1e12 AS total_time_sec,
  avg_timer_wait / 1e9 AS avg_time_ms
FROM performance_schema.events_statements_summary_by_digest
WHERE digest_text LIKE '%orders o%customers c%'
LIMIT 5;
```

### Сценарий 3: Настройка per-connection буферов для MRR/BKA

```ini
[mysqld]
# Глобальное включение
optimizer_switch = "mrr=on,mrr_cost_based=off,batched_key_access=on,index_condition_pushdown=on"

# Буферы
read_rnd_buffer_size = 4M    # Для MRR: сортировка PK
join_buffer_size     = 8M    # Для BKA: накопление ключей внешней таблицы
```

**Расчёт для серверов с большим количеством соединений:**
```bash
# Максимальное потребление RAM на optimizer buffers
MAX_CONNECTIONS=500
READ_RND_BUFFER=4M
JOIN_BUFFER=8M

TOTAL_RAM=$(( (READ_RND_BUFFER + JOIN_BUFFER) * MAX_CONNECTIONS ))
echo "Total RAM for optimizer buffers: ${TOTAL_RAM} MB ($(( TOTAL_RAM / 1024 )) GB)"
# → Total RAM for optimizer buffers: 6000 MB (~6 GB)
```

### Сценарий 4: Принудительное включение MRR на уровне сессии

Для проблемных запросов, где оптимизатор отказывается использовать MRR:

```sql
-- Включение MRR только для текущей сессии
SET SESSION optimizer_switch='mrr=on,mrr_cost_based=off';

-- Проверка плана
EXPLAIN FORMAT=TREE
SELECT * FROM large_table
WHERE indexed_col BETWEEN 1000 AND 100000;

-- Ожидаем увидеть: "Using MRR"
```

### Сценарий 5: Валидация эффективности (EXPLAIN ANALYZE)

```sql
-- До настройки
EXPLAIN ANALYZE
SELECT o.id, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.order_date BETWEEN '2026-01-01' AND '2026-01-31'
LIMIT 1000;

-- После включения optimizer_switch и перезапуска
-- Сравниваем actual time, rows, loops
```

### Сценарий 6: Мониторинг и алертинг (Prometheus + MySQL Exporter)

Метрики для отслеживания эффективности ICP/MRR/BKA:

```yaml
# Prometheus recording rules
groups:
  - name: mysql_optimizer
    rules:
      # MRR эффективность: отношение random reads к sequential
      - record: mysql:handler_read_rnd_next:rate
        expr: rate(Handler_read_rnd_next[5m])

      # ICP эффективность: снижение Innodb_rows_read
      - record: mysql:innodb_rows_read:rate
        expr: rate(Innodb_rows_read[5m])

      # BKA эффективность: снижение Select_full_join
      - record: mysql:select_full_join:rate
        expr: rate(Select_full_join[5m])

      # Проверка активации в планах запросов
      - record: mysql:queries_using_mrr:rate
        expr: rate(performance_schema_events_statements_summary_by_digest{EXTRA="Using MRR"}[5m])
```

**Алерты:**

```yaml
- alert: MySQLMRRNotUsed
  expr: rate(Handler_read_rnd_next[5m]) > 10000
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "High random I/O on {{ $labels.instance }} — MRR may not be active"

- alert: MySQLBKAEffective
  expr: rate(Select_full_join[5m]) > 0
  for: 5m
  labels:
    severity: info
  annotations:
    summary: "Full joins detected on {{ $labels.instance }} — BKA may reduce load"
```

### Сценарий 7: Edge Cases — когда оптимизатор отказывается использовать механизмы

#### ICP не активируется

**Причины:**
- Условия используют функции: `WHERE YEAR(order_date) = 2026`
- Столбец с NULL и условие `IS NOT NULL` (зависит от версии)
- Storage engine не InnoDB

**Решение:**
```sql
-- Переписать условие без функций
WHERE order_date >= '2026-01-01' AND order_date < '2027-01-01';

-- Проверить тип индекса
SHOW INDEX FROM orders WHERE Key_name != 'PRIMARY';
```

#### MRR не активируется (Using MRR отсутствует)

**Причины:**
- `mrr_cost_based=on` и оптимизатор неверно оценил стоимость
- Range Scan охватывает слишком мало строк (<100)
- `read_rnd_buffer_size` слишком мал для объёма данных

**Решение:**
```sql
-- Принудительное включение на сессию
SET SESSION optimizer_switch='mrr=on,mrr_cost_based=off';

-- Или увеличение буфера
SET SESSION read_rnd_buffer_size = 16M;
```

#### BKA не активируется

**Причины:**
- Внутренняя таблица имеет подходящий индекс (BNLJ или NLJ эффективнее)
- Hash Join выбран (MySQL 8.0.20+)
- `join_buffer_size` слишком мал

**Решение:**
```sql
-- Проверить наличие индекса на поле соединения
SHOW INDEX FROM customers WHERE Column_name = 'id';

-- Принудительное включение BKA
SET SESSION optimizer_switch='batched_key_access=on,mrr=on,mrr_cost_based=off';
```

### Сценарий 8: Сравнение производительности ICP/MRR/BKA

```bash
# Скрипт для сравнения планов до/после
mysql -u root -p -e "
SELECT 'BEFORE' AS stage;
EXPLAIN FORMAT=JSON
SELECT o.id, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.order_date BETWEEN '2026-01-01' AND '2026-01-31'
LIMIT 1000\G

-- Включение механизмов
SET PERSIST optimizer_switch='mrr=on,mrr_cost_based=off,batched_key_access=on,index_condition_pushdown=on';

SELECT 'AFTER' AS stage;
EXPLAIN FORMAT=JSON
SELECT o.id, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.order_date BETWEEN '2026-01-01' AND '2026-01-31'
LIMIT 1000\G
"
```

### Сценарий 9: Настройка в контексте высоконагруженного приложения

```ini
# my.cnf для Production (высокая нагрузка, >16 CPU cores)
[mysqld]
optimizer_switch = "mrr=on,mrr_cost_based=off,batched_key_access=on,index_condition_pushdown=on,hashjoin=on"

# Консервативные буферы для серверов с малым RAM
read_rnd_buffer_size = 2M    # Для Range Scan
join_buffer_size     = 4M    # Для BKA

# Для серверов с большим RAM (>64 GB)
# read_rnd_buffer_size = 8M
# join_buffer_size     = 16M
```

### Сценарий 10: Взаимодействие с connection pooling

При использовании connection pooling (ProxySQL, MaxScale, application-level pool):

```sql
-- Установка optimizer_switch на уровне сессии при подключении
SET SESSION optimizer_switch='mrr=on,mrr_cost_based=off,batched_key_access=on,index_condition_pushdown=on';

-- Проверка, что настройка применилась
SHOW SESSION VARIABLES LIKE 'optimizer_switch';
```

**Важно:** Некоторые пулы сбрасывают сессионные переменные при возврате соединения в пул. Убедитесь, что конфигурация применяется после каждого checkout.

## Диагностика и устранение неисправностей

| Ошибка / симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Using index condition` отсутствует в `Extra` | Условия используют функции или столбцы не из индекса; `type=ALL` | Переписать условия; создать покрывающий индекс |
| `Using MRR` отсутствует | `mrr_cost_based=on`; слишком маленький Range Scan; маленький `read_rnd_buffer_size` | `SET SESSION optimizer_switch='mrr=on,mrr_cost_based=off'`; увеличить буфер |
| `Using join buffer (Batched Key Access)` отсутствует | Внутренняя таблица имеет индекс; Hash Join выбран (8.0.20+); `join_buffer_size` мал | Проверить индексы; увеличить `join_buffer_size`; принудительно включить BKA |
| `EXPLAIN ANALYZE` недоступен | Версия MySQL < 8.0.18 | Использовать `SET profiling = 1` (deprecated) или сравнить планы через `EXPLAIN FORMAT=JSON` |
| План "плывёт" после ANALYZE | Устаревшая статистика; extreme data skew | `ANALYZE TABLE`; создать гистограмму; рассмотреть `condition_fanout_filter=off` |
| Высокий `Handler_read_rnd_next` | MRR не активен; отсутствуют индексы для Range Scan | Проверить `optimizer_switch`; добавить индексы; включить MRR |
| OOM при больших соединениях | Слишком большой `join_buffer_size` × `max_connections` | Уменьшить буферы; использовать `LIMIT`; оптимизировать запросы |
| Hash Join замедляет запрос | Данные не равномерные; `join_buffer_size` недостаточен | Отключить Hash Join: `optimizer_switch='hashjoin=off'`; вернуться к BKA/NLJ |

### Пороги мониторинга (Prometheus)

| Метрика | Порог (warning) | Порог (critical) | Действие |
| :--- | :--- | :--- | :--- |
| `rate(Handler_read_rnd_next[5m])` | > 10 000 | > 50 000 | Проверить активацию MRR; добавить индексы |
| `rate(Select_full_join[5m])` | > 100 | > 1 000 | Проверить индексы для JOIN; включить BKA |
| `rate(Innodb_rows_read[5m])` | > 1M | > 10M | Проверить ICP; оптимизировать условия WHERE |
| `performance_schema_queries_without_using_mrr` | > 10% от общего числа Range Scan | > 30% | Проверить `optimizer_switch` и `read_rnd_buffer_size` |

## Бест-практисы

1. **Используйте ICP/MRR/BKA по умолчанию** в MySQL 8.0+. Они включены по умолчанию и не требуют ручной настройки в большинстве случаев.
2. **Отключайте `mrr_cost_based` только после тестирования.** На системах с SSD или Buffer Pool с высокой hit rate стоимостная модель может быть точной.
3. **Настройте `optimizer_switch` на уровне сессии**, а не глобально, если используется connection pooling. Это позволяет избежать побочных эффектов на другие соединения.
4. **Мониторьте `Handler_read_rnd_next`** — ключевой метрики эффективности MRR. Рост без увеличения нагрузки на приложение указывает на неактивность MRR.
5. **Используйте `EXPLAIN ANALYZE`** для верификации, а не только `EXPLAIN`. План может показывать `Using MRR`, но реальная выгода зависит от размера данных.
6. **Не увеличивайте `read_rnd_buffer_size` и `join_buffer_size` без необходимости.** Они per-connection и умножаются на `max_connections`.
7. **Учитывайте Hash Join** при переходе на MySQL 8.0.20+. Для больших неиндексированных соединений он может заменить BKA.
8. **Обновляйте статистику** после массовых изменений данных. Устаревшая статистика — главная причина неоптимальных планов, включая отказ от ICP/MRR/BKA.
9. **Тестируйте изменения в staging** перед применением в Production. `optimizer_switch` влияет на все запросы.
10. **Документируйте отклонения от defaults.** Если вы отключили `mrr_cost_based` или `batched_key_access`, запишите причину и ожидаемые эффекты.

## Дополнительная информация

### См. также

- **[Обзор MySQL](./overview.md)** — архитектура SQL-слоя.
- **[Конфигурация MySQL](./configuration.md)** — детальный тюнинг буферов и параметров.
- **[Оптимизация запросов: EXPLAIN и Optimizer Hints](./Operations/explain_and_optimization.md)** — анализ планов, hints, диагностика.
- **[Индексы в MySQL](./indexing.md)** — типы индексов, покрывающие индексы, подсказки оптимизатору.
- **[Хранение данных: InnoDB, MyISAM](./Operations/storage_engines_deep_dive.md)** — взаимодействие движка и оптимизатора.
- **[Мониторинг MySQL](./monitoring.md)** — отслеживание метрик производительности.
- **[Диагностика дисковых узких мест](../Concepts/database_performance_concepts.md)** — Random I/O vs Sequential I/O.

### Внешние ресурсы

- **[MySQL 8.4 Reference: Optimizer Switch](https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html#sysvar_optimizer_switch)** — все доступные флаги оптимизатора.
- **[MySQL 8.4 Reference: EXPLAIN ANALYZE](https://dev.mysql.com/doc/refman/8.4/en/explain-analyze.html)** — детальное описание формата вывода.
- **[MySQL 8.4 Reference: Multi-Range Read Optimization](https://dev.mysql.com/doc/refman/8.4/en/mrr-optimization.html)** — официальная документация по MRR.
- **[MySQL 8.4 Reference: Hash Join Optimization](https://dev.mysql.com/doc/refman/8.4/en/hash-join-optimization.html)** — Hash Join в MySQL 8.0.20+.
- **[MySQL 8.4 Reference: Index Condition Pushdown](https://dev.mysql.com/doc/refman/8.4/en/index-condition-pushdown.html)** — официальная документация по ICP.
