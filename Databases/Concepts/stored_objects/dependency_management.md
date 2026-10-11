# Управление зависимостями и impact-анализ хранимых объектов

**Актуально для:** PostgreSQL 17/18, MariaDB 10.11/11.4, MySQL 8.4 LTS

## Определения

**Зависимость (dependency)** — зафиксированная в системном каталоге связь между двумя объектами БД, при которой referenced-объект нельзя удалить, не удалив dependent-объект.

**Объект-ссылка (referenced)** — объект, на который указывает зависимость: таблица, тип, другая функция. Удаление ссылающегося объекта тянет за собой зависимый.

**Объект-потребитель (dependent)** — объект, который использует ссылающийся: функция, вызывающая другую функцию; представление, читающее таблицу; триггер, привязанный к таблице.

**Транзитивность** — свойство каскадного удаления: если удаляется A, а B зависит от A, а C зависит от B, то `DROP ... CASCADE` на A удалит и B, и C.

**Impact-анализ (анализ воздействия)** — оценка того, что сломается, если удалить или изменить объект: какие объекты, представления, триггеры, расписания и вызовы приложения на него завязаны.

**Тело-строка (string-literal body)** — определение тела функции как строкового литерала: `AS $$ ... $$` или `AS 'SELECT ...'`. Тело разбирается при первом вызове, а не при создании.

**Тело `BEGIN ATOMIC`** — SQL-стандартная форма тела (`BEGIN ATOMIC ... END`), которая разбирается на этапе определения объекта.

**Висячий объект (dangling routine)** — функция или процедура, которая осталась в каталоге после удаления объекта, на который ссылается её тело. Создание объекта формально успешно, ошибка возникает только при вызове.

## Основные концепции

### Различия движков — главное, что нужно понять до работы

Зависимости хранимых объектов — это **не** общая функция СУБД, а возможность конкретного движка. Разрыв между PostgreSQL и MariaDB/MySQL здесь принципиальный, и он определяет всю операционную процедуру.

| Возможность | PostgreSQL | MariaDB/MySQL |
|---|---|---|
| Каталог зависимостей | `pg_depend` | отсутствует |
| `DROP ... RESTRICT` / `CASCADE` для routines | да, с разбором `DETAIL` | нет |
| Проверка «есть ли зависимости» перед удалением | да | нет |
| Кто вызывает функцию | частично, через `information_schema` (ограничения ниже) | нет |
| Текст определения | `pg_get_functiondef(oid)` | `SHOW CREATE FUNCTION`, `information_schema.ROUTINES.ROUTINE_DEFINITION` |

Практический вывод: **в MariaDB/MySQL impact-анализ перед удалением — ручная операция**, и её нельзя пропустить, потому что СУБД не остановит вас. `DROP FUNCTION` в MariaDB требует только привилегии `ALTER ROUTINE` на объект и не сверяется ни с какими ссылками; удаление проходит, а падение происходит позже — в момент вызова из оставшегося кода.

### PostgreSQL: что и как хранится в `pg_depend`

Каталог `pg_depend` записывает отношения зависимостей между объектами БД именно для того, чтобы команды `DROP` могли найти, что ещё нужно удалить при `CASCADE` или запретить удаление при `RESTRICT`. Одна строка — одна связь:

| Колонка | Смысл |
|---|---|
| `classid`, `objid` | OID зависимого объекта и его каталога (`pg_class.oid`) |
| `objsubid` | Номер колонки для зависимости на колонку; для прочих объектов `0` |
| `refclassid`, `refobjid` | OID ссылающегося объекта и его каталога |
| `refobjsubid` | Номер колонки ссылающегося объекта |
| `deptype` | Семантика связи (см. ниже) |

Универсальное свойство: **запись в `pg_depend` означает, что ссылающийся объект нельзя удалить, не удалив зависимый**. При этом между двумя объектами может быть несколько записей одновременно — они выражают объединение разных семантик.

Тип связи задаёт, кто выживет при каком действии:

- `NORMAL` (`n`) — обычная связь отдельно созданных объектов. Зависимый удаляется независимо; ссылающийся удаляется **только** с `CASCADE`, и тогда зависимый тоже удаляется.
- `AUTO` (`a`) — зависимый удаляется автоматически при удалении ссылающегося, независимо от `RESTRICT` или `CASCADE`. Пример: именованное ограничение относительно таблицы.
- `INTERNAL` (`i`) — зависимый является частью внутренней реализации ссылающегося. Прямой `DROP` зависимого запрещён, сервер предложит удалить ссылающийся. Пример: правило `ON SELECT` представления.
- `PARTITION_PRI` (`P`) / `PARTITION_SEC` (`S`) — зависимости партиционированных объектов; первичная предпочтительна в сообщениях об ошибках.
- `EXTENSION` (`e`) — зависимый является членом расширения, удалить его можно только через `DROP EXTENSION`.
- `AUTO_EXTENSION` (`x`) — объект не входит в расширение, но не может работать без него и удаляется вместе с ним; в отличие от `EXTENSION`, не игнорируется `pg_dump`.

Объекты, созданные при `initdb`, считаются «закреплёнными» (pinned) и не удаляются, поэтому записи `pg_depend` для них не создаются.

### Главное ограничение PostgreSQL: тело-строка не создаёт зависимостей

Это самый важный для эксплуатации факт во всей теме. PostgreSQL отслеживает зависимости, связанные с **внешне видимыми свойствами** функции — типами аргументов и результата, — но **не** зависимости, которые можно узнать только чтением тела.

Документированный пример:

```sql
CREATE TYPE rainbow AS ENUM ('red', 'orange', 'yellow', 'green', 'blue', 'purple');
CREATE TABLE my_colors (color rainbow, note text);

-- Тело-строка: разбирается при вызове, зависимость от my_colors НЕ сохраняется
CREATE FUNCTION get_color_note (rainbow) RETURNS text AS
  'SELECT note FROM my_colors WHERE color = $1'
LANGUAGE SQL;

DROP TABLE my_colors;
-- → DROP TABLE (успешно) — функция get_color_note осталась в каталоге
SELECT get_color_note('red');
-- → ERROR: relation "my_colors" does not exist   (падает только в момент вызова)
```

Тип `rainbow` в аргументе — внешне видимое свойство, поэтому такая зависимость **есть** и `DROP TYPE` требует `CASCADE`. Таблица `my_colors` упомянута только в теле, поэтому её удаление проходит молча.

У этого поведения есть и задокументированная польза: «функция всё ещё в некотором смысле валидна, если таблица отсутствует, — её вызов даст ошибку; создание новой таблицы с тем же именем снова сделает функцию рабочей». Для продакшена это плохая новость: опечатка или `DROP TABLE` оставляет в базе объект, который выглядит исправным в каталоге и взрывается в рантайме.

### Как восстановить отслеживание: тело `BEGIN ATOMIC`

Для функции или процедуры на `LANGUAGE SQL` с телом в SQL-стандартном стиле тело разбирается **на этапе определения**, и все зависимости, распознанные парсером, сохраняются:

```sql
CREATE FUNCTION get_color_note (rainbow) RETURNS text
BEGIN ATOMIC
  SELECT note FROM my_colors WHERE color = $1;
END;
-- Теперь зависимость от my_colors записана

DROP TABLE my_colors;
-- → ERROR: cannot drop table my_colors because other objects depend on it
-- → DETAIL: function get_color_note(rainbow) on schema public depends on table my_colors
-- → HINT: Use DROP ... CASCADE to drop the dependent objects too.
```

Цена перехода, все ограничения задокументированы:

- форма работает **только** для `LANGUAGE SQL`; строковая форма работает для всех языков;
- тело разбирается при создании, строковая — при вызове, поэтому `BEGIN ATOMIC` **не поддерживает** полиморфные типы аргументов и прочие конструкции, не разрешимые на момент определения;
- `BEGIN ATOMIC` лучше соответствует стандарту SQL и другим реализациям.

Практический вывод для стека на PL/pgSQL: **восстановить отслеживание нельзя** — форма доступна только для `LANGUAGE SQL`. Если схема на PL/pgSQL, единственный способ impact-анализа — внешний: поиск по тексту определений, ревью и журналы вызовов.

### Представления `information_schema` для обхода PL/pgSQL

`pg_depend` бессилен для PL/pgSQL, но частичный обзор дают представления стандарта SQL:

- `routine_routine_usage` — функции и процедуры, используемые другой (или той же) функцией или процедурой, в теле SQL или в выражениях значений по умолчанию параметров. Колонки: `specific_schema`, `specific_name` (потребитель) и `routine_schema`, `routine_name` (используемый).
- `routine_table_usage`, `routine_sequence_usage`, `routine_column_usage` — таблицы, последовательности и колонки, используемые routines.
- `view_routine_usage` — routines, используемые в запросе представления.
- `check_constraint_routine_usage` — функции в проверочных ограничениях.

Три ограничения, без которых представление даст ложное «зависимостей нет»:

1. Работает **только для некавырованных SQL-тел** — то есть для `BEGIN ATOMIC`. PL/pgSQL, C, PL/Python не охвачены.
2. Запись появляется, только если используемая функция принадлежит **включённой в текущей сессии роли**. Объекты, принадлежащие неактивным ролям, не видны.
3. Имена обеих сторон приведены к «specific name», то есть с учётом перегрузки по типам аргументов; сравнение с «простым» именем из `pg_proc` не даст совпадения.

### Безопасный просмотр того, что удалит `CASCADE`

Документированный приём: **выполнить `DROP` без `CASCADE` и прочитать `DETAIL`.** Сервер откатывает команду и печатает полный список зависимых объектов. Это безопасный «сухой прогон» — изменить схему он не может.

```sql
-- Цель: понять, что упадёт вместе с таблицей
DROP TABLE my_colors;
-- → ERROR:  cannot drop table my_colors because other objects depend on it
-- → DETAIL:  function get_color_note(rainbow) on schema public depends on table my_colors
-- →         view v_my_colors on schema public depends on table my_colors
-- →         trigger trg_audit on table orders depends on table my_colors
-- → HINT:  Use DROP ... CASCADE to drop the dependent objects too.
```

Понимать `DETAIL` нужно грамотно: `CASCADE` удаляет **зависимые** объекты, а не ссылающиеся на них таблицы. В примере выше каскад удалит все перечисленные объекты — функцию, представление и триггер; сама таблица `orders` останется (если на неё саму ничего не висит) — каскад останавливается там, где сам объект больше от чего-либо не зависит.

### MariaDB/MySQL: зависимостей нет, анализ строится на определениях

В MariaDB/MySQL каталога зависимостей нет, `DROP PROCEDURE`/`DROP FUNCTION` его не проверяет, а представления `information_schema` дают только один узкий срез — `VIEW_ROUTINE_USAGE` (доступно с MySQL 8.0.13): какие **сохранённые функции используются в определениях представлений**. Ни о процедурах, ни о вызовах функция друг друга там ничего нет.

Отсюда рабочий, но ручной набор приёмов:

```sql
-- 1. Тексты всех определений — основной источник для поиска вызовов
SELECT ROUTINE_SCHEMA, ROUTINE_NAME, ROUTINE_TYPE,
       ROUTINE_DEFINITION
FROM information_schema.ROUTINES
WHERE ROUTINE_SCHEMA NOT IN ('mysql', 'sys', 'performance_schema', 'information_schema');
-- → ROUTINE_DEFINITION равен NULL, если у текущего пользователя нет привилегий —
--   это не пустой результат, а потеря доступа; проверяйте права до выводов

-- 2. Кто вызывает функцию из представления (единственный машинный срез)
SELECT TABLE_SCHEMA, TABLE_NAME, SPECIFIC_SCHEMA, SPECIFIC_NAME
FROM information_schema.VIEW_ROUTINE_USAGE
WHERE SPECIFIC_NAME = 'calculate_discount';
-- → mydb | v_discount | mydb | calculate_discount

-- 3. Полное определение целевого объекта
SHOW CREATE FUNCTION mydb.calculate_discount;

-- 4. Есть ли событие или триггер, ссылающийся на объект
SELECT TRIGGER_SCHEMA, TRIGGER_NAME, EVENT_MANIPULATION, EVENT_OBJECT_TABLE
FROM information_schema.TRIGGERS
WHERE ACTION_STATEMENT LIKE '%calculate_discount%';

SELECT EVENT_SCHEMA, EVENT_NAME, STATUS, INTERVAL_VALUE, INTERVAL_FIELD, LAST_EXECUTED
FROM information_schema.EVENTS
WHERE EVENT_DEFINITION LIKE '%calculate_discount%';
-- → LAST_EXECUTED показывает момент СТАРТА последнего выполнения, а не завершения;
--   NULL означает, что событие ещё ни разу не выполнялось
```

Текстовый поиск по `ROUTINE_DEFINITION` даёт ложноположительные совпадения (имя в комментарии или в строке) и пропускает вызовы через динамический SQL — `EXECUTE` из собранной строки. Поэтому такой анализ — первый фильтр, а не доказательство. Второй фильтр — журналы вызовов: для MariaDB/MySQL это Performance Schema.

```sql
-- Кто фактически вызывал объект (данные Performance Schema, сброшенные при рестарте)
SELECT OBJECT_SCHEMA, OBJECT_NAME, COUNT_STAR,
       ROUND(SUM_TIMER_WAIT/1e12, 3) AS total_seconds
FROM performance_schema.events_statements_summary_by_program
WHERE OBJECT_SCHEMA NOT IN ('mysql', 'sys', 'performance_schema', 'information_schema')
GROUP BY OBJECT_SCHEMA, OBJECT_NAME
ORDER BY SUM_TIMER_WAIT DESC
LIMIT 20;
-- → OBJECT_SCHEMA | OBJECT_NAME        | COUNT_STAR | total_seconds
-- → mydb           | calculate_discount |      18422 |        12.481
```

`events_statements_summary_by_program` отражает только то, что выполнялось с момента последнего сброса или рестарта. Ноль строк для объекта означает «не выполнялся в этом окне», а не «не используется»: редкий ночной отчёт или разовая миграция туда не попадут. Планировщик событий также нужно включать явно, иначе его вызовы в статистику не попадают.

### Изменение подписи — это новый объект

В PostgreSQL `CREATE OR REPLACE` не позволяет изменить имя или типы аргументов: попытка приводит к созданию нового, отдельного объекта, а не к замене старого. Следствие для rollout: смена сигнатуры — это `CREATE` нового объекта плюс `DROP` старого, а не «обновление». Именно поэтому изменение сигнатуры ломает все зависимые вызовы сразу, тогда как изменение тела при той же сигнатуре — безопасная операция с точки зрения каталога. Подробно о порядке внедрения: [Управление изменениями хранимых объектов](change_management.md).

## Практические сценарии

#### Предпосылки

Перед сценариями проверьте:

- **Доступ к каталогам:** чтение `pg_catalog` (`pg_depend`, `pg_proc`) и `information_schema` доступно роли `public` по умолчанию; для `pg_get_functiondef` достаточно `USAGE` на схеме объекта.
- **Performance Schema (MariaDB/MySQL):** включён по умолчанию, но сбор статистики по хранимым программам может быть выключен — проверка и включение потребителя описаны в [Мониторинг хранимых объектов](monitoring.md).
- **Планировщик событий:** `event_scheduler = ON`, иначе вызовы из событий не попадут в статистику и impact-анализ даст ложный «не используется».
- **Роль-владелец:** `information_schema` представления об использовании показывают только объекты, принадлежащие включённым в сессии ролям — для полного обзора подключайтесь от роли-владельца.
- **Права на «сухой прогон»:** для тестового `DROP` на staging — владение объектом (PostgreSQL) или `ALTER ROUTINE` (MariaDB/MySQL).

### Сценарий 1: Проверка перед удалением функции в PostgreSQL

Требуется убрать функцию, которая годами накапливала вызовы. Порядок действий, который не ломает production:

```sql
-- Шаг 1. Выяснить, кто на неё ссылается — машинно, где возможно
SELECT specific_schema, specific_name AS caller,
       routine_schema, routine_name AS callee
FROM information_schema.routine_routine_usage
WHERE routine_schema = 'app' AND routine_name = 'get_color_note';
-- → (0 rows) — не означает «не вызывается»: PL/pgSQL-тела не видны этому представлению

-- Шаг 2. Выяснить, не является ли она частью расширения
SELECT d.deptype, d.classid::regclass AS dependent_catalog,
       d.objid, d.refclassid::regclass AS referenced_catalog, d.refobjid
FROM pg_depend d
WHERE d.refclassid = 'pg_proc'::regclass
  AND d.refobjid = 'app.get_color_note(rainbow)'::regprocedure;
-- → deptype = e означает членство в расширении: удалять только через DROP EXTENSION

-- Шаг 3. Сухой прогон удаления
DROP FUNCTION app.get_color_note(rainbow);
-- → ERROR: cannot drop function get_color_note(rainbow) because other objects depend on it
-- → DETAIL: function wrapper_fn() on schema app depends on function get_color_note(rainbow)
```

Шаг 1 пустой, а шаг 3 показал зависимость — это нормальная и ожидаемая ситуация. Значит, зависимость зарегистрирована (тело-объект SQL-стиля), но не попала в `information_schema` представление, например потому, что объект принадлежит неактивной роли.

### Сценарий 2: Инвентаризация перед крупным рефакторингом

Задача — перед заменой пачки функций понять полный blast radius. В PostgreSQL:

```sql
-- Все routines проекта и их владельцы — базовый инвентарь
SELECT n.nspname AS schema,
       p.proname,
       pg_get_function_identity_arguments(p.oid) AS args,
       CASE p.prokind WHEN 'f' THEN 'FUNCTION'
             WHEN 'p' THEN 'PROCEDURE'
             WHEN 'a' THEN 'AGGREGATE'
             WHEN 'w' THEN 'WINDOW FUNCTION' END AS kind,
       pg_get_userbyid(p.proowner) AS owner,
       p.prosecdef AS security_definer,
       p.provolatile,
       pg_get_functiondef(p.oid) AS definition
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'app'
ORDER BY p.proname;
```

Обратите внимание на `pg_get_function_identity_arguments` — именно он даёт «specific name», по которому объект адресуется в сообщениях об ошибках, в `information_schema` представлениях и в `GRANT`/`DROP` по перегруженным именам. Сравнение по «простому» имени для перегруженных функций даёт ложные совпадения.

Для MariaDB/MySQL тот же инвентарь идёт через `information_schema.ROUTINES` плюс `SHOW CREATE`, а зависимости приходится искать текстовым поиском по полученным определениям.

### Сценарий 3: Восстановление зависимостей через `BEGIN ATOMIC`

Если логика объекта умещается в `LANGUAGE SQL` и не использует полиморфные типы, перевод тела в `BEGIN ATOMIC` даёт СУБД возможность защитить вас от висячих объектов в будущем:

```sql
-- Было: тело-строка, зависимости от таблиц не отслеживаются
CREATE OR REPLACE FUNCTION app.get_order_note(p_id INT) RETURNS TEXT AS
$$ SELECT note FROM orders WHERE id = p_id $$
LANGUAGE SQL;

-- Стало: зависимости от orders записываются и защищаются DROP
CREATE OR REPLACE FUNCTION app.get_order_note(p_id INT) RETURNS TEXT
BEGIN ATOMIC
  SELECT note FROM orders WHERE id = p_id;
END;

-- Проверка, что связь видна системе
SELECT pg_get_functiondef('app.get_order_note(int)'::regprocedure);
-- → CREATE OR REPLACE FUNCTION app.get_order_note(p_id integer) RETURNS text
-- →  LANGUAGE sql
-- →  BEGIN ATOMIC
-- →    SELECT note FROM orders WHERE id = p_id;
-- → END;
```

Если логика требует PL/pgSQL, приём неприменим. Тогда защита строится вне СУБД: обязательный шаг теста «удали таблицу, убедись, что тест падает» вместо рассуждения о зависимостях.

### Сценарий 4: Удаление триггера и его функции в правильном порядке

Триггер в PostgreSQL — отдельный объект, связанный с функцией. Удалять их нужно в правильном порядке, иначе получите висячий триггер, который падает на каждой записи в таблицу:

```sql
-- Неправильно: функция удаляется, триггер остаётся
DROP FUNCTION app.audit_changes();
-- → ERROR: cannot drop function audit_changes() because other objects depend on it
-- → DETAIL: trigger trg_orders_audit on table orders depends on function audit_changes()
-- (в этом случае PostgreSQL вас спас — но только если зависимость зарегистрирована)

-- Правильно: сначала триггер, затем функция
DROP TRIGGER trg_orders_audit ON orders;
DROP FUNCTION app.audit_changes();
```

Обратите внимание: зависимость «триггер → функция» регистрируется всегда, потому что она задана ссылкой на объект, а не текстом тела. Именно поэтому этот случай — один из немногих, где `pg_depend` работает и для PL/pgSQL.

## Устранение неполадок

### `DROP ... CASCADE` удалил больше, чем ожидалось

**Симптомы:** после каскадного удаления исчезли триггеры, представления или функции, которые никто не собирался трогать.

**Причина:** каскад рекурсивен и идёт по цепочке зависимых от удаляемого объекта — включая зависимые тех зависимых. `DETAIL` в сообщении об ошибке показывает **прямых** зависимых; их собственные зависимости в списке не перечислены, но тоже будут удалены.

**Решение:** сначала выполните `DROP` без `CASCADE` и разверните цепочку рекурсивно — либо наведите на каждое имя из `DETAIL` тот же запрос. Удаляйте объекты явным списком в правильном порядке: триггеры и представления, затем функции, затем таблицы.

### Функция осталась в каталоге, но падает при вызове

**Симптомы:** `ERROR: relation "..." does not exist` при вызове функции, при этом `DROP TABLE` в журнале прошёл без ошибок.

**Причина:** тело-строка не регистрирует зависимости, либо объект принадлежит неактивной роли и не виден в `information_schema` представлениях.

**Диагностика:**

```sql
-- Тело в SQL-standard форме? Тогда зависимости отслеживаются
SELECT prosqlbody IS NOT NULL AS body_is_atomic,
       pg_get_functiondef('app.audit_changes()'::regprocedure)
FROM pg_proc WHERE oid = 'app.audit_changes()'::regprocedure;
-- → body_is_atomic = t для BEGIN ATOMIC; f для строковых тел
--   (PL/pgSQL, C, SQL AS '...') — зависимостей от тела в pg_depend нет

-- Есть ли записи о зависимостях от pg_class (таблицы)
SELECT d.deptype, d.refobjid::regclass AS referenced
FROM pg_depend d
WHERE d.classid = 'pg_proc'::regclass
  AND d.objid = 'app.audit_changes()'::regprocedure
  AND d.refclassid = 'pg_class'::regclass;
-- → (0 rows) — ожидаемо для PL/pgSQL
```

**Решение:** вернуть таблицу под тем же именем немедленно (восстановить из дампа), затем перевести тело в `BEGIN ATOMIC`, если это `LANGUAGE SQL`, либо добавить в тесты кейс удаления зависимой таблицы.

### `information_schema` показывает пустую зависимость, а объект используется

**Симптомы:** `routine_routine_usage` не возвращает строк, хотя вызовы точно есть.

**Причины, проверяемые по порядку:**
1. Тело — PL/pgSQL или другой не-SQL язык: представление работает только для некавырованных SQL-тел.
2. Используемая функция принадлежит роли, не включённой в текущей сессии — строка просто не попадёт в результат.
3. Вызов происходит через динамический SQL, собранный в строку, — статический разбор его не видит в принципе.

**Решение:** для пунктов 1–2 подключиться от роли-владельца и повторить запрос; для пункта 3 использовать журналы вызовов (`pg_stat_statements` с `track = all`, Performance Schema) как источник фактического использования.

### Не могу удалить функцию: ошибка `cannot drop ... because other objects depend on it`

**Симптомы:** `ERROR` на `DROP FUNCTION`, в `DETAIL` перечислены представления, функции-обёртки или триггеры.

**Причина:** объект действительно используется. Частая ложная тревога — триггер на функции: удаление функции триггером не блокируется, если зависимость не зарегистрирована, но здесь она зарегистрирована.

**Решение:** не добавляйте `CASCADE` «чтобы не тратить время». Прочитайте `DETAIL`, определите, что это за объекты и нужны ли они. Если зависимость ложная (объект не используется) — удалите его явно, затем повторите `DROP` без `CASCADE`.

## Лучшие практики

1. **Перед любым `DROP` в production выполняйте «сухой прогон».** `DROP` без `CASCADE` ничего не меняет, но печатает список последствий. Это дешёвый способ не удивляться.
2. **Избегайте `CASCADE` в production без разбора `DETAIL`.** Каскад рекурсивен, а его полный состав в сообщении не перечислен.
3. **Пишите логику на `LANGUAGE SQL` c `BEGIN ATOMIC`, где это возможно.** Это единственный способ получить от СУБД защиту от висячих объектов.
4. **Относитесь к PL/pgSQL как к коду без зависимостей.** Раз подсказки нет, impact-анализ обязателен: текстовый поиск определений плюс журналы вызовов.
5. **В MariaDB/MySQL внедряйте проверку вызовов в пайплайн.** Механизма зависимостей нет, поэтому единственная защита — дисциплина ревью и обязательный шаг «проверить вызовы перед `DROP`».
6. **Адресуйте объекты по полной сигнатуре.** `app.fn(int, text)`, а не `app.fn` — иначе перегрузки дадут ложные совпадения и в `GRANT`, и в запросах зависимостей.
7. **Не меняйте сигнатуру объекта под нагрузкой.** Смена типов аргументов создаёт новый объект и ломает все вызовы; выносите новую версию под новым именем (см. [Управление изменениями](change_management.md)).
8. **Удаляйте триггер раньше функции.** Зависимость «триггер → функция» СУБД отслеживает всегда, обратная — никогда.
9. **Включайте планировщик событий при снятии статистики.** Иначе вызовы из событий отсутствуют в Performance Schema, и impact-анализ даёт ложный «не используется».

## Дополнительная информация

### См. также

- **[Хранимые объекты: обзор](../stored_objects_overview.md)** — жизненный цикл и общие принципы.
- **[Управление изменениями хранимых объектов](change_management.md)** — версионирование, rollout, откат, расписания.
- **[Мониторинг хранимых объектов](monitoring.md)** — статистика вызовов: `pg_stat_user_functions` и Performance Schema.
- **[Troubleshooting хранимых объектов](troubleshooting.md)** — таймауты, блокировки, рекурсия.
- **[Безопасность хранимых объектов](security.md)** — владелец объекта, `SECURITY DEFINER`, RLS.
- **[Отладка объектов в PostgreSQL](../../PostgreSQL/Concepts/stored_objects_debugging.md)** — профилирование и поиск ошибок.
- **[Управление объектами в MariaDB/MySQL](../../MariaDB/Concepts/stored_objects_management.md)** — Event Scheduler и отладка.

### Внешние источники

- [PostgreSQL 18: 5.15 Dependency Tracking](https://www.postgresql.org/docs/current/ddl-depend.html)
- [PostgreSQL 18: 52.18 pg_depend](https://www.postgresql.org/docs/current/catalog-pg-depend.html)
- [PostgreSQL 18: 35.42 routine_routine_usage](https://www.postgresql.org/docs/18/infoschema-routine-routine-usage.html)
- [PostgreSQL 18: CREATE PROCEDURE](https://www.postgresql.org/docs/current/sql-createprocedure.html)
- [MySQL 8.4: The INFORMATION_SCHEMA VIEW_ROUTINE_USAGE Table](https://dev.mysql.com/doc/refman/8.4/en/information-schema-view-routine-usage-table.html)
- [MariaDB: DROP PROCEDURE](https://mariadb.com/docs/server/server-usage/stored-routines/stored-procedures/drop-procedure)