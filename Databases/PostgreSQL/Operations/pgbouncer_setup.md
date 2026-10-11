# Настройка PgBouncer для PostgreSQL

**Актуально для:** PgBouncer 1.21–1.26, PostgreSQL 13–18

> PgBouncer — легковесный пулер соединений PostgreSQL: event-driven процесс на одно ядро, десятки тысяч клиентских сессий при сотне реальных серверных соединений. Установка, конфигурация, аутентификация и безопасность; мониторинг, failover и отказоустойчивость — в **[Эксплуатация и мониторинг PgBouncer](./pgbouncer_operations.md)**.

## Определения

- **PgBouncer** — легковесный connection pooler для PostgreSQL, работающий на уровне протокола как прозрачный прокси между приложением и сервером: принимает клиентские подключения, аутентифицирует их сам и переиспользует пул серверных соединений.
- **Пул соединений (Connection Pool)** — набор заранее установленных соединений с базой данных, распределяемых между активными клиентами.
- **Пулинг сессий (Session Pooling)** — серверное соединение закреплено за клиентом до отключения клиента. Режим по умолчанию; самый безопасный, но не решает проблему масштабирования при большом числе «спящих» клиентов.
- **Пулинг транзакций (Transaction Pooling)** — серверное соединение возвращается в пул сразу после `COMMIT`/`ROLLBACK`. Самый эффективный режим для веб-приложений.
- **Пулинг операторов (Statement Pooling)** — соединение возвращается в пул после каждого запроса; многооператорные транзакции запрещены. Используется крайне редко.
- **Шторм соединений (Connection Storm)** — лавинообразный рост попыток подключения к БД, способный исчерпать ресурсы ОС и привести к отказу СУБД.
- **Админ-консоль** — виртуальная база данных `pgbouncer` с командами `SHOW`/`PAUSE`/`RELOAD` и др. для управления экземпляром.
- **Forced user** — пользователь, зафиксированный в строке подключения секции `[databases]` (`user=...`); все клиенты базы заходят на сервер под ним, пул становится единственным для всей базы.
- **auth_file / auth_user** — статический файл пользователей (`userlist.txt`) или механизм динамической проверки паролей через запрос к PostgreSQL.

## Предпосылки

1. **PostgreSQL 10+** (SCRAM-SHA-256); для актуальных возможностей — 13+.
2. **PgBouncer 1.21+** — критично для протокольных Prepared Statements в режимах transaction/statement pooling (`max_prepared_statements`). Актуальная версия — **1.26.0** (2026-09-23): закрыты CVE-2026-19888, CVE-2026-6668, CVE-2026-6669; `search_path` и `default_transaction_read_only` отслеживаются по умолчанию.
3. **Порты:** 6432 — пулер (`listen_port`, по умолчанию), 5432 — PostgreSQL. Важно: если `listen_addr` не задан, PgBouncer слушает **только Unix-сокет** — TCP-подключения не работают.
4. **Права доступа:** отдельный пользователь ОС `pgbouncer` без shell (`/usr/sbin/nologin`); для динамической аутентификации — непривилегированная роль БД + `SECURITY DEFINER`-функция (см. ниже).
5. **Дескрипторы:** `ulimit -n` ≥ 65536 в production; теоретический максимум дескрипторов: `max_client_conn + (max_pool_size × число_баз × число_пользователей)`.
6. **Сетевая доступность:** приложение должно иметь доступ к `listen_addr:listen_port`; PostgreSQL — к `host` из `[databases]`.

## Основные концепции

### Архитектура

```text
Клиент → [PgBouncer frontend: listen_addr:listen_port] ⇄ [пул серверных соединений] → PostgreSQL
```

- **Single-threaded event-driven** (libevent): один процесс обслуживает одно ядро. Для использования нескольких ядер запускают несколько экземпляров на одном порту с `so_reuseport = 1` (Linux, DragonFlyBSD, FreeBSD).
- **Frontend** — клиентские сессии; состояния клиентских соединений (`SHOW CLIENTS`): `active` (связан с серверным), `idle` (нет запросов), `waiting` (запрос ждёт серверного соединения), `active_cancel_req`, `waiting_cancel_req`.
- **Backend** — пул серверных соединений; состояния (`SHOW SERVERS`): `active`, `idle` (свободно, готов к выдаче), `used` (простаивал дольше `server_check_delay`, требуется `server_check_query`), `tested` (выполняется `server_reset_query`/`server_check_query`), `new`, `active_cancel`, `being_canceled`.
- **DNS** — хост из `[databases]` резолвится в момент подключения и кэшируется на `dns_max_ttl` (15 с по умолчанию). При изменении резолва старые серверные соединения закрываются при освобождении, новые идут на новый адрес — `RELOAD` для DNS-изменений **не требуется**.
- **Жизненный цикл соединения в transaction pooling:**
  1. Клиент начинает транзакцию (`START TRANSACTION` или первый DML/DDL).
  2. PgBouncer выдаёт свободное серверное соединение из пула (`default_pool_size` на пару «база, пользователь»).
  3. Запрос выполняется, результат возвращается клиенту.
  4. На `COMMIT`/`ROLLBACK` серверное соединение немедленно возвращается в пул.
  5. Клиентское соединение остаётся открытым, но не держит серверную сессию.
- В отличие от application-side пулов (HikariCP, `psycopg2.pool`), PgBouncer централизован и не зависит от языка/фреймворка приложения.

### Зачем нужен PgBouncer

1. **Экономия RAM:** PostgreSQL создаёт процесс на каждое соединение (порядка 5–10 MB на бэкенд). 10 000 клиентов обслуживаются через 100–200 реальных соединений.
2. **Снижение latency:** исключается форк процесса PostgreSQL при каждом новом подключении.
3. **Управление очередями:** при исчерпании пула запросы встают в очередь (`cl_waiting`), а не «убивают» БД новыми подключениями.
4. **Безопасный failover:** бэкенд можно переключить (Primary → Replica, switchover) незаметно для приложения (см. `pgbouncer_operations.md`).

### Режимы работы (Pool Modes)

| Характеристика | Session | Transaction | Statement |
| :--- | :--- | :--- | :--- |
| **Удержание соединения** | Весь период сессии | Только на время транзакции | На время одного запроса |
| **Поддержка транзакций** | Полная | Полная | Нет (многооператорные запрещены) |
| **Временные таблицы** | Да | Нет | Нет |
| **Протокольные Prepared Statements** | Да | **Да (PgBouncer 1.21+)** | Да (1.21+) |
| **LISTEN/NOTIFY** | Да | Нет | Нет |
| **Когда использовать** | pgAdmin, миграции, legacy-код с temp-таблицами, LISTEN/NOTIFY | Веб-приложения, API, ORM (Hibernate, Prisma, Django) | Только read-only без транзакций; практически не используется |

`pool_mode` задаётся глобально, в секции `[databases]` для базы и в секции `[users]` для пользователя — более частный уровень перекрывает глобальный.

### Prepared Statements в transaction pooling

Начиная с 1.21 (`max_prepared_statements`, по умолчанию **200**; `0` отключает поддержку):

- PgBouncer отслеживает протокольные (расширенный протокол) именованные prepared statements: каждому уникальному тексту запроса присваивается внутреннее имя `PGBOUNCER_<id>`, общий кеш текстов запросов един для всех клиентов.
- Если на новом серверном соединении запрос ещё не подготовлен — PgBouncer готовит его прозрачно перед выполнением; при 100 клиентах с одним запросом и `pool_size = 20` запрос парсится на сервере только 20 раз.
- Размер LRU-кеша prepared statements — **на одно серверное соединение**; слишком маленькое значение вытесняет частые запросы, слишком большое — расходует память PostgreSQL (планы) и PgBouncer (тексты запросов).
- SQL-команды `PREPARE`/`EXECUTE`/`DEALLOCATE` передаются напрямую; `DEALLOCATE ALL` и `DISCARD ALL` очищают отслеживаемые statements клиента.
- При DDL, меняющем типы результата/аргументов, PostgreSQL выдаёт `ERROR: cached plan must not change result type` — лечится командой `RECONNECT` на консоли после миграции.
- Подготовленные statements кешируются на стороне PgBouncer, а не PostgreSQL; SQL-level `PREPARE` не отслеживается.
- Оценка памяти (из документации): 1000 активных клиентов, 200 уникальных запросов по 5 kB, `pkt_buf = 4096` → ~17 MB.

Детали влияния на планировщик — в **[Планировщик и кеш планов](../Concepts/planner_internals.md)**.

### Планирование ёмкости пула (Capacity Planning)

Размер пула задаётся профилем нагрузки на БД, а не числом клиентов или воркеров приложения:

- `default_pool_size` (по умолчанию **20**) — серверных соединений на пару (база, пользователь). Для коротких OLTP-транзакций обычно 20–50.
- `max_client_conn` (по умолчанию **100**) — лимит **клиентских сессий**, а не соединений к БД. При повышении проверьте `ulimit -n`.
- Правило: суммарный `default_pool_size` всех пулов **меньше** `max_connections` PostgreSQL — запас 30% на админов, миграции, логическую репликацию. Иначе пулер упирается в лимит СУБД.
- Транзакционный пулинг умножает ёмкость: 10 000 клиентов при пуле 50 → ~50 реальных соединений к БД.
- Альтернативная эвристика стартового значения — число ядер CPU (для HDD `(ядра × 2) + диски`); см. **[Масштабирование](../Concepts/scaling.md)**.

#### Формулы и примеры

**Минимальный `default_pool_size` для OLTP:**

```text
default_pool_size ≥ (RPS × avg_latency_sec) / parallelism_factor
```

где `parallelism_factor` — эффективная параллельность одного PostgreSQL-процесса (обычно 1.0–2.0). Пример: 2000 RPS, средняя латентность 15 мс:

```text
(2000 × 0.015) / 1.5 ≈ 20 → default_pool_size = 25–30
```

**Максимальный `default_pool_size`:**

```text
sum(default_pool_size) ≤ max_connections × 0.7
```

**`max_client_conn` под нагрузку:**

```text
max_client_conn ≤ ulimit -n − (max_pool_size × число_баз × число_пользователей) − 64
```

Запас 64 дескриптора — на логи, stdin/stdout и служебные файлы.

**`reserve_pool_size` при всплесках:**

```text
reserve_pool_size = ceil(default_pool_size × 0.2)
```

Резервный пул подключается только когда основной исчерпан и клиент ждёт дольше `reserve_pool_timeout` (5 с по умолчанию; `0` отключает).

#### Типичные ошибки capacity planning

1. **`default_pool_size = max_connections`**: пулер блокирует СУБД, не оставляя места для администрирования.
2. **Игнорирование пиков**: `default_pool_size` должен покрывать пиковое RPS, а не среднее.
3. **Слишком маленький `max_client_conn`**: при 10k+ воркерах приложения получают `FATAL: too many open files`, хотя пул в БД не переполнен.
4. **Одна база — все пользователи**: разделяйте пользователей по базам или используйте `auth_user`/forced user для изоляции нагрузок.
5. **Игнорирование `max_db_connections`/`max_user_connections`**: без них одна «горячая» база или пользователь может съесть весь пул.

Общие принципы пулинга соединений — в **[Connection Pooling](../../../Networking/Concepts/connection_pooling.md)**.

## Практические сценарии

### Установка

**Ubuntu / Debian:**

```bash
sudo apt update && sudo apt install pgbouncer -y
```

**RHEL / CentOS / Rocky Linux:**

```bash
sudo dnf install epel-release -y
sudo dnf install pgbouncer -y
```

Проверка версии:

```bash
pgbouncer -V
# → pgbouncer 1.26.0
```

### Конфигурация (`pgbouncer.ini`)

Типовой файл `/etc/pgbouncer/pgbouncer.ini` (значения по умолчанию PgBouncer указаны в комментариях):

```ini
[databases]
# Шаблон: dbname = host=... port=... dbname=... user=... auth_user=...
# "*" = host=127.0.0.1 port=5432   — fallback для любых имён баз
myapp_db = host=10.0.0.10 port=5432 dbname=myapp_prod auth_user=pgb_auth_user

[pgbouncer]
# Сетевые настройки
listen_addr = 0.0.0.0          # по умолчанию не задан — только Unix-сокет! "*" = все адреса
listen_port = 6432             # по умолчанию 6432
unix_socket_dir = /var/run/postgresql  # по умолчанию /tmp; "" отключает Unix-сокеты
user = pgbouncer               # сброс привилегий (запуск от root) или уже работающий пользователь

# Логирование (все флаги по умолчанию = 1)
log_connections = 1
log_disconnections = 1
log_pooler_errors = 1
log_stats = 1
stats_period = 60              # период усреднения статистики, сек
verbose = 0                    # 0–3, аналог -v

# Аутентификация
auth_type = scram-sha-256      # по умолчанию md5 (при SCRAM-секрете в auth_file автоматом используется SCRAM)
auth_file = /etc/pgbouncer/userlist.txt
# Динамическая проверка паролей через БД (рекомендуется вместо синхронизации userlist.txt)
auth_user = pgbouncer
auth_query = SELECT usename, passwd FROM pgbouncer.get_auth($1)

# Настройки пула
pool_mode = transaction        # по умолчанию session
default_pool_size = 50         # по умолчанию 20
min_pool_size = 0              # прогрев пула после простоя; 0 = disabled
reserve_pool_size = 10         # по умолчанию 0 (disabled)
reserve_pool_timeout = 5       # сек; 0 = disabled
max_client_conn = 10000        # по умолчанию 100
max_db_connections = 0         # 0 = unlimited; лимит серверных соединений на базу
max_user_connections = 0       # 0 = unlimited; лимит серверных соединений на пользователя

# Prepared Statements (PgBouncer 1.21+; по умолчанию 200, 0 = disabled)
max_prepared_statements = 100

# Отслеживаемые параметры сессии в transaction pooling
# (по умолчанию отслеживаются: application_name, client_encoding, DateStyle,
#  default_transaction_read_only, IntervalStyle, scram_iterations, search_path,
#  session_authorization, standard_conforming_strings, TimeZone)
track_extra_parameters =

# Администрирование
admin_users = pgb_admin        # полные права на консоль (по умолчанию пусто)
stats_users = pgb_monitor      # read-only: все SHOW-команды (по умолчанию пусто)

# Прочее
server_idle_timeout = 600      # сек, по умолчанию 600; 0 = disabled
server_lifetime = 3600         # сек, по умолчанию 3600
server_connect_timeout = 15    # сек, по умолчанию 15
query_wait_timeout = 120       # сек, по умолчанию 120; 0 = бесконечная очередь
```

Проверка конфига перед применением — запуск в foreground (флага `--check-config` нет; `pgbouncer -d` сразу демонизирует процесс и **не годится** для проверки):

```bash
pgbouncer /etc/pgbouncer/pgbouncer.ini
# → LOG: parsing ... / LOG: listening on ...   (ошибки парсинга выводятся сразу)
# Ctrl-C для остановки
```

### Секция `[databases]` — строки подключения

Каждая строка `имя = connection_string` (формат близок к libpq, но не совпадает с ним):

| Ключ | Смысл |
| :--- | :--- |
| `host` | IP/имя; `/путь` — Unix-сокет, `@имя` — abstract namespace (Linux/Windows); список через запятую — round-robin; по умолчанию — Unix-сокет |
| `port` | По умолчанию 5432 |
| `dbname` | По умолчанию — имя базы клиента |
| `user` | Forced user: все клиенты базы идут на сервер под ним, пул единственный |
| `password` | Пароль forced user (без него — из `auth_file`; `auth_query` не поддерживается) |
| `auth_user` / `auth_query` / `auth_dbname` | Переопределения глобальных настроек аутентификации; `auth_query` целиком в одинарных кавычках |
| `pool_size` / `min_pool_size` / `reserve_pool_size` | Размеры пула для базы |
| `pool_mode` | Режим пула для базы |
| `connect_query` | Запрос после установления соединения, до выдачи клиенту (ошибки логируются, игнорируются) |
| `load_balance_hosts` | `round-robin` (по умолчанию) / `disable` — выбор хоста из списка для новых соединений |
| `max_db_connections` / `max_db_client_connections` | Лимиты серверных/клиентских соединений для базы |
| `server_lifetime` | Переопределение для базы |
| `client_encoding` / `datestyle` / `timezone` | Запрашиваемые параметры сессии у сервера |

Ключ `pgbouncer` зарезервирован за админ-консолью. Имя `*` — fallback: соединения к неописанным базам маршрутизируются по нему (пулы такого «авто»-вида освобождаются через `autodb_idle_timeout`, 3600 с).

### Секция `[users]` — настройки на пользователя

```ini
[users]
report_user = pool_mode=session pool_size=10
readonly_user = pool_mode=transaction max_user_connections=20
```

Доступные ключи: `pool_size`, `reserve_pool_size`, `pool_mode`, `max_user_connections`, `max_user_client_connections`, `query_timeout`, `query_wait_timeout`, `idle_transaction_timeout`, `transaction_timeout`, `client_idle_timeout`. Пользователь, описанный здесь, но отсутствующий в `auth_file`, аутентифицируется через `auth_query` (если задан `auth_user`).

### Динамическая аутентификация (`auth_user` + `auth_query`)

PgBouncer проверяет пароли пользователей напрямую в PostgreSQL, без синхронизации `userlist.txt`. Механизм: пользователи, отсутствующие в `auth_file`, запрашиваются через `auth_query` от имени `auth_user`; пароль самого `auth_user` берётся из `auth_file`.

1. **В PostgreSQL (под суперпользователем) — в каждой целевой базе** (запрос `auth_query` выполняется внутри той базы, к которой подключается клиент):

```sql
CREATE USER pgbouncer WITH PASSWORD 'pgbouncer_secret_password';
CREATE SCHEMA pgbouncer AUTHORIZATION pgbouncer;

-- Функция для получения хеша пароля; SECURITY DEFINER + фиксированный search_path
-- обязателен как защита от подмены search_path в startup-пакете (CVE-2025-12819)
CREATE OR REPLACE FUNCTION pgbouncer.get_auth(p_usename text)
RETURNS TABLE(usename text, passwd text) AS $$
    SELECT rolname::text, rolpassword::text
    FROM pg_catalog.pg_authid
    WHERE rolname = $1 AND rolcanlogin;
$$ LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog;

-- Ограничение прав
REVOKE ALL ON FUNCTION pgbouncer.get_auth(text) FROM PUBLIC;
GRANT USAGE ON SCHEMA pgbouncer TO pgbouncer;
```

Владелец функции должен иметь права на чтение `pg_catalog.pg_authid` (обычно суперпользователь). Прямой доступ `auth_user` к `pg_authid` требует админ-прав — документация рекомендует именно `SECURITY DEFINER`-функцию.

2. **В `userlist.txt` — только пользователя `pgbouncer`:**

```text
"pgbouncer" "SCRAM-SHA-256$4096:..."
```

Формат строки `userlist.txt`: `"имя" "пароль"` — пароль открытым текстом, MD5-хеш или SCRAM-verifier. Сгенерировать файл из `pg_authid` можно скриптом `etc/mkauth.py` из дистрибутива PgBouncer.

**Managed-серверы** (нет доступа к `pg_authid`): сгенерировать одинаковый SCRAM-verifier на обеих сторонах — `psql --echo-hidden ... \password роль` печатает verifier в консоль до отправки на сервер; вставить его в `userlist.txt` и установить через `ALTER ROLE ... PASSWORD 'verifier'`.

По умолчанию `auth_query`:

```sql
SELECT rolname, CASE WHEN rolvaliduntil < now() THEN NULL ELSE rolpassword END FROM pg_authid WHERE rolname=$1 AND rolcanlogin
```

(требует админ-прав у `auth_user`; учитывает истечение пароля через `rolvaliduntil`).

### Аутентификация клиентов (`auth_type`)

| `auth_type` | Поведение |
| :--- | :--- |
| `md5` | По умолчанию. MD5-проверка; если у пользователя SCRAM-секрет — автоматически SCRAM |
| `scram-sha-256` | SCRAM-SHA-256; `auth_file` должен содержать SCRAM-verifier или открытый пароль |
| `trust` | Без проверки пароля; пользователь должен существовать в `auth_file` |
| `any` | Как `trust`, но имя пользователя игнорируется; требует forced user в `[databases]`; консоль открыта всем |
| `cert` | TLS с валидным клиентским сертификатом; имя пользователя из CommonName |
| `hba` | Методы из `auth_hba_file` (аналог `pg_hba.conf`): поддерживаются `local`, `host`, `hostssl`, `hostnossl`; методы — поддерживаемые `auth_type` плюс `peer` и `reject`; `peer` работает на Unix-сокете |
| `ldap` / `pam` | Внешняя аутентификация (как в PostgreSQL); `pam` несовместим с `auth_user`, в HBA-файле не поддерживается |

`auth_hba_file` используется **только при `auth_type = hba`**. Ограничения формата: не поддерживаются `samerole`/`samegroup`, `samehost`/`samenetwork`, DNS-имена и доменные суффиксы в адресе; `map=` работает при `auth_type = cert` или `peer` (с `auth_ident_file`).

### TLS/SSL

```ini
# Шифрование трафика клиент ↔ PgBouncer (по умолчанию disable)
client_tls_sslmode = require
client_tls_cert_file = /etc/pgbouncer/server.crt
client_tls_key_file = /etc/pgbouncer/server.key   # владелец pgbouncer, права 0600

# Шифрование трафика PgBouncer ↔ PostgreSQL (по умолчанию prefer!)
server_tls_sslmode = verify-full
server_tls_ca_file = /etc/pgbouncer/ca.crt
server_tls_cert_file = /etc/pgbouncer/client.crt
server_tls_key_file = /etc/pgbouncer/client.key
```

Режимы: `disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full` (`client_tls_sslmode` по умолчанию `disable`, `server_tls_sslmode` — `prefer`). Версии: `client_tls_protocols`/`server_tls_protocols` = `secure` (TLS 1.2+). **Любое изменение TLS-настроек автоматически вызывает `RECONNECT`** — старые соединения доживают до освобождения, новые работают по новым файлам; при смене содержимого сертификатов без смены имён файлов после `RELOAD` то же самое.

### Hardening: systemd, лимиты, логирование

**systemd unit** (пакетные unitы уже есть; пример для hand-made конфигурации). `Type=notify-reload` поддерживается с PgBouncer 1.24.0 (systemd ≥ 253):

```ini
# /etc/systemd/system/pgbouncer.service
[Unit]
Description=PgBouncer PostgreSQL Connection Pooler
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=notify-reload
User=pgbouncer
Group=pgbouncer
# Без -d: systemd сам управляет фоновым процессом; -d требует pidfile+logfile и ломает Type=simple/notify
ExecStart=/usr/sbin/pgbouncer /etc/pgbouncer/pgbouncer.ini
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5s
LimitNOFILE=65536

# Ограничение ресурсов
MemoryMax=512M
CPUQuota=200%
TasksMax=64

# Безопасность
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pgbouncer
```

**ulimit и sysctl** — event-driven процесс ограничен числом дескрипторов и бэклогом listen-очереди (`listen_backlog`, по умолчанию 128):

```bash
# /etc/security/limits.d/pgbouncer.conf
pgbouncer soft nofile 65536
pgbouncer hard nofile 65536

# /etc/sysctl.d/99-pgbouncer.conf
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.tcp_syn_retries = 3
net.ipv4.tcp_synack_retries = 2
```

```bash
sudo sysctl --system
```

**Логирование и ротация.** В демон-режиме (`-d`) требуется `logfile` или `syslog`; при `logfile` после ротации нужен `kill -HUP` или `RELOAD` для переоткрытия файла:

```ini
# pgbouncer.ini
logfile = /var/log/pgbouncer/pgbouncer.log
# syslog = 1            # альтернатива logfile; syslog_facility = daemon
```

```ini
# /etc/logrotate.d/pgbouncer
/var/log/pgbouncer/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload pgbouncer >/dev/null 2>&1 || true
    endscript
}
```

**Дополнительные hardening-настройки:**

- `disable_pqexec = 1` — отключить Simple Query Protocol (одним пакетом можно отправить несколько запросов, что открывает класс SQL-инъекций); работает только для приложений на Extended Query Protocol.
- `application_name_add_host = 1` — добавить адрес клиента в `application_name` при подключении (помогает искать источник плохих запросов).
- `ignore_startup_parameters = extra_float_digits` — требуется для **pgbouncer_exporter** (и любых драйверов, шлющих неотслеживаемые параметры).
- `peer_id` + секция `[peers]` — объединение экземпляров в группу для передачи запросов отмены между процессами (нужно при `so_reuseport` и TCP-балансировщике перед несколькими пулерами).
- `scram_iterations = 4096` — итерации SCRAM при генерации verifier (по умолчанию 4096).

**Минимальные права:**

- Пользователь ОС `pgbouncer`: `/usr/sbin/nologin`, нет доступа к `/etc/postgresql`, `/var/lib/postgresql` и домашним каталогам других пользователей; ключи TLS — владелец `pgbouncer`, права `0600`.
- Пользователь БД `pgbouncer` (для `auth_query`): только `USAGE` на схеме и `EXECUTE` на функции; никаких `SUPERUSER`/`CREATEDB`.

**Аудит и compliance:** `log_connections = 1`, `log_disconnections = 1`, `log_pooler_errors = 1` — попытки аутентификации, отключения с причинами, ошибки пулера. Ключевые события для аудита: неуспешные логины, достижение лимитов (`max_client_conn`, `max_db_connections`), операции `PAUSE`/`RESUME`/`RELOAD` на консоли.

### Резервное копирование конфигурации

Храните `pgbouncer.ini`, `userlist.txt` (и `auth_hba_file`, если используется) в Git. Восстановление при аварии — минуты: вернуть файлы из Git, `systemctl reload pgbouncer` (SIGHUP = `RELOAD`).

## Операции и команды

**Командная строка:**

```text
pgbouncer [-d] [-v] [-q] [-u user] <pgbouncer.ini>
pgbouncer -V | -h
```

- `-d` — демонизация (требует `pidfile` + `logfile`/`syslog`); для systemd **не используется**.
- `-v` — verbosity (можно многократно; аналог `verbose = 0–3`), `-q` — не писать в stderr, `-u user` — сменить пользователя при старте.
- `SIGHUP` — эквивалент консольной команды `RELOAD` (перечитать конфиг и `changeable`-настройки).

**Админ-консоль** — полное описание команд и SHOW-запросов в **[Эксплуатация и мониторинг PgBouncer](./pgbouncer_operations.md)**. Минимально для эксплуатации конфигурации:

```bash
psql -h /var/run/postgresql -U pgb_admin pgbouncer   # Unix-сокет; или -h 127.0.0.1 -p 6432
```

```sql
RELOAD;                      -- перечитать конфиг (SIGHUP)
SHOW CONFIG;                 -- текущие значения + changeable (да/нет — можно ли менять через SET)
SHOW DATABASES;              -- маршруты, размеры пулов, paused/disabled
SET log_connections = 1;     -- смена changeable-настройки в рантайме
```

Права на консоль: `admin_users` (все команды), `stats_users` (только `SHOW`). Пользователь `pgbouncer` входит без пароля через Unix-сокет, если UID совпадает с UID процесса. Консоль поддерживает **только Simple Query Protocol** — драйверы, шлющающие все команды расширенным протоколом, на ней не работают.

## Валидация

1. **Статус сервиса:**

```bash
systemctl status pgbouncer
# → active (running), Main PID, LimitNOFILE=65536
```

2. **Тестовое подключение через пулер:**

```bash
psql -h 127.0.0.1 -p 6432 -U myuser -d myapp_db -c "SELECT 1;"
# →  ?column?
# →  1
```

3. **Проверка маршрута и пула:**

```sql
SHOW DATABASES;
-- → myapp_db | 10.0.0.10 | 5432 | myapp_prod | ... pool_size=50 ... paused=0 disabled=0
SHOW POOLS;
-- → появляются строки (database, user) после первой нагрузки
```

4. **Проверка Prepared Statements (1.21+):** приложение выполняет подготовленные запросы без ошибок `unsupported frontend message`; в `SHOW SERVERS` поле `prepared_statements > 0`.

5. **Проверка, что трафик идёт через пулер:** `SHOW CLIENTS` показывает клиентов приложения; на PostgreSQL соединений от приложения не больше `default_pool_size` (при transaction pooling).

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **`psql: error: connection failed: Connection refused`** | PgBouncer не запущен, порт закрыт или не задан `listen_addr` (тогда работает только Unix-сокет) | `systemctl status pgbouncer`, `ss -ntlp \| grep 6432`; проверить `listen_addr` |
| **`ERROR: no such user`** | Пользователь отсутствует в `userlist.txt` и недоступен через `auth_query` | Проверить `userlist.txt` или выполнить `auth_query` вручную в PostgreSQL |
| **`ERROR: pgbouncer cannot connect to server`** | Ошибка подключения пулера к БД (IP, порт, `pg_hba.conf`) | Логи PgBouncer; `pg_hba.conf` на стороне PostgreSQL (см. [Установка и безопасность](../../installation_security.md)) |
| **`FATAL: too many open files`** | Исчерпан лимит дескрипторов процесса | Поднять `ulimit -n`/`LimitNOFILE`; проверить формулу `max_client_conn + пулы < ulimit` |
| **`ERROR: cannot access temporary tables during a non-session pooling`** | Temp-таблицы не работают в transaction/statement pooling | `pool_mode = session` для этого пользователя в `[users]` или переписать логику без temp-таблиц |
| **`ERROR: unsupported frontend message`** | Приложение шлёт подготовленные запросы при `max_prepared_statements = 0` | Выставить `max_prepared_statements` ≥ числа уникальных запросов (по умолчанию 200) |
| **`ERROR: permission denied for table pg_authid`** | `auth_user` без прав при прямом `auth_query` | Использовать `SECURITY DEFINER`-функцию (см. выше) |
| **Ошибка аутентификации на managed-сервере** | PgBouncer не может прочитать SCRAM-verifier из `pg_authid` | Сгенерировать одинаковый verifier на обеих сторонах (`psql --echo-hidden ... \password`) |
| **Задержка логина ~15 с после рестарта PostgreSQL** | `server_login_retry` (15 с по умолчанию): в паузе новые клиенты получают ошибку сразу | Плановые работы — через `PAUSE`/`RESUME` (см. `pgbouncer_operations.md`) |
| **`server login failed` в логах с повторами** | Неверный пароль forced user / хост в `[databases]` | Проверить `password=`/`auth_file` и доступность `host:port` |

## Лучшие практики

1. **Обновиться до 1.26.0** — закрыты CVE-2026-19888/6668/6669 (DoS); версии 1.25.1/1.25.2 закрывают CVE-2025-12819 (выполнение SQL при аутентификации через подмену `search_path` в startup-пакете).
2. **`auth_query` с фиксированным `search_path`** — `SECURITY DEFINER` + `SET search_path = pg_catalog` или полностью квалифицированные имена объектов.
3. **Не ставить `default_pool_size = max_connections`** — запас 30% на администрирование.
4. **`track_extra_parameters` вместо session-режима для всех** — отслеживаемые параметры сессии восстанавливаются между транзакциями и в transaction pooling.
5. **Один пулер — один сценарий**: `LISTEN/NOTIFY` и temp-таблицы — отдельный инстанс или `pool_mode = session` в `[users]`.
6. **Не использовать application-side pool и PgBouncer одновременно** для одних и тех же соединений — выберите один уровень.
7. **`disable_pqexec = 1`** для приложений на Extended Query Protocol.
8. **TLS `verify-full`** на серверном leg'е; ключи `0600`, владелец `pgbouncer`.
9. **Конфиги в Git** + `RELOAD` после правок; `SIGHUP` = `RELOAD`.
10. **`max_db_connections`/`max_user_connections`** для изоляции «горячих» баз и пользователей.

## Очистка и откат

- **Откат конфигурации:** `git restore /etc/pgbouncer/pgbouncer.ini && systemctl reload pgbouncer`; настройки, неперезагружаемые в рантайме (`changeable = no` в `SHOW CONFIG`), требуют `systemctl restart pgbouncer`.
- **Полное отключение пулера:** перенаправить приложение на порт PostgreSQL (5432), дождаться завершения транзакций, `systemctl stop pgbouncer` (SIGTERM = `SHUTDOWN WAIT_FOR_CLIENTS`).
- **Отключение динамической аутентификации:** убрать `auth_user`/`auth_query` из `pgbouncer.ini`, вернуть полный `userlist.txt`, `RELOAD`.
- **Удаление пакета:** `sudo apt remove pgbouncer` / `sudo dnf remove pgbouncer`; конфиги и логи удаляются вручную.

## Дополнительная информация

- **[Эксплуатация и мониторинг PgBouncer](./pgbouncer_operations.md)** — админ-консоль, метрики, алерты, failover, rolling restart, бенчмарк, совместимость с ORM.
- **[Pgpool-II](./pgpool.md)** — альтернативный middleware: пул + балансировка read + failover; когда выбирать что — сравнение в файле.
- **[Connection Pooling: общая теория](../../../Networking/Concepts/connection_pooling.md)** — TCP keepalive, conntrack, пулы на уровне nginx/HAProxy.
- **[Масштабирование](../Concepts/scaling.md)** — эвристика sizing'а пула по числу ядер.
- **[Планировщик и кеш планов](../Concepts/planner_internals.md)** — влияние transaction pooling на `Planning Time`.
- **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — архитектура HA-кластера, связка HAProxy + PgBouncer.
- **[Установка и безопасность PostgreSQL](../../installation_security.md)** — `pg_hba.conf`, TLS, аудит.
- **[Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md)** — сохранение реального IP клиента за HAProxy.
- **[Сетевая связность в Kubernetes](./kubernetes_connectivity.md)** — PgBouncer как прокси в кластере.
- Официальная документация: [Configuration](https://www.pgbouncer.org/config.html), [Usage](https://www.pgbouncer.org/usage.html), [Changelog](https://www.pgbouncer.org/changelog.html).
