# Нагрузочное тестирование MariaDB: sysbench и mariadb-slap

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS, sysbench 1.0.20+

## Определения

*   **sysbench** — модульный бенчмарк-кроссплатформенный инструмент. Для MariaDB используется `sysbench/oltp_*` набор: OLTP-нагрузка (read-only, read-write, write-only, point-select). Поддерживает драйвер `mysql` (совместим с MariaDB). Подробнее: **[sysbench (общие концепции)](../Concepts/sysbench.md)**.
*   **`mariadb-slap`** — встроенный в MariaDB инструмент нагрузочного тестирования (форк `mysqlslap`). Генерирует конкурентные запросы, измеряет latency. Удобен для быстрой проверки без подготовки данных.
*   **OLTP (Online Transaction Processing)** — нагрузка с короткими транзакциями (SELECT/INSERT/UPDATE/DELETE) — типичная для OLTP-систем.
*   **TPS (Transactions Per Second)** — число транзакций в секунду. Ключевая метрика OLTP-нагрузки.
*   **QPS (Queries Per Second)** — число запросов в секунду.
*   **Latency (p95, p99)** — перцентили времени ответа. p99 — 99% запросов быстрее этого значения. Критична для SLO.
*   **Working set** — объём данных, активно читаемых в память (горячий набор). Должен помещаться в `innodb_buffer_pool_size` для высокой произвительности.
*   **Coordinated Omission** — методологическая ошибка бенчмаркинга (см. [Бенчмаркинг СУБД](../Concepts/benchmarking.md)), при которой инструмент пропускает запросы во время пиковых задержек, тем самым занижая измеренные перцентили.
*   **Saturation Point** — точка на кривой производительности, где TPS перестаёт расти, а Latency начинает расти экспоненциально. Определяет максимальную нагрузку СУБД.

## Требования и предпосылки

Перед запуском тестов убедитесь, что выполнены предпосылки:

### Оборудование и ОС

- **CPU:** выделите выделенные ядра для СУБД и нагрузчика (см. [Бенчмаркинг СУБД](../Concepts/benchmarking.md) — почему изоляция важна). На сервере с NUMA используйте `numactl --hardware` и привязывайте `mariadbd` к одному узлу.
- **RAM:** `innodb_buffer_pool_size` должен быть 70–80% от доступной памяти, если working set помещается в память; иначе тестируйте с реалистичным ratio данных к буферу.
- **Диски:** используйте `fio` для проверки IOPS/latency диска перед тестом (см. [fio: Flexible I/O Tester](../../Linux/Diagnostics/Filesystem/fio.md)). Для write-intensive тестов — NVMe.
- **OS tuning:** отключите THP (`echo never > /sys/kernel/mm/transparent_hugepage/enabled`), установите `vm.swappiness=1`, проверьте `ulimit -n` ≥ 65535 (см. [Конфигурация MariaDB](./configuration.md)).

### Конфигурация MariaDB для тестирования

- **Performance Schema включён:** `performance_schema=ON` в `my.cnf` (MariaDB выключает его по умолчанию — см. [Мониторинг](./monitoring.md)). Без него недоступны метрики для анализа.
- **Логи выключены или перенаправлены:** временно увеличьте `long_query_time` до высокого значения и/или отключите `slow_query_log` и `general_log` на время теста, чтобы исключить overhead записи логов.
- **InnoDB sizing:** для теста, где working set > buffer pool, используйте `innodb_io_capacity=2000` и `innodb_flush_method = O_DIRECT`. См. [Управление памятью](./memory_management.md) и [InnoDB: долговечность](./innodb_durability_tuning.md).
- **Подключения:** `max_connections` должен превышать `--threads` теста.

### Пользователь и база данных для теста

```sql
-- Создать dedicated test environment
CREATE DATABASE sbtest;
CREATE USER 'sbtest'@'%' IDENTIFIED BY 'StrongTestPassword123!';
GRANT ALL PRIVILEGES ON sbtest.* TO 'sbtest'@'%';
FLUSH PRIVILEGES;
```

```bash
# Проверить подключение перед тестом
mariadb-admin -h 127.0.0.1 -u sbtest -pStrongTestPassword123! ping
# → mysqld is alive
```

### Изоляция тестовой среды

- **Staging** — отдельный сервер/ВМ с данными, репрезентативными по объёму и схеме.
- **Отключите фоновые задачи** — `event_scheduler`, плановые `ANALYZE TABLE`/`OPTIMIZE TABLE`, резервные копии.
- **Дождитесь прогрева** — запустите нагрузку 5–10 минут перед измерением (buffer pool, page cache).

## Базовые концепции

### sysbench vs mariadb-slap

| Характеристика | sysbench | mariadb-slap |
| :--- | :--- | :--- |
| **Назначение** | Профессиональный бенчмарк | Быстрая проверка |
| **Наборы** | oltp_read_only, oltp_read_write, oltp_write_only, oltp_point_select, oltp_update_index, oltp_update_non_index | произвольный SQL |
| **Подготовка данных** | встроенная (`--tables`, `--table-size`) | встроенная (`--create-schema`, `--number-of-queries`) |
| **Метрики** | TPS, QPS, latency (p95, p99), errors | latency, concurrency |
| **Драйвер** | `mysql` (MariaDB-совместим) | нативный |
| **Гибкость** | Lua-скрипты (кастомные нагрузки) | ограниченная |

**Выбор:** sysbench — для серьёзного нагрузочного тестирования и сравнения конфигураций; `mariadb-slap` — для быстрой проверки и smoke-тестов.

### Методология нагрузочного тестирования

1.  **Baseline:** замерьте текущую производительность до изменений.
2.  **Изолируйте переменные:** меняйте один параметр за раз.
3.  **Прогрев:** прогрейте buffer pool (запустите нагрузку 5-10 мин до замера).
4.  **Длительность:** замер ≥ 5-10 минут для стабильных метрик.
5.  **Мониторинг:** параллельно собирайте метрики (CPU, RAM, I/O, `Threads_running`, buffer pool).
6.  **Реалистичный working set:** размер данных ≥ buffer pool (иначе всё в кэше — нереалистично).

## Практические сценарии

### 1. Установка sysbench

```bash
# Debian/Ubuntu
sudo apt-get install sysbench

# RHEL/CentOS
sudo dnf install sysbench

# Проверка
sysbench --version
# → sysbench 1.0.20
```

### 2. Подготовка данных (sysbench)

```bash
# Подготовить 10 таблиц по 1M строк (≈ 10M строк, ~1-2 GB)
sysbench /usr/share/sysbench/oltp_read_write.lua \
  --mysql-host=127.0.0.1 \
  --mysql-port=3306 \
  --mysql-user=sbtest \
  --mysql-password=sbtest_password \
  --mysql-db=sbtest \
  --tables=10 \
  --table-size=1000000 \
  --db-driver=mysql \
  prepare

# Создать пользователя для тестов
mariadb -u root -p -e "
  CREATE DATABASE sbtest;
  CREATE USER 'sbtest'@'localhost' IDENTIFIED BY 'sbtest_password';
  GRANT ALL PRIVILEGES ON sbtest.* TO 'sbtest'@'localhost';
  FLUSH PRIVILEGES;"
```

### 3. Запуск нагрузки (sysbench)

```bash
# OLTP read-write: 64 потока, 10 минут
sysbench /usr/share/sysbench/oltp_read_write.lua \
  --mysql-host=127.0.0.1 \
  --mysql-port=3306 \
  --mysql-user=sbtest \
  --mysql-password=sbtest_password \
  --mysql-db=sbtest \
  --tables=10 \
  --table-size=1000000 \
  --threads=64 \
  --time=600 \
  --report-interval=10 \
  --db-driver=mysql \
  run

# Read-only
sysbench /usr/share/sysbench/oltp_read_only.lua ... run

# Point select (только PK-чтения)
sysbench /usr/share/sysbench/oltp_point_select.lua ... run

# Write-only
sysbench /usr/share/sysbench/oltp_write_only.lua ... run
```

**Интерпретация вывода:**
```
SQL statistics:
    queries performed:
        read:                            1234567
        write:                           345678
        other:                           123456
        total:                           1703601
    transactions:                        56789  (94.65 per sec.)
    queries:                             1703601 (2839.45 per sec.)
    ignored errors:                      0      (0.00 per sec.)
    reconnects:                          0      (0.00 per sec.)

General statistics:
    total time:                          600.0012s
    total number of events:              56789

Latency (ms):
         min:                                    1.23
         avg:                                    10.45
         max:                                   250.12
         95th percentile:                        25.34
         sum:                               593456.78

Threads fairness:
    events (avg/stddev):           887.3281/12.34
    execution time (avg/stddev):   9.2728/0.01
```

**Ключевые метрики:**
*   `transactions` (TPS) — пропускная способность.
*   `95th percentile` — latency p95.
*   `ignored errors` — должно быть 0.

### 4. mariadb-slap (быстрая проверка)

```bash
# Простой тест: 10 клиентов, 1000 запросов
mariadb-slap \
  --host=127.0.0.1 \
  --user=root \
  --password=StrongRootPassword \
  --concurrency=10 \
  --iterations=5 \
  --number-of-queries=1000 \
  --create-schema=test \
  --query="SELECT * FROM sbtest1 WHERE id = ?"

# С кастомным SQL-файлом
mariadb-slap \
  --host=127.0.0.1 \
  --user=root \
  --password=StrongRootPassword \
  --concurrency=50 \
  --iterations=3 \
  --query-file=queries.sql \
  --create-schema=test
```

**Вывод:**
```
Benchmark
        Average number of seconds to run all queries: 0.523 seconds
        Minimum number of seconds to run all queries: 0.512 seconds
        Maximum number of seconds to run all queries: 0.541 seconds
        Number of clients running queries: 10
        Average number of queries per client: 100
```

### 5. Кастомный Lua-скрипт (sysbench)

```lua
-- custom.lua
function thread_init()
  drv = sysbench.sql.driver()
  con = drv:connect()
end

function event()
  local rs = con:query("SELECT * FROM sbtest1 WHERE id = " ..
    sysbench.rand.default(1, 1000000))
  rs:free()
end

function thread_done()
  con:disconnect()
end
```

```bash
sysbench custom.lua \
  --mysql-host=127.0.0.1 \
  --mysql-user=sbtest \
  --mysql-password=sbtest_password \
  --mysql-db=sbtest \
  --threads=32 \
  --time=300 \
  --db-driver=mysql \
  run
```

### 6. Параллельный мониторинг во время теста

```bash
# В отдельном терминале
# CPU / RAM
vmstat 1

# I/O
iostat -x 1

# MariaDB метрики
watch -n 1 "mariadb -u root -p -e 'SHOW GLOBAL STATUS LIKE \"Threads_running\"; SHOW GLOBAL STATUS LIKE \"Innodb_buffer_pool_read%\";'"

# Prometheus (если настроен)
# rate(mysql_global_status_queries[1m])
```

### 7. Очистка после теста

```bash
sysbench /usr/share/sysbench/oltp_read_write.lua \
  --mysql-host=127.0.0.1 \
  --mysql-user=sbtest \
  --mysql-password=sbtest_password \
  --mysql-db=sbtest \
  --tables=10 \
  --db-driver=mysql \
  cleanup

mariadb -u root -p -e "DROP DATABASE sbtest; DROP USER 'sbtest'@'localhost';"
```

## Устранение неполадок (Troubleshooting)

### sysbench: «connection refused»

*   **Причина:** MariaDB не запущена или недоступна по указанному host/port.
*   **Решение:** проверьте `mariadb-admin ping`, `ss -tlnp | grep 3306`, firewall.

### Низкий TPS при высокой нагрузке

*   **Причина:** узкое место — CPU, I/O, lock contention, или `Threads_running` упирается в CPU.
*   **Диагностика:** `vmstat` (CPU wa — I/O wait), `iostat` (%util), `SHOW GLOBAL STATUS LIKE 'Threads_running'`.
*   **Решение:** найдите узкое место; оптимизируйте конфигурацию (innodb_io_capacity, buffer pool).

### Ошибки в sysbench (ignored errors > 0)

*   **Причина:** deadlocks (1213), lock waits (1205), duplicate keys (1062) при write-нагрузке.
*   **Решение:** нормальное явление при высокой write-конкуренции; проверьте `SHOW ENGINE INNODB STATUS`.

### Результаты не воспроизводимы

*   **Причина:** нет прогрева buffer pool, фоновые процессы, другие нагрузки.
*   **Решение:** прогрейте 5-10 мин; изолируйте тестовый сервер; фиксируйте конфигурацию.

## Лучшие практики (Best Practices)

1.  **Baseline перед изменениями:** замерьте производительность до тюнинга.
2.  **Реалистичный working set:** данные ≥ buffer pool.
3.  **Прогрев:** 5-10 минут нагрузки перед замером.
4.  **Один параметр за раз:** изолируйте переменные.
5.  **Мониторинг параллельно:** CPU/RAM/I/O/MariaDB-метрики.
6.  **sysbench для серьёзных тестов**, `mariadb-slap` для smoke-тестов.
7.  **Очищайте тестовые данные** после теста.
8.  **Автоматизируйте захват результатов** — сохраняйте вывод sysbench в JSON или CSV для последующего сравнения (см. ниже).
9.  **Фиксируйте конфигурацию** — `SHOW VARIABLES` и `SHOW GLOBAL STATUS` до и после теста для аудита.

### Автоматизированный захват результатов

Сохранение результатов в машинно-читаемом формате позволяет автоматизировать сравнение конфигураций и выявлять регрессии:

```bash
# Запуск с --report-interval и сохранение в файл
sysbench /usr/share/sysbench/oltp_read_write.lua \
  --mysql-host=127.0.0.1 \
  --mysql-user=sbtest \
  --mysql-password=StrongTestPassword123! \
  --mysql-db=sbtest \
  --tables=10 --table-size=1000000 \
  --threads=64 --time=600 --report-interval=10 \
  --db-driver=mysql \
  run | tee results_$(date +%Y%m%d_%H%M%S).txt

# Извлечение ключевых метрик с помощью awk
TPS=$(grep "transactions:" results_*.txt | awk '{print $3}' | sed 's/(//')
P95=$(grep "95th percentile:" results_*.txt | awk '{print $4}')
echo "TPS=$TPS  p95=$P95"
```

```bash
# sysbench (>= 1.1) поддерживает вывод в JSON через --report-json=FILE
# Структура полей зависит от версии sysbench; проверьте через `jq . results.json`
sysbench /usr/share/sysbench/oltp_read_write.lua \
  --mysql-host=127.0.0.1 --mysql-user=sbtest \
  --mysql-db=sbtest \
  --threads=64 --time=600 \
  --report-interval=10 --report-json=results.json \
  --db-driver=mysql \
  run

# Парсинг JSON с помощью jq для CI/CD (проверьте реальные пути полей)
# jq '. | keys' results.json  # чтобы увидеть структуру
jq -r '.results.transactions.per_second' results.json
```

### CI/CD: обнаружение регрессий производительности

Для автоматизированного выявления регрессий добавьте шаг в пайплайн:

```bash
#!/bin/bash
# compare_benchmarks.sh — сравнение с baseline
BASELINE="results_baseline.json"
CURRENT="results_current.json"
THRESHOLD=5  # % регрессии, при которой тест падает

tps_base=$(jq -r '.results.tps' "$BASELINE")
tps_curr=$(jq -r '.results.tps' "$CURRENT")
pct_diff=$(echo "scale=2; ($tps_curr - $tps_base) / $tps_base * 100" | bc)

echo "TPS: baseline=$tps_base current=$tps_curr change=${pct_diff}%"

if (( $(echo "$pct_diff < -$THRESHOLD" | bc -l) )); then
  echo "REGRESSION: TPS dropped by ${pct_diff}% (threshold: -$THRESHOLD%)"
  exit 1
fi
```

```yaml
# Пример шага CI (GitLab CI / GitHub Actions)
# - name: Run sysbench and compare
#   run: |
#     sysbench oltp_read_write.lua --threads=32 --time=120 \
#       --report-json=results.json --db-driver=mysql run
#     ./compare_benchmarks.sh results.json results_baseline.json
```

**Важно:** sysbench использует **Closed Loop** модель (см. [Бенчмаркинг СУБД](../Concepts/benchmarking.md)), поэтому для измерения реальной пропускной способности и высоких перцентилей используйте `--rate` для имитации Open Loop, либо k6/wrk2 для production-валидации.

## Ограничения и граничные случаи

### Ограничения mariadb-slap

- **Нет progress reporting** — `mariadb-slap` не выводит промежуточную статистику во время выполнения (в отличие от sysbench `--report-interval`).
- **Ограничена гибкость запросов** — поддерживает `--query` или `--query-file`, но не параметризованные запросы с разными аргументами.
- **Не масштабируется на высокую конкуренцию** — при `--concurrency > 200` может давать искусственно завышенные latency из-за overhead нагрузчика.
- **Не сохраняет результаты** — вывод в stdout; для CI/CD нужен парсинг.

### Ограничения sysbench

- **Coordinated Omission** — sysbench использует Closed Loop по умолчанию, что занижает p99. Используйте `--rate` для ограничения частоты запросов или k6 для Open Loop тестов.
- **Драйвер mysql** — использует `libmysqlclient` или `mariadb-connector-c`; если библиотека не установлена, используйте `--db-driver=mysql` с указанием пути к connector.
- **Данные в памяти** — если working set < buffer pool, все данные кэшируются и результаты не отражают production-поведение. Используйте `--table-size` ≥ объёму working set.
- **Перезапуск между тестами** — sysbench не сбрасывает состояние СУБД между прогонами. Для чистых замеров перезапускайте `mariadbd` или очищайте buffer pool.

### Когда sysbench не подходит

- **Аналитические (OLAP) нагрузки** — sysbench OLTP-сценарии не имитируют аналитические запросы (агрегации, JOIN, scan). Для OLAP используйте TPC-H или собственные запросы.
- **Трафик с mixed read/write ratio** — если production имеет 90% read, а sysbench `oltp_read_write` даёт 50%/50%, результаты будут искажены. Корректируйте `--range-locks`, `--range-selects` и `--secondary-locks` для приближения к реальному трафику.
- **Нагрузка с долгими транзакциями** — sysbench генерирует короткие транзакции (1–2 запроса). Для имитации long-running транзакций используйте кастомные Lua-скрипты или реальный трафик.

## Дополнительная информация

### См. также

*   **[sysbench (общие концепции)](../Concepts/sysbench.md)** — теория и методология.
*   **[Бенчмаркинг СУБД](../Concepts/benchmarking.md)** — общие концепции: Open Loop vs Closed Loop, Coordinated Omission, Saturation Point, NUMA.
*   **[MySQL mysqlslap](../Concepts/mysqlslap.md)** — аналог `mariadb-slap` для MySQL (форк).
*   **[Оптимизация запросов](query_optimization.md)** — анализ результатов.
*   **[Мониторинг](monitoring.md)** — метрики во время теста.
*   **[Управление памятью](memory_management.md)** — buffer pool sizing.
*   **[Конфигурация MariaDB](./configuration.md)** — OS tuning, InnoDB sizing для тестов.

### Внешние ресурсы

*   [sysbench Documentation](https://github.com/akopytov/sysbench)
*   [MariaDB mariadb-slap](https://mariadb.com/kb/en/mariadb-slap/)
*   [sysbench OLTP test scripts](https://github.com/akopytov/sysbench/tree/master/src/lua) — Lua scripts (oltp_read_write.lua, oltp_point_select.lua и др.)
*   [Percona: sysbench articles](https://www.percona.com/blog/tag/sysbench/) — methodology, histograms, TPCC-like workloads
