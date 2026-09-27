# Настройка репликации в PostgreSQL

Данное руководство описывает процесс настройки различных видов репликации в режиме **Primary-Standby**. Инструкции актуальны для PostgreSQL версий 13, 14, 15, 16 и 17.

Теоретические основы и сравнение типов репликации описаны в разделе **[Репликация в PostgreSQL](../Concepts/replication.md)**.

## Определения

- **Репликация** — процесс дублирования данных с основного сервера (**Primary**) на вспомогательные (**Standby**).
- **Потоковая репликация (Streaming Replication)** — физическая передача WAL-записей в реальном времени.
- **Синхронная репликация** — режим, при котором транзакция на Primary не считается завершенной, пока не получено подтверждение от реплики.
- **Каскадная репликация** — Standby-сервер выступает источником для других реплик.
- **Логическая репликация** — передача изменений на уровне строк/таблиц (Publisher-Subscriber).
- **Репликационный слот (Replication Slot)** — механизм на Primary, предотвращающий удаление WAL, не дошедших до реплики.

## Предварительные требования

*   Два и более серверов с установленным PostgreSQL одной мажорной версии (для физической репликации).
*   Сетевая связность по порту 5432.
*   **Синхронизация времени**: Настройка NTP или Chrony на всех узлах (критично для мониторинга лага).
*   Права `sudo` на всех хостах.
*   Настроенный брандмауэр (разрешить порт 5432 для IP партнеров).

## Базовый сценарий: Потоковая асинхронная репликация

Это стандартная конфигурация для обеспечения высокой доступности и масштабирования чтения.

### Шаг 1: Подготовка Primary-сервера (Master)

1.  **Создание пользователя для репликации**:
    ```sql
    CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'your_strong_password';
    ```

2.  **Настройка доступа (`pg_hba.conf`)**:
    ```conf
    # Разрешить пользователю replicator подключаться с IP реплики
    host    replication    replicator    REPLICA_IP/32    scram-sha-256
    ```

3.  **Конфигурация параметров (`postgresql.conf`)**:
    ```conf
    listen_addresses = '*'
    wal_level = replica
    max_wal_senders = 10
    wal_keep_size = 1GB             # Хранить WAL на случай кратковременного сбоя связи
    max_replication_slots = 10
    hot_standby = on                # Включить для единообразия
    ```

4.  **Создание слота репликации**:
    ```sql
    SELECT * FROM pg_create_physical_replication_slot('replica_1_slot');
    ```

5.  **Применение настроек**:
    ```bash
    sudo systemctl restart postgresql
    ```

### Шаг 2: Подготовка Standby-сервера (Replica)

1.  **Остановка и очистка данных**:
    ```bash
    sudo systemctl stop postgresql
    sudo su - postgres
    # ВНИМАНИЕ: убедитесь в правильности пути
    rm -rf /var/lib/postgresql/17/main/*
    ```

2.  **Клонирование данных (Base Backup)**:
    ```bash
    pg_basebackup -h MASTER_IP -D /var/lib/postgresql/17/main -U replicator -P -R --slot=replica_1_slot -X stream
    ```
    *   `-R`: Создает файл `standby.signal` и обновляет `postgresql.auto.conf`.
    *   `--slot`: Привязывает реплику к физическому слоту.

3.  **Запуск реплики**:
    ```bash
    exit
    sudo systemctl start postgresql
    ```

## Дополнительные сценарии

### Сценарий 3: Синхронная репликация (Zero Data Loss)

Обеспечивает гарантию сохранности данных при аварии Primary.

**На Primary (`postgresql.conf`):**
```conf
synchronous_commit = on
synchronous_standby_names = 'ANY 1 (replica_1, replica_2)'
```

**На Standby (`postgresql.auto.conf` через `primary_conninfo`):**
Добавьте `application_name` к строке подключения:
```conf
primary_conninfo = 'host=MASTER_IP ... application_name=replica_1'
```
*Требуется перезапуск сервисов.*

### Сценарий 4: Каскадная репликация

Снижает нагрузку на Primary в распределенных сетях.
1.  **Standby 1** настраивается как Master (включая `max_wal_senders`).
2.  **Standby 2** выполняет `pg_basebackup` с адреса **Standby 1**.
3.  В `primary_conninfo` на Standby 2 указывается адрес Standby 1.

### Сценарий 5: Логическая репликация (PG 17)

Для миграций или частичной синхронизации.
**Publisher (Мастер):** `wal_level = logical`.
```sql
CREATE PUBLICATION app_pub FOR ALL TABLES;
```
**Subscriber (Реплика):**
```sql
CREATE SUBSCRIPTION app_sub CONNECTION 'host=PUB_IP ...' PUBLICATION app_pub;
```

## Шаг 3: Мониторинг

### На Primary
Анализ подключенных реплик и лага:
```sql
SELECT 
    client_addr, 
    application_name,
    state, 
    sync_state, 
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS total_lag
FROM pg_stat_replication;
```

### На Standby
```sql
SELECT pg_is_in_recovery(); -- Должно быть 't'
SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;
```

## Шаг 4: Повышение реплики (Promotion)

В случае аварии на Primary:
```bash
sudo -u postgres pg_ctl promote -D /var/lib/postgresql/17/main
```
Файл `standby.signal` будет удален, сервер перейдет в режим записи. Для автоматизации используйте **[Patroni](./high_availability_patroni.md)**.

## Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `FATAL: password authentication failed` | Ошибка в `pg_hba.conf` | Проверьте метод (scram-sha-256) и пароль. |
| `is already active` | Слот занят | Проверьте `pg_replication_slots` на мастере. |
| Огромный рост `pg_wal` | Реплика не забирает данные | Удалите неактивный слот: `pg_drop_replication_slot('slot')`. |
| Репликация не стартует | Firewall или `listen_addresses` | Проверьте доступность 5432 через `nc -zv`. |
| Конфликты восстановления | Vacuum удалил нужные реплике строки | Сначала сократите длительные запросы на Standby и настройте vacuum; `hot_standby_feedback = on` может увеличить bloat и WAL на primary, поэтому включайте его осознанно. |

## Обслуживание

*   **Мониторинг слотов**: Регулярно проверяйте `pg_replication_slots`.
*   **Смена пароля**: Обновите пароль на мастере и в `primary_conninfo` на всех репликах.
*   **Безопасность**: Используйте TLS для репликации через открытые сети.

### См. также
*   [Репликация в PostgreSQL: Концепции](../Concepts/replication.md)
*   [Отказоустойчивость (Patroni)](./high_availability_patroni.md)
*   [Оптимизация производительности](./performance_tuning.md)
*   [Write Ahead Log (WAL)](../../Concepts/write_ahead_log.md)
