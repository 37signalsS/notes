# Диагностический runbook MySQL: симптом, команда, причина

**Актуально для:** MySQL 8.0.x (legacy — EOL апрель 2026) / 8.4 LTS / 9.x Innovation

Справочник для разбора инцидентов по принципу «симптом → первая команда → вероятная
причина». Не заменяет детальные разборы в специализированных файлах, а связывает их:
задача runbook — за минуту прийти к правильному файлу и правильной команде.

Партнёры по теме: [Emergency Recovery](./backup_and_recovery/emergency_recovery.md) —
повреждение данных; [Блокировки и дедлоки](./locking_and_deadlocks.md) — 1205 и 1213;
[Управление соединениями](./connection-management.md) — 1040; [Performance Schema и sys
schema](./Operations/performance-schema-and-sys.md) — инструментация диагностики.

## Определения

| Термин | Значение |
| :--- | :--- |
| Runbook | Документ, связывающий наблюдаемый симптом с диагностическими командами |
| First responder | Тот, кто разбирает инцидент первым; ему нужны команды, а не объяснения |
| Error log | Основной журнал сервера; место, где всегда ищут первопричину |
| Latency | Время ответа; в MySQL измеряется через wait events |
| Saturation | Степень загрузки ресурса, при которой он перестаёт справляться |

## Базовые концепции

### Порядок разбора: не начинать с оптимизации

```
Симптом: «MySQL тормозит»
  │
  ├─ 1. Воспроизводится ли? (тест извне против внутреннего SELECT 1)
  ├─ 2. Где слой: приложение / сеть / процесс mysqld / диск / память
  ├─ 3. Что растёт: Connections, Threads_running, CPU, iowait, Slow_queries
  └─ 4. Только затем: планы запросов, индексы, настройки
```

Практическое правило: **прежде чем читать `EXPLAIN`, нужно установить, что именно
тормозит**. Обычная картина — приложение ждёт соединение, а не запрос; или запрос
выполняется 3 мс, а latency 2 с из-за ожидания в очереди на ввод-вывод. Оптимизация
запроса в такой ситуации бесполезна.

### Первый сбор данных при инциденте

Собирайте всё одновременно и **до** любых изменений: после перезапуска следы
исчезают.

```sql
CALL sys.diagnostics();
-- → Полный срез: версии, переменные, статусы, P_S, операции, блокировки, память
```

```sql
-- Минимальный ручной срез, если процедура недоступна
SHOW GLOBAL STATUS;
SHOW GLOBAL VARIABLES;
SHOW ENGINE INNODB STATUS\G
SHOW REPLICA STATUS\G
SELECT * FROM information_schema.PROCESSLIST;
```

```bash
# Системный уровень
top -b -n1 | head -20              # CPU и load average
vmstat 1 5                         # iowait, run queue, free memory
iostat -x 1 3                      # %util, await, aqu-sz по дискам
free -h                            # доступная память и swap
df -h /var/lib/mysql               # свободное место
ss -tanp | grep 3306 | wc -l       # число TCP-соединений

# Error log — искать последнее, что произошло перед инцидентом
sudo tail -200 /var/log/mysql/error.log
```

### Что собирать перед перезапуском сервера

| Что | Зачем |
| :--- | --- |
| `SHOW ENGINE INNODB STATUS\G` | Транзакции, блокировки, последний дедлок, состояние buffer pool |
| `SHOW REPLICA STATUS\G` | Позиция в binlog, ошибки применения |
| `SHOW BINARY LOGS` | Какие журналы есть; нужно ли дочитывать |
| `information_schema.PROCESSLIST` | Кто выполняет запрос прямо сейчас |
| `SELECT * FROM sys.statement_analysis LIMIT 20` | Топ запросов по суммарной задержке |
| Error log целиком | Причина, а не следствие |
| Состояние табличных файлов | При подозрении на повреждение — `ls -l` на `datadir` |

> **Осторожность:** перезапуск неисправного сервера уничтожает данные для
> расследования. Если есть подозрение на повреждение данных, сначала сделайте
> копию `datadir` — порядок действий описан в
> [Emergency Recovery](./backup_and_recovery/emergency_recovery.md).

## Предварительные требования

Перед началом диагностики требуется:

- **Доступ к серверу MySQL** с привилегиями `PROCESS`, `RELOAD`, `SUPER` (или
  `SYSTEM_VARIABLES_ADMIN`) для диагностики, снятия блокировок и снятия статуса
  read-only.
- **Системный доступ** (root или sudo) к хосту — для чтения error log,
  управления процессами, работы с файловой системой и остановки `mysqld` для
  `innochecksum`.
- **Клиентская утилита `mysql`** версии 8.0+ (8.4+ предпочтительно — поддерживает
  административный порт 33062 для подключения при `super_read_only`).
- **Схема `sys`** в базе (входит в комплект MySQL 8.0+) — требуется для
  процедур `sys.diagnostics()` и представлений `sys.processlist`, `sys.session`,
  `sys.statement_analysis`. Проверить наличие:

  ```sql
  SELECT COUNT(*) AS has_sys
  FROM information_schema.schemata
  WHERE schema_name = 'sys';
  -- → has_sys | 1
  ```

- **Инструменты ОС**: `procps` (`ps`, `top`), `sysstat` (`vmstat`, `iostat`),
  `iproute2` (`ss`), `coreutils` (`df`, `du`).
- **Понимание контекста**: текущий уровень изоляции транзакций (в MySQL 8 по
  умолчанию `REPEATABLE READ`), типы блокировок InnoDB (shared/exclusive/MDL),
  роль сервера в топологии репликации (source/replica).

  super_read_only=OFF — требует привилегии `SYSTEM_VARIABLES_ADMIN`. На репликах
  с `super_read_only = ON` даже `root` не может выполнить запись. Используйте
  административный порт 33062 либо временно снимайте статус:
  `SET GLOBAL super_read_only = OFF;` — фиксируйте в инцидент-репорте.

## Практические сценарии

### Сценарий 1. Сервер не запускается

```bash
# 1. Статус службы
sudo systemctl status mysql
# → mysql.service - MySQL Community Server
# →    Loaded: loaded (/lib/systemd/system/mysql.service; enabled)
# →   Active: failed (Result: exit-code) since Sat 2026-10-03 11:42:03 MSK
# →  Main PID: 1234 (code=exited, status=1/FAILURE)

# 2. Лог запуска
sudo journalctl -u mysql -n 100 --no-pager
# → mysqld[1234]: [ERROR] [MY-013169] [Server] Failed to set up O_DIRECT on file ./ibdata1

# 3. Error log
sudo tail -50 /var/log/mysql/error.log
```

| Сообщение | Причина | Решение |
| :--- | :--- | :--- |
| `unknown variable 'X'` | Удалённый или переименованный параметр в `my.cnf` | Найти и удалить параметр; перечень удалённых — [Обслуживание и обновления](./maintenance-and-upgrades.md) |
| `Can't create/write to file` | Недостаточно места или неверные права | `df -h`; проверить права и SELinux/AppArmor |
| `Table 'mysql.user' doesn't exist` | Повреждённый `mysql`-schemaspace | Аварийный режим — [Emergency Recovery](./backup_and_recovery/emergency_recovery.md) |
| `InnoDB: corruption in page` | Повреждение табличных файлов | [Emergency Recovery](./backup_and_recovery/emergency_recovery.md), сценарий определения масштаба |
| `setrlimit` / `Max open files` | Слишком низкий лимит дескрипторов | Поднять `LimitNOFILE` в unit-файле systemd |
| `Address already in use` | Порт занят другим процессом | `ss -ltnp | grep 3306` |
| `Plugin 'X' reported: init function failed` | Плагин несовместим с версией | Проверить версию плагина; для удалённых компонентов — удалить из `my.cnf` |

Перед правкой `my.cnf` всегда проверяйте синтаксис:

```bash
sudo mysqld --validate-config
# → ошибки выводятся в stderr; пустой вывод — ошибок нет
```

### Сценарий 2. Клиент не может подключиться

```bash
# 1. Отвечает ли порт
nc -zv db01.internal 3306
# → nc: connect to db01.internal port 3306 (tcp) failed: Connection refused

# 2. На самом хосте по сокету
sudo mysql -S /var/run/mysqld/mysqld.sock -u root -p -e "SELECT 1"
# → 1
```

Различие между двумя результатами локализует проблему: сокет работает, сеть — нет.

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `ERROR 2003 (HY000): Can't connect` | Порт закрыт, неверный хост или `bind_address` | `ss -ltnp`, firewall, `bind_address` |
| `ERROR 2006 (HY000): MySQL server has gone away` | Соединение закрыто сервером: таймаут или `KILL` | `wait_timeout`, `max_allowed_packet`, `max_execution_time` |
| `ERROR 2013 (HY000): Lost connection to MySQL server during query` | Обрыв во время выполнения запроса | Проверить `Aborted_clients`, timeout клиента, разрывы сети |
| `ERROR 1045 (28000): Access denied` | Неверные учётные данные или хост | `SHOW GRANTS`, `mysql.user.host` |
| `ERROR 1130 (HY000): Host 'X' is not allowed to connect` | Нет подходящего `GRANT` для хоста | Выдать привилегию для конкретного хоста или диапазона |
| `ERROR 1049 (42000): Unknown database` | База не создана или удалена | Проверить `SHOW DATABASES` |
| `ERROR 2005 (HY000): Unknown MySQL server host` | Ошибка DNS или сетевого маршрута | `dig db01.internal`; рассмотреть `skip_name_resolve` |

### Сценарий 3. Отказы соединений

Подробно — [Управление соединениями](./connection-management.md).

```sql
SHOW STATUS WHERE Variable_name IN
  ('Threads_connected','Threads_running','Max_used_connections',
   'Connection_errors_max_connections','Aborted_connects');
```

`ERROR 1040` в логе приложения при нормальном CPU означает исчерпание соединений, а не
перегрузку: слоты заняты простаивающими сессиями.

### Сценарий 4. Отказы доступа

```sql
-- Кто и откуда подключается успешно
SELECT user, host, COUNT(*) AS connections
FROM information_schema.PROCESSLIST
GROUP BY user, host ORDER BY connections DESC LIMIT 15;

-- Неудачные попытки входа
SELECT USER, HOST, FAILURE_COUNT, MINIMUM_FAILURES
FROM INFORMATION_SCHEMA.CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS
ORDER BY FAILURE_COUNT DESC LIMIT 10;
```

Ошибки `Access denied` при верном пароле и правильном хосте чаще всего означают:

1. Задержку от `connection_control` после серии неудачных попыток.
2. Учётную запись, созданную с ограниченным списком хостов.
3. Устаревший метод аутентификации клиента: в MySQL 8.4 `mysql_native_password`
   отключён по умолчанию, а в 9.x удалён — см. [Безопасность MySQL](./security.md).

### Сценарий 5. Высокая загрузка CPU

```sql
-- Что выполняется сейчас
SELECT * FROM sys.processlist WHERE command = 'Query' ORDER BY time DESC LIMIT 15;

-- Триггерные процессы
SELECT name, type, thread_id FROM performance_schema.threads
WHERE name NOT LIKE 'worker%' AND type = 'BACKGROUND' LIMIT 20;

-- Кто грузит сервер (суммарно)
SELECT user, SUM(total_latency)/1e9 AS total_s, COUNT(*) AS distinct_digests
FROM sys.statement_analysis GROUP BY user ORDER BY total_s DESC LIMIT 10;
```

| Диагноз | Признак | Куда идти |
| :--- | :--- | :--- |
| Тяжёлый запрос | `sys.statement_analysis` с большой долей | [Анализ медленных запросов](./Operations/slow-query-analysis.md) |
| Много коротких запросов | Высокий `Queries`, малый `max_latency` | Пул и батчинг на стороне приложения |
| Ожидание метаданных | Высокая доля `metadata/sql` | Долгий запрос или `ALTER`; см. ниже |
| Активный поиск дедлоков | Высокий `CPU` при низком `iowait` и отсутствии тяжёлых запросов | Высокая конкуренция за блокировки: `innodb_deadlock_detect = OFF` снижает эту нагрузку — см. [Блокировки и дедлоки](./locking_and_deadlocks.md) |
| Раздутый buffer pool / сортировки | Высокий `iowait` + временные таблицы | [Движки MySQL: InnoDB](./Operations/storage_engines_deep_dive.md), [EXPLAIN и оптимизация](./Operations/explain_and_optimization.md) |

### Сценарий 6. Высокая latency при нормальном CPU

```sql
-- Топ ожиданий
SELECT event_name, count_star, ROUND(sum_timer_wait/1e12, 3) AS total_s
FROM performance_schema.events_waits_summary_global_by_event_name
ORDER BY sum_timer_wait DESC LIMIT 15;

-- Дисковый ввод-вывод по таблицам
SELECT * FROM sys.innodb_buffer_stats_by_table ORDER BY hit_rate ASC LIMIT 15;
```

| Преобладающий wait event | Диагноз |
| :--- | :--- |
| `socket/sql` | Ожидание данных от клиента: проблема в приложении или сети |
| `metadata/sql` | Ожидание MDL: долгий запрос или незавершённый `ALTER` |
| `transaction/sql` | Блокировки строк |
| `innodb_buffer_pool/page_*` | Промахи buffer pool, чтение с диска |
| `thread/sql` | Ожидание CPU: перегрузка или избыточная конкуренция |

Разделение «медленно из-за БД» и «медленно из-за клиента или сети» делается сравнением
времени на стороне клиента с временем исполнения на стороне сервера:

```sql
-- Серверная сторона: замер одной и той же операции
SET SESSION profiling = 0;                     -- отключить профилирование, если было включено
SELECT NOW(6) AS t0;
SELECT COUNT(*) FROM shop.orders WHERE customer_id = 42;
SELECT NOW(6) AS t1;
-- t1 - t0 = 00:00:00.003712  → сервер исполнял запрос 3.7 мс
```

```bash
# Клиентская сторона: тот же запрос с внешним таймером
/usr/bin/time -f "wall=%e s" mysql -h db01.internal -u app -p -e \
  "SELECT COUNT(*) FROM shop.orders WHERE customer_id = 42" 2>&1 | tail -2
# wall=1.842 s client   → 1.8 с вне сервера: сеть, DNS, TLS, ожидание в пуле соединений
```

Если `wall` многократно больше серверного времени, проблема не в MySQL. Если оба
значения велики — возвращаться к wait events и плану запроса.

```sql
-- То же изнутри для произвольного соединения без клиентских потерь
SELECT * FROM sys.session WHERE conn_id = 9012\G
SELECT * FROM sys.statement_analysis WHERE query LIKE '%orders%'\G
```

### Сценарий 7. Диск заполнен

```bash
df -h /var/lib/mysql
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/vg0/data   500G  487G   13G  98% /var/lib/mysql

du -sh /var/lib/mysql/* | sort -h | tail -10
# → 210G  /var/lib/mysql/analytics
-- → 180G  /var/lib/mysql/shop
```

```sql
-- Кто занимает место в InnoDB
SELECT name,
       ROUND(data_length/1024/1024/1024, 1)  AS data_gb,
       ROUND(index_length/1024/1024/1024, 1) AS index_gb,
       ROUND(data_free/1024/1024/1024, 1)   AS free_gb
FROM information_schema.TABLES
WHERE table_schema NOT IN ('mysql','information_schema','performance_schema','sys')
ORDER BY data_length + index_length DESC
LIMIT 15;
-- → name              | data_gb | index_gb | free_gb
-- → shop/orders       |   412.3 |     88.1 |   124.0  ← DATA_FREE: кандидат на OPTIMIZE
-- → shop/events       |   198.7 |      2.4 |     1.2

-- Ошибки в error log
sudo grep -iE "no space|disk full|errno 28" /var/log/mysql/error.log | tail -20
```

Действия по приоритету:

1. **Освободить место немедленно** — очистить логи, временные таблицы, старые бэкапы.
2. **`DELETE` не освобождает место.** Он лишь помечает страницы; освобождение даёт
   `OPTIMIZE TABLE` (пересборка) или удаление таблицы. Порядок и риски —
   [Обслуживание и обновления](./maintenance-and-upgrades.md).
3. **Расширить файловую систему**, если LVM/ZFS это позволяет.
4. Проверить `innodb_data_file_path` и наличие свободного места для расширения
   табличных пространств.

### Сценарий 8. `ERROR 1114: Table is full`

Таблица упёрлась не в диск, а в предел размера табличного пространства.

| Параметр | Значение |
| :--- | --- |
| `innodb_page_size = 4KB` | 16 TB |
| `innodb_page_size = 8KB` | 32 TB |
| `innodb_page_size = 16KB` | 64 TB |
| `innodb_page_size = 32KB` | 128 TB |
| `innodb_page_size = 64KB` | 256 TB |

```sql
SELECT @@innodb_page_size;
-- → innodb_page_size = 16384

SELECT NAME, ROW_FORMAT FROM INFORMATION_SCHEMA.INNODB_TABLES
WHERE NAME = 'shop/huge_table';
```

Разбор `ERROR 1114` требует разграничения: нехватка дискового пространства на файловой
системе (сценарий 7) и исчерпание лимита табличного пространства (этот сценарий) —
разные проблемы с разными решениями. Максимальный размер табличного пространства
равен максимальному размеру таблицы.

### Сценарий 9. Повреждение таблицы или страниц

Признаки: `ERROR 1030 Got error 28 from storage engine`,
`ERROR 1267` в данных, сообщения `Corruption: page ... checksum ...` в error log.
Ошибка `28` — это `ENOSPC` операционной системы, а не код MySQL.

```sql
-- Проверить подозрительные таблицы
CHECK TABLE shop.broken_table QUICK;
-- → +------------------+-------+------------+----------+----------+
-- → | Table            | Op    | Msg_type   | Msg_text | Corr_idx |
-- → +------------------+-------+------------+----------+----------+
-- → | shop.broken_table | check | status     | OK       |     NULL |
-- → +------------------+-------+------------+----------+----------+
--   либо
-- → | shop.broken_table | check | error      | 119      |     idx_c |
--   119 = ER_NOT_KEY_PART / повреждение индекса: сообщение приходит в Corr_idx

-- Полная проверка всех страниц (блокирует таблицу)
CHECK TABLE shop.broken_table EXTENDED;
```

Ограничения `CHECK TABLE`, о которых нужно знать заранее:

- `FAST` **игнорируется для InnoDB** (работает только с MyISAM).
- `QUICK` не проверяет корректность связей индексов, поэтому способен пропустить часть
  повреждений.
- `EXTENDED` — полная проверка, но с блокировкой таблицы.
- `CHECK TABLE` **не проверяет заголовок `.ibd`** — первые три страницы. Если
  повреждение затрагивает только заголовок, `CHECK TABLE` его не увидит.
- `REPAIR TABLE` для InnoDB **не поддерживается**. `mysqlcheck` умеет проверять InnoDB,
  но не чинит; `REPAIR TABLE` работает только с MyISAM.
- `CHECK TABLE` не может обнаружить все виды повреждений, а «повреждение страницы» иногда
  означает повреждение кэша файлов ОС, а не данных на диске.

Полная проверка файла табличного пространства — утилитой `innochecksum`:

```bash
# ВАЖНО: innochecksum нельзя запускать на файле, открытом сервером.
# На работающем сервере получается ошибка "Unable to lock file".
# Сначала остановить mysqld, либо проверять копию файла.

sudo systemctl stop mysql
sudo innochecksum --page-type-summary /var/lib/mysql/shop/broken_table.ibd
# → File::/var/lib/mysql/shop/broken_table.ibd
# → ================PAGE TYPE SUMMARY==============
# → #PAGE_COUNT PAGE_TYPE
# → ===============================================
# →         1024        Index page
# →           31        Inode page
# →            1        File Space Header
# →            1        Insert buffer bitmap
# → ===============================================

# Контрольные суммы всех страниц; по умолчанию innochecksum прерывается
# на первом несовпадении
sudo innochecksum /var/lib/mysql/shop/broken_table.ibd
# → page 8123: Checksum error

# Продолжить проверку, допустив N расхождений
sudo innochecksum --allow-mismatches=100 /var/lib/mysql/shop/broken_table.ibd

# Сколько всего страниц в файле
sudo innochecksum --count /var/lib/mysql/shop/broken_table.ibd
# → 1057
sudo systemctl start mysql
```

Что делает утилита: читает файл табличного пространства, вычисляет контрольную сумму
каждой страницы, сравнивает её с сохранённой и сообщает о несовпадениях. Смысл применения
в том, что **расхождение контрольной суммы заставит InnoDB аварийно остановить работающий
сервер**, поэтому проверять файл утилитой безопаснее, чем ждать, пока сервер в продакшене
наткнётся на повреждённую страницу.

Рекомендуемая реакция при найденных расхождениях: восстановить табличное пространство из
бэкапа либо запустить сервер и выгрудить данные таблиц утилитой `mysqldump`.

Дополнительно — метаданные таблицы: `INFORMATION_SCHEMA.INNODB_TABLES.FLAG` содержит
битовую информацию о формате таблицы и её состоянии, включая отметку о повреждении.
Документация не публикует разбивку по битам, поэтому опираться следует на `CHECK TABLE`
и `innochecksum`, а не на ручной разбор `FLAG`:

```sql
SELECT TABLE_ID, NAME, FLAG, SPACE, ROW_FORMAT
FROM INFORMATION_SCHEMA.INNODB_TABLES
WHERE NAME = 'shop/broken_table';
-- → TABLE_ID: 4711
-- → NAME:     shop/broken_table
-- → FLAG:     33          ← в примерах документации 33 соответствует Dynamic, 1 — Compact
-- → SPACE:    57          ← 0 = системное пространство, иначе file-per-table или general
-- → ROW_FORMAT: Dynamic
```

InnoDB дублирует отметку о повреждении в redo log (чтобы она пережила падение) и в
служебную системную таблицу на каждом контрольной точке; при восстановлении флаги
читаются из обоих источников и объединяются.

Порядок действий и метод `innodb_force_recovery` разбираются в
[Emergency Recovery](./backup_and_recovery/emergency_recovery.md). Ключевое правило:
не запускать `REPAIR TABLE` и `OPTIMIZE TABLE` до того, как определён масштаб
повреждения — перезапись данных необратима.

### Сценарий 10. Инцидент из-за зависшего `ALTER TABLE`

Метаданные заблокированы: сервер не отвечает ни на запросы, ни на `ALTER`.

```sql
-- Кто держит блокировку метаданных
SELECT * FROM sys.schema_table_lock_waits\G
-- → waiting_pid: 9012
-- → waiting_query: SELECT * FROM shop.orders WHERE status = 'new'
-- → blocking_pid: 8871
-- → blocking_query: ALTER TABLE shop.orders ADD COLUMN channel VARCHAR(32), ALGORITHM=COPY

-- Убить блокирующую сессию
KILL QUERY 8871;
-- → Query OK, 0 rows affected
```

```bash
# Долгий ALTER — в error log
sudo grep -E "ALTER TABLE|InnoDB: Online DDL" /var/log/mysql/error.log | tail -10
```

Профилактика — задавать таймаут ожидания метаданных **до** `ALTER`:

```sql
SET SESSION lock_wait_timeout = 30;
-- → Query OK, 0 rows affected

ALTER TABLE shop.orders ADD INDEX idx_channel (channel), ALGORITHM=INPLACE, LOCK=NONE;
-- → при превышении 30 секунд: ERROR 1205 (HY000): Lock wait timeout exceeded; try restarting transaction
```

`lock_wait_timeout` по умолчанию превышает любой разумный срок, поэтому без явной
установки `ALTER` может ждать очень долго. Подробнее — [Online Schema Change](./Operations/online-schema-change.md).

### Сценарий 11. Повторяющиеся ошибки записи

```sql
SELECT query, error, warn, exec_count, total_latency
FROM sys.statements_with_errors_or_warnings
WHERE error <> 0
ORDER BY error DESC LIMIT 20;
-- → query                                    | error | warn | exec_count
-- → UPDATE orders SET amount = ? WHERE id = ? | 1264  |    0 |     182345
```

| Код | Значение | Первое действие |
| :--- | --- | --- |
| 1040 | `Too many connections` | Освободить соединения, см. [Управление соединениями](./connection-management.md) |
| 1045 | `Access denied` | `SHOW GRANTS`, список хостов учётной записи |
| 1062 | `Duplicate entry` | Проверить уникальный индекс и логику приложения (`INSERT IGNORE`, `ON DUPLICATE KEY UPDATE`) |
| 1071 | `Specified key was too long` | Длина ключа индекса и кодировка, см. [Кодировки и сортировки](./charset-and-collation.md) |
| 1170 | `BLOB/TEXT column used in key specification without a key length` | Указать префикс индекса |
| 1205 | `Lock wait timeout exceeded` | [Блокировки и дедлоки](./locking_and_deadlocks.md) |
| 1213 | `Deadlock found when trying to get lock` | Повторять транзакцию; разбор — [Блокировки и дедлоки](./locking_and_deadlocks.md) |
| 1264 | `Out of range value` | Тип колонки не вмещает значение |
| 1267 | `Illegal mix of collations` | [Кодировки и сортировки](./charset-and-collation.md) |
| 1292 | `Incorrect datetime value` | Некорректная дата во входных данных |
| 1366 | `Incorrect ... value` | Тип данных во входных данных |
| 1368 | `CHECK OPTION on non-updatable view` | `UPDATE`/`INSERT` через представление с `WITH CHECK OPTION`, которое нельзя обновить; обновлять базовую таблицу |
| 1846 | `ALGORITHM=... is not supported` | Запрошенный алгоритм недоступен, см. [Online Schema Change](./Operations/online-schema-change.md) |
| 1927 | `Connection was killed` | Соединение прервано извне: `KILL`, `max_execution_time`, таймаут клиента |
| 3024 | `Query execution was interrupted, maximum statement execution time exceeded` | Сработал `max_execution_time` |

### Сценарий 12. Проверка гипотезы без риска для продакшена

```sql
-- Разница счётчиков за интервал: сбросить и измерить
FLUSH STATUS;
-- ... подождать 60 секунд ...
SHOW GLOBAL STATUS WHERE Variable_name IN
  ('Queries','Slow_queries','Threads_connected','Threads_running',
   'Handler_read_next','Handler_read_key','Created_tmp_disk_tables');
```

```sql
-- Стратегия конкретного соединения
SELECT * FROM sys.session WHERE conn_id = 9012\G
```

```sql
-- Явно ограничить дорогой диагностический запрос
SET SESSION max_execution_time = 3000;
SELECT * FROM information_schema.innodb_trx ORDER BY trx_started LIMIT 50;
-- → Query OK, 0 rows affected (выполнено за 1.8 с)
```

Последняя мера — **не лечить, а измерять.** Большинство «лекарств», применённых
в панике (`flush tables`, массовый `KILL`, рестарт), уничтожают данные для расследования
и часть проблемы.

## Устранение неисправностей (Troubleshooting)

### Границы применимости runbook

| Симптом | Этот файл поможет | Нужен другой файл |
| :--- | --- | --- |
| Сервер не запускается | Да | [Emergency Recovery](./backup_and_recovery/emergency_recovery.md) при повреждении данных |
| Недоступен по сети | Да | — |
| Тормозит | Да (первичная локализация) | [Анализ медленных запросов](./Operations/slow-query-analysis.md), [EXPLAIN и оптимизация](./Operations/explain_and_optimization.md) |
| Мало места | Да | [Обслуживание и обновления](./maintenance-and-upgrades.md) |
| Дедлоки | Только коды ошибок | [Блокировки и дедлоки](./locking_and_deadlocks.md) |
| Отставание реплики | Только первичная проверка | [Отслеживание лага репликации](./replication/lag_monitoring.md) |
| Повреждение данных | Только первичная оценка | [Emergency Recovery](./backup_and_recovery/emergency_recovery.md) |

## Лучшие практики

- **Собирать данные до изменений.** Перезапуск и `flush tables` уничтожают следы.
- **Идти от симптома к слою, а не от гипотезы к оптимизации.** Две трети «медленных
  запросов» на практике оказываются проблемой соединений, клиента или диска.
- **Держать error log длинной историей.** Инцидент обычно становится понятен через
  сутки после события, а не в момент его возникновения.
- **Проверять `sys.ps_check_lost_instrumentation`.** Если наблюдаемость молча
  деградировала, все сделанные выводы ненадёжны.
- **Иметь готовый список экстренных команд.** Подключение по сокету, убийство
  соединений, отмена `ALTER` — всё это должно быть написано заранее.
- **Фиксировать вывод `sys.diagnostics()` как артефакк.** Это основа для разбора после
  инцидента.

### Очистка и откат

Все изменения, внесённые во время диагностики, должны быть отменены после разбора
инцидента:

| Что изменено | Как откатить |
| :--- | :--- |
| `SET SESSION max_execution_time = 3000` | Переподключиться или `SET SESSION max_execution_time = @@global.max_execution_time` |
| `SET SESSION lock_wait_timeout = 30` | Переподключиться или `SET SESSION lock_wait_timeout = @@global.lock_wait_timeout` |
| `SET SESSION profiling = 1` | `SET SESSION profiling = 0` |
| `SET GLOBAL super_read_only = OFF` | `SET GLOBAL super_read_only = ON` (только если вы его снимали) |
| `SET GLOBAL` параметры (если менялись) | Восстановить из `performance_schema.variables_info` или `my.cnf` |
| Временные таблицы/файлы | Автоматически удаляются при разъединении |
| Сессии `KILL` | Необратимо — фиксировать в инцидент-репорте |
| `innochecksum` / остановка сервера | После восстановления данных — перезапустить сервер |

`SET SESSION` сбрасывается автоматически при переподключении. `SET GLOBAL` требует
ручного отката — проверьте `performance_schema.variables_info` или `my.cnf`. Если
сервер был перезапущен для диагностики (`innochecksum`, `innodb_force_recovery`),
убедитесь, что все параметры восстановлены из конфигурационного файла:

```bash
sudo mysqld --validate-config && sudo systemctl restart mysql
# → (пустой вывод validate-config = конфиг корректен)
```

## Дополнительная информация

### Полезные команды вне сети

```bash
# Список открытых соединений по состояниям
ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn
# → 4821 ESTAB
# →   91 TIME-WAIT

# Что делает процесс mysqld
sudo strace -p $(pgrep mysqld) -c -f -q -w -S calls -e trace=read,write,openat 2>&1 | head -20
# → (профиль системных вызовов; использовать точечно)

# Проверить, не упёрся ли процесс в лимит дескрипторов
ls /proc/$(pgrep mysqld)/fd | wc -l
# → 1523
sudo systemctl show mysql -p LimitNOFILE
# → LimitNOFILE=1024     ← меньше, чем использует процесс
```

### Внешние ресурсы

- [MySQL 8.4 Reference Manual: Error Messages and Common Problems](https://dev.mysql.com/doc/refman/8.4/en/error-messages.html)
- [MySQL 8.4 Reference Manual: InnoDB Limits](https://dev.mysql.com/doc/refman/8.4/en/innodb-limits.html)
- [MySQL 8.4 Reference Manual: Administrative Connection Interface](https://dev.mysql.com/doc/refman/8.4/en/administrative-connection-interface.html)

### См. также

- **[Управление соединениями](./connection-management.md)** — 1040, `PROCESSLIST`,
  административный интерфейс.
- **[Блокировки и дедлоки](./locking_and_deadlocks.md)** — 1205, 1213, MDL.
- **[Emergency Recovery](./backup_and_recovery/emergency_recovery.md)** —
  `innodb_force_recovery`, восстановление после повреждения.
- **[Performance Schema и sys schema](./Operations/performance-schema-and-sys.md)** —
  инструменты диагностики.
- **[Движки MySQL: InnoDB](./Operations/storage_engines_deep_dive.md)** — buffer pool,
  undo tablespaces, purge, adaptive hash index, page compression.
- **[Диагностика дисковых узких мест](../db_disk_bottleneck_troubleshooting.md)** —
  тот же разбор на уровне инфраструктуры.
- **[Обслуживание и обновления MySQL](./maintenance-and-upgrades.md)** — освобождение
  места, `OPTIMIZE TABLE`, дефрагментация.