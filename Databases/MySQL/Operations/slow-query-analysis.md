# Анализ медленных запросов MySQL: slow query log, pt-query-digest, разбор логов

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation, Percona Toolkit 3.x

Медленный запрос log (slow query log) — единственный встроенный механизм MySQL, который
даёт историю запросов, а не мгновенный срез. Performance Schema показывает, что происходит
прямо сейчас, но не показывает, что происходило вчера в 03:00, когда была деградация.
Этот файл закрывает именно историческую часть: как включить лог, как его разобрать и
как довести разбор до конкретного индекса или изменения кода.

Партнёры по теме: [Performance Schema и sys schema](./performance-schema-and-sys.md) —
текущий срез вместо истории; [EXPLAIN и оптимизация](./explain_and_optimization.md) —
план исполнения найденного запроса; [Индексы в MySQL](../indexing.md) — добавление
индекса после того, как запрос найден.

## Определения

| Термин | Значение |
| :--- | :--- |
| Slow query log | Лог запросов, время выполнения которых превысило `long_query_time` |
| `Query_time` | Время выполнения оператора в секундах |
| `Lock_time` | Время, потраченное на получение блокировок, в секундах |
| `Rows_sent` | Количество возвращённых клиенту строк |
| `Rows_examined` | Количество прочитанных движком строк |
| Fingerprint | Нормализованный текст запроса с литералами, заменёнными на `?` |
| Digest (в значении MySQL) | Тот же fingerprint, но с привязкой к учётной записи и хосту |
| Replication | Копирование запроса на другую ноду для его повторного выполнения (для оценки влияния) |

Разница между `Query_time` и `Lock_time` — главная подсказка при разборе: если
`Lock_time` составляет заметную долю `Query_time`, проблема в блокировках, а не в плане.

## Базовые концепции

### Анатомия записи лога

```text
# Time: 2026-10-03T12:00:00.000000Z
# User@Host: app[app] @ localhost [local]  Id:   4821
# Query_time: 3.000500  Lock_time: 0.000100 Rows_sent: 1  Rows_examined: 1000000
SET timestamp=1759492800;
SELECT * FROM orders WHERE user_id = 42;
```

| Поле | Как читать |
| :--- | :--- |
| `Time` | Время **начала** выполнения начиная с MySQL 8.0.14. В более старых версиях — время записи в лог, то есть **после** окончания запроса |
| `User@Host` | Учётная запись и хост подключения |
| `Id` | Идентификатор соединения |
| `Query_time` | Полное время выполнения |
| `Lock_time` | Время ожидания блокировок |
| `Rows_sent` | Возвращено клиенту |
| `Rows_examined` | Прочитано движком — главный индикатор неэффективности плана |

При `log_slow_extra = ON` (доступно с MySQL 8.0.14) в заголовок добавляются
`Thread_id`, `Schema`, `QC_hit` и прочие поля — они упрощают корреляцию записей.

Пароли в запросах сервер переписывает, они не попадают в лог в открытом виде.

### Куда пишется лог

`log_output` управляет назначением вывода и допускает комбинацию через запятую:

```sql
SHOW VARIABLES LIKE 'log_output';
-- → FILE, TABLE
```

| Значение | Путь | Особенности |
| :--- | :--- | :--- |
| `FILE` | `slow_query_log_file` | Файловый лог, пригоден для внешних инструментов анализа |
| `TABLE` | Таблица `mysql.slow_log` | Удобно для запросов через SQL, но в 8.0 это таблица на движке CSV: индекса нет, полное сканирование |
| `NONE` | — | Запрет записи |

Практика: `FILE` — основной источник, `TABLE` — только для быстрых ad-hoc запросов.

### Почему одного порога `long_query_time` недостаточно

Значение по умолчанию `long_query_time = 10` — слишком высокое для диагностики
и слишком низкое для объёма логов. Дополнительные фильтры решают остальные задачи:

| Переменная | По умолчанию | Что добавляет в лог |
| :--- | :--- | :--- |
| `long_query_time` | `10` | Порог времени в секундах; допускает дробные значения (микросекундная точность) |
| `min_examined_row_limit` | `0` | Отсекает запросы, прочитавшие меньше указанного числа строк |
| `log_queries_not_using_indexes` | `OFF` | Запросы, не использующие индекс для поиска строк |
| `log_throttle_queries_not_using_indexes` | `60` | Минимальный интервал в секундах между записями таких запросов |
| `log_slow_admin_statements` | `OFF` | Административные операции: `ALTER TABLE`, `ANALYZE TABLE`, `CHECK TABLE`, `CREATE INDEX`, `DROP INDEX`, `OPTIMIZE TABLE`, `REPAIR TABLE` |
| `log_slow_extra` | `OFF` | Дополнительные поля в заголовке записи |
| `log_slow_replica_statements` | `OFF` | Медленные запросы на реплике (с MySQL 8.0.26; раньше `log_slow_slave_statements`) |

Три практических следствия:

1. **`log_queries_not_using_indexes` ротировать нельзя на постоянной основе «включено
   и забыли».** При включённом флаге лог растёт очень быстро: в него попадают все
   запросы, даже быстрые. Рабочий режим — включать на час-другой на время расследования
   либо держать включённым вместе с `log_throttle_queries_not_using_indexes`.
2. **`log_slow_replica_statements` не работает при `binlog_format=ROW`.** Запросы,
   применяемые на реплике из строковых событий, в лог не попадают вовсе, независимо
   от значения переменной. Это часто озадачивает: переменная выставлена, лог на реплике
   пуст.
3. **`min_examined_row_limit` — главный инструмент против шума.** Он отсекает
   тривиальные запросы к таблицам с малым числом строк, не трогая тяжёлые полные
   сканирования.

### Иерархия инструментов анализа

| Инструмент | Что даёт | Когда применять |
| :--- | :--- | :--- |
| `SHOW GLOBAL STATUS LIKE 'Slow_queries'` | Счётчик с момента старта | Быстрая оценка масштаба проблемы |
| `mysql.slow_log` | Запросы из таблицы | Разовый ad-hoc разбор без доступа к файлу |
| `mysqldumpslow` | Топ по времени без агрегации | Файл лога есть, Percona Toolkit нет |
| `pt-query-digest` | Агрегация по fingerprint, сортировка по разным метрикам | Основной инструмент |
| `pt-query-digest --watch` | Сравнение снимков во времени | Отслеживание изменений после релиза |
| `sys.statement_analysis` | Текущий агрегат без чтения логов | Проблема прямо сейчас |

Выбор между сортировкой по суммарному и максимальному времени — тот же, что в
[Performance Schema](./performance-schema-and-sys.md): симптом определяет ключ сортировки.

## Практические сценарии

### Сценарий 1. Оценка масштаба проблемы

```sql
SHOW GLOBAL STATUS LIKE 'Slow_queries';
-- → Variable_name   | Value
-- → Slow_queries    | 154238
```

Счётчик растёт с момента старта сервера. Чтобы получить прирост за интервал:

```bash
mysql -N -B -e "SHOW GLOBAL STATUS LIKE 'Slow_queries'" | awk '{print $2}'   # → 154238
sleep 300
mysql -N -B -e "SHOW GLOBAL STATUS LIKE 'Slow_queries'" | awk '{print $2}'   # → 154901
# → прирост 663 запросов за 5 минут
```

### Сценарий 2. Включение и проверка лога

```ini
[mysqld]
slow_query_log                  = 1
slow_query_log_file             = /var/log/mysql/slow-query.log
log_output                      = FILE
long_query_time                 = 0.5
min_examined_row_limit          = 1000
log_slow_admin_statements       = ON
log_timestamps                  = UTC
```

| Переменная | Допустимые значения | Практический смысл |
| :--- | :--- | :--- |
| `log_timestamps` | `SYSTEM` (по умолчанию), `UTC` | Часовой пояс в метках файлов логов. `UTC` избавляет от путаницы при слиянии логов с нескольких хостов и при анализе инцидентов на границе суток. На табличные логи не влияет |

```bash
sudo mysqld --validate-config
# → проверка синтаксиса конфигурации
sudo systemctl reload mysql     # либо restart, если переменная не динамическая
# → сервер перезагружен/перезапущен

# Валидация после применения: проверка переменных и возможности записи
mysql -e "SELECT @@slow_query_log, @@long_query_time, @@log_output, @@slow_query_log_file;"
```

> **Валидация:** после перезагрузки обязательно выполните Сценарий 12 (валидация настройки slow query log).

### Сценарий 3. Проверка, что лог пишется

```sql
SET SESSION long_query_time = 0;
SELECT SLEEP(2);
-- → подождать 2 секунды

-- Должна появиться свежая запись
mysql -N -B -e "SHOW GLOBAL STATUS LIKE 'Slow_queries'" | awk '{print $2}'
# → значение выросло на 1

tail -3 /var/log/mysql/slow-query.log
# → # Time: 2026-10-03T12:34:56.123456Z
# → # User@Host: root[root] @ localhost []  Id:     7
# → # Query_time: 2.000104  Lock_time: 0.000000 Rows_sent: 1  Rows_examined: 0
# → SET timestamp=1759499696;
# → SELECT SLEEP(2);
```

> **Осторожно:** `SET SESSION long_query_time = 0` логирует вообще всё, включая
> внутренние запросы мониторинга. Возвращайте значение сразу после проверки, не оставляйте
> сессию открытой.

### Сценарий 4. Разовый разбор через таблицу mysql.slow_log

```sql
-- 10 самых долгих запросов за последний час
SELECT
    time_format(start, '%Y-%m-%d %H:%i:%s') AS started,
    user_host,
    query_time,
    lock_time,
    rows_sent,
    rows_examined,
    LEFT(query, 120) AS query_head
FROM mysql.slow_log
WHERE start > NOW() - INTERVAL 1 HOUR
ORDER BY query_time DESC
LIMIT 10;
-- → started            | user_host            | query_time | rows_sent | rows_examined
-- → 2026-10-03 11:42:03 | app[app] @ localhost  |     12.512 |         1 |     4820113
```

Очистка таблицы — обрезка:

```sql
TRUNCATE TABLE mysql.slow_log;
-- → Query OK, 0 rows affected
```

> **Осторожно:** `TRUNCATE` безусловно уничтожает всю историю в таблице. На боевом
> сервере с `log_output = FILE,TABLE` выполнять только подтвердив, что копия логов
> сохранена и файл разобран.

### Сценарий 5. Разбор лога без Percona Toolkit

```bash
# Топ-10 запросов по суммарному времени
mysqldumpslow -s t -t 10 /var/log/mysql/slow-query.log
# → Count: 1240  Time: 9843.11 (63.2%)  Lock: 12.4 (0.08%)  Rows_sent: 1240  Rows_examined: 41938221
# → SELECT * FROM orders WHERE user_id = ?

# Топ-10 запросов по количеству вызовов
mysqldumpslow -s c -t 10 /var/log/mysql/slow-query.log
# → Count: 91203  Time: 812.4 (5.2%)  ...

# Топ-10 запросов по числу прочитанных строк
mysqldumpslow -s r -t 10 /var/log/mysql/slow-query.log
# → Count: 8021  Time: 7120.8 (45.7%)  Rows_sent: 8021  Rows_examined: 512894002
# → SELECT * FROM events WHERE type = ?
```

| Ключ `-s` | Сортировка | Когда применять |
| :--- | :--- | :--- |
| `t` | По суммарному времени | Суммарная нагрузка на сервер |
| `c` | По количеству вызовов | Высокая частота запроса, даже если он быстрый |
| `r` | По числу прочитанных строк | Неэффективные планы и отсутствие индексов |

Дополнительно полезно отфильтровать по паттерну: `-g 'INSERT INTO events'` оставит
только нужные записи.

### Сценарий 6. Агрегация по fingerprint (основной сценарий)

```bash
pt-query-digest --limit 15 /var/log/mysql/slow-query.log
# → (сводный отчёт: Count, Time (%), Calls, Lock (ms), Rows, Sent, Digest)
# → (далее секция "# Fingerprints")
# → (далее секция "# Query fingerprints" с подробной статистикой)
```

Базовый вызов даёт три секции:

1. **Сводная таблица** — топ запросов по выбранной метрике.
2. **`# Fingerprints`** — агрегаты по нормализованному тексту.
3. **`# Query fingerprints`** — детализация по каждому fingerprint, включая репликацию.

Ключевые опции:

| Опция | Назначение |
| :--- | :--- |
| `--limit N` | Сколько строк вывести в отчёте |
| `--sample N` | Выборка 1 из N записей для больших логов |
| `--filter 'cond'` | Фильтр условием, например `--filter 'user=~"^app\."' AND $event !~ /^\s*(SET|COMMIT)/i` |
| `--type {slowlog,genlog,binlog,tcpdump,processlist}` | Формат входных данных |
| `--ratelist N` | Гистограмма времени выполнения для N запросов |
| `--[no]explain` | Попытка получить план исполнения для каждого fingerprint |
| `--[no]fingerprints` | Нормализация литералов |
| `--[no]group-by-fingerprint` | Группировка по нормализованному тексту |
| `--review D=db,t=table` | Сохранение fingerprint в таблицу ревью (обычно `percona_schema.reviews`) |
| `--history D=db,t=table` | Сохранение истории запросов (обычно `percona_schema.history`) |
| `--watch` | Непрерывный опрос файла с отчётом о новых запросах |
| `--output file` | Запись отчёта в файл |
| `--format {brief,json,csv,slowlog,general}` | Формат отчёта; по умолчанию `brief` |
| `--[no]utc-time` | Время в UTC вместо локального |

### Сценарий 7. Сравнение снимков до и после релизы

Ключевой сценарий регулярной эксплуатации: убедиться, что оптимизация не ухудшила
другие запросы.

```bash
pt-query-digest --output /var/log/mysql/qd_before.txt /var/log/mysql/slow-query.log
# → отчёт сохранён

# ... выкатка изменения, 15 минут наблюдения ...

pt-query-digest --output /var/log/mysql/qd_after.txt /var/log/mysql/slow-query.log

diff /var/log/mysql/qd_before.txt /var/log/mysql/qd_after.txt
# → 32c32
# → < 8.12%  1284  4:52.1  SELECT * FROM orders WHERE user_id = ?
# → ---
# → 0.91%  1244  0:31.0  SELECT * FROM orders WHERE user_id = ?
```

Снижение доли с 8% до 0.9% — доказательство, что изменение сработало.

### Сценарий 8. Доведение запроса до индекса

```bash
pt-query-digest --limit 1 --explain /var/log/mysql/slow-query.log
# → разбор получает план исполнения для каждого fingerprint (требует соединения с сервером)
```

Дальнейшая цепочка: вставить текст запроса в
[EXPLAIN и оптимизацию](./explain_and_optimization.md), получить план, проверить,
используется ли индекс, и применить изменения из
[Индексов в MySQL](../indexing.md).

Для production-критичных изменений сначала проверьте, что изменение не ломает другие
запросы, — [Online Schema Change](./online-schema-change.md).

### Сценарий 9. Разовая проверка гипотезы: сколько строк читает запрос

Быстрый способ проверить, является ли запрос источником нагрузки, не читая лог:

```sql
-- Сбросить счётчик и выполнить запрос
FLUSH STATUS;
SELECT * FROM events WHERE type = 'click';   -- подставить свой запрос
SHOW SESSION STATUS LIKE 'Handler_read%';
-- → Handler_read_rnd_next | 1048576   ← строк прочитано полным сканированием
-- → Handler_read_key      | 12
```

Резкое расхождение `Handler_read_rnd_next` и `Handler_read_key` означает отсутствие
подходящего индекса.

Ограничение сессии по времени выполнения на сервере 8.0:

```sql
SET SESSION max_execution_time = 5000;  -- мс, применяется к SELECT
SELECT * FROM huge_table WHERE ...;
-- → ERROR 3024 (HY000): Query execution was interrupted, maximum statement execution time exceeded
```

`max_execution_time` действует только на `SELECT`. Это защита от случайного
дорогого запроса в интерактивной сессии, а не механизм управления нагрузкой в проде.

### Сценарий 10. Ротация логов

```ini
[mysqld]
slow_query_log_file    = /var/log/mysql/slow-query.log
```

```bash
# Переключение на новый файл без рестарта
mysql -e "SET GLOBAL slow_query_log_file = '/var/log/mysql/slow-query.log.$(date +%F)'"
# → Если файл уже открыт, он закрывается и открывается новый

# Ротация по logrotate
/var/log/mysql/slow-query.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    create 0640 mysql mysql
    postrotate
        /usr/bin/mysqladmin flush-logs > /dev/null
    endscript
}
```

> **Осторожно:** `logrotate` без `postrotate` с `flush-logs` приведёт к тому, что
> сервер продолжит писать в переименованный файл, и данные окажутся в файле с
> неправильным именем. Файл должен быть доступен процессу `mysqld` на запись.

### Сценарий 11. Мониторинг: медленный запрос log на реплике

```sql
SELECT user, host, start, query_time, rows_examined, LEFT(query, 100) AS q
FROM mysql.slow_log
WHERE start > NOW() - INTERVAL 15 MINUTE
ORDER BY query_time DESC
LIMIT 5;
```


**Особенность:** При `binlog_format = ROW` SQL-текст запросов не воспроизводится на реплике из событий ROW — в этом случае `log_slow_replica_statements` часто не фиксирует медленные запросы, применяемые репликой. Для диагностики нагрузки на реплике в таком режиме предпочтительно использовать [Performance Schema](./performance-schema-and-sys.md) (в частности, агрегаты по дайджестам), а не slow query log.


> **Ограничение:** при `binlog_format = ROW` переменная `log_slow_replica_statements`
> не действует. Для наблюдения за медленными запросами на реплике используйте
> [Performance Schema](./performance-schema-and-sys.md), а не slow query log.



### Сценарий 12. Валидация настройки slow query log

**Цель:** убедиться, что конфигурация корректно применена и лог работает в ожидаемом режиме.

**Проверка переменных:**

```sql
SHOW GLOBAL VARIABLES LIKE 'slow_query%';
SHOW GLOBAL VARIABLES LIKE 'long_query_time';
SHOW GLOBAL VARIABLES LIKE 'log_output';
SHOW GLOBAL VARIABLES LIKE 'min_examined_row_limit';
SHOW GLOBAL VARIABLES LIKE 'log_slow_admin_statements';
SHOW GLOBAL VARIABLES LIKE 'log_queries_not_using_indexes';
SHOW GLOBAL VARIABLES LIKE 'log_throttle_queries_not_using_indexes';
```

**Проверка записи лога (файловый режим):**

```bash
test -f "$(mysql -N -B -e "SELECT @@slow_query_log_file")" && echo "OK" || echo "MISSING"
ls -lh "$(mysql -N -B -e "SELECT @@slow_query_log_file")"
```

**Проверка прав доступа:**

```bash
stat -c "%a %U:%G" "$(mysql -N -B -e "SELECT @@slow_query_log_file")"
# Ожидаем: 0640 mysql:mysql (или эквивалент системной учётной записи)
```

**Контроль роста лога:**

```bash
du -sh "$(mysql -N -B -e "SELECT @@slow_query_log_file")"
```

> **Примечание:** При использовании `log_output = TABLE` валидация осуществляется через `SELECT COUNT(*) FROM mysql.slow_log;`.


## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Лог пуст, `Slow_queries` растёт | Запись идёт в `TABLE`, а не в файл | `SHOW VARIABLES LIKE 'log_output'`; читать `mysql.slow_log` |
| Метки времени не совпадают с `NOW()` | В лог пишется локальный часовой пояс | Установить `log_timestamps = UTC` |
| Лог на реплике пуст при включённом флаге | Используется `binlog_format = ROW` | Переключить формат или использовать P_S |
| Лог растёт на десятки гигабайт в сутки | Включён `log_queries_not_using_indexes` без троттлинга | Уменьшить `log_throttle_queries_not_using_indexes`, добавить `min_examined_row_limit` |
| `pt-query-digest` падает с ошибкой подключения | Требуется DSN для `--explain` или `--review` | Указать `D=db,t=table,host=...,user=...` или убрать `--explain` |
| `pt-query-digest` зависает на большом логе | Обработка десятков гигабайт | Добавить `--sample 100` или предварительно разрезать лог по времени |
| В отчёте много похожих запросов | Нормализация не сработала для сложных выражений | Проверить `--[no]fingerprints`; вручную сгруппировать по шаблону |
| `mysqldumpslow` возвращает 0 строк | Лог только что переключён и ещё не сброшен | `FLUSH SLOW LOGS;` и повторить |
| Рекомендации `pt-query-digest` не воспроизводятся | Fingerprint содержит плейсхолдеры и литералы | Подставить реальные значения; для запросов с подсказками проверить, не меняется ли результат |

| `FLUSH SLOW LOGS` не создаёт новый файл | Сервер продолжает писать в старый дескриптор | Проверьте `slow_query_log_file`: после `FLUSH SLOW LOGS` файл переименовывается только при ротации через `mysqladmin flush-logs` в связке с logrotate. MySQL не всегда закрывает файл мгновенно — убедитесь, что процесс `mysqld` имеет права на создание нового файла в каталоге |
| Дробные значения `long_query_time` игнорируются | Версия MySQL слишком старая / формат конфигурации | В MySQL 8.0 `long_query_time` поддерживает микросекундную точность. Убедитесь, что в my.cnf используется число с десятичной точкой (например, `0.50`) и нет пробелов/неверного формата |
| `log_slow_extra = ON` не добавляет поля | Переменная не динамическая в окружении / версия ниже 8.0.14 | `log_slow_extra` доступен с MySQL 8.0.14. Требуется перезапуск, если не поддерживается динамическое изменение. Проверьте `SELECT @@version;` |
| Медленные DDL/DML админ-операции не попадают в лог | `log_slow_admin_statements = OFF` | Включите `log_slow_admin_statements = ON` для отслеживания `ALTER TABLE`, `ANALYZE TABLE`, `CHECK TABLE`, `CREATE INDEX`, `DROP INDEX`, `OPTIMIZE TABLE`, `REPAIR TABLE` |
| После изменения `slow_query_log_file` лог продолжает писаться в старый файл | Файл уже открыт файловым дескриптором | `SET GLOBAL slow_query_log_file = ...` заставляет MySQL закрыть старый и открыть новый файл. Убедитесь, что новый путь существует и доступен для `mysqld`. При ошибке сервер может продолжить писать в старый файл — проверьте логи ошибок MySQL |



## Операции и обслуживание

### Мониторинг и алертинг (DevOps/SRE)

Рекомендуемые метрики для наблюдения за slow query log:

| Метрика | Источник | Порог (ориентир) | Действие |
| :--- | :--- | :--- | :--- |
| `Slow_queries` (прирост/мин) | `SHOW GLOBAL STATUS` / mysqld_exporter (`mysql_global_status_slow_queries`) | > 50–100/мин (зависит от нагрузки) | Проверить топ запросов за интервал |
| Доля медленных запросов | Slow_queries / Questions (за интервал) | > 1–5% | Анализировать pt-query-digest за окном |
| Средний `Query_time` по топу | pt-query-digest (сводка) | > 0.5–1.0с (OLTP) | Выявить проблемные fingerprint |
| `Rows_examined` / `Rows_sent` | pt-query-digest | > 10–100x | Отсутствие/неэффективность индексов |
| Рост slow query log (ГБ/ч) | Файловая система | > 1 ГБ/ч | Настроить ротацию, повысить `long_query_time` или `min_examined_row_limit`, использовать троттлинг |

**Рекомендуемая практика алертинга:** алертить по *приросту* `Slow_queries` за 5–15 минут, а не по абсолютному значению.

### Ротация и хранение логов

- **Ротация:** использовать `logrotate` с `postrotate` + `mysqladmin flush-logs` (см. Сценарий 10).
- **Хранение:** хранить сжатые архивы slow query log не менее 7–30 дней (в зависимости от регуляторных/операционных требований). Никогда не хранить чувствительные данные в открытом виде дольше необходимого.
- **Артефакты:** сохранять отчёты `pt-query-digest` как артефакты релиза/деплоя для сопоставления до/после изменений.

### Резервное копирование и защита доступа

- Slow query log может содержать чувствительные данные в `WHERE`-условиях. Обеспечить такие же или более строгие права доступа, как у конфиденциальных таблиц.
- Не передавать логи третьим лицам в сыром виде без предварительной нормализации (fingerprint-анализ) и вырезки чувствительных данных.


## Лучшие практики

- **Держать `long_query_time` ниже, чем кажется нужным.** Значение `0.5`–`1.0` для OLTP
  даёт полезный объём; `10` по умолчанию пропускает почти всё интересное.
- **Всегда ставить `min_examined_row_limit`.** Это единственный способ получить полезный
  лог без троттлинга.
- **Фильтровать анализ по учётной записи и хосту.** Мониторинг, бэкапы и репликация
  создают шум, который вытесняет прикладные запросы из топа.
- **Анализировать fingerprint, а не сырой текст.** Именно агрегация по нормализованному
  тексту превращает миллион строк лога в двадцать строков actionable-вывода.
- **Хранить `pt-query-digest --output` как артефакт релиза.** Это доказательная база для
  разборов производительности.
- **Пароли не пишутся в лог в открытом виде**, но текст запроса может содержать
  персональные данные из `WHERE`-условий — файл лога требует такого же режима доступа,
  как и сама таблица.

## Дополнительная информация

### Внешние ресурсы

- [MySQL Reference Manual: The Slow Query Log](https://dev.mysql.com/doc/refman/8.0/en/slow-query-log.html)
- [MySQL Reference Manual: Using System Variables](https://dev.mysql.com/doc/refman/8.0/en/using-system-variables.html)
- [Percona Toolkit: pt-query-digest](https://docs.percona.com/percona-toolkit/pt-query-digest.html)

### См. также

- **[Performance Schema и sys schema](./performance-schema-and-sys.md)** — текущий срез
  запросов без чтения логов.
- **[EXPLAIN и оптимизация](./explain_and_optimization.md)** — следующий шаг после
  обнаружения медленного запроса.
- **[Индексы в MySQL](../indexing.md)** — добавление индекса и безопасное создание
  индекса на большой таблице.
- **[Online Schema Change](./online-schema-change.md)** — применение найденного изменения
  без простоя.
- **[Диагностика дисковых узких мест](../../db_disk_bottleneck_troubleshooting.md)** —
  тот же анализ, но с позиции инфраструктуры.
- **[Конфигурация MySQL](../configuration.md)** — блок `log_slow_extra` и пороги.