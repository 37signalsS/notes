# Эксплуатация и мониторинг PgBouncer

**Актуально для:** PgBouncer 1.21–1.26 (последний релиз — 1.26.0, 2026-09-23), PostgreSQL 13–18

> Второй файл пары: **[Настройка PgBouncer](./pgbouncer_setup.md)** — установка, конфигурация, аутентификация, безопасность, capacity planning. Здесь — админ-консоль, мониторинг, failover, rolling restart, бенчмарк и совместимость с приложениями.

## Определения

- **Админ-консоль** — виртуальная база данных `pgbouncer` с командами `SHOW`/`PAUSE`/`RELOAD` и др.; поддерживает только Simple Query Protocol.
- **`cl_active` / `cl_waiting`** — клиентские соединения, связанные с серверными (или простаивающие без запросов), и клиенты, чьи запросы ждут свободного серверного соединения.
- **`sv_active` / `sv_idle` / `sv_used` / `sv_tested` / `sv_login`** — серверные соединения: занятые, свободные, простаивавшие дольше `server_check_delay`, выполняющие reset/check, в процессе логина.
- **`maxwait`** — время ожидания старейшего клиента в очереди, секунды; растёт при перегруженном пуле или медленном бэкенде.
- **Reserve pool** — `reserve_pool_size` дополнительных соединений, подключаемых при исчерпании основного пула, если клиент ждёт дольше `reserve_pool_timeout` (5 с по умолчанию); sizing — в **[Настройке](./pgbouncer_setup.md)**.
- **SPOF (Single Point of Failure)** — PgBouncer единственным экземпляром сам является точкой отказа.
- **Rolling restart** — поочерёдная перезагрузка экземпляров на одном порту (`so_reuseport`) без обрыва клиентских сессий.
- **Peering** — группа экземпляров PgBouncer (`peer_id` + секция `[peers]`), пересылающая друг другу запросы отмены запросов.
- **Host list** — список хостов в `host=a,b,c` строки подключения (1.17+); новые соединения выбираются round-robin (`load_balance_hosts`).

## Предпосылки

1. Работающий PgBouncer, настроенный по **[Настройка PgBouncer](./pgbouncer_setup.md)**.
2. Пользователь из `admin_users` (полный доступ) или `stats_users` (только `SHOW`) для консоли. Через Unix-сокет пользователь `pgbouncer` с тем же UID, что и процесс, входит без пароля.
3. Для Prometheus-метрик — `pgbouncer_exporter` (prometheus-community, порт `9127`, путь `/metrics`; требуется `ignore_startup_parameters = extra_float_digits` в `pgbouncer.ini`).
4. Для корреляции — доступ к `pg_stat_activity` на PostgreSQL.
5. **Безопасность версий:** обновитесь до **≥1.26.0** — до 1.26.0 неаутентифицированный клиент мог упасть (CVE-2026-19888) или навсегда повесить пулер (CVE-2026-6668, integer overflow в росте packet buffer); `KILL_CLIENT` доступен любому консольному пользователю до **1.25.2** (CVE-2026-6667); условия CVE-2025-12819 (выполнение SQL при аутентификации через `search_path` в startup-пакете) — `track_extra_parameters` с `search_path` + `auth_user` + не квалифицированный `auth_query`, исправлено в 1.25.1.

## Основные концепции

### Модель метрик

- **`SHOW STATS`** — суммарные счётчики с момента старта процесса и средние за последний `stats_period` (60 с по умолчанию): `total_xact_count`, `total_query_count`, `total_received`/`total_sent`, `total_xact_time`, `total_query_time`, `total_wait_time` (время ожидания клиентами сервера), `avg_*` (в т.ч. `avg_xact_time`, `avg_query_time`, `avg_wait_time` — расчёт `avg_wait_time` исправлен только в 1.23.0), `total_server_assignment_count`/`avg_server_assignment_count` (сколько раз сервер выдавался клиенту), `total_client_login_count` (с 1.26 — детект churn'а соединений). Счётчики prepared statements (с 1.24): `total_client_parse_count`, `total_server_parse_count`, `total_bind_count` и `avg_*` аналоги. Подмножества: `SHOW STATS_TOTALS`, `SHOW STATS_AVERAGES`, `SHOW TOTALS` (агрегат по всем базам).
- **`SHOW POOLS`** — мгновенные состояния пулов; новая строка на каждую пару (база, пользователь). Колонки: `cl_active`, `cl_waiting`, `cl_active_cancel_req`, `cl_waiting_cancel_req` (клиенты с отменами), `sv_active`, `sv_active_cancel`, `sv_being_canceled`, `sv_idle`, `sv_used`, `sv_tested`, `sv_login`, `maxwait`, `maxwait_us`, `pool_mode`, `load_balance_hosts`.
- **`SHOW CLIENTS` / `SHOW SERVERS`** — детальные списки соединений с адресами, временами, `application_name`, числом prepared statements, `replication` (`none`/`logical`/`physical` — с 1.23), уникальным `id`.
- **`SHOW DATABASES`** — маршруты, размеры пулов (`pool_size`, `min_pool_size`, `reserve_pool_size`), лимиты (`max_connections`/`current_connections` серверных, `max_client_connections`/`current_client_connections` клиентских — с 1.24), `server_lifetime`, `load_balance_hosts`, флаги `paused`/`disabled`.
- **`SHOW USERS`** — переопределения (`pool_size`, `reserve_pool_size`, `pool_mode`, `max_user_connections`, `max_user_client_connections`) и текущие соединения (`current_connections` серверные, `current_client_connections` клиентские — с 1.24).
- **`SHOW LISTS`** — внутренние счётчики: числа баз, пользователей, пулов, свободных/используемых клиентов и серверов, DNS-кэша (включая `dns_queries` — in-flight DNS-запросы).
- **`SHOW CONFIG`** — текущие значения, дефолты и флаг `changeable` (можно ли менять через `SET` в рантайме).
- Также: `SHOW VERSION`, `SHOW STATE` (`active`/`paused`), `SHOW MEM`, `SHOW DNS_HOSTS`, `SHOW DNS_ZONES`, `SHOW PEERS`, `SHOW PEER_POOLS`, `SHOW SOCKETS`, `SHOW ACTIVE_SOCKETS`, `SHOW HELP`.

### Корреляция с PostgreSQL

Сопоставляйте метрики PgBouncer с `pg_stat_activity`:

```sql
SELECT state, count(*)
FROM pg_stat_activity
WHERE datname = 'myapp_db'
GROUP BY state;
```

Если `cl_active` в PgBouncer высокий, а `active` в `pg_stat_activity` низкий — проблема в длительных транзакциях или сетевой задержке между пулером и бэкендом; если растёт `total_wait_time` — пул мал относительно нагрузки.

### SPOF и отказоустойчивость самого PgBouncer

PgBouncer единственным экземпляром — SPOF. Варианты устранения:

1. **HAProxy перед несколькими экземплярами PgBouncer** — при падении одного балансировщик переключает трафик; рекомендуется с `peer_id`/`[peers]`, чтобы запросы отмены (cancel) доходили до нужного процесса.
2. **Несколько процессов на одном порту через `so_reuseport = 1`** — ядро распределяет соединения (Linux, DragonFlyBSD, FreeBSD; на FreeBSD применяется `SO_REUSEPORT_LB`); минус — нельзя адресовать конкретный экземпляр по TCP, что мешает мониторингу; каждому экземпляру нужны свои `unix_socket_dir` и `pidfile` (и `logfile`, если используется).
3. **DNS Round-Robin** — не рекомендуется из-за кэширования DNS (`dns_max_ttl` 15 с) и задержки переключения.
4. **Kubernetes**: sidecar-контейнер (приложение подключается к `localhost:6432`, меньше межсервисного трафика) или отдельный Deployment + Service для агрегации соединений от множества сервисов.

**Поведение при падении PgBouncer:** клиенты получают `Connection refused`/сброс соединения, все серверные соединения закрываются ОС (активные транзакции откатываются); восстановление — `systemctl restart pgbouncer` + retry-логика приложения. Утечка памяти → OOM killer: ограничьте `MemoryMax` в unit'е. Бурст подключений упирается в `listen_backlog` (128 по умолчанию) — новые соединения дропаются при полном очереди.

## Практические сценарии

### Мониторинг через админ-консоль

```bash
psql -h /var/run/postgresql -U pgb_admin pgbouncer
```

```sql
SHOW POOLS;
--  database | user | cl_active | cl_waiting | sv_active | sv_idle | sv_used | sv_tested | sv_login | maxwait | maxwait_us | pool_mode
--  myapp_db | app  |       120 |          0 |        50 |       0 |       0 |         0 |        0 |    0.00 |          0 | transaction
SHOW STATS;
SHOW DATABASES;
SHOW CLIENTS;
SHOW SERVERS;
```

- `cl_waiting` — клиенты в очереди; должно быть `0` в steady state.
- `sv_active` — занятые серверные соединения; достижение `default_pool_size` означает исчерпание пула.
- `maxwait` — время ожидания старейшего клиента; алерт при > 2 с.
- Клиенты, простоявшие в очереди > 5 с (`query_wait_notify`, дефолт 5), получают NOTICE — видны в логах пулера и у приложения.
- `SHOW SERVERS` → `state` (`active`, `idle`, `used`, `tested`, `new`, `active_cancel`, `being_canceled`), `addr`, `application_name`, `prepared_statements`, `close_needed` (1 = соединение будет закрыто при освобождении после `RELOAD`/`RECONNECT`/смены DNS).

### Мониторинг через Prometheus (pgbouncer_exporter)

```bash
pgbouncer_exporter --pgbouncer.upstream.url=http://127.0.0.1:6432
# → metrics на http://localhost:9127/metrics
```

Требуется в `pgbouncer.ini`: `ignore_startup_parameters = extra_float_digits`. Метрики (проверенные имена prometheus-community/pgbouncer_exporter):

| PgBouncer (SHOW) | Prometheus-метрика | Смысл |
| :--- | :--- | :--- |
| `pools.cl_active` | `pgbouncer_pools_client_active_connections` | клиенты, связанные с сервером или простаивающие |
| `pools.cl_waiting` | `pgbouncer_pools_client_waiting_connections` | клиенты, ждущие серверное соединение |
| `pools.sv_active` | `pgbouncer_pools_server_active_connections` | занятые серверные соединения |
| `pools.sv_idle` | `pgbouncer_pools_server_idle_connections` | свободные, готовые к выдаче |
| `pools.sv_used` | `pgbouncer_pools_server_used_connections` | простаивали > `server_check_delay` |
| `pools.sv_tested` | `pgbouncer_pools_server_testing_connections` | выполняют reset/check |
| `pools.sv_login` | `pgbouncer_pools_server_login_connections` | в процессе логина |
| `pools.maxwait` | `pgbouncer_pools_client_maxwait_seconds` | возраст старейшего клиента в очереди |
| `stats.total_query_count` | `pgbouncer_stats_queries_pooled_total` | всего запросов |
| `stats.total_query_time` | `pgbouncer_stats_queries_duration_seconds_total` | суммарное время выполнения запросов |
| `stats.total_xact_count` | `pgbouncer_stats_sql_transactions_pooled_total` | транзакции |
| `stats.total_xact_time` | `pgbouncer_stats_server_in_transaction_seconds_total` | время в транзакции (в т.ч. idle in transaction) |
| `stats.total_wait_time` | `pgbouncer_stats_client_wait_seconds_total` | время ожидания клиентами сервера |
| `stats.total_received` / `total_sent` | `pgbouncer_stats_received_bytes_total` / `pgbouncer_stats_sent_bytes_total` | трафик |
| `config.max_client_conn` | `pgbouncer_config_max_client_connections` | настроенный лимит клиентских сессий |
| `config.max_user_connections` | `pgbouncer_config_max_user_connections` | лимит серверных соединений на пользователя |
| — | `up{job="pgbouncer"}` | доступность цели экспортера |

**Пороги алертов:**

| Условие | Тяжесть | Описание |
| :--- | :--- | :--- |
| `sum(pgbouncer_pools_client_waiting_connections) > 0` | Critical | Клиенты ждут свободного соединения |
| `pgbouncer_pools_client_maxwait_seconds > 2` | Warning | Старейший клиент в очереди ждёт > 2 с |
| `rate(pgbouncer_stats_client_wait_seconds_total[5m]) / rate(pgbouncer_stats_queries_pooled_total[5m]) > 0.5` | Warning | Среднее ожидание сервера > 500 мс на запрос |
| `up{job="pgbouncer"} == 0` | Critical | PgBouncer/экспортер недоступен |

Утилизация пула (`sv_active` / `pool_size`) в Prometheus напрямую не выражается — `pool_size` экспортер не отдаёт; контролируйте её периодическим `SHOW DATABASES` (поля `pool_size`, `current_connections`) или recording rule'ом с константой. На дашборде «PgBouncer Overview»: глобальная очередь `sum(pgbouncer_pools_client_waiting_connections)`, `pgbouncer_pools_server_active_connections`, `pgbouncer_pools_server_idle_connections`.

**Кавказы мониторинга:**

- `pool_idle_timeout` (1.26+, дефолт выключен) освобождает неиспользуемые пулы — статистика освобождённого пула теряется, и суммарные счётчики `SHOW STATS` **уменьшаются**, что мониторинг может принять за сброс счётчика.
- `avg_wait_time` на версиях < 1.23.0 рассчитывался неверно.
- `log_stats = 0` отключает агрегированную статистику в лог (раз в `stats_period`) — делайте это при внешнем мониторинге, чтобы не дублировать.

### Переключение бэкенда (Failover) без обрыва клиентов

При смене Primary (Patroni или вручную) не разрывайте клиентов: активные транзакции завершатся, серверные соединения закроются при освобождении, новые клиенты встанут в очередь:

```bash
# 1. Пауза базы: команда вернётся только после отключения от всех серверов
psql -h 127.0.0.1 -p 6432 -U pgb_admin pgbouncer -c "PAUSE myapp_db"
# 2. Обновить [databases] -> host=новый_primary в /etc/pgbouncer/pgbouncer.ini
# 3. RELOAD: старые серверные соединения закроются при освобождении,
#    новые сразу пойдут на новый адрес (RECONNECT не нужен после RELOAD)
psql -h 127.0.0.1 -p 6432 -U pgb_admin pgbouncer -c "RELOAD"
# 4. Возобновить
psql -h 127.0.0.1 -p 6432 -U pgb_admin pgbouncer -c "RESUME myapp_db"
```

**Валидация:** `SHOW DATABASES` → `paused=0`; `SHOW SERVERS` → `addr` нового бэкенда; в логах нет ошибок подключения.

- `RECONNECT [db]` нужен, когда маршрутизация происходит **ниже** PgBouncer (например, внешний балансировщик): он закрывает серверные соединения при освобождении, новые идут по новому маршруту. Для постепенного переключения части трафика (read-only на replica) — `RECONNECT`; для мгновенного переключения всего — `PAUSE`.
- `WAIT_CLOSE [db]` — дождаться, пока все соединения покинут состояние `close_needed` (поле в `SHOW SERVERS`); использовать в скриптах switchover после `RECONNECT`/`RELOAD`.
- При плановом рестарте PostgreSQL используйте `PAUSE`/`RESUME`, а не просто kill postgres: иначе `server_login_retry` (15 с) будет выдавать клиентам ошибки в паузе между попытками.
- **Host list** (`host=10.0.0.1,10.0.0.2`, 1.17+): новые соединения выбираются round-robin (`load_balance_hosts = round-robin`, дефолт) или держатся на одном хосте до сбоя (`load_balance_hosts = disable`); **все хосты списка должны быть доступны всегда — механизма пропуска недоступного хоста нет** (это не failover-лист, в отличие от `host` в libpq). Для быстрых повторов при нескольких хостах ставьте `server_login_retry` ниже дефолта. Для равномерной нагрузки на уже установленных соединениях (multi-IP DNS или host list) — `server_round_robin = 1` (по умолчанию PgBouncer переиспользует соединения LIFO).

### Graceful shutdown и rolling restart

**Сигналы:**

| Сигнал | Эквивалент на консоли | Эффект |
| :--- | :--- | :--- |
| `SIGHUP` | `RELOAD` | Перечитать конфиг (и reopen `logfile` — ротация логов) |
| `SIGTERM` | `SHUTDOWN WAIT_FOR_CLIENTS` | Super safe shutdown: не принимать новые, дождаться отключения клиентов (в версиях < 1.23 — мгновенное завершение) |
| `SIGINT` | `SHUTDOWN WAIT_FOR_SERVERS` | Safe shutdown: отключиться от серверов по правилам режима пула |
| `SIGQUIT` | `SHUTDOWN` | Мгновенное завершение |
| `SIGUSR1` / `SIGUSR2` | `PAUSE` / `RESUME` | Пауза/возобновление |

**Rolling restart без обрыва клиентов** (zero-downtime, процедура из документации):

1. Запустите два и более экземпляра PgBouncer на одном порту через `so_reuseport = 1` (peering рекомендуется для корректной отмены запросов).
2. Выберите процесс A и отправьте ему `SIGTERM` (`SHUTDOWN WAIT_FOR_CLIENTS`).
3. Дождитесь, пока клиенты переподключатся к другим процессам (клиентский pooler переподключится сам по `server_idle_timeout`/аналогу, иначе — рестарт клиентов).
4. Процесс A завершится сам, когда клиентов не останется; запустите его снова.
5. Повторите для каждого оставшегося процесса.

**Обновление бинарника** на инфраструктуре без `so_reuseport` — blue-green: второй экземпляр на порту `6433` с новым бинарником → переключить конфиг/балансировщик приложения на `6433` → остановить старый на `6432`. `systemctl reload pgbouncer` обновляет **только конфиг**, не бинарник.

**Аварийные команды консоли:**

- `DISABLE db` / `ENABLE db` — отклонять новые подключения к базе без разрыва существующих (полезно для drain'а и отладки).
- `KILL [db]` — немедленно сбросить все клиентские и серверные соединения к базе (кроме консоли); с 1.25.0 без имени базы — ко всем базам; после `KILL` требуется `RESUME`.
- `KILL_CLIENT <id>` — принудительно закрыть конкретное клиентское соединение (`id` из `SHOW CLIENTS`); с 1.24; **до 1.25.2 команда доступна любому консольному пользователю, не только `admin_users`** (CVE-2026-6667).

**Особенности shutdown:** при `SHUTDOWN WAIT_FOR_SERVERS`/`WAIT_FOR_CLIENTS` Unix-сокеты остаются открытыми и принимают **только** подключения к админ-консоли — это способ диагностировать зависший shutdown и принудительно закрыть клиента через `KILL_CLIENT`.

### Таймауты и защита от зависших транзакций

```ini
# pgbouncer.ini
server_idle_timeout = 600      # закрывать простаивающие серверные соединения (по умолчанию 600)
server_lifetime = 3600         # переподключать старые серверные соединения (NAT, firewall)
server_connect_timeout = 15    # таймаут подключения к бэкенду
server_login_retry = 15        # пауза между повторными логинами; в этот период новые
                                # клиенты получают ошибку сразу — плановые работы через PAUSE
client_login_timeout = 60      # таймаут логина клиента
query_wait_timeout = 120       # макс. ожидание серверного соединения; 0 = бесконечно
                                # (с 1.26 — переопределение на уровне [users]/[databases])
query_timeout = 0              # отменять длинные запросы (опасно: ломает миграции;
                                # должен быть чуть меньше server-side statement_timeout;
                                # до 1.26.0 мог закрывать соединения без запроса в полёте)
idle_transaction_timeout = 0   # отключать «idle in transaction» (0 = disabled)
transaction_timeout = 0        # отключать длинные транзакции (0 = disabled; с 1.25.0)
client_idle_timeout = 0        # закрывать простаивающие клиентские сессии (0 = disabled; с 1.24.0)
cancel_wait_timeout = 10       # таймаут пересылки cancel-запроса
```

**Защита от всплесков (burst):** `reserve_pool_size` дополнительных соединений подключается, когда клиент ждёт дольше `reserve_pool_timeout` (5 с по умолчанию); клиентские лимиты `max_db_client_connections`/`max_user_client_connections` (с 1.24) задают максимум клиентских сессий на базу/пользователя — разница с `max_db_connections`/`max_user_connections` = допустимый размер очереди. Sizing — в **[Настройке](./pgbouncer_setup.md)**.

**Дополнительные таймауты:** `autodb_idle_timeout` (3600) — освобождение автоматически созданных (`*`) баз; `pool_idle_timeout` (1.26+, 0 = disabled) — освобождение пулов (база+пользователь) без клиентов и серверов; `query_wait_notify` (5) — NOTICE клиенту, простоявшему в очереди дольше N сек; `server_fast_close` — закрывать серверные соединения в session-режиме при `close_needed` сразу (а не по завершении сессии) — применяет изменения конфигурации быстрее, но клиентские сессии придётся переподключать.

### Профили нагрузки

| Профиль | Характеристики | `default_pool_size` | `pool_mode` | Особенности |
| :--- | :--- | :--- | :--- | :--- |
| **OLTP (Web, API)** | Короткие транзакции, < 50 мс | 20–50 | transaction | Prepared statements (`max_prepared_statements`) |
| **OLAP / Аналитика** | Долгие запросы, > 1 с | 5–10 | session | Один клиент = одно соединение |
| **Mixture (Hybrid)** | Смесь коротких и длинных | 30–60 | transaction + per-user | Длинные запросы — в отдельный пул/базу |
| **Bulk Load / ETL** | Массовая вставка, `COPY` | 10–20 | session | Большие транзакции, низкая параллельность |

### ORM и драйверы

PgBouncer совместим с большинством PostgreSQL-драйверов и ORM, но есть нюансы:

- С 1.26.0 PgBouncer отправляет клиенту `ParameterStatus`: `pgbouncer.version`, `pgbouncer.pool_mode`, `pgbouncer.max_prepared_statements` — драйвер может детектировать, что он за пулером, и адаптировать поведение.
- `login_notify_message` (1.26.0) — NOTICE клиенту после логина; используйте, чтобы клиенты явно видели, что подключены к пулеру, а не к PostgreSQL.
- **Hibernate / JPA**: `hibernate.connection.provider_disables_autocommit=true` при transaction pooling, чтобы избежать лишних round-trip.
- **Django**: `CONN_MAX_AGE = 0` (по умолчанию) не конфликтует с PgBouncer; при `> 0` убедитесь, что долгие соединения не удерживают серверные сессии.
- **Prisma**: поддерживает connection URL с портом 6432; `preparedStatements: false` при PgBouncer < 1.21.
- **SQLAlchemy**: `pool_pre_ping=True` полезен, но создаёт дополнительные запросы `SELECT 1`; лучше полагаться на `server_check_query` в PgBouncer (с 1.25.0 дефолт — пустой запрос вместо `SELECT 1`).
- **psycopg2 / psycopg3**: application-side пул (`ThreadedConnectionPool`) избыточен при PgBouncer — либо пул в приложении, либо PgBouncer, но не оба одновременно.
- `application_name_add_host = 1` — добавляет адрес/порт клиента в `application_name` при подключении (только в startup; последующий `SET` не отслеживается) — помогает находить источник проблемных запросов.

### Совместимость со специфическими функциями PostgreSQL

| Функция | Session | Transaction | Statement |
| :--- | :--- | :--- | :--- |
| **Temporary tables** | Да | Нет | Нет |
| **LISTEN / NOTIFY** | Да | Нет | Нет |
| **Advisory locks (`pg_advisory_lock`)** | Да | Да (в рамках транзакции; сбрасывается при COMMIT/ROLLBACK) | Нет |
| **Large Objects (`lo_*`)** | Да | Да | Нет |
| **`COPY ... FROM STDIN`** | Да | Да (до 1.26.0 поздние COPY-сообщения могли исчерпать пул в transaction-режиме — исправлено в 1.26.0; `COPY` вне явной транзакции работает с 1.26.0) | Да |
| **`SET`/`RESET` параметров сессии** | Да | Только отслеживаемые параметры (см. ниже) | Только отслеживаемые |

**Сессионные параметры в transaction pooling.** По умолчанию PgBouncer отслеживает и восстанавливает между транзакциями: `application_name`, `client_encoding`, `DateStyle`, `default_transaction_read_only` (PG 14+), `IntervalStyle`, `scram_iterations` (PG 16+), `search_path` (PG 18+, по умолчанию с 1.26), `session_authorization`, `standard_conforming_strings`, `TimeZone`. Другие параметры — через `track_extra_parameters` (например, расширения). Для параметров **вне** списка `SET` между транзакциями не сохраняется: PgBouncer знает только значение из startup-пакета клиента, а изменения через `SET` «утекают» к соседям по серверному соединению, если не включён `server_reset_query_always` (меняет недетерминированное поведение на детерминированное — клиенты теряют состояние после каждой транзакции).

- Для `LISTEN/NOTIFY` — `pool_mode = session` для этого пользователя или выделенный инстанс.
- **Репликация:** с 1.23 PgBouncer поддерживает replication-соединения (`SHOW CLIENTS`/`SHOW SERVERS` → `replication`: `none`/`logical`/`physical`); физическая репликация (walsender) и фоновые воркеры обычно подключаются к PostgreSQL напрямую, мимо пулера.
- FDW: внешние обращения могут удерживать серверное соединение дольше обычного — учитывайте в sizing'е.

### Бенчмаркинг PgBouncer

```bash
# Создание тестовой базы
pgbench -i -s 50 myapp_db

# Тест без PgBouncer (прямое подключение)
pgbench -c 100 -j 4 -T 30 -P 1 myapp_db

# Тест через PgBouncer
pgbench -h 127.0.0.1 -p 6432 -c 100 -j 4 -T 30 -P 1 myapp_db
```

Сравнивайте TPS и латентность. При transaction pooling с `c > 50` результат должен быть стабильным или выше за счёт переиспользования соединений; при `c` значительно больше `default_pool_size` растёт `cl_waiting`/`maxwait` — это ожидаемое поведение очереди, а не деградация. Перед пиковой нагрузкой прогоните тот же тест с пиковыми параметрами.

## Операции и команды

**Админ-консоль — команды управления:**

| Команда | Эффект |
| :--- | :--- |
| `RELOAD` | Перечитать конфиг и `changeable`-настройки (аналог `SIGHUP`), reopen `logfile`; смена параметров подключения в `[databases]` автоматически закрывает старые серверные соединения при освобождении; TLS-соединения пересоздаются **только** при изменении TLS-настроек (с 1.24 — раньше RELOAD пересоздавал все TLS-соединения, что давало просадку производительности) |
| `SET key = arg` | Смена `changeable`-настройки в рантайме, например `SET log_connections = 1;`, `SET server_check_query = 'select 2';` |
| `PAUSE [db]` | Отключиться от всех серверов (дождавшись освобождения по правилам режима); новые клиенты ждут `RESUME` |
| `RESUME [db]` | Возобновить после `PAUSE`/`KILL` |
| `DISABLE db` / `ENABLE db` | Отклонять/разрешать новые подключения без разрыва существующих |
| `RECONNECT [db]` | Закрыть серверные соединения при освобождении, новые — по новому маршруту; для gradual switchover и случаев, когда маршрутизация ниже PgBouncer |
| `WAIT_CLOSE [db]` | Дождаться освобождения всех соединений из состояния `close_needed` (в скриптах switchover) |
| `KILL [db]` | Немедленно сбросить все соединения к базе (без аргумента — ко всем базам, с 1.25.0); после — `RESUME` |
| `KILL_CLIENT <id>` | Сбросить конкретное клиентское соединение (`id` из `SHOW CLIENTS`) |
| `SHUTDOWN` / `SHUTDOWN WAIT_FOR_SERVERS` / `SHUTDOWN WAIT_FOR_CLIENTS` | Мгновенное / safe / super safe завершение процесса |

**Ограничение:** консоль поддерживает только Simple Query Protocol; `psql` работает, драйверы с принудительным extended protocol — нет. `disable_pqexec = 1` отключает Simple Query на обычных базах (защита от части SQL-инъекций), но **не используйте его, если нужен доступ к консоли через TCP**.

**Прочие операционные настройки:** `conffile` — смена конфигурационного файла для следующего `RELOAD` (blue-green конфигов); `verbose = 1..3` — уровень детализации; `log_stats = 0` — не дублировать статистику в лог при внешнем мониторинге; `syslog = 1` — логи в syslog/journald (с метаданными severity).

## Валидация

1. **Состояние экземпляра:**

```sql
SHOW STATE;
-- → state: active   (paused — если база на паузе)
SHOW DATABASES;
-- → все базы: paused=0, disabled=0
```

2. **Здоровье очереди:**

```sql
SHOW POOLS;
-- → maxwait = 0.00, cl_waiting = 0 для всех пулов
```

3. **Серверные соединения на правильном бэкенде:**

```sql
SHOW SERVERS;
-- → addr = ожидаемый IP, state = active/idle, close_needed = 0
```

4. **Экспортер Prometheus:**

```bash
curl -s http://127.0.0.1:9127/metrics | grep pgbouncer_pools
# → pgbouncer_pools_client_active_connections{...} 120
```

5. **Клиентский smoke-тест через пулер:**

```bash
psql -h 127.0.0.1 -p 6432 -U myuser -d myapp_db -c "SELECT 1;"
# →  1
```

6. **Churn соединений (1.26+):**

```sql
SHOW STATS;
-- → total_client_login_count растёт значительно быстрее,
--    чем число реальных клиентов → приложение чейнжит соединения
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **`cl_waiting` постоянно > 0, растёт `maxwait`** | Долгие транзакции или малый пул | `pg_stat_activity` (долгие транзакции), увеличить `default_pool_size`, вычитывать read-only на реплики; `reserve_pool_size` на всплески |
| **`sv_active` == `default_pool_size`** | Пул исчерпан | То же; проверить `max_db_connections`/`max_user_connections`; в логах 1.26+ причина eviction: `evicted for max_db_connections` / `evicted for pool_size` / `evicted for max_user_connections` |
| **`ERROR: closing because: ... pool full`** | Исчерпан `max_client_conn` | Поднять `max_client_conn` (в пределах `ulimit -n`) |
| **Лимит клиентских сессий на базу/пользователя** | `max_db_client_connections` / `max_user_client_connections` (1.24+) | Поднять лимит или увеличить разрыв с серверным лимитом (= размер очереди) |
| **`ERROR: prepared statement "..." already exists`** | Конфликт имён в transaction pooling на версиях < 1.21 | Обновиться до 1.21+ или отключить prepared statements в приложении |
| **`ERROR: cached plan must not change result type`** | DDL изменил типы результата/аргументов | `RECONNECT` на консоли после миграции |
| **Высокий `Planning Time` через пулер** | Кеш планов не переиспользуется между бэкендами | `max_prepared_statements` (1.21+, дефолт 200 с 1.24), драйверный кеш; см. [Планировщик](../Concepts/planner_internals.md) |
| **Утечка клиентских сессий** | Приложение не закрывает соединения | `SHOW CLIENTS` по `application_name`/`addr`; `client_idle_timeout`; `total_client_login_count` (1.26+) для churn |
| **Медленные запросы только через пулер** | Очередь или сессионные параметры вне списка отслеживаемых | `total_wait_time` в `SHOW STATS`; `track_extra_parameters` |
| **Экспортер не отдаёт метрики / ошибки подключения** | Драйвер экспортера шлёт `extra_float_digits` | `ignore_startup_parameters = extra_float_digits` |
| **OOM killer убивает PgBouncer** | Утечка/перерасход памяти | `MemoryMax` в unit'е, `verbose = 0`, меньше `max_prepared_statements` |
| **Задержка ~15 с на подключении после рестарта PostgreSQL** | `server_login_retry` | Плановые работы — через `PAUSE`/`RESUME` |
| **Один крупный результат «вешает» пулер** | Single-threaded event loop: одна сессия с большим result set занимает цикл | `sbuf_loopcnt` (дефолт 5 циклов по `pkt_buf`), `max_packet_size`; читать меньшими порциями |
| **`COPY` в transaction-режиме исчерпывает пул** | Баг ≤1.25: поздние COPY-сообщения | Обновиться до 1.26.0 |
| **`query_timeout` закрывает соединения без запроса** | Баг ≤1.25 | Обновиться до 1.26.0 |
| **`KILL_CLIENT` доступен не-admin'у** | CVE-2026-6667 на <1.25.2 | Обновиться до 1.25.2+ |
| **`avg_wait_time` выглядит неверным** | Баг расчёта <1.23.0 | Обновиться до 1.23.0+ |

## Лучшие практики

1. **Алертьте на `cl_waiting > 0` и `maxwait > 2` с**, а не только на утилизацию пула — очередь видна раньше, чем исчерпание.
2. **Мониторьте `total_wait_time`/`avg_wait_time`** (`SHOW STATS`, `pgbouncer_stats_client_wait_seconds_total`) — прямой сигнал нехватки серверных соединений.
3. **`query_wait_timeout`** как защита от зависшего бэкенда (по умолчанию 120 с) — не отключайте навсегда (`0`) в продакшене.
4. **Peering (`peer_id` + `[peers]`)** при нескольких экземплярах/балансировщике — иначе запросы отмены (cancel) теряются.
5. **Учитывайте `server_login_retry`** при failover: пауза 15 с между попытками логина — плановые работы через `PAUSE`.
6. **Аудит**: `log_connections = 1`, `log_disconnections = 1` — кто подключался и по какой причине отключался.
7. **Регулярный бенчмарк** `pgbench` с пиковыми параметрами перед ожидаемыми пиками нагрузки.
8. **`SHOW CONFIG`** после `RELOAD` — убедиться, что `changeable`-настройки применились, а неперезагружаемые требуют restart'а.
9. **`server_round_robin = 1`** при round-robin бэкендах (host list, multi-IP DNS) — равномерная нагрузка на установленных соединениях вместо LIFO.
10. **`pool_idle_timeout`** (1.26+) при множестве редко подключающихся пользователей — иначе число пулов растёт без ограничения; учтите, что освобождённый пул теряет статистику.
11. **`disable_pqexec = 1`** на обычных базах для защиты от части SQL-инъекций — если доступ к консоли только через Unix-сокет.

## Очистка и откат

- **Drain перед остановкой:** `DISABLE db` → дождаться завершения транзакций (`WAIT_CLOSE`) → `SHUTDOWN WAIT_FOR_CLIENTS` (или `SIGTERM`).
- **Откат версии (blue-green):** переключить балансировщик/конфиг приложения на старый экземпляр, остановить новый.
- **Откат изменённых настроек:** `git restore /etc/pgbouncer/pgbouncer.ini && systemctl reload pgbouncer`; неперезагружаемые настройки — `systemctl restart pgbouncer`.
- **Ротация логов:** `SIGHUP`/`RELOAD` reopens `logfile` (на Windows — рестарт службы).
- **Отключение мониторинга:** остановить `pgbouncer_exporter`; `ignore_startup_parameters` в `pgbouncer.ini` можно оставить (безвредно).

## Дополнительная информация

- **[Настройка PgBouncer](./pgbouncer_setup.md)** — установка, конфигурация, аутентификация, TLS, hardening, capacity planning.
- **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — HAProxy + PgBouncer, Patroni, switchover.
- **[Мониторинг PostgreSQL](./observability.md)** — метрики, алерты и wait events на стороне СУБД.
- **[Оптимизация производительности](./performance_tuning.md)** — тюнинг самой СУБД.
- **[Connection Pooling: общая теория](../../../Networking/Concepts/connection_pooling.md)** — пулы на уровне nginx/HAProxy, conntrack.
- **[Мониторинг PostgreSQL в Zabbix](../../../Zabbix/zabbix_postgresql_monitoring.md)** — особенности мониторинга через пулер.
- **[Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md)** — сохранение реального IP клиента за HAProxy.
- **[Сетевая связность в Kubernetes](./kubernetes_connectivity.md)** — PgBouncer как прокси в кластере.
- **[Адvisory locks и уровни блокировок](../Concepts/concurrency_and_locking.md)** — advisory locks при transaction pooling.
- Официальная документация: [Usage (консоль, сигналы)](https://www.pgbouncer.org/usage.html), [Configuration](https://www.pgbouncer.org/config.html), [Changelog](https://www.pgbouncer.org/changelog.html).
