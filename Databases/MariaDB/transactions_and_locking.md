# Транзакции и блокировки в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**Transaction (транзакция)** — логическая единица работы, подчинённая правилам **[ACID](../Concepts/acid.md)**. В MariaDB транзакционными являются таблицы InnoDB; Aria и MyISAM транзакций не поддерживают, а `LOCK TABLES` работает для них как блокировка на уровне таблицы.

**Isolation level (уровень изоляции)** — правило, определяющее, какие изменения чужих транзакций данная транзакция обязана увидеть. Управляется переменными `transaction_isolation` и `tx_isolation`.

**MVCC** — механизм, при котором читатель получает согласованный снимок данных, не блокируя писателя. Реализуется через undo-логи: см. **[Журнал предзаписи](../Concepts/write_ahead_log.md)**.

**Gap locking (блокировка промежутков)** — блокировка пустого интервала между индексированными записями, а не самих строк. Существует, чтобы при `REPEATABLE READ` повторное чтение диапазона не видело фантомных строк.

**Metadata lock (MDL)** — блокировка структуры объекта (метаданных таблицы, представления, триггера), а не его данных. Удерживается до конца транзакции и является причиной большинства «зависших» DDL: общая механика разобрана в **[Блокировки метаданных (MDL)](../Concepts/metadata_locking.md)**.

**User-level lock (пользовательская блокировка)** — именованная блокировка уровня приложения (`GET_LOCK()`, `RELEASE_LOCK()`, `IS_FREE_LOCK()`, `IS_USED_LOCK()`, `RELEASE_ALL_LOCKS()`). Не связана с блокировками строк и метаданных; одно соединение может удерживать несколько именованных блокировок, блокировка освобождается явно или при разрыве соединения.

**`autocommit`** — режим, в котором каждый оператор является отдельной транзакцией (значение по умолчанию `1`). При `autocommit=0` изменения фиксируются только явным `COMMIT`; переключение сессии обратно в `autocommit=1` немедленно коммитит все открытые транзакции.

## Основные концепции

### Уровни изоляции

MariaDB поддерживает ровно четыре уровня: `READ-UNCOMMITTED`, `READ-COMMITTED`, `REPEATABLE-READ`, `SERIALIZABLE`. Уровень `SNAPSHOT`, существующий в MySQL, **в MariaDB отсутствует** — он не входит ни в грамматику `SET TRANSACTION`, ни в список допустимых значений переменных изоляции.

Значение по умолчанию — `REPEATABLE-READ` во всех четырёх линиях.

| Переменная | Статус | Примечание |
|---|---|---|
| `transaction_isolation` | актуальное имя, с MariaDB 11.1.1 | В MariaDB 10.11 **не существует** |
| `tx_isolation` | deprecated с MariaDB 11.1 | Работает во всех четырёх линиях |

Это различие ломает скрипты, написанные под MySQL: на 10.11 обращение к `@@transaction_isolation` завершится ошибкой.

```sql
-- Актуальный способ для 11.4 / 11.8 / 12.3
SELECT @@transaction_isolation;
-- → REPEATABLE-READ

-- Способ, работающий во всех четырёх линиях
SELECT @@tx_isolation;
-- → REPEATABLE-READ

-- Переключение уровня для следующей транзакции
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- Явно задать уровень в одной транзакции
START TRANSACTION ISOLATION LEVEL READ COMMITTED;
```

Обратите внимание на особенность `tx_isolation`: присваивание `SET @@tx_isolation=...` действует только на последующую транзакцию. Для постоянного действия сессии используйте `SET SESSION tx_isolation`.

### Автокоммит, неявные транзакции и свойства `START TRANSACTION`

`autocommit` по умолчанию равен `1`: каждый оператор — отдельная транзакция, и блокирующие чтения (`SELECT ... FOR UPDATE`, `LOCK IN SHARE MODE`) в этом режиме не удерживают блокировок после завершения оператора. При `autocommit=0` изменения фиксируются только `COMMIT`; переключение сессии обратно в `autocommit=1` немедленно коммитит все открытые транзакции.

`START TRANSACTION` (синоним `BEGIN`) неявно коммитит текущую транзакцию, если она была. Свойства:

```sql
-- Согласованный снимок сразу на старте транзакции (consistent read)
START TRANSACTION WITH CONSISTENT SNAPSHOT;

-- Режим доступа: READ WRITE (по умолчанию) или READ ONLY
START TRANSACTION READ ONLY;
```

*   `READ ONLY` позволяет движку применять оптимизации, недоступные для пишущих транзакций; DDL над временными таблицами в таком режиме запрещён.
*   `COMMIT AND CHAIN` / `ROLLBACK AND CHAIN` сразу начинают новую транзакцию с тем же уровнем изоляции; `RELEASE` закрывает соединение после завершения транзакции (дефолт определяется переменной `completion_type`).
*   Неявный `COMMIT` вызывают DDL (`CREATE`, `ALTER`, `DROP`), административные операторы (`FLUSH`, `RESET`, `OPTIMIZE`, `ANALYZE`, `CHECK`, `REPAIR`, `CACHE INDEX`), `BEGIN`/`START TRANSACTION` и `LOAD DATA INFILE`. Исключение — DDL над временными таблицами: они не коммитят транзакцию, но и не откатываются.
*   Транзакции нельзя использовать в хранимых функциях и триггерах; в хранимых процедурах и событиях `BEGIN` недопустим — только `START TRANSACTION`.
*   `@@in_transaction` — сессионная read-only переменная: `1` внутри транзакции, `0` вне.

### Gap locking и уровень изоляции

При `REPEATABLE-READ` (дефолт) InnoDB блокирует промежутки между индексированными записями. При `READ-COMMITTED` и `READ-UNCOMMITTED` gap locking отключён.

Два исключения, о которых важно знать при разборе блокировок:

- Проверка дубликатов по уникальному индексу берёт next-key lock **на каждом** уровне изоляции.
- Проверки ограничений внешних ключей не берут gap locks на `READ-COMMITTED`.

Начиная с MariaDB 10.3.38, 10.4.28, 10.5.19, 10.6.12, 10.7.8, 10.8.7, 10.9.5, 10.10.3, 11.0 и 10.11.2 MariaDB **больше не ослабляет** блокировку промежутков для уникальных индексов: поиск по всем колонкам уникального индекса по-прежнему берёт next-key lock (полный список версий — на странице `SET TRANSACTION`, вкладка «Current» против «< 11.0 / 10.11.2 / …»).

Переменная `innodb_locks_unsafe_for_binlog` (отключение gap locking для поисков и сканирований индексов) в MariaDB **устарела**; документация рекомендует вместо неё уровень `READ COMMITTED`.

Следствие для конфигурации: переключение базы на `READ-COMMITTED` уменьшает объём блокировок и число взаимоблокировок, но **не устраняет** блокировки на уникальных индексах. Рассчитывать на полное отсутствие next-key lock нельзя.

Ограничение на бинарный лог: сочетание `READ-COMMITTED`, `binlog_format=STATEMENT` и InnoDB недопустимо.

```sql
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
-- при binlog_format=STATEMENT:
-- → ERROR 1665 (HY000): Cannot execute statement: impossible to write to binary log...
```

Режимы `MIXED` и `ROW` такого ограничения не имеют.

### innodb_snapshot_isolation: изменение поведения между линиями

Это самая значимая версионная дельта в теме транзакций, и она попадает точно на границу наших линий поддержки.

Переменная `innodb_snapshot_isolation` (Global + Session, dynamic, boolean) включает обнаружение конфликтов типа write/write. Когда она включена, `UPDATE` или `DELETE` по строке, изменённой после создания снимка, приводит к ошибке и **откату всей транзакции** — как при взаимоблокировке.

| Версия | Значение по умолчанию |
|---|---|
| 10.11 LTS | `OFF` |
| 11.4 LTS | `OFF` |
| 11.8 LTS | `ON` |
| 12.3 LTS | `ON` |

Флаг появился в 10.6.18, 10.11.8, 11.0.6, 11.1.5, 11.2.4 и 11.4.2 со значением `OFF`; значение по умолчанию переключилось на `ON` с версии 11.6.2. То есть на 10.11 и 11.4 LTS после обновления до актуального патча он по-прежнему выключен, а на 11.8 и 12.3 включён по умолчанию.

Практическое следствие: приложение, использующее оптимистичную схему «прочитать, посчитать, записать» без явной блокировки, на 11.8 и 12.3 начнёт получать `ERROR 1020` там, где раньше молча перезаписывало данные. Это изменение именно **семантики `REPEATABLE READ`**, а не настройки производительности.

```sql
SELECT @@innodb_snapshot_isolation;
-- MariaDB 10.11 / 11.4: 0
-- MariaDB 11.8 / 12.3:  1

SELECT * FROM accounts WHERE id = 1 FOR UPDATE;   -- неявная блокировка строки
-- Явная блокировка делает поведение детерминированным независимо от флага
```

Если миграция на 11.8 или 12.3 невозможна сразу, флаг можно зафиксировать на время переходного периода, но это откладывает исправление приложения:

```ini
[mariadbd]
innodb_snapshot_isolation=OFF
```

> **Ограничение:** для распределённых XA-транзакций минимальный уровень — `REPEATABLE READ`; для XA рекомендуется `SERIALIZABLE`.

### Таймауты блокировок: три независимых механизма

MariaDB использует три разных переменных, и их путание — источник большинства диагностических ошибок.

| Переменная | Значение по умолчанию | Что ограничивает | Динамичность |
|---|---|---|---|
| `lock_wait_timeout` | `86400` (1 сутки) | Ожидание **метаданных** (MDL) | Global + Session |
| `innodb_lock_wait_timeout` | `50` | Ожидание **блокировки строки** | Global + Session |
| `innodb_deadlock_detect` | `1` | Поиск взаимоблокировок | Только Global |

**Важно:** страница Metadata Locking в документации утверждает, что значение по умолчанию `lock_wait_timeout` равно 31536000 (год). Это устаревшая формулировка — 31536000 является **максимумом**, а не значением по умолчанию. Ориентируйтесь на справочник системных переменных: по умолчанию `86400`, диапазон `0`–`31536000`, где `0` означает «не ждать».

```sql
SHOW VARIABLES LIKE 'lock_wait_timeout';
-- → lock_wait_timeout | 86400

SHOW VARIABLES LIKE 'innodb_lock_wait_timeout';
-- → innodb_lock_wait_timeout | 50
```

Для `innodb_lock_wait_timeout` значение `100000000` или выше означает бесконечное ожидание (а не «больше 100000000»), а `0` — не ждать вовсе. Диапазон `0`–`100000000` начиная с 10.6.3; тип `INT UNSIGNED`.

При истечении таймаута откатывается **оператор**, а не вся транзакция. Чтобы откатывалась транзакция, нужен `innodb_rollback_on_timeout=1`. На взаимоблокировки таймауты не распространяются — там работает детектор.

```ini
[mariadb]
# Строгий режим: откатывать транзакцию, а не только оператор.
# Переменная НЕ динамическая (Dynamic: No) — только командная строка/my.cnf,
# SET GLOBAL не поддерживается
innodb_rollback_on_timeout = ON
```

Таймауты блокировок не следует путать с закрытием простаивающих соединений — за это отвечает `wait_timeout`. Для зависших транзакций MariaDB имеет отдельный механизм:

```ini
[mariadbd]
idle_transaction_timeout       = 300
idle_write_transaction_timeout  = 120
idle_readonly_transaction_timeout = 0
```

Все три переменные появились в MariaDB 10.3, имеют значение по умолчанию `0` (без таймаута) и диапазон `0`–`31536000`. При срабатывании сервер **закрывает соединение**, и клиент получает `ERROR 2006 (HY000): MySQL server has gone away`. Если заданы и общий, и частный таймаут, частный имеет приоритет. Это самый прямой способ защиты от транзакций, оставленных открытыми приложением.

### WAIT и NOWAIT

Поддерживаются clauses `WAIT n` и `NOWAIT`, которые переопределяют `lock_wait_timeout` и `innodb_lock_wait_timeout` для конкретного оператора. Номер версии, в которой они появились, в официальной документации не указан — фиксируйте факт по факту на целевой версии.

Поддерживаются в: `ALTER TABLE`, `CREATE INDEX`, `DROP INDEX`, `DROP TABLE`, `LOCK TABLE`, `OPTIMIZE TABLE`, `RENAME TABLE`, `TRUNCATE TABLE`, `SELECT ... FOR UPDATE`, `SELECT ... LOCK IN SHARE MODE`. `WAIT 0` эквивалентен `NOWAIT`.

```sql
-- Не блокироваться и упасть сразу, если таблица занята
ALTER TABLE orders ADD COLUMN status VARCHAR(16), NOWAIT;
-- → ERROR 1205 (HY000): Lock wait timeout exceeded; try restarting transaction

-- Ждать не более 5 секунд
DROP INDEX idx_status ON orders, WAIT 5;
```

> [!warning] Код ошибки `NOWAIT` официально не документирован
> Документация MariaDB описывает `ERROR 1205 (HY000): Lock wait timeout exceeded; try restarting transaction` как ошибку **истечения таймаута** метаданных, но нигде не указывает, какой код возвращает именно `NOWAIT`. В справочнике кодов ошибок MariaDB диапазон 3500–3599 отсутствует, то есть код, который использует MySQL, в MariaDB не задокументирован. Проверьте фактическое поведение на целевой версии, прежде чем строить на нём парсер логов.

Также `NOWAIT` в MariaDB работает для `LOCK TABLES` и DDL. В документированный синтаксис `WAIT n | NOWAIT` представления и хранимые процедуры не входят — отдельного подтверждения, что MariaDB отвергает такой синтаксис или отличается здесь от MySQL, в документации нет.

### Пользовательские блокировки (user-level locks)

Механизм координации на уровне приложения — именованные блокировки, не связанные ни со строками, ни с метаданными:

```sql
-- Получить блокировку: 1 — получена, 0 — истёк таймаут, NULL — ошибка.
-- Таймаут задаётся в секундах, поддерживаются микросекунды
SELECT GET_LOCK('myapp:job:42', 30);

-- Проверить состояние
SELECT IS_FREE_LOCK('myapp:job:42');   -- 1 — свободна, 0 — занята, NULL — ошибка
SELECT IS_USED_LOCK('myapp:job:42');   -- ID соединения-держателя или NULL

-- Освободить: 1 — освобождена, 0 — не была взята этим соединением,
-- NULL — блокировки не существует
SELECT RELEASE_LOCK('myapp:job:42');
SELECT RELEASE_ALL_LOCKS();
```

Особенности:

*   Одно соединение может удерживать **несколько** именованных блокировок; блокировка освобождается явно через `RELEASE_LOCK()`/`RELEASE_ALL_LOCKS()` или автоматически при разрыве соединения.
*   Имя регистронезависимо; пустая строка или `NULL` в качестве имени возвращают `NULL` без действий.
*   `IS_FREE_LOCK()` и `RELEASE_LOCK()` небезопасны для statement-based репликации.
*   Плагин `metadata_lock_info` (см. ниже) показывает и пользовательские блокировки `GET_LOCK`.

### Диагностика блокировок

#### Что удерживает метаданные

Метаданные удерживаются до конца транзакции. Ни `SAVEPOINT`, ни частичный откат их не освобождают. В очередь встаёт и `LOCK TABLES ... WRITE`.

```sql
-- Не требует плагина, доступно при performance_schema=ON
SELECT OBJECT_TYPE, OBJECT_SCHEMA, OBJECT_NAME, LOCK_TYPE, LOCK_DURATION, LOCK_STATUS,
       SOURCE, OWNER_THREAD_ID
FROM performance_schema.metadata_locks
WHERE LOCK_STATUS = 'PENDING';
-- → PENDING-запись означает, что DDL ждёт метаданные
```

Значения `LOCK_STATUS`: `GRANTED`, `PENDING`, `TIMEOUT`, `KILLED`, `VICTIM`, `PRE_ACQUIRE_NOTIFY`, `POST_RELEASE_NOTIFY`.

Для детализации есть плагин `metadata_lock_info`, поставляемый с сервером, но не устанавливаемый по умолчанию:

```sql
INSTALL SONAME 'metadata_lock_info';

SELECT * FROM information_schema.metadata_lock_info;
-- → THREAD_ID | LOCK_MODE | LOCK_DURATION | LOCK_TYPE | TABLE_SCHEMA | TABLE_NAME

UNINSTALL SONAME 'metadata_lock_info';
```

Плагин показывает и пользовательские блокировки `GET_LOCK`. Его параметр `--metadata-lock-info` принимает `OFF`, `ON`, `FORCE`, `FORCE_PLUS_PERMANENT` при значении по умолчанию `ON`.

> **Важно:** `performance_schema` по умолчанию **выключен** в MariaDB, тогда как в MySQL он включён по умолчанию. Без `performance_schema=ON` в `my.cnf` диагностические представления пусты.

#### Что удерживает блокировки строк

```sql
SELECT trx.trx_mysql_thread_id AS conn_id,
       trx.trx_state,
       TIMESTAMPDIFF(SECOND, trx.trx_wait_started, NOW()) AS wait_sec,
       trx.trx_rows_locked,
       trx.trx_query
FROM information_schema.innodb_trx trx
WHERE trx.trx_state = 'LOCK WAIT'
ORDER BY trx.trx_wait_started;
-- → conn_id | trx_state  | wait_sec | trx_rows_locked | trx_query
-- → 412     | LOCK WAIT | 184      | 1               | UPDATE orders SET ...
```

Значения `TRX_STATE`: `RUNNING`, `LOCK WAIT`, `ROLLING BACK`, `COMMITTING`. Транзакции XA в `INNODB_TRX` **не хранятся** — для них используйте `XA RECOVER`.

Готовая агрегированная сводка есть в `sys`:

```sql
SELECT * FROM sys.innodb_lock_waits\G
```

Таблицы `INFORMATION_SCHEMA.INNODB_LOCKS` и `INNODB_LOCK_WAITS` в MariaDB присутствуют. `LOCK_MODE` принимает значения `S`, `X`, `IS`, `IX`, `S_GAP`, `X_GAP`, `IS_GAP`, `IX_GAP`, `AUTO_INC` — по ним видно, что именно удерживается: блокировка записи или промежутка. `INNODB_LOCK_WAITS` требует привилегии `PROCESS`.

```sql
SELECT l.lock_mode, l.lock_type, l.lock_table, l.lock_index,
       w.requesting_trx_id, w.blocking_trx_id
FROM information_schema.innodb_locks l
JOIN information_schema.innodb_lock_waits w ON l.lock_id = w.requested_lock_id;
```

#### Взаимоблокировки

```sql
SHOW ENGINE INNODB STATUS\G
```

Секции отчёта: `LATEST FOREIGN KEY ERROR` (только если ошибка была), `LATEST DETECTED DEADLOCK` (только если была), `TRANSACTIONS`.

Чтобы не терять историю взаимоблокировок, включите вывод в журнал ошибок — по умолчанию выключено:

```ini
[mariadbd]
innodb_print_all_deadlocks = ON
innodb_deadlock_detect    = ON
innodb_deadlock_report    = full
```

`innodb_deadlock_report` принимает `off`, `basic`, `full` и по умолчанию равен `full`; появился в MariaDB 10.6.0. Отключать `innodb_deadlock_detect` стоит только осознанно: в режиме `REPEATABLE-READ` без него взаимоблокировки не обнаруживаются и транзакции ждут до таймаута.

## Предварительные требования

Для полноценной диагностики блокировок необходимы:

```ini
[mariadbd]
performance_schema = ON
```

Это требование рестарта — переменная не динамическая. Без неё недоступны `performance_schema.metadata_locks`, `sys.innodb_lock_waits` и агрегаты по медленным запросам.

Права: `INNODB_LOCK_WAITS` требует привилегии `PROCESS`.

## Практические сценарии

### Сценарий 1. DDL «завис» на минутах

**Симптомы:** `ALTER TABLE` выполняется часами, в `SHOW PROCESSLIST` видно состояние `Waiting for table metadata lock`.

**Диагностика:**

```sql
-- 1. Кто ждёт
SELECT * FROM information_schema.processlist
WHERE info LIKE 'ALTER%' OR state LIKE '%metadata%'\G

-- 2. Что именно занято (performance_schema=ON)
SELECT OBJECT_SCHEMA, OBJECT_NAME, LOCK_TYPE, LOCK_DURATION, LOCK_STATUS, OWNER_THREAD_ID
FROM performance_schema.metadata_locks
WHERE LOCK_STATUS <> 'GRANTED';

-- 3. Кто удерживает метаданные
SELECT trx.trx_mysql_thread_id, trx.trx_started, trx.trx_state, trx.trx_query
FROM information_schema.innodb_trx trx
WHERE trx.trx_mysql_thread_id IN (SELECT OWNER_THREAD_ID FROM performance_schema.metadata_locks);
```

**Решение:**

```sql
-- Проверить возраст транзакции-держателя
SELECT TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS age_sec, trx_mysql_thread_id
FROM information_schema.innodb_trx WHERE trx_mysql_thread_id = 412;
-- → 18420: транзакция висит более 5 часов

-- Завершить её
KILL 412;
```

**Профилактика:**

1. Задать `idle_transaction_timeout` — это устраняет причину, а не симптом.
2. Применять `NOWAIT` к DDL в автоматизации: падение быстрее, чем неконтролируемое ожидание.
3. Не держать транзакции открытыми вокруг вызовов внешних систем.

### Сценарий 2. Массовый UPDATE вызывает лавину взаимоблокировок

**Симптомы:** `ERROR 1213 (40001): Deadlock found when trying to get lock; try restarting transaction`.

**Диагностика:**

```sql
SHOW ENGINE INNODB STATUS\G
-- Секция LATEST DETECTED DEADLOCK содержит обе транзакции и точный индекс конфликта
```

**Решение.** Три меры по убыванию приоритета:

1. Единый порядок доступа к строкам во всех частях приложения — основная причина взаимоблокировок это разный порядок.
2. Пересмотр уровня изоляции:

```sql
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
```

3. Массовую операцию дробить партиями с явными границами — см. **[Безопасные массовые изменения данных](../Concepts/safe_large_scale_data_modification.md)**.

```sql
-- Порция по 1000 строк с явной транзакцией на партию
START TRANSACTION;
UPDATE orders SET status = 'archived'
WHERE id BETWEEN 1 AND 1000;
COMMIT;
```

Ретрай транзакции после `ERROR 1213` обязателен: откатывается вся транзакция, а не оператор.

### Сценарий 3. Приложение оставляет транзакции открытыми

**Симптомы:** растёт `Innodb_row_lock_waits`, purge не успевает, размер undo логов растёт.

**Диагностика:**

```sql
SELECT trx_mysql_thread_id AS conn_id,
       TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS age_sec,
       trx_rows_locked, trx_query
FROM information_schema.innodb_trx
ORDER BY trx_started;

-- Счётчики ожиданий блокировок с момента старта сервера
SHOW GLOBAL STATUS LIKE 'Innodb_row_lock%';
-- Innodb_row_lock_current_waits, Innodb_row_lock_waits,
-- Innodb_row_lock_time, Innodb_row_lock_time_avg, Innodb_row_lock_time_max

SHOW GLOBAL STATUS LIKE 'Innodb_deadlocks';
```

PromQL-алерты по этим счётчикам — в **[Мониторинг MariaDB](monitoring.md)**.

**Решение:** включить серверные таймауты как страховку.

```ini
[mariadbd]
idle_transaction_timeout      = 300
idle_write_transaction_timeout = 120
```

**Валидация:** значение применяется к существующим соединениям, проверяется на сессии:

```sql
SET SESSION idle_transaction_timeout = 60;
START TRANSACTION;
SELECT SLEEP(90);
-- → ERROR 2006 (HY000): MySQL server has gone away: соединение закрыто по таймауту
```

Обратите внимание: приложение получит ошибку соединения, а не отказ запроса. Это осознанный размен — защита от накопления блокировок в ущерб корректности обработки ошибок на стороне клиента.

### Сценарий 4. Планирование DDL без блокировки окна

```sql
-- Строгая проверка: операция обязана пройти мгновенно
ALTER TABLE orders ADD COLUMN created_at DATETIME, ALGORITHM=INSTANT, NOWAIT;

-- Допустить ожидание до 30 секунд, затем отступить
ALTER TABLE orders ENGINE=InnoDB, ALGORITHM=INPLACE, LOCK=NONE, WAIT 30;
```

Комбинация `ALGORITHM` и `LOCK` подробно разобрана в **[Онлайн-DDL и metadata locks](online_schema_change.md)**.

## Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| DDL висит минутами | Удерживается MDL незакрытой транзакцией | `performance_schema.metadata_locks` со `LOCK_STATUS = 'PENDING'` | Найти и завершить транзакцию-держатель; настроить `idle_transaction_timeout` |
| `ERROR 1205` при обычном DML | Истёк `innodb_lock_wait_timeout` (50 с по умолчанию) | `sys.innodb_lock_waits` | Сократить критическую секцию транзакции; проверить индексы |
| `ERROR 1205` сразу при старте запроса | Сработал `NOWAIT`, а не таймаут | Проверить наличие `NOWAIT` в тексте DDL | Повторить с `WAIT n` или устранить конкуренцию |
| `ERROR 1213` массово | Разный порядок доступа к строкам | `LATEST DETECTED DEADLOCK` | Единый порядок; пересмотр уровня изоляции; ретрай |
| `ERROR 1020` после апгрейда на 11.8/12.3 | `innodb_snapshot_isolation=ON` по умолчанию | `SELECT @@innodb_snapshot_isolation` | Явные блокировки `FOR UPDATE` в приложении |
| `ERROR 2006` при паузе в транзакции | Сработал `idle_transaction_timeout` | `SHOW VARIABLES LIKE 'idle%transaction_timeout'` | Пересмотреть значение; приложение должно обрабатывать разрыв соединения |
| `@@transaction_isolation` не существует | MariaDB 10.11 | `SELECT @@version` | Использовать `@@tx_isolation` |
| `sys.innodb_lock_waits` пуст | `performance_schema` выключен | `SHOW VARIABLES LIKE 'performance_schema'` | Включить в `my.cnf` и перезапустить |

## Лучшие практики (Best Practices)

1. **Всегда включайте `performance_schema=ON`.** В MariaDB он выключен по умолчанию, и без него большинство диагностических представлений недоступно.
2. **Задайте `idle_transaction_timeout`.** Это единственная мера, устраняющая причину зависаний — открытые транзакции, — а не их последствия.
3. **Используйте `NOWAIT`/`WAIT n` в автоматизации DDL.** Ожидание в один год — поведение по умолчанию, а не защита.
4. **Явно задавайте `ALGORITHM` в DDL.** Указание алгоритма строго: неподдерживаемая операция завершится ошибкой, а не тихо выполнится через `COPY`.
5. **Держите уровень изоляции явным в конфигурации.** `REPEATABLE-READ` — дефолт, но для конкурентных нагрузок часто лучше `READ-COMMITTED`.
6. **Учитывайте `innodb_snapshot_isolation` при переходе на 11.8 и 12.3.** Значение по умолчанию меняется с `OFF` на `ON`; проверяйте приложение на оптимистичные схемы обновления.
7. **Включите `innodb_print_all_deadlocks`.** По умолчанию выключено; без него история взаимоблокировок не сохраняется.
8. **Не меняйте `lock_wait_timeout` в сторону уменьшения без анализа.** Значение по умолчанию 86400 — это защита от каскадного отказа при массовых DDL; снижение до 50 с превращает каждую неудачную миграцию в отказ в обслуживании.

## Дополнительная информация

### Источники

- [Transactions | MariaDB Documentation](https://mariadb.com/docs/server/reference/sql-statements/transactions)
- [START TRANSACTION | MariaDB Documentation](https://mariadb.com/docs/server/reference/sql-statements/transactions/start-transaction)
- [Metadata Locking | MariaDB Documentation](https://mariadb.com/docs/server/reference/sql-statements/transactions/metadata-locking)
- [Transaction Timeouts | MariaDB Documentation](https://mariadb.com/docs/server/reference/sql-statements/transactions/transaction-timeouts)
- [WAIT and NOWAIT | MariaDB Documentation](https://mariadb.com/docs/server/reference/sql-statements/transactions/wait-and-nowait)
- [InnoDB Lock Modes | MariaDB Documentation](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-lock-modes)
- [InnoDB System Variables | MariaDB Documentation](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-system-variables)
- [Server System Variables | MariaDB Documentation](https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables)
- [InnoDB Recovery Modes | MariaDB Documentation](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-troubleshooting/innodb-recovery-modes)
- [SET TRANSACTION | MariaDB Documentation](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/set-commands/set-transaction)
- [GET_LOCK | MariaDB Documentation](https://mariadb.com/docs/server/reference/sql-functions/secondary-functions/miscellaneous-functions/get_lock)
- [Incompatibilities Between MariaDB 11.4 and MySQL 8](https://mariadb.com/docs/release-notes/community-server/about/compatibility-and-differences/incompatibilities-and-feature-differences-between-mariadb-11-4-and-mysql-8)

### Смежные темы

- **[ACID](../Concepts/acid.md)** — теоретическая база изоляции и долговечности.
- **[Блокировки метаданных (MDL)](../Concepts/metadata_locking.md)** — общий механизм блокировки структуры.
- **[Онлайн-DDL и metadata locks](online_schema_change.md)** — планирование изменений схемы без блокировки окна.
- **[Журнал предзаписи](../Concepts/write_ahead_log.md)** — механизм, обеспечивающий откат транзакций.
- **[Безопасные массовые изменения данных](../Concepts/safe_large_scale_data_modification.md)** — стратегии пакетных операций.
- **[Управление памятью MariaDB](memory_management.md)** — буферный пул и purge, ограниченные долгими транзакциями.
- **[Мониторинг MariaDB](monitoring.md)** — метрики блокировок и транзакций.
- **[Движки хранения MariaDB](storage_engines.md)** — транзакционность InnoDB против Aria и MyISAM.