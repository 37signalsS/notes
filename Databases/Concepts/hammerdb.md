# HammerDB

**Актуально для:** HammerDB 4.x

## Определения

**HammerDB** — отраслевой стандарт для профессионального сравнения различных СУБД (SQL Server, Oracle, MySQL, PostgreSQL). Поддерживает профили TPC-C (OLTP) и TPC-H (OLAP). Позволяет выполнять распределенные тесты на нескольких узлах одновременно. Интерфейс построен на Tcl/Tk: есть GUI (`hammerdb`) и CLI (`hammerdbcli`).

**NOPM (New Orders Per Minute)** — ключевая метрика HammerDB для TPC-C. Позволяет сравнивать производительность разных движков (например, SQL Server vs PostgreSQL) в одинаковых бизнес-сценариях. Аналогична tpmC в официальном TPC-C, но без привязки к конкретным условиям теста.

**TPC-C (в контексте HammerDB)** — отраслевой стандарт профиля нагрузки для OLTP-систем. В схеме HammerDB используются 8 таблиц: `warehouse`, `district`, `customer`, `order`, `order_line`, `stock`, `item`, `history`. Количество warehouses определяет масштаб данных и уровень блокировок. Ключевая метрика — NOPM.

**TPC-H (в контексте HammerDB)** — отраслевой стандарт для OLAP-систем. Включает 22 аналитических запросов (агрегация, join, subquery) к набору таблиц (`lineitem`, `orders`, `part`, `supplier` и др.). Метрика — QphH@size (queries per hour). Scale Factor определяет размер данных: SF=1 соответствует примерно 1 ГБ несжатых данных.

**Virtual Users (VUs)** — виртуальные пользователи HammerDB, каждый из которых выполняет транзакции TPC-C в бесконечном цикле. Количество VUs определяет степень параллелизма и pressure на СУБД.

**Build Schema** — процесс создания схемы TPC-C/TPC-H и заполнения данными в HammerDB. Для TPC-C создаются 8 таблиц с указанным количеством warehouses; для TPC-H — набор таблиц с данными указанного Scale Factor.

---

## Архитектура и принцип работы

### TPC-C схема

HammerDB реализует стандартную схему TPC-C:

| Таблица | Содержание | Зависимости |
| :--- | :--- | :--- |
| `warehouse` | Справочник складов | Корневая таблица |
| `district` | Районы (10 на warehouse) | `warehouse` |
| `customer` | Клиенты | `district`, `warehouse` |
| `order` / `oorder` | Заказы | `customer`, `warehouse` |
| `order_line` | Позиции заказов | `order`, `item`, `stock` |
| `stock` | Остатки товаров | `warehouse`, `item` |
| `item` | Справочник товаров | — |
| `history` | История транзакций | `warehouse`, `customer`, `district` |

Каждая транзакция TPC-C в HammerDB содержит mix из 5 операций:
1. **NewOrder** (45%) — создание нового заказа.
2. **Payment** (43%) — обновление остатков и запись в историю.
3. **OrderStatus** (4%) — чтение последних заказов клиента.
4. **Delivery** (2%) — пакетное обновление статусов заказов.
5. **StockLevel** (1%) — анализ низких остатков.

Blocking возникает на уровне строк (`row-level locking`) при доступе к `warehouse`, `district`, `customer` и `order`. Чем больше warehouses, тем меньше probability конфликта — отсюда пропорция 5:1 к ядрам CPU.

### TPC-H схема

TPC-H использует 8 таблиц фактов и измерений (`part`, `supplier`, `partsupp`, `customer`, `orders`, `lineitem`, `nation`, `region`). Запросы mix: простые агрегации, многetable joins, оконные функции, subqueries. HammerDB генерирует данные через `dbgen`-подобный алгоритм и запускает 22 запроса последовательно или параллельно.

### Distributed-режим

HammerDB поддерживает распределенные тесты: несколько инстансов HammerDB могут одновременно нажимать на один endpoint БД. В этом случае каждый инстанс управляет своим набором VUs, а результаты агрегируются вручную или через `unloadresult`. Это позволяет превысить лимиты одного сервера-нагрузчика, но требует аккуратного учета общего числа warehouses и VUs, чтобы не превысить capacity целевой СУБД.

---

## Установка

```bash
# Linux — требует Tcl 8.6+
# Скачайте последнюю версию с GitHub Releases:
# https://github.com/HammerDB/HammerDB/releases
# Извлеките архив соответствующей вашей ОС
tar xzf HammerDB-*-Linux-x86-64-*.tar.gz

# Проверка Tcl:
tclsh <<< 'puts $tcl_version'  # → 8.6
```

### GUI и CLI

```bash
# GUI (Tk-based, требует дисплей или X11 forwarding)
./hammerdb

# CLI (для headless-серверов и автоматизации)
./hammerdbcli
```

### Зависимости

| Компонент | Версия | Примечание |
| :--- | :--- | :--- |
| Tcl/Tk | 8.6+ | Обязательно для GUI и CLI |
| GLIBC | 2.17+ | Для бинарных сборок OL7/OL8 |
| X11 / Wayland | Любая | Только для GUI; для headless используйте `xvfb-run` |

---

## Поддерживаемые СУБД

| СУБД | TPC-C | TPC-H | Примечания |
| :--- | :--- | :--- | :--- |
| **PostgreSQL** | Да | Да | Рекомендуется pgbench для TPC-B |
| **MySQL** | Да | Нет | sysbench более гибок для OLTP |
| **Oracle** | Да | Да | Требует лицензию |
| **SQL Server** | Да | Да | Требует лицензию |
| **MariaDB** | Да | Нет | Аналогичен MySQL |
| **IBM Db2** | Да | Да | Требует лицензию |

---

## Подготовка окружения и изоляция

### Общие требования

Перед запуском HammerDB убедитесь, что окружение соответствует рекомендациям из [Нагрузочное тестирование СУБД](./benchmarking.md). Ниже — HammerDB-специфичные дополнения.

### Отдельный хост для нагрузчика

HammerDB — клиентское приложение. Запускайте его на выделенном сервере, отдельном от целевой СУБД. Нагрузка HammerDB может быть существенной при 1000+ warehouses и множестве VUs:
- **CPU:** HammerDB тратит CPU на генерацию транзакций и прием результатов. При 160 VUs потребуется 4+ ядер.
- **RAM:** 8+ ГБ для хранения кэша результатов и временных файлов.
- **Сеть:** 10 Гбит при удаленном расположении нагрузчика; задержка <0.5 мс.

### Операционная система

```bash
# Фиксация частоты CPU (предотвращает throttle)
for i in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > $i
done

# Увеличение лимита открытых файлов
ulimit -n 65536

# Отключение NUMA balancing для Ryzen/EPYC (если целевая СУБД на том же хосте)
echo 0 > /proc/sys/kernel/numa_balancing
```

### Диски и расположение результатов

- **Целевая СУБД:** диски должны быть отделены от диска, где хранятся данные HammerDB (`unloadresult`).
- **Логи HammerDB:** направляйте в `/var/log/hammerdb/` или на отдельный диск, чтобы не забить partition корня.
- **Временные файлы:** убедитесь, что `/tmp` имеет достаточно места; при 1000+ warehouses схема может занимать десятки ГБ.

---

## Конфигурация TPC-C

### Пропорция Warehouses к CPU

Количество "складов" (Warehouses) определяет уровень блокировок в тесте. Рекомендуемая пропорция — **5:1 к количеству ядер CPU**:

| Ядра CPU | Warehouses | Ожидаемый NOPM |
| :--- | :--- | :--- |
| 4 | 20 | 20,000–50,000 |
| 8 | 40 | 50,000–150,000 |
| 16 | 80 | 150,000–400,000 |
| 32 | 160 | 400,000–1,000,000 |
| 64 | 320 | 1,000,000+ |

При меньшем количестве Warehouse наблюдается высокий Lock Contention, при большем — растет время подготовки данных.

### Параметры подключения

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `pg_service_pool` / `mysql_service_pool` | Количество соединений в пуле HammerDB | Должно совпадать с числом VUs; не превышать `max_connections` СУБД |
| `pg_host` / `mysql_host` | Hostname или IP целевой СУБД | Используйте IP, чтобы исключить DNS-задержку |
| `pg_port` / `mysql_port` | Порт СУБД | Стандартный или кастомный |
| `pg_user` / `mysql_user` | Пользователь БД | Создайте отдельного пользователя `dbench` с правами на схему |
| `pg_pass` / `mysql_pass` | Пароль | Храните в vault, не коммитьте в скрипты |
| `pg_dbase` / `mysql_dbase` | Имя базы данных | База должна быть создана до `buildschema` |

---

## Настройка СУБД для HammerDB

### PostgreSQL

```sql
-- Перед buildschema создайте базу и пользователя
CREATE DATABASE tpcc;
CREATE USER dbench WITH PASSWORD 'password123';
GRANT ALL PRIVILEGES ON DATABASE tpcc TO dbench;

-- Критические параметры для честного бенчмаркинга
ALTER SYSTEM SET shared_buffers = '25% of RAM';
ALTER SYSTEM SET work_mem = '64MB';
ALTER SYSTEM SET maintenance_work_mem = '512MB';
ALTER SYSTEM SET checkpoint_timeout = '60min';
ALTER SYSTEM SET max_wal_size = '16GB';
ALTER SYSTEM SET synchronous_commit = 'off';  -- Только для тестового стенда!
ALTER SYSTEM SET full_page_writes = 'off';    -- Только для тестового стенда!
ALTER SYSTEM SET random_page_cost = 1.0;      -- Для SSD/NVMe
ALTER SYSTEM SET effective_io_concurrency = 200;
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET max_prepared_transactions = 300;
```

> **Важно:** `synchronous_commit = off` и `full_page_writes = off` допустимы только на выделенном тестовом стенде. На production восстановление после сбоя может быть невозможно.

### MySQL / MariaDB

```sql
-- Перед buildschema
CREATE DATABASE tpcc;
CREATE USER 'dbench'@'%' IDENTIFIED BY 'password123';
GRANT ALL PRIVILEGES ON tpcc.* TO 'dbench'@'%';

-- Критические параметры
SET GLOBAL innodb_buffer_pool_size = 25% of RAM;
SET GLOBAL innodb_log_file_size = 4GB;
SET GLOBAL innodb_flush_log_at_trx_commit = 0;  -- Только для тестового стенда!
SET GLOBAL innodb_flush_method = O_DIRECT;
SET GLOBAL innodb_io_capacity = 20000;
SET GLOBAL innodb_io_capacity_max = 40000;
SET GLOBAL max_connections = 200;
```

> **Важно:** `innodb_flush_log_at_trx_commit = 0` допустим только на тестовом стенде. На production риск потери данных при сбое питания равен 1 секунде.

---

## Построение схемы и подготовка данных

### Стандартная инициализация

```bash
hammerdbcli << 'EOF'
dbset db PostgreSQL
setldbdict PostgreSQL 10.10.0
setdict tpcc

diset connection pg_host 192.168.1.100
diset connection pg_port 5432
diset connection pg_user dbench
diset connection pg_pass password123
diset connection pg_dbase tpcc
diset tpcc pg_count_ware 100

# Создание схемы и данных
buildschema
EOF
```

### Время подготовки

| Warehouses | Ориентировочное время | Дисковый объем |
| :--- | :--- | :--- |
| 100 | 10–30 минут | ~20 ГБ |
| 500 | 1–2 часа | ~100 ГБ |
| 1000 | 3–6 часов | ~200 ГБ |
| 2000 | 8–12 часов | ~400 ГБ |

Для ускорения используйте:
- `diset tpcc pg_parallel_build 8` — параллельная загрузка (если поддерживается версией).
- SSD/NVMe для целевой СУБД.
- Отдельный процесс `buildschema` без одновременного запуска других нагрузок.

### VACUUM и ANALYZE после buildschema

```bash
# PostgreSQL
psql -d tpcc -c "VACUUM ANALYZE;"

# MySQL
mysql -e "ANALYZE TABLE warehouse, district, customer, `order`, order_line, stock, item, history;" tpcc
```

Это убирает "холодный старт" на первом запуске теста, когда СУБД сканирует много мертвых tuples.

---

## Запуск теста

```bash
hammerdbcli << 'EOF'
dbset db PostgreSQL
setldbdict PostgreSQL 10.10.0
setdict tpcc

diset connection pg_host 192.168.1.100
diset connection pg_port 5432
diset connection pg_user dbench
diset connection pg_pass password123
diset connection pg_dbase tpcc
diset tpcc pg_count_ware 1000

# Настройка теста
diset tpcc pg_num_vu 64
diset tpcc pg_tpcc_time 1800

unloadresult /tmp/hammerdb_results
setcommandtimeout 180
vudestroy
vucreate vudestroy
runtimer 1800
vurun
EOF
```

### Параметры теста

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `pg_count_ware` / `mysql_count_ware` | Количество warehouses | Пропорция 5:1 к ядрам CPU |
| `pg_num_vu` / `mysql_num_vu` | Количество Virtual Users | Начинайте с 5× warehouses, увеличивайте до saturation |
| `pg_tpcc_time` / `mysql_tpcc_time` | Длительность теста в секундах | Минимум 900 (15 мин), предпочтительно 1800 (30 мин) |

---

## Валидация и повторяемость

### Прогрев

HammerDB не имеет встроенного прогрева Buffer Pool. После `buildschema` выполните:

```bash
# PostgreSQL
psql -d tpcc -c "SELECT pg_prewarm('warehouse'); SELECT pg_prewarm('district'); ..."

# Или полное сканирование
psql -d tpcc -c "SELECT COUNT(*) FROM warehouse; SELECT COUNT(*) FROM district; ..."
```

### Повторяемость

1. **Минимум 3 запуска** на каждой конфигурации. Берите медиану NOPM.
2. **Исключайте первые 5 минут** каждого теста из анализа — "холодный старт".
3. **Фиксируйте конфигурацию:** `postgresql.conf` / `my.cnf`, версия ПО, количество warehouses, количество VUs.
4. **Используйте одинаковые hardware/OS условия** для всех запусков в одном сравнении.

---

## Мониторинг во время теста

Откройте в отдельных терминалах или собирайте в Prometheus/Grafana:

```bash
# Терминал 1: CPU и процессы
htop

# Терминал 2: Детальная статистика дисков (обновление каждую секунду)
iostat -xz 1

# Терминал 3: Сетевая статистика
sar -n DEV 1

# Терминал 4: Метрики PostgreSQL
psql -d tpcc -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"
psql -d tpcc -c "SELECT * FROM pg_stat_bgwriter;"
psql -d tpcc -c "SELECT * FROM pg_stat_replication;"

# Терминал 5: Метрики MySQL
mysql -e "SHOW PROCESSLIST; SHOW ENGINE INNODB STATUS\G"
```

### Пороги алертов

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| `iowait` | >30% | Проверьте дисковую подсистему (`iostat -xz 1`) |
| `load average` | > количества ядер | CPU starvation, уменьшите VUs или warehouses |
| `pg_stat_bgwriter.buffers_checkpoint` | Растет быстрее `buffers_clean` | Чекпоинты слишком частые, увеличьте `checkpoint_timeout` |
| `pg_stat_replication.lag_bytes` | Растет постоянно | WAL-насыщение, проверьте archival и `wal_keep_size` |
| `SHOW ENGINE INNODB STATUS` — log waits | >0 | Увеличьте `innodb_log_file_size` или `innodb_log_buffer_size` |

---

## Интерпретация результатов

```text
VU Output:
1000,+,0,150000,2500,123.45,67.89,12.34
...
EOF

test result: 150000 NOPM achieved
```

**На что смотреть:**
- **NOPM** — основная метрика. Сравнивайте между разными конфигурациями.
- **Virtual Users** — количество активных виртуальных пользователей.
- **Latency** — среднее время ответа. Если растет при стабильном NOPM — приближаетесь к saturation.
- **Checkpoint** — частота сброса данных на диск. Влияет на Latency.
- **Rollback** — количество откаченных транзакций. Высокое значение указывает на deadlocks или resource starvation.

---

## Ключевые команды CLI

| Команда | Описание |
| :--- | :--- |
| `dbset db <DBMS>` | Выбор СУБД (PostgreSQL, MySQL, Oracle, etc.) |
| `setldbdict <DBMS> <version>` | Указание версии СУБД для корректного словаря |
| `setdict tpcc` | Режим TPC-C |
| `setdict tpc-h` | Режим TPC-H |
| `diset connection <param> <value>` | Настройка подключения |
| `diset tpcc <param> <value>` | Настройка TPC-C параметров |
| `buildschema` | Создание схемы и заполнение данными |
| `vudestroy` | Уничтожение существующих данных |
| `vucreate` | Создание виртуальных пользователей |
| `runtimer <seconds>` | Установка времени теста |
| `vurun` | Запуск теста |
| `unloadresult <path>` | Сохранение результатов |
| `setcommandtimeout <seconds>` | Таймаут командной строки |

---

## Поиск и устранение неисправностей

### Долгая подготовка схемы (buildschema > 2 часов)

**Симптомы:** `buildschema` работает дольше ожидаемого, CPU на сервере БД низкий.
**Причины:**
- Недостаточно I/O throughput на дисках СУБД.
- `maintenance_work_mem` слишком мал для создания индексов.
- WAL-архивация или репликация consuming bandwidth.
**Решение:** увеличьте `maintenance_work_mem`, отключите archival на время buildschema, используйте NVMe.

### Низкий NOPM при малом Lock Contention

**Симптомы:** NOPM значительно ниже ожидаемого приWarehouses << CPU cores.
**Причины:**
- `shared_buffers` слишком мал, происходит frequent eviction.
- `work_mem` недостаточен для sorts/hash joins в транзакциях.
- Checkpoint или autovacuum активны во время теста.
**Решение:** увеличьте `shared_buffers` до 25–30% RAM, отключите autovacuum на время теста, увеличьте `checkpoint_timeout`.

### Высокий initial connection time

**Симптом:** `initial connection time = 500+ мс`.
**Причины:**
- Отсутствует Connection Pooler (PgBouncer / ProxySQL).
- `max_connections` исчерпан.
- DNS-резолвинг при подключении по имени хоста.
**Решение:** используйте PgBouncer, подключение по IP, увеличьте `max_connections` или уменьшите количество VUs.

### Нестабильность результатов между запусками

**Симптомы:** NOPM колеблется более чем на 10% при одинаковых параметрах.
**Причины:**
- Checkpoint или autovacuum запустились во время теста.
- Частота CPU не зафиксирована (Turbo Boost / throttle).
- Данные не выровнены по pages (фрагментация после buildschema).
**Решение:** фиксируйте `scaling_governor = performance`, исключайте первые 5 минут, запускайте минимум 3 раза, выполните `VACUUM FULL` или `OPTIMIZE TABLE` между сериями.

### NOPM падает во время длительного теста

**Симптомы:** NOPM стабилен первые 10–15 минут, затем плавно падает.
**Причины:**
- WAL-архивация или репликация не успевает за генерацией WAL.
- Файловая система заполняется или hit inode limit.
- Bloat в таблицах `order` и `order_line` из-за отсутствия VACUUM.
**Решение:** увеличьте `max_wal_size`, отключите archival на время теста, мониторьте свободное место на диске.

---

## Ограничения

- **Сложность настройки:** CLI-интерфейс неинтуитивен, требуется время на изучение. GUI удобен для разведки, но не для автоматизации.
- **Долгая подготовка:** Генерация данных для 1000+ Warehouse занимает часы. Планируйте buildschema заранее.
- **Closed Loop модель:** Аналогично sysbench/pgbench, при росте Latency автоматически падает NOPM. Для Open Loop используйте внешние инструменты (k6, wrk2).
- **Ограниченные СУБД:** Поддерживает только основные коммерческие и open-source СУБД. Для niche-движков (ClickHouse, CockroachDB) используйте встроенные инструменты.
- **Высокие требования к ресурсам:** Тест на 1000+ Warehouse требует значительного объема RAM и CPU на стороне СУБД и нагрузчика.
- **GUI не для production:** HammerDB GUI удобен для разработки и разведки, но для production-автоматизации используйте `hammerdbcli` с шаблонами Tcl.
- **Нет native распределенного агента:** Distributed-режим требует ручной координации нескольких инстансов HammerDB и последующего объединения результатов.

---

## Best Practices

1.  **Никогда не тестируйте production без оговорок:** Используйте read-only реплику или выделенное окно обслуживания. Even read-only TPC-C создает нагрузку на CPU и диски.
2.  **Изоляция:** Запускайте HammerDB на отдельном хосте. Если это невозможно — используйте `taskset` и `nice` для изоляции CPU.
3.  **Объем данных:** Количество warehouses должно обеспечивать размер данных > 2× RAM сервера. Иначе вы тестируете кэш, а не дисковую подсистему.
4.  **Прогрев:** Всегда прогревайте Buffer Pool перед тестом. Исключайте первые 5 минут из анализа.
5.  **Повторяемость:** Запускайте минимум 3 раза, берите медиану. Длительность Steady State — минимум 30 минут.
6.  **Фиксация конфигурации:** Сохраняйте `postgresql.conf` / `my.cnf` и версию ПО перед каждым тестом. Восстанавливайте конфигурацию после завершения.
7.  **Мониторинг WAL:** Следите за `wal_bytes` в `pg_stat_database` и `sent_lsn`/`replay_lsn` на репликах. Длительный HammerDB-тест может вызвать Replica Lag.
8.  **Используйте шаблоны Tcl:** Храните сценарии в VCS, параметризируйте hosts/credentials через переменные окружения или vault. Не храните пароли в скриптах.

---

## Дополнительная информация

### См. также

- **[Нагрузочное тестирование СУБД](./benchmarking.md)** — общая методология, подготовка среды, интерпретация результатов.
- **[Ключевые концепции производительности](./database_performance_concepts.md)** — теория TPS, Latency, USE-метод.
- **[sysbench](./sysbench.md)** — кросс-СУБД бенчмаркинг (MySQL, PostgreSQL, MariaDB).
- **[pgbench](./pgbench.md)** — встроенный инструмент PostgreSQL для TPC-B нагрузки.
