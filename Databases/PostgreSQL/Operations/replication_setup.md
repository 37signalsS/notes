# Настройка потоковой репликации в PostgreSQL

Данное руководство описывает процесс настройки базовой потоковой асинхронной репликации в режиме **Master-Replica** (основной сервер для записи, реплика только для чтения).

## Предварительные требования
*   Два сервера с установленным PostgreSQL (одинаковой мажорной версии).
*   Сетевая связность между серверами.
*   Права `sudo` на обоих хостах.

## Шаг 1: Подготовка Master-сервера

1.  **Настройка доступа**: Отредактируйте файл `pg_hba.conf` (путь зависит от версии, например `/etc/postgresql/14/main/pg_hba.conf`), чтобы разрешить реплике подключаться.
    ```conf
    # Разрешить пользователю postgres подключаться для репликации с IP реплики
    host    replication    postgres    REPLICA_IP/32    scram-sha-256
    ```

2.  **Конфигурация параметров**: Внесите изменения в `postgresql.conf`:
    ```conf
    listen_addresses = 'localhost, MASTER_IP'
    wal_level = replica         # Минимальный уровень для репликации
    archive_mode = on           # Включение архивации WAL
    archive_command = 'cd .'    # Заглушка (в production заменить на реальную команду)
    max_wal_senders = 10        # Максимальное число процессов передачи WAL
    hot_standby = on            # Разрешить подключения на реплике
    ```

3.  **Применение настроек**:
    ```bash
    sudo service postgresql restart
    ```

## Шаг 2: Подготовка Replica-сервера

1.  **Остановка сервиса**:
    ```bash
    sudo service postgresql stop
    ```

2.  **Настройка доступа и параметров**: Отредактируйте `pg_hba.conf` и `postgresql.conf` аналогично мастеру, указав локальный IP реплики в `listen_addresses`. Это позволит реплике в будущем стать мастером.

3.  **Клонирование данных (Base Backup)**:
    Удалите текущие данные (сделайте бэкап, если нужно) и скачайте актуальное состояние с мастера.
    ```bash
    sudo su - postgres
    cd /var/lib/postgresql/14/
    rm -rf main
    
    # Создание копии с мастера
    pg_basebackup -h MASTER_IP -D ./main -U postgres -P -R -X stream
    ```
    *   `-R`: Автоматически создает файл `standby.signal` (для PG 12+) или `recovery.conf` (для старых версий). Наличие этого файла переводит сервер в режим реплики.

4.  **Запуск реплики**:
    ```bash
    exit
    sudo service postgresql start
    ```

## Шаг 3: Проверка репликации

1.  **На мастере**: Создайте тестовую таблицу и вставьте данные.
    ```sql
    CREATE TABLE replication_test (id INT, data TEXT);
    INSERT INTO replication_test VALUES (1, 'Hello from Master');
    ```

2.  **На реплике**: Проверьте наличие данных.
    ```sql
    SELECT * FROM replication_test;
    ```

3.  **Проверка Read-Only**: Попытка записи на реплике должна вернуть ошибку:
    `ERROR: cannot execute INSERT in a read-only transaction`

## Шаг 4: Повышение реплики до мастера (Promotion)

Если основной сервер вышел из строя, реплику можно перевести в режим записи.

1.  **Команда повышения**:
    ```bash
    sudo -u postgres pg_ctl promote -D /var/lib/postgresql/14/main
    ```
    После выполнения команды файл `standby.signal` удалится, и сервер начнет принимать запросы на запись.

**Примечание:** Повышение реплики до мастера не перенаправляет трафик приложений автоматически. Для автоматизации этого процесса рекомендуется использовать **[Patroni](../high_availability.md)** или балансировщик нагрузки.

### См. также
*   [Теория репликации](../Concepts/replication.md)
*   [Отказоустойчивость (High Availability)](../high_availability.md)
*   [Утилита pg_basebackup](./crud_operations.md)
