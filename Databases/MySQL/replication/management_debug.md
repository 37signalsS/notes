# Управление и отладка репликации

## Основные команды

- **`SHOW SLAVE STATUS\G`**: Основная команда для диагностики на Slave. Показывает состояние потоков, ошибки, отставание (`Seconds_Behind_Master`).

- **`SHOW MASTER STATUS\G`**: Показывает текущую позицию в бинарном логе на Master-сервере.

- **`START SLAVE;` / `STOP SLAVE;`**: Запуск и остановка репликации на Slave.

- **Пропуск ошибочной транзакции**: Если репликация остановилась из-за ошибки (например, дубликат ключа), ее можно пропустить:

    ```sql
    STOP SLAVE;
    SET GLOBAL SQL_SLAVE_SKIP_COUNTER = 1;
    START SLAVE;
    ```

## Особенности MySQL 8

### Плагин аутентификации

По умолчанию используется `caching_sha2_password` вместо `mysql_native_password`, что может вызвать проблемы совместимости со старыми клиентами. Варианты решения:

1. **Создать пользователя со старым плагином:**

    ```sql
    CREATE USER 'slave_user'@'%'
    IDENTIFIED WITH mysql_native_password BY '${REPLICATION_PASSWORD}';
    ```

2. **Использовать безопасную передачу пароля по RSA:**

    В команде `CHANGE MASTER TO` на slave-сервере указать опцию запроса публичного ключа:

    ```sql
    CHANGE MASTER TO GET_MASTER_PUBLIC_KEY = 1;
    ```

3. **(Менее безопасно) Вернуть старый плагин по умолчанию в `my.cnf` на мастере:**

    ```ini
    [mysqld]
    default-authentication-plugin=mysql_native_password
    ```

### Цепочечная репликация

Опция `log_slave_updates` (в старых версиях `log-slave-updates`) включена по умолчанию. Это значит, что slave записывает полученные от мастера изменения в свой бинарный лог, позволяя ему выступать мастером для других slave (M -> S1 -> S2). Раньше эту опцию нужно было включать явно.

---

**Связанные темы:**

* [Настройка репликации](./setup_guide.md) — пошаговое руководство
* [GTID](./gtid.md) — репликация на основе Global Transaction Identifier
* [Multi-Source репликация](../multi-source-replication.md)
