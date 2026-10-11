# ProxySQL для MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS, ProxySQL 2.5 / 3.0.x

## Определения

*   **ProxySQL** — высокопроизводительный SQL-прокси (L7) для MySQL/MariaDB. Выполняет маршрутизацию запросов (read/write split), балансировку нагрузки, connection pooling, кэширование запросов, firewall и шардирование. Работает как промежуточный слой между приложением и MariaDB.
*   **Read/Write Split** — маршрутизация: запросы `SELECT` — на реплики, `INSERT/UPDATE/DELETE` — на source. Реализуется через правила (`mysql_query_rules`) и флаг `read_only` на репликах.
*   **Connection Pooling** — пул соединений ProxySQL к backend-серверам. Приложение подключается к ProxySQL, который переиспользует固定连接 к MariaDB. Снижает нагрузку на Thread Pool и `Threads_created`.
*   **Query Rules (`mysql_query_rules`)** — правила маршрутизации и модификации запросов по регулярным выражениям. Позволяют направлять запросы на конкретные хостгруппы, кэшировать, переписывать.
*   **Hostgroup** — логическая группа backend-серверов (например, `0` — writers, `1` — readers). Запросы маршрутизируются на хостгруппу.
*   **Query Cache** — кэш результатов SELECT в ProxySQL (отличается от удалённого MySQL Query Cache — работает на уровне прокси).
*   **`mysql_servers`** — таблица конфигурации backend-серверов (хост, порт, хостгруппа, вес).
*   **`mysql_users`** — таблица пользователей ProxySQL (логин, пароль, default_hostgroup).

## Требования и предпосылки

### Аппаратное обеспечение и ОС

| Требование | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| **CPU** | 2 cores | 4+ cores (dedicated) |
| **RAM** | 2 ГБ | 4–8 ГБ (зависит от количества соединений) |
| **Диск** | 10 ГБ | SSD для `datadir` и логов (50+ ГБ) |
| **OS** | CentOS/RHEL 8+, Ubuntu 20.04+ | Debian 12, RHEL 9 |

**OS tuning:**
*   Отключите THP: `echo never > /sys/kernel/mm/transparent_hugepage/enabled`
*   `net.core.somaxconn ≥ 65535`
*   `fs.file-max ≥ 1000000` (ulimit -n ≥ 100000 для пользователя `proxysql`)
*   CPU isolation: `isolcpus` в GRUB для dedicated cores

### Порты и сеть

*   **6032** — admin interface (SQLite over TCP)
*   **6033** — MySQL client interface
*   **6031** — REST API (опционально, `admin-restapi_enabled`)
*   Admin interface должен быть доступен **только** из доверенной сети или через VPN/SSH tunnel.

### Безопасность

1.  **Измените пароль администратора** immediately после установки:
    ```sql
    UPDATE global_variables SET variable_value='admin:YourStrongPass123!' WHERE variable_name='admin-admin_credentials';
    LOAD ADMIN VARIABLES TO RUNTIME;
    SAVE ADMIN VARIABLES TO DISK;
    ```
2.  **Ограничьте admin interface** — привяжите к localhost или internal IP:
    ```sql
    UPDATE global_variables SET variable_value='127.0.0.1:6032' WHERE variable_name='admin-mysql_ifaces';
    ```
3.  **TLS для клиентских подключений** (`mysql-have_ssl=true` по умолчанию; сертификаты для ProxySQL→backend через `mysql-ssl_p2s_ca`, `mysql-ssl_p2s_cert`, `mysql-ssl_p2s_key`). Детали — в [ProxySQL: Security](../MySQL/ProxySQL/proxysql_security.md).
4.  **Firewall:** разрешите 6033 только из сети приложений, 6032 — только из Bastion/VPN.

### Файлы конфигурации и данные

*   **Config file:** `/etc/proxysql.cnf` (читается только при первом запуске; последующее управление через admin interface)
*   **Data directory:** `/var/lib/proxysql/` (SQLite database: `proxysql.db`)
*   **Log files:** `/var/log/proxysql/`

## Базовые концепции

### Архитектура

```
Приложение
    ↓ (3306)
ProxySQL (admin: 6032, MySQL: 6033)
    ↓
┌──────────────┬──────────────┐
│ Hostgroup 0  │ Hostgroup 1  │
│ (writers)    │ (readers)    │
│  source      │  replica-1   │
│              │  replica-2   │
└──────────────┴──────────────┘
```

*   **Admin interface** (порт 6032): конфигурация через SQL (`mysql_servers`, `mysql_users`, `mysql_query_rules`).
*   **MySQL interface** (порт 6033): клиентские подключения.

### Отличие от MaxScale

| Характеристика | ProxySQL | MaxScale |
| :--- | :--- | :--- |
| **Лицензия** | GPLv3 (open source) | BSL → proprietary (25.01+) |
| **Маршрутизация** | L7, query rules, regex | L7, модули (readwritesplit) |
| **Connection pooling** | Да, встроенный | Да |
| **Query cache** | Да | Нет |
| **Firewall** | Да | Да (SQL firewall) |
| **Failover** | Через скрипты/мониторинг | Встроенный (mariadbmon) |
| **Сложность** | Средняя | Средняя |

**Выбор:** ProxySQL — для read/write split, pooling, query cache, firewall. MaxScale — для автоматического failover и Galera-мониторинга. Подробнее: **[MaxScale](MaxScale/maxscale_overview.md)**.

### Мониторинг backend

ProxySQL периодически проверяет backend-серверы:
*   `mysql-monitor_username` / `mysql-monitor_password` — пользователь для проверок.
*   Проверки: `ping`, `read_only` (для определения readers/writers), replication lag.
*   Сервер автоматически выводится из rotation при недоступности (`OFFLINE_HARD`).

**Автоматический read/write split через `mysql_replication_hostgroups`:**

```sql
-- Пары hostgroups: ProxySQL перемещает серверы между writer и reader по read_only
INSERT INTO mysql_replication_hostgroups (writer_hostgroup, reader_hostgroup, check_type)
VALUES
  (0, 1, 'super_read_only');  -- MariaDB 10.4+ использует super_read_only

LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

| `check_type` | Условие «сервер является writer» |
| :--- | :--- |
| `super_read_only` | `super_read_only = OFF` |
| `innodb_read_only` | `innodb_read_only = OFF` |
| `read_only\|innodb_read_only` | хотя бы одна переменная `OFF` |
| `read_only&innodb_read_only` | обе переменные `OFF` |

> **Важно для ProxySQL 3.0.x:** одиночное значение `read_only` (часто встречается в примерах для 2.x) **не входит в список допустимых** в 3.0.11+ — будет отклонено CHECK-ограничением. Для MariaDB 10.4+ используйте `super_read_only`. Подробнее — в [ProxySQL: Failover](../MySQL/ProxySQL/proxysql_failover.md).

**Ограничение:** пользователь монитора (`mysql-monitor_username`) **не может** быть указан в таблице `mysql_users` — это разные роли.

**Пороги лага и latency** (per-server в `mysql_servers`):

| Колонка | Единица | Смысл |
| :--- | :--- | :--- |
| `max_replication_lag` | Секунды | server excluded from writer-group если лаг > порог |
| `max_latency_ms` | МС | пинг-задержка |
| `max_connections` | соединения | лимит пула к серверу |

```sql
-- Исключать реплику из writers при лаге > 30с
UPDATE mysql_servers SET max_replication_lag = 30
WHERE hostgroup_id = 1 AND hostname = 'replica-1.example.com';
LOAD MYSQL SERVERS TO RUNTIME;
```

## Практические сценарии

### 1. Установка

```bash
# Debian/Ubuntu (официальный репозиторий ProxySQL)
sudo apt-get install proxysql

# RHEL/CentOS
sudo dnf install proxysql

# Запуск
sudo systemctl enable --now proxysql

# Проверка
sudo systemctl status proxysql
# Admin interface: 127.0.0.1:6032 (admin:admin)
# MySQL interface: 127.0.0.1:6033
```

### 2. Базовая конфигурация (read/write split)

```sql
-- Подключение к admin interface
mariadb -h 127.0.0.1 -P 6032 -u admin -padmin

-- Добавить backend-серверы
INSERT INTO mysql_servers (hostgroup_id, hostname, port, weight) VALUES
  (0, 'source.example.com', 3306, 1000),   -- writers
  (1, 'replica1.example.com', 3306, 1000), -- readers
  (1, 'replica2.example.com', 3306, 1000); -- readers

LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;

-- Добавить пользователя
INSERT INTO mysql_users (username, password, default_hostgroup) VALUES
  ('app_user', 'app_password', 0);

LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;

-- Настроить мониторинг
UPDATE global_variables SET variable_value='monitor' WHERE variable_name='mysql-monitor_username';
UPDATE global_variables SET variable_value='monitor_password' WHERE variable_name='mysql-monitor_password';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

### 3. Read/Write Split через query rules

```sql
-- Правило: SELECT (не FROM write_hostgroup) → readers (hostgroup 1)
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, destination_hostgroup, apply) VALUES
  (1, 1, '^SELECT', 1, 1);

-- Исключение: SELECT ... FOR UPDATE → writers (hostgroup 0)
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, destination_hostgroup, apply) VALUES
  (2, 1, '^SELECT.*FOR UPDATE', 0, 1);

LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

**Порядок правил:** правила применяются по `rule_id` (порядку); `apply=1` останавливает обработку следующих правил. Правило `FOR UPDATE` должно быть перед общим `^SELECT`.

### 4. Connection pooling

```sql
-- Проверить пул
SELECT * FROM stats_mysql_connection_pool;

-- Настроить размер пула (по умолчанию — динамический)
-- max_connections на backend ограничивается через mysql_servers
UPDATE mysql_servers SET max_connections = 200 WHERE hostgroup_id = 0;
LOAD MYSQL SERVERS TO RUNTIME;
```

### 5. Query Cache (ProxySQL)

```sql
-- Включить кэш: непустое значение mysql-query_cache_size_MB активирует механизм
UPDATE global_variables SET variable_value='256'
WHERE variable_name='mysql-query_cache_size_MB';  -- размер в МБ

-- Soft TTL: доля от cache_ttl, начиная с которой запись считается устаревшей (0–100%)
UPDATE global_variables SET variable_value='80'
WHERE variable_name='mysql-query_cache_soft_ttl_pct';

LOAD MYSQL VARIABLES TO RUNTIME;

-- Правило: кэшировать SELECT на 60 секунд (TTL в мс)
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, cache_ttl, apply) VALUES
  (10, 1, '^SELECT .* FROM products$', 60000, 1);

LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;

-- Проверить кэш
SELECT * FROM stats_mysql_query_rules;
```

**Важное ограничение:** инвалидации кэша по изменению данных в таблицах **нет**. Запись перестаёт выдаваться только по истечении `cache_ttl`. Кэш пригоден только для справочных данных, изменяемых редко. Подробнее — в [ProxySQL: Query Rules и Query Cache](../MySQL/ProxySQL/proxysql_query_rules.md).

### 6. Мониторинг и диагностика

```sql
-- Статус backend-серверов
SELECT hostgroup_id, hostname, port, status, weight
FROM runtime_mysql_servers;

-- Статистика запросов
SELECT * FROM stats_mysql_query_digest ORDER BY sum_time DESC LIMIT 10;

-- Соединения
SELECT * FROM stats_mysql_global WHERE variable_name IN ('Client__connections', 'Conn__pool');

-- Правила (какие сработали)
SELECT rule_id, hits, hit_ratio FROM stats_mysql_query_rules;

-- Проверить маршрутизацию
SELECT * FROM stats_mysql_query_digest WHERE digest_text LIKE '%orders%';
```

**Валидация read/write split:**
```bash
# Через ProxySQL
mariadb -h 127.0.0.1 -P 6033 -u app_user -papp_password \
  -e "SELECT @@hostname, @@read_only;"
# → source (read_only=0) для WRITE, replica (read_only=1) для SELECT
```

## Устранение неполадок (Troubleshooting)

### Backend-сервер OFFLINE

*   **Причина:** недоступен, неверные credentials мониторинга, `read_only` не определён.
*   **Диагностика:** `SELECT * FROM runtime_mysql_servers;` — статус `OFFLINE_HARD`/`OFFLINE_SOFT`.
*   **Решение:** проверьте сетевую доступность, пользователя мониторинга, `read_only` на репликах.

### Запросы идут не на тот сервер

*   **Причина:** неправильный порядок `mysql_query_rules`, `apply` не установлен.
*   **Диагностика:** `SELECT * FROM stats_mysql_query_rules;` — `hits` по правилам.
*   **Решение:** проверьте `rule_id` (порядок), `apply=1`, `match_pattern` (regex).

### Connection pooling не работает

*   **Причина:** приложение использует разные credentials или charset.
*   **Диагностика:** `stats_mysql_connection_pool` — много соединений к одному backend.
*   **Решение:** унифицируйте credentials приложения; проверьте `mysql_users`.

### Высокая задержка через ProxySQL

*   **Причина:** query rules с дорогими regex, недостаточно памяти, DNS-lookup.
*   **Решение:** упростите regex; увеличьте память; используйте IP вместо hostname.

## Лучшие практики (Best Practices)

1.  **Read/Write Split:** направляйте `SELECT` на реплики, `FOR UPDATE` — на source.
2.  **Connection pooling:** используйте вместо увеличения `max_connections` на MariaDB.
3.  **Мониторьте `stats_mysql_query_digest`** — топ запросов через прокси.
4.  **Query cache** — только для редко меняющихся данных (с `cache_ttl`).
5.  **Failover:** для автоматического failover используйте MaxScale, Orchestrator или скрипты (ProxySQL реагирует на смену ролей, но не выполняет failover самостоятельно).
6.  **Тестируйте правила** в staging перед production.

## Ограничения и граничные случаи

### 1. Нет встроенного автоматического failover

ProxySQL **не выполняет** повышение реплики до primary — это задача внешнего инструмента (Orchestrator, MHA, Patroni). ProxySQL **реагирует** на изменения ролей через `mysql_replication_hostgroups`. Подробнее — в [ProxySQL: Failover](../MySQL/ProxySQL/proxysql_failover.md).

### 2. Query Cache: отсутствие инвалидации при изменении данных

Кеш ProxySQL не инвалидируется при `UPDATE`/`DELETE` — запись сбрасывается только по истечении `cache_ttl`. Использовать только для справочных данных, изменяемых редко (reference data, товарные каталоги с периодическим обновлением).

### 3. `SET` команды и multiplexing

Приложения, выполняющие `SET` сессионных переменных (часто ORM), вызывают **pinning** — соединение не возвращается в пул. Массовый pinning теряет весь эффект connection pooling. Решения — в [ProxySQL: Connection Pool](../MySQL/ProxySQL/proxysql_connection_pool.md): задать `mysql-default_isolation_level` и не полагаться на `SET` от клиента; использовать `transaction_persistent = 1` для пользователей, которым нужна стабильность.

### 4. Regex performance в `mysql_query_rules`

Сложные regex в `match_pattern` могут стать узким местом на высоких throughput. Рекомендуется:
*   Использовать `match_digest` вместо `match_pattern` (хэш нормализованного запроса вместо regex)
*   Упорядочивать правила по `rule_id` — самые популярные первыми
*   Избегать `.*?` в начале шаблона

```sql
-- Предпочтительно: match_digest (быстрее)
INSERT INTO mysql_query_rules (rule_id, active, match_digest, destination_hostgroup, apply)
VALUES (1, 1, 'SELECT .* FROM orders WHERE', 1, 1);
```

### 5. Ограничения `read_only` в ProxySQL 3.0.x

В ProxySQL 3.0.11+ одиночное значение `read_only` в `mysql_replication_hostgroups.check_type` отклоняется CHECK-ограничением. Требуется `super_read_only`, `innodb_read_only`, или комбинированное значение (`read_only&innodb_read_only`). Для MariaDB 10.4+ используйте `super_read_only`.

### 6. Admin interface: открытый доступ

По умолчанию admin interface слушает `0.0.0.0:6032` с паролем `admin:admin`. В продакшене:
*   Измените пароль
*   Привяжите к localhost или internal IP
*   Используйте firewall

```sql
-- Проверить текущие настройки
SELECT variable_name, variable_value FROM global_variables
WHERE variable_name IN ('admin-mysql_ifaces', 'admin-admin_credentials');
```

### 7. Состояние SHUNNED vs OFFLINE

| Статус | Автоматически? | Когда используется |
| :--- | :--- | :--- |
| `SHUNNED` | Да (monitor) | Временно исключение при ошибках ping/медленном ответе |
| `OFFLINE_SOFT` | Да или вручную | Перестаёт получать новые запросы, но дожидается завершения текущих |
| `OFFLINE_HARD` | Да или вручную | Немедленное удаление из rotation; активные соединения разорваны |

## Дополнительная информация

### См. также

*   **[MaxScale](MaxScale/maxscale_overview.md)** — альтернативный прокси с встроенным failover.
*   **[Отказоустойчивость](high_availability.md)** — HA-архитектуры MariaDB.
*   **[Репликация: обзор](replication/overview.md)** — source-replica топология.
*   **[Управление соединениями](connection_management.md)** — pooling в MariaDB.
*   **[Конфигурация MariaDB](configuration.md)** — OS tuning, InnoDB sizing.
*   **[Мониторинг](monitoring.md)** — метрики и алёрты для MariaDB.
*   **[MySQL: ProxySQL — обзор](../MySQL/ProxySQL/proxysql_overview.md)** — общая архитектура, трёхуровневая модель конфигурации.
*   **[MySQL: ProxySQL — failover](../MySQL/ProxySQL/proxysql_failover.md)** — `mysql_replication_hostgroups`, `max_replication_lag`, monitor-пользователь.
*   **[MySQL: ProxySQL — мониторинг](../MySQL/ProxySQL/proxysql_monitoring.md)** — метрики, dashboard, `monitor` DB.
*   **[MySQL: ProxySQL — connection pool](../MySQL/ProxySQL/proxysql_connection_pool.md)** — multiplexing, pinning.
*   **[MySQL: ProxySQL — query rules](../MySQL/ProxySQL/proxysql_query_rules.md)** — DSL, cache TTL, soft TTL.
*   **[MySQL: ProxySQL — security](../MySQL/ProxySQL/proxysql_security.md)** — TLS, credentials, firewall.
*   **[MySQL: ProxySQL — HA/cluster](../MySQL/ProxySQL/proxysql_ha_cluster.md)** — active/passive multi-instance.

### Внешние ресурсы

*   [ProxySQL Documentation](https://proxysql.com/documentation/)
*   [ProxySQL GitHub](https://github.com/sysown/proxysql)
*   [ProxySQL Query Rules](https://proxysql.com/documentation/topics/query-handling)
*   [ProxySQL MySQL Servers](https://proxysql.com/documentation/backend-server-configuration)
