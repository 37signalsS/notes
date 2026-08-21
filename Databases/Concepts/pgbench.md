# pgbench

## Определения

**pgbench** — встроенный инструмент PostgreSQL для бенчмаркинга и нагрузочного тестирования. Изначально имитирует TPC-B нагрузку (высокая интенсивность обновлений) с4 таблицами: `pgbench_accounts`, `pgbench_branches`, `pgbench_history`, `pgbench_tellers`. В PostgreSQL 10+ доступны расширенные профили и поддержка кастомных SQL-скриптов. Использует Closed Loop модель.

**TPC-B (в контексте pgbench)** — упрощенный профиль нагрузки, не являющийся полноценным TPC-C. Включает SELECT, UPDATE и INSERT в фиксированных пропорциях. Для полноценного TPC-C используйте [HammerDB](./hammerdb.md).

---

## Установка

pgbench входит в дистрибутив PostgreSQL и не требует отдельной установки:

```bash
# Ubuntu / Debian
sudo apt install -y postgresql-client

# RHEL / CentOS / Rocky Linux
sudo dnf install -y postgresql
```

### Проверка версии

```bash
pgbench --version  # → pgbench (PostgreSQL) 16.x
```

---

## Подготовка данных

### Стандартная инициализация (TPC-B)

```bash
# Scale factor 100 = 10 млн строк (100 * 100,000 accounts)
pgbench -i -s 100 mydatabase
# → Создает 4 таблицы:
#   pgbench_accounts (10,000,000 строк)
#   pgbench_branches (100,000 строк)
#   pgbench_tellers  (1,000,000 строк)
#   pgbench_history  (не заполняется при инициализации)

# Проверка данных:
psql -d mydatabase -c "SELECT COUNT(*) FROM pgbench_accounts;"
# → 10000000
```

### Параметры инициализации

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-i` | Режим инициализации (initialize) | Обязательный для первого запуска |
| `-s` | Scale factor (множитель размера) | SF=100 для 10 млн строк |
| `--fillfactor` | Процент заполнения страниц (для UPSERT) | По умолчанию 100 |
| `-p` | Параллелизм инициализации | Ускоряет создание больших таблиц |

---

## Запуск теста

### Стандартный режим (TPC-B)

```bash
# Запуск теста:
# -c: клиенты (параллельные соединения)
# -j: потоки (внутренняя параллелизация pgbench)
# -T: время в секундах
# -S: только чтение (select-only)
# -M: protocol (extended, simple, prepared)
pgbench -c 50 -j 8 -T 600 -S mydatabase
# → Тест "только чтение" с 50 клиентами в течение 10 минут

# Запуск смешанной нагрузки (чтение + запись, по умолчанию):
pgbench -c 50 -j 8 -T 600 mydatabase
# → По умолчанию: SELECT (70%), UPDATE (14%), INSERT (14%), DELETE (2%)
```

### Ключевые параметры

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-c` | Количество параллельных клиентов | Начинайте с 1, увеличивайте до Saturation Point |
| `-j` | Количество потоков pgbench | Обычно等于 количеству ядер CPU |
| `-T` | Время теста в секундах | Минимум 300, для Steady State — 1800 |
| `-S` | Только чтение (select-only) | Для тестирования реплик |
| `-M` | Протокол (extended/simple/prepared) | `prepared` снижает overhead парсинга |
| `--log` | Логирование каждой транзакции | Для детального анализа |
| `--report-per-command` | Статистика по каждому типу запроса | В совокупности с `--log` |

### Расширенные профили (PostgreSQL 10+)

```bash
# Протокол prepared (снижает overhead парсинга):
pgbench -c 50 -j 8 -T 600 -M prepared mydatabase

# Протокол extended (по умолчанию, самый безопасный):
pgbench -c 50 -j 8 -T 600 -M extended mydatabase

# Логирование каждой транзакции для анализа:
pgbench -c 32 -j 8 -T 300 --log --log-prefix=pgbench_log mydatabase
# → Создает файлы pgbench_log_*.log с деталями каждой транзакции
```

---

## Кастомные SQL-скрипты

pgbench позволяет писать собственные SQL-сценарии через файлы:

### Пример 1: Точечные selects

```sql
-- custom_select.sql — точечные selects по primary key
\set aid random(1, 10000000)
SELECT abalance FROM pgbench_accounts WHERE aid = :aid;
```

### Пример 2: Смешанная нагрузка

```sql
-- mixed_workload.sql — смешанная нагрузка с динамическими данными
\set aid random(1, 10000000)
\set bid random(1, 10000)
\set tid random(1, 100000)
\set delta random(-5000, 5000)

BEGIN;
UPDATE pgbench_accounts SET balance = balance + :delta WHERE aid = :aid;
UPDATE pgbench_tellers SET balance = balance + :delta WHERE tid = :tid;
UPDATE pgbench_branches SET balance = balance + :delta WHERE bid = :bid;
INSERT INTO pgbench_history (tid, bid, aid, delta, mtime) VALUES (:tid, :bid, :aid, :delta, CURRENT_TIMESTAMP);
END;
```

### Запуск кастомных скриптов

```bash
# Запуск с кастомным скриптом:
pgbench -c 32 -j 8 -T 300 -f custom_select.sql mydatabase

# Смешивание стандартных и кастомных сценариев (веса):
pgbench -c 32 -j 8 -T 300 \
    -f custom_select.sql@70 \
    -f mixed_workload.sql@30 \
    mydatabase
```

### Доступные pgbench-директивы

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `\set var random(min, max)` | Генерация случайного числа | `\set aid random(1, 10000000)` |
| `\set var int'literal'` | Присвоение переменной | `\set scale 100` |
| `\sleep int' seconds'` | Пауза между запросами | `\sleep 0.5` |
| `\g` | Выполнение накопленного запроса | После нескольких SQL-строк |

---

## Интерпретация вывода

```text
transaction type: <builtin: TPC-B (sort of)>
scaling factor: 100
query mode: simple
number of clients: 50
number of threads: 8
duration: 600 s
number of transactions actually processed: 1456789
latency average = 2.061 ms
initial connection time = 12.345 ms
tps = 24279.816449 (without establishing connection)
```

**На что смотреть:**
- **`tps`** — пропускная способность без учёта времени установки соединения. Сравнивайте с baseline.
- **`latency average`** — средняя задержка. Для более детального анализа используйте `--log`.
- **`initial connection time`** — время установки соединения. Если велико, проверьте настройки `max_connections` и Connection Pooler.
- **`number of transactions actually processed`** — фактически обработанные транзакции. Должно быть близко к ожидаемому (TPS * duration).

---

## Ограничения

- **TPC-B, не TPC-C:** pgbench имитирует TPC-B (упрощенный профиль), а не полноценный TPC-C. Для TPC-C используйте [HammerDB](./hammerdb.md).
- **Только PostgreSQL:** Не работает с другими СУБД.
- **Точность метрик:** pgbench не сообщает перцентили (p95, p99) в основном выводе. Для детального анализа используйте `--log`.
- **Closed Loop модель:** Аналогично sysbench, при росте Latency автоматически падает RPS.

---

## Дополнительная информация

### См. также

- **[Нагрузочное тестирование СУБД](./benchmarking.md)** — общая методология, подготовка среды, интерпретация результатов.
- **[Ключевые концепции производительности](./database_performance_concepts.md)** — теория TPS, Latency, USE-метод.
- **[sysbench](./sysbench.md)** — кросс-СУБД бенчмаркинг (MySQL, PostgreSQL, MariaDB).
- **[HammerDB](./hammerdb.md)** — кросс-СУБД бенчмаркинг (TPC-C/TPC-H).
