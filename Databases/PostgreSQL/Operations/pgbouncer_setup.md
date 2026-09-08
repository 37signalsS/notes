# Настройка PgBouncer для PostgreSQL (Сквозной пулинг)

> PgBouncer — это стандарт индустрии для управления пулом соединений в PostgreSQL, позволяющий масштабировать количество клиентских подключений до десятков тысяч при минимальном потреблении ресурсов.

## Определения

- **PgBouncer** — легковесный пулер соединений (connection pooler), работающий на уровне протокола PostgreSQL. Он выступает прокси-сервером между приложением и БД, снижая нагрузку на бэкенд за счет переиспользования открытых сессий.
- **Пул соединений (Connection Pool)** — набор заранее установленных соединений с базой данных, которые распределяются между активными клиентами.
- **Пулинг сессий (Session Pooling)** — соединение закрепляется за клиентом на всё время его сессии. Применяется редко, так как не решает проблему масштабирования при большом количестве "спящих" клиентов.
- **Пулинг транзакций (Transaction Pooling)** — соединение возвращается в пул сразу после завершения транзакции (`COMMIT`/`ROLLBACK`). Самый эффективный и популярный режим для веб-приложений.
- **Пулинг операторов (Statement Pooling)** — соединение возвращается в пул после каждого SQL-запроса. Не поддерживает многооператорные транзакции и используется крайне редко.
- **Шторм соединений (Connection Storm)** — лавинообразный рост попыток подключения к БД, способный привести к исчерпанию ресурсов ОС и отказу СУБД.

## Предпосылки

Для успешного внедрения PgBouncer требуется:

1.  **Версия PostgreSQL:** 12 и выше (для поддержки SCRAM-аутентификации).
2.  **Версия PgBouncer:** 1.21+ (критично для поддержки Prepared Statements в режиме транзакций).
3.  **Сетевая доступность:** Открытые порты (по умолчанию 6432 для пулера и 5432 для БД).
4.  **Права доступа:** Учетная запись с правами на чтение системных таблиц (для динамической аутентификации).

## Основные концепции

### Архитектура PgBouncer

PgBouncer работает как **прозрачный прокси** на уровне протокола PostgreSQL между клиентским приложением и сервером баз данных:

```
Клиент → [PgBouncer Frontend] ⇄ [PgBouncer Backend] → PostgreSQL
```

**Компоненты:**
- **Frontend (Client-facing)**: принимает клиентские подключения на указанном `listen_addr:listen_port` (по умолчанию `0.0.0.0:6432`), выполняет аутентификацию и поддерживает пул клиентских сессий.
- **Backend (Server-facing)**: поддерживает пул физических соединений к PostgreSQL, управляет их жизненным циклом.
- **State Machine**: для каждого клиента отслеживается состояние (`any`, `used`, `archive`, `login`, `close`, `waiting`, `active`, `idle`). При переходе из `active` в `idle` в режиме транзакций соединение немедленно возвращается в пул и становится доступным для другого клиента.
- **DNS/Service Discovery**: PgBouncer кэширует DNS на время жизни соединения. При изменении IP бэкенда (failover) используйте `RELOAD` или перезапуск, иначе старые соединения будут "висеть" на старом адресе.

**Жизненный цикл соединения в transaction pooling:**
1. Клиент инициирует `START TRANSACTION` или DML/DDL-запрос.
2. PgBouncer выделяет свободное серверное соединение из пула (`default_pool_size`).
3. Запрос выполняется, результат возвращается клиенту.
4. При `COMMIT`/`ROLLBACK` серверное соединение немедленно освобождается и возвращается в пул.
5. Клиентское соединение остается открытым и готовит следующий запрос, но без привязки к серверной сессии.

**Важно:** В отличие от application-side пулов (HikariCP, psycopg2.pool), PgBouncer централизован и не зависит от языка/фреймворка приложения.

### Зачем нужен PgBouncer?
1.  **Экономия RAM**: PostgreSQL создает отдельный процесс на каждое соединение (от 10 MB RAM). PgBouncer позволяет обслуживать 10 000 клиентов через 100-200 реальных серверных процессов.
2.  **Снижение Latency**: Исключает затраты времени на fork процесса PostgreSQL при каждом новом подключении клиента.
3.  **Управление очередями**: Если пул переполнен, PgBouncer ставит новые запросы в очередь вместо того, чтобы "убить" БД новыми подключениями.
4.  **Безопасный Failover**: Позволяет переключать бэкенд (например, с Primary на Replica или на новый мастер после Switchover) незаметно для приложения.

### Режимы работы (Pool Modes)

| Характеристика | Session | Transaction | Statement |
| :--- | :--- | :--- | :--- |
| **Удержание соединения** | Весь период сессии | Только на время транзакции | На время одного запроса |
| **Поддержка транзакций** | Полная | Полная | Нет |
| **Временные таблицы** | Да | Нет | Нет |
| **Prepared Statements** | Да | **Да (с версии 1.21+)** | Нет |
| **LISTEN/NOTIFY** | Да | Нет | Нет |
| **Когда использовать** | Session-приложения (pgAdmin, миграции), legacy-код с temp-таблицами | Веб-приложения, API, ORM (Hibernate, Prisma, Django) | Только read-only аналитика без транзакций; практически не используется |

> **Важно:** Начиная с версии 1.21, PgBouncer поддерживает протокольные Prepared Statements в режиме транзакций через параметр `max_prepared_statements`.

### Планирование ёмкости пула (Capacity Planning)

Размер пула задаётся профилем нагрузки на БД, а не числом клиентов или воркеров приложения:

- `default_pool_size` — число серверных соединений на пару (база, пользователь). Для коротких OLTP-транзакций обычно 20–50.
- `max_client_conn` — лимит **клиентских сессий** (не соединений к БД). Ограничен `ulimit -n` процесса: сумма `max_client_conn + default_pool_size × число_баз` должна быть меньше доступных дескрипторов.
- Правило: суммарный `default_pool_size` всех пулов **меньше** `max_connections` PostgreSQL (оставляем запас на админов и миграции). Иначе PgBouncer упирается в лимит СУБД.
- Транзакционный пулинг умножает ёмкость: 10 000 клиентов при пуле 50 → ~50 реальных соединений к БД.

#### Формулы и примеры

**Минимальный `default_pool_size` для OLTP:**
```
default_pool_size ≥ (RPS × avg_latency_sec) / parallelism_factor
```
где `parallelism_factor` — эффективное число параллельных запросов, которое может обработать один PostgreSQL-процесс. Обычно 1.0–2.0.

Пример: 2000 RPS, средняя латентность транзакции 15 мс (0.015 с):
```
(2000 × 0.015) / 1.5 ≈ 20 → default_pool_size = 25–30
```

**Максимальный `default_pool_size`:**
```
sum(default_pool_size) ≤ max_connections × 0.7
```
Запас 30% оставляется на суперпользователей, миграции, логическую репликацию и административные сессии.

**`max_client_conn` под нагрузку:**
```
max_client_conn ≤ ulimit -n − (default_pool_size × databases_count) − 64
```
Оставляем запас на файлы логов, stdin/stdout и служебные дескрипторы. Для production рекомендуем `ulimit -n = 65536`.

**`reserve_pool_size` при всплесках:**
```
reserve_pool_size = ceil(default_pool_size × 0.2)
```
Резервный пул используется только когда обычный пул исчерпан и клиенты ждут дольше `reserve_pool_timeout` (по умолчанию 5 сек).

#### Типичные ошибки capacity planning
1. **`default_pool_size = max_connections`**: пулер полностью блокирует СУБД, не оставляя места для администрирования.
2. **Игнорирование пиков**: если RPS растет в 3 раза утром, `default_pool_size` должен покрывать пик, а не среднее.
3. **Слишком маленький `max_client_conn`**: при 10k+ воркерах приложения часто сталкиваются с `FATAL: too many open files`, хотя пул в БД не переполнен.
4. **Одна база — все пользователи**: разделяйте пользователей по базам или используйте `auth_db` для изоляции нагрузок.

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

### Конфигурация (`pgbouncer.ini`)

Типовой файл конфигурации `/etc/pgbouncer/pgbouncer.ini`:

```ini
[databases]
# Шаблон: dbname = host=... port=... auth_user=...
# * = host=127.0.0.1 port=5432
myapp_db = host=10.0.0.10 port=5432 dbname=myapp_prod auth_user=pgb_auth_user

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
unix_socket_dir = /var/run/postgresql
user = pgbouncer

# Логирование
log_connections = 0
log_disconnections = 0
log_stats = 1
stats_period = 60

# Аутентификация
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
# Динамическая проверка паролей через БД (рекомендуется)
auth_user = pgbouncer
auth_query = SELECT usename, passwd FROM pgbouncer.get_auth($1)

# Настройки пула
pool_mode = transaction
default_pool_size = 50
reserve_pool_size = 10
max_client_conn = 10000

# Поддержка Prepared Statements (для PgBouncer 1.21+)
max_prepared_statements = 100

# Администрирование
admin_users = postgres, pgb_admin
stats_users = pgb_monitor
```

### Настройка динамической аутентификации (`auth_query`)

Этот метод позволяет PgBouncer проверять пароли пользователей напрямую в PostgreSQL, избавляя от необходимости вручную синхронизировать `userlist.txt`.

1. **В PostgreSQL (под суперпользователем):**
```sql
CREATE USER pgbouncer WITH PASSWORD 'pgbouncer_secret_password';
CREATE SCHEMA pgbouncer;

-- Функция для получения хеша пароля
CREATE OR REPLACE FUNCTION pgbouncer.get_auth(p_usename text)
RETURNS TABLE(usename text, passwd text) AS $$
    SELECT usename, passwd FROM pg_catalog.pg_shadow WHERE usename=$1;
$$ LANGUAGE sql SECURITY DEFINER;

-- Ограничение прав
REVOKE ALL ON FUNCTION pgbouncer.get_auth(text) FROM public;
GRANT USAGE ON SCHEMA pgbouncer TO pgbouncer;
GRANT EXECUTE ON FUNCTION pgbouncer.get_auth(text) TO pgbouncer;
```

2. **В `userlist.txt` добавьте только самого пользователя `pgbouncer`:**
```text
"pgbouncer" "SCRAM-SHA-256$4096:..."
```

### Управление через консоль

PgBouncer имеет виртуальную базу данных `pgbouncer`, к которой можно подключиться для управления.

```bash
psql -h localhost -p 6432 -U postgres pgbouncer
```

**Основные команды:**
- `SHOW STATS` — статистика запросов, транзакций и времени выполнения.
- `SHOW POOLS` — состояние очередей и активных соединений.
- `SHOW CLIENTS` / `SHOW SERVERS` — детальный список подключений.
- `RELOAD` — мягкая перезагрузка конфигурации.
- `PAUSE` / `RESUME` — приостановка/возобновление работы (транзакции ставятся на паузу, не обрываясь).

### Мониторинг (Prometheus и SQL)

Для мониторинга рекомендуется использовать `pgbouncer_exporter`. 

**Ключевые метрики для алертинга:**
1. **`pgbouncer_pools_client_waiting_connections`** — если > 0, клиенты ждут в очереди. Это критично.
2. **`pgbouncer_pools_client_maxwait_seconds`** — время ожидания самого старого клиента в очереди.
3. **`pgbouncer_pools_server_active_connections`** — количество занятых серверных соединений.
4. **`pgbouncer_up`** — доступность самого сервиса.

#### Консольные запросы для диагностики

```sql
-- Состояние всех пулов
SHOW POOLS;

-- Активные клиенты и серверные соединения
SHOW CLIENTS;
SHOW SERVERS;

-- Статистика по базам
SHOW STATS;

-- Текущие лимиты и usage
SHOW CONFIG;
SHOW LIMITS;
```

Пример анализа `SHOW POOLS`:
```
 database  | cl_active | cl_waiting | sv_active | sv_idle | sv_used | sv_tested | sv_login | maxwait
-----------+-----------+------------+-----------+---------+---------+-----------+----------+--------
 myapp_db  |      120  |          0 |        50 |       0 |       0 |         0 |        0 |   0.00
```
- `cl_active` — клиенты,currently выполняющие запрос.
- `cl_waiting` — клиенты в очереди. Должно быть `0` в steady state.
- `sv_active` — занятые серверные соединения. Если достигает `default_pool_size` — пул переполнен.
- `maxwait` — время ожидания самого старого клиента в секундах. Алерт если > 2 сек.

#### Дашборды и алерты (Prometheus / Grafana)

**Панель "PgBouncer Overview":**
- `sum(pgbouncer_pools_client_waiting_connections)` — глобальная очередь.
- `sum(pgbouncer_pools_server_active_connections) / sum(pgbouncer_databases_default_pool_size) * 100` — утилизация пула в %.
- `histogram_quantile(0.99, sum(rate(pgbouncer_query_time_seconds_bucket[5m])) by (le))` — P99 латентности запросов.

**Пороги алертов:**
| Условие | Тяжесть | Описание |
| :--- | :--- | :--- |
| `pgbouncer_pools_client_waiting_connections > 0` | Critical | Клиенты ждут свободного соединения > 0 сек. |
| `pgbouncer_pools_client_maxwait_seconds > 2` | Warning | Самый старый клиент в очереди ждет > 2 сек. |
| `pgbouncer_pools_server_active_connections == default_pool_size` | Warning | Пул исчерпан, новые запросы станут в очередь. |
| `rate(pgbouncer_total_query_time[5m]) / rate(pgbouncer_total_queries[5m]) > 0.5` | Warning | Средняя латентность запроса > 500 мс. |
| `pgbouncer_up == 0` | Critical | PgBouncer недоступен. |

#### Корреляция с PostgreSQL

Сопоставляйте метрики PgBouncer с `pg_stat_activity`:
```sql
SELECT state, count(*) 
FROM pg_stat_activity 
WHERE datname = 'myapp_db' 
GROUP BY state;
```
Если `cl_active` в PgBouncer высокий, а `active` в `pg_stat_activity` низкий — проблема в длительных транзакциях на стороне приложения.

### Переключение бэкенда (Failover) без обрыва клиентов

При смене Primary (Patroni или вручную) не разрывайте клиентов: поставьте PgBouncer на паузу (активные транзакции завершатся, новые встанут в очередь), укажите новый адрес и возобновите:

```bash
psql -h localhost -p 6432 -U postgres pgbouncer -c "PAUSE myapp_db"
# обновить [databases] -> host=новый_primary в /etc/pgbouncer/pgbouncer.ini
psql -h localhost -p 6432 -U postgres pgbouncer -c "RELOAD"
psql -h localhost -p 6432 -U postgres pgbouncer -c "RESUME myapp_db"
```

**Валидация:** `SHOW POOLS` показывает `paused=0` и рост `sv_active` на новом бэкенде; в логах отсутствуют `closing because:`.

## Эксплуатация и надёжность

### Production Hardening

#### systemd unit и процесс

На production-серверах PgBouncer должен работать как managed service с авторестартом:

```ini
# /etc/systemd/system/pgbouncer.service
[Unit]
Description=PgBouncer PostgreSQL Connection Pooler
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=pgbouncer
Group=pgbouncer
ExecStart=/usr/bin/pgbouncer -d /etc/pgbouncer/pgbouncer.ini
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

#### ulimit и системные параметры

PgBouncer — это event-driven single-threaded процесс. Его производительность зависит от числа дескрипторов и размера backlog:

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

Применение:
```bash
sudo sysctl --system
```

#### Логирование и ротация

PgBouncer пишет в stdout/stderr. В production используйте journald или external syslog:

```ini
# pgbouncer.ini
log_connections = 1
log_disconnections = 1
log_stats = 1
stats_period = 60
logfile = /var/log/pgbouncer/pgbouncer.log
```

```bash
sudo journalctl -u pgbouncer -f
```

Ротация логов через logrotate:
```bash
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

#### Zero-downtime обновление PgBouncer

PgBouncer поддерживает **фоновый перезапуск** через SIGHUP или graceful restart:

```bash
# Вариант 1: HUP (если конфиг изменился)
sudo kill -HUP $(pgrep pgbouncer)

# Вариант 2: через консоль управления
psql -h 127.0.0.1 -p 6432 -U postgres pgbouncer -c "RELOAD"

# Вариант 3: обновление бинарника без обрыва клиентов
sudo systemctl reload pgbouncer
```

Для обновления самого бинарника на rolling infrastructure используйте **blue-green switch**:
1. Запустите второй экземпляр PgBouncer на порту `6433` с новым бинарником.
2. Переключите алерт/сервис/конфиг приложения на порт `6433`.
3. Остановите старый инстанс на `6432`.

#### Бэкап конфигурации

Храните `pgbouncer.ini`, `userlist.txt` и `hba_file` в Git. При аварии восстановление занимает минуты:

```bash
# Проверка целостности конфига перед применением
pgbouncer -d /etc/pgbouncer/pgbouncer.ini
# → "LOG configuration files parsed"
```

### Безопасность (TLS/SSL)

Для защиты трафика между клиентом и PgBouncer:

```ini
client_tls_sslmode = require
client_tls_key_file = /etc/pgbouncer/server.key
client_tls_cert_file = /etc/pgbouncer/server.crt
```

Для защиты трафика между PgBouncer и PostgreSQL (рекомендуется в production):

```ini
server_tls_sslmode = verify-full
server_tls_ca_file = /etc/pgbouncer/ca.crt
server_tls_key_file = /etc/pgbouncer/client.key
server_tls_cert_file = /etc/pgbouncer/client.crt
```

#### Управление доступом через hba_file

PgBouncer поддерживает собственный файл управления доступом, аналогичный `pg_hba.conf`:

```ini
# /etc/pgbouncer/pgbouncer.ini
hba_file = /etc/pgbouncer/hba.conf
```

Пример `hba.conf`:
```ini
# TYPE  DATABASE  USER  ADDRESS  METHOD
host    all       all   10.0.0.0/8  scram-sha-256
host    all       all   172.16.0.0/12  md5
host    all       all   0.0.0.0/0  reject
local   all       all                trust
```

#### Аудит и compliance

Включите расширенное логирование для compliance:

```ini
log_connections = 1
log_disconnections = 1
log_pooler_errors = 1
```

Ключевые события для аудита:
- Успешные и неуспешные попытки аутентификации.
- Смена `PAUSE`/`RESUME` (кто и когда отключал пул).
- Переключение бэкенда (`RELOAD` после смены `host=`).
- Достижение лимитов (`max_client_conn`, `default_pool_size`).

#### Минимальные права пользователя

Пользователь ОС `pgbouncer` не должен иметь:
- Доступа к оболочке (`/usr/sbin/nologin` в `/etc/passwd`).
- Прав на запись в домашние директории других пользователей.
- Доступа к файлам конфигурации PostgreSQL (`/etc/postgresql`, `/var/lib/postgresql`).

Пользователь БД `pgbouncer` (для `auth_query`) должен иметь только:
- `USAGE` на схеме `pgbouncer`.
- `EXECUTE` на функции `get_auth`.
- Никаких других прав, особенно `SUPERUSER` или `CREATEDB`.

### Развертывание в Kubernetes
В K8s PgBouncer часто используется как **Sidecar-контейнер**:
- Приложение подключается к `localhost:6432`.
- Снижается нагрузка на межсервисную сеть.
- Упрощается аутентификация.

Альтернатива — **PgBouncer как отдельный сервис** (Deployment + Service) для агрегации соединений от множества микросервисов.

### Ограничения и особенности
- **Prepared Statements**: В режиме транзакций работают только на протокольном уровне (не через SQL `PREPARE`).
- **Таймауты**: Обязательно настраивайте `server_idle_timeout` (например, 600s), чтобы не держать лишние idle-соединения в БД.
- **FDW**: При использовании Foreign Data Wrappers через PgBouncer учитывайте, что каждое внешнее обращение может занимать соединение дольше обычного.

## Валидация и проверка

После настройки PgBouncer выполните следующие шаги для подтверждения корректности работы:

1.  **Проверка статуса сервиса:**
    ```bash
    systemctl status pgbouncer
    ```
2.  **Тестовое подключение через пулер:**
    ```bash
    psql -h 127.0.0.1 -p 6432 -U myuser -d myapp_db -c "SELECT 1;"
    ```
3.  **Проверка использования пула:**
    Подключитесь к виртуальной базе `pgbouncer` и выполните:
    ```sql
    SHOW POOLS;
    ```
    *Ожидаемый результат:* наличие вашей базы данных в списке с активными серверными соединениями (`sv_active > 0`).
4.  **Проверка Prepared Statements (для 1.21+):**
    Убедитесь, что приложение успешно выполняет подготовленные запросы, а в логах PgBouncer отсутствуют ошибки типа `unsupported frontend message`.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **`psql: error: connection failed: Connection refused`** | PgBouncer не запущен или порт 6432 закрыт. | Проверить статус через `systemctl status pgbouncer` и `ss -ntlp | grep 6432`. |
| **`ERROR: no such user`** | Пользователь отсутствует в `userlist.txt` или в БД (при `auth_query`). | Проверить `userlist.txt` или результат `auth_query` вручную в PostgreSQL. |
| **`ERROR: pgbouncer cannot connect to server`** | Ошибка подключения от пулера к БД (IP, порт, HBA). | Проверить логи PgBouncer и файл `pg_hba.conf` на стороне PostgreSQL. |
| **`ERROR: prepared statement "..." already exists`** | Конфликт имен в режиме транзакций (старые версии). | Обновитесь до 1.21+ или отключите Prepared Statements в приложении. |
| **`sv_active` достигает `default_pool_size`** | Пул переполнен, запросы встают в очередь. | Увеличьте `default_pool_size` или проанализируйте длительные транзакции в БД. |
| **`ERROR: closing because: pgbouncer: connection pool full`** | Исчерпан лимит `max_client_conn`. | Увеличьте `max_client_conn` в `pgbouncer.ini` (зависит от `ulimit` процесса). |
| **`client_waiting` постоянно > 0** | Клиенты ждут свободного серверного соединения. | Проверьте долгие транзакции (`pg_stat_activity`), увеличьте `default_pool_size` или добавьте реплики для чтения. |
| **`FATAL: too many open files`** | Исчерпан лимит дескрипторов у процесса pgbouncer. | Поднимите `ulimit -n` для сервиса и убедитесь, что `max_client_conn + пулы < ulimit`. |
| **`ERROR: cannot access temporary tables during a non-session pooling`** | Temp-таблицы не работают в режиме transaction. | Переведите этого пользователя в `session` пул или перепишите логику без temp-таблиц. |

## Совместимость и известные ограничения

### ORM и драйверы

PgBouncer совместим с большинством PostgreSQL-драйверов и ORM, но есть нюансы:

- **Hibernate / JPA**: Используйте `hibernate.connection.provider_disables_autocommit=true` при transaction pooling, чтобы избежать лишних round-trip.
- **Django**: `CONN_MAX_AGE = 0` (по умолчанию) не конфликтует с PgBouncer; при `> 0` убедитесь, что долгие соединения не удерживают серверные сессии.
- **Prisma**: Поддерживает connection URL с портом 6432. Включите `preparedStatements: false` если используете PgBouncer < 1.21.
- **SQLAlchemy**: `pool_pre_ping=True` полезен, но создает дополнительные запросы `SELECT 1`. Лучше полагаться на `server_check_query` в PgBouncer.
- **psycopg2 / psycopg3**: Application-side пул (`ThreadedConnectionPool`) избыточен при PgBouncer. Используйте либо пул в приложении, либо PgBouncer, но не оба одновременно.

### Специфические функции PostgreSQL

| Функция | Session | Transaction | Statement |
| :--- | :--- | :--- | :--- |
| **Temporary tables** | Да | Нет | Нет |
| **LISTEN / NOTIFY** | Да | Нет | Нет |
| ** advisory locks (`pg_advisory_lock`)** | Да | Да (в рамках транзакции) | Нет |
| **Large Objects (lo_*)** | Да | Да | Нет |
| **COPY ... FROM STDIN** | Да | Да | Да |
| **Background workers** | Да | Да | Нет |
| **SET/RESET параметры сессии** | Да | Нет | Нет |

**Рекомендации:**
- Для `LISTEN/NOTIFY` используйте `pool_mode = session` только для этого пользователя или выделите отдельный инстанс PgBouncer.
- Advisory locks в transaction pooling работают, но блокировка сбрасывается при завершении транзакции.
- `SET` параметры (например, `search_path`, `work_mem`) в transaction pooling применяются только к одному запросу и не сохраняются между транзакциями.

### Подготовленные выражения (Prepared Statements)

Начиная с PgBouncer 1.21, поддерживаются протокольные Prepared Statements в режиме транзакций. Однако:

- Они кэшируются на стороне PgBouncer, а не PostgreSQL.
- `max_prepared_statements` ограничивает количество уникальных запросов на клиентскую сессию. При переполнении старые выражения вытесняются.
- При использовании `auth_user` и динамической аутентификации убедитесь, что функция `get_auth` не создает prepared statements сама (используйте `SECURITY DEFINER` и простой SQL).

## Оптимизация производительности

### Профили нагрузки

| Профиль | Характеристики | `default_pool_size` | `pool_mode` | Особенности |
| :--- | :--- | :--- | :--- | :--- |
| **OLTP (Web, API)** | Короткие транзакции, <50 мс | 20–50 | transaction | Prepared statements обязательны |
| **OLAP / Аналитика** | Долгие запросы, >1 сек | 5–10 | session | Один клиент = одно соединение |
| **Mixture (HYBRID)** | Смесь коротких и длинных | 30–60 | transaction + per-user | Длинные запросы выносятся в отдельный пул |
| **Bulk Load / ETL** | Массовая вставка, COPY | 10–20 | session | Большие транзакции, низкая параллельность |

### Таймауты и защита от зависших транзакций

```ini
# pgbouncer.ini
server_idle_timeout = 600
server_lifetime = 3600
server_connect_timeout = 15
query_timeout = 0
idle_in_transaction_session_timeout = 0
```

- `server_idle_timeout`: закрывает idle-соединения к PostgreSQL. Экономит ресурсы БД.
- `server_lifetime`: принудительно реконнектит серверные соединения для обхода network-level таймаутов (NAT, firewall).
- `server_connect_timeout`: защита от зависания при подключении к недоступному бэкенду.
- `query_timeout`: прерывает запросы, выполняющиеся дольше N секунд. Используйте осторожно — может сломать миграции.

### Бенчмаркинг PgBouncer

```bash
# Установка pgbench для тестирования
sudo apt install postgresql-contrib -y

# Создание тестовой базы
pgbench -i -s 50 myapp_db

# Тест без PgBouncer (прямое подключение)
pgbench -c 100 -j 4 -T 30 -P 1 myapp_db

# Тест через PgBouncer
pgbench -h 127.0.0.1 -p 6432 -c 100 -j 4 -T 30 -P 1 myapp_db
```

Сравнивайте TPS и латентность. PgBouncer на transaction pooling должен показывать **стабильную или более высокую** производительность при `c > 50` за счет переиспользования соединений.

## Отказоустойчивость самого PgBouncer

### Точка отказа (SPOF)

PgBouncer сам по себе является SPOF. Production-архитектура должна учитывать его отказ:

**Варианты устранения SPOF:**
1. **HAProxy перед PgBouncer**: несколько инстансов PgBouncer за балансировщиком. При падении одного HAProxy переключает трафик.
2. **DNS Round-Robin**: приложение подключается к `pgbouncer-01.db.internal, pgbouncer-02.db.internal`. Не рекомендуется из-за кэширования DNS и задержки переключения.
3. **Service Mesh / Sidecar**: в Kubernetes PgBouncer как sidecar автоматически перезапускается при падении пода.

### Поведение при падении PgBouncer

| Сценарий | Влияние на клиент | Восстановление |
| :--- | :--- | :--- |
| **Убийство процесса** | Все клиенты получают `Connection refused` | systemctl restart pgbouncer; приложение retry |
| **Падение ОС / ноды** | Аналогично убийству + потеря всех idle-соединений | failover ноды; DNS/Service переключение |
| **Блокировка backlog** | Новые подключения отклоняются с `ECONNREFUSED` | Увеличить `somaxconn`, проверить `client_waiting` |
| **Утечка памяти** | OOM Killer убивает процесс | Настроить `MemoryMax=512M`, добавить swap |

### Graceful Shutdown

При остановке PgBouncer (`systemctl stop`) активные транзакции завершаются корректно, но новые запросы отклоняются. Для graceful shutdown:

```bash
# 1. Поставить все базы на паузу
psql -h localhost -p 6432 -U postgres pgbouncer -c "PAUSE"

# 2. Дождаться завершения активных транзакций (timeout 30 сек)
sleep 30

# 3. Остановить сервис
sudo systemctl stop pgbouncer
```

## Дополнительная информация

### Рекомендации по эксплуатации
1. **Версия 1.21+**: Переход на версии 1.21 и выше обязателен для использования Prepared Statements в режиме транзакций, что значительно повышает производительность ORM (Hibernate, Prisma, Django).
2. **HBA**: Используйте `hba_file` в PgBouncer для гибкого управления доступом на уровне IP/сетей, аналогично `pg_hba.conf`.
3. **Odyssey**: Если вам нужна многопоточность на стороне пулера (одно ядро PgBouncer перестало справляться), рассмотрите **Odyssey** (Yandex) или **PgCat**.
4. **Systemd**: Всегда используйте managed service unit с `Restart=on-failure` и `LimitNOFILE=65536`.
5. **TLS**: Включайте `server_tls_sslmode = verify-full` для защиты трафика между PgBouncer и PostgreSQL.
6. **Capacity Planning**: Рассчитывайте `default_pool_size` по формуле `(RPS × avg_latency) / parallelism`, а не по числу воркеров приложения.
7. **Monitoring**: Алертьте не только на `client_waiting`, но и на `client_maxwait_seconds > 2` и утилизацию пула > 80%.

### См. также
- **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — архитектура HA-кластера.
- **[Оптимизация производительности](./performance_tuning.md)** — общие рекомендации по тюнингу СУБД.
- **[Сетевая связность в Kubernetes](./kubernetes_connectivity.md)** — детали использования PgBouncer как зонального прокси.
- **[Connection Pooling: общая теория](../../../Networking/Concepts/connection_pooling.md)** — TCP keepalive, conntrack, пулы на уровне nginx/HAProxy.
- **[Мониторинг PostgreSQL в Zabbix](../../../Zabbix/zabbix_postgresql_monitoring.md)** — особенности настройки мониторинга через пулер соединений.
- **[Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md)** — использование PgBouncer с HAProxy и сохранением реального IP клиента.
