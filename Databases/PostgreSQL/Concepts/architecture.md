# Архитектура PostgreSQL

**Актуально для:** PostgreSQL 15–18

## Определения

- **Экземпляр (Instance)**: Совокупность запущенных процессов PostgreSQL (`postmaster` и дочерние) и разделяемой области оперативной памяти. Управляет доступом к кластеру баз данных.
- **Кластер баз данных (Database Cluster)**: Совокупность баз данных, хранящихся в едином каталоге **PGDATA**. Управляется одним инстансом.
- **Страница (Page)**: Блок данных фиксированного размера (обычно 8 КБ). Содержит заголовок (PageHeaderData), указатели на строки (ItemIds) и сами данные (Tuples).
- **LSN (Log Sequence Number)**: Уникальный 64-битный адрес позиции в WAL. Критичен для синхронизации памяти и диска (условие: страница может быть сброшена на диск только если WAL до ее LSN уже на диске).
- **TID (Tuple Identifier)**: Физический адрес строки вида `(block_number, offset_index)`.
- **OID (Object Identifier)**: Внутренний числовой идентификатор объектов (БД, таблиц, типов).
- **Filenode**: Имя физического файла на диске, соответствующего таблице или индексу. Обычно совпадает с OID, но меняется при операциях типа `VACUUM FULL` или `TRUNCATE`.
- **Backend-процесс (postgres)**: Индивидуальный процесс, обслуживающий одно клиентское соединение.
- **PGDATA**: Корневой каталог кластера PostgreSQL, содержащий все файлы конфигурации, данные и WAL. Переменная окружения `PGDATA` или параметр `data_directory` в `postgresql.conf`.
- **Fork**: Подраздел внутри файла отношения (relation). Основные типы: `main` (данные), `fsm` (карта свободного места), `vm` (карта видимости), `init` (инициализация).
- **Relation**: Объект базы данных с физическим хранением (таблица, индекс, материализованное представление). Каждый relation имеет OID и filenode.

## Базовые концепции

### Процессная модель

PostgreSQL использует модель **Process-per-connection**. Это обеспечивает высокую изоляцию, но требует использования пулеров соединений для масштабирования.

1. **Postmaster (PostgreSQL Supervisor)**:
   - Слушает управляющий сокет.
   - Выполняет аутентификацию и порождает (fork) Backend-процессы.
   - Инициирует восстановление кластера при падении любого из дочерних процессов.
2. **Вспомогательные процессы (Auxiliary Processes)**:
   - **Checkpointer**: Координирует сброс "грязных" страниц на диск для сокращения времени восстановления (Recovery Time).
   - **Background Writer (bgwriter)**: Сбрасывает страницы порциями, чтобы в **Shared Buffers** всегда были свободные блоки для новых данных.
   - **WAL Writer**: Сбрасывает WAL-буферы на диск. Гарантирует **Durability** (буква D в ACID).
   - **Autovacuum Launcher/Workers**: Автоматизируют очистку мертвых кортежей. В **PG 17** используют **TidStore** для эффективного хранения идентификаторов строк в RAM.
   - **Walsummarizer (PG 17)**: Создает сводки изменений WAL для поддержки инкрементальных бэкапов.
   - **Archiver**: Перемещает заполненные сегменты WAL в архивное хранилище.
   - **Startup Process**: Выполняет восстановление данных при запуске системы.

### Структуры памяти

#### Общая память (Shared Memory)
- **Shared Buffers**: Кэш страниц. PostgreSQL использует алгоритм **Clock Sweep** (приближение к LRU): каждая страница имеет счетчик обращений (usage count), который уменьшается при "проходе" часовой стрелки.
- **WAL Buffers**: Краткосрочное хранилище записей журнала перед их записью на диск.
- **Caches (Syscache/Relcache)**: Хранят метаданные системных таблиц (определения колонок, прав доступа).
- **Lock Space**: Таблицы блокировок (Shared, Exclusive, LWLocks), доступные всем процессам.

#### Локальная память процесса (Backend Private Memory)
- **Work Mem**: Лимит на одну операцию сортировки или хеширования. Если данных больше — используется диск (Temp Files).
- **Maintenance Work Mem**: Лимит для сервисных операций (`VACUUM`, `CREATE INDEX`). В **PG 17** ограничения на объем памяти для хранения TID при вакууме значительно расширены.
- **Temp Buffers**: Для временных таблиц (`CREATE TEMP TABLE`).

#### Подсистемы SLRU (Simple Least Recently Used)
PostgreSQL использует механизмы SLRU для хранения служебных данных, не помещающихся в Shared Buffers, но требующих быстрого доступа. Эти данные разбиты на страницы (обычно 8 КБ) и кешируются в оперативной памяти.

1.  **CLOG (Commit Log / pg_xact)**: Хранит состояние транзакций (In-progress, Committed, Aborted). Каждая транзакция занимает 2 бита.
2.  **pg_subtrans**: Хранит связи между подтранзакциями и их родителями. Критично для проверки видимости в MVCC.
3.  **pg_multixact**: Используется для групповых блокировок строк (например, несколько `FOR SHARE`).
4.  **LWLocks на SLRU**: При высокой интенсивности транзакций (десятки тысяч TPS) возникают конфликты за защелки (`CLOGControlLock`, `SubtransControlLock`). Решение: увеличение количества буферов SLRU (через системные параметры в новых версиях) или группировка транзакций.

### Физическая структура (PGDATA)

```bash
$ ls -F $PGDATA
base/               # Файлы БД (по подкаталогам с OID БД)
global/             # Общие таблицы инстанса (pg_database, pg_authid)
pg_wal/             # Журналы предзаписи (Write-Ahead Logs)
pg_xact/            # Состояние транзакций (Commit Log)
pg_tblspc/          # Символьные ссылки на внешние табличные пространства
postgresql.conf     # Основной конфиг
pg_hba.conf         # Конфиг аутентификации (Host-Based Authentication)
```

#### Анатомия кортежа (Tuple Layout) и выравнивание
Каждая строка (tuple) в PostgreSQL имеет заголовок и область данных.

**Структура заголовка (HeapTupleHeaderData):**
- **XMIN / XMAX**: ID транзакций создания и удаления.
- **CID / CTID**: Системные идентификаторы.
- **Infomask**: Метаданные состояния.
- **Null Bitmap**: Опциональная битовая карта для NULL-значений.

**Выравнивание данных (Alignment Padding):**
PostgreSQL выравнивает данные на границах 8 байт (для 64-битных систем). Если порядок колонок неоптимален, возникают "пустые" байты (padding).
- **Пример**: `(int2, bigint, int2)` займет больше места, чем `(bigint, int2, int2)`, из-за необходимости выравнивания `bigint` на 8-байтную границу.
- **Рекомендация**: Размещайте фиксированные типы большой длины (`bigint`, `timestamp`) первыми, а мелкие (`int2`, `bool`) — в конце. Это может сэкономить до 20% места на терабайтных таблицах.

**Анатомия файла таблицы:**
- Каждый файл разбит на сегменты по 1 ГБ.
- **_fsm (Free Space Map)**: Битовая карта свободных мест в страницах.
- **_vm (Visibility Map)**: Указывает страницы, где нет "мертвых" строк (для оптимизации VACUUM и Index-Only Scan).

## Практические сценарии

### 1. Расчет и настройка памяти

- **shared_buffers**: Оптимально **25%** от RAM. При значениях > 32ГБ эффективность Clock Sweep может снижаться. Default: 128MB.
- **Huge Pages**: В Linux рекомендуется включить `huge_pages = try/on` для уменьшения оверхеда на управление таблицей страниц (Page Table) при больших объемах RAM.
  ```bash
  # Проверка требуемого количества страниц (2MB по умолчанию)
  head -n 1 $PGDATA/postmaster.pid # Получить PID
  pmap -d <PID> | grep shared      # Оценить объем
  ```

**Ожидаемый результат:**
```text
# head -n 1 $PGDATA/postmaster.pid
12345
# pmap -d 12345 | grep shared
00007f...  131072K rw-s- 00000000  00000000  /dev/zero (загружено в shared_buffers)
```

### 2. Диагностика использования Shared Buffers
Требует расширения `pg_buffercache`.
```sql
CREATE EXTENSION pg_buffercache;

SELECT c.relname, count(*) AS pages, usagecount
FROM pg_buffercache b
JOIN pg_class c ON b.relfilenode = pg_relation_filenode(c.oid)
WHERE datapath IS NOT NULL
GROUP BY c.relname, usagecount
ORDER BY usagecount DESC;
```

**Ожидаемый результат:**
```text
      relname       | pages | usagecount
---------------------+-------+------------
 pg_class            |    12 |         10
 users               |   245 |          8
 ...
```

### 3. Жизненный цикл запроса (Tracing)

1. **Parser**: Проверка синтаксиса.
2. **Analyzer/Rewriter**: Развертывание View и применение правил (`Rules`).
3. **Planner**: Построение дерева путей и выбор самого дешевого на основе стоимостной модели (MCV, гистограммы). Подробности: **[Математика планировщика](./planner_internals.md)**.
4. **Executor**: Обращение к **Shared Buffers** или диску.

**Проверка планировщика:**
```sql
EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
SELECT * FROM users WHERE email = 'test@example.com';
-- Смотрите на 'shared hit' (кэш) и 'shared read' (диск)
```

**Ожидаемый результат:**
```text
 Seq Scan on users  (cost=0.00..25.88 rows=6 width=152) (actual time=0.015..0.018 rows=6 loops=1)
   Buffers: shared hit=3
 Planning:
   Buffers: shared hit=5
```

### 4. Управление TOAST
TOAST (The Oversized-Attribute Storage Technique) срабатывает, когда строка не влезает в страницу.
- **Стратегии**: `PLAIN` (всегда в строке), `EXTENDED` (сжатие + вне кучи), `EXTERNAL` (вне кучи без сжатия), `MAIN` (сжатие внутри кучи).
- **Диагностика**:
  ```sql
  SELECT relname, lp.attname, lp.attstorage 
  FROM pg_attribute lp 
  JOIN pg_class c ON lp.attrelid = c.oid 
  WHERE c.relname = 'my_table';
  ```

**Ожидаемый результат:**
```text
  relname  | attname | attstorage
-----------+---------+------------
 my_table  | data    | x  (EXTENDED)
 my_table  | comment | p  (PLAIN)
```

### 5. Мониторинг для SRE
Для системного администратора критично отслеживать потребление ресурсов инстансом.

```sql
-- Проверка статуса кластера и recovery
SELECT pg_is_in_recovery(), pg_is_wal_replay_paused();

-- Размер PGDATA и отдельных БД
SELECT pg_size_pretty(sum(pg_database_size(oid))) FROM pg_database;

-- Статус WAL: количество сегментов, размер, архивация
SELECT archived_count, failed_count, last_archived_wal, last_archived_time
FROM pg_stat_archiver;

-- Активные подключения и подготовленные транзакции
SELECT count(*) AS active, count(*) FILTER (WHERE state = 'idle') AS idle,
       count(*) FILTER (WHERE wait_event_type IS NOT NULL) AS waiting
FROM pg_stat_activity;

-- Размер shared_buffers в памяти
SHOW shared_buffers;

-- Работа autovacuum
SELECT schemaname, relname, last_vacuum, last_autovacuum, n_dead_tup
FROM pg_stat_user_tables
WHERE n_dead_tup > 10000
ORDER BY n_dead_tup DESC;
```

**Ожидаемый результат:**
```text
 pg_is_in_recovery | pg_is_wal_replay_paused
--------------------+------------------------
 f                  | f

 archived_count | failed_count | last_archived_wal |   last_archived_time
----------------+--------------+-------------------+-------------------------------
           1423 |            0 | 000000010000000A | 2026-10-02 12:30:00+00
```

### 6. Проверка целостности на уровне файловой системы
```bash
# Проверка контрольной суммы кластера
pg_controldata $PGDATA

# Проверка секций WAL на повреждение
pg_waldump $PGDATA/pg_wal/000000010000000A000000XX 2>&1 | head

# Список таблиц с filenode, отличным от OID (возможна проблема с filenode mapping)
SELECT c.relname, c.relfilenode, c.oid
FROM pg_class c
WHERE c.relfilenode != c.oid
  AND c.relkind = 'r';
```

**Ожидаемый результат (pg_controldata):**
```text
Catalog version number:            202505201
Database system identifier:        7200001234567890
Database cluster state:            in production
...
Latest checkpoint location:        000000010000000A000000AB
...
```

## Лучшие практики и очистка

### Рекомендации для SRE/Sysadmin

1. **Дисковая подсистема**: Отдельный диск/раздел для `pg_wal` (WAL), отдельный для `base/` (данные), отдельный для бэкапов. На SSD/NVMe — WAL на выделенный device для минимизации latency.
2. **Синхронизация времени**: NTP обязателен. Логическая репликация и `commit_timestamp` ломаются при рассинхронизации часов.
3. **Мониторинг**: `pg_stat_activity`, `pg_stat_archiver`, `pg_stat_bgwriter`, `pg_stat_database` — базовый набор для Prometheus/Grafana или Zabbix.
4. **Shared Buffers**: 25% RAM для dedicated сервера. Не > 40% — OS cache тоже важен.
5. **Huge Pages**: Включите `huge_pages = on` на Linux для инстансов > 32GB RAM. Проверяйте через `grep Huge /proc/meminfo`.
6. **Автовакуум**: Мониторьте `n_dead_tup` и `last_autovacuum`. Если autovacuum не успевает — настройте `autovacuum_vacuum_scale_factor` и `autovacuum_work_mem`.
7. **WAL**: `wal_buffers` = -1 (autotune, default 128MB). `max_wal_size` >= 2GB для OLTP, >= 10GB для analytics.
8. **Безопасность**: `ssl = on` в production, `pg_hba.conf` — `hostssl` только, `ssl_min_protocol_version = TLSv1.2`.

### Откат и очистка

- **Сброс параметров конфигурации**: `ALTER SYSTEM RESET <parameter>;` + `pg_ctl reload;`
- **Удаление неиспользуемых расширений**: `DROP EXTENSION pg_buffercache;`
- **Очистка временных файлов**: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle';` — при необходимости.
- **Восстановление после сбоя конфигурации**: запуск через `postgres -D $PGDATA -c config_file=/path/to/fallback.conf`

## Дополнительная информация

### Синхронизация и блокировки
На архитектурном уровне PostgreSQL использует:
- **Spinlocks**: Быстрые блокировки для очень коротких операций (единицы инструкций).
- **LWLocks (Lightweight Locks)**: Защищают структуры данных в общей памяти (например, конкретный буфер).
- **Regular Locks**: Блокировки таблиц и строк на уровне SQL.

### Сравнение версий

| Версия | Ключевые изменения в архитектуре |
|--------|----------------------------------|
| PG 15  | `vacuum_buffer_usage_limit` (VACUUM использует ограниченное число shared buffers), улучшения в parallel vacuum |
| PG 16  | Поддержка `maintenance_work_mem` для `CREATE INDEX CONCURRENTLY` с параллелизмом, улучшения в SLRU buffers |
| PG 17  | **TidStore** в autovacuum (эффективное хранение TID в RAM), **Walsummarizer** (инкрементальные бэкапы), `vacuum_buffer_usage_limit` default 2MB |
| PG 18  | `EXPLAIN (BUFFERS)` теперь по умолчанию (раньше требовал явного указания), улучшения в планировщике и executor |

### Смежные темы
- Настройка производительности: **[Performance Tuning](../Operations/performance_tuning.md)**
- Механизм транзакций: **[Concurrency and Locking](./concurrency_and_locking.md)**
- Журналирование: **[Write Ahead Log (WAL)](../../Concepts/write_ahead_log.md)**
- Репликация: **[Replication в PostgreSQL](./replication.md)**
- Восстановление после сбоев: **[Corruption Recovery](./corruption_recovery.md)**
