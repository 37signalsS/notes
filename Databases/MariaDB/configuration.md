# Конфигурация MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**Конфигурационный файл (`my.cnf`):** Основной текстовый файл в формате INI, который MariaDB сервер и клиентские утилиты считывают при старте. Он определяет параметры производительности, пути к данным, сетевые настройки и плагины.

**Группа параметров (секция):** Блок настроек, ограниченный квадратными скобками (например, `[mariadb]`). Утилиты считывают только те секции, которые соответствуют их имени или общим группам.

**Директива `!includedir`:** Механизм рекурсивного включения всех файлов из указанной директории. Позволяет разделять конфигурацию на логические блоки (например, `galera.cnf`, `tuning.cnf`).

**Динамические переменные:** Параметры, которые можно изменить в реальном времени без перезагрузки сервера с помощью команды `SET GLOBAL`.

## Базовые концепции

### Иерархия и приоритеты загрузки

MariaDB считывает файлы в жестко определенном порядке. Если параметр встречается в нескольких файлах, применяется значение из **последнего** считанного файла.

1.  **/etc/my.cnf**: Глобальные настройки системы.
2.  **/etc/my.cnf.d/** (RHEL/CentOS) или **/etc/mysql/mariadb.conf.d/** (Debian/Ubuntu): Модульные файлы.
    - *Важно:* Файлы считываются в алфавитном порядке. Поэтому файлы с префиксами `99-custom.cnf` переопределяют настройки из `50-server.cnf`.
3.  **/etc/mysql/my.cnf**: Дополнительный глобальный путь (зависит от дистрибутива).
4.  **~/.my.cnf**: Пользовательские настройки. Используются для хранения учетных данных (`[client] user=... password=...`) для автоматизации без ввода пароля.

### Применение `MARIADB_GROUP_SUFFIX`

Этот механизм позволяет одному файлу конфигурации обслуживать разные окружения.
- Если запустить сервер с переменной окружения `MARIADB_GROUP_SUFFIX=.prod`, он будет считывать секции `[mariadb]` И `[mariadb.prod]`.
- Это исключает дублирование общих настроек и позволяет переопределять только специфичные параметры (например, размеры буферов) для разных сред.

### Управление переменными в рантайме

Не все параметры требуют перезагрузки сервера (`systemctl restart mariadb`).
- **Просмотр текущего значения:** `SHOW VARIABLES LIKE 'max_connections';`
- **Изменение без перезагрузки:** `SET GLOBAL max_connections = 1000;`
- **Временное изменение для сессии:** `SET SESSION wait_timeout = 600;`
- *Внимание:* Изменения через `SET GLOBAL` сбросятся после перезагрузки, если они не зафиксированы в `my.cnf`.

## Предварительные требования

Перед изменением параметров `my.cnf` убедитесь, что среда соответствует минимальным требованиям.

### Требования к оборудованию и ОС

- **ОЗУ:** Минимум 2GB для тестовых сред. Production: минимум 8GB, рекомендуется 16GB+.
- **Диск:** Поддерживаются любые файловые системы, совместимые с `O_DIRECT` (ext4, XFS, ZFS).
- **Ядра Linux:** 5.4+ для стабильной работы Thread Pool и Transparent Huge Pages.
- **Права доступа:** Пользователь `mysql` должен иметь права на запись в `datadir`, каталог логов и каталог сокета.

### Подготовка ОС

```bash
# Проверка прозрачных огромных страниц (THP)
cat /sys/kernel/mm/transparent_hugepage/enabled
# → рекомендуется: never

# Проверка лимитов файловых дескрипторов
ulimit -n
# → должно быть >= 65535 для production

# Проверка vm.swappiness
cat /proc/sys/vm/swappiness
# → рекомендуется: 1
```

**Валидация:**

```bash
# Проверка vm.swappiness
sysctl vm.swappiness
# → vm.swappiness = 1

# Проверка vm.overcommit_memory
sysctl vm.overcommit_memory
# → vm.overcommit_memory = 2 (рекомендуется для production)

# Проверка открытых файловых дескрипторов для mysql
cat /proc/$(pidof mysqld)/limits | grep "open files"
# → Max open files 65535 65535 files
```

## Практические сценарии

### 1. Конфигурация под высокую нагрузку и NVMe (MariaDB 12.3 LTS)

Пример конфигурации для сервера с 32ГБ ОЗУ и NVMe-дисками.

```ini
[mariadb]
# -- Пути и идентификация --
datadir                 = /var/lib/mysql
socket                  = /run/mysqld/mysqld.sock
user                    = mysql

# -- Сетевая подсистема --
bind-address            = 0.0.0.0 # Слушать на всех интерфейсах
max_connections         = 1000    # Лимит соединений
max_allowed_packet      = 64M     # Максимальный размер одного запроса/пакета
skip-name-resolve       = 1       # Отключает DNS-lookup (ускоряет подключение)

# -- Управление памятью и InnoDB --
# Рекомендуется выделять 60-75% доступной ОЗУ под Buffer Pool
innodb_buffer_pool_size         = 20G
innodb_flush_method             = O_DIRECT # Deprecated с 11.0; O_DIRECT — default на Unix с 10.6
innodb_log_file_size            = 2G       # Размер лога транзакций (WAL)
innodb_io_capacity              = 2000     # Лимит IOPS для фоновых задач InnoDB
innodb_io_capacity_max          = 4000

# -- Инновации MariaDB 12.3 --
# Атомарные логи: бинарный лог хранится внутри InnoDB для надежности
binlog_storage_engine           = innodb
# Оптимизация для современных SSD
innodb_flush_neighbors          = 0        # Не сбрасывать соседние страницы; игнорируется для табличных пространств на SSD

# -- Thread Pool (Масштабируемость) --
thread_handling                 = pool-of-threads
thread_pool_size                = 16       # Обычно равно кол-ву ядер CPU
thread_pool_max_threads         = 2000     # Жесткий лимит потоков

# -- Логирование --
slow_query_log                  = 1
long_query_time                 = 0.5      # Логировать запросы дольше 500мс
log_slow_verbosity              = explain,query_plan # Детальная диагностика в логе
```

**Валидация:**

```sql
-- Проверка параметров InnoDB
SHOW VARIABLES LIKE 'innodb_buffer_pool_size';
-- → innodb_buffer_pool_size = 21474836480 (20G)

SHOW VARIABLES LIKE 'innodb_io_capacity';
-- → innodb_io_capacity = 2000

SHOW VARIABLES LIKE 'binlog_storage_engine';
-- → binlog_storage_engine = innodb

-- Проверка статуса Buffer Pool
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool%';
-- → Innodb_buffer_pool_pages_total = 2621440 (для 20G при 16K page size)

-- Проверка размера лога транзакций
SHOW VARIABLES LIKE 'innodb_log_file_size';
-- → innodb_log_file_size = 2147483648 (2G)
```

> [!warning] `innodb_flush_method` помечен как deprecated с MariaDB 11.0
> Переменная продолжает работать, но не является динамической, а управление поведением сброса передано четырём булевым параметрам: `innodb_log_file_buffering`, `innodb_data_file_buffering`, `innodb_log_file_write_through`, `innodb_data_file_write_through`. Если заданы оба способа, `innodb_flush_method` транслируется в эти четыре параметра, а не наоборот. Подробно — в [InnoDB: долговечность и настройка записи](./innodb_durability_tuning.md).

### 2. Настройка пула соединений и лимитов

Параметры, управляющие параллелизмом и защищающие от перегрузки.

```ini
[mariadb]
# Лимит одновременных соединений
max_connections         = 1000

# Лимит на одного пользователя (защита от DoS)
max_user_connections    = 100

# Таймаут неактивных соединений (секунды)
wait_timeout            = 600
interactive_timeout     = 600

# Размер сетевого пакета
max_allowed_packet      = 64M
```

**Валидация:**

```sql
-- Проверка текущих лимитов
SHOW VARIABLES LIKE 'max_connections';
-- → max_connections = 1000

SHOW VARIABLES LIKE 'max_user_connections';
-- → max_user_connections = 100

SHOW VARIABLES LIKE 'wait_timeout';
-- → wait_timeout = 600

-- Проверка активных соединений
SHOW STATUS LIKE 'Threads_connected';
-- → Threads_connected = 15
```

### 3. Настройка логирования и ротации

```ini
[mariadb]
# Логирование медленных запросов
slow_query_log                  = 1
slow_query_log_file             = /var/log/mysql/slow.log
long_query_time                 = 0.5      # 500ms для production
log_slow_verbosity              = explain,query_plan

# Автоматическая ротация бинарных логов (предпочтительно с MariaDB 10.6.1)
binlog_expire_logs_seconds      = 604800   # 7 дней в секундах
# Алиас (не рекомендуется для новых конфигураций):
# expire_logs_days = 7

# Детализация error log (0-9, 2=по умолчанию; 3 — только для отладки)
log_warnings                  = 2
```

**Валидация:**

```sql
-- Проверка лога медленных запросов
SHOW VARIABLES LIKE 'slow_query_log';
-- → slow_query_log = ON

SHOW VARIABLES LIKE 'long_query_time';
-- → long_query_time = 0.500000

SHOW VARIABLES LIKE 'binlog_expire_logs_seconds';
-- → binlog_expire_logs_seconds = 604800

-- Проверка текущих бинарных логов
SHOW BINARY LOGS;
-- → список файлов и размеров
```

### 4. Настройка InnoDB для OLTP и архивных нагрузок

Для архивных нагрузок с большими таблицами Aria/MyISAM:

```ini
[mariadb]
# Для смешанной нагрузки InnoDB + Aria
innodb_buffer_pool_size         = 16G
key_buffer_size                 = 4G        # Для индексов Aria/MyISAM
aria_pagecache_buffer_size      = 2G        # Кэш страниц Aria

# Увеличение размера таблицы для больших объёмов
open_files_limit               = 65535
table_open_cache               = 4000
table_definition_cache         = 2000
```

**Валидация:**

```sql
-- Проверка размера Buffer Pool
SHOW VARIABLES LIKE 'innodb_buffer_pool_size';
-- → innodb_buffer_pool_size = 17179869184 (16G)

SHOW VARIABLES LIKE 'key_buffer_size';
-- → key_buffer_size = 4294967296 (4G)

-- Проверка кэша таблиц
SHOW STATUS LIKE 'Opened_tables';
-- → Opened_tables = 0 (цель: стабильное значение без роста)
```

### 5. Режимы только для чтения

Для реплик и окон обслуживания:

```ini
[mariadb]
# Режим только чтение (для реплик или обслуживания)
read_only = ON

# Супер-режим только чтения (блокирует даже SUPER-аккаунты)
# Включите только после read_only = ON
super_read_only = ON
```

**Валидация:**

```sql
-- Проверка режима
SHOW VARIABLES LIKE 'read_only';
-- → read_only = ON

SHOW VARIABLES LIKE 'super_read_only';
-- → super_read_only = ON

-- Временная разблокировка для обслуживания (только для SUPER)
SET GLOBAL super_read_only = OFF;
-- ...выполните обслуживание...
SET GLOBAL super_read_only = ON;
```

## Устранение неполадок (Troubleshooting)

### Ошибка: `Permission denied` на сокет или каталог данных

**Причина:** Пользователь `mysql` не имеет прав на запись в `datadir` или каталог сокета.

**Диагностика:**

```bash
# Проверка владельца каталога данных
ls -ld /var/lib/mysql
# → drwxr-xr-x mysql mysql /var/lib/mysql

# Проверка каталога сокета
ls -ld /run/mysqld/
# → drwxr-xr-x mysql mysql /run/mysqld/
```

**Решение:** Установите владельца `mysql:mysql` и права `755`:

```bash
chown -R mysql:mysql /var/lib/mysql
chown mysql:mysql /run/mysqld
chmod 755 /run/mysqld
```

### Ошибка: `unknown variable` или `syntax error` при старте

**Причина:** В `my.cnf` используется параметр, удалённый в текущей версии MariaDB (например, `innodb_buffer_pool_instances` в 10.6+, `big_tables`, `storage_engine`). Параметр `query_cache_size` при этом НЕ удалён — он валиден во всех версиях MariaDB, но выключен по умолчанию (`query_cache_type=OFF`).

**Диагностика:**

```bash
# Проверка логов systemd
journalctl -u mariadb --since "10 minutes ago"
# → строки с [ERROR] и указанием на строку в my.cnf
```

**Решение:** Найдите строку с ошибкой в логах, отредактируйте `my.cnf` и перезапустите:

```bash
systemctl restart mariadb
mariadb-admin -u root ping
# → mysqld is alive
```

### Ошибка: `Out of memory` или OOM Kill

**Причина:** Сумма `Global Buffers + Per-Thread Buffers × max_connections` превышает доступную ОЗУ. Подробный расчёт см. в **[Управление памятью в MariaDB](memory_management.md)**.

**Диагностика:**

```bash
# Проверка логов ядра
dmesg | grep -i "oom\|killed process"
# → [19534.841025] mysqld invoked oom-killer

# Проверка RSS процесса
ps -o pid,rss,vsz,cmd -p $(pidof mysqld)
# → RSS близок к лимиту ОЗУ
```

**Решение:** Уменьшите `innodb_buffer_pool_size` или `max_connections` в `my.cnf`. Добавьте swap как временную меру. Для containerized окружения проверьте cgroup лимиты.

### Ошибка: Конфигурация игнорируется после перезагрузки

**Причина:** Параметр изменён через `SET GLOBAL`, но не зафиксирован в `my.cnf`. Либо параметр статический и требует перезагрузки, либо файл считывается не из того пути.

**Диагностика:**

```bash
# Проверка путей конфигурации
mariadb --help --verbose | grep -A 1 "Default options"
# → /etc/my.cnf /etc/mysql/my.cnf ~/.my.cnf

# Проверка активного значения
mariadb -e "SHOW VARIABLES LIKE 'innodb_buffer_pool_size';"
```

**Решение:** Добавьте параметр в `my.cnf` и перезапустите сервер. Для динамических параметров используйте `SET GLOBAL` как временное решение.

### Ошибка: `Too many connections`

**Причина:** `max_connections` исчерпан или Thread Pool не справляется с нагрузкой.

**Диагностика:**

```sql
SHOW STATUS LIKE 'Threads_connected';
SHOW VARIABLES LIKE 'max_connections';
SHOW STATUS LIKE 'Threads_running';
```

**Решение:**
1. Увеличьте `max_connections` в `my.cnf`.
2. Если используется Thread Pool, проверьте `thread_pool_max_threads`.
3. Для приложений с большим количеством коротких соединений используйте ProxySQL или MaxScale вместо увеличения `max_connections`.

### Ошибка: Конфликт параметров в `my.cnf`

**Причина:** Один параметр указан в нескольких секциях или файлах. Применяется значение из последнего считанного файла.

**Диагностика:**

```bash
# Проверка всех источников конфигурации
mariadb --help --verbose | grep -A 20 "Default options"
```

**Решение:** Удалите дублирующиеся определения. Используйте `!includedir` для модульности, но избегайте конфликтов имён файлов.

## Best Practices

1. **Версионный контроль конфигурации:** Храните `my.cnf` в Git. Используйте `diff` для аудита изменений между окружениями.
2. **Модульная конфигурация:** Разделяйте настройки по файлам: `50-server.cnf` (базовые), `60-innodb.cnf` (движок), `70-security.cnf` (безопасность), `99-custom.cnf` (переопределения).
3. **Избегайте `SET GLOBAL` в production:** Все критичные параметры должны быть в `my.cnf`. `SET GLOBAL` сбрасывается при перезагрузке.
4. **Валидация после изменений:** После любого изменения конфигурации проверяйте `SHOW VARIABLES` и `SHOW GLOBAL STATUS` на предмет аномалий.
5. **Documentation by code:** Каждый параметр в `my.cnf` должен иметь комментарий с обоснованием значения.
6. **OS tuning перед MariaDB tuning:** Выполняйте настройку ОС (THP, swappiness, ulimit) перед изменением параметров MariaDB.

## Дополнительная информация

### Смежные темы
- **[Обзор MariaDB](overview.md)** — архитектура и стратегия развития.
- **[Управление памятью в MariaDB](memory_management.md)** — расчёт глобальных и per-thread буферов, диагностика утечек.
- **[Резервное копирование MariaDB](backup_and_recovery.md)** — `mariadb-backup` и `mariadb-dump`.
- **[Безопасность MariaDB](security/index.md)** — многоуровневая модель безопасности.
- **[Дополнительные параметры безопасности](security/additional-parameters.md)** — базовый набор hardening-параметров.
- **[Мониторинг MariaDB](monitoring.md)** — отслеживание метрик через Prometheus.
- **[Клиентские утилиты](client_utilities.md)** — использование `--defaults-file` и `--defaults-extra-file`.
- **[High Availability](high_availability.md)** — настройка Galera Cluster (подробная конфигурация `wsrep_*` параметров).
- **[Стандартная репликация MariaDB](./replication/overview.md)** — настройка Source-Replica и GTID.

### Внешние ресурсы
- [MariaDB Server System Variables](https://mariadb.com/docs/server/server-system-variables/)
- [MariaDB SQL Mode](https://mariadb.com/docs/server/sql-mode/)
- [MariaDB Read Only Variables](https://mariadb.com/docs/server/sql-statements/storage-engines/replication-statistics/#read-only-and-super-read-only)
