# Миграция PostgreSQL без простоя (Zero-Downtime)

**Актуально для:** PostgreSQL 14–18 (текущий stable — 18, релиз 2025-09-25; нативная репликация последовательностей появится только в PostgreSQL 19)

## Определения

*   **Миграция без простоя (Zero-Downtime Migration)** — процесс переноса базы данных, при котором время недоступности ограничено только переключением (Cutover) трафика приложения: обычно от нескольких секунд до минуты.
*   **Cutover (переключение)** — финальный этап миграции: запись на источнике останавливается, лаг репликации обнуляется, трафик приложения переключается на целевой сервер.
*   **Лаг (Lag)** — отставание подписчика от издателя, измеряемое в байтах WAL (разница LSN) или во времени.
*   **Логическая репликация (Logical Replication)** — механизм передачи изменений на уровне строк, основанный на декодировании WAL в поток логических сообщений. Позволяет передавать данные между разными мажорными версиями PostgreSQL (например, с 12 на 18) и между разными платформами (Linux → Windows).
*   **Издатель (Publisher) / Подписчик (Subscriber)** — узлы источника и приёмника соответственно. Подписчик вытягивает изменения из публикаций и может сам быть издателем (каскадная репликация).
*   **Публикация (Publication)** — объект на издателе, определяющий набор таблиц (и операций) для репликации.
*   **Подписка (Subscription)** — объект на подписчике, определяющий соединение с издателем и набор публикаций. Создаёт слот репликации на издателе.
*   **Слот репликации (Replication Slot)** — механизм на издателе, гарантирующий, что WAL не удаляется до передачи подписчику. Неактивный слот удерживает WAL до заполнения диска.
*   **LSN (Log Sequence Number)** — 64-битный идентификатор позиции в WAL, используется для отслеживания прогресса репликации.
*   **REPLICA IDENTITY** — параметр таблицы, определяющий, какая информация о старой версии строки записывается в WAL при UPDATE/DELETE: `DEFAULT` (первичный ключ, если есть), `INDEX` (конкретный уникальный индекс), `FULL` (вся строка), `NOTHING` (только INSERT реплицируется).
*   **Expand-Contract** — паттерн применения DDL при миграции: сначала аддитивное изменение на подписчике, затем на издателе, чтобы репликация не прерывалась.

## Базовые концепции

### Выбор метода миграции

| Метод | Простой | Между мажорными версиями | Скорость | Основные ограничения |
| :--- | :--- | :--- | :--- | :--- |
| `pg_upgrade` | полный (останов кластера) | да | минуты | та же архитектура ОС; статистика сохраняется только с PG 18; пошаговая процедура — в [pg_upgrade](./pg_upgrade.md) |
| `pg_dump` / `pg_restore` | полный (время восстановления) | да | медленно на больших БД | см. [Logical Backup Migration](./logical_backup_migration.md) |
| Логическая репликация | секунды (только Cutover) | да | начальная копия + накатка | нет DDL, последовательностей (≤18), больших объектов |

### Архитектура процесса

Модель «издатель — подписчик» (Publisher-Subscriber):
1.  **Начальная синхронизация (Snapshot):** подписчик делает снапшот таблиц и копирует текущее состояние (через COPY).
2.  **Накатка (Catch-up):** после копирования снапшота подписчик применяет изменения, произошедшие во время копирования, из потока логического декодирования.
3.  **Синхронное состояние:** лаг стремится к нулю — система готова к Cutover.

### Совместимость версий и формат данных

*   Репликация между разными мажорными версиями — штатный вариант использования (use-case из документации).
*   Таблицы сопоставляются по полному имени (`schema.table`), столбцы — по имени; порядок столбцов на подписчике может отличаться.
*   Типы данных должны иметь совместимое текстовое представление (`integer` → `bigint` работает). Текстовый формат (по умолчанию) более гибок; бинарный (`binary = true`) строже, а начальная синхронизация в бинарном формате требует издателя PostgreSQL 16+ и наличия binary send/receive функций у всех типов.
*   Столбцы, добавленные на подписчике сверх публикации, заполняются значениями по умолчанию.

### Ключевые возможности по версиям

*   **PostgreSQL 14:** потоковая передача незакоммиченных транзакций (`streaming = 'on'`).
*   **PostgreSQL 15:** фильтры строк (`WHERE`), списки столбцов, партиционированные таблицы в публикациях, two-phase commit (`two_phase`), `run_as_owner` (default `false`), `ALTER SUBSCRIPTION ... SKIP`.
*   **PostgreSQL 16:** `streaming = 'parallel'` (параллельное применение), `FOR TABLES IN SCHEMA`, начальная синхронизация в бинарном формате.
*   **PostgreSQL 17:** утилита `pg_createsubscriber` (создание логической реплики из физической standby), failover-слоты (`failover` + `sync_replication_slots`), `pg_upgrade` сохраняет слоты и состояние подписок (для кластеров 17+), хеш-индексы для применения изменений.
*   **PostgreSQL 18:** `streaming = 'parallel'` стал значением по умолчанию; репликация generated-столбцов (`publish_generated_columns`); логирование конфликтов в `pg_stat_subscription_stats`; предопределённая роль `pg_create_subscription`; `password_required` (default `true`); `idle_replication_slot_timeout` (автоинвалидация неактивных слотов); whitelist output-плагинов `output_plugin_libraries` (18.6 и бэкпорты в поддерживаемые ветки, default `'pgoutput, test_decoding'`). AIO-подсистема PG 18 ускоряет sequential scans, bitmap heap scans и vacuum — для логического декодирования это не заявлено.
*   **PostgreSQL 19:** нативная репликация последовательностей (`CREATE PUBLICATION ... FOR ALL SEQUENCES`, требует издателя 19+).

## Предварительные требования

1.  **Версии:** логическая репликация поддерживается между мажорными версиями начиная с PG 10; целевой сервер должен быть не ниже 14 для рассматриваемых здесь опций.
2.  **Сеть:** TCP/5432 от подписчика к издателю (firewall, VPN или peering между площадками; в Kubernetes — NetworkPolicy).
3.  **`pg_hba.conf` на издателе:** доступ для роли репликации, например:
    ```ini
    host    replication     migration_user    10.0.0.0/24    scram-sha-256
    ```
    MD5-аутентификация объявлена устаревшей в PG 18 — используйте SCRAM-SHA-256.
4.  **Привилегии:**
    *   Роль репликации: атрибут `REPLICATION` (или суперпользователь), `LOGIN`, `SELECT` на публикуемые таблицы.
    *   Создание публикации: `CREATE` в базе; добавление таблиц — право владения таблицей; `FOR ALL TABLES` / `FOR TABLES IN SCHEMA` — только суперпользователь.
    *   Создание подписки (PG 18+): роль `pg_create_subscription` (по умолчанию у владельца базы) и `CREATE` в базе.
5.  **Место на диске:** запас на издателе для WAL, удерживаемого слотом, пока подписчик отстаёт или недоступен.
6.  **Расширения:** необходимые расширения должны быть созданы на подписчике вручную — расширения не реплицируются.
7.  **`wal_level = logical`** на издателе — требует перезапуска.

## Практические сценарии

### Сценарий: Миграция на новую мажорную версию (например, 14 → 18)

#### Шаг 1: Подготовка исходного сервера (Source)

1.  **Настройка `postgresql.conf`:**
    ```ini
    # postgresql.conf (requires restart)
    wal_level = logical
    max_replication_slots = 10
    max_wal_senders = 10
    # Memory cap per logical decoding connection before spilling to disk (default 64MB, PG 13+)
    logical_decoding_work_mem = 64MB
    ```

2.  **Создание пользователя миграции:**
    ```sql
    -- REPLICATION attribute is required for the replication connection
    CREATE ROLE migration_user WITH REPLICATION LOGIN PASSWORD 'strong_password';
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO migration_user;
    ```

#### Шаг 2: Перенос схемы и подготовка Target

Логическая репликация не переносит DDL. Схему переносят заранее:
```bash
# Schema only; pg_dump client version must be >= source server version
pg_dump -h source_host -U postgres -s --no-owner dbname > schema.sql
psql -h target_host -U postgres -d dbname -f schema.sql
# Roles and tablespaces (global objects are not in pg_dump)
pg_dumpall -h source_host -U postgres -g > roles.sql
psql -h target_host -U postgres -f roles.sql
```
*Важно:* перед началом синхронизации на Target достаточно PK/Unique-индексов. Тяжёлые индексы (GIN/GiST) создавайте после начальной синхронизации через `CREATE INDEX CONCURRENTLY`.

#### Шаг 3: Создание публикации и подписки

1.  **На Source (создание публикации):**
    ```sql
    -- FOR ALL TABLES requires superuser
    CREATE PUBLICATION migration_pub FOR ALL TABLES;
    -- Alternatively, explicit tables:
    -- CREATE PUBLICATION migration_pub FOR TABLE users, orders;
    ```

2.  **На Target (создание подписки):**
    ```sql
    CREATE SUBSCRIPTION migration_sub
    CONNECTION 'host=source_host port=5432 user=migration_user password=strong_password dbname=dbname'
    PUBLICATION migration_pub
    WITH (
        copy_data = true,
        streaming = 'parallel'  -- default since PG 18; parallel apply requires PG 16+
    );
    ```
    *Примечания:*
    *   `CREATE SUBSCRIPTION` с созданием слота нельзя выполнять внутри транзакции.
    *   Параллельные apply-воркеры ограничены `max_logical_replication_workers` (default 4) и `max_sync_workers_per_subscription` (default 2) на подписчике.
    *   Не используйте `run_as_owner = true`: в этом режиме владелец любой реплицируемой таблицы может выполнять код с правами владельца подписки. Документация рекомендует избегать этой опции (доступна с PG 15, default `false` — безопасный режим с переключением на владельца таблицы).
    *   `password_required = true` (default) требует аутентификации по паролю в conninfo.

#### Шаг 4: Мониторинг и тюнинг

**На Source — состояние слота и удержание WAL:**
```sql
SELECT slot_name, plugin, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS slot_lag
FROM pg_replication_slots;
```
**На Source — walsender подписки (application_name = имя подписки):**
```sql
SELECT application_name, state, sent_lsn, write_lsn, flush_lsn, replay_lsn
FROM pg_stat_replication;
```
**На Target — воркеры подписки (ноль строк = подписка отключена или упала):**
```sql
SELECT subname, pid, received_lsn, latest_end_lsn, last_msg_receipt_time
FROM pg_stat_subscription;

-- Apply errors and (PG 18+) conflicts
SELECT * FROM pg_stat_subscription_stats;
```
Если лаг растёт — проверьте `max_logical_replication_workers` / `max_sync_workers_per_subscription` на Target, отсутствие тяжёлых индексов во время `copy_data` и не используется ли `REPLICA IDENTITY FULL`.

#### Шаг 5: Переключение (Cutover)

1.  **Остановка записи:** режим обслуживания в приложении или read-only на Source:
    ```sql
    ALTER SYSTEM SET default_transaction_read_only = on;
    SELECT pg_reload_conf();
    ```
2.  **Финальная проверка:** лаг слота равен 0 (`slot_lag` = 0, `last_msg_receipt_time` свежий).
3.  **Синхронизация последовательностей (PG ≤ 18 — последовательности НЕ реплицируются):**
    ```sql
    -- On target, for each sequence-backed column
    SELECT setval('public.users_id_seq', (SELECT max(id) FROM public.users));
    ```
4.  **Удаление связей:**
    ```sql
    DROP SUBSCRIPTION migration_sub; -- On target (drops the slot on publisher)
    DROP PUBLICATION migration_pub;  -- On source
    ```
5.  **Смена точки входа:** обновите DNS (TTL снизьте заранее, за ~24 часа) или конфигурацию приложения; при использовании PgBouncer — `RELOAD` после смены бэкендов (см. [PgBouncer](./pgbouncer_setup.md)).
6.  **Сбор статистики на Target:** `ANALYZE` — статистика оптимизатора не переносится логической репликацией (см. [Планировщик](../Concepts/planner_internals.md)).

### Валидация после миграции

```sql
-- 1. Row counts on source vs target
SELECT count(*) FROM public.users;

-- 2. Sample checksum (deterministic order; 1000 rows is a sample, not the whole table)
SELECT md5(string_agg(md5(t::text), '' ORDER BY id))
FROM (SELECT * FROM public.users ORDER BY id LIMIT 1000) t;

-- 3. Sequence values on target must be >= source values
SELECT last_value FROM public.users_id_seq;
```
Дополнительно: сверьте версии расширений (`SELECT * FROM pg_extension`), проверьте структурную целостность расширением `amcheck` (`bt_index_check`, `verify_relation`) и убедитесь, что `pg_stat_subscription` не содержит строк после `DROP SUBSCRIPTION`.

### Сценарий: DDL во время миграции (Expand-Contract)

Логическая репликация останавливается при несовпадении схем. Документация рекомендует применять аддитивные изменения схемы на подписчике **первым** — это предотвращает прерывистые ошибки:
1.  Примените DDL на **Target** (Subscriber).
2.  Примените DDL на **Source** (Publisher).
3.  Репликация продолжит работу, так как Target готов принимать новые поля.
Для удаления столбцов — порядок обратный: сначала убрать из использования на Target (или расширить публикацию), затем на Source.

### Сценарий: Миграция с ВМ / bare-metal в Kubernetes

Типичный сценарий: PostgreSQL работает на ВМ или bare-metal, требуется перенести его в Kubernetes без простоя.

**Подводные камни:**
1.  **Сетевые задержки:** высокий latency между площадками увеличивает лаг репликации.
2.  **Firewall/NetworkPolicy:** необходимо разрешить трафик от пода PostgreSQL в K8s к ВМ на порт 5432.
3.  **Размер базы:** на больших БД (>500 ГБ) начальная синхронизация (`copy_data`) может занять часы.
4.  **DNS/Service Discovery:** после переключения приложений на кластер K8s необходимо обновить DNS-записи или конфигурации.

**Порядок действий:**
1.  Разверните PostgreSQL в K8s (оператор или Patroni — см. [Kubernetes Deployment](./kubernetes_deployment.md) и [Patroni](./high_availability_patroni.md)); убедитесь, что `wal_level = logical` на Source.
2.  Настройте сетевую связность и проверьте доступность: `psql -h <k8s-service> -U migration_user -d dbname`.
3.  Перенесите схему и роли (Шаг 2 основного сценария).
4.  На Source (ВМ): `CREATE PUBLICATION migration_pub FOR ALL TABLES;`
    На Target (K8s): `CREATE SUBSCRIPTION migration_sub CONNECTION 'host=vm-host ...' PUBLICATION migration_pub;`
5.  Контролируйте лаг до достижения минимального значения (Шаг 4).
6.  Cutover по Шаг 5: остановка записи, обнуление лага, синхронизация последовательностей, удаление подписки/публикации, переключение приложений на Service K8s.

**Схема переключения ролей:** исходный мастер (ВМ) → останов записи → новый мастер (в K8s). Бывшая ВМ может остаться как физическая реплика **только при совпадении мажорных версий**; при миграции между версиями она выводится из эксплуатации или архивируется.

**Важно:** после переключения проверьте целостность данных, настройте бэкапы нового кластера (см. [WAL-G автоматизация](./backup_automation.md)) и убедитесь, что последовательности синхронизированы.

## Устранение неполадок (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `duplicate key value violates unique constraint` | На Target уже были данные или на Target идёт запись | Очистите таблицы: `TRUNCATE TABLE name CASCADE`; Target должен быть read-only |
| `logical replication target relation ... is missing some replicated columns` | Схемы Source и Target различаются | Примените `ALTER TABLE` на Target первым (Expand-Contract) |
| `relation "..." does not exist` | Схема не создана на Target | Примените `schema.sql` |
| Бесконечный рост WAL на Source | Слот неактивен (`active = f`) | Проверьте логи Target; если миграция заброшена — `SELECT pg_drop_replication_slot('migration_sub');`. В PG 18+: `idle_replication_slot_timeout` автоинвалидирует слот |
| `ERROR: replication slot ... is active for PID ...` | Другая подписка использует этот слот | Уникальные имена; слот по умолчанию именуется как подписка |
| `ERROR: password is required` | `password_required = true` (default) | Укажите пароль (SCRAM) в conninfo подписки |
| `ERROR: logical decoding requires wal_level >= logical` | Не установлен `wal_level` | `wal_level = logical` + перезапуск |
| `ERROR: library "..." may not be used as an output plugin` | Whitelist `output_plugin_libraries` (PG 18.6+/бэкпорты) | Добавьте плагин в список или используйте `pgoutput` |
| Ноль строк в `pg_stat_subscription` | Подписка отключена или воркер упал | `ALTER SUBSCRIPTION migration_sub ENABLE;`, логи Target |
| `ERROR: publication "..." does not exist` | Публикация ещё не создана (допустимо) | Создайте публикацию, затем `ALTER SUBSCRIPTION ... REFRESH PUBLICATION;` |
| Застряла плохая транзакция | Ошибка применения одной транзакции | `ALTER SUBSCRIPTION ... SKIP (lsn)` (PG 15+) — пропуск одной транзакции |
| Огромный лаг на больших таблицах | Нет параллелизма или тяжёлые индексы | `streaming = 'parallel'`, `max_logical_replication_workers`, отключите лишние индексы на время `copy_data` |
| `ERROR: could not start streaming` / connection refused | pg_hba, firewall, NetworkPolicy | Разрешите `host replication migration_user <подсеть> scram-sha-256` |
| Конфликты при применении | На Target идут записи | Target должен быть read-only; счётчики в `pg_stat_subscription_stats.apply_error_count` |

## Пограничные случаи и ограничения

### Таблицы без первичных ключей
*   Без REPLICA IDENTITY (или с `NOTHING`) UPDATE/DELETE на публикуемых таблицах вызывают ошибку на издателе.
*   `REPLICA IDENTITY FULL`: каждый UPDATE/DELETE передаёт всю строку (рост WAL и нагрузки CPU); на подписчике для поиска строк можно использовать btree/хеш-индексы (непарциальные, левое поле — столбец). Если подходящего индекса нет — последовательное сканирование и катастрофический рост лага.
*   С `REPLICA IDENTITY FULL` UPDATE/DELETE не применяются, если таблица содержит типы без дефолтного operator class для B-tree/Hash (например, `point`, `box`) — решение: задать PK или REPLICA IDENTITY.
*   **Рекомендация:** добавьте хотя бы PK или UNIQUE-индекс.

### Последовательности (PostgreSQL ≤ 18)
Данные последовательностей **не реплицируются**: на подписчике последовательность остаётся на стартовом значении. Для read-only использования это не проблема, но при переключении (switchover/failover) значения нужно обновить вручную: `setval()` из `max(id)` или `pg_dump` со значениями. Нативная репликация (`FOR ALL SEQUENCES`) появится в PostgreSQL 19.

### Большие объекты (Large Objects)
Тип `lo` и функции `lo_create`/`lo_export` не реплицируются, обходного пути нет, кроме хранения данных в обычных таблицах (`bytea`).

### Нереплицируемые объекты
В публикацию не входят: временные таблицы, UNLOGGED-таблицы, foreign tables, materialized views, обычные views — попытка добавить их вызывает ошибку. Роли, табличные пространства и расширения переносятся отдельно (`pg_dumpall -g`, `CREATE EXTENSION`).

### TRUNCATE и внешние ключи
TRUNCATE реплицируется (по умолчанию), но при усечении группы таблиц, связанных FK, подписчик усекает тот же набор (включая CASCADE) минус таблицы вне подписки. Если усечённая таблица ссылается FK на таблицу вне подписки — применение завершится ошибкой.

### Партиционированные таблицы
По умолчанию изменения публикуются с листовых партиций — партиции издателя должны существовать на подписчике как валидные таблицы. Параметр `publish_via_partition_root = true` публикует изменения от имени корневой партиционированной таблицы (полезно при другой структуре партиций на целевой стороне).

### Длинные транзакции и VACUUM
Начальная синхронизация удерживает снапшот, мешая VACUUM очищать мёртвые строки на Source (рост bloat). Длинные транзакции и массивные операции (`VACUUM FULL`, пересоздание индексов) генерируют огромный поток WAL, который может забить канал логической репликации. `logical_decoding_work_mem` (default 64MB) ограничивает память декодирования на одно соединение.

### Конфликты
Подписчик, принимающий записи извне (приложение, другие подписки), порождает конфликты (например, INSERT существующего PK). Во время миграции Target должен быть read-only; счётчики конфликтов — в `pg_stat_subscription_stats` (PG 18+).

## Лучшие практики

*   **План отката (Rollback):** до Cutover Source заморожен read-only — откат это переключение трафика обратно без потерь. Если запись на Target уже началась — либо поднимите обратную подписку Target → Source, либо фиксируйте расхождение. Не удаляйте публикацию сразу после Cutover.
*   **Алертинг:** слот-лаг (`pg_replication_slots`), `apply_error_count`, отсутствие строк в `pg_stat_subscription`.
*   **Очень большие БД (PG 17+):** `pg_createsubscriber` — поднимите K8s-кластер как физическую standby (`pg_basebackup`), затем преобразуйте её в логического подписчика; это избавляет от долгого окна начальной копии.
*   **HA-источник (PG 17+):** failover-слоты (`WITH (failover = true)` + `sync_replication_slots = on` на издателе) позволяют подписке продолжить работу после failover издателя — полезно, когда Source — кластер Patroni.
*   **Безопасность:** выделенная роль с сильным паролем (conninfo с паролем хранится в `pg_subscription` — ротируйте через `ALTER SUBSCRIPTION ... CONNECTION`), минимальные привилегии, без `run_as_owner`.
*   **Cleanup после миграции:** `DROP SUBSCRIPTION`, `DROP PUBLICATION`, `DROP ROLE migration_user`, удаление строки `pg_hba.conf`.
*   **Тестирование:** сначала прогоните весь цикл на копии базы, замерьте время начальной синхронизации и лаг под боевой нагрузкой.

## Дополнительная информация

*   [Репликация в PostgreSQL](../Concepts/replication.md) — теория физической и логической репликации.
*   [Настройка репликации](./replication_setup.md) — практика настройки.
*   [Logical Backup Migration](./logical_backup_migration.md) — миграция небольших БД с простоем.
*   [Бэкапы и восстановление](../Concepts/backup_and_recovery.md) — `pg_dump`/`pg_dumpall`, правила версий клиента.
*   [Планировщик и статистика](../Concepts/planner_internals.md) — почему нужен `ANALYZE` после восстановления.
*   [Конкурентность и блокировки](../Concepts/concurrency_and_locking.md) — влияние миграции на производительность.
*   [PgBouncer](./pgbouncer_setup.md) — переключение бэкендов при Cutover.
*   [Patroni](./high_availability_patroni.md), [Kubernetes Deployment](./kubernetes_deployment.md), [Kubernetes Connectivity](./kubernetes_connectivity.md) — целевая инфраструктура.
*   [WAL-G автоматизация](./backup_automation.md) — бэкапы нового кластера.
*   Внешние источники: [Chapter 29. Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html), [CREATE PUBLICATION](https://www.postgresql.org/docs/current/sql-createpublication.html), [CREATE SUBSCRIPTION](https://www.postgresql.org/docs/current/sql-createsubscription.html), [Release Notes 18](https://www.postgresql.org/docs/current/release-18.html).
*   `pg_recvlogical` — утилита потребления логического потока (CDC); `pglogical` (2ndQuadrant) — стороннее расширение, предшественник встроенной логической репликации; для новых миграций предпочтительна встроенная реализация.
