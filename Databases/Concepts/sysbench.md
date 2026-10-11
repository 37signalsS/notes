# sysbench

**Актуально для:** sysbench 1.0.20

## Определения

**sysbench** — универсальный инструмент для бенчмаркинга и нагрузочного тестирования на базе LuaJIT. Поддерживает несколько встроенных профилей нагрузки для CPU, памяти, файловой системы, потоков, мьютексов и СУБД (MySQL, MariaDB, PostgreSQL). Поддерживает кастомные Lua-скрипты для создания произвольных сценариев. Использует Closed Loop модель (новый запрос отправляется только после получения ответа на предыдущий).

---

## Архитектура и принцип работы

sysbench состоит из ядра на C, интерпретатора LuaJIT и набора встроенных Lua-скриптов. Архитектура разделена на три фазы:

1. **Prepare** — подготовка данных: создание таблиц (для БД), генерация тестовых файлов (для fileio), выделение областей памяти (для memory).
2. **Run** — выполнение теста: создание N потоков, каждый из которых многократно выполняет функцию `event()` из Lua-скрипта. Результаты агрегируются в реальном времени.
3. **Cleanup** — удаление временных данных: DROP таблиц, удаление файлов.

Для БД-тестов sysbench по умолчанию использует встроенную схему `sbtest` с таблицами `sbtest1..N`, каждая из которых содержит строку с полями `id` (PK), `k` (индекс), `c` (случайная строка), `pad` (дополнение).

Поддерживаемые драйверы:
- `mysql` — MySQL/MariaDB (требует `libmysqlclient` или `mariadb-connector-c`)
- `pgsql` — PostgreSQL (требует `libpq`)

---

## Установка

### Пакетный менеджер

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y sysbench

# RHEL / CentOS / Rocky Linux
sudo dnf install -y sysbench

# macOS (Homebrew)
brew install sysbench
```

### Сборка из исходного кода

Для поддержки PostgreSQL или актуальной версии собирайте из исходников:

```bash
# Зависимости (Ubuntu/Debian)
sudo apt install -y build-essential cmake libmysqlclient-dev libpq-dev git

# Клонирование и сборка
git clone https://github.com/akopytov/sysbench.git
cd sysbench
./autogen.sh
./configure --with-pgsql --with-mysql
make -j$(nproc)
sudo make install
```

### Проверка версии

```bash
sysbench --version  # → sysbench 1.0.20
```

### Проверка драйверов

```bash
sysbench --db-driver=mysql --version
sysbench --db-driver=pgsql --version
```

---

## Доступные тесты

| Тест | Описание | Типичное применение |
| :--- | :--- | :--- |
| `cpu` | Вычисления с плавающей запятой (primes) | Проверка чистой CPU-производительности |
| `memory` | Последовательное чтение/запись памятью | Проверка пропускной способности RAM и NUMA |
| `fileio` | Случайное/последовательное чтение и запись на диск | Бенчмаркинг файловой системы и дисков |
| `threads` | Создание и управление потоками | Проверка планировщика потоков ОС |
| `mutex` | Конкуренция за POSIX-мьютекс | Проверка производительности мьютексов на высоком параллелизме |
| `oltp_read_write` | Смешанная нагрузка 80/20 (чтение/запись) | Основной OLTP-тест |
| `oltp_read_only` | Только чтение | Тестирование реплик |
| `oltp_write_only` | Только запись | Тестирование ingestion |
| `oltp_point_select` | Точечный SELECT по PK | Максимальный IOPS |
| `oltp_scan` | Сканирование диапазона | Тестирование range scan |
| `oltp_insert` | Вставка строк | Тестирование пропускной способности вставки |
| `oltp_delete` | Удаление строк | Тестирование удаления |
| `oltp_update_index` | Обновление с индексами | Тестирование contention |
| `oltp_update_non_index` | Обновление без индексов | Тестирование heap |
| `oltp_bulk_insert` | Пакетная вставка | LOAD DATA, COPY |

---

## Подготовка данных

### Подготовка для БД

```bash
# 10 таблиц по 1 млн строк (~4 ГБ на таблицу, ~40 ГБ всего)
sysbench oltp_read_write --mysql-db=test --tables=10 --table-size=1000000 prepare
# → Создает таблицы и заполняет их данными через bulk INSERT

# Проверка созданных данных:
mysql -e "SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='test';"
# → sbtest1 (1000000), sbtest2 (1000000), ...
```

### Подготовка для fileio

```bash
# Создание 16 файлов по 2 ГБ каждый (итого 32 ГБ)
sysbench fileio --file-total-size=32G --file-num=16 prepare
# → Создает /tmp/sysbench-fileio/*.dat
```

### Валидация подготовленных данных

```bash
# Проверка количества строк в sbtest
mysql -e "SELECT COUNT(*) FROM test.sbtest1;"  # → 1000000

# Проверка размера файлов fileio
ls -lh /tmp/sysbench-fileio/  # → 16 файлов по 2G
```

**Важно:** Размер данных (`--table-size`) должен превышать объем RAM сервера минимум в 2 раза. В противном случае вы тестируете только скорость RAM, а не реальную производительность СУБД под нагрузкой I/O.

---

## Запуск теста

### Базовый запуск OLTP

```bash
# 16 потоков, 5 минут, отчет каждые 10 секунд
sysbench oltp_read_write --threads=16 --time=300 --report-interval=10 run
```

### CPU-тест

```bash
# 4 потока, 30 секунд
sysbench cpu --threads=4 --time=30 run
# → events per second: 8420.12
```

### Memory-тест

```bash
# 4 потока, блоки 4K, общий объем 100 ГБ, 30 секунд
sysbench memory --threads=4 --memory-block-size=4K --memory-total-size=100G --time=30 run
# → MiB transferred: 204800.00 (6712.45 MiB/sec)
```

### File I/O-тест

```bash
# Случайное чтение/запись, 4 потока, 30 секунд
sysbench fileio --file-total-size=8G --file-test-mode=rndrw --threads=4 --time=30 --report-interval=10 run
# → IOPS: 125430.12
```

### Threads-тест

```bash
# Создание 1024 потоков, 30 секунд
sysbench threads --threads=1024 --time=30 run
# → events per second: 3400.50
```

### Mutex-тест

```bash
# Конкуренция за мьютекс, 64 потока, 30 секунд
sysbench mutex --threads=64 --time=30 run
# → events per second: 1250.75
```

---

## Ключевые параметры

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `--threads` | Количество виртуальных пользователей | Начинайте с 1, увеличивайте до Saturation Point |
| `--time` | Время теста в секундах | Минимум 300 (5 мин), для Steady State — 1800 (30 мин) |
| `--report-interval` | Интервал вывода промежуточных результатов | 10-60 секунд |
| `--mysql-db` / `--pgsql-db` | Имя базы данных | Обязательный параметр для БД-тестов |
| `--table-size` | Количество строк в каждой таблице | Должно превышать RAM в 2+ раза |
| `--tables` | Количество таблиц | По умолчанию 10 |
| `--db-driver` | Драйвер БД | `mysql` или `pgsql` |
| `--file-total-size` | Общий размер файлов для fileio | Минимум 8 ГБ |
| `--file-test-mode` | Режим работы с файлами | `seqwr`, `seqrewr`, `seqrd`, `rndrd`, `rndwr`, `rndrw` |
| `--memory-block-size` | Размер блока для memory-теста | 4K, 1M |
| `--memory-total-size` | Общий объем памяти для теста | 100G+ |
| `--events` | Максимальное количество событий | Альтернатива `--time` |
| `--rate` | Ограничение скорости (events/sec) | Для имитации фиксированной нагрузки |
| `--skip-triggers` | Пропустить триггеры в БД | Ускоряет prepare для больших наборов |

---

## Интерпретация вывода

```text
Running the test with following options:
Number of threads: 16

Final results:
    transactions:                        234567 (7819.56 per sec.)
    queries:                             3753072 (125112.89 per sec.)
    ignored errors:                      0      (0.00 per sec.)
    reconnects:                          0      (0.00 per sec.)

General statistics:
    total time:                          30.0005s
    total number of events:              234567

Latency (ms):
        min:                                    0.82
        avg:                                    2.04
        max:                                  156.73
        95th percentile:                        3.21   <- КЛЮЧЕВАЯ МЕТРИКА
        sum:                               478532.10

Threads fairness:
    events (avg/stddev):           14660.4375/142.67
    execution time (avg/stddev):   29.9083/0.08
```

### CPU/Memory/FileIO вывод

```text
CPU test:
    events per second: 8420.12

Memory test:
    MiB transferred: 204800.00 (6712.45 MiB/sec)

FileIO test:
    IOPS: 125430.12
    Latency (ms):
        min:    0.02
        avg:    0.32
        max:    12.45
        95th percentile: 0.85
```

**На что смотреть:**
- **`transactions (per sec.)`** — итоговый Throughput (TPS). Сравнивайте с baseline.
- **`queries (per sec.)`** — суммарный QPS. Для `oltp_read_write` TPS × 13 = QPS (1 транзакция = 13 запросов).
- **`95th percentile`** — хвостовая задержка. Для OLTP целевое значение обычно < 5-10 мс.
- **`max`** — максимальная задержка. Если на порядки больше `avg`, возможны всплески (spikes) из-за Checkpoint или блокировок.
- **`reconnects`** — если > 0, означает потерю соединений (исчерпан `max_connections` или `wait_timeout`).
- **`ignored errors`** — если > 0, означает ошибки транзакций (deadlock, timeout). Требует разбора.
- **`events per second`** — для не-БД тестов показывает пропускную способность (CPU primes/sec, memory MiB/sec, fileio IOPS).
- **`Threads fairness`** — показывает равномерность распределения нагрузки между потоками. Большое `stddev` означает contention.

---

## Кастомные Lua-скрипты

sysbench позволяет создавать собственные профили нагрузки через Lua-скрипты:

```lua
-- custom_oltp.lua — пример кастомного теста
-- Смешивает point select (70%), range select (20%) и update (10%)
function thread_init(thread_id)
    -- Инициализация подготовленных запросов
    stmt_point = db_prepare("SELECT c FROM sbtest1 WHERE id = ?")
    stmt_range = db_prepare("SELECT c FROM sbtest1 WHERE id BETWEEN ? AND ?")
    stmt_update = db_prepare("UPDATE sbtest1 SET k = k + 1 WHERE id = ?")
end

function event(thread_id)
    local id = sysbench.rand.uniform(1, sysbench.opt.table_size)
    if sysbench.rand.uniform(0, 100) < 70 then
        db_execute(stmt_point, id)
    elseif sysbench.rand.uniform(0, 100) < 67 then
        db_execute(stmt_range, id, id + 99)
    else
        db_execute(stmt_update, id)
    end
end
```

```bash
# Запуск кастомного теста:
sysbench /path/to/custom_oltp.lua --mysql-db=test --table-size=1000000 \
    --threads=16 --time=300 run
```

### Доступные Lua-функции

| Функция | Описание |
| :--- | :--- |
| `db_prepare(sql)` | Подготовка SQL-запроса (prepared statement) |
| `db_execute(stmt, ...)` | Выполнение подготовленного запроса с параметрами |
| `db_query(sql)` | Выполнение произвольного SQL-запроса |
| `sysbench.rand.uniform(min, max)` | Генерация случайного числа в диапазоне |
| `sysbench.rand.gaussian(mean, stddev)` | Генерация случайного числа по нормальному распределению |
| `sysbench.opt.table_size` | Доступ к параметру `--table-size` |
| `sysbench.opt.threads` | Доступ к параметру `--threads` |

---

## Устранение неисправностей (Troubleshooting)

### Ошибка 1: Координационный пропуск (Coordinated Omission)

**Симптом:** При росте Latency TPS падает пропорционально, p99 занижен.
**Причина:** Closed Loop модель. sysbench отправляет следующий запрос только после получения ответа, поэтому при увеличении Latency автоматически падает RPS.
**Диагностика:** Сравните `avg` и `max` Latency. Если `max` на порядки больше `avg` — вероятен Coordinated Omission.
**Решение:** Для точного измерения используйте инструменты с Open Loop моделью (k6 с `constant-arrival-rate`, wrk2).

### Ошибка 2: Тестирование RAM вместо дисков

**Симптом:** TPS очень высокий, Latency очень низкий, `iowait` = 0%.
**Причина:** Размер данных меньше объема RAM. Buffer Pool покрывает все данные.
**Диагностика:** `free -h` / `vmstat 1`. Если `buff/cache` > размер данных — данные в памяти.
**Решение:** Увеличьте `--table-size` так, чтобы данные превышали RAM в 2+ раза.

### Ошибка 3: Высокий stddev в Threads fairness

**Симптом:** `events (avg/stddev)` имеет большое значение `stddev`.
**Причина:** Конкуренция за общие ресурсы (CPU, мьютексы, блокировки в БД).
**Диагностика:** `htop` — смотрите `%CPU` по потокам. `perf top` — ищите hot spots.
**Решение:** Уменьшите `--threads`, найдите источник contention (Lock Contention, Latch Contention).

### Ошибка 4: Нулевые или низкие reconnects/ignored errors

**Симптом:** `reconnects` или `ignored errors` > 0.
**Причина:** `reconnects` — потеря соединений (`max_connections` или `wait_timeout`). `ignored errors` — deadlock, timeout, дубликаты.
**Диагностика:** 
```sql
-- MySQL:
SHOW VARIABLES LIKE 'max_connections';
SHOW STATUS LIKE 'Threads_connected';
-- PostgreSQL:
SELECT count(*) FROM pg_stat_activity;
```
**Решение:** Увеличьте лимит соединений, настройте Connection Pooler (PgBouncer, ProxySQL).

### Ошибка 5: Падение производительности при масштабировании

**Симптом:** TPS перестает расти после добавления потоков, Latency растет.
**Причина:** Saturation Point — исчерпание CPU, диска или блокировки.
**Диагностика:** `iostat -xz 1`, `vmstat 1`, `perf top`.
**Решение:** Найдите узкое место (CPU — оптимизация запросов, Disk — NVMe/параметры I/O, Locks — уменьшение contention).

### Ошибка 6: Нестабильные результаты

**Симптом:** Повторные запуски дают разный TPS с отклонением > 10%.
**Причина:** Фоновые процессы (Checkpoint, autovacuum), плавание частоты CPU, кэширование.
**Диагностика:** `cat /proc/cpuinfo | grep "cpu MHz"`, `iostat -xz 1`.
**Решение:** Фиксируйте частоту CPU (`performance` governor), делайте warm-up, запускайте минимум 3 раза и берите медиану.

---

## Best Practices

1. **Изоляция нагрузчика:** Никогда не запускайте `sysbench` на том же сервере, где находится БД. Вы получите искаженные результаты из-за борьбы за CPU.
2. **Объем данных:** Размер тестовых данных (`--table-size`) ОБЯЗАН превышать объем оперативной памяти сервера минимум в 2 раза.
3. **Мониторинг ресурсов:** Во время теста всегда держите открытым `iostat -xz 1` и `vmstat 1`. Высокий `iowait` при низком TPS — явный признак медленных дисков.
4. **Прогрев (Warm-up):** Всегда выполняйте подготовку данных и warm-up перед тестом, чтобы загрузить индексы в Buffer Pool.
5. **Повторяемость:** Запускайте каждый тест минимум 3 раза и берите медиану. Стандартное отклонение не должно превышать 5% от среднего значения.
6. **Фиксация конфигурации:** Перед каждым тестом фиксируйте конфигурацию СУБД и версию sysbench. Это критично для воспроизводимости.
7. **Валидация дисков:** Перед тестированием СУБД проверьте диски через `fio` (см. [fio.md](../../Linux/Diagnostics/Filesystem/fio.md)).
8. **Постепенная нагрузка:** Используйте методологию ramp-up (1, 4, 8, 16, 32, 64...) для нахождения Saturation Point.

---

## Дополнительная информация

### См. также

- **[Нагрузочное тестирование СУБД](./benchmarking.md)** — общая методология, подготовка среды, интерпретация результатов.
- **[Ключевые концепции производительности](./database_performance_concepts.md)** — теория TPS, Latency, USE-метод.
- **[pgbench](./pgbench.md)** — встроенный инструмент PostgreSQL для TPC-B нагрузки.
- **[HammerDB](./hammerdb.md)** — кросс-СУБД бенчмаркинг (TPC-C/TPC-H).
- **[mysqlslap](./mysqlslap.md)** — встроенный инструмент MySQL для быстрого smoke-теста.
- **[fio: Flexible I/O Tester](../../Linux/Diagnostics/Filesystem/fio.md)** — бенчмаркинг дисковой подсистемы.
