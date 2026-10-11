# mysqlslap

**Актуально для:** MySQL Client 8.0 LTS / 8.4 LTS

## Определения

**mysqlslap** — встроенный инструмент MySQL для бенчмаркинга и нагрузочного тестирования. Входит в состав MySQL Server и MySQL Client (начиная с 5.5) и не требует отдельной установки. Подходит для быстрых проверок и A/B-тестирования конфигураций, но менее функционален, чем [sysbench](./sysbench.md). Использует Closed Loop модель.

---

## Архитектура и принцип работы

mysqlslap работает в трёх последовательных стадиях:

1. **Create** — создание схемы и таблиц: выполнение SQL из `--create` или auto-generated DDL.
2. **Run** — нагрузочный прогон: создание N параллельных соединений (`--concurrency`), каждое выполняет запросы из `--query` или auto-generated SQL. Результаты агрегируются по итерациям.
3. **Cleanup** — удаление временных объектов: DROP TABLE, если указан флаг `--drop-first` или используется auto-generate режим с очисткой.

Для auto-generate режима mysqlslap создаёт таблицу с двумя INT-полями и несколькими VARCHAR-полями, заполняет её данными, выполняет нагрузку и удаляет таблицу. Для пользовательских запросов схема и данные должны существовать заранее.

**Варианты запуска:**
- **auto-generate-sql** — mysqlslap создаёт таблицу, данные и запросы автоматически.
- **пользовательские запросы** — передаются через `--query` и `--create`.
- **файловый режим** — `--query=query.sql` и `--create=create.sql` для сложных сценариев.

---

## Установка

mysqlslap поставляется с mysql-client и не требует отдельной установки:

```bash
# Проверка наличия:
mysqlslap --help

# Версия соответствует версии MySQL Client:
mysqlslap --version  # → mysqlslap  Ver 8.4.11 for Linux on x86_64 (MySQL Community Server - GPL)
```

### Совместимость с MariaDB

В MariaDB 10.5+ инструмент переименован в `mariadb-slap` (см. [client_utilities.md](../../Databases/MariaDB/client_utilities.md)). Старое имя `mysqlslap` сохраняется как символическая ссылка, но в автоматизации рекомендуется использовать новые имена для избежания конфликтов с Oracle MySQL.

```bash
# MariaDB:
mariadb-slap --help
```

---

## Режимы работы

### 1. Автоматический тест (auto-generate-sql)

MySQL сам генерирует нагрузку с помощью встроенных запросов:

```bash
# Базовый автоматический тест:
mysqlslap --auto-generate-sql \
    --auto-generate-sql-write-number=100000 \
    --auto-generate-sql-load-type=mixed \
    --concurrency=50 --iterations=5 \
    --number-of-queries=1000000 \
    --host=localhost --user=root --password=secret
# → Average number of seconds to run all queries: 12.345
```

#### Параметры auto-generate-sql

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `--auto-generate-sql-write-number` | Количество строк для вставки | Зависит от размера теста |
| `--auto-generate-sql-load-type` | Тип нагрузки (read/write/mixed) | `mixed` для OLTP |
| `--auto-generate-sql-add-autoinc` | Добавление AUTO_INCREMENT | Для корректного теста |
| `--auto-generate-sql-write-number-multiplier` | Множитель для write-number | Ускоряет подготовку |

### 2. Пользовательские запросы

```bash
# Тест с пользовательским запросом:
mysqlslap --query="SELECT * FROM orders WHERE customer_id = FLOOR(RAND() * 100000)" \
    --concurrency=32 --iterations=10 \
    --create-schema=testdb \
    --host=localhost --user=root --password=secret
```

### 3. Сравнение конфигураций

```bash
# Запуск теста с текущими настройками:
mysqlslap --auto-generate-sql --concurrency=50 --iterations=3 \
    --number-of-queries=500000 --host=localhost --user=root
# → Average number of seconds to run all queries: 12.345

# Измените my.cnf, перезапустите MySQL, запустите тест снова:
mysqlslap --auto-generate-sql --concurrency=50 --iterations=3 \
    --number-of-queries=500000 --host=localhost --user=root
# → Average number of seconds to run all queries: 8.901

# Сравните: 12.345 -> 8.901 (улучшение на 28%)
```

---

## Подготовка данных

### Подготовка для пользовательских запросов

Для режима `--query` схема и таблицы должны существовать заранее:

```bash
# Создание тестовой схемы и таблицы:
mysql -e "CREATE DATABASE IF NOT EXISTS testdb;
          CREATE TABLE testdb.orders (
              id INT AUTO_INCREMENT PRIMARY KEY,
              customer_id INT NOT NULL,
              amount DECIMAL(10,2),
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_customer (customer_id)
          );"

# Заполнение данными (для нагрузочного теста):
mysql -e "INSERT INTO testdb.orders (customer_id, amount)
          SELECT FLOOR(RAND() * 100000), RAND() * 1000
          FROM information_schema.columns
          LIMIT 1000000;"
```

### Подготовка через файлы (create/query)

Для сложных сценариев используйте файлы с SQL:

```sql
-- create.sql
CREATE TABLE IF NOT EXISTS testdb.orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    amount DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_customer (customer_id)
);
INSERT INTO testdb.orders (customer_id, amount)
SELECT FLOOR(RAND() * 100000), RAND() * 1000
FROM information_schema.columns
LIMIT 1000000;
```

```sql
-- query.sql
SELECT * FROM orders WHERE customer_id = FLOOR(RAND() * 100000);
SELECT count(*) FROM orders WHERE customer_id = ?;
UPDATE orders SET amount = amount * 1.1 WHERE id = ?;
```

```bash
# Запуск с файлами:
mysqlslap --create=create.sql --query=query.sql \
    --concurrency=32 --iterations=10 \
    --delimiter=";" \
    --host=localhost --user=root --password=secret
```

### Валидация подготовленных данных

```bash
# Проверка количества строк:
mysql -e "SELECT COUNT(*) FROM testdb.orders;"  # → 1000000

# Проверка индексов:
mysql -e "SHOW INDEX FROM testdb.orders;"
```

**Важно:** Для auto-generate режима mysqlslap сам создаёт таблицу, но для пользовательских запросов схема должна существовать заранее.

---

## Ключевые параметры

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `--concurrency` | Количество параллельных соединений | Начинайте с 10, увеличивайте до Saturation Point |
| `--iterations` | Количество повторений теста | Минимум 3 для статистики |
| `--number-of-queries` | Общее количество запросов | Зависит от времени теста |
| `--create-schema` | Имя создаваемой БД | Обязательный параметр для user queries |
| `--host` | Хост MySQL | localhost для локального теста |
| `--user` | Пользователь MySQL | Достаточно SELECT на тестовых таблицах |
| `--delimiter` | Разделитель запросов (для файла) | По умолчанию `;` |
| `--query` | Файл с запросами или строка | Для пользовательских запросов |
| `--create` | Файл или строка с DDL/DML | Для создания схемы и данных |
| `--auto-generate-sql` | Автогенерация схемы, данных и запросов | Для быстрых smoke-тестов |
| `--auto-generate-sql-write-number` | Количество строк для вставки | Зависит от размера теста |
| `--auto-generate-sql-load-type` | Тип нагрузки (read/write/mixed) | `mixed` для OLTP |
| `--number-int-cols` | Количество INT-столбцов в auto-generate | 2 по умолчанию |
| `--number-char-cols` | Количество VARCHAR-столбцов | 3 по умолчанию |
| `--drop-first` | Удалить таблицу перед созданием | Для повторяемых тестов |
| `--verbose` | Подробный вывод | Для отладки |
| `--engine` | Хранилище (innodb/myisam) | innodb для OLTP |
| `--ssl` | Включить SSL/TLS соединение | Для production-подобных тестов |

---

## Интерпретация вывода

```text
Benchmark
    Running for engine innodb
    Average number of seconds to run all queries: 12.345 seconds
    Minimum number of seconds to run all queries: 11.200 seconds
    Maximum number of seconds to run all queries: 13.500 seconds
    Number of clients running queries: 50
    Average number of queries per client: 20000
```

**На что смотреть:**
- **`Average number of seconds`** — основная метрика. Сравнивайте между конфигурациями.
- **`Minimum / Maximum`** — разброс результатов. Большой разброс указывает на нестабильность.
- **`Number of clients`** — параллельность нагрузки.
- **`Average number of queries per client`** — общая нагрузка на клиента.

### Ограничения вывода

mysqlslap выводит только среднее время, без перцентилей (p95/p99). Для детального анализа latency используйте [sysbench](./sysbench.md) или [pgbench](./pgbench.md).

---

## Устранение неисправностей (Troubleshooting)

### Ошибка 1: Утечка пароля в процессах

**Симптом:** Пароль виден в `ps aux` или истории команд.
**Причина:** Использование `--password=secret` в командной строке.
**Решение:** Используйте `--defaults-extra-file=/path/to/creds.cnf` с правами `600`.

### Ошибка 2: Тестирование RAM вместо дисков

**Симптом:** Вывод показывает очень низкое время выполнения, `Innodb_buffer_pool_reads` = 0.
**Причина:** Размер данных меньше Buffer Pool.
**Диагностика:** `SHOW STATUS LIKE 'Innodb_buffer_pool_reads';` — если 0 или близко к 0, данные в памяти.
**Решение:** Увеличьте размер тестовой таблицы так, чтобы она превышала Buffer Pool в 2+ раза.

### Ошибка 3: Нестабильные результаты между итерациями

**Симптом:** Разброс `Average/Minimum/Maximum` > 20%.
**Причина:** Фоновые процессы (Checkpoint, purge), плавание частоты CPU, кэширование.
**Диагностика:** `cat /proc/cpuinfo | grep "cpu MHz"`, `iostat -xz 1`.
**Решение:** Фиксируйте частоту CPU (`performance` governor), делайте warm-up, запускайте минимум 3 раза и берите медиану.

### Ошибка 4: Низкая параллельность (concurrency bottleneck)

**Симптом:** При увеличении `--concurrency` общее время не уменьшается.
**Причина:** Исчерпание `max_connections`, `innodb_thread_concurrency` или CPU на сервере.
**Диагностика:** `SHOW STATUS LIKE 'Threads_connected';`, `SHOW VARIABLES LIKE 'max_connections';`.
**Решение:** Увеличьте лимиты, проверьте Connection Pooler.

### Ошибка 5: Слишком быстрые результаты для write-тестов

**Симптом:** `mixed` или `write` тест выполняется за доли секунды.
**Причина:** Слишком маленький `--number-of-queries` или `--auto-generate-sql-write-number`.
**Решение:** Увеличьте количество запросов/строк до реалистичных значений (100K+).

---

## Ограничения и нюансы (Edge Cases)

- **Нет перцентилей:** Выводит только среднее время, без p95/p99. Для детального анализа используйте [sysbench](./sysbench.md).
- **Closed Loop модель:** Аналогично sysbench/pgbench, при росте Latency автоматически падает RPS. При высокой latency вы получите заниженный Throughput.
- **Простой анализ:** Невозможно разделить разные типы запросов в смешанной нагрузке. Всё сводится к одному среднему значению.
- **Ограниченная функциональность:** Нет встроенных профилей нагрузки OLTP/OLAP. Для TPC-C/TPC-H используйте [HammerDB](./hammerdb.md).
- **Нет кастомных скриптов:** Только SQL-запросы, без Lua/Python расширений.
- **Deprecated опция:** Начиная с MySQL 8.0.18, опция `--auto-generate-sql` помечена как deprecated. В будущих версиях она может быть удалена. Для долгосрочных сценариев используйте пользовательские запросы через `--query` и `--create`.
- **Зависимость от хранилища по умолчанию:** Auto-generate создаёт таблицы в хранилище по умолчанию. Убедитесь, что тестируете нужный engine (`--engine=innodb`).

---

## Best Practices

1. **Изоляция нагрузчика:** Никогда не запускайте `mysqlslap` на том же сервере, где находится БД. Используйте отдельный сервер или контейнер для нагрузки.
2. **Безопасность:** Не передавайте пароль через `--password` в командной строке — он виден в `ps aux` и истории. Используйте `--defaults-extra-file=/path/to/creds.cnf`:
   ```ini
   # creds.cnf
   [client]
   user=benchmark
   password=secret
   ```
   ```bash
   mysqlslap --defaults-extra-file=./creds.cnf --host=prod-db ...
   ```
3. **Объём данных:** Размер тестовой таблицы должен превышать объем InnoDB Buffer Pool минимум в 2 раза. Иначе вы тестируете только скорость RAM.
4. **Повторяемость:** Запускайте каждый тест минимум 3 раза и берите медиану. Стандартное отклонение не должно превышать 5%.
5. **Фиксация конфигурации:** Перед A/B-тестированием фиксируйте версию MySQL, параметры my.cnf и схему данных.
6. **Мониторинг:** Во время теста держите открытым `mysqladmin extended-status` и `iostat -xz 1`. Следите за `Innodb_buffer_pool_reads` и `iowait`.
7. **Постепенная нагрузка:** Используйте ramp-up (10, 25, 50, 100, 200...) для нахождения Saturation Point.
8. **Валидация дисков:** Перед тестированием СУБД проверьте диски через `fio` (см. [fio.md](../../Linux/Diagnostics/Filesystem/fio.md)).

---

## Когда использовать mysqlslap

| Сценарий | Рекомендация |
| :--- | :--- |
| Быстрая проверка изменений конфигурации | mysqlslap подходит |
| A/B тестирование двух настроек my.cnf | mysqlslap подходит |
| Профессиональный бенчмаркинг с перцентилями | Используйте [sysbench](./sysbench.md) |
| Сравнение разных СУБД | Используйте [HammerDB](./hammerdb.md) |
| Тестирование PostgreSQL | Используйте [pgbench](./pgbench.md) |

---

## Дополнительная информация

### См. также

- **[Нагрузочное тестирование СУБД](./benchmarking.md)** — общая методология, подготовка среды, интерпретация результатов.
- **[sysbench](./sysbench.md)** — более функциональный инструмент для MySQL/MariaDB/PostgreSQL.
- **[Ключевые концепции производительности](./database_performance_concepts.md)** — теория TPS, Latency, USE-метод.
- **[MariaDB Client Utilities](../../Databases/MariaDB/client_utilities.md)** — переименование утилит в MariaDB, `mariadb-slap`.
- **[fio: Flexible I/O Tester](../../Linux/Diagnostics/Filesystem/fio.md)** — бенчмаркинг дисковой подсистемы перед тестированием СУБД.
