# Пошаговая настройка Master-Slave репликации

## Определения

**Классическая репликация** — метод настройки тиражирования данных на основе точных координат бинарного лога (Binary Log). Включает в себя имя файла лога (`MASTER_LOG_FILE`) и позицию в нём (`MASTER_LOG_POS`).

**GTID-репликация (Global Transaction Identifier)** — современный метод репликации, использующий глобальные уникальные идентификаторы транзакций. Обеспечивает автоматическое позиционирование (`MASTER_AUTO_POSITION = 1`), что упрощает управление кластером и процесс переключения мастера (failover).

## Основные концепции

### Предварительные требования

| Требование | Описание |
| :--- | :--- |
| Версия MySQL | 5.7+ (рекомендуется), 8.0+ (предпочтительно) |
| Совместимость | Мажорные версии должны совпадать или Slave должен быть новее Master |
| Сеть | Порт TCP 3306 открыт между серверами |
| Ресурсы | Достаточно места для данных, бинарных логов и Relay Log |

### Методы настройки

- **По координатам бинарного лога:** Традиционный подход, требующий ручной фиксации позиции при создании дампа данных.
- **С использованием GTID:** Рекомендуемый подход для новых инсталляций, исключающий необходимость отслеживания позиций файлов лога.

Подробности о работе идентификаторов — в документе **[GTID-репликация](./gtid.md)**.

### Привилегии пользователя

Для процесса репликации на Master-сервере должен быть создан технический пользователь с правами `REPLICATION SLAVE`.

```sql
-- Создание пользователя (на Master)
CREATE USER 'slave_user'@'192.168.1.2' IDENTIFIED BY 'secure_password';
GRANT REPLICATION SLAVE ON *.* TO 'slave_user'@'192.168.1.2';
FLUSH PRIVILEGES;
-- -> Query OK, 0 rows affected
```

## Практические сценарии

### Сценарий 1: Классическая настройка (по координатам)

#### 1. Настройка Master-сервера

В конфигурационном файле (`my.cnf` или `mysqld.cnf`) в секции `[mysqld]` установите:

```ini
[mysqld]
server-id = 1
log_bin = /var/log/mysql/mysql-bin.log
binlog_expire_logs_seconds = 604800
```

Перезапустите сервис:

```bash
sudo systemctl restart mysql
# -> (перезапуск выполнен успешно)
```

Зафиксируйте текущую позицию лога:

```sql
SHOW MASTER STATUS;
/*
+------------------+----------+--------------+------------------+
| File             | Position | Binlog_Do_DB | Binlog_Ignore_DB |
+------------------+----------+--------------+------------------+
| mysql-bin.000001 |      154 |              |                  |
+------------------+----------+--------------+------------------+
*/
```

#### 2. Создание и перенос дампа

Создайте консистентный снимок данных:

```bash
mysqldump -u root -p --all-databases --single-transaction --master-data=2 > master_dump.sql
# -> (файл master_dump.sql создан)
```

#### 3. Настройка и запуск Slave-сервера

Установите уникальный `server-id` в конфигурации Slave и перезапустите его. Затем загрузите дамп и настройте подключение:

```bash
mysql -u root -p < master_dump.sql
# -> (данные импортированы)
```

```sql
CHANGE MASTER TO
  MASTER_HOST='192.168.1.1',
  MASTER_USER='slave_user',
  MASTER_PASSWORD='secure_password',
  MASTER_LOG_FILE='mysql-bin.000001',
  MASTER_LOG_POS=154;
-- -> Query OK, 0 rows affected

START SLAVE;
-- -> Query OK, 0 rows affected
```

---

### Сценарий 2: Настройка с использованием GTID

#### 1. Подготовка конфигурации

На **всех** серверах добавьте в `my.cnf`:

```ini
[mysqld]
gtid_mode = ON
enforce_gtid_consistency = ON
log_bin = /var/log/mysql/mysql-bin.log
log_slave_updates = ON
```

#### 2. Запуск репликации

После переноса дампа на Slave выполните:

```sql
CHANGE MASTER TO
  MASTER_HOST='192.168.1.1',
  MASTER_USER='slave_user',
  MASTER_PASSWORD='secure_password',
  MASTER_AUTO_POSITION = 1;
-- -> Query OK, 0 rows affected

START SLAVE;
-- -> Query OK, 0 rows affected
```

## Дополнительная информация

### Проверка статуса

Основная команда для мониторинга на стороне Slave:

```sql
SHOW SLAVE STATUS\G
/*
             Slave_IO_Running: Yes
            Slave_SQL_Running: Yes
        Seconds_Behind_Master: 0
                Last_IO_Error: 
               Last_SQL_Error: 
*/
```

### Частые ошибки

- **Смещение server-id:** Если идентификаторы серверов совпадают, репликация не запустится.
- **Ошибки сети:** Проверьте доступность порта 3306 через `telnet` или `nc`.
- **Дубликаты ключей:** Возникают при записи напрямую на Slave. Рекомендуется использовать режим `read_only = 1` на всех репликах.

**См. также:**

- **[Обзор репликации MySQL](./overview.md)**
- **[Механизм работы Master-Slave](./master_slave_mechanism.md)**
- **[Диагностика и отладка репликации](./management_debug.md)**
