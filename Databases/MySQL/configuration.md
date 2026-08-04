# Конфигурация MySQL (my.cnf)

## Определения

**Конфигурационный файл (my.cnf)** — текстовый файл, содержащий параметры настройки сервера `mysqld` и клиентских утилит. Файл считывается при запуске процесса для определения архитектурных лимитов, путей к данным и параметров производительности.

**Секция конфигурации** — именованный блок параметров, ограниченный квадратными скобками.
- `[mysqld]`: Основные настройки сервера базы данных.
- `[client]`: Настройки, применяемые ко всем клиентским программам (mysql, mysqldump).
- `[mysql]`: Специфичные настройки интерактивной оболочки.

**mysqld-auto.cnf** — JSON-файл в директории данных (`datadir`), в который записываются параметры, измененные командой `SET PERSIST`. Имеет приоритет над обычным `my.cnf`.

## Базовые концепции

### 1. Расположение и иерархия
MySQL ищет конфигурацию в нескольких местах. Если параметр указан в нескольких файлах, применяется значение из файла, загруженного **последним**.

**Типовые пути (Linux):**
1.  `/etc/my.cnf` — Глобальный файл (RHEL/Rocky).
2.  `/etc/mysql/my.cnf` — Глобальный файл (Debian/Ubuntu).
3.  `/etc/mysql/mysql.conf.d/mysqld.cnf` — Конфигурация сервера в Ubuntu.
4.  `~/.my.cnf` — Пользовательские настройки.

### 2. Валидация конфигурации
Перед перезагрузкой сервера **обязательно** проверяйте синтаксис файла, чтобы избежать сбоя при старте.

```bash
# Проверка синтаксиса без запуска сервера
mysqld --validate-config

# Если ошибок нет, команда ничего не выведет и вернет код 0
echo $?
```

### 3. Динамическая настройка и персистентность
В MySQL 8.4+ параметры делятся на динамические (можно менять без перезагрузки) и статические.

```sql
-- Изменение и сохранение параметра между перезагрузками
SET PERSIST innodb_redo_log_capacity = 2147483648;

-- Удаление персистентной настройки
RESET PERSIST innodb_redo_log_capacity;
```

### 4. Ключевые группы параметров MySQL 8.4 LTS

#### Автоматический тюнинг
- **`innodb_dedicated_server = ON`**: Автоматически рассчитывает `innodb_buffer_pool_size` и `innodb_redo_log_capacity` на основе ресурсов системы. Идеально для выделенных серверов и Docker-контейнеров.

#### Дисковая подсистема (InnoDB)
- **`innodb_redo_log_capacity`**: Основной параметр объема журналов транзакций. В 8.4 заменяет старые `innodb_log_file_size`. Рекомендуется от 2GB до 16GB в зависимости от интенсивности записи.
- **`innodb_io_capacity = 10000`**: Дефолт в 8.4 оптимизирован под NVMe. Для старых HDD следует снизить до 200–500.
- **`innodb_flush_method = O_DIRECT`**: Исключает двойное кэширование данных в ОС. Критично для производительности на Linux.

#### Логирование и репликация
- **`binlog_expire_logs_seconds = 604800`**: Хранение бинарных логов (7 дней).
- **`slow_query_log = 1`**: Включение лога медленных запросов.
- **`long_query_time = 1.0`**: Порог фиксации медленного запроса (в секундах).

## Практические сценарии

### Оптимальная конфигурация для SSD (MySQL 8.4 LTS)

Пример файла `/etc/mysql/mysql.conf.d/mysqld.cnf` для сервера с 16GB+ ОЗУ.

```ini
[mysqld]
# -- Базовые настройки --
user                    = mysql
datadir                 = /var/lib/mysql
socket                  = /var/run/mysqld/mysqld.sock
bind-address            = 0.0.0.0
port                    = 3306

# -- Автотюнинг (Рекомендуется) --
innodb_dedicated_server = ON

# -- Тюнинг InnoDB (Ручной, если auto-tuning выключен) --
# innodb_buffer_pool_size = 12G
# innodb_redo_log_capacity = 2G

# -- Оптимизация ввода-вывода --
innodb_flush_method     = O_DIRECT
innodb_io_capacity      = 10000
innodb_io_capacity_max  = 20000
# Адаптивный хэш-индекс по умолчанию OFF в 8.4 для снижения конкуренции за мьютексы
innodb_adaptive_hash_index = OFF

# -- Соединения и память --
max_connections         = 1000
max_allowed_packet      = 256M
table_open_cache        = 4000

# -- Безопасность --
# В 9.0 полностью удален mysql_native_password
# В 8.4 по умолчанию caching_sha2_password
default_authentication_plugin = caching_sha2_password

# -- Логирование --
log_error               = /var/log/mysql/error.log
slow_query_log          = 1
long_query_time         = 1.0
log_queries_not_using_indexes = 0

# -- Репликация (Source) --
server-id               = 101
log_bin                 = /var/log/mysql/mysql-bin.log
binlog_format           = ROW
gtid_mode               = ON
enforce_gtid_consistency = ON
binlog_expire_logs_seconds = 604800
```

## Дополнительная информация

### Проверка текущих настроек
```sql
-- Просмотр значения переменной
SHOW VARIABLES LIKE 'innodb_redo_log_capacity';

-- Просмотр динамических изменений (SET PERSIST)
SELECT * FROM performance_schema.persisted_variables;

-- Проверка эффективности Buffer Pool
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read_requests';
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_reads';
-- Hit Rate = 1 - (reads / read_requests)
```

### См. также
- **[Обзор MySQL и форков](./overview.md)** — архитектура и внутренние механизмы.
- **[Репликация в MySQL: Обзор](./replication/overview.md)** — детали настройки GTID и бинарных логов.
- **[Мониторинг MySQL](./monitoring.md)** — использование Performance Schema.
