# Блокировки и взаимоблокировки в MySQL

Специфичные для движка InnoDB механизмы управления конкурентным доступом. Общие теоретические основы (ACID, уровни изоляции) описаны в руководстве **[Стратегии отката в базах данных](../Concepts/rollback_strategies.md)**.

---

## Определения

**Блокировка (Lock)** — механизм предотвращения одновременного изменения одних и тех же данных несколькими транзакциями для обеспечения целостности.

**Взаимоблокировка (Deadlock)** — ситуация, при которой две или более транзакции ожидают ресурсы, захваченные друг другом, образуя циклическую зависимость.

**Metadata Lock (MDL)** — блокировка на уровне словаря данных (структуры таблиц), предотвращающая изменение схемы таблицы (DDL), пока она используется другими транзакциями (DML/SELECT).

**Явная блокировка (Explicit Lock)** — блокировка, запрошенная напрямую через SQL-оператор (`SELECT ... FOR UPDATE`, `SELECT ... LOCK IN SHARE MODE`).

**Неявная блокировка (Implicit Lock)** — блокировка, которую InnoDB приобретает автоматически при выполнении `INSERT`, `UPDATE`, `DELETE` или `REPLACE` для защиты изменяемых строк.

**Блокировка намерения (Intention Lock)** — маркер на уровне таблицы, сигнализирующий о том, что транзакция намерена приобрести блокировку строк в этой таблице. Позволяет движку быстро определить возможность конфликта без проверки каждой строки.

**Autocommit** — режим, при котором каждый SQL-оператор автоматически оборачивается в отдельную транзакцию. При `autocommit=1` (дефолт) блокировки освобождаются после завершения оператора; при `autocommit=0` блокировки удерживаются до явного `COMMIT` или `ROLLBACK`.

---

## Базовые концепции

### 1. Взаимосвязь блокировок и уровней изоляции

Уровень изоляции транзакции определяет, какие блокировки и в каких случаях InnoDB применяет:

| Уровень изоляции | Dirty Reads | Non-Repeatable Reads | Phantom Reads | Тип блокировок |
| :--- | :--- | :--- | :--- | :--- |
| **READ UNCOMMITTED** | Возможны | Возможны | Возможны | Только Record Locks (минимум) |
| **READ COMMITTED** | Нет | Возможны | Возможны | Record Locks (без Gap Locks) |
| **REPEATABLE READ** (дефолт) | Нет | Нет | Нет | Next-Key Locks (Record + Gap) |
| **SERIALIZABLE** | Нет | Нет | Нет | SELECT превращается в `SELECT ... LOCK IN SHARE MODE` |

**Важно:** На уровне `REPEATABLE READ` InnoDB использует **Next-Key Locks** для поиска и сканирования индексов, что полностью решает проблему фантомного чтения (Phantom Reads). При точном совпадении по уникальному индексу Next-Key Lock деградирует до **Record Lock**.

### 2. Механизм обнаружения взаимоблокировок

InnoDB автоматически обнаруживает дедлоки и откатывает одну из транзакций (обычно ту, которая внесла меньше изменений).

**Ключевой параметр:**
- `innodb_deadlock_detect = ON` (дефолт): включает активный поиск дедлоков через граф ожиданий. На высоконагруженных системах с сотнями конкурентных потоков это создает дополнительную нагрузку на CPU из-за постоянного сканирования графа.
- `innodb_deadlock_detect = OFF`: отключает активный поиск. В этом случае дедлоки обнаруживаются только по таймауту `innodb_lock_wait_timeout`. **Рекомендуется** только для систем с низкой конкурентностью или когда приоритетнее минимизировать CPU-нагрузку.

### 3. Intention Locks (Блокировки намерения)

InnoDB использует две разновидности intention-блокировок на уровне таблицы:
- **IS (Intention Shared):** Транзакция собираетсяacquire Shared Lock на строках таблицы (`SELECT ... LOCK IN SHARE MODE`).
- **IX (Intention Exclusive):** Транзакция собираетсяacquire Exclusive Lock на строках таблицы (`SELECT ... FOR UPDATE`, `UPDATE`, `DELETE`).

**Совместимость:** IS совместим с IS и IX; IX совместим только с IS. Exclusive Table Lock (`X`) несовместим ни с чем.

### 4. Автоматические блокировки автоинкремента

При вставке в столбец `AUTO_INCREMENT` InnoDB приобретает специальную блокировку (`AUTO-INC Lock`) для гарантии последовательности значений.

**Параметр:** `innodb_autoinc_lock_mode`
- **0 (Traditional):** Требует блокировки таблицы на всю вставку. Безопасно, но медленно для массовых `INSERT`.
- **1 (Consecutive, дефолт до 8.0):** Блокировка удерживается до конца `INSERT` (не транзакции). Ускоряет массовые вставки, но может вызвать дедлоки при откате.
- **2 (Interleaved, дефолт MySQL 8.0+):** Блокировка удерживается минимально необходимый промежуток времени. Не блокирует таблицу, но значения `AUTO_INCREMENT` могут быть не последовательными при откате транзакции.

### 5. FOR SHARE vs FOR UPDATE

- `SELECT ... FOR UPDATE`: Приобретает **exclusive** Record Lock. Никакая другая транзакция не может изменить или добавить блокировку на эти строки.
- `SELECT ... LOCK IN SHARE MODE`: Приобретает **shared** Record Lock. Другие транзакции могут читать строки, но не могут изменять их до тех пор, пока первая транзакция не завершится.

---

## Классификация блокировок InnoDB

### 1. Блокировки строк (Record Locks)
Блокируют конкретную запись в индексе.
- **Пример:** `SELECT * FROM users WHERE id = 10 FOR UPDATE;`
- **Особенность:** Даже если таблица не имеет первичного ключа, InnoDB создает скрытый кластерный индекс и блокирует запись в нем.

### 2. Gap Locks (Блокировки промежутков)
Блокируют пространство *между* индексными записями, перед первой или после последней записью.
- **Цель:** Предотвращение вставки новых строк (фантомное чтение) другими транзакциями.
- **Применение:** Используется только на уровне изоляции **Repeatable Read** (дефолт в MySQL) и при поиске без точного совпадения по уникальному индексу.
- **Пример:** `SELECT * FROM users WHERE id BETWEEN 10 AND 20 FOR UPDATE;` заблокирует вставку пользователя с `id=15`, даже если его не существует.

### 3. Next-Key Locks
Комбинация **Record Lock** на индексную запись и **Gap Lock** на промежуток *перед* этой записью.
- **Механика:** InnoDB использует Next-Key Locks для поиска и сканирования индексов, что полностью решает проблему фантомного чтения (Phantom Reads).
- **Важно:** Если запрос использует уникальный индекс с точным совпадением (Unique Index Search), Next-Key Lock деградирует до Record Lock.

### 4. Metadata Locks (MDL)
Работают на уровне сервера MySQL (SQL Layer).
- **Shared MDL:** Удерживается любым `SELECT`, `INSERT`, `UPDATE`. Позволяет нескольким транзакциям читать/писать данные одновременно.
- **Exclusive MDL:** Требуется для `ALTER TABLE`, `DROP TABLE`, `TRUNCATE`.
- **Проблема:** Если долгий `SELECT` удерживает Shared MDL, выполнение `ALTER TABLE` встает в очередь (Exclusive MDL), а *все последующие* даже короткие `SELECT` встают в очередь за `ALTER TABLE`. Это может привести к мгновенному исчерпанию пула соединений.

---

## Практические сценарии

### Сценарий 1: Искусственное создание и анализ взаимоблокировки

**Цель:** Наблюдение циклической зависимости и понимание механизма выбора жертвы.

**Шаг 1: Создание таблицы и запуск первой транзакции**
```sql
CREATE TABLE accounts (
    id INT PRIMARY KEY,
    balance DECIMAL(10,2)
) ENGINE=InnoDB;

INSERT INTO accounts VALUES (1, 1000), (2, 2000);
```
```bash
# В первом терминале
mysql -u root -p -e "
START TRANSACTION;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
-- Не делайте COMMIT, оставьте транзакцию открытой
SELECT SLEEP(60);
"
# → result: Транзакция T1 ожидает 60 секунд после блокировки строк
```

**Шаг 2: Запуск второй транзакции с обратным порядком**
```bash
# Во втором терминале
mysql -u root -p -e "
START TRANSACTION;
UPDATE accounts SET balance = balance - 200 WHERE id = 2;
UPDATE accounts SET balance = balance + 200 WHERE id = 1;
-- Не делайте COMMIT, оставьте транзакцию открытой
SELECT SLEEP(60);
"
# → result: ERROR 1213 (40001): Deadlock found when trying to get lock; try restarting transaction
```

**Шаг 3: Анализ через SHOW ENGINE INNODB STATUS**
```sql
SHOW ENGINE INNODB STATUS\G
```
```text
-- → ожидаемый фрагмент вывода:
LATEST DETECTED DEADLOCK
------------------------
*** (1) TRANSACTION:
TRANSACTION 12345, ACTIVE 45 sec updating
mysql tables in use 1, locked 1
LOCK WAIT 4 lock struct(s), heap size 1136, 2 row lock(s)
MySQL thread id 5, OS thread handle 140735000000000, query id 100 localhost root Updating
UPDATE accounts SET balance = balance - 200 WHERE id = 2

*** (1) WAITING FOR THIS LOCK TO BE GRANTED:
Record lock, heap no 2 
-- table: test.accounts
-- index: PRIMARY
-- len: 4; match: 2
-- where: id = 2

*** (2) TRANSACTION:
TRANSACTION 12346, ACTIVE 45 sec updating
mysql tables in use 1, locked 1
4 lock struct(s), heap size 1136, 3 row lock(s)
MySQL thread id 6, OS thread handle 140735000000000, query id 101 localhost root Updating
UPDATE accounts SET balance = balance + 200 WHERE id = 1

*** (2) HOLDS THE LOCK(S):
Record lock, heap no 2 
-- table: test.accounts
-- index: PRIMARY
-- len: 4; match: 1
-- where: id = 2

*** WE ROLL BACK TRANSACTION (1)
```

**Валидация:**
- Одна транзакция получила `ERROR 1213`
- В `SHOW ENGINE INNODB STATUS` присутствует секция `LATEST DETECTED DEADLOCK`
- Выход показывает `HOLDS THE LOCK(S)` для жертвы и `WAITING FOR THIS LOCK TO BE GRANTED` для блокированного

**Принцип выбора жертвы:** InnoDB откатывает транзакцию, которая внесла меньше изменений (меньше row locks), чтобы минимизировать потери. В примере: если T1 обновила 1 строку, а T2 — 2 строки, жертвой выбирается T1.

### Сценарий 2: Демонстрация Gap Lock (фантомное чтение)

**Цель:** Показать, как Next-Key/Gap Locks предотвращают появление фантомных строк при отсутствии индекса.

**Шаг 1: Создание таблицы без индекса на фильтрующем столбце**
```sql
CREATE TABLE sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id INT,
    created_at DATETIME,
    payload TEXT
) ENGINE=InnoDB;

INSERT INTO sessions VALUES ('sess_001', 42, NOW(), 'data1'), ('sess_002', 42, NOW(), 'data2');
```
```bash
# В первом терминале
mysql -u root -p -e "
START TRANSACTION;
SELECT * FROM sessions WHERE user_id = 42 FOR UPDATE;
-- Транзакция остаётся открытой
SELECT SLEEP(60);
"
```

**Шаг 2: Попытка вставить фантомную строку из второго терминала**
```bash
# Во втором терминале
mysql -u root -p -e "
INSERT INTO sessions (session_id, user_id, created_at, payload)
VALUES ('sess_003', 42, NOW(), 'phantom');
-- Вставка заблокирована, запрос висит
"
# → result: Запрос зависает (Waiting for table metadata lock или row lock)
```

**Шаг 3: Переключение на READ COMMITTED для устранения Gap Lock**
```bash
# В третьем терминале (с отдельным соединением)
mysql -u root -p -e "
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT * FROM sessions WHERE user_id = 42 FOR UPDATE;
-- Теперь Next-Key Locks не создаются; 
-- только существующие строки блокируются
SELECT SLEEP(60);
"
```

**Шаг 4: Вставка из второго терминала теперь работает**
```bash
# Во втором терминале (соединение с READ COMMITTED)
mysql -u root -p -e "
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
INSERT INTO sessions (session_id, user_id, created_at, payload)
VALUES ('sess_003', 42, NOW(), 'phantom');
-- → result: Query OK, 1 row affected
"
```

**Валидация:**
- При `REPEATABLE READ` вставка фантомной строки блокируется
- При `READ COMMITTED` вставка проходит, так как Gap Lock не создается
- Это подтверждает, что переход на `READ COMMITTED` снижает количество дедлоков, но допускает фантомные чтения

### Сценарий 3: MDL-блокировка при долгом SELECT

**Цель:** Демонстрация классической проблемы MDL, когда долгий `SELECT` мешает `ALTER TABLE`.

**Шаг 1: Создание таблицы и запуск долгого SELECT**
```sql
CREATE TABLE logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    message TEXT,
    created_at DATETIME
) ENGINE=InnoDB;

INSERT INTO logs SELECT NULL, CONCAT('log ', RAND()), NOW() FROM information_schema.columns LIMIT 1000000;
```
```bash
# В первом терминале
mysql -u root -p -e "
SELECT SQL_NO_CACHE COUNT(*) FROM logs WHERE message LIKE '%log%';
-- Долгий запрос удерживает Shared MDL
SELECT SLEEP(60);
"
```

**Шаг 2: Попытка ALTER TABLE из второго терминала**
```bash
# Во втором терминале
mysql -u root -p -e "
ALTER TABLE logs ADD COLUMN severity INT DEFAULT 0;
-- Запрос зависнет в статусе 'Waiting for table metadata lock'
"
# → result: Запрос висит, SHOW PROCESSLIST показывает 'Waiting for table metadata lock'
```

**Шаг 3: Диагностика блокирующего процесса**
```sql
-- В третьем терминале
SELECT * FROM performance_schema.metadata_locks WHERE object_name = 'logs'\G
-- → result:
-- OBJECT_NAME: logs
-- LOCK_TYPE: SHARED_READ
-- LOCK_STATUS: GRANTED
-- OWNER_THREAD_ID: <thread_id долгого SELECT>

-- Поиск PID процесса
SELECT thread_id, PROCESSLIST_ID, PROCESSLIST_USER, PROCESSLIST_HOST, PROCESSLIST_INFO
FROM performance_schema.threads
WHERE thread_id = <owner_thread_id>;
-- → result: PROCESSLIST_ID = 15

-- Проверка SHOW PROCESSLIST
SHOW PROCESSLIST;
-- → result: строка с Id=15, Status='Sleep', Command='Query', Info='SELECT ...'
```

**Шаг 4: Освобождение MDL**
```sql
-- Опция A: Дождаться завершения SELECT (не подходит для production)
-- Опция B: Завершить блокирующий процесс
KILL 15;
-- → result: Query OK, 0 rows affected

-- ALTER TABLE немедленно продолжает выполнение
-- Проверка
SHOW PROCESSLIST;
-- → строка с ALTER TABLE теперь имеет Status='altering' или 'Creating index'
```

**Валидация:**
- `SHOW PROCESSLIST` показывает статус `Waiting for table metadata lock` для `ALTER TABLE`
- `performance_schema.metadata_locks` показывает владельца блокировки
- `KILL <pid>` немедленно освобождает MDL и позволяет DDL продолжить

**Профилактика:**
- Никогда не выполняйте `ALTER TABLE` во время пиковой нагрузки без `LOCK=NONE`
- Используйте `pt-online-schema-change` или `gh-ost` для больших таблиц
- Устанавливайте сессионный `lock_wait_timeout` перед DDL:
  ```sql
  SET SESSION lock_wait_timeout = 30;
  ALTER TABLE logs ADD COLUMN severity INT DEFAULT 0;
  -- Если MDL не будет освобождена за 30 секунд — запрос завершится ошибкой
  ```

### Сценарий 4: Bulk UPDATE без индекса (полная блокировка таблицы)

**Цель:** Показать, почему отсутствие индекса на условии `WHERE` превращает `UPDATE` в полное сканирование таблицы с массовыми Next-Key Locks.

**Шаг 1: Создание таблицы без индекса на user_id**
```sql
CREATE TABLE user_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id INT,
    is_active TINYINT(1),
    last_seen DATETIME
) ENGINE=InnoDB;

INSERT INTO user_sessions SELECT UUID(), FLOOR(RAND()*1000), 1, NOW() FROM information_schema.columns LIMIT 50000;
-- Индекс на user_id отсутствует
```

**Шаг 2: Выполнение UPDATE без индекса**
```bash
mysql -u root -p -e "
UPDATE user_sessions SET is_active = 0 WHERE user_id = 42;
-- InnoDB сканирует ВСЕ строки таблицы
-- и удерживает Next-Key Locks на всех из них
"
# → result: Query OK, 500 rows affected (0.85 sec)
```

**Шаг 3: Диагностика блокировок во время UPDATE**
```sql
-- В параллельном соединении во время UPDATE
SELECT * FROM sys.innodb_lock_waits\G
-- → result: ожидающие транзакции, заблокированные массовым UPDATE

-- Проверка locks в performance_schema
SELECT 
    LOCK_STATUS, LOCK_MODE, OBJECT_SCHEMA, OBJECT_NAME, INDEX_NAME
FROM performance_schema.data_locks
WHERE OBJECT_SCHEMA = DATABASE() AND OBJECT_NAME = 'user_sessions';
-- → result: множество X-блокировок на индексе PRIMARY и Gap Locks между ними
```

**Шаг 4: Решение — добавление индекса**
```sql
-- Создание индекса
CREATE INDEX idx_user_sessions_user ON user_sessions (user_id);
-- → result: Query OK, 0 rows affected

-- Повторный UPDATE
UPDATE user_sessions SET is_active = 0 WHERE user_id = 42;
-- → result: Query OK, 500 rows affected (0.02 sec) — значительно быстрее
-- Блокируются только строки с user_id = 42 (Record Locks)
```

**Валидация:**
- Без индекса: `UPDATE` затрагивает все строки таблицы
- С индексом: `UPDATE` затрагивает только нужные строки
- Количество блокировок в `performance_schema.data_locks` резко снижается

---

## Анализ взаимоблокировок (Deadlocks)

InnoDB автоматически обнаруживает дедлоки и откатывает одну из транзакций (обычно ту, которая внесла меньше изменений).

### Практическое руководство по SHOW ENGINE INNODB STATUS

Для детального анализа выполните:
```sql
SHOW ENGINE INNODB STATUS\G
```

Ищите секцию **LATEST DETECTED DEADLOCK**. Разбор типичного вывода:

1.  **TRANSACTION (1) / (2):** Данные о транзакциях (ID, активные запросы, количество заблокированных строк).
2.  **WAITING FOR THIS LOCK TO BE GRANTED:** Тип блокировки, которую ждет транзакция.
    - `lock_mode X locks rec but not gap`: Ожидание Record Lock (постоянная запись).
    - `lock_mode X waiting`: Ожидание Next-Key Lock.
3.  **HOLDS THE LOCK(S):** Список блокировок, которые уже удерживаются транзакцией-конкурентом.
4.  **WE ROLL BACK TRANSACTION (1/2):** Указание на то, какая транзакция была выбрана жертвой.

### Мониторинг блокировок в реальном времени (sys schema)

```sql
-- Кто кого блокирует прямо сейчас?
SELECT * FROM sys.innodb_lock_waits;

-- Детальный перечень всех активных блокировок InnoDB (MySQL 8.0+)
SELECT 
    LOCK_STATUS,
    LOCK_MODE,
    OBJECT_SCHEMA,
    OBJECT_NAME,
    INDEX_NAME,
    LOCK_DATA
FROM performance_schema.data_locks
WHERE LOCK_STATUS = 'GRANTED'
  AND OBJECT_SCHEMA NOT IN ('mysql', 'sys', 'performance_schema', 'information_schema');

-- Суммарная статистика по типам ожиданий
SELECT event_name, count_star, time_waited FROM performance_schema.events_waits_summary_global_by_event_name 
WHERE event_name LIKE 'wait/io/table/%' ORDER BY time_waited DESC;
```

### Статистика по времени блокировок строк

```sql
-- Глобальные счетчики блокировок InnoDB
SHOW GLOBAL STATUS LIKE 'Innodb_row_lock%';
-- → result:
-- Innodb_row_lock_time:         общее время ожидания блокировок (миллисекунды)
-- Innodb_row_lock_time_avg:     среднее время ожидания одной блокировки
-- Innodb_row_lock_waits:        количество попыток ожидания блокировки

-- Детальная метрика через information_schema (MySQL 8.0+)
SELECT * FROM information_schema.INNODB_METRICS 
WHERE NAME IN ('lock_row_lock_time', 'lock_row_lock_time_avg', 'lock_row_lock_waits');
```

---

## Практические советы (SRE Guide)

### Как минимизировать блокировки и дедлоки
1.  **Держите транзакции короткими:** Чем дольше транзакция, тем выше вероятность конфликта.
2.  **Соблюдайте порядок:** Всегда обновляйте таблицы и строки в одном и том же порядке во всех частях приложения.
3.  **Индексируйте поля фильтрации:** Если запрос `UPDATE/DELETE` не использует индекс, InnoDB заблокирует **все строки** таблицы (Next-Key Locks на весь диапазон).
4.  **Используйте READ COMMITTED:** Если бизнес-логика позволяет, переход с `Repeatable Read` на `Read Committed` отключает Gap Locks, что значительно снижает количество дедлоков.
5.  **Настройка таймаутов:**
    - `innodb_lock_wait_timeout`: Время ожидания блокировки строки (дефолт 50с, в высоконагруженных системах лучше снизить до 5–10с).
    - `lock_wait_timeout`: Время ожидания MDL (дефолт 1 год! Рекомендуется ограничить сессионно перед DDL).
    - `innodb_deadlock_detect`: ON по умолчанию. OFF только для низко-конкурентных окружений.
6.  **Используйте `FOR UPDATE SKIP LOCKED`:** Для очередей задач позволяет пропускать заблокированные строки вместо ожидания.
    ```sql
    -- Получение следующей необработанной задачи без ожидания блокировки
    SELECT * FROM job_queue 
    WHERE status = 'pending' 
    ORDER BY created_at 
    LIMIT 1 
    FOR UPDATE SKIP LOCKED;
    ```

### Диагностика Metadata Lock (MDL)
Если вы видите в `SHOW PROCESSLIST` статус `Waiting for table metadata lock`:
1.  Найдите ID транзакции, удерживающей MDL:
    ```sql
    SELECT * FROM performance_schema.metadata_locks WHERE object_name = 'my_table';
    ```
2.  Найдите PID процесса, соответствующий этой транзакции, и завершите его (`KILL <pid>`), чтобы разблокировать DDL.

---

## Устранение неисправностей (Troubleshooting)

| Симптом | Возможная причина | Первый шаг диагностики |
| :--- | :--- | :--- |
| **ERROR 1213: Deadlock found** | Циклическая зависимость между транзакциями | `SHOW ENGINE INNODB STATUS\G` — секция `LATEST DETECTED DEADLOCK` |
| **Запрос висит на `Waiting for table metadata lock`** | Долгий SELECT удерживает Shared MDL | `SELECT * FROM performance_schema.metadata_locks` |
| **Высокий `Innodb_row_lock_time_avg`** | Долгие транзакции, отсутствие индексов | `SHOW GLOBAL STATUS LIKE 'Innodb_row_lock%'`, `EXPLAIN` запроса |
| **Массовый рост заблокированных строк** | UPDATE/DELETE без индекса на WHERE | `performance_schema.data_locks` — проверка количества X-блокировок |
| **Постоянные дедлоки на одном запросе** | Несоблюдение порядка обновления таблиц | Аудит порядка UPDATE в приложении |
| **`canceling statement due to lock wait timeout`** | Транзакция ожидала блокировку дольше `innodb_lock_wait_timeout` | Увеличение таймаута или оптимизация транзакций |

---

## Дополнительная информация

### Границы применимости и ограничения

1. **MDL и хранимые процедуры:** Внутри хранимых процедур MDL удерживается на все объекты, к которым происходит обращение, до завершения процедуры. Длительные процедуры могут блокировать DDL на своих таблицах.
2. **Информационная схема:** Запросы к `information_schema` могут удерживать кратковременные MDL. При высокой частоте таких запросов возможны каскадные задержки.
3. **Флаг `NOWAIT` и `SKIP LOCKED`:** `SELECT ... FOR UPDATE NOWAIT` немедленно возвращает ошибку, если блокировка недоступна. `SKIP LOCKED` пропускает заблокированные строки. Оба варианта доступны с MySQL 8.0.
4. **`innodb_lock_wait_timeout` vs `lock_wait_timeout`:** Первый относится к блокировкам строк InnoDB (Record/Gap/Next-Key), второй — к MDL. Значения таймаутов не связаны.
5. **Блокировки в replica-экземплярах:** На репликах SQL Thread выполняет транзакции последовательно, поэтому блокировки на репликах возникают реже, но при конфликте могут вызвать задержку репликации (`Seconds_Behind_Master` растет).

### См. также
- **[Индексы в MySQL](./indexing.md)** — влияние типов индексов на блокировки.
- **[Оптимизатор MySQL](./optimizer_mechanisms.md)** — как планы выполнения влияют на захват ресурсов.
- **[Обслуживание и обновления](./maintenance-and-upgrades.md)** — безопасное выполнение DDL.
