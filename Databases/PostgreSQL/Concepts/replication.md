# Репликация в PostgreSQL

## Определения

- **Репликация** — процесс дублирования данных, при котором информация с основного сервера (**Master/Primary**) автоматически копируется на один или несколько вспомогательных серверов (**Replica/Standby**).
- **Физическая репликация (Physical Replication)**: Побайтовая передача данных. Реализуется через механизм **Streaming Replication**. Реплика является точной бинарной копией основного сервера.
- **Логическая репликация (Logical Replication)**: Передача изменений на уровне отдельных строк или таблиц по принципу «издатель — подписчик» (**Publisher-Subscriber**). Основана на декодировании WAL в поток логических изменений.
- **WAL (Write-Ahead Log)**: Журнал предзаписи транзакций. Фундамент для всех видов репликации: все изменения сначала фиксируются в WAL, а затем передаются на реплики.
- **Репликационный слот (Replication Slot)**: Механизм на источнике, гарантирующий, что необходимые WAL-файлы не будут удалены до тех пор, пока они не будут успешно переданы на реплику.

## Цели репликации

1.  **Повышение отказоустойчивости (High Availability)**: При выходе из строя основного сервера одна из реплик может быть повышена до мастера.
2.  **Повышение производительности (Read Scaling)**: Распределение нагрузки путем направления SELECT-запросов на реплики.
3.  **Географическое распределение**: Размещение данных ближе к пользователям.
4.  **Снятие нагрузки (Offloading)**: Выполнение бэкапов или тяжелой аналитики на реплике без влияния на Primary.

## Базовые концепции

### Потоковая репликация (Streaming Replication)

Основной тип физической репликации. WAL-записи передаются в реальном времени.

**Режимы синхронизации:**

| Режим | Описание | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Асинхронная** | Мастер подтверждает транзакцию сразу после локальной записи. | Максимальная скорость. | Риск потери данных при сбое мастера. |
| **Синхронная** | Мастер ждет подтверждения записи в WAL на реплике. | Гарантированная сохранность. | Снижение производительности из-за задержек сети. |

**Особенности:**
- Реплицируется весь инстанс БД целиком.
- Требуется идентичная мажорная версия PostgreSQL и архитектура ОС.
- **Hot Standby**: Позволяет использовать реплику для запросов на чтение.

### Логическая репликация

Работает по модели **Публикация (Publication)** — **Подписка (Subscription)**.

**Ключевые возможности и улучшения (PG 16/17):**
- **Выборочная репликация**: Только нужные таблицы или строки (через `WHERE`).
- **Разные версии**: Работа между разными мажорными версиями PostgreSQL.
- **Репликация со Standby (PG 16)**: Теперь логическое декодирование может выполняться на Standby-сервере, что снимает нагрузку с основного мастера.
- **Failover слотов (PG 17)**: Синхронизация логических слотов между мастером и физической репликой позволяет логическим подписчикам продолжать работу после переключения мастера.

**Ограничения:**
- Не реплицируются DDL (`CREATE TABLE`, `ALTER`).
- Не реплицируются последовательности (`sequences`) и крупные объекты.
- Требуется `PRIMARY KEY` (или `REPLICA IDENTITY FULL`).

## Уровни синхронизации (synchronous_commit)

Параметр управляет балансом между производительностью и гарантией сохранности.

| Значение | Описание | Гарантия |
| :--- | :--- | :--- |
| **`remote_apply`** | Ждет записи в WAL и **применения** данных на реплике. | Самая высокая (чтение актуально сразу). |
| **`on`** (Default) | Ждет записи в WAL на **диск** реплики. | Оптимальный баланс для HA. |
| **`remote_write`** | Ждет получения WAL в **память** (кэш ОС) реплики. | Риск потери при сбое питания реплики. |
| **`local`** | Подтверждает запись только в локальный WAL. | Асинхронный режим для реплик. |

## Практические сценарии

### 1. Настройка потоковой репликации (физической)

Подробное пошаговое руководство: **[Настройка потоковой репликации](../Operations/replication_setup.md)**.

**На стороне Primary:**
1. Настроить `postgresql.conf`:
   ```conf
   wal_level = replica
   max_wal_senders = 10
   wal_keep_size = 1GB
   ```
2. Создать пользователя: `CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'pass';`
3. Добавить в `pg_hba.conf`: `host replication replicator <replica_ip>/32 scram-sha-256`

**На стороне Standby:**
1. Снять базовую копию:
   ```bash
   pg_basebackup -h <primary_ip> -U replicator -D /var/lib/postgresql/data -P -R --slot=replica_1
   ```
   *Флаг `-R` создаст `standby.signal` и `postgresql.auto.conf`.*

### 2. Настройка логической репликации (PG 16/17)

**Публикация с фильтрацией (Publisher):**
```sql
CREATE PUBLICATION sales_pub FOR TABLE orders (id, amount, status) WHERE (status = 'completed');
```

**Подписка со Standby (PG 16):**
Для настройки логической репликации, где источником является Standby-сервер:
1. На Standby: `wal_level = logical`, `hot_standby_feedback = on`.
2. На подписчике:
```sql
CREATE SUBSCRIPTION sales_sub CONNECTION 'host=<standby_ip> dbname=...' PUBLICATION sales_pub;
```

**Синхронизация слотов (PG 17):**
Чтобы логические слоты выжили после Failover физической реплики:
1. На Primary создать слот с поддержкой failover:
```sql
SELECT pg_create_logical_replication_slot('my_slot', 'pgoutput', false, true); -- failover = true
```
2. На Standby включить параметр: `sync_replication_slots = on`.

### 3. Использование pg_createsubscriber (PG 17)

Новая утилита для быстрого преобразования физической реплики в логическую.
```bash
pg_createsubscriber -d "host=master_node dbname=mydb" -s "host=standby_node dbname=mydb" -p 5432 -D /var/lib/postgresql/data
```

## Мониторинг и диагностика

### Проверка отставания (Lag) и статуса
На Primary через `pg_stat_replication`:
```sql
SELECT client_addr, state, sync_state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS send_lag,
       pg_wal_lsn_diff(sent_lsn, write_lsn) AS write_lag,
       pg_wal_lsn_diff(write_lsn, flush_lsn) AS flush_lag,
       pg_wal_lsn_diff(flush_lsn, replay_lsn) AS replay_lag,
       replay_lag AS time_lag
FROM pg_stat_replication;
```

### Статус на Standby
```sql
SELECT pg_is_in_recovery(), 
       pg_last_wal_receive_lsn(), 
       pg_last_wal_replay_lsn(),
       now() - pg_last_xact_replay_timestamp() AS last_apply_delay;
```

### Управление слотами
```sql
-- Проверка размера удерживаемого WAL слотом
SELECT slot_name, active, restart_lsn, 
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS wal_keep_size
FROM pg_replication_slots;
```

## Дополнительная информация

### Управление отказоустойчивостью
Автоматизация переключения при сбое:
- **Patroni**: Стандарт для HA-кластеров. Подробнее: **[High Availability](./high_availability.md)**.
- **repmgr**: Инструментарий для управления репликацией и Failover.

### Смежные темы
- Теория: **[Репликация баз данных](../../Concepts/replication.md)**
- Масштабирование: **[Масштабирование PostgreSQL](./scaling.md)**
- Внутренности: **[Write Ahead Log (WAL)](../../Concepts/write_ahead_log.md)**
- Настройка HA: **[High Availability в PostgreSQL](./high_availability.md)**
