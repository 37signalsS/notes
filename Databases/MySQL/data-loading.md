# Массовая загрузка данных в MySQL: LOAD DATA и mysqlimport

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation

Практический разбор загрузки данных из текстовых файлов: как выбрать между `LOAD DATA`
и `mysqlimport`, как правильно описать разделители и экранирование, почему `LOCAL` меняет
семантику ошибок, и что делать, если загрузка идёт в реплицируемую базу.

Смежные темы, которые не дублируются здесь: стратегии массовых изменений данных и
подмена таблицы — [Безопасное массовое изменение данных](../Concepts/atomic_operations.md);
DDL после загрузки — [Online Schema Change](./Operations/online-schema-change.md);
разбор плана и TempTable — [EXPLAIN и оптимизация](./Operations/explain_and_optimization.md).

## Определения

| Термин | Значение |
| :--- | :--- |
| Staging table | Временная таблица-приёмник, в которую грузят до проверки |
| `LOCAL` | Модификатор `LOAD DATA`, при котором файл читает **клиент**, а не сервер |
| Restrictive interpretation | Строгая трактовка данных: ошибка прерывает загрузку |
| Nonrestrictive interpretation | Мягкая трактовка: ошибка превращается в предупреждение |
| Escape character | Символ, отмечающий специальные последовательности в поле |
| `secure_file_priv` | Ограничение каталога для операций с файлами на стороне сервера |

## Базовые концепции

### Три источника данных и что означает `LOCAL`

`LOAD DATA` читает строки из текстового файла с высокой скоростью. Файл может лежать на
хосте сервера или на хосте клиента — это и определяет модификатор `LOCAL`.

| | Без `LOCAL` | С `LOCAL` |
| :--- | :--- | :--- |
| Где лежит файл | На хосте **сервера** | На хосте **клиента** |
| Кто читает | Сервер напрямую | Клиент, затем передаёт по соединению |
| Привилегия `FILE` | **Требуется** | Не требуется |
| Ограничение `secure_file_priv` | Действует | Не действует |
| Влияет на обработку дублей | Только `REPLACE`/`IGNORE` | **`LOCAL` само по себе действует как `IGNORE`** |
| Скорость | Выше (прямое чтение) | Ниже (передача по сети) |
| Копия файла на сервере | Нет | **Есть** — во временном каталоге |

Последняя строка таблицы — главный практический подвох `LOCAL`: сервер создаёт копию
файла в каталоге временных файлов. **Нехватка места во временном каталоге приводит к
падению `LOAD DATA`**, причём ошибка выглядит как проблема диска, а не как проблема
загрузки.

Как сервер находит файл без `LOCAL`:

- Абсолютный путь — используется как есть.
- Относительный путь с ведущими компонентами — относительно `datadir`.
- Имя без ведущих компонентов — относительно каталога **базы данных по умолчанию**
  (текущей базы), а не той, куда грузится.

Поэтому `LOAD DATA INFILE 'data.txt' INTO TABLE db2.my_table` при текущей базе `db1`
прочитает `db1/data.txt`.

### Строгая и мягкая трактовка данных

Итог зависит от двух факторов: `sql_mode` и наличие `IGNORE`/`LOCAL`.

| | Строгая трактовка | Мягкая трактовка |
| :--- | :--- | :--- |
| Когда | `sql_mode` строгий **и** нет `IGNORE`/`LOCAL` | `sql_mode` нестрогий **или** задан `IGNORE`/`LOCAL` |
| Слишком много полей | Ошибка | Лишние поля игнорируются, счётчик предупреждений растёт |
| Слишком мало полей | Ошибка | Отсутствующие колонки получают значения по умолчанию |
| `NULL` (`\N`) в `NOT NULL` | Ошибка | Подставляется неявное значение по умолчанию |
| Значение вне диапазона типа | Ошибка | Обрезается до ближайшей границы |
| Невалидное значение (`'x'` в числовую) | Ошибка | Преобразуется в `0` |
| Дубликат по уникальному ключу | Ошибка, **оставшаяся часть файла не читается** | Пропускается (при `IGNORE`/`LOCAL`) |

> **Осторожность:** модификатор `LOCAL` **перекрывает строгий `sql_mode`**, если не
> задан `REPLACE`. Загрузка «пройдёт успешно» и при этом молча испортит часть данных —
> например, превратит `'x'` в `0`. Всегда сверять `Records / Deleted / Skipped / Warnings`
> после загрузки.

Обратите внимание на разницу между **пустым** и **отсутствующим** полем: пустое значение
для строки даёт `''`, для числа — `0`, для даты — «нулевую» дату.

### Дубликаты: `REPLACE`, `IGNORE` и поведение по умолчанию

| Модификатор | Что происходит с конфликтующей строкой |
| :--- | :--- |
| `REPLACE` | Новая строка **заменяет** существующую (требует привилегии `INSERT` и `DELETE`) |
| `IGNORE` | Конфликтующая строка **отбрасывается** |
| `LOCAL` без `REPLACE` | То же, что `IGNORE` |
| Ничего не указано | Ошибка, и **остаток файла не обрабатывается** |

### `SELECT ... INTO OUTFILE` — зеркало `LOAD DATA`

`SELECT ... INTO OUTFILE` записывает результат запроса в файл на **сервере** и является
прямым обратным операцием `LOAD DATA`: те же клаузы `FIELDS`/`LINES`, те же ограничения
на `secure_file_priv`, та же привилегия `FILE`. Это не инструмент резервного копирования —
он не делает DDL и не формирует `.sql`-дамп; для последнего есть
[MySQL Shell Dump & Load](../backup_and_recovery/mysql_shell_dump.md).

| Свойство | Значение |
| :--- | :--- |
| Куда пишется | На хосте сервера, в `secure_file_priv` |
| Привилегия | `FILE` |
| Ограничение пути | `secure_file_priv` должен быть задан; иначе операция отклонена |
| Файл | Не может существовать — защита от перезаписи системных файлов |
| Владелец | ОС-пользователь, под которым работает `mysqld` |
| `umask` | С 8.0.17 — `0640`; до этого `0666` (файл читаем всем на хосте) |

```sql
-- Выгрузка с теми же разделителями, что и последующий LOAD DATA
TABLE shop.orders ORDER BY id LIMIT 1000
  INTO OUTFILE '/var/lib/mysql-files/orders_export.csv'
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\'
  LINES TERMINATED BY '\n';
-- → Query OK, 1000 rows affected (0.03 sec)
```

Ключевые нюансы:

- **`CHARACTER SET` в `INTO OUTFILE` задаёт кодировку вывода**, а не ввода. Без неё
  значения пишутся в `binary` — без преобразования. Если в выборке колонки с разными
  кодировками, файл будет смешанным и `LOAD DATA` его прочитает неверно.
- **`FIELDS ESCAPED BY` управляет экранированием на выходе.** При пустом `ESCAPED BY ''`
  ни один символ не экранируется и `NULL` пишется словом `NULL`, а не как `\N` — это
  делает файл непригодным для обратной загрузки через `LOAD DATA` с дефолтным escape.
- **`INTO DUMPFILE` — для одного поля, без форматирования.** Подходит для выгрузки
  `BLOB`/`TEXT` в исходном виде. Требует `LIMIT 1`, если в выборке больше одной строки.
- **Кодировка имени файла** — `character_set_filesystem`, как и у `LOAD DATA`.
- **Выгрузка на другой хост** требует либо сетевого монтирования `secure_file_priv`
  на клиенте, либо переноса файла по SCP/rsync. Прямой `SELECT ... INTO OUTFILE` на
  удалённом хосте не копирует файл клиенту.

### Кодировки

- Имя файла интерпретируется в кодировке `character_set_filesystem`.
- Содержимое файла — в кодировке `character_set_database`. Если она отличается, задавайте
  `CHARACTER SET` явно.
- `SET NAMES` и `character_set_client` на интерпретацию содержимого **не влияют**.
- Все поля файла считаются имеющими одну кодировку независимо от типов колонок.
- `CHARACTER SET binary` означает «без преобразования».
- **Загрузить файлы в `ucs2`, `utf16`, `utf16le`, `utf32` невозможно.**
- `SELECT ... INTO OUTFILE` должен использовать ту же кодировку, что и последующий
  `LOAD DATA` (тот же `--default-character-set`), иначе файл прочитается неверно.

## Практические сценарии

### Сценарий 1. CSV с заголовком — базовый случай

```csv
id,customer,amount,created_at
1,Иванов,1500.50,2026-01-15 10:23:00
2,Петров,2300.00,2026-01-15 10:24:11
```

```sql
SHOW VARIABLES LIKE 'secure_file_priv';
-- → secure_file_priv = /var/lib/mysql-files

-- Файл обязан лежать в этом каталоге, иначе операция будет отклонена
TRUNCATE TABLE shop.stg_orders;
-- → Query OK, 0 rows affected

LOAD DATA INFILE '/var/lib/mysql-files/orders.csv'
INTO TABLE shop.stg_orders
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(id, customer, amount, created_at);
-- → Records: 2  Deleted: 0  Skipped: 0  Warnings: 0
```

Три обязательных момента:

1. `IGNORE 1 LINES` — пропустить строку заголовка.
2. `OPTIONALLY ENCLOSED BY '"'` — без `OPTIONALLY` кавычки будут требоваться всегда;
   значения без кавычек станут ошибкой. Пустые кавычки `ENCLOSED BY ''` означают, что
   кавычек в файле нет.
3. `secure_file_priv` — путь к файлу обязан быть внутри разрешённого каталога.

Проверка результата:

```sql
SHOW WARNINGS;
-- → (пусто)

SELECT COUNT(*) AS loaded FROM shop.stg_orders;
-- → loaded = 2

SELECT * FROM shop.stg_orders ORDER BY id;
-- → id | customer | amount  | created_at
-- →  1 | Иванов   | 1500.50 | 2026-01-15 10:23:00
```

### Сценарий 2. Разделители по умолчанию и как их увидеть

Если `FIELDS`/`LINES` не заданы, действуют значения, эквивалентные:

```sql
FIELDS TERMINATED BY '\t' ENCLOSED BY '' ESCAPED BY '\\'
LINES  TERMINATED BY '\n' STARTING BY ''
```

То есть сервер ищет **табуляцию** между полями, **не ожидает кавычек** и понимает
последовательности с обратным слэшем.

| Задача | Клауза |
| :--- | :--- |
| CSV | `FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'` |
| Значения разделены `;` | `FIELDS TERMINATED BY ';' OPTIONALLY ENCLOSED BY '"'` |
| Windows CRLF | `LINES TERMINATED BY '\r\n'` |
| Только `\r` (WordPad) | `LINES TERMINATED BY '\r'` |
| Каждая строка — одна запись из N символов | `FIELDS TERMINATED BY '' ENCLOSED BY ''` |
| Префикс в начале каждой строки | `LINES STARTING BY 'xxx'` |

Ограничения на разделители, которые ломают разбор:

- `FIELDS TERMINATED BY ''` и `ENCLOSED BY ''` вместе задают формат фиксированной
  ширины. Он **не поддерживается для `BLOB`/`TEXT`** и **не работает с многобайтовыми
  кодировками**.
- Разделитель нельзя делать равным другому разделителю или его префиксу:
  `FIELDS TERMINATED BY '"' ENCLOSED BY '"'` приведёт к неверному разбору.
- `ESCAPED BY ''` отключает интерпретацию escape-последовательностей; тогда `NULL`
  пишется словом `NULL`, а не как `\N`.

Escape-последовательности, которые понимает `LOAD DATA` при непустом `ESCAPED BY`:

| Последовательность | Значение |
| :--- | :--- |
| `\0` | ASCII NUL (`X'00'`) |
| `\b` | Забой |
| `\n` | Перевод строки |
| `\r` | Возврат каретки |
| `\t` | Табуляция |
| `\Z` | ASCII 26 (Ctrl+Z) |
| `\N` | `NULL` |

Двойная кавычка внутри значения экранируется удвоением: `"The ""BIG"" boss"`
читается как `The "BIG" boss`.

### Сценарий 3. Преобразование данных на лету через `SET`

Список колонок в конце `LOAD DATA` принимает и имена колонок, и пользовательские
переменные `@var`. В `SET` можно преобразовать значение.

```sql
LOAD DATA INFILE '/var/lib/mysql-files/orders.csv'
INTO TABLE shop.orders
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(id, customer, @amount_cents, created_at, @dummy, source)
SET amount = @amount_cents / 100,
    source = 'legacy_import';
-- → Records: 1000000  Deleted: 0  Skipped: 0  Warnings: 0
```

Правила для `SET`-clause:

- Слева от `=` допустимы **только имена колонок**.
- Справа разрешён скалярный подзапрос, но **нельзя выбирать из загружаемой таблицы**.
- Строки, пропущенные `IGNORE n LINES`, не участвуют и в списке колонок, и в `SET`.
- Значения, не нужные таблице, направляются в переменную, которой не назначена
  колонка (`@dummy`) — это способ отбросить столбец.
- Пользовательские переменные не работают в формате фиксированной ширины.

Пример: загрузка значения `BIT` из двоичной записи.

```bash
printf "b'10'\nb'1111111'\n" > /var/lib/mysql-files/bit.txt
```

```sql
LOAD DATA INFILE '/var/lib/mysql-files/bit.txt'
INTO TABLE shop.bit_test (@var1)
SET b = CAST(CONV(MID(@var1, 3, LENGTH(@var1)-3), 2, 10) AS UNSIGNED);
-- → Records: 2  Deleted: 0  Skipped: 0  Warnings: 0
```

`LOAD DATA` трактует весь ввод как строки, поэтому значения для колонок `ENUM` и `SET`
нельзя передавать числами — только строками.

### Сценарий 4. Загрузка в staging-таблицу и подмена

Безопасная последовательность для большого файла: сначала грузить в отдельную таблицу
без ограничений и вторичных индексов, проверить, затем подменить.

```sql
-- 1. Приёмник: только колонки, которые есть в файле
CREATE TABLE shop.orders_new (
  id           BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  customer     VARCHAR(128) NOT NULL,
  amount       DECIMAL(12,2) NOT NULL,
  created_at   DATETIME NOT NULL
) ENGINE=InnoDB;

-- 2. Загрузка без вторичных индексов и без проверки внешних ключей
SET SESSION foreign_key_checks = 0;
-- → Query OK, 0 rows affected

LOAD DATA INFILE '/var/lib/mysql-files/orders.csv'
INTO TABLE shop.orders_new
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(id, customer, amount, created_at);
-- → Records: 1000000  Deleted: 0  Skipped: 0  Warnings: 0

SET SESSION foreign_key_checks = 1;

-- 3. Проверка ДО подмены
SELECT COUNT(*) AS rows_loaded, MIN(id) AS min_id, MAX(id) AS max_id
FROM shop.orders_new;
-- → rows_loaded = 1000000  min_id = 1  max_id = 1000000

SHOW WARNINGS;
-- → (пусто — если строки не помещались в поля, предупреждения будут здесь)

SELECT id FROM shop.orders_new WHERE amount = 0 ORDER BY id LIMIT 10;
-- → (пусто — признак того, что невалидные значения превратились в 0)

-- 4. Индексы добавляются после загрузки
ALTER TABLE shop.orders_new ADD INDEX idx_customer (customer),
    ADD INDEX idx_created (created_at),
    ALGORITHM=INPLACE, LOCK=NONE;
-- → Query OK, 0 rows affected (48.21 sec)

-- 5. Подмена
RENAME TABLE shop.orders TO shop.orders_old,
             shop.orders_new TO shop.orders;
-- → Query OK, 0 rows affected

ANALYZE TABLE shop.orders;
-- → Table          | Op        | Msg_type | Msg_text
-- → shop.orders    | analyze   | status   | Table statistics updated
```

Порядок шагов важен: индексы, добавленные до загрузки, поддерживаются на каждой
вставленной строке и радикально замедляют её. Полная методика, включая откат
подмены, — в [Безопасное массовое изменение данных](../Concepts/atomic_operations.md).

**Оптимизация окна загрузки через `SET_VAR` hint.** Вместо `SET SESSION`/`SET GLOBAL`
и последующего возврата значения можно ослаблять проверки прямо в операторе загрузки
через оптимизационную подсказку `SET_VAR` (MySQL 8.0+). Hint действует только для
длительности одного statements и восстанавливает значение автоматически — не нужно
вручную отслеживать, где закончилось окно:

```sql
-- Один оператор: без проверки внешних ключей, без unique-проверок, с отключённым
-- delayed_key_write. Hint не влияет на репликуцию (реплики его игнорируют).
LOAD DATA /*+ SET_VAR(foreign_key_checks=0)
              SET_VAR(unique_checks=0)
              SET_VAR(delayed_key_write=OFF) */
INFILE '/var/lib/mysql-files/orders.csv'
INTO TABLE shop.orders_new
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(id, customer, amount, created_at);
-- → Records: 1000000  Deleted: 0  Skipped: 0  Warnings: 0
```

Ограничения hint'а:

- Допустимы **только системные переменные с флагом `HINT_UPDATEABLE`** (оптимайзер и
  буферы выполнения: `optimizer_switch`, `max_heap_table_size`, `tmp_table_size`,
  `join_buffer_size`, `sort_buffer_size`, `foreign_key_checks`, `unique_checks` и др.).
  `innodb_flush_log_at_trx_commit`, `sync_binlog` и `innodb_io_capacity` с этим
  флагом не помечены — их можно менять только через `SET GLOBAL`.
- Hint должен стоять **сразу после ключевого слова** (`LOAD DATA /*+ ... */`).
- При несогласованности (например, значение не по типу или переменная не существует)
  hint игнорируется с предупреждением, а загрузка продолжается как обычно — не confuse
  молчаливое игнорирование с работой hint'а.
- Множественные `SET_VAR` в одном комментарии разрешены; при дублировании одной и той
  же переменной применяется **первый**, остальные — с предупреждением.

### Сценарий 5. `mysqlimport` как обёртка над `LOAD DATA`

`mysqlimport` не имеет собственного протокола — он формирует и отправляет `LOAD DATA`.

```bash
# Базовая загрузка CSV с заголовком
mysqlimport \
  --host=db01.internal \
  --user=loader --password \
  --local \
  --fields-terminated-by=',' \
  --fields-optionally-enclosed-by='"' \
  --lines-terminated-by='\n' \
  --ignore-lines=1 \
  --default-character-set=utf8mb4 \
  shop orders.csv
# → shop.orders: Records: 2  Deleted: 0  Skipped: 0  Warnings: 0
```

Ключевые опции:

| Опция | Эквивалент в `LOAD DATA` | Назначение |
| :--- | :--- | :--- |
| `--local` | `LOCAL` | Файл читает клиент; требует `local_infile` и на клиенте |
| `--replace` | `REPLACE` | Конфликтующие строки заменяют существующие |
| `--ignore` | `IGNORE` | Конфликтующие строки отбрасываются |
| `--fields-terminated-by=str` | `FIELDS TERMINATED BY` | Разделитель полей |
| `--fields-optionally-enclosed-by=c` | `OPTIONALLY ENCLOSED BY` | Кавычки значений |
| `--fields-escaped-by=c` | `FIELDS ESCAPED BY` | Символ экранирования |
| `--lines-terminated-by=str` | `LINES TERMINATED BY` | Разделитель строк |
| `--ignore-lines=n` | `IGNORE n LINES` | Пропустить первые `n` строк |
| `--delete` | — | Удалить таблицу перед загрузкой |
| `--default-character-set=cs` | `CHARACTER SET` | Кодировка |

`--local` требует **двух** включений: `local_infile=ON` на сервере и
`--local-infile=1` у клиента. В конфигурации по умолчанию `local_infile` выключен —
это мера безопасности, см. [Безопасность MySQL](./security.md).

### Сценарий 6. Наблюдение за ходом загрузки

```sql
-- Отдельная сессия: что сейчас грузится
SELECT ID, USER, TIME, STATE, LEFT(INFO, 100) AS query
FROM information_schema.PROCESSLIST
WHERE INFO LIKE 'LOAD DATA%';
-- → ID   | USER   | TIME | STATE         | query
-- → 9012 | loader |   42 | Sending data  | LOAD DATA INFILE '/var/lib/mysql-files/or...

-- Прогресс в процентах по имени файла в реплике
SELECT CHANNEL_NAME, SERVICE_STATE, REMAINING_DELAY,
       LAST_ERROR_NUMBER, LAST_QUEUED_TRANSACTION
FROM performance_schema.replication_applier_status_by_worker;
-- → CHANNEL_NAME | SERVICE_STATE | REMAINING_DELAY | LAST_ERROR_NUMBER
-- →              | Applying      |             0.0 |                  0

-- Уровень изоляции: транзакция не фиксируется до конца файла
SELECT trx_id, trx_started, trx_rows_locked, trx_mysql_thread_id
FROM information_schema.INNODB_TRX
WHERE trx_mysql_thread_id = 9012;
```

Прогресс по числу строк можно оценить косвенно — по объёму undo и по скорости роста
таблицы:

```sql
SELECT table_name,
       ROUND(data_length/1024/1024, 1) AS data_mb,
       table_rows
FROM information_schema.TABLES
WHERE table_schema = 'shop' AND table_name IN ('orders','orders_new');
```

### Сценарий 7. Загрузка из именованного канала (FIFO) на Unix

Если данные ещё не лежат в файле, можно читать поток:

```bash
mkfifo /var/lib/mysql-files/stream.dat
chmod 666 /var/lib/mysql-files/stream.dat
find / -ls > /var/lib/mysql-files/stream.dat &
mysql -e "LOAD DATA INFILE 'stream.dat' INTO TABLE shop.fs_list" shop
# → Records: 4821  Deleted: 0  Skipped: 0  Warnings: 0
```

Ограничение: генератор данных и команда `mysql` должны выполняться в разных терминалах,
либо генератор запускается в фоне. Иначе чтение блокируется до момента получения данных.

## Устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR 1146 (42S02): Table 'shop.x' doesn't exist` | Опечатка в имени или не выбрана база | Проверить `SHOW TABLES LIKE 'x'` |
| `ERROR 1045` / отказ при `INFILE` без `LOCAL` | Нет привилегии `FILE` | Выдать `FILE` только на время загрузки: `GRANT FILE ON *.* TO 'loader'@'10.%';` |
| Отказ из-за `secure_file_priv` | Файл вне разрешённого каталога | Перенести файл в `secure_file_priv` (в конфигурации базы — `/var/lib/mysql-files`) |
| `ERROR 1148 (42000): The used command is not allowed with InnoDB` (для `LOCAL` в ряде конфигураций) | `local_infile=OFF` | Включать только на время: `SET GLOBAL local_infile = ON;` и снять после загрузки |
| `ERROR 1062 Duplicate entry` и загрузка встала на середине | Не задан `IGNORE`/`REPLACE` | Добавить `IGNORE` и загружать в staging-таблицу |
| Мусор вместо кириллицы | Кодировка файла не совпадает с `character_set_database` | Указать `CHARACTER SET utf8mb4` явно |
| `ERROR 1366 Incorrect ... value` на части строк | Строгий `sql_mode` + невалидные данные | Найти строки через `SHOW WARNINGS`, исправить файл; **не** полагаться на `IGNORE` |
| `Records: 1000000 Skipped: 40000` | Дубликаты по уникальному ключу | Ожидаемо при `IGNORE`/`LOCAL`; проверить, что это именно дубли, а не битые строки |
| `ERROR 3938 (22000): Found a row not matching the given partition set` | `PARTITION (...)` в `LOAD DATA`, строка не попадает ни в одну секцию | Убрать `PARTITION` либо расширить список секций |
| Загрузка `LOCAL` падает с ошибкой о диске | Сервер не может создать копию файла во временном каталоге | Проверить `datadir`/tmpdir; увеличить место; перейти на не-`LOCAL` вариант |
| Значения `ENUM`/`SET` грузятся как числа или 0 | `LOAD DATA` читает весь ввод как строки | Передавать значения строками |
| `BIT` грузится неверно | Двоичная запись `b'...'` не интерпретируется | Использовать `CONV`/`MID` в `SET` (сценарий 3) |
| Медленно, растёт buffer pool | Вторичные индексы созданы до загрузки | Грузить в таблицу без индексов, индексы добавлять после |
| `LOAD DATA` блокирует таблицу надолго | Блокировка метаданных на начало/конец операции | `SET SESSION lock_wait_timeout = 30;` перед загрузкой |
| После загрузке планы запросов неверны | Устаревшая статистика | `ANALYZE TABLE` до, а не после, `OPTIMIZE TABLE` |
| Загрузка медленно «замирает» на 90% | `innodb_io_capacity` слишком низок для диска; чистка буфер-пула отстаёт | Поднять `innodb_io_capacity`/`innodb_io_capacity_max`; проверить `SHOW ENGINE INNODB STATUS` |
| После загрузки `History list length` не падает | Undo-чистка отстаёт из-за низкого темпа I/O | Поднять `innodb_io_capacity`; при необходимости `SET GLOBAL innodb_purge_threads = 8` |
| `LOAD DATA LOCAL` роняет сервер с `Can't create/write to file` | Сервер не может создать копию файла во временном каталоге | Проверить `datadir`/tmpdir; увеличить место; перейти на не-`LOCAL` вариант |
| `SELECT ... INTO OUTFILE` возвращает `Access denied` | Нет привилегии `FILE` или путь вне `secure_file_priv` | Выдать `FILE` на время; проверить `SHOW VARIABLES LIKE 'secure_file_priv'` |
| `INTO OUTFILE` создаёт файл с `umask 0640` | С 8.0.17 umask при создании файлов — `0640`; до этого `0666` | Проверить права на файл: `ls -l /var/lib/mysql-files/` |
| Загрузка встаёт на середине из-за исчерпания FD | `ulimit -n` на `mysqld` ниже числа одновременных операций I/O | Проверить `SHOW VARIABLES LIKE 'open_files_limit'`; поднять `LimitNOFILE` в systemd |
| `Records: 1000000 Skipped: 40000` | Дубликаты по уникальному ключу | Ожидаемо при `IGNORE`/`LOCAL`; проверить, что это именно дубли, а не битые строки |

Полный разбор инцидентов по симптомам — [Диагностический runbook](./troubleshooting-runbook.md).

## Лучшие практики

- **Всегда грузить в staging-таблицу.** `LOAD DATA` не атомарен: прерванная на середине
  загрузка оставляет таблицу с частичными данными, и отличить их от корректных без
  внешнего источника правды невозможно.
- **Всегда сверять `Records / Deleted / Skipped / Warnings`.** Успешное сообщение
  `Query OK` при `LOCAL` или `IGNORE` не означает, что загружены правильные данные.
- **Проверять `SHOW WARNINGS`, а не полагаться на `Query OK`.** Список ограничен
  `max_error_count` предупреждениями — увеличить при разборе:
  `SET SESSION max_error_count = 1000;`
- **Задавать `FIELDS`/`LINES` явно**, даже когда кажется, что хватает умолчаний. Файл,
  выгруженный с другого сервера, может оказаться в формате по умолчанию.
- **Создавать вторичные индексы после загрузки**, а не до.
- **Держать `local_infile=OFF` в постоянной конфигурации** и включать его точечно на
  время загрузки, если без `LOCAL` обойтись нельзя.
- **Выдавать привилегию `FILE` по необходимости** и отзывать сразу после загрузки.
- **Не полагаться на `LOAD DATA` при statement-based репликации** (см. ниже).
- **Проверять кодировку на небольшой выборке** до загрузки большого файла: 100 строк
  покажут проблему за секунду, а не после часовой загрузки.

### Сравнение способов массовой загрузки

| Способ | Скорость | Атомарность | Когда применять |
| :--- | :--- | :--- | :--- |
| `LOAD DATA INFILE` | Самый быстрый (парсинг на сервере) | Не атомарен | Большие файлы (CSV), staging-загрузка |
| Multi-row `INSERT` | Быстрый (один round-trip) | Атомарен (в рамках транзакции) | Приложение, небольшие батчи (100–1000 строк) |
| `INSERT ... SELECT` | Зависит от SELECT | Атомарен | Перенос данных между таблицами |
| Построчный `INSERT` | Медленный (round-trip на строку) | Атомарен | Не использовать для массовой загрузки |

**Multi-row INSERT — размер батча:**

```sql
-- Хорошо: одна транзакция, один round-trip
INSERT INTO stg_orders (id, customer, amount) VALUES
  (1, 'Иванов', 1500.50),
  (2, 'Петров', 2300.00),
  ...;   -- 100–1000 строк за оператор
```

Практические ориентиры:

- **Размер батча 100–1000 строк** — оптимум между round-trip'ами и
  размером транзакции. Слишком маленькие батчи — много round-trip'ов;
  слишком большие — длинные транзакции, блокировки, undo log.
- **`max_allowed_packet`** — лимит на размер одного оператора; батч
  не должен его превышать. Проверить: `SHOW VARIABLES LIKE 'max_allowed_packet';`
- **Оборачивать в транзакцию** при InnoDB: `START TRANSACTION; ... COMMIT;`
  — иначе каждый оператор = отдельная транзакция (fsync на каждый).
- **`LOAD DATA` быстрее `INSERT`** примерно в 20–100 раз на больших
  объёмах, но требует файла в `secure_file_priv` и не атомарен.

**Когда что выбирать:**

- Файл уже есть (выгрузка из другой системы) → `LOAD DATA`.
- Данные формирует приложение → multi-row `INSERT` батчами.
- Перенос между таблицами на том же сервере → `INSERT ... SELECT`.

## Дополнительная информация

### Репликация: почему `LOAD DATA` опасен при `STATEMENT`

`LOAD DATA` считается небезопасным для statement-based репликации. При
`binlog_format=STATEMENT` **каждая реплика создаёт временный файл с данными**. Этот файл
**не шифруется, даже если шифрование binary log включено на источнике**.

Практическое следствие: если требуется шифрование данных на репликах, использовать
row-based или mixed-формат — при них реплики временный файл не создают.

```sql
SELECT @@binlog_format;
-- → @@binlog_format = ROW

SHOW BINARY LOGS;
-- → Log_name           | File_size
-- → binlog.000031      | 1048576
```

Формат binary log, проверка репликации и PITR — [Репликация](./replication/overview.md)
и [GTID](./replication/gtid.md).

### Модификаторы `LOW_PRIORITY` и `CONCURRENT`

`LOW_PRIORITY` откладывает `LOAD DATA` до момента, когда таблицу никто не читает, а
`CONCURRENT` позволяет читать таблицу MyISAM параллельно с загрузкой. **Оба влияют
только на движки с исключительной табличной блокировкой** (MyISAM, MEMORY, MERGE) и
не оказывают никакого действия на InnoDB.

### Параметры-кандидаты на ускорение

Цена ускорения — всегда снижение гарантий. Значения и их последствия описаны в
[Конфигурация MySQL](./configuration.md) и
[Обслуживание и обновления](./maintenance-and-upgrades.md):

| Что ослабляется | Что теряется |
| :--- | :--- |
| `innodb_flush_log_at_trx_commit` | Гарантия записи redo log при каждом коммите |
| `sync_binlog` | Гарантия записи binlog при каждом коммите |
| `foreign_key_checks = 0` | Проверка ссылочной целостности |
| `unique_checks = 0` | Проверка уникальности при вставке |
| `innodb_io_capacity` (повышение) | Риск упасть в бэклог чистки буфер-пула при всплеске |
| `innodb_flush_log_at_trx_commit = 2` | Гарантия при коммите, но не при смерти ОС (только при `mysql`-сбое) |

Эти параметры ослабляются **только на окно загрузки в непроизводственной среде или при
полном понимании риска потери данных**, и возвращаются к безопасным значениям сразу
после. Порядок проверки — [Диагностический runbook](./troubleshooting-runbook.md).

### InnoDB I/O при массовой загрузке

Массовая загрузка — это всплеск `INSERT`, а не фоновая нагрузка, и InnoDB на это
реагирует не по-другому: dirty-page-флудинг, checkpoint-бэклог и `fsync`-шторм.
Ключевые переменные, которые настройка под окно загрузки:

| Переменная | Дефолт | Что делает | Рекомендация на окно загрузки |
| :--- | :--- | :--- | :--- |
| `innodb_io_capacity` | `200` | Базовый темп фоновой чистки (IOPS) | Поднять до 1000–5000 (SSD/NVMe) |
| `innodb_io_capacity_max` | `max(2000, 2×innodb_io_capacity)` | Максимальный темп при отставании чистки | Поднять до 2× от `innodb_io_capacity`, но не выше 10000 |
| `innodb_flush_log_at_trx_commit` | `1` | `fsync` при каждом коммите | Временно `2` — коммит логируется, `fsync` откладывается до flush-события |
| `innodb_flush_neighbors` | `0` (с 8.0) | Чистить соседние страницы при flush | На SSD оставить `0`; на HDD при вставке пакетами — `1` |
| `innodb_max_dirty_pages_pct` | `90` (с 8.0) | Порог, после которого чистка ускоряется | Оставить `90` — при загрузке он и так превышается, это норма |
| `innodb_adaptive_flushing` | `ON` | Динамическая регулировка темпа чистки | Оставить включённым — без него всплеск приводит к `fsync`-шторму |

**Что смотреть, если загрузка «теряет» скорость с ростом таблицы:**

```sql
SELECT * FROM information_schema.INNODB_METRICS
WHERE NAME LIKE 'buffer_pool_pages%' OR NAME LIKE 'checkpoint%';
-- → NAME                                          | COUNT
-- → buffer_pool_pages_dirty                       | 48210
-- → buffer_pool_pages_total                       | 262144
-- → buffer_pool_read_requests                      | 31284710
-- → buffer_pool_pages_flushed                     | 48210
```

```sql
SHOW ENGINE INNODB STATUS;
-- Искать в `BACKGROUND THREAD` и `FLUSH`:
-- History list length — рост говорит о отставании undo-чистки
-- Log sequence number - Last checkpoint — если близко к размеру redo log,
-- чистка не успевает и появляются «всплески» latency
```

**Критерий отката:** после окна загрузки `History list length` должна вернуться к
тысячам (а не к десяткам тысяч), а `Modified pages` — упасть ниже
`innodb_max_dirty_pages_pct` от буфер-пула. Если не падает — `innodb_io_capacity`
слишком низок для диска.

### Внешние ресурсы

- [MySQL Reference Manual: LOAD DATA Statement](https://dev.mysql.com/doc/refman/8.0/en/load-data.html)
- [MySQL Reference Manual: Security Considerations for LOAD DATA LOCAL](https://dev.mysql.com/doc/refman/8.0/en/load-data-local-security.html)
- [MySQL Reference Manual: Replication and LOAD DATA](https://dev.mysql.com/doc/refman/8.0/en/replication-and-load-data.html)
- [MySQL Reference Manual: mysqlimport](https://dev.mysql.com/doc/refman/8.0/en/mysqlimport.html)

### См. также

- **[Online Schema Change](./Operations/online-schema-change.md)** — добавление
  индексов после массовой загрузки.
- **[Безопасное массовое изменение данных](../Concepts/atomic_operations.md)** —
  порционные операции, подмена таблицы, pre-flight проверки, откат.
- **[Обслуживание и обновления MySQL](./maintenance-and-upgrades.md)** —
  `ANALYZE TABLE`, `OPTIMIZE TABLE`, дефрагментация после загрузки.
- **[Кодировки и сортировки](./charset-and-collation.md)** — `utf8mb4`, ошибки
  `Illegal mix of collations` при загрузке.
- **[Диагностический runbook](./troubleshooting-runbook.md)** — разбор по кодам ошибок.
- **[Безопасность MySQL](./security.md)** — `local_infile`, `secure_file_priv`,
  привилегия `FILE`.
- **[Индексы в MySQL](./indexing.md)** — статистика и планы после массовой загрузки.