# Репликация на основе GTID (Global Transaction Identifier)

**GTID** — это уникальный идентификатор транзакции, который присваивается каждой транзакции при её выполнении на master-сервере. GTID имеет формат `source_id:transaction_id`, где `source_id` — UUID сервера, а `transaction_id` — порядковый номер транзакции.

## Преимущества GTID перед классической репликацией по binlog

- **Упрощённое переключение master:** При failover не нужно отслеживать имя файла и позицию binlog — достаточно указать новый master-host.
- **Автоматическое определение позиции:** Slave сам определяет, какие транзакции уже применены, на основе GTID.
- **Гарантированная консистентность:** Каждая транзакция выполняется только один раз в кластере.
- **Упрощённая настройка:** Не требуется указывать `MASTER_LOG_FILE` и `MASTER_LOG_POS`.

## Включение GTID

Для использования GTID добавьте в конфигурацию (`my.cnf`) на всех серверах кластера:

```ini
[mysqld]
gtid_mode = ON
enforce_gtid_consistency = ON
log_bin = /var/log/mysql/mysql-bin.log
log_slave_updates = ON
```

> **Важно:** Включение GTID требует перезапуска сервера и не может быть выполнено на уже работающей репликации без пересоздания.

## Настройка репликации с GTID

1. **На master создайте пользователя репликации** (как в обычной настройке).

2. **На slave выполните:**

    ```sql
    CHANGE MASTER TO
      MASTER_HOST='<ip_адрес_мастера>',
      MASTER_USER='slave_user',
      MASTER_PASSWORD='${REPLICATION_PASSWORD}',
      MASTER_AUTO_POSITION = 1;

    START SLAVE;
    ```

    Параметр `MASTER_AUTO_POSITION = 1` активирует использование GTID.

3. **Проверка статуса:**

    ```sql
    SHOW SLAVE STATUS\G
    ```

    Убедитесь, что `Auto_Position: Yes`.

## Переключение master при использовании GTID

При выходе master из строя и повышении slave до роли нового master:

```sql
-- На новом master (бывший slave)
STOP SLAVE;
RESET SLAVE ALL;

-- На остальных slave
CHANGE MASTER TO
  MASTER_HOST='<ip_нового_мастера>',
  MASTER_USER='slave_user',
  MASTER_PASSWORD='${REPLICATION_PASSWORD}',
  MASTER_AUTO_POSITION = 1;

START SLAVE;
```

GTID автоматически определит недостающие транзакции и продолжит репликацию с правильной позиции.

## Важные нюансы

- **`gtid_executed`:** Содержит диапазон уже выполненных транзакций. Используется для определения позиции при восстановлении.
- **`gtid_purged`:** Транзакции, которые были удалены из binlog. При настройке нового slave может потребоваться синхронизация этих значений.
- **Переход с классической репликации:** Требует полного пересоздания репликации с дампа данных.

---

**Связанные темы:**

* [Настройка репликации](./setup_guide.md) — классическая настройка по binlog
* [Управление и отладка](./management_debug.md) — команды диагностики
* [Multi-Source репликация](./multi-source-replication.md)
