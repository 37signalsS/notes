# Конфигурация MySQL (my.cnf)

**Актуально для:** MySQL 5.7 (legacy — версия завершила поддержку 2023-10; приведена
для миграции) / 8.0 / 8.4 LTS

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
# Проверка синтакса (выводит ошибки в stderr)
mysqld --validate-config

# Если вывод пуст — ошибок нет.
```

**Валидация в эксплуатации:**
```sql
-- Проверка критичных параметров после рестарта
SHOW VARIABLES LIKE 'innodb_buffer_pool_size';
SHOW VARIABLES LIKE 'innodb_dedicated_server';
SHOW VARIABLES LIKE 'max_connections';
SHOW VARIABLES LIKE 'bind_address';
```

### 4. Системные требования и подготовка ОС

MySQL — процесс с высокими требованиями к дисковому вводу-выводу и памяти. Настройка ОС напрямую влияет на стабильность и производительность СУБД.

**Память и hugepages:**
```bash
# Отключение swap для предотвращения stalls (требует достаточного RAM)
sudo swapoff -a

# Резерв копирование sysctl.conf
sudo cp /etc/sysctl.conf /etc/sysctl.conf.bak

# Настройка параметров ядра
cat <<EOF | sudo tee -a /etc/sysctl.conf
# MySQL / InnoDB оптимизация
vm.swappiness = 10
vm.nr_hugepages = 1024
fs.file-max = 65535
fs.aio-max-nr = 1048576
EOF

sudo sysctl -p
```

**Ограничения файловых дескрипторов:**
```bash
# Для systemd-сервиса (см. unit-файл ниже)
cat <<EOF | sudo tee /etc/systemd/system/mysql.conf.d/limits.conf
[Service]
LimitNOFILE = 65535
EOF
```

**Планирование емкости (Capacity Planning):**
Формула для выделенного сервера БД:
- **RAM:** `innodb_buffer_pool_size` + per-connection buffers (`sort_buffer_size` + `join_buffer_size` + `read_buffer_size` + `thread_stack`) × `max_connections` + OS overhead (~1–2GB) ≤ физическая RAM.
- **Диск:** Под `datadir` + `innodb_log_file_size` + binlog + relay log + slow query log + error log. Минимум 20% свободного пространства для дефрагментации и бэкапов.
- **IOPS:** `innodb_io_capacity` должен соответствовать реальной возможностям диска. NVMe: 10000–20000, SSD: 2000–5000, HDD: 100–200.

**Смежные системные настройки (не дублируются здесь):**

| Тема | Где разобрано подробно |
| :--- | :--- |
| Transparent Huge Pages (THP), дефрагментация, `khugepaged` | **[HugePages и THP](../../Linux/Core/memory/performance_tuning.md)** |
| Диагностика влияния THP на latency | **[Диагностика tail latency](../../Linux/Diagnostics/Performance/diagnosing_tail_latency.md)** |
| HugePages для баз данных, `hugetlbfs`, резервирование страниц | **[Виртуальные файловые системы](../../Linux/FileSystems/virtual_filesystems.md)** (раздел «Оптимизация HugePages для баз данных») |
| Диагностика памяти процесса, `smaps`, `pmap` | **[Диагностика производительности памяти](../../Linux/Diagnostics/Performance/memory_performance_diagnostics.md)** |
| Swap и его влияние на СУБД | **[Влияние подкачки на ввод-вывод](../../Linux/Diagnostics/Performance/DiskIO/swap_io_impact.md)** |
| Планирование ёмкости по памяти и диску | **[Capacity planning](../../Concepts/capacity-planning.md)** |

Правило: параметры ядра (`vm.*`, `fs.*`) настраиваются здесь, а их обоснование
и диагностика — в указанных файлах. Не меняйте системные параметры для СУБД,
не прочитав соответствующий раздел.

### 5. Стандартные права и владение файлами

Все файлы данных и конфигурации должны принадлежать пользователю `mysql:mysql`.

```bash
# Проверка и исправление прав
sudo chown -R mysql:mysql /var/lib/mysql
sudo chown -R mysql:mysql /etc/mysql
sudo chmod 750 /var/lib/mysql
sudo chmod 644 /etc/mysql/my.cnf
sudo chmod 644 /etc/mysql/conf.d/*.cnf

# Запрет записи для group/others на конфигах
sudo chmod 600 /etc/mysql/conf.d/production.cnf
```

**Валидация:**
```bash
ls -la /etc/mysql/my.cnf
# → -rw-r--r-- 1 mysql mysql ...

sudo -u mysql mysqld --validate-config
# → (пустой вывод при отсутствии ошибок)
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

**Ручной тюнинг (если автономный режим отключен):**
```ini
[mysqld]
# Размер Buffer Pool должен быть кратен innodb_buffer_pool_chunk_size × instances
innodb_buffer_pool_size = 12G
innodb_buffer_pool_instances = 12
innodb_buffer_pool_chunk_size = 128M
```

**Быстрый дамп/загрузка Buffer Pool при рестарте:**
```ini
[mysqld]
# Дамп содержимого Buffer Pool при остановке
innodb_buffer_pool_dump_at_shutdown = ON
# Автозагрузка при старте
innodb_buffer_pool_load_at_startup = ON
```

### 2. Оптимизация дискового ввода-вывода (I/O)

Для современных NVMe/SSD дисков стандартные настройки могут быть слишком консервативными.

```ini
[mysqld]
# Исключаем двойное кэширование (рекомендуется для Linux)
innodb_flush_method = O_DIRECT

# Отключение flush соседних страниц (только для SSD/NVMe)
innodb_flush_neighbors = 0

# Количество IOPS, которые может выдать диск (NVMe: 10000+, SSD: 2000+)
innodb_io_capacity = 10000
innodb_io_capacity_max = 20000

# Потоки для асинхронного I/O (по умолчанию: 4 read + 4 write)
innodb_read_io_threads = 8
innodb_write_io_threads = 8

# Глубина сканирования LRU (подбирайте под workload)
innodb_lru_scan_depth = 1024

# Размер журнала транзакций (WAL). В 8.4 заменяет innodb_log_file_size
innodb_redo_log_capacity = 2G
```

### 3. Тюнинг соединений и кэширование

```ini
[mysqld]
# Максимальное кол-во одновременных сессий
max_connections = 1000

# Очередь на подключение (увеличьте при всплесках нагрузки)
back_log = 512

# Тайм-аут ожидания неактивного соединения (по умолчанию 8 часов, лучше снизить)
wait_timeout = 600
interactive_timeout = 600

# Кэширование соединений для снижения накладных расходов
thread_cache_size = 100

# Максимальный размер временных таблиц в памяти (на запрос)
tmp_table_size = 64M
max_heap_table_size = 64M

# Кэш открытых таблиц
table_open_cache = 4000
table_definition_cache = 2000
```

### 4. Кодировки и сравнения по умолчанию

UTF-8mb4 — единственный безопасный выбор для новых инсталляций.

```ini
[mysqld]
character_set_server = utf8mb4
collation_server = utf8mb4_0900_ai_ci
```

**Валидация:**
```sql
SHOW VARIABLES LIKE 'character_set%';
SHOW VARIABLES LIKE 'collation%';
```

### 5. Репликация и бинарные логи

Для продакшн-репликации требуется GTID, ROW-формат и корректные retention-настройки.

```ini
[mysqld]
# Включение бинарного логирования (обязательно для репликации)
log_bin = /var/log/mysql/mysql-bin.log

# Имя сервера (должно быть уникальным в топологии)
server-id = 101

# Формат бинарного лога (ROW — единственный безопасный для GTID)
binlog_format = ROW

# Включение GTID (MySQL 5.7.6+)
gtid_mode = ON
enforce_gtid_consistency = ON

# Размер файла бинарного лога (по умолчанию 1G)
max_binlog_size = 256M

# Хранение бинарных логов: 7 дней
binlog_expire_logs_seconds = 604800

# Разрешение создания функций/триггеров без SUPER (для реплик)
log_bin_trust_function_creators = ON
```

**Примечание:** Детальная настройка GTID, полусинхронной репликации и SSL-каналов описана в [Репликация MySQL: Обзор](./replication/overview.md).

### 6. Performance Schema и sys schema

Performance Schema — источник метрик для отладки производительности. Включение всех счетчиков влияет на накладные расходы (~5–10% CPU).

```ini
[mysqld]
# Включение Performance Schema (рекомендуется для Production)
performance_schema = ON

# Включение sys schema (упрощает запросы к Performance Schema)
sys_schema = ON
```

**Валидация:**
```sql
-- Проверка включения
SHOW VARIABLES LIKE 'performance_schema';
SHOW VARIABLES LIKE 'sys_schema';

-- Быстрая проверка через sys schema
SELECT * FROM sys.memory_global_total;
SELECT * FROM sys.file_summary_by_event_name LIMIT 5;
```

Детали диагностики и мониторинга через Performance Schema описаны в [Мониторинг MySQL](./monitoring.md).

### 7. Эталонный конфиг для Production (MySQL 8.4 LTS)

Пример `/etc/mysql/mysql.conf.d/mysqld.cnf` для сервера с 16GB RAM и SSD.

```ini
[mysqld]
# -- Идентификация и пути --
user                    = mysql
pid-file                = /var/run/mysqld/mysqld.pid
socket                  = /var/run/mysqld/mysqld.sock
datadir                 = /var/lib/mysql
bind-address            = 10.0.0.5

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
innodb_flush_neighbors  = 0
innodb_read_io_threads  = 8
innodb_write_io_threads = 8

# -- Сеть и Соединения --
max_connections         = 1000
max_allowed_packet      = 128M
skip-name-resolve       = 1  # Отключает DNS-запросы, ускоряет вход
wait_timeout            = 600
interactive_timeout     = 600
thread_cache_size       = 100

# -- Временные таблицы и кэш --
tmp_table_size          = 64M
max_heap_table_size     = 64M
table_open_cache        = 4000
table_definition_cache  = 2000

# -- Кодировки --
character_set_server    = utf8mb4
collation_server        = utf8mb4_0900_ai_ci

# -- Безопасность --
authentication_policy   = caching_sha2_password,,
local_infile            = OFF
secure_file_priv        = /var/lib/mysql-files

# -- Логирование --
log_error               = /var/log/mysql/error.log
slow_query_log          = 1
slow_query_log_file     = /var/log/mysql/slow-query.log
long_query_time         = 1.0
log_queries_not_using_indexes = 1        # попадать в лог запросы без индексов
log_slow_admin_statements = 1            # включать административные операторы
log_slow_replica_statements = 1          # писать ли запросы, приходящие от реплик
log_timestamps          = UTC            # метки времени в логах (UTC или SYSTEM)
log_slow_extra          = ON             # доп. поля: thread_id, schema, rows_affected
min_examined_row_limit  = 1000           # порог просмотренных строк для попадания в лог
log_throttle_queries_not_using_indexes = 60  # не чаще 1 раза в минуту

# -- Часовой пояс --
default_time_zone       = '+00:00'       # фиксированный UTC для избежания DST-ошибок

# -- Репликация (Modern GTID) --
server-id               = 101
log_bin                 = /var/log/mysql/mysql-bin.log
binlog_format           = ROW
gtid_mode               = ON
enforce_gtid_consistency = ON
binlog_expire_logs_seconds = 604800 # 7 дней
max_binlog_size         = 256M
log_bin_trust_function_creators = ON
```

**Валидация после применения:**
```bash
# 1. Проверка синтаксиса
sudo mysqld --validate-config

# 2. Применение
sudo systemctl restart mysql

# 3. Проверка статуса
sudo systemctl status mysql

# 4. Проверка ключевых параметров
mysql -e "SHOW VARIABLES LIKE 'innodb_buffer_pool_size';"
mysql -e "SHOW VARIABLES LIKE 'innodb_dedicated_server';"
mysql -e "SHOW VARIABLES LIKE 'max_connections';"
mysql -e "SHOW VARIABLES LIKE 'bind_address';"
mysql -e "SHOW VARIABLES LIKE 'character_set_server';"
mysql -e "SHOW VARIABLES LIKE 'gtid_mode';"
```

### 8. Resource groups: приоритеты и ограничение нагрузки (MySQL 8.0+)

Resource groups — механизм MySQL 8.0, который назначает потокам и отдельным
операторам приоритет планирования и привязку к CPU. Практический сценарий:
отчётность и аналитика на боевой базе получают низкий приоритет, и перестают
вытеснять OLTP-нагрузку.

Группы бывают двух типов, и тип фиксируется при создании:

- `SYSTEM` — для фоновых потоков (соответствуют background-потокам в
  `performance_schema.threads`), диапазон приоритета `-20..0`;
- `USER` — для пользовательских (foreground) потоков, диапазон `0..19`.

```sql
CREATE RESOURCE GROUP group_name
  TYPE = {SYSTEM | USER}
  [VCPU [=] vcpu_spec [, vcpu_spec] ...]
  [THREAD_PRIORITY [=] N]
  [ENABLE | DISABLE];
-- vcpu_spec: { N | M - N }
```

Общий диапазон приоритета — `-20` (высший) … `19` (низший), значение по
умолчанию `0`. Разделение диапазонов гарантирует, что пользовательские потоки
никогда не получат более высокий приоритет, чем системные. Если `VCPU` не
задан, группа не имеет привязки к CPU и может использовать все процессоры.

Стандартные группы `SYS_default` и `USR_default` удалить нельзя, их атрибуты
нельзя менять; новые потоки попадают в них.

```sql
-- Низкоприоритетная группа для отчётности: потоки 2 и 4
CREATE RESOURCE GROUP reporting
  TYPE = USER
  VCPU = 0-3
  THREAD_PRIORITY = 19;

-- Назначить конкретные потоки
SET RESOURCE GROUP reporting FOR 42, 43;

-- Назначить текущую сессию
SET RESOURCE GROUP reporting;
```

Для одного оператора группа задаётся optimizer hint — он указывается сразу
после начального ключевого слова:

```sql
SELECT /*+ RESOURCE_GROUP(reporting) */ COUNT(*)
FROM orders
WHERE customer_id = 17;
```

Отдельно от приоритета работает ограничение времени выполнения: hint
`MAX_EXECUTION_TIME(N)` допустим **только для `SELECT`** и задаёт лимит в
миллисекундах. Если опция отсутствует или `N = 0`, применяется системная
переменная `max_execution_time`.

Привилегии:

| Привилегия | Что разрешает |
| :--- | :--- |
| `RESOURCE_GROUP_ADMIN` | Создание, изменение и удаление групп, а также назначение потоков и операторов группам |
| `RESOURCE_GROUP_USER` | Только назначение потоков и операторов группам |

Что необходимо проверить до внедрения:

- **Resource groups недоступны при установленном thread pool plugin.**
- **На macOS механизм недоступен** — нет API привязки потока к CPU.
- На FreeBSD и Solaris приоритеты игнорируются с предупреждением
  `Attribute thread_priority is ignored (using default value)`.
- На Linux приоритеты работают только при наличии `CAP_SYS_NICE`; для
  systemd-сервиса это оформляется как `AmbientCapabilities=CAP_SYS_NICE` в
  drop-in unit-файле.
- На Windows диапазон `-20..19` отображается на пять уровней
  `THREAD_PRIORITY_*`.

Обратите внимание: приоритет потока не отменяет и не заменяет ограничение
времени выполнения. Для отчётности обычно нужны оба механизма.

Особенности хранения и репликации:

- определения групп хранятся в таблице словаря данных `resource_groups`
  (часть `mysql.ibd`), поэтому группы **переживают рестарт** сервера;
- `SET PERSIST` к resource groups **неприменим**: он сохраняет значения
  системных переменных, а операторов персистенции для групп нет;
- операторы resource groups и изменения таблицы `resource_groups` **не
  пишутся в бинарный лог и не реплицируются** — управление группами
  локально для каждого сервера.

Следствие для эксплуатации: на реплике группы нужно создавать отдельно, иначе
аналитика на реплике получит `SYS_default`/`USR_default` вместо приоритетной
группы. Это не ошибка репликации, а ожидаемое поведение.

Проверка состояния:

```sql
SELECT RESOURCE_GROUP_NAME,
       RESOURCE_GROUP_TYPE,
       RESOURCE_GROUP_ENABLED,
       VCPU_IDS,
       THREAD_PRIORITY
FROM INFORMATION_SCHEMA.RESOURCE_GROUPS;
```

```text
# → RESOURCE_GROUP_NAME | RESOURCE_GROUP_TYPE | RESOURCE_GROUP_ENABLED | VCPU_IDS | THREAD_PRIORITY
# → SYS_default         | SYSTEM              | ENABLED                | NULL     |              0
# → USR_default         | USER                | ENABLED                | NULL     |              0
# → reporting           | USER                | ENABLED                | 0-3      |             19
```

```sql
-- Потоки с назначенными группами (колонка NULL, если механизм не поддерживается)
SELECT THREAD_ID, TYPE, RESOURCE_GROUP, PROCESSLIST_USER
FROM performance_schema.threads
WHERE RESOURCE_GROUP IS NOT NULL
ORDER BY THREAD_ID
LIMIT 5;
```

```text
# → THREAD_ID | TYPE       | RESOURCE_GROUP | PROCESSLIST_USER
# →         1 | BACKGROUND | SYS_default    | NULL
# →        42 | FOREGROUND | reporting      | report_bot
# →        43 | FOREGROUND | reporting      | report_bot
```

Проверка эффекта: `SHOW ENGINE INNODB STATUS` показывает текущий приоритет
потока в разделе транзакций; в выводе соединения он виден как
`thread_priority`.

## Поиск и устранение неисправностей (Troubleshooting)

### Сервер не запускается после правки my.cnf
1.  **Проверьте логи:** `tail -n 100 /var/log/mysql/error.log`. Обычно там указана строка с ошибкой.
2.  **Типичная ошибка:** Опечатки в названиях (например, `innodb_buffer_pool_siz` вместо `size`).
3.  **Права доступа:** Файл `my.cnf` должен быть доступен для чтения пользователю `mysql`, но защищен от записи другими. Оптимально: `644`.
4.  **Валидация:** `mysqld --validate-config` перед рестартом.

### MySQL потребляет слишком много памяти (OOM Killer)
- **Причина:** Общая сумма `innodb_buffer_pool_size` + (кол-во соединений × `thread_stack` / `sort_buffer_size`) превышает RAM.
- **Решение:** Уменьшите Buffer Pool или `max_connections`. Используйте `innodb_dedicated_server = ON` для безопасного автопилота.
- **Диагностика:** `dmesg | grep -i kill` покажет процесс, убитый OOM Killer.

### Права на .my.cnf
Если клиент выдает предупреждение `World-writable config file is ignored`:
- **Решение:** `chmod 600 ~/.my.cnf`. MySQL игнорирует файлы конфигурации с небезопасными правами.

### Не применяются изменения из my.cnf
- **Причина:** Дублирование параметра в `mysqld-auto.cnf` (SET PERSIST) с более высоким приоритетом.
- **Решение:** `SELECT * FROM performance_schema.persisted_variables;` и `RESET PERSIST <parameter>;` если нужно.

### Ошибка `Unknown/unsupported storage engine: InnoDB`
- **Причина:** Поврежден `datadir` или неверные права.
- **Решение:** `chown -R mysql:mysql /var/lib/mysql`, проверка свободного места, переинициализация `mysqld --initialize-insecure`.

### Ошибка `Can't create/write to file` (errno: 28)
- **Причина:** Диск переполнен или `secure_file_priv` указывает на несуществующую директорию.
- **Решение:** `df -h`, проверка `secure_file_priv`, создание директории.

### Слишком медленные запросы без записи в slow log
- **Причина:** `long_query_time` слишком высокий или `slow_query_log` отключен.
- **Решение:** Установите `long_query_time = 1.0` и `slow_query_log = 1`, проверьте `log_output`.

### `skip-name-resolve` ломает GRANT
- **Причина:** В `mysql.user` используются доменные имена вместо IP.
- **Решение:** Пересоздайте пользователей с хостами в виде IP: `CREATE USER 'app'@'10.0.%' IDENTIFIED BY '...';`

### Утечка соединений (connections в статусе Sleeping)
- **Причина:** Приложение не закрывает соединения, `wait_timeout` слишком велик.
- **Решение:** `SHOW STATUS LIKE 'Threads_connected';`, `KILL <id>;`, уменьшение `wait_timeout` до 300–600.

### Время в логах не совпадает с прикладным
- **Причина:** `log_timestamps = SYSTEM` печатает метки в
  локальном часовом поясе ОС (по умолчанию — `UTC`); при переводе
  часов или в контейнере с `TZ=UTC` метки «прыгают».
- **Решение:** задать `log_timestamps = UTC` и коррелировать с метками приложения,
  пересчитав их в UTC. Проверка: `SHOW VARIABLES LIKE 'log_timestamps';`
- **Отдельно про данные:** `default_time_zone` влияет на `NOW()`, `TIMESTAMP` и
  `CONVERT_TZ()`, но не на метки логов. Если значения `TIMESTAMP` «сдвинулись» после
  перевода часов или переезда в другой `TZ` — проверять `default_time_zone`,
  `system_time_zone` и содержимое таблиц `mysql.time_zone_name`,
  `mysql.time_zone_transition`. Подробно — [Часовые пояса](./timezone.md).

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Версионность:** Храните конфигурацию в Git.
2.  **Модульность:** Используйте директиву `!includedir /etc/mysql/conf.d/` для разделения настроек (репликация, тюнинг, безопасность).
3.  **Сравнение:** Используйте утилиту `mysqltuner` для получения быстрых советов по оптимизации на основе статистики работы.
4.  **Файлы прав:** Все `*.cnf` должны иметь права `644` или `600`. Никогда не храните пароли в общем `my.cnf`.
5.  **Автоматизация:** Используйте Ansible/Puppet/Chef для распространения конфигурации. Никогда не редактируйте `my.cnf` вручную на боевых серверах.
6.  **Валидация:** После каждого изменения запускайте `mysqld --validate-config` и проверяйте `SHOW VARIABLES` на соответствие ожиданиям.
7.  **Capacity Planning:** Пересчитывайте конфигурацию при изменении объема данных в 2 раза или изменении аппаратной базы.
8.  **Резервное копирование:** Бэкапите `my.cnf`, `mysqld-auto.cnf` и `conf.d/` вместе с данными.

### Краевые случаи (Edge Cases)

- **Контейнеризация:** В Docker лимиты памяти (cgroups) могут не видеться `innodb_dedicated_server` корректно в старых версиях. В 8.4 это исправлено, но проверяйте результат через `SHOW VARIABLES`.
- **Case Sensitivity:** Названия параметров нечувствительны к регистру, но пути к файлам в Linux — чувствительны.
- **Миграция с Percona/MariaDB:** Некоторые параметры имеют разные имена или отсутствуют (например, `innodb_dedicated_server` доступен только в Oracle MySQL 8.0.15+).
- **Очень большие Buffer Pool (>64GB):** Увеличивайте `innodb_buffer_pool_chunk_size` до 1G для уменьшения времени старта.
- **Высоконагруженные системы (>5000 QPS):** Уменьшайте `innodb_adaptive_hash_index` до `OFF`, увеличивайте `innodb_read_io_threads` и `innodb_write_io_threads`.
- **Аварийное восстановление:** Если `mysqld-auto.cnf` поврежден, удалите его и перезапустите сервер — он начнет с параметров из `my.cnf`.

### См. также

- **[Обзор MySQL и форков](./overview.md)** — архитектура InnoDB и WAL.
- **[Безопасность MySQL](./security.md)** — детали настройки TDE, keyring и hardening.
- **[Механизмы оптимизатора MySQL](./optimizer_mechanisms.md)** — рекомендуемые параметры `optimizer_switch` для ICP, MRR и BKA.
- **[Репликация в MySQL: Обзор](./replication/overview.md)** — детали настройки GTID и бинарных логов.
- **[Мониторинг MySQL](./monitoring.md)** — использование Performance Schema и mysqld_exporter.
- **[Запуск MySQL в Docker](./docker.md)** — контейнеризация и лимиты cgroups.
- **[Безопасная установка СУБД](../installation_security.md)** — защита конфигурационных файлов.
- **[Анализ медленных запросов](./Operations/slow-query-analysis.md)** — разбор `slow query log`, `pt-query-digest`, пороги фиксации.
- **[Performance Schema и sys schema](./Operations/performance-schema-and-sys.md)** — наблюдаемость поверх конфигурации.
- **[SQL mode в MySQL](./sql-mode.md)** — `sql_mode`, строгий режим и его влияние на загрузку данных.
- **[Управление соединениями](./connection-management.md)** — `max_connections`, пулы, административный интерфейс.
- **[Бенчмаркинг СУБД](../Concepts/benchmarking.md)** — методика нагрузочного тестирования и capacity planning.
- **[sysbench](../Concepts/sysbench.md)** — OLTP-нагрузка для MySQL.
