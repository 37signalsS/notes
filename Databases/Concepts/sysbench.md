# sysbench

## Определения

**sysbench** — универсальный инструмент для бенчмаркинга и нагрузочного тестирования СУБД (MySQL, MariaDB, PostgreSQL). Поддерживает несколько встроенных профилей нагрузки и кастомные Lua-скрипты для создания произвольных сценариев. Использует Closed Loop модель (новый запрос отправляется только после получения ответа на предыдущий).

---

## Установка

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y sysbench

# RHEL / CentOS / Rocky Linux
sudo dnf install -y sysbench

# macOS (Homebrew)
brew install sysbench
```

### Проверка версии

```bash
sysbench --version  # → sysbench 1.0.xx
```

---

## Доступные тесты

| Тест | Описание | Типичное применение |
| :--- | :--- | :--- |
| `oltp_read_write` | Смешанная нагрузка 80/20 (чтение/запись) | Основной OLTP-тест |
| `oltp_read_only` | Только чтение | Тестирование реплик |
| `oltp_write_only` | Только запись | Тестирование ingestion |
| `oltp_point_select` | Точечный SELECT по PK | Максимальный IOPS |
| `oltp_scan` | Сканирование диапазона | Тестирование range scan |
| `oltp_insert` | Вставка строк | Тестирование吞吐量 вставки |
| `oltp_delete` | Удаление строк | Тестирование удаления |
| `oltp_update_index` | Обновление с индексами | Тестирование contention |
| `oltp_update_non_index` | Обновление без индексов | Тестирование heap |
| `oltp_bulk_insert` | Пакетная вставка | LOAD DATA, COPY |

---

## Подготовка данных

```bash
# 10 таблиц по 1 млн строк (~4 ГБ на таблицу, ~40 ГБ всего)
sysbench oltp_read_write --mysql-db=test --tables=10 --table-size=1000000 prepare
# → Создает таблицы и заполняет их данными через bulk INSERT

# Проверка созданных данных:
mysql -e "SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='test';"
# → sbtest1 (1000000), sbtest2 (1000000), ...
```

**Важно:** Размер данных (`--table-size`) должен превышать объем RAM сервера минимум в 2 раза. В противном случае вы тестируете только скорость RAM, а не реальную производительность СУБД под нагрузкой I/O.

---

## Запуск теста

```bash
# 16 потоков, 5 минут, отчет каждые 10 секунд
sysbench oltp_read_write --threads=16 --time=300 --report-interval=10 run
```

### Ключевые параметры

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `--threads` | Количество виртуальных пользователей | Начинайте с 1, увеличивайте до Saturation Point |
| `--time` | Время теста в секундах | Минимум 300 (5 мин), для Steady State — 1800 (30 мин) |
| `--report-interval` | Интервал вывода промежуточных результатов | 10-60 секунд |
| `--mysql-db` | Имя базы данных | Обязательный параметр |
| `--table-size` | Количество строк в каждой таблице | Должно превышать RAM в 2+ раза |
| `--tables` | Количество таблиц | По умолчанию 10 |

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

**На что смотреть:**
- **`transactions (per sec.)`** — итоговый Throughput (TPS). Сравнивайте с baseline.
- **`95th percentile`** — хвостовая задержка. Для OLTP целевое значение обычно < 5-10 мс.
- **`max`** — максимальная задержка. Если на порядки больше `avg`, возможны всплески (spikes) из-за Checkpoint или блокировок.
- **`reconnects`** — если > 0, означает потерю соединений (исчерпан `max_connections` или `wait_timeout`).
- **`ignored errors`** — если > 0, означает ошибки транзакций (deadlock, timeout). Требует разбора.

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
| `db_prepare(sql)` | Подготовка SQL-запроса (-prepared statement) |
| `db_execute(stmt, ...)` | Выполнение подготовленного запроса с параметрами |
| `db_query(sql)` | Выполнение произвольного SQL-запроса |
| `sysbench.rand.uniform(min, max)` | Генерация случайного числа в диапазоне |
| `sysbench.rand.gaussian(mean, stddev)` | Генерация случайного числа по нормальному распределению |
| `sysbench.opt.table_size` | Доступ к параметру `--table-size` |

---

## Ограничения

- **Closed Loop модель:** sysbench использует Closed Loop. Для точного измерения Coordinated Omission используйте k6 с `constant-arrival-rate`.
- **Ограниченные профили:** Невозможно легко создать сложный профиль без написания Lua-скрипта.
- **Одна СУБД за раз:** sysbench не умеет выполнять распределенные тесты (sharding) без внешней оркестрации.
- **Нет Open Loop:** При росте Latency автоматически падает RPS, что маскирует реальную пропускную способность.

---

## Дополнительная информация

### См. также

- **[Нагрузочное тестирование СУБД](./benchmarking.md)** — общая методология, подготовка среды, интерпретация результатов.
- **[Ключевые концепции производительности](./database_performance_concepts.md)** — теория TPS, Latency, USE-метод.
- **[pgbench](./pgbench.md)** — встроенный инструмент PostgreSQL для TPC-B нагрузки.
- **[HammerDB](./hammerdb.md)** — кросс-СУБД бенчмаркинг (TPC-C/TPC-H).
