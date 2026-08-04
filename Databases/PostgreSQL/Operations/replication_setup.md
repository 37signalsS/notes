# Настройка потоковой репликации в PostgreSQL

Данное руководство описывает процесс настройки физической потоковой асинхронной репликации в режиме **Primary-Standby** (основной сервер для записи, реплика только для чтения). Инструкции актуальны для PostgreSQL версий 13, 14, 15, 16 и 17.

Теоретические основы и сравнение типов репликации описаны в разделе **[Репликация в PostgreSQL](../Concepts/replication.md)**.

## Предварительные требования

*   Два сервера с установленным PostgreSQL одной мажорной версии.
*   Сетевая связность по порту 5432.
*   **Синхронизация времени**: Настройте NTP или Chrony на обоих серверах (критично для мониторинга лага).
*   Права `sudo` на обоих хостах.
*   Настроенный брандмауэр (разрешить входящие соединения на порт 5432 с IP-адресов партнеров).

## Шаг 1: Подготовка Primary-сервера (Master)

1.  **Создание пользователя для репликации**:
    Подключитесь к PostgreSQL и создайте роль с правами репликации.
    ```sql
    CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'your_strong_password';
    ```

2.  **Настройка доступа**: Отредактируйте файл `pg_hba.conf` (путь обычно `/etc/postgresql/XX/main/pg_hba.conf`).
    ```conf
    # Разрешить пользователю replicator подключаться для репликации с IP реплики
    host    replication    replicator    REPLICA_IP/32    scram-sha-256
    ```

3.  **Конфигурация параметров**: Внесите изменения в `postgresql.conf`:
    ```conf
    listen_addresses = '*'          # Или список конкретных IP
    wal_level = replica             # Минимальный уровень для репликации
    max_wal_senders = 10            # Максимальное число процессов передачи WAL
    wal_keep_size = 1GB             # Объем WAL, который мастер хранит для реплик (с PG 13)
    max_replication_slots = 10      # Максимальное количество слотов репликации
    hot_standby = on                # Рекомендуется включать и на мастере для единообразия
    ```

4.  **Создание слота репликации (рекомендуется)**:
    Использование слотов гарантирует, что мастер не удалит WAL-файлы, пока они не будут получены репликой.
    ```sql
    SELECT * FROM pg_create_physical_replication_slot('replica_1_slot');
    ```

5.  **Применение настроек**:
    ```bash
    sudo systemctl restart postgresql
    ```

## Шаг 2: Подготовка Standby-сервера (Replica)

1.  **Остановка и очистка данных**:
    Перед клонированием данных сервис должен быть остановлен, а текущая директория данных очищена.
    ```bash
    sudo systemctl stop postgresql
    sudo su - postgres
    # ВНИМАНИЕ: убедитесь, что путь верный перед выполнением rm
    rm -rf /var/lib/postgresql/XX/main/*
    ```

2.  **Клонирование данных (Base Backup)**:
    Выполните `pg_basebackup` с использованием созданного ранее слота.
    ```bash
    pg_basebackup -h MASTER_IP -D /var/lib/postgresql/XX/main -U replicator -P -R --slot=replica_1_slot -X stream
    ```
    *   `-R`: Создает файл `standby.signal` и добавляет настройки подключения в `postgresql.auto.conf`.
    *   `--slot`: Привязывает реплику к конкретному слоту на мастере.

3.  **Запуск реплики**:
    ```bash
    exit
    sudo systemctl start postgresql
    ```

## Шаг 3: Проверка и мониторинг

### Проверка статуса на Primary
Выполните запрос для анализа подключенных реплик и их отставания:
```sql
SELECT 
    client_addr, 
    state, 
    sync_state, 
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)) AS send_lag,
    pg_size_pretty(pg_wal_lsn_diff(sent_lsn, write_lsn)) AS write_lag,
    pg_size_pretty(pg_wal_lsn_diff(write_lsn, flush_lsn)) AS flush_lag,
    pg_size_pretty(pg_wal_lsn_diff(flush_lsn, replay_lsn)) AS replay_lag
FROM pg_stat_replication;
```

### Проверка статуса на Standby
Убедитесь, что сервер находится в режиме восстановления (чтения):
```sql
SELECT pg_is_in_recovery(); -- Должно вернуть 't' (true)

-- Просмотр времени последней примененной транзакции
SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;
```

## Шаг 4: Повышение реплики до мастера (Promotion)

В случае аварии на основном сервере реплику можно перевести в режим записи.

1.  **Команда повышения**:
    ```bash
    sudo -u postgres pg_ctl promote -D /var/lib/postgresql/XX/main
    ```
    После этого файл `standby.signal` будет удален автоматически.

**Примечание:** Повышение реплики вручную не перенаправляет трафик приложений автоматически. Для построения отказоустойчивых кластеров с автоматическим переключением рекомендуется использовать **[Patroni](./high_availability_patroni.md)**.

## Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `FATAL: password authentication failed` | Ошибка в `pg_hba.conf` или пароле | Проверьте метод аутентификации и пароль пользователя `replicator`. |
| `is already active` (при запуске реплики) | Слот занят другим процессом | Проверьте `pg_replication_slots` на мастере, удалите и пересоздайте слот при необходимости. |
| Репликация не стартует | Firewall блокирует порт 5432 | Проверьте доступность порта: `telnet MASTER_IP 5432`. |
| Огромный рост папки `pg_wal` на мастере | Реплика не забирает данные, слот держит WAL | Проверьте статус реплики. Если она выключена надолго, удалите слот: `pg_drop_replication_slot('slot_name')`. |

## Обслуживание

*   **Мониторинг слотов**: Регулярно проверяйте `pg_replication_slots`, чтобы неактивные слоты не переполнили диск на мастере.
*   **Смена пароля**: При изменении пароля пользователя `replicator` на мастере, необходимо обновить его в `postgresql.auto.conf` на реплике (параметр `primary_conninfo`) и перезапустить сервис.

### См. также
*   [Репликация в PostgreSQL: Концепции](../Concepts/replication.md)
*   [Отказоустойчивость (High Availability)](../Concepts/high_availability.md)
*   [Оптимизация PostgreSQL](./performance_tuning.md)
*   [Управление ролями и БД](./role_management.md)
