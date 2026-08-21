# mysqlslap

## Определения

**mysqlslap** — встроенный инструмент MySQL для бенчмаркинга и нагрузочного тестирования. Входит в дистрибутив MySQL Server (начиная с 5.5) и не требует отдельной установки. Подходит для быстрых проверок и A/B-тестирования конфигураций, но менее функционален, чем [sysbench](./sysbench.md). Использует Closed Loop модель.

---

## Установка

mysqlslap уже доступен, если установлен MySQL Server или MySQL Client:

```bash
# Проверка наличия:
mysqlslap --help

# Версия:
mysqlslap --version  # → mysqlslap  Ver 8.0.xx Distrib
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

## Ключевые параметры

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `--concurrency` | Количество параллельных соединений | Начинайте с 10, увеличивайте |
| `--iterations` | Количество повторений теста | Минимум 3 для статистики |
| `--number-of-queries` | Общее количество запросов | Зависит от времени теста |
| `--create-schema` | Имя создаваемой БД | Обязательный параметр |
| `--host` | Хост MySQL | localhost для локального теста |
| `--user` | Пользователь MySQL | Достаточно SELECT на тестовых таблицах |
| `--delimiter` | Разделитель запросов (для файла) | По умолчанию `;` |
| `--query` | Файл с запросами или строка | Для пользовательских запросов |

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

---

## Ограничения

- **Нет перцентилей:** Выводит только среднее время, без p95/p99. Для детального анализа используйте [sysbench](./sysbench.md).
- **Closed Loop модель:** Аналогично sysbench/pgbench, при росте Latency автоматически падает RPS.
- **Простой анализ:** Невозможно разделить разные типы запросов в смешанной нагрузке.
- **Ограниченная функциональность:** Нет встроенных профилей нагрузки (OLTP, OLAP).
- **Нет кастомных скриптов:** Только SQL-запросы, без Lua/Python расширений.

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
