# Обработка часовых поясов в PostgreSQL

**Актуально для:** PostgreSQL 14–18

## Определения

*   **`timestamptz` (`timestamp with time zone`)** — тип, хранящий момент времени как UTC-эпоху (внутренне — секунды от 2000-01-01 00:00 UTC). При записи применяет `timezone` сессии, при чтении — обратно. Сам пояса в строке не хранит: хранится абсолютный момент.
*   **`timestamp` (`timestamp without time zone`)** — «наивное» время без пояса: дата-время как строка, без привязки к UTC. Сравнение и арифметика не учитывают переходы на летнее время (DST).
*   **`timezone` (GUC)** — параметр сессии/сервера, определяющий пояс для интерпретации и отображения `timestamptz`. Дефолт — из `postgresql.conf` (обычно `Etc/UTC` или системный). Изменяется `SET timezone = 'Europe/Moscow'` без перезапуска.
*   **`AT TIME ZONE`** — оператор преобразования: `timestamptz AT TIME ZONE 'UTC'` → `timestamp` (в заданном поясе); `timestamp AT TIME ZONE 'Europe/Moscow'` → `timestamptz` (интерпретирует наивное время как московское).
*   **DST (Daylight Saving Time)** — переход на летнее/зимнее время. Арифметика `timestamptz` корректна при переходах (интервалы считаются по абсолютному времени); арифметика `timestamp` — нет (2:30 + 1 час в день перехода может дать 3:30 или 2:30 в зависимости от направления).
*   **`log_timezone`** — кластерный параметр (context `sighup`), задающий пояс для временных меток в серверном логе. Должен совпадать с поясом остальной инфраструктуры, чтобы коррелировать логи PostgreSQL с логами приложений. Изменяется через `postgresql.conf` или `ALTER SYSTEM` + `pg_reload_conf()` (без перезапуска); **не изменяется** `SET` в сессии. Дефолт — `GMT`.
*   **`pg_timezone_names`** — системное view со списком всех поддерживаемых IANA-имён поясов (из `tzdata`).
*   **`pg_timezone_abbrevs`** — системное view с аббревиатурами поясов и фиксированными смещениями.
*   **`tzdata`** — база данных часовых поясов IANA; правила DST в ней периодически обновляются (например, отмена переходов в РФ в 2014 году).

## Базовые концепции

### Почему `timestamptz` — дефолт для production

`timestamptz` хранит абсолютный момент (UTC). Отображение зависит только от `timezone` сессии, поэтому:

*   Приложения в разных регионах видят одно и то же время в своём поясе без конвертаций в коде.
*   Смена пояса сервера или сессии не меняет данные — меняется только вывод.
*   Арифметика интервалов (`created_at + interval '1 day'`) корректна при DST-переходах.

`timestamp` оправдан только для «наивных» понятий, не привязанных к моменту: «открытие в 09:00», расписание, даты без времени.

### Как PostgreSQL определяет пояс

1.  **`timezone` в `postgresql.conf`** — серверный дефолт для новых сессий.
2.  **`PGTZ` / `options=-c timezone=...`** в строке подключения — переопределяет для сессии.
3.  **`SET timezone = '...'`** — в транзакции/сессии.
4.  Если `timezone` не задан явно — PostgreSQL читает `TZ` из окружения ОС, иначе `GMT`.

Имена поясов — из базы IANA (`tzdata`): `Europe/Moscow`, `America/New_York`. Аббревиатуры (`MSK`, `PST`) неоднозначны и не рекомендуются.

### Ловушки (почему это спрашивают на собеседованиях)

*   **`now()` vs `CURRENT_TIMESTAMP` vs `clock_timestamp()`**: `now()`/`CURRENT_TIMESTAMP` — время **начала транзакции** (фиксировано внутри транзакции); `clock_timestamp()` — реальное текущее время (меняется внутри транзакции). Для `updated_at DEFAULT now()` это означает, что все строки одной транзакции получат одинаковую метку.
*   **Сравнение `timestamptz` и `timestamp`**: прямое сравнение приводит `timestamp` к `timestamptz` через `timezone` сессии — результат зависит от пояса сессии. Сравнивайте в явном виде через `AT TIME ZONE`.
*   **`pg_dump` и `timestamptz`**: дамп хранит `timestamptz` в ISO-8601 с смещением; при восстановлении пояс не «теряется», так как хранится абсолютный момент.
*   **Приложение vs база**: если приложение пишет `timestamp` (без пояса), а база в другом поясе — данные смещены. Правило: приложение пишет UTC (`timestamptz`), отображение — на клиенте.

## Справочник GUC-параметров

| Параметр | Context | Описание | Как изменить |
|---|---|---|---|
| `timezone` | `user`/`sighup` | Пояс для интерпретации и отображения `timestamptz` в сессии | `SET timezone` (сессия); `postgresql.conf` (сервер) |
| `log_timezone` | `sighup` | Пояс для временных меток в серверном логе (кластер-wide) | `postgresql.conf` / `ALTER SYSTEM` + `pg_reload_conf()` |
| `DateStyle` | `user`/`sighup` | Формат вывода дат/времени | `SET datestyle` |
| `IntervalStyle` | `user`/`sighup` | Формат вывода интервалов | `SET intervalstyle` |
| `timezone_abbreviations` | `sighup` | Набор аббревиатур для ввода | `postgresql.conf` / `ALTER SYSTEM` |

## Практические сценарии

### Предварительные требования

1.  **PostgreSQL 14–18** с доступом к `psql`.
2.  **Права**: `SELECT` на таблицы для анализа колонок; `SET` — любому пользователю; `ALTER SYSTEM` — суперпользовтелю или роли с `pg_read_all_settings`/`pg_write_server_files`.
3.  **tzdata в ОС**: `tzdata` должен быть обновлён до актуальной версии IANA (см. [Лучшие практики](#лучшие-практики)).

### 1. Проверка текущего пояса и времени

```sql
SHOW timezone;
-- → Europe/Moscow

SHOW log_timezone;
-- → Europe/Moscow

SELECT now(), now() AT TIME ZONE 'UTC', clock_timestamp();
-- → 2026-10-04 21:45:12.123456+03 | 2026-10-04 18:45:12.123456 | 2026-10-04 21:45:12.654321+03
-- now() = время начала транзакции; clock_timestamp() = реальное время
```

```sql
-- Список доступных IANA-имён поясов
SELECT name, utc_offset, is_dst FROM pg_timezone_names
WHERE name IN ('Europe/Moscow', 'Europe/Samara')
ORDER BY name;
-- → Europe/Moscow | 03:00:00 | false
```

### 2. Конвертация между поясами

```sql
-- Храним UTC-момент, показываем в московском поясе
SELECT created_at AT TIME ZONE 'Europe/Moscow' AS moscow_time
FROM orders WHERE id = 42;
-- → 2026-10-04 21:45:12.123456   (тип timestamp — наивное московское время)

-- Обратно: наивное московское время → абсолутный момент
SELECT '2026-10-04 21:45:12'::timestamp AT TIME ZONE 'Europe/Moscow';
-- → 2026-10-04 21:45:12+03        (тип timestamptz)
```

### 3. Агрегация по часу в фиксированном поясе

```sql
-- Группировка по московскому часу независимо от timezone сессии
SELECT date_trunc('hour', created_at AT TIME ZONE 'Europe/Moscow') AS hour_msk,
       count(*) AS orders
FROM orders
GROUP BY 1 ORDER BY 1;
-- → hour_msk            | orders
-- → 2026-10-04 18:00:00 | 152
```

### 4. Поиск «дыры» DST (несуществующее время)

```sql
-- Время 02:30 2026-03-08 в America/New_York не существует (перевод часов)
SELECT '2026-03-08 02:30:00'::timestamp AT TIME ZONE 'America/New_York';
-- → 2026-03-08 03:30:00-04   (PostgreSQL нормализует вперёд)
```

### 5. Настройка пояса сервера и лога

```bash
# postgresql.conf (или ALTER SYSTEM SET)
timezone = 'Europe/Moscow'      # для сессий
log_timezone = 'Europe/Moscow'  # для серверного лога (reload)
```
```sql
SELECT pg_reload_conf();
-- → t
```

### 6. Проверка колонок на использование `timestamptz`

```sql
-- Поиск колонок timestamp без пояса в таблицах приложения
SELECT table_schema, table_name, column_name
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND data_type = 'timestamp without time zone'
ORDER BY table_schema, table_name;
-- → (пусто — значит все колонки времени используют timestamptz)
```

## Валидация и проверка

1.  **Согласованность `timezone` и `log_timezone`**: оба должны быть IANA-именами (не аббревиатурами).
```sql
SHOW timezone;        -- → Europe/Moscow  (IANA)
SHOW log_timezone;    -- → Europe/Moscow  (IANA)
SELECT name FROM pg_timezone_names WHERE name = current_setting('timezone');
-- → Europe/Moscow    (подтверждает валидность)
```
2.  **Отсутствие `timestamp` для колонок событий**: все `created_at`, `updated_at`, `event_time` должны быть `timestamptz`.
```sql
SELECT count(*) FROM information_schema.columns
WHERE column_name ~ '_(at|time)$' AND data_type = 'timestamp without time zone';
-- → 0  (хорошо)
```
3.  **Проверка версии tzdata в ОС**: см. [Cleanup](#очистка-и-откат).
4.  **Согласованность с инфраструктурой**: временные метки в логах PostgreSQL и приложения должны совпадать.
5.  **Функциональные индексы на `AT TIME ZONE`**: проверяются в [Оптимизация производительности](../Operations/performance_tuning.md).

## Мониторинг и алерты (DevOps/SRE)

*   **Алерт: `timezone` ≠ `log_timezone`** — расхождение между поясом сессий и лога усложняет корреляцию. Проверка раз в суть:
```sql
SELECT CASE
  WHEN current_setting('timezone') != current_setting('log_timezone')
  THEN 'WARNING: mismatch'
  ELSE 'OK'
END AS check_result;
```
*   **Алерт: аббревиатура вместо IANA-имени** — `SHOW timezone` возвращает аббревиатуру (например, `MSK`), это неоднозначно. SRE-правило: требовать `Europe/Moscow`, а не `MSK`.
*   **Мониторинг: использование `timestamp` для колонок событий** — периодически сканировать `information_schema.columns` на `timestamp without time zone` в бизнес-таблицах (см. сценарий 6).
*   **Мониторинг: `pg_timezone_names` out of date** — если сервер выдаёт ошибку `invalid value for parameter "timezone"`, tzdata в ОС устарел:
```bash
# Debian/Ubuntu
dpkg -l tzdata
apt list --upgradable tzdata

# RHEL/CentOS
rpm -q tzdata
dnf check-update tzdata
```
*   **SRE-правило: `log_timezone` = `UTC`** для распределённых систем — все логи коррелируются в одном поясе, локальная конвертация только на этапе отображения в UI.
*   **Мониторинг: `interval '1 day'` на `timestamp`** — алерты на запросы с `timestamp + interval '1 day'` в таблицах с DST-поясами (риск смещения на 1 час).

## Устранение неполадок

*   **Смещение времени на 1 час при переходе на летнее время**: данные записаны как `timestamp` (без пояса), а приложение или БД поменял пояс. Решение: конвертировать в `timestamptz` через `AT TIME ZONE` с явным указанием исходного пояса, либо изменить тип колонки (`ALTER TABLE ... ALTER COLUMN created_at TYPE timestamptz`).
*   **Время 02:30 не существует или существует дважды (DST-переход)**: PostgreSQL нормализует «дыру» вперёд, а «дубль» (ambiguous time) разрешает через смещение. Используйте явные IANA-имена и `AT TIME ZONE`, а не аббревиатуры.
*   **Сравнение `timestamp` и `timestamptz` даёт неожиданный результат**: PostgreSQL неявно приводит `timestamp` к `timestamptz` через `timezone` сессии. Устранение: всегда используйте `AT TIME ZONE` для явного приведения.
*   **Логи PostgreSQL смещены относительно логов приложения**: проверьте `log_timezone` — он должен совпадать с поясом логов приложения или быть `UTC` (рекомендуется для распределённых систем).
*   **`SET timezone = 'MSK'` работает, но даёт неверные результаты в других версиях tzdata**: MSK в одних версиях = UTC+3, в других = UTC+4. Используйте `Europe/Moscow`.
*   **В контейнере timezone = GMT, но приложение ожидает локальный пояс**: задайте `PGTZ=Europe/Moscow` в env контейнера, либо `options=-c timezone=Europe/Moscow` в строке подключения.
*   **`pg_dump` «потерял» пояс**: это невозможно для `timestamptz` — он хранит UTC. Проверьте, что колонка действительно `timestamptz`, а не `timestamp`.
*   **`now()` возвращает одно и то же значение для всех строк в транзакции**: это корректно — `now()` = `transaction_timestamp()`. Для уникальных меток используйте `clock_timestamp()` или `transaction_timestamp() + random() * interval '1 microsecond'`.
*   **`timezone = 'America/New_York'` в январе работает, а в мае — ошибка**: проверьте, что IANA-имя существует в `pg_timezone_names` для вашей ОС/tzdata.
*   **Приложение пишет `2026-03-08 02:30:00` и получает ошибку**: время попадает в «дыру» DST при интерпретации через `timestamp AT TIME ZONE 'America/New_York'`. PostgreSQL нормализует автоматически, но логика приложения может ожидать другое.

## Лучшие практики

1.  **Всегда `timestamptz`** для моментов событий (`created_at`, `updated_at`, `event_time`). `timestamp` — только для расписаний и «наивных» дат.
2.  **Храните UTC, отображайте локально**: приложение пишет `timestamptz` (база конвертирует в UTC), читатель форматирует в своём поясе. Не храните смещение в отдельной колонке.
3.  **Явный `AT TIME ZONE`** при агрегации по часам/дням — иначе результат зависит от `timezone` сессии и «плывёт» между средами.
4.  **`log_timezone` = поясу инфраструктуры** — чтобы логи PostgreSQL коррелировались с логами приложений и nginx. Для распределённых систем предпочтительно `UTC`.
5.  **`now()` для `DEFAULT`** — время начала транзакции; если нужна точная метка записи — `clock_timestamp()`.
6.  **Обновляйте `tzdata`** в ОС (`apt upgrade tzdata` / `dnf update tzdata`) — правила DST меняются (например, отмена перехода в РФ). Устаревший `tzdata` даёт смещения на час.
7.  **Используйте IANA-имена, а не аббревиатуры** — `Europe/Moscow`, а не `MSK`.
8.  **`log_timezone` и `timezone` должны совпадать**, если логи используются для аудита и отладки в локальном поясе.
9.  **Для контейнеров** — задавайте `PGTZ` или `options=-c timezone=...` явно, не полагаясь на `TZ` env.

## Очистка и откат

*   **Сброс `timezone` сессии**:
```sql
SET timezone = DEFAULT;
-- или
RESET timezone;
```
*   **Откат изменений `log_timezone` в кластере**:
```sql
ALTER SYSTEM RESET log_timezone;
SELECT pg_reload_conf();
```
*   **Откат изменений в `postgresql.conf`**: удалите или закомментируйте строки `timezone` и `log_timezone`, затем:
```bash
pg_ctl reload -D /path/to/data
-- или
psql -c "SELECT pg_reload_conf();"
```
*   **Проверка версии `tzdata`** (DevOps-поток):
```bash
# Debian/Ubuntu
dpkg -l tzdata 2>/dev/null | grep tzdata
apt list --upgradable 2>/dev/null | grep tzdata

# RHEL/CentOS/Fedora
rpm -q tzdata

# Alpine
apk info tzdata
```
*   **`psql`-утилиты для отката**: `\set timezone` не сбрасывает GUC; используйте `RESET timezone` или `SET timezone = DEFAULT`.

## Пограничные случаи

*   **`interval '1 day'` на `timestamptz`** — абсолютные 24 часа; на `timestamp` — «следующие сутки» (может быть 23 или 25 часов при DST).
*   **`timezone = 'UTC'` в контейнерах** — дефолт Docker/Alpine; если приложение ожидает локальный пояс — задавайте `timezone` явно или `PGTZ`.
*   **`timestamp` без пояса в `pg_dump`** — восстанавливается как есть; смещение не теряется, потому что его и не было.
*   **`AT TIME ZONE` с аббревиатурой** (`MSK`) — работает, но неоднозначно (MSK = UTC+3 всегда, но `CET` меняется с DST); используйте имена IANA.

## Дополнительная информация

*   [Архитектура PostgreSQL](./architecture.md) — типы данных и хранение.
*   [Консольные основы (psql)](../Operations/console_basics.md) — `\show timezone`, переменные окружения.
*   [Оптимизация производительности](../Operations/performance_tuning.md) — влияние `timezone` на планы (функциональные индексы на `AT TIME ZONE`).
*   [Официальная документация: типы дата/время](https://www.postgresql.org/docs/current/datatype-datetime.html)
*   [Официальная документация: функции дата/время](https://www.postgresql.org/docs/current/functions-datetime.html)
*   [Официальная документация: логирование (log_timezone)](https://www.postgresql.org/docs/current/runtime-config-logging.html)
*   [GUC Atlas: log_timezone](https://guc.pg.center/parameters/log_timezone/)
*   [pgpedia: log_timezone](https://pgpedia.info/l/log_timezone.html)
