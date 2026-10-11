# Миграции схем в PostgreSQL

**Актуально для:** PostgreSQL 11+ / 12+

## Определения

- **Транзакционный DDL** — возможность выполнения команд изменения структуры (Data Definition Language) внутри транзакции. В PostgreSQL почти все DDL-команды атомарны и могут быть откачены в случае сбоя.
- **Очередь блокировок (Lock Queue)** — механизм FIFO, в котором запросы ждут доступа к таблице. Опасность в том, что тяжелая DDL-операция (требующая `ACCESS EXCLUSIVE`) заблокирует все последующие даже легкие `SELECT`, вызывая лавинообразный рост соединений и отказ в обслуживании.
- **Блокировка таблицы (Table Lock)** — механизм предотвращения конфликтов. Большинство DDL-операций требуют `ACCESS EXCLUSIVE`, блокируя даже чтение.
- **Идемпотентность** — свойство миграции, позволяющее запускать её повторно без ошибок (использование `IF NOT EXISTS`, `IF EXISTS`).
- **Zero Downtime Migration** — стратегия изменения схемы без остановки приложения и длительных блокировок.
- **Online Schema Change** — выполнение миграции на «живой» базе данных без эксклюзивной блокировки всей таблицы на время операции.
- **lock_timeout** — параметр сессии, ограничивающий время ожидания получения блокировки.
- **idle_in_transaction_session_timeout** — лимит времени, в течение которого сессия может находиться в состоянии «idle in transaction» (открытая транзакция без выполняемого запроса), что предотвращает удержание блокировок забытыми сессиями.
- **Backfilling** — процесс фонового заполнения новой колонки данными, выполняемый небольшими пачками (batches) для минимизации нагрузки на WAL.

## Базовые концепции

### Транзакционность и ограничения
PostgreSQL гарантирует, что при сбое в середине сложной миграции база не останется в промежуточном состоянии.

**Исключения (команды вне транзакций):**
- `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY`.
- `REINDEX CONCURRENTLY`.
- `VACUUM` и `CLUSTER`.
- `ALTER TYPE ... ADD VALUE` — до PostgreSQL 12 нельзя было выполнять внутри транзакции вообще; начиная с 12 — можно, но новое значение нельзя использовать до коммита этой транзакции. На версиях 11 и старше команда в транзакции падает с ошибкой `ALTER TYPE ... ADD cannot run inside a transaction block`.

### Уровни блокировок DDL-операций
Разные подкоманды `ALTER TABLE` захватывают разные блокировки — от мгновенных до длительных. Знание уровня блокировки позволяет оценить влияние миграции на запись до её запуска:

| Операция | Блокировка | Эффект на таблицу |
| :--- | :--- | :--- |
| `ADD COLUMN` (неконфликтующий `DEFAULT`) | `ACCESS EXCLUSIVE`, кратковременно | Только запись в каталог; перезаписи нет |
| `ADD CONSTRAINT ... CHECK ... NOT VALID` | `ACCESS EXCLUSIVE`, кратковременно | Сканирование пропускается, блокировка удерживается только на время записи в каталог |
| `VALIDATE CONSTRAINT` | `SHARE UPDATE EXCLUSIVE` | Длительный скан, но `INSERT/UPDATE/DELETE` не блокируются |
| `ADD CONSTRAINT ... FOREIGN KEY ... NOT VALID` | `SHARE ROW EXCLUSIVE` на обеих таблицах | Кратко блокирует запись (не `ACCESS EXCLUSIVE`) |
| `ALTER COLUMN ... SET NOT NULL` (PG 12+, есть валидный `CHECK`) | `ACCESS EXCLUSIVE`, мгновенно | Скан пропускается, т.к. `CHECK (col IS NOT NULL)` доказывает отсутствие NULL |
| `CREATE INDEX` | `SHARE` | Блокирует запись на время построения, чтение разрешено |
| `CREATE INDEX CONCURRENTLY` | без эксклюзивных | Два сканирования таблицы, запись разрешена |
| `DROP INDEX CONCURRENTLY` | без эксклюзивных | Запись разрешена |

### Управление блокировками и FIFO
Даже быстрый `ALTER TABLE` может вызвать простой, если он ждет завершения долгого `SELECT`. Очередь блокировок работает по принципу FIFO: эксклюзивная блокировка в очереди заблокирует все последующие запросы, даже если они могли бы выполняться параллельно с текущими.

**Правило безопасности:** всегда устанавливайте `lock_timeout` в сессии миграции. Дополняйте его `statement_timeout` как страховкой от долгого выполнения самой команды:
```sql
SET lock_timeout = '5s';
SET statement_timeout = '30s';
-- Если блокировка не получена за 5 секунд, миграция упадет, не создав очередь
ALTER TABLE users ADD COLUMN bio TEXT;
```

**CD-пайплайн через `PGOPTIONS`:** В CI/CD удобно передавать `lock_timeout` через переменную окружения `PGOPTIONS`, чтобы гарантировать, что ни один `ALTER` не зависнет на долгое время:
```bash
PGOPTIONS="-c lock_timeout=5s" psql -h $DB_HOST -U $DB_USER $DB_NAME \
  -c "ALTER TABLE users ADD COLUMN bio TEXT;"
```
**Важно:** `PGOPTIONS` задействован до подключения и не требует правки каждого SQL-файла миграции — достаточно настроить шаг пайплайна. Подробнее о механизме каскада блокировок — в **[Конкурентности и блокировках](./concurrency_and_locking.md#сценарий-каскад-блокировок-при-миграции-lock-queue-cascade)**.

**Инструменты миграций и транзакции:** Alembic и Flyway по умолчанию оборачивают каждый файл миграции в транзакцию. `SET` в начале файла действует на всю сессию, но `CREATE INDEX CONCURRENTLY` внутри такой транзакции не выполнится — выносите его в отдельный шаг без транзакции (в Alembic — блок `autocommit_block`).

**Перенос read-запросов на реплику:** Долгие аналитические `SELECT`-ы с кучей `JOIN`-ов можно перенести на read-реплику, чтобы не держать `AccessShareLock` на мастере, где выполняются DDL. Учитывайте `replication lag` — для критичных транзакций чтение с реплики недопустимо.

## Предпосылки

Перед запуском миграции в Production:
- **Права:** владелец таблицы для DDL; `pg_repack` требует superuser (или владельца таблицы с ключом `-k`).
- **Расширения:** `pg_repack` установлен (`CREATE EXTENSION pg_repack`), если он нужен для перестроения.
- **Состояние БД:** актуальный проверенный бэкап, лаг репликации в норме, нет долгоживущих транзакций в статусе `idle in transaction` (они удерживают `AccessShareLock` и превращают кратковременную DDL-блокировку в каскад).
- Полный чек-лист pre-flight (бэкапы, пулы соединений, CAB, runbook) — в **[Лучшие практики миграций](../../Concepts/migrations/migration_practices.md#предпосылки-и-подготовка)**.

## Практические сценарии

### 1. Добавление колонок (PostgreSQL 11+)
Начиная с версии 11, добавление колонки с дефолтным значением (`DEFAULT`) выполняется мгновенно без перезаписи таблицы — значение сохраняется в каталоге и подставляется при чтении старых строк.

```sql
-- Выполняется мгновенно даже на миллиардах строк
ALTER TABLE orders ADD COLUMN internal_comment TEXT DEFAULT 'none';
```

**Исключения (перезаписывают таблицу и индексы):**
- `DEFAULT` с volatile-функцией (`clock_timestamp()`, `random()`) — значение должно быть вычислено для каждой строки;
- хранимые generated-колонки (`GENERATED ALWAYS AS ... STORED`), identity-колонки (`GENERATED AS IDENTITY`), колонки доменного типа с ограничениями.

**Обходной путь:** добавить колонку без `DEFAULT`, заполнить её батчами (рецепт — в **[Сценарий 2: Пакетная миграция данных](../../Concepts/migrations/scenarios.md#сценарий-2-пакетная-миграция-данных-batch-data-migration)**), затем установить `DEFAULT` через `ALTER COLUMN ... SET DEFAULT` — эта команда мгновенна и не затрагивает существующие строки.

### 2. Безопасное управление ограничениями (Constraints)
Добавление `NOT NULL` или `FOREIGN KEY` на большие таблицы вызывает полный скан таблицы. Безопасный путь — добавить ограничение как `NOT VALID`, затем валидировать.

**Версии:** `NOT VALID` для `CHECK` и `FOREIGN KEY` работает начиная с PostgreSQL 9.1; мгновенный `SET NOT NULL` (без сканирования) — начиная с PostgreSQL 12.

```sql
-- Шаг 1: мгновенно, ACCESS EXCLUSIVE удерживается только на запись каталога
ALTER TABLE orders ADD CONSTRAINT orders_amount_not_null 
CHECK (amount IS NOT NULL) NOT VALID;

-- Шаг 2: длительный скан, но SHARE UPDATE EXCLUSIVE — запись не блокируется
ALTER TABLE orders VALIDATE CONSTRAINT orders_amount_not_null;

-- Шаг 3: мгновенно в PG 12+ — скан пропускается, т.к. валидный CHECK доказывает отсутствие NULL
ALTER TABLE orders ALTER COLUMN amount SET NOT NULL;
```

**FOREIGN KEY:** `ADD FOREIGN KEY ... NOT VALID` требует только `SHARE ROW EXCLUSIVE` (а не `ACCESS EXCLUSIVE`), но захватывает его и на ссылающейся, и на ссылуемой таблице — запись блокируется на время команды. Валидация длится долго на больших таблицах, но не блокирует запись.

**Валидация:**
```sql
SELECT conname, convalidated FROM pg_constraint WHERE conrelid = 'orders'::regclass;
-- convalidated = true для всех новых ограничений
```

### 3. Изменение типа колонки или переименование
Операция `ALTER COLUMN TYPE` обычно вызывает перезапись таблицы (Rewriting).

**Исключение:** перезаписи нет, если `USING` не меняет содержимое колонки, а старый тип бинарно приводим к новому (или является неограниченным доменом над ним).

**Безопасный путь (Expand-Contract):**
1. Создать новую колонку с нужным типом (`col_new`).
2. Настроить триггер для копирования данных из `col_old` в `col_new` при записи.
3. Фоново перелить исторические данные (Batching).
4. Переключить код приложения на `col_new`.
5. Удалить `col_old`.

Детальная методология — в **[Обратно-совместимых миграциях (Expand-Contract)](../../Concepts/migrations/expand_contract.md)**.

### 4. Онлайн-перестраивание таблиц (pg_repack)
Когда нужно устранить раздувание (Bloat) или изменить структуру, требующую перезаписи, без остановки записи.
- **Инструмент:** `pg_repack`. Создает копию таблицы в фоне, синхронизирует изменения через триггеры и подменяет её в конце операции.
- **Требования:** таблица должна иметь `PRIMARY KEY` или `UNIQUE`-индекс на `NOT NULL`-колонке; свободное место ≈ 2× от размера таблицы с индексами; права superuser (или владелец таблицы с ключом `-k`).
- **Блокировки:** во время работы удерживается `ACCESS SHARE` (разрешены `SELECT`, запрещены DDL кроме `VACUUM`/`ANALYZE`); краткий `ACCESS EXCLUSIVE` — только на финальный swap. После перестроения `pg_repack` выполняет `ANALYZE`.
- Детали и примеры — в **[Борьба с раздуванием (Bloat) и pg_repack](../Operations/performance_tuning.md#сценарий-5-борьба-с-раздуванием-bloat-и-pg_repack)**; нативная альтернатива `REPACK CONCURRENTLY` в PostgreSQL 19 — в **[Внутренности VACUUM](./vacuum_internals.md)**.

### 5. Работа с индексами
- **Построение:** используйте `CONCURRENTLY`. Выполняется в два сканирования таблицы с ожиданием завершения открытых транзакций; запрещено в транзакциях и на секционированных таблицах (для секционированных — строите по секциям, затем создаёте индекс корня обычным способом). Только один конкурентный индекс может строиться на таблице одновременно.
- **Инвалидация:** если построение прервалось (deadlock, нарушение уникальности), индекс останется `INVALID`. Его нужно удалить (`DROP INDEX CONCURRENTLY`) и создать заново; альтернатива — `REINDEX INDEX CONCURRENTLY`.
- **Перестроение:** `REINDEX INDEX CONCURRENTLY`.
- **`DROP INDEX CONCURRENTLY`:** доступен с PostgreSQL 9.2; поддерживает только один индекс за раз, не поддерживает `CASCADE` (нельзя удалить индекс, поддерживающий `UNIQUE`/`PRIMARY KEY`), не работает в транзакции и на секционированных таблицах.

**Поиск невалидных индексов:**
```sql
SELECT c.relname AS table_name, ic.relname AS index_name
FROM pg_index i
JOIN pg_class c ON c.oid = i.indrelid
JOIN pg_class ic ON ic.oid = i.indexrelid
WHERE NOT i.indisvalid;
```

### 6. Идентичность и последовательности (Identity Columns)
В новых версиях (PG 10+) рекомендуется использовать `GENERATED AS IDENTITY` вместо `SERIAL` для лучшей совместимости со стандартом SQL и интеграции с правами доступа.

**Миграции и репликация:** последовательности не реплицируются логической репликацией — при switchover на подписчика их значения нужно синхронизировать вручную (либо использовать нативную репликацию последовательностей, доступную с PostgreSQL 19 — см. **[Миграция PostgreSQL без простоя](../Operations/zero_downtime_migration.md)**).

### 7. Миграции и логическая репликация
Встроенная логическая репликация **не реплицирует DDL**.
- Изменения схемы применяются вручную. Расширяющие (additive) изменения безопасно применять сначала на подписчике (Subscriber), затем на издателе (Publisher) — так избегаются перебойные ошибки, когда реплицируемые данные не помещаются в текущую схему подписчика.
- Несовпадение схем приведет к ошибкам репликации до тех пор, пока схема не будет приведена в соответствие.
- Large objects (`lo`) не реплицируются вовсе — храните такие данные в обычных таблицах.
- Полный процесс переезда между мажорными версиями — в **[Миграции PostgreSQL без простоя](../Operations/zero_downtime_migration.md)**.

## Диагностика и обслуживание

### Поиск блокирующих транзакций
Если миграция "висит", найдите PID блокирующего процесса:
```sql
SELECT pid, state, query, age(now(), query_start) AS duration
FROM pg_stat_activity 
WHERE wait_event_type = 'Lock';
```

**Кто кого блокирует:**
```sql
SELECT blocked.pid AS blocked_pid, blocked.query AS blocked_query,
       blocking.pid AS blocking_pid, blocking.state AS blocking_state,
       blocking.query AS blocking_query
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked ON blocked.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks
  ON blocking_locks.locktype = blocked_locks.locktype
 AND blocking_locks.relation = blocked_locks.relation
 AND blocking_locks.pid <> blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking ON blocking.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```
Завершение блокирующей сессии: `SELECT pg_terminate_backend(<blocking_pid>);`

### Обслуживание после миграции
После массового изменения данных выполните `ANALYZE` для актуализации статистики планировщика.
```sql
ANALYZE VERBOSE users;
```
Для expression-индексов статистика появится только после `ANALYZE` (или после работы autovacuum). Проверьте отсутствие невалидных индексов и `convalidated = true` у новых ограничений; убедитесь, что autovacuum вернулся в нормальный режим после массовых DML.

## Устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `canceling statement due to lock timeout` | Таблица занята долгим запросом или `idle in transaction` | Повторить в окно низкой нагрузки; найти и завершить блокирующую сессию (`pg_terminate_backend`) |
| `CREATE INDEX CONCURRENTLY cannot run inside a transaction block` | CIC внутри транзакции (инструмент миграций) | Вынести в отдельный шаг без транзакции |
| `DROP INDEX CONCURRENTLY cannot run inside a transaction block` | То же для удаления индекса | То же |
| `ALTER TYPE ... ADD cannot run inside a transaction block` | `ALTER TYPE ADD VALUE` в транзакции на PG ≤ 11 | Обновить PostgreSQL до 12+ или выполнять команду вне транзакции |
| Индекс отображается как `INVALID` | Прерванное `CREATE INDEX CONCURRENTLY` | `DROP INDEX CONCURRENTLY` и пересоздание (или `REINDEX INDEX CONCURRENTLY`) |
| Ошибки репликации после DDL | Схема подписчика не обновлена | Применить DDL на подписчике, затем на издателе; перезапустить подписку |
| `pg_repack` отказывается работать с таблицей | Нет `PRIMARY KEY` или `UNIQUE`-индекса на `NOT NULL`-колонке | Создать такой индекс |

## Лучшие практики (DevOps/SRE)

1. **DDL и DML раздельно**: Не смешивайте изменение структуры и обновление данных в одной транзакции/файле.
2. **Lock Timeout везде**: Без него любой `ALTER` — это риск DoS всей базы данных. Дополняйте `statement_timeout`.
3. **Обратная совместимость**: Код версии N должен работать со схемой N+1 (Expand-Contract).
4. **Малые пачки (Batches)**: При обновлении миллионов строк делайте `COMMIT` каждые 5000-10000 строк.
5. **Проверка на Stage**: Тестируйте миграции на копии продакшена для оценки времени блокировок.
6. **Fix-Forward вместо отката**: Откат DML-части часто невозможен — применяйте компенсирующую миграцию (см. **[Стратегии отката](../../Concepts/migrations/rollback_strategies.md)**).

Общая методология (именование файлов, CAB, quality gates в CI/CD, изоляция прав CI-пользователя) — в **[Лучшие практики миграций](../../Concepts/migrations/migration_practices.md)**.

## Дополнительная информация

### Инструменты и линтинг
- **Squawk**: Линтер SQL для PostgreSQL, обнаруживает опасные операции (`ALTER` без `CONCURRENTLY`, добавление `NOT NULL` без `DEFAULT` и т.п.).
- **Strong Migrations**: Линтер (Ruby/Rails), обнаруживающий опасные операции (переименования без триггеров и т.д.).
- **Alembic**: Стандарт для Python/SQLAlchemy.
- **Atlas / Flyway / Liquibase**: Автоматизация и контроль версий — подробнее в **[Flyway: Практическое руководство](../../Concepts/migrations/tools/flyway_practical_guide.md)** и **[Liquibase: Практическое руководство](../../Concepts/migrations/tools/liquibase_practical_guide.md)**.

### Смежные темы
- **[Конкурентность и блокировки](./concurrency_and_locking.md)** — глубокий разбор уровней и каскад блокировок.
- **[Миграция без простоя (версии)](../Operations/zero_downtime_migration.md)** — переезд между мажорными версиями.
- **[Обратно-совместимые миграции (Expand-Contract)](../../Concepts/migrations/expand_contract.md)** — детальная стратегия.
- **[Типовые сценарии миграций](../../Concepts/migrations/scenarios.md)** — практические рецепты, включая батчинг.
- **[Безопасные массовые операции](../../Concepts/safe_large_scale_data_modification.md)** — батчинг и лимиты.
- **[Индексы](./indexes.md)** — CIC и перестроение индексов.
