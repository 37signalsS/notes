# ClickHouse — Эволюция схемы и ALTER TABLE

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Schema evolution** — изменение структуры таблицы (добавление/удаление/изменение колонок, ограничений, настроек) без потери данных и, в идеале, без простоя.

**DEFAULT** — выражение по умолчанию: вычисляется при `INSERT`, если колонка не указана явно. Значение сохраняется на диске.

**MATERIALIZED** — выражение, вычисляемое при вставке и всегда хранимое на диске. Нельзя указать в `INSERT`, не показывается в `SELECT *`.

**EPHEMERAL** — эфемерная колонка: не хранится, прочитать её нельзя (`SELECT` недоступен). Единственное назначение — участвовать в выражениях `DEFAULT`/`MATERIALIZED` других колонок.

**ALIAS** — вычисляемая колонка: не хранится, значение вычисляется в момент чтения при явном обращении. Нельзя вставить значение, исключена из `SELECT *` (если не включён `asterisk_include_alias_columns`).

**MATERIALIZE COLUMN** — операция перезаписи существующих данных колонки после изменения её `DEFAULT`/`MATERIALIZED`-выражения.

**Мутация (Mutation)** — асинхронная фоновая операция перезаписи данных parts (`ALTER TABLE ... UPDATE/DELETE/MATERIALIZE ...`). Для MergeTree таблиц перезаписывает целые parts.

**Code 517 (`CANNOT_ASSIGN_ALTER`)** — retryable-ошибка гонки при одновременных метаданных-`ALTER` на реплике; лечится повторной отправкой или объединением операций в один `ALTER`.

**mutations_concurrency** — настройка количества параллельных воркеров мутаций (server-level). Увеличивается для ускорения stuck мутаций при достаточном I/O.

**alter_sync** — настройка синхронизации `ALTER`/`OPTIMIZE`/`TRUNCATE` на репликах: `0` (не ждать), `1` (ждать свою), `2` (ждать всех), `3` (ждать только активных). Cloud default: `0`. Alias: `replication_alter_partitions_sync`.

**mutations_sync** — настройка синхронизации мутаций (`UPDATE`, `DELETE`, `MATERIALIZE ...`): `0` (асинхронно), `1` (ждать на текущем сервере), `2` (ждать на всех репликах), `3` (ждать только активных). Default: `0`.

**alter_update_mode** — режим `ALTER TABLE ... UPDATE` (начиная с 25.5): `heavy` (стандартный мутационный), `lightweight` (lightweight update при возможности), `lightweight_force` (lightweight update, иначе исключение). Default: `heavy`.

## Основные концепции

### Типы колонок: что где хранится

| Модификатор | Хранение | INSERT | SELECT * | Вычисление |
| :--- | :--- | :--- | :--- | :--- |
| `DEFAULT expr` | На диске | Если не указана — вычисляется | Да | При вставке |
| `MATERIALIZED expr` | На диске | Нельзя указать | Нет | При вставке |
| `EPHEMERAL [expr]` | Не хранится | Пропускается | Нет | При вставке (для других колонок) |
| `ALIAS expr` | Не хранится | Нельзя указать | Нет | При чтении |

**Почему это важно для продакшена:**
- `MATERIALIZED` и `ALIAS` не занимают места на диске (кроме `MATERIALIZED`, который хранит результат).
- `ALIAS` вычисляется при каждом чтении — дорого для частых запросов; `MATERIALIZED` вычисляется один раз при вставке.
- `EPHEMERAL` полезна как промежуточное значение для вычисления других колонок (например, сырое поле, из которого выводятся несколько производных).

### Как работает ALTER TABLE

- **Метаданные-операции** (`ADD COLUMN`, `DROP COLUMN`, `ADD INDEX`, `ADD CONSTRAINT`, `MODIFY SETTING`, `COMMENT COLUMN`) — мгновенные: меняют только метаданные, данные не перезаписываются.
- **Старые данные**: при `ADD COLUMN` старые части не перезаписываются — для старых строк колонка читается как значение по умолчанию (вычисляется на лету). Чтобы зафиксировать значение на диске, используйте `MATERIALIZE COLUMN`.
- **`MODIFY COLUMN`** (смена типа) — тяжёлая операция: перезаписывает данные всех частей через мутацию (`READ_COLUMN`).
- **`ALTER TABLE ... UPDATE/DELETE`** — мутации, перезаписывающие целые parts. Асинхронны по умолчанию; синхронизация через `mutations_sync`.
- **Репликация**: метаданные `ALTER` и мутации транслируются через Keeper/ZooKeeper на все реплики автоматически. `alter_sync`/`mutations_sync` управляют ожиданием.

### Синхронизация и DDL-coordinator

В кластере `ALTER` проходит через DDL-координатор (`distributed_ddl`). Настройки управления синхронизацией:

```xml
<!-- config.xml -->
<clickhouse>
    <distributed_ddl>
        <ddl_queue_update_level>0</ddl_queue_update_level>
        <!-- alter_sync и mutations_sync задаются как session settings -->
    </distributed_ddl>
</clickhouse>
```

```sql
-- Синхронный ALTER на всех репликах (metadata)
SET alter_sync = 2;
ALTER TABLE logs ADD COLUMN host_name String DEFAULT '';
-- # → ALTER 24056

-- Синхронный мутационный ALTER (wait = 30s timeout)
SET mutations_sync = 2;
ALTER TABLE logs MATERIALIZE COLUMN level_low;
-- # → ALTER 24057
```

### Порядок операций при эволюции схемы

1. Сначала `ALTER TABLE ... ADD COLUMN` в ClickHouse (новая колонка появится со значениями по умолчания).
2. Затем — в источнике (PostgreSQL, Kafka-схема и т. д.).
3. При использовании CDC (Debezium, PeerDB) удаление колонок или смена типов обычно требуют остановки репликации или пересоздания Mirror.
4. Для `MaterializedPostgreSQL` — `DETACH TABLE ... PERMANENTLY` / `ATTACH TABLE` для синхронизации схемы.

## Предпосылки (Prerequisites)

| Требование | Минимум | Примечание |
| :--- | :--- | :--- |
| Версия ClickHouse | 24.3+ (LTS) | On-disk query cache и `alter_update_mode` требуют 25.3+ |
| Кластер | Standalone или кластер с Keeper | DDL координация через `distributed_ddl` |
| Права | `ALTER TABLE` на целевую таблицу | Для `KILL MUTATION` — `KILL QUERY`/`SYSTEM` privileges |
| Резервная копия | `clickhouse-backup` или `FREEZE` | Обязательна перед `MODIFY COLUMN` и `DROP COLUMN` |
| Мониторинг | `system.mutations`, `system.processes` | Алерт на застрявшие мутации (>60 мин) |

## Практические сценарии

### Добавление и удаление колонок

```sql
-- Добавить колонку (мгновенно, метаданные)
ALTER TABLE logs ADD COLUMN host_name String DEFAULT '';

-- Добавить колонку с MATERIALIZED-выражением
ALTER TABLE logs ADD COLUMN level_low LowCardinality(String) MATERIALIZED lowerUTF8(level);

-- Удалить колонку (мгновенно; данные удаляются при следующих слияниях)
ALTER TABLE logs DROP COLUMN host_name;

-- Перезаписать данные колонки после изменения выражения
ALTER TABLE logs MATERIALIZE COLUMN level_low;

-- Сменить тип колонки (тяжело: перезапись всех частей)
ALTER TABLE logs MODIFY COLUMN event_time DateTime64(3);

-- Комментарий к колонке
ALTER TABLE logs COMMENT COLUMN level 'Уровень логирования';
```

### Колонки DEFAULT / MATERIALIZED / EPHEMERAL / ALIAS

```sql
CREATE TABLE events
(
    event_time DateTime,
    raw_message String,
    -- EPHEMERAL: не хранится, служит входом для других выражений
    message_parts Array(String) EPHEMERAL,
    -- MATERIALIZED: вычисляется при вставке и хранится
    level LowCardinality(String) MATERIALIZED arrayElement(message_parts, 1),
    -- ALIAS: вычисляется при чтении
    level_upper String ALIAS upper(level),
    -- DEFAULT: вычисляется при вставке, если не указана
    source String DEFAULT 'unknown'
)
ENGINE = MergeTree()
ORDER BY (level, event_time);

-- Проверка типов колонок
SELECT name, type, default_kind, default_expression
FROM system.columns
WHERE table = 'events';
```

### Ограничения (CHECK / ASSUME)

```sql
-- CHECK: проверяется при INSERT (нарушение — ошибка вставки)
ALTER TABLE sales ADD CONSTRAINT revenue_positive CHECK (revenue >= 0);

-- ASSUME: оптимизатор доверяет условию без проверки (ускоряет план)
ALTER TABLE sales ADD CONSTRAINT date_not_future ASSUME event_date <= today();

-- Изменить / удалить
ALTER TABLE sales MODIFY CONSTRAINT revenue_positive CHECK (revenue > 0);
ALTER TABLE sales DROP CONSTRAINT revenue_positive;
```

**Важно:** проверка `CHECK` **не выполняется** на уже существующих данных при добавлении ограничения — только на новых вставках. Для валидации старых данных используйте отдельный запрос:

```sql
-- Найти строки, нарушающие ограничение (до его добавления)
SELECT count() FROM sales WHERE revenue < 0;
```

**Ограничения** могут быть объявлены при создании или добавлены через `ALTER TABLE ... ADD CONSTRAINT`. `CHECK` проверяется при вставке, `ASSUME` доверяется оптимизатору. Ограничения реплицируются через Keeper на все реплики.

### Изменение настроек таблицы

```sql
-- Изменить настройку MergeTree
ALTER TABLE logs MODIFY SETTING parts_to_delay_insert = 2000;

-- Сбросить к глобальному дефолту
ALTER TABLE logs RESET SETTING parts_to_delay_insert;

-- Посмотреть текущие значения всех MergeTree-настроек
SELECT name, value FROM system.merge_tree_settings;
```

**Важно:** `ALTER TABLE ... MODIFY SETTING` применяется **только к MergeTree-family** таблицам.

### Lightweigh update (ALTER TABLE ... UPDATE, 25.5+)

```sql
-- heavy mode (default): стандартный мутационный UPDATE
ALTER TABLE logs UPDATE severity = 'WARN' WHERE severity = 'WARNING';

-- lightweight mode: запись в patch parts (быстрее на wide частях)
SET alter_update_mode = 'lightweight';
ALTER TABLE logs UPDATE severity = 'WARN' WHERE severity = 'WARNING';

-- force: lightweight, иначе исключение
SET alter_update_mode = 'lightweight_force';
```

### Комбинирование операций в одном ALTER

```sql
-- Несколько независимых метаданных-операций за один запрос
ALTER TABLE logs
    ADD COLUMN host_name String DEFAULT '',
    ADD INDEX idx_host host_name TYPE bloom_filter(0.01) GRANULARITY 4,
    MODIFY SETTING index_granularity = 8192;
```

При гонке метаданных-`ALTER` на реплике (`CANNOT_ASSIGN_ALTER`, Code 517) — повторите запрос; независимые операции можно объединять в один многоклаузный `ALTER`.

## Мониторинг и DevOps/SRE

### Система мутаций

```sql
-- Активные мутации
SELECT database, table, mutation_id, command, create_time,
       parts_to_do, is_done
FROM system.mutations
WHERE database = 'default' AND is_done = 0
ORDER BY create_time;

-- С длительностью исполнения
SELECT mutation_id, command,
       formatReadableTimeDelta(now() - create_time) AS running_for,
       parts_to_do
FROM system.mutations
WHERE is_done = 0
ORDER BY running_for DESC;

-- Ошибки мутаций
SELECT mutation_id, latest_failed_part, latest_fail_reason,
       latest_fail_error_code_name
FROM system.mutations
WHERE is_done = 0 AND latest_fail_reason != '';

-- Алерт: застрявшие мутации (>60 минут)
SELECT count()
FROM system.mutations
WHERE is_done = 0 AND create_time < now() - INTERVAL 60 MINUTE;
```

**Колонки `system.mutations`** (полнйй список): `database`, `table`, `mutation_id`, `command`, `create_time`, `finish_time`, `block_numbers.partition_id`, `block_numbers.number`, `parts_in_progress_names`, `parts_to_do_names`, `parts_to_do`, `parts_postpone_reasons`, `is_done`, `is_killed` (Cloud), `latest_failed_part`, `latest_fail_time`, `latest_fail_reason`, `latest_fail_error_code_name`.

### Управление мутациями

```sql
-- Принудительное удаление мутации
KILL MUTATION WHERE database = 'default' AND table = 'logs';

-- Точное удаление
KILL MUTATION WHERE database = 'default' AND table = 'logs' AND mutation_id = 'mutation_3';

-- Остановка всех мутаций (только для исправления, не для планового использования)
SYSTEM STOP MERGES logs;
-- ... исправление ...
SYSTEM START MERGES logs;
```

### Синхронизация DDL в кластере

```sql
-- Ждать завершения мутации на всех репликах
SET mutations_sync = 2;
ALTER TABLE logs MATERIALIZE COLUMN level_low;

-- Ждать метаданных ALTER на всех репликах (Cloud default = 0)
SET alter_sync = 2;
ALTER TABLE logs ADD COLUMN host_name String DEFAULT '';

-- DDL через координатор (ON CLUSTER)
ALTER TABLE logs ADD COLUMN host_name String DEFAULT '' ON CLUSTER 'all_cluster';
```

## Операции и команды

| Операция | Команда | Асинхронность | Синхронизация | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| ADD COLUMN | `ALTER TABLE ... ADD COLUMN` | Метаданные | `alter_sync` | Мгновенно |
| DROP COLUMN | `ALTER TABLE ... DROP COLUMN` | Метаданные + фоновая очистка | `alter_sync` | Данные удаляются в merge |
| MODIFY COLUMN (тип) | `ALTER TABLE ... MODIFY COLUMN` | Мутация (`READ_COLUMN`) | `alter_sync` | Перезапись всех parts |
| UPDATE | `ALTER TABLE ... UPDATE` | Мутация | `mutations_sync` | Перезапись parts |
| DELETE | `ALTER TABLE ... DELETE` | Мутация | `mutations_sync` | Перезапись parts |
| MATERIALIZE COLUMN | `ALTER TABLE ... MATERIALIZE COLUMN` | Мутация | `mutations_sync` | Перезапись данных |
| MATERIALIZE INDEX | `ALTER TABLE ... MATERIALIZE INDEX` | Мутация | `mutations_sync` | Перезапись parts |
| ADD/DROP CONSTRAINT | `ALTER TABLE ... ADD/DROP CONSTRAINT` | Метаданные | `alter_sync` | Мгновенно |
| MODIFY SETTING | `ALTER TABLE ... MODIFY SETTING` | Метаданные | `alter_sync` | Только MergeTree |
| KILL MUTATION | `KILL MUTATION WHERE ...` | Синхронный | — | Отмена мутации |
| STOP/START MERGES | `SYSTEM STOP/START MERGES` | Синхронный | — | Управление фоновыми merge |

## Валидация

```sql
-- 1. Проверить, что колонка добавлена
SELECT name, type, default_kind, default_expression
FROM system.columns
WHERE database = 'default' AND table = 'logs' AND name = 'host_name';
-- # → host_name | String | DEFAULT | ''

-- 2. Проверить, что ограничения применены
SELECT name, type, kind, expr
FROM system.constraints
WHERE database = 'default' AND table = 'logs';

-- 3. Проверить, что все мутации завершились
SELECT count() AS pending_mutations
FROM system.mutations
WHERE database = 'default' AND table = 'logs' AND is_done = 0;
-- # → 0

-- 4. Проверить, что изменение колонки применилось ко всем parts
SELECT count() AS parts_without_column
FROM system.parts
WHERE database = 'default' AND table = 'logs'
  AND column_names_without_sensitive IS DISTINCT FROM 'host_name';

-- 5. Проверить, что запросы работают корректно
SELECT count() FROM logs WHERE host_name = 'app-server-01';
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Code 517` (`CANNOT_ASSIGN_ALTER`) при ALTER | Гонка одновременных метаданных-`ALTER` на реплике | Повторить запрос; объединить операции в один `ALTER` |
| Новая колонка пуста для старых данных | `ADD COLUMN` не перезаписывает старые части | `ALTER TABLE ... MATERIALIZE COLUMN col` |
| `MATERIALIZED`-колонка не в `SELECT *` | Так работает спецификация | Обратиться к колонке явно; `asterisk_include_materialized_columns=1` |
| `ALIAS`-колонка медленная | Вычисляется при каждом чтении | Перевести в `MATERIALIZED`, если вычисление дорогое |
| `MODIFY COLUMN` зависла | Перезапись всех частей на больших таблицах | Мониторить `system.mutations`; при необходимости `KILL MUTATION` |
| `INSERT` не принимает MATERIALIZED-колонку | MATERIALIZED нельзя указывать в INSERT | Убрать колонку из списка вставки |
| CDC сломался после DDL | Ломающий DDL (тип/столбцы) | `DETACH TABLE ... PERMANENTLY`, синхронизировать схему, `ATTACH TABLE` |
| Мутация висит > 60 мин | Конкуренция за I/O или диск заполнен | Проверить `system.mutations`, `parts_to_do`; увеличить `mutations_concurrency`; при необходимости `KILL MUTATION` |
| `ALTER TABLE ... UPDATE` медленно | Heavy mode rewrite; high background load | `SET alter_update_mode = 'lightweight'` (с 25.5) |
| `DROP COLUMN` не освобождает место | Данные удаляются только при merge | `OPTIMIZE TABLE ... FINAL` для принудительного merge; проверить `system.parts` |

## Лучшие практики

1. **Добавляйте колонки через `ADD COLUMN`** — это мгновенная метаданные-операция, безопасная для продакшена.
2. **`MATERIALIZED` вместо `ALIAS`** для вычислений, которые нужны в каждом запросе: вычисление один раз при вставке дешевле, чем при каждом чтении.
3. **`EPHEMERAL`** для промежуточных значений, которые не нужны в запросах, но нужны для вычисления других колонок.
4. **`CHECK`-ограничения** добавляйте до начала потока данных — они не валидируют существующие данные.
5. **`MATERIALIZE COLUMN`** запускайте в off-peak: это перезапись данных.
6. **`MODIFY COLUMN` (смена типа)** планируйте как отдельную операцию обслуживания на больших таблицах.
7. **Синхронизация в кластере:** используйте `alter_sync = 2` для метаданных и `mutations_sync = 2` для мутаций в средах, где consistency критична.
8. **Мониторинг:** алерт на `system.mutations WHERE is_done = 0 AND create_time < now() - 60 MINUTE`.
9. **Резервные копии** перед `MODIFY COLUMN`, `DROP COLUMN`, `MATERIALIZE COLUMN`.
10. **Объединяйте операции** в один многоклаузный `ALTER` для снижения вероятности `CANNOT_ASSIGN_ALTER`.
11. **Lightweigh update** (`alter_update_mode = 'lightweight'`, с 25.5): используйте для UPDATE на wide таблицах с высокой нагрузкой.

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- Движки семейства MergeTree — **[Архитектура](./clickhouse-architecture.md)**.
- Мутации и lightweight delete — **[Операционный SQL](./clickhouse-sql-operations.md)**.
- Мониторинг мутаций — **[Мониторинг](./clickhouse-monitoring.md)**.
- Настройка DDL координатора и репликация — **[Кластерное управление](./clickhouse-cluster.md)**.
- Интеграция PostgreSQL (CDC, MaterializedPostgreSQL) — **[Интеграция PostgreSQL и ClickHouse](../PostgreSQL/Integrations/clickhouse.md)**.
- Data modeling patterns (constraints at CREATE) — **[Моделирование данных](./clickhouse-data-modeling.md)**.

### Ресурсы

- [Документация: ALTER](https://clickhouse.com/docs/reference/statements/alter)
- [Документация: ALTER TABLE ... CONSTRAINT](https://clickhouse.com/docs/reference/statements/alter/constraint)
- [Документация: CREATE TABLE (колонки)](https://clickhouse.com/docs/reference/statements/create/table)
- [Настройки мутаций (mutations_sync)](https://clickhouse.com/docs/reference/settings/session-settings/mutations)
- [Настройки ALTER (alter_sync)](https://clickhouse.com/docs/reference/settings/session-settings/alter#alter_sync)
- [system.mutations](https://clickhouse.com/docs/reference/system-tables/mutations)
- [KILL MUTATION](https://clickhouse.com/docs/reference/statements/kill#kill-mutation)
