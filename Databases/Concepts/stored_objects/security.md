# Безопасность хранимых объектов

**Актуально для:** PostgreSQL 17/18, MariaDB 10.11/11.4, MySQL 8.4 LTS

## Определения

**SECURITY DEFINER (PostgreSQL)** — режим выполнения хранимого объекта, при котором он запускается с привилегиями **владельца** функции (пользователя, который её создал), а не вызывающего.

**SECURITY INVOKER (PostgreSQL)** — режим выполнения по умолчанию, при котором хранимый объект запускается с привилегиями **вызывающего** пользователя.

**DEFINER / INVOKER (MariaDB/MySQL)** — аналоги модели PostgreSQL: `DEFINER` указывает пользователя, от имени которого выполняется объект; `INVOKER` — пользователь, который объект вызвал.

**Принцип наименьших привилегий (PoLP)** — предоставление ролям и пользователям только тех прав, которые минимально необходимы для выполнения их функций.

**Динамический SQL** — SQL-запрос, формируемый и выполняемый во время работы хранимого объекта (в отличие от статического SQL, известного на этапе создания). Является источником SQL-инъекций при некорректной обработке параметров.

**SQL-инъекция** — внедрение вредоносного SQL-кода через входные параметры хранимого объекта, что может привести к утечке или модификации данных.

## Основные концепции

### Модель привилегий для хранимых объектов

Хранимые объекты не имеют собственных привилегий — они наследуют права владельца (DEFINER) или вызывающего (INVOKER). Контроль доступа строится на двух уровнях:

1. **Право на выполнение (`EXECUTE`)** — базовое право, без которого объект недоступен для вызова.
2. **Права владельца объекта** — в режиме `SECURITY DEFINER` / `DEFINER` объект наследует все права создателя, что создаёт риск elevation of privileges.

### Контекст выполнения

При вызове хранимого объекта СУБД создаёт контекст выполнения, включающий:
- **Идентификатор владельца** — определяет набор привилегий в режиме `SECURITY DEFINER`.
- **Идентификатор вызывающего** — используется в режиме `SECURITY INVOKER` для проверки прав.
- **Транзакционный контекст** — хранимый объект выполняется в рамках транзакции вызывающего сеанса.
- **Поисковый путь (`search_path`)** — определяет порядок разрешения имён объектов в PostgreSQL.

### Риски SECURITY DEFINER

Режим `SECURITY DEFINER` необходим для инкапсуляции сложной логики с привилегиями владельца, но несёт риски:

- **Elevation of Privileges:** Если владелец — суперпользователь (`postgres`, `root`), любой пользователь с правом `EXECUTE` получает доступ ко всем операциям от имени суперпользователя.
- **Неявный доверенный круг:** Объект, созданный много лет назад суперпользователем, продолжает работать с его привилегиями даже после смены владельца базы.
- **Сложность аудита:** Отследить, какие пользователи фактически используют привилегии definer, сложнее, чем при явном `GRANT`.

### Захват поискового пути (search_path hijacking)

Отдельный риск, не сводимый к elevation of privileges, и именно он чаще всего остаётся незамеченным.

Механика: имя объекта без схемы разрешается по `search_path` в порядке перечисления. Если в начало пути попадёт схема, в которой вызывающий пользователь может создавать объекты, то он подменит нужный объект своим — и выполнит ваш `SECURITY DEFINER`-код от имени привилегированного владельца.

Почему путь по умолчанию уязвим. Типовое значение — `"$user", public`. Схема `$user` указывает на схему с именем текущего пользователя: если у вызывающего есть право `CREATE` в базе, он создаёт в ней объект с тем же именем, что и внутренне используемый в функции, и он будет выбран раньше `public`. Вторая составляющая — временные объекты: если `pg_temp` не закреплён последним в пути, неявно создаваемые временные таблицы тоже попадают в зону подмены.

```sql
-- Проверить текущий путь
SHOW search_path;
-- → "$user", public
```

Три штатные меры, и они не взаимозаменяемы:

1. **Пустой путь с явным префиксом системной схемы.** Внутри функции объявьте `SET search_path = ''` — это запрещает любые неявные разрешения имён. Всё, что осталось, должно быть адресовано полностью: `pg_catalog.count(*)`, `pg_catalog.now()`. Начиная с PostgreSQL 15 `pg_catalog` подставляется неявно, но полное имя всё равно надёжнее.
2. **Закрепление `pg_temp` последним.** Если путь непустой, `pg_temp` должен стоять последним элементом — иначе временная таблица вызывающего перехватит разрешение.
3. **Адресуйте объекты по полной схеме.** `app.audit_log` вместо `audit_log` — независимо от того, что стоит в пути.

Механизм применяется на уровне объекта, то есть не требует правки каждого вызова:

```sql
CREATE FUNCTION app.get_customer(p_id INT) RETURNS SETOF customers
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, app
AS $$
BEGIN
  RETURN QUERY SELECT * FROM app.customers WHERE id = p_id;
END;
$$;

-- Проверка: что фактически закреплено на объекте
SELECT prosecdef, proconfig
FROM pg_proc
WHERE proname = 'get_customer';
-- → prosecdef | proconfig
-- → ---------+-------------------------------------------
-- → t        | {search_path=pg_catalog, app}
```

Привилегированный `SET search_path` выполняется один раз при вызове и после этого не может быть переопределён вложенными вызовами — вложенная `SECURITY DEFINER`-функция, вызванная из функции с закреплённым путём, наследует его. Это делает закрепление на объекте устойчивым, тогда как `SET LOCAL` внутри тела действует только до конца текущей транзакции.

Требование к владельцу дополняет меры: `SECURITY DEFINER`-функция должна принадлежать непривилегированной роли, а её владелец не должен иметь права `CREATE` в публикуемой схеме. Иначе закрепление пути не помогает — перехватить можно и через `pg_temp`, если владелец способен в неё писать. Разбор этого разделения: [Управление ролями и привилегиями в PostgreSQL](../../PostgreSQL/Operations/role_management.md).

### Практические ограничения

- В PostgreSQL `SECURITY DEFINER` поддерживается и для функций, и для процедур — в `CREATE PROCEDURE` присутствует `[ EXTERNAL ] SECURITY INVOKER | [ EXTERNAL ] SECURITY DEFINER`. Ограничение другое: процедура с `SECURITY DEFINER` не может выполнять управление транзакциями (`COMMIT`/`ROLLBACK`).
- В MariaDB/MySQL `DEFINER` должен существовать в системе пользователей; при удалении definer-пользователя объект становится нерабочим.
- Триггеры всегда выполняются в контексте вызвавшей транзакции и не поддерживают отдельный режим DEFINER/INVOKER.

### Взаимодействие с Row-Level Security

RLS и `SECURITY DEFINER` взаимодействуют так, что логика, написанная безопасно «в вакууме», начинает обходить политики. Механика по документации PostgreSQL:

- Выражения политик вычисляются как часть запроса **с привилегиями пользователя, выполняющего запрос**. Обходной путь один: security-definer функция позволяет обратиться к данным, недоступным вызывающему.
- **Владелец таблицы обычно не подпадает под политики**, суперпользователи и роли с атрибутом `BYPASSRLS` обходят RLS всегда. Владелец может подчинить себя политикам через `ALTER TABLE ... FORCE ROW LEVEL SECURITY`.

Отсюда следует главный инцидент этого класса: внутри `SECURITY DEFINER`-функции «пользователь, выполняющий запрос» — это владелец функции. Если он же владеет таблицей (а это естественный результат `CREATE FUNCTION`, сделанного владельцем схемы), то политики RLS **не применяются вообще**, и роль, которой политика оставляла только собственные строки, через эту функцию получает все строки. Политика при этом остаётся в схеме и выглядит работающей — `SELECT` из таблицы напрямую фильтрует корректно.

Практические требования к такому объекту:

1. **Владелец функции не должен быть владельцем таблицы и не должен иметь `BYPASSRLS`.** Дайте отдельной роли только те права на таблицу, которые нужны объекту (`SELECT`, `INSERT`, `UPDATE`).
2. **Если владелец функции обязан совпадать с владельцем таблицы** (например, роль уже занята), включите `ALTER TABLE ... FORCE ROW LEVEL SECURITY` — иначе привилегии роли на саму таблицу обесценят политики.
3. **Не опирайтесь на `current_user` как на идентификатор вызывающего.** Внутри `SECURITY DEFINER`-функции `current_user` — владелец функции. Разделение по пользователю или тенанту передавайте параметром (после проверки прав приложением) либо через переменную сессии, на которую ссылается политика; политика с подзапросом к `users` по `current_user` внутри такой функции вернёт данные владельца функции.
4. **Явно тестируйте поведение, а не наличие политики.** Проверка через `SET ROLE` обязательна: смена роли не меняет владельца функции, поэтому только она покажет реальную видимость строк.

Для представлений та же семантика снимается штатно: с PostgreSQL 15 представление можно переключить на invoker-права — `CREATE VIEW v WITH (security_invoker = true) AS ...`. У функций такого параметра нет, поэтому разделение прав ложится на схему владения и на параметры. Отдельно учитывайте ограничение загрузки: `COPY FROM` не поддерживается для таблиц с включённым RLS — для загрузки в такую таблицу используйте `INSERT`. Механика RLS целиком: [Безопасность PostgreSQL](../../PostgreSQL/Concepts/security_and_encryption.md).

## Практические сценарии

### PostgreSQL: Изоляция приложения через роли и хранимые объекты

Создайте роль приложения без прямого доступа к таблицам. Доступ к данным — только через хранимые объекты:

```sql
-- 1. Создание роли приложения (NOLOGIN — вход только через внешний сервис)
CREATE ROLE app_role NOLOGIN;

-- 2. Запрет прямого доступа к таблицам
REVOKE ALL ON orders FROM app_role;
REVOKE ALL ON customers FROM app_role;

-- 3. Создание хранимых объектов от имени владельца
CREATE FUNCTION get_order_total(p_id INT)
RETURNS NUMERIC
LANGUAGE sql
SECURITY INVOKER  -- ← привилегии вызывающего (app_role)
AS $$ SELECT total FROM orders WHERE id = p_id; $$;

-- 4. Предоставление права только на выполнение
GRANT EXECUTE ON FUNCTION get_order_total(INT) TO app_role;
```

### PostgreSQL: Безопасный DEFINER с минимальными привилегиями

Если логика требует прав владельца, создайте выделенного пользователя с минимально необходимыми правами:

```sql
-- 1. Создание выделенного пользователя для definer
CREATE ROLE api_definer NOLOGIN;

-- 2. Предоставление только необходимых прав
GRANT SELECT, INSERT ON audit_log TO api_definer;

-- 3. Создание функции от имени api_definer
SET ROLE api_definer;
CREATE OR REPLACE FUNCTION log_api_call(p_user TEXT, p_action TEXT)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER  -- ← выполняется от имени api_definer, не postgres
AS $$
BEGIN
    INSERT INTO audit_log (user_name, action, created_at)
    VALUES (p_user, p_action, NOW());
END;
$$;
RESET ROLE;

-- 4. Предоставление права на выполнение приложению
GRANT EXECUTE ON FUNCTION log_api_call(TEXT, TEXT) TO app_role;
```

### MariaDB/MySQL: Изоляция через DEFINTER с минимальными привилегиями

```sql
-- 1. Создание технического пользователя для definer
CREATE USER 'definer_user'@'localhost' IDENTIFIED BY 'strong_password';

-- 2. Предоставление только необходимых прав
GRANT SELECT, INSERT ON mydb.audit_log TO 'definer_user'@'localhost';

-- 3. Создание хранимого объекта с указанием definer
DELIMITER //
CREATE DEFINER = 'definer_user'@'localhost'
FUNCTION calculate_discount(p_user_id INT)
RETURNS DECIMAL(5,2)
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_discount DECIMAL(5,2);
    SELECT discount INTO v_discount FROM user_discounts WHERE user_id = p_user_id;
    RETURN v_discount;
END //
DELIMITER ;

-- 4. Создание пользователя приложения
CREATE USER 'app_user'@'%' IDENTIFIED BY 'strong_password';

-- 5. Запрет прямого доступа к таблицам
REVOKE ALL PRIVILEGES ON mydb.* FROM 'app_user'@'%';

-- 6. Разрешение только выполнение функции
GRANT EXECUTE ON FUNCTION mydb.calculate_discount TO 'app_user'@'%';

FLUSH PRIVILEGES;
```

### PostgreSQL: закрытый контур доступа через хранимые объекты

Комплексный сценарий, собирающий четыре меры в одну схему: привилегированный владелец, явный `search_path`, снятый грант `PUBLIC` и `ALTER DEFAULT PRIVILEGES`, чтобы новые объекты не вернули дыру.

**Исходная проблема:** приложение подключается ролью `app_user` и должно работать только через три функции. Реальная конфигурация по умолчанию даёт три утечки: `EXECUTE` на каждую новую функцию достаётся `PUBLIC`, `search_path` оставляет перехват имени через схему `$user`, а владельцем функции часто становится суперпользователь.

```sql
-- 1. Отдельный владелец объектов — не суперпользователь, не владелец таблиц
CREATE ROLE app_owner NOLOGIN;
CREATE ROLE app_user  NOLOGIN;

-- 2. Схема приложения: владелец отдельный, CREATE для роли приложения закрыт
CREATE SCHEMA app AUTHORIZATION app_owner;
REVOKE CREATE ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO app_role;
GRANT USAGE ON SCHEMA app TO app_user;

-- 3. Запрет CREATE в public — убирает второй вектор подмены через "$user"/public
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- 4. Функция: привилегированный владелец + закреплённый search_path
CREATE FUNCTION app.get_customer(p_id INT) RETURNS SETOF app.customers
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, app
AS $$
BEGIN
  RETURN QUERY SELECT * FROM app.customers WHERE id = p_id;
END;
$$;

ALTER FUNCTION app.get_customer(INT) OWNER TO app_owner;

-- 5. Права выдаются роли, не пользователю
GRANT EXECUTE ON FUNCTION app.get_customer(INT) TO app_role;
GRANT app_role TO app_user;

-- 6. Снятие неявного доступа у PUBLIC
REVOKE EXECUTE ON FUNCTION app.get_customer(INT) FROM PUBLIC;

-- 7. Тот же режим для всех будущих объектов — выполняется ролью-мигратором
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
  REVOKE EXECUTE ON PROCEDURES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
  GRANT EXECUTE ON FUNCTIONS TO app_role;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
  GRANT EXECUTE ON PROCEDURES TO app_role;
```

**Валидация — по поведению, а не по каталогу:**

```sql
-- Закреплён ли search_path и является ли объект DEFINER
SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner)
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'app' AND p.proname = 'get_customer';
-- → prosecdef | proconfig                     | owner
-- → t        | {search_path=pg_catalog, app}  | app_owner

-- Остались ли объекты с грантом PUBLIC
SELECT n.nspname, p.proname
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.proacl IS NULL
  AND n.nspname NOT IN ('pg_catalog', 'information_schema');
-- → (0 rows) — умолчания не действуют ни на один объект
```

Проверка прав на вызов должна идти от имени роли, а не суперпользователя: `SET ROLE app_user` внутри `SECURITY DEFINER`-функции не меняет её владельца, поэтому проверка покажет реальную картину только из отдельного соединения с правами `app_user`.

### Динамический SQL: защита от инъекций

**PostgreSQL (PL/pgSQL):**

```sql
-- ОПАСНО: прямая конкатенация строк
CREATE OR REPLACE FUNCTION unsafe_search(p_name TEXT)
RETURNS TABLE(id INT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY EXECUTE 'SELECT id FROM users WHERE name = ''' || p_name || '''';
    -- Инъекция: p_name = "'; DROP TABLE users; --"
END;
$$;

-- Безопасно: параметризованный запрос с USING
CREATE OR REPLACE FUNCTION safe_search(p_name TEXT)
RETURNS TABLE(id INT, name TEXT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY EXECUTE
        'SELECT id, name FROM users WHERE name = $1'
        USING p_name;  -- ← автоматическое экранирование
END;
$$;

-- Безопасно: форматирование идентификаторов через %I
CREATE OR REPLACE FUNCTION search_any(p_table TEXT, p_name TEXT)
RETURNS TABLE(id INT, name TEXT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY EXECUTE
        'SELECT id, name FROM ' || format('%I', p_table) || ' WHERE name = $1'
        USING p_name;
END;
$$;
```

**MariaDB/MySQL:**

```sql
-- Безопасно: prepared statement с параметрами
DELIMITER //
CREATE PROCEDURE safe_search(IN p_name VARCHAR(100))
BEGIN
    SET @sql = 'SELECT id, name FROM users WHERE name = ?';
    SET @p = p_name;
    PREPARE stmt FROM @sql;
    EXECUTE stmt USING @p;
    DEALLOCATE PREPARE stmt;
END //
DELIMITER ;

-- ОПАСНО: прямая подстановка
DELIMITER //
CREATE PROCEDURE unsafe_search(IN p_name VARCHAR(100))
BEGIN
    SET @sql = CONCAT('SELECT id FROM users WHERE name = ''', p_name, '''');
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
END //
DELIMITER ;
```

## Валидация и проверка

### Проверка модели привилегий (PostgreSQL)

```sql
-- Список привилегий на хранимые объекты
SELECT grantee, routine_name, routine_type, privilege_type
FROM information_schema.role_routine_grants
WHERE routine_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY grantee, routine_name;
-- → grantee | routine_name | routine_type | privilege_type
-- → app_role| get_order_total| FUNCTION     | EXECUTE

-- Проверка отсутствия прямых GRANT пользователям (все должны быть через роли)
-- ВНИМАНИЕ: этот запрос не видит грант роли PUBLIC — см. следующий блок
SELECT DISTINCT grantee
FROM information_schema.role_routine_grants
WHERE grantee NOT IN (SELECT rolname FROM pg_roles WHERE rolcanlogin = false);
-- → (ожидается пустой результат или только технические роли)
```

**Проверка невидимого по умолчанию гранта `PUBLIC`.** Предыдущая проверка даёт ложное «всё чисто», если функция доступна через `PUBLIC`. PostgreSQL выдаёт `EXECUTE` на новые функции и процедуры роли `PUBLIC` автоматически — то есть каждому, кто может выполнить `CONNECT` к базе. При этом `PUBLIC` в `pg_roles` выглядит как роль, но `rolcanlogin` у неё истинно и имя начинается с непечатного символа, поэтому фильтр `rolcanlogin = false` этот грант отсекает.

```sql
-- Полный аудит: два разных состояния означают грант EXECUTE для PUBLIC
--
-- (a) proacl IS NULL — действуют умолчания PostgreSQL, то есть EXECUTE для PUBLIC.
--     aclexplode() здесь вернёт 0 строк, поэтому этот случай ловится отдельно.
SELECT n.nspname AS schema,
       p.proname AS object_name,
       CASE p.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END AS object_type,
       'proacl IS NULL (умолчания)' AS public_state
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.proacl IS NULL
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')

UNION ALL

-- (b) proacl задан явно и содержит грант псевдороли PUBLIC (aclexplode
--     представляет её как grantee = 0)
SELECT n.nspname,
       p.proname,
       CASE p.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END,
       'явный грант PUBLIC'
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
CROSS JOIN LATERAL aclexplode(p.proacl) acl
WHERE acl.grantee = 0
  AND acl.privilege_type = 'EXECUTE'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')

ORDER BY 1, 2;
-- → schema | object_name   | object_type | public_state
-- → public | get_order_total | FUNCTION    | proacl IS NULL (умолчания)
-- → public | delete_all      | PROCEDURE   | явный грант PUBLIC
```

Различить состояния важно, потому что они выглядят одинаково, но означают разное. Пустой непустой массив `{}` (после снятия всех грантов) — это **не** грант `PUBLIC`: при нём прав нет ни у кого, включая владельца, который при этом сохраняет полные права неявно. Ошибочное прочтение `{}` как «дефолта» приводит к ложной тревоге, а пропуск `NULL` — к ложному «всё чисто».

Обратная сторона того же механизма: приведённая выше проверка «нет прямых грантов пользователям» в реальности всегда пуста — каждый объект имеет как минимум грант `PUBLIC`. Отсутствие `proacl` (`NULL`) означает «используются умолчания PostgreSQL», то есть набор включает `EXECUTE` для `PUBLIC`. Именно этот случай, а не пустой `proacl`, требует внимания.

**Снятие гранта `PUBLIC` и замена явными ролями:**

```sql
-- 1. Снять EXECUTE у PUBLIC у конкретного объекта
REVOKE EXECUTE ON FUNCTION app.get_order_total(int) FROM PUBLIC;
-- либо сразу на все функции и процедуры схемы одной командой:
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC;
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA app FROM PUBLIC;

-- 2. Выдать право только той роли, которой оно нужно
GRANT EXECUTE ON FUNCTION app.get_order_total(int) TO app_role;

-- 3. То же для будущих объектов — без этого шага каждый новый объект
--    снова получит грант PUBLIC при создании
ALTER DEFAULT PRIVILEGES IN SCHEMA app
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
  REVOKE EXECUTE ON PROCEDURES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
  GRANT EXECUTE ON FUNCTIONS TO app_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
  GRANT EXECUTE ON PROCEDURES TO app_role;

-- 4. Валидация: снятый грант виден как proacl без '=X/'
SELECT proname, proacl FROM pg_proc
WHERE pronamespace = 'app'::regnamespace AND proname = 'get_order_total';
-- → proname | proacl
-- → --------+-----------------------
-- → get_order_total | {app_role=X/app_role}
```

Шаг 3 — то, что отсутствует у аудита без него: `REVOKE` на существующем объекте не влияет на объекты, созданные позже, и они снова получат `EXECUTE` для `PUBLIC` при следующем деплое. `ALTER DEFAULT PRIVILEGES` действует только на объекты, созданные **после** выполнения команды, и только от имени её исполнителя — то есть её должен выполнить создатель объектов (миграционная роль), иначе правило не применится к их творениям. Разбор ролевой модели и привилегий: [Управление ролями и привилегиями в PostgreSQL](../../PostgreSQL/Operations/role_management.md).

### Проверка SECURITY DEFINER объектов (PostgreSQL)

```sql
-- Поиск всех DEFINER-объектов с владельцем-суперпользователем
SELECT n.nspname AS schema,
       p.proname AS function_name,
       pg_get_userbyid(p.proowner) AS owner,
       p.prosecdef AS security_definer
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.prosecdef = true
  AND pg_get_userbyid(p.proowner) IN ('postgres', 'root')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema');
-- → schema | function_name | owner  | security_definer
-- → public | drop_temp     | postgres| true            -- ОПАСНО
```

### Проверка DEFINER-объектов, обходящих RLS (PostgreSQL)

Эвристическое сканирование по совпадению схемы: находит DEFINER-функции, владелец которых — владелец RLS-таблицы из той же схемы. Это **не** разбор зависимостей: для тела-строки PostgreSQL такие связи не хранит вовсе (см. [Управление зависимостями и impact-анализ](dependency_management.md)), поэтому для PL/pgSQL другого способа нет.

```sql
SELECT n.nspname AS schema,
       p.proname AS function_name,
       pg_get_userbyid(p.proowner) AS function_owner,
       t.relname AS rls_table,
       t.relforcerowsecurity AS force_rls
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_class t ON t.relnamespace = n.oid
WHERE p.prosecdef
  AND t.relrowsecurity
  AND t.relowner = p.proowner
  AND t.relkind = 'r'
ORDER BY 1, 2, 4;
-- → schema | function_name | function_owner | rls_table  | force_rls
-- → public | get_my_orders | app_owner      | orders     | f           -- ОПАСНО: политики не применяются

-- Суперпользователи и BYPASSRLS-роли обходят RLS всегда — их функции опасны на любой RLS-таблице
SELECT rolname, rolbypassrls, rolsuper
FROM pg_roles
WHERE rolbypassrls OR rolsuper;
-- → rolname   | rolbypassrls | rolsuper
-- → postgres  | t            | t
```

Проверка фактической видимости (единственный способ убедиться, что политика работает) — через смену роли:

```sql
SET ROLE app_user;
SELECT count(*) FROM orders;                     -- отфильтровано политикой
SELECT count(*) FROM get_my_orders('42');        -- может вернуть все строки, если владелец функции обходит RLS
RESET ROLE;
```

### Проверка DEFINER объектов (MariaDB/MySQL)

```sql
-- Поиск объектов с definer = root
SELECT ROUTINE_SCHEMA,
       ROUTINE_NAME,
       ROUTINE_TYPE,
       DEFINER
FROM information_schema.routines
WHERE DEFINER LIKE 'root%'
   OR DEFINER LIKE '%@%';  -- любые definer, требующие аудита
-- → ROUTINE_SCHEMA | ROUTINE_NAME | ROUTINE_TYPE | DEFINER
-- → mydb           | calc_total   | FUNCTION      | root@localhost

-- Проверка существования definer-пользователей
SELECT ROUTINE_NAME,
       DEFINER
FROM information_schema.routines
WHERE DEFINER NOT IN (
    SELECT CONCAT(User, '@', Host)
    FROM mysql.user
);
-- → ROUTINE_NAME | DEFINER
-- → orphan_routine| deleted_user@localhost  -- ОПАСНО: definer удалён
```

### Проверка динамического SQL на инъекции

```sql
-- PostgreSQL: поиск опасных паттернов в исходниках
SELECT n.nspname, p.proname, pg_get_functiondef(p.oid)
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE pg_get_functiondef(p.oid) ILIKE '%''%''%'
   OR pg_get_functiondef(p.oid) ILIKE '%execute%format%';
-- Изучите вывод вручную на предмет конкатенации параметров
```

### Проверка прав на схему (PostgreSQL)

```sql
-- Список схем, доступных для роли
SELECT n.nspname AS schema,
       has_schema_privilege('app_role', n.nspname, 'USAGE') AS has_usage,
       has_schema_privilege('app_role', n.nspname, 'CREATE') AS has_create
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast');
-- → schema  | has_usage | has_create
-- → public  | t         | f
-- → app_data| t         | f
```

## Устранение неполадок

### Проблема: DEFINER-объект работает от имени суперпользователя

**Симптомы:** Объект может читать/изменять данные из таблиц, к которым вызывающий пользователь не имеет доступа.

**Причина:** Объект создан с `SECURITY DEFINER` от имени суперпользователя (`postgres`, `root`).

**Решение:**
1. Создайте выделенного пользователя с минимально необходимыми привилегиями.
2. Пересоздайте объект от имени выделенного пользователя.
3. Проверьте владельца: `\df+ function_name` (PostgreSQL) или `SHOW CREATE FUNCTION` (MariaDB).

### Проблема: Definer-пользователь удалён из системы

**Симптомы:** Вызов объекта завершается ошибкой `definer does not exist` или `SQLSTATE 42000`.

**Причина:** Пользователь, указанный в `DEFINER`, был удалён из `mysql.user` или `pg_roles`.

**Решение:**
```sql
-- MariaDB/MySQL: пересоздание объекта с существующим definer
ALTER DEFINER = 'definer_user'@'localhost'
FUNCTION mydb.calculate_discount() ...
```

### Проблема: объект в схеме `public` доступен всем без явного GRANT

**Симптомы:** аудит показывает, что прямых `GRANT` пользователям нет, однако `SELECT` из функции работает от имени любого пользователя с `CONNECT` к базе.

**Причина:** PostgreSQL выдаёт `EXECUTE` на каждую новую функцию и процедуру роли `PUBLIC` автоматически. Проверка через `information_schema.role_routine_grants` с фильтром `rolcanlogin = false` этот грант не видит: `PUBLIC` — псевдосъёмка с `rolcanlogin = true`, и её имя начинается с непечатного символа. Проверка «нет прямых грантов» поэтому всегда возвращает пустой результат и создаёт ложное чувство защищённости.

**Диагностика:**

```sql
-- Что именно закреплено на объекте: NULL = умолчания (PUBLIC имеет EXECUTE)
SELECT n.nspname, p.proname, p.proacl
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.prokind = 'f';
-- → nspname | proname        | proacl
-- → public  | get_order_total|
-- → public  | delete_all     | {=X/app_role}
```

**Решение:** `REVOKE EXECUTE ON FUNCTION ... FROM PUBLIC` на существующих объектах, плюс `ALTER DEFAULT PRIVILEGES ... REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC` — иначе следующий деплой вернёт грант на новые объекты. Полный разбор: раздел «Проверка невидимого по умолчанию гранта `PUBLIC`».

### Проблема: `SECURITY DEFINER`-функция возвращает данные, недоступные вызывающему

**Симптомы:** роль, которой политика RLS оставляла только собственные строки, через функцию видит все строки таблицы. При этом прямой `SELECT` из таблицы фильтрует корректно.

**Причина:** внутри `SECURITY DEFINER`-функции «пользователь, выполняющий запрос» — это владелец функции. Если он же владеет таблицей, политики RLS не применяются вовсе. Вторая возможная причина — подмена объекта через небезопасный `search_path`: вызывающий создаёт объект с тем же именем в своей схеме, и он разрешается раньше, чем объект в `app`.

**Диагностика:**

```sql
-- 1. Владелец функции не должен совпадать с владельцем RLS-таблицы
SELECT p.proname AS function_name,
       pg_get_userbyid(p.proowner) AS fn_owner,
       t.relname AS rls_table,
       pg_get_userbyid(t.relowner) AS table_owner,
       t.relforcerowsecurity AS force_rls
FROM pg_proc p
JOIN pg_depend d
  ON d.classid = 'pg_proc'::regclass
 AND d.objid = p.oid
 AND d.deptype IN ('n', 'a')
JOIN pg_class t ON t.oid = d.refobjid AND t.relkind = 'r'
WHERE p.prosecdef
  AND t.relrowsecurity
  AND t.relowner = p.proowner;
-- → fn_owner = table_owner — политики не действуют

-- 2. Проверить, закреплён ли search_path на объекте
SELECT proname, proconfig FROM pg_proc
WHERE pronamespace = 'public'::regnamespace AND prosecdef;
-- → proconfig NULL — действует путь по умолчанию, подмена имени возможна
```

**Решение:** выделить непривилегированного владельца функции, отличного от владельца таблицы; при невозможности разделения включить `ALTER TABLE ... FORCE ROW LEVEL SECURITY`; закрепить `SET search_path = pg_catalog, app` на объекте. Подробно: раздел «Взаимодействие с Row-Level Security» и «Захват поискового пути».

### Проблема: SQL-инъекция через динамический SQL

**Симптомы:** Неожиданное поведение при передаче специальных символов в параметры.

**Причина:** Прямая конкатенация параметров в строку запроса без экранирования.

**Решение:**
- PostgreSQL: используйте `USING` для параметров, `format('%I')` для идентификаторов.
- MariaDB/MySQL: используйте `PREPARE` / `EXECUTE` с `USING`.

### Проблема: Утечка секретов в теле хранимого объекта

**Симптомы:** В исходном коде объекта видны пароли, API-ключи, токены.

**Причина:** Разработчик сохранил секреты прямо в теле функции/процедуры.

**Решение:**
1. Вынесите секреты во внешний vault. Выбор зависит от размещения: в облаке — AWS Secrets Manager, Azure Key Vault, GCP Secret Manager; в on-prem — HashiCorp Vault или его аналог. Ключевое требование — секрет не должен попадать в тело объекта ни при каком виде дампа.
2. Получайте секреты через вызов к vault из приложения, а не из хранимого объекта.
3. Проверьте все объекты: `SELECT routine_name, routine_definition FROM information_schema.routines WHERE routine_definition LIKE '%password%';`

Оговорка про MariaDB: `information_schema.ROUTINES.ROUTINE_DEFINITION` заполняется не для всех routine — в частности, тело функции MariaDB скрыто от непривилегированного пользователя, если у него нет `SHOW ROUTINE`-привилегии или прав на саму функцию. Поэтому такой поиск находит не всё; для полного аудита проходите по `SHOW CREATE` для каждого объекта, а не только по `information_schema`.

## Лучшие практики

1. **Всегда используйте `SECURITY INVOKER` по умолчанию.** Переключайтесь на `SECURITY DEFINER` / `DEFINER` только когда логика объективно требует прав владельца.
2. **Создавайте отдельного пользователя для definer.** Никогда не используйте суперпользователя (`postgres`, `root`) в качестве definer. Создайте роль с минимально необходимыми привилегиями.
3. **Группируйте права через роли.** Не выдавайте `EXECUTE` напрямую пользователям. Используйте роли: `GRANT EXECUTE ON ... TO app_role; GRANT app_role TO app_user;`.
4. **Аудит definer-объектов регулярно.** Раз в квартал запускайте скрипт, который ищет объекты с definer-пользователями, не входящими в актуальный список.
5. **Экранируйте все параметры в динамическом SQL.** Никогда не конкатенируйте входные параметры напрямую в строку запроса. Используйте параметризованные запросы (`USING`) или форматирование идентификаторов (`format('%I')`).
6. **Не храните секреты в объектах.** Пароли, ключи API, токены — во внешних vault-сервисах. Хранимые объекты — не место для секретов.
7. **Версионируйте хранимые объекты в Git.** Используйте инструменты миграций (Atlas, Sqitch, Liquibase) для деплоя. Никогда не изменяйте объекты напрямую в production.
8. **Устанавливайте таймауты.** В PostgreSQL: `SET LOCAL statement_timeout = '5s';` внутри процедуры. В MariaDB: `SET STATEMENT max_statement_time=5 FOR ...` либо `SET max_statement_time = 5;` (единицы — секунды). В MySQL: `SET MAX_EXECUTION_TIME = 5000;` (единицы — миллисекунды). Переменная `max_execution_time` существует только в MySQL: MariaDB её переименовала в `max_statement_time`, и попытка установить её в MariaDB завершается ошибкой. Это предотвращает зависание сессий.
9. **Логируйте вызовы критичных процедур.** Используйте `RAISE LOG` (PostgreSQL) или таблицу логов (MariaDB) для аудита вызовов процедур, изменяющих данные.
10. **Тестируйте права в изолированной среде.** Перед деплоем проверьте, что приложение может выполнить только разрешённые операции.
11. **Снимайте `EXECUTE` у `PUBLIC` явно.** PostgreSQL выдаёт его на каждую новую функцию и процедуру автоматически. Сделайте `REVOKE ... FROM PUBLIC` частью шаблона создания объекта, а не разовым исправлением.
12. **Закрепляйте `search_path` на каждом `SECURITY DEFINER`-объекте.** Путь по умолчанию `"$user", public` позволяет вызывающему подменить объект через схему с правом `CREATE`. Используйте `SET search_path = pg_catalog, app` (или `= ''` с полными именами) на уровне объекта.
13. **Настройте `ALTER DEFAULT PRIVILEGES` в миграциях.** Иначе каждый объект, созданный после деплоя, снова получит грант `PUBLIC`. Команда должна выполняться ролью, которая создаёт объекты.

## Дополнительная информация

### См. также

- **[Хранимые объекты: обзор](../../Concepts/stored_objects_overview.md)** — общие принципы хранимых объектов.
- **[Безопасность PostgreSQL](../../PostgreSQL/Concepts/security_and_encryption.md)** — TDE, RLS, SSL/TLS.
- **[Безопасность MariaDB](../../MariaDB/security/index.md)** — RBAC, аудит, TDE.
- **[Управление ролями PostgreSQL](../../PostgreSQL/Operations/role_management.md)** — RBAC, наследование прав.
- **[Хранимые объекты в MariaDB/MySQL](../../MariaDB/Concepts/stored_objects_management.md)** — управление, отладка, Event Scheduler.
- **[Troubleshooting хранимых объектов](troubleshooting.md)** — блокировки, рекурсия, ограничения СУБД.
- **[Шифрование данных в покое](../../Concepts/encryption_at_rest.md)** — теория DEK/KEK, TDE.
