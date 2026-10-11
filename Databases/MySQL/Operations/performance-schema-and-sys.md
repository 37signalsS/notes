# Performance Schema и sys schema в MySQL: профилирование работающей СУБД

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation

Performance Schema (P_S) — встроенный в сервер механизм наблюдения, собирающий счётчики
ожиданий, блокировок, SQL-операций и памяти. sys schema — надстройка над P_S: набор
представлений, хранимых процедур и функций, превращающий технические счётчики в готовые
ответы на эксплуатационные вопросы. Оба механизма включаются по умолчанию и не требуют
рестарта — в этом их главная ценность для SRE: на живом сервере видно, кто именно и
чем именно мешает.

Партнёры по теме: [Анализ медленных запросов](./slow-query-analysis.md) — логи и
`pt-query-digest`; [EXPLAIN и оптимизация](./explain_and_optimization.md) — план
исполнения конкретного запроса; [Мониторинг MySQL](../monitoring.md) — выгрузка метрик
в Prometheus/Zabbix.

## Определения

| Термин | Значение |
| :--- | :--- |
| Instrument | Точка измерения внутри сервера (ожидание файлового ввода-вывода, блокировка, выполнение SQL). Имеет состояние `ENABLED`/`DISABLED` и флаг `TIMED` |
| Consumer | Механизм, решил, события каких инструментов собирать и в какие таблицы складывать |
| Statement digest | Нормализованный текст запроса, где литералы заменены на `?`. `SELECT * FROM t WHERE id = 42` и `SELECT * FROM t WHERE id = 7` дают один digest |
| Timer | Все значения времени в P_S хранятся в пикосекундах. Секунды = значение / 1e12 |
| Wait event | Событие ожидания: клиент ждал ресурса сервера (диск, блокировка, сеть). Суммарное время ожиданий близко к реальной latency |
| Stage event | Этап выполнения внутри одного wait event (например, «инициализация сканирования» внутри «чтение страницы») |

## Предварительные требования и начальная настройка

- **MySQL 8.0+** — sys schema устанавливается автоматически при инициализации
  data directory. На MySQL 5.7 его устанавливал `mysql_upgrade` вручную; при работе
  с 5.7 доступен меньший набор представлений (см. [Граничные случаи и ограничения](#граничные-случаи-и-ограничения)).
- **`performance_schema` включён по умолчанию** в MySQL 8.0+ (переменная
  `performance_schema = ON`, не динамическая —/rest required). На MariaDB по умолчанию
  выcluded и требует включения в конфигурационном файле с последующим рестартом.
- **Привилегии:** для чтения `performance_schema` и `sys` достаточно `SELECT`. Для
  просмотра чужих сессий в `SHOW PROCESSLIST` / `INFORMATION_SCHEMA.PROCESSLIST`
  нужна `PROCESS`. Для изменения `setup_instruments` / `setup_consumers` — `SUPER`
  (или `SYSTEM_VARIABLES_ADMIN` / `UPDATE` на `performance_schema`*).
- **Проверка включения P_S:**

```sql
SHOW VARIABLES LIKE 'performance_schema';
-- → performance_schema | ON

SHOW GLOBAL STATUS LIKE 'Performance_schema_setup_instruments';
-- → Performance_schema_setup_instruments | 130
```

- **Проверка доступности sys schema:**

```sql
SELECT COUNT(*) FROM sys.sys_config;
-- → COUNT(*) | 6
```

Если `sys.sys_config` недоступна — схема не установлена; на 5.7 выполнить
`mysql_upgrade --upgrade-system-tables`.

## Базовые концепции

### Архитектура наблюдаемости

P_S состоит из трёх слоёв:

1. **Инструменты (instruments)** — объявлены в `performance_schema.setup_instruments`.
   Каждый инструмент можно включать и выключать по отдельности.
2. **Потребители (consumers)** — объявлены в `performance_schema.setup_consumers`.
   Пример: `events_statements_current` (что выполняется прямо сейчас),
   `events_statements_summary_by_digest` (агрегаты по всем запросам),
   `events_waits_summary_global_by_event_name` (агрегаты по ожиданиям).
3. **Таблицы с данными** — обычные таблицы в схеме `performance_schema`,
   читаемые обычным `SELECT`.

Метаданные и сводные таблицы потребляют память и, при большом числе активных инструментов,
дают заметный оверхед. Управление этим — практическая задача: либо оставить включённым
набор по умолчанию, либо точечно расширить его под конкретную проблему.

### sys schema: два вида представлений

Большинство представлений sys schema существует парами:

| Имя | Содержимое |
| :--- | :--- |
| `sys.statement_analysis` | Пикосекунды, форматированные в читаемый вид (`1.23 s`), часть колонок обрезана по длине |
| `sys.x$statement_analysis` | Те же данные в сыром виде, без форматирования — для программной обработки |

Пара — это `sys.<имя>` и `sys.x$<имя>`. Все объекты sys schema имеют `DEFINER` вида
`mysql.sys@localhost`. Схема устанавливается при инициализации data directory начиная
с MySQL 8.0; на 5.7 её ставил `mysql_upgrade`.

Настройки самого sys schema лежат в таблице `sys.sys_config` (пишется через неё,
а не через `SET PERSIST`):

```sql
SELECT variable, value, set_time, set_by
FROM sys.sys_config
WHERE variable LIKE 'statement%';

-- → variable                              | value | set_time           | set_by
-- → statement_truncate_len                | 64    | 2024-01-01 00:00:00 | NULL
-- → statement_performance_analyzer.limit  | 100   | 2024-01-01 00:00:00 | NULL

UPDATE sys.sys_config
SET value = '5000'
WHERE variable = 'statement_truncate_len';
-- → Запрос выполнен, затронуто 1 строка
```

Колонка `set_by` заполняется триггерами `sys_config_insert_set_user` /
`sys_config_update_set_user` при вставке/обновлении строки: если вставляемое или
изменяемое значение `set_by` равно `NULL` и не установлен флаг
`@sys.ignore_sys_config_triggers = true` (используется при сбросе таблицы в тестах),
оно заменяется на `USER()`. Если значение `set_by` уже задано — триггер его не
перезаписывает. Значение `set_time` обновляется автоматически при каждом
изменении строки (DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP).

### Statement digest и его ограничения

Digest приводит текст запроса к нормализованной форме заменой литералов. Это позволяет
отвечать на вопрос «какой запрос суммарно съедает больше всего процессорного времени»,
даже если запрос выполняется с десятком разных значений параметров.

Цена этого — обрезка: если текст запроса длиннее `performance_schema_max_digest_length`,
хвост обрезается. Для диагностики это почти всегда несущественно.

Отдельный случай: `performance_schema` не видит запросы, выполненные через Prepared
Statements, без фактического `EXECUTE` — учёт идёт по вызовам, а не по тексту.

### Что даёт `sys.diagnostics()`

Хранимая процедура `sys.diagnostics()` собирает срез состояния сервера одним вызовом:
версии, переменные, статусные счётчики, конфигурация P_S, сводка по операциям, блокировки,
метаданные, память. Это правильный первый вызов при инциденте — вместо двадцати ручных
`SHOW` получается один отчёт.

## Практические сценарии

### Сценарий 1. Найти самый дорогой запрос на живом сервере

Это первый вопрос почти при любом разборе инцидента производительности.

```sql
-- Топ-10 запросов по суммарной задержке за период наблюдения
SELECT
    query,
    exec_count,
    round(total_latency/1e9, 2)        AS total_s,
    round(avg_latency/1e9, 6)          AS avg_s,
    round(max_latency/1e9, 3)          AS max_s,
    rows_sent_avg,
    rows_examined_avg,
    tmp_disk_tables,
    full_scan,
    last_seen
FROM sys.statement_analysis
ORDER BY total_latency DESC
LIMIT 10;
```

Порядок сортировки выбирают по симптому:

| Симптом | Сортировать по | Что ищем |
| :--- | :--- | :--- |
| Высокий CPU на сервере | `total_latency DESC` | Запросы, суммарно съедающие CPU |
| Медленный единичный запрос | `max_latency DESC` | Тяжёлые разовые запросы |
| Много возвращённых данных | `rows_sent_avg DESC` | Запросы без `LIMIT`, отдающие лишнее |
| Много прочитанных строк | `rows_examined_avg DESC` | Запросы с неэффективным планом |
| Растёт дисковое чтение | `tmp_disk_tables DESC` | Запросы, уходящие во временные таблицы на диск |

Второй по важности критерий — **соотношение `rows_examined_avg` к `rows_sent_avg`**.
Если сервер прочитал 1 000 000 строк, чтобы вернуть 20, — проблема не в скорости, а в
индексах, и никакой тюнинг сервера её не решит.

### Сценарий 2. Найти запросы без индексов и с полным сканированием

```sql
-- Запросы, выполнившие полное сканирование таблицы
SELECT query, db, exec_count,
       rows_examined_max, rows_sent_avg, total_latency
FROM sys.statements_with_full_table_scans
ORDER BY total_latency DESC
LIMIT 20;

-- Таблицы, которые чаще всего сканируются целиком
SELECT * FROM sys.schema_tables_with_full_table_scans
LIMIT 20;

-- Запросы, которые создали дисковые временные таблицы
SELECT query, exec_count, memory_tmp_tables, disk_tmp_tables
FROM sys.statements_with_temp_tables
WHERE disk_tmp_tables > 0
ORDER BY disk_tmp_tables DESC
LIMIT 10;

-- Запросы с ошибками или предупреждениями (частая причина «медленно» — retry в приложении)
SELECT query, error, warn, exec_count, total_latency
FROM sys.statements_with_errors_or_warnings
ORDER BY error DESC
LIMIT 10;
```

### Сценарий 3. Топ запросов по 95-му перцентилю

Среднее время врёт: запрос со средним 10 мс может иметь 99-ю перцентиль в 5 секунд.
Представление `statements_with_runtimes_in_95th_percentile` показывает запросы, чья
средняя задержка в микросекундах превышает 95-й перцентиль среди всех digest'ов —
удобный быстрый срез «что медленно»:

```sql
SELECT * FROM sys.statements_with_runtimes_in_95th_percentile LIMIT 10;
```

Механизм: представление присоединяет строки из
`performance_schema.events_statements_summary_by_digest` к вспомогательному
представлению `x$ps_digest_95th_percentile_by_avg_us`, вычисляющему 95-й перцентиль
по столбцу `AVG_TIMER_WAIT` (переведённому в микросекунды), и отбирает те, у кого
`ROUND(stmts.avg_timer_wait/1000000)` больше или равна перцентилю. Сортировка по
`AVG_TIMER_WAIT DESC`. Порог отсечения — встроенный в представление, регулируется
параметром `statement_performance_analyzer.limit` в `sys.sys_config`
(по умолчанию `100`).

### Сценарий 4. Точечная инструментация конкретного запроса

По умолчанию многие инструменты выключены, чтобы не платить оверхедом. Когда нужно
разобрать один запрос и не весь сервер, инструмент включается адресно.

```sql
-- Включить сбор ожиданий для конкретного SQL-оператора и всех классов ожиданий
UPDATE performance_schema.setup_instruments
SET ENABLED = 'YES', TIMED = 'YES'
WHERE NAME IN ('statement/sql/select',
               'wait/io/file/sql/innodb',
               'wait/lock/table/sql',
               'wait/lock/transaction/sql');

-- Проверить, что инструмент действительно включился
SELECT NAME, ENABLED, TIMED
FROM performance_schema.setup_instruments
WHERE NAME = 'statement/sql/select';
-- → NAME                   | ENABLED | TIMED
-- → statement/sql/select   | YES     | YES

-- Простой запрос наблюдать в реальном времени (по одному событию на поток)
SELECT sql_text, timer_start, timer_end,
       rows_examined, rows_sent, sort_rows
FROM performance_schema.events_statements_current
ORDER BY timer_start DESC
LIMIT 5;
-- → ... текущие операции (в т.ч. сам диагностический SELECT)

-- Гистограмма времени выполнения
CALL sys.ps_statement_avg_latency_histogram();
-- → histogram
-- → percentile | total_latency | avg_latency | count | stddev | min | max
-- → 0.00        | 0.00 s        | 0.000105 s  | 1523  | ...    | ... | ...

-- Трассировка всех инструментов конкретного digest (глубокая диагностика)
CALL sys.ps_trace_statement_digest('YOUR_DIGEST_GOES_HERE');
```

Обязательно возвращать инструменты в исходное состояние после диагностики:

```sql
UPDATE performance_schema.setup_instruments
SET ENABLED = 'NO', TIMED = 'NO'
WHERE NAME = 'statement/sql/select';
```

> **Практический вывод:** инструментация — не бесплатная. `TIMED = 'YES'` означает
> два чтения часов на событие. На нагруженном сервере включение инструментов для всех
> потоков заметно снижает пропускную способность. Включать точечно и на короткое время.

### Сценарий 5. Разбор ожиданий (wait events)

Суммарное время ожиданий по классам — главный ответ на вопрос «куда уходит latency».

```sql
-- Топ ожиданий по суммарному времени (требует consumers events_waits_summary_global_by_event_name)
SELECT event_name, count_star,
       round(sum_timer_wait/1e12, 3)   AS total_s,
       round(avg_timer_wait/1e9, 3)    AS avg_ms
FROM performance_schema.events_waits_summary_global_by_event_name
ORDER BY sum_timer_wait DESC
LIMIT 15;

-- То же самое через sys schema
SELECT * FROM sys.wait_classes_global_by_latency LIMIT 10;

-- Что конкретно делает конкретный поток прямо сейчас
SELECT tid, processlist_id, processlist_user, processlist_command,
       processlist_time, current_statement
FROM performance_schema.threads
WHERE type = 'FOREGROUND' AND processlist_id IS NOT NULL
ORDER BY processlist_time DESC
LIMIT 10;
-- → tid | processlist_id | user     | command | time | current_statement
-- → 137 |            4821 | appuser  | Query   |   31 | SELECT ... FROM orders
```

Значения `wait_classes_global_by_latency` читаются так:

| Высокая доля | Диагноз | Куда идти |
| :--- | :--- | :--- |
| `metadata/sql` | Ожидание MDL — тяжёлый DDL или долгий запрос, держащий блокировку метаданных | `sys.schema_table_lock_waits` |
| `transaction/sql` | Блокировки строк | `sys.innodb_lock_waits`, [Блокировки и дедлоки](../locking_and_deadlocks.md) |
| `innodb_buffer_pool` / `wait/io` | Данных в памяти нет, идёт чтение с диска | Проверить hit rate buffer pool и физический ввод-вывод |
| `socket/sql` | Ожидание данных от клиента или медленный клиент | Проблема на стороне приложения или сети |
| `thread/sql` | Планировщик не даёт потоку CPU | Перегрузка CPU либо избыточная конкуренция за ресурсы |

### Сценарий 6. Память: кто и на что тратит

```sql
-- Глобальный срез памяти
SELECT event_name, current_alloc, current_alloc / 1024 / 1024 AS current_mb
FROM sys.memory_global_by_current_bytes
ORDER BY current_alloc DESC
LIMIT 10;

-- Общая сумма
SELECT * FROM sys.memory_global_total;
-- → total_allocated | total_current_allocated | ...
-- → 1.23G          | 456.78M                  | ...

-- Потребление памяти потоками приложения
SELECT thread_id, user, current_bytes FROM sys.memory_by_thread_by_current_bytes
WHERE user <> 'user/background' ORDER BY current_bytes DESC LIMIT 5;
```

Отдельно полезно найти потерянные инструменты — они молча перестают собирать данные,
и это выглядит как «P_S не работает», хотя на самом деле данные не собираются:

```sql
SELECT * FROM sys.ps_check_lost_instrumentation;
-- → variable | value
-- → (пустой результат — потерь нет)
```

### Сценарий 7. Накладные расходы и состояние P_S

```sql
SHOW VARIABLES LIKE 'performance_schema%';
-- → performance_schema = ON

SHOW GLOBAL STATUS LIKE 'Performance_schema%';
-- → Performance_schema_memory_handles        | 372
-- → Performance_schema_memory_handles_lost   | 0        ← потери памяти: счётчик обязан быть 0
-- → Performance_schema_memory_global_handles | 372
-- → Performance_schema_users                 | 8
-- → Performance_schema_setup_consumers       | 16
-- → Performance_schema_setup_instruments     | 130

-- Что включено прямо сейчас
CALL sys.ps_setup_show_enabled_consumers();
CALL sys.ps_setup_show_enabled_instruments();
CALL sys.ps_setup_show_disabled_consumers();
```

`Performance_schema_memory_handles_lost` — главный индикатор проблемы: ненулевое значение
означает, что сервер не смог выделить память под данные P_S и часть событий потеряна.

### Сценарий 8. Сброс накопленных агрегатов

Сводные таблицы P_S живут всю жизнь сервера и содержат данные с момента старта. После
изменения схемы запросов старые агрегаты мешают анализу.

```sql
CALL sys.ps_truncate_all_tables();
```

> **Осторожно:** сброс обнуляет всю накопленную историю агрегатов P_S. Не выполнять,
> если анализ уже идёт или данные используются для отчётов.

### Сценарий 9. Инвентаризация подключений и хостов

```sql
-- Частота запросов по типам от конкретных хостов
SELECT * FROM sys.host_summary_by_statement_latency LIMIT 10;

-- Разбивка по пользователям — быстрый ответ на вопрос «кто грузит сервер»
SELECT user, statements, total_latency, total_statement_latency
FROM sys.user_summary
ORDER BY total_latency DESC
LIMIT 10;

-- Кэш хостов: показывает, как клиенты подключаются (DNS-резолв, аутентификация)
SELECT IP, HOST, HOST_VALIDATED, SUM_CONNECT_ERRORS, COUNT_HOST_BLOCKED_ERRORS,
       COUNT_HANDSHAKE_ERRORS, FIRST_SEEN, LAST_SEEN
FROM performance_schema.host_cache
ORDER BY SUM_CONNECT_ERRORS DESC
LIMIT 10;
```

`host_cache` — недооценённый инструмент. Он отвечает на вопрос «кто ходит на мой сервер и
почему у него ошибки подключения» без анализа логов.

### Сценарий 10. Быстрый отчёт при инциденте

```sql
CALL sys.diagnostics();
-- → Логический дамп диагностической информации (версии, переменные, статусы,
--   конфигурация P_S, сводка по операциям, блокировки, метаданные, память)
```

Вывод сохраняется целиком в файл и используется как вложение к тикету:

```bash
mysql -u monitoring -p -e "CALL sys.diagnostics()" > /var/log/mysql/diag_$(date +%F_%H%M).txt
# → файл на 500–2000 строк, пригоден для офлайн-разбора
```

### Сценарий 11. Сборка отчёта о медленных запросах за период

```sql
CALL sys.statement_performance_analyzer();
-- → Отчёт по операциям, выполняющимся на сервере (top N по latency, памяти и блокировкам)
```

Альтернатива для регулярного сбора — `statement_analysis` в JSON, который забирается
мониторингом. Список представлений sys schema полезно знать целиком: он небольшой
и закрывает почти все операционные вопросы.

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `sys.statement_analysis` возвращает пустой результат | Не сработал consumer `events_statements_digest` или запросов ещё не было | `SELECT NAME, ENABLED FROM performance_schema.setup_consumers WHERE NAME LIKE '%statements%'`; выполнить любой запрос и повторить |
| В `statement_analysis` обрезаны тексты запросов | Слишком мал `performance_schema_max_digest_length` (по умолчанию 1024 байт) | Увеличить системную переменную `performance_schema_max_digest_length` при старте сервера; проверить `statement_truncate_len` в `sys.sys_config` |
| `sys.ps_check_lost_instrumentation` возвращает строки | Сервер не смог выделить память под данные P_S | Уменьшить число включённых инструментов либо увеличить память; проверить `Performance_schema_memory_handles_lost` |
| Текст запросов в P_S обрезан по умолчанию | Диагностический `SELECT` конкурирует с приложением | Фильтровать по `THREAD_ID` конкретного соединения, а не читать `events_statements_current` целиком |
| `sys.schema_unused_indexes` показывает индекс, который «не используется» | Учитывается только период наблюдения; ночные или месячные задачи не попали в окно | Собрать статистику за период, сопоставимый с полным циклом задач, удалять осознанно |
| Нет данных по конкретному инструменту ожидания | Инструмент не `TIMED` или не `ENABLED` | Проверить `setup_instruments`, включить адресно |

## Лучшие практики

- **Начинать с `sys.statement_analysis`, а не с `EXPLAIN`.** План исполнения показывает,
  что *должно* произойти; агрегаты показывают, что *происходит на самом деле* в проде.
- **Смотреть на соотношение `rows_examined` к `rows_sent`.** Это главный индикатор
  необходимости индексов.
- **Инструментацию включать адресно и временно.** Массовое `TIMED = 'YES'` по всем
  инструментам на нагруженном сервере само по себе создаёт инцидент.
- **Данные P_S — only in memory.** Они обнуляются при рестарте. Для истории нужны
  [логи](./slow-query-analysis.md) или внешний сбор метрик.
- **Не читать `events_statements_current` без фильтра.** Это самая частая причина
  собственного лоада на диагностике.
- **Регулярно проверять `Performance_schema_memory_handles_lost`.** Ненулевое значение —
  тихий дефект наблюдаемости.

## Дополнительная информация

### Полный инвентарь sys schema

**Таблица и триггеры**

| Объект | Назначение |
| :--- | :--- |
| `sys_config` | Таблица настроек sys schema |
| `sys_config_insert_set_user` | Триггер на INSERT в `sys_config` |
| `sys_config_update_set_user` | Триггер на UPDATE в `sys_config` |

**Представления**

| Представление | Содержимое |
| :--- | :--- |
| `host_summary` | Активность операций, файловый ввод-вывод, соединения по хостам |
| `host_summary_by_file_io` | Файловый ввод-вывод по хостам |
| `host_summary_by_file_io_type` | Файловый ввод-вывод по хостам и типам событий |
| `host_summary_by_stages` | Этапы операций по хостам |
| `host_summary_by_statement_latency` | Статистика операций по хостам |
| `host_summary_by_statement_type` | Выполненные операции по хостам и типам |
| `innodb_buffer_stats_by_schema` | Данные buffer pool по схемам |
| `innodb_buffer_stats_by_table` | Данные buffer pool по схемам и таблицам |
| `innodb_lock_waits` | Информация о блокировках InnoDB |
| `io_by_thread_by_latency` | Потребители ввода-вывода по потокам |
| `io_global_by_file_by_bytes` | Потребители ввода-вывода по файлам и байтам |
| `io_global_by_file_by_latency` | Потребители ввода-вывода по файлам и задержке |
| `io_global_by_wait_by_bytes` | Потребители ввода-вывода по байтам |
| `io_global_by_wait_by_latency` | Потребители ввода-вывода по задержке |
| `latest_file_io` | Последние операции ввода-вывода по файлам и потокам |
| `memory_by_host_by_current_bytes` | Память по хостам |
| `memory_by_thread_by_current_bytes` | Память по потокам |
| `memory_by_user_by_current_bytes` | Память по пользователям |
| `memory_global_by_current_bytes` | Память по типам выделения |
| `memory_global_total` | Суммарное потребление памяти |
| `metrics` | Метрики сервера |
| `processlist` | Данные processlist |
| `ps_check_lost_instrumentation` | Переменные, потерявшие инструменты |
| `schema_auto_increment_columns` | Информация о колонках AUTO_INCREMENT |
| `schema_index_statistics` | Статистика по индексам |
| `schema_object_overview` | Типы объектов в каждой схеме |
| `schema_redundant_indexes` | Дублирующиеся и избыточные индексы |
| `schema_table_lock_waits` | Ожидания блокировок на уровне таблиц (включая MDL) |
| `schema_table_statistics` | Статистика по таблицам |
| `schema_table_statistics_with_buffer` | Статистика по таблицам с данными buffer pool |
| `schema_tables_with_full_table_scans` | Таблицы, сканируемые целиком |
| `schema_unused_indexes` | Неиспользуемые индексы |
| `sessions` | Активные сессии с контекстом (пользователь, хост, запрос, транзакция) |
| `session_ssl_status` | SSL-информация по соединениям |
| `statement_analysis` | Агрегатная статистика по операциям |
| `statements_with_errors_or_warnings` | Операции с ошибками и предупреждениями |
| `statements_with_full_table_scans` | Операции с полным сканированием |
| `statements_with_runtimes_in_95th_percentile` | Операции с наибольшим средним временем |
| `statements_with_sorting` | Операции, выполнявшие сортировку |
| `statements_with_temp_tables` | Операции, использовавшие временные таблицы |
| `user_summary` | Активность операций и соединений по пользователям |
| `user_summary_by_file_io` | Файловый ввод-вывод по пользователям |
| `user_summary_by_file_io_type` | Файловый ввод-вывод по пользователям и типам событий |
| `user_summary_by_stages` | Этапы операций по пользователям |
| `user_summary_by_statement_latency` | Статистика операций по пользователям |
| `user_summary_by_statement_type` | Выполненные операции по пользователям и типам |
| `version` | Версии sys schema и сервера MySQL |
| `wait_classes_global_by_avg_latency` | Средняя задержка по классам ожиданий |
| `wait_classes_global_by_latency` | Суммарная задержка по классам ожиданий |
| `waits_by_host_by_latency` | События ожидания по хостам и событиям |
| `waits_by_user_by_latency` | События ожидания по пользователям и событиям |
| `waits_global_by_latency` | События ожидания по событиям |

Некоторые представления имеют версионные варианты с суффиксом `_57` — они используют
другую структуру строк `performance_schema` и доступны для обратной совместимости:
`host_summary_57`, `processlist_57`, `user_summary_57`, `metrics_56`,
`ps_check_lost_instrumentation_57`, `ps_trace_thread_57`, `ps_setup_reset_to_default_57*`.
На MySQL 8.0+ используйте версии без суффикса.

Представления `x$ps_digest_95th_percentile_by_avg_us`, `x$ps_digest_avg_latency_distribution`,
`x$ps_schema_table_statistics_io`, `x$schema_flattened_keys` — служебные помощники,
используемые перечисленными выше представлениями.

**Хранимые процедуры**

| Процедура | Назначение |
| :--- | :--- |
| `diagnostics()` | Сбор системной диагностической информации |
| `create_synonym_db()` | Создание синонима для схемы |
| `execute_prepared_stmt()` | Выполнение подготовленного оператора |
| `statement_performance_analyzer()` | Отчёт по операциям на сервере |
| `table_exists()` | Проверка существования таблицы |
| `ps_setup_enable_instrument()` | Включить инструмент |
| `ps_setup_disable_instrument()` | Выключить инструмент |
| `ps_setup_enable_consumer()` | Включить потребителя |
| `ps_setup_disable_consumer()` | Выключить потребителя |
| `ps_setup_enable_thread()` | Включить инструментацию потока |
| `ps_setup_disable_thread()` | Выключить инструментацию потока |
| `ps_setup_enable_background_threads()` | Включить инструментацию фоновых потоков |
| `ps_setup_disable_background_threads()` | Выключить инструментацию фоновых потоков |
| `ps_setup_reload_saved()` | Загрузить сохранённую конфигурацию P_S |
| `ps_setup_reset_to_default()` | Сбросить конфигурацию к значениям по умолчанию |
| `ps_setup_save()` | Сохранить текущую конфигурацию P_S |
| `ps_setup_show_disabled()` | Показать выключенную конфигурацию P_S |
| `ps_setup_show_disabled_consumers()` | Показать выключенных потребителей |
| `ps_setup_show_disabled_instruments()` | Показать выключенные инструменты |
| `ps_setup_show_enabled()` | Показать включённую конфигурацию P_S |
| `ps_setup_show_enabled_consumers()` | Показать включённых потребителей |
| `ps_setup_show_enabled_instruments()` | Показать включённые инструменты |
| `ps_statement_avg_latency_histogram()` | Гистограмма задержки операций |
| `ps_trace_statement_digest()` | Трассировка инструментации для digest |
| `ps_trace_thread()` | Дамп данных P_S для потока |
| `ps_truncate_all_tables()` | Очистить сводные таблицы P_S |

**Хранимые функции**

| Функция | Назначение |
| :--- | :--- |
| `format_bytes()` | Преобразование байтов в значение с единицами измерения |
| `format_path()` | Замена каталогов в пути на имена системных переменных |
| `format_statement()` | Обрезка длинного оператора до фиксированной длины |
| `format_time()` | Преобразование пикосекунд в значение с единицами измерения |
| `list_add()` | Добавление элемента в список |
| `list_drop()` | Удаление элемента из списка |
| `quote_identifier()` | Экранирование строки как идентификатора |
| `sys_get_config()` | Значение настройки sys schema |
| `extract_schema_from_file_name()` | Извлечение имени схемы из имени файла |
| `extract_table_from_file_name()` | Извлечение имени таблицы из имени файла |
| `ps_is_account_enabled()` | Включена ли инструментация для учётной записи |
| `ps_is_consumer_enabled()` | Включён ли потребитель |
| `ps_is_instrument_default_enabled()` | Включён ли инструмент по умолчанию |
| `ps_is_instrument_default_timed()` | Таймируется ли инструмент по умолчанию |
| `ps_is_thread_instrumented()` | Включена ли инструментация для ID соединения |
| `ps_thread_account()` | Учётная запись по ID потока P_S |
| `ps_thread_id()` | ID потока P_S для ID соединения |
| `ps_thread_stack()` | События ожидания для ID соединения |
| `ps_thread_trx_info()` | Информация о транзакции для ID потока |
| `version_major()` | Старшая часть версии сервера |
| `version_minor()` | Младшая часть версии сервера |
| `version_patch()` | Патч версии сервера |

### Граничные случаи и ограничения

- **Данные не переживают рестарт.** Это принципиальное отличие от логов и от метрик,
  выгружаемых во внешние системы.
- **Агрегаты накапливаются с момента старта.** На сервере, работающем месяцы, в таблице
  присутствуют и актуальные, и исчезнувшие запросы; для точной картины применяют
  `ps_truncate_all_tables()` или смотрят на `first_seen`/`last_seen`.
- **`sys.schema_unused_indexes` опасен как источник истины.** Индекс, не использованный
  за текущий период наблюдения, может использоваться ежемесячной задачей. Удалять
  индексы следует только после полного цикла бизнес-операций.
- **`row_number()` и подобные оконные функции в sys schema** — часть MySQL 8.0, но при
  анализе старых дампов с MySQL 5.7 эти представления недоступны.
- **Актуальные представления sys schema** (например, `statements_with_temp_tables`)
  появились в ветке 8.0 и отсутствуют в 5.7; при работе с 5.7 доступен меньший набор.

### Внешние ресурсы

- [MySQL Reference Manual: The MySQL sys Schema](https://dev.mysql.com/doc/refman/8.0/en/sys-schema.html)
- [MySQL Reference Manual: The MySQL Performance Schema](https://dev.mysql.com/doc/refman/8.0/en/performance-schema.html)
- [MySQL Reference Manual: Internal Temporary Table Use in MySQL](https://dev.mysql.com/doc/refman/8.0/en/internal-temporary-tables.html)

### См. также

- **[Анализ медленных запросов](./slow-query-analysis.md)** — логи как источник истории,
  которого нет у P_S.
- **[EXPLAIN и оптимизация](./explain_and_optimization.md)** — план исполнения и разбор
  конкретного запроса.
- **[Индексы в MySQL](../indexing.md)** — `schema_unused_indexes` и
  `schema_redundant_indexes` в контексте проектирования индексов.
- **[Блокировки и дедлоки](../locking_and_deadlocks.md)** — `sys.innodb_lock_waits`
  и `data_lock_waits`.
- **[Движки MySQL: InnoDB](./storage_engines_deep_dive.md)** — buffer pool, undo
  tablespaces, purge, adaptive hash index, временные таблицы.
- **[Управление соединениями](../connection-management.md)** — `processlist`,
  `host_cache` и защита от перегрузки.
- **[Мониторинг MySQL](../monitoring.md)** — экспорт метрик из P_S в Prometheus.