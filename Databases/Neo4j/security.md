# Neo4j: Безопасность

**Актуально для:** Neo4j 2026.09.x / Neo4j 5.26 LTS

> **Редакции.** Значительная часть описанного ниже — fine-grained RBAC, sub-graph access control, ABAC, `security.log`, онлайн-бэкапы — доступна только в **Enterprise Edition**. В Community Edition остаётся нативный auth provider, базовые встроенные роли и собственные процедуры авторизации. Проверяйте принадлежность функции к редакции до проектирования схемы прав: перенос Community → Enterprise меняет набор доступных привилегий. Матрица «что доступно в какой редакции» — в [обзоре](./overview.md#редакции-что-доступно-в-какой-редакции).

## Определения

| Термин | Значение |
| :--- | :--- |
| **DBMS** | Экземпляр Neo4j, управляющий одной или несколькими базами данных. |
| **`system`** | Служебная база, в которой хранятся пользователи, роли, привилегии и конфигурация безопасности. Все административные команды исполняются против неё. |
| **Auth provider** | Механизм проверки учётных данных. Бывает встроенным (`native`) или внешним (LDAP, OIDC/SSO, Kerberos, custom plugin). |
| **RBAC** | Role-Based Access Control: привилегии выдаются ролям, роли назначаются пользователям. |
| **Privilege** | Конкретное право (`READ`, `MATCH`, `WRITE`, `CREATE`, `LOAD`, `START DATABASE` и т. д.), выдаваемое на определённый ресурс. |
| **Sub-graph access control** | Ограничение доступа до конкретных комбинаций меток, типов связей и свойств внутри графа. |
| **ABAC** | Attribute-Based Access Control: роли выдаются динамически по атрибутам пользователя (claims из OIDC-токена или теги нативного пользователя). |
| **SSL policy** | Именованный набор параметров TLS (`bolt`, `https`, `cluster`, `backup`), задаваемый через `dbms.ssl.policy.<scope>.*`. |
| **mTLS** | Взаимная TLS-аутентификация: и сервер, и клиент предъявляют сертификаты. |
| **BOOSTED** | Привилегия выполнения процедур через внутренние API Neo4j, минуя проверку прав на данные. |

## Модель безопасности: как Neo4j принимает решение о доступе

Neo4j проверяет доступ в два независимых этапа. Понимание порядка критично: запрос может пройти аутентификацию и всё равно быть отклонён, и наоборот.

```text
1. Аутентификация — «кто вы?»        → auth provider (native / ldap / oidc / kerberos)
        ↓
2. Авторизация — «можно ли вам это?» → RBAC: привилегии ролей, DENY перекрывает GRANT
        ↓
3. Доступ к данным                    → MATCH / READ / WRITE с фильтром по меткам и свойствам
```

**Этап 1. Аутентификация.** Проверяется учётная запись, и она должна быть активна (`SUSPENDED` пользователь не может аутентифицироваться ни при каких ролях). Провайдер выбирается по конфигурации и по привязанному к пользователю auth provider.

**Этап 2. Авторизация.** Права — это **объединение (union) привилегий всех назначенных пользователю ролей**. У пользователя может быть несколько ролей, и он получает сумму их прав. `DENY` всегда перекрывает `GRANT`: доступ есть тогда и только тогда, когда есть разрешение **и** нет запрета на тот же ресурс. Все остальные комбинации (только `DENY`, ничего не задано, `GRANT` без `GRANT`-а на сам ресурс) дают отказ.

**Этап 3. Права на данные.** Привилегии выдаются на конкретный граф и сущности внутри него. Отсутствие `ACCESS ON DATABASE` блокирует соединение к базе независимо от прочих привилегий.

Практическое следствие для администратора: `GRANT` без `GRANT` на родительском ресурсе — самая частая причина того, что «права выдали, а доступа нет». Например, `GRANT MATCH {*} ON GRAPH neo4j NODES Person TO role` не даст ничего, пока роли не выдан `ACCESS ON DATABASE neo4j`.

## Аутентификация

### Встроенный (native) auth provider

Пользователи и роли хранятся в базе `system`. Параметры:

```properties
# neo4j.conf
dbms.security.auth_enabled=true
dbms.security.auth_max_failed_attempts=3
dbms.security.auth_lock_time=5s
```

| Параметр | По умолчанию | Смысл |
| :--- | :--- | :--- |
| `dbms.security.auth_enabled` | `true` | Требовать аутентификацию. **Отключать только на время аварийного восстановления** и обязательно с ограничением сетевых подключений — см. [Восстановление доступа](#восстановление-доступа-утрачен-пароль-или-роль-admin) |
| `dbms.security.auth_max_failed_attempts` | `3` | Число неудачных попыток до блокировки учётной записи |
| `dbms.security.auth_lock_time` | `5s` | Длительность блокировки |

> **Блокировка — это и защита, и отказ в обслуживании.** Значения по умолчанию (3 попытки / 5 секунд) агрессивны: при трёх неудачных попытках аккаунт заблокирован, но всего на 5 секунд, то есть перебор пароля продолжается фактически без пауз. Для интернет-доступного инстанса это превращает Neo4j в источник проверки паролей онлайн. Сознательно увеличьте `auth_lock_time` (например, до `60s`) и ограничьте доступ к Bolt на сетевом уровне.

**Политика паролей** в Neo4j минимальна и не настраивается: пароль не может быть пустым, должен отличаться от предыдущего и содержать **не менее 8 символов**. Ни требований к сложности, ни срока действия, ни истории паролей нет. Если политика сложности нужна — она реализуется на стороне внешнего auth provider (LDAP/OIDC) либо процедурой проверки на входе приложения.

**Создание и управление пользователями:**

```cypher
// Создание с обязательной сменой пароля при первом входе
CREATE USER app_user IDENTIFIED BY 'Str0ngInitialPass' SET PASSWORD CHANGE REQUIRED;

// Установка и смена пароля
ALTER USER app_user SET PASSWORD 'An0therStr0ngPass' SET PASSWORD CHANGE NOT REQUIRED;

// Смена собственного пароля текущим пользователем
ALTER CURRENT USER SET PASSWORD FROM 'OldPass' TO 'NewStr0ngPass';

// Временная блокировка учётной записи (не удаление)
SUSPEND USER app_user;
ENABLE USER app_user;

// Домашняя база по умолчанию и срок действия
ALTER USER app_user SET HOME DATABASE graphdb;

// Удаление
DROP USER app_user;
```

```bash
# Начальный пароль администратора — только до первого старта
sudo neo4j-admin dbms set-initial-password 'Str0ngInitialPass' --require-password-change
# → Initial password set successfully, password change required.
```

**Аудитная проверка состава пользователей** (выполнять на `system`):

```cypher
SHOW USERS;
SHOW USERS YIELD user, roles, suspended RETURN user, roles, suspended, auth;
SHOW ROLES;
SHOW POPULATED ROLES;                 // только роли, назначенные хоть одному пользователю
SHOW ROLES WITH USERS;                // какие пользователи в каждой роли
```

> **Аутентифицироваться в `system` должен именно `neo4j` (администратор).** Пользователь приложения может видеть только собственные привилегии: команда `SHOW USER PRIVILEGES` без имени работает для текущего пользователя, а чужие привилегии при внешнем auth provider недоступны вовсе.

### Блокировка учётной записи: что видно в логе

```plain
# logs/security.log
2026-09-14 11:22:41.318+0000 ERROR [johndoe]: failed to log in: invalid principal or credentials
2026-09-14 11:22:44.902+0000 ERROR [attacker]: failed to log in: too many failed attempts
```

Второе сообщение — срабатывание `dbms.security.auth_max_failed_attempts`. Регулярное появление этой строки от внешних адресов — признак перебора паролей, а не сбоя приложения.

### Внешние auth providers: LDAP, OIDC/SSO, Kerberos

Внешние провайдеры не заменяют модель прав — они поставляют **имя пользователя**, которое затем сопоставляется с внутренней учётной записью. Сами роли и привилегии остаются в `system`.

```properties
# neo4j.conf — смешанный режим: native для админа, OIDC для людей
dbms.security.authentication_providers=native,oidc-okta
dbms.security.authorization_providers=native,oidc-okta

dbms.security.oidc.okta.display_name=Okta
dbms.security.oidc.okta.auth_flow=pkce
dbms.security.oidc.okta.well_known_discovery_uri=https://example.okta.com/oauth2/default/.well-known/openid-configuration
dbms.security.oidc.okta.audience=neo4j
dbms.security.oidc.okta.claims.username=sub
dbms.security.oidc.okta.claims.groups=groups
dbms.security.oidc.okta.authorization.group_to_role_mapping="neo4j_readers"=reader; "neo4j_editors"=editor
```

Практические требования к внешней аутентификации:

- **LDAP должен использовать StartTLS.** Открытый LDAP — это передача паролей и групповых memberships в открытом виде; `dbms.security.ldap.*` сам по себе этого не решает.
- **Роли из маппинга должны существовать в Neo4j.** Если в `group_to_role_mapping` указана роль, которой нет в `system`, пользователь её не получит. Сверяйте `SHOW ROLES` с `SHOW ROLES WITH USERS` после первого входа.
- **Изменения конфигурации OIDC/LDAP требуют рестарта** — в отличие от динамических настроек.
- **Kerberos** поставляется отдельным аддоном (Neo4j Kerberos Add-On), а не встроенным провайдером.
- **Для `pkce` не используйте `implicit`**: auth flow `implicit` помечен к удалению начиная с 2026.06.

**User auth providers** — привязка внешней identity к внутренней учётной записи на уровне конкретного пользователя. Требует `dbms.security.require_local_user=true`; после этого аутентифицироваться смогут только пользователи, для которых в базе есть соответствующая привязка.

```cypher
CREATE USER alice SET AUTH 'oidc-okta' VALUE '00u1a2b3c';
ALTER USER alice SET AUTH 'oidc-okta' VALUE '00u9z8y7x';
```

`require_local_user=true` — важный защитный переключатель: без него внешний пользователь, для которого в базе нет записи, всё равно аутентифицируется. Это закрывает путь обхода через внешний провайдер (см. предупреждение о тегах в разделе [ABAC](#abac-attribute-based-access-control)).

## Авторизация: RBAC

### Встроенные роли

Роли **иерархические**, от `reader` внизу до `admin` вверху. Каждая верхняя включает возможности нижних.

| Роль | Возможности |
| :--- | :--- |
| `PUBLIC` | Назначается всем автоматически, не отзывается и не удаляется. Даёт доступ к домашней базе, `LOAD` и выполнение процедур/функций. **Не даёт прав на чтение данных** |
| `reader` | Чтение и обход всех графов, кроме `system`; просмотр индексов и ограничений |
| `editor` | Всё от `reader` плюс запись. Не может создавать новые метки, ключи свойств и типы связей |
| `publisher` | Всё от `editor` плюс создание новых меток, ключей свойств и типов связей |
| `architect` | Всё от `publisher` плюс создание и удаление индексов и ограничений |
| `admin` | Всё от `architect` плюс управление базами, алиасами, пользователями, ролями, привилегиями, конфигурацией и процедурами |

> **Пять ролей, а не три.** Утверждение «`editor` = чтение и запись» верно, но неполно: `editor` принципиально **не может** создать новую метку или тип связи. Приложение, которому нужно завести новую метку при первой миграции схемы, на `editor` получит отказ — ему нужен `publisher`. Роли `publisher`, `architect` и `admin` в Community Edition недоступны.

Практическое правило: **встроенные роли не годятся под приложение**. Их зрелищные имена провоцируют ошибку — выдать приложению `editor` «на всякий случай». Приложению нужна отдельная роль с минимальным набором привилегий на конкретный граф.

### Синтаксис привилегий

```text
{GRANT | DENY} [IMMUTABLE] privilege
  ON { GRAPH[S] {* | name[,...]} | DATABASE[S] {* | name[,...]} | HOME GRAPH | DBMS }
  [entity]
  TO role[, ...]
```

`entity` задаёт подграф: `NODES Label`, `RELATIONSHIPS Type`, `ELEMENTS Label` (и то и другое), либо шаблон `FOR (n:Label) WHERE ...`. Несколько меток перечисляются через запятую; `*` — все. Если `entity` опущен, действует `ELEMENTS *`.

Ключевое слово `IMMUTABLE` делает привилегию неотзываемой: её нельзя выдать, запретить или отозвать, пока не отключена аутентификация. Это защита от «инженер выдал себе `IMMUTABLE WRITE` и забыл» — но и от легального отката. Применяйте осознанно и только на короткий срок.

### Права на данные: минимальный пример для приложения

```cypher
// Отдельная роль приложения вместо встроенного editor
CREATE ROLE app_service;
GRANT ROLE app_service TO app_user;

// Доступ к самой базе — без этого остальные привилегии бессмысленны
GRANT ACCESS ON DATABASE neo4j TO app_service;

// Чтение узлов Person со всеми свойствами
GRANT MATCH {*} ON GRAPH neo4j NODES Person TO app_service;

// Чтение только части свойств — principle of least privilege на уровне полей
GRANT MATCH {name, born} ON GRAPH neo4j NODES Person TO app_service;

// Обход связей конкретного типа (без этого MATCH по узлам не найдёт соседей)
GRANT MATCH {*} ON GRAPH neo4j RELATIONSHIPS KNOWS TO app_service;

// Запись: создание узлов Person
GRANT CREATE ON GRAPH neo4j NODES Person TO app_service;
GRANT SET PROPERTY {name, born} ON GRAPH neo4j NODES Person TO app_service;
```

Особенности, которые ломают наивные конфигурации:

- **`GRANT MATCH` требует блок свойств.** Синтаксис `GRANT MATCH ON GRAPH ...` без `{...}` невалиден: блок `{*}` или список имён обязателен. Читаемость данных при этом подчиняется правилу «свойства читаются только у найденных сущностей» — `READ` без `TRAVERSE` не даёт увидеть сам узел.
- **`SET LABEL` и `WRITE` нельзя ограничить подграфом.** Нельзя сказать «разрешить добавлять метку `Verified` ко всем узлам, но запретить добавлять метку `Admin`» — приходится комбинировать `GRANT WRITE` с точечными `DENY`.
- **`MERGE` нельзя запретить через `DENY MERGE`.** Запрещайте через `DENY CREATE` и `DENY SET PROPERTY`.
- **Новые метки требуют отдельных прав.** `CREATE` на `NODES Person` не позволит создать узел с меткой, которой в базе ещё нет: нужна привилегия `CREATE NEW LABEL` (аналогично `CREATE NEW RELATIONSHIP TYPE` и `CREATE NEW PROPERTY NAME`).
- **Письмо в `query.log` может раскрыть данные.** `db.logs.query.obfuscate_literals=true` в `query.log` по умолнию выключен — см. [Аудит и логирование](#аудит-и-логирование).

### Sub-graph и property-based access control

Главная возможность, которой нет у большинства графовых СУБД: ограничить чтение до конкретных меток, типов связей и даже отдельных свойств. Для данных с разной чувствительностью в одном графе это основной инструмент разделения доступа.

```cypher
// Публичные документы видны всем читателям
GRANT MATCH {title, createdAt} ON GRAPH neo4j NODES Document
  FOR (d:Document) WHERE d.visibility = 'public'
  TO reader;

// Платёжные свойства — только финансовой роли
GRANT MATCH {pan, iban} ON GRAPH neo4j NODES Account TO finance;

// Явный запрет: редакторам нельзя читать приватные документы
DENY MATCH {*} ON GRAPH neo4j NODES Document
  FOR (d:Document) WHERE d.visibility = 'private'
  TO editor;
```

**Семантика `DENY MATCH {*}` против `DENY MATCH {prop}`.** Если указаны конкретные ключи свойств, запрет касается только их чтения — сама сущность остаётся доступной для обхода. При `{*}` блокируется и обход, и все свойства. Это частая причина «DENY не сработал»: формально он сработал, но запретил не то, что имелось в виду.

**Ошибка чтения и ошибка записи ведут себя по-разному.** Ограничение на чтение делает данные **невидимыми** — запрос возвращает меньше результатов без ошибки. Ограничение на запись **возвращает ошибку**. Это важно при проектировании: приложение, полагающееся на количество строк, не заметит потерю данных, а попытка записи сразу даст отказ.

### Аудит привилегий

```cypher
SHOW ROLE app_service PRIVILEGES;
SHOW ROLE app_service PRIVILEGES AS COMMANDS;   // воспроизводимый скрипт
SHOW USER app_user PRIVILEGES;
SHOW CURRENT USER PRIVILEGES;                  // только для себя
SHOW SUPPORTED PRIVILEGES;                     // полный перечень привилегий сервера
```

`AS COMMANDS` — операционный инструмент: выгрузка позволяет хранить декларацию прав в Git и применять её идемпотентно, а не вносить правки вручную на работающем сервере.

### ABAC (Attribute-Based Access Control)

*Enterprise Edition; `SET CONDITION` и теги нативных пользователей — с 2026.06.*

ABAC выдаёт роли **динамически**, по условию, а не статическим `GRANT ROLE`. Это снимает рутинный труд с назначением прав при переходах людей между отделами и позволяет выдавать дежурные права по расписанию.

```properties
# neo4j.conf
dbms.security.abac.authorization_providers=native,oidc-okta
dbms.security.logs.oidc.jwt_claims_at_debug_level_enabled=true   # отладка: видеть claims
```

```cypher
CREATE ROLE salesTeam;
CREATE AUTH RULE salesRule
    SET CONDITION abac.oidc.user_attribute('department') = 'sales';
GRANT ROLE salesTeam TO AUTH RULE salesRule;

// Несколько тегов одновременно (native users)
CREATE AUTH RULE financeAuditorRule
    SET CONDITION all(tag IN ['finance', 'auditor'] WHERE tag IN abac.native.user_tags());

// Дежурный доступ: тег + временное окно в UTC
CREATE AUTH RULE onCallRule
    SET CONDITION 'on-call' IN abac.native.user_tags()
        AND (time.transaction('UTC').hour < 9 OR time.transaction('UTC').hour >= 17);
GRANT ROLE onCallTeam TO AUTH RULE onCallRule;
```

Ограничения, которые делают ABAC опасным без понимания:

- **ABAC не ограничивает RBAC.** Пользователь получает **объединение** ролей из RBAC и из выполненных auth rules. Если `admin` назначен через `GRANT ROLE` в JWT-группе, правило ABAC «только с 19:00 до 20:00» его не урежет. Временные и контекстные правила работают только для ролей, которые **больше нигде не назначены статически**.
- **Не стройте правило на отсутствии тега.** `NOT ('restricted' IN abac.native.user_tags())` выполняется для любого пользователя без тегов: и для только что созданного, и для аутентифицированного через OIDC без привязки к нативной учётной записи. Это прямой путь к эскалации. Формулируйте на **наличии** требуемого тега.
- **Пропущенный claim даёт `null`, а не ошибку** — условие ложно, роль не выдаётся. Это безопасное поведение (fail-closed), но при отсутствии claim у внешнего пользователя он молча получит меньше прав, чем ожидает разработчик.
- **Только OIDC и `native` поставляют атрибуты.** LDAP не имеет функции-аксессора: пользователя LDAP нужно связать с нативной учётной записью, и теги читать с неё.
- **Новые claims требуют повторной аутентификации.** Условие действует на существующие сессии, но только по claims, которые уже были загружены при старте сессии. После правки правила пользователям нужно переподключиться.
- **Дниги и часы:** `datetime.transaction()` отражают время сервера, а не время выдачи токена. В кластере обязательно синхронизируйте часы между членами, иначе решение о доступе будет расходиться между узлами. Смешивать claims-время из токена с серверным временем нельзя — форматы и часовые пояса различаются.
- **Роли с `DENY`-привилегиями назначить auth rule нельзя.** Это осознанная страховка: если правило не выполнилось, возможно только сужение прав, никогда расширение.

Отладка: включить debug-уровень для `security.log` и `debug.log`, а для OIDC — `dbms.security.logs.oidc.jwt_claims_at_debug_level_enabled=true`. Теги читаются через `SHOW USERS YIELD *`; в логах переводы строк внутри тегов заменяются пробелами (защита от log forging), поэтому значение из лога может не совпасть с фактическим — сверяйтесь с `SHOW USERS`.

## Защита расширений и выполнения кода

Процедуры и функции — основной вектор выхода за модель привилегий, потому что код, исполняемый на сервере, работает с привилегиями `BOOSTED`.

```properties
# neo4j.conf — минимальный allowlist
dbms.security.procedures.allowlist=apoc.math.*,apoc.rel.*,apoc.load.json
dbms.security.procedures.unrestricted=apoc.cypher.runFirstColumn
```

**`allowlist` по умолчанию загружает все процедуры** — утверждение «забыли добавить `apoc.*` в allowlist» неверно. Наоборот, переопределение минимальным списком и есть рекомендация вендора. **`unrestricted` разблокирует процедуры на внутренних API** — по умолчанию они отключены, даже при пустом allowlist. Практическое правило: `allowlist` перечисляет используемое, `unrestricted` — только то, что действительно упирается во внутренние API.

Ограничение SSRF при загрузке по URL задаётся load-привилегиями с CIDR; в Community Edition — параметром `internal.dbms.cypher_ip_blocklist`. Если загрузка по внешним URL не нужна — не давайте процедуре доступ в allowlist.

Ограничение load-привилегий **обходится привилегией `BOOSTED`**: процедура, исполняемая с повышенными привилегиями, получает полный доступ, а `EXECUTE BOOSTED PROCEDURE` перекрывает любые load-привилегии — сетевое ограничение CIDR при этом не действует. Вендор требует применять дополнительный запрет:

```cypher
DENY EXECUTE BOOSTED PROCEDURE apoc.* ON DBMS TO PUBLIC;
```

Без этого `DENY` пользователь с административными привилегиями обходит сетевое ограничение. Учтите, что `DENY EXECUTE BOOSTED PROCEDURE` отменяет только повышение прав, но не само выполнение процедуры: для запрета вызова нужен `DENY EXECUTE PROCEDURE apoc.* ON DBMS TO PUBLIC`.

Разбор обоих параметров, типовые SSRF-сценарии и диагностика — в [APOC: модель безопасности](./apoc.md#модель-безопасности-allowlist-и-unrestricted).

Процедуры динамического выполнения запросов (`apoc.cypher.runFirstColumn`, `apoc.cypher.*`) — не только вопрос allowlist: это прямой канал исполнения произвольного Cypher, построенного приложением. Модель угроз и защиты — в разделе [Защита запросов от инъекций](#защита-запросов-от-инъекций-параметризация-как-единственная-граница).

**Загрузка данных с диска:**

```cypher
LOAD CSV FROM 'file:///data/import.csv' ...
```

```properties
dbms.security.allow_csv_import_from_file_urls=false
```

Параметр управляет разрешением `file:///`-URL. По умолчанию пути резолвятся относительно каталога `server.directories.import` — это ограничение по умолчанию. Прежде чем включать чтение по произвольным путям, оцените, кто может положить файл в этот каталог: `LOAD CSV` — это read primitive, и она читает всё, до чего дотягивается серверный процесс.

**Права на файлы установки.** Каталоги `bin`, `lib` и `plugins` должны быть доступны **только** системному пользователю, от имени которого работает Neo4j. Практическая проверка:

```bash
ls -ld /var/lib/neo4j/{bin,lib,plugins,conf}
# → drwxr-x---  neo4j neo4j     (750, не 755 и не 777)
ls -l /var/lib/neo4j/conf/neo4j.conf
# → -rw-r-----  neo4j neo4j     (640)
```

`neo4j.conf` содержит секреты (пароли OIDC, LDAP, passphrase приватного ключа) и потому не должен быть world-readable.

## Защита запросов от инъекций: параметризация как единственная граница

### Механизм проблемы

Драйвер отправляет запрос и данные раздельно: текст запроса — это структура, значения — параметры. Пока текст запроса собирается из пользовательского ввода конкатенацией, граница исчезает: всё, что попало в строку, становится частью языка, а не данными.

Официальная формулировка верна и для безопасности: параметризованный запрос — это запрос, в котором используются подстановки параметров, а значения передаются в момент выполнения, поэтому **разработчику не приходится прибегать к сборке строк для создания запроса**.

### Что можно и что нельзя передать параметром

Граница проходит по структуре запроса, а не по типу данных:

| Можно передать параметром | Нельзя передать параметром |
| :--- | :--- |
| Литералы и выражения | Ключи свойств: `MATCH (n) WHERE n.$param = 'x'` — невалидно |
| ID узлов и связей | Типы связей в паттерне: `MATCH (n)-[:$param]->(m)` — невалидно |
| Свойства при динамической ссылке (`n[$param]`) | Метки узлов в паттерне: `MATCH (n:$param)` — невалидно |
| Метки и типы связей **при динамической ссылке** | — |

Запрещённые конструкции некомпилируются не по соображениям безопасности, а потому что они формируют структуру запроса, которая попадает в план. Отсюда важное следствие для безопасности: **идентификаторы — метки, типы связей, ключи свойств — принципиально не переносятся в параметры**, и защита для них строится иначе, чем для значений.

### Инъекция значений

```cypher
-- УЯЗВИМО: ввод пользователя становится частью языка
MATCH (p:Person {email: '" + $userEmail + "'}) RETURN p;
```

```python
# УЯЗВИМО
driver.execute_query(f"MATCH (p:Person) WHERE p.name = '{user_input}' RETURN p")
```

```python
# ПРАВИЛЬНО: структура фиксирована, значение передаётся параметром
driver.execute_query(
    "MATCH (p:Person {email: $email}) RETURN p",
    email=user_input,
)
```

Параметризованный запрос выполняется как задумано при любом содержимом значения: кавычки, обратные слэши и управляющие символы в параметре остаются данными.

### Инъекция идентификаторов

Здесь параметры не помогают, и ошибка делается на уровне модели. Плохой вариант — подставлять метку из ввода:

```cypher
-- УЯЗВИМО: метка из пользовательского ввода склеена с текстом запроса
MATCH (n:$(label)) RETURN n LIMIT 10;
```

Правильный вариант — **белый список**: метка выбирается из конечного множества на стороне приложения, а не приходит от пользователя.

```python
ALLOWED_LABELS = {"Person", "Company", "Product"}

def fetch_by_label(driver, label):
    if label not in ALLOWED_LABELS:
        raise ValueError(f"label not allowed: {label}")
    return driver.execute_query(
        f"MATCH (n:{label}) RETURN count(n) AS total"
    )
```

Ключи свойств в динамических конструкциях — тот же случай:

```cypher
-- Динамическое свойство: значение безопасно, ключ должен быть из белого списка
SET n[$field] = $value
```

Динамический синтаксис для меток, свойств и ключей — `SET n:$(labels)`, `SET n[key] = value`; он же указан как замена устаревшим процедурам в [APOC](./apoc.md).

### Динамическое выполнение запросов

Отдельный класс риска — когда приложение строит Cypher и передаёт его на исполнение процедуре:

```cypher
CALL apoc.cypher.runFirstColumn($userBuiltQuery, $params) YIELD value RETURN value
```

Здесь параметризация не помогает ничем: запрос уже собран. Разбор такой конструкции:

| Вопрос | Ответ по документации |
| :--- | --- |
| Нужна ли процедура в allowlist | Да |
| Нужна ли она в `unrestricted` | Да — она работает на внутренних API |
| Что ограничивает исполнение | Только то, что построено приложением; сама база предела не имеет |

Практические меры: не использовать `apoc.cypher.*` для запросов, в которых участвует пользовательский ввод; если без этого обойтись нельзя — пропускать собранный запрос через белый список конструкций, а не через экранирование строк.

### Что параметризация НЕ решает

- **Доступ к данным.** Параметризация защищает от изменения запроса, но не от чтения чужих данных. Для этого нужны привилегии и sub-graph доступ — см. [Sub-graph и property-based access control](#sub-graph-и-property-based-access-control).
- **Логические ошибки в запросе.** `$tenantId` в обязательном фильтре — уже вопрос корректности, а не безопасности.
- **Загрузка файлов.** `LOAD CSV` с путём из пользовательского ввода регулируется отдельно — см. раздел ниже про `dbms.security.allow_csv_import_from_file_urls`.
- **Автоматическая параметризация.** Начиная с Neo4j 5 Cypher пытается выводить параметры даже для частично параметризованного запроса: каждый литерал заменяется параметром, что повышает переиспользование плана. Это про кэш планов, а не про безопасность: параметризация не появится для текста, который вы склеили сами.

### Диагностика

| Признак | Что проверить |
| :--- | --- |
| В коде есть `execute_query(f"...")` или конкатенация строк с `+` | Прямая конкатенация пользовательского ввода в текст запроса |
| Метка или ключ свойства приходит из API-запроса | Нет белого списка идентификаторов |
| В `allowlist` присутствует `apoc.cypher.*` | Возможность исполнения произвольного Cypher приложением |
| Запрос изменил смысл при «необычном» вводе | Проверить, действительно ли запрос параметризован |

В логах следы удачных инъекций искать бесполезно: при эксплуатации запрос выполняется как обычный легитимный. Единственная надёжная защита — параметризация в коде и ревью, запрещающее конкатенацию в тексте запроса.

## Шифрование (TLS) — SSL Framework

### Принцип: TLS включается двумя независимыми настройками

С 5-й версии TLS в Neo4j настраивается через **SSL Framework** — именованные политики вида `dbms.ssl.policy.<scope>.*`. Настройки 4.x (`server.ssl.enabled`, `server.ssl.policy`, `server.ssl.key_file`, `server.ssl.certificate_file`) в 5.x и 2026.x **не используются**; при строгой валидации конфигурации (`server.config.strict_validation.enabled=true` по умолчанию) сервер с ними не стартует.

Два независимых условия, без обоих шифрования не будет:

1. **Политика включена** — `dbms.ssl.policy.<scope>.enabled=true`.
2. **Коннектор требует TLS** — `server.bolt.tls_level=REQUIRED` (для Bolt; по умолчанию `DISABLED`, то есть принимаются только незашифрованные соединения).

Включить политику, но забыть про `tls_level` — самая частая ошибка: в `neo4j.log` нет ошибок, а трафик идёт открытым.

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `enabled` | `false` | Включает политику |
| `base_directory` | `certificates/` | Базовый каталог, относительно которого ищутся файлы |
| `private_key` | `private.key` | Приватный ключ |
| `public_certificate` | `public.crt` | Публичный сертификат, подписанный CA |
| `trusted_dir` | `trusted/` | Каталог с сертификатами доверенных сторон |
| `revoked_dir` | `revoked/` | Каталог со списками отзыва (CRL) |
| `client_auth` | `OPTIONAL` для bolt/https, `REQUIRE` для cluster/backup | Требовать клиентский сертификат (mTLS) |
| `tls_versions` | `TLSv1.2 TLSv1.3` | Разрешённые версии TLS |
| `ciphers` | наборы JRE | Разрешённые шифронаборы |
| `verify_hostname` | `true` | Проверка CN/SAN сертификата против адреса подключения |
| `trust_all` | `false` | **`true` отключает проверку — только для отладки** |

Области (`scope`): `bolt`, `https`, `cluster`, `backup`.

### Настройка TLS для Bolt

```properties
# neo4j.conf
dbms.ssl.policy.bolt.enabled=true
dbms.ssl.policy.bolt.base_directory=certificates/bolt
dbms.ssl.policy.bolt.private_key=private.key
dbms.ssl.policy.bolt.public_certificate=public.crt
dbms.ssl.policy.bolt.client_auth=NONE
dbms.ssl.policy.bolt.tls_versions=TLSv1.2,TLSv1.3
dbms.ssl.policy.bolt.verify_hostname=true
server.bolt.tls_level=REQUIRED
```

```bash
# Раскладка файлов — пути относительно base_directory
sudo install -d -o neo4j -g neo4j -m 750 \
  /var/lib/neo4j/certificates/bolt \
  /var/lib/neo4j/certificates/bolt/trusted
sudo install -o neo4j -g neo4j -m 640 private.key public.crt \
  /var/lib/neo4j/certificates/bolt/
sudo systemctl restart neo4j
```

### Генерация сертификата для тестовой среды

Приватный ключ должен быть в формате **PKCS #8** в PEM. Формат PKCS #1 (`-----BEGIN RSA PRIVATE KEY-----`) объявлен устаревшим начиная с Neo4j 5.0. Команда `openssl req -newkey` в OpenSSL 3.x по умолчанию выдаёт именно PKCS #8.

```bash
# Самоподписанный сертификат для тестовой среды
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout private.key -out public.crt \
  -days 365 -subj "/CN=neo4j.internal" \
  -addext "subjectAltName=DNS:neo4j.internal,DNS:localhost,IP:127.0.0.1"

# → private.key  должен начинаться с  -----BEGIN PRIVATE KEY-----   (PKCS #8)
head -1 private.key
```

> **Самоподписанный сертификат — не средство защиты, а средство шифрования.** Он защищает трафик от прослушивания, но не от посредника: клиент, доверяющий любому сертификату, уязвим к MITM. Итог: в production — сертификат от доверенного CA, `bolt+s://` на клиенте и `verify_hostname=true`. Для тестового контура с самоподписанным сертификатом клиент подключается через `bolt+ssc://` — он отключает проверку CA, но **проверку имени хоста выполняет по-прежнему**, поэтому `subjectAltName` должен содержать имя, по которому вы подключаетесь.

### Проверка

```bash
# 1. Уровень TLS и сертификат — без участия Neo4j
openssl s_client -connect localhost:7687 -CAfile /var/lib/neo4j/certificates/bolt/public.crt </dev/null 2>/dev/null \
  | grep -E "Protocol|Cipher|Verify return code"
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → Verify return code: 0 (ok)

# 2. Шифрованное соединение клиентом
cypher-shell -a bolt+s://localhost:7687 -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1 AS test;"
# → +------+
#    | test |
#    +------+
#    | 1    |
#    +------+

# 3. Убедиться, что незашифрованное соединение отвергается (tls_level=REQUIRED)
cypher-shell -a bolt://localhost:7687 -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1"
# → Connection refused / SSL handshake failed
```

Пункт 3 — обязательная проверка. Пока он не пройден, утверждать, что шифрование обязательно, нельзя.

### mTLS и взаимная аутентификация

```properties
dbms.ssl.policy.bolt.client_auth=REQUIRE
dbms.ssl.policy.bolt.trusted_dir=certificates/bolt/trusted
```

Клиент предъявляет свой сертификат из этого каталога; на стороне драйвера это второй фактор аутентификации (Enterprise). Настройка клиентских сертификатов — в [драйверах](./drivers.md#безопасность-подключения). Практическая выгода: пароль приложения перестаёт быть единственным секретом, а отзыв сертификата даёт мгновенный эффект без смены паролей.

### Внутрикластерная коммуникация и бэкапы

```properties
# Внутрикластерный обмен — по умолчанию уже REQUIRE, но шифрование не включено
dbms.ssl.policy.cluster.enabled=true
dbms.ssl.policy.cluster.client_auth=REQUIRE
dbms.ssl.policy.cluster.base_directory=certificates/cluster

# Приём онлайн-бэкапов (порт 6362)
dbms.ssl.policy.backup.enabled=true
dbms.ssl.policy.backup.client_auth=REQUIRE
```

Порты 6000, 7000 и 6362 **не аутентифицируют** отправителя на уровне приложения: транзакционный протокол кластера допускает репликацию базы без аутентификации. Единственная линия защиты здесь — сетевой доступ и `client_auth=REQUIRE`.

### Контейнеры

В Docker параметры `neo4j.conf` передаются через переменные окружения по схеме `NEO4J_<параметр>`, где **каждое подчёркивание в имени параметра удваивается**:

```bash
docker run -d --name neo4j \
  -p 7687:7687 \
  -v "$PWD/certificates:/var/lib/neo4j/certificates:ro" \
  -e NEO4J_AUTH=neo4j/Str0ngInitialPass \
  -e NEO4J_dbms_ssl_policy_bolt_enabled=true \
  -e NEO4J_dbms_ssl_policy_bolt_base__directory=certificates/bolt \
  -e NEO4J_dbms_ssl_policy_bolt_private__key=private.key \
  -e NEO4J_dbms_ssl_policy_bolt_public__certificate=public.crt \
  -e NEO4J_server_bolt_tls__level=REQUIRED \
  -e NEO4J_server_https__enabled=false \
  neo4j:2026.09.0-enterprise
```

`base__directory` и `tls__level` с **двумя** подчёркиваниями — самая частая опечатка; при неверном имени переменной настройка молча не применяется. Значение `base_directory` указывает на путь **внутри volume**, а не на путь на хосте.

### FIPS 140-3 и постквантовый обмен ключами

**FIPS 140-3.** Требуется ОС и железо, совместимые с FIPS, FIPS-сертифицированный OpenSSL с включённым FIPS-провайдером, и **динамически слинкованный `netty-tcnative`** (статическая сборка на BoringSSL FIPS-сертификации не имеет). Переключение провайдера и перечень шифронаборов:

```properties
dbms.netty.ssl.provider=OPENSSL
server.bolt.tls_level=REQUIRED
dbms.ssl.policy.bolt.trust_all=false
dbms.ssl.policy.bolt.tls_versions=TLSv1.2,TLSv1.3
dbms.ssl.policy.bolt.ciphers=TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384,TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,TLS_DHE_RSA_WITH_AES_256_GCM_SHA384,TLS_DHE_RSA_WITH_AES_128_GCM_SHA256,TLS_AES_256_GCM_SHA384,TLS_AES_128_GCM_SHA256
dbms.ssl.policy.bolt.private_key_password=<пароль от зашифрованного ключа, не открытым текстом>
```

Приватный ключ в режиме FIPS обязан быть защищён паролем, а пароль — читаться из файла, а не храниться в `neo4j.conf` открытым текстом. Поддерживается только Linux. FIPS 140-2 выходит из обращения 21 сентября 2026 — миграция на валидированные FIPS 140-3 реализации.

**Постквантовый гибридный обмен ключами.** Требует OpenSSL 3.5+ и `dbms.netty.ssl.provider=OPENSSL`. Группа `X25519MLKEM768` (ML-KEM-768 по FIPS 203 в сочетании с X25519) защищает от сценария HNDL — «собрать сейчас, расшифровать позже». Проверка:

```bash
openssl s_client -connect localhost:7687 -groups X25519MLKEM768 -CAfile public.crt </dev/null 2>/dev/null \
  | grep -E "Negotiated TLS1.3 group|Protocol"
# → Protocol  : TLSv1.3
# → Negotiated TLS1.3 group: X25519MLKEM768
```

Ограничение: поддерживается **только Bolt**. HTTP-сервер работает на нативных Java-криптобиблиотеках, поддержка ожидает бэкпорта в LTS-версии JVM.

## Сетевая изоляция

Полная таблица портов — в [обзоре](./overview.md#порты-и-сетевые-коннекторы). Здесь только то, что имеет прямое отношение к безопасности.

```properties
# neo4j.conf — точечная привязка вместо 0.0.0.0
server.bolt.listen_address=127.0.0.1:7687
server.http.enabled=false
server.https.enabled=false
```

**Правило по умолчанию уже безопасное.** `server.default_listen_address` по умолчанию равен `localhost`, то есть Neo4j не слушает внешние интерфейсы, пока это не изменено намеренно. Типовая ошибка — выставить `0.0.0.0`, «чтобы драйвер подключился», и забыть, что этим открыты все порты, включая кластерные.

**Порты, которые нельзя выставлять наружу:**

| Порт | Почему опасен |
| :--- | :--- |
| 6362 | Приём онлайн-бэкапа. Незащищённый порт — возможность скопировать базу на другую машину |
| 6000 | Транзакционный протокол кластера. **Репликация базы без аутентификации** |
| 7000 | Raft-протокол кластера — вмешательство в консенсус |
| 7688 | Bolt Routing — внутренний канал маршрутизации |
| 3637 | JMX (`server.jvm.additional=-Dcom.sun.management.jmxremote.port=3637`) — исторический вектор RCE. Слушает без аутентификации, если не настроить SSL и пароль |
| 5005 | JDWP (`-agentlib:jdwp:...address=*:5005`) — отладочный порт JVM, даёт полный контроль над процессом |

Кластерные порты (6000, 7000, 7688) по умолчанию открыты на всех Enterprise-инстансах и начинают слушать, как только `server.default_listen_address` изменён с `localhost`. Если кластеризация не используется, привяжите их явно:

```properties
server.cluster.listen_address=127.0.0.1:6000
server.cluster.raft.listen_address=127.0.0.1:7000
```

**HTTP-коннектор.** Включён по умолчанию, трафик не шифруется, и это основной путь для Neo4j Browser. Если приложения ходят по Bolt, выключайте его целиком:

```properties
server.http.enabled=false
```

Альтернатива — оставить HTTP, но сузить набор endpoint'ов (`server.http_enabled_modules`):

```properties
server.http_enabled_modules=BROWSER
# По умолчанию: TRANSACTIONAL_ENDPOINTS,UNMANAGED_EXTENSIONS,BROWSER,ENTERPRISE_MANAGEMENT_ENDPOINTS,QUERY_API_ENDPOINTS
```

Если HTTP нужен наружу (например, интеграции), включайте HTTPS и **не** полагайтесь на ограничение по IP как на единственную защиту.

**Правило сегментации:** Neo4j-подсеть отделена от сегмента приложений, доступ к Bolt — только с адресов драйверов. `advertised_address` обязан совпадать с адресом, который видит клиент (reverse proxy, NAT), иначе драйвер получит неверный адрес раутинга.

## Аудит и логирование

### security.log

Отдельный файл `security.log` (Enterprise) включается автоматически, когда `dbms.security.auth_enabled=true` — **отдельного параметра для его включения не существует**. В него пишутся:

- попытки входа (по умолчанию и успешные, и неуспешные);
- все административные команды против `system` — создание пользователей, выдача ролей и привилегий, `DROP USER`;
- отказы авторизации по RBAC;
- при LDAP — события и ошибки обмена с сервером каталога.

```properties
# Снизить шум при большом числе программных подключений
dbms.security.log_successful_authentication=false
```

> **Компромисс явный.** Отключение успешных входов убирает из лога событие легитимного подключения, но оставляет все административные команды и отказы. Включайте, когда `security.log` растёт неконтролируемо, и обязательно убедитесь, что административные команды в нём остаются — именно они дают след при расследовании инцидента.

```plain
# logs/security.log
2026-09-14 11:20:02.104+0000 INFO  [johnsmith]: logged in
2026-09-14 11:22:41.318+0000 ERROR [johndoe]: failed to log in: invalid principal or credentials
2026-09-14 11:24:15.771+0000 INFO  [johnsmith]: CREATE USER janedoe SET PASSWORD '********' CHANGE REQUIRED
2026-09-14 11:25:03.220+0000 INFO  [johnsmith]: GRANT ROLE app_service TO app_user
2026-09-14 11:25:44.615+0000 INFO  [johnsmith]: DROP USER app_user
```

Пароль в записи административной команды маскируется. Это делает `security.log` пригодным для выгрузки в централизованный сбор логов — в отличие от логов драйверов на уровне `Trace`.

Для JSON-формата (удобно для парсинга) в `conf/server-logs.xml` замените `PatternLayout` у `SecurityLog` на `JsonTemplateLayout`. Поля: `time`, `level`, `type` (всегда `security`), `source`, `database`, `executingUser`, `authenticatedUser`, `message`, `stacktrace`.

### query.log: риск утечки данных

`query.log` по умолчанию пишет **все** запросы (`db.logs.query.enabled=VERBOSE`) вместе с параметрами — и это регулярный канал утечки персональных данных в логи.

```properties
# Обязательно для production
db.logs.query.obfuscate_literals=true      # маскирует литералы в тексте запроса
db.logs.query.obfuscate_errors=true        # маскирует чувствительные данные в сообщениях об ошибках (с 2026.01)
db.logs.query.parameter_logging_enabled=false   # не логировать значения параметров
```

`obfuscate_literals` скрывает значения, но **оставляет** метки, типы связей и ключи свойств — они описывают форму запроса, а не данные. `SKIP` и `LIMIT` тоже показываются. Не забывайте: изменение настройки не действует на закэшированные запросы — для немедленного эффекта выполните `CALL db.clearQueryCaches()`.

Если параметры логировать не нужно, отключите `parameter_logging_enabled` — `obfuscate_literals` их **не** покрывает. И имейте в виду: неразбираемый запрос обфусцировать нельзя (неизвестно, что в нём литерал), поэтому его текст в лог не попадёт вовсе.

Подробнее о форматах, уровнях и разборе записей — в [мониторинге и логах](./monitoring.md).

## Защита данных при хранении

```bash
# Шифрование томов — на уровне хоста/LVM/LUKS, не средствами Neo4j
cryptsetup luksFormat /dev/vg0/neo4j-data
cryptsetup open /dev/vg0/neo4j-data neo4j-data
# далее монтирование тома в /var/lib/neo4j/data

# Права: каталоги 750, файлы конфигурации 640
sudo find /var/lib/neo4j -type d -exec chmod 750 {} \;
sudo chown -R neo4j:neo4j /var/lib/neo4j/{data,logs,certificates,conf}

# Ограничить маску для новых файлов
umask 077
```

| Сценарий | Рекомендуемый режим |
| :--- | :--- |
| Только владелец | `700` |
| Владелец и конкретная группа | `750` |

Каталог, хранящий чувствительные данные, не должен быть world-readable **или world-executable**: даже при закрытых файлах исполняемый каталог раскрывает структуру. Файлы бэкапов и дампов — те же требования плюс ограничение доступа к месту, где они лежат. Учтите, что `neo4j.conf`, дампы и бэкапы содержат данные в открытом виде: их нужно включать в план ротации и в периметр защиты.

## Восстановление доступа: утрачен пароль или роль admin

Единственный поддерживаемый путь — кратковременное отключение аутентификации **при одновременной изоляции от сети**. Порядок обязателен: сначала сеть, потом auth.

```properties
# 1. Сервер остановлен
dbms.security.auth_enabled=false
server.default_listen_address=127.0.0.1
server.http.enabled=false
```

```bash
# 2. Старт и подключение ТОЛЬКО с localhost
sudo systemctl start neo4j
cypher-shell -d system

# 3. Восстановление пароля администратора
```

```cypher
ALTER USER neo4j SET PASSWORD 'NewStr0ngPass';
-- либо выдать роль admin существующему пользователю:
GRANT ROLE admin TO alice;
```

```bash
# 4. Вернуть настройки и перезапустить
sudo systemctl stop neo4j
# вернуть dbms.security.auth_enabled=true и исходные listen_address
sudo systemctl start neo4j
```

**Восстановление удалённой роли `admin`** требует воспроизвести полный набор привилегий роли — иначе получится роль, которая выглядит как admin, но не может половину операций:

```cypher
CREATE ROLE admin;
GRANT ACCESS ON DATABASE * TO `admin`;
GRANT ALL DBMS PRIVILEGES ON DBMS TO `admin`;
GRANT CONSTRAINT MANAGEMENT ON DATABASE * TO `admin`;
GRANT INDEX MANAGEMENT ON DATABASE * TO `admin`;
GRANT LOAD ON ALL DATA TO `admin`;
GRANT MATCH {*} ON GRAPH * NODE * TO `admin`;
GRANT MATCH {*} ON GRAPH * RELATIONSHIP * TO `admin`;
GRANT NAME MANAGEMENT ON DATABASE * TO `admin`;
GRANT SHOW CONSTRAINT ON DATABASE * TO `admin`;
GRANT SHOW INDEX ON DATABASE * TO `admin`;
GRANT START ON DATABASE * TO `admin`;
GRANT STOP ON DATABASE * TO `admin`;
GRANT TRANSACTION MANAGEMENT (*) ON DATABASE * TO `admin`;
GRANT WRITE ON GRAPH * TO `admin`;
GRANT ROLE admin TO neo4j;
```

> **Окно незащищённости — реальный риск.** Между `auth_enabled=false` и обратным включением любой, кто достигает порта Bolt, получает полный доступ без пароля. Поэтому `server.default_listen_address=127.0.0.1` ставится **до** старта, а `server.http.enabled=false` — в том же изменении, а не по памяти. В кластере процедура выполняется на одном члене, а изоляция обеспечивается на всех.

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Not authorized` при `CALL` процедуры | Процедура не в `dbms.security.procedures.allowlist`, либо на внутренних API и не в `unrestricted` | `SHOW PROCEDURES YIELD name WHERE name = 'apoc.meta.stats'` | Добавить в allowlist / unrestricted — см. [APOC](./apoc.md#модель-безопасности-allowlist-и-unrestricted) |
| Запрос возвращает меньше строк, ошибки нет | Сработал `DENY MATCH` — данные **невидимы**, а не недоступны | `SHOW ROLE r PRIVILEGES` | Проверить, не слишком ли широк `DENY MATCH {*}` вместо точечного |
| Нет прав, хотя `GRANT` выполнен | Не выдан `ACCESS ON DATABASE`, или привилегия задана на другой граф/роль | `SHOW USER u PRIVILEGES` | Выдать `ACCESS ON DATABASE` |
| `MATCH` без `{}` — синтаксическая ошибка | Блок свойств обязателен | — | `GRANT MATCH {*} ON GRAPH ...` |
| `CREATE` на новую метку отклонён | Нет `CREATE NEW LABEL` | `SHOW SUPPORTED PRIVILEGES` | Выдать `CREATE NEW LABEL` (или роль `publisher`) |
| `failed to log in: too many failed attempts` | Сработал `auth_max_failed_attempts` | `logs/security.log` | Подождать `auth_lock_time`; если это перебор — ограничить сеть |
| `PKIX path building failed` на клиенте | Сертификат не выдан доверенным CA либо клиент использует `bolt+s://` с самоподписанным | `openssl s_client -CAfile ...` | В production — CA-сертификат; для теста — `bolt+ssc://` |
| Рукопожатие проходит, трафик открыт | Включена политика, но не выставлен `server.bolt.tls_level` | `openssl s_client` показывает TLS; `cypher-shell -a bolt://` тоже подключается | `server.bolt.tls_level=REQUIRED` |
| Сервер не стартует, ругается на неизвестный параметр | Строгая валидация конфигурации (по умолчанию включена) | `neo4j.log` | Убрать параметры 4.x (`server.ssl.*`) или опечатки; проверить `SHOW SETTINGS` |
| `Unauthorized` при входе после смены `auth_enabled` | Клиент продолжает слать `auth`, а сервер его не требует | `cypher-shell` с теми же учётными данными | Убрать `auth` из драйвера либо вернуть аутентификацию |
| `user_attribute()` даёт `null`, роль не выдаётся | Claim отсутствует в токене | `dbms.security.logs.oidc.jwt_claims_at_debug_level_enabled=true` | Проверить состав claims; правило сработает fail-closed |
| Правило ABAC не сужает права | Роль дополнительно назначена статически через `GRANT ROLE` | `SHOW ROLES WITH USERS`, `SHOW AUTH RULES` | Убрать статическое назначение роли, которую должно выдавать правило |

## Чек-лист production hardening

**Аутентификация**

- [ ] `dbms.security.auth_enabled=true`, `dbms.security.require_local_user=true` при внешних провайдерах
- [ ] Начальный пароль задан через `neo4j-admin dbms set-initial-password --require-password-change`
- [ ] Учётная запись приложения — отдельная, с `SET PASSWORD CHANGE NOT REQUIRED`; пароль из менеджера секретов, не из репозитория
- [ ] Убрана учётная запись `neo4j` из повседневного использования; есть второй администратор
- [ ] Внешняя аутентификация (LDAP/OIDC) переведена на StartTLS/TLS; `implicit` auth flow не используется
- [ ] `auth_lock_time` осознанно выбран для модели угроз

**Авторизация**

- [ ] Приложения работают на собственных ролях, а не на `editor`/`admin`
- [ ] Каждой роли выдан `ACCESS ON DATABASE` ровно на нужные базы
- [ ] Чтение ограничено `MATCH {конкретные свойства}`, а не `{*}`
- [ ] Приватные подграфы закрыты `DENY`, проверено фактическим запросом, а не чтением привилегий
- [ ] `security.log` включён и попадает в централизованный сбор
- [ ] Правовые роли выгружены через `SHOW ROLE ... AS COMMANDS` и хранятся в репозитории

**Код и расширения**

- [ ] `dbms.security.procedures.allowlist` переопределён минимальным списком
- [ ] `dbms.security.procedures.unrestricted` содержит только реально необходимое
- [ ] `dbms.security.allow_csv_import_from_file_urls=false`
- [ ] Каталоги `bin`, `lib`, `plugins` доступны только пользователю `neo4j`
- [ ] В коде нет конкатенации пользовательского ввода в текст Cypher-запроса
- [ ] Метки, типы связей и ключи свойств из пользовательского ввода фильтруются белым списком
- [ ] `apoc.cypher.*` не используется для запросов с пользовательским вводом

**Шифрование**

- [ ] `dbms.ssl.policy.bolt.enabled=true` **и** `server.bolt.tls_level=REQUIRED`
- [ ] Сертификат выдан доверенным CA; клиенты используют `bolt+s://`
- [ ] Приватный ключ в PKCS #8, права `640`, владелец `neo4j`
- [ ] `verify_hostname=true`, `trust_all=false`
- [ ] Кластерная коммуникация и бэкапы зашифрованы с `client_auth=REQUIRE`
- [ ] Проверено, что `bolt://` без TLS отвергается

**Сеть**

- [ ] `server.http.enabled=false` либо включён HTTPS и сужен `server.http_enabled_modules`
- [ ] Кластерные порты 6000, 7000, 7688 не доступны извне (при отсутствии кластеризации — привязаны к `127.0.0.1`)
- [ ] Порт 6362 (backup) закрыт firewall
- [ ] JMX 3637 и JDWP 5005 не слушают наружу
- [ ] `advertised_address` соответствует адресу, видимому клиентом

**Данные и логи**

- [ ] Тома с данными, бэкапами и логами зашифрованы
- [ ] Каталоги `700`/`750`, `neo4j.conf` — `640`
- [ ] `db.logs.query.obfuscate_literals=true`, `db.logs.query.parameter_logging_enabled=false`
- [ ] `dbms.security.log_successful_authentication` выбран осознанно
- [ ] Доступ к бэкапам и дампам ограничен, учтена их ротация

**Обновления**

- [ ] Установлен последний патч релиза; заведён процесс обновления по публикации advisories
- [ ] Перед обновлением с 5.26 LTS базы Enterprise переведены в формат `block`

## См. также

- **[Обзор Neo4j](./overview.md)** — редакции и лицензии, версии и поддержка, порты и коннекторы.
- **[Мультитенантность и composite databases](./multi_tenancy.md)** — изоляция данных и прав доступа по базам и алиасам.
- **[CDC и интеграция с потоками](./cdc_integration.md)** — привилегии `EXECUTE BOOSTED`, доступ к базе для потребителей потока.
- **[APOC: библиотека расширений](./apoc.md)** — allowlist/unrestricted, SSRF, фоновые задачи.
- **[Драйверы для приложений](./drivers.md)** — `bolt+s://` vs `bolt+ssc://`, mTLS, схемы аутентификации, TLS-контекст.
- **[Обслуживание и эксплуатация](./operations.md)** — бэкап и восстановление, метрики, диагностика.
- **[Установка и настройка](./installation_and_setup.md)** — развёртывание, начальная конфигурация, Docker Compose.
- **[Кластеризация и HA](./clustering.md)** — топология, межкластеровое шифрование.
- **[Безопасная установка СУБД](../installation_security.md)** — общие принципы закалки СУБД.
- **Документация:** [Security checklist](https://neo4j.com/docs/operations-manual/current/security/checklist/) · [SSL framework](https://neo4j.com/docs/operations-manual/current/security/ssl-framework/) · [Authentication and authorization](https://neo4j.com/docs/operations-manual/current/authentication-authorization/) · [Built-in roles and privileges](https://neo4j.com/docs/operations-manual/current/authentication-authorization/built-in-roles/) · [Securing extensions](https://neo4j.com/docs/operations-manual/current/security/securing-extensions/) · [Attribute-based access control](https://neo4j.com/docs/operations-manual/current/authentication-authorization/attribute-based-access-control/)
