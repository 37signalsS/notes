# Часовые пояса (Time Zones) в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **`time_zone`** — серверная переменная, определяющая часовой пояс, в котором MariaDB интерпретирует и возвращает значения `TIMESTAMP` и функции `NOW()`, `CURTIME()`, `CURRENT_TIMESTAMP()`. По умолчанию — `SYSTEM` (часовой пояс ОС).
*   **`system_time_zone`** — часовой пояс, определённый при запуске сервера из настроек ОС. Только для чтения; не меняется через `SET`.
*   **`default_time_zone`** — синоним глобального значения `time_zone`; задаётся при запуске сервера опцией `--default-time-zone` (или `default_time_zone` в option-файле).
*   **`TIMESTAMP`** — тип данных, хранящий значение в UTC и конвертирующий его в текущий `time_zone` при чтении. Зависит от часового пояса сессии.
*   **`DATETIME`** — тип данных, хранящий значение «как есть», без привязки к часовому поясу. Не конвертируется при чтении.
*   **Таблицы часовых поясов (`mysql.time_zone*`)** — набор таблиц (`time_zone`, `time_zone_name`, `time_zone_transition`, `time_zone_transition_type`, `time_zone_leap_second`), содержащих именованные часовые пояса (например, `America/New_York`) с учётом перехода на летнее время (DST). Без загруженных таблиц именованные зоны недоступны — работают только `SYSTEM` и UTC-смещения. По умолчанию таблицы создаются, но **не заполняются**.
*   **`CONVERT_TZ()`** — функция конвертации значения между часовыми поясами. Требует загруженных таблиц часовых поясов для именованных зон.
*   **`mariadb-tzinfo-to-sql`** — утилита загрузки данных часовых поясов из системной базы zoneinfo в таблицы `mysql.time_zone*`. Ранее называлась `mysql_tzinfo_to_sql`; старое имя доступно через symlink (Linux) или alternate binary (Windows).

## Базовые концепции

### Форматы значения `time_zone`

Переменная `time_zone` принимает три формата:

| Формат | Пример | Описание |
| :--- | :--- | :--- |
| **SYSTEM** | `SYSTEM` | Часовой пояс ОС (по умолчанию) |
| **UTC-смещение** | `+05:00`, `-08:00` | Фиксированное смещение от UTC |
| **Именованная зона** | `Europe/Moscow`, `America/New_York` | Требует загруженных таблиц `mysql.time_zone*` |

### TIMESTAMP vs DATETIME

*   **`TIMESTAMP`:** хранится в UTC, конвертируется в `time_zone` сессии при чтении. При смене часового пояса сессии одно и то же значение отображается по-разному. Диапазон зависит от версии:
    *   **MariaDB 11.5 и новее:** `1970-01-01 00:00:01` UTC — `2106-02-07 06:28:15` UTC.
    *   **До MariaDB 11.5:** `1970-01-01 00:00:01` UTC — `2038-01-19 03:14:07` UTC.
    *   Значение `1970-01-01 00:00:00` UTC зарезервировано: секунда #0 используется для представления `0000-00-00 00:00:00`.
*   **`DATETIME`:** хранится без привязки к поясу. Не зависит от `time_zone`. Диапазон: `1000-01-01` — `9999-12-31`.

**Проверка литералов по поясу сессии:** MariaDB проверяет литералы `TIMESTAMP` в контексте `time_zone` сессии. Если момент времени не существовал в заданном поясе (пропуск при переходе на летнее время), значение невалидно для этого пояса. Например, `2026-03-08 02:30:00` в `America/New_York` не существует: в это воскресенье часы переводятся с 02:00 на 03:00.

MariaDB не хранит идентификатор часового пояса вместе со значением `TIMESTAMP` (MDEV-10018) и не поддерживает литералы времени с идентификаторами поясов (MDEV-11829).

**Практическое правило:** для хранения абсолютных моментов времени (события, логи) используйте `TIMESTAMP` (или `DATETIME` в UTC). Для «локальных» значений, не зависящих от пояса (например, время открытия магазина), используйте `DATETIME`.

### Функции, зависящие от часового пояса

*   **Зависят от `time_zone`:** `NOW()`, `SYSDATE()`, `CURDATE()`, `CURTIME()`, `UNIX_TIMESTAMP()`.
*   **Не зависят:** `UTC_DATE()`, `UTC_TIME()`, `UTC_TIMESTAMP()`.

### Как определяется и меняется `system_time_zone`

`system_time_zone` определяется при запуске сервера из окружения ОС и не меняется через `SET` — для изменения требуется действовать на уровне ОС и перезапустить сервер:

```bash
# Переменная окружения TZ перед запуском сервера
export TZ='America/New_York'
service mariadb start

# Symlink /etc/localtime на нужную зону (Unix)
sudo rm /etc/localtime
sudo ln -s /usr/share/zoneinfo/America/New_York /etc/localtime

# Debian/Ubuntu
sudo dpkg-reconfigure tzdata

# systemd (Linux)
sudo timedatectl set-timezone America/New_York
```

Либо опция `--timezone` утилиты `mariadbd-safe` (группа `[mariadbd-safe]` в option-файле):

```ini
[mariadbd-safe]
timezone='America/New_York'
```

### Загрузка таблиц часовых поясов

Именованные зоны (`Europe/Moscow` и т.п.) работают только после загрузки системных таблиц. **По умолчанию таблицы создаются, но не заполняются** — не полагайтесь на автоматическую загрузку, проверяйте запросом.

**Требования:** доступ к серверу с привилегией `SUPER`/`SYSTEM_VARIABLES_ADMIN`; наличие базы zoneinfo (`/usr/share/zoneinfo` на Linux, macOS, FreeBSD; `/usr/share/lib/zoneinfo` на Solaris). Windows не имеет zoneinfo — используются предзагруженные таблицы (см. ниже).

```bash
# Проверить, загружены ли таблицы
mariadb -u root -p -e "SELECT COUNT(*) FROM mysql.time_zone_name;"
# → 0 — таблицы не загружены; > 0 — загружены

# Загрузить все зоны из /usr/share/zoneinfo (Linux)
mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb -u root -p mysql

# Для конкретной зоны: файл зоны + имя зоны
mariadb-tzinfo-to-sql /usr/share/zoneinfo/Europe/Moscow Europe/Moscow | mariadb -u root -p mysql

# С учётом високосных секунд (файл зоны с leap seconds, при наличии — обычно right/)
mariadb-tzinfo-to-sql --leap /usr/share/zoneinfo/right/UTC | mariadb -u root -p mysql
```

**Важно:**

*   После загрузки или перезагрузки таблиц (например, при обновлении правил DST) **перезапустите сервер**: старые значения поясов действуют до перезапуска, а новые данные корректно подхватываются только после рестарта.
*   **Windows:** импортируйте предзагруженные таблицы часовых поясов с зеркал MariaDB: <https://mirror.mariadb.org/zoneinfo/>.
*   **Обновление правил DST:** при обновлении системного пакета `tzdata` перезагрузите таблицы тем же способом — правила перехода на летнее время меняются (например, отмена перехода на летнее время в РФ).

**Сброс таблиц** (например, перед повторной загрузкой):

```sql
TRUNCATE TABLE mysql.time_zone;
TRUNCATE TABLE mysql.time_zone_name;
TRUNCATE TABLE mysql.time_zone_transition;
TRUNCATE TABLE mysql.time_zone_transition_type;
TRUNCATE TABLE mysql.time_zone_leap_second;
```

**Привилегии:** `SET GLOBAL time_zone` требует `SUPER` (legacy) или `SYSTEM_VARIABLES_ADMIN`; `SET time_zone` для сессии — `SESSION_VARIABLES_ADMIN` (MariaDB 10.5+).

## Практические сценарии

### 1. Проверка и настройка часового пояса

```sql
-- Текущий часовой пояс сессии и сервера
SELECT @@time_zone, @@system_time_zone;
SHOW SESSION VARIABLES LIKE 'time_zone';
SHOW GLOBAL VARIABLES LIKE 'time_zone';

-- Текущее время
SELECT NOW(), UTC_TIMESTAMP();

-- Установить часовой пояс сессии
SET time_zone = 'Europe/Moscow';
SET time_zone = '+05:00';
SET time_zone = 'SYSTEM';

-- Установить глобальный часовой пояс (требует SUPER / SYSTEM_VARIABLES_ADMIN)
SET GLOBAL time_zone = 'Europe/Moscow';

-- Проверить именованные зоны
SELECT Name FROM mysql.time_zone_name ORDER BY Name;
```

**Валидация:** после `SET time_zone = 'Europe/Moscow'` запрос `SELECT NOW()` должен возвращать время в московском поясе, а `UTC_TIMESTAMP()` — в UTC.

### 2. Конвертация между поясами

```sql
-- Конвертировать значение между поясами
SELECT CONVERT_TZ('2026-10-04 12:00:00', 'Europe/Moscow', 'UTC');
-- → 2026-10-04 09:00:00

-- CONVERT_TZ с NULL, если таблицы не загружены
SELECT CONVERT_TZ(NOW(), 'SYSTEM', 'America/New_York');
-- → NULL, если mysql.time_zone* не загружены
```

### 3. Настройка в my.cnf

```ini
[mariadb]
# Фиксированный UTC (рекомендуется для серверов)
default_time_zone = '+00:00'

# Или именованная зона (требует загруженных таблиц)
# default_time_zone = 'Europe/Moscow'
```

### 4. Работа с TIMESTAMP в приложениях

```sql
-- Хранение в UTC, чтение в локальном поясе
SET time_zone = '+00:00';
INSERT INTO events (created_at) VALUES (NOW());  -- сохранит UTC

SET time_zone = 'Europe/Moscow';
SELECT created_at FROM events;  -- вернёт в московском поясе
```

### 5. PITR: временные метки в mariadb-binlog

Опции `--start-datetime` / `--stop-datetime` утилиты `mariadb-binlog` (ранее `mysqlbinlog`) интерпретируются **в локальном времени машины, где запущен клиент**, а не сервера. При восстановлении на другой машине учитывайте её часовой пояс (`TZ`):

```bash
mariadb-binlog --start-datetime="2026-10-04 09:00:00" --stop-datetime="2026-10-04 10:00:00" \
  /var/lib/mysql/mariadb-bin.000001
```

## Устранение неполадок (Troubleshooting)

### `CONVERT_TZ()` возвращает NULL

*   **Причина:** таблицы часовых поясов (`mysql.time_zone*`) не загружены.
*   **Диагностика:** `SELECT COUNT(*) FROM mysql.time_zone_name;` — если 0, таблицы не загружены.
*   **Решение:** загрузите таблицы: `mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb -u root -p mysql` (или `mysql_tzinfo_to_sql` — старое имя той же утилиты).

### Именованные зоны не появились после загрузки таблиц

*   **Причина:** сервер использует загруженные в память значения часовых поясов до перезапуска.
*   **Решение:** перезапустите сервер после `mariadb-tzinfo-to-sql`: `sudo systemctl restart mariadb`.

### Значение `TIMESTAMP` отклоняется в DST-пробеле

*   **Причина:** MariaDB проверяет литералы `TIMESTAMP` по `time_zone` сессии; время, которое не наступало в поясе (переход на летнее время), невалидно.
*   **Пример:** `2026-03-08 02:30:00` при `time_zone = 'America/New_York'` — в это воскресенье часы переводятся с 02:00 на 03:00, значения интервала 02:00–03:00 не существуют.
*   **Решение:** записывайте такие значения в UTC (`SET time_zone = '+00:00'`) или используйте `DATETIME` для наивных (без пояса) значений.

### Разное время на source и replica

*   **Причина:** при statement-based (SBR) или mixed репликации функции `NOW()`, `CURTIME()`, `UNIX_TIMESTAMP()` вычисляются на source, но если `system_time_zone` различается, результаты расходятся.
*   **Решение:** используйте одинаковый `system_time_zone` на всех узлах репликации, либо `binlog_format = ROW` (значения реплицируются как данные), либо храните время в UTC. Подробно — [Репликация: обзор](replication/overview.md).

### Время «съезжает» после смены `time_zone`

*   **Причина:** `TIMESTAMP` конвертируется в текущий `time_zone` сессии. Если приложение меняет пояс сессии, значения `TIMESTAMP` отображаются по-разному.
*   **Решение:** зафиксируйте `time_zone` на уровне приложения или используйте `DATETIME` для значений, которые не должны конвертироваться.

### Нет переменной `log_timestamps`

*   **Контекст:** `log_timestamps` (часовой пояс меток error/slow/general логов) — системная переменная **только MySQL**; в MariaDB такой переменной нет.
*   **Решение:** в MariaDB метки error log имеют формат `YYYY-MM-DD HH:MM:SS` без явного указания пояса; при корреляции логов между серверами проверяйте часовой пояс ОС каждого узла.

## Лучшие практики (Best Practices)

1.  **Храните время в UTC:** используйте `default_time_zone = '+00:00'` на сервере и `TIMESTAMP` (или `DATETIME` в UTC) для абсолютных моментов.
2.  **Проверьте и при необходимости загрузите таблицы часовых поясов** при установке — иначе именованные зоны и `CONVERT_TZ()` не работают.
3.  **Перезапускайте сервер после загрузки или обновления таблиц** — новые данные поясов подхватываются только после рестарта.
4.  **Обновляйте `tzdata` в ОС** (`apt upgrade tzdata` / `dnf update tzdata`) и перезагружайте таблицы — правила DST меняются.
5.  **Единый пояс в репликации:** `system_time_zone` должен совпадать на всех узлах при SBR/mixed; для ROW-формата это менее критично.
6.  **Не смешивайте TIMESTAMP и DATETIME** без понимания разницы: `TIMESTAMP` зависит от пояса сессии, `DATETIME` — нет.
7.  **Явно указывайте пояс в приложении** (`SET time_zone` при подключении), чтобы избежать зависимости от серверного дефолта.
8.  **Контейнеры:** в контейнере `SYSTEM` следует за `/etc/localtime` образа (часто UTC). Задавайте пояс явно — переменной `TZ` перед запуском сервера или `default_time_zone` в `my.cnf` — см. [Docker](docker.md).

## Дополнительная информация

### См. также

*   **[Репликация: обзор](replication/overview.md)** — влияние часовых поясов на SBR-репликацию.
*   **[Конфигурация](configuration.md)** — настройка `my.cnf`.
*   **[Docker](docker.md)** — часовой пояс в контейнерах.

### Внешние ресурсы

*   [MariaDB Time Zones](https://mariadb.com/kb/en/time-zones/)
*   [MariaDB CONVERT_TZ](https://mariadb.com/kb/en/convert_tz/)
*   [MariaDB TIMESTAMP](https://mariadb.com/kb/en/timestamp/)
*   [MariaDB mariadb-tzinfo-to-sql](https://mariadb.com/kb/en/mariadb-tzinfo-to-sql/)
*   [Предзагруженные таблицы часовых поясов для Windows](https://mirror.mariadb.org/zoneinfo/)
