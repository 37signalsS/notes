# Пошаговая настройка репликации MySQL

## Определения

**Репликация MySQL** — процесс синхронизации данных между несколькими серверами, где один сервер (Источник) передает изменения другим серверам (Репликам).

**Источник (Source)** — сервер, принимающий изменения и записывающий их в бинарный лог.
**Реплика (Replica)** — сервер, который считывает бинарный лог источника и применяет изменения к своим данным.

**Классическая репликация** — метод на основе точных координат бинарного лога (**Binary Log**). Требует ручного указания имени файла (`SOURCE_LOG_FILE`) и смещения (`SOURCE_LOG_POS`).

**GTID-репликация (Global Transaction Identifier)** — современный стандарт, использующий уникальные ID транзакций. Позволяет автоматически находить позицию в логах (`SOURCE_AUTO_POSITION = 1`), что упрощает восстановление и Failover.

## Основные концепции

### Предварительные требования

| Параметр | Описание |
| :--- | :--- |
| **Сетевая связность** | Доступ к порту 3306. Проверка: `nc -zv <source_ip> 3306`. |
| **server_id** | Уникальное число (1-4294967295) для каждого узла в топологии. |
| **binlog_format** | Рекомендуется `ROW` (обязателен для GTID и Group Replication). |
| **Версии** | Реплика должна быть той же версии или новее. Источник новее Реплики не поддерживается в LTS-релизах (например, 8.4). |

### Методы инициализации данных

1.  **Clone Plugin:** Прямое копирование физических данных (блоков InnoDB). Самый быстрый способ для MySQL 8.0.17+.
2.  **MySQL Shell (`util.dumpInstance`):** Параллельный логический дамп. Значительно быстрее классического `mysqldump` для баз > 50 ГБ.
3.  **mysqldump:** Классический инструмент. Использовать с флагами `--single-transaction --set-gtid-purged=ON`.

## Практические сценарии

### 1. Подготовка пользователя (на Источнике)

Для MySQL 8.0+ рекомендуется использовать плагин аутентификации `caching_sha2_password`.

```sql
CREATE USER 'repl_user'@'%' IDENTIFIED BY 'StrongPassword123!';
GRANT REPLICATION SLAVE ON *.* TO 'repl_user'@'%';

-- Если планируется использовать Clone Plugin
GRANT BACKUP_ADMIN ON *.* TO 'repl_user'@'%';
```

### 2. Настройка через Clone Plugin

Позволяет создать реплику "с нуля" без ручного переноса дампов.

**На Источнике и Реплике:**
```sql
INSTALL PLUGIN clone SONAME 'mysql_clone.so';
```

**На Реплике:**
```sql
-- Разрешаем прием данных с конкретного хоста
SET GLOBAL clone_valid_donor_list = '192.168.1.10:3306';

-- Запуск клонирования (сервер перезагрузится автоматически)
CLONE INSTANCE FROM 'repl_user'@'192.168.1.10':3306 IDENTIFIED BY 'StrongPassword123!';
```

### 3. Настройка GTID-репликации (Конфигурация)

Рекомендуемый режим для всех новых инсталляций.

**Параметры `my.cnf` (на всех узлах):**
```ini
[mysqld]
server_id = 101
gtid_mode = ON
enforce_gtid_consistency = ON

# Настройки бинарного лога
log_bin = /var/log/mysql/mysql-bin.log
log_replica_updates = ON
binlog_format = ROW

# Время хранения логов (заменяет устаревший expire_logs_days)
binlog_expire_logs_seconds = 604800 # 7 дней
```

**Запуск на Реплике:**
```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='192.168.1.10',
  SOURCE_USER='repl_user',
  SOURCE_PASSWORD='StrongPassword123!',
  SOURCE_AUTO_POSITION = 1,
  GET_SOURCE_PUBLIC_KEY = 1;

START REPLICA;
```

### 4. Использование фильтров репликации

Если необходимо реплицировать только конкретные базы данных. Настраивается на **Реплике**.

```ini
[mysqld]
# Реплицировать только указанную БД
replicate-do-db = production_db
# Игнорировать системные или временные БД
replicate-ignore-db = test_db
```
*Внимание: При использовании GTID отфильтрованные транзакции всё равно фиксируются в `gtid_executed` как пустые.*

## Дополнительная информация

### Мониторинг и производительность

**Основные команды:**
```sql
-- Статус репликации
SHOW REPLICA STATUS\G

-- Мониторинг через Performance Schema (более детально)
SELECT * FROM performance_schema.replication_connection_status;
SELECT * FROM performance_schema.replication_applier_status_by_worker;
```

**Ускорение репликации (Многопоточность):**
Если `Seconds_Behind_Source` растет, включите параллельное применение транзакций:
```sql
STOP REPLICA;
SET GLOBAL replica_parallel_type = 'LOGICAL_CLOCK';
SET GLOBAL replica_parallel_workers = 4; -- По числу ядер CPU
START REPLICA;
```

### Безопасность

- **Read Only:** На репликах всегда устанавливайте `super_read_only = 1`.
- **Защита данных:** Используйте `require_table_primary_key_check = ON` (8.0.21+), чтобы гарантировать наличие первичных ключей. Репликация таблиц без PK работает крайне медленно (Full Table Scan на каждое изменение).
- **Шифрование:** Добавьте `SOURCE_SSL = 1` в `CHANGE REPLICATION SOURCE TO` для защиты трафика.

### См. также

- **[Обзор репликации MySQL](./overview.md)**
- **[GTID-репликация в деталях](./gtid.md)**
- **[Управление и отладка](./management_debug.md)**
- **[Multi-Source репликация](./multi-source.md)**
