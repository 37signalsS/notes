# Undo logs, purge и History list length в MySQL

**Актуально для:** MySQL 8.4 LTS (проверено по MySQL 8.4 Reference Manual)

В InnoDB удаление строки не означает удаления данных с диска. Изменение
фиксируется в undo log, старая версия строки остаётся в файлах таблицы до тех
пор, пока её удалить не станет безопасно. Этот процесс называется **purge**, и
именно он — причина большинства «медленных» инцидентов, которые не связаны с
нагрузкой: транзакция или дамп держат базу в состоянии, когда purge не может
догнать запись, растёт лаг репликации и база постепенно раздувается.

Один параметр, который объясняет эти симптомы, —
`History list length` из `SHOW ENGINE INNODB STATUS`. Это первая метрика,
которую стоит смотреть при жалобах «база стала медленнее, а нагрузка та же».

Связанные темы: **[Транзакции и долговечность](./transactions_and_durability.md)** —
жизненный цикл транзакции; **[Блокировки и взаимоблокировки](./locking_and_deadlocks.md)** —
как длинные транзакции удерживают блокировки.

## Определения

| Термин | Значение |
| :--- | :--- |
| Undo log | Журнал отката: записывает изменения строки, позволяющие вернуть её предыдущую версию и откатить незавершённую транзакцию |
| Purge | Фоновая операция InnoDB, физически удаляющая ненужные версии строк и освобождающая undo log |
| History list length | Количество невытесненных записей undo log в истории транзакций; отображается в секции `TRANSACTIONS` вывода `SHOW ENGINE INNODB STATUS` |
| Purge lag | Отставание purge; отображается именно как `History list length` |
| Undo tablespace | Отдельное табличное пространство для undo log; может быть усечено при выполнении условий |
| Rollback segment (rseg) | Структура хранения записей истории транзакций; при переполнении история «наследуется» предыдущему сегменту |
| `innodb_purge_threads` | Число фоновых потоков, выполняющих purge |
| `innodb_max_purge_lag` | Желаемый максимум отставания purge; при превышении DML-операции искусственно задерживаются, чтобы purge догнал |

## Предварительные требования

Перед диагностикой и управлением undo log требуется:

- **Доступ к серверу MySQL** с привилегиями `PROCESS`, `RELOAD` и `SYSTEM_VARIABLES_ADMIN`
  для запросов к `INNODB_METRICS`, `INNODB_STATUS`, `INNODB_TRX` и изменения GLOBAL-параметров.
- **Доступ к хосту** (root или sudo) — для чтения error log, остановки/перезапуска `mysqld`
  при ручном усечении undo tablespace (`innochecksum`), и для оценки лагов ввода-вывода.
- **Схема `sys`** (входит в MySQL 8.0+) — не используется напрямую для undo-метрик,
  но требуется для связанных диагностических запросов (`sys.statement_analysis`,
  `sys.processlist`). Проверить наличие:

  ```sql
  SELECT COUNT(*) AS has_sys
  FROM information_schema.schemata WHERE schema_name = 'sys';
  ```

- **Инструменты ОС**: `procps` (`ps`), `sysstat` (`vmstat`, `iostat`), `iproute2` (`ss`),
  `coreutils` (`df`, `du`).
- **Для реплик с `super_read_only = ON`**: административный порт 33062 либо временное
  снятие `super_read_only` — см. [Диагностический runbook](./troubleshooting-runbook.md).

## Базовые концепции

### Почему удалённые строки остаются на диске

InnoDB физически не удаляет строку сразу после `DELETE`: строка и её записи
индексов удаляются только тогда, когда InnoDB отбрасывает запись undo log,
созданную для этого удаления. Эта операция и называется purge.

Причина — MVCC. Старые данные сохраняются, пока не завершатся транзакции,
которые начались раньше или одновременно, чтобы они могли видеть предыдущее
состояние строк. Отсюда прямое следствие, из которого следует всё остальное:

> **Длинная транзакция мешает purge удалять изменения, сделанные другими
> транзакциями.**

Официальная документация объясняет, почему растёт `History list length`:
при уровне изоляции `REPEATABLE READ` транзакция обязана возвращать тот же
результат, что и в момент создания её read view, поэтому MVCC обязан хранить
копию данных в undo log до тех пор, пока все зависящие от неё транзакции не
завершатся. Практические примеры такой транзакции из документации:
`mysqldump` с опцией `--single-transaction` при значительном параллельном DML
и запрос `SELECT` после отключения `autocommit`, когда забывают выполнить
`COMMIT` или `ROLLBACK`.

Симптомы при растущем `History list length`:

- растёт лаг репликации: SQL-поток реплики ждёт завершения своей длинной
  транзакции, а эта транзакция не может завершиться;
- растёт объём undo tablespace, а вместе с ним — нагрузка на ввод-вывод;
- при заполнении системного диска возможен `ERROR 1114: Table is full` и
  остановка записи (см.
  **[Диагностический runbook](./troubleshooting-runbook.md)**).

### Как измеряется отставание purge

**`SHOW ENGINE INNODB STATUS`**, секция `TRANSACTIONS` — самый прямой путь:

```bash
mysql -u root -p -e "SHOW ENGINE INNODB STATUS\G" | grep -E "Purge|History"
```

```text
# → ---TRANSACTION 290328385, ACTIVE 0 sec
# → Trx id counter 290328385
# → Purge done for trx's n:o < 290315608 undo n:o < 17
# → History list length 20
```

Точное имя метрики в `INNODB_METRICS` — `trx_rseg_history_len`
(подсистема `transaction`, включена по умолчанию):

```sql
SELECT NAME, SUBSYSTEM, COUNT, STATUS
FROM INFORMATION_SCHEMA.INNODB_METRICS
WHERE NAME = 'trx_rseg_history_len';
```

```text
# → NAME                   | SUBSYSTEM   | COUNT | STATUS
# → trx_rseg_history_len   | transaction |    20 | enabled
```

Это единственный источник значения, пригодный для автоматического сбора: в
sys schema представления для undo log и purge нет, поэтому рассчитывать на
`sys.*` в мониторинге нельзя. Сценарии длинных транзакций, которые официально
приводит документация как причину роста `History list length`, — это
`mysqldump --single-transaction` при значительном параллельном DML и запрос
`SELECT` после отключения `autocommit`, когда забывают выполнить `COMMIT`
или `ROLLBACK`. Второй случай разбирается в сценарии 2 ниже.

Ориентиры по величине: документация указывает, что значение обычно невелико —
«менее нескольких тысяч», но при записи с большой интенсивностью или при
длинных транзакциях оно растёт. **Числового порога в документации нет** —
его нужно выбирать для конкретной базы по собственному baseline, а не
копировать из чужой.

### Параметры purge и undo log (значения — из документации 8.4)

| Параметр | Значение | Область | Динамический | Допустимые значения |
| :--- | :--- | :--- | :--- | :--- |
| `innodb_purge_threads` | `1`, если доступно логических процессоров не больше 16, иначе `4` | Global | **Нет** (требует рестарта) | `1`–`32` |
| `innodb_max_undo_log_size` | `1073741824` (1024 MiB) | Global | Да | от `10485760` байт до `2**64-1` |
| `innodb_undo_log_truncate` | `ON` | Global | Да | булево |
| `innodb_undo_tablespaces` | `2` (переменная устарела) | Global | Да | `2`–`127` |
| `innodb_purge_rseg_truncate_frequency` | `128` | Global | Да | `1`–`128` |
| `innodb_max_purge_lag` | `0` — без ограничения | Global | Да | целое |
| `innodb_max_purge_lag_delay` | верхняя граница задержки, применяемой при превышении `innodb_max_purge_lag` | Global | Да | целое |

Что из этого следует:

- **`innodb_purge_threads` в 8.4 нельзя изменить на лету** — рестарт обязателен.
  Планировать увеличение нужно заранее, как изменение конфигурации, а не как
  реакцию на инцидент. Документация рекомендует больше потоков purge, когда
  DML распределено по множеству таблиц.
- **Усечение undo tablespace** происходит, когда таблическое пространство
  превышает порог `innodb_max_undo_log_size` и включён
  `innodb_undo_log_truncate`. Для усечения требуется **минимум два** undo
  tablespace; усечение undo log, размещённого в системном табличном
  пространстве, не поддерживается. Частоту освобождения rollback-сегментов
  можно ускорить параметром `innodb_purge_rseg_truncate_frequency` (по
  умолчанию `128`).
- **`innodb_max_purge_lag`** — единственный инструмент, который не даёт purge
  отставать бесконтрольно: при превышении порога в `INSERT`, `UPDATE` и
  `DELETE` вносятся задержки. Значение по умолчанию `0` означает, что
  ограничения нет. У задержки есть верхняя граница
  `innodb_max_purge_lag_delay` — её нужно задавать вместе, иначе DML может
  встать слишком долго.

Производительность усечения: активация усечения улучшает состояние
табличного пространства, но может вызывать периодические всплески нагрузки.
В MySQL 8.0.21 это смягчено — InnoDB оставляет страницы в buffer pool после
удаления файла undo, вместо того чтобы сбрасывать их все. Если же
`innodb_max_undo_log_size` слишком мал для нагруженной системы, одно и то же
табличное пространство может усекаться слишком часто, что само по себе
создаёт нагрузку.

### Что делать, когда purge отстаёт

Официально документированные рычаги:

1. **Закрыть или прервать длинную транзакцию.** Пока транзакция, удерживающая
   read view, не завершена, purge не сможет удалить её версии.
2. **Увеличить `innodb_purge_threads`** — помогает, когда DML распределено по
   многим таблицам (в 8.4 требует рестарта).
3. **Задать `innodb_max_purge_lag`** вместе с `innodb_max_purge_lag_delay` —
   сервер сам начнёт притормаживать DML, не дожидаясь аварии.
4. **Увеличить `innodb_max_undo_log_size`** — порог усечения выше, значит
   табличное пространство не растёт; меняется динамически.
5. **Принудительно пометить tablespace к усечению:**
   `ALTER UNDO TABLESPACE tablespace_name SET INACTIVE;` (для ручного усечения,
   когда оно кажется слишком медленным). Сессия, активировавшая такое усечение,
   должна оставаться открытой.

## Практические сценарии

### 1. Диагностика: снять все четыре показателя

```sql
SELECT NAME, COUNT FROM INFORMATION_SCHEMA.INNODB_METRICS
WHERE NAME IN ('trx_rseg_history_len', 'trx_rseg_history_len_Avg',
               'purge_requests', 'purge_delays', 'purge_no_dblmark',
               'purge_dblmark_wait', 'trx_purge_max_hint')
ORDER BY NAME;
```

```text
# → NAME                    | COUNT
# → trx_rseg_history_len    | 18432
# → trx_rseg_history_len_Avg| 12
# → purge_requests          | 9034211
# → purge_delays            | 2741
```

Высокое `purge_delays` при растущем `trx_rseg_history_len` означает, что purge
работает с задержками, и причина, скорее всего, в большом объёме работы либо в
том, что самые старые версии всё ещё удерживаются транзакцией.

Состояние самих undo tablespace:

```sql
SELECT TABLESPACE_NAME, FILE_TYPE, FILE_SIZE, ALLOCATED_SIZE
FROM INFORMATION_SCHEMA.FILES
WHERE FILE_TYPE LIKE 'UNDO LOG';
```

```text
# → TABLESPACE_NAME         | FILE_TYPE | FILE_SIZE | ALLOCATED_SIZE
# → innodb_undo_01          | UNDO LOG  | 104857600 |   113246208
# → innodb_undo_02          | UNDO LOG  | 104857600 |    17825792
```

`FILE_SIZE` около `1073741824` байт при работающем сервере означает, что
табличное пространство доросло до порога и ждёт усечения.

### 2. Найти транзакцию-виновника

Метрика показывает симптом, но не причину. Причина — транзакция с самым
старым `trx_started`:

```sql
SELECT trx_id,
       trx_state,
       trx_started,
       TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS age_sec,
       trx_mysql_thread_id,
       trx_query
FROM information_schema.INNODB_TRX
WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 300
ORDER BY trx_started
LIMIT 5;
```

```text
# → trx_id     | trx_state | trx_started           | age_sec | trx_mysql_thread_id | trx_query
# → 1283741002 | RUNNING   | 2026-10-03 13:58:02.0 |     4051|               4821 | SELECT * FROM orders WHERE customer_id = 17
```

Сверка с `processlist`, чтобы понять, кто это:

```sql
SELECT ID, USER, HOST, DB, COMMAND, TIME, STATE, LEFT(INFO, 100) AS info
FROM information_schema.PROCESSLIST
WHERE ID = 4821;
```

```text
# → ID   | USER       | HOST         | DB   | COMMAND | TIME | STATE | info
# → 4821 | app_writer | app-01       | shop | Sleep   | 3898 |       | NULL
```

`COMMAND = Sleep` вместе с большим `TIME` и текстом запроса, выполненного
последним, — это забытая транзакция: `autocommit=0`, `SELECT` без
`COMMIT`/`ROLLBACK`. Это ровно тот случай, который документация называет
примером роста `History list length`.

Отдельный класс виновников — потоки репликации:

```sql
SELECT CHANNEL_NAME,
       SERVICE_STATE,
       REMAINING_DELAY,
       LAST_APPLIED_TRANSACTION
FROM performance_schema.replication_applier_status_by_worker;
```

```text
# → CHANNEL_NAME | SERVICE_STATE | REMAINING_DELAY | LAST_APPLIED_TRANSACTION
# →              | Service_state |              0 | 6b9a6b9a-1111-11ee-b12b-0242ac110002:4711
```

Если SQL-поток реплики висит, purge на реплике отстаёт по той же причине —
незавершённая транзакция; лаг при этом виден в
**[Мониторинг лага репликации](./replication/lag_monitoring.md)**.

Прервать:

```sql
KILL 4821;
```

На реплике поток SQL можно остановить без потери транзакции: он возобновит
работу после `START REPLICA`:

```sql
STOP REPLICA SQL_THREAD;
START REPLICA SQL_THREAD;
```

### 3. Снизить давление на purge без рестарта

На живом сервере доступны только динамические параметры:

```sql
-- Порог усечения undo tablespace: 2 GiB вместо дефолтных 1024 MiB
SET GLOBAL innodb_max_undo_log_size = 2147483648;

-- Ограничить отставание purge: при превышении 100000 записей
-- сервер будет задерживать DML
SET GLOBAL innodb_max_purge_lag = 100000;
SET GLOBAL innodb_max_purge_lag_delay = 100;  -- не более 100 мс задержки

-- Проверка
SHOW GLOBAL VARIABLES WHERE Variable_name IN
  ('innodb_max_undo_log_size', 'innodb_max_purge_lag', 'innodb_max_purge_lag_delay');
```

```text
# → Variable_name              | Value
# → innodb_max_undo_log_size   | 2147483648
# → innodb_max_purge_lag       | 100000
# → innodb_max_purge_lag_delay | 100
```

Осторожно с `innodb_max_purge_lag_delay`: задержка применяется к каждой
DML-операции, поэтому слишком большое значение превращается в видимую
деградацию записи. Начинать с малых значений и наблюдать за
`Innodb_row_lock_time` и временем ответа.

### 4. Увеличить число потоков purge (требует рестарта)

```bash
# Текущее значение и план
mysql -u root -p -e "SHOW VARIABLES LIKE 'innodb_purge_threads'";
# → Variable_name         | Value
# → innodb_purge_threads | 1
```

```ini
[mysqld]
# DML распределено по множеству таблиц — расширяем purge
innodb_purge_threads = 4
```

```bash
sudo -u mysql mysqld --validate-config
# → (пустой вывод при отсутствии ошибок)

sudo systemctl restart mysql
mysql -u root -p -e "SHOW VARIABLES LIKE 'innodb_purge_threads';"
# → innodb_purge_threads | 4
```

Проверку значения после рестарта удобно делать через
`performance_schema.variables_info` — она показывает источник значения
(`PERSISTED`, `GLOBAL`, `COMPILED`) и защищает от «правил в файле, но не
применённых в рантайме»:

```sql
SELECT VARIABLE_NAME, VARIABLE_SOURCE, VARIABLE_PATH
FROM performance_schema.variables_info
WHERE VARIABLE_NAME IN ('innodb_purge_threads', 'innodb_max_purge_lag');
```

```text
# → VARIABLE_NAME         | VARIABLE_SOURCE | VARIABLE_PATH
# → innodb_purge_threads  | GLOBAL          |
# → innodb_max_purge_lag | COMPILED        |
```

### 5. Ручное усечение undo tablespace

Если файлы undo разрослись и автоматического усечения недостаточно, его можно
запустить явно:

```sql
-- Текущие undo tablespace
SELECT TABLESPACE_NAME, STATE FROM INFORMATION_SCHEMA.INNODB_TABLESPACES
WHERE TABLESPACE_NAME LIKE 'innodb_undo%';
```

```text
# → TABLESPACE_NAME | STATE
# → innodb_undo_01  | NORMAL
# → innodb_undo_02  | NORMAL
```

```sql
ALTER UNDO TABLESPACE innodb_undo_02 SET INACTIVE;
```

```sql
SELECT TABLESPACE_NAME, STATE FROM INFORMATION_SCHEMA.INNODB_TABLESPACES
WHERE TABLESPACE_NAME LIKE 'innodb_undo%';
```

```text
# → TABLESPACE_NAME | STATE
# → innodb_undo_01  | NORMAL
# → innodb_undo_02  | INACTIVE
```

`INACTIVE` означает «помечен к усечению», а не «удалён»: пространство
освобождается по мере того, как purge доходит до его записей, поэтому при
`History list length` в сотни тысяч усечение займёт время. Сессия, выполняющая
такое усечение, должна оставаться открытой до завершения.

### 6. Валидация: purge догнал

```bash
mysql -u root -p -e "SHOW ENGINE INNODB STATUS\G" | grep -E "History list length"
# → History list length 23
```

```sql
SELECT NAME, COUNT FROM INFORMATION_SCHEMA.INNODB_METRICS
WHERE NAME = 'trx_rseg_history_len';
# → trx_rseg_history_len | 23
```

```sql
SELECT TABLESPACE_NAME, FILE_SIZE FROM INFORMATION_SCHEMA.FILES
WHERE FILE_TYPE LIKE 'UNDO LOG';
# → innodb_undo_01 | 4194304
# → innodb_undo_02 | 4194304
```

Если после устранения виновника `History list length` не уменьшается в
течение нескольких минут, а счётчик `purge_requests` не растёт — purge не
обрабатывает новые запросы. Проверьте, не исчерпаны ли rollback-сегменты
(`Innodb_trx_rseg_history_len`) и достаточно ли потоков purge.

## Устранение неисправностей (Troubleshooting)

Перед применением ремедий в таблице ниже обязательно определите виновника —
длинная транзакция или низкая ёмкость purge. Без этого любые изменения дают
временное облегчение, а проблема возвращается.

| Симптом | Этот файл поможет | Куда идти |
| :--- | --- | --- |
| `History list length` растёт | Да (вся диагностика и ремедии) | — |
| `History list length` в сотнях тысяч | Да (сценарии 1–5) | Если purge не движется — [Диагностический runbook](./troubleshooting-runbook.md) (system-level) |
| Растёт `undo tablespace` на диске | Да (сценарий 5) | Если файлы undo более 80% от раздела — срочно добавить место |
| Запросы подвисают на этапе `COMMIT` | Да (purge lag) | Если `innodb_max_purge_lag` не задан — [Транзакции и долговечность](./transactions_and_durability.md) |
| Реплика отстаёт | Да (виновник — long trx) | [Мониторинг лага репликации](./replication/lag_monitoring.md) |
| Таблица растёт без INSERT-ов | Да (сценарий 7) | [Обслуживание и обновления](./maintenance-and-upgrades.md) — `OPTIMIZE TABLE` |

Если после устранения виновника `History list length` не падает в течение 5 минут,
а `purge_requests` не растёт — purge не обрабатывает новые запросы. Проверьте:

```sql
-- Есть ли активные purge-потоки?
SELECT NAME, COUNT, STATUS
FROM INFORMATION_SCHEMA.INNODB_METRICS
WHERE NAME IN ('trx_rseg_history_len', 'purge_requests', 'purge_delays');
-- → Если purge_requests НЕ растёт — purge stuck
```

```bash
# Есть ли purge-потоки в процессах?
ps -C mysqld -o pid,stat,wchan | grep -i purge
# → Если нет строк — purge threads не работают
```

### Частые причины и решения

| Причина | Как диагностировать | Решение |
| :--- | --- | --- |
| Забытая транзакция (autocommit=0, нет COMMIT) | `SELECT ... FROM INNODB_TRX WHERE age_sec > 300` | `KILL <trx_mysql_thread_id>` |
| `mysqldump --single-transaction` на нагруженной БД | `trx_started` на 2+ часа, `trx_query = SHOW TABLE STATUS` | Дождаться завершения или `KILL` |
| Слишком мало purge threads | `innodb_purge_threads = 1`, `purge_delays` растёт | Увеличить до 4–8 (`--validate-config && restart`) |
| `innodb_max_purge_lag = 0` (без лимита) | `SHOW VARIABLES LIKE 'innodb_max_purge_lag'` | `SET GLOBAL innodb_max_purge_lag = 100000` |
| Undo tablespace близко к лимиту | `SELECT FILE_SIZE FROM FILES WHERE FILE_TYPE='UNDO LOG'` | `SET GLOBAL innodb_max_undo_log_size = 2147483648` |

## Лучшие практики

- **Ограничьте время жизни транзакции на уровне приложения и ProxySQL.**
  В ProxySQL это `mysql-max_transaction_idle_time` и
  `mysql-max_transaction_time` (см.
  **[ProxySQL: Транзакции и Prepared Statements](./ProxySQL/proxysql_transactions.md)**).
- **Ограничьте время выполнения запроса**, чтобы «забытый» `SELECT` не ждал
  часами: `MAX_EXECUTION_TIME` (см.
  **[Resource groups](./configuration.md)** — там же про ограничение нагрузки).
- **Никогда не запускайте `mysqldump --single-transaction` на реплике, которую
  нельзя остановить**, не оценив ожидаемый объём DML: длительный дамп — это
  длинная транзакция, а она останавливает purge на всей реплике.
- **Не оставляйте транзакцию открытой без надобности** — каждая открытая
  транзакция держит read view, а это прямой вклад в `History list length`.

### Очистка и откат

Все изменения параметров, внесённые во время диагностики, должны быть отменены
или зафиксированы после разбора инцидента:

| Что изменено | Как откатить |
| :--- | :--- |
| `SET GLOBAL innodb_max_undo_log_size = 2147483648` | `SET GLOBAL innodb_max_undo_log_size = 1073741824` (default 1024 MiB) |
| `SET GLOBAL innodb_max_purge_lag = 100000` | `SET GLOBAL innodb_max_purge_lag = 0` (снять ограничение) |
| `SET GLOBAL innodb_max_purge_lag_delay = 100` | `SET GLOBAL innodb_max_purge_lag_delay = 0` |
| `ALTER UNDO TABLESPACE X SET INACTIVE` | `ALTER UNDO TABLESPACE X SET ACTIVE;` — возвращает в NORMAL |
| `innodb_purge_threads` в `my.cnf` | Убрать из конфигурации или вернуть значение по умолчанию |
| `KILL <thread_id>` | Необратимо — фиксировать в инцидент-репорте |
| `STOP REPLICA SQL_THREAD` | `START REPLICA SQL_THREAD;` |

`SET GLOBAL` сбрасывается при перезапуске сервера. Чтобы изменения не
потерялись и после рестарта — задайте их через `SET PERSIST`:

```sql
SET PERSIST innodb_max_purge_lag = 100000;
-- → Query OK, 0 rows affected
```

Проверить, что параметр действительно применился из конфигурации, а не только
в runtime:

```sql
SELECT VARIABLE_NAME, VARIABLE_SOURCE, VARIABLE_PATH
FROM performance_schema.variables_info
WHERE VARIABLE_NAME = 'innodb_max_purge_lag';
-- → VARIABLE_SOURCE = PERSISTED (если через SET PERSIST)
-- → VARIABLE_SOURCE = GLOBAL  (если через SET GLOBAL — не выживет рестарт)
```

- **Ограничьте время жизни транзакции на уровне приложения и ProxySQL.**
  В ProxySQL это `mysql-max_transaction_idle_time` и
  `mysql-max_transaction_time` (см.
  **[ProxySQL: Транзакции и Prepared Statements](./ProxySQL/proxysql_transactions.md)**).
- **Ограничьте время выполнения запроса**, чтобы «забытый» `SELECT` не ждал
  часами: `MAX_EXECUTION_TIME` (см.
  **[Resource groups](./configuration.md)** — там же про ограничение нагрузки).
- **Никогда не запускайте `mysqldump --single-transaction` на реплике, которую
  нельзя остановить**, не оценив ожидаемый объём DML: длительный дамп — это
  длинная транзакция, а она останавливает purge на всей реплике.
- **Не оставляйте транзакцию открытой без надобности** — каждая открытая
  транзакция держит read view, а это прямой вклад в `History list length`.

## Дополнительная информация

### См. также

- **[Транзакции и долговечность](./transactions_and_durability.md)** — autocommit,
  неявный commit, savepoint, параметры долговечности.
- **[Блокировки и взаимоблокировки](./locking_and_deadlocks.md)** — как длинные
  транзакции удерживают блокировки и вызывают дедлоки.
- **[Мониторинг MySQL](./monitoring.md)** — метрики и алерты Prometheus/Zabbix.
- **[Performance Schema и sys schema](./Operations/performance-schema-and-sys.md)** —
  источники данных P_S и ограничения покрытия.
- **[Резервное копирование и восстановление](./backup_and_recovery/overview.md)** —
  почему физический бэкап читает undo log и как это связано с ростом нагрузки.
- **[Диагностический runbook](./troubleshooting-runbook.md)** — `ERROR 1114:
  Table is full`, диск заполнен, повреждение страниц.

### Официальная документация

- [Purge Configuration](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/innodb-purge-configuration.html) — механика purge, `History list length`, примеры длинных транзакций
- [Undo Tablespaces](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/innodb-undo-tablespaces.html) — усечение, `innodb_max_undo_log_size`, `ALTER UNDO TABLESPACE`
- [INNODB_METRICS Table](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/innodb-information-schema-metrics-table.html) — счётчики и подсистемы
- [InnoDB Parameters](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/innodb-parameters.html) — `innodb_purge_threads`, `innodb_max_purge_lag`, `innodb_purge_rseg_truncate_frequency`
- [Optimizing InnoDB Transaction Management](https://dev.mysql.com/doc/refman/8.4/en/optimizing-innodb-transaction-management.html) — MVCC и последствия длинных транзакций
- [SHOW ENGINE INNODB STATUS](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/show-engine.html) — секция `TRANSACTIONS`
- [Improvements to Undo Truncation in MySQL 8.0.21](https://dev.mysql.com/blog-archive/improvements-to-undo-truncation-in-mysql-8-0-21/) — смягчение всплесков при усечении