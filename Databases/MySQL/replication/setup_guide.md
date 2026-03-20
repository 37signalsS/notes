# Пошаговая настройка Master-Slave репликации

Теоретические основы репликации (синхронная, асинхронная, топологии) и CAP-теорема рассмотрены в основной заметке: **[Репликация баз данных](../../Concepts/replication.md)**.

## Шаг 1: Настройка Master-сервера

### 1. Редактирование конфигурации (`my.cnf`)

В файле конфигурации (обычно `/etc/mysql/my.cnf` или `/etc/mysql/mysql.conf.d/mysqld.cnf`) в секции `[mysqld]` укажите:

```ini
[mysqld]
# Уникальный ID сервера в кластере (целое число > 0)
server-id = 1

# Имя файла, активирующее ведение бинарного лога
log_bin = /var/log/mysql/mysql-bin.log
```

> После изменения конфигурации перезапустите сервис MySQL.

### 2. Создание пользователя для репликации

Создайте на Master-сервере специального пользователя, от имени которого Slave будет подключаться.

```sql
-- Для безопасности рекомендуется указать IP-адрес slave-сервера вместо '%'
CREATE USER 'slave_user'@'%' IDENTIFIED BY '${REPLICATION_PASSWORD}';

-- Выдача необходимых прав
GRANT REPLICATION SLAVE ON *.* TO 'slave_user'@'%';

FLUSH PRIVILEGES;
```

## Шаг 2: Создание дампа и фиксация позиции на Master

Для инициализации реплики необходимо создать дамп текущих данных и зафиксировать позицию в бинарном логе на этот момент.

Используйте `mysqldump` с флагами, которые автоматически добавляют в дамп координаты для старта репликации:

```bash
# --single-transaction: создает консистентный дамп для InnoDB без блокировки таблиц.
# --master-data=2: добавляет в дамп закомментированную команду CHANGE MASTER TO.
# (Используйте --master-data=1, если не хотите, чтобы команда была закомментирована).
mysqldump -u root -p --all-databases --single-transaction --master-data=2 > master_dump.sql

# Для MyISAM требуется полная блокировка:
# mysqldump -u root -p --all-databases --lock-all-tables --master-data=2 > master_dump.sql
```

Флаг `--master-data=2` добавит в начало дампа строку с координатами для запуска репликации:

```sql
-- CHANGE MASTER TO MASTER_LOG_FILE='mysql-bin.000001', MASTER_LOG_POS=154;
```

## Шаг 3: Настройка Slave-сервера

### 1. Редактирование конфигурации (`my.cnf`)

На Slave-сервере также задайте уникальный `server-id`.

```ini
[mysqld]
# ID должен отличаться от ID master-сервера
server-id = 2

# (Опционально) Лог для отладки репликации
relay-log = /var/log/mysql/mysql-relay-bin.log

# (Опционально) Включает бинарный лог, если slave будет мастером для другого slave
# (необходимо для каскадной репликации: Master -> Slave1 -> Slave2).
# В MySQL 8+ опция log_slave_updates, отвечающая за это, включена по умолчанию.
log_bin = /var/log/mysql/mysql-bin.log
```

> После изменения конфигурации перезапустите сервис MySQL.

## Шаг 4: Восстановление данных и запуск репликации на Slave

### 1. Загрузка дампа

Перенесите файл `master_dump.sql` на Slave-сервер и примените его:

```bash
mysql -u root -p < master_dump.sql
```

### 2. Подключение к Master и запуск

Выполните на Slave команду `CHANGE MASTER TO`, используя данные из дампа и дополнив их учетными данными.

```sql
-- Раскомментируйте и дополните строку из файла master_dump.sql
CHANGE MASTER TO
  MASTER_HOST='<ip_адрес_мастера>',
  MASTER_USER='slave_user',
  MASTER_PASSWORD='${REPLICATION_PASSWORD}',
  MASTER_LOG_FILE='mysql-bin.000001', -- из дампа
  MASTER_LOG_POS=154;                 -- из дампа

START SLAVE;
```

### 3. Проверка статуса

Проверьте статус репликации. Оба потока должны иметь статус `Yes`.

```sql
SHOW SLAVE STATUS\G
```

Ключевые поля:
- `Slave_IO_Running: Yes` — I/O-поток успешно получает данные от Master.
- `Slave_SQL_Running: Yes` — SQL-поток успешно применяет данные.
- `Seconds_Behind_Master: 0` — Отставание от мастера отсутствует.

---

**Связанные темы:**

* [Обзор репликации](./overview.md) — определения, ключевые компоненты
* [Механизм Master-Slave](./master_slave_mechanism.md) — потоки репликации
* [Управление и отладка](./management_debug.md) — диагностика проблем
* [GTID](./gtid.md) — современная настройка с MASTER_AUTO_POSITION
