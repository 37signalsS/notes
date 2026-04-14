# Репликация на основе GTID (Global Transaction Identifier)

## Definitions

**GTID (Global Transaction Identifier)** — уникальный идентификатор транзакции, присваиваемый каждой транзакции при выполнении на master-сервере. Гарантирует однозначную идентификацию транзакции во всём кластере.

**Формат GTID:** `source_id:transaction_id`

- `source_id` — UUID сервера (например, `3E11FA47-71CA-11E1-9E33-C80AA9429562`)
- `transaction_id` — порядковый номер транзакции (например, `1-542`)

**Пример:** `3E11FA47-71CA-11E1-9E33-C80AA9429562:1-542`

**GTID-репликация** — режим репликации, при котором slave отслеживает выполненные транзакции по их GTID, а не по позиции в бинарном логе.

## Basic Concepts

### Преимущества GTID перед классической репликацией

| Преимущество | Описание |
| :--- | :--- |
| Упрощённое переключение master | При failover не нужно отслеживать имя файла и позицию binlog |
| Автоматическое определение позиции | Slave сам определяет, какие транзакции уже применены |
| Гарантированная консистентность | Каждая транзакция выполняется только один раз в кластере |
| Упрощённая настройка | Не требуется указывать `MASTER_LOG_FILE` и `MASTER_LOG_POS` |
| Идемпотентность | Повторное применение той же транзакции автоматически игнорируется |

### Принцип работы

1. Каждая транзакция на master получает уникальный GTID перед записью в binlog
2. Slave читает GTID из binlog master и сохраняет в таблице `mysql.gtid_executed`
3. При переключении master slave автоматически запрашивает недостающие GTID
4. Система отслеживает выполненные (`gtid_executed`) и очищенные (`gtid_purged`) транзакции

### Требования и ограничения

- **Все серверы в кластере должны иметь включенный GTID** — нельзя смешивать режимы
- **`enforce_gtid_consistency = ON`** — запрещает недетерминированные запросы
- **Включение требует перезапуска** — нельзя включить на работающей репликации без пересоздания
- **Необратимо** — после включения рекомендуется не отключать

## Practical Scenarios

### Включение GTID

Добавьте в конфигурацию (`my.cnf` / `mysqld.cnf`) на **всех** серверах кластера:

```ini
[mysqld]
gtid_mode = ON
enforce_gtid_consistency = ON
log_bin = /var/log/mysql/mysql-bin.log
log_slave_updates = ON
server-id = <уникальный_id>
```

> **Важно:** Требуется перезапуск MySQL. Порядок включения: сначала slave, затем master.

### Пошаговая активация (без пересоздания репликации)

Для MySQL 5.7+ существует постепенный путь миграции:

```ini
# Шаг 1: На всех серверах (перезапуск не требуется)
gtid_mode = OFF_PERMISSIVE
enforce_gtid_consistency = ON

# Шаг 2: На всех серверах (перезапуск не требуется)
gtid_mode = ON_PERMISSIVE

# Шаг 3: Проверка статуса
SHOW STATUS LIKE 'Gtid_mode';
# Должно вернуться: ON_PERMISSIVE

# Шаг 4: На всех серверах (перезапуск не требуется)
gtid_mode = ON

# Шаг 5: Отключить обратную совместимость (опционально)
gtid_mode = ON
```

### Настройка репликации с GTID

1. **На master создайте пользователя репликации:**

    ```sql
    CREATE USER 'slave_user'@'%' IDENTIFIED BY '${REPLICATION_PASSWORD}';
    GRANT REPLICATION SLAVE ON *.* TO 'slave_user'@'%';
    FLUSH PRIVILEGES;
    ```

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

    Убедитесь, что `Auto_Position: Yes` и оба потока работают (`Slave_IO_Running: Yes`, `Slave_SQL_Running: Yes`).

### Переключение master (failover)

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

### Диагностика и мониторинг

```sql
-- Проверка выполненных GTID на сервере
SELECT @@GLOBAL.gtid_executed;

-- Проверка очищенных GTID (удалены из binlog)
SELECT @@GLOBAL.gtid_purged;

-- Проверка режима GTID
SELECT @@GLOBAL.gtid_mode;

-- Просмотр набора GTID, которые slave получил от master
SHOW SLAVE STATUS\G
-- Поля: Retrieved_Gtid_Set, Executed_Gtid_Set
```

### Ручное управление GTID

```sql
-- Сброс всех GTID (опасно! только для тестовых сред)
RESET MASTER;

-- Установка gtid_purged (при восстановлении из дампа)
SET GLOBAL gtid_purged = '3E11FA47-71CA-11E1-9E33-C80AA9429562:1-1000';

-- Пропуск конкретной транзакции GTID (при ошибках репликации)
SET GTID_NEXT='3E11FA47-71CA-11E1-9E33-C80AA9429562:542';
BEGIN; COMMIT;
SET GTID_NEXT='AUTOMATIC';
```

> **Предупреждение:** Ручное управление GTID может привести к рассинхронизации. Используйте только при понимании последствий.

### Best Practices

| Задача | Решение |
| :--- | :--- |
| Включение GTID | Постепенная миграция через `OFF_PERMISSIVE` → `ON_PERMISSIVE` → `ON` |
| Failover | Использовать `MASTER_AUTO_POSITION = 1` на всех slave |
| Восстановление | Синхронизировать `gtid_purged` перед стартом репликации |
| Мониторинг | Отслеживать `Retrieved_Gtid_Set` и `Executed_Gtid_Set` |

## Additional Information

### Переменные GTID

| Переменная | Описание |
| :--- | :--- |
| `gtid_executed` | Диапазон всех выполненных транзакций на сервере |
| `gtid_purged` | Транзакции, которые были удалены из binlog |
| `gtid_owned` | GTID, которые текущая сессия выполняет в данный момент |
| `gtid_next` | GTID для следующей транзакции (для ручного управления) |
| `gtid_mode` | Текущий режим GTID (`OFF`, `ON`, `OFF_PERMISSIVE`, `ON_PERMISSIVE`) |

### GTID Sets

GTID может представляться как набор диапазонов:

- `UUID:1-542` — транзакции с 1 по 542
- `UUID:1-100,UUID:200-250` — несколько диапазонов
- `UUID:1-542,UUID2:1-100` — несколько серверов

### Проблемы и решения

**Проблема:** Репликация остановилась с ошибкой дубликата GTID.

**Решение:**

```sql
STOP SLAVE;
SET GLOBAL SQL_SLAVE_SKIP_COUNTER = 1;
START SLAVE;
```

Или пропустить конкретный GTID (см. выше).

**Проблема:** `gtid_purged` не синхронизирован при восстановлении из дампа.

**Решение:**

```sql
-- Перед импортом дампа на slave
SET GLOBAL gtid_purged = '<значение_из_мастера>';
```

### Сравнение с классической репликацией

| Параметр | Классическая (binlog) | GTID |
| :--- | :--- | :--- |
| Идентификация позиции | `MASTER_LOG_FILE` + `MASTER_LOG_POS` | `MASTER_AUTO_POSITION = 1` |
| Failover | Ручное указание позиции | Автоматическое определение |
| Консистентность | Зависит от формата binlog | Гарантирована |
| Сложность настройки | Выше | Ниже |
| Требования | Минимальные | `enforce_gtid_consistency` |

### MySQL 8.0+ особенности

- Улучшена производительность таблицы `mysql.gtid_executed`
- Добавлена поддержка `gtid_next` для параллельной репликации
- Улучшена обработка ошибок при конфликтах GTID

---

**См. также:** [Настройка репликации](./setup_guide.md), [Форматы бинарного лога](./binlog_formats.md), [Управление и отладка](./management_debug.md), [Multi-Source репликация](../multi-source-replication.md).
