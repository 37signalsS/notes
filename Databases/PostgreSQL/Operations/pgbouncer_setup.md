# Настройка PgBouncer для PostgreSQL

> PgBouncer — это стандарт индустрии для управления пулом соединений в PostgreSQL, позволяющий масштабировать количество клиентских подключений до десятков тысяч при минимальном потреблении ресурсов.

## Определения

- **PgBouncer** — легковесный пулер соединений (connection pooler), работающий на уровне протокола PostgreSQL. Он выступает прокси-сервером между приложением и БД, снижая нагрузку на бэкенд за счет переиспользования открытых сессий.
- **Connection Pool (Пул соединений)** — набор заранее установленных соединений с базой данных, которые распределяются между активными клиентами.
- **Session Pooling (Пулинг сессий)** — соединение закрепляется за клиентом на всё время его сессии. Применяется редко, так как не решает проблему масштабирования при большом количестве "спящих" клиентов.
- **Transaction Pooling (Пулинг транзакций)** — соединение возвращается в пул сразу после завершения транзакции (`COMMIT`/`ROLLBACK`). Самый эффективный и популярный режим для веб-приложений.
- **Statement Pooling (Пулинг операторов)** — соединение возвращается в пул после каждого SQL-запроса. Не поддерживает многооператорные транзакции и используется крайне редко.
- **Connection Storm** — лавинообразный рост попыток подключения к БД, способный привести к исчерпанию ресурсов ОС и отказу СУБД.

## Базовые концепции

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

> **Важно:** Начиная с версии 1.21, PgBouncer поддерживает протокольные Prepared Statements в режиме транзакций через параметр `max_prepared_statements`.

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

### Мониторинг (Prometheus)

Для мониторинга рекомендуется использовать `pgbouncer_exporter`. 

**Ключевые метрики для алертинга:**
1. **`pgbouncer_pools_client_waiting_connections`** — если > 0, клиенты ждут в очереди. Это критично.
2. **`pgbouncer_pools_client_maxwait_seconds`** — время ожидания самого старого клиента в очереди.
3. **`pgbouncer_pools_server_active_connections`** — количество занятых серверных соединений.
4. **`pgbouncer_up`** — доступность самого сервиса.

## Эксплуатация и надежность

### Безопасность (TLS/SSL)
Для защиты трафика между клиентом и PgBouncer:

```ini
client_tls_sslmode = require
client_tls_key_file = /etc/pgbouncer/server.key
client_tls_cert_file = /etc/pgbouncer/server.crt
```

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

## Дополнительная информация

### Рекомендации 2026 года
1. **Версия 1.21+**: Переход на версии 1.21 и выше обязателен для использования Prepared Statements в режиме транзакций, что значительно повышает производительность ORM (Hibernate, Prisma, Django).
2. **HBA**: Используйте `hba_file` в PgBouncer для гибкого управления доступом на уровне IP/сетей, аналогично `pg_hba.conf`.
3. **Odyssey**: Если вам нужна многопоточность на стороне пулера (одно ядро PgBouncer перестало справляться), рассмотрите **Odyssey** (Yandex) или **PgCat**.

### См. также
- **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — архитектура HA-кластера.
- **[Оптимизация производительности](./performance_tuning.md)** — общие рекомендации по тюнингу СУБД.
- **[Сетевая связность в Kubernetes](./kubernetes_connectivity.md)** — детали использования PgBouncer как зонального прокси.
