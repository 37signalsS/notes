# Нагрузочное тестирование и бенчмаркинг СУБД

**Актуально для:** SRE/DevOps/Sysadmin практики 2024–2026

## Определения

**Бенчмаркинг (Benchmarking)** — процесс измерения производительности аппаратного или программного обеспечения по эталонным тестам. В контексте СУБД бенчмаркинг позволяет количественно сравнить производительность разных конфигураций, версий или даже разных СУБД в одинаковых условиях.

**Нагрузочное тестирование (Load Testing)** — проверка способности СУБД обрабатывать ожидаемый объем транзакций при соблюдении заданных SLA по задержке (Latency).

**TPC-C** — отраслевой стандарт профиля нагрузки для OLTP-систем. Имитирует комплексную деятельность по обработке заказов: таблицы `warehouse`, `district`, `customer`, `order`, `order_line`, `stock`, `item`. Ключевая метрика — **TPC-C tpmC** (transactions per minute, модель C). Один склад (Warehouse) генерирует фиксированный объем нагрузки; соотношение CPU:Warehouses определяет степень блокировок.

**TPC-H** — отраслевой стандарт для OLAP-систем. Состоит из 22 аналитических запросов (aggregation, join, subquery) к набору данных сгенерированных таблиц (`lineitem`, `orders`, `part`, `supplier` и др.). Метрика — **QphH@size** (queries per hour). Scale Factor определяет размер данных: SF=1 соответствует примерно 1 ГБ несжатых данных.

**TPC-DS** — расширенная версия TPC-H для аналитики нового поколения. Включает 99 запросов с подзапросами, CTE и оконными функциями. Более реалистично имитирует поведение реальных DSS (Decision Support System) нагрузок.

**Tail Latency (Хвостовая задержка)** — задержка на высоких перцентилях (p95, p99, p99.9). В SRE-практике среднее значение считается "лживой метрикой", так как скрывает проблемы 1% пользователей, которые могут видеть задержки в 10–100 раз выше средних. Подробнее о перцентилях и физике задержек — в [Ключевые концепции производительности баз данных](./database_performance_concepts.md).

**Coordinated Omission (Координированное упущение)** — методологическая ошибка бенчмаркинга, при которой инструмент пропускает (или откладывает) запросы во время периодов высокой задержки, тем самым занижая измеренные перцентили. Пример: если инструмент отправляет запрос каждые 10 мс, а система задерживает ответ на 500 мс, инструмент "пропустит" около 50 запросов, которые в реальности были бы в очереди. Решение — использование инструментов с поддержкой **constant-arrival-rate** (k6, wrk2) вместо **closed-loop** (ab, wrk).

**Closed Loop (Закрытый цикл)** — модель нагрузки, при которой новый запрос отправляется только после получения ответа на предыдущий. Количество активных запросов ограничено числом виртуальных пользователей. Максимальный Throughput определяется как `RPS = Concurrent Users / Avg Latency`. Проблема: при росте Latency автоматически падает RPS, что маскирует реальную пропускную способность.

**Open Loop (Открытый цикл / Arrival Rate)** — модель нагрузки, при которой запросы генерируются с заданной частотой независимо от времени ответа системы. Позволяет точно измерять реальную пропускную способность и выявлять Coordinated Omission. Стандарт для профессионального бенчмаркинга в 2026 году.

**Saturation Point (Точка насыщения)** — точка на кривой производительности, где TPS перестает расти, а Latency начинает расти экспоненциально. Определяет максимальную рабочую нагрузку СУБД в данной конфигурации.

**Connection Pool (Пул соединений)** — кэш готовых соединений к СУБД, используемый приложениями для снижения накладных расходов на установку сессии. При исчерпании пула запросы начинают ожидать в очереди, что искусственно завышает Latency без перегрузки самой СУБД.

## Основные принципы

Бенчмаркинг СУБД — это не просто запуск инструмента и сравнение цифр. Чтобы результат был применим к production, нужно понять, **что именно вы измеряете** и **почему результат может отличаться** от реальной нагрузки.

### Цель бенчмаркинга

Измерить реальную пропускную способность и задержку конкретной конфигурации (железо + ОС + СУБД + схема данных) под контролируемой нагрузкой. Результат используется для:
- Валидации изменений конфигурации перед продом.
- Определения точки насыщения (Saturation Point) для capacity planning.
- Выявления регрессий при обновлении версий СУБД.
- Диагностики узких мест перед оптимизацией запросов.

### Почему бенчмаркинг сложен

Производительность СУБД зависит от четырех слоев, и проблема в любом из них искажает результат:

1. **Аппаратное обеспечение.** CPU (частота ядер, NUMA), RAM (объем, Huge Pages), Диски (IOPS, latency, очередь). Методология проверки дисков — в [fio: Flexible I/O Tester](../../Linux/Diagnostics/Filesystem/fio.md).
2. **Операционная система.** Планировщик CPU, Page Cache, `fsync`, лимиты открытых файлов, сетевой стек. Неправильный `vm.swappiness` или отключенный `O_DIRECT` могут исказить результат в разы.
3. **СУБД.** Настройки Buffer Pool, WAL, Checkpoint, Vacuum, Connection Limit. Default-конфигурация почти всегда неоптимальна для производительности.
4. **Схема данных и нагрузка.** Индексы, статистика, selectivity запросов, транзакционный профиль (read/write ratio, HOT vs COLD).

### Open Loop vs Closed Loop: почему это важно

На большинстве production-систем нагрузка не зависит от того, как быстро СУБД отвечает. Пользователи не ждут ответа перед следующим кликом; запросы приходят с постоянной частотой (например, 1000 RPS). Поэтому для честного измерения нужна **Open Loop** модель:

- **Closed Loop** (`sysbench`, `pgbench`, `HammerDB`, `mysqlslap` по умолчанию) удобна для относительных сравнений, но дает заниженный p99 и не выявляет Coordinated Omission.
- **Open Loop** (`k6` с `constant-arrival-rate`, `wrk2` с `-R`, `ghz` для gRPC) — единственно корректный способ измерить реальную пропускную способность и высокие перцентили.

Практический совет: используйте Closed Loop для быстрого relative-теста между конфигурациями, но для финальной валидации перед продом и определения Saturation Point применяйте Open Loop.

### Физика памяти и NUMA

Современные многопроцессорные серверы имеют архитектуру NUMA (Non-Uniform Memory Access). Если процесс СУБД работает на одном socket, а Buffer Pool выделен в памяти другого, каждая операция с памятью становится на 30–100% медленнее.

Перед бенчмаркингом проверьте:
```bash
# Распределение процессов по NUMA-узлам
numactl --hardware
ps -eo pid,psr,comm | grep -E "postgres|mysqld"
```

Для тяжёлых Buffer Pool настройте **Huge Pages** (2 МБ вместо 4 КБ). Это снижает нагрузку на TLB (Translation Lookaside Buffer) и экономит до 10–15% CPU на операциях с памятью. Проверка: `grep Huge /proc/meminfo`.

### Важность изоляции

Нагрузчик и СУБД должны работать на **разных физических ядрах** или, как минимум, в разных ВМ на одном хосте. Если нагрузчик и СУБД делят CPU кэш и частоту, вы измеряете не СУБД, а конкуренцию за ресурсы.

Для строгой изоляции используйте `cset shield` (Linux):
```bash
# Создать набор ядер для СУБД (например, 0–7)
cset shield --cpu 0-7 --kthread on
# Запустить СУБД в изолированном наборе
cset shield --exec -- systemctl start postgresql
# Запустить нагрузчик в остальных ядрах (8–31)
cset shield --exec -- sysbench ...
```

### Данные против кэша

Buffer Pool и Page Cache — единственные причины, по которым бенчмаркинг может показывать завышенную производительность. Если размер базы данных меньше объема RAM, все данные читаются из памяти, и вы тестируете только скорость RAM, а не дисковой подсистемы или логику СУБД.

Правило: **данные должны превышать RAM минимум в 2 раза**. Для OLAP-нагрузок с большими сканированиями коэффициент должен быть 3–5x.

## Инструменты бенчмаркинга

Детальные руководства по каждому инструменту — в отдельных файлах:

| Инструмент | СУБД / Протокол | Профиль | Модель | Файл |
| :--- | :--- | :--- | :--- | :--- |
| **sysbench** | MySQL, MariaDB, PostgreSQL | OLTP (read/write, point select, scan) | Closed Loop | [sysbench.md](./sysbench.md) |
| **pgbench** | PostgreSQL | TPC-B (SELECT/UPDATE/INSERT) | Closed Loop | [pgbench.md](./pgbench.md) |
| **HammerDB** | SQL Server, Oracle, MySQL, PostgreSQL | TPC-C, TPC-H | Closed Loop | [hammerdb.md](./hammerdb.md) |
| **mysqlslap** | MySQL | Автогенерация / пользовательские запросы | Closed Loop | [mysqlslap.md](./mysqlslap.md) |
| **k6** | Любая (через HTTP/gRPC) | Произвольный (Performance-as-Code) | Open Loop | См. [методология тестирования](../../Testing/performance_testing_methodology.md) |
| **wrk2** | HTTP/gRPC | Произвольный | Open Loop | См. [методология тестирования](../../Testing/performance_testing_methodology.md) |
| **ghz** | gRPC | Произвольный | Open Loop | [gRPC: Обзор](../../Networking/ServicesAndTools/grpc_overview.md) |
| **redis-benchmark** | Redis / Memcached | Key-value, pipelining | Closed Loop | [Redis: Обзор и эксплуатация](../../Databases/redis_overview.md) |
| **memtier_benchmark** | Redis / Memcached | Key-value, skew-распределение | Open Loop | [Redis: Обзор и эксплуатация](../../Databases/redis_overview.md) |
| **ClickBench** | ClickHouse | OLAP (TPC-H-like, пользовательские аналитические запросы) | Closed Loop | [ClickHouse: Обзор и эксплуатация](../../Databases/ClickHouse/clickhouse.md) |

## Предварительные требования

### Системные требования

| Параметр | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **CPU нагрузчика** | 2 ядра | 4+ ядер (изолированный сервер) |
| **RAM нагрузчика** | 4 ГБ | 8+ ГБ (для large `--table-size`) |
| **Диск БД** | SSD (SATA) | NVMe Gen4+ (для OLTP) |
| **RAM БД** | 8 ГБ | 32+ ГБ (Buffer Pool должен быть меньше RAM) |
| **Сеть** | 1 Гбит | 10 Гбит (для удаленных нагрузчиков) |
| **ОС** | Linux 4.x+ | Linux 5.x+ (для io_uring, PSI) |

### Сетевые лимиты ОС

Для нагрузки с большим числом соединений увеличьте лимиты до значений, превышающих планируемый `max_connections` СУБД минимум в 2 раза:

```bash
# Максимальное число открытых файлов
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf

# Очередь входящих соединений
sysctl -w net.core.somaxconn=4096
sysctl -w net.ipv4.tcp_tw_reuse=1

# Максимальное число файлов в системе
sysctl -w fs.file-max=2097152
```

### CPU и NUMA

```bash
# Фиксация частоты CPU (предотвращает throttle)
for i in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > $i
done

# Проверка топологии NUMA
numactl --hardware

# Опционально: запуск СУБД в изолированных ядрах
cset shield --cpu 0-7 --kthread on
```

## Подготовка среды

Правильный тест должен длиться достаточно долго, чтобы активировались фоновые процессы БД (Checkpoint, Vacuum, Log Flush). Перед запуском бенчмаркинга необходимо подготовить среду.

### 1. Валидация дисковой подсистемы (fio)

Перед тестированием СУБД убедитесь, что диски соответствуют ожидаемым характеристикам. Подробности работы с `fio` — в [отдельном файле](../../Linux/Diagnostics/Filesystem/fio.md).

```bash
# Тест случайного чтения 4K (имитация работы с индексами OLTP)
fio --name=randread_oltp --ioengine=libaio --iodepth=64 --rw=randread \
    --bs=4k --direct=1 --size=4G --numjobs=4 --runtime=60 --group_reporting
# → Ожидаемый результат для NVMe Gen4: IOPS > 800k

# Тест смешанной нагрузки 70/30 (имитация OLTP read/write)
fio --name=oltp_mix --ioengine=libaio --iodepth=32 --rw=randrw --rwmixread=70 \
    --bs=8k --direct=1 --size=8G --numjobs=4 --runtime=120 --group_reporting
# → Ожидаемый результат: IOPS > 200k, lat_p99 < 200 мкс

# Тест последовательной записи (имитация WAL / checkpoint)
fio --name=seq_write --ioengine=libaio --rw=write --bs=64k --direct=1 \
    --size=4G --numjobs=1 --runtime=30 --group_reporting
# → Ожидаемый результат для NVMe: BW > 3000 МБ/с
```

Если результаты `fio` значительно ниже заявленных характеристик диска — проблема в драйверах, контроллере или конфигурации ОС, а не в СУБД.

### 2. Подготовка данных

Данные должны **обязательно** превышать объем RAM сервера минимум в 2 раза. В противном случае вы тестируете только скорость RAM, а не реальную производительность СУБД под нагрузкой I/O.

```bash
# Определение объема RAM сервера
free -h | awk '/^Mem:/{print $2}'  # → 64Gi

# Расчет: 64 ГБ RAM * 2 = 128 ГБ минимальный размер данных
# Для sysbench: --table-size=33554432 (32 млн строк * 10 таблиц ≈ 128 ГБ при ~400 байт/строка)
```

### 3. Конфигурация ОС и СУБД для бенчмаркинга

```bash
# Отключение page caches (предотвращает кэширование при O_DIRECT)
echo 3 > /proc/sys/vm/drop_caches

# Увеличение лимита открытых файлов
ulimit -n 65536

# PostgreSQL: отключение autovacuum во время теста (если нужно изолировать влияние)
# Но для Steady State оставьте включенным, чтобы увидеть реальное влияние фоновых процессов

# MySQL: фиксация innodb_flush_log_at_trx_commit=1 для честного теста ACID
# В конфиге my.cnf перед тестом:
# innodb_flush_log_at_trx_commit = 1
# sync_binlog = 1
```

### 4. Прогрев (Warm-up)

```bash
# Прогрев Buffer Pool: полное сканирование всех таблиц
# PostgreSQL:
psql -d mydatabase -c "SELECT pg_prewarm(c.relname::regclass::text) FROM pg_class c WHERE c.relkind = 'r';"

# MySQL:
mysql -e "SELECT COUNT(*) FROM table1; SELECT COUNT(*) FROM table2; ..." mydatabase

# Альтернатива: выполнение запросов с полным сканированием индексов
# PostgreSQL:
psql -d mydatabase -c "REINDEX DATABASE mydatabase;"
# MySQL:
mysql -e "ANALYZE TABLE table1; ANALYZE TABLE table2; ..." mydatabase
```

### 5. Мониторинг во время теста

Откройте в отдельных терминалах (или собирайте в Prometheus/Grafana):

```bash
# Терминал 1: CPU и процессы
htop

# Терминал 2: Детальная статистика дисков (обновление каждую секунду)
iostat -xz 1

# Терминал 3: Сетевая статистика
sar -n DEV 1

# Терминал 4: Метрики СУБД
# PostgreSQL:
psql -d mydatabase -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"
# MySQL:
mysql -e "SHOW PROCESSLIST; SHOW ENGINE INNODB STATUS\G"

# Терминал 5 (опционально): Pressure Stall Information (Linux 5.x+)
watch -n 1 cat /proc/pressure/memory
watch -n 1 cat /proc/pressure/cpu
```

## Методология SRE: 4 этапа тестирования

### Этап 1: Baseline (Эталон)

Однопоточный тест для определения минимально возможной задержки в текущей конфигурации. Результат этого этапа — нижняя граница Latency, к которой система будет стремиться при идеальных условиях.

```bash
# sysbench: 1 поток, 60 секунд
sysbench oltp_read_write --threads=1 --time=60 --report-interval=10 run

# pgbench: 1 клиент
pgbench -c 1 -j 1 -T 60 mydatabase
```

**Важно:** Зафиксируйте результат. Он будет использоваться как baseline для сравнения.

### Этап 2: Ramp-up (Разгон)

Поэтапное увеличение количества виртуальных пользователей (1, 4, 8, 16, 32, 64, 128...). На каждом шаге выполняйте тест в течение 2–3 минут. Цель — найти точку перегиба кривой производительности.

```bash
# Серия тестов с нарастающей нагрузкой
for threads in 1 4 8 16 32 64 128; do
    echo "=== Threads: $threads ==="
    sysbench oltp_read_write --threads=$threads --time=180 --report-interval=30 run \
        | grep -E "transactions:|queries:|p95|95th"
done
```

### Этап 3: Steady State (Стабильное состояние)

Удержание пиковой нагрузки (определенной на этапе Ramp-up) в течение 15–30 минут. Минимальная длительность — 15 минут для выявления проблем с Checkpoint, Vacuum и Log Flush.

```bash
# sysbench: стабильное состояние 30 минут
sysbench oltp_read_write --threads=32 --time=1800 --report-interval=60 run

# pgbench: стабильное состояние 30 минут
pgbench -c 32 -j 8 -T 1800 mydatabase
```

*Важно:* Не фиксируйте результаты в первые 5 минут ("холодный старт"), пока Buffer Pool не прогрет и не стабилизировались фоновые процессы.

### Этап 4: Analysis (Анализ)

Построение графика `Throughput (TPS)` vs `Latency (p95)` на основе данных всех этапов. На графике ищите **Saturation Point (Точку насыщения)** — точку, где TPS перестает расти, а Latency начинает расти экспоненциально.

```
Пример данных для построения графика:

Threads | TPS      | Latency p95 (ms)
--------|----------|------------------
1       | 1,200    | 0.8
4       | 4,500    | 0.9
8       | 8,200    | 1.1
16      | 14,800   | 1.5
32      | 22,100   | 2.8     <- начало роста Latency
64      | 23,500   | 8.5     <- Saturation Point
128     | 22,800   | 45.2    <- Exhaustion
```

## Capacity Planning на основе бенчмаркинга

Результаты бенчмаркинга — основа для capacity planning. Используйте их для расчета параметров инфраструктуры.

### Формулы

**1. Пиковая нагрузка (Peak Load):**
```
Peak RPS = Average RPS × Burst Factor (обычно 1.5–3.0)
```

**2. Требуемый TPS с запасом прочности:**
```
Required TPS = Peak RPS × Safety Margin (обычно 1.2–1.5)
```

**3. Размер Connection Pool:**
```
Pool Size = (Core Count × 2) + Effective Spindle Count
```
Для PostgreSQL с PgBouncer в режиме transaction pooling:
```
Pool Size = Core Count × 2
```
Для MySQL Thread Pool:
```
Threads = Core Count × (1 + (Average Latency ms / 10))
```

**4. Объем RAM для Buffer Pool:**
```
Buffer Pool = Total RAM × 0.25–0.4
```
Для PostgreSQL: `shared_buffers = RAM × 0.25`
Для MySQL: `innodb_buffer_pool_size = RAM × 0.6–0.75` (InnoDB эффективнее использует кэш ОС, поэтому доля выше)

**5. Дисковый запас:**
```
Required IOPS = Required TPS × (Read Ratio + Write Ratio × 2)
```
Коэффициент 2 для write возникает из-за WAL и случайного обновления страниц.

### Пример расчета

Дано:
- Average RPS = 500
- Burst Factor = 2.0
- Safety Margin = 1.3
- Сервер: 16 ядер, 64 ГБ RAM, NVMe (500k IOPS)

```
Peak RPS = 500 × 2.0 = 1000
Required TPS = 1000 × 1.3 = 1300
Pool Size (PostgreSQL) = (16 × 2) + 4 = 36
Buffer Pool (PostgreSQL) = 64 GB × 0.25 = 16 GB
Required IOPS = 1300 × (0.7 + 0.3 × 2) = 1300 × 1.3 = 1690 IOPS
```

NVMe с 500k IOPS покрывает нагрузку с запасом ~300x. Узкое место — CPU (если при 1300 TPS CPU > 70%, нужно больше ядер).

## Интерпретация результатов

| Паттерн | Признак | Рекомендация SRE |
| :--- | :--- | :--- |
| **Здоровое состояние** | TPS растет линейно, Latency стабилен. | Система имеет запас прочности. Зафиксируйте текущий TPS как baseline. |
| **Saturation (Насыщение)** | TPS — плато, Latency p95 растет. | Узкое место в CPU или блокировках (Lock Contention). Используйте `perf top` и `pg_stat_activity` для поиска горячих запросов. |
| **Exhaustion (Истощение)** | TPS падает, Latency растет экспоненциально. | Дисковая подсистема перегружена (I/O Wait 100%) или нехватка RAM (Swap/Thrashing). Проверьте `iostat -xz 1` и `vmstat 1`. |
| **Coordinated Omission** | При росте Latency TPS падает пропорционально. | Используйте инструменты с Open Loop моделью (k6, wrk2). Не используйте ab/wrk для бенчмаркинга СУБД. |
| **Periodic Spikes** | Latency резко возрастает каждые N минут. | Фоновый процесс: Checkpoint (каждые несколько минут), Vacuum, autovacuum. Проверьте настройки `checkpoint_timeout`, `checkpoint_completion_target`. |
| **Connection Storm** | TPS резко падает при старте теста. | Массовое подключение клиентов. Используйте Connection Pooler (PgBouncer) или увеличьте `max_connections` с предварительным прогревом. |
| **Regression vs Baseline** | TPS ниже baseline на >5%. | Сравните `EXPLAIN ANALYZE` планы запросов, проверьте свежесть статистики (`ANALYZE`), наличие Bloat. |

## Типичные ошибки и устранение неисправностей

### Ошибка 1: Тестирование RAM вместо дисков

**Симптом:** TPS очень высокий, Latency очень низкий, `iowait` = 0%.
**Причина:** Размер данных меньше объема RAM. Buffer Pool покрывает все данные.
**Решение:** Увеличьте `--table-size` так, чтобы данные превышали RAM в 2+ раза.

### Ошибка 2: Запуск нагрузчика на сервере БД

**Симптом:** TPS не растет при увеличении потоков, высокий `sys` CPU.
**Причина:** Конкуренция за CPU между СУБД и инструментом бенчмаркинга.
**Решение:** Выделите отдельный сервер-нагрузчик. Минимальное расстояние — отдельная ВМ на том же физическом сервере.

### Ошибка 3: Неправильный прогрев

**Симптом:** Первые 5–10 минут теста показывают растущий TPS.
**Причина:** Buffer Pool холодный, данные читаются с диска.
**Решение:** Всегда выполняйте прогрев перед тестом (см. раздел "Подготовка среды").

### Ошибка 4: Малое время теста

**Симптом:** Результаты не повторяются, высокая дисперсия.
**Причина:** Фоновые процессы (Checkpoint, autovacuum) не успевают активироваться.
**Решение:** Минимальное время теста — 15 минут. Для Steady State — 30 минут.

### Ошибка 5: Использование default конфигурации СУБД

**Симптом:** Производительность значительно ниже ожиданий.
**Причина:** дефолтные настройки оптимизированы для безопасности, а не для производительности.
**Решение:** Настройте `shared_buffers`, `effective_cache_size`, `work_mem` (PostgreSQL), `innodb_buffer_pool_size`, `innodb_redo_log_capacity` (MySQL) перед тестом.

### Ошибка 6: Coordinated Omission при использовании ab/wrk

**Симптом:** p99 Latency занижена, TPS выглядит стабильной, но реальные пользователи видят задержки.
**Причина:** Closed Loop модель: при росте Latency автоматически падает RPS.
**Решение:** Используйте k6 с `constant-arrival-rate` или wrk2 с `-R` (constant request rate).

### Ошибка 7: Игнорирование NUMA

**Симптом:** Производительность неожиданно низкая при большом объеме RAM и быстрых дисках.
**Причина:** Процесс СУБД работает в удаленном NUMA-узле от памяти.
**Решение:** Используйте `numactl` или `cset shield` для привязки СУБД к локальному socket.

### Ошибка 8: Отсутствие Huge Pages

**Симптом:** Высокий `context switches` (`cs` в `vmstat`) и низкий TPS при большом Buffer Pool.
**Причина:** TLB misses из-за стандартных 4 КБ страниц.
**Решение:** Настройте Huge Pages 2 МБ: `sysctl -w vm.nr_hugepages=XXXX`.

## SRE Best Practices (2026)

1. **Изоляция нагрузчика:** Никогда не запускайте `sysbench`, `pgbench` или `HammerDB` на том же сервере, где находится БД. Вы получите искаженные результаты из-за борьбы за CPU.
2. **Объем данных:** Размер тестовых данных (`--table-size`) ОБЯЗАН превышать объем оперативной памяти сервера минимум в 2 раза. В противном случае вы тестируете только скорость RAM, а не реальную производительность СУБД под нагрузкой I/O.
3. **Мониторинг ресурсов:** Во время теста всегда держите открытым `top`/`htop` или `iostat -xz 1`. Высокий `iowait` при низком TPS — явный признак медленных дисков или неверной настройки `innodb_io_capacity`.
4. **Прогрев (Warm-up):** Всегда выполняйте полное сканирование таблиц перед тестом, чтобы загрузить индексы в Buffer Pool.
5. **Повторяемость:** Запускайте каждый тест минимум 3 раза и берите медиану. Стандартное отклонение не должно превышать 5% от среднего значения.
6. **Запись конфигурации:** Перед каждым тестом фиксируйте конфигурацию СУБД (`SHOW VARIABLES` для MySQL, `SHOW ALL` для PostgreSQL) и версию ПО. Это критично для воспроизводимости результатов.
7. **Валидация после изменений:** После каждого изменения конфигурации перезапускайте Baseline для проверки корректности изменений.
8. **Профилирование запросов:** Для PostgreSQL включите `pg_stat_statements`; для MySQL — Performance Schema. Это покажет Top SQL запросы по времени выполнения.
9. **Open Loop для финальной валидации:** Используйте k6/wrk2/ghz для измерения реальных перцентилей перед деплоем в прод.
10. **Capacity Planning:** Используйте результаты бенчмаркинга для расчета Buffer Pool, Connection Pool и необходимого числа дисковых устройств.

## Особенности тестирования разных СУБД

| СУБД | Особенности бенчмаркинга | Ключевые параметры для настройки |
| :--- | :--- | :--- |
| **PostgreSQL** | Используйте pgbench + sysbench. Обязательно настройте `shared_buffers` и `work_mem`. Для точного измерения используйте `track_activities = on` и `pg_stat_statements`. | `shared_buffers`, `effective_cache_size`, `work_mem`, `max_connections`, `maintenance_work_mem` |
| **MySQL 8.x** | sysbench — основной инструмент. Включите `innodb_flush_log_at_trx_commit=1` и `sync_binlog=1` для честного теста. Используйте Performance Schema для Top SQL. | `innodb_buffer_pool_size`, `innodb_redo_log_capacity`, `innodb_io_capacity`, `innodb_flush_method` |
| **MariaDB 11.x** | Аналогичен MySQL, но имеет собственные оптимизации для аналитики (ColumnStore). | `innodb_buffer_pool_size`, `aria_group_commit`, `thread_cache_size` |
| **SQLite** | Только для встраиваемых сценариев. Используйте `sqlite3_analyzer` для анализа размера. | `journal_mode` (WAL), `synchronous`, `cache_size`, `locking_mode` |
| **ClickHouse** | Используйте ClickBench для OLAP-тестов. Не подходит для OLTP. Настройте `max_threads` под количество ядер. | `max_threads`, `max_memory_usage`, `max_bytes_before_external_group_by` |
| **CockroachDB** | Используйте встроенный `cockroach workload` для YCSB и TPC-C. Учитывайте геораспределение и репликацию. | `--max-sql-memory`, `--cache`, Raft consensus overhead |
| **TimescaleDB** | Построен на PostgreSQL, используйте `timescaledb-tune` для автоматической настройки. Тестируйте с chunk-стратегией, характерной для time-series данных. | `time_partitioning`, `compression`,continuous aggregates |
| **Redis / Memcached** | Используйте `redis-benchmark` для относительных тестов и `memtier_benchmark` для Open Loop. Учитывайте persistence (RDB/AOF). | `maxmemory`, `maxmemory-policy`, `save` / `appendfsync` (для влияния на write) |

## Дополнительная информация

### См. также

- **[Ключевые концепции производительности баз данных](./database_performance_concepts.md)** — теория Latency, Throughput, USE-метод, иерархия памяти, NUMA, Huge Pages.
- **[Диагностика дисковых узких мест](../db_disk_bottleneck_troubleshooting.md)** — глубокий анализ I/O.
- **[fio: Flexible I/O Tester](../../Linux/Diagnostics/Filesystem/fio.md)** — бенчмаркинг дисковой подсистемы перед тестированием СУБД.
- **[Обзор методологий тестирования](../../Testing/performance_testing_methodology.md)** — общие принципы Performance-as-Code и Quality Gates.
- **[Мониторинг PostgreSQL](../PostgreSQL/Operations/observability.md)** — `pg_stat_statements`, `pg_stat_activity`, регламентные задания.
- **[Настройка PgBouncer](../PostgreSQL/Operations/pgbouncer_setup.md)** — connection pooling,capacity planning и типичные ошибки.
