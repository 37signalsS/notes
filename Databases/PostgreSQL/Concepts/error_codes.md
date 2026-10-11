# Справочник кодов ошибок PostgreSQL (SQLSTATE)

**Актуально для:** PostgreSQL 14–18 (список по Appendix A документации PG 18.6)

## Определения

*   **SQLSTATE** — пятизначный код ошибки по стандарту SQL (например, `53300`). Первые два символа — класс, последние три — конкретное условие в классе.
*   **Condition name** — символьное имя условия для PL/pgSQL (`EXCEPTION WHEN unique_violation THEN ...`); регистр не важен.
*   **Класс** — первые два символа SQLSTATE: `00` — успех, `01` — warning, `02` — no data, `08` — connection exception, `22` — data exception, `23` — constraint violation, `28` — authorization, `40` — transaction rollback, `42` — syntax/access rule, `53` — insufficient resources, `55` — object not in prerequisite state, `57` — operator intervention, `58` — system error, `HV` — FDW, `P0` — PL/pgSQL, `XX` — internal error.
*   **`GET STACKED DIAGNOSTICS`** — оператор получения деталей текущей ошибки внутри обработчика `EXCEPTION` (`RETURNED_SQLSTATE`, `MESSAGE_TEXT`, `CONSTRAINT_NAME`).

## Предпосылки

Для работы с кодами ошибок и их мониторинга необходимо:

- **`log_error_verbosity = verbose`** в `postgresql.conf` — выводит SQLSTATE, `DETAIL`, `HINT`, `CONTEXT` и исходный файл/функцию в серверный лог (см. [Конфигурация для наблюдаемости](../Operations/observability.md#конфигурация-для-глубокой-наблюдаемости)).
- **Расширение `pg_stat_statements`** — сбор статистики ошибок на уровне запросов:
  ```ini
  shared_preload_libraries = 'pg_stat_statements'
  pg_stat_statements.track = all
  ```
  и `CREATE EXTENSION pg_stat_statements;` в каждой БД. Параметр `track = all` включает DDL- и utility-операторы (ошибки в DDL попадают в статистику).
- **Роль `pg_monitor`** или `pg_read_all_stats` — доступ к `pg_stat_statements`, `pg_stat_activity` и другим представлениям мониторинга без суперпользователя.
- **Синхронизация времени** (Chrony или systemd-timesyncd) — корректные временные метки в логах для корреляции с событиями приложения.

## Базовые концепции

### Структура сообщения об ошибке

```
ERROR:  duplicate key value violates unique constraint "orders_pkey"
SQLSTATE: 23505
```

*   Текст — человекочитаемый, **локализуемый** (может меняться от версии к версии и при переводе).
*   SQLSTATE — стабильный между релизами; приложения должны тестировать **код**, а не текст.
*   Имя объекта (таблица, колонка, ограничение) передаётся отдельным полем — не вытаскивать его из текста. Полное покрытие отдельных полей гарантировано для класса `23` (integrity constraint violation).

### Почему коды важнее текста

1.  Стабильность: текст меняется при локализации и между мажорными версиями; код — нет.
2.  Программная обработка: retry при `40001`/`40P01`, reconnect при `08006`/`57P03`, обработка дубликата при `23505`.
3.  Логирование: `log_error_verbosity = verbose` добавляет SQLSTATE, DETAIL, HINT, CONTEXT и исходный файл/функцию к серверному логу.

## Справочник частых кодов

### Соединение и аутентификация (классы 08, 28, 53, 57)

| SQLSTATE | Condition name | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- |
| `08006` | `connection_failure` | Обрыв соединения | Сеть, перезапуск сервера, таймаут; retry с backoff |
| `08001` | `sqlclient_unable_to_establish_sqlconnection` | Клиент не может установить соединение | Сервер недоступен, firewall, неверный порт/хост |
| `08004` | `sqlserver_rejected_establishment_of_sqlconnection` | Сервер отклонил соединение | `pg_hba.conf` не пропускает; `listen_addresses` |
| `08P01` | `protocol_violation` | Нарушение протокола | Несовместимость клиентской библиотеки и сервера |
| `28000` | `invalid_authorization_specification` | Не указана аутентификация | Пустой пользователь/база |
| `28P01` | `invalid_password` | Неверный пароль | Проверить `pg_authid`, SCRAM-SHA-256 |
| `53300` | `too_many_connections` | Исчерпан `max_connections` | Пулер (PgBouncer/Pgpool), `max_connections`, `reserved_connections` (PG 17+) |
| `57P03` | `cannot_connect_now` | Сервер в процессе старта/recovery | Дождаться; проверить `pg_is_in_recovery()` |

### Ограничения целостности (класс 23)

| SQLSTATE | Condition name | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- |
| `23502` | `not_null_violation` | NULL в NOT NULL-колонке | `DEFAULT`, валидация на входе |
| `23503` | `foreign_key_violation` | Нет родительской строки | Порядок вставок, `ON DELETE` политика |
| `23505` | `unique_violation` | Дубликат уникального ключа | `ON CONFLICT`, идемпотентность повторов |
| `23514` | `check_violation` | Нарушение CHECK | Валидация на входе |
| `23P01` | `exclusion_violation` | Нарушение EXCLUDE | Пересечение диапазонов/геоданных |

### Синтаксис и объекты (класс 42)

| SQLSTATE | Condition name | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- |
| `42601` | `syntax_error` | Синтаксическая ошибка | Исправить SQL |
| `42501` | `insufficient_privilege` | Нет прав | `GRANT`; роли `pg_read_all_data`/`pg_write_all_data` |
| `42703` | `undefined_column` | Колонка не существует | Опечатка, `search_path`, неприменённая миграция |
| `42P01` | `undefined_table` | Таблица не существует | То же; проверить схему |
| `42883` | `undefined_function` | Функция не существует | Расширение не установлено, перегрузка аргументов |
| `42702` | `ambiguous_column` | Колонка неоднозначна | Квалифицировать `table.column` |
| `42725` | `ambiguous_function` | Неоднозначная функция | Два расширения или схемы с одинаковыми функциями; `DROP FUNCTION IF EXISTS` или qualification по схеме |
| `42P07` | `duplicate_table` | Таблица уже существует | `IF NOT EXISTS`, порядок миграций |
| `42701` | `duplicate_column` | Колонка уже существует | Миграция дублирует колонку |
| `42P02` | `undefined_parameter` | Параметр не определён | Подготовленный запрос без привязки |
| `42704` | `undefined_object` | Объект не существует | Схема/тип/домен не создан |

### Данные (класс 22)

| SQLSTATE | Condition name | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- |
| `22P02` | `invalid_text_representation` | Невалидное текстовое представление | `'abc'` → integer; приведение типов |
| `22012` | `division_by_zero` | Деление на ноль | `NULLIF(denominator, 0)` |
| `22003` | `numeric_value_out_of_range` | Выход за диапазон типа | `bigint` вместо `integer`, `numeric` |
| `22001` | `string_data_right_truncation` | Строка длиннее поля | Увеличить длину `varchar` |
| `22023` | `invalid_parameter_value` | Невалидное значение параметра | Проверить аргументы функции |
| `22007` | `invalid_datetime_format` | Невалидный формат даты/времени | ISO-формат, `to_timestamp` с маской |
| `22024` | `unterminated_c_string` | Незавершённая строка | Экранирование кавычек |
| `22032` | `invalid_json_text` | Невалидный JSON (PG 18) | Валидация JSON на входе |

### Транзакции (классы 25, 40)

| SQLSTATE | Condition name | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- |
| `25P01` | `no_active_sql_transaction` | Нет активной транзакции | `BEGIN` перед оператором |
| `25P02` | `in_failed_sql_transaction` | Транзакция в состоянии aborted | `ROLLBACK`; в текущей транзакции можно только откат |
| `25P03` | `idle_in_transaction_session_timeout` | Превышен лимит `idle in transaction` | `idle_in_transaction_session_timeout` на роли |
| `25P04` | `transaction_timeout` | Превышен лимит транзакции (PG 17) | `transaction_timeout` на роли |
| `40001` | `serialization_failure` | Конфликт сериализации (SSI) | Повтор транзакции с экспоненциальной задержкой |
| `40P01` | `deadlock_detected` | Deadlock | Единый порядок обновлений; retry |

### Ресурсы и лимиты (классы 53, 54)

| SQLSTATE | Condition name | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- |
| `53100` | `disk_full` | Диск заполнен | Очистка, WAL/slots/bloat, масштабирование |
| `53200` | `out_of_memory` | Нехватка памяти | `work_mem` бюджет, `overcommit_memory=2` |
| `53400` | `configuration_limit_exceeded` | Превышен конфигурационный лимит | `max_connections`, `max_locks_per_transaction` |
| `54000` | `program_limit_exceeded` | Превышен программный лимит | Сложность запроса, число колонок/аргументов |
| `54001` | `statement_too_complex` | Запрос слишком сложен | Упростить запрос |
| `54011` | `too_many_columns` | Слишком много колонок | Нормализация |

### Объекты в использовании (класс 55)

| SQLSTATE | Condition name | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- |
| `55P03` | `lock_not_available` | Блокировка недоступна | `lock_timeout`, разбор блокирующих сессий |
| `55006` | `object_in_use` | Объект в использовании | Дождаться завершения операции |
| `55P02` | `cant_change_runtime_param` | Параметр нельзя менять в runtime | Контекст параметра (`postmaster` — restart) |

### Вмешательство оператора и системные (классы 57, 58, XX)

| SQLSTATE | Condition name | Описание | Типичная причина и решение |
| :--- | :--- | :--- | :--- |
| `57000` | `operator_intervention` | Произвольное вмешательство оператора | `pg_ctlcluster restart`, `pg_terminate_backend` |
| `57014` | `query_canceled` | Запрос отменён (`statement_timeout`, `pg_cancel_backend`) | Оптимизация запроса, таймауты |
| `57P01` | `admin_shutdown` | Административное выключение | Плановое обслуживание |
| `57P02` | `crash_shutdown` | Выключение после краха | Восстановление, проверка целостности |
| `57P04` | `database_dropped` | База удалена | — |
| `57P05` | `idle_session_timeout` | Превышен лимит idle-сессии (PG 14+) | `idle_session_timeout` |
| `58030` | `io_error` | Ошибка ввода-вывода | Диск, файловая система |
| `58P01` | `undefined_file` | Файл не найден | Расширение `.so`, `shared_preload_libraries` |
| `XX000` | `internal_error` | Внутренняя ошибка | Баг PostgreSQL; лог + баг-репорт |
| `XX001` | `data_corrupted` | Повреждение данных | amcheck, восстановление из бэкапа |
| `XX002` | `index_corrupted` | Повреждение индекса | `REINDEX`, восстановление |

### FDW (класс HV) и PL/pgSQL (класс P0)

| SQLSTATE | Condition name | Описание |
| :--- | :--- | :--- |
| `HV000` | `fdw_error` | Общая ошибка FDW |
| `HV00N` | `fdw_unable_to_establish_connection` | FDW не может подключиться к внешнему источнику |
| `HV00R` | `fdw_table_not_found` | Внешняя таблица не найдена |
| `P0001` | `raise_exception` | `RAISE EXCEPTION` в PL/pgSQL |
| `P0002` | `no_data_found` | `SELECT INTO` не вернул строк |
| `P0003` | `too_many_rows` | `SELECT INTO` вернул больше одной строки |
| `P0004` | `assert_failure` | `ASSERT` не выполнен |

### Конфигурация и системные ошибки (класс F)

| SQLSTATE | Condition name | Описание |
| :--- | :--- | :--- |
| `F0000` | `config_file_error` | Синтаксическая ошибка в `postgresql.conf` или `pg_hba.conf` |
| `F0001` | `lock_file_exists` | Файл блокировки (`postmaster.pid`) существует при запуске; удалить при отсутствии процесса PostgreSQL |

## Практические сценарии

### Сценарий: Обработка ошибок в приложении

```python
# psycopg3: retry на транзакционных конфликтах
import psycopg, time
for attempt in range(5):
    try:
        with conn.transaction():
            conn.execute("UPDATE accounts SET balance = balance - 100 WHERE id = 1")
        break
    except psycopg.errors.SerializationFailure:      # 40001
        time.sleep(0.1 * 2 ** attempt); continue
    except psycopg.errors.DeadlockDetected:          # 40P01
        time.sleep(0.1 * 2 ** attempt); continue
```

### Сценарий: RAISE с SQLSTATE в PL/pgSQL

```sql
CREATE FUNCTION charge(p_amount numeric) RETURNS void AS $$
BEGIN
  IF p_amount <= 0 THEN
    RAISE EXCEPTION 'amount must be positive'
      USING ERRCODE = 'check_violation';   -- или SQLSTATE '23514'
  END IF;
END;
$$ LANGUAGE plpgsql;
```

В обработчике — детали через `GET STACKED DIAGNOSTICS`:

```sql
BEGIN
  ...
EXCEPTION
  WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_sqlstate = RETURNED_SQLSTATE,
                             v_msg = MESSAGE_TEXT,
                             v_constraint = CONSTRAINT_NAME;
    RAISE NOTICE 'Error %: % (constraint %)', v_sqlstate, v_msg, v_constraint;
END;
```

**Важно:** `WHEN OTHERS` не ловит `QUERY_CANCELED` (отмена по `statement_timeout`/`pg_cancel_backend`) и `ASSERT_FAILURE` — их ловить только явно по имени.

### Сценарий: Поиск ошибок в логе по SQLSTATE

```bash
grep -oP 'SQLSTATE: \K[0-9A-Z]{5}' /var/log/postgresql/postgresql-18-main.log | sort | uniq -c | sort -rn
# →   412 23505
# →    87 40001
# →    12 53300
```

## Валидация и проверка

После настройки обработки ошибок выполните проверку:

1.  **Проверка логирования SQLSTATE:**
    ```sql
    SELECT nonexistent_function();
    ```
    ```bash
    grep "SQLSTATE: 42883" /var/log/postgresql/postgresql-18-main.log
    # → ERROR: ... SQLSTATE: 42883
    ```

2.  **Проверка `pg_stat_statements` для ошибок (utility/DDL):**
    ```sql
    SELECT query, calls, mean_time
    FROM pg_stat_statements
    WHERE userid IS NULL;  -- NULL userid = utility/DDL операции
    ```

3.  **Проверка алертов на коррупцию:** лог-парсер должен отлавливать `SQLSTATE: XX*`.

## Мониторинг и алерты (DevOps/SRE)

### Алёрты на SQLSTATE через разбор логов

Для алёртов на основе логов используйте pgbadger или регулярные выражения в log-collector/SIEM:

```bash
# Коррупция данных — немедленный инцидент
grep "SQLSTATE: XX" /var/log/postgresql/*.log

# Авторизация — брутфорс
grep "SQLSTATE: 28" /var/log/postgresql/*.log | wc -l

# Конфигурация — ошибка в postgresql.conf
grep "SQLSTATE: F0" /var/log/postgresql/*.log
```

### Мониторинг ошибок через pg_stat_statements

```sql
-- Топ utility-запросов с ошибками (userid IS NULL = DDL/utility)
SELECT userid::regrole, dbid, query, calls, mean_time
FROM pg_stat_statements
WHERE userid IS NULL AND calls > 10
ORDER BY total_exec_time DESC LIMIT 10;
```

### Ключевые алёрты SRE

| SQLSTATE | Алёрт | Порог | Источник |
| :--- | :--- | :--- | :--- |
| `XX00*` | data_corrupted / index_corrupted | немедленно (P1) | log parser / pgbadger |
| `40001`/`40P01` | serialization_failure / deadlock_detected | >10/мин | `pg_stat_database.deadlocks` |
| `53300` | too_many_connections | активных >80% от `max_connections` | `pg_stat_activity` |
| `28*` | auth_errors | >5/мин с одного IP | log parser |
| `F0*` | config_errors | ≥1 | log parser |

Связь с [Наблюдаемостью PostgreSQL](../Operations/observability.md) для настройки pgbadger, `pg_stat_statements` и wait events.

## Устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| SQLSTATE не появляется в логе | `log_error_verbosity` ≠ `verbose` | `ALTER SYSTEM SET log_error_verbosity = verbose; SELECT pg_reload_conf();` |
| `pg_stat_statements` не показывает ошибки DDL | `pg_stat_statements.track` ≠ `all` | `ALTER SYSTEM SET pg_stat_statements.track = all;` + перезапустить сервер |
| `WHEN OTHERS` не ловит `query_canceled` | `QUERY_CANCELED` (57014) исключён из `OTHERS` в PL/pgSQL | Явно обрабатывать `WHEN SQLSTATE = '57014'` |
| `GET STACKED DIAGNOSTICS` возвращает NULL для `CONSTRAINT_NAME` | Гарантированное покрытие имен объектов только для класса 23 | Использовать `MESSAGE_TEXT` или `PG_EXCEPTION_DETAIL` |
| Алёрт на `XX000` срабатывает ночью | `autovacuum`/`auto_analyze` временно ломают индексы | Проверить `autovacuum_vacuum_cost_limit`; не отключать алёрт |



1.  **Тестируйте код, а не текст** — текст локализуем и нестабилен.
2.  **Retry только для `40001`/`40P01`** (и `08006`/`57P03` для reconnect) — с экспоненциальной задержкой.
3.  **`log_error_verbosity = verbose`** в production — SQLSTATE и контекст в лог.
4.  **Алерт на `XX000`/`XX001`/`XX002`** — внутренние ошибки и коррупция требуют немедленного разбора.
5.  **`GET STACKED DIAGNOSTICS`** вместо парсинга `SQLERRM` — структурированные поля.
6.  **Коды класса 23** — единственные с гарантированным отдельным полем имени объекта.

## Очистка и откат

- **Сброс статистики `pg_stat_statements`:**
  ```sql
  SELECT pg_stat_statements_reset();  -- текущая БД
  ```
- **Отключение расширения `pg_stat_statements`:**
  ```sql
  DROP EXTENSION IF EXISTS pg_stat_statements CASCADE;  -- в каждой БД
  -- затем убрать из shared_preload_libraries и перезапустить сервер
  ```
- **Сброс конфигурации логирования:**
  ```sql
  ALTER SYSTEM RESET log_error_verbosity;
  ALTER SYSTEM RESET pg_stat_statements.track;
  SELECT pg_reload_conf();
  ```
- **Очистка логов:** ротация через `logrotate` или встроенный `logging_collector` (`log_rotation_age`/`log_rotation_size`).

## Дополнительная информация

*   [Диагностический runbook](../Operations/troubleshooting_runbook.md#сценарий-13-частые-ошибки-приложений-sqlstate) — сценарии по ошибкам
*   [Отладка хранимых объектов](./stored_objects_debugging.md) — `GET STACKED DIAGNOSTICS`, `RAISE`
*   [Конкурентность и блокировки](./concurrency_and_locking.md) — `40001`, `40P01`, SSI
*   [Управление соединениями](../Operations/connection_management.md) — `53300`, таймауты
*   [Наблюдаемость PostgreSQL](../Operations/observability.md) — `pg_stat_statements`, `log_error_verbosity`, pgbadger
*   [Расширения PostgreSQL](./extensions_utility.md#pg_stat_statements-золотой-стандарт) — настройка `pg_stat_statements`
*   [Официальная документация: Appendix A. PostgreSQL Error Codes](https://www.postgresql.org/docs/current/errcodes-appendix.html)
*   [Официальная документация: PL/pgSQL Error Trapping](https://www.postgresql.org/docs/current/plpgsql-control-structures.html#PLPGSQL-ERROR-TRAPPING)
