# SQL mode в MySQL: строгий режим, ONLY_FULL_GROUP_BY и обязательный первичный ключ

**Актуально для:** MySQL 8.4 LTS / 9.7 LTS / 26.x Innovation

> **Статус:** MySQL 8.0 достигла End of Life в апреле 2026 года (8.0.46). Все
> описанные ниже режимы работают в 8.4 и позже без изменений; для новых
> развёртываний рекомендуется 8.4 LTS или 9.7 LTS.

`sql_mode` — набор переключателей, меняющих поведение сервера: начиная с того, считать ли
ошибкой недопустимое значение, и заканчивая тем, разрешено ли в `GROUP BY` упоминать
колонку, которой нет в самом `GROUP BY`. Для эксплуатации тема важна по двум причинам:
режим объясняет, почему одинаковый код ведёт себя по-разному на разных инсталляциях, и
именно `sql_mode` чаще всего ломает приложение при переходе на 8.x.

Партнёры по теме: [Кодировки и сортировки](./charset-and-collation.md) —
взаимодействие с `NO_BACKSLASH_ESCAPES` и `ANSI_QUOTES`; [Конфигурация MySQL](./configuration.md) —
`sql_mode` в `my.cnf`; [Роли и привилегии](./role_management.md) — привилегии,
необходимые для изменения режима.

## Требования и предпосылки

| Проверка | Команда / способ | Ожидаемый результат |
| :--- | :--- | :--- |
| Версия сервера | `SELECT VERSION();` | `8.4.x` или выше; ниже 8.0 — режимы недоступны |
| Значение `sql_mode` по умолчанию | `SELECT @@GLOBAL.sql_mode;` | `ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION` |
| Поддержка `sys.list_add`/`sys.list_drop` | `SELECT sys.list_add('a,b', 'c');` | `a,b,c` — функции доступны с MySQL 8.0.18 |
| Поддержка хинта `SET_VAR` | `SELECT /*+ SET_VAR(sql_mode='STRICT_TRANS_TABLES') */ 1;` | `1` без ошибки — хинт работает с 8.0.3 |
| Поддержка `sql_require_primary_key` | `SHOW VARIABLES LIKE 'sql_require_primary_key';` | `OFF` — переменная доступна с 8.0.13 |
| Наличие привилегии | `SHOW GRANTS;` | `SYSTEM_VARIABLES_ADMIN` (или устаревший `SUPER`) для `SET GLOBAL` |
| Отсутствие устаревших режимов в `my.cnf` | `grep -i sql_mode /etc/mysql/my.cnf` | Нет `DB2`, `MAXDB`, `MSSQL`, `MYSQL323`, `MYSQL40`, `ORACLE`, `POSTGRESQL`, `NO_FIELD_OPTIONS`, `NO_KEY_OPTIONS`, `NO_TABLE_OPTIONS`, `NO_AUTO_CREATE_USER` |

**Важные предпосылки:**

- **Зарезервированные слова.** Режимы `ANSI_QUOTES`, `IGNORE_SPACE`, `PIPES_AS_CONCAT` влияют на парсер; при их включении убедитесь, что имена объектов не конфликтуют с зарезервированными словами.
- **Апгрейд с 5.7.** Дефолт `sql_mode` в 5.7 не включал `NO_ZERO_DATE`, `NO_ZERO_IN_DATE`, `ERROR_FOR_DIVISION_BY_ZERO`. Если приложение писалось под 5.7, проверьте его на совместимость до перехода на 8.x (см. сценарий 2).
- **Совместимость с репликой.** `sql_mode` должен быть одинаков на всех узлах кластера. Используйте `SET PERSIST` для переживания рестарта.

## Определения

| Термин | Значение |
| :--- | :--- |
| Strict mode | Совокупность режимов, превращающих некорректные данные в ошибку вместо тихого исправления |
| `sql_mode` | Системная переменная, составная из перечисленных через запятую режимов |
| Coercion | Неявное приведение типа или сравнение с потерями точности |
| Functional dependency | Функциональная зависимость: если `GROUP BY` содержит первичный ключ, все колонки таблицы считаются в нём задействованными |
| `ANY_VALUE()` | Функция, явно разрешающая неагрегированную колонку в `GROUP BY` |
| `SET_VAR` | Хинт для подмены значения системной переменной в отдельном запросе |

## Базовые концепции

### Значение по умолчанию

```sql
SELECT @@GLOBAL.sql_mode;
-- → ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION
```

| Режим | Что меняет |
| :--- | :--- |
| `ONLY_FULL_GROUP_BY` | Запрещает неагрегированные колонки в `SELECT`/`HAVING`/`ORDER BY`, не перечисленные в `GROUP BY` и не находящиеся в функциональной зависимости от него |
| `STRICT_TRANS_TABLES` | Ошибка вместо исправления недопустимых значений для транзакционных таблиц |
| `NO_ZERO_IN_DATE` | Запрещает нулевые месяц и день в датах. Объявлен устаревшим: его эффект включён в строгий режим |
| `NO_ZERO_DATE` | Запрещает дату `0000-00-00` |
| `ERROR_FOR_DIVISION_BY_ZERO` | Деление на ноль в `INSERT`/`UPDATE` даёт ошибку. **Устаревший режим (deprecated)** — ожидается интеграция в строгий режим |
| `NO_ENGINE_SUBSTITUTION` | Ошибка, если запрошенный движок недоступен, вместо молчаливой подстановки |

Практический вывод: **значение по умолчанию уже строгое**. Многие инструкции и статьи,
советующие «включить строгий режим», описывают переход с MySQL 5.6 и 5.7, где дефолт
был другим.

### Полный список режимов

| Режим | Действие |
| :--- | :--- |
| `ALLOW_INVALID_DATES` | Разрешает некорректные даты, которые иначе обнуляются |
| `ANSI_QUOTES` | Двойные кавычки обрабатываются как идентификаторы, а не как строки |
| `ERROR_FOR_DIVISION_BY_ZERO` | Ошибка при делении на ноль в `INSERT`/`UPDATE` |
| `HIGH_NOT_PRECEDENCE` | `NOT` имеет тот же приоритет, что и операторы сравнения, вместо более высокого приоритета |
| `IGNORE_SPACE` | Допускает пробелы между именем функции и открывающей скобкой |
| `NO_AUTO_VALUE_ON_ZERO` | `AUTO_INCREMENT`-колонка может быть записана нулём |
| `NO_BACKSLASH_ESCAPES` | Обратный слэш не является экранирующим символом |
| `NO_DIR_IN_CREATE` | `CREATE` не создаёт каталог |
| `NO_ENGINE_SUBSTITUTION` | Ошибка при недоступности движка |
| `NO_UNSIGNED_SUBTRACTION` | Результат беззнаковой арифметики не сворачивается в `DECIMAL` со знаком |
| `NO_ZERO_DATE` | Запрещает `0000-00-00` |
| `NO_ZERO_IN_DATE` | Запрещает нули в месяце и дне (устарел) |
| `ONLY_FULL_GROUP_BY` | Строгие правила для `GROUP BY` |
| `PAD_CHAR_TO_FULL_LENGTH` | При извлечении `CHAR` дополняется пробелами до полной длины. Объявлен устаревшим в MySQL 8.0.13 |
| `PIPES_AS_CONCAT` | `||` работает как конкатенация строк, а не как логическое ИЛИ |
| `REAL_AS_FLOAT` | Тип `REAL` трактуется как `FLOAT` |
| `STRICT_ALL_TABLES` | Строгий режим для всех таблиц, включая не транзакционные |
| `STRICT_TRANS_TABLES` | Строгий режим только для транзакционных таблиц |
| `TIME_TRUNCATE_FRACTIONAL` | Дробная часть секунд усекается, а не округляется |

Существуют также составные режимы (`ANSI`, `TRADITIONAL` и ряд других), объединяющие
несколько перечисленных. **В MySQL 8.0.11** как несовместимое изменение удалены:
`DB2`, `MAXDB`, `MSSQL`, `MYSQL323`, `MYSQL40`, `ORACLE`, `POSTGRESQL`,
`NO_FIELD_OPTIONS`, `NO_KEY_OPTIONS`, `NO_TABLE_OPTIONS` — присвоить их `sql_mode` или
использовать как значение для `mysqldump --compatible` больше нельзя. Это частая причина
ошибки старта при обновлении с 5.7. Аналогично в 8.0.11 удалён `NO_AUTO_CREATE_USER` —
`GRANT` больше не создаёт пользователей, и режим стал неактуальным.

### Что делает строгий режим

Сравнение одного и того же кода в строгом и нестрогом режиме:

```sql
CREATE TABLE orders (id INT PRIMARY KEY AUTO_INCREMENT, amount DECIMAL(10,2) NOT NULL);
```

| Операция | Строгий режим | Нестрогий режим |
| :--- | :--- | :--- |
| `INSERT INTO orders (amount) VALUES ('abc')` | `ERROR 1366 (HY000): Incorrect decimal value` | `Query OK, 1 row affected, 1 warning`, записано `0.00` |
| `INSERT INTO orders (amount) VALUES (99999999999)` | `ERROR 1264 (22003): Out of range value` | Записано максимальное допустимое значение, warning |
| `INSERT INTO orders (amount) VALUES (10.999)` | `ERROR 1265 (22003): Data truncated for column` | Записано `10.99`, warning |
| `INSERT INTO orders VALUES (1, 10/0)` | `ERROR 1365 (22012): Division by 0` | Записано `NULL`, warning |
| Некорректная дата `'2026-02-30'` | `ERROR 1292 (22007): Incorrect datetime value` | Записано `0000-00-00`, warning |

Разница не в сообщении, а в данных: в нестрогом режиме в базу попадают нули и обрезанные
значения, и ошибка обнаруживается месяцами позже — в отчётах.

### ONLY_FULL_GROUP_BY: почему ломаются старые запросы

```sql
CREATE TABLE mytable (
  id INT UNSIGNED NOT NULL PRIMARY KEY,
  a  VARCHAR(10),
  b  INT
);
INSERT INTO mytable VALUES (1,'abc',1000), (2,'abc',2000), (3,'def',4000);
```

```sql
-- Ошибка при включённом ONLY_FULL_GROUP_BY
SELECT a, b, SUM(c) FROM mytable WHERE a = 'abc' AND b = 'qrs' GROUP BY id;
-- → ERROR 3065 (HY000): Expression #2 of SELECT list is not in GROUP BY clause
--   and contains nonaggregated column 'test.mytable.b' which is not functionally
--   dependent on columns in GROUP BY clause; this is incompatible with sql_mode=ONLY_FULL_GROUP_BY
```

Режим допускает больше, чем кажется:

```sql
-- Столбец имеет единственное значение в каждой группе — допустимо
SELECT a, SUM(b) FROM mytable WHERE a = 'abc' GROUP BY a;
-- → a  | SUM(b)
-- → abc |    3000
```

Функциональная зависимость распознаётся автоматически: если `GROUP BY` содержит
первичный ключ, все колонки таблицы считаются от него зависимыми.

```sql
-- GROUP BY по первичному ключу — зависимость распознана, ошибки нет
SELECT id, a, b FROM mytable GROUP BY id;
-- → OK
```

Альтернатива отключению режима — явное `ANY_VALUE()`, которое документирует намерение
и не меняет настройки сервера:

```sql
SELECT a, ANY_VALUE(b) AS b_representative, SUM(b)
FROM mytable GROUP BY a;
```

### sql_require_primary_key — отдельная переменная, не часть sql_mode

Требование наличия первичного ключа реализовано **не** через `sql_mode`, а отдельной
системной переменной.

| Параметр | Значение |
| :--- | :--- |
| Появление | MySQL 8.0.13 |
| Значение по умолчанию | `OFF` |
| Область действия | Global, Session |
| Динамическая | Да |

Зачем это нужно операционно: таблица без первичного ключа при построчной репликации
требует полного сканирования таблицы для каждого изменения — и медленный master, и медленная
репликация. Серверная проверка на этапе `CREATE TABLE`/`ALTER TABLE` устраняет проблему
до её появления.

```sql
SET GLOBAL sql_require_primary_key = ON;
-- → Query OK, 0 rows affected
```

```sql
CREATE TABLE shop.tmp_events (id BIGINT, payload TEXT) ENGINE=InnoDB;
-- → ERROR 4000 (HY000): Table 'shop.tmp_events' doesn't have a primary key. Please define one.
```

Тот же код `4000` даёт `ALTER TABLE`, добавляющий столбец без PK в таблицу, где PK ещё нет.

Сопутствующая настройка на стороне реплики:

```sql
STOP REPLICA;
SET @@sql_require_primary_key = ON;
CHANGE REPLICA SOURCE TO REQUIRE_TABLE_PRIMARY_KEY_CHECK = GENERATE FOR CHANNEL 'ch1';
```

Управление распространением значения: при `REQUIRE_TABLE_PRIMARY_KEY_CHECK = GENERATE`
реплика всегда применяет `sql_require_primary_key = ON`, при `OFF` — всегда `OFF`,
независимо от значения на источнике.

Связанная особенность: поток применения репликации не прерывается с ошибкой на
событиях `Query`, отфильтрованных по причине отсутствия необходимых прав на установку
перечисленных переменных, включая `sql_require_primary_key` и `default_table_encryption`.

### Уровни применения

```
Глобальный (по умолчанию для новых соединений)
  └─ Сессионный (перекрывает глобальный)
       └─ Хинт SET_VAR (перекрывает сессионный для одного оператора)
```

```sql
SHOW VARIABLES LIKE 'sql_mode';
SHOW SESSION VARIABLES LIKE 'sql_mode';
-- → session sql_mode
-- → ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION
```

Хинт `SET_VAR` действует на один оператор — полезный способ выполнить один специфичный
запрос без изменения сессии:

```sql
SELECT /*+ SET_VAR(sql_mode = 'STRICT_TRANS_TABLES') */ id FROM t WHERE amount = 'abc';
```

Поддержка `SET_VAR` есть не у всех переменных: `sql_mode` её поддерживает.

Для добавления и удаления режимов есть функции sys schema, безопаснее ручного разбора строки:

```sql
-- Добавить режим к текущему значению
SET SESSION sql_mode = sys.list_add(@@SESSION.sql_mode, 'NO_ZERO_DATE');
-- → Query OK, 0 rows affected

-- Удалить режим
SET SESSION sql_mode = sys.list_drop(@@SESSION.sql_mode, 'NO_ZERO_DATE');
-- → Query OK, 0 rows affected
```

## Практические сценарии

### Сценарий 1. Проверка режима и поиск расхождений между сессиями

```sql
-- Глобальное значение
SELECT @@GLOBAL.sql_mode;

-- Текущая сессия
SELECT @@SESSION.sql_mode;

-- Расхождение: сессия приложения мягче глобальной
SELECT IF(@@GLOBAL.sql_mode = @@SESSION.sql_mode, 'same', 'DIFFERENT') AS state;
-- → DIFFERENT

-- Проверить с клиента, не заходя в сессию
mysql -N -B -e "SELECT @@SESSION.sql_mode"
# → ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,...
```

Приложение, которое устанавливает `sql_mode` в соединении (JDBC-строка, ORM-конфигурация,
код инициализации), будет вести себя иначе, чем предполагает конфигурация сервера.
Значение `DIFFERENT` — первый сигнал искать именно такую настройку.

### Сценарий 2. Разбор приложения на несовместимость с ONLY_FULL_GROUP_BY

Запускайте проверку до перевода приложения на 8.x:

```bash
# На текущей версии MySQL (5.7 с отключённым режимом) включить режим на сессию
mysql -e "SET SESSION sql_mode='$(mysql -N -B -e 'SELECT @@SESSION.sql_mode' | sed 's/ONLY_FULL_GROUP_BY,//')'"
# затем прогнать регрессионные тесты и собрать ошибки 3065
```

```sql
-- Найти в коде запросы, которые перестанут работать: группировка с неагрегированными
-- колонками вне списка GROUP BY
-- (конкретные места находятся в коде приложения; сервер лишь сообщает ошибку)
```

План миграции:

```
1. Собрать все запросы, возвращающие ошибку 3065 (тестовый прогон)
2. Для каждого — исправить запрос либо добавить ANY_VALUE() там, где недетерминизм допустим
3. Повторить прогон до нуля ошибок
4. Только после этого переходить на 8.x
```

### Сценарий 3. Настройка режима в my.cnf

```ini
[mysqld]
# Явное перечисление — устойчивее к изменению дефолтов между версиями
sql_mode = STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,
           ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,
           ONLY_FULL_GROUP_BY
```

```bash
sudo mysqld --validate-config
# → ошибок нет, вывод пуст

sudo systemctl restart mysql
# → сервер перезапущен

mysql -N -B -e "SELECT @@GLOBAL.sql_mode"
# → STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,ONLY_FULL_GROUP_BY
```

Порядок режимов в строке не влияет на поведение, но при сравнении вывода с ожидаемым
значением имеет значение.

### Сценарий 4. Временное смягчение для одного клиента

Иногда мягче дать проблемному приложению собственный режим, чем отключать строгость
для всех. Решение — выдать учётной записи `SESSION_VARIABLES_ADMIN` и настроить режим
в строке подключения приложения:

```sql
CREATE USER 'legacy_app'@'10.%' IDENTIFIED BY '...';
GRANT SESSION_VARIABLES_ADMIN ON *.* TO 'legacy_app'@'10.%';
```

```bash
mysql --init-command="SET SESSION sql_mode='NO_ENGINE_SUBSTITUTION'" -u legacy_app -p
```

> **Осторожно:** смягчение режима для одного клиента маскирует проблему в данных. Если
> клиент пишет в таблицы, которые читает отчётность, исправление запросов всё равно
> необходимо.

### Сценарий 5. Поиск данных, испорченных нестрогим режимом

Если нестрогий режим действовал исторически, последствия уже в данных:

```sql
-- Нулевые даты (типичный признак нестрогого режима)
SELECT COUNT(*) AS zero_dates
FROM shop.orders
WHERE created_at = '0000-00-00';
-- → 184203

-- Нули в денежных колонках, где их быть не должно
SELECT COUNT(*) AS zero_amounts FROM shop.orders WHERE amount = 0;
-- → 9120
```

```sql
-- Образец испорченных строк
SELECT id, created_at, amount
FROM shop.orders
WHERE created_at = '0000-00-00' OR amount = 0
LIMIT 20;
```

Выборка по объёму, батчами — см.
[Безопасные массовые операции с данными](../Concepts/safe_large_scale_data_modification.md).

### Сценарий 6. Включение обязательного первичного ключа

```sql
SHOW GLOBAL VARIABLES LIKE 'sql_require_primary_key';
-- → sql_require_primary_key = OFF

-- Проверить существующие таблицы без первичного ключа
SELECT t.TABLE_SCHEMA, t.TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES t
LEFT JOIN (
    SELECT TABLE_SCHEMA, TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_TYPE = 'PRIMARY KEY'
) pk
  ON pk.TABLE_SCHEMA = t.TABLE_SCHEMA AND pk.TABLE_NAME = t.TABLE_NAME
WHERE t.TABLE_TYPE = 'BASE TABLE'
  AND pk.TABLE_NAME IS NULL
  AND t.TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys')
ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME;
-- → TABLE_SCHEMA | TABLE_NAME
-- → analytics    | events_raw       ← требует внимания
-- → shop         | session_cache

SET PERSIST sql_require_primary_key = ON;
-- → Query OK, 0 rows affected (SET PERSIST — переживает рестарт)
```

Включать только после того, как все таблицы получили первичный ключ: переменная
затрагивает `CREATE TABLE` и `ALTER TABLE`, и падение процесса миграции из-за
отсутствия ключа нежелательно.

### Сценарий 7. Диагностика ошибок записи в логе

```sql
-- Найти запросы, которые завершились ошибками, через sys schema
SELECT query, error, warn, exec_count
FROM sys.statements_with_errors_or_warnings
ORDER BY error DESC
LIMIT 20;
-- → query                                   | error | warn | exec_count
-- → UPDATE orders SET amount = ? WHERE id = ? | 1264  |    0 |     182345
-- →   ERROR 1264: Out of range value for column 'amount'
```

Высокое число ошибок 1264, 1366, 1292 при работающем приложении означает одно из двух:
либо строгий режим включён и приложение не обрабатывает исключения, либо данные приходят
из внешнего источника без валидации. Оба случая требуют правки на стороне приложения —
ослабление режима здесь не решение.

### Сценарий 8. Проверка перед апгрейдом с 5.7

Перед переходом с MySQL 5.7 на 8.x выполните проверку, чтобы выявить запросы, которые
перестанут работать из-за изменения дефолтного `sql_mode`:

```bash
# 1. Проверить текущий sql_mode (пример для MySQL 5.7)
mysql -N -B -e "SELECT @@GLOBAL.sql_mode"
# → ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION
#    (5.7 — без NO_ZERO_DATE, NO_ZERO_IN_DATE, ERROR_FOR_DIVISION_BY_ZERO)
#    NO_AUTO_CREATE_USER удалён в 8.0.11 — при апгрейде удалить из my.cnf

# 2. Включить полный строгий режим на сессию и прогонять тесты
mysql -e "SET SESSION sql_mode='ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
# затем прогнать регрессионные тесты и собрать ошибки 3065, 1292, 1366, 1264

# 3. Проверить, нет ли устаревших режимов в конфигурации
grep -i sql_mode /etc/mysql/my.cnf /etc/mysql/my.cnf.d/* 2>/dev/null
# → искать DB2, MAXDB, MSSQL, MYSQL323, MYSQL40, ORACLE, POSTGRESQL,
#    NO_FIELD_OPTIONS, NO_KEY_OPTIONS, NO_TABLE_OPTIONS, NO_AUTO_CREATE_USER
```

План действий:

```
1. Собрать все запросы, возвращающие ошибку 3065 (тестовый прогон)
2. Для каждого — исправить запрос либо добавить ANY_VALUE() там, где недетерминизм допустим
3. Проверить, что в my.cnf нет удалённых режимов — удалить при наличии
4. Повторить прогон до нуля ошибок
5. Только после этого переходить на 8.x
```

## Валидация

После изменения `sql_mode` проверьте, что новое значение применилось:

```sql
-- Глобальное значение
SELECT @@GLOBAL.sql_mode;

-- Сессионное значение (должно совпадать с глобальным при новом соединении)
SELECT @@SESSION.sql_mode;

-- Проверить, что нужный режим присутствует
SELECT @@sql_mode LIKE '%ONLY_FULL_GROUP_BY%' AS ofgb_on;
-- → 1 (включён) или 0 (выключен)

-- Проверить отсутствие устаревших режимов
SELECT @@sql_mode LIKE '%NO_AUTO_CREATE_USER%';
-- → 0 (режим удалён в 8.0.11)
```

Для проверки поведения приложения используйте сценарий 7 — `sys.statements_with_errors_or_warnings`
показывает, какие запросы генерируют ошибки при включённом строгом режиме.

**Критерии успешной валидации:**
- `@@GLOBAL.sql_mode` и `@@SESSION.sql_mode` совпадают (или сессионное значение оправдано
  Intent-настройкой приложения).
- В строке `sql_mode` нет устаревших или удалённых режимов.
- Регрессионные тесты проходят без ошибок 3065, 1292, 1366, 1264.

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `ERROR 3065` ... `incompatible with sql_mode=ONLY_FULL_GROUP_BY` | Запрос не соответствует строгим правилам `GROUP BY` | Добавить колонку в `GROUP BY`, `ANY_VALUE()` или исправить запрос; см. сценарий 2 |
| `ERROR 1366: Incorrect ... value` при вставке | Строгий режим; данные не соответствуют типу колонки | Валидация на стороне приложения; найти источник через `sys.statements_with_errors_or_warnings` |
| `ERROR 1292: Incorrect datetime value` | Некорректная дата, частая причина — дата с днём 29–31 в месяце без него | Валидация дат в приложении; не подменять `NO_ZERO_DATE` |
| `ERROR 1264: Out of range value` | Значение не помещается в тип колонки (часто `INT` вместо `BIGINT`) | Расширить тип колонки через `ALTER TABLE ... MODIFY`; см. [Online Schema Change](./Operations/online-schema-change.md) |
| Сервер не стартует: `unknown variable 'sql_mode=...'` | Указан удалённый режим (`DB2`, `ORACLE`, `MYSQL40` и другие) | Удалить режим из `my.cnf`; они удалены в MySQL 8.0.11 |
| Приложение ведёт себя не так, как настроено в `my.cnf` | `sql_mode` переопределён в строке подключения или в коде | Проверить `@@SESSION.sql_mode` именно в сессии приложения |
| `CREATE TABLE` без первичного ключа падает неожиданно | Включён `sql_require_primary_key` | Проверить значение; добавить первичный ключ в таблицу |
| Репликация останавливается на запросах приложения, а на master ошибок нет | На реплике `sql_require_primary_key = ON`, на источнике `OFF` | Согласовать через `REQUIRE_TABLE_PRIMARY_KEY_CHECK` |

## Лучшие практики

- **Задавать `sql_mode` явно в `my.cnf`**, даже когда доверяете дефолту: дефолты менялись
  между версиями, и явное перечисление делает поведение предсказуемым.
- **Не «чинить» приложение отключением строгого режима.** Ослабление режима переносит
  ошибку из момента записи в момент чтения отчёта — туда, где её сложнее исправить.
- **`ANY_VALUE()` вместо отключения `ONLY_FULL_GROUP_BY`.** Явное намерение лучше
  глобальной настройки.
- **Проверять `@@SESSION.sql_mode` в сессии приложения**, а не только глобальное
  значение. Это самая частая причина «невозможного» расхождения поведения.
- **`sql_require_primary_key` включать после аудита таблиц.** Для построчной репликации
  таблица без ключа — реальная проблема, но включать проверку нужно последним шагом.
- **`SET PERSIST` вместо `SET GLOBAL`** для переменных, значение которых должно пережить
  рестарт.

## Дополнительная информация

### Граничные случаи и ограничения

- **Режимы, объявленные устаревшими:** `NO_ZERO_IN_DATE` (эффект вошёл в строгий режим)
  и `PAD_CHAR_TO_FULL_LENGTH` (MySQL 8.0.13). Они работают, но опираться на них не следует.
- **Составные режимы удалены в MySQL 8.0.11.** Попытка указать их в `my.cnf` даёт
  ошибку запуска — частая причина проблем при обновлении с 5.7.
- **`sql_require_primary_key` не является частью `sql_mode`.** Это отдельная переменная со
  своей областью действия и своим уровнем привилегий.
- **`STRICT_ALL_TABLES` делает строгим всё**, включая не транзакционные таблицы; для
  типовой OLTP-конфигурации достаточно `STRICT_TRANS_TABLES`.
- **Хинт `SET_VAR` работает не для всех переменных.** Проверяйте поддержку в документации
  конкретной переменной перед использованием.
- **`char(x) = char(y)` зависит от pad-атрибута collation.** Если в проекте менялась
  collation, поведение сравнения менялось вместе с ней — см.
  [Кодировки и сортировки](./charset-and-collation.md).

### Внешние ресурсы

- [MySQL Reference Manual: Server SQL Modes](https://dev.mysql.com/doc/refman/8.4/en/sql-mode.html)
- [MySQL Reference Manual: MySQL Handling of GROUP BY](https://dev.mysql.com/doc/refman/8.4/en/group-by-handling.html)
- [MySQL 8.0.13 Release Notes: sql_require_primary_key](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-13.html)
- [MySQL 8.0.11 Release Notes: удаление составных режимов](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-11.html)
- [MySQL 8.0.28 Release Notes: sys.list_add / list_drop](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-28.html)
- [MySQL 8.4 FAQ: Server SQL Mode](https://dev.mysql.com/doc/refman/8.4/en/faqs-sql-modes.html)

### Откат и очистка

| Действие | Как отменить | Последствия |
| :--- | :--- | :--- |
| `SET SESSION sql_mode = '...'` | Закрыть соединение или `SET SESSION sql_mode = @@GLOBAL.sql_mode` | Сессионное значение восстанавливается при новом соединении |
| `SET GLOBAL sql_mode = '...'` | `SET GLOBAL sql_mode = <предыдущее значение>` или перезагрузка | Влияет на новые соединения; требует `SYSTEM_VARIABLES_ADMIN` |
| `SET PERSIST sql_mode = '...'` | `SET PERSIST sql_mode = <предыдущее значение>` или `RESET PERSIST` | Переживает рестарт; значение сохраняется в `mysql Innodb_table_stats` |
| `SET PERSIST_ONLY sql_mode = '...'` | `RESET PERSIST ONLY` | Не применяется при старте, только для переживания рестарта |
| `sql_require_primary_key = ON` | `SET PERSIST sql_require_primary_key = OFF` | Разрешает `CREATE TABLE` без PK; отменить можно только вручную |
| `sys.list_add` / `sys.list_drop` | Выполнять обратную операцию или перенастроить | Функции доступны с 8.0.18; не влияют на конфигурацию |
| Хинт `SET_VAR(sql_mode = ...)` | Ничего — хинт действует только на один оператор | Автоматически восстанавливается после выполнения запроса |

**Очистка данных, испорченных нестрогим режимом:**
- Нулевые даты (`0000-00-00`) — заменить на `NULL` или валидную дату через `UPDATE ... SET created_at = NULL WHERE created_at = '0000-00-00'`.
- Обрезанные значения (например, `10.99` вместо `10.999`) — проверить тип колонки и расширить при необходимости.
- Нули в monetary-колонках — провести аудит через `sys.statements_with_errors_or_warnings`.

### См. также

- **[Конфигурация MySQL (my.cnf)](./configuration.md)** — `sql_mode` в конфигурации,
  `SET PERSIST`, валидация, `--validate-config`.
- **[Кодировки и сортировки](./charset-and-collation.md)** — `ANSI_QUOTES`,
  `NO_BACKSLASH_ESCAPES` и pad-атрибуты.
- **[Роли и управление привилегиями](./role_management.md)** — привилегии для изменения
  `sql_mode` и связанных переменных (`SYSTEM_VARIABLES_ADMIN`, `SESSION_VARIABLES_ADMIN`).
- **[Индексы в MySQL](./indexing.md)** — план по индексам после устранения ошибок
  группировки.
- **[Performance Schema и sys schema](./Operations/performance-schema-and-sys.md)** —
  поиск запросов, порождающих ошибки записи (`sys.statements_with_errors_or_warnings`).
- **[Online Schema Change](./Operations/online-schema-change.md)** — изменение типов колонок
  без простаивания.
- **[Безопасные массовые операции с данными](../Concepts/safe_large_scale_data_modification.md)** —
  выборка и исправление испорченных строк батчами.