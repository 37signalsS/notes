# Пошаговая настройка Master-Slave репликации

## Definitions

**Классическая репликация** — настройка репликации по координатам бинарного лога (`MASTER_LOG_FILE`, `MASTER_LOG_POS`). Требует точной фиксации позиции на момент создания дампа.

**GTID-репликация** — современная настройка с автоматическим определением позиции (`MASTER_AUTO_POSITION = 1`). Рекомендуется для MySQL 5.7+.

## Basic Concepts

### Предварительные требования

| Требование | Описание |
| :--- | :--- |
| Версия MySQL | 5.7+ (рекомендуется), 8.0+ (предпочтительно) |
| Совместимость версий | Minor-версии должны совпадать (например, 5.7.x → 5.7.x) |
| Сетевая связность | Port 3306 открыт между Master и Slave |
| Дисковое пространство | Достаточно места для данных + binlog + relay log |
| Привилегии | ROOT или SUPER на обоих серверах |

### Типы настройки

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| По координатам binlog | Классический метод с `MASTER_LOG_FILE` + `MASTER_LOG_POS` | MySQL < 5.7, совместимость |
| С GTID | Автоматическое позиционирование (`MASTER_AUTO_POSITION = 1`) | MySQL 5.7+ (рекомендуется) |

Подробно о GTID — в [gtid.md](./gtid.md).

### Необходимые привилегии

Для настройки репликации требуется пользователь с правами:

```sql
-- На Master: пользователь для репликации
CREATE USER 'slave_user'@'%' IDENTIFIED BY '${REPLICATION_PASSWORD}';
GRANT REPLICATION SLAVE ON *.* TO 'slave_user'@'%';
FLUSH PRIVILEGES;
```

> **Безопасность:** Укажите конкретный IP-адрес Slave вместо `%` для ограничения доступа.

## Practical Scenarios

### Сценарий 1: Классическая настройка (по binlog координатам)

#### Шаг 1: Настройка Master-сервера

**1.1. Редактирование конфигурации (`my.cnf`)**

В файле конфигурации (обычно `/etc/mysql/my.cnf` или `/etc/mysql/mysql.conf.d/mysqld.cnf`) в секции `[mysqld]` укажите:

```ini
[mysqld]
# Уникальный ID сервера в кластере (целое число > 0)
server-id = 1

# Имя файла, активирующее ведение бинарного лога
log_bin = /var/log/mysql/mysql-bin.log

# (Опционально) Максимальный размер одного файла binlog
max_binlog_size = 100M

# (Опционально) Автоматическое удаление старых binlog
binlog_expire_logs_seconds = 604800  # 7 дней
```

Перезапустите сервис MySQL:
```bash
sudo systemctl restart mysql
```

**1.2. Создание пользователя для репликации**

```sql
-- Рекомендуется указать IP-адрес slave-сервера вместо '%'
CREATE USER 'slave_user'@'192.168.1.2' IDENTIFIED BY '${REPLICATION_PASSWORD}';
GRANT REPLICATION SLAVE ON *.* TO 'slave_user'@'192.168.1.2';
FLUSH PRIVILEGES;

-- Проверка созданного пользователя
SELECT User, Host FROM mysql.user WHERE User = 'slave_user';
```

#### Шаг 2: Создание дампа и фиксация позиции на Master

**2.1. Создание дампа**

Используйте `mysqldump` с флагами для автоматической фиксации координат:

```bash
# Для InnoDB (без блокировки таблиц)
mysqldump -u root -p --all-databases --single-transaction --master-data=2 > master_dump.sql

# Для MyISAM (требуется блокировка)
# mysqldump -u root -p --all-databases --lock-all-tables --master-data=2 > master_dump.sql
```

**Описание флагов:**
- `--single-transaction` — создает консистентный дамп для InnoDB без блокировки
- `--master-data=2` — добавляет закомментированную `CHANGE MASTER TO` в дамп
- `--master-data=1` — то же, но команда не закомментирована (используйте осторожно)

**2.2. Фиксация позиции**

Флаг `--master-data=2` добавит в начало дампа строку:

```sql
-- CHANGE MASTER TO MASTER_LOG_FILE='mysql-bin.000001', MASTER_LOG_POS=154;
```

Запишите эти значения — они потребуются на шаге 4.

**Альтернатива:** Текущую позицию можно получить командой:
```sql
SHOW MASTER STATUS;
-- Запомните: File (mysql-bin.000001), Position (154)
```

#### Шаг 3: Настройка Slave-сервера

**3.1. Редактирование конфигурации (`my.cnf`)**

```ini
[mysqld]
# ID должен отличаться от ID master-сервера
server-id = 2

# (Опционально) Лог для отладки репликации
relay-log = /var/log/mysql/mysql-relay-bin.log

# (Опционально) Для каскадной репликации (Master -> Slave1 -> Slave2)
# В MySQL 8+ включено по умолчанию
log_bin = /var/log/mysql/mysql-bin.log
```

Перезапустите сервис MySQL:
```bash
sudo systemctl restart mysql
```

#### Шаг 4: Восстановление данных и запуск репликации на Slave

**4.1. Загрузка дампа**

Перенесите файл `master_dump.sql` на Slave-сервер и примените его:

```bash
mysql -u root -p < master_dump.sql
```

**4.2. Подключение к Master и запуск**

Выполните на Slave команду `CHANGE MASTER TO`:

```sql
CHANGE MASTER TO
  MASTER_HOST='192.168.1.1',           -- IP-адрес мастера
  MASTER_USER='slave_user',
  MASTER_PASSWORD='${REPLICATION_PASSWORD}',
  MASTER_LOG_FILE='mysql-bin.000001',  -- из дампа (шаг 2.2)
  MASTER_LOG_POS=154;                  -- из дампа (шаг 2.2)

START SLAVE;
```

**4.3. Проверка статуса**

```sql
SHOW SLAVE STATUS\G
```

**Ожидаемый результат:**
- `Slave_IO_Running: Yes` — I/O-поток получает данные от Master
- `Slave_SQL_Running: Yes` — SQL-поток применяет данные
- `Seconds_Behind_Master: 0` — отставание отсутствует
- `Last_IO_Error: (пусто)`
- `Last_SQL_Error: (пусто)`

---

### Сценарий 2: Настройка с GTID (MySQL 5.7+)

#### Шаг 1: Включение GTID на всех серверах

Добавьте в конфигурацию (`my.cnf`) на **Master и Slave**:

```ini
[mysqld]
server-id = <уникальный_id>  # 1 для Master, 2 для Slave
gtid_mode = ON
enforce_gtid_consistency = ON
log_bin = /var/log/mysql/mysql-bin.log
log_slave_updates = ON
```

Перезапустите MySQL на всех серверах.

#### Шаг 2: Создание пользователя репликации

На Master:
```sql
CREATE USER 'slave_user'@'%' IDENTIFIED BY '${REPLICATION_PASSWORD}';
GRANT REPLICATION SLAVE ON *.* TO 'slave_user'@'%';
FLUSH PRIVILEGES;
```

#### Шаг 3: Создание и загрузка дампа

```bash
# На Master: создание дампа
mysqldump -u root -p --all-databases --single-transaction > master_dump.sql

# На Slave: загрузка дампа
mysql -u root -p < master_dump.sql
```

#### Шаг 4: Запуск репликации с GTID

На Slave:
```sql
CHANGE MASTER TO
  MASTER_HOST='192.168.1.1',
  MASTER_USER='slave_user',
  MASTER_PASSWORD='${REPLICATION_PASSWORD}',
  MASTER_AUTO_POSITION = 1;  # Ключевое отличие от классического метода

START SLAVE;
```

#### Шаг 5: Проверка

```sql
SHOW SLAVE STATUS\G

-- Проверьте:
--   Auto_Position: Yes
--   Slave_IO_Running: Yes
--   Slave_SQL_Running: Yes
```

Подробно о GTID — в [gtid.md](./gtid.md).

---

### Troubleshooting: частые проблемы

**Проблема:** `Slave_IO_Running: No`, ошибка подключения

**Решение:**
```sql
SHOW SLAVE STATUS\G | grep Last_IO_Error
```
- Проверьте сетевую доступность Master (`telnet master_host 3306`)
- Убедитесь в правильности `MASTER_USER` и `MASTER_PASSWORD`
- Проверьте привилегии пользователя на Master

**Проблема:** `Slave_SQL_Running: No`, ошибка дубликата ключа

**Решение:**
```sql
SHOW SLAVE STATUS\G | grep Last_SQL_Error

-- Пропуск ошибочной транзакции
STOP SLAVE;
SET GLOBAL SQL_SLAVE_SKIP_COUNTER = 1;
START SLAVE;
```

**Проблема:** `Seconds_Behind_Master` постоянно растет

**Решение:**
- Проверьте нагрузку на Slave (возможно, не хватает ресурсов)
- Включите параллельную репликацию (MySQL 5.7+):
  ```ini
  [mysqld]
  slave_parallel_workers = 4
  slave_parallel_type = LOGICAL_CLOCK
  ```

**Проблема:** Репликация не запускается после восстановления из дампа

**Решение:**
- Убедитесь, что `server-id` уникален на каждом сервере
- Проверьте, что пользователь репликации существует на Master
- Убедитесь, что binlog Master содержит указанную позицию

## Additional Information

### Проверка после настройки

```sql
-- На Slave: комплексная проверка
SHOW SLAVE STATUS\G

-- На Master: проверка подключенных slave
SHOW SLAVE HOSTS;

-- Проверка отставания в реальном времени
WATCH (SELECT 
  Slave_IO_Running, 
  Slave_SQL_Running, 
  Seconds_Behind_Master 
FROM information_schema.PROCESSLIST 
WHERE USER = 'system user');
```

### Безопасность

| Мера | Описание |
| :--- | :--- |
| Ограничение по IP | Используйте `'slave_user'@'192.168.1.2'` вместо `'%'` |
| Сложный пароль | Минимум 16 символов, спецсимволы |
| SSL/TLS | Настройте зашифрованное соединение для репликации |
| Отдельный пользователь | Не используйте root для репликации |

### MySQL 8.0+ особенности

- **Плагин аутентификации:** По умолчанию `caching_sha2_password`. Для совместимости используйте `mysql_native_password` или `GET_MASTER_PUBLIC_KEY = 1`
- **log_slave_updates:** Включено по умолчанию
- **GTID:** Рекомендуется использовать с момента настройки

### Удаление репликации

```sql
-- На Slave: полная очистка
STOP SLAVE;
RESET SLAVE ALL;
RESET MASTER;  # Очистка binlog на Slave

-- Удаление пользователя на Master
DROP USER 'slave_user'@'%';
```

---

**См. также:** [Обзор репликации](./overview.md), [Механизм Master-Slave](./master_slave_mechanism.md), [GTID](./gtid.md), [Управление и отладка](./management_debug.md), [Общие концепции репликации](../../Concepts/replication.md).
