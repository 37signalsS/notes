# Репликация в PostgreSQL

**Актуально для:** PostgreSQL 15–18

## Определения

- **Репликация** — процесс дублирования данных, при котором информация с основного сервера (**Master/Primary**) автоматически копируется на один или несколько вспомогательных серверов (**Replica/Standby**).
- **Физическая репликация (Physical Replication)**: Побайтовая передача данных. Реализуется через механизм **Streaming Replication**. Реплика является точной бинарной копией основного сервера.
- **Логическая репликация (Logical Replication)**: Передача изменений на уровне отдельных строк или таблиц по принципу «издатель — подписчик» (**Publisher-Subscriber**). Основана на декодировании WAL в поток логических изменений.
- **WAL (Write-Ahead Log)**: Журнал предзаписи транзакций. Фундамент для всех видов репликации: все изменения сначала фиксируются в WAL, а затем передаются на реплики.
- **LSN (Log Sequence Number)**: Уникальный 64-битный идентификатор позиции в WAL. Используется для синхронизации и определения "отставания" (lag) реплик.
- **Репликационный слот (Replication Slot)**: Механизм на источнике, гарантирующий, что необходимые WAL-файлы не будут удалены до тех пор, пока они не будут успешно переданы на реплику. Предотвращает разрыв связи, но несет риск переполнения диска при длительном простое реплики.
- **Replication Origin**: Механизм идентификации источника изменений в логической репликации, позволяющий избежать циклов при двунаправленной репликации.
- **Synchronous Standby Names**: Список реплик, которых должен ждать мастер при синхронной репликации перед подтверждением транзакции.
- **Promote**: Переключение реплики в режим записи (Primary). Выполняется через команду `pg_ctl promote` или создание файла `promote.signal` (PG 16+).
- **pg_rewind**: Утилита для быстрого возврата бывшего мастера в состав кластера после failover без необходимости полной перебазы.
- **Cascading Replication (Каскадная репликация)**: Топология, в которой Standby-сервер сам выступает источником для других реплик, снижая нагрузку на Primary.
- **WAL Archiver**: Фоновый процесс или внешний механизм, переносящий заполненные WAL-сегменты в архивное хранилище для PITR и бэкапов.

## Цели репликации

1.  **Повышение отказоустойчивости (High Availability)**: При выходе из строя основного сервера одна из реплик может быть повышена до мастера.
2.  **Повышение производительности (Read Scaling)**: Распределение нагрузки путем направления SELECT-запросов на реплики.
3.  **Географическое распределение**: Размещение данных ближе к пользователям.
4.  **Снятие нагрузки (Offloading)**: Выполнение бэкапов или тяжелой аналитики на реплике без влияния на Primary.

## Базовые концепции

### Архитектура репликации

Все механизмы репликации опираются на **WAL (Write-Ahead Log)**. Последовательность работы:

1.  **Запись**: Любое изменение данных записывается в буфер WAL на shared_buffers.
2.  **Сброс на диск (WAL Writer)**: Фоновый процесс `walwriter` сбрасывает WAL-буферы на диск в `pg_wal`.
3.  **Передача (Walsender)**: На Primary процесс `walsender` читает WAL и передает изменения:
    -   **Физическая**: байт-в-байт по протоколу Streaming Replication.
    -   **Логическая**: через логическое декодирование (Logical Decoding) в формат изменений (INSERT/UPDATE/DELETE).
4.  **Прием (Walreceiver)**: На Standby процесс `walreceiver` принимает WAL и записывает в локальный `pg_wal`.
5.  **Применение (Startup/Apply Worker)**: Процесс `startup` (физическая) или apply worker (логическая) накатывает изменения на данные.

**Важно для SRE:** Суперпользователь `postgres` на Primary может читать все данные, передаваемые на реплики. Репликация не шифрует трафик между узлами. Для защиты канала используйте SSL/TLS (`ssl = on` + `hostssl` в `pg_hba.conf`) или VPN/Stunnel между хостами.

### Потоковая репликация (Streaming Replication)

Основной тип физической репликации. Процесс `walsender` на мастере читает WAL и отправляет его процессу `walreceiver` на реплике.

**Режимы синхронизации:**

| Режим | Описание | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Асинхронная** | Мастер подтверждает транзакцию сразу после локальной записи. | Максимальная скорость. | Риск потери данных при сбое мастера. |
| **Синхронная** | Мастер ждет подтверждения записи в WAL на реплике. | Гарантированная сохранность. | Снижение производительности из-за задержек сети. |

**Особенности:**
- Реплицируется весь инстанс БД целиком.
- Требуется идентичная мажорная версия PostgreSQL и архитектура ОС.
- **Hot Standby**: Позволяет использовать реплику для запросов на чтение.

**Каскадная репликация (Cascading Replication):**
Standby-сервер может сам выступать `walsender` для следующих реплик. Это снижает нагрузку на Primary и ускоряет доставку WAL в географически распределенных кластерах. В PostgreSQL 18 поддерживается неограниченная глубина каскада.

### Логическая репликация

Работает по модели **Публикация (Publication)** — **Подписка (Subscription)**. Процесс `walsender` выполняет логическое декодирование (Logical Decoding) WAL-записей в сообщения об изменениях (INSERT/UPDATE/DELETE).

**Ключевые возможности и улучшения (PG 16/17):**
- **Выборочная репликация**: Только нужные таблицы или строки (фильтрация через `WHERE`).
- **Разные версии**: Работа между разными мажорными версиями PostgreSQL (идеально для миграций).
- **Репликация со Standby (PG 16)**: Теперь логическое декодирование может выполняться на Standby-сервере, что полностью снимает нагрузку с основного мастера.
- **Репликация последовательностей (PG 17)**: Нативная поддержка синхронизации `sequences`, что упрощает переключение (failover) приложений.
- **Failover слотов (PG 17)**: Синхронизация логических слотов между мастером и физической репликой позволяет логическим подписчикам бесшовно продолжать работу после переключения мастера.

**Ограничения:**
- Не реплицируются DDL (`CREATE TABLE`, `ALTER`), кроме случаев использования специализированных триггеров.
- Требуется `PRIMARY KEY` или `REPLICA IDENTITY FULL` (последнее существенно увеличивает нагрузку на WAL).

### Архивация WAL (WAL Archiving)

Параллельно со Streaming Replication рекомендуется настраивать archival WAL для PITR и защиты от потери данных, если реплика отстает.

**На Primary:**
```ini
archive_mode = on
archive_command = 'test ! -f /var/lib/postgresql/wal_archive/%f && cp %p /var/lib/postgresql/wal_archive/%f'
```

**Важно для SRE:**
- `archive_command` выполняется под пользователем ОС, от которого запущен PostgreSQL. Убедитесь, что у него есть права на запись в целевую директорию.
- При использовании сетевого хранилища (NFS, S3 via s3fs) учитывайте задержку и возможность потери WAL при сбое сети.
- Для production-grade archival используйте инструменты: `pgBackRest`, `WAL-G`. Они поддерживают сжатие, шифрование, retention policies и параллельные бэкапы.

### Failover и Promote

**Ручное переключение (Promote):**
```bash
# На реплике: переключение в режим Primary
pg_ctl promote -D /var/lib/postgresql/data
# Или (PG 16+):
touch /var/lib/postgresql/data/promote.signal
```

**Возврат бывшего мастера (pg_rewind):**
Если бывший Primary не был поврежден, `pg_rewind` быстро синхронизирует его с новым Primary без полной перебазы:
```bash
pg_rewind --source-server="host=new_primary port=5432 dbname=postgres" --target-pgdata=/var/lib/postgresql/data
```

**Каскадная репликация и Failover:**
При promote Standby 1 (каскадного) логические подписчики, подключенные к нему, продолжат работу без перенастройки, если `sync_replication_slots = on` был включен на физическом Standby.

## Уровни синхронизации (synchronous_commit)

Параметр управляет балансом между производительностью и гарантией сохранности.

| Значение | Описание | Гарантия |
| :--- | :--- | :--- |
| **`remote_apply`** | Ждет записи в WAL и **применения** данных на реплике. | Самая высокая (чтение актуально сразу). |
| **`on`** (Default) | Ждет записи в WAL на **диск** реплики. | Оптимальный баланс для HA. |
| **`remote_write`** | Ждет получения WAL в **память** (кэш ОС) реплики. | Риск потери при сбое питания реплики. |
| **`local`** | Подтверждает запись только в локальный WAL. | Асинхронный режим для реплик. |

**Важно:** Даже при включенной синхронной репликации отдельные транзакции могут использовать `SET LOCAL synchronous_commit = local` для снижения задержки.

### synchronous_standby_names

Параметр `synchronous_standby_names` в `postgresql.conf` определяет, какие реплики считаются синхронными:

```ini
# Требовать подтверждения от любой из 2 реплик (кворум)
synchronous_standby_names = 'ANY 2 (standby1, standby2, standby3)'

# Требовать подтверждения от первой доступной реплики в списке
synchronous_standby_names = 'FIRST 1 (standby1, standby2)'
```

**Для SRE:** Используйте `ANY N` для кворумной модели (устойчивость к потере одной реплики) и `FIRST N` для приоритетной модели (гарантия порядка промоции). Без этого параметра синхронная репликация не работает — все транзакции ведут себя как `local`.

## Практические сценарии

### Предварительные требования

1.  **Сетевая связность**: Реплика должна иметь доступ к порту мастера (по умолчанию 5432).
2.  **Настройки ОС**: `max_files_per_process` и лимиты памяти должны быть достаточными. Отключите `transparent_hugepage` для процессов PostgreSQL.
3.  **Пользователь**: Выделенная роль с атрибутом `REPLICATION`.
4.  **Метод аутентификации**: Рекомендуется `scram-sha-256`.
5.  **Синхронизация времени**: На всех узлах кластера настройте NTP. Отставание часов более 1 секунды может вызвать проблемы с сертификатами SSL и race conditions при логической репликации.
6.  **Диски**: Выделите отдельный диск/partition для `pg_wal` на Primary и Standby. Это снижает задержку WAL и упрощает мониторинг.

### 1. Настройка потоковой репликации (физической)

Подробное пошаговое руководство: **[Настройка потоковой репликации](../Operations/replication_setup.md)**.

**На стороне Primary:**
1. Настроить `postgresql.conf`:
    ```ini
    wal_level = replica
    max_wal_senders = 10
    wal_keep_size = 1GB
    # Для синхронной репликации:
    synchronous_standby_names = 'ANY 1 (standby1)'
    ```
2. Создать пользователя: `CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'strong_password';`
3. Добавить в `pg_hba.conf`: `host replication replicator <replica_ip>/32 scram-sha-256`

**На стороне Standby:**
1. Снять базовую копию:
    ```bash
    # Остановка текущего сервиса и очистка PGDATA
    systemctl stop postgresql
    rm -rf /var/lib/postgresql/data/*
    
    # Создание копии
    pg_basebackup -h <primary_ip> -U replicator -D /var/lib/postgresql/data -P -R --slot=replica_1
    ```
    *Флаг `-R` создаст `standby.signal` и `postgresql.auto.conf` с параметрами подключения.*

### 2. Настройка логической репликации (PG 17)

**Публикация (Publisher):**
```sql
-- Создание публикации для таблиц и всех последовательностей (PG 17)
CREATE PUBLICATION sales_pub 
FOR TABLE orders, users, 
    ALL SEQUENCES IN SCHEMA public;
```

**Подписка (Subscriber):**
```sql
-- Создание подписки
CREATE SUBSCRIPTION sales_sub 
CONNECTION 'host=<primary_ip> dbname=mydb user=replicator password=...' 
PUBLICATION sales_pub;
```

**Синхронизация слотов при Failover (PG 17):**
1. На Primary создать слот с флагом `failover`:
```sql
SELECT pg_create_logical_replication_slot('my_slot', 'pgoutput', false, true);
```
2. На физическом Standby включить: `sync_replication_slots = on`.

### 3. Использование pg_createsubscriber (PG 17)

Новая утилита для быстрого преобразования физической реплики в логическую (идеально для "бесшовной" миграции).
```bash
pg_createsubscriber -d "host=master_node dbname=mydb" -s "host=standby_node dbname=mydb" -p 5432 -D /var/lib/postgresql/data
```

## Мониторинг и диагностика

### Проверка отставания (Lag) и статуса
На Primary через `pg_stat_replication`:
```sql
SELECT client_addr, state, sync_state,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)) AS send_lag,
       pg_size_pretty(pg_wal_lsn_diff(sent_lsn, write_lsn)) AS write_lag,
       pg_size_pretty(pg_wal_lsn_diff(write_lsn, flush_lsn)) AS flush_lag,
       pg_size_pretty(pg_wal_lsn_diff(flush_lsn, replay_lsn)) AS replay_lag;
```

### Статус на Standby
```sql
SELECT pg_is_in_recovery() AS is_replica, 
       pg_last_wal_receive_lsn() AS last_received, 
       pg_last_wal_replay_lsn() AS last_replayed,
       now() - pg_last_xact_replay_timestamp() AS last_apply_delay;
```

### Мониторинг replication slots
```sql
-- Проверка состояния слотов на Primary
SELECT slot_name, slot_type, active, 
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal,
       wal_status
FROM pg_replication_slots;
```

### Валидация репликации

```sql
-- Проверка статуса расширения репликации
SELECT extname, extversion FROM pg_extension WHERE extname IN ('pgoutput', 'test_decoding');

-- Проверка подписок
SELECT subname, subenabled, subrelid::regclass AS table_name
FROM pg_subscription;

-- Проверка статуса WAL архивации
SELECT archived_count, failed_count, last_archived_wal, last_failed_wal, last_failed_time
FROM pg_stat_archiver;
```

## Типичные проблемы и пограничные случаи

1.  **WAL Bloat**: Слот репликации "держит" WAL-файлы, если реплика отключена. 
    - *Симптом:* Резкий рост занимаемого места в `pg_wal`.
    - *Решение:* Удалить неактивный слот `SELECT pg_drop_replication_slot('slot_name');`.
    - *Профилактика:* Установите `max_slot_wal_keep_size = 10GB` (или подходящее значение) в `postgresql.conf`. При достижении лимита слот автоматически становится невалидным.
2.  **Конфликты логической репликации**: Ошибка `duplicate key value violates unique constraint` на подписчике.
    - *Причина:* Прямая запись данных на подписчик, которые затем приходят по репликации.
    - *Решение:* Запретить запись на подписчик (RLS или права) или использовать `SKIP` в настройках подписки (PG 15+).
3.  **Vacuum и Репликация**: На Standby может возникнуть ошибка `User query might have needed a row version that must be removed`.
    - *Решение:* Сначала сократите длительные запросы на standby и настройте vacuum. `hot_standby_feedback = on` может предотвратить конфликты, но удерживает `xmin` и способен увеличить bloat и WAL на primary; включайте его только после оценки этого компромисса.
4.  **Разрыв репликации (Disconnected Replication)**: Реплика перестает принимать WAL из-за сетевого разрыва.
    - *Диагностика:* Проверьте `state = 'streaming'` в `pg_stat_replication`. Если `state = 'catchup'` — реплика пытается догнать. Если долго не догоняет — проверьте сеть и `wal_receiver_timeout`.
    - *Решение:* Убедитесь, что `wal_keep_size` достаточен для быстрого переподключения, или используйте replication slots.
5.  **Исчерпание worker processes**: При большом числе подписок логическая репликация может исчерпать `max_worker_processes`.
    - *Решение:* Увеличьте `max_worker_processes` с запасом: `max_logical_replication_workers + max_parallel_apply_workers_per_subscription + 10`.
6.  **Сетевые задержки и синхронная репликация**: Высокий ping между Primary и Standby вызывает рост latency всех транзакций.
    - *Решение:* Размещайте Standby в том же дата-центре. Для географического распределения используйте асинхронную репликацию + WAL archiving, а не синхронную.
7.  **pg_basebackup зависает**: При больших базах `pg_basebackup` может зависнуть из-за долгих запросов или блокировок.
    - *Решение:* Используйте `--checkpoint=fast` (PG 17+) для ускорения. Для минимального влияния на prod выполняйте бэкап на Standby, а не на Primary.

## Лучшие практики и очистка

*   **Сеть:** Для Streaming Replacement размещайте Primary и Standby в одной подсети/VLAN с низким latency (<1 мс). Используйте SSL/TLS между узлами (`hostssl` в `pg_hba.conf` + сертификаты).
*   **Синхронная репликация:** Используйте `synchronous_standby_names` только когда у вас минимум 2 Standby. Один Standby не дает отказоустойчивости: при его падении Primary блокируется до его возврата или ручного `SET LOCAL synchronous_commit = local`.
*   **Слоты:** Никогда не создавайте replication slots без плана их мониторинга. Ограничьте `max_slot_wal_keep_size`. Для временных слотов используйте `TEMPORARY` (они автоматически удаляются при разрыве соединения).
*   **Мониторинг:** Отслеживайте `pg_stat_replication.sync_state`, lag в байтах/секунду, `pg_replication_slots.wal_status`. Настройте алерты при `replay_lag > 30s` или `retained_wal > 50GB`.
*   **WAL Archiving:** Архивируйте WAL независимо от репликации. Репликация защищает от сбоя одного узла; archival защищает от логической ошибки (DROP TABLE) и обеспечивает PITR.
*   **hot_standby_feedback:** Включайте только если у вас долгие аналитические запросы на Standby, и готовы мириться с ростом `xmin` и WAL на Primary. Для коротких запросов выключение параметра безопаснее.
*   **pg_rewind:** Регулярно тестируйте сценарий `pg_rewind` на стенде. На production он критичен для быстрого возврата бывшего мастера после автоматического failover.
*   **Резервное копирование:** Бэкапы должны сниматься с Standby, а не с Primary, чтобы не нагружать мастер. Используйте `pg_basebackup --format=tar` с WAL streaming (`-X stream`).
*   **Версии:** Для логической репликации между версиями оставляйте минимум 1–2 minor version разрыва (например, PG 16 → PG 17). После миграции обновите подписку до текущей версии.

### Откат и очистка

1.  **Удаление подписки (логическая репликация):**
    ```sql
    DROP SUBSCRIPTION sales_sub;
    ```
    *Примечание:* Удаление подписки не удаляет данные на подписчике. Для полного удаления выполните `TRUNCATE` вручную.

2.  **Удаление репликационного слота:**
    ```sql
    SELECT pg_drop_replication_slot('slot_name');
    ```

3.  **Остановка репликации и переход в режим Primary (физическая):**
    ```bash
    # Удалить standby.signal
    rm /var/lib/postgresql/data/standby.signal
    # Или выполнить promote
    pg_ctl promote -D /var/lib/postgresql/data
    ```

## Сравнение типов репликации

| Тип | Скорость | Гибкость | Поддержка DDL | Failover | Использование |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Физическая Streaming** | Высокая (байт-в-байт) | Низкая (весь кластер) | Да | Да (Patroni/repmgr) | HA, Read Scaling |
| **Каскадная Streaming** | Средняя (через промежуточный) | Средняя | Да | Да | Географическое распределение |
| **Логическая (PG 17)** | Средняя (декодирование) | Высокая (таблицы/строки) | Нет (нужны триггеры) | Да (sync slots) | Миграции, шардирование, CDC |

### См. также
- [Настройка потоковой репликации](../Operations/replication_setup.md)
- [High Availability в PostgreSQL](./high_availability.md)
- [Write Ahead Log (WAL)](../../Concepts/write_ahead_log.md)
- [Бэкапы и восстановление](../Concepts/backup_and_recovery.md)
- [Официальная документация: Streaming Replication](https://www.postgresql.org/docs/18/warm-standby.html)
- [Официальная документация: Logical Replication](https://www.postgresql.org/docs/18/logical-replication.html)
