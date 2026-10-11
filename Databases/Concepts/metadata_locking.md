# Блокировки метаданных (Metadata Locking, MDL)

**Актуально для:** MySQL 8.0 / 8.4 / 9.x, MariaDB 10.11 / 11.4 / 11.8 / 12.3

**Предварительные требования:** сервер MySQL 8.0+ или MariaDB 10.11+; привилегия `SELECT` на `performance_schema` и `PROCESS` для просмотра чужих сессий в `SHOW PROCESSLIST` / `INFORMATION_SCHEMA.PROCESSLIST`; на MariaDB — `performance_schema=ON` в конфигурационном файле и рестарт сервера (по умолчанию выключен), на MySQL — `performance_schema` включён по умолчанию.

Механизм общий для MySQL и MariaDB, но инструментарий, состав документированных представлений `sys` и поведение XA-транзакций различаются. Каждое утверждение ниже снабжено указанием на продукт; там, где документация разных продуктов расходится, приведены обе версии.

## Определения

| Термин | Значение |
|---|---|
| **Metadata Lock (MDL)** | Блокировка структуры объекта БД (таблицы, представления, триггера, хранимой процедуры), а не его данных. Удерживается до конца транзакции |
| **DDL** | Операции, меняющие структуру: `ALTER TABLE`, `CREATE INDEX`, `DROP INDEX`, `RENAME TABLE`, `OPTIMIZE TABLE`, `TRUNCATE TABLE` |
| **DDL-очередь** | Соединения, ожидающие метаданные, удерживаемые транзакцией другого соединения |
| **Starvation of X locks** | Ситуация, когда ожидающие эксклюзивной блокировки запросы не получают её, будучи непрерывно обходимы новыми общими запросами |
| **`lock_wait_timeout`** | Серверная переменная, таймаут ожидания метаданных |
| **`innodb_lock_wait_timeout`** | Переменная InnoDB, таймаут ожидания блокировок строк |
| **`metadata_lock_info`** | Опциональный плагин MariaDB, добавляющий одноимённую таблицу в `INFORMATION_SCHEMA` |
| **`BACKUP LOCK`** | MariaDB-команда, реализованная через `MDL_SHARED_HIGH_PRIO` на объекте таблицы |

## Основные концепции

### Что защищает MDL

Цитата из документации MariaDB: транзакция «acquires a metadata lock on every table it accesses to prevent other connections from altering their structure. The lock is released at the end of the transaction» (MariaDB).

Из этого следуют четыре практических следствия:

1. **DDL не выполняется мгновенно, если таблица занята.** Соединение, выполнившее `ALTER TABLE` над таблицей, чьи метаданные заблокированы, ставится в очередь и ждёт освобождения (MariaDB). Ошибку получают и некоторые некорректные операторы — они могут не ждать вовсе (MariaDB).
2. **MDL не зависит от движка.** Блокируются и нетранзакционные таблицы, и представления, и связанные объекты — хранимые функции, триггеры (MariaDB).
3. **Длительность — до конца транзакции.** Ни `SAVEPOINT`, ни частичный откат метаданные не освобождают (MariaDB). Это делает «откатиться и продолжить» неработающим способом снять блокировку.
4. **`LOCK TABLES ... WRITE` ставится в ту же очередь** (MariaDB), то есть неявный захват сильной блокировки метаданных из прикладного кода способен остановить DDL.

Дополнительно XA-транзакции ведут себя так же: «Like regular transactions, XA transactions create metadata locks on accessed tables» (MariaDB).

### Иерархия объектов

Тип объекта фиксируется в `OBJECT_TYPE`. Состав по документации:

MariaDB: `BACKUP`, `COMMIT`, `EVENT`, `FUNCTION`, `GLOBAL`, `LOCKING SERVICE`, `PROCEDURE`, `SCHEMA`, `TABLE`, `TABLESPACE`, `TRIGGER` (не используется), `USER LEVEL LOCK`.
MySQL 8.0: `GLOBAL`, `SCHEMA`, `TABLE`, `FUNCTION`, `PROCEDURE`, `TRIGGER` (currently unused), `EVENT`, `COMMIT`, `USER LEVEL LOCK`, `TABLESPACE`, `BACKUP LOCK`, `LOCKING SERVICE`.

Распространение блокировки на связанные объекты:

- **От таблицы или представления к связанным объектам** — блокируются хранимые функции и триггеры (MariaDB). Обратное направление — «блокировка представления блокирует базовые таблицы» — в документации **не подтверждено**.
- **Внешние ключи** — единственное документированное распространение MDL по иерархии: «Metadata locks are extended, as necessary, to tables related by a foreign key constraint… When updating a parent table, a metadata lock is taken on the child table while updating foreign key metadata. Foreign key metadata is owned by the child table» (MySQL 8.0). Для MariaDB аналогичной формулировки в документации не найдено.
- **Динамический SQL внутри хранимой функции** — важное исключение (MariaDB): функция с динамическим SQL «is not pre-locked by its caller: it opens and locks its own tables». При этом «No metadata lock is taken on the routine itself», то есть конкурентный `DROP FUNCTION` может завершиться, пока функция исполняется. Следствие: ошибка `SELECT * FROM t1 WHERE a = f1()`, если `f1()` обращается к `t1` — такой вызов отклоняется.
- **Временные таблицы** — поведение MDL в документации не описано. Подтверждено другое: операции DDL над временными таблицами не вызывают неявный `COMMIT` и не могут быть откачены (MariaDB).

### Уровни привилегий MDL

MariaDB документирует их в `METADATA_LOCK_INFO.LOCK_MODE` с префиксом `MDL_`: `MDL_INTENTION_EXCLUSIVE`, `MDL_SHARED`, `MDL_SHARED_HIGH_PRIO`, `MDL_SHARED_READ`, `MDL_SHARED_READ_ONLY`, `MDL_SHARED_WRITE`, `MDL_SHARED_NO_WRITE`, `MDL_SHARED_NO_READ_WRITE`, `MDL_SHARED_UPGRADABLE`, `MDL_EXCLUSIVE`.

MySQL 8.0 приводит их же в `performance_schema.metadata_locks.LOCK_TYPE` без префикса: `INTENTION_EXCLUSIVE`, `SHARED`, `SHARED_HIGH_PRIO`, `SHARED_READ`, `SHARED_WRITE`, `SHARED_UPGRADABLE`, `SHARED_NO_WRITE`, `SHARED_NO_READ_WRITE`, `EXCLUSIVE`.

Ключевые характеристики по документации MariaDB:

| Уровень | Назначение по документации |
|---|---|
| `MDL_SHARED_READ` | Чтение метаданных, использование таблицы для чтения |
| `MDL_SHARED_WRITE` | Чтение и запись данных при совместимости с чтением метаданных |
| `MDL_SHARED_UPGRADABLE` | Намерение изменять данные, а не только читать. Может быть повышено до `MDL_SHARED_NO_WRITE` и `MDL_EXCLUSIVE`. Используется для первой фазы `ALTER TABLE` |
| `MDL_SHARED_NO_WRITE` | Чтение метаданных без блокировки записи данных. Несовместима ни с чем, кроме `S` и `SH` |
| `MDL_SHARED_NO_READ_WRITE` | Используется для `LOCK TABLES WRITE`. Несовместима ни с чем, кроме `S` и `SH` |
| `MDL_EXCLUSIVE` | «No other type of metadata lock can be granted while this lock is held». Для `CREATE`/`DROP`/`RENAME TABLE` и некоторых фаз других DDL |
| `MDL_SHARED_HIGH_PRIO` | «"High priority" means that, unlike other shared locks, it is granted ignoring pending requests for exclusive locks» |

> [!warning] Дефект документации MariaDB
> На странице таблицы `performance_schema.metadata_locks` перечисление `LOCK_TYPE` содержит **только** семейство `BACKUP_*` (`BACKUP_ALTER_COPY`, `BACKUP_BLOCK_DDL`, `BACKUP_COMMIT`, `BACKUP_DDL`, `BACKUP_DML`, `BACKUP_FLUSH`, `BACKUP_FTWRL1`, `BACKUP_START`, `BACKUP_TRANS_DML`, `BACKUP_WAIT_COMMIT`, `BACKUP_WAIT_DDL`, `BACKUP_WAIT_FLUSH`), тогда как пример на той же странице показывает `LOCK_TYPE: SHARED_READ`. Перечисление нельзя считать нормативным; уровни привилегий документированы на странице `METADATA_LOCK_INFO`. Не пытайтесь «исправить» список уровней по странице `metadata_locks`.

Три остальных измерения состояния:

- `LOCK_STATUS` (MariaDB): `GRANTED`, `KILLED`, `PENDING`, `POST_RELEASE_NOTIFY`, `PRE_ACQUIRE_NOTIFY`, `TIMEOUT`, `VICTIM`. MySQL 8.0 перечисляет тот же набор. Значения `SHARED` и `EXCLUSIVE` **не** являются статусами. Документация MySQL (8.4 / 9.x) описывает жизненный цикл строк: `VICTIM`, `TIMEOUT` и `KILLED` кратковременны и означают, что строка вскоре будет удалена; `PRE_ACQUIRE_NOTIFY` и `POST_RELEASE_NOTIFY` — уведомление движков хранения при захвате и освобождении. Диагностическое следствие: строки со статусами `TIMEOUT` / `VICTIM` искать бессмысленно — в момент чтения их уже нет.
- `LOCK_DURATION` (MariaDB): `EXPLICIT` — снимается явным действием, например глобальной блокировкой `FLUSH TABLES WITH READ LOCK`; `STATEMENT` — неявно в конце оператора; `TRANSACTION` — неявно в конце транзакции.
- Страница `ALTER TABLE` в MariaDB: «If another connection is using the table, a metadata lock is active, and this statement will wait until the lock is released. This is also true for non-transactional tables». То же предложение повторяется на страницах `CREATE INDEX`, `DROP INDEX`, `DROP TABLE`.

### Приоритеты и очередь

Документированные правила:

- **MySQL 8.0** (проверено в 8.4 / 9.7 — формулировка не изменилась): «If there are multiple waiters for a given lock, the highest-priority lock request is satisfied first… Write lock requests have higher priority than read lock requests». В этом же абзаце упомянуто исключение через `max_write_lock_count`: при низком значении запросы на чтение могут предпочитаться ожидающим запросам на запись, если они уже были отложены в пользу заданного числа запросов на запись. Практически это не происходит, так как `max_write_lock_count` по умолчанию очень велик. Действие этого параметра именно на ожидание MDL в документации не подтверждено.
- **MySQL 8.0**: «Statements acquire metadata locks one by one, not simultaneously, and perform deadlock detection in the process». Порядок именования: «DDL statements, LOCK TABLES, and other similar statements… acquiring locks on explicitly named tables in name order» — это снижает вероятность взаимоблокировок между параллельными DDL.
- **MariaDB** документирует исключение, а не правило, через `MDL_SHARED_HIGH_PRIO`, выдаваемый «ignoring pending requests for exclusive locks», и называет отказ от такого поведения «starvation for X locks».

> [!important] Что здесь документировано, а что является следствием
> Для **online DDL** утверждение документировано в MySQL: «Additionally, a pending exclusive metadata lock requested by an online DDL operation blocks subsequent transactions on the table» (MySQL 8.4 / 9.x, Online DDL Performance and Concurrency; в примере `SELECT * FROM t1` третьей сессии блокируется ожидающим `ALTER TABLE ... ALGORITHM=INPLACE, LOCK=NONE`). Как **общее** правило для всех DDL оно отдельно не сформулировано ни на одной странице документации MariaDB или MySQL — оно следует из двух документированных фактов: приоритета запросов на запись над запросами на чтение (MySQL 8.0) и несовместимости `MDL_EXCLUSIVE` с любым другим уровнем («No other type of metadata lock can be granted while this lock is held», MariaDB), плюс документированного исключения, существующего именно потому, что общее правило обратно.
>
> На практике это приводит к тому, что зависший `ALTER TABLE` останавливает не только пишущие, но и читающие запросы к той же таблице, а при исчерпании пула соединений приложения — и к отказу в новых соединениях. Это наблюдаемое поведение и известный источник инцидентов; при планировании работ исходите из него, но при описании ссылайтесь на документированное правило для online DDL (MySQL) либо на приоритет и несовместимость, а не на выдуманную общую цитату.

### MDL и DDL: неизбежные эксклюзивные окна

MariaDB, раздел про стратегии блокирования InnoDB при DDL: «Regardless of which locking strategy is used to perform a DDL operation, InnoDB will have to exclusively lock the table for a short time at the start and end of the operation's execution. This means that any active transactions that may have accessed the table must be committed or aborted for the operation to continue. This applies to most DDL statements, such as ALTER TABLE, CREATE INDEX, DROP INDEX, OPTIMIZE TABLE, RENAME TABLE, etc.»

Два уточнения, важных для точности формулировок:

- Страница InnoDB DDL говорит об эксклюзивной блокировке **таблицы**, а не о «metadata lock»; термин MDL там не используется. Явная связка MDL и `ALTER TABLE` дана на странице `ALTER TABLE` (цитата выше).
- Поскольку утверждение «regardless of which locking strategy» не делает исключений, оно распространяется и на `LOCK=NONE`, и на `ALGORITHM=INSTANT`: **`ALGORITHM=INSTANT` в MariaDB требует MDL** — по общности формулировки, а не по отдельному предложению про INSTANT.

**MySQL 8.0** описывает это поалгоритмно, причём формулировка менялась со временем:

| Алгоритм | MySQL 8.0, текущий текст |
|---|---|
| `COPY` | «Concurrent DML is not permitted». Упоминания metadata lock нет |
| `INPLACE` | «An exclusive metadata lock on the table may be taken briefly during preparation and execution phases of the operation». Обычно параллельный DML поддерживается |
| `INSTANT` | «An exclusive metadata lock on the table may be taken briefly during the execution phase of the operation». Данные таблицы не затрагиваются, параллельный DML разрешён |

> [!warning] Формулировка про INSTANT в MySQL была исправлена
> Снимок документации MySQL 8.0 от января 2022 года для `INSTANT` утверждал обратное: «**No exclusive metadata locks are taken on the table during preparation and execution**». В снимке от января 2023 года это заменено на «may be taken briefly during the execution phase». Актуальна более поздняя формулировка. Утверждение «`ALGORITHM=INSTANT` не требует эксклюзивной блокировки метаданных» в руководстве MySQL 8.0 **отсутствует** — если оно встречается в производных материалах, это дефект.

### MDL и внешние ключи

MySQL 8.0 расширяет метаданные на таблицы, связанные ограничением внешнего ключа, — цитата приведена в разделе об иерархии объектов. Практическое следствие: изменение метаданных родительской таблицы берёт MDL на дочернюю, то есть одна транзакция над родителем блокирует DDL сразу на двух таблицах. Проверяйте владельца по дочерней таблице, а не только по родительской.

### MDL и XA-транзакции

| Продукт | Поведение |
|---|---|
| MariaDB | «Like regular transactions, XA transactions create metadata locks on accessed tables» |
| MySQL 8.0 (с 8.0.13) | «As of MySQL 8.0.13, for XA transactions in PREPARED state, metadata locks are maintained across client disconnects and server restarts, until an XA COMMIT or XA ROLLBACK is executed» |

Разница операционно существенна: prepared-транзакция MySQL, удерживающая MDL, переживает рестарт сервера и превращается в постоянную блокировку DDL. Эквивалента в документации MariaDB не найдено.

MySQL 8.0 отдельно документирует: «Metadata locks acquired during a PREPARE statement are released once the statement has been prepared, even if preparation occurs within a multiple-statement transaction».

### Два таймаута — одна ошибка

Документация MariaDB по `innodb_lock_wait_timeout` указывает два ограничения «by design»:

- переменная затрагивает только транзакционные операторы, а не `ALTER TABLE` или `TRUNCATE TABLE`;
- она «only concerns row locks. It does not put a timeout on metadata locks, or table locks acquired — for example — with the LOCK TABLES statement».

И отдельно: «lock_wait_timeout can be used for metadata locks».

| Что ожидается | Таймаут | Документация |
|---|---|---|
| Блокировка строки InnoDB | `innodb_lock_wait_timeout` | MariaDB |
| Метаданные (DDL в очереди) | `lock_wait_timeout` | MariaDB |
| Табличная блокировка `LOCK TABLES` | Не ограничена `innodb_lock_wait_timeout` | MariaDB |
| Любой тип блокировки | `WAIT n` / `NOWAIT` | MariaDB |

Значения по умолчанию: `lock_wait_timeout` — MySQL `31536000` секунд (1 год), MariaDB `86400` (1 сутки); `innodb_lock_wait_timeout` — `50` секунд в обоих продуктах.

> [!danger] `ERROR 1205` не различает подсистемы
> И `innodb_lock_wait_timeout`, и `lock_wait_timeout` приводят к одному и тому же сообщению MariaDB: `ERROR 1205 (HY000): Lock wait timeout exceeded; try restarting transaction`. По тексту ошибки определить, была ли исчерпана блокировка строки или метаданных, невозможно — нужно смотреть, какой оператор выполнялся и что показывает `SHOW PROCESSLIST` или `information_schema.INNODB_TRX`.
>
> Формально таймауты принадлежат разным подсистемам, и у каждой свой счётчик. Утверждение, что DDL, ожидающий метаданных, не блокирует блокировки строк (и наоборот), в документации **отсутствует**; документированное обратное предупреждение касается смешивания режимов: соединение, удерживающее `MDL_SHARED_HIGH_PRIO`, «should not try to acquire any kind of table-level or row-level lock, as this can lead to a deadlock».

### Длительность и освобождение

MariaDB документирует срок жизни в терминах `LOCK_DURATION`:

- `TRANSACTION` — блокировка метаданных обычной транзакции, снимается в конце транзакции;
- `STATEMENT` — снимается в конце оператора;
- `EXPLICIT` — снимается явным действием, например `FLUSH TABLES WITH READ LOCK`; сюда же реализуется `BACKUP LOCK`: по документации MariaDB он «implemented by taking an `MDL_SHARED_HIGH_PRIO` MDL lock on the table object, which protects the table from any DDL operations».

Отсюда важное ограничение: **`ROLLBACK` внутри транзакции снимает блокировки строк, но не метаданных.** Транзакция, делающая `ROLLBACK` и остающаяся открытой, продолжает удерживать MDL.

## Практические сценарии

### Диагностика: кто кого блокирует (MariaDB)

Официальный запрос из документации плагина `metadata_lock_info` (требуется установленный плагин):

```sql
SELECT
  CONCAT('Thread ', P.ID, ' executing "', P.INFO, '" IS LOCKED BY Thread ', M.THREAD_ID) AS WhoLocksWho
FROM INFORMATION_SCHEMA.PROCESSLIST P,
     INFORMATION_SCHEMA.METADATA_LOCK_INFO M
WHERE LOCATE(LOWER(M.LOCK_TYPE), LOWER(P.STATE)) > 0;
```

```text
+-----------------------------------------------------------------------------------+
| WhoLocksWho                                                                       |
+-----------------------------------------------------------------------------------+
| Thread 3 executing "INSERT INTO foo ( b ) VALUES ( 'FOO' )" IS LOCKED BY Thread 2 |
+-----------------------------------------------------------------------------------+
```

Ограничения этого запроса, которые важно понимать до того, как он будет использоваться:

- он соединяется с `INFORMATION_SCHEMA.PROCESSLIST`, **а не** с `performance_schema.threads`; официального запроса MariaDB, соединяющего `metadata_locks` с `performance_schema.threads`, в документации нет;
- он работает через `LOCATE()` по тексту состояния, поэтому находит только потоки, у которых строка состояния содержит фразу из `LOCK_TYPE`. Поток, висящий в состоянии `Waiting for table metadata lock`, совпадёт только если эта фраза совпадает со значением `LOCK_TYPE`.

Компромиссный, но не привязанный к плагину способ — соединить таблицу метаданных с процесслистом вручную:

```sql
SELECT ml.OBJECT_TYPE, ml.OBJECT_NAME, ml.LOCK_TYPE, ml.LOCK_DURATION,
       ml.LOCK_STATUS, ml.OWNER_THREAD_ID, t.PROCESSLIST_ID
FROM performance_schema.metadata_locks ml
LEFT JOIN information_schema.PROCESSLIST t
       ON t.ID = ml.OWNER_THREAD_ID
WHERE ml.LOCK_STATUS = 'PENDING'
ORDER BY t.TIME DESC;
```

```bash
mariadb -e "SELECT COUNT(*) AS granted, SUM(LOCK_STATUS='PENDING') AS pending FROM performance_schema.metadata_locks;"
# → granted | pending
# →      7 |      1
```

### Включение инструментария MDL (MariaDB)

MariaDB требует явного включения инструмента:

```sql
UPDATE performance_schema.setup_instruments
SET enabled = 'YES', timed = 'YES'
WHERE name LIKE 'wait/lock/metadata%';
```

```bash
mariadb -e "SELECT name, enabled, timed FROM performance_schema.setup_instruments WHERE name LIKE 'wait/lock/metadata%';"
# → name                                | enabled | timed
# → wait/lock/metadata/sql/mdl          | YES     | YES
```

Runtime-изменение теряется при рестарте. Постоянное включение — строки в секции `[mariadb]` конфигурационного файла (требуется рестарт; сам `performance_schema` при этом тоже должен быть включён):

```ini
performance_schema = ON
performance-schema-instrument='wait/lock/metadata/sql/mdl=ON'
```

Отключение — обратная операция:

```sql
UPDATE performance_schema.setup_instruments
SET enabled = 'NO', timed = 'NO'
WHERE name LIKE 'wait/lock/metadata%';
```

> [!important] Различие с MySQL
> MySQL 8.0 указывает, что инструмент метаданных **включён по умолчанию**. В MariaDB его нужно включать самому. Практическое следствие: пустая таблица `performance_schema.metadata_locks` на MariaDB — это не доказательство отсутствия блокировок, а чаще всего невключённый инструмент. Напомним также, что сам `performance_schema` в MariaDB по умолчанию выключен и требует рестарта; в MySQL 8 он включён по умолчанию.

### MySQL: представление `sys` для MDL

MySQL 8 документирует представления `schema_table_lock_waits` и `x$schema_table_lock_waits`: «These views display which sessions are blocked waiting on metadata locks, and what is blocking them».

```sql
SELECT waiting_pid, waiting_query, waiting_query_secs,
       blocking_pid, object_schema, object_name
FROM sys.schema_table_lock_waits\G
```

Документированные столбцы: `object_schema`, `object_name`, `waiting_thread_id`, `waiting_pid`, `waiting_account`, `waiting_lock_type`, `waiting_lock_duration`, `waiting_query`, `waiting_query_secs`, `waiting_query_rows_affected`, `waiting_query_rows_examined`, `blocking_thread_id`, `blocking_pid`, `blocking_account`.

> [!warning] `sys.schema_table_lock_waits` не документирован для MariaDB
> Строка `schema_table_lock_waits` не встречается ни на одной из 8729 страниц документации MariaDB. В документированный набор представлений `sys` у MariaDB входит `sys.innodb_lock_waits`, но он относится только к блокировкам строк. Это утверждение именно о **документированном** наборе: список представлений на странице сам обрывается алфавитно на `schema_object_overview`, поэтому отсутствие в документации не доказывает отсутствие в поставке. Сверяйтесь с собственным сервером:
>
> ```sql
> SHOW TABLES FROM sys LIKE '%lock%';
> ```

### Разбор инцидента: DDL стоит, чтения стоят

Симптом: после запуска `ALTER TABLE` на большой таблице приложение получает таймауты, хотя `SHOW FULL PROCESSLIST` не показывает тяжёлых запросов.

Порядок разбора:

1. **Найти ожидающий DDL** и удерживающего держателя:

```sql
SELECT P.ID AS waiting_id, P.TIME AS waiting_sec, P.STATE, P.INFO,
       M.OWNER_THREAD_ID AS blocked_by_thread
FROM information_schema.PROCESSLIST P
JOIN performance_schema.metadata_locks M ON M.OWNER_THREAD_ID = P.ID
WHERE P.STATE LIKE '%metadata lock%';
```

2. **Найти держателя** по `OWNER_THREAD_ID` из `performance_schema.metadata_locks` и установить, держит ли он транзакцию:

```sql
SELECT trx_id, trx_state, trx_started, trx_rows_locked, trx_query
FROM information_schema.INNODB_TRX
ORDER BY trx_started;
```

```bash
mariadb -e "SHOW FULL PROCESSLIST\G"
# → Id: 4821
# → State: Waiting for table metadata lock
# → Info: ALTER TABLE orders ADD COLUMN status VARCHAR(16)
# →
# → Id: 5107
# → State: (idle in transaction)
# → Info: SELECT * FROM orders WHERE created_at > NOW() - INTERVAL 1 DAY
```

3. **Оценить безопасность прерывания.** Держатель в состоянии `idle in transaction` с уже выполненными изменениями данных — это операция приложения, её обрыв приводит к откату. Оценку даёт `SHOW ENGINE INNODB STATUS`, где видны последние `COMMIT` и `ROLLBACK`.

```sql
-- Дождаться освобождения, если это допустимо по SLA
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders ADD COLUMN status VARCHAR(16);
# → ERROR 1205 (HY000): Lock wait timeout exceeded; try restarting transaction

SET SESSION lock_wait_timeout = DEFAULT;
-- вернуть серверное значение после диагностики
```

Именно этот сценарий — практическое обоснование снижения `lock_wait_timeout`: без него DDL ждёт до истечения server-level таймаута и успевает исчерпать пул соединений приложения.

### Планирование DDL в рабочей системе

Практический набор приёмов:

- **Узнавать держателей метаданных до запуска DDL**, а не после: снимать `FLUSH TABLES WITH READ LOCK` и смотреть на транзакции, либо проверять возраст транзакций в `information_schema.INNODB_TRX`. Долгая транзакция без MDL в `performance_schema.metadata_locks` — сигнал о том, что приложение работает не так, как предполагает регламент.
- **Выбирать `ALGORITHM` явно.** `ALGORITHM=INSTANT` снимает копирование данных, но не снимает эксклюзивное окно метаданных — это лишь сокращает окно, а не устраняет его.
- **Учитывать, что `OPTIMIZE TABLE`, `TRUNCATE TABLE`, `RENAME TABLE`, `CREATE INDEX`, `DROP INDEX` требуют эксклюзивного MDL** так же, как `ALTER TABLE`.
- **Избегать `LOCK TABLES` в прикладном коде.** Он берёт сильный MDL (`MDL_SHARED_NO_READ_WRITE`) и ставит в очередь последующие `LOCK TABLES ... WRITE`, попутно увеличивая счётчик `In_use`.
- **Учитывать влияние внешних ключей:** DDL над родительской таблицей может потребовать MDL на дочерней.
- **Проверять после рестарта prepared-транзакции** (MySQL 8.0.13+): XA в PREPARED удерживает метаданные, и DDL будет заблокирован до `XA COMMIT`/`XA ROLLBACK`.

## Диагностика и устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| `ALTER TABLE` в состоянии `Waiting for table metadata lock` | Транзакция удерживает метаданные | `performance_schema.metadata_locks` с `LOCK_STATUS='PENDING'`, затем `INNODB_TRX` | Завершить или откатить транзакцию-держателя; если это бизнес-операция — сначала согласовать |
| Всё приложение встало после DDL | Пул соединений исчерпан ожидающими чтениями | `SHOW GLOBAL STATUS LIKE 'Threads_connected'` вместе с числом процессов в состоянии ожидания метаданных | Увеличить пул; вынести DDL в окно низкой нагрузки; не выполнять DDL на пике |
| `ERROR 1205` при вставке, а не при DDL | Истёк `innodb_lock_wait_timeout` | `SHOW ENGINE INNODB STATUS` (секция `TRANSACTIONS`), `INNODB_TRX` | См. [transactions_and_locking.md](../MariaDB/transactions_and_locking.md) |
| `ERROR 1205` при DDL | Истёк `lock_wait_timeout` | `SHOW FULL PROCESSLIST`, `performance_schema.metadata_locks` | То же самое — оценить держателя, снизить таймаут для диагностики |
| `performance_schema.metadata_locks` пуста | Инструмент MDL не включён (MariaDB) | `SELECT ... FROM performance_schema.setup_instruments WHERE name LIKE 'wait/lock/metadata%'` | Включить инструмент; при необходимости включить сам `performance_schema` |
| DDL не проходит и после рестарта сервера | MySQL 8.0.13+: prepared XA удерживает метаданные | `XA RECOVER` | Выполнить `XA COMMIT` или `XA ROLLBACK` |
| `DROP FUNCTION` не ждёт работающей функции | Функция с динамическим SQL не берёт MDL на саму себя (MariaDB) | Осознанное проектирование: не полагаться на блокировку | Не использовать динамический SQL в функциях, если нужна защита вызова |
| DDL блокируется, хотя в `SHOW PROCESSLIST` нет незакрытых транзакций | `FLUSH TABLES WITH READ LOCK` — блокировка с `LOCK_DURATION=EXPLICIT` | `LOCK_DURATION='EXPLICIT'` в `metadata_locks` | `UNLOCK TABLES` |
| Блокировка метаданных родительской таблицы блокирует DDL на дочерней | Расширение MDL по внешним ключам (MySQL 8.0) | Проверить ограничения и владельца метаданных дочерней таблицы | Планировать DDL для обеих таблиц одновременно |

## Лучшие практики

- **Считайте MDL ресурсом с длительным жизненным циклом.** Он освобождается на границе транзакции, а не запроса. Транзакция, которая осталась открытой, — это удержание блокировки метаданных, даже если запросов не было.
- **Не применяйте `ROLLBACK` как способ снять MDL.** Откат снимает блокировки строк. Чтобы освободить метаданные, транзакцию нужно завершить.
- **Держите транзакции короткими.** Возраст транзакции — прямая мера того, сколько продлится блокировка метаданных.
- **Проводите DDL в окно низкой нагрузки и с явным `ALGORITHM`.** Это сокращает окно эксклюзивной блокировки, но не отменяет его.
- **Снижайте `lock_wait_timeout`, если DDL обслуживают люди.** По умолчанию ожидание длится 1 год в MySQL (`31536000` с) или 1 сутки в MariaDB (`86400` с) — в течение этого времени пул соединений может быть исчерпан.
- **Включайте инструмент MDL заранее** на MariaDB: `wait/lock/metadata/sql/mdl` по умолчанию не включён, а `performance_schema` выключен по умолчанию.
- **Избегайте `LOCK TABLES` в прикладном коде** и учитывайте, что `BACKUP LOCK` тоже берёт метаданные.
- **Не смешивайте режимы блокировок в одном соединении.** Документированное предупреждение для `MDL_SHARED_HIGH_PRIO`: соединение, удерживающее его, не должно затем брать табличные или построчные блокировки и не должно ждать других ресурсов — это ведёт к взаимоблокировкам и голоданию запросов на запись.

## Ограничения и неподтверждённое

Перечисленные ниже утверждения **отсутствуют** в официальной документации обеих продуктовых семей. Планируя работу, опирайтесь на наблюдаемое поведение, но не приписывайте ему документальный статус:

- Что ожидающий эксклюзивный запрос MDL заставляет новые общие запросы вставать в очередь за ним **во всех видах DDL**. Для online DDL это документировано в MySQL («a pending exclusive metadata lock requested by an online DDL operation blocks subsequent transactions on the table», MySQL 8.4 / 9.x); как общее правило — выводится из приоритета запросов на запись (MySQL 8.0) и несовместимости `MDL_EXCLUSIVE` с любым другим уровнем (MariaDB).
- Действие переменной `max_write_lock_count` именно на ожидание MDL.
- Блокирует ли взятие метаданных представления или хранимой процедуры базовые таблицы. Документировано только распространение от таблицы или представления к связанным объектам.
- Поведение MDL на временных таблицах.
- Наличие `performance_schema.metadata_locks_info_by_thread` в MariaDB — в документации MariaDB такой таблицы нет.
- Наличие `sys.schema_table_lock_waits` в MariaDB — в документированном наборе представлений `sys` такого нет; страница перечня представлений сама обрезана, поэтому это утверждение о документации, а не о поставке.
- Что DDL, ожидающий метаданных, не блокирует блокировки строк, и наоборот.
- Сохранение метаданных prepared-транзакцией XA в MariaDB.

## Дополнительная информация

### Документация MariaDB

- [Metadata Locking](https://mariadb.com/docs/server/reference/sql-statements/transactions/metadata-locking) — базовое описание, поведение очереди, пример с MEMORY-таблицей
- [performance_schema.metadata_locks](https://mariadb.com/docs/server/reference/system-tables/performance-schema/performance-schema-tables/performance-schema-metadata_locks-table) — столбцы `OBJECT_TYPE`, `LOCK_STATUS`, `LOCK_DURATION`; здесь же дефект перечисления `LOCK_TYPE`
- [INFORMATION_SCHEMA.METADATA_LOCK_INFO](https://mariadb.com/docs/server/reference/system-tables/information-schema/information-schema-tables/information-schema-metadata_lock_info-table) — уровни привилегий `MDL_*` с описаниями
- [metadata_lock_info plugin](https://mariadb.com/docs/server/reference/plugins/other-plugins/metadata-lock-info-plugin) — установка и официальный диагностический запрос
- [ALTER TABLE](https://mariadb.com/docs/server/reference/sql-statements/data-definition/alter/alter-table) — связь MDL и DDL
- [InnoDB Online DDL Overview](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-online-ddl/innodb-online-ddl-overview) — эксклюзивная блокировка в начале и конце операции
- [XA Transactions](https://mariadb.com/docs/server/reference/sql-statements/transactions/xa-transactions) — MDL в XA
- [Stored Functions → Further Restrictions](https://mariadb.com/docs/server/server-usage/stored-routines/stored-functions) — динамический SQL и отсутствие MDL на самой функции
- [BACKUP LOCK](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/backup-commands/backup-lock) — реализация через `MDL_SHARED_HIGH_PRIO`

### Документация MySQL

- [Metadata Locking](https://dev.mysql.com/doc/refman/8.0/en/metadata-locking.html) — приоритеты, порядок именования объектов, XA с 8.0.13, расширение на внешние ключи
- [The metadata_locks Table](https://dev.mysql.com/doc/refman/8.0/en/performance-schema-metadata-locks-table.html)
- [The schema_table_lock_waits View](https://dev.mysql.com/doc/refman/8.0/en/sys-schema-table-lock-waits.html)
- [ALTER TABLE → Performance and Space Requirements](https://dev.mysql.com/doc/refman/8.0/en/alter-table.html) — формулировки по `COPY` / `INPLACE` / `INSTANT`
- [Online DDL Performance and Concurrency](https://dev.mysql.com/doc/refman/8.4/en/innodb-online-ddl-performance.html) — три фазы online DDL и документированное блокирование последующих транзакций ожидающим эксклюзивным MDL (проверено в 8.4 / 9.7)

### Смежные документы базы знаний

- [DDL vs DML](../Concepts/DDL_vs_DML.md) — место DDL в конкуренции с DML
- [Транзакции и блокировки (MariaDB)](../MariaDB/transactions_and_locking.md) — таймауты блокировок, isolation, диагностика
- [InnoDB: долговечность и настройка записи (MariaDB)](../MariaDB/innodb_durability_tuning.md) — page flushing и чекпоинты, порождающие нагрузку на DDL
- [Блокировки и взаимоблокировки в MySQL](../MySQL/locking_and_deadlocks.md) — блокировки строк, gap locks, MDL-сценарии для MySQL
- [Online Schema Change (MySQL)](../MySQL/Operations/online-schema-change.md) — обходные пути вместо прямого `ALTER TABLE`
- [Индексы](./indexes.md) — почему `CREATE INDEX` и `DROP INDEX` относятся к DDL
- [ACID](./acid.md) — изоляция и границы транзакции, в которой живёт MDL