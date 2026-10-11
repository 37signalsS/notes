# SQL_MODE в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 12.3 LTS

## Определения

**SQL_MODE** — набор флагов, изменяющих поведение парсера, проверки данных и интерпретации неоднозначных конструкций. Хранится в одноимённой системной переменной с глобальным и сессионным уровнем.

**Strict mode** — состояние, при котором хотя бы один из флагов `TRADITIONAL`, `STRICT_TRANS_TABLES` или `STRICT_ALL_TABLES` включён. В strict mode недопустимые значения вызывают ошибку, а не молчаливое приведение к допустимому — это разница между потерей данных и её предотвращением.

**Compatibility mode** — флаги, переключающие синтаксис и семантику на поведение другого диалекта: `ORACLE`, `MSSQL`, `POSTGRESQL`, `DB2`, `MAXDB`, `ANSI`. Применяются для миграции приложения без переписывания, а не как постоянная настройка сервера.

## Основные концепты

### Значение по умолчанию

MariaDB не наследует дефолт MySQL. Актуальное значение по умолчанию:

| Версия | `sql_mode` по умолчанию |
|---|---|
| 10.11 LTS | `STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION` |
| 11.4 LTS | то же |
| 12.3 LTS | `STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION` |

```sql
SELECT @@global.sql_mode, @@session.sql_mode;
-- → STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION
-- (MariaDB 12.3 LTS: STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION)
```

Значение по умолчанию действует с MariaDB 10.2.4; в 10.1.7 было `NO_ENGINE_SUBSTITUTION,NO_AUTO_CREATE_USER`, в 10.1.6 и старше — пустое значение.

**Чем дефолт MariaDB отличается от дефолта MySQL** — это критично при миграции, потому что приложение, написанное под MySQL, меняет поведение без изменения кода:

| Флаг | MariaDB по умолчанию | MySQL 8.x по умолчанию | Следствие расхождения |
|---|---|---|---|
| `ONLY_FULL_GROUP_BY` | выключен | включён | Запросы с недетерминированным `GROUP BY` проходят на MariaDB и падают на MySQL |
| `NO_ZERO_IN_DATE`, `NO_ZERO_DATE` | выключены | включены | Невалидные даты принимаются MariaDB тихо |
| `NO_AUTO_CREATE_USER` | включён | отсутствует в 8.0+ | Различие при разборе `GRANT` |

Ошибка `ERROR_FOR_DIVISION_BY_ZERO` присутствует в дефолте MariaDB, но помечена как deprecated в MySQL — при миграции в другую сторону поведение снова расходится.

### Практический смысл дефолта

`STRICT_TRANS_TABLES` означает, что ошибка при подстановке значения прерывает оператор, но **не откатывает всю транзакцию**. Для транзакционных таблиц отличать этот режим от `STRICT_ALL_TABLES` существенно: `STRICT_ALL_TABLES` прерывает оператор и в нетранзакционном случае, делая no-op на месте.

Включение `NO_ENGINE_SUBSTITUTION` превращает ошибку «движок недоступен» в ошибку, а не в молчаливую подмену на движок по умолчанию. Для Galera-кластера, где доступен только InnoDB, это защита от неявного создания таблиц в Aria.

### ONLY_FULL_GROUP_BY: почему его нет в дефолте MariaDB

Документация MariaDB формулирует правило жёстко: выбор негруппированной колонки в `SELECT` не определён — «неясно, из какой строки берётся значение», и такой запрос не разрешён при включённом `ONLY_FULL_GROUP_BY`.

```sql
-- При ONLY_FULL_GROUP_BY этот запрос отклоняется
SELECT id, MAX(created_at), email FROM orders GROUP BY id;
```

Отличие от MySQL: MySQL 5.7.5+ определяет функциональную зависимость и разрешает запрос, если колонка однозначно определяется ключом или равенством из `WHERE`/`JOIN`. В MariaDB такого определения нет, поэтому режим строже и включение его ломает запросы, которые на MySQL выполняются. Именно поэтому флаг вынесен из дефолта, а не включён в него.

Практический вывод для прикладной разработки: переносить дефолт MySQL в MariaDB через `SET GLOBAL sql_mode` — не безопасное ужесточение. Если приложение содержит недетерминированные `GROUP BY`, его нужно сначала исправить, и лишь затем включать флаг.

### Режимы совместимости

`ORACLE` — наиболее полезный на практике: даёт PL/SQL-совместимый синтаксис для хранимых процедур, типы данных и последовательности. Применяется для миграции с Oracle, а не как постоянный режим.

`ANSI` (с MariaDB 10.3.3) — преобразует строковые литералы, созданные парсером, в `NULL`, и пустую строку в prepared statement — в `NULL`.

`PIPES_AS_CONCAT` — переопределяет `||` как оператор конкатенации строк вместо логического «ИЛИ». Это ломает любой код, где `||` использовался как булево условие, и наоборот: без флага запросы, написанные под Oracle-семантику, не разбираются. Флаг не является «ужесточением безопасности» и не должен попадать в общий production-профиль.

### Устаревшие и удалённые параметры, связанные с режимами

`sql_big_tables` и `big_tables` объявлены deprecated в MariaDB 10.5.0 и **удалены в MariaDB 12.0**. Файл конфигурации, унаследованный от 10.x, с этими параметрами не пройдёт старт на 12.3. Проверьте `my.cnf` до апгрейда:

```bash
grep -rnE '^\s*(sql_big_tables|big_tables)\s*=' /etc/mysql/ /etc/my.cnf.d/ 2>/dev/null
# → пусто: миграция на 12.x безопасна
```

## Полный список флагов sql_mode

В таблице приведены все флаги, доступные в MariaDB 10.11 / 11.4 / 12.3. Флаги, удалённые в 10.x или 12.x, помечены.

| Флаг | Категория | Описание |
|---|---|---|
| `STRICT_TRANS_TABLES` | Strict | Ошибка вместо молчаливого усечения/приведения для транзакционных таблиц |
| `STRICT_ALL_TABLES` | Strict | Строгий режим для всех таблиц (включая не транзакционные) |
| `TRADITIONAL` | Composite | Псевдоним для `STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION` |
| `ERROR_FOR_DIVISION_BY_ZERO` | Data integrity | Деление на ноль в `INSERT`/`UPDATE` даёт ошибку (в нестрогом — warning + NULL) |
| `NO_ZERO_DATE` | Data integrity | Запрещает дату `'0000-00-00'` (в строгом режиме эффект включён автоматически) |
| `NO_ZERO_IN_DATE` | Data integrity | Запрещает нули в месяце/дне даты (`'2026-00-01'`). **Deprecated** в MariaDB 10.3+, эффект вошёл в строгий режим |
| `NO_ENGINE_SUBSTITUTION` | Engine | Ошибка, если запрошенный движок недоступен, вместо молчаливой подмены |
| `ONLY_FULL_GROUP_BY` | GROUP BY | Запрещает неагрегированные колонки в SELECT/HAVING/ORDER BY, не входящие в GROUP BY. В MariaDB нет определения функциональной зависимости — флаг строже, чем в MySQL |
| `PIPES_AS_CONCAT` | Syntax | `||` работает как конкатенация строк, а не как логическое ИЛИ |
| `ANSI_QUOTES` | Syntax | Двойные кавычки обрабатываются как идентификаторы, а не как строковые литералы |
| `IGNORE_SPACE` | Syntax | Допускает пробелы между именем функции и открывающей скобкой (`COUNT (*)`) |
| `NO_AUTO_VALUE_ON_ZERO` | Auto-inc | `AUTO_INCREMENT` колонка может быть записана нулём (не генерирует новое значение) |
| `NO_BACKSLASH_ESCAPES` | Strings | Обратный слэш не является экранирующим символом в строковых литералах |
| `NO_UNSIGNED_SUBTRACTION` | Numeric | Результат беззнаковой арифметики не сворачивается в знаковый `DECIMAL` |
| `REAL_AS_FLOAT` | Types | Тип `REAL` трактуется как `FLOAT`, а не как `DOUBLE` |
| `PAD_CHAR_TO_FULL_LENGTH` | Strings | При извлечении `CHAR` дополняется пробелами до полной длины |
| `HIGH_NOT_PRECEDENCE` | Operators | `NOT` имеет приоритет как операторы сравнения, а не выше |
| `TIME_TRUNCATE_FRACTIONAL` | Temporal | Дробная часть секунд усекается, а не округляется (MariaDB 10.2.4+) |
| `ANSI` | Composite | Составной режим: `REAL_AS_FLOAT,PIPES_AS_CONCAT,ANSI_QUOTES,IGNORE_SPACE` + преобразование `''` в `NULL` |
| `DB2` | Compatibility | **Удалён в MariaDB 10.0** — совместимость с DB2 |
| `MAXDB` | Compatibility | **Удалён в MariaDB 10.0** — совместимость с MAXDB (SAP) |
| `MSSQL` | Compatibility | **Удалён в MariaDB 10.0** — совместимость с MS SQL Server |
| `MYSQL323` | Compatibility | **Удалён в MariaDB 10.0** — совместимость с MySQL 3.23 |
| `MYSQL40` | Compatibility | **Удалён в MariaDB 10.0** — совместимость с MySQL 4.0 |
| `ORACLE` | Compatibility | PL/SQL-совместимый синтаксис для процедур, типов, последовательностей |
| `POSTGRESQL` | Compatibility | **Удалён в MariaDB 10.0** — совместимость с PostgreSQL |
| `NO_AUTO_CREATE_USER` | Security | **Удалён в MariaDB 12.0** — запрет неявного создания пользователей через `GRANT`. В 12.0+ `GRANT` никогда не создаёт пользователя |

> **Важно:** составные режимы `DB2`, `MAXDB`, `MSSQL`, `MYSQL323`, `MYSQL40`, `POSTGRESQL` удалены в MariaDB 10.0. Присвоить их `sql_mode` нельзя — попытка даст ошибку запуска. `NO_AUTO_CREATE_USER` удалён в 12.0 (функциональность больше не нужна, `GRANT` не создаёт пользователей).

## Операции и команды

### Просмотр и установка режима

```sql
-- Глобальное значение (для новых соединений)
SELECT @@global.sql_mode;

-- Текущая сессия
SELECT @@session.sql_mode;

-- Установка глобально (не завершает открытые сессии)
SET GLOBAL sql_mode = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION,NO_ZERO_IN_DATE,NO_ZERO_DATE';

-- Установка для текущей сессии
SET SESSION sql_mode = @@global.sql_mode;

-- Добавление одного флага к текущему значению (без разбора строки вручную)
SET SESSION sql_mode = CONCAT(@@session.sql_mode, ',NO_ZERO_DATE');

-- Удаление одного флага
SET SESSION sql_mode = REPLACE(@@session.sql_mode, 'NO_ZERO_DATE', '');
-- Убираем возможную двойную запятую
SET SESSION sql_mode = REPLACE(@@session.sql_mode, ',,', ','); 
SET SESSION sql_mode = TRIM(BOTH ',' FROM @@session.sql_mode);
```

### Валидация strict mode

```sql
-- Тест 1: out of range
CREATE TEMPORARY TABLE t_mode_check (i TINYINT);
INSERT INTO t_mode_check VALUES (257);
-- → ERROR 1264 (22003): Out of range value for column 'i' at row 1
DROP TEMPORARY TABLE t_mode_check;

-- Тест 2: некорректная дата
CREATE TEMPORARY TABLE t_date_check (d DATE);
INSERT INTO t_date_check VALUES ('2026-02-30');
-- → ERROR 1292 (22007): Incorrect datetime value
DROP TEMPORARY TABLE t_date_check;

-- Тест 3: деление на ноль
INSERT INTO t_mode_check VALUES (1/0);
-- → ERROR 1365 (22012): Division by 0
```

Ошибка `1264`, `1292`, `1365` означает, что strict mode работает. Если вместо ошибки значение молча заменилось — режим не действует.

### Проверка расхождения между узлами кластера

```sql
-- На каждом узле Galera / реплике
SELECT @@global.sql_mode, @@hostname, @@server_id;
-- → node-1: STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION
-- → node-2: STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION
-- (MariaDB 12.3: NO_AUTO_CREATE_USER отсутствует в дефолте)

-- Автоматизированная проверка
mysql -h node-1 -N -B -e "SELECT @@global.sql_mode" &
mysql -h node-2 -N -B -e "SELECT @@global.sql_mode" &
mysql -h node-3 -N -B -e "SELECT @@global.sql_mode" &
wait
```

В Galera значения должны совпадать на всех узлах — иначе репликация не гарантирует одинаковый результат запроса.

### Закрепление в my.cnf

```ini
[mariadb]
# Явное перечисление — устойчивее к изменению дефолтов между версиями
sql_mode = STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION,NO_ZERO_IN_DATE,NO_ZERO_DATE
```

```bash
# Валидация конфигурации
mariadbd --validate-config
# → ошибок нет, вывод пуст

systemctl restart mariadb
# → сервер перезапущен

mysql -N -B -e "SELECT @@GLOBAL.sql_mode"
# → STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION,NO_ZERO_IN_DATE,NO_ZERO_DATE
```

## Устранение неполадок (Troubleshooting)

### Ошибка 1366 при вставке, хотя strict mode включён

**Диагностика:** ошибка возникает при включённом strict mode — это ожидаемое поведение, а не сбой. Проверьте тип колонки и реальное значение:

```sql
SHOW CREATE TABLE orders\G
```

Если приложение должно принимать усечение значения, осознанно отключайте strict mode для конкретной операции, а не для сервера:

```sql
SET SESSION sql_mode = REPLACE(@@session.sql_mode, 'STRICT_TRANS_TABLES', '');
SET SESSION sql_mode = REPLACE(@@session.sql_mode, ',,', ',');
SET SESSION sql_mode = TRIM(BOTH ',' FROM @@session.sql_mode);
```

### Неожиданное `NULL` вместо пустой строки в ANSI-режиме

**Причина:** флаг `ANSI` преобразует пустую строку в `NULL` — как при парсинге литерала, так и при биндинге параметра prepared statement.

**Решение:** проверить наличие `ANSI` в списке режимов и убрать его, если приложение различает `''` и `NULL`:

```sql
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION';
SELECT '' IS NULL;
-- → 0: пустая строка осталась строкой
```

### `||` работает как логическое ИЛИ вместо конкатенации

**Причина:** отсутствует `PIPES_AS_CONCAT` в `sql_mode`.

**Диагностика:**

```sql
SELECT @@session.sql_mode LIKE '%PIPES_AS_CONCAT%' AS pipes_as_concat_on;
-- → 1: включён, || — конкатенация
-- → 0: выключен, || — логическое ИЛИ
```

### `sql_mode` изменился после обновления MariaDB

**Симптом:** После `apt upgrade` / `mariadb-upgrade` приложение начинает падать с ошибками `Incorrect integer value` или `Data truncated`.

**Причина:** В новых версиях MariaDB изменился `sql_mode` по умолчанию или `mariadb-upgrade` обновил системные таблицы.

**Решение:**

1. Проверьте текущий режим: `SELECT @@sql_mode;`
2. Сравните с закреплённым в `my.cnf` значением.
3. Если `my.cnf` содержит явное значение — перезапустите сервер.
4. Если `my.cnf` пуст — добавьте нужный профиль в `my.cnf` и перезапустите.

> **Не рекомендуется:** удалять `STRICT_TRANS_TABLES` для совместимости со старым поведением. Предпочтительнее исправить приложение для работы со строгим режимом.

### Сессия приложения игнорирует глобальный sql_mode

**Симптом:** Глобальный режим строгий, а приложение работает в мягком режиме.

**Диагностика:**

```sql
SELECT @@global.sql_mode, @@session.sql_mode;
-- Если global строгий, а session пуст/другой — приложение переопределяет режим в сессии
```

**Причина:** Часть коннекторов и ORM задают `sql_mode` в строке подключения или при инициализации пула. Это делает значение сессии неуправляемым через серверную настройку.

**Решение:**
- Найдите в коде приложения / конфигурации ORM установку `sql_mode` (JDBC: `sessionVariables=sql_mode=...`, Python: `init_command`, Go: `SET VARIABLES`).
- Уберите переопределение или приведите его к нужному профилю.
- Если переопределение необходимо для legacy-кода — выдайте учётной записи привилегию `SESSION_VARIABLES_ADMIN` и настройте режим в строке подключения этого пользователя.

## Лучшие практики (Best Practices)

1. **Не переносите дефолт MySQL в MariaDB.** Дефолт MariaDB уже содержит `STRICT_TRANS_TABLES` и `NO_ENGINE_SUBSTITUTION`. Добавление флагов должно быть обоснованным изменением, а не копированием строки из конфигурации MySQL.

2. **Расширяйте профиль по одному флагу.** Каждое добавление `NO_ZERO_DATE` или `ONLY_FULL_GROUP_BY` способно отклонить запросы, работающие годами. Один флаг — один этап тестирования.

3. **`ONLY_FULL_GROUP_BY` включайте только после исправления запросов.** В MariaDB нет определения функциональной зависимости, поэтому флаг строже, чем в MySQL.

4. **`PIPES_AS_CONCAT` — только для приложений, переносимых с Oracle.** Это не флаг безопасности.

5. **Держите `sql_mode` одинаковым на всех узлах** кластера — включая Galera.

6. **Закрепите `sql_mode` в `my.cnf`, а не только в `SET GLOBAL`.** Значение из `SET GLOBAL` теряется при рестарте, и расхождение обнаружится уже в инциденте.

7. **Включите `sql_mode` в сравнение конфигураций** при проверке апгрейда: расширение состава флагов между линиями меняет поведение без изменения кода.

8. **Проверяйте `@@SESSION.sql_mode` в сессии приложения**, а не только глобальное значение. Это самая частая причина «невозможного» расхождения поведения.

```ini
[mariadb]
sql_mode = STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION,NO_ZERO_IN_DATE,NO_ZERO_DATE
```

## Дополнительная информация

### Источники

- [SQL_MODE | MariaDB Documentation](https://mariadb.com/docs/server/server-management/variables-and-modes/sql_mode)
- [Numeric Data Type Overview — влияние strict mode](https://mariadb.com/docs/server/reference/data-types/numeric-data-types/numeric-data-type-overview)
- [System Variable Differences Between MariaDB and MySQL](https://mariadb.com/docs/release-notes/community-server/about/compatibility-and-differences)

### Смежные темы

- **[Дополнительные параметры безопасности](security/additional-parameters.md)** — где профиль режимов применяется вместе с другими настройками защиты.
- **[Конфигурация MariaDB](configuration.md)** — размещение параметров в `my.cnf`.
- **[Миграция с MySQL на MariaDB](Operations/migration_mysql_to_mariadb.md)** — проверка расхождений переменных при смене вендора.
- **[Zero-Downtime Upgrade](Operations/zero_downtime_upgrade.md)** — что проверять перед переходом на новую линию.
- **[Хранимые объекты: процедуры и функции](Concepts/stored_objects_management.md)** — режимы совместимости в контексте PL/SQL-совместимых процедур.
- **[Обзор MariaDB](overview.md)** — роль `sql_mode=ORACLE` в стратегии развития.