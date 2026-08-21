# Настройка репликации MariaDB: Пошаговое руководство

## Определения

*   **Инициализация (Seeding)** — процесс создания начальной копии данных источника на реплике.
*   **CHANGE MASTER TO** — основная SQL-команда для настройки параметров соединения реплики с источником. В MariaDB 10.5+ также поддерживается синтаксис `CHANGE REPLICATION SOURCE TO`.
*   **Relay Log** — локальный журнал реплики, куда сохраняются события, полученные от источника перед их применением.
*   **GTID (Global Transaction ID)** — уникальный идентификатор транзакции, позволяющий автоматически определять позицию репликации без привязки к файлам и позициям.
*   **gtid_strict_mode** — режим, при котором MariaDB не позволит реплике выполнять транзакции, которые уже были выполнены (защита от дублирования).
*   **mariadb-backup** — инструмент для создания физических бэкапов без блокировки данных (ранее назывался mariabackup).
*   **Crash-safe Replication** — механизм восстановления реплики после аварийного завершения благодаря хранению позиции репликации в таблице.

## Базовые концепции

### Предварительные требования

Перед настройкой репликации убедитесь:

1.  **Версии MariaDB:** Рекомендуется использовать одинаковые версии на источнике и реплике. Минимальная версия для GTID: MariaDB 10.0+; для параллельной репликации: MariaDB 10.5+.
2.  **Сетевая связность:** Источник и реплика должны иметь стабильное сетевое соединение. Проверьте доступность порта 3306:
    ```bash
    # С реплики
    telnet source_ip 3306
    # или
    mysql -h source_ip -u root -p -e "SELECT 1"
    ```
3.  **Уникальные server_id:** Каждый узел в репликации должен иметь уникальный `server_id` (целое число от 1 до 2^32-1).
4.  **Достаточный диск:** На источнике должно быть достаточно места для хранения бинарных логов; на реплике — для relay log и данных.
5.  **Безопасность:** Создайте отдельного пользователя для репликации с минимально необходимыми привилегиями.

### Этапы настройки

Процесс настройки состоит из пяти этапов:
1.  Подготовка конфигурации на обоих узлах.
2.  Настройка безопасности (SSL/TLS, пользователи).
3.  Создание пользователя для репликации на источнике.
4.  Перенос снимка данных (snapshot) с источника на реплику.
5.  Запуск потоков репликации и валидация.

### Crash-safe Replication

Для обеспечения восстановления после сбоев добавьте в конфигурацию **реплики**:

```ini
[mariadb]
# Восстановление relay log после сбоя
relay_log_recovery = ON

# Хранение позиции репликации в таблице (надежнее файла)
relay_log_info_repository = TABLE

# Синхронизация relay log на диск (повышает надежность, снижает производительность)
sync_relay_log = 1
```

---

## Практические сценарии

### Сценарий 1: Базовая Source-Replica (GTID-based)

Использование GTID является стандартом для MariaDB 10.x+.

#### 1. Настройка Источника (Source)

В файле `/etc/mysql/mariadb.conf.d/50-server.cnf`:

```ini
[mariadb]
server_id               = 1
log_bin                 = /var/log/mysql/mariadb-bin
binlog_format           = ROW
gtid_domain_id          = 0
gtid_strict_mode        = ON

# Crash-safe settings
sync_binlog             = 1
innodb_flush_log_at_trx_commit = 1
```

После изменения перезапустите MariaDB:

```bash
sudo systemctl restart mariadb
```

Создайте пользователя для репликации:

```sql
CREATE USER 'repl_user'@'192.168.1.%' IDENTIFIED BY 'StrongPassword123';
GRANT REPLICATION SLAVE ON *.* TO 'repl_user'@'192.168.1.%';
FLUSH PRIVILEGES;
```

**Важно:** Используйте конкретную подсеть или IP вместо `%` для повышения безопасности.

#### 2. Настройка Реплики (Replica)

В конфигурации `/etc/mysql/mariadb.conf.d/50-server.cnf`:

```ini
[mariadb]
server_id               = 2
log_bin                 = /var/log/mysql/mariadb-bin
relay_log               = /var/log/mysql/relay-bin
read_only               = 1
gtid_domain_id          = 0
gtid_strict_mode        = ON

# Crash-safe settings
relay_log_recovery      = ON
relay_log_info_repository = TABLE
sync_relay_log          = 1

# Parallel replication (опционально)
slave_parallel_threads  = 4
slave_parallel_mode     = 'optimistic'
```

#### 3. Перенос данных

**Метод A: mariadb-dump (для небольших БД, < 10GB)**

```bash
# На источнике
mariadb-dump --all-databases \
    --user=root \
    --password \
    --single-transaction \
    --routines \
    --events \
    --triggers \
    --master-data=2 > full_dump.sql

# Перенесите файл на реплику
scp full_dump.sql user@replica_ip:/tmp/

# На реплике
mariadb -u root -p < /tmp/full_dump.sql
```

**Метод B: mariadb-backup (для больших БД, > 10GB)**

```bash
# На источнике: создание бэкапа
mariadb-backup --backup \
    --target-dir=/backup/full \
    --user=root \
    --password \
    --parallel=4

# Подготовка бэкапа
mariadb-backup --prepare --target-dir=/backup/full

# Перенесите бэкап на реплику
rsync -avz /backup/full/ user@replica_ip:/backup/full/

# На реплике: остановите MariaDB
sudo systemctl stop mariadb

# Очистите директорию данных
sudo rm -rf /var/lib/mysql/*

# Восстановите из бэкапа
mariadb-backup --copy-back --target-dir=/backup/full --user=mysql

# Исправьте права доступа
sudo chown -R mysql:mysql /var/lib/mysql

# Запустите MariaDB
sudo systemctl start mariadb
```

#### 4. Запуск репликации

```sql
-- На реплике
CHANGE MASTER TO
    MASTER_HOST='192.168.1.10',
    MASTER_USER='repl_user',
    MASTER_PASSWORD='StrongPassword123',
    MASTER_USE_GTID=slave_pos;

START SLAVE;
```

### Сценарий 2: Полусинхронная репликация (rpl_semi_sync)

#### 1. Установка плагинов (на обоих узлах)

```sql
-- На источнике
INSTALL SONAME 'semisync_master';

-- На реплике
INSTALL SONAME 'semisync_slave';
```

#### 2. Активация

**На Источнике:**

```sql
SET GLOBAL rpl_semi_sync_master_enabled = ON;
SET GLOBAL rpl_semi_sync_master_timeout = 10000; -- 10 секунд (по умолчанию)
SET GLOBAL rpl_semi_sync_master_wait_point = 'AFTER_SYNC'; -- Рекомендуется
```

**На Реплике:**

```sql
SET GLOBAL rpl_semi_sync_slave_enabled = ON;
STOP SLAVE IO_THREAD;
START SLAVE IO_THREAD;
```

#### 3. Проверка работы

```sql
-- На источнике
SHOW STATUS LIKE 'Rpl_semi_sync_master_clients';
-- Должно быть >= 1

SHOW STATUS LIKE 'Rpl_semi_sync_master_status';
-- Active: ON
```

### Сценарий 3: Мульти-сорс репликация (Multi-source)

В MariaDB для каждого источника создается отдельный именной канал.

```sql
-- Настройка соединения с первым источником
CHANGE MASTER 'marketing_db' TO
    MASTER_HOST='10.0.0.1',
    MASTER_USER='repl_user',
    MASTER_PASSWORD='Password1',
    MASTER_USE_GTID=slave_pos;

-- Настройка соединения со вторым источником
CHANGE MASTER 'sales_db' TO
    MASTER_HOST='10.0.0.2',
    MASTER_USER='repl_user',
    MASTER_PASSWORD='Password2',
    MASTER_USE_GTID=slave_pos;

-- Запуск всех каналов
START ALL SLAVES;

-- Проверка статуса конкретного канала
SHOW SLAVE 'marketing_db' STATUS\G
```

### Сценарий 4: Настройка параллельной репликации

Для уменьшения лага репликации:

```sql
-- На реплике
STOP SLAVE;

-- Установка количества параллельных потоков
SET GLOBAL slave_parallel_threads = 8;

-- Режим параллелизма (optimistic рекомендуется для MariaDB 10.5+)
SET GLOBAL slave_parallel_mode = 'optimistic';

START SLAVE;
```

**Для сохранения настроек** добавьте в `my.cnf`:

```ini
[mariadb]
slave_parallel_threads = 8
slave_parallel_mode = 'optimistic'
```

### Сценарий 5: Настройка с SSL/TLS

Для зашифрованного соединения между источником и репликой:

**На источнике:**

```sql
-- Создайте пользователя с требованием SSL
CREATE USER 'repl_ssl'@'192.168.1.%' IDENTIFIED BY 'StrongPassword123'
    REQUIRE SSL;
GRANT REPLICATION SLAVE ON *.* TO 'repl_ssl'@'192.168.1.%';
```

**На реплике:**

```sql
CHANGE MASTER TO
    MASTER_HOST='192.168.1.10',
    MASTER_USER='repl_ssl',
    MASTER_PASSWORD='StrongPassword123',
    MASTER_USE_GTID=slave_pos,
    MASTER_SSL=1,
    MASTER_SSL_CA='/etc/mysql/ssl/ca-cert.pem',
    MASTER_SSL_CERT='/etc/mysql/ssl/client-cert.pem',
    MASTER_SSL_KEY='/etc/mysql/ssl/client-key.pem';
```

---

## Валидация и проверка

### Базовая проверка

1.  **Проверка статуса репликации:**
    ```sql
    SHOW SLAVE STATUS\G
    ```

    Ключевые поля для проверки:
    - `Slave_IO_Running: Yes`
    - `Slave_SQL_Running: Yes`
    - `Seconds_Behind_Master: 0` (или близко к 0)
    - `Last_IO_Error: (пусто)`
    - `Last_SQL_Error: (пусто)`

2.  **Проверка GTID:**
    ```sql
    -- На источнике
    SELECT @@GLOBAL.gtid_binlog_pos;

    -- На реплике
    SELECT @@GLOBAL.gtid_slave_pos;

    -- Позиции должны совпадать (или быть очень близки)
    ```

3.  **Проверка полусинхронности (на источнике):**
    ```sql
    SHOW STATUS LIKE 'Rpl_semi_sync_master_clients';
    -- Должно быть > 0
    ```

### Тестирование репликации

1.  **Создайте тестовую таблицу на источнике:**
    ```sql
    USE test_db;
    CREATE TABLE repl_test (
        id INT AUTO_INCREMENT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        message VARCHAR(100)
    );

    INSERT INTO repl_test (message) VALUES ('Test replication');
    ```

2.  **Проверьте на реплике:**
    ```sql
    SELECT * FROM test_db.repl_test;
    -- Должна быть строка с message = 'Test replication'
    ```

3.  **Удалите тестовую таблицу:**
    ```sql
    DROP TABLE test_db.repl_test;
    ```

### Проверка консистентности данных

Для полноценной проверки используйте `pt-table-checksum` из Percona Toolkit:

```bash
# На реплике (безопасная проверка)
pt-table-checksum --replicate=percona.checksums \
    --host=source_ip \
    --user=monitor_user \
    --password=monitor_password
```

---

## Типовые ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Error 1236: ... master has purged binary logs` | Реплика слишком долго была отключена. | Требуется пересоздание снимка данных (re-seeding). |
| `Duplicate entry ... for key 'PRIMARY'` | Попытка записать данные, которые уже есть. | Проверьте, нет ли записи на реплику напрямую. Используйте `read_only = 1`. |
| `Seconds_Behind_Master` растет | SQL Thread не успевает применять данные. | Включите параллельную репликацию (`slave_parallel_threads > 1`). |
| `Error 2003: Can't connect to MySQL server` | Сетевая проблема или неправильный хост. | Проверьте firewall, порт 3306, bind-address на источнике. |
| `Error 1045: Access denied for user` | Неправильный логин/пароль или хост. | Проверьте учетные данные и IP в `GRANT`. |
| `Slave_SQL_Running: No` | Ошибка при применении транзакции. | Проверьте `Last_SQL_Error`; возможно, потребуется пропуск или исправление. |

---

## Дополнительная информация

### Версии MariaDB и особенности

| Версия | Ключевые особенности |
| :--- | :--- |
| **MariaDB 10.0** | Первая поддержка GTID |
| **MariaDB 10.5** | Параллельная репликация (optimistic mode), улучшенная безопасность |
| **MariaDB 10.6** | Долгосрочная поддержка (LTS), улучшенная производительность |
| **MariaDB 11.x** | Новые функции, экспериментальные возможности |
| **MariaDB 12.3** | Текущий LTS (2026), максимальная производительность и безопасность |

### Best Practices

1.  **Всегда используйте GTID** для упрощения failover и восстановления.
2.  **Включайте `gtid_strict_mode = ON`** для защиты от дублирования транзакций.
3.  **Используйте `read_only = 1`** на репликах для предотвращения случайной записи.
4.  **Настройте crash-safe replication** для восстановления после сбоев.
5.  **Регулярно проверяйте консистентность данных** с помощью `pt-table-checksum`.
6.  **Мониторьте лаг репликации** и настраивайте алерты.

### См. также
- **[Обзор репликации](./overview.md)** — архитектура потоков и журналов.
- **[Фильтрация в репликации](./filtering.md)** — как исключить ненужные базы.
- **[Диагностика и Troubleshooting](./troubleshooting.md)** — глубокий анализ производительности.
- **[Резервное копирование](../backup_and_recovery.md)** — методы создания снимков данных.