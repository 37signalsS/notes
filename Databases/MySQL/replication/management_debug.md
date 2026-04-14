# Управление и отладка репликации

## Definitions

**Диагностика репликации** — процесс мониторинга состояния потоков репликации, выявления ошибок и отставания (lag) между master и slave.

**Отставание репликации (Replication Lag)** — задержка между выполнением транзакции на master и её применением на slave. Измеряется в секундах (`Seconds_Behind_Master`).

## Basic Concepts

### Потоки репликации

Для работы репликации используются три потока:

| Поток | Сервер | Описание |
| :--- | :--- | :--- |
| I/O-поток | Slave | Подключается к master, читает binlog и записывает в relay log |
| SQL-поток | Slave | Читает relay log и применяет транзакции к данным |
| Binlog dump | Master | Отправляет события binlog подключенным slave |

### Ключевые метрики

- **`Slave_IO_Running`** — статус I/O-потока (`Yes`/`No`)
- **`Slave_SQL_Running`** — статус SQL-потока (`Yes`/`No`)
- **`Seconds_Behind_Master`** — отставание в секундах (NULL при ошибках)
- **`Last_Error`** — последняя ошибка, остановившая репликацию
- **`Last_IO_Error`**, **`Last_SQL_Error`** — детализация по потокам

## Practical Scenarios

### Базовые команды управления

```sql
-- Запуск репликации
START SLAVE;

-- Остановка репликации
STOP SLAVE;

-- Остановка и сброс всех настроек репликации
RESET SLAVE ALL;

-- Проверка статуса (вертикальный вывод для удобства)
SHOW SLAVE STATUS\G

-- Проверка статуса на master (текущая позиция binlog)
SHOW MASTER STATUS\G
```

### Диагностика состояния репликации

```sql
-- Полная информация о репликации
SHOW SLAVE STATUS\G

-- Ключевые поля для проверки:
--   Slave_IO_Running: Yes
--   Slave_SQL_Running: Yes
--   Seconds_Behind_Master: 0
--   Last_IO_Error: (пусто)
--   Last_SQL_Error: (пусто)
--   Auto_Position: Yes (для GTID)
```

### Таблица полей SHOW SLAVE STATUS

| Поле | Описание |
| :--- | :--- |
| `Slave_IO_Running` | Статус I/O-потока (чтение binlog master) |
| `Slave_SQL_Running` | Статус SQL-потока (применение транзакций) |
| `Seconds_Behind_Master` | Отставание в секундах (NULL = неизвестно) |
| `Master_Host`, `Master_User` | Параметры подключения к master |
| `Master_Log_File` | Текущий файл binlog на master |
| `Read_Master_Log_Pos` | Позиция, до которой slave прочитал master |
| `Relay_Master_Log_File` | Файл master, соответствующий текущей позиции relay log |
| `Exec_Master_Log_Pos` | Позиция выполнения SQL-потока |
| `Last_IO_Error` | Последняя ошибка I/O-потока |
| `Last_SQL_Error` | Последняя ошибка SQL-потока |
| `Retrieved_Gtid_Set` | GTID, полученные от master |
| `Executed_Gtid_Set` | GTID, выполненные на slave |
| `Auto_Position` | Режим GTID (`Yes`/`No`) |

### Пропуск ошибочной транзакции

Если репликация остановилась из-за ошибки (дубликат ключа, отсутствие таблицы):

```sql
-- Остановить репликацию
STOP SLAVE;

-- Пропустить одну транзакцию
SET GLOBAL SQL_SLAVE_SKIP_COUNTER = 1;

-- Запустить репликацию
START SLAVE;

-- Проверить статус
SHOW SLAVE STATUS\G
```

> **Предупреждение:** Пропуск транзакций может привести к рассинхронизации данных. Используйте только при понимании последствий.

### Пропуск транзакции в режиме GTID

```sql
STOP SLAVE;

-- Пропустить конкретный GTID
SET GTID_NEXT='3E11FA47-71CA-11E1-9E33-C80AA9429562:542';
BEGIN; COMMIT;
SET GTID_NEXT='AUTOMATIC';

START SLAVE;
```

Подробно о GTID — в [gtid.md](./gtid.md).

### Сброс и перенастройка репликации

```sql
-- Полная остановка и сброс
STOP SLAVE;
RESET SLAVE ALL;

-- Повторная настройка (классический режим)
CHANGE MASTER TO
  MASTER_HOST='master_host',
  MASTER_USER='repl_user',
  MASTER_PASSWORD='password',
  MASTER_LOG_FILE='mysql-bin.000001',
  MASTER_LOG_POS=154;

-- Или с GTID
CHANGE MASTER TO
  MASTER_HOST='master_host',
  MASTER_USER='repl_user',
  MASTER_PASSWORD='password',
  MASTER_AUTO_POSITION=1;

START SLAVE;
```

### Troubleshooting: частые ошибки

**Ошибка:** `Last_IO_Error: error connecting to master`

**Решение:**

- Проверить сеть между slave и master
- Убедиться, что master доступен (`ping`, `telnet master_host 3306`)
- Проверить пользователя репликации на master
- Проверить `MASTER_HOST`, `MASTER_USER`, `MASTER_PASSWORD`

**Ошибка:** `Last_SQL_Error: Duplicate entry for key 'PRIMARY'`

**Решение:**

- Пропустить транзакцию (см. выше)
- Или найти причину конфликта данных

**Ошибка:** `Seconds_Behind_Master: NULL`

**Решение:**

- Проверить, работает ли SQL-поток
- Проверить `Last_SQL_Error`
- NULL может означать, что slave не может определить отставание

### Мониторинг отставания

```sql
-- Быстрая проверка отставания
SHOW SLAVE STATUS\G | grep Seconds_Behind_Master

-- В скриптах (возвращает числовое значение)
SELECT 
  CASE 
    WHEN Slave_SQL_Running = 'Yes' AND Slave_IO_Running = 'Yes' 
    THEN Seconds_Behind_Master 
    ELSE NULL 
  END AS replication_lag
FROM information_schema.PROCESSLIST
WHERE USER = 'system user';
```

## Additional Information

### Особенности MySQL 8

#### Плагин аутентификации

По умолчанию используется `caching_sha2_password` вместо `mysql_native_password`, что может вызвать проблемы совместимости со старыми клиентами.

**Варианты решения:**

1. **Создать пользователя со старым плагином:**

    ```sql
    CREATE USER 'slave_user'@'%'
    IDENTIFIED WITH mysql_native_password BY '${REPLICATION_PASSWORD}';
    ```

2. **Использовать безопасную передачу пароля по RSA:**

    ```sql
    CHANGE MASTER TO GET_MASTER_PUBLIC_KEY = 1;
    ```

3. **Вернуть старый плагин по умолчанию (менее безопасно):**

    ```ini
    [mysqld]
    default-authentication-plugin=mysql_native_password
    ```

> **Важно:** Начиная с MySQL 8.0.27, `mysql_native_password` считается устаревшим. Рекомендуется использовать `caching_sha2_password` с SSL/TLS или `GET_MASTER_PUBLIC_KEY = 1`.

#### Цепочечная репликация

Опция `log_slave_updates` (в старых версиях `log-slave-updates`) включена по умолчанию. Это значит, что slave записывает полученные от мастера изменения в свой бинарный лог, позволяя ему выступать мастером для других slave (M → S1 → S2).

### Параллельная репликация (MySQL 5.7+)

Для ускорения применения транзакций на slave можно включить параллельное выполнение:

```ini
[mysqld]
slave_parallel_workers = 4
slave_parallel_type = LOGICAL_CLOCK
```

### SSL/TLS для репликации

Для безопасной передачи данных между master и slave:

```sql
CHANGE MASTER TO
  MASTER_SSL = 1,
  MASTER_SSL_CA = '/path/to/ca.pem',
  MASTER_SSL_CERT = '/path/to/client-cert.pem',
  MASTER_SSL_KEY = '/path/to/client-key.pem';
```

---

**См. также:** [Настройка репликации](./setup_guide.md), [GTID](./gtid.md), [Бинарный лог](./binlog_formats.md), [Multi-Source репликация](../multi-source-replication.md).
