# Оптимизация запросов в MariaDB: EXPLAIN, ANALYZE и гистограммы

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **EXPLAIN** — оператор, показывающий план выполнения запроса без его фактического выполнения. Выводит порядок чтения таблиц, используемые индексы, тип соединения (join type) и оценочное количество строк. Базовый инструмент диагностики медленных запросов.
*   **EXPLAIN FORMAT=JSON** — расширенный формат вывода плана в виде JSON-структуры. Доступен с MariaDB 10.1. Содержит детализацию по каждой операции: `cost`, `rows`, `filtered`, используемые индексы и условия. В MariaDB **нет** формата `EXPLAIN FORMAT=TREE` (это особенность MySQL 8.0.16+).
*   **ANALYZE** — оператор, который фактически выполняет запрос и дополняет план реальными значениями: сколько строк прочитано, время выполнения, истинная селективность. Доступен с MariaDB 10.1. Ключевое отличие от `EXPLAIN`: `ANALYZE` выполняет запрос, `EXPLAIN` — нет.
*   **ANALYZE FORMAT=JSON** — выполняет запрос и возвращает план с реальными метриками в JSON. Доступен с MariaDB 10.1.
*   **SHOW ANALYZE FORMAT=JSON** — вывод плана с реальными метриками для запроса, выполняющегося в текущий момент. Доступен с MariaDB 10.9.
*   **EXPLAIN FOR CONNECTION** — план выполнения запроса в указанной сессии (по `CONNECTION_ID()`). Доступен с MariaDB 10.9. Позволяет диагностировать долгие запросы без их прерывания.
*   **Index Hints (USE / FORCE / IGNORE INDEX)** — подсказки оптимизатору для выбора индекса. Синтаксис MariaDB: `USE INDEX`, `FORCE INDEX`, `IGNORE INDEX`. **Важно:** синтаксис оптимизаторных хинтов MySQL 8.0 (`/*+ INDEX(...) */`, `/*+ NO_INDEX_MERGE(...) */`) в MariaDB **не поддерживается** — только классические index hints.
*   **Гистограммы (Histograms)** — статистика распределения значений в столбце, используемая оптимизатором для оценки селективности неравенств (`<`, `>`, `BETWEEN`, `LIKE`). Реализованы через Engine Independent Table Statistics. Доступны с MariaDB 10.0. Хранятся в таблице `mysql.column_stats`.
*   **`r_engine_stats`** — расширенная статистика движка в выводе `EXPLAIN FORMAT=JSON` / `ANALYZE FORMAT=JSON`: количество обращений к страницам InnoDB (`pages_accessed`), время I/O и т.д. Доступна начиная с MariaDB 10.6.15, 10.8.8, 10.9.8, 10.10.6, 10.11.5, 11.0.3, 11.1.2, 11.2.1 (MDEV-31577).
*   **pt-query-digest** — утилита Percona Toolkit для агрегации и ранжирования запросов из slow query log или Performance Schema. Строит отчёт по «дайджестам» (нормализованным шаблонам запросов), выявляя самые тяжёлые запросы по суммарному времени, числу вызовов и числу просмотренных строк.
*   **Slow Query Log** — журнал запросов, превышающих порог `long_query_time` (по умолчанию 10 сек). Основной источник данных для `pt-query-digest` и ручного анализа.
*   **Performance Schema** — инструментация внутри MariaDB для сбора метрик выполнения запросов, ожиданий, блокировок и I/O. В MariaDB **выключена по умолчанию** (в отличие от MySQL 8.0+): включается `performance_schema=ON` в `my.cnf`, переменная не динамическая — требуется рестарт. Таблицы `events_statements_summary_by_digest`, `table_io_waits_summary_by_index_usage` — ключевые для анализа запросов.
*   **sys schema** — набор удобных представлений поверх Performance Schema (MariaDB 10.5+). Упрощает доступ к агрегированным метрикам: `sys.schema_unused_indexes`, `sys.statements_with_runtimes_in_95th_percentile`, `sys.statements_with_full_table_scans`.

## Требования и предпосылки (Prerequisites)

### Версии и инструменты

| Компонент | Минимум | Рекомендуется | Примечание |
| :--- | :--- | :--- | :--- |
| **MariaDB** | 10.11 LTS | 11.4 LTS / 11.8 LTS / 12.3 LTS | `EXPLAIN FOR CONNECTION`, `SHOW ANALYZE` — с 10.9+ |
| **Percona Toolkit** | 3.5 | 3.6+ | `pt-query-digest` для анализа slow log / Performance Schema |
| **MariaDB Client** | 10.11 | Актульная LTS | Для `mariadb` CLI, `mariadb-dump`, `mariadb-check` |
| **Performance Schema** | Встроена | Включена (`performance_schema=ON`) | Необходима для `sys schema` и P_S запросов |
| **sys schema** | MariaDB 10.5+ | Установлена (`mysql_sys_schema.sql`) | Упрощает анализ P_S; в 10.11+ установлена по умолчанию |

### Конфигурация MariaDB для анализа

**Обязательные настройки в `my.cnf` / `mariadb.conf.d/50-server.cnf`:**

```ini
[mariadb]
# Slow Query Log — источник для pt-query-digest
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 0.5          # Логировать запросы > 500 мс (production: 1-2 сек)
log_slow_rate_limit = 100      # Ограничить спам (1 запрос в 100 при одинаковом дайджесте)
log_slow_verbosity = query_plan,explain  # Добавить EXPLAIN в slow log (MariaDB 10.4+)

# Performance Schema — для sys schema и P_S аналитики
performance_schema = ON
performance_schema_instrument = '%=ON'  # Включить все инструменты

# Histogram settings (MariaDB 10.4.3+)
histogram_type = DOUBLE_PREC_HB
histogram_size = 255
analyze_sample_percentage = 100
```

**Валидация после применения конфигурации:**

```sql
-- Проверить, что slow log пишется
SHOW VARIABLES LIKE 'slow_query_log%';
SHOW VARIABLES LIKE 'long_query_time';

-- Проверить Performance Schema
SHOW VARIABLES LIKE 'performance_schema';
SELECT * FROM performance_schema.setup_instruments WHERE NAME LIKE 'statement/%' AND ENABLED = 'YES';

-- Проверить sys schema
SELECT * FROM sys.schema_unused_indexes LIMIT 1;
```

### Подготовка окружения (DevOps/SRE)

1.  **Доступы:** пользователь с правами `SELECT` на `mysql.*`, `performance_schema.*`, `sys.*`, `information_schema.*`; `PROCESS` для `EXPLAIN FOR CONNECTION`; `SUPER` для изменения глобальных переменных.
2.  **Дисковое пространство:** `/var/log/mysql/` — минимум 5 ГБ для slow log (ротация через `logrotate`).
3.  **Сетевое:** доступ к порту 3306 с хоста аналитика / CI-парнера.
4.  **Бэкап статистики:** перед массовым `ANALYZE TABLE` или созданием гистограмм на production — сделайте дамп `mysql.column_stats` и `mysql.innodb_index_stats`.

### Изоляция тестов

*   Не запускайте `ANALYZE` / `ANALYZE TABLE ... PERSISTENT` на production-базе без окна обслуживания — это может вызвать перестроение планов и кратковременную деградацию.
*   Используйте копию production-данных (физический бэкап или логическая реплика) для экспериментов с индексами и гистограммами.
*   В CI/CD: запускайте `EXPLAIN` на миграциях и сравнивайте планы с baseline (см. раздел **Автоматизация в CI/CD**).

## Базовые концепции

### Как работает оптимизатор MariaDB

MariaDB использует cost-based оптимизатор. Для каждого возможного плана выполнения он оценивает «стоимость» (cost) — взвешенную сумму операций I/O и CPU — и выбирает план с минимальной стоимостью. Оценка основывается на:

1.  **Статистике индексов** — кардинальность (количество уникальных значений), получаемая через `SHOW INDEX` / `ANALYZE TABLE`.
2.  **Гистограммах** — распределение значений для оценки селективности диапазонных условий.
3.  **Ограничениях таблицы** — `NOT NULL`, уникальность, наличие PK.

Типичные причины неоптимального плана: устаревшая статистика индексов, отсутствие гистограмм на неравномерно распределённых столбцах, некорректные типы данных в условиях (скрытое приведение типов отменяет использование индекса).

### Чтение вывода EXPLAIN

Ключевые столбцы классического `EXPLAIN`:

| Столбец | Значение | На что обращать внимание |
| :--- | :--- | :--- |
| `id` | Порядковый номер операции SELECT | Одинаковый `id` — операции выполняются вместе; разные — вложенные подзапросы |
| `select_type` | Тип SELECT | `SIMPLE`, `PRIMARY`, `SUBQUERY`, `DERIVED`, `UNCACHEABLE` |
| `table` | Таблица | Порядок чтения таблиц (сверху вниз) |
| `type` | Тип соединения | От лучшего к худшему: `system` → `const` → `eq_ref` → `ref` → `range` → `index` → `ALL` |
| `possible_keys` | Доступные индексы | Если `NULL` — подходящего индекса нет |
| `key` | Выбранный индекс | `NULL` — индекс не используется (full scan) |
| `rows` | Оценочное число строк | Сравните с реальным числом строк в таблице |
| `filtered` | % строк, прошедших условие | Низкое значение — условие мало селективно |
| `Extra` | Дополнительная информация | `Using index` (covering index — хорошо), `Using filesort` (сортировка на диске/в памяти), `Using temporary` (временная таблица), `Using where` |

**Правило диагностики:** `type = ALL` (full table scan) на большой таблице и `Using filesort` / `Using temporary` — основные сигналы для оптимизации.

### Гистограммы: когда они нужны

Статистика индексов (кардинальность) не отражает распределение значений. Для столбца с неравномерным распределением (например, 99% строк со значением `active` и 1% — `banned`) оптимизатор без гистограммы оценит `WHERE status = 'banned'` как сканирование половины таблицы, хотя реально затрагивается 1%. Гистограмма позволяет оптимизатору выбрать индекс для редких значений.

MariaDB поддерживает два типа гистограмм:
*   `SINGLE_PREC_HB` — одинарной точности (single-precision), экономит память (по умолчанию).
*   `DOUBLE_PREC_HB` — двойной точности, точнее для больших диапазонов.
*   `JSON_HB` — JSON-формат (MariaDB 10.8+).

**Важно:** синтаксис MariaDB отличается от MySQL. В MySQL используется `ANALYZE TABLE ... UPDATE HISTOGRAM ON col WITH N BUCKETS`; в MariaDB — `ANALYZE TABLE ... PERSISTENT FOR COLUMNS (col)`.

## Практические сценарии

### 1. Базовый анализ плана запроса

```sql
-- Классический EXPLAIN
EXPLAIN SELECT * FROM orders WHERE customer_id = 100 AND status = 'new';

-- Расширенный JSON-план (MariaDB 10.1+)
EXPLAIN FORMAT=JSON SELECT * FROM orders WHERE customer_id = 100 AND status = 'new';

-- Выполнение запроса с реальными метриками (MariaDB 10.1+)
ANALYZE SELECT * FROM orders WHERE customer_id = 100 AND status = 'new';

-- JSON-план с реальными метриками
ANALYZE FORMAT=JSON SELECT * FROM orders WHERE customer_id = 100 AND status = 'new';
```

**Валидация:** в выводе `EXPLAIN` для `customer_id` должно быть `type = ref` и `key = idx_customer`, а не `type = ALL`.

### 2. Диагностика долгого запроса в реальном времени (MariaDB 10.9+)

```sql
-- Найти ID долгого запроса
SELECT ID, TIME, STATE, INFO FROM information_schema.PROCESSLIST WHERE COMMAND != 'Sleep';

-- Получить план выполняющегося запроса без его прерывания
EXPLAIN FOR CONNECTION 42;

-- Получить план с реальными метриками для выполняющегося запроса
SHOW ANALYZE FORMAT=JSON FOR CONNECTION 42;
```

### 3. Создание и управление гистограммами

```sql
-- Создать гистограмму на столбце (MariaDB 10.0+)
ANALYZE TABLE orders PERSISTENT FOR COLUMNS (status);

-- Гистограмма на нескольких столбцах
ANALYZE TABLE orders PERSISTENT FOR COLUMNS (status, country);

-- Гистограммы на всех столбцах таблицы
ANALYZE TABLE orders PERSISTENT FOR ALL;

-- Удалить гистограмму
ANALYZE TABLE orders PERSISTENT FOR COLUMNS (status) WITH 0 BUCKETS;

-- Проверить наличие гистограмм
SELECT * FROM mysql.column_stats WHERE table_name = 'orders';

-- Настройка (в my.cnf)
[mariadb]
histogram_type = DOUBLE_PREC_HB   # по умолчанию SINGLE_PREC_HB (10.4.3+)
histogram_size = 255              # число бакетов, по умолчанию 255 (10.7+)
analyze_sample_percentage = 100   # % строк для анализа, по умолчанию 100 (10.4.3+)
```

**Валидация:** после создания гистограммы повторите `EXPLAIN` на запросе с редким значением — оценка `rows` должна стать точнее.

### 4. Index hints (MariaDB-синтаксис)

```sql
-- Предложить оптимизатору использовать индекс
SELECT * FROM orders USE INDEX (idx_customer) WHERE customer_id = 100;

-- Заставить использовать индекс (даже если оптимизатор считает иначе)
SELECT * FROM orders FORCE INDEX (idx_customer) WHERE customer_id = 100;

-- Запретить использование индекса
SELECT * FROM orders IGNORE INDEX (idx_customer) WHERE customer_id = 100;

-- Хинты для JOIN
SELECT * FROM orders o FORCE INDEX (idx_customer) JOIN customers c USE INDEX (PRIMARY) ON o.customer_id = c.id;
```

**Важно:** MySQL-ский синтаксис оптимизаторных хинтов (`/*+ ... */`) в MariaDB не работает. Используйте только `USE/FORCE/IGNORE INDEX`.

### 5. Рабочий процесс pt-query-digest

```bash
# Установка Percona Toolkit (Debian/Ubuntu)
sudo apt-get install percona-toolkit

# Анализ slow query log: топ-10 запросов по суммарному времени
pt-query-digest /var/log/mysql/slow.log --limit 10

# Анализ за последние 24 часа
pt-query-digest --since '24h' /var/log/mysql/slow.log

# Анализ из Performance Schema (без slow log)
pt-query-digest --review h=localhost,D=performance_schema,t=query_review \
  --source=perfschema

# Сохранение отчёта в файл
pt-query-digest /var/log/mysql/slow.log > report.txt

# Фильтрация по базе
pt-query-digest --filter '$event->db eq "shop"' /var/log/mysql/slow.log
```

**Интерпретация отчёта:** обратите внимание на столбцы `Exec count` (число вызовов), `Total time` (суммарное время), `Max time` (максимальное время), `Rows examine` (просмотренные строки). Запрос с высоким `Rows examine` / `Rows sent` ratio — кандидат на добавление индекса.

### 6. Проверка расширенной статистики движка (r_engine_stats)

```sql
-- Доступно с 10.6.15 / 10.8.8 / 10.9.8 / 10.10.6 / 10.11.5 / 11.0.3+
ANALYZE FORMAT=JSON SELECT * FROM orders WHERE customer_id = 100;
-- В выводе JSON ищите секцию "r_engine_stats" с полями:
--   "pages_accessed": N  — сколько страниц InnoDB прочитано
--   "pages_read": N      — физических чтений с диска
```

### 7. Анализ через Performance Schema и sys schema

```sql
-- Топ-10 запросов по суммарному времени (P95/среднее)
SELECT * FROM sys.statements_with_runtimes_in_95th_percentile LIMIT 10;

-- Запросы с полным сканированием таблиц
SELECT * FROM sys.statements_with_full_table_scans;

-- Запросы с файловой сортировкой (Using filesort)
SELECT * FROM sys.statements_with_sorting;

-- Неиспользуемые индексы (MariaDB 10.5+)
SELECT * FROM sys.schema_unused_indexes;

-- Дублирующиеся/избыточные индексы
SELECT * FROM sys.schema_redundant_indexes;

-- Прямой запрос к P_S: дайджесты запросов с метриками
SELECT
  digest_text,
  count_star AS exec_count,
  ROUND(sum_timer_wait/1e12, 3) AS total_time_sec,
  ROUND(avg_timer_wait/1e9, 3) AS avg_time_ms,
  ROUND(max_timer_wait/1e9, 3) AS max_time_ms,
  sum_rows_examined,
  sum_rows_sent,
  ROUND(sum_rows_examined/NULLIF(sum_rows_sent,0), 2) AS rows_examined_per_sent
FROM performance_schema.events_statements_summary_by_digest
WHERE schema_name = 'shop'
ORDER BY sum_timer_wait DESC
LIMIT 20;
```

**Валидация:** `rows_examined_per_sent` >> 1 — запрос читает много строк на каждую возвращённую (плохой индекс или отсутствие индекса).

### 8. Автоматизация в CI/CD: регрессионный контроль планов

```bash
#!/usr/bin/env bash
# compare_plans.sh — сравнить EXPLAIN планы с baseline
# Запускать в CI после миграций схемы

BASELINE_DIR="ci/baseline_plans"
CURRENT_DIR="ci/current_plans"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_USER="${DB_USER:-ci_user}"
DB_PASS="${DB_PASS}"
DB_NAME="${DB_NAME:-shop}"

mkdir -p "$CURRENT_DIR"

# Список критических запросов (по одному в строке, без завершающей точки с запятой)
QUERIES=(
  "SELECT * FROM orders WHERE customer_id = ? AND status = ?"
  "SELECT o.*, c.name FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.order_date > ?"
)

for i in "${!QUERIES[@]}"; do
  QUERY="${QUERIES[$i]}"
  FILE="$CURRENT_DIR/query_$i.json"
  mariadb -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" \
    -e "EXPLAIN FORMAT=JSON $QUERY" > "$FILE" 2>&1
  
  if [[ -f "$BASELINE_DIR/query_$i.json" ]]; then
    # Сравнить ключевые поля: key, type, rows, filtered
    if ! diff -u <(jq -r '.query_block.table.key' "$BASELINE_DIR/query_$i.json") \
                 <(jq -r '.query_block.table.key' "$FILE") >/dev/null; then
      echo "⚠️  PLAN CHANGED for query $i: index changed"
      echo "Baseline: $(jq -r '.query_block.table.key' "$BASELINE_DIR/query_$i.json")"
      echo "Current:  $(jq -r '.query_block.table.key' "$FILE")"
      exit 1
    fi
  fi
done

echo "✅ All query plans match baseline"
```

**Использование:** сохраняйте baseline после успешного деплоя: `cp ci/current_plans/* ci/baseline_plans/`. В CI pipeline этот скрипт фейлит сборку при изменении плана.

### 9. Еженедельный регламент: pt-query-digest + алерты

```bash
#!/usr/bin/env bash
# weekly_query_review.sh — еженедельный отчёт по медленным запросам

REPORT_DIR="/var/log/mysql/query_reports"
SLOW_LOG="/var/log/mysql/slow.log"
ALERT_THRESHOLD_MS=5000  # Алертить, если max_time > 5 сек

mkdir -p "$REPORT_DIR"
DATE=$(date +%Y%m%d)

# Полный отчёт
pt-query-digest "$SLOW_LOG" \
  --since '7d' \
  --limit 20 \
  --output json \
  > "$REPORT_DIR/report_$DATE.json"

# Человекочитаемый отчёт
pt-query-digest "$SLOW_LOG" \
  --since '7d' \
  --limit 20 \
  > "$REPORT_DIR/report_$DATE.txt"

# Проверка на регрессии: сравнить с прошлой недельей
if [[ -f "$REPORT_DIR/report_$(date -d '7 days ago' +%Y%m%d).txt" ]]; then
  # Простой diff по top-5 дайджестам
  diff -u <(head -30 "$REPORT_DIR/report_$(date -d '7 days ago' +%Y%m%d).txt") \
          <(head -30 "$REPORT_DIR/report_$DATE.txt") \
          || echo "⚠️  Query profile changed since last week"
fi

# Алерты: запросы с max_time > порога
pt-query-digest "$SLOW_LOG" \
  --since '7d' \
  --filter "(\$event->{max_time} || 0) > $ALERT_THRESHOLD_MS/1000" \
  --no-report \
  2>/dev/null | grep -q "^--" && echo "🚨 Slow queries exceeding ${ALERT_THRESHOLD_MS}ms detected"
```

**Планирование:** добавьте в `cron` (`0 6 * * 1 /path/to/weekly_query_review.sh`) или в систему мониторинга (Prometheus + node_exporter + textfile collector).

## Операции и команды (Reference)

| Операция | Команда / SQL | Версия | Назначение |
| :--- | :--- | :--- | :--- |
| **Классический план** | `EXPLAIN SELECT ...` | Все | Быстрая оценка плана |
| **JSON-план** | `EXPLAIN FORMAT=JSON SELECT ...` | 10.1+ | Детальный план с cost, filtered |
| **План с реальными метриками** | `ANALYZE SELECT ...` | 10.1+ | Выполняет запрос + реальные rows, time |
| **JSON + реальные метрики** | `ANALYZE FORMAT=JSON SELECT ...` | 10.1+ | JSON с реальными метриками |
| **План выполняющегося запроса** | `EXPLAIN FOR CONNECTION <id>` | 10.9+ | Диагностика без прерывания |
| **JSON план выполняющегося** | `SHOW ANALYZE FORMAT=JSON FOR CONNECTION <id>` | 10.9+ | Реальные метрики живого запроса |
| **Создать гистограмму** | `ANALYZE TABLE t PERSISTENT FOR COLUMNS (c)` | 10.0+ | Статистика распределения значений |
| **Гистограмма на всех колонках** | `ANALYZE TABLE t PERSISTENT FOR ALL` | 10.0+ | Массовое создание |
| **Удалить гистограмму** | `ANALYZE TABLE t PERSISTENT FOR COLUMNS (c) WITH 0 BUCKETS` | 10.0+ | Очистка |
| **Обновить статистику индексов** | `ANALYZE TABLE t` | Все | Кардинальность для оптимизатора |
| **Проверить гистограммы** | `SELECT * FROM mysql.column_stats WHERE table_name='t'` | 10.0+ | Инвентаризация |
| **pt-query-digest (файл)** | `pt-query-digest /var/log/mysql/slow.log --limit 10` | PT 3.0+ | Топ запросов из slow log |
| **pt-query-digest (P_S)** | `pt-query-digest --source=perfschema --review h=...,D=performance_schema,t=query_review` | PT 3.0+ | Анализ без slow log |
| **sys: неиспользуемые индексы** | `SELECT * FROM sys.schema_unused_indexes` | 10.5+ | Кандидаты на удаление |
| **sys: дублирующиеся индексы** | `SELECT * FROM sys.schema_redundant_indexes` | 10.5+ | Кандидаты на удаление |
| **sys: топ запросов P95** | `SELECT * FROM sys.statements_with_runtimes_in_95th_percentile` | 10.5+ | Регрессионный контроль |
| **r_engine_stats** | `ANALYZE FORMAT=JSON SELECT ...` → JSON `r_engine_stats` | 10.6.15+ / 11.0.3+ | I/O статистика InnoDB |

## Устранение неполадок (Troubleshooting)

### EXPLAIN показывает type=ALL (full scan)

*   **Причина:** нет индекса по условию WHERE, или условие отменяет индекс (функция над столбцом, скрытое приведение типов).
*   **Диагностика:** проверьте `possible_keys` (NULL = нет индекса). Проверьте типы данных: `WHERE varchar_col = 100` (число vs строка) отменяет индекс.
*   **Решение:** создайте индекс по условию; избегайте функций над индексированными столбцами в WHERE (`WHERE DATE(created_at) = ...` — перепишите как диапазон `created_at >= ... AND created_at < ...`).

### Оценка `rows` в EXPLAIN сильно отличается от реальной

*   **Причина:** устаревшая статистика индексов или отсутствие гистограмм на неравномерно распределённых столбцах.
*   **Диагностика:** `SHOW INDEX FROM table` — проверьте кардинальность. `SELECT * FROM mysql.column_stats` — проверьте наличие гистограмм.
*   **Решение:** `ANALYZE TABLE table_name;` для обновления статистики; создайте гистограмму через `ANALYZE TABLE ... PERSISTENT FOR COLUMNS (col)`.

### ANALYZE выполняется слишком долго

*   **Причина:** `ANALYZE` фактически выполняет запрос — на тяжёлых запросах это может занять значительное время.
*   **Решение:** используйте `EXPLAIN` для предварительной оценки; `ANALYZE` — только на запросах приемлемой длительности. Для долгих запросов используйте `EXPLAIN FOR CONNECTION` (10.9+).

### Гистограмма не улучшает план

*   **Причина:** гистограммы работают только для условий сравнения (`=`, `<`, `>`, `BETWEEN`, `IN`), не для `LIKE '%...'`, `IS NULL`, и не влияют на выбор порядка JOIN.
*   **Решение:** проверьте, что условие подходит для гистограммы; увеличьте `histogram_size` (число бакетов).

## Ограничения и граничные случаи (Edge Cases)

### 1. Отсутствие `EXPLAIN FORMAT=TREE` в MariaDB

MariaDB **не поддерживает** формат `EXPLAIN FORMAT=TREE` (появился в MySQL 8.0.16). Для иерархического представления используйте `EXPLAIN FORMAT=JSON` и парсьте дерево программно, либо `ANALYZE FORMAT=tree` (MariaDB 10.5+, алиас для JSON). В CI/CD скриптах не полагайтесь на TREE-формат.

### 2. `EXPLAIN FOR CONNECTION` — ограничения

*   Требует привилегию `PROCESS` (или быть тем же пользователем).
*   Показывает план **только для текущего состояния** запроса — если запрос уже завершился, вернёт ошибку.
*   Не работает для prepared statements, выполненных через бинарный протокол (только для текстовых запросов).
*   В высоконагруженных системах сам `EXPLAIN FOR CONNECTION` может добавить нагрузку — используйте избирательно.

### 3. `ANALYZE` выполняет запрос — побочные эффекты

`ANALYZE SELECT ...` **фактически выполняет** запрос:
*   Пишет в binlog (если не `SELECT` — но `ANALYZE` работает только для `SELECT`).
*   Может триггерить триггеры (в редких случаях, если оптимизатор решает материализовать подзапрос).
*   Удерживает блокировки на время выполнения.
*   **Не используйте** на `DELETE`/`UPDATE` — синтаксис не поддерживается.

### 4. Гистограммы: ограничения применимости

*   Не работают для `LIKE '%pattern%'` (leading wildcard) — всегда full scan.
*   Не работают для `IS NULL` / `IS NOT NULL` (оптимизатор использует другую логику).
*   Не влияют на **порядок JOIN** — только на оценку селективности доступа к одной таблице.
*   На больших таблицах (>100M строк) создание гистограммы может занять минуты — планируйте окно обслуживания.
*   `ANALYZE TABLE ... PERSISTENT FOR ALL` на wide-таблицах (50+ колонок) создаёт громоздкую запись в `mysql.column_stats` — укажите только нужные колонки.

### 5. Оптимизаторные хинты MySQL (`/*+ ... */`) — не работают

В MariaDB **нет** поддержки:
*   `/*+ INDEX(t idx_name) */` — используйте `FORCE INDEX`
*   `/*+ JOIN_ORDER(t1, t2) */` — нет аналога
*   `/*+ MAX_EXECUTION_TIME(1000) */` — используйте `max_statement_time` переменную сессии
*   `/*+ HASH_JOIN(...) */` — Hash Join в MariaDB управляется через `optimizer_switch`

**Миграция с MySQL:** при переносе приложения с MySQL 8.0 на MariaDB все optimizer hints в комментариях становятся неэффективными (игнорируются). Необходим аудит кода и замена на MariaDB-синтаксис или `optimizer_switch`.

### 6. `pt-query-digest` — ограничения

*   Не парсит `EXPLAIN` из `log_slow_verbosity=query_plan` автоматически — нужен кастомный `--filter`.
*   При анализе Performance Schema требует таблицу `query_review` (создаётся автоматически, но нужны права `CREATE`/`INSERT` на `performance_schema`).
*   Не учитывает `r_engine_stats` — только тайминги и rows.
*   На очень больших slow log (>10 ГБ) потребляет много RAM — используйте `--since` для ограничения временного окна.

### 7. `sys schema` — версии и совместимость

*   В MariaDB 10.5–10.10 `sys schema` может отсутствовать или быть устаревшей — установите актуальную через `mysql_sys_schema.sql` из репозитория MariaDB.
*   В 10.11+ включена по умолчанию, но представления могут отличаться от MySQL 8.0 `sys` (например, нет `sys.schema_table_lock_waits`).
*   `sys.schema_unused_indexes` не учитывает индексы, используемые для FK-проверок — перед удалением проверяйте `information_schema.TABLE_CONSTRAINTS`.

### 8. Статистика и `ANALYZE TABLE` на репликах

На репликах с `read_only=ON`:
*   `ANALYZE TABLE` **блокируется** (требует запись в `mysql.innodb_index_stats` / `mysql.column_stats`).
*   Статистика реплицируется от source через binlog (DDL `ANALYZE TABLE` реплицируется).
*   Если на source статистика устарела — реплика тоже будет с устаревшей. Решение: запускать `ANALYZE TABLE` на source в окне обслуживания.

### 9. `r_engine_stats` — доступность по версиям

`r_engine_stats` в `EXPLAIN FORMAT=JSON` / `ANALYZE FORMAT=JSON` доступен **только** в указанных патч-версиях (MDEV-31577):
*   10.6.15+, 10.8.8+, 10.9.8+, 10.10.6+, 10.11.5+, 11.0.3+, 11.1.2+, 11.2.1+
*   В 10.11.4, 11.0.2, 11.1.1 — **отсутствует**. Проверяйте версию перед использованием в скриптах.

## Лучшие практики (Best Practices)

1.  **Всегда начинайте с EXPLAIN:** перед оптимизацией запроса смотрите план. `type = ALL` и `Using filesort` — основные сигналы.
2.  **Обновляйте статистику после массовых изменений:** `ANALYZE TABLE` после загрузки больших объёмов данных.
3.  **Гистограммы на неравномерных столбцах:** создавайте гистограммы на столбцах с перекошенным распределением (статусы, флаги, регионы).
4.  **MariaDB-синтаксис хинтов:** используйте `USE/FORCE/IGNORE INDEX`, а не MySQL-ский `/*+ ... */`.
5.  **pt-query-digest в регламенте:** запускайте еженедельно для выявления регрессий производительности.
6.  **Не оптимизируйте без измерений:** используйте `ANALYZE` для подтверждения, что изменение плана реально ускорило запрос.
7.  **CI/CD: контроль планов выполнения:** храните baseline `EXPLAIN FORMAT=JSON` для критических запросов и сравнивайте в pipeline после миграций (см. сценарий **Автоматизация в CI/CD**).
8.  **Slow Query Log на production:** `long_query_time = 1-2` сек, `log_slow_verbosity = query_plan,explain` — даёт контекст без необходимости подключаться к БД.
9.  **Performance Schema + sys schema:** используйте `sys.statements_with_runtimes_in_95th_percentile` и `sys.schema_unused_indexes` для еженедельного аудита без парсинга логов.
10. **Индексы перед гистограммами:** правильный составной индекс часто решает проблему лучше, чем гистограмма. Гистограммы — для случаев, когда индекс существует, но оптимизатор ошибается в селективности.
11. **Настройте `max_statement_time`:** в production установите лимит времени выполнения запроса (сессионно или глобально) для защиты от runaway queries.
12. **Мониторьте `Handler_read_rnd_next` / `Handler_read_next`:** через `SHOW GLOBAL STATUS` — рост `Handler_read_rnd_next` указывает на полные сканирования.
13. **Документируйте FORCE INDEX:** каждый `FORCE INDEX` в коде должен иметь комментарий с тикетом и датой пересмотра — при изменении данных он может стать вредным.
14. **Бэкап статистики перед массовыми изменениями:** `mysqldump mysql.column_stats mysql.innodb_index_stats` перед `ANALYZE TABLE ... PERSISTENT FOR ALL` или массовым перестроением индексов.
15. **Избегайте `SELECT *` в production:** всегда перечисляйте колонки — это позволяет оптимизатору использовать covering index и уменьшает I/O.

## Дополнительная информация

### См. также

*   **[Индексы в MariaDB](indexing.md)** — создание и обслуживание индексов, Ignored Indexes, covering indexes.
*   **[Временные таблицы](temporary_tables.md)** — диагностика `Using temporary`, настройка `tmp_table_size` / `max_heap_table_size`.
*   **[Мониторинг MariaDB](monitoring.md)** — slow query log, Performance Schema, sys schema, алерты на `Handler_read_rnd_next`.
*   **[InnoDB: настройка производительности](innodb_durability_tuning.md)** — буферы, I/O, чекпоинты.
*   **[Конфигурация MariaDB](configuration.md)** — `optimizer_switch`, `sort_buffer_size`, `join_buffer_size`, `tmp_table_size`.
*   **[Обслуживание](maintenance.md)** — регламентные задачи: `ANALYZE TABLE`, проверка неиспользуемых индексов, ротация slow log.
*   **[Онлайн DDL](online_schema_change.md)** — создание индексов без блокировок записи.
*   **[Общие концепции индексов](../Concepts/indexes.md)** — теория B-tree, покрывающие индексы, селективность, leftmost prefix.
*   **[Концепции производительности БД](../Concepts/database_performance_concepts.md)** — USE/RED методы, SLO/SLI, capacity planning.
*   **[MySQL: EXPLAIN и оптимизация](../MySQL/Operations/explain_and_optimization.md)** — отличия MySQL (FORMAT=TREE, оптимизаторные хинты, Hash Join, MRR).
*   **[MariaDB: репликация](replication/overview.md)** — влияние `ANALYZE TABLE` на репликацию статистики.

### Внешние ресурсы

*   [MariaDB EXPLAIN](https://mariadb.com/kb/en/explain/)
*   [MariaDB ANALYZE](https://mariadb.com/kb/en/analyze/)
*   [MariaDB Histograms](https://mariadb.com/kb/en/histograms/)
*   [MariaDB Index Hints](https://mariadb.com/kb/en/index-hints/)
*   [pt-query-digest](https://www.percona.com/doc/percona-toolkit/LATEST/pt-query-digest.html)
*   [MariaDB Optimizer Switch](https://mariadb.com/kb/en/optimizer-switch/)
*   [MariaDB sys schema](https://mariadb.com/kb/en/sys-schema/)
*   [MDEV-31577: r_engine_stats](https://jira.mariadb.org/browse/MDEV-31577)
