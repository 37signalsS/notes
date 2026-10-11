# ProxySQL: Connection Pool и Multiplexing

**Актуально для:** ProxySQL 3.0.x / 3.1.x

## Определения

| Термин | Значение |
| :--- | :--- |
| **Multiplexing** | Механизм, при котором одно физическое соединение ProxySQL → бэкенд обслуживает несколько клиентских сессий одновременно |
| **Connection Pool** | Пул физических соединений к бэкендам, которым управляет Hostgroup Manager; хранится отдельно для каждой пары (hostgroup, сервер) |
| **Hostgroup Manager** | Компонент, определяющий, можно ли безопасно разделить соединение между сессиями, и удерживающий свободные соединения в пуле |
| **Pinning (закрепление)** | Ситуация, когда клиентская сессия более не может использовать мультиплексинг и закрепляется за конкретным соединением пула |
| **`mysql-max_connections`** | Максимум клиентских (фронтендных) соединений, которые ProxySQL принимает суммарно. Дефолт `10000` (подтверждён в исходном коде `lib/MySQL_Thread.cpp`, ветка v3.0: `variables.max_connections=10*1000`) |
| **`max_connections` в `mysql_servers`** | Максимум соединений пула к одному бэкенду. Дефолт `1000` |
| **`mysql-free_connections_pct`** | Доля от `max_connections` **каждого сервера в `mysql_servers`**, которую Hostgroup Manager держит свободной в пуле. Дефолт `10` (10%) |
| **Connection Warming** | Фоновое досоздание соединений пула до расчётного уровня (`mysql-connection_warming`, дефолт `false`) |
| **ConnUsed / ConnFree / ConnOK / ConnERR / MaxConnUsed** | Столбцы `stats_mysql_connection_pool`: соединения в использовании / свободные / успешно установленные за всё время / неудачные попытки / максимум одновременно использованных |
| **SHUNNED** | Временное исключение сервера из ротации монитором (серия неудачных проверок или превышение лага репликации) |
| **`stats_mysql_processlist`** | Таблица Admin-интерфейса со снимком клиентских сессий; столбец `extended_info` (JSON) содержит причины отключения мультиплексирования |

## Теоретический блок

### Зачем нужен мультиплексинг

Проблема, которую решает ProxySQL, не в соединениях **к** прокси, а в соединениях **между** прокси и бэкендом.

MySQL создаёт отдельный поток на каждое входящее соединение. Если 10 000 клиентских соединений подключаются напрямую к одному бэкенду, MySQL создаёт 10 000 потоков, что деградирует производительность даже при простаивающих соединениях. ProxySQL использует пул потоков (thread pool), а multiplexing дополнительно сокращает число соединений к бэкендам: например, 200 физических соединений обслуживают 10 000 клиентских сессий.

Отсюда формула масштабирования:

```
клиентские соединения = соединения_пула × число_мультиплексируемых_сессий_на_соединение
```

При типичной нагрузке (OLTP-запросы, соединение не удерживается постоянно) одна сессия может multiplex'иться с десятками других.

### Как работает мультиплексинг

Соединения к бэкендам **не предаллоцируются**: при старте ProxySQL держит 0 соединений, и каждое создаётся по требованию, когда для него нашлась клиентская сессия.

Когда сессия завершает запрос, соединение возвращается в Hostgroup Manager. Manager проверяет, **безопасно ли разделить** соединение между сессиями (то есть не осталось ли на нём состояния, привязанного к сессии — полный перечень ниже). Если соединение безопасно и пул не переполнен, оно помещается в пул и может быть назначено следующей клиентской сессии.

Свободные соединения поддерживаются живыми периодическими пингами; соединение считается idle, если не использовалось с последнего круга пингов. Интервал между кругами пингов — `mysql-ping_interval_server_msec` (дефолт `120000` мс).

**Следствие для мониторинга:** «свободное» соединение пула и «неиспользуемое» — разные вещи. Реальная загрузка видна в `stats_mysql_connection_pool` (колонки `ConnUsed`/`ConnFree`) и `stats_mysql_processlist`, а не в суммарном счётчике соединений.

### Условия отключения мультиплексинга

Это главный практический раздел. Multiplexing **отключается** при выполнении любого из условий:

| Условие | Действие до возобновления |
| :--- | :--- |
| Активная транзакция (`BEGIN` без `COMMIT`/`ROLLBACK`) | До `COMMIT`/`ROLLBACK` |
| `LOCK TABLE` / `LOCK TABLES` / `FLUSH TABLES WITH READ LOCK` | До `UNLOCK TABLES` |
| `GET_LOCK()` | Отключение **постоянное** для соединения |
| Пользовательские переменные (`@var` в query digest) | Отключение **постоянное** для соединения |
| `SET SQL_SAFE_UPDATES=?`, `SET SQL_SELECT_LIMIT=?`, `SET MAX_JOIN_SIZE=?` (в т.ч. `mysql --safe-updates`), `SET FOREIGN_KEY_CHECKS`, `SET UNIQUE_CHECKS`, `SET AUTO_INCREMENT_INCREMENT`, `SET AUTO_INCREMENT_OFFSET`, `SET GROUP_CONCAT_MAX_LEN` | Отключение **постоянное** для соединения |
| `SELECT ... SQL_CALC_FOUND_ROWS` | Отключение **постоянное** для соединения |
| `CREATE TEMPORARY TABLE` | Отключение **постоянное** для соединения |
| `PREPARE` (text-протокол, не binary) | Отключение **постоянное** для соединения |
| `SET SQL_LOG_BIN=0` | Пока не вернуть `SQL_LOG_BIN=1` |
| `mysql-multiplexing = false` | Глобально для всех сессий |
| `mysql-auto_increment_delay_multiplex` (дефолт `5`) | После OK-пакета с `last_insert_id` мультиплексинг отключён на следующие N запросов — защита корректности `LAST_INSERT_ID()` |
| `mysql-connection_delay_multiplex_ms` (дефолт `0`, макс. `300000`) | Мультиплексинг держится отключённым X мс после запроса — полезно для батчинга, когда сессия сразу шлёт следующий запрос |
| `autocommit=0` при `mysql-autocommit_false_is_transaction=true` (дефолт `false`) | Трактуется как активная транзакция; при `mysql-autocommit_false_not_reusable=true` соединение дополнительно уничтожается при возврате в пул |
| `last_errno != 0` на соединении | Пока ошибка не сброшена (`last_errno = 0`) |

**Два исключения, захардкоженных в коде** (многие приложения выполняют их при каждом соединении): `SELECT @@tx_isolation` и `SELECT @@version` **не** отключают мультиплексинг. Список настраивается переменной `mysql-keep_multiplexing_variables` (дефолт `tx_isolation,version`).

**Управление через правила.** В `mysql_query_rules` столбец `multiplex` принимает значения: `0` — отключить мультиплексинг для подходящих запросов, `1` — разрешить (может быть включён снова, если нет других условий), `2` — не отключать мультиплексинг даже для запросов с `@var`.

**Почему это важно на практике:** приложение может не использовать ни одного из этих механизмов явно, но получить pinning из-за ORM. Многие ORM выполняют `SET` сессионных переменных (например, `sql_mode`) или запрашивают `@@...` при установлении соединения. Результат — multiplexing отключается для всех соединений пула, и весь эффект пулинга теряется, хотя в коде приложения ничего «необычного» нет.

**Побочный эффект временных таблиц:** отключение мультиплексинга не отключает маршрутизацию. Если после `CREATE TEMPORARY TABLE` следующий `SELECT` на ту же таблицу уйдёт в другой hostgroup (по правилу), на бэкенде вернётся ошибка «`schemaname.temporary_tablename` doesn't exist». Лечение — правила маршрутизации, а не пул.

**Поведение с OFFLINE_SOFT.** Если по любой из причин выше мультиплексинг отключён, активное соединение остаётся на сервере, переведённом в `OFFLINE_SOFT`, и запросы продолжают на него маршрутизироваться. Если причиной была транзакция — после её завершения соединение автоматически уходит с `OFFLINE_SOFT`-узла. Приложениям с собственным пулом следует рециклировать соединения **до** failover'а.

### Отслеживание причин через `extended_info`

С версии 2.0 поле `extended_info` в `stats_mysql_processlist` содержит **JSON** с деталями сессии. Это основной инструмент при разборе «пул не работает». Ключевые поля внутри `$.backends[0].conn`:

| Поле JSON | Когда указывает на отключение мультиплексинга |
| :--- | :--- |
| `MultiplexDisabled` | `true` — мультиплексинг отключён глобально (`mysql-multiplexing=false`) |
| `sql_log_bin` | `"0"` — выполнен `SET SQL_LOG_BIN=0` |
| `status.user_variable` | `true` — установлены пользовательские переменные |
| `status.temporary_table` | `true` — используется временная таблица |
| `status.get_lock` | `true` — использовалась `GET_LOCK()` |
| `status.lock_tables` | `true` — выполнены `LOCK TABLES` |
| `status.found_rows` | `true` — флаг FOUND_ROWS (например, `SQL_CALC_FOUND_ROWS`) |
| `status.no_multiplex` | `true` — мультиплексинг отключён для этой сессии |
| `mysql.server_status` | нечётное значение — активна транзакция (`SERVER_STATUS_IN_TRANS` = бит `0x0001` в флагах статуса MySQL) |
| `mysql.net.last_errno` | `!= 0` — на соединении не сброшенная ошибка бэкенда |
| `autocommit` | `"OFF"` при `mysql-autocommit_false_is_transaction=true` трактуется как транзакция |

Сессии, которые выполняют запрос или имеют отключённый мультиплексинг, — это как раз те, у которых в `extended_info` заполнен массив `backends`. Простаивающие сессии без привязки к бэкенду возвращают `NULL` по путям `$.backends[0]...`.

### Расчёт размеров пула

#### Четыре уровня лимитов

| Уровень | Параметр | Дефолт | Что ограничивает |
| :--- | :--- | :--- | :--- |
| ProxySQL, вход | `mysql-max_connections` | `10000` | Сколько клиентских соединений ProxySQL примет суммарно |
| ProxySQL, вход, на пользователя | `max_connections` в `mysql_users` | `10000` | Сколько одновременных сессий может иметь один пользователь |
| ProxySQL, выход | `max_connections` в `mysql_servers` | `1000` | Сколько соединений пула открыто к одному бэкенду |
| Бэкенд | `max_connections` в MySQL/MariaDB | зависит от сервера | Сколько соединений бэкенд примет в сумме |

**Правило согласования:** `max_connections` на бэкенде должен быть **больше** суммы `max_connections` всех ProxySQL-узлов, обращающихся к нему, плюс запас на прямые подключения (мониторинг, репликация, админские инструменты).

Пример: 3 узла ProxySQL, у каждого `max_connections = 200` в `mysql_servers` для одного бэкенда. Требуемый `max_connections` бэкенда: `3 × 200 = 600` плюс запас на репликацию и прямые подключения → `800`.

При достижении входного лимита новые клиентские соединения отклоняются с ошибкой MySQL **1040, SQLSTATE `08004`, текст «Too many connections»** (в исходном коде: `generate_pkt_ERR(...1040, "08004", "Too many connections"...)`; в логе ProxySQL — предупреждение `mysql-max_connections reached`).

#### `mysql-free_connections_pct`

Переменная задаёт долю от `max_connections` **каждого сервера в `mysql_servers`** (а не от глобального `mysql-max_connections`), которую Hostgroup Manager обязан держать свободной в пуле. Дефолт `10` (10%).

Для каждой пары (hostgroup, бэкенд) пул удерживает до:

```
mysql-free_connections_pct × mysql_servers.max_connections / 100
```

свободных соединений. Например, при `free_connections_pct = 10` и `mysql_servers.max_connections = 300` пул держит до 30 свободных соединений к этому бэкенду. Свободные соединения поддерживаются живыми пингами с интервалом `mysql-ping_interval_server_msec`.

Смысл резерва: если свободных соединений не осталось, новые клиентские сессии будут ждать создания соединения или получать ошибку — даже если часть занятых сессий вот-вот завершится. Включённый `mysql-connection_warming` досоздаёт соединения до расчётного уровня автоматически.

#### Переопределения на уровне hostgroup

С версии 2.5 таблица `mysql_hostgroup_attributes` задаёт настройки для конкретного hostgroup, перекрывая глобальные: `free_connections_pct` (дефолт `10`), `multiplex` (дефолт `1`), `connection_warming` (дефолт `0`), `throttle_connections_per_sec` (лимит новых соединений в секунду для hostgroup), `init_connect` (SQL-инициализация каждого соединения пула в hostgroup), `hostgroup_settings` (JSON, например `{"default_query_timeout": 5000}`), `servers_defaults` (JSON-дефолты `weight`, `max_connections`, `use_ssl` для автоматически обнаруживаемых серверов). Применяется вместе с модулем серверов: `LOAD MYSQL SERVERS TO RUNTIME; SAVE MYSQL SERVERS TO DISK;`. Проверка консистентности слоёв — `CHECKSUM MYSQL HOSTGROUP ATTRIBUTES`.

### Жизненный цикл соединений

| Переменная | Дефолт | Назначение |
| :--- | :--- | :--- |
| `mysql-connection_warming` | `false` | Фоновое досоздание соединений до расчётного уровня (`free_connections_pct × max_connections / 100`) |
| `mysql-connection_max_age_ms` | `0` (макс. `86400000`, 24 ч) | Неиспользуемые соединения пула, созданные более N мс назад, закрываются. `0` — без ограничения по возрасту |
| `mysql-ping_interval_server_msec` | `120000` | Интервал круга пингов для idle-соединений пула |
| `mysql-connection_delay_multiplex_ms` | `0` (макс. `300000`) | Держать мультиплексинг отключённым X мс после запроса (батчинг) |
| `mysql-auto_increment_delay_multiplex` | `5` | Отключать мультиплексинг на N запросов после OK-пакета с `last_insert_id` |
| `mysql-auto_increment_delay_multiplex_timeout_ms` | `10000` (с 2.4.0) | Через сколько мс счётчик `auto_increment_delay_multiplex` сбрасывается |
| `mysql-throttle_connections_per_sec_to_hostgroup` | `1000000` | Максимум новых соединений в секунду к одному hostgroup |

**Практический смысл `connection_max_age_ms`.** Долгоживущие соединения пула — источник проблем: накопление состояния, рассинхронизация с изменениями на бэкенде, «мёртвые» соединения после длительного простоя. Ненулевое значение заставляет пул периодически пересоздавать соединения. Важная деталь: при достижении возраста соединение закрывается **без** `COM_QUIT`, поэтому в логах MySQL могут появляться предупреждения `Aborted connection` — это штатное поведение (GH #1861).

### Распределение нагрузки: `weight`

`weight` определяет вероятность выбора сервера из hostgroup: чем больше вес сервера относительно других, тем выше вероятность его выбора. Алгоритм балансировки по умолчанию — **random-weighted** (случайный с весами). Дефолт `weight = 1`, диапазон `0..10000000`.

```sql
-- Сервер с большей производительностью получает примерно вдвое больше соединений
UPDATE mysql_servers SET weight = 100 WHERE hostname = 'db-reader-big';
UPDATE mysql_servers SET weight = 50  WHERE hostname = 'db-reader-small';
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

Соотношение `100 : 50` даёт примерно 2:1 по числу соединений **в среднем и при большом числе новых соединений**; на малых объёмах трафика распределение отклоняется от пропорций из-за случайности алгоритма. Учтите: `max_connections` на сервере — жёсткий потолок: даже при максимальном весе новых соединений к серверу не будет после его достижения.

## Практический блок

### Диагностика состояния пула

```sql
-- Общая картина по hostgroup: сколько соединений в каждом статусе
SELECT hostgroup, srv_host, srv_port, status,
       ConnUsed, ConnFree, ConnOK, ConnERR, MaxConnUsed,
       Queries, Latency_us
FROM stats_mysql_connection_pool
ORDER BY hostgroup, srv_host;
# → hostgroup | srv_host   | status  | ConnUsed | ConnFree | ConnOK | ConnERR | MaxConnUsed
# → 20        | db-reader-1 | ONLINE | 74       | 106      | 524    | 0       | 180
# → 20        | db-reader-2 | ONLINE | 71       | 105      | 511    | 0       | 176
# → 10        | db-writer-1 | ONLINE | 186      | 14       | 197    | 2       | 199
```

Статусы в колонке `status`: `ONLINE`, `SHUNNED`, `OFFLINE_SOFT`, `OFFLINE_HARD`. Сервер, входящий в несколько hostgroup, отображается отдельной строкой в каждом.

**Ключевые счётчики:**

| Столбец | Что показывает |
| :--- | :--- |
| `ConnUsed` | Соединения, которыми прямо сейчас выполняются запросы |
| `ConnFree` | Простаивающие соединения, удерживаемые в пуле |
| `ConnOK` / `ConnERR` | Успешные / неудачные попытки соединений за всё время (рост `ConnERR` — сигнал проблем с бэкендом) |
| `MaxConnUsed` | Максимум одновременно использованных соединений (high water mark) — база для подбора `mysql_servers.max_connections` |
| `Queries` | Число запросов, направленных на этот бэкенд |
| `Latency_us` | Текущий пинг до бэкенда в микросекундах (данные монитора) |

Дополнительно доступны: `stats_mysql_free_connections` — список свободных соединений пула (`fd`, `hostgroup`, `srv_host`, `srv_port`, `user`, `schema`, `init_connect`, `time_zone`, `sql_mode`, `autocommit`, `idle_ms`, `statistics`, `mysql_info`) — для разбора, какие именно соединения простаивают; и `stats_mysql_connection_pool_reset` — та же схема, что у `stats_mysql_connection_pool`, но со сбросом счётчиков.

> **Диагностика.** Сам по себе `status = ONLINE` мало о чём говорит: соединения могут быть `ONLINE`, но мультиплексироваться с одним клиентом или ни с одним. Чтобы понять реальную эффективность пула, смотрите на соотношение `ConnUsed + ConnFree` и числа клиентских сессий в `stats_mysql_processlist`.

### Проверка фактического мультиплексирования

```sql
-- Соотношение физических соединений пула и клиентских сессий.
-- Большее значение client_sessions / pool_connections означает более эффективный мультиплексинг.
SELECT (SELECT SUM(ConnUsed) + SUM(ConnFree)
        FROM stats_mysql_connection_pool) AS pool_connections,
       (SELECT COUNT(*)
        FROM stats_mysql_processlist)      AS client_sessions;
# → pool_connections | client_sessions
# → 555              | 4200
```

Если `client_sessions` лишь незначительно превышает `pool_connections`, мультиплексинг фактически не работает. Причину покажет `extended_info`:

```sql
-- Топ причин отключения мультиплексирования (JSON-поля из extended_info)
SELECT
  CASE
    WHEN JSON_EXTRACT(extended_info, '$.backends[0].conn.MultiplexDisabled') = 1
      THEN 'multiplexing disabled globally'
    WHEN JSON_EXTRACT(extended_info, '$.backends[0].conn.status.user_variable') = 1
      THEN 'user variables (@var)'
    WHEN JSON_EXTRACT(extended_info, '$.backends[0].conn.status.temporary_table') = 1
      THEN 'temporary table'
    WHEN JSON_EXTRACT(extended_info, '$.backends[0].conn.status.get_lock') = 1
      THEN 'GET_LOCK()'
    WHEN JSON_EXTRACT(extended_info, '$.backends[0].conn.status.lock_tables') = 1
      THEN 'LOCK TABLES'
    WHEN JSON_EXTRACT(extended_info, '$.backends[0].conn.status.found_rows') = 1
      THEN 'SQL_CALC_FOUND_ROWS'
    WHEN JSON_EXTRACT(extended_info, '$.backends[0].conn.mysql.server_status') % 2 = 1
      THEN 'active transaction'
    WHEN JSON_EXTRACT(extended_info, '$.backends[0].conn.mysql.net.last_errno') != 0
      THEN 'backend error not cleared'
    ELSE 'other condition'
  END AS reason,
  COUNT(*) AS sessions
FROM stats_mysql_processlist
WHERE extended_info IS NOT NULL AND extended_info != ''
  AND JSON_EXTRACT(extended_info, '$.backends[0].conn') IS NOT NULL
GROUP BY reason
ORDER BY sessions DESC;
# → reason                   | sessions
# → user variables (@var)    | 1840
# → active transaction       | 210
```

**Прямая диагностика сессий с привязкой к бэкенду:**

```sql
SELECT SessionID, user, cli_host, cli_port, hostgroup,
       srv_host, srv_port, command, time_ms, status_flags, extended_info
FROM stats_mysql_processlist
WHERE extended_info IS NOT NULL AND extended_info != ''
ORDER BY time_ms DESC
LIMIT 20;
```

> **Важно:** в `stats_mysql_processlist` нет колонок `username`, `client`, `server`, `state`, `shard_id` — используются `user`, `cli_host`/`cli_port`, `srv_host`/`srv_port`, `command`. Данные — снимок в момент времени; через долю секунды состав может измениться.

### Настройка пула для высокой конкурентности

```sql
-- 1. Общий лимит клиентских соединений (дефолт 10000)
UPDATE global_variables SET variable_value = '20000'
WHERE variable_name = 'mysql-max_connections';

-- 2. Держать 10% от max_connections каждого сервера свободными
UPDATE global_variables SET variable_value = '10'
WHERE variable_name = 'mysql-free_connections_pct';

-- 3. Фоновое досоздание соединений до расчётного уровня
UPDATE global_variables SET variable_value = 'true'
WHERE variable_name = 'mysql-connection_warming';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
-- С 3.0.10 LOAD ... VARIABLES TO RUNTIME возвращает сводку в поле information пакета OK:
-- → OK. Records: <число строк в таблице> Updated: 3 Rejected: 0 Unknown: 0
-- Rejected > 0 — известная переменная с непрошедшей валидацию значением
-- (значение не активировано, восстановлено прежнее); Unknown > 0 — имя не поддерживается
-- этой версией. Команда вернёт OK и при ненулевых Rejected/Unknown — проверяйте сводку.
```

```sql
-- 4. Лимит соединений к бэкендам и веса для распределения нагрузки
UPDATE mysql_servers
SET max_connections = 300, weight = 1000
WHERE hostgroup_id = 20;
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

**Проверка:**

```sql
SELECT variable_name, variable_value FROM global_variables
WHERE variable_name IN ('mysql-max_connections',
                        'mysql-free_connections_pct',
                        'mysql-connection_warming');
# → variable_name               | variable_value
# → mysql-max_connections       | 20000
# → mysql-free_connections_pct  | 10
# → mysql-connection_warming    | true
```

### Лимиты на уровне пользователей

`mysql-max_connections = 10000` — общий лимит, а не лимит на пользователя. Если приложение открывает 3000 соединений, а другой пользователь — 8000, третья волна получит ошибку 1040 независимо от состояния бэкендов.

При большом числе приложений задавайте лимиты на уровне пользователей (`max_connections` в `mysql_users`, дефолт `10000`, `NOT NULL`):

```sql
INSERT INTO mysql_users (username, default_hostgroup, max_connections, transaction_persistent)
VALUES ('app_reporting', 20, 100, 0);
-- max_connections ограничивает число одновременных клиентских сессий пользователя;
-- transaction_persistent=0 разрешает покидать default_hostgroup вне транзакций
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

### Когда мультиплексинг мешает

| Сценарий | Проблема | Решение |
| :--- | :--- | :--- |
| Все сессии постоянно закреплены (все в транзакциях, `GET_LOCK`, `@var`) | Экономии нет: соединений ≈ число сессий, есть только накладные расходы | Подобрать `mysql_servers.max_connections` под фактическое число закреплённых сессий; убрать причины pinning |
| Сессии удерживают соединения часами (длинные запросы, удержание в приложении) | Каждая сессия держит своё соединение, пул разрастается | Увеличить `mysql_servers.max_connections`; искать длинные запросы через `stats_mysql_processlist` (`time_ms`) |
| ORM проверяет/устанавливает `sql_mode` при каждом соединении | Массовый pinning из-за `SET` | Убрать потребность в `SET`: задать `mysql-default_sql_mode` (и другие `mysql-default_*`), либо правило `mysql_query_rules` с `OK_msg`, возвращающим OK без выполнения запроса, либо `multiplex=2` для запросов с `@` |
| Приложение полагается на `LAST_INSERT_ID()` нестандартным образом | Запрос с `LAST_INSERT_ID()` может выполниться на другом соединении | Оставить `mysql-auto_increment_delay_multiplex = 5` (дефолт) или увеличить; `SELECT LAST_INSERT_ID()`, `SELECT LAST_INSERT_ID() LIMIT 1`, `SELECT @@IDENTITY` обрабатываются корректно и при 0 |
| Транзакции должны идти на один и тот же бэкенд | Переключение между соединениями внутри транзакции нежелательно | `transaction_persistent = 1` (дефолт) для пользователя — транзакция остаётся в том же hostgroup |

### Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Клиенты получают ошибку **1040, SQLSTATE 08004, «Too many connections»** | Достигнут `mysql-max_connections` или `max_connections` пользователя в `mysql_users` | Увеличить лимит либо найти утечку клиентских сессий в приложении; в логе ProxySQL — `mysql-max_connections reached` |
| Ошибка **9001: «Max connect timeout reached while reaching hostgroup N after Xms»** | Ни один бэкенд hostgroup не отвечает в пределах `mysql-connect_timeout_server_max` (дефолт `10000` мс) | Проверить доступность бэкендов; подобрать `mysql-connect_timeout_server` (дефолт `1000`) и `mysql-connect_timeout_server_max` |
| Ошибка **9002: «Max connect failure while reaching hostgroup N»** | Исчерпано `mysql-connect_retries_on_failure` (дефолт `10`) попыток | Проверить бэкенд; подобрать `mysql-connect_retries_on_failure` и `mysql-connect_retries_delay` (дефолт `1` мс). Высокое значение заметно увеличивает латентность ответа об ошибке |
| Ошибка **9004: «Backend Offline Detected»** | Сервер в `OFFLINE_SOFT`/`OFFLINE_HARD` или исключён монитором | Проверить `runtime_mysql_servers` и статус в `stats_mysql_connection_pool` |
| Ошибка **9006: «Connection is locked to hostgroup X but trying to reach hostgroup Y»** | Сессия привязана к hostgroup (транзакция + `transaction_persistent`), а запрос маршрутизирован в другой | Не менять маршрутизацию внутри транзакции; проверить правила |
| Сервер `SHUNNED` в `stats_mysql_connection_pool` | Число ошибок соединений к одному серверу в течение 1 с превысило `mysql-shun_on_failures` (дефолт `5`), либо превышен `max_replication_lag` | Разобрать монитор; возврат в `ONLINE` требует и доступности, и активности пула для этого hostgroup (`mysql-shun_recovery_time_sec`, дефолт `10`) |
| Multiplexing не работает | Массовый pinning из-за `SET`, транзакций, `@var`, временных таблиц | Изучить `extended_info` (см. выше) и устранить причину |
| `Too many connections` **на бэкенде** | Сумма `max_connections` по всем ProxySQL-узлам превышает лимит бэкенда | Снизить `mysql_servers.max_connections`, согласовать с `max_connections` бэкенда |
| Пул не держит резерв свободных соединений | `mysql-free_connections_pct` слишком мал при пиковых нагрузках | Увеличить процент или включить `mysql-connection_warming` (расчёт: `pct × max_connections / 100` на сервер) |
| Медленный первый запрос после простоя | Соединение пула было закрыто бэкендом по его `wait_timeout` и пересоздаётся | Обеспечить `mysql-ping_interval_server_msec` < `wait_timeout` бэкенда; включить `mysql-connection_warming` |
| «Aborted connection» в логах MySQL после правки пула | `mysql-connection_max_age_ms` закрывает соединения без `COM_QUIT` | Штатное поведение; проигнорировать или снизить `connection_max_age_ms` |
| `ConnERR` растёт, `ConnUsed` не падает | Ошибки установления соединений к бэкенду | Проверить `ConnERR` по серверам, сетевую доступность и учётные данные |

### Проверка и валидация после изменений

```sql
-- Комплексная проверка после изменения лимитов
SELECT
  (SELECT SUM(ConnUsed) FROM stats_mysql_connection_pool) AS used_connections,
  (SELECT SUM(ConnFree) FROM stats_mysql_connection_pool) AS free_connections,
  (SELECT SUM(ConnERR) FROM stats_mysql_connection_pool) AS failed_connects,
  (SELECT SUM(MaxConnUsed) FROM stats_mysql_connection_pool) AS max_used_high_water,
  (SELECT COUNT(*) FROM stats_mysql_processlist) AS client_sessions,
  (SELECT variable_value FROM global_variables
   WHERE variable_name = 'mysql-max_connections') AS max_client_connections;
# → used_connections | free_connections | failed_connects | max_used_high_water | client_sessions | max_client_connections
# → 480              | 75               | 0               | 520                 | 4200            | 20000
```

**Критерии успеха:**
- `failed_connects = 0` (или не растёт) — соединения к бэкендам стабильны.
- `client_sessions` заметно больше `used_connections + free_connections` — мультиплексинг работает.
- `client_sessions < max_client_connections` — запас по входному лимиту есть.
- `used_connections + free_connections` ≤ суммы `mysql_servers.max_connections` — пул в пределах настроенных лимитов; `MaxConnUsed` показывает, был ли потолок достигнут ранее.

### Очистка и откат

```sql
-- Откат изменённых переменных к значениям, сохранённым на диске:
-- LOAD ... FROM DISK читает Disk в Memory, затем TO RUNTIME применяет в Runtime
LOAD MYSQL VARIABLES FROM DISK;
LOAD MYSQL VARIABLES TO RUNTIME;

-- Возврат лимита соединений к значению по умолчанию
UPDATE global_variables SET variable_value = '10000'
WHERE variable_name = 'mysql-max_connections';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

```sql
-- Снять пользовательский лимит (дефолт mysql_users.max_connections — 10000;
-- столбец NOT NULL, NULL установить нельзя)
UPDATE mysql_users SET max_connections = 10000 WHERE username = 'app_reporting';
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

## Дополнительная информация

### См. также
- **[ProxySQL: Обзор](./proxysql_overview.md)** — архитектура и базовая настройка.
- **[ProxySQL: Конфигурация и переменные](./proxysql_configuration.md)** — слои конфигурации, LOAD/SAVE, переменные.
- **[ProxySQL: Транзакции и prepared statements](./proxysql_transactions.md)** — главные причины pinning.
- **[ProxySQL: Failover и мониторинг репликации](./proxysql_failover.md)** — поведение пула при исключении сервера.
- **[ProxySQL: Мониторинг](./proxysql_monitoring.md)** — метрики пула, схемы stats-таблиц и алертинг.
- **[Connection Pooling](../../../Networking/Concepts/connection_pooling.md)** — общие принципы пулинга соединений.

### Официальная документация
- [Multiplexing](https://proxysql.com/documentation/multiplexing/) — условия отключения мультиплексинга и `extended_info`
- [MySQL Stats Tables](https://proxysql.com/documentation/the-admin-schemas/stats/stats-mysql/) — схемы `stats_mysql_connection_pool` и `stats_mysql_processlist`
- [MySQL Variables](https://proxysql.com/documentation/global-variables/mysql-variables/) — `mysql-free_connections_pct`, `mysql-connection_warming`, `mysql-connection_max_age_ms`
- [Backend Server Configuration](https://proxysql.com/documentation/backend-server-configuration/) — `mysql_servers`, `weight`, статусы
- [MySQL Users Management](https://proxysql.com/documentation/users-management/mysql-users-management/) — `mysql_users.max_connections`
- [ProxySQL Error Codes](https://proxysql.com/documentation/error-codes/) — ошибки 9001–9006
- [Admin Commands](https://proxysql.com/documentation/the-admin-schemas/admin-commands/) — LOAD/SAVE, формат сводки `Records/Updated/Rejected/Unknown`
