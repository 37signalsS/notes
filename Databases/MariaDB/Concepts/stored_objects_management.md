# Управление хранимыми объектами в MariaDB/MySQL: Отладка и автоматизация

## Определения

*   **Event Scheduler (Планировщик событий):** Встроенный в MariaDB механизм для запуска SQL-задач по расписанию. Работает как демон-поток (`event_scheduler`), обрабатывающий события из системной таблицы `mysql.event`.
*   **Definer:** Учетная запись, от имени которой выполняется хранимый объект. Определяет контекст безопасности выполнения и проверяется при каждом вызове.
*   **SIGNAL / RESIGNAL:** Операторы для генерации пользовательских ошибок и управления исключениями внутри хранимых программ. Позволяют прерывать выполнение с определенным кодом ошибки и сообщением.
*   **Performance Schema:** Набор таблиц для глубокого мониторинга выполнения инструкций внутри хранимых программ. Собирает статистику по времени выполнения, количеству вызовов и использованию ресурсов.
*   **DECLARE HANDLER:** Конструкция для обработки исключений (ошибок SQL и условий `NOT FOUND`) внутри хранимых программ. Поддерживает действия `CONTINUE` (продолжить выполнение), `EXIT` (прервать блок) и `UNDO` (откатить изменения, только в MariaDB).
*   **SQLSTATE:** Пятибуквенный код стандарта SQL для классификации ошибок. Используется в `SIGNAL`, `RESIGNAL` и `DECLARE HANDLER` для определения типов обрабатываемых исключений.
*   **ON COMPLETION:** Параметр события, определяющий его поведение после завершения расписания. `NOT PRESERVE` (по умолчанию) — событие удаляется; `PRESERVE` — событие сохраняется в состоянии `COMPLETED`.
*   **Event Metadata:** Служебная информация о событии: время последнего и следующего запуска, количество выполнений, состояние. Доступна через `information_schema.EVENTS` и `SHOW EVENTS`.

---

## Базовые концепции

### Архитектура Event Scheduler

Event Scheduler в MariaDB реализован как отдельный поток-демон, обрабатывающий события из системной таблицы `mysql.event`. Понимание архитектуры критично для надежной автоматизации.

#### Компоненты системы

1. **Демон event_scheduler:** Главный поток, проверяющий расписание событий каждую секунду. Состояние: `ON` (активен), `OFF` (выключен), `DISABLED` (отключен и не может быть включен без перезапуска сервера).
2. **Системная таблица `mysql.event`:** Хранит определения всех событий, включая расписание, тело SQL и метаданные. Реплицируется между узлами вsätze-топологии.
3. **Системный пользователь `event_scheduler`:** Внутренняя учетная запись, от имени которой выполняются события. Невидима в `SHOW PROCESSLIST` при использовании `SHOW FULL PROCESSLIST`.

#### Режимы расписания

MariaDB поддерживает несколько типов расписания:

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| `AT` | Однократное выполнение в指定ленное время | `AT '2026-01-15 03:00:00'` |
| `EVERY` | Периодическое выполнение | `EVERY 1 HOUR` |
| `EVERY ... STARTS ... ENDS` | Периодическое с ограничением диапазона | `EVERY 1 DAY STARTS '2026-01-01' ENDS '2026-12-31'` |

#### Важные параметры событий

- **`ON COMPLETION { PRESERVE | NOT PRESERVE }`:** Определяет поведение после завершения расписания. `NOT PRESERVE` (по умолчанию) удаляет событие; `PRESERVE` сохраняет его в таблице `mysql.event` с状态 `COMPLETED`.
- **`ENABLE | DISABLE | DISABLE ON SLAVE`:** Управляет активностью события. `DISABLE ON SLAVE` используется в репликации для предотвращения выполнения на ведомом узле.
- **`EVENT_SCHEMA`:** База данных, в контексте которой выполняется событие. Влияет на разрешение имен объектов в теле события.
- **`DEFINER`:** Пользователь, от имени которого выполняется событие. Должен существовать и иметь необходимые привилегии.

#### Поведение при перезапуске сервера

События сохраняются в `mysql.event` и автоматически восстанавливаются при перезапуске сервера (если `event_scheduler = ON`). Состояние `LAST_EXECUTED` обновляется при каждом выполнении.

### Обработка исключений: DECLARE HANDLER

`DECLARE HANDLER` — ключевой механизм для создания надежных хранимых программ. Без обработки исключений процедура завершится при первой ошибке, potentially оставляя незавершенные транзакции или некonsистентные данные.

#### Типы обработчиков

| Действие | Поведение | Применение |
| :--- | :--- | :--- |
| `CONTINUE` | Выполняет обработчик и продолжает выполнение со следующей инструкции | Логирование ошибок, пропуск неkritisных операций |
| `EXIT` | Прерывает выполнение текущего блока `BEGIN...END` | Гарантированный откат, предотвращение повреждения данных |
| `UNDO` | Откатывает изменения в текущем блоке и выполняет обработчик (только MariaDB) | Сложные транзакционные сценарии |

#### Типы условий

- **SQL exceptions:** Ошибки SQL (дублирование ключа, нарушение ссылочной целостности и т.д.). Указываются через `SQLSTATE` или `MYSQL_ERRNO`.
- **SQL warnings:** Предупреждения (не Fatal). Указываются через `SQLWARNING` или `SQLEXCEPTION`.
- **`NOT FOUND`:** Условие, возникающее при использовании курсора, когда данные закончились (fetchAll).
- **Именованные условия:** Пользовательские условия, определяемые через `DECLARE ... CONDITION FOR`.

#### Приоритет обработки

При возникновении исключения MariaDB проверяет обработчики в порядке:
1. Текущий блок `BEGIN...END`
2. Внешние блоки (вложенность)
3. Глобальный обработчик (если определен)

Если подходящий обработчик не найден, ошибка передается клиенту.

### SIGNAL и RESIGNAL: управление ошибками

`SIGNAL` и `RESIGNAL` позволяют генерировать пользовательские ошибки с произвольными кодами SQLSTATE и сообщениями. Это основной механизм для реализации бизнес-логики проверок и валидации.

#### SIGNAL vs RESIGNAL

| Оператор | Контекст | Назначение |
| :--- | :--- | :--- |
| `SIGNAL` | Любая хранимая программа | Генерация новой ошибки (например, проверка входных параметров) |
| `RESIGNAL` | Только внутри `DECLARE HANDLER` | Переотправка текущей ошибки с измененным SQLSTATE или сообщением |

#### Стандартные диапазоны SQLSTATE

- **`08xxx`**: Ошибки соединения (connection exceptions)
- **`23xxx`**: Нарушения целостности (integrity constraint violations)
- **`25xxx`**: Ошибки транзакций (invalid transaction state)
- **`42xxx`**: Синтаксические ошибки и ошибки выполнения (syntax error or access rule violation)
- **`45xxx`**: Пользовательские ошибки (unhandled user-defined exception) — рекомендуемый диапазон для приложений

#### Практические паттерны

1. **Валидация входных параметров:** `SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Value must be positive'`
2. **Бизнес-логика:** Проверка баланса, прав доступа, состояния заказа
3. **Аудит ошибок:** `RESIGNAL` с добавлением контекста в `MESSAGE_TEXT`

### Мониторинг через Performance Schema

Performance Schema собирает детальную статистику по выполнению хранимых программ без влияния на производительность (асинхронный сбор).

#### Ключевые таблицы для хранимых объектов

| Таблица | Назначение |
| :--- | :--- |
| `events_statements_summary_by_program` | Агрегированная статистика по программам (процедуры, функции, триггеры, события) |
| `events_statements_summary_by_digest` | Статистика по уникальным запросам (включая тела хранимых объектов) |
| `threads` | Информация о потоках, выполняющих хранимые программы |
| `metadata_locks` | Текущие мета-блокировки, влияющие на DDL и DML |

#### Метрики для алертинга

- **SUM_TIMER_WAIT:** Общее время выполнения (в наносекундах). Используйте деление на `1000000000` для перевода в миллисекунды.
- **COUNT_STAR:** Общее количество вызовов (успешных и ошибочных).
- **COUNT_ERROR:** Количество ошибок. Высокое значение указывает на проблемы.
- **SUM_NO_INDEX_USED:** Количество запросов без использования индексов (потенциальная проблема производительности).

### Модель безопасности Definer

Definer определяет контекст безопасности выполнения хранимого объекта. Понимание модели критично для предотвращения уязвимостей.

#### Правила проверки

1. При создании объекта с `DEFINER` пользователь должен иметь привилегию `SUPER` (или `SET_USER_ID` в MariaDB 10.5.9+).
2. При выполнении объекта проверяется, что **текущий пользователь** имеет привилегию `EXECUTE` для объекта **и** что Definer существует.
3. Если Definer был удален, объект становится недоступным (ошибка "Access denied").

#### Рекомендации по безопасности

- Используйте выделенного техничого пользователя (например, `app_procedures@localhost`) вместо `root`.
- Минимизируйте привилегии Definer: только `EXECUTE` на необходимых объектах.
- Регулярно проверяйте существование Definer: `SELECT DEFINER FROM information_schema.ROUTINES`.

---

## Практические сценарии

### 1. Отладка хранимой логики

В MariaDB/MySQL нет встроенного пошагового отладчика в CLI. Основной метод — **инструментация**.

#### Метод: Таблица логов

```sql
CREATE TABLE debug_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    msg TEXT,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE PROCEDURE my_proc(p_val INT)
BEGIN
    INSERT INTO debug_log(msg) VALUES (CONCAT('Start my_proc with val: ', p_val));
    -- Основная логика
    IF p_val < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Value must be positive';
    END IF;
    INSERT INTO debug_log(msg) VALUES ('End my_proc');
END;
```

#### Метод: Пользовательские переменные

```sql
SET @debug = 1;
-- В процедуре:
IF @debug THEN SELECT 'Current state: step 1'; END IF;
```

#### Метод: SELECT для отладки ( временный)

```sql
-- Внутри процедуры для вывода промежуточных значений
SELECT p_val AS debug_val, NOW() AS debug_time;
-- Внимание: SELECT внутри процедуры может влиять на производительность
```

#### Метод: Просмотр определения объекта

```sql
-- Просмотр исходного кода процедуры
SHOW CREATE PROCEDURE my_proc;

-- Просмотр функции
SHOW CREATE FUNCTION my_func;

-- Просмотр триггера
SHOW CREATE TRIGGER my_trigger;

-- Информация из information_schema
SELECT ROUTINE_NAME, ROUTINE_DEFINITION, CREATED, LAST_ALTERED
FROM information_schema.ROUTINES
WHERE ROUTINE_SCHEMA = 'my_db' AND ROUTINE_NAME = 'my_proc';
```

### 2. Эксплуатация Event Scheduler

Для работы планировщика он должен быть включен на уровне сервера.

#### Настройка и проверка статуса

```sql
-- Проверить статус
SELECT @@event_scheduler;
-- Включить
SET GLOBAL event_scheduler = ON;
-- Проверить в конфигурации (постоянно)
-- my.cnf: event_scheduler = ON
```

#### Пример события для очистки логов (раз в сутки)

```sql
CREATE EVENT purge_old_logs
ON SCHEDULE EVERY 1 DAY
STARTS (TIMESTAMP(CURRENT_DATE) + INTERVAL 1 DAY + INTERVAL 3 HOUR) -- 3:00 AM
DO
  DELETE FROM system_logs WHERE created_at < NOW() - INTERVAL 30 DAY;
```

#### Сложное расписание: диапазон дат и ON COMPLETION

```sql
-- Ежедневный отчет за январь 2026, с сохранением после завершения
CREATE EVENT daily_january_report
ON SCHEDULE EVERY 1 DAY
STARTS '2026-01-01 06:00:00'
ENDS '2026-01-31 23:59:59'
ON COMPLETION PRESERVE
ENABLE
COMMENT 'Ежедневный отчет за январь'
DO
BEGIN
    INSERT INTO reports (report_date, report_data)
    SELECT CURDATE(), COUNT(*) FROM orders WHERE order_date = CURDATE();
END;
```

#### Управление событиями

```sql
-- Включить/выключить событие
ALTER EVENT purge_old_logs DISABLE;
ALTER EVENT purge_old_logs ENABLE;

-- Переименовать событие
ALTER EVENT old_name RENAME TO new_name;

-- Изменить расписание
ALTER EVENT purge_old_logs
ON SCHEDULE EVERY 6 HOUR;

-- Удалить событие
DROP EVENT IF EXISTS purge_old_logs;

-- Просмотр всех событий в базе данных
SHOW EVENTS FROM my_db;

-- Просмотр деталей события
SELECT EVENT_NAME, EVENT_TYPE, EXECUTE_AT, INTERVAL_VALUE, INTERVAL_FIELD,
       STATUS, LAST_EXECUTED, EVENT_DEFINITION
FROM information_schema.EVENTS
WHERE EVENT_SCHEMA = 'my_db';
```

#### Параллельная защита с GET_LOCK

```sql
CREATE EVENT safe_periodic_job
ON SCHEDULE EVERY 5 MINUTE
DO
BEGIN
    DECLARE lock_result INT;
    -- Попытка получить блокировку с таймаутом 1 секунда
    SET lock_result = GET_LOCK('periodic_job_lock', 1);
    IF lock_result = 1 THEN
        -- Блокировка получена, выполняем работу
        CALL heavy_maintenance_procedure();
        -- Освобождение блокировки (автоматически при завершении сессии)
    END IF;
    -- Если lock_result = 0, предыдущий запуск еще не завершен
END;
```

### 3. Мониторинг через Performance Schema

Для отслеживания производительности объектов MariaDB 10.x+ использует Performance Schema.

#### Время выполнения хранимых процедур

```sql
SELECT OBJECT_NAME, COUNT_STAR, SUM_TIMER_WAIT/1000000000 AS SUM_WAIT_MS
FROM performance_schema.events_statements_summary_by_program
WHERE OBJECT_TYPE = 'PROCEDURE'
ORDER BY SUM_WAIT_MS DESC;
```

#### Поиск медленных запросов внутри хранимых объектов

```sql
-- Топ-10 запросов по времени выполнения
SELECT DIGEST_TEXT, COUNT_STAR, SUM_TIMER_WAIT/1000000000 AS SUM_WAIT_MS,
       SUM_NO_INDEX_USED
FROM performance_schema.events_statements_summary_by_digest
WHERE SCHEMA_NAME IS NOT NULL
ORDER BY SUM_TIMER_WAIT DESC
LIMIT 10;
```

#### Мониторинг активных хранимых программ

```sql
-- Текущие выполняющиеся хранимые программы
SELECT t.THREAD_ID, t.PROCESSLIST_ID, t.PROCESSLIST_USER,
       t.PROCESSLIST_HOST, t.PROCESSLIST_DB, t.PROCESSLIST_COMMAND,
       t.PROCESSLIST_TIME, t.PROCESSLIST_STATE
FROM performance_schema.threads t
WHERE t.TYPE = 'FOREGROUND'
  AND t.PROCESSLIST_COMMAND != 'Sleep';
```

#### Проверка блокировок

```sql
-- Текущие мета-блокировки (влияют на DDL и DML)
SELECT OBJECT_TYPE, OBJECT_SCHEMA, OBJECT_NAME, LOCK_TYPE, LOCK_STATUS
FROM performance_schema.metadata_locks
WHERE OBJECT_SCHEMA NOT IN ('performance_schema', 'information_schema', 'mysql');
```

### 4. Обработка исключений: DECLARE HANDLER

#### Базовый паттерн: логирование ошибок и продолжение

```sql
CREATE PROCEDURE safe_insert(p_id INT, p_name VARCHAR(100))
BEGIN
    DECLARE CONTINUE HANDLER FOR 1062  -- Duplicate entry
    BEGIN
        INSERT INTO error_log (proc_name, error_msg, ts)
        VALUES ('safe_insert', CONCAT('Duplicate ID: ', p_id), NOW());
    END;

    INSERT INTO users (id, name) VALUES (p_id, p_name);
END;
```

#### Паттерн: откат и выход при критической ошибке

```sql
CREATE PROCEDURE transfer_funds(p_from INT, p_to INT, p_amount DECIMAL(10,2))
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        INSERT INTO audit_log (action, details, ts)
        VALUES ('transfer_failed', CONCAT(p_from, ' -> ', p_to, ': ', p_amount), NOW());
    END;

    START TRANSACTION;
        UPDATE accounts SET balance = balance - p_amount WHERE id = p_from;
        UPDATE accounts SET balance = balance + p_amount WHERE id = p_to;
    COMMIT;
END;
```

#### Паттерн: обработка NOT FOUND с курсором

```sql
CREATE PROCEDURE process_all_orders()
BEGIN
    DECLARE v_order_id INT;
    DECLARE v_done INT DEFAULT 0;
    DECLARE cur CURSOR FOR SELECT id FROM orders WHERE status = 'pending';
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;

    OPEN cur;
    read_loop: LOOP
        FETCH cur INTO v_order_id;
        IF v_done THEN
            LEAVE read_loop;
        END IF;
        CALL process_single_order(v_order_id);
    END LOOP;
    CLOSE cur;
END;
```

#### Пользовательские ошибки с SIGNAL

```sql
CREATE PROCEDURE withdraw(p_account_id INT, p_amount DECIMAL(10,2))
BEGIN
    DECLARE v_balance DECIMAL(10,2);

    SELECT balance INTO v_balance FROM accounts WHERE id = p_account_id;

    IF v_balance IS NULL THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Account not found',
            MYSQL_ERRNO = 1001;
    END IF;

    IF v_balance < p_amount THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Insufficient funds',
            MYSQL_ERRNO = 1002;
    END IF;

    UPDATE accounts SET balance = balance - p_amount WHERE id = p_account_id;
END;
```

#### RESIGNAL с добавлением контекста

```sql
CREATE PROCEDURE complex_operation()
BEGIN
    DECLARE CONTINUE HANDLER FOR SQLEXCEPTION
    BEGIN
        -- Добавляем контекст к текущей ошибке
        RESIGNAL SET MESSAGE_TEXT = CONCAT('Error in complex_operation: ', MESSAGE_TEXT);
    END;

    -- Основная логика
    CALL another_procedure();
END;
```

---

## Рекомендации SRE

### Безопасность

1. **Definer:** Избегайте создания объектов с `DEFINER = 'root'@'localhost'`. Используйте выделенного технического пользователя с минимально необходимыми правами. Регулярно проверяйте существование Definer через `information_schema.ROUTINES`.
2. **Привилегии:** Минимизируйте права: `EXECUTE` для вызова процедур, `SELECT`/`INSERT`/`UPDATE`/`DELETE` только на необходимые таблицы. Избегайте `ALL PRIVILEGES`.
3. **Динамический SQL:** Используйте `PREPARE/EXECUTE` с параметризованными запросами для предотвращения SQL-инъекций. Никогда не конкатенируйте пользовательский ввод в SQL.

### Производительность

4. **Concurrency в Events:** По умолчанию события не проверяют, завершилась ли предыдущая итерация. Используйте `GET_LOCK()`, чтобы предотвратить одновременный запуск одного и того же события.
5. **Индексы:** Убедитесь, что все запросы внутри хранимых объектов используют индексы. Проверяйте через `EXPLAIN` перед деплоем.
6. **Батчинг:** При обработке больших объемов данных используйте пакетную обработку (LIMIT + цикл), чтобы избежать длительных блокировок и переполнения памяти.

### Надежность

7. **Обработка исключений:** Всегда используйте `DECLARE ... HANDLER` для обработки исключений, чтобы процедура не оставляла "повисших" транзакций при сбое.
8. **Транзакции:** Группируйте связанные операции в транзакции. Используйте `START TRANSACTION` явно, а не полагайтесь на авто-коммит.
9. **Логирование:** Включайте логирование критических операций в таблицы аудита для отслеживания выполнения и диагностики проблем.

### Поддержка и миграция

10. **Версионирование:** Храните исходный код всех хранимых объектов в Git. Используйте инструменты миграций (Flyway, Liquibase) для деплоя.
11. **Тестирование:** Тестируйте хранимые объекты в изолированной среде перед деплоем в production. Включайте edge-кейсы и проверку границ значений.
12. **Документация:** Добавляйте комментарии к процедурам и функциям, описывающие назначение, параметры и возвращаемые значения.

---

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Событие (Event) не запускается** | `event_scheduler` выключен. | Выполните `SET GLOBAL event_scheduler = ON;`. |
| **Ошибка "Access denied" при вызове** | У пользователя нет прав `EXECUTE` или Definer не существует. | Проверьте права (`SHOW GRANTS FOR user`) и существование учетной записи Definer. |
| **Процедура тормозит всю БД** | Отсутствие индексов в запросах внутри процедуры или долгие блокировки. | Проверьте `Slow Query Log` и активные блокировки через `metadata_lock_info` (MariaDB). |
| **SIGNAL генерирует неизвестную ошибку** | Неправильный формат SQLSTATE (5 символов, начинается с A-Z, кроме 00000). | Проверьте формат: `SQLSTATE` должен быть ровно 5 символов. Используйте диапазон `45xxx` для пользовательских ошибок. |
| **RESIGNAL не работает** | Использование вне блока `DECLARE HANDLER`. | `RESIGNAL` допустим только внутри обработчика исключений. |
| **Событие удалилось после выполнения** | Параметр `ON COMPLETION NOT PRESERVE` (по умолчанию). | Используйте `ON COMPLETION PRESERVE`, если событие должно сохраняться. |
| **Definer не существует** | Пользователь был удален, но объект остался. | Пересоздайте объект с существующим Definer или измените Definer: `ALTER DEFINER=...`. |
| **Performance Schema не собирает данные** | Плагин отключен или нет привилегий. | Проверьте `performance_schema` = ON и grants для пользователя мониторинга. |
| **Курсор не работает** | Неправильная обработка `NOT FOUND`. | Добавьте `DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;` и проверьте `LEAVE` в цикле. |
| **GET_LOCK не работает** | Разные сессии или таймаут истек. | `GET_LOCK` привязан к сессии. Увеличьте таймаут или проверьте, что вызовы происходят в одной транзакции. |

---

## Ограничения и особенности

### Event Scheduler

1. **Однопоточность:** Демон event_scheduler — один поток. Многочисленные события выполняются последовательно, что может вызвать задержки при большом количестве событий.
2. **Точность расписания:** Проверка расписания происходит каждую секунду. Минимальный интервал `EVERY` — 1 секунда. Для подсекундных интервалов используйте `SLEEP()` внутри тела события (не рекомендуется).
3. **Ошибка при выполнении:** Если тело события содержит ошибку, событие продолжает работать по расписанию. Ошибки логируются в error log.
4. **Репликация:** События реплицируются в statement-based репликации. В row-based репликации события не реплицируются автоматически.
5. **DROP EVENT при несуществующей базе данных:** Если `EVENT_SCHEMA` указывает на несуществующую базу данных, событие не будет создано (или будет удалено при восстановлении).

### SIGNAL/RESIGNAL

6. **Длина MESSAGE_TEXT:** Максимальная длина — 128 символов (ограничение протокола MySQL).
7. **Вложенность:** `RESIGNAL` нельзя использовать в обработчике, который сам вызывается для обработки `RESIGNAL` (защита от бесконечной рекурсии).
8. **Пользовательские SQLSTATE:** Должны начинаться с буквы, кроме `00000` (успех). Рекомендуемый диапазон — `45xxx`.
9. **MYSQL_ERRNO:** Опциональный параметр для установки номера ошибки MySQL. Должен соответствовать допустимому диапазону (1-65535).

### DECLARE HANDLER

10. **UNDO:** Доступен только в MariaDB, не в MySQL. В MySQL используйте `CONTINUE` или `EXIT` с явным откатом.
11. **Приоритет:** Обработчики проверяются от внутреннего к внешнему. Если несколько обработчиков подходят, используется первый найденный.
12. **Транзакции:** `EXIT` handler прерывает выполнение, но не откатывает транзакцию автоматически (если не вызван `ROLLBACK` явно).

### Performance Schema

13. **Влияние на производительность:** Сбор статистики имеет минимальное влияние, но при большом количестве инструкций может потреблять память. Настройте `performance_schema_max_*` переменные для ограничения.
14. **Сброс статистики:** Статистика накапливается с момента перезапуска сервера. Для сброса выполните `TRUNCATE TABLE performance_schema.events_statements_summary_by_program`.

---

## Дополнительная информация

### См. также
- **[Мониторинг MariaDB](../monitoring.md)** — общие подходы к метрикам и настройке mysqld_exporter.
- **[Конфигурация MariaDB](../configuration.md)** — параметры сервера, включая event_scheduler.
- **[Stored Objects Overview](../../Concepts/stored_objects_overview.md)** — общие принципы хранимых объектов.
- **[Безопасность MariaDB](../security/index.md)** — RBAC, аудит и шифрование.
- **[Отладка в PostgreSQL](../../PostgreSQL/Concepts/stored_objects_debugging.md)** — сравнение подходов к отладке хранимых объектов.
