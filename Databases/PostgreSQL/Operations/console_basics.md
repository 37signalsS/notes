# Работа с PostgreSQL через консоль (psql)

**Актуально для:** PostgreSQL 13–18; метакоманды с пометками версий (10+, 11+, 12+, 14+, 15+)

## Определения

**psql** — интерактивный терминальный клиент PostgreSQL (frontend), основной инструмент администратора и разработчика для выполнения SQL-запросов и управления сервером из командной строки.

**Ключевые понятия:**
- **Frontend/Backend протокол:** `psql` — frontend; общается с сервером (backend) через библиотеку `libpq`. SQL-команды выполняются на сервере, метакоманды — локально, самим клиентом.
- **Метакоманды (backslash commands):** начинаются с `\`; выполняются клиентом немедленно, `;` в конце не требуется.
- **psql-переменные:** именованные значения, устанавливаемые через `\set` и подставляемые в запросы как `:имя`; часть из них управляет поведением клиента (`ON_ERROR_STOP`, `VERBOSITY`, `AUTOCOMMIT` и др.).
- **Файл запуска `psqlrc`:** системный (`sysconfdir`/psqlrc) и пользовательский (`~/.psqlrc`, либо путь из переменной `PSQLRC`); выполняются при старте интерактивной сессии. В скриптах отключаются ключом `-X`.

## Предпосылки

1. **Установленный клиент:** пакет `postgresql-client` (Debian/Ubuntu) или `postgresql` (RHEL/CentOS; пакет содержит и сервер, и клиент).
   ```bash
   psql --version
   # → psql (PostgreSQL) 16.4
   ```
2. **Сетевая доступность:** порт (обычно 5432) открыт — проверить через `nc -zv <host> 5432`.
3. **Правило `pg_hba.conf`** на сервере для данной пары (пользователь, адрес, метод) — см. [PostgreSQL: Безопасность через pg_hba.conf и аудит](../../installation_security.md#postgresql-безопасность-через-pg_hbaconf-и-аудит).
4. **Редактор для `\e`/`\ef`/`\ev`:** psql ищет `PSQL_EDITOR`, затем `EDITOR`, затем `VISUAL` (первый установленный используется); по умолчанию — `vi`.

## Основные концепции

### Режимы работы

- **Интерактивный режим:** работа в консоли с немедленным ответом; основной режим отладки и администрирования.
- **Пакетный режим:** выполнение заранее подготовленных скриптов:
  ```bash
  psql -f script.sql -d mydb          # файл
  psql -c "SELECT now();" -d mydb     # одна команда без входа в оболочку
  cat script.sql | psql -d mydb       # конвейер (stdin)
  ```
  **Особенность `-c`:** строка передаётся серверу как один запрос и выполняется как одна транзакция, даже если внутри несколько SQL-команд. Для скриптов с логикой используйте `-f`.
- **Синтаксис команд:** SQL-команды заканчиваются точкой с запятой `;` и отправляются на сервер; метакоманды начинаются с `\` и выполняются клиентом.

### Подключение к серверу

Параметры подключения задаются четырьмя способами (приоритет: ключи CLI → URI/conninfo → переменные окружения → умолчания libpq):

1. **Ключи CLI:**
   ```bash
   psql -h <хост> -p <порт> -U <пользователь> -d <база_данных>
   ```
2. **Строка подключения (Connection URI):** поддерживает SSL, таймауты и имя приложения:
   ```bash
   psql "postgresql://user:password@host:port/dbname?sslmode=verify-full&connect_timeout=10&application_name=psql_admin"
   ```
   `application_name` позволяет идентифицировать сессию в `pg_stat_activity`. **Предупреждение:** пароль в URI виден в списке процессов и в истории shell — для постоянного доступа используйте `.pgpass`.
3. **Переключение изнутри psql:** `\c`/`\connect` — позиционный синтаксис (`\c db user host port`) или conninfo-строка; без аргументов — переподключение с прежними параметрами.
4. **Service-файлы:** именованные наборы параметров в `~/.pg_service.conf` (путь — `PGSERVICEFILE`, выбор секции — `PGSERVICE`):
   ```ini
   [prod]
   host=db.internal
   port=5432
   dbname=appdb
   user=appuser
   ```
   ```bash
   psql service=prod          # или PGSERVICE=prod psql
   ```

### Аутентификация

Способы входа без ручного ввода пароля (в порядке убывания безопасности):

1. **Peer-аутентификация** (метод в `pg_hba.conf` для локальных Unix-сокетов): роль БД должна совпадать с именем системного пользователя:
   ```bash
   sudo -u postgres psql
   ```
2. **Файл `.pgpass`** (`PGPASSFILE`, по умолчанию `~/.pgpass`, права `0600`): формат `hostname:port:database:username:password`.
3. **Переменная `PGPASSWORD`** (не рекомендуется): видна другим процессам того же пользователя через `/proc/<pid>/environ` или `ps e`, а при `export` попадает в историю shell.
4. **Ключи `-w`/`--no-password`** (никогда не запрашивать пароль) и **`-W`/`--password`** (запросить принудительно) — управляют интерактивным запросом пароля.
5. **`\password [username]`** — смена пароля: ввод скрыт, шифрование на клиенте, отправка как `ALTER ROLE`; пароль не попадает в историю команд и серверный лог (см. [Безопасность и шифрование](../Concepts/security_and_encryption.md)).

### Кодировка клиента

`\encoding [encoding]` показывает или устанавливает клиентскую кодировку; аналог — переменная окружения `PGCLIENTENCODING`.

## Практические сценарии

### Быстрый старт

```bash
# Подключение к локальному серверу от имени системного пользователя postgres
sudo -u postgres psql
# → psql (16.4 ...), введите "help" для справки.

# Проверка окружения после подключения
SELECT version();                       # → PostgreSQL 16.4 on x86_64-pc-linux-gnu, ...
SELECT current_user, is_superuser;
\conninfo                               # → Вы подключены к базе "postgres" ...
\echo :DBNAME                           # → postgres
```

### Скрипты и автоматизация (cron, CI/CD)

Ключевые флаги для надёжных скриптов:

```bash
psql -X -v ON_ERROR_STOP=1 -q -f migration.sql
```

- `-X`/`--no-psqlrc` — не читать `psqlrc` (детерминированность окружения).
- `-v ON_ERROR_STOP=1` — прервать скрипт при первой ошибке (иначе psql продолжает выполнение и возвращает код 0).
- `-1`/`--single-transaction` — обернуть `-c`/`-f` в `BEGIN`/`COMMIT` (атомарность миграции).
- `-q`/`--quiet` — подавить приветствия и информационный вывод.
- `-t`/`--tuples-only`, `-A`/`--no-align`, `-F`, `--csv` — машиночитаемый вывод для pipeline.

Подстановка переменных в запросы:

```sql
\set table_name 'orders'
SELECT count(*) FROM :table_name;               -- подстановка как есть
SELECT * FROM :"table_name" WHERE id = :'id';   -- :"..." — идентификатор, :'...' — литерал
```

Условная логика и ввод (psql 10+):

```sql
\set dry_run on
\if :dry_run
  \echo 'Режим проверки: DDL не применяется'
\else
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_user ON orders(user_id);
\endif
\prompt 'Введите схему: ' schema_name
\echo 'Работаем со схемой :schema_name'
```

`\gset` сохраняет результат запроса в переменные (по именам столбцов):

```sql
SELECT count(*) AS n, pg_size_pretty(pg_database_size(current_database())) AS sz
FROM pg_stat_database WHERE datname = current_database() \gset
\echo 'Строк: :n, размер: :sz'
```

Вывод сообщений: `\echo` — в stdout, `\warn` — в stderr, `\qecho` — в поток вывода запросов (полезно вместе с `\o`).

### Мониторинг в реальном времени

`\watch` повторяет текущий буфер запроса до прерывания (Ctrl+C), ошибки запроса, достижения лимита итераций или исчезновения минимума строк:

```sql
SELECT pid, state, now() - query_start AS dur, left(query, 60)
FROM pg_stat_activity WHERE state = 'active' AND pid <> pg_backend_pid()
\watch i=5 c=12
-- → каждые 5 секунд, 12 итераций; заголовок содержит \pset title и время замера
```

- Интервал по умолчанию — 2 секунды (переопределяется переменной `WATCH_INTERVAL`); полный синтаксис: `\watch [i[nterval]=seconds] [c[ount]=times] [m[in_rows]=rows]`.
- `\timing` — время каждого запроса (в мс; для интервалов > 1 с — в формате минуты:секунды, при необходимости добавляются часы и дни).
- `\x auto` (psql 11+) — автоматический expanded-режим для широких строк.
- `\pset title 'text'` — заголовок таблицы (отображается и в заголовке `\watch`).

### Импорт и экспорт данных

`\copy` — клиентская копия: данные проходят через клиент, файлы читаются/пишутся с правами локального пользователя, SQL-суперпользователь не требуется (в отличие от серверной `COPY`):

```sql
\copy (SELECT * FROM orders WHERE created_at > now() - interval '1 day') TO 'orders.csv' WITH (FORMAT csv, HEADER true)
\copy orders FROM 'orders.csv' WITH (FORMAT csv, HEADER true)
\copy orders FROM program 'zcat orders.csv.gz' WITH (FORMAT csv)
\copy orders FROM pstdin WITH (FORMAT csv)      -- параллельная загрузка (PG 14+)
\copy orders TO pstdout WITH (FORMAT csv)
```

Потоки `stdin`/`stdout` читают/пишут через тот же источник, что и команда `\copy`; `program 'command'` выполняет команду локально через shell; `where condition` фильтрует строки при загрузке. Пути к файлам отсчитываются от текущего каталога клиента (не сервера).

### Настройка ~/.psqlrc

Файл `~/.psqlrc` автоматизирует рутину и улучшает визуализацию интерактивной сессии:

```sql
-- 1. Визуальное оформление
\set PROMPT1 '%n@%m:%> %p %/ %R%# '   -- приглашение: user@host:port pid/db %R%#
\pset null '[NULL]'                    -- явное отображение пустых значений
\pset linestyle unicode                -- рамки таблиц
\pset border 2                         -- двойные рамки
\timing on                             -- замер времени по умолчанию
\x auto                                -- expanded для широких строк (psql 11+)

-- 2. Переменные-скрипты: вызов через :locks / :active
\set locks 'SELECT pid, relname, locktype, mode, granted FROM pg_locks l JOIN pg_class c ON l.relation = c.oid WHERE NOT granted'
\set active 'SELECT pid, query, state, now() - query_start AS duration FROM pg_stat_activity WHERE state != \'idle\''

-- 3. Диагностика по умолчанию (при инциденте)
-- \set VERBOSITY verbose              -- подробный вывод ошибок; см. stored_objects_debugging.md
```

`\set AUTOCOMMIT off` отключает автокоммит: каждая команда открывает транзакцию, которая завершается только явным `COMMIT`/`ROLLBACK` (или при выходе — откатом). Это не «режим только для чтения»: изменения в такой транзакции фиксируются при `COMMIT`.

### Переменные окружения

| Переменная | Назначение |
| :--- | :--- |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE` | Хост, порт, пользователь, база по умолчанию |
| `PGPASSWORD` | Пароль (не рекомендуется — см. раздел «Аутентификация») |
| `PGAPPNAME` | Имя приложения (`application_name`), видно в `pg_stat_activity` |
| `PGSSLMODE` | Режим TLS: `disable`/`allow`/`prefer`/`require`/`verify-ca`/`verify-full` |
| `PGCONNECT_TIMEOUT` | Таймаут подключения в секундах (по умолчанию — системный таймаут ОС) |
| `PGCLIENTENCODING` | Клиентская кодировка (аналог `\encoding`) |
| `PGOPTIONS` | Дополнительные опции серверу, например `PGOPTIONS="-c lock_timeout=5s"` |
| `PGPASSFILE` | Путь к файлу паролей (по умолчанию `~/.pgpass`) |
| `PGSERVICE`, `PGSERVICEFILE` | Выбор секции и путь service-файла (по умолчанию `~/.pg_service.conf`) |
| `PSQLRC` | Альтернативный путь пользовательского `psqlrc` (раскрытие `~` выполняется) |
| `PSQL_PAGER`, `PAGER` | Программа постраничного вывода (`\pset pager`) |
| `PSQL_WATCH_PAGER` | Программа постраничного вывода для `\watch` (Unix) |
| `PSQL_EDITOR`, `EDITOR`, `VISUAL` | Редактор для `\e`/`\ef`/`\ev` — проверяются в указанном порядке |
| `SHELL` | Интерпретатор для `\!` |
| `TMPDIR` | Каталог временных файлов (буфер `\e`) |

### psql-переменные

| Переменная | Назначение |
| :--- | :--- |
| `ON_ERROR_STOP` | `on` — прервать выполнение при ошибке (код возврата 3) |
| `ON_ERROR_ROLLBACK` | `on`/`interactive` — при ошибке в транзакции откатить до savepoint и продолжить |
| `AUTOCOMMIT` | `on` (по умолчанию) — автокоммит; `off` — неявные транзакции |
| `ECHO`, `ECHO_HIDDEN` | `all`/`queries`/`errors` — эхо команд; `ECHO_HIDDEN` — эхо запросов, генерируемых `\d` и др. |
| `VERBOSITY`, `SHOW_CONTEXT` | Подробность ошибок (`terse`/`default`/`verbose`) и контекст (`never`/`auto`/`always`) — см. [Отладка хранимых объектов](../Concepts/stored_objects_debugging.md) |
| `FETCH_COUNT` | Получать результат пакетами по N строк вместо всего набора (экономия памяти на больших выборках) |
| `HISTCONTROL`, `HISTSIZE` | История: `ignorespace`/`ignoredups`, размер |
| `COMP_KEYWORD_CASE` | Регистр SQL-ключевых слов при дополнении (`lower`/`upper`/`preserve-*`) |
| `WATCH_INTERVAL` | Интервал `\watch` по умолчанию (секунды) |
| `SINGLESTEP`, `SINGLELINE` | Пошаговый режим (`-s`) и однострочный режим |
| `QUIET` | Тихий режим (`-q`) |
| `ENCODING`, `DBNAME`, `HOST`, `PORT`, `USER`, `SQLSTATE` | Текущие значения сессии; `SQLSTATE` — код последней ошибки |

## Операции и команды

### Ключи командной строки

| Ключ | Длинная форма | Назначение |
| :--- | :--- | :--- |
| `-h` | `--host` | Хост сервера |
| `-p` | `--port` | Порт сервера |
| `-U` | `--username` | Пользователь |
| `-d` | `--dbname` | База данных |
| `-c` | `--command` | Выполнить команду (один запрос = одна транзакция) |
| `-f` | `--file` | Выполнить файл со скриптом |
| `-l` | `--list` | Список баз и выход (аналог `\list`) |
| `-v` | `--set` | Установить psql-переменную (`-v ON_ERROR_STOP=1`) |
| `-X` | `--no-psqlrc` | Не читать `psqlrc` (системный и пользовательский) |
| `-x` | `--expanded` | Expanded-формат (аналог `\x`) |
| `-1` | `--single-transaction` | Обернуть `-c`/`-f` в одну транзакцию |
| `-q` | `--quiet` | Без приветствий и информационного вывода |
| `-t` | `--tuples-only` | Без заголовков столбцов и счётчика строк (аналог `\t`) |
| `-A` | `--no-align` | Unaligned-вывод (аналог `\pset format unaligned`) |
| `-F` | `--field-separator` | Разделитель полей для unaligned (аналог `\pset fieldsep`) |
| `-z` | `--field-separator-zero` | Разделитель полей — нулевой байт |
| `-0` | `--record-separator-zero` | Разделитель записей — нулевой байт |
| `-P` | `--pset` | Опция `\pset` (`-P format=latex`) |
| `-o` | `--output` | Вывод в файл или конвейер (аналог `\o`) |
| `-e` | `--echo-queries` | Эхо всех SQL-команд, отправленных серверу |
| `-E` | `--echo-hidden` | Эхо запросов, генерируемых `\d` и другими метакомандами (изучение внутренней работы) |
| `-b` | `--echo-errors` | Печать неудавшихся SQL-команд в stderr |
| `-s` | `--single-step` | Пошаговый режим: подтверждение перед каждой командой |
| `-n` | `--no-readline` | Без Readline и истории команд |
| `-w` | `--no-password` | Никогда не запрашивать пароль |
| `-W` | `--password` | Запросить пароль принудительно |
| `--csv` | — | CSV-вывод (psql 12+; аналог `\pset format csv`) |
| `-V` | `--version` | Версия psql |
| `-?` | `--help` | Справка по ключам |

### Коды возврата

| Код | Смысл |
| :--- | :--- |
| `0` | Нормальное завершение |
| `1` | Фатальная ошибка самого psql (например, нехватка памяти, файл не найден) |
| `2` | Соединение с сервером потеряно, сессия не интерактивна |
| `3` | Ошибка в скрипте при установленном `ON_ERROR_STOP` |

### Метакоманды: соединение и навигация

| Команда | Назначение |
| :--- | :--- |
| `\c`/`\connect [db [user [host [port]]] \| conninfo]` | Новое соединение; без аргументов — переподключение с прежними параметрами; `-reuse-previous=on\|off` управляет повторным использованием параметров |
| `\conninfo` | Параметры текущего соединения, включая SSL; поле Client User показывает пользователя на клиенте — важно при `SET ROLE` |
| `\encoding [enc]` | Показать/установить клиентскую кодировку |
| `\l`/`\list [pattern]`, `\l+` | Базы данных: имена, владельцы, кодировки, права; `+` — размеры |
| `\password [user]` | Смена пароля без открытого текста в истории и логах |
| `\q`/`\quit` | Выход из psql |

### Метакоманды: объекты (\d*-семейство)

| Команда | Назначение |
| :--- | :--- |
| `\d [pattern]`, `\d+` | Структура отношения (таблица, представление, матпредставление, индекс, последовательность, foreign table) или composite-типа: столбцы, типы, табличное пространство, атрибуты (`NOT NULL`, defaults); связанные индексы, ограничения, правила, триггеры. Без аргумента — аналог `\dtvmsE` (видимые объекты в `search_path`) |
| `\dt`, `\di`, `\ds`, `\dv`, `\dm`, `\dE` | Таблицы, индексы, последовательности, представления, матпредставления, foreign-таблицы |
| `\dn [pattern]` | Схемы (namespaces) |
| `\db [pattern]`, `\db+` | Табличные пространства; `+` — размеры |
| `\du [pattern]`, `\dg [pattern]` | Роли (команды эквивалентны; модификатор `S` — системные роли) |
| `\dp [pattern]`, `\z [pattern]` | Таблицы, представления и последовательности с правами доступа |
| `\df[anptwSx+] [pattern [args]]` | Функции; модификаторы `a`/`n`/`p`/`t`/`w` — агрегаты/обычные/procedures/триггеры/оконные |
| `\dA [pattern]` | Методы доступа (PG 10+) |
| `\dC [pattern]` | Приведения типов (casts) |
| `\dc [pattern]` | Преобразования кодировок |
| `\dD [pattern]` | Домены |
| `\dF`, `\dFd`, `\dFp`, `\dFt` | Конфигурации, словари, парсеры, шаблоны текстового поиска — см. [Полнотекстовый поиск](../Concepts/full_text_search.md) |
| `\dL [pattern]` | Процедурные языки |
| `\do [pattern]` | Операторы |
| `\da [pattern]` | Агрегатные функции |
| `\dd [pattern]` | Описания (COMMENT) объектов — только объекты с описанием |
| `\dT [pattern]` | Типы данных |
| `\dx [pattern]`, `\dx+` | Установленные расширения; `+` — описания |
| `\dRp [pattern]`, `\dRs [pattern]` | Публикации и подписки логической репликации (PG 10+); `+` — таблицы/схемы в публикации |
| `\dy [pattern]` | Триггеры событий (event triggers, PG 9.3+) |
| `\dconfig [pattern]` | Параметры конфигурации сервера (PG 15+); без pattern — только отличные от дефолтных, `\dconfig *` — все |
| `\dew [pattern]` | Обёртки сторонних данных (foreign-data wrappers, PG 15+) |
| `\drds [role [db]]` | Настройки, специфичные для роли и/или базы (`ALTER ROLE ... IN DATABASE`) |

Модификаторы: `S` — включая системные объекты (по умолчанию показываются только пользовательские), `x` — expanded-вывод, `+` — дополнительные сведения (размеры, описания, владельцы — состав зависит от команды).

### Метакоманды: код и исходники

| Команда | Назначение |
| :--- | :--- |
| `\e`/`\edit [file] [line]` | Редактирование файла (содержимое попадает в буфер) или текущего буфера во внешнем редакторе |
| `\ef [function [line]]` | Редактирование определения функции как `CREATE OR REPLACE`; выход без сохранения — изменения отбрасываются; сохранение с `;` в конце — команда выполняется сразу |
| `\ev [view [line]]` | То же для представления |
| `\sf [function]` | Только исходный код функции (Show Function) |
| `\sv [view]` | Только исходный код представления (Show View) |
| `\i`/`\include file` | Выполнить SQL-файл; `\i -` — читать stdin до EOF или `\q` |
| `\ir`/`\include_relative file` | Как `\i`, но относительные пути отсчитываются от файла, содержащего `\ir`, а не от текущего каталога |

### Метакоманды: вывод и формат

| Команда | Назначение |
| :--- | :--- |
| `\x [on\|off\|auto]` | Expanded-режим (psql 11+: `auto` — по ширине строки) |
| `\pset [option [value]]` | Опции вывода: `format`, `border`, `linestyle`, `null`, `fieldsep`, `recordsep`, `tuples_only`, `expanded`, `pager`, `pager_min_lines`, `title`, `footer`, `columns`, `tableattr`, `numeric_locale`, `csv_fieldsep`; без аргументов — текущий статус всех опций |
| `\pset format csv` | CSV-формат (аналог `--csv`, psql 12+); другие значения: `aligned` (по умолчанию), `unaligned`, `html`, `latex`, `troff-ms`, `wrapped` |
| `\pset pager off` | Отключить постраничный вывод (программа из `PSQL_PAGER`/`PAGER`) |
| `\timing [on\|off]` | Замер времени выполнения каждого запроса |
| `\o`/`\out [file \| \|command]` | Перенаправить вывод запросов в файл или конвейер; без аргумента — сброс в stdout |
| `\g [(option=value ...)] [file \| \|command]` | Выполнить буфер с разовыми опциями формата и/или выводом в файл/конвейер |
| `\gx` | Как `\g`, но с expanded-выводом для данного запроса |
| `\watch [i=сек] [c=раз] [m=строк]` | Циклическое выполнение буфера (по умолчанию каждые 2 с) |

### Метакоманды: скрипты и переменные

| Команда | Назначение |
| :--- | :--- |
| `\set [name [value ...]]` | Установить psql-переменную (несколько значений склеиваются); без аргументов — список всех переменных |
| `\unset name` | Удалить переменную |
| `\prompt [text] name` | Запросить значение у пользователя в переменную |
| `\gset [prefix]` | Результат запроса → переменные (по именам столбцов) |
| `\gexec` | Выполнить каждый столбец каждой строки результата как SQL-команду |
| `\if`/`\elif`/`\else`/`\endif` | Вложенные условные блоки (psql 10+) |
| `\echo`, `\qecho`, `\warn` | Вывод в stdout / поток вывода запросов / stderr |
| `\setenv name [value]` | Установить или снять переменную окружения (psql 11+) |
| `\getenv psql_var env_var` | Переменная окружения → psql-переменная |
| `\s [file]` | История команд psql (в файл или stdout) |
| `\r`/`\reset` | Очистить буфер запроса |
| `\errverbose` | Повторить последнюю ошибку сервера с максимальной подробностью (как `VERBOSITY=verbose` + `SHOW_CONTEXT=always`) |
| `\h`/`\help [command]` | Справка по синтаксису SQL-команды; без аргумента — список всех команд |
| `\? [topic]` | Справка psql: `commands`, `options`, `variables` |

### Метакоманды: системное взаимодействие

| Команда | Назначение |
| :--- | :--- |
| `\! command` | Выполнить команду shell на клиенте (используется `SHELL`); права — локального пользователя |
| `\copy ...` | Клиентская COPY — см. раздел «Импорт и экспорт данных» |
| `\lo_import`, `\lo_export`, `\lo_list`, `\lo_unlink` | Large objects через клиент — см. [Large Objects](../Concepts/large_objects.md) |

### Шаблоны поиска объектов (Patterns)

- Без аргумента `\d`-команды показывают объекты, видимые в текущем `search_path` (эквивалент `*`); шаблон `*.*` — все объекты базы независимо от видимости.
- `*` — любая последовательность символов (включая пустую), `?` — ровно один символ (как glob в shell). Внутри двойных кавычек `*` и `?` — литеральные.
- `.` отделяет шаблон схемы от шаблона объекта (`\dt foo*.*bar*` — таблицы, содержащие `bar`, в схемах на `foo*`); два `.` — база.схема.объект (база должна совпадать с текущей, иначе ошибка).
- Имена приводятся к нижнему регистру (`\dt FOO` → таблица `foo`); двойные кавычки отключают приведение (`\dt "FOO"`), допустимо частичное кавычение (`\dt FOO"FOO"BAR` → `fooFOObar`).

## Валидация

После подключения рекомендуется выполнить базовую проверку среды:

1. **Версии клиента и сервера:**
   ```bash
   psql --version
   # → psql (PostgreSQL) 16.4
   ```
   ```sql
   SELECT version();
   -- → PostgreSQL 16.4 on x86_64-pc-linux-gnu, compiled by gcc ..., 64-bit
   ```
2. **Права и текущая роль:**
   ```sql
   SELECT current_user, is_superuser;
   -- → current_user | is_superuser
   -- → app_user     | f
   ```
3. **Параметры соединения:** `\conninfo` — хост, порт, параметры шифрования (SSL/TLS). Убедитесь, что используется ожидаемый уровень безопасности.
4. **Кодировка:** `\encoding` → `UTF8` (или требуемая).
5. **Скриптовая проверка:** `psql -X -v ON_ERROR_STOP=1 -c "SELECT 1"` — код возврата `0` подтверждает доступность и корректность флагов.

## Типовые ошибки и Troubleshooting

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `connection to server at "host" (ip), port 5432 failed: Connection refused` | База не запущена или порт закрыт | `systemctl status postgresql` и `ss -ntlp \| grep 5432` |
| `... failed: No such file or directory` (при локальном подключении без `-h`) | Сервер не слушает Unix-сокет или неверен `PGHOST`/`-h` | Проверить `unix_socket_directories` (показывает `\conninfo`), запустить сервер |
| `FATAL: password authentication failed for user "..."` | Неверный пароль или пользователь | Проверить `.pgpass` (формат, права `0600`), `PGPASSWORD`, соответствие в `pg_hba.conf` |
| `FATAL: no pg_hba.conf entry for host "...", user "...", database "...", SSL on/off` | Нет подходящего правила | Настроить [pg_hba.conf](../../installation_security.md#postgresql-безопасность-через-pg_hbaconf-и-аудит); проверить синтаксис правил: `SELECT line_number, type, database, user_name, error FROM pg_hba_file_rules WHERE error IS NOT NULL;` |
| `FATAL: Peer authentication failed for user "..."` | Метод `peer` требует совпадения системного пользователя и роли БД | `sudo -u postgres psql` или смена метода в `pg_hba.conf` на `scram-sha-256` |
| `connection to server at "..." timeout` | Сеть или файрвол | `nc -zv host port`, `connect_timeout` в URI |
| `server closed the connection unexpectedly` | Сервер упал, файрвол дропает idle-соединения | Логи сервера; `TCPKeepalive`/`keepalives_idle` в conninfo |
| `FATAL: remaining connection slots are reserved...` | Исчерпан лимит `max_connections` | `pg_terminate_backend(<pid>)`, PgBouncer — см. [Управление соединениями](./connection_management.md) и [PgBouncer](./pgbouncer_setup.md) |
| `fe_sendauth: no password supplied` | Требуется пароль, а источника нет (нет `.pgpass`/`PGPASSWORD`, нет tty) | Создать `.pgpass` или использовать `-W` |
| `could not translate host name "..." to address` | DNS-имя не резолвится | Проверить имя или использовать IP |
| `command not found: psql` | Клиент не установлен или не в `PATH` | Установить `postgresql-client`; при `sudo` — `sudo -u postgres psql` (secure_path) |
| `ERROR: permission denied for table ...` | Нет прав на объект | `\dp`/`\z` для проверки прав, `GRANT` — см. [Роли и права](./role_management.md) |
| `ERROR: current transaction is aborted, commands ignored until end of transaction block` | Ошибка внутри транзакции | `ROLLBACK` (или `\r` для сброса буфера); для скриптов — `ON_ERROR_ROLLBACK` |
| `ERROR: canceling statement due to statement timeout` | Превышен `statement_timeout` | `SET statement_timeout` — см. [Оптимизация производительности](./performance_tuning.md) |
| `ERROR: relation "..." does not exist` | Неправильная схема или опечатка | `SHOW search_path;`, `\dt`, шаблоны (`\dt public.*`), кавычки для регистра |
| `psql: error: unrecognized option` | Опечатка в ключе | `psql --help` |
| `could not open file "...": No such file or directory` при `\i`/`\copy` | Путь относительно текущего каталога клиента | Использовать `\ir` для путей относительно файла скрипта |
| `SSL error: certificate verify failed` | Проблема TLS/CA | `sslmode` и CA — см. [Безопасность и шифрование](../Concepts/security_and_encryption.md) |

## Лучшие практики

1. **Скрипты всегда с `-X -v ON_ERROR_STOP=1`** — детерминированность и корректный код возврата в cron/CI.
2. **Миграции — с `-1`/`--single-transaction`** — атомарность; для `CREATE INDEX CONCURRENTLY` отдельный шаг (внутри транзакции не работает).
3. **`application_name`** в URI или `PGAPPNAME` — сессии сразу идентифицируются в `pg_stat_activity` и в логах.
4. **`.pgpass` с правами `0600`** вместо `PGPASSWORD`; `\password` вместо передачи пароля в SQL.
5. **`\timing` + `\watch`** для быстрой диагностики; `\x auto` для широких строк; `\pset title` для подписи в `\watch`.
6. **`\gset`/`\if`/`\gexec`** для генерации и применения DDL (например, создание индексов по всем столбцам таблицы через `\gexec`).
7. **`--csv`/`-A`/`-F`** для машиночитаемого вывода в pipeline; `FETCH_COUNT` для больших выгрузок (экономия памяти).
8. **`\set VERBOSITY verbose`** (или `\errverbose` после ошибки) при инцидентах — полный контекст ошибки; см. [Отладка хранимых объектов](../Concepts/stored_objects_debugging.md).
9. **`\encoding UTF8`** при не-UTF8 локали клиента — избежать ошибок преобразования символов.
10. **`\!` выполняется на клиенте** с правами локального пользователя — не путать с серверными командами; `\copy` аналогично клиентская.

## Очистка и откат

- `\o` без аргумента — вернуть вывод в stdout; удалить файлы, созданные `\o`, `\g file`, `\copy ... TO`.
- `\unset name` — удалить переменную; `\set` без аргументов — список текущих переменных.
- Сброс формата: `\pset format aligned`, `\x off`, `\timing off`, `\pset pager on`, `\pset border 2` (по необходимости).
- `\c` — вернуться к нужной базе; `\q` — выход из сессии.
- `\watch` — прервать комбинацией Ctrl+C.
- `\ef`/`\ev` — выйти из редактора без сохранения (изменения отбрасываются) или восстановить определение из системы контроля версий; при сохранении с `;` команда выполняется сразу.
- `\!` — побочные эффекты (файлы, службы) откатываются вручную.
- `\password` — необратима; повторный вызов для новой смены.
- Изменения `~/.psqlrc` — отредактировать файл; для тестирования альтернативного файла — переменная `PSQLRC`.

## Дополнительная информация

- [Обзор PostgreSQL](../overview.md) — архитектура и основные возможности.
- [Управление ролями и правами](./role_management.md) — создание ролей и `GRANT`/`REVOKE`.
- [Управление соединениями](./connection_management.md) — `pg_stat_activity`, блокировки, пулинг.
- [Оптимизация производительности](./performance_tuning.md) — глубокий анализ запросов.
- [Наблюдаемость PostgreSQL](./observability.md) — метрики, wait events, трассировка.
- [Инструменты управления](./management_tools.md) — GUI и CLI-альтернативы.
- [Безопасность СУБД](../../installation_security.md) — `pg_hba.conf` и шифрование.
- Официальная документация: [psql](https://www.postgresql.org/docs/current/app-psql.html), [libpq: переменные окружения](https://www.postgresql.org/docs/current/libpq-envars.html).
