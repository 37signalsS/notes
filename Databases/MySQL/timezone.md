# Часовые пояса в MySQL: time zone, TIMESTAMP и DATETIME

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation

> **Статус:** MySQL 8.0 достиг End of Life в апреле 2026 (последний выпуск
> 8.0.46). Описанное применимо к 8.0, но для новых инсталляций и обновлений —
> MySQL 8.4 LTS.

Часовой пояс — серверная настройка, которая «всплывает» в самый неподходящий
момент: при переезде сервера в другой ЦОД или контейнер значения `TIMESTAMP`
начинают читаться по-другому, а метки в логах перестают коррелировать с
метками приложения.

Партнёры по теме: [Кодировки и сортировки](./charset-and-collation.md) —
вторая серверная настройка уровня сервера/сессии; [Резервное копирование
mysqldump](./backup_and_recovery/mysqldump.md) — `--tz-utc` при дампе;
[Конфигурация MySQL](./configuration.md) — `log_timestamps` и
`default-time-zone` в my.cnf.

## Определения

| Термин | Значение |
| :--- | :--- |
| `system_time_zone` | Часовой пояс ОС, который сервер взял при старте (только чтение) |
| `time_zone` | Пояс, в котором сервер интерпретирует и показывает `TIMESTAMP` (глобальная и сессионная переменные) |
| `default_time_zone` | Имя параметра в my.cnf (option file); в runtime соответствует переменной `time_zone`. Принимает те же форматы: `'SYSTEM'`, именованный пояс или смещение `'+03:00'` |
| `log_timestamps` | Пояс меток в error/slow/general логах (`UTC` или `SYSTEM`) |
| `timestamp` | Системная переменная сессии для симуляции времени в тестах: `SET timestamp = <unixtime>` влияет на `NOW()`, `CURTIME()`, `DEFAULT CURRENT_TIMESTAMP`. При `SET timestamp = 0` отключается симуляция — используется реальное время |
| Именованный пояс | Формат `'Europe/Moscow'`; требует загруженных таблиц `mysql.time_zone*` |
| Смещение | Формат `'+03:00'`; работает всегда, без таблиц |

## Базовые концепции

### Три уровня часового пояса

| Переменная | Что определяет | Проверка |
| :--- | :--- | :--- |
| `system_time_zone` | Часовой пояс ОС (только чтение) | `SHOW VARIABLES LIKE 'system_time_zone';` |
| `time_zone` (глобальная / сессионная) | Пояс сервера для `NOW()`, `CURTIME()`, `TIMESTAMP` | `SELECT @@global.time_zone, @@session.time_zone;` |
| `log_timestamps` | Пояс меток в error/slow/general логах | `SHOW VARIABLES LIKE 'log_timestamps';` |

### Как хранят время типы

- **`TIMESTAMP`** хранится в UTC и конвертируется в `time_zone` при
  чтении. Диапазон: `'1970-01-01 00:00:01'` UTC — `'2038-01-19 03:14:07'`
  UTC. По умолчанию текущий пояс соединения — пояс сервера; пояс можно
  задавать на уровне соединения.
- **`DATETIME`** хранится «как есть», без учёта пояса: ни при записи, ни при
  чтении конвертации нет.
- **`UTC_TIMESTAMP()`** возвращает время в UTC независимо от `time_zone` —
  безопасная функция для меток аудита и логов приложения.

### Именованные пояса и таблицы `mysql.time_zone*`

Именованные пояса (`'Europe/Moscow'`) требуют загруженных таблиц
`mysql.time_zone_name`, `mysql.time_zone_transition` и др. Без них —
только смещения `'+03:00'`.

> **Подводный камень:** `SET time_zone = 'UTC'` даёт
> `ERROR 1298 (HY000): Unknown or incorrect time zone: 'UTC'`, если таблицы
> поясов не загружены — `'UTC'` для сервера тоже именованный пояс. Смещение
> `'+00:00'` работает всегда.

### Почему `time_zone = SYSTEM` опасен под нагрузкой

При значении `SYSTEM` каждый вызов функции, требующей расчёта пояса,
выполняет системный вызов для определения текущего пояса ОС. Этот вызов
может быть защищён глобальным мьютексом — источник contention на
высоконагруженных инстансах. Конкретный пояс (`'+03:00'` или
`'Europe/Moscow'`) такого системного вызова не делает.

### Часовой пояс на уровне соединения

`time_zone` имеет область видимости **GLOBAL** и **SESSION** — каждое
соединение может переопределить пояс без влияния на остальных:

```sql
-- В клиентском приложении: перевести TIMESTAMP в нужный пояс для вывода
SET time_zone = 'Europe/Moscow';

-- Или через флаг клиента mysql:
-- mysql --default-time-zone='Europe/Moscow' -u root -p

-- Сбросить к глобальному значению:
SET time_zone = DEFAULT;
-- или
SET time_zone = @@global.time_zone;
```

Это важно для BI-инструментов и администраторов, которые читают `TIMESTAMP`
из базы в разных регионах: глобальный `time_zone` гарантирует согласованность
данных, а сессионный — удобство отображения. При этом `log_timestamps`
(см. таблица выше) управляет **только логами** и не зависит от сессионного
`time_zone`.

## Предварительные требования

1. **MySQL 8.0 / 8.4 LTS / 9.x** с доступом пользователя с правами
   `SYSTEM_VARIABLES_ADMIN` (или устаревшего `SUPER`) для изменения
   `time_zone`, `RESTART` — для применения изменений `default_time_zone` в
   my.cnf.
2. **tzdata в ОС** (Linux/macOS/FreeBSD/Solaris): `mysql_tzinfo_to_sql`
   читает `/usr/share/zoneinfo`. Проверьте: `ls /usr/share/zoneinfo/`.
3. **Для Windows:** в ОС нет zoneinfo — используйте загружаемый пакет
   с [MySQL Developer Zone](https://dev.mysql.com/downloads/timezones.html)
   (см. Сценарий 4).
4. **Для репликации:** все серверы источника и реплики должны иметь
   согласованный `time_zone` (рекомендуется `UTC`); таблицы поясов должны быть
   загружены на всех узлах (см. Сценарий 4).

## Практические сценарии

### Сценарий 1. Диагностика «сдвинулись значения TIMESTAMP»

```sql
-- Что сейчас действует
SHOW VARIABLES LIKE 'time_zone';
SHOW VARIABLES LIKE 'system_time_zone';
SHOW VARIABLES LIKE 'log_timestamps';

-- Абсолютное время vs время сервера: расхождение = действующий пояс
SELECT NOW() AS server_time, UTC_TIMESTAMP() AS utc_time;

-- Конвертация между поясами (вернёт NULL, если именованный пояс не загружен)
SELECT CONVERT_TZ('2026-01-15 10:00:00', 'UTC', 'Europe/Moscow');

-- Симуляция момента времени для тестов (UNIX-метка)
SET time_zone = '+00:00';
SET timestamp = 1230767999;
SELECT NOW();
-- → 2008-12-31 23:59:59
```

Типичные выводы:

- `NOW()` сдвинута относительно `UTC_TIMESTAMP()` на постоянную разницу —
  действует фиксированное смещение, данные целы, просто пояс другой.
- `NOW()` «плывёт» по часам (смена летнего/зимнего времени) — действует
  именованный пояс, а данные записывались при другом.

### Сценарий 2. Загрузка таблиц часовых поясов

```bash
# Загрузить пояса из tzdata ОС (Linux: /usr/share/zoneinfo)
mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root -p mysql
```

```sql
-- Проверка: сколько именованных поясов доступно
SELECT COUNT(*) FROM mysql.time_zone_name;
-- → 0 — именованные пояса не загружены, используйте '+HH:MM'
-- → 593 — пояса загружены, можно 'Europe/Moscow'
```

### Сценарий 3. Единообразие логов и дампов

```ini
# my.cnf: метки логов в UTC независимо от пояса ОС
[mysqld]
log_timestamps = UTC
default-time-zone = '+03:00'   # или named zone, если таблицы загружены
```

- `log_timestamps` влияет **только на логи**, не на данные. По умолчанию
  `UTC` — и в MySQL 5.7, и в 8.0/8.4. Метки пишутся в ISO 8601/RFC 3339:
  `2020-08-07T15:02:00.832521Z` (UTC) или `2020-08-07T10:02:00.832521-05:00`
  (SYSTEM).
- **`mysqldump --tz-utc` включён по умолчанию**: mysqldump устанавливает
  пояс соединения в UTC и пишет `SET TIME_ZONE='+00:00'` в начало дампа,
  что делает `TIMESTAMP` переносимыми между серверами в разных поясах и
  защищает от перехода на летнее/зимнее время. Отключается
  `--skip-tz-utc`. Подробно — [mysqldump](../backup_and_recovery/mysqldump.md).
- Задать пояс серверу на старте: `--default-time-zone='Europe/Moscow'` в
  командной строке или `default-time-zone='Europe/Moscow'` в option file.
   Изменить в рантайме: `SET GLOBAL time_zone = ...` (требуется
   `SYSTEM_VARIABLES_ADMIN` или устаревший `SUPER`).

### Сценарий 4. Загрузка таблиц поясов в топологии репликации и на Windows

**Репликация.** Загрузка таблиц поясов пишет в `mysql.time_zone*` — эти
таблицы реплицируются. Чтобы не захламлять бинарный лог и не реплицировать
на реплики, используйте `--skip-write-binlog`:

```bash
# На источнике: загрузка без записи в binlog
mysql_tzinfo_to_sql --skip-write-binlog /usr/share/zoneinfo | mysql -u root -p mysql

# Затем вручную загрузите на реплики (они не получили изменения через binlog):
#   mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root -p mysql
```

После загрузки **перезапустите `mysqld` на каждом узле** — сервер кэширует
таблицы поясов при старте, и без рестарта `CONVERT_TZ()` может возвращать
`NULL` даже после загрузки.

**Windows.** В ОС Windows нет zoneinfo (`/usr/share/zoneinfo`). Используйте
загружаемый пакет с [MySQL Developer Zone](https://dev.mysql.com/downloads/timezones.html):

```bash
# 1. Скачайте timezone_YYYYx_posix_sql.zip (POSIX) или timezone_YYYYx_leaps_sql.zip (с leap seconds)
# 2. Распакуйте архив
# 3. Загрузите SQL-файлы в mysql.time_zone*
mysql -u root -p mysql < timezone_posix_sql/timezone_posix.sql
```

> **Важно:** используйте пакет с `InnoDB`-таблицами (MySQL 8.0+). Пакеты с
> `MyISAM`-таблицами — для устаревших версий и вызывают ошибки в 8.x.

**Вспышка с DST-правками.** Когда правила перехода на летнее время меняются
(например, отмена переходов в РФ в 2014), перезагружайте таблицы поясов:

```bash
# После обновления tzdata в ОС
mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root -p mysql
# Затем RESTART mysqld — сервер кэширует таблицы поясов при старте
```

## Валидация

```sql
-- 1. Пояс задан явно, не SYSTEM
SELECT @@global.time_zone, @@session.time_zone;
-- → '+03:00' | '+03:00'

-- 2. Логи в UTC
SHOW VARIABLES LIKE 'log_timestamps';
-- → log_timestamps | UTC

-- 3. Именованные пояса доступны (если используются)
SELECT COUNT(*) FROM mysql.time_zone_name;
-- → > 0

-- 4. Абсолютное время совпадает с ожидаемым
SELECT NOW() = UTC_TIMESTAMP() + INTERVAL 3 HOUR;
-- → 1   (при time_zone = '+03:00')
```

**Для репликации** — дополнительная проверка согласованности поясов
между источником и репликами (выполняется на каждом узле):

```sql
-- 5. Убедиться, что на реплике time_zone = UTC (или согласован с источником)
SELECT @@global.time_zone, @@session.time_zone;
-- → '+00:00' | '+00:00'   (рекомендуется на всех узлах)

-- 6. Таблицы поясов загружены на реплике после --skip-write-binlog
SELECT COUNT(*) FROM mysql.time_zone_name;
-- → > 0   (если загружали с --skip-write-binlog, реплика не получила данные автоматически)
```

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Значения `TIMESTAMP` «сдвинулись» после переезда/перезапуска | `time_zone = SYSTEM` на старом сервере, другой `TZ` в новом | Задать `time_zone` явно; сравнить `NOW()` и `UTC_TIMESTAMP()` |
| `ERROR 1298 (HY000): Unknown or incorrect time zone: '...'` | Именованный пояс не загружен (`mysql.time_zone_name` пуста) | `mysql_tzinfo_to_sql ... \| mysql mysql` либо смещение `'+HH:MM'` |
| `SET time_zone = 'UTC'` не работает | `'UTC'` — именованный пояс, требует таблиц | Использовать `'+00:00'` |
| `CONVERT_TZ()` возвращает `NULL` | Аргумент-имя пояса не загружен | Загрузить таблицы поясов или использовать смещения |
| Метки логов не совпадают с метками приложения | `log_timestamps = SYSTEM`, пояс ОС ≠ пояс логов приложения | `log_timestamps = UTC` |
| Дамп восстанавливается со сдвигом на другой машине | `--skip-tz-utc` или разные пояса source/target | Использовать `--tz-utc` (по умолчанию) |
| Нагрузка CPU/mutex на высоконагруженном инстансе | `time_zone = SYSTEM`: системный вызов под глобальным мьютексом | Задать конкретный пояс (`'+HH:MM'` или именованный) |
| `CONVERT_TZ()` возвращает `NULL` на реплике после загрузки на источнике | Таблицы поясов загружены с `--skip-write-binlog` — реплика не получила изменения | Вручную загрузить `mysql_tzinfo_to_sql` на реплике; перезапустить `mysqld` |
| `CONVERT_TZ()` возвращает `NULL` после загрузки таблиц поясов | `mysqld` не перезапущен — кэш старых (пустых) таблиц поясов | `RESTART mysqld` (сервер кэширует таблицы поясов при старте) |
| `ERROR 1298` с именованным поясом на Windows | На Windows нет `/usr/share/zoneinfo`; таблицы не загружены | Скачать пакет с [MySQL Developer Zone](https://dev.mysql.com/downloads/timezones.html) и загрузить в `mysql.time_zone*` |

## Лучшие практики

- **Задавать `time_zone` явно, не `SYSTEM`.** Стабильность при переезде в
  контейнер с другим `TZ` и снятие mutex contention.
- **`log_timestamps = UTC`** для единообразия логов в распределённой
  инфраструктуре.
- **Загрузить таблицы поясов** (`mysql_tzinfo_to_sql`), если нужны
  именованные пояса; иначе использовать только смещения `'+HH:MM'`.
- **Моменты событий — в `TIMESTAMP`** (абсолютное время) или в `DATETIME`
  с документированным согласованным поясом; для аудита — `UTC_TIMESTAMP()`.
- **Не отключать `--tz-utc`** в mysqldump без необходимости.
- **Тестировать переезд**: сравнить `NOW()`, `UTC_TIMESTAMP()`,
  `CONVERT_TZ()` до и после миграции.
- **Репликация:** `time_zone = 'UTC'` на всех узлах (источник + реплики);
  таблицы поясов загружать с `--skip-write-binlog` на источнике и вручную
  на репликах.
- **Перезапуск после загрузки:** `RESTART mysqld` после `mysql_tzinfo_to_sql`,
  чтобы сбросить кэш таблиц поясов.
- **Windows:** для именованных поясов используйте загружаемый пакет с
  [MySQL Developer Zone](https://dev.mysql.com/downloads/timezones.html)
  (только InnoDB, не MyISAM).

## Очистка и откат

- **Сброс к глобальному `time_zone`:**
  ```sql
  SET time_zone = DEFAULT;
  -- или
  SET time_zone = @@global.time_zone;
  ```
- **Откат `default_time_zone` из my.cnf:** удалите или закомментируйте строку
  `default-time-zone` в `my.cnf` и перезапустите `mysqld`. Без перезапорта
  изменения в `[mysqld]` не применятся.
- **Откат `log_timestamps`:** удалите строку `log_timestamps` из `my.cnf`
  (по умолчанию `UTC`); перезапуск не требуется — `SET GLOBAL log_timestamps = 'UTC'`.
- **Сброс `timestamp` (симуляция времени):**
  ```sql
  SET timestamp = 0;  -- 0 = использовать реальное время
  ```
- **Удаление таблиц поясов:** если именованные поясы больше не нужны, можно
  очистить таблицы (рекомендуется через перезапуск, чтобы сбросить кэш):
  ```sql
  -- Требует root / SYSTEM_VARIABLES_ADMIN
  SET sql_mode = 'ALLOW_INVALID_DATES';
  TRUNCATE mysql.time_zone;
  TRUNCATE mysql.time_zone_name;
  TRUNCATE mysql.time_zone_transition;
  TRUNCATE mysql.time_zone_transition_type;
  TRUNCATE mysql.time_zone_leap_second;
   -- RELOAD или RESTART mysqld для сброса кэша таблиц поясов
  ```
- **Восстановление из дампа с `--skip-tz-utc`:** если дамп создавался с
  `--skip-tz-utc`, `TIMESTAMP` восстанавливается в поясе источника — при
   необходимости выполните `SET time_zone = <original_zone>` перед вставкой.

## Дополнительная информация

### Граничные случаи и ограничения

- **`TIMESTAMP` упирается в 2038**: диапазон заканчивается
  `'2038-01-19 03:14:07'` UTC; для более поздних дат — `DATETIME`.
- **С 8.0.19** при вставке в `TIMESTAMP`/`DATETIME` можно указать смещение
  в значении: `INSERT ... VALUES ('2026-01-15 10:00:00+03:00')`.
- **С 8.4** `CAST(... AT TIME ZONE ...)` преобразует `TIMESTAMP` в `DATETIME`
  в указанном поясе (в отличие от `CONVERT_TZ`, который возвращает `NULL`
  при отсутствии таблиц поясов):
  ```sql
  SELECT CAST(NOW() AT TIME ZONE INTERVAL '+00:00' AS DATETIME);
  -- → 2026-10-10 08:11:55   (пример; время зависит от момента выполнения)
  ```
- Имена поясов нечувствительны к регистру; смещения — `'[H]H:MM'` со знаком
  (`'+10:00'`, `'-6:00'`, `'+05:30'`).
- `SET timestamp = <unixtime>` — симуляция текущего времени для тестов
  (влияет на `NOW()`, `CURTIME()` и `DEFAULT CURRENT_TIMESTAMP`).
- **Windows:** нет `/usr/share/zoneinfo` — именованные пояса недоступны
  без загружаемого пакета с
  [MySQL Developer Zone](https://dev.mysql.com/downloads/timezones.html).
  Используйте смещения `'+HH:MM'` либо загрузите пакет в `mysql.time_zone*`.
  Пакеты с `MyISAM`-таблицами (для MySQL 5.7-) вызывают ошибки в 8.0+.
- **Leap seconds:** `mysql_tzinfo_to_sql --leap /usr/share/zoneinfo/UTC`
  загружает информацию о leaping seconds в `mysql.time_zone_leap_second`.
  Без этого `TIMESTAMP` может отставать/опережать на 1 секунду в дни
  введения коррекции.
- **Клиентский пояс:** `mysql --default-time-zone='+00:00'` задаёт пояс
  соединения на клиентской стороне, не влияя на сервер. Аналогично
  `SET time_zone` после подключения. В JDBC: параметр `connectionTimeZone`
  в URL.
- **Репликация и DST:** если источник и реплика в разных поясах, `TIMESTAMP`
  в binlog хранится в поясе источника. При воспроизведении репликой значение
  конвертируется обратно — но только если таблицы поясов загружены на обоих
  узлах. Рекомендация: `time_zone = 'UTC'` на всех узлах репликации.

### Внешние ресурсы

- [MySQL Reference Manual: MySQL Server Time Zone Support](https://dev.mysql.com/doc/refman/8.4/en/time-zone-support.html)
- [MySQL Reference Manual: mysql_tzinfo_to_sql](https://dev.mysql.com/doc/refman/8.4/en/mysql-tzinfo-to-sql.html) — загрузка таблиц поясов, `--leap`, `--skip-write-binlog`
- [MySQL Reference Manual: Server System Variables](https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html) — `time_zone`, `default_time_zone`, `timestamp`
- [MySQL Reference Manual: The DATE, DATETIME, and TIMESTAMP Types](https://dev.mysql.com/doc/refman/8.4/en/datetime.html)
- [MySQL Reference Manual: Error Log Output Format](https://dev.mysql.com/doc/refman/8.4/en/error-log-format.html) — `log_timestamps`
- [MySQL Reference Manual: mysqldump](https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html) — `--tz-utc`
- [MySQL Developer Zone: Time Zone Downloads](https://dev.mysql.com/downloads/timezones.html) — пакет для Windows

### См. также

- **[Кодировки и сортировки](./charset-and-collation.md)** — character set
  и collation, вторая серверная настройка уровня сервера/сессии.
- **[Конфигурация MySQL](./configuration.md)** — `log_timestamps` и
  `default-time-zone` в my.cnf.
- **[Резервное копирование mysqldump](./backup_and_recovery/mysqldump.md)**
  — `--tz-utc` (включён по умолчанию) и `--skip-tz-utc` при дампе.
- **[Управление репликацией (debug)](./replication/management_debug.md)**
  — `time_zone = 'UTC'` на всех узлах репликации.
- **[Timezone handling в PostgreSQL](../PostgreSQL/Concepts/timezone_handling.md)**
  — сравнение моделей поясов: `timestamptz` в PostgreSQL против `TIMESTAMP`
  в MySQL.
