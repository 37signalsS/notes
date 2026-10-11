# MariaDB MaxScale: Read/Write Split — расширенная маршрутизация

**Актуально для:** MaxScale 25.10.x

## Определения

*   **slave_selection_criteria** — критерий выбора реплики для чтения. По умолчанию `least_current_operations` (реплика с наименьшим числом активных операций).
*   **server rank** — приоритет сервера (`rank=` в секции сервера). Общее правило: `primary` используется раньше `secondary`; readwritesplit — исключение (см. «Server Ranks»).
*   **master_failure_mode** — поведение роутера при потере Primary: `fail_instantly`, `fail_on_write`, `error_on_write`.
*   **master_reconnection** — возможность прозрачного переподключения сессии к новому Primary mid-session.
*   **causal_reads** — гарантия причинно-следственной консистентности чтения: запись, сделанная в этой сессии, гарантированно видна последующим чтениям.
*   **sync_transaction** — ожидание репликации транзакции на одном или нескольких серверах перед подтверждением `COMMIT` клиенту (аналог semi-sync, но на уровне MaxScale).
*   **transaction_replay** — автоматический перенос прерванной транзакции на новый сервер без видимости для клиента.
*   **delayed_retry** — отложенный повтор маршрутизации запроса, если целевой сервер временно недоступен.
*   **retry_failed_reads** — повтор autocommit-`SELECT` на заменяющем сервере при отказе реплики.
*   **max_slave_connections / slave_connections** — жёсткий и мягкий лимит числа соединений сессии к репликам.
*   **session command history** (`max_sescmd_history`, `prune_sescmd_history`, `disable_sescmd_history`) — буфер сессионных команд, воспроизводимых на новом соединении при reconnect; см. [Configuration Guide](https://mariadb.com/docs/maxscale/maxscale-management/deployment/installation-and-configuration/maxscale-configuration-guide.md).
*   **routing hints** — SQL-комментарии-подсказки (`/* route to master */` и др.), влияющие на маршрутизацию отдельного запроса.
*   **strict_tmp_tables / strict_multi_stmt / strict_sp_calls** — параметры, запрещающие переключение сервера при наличии состояния, привязанного к соединению.

## Теоретический блок

### Как readwritesplit распределяет запросы

Роутер разбирает каждый запрос и классифицирует его. Четыре класса маршрутизации:

**1. На Primary** (безопасность данных: большинство записей попадает в binlog и реплицируется):

*   DML (`INSERT`, `UPDATE`, `DELETE` и др.) и DDL (`DROP`, `CREATE`, `ALTER` и др.).
*   Все операторы внутри открытой read-write транзакции.
*   Вызовы хранимых процедур и UDF.
*   Запросы к временным таблицам, созданным в этой же сессии.
*   Запросы к последовательностям (`NEXT VALUE FOR seq`, `NEXTVAL(seq)`, `seq.nextval`).
*   Операторы с функциями `LAST_INSERT_ID()`, `GET_LOCK()`, `RELEASE_LOCK()`, `IS_USED_LOCK()`, `IS_FREE_LOCK()` или переменными `@@last_insert_id`, `@@identity`.
*   Чтения с `causal_reads`, у которых истёк таймаут на реплике.
*   Команды репликации Primary (например, `SHOW MASTER STATUS`).
*   Multi-statement запросы (несколько операторов в одном пакете) — всегда на Primary.
*   Если для всех реплик лаг превышает `max_replication_lag`.

**2. На реплики:**

*   Read-only операторы (`SELECT`, `SHOW`) вне транзакций при включённом `autocommit`, использующие только read-only встроенные функции.
*   Все операторы внутри явной read-only транзакции (`START TRANSACTION READ ONLY`).

**3. На все бэкенды сессии** (сессионные команды — влияют на будущие результаты и должны быть воспроизведены везде):

*   Изменение состояния сессии (`SET`, `USE`, `CHANGE USER`), текстовый `PREPARE`, бинарные prepared statements, служебные команды (`COM_QUIT`, `COM_PING`).
*   Присваивание переменной внутри оператора записи идёт только на Primary: `INSERT INTO t1 VALUES (@myvar:=5, 7)`.
*   Роутер хранит историю сессионных команд, чтобы воспроизвести её на новом соединении при отказе (объём — `max_sescmd_history`).

**4. На тот же сервер, что и предыдущий запрос** (если предыдущей цели нет — на Primary):

*   `FOUND_ROWS()` — на сервер последнего запроса (предполагается предшествующий `SQL_CALC_FOUND_ROWS`).
*   `COM_STMT_FETCH_ROWS` — на тот же сервер, что и `COM_STMT_EXECUTE`.

**Transaction Isolation Level Tracking:** если на сервере задано `session_track_transaction_info=CHARACTERISTICS` или `session_track_system_variables=tx_isolation`, readwritesplit отслеживает уровень изоляции и блокирует сессию на Primary при `SERIALIZABLE` (иначе корректность уровня не гарантируется). Начиная с 23.08, при смене уровня на отличный от `SERIALIZABLE` сессия возвращается в обычный режим; в старых версиях блокировка сохранялась до конца сессии.

### Критерии выбора реплики

| Критерий | Метрика | Когда использовать |
| :--- | :--- | :--- |
| `least_current_operations` (default) | Число активных SQL-операций | Баланс throughput; оптимален для однородных серверов |
| `adaptive_routing` | Среднее время ответа + оценка загрузки | Гетерогенные кластеры (разное железо, нагрузка бэкапом); если серверы опрашиваются и другими клиентами, их нагрузка учитывается косвенно |
| `least_behind_master` | Лаг репликации (`Seconds_Behind_Master` из `SHOW REPLICA STATUS`) | Когда важна свежесть данных; только классическая репликация, не Galera. Уступает `causal_reads` (нет гарантии, что запись сессии попала на выбранный сервер). Рекомендуется комбинировать с `causal_reads` |
| `least_global_connections` | Число соединений от MaxScale | Legacy; не рекомендуется — метрика слишком грубая |
| `least_router_connections` | Число соединений от этого сервиса | Legacy; не рекомендуется |

Примечания: `least_global_connections`/`least_router_connections` считают соединения MaxScale к серверу, а не соединения, сообщённые сервером. Строчные значения параметра принимаются с 2.5.29/6.4.11/22.08.9/23.02.5/23.08.1; прописные (`LEAST_CURRENT_OPERATIONS`) deprecated с 23.08.1 — runtime-изменения сохраняются в строчном виде.

### Server Ranks

Общее правило MaxScale — `primary`-серверы используются раньше `secondary`; readwritesplit — исключение:

*   Сессия использует текущий Primary как можно дольше: сессия с «вторичным Primary» не переключается на главный Primary, пока вторичный доступен.
*   Все реплика-соединения сессии используют тот же rank, что и Primary-соединение; соединения с другим rank отбрасываются.
*   Если Primary-соединения нет и `master_reconnection` включён — создаётся соединение к лучшему Primary; соединения с другим rank отбрасываются.
*   Открытые соединения используются для маршрутизации: если Primary потерян, но у сессии есть реплики с тем же rank — они остаются в работе.
*   Если открытых соединений нет — используются серверы с лучшим rank.

### Режимы causal_reads

| Режим | Уровень причинности | Задержка |
| :--- | :--- | :--- |
| `none` (default) | Нет гарантий | — |
| `local` | Сессия: запись видна только в той же сессии | Низкая, одна синхронизация на запись |
| `fast` | Сессия: без синхронизации, чтение идёт на серверы, точно реплицировавшие запись (иначе — на Primary) | Нет синхронизации |
| `global` | Сервис: запись видна всем сессиям сервиса | Средняя, синхронизация на каждое чтение |
| `fast_global` | Сервис: как `fast`, но по глобальному GTID | Нет синхронизации |
| `universal` | Кластер: каждое чтение гарантированно видит последнее состояние; перед каждым чтением — roundtrip к Primary (`@@gtid_current_pos`) | Высокая |
| `fast_universal` | Кластер: как `universal`, но при отставании реплик чтение идёт на Primary | Один roundtrip |

`fast`-режимы подходят для преимущественно читающих нагрузок: при смешанной или write-heavy нагрузке трафик скатится почти целиком на Primary. Режимы на `MASTER_GTID_WAIT` (`local`, `global`, `universal`) **не работают с Galera** (Galera не позволяет ждать конкретный GTID); `fast`-режимы работают с Galera начиная с MaxScale 24.02.5.

Механизм: MaxScale отслеживает GTID каждой транзакции и синхронизирует реплику через `MASTER_GTID_WAIT(gtid, timeout)`. Если реплика не догнала за `causal_reads_timeout` — чтение повторяется на Primary. С MaxScale 24.02 не требуется настраивать `session_track_system_variables` на серверах — MaxScale сам добавляет `last_gtid` при подключении. С 25.10 MaxScale проверяет, отслеживает ли сервер `last_gtid`, и не отправляет `SET`, если он уже настроен (эффективнее установка соединения).

Текстовый протокол — синхронизация встраивается в один multi-query:

```sql
INSERT INTO test.t1 (id) VALUES (1);
-- Выполняется как один multi-query:
SET @maxscale_secret_variable=(
    SELECT CASE
           WHEN MASTER_GTID_WAIT('0-3000-8', 10) = 0 THEN 1
           ELSE (SELECT 1 FROM INFORMATION_SCHEMA.ENGINES)
    END); SELECT * FROM test.t1 WHERE id = 1;
```

Бинарный протокол (prepared statements) — синхронизация отдельным пакетом, отправляемым одновременно с `COM_STMT_EXECUTE`, чтобы не ждать результата синхронизации:

```sql
COM_QUERY:         INSERT INTO test.t1 (id) VALUES (1);
COM_STMT_PREPARE:  SELECT * FROM test.t1 WHERE id = ?
COM_QUERY:         IF (MASTER_GTID_WAIT('0-3000-8', 10) <> 0) THEN KILL (SELECT CONNECTION_ID()); END IF
COM_STMT_EXECUTE:  ? = 123
```

При таймауте синхронизации соединение убивается (`KILL`), и запрос повторяется на Primary — это предотвращает выполнение подготовленного оператора на отстающем сервере. При использовании prepared statements с `causal_reads` рекомендуется держать включённую историю сессионных команд, чтобы можно было открыть новое соединение.

Ограничения `causal_reads`:

*   Если сумма исходного оператора и добавленных MaxScale команд превышает максимальный размер пакета (16777213 байт), causal read не выполняется — читается без гарантий (только текстовый протокол; бинарный использует другой механизм).
*   Операторы вроде `INSERT ... RETURNING`, фиксирующие транзакцию и возвращающие resultset, работают с causal reads только при поддержке коннектором протокола `DEPRECATE_EOF`: Connector/J 3.5.2+, Connector/Node.js 3.4.0+, Connector/R2DBC 1.3.0+; **не** поддерживают Connector/C 3.4.4, Connector/C++ 1.1.5, Connector/ODBC 3.2.5.
*   `causal_reads` включает multi-statement execution в протоколе (аналог `allowMultiQueries=true` в Connector/J или `CLIENT_MULTI_STATEMENTS`/`CLIENT_MULTI_RESULTS` в Connector/C).
*   Мультидоменный GTID безопасен с 2.5.15 (до 2.5.14 включительно возможны non-causal чтения); при reset репликации координаты GTID не сбрасываются автоматически — только перезапуском MaxScale или командой `reset-gtid`.

### Синхронизация транзакций (`sync_transaction`)

Ожидание репликации всех зафиксированных транзакций на одном или нескольких серверах перед возвратом клиенту OK для `COMMIT`:

*   **`soft`** (по умолчанию в режимах с синхронизацией) — синхронизирует, но при таймауте молча продолжает: троттлит скорость транзакций, новые `COMMIT` всё равно проходят. Полезен для ограничения лага репликации.
*   **`hard`** — при таймауте клиентское соединение закрывается: OK для `COMMIT` означает, что транзакция реплицирована и обработана хотя бы одним сервером. Это синхронная форма репликации (альтернатива semi-sync MariaDB), но если ни один сервер не успел реплицировать — новые транзакции не коммитятся, пока сервер не появится и не догонит.
*   При автоматическом failover `mariadbmon` в `soft`-режиме всё ещё полезно включить semi-sync: синхронизация работает скорее как защита от лага. `hard` + auto-failover + cooperative replication `mariadbmon` формирует disaster-tolerant synchronous replication cluster.

Ограничения: не работает с Galera и MySQL; если оператор порождает несколько коммитов (более одного GTID), синхронизируется только первая транзакция.

### Поведение при потере Primary

| `master_failure_mode` | Что происходит |
| :--- | :--- |
| `fail_instantly` | Соединение закрывается сразу при обнаружении потери Primary |
| `fail_on_write` (default с 23.08; в 23.08 default был `fail_instantly`) | Соединение закрывается, только если пришёл запрос на запись при отсутствии Primary; idle-сессии живут |
| `error_on_write` | Запись при отсутствии Primary возвращает ошибку «read-only»; сессия не закрывается |

Дополнительно:

*   В режимах `fail_on_write`/`error_on_write` idle-сессии не закрываются даже при отказе всех бэкенд-соединений — в расчёте, что до следующего запроса клиента появится новая цель. Такие соединения могут зависать, если приложение их не закрывает; для защиты — параметр сервиса `wait_timeout`.
*   При `error_on_write` клиенты по умолчанию не смогут писать после появления нового Primary без переподключения к MaxScale; с `master_reconnection=true` сессия восстановится, если реплика promotion'ена.
*   `master_reconnection`: default `true` (≥24.02) / `false` (≤23.08). Требует, чтобы не использовался `disable_sescmd_history` (с 24.02 его включение автоматически отключает `master_reconnection`). Смена Primary возможна только при включённом `prune_sescmd_history` или непревышенном `max_sescmd_history`, и только при отсутствии открытой транзакции. С `fail_instantly` Primary может смениться только без потери старого; с `fail_on_write` потеря Primary не фатальна — прозрачное переподключение, если замена появилась до прихода записей.
*   Рекомендация: `master_reconnection=true` + `master_failure_mode=fail_on_write` — прозрачное переподключение без риска для консистентности.

### Transaction Replay

При обрыве сервера внутри транзакции MaxScale может перенести транзакцию на замену:

*   Включает `delayed_retry` и `master_reconnection`, принудительно ставит `master_failure_mode=fail_on_write` (переопределяет настроенные значения). Если замена не появляется — соединение закрывается.
*   Контроль целостности — по чексумме (`transaction_replay_checksum`): `full` (default, единственный гарантирующий консистентность), `result_only` (OK-пакеты игнорируются; безопасен, только если auto-generated ID не используется дальше), `no_insert_id` (как `result_only`, но игнорируются и результаты `LAST_INSERT_ID()`).
*   С 23.08 для каждого оператора хранится 128-битная xxHash-чексумма (в старых версиях — один 160-битный SHA1 на транзакцию). При несовпадении результатов replay'а с оригиналом клиентское соединение закрывается.
*   `transaction_replay_safe_commit=true` (default) — транзакция не повторяется, если `COMMIT` уже ушёл на сервер (иначе возможна двойная вставка). Отключать только когда весь SQL безопасен; см. «Ограничения».
*   `transaction_replay_retry_on_deadlock=false` (default) — автоматический retry транзакций, упавших в дедлок (`SQLSTATE 40001`), до успеха или ошибки чексуммы.
*   `transaction_replay_retry_on_mismatch=false` (default) — retry транзакций с несовпадением чексуммы до достижения лимитов (`delayed_retry_timeout`, `transaction_replay_timeout` или `transaction_replay_attempts`).
*   Ограничение по размеру: `transaction_replay_max_size` (default 1 MiB) — пиковая память = размер × число клиентских соединений; превышение логируется на уровне info и считается в `trx_max_size_exceeded`.
*   `transaction_replay_timeout` (default 30s с 24.02; 0s до 23.08) — единственный контроллер длительности replay; если `delayed_retry_timeout` меньше, он поднимается до этого значения. Без `transaction_replay_timeout` максимум = `delayed_retry_timeout` × `transaction_replay_attempts` (по default 50с), минимум — `transaction_replay_attempts` секунд (5с), например при достижении `max_connections` на сервере.
*   `transaction_replay_attempts` (default 5) — сколько отказов сервера/сети терпит один replay; при успехе счётчик сбрасывается.

### Routing hints

Readwritesplit поддерживает routing hints (синтаксис — в документации HintFilter). `/* route to master */` заставляет читать как запись — полезно для чтения вне транзакции, зависящего от ранее зафиксированной транзакции, которая ещё не реплицирована; автоматические альтернативы — `causal_reads` и `sync_transaction`. Все hints внутри транзакции игнорируются (для консистентности транзакции). `/* route to slave */` всегда игнорируется (избыточен или направил бы запись не туда). `/* route to last */` и `/* route to server <name> */` работают только для чтения; для записи, если цель непригодна, это retryable error при включённом retry.

### Interaction с серверами в `Maintenance` и `Draining`

При переводе сервера в maintenance выполняющиеся запросы завершаются перед закрытием соединения; если это Primary — завершаются и открытые транзакции. Idle-сессии и длинные транзакции readwritesplit **не** закрывает самостоятельно; принудительно: `maxctrl set server <server> maintenance --force`. Сервер в `Draining` обслуживает существующие соединения, но новые соединения создаются только к серверам, не находящимся в `Draining`/`Drained`.

## Практические сценарии

### Prerequisites

*   Настроенный монитор (`mariadbmon` или `galeramon`), определяющий роли Master/Slave.
*   Для `causal_reads` на классической репликации — GTID.
*   Для `sync_transaction` — классическая репликация (не Galera/MySQL) и монитор, измеряющий лаг.
*   Для `transaction_replay` — сессии без состояния, не воспроизводимого при replay (см. ограничения).
*   Сервис должен иметь хотя бы один listener; для аутентификации — служебный пользователь.

### Шаг 1: Полная конфигурация readwritesplit

```ini
# /etc/maxscale.cnf

[RW-Split-Service]
type=service
router=readwritesplit
servers=db-node-1,db-node-2,db-node-3
user=maxscale_user
password=СЛОЖНЫЙ_ПАРОЛЬ

# Выбор реплики
slave_selection_criteria=least_current_operations
max_slave_connections=255
slave_connections=1

# Лаг репликации (секунды; 0 = отключено)
max_replication_lag=30

# Поведение при потере Primary
master_failure_mode=fail_on_write
master_reconnection=true
master_accept_reads=false

# Повтор запросов
delayed_retry=true
delayed_retry_timeout=10s
retry_failed_reads=true

# Транзакции
transaction_replay=true
transaction_replay_timeout=30s
transaction_replay_max_size=1MiB
transaction_replay_attempts=5
transaction_replay_checksum=full
transaction_replay_safe_commit=true

# Причинно-следственное чтение
causal_reads=local
causal_reads_timeout=10s

# Синхронизация транзакций (аналог semi-sync на уровне MaxScale)
# sync_transaction=soft
# sync_transaction_count=1
# sync_transaction_timeout=10s
# sync_transaction_max_lag=0s

# Строгие режимы (включать только при реальной необходимости)
strict_multi_stmt=false
strict_sp_calls=false
strict_tmp_tables=true

# Пользовательские переменные
use_sql_variables_in=all

# Ленивое создание соединений
lazy_connect=false
```

**Справочник параметров** (все параметры роутера — Dynamic: Yes, изменяются через `maxctrl alter service`, применяются только к новым сессиям):

| Параметр | Тип | Default |
| :--- | :--- | :--- |
| `max_slave_connections` | integer, 0–255 | 255 |
| `slave_connections` | integer | 255 |
| `max_replication_lag` | duration | 0s |
| `use_sql_variables_in` | enum: `master`, `all` | `all` |
| `master_reconnection` | boolean | `true` (≥24.02), `false` (≤23.08) |
| `slave_selection_criteria` | enum (см. таблицу критериев) | `least_current_operations` |
| `master_accept_reads` | boolean | `false` |
| `strict_multi_stmt` | boolean | `false` |
| `strict_sp_calls` | boolean | `false` |
| `strict_tmp_tables` | boolean | `true` (≥24.02), `false` (≤23.08) |
| `master_failure_mode` | enum: `fail_instantly`, `fail_on_write`, `error_on_write` | `fail_on_write` (23.08: `fail_instantly`) |
| `retry_failed_reads` | boolean | `true` |
| `delayed_retry` | boolean | `false` |
| `delayed_retry_timeout` | duration | 10s |
| `transaction_replay` | boolean | `false` |
| `transaction_replay_max_size` | size | 1 MiB |
| `transaction_replay_attempts` | integer | 5 |
| `transaction_replay_timeout` | duration | 30s (≥24.02), 0s (≤23.08) |
| `transaction_replay_retry_on_deadlock` | boolean | `false` |
| `transaction_replay_safe_commit` | boolean | `true` |
| `transaction_replay_retry_on_mismatch` | boolean | `false` |
| `transaction_replay_checksum` | enum: `full`, `result_only`, `no_insert_id` | `full` |
| `causal_reads` | enum (см. таблицу режимов) | `none` |
| `causal_reads_timeout` | duration | 10s |
| `lazy_connect` | boolean | `false` |
| `sync_transaction` | enum: `none`, `soft`, `hard` | `none` |
| `sync_transaction_count` | integer, 1–255 | 1 |
| `sync_transaction_timeout` | duration | 10s |
| `sync_transaction_max_lag` | duration | 0s |

Удалённые параметры: `optimistic_trx` → фильтр OptimisticTrx (25.01), `reuse_prepared_statements` → фильтр PsReuse (25.01). Deprecated: `max_slave_replication_lag` → `max_replication_lag` (до 23.02, алиас ещё работает).

**Пояснения:**

*   `slave_connections=1` — мягкий лимит (число соединений может превысить его, если алгоритм найдёт неподключённую реплику лучше всех остальных); рекомендуется для короткоживущих соединений (быстрее создание, меньше ресурсов).
*   `max_slave_connections=0` — все чтения на Primary (удобно для отладки или принудительной централизации трафика; при этом replay/reconnection-фичи продолжают работать). Нюанс: с `master_failure_mode=fail_on_write`, если Primary упал и пришёл `SELECT` при отсутствии другого Primary, соединение закрывается — чтобы не создавать лишнее slave-соединение, которое не закроется при появлении нового Primary.
*   `master_accept_reads=false` (default) — чтения не идут на Primary, пока есть валидная реплика. Если реплик нет — чтения идут на Primary в любом случае.
*   `lazy_connect=true` — соединения с бэкендами создаются только при необходимости: снижает нагрузку при короткоживущих сессиях, но добавляет задержку на первый запрос. С 23.08.2 первая сессионная команда выполняется на реплике (на Primary — если `master_accept_reads=true`); для workload с преимущественно чтениями и редкими записями при `lazy_connect=true` лучше отключить `master_accept_reads`.
*   `use_sql_variables_in=all` (default) — `SET @var`, модификация `@var` внутри `SELECT` и чтение `@var` идут на все серверы (до 22.08 модификация в `SELECT` при `all` давала ошибку; теперь запрос идёт на все серверы, лишние результаты отбрасываются). `master` — всё, что касается пользовательских переменных, на Primary: меньше отбрасываемых данных, но состояние `@var` становится недетерминированным при модификации в `SELECT`. DML, модифицирующий `@var` (`INSERT ... VALUES (@myid := @myid + 1)`), всегда идёт на Primary — значение `@myid` на серверах расходится, и последующий `SELECT @myid` может вернуть разное.
*   `max_replication_lag`: реплика допускается только если её лаг **строго меньше** значения (`max_replication_lag=1s` — все реплики должны быть полностью актуальны). Гарантии read-your-writes не даёт — для этого `causal_reads`. Гранулярность — секунды (значение в миллисекундах отклоняется, даже если больше секунды). Лаг измеряет не роутер, а монитор (`mariadbmon`); для Galera неприменим (у Galera нет понятия лага репликации). Дисквалификация по лагу и восстановление логируются warning'ами — только когда маршрутизируется запрос и состояние меняется. С 23.08.7/24.02.3/25.01.1 соединения к серверам с лагом `> MAX(300, 2 * max_replication_lag)` отбрасываются.
*   `retry_failed_reads=true` (default) — autocommit-`SELECT` вне транзакции повторяется на заменяющем сервере при отказе реплики: отказ прозрачен для клиента. Если часть результата уже доставлена клиенту, запрос не повторяется (повтор возможен только с `transaction_replay`).

### Шаг 2: causal_reads — выбор режима

```ini
# Типичный OLTP: сессия пишет, затем читает свои же записи
causal_reads=local
causal_reads_timeout=10s

# Аналитика/отчёты: любая сессия должна видеть записи любой другой
causal_reads=global

# Максимальная строгость (дороже всего): каждое чтение сверяется с Primary
causal_reads=universal
```

Проверка в рантайме:

```bash
maxctrl alter service RW-Split-Service causal_reads=local
# Изменение применяется только к новым сессиям

# Сброс глобального GTID-состояния (causal_reads=global) — когда кластер
# откатили в прошлое и записанные GTID стали недействительны:
maxctrl call command readwritesplit reset-gtid RW-Split-Service
```

### Шаг 3: sync_transaction — синхронная фиксация

```ini
# soft: троттлить транзакции, COMMIT не блокируется надолго
sync_transaction=soft
sync_transaction_timeout=10s
sync_transaction_max_lag=0s     # 0 = всегда синхронизировать; иначе — зондирование

# hard: OK для COMMIT = транзакция реплицирована хотя бы на 1 сервер
sync_transaction=hard
sync_transaction_count=1        # минимум серверов для синхронизации
sync_transaction_timeout=10s    # таймаут можно задавать в миллисекундах
```

*   `sync_transaction_count` — минимальное число бэкендов для синхронизации; запрос уходит всем бэкендам с открытыми соединениями. Если `max_slave_connections` меньше `sync_transaction_count`, он автоматически поднимается до него.
*   `sync_transaction_max_lag` (только `soft`) — при ненулевом значении одна транзакция зондирует лаг синхронизации, остальные выполняются параллельно без синхронизации; когда измеренный лаг превышает лимит, все транзакции начинают синхронизироваться. Если `max_lag` > `timeout`, для решения используется лаг репликации из монитора. Слишком большие значения обоих параметров вызывают осцилляции времени коммита — держите `max_lag` относительно низким.
*   В `hard`-режиме `sync_transaction_max_lag` игнорируется.

### Шаг 4: OptimisticTrx — оптимизация read-only транзакций

Фильтр `optimistictrx` (заменил параметр `optimistic_trx`, удалённый из readwritesplit в 25.01) выполняет транзакции оптимистично на реплике: `BEGIN` заменяется на `START TRANSACTION READ ONLY`; при записи — `ROLLBACK` и replay на Primary.

```ini
[OptimisticTrx]
type=filter
module=optimistictrx

[RW-Split-Service]
type=service
router=readwritesplit
...
filters=OptimisticTrx
```

Создание в рантайме:

```bash
maxctrl create filter OptimisticTrx optimistictrx
maxctrl alter service-filter RW-Split-Service OptimisticTrx
```

### Шаг 5: Диагностика маршрутизации

```bash
# Статистика сервиса (router_diagnostics readwritesplit):
# queries            — всего запросов через сервис
# route_master       — записей на Primary
# route_slave        — чтений на реплики
# route_all          — сессионных команд на все серверы
# rw_transactions    — явных read-write транзакций
# ro_transactions    — явных read-only транзакций
# replayed_transactions — реплеированных транзакций
# trx_max_size_exceeded — превышений transaction_replay_max_size
# server_query_statistics — по каждому серверу: total, read, write,
#   avg_sess_duration, avg_sess_active_pct (0% = соединения открыты, но не использовались),
#   avg_selects_per_session
maxctrl show service RW-Split-Service

# Состояние серверов и GTID; дисквалификация по лагу логируется warning'ом
maxctrl list servers
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Чтение не видит только что записанное | `causal_reads=none` и чтение попало на отстающую реплику | Включите `causal_reads=local` (или `global` для межсессионной видимости) |
| `Error: 1792 / SQLSTATE 25006: Causal read timed out while in a read-only transaction` | Реплика не догнала за `causal_reads_timeout` в read-only транзакции | Увеличьте `causal_reads_timeout`; проверьте лаг репликации |
| Соединение закрывается при падении Primary | `master_failure_mode=fail_instantly` | Используйте `fail_on_write` + `master_reconnection=true` |
| `master_reconnection` не работает | Включён `disable_sescmd_history`, превышен `max_sescmd_history` при выключенном `prune_sescmd_history`, или открыта транзакция | Отключите `disable_sescmd_history`; увеличьте `max_sescmd_history` или включите `prune_sescmd_history` |
| Транзакции не replay'ятся | `transaction_replay_safe_commit=true` и `COMMIT` уже ушёл на сервер | Это защита от дублирования; не отключайте без анализа SQL |
| `trx_max_size_exceeded` растёт | Транзакции больше `transaction_replay_max_size` | Увеличьте лимит (помните: пиковая память = лимит × число соединений) |
| Чтения идут на Primary, хотя реплики есть | `master_accept_reads=true` или все реплики отстали больше `max_replication_lag` | Проверьте `maxctrl list servers` и лог: дисквалификация по лагу логируется |
| Prepared statements ломаются при переключении | История сессионных команд отключена | Не используйте `disable_sescmd_history` вместе с `master_reconnection` и `causal_reads` |
| `causal_reads` не работает с Galera | Режимы на `MASTER_GTID_WAIT` не поддерживаются Galera | Используйте `fast`/`fast_global`/`fast_universal` (MaxScale 24.02.5+) |
| Causal read молча не выполняется | Оператор + добавленные MaxScale команды превышают 16777213 байт | Разбейте запрос; для такого размера гарантия не предоставляется |
| `INSERT ... RETURNING` теряет причинность | Коннектор не поддерживает `DEPRECATE_EOF` | Connector/J 3.5.2+, Node.js 3.4.0+, R2DBC 1.3.0+; Connector/C, C++, ODBC — не поддерживают |
| Сессия заблокирована на Primary | Уровень изоляции `SERIALIZABLE` + `session_track_transaction_info`/`tx_isolation` | Корректное поведение; с 23.08 блокировка снимается при смене уровня |
| После `CREATE DATABASE` + `USE db` сессия теряет соединение | `USE` исполнился раньше, чем создание БД реплицировалось; результат сессионной команды различается на серверах | Соединение с проблемным сервером отбрасывается навсегда до конца сессии — корректная защита; повторите `USE` позже |
| Транзакция с `SQL_MODE`, изменённым внутри транзакции, не replay'ится | Состояние сессии, изменённое в транзакции, сохраняется при reconnect и ломает replay | Меняйте сессионные переменные до `BEGIN` или вне транзакции |

## Ограничения

*   **Максимум 256 целей** (с 25.10): при большем числе серверов в сервисе используются только первые 256.
*   **Чтения на Primary** дополнительно случаются: внутри открытой read-write транзакции; при вызове хранимой процедуры или UDF; в multi-statement запросе (например, `INSERT ... ; SELECT LAST_INSERT_ID();`).
*   **Prepared statement на временной таблице Primary**: реплики не смогут его выполнить — все реплика-соединения закрываются (MXS-1816).
*   **Transaction Replay:** транзакции с серверно-зависимыми результатами (`NOW()`, `@@server_id`) не могут быть успешно реплеированы (попытка всё равно делается); транзакцию, читающую данные перед изменением, защищайте `SELECT ... FOR UPDATE` (иначе перекрывающиеся replay одного набора строк); потеря соединения во время `COMMIT` может привести к двойному выполнению при `transaction_replay_safe_commit=false` — типичные небезопасные паттерны: `INSERT` в таблицу без auto-increment PK, «слепое» обновление `UPDATE t SET c = c + 1`, «слепое» удаление `DELETE ... LIMIT`; операторы с неявным коммитом не сбрасывают транзакцию (кроме `BEGIN`/`START TRANSACTION`, которые распознаются) — replay зафиксируется дважды; потеря соединения во время `ROLLBACK` всё равно вызывает попытку replay (может быть отчёт о конфликте). С 23.08 (MXS-4549) оператор с частично доставленным результатом внутри транзакции replay'ится (в старых версиях сессия закрывалась немедленно).
*   **Service-to-service routing:** если в конфигурации сервис использует другой сервис (`targets`), транзакция верхнего сервиса заставляет нижележащие readwritesplit вести себя так, будто транзакция открыта; отказ бэкенда может вызвать лишние replay и конфликты чексумм — не используйте внутри транзакции команды, маршрутизируемые на несколько узлов.
*   **Multi-statement:** всегда маршрутизируется на Primary; если multi-statement создаёт временную таблицу, это не детектируется, и чтения к ней могут уйти на реплики — создавайте временную таблицу отдельным оператором.

## Best Practices

1.  **`slave_selection_criteria=least_current_operations`** — default и оптимальный выбор для однородных кластеров; `adaptive_routing` — для гетерогенных.
2.  **`causal_reads=local`** — минимальная цена за корректность «read-your-writes» в сессии; включайте по умолчанию в OLTP.
3.  **`master_reconnection=true` + `master_failure_mode=fail_on_write`** — рекомендуемая пара для отказоустойчивости.
4.  **`transaction_replay`** включайте, когда приложение не идемпотентно и не обрабатывает разрывы соединений само; помните про лимит размера и `safe_commit`.
5.  **`strict_tmp_tables=true`** (default с 24.02) — защищает временные таблицы от исчезновения при reconnect; но сессии, не закрывающие временные таблицы, фактически отключают reconnect.
6.  **`delayed_retry`** — безопасен на MaxScale 25.01.1+: запрос, уже отправленный на сервер, не повторяется (защита от двойного выполнения).
7.  **Не включайте `strict_multi_stmt`/`strict_sp_calls`** без доказанной необходимости — они отправляют все последующие запросы на Primary.
8.  **`least_global_connections`/`least_router_connections`** — legacy, не используйте: грубая метрика (число соединений вместо числа операций).
9.  **`sync_transaction=soft`** — лёгкая альтернатива semi-sync для ограничения лага; `hard` — только когда выживание транзакций важнее доступности коммитов.
10. **`maxctrl set server <name> maintenance --force`** — когда нужно закрыть даже idle-сессии и длинные транзакции при выводе сервера в maintenance.

## Дополнительная информация

### См. также

*   **[Обзор MaxScale](./maxscale_overview.md)** — базовая конфигурация RW-split для Galera.
*   **[Failover и Switchover](./maxscale_failover.md)** — как меняется Primary и что это значит для сессий.
*   **[Connection Pooling](./maxscale_connection_pooling.md)** — пулинг соединений к бэкендам.
*   **[Readconnroute и schemarouter](./maxscale_routers.md)** — сравнение роутеров; `rank`/`preferred_labels` в readconnroute.
*   **[Отказоустойчивость MariaDB](../high_availability.md)** — Galera и классическая репликация.
*   [Официальная страница Readwritesplit](https://mariadb.com/docs/maxscale/reference/maxscale-routers/maxscale-readwritesplit.md) — полный справочник параметров.
*   [HintFilter](https://mariadb.com/docs/maxscale/reference/maxscale-filters/maxscale-hintfilter.md) — синтаксис routing hints.
*   [OptimisticTrx](https://mariadb.com/docs/maxscale/reference/maxscale-filters/maxscale-optimistic-transaction-execution-filter.md) и [PsReuse](https://mariadb.com/docs/maxscale/reference/maxscale-filters/maxscale-psreuse-filter.md) — фильтры, заменившие параметры `optimistic_trx` и `reuse_prepared_statements` (25.01).
