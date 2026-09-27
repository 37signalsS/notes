# PostgreSQL для памяти ИИ-агентов

## Предпосыки и версионность

Перед развертыванием PostgreSQL как хранилища памяти ИИ-агента проверяют соответствующую версию и базовую конфигурацию:

- **Рекомендуемая версия PostgreSQL:** 16–18. Версии 16 и выше поддерживают параллельное применение изменений в логической репликации, улучшенное логическое декодирование и расширенные инструменты диагностики. PostgreSQL 18 добавляет нативное Asynchronous I/O (AIO), `autovacuum_vacuum_max_threshold`, расширения для TID-хранилища и улучшения при логическом декодировании WAL.
- **Расширения:** `pgvector` (векторный поиск), `pg_partman` (автоматическое партиционирование), `pg_repack` (онлайн-пересборка при измеренной необходимости), `pg_stat_statements` (статистика запросов).
- **Конфигурация ядра ОС:** `vm.swappiness = 1–10`, `vm.overcommit_memory = 2`, монтирование ФС с опциями `noatime, nodiratime`. Подробный чек-лист — в **[Оптимизации производительности PostgreSQL](./performance_tuning.md)**.
- **Пул соединений:** при количестве одновременных клиентских сессий более 100–200 рекомендуется PgBouncer в режиме transaction pooling. Детали — в **[Настройке PgBouncer](./pgbouncer_setup.md)** и **[Управлении соединениями](./connection_management.md)**.
- **Резервное копирование:** агентская память содержит состояния, которые нельзя терять. Настройте автоматизированные бэкапы (логические через `pg_dump` или физические через `pgBackRest`) и проверяйте их восстановление. Подробнее — в **[Автоматизации резервного копирования](./backup_automation.md)** и **[Теории бэкапов и восстановления](../Concepts/backup_and_recovery.md)**.
- **Высокая доступность:** для production-развертываний агентской памяти используйте синхронную или квазисинхронную репликацию (Patroni/etcd или ванильную Streaming Replication). При сбое primary должна быть возможность быстрого failover без потери checkpoint. Детали — в **[Отказоустойчивом кластере (Patroni)](./high_availability_patroni.md)** и **[Репликации](../Concepts/replication.md)**.

## Назначение и границы применения

PostgreSQL подходит для реляционной части памяти ИИ-агента: состояния графа, истории диалога, фактов о пользователе, задач и служебных событий. При этом разные таблицы имеют разные профили нагрузки, поэтому настройки хранения, очистки и индексации нужно задавать отдельно для каждой таблицы.

**Проверенная модель LangGraph:**

- **Checkpointer** хранит снимки состояния одного thread. Это краткосрочная, ограниченная одним диалогом память, необходимая для продолжения разговора, human-in-the-loop, time travel и восстановления после сбоя.
- **Store** хранит прикладные данные в формате ключ-значение вне состояния графа. Это долгосрочная память, доступная между thread: предпочтения пользователя, извлеченные факты и общие знания.
- Большинство приложений используют оба механизма: checkpointer для текущего thread и store для данных, которые должны переживать отдельный запуск графа.

PostgreSQL не следует автоматически превращать в универсальное хранилище для всей телеметрии, аналитики, векторного поиска и больших бинарных артефактов. Эти нагрузки конкурируют за `shared_buffers`, WAL, процессор, дисковый ввод-вывод и `autovacuum`. При росте объема или задержек их выделяют в отдельный инстанс или специализированную систему.

## Модель данных и профиль нагрузки

| Компонент | Типичные данные | Преобладающая операция | Основные риски |
| :--- | :--- | :--- | :--- |
| LangGraph checkpointer | Снимки состояния, версии каналов, промежуточные записи | `INSERT`, периодическое удаление по retention | Неограниченный рост, большие `jsonb`/BLOB, TOAST, WAL |
| LangGraph store | Факты и пользовательские данные в формате ключ-значение | `INSERT` и частые `UPDATE` | Dead tuples, bloat, потеря HOT при индексации обновляемых полей |
| Очередь задач | Задача, статус, попытка, срок видимости, результат | `INSERT`, `UPDATE status`, `DELETE` | Блокировки, повторная доставка, рост частичного индекса |
| Телеметрия и traces | Спаны, токены, latency, метаданные вызовов | Массовые `INSERT`, затем отдельные `UPDATE` | Объем растет быстрее полезного состояния, конкуренция с онлайн-нагрузкой |
| Векторная память | Векторные представления и метаданные | `INSERT`, ANN-поиск, редкие обновления | Потребление RAM, большой индекс, конкуренция за буферы |
| Большие артефакты | Скриншоты, файлы, большие ответы | Запись и чтение больших значений | TOAST, декомпрессия, увеличение WAL и времени обновления |

## LangGraph: checkpointer и store

### Разделение краткосрочной и долгосрочной памяти

Checkpointer сохраняет снимок состояния thread после шагов графа. Каждый новый снимок является новой записью, а не заменой предыдущего. Поэтому длинный диалог и частые переходы между узлами создают insert-heavy нагрузку. Старые снимки не удаляются автоматически; для них нужна политика хранения.

Store предназначен для данных, которые не являются внутренним состоянием графа. Например, предпочтения пользователя можно хранить в namespace по `user_id`, а в узел графа передавать только нужные значения. Это уменьшает размер checkpoint и позволяет управлять временем жизни данных независимо от thread.

Для PostgreSQL в production используют `PostgresSaver`/`AsyncPostgresSaver` и `PostgresStore`/`AsyncPostgresStore`. Перед первым использованием вызываются `setup()`/`asetup()`, создающие таблицы и индексы. Значения `thread_id` следует держать короткими: текущая документация LangGraph рекомендует не превышать 255 символов; для длинных идентификаторов используют UUID или хеш.

### Ограничение размера checkpoint

До настройки PostgreSQL нужно уменьшить объем записываемых данных:

1. Сохранять только последние сообщения или ограничивать контекст по числу сообщений и токенов.
2. Периодически суммаризировать старую часть диалога и заменять ею подробную историю.
3. Не помещать в checkpoint скриншоты, файлы и другие большие артефакты. Их хранят в объектном хранилище, а в PostgreSQL оставляют ссылку и метаданные.
4. Удалять завершенные или истекшие thread вместе со связанными записями в одной транзакции либо заранее подготовленным набором операций.
5. Периодически удалять старые checkpoint по retention policy. Удаление строк само по себе не уменьшает физический файл таблицы.

Если один checkpoint содержит весь диалог, его размер растет вместе с диалогом. Это увеличивает количество страниц, число чтений, объем WAL и вероятность вытеснения полезных страниц из `shared_buffers`.

## Схемы таблиц и storage parameters

### Примеры DDL для компонентов агентской памяти

Ниже приведены типовые схемы таблиц, которые создают `PostgresSaver`/`AsyncPostgresSaver` и `PostgresStore`/`AsyncPostgresStore` при вызове `setup()`/`asetup()`. Зная схему, SRE может подобрать индексы, `fillfactor` и пороги autovacuum под конкретную таблицу.

**Checkpointer (PostgresSaver):**
```sql
-- Таблица checkpoint (снимки состояния thread)
CREATE TABLE IF NOT EXISTS checkpoint (
    thread_id text NOT NULL,
    checkpoint_id text NOT NULL,
    parent_checkpoint_id text,
    type text NOT NULL,
    checkpoint jsonb NOT NULL,
    metadata jsonb,
    PRIMARY KEY (thread_id, checkpoint_id)
);

-- Таблица writes (промежуточные записи узлов между checkpoint)
CREATE TABLE IF NOT EXISTS writes (
    thread_id text NOT NULL,
    checkpoint_id text NOT NULL,
    task_id text NOT NULL,
    channel text NOT NULL,
    value jsonb NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_id, task_id, channel)
);

-- Индекс для поиска последнего checkpoint по thread_id
CREATE INDEX IF NOT EXISTS checkpoint_thread_id_idx ON checkpoint (thread_id);
```

**Store (PostgresStore):**
```sql
-- Основная таблица store (ключ-значение в namespace)
CREATE TABLE IF NOT EXISTS store (
    namespace text NOT NULL,
    key text NOT NULL,
    value jsonb NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    PRIMARY KEY (namespace, key)
);

-- Индекс для поиска по части namespace (например, 'user_123%')
CREATE INDEX IF NOT EXISTS store_namespace_prefix_idx ON store (namespace text_pattern_ops);
```

### Настройка storage parameters под каждый тип нагрузки

Для каждой таблицы задают отдельные параметры хранения. Примеры для типовых сценариев:

**Checkpointer (insert-heavy, редкие UPDATE):**
```sql
ALTER TABLE checkpoint SET (
    fillfactor = 100,                 -- insert-only, резерв не нужен
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_insert_scale_factor = 0.02,
    autovacuum_vacuum_insert_threshold = 5000,
    autovacuum_vacuum_cost_limit = 2000
);
```

**Store (update-heavy, частые UPDATE):**
```sql
ALTER TABLE store SET (
    fillfactor = 75,                  -- резерв для HOT-обновлений
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_analyze_scale_factor = 0.005,
    autovacuum_vacuum_cost_limit = 1000,
    autovacuum_vacuum_cost_delay = 0  -- агрессивно, после проверки I/O
);
```

**Очереди задач (смешанный профиль):**
```sql
ALTER TABLE agent_tasks SET (
    fillfactor = 80,
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_vacuum_cost_limit = 500
);
```

Параметр `autovacuum_vacuum_cost_delay = 0` делает очистку агрессивнее, но увеличивает конкуренцию за диск. Его применяют после проверки I/O и latency, а не как универсальное значение. В PostgreSQL 18 `autovacuum_worker_slots` резервирует места для воркеров; значение согласуют с `autovacuum_max_workers` и доступной памятью.

### Таблицы для телеметрии и traces

Телеметрия и traces (спаны, токены, latency, метаданные вызовов) имеют профиль массовых `INSERT` с последующей редкой обработкой. Их рекомендуется выносить в отдельную схему или отдельный инстанс, но если объединение временно необходимо, используют типовые настройки:

```sql
-- Таблица телеметрии (insert-heavy, retention по времени)
CREATE TABLE agent_telemetry (
    id bigserial PRIMARY KEY,
    thread_id text,
    event_type text NOT NULL,
    span_data jsonb NOT NULL,
    created_at timestamptz DEFAULT now()
) PARTITION BY RANGE (created_at);

-- Создание партиций по месяцам (пример для текущего и будущего месяца)
CREATE TABLE agent_telemetry_2026_09 PARTITION OF agent_telemetry
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE agent_telemetry_2026_10 PARTITION OF agent_telemetry
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
```

Для автоматического создания и удаления партиций используют `pg_partman`. Подробнее — в разделе **Партиционирование и удаление старых данных** ниже и в **[Документации pg_partman](https://github.com/pgpartman/pg_partman)**.

## Интеграция с LangGraph: настройка и параметры соединения

### Подключение checkpointer и store

Для production-использования `PostgresSaver`/`AsyncPostgresSaver` и `PostgresStore`/`AsyncPostgresStore` настройте строку подключения с account-параметрами и используйте пул соединений:

**Синхронный вариант (PostgresSaver):**
```python
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from psycopg import ConnectionLoader

# Строка подключения с account-параметрами для PgBouncer
conn_str = (
    "postgresql://app_user:password@pgbouncer_host:6432/agent_db"
    "?account=app_user"
    "&connect_timeout=10"
    "&application_name=langgraph_agent"
)

# Создание соединения с настройками пула
loader = ConnectionLoader(
    conn_str,
    min_size=5,      # Минимальное число соединений в пуле
    max_size=20,     # Максимальное число соединений в пуле
    kwargs={"autocommit": False},
)

# Инициализация checkpointer и store
saver = PostgresSaver(conn_loader=loader)
store = PostgresStore(conn_loader=loader)

# Создание таблиц и индексов (однократно при первом запуске)
saver.setup()
store.asql_setup()  # для асинхронного store
```

**Асинхронный вариант (AsyncPostgresSaver):**
```python
from langgraph.checkpoint.postgres import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore
from psycopg import AsyncConnection

# Асинхронное подключение
conn_str = (
    "postgresql://app_user:password@pgbouncer_host:6432/agent_db"
    "?account=app_user"
    "&connect_timeout=10"
)

saver = AsyncPostgresSaver.from_conn_string(conn_str)
store = AsyncPostgresStore.from_conn_string(conn_str)

# Инициализация
async with saver as checkpointer:
    await checkpointer.asql_setup()
async with store as store_instance:
    await store_instance.asql_setup()
```

### Параметры пула соединений

При прямом подключении без PgBouncer настройте `max_connections` на PostgreSQL с учетом:

```
max_connections = (прикладные соединения) + (воркеры autovacuum) + (административные) + (резерв)
```

**Пример для среды с PgBouncer:**
```ini
# postgresql.conf
max_connections = 300          # Основной лимит
superuser_reserved_connections = 5
autovacuum_max_workers = 3     # По одному воркеру на checkpoint/store/очередь
```

**Пример без PgBouncer (масштабируемость ограничена):**
```ini
max_connections = 200
work_mem = 16MB                 # На каждую операцию сортировки/хэша
```

Формула расчета RAM на соединения:
```
Общая RAM на соединения = max_connections × (work_mem + overhead)
```
Где `overhead` ≈ 10 MB на простое соединение. Подробнее — в **[Управлении соединениями](./connection_management.md)**.

### Настройка thread_id и namespace

**thread_id:** держите короткими — текущая документация LangGraph рекомендует не превышать 255 символов. Для длинных идентификаторов используйте UUID или хеш:
```python
import uuid

thread_id = str(uuid.uuid4())  # Рекомендуется
# thread_id = "user_12345_session_20260910"  # Допустимо, но длиннее
```

**Store namespace:** структурируйте по типам данных и пользователям:
```python
# Предпочтения пользователя
await store.aput(("users", str(user_id), "preferences"), {
    "language": "ru",
    "tone": "technical"
})

# Извлеченный факт
await store.aput(("facts", str(user_id), "postgres_version"), {
    "value": "18",
    "source": "SELECT version()"
})
```

### Параметры подключения к PostgreSQL

Для стабильной работы агентской памяти настройте следующие параметры в `postgresql.conf`:

```ini
# --- Соединения ---
max_connections = 300
superuser_reserved_connections = 5
idle_in_transaction_session_timeout = '5min'  # Защита от зависших транзакций
statement_timeout = '10min'                   # Общий таймаут запросов
lock_timeout = '10s'                          # Таймаут ожидания блокировок

# --- Память ---
shared_buffers = '2GB'                        # 25% от всего ОЗУ (8ГБ)
work_mem = '16MB'
maintenance_work_mem = '1GB'                  # Для VACUUM и CREATE INDEX

# --- WAL и checkpoint ---
wal_level = replica
max_wal_size = '4GB'
checkpoint_timeout = '15min'
checkpoint_completion_target = 0.9
synchronous_commit = on                       # Для критичных данных

# --- Логирование ---
log_min_duration_statement = 1000             # Медленные запросы (>1с)
log_statement = 'ddl'                         # Логировать DDL
log_connections = on
log_disconnections = on
```

## MVCC, HOT и fillfactor

### Почему UPDATE создает дополнительные версии

При `UPDATE` PostgreSQL создает новую версию строки и связывает ее со старой через MVCC. Старая версия остается видимой транзакциям с подходящим снимком до завершения очистки. Частые обновления поэтому создают dead tuples и увеличивают таблицу и индексы.

**HOT (Heap Only Tuple)** позволяет PostgreSQL записать новую версию на той же странице без обновления обычных индексов, если:

- обновляемые столбцы не входят в индексы, которые необходимо менять;
- новая версия помещается на той же странице;
- на странице есть свободное место;
- изменение не требует перехода в другую страницу.

Дополнительный индекс по обновляемому столбцу или по предикату частичного индекса может отключить HOT. Для update-heavy таблицы иногда полезнее убрать вторичный индекс и выполнять редкий аналитический запрос другим способом, чем ускорить отдельный `SELECT` ценой многократного обновления индекса.

### Fillfactor

`fillfactor` таблицы определяет, какую часть страницы занимают новые строки. Для insert-only таблиц, включая типичные checkpoint-таблицы, обычно оставляют `100`: резерв места не нужен и только увеличивает физический объем.

Для таблиц с частыми обновлениями применяют значение примерно `70–80`, чтобы новая версия строки чаще помещалась на той же странице и использовала HOT. Значение подбирают по фактической доле HOT-обновлений и размеру строк.

Параметр действует при создании новых страниц. Изменение `fillfactor` не перестраивает уже заполненные страницы; для применения к существующим данным требуется пересборка или другая операция переписи таблицы. Для индексов `fillfactor` решает отдельную задачу и сам по себе не создает резерв в heap-страницах.

## Autovacuum и борьба с раздуванием

### Настройка на уровне таблицы

Для агентской памяти недостаточно глобального `autovacuum_vacuum_scale_factor`: checkpoint, store, очередь и телеметрия имеют разные пороги. Для каждой таблицы задают отдельные storage parameters.

Базовая формула срабатывания vacuum использует порог и долю от размера таблицы. Для больших таблиц абсолютная доля может оказаться слишком большой, поэтому дополнительно проверяют:

- `autovacuum_vacuum_threshold`;
- `autovacuum_vacuum_scale_factor`;
- `autovacuum_vacuum_insert_threshold`;
- `autovacuum_vacuum_insert_scale_factor`;
- `autovacuum_analyze_scale_factor`;
- `autovacuum_vacuum_cost_limit`;
- `autovacuum_vacuum_cost_delay`.

В PostgreSQL 18 добавлен `autovacuum_vacuum_max_threshold`, ограничивающий максимальное число обновленных или удаленных tuples, после которого запускается vacuum. Это полезно для больших таблиц, где одна только процентная формула допускает слишком много dead tuples.

Пример для update-heavy store:

```sql
ALTER TABLE agent_store SET (
  fillfactor = 75,
  autovacuum_vacuum_scale_factor = 0.01,
  autovacuum_analyze_scale_factor = 0.005,
  autovacuum_vacuum_cost_limit = 1000,
  autovacuum_vacuum_cost_delay = 0
);
```

`autovacuum_vacuum_cost_delay = 0` делает очистку агрессивнее, но увеличивает конкуренцию за диск. Его применяют после проверки I/O и latency, а не как универсальное значение. В PostgreSQL 18 `autovacuum_worker_slots` резервирует места для воркеров; значение согласуют с `autovacuum_max_workers` и доступной памятью.

### Что делает VACUUM

Обычный `VACUUM`:

- помечает освободившиеся строки и line pointers для повторного использования;
- удаляет мертвые записи из индексов;
- обновляет Visibility Map и статистику;
- может обрезать полностью пустые страницы в конце файла;
- в большинстве случаев не возвращает занятый таблицей файл операционной системе.

`VACUUM FULL` переписывает таблицу в новый файл, возвращает место и требует `ACCESS EXCLUSIVE` lock. Его не используют как регулярную очистку. `pg_repack` может выполнить онлайн-пересборку, но требует отдельного расширения, временного места и проверки блокировок на конкретной версии.

Индекс после vacuum может содержать меньше мертвых записей, но его физический файл обычно не уменьшается. Для уменьшения размера индекса используют `REINDEX` или `REINDEX CONCURRENTLY`, если это оправдано измеренным bloat.

### Что мешает очистке

Dead tuples могут удерживаться:

- долгоживущей транзакцией;
- сессией в состоянии `idle in transaction`;
- старым snapshot;
- операцией, которая долго читает данные;
- некоторыми сценариями репликации и логического декодирования.

Неактивный replication slot прежде всего удерживает WAL и может привести к заполнению `pg_wal`; он не является универсальной заменой проверке старыхxmin и активных транзакций. Для диагностики используют `pg_stat_activity`, `pg_replication_slots`, `pg_stat_progress_vacuum` и возраст XID/MultiXID.

## TOAST, JSONB и большие значения

PostgreSQL обычно хранит большие переменные значения в связанной TOAST-таблице. Значения сжимаются и разбиваются на chunks; основная таблица хранит указатель. TOAST находится внутри кластера PostgreSQL, а не в S3 или другом внешнем файловом хранилище.

Для больших `jsonb` и BLOB важны следующие правила:

- изменение большого значения создает новую версию строки и может переписать весь логический объект;
- неизмененные TOAST-значения при обновлении обычно сохраняются без повторной записи;
- частые поля, статусы и счетчики выносят в обычные колонки;
- для больших текстовых или бинарных полей выбирают `EXTENDED` (сжатие и out-of-line) или `EXTERNAL` (out-of-line без сжатия) осознанно;
- `EXTERNAL` может ускорить выбор части большого `text`/`bytea`, но увеличивает занимаемое место;
- LZ4 часто выгоден по скорости декомпрессии, если сборка PostgreSQL поддерживает этот метод.

Изменение `COMPRESSION` влияет на новые данные и не является автоматической перекомпрессией уже хранящихся значений.

## Партиционирование и удаление старых данных

Для checkpoint, traces и других временных данных используют partitioning по времени, если запросы и retention действительно используют временной ключ. Partition pruning работает только тогда, когда условие запроса позволяет планировщику исключить партиции. Например, фильтр только по `thread_id` не исключит месячные партиции, разделенные по `created_at`.

Преимущества временного partitioning:

- удаление старой партиции быстрее массового `DELETE` по строкам;
- индексы меньше и обслуживаются отдельно;
- `VACUUM` работает с меньшими отношениями;
- можно заранее создавать будущие партиции и автоматически удалять истекшие.

Для автоматизации применяют `pg_partman`. При удалении или detach партиции учитывают WAL: операция изменения данных журналируется и попадает на реплики. Для больших исторических объемов detach/drop обычно дешевле, чем удаление строк с последующей пересборкой.

Не следует делать partitioning только ради хранения thread, если ключ partitioning не используется в запросах: это добавит планирование и обслуживание без pruning. Чрезмерное количество партиций также увеличивает Planning Time.

## Очереди задач в PostgreSQL

### Простая очередь через SKIP LOCKED

Для небольшой очереди задач подходит выбор доступной строки с блокировкой:

```sql
BEGIN;

SELECT id, payload
FROM agent_tasks
WHERE status = 'pending'
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED;

UPDATE agent_tasks
SET status = 'done', finished_at = now()
WHERE id = :id;

COMMIT;
```

`SKIP LOCKED` пропускает строки, уже заблокированные другими воркерами, и позволяет им брать разные задачи без ожидания. Частичный индекс по `status = 'pending'` уменьшает размер индекса, но обновление `status` меняет принадлежность строки индексу и может отключить HOT. Если статус часто обновляется, проверяют компромисс между скоростью выбора и стоимостью записи.

### Гарантии доставки

Простая схема `SELECT FOR UPDATE SKIP LOCKED` не дает exactly-once execution:

- если задача удалена или помечена выполненной до внешней работы, сбой воркера может привести к потере задачи;
- если внешняя работа выполнена до `COMMIT`, сбой транзакции может привести к повторному выполнению;
- воркер может получить задачу повторно после отката или истечения видимимости.

Обработку делают идемпотентной, хранят уникальный ключ операции и используют явный lease/visibility timeout. Для более сложной очереди применяют PGMQ: он предоставляет API, archive, partitioned archive и visibility timeout. Гарантия PGMQ относится к доставке сообщения в пределах visibility timeout; идемпотентность внешней side effect-операции все равно обязательна.

Очередь в PostgreSQL удобна для умеренной нагрузки и атомарности с бизнес-данными. При большом backlog, высокой частоте polling или жестких требованиях к throughput отдельный broker обычно дает лучшее масштабирование и управление backpressure.

### PGMQ — расширение для очередей

`PGMQ` (Postgres Message Queue) — расширение, добавляющее нативную поддержку очередей сообщений в PostgreSQL с интерфейсом, схожим с cloud-брокерами (Kafka, SQS), но без отдельного инфраструктурного компонента.

**Ключевые возможности:**
- Отправка (`send`), получение (`recv`) и удаление (`delete`) сообщений через SQL-интерфейс.
- `visibility timeout` — после получения сообщения оно становится невидимым для других воркеров на заданный timeout, предотвращая дублированную обработку.
- Архивация и partitioned archive — старые сообщения могут быть автоматически архивированы в отдельные таблицы.
- Поддержка long polling и параллельных воркеров.

**Базовое использование:**
```sql
-- Создание очереди
SELECT pgmq.create_queue('agent_tasks');

-- Отправка сообщения
SELECT pgmq.send('agent_tasks', '{"task": "summarize", "thread_id": "abc123"}');

-- Получение сообщений (с visibility timeout 30s)
SELECT * FROM pgmq.recv('agent_tasks', 30, 3);

-- Удаление обработанного сообщения
SELECT pgmq.delete('agent_tasks', msg_id);
```

Гарантия PGMQ относится к доставке сообщения в пределах visibility timeout; идемпотентность внешней side effect-операции все равно обязательна. PGMQ подходит для умеренной нагрузки; при десятках тысяч сообщений в секунду и жестких требованиях к throughput отдельный broker (RabbitMQ, Kafka) дает лучшее масштабирование.

## Безопасность и изоляция данных

Для агентской памяти важна изоляция между пользователями, thread и типами данных. Рекомендуемые меры:

### RBAC и права доступа

Создайте отдельные роли с минимально необходимыми правами. Подробный гайд — в **[Управлении ролями и правами доступа (RBAC)](./role_management.md)**.

```sql
-- Роль для приложения (чтение/запись агентской памяти)
CREATE ROLE agent_app WITH LOGIN PASSWORD 'strong_password' CONNECTION LIMIT 50;
GRANT CONNECT ON DATABASE agent_db TO agent_app;

-- Роль для мониторинга (только чтение статистики)
CREATE ROLE agent_monitor WITH LOGIN;
GRANT pg_monitor TO agent_monitor;
GRANT USAGE ON SCHEMA public TO agent_monitor;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_monitor;
```

### Row-Level Security (RLS)

Для изоляции данных между пользователями и thread на уровне строк включите RLS на таблицах checkpoint и store:

```sql
-- Включение RLS
ALTER TABLE checkpoint ENABLE ROW LEVEL SECURITY;
ALTER TABLE store ENABLE ROW LEVEL SECURITY;

-- Политика: пользователь видит только свои thread
CREATE POLICY user_checkpoint_policy ON checkpoint
    FOR SELECT
    USING (thread_id LIKE current_setting('app.current_user_id') || '%');

-- Политика: доступ к namespace по user_id
CREATE POLICY user_store_policy ON store
    FOR ALL
    USING (namespace LIKE current_setting('app.current_user_id') || '%');
```

**Внимание:** RLS добавляет накладные расходы на каждый запрос. Для высоконагруженных систем проверьте влияние на latency через `EXPLAIN ANALYZE`.

### Шифрование данных

- **В покое (at rest):** в ванильном PostgreSQL нативного TDE нет. Используйте шифрование на уровне ФС (LUKS/ZFS) или расширение `pg_tde` (Percona). Подробности — в **[Безопасности и шифровании](../Concepts/security_and_encryption.md)**.
- **В transit:** включите SSL/TLS для всех соединений. В `postgresql.conf`:
  ```ini
  ssl = on
  ssl_cert_file = '/etc/ssl/certs/postgres.crt'
  ssl_key_file = '/etc/ssl/private/postgres.key'
  ssl_min_protocol_version = 'TLSv1.3'
  ```
- **На уровне столбцов:** для особенно чувствительных данных (например, токены пользователей) используйте `pgcrypto`:
  ```sql
  CREATE EXTENSION IF NOT EXISTS pgcrypto;
  INSERT INTO store (namespace, key, value)
  VALUES ('user_123', 'api_token', pgp_sym_encrypt('secret-token', 'encryption-key'));
  ```

### Аудит и логирование

Включите аудит через journal и `pgaudit`:
```ini
# postgresql.conf
log_connections = on
log_disconnections = on
log_statement = 'ddl'          -- логировать DDL
log_min_duration_statement = 1000  -- медленные запросы (>1с)
```

## Миграция и восстановление данных

### Миграция агентской памяти

При миграции PostgreSQL-памяти агента (смена версии, перенос в другой инстанс) важно сохранить checkpoint, store и очереди. Два основных пути:

**1. Логическая миграция (рекомендуется для межверсионных миграций):**

Используйте логическую репликацию (Publisher-Subscriber) или `pg_dump`/`pg_restore`. Подробное руководство — в **[Миграции без простоя](./zero_downtime_migration.md)**.

```bash
# Логический дамп с компрессией ZSTD (PostgreSQL 17+)
pg_dump -h source_host -U backup_user -d agent_db \
  -Fc --compress=zstd:3 \
  -f /backups/agent_db_$(date +%Y%m%d).dump

# Восстановление
pg_restore -h target_host -U postgres -d agent_db_restored \
  -j 4 /backups/agent_db_20260910.dump
```

**2. Физическая миграция (быстрее, но только в пределах одной мажорной версии):**

Используйте `pg_basebackup` или `pgBackRest`:
```bash
# Базовый физический бэкап
pg_basebackup -h source_host -U replicator -D /backups/base_backup -X stream --wal

# Восстановление через pgBackRest
pgbackrest restore --stanza=main --target=/var/lib/postgresql/16/main
```

### Восстановление после сбоя

Сценарии восстановления агентской памяти:

**Сценарий 1: Восстановление checkpoint после сбоя инстанса**
```python
# При запуске агента подключите checkpointer с существующим thread_id
config = {
    "configurable": {
        "thread_id": "user_123_session_456"
    }
}

# Checkpointer автоматически загрузит последний checkpoint
state = await graph.ainvoke(None, config)
```

**Сценарий 2: Восстановление store из бэкапа**
```bash
# Восстановление только таблицы store
pg_restore -h target_host -U postgres -d agent_db \
  -t store /backups/agent_db.dump
```

**Сценарий 3: Обработка задач, прервавшихся во время сбоя**
```sql
-- Найти задачи, которые были в обработке при сбое
SELECT id, created_at, now() - created_at AS age
FROM agent_tasks
WHERE status = 'in_progress'
ORDER BY created_at;

-- Перевести их в pending (идемпотентность гарантирует безопасность)
UPDATE agent_tasks
SET status = 'pending', attempts = attempts + 1
WHERE id IN (SELECT id FROM agent_tasks WHERE status = 'in_progress');
```

### PITR (Point-in-Time Recovery)

Для восстановления агентской памяти на конкретный момент времени используйте PITR:
```bash
# Восстановление на 2026-09-10 14:30:00
pgbackrest restore --stanza=main \
  --target-time="2026-09-10 14:30:00" \
  --target-action=promote \
  --target=/var/lib/postgresql/16/main
```

**Важно:** PITR требует настроенного `archive_mode` и `archive_command` для сохранения WAL. Подробности — в **[Теории бэкапов и восстановления](../Concepts/backup_and_recovery.md)**.

## WAL, checkpoint и durability

Checkpoint в PostgreSQL и checkpoint LangGraph — разные понятия. Контрольная точка PostgreSQL сбрасывает грязные страницы и влияет на I/O; снимок LangGraph хранит состояние thread. Рост таблиц, TOAST и индексов увеличивает число страниц, которые могут участвовать в проверках, чтении и записи, поэтому bloat косвенно ухудшает и работу контрольных точек.

`max_wal_size`, `checkpoint_timeout` и `checkpoint_completion_target` настраивают баланс между частотой I/O и временем восстановления. Их нельзя менять без измерения `pg_stat_bgwriter`/`pg_stat_checkpointer`, WAL throughput и recovery RTO.

`synchronous_commit` можно ослаблять только для данных, потерю которых допустимо пережить:

- `on` ожидает локальную фиксацию WAL и дает стандартную durability;
- `local` ожидает локальную запись WAL, но не подтверждений синхронных standby;
- `off` не ожидает синхронного сброса WAL и допускает потерю недавно подтвержденных транзакций при сбое.

Для пользовательского состояния, фактов, задач и других обязательных данных сохраняют строгие гарантии. Для временных telemetry-данных решение принимают отдельно на основании допустимой потери и требований к latency.

## Векторная память и изоляция нагрузки

`pgvector` удобен, когда векторный поиск должен выполняться в той же транзакции и с теми же метаданными, что и реляционные данные. При этом ANN-индексы, особенно HNSW, требуют памяти и дополнительного обслуживания. Большой индекс может вытеснять страницы checkpoint, store и очереди из `shared_buffers`.

Перед объединением нагрузок проверяют:

- размер векторного индекса и его долю в RAM;
- время построения и обновления индекса;
- latency ANN-поиска под реальной кардинальностью;
- конкуренцию с checkpoint, WAL, vacuum и аналитическими запросами;
- возможность отдельного read replica или отдельного векторного инстанса.

Если индекс не помещается в память или аналитика начинает ухудшать online latency, векторный поиск выносят в отдельный сервис или инстанс. Для временных рядов, telemetry и тяжелой аналитики чаще подходит специализированное хранилище, чем смешивание всех данных в одном PostgreSQL.

### Практические примеры pgvector в агентской памяти

**Таблица с embeddings:**
```sql
CREATE TABLE agent_facts (
    id bigserial PRIMARY KEY,
    namespace text NOT NULL,        -- например, 'user_123'
    key text NOT NULL,
    fact text NOT NULL,
    embedding vector(1536),         -- размерность для OpenAI text-embedding-3-small
    created_at timestamptz DEFAULT now()
);

-- Индекс HNSW для ANN-поиска (рекомендуется для production)
CREATE INDEX agent_facts_embedding_hnsw_idx ON agent_facts
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);

-- Частичный индекс только для активных записей
CREATE INDEX agent_facts_active_idx ON agent_facts (namespace, key)
    WHERE created_at > now() - interval '90 days';
```

**Поиск похожих фактов с фильтрацией по namespace:**
```sql
SELECT id, fact, 1 - (embedding <=> $1) AS similarity
FROM agent_facts
WHERE namespace = 'user_123'
ORDER BY embedding <=> $1
LIMIT 5;
```

**Гибридный поиск (векторный + полнотекстовый):**
```sql
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1) as rank
    FROM agent_facts
    WHERE namespace = 'user_123'
    LIMIT 50
),
keyword AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(to_tsvector('russian', fact), to_tsquery($2)) DESC) as rank
    FROM agent_facts
    WHERE namespace = 'user_123'
      AND to_tsvector('russian', fact) @@ to_tsquery($2)
    LIMIT 50
)
SELECT id, fact,
       (1.0 / (60 + COALESCE(s.rank, 101))) + (1.0 / (60 + COALESCE(k.rank, 101))) AS rrf_score
FROM semantic s
FULL JOIN keyword k USING (id)
ORDER BY rrf_score DESC
LIMIT 10;
```

**Мониторинг размера индекса:**
```sql
SELECT
    indexrelname,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
    pg_size_pretty(pg_relation_size(relid)) AS table_size
FROM pg_stat_user_indexes
WHERE relname = 'agent_facts';
```

**Тюнинг производительности ANN-поиска:**
```sql
-- Увеличить точность поиска (жестче, но медленнее)
SET hnsw.ef_search = 100;

-- Уменьшить точность для скорости (быстрее, но ниже recall)
SET hnsw.ef_search = 40;
```

### Критерии выноса векторного поиска

Векторный поиск выносится в отдельный инстанс или сервис, если:
- Размер HNSW-индекса превышает 50% от `shared_buffers`.
- ANN-поиск вызывает рост `DataFileRead` wait events.
- Латентность p95 ANN-запросов превышает 50 мс под реальной кардинальностью.
- Индекс мешает checkpoint и autovacuum ( частые `CHECKPOINT` или `VACUUM`).
- Используется `halfvec`/`bit` для экономии памяти, но точности не хватает.

## Резервное копирование и восстановление

Агентская память содержит состояния, которые нельзя терять: checkpoint thread, факты пользователя, задачи. Стратегия бэкапов должна быть адаптирована под особенности агентской памяти.

### Особенности бэкапа агентской памяти

- **Checkpoint (checkpointer):** таблицы растут непрерывно из-за `INSERT` каждого шага графа. Старые checkpoint удаляются по retention policy, но на момент бэкапа таблица может быть большой. Регулярные `VACUUM` и партиционирование упрощают логический дамп.
- **Store:** таблица с частыми `UPDATE`. При `pg_dump` используется формат `custom` (`-F c`) с компрессией ZSTD для эффективного архивирования.
- **Очереди задач:** задачи могут быть в статусе `pending` или `in progress`. При восстановлении из бэкапа важно не запускать задачи, которые уже обрабатываются (идемпотентность).
- **Телеметрия и traces:** данные, потерю которых допустимо пережить. Их бэкап может выполняться реже или выноситься в отдельное хранилище.

### Рекомендуемый подход

Для production-развертываний агентской памяти используют физический бэкап через `pgBackRest` или `WAL-G`, который поддерживает инкрементальные копии и восстановление на момент времени (PITR). Подробная настройка — в **[Автоматизации резервного копирования](./backup_automation.md)** и **[Теории бэкапов и восстановления](../Concepts/backup_and_recovery.md)**.

**Базовый конфиг `pgBackRest`:**
```ini
[global]
repo1-path=/var/lib/pgbackrest
repo1-retention-full=2          # Хранить 2 полных бэкапа
repo1-retention-diff=7          # Хранить 7 дифференциальных
process-max=4
log-level-console=info

[main]
pg1-path=/var/lib/postgresql/16/main
```

**Автоматизация через Systemd Timer:**
```ini
[Unit]
Description=Daily pgBackRest Full Backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

**Команда запуска:**
```bash
# pgBackRest сам выберет тип (full/incr/diff) на основе расписания и наличия предыдущих копий
pgbackrest backup --stanza=main --type=incr
```

### Верификация бэкапов

После каждого бэкапа проверяйте целостность:
```bash
# Проверка манифеста и контрольных сумм (PostgreSQL 13+)
pg_verifybackup /var/lib/pgbackrest/backup/main/latest
```

Рекомендуется также автоматическое тестовое восстановление последнего бэкапа на изолированном инстансе раз в неделю.

## Жизненный цикл данных и масштабирование

### Управление retention

Для каждого типа данных задайте политику хранения:

| Тип данных | Рекомендуемый retention | Механизм удаления |
| :--- | :--- | :--- |
| Checkpointer (снимки thread) | 7–30 дней | `DELETE` по `created_at` + `VACUUM` или partition drop |
| Store (факты, предпочтения) | Постоянно или по TTL | `DELETE` по `updated_at` + `VACUUM` |
| Очереди задач | 7–14 дней | Удаление выполненных/отмененных задач |
| Телеметрия и traces | 3–90 дней | Partition drop по месяцам |
| Векторная память | По требованию | Очистка устаревших embeddings |

Удаление строк само по себе не уменьшает физический файл таблицы. Для возврата места используют `VACUUM` (освобождает для повторного использования) или `VACUUM FULL`/`pg_repack` (переписывает таблицу, только при измеренной необходимости).

### Масштабирование нагрузки

При росте объема данных и нагрузки агентской памяти рассмотрите следующие пути:

1. **Разделение по типам данных:** отдельные инстансы PostgreSQL для checkpoint, store и очередей. Это изолирует insert-heavy нагрузку checkpoint от update-heavy store и предотвращает конкуренцию за `shared_buffers`, WAL и CPU.
2. **Чтение/запись разделение:** использование read replica для отчетов, аналитики и векторного поиска, если он не критичен для latency.
3. **Отдельный векторный инстанс:** при росте ANN-индекса сверх допустимой доли `shared_buffers` pgvector выносится в отдельный PostgreSQL с отдельными настройками памяти.
4. **Отдельный брокер очередей:** при backlog более нескольких тысяч задач или throughput более нескольких сотен задач в секунду PGMQ заменяется на RabbitMQ или Kafka.
5. **Специализированные хранилища:** телеметрия и traces с высокой скоростью поступления могут быть переведены в TimescaleDB, ClickHouse или лог-агрегатор (ELK Stack).

### Высокая доступность

Для production-развертываний агентской памяти требуется отказоустойчивый кластер. Используйте синхронную или квазисинхронную репликацию, чтобы checkpoint и store не потерялись при failover. Подробности — в **[Отказоустойчивом кластере (Patroni)](./high_availability_patroni.md)** и **[Репликации](../Concepts/replication.md)**.

Ключевые параметры для HA:
```ini
# postgresql.conf
synchronous_commit = on           # Строгая гарантия durability
synchronous_standby_names = '*'   # Ожидать подтверждения от всех standby
wal_level = replica
max_wal_senders = 10
max_replication_slots = 10
hot_standby = on                  # Позволить чтение на standby
```

## Наблюдаемость

### Критические алерты (SRE-пороги)

Для PostgreSQL-памяти агента настройте следующие алерты в Prometheus/Grafana или Zabbix:

| Алерт | Условие | Причина |
| :--- | :--- | :--- |
| **Dead tuples растут** | `n_dead_tup / (n_live_tup + n_dead_tup) > 30%` | autovacuum не успевает, растет bloat |
| **Idle in transaction** | `count(state='idle in transaction') > 0` в течение 5 мин | Долгие транзакции мешают VACUUM |
| **Backlog очереди** | `count(status='pending') > 1000` или возраст самой старой задачи > 1 ч | Очередь растет быстрее, чем обрабатывается |
| **WAL generation rate** | `wal_bytes_generated > 100 МБ/мин` | Слишком частые checkpoint или массовые INSERT |
| **Checkpoint frequency** | `checkpoint_timeout` сработал, но `checkpoint_blocks` > 50% | Checkpoint слишком длинный, risk I/O |
| **Replication lag** | `pg_last_xact_replay_timestamp()` отстает > 10 сек | Реплика отстает, risk потери данных |
| **Векторный индекс растет** | `pg_relation_size(indrelid) > 50% от shared_buffers` | HNSW вытесняет checkpoint/store из кэша |
| **XID/MultiXID возраст** | `age(datfrozenxid) > 150 млн` | Приближение к wraparound |
| **TOAST растет** | `pg_total_relation_size(relid)` растет быстрее heap | Большие `jsonb`/BLOB увеличивают WAL |

### Минимальный набор проверок

Для PostgreSQL-памяти агента выполняйте следующие запросы:

```sql
SELECT
  schemaname,
  relname,
  pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
  n_live_tup,
  n_dead_tup,
  last_autovacuum,
  autovacuum_count
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

SELECT
  pid,
  usename,
  state,
  now() - xact_start AS xact_age,
  wait_event_type,
  wait_event,
  left(query, 160) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
ORDER BY xact_start
LIMIT 10;

SELECT
  relname,
  phase,
  heap_blks_scanned,
  heap_blks_total,
  index_vacuum_count
FROM pg_stat_progress_vacuum;

SELECT
  slot_name,
  active,
  restart_lsn,
  wal_status,
  pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;
```

### Дополнительные проверки по типам данных

**Размеры main relation, индексов и TOAST отдельно:**
```sql
SELECT
  relname,
  pg_size_pretty(pg_relation_size(relid)) AS heap_size,
  pg_size_pretty(pg_indexes_size(relid)) AS indexes_size,
  pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid) - pg_indexes_size(relid)) AS toast_size,
  pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```

**Доля HOT-обновлений и число dead index tuples:**
```sql
SELECT
  schemaname,
  relname,
  n_tup_upd,
  n_tup_hot_upd,
  CASE WHEN n_tup_upd > 0
    THEN round(100.0 * n_tup_hot_upd / n_tup_upd, 1)
    ELSE 0
  END AS hot_pct,
  n_dead_tup,
  last_autovacuum
FROM pg_stat_user_tables
WHERE n_tup_upd > 0
ORDER BY n_tup_upd DESC;
```

**Backlog очереди по статусам и возраст самой старой задачи:**
```sql
SELECT
  status,
  count(*) AS count,
  min(now() - created_at) AS oldest_age
FROM agent_tasks
GROUP BY status
ORDER BY count DESC;

-- Самая старая pending-задача
SELECT id, created_at, now() - created_at AS age
FROM agent_tasks
WHERE status = 'pending'
ORDER BY created_at
LIMIT 5;
```

**Размер и скорость роста векторного индекса:**
```sql
SELECT
  i.indexrelname,
  pg_size_pretty(pg_relation_size(i.indexrelid)) AS index_size,
  pg_size_pretty(pg_total_relation_size(i.relid)) AS total_table_size
FROM pg_stat_user_indexes i
JOIN pg_stat_user_tables t ON t.relid = i.relid
WHERE i.indexrelname LIKE '%hnsw%' OR i.indexrelname LIKE '%ivfflat%';
```

**Возраст XID/MultiXID и прогресс anti-wraparound vacuum:**
```sql
SELECT
  datname,
  age(datfrozenxid) AS xid_age,
  age(datlastvacuum) AS last_vacuum_age
FROM pg_database
ORDER BY age(datfrozenxid) DESC;

SELECT
  relname,
  relfrozenxid,
  age(relfrozenxid) AS frozen_xid_age,
  mxid_age(relminmxid) AS mxid_age
FROM pg_class
WHERE relkind IN ('r', 'm')
ORDER BY age(relfrozenxid) DESC;
```

**WAL generation rate и частота checkpoints:**
```sql
SELECT
  pg_size_pretty(wal_bytes) AS wal_bytes,
  pg_size_pretty(wal_bytes / GREATEST(extract(epoch FROM (now() - stats_reset)), 1)) AS wal_per_sec,
  checkpoints_timed,
  checkpoints_req,
  checkpoint_write_time,
  checkpoint_sync_time
FROM pg_stat_bgwriter;
```

Дополнительно отслеживают:

- `n_dead_tup`, `n_live_tup`, `last_autovacuum` и `autovacuum_count` по каждой таблице;
- размеры main relation, индексов и TOAST отдельно;
- долю HOT-обновлений и число dead index tuples;
- backlog очереди по статусам и возраст самой старой задачи;
- `shared hit/read`, временные файлы, WAL generation rate и частоту checkpoints;
- latency checkpoint/store/queue запросов по percentile;
- возраст XID/MultiXID и прогресс anti-wraparound vacuum;
- размер и скорость роста векторного индекса.

## Диагностика и порядок действий

### Чек-лист развертывания (после настройки)

Перед запуском production-агента выполните следующую последовательность:

1. **Установка и активация расширений:**
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector
   CREATE EXTENSION IF NOT EXISTS pg_partman;  -- партиционирование
   CREATE EXTENSION IF NOT EXISTS pg_stat_statements; -- статистика запросов
   ```
   Для очередей: `CREATE EXTENSION IF NOT EXISTS pgmq;` (если используется PGMQ).

2. **Настройка пула соединений:** PgBouncer в режиме transaction pooling, `max_connections` на PostgreSQL — 100–300. Подробнее — в **[Настройке PgBouncer](./pgbouncer_setup.md)**.

3. **Настройка storage parameters** для каждой таблицы (см. раздел **Схемы таблиц и storage parameters**).

4. **Настройка retention и партиционирования:** создать партиции для checkpoint, telemetry, traces; настроить `pg_partman` для автоматического добавления/удаления.

5. **Настройка бэкапов:** pgBackRest или WAL-G с ежедневным полным и hourly инкрементальным бэкапом, верификацией и тестовым восстановлением.

6. **Настройка HA:** синхронная репликация (Patroni/etcd или ванильная), `synchronous_commit = on`, `hot_standby = on`.

7. **Настройка мониторинга:** алерты по списку выше, дашборд в Grafana, сбор логов с `log_min_duration_statement = 1000`.

8. **Нагрузочное тестирование:** см. раздел ниже.

### Порядок диагностики деградации

1. **Уменьшить запись:** обрезать контекст, суммаризировать историю, вынести большие артефакты и убрать лишние поля из checkpoint.
2. **Разделить нагрузки:** отдельные таблицы и настройки для checkpoint, store, очереди, telemetry и vector.
3. **Проверить схему индексов:** удалить избыточные индексы на update-heavy таблицах и проверить влияние частичных индексов на HOT.
4. **Настроить таблицу:** подобрать `fillfactor`, пороги autovacuum, cost parameters и retention.
5. **Устранить удерживающие транзакции:** найти `idle in transaction`, старые snapshots и проблемные replication slots.
6. **Организовать удаление:** использовать partition drop/detach для временных данных; не ожидать уменьшения файла после обычного `DELETE` и `VACUUM`.
7. **Проверить физическое восстановление места:** только при измеренной необходимости использовать `VACUUM FULL` или `pg_repack`.
8. **Изолировать аналитику:** telemetry, traces и тяжелый vector search переносить при конкуренции за RAM, CPU, WAL или disk.
9. **Повторить нагрузочный тест:** сравнивать latency, throughput, bloat, WAL и cache hit до и после каждого изменения.

### Нагрузочное тестирование

Перед запуском в production и после каждого изменения конфигурации выполните нагрузочный тест:

```bash
# 1. Тест пропускной способности checkpoint (массовые INSERT)
pgbench -c 10 -j 2 -T 60 -P 1 agent_db

# 2. Тест update-heavy нагрузки (store)
pgbench -c 5 -j 1 -T 60 -P 1 -f store_update.sql agent_db

# 3. Тест очереди (SKIP LOCKED)
# Используйте скрипт, имитирующий воркеров, берущих задачи с блокировкой

# 4. Тест векторного поиска (ANN)
# Выполните 1000 ANN-запросов и измерьте p50/p95/p99 latency
```

**Что измерять:**
- Latency checkpoint/store/queue запросов (p50, p95, p99).
- Throughput (транзакций в секунду).
- Bloat (доля dead tuples) до и после теста.
- WAL generation rate (МБ/мин).
- Cache hit rate (`shared hit` / `shared read`).
- Использование CPU, RAM, I/O.

## Оптимизация запросов и индексация

### Профилирование запросов

Перед оптимизацией всегда выполняйте `EXPLAIN (ANALYZE, BUFFERS)`:

```sql
-- Пример: анализ запроса на получение последнего checkpoint
EXPLAIN (ANALYZE, BUFFERS)
SELECT checkpoint, metadata
FROM checkpoint
WHERE thread_id = 'user_123'
ORDER BY created_at DESC
LIMIT 1;

-- Пример: анализ запроса store
EXPLAIN (ANALYZE, BUFFERS)
SELECT value
FROM store
WHERE namespace = 'user_123' AND key = 'preferences';
```

**На что смотреть в выводе:**
- `Seq Scan` на большой таблице — нужен индекс.
- `shared read` вместо `shared hit` — данные не в кэше, увеличьте `shared_buffers`.
- `Buffers: shared dirtied` — страницы помечены как грязные, будут сбрасываться на диск.
- `Actual rows` значительно больше `Estimated rows` — статистика устарела, запустите `ANALYZE`.

### Рекомендуемые индексы для агентской памяти

**Checkpointer:**
```sql
-- Индекс для поиска последнего checkpoint по thread_id
CREATE INDEX checkpoint_thread_created_idx ON checkpoint (thread_id, created_at DESC);

-- Индекс для cleanup по retention
CREATE INDEX checkpoint_created_retention_idx ON checkpoint (created_at)
WHERE created_at < now() - interval '30 days';
```

**Store:**
```sql
-- Индекс для поиска по namespace + key (основной запрос)
-- PRIMARY KEY уже покрывает, но добавьте partial index для активных записей
CREATE INDEX store_active_idx ON store (namespace, key)
WHERE updated_at > now() - interval '90 days';
```

**Очереди задач:**
```sql
-- Частичный индекс только для pending задач (меньше размер)
CREATE INDEX agent_tasks_pending_idx ON agent_tasks (created_at)
WHERE status = 'pending';

-- Индекс для обработки по приоритету
CREATE INDEX agent_tasks_priority_idx ON agent_tasks (priority DESC, created_at)
WHERE status = 'pending';
```

**Векторная память:**
```sql
-- HNSW индекс (детали в разделе "Векторная память")
CREATE INDEX agent_facts_embedding_hnsw_idx ON agent_facts
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);
```

### Анализ производительности индексов

```sql
-- Проверка использования индексов
SELECT
    relname,
    indexrelname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE relname IN ('checkpoint', 'store', 'agent_tasks', 'agent_facts')
ORDER BY idx_scan DESC;
```

### Правила индексации для агентской памяти

1. **Не создавайте индексы на все колонки.** Каждый индекс увеличивает стоимость `INSERT`/`UPDATE`/`DELETE` и требует autovacuum-обслуживания.
2. **Частичные индексы** (`WHERE status = 'pending'`) уменьшают размер, но могут отключить HOT при обновлении индексированных колонок.
3. **Индексы на update-heavy таблицах** (store) должны быть минимальными. Дополнительный индекс по обновляемому столбцу блокирует HOT.
4. **Expression indexes** полезны для поиска по вычисленным полям, но увеличивают бloat.
5. **INCLUDE columns** (PG 11+) позволяют создавать covering indexes без добавления колонок в дерево индекса:
   ```sql
   CREATE INDEX store_namespace_key_include ON store (namespace, key)
   INCLUDE (value, updated_at);
   ```

## См. также

- **[Внутреннее устройство VACUUM](../Concepts/vacuum_internals.md)** — dead tuples, Visibility Map, freezing и wraparound.
- **[Оптимизация производительности PostgreSQL](./performance_tuning.md)** — bloat, checkpoint, `pg_repack` и общий тюнинг.
- **[Официальная документация LangGraph: Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)** — checkpointer, store и retention.
- **[pgvector: Векторный поиск](../pgvector.md)** — HNSW, IVFFlat, hybrid search и тюнинг ANN-индексов.
- **[Настройка PgBouncer](./pgbouncer_setup.md)** — пулинг соединений для агентской памяти.
- **[Управление соединениями](./connection_management.md)** — `max_connections`, `idle in transaction`, диагностика.
- **[Автоматизация резервного копирования](./backup_automation.md)** — pgBackRest, WAL-G, бэкапы агентской памяти.
- **[Теория бэкапов и восстановления](../Concepts/backup_and_recovery.md)** — PITR, RPO/RTO, инкрементальные копии.
- **[Миграция без простоя](./zero_downtime_migration.md)** — логическая репликация при миграции агентской памяти.
- **[Отказоустойчивый кластер (Patroni)](./high_availability_patroni.md)** — HA для production-памяти агентов.
- **[Репликация в PostgreSQL](../Concepts/replication.md)** — streaming replication, synchronous_commit, replication slots.
- **[Управление ролями и правами доступа (RBAC)](./role_management.md)** — изоляция пользователей и thread.
- **[Безопасность и шифрование](../Concepts/security_and_encryption.md)** — SSL/TLS, TDE, шифрование данных.
- **[Наблюдаемость PostgreSQL](./observability.md)** — сквозной мониторинг, wait events, трассировка.
- **[Конкурентность и блокировки](../Concepts/concurrency_and_locking.md)** — MVCC, уровни изоляции, `SKIP LOCKED`.
- **[Индексы в PostgreSQL](../Concepts/indexes.md)** — типы индексов, `fillfactor`, `REINDEX`.
- **[Архитектура PostgreSQL](../Concepts/architecture.md)** — shared_buffers, WAL, checkpoint, процессы.
