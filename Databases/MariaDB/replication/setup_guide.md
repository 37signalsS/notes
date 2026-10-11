# Настройка репликации MariaDB: Пошаговое руководство

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Инициализация (Seeding)** — процесс создания начальной копии данных источника на реплике.
*   **CHANGE REPLICATION SOURCE TO** — основная SQL-команда для настройки параметров соединения реплики с источником (современный синтаксис, MariaDB 10.5+). Устаревший синтаксис: `CHANGE MASTER TO`.
*   **Relay Log** — локальный журнал реплики, куда сохраняются события, полученные от источника перед их применением.
*   **GTID (Global Transaction ID)** — уникальный идентификатор транзакции, позволяющий автоматически определять позицию репликации без привязки к файлам и позициям. Формат MariaDB: `domain-id-server-id:sequence`.
*   **gtid_strict_mode** — режим, при котором MariaDB не позволит реплике выполнять транзакции, которые уже были выполнены (защита от дублирования).
*   **mariadb-backup** — инструмент для создания физических бэкапов без блокировки данных (форк Percona XtraBackup, оптимизированный под MariaDB).
*   **Crash-safe Replication** — механизм восстановления реплики после аварийного завершения благодаря хранению позиции репликации в таблице.
*   **`binlog_gtid_index`** — системная переменная (MariaDB 11.4+, default ON), создающая индекс GTID в каждом файле бинарного лога. Ускоряет поиск стартовой позиции для новой реплики при переподключении.
*   **`slave_domain_parallel_threads`** — количество рабочих потоков на домен GTID при out-of-order параллельной репликации (MariaDB 11.7+).

## Базовые концепции

### Предварительные требования

### Программное обеспечение и версии

*   **MariaDB Server** — версия 11.4 LTS или 12.3 LTS (рекомендуется) на источнике и реплике. Источник должен быть такой же или более новой версии, чем реплика.
*   **Операционная система** — Linux (RHEL/CentOS, Ubuntu/Debian, SUSE). Требования к ресурсам зависят от объема данных и нагрузки.
*   **Сеть** — стабильное соединение между источником и репликой. Рекомендуется выделенный канал или VLAN для репликационного трафика.
*   **Достаточное дисковое пространство** — на источнике для бинарных логов, на реплике для relay log и полной копии данных.

### Безопасность и доступ

*   Создайте отдельного пользователя для репликации с минимально необходимыми привилегиями (`REPLICATION SLAVE`).
*   Ограничьте доступ по подсети или IP (`repl_user@192.168.1.%`).
*   Настройте SSL/TLS для шифрования репликационного трафика (`require_secure_transport = ON`).
*   На реплике включите `read_only = 1` для предотвращения случайной записи.

### Проверка совместимости

*   Убедитесь, что на источнике включен бинарный лог (`log_bin = ON`).
*   Проверьте, что `server_id` уникален на всех узлах репликации.
*   При использовании GTID убедитесь, что `gtid_domain_id` уникален в топологии.
*   При репликации с MySQL на MariaDB убедитесь в совместимости формата binlog и GTID (прямая репликация невозможна; требуется логическая миграция через `mariadb-dump`).

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

### Рекомендуемые параметры конфигурации

**На источнике:**
```ini
[mariadb]
server_id               = 1
log_bin                 = /var/log/mysql/mariadb-bin
binlog_format           = ROW
gtid_domain_id          = 0
gtid_strict_mode        = ON

# Надежность
sync_binlog             = 1
innodb_flush_log_at_trx_commit = 1

# Ротация бинарных логов (автоматически в MariaDB 11.4+, но рекомендуется настроить)
expire_logs_days        = 7
binlog_expire_logs_seconds = 604800
```

**На реплике:**
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

# Ротация логов
expire_logs_days        = 7
binlog_expire_logs_seconds = 604800
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
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='192.168.1.10',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='StrongPassword123',
    SOURCE_USE_GTID=slave_pos;

START REPLICA;
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
STOP REPLICA IO_THREAD;
START REPLICA IO_THREAD;
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
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='10.0.0.1',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='Password1',
    SOURCE_USE_GTID=slave_pos
    FOR CHANNEL 'marketing_db';

-- Настройка соединения со вторым источником
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='10.0.0.2',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='Password2',
    SOURCE_USE_GTID=slave_pos
    FOR CHANNEL 'sales_db';

-- Запуск всех каналов
START ALL REPLICAS;

-- Проверка статуса конкретного канала
SHOW REPLICA STATUS FOR CHANNEL 'marketing_db'\G
```

### Сценарий 4: Настройка параллельной репликации

Для уменьшения лага репликации:

```sql
-- На реплике
STOP REPLICA;

-- Установка количества параллельных потоков
SET GLOBAL slave_parallel_threads = 8;

-- Режим параллелизма (optimistic рекомендуется для MariaDB 10.5+)
SET GLOBAL slave_parallel_mode = 'optimistic';

START REPLICA;
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
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='192.168.1.10',
    SOURCE_USER='repl_ssl',
    SOURCE_PASSWORD='StrongPassword123',
    SOURCE_USE_GTID=slave_pos,
    SOURCE_SSL=1,
    SOURCE_SSL_CA='/etc/mysql/ssl/ca-cert.pem',
    SOURCE_SSL_CERT='/etc/mysql/ssl/client-cert.pem',
    SOURCE_SSL_KEY='/etc/mysql/ssl/client-key.pem';
```

---

## Валидация и проверка

### Базовая проверка

1.  **Проверка статуса репликации:**
    ```sql
    SHOW REPLICA STATUS\G
    ```

    Ключевые поля для проверки:
    - `Replica_IO_Running: Yes`
    - `Replica_SQL_Running: Yes`
    - `Seconds_Behind_Source: 0` (или близко к 0)
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
| `Seconds_Behind_Source` растет | SQL Thread не успевает применять данные. | Включите параллельную репликацию (`slave_parallel_threads > 1`). |
| `Error 2003: Can't connect to MySQL server` | Сетевая проблема или неправильный хост. | Проверьте firewall, порт 3306, bind-address на источнике. |
| `Error 1045: Access denied for user` | Неправильный логин/пароль или хост. | Проверьте учетные данные и IP в `GRANT`. |
| `Replica_SQL_Running: No` | Ошибка при применении транзакции. | Проверьте `Last_SQL_Error`; возможно, потребуется пропуск или исправление. |

### Типовые ограничения и Edge Cases

1.  **Несоответствие версий:** Источник должен быть такой же или более новой версии, чем реплика. При репликации с MySQL на MariaDB убедитесь в совместимости формата binlog и GTID (прямая репликация невозможна; требуется логическая миграция через `mariadb-dump`).
2.  **Смена `binlog_format`:** Переключение с SBR на RBR требует перезапуска репликации или сброса позиции. GTID-репликация чувствительна к формату binlog на источнике.
3.  **Параллельная репликация и триггеры:** Режим `aggressive` несовместим с триггерами Conflict Detection and Resolution в MariaDB Enterprise Server 12.3+.
4.  **Полусинхронная репликация:** При недоступности реплик источник через таймаут переходит в асинхронный режим. Убедитесь, что `rpl_semi_sync_master_timeout` настроен адекватно вашим SLA.
5.  **Multi-source и уникальные `server_id`:** Все источники в топологии multi-source должны иметь уникальные `server_id`. Дублирование приведет к непредсказуемому поведению GTID.

---

## Дополнительная информация

### Версии MariaDB и особенности

| Версия | Ключевые особенности |
| :--- | :--- |
| **MariaDB 10.0** | Первая поддержка GTID |
| **MariaDB 10.5** | Параллельная репликация (`optimistic` mode), `CHANGE REPLICATION SOURCE TO`, улучшенная безопасность |
| **MariaDB 10.6** | Долгосрочная поддержка (LTS), улучшенная производительность |
| **MariaDB 10.10** | GTID включен по умолчанию для новых инсталляций |
| **MariaDB 11.4 LTS** | Текущий LTS, `binlog_gtid_index` (default ON), улучшенная стабильность |
| **MariaDB 11.7** | `slave_domain_parallel_threads` для out-of-order параллельной репликации, `binlog-do-db`/`binlog-ignore-db` deprecated |
| **MariaDB 12.3** | Текущий LTS (2026), новый InnoDB-based binlog, максимальная производительность и безопасность |

### Best Practices

1.  **Всегда используйте GTID** для упрощения failover и восстановления. С MariaDB 10.10 GTID включен по умолчанию для новых инсталляций.
2.  **Включайте `gtid_strict_mode = ON`** для защиты от дублирования транзакций.
3.  **Используйте `read_only = 1`** на репликах для предотвращения случайной записи.
4.  **Настройте crash-safe replication** для восстановления после сбоев (`relay_log_recovery = ON`, `relay_log_info_repository = TABLE`).
5.  **Используйте `binlog_format = ROW`** для максимальной надежности и совместимости с фильтрацией репликации.
6.  **Регулярно проверяйте консистентность данных** с помощью `pt-table-checksum` из Percona Toolkit.
7.  **Мониторьте лаг репликации** и настраивайте алерты. Не полагайтесь только на `Seconds_Behind_Source` — используйте GTID-позиции для точного измерения.
8.  **Используйте современный синтаксис:** `CHANGE REPLICATION SOURCE TO`, `START REPLICA`, `STOP REPLICA`, `SHOW REPLICA STATUS`.
9.  **При использовании SSL/TLS** убедитесь, что сертификаты действительны и не истекли. Настройте автоматическое обновление.
10. **Для полусинхронной репликации** используйте `rpl_semi_sync_master_wait_point = 'AFTER_SYNC'` для гарантии отсутствия "phantom reads".

### См. также
- **[Обзор репликации](./overview.md)** — архитектура потоков и журналов.
- **[Фильтрация в репликации](./filtering.md)** — как исключить ненужные базы.
- **[Диагностика и Troubleshooting](./troubleshooting.md)** — глубокий анализ производительности.
- **[Отложенная репликация](./delayed_replication.md)** — `SOURCE_DELAY`.
- **[Топологии](./topologies.md)** — каскадная, кольцевая, multi-master.
- **[Split-brain и fencing](./split_brain_fencing.md)** — `super_read_only`, защита от двойной записи.
- **[Управление Relay Log](./relay_log_management.md)** — `relay_log_space_limit`, purge.
- **[Проверка консистентности](./data_consistency.md)** — `pt-table-checksum` / `pt-table-sync`.
- **[Ручной Switchover](./switchover.md)** — плановое переключение.
- **[Мониторинг репликации](./monitoring.md)** — Prometheus, алерты.
- **[Привилегии](./replication_privileges.md)** — `REPLICATION SLAVE ADMIN`.
- **[Capacity Planning](./capacity_planning.md)** — sizing ресурсов.
- **[Операционные сценарии](./operational_scenarios.md)** — большие транзакции, DDL, WAN.
- **[Собеседование](./interview_questions.md)** — вопросы и ответы.
- **[Сценарии использования](./replication_use_cases.md)** — read scaling, бэкап, DR.
- **[Резервное копирование](../backup_and_recovery.md)** — методы создания снимков данных.