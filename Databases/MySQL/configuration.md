# Конфигурация MySQL (my.cnf)

## Определения

**Конфигурационный файл (my.cnf / my.ini)** — текстовый файл в формате INI, считываемый сервером `mysqld` и клиентскими утилитами при запуске. Он определяет границы ресурсов, пути к данным, параметры безопасности и настройки производительности.

**mysqld-auto.cnf** — файл в формате JSON, расположенный в `datadir`. В него записываются параметры, измененные через `SET PERSIST`. Этот файл считывается **после** всех `my.cnf`, переопределяя их значения.

**Область видимости (Scope):**
- **GLOBAL:** Параметры, влияющие на весь сервер (например, размер Buffer Pool).
- **SESSION:** Настройки, которые могут быть переопределены для конкретного подключения (например, `sql_mode` или `sort_buffer_size`).

**Типы переменных:**
- **Динамические:** Можно изменить в рантайме без перезагрузки сервера (`SET GLOBAL ...`).
- **Статические:** Требуют перезапуска службы для применения (например, `innodb_log_file_size` в старых версиях или `datadir`).

## Базовые концепции

### 1. Иерархия и приоритеты загрузки
MySQL считывает файлы в строгом порядке. Если один и тот же параметр указан в нескольких файлах, приоритет имеет тот, что был считан **последним**.

**Типовой порядок загрузки в Linux:**
1.  `/etc/my.cnf` — Глобальные настройки системы.
2.  `/etc/mysql/my.cnf` — Основной путь в Debian/Ubuntu.
3.  `SYSCONFDIR/my.cnf` — Конфигурация, заданная при компиляции.
4.  `$MYSQL_HOME/my.cnf` — Настройки из домашней директории MySQL.
5.  `--defaults-extra-file` — Дополнительный файл, указанный в аргументах запуска.
6.  `~/.my.cnf` — Пользовательские настройки (часто используются для хранения паролей клиентов).
7.  `mysqld-auto.cnf` — Персистентные настройки MySQL 8.0+.

**Диагностика иерархии:**
```bash
# Узнать, какие файлы и в каком порядке ищет MySQL
mysqld --help --verbose | grep -A 1 "Default options"

# Посмотреть финальный результат слияния всех конфигов
mysqld --print-defaults
```

### 2. Динамическое управление (SET PERSIST)
В MySQL 8.4 LTS механизмы управления конфигурацией стали более гибкими. Теперь не обязательно вручную редактировать файлы на диске для сохранения настроек.

```sql
-- Изменение параметра и его сохранение в mysqld-auto.cnf
SET PERSIST innodb_max_dirty_pages_pct = 90;

-- Сохранение только в память (сбросится после рестарта)
SET GLOBAL max_connections = 2000;

-- Просмотр переменных, измененных через PERSIST
SELECT * FROM performance_schema.persisted_variables;

-- Удаление настройки из mysqld-auto.cnf
RESET PERSIST innodb_max_dirty_pages_pct;
```

### 3. Валидация конфигурации
Ошибки в `my.cnf` — частая причина отказа сервера при запуске. Всегда проверяйте синтаксис перед `systemctl restart`.

```bash
# Проверка синтаксиса (выводит ошибки в stderr)
mysqld --validate-config

# Если вывод пуст — ошибок нет.
```

## Практические сценарии

### 1. Управление памятью (InnoDB Buffer Pool)
Buffer Pool — самая важная область памяти, где кэшируются данные и индексы таблиц InnoDB.
- **Рекомендация:** На выделенном сервере выделяйте 50–75% всей RAM.
- **Нюанс:** Если Buffer Pool > 1GB, разделите его на сегменты (`innodb_buffer_pool_instances`), чтобы уменьшить конкуренцию между потоками.

**Автоматический тюнинг (8.4 LTS):**
```ini
[mysqld]
# MySQL сам рассчитает Buffer Pool и Redo Log на основе доступной RAM
innodb_dedicated_server = ON
```

### 2. Оптимизация дискового ввода-вывода (I/O)
Для современных NVMe/SSD дисков стандартные настройки могут быть слишком консервативными.

```ini
[mysqld]
# Исключаем двойное кэширование (рекомендуется для Linux)
innodb_flush_method = O_DIRECT

# Количество IOPS, которые может выдать диск (NVMe: 10000+, SSD: 2000+)
innodb_io_capacity = 10000
innodb_io_capacity_max = 20000

# Размер журнала транзакций (WAL). В 8.4 заменяет innodb_log_file_size
innodb_redo_log_capacity = 2G
```

### 3. Тюнинг соединений
```ini
[mysqld]
# Максимальное кол-во одновременных сессий
max_connections = 1000

# Очередь на подключение (увеличьте при всплесках нагрузки)
back_log = 512

# Тайм-аут ожидания неактивного соединения (по умолчанию 8 часов, лучше снизить)
wait_timeout = 600
interactive_timeout = 600
```

### 4. Эталонный конфиг для Production (MySQL 8.4 LTS)
Пример `/etc/mysql/mysql.conf.d/mysqld.cnf` для сервера с 16GB RAM и SSD.

```ini
[mysqld]
# -- Идентификация и пути --
user                    = mysql
pid-file                = /var/run/mysqld/mysqld.pid
socket                  = /var/run/mysqld/mysqld.sock
datadir                 = /var/lib/mysql
bind-address            = 0.0.0.0

# -- Оптимизация ресурсов --
innodb_dedicated_server = ON
# Если выключено, настраивайте вручную:
# innodb_buffer_pool_size = 12G
# innodb_redo_log_capacity = 2G

# -- InnoDB I/O --
innodb_flush_method     = O_DIRECT
innodb_flush_log_at_trx_commit = 1
innodb_io_capacity      = 5000
innodb_adaptive_hash_index = OFF

# -- Сеть и Соединения --
max_connections         = 1000
max_allowed_packet      = 128M
skip-name-resolve       = 1  # Отключает DNS-запросы, ускоряет вход

# -- Безопасность --
# В 9.0 удален mysql_native_password, в 8.4 по умолчанию caching_sha2_password
authentication_policy   = caching_sha2_password,,

# -- Логирование --
log_error               = /var/log/mysql/error.log
slow_query_log          = 1
slow_query_log_file     = /var/log/mysql/slow-query.log
long_query_time         = 1.0

# -- Репликация (Modern GTID) --
server-id               = 101
log_bin                 = /var/log/mysql/mysql-bin.log
binlog_format           = ROW
gtid_mode               = ON
enforce_gtid_consistency = ON
binlog_expire_logs_seconds = 604800 # 7 дней
```

## Поиск и устранение неисправностей (Troubleshooting)

### Сервер не запускается после правки my.cnf
1.  **Проверьте логи:** `tail -n 100 /var/log/mysql/error.log`. Обычно там указана строка с ошибкой.
2.  **Типичная ошибка:** Опечатки в названиях (например, `innodb_buffer_pool_siz` вместо `size`).
3.  **Права доступа:** Файл `my.cnf` должен быть доступен для чтения пользователю `mysql`, но защищен от записи другими. Оптимально: `644`.

### MySQL потребляет слишком много памяти (OOM Killer)
- **Причина:** Общая сумма `innodb_buffer_pool_size` + (кол-во соединений * `thread_stack` / `sort_buffer_size`) превышает RAM.
- **Решение:** Уменьшите Buffer Pool или `max_connections`. Используйте `innodb_dedicated_server = ON` для безопасного автопилота.

### Права на .my.cnf
Если клиент выдает предупреждение `World-writable config file is ignored`:
- **Решение:** `chmod 600 ~/.my.cnf`. MySQL игнорирует файлы конфигурации с небезопасными правами.

## Дополнительная информация

### Рекомендации (Best Practices)
1.  **Версионность:** Храните конфигурацию в Git.
2.  **Модульность:** Используйте директиву `!includedir /etc/mysql/conf.d/` для разделения настроек (репликация, тюнинг, безопасность).
3.  **Сравнение:** Используйте утилиту `mysqltuner` для получения быстрых советов по оптимизации на основе статистики работы.

### Краевые случаи (Edge Cases)
- **Контейнеризация:** В Docker лимиты памяти (cgroups) могут не видеться `innodb_dedicated_server` корректно в старых версиях. В 8.4 это исправлено, но проверяйте результат через `SHOW VARIABLES`.
- **Case Sensitivity:** Названия параметров нечувствительны к регистру, но пути к файлам в Linux — чувствительны.

### См. также
- **[Обзор MySQL и форков](./overview.md)** — архитектура InnoDB и WAL.
- **[Репликация в MySQL: Обзор](./replication/overview.md)** — детали настройки GTID.
- **[Мониторинг MySQL](./monitoring.md)** — использование Performance Schema для отладки.
- **[Безопасная установка СУБД](../installation_security.md)** — защита конфигурационных файлов.
