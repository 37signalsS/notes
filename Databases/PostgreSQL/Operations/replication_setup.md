# Настройка репликации в PostgreSQL

**Актуально для:** PostgreSQL 14–18 (PG 13 EOL 13.11.2025 — шаги применимы и к нему, но обновление рекомендуется)

Теоретические основы, сравнение типов репликации и матрица режимов синхронизации описаны в разделе **[Репликация в PostgreSQL](../Concepts/replication.md)**. Здесь — операционные процедуры: настройка, мониторинг, promotion и откат.

## Определения

- **Репликация** — процесс дублирования данных с основного сервера (**Primary**) на вспомогательные (**Standby**).
- **Потоковая репликация (Streaming Replication)** — физическая (побайтовая) передача WAL-записей в реальном времени: процесс `walsender` на Primary читает WAL и отправляет его процессу `walreceiver` на Standby.
- **Синхронная репликация** — режим, при котором транзакция на Primary не считается завершенной, пока не получено подтверждение от реплики.
- **Каскадная репликация** — Standby-сервер выступает источником для других реплик.
- **Логическая репликация** — передача изменений на уровне строк/таблиц (Publisher-Subscriber), доступна с **PG 10**.
- **Репликационный слот (Replication Slot)** — механизм на Primary, предотвращающий удаление WAL, не дошедших до реплики; при этом неактивный слот удерживает WAL бесконечно — источник риска заполнения диска.
- **standby.signal** — файл-маркер (с PG 12 вместо `recovery.conf`): наличие файла переводит сервер в режим Standby.
- **Timeline (линия времени)** — история переключений Primary; после promote реплики должны следовать за новой timeline (`recovery_target_timeline = 'latest'` — значение по умолчанию с PG 12).

## Предпосылки

- Два и более серверов с PostgreSQL **одной мажорной версии** (для физической репликации); minor-версия Standby должна быть не ниже, чем на Primary. Проверка: `SELECT version();` на обоих узлах.
- Сетевая связность по порту 5432 (или нестандартному порту кластера) между партнерами; брандмауэр разрешает порт только для IP партнеров.
- **Синхронизация времени** (NTP/chrony) на всех узлах — критично для мониторинга лага и `commit_timestamp`.
- Права `sudo` и доступ к каталогу данных (`PGDATA`) на всех хостах.
- Для логической репликации: `wal_level = logical` (требует restart).

## Практические сценарии

### Сценарий 1: Потоковая асинхронная репликация

Стандартная конфигурация для высокой доступности и масштабирования чтения.

#### Шаг 1: Подготовка Primary-сервера

1. **Создание пользователя для репликации** (пароль не попадает в историю psql):
    ```sql
    CREATE ROLE replicator WITH REPLICATION LOGIN;
    \password replicator
    ```
    *Привилегия `REPLICATION` разрешает только streaming-подключения; `LOGIN` нужен, так как подключение идёт по сети.*

2. **Настройка доступа (`pg_hba.conf`)**:
    ```conf
    # Разрешить пользователю replicator подключаться с IP реплики
    host    replication    replicator    STANDBY_IP/32    scram-sha-256
    # hostssl — то же, но только по TLS (требует настроенного ssl=on)
    ```
    *Запись `replication` в поле DATABASE ловит только физические репликационные подключения.*

3. **Конфигурация параметров (`postgresql.conf`)**:
    ```conf
    listen_addresses = 'PRIMARY_IP'   # конкретный IP вместо '*', если возможно
    wal_level = replica               # default, указывать необязательно
    max_wal_senders = 10              # default, хватает для 10 реплик/бэкапов
    max_replication_slots = 10        # default
    wal_keep_size = 1GB               # опционально: резерв WAL на кратковременный разрыв связи
    max_slot_wal_keep_size = 10GB     # PG 13+: ограничение WAL, удерживаемого слотом
    wal_sender_timeout = 60s          # default: разрыв соединения при молчании отправителя
    ```
    *При использовании репликационного слота `wal_keep_size` для этой реплики избыточен (слот сам удерживает WAL), но полезен для `pg_basebackup` без слота и других потребителей. При превышении `max_slot_wal_keep_size` слот инвалидируется (`wal_status = lost`) — реплика потребует пересборки: это осознанный tradeoff против бесконечного роста `pg_wal`.*

4. **Создание слота репликации** (до `pg_basebackup` — он не создаёт слоты самостоятельно):
    ```sql
    SELECT * FROM pg_create_physical_replication_slot('replica_1_slot');
    ```

5. **Применение настроек** (`listen_addresses` — параметр postmaster):
    ```bash
    sudo systemctl restart postgresql
    ```

#### Шаг 2: Подготовка Standby-сервера

1. **Остановка и очистка данных** (путь приведён для Debian/Ubuntu; на RHEL/CentOS — `/var/lib/pgsql/17/data`):
    ```bash
    sudo systemctl stop postgresql
    sudo -u postgres ls -A /var/lib/postgresql/17/main   # убедиться, что очищаем тот кластер
    sudo -u postgres rm -rf /var/lib/postgresql/17/main/*
    ```

2. **Клонирование данных (Base Backup)**:
    ```bash
    sudo -u postgres pg_basebackup -h PRIMARY_IP -D /var/lib/postgresql/17/main \
      -U replicator -P -R --slot=replica_1_slot -X stream
    ```
    *   `-R`: создаёт `standby.signal` и прописывает `primary_conninfo` (и `primary_slot_name` при `--slot`) в `postgresql.auto.conf`.
    *   `--slot`: привязывает реплику к физическому слоту; `-X stream` — потоковая передача WAL во время копирования.
    *   Пароль запрашивается интерактивно или берётся из `~postgres/.pgpass`.

3. **Запуск реплики**:
    ```bash
    sudo systemctl start postgresql
    ```

#### Шаг 3: Валидация

```sql
-- На Standby: сервер в режиме восстановления
SELECT pg_is_in_recovery();
-- → t

-- На Primary: реплика подключена и стримит
SELECT client_addr, application_name, state, sync_state
FROM pg_stat_replication;
-- → 10.0.0.2 |       | streaming | async
```

### Сценарий 2: Синхронная репликация (Zero Data Loss)

Обеспечивает гарантию сохранности данных при аварии Primary.

**На Primary (`postgresql.conf`):**
```conf
synchronous_commit = on                          # user-контекст: можно менять per-transaction
synchronous_standby_names = 'ANY 1 (replica_1, replica_2)'
```

**На Standby (`postgresql.auto.conf` через `primary_conninfo`):** имя реплики задаётся параметром `application_name` (имена в `synchronous_standby_names` сопоставляются с ним без учёта регистра):
```conf
primary_conninfo = 'host=PRIMARY_IP user=replicator password_file=/var/lib/postgresql/.pgpass application_name=replica_1'
```

**Применение: достаточно reload, не restart** — `synchronous_standby_names` имеет контекст `sighup`:
```bash
sudo systemctl reload postgresql    # либо SELECT pg_reload_conf();
```

**Проверка режима:** в `pg_stat_replication` поле `sync_state` принимает значение `sync` (для `FIRST`/одного) или `quorum` (для `ANY N`); остальные кандидаты — `potential`, прочие реплики — `async`.

### Сценарий 3: Каскадная репликация

Снижает нагрузку на Primary в распределенных сетях: WAL передаётся цепочкой.

1. **Standby 1** дополнительно настраивается как источник: `max_wal_senders` (default 10) и `wal_level = replica` (default) уже позволяют принимать подключения; в `pg_hba.conf` Standby 1 разрешает `replication` для Standby 2.
2. **Standby 2** выполняет `pg_basebackup` с адреса **Standby 1** (казённый порт и пользователь те же).
3. В `primary_conninfo` на Standby 2 указывается адрес Standby 1 и `application_name=replica_2`.

*В `pg_stat_replication` на Primary каскадная реплика видна как подключение к Standby 1; лаг каскадных реплик отслеживается на промежуточном узле.*

### Сценарий 4: Логическая репликация (с PG 10)

Для миграций, частичной синхронизации и selective replication. Отличия от физической: копируются только выбрананные таблицы, DDL **не** реплицируется, значения последовательностей не синхронизируются (на subscriber нужно `setval` вручную).

**Publisher (Primary):** `wal_level = logical` (параметр postmaster — требует **restart**).
```sql
CREATE PUBLICATION app_pub FOR ALL TABLES;   -- включая будущие таблицы
-- CREATE PUBLICATION app_pub FOR TABLE t1, t2;  -- выборочные таблицы
```

**Subscriber (Replica):** структура таблиц должна существовать заранее (например, `pg_dump --schema-only` с Publisher).
```sql
CREATE SUBSCRIPTION app_sub
  CONNECTION 'host=PUB_IP user=repl_user dbname=app'
  PUBLICATION app_pub;
```
*При создании подписки по умолчанию: `copy_data = true` (существующие данные копируются), `create_slot = true` (на Publisher создаётся логический слот с именем подписки), `enabled = true`. Пароль берётся из `~/.pgpass`, если не указан в conninfo.*

**Мониторинг и управление:**
```sql
SELECT * FROM pg_stat_subscription;                 -- состояние worker'ов
ALTER SUBSCRIPTION app_sub DISABLE;               -- пауза без разрыва слота
ALTER SUBSCRIPTION app_sub ENABLE;
DROP SUBSCRIPTION app_sub;                        -- удаляет и слот на Publisher (при доступности соединения)
```

## Мониторинг

**На Primary** (видимость — суперпользователь или роль `pg_monitor`):
```sql
SELECT client_addr, application_name, state, sync_state,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS total_lag
FROM pg_stat_replication;

SELECT slot_name, slot_type, active, wal_status,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;
```

**На Standby:**
```sql
SELECT pg_is_in_recovery();                              -- → t
SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;  -- NULL, если на Primary нет активности
SELECT status, sender_host, last_msg_receipt_time FROM pg_stat_wal_receiver;
```
*Лаг по времени (`now() - pg_last_xact_replay_timestamp`) показывает возраст последней replay'ed транзакции, а не реальный отставание при простой на Primary; надёжнее сравнивать LSN (см. `pg_wal_lsn_diff`).*

## Повышение реплики (Promotion)

В случае аварии на Primary:
```bash
sudo -u postgres pg_ctl promote -D /var/lib/postgresql/17/main
```
или из SQL (с PG 12):
```sql
SELECT pg_promote();
```
Файл `standby.signal` удаляется, сервер переходит в режим записи на новой timeline. **Бывший Primary (если восстановлен) требует пересборки через `pg_basebackup` с нового Primary**, как и остальные реплики, не переключённые автоматически. Для автоматизации failover используйте **[Patroni](./high_availability_patroni.md)**.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `FATAL: password authentication failed` | Неверный пароль или `LOGIN` у роли | Сбросить пароль (`\password replicator`), проверить `rolcanlogin` в `pg_authid`; метод в `pg_hba.conf` должен быть `scram-sha-256` |
| `FATAL: no pg_hba.conf entry for host ...` | Нет подходящей записи `pg_hba.conf` | Добавить строку `host [ssl] replication replicator IP/32 scram-sha-256`; reload |
| `ERROR: replication slot "..." is already active` | Слот уже стримит другой `walsender` (две реплики с одним слотом или stale-подключение) | Проверить `pg_stat_replication` и `pg_stat_activity`; каждой реплике — свой слот |
| Рост `pg_wal` на Primary | Неактивный слот удерживает WAL | Проверить `pg_replication_slots` (`active = f`); удалять слот только если реплика, его использовавшая, более не нужна или будет пересобрана: `SELECT pg_drop_replication_slot('slot');` |
| `pg_wal` заполнен, слот `wal_status = lost` | Превышен `max_slot_wal_keep_size` | Реплика отстала необратимо — пересобрать её через `pg_basebackup` |
| Репликация не стартует | Firewall или `listen_addresses` | Проверить доступность порта: `nc -zv PRIMARY_IP 5432` |
| Конфликты восстановления на Standby | Vacuum удалил строки, нужные длинному запросу | Сократить длительные запросы; `hot_standby_feedback = on` отключает vacuum-cleanup, но увеличивает bloat и WAL на Primary — включать осознанно |

## Лучшие практики

*   **Версии:** одинаковая мажорная версия на всех узлах; minor-версия Standby не ниже Primary; регулярно обновляйтесь до текущего minor-релиза мажорной версии.
*   **Идентификация:** каждой реплике — уникальный `application_name` (обязателен для синхронной репликации) и собственный слот.
*   **Секреты:** пароль через `\password` и `password_file`/`.pgpass`, не в открытом SQL; `hostssl` + `sslmode=verify-ca` в `primary_conninfo` для репликации через открытые сети.
*   **Слоты:** регулярно проверяйте `pg_replication_slots`; `max_slot_wal_keep_size` как предохранитель от заполнения диска.
*   **Тестирование:** периодически отрабатывайте promote в staging — непроверенный failover не является failover.
*   **Не путайте репликацию с бэкапом:** реплика защищает от отказа сервера, но не от `DROP TABLE` — бэкапы по-прежнему обязательны (**[Автоматизация бэкапов](./backup_automation.md)**).

## Очистка и откат

**Разорвать репликацию (сделать Standby standalone):**
```bash
sudo systemctl stop postgresql
sudo -u postgres rm -f /var/lib/postgresql/17/main/standby.signal
sudo -u postgres sed -i '/primary_conninfo/d;/primary_slot_name/d' /var/lib/postgresql/17/main/postgresql.auto.conf
sudo systemctl start postgresql
# На Primary, после остановки реплики:
SELECT pg_drop_replication_slot('replica_1_slot');
```

**Откат к исходному состоянию:** реплику, отставшую или повреждённую, не «чинят» — её пересобирают: остановить, очистить `PGDATA`, выполнить `pg_basebackup` с Primary (см. сценарий 1).

## Дополнительная информация

### См. также
*   [Репликация в PostgreSQL: Концепции](../Concepts/replication.md) — теория и сравнение типов репликации
*   [Отказоустойчивость (Patroni)](./high_availability_patroni.md) — автоматический failover
*   [Миграция без простоя](./zero_downtime_migration.md) — логическая репликация как инструмент миграции
*   [Write Ahead Log (WAL)](../../Concepts/write_ahead_log.md)
*   [Оптимизация производительности](./performance_tuning.md)
