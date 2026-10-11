# Отладка хранимых объектов в PostgreSQL

**Актуально для:** PostgreSQL 13–18

## Определения

* **PL/pgSQL:** основной процедурный язык PostgreSQL; встроенные средства отладки — `RAISE`, `GET DIAGNOSTICS`, блок `EXCEPTION`, `ASSERT`.
* **`RAISE`:** оператор выдачи сообщений и ошибок; уровни `DEBUG`, `LOG`, `INFO`, `NOTICE`, `WARNING`, `EXCEPTION` (дефолт — `EXCEPTION`).
* **`GET STACKED DIAGNOSTICS`:** оператор получения деталей текущей ошибки внутри обработчика `EXCEPTION` (SQLSTATE, текст сообщения, имя ограничения, контекст стека вызовов).
* **Подтранзакция (subtransaction):** точка сохранения, создаваемая блоком `BEGIN ... EXCEPTION`; при перехвате ошибки изменения внутри блока откатываются, локальные переменные сохраняются.
* **`ASSERT`:** проверка внутреннего инварианта; при невыполнении условия поднимает `ASSERT_FAILURE`; отключается параметром `plpgsql.check_asserts`.
* **`client_min_messages` / `log_min_messages`:** пороги уровней сообщений для клиента и серверного лога (дефолты `NOTICE` и `WARNING`).
* **`track_functions`:** параметр сбора статистики по функциям (`none` / `pl` / `all`, дефолт `none`); метрики и методология мониторинга — в SSoT **[Мониторинг хранимых объектов](../../Concepts/stored_objects/monitoring.md)**.
* **`pldbgapi` / `plugin_debugger`:** серверная часть пошагового отладчика PL/pgSQL (расширение `pldebugger`, repo [EnterpriseDB/pldebugger](https://github.com/EnterpriseDB/pldebugger)); клиентский UI предоставляет pgAdmin 4 или DBeaver.
* **`plprofiler`:** расширение профилирования PL/pgSQL с Flame Graph по wall-clock времени; установка и примеры — в **[Оптимизация PL/pgSQL](./pl_pgsql_optimization.md)**.

## Базовые концепции

### Каналы доставки сообщений

Куда попадает сообщение уровня `RAISE`, определяют два порога: `client_min_messages` (дефолт `NOTICE`) и `log_min_messages` (дефолт `WARNING`). Порядок уровней в них **различается**, поэтому `LOG` и `NOTICE` ведут себя по-разному:

| Уровень `RAISE` | Клиент (по дефолту) | Серверный лог (по дефолту) | Прерывает транзакцию |
| :--- | :--- | :--- | :--- |
| `DEBUG` | Нет | Нет | Нет |
| `INFO` | **Всегда** (специальное правило) | Нет | Нет |
| `NOTICE` | Да | Нет | Нет |
| `WARNING` | Да | Да | Нет |
| `LOG` | Нет | Да | Нет |
| `ERROR` / `EXCEPTION` | Да | Да | Да (если не перехвачена) |

```sql
SHOW client_min_messages;  -- → notice
SHOW log_min_messages;     -- → warning
```

Практический вывод SRE: `RAISE NOTICE` — прогресс выполнения для клиента; `RAISE LOG` — административные события, которые гарантированно попадают в серверный лог, но не спамят клиента; `RAISE DEBUG` — только на staging, где оба порога понижены (`log_min_messages = debug1`).

### Транзакционный контекст отладки

* Необработанная ошибка в функции или триггере откатывает **всю транзакцию** вызывающей сессии.
* Блок `BEGIN ... EXCEPTION` создаёт подтранзакцию: при перехвате ошибки откатываются только изменения внутри блока, а локальные переменные сохраняют значения на момент ошибки.
* `WHEN OTHERS` перехватывает всё, **кроме** `QUERY_CANCELED` (отмена по `statement_timeout`/`pg_cancel_backend`) и `ASSERT_FAILURE` — их можно ловить только явно по имени (что обычно нежелательно).
* Вход и выход из блока с `EXCEPTION` значительно дороже обычного блока — не оборачивайте в `EXCEPTION` горячие циклы «на всякий случай» (подробнее — в **[Оптимизация PL/pgSQL](./pl_pgsql_optimization.md)**).

## Практические сценарии

### Требования

* PostgreSQL 13–18; `psql` (или клиент, показывающий `NOTICE`).
* Суперпользователь: для `shared_preload_libraries`, `CREATE EXTENSION pldbgapi` и `SET track_functions`.
* Пакеты отладчика: PGDG `pldebugger_18` (RHEL/Rocky/Alma/Fedora, версии 14–18) или `postgresql-18-pldebugger` (Debian/Ubuntu).
* Для профилирования: `pg_stat_statements` (см. SSoT **[Мониторинг хранимых объектов](../../Concepts/stored_objects/monitoring.md)**).

### 1. Инструментирование через `RAISE`

Базовый синтаксис: `RAISE [level] 'format' [, expr ...] [USING option = expr ...]`. В строке формата `%` заменяется строковым представлением следующего аргумента, `%%` — литеральный `%`; число аргументов должно совпадать с числом `%` (иначе — ошибка компиляции функции).

```sql
CREATE OR REPLACE FUNCTION debug_example(p_id INT) RETURNS VOID AS $$
BEGIN
    -- Прогресс для клиента (NOTICE виден по умолчанию)
    RAISE NOTICE 'Starting procedure for ID: %', p_id;

    IF p_id < 0 THEN
        -- Прерывание с ошибкой (EXCEPTION — дефолтный уровень)
        RAISE EXCEPTION 'ID cannot be negative: %', p_id;
    END IF;

    -- Административное событие: всегда в серверный лог, клиенту не отправляется
    RAISE LOG 'Step 1 completed at %', now();
END;
$$ LANGUAGE plpgsql;

SELECT debug_example(42);
-- → NOTICE:  Starting procedure for ID: 42
-- → (запись в серверном логе: LOG:  Step 1 completed at ...)
```

Дополнительные варианты и опции `USING`:

| Конструкция / опция | Назначение |
| :--- | :--- |
| `RAISE division_by_zero;` | Поднять существующее условие по имени (Appendix A) |
| `RAISE WARNING SQLSTATE '22012';` | Поднять ошибку с заданным 5-символьным кодом |
| `RAISE;` (без параметров) | Повторно поднять текущую ошибку — только внутри `EXCEPTION`-блока |
| `USING ERRCODE = 'unique_violation'` | Код ошибки: имя условия или SQLSTATE (дефолт для `EXCEPTION` — `raise_exception` / `P0001`) |
| `USING MESSAGE / DETAIL / HINT` | Основной текст, детализация, подсказка (показываются клиенту и в логе) |
| `USING TABLE / SCHEMA / COLUMN / CONSTRAINT / DATATYPE` | Имена связанных объектов — появляются в выводе `psql` при `VERBOSITY verbose` |

```sql
RAISE EXCEPTION 'Duplicate user ID: %', user_id
    USING ERRCODE = '23505',
          HINT = 'Проверьте уникальность user_id';
```

Произвольный SQLSTATE: любые 5 цифр/заглавных букв, кроме `00000`; избегайте кодов, оканчивающихся на три нуля — это коды категорий, ловящиеся только целой категорией.

### 2. Детали ошибки: `GET DIAGNOSTICS` / `GET STACKED DIAGNOSTICS`

Внутри обработчика доступны специальные переменные `SQLSTATE` (код ошибки) и `SQLERRM` (текст сообщения) — за пределами обработчика они не определены. Для структурированных деталей — `GET STACKED DIAGNOSTICS`:

| Параметр | Тип | Содержимое |
| :--- | :--- | :--- |
| `RETURNED_SQLSTATE` | text | SQLSTATE ошибки |
| `MESSAGE_TEXT` | text | Основное сообщение |
| `PG_EXCEPTION_DETAIL` / `PG_EXCEPTION_HINT` | text | DETAIL / HINT (пустая строка, если нет) |
| `TABLE_NAME` / `SCHEMA_NAME` / `COLUMN_NAME` / `CONSTRAINT_NAME` / `PG_DATATYPE_NAME` | text | Связанные объекты |
| `PG_EXCEPTION_CONTEXT` | text | Трассировка стека вызовов на момент ошибки |

```sql
CREATE OR REPLACE FUNCTION safe_update(p_id INT, p_status TEXT) RETURNS VOID AS $$
DECLARE
    v_detail TEXT;
    v_hint   TEXT;
BEGIN
    UPDATE orders SET status = p_status WHERE id = p_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'order % not found', p_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS
            v_detail = PG_EXCEPTION_DETAIL,
            v_hint   = PG_EXCEPTION_HINT;
        RAISE WARNING 'update failed: % / % / %', SQLERRM, v_detail, v_hint;
END;
$$ LANGUAGE plpgsql;
```

Текущее место выполнения (не по ошибке) — `GET DIAGNOSTICS ... = PG_CONTEXT`: строка описывает текущую функцию, последующие — вызывающие функции по стеку:

```sql
GET DIAGNOSTICS v_stack = PG_CONTEXT;
RAISE NOTICE E'--- Call Stack ---\n%', v_stack;
-- → NOTICE:  --- Call Stack ---
-- → PL/pgSQL function inner_func() line 5 at GET DIAGNOSTICS
-- → PL/pgSQL function outer_func() line 3 at RETURN
```

В `psql` при инциденте включайте подробный вывод — он добавляет SQLSTATE, DETAIL, HINT, CONTEXT и имена объектов:

```bash
\set VERBOSITY verbose      # в psql; сброс: \set VERBOSITY default
```

Для серверного лога аналог даёт `log_error_verbosity = verbose` (добавляет SQLSTATE и исходный файл/функцию/строку кода).

### 3. `ASSERT` для проверки инвариантов

```sql
ASSERT p_id > 0, format('invalid p_id: %', p_id);
```

`ASSERT` — средство обнаружения багов программы, а не ошибок ввода (для тех — `RAISE`). При ложном/NULL-условии поднимается `ASSERT_FAILURE`; сообщение не вычисляется в успешном случае. Проверку можно отключить: `SET plpgsql.check_asserts = off` (дефолт `on`). `WHEN OTHERS` `ASSERT_FAILURE` не перехватывает.

### 4. Пошаговая отладка (`pldbgapi`)

Нативного отладчика в PostgreSQL нет; пошаговую отладку (breakpoints, step over/into, просмотр переменных) даёт расширение `pldebugger` (API-расширение называется `pldbgapi`).

**Настройка:**

```bash
# RHEL/Rocky/Alma/Fedora (PGDG):
sudo dnf install pldebugger_18
# Debian/Ubuntu:
sudo apt install postgresql-18-pldebugger
```

```ini
# postgresql.conf — требуется перезапуск сервера (параметр читается только при старте)
shared_preload_libraries = 'plugin_debugger'
```

```sql
CREATE EXTENSION pldbgapi;   -- суперпользователь; выполняется в каждой БД, где отлаживаете
```

Клиенты: pgAdmin 4 (требует суперпользователя для отладки; режимы in-context — останов на breakpoints при обычном вызове, и direct — запуск функции с тестовыми аргументами) и DBeaver. Подавляющее большинство проблем с отладчиком вызвано тем, что `plugin_debugger` не добавлен в `shared_preload_libraries` или сервер не перезапущен после правки.

### 5. Профилирование производительности

Метрики и методология (baseline, алертинг, USE-методология) — в SSoT **[Мониторинг хранимых объектов](../../Concepts/stored_objects/monitoring.md)**. Здесь — отладочный минимум:

```sql
SHOW track_functions;   -- → none (дефолт: статистика не собирается)

-- Включение (перезапуск НЕ нужен: контекст PGC_SUSET — reload достаточно,
-- суперпользователь может также SET в сессии)
ALTER SYSTEM SET track_functions = 'pl';   -- 'pl' достаточно для PL/pgSQL
SELECT pg_reload_conf();                   -- 'all' добавляет SQL- и C-функции, но дороже

-- Топ-5 функций по общему времени
SELECT funcname, calls, total_time, self_time
FROM pg_stat_user_functions
ORDER BY total_time DESC
LIMIT 5;
-- → funcname      | calls | total_time | self_time
-- → audit_changes | 15234 |     4523.1 |    4523.1
```

Ключевые нюансы:

* `total_time` ≫ `self_time` — время уходит на вложенные вызовы функций и SQL-запросы; `self_time` — собственно код функции.
* `pg_stat_user_functions` отслеживает **функции, но не процедуры** (`PROCEDURE`); вызовы процедур видны в `pg_stat_statements` (`CALL ...`).
* SQL-функции, простые enough для «inlining» в вызывающий запрос, не отслеживаются ни при каком `track_functions`.
* Статистика кэшируется до конца транзакции (`stats_fetch_consistency = cache`, дефолт) — в длинной транзакции значения «замораживаются»; сброс кэша: `SELECT pg_stat_clear_snapshot();`.
* Статистика текущей транзакции (ещё не сброшенная в shared memory) — в `pg_stat_xact_user_functions`.
* Flame Graph по PL/pgSQL-коду (wall-clock, self_time = total_time − children_time) — расширение `plprofiler`, детали в **[Оптимизация PL/pgSQL](./pl_pgsql_optimization.md)**.

### 6. Диагностика зависших и долгих вызовов

```sql
-- Что выполняет «зависшая» сессия и на чём ждёт
SELECT pid, usename, state, wait_event_type, wait_event, query_start, query
FROM pg_stat_activity
WHERE state = 'active'
  AND query NOT LIKE '%pg_stat_activity%';
-- → pid | usename | state  | wait_event_type | wait_event | query
-- → 1234| app_user| active | Lock            | relation   | CALL long_proc()

SELECT pg_cancel_backend(1234);    -- отмена текущего оператора (SIGINT)
SELECT pg_terminate_backend(1234); -- разрыв сессии (SIGTERM)
```

`wait_event_type = Lock` — блокировка (см. **[Конкурентность и блокировки](./concurrency_and_locking.md)** и runbook в **[Troubleshooting хранимых объектов](../../Concepts/stored_objects/troubleshooting.md)**); `Timeout` с `wait_event = statement_timeout` — ушёл в бесконечный цикл до истечения таймаута. Защита production: `statement_timeout`, `lock_timeout`, `transaction_timeout` (PG 17) на роли — детали и иерархия таймаутов в **[Troubleshooting хранимых объектов](../../Concepts/stored_objects/troubleshooting.md)**. Для ловли медленных `CALL` в production — `log_min_duration_statement` (в лог попадает текст оператора).

### 7. Отладка триггеров

Триггерная функция видит контекст через переменные `TG_NAME`, `TG_OP`, `TG_TABLE_NAME`, `TG_ARGV`. Типовые проблемы — рекурсия триггеров (`ERROR: stack depth limit exceeded`), блокировки в триггере, «невидимые» строки в `BEFORE`-триггере — с симптомами, диагностикой и защитным флагом через `set_config(...)`: в **[Troubleshooting хранимых объектов](../../Concepts/stored_objects/troubleshooting.md)**. Для изоляции проблемного триггера: `ALTER TABLE ... DISABLE TRIGGER trigger_name;` (суперпользователь).

### Сравнение с MariaDB/MySQL

В MariaDB/MySQL нет аналога `RAISE`: ошибки поднимаются оператором `SIGNAL SQLSTATE '...' SET MESSAGE_TEXT = ...`, повторная выдача — `RESIGNAL`. Пошагового отладчика нет; диагностика идёт через Performance Schema (`events_statements_summary_by_program`) и slow log — детали в **[Мониторинг хранимых объектов](../../Concepts/stored_objects/monitoring.md)** и **[Управлении объектами в MariaDB/MySQL](../../MariaDB/Concepts/stored_objects_management.md)**.

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `RAISE NOTICE` не виден клиенту | `client_min_messages` повышен (`warning`/`error`) | `SET client_min_messages = notice;` (`INFO` отправляется клиенту всегда) |
| `RAISE DEBUG` нигде не появляется | `log_min_messages = warning` (дефолт) подавляет `DEBUG` | `SET log_min_messages = debug1;` (суперпользователь) + `SET client_min_messages = debug1;` |
| `pg_stat_user_functions` пуста | `track_functions = none` (дефолт) | `ALTER SYSTEM SET track_functions = 'pl'; SELECT pg_reload_conf();` — процедуры и inlined SQL-функции не отслеживаются |
| Статистика не меняется в транзакции | Кэш `stats_fetch_consistency = cache` | `SELECT pg_stat_clear_snapshot();` |
| Отладчик не подключается / «plugin_debugger not found» | `plugin_debugger` не в `shared_preload_libraries` или сервер не перезапущен; `CREATE EXTENSION pldbgapi` не выполнен | Добавить в `shared_preload_libraries`, `sudo systemctl restart postgresql`, `CREATE EXTENSION pldbgapi;` (суперпользователь) |
| `CREATE EXTENSION pldbgapi`: permission denied | Расширение не trusted | Выполнять от суперпользователя |
| `ERROR: out of shared memory` | Исчерпан лимит блокировок одной транзакции (массовые срабатывания триггеров) | Увеличить `max_locks_per_transaction` (дефолт 64) + перезапуск |
| `ERROR: stack depth limit exceeded` | Рекурсия триггера/функции | Runbook и защитный флаг — **[Troubleshooting хранимых объектов](../../Concepts/stored_objects/troubleshooting.md)**; `max_stack_depth` (дефолт 2 MB) — не лечит, а только отсекает глубже |
| Функция «зависла» | Блокировка или бесконечный цикл | `pg_stat_activity` → `pg_cancel_backend`/`pg_terminate_backend`; runbook — в **[Troubleshooting хранимых объектов](../../Concepts/stored_objects/troubleshooting.md)** |
| `EXCEPTION WHEN OTHERS` «глотает» ошибку | Ловится слишком широко; подтранзакция откатывает изменения блока | Ловить конкретные условия (`WHEN unique_violation`); `OTHERS` не перехватывает `QUERY_CANCELED` и `ASSERT_FAILURE` |
| Ошибка компиляции функции: «число аргументов не совпадает» | Число `%` в формате `RAISE` ≠ числу аргументов | Выровнять аргументы; литерал — `%%` |
| В выводе ошибки нет деталей | `psql` в режиме terse/default | `\set VERBOSITY verbose`; в логе — `log_error_verbosity = verbose` |

## Лучшие практики

* `RAISE NOTICE` — прогресс для клиента; `RAISE LOG` — административные события (всегда в серверный лог); `RAISE DEBUG` — только на staging с пониженными порогами.
* Ловить конкретные условия (`WHEN unique_violation`), не `WHEN OTHERS`; не оборачивать в `EXCEPTION` горячие циклы — подтранзакция имеет стоимость.
* Использовать `USING ERRCODE/DETAIL/HINT` — структурированная диагностика вместо свободного текста.
* `track_functions = pl` в production (дешевле `all`); `pg_stat_statements` — для процедур (`CALL`).
* `\set VERBOSITY verbose` в runbook инцидентов; `log_line_prefix = '%m [%p] %u@%d/%a '` — корреляция `NOTICE`/`LOG` с сессиями в логе.
* Версионировать код объектов в Git (Flyway/Liquibase/Sqitch); удалять отладочные `RAISE` перед релизом.

## Очистка и откат изменений

```sql
DROP EXTENSION pldbgapi;          -- в каждой БД, где создавали
-- postgresql.conf: убрать plugin_debugger из shared_preload_libraries
sudo systemctl restart postgresql

ALTER SYSTEM RESET track_functions; SELECT pg_reload_conf();  -- или RESET track_functions; в сессии
SET client_min_messages = notice;   -- дефолт
SET plpgsql.check_asserts = on;     -- дефолт
SELECT pg_stat_reset();             -- сброс всей статистики БД, включая функции
```

## Вопросы на собеседованиях

1. Чем отличаются `client_min_messages` и `log_min_messages`, и куда по умолчанию попадают `NOTICE`, `LOG` и `INFO`?
2. Что откатывается при перехвате ошибки в блоке `BEGIN ... EXCEPTION`, и почему этот блок дорого входить?
3. Как в обработчике ошибки получить SQLSTATE, имя ограничения и трассировку стека вызовов?
4. Почему `track_functions = pl` достаточно для PL/pgSQL, и почему процедуры (`PROCEDURE`) не видны в `pg_stat_user_functions`?
5. Какие шаги нужны, чтобы заработал пошаговый отладчик (`pldbgapi`)? Почему без перезапуска не работает?
6. Как по `pg_stat_activity` отличить «зависла на блокировке» от «бесконечный цикл»?
7. Почему `WHEN OTHERS` не перехватывает `QUERY_CANCELED` и `ASSERT_FAILURE`?

## Дополнительная информация

### Смежные темы

- **[Мониторинг хранимых объектов (SSoT)](../../Concepts/stored_objects/monitoring.md)** — `pg_stat_user_functions`, `pg_stat_statements`, Performance Schema, baseline.
- **[Troubleshooting хранимых объектов (SSoT)](../../Concepts/stored_objects/troubleshooting.md)** — рекурсия триггеров, блокировки, зависшие сессии, таймауты.
- **[Оптимизация PL/pgSQL](./pl_pgsql_optimization.md)** — `EXCEPTION`/`RAISE`/`ASSERT`, `plprofiler` Flame Graph, `SECURITY DEFINER`.
- **[Конкурентность и блокировки](./concurrency_and_locking.md)** — MVCC, локи, deadlock.
- **[Хранимые объекты: обзор](../../Concepts/stored_objects_overview.md)** — типы объектов.
- **[Безопасность хранимых объектов](../../Concepts/stored_objects/security.md)** — `SECURITY DEFINER`, привилегии `EXECUTE`.

### Официальная документация PostgreSQL 18

- [PL/pgSQL: Errors and Messages (`RAISE`, `ASSERT`)](https://www.postgresql.org/docs/current/plpgsql-errors-and-messages.html)
- [PL/pgSQL: Control Structures (`EXCEPTION`, `GET STACKED DIAGNOSTICS`)](https://www.postgresql.org/docs/current/plpgsql-control-structures.html)
- [Run-time Statistics (`track_functions`)](https://www.postgresql.org/docs/current/runtime-config-statistics.html)
- [Error Reporting and Logging (`log_min_messages`, `log_error_verbosity`)](https://www.postgresql.org/docs/current/runtime-config-logging.html)
- [Client Connection Defaults (`client_min_messages`)](https://www.postgresql.org/docs/current/runtime-config-client.html)
- [pldebugger (EnterpriseDB)](https://github.com/EnterpriseDB/pldebugger)
