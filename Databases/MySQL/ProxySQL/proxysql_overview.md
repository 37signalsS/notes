# ProxySQL: Обзор и использование с MySQL/MariaDB

**Актуально для:** ProxySQL 3.0.x

## Определения

*   **ProxySQL** — высокопроизводительный, открытый прокси-сервер для протокола MySQL. Обладает глубоким пониманием SQL-запросов и обеспечивает интеллектуальную маршрутизацию, пулинг соединений и кэширование. Работает на уровне L7 (Application Layer), в отличие от L4-балансировщиков, анализируя содержимое каждого SQL-запроса для принятия решения о маршрутизации.
*   **Hostgroup (Группа хостов)** — логическое объединение серверов БД в ProxySQL. Обычно разделяются на `writer` (для записи) и `reader` (для чтения). Каждый сервер может принадлежать нескольким группам одновременно.
*   **Query Rule (Правило запроса)** — условие (регулярное выражение, ключевое слово, digest или клиентский IP), на основе которого ProxySQL решает, в какую `hostgroup` направить запрос, кэшировать ли результат или блокировать запрос.
*   **Admin Interface** — встроенный интерфейс управления на базе SQLite, доступный по порту 6032 по умолчанию. Позволяет изменять конфигурацию в рантайме без перезапуска прокси. Поддерживает SQL-синтаксис для управления серверами, правилами, пользователями и мониторингом.
*   **Monitor** — внутренний модуль ProxySQL, который отслеживает здоровье серверов БД (connectivity, replication lag, read_only). Временно исключает проблемные серверы из роутинга, помечая их как `SHUNNED` (состояние монитора), либо выставляя им статус `OFFLINE_SOFT` / `OFFLINE_HARD` в таблице `mysql_servers`.
*   **Query Digest** — хэш-сумма нормализованного SQL-запроса (без литеральных значений), используемая для группировки статистики и применения правил маршрутизации.
*   **Connection Pooling** — механизм переиспользования TCP-соединений с серверами БД. Клиентские сессии мультиплексируются через ограниченное число бэкенд-соединений, что снижает нагрузку на `max_connections` сервера.
*   **Multiplexing** — расширение пулинга: возможность обслуживать тысячи клиентских сессий через десятки соединений с БД, при условии что клиенты не используют транзакции, временные таблицы или пользовательские переменные.

---

## Базовые концепции

### Архитектура ProxySQL

ProxySQL работает как промежуточный слой между приложением и базой данных. В отличие от L4-балансировщиков (HAProxy), он анализирует содержимое каждого SQL-запроса (L7), что позволяет принимать решения на основе самого запроса, а не только IP/порта.

```
Client (App) → ProxySQL:6033 → MySQL/MariaDB Backend
                 ↕
           Admin Interface:6032 (управление)
```

**Поток запроса через ProxySQL:**

1. Клиент устанавливает TCP-соединение с ProxySQL (порт по умолчанию 6033).
2. ProxySQL проверяет credentials клиента через таблицу `mysql_users`.
3. Запрос проходит через цепочку **Query Rules** (по приоритету `rule_id`).
4. По совпавшему правилу определяется целевая `hostgroup`.
5. Соединение берется из **Connection Pool** (или создается новое).
6. Запрос перенаправляется на выбранный сервер БД.
7. Результат возвращается клиенту через ProxySQL.
8. При кэшировании — результат сохраняется и повторные идентичные запросы обслуживаются из кэша.

### Трёхуровневая модель конфигурации

ProxySQL использует уникальную трёхуровневую систему, что является одним из его ключевых преимуществ. Это позволяет тестировать изменения перед применением и делать откат конфигурации за миллисекунды.

| Уровень | Описание | Когда используется |
| :--- | :--- | :--- |
| **MEMORY** | Текущая рабочая конфигурация в оперативной памяти. Все изменения через Admin Interface попадают сюда. | Основной рабочий уровень. Все запросы обрабатываются на основе именно этого уровня. |
| **DISK** | Персистентное хранилище (SQLite-файл на диске). Выживает перезапуск ProxySQL. | Автозагрузка при старте ProxySQL. Точка сохранения «эталонной» конфигурации. |
| **RUNTIME** | Активная конфигурация, используемая рабочими потоками. Зеркало MEMORY после `LOAD ... TO RUNTIME`. | Фактический уровень обработки запросов. Кэширует предыдущую конфигурацию для быстрого отката. |

**Цикл изменения конфигурации:**

```sql
-- 1. Изменение в MEMORY
INSERT INTO mysql_servers (...) VALUES (...);

-- 2. Проверка изменений (опционально, но рекомендуется)
SELECT * FROM mysql_servers WHERE hostname = 'new-server';

-- 3. Активация: MEMORY → RUNTIME
LOAD MYSQL SERVERS TO RUNTIME;

-- 4. Сохранение на диск: MEMORY → DISK
SAVE MYSQL SERVERS TO DISK;
```

**Быстрый откат:** Если новая конфигурация привела к проблемам, верните состояние, сохранённое на диске: `LOAD MYSQL SERVERS FROM DISK;` (Disk → Memory), затем `LOAD MYSQL SERVERS TO RUNTIME;` (Memory → Runtime).

### Ключевые возможности SRE-уровня

*   **Query Firewall:** Возможность блокировать вредоносные или неоптимизированные запросы на лету без изменения кода приложения. Поддерживает регулярные выражения, совпадение по digest и клиентским IP.
*   **Query Caching:** Встроенное TTL-кэширование результатов запросов, снижающее задержки для часто запрашиваемых данных. Кэш инвалидируется автоматически по TTL или при записи в связанные таблицы.
*   **Multiplexing:** Позволяет тысячам клиентов работать через небольшое количество соединений с БД, если они не используют транзакции или временные таблицы. Критически важно для environments с высоким `max_connections` на стороне приложений.
*   **Graceful Failover:** При интеграции с Orchestrator или MHA, ProxySQL может мгновенно перенаправлять трафик при падении мастера, минимизируя ошибки 5xx. С 2026 года Orchestrator поддерживает нативную интеграцию с ProxySQL без внешних скриптов.
*   **Read/Write Splitting:** Автоматическое разделение трафика: `SELECT` уходят на реплики, `INSERT/UPDATE/DELETE` — на мастер. Поддерживает сложные сценарии с `SELECT FOR UPDATE`, транзакциями и session variables.
*   **Runtime Configuration:** Все изменения конфигурации применяются без перезапуска ProxySQL и без разрыва клиентских соединений. Время применения — миллисекунды.
*   **Мониторинг и статистика:** Встроенные таблицы статистики (`stats_mysql_query_digest`, `stats_mysql_connection_pool`, `stats_mysql_backend`) позволяют анализировать распределение запросов, задержки и ошибки в реальном времени.

---

## Установка и предварительные требования

### Системные требования

| Параметр | Минимальный | Рекомендуемый |
| :--- | :--- | :--- |
| **CPU** | 1 ядро | 2+ ядра (зависимость от нагрузки) |
| **RAM** | 512 MB | 2+ GB (особенно при большом количестве правил) |
| **Диск** | 100 MB | SSD для логов и базы данных мониторинга |
| **ОС** | Linux (RHEL 7+, Debian 9+, Ubuntu 18.04+) | Текущий стабильный релиз |
| **MySQL/MariaDB** | MySQL 5.5+, MariaDB 10.0+ | MySQL 8.0+, MariaDB 10.6+ |

### Установка из официального репозитория

**RHEL/CentOS/Rocky Linux:**

```bash
# Добавление репозитория ProxySQL
curl -sS https://repo.proxysql.com/ProxySQL/repo_pub_key | sudo tee /etc/pki/rpm-gpg/RPM-GPG-KEY-ProxySQL
sudo tee /etc/yum.repos.d/ProxySQL.repo <<'EOF'
[proxysql]
name = ProxySQL
baseurl = https://repo.proxysql.com/ProxySQL/proxysql-3.0.x/centos/$releasever
gpgkey = https://repo.proxysql.com/ProxySQL/proxysql-3.0.x/repo_pub_key
gpgcheck = 1
enabled = 1
EOF

sudo dnf install -y proxysql
```

**Debian/Ubuntu:**

```bash
# Добавление репозитория ProxySQL
curl -sS https://repo.proxysql.com/ProxySQL/repo_pub_key | sudo tee /etc/apt/trusted.gpg.d/proxysql-keyring.gpg
echo "deb https://repo.proxysql.com/ProxySQL/proxysql-3.0.x/$(lsb_release -cs) ./" | sudo tee /etc/apt/sources.list.d/proxysql.list

sudo apt-get update
sudo apt-get install -y proxysql
```

**Docker (для тестирования):**

```bash
# Docker-образ не должен запускаться с тегом latest: версия из образа
# должна совпадать со строкой версии файла (ProxySQL 3.0.x).
# Актуальный список тегов проверяется в реестре перед развёртыванием:
#   docker manifest inspect proxysql/proxysql:3.0.11
docker run -d \
  --name proxysql \
  -p 6033:6033 \
  -p 6032:6032 \
  proxysql/proxysql:3.0.11
# → Идентификатор контейнера возвращён
```

### Проверка установки

```bash
# Проверка версии
proxysql --version
# → ProxySQL version 3.0.x, codename ...

# Проверка статуса службы
systemctl status proxysql
# → active (running)

# Просмотр логов
tail -f /var/lib/proxysql/proxysql.log
```

### Создание служебного пользователя в MySQL/MariaDB

ProxySQL использует **разные** учётные данные для монитора и для роутера, и они не должны совпадать.

### Учётная запись монитора (`mysql-monitor_username` / `mysql-monitor_password`)

Подключается Monitor-модулем для проверок доступности, `read_only` и лага репликации. По умолчанию — `monitor` / `monitor`.

```sql
-- Выполните на каждом узле MySQL/MariaDB
CREATE USER 'monitor'@'%' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
GRANT USAGE ON *.* TO 'monitor'@'%';
-- Для мониторинга лага репликации добавьте:
GRANT REPLICATION CLIENT ON *.* TO 'monitor'@'%';
FLUSH PRIVILEGES;

UPDATE global_variables SET variable_value = 'monitor'
WHERE variable_name = 'mysql-monitor_username';
UPDATE global_variables SET variable_value = 'СЛОЖНЫЙ_ПАРОЛЬ'
WHERE variable_name = 'mysql-monitor_password';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

**Объяснение привилегий:**
- `USAGE` — базовый уровень, достаточный для подключения, пинга и проверки `read_only`.
- `REPLICATION CLIENT` — требуется только если у серверов задан `max_replication_lag > 0` (мониторинг лага через `SHOW REPLICA STATUS`).

> **Важно:** пользователь из `mysql-monitor_username` **не может** быть использован в таблице `mysql_users` — это ограничение ProxySQL. Учётные данные для роутера (подключения к бэкендам от имени клиентов) задаются отдельно, в `mysql_users`.

**Дополнительно:** Для read-only доступа к статистике через `admin-stats_credentials` настройте отдельного пользователя Admin-интерфейса, а для сбора метрик в Prometheus используйте встроенный exporter (см. [ProxySQL: Мониторинг](./proxysql_monitoring.md)) — отдельный `proxysql-exporter` больше не требуется.

---

## Практические сценарии

### 1. Настройка Read/Write Split

**Prerequisites:** Развернутый ProxySQL и кластер MySQL/MariaDB (1 мастер, 2 реплики).

#### Шаг 1: Подключение к Admin-интерфейсу

```bash
mysql -u admin -p -h 127.0.0.1 -P 6032
# Пароль по умолчанию: admin (НЕОБХОДИМО сменить в продакшене!)
```

#### Шаг 2: Добавление серверов в группы хостов

```sql
-- Writer группа (мастер, группа 10)
INSERT INTO mysql_servers(hostgroup_id, hostname, port, max_connections, weight)
VALUES (10, 'db-master', 3306, 200, 1000);

-- Reader группа (реплики, группа 20)
INSERT INTO mysql_servers(hostgroup_id, hostname, port, max_connections, weight)
VALUES (20, 'db-replica-1', 3306, 200, 1000);

INSERT INTO mysql_servers(hostgroup_id, hostname, port, max_connections, weight)
VALUES (20, 'db-replica-2', 3306, 200, 1000);

-- Активация и сохранение
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

**Параметры:**
- `max_connections` — максимальное количество соединений из пула к данному серверу.
- `weight` — вес сервера в рамках группы для балансировки. Чем выше вес, тем больше трафика получает сервер.

#### Шаг 3: Настройка мониторинга (Health Check)

```sql
-- Настройка проверки подключения к серверам
UPDATE global_variables SET variable_value='2000'
WHERE variable_name='mysql-monitor_connect_interval';

UPDATE global_variables SET variable_value='1000'
WHERE variable_name='mysql-monitor_ping_interval';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

#### Шаг 4: Создание правил маршрутизации

```sql
-- Правило 1: Все SELECT запросы на группу 20 (реплики)
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, destination_hostgroup, apply)
VALUES (1, 1, '^SELECT .*', 20, 1);

-- Правило 2: SELECT FOR UPDATE на мастера (группа 10) — для консистентности данных
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, destination_hostgroup, apply)
VALUES (2, 1, '^SELECT .* FOR UPDATE', 10, 1);

-- Правило 3: Транзакции на мастера
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, destination_hostgroup, apply)
VALUES (3, 1, '^(INSERT|UPDATE|DELETE|COMMIT|ROLLBACK).*', 10, 1);

-- Активация и сохранение
LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

**Объяснение полей `mysql_query_rules`:**
- `rule_id` — уникальный идентификатор правила. Правила применяются по возрастанию `rule_id`.
- `active` — `1` = правило активно, `0` = отключено.
- `match_pattern` — регулярное выражение для сопоставления с текстом запроса.
- `destination_hostgroup` — целевая группа хостов.
- `apply` — `1` = остановить обработку следующих правил после совпадения, `0` = продолжить проверку.

#### Шаг 5: Настройка пользователей приложений

```sql
-- Создание пользователя в ProxySQL (не в MySQL!)
INSERT INTO mysql_users (username, password, default_hostgroup)
VALUES ('app_user', 'ПАРОЛЬ_ПРИЛОЖЕНИЯ', 10);

LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

**Важно:** Пользователь `app_user` должен быть создан на всех серверах MySQL/MariaDB. ProxySQL использует его для подключения к бэкенд-серверам.

#### Шаг 6: Валидация работы

```bash
# Подключение через ProxySQL
mysql -u app_user -p -h <proxysql_host> -P 6033

# Проверка маршрутизации
SELECT * FROM stats_mysql_query_digest WHERE digest_text LIKE 'SELECT%' LIMIT 5;
# → digest_text покажет запросы, count_star — количество выполнений

# Проверка распределения по группам
SELECT hostgroup, count_star, sum_time FROM stats_mysql_query_digest;
# → hostgroup 20 (reader) должен иметь значительно больше запросов, чем 10 (writer)

# Проверка статуса серверов
SELECT hostgroup, srv_host, status, ConnUsed, ConnFree, ConnOK, ConnERR
FROM stats_mysql_connection_pool;
# → status должен быть OK у всех серверов

# Проверка здоровья через монитор
SELECT hostname, port, status, connect_time
FROM monitor.mysql_server_connect_log
ORDER BY time_start_us DESC
LIMIT 5;
```

### 2. Query Firewall: Блокировка запросов

Query Firewall позволяет блокировать опасные или ресурсоемкие запросы на уровне прокси, не изменяя код приложения.

```sql
-- Блокировка запросов с DROP TABLE
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, error_msg, apply)
VALUES (10, 1, '.*DROP TABLE.*', 'DROP TABLE is not allowed through ProxySQL', 1);

-- Блокировка запросов с CREATE TABLE (ограничение DDL)
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, error_msg, apply)
VALUES (11, 1, '.*CREATE TABLE.*', 'DDL operations are restricted', 1);

-- Блокировка запросов от определенного клиента по IP
INSERT INTO mysql_query_rules (rule_id, active, client_addr, error_msg, apply)
VALUES (12, 1, '10.0.0.99', 'Access denied from this IP', 1);

LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

**Параметры `error_msg`:** Текст ошибки, который ProxySQL вернет клиенту вместо выполнения запроса. Позволяет приложению различать блокировку прокси от ошибки сервера.

### 3. Query Cache: TTL-кэширование

Встроенное кэширование результатов запросов для снижения нагрузки на БД. Механизм ProxySQL не связан с `query_cache` самого MySQL и включается **отдельными переменными**, а не через `mysql-server_capabilities`.

```sql
-- Включение кэширования и задание его предельного размера.
-- Установка непустого значения mysql-query_cache_size_MB включает механизм.
UPDATE global_variables SET variable_value='128'
WHERE variable_name='mysql-query_cache_size_MB';

-- «Мягкий» TTL: доля от cache_ttl, начиная с которой запись считается устаревшей.
-- Тип — целое число (проценты), диапазон 0-100. По умолчанию 0 — механизм выключен.
UPDATE global_variables SET variable_value='80'
WHERE variable_name='mysql-query_cache_soft_ttl_pct';

-- TTL задаётся в правилах, в миллисекундах
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, cache_ttl, apply)
VALUES (20, 1, '^SELECT .* FROM products WHERE category_id = .*', 30000, 1);

-- Кэширование результатов запросов к справочнику (TTL 5 минут)
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, cache_ttl, apply)
VALUES (21, 1, '^SELECT .* FROM reference_data.*', 300000, 1);

LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

**Объяснение:**
- `mysql-query_cache_size_MB` — размер кэша в МБ; `NULL`/0 отключает кэширование.
- `mysql-query_cache_soft_ttl_pct` — «мягкий» TTL: если запись достигла этой доли от `cache_ttl`, но ещё не достигла самого TTL, то следующий запрос **не попадёт** в кэш — он уйдёт на бэкенд, который обновит и результат, и TTL записи. Тип — целое число (проценты), диапазон `0`–`100`, по умолчанию `0`. Смысл: заставить «горячие» записи освежаться с бэкенда до истечения жёсткого TTL, а не отдавать клиенту устаревшие данные.
- `cache_ttl` — время жизни записи кэша в миллисекундах; `0` = кэширование отключено.
- `cache_empty_result` — кэшировать ли пустой результат (`0`/`1`).
- `cache_timeout` — сколько миллисекунд можно ждать ответа бэкенда, прежде чем отдавать устаревшее значение из кэша.

**Важное ограничение:** инвалидации кэша по изменению данных в таблице **нет**. Запись перестаёт выдаваться только по истечении `cache_ttl`. Это делает механизм пригодным лишь для справочных данных, изменяемых редко. Подробнее — в [ProxySQL: Query Rules и Query Cache](./proxysql_query_rules.md).

**Проверка статистики кэша:**

```sql
SELECT * FROM stats_mysql_query_digest WHERE cache_hit_count > 0;
# → строки с ненулевым cache_hit_count
```

### 4. Интеграция с Orchestrator: Нативная поддержка

Orchestrator умеет обновлять hostgroups ProxySQL самостоятельно, без внешних скриптов: при failover он меняет статус `read_only` у узлов и переносит новый writer/reader в соответствующие hostgroups ProxySQL. Механизм включается секцией `ProxySQL` в конфигурации Orchestrator.

#### Конфигурация Orchestrator

```json
{
  "ProxySQL": {
    "ProxySQLAdminAddress": "10.0.1.10:6032",
    "ProxySQLAdminPort": 6032,
    "ProxySQLAdminUser": "orchestrator",
    "ProxySQLAdminPassword": "СЛОЖНЫЙ_ПАРОЛЬ",
    "ProxySQLWriterHostgroup": 10,
    "ProxySQLReaderHostgroup": 20,
    "ProxySQLPreFailoverAction": "true"
  }
}
```

**Значения параметров:**

| Параметр | Назначение |
| :--- | :--- |
| `ProxySQLAdminAddress` | Адрес admin-интерфейса ProxySQL (`host:port`) |
| `ProxySQLAdminPort` | Порт admin-интерфейса (по умолчанию `6032`) |
| `ProxySQLAdminUser` / `ProxySQLAdminPassword` | Учётные данные для подключения к admin-интерфейсу |
| `ProxySQLWriterHostgroup` | Hostgroup для writer (в примере — `10`) |
| `ProxySQLReaderHostgroup` | Hostgroup для reader (в примере — `20`) |
| `ProxySQLPreFailoverAction` | Управляет тем, обновляет ли Orchestrator hostgroups до или после MySQL-failover |

#### Настройка ProxySQL для работы с Orchestrator

```sql
-- Группы хостов должны соответствовать конфигурации Orchestrator:
-- Writer (master) — hostgroup 10, Reader (реплики) — hostgroup 20.
-- Задаются через mysql_replication_hostgroups (см. ниже) либо напрямую.

-- Проверка текущей конфигурации
SELECT hostgroup_id, hostname, port, status FROM mysql_servers;
# → hostgroup_id | hostname | port | status
# →           10 | db-master-1 | 3306 | ONLINE
# →           20 | db-replica-1 | 3306 | ONLINE
```

**Как это работает:**
1. Orchestrator обнаруживает падение writer.
2. Выбирает реплику для promotion и выполняет MySQL-failover.
3. Обновляет hostgroups в ProxySQL: новый writer попадает в `ProxySQLWriterHostgroup`, остальные реплики — в `ProxySQLReaderHostgroup`.
4. ProxySQL начинает маршрутизировать запись на новый writer.

**Важно:** GTID **не обязателен**. Orchestrator поддерживает как GTID-репликацию, так и pseudo-GTID, а также file-based репликацию. Правила выбора реплики по лагу настраиваются отдельно.

Полная схема hostgroups, мониторинга лага и ручного failover — в [ProxySQL: Failover и мониторинг репликации](./proxysql_failover.md).

### 5. Мониторинг через Prometheus

ProxySQL имеет **встроенный** HTTP-endpoint для метрик, отдельный `proxysql-exporter` не требуется. Экспорт реализован в виде REST API admin-интерфейса и включается переменными `admin-restapi_enabled` / `admin-restapi_port`.

#### Включение встроенного мониторинга

```sql
-- Включение REST API с метриками (по умолчанию выключено)
UPDATE global_variables SET variable_value='true'
WHERE variable_name='admin-restapi_enabled';

-- Порт REST API с метриками (не путать с admin-интерфейсом 6032)
UPDATE global_variables SET variable_value='6070'
WHERE variable_name='admin-restapi_port';

LOAD ADMIN VARIABLES TO RUNTIME;
SAVE ADMIN VARIABLES TO DISK;
```

#### Настройка Prometheus scrape

```yaml
scrape_configs:
  - job_name: 'proxysql'
    scrape_interval: 15s
    static_configs:
      - targets: ['proxysql-host:6070']
    metrics_path: '/metrics'
    # Порт 6070 — встроенный exporter. Внешний proxysql-exporter
    # на отдельном порту не используется.
```

#### Ключевые метрики для мониторинга

Имена метрик и значения лейблов приведены по исходному коду ProxySQL 3.0.11. В 3.0.11 все метрики дополнительно несут лейбл `protocol="mysql"` — он нужен, потому что модули MySQL и PostgreSQL регистрируют одноимённые метрики.

| Метрика | Описание | Типичный порог |
| :--- | :--- | :--- |
| `proxysql_client_connections_connected` | Клиентские соединения в состоянии connected | Резкий рост = утечка соединений |
| `proxysql_client_connections_total{status="aborted"}` | Прерванные клиентские соединения (rate) | Рост = проблемы с приложением или сетью |
| `proxysql_connpool_conns{status="used"}` | Занятые соединения пула (gauge) | Рост = нехватка размера пула |
| `proxysql_connpool_conns{status="free"}` | Свободные соединения пула (gauge) | Должно быть > 0 при нормальной нагрузке |
| `proxysql_connpool_conns_total{status="err"}` | Неудачные попытки взять соединение из пула (rate) | > 0 = разрыв соединения с бэкендом или исчерпание пула |
| `proxysql_connpool_conns_queries_total` | Запросы, прошедшие через пул | Рост = трафик |
| `proxysql_myhgm_auto_increment_multiplex_total` | Переключения на мультиплексирование | Резкий рост = multiplexing отключается |
| `proxysql_questions_total` | Всего запросов от клиентов | Рост = трафик |
| `proxysql_backend_query_time_seconds_total` | Гистограмма времени выполнения запросов на бэкенде | p99 > 100ms = проблема |
| `proxysql_mysql_monitor_enabled` | Включён ли MySQL Monitor (1/0) | 0 = монитор выключен |
| `proxysql_mysql_error_total` | Ошибки протокола MySQL | Рост = несовпадение версий или клиента |
| `proxysql_backend_offline_during_query_total` | Запросы к бэкенду, упавшему в `OFFLINE` | Рост = реальные failover-инциденты |

Полный список метрик и правила алертинга — в [ProxySQL: Мониторинг](./proxysql_monitoring.md).

#### Запросы для анализа через Admin Interface

```sql
-- Распределение запросов по группам хостов
SELECT hostgroup, count_star, sum_time, sum_time/count_star AS avg_time
FROM stats_mysql_query_digest
GROUP BY hostgroup;

-- Самые частые запросы (Top-10 по количеству выполнений)
SELECT digest_text, count_star, sum_time, sum_time/count_star AS avg_time_us
FROM stats_mysql_query_digest
ORDER BY count_star DESC
LIMIT 10;

-- Статистика пула соединений
SELECT hostgroup, srv_host, status, ConnUsed, ConnFree, ConnOK, ConnERR
FROM stats_mysql_connection_pool;

-- Мониторинг здоровья серверов
SELECT hostname, port, status, connect_time
FROM monitor.mysql_server_connect_log
ORDER BY time_start_us DESC
LIMIT 20;

-- Запросы с ошибками
SELECT hostgroup, digest_text, count_star
FROM stats_mysql_query_digest
WHERE count_star > 0 AND hostgroup IS NOT NULL
HAVING count_star > 100;
```

---

## Управление и мониторинг

### Основные таблицы Admin Interface

ProxySQL предоставляет обширный набор таблиц для управления и мониторинга:

#### Таблицы конфигурации

| Таблица | Назначение |
| :--- | :--- |
| `mysql_servers` | Серверы БД и их принадлежность к группам |
| `mysql_users` | Пользователи ProxySQL (для подключения приложений) |
| `mysql_query_rules` | Правила маршрутизации запросов |
| `global_variables` | Глобальные переменные конфигурации |
| `mysql_replication_hostgroups` | Автоматическое определение writer/reader для групп |

#### Таблицы статистики

| Таблица | Назначение |
| :--- | :--- |
| `stats_mysql_query_digest` | Статистика запросов по digest (количество, время, группа) |
| `stats_mysql_query_rules` | Счётчик совпадений по каждому `rule_id` |
| `stats_mysql_connection_pool` | Состояние пула соединений по серверам и hostgroup |
| `stats_mysql_processlist` | Активные клиентские сессии |
| `stats_mysql_errors` | Ошибки соединений и запросов |
| `stats_mysql_global` | Глобальные счётчики ProxySQL |

Полный список и назначение — в [ProxySQL: Мониторинг](./proxysql_monitoring.md).

#### Атомарная замена состава hostgroup

Отдельной staging-таблицы для замены состава группы **нет** — состав hostgroup хранится в `mysql_servers` (столбец `hostgroup_id`). Замена атомарна на этапе `LOAD MYSQL SERVERS TO RUNTIME`: правки (`DELETE` + `INSERT`) живут в Memory-таблице и применяются разом, без промежуточного состояния, в котором серверы отсутствуют. Полная процедура — в [ProxySQL: Конфигурация и переменные](./proxysql_configuration.md).

```sql
-- 1. Описать новый состав группы в Memory
DELETE FROM mysql_servers WHERE hostgroup_id = 20;
INSERT INTO mysql_servers (hostgroup_id, hostname, port)
VALUES (20, 'new-replica-1', 3306),
       (20, 'new-replica-2', 3306);

-- 2. Применить атомарно и зафиксировать
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

### Просмотр и изменение конфигурации

```sql
-- Просмотр текущих серверов
SELECT hostgroup_id, hostname, port, status, max_connections, weight
FROM runtime_mysql_servers;

-- Просмотр правил маршрутизации
SELECT rule_id, active, match_pattern, destination_hostgroup, cache_ttl, error_msg
FROM runtime_mysql_query_rules;

-- Просмотр переменных конфигурации
SHOW VARIABLES LIKE 'mysql%';

-- Быстрое добавление сервера (runtime без перезапуска)
INSERT INTO mysql_servers (hostgroup_id, hostname, port, max_connections)
VALUES (20, 'new-replica', 3306, 200);
LOAD MYSQL SERVERS TO RUNTIME;
```

### Автоматическое определение топологии (MySQL Replication)

ProxySQL может автоматически определять, какой сервер является мастером, а какие — репликами, через мониторинг переменной `read_only`.

```sql
-- Настройка автоматического переключения групп.
-- check_type в 3.0.x допускает: innodb_read_only, super_read_only,
-- read_only|innodb_read_only, read_only&innodb_read_only
INSERT INTO mysql_replication_hostgroups (writer_hostgroup, reader_hostgroup, check_type)
VALUES (10, 20, 'super_read_only');

LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

> Одиночное значение `read_only` — не исключение, а значение по умолчанию (`DEFAULT 'read_only'`) в 3.0.x; CHECK-ограничение отклонит только опечатки и несуществующие значения. Переносить конфигурацию с 2.x не требуется. Для MySQL 8.0+ предпочтительнее `super_read_only` — он является надмножеством `read_only` и учитывает обе переменные одновременно. Для Galera и Group Replication используются отдельные таблицы `mysql_galera_hostgroups` и `mysql_group_replication_hostgroups` — подробности в [ProxySQL: Failover](./proxysql_failover.md).

**Как это работает:**
- ProxySQL опрашивает все серверы в группе writer (10) и reader (20).
- Если сервер в группе writer имеет `read_only=ON`, он автоматически перемещается в группу reader.
- Если сервер в группе reader имеет `read_only=OFF`, он автоматически перемещается в группу writer.
- Это обеспечивает автоматическую маршрутизацию при `switchover` (плановом переключении).

---

## Best Practices

### Архитектурные рекомендации

1.  **Высокая доступность прокси:** Никогда не используйте один инстанс ProxySQL. Разворачивайте минимум два узла в связке с **Keepalived (VRRP)** для плавающего VIP. Это исключает single point of failure на уровне прокси. Альтернативно используйте **ProxySQL Cluster** для синхронизации конфигурации между несколькими инстансами.
2.  **Изоляция ресурсов:** Размещайте ProxySQL на отдельных виртуальных машинах или контейнерах. При высокой нагрузке ProxySQL потребляет значительные ресурсы CPU и памяти.
3.  **GTID-репликация:** Используйте GTID для корректной работы автоматического определения топологии и интеграции с Orchestrator.

### Конфигурация

4.  **`mysql-monitor_connect_interval`:** Интервал проверки достижимости серверов. Значение по умолчанию — `120000` мс (2 минуты). Для критичных систем его уменьшают, чтобы сократить окно недоступности, но нужно учитывать, что каждая проверка создаёт соединение с бэкендом.
5.  **`mysql-monitor_ping_interval`:** Интервал пинга серверов. Значение по умолчанию — `8000` мс. Уменьшать стоит осознанно: слишком частые проверки увеличивают нагрузку на бэкенды.
6.  **`max_connections` на серверах:** Задавайте `max_connections` на сервере БД выше, чем сумма `max_connections` всех прокси, чтобы не исчерпать лимит.
7.  **`default_hostgroup`:** Всегда задавайте `default_hostgroup` для пользователей, чтобы избежать маршрутизации по умолчанию на writer-группу.
8.  **Приоритет правил:** Правила оцениваются **в порядке убывания `rule_id`**. Первым применяется правило с наибольшим `rule_id`, поэтому специфичные правила должны иметь более высокий `rule_id`, чем общие (например, `SELECT ... FOR UPDATE` — больше, чем `SELECT`).

### Безопасность

9.  **Смена пароля Admin:** По умолчанию пароль Admin-интерфейса — `admin`. Обязательно смените его в продакшене.
10. **Ограничение доступа:** Привяжите Admin-интерфейс к конкретному IP (`admin-mysql_ifaces` в `global_variables`).
11. **Шифрование соединений:** Включите SSL/TLS для соединений между ProxySQL и клиентами, а также между ProxySQL и серверами БД.

### Мониторинг и алертинг

12. **Настройте алерты:** Мониторьте `proxysql_backend_query_time_seconds_total` (время выполнения запросов), `proxysql_connpool_conns_total{status="err"}` (неудачные попытки взять соединение из пула) и `proxysql_backend_offline_during_query_total` (запросы к упавшему бэкенду). Актуальный список метрик и примеры правил Prometheus — в [ProxySQL: Мониторинг](./proxysql_monitoring.md).
13. **Ротация логов:** Настройте ротацию логов ProxySQL для предотвращения заполнения диска.
14. **Регулярно проверяйте `stats_mysql_connection_pool`:** Убедитесь, что все серверы в статусе `ok`.

---

## Очистка и откат изменений

### Быстрый откат конфигурации

Если изменения, примененные через `LOAD ... TO RUNTIME`, привели к проблемам:

```sql
-- Откат к последнему сохраненному состоянию (DISK → RUNTIME)
LOAD MYSQL SERVERS TO RUNTIME;
LOAD MYSQL QUERY RULES TO RUNTIME;
LOAD MYSQL USERS TO RUNTIME;
LOAD MYSQL VARIABLES TO RUNTIME;
```

### Удаление серверов

```sql
-- Удаление сервера из конфигурации
DELETE FROM mysql_servers WHERE hostname = 'old-replica' AND hostgroup_id = 20;
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

### Удаление правил маршрутизации

```sql
-- Удаление правила по rule_id
DELETE FROM mysql_query_rules WHERE rule_id = 1;
LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

### Остановка и удаление ProxySQL

```bash
# Остановка службы
systemctl stop proxysql

# Удаление пакета (RHEL/Debian)
sudo dnf remove proxysql   # или apt remove proxysql

# Удаление данных конфигурации
sudo rm -rf /etc/proxysql /var/lib/proxysql /var/log/proxysql
```

---

## Граничные случаи и ограничения

### Известные ограничения

1.  **Транзакции и Read/Write Split:** Если транзакция начинается с `SELECT` (автоматическое чтение на реплике), а затем выполняется `UPDATE`, ProxySQL перенаправит `UPDATE` на мастер. Однако, если соединение уже привязано к реплике через Multiplexing, `UPDATE` может завершиться ошибкой. Используйте `SELECT ... FOR UPDATE` для гарантии направления на мастер.
2.  **Временные таблицы:** Временные таблицы видны только в пределах одной сессии. При переключении соединения между серверами временные таблицы теряются. ProxySQL отключает Multiplexing для соединений с временными таблицами.
3.  **Пользовательские переменные:** Переменные типа `@variable` не маршрутизируются и могут привести к некорректному поведению при переключении серверов. Минимизируйте их использование.
4.  **Prepared Statements:** ProxySQL поддерживает prepared statements как в text protocol (клиент подставляет значения через `mysql_real_escape_string`), так и в binary protocol (параметры передаются отдельно от текста запроса). Отдельный флаг `MYSQL_FORWARD_STMT` в актуальных версиях не требуется. Правила роутинга применяются к prepared statements так же, как к обычным запросам; при `transaction_persistent=1` у пользователя соединение закрепляется за сервером на всё время сессии. Подробнее — в [ProxySQL: Транзакции и prepared statements](./proxysql_transactions.md).
5.  **Глобальные блокировки:** `LOCK TABLES`, `FLUSH TABLES WITH READ LOCK` могут конфликтовать с работой роутера и вызывать зависания.
6.  **Одновременные транзакции:** ProxySQL не поддерживает маршрутизацию внутри одной транзакции на несколько серверов. Все операции в рамках одной транзакции направляются на один сервер.

### Нестандартные сценарии

*   **Смешанные MySQL + MariaDB:** ProxySQL поддерживает оба движка, но некоторые функции (например, GTID) могут работать по-разному. Рекомендуется использовать однородный стек.
*   **Каскадная репликация:** ProxySQL не имеет ограничений на топологию репликации. В cascaded-топологии (Replica → Replica) промежуточная реплика может обслуживать и запросы на запись, и реплицировать их дальше, если соответствующим hostgroups назначены роли. Нужно лишь учитывать, что `read_only`-мониторинг видит только локальное состояние узла, а задержка в цепочке накапливается.
*   **Большое количество баз данных:** При большом количестве баз данных необходимо настраивать правила маршрутизации по регулярным выражениям для конкретных схем.

---

## Устранение неполадок (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Error 1105: ProxySQL Error: no viable nodes in hostgroup` | Все серверы в группе помечены как `OFFLINE` или `SHUNNED`. | Проверьте таблицу `runtime_mysql_servers` и логи здоровья (таблица `monitor.mysql_server_connect_log`). Убедитесь, что мониторинг работает корректно. |
| Запросы не кэшируются | Отсутствие правила с `cache_ttl` или запрос содержит волатильные функции (NOW, RAND). | Добавьте правило с `cache_ttl > 0` для конкретного `digest`. Проверьте, что запрос не содержит волатильных функций. |
| Высокий Latency | Отключен Multiplexing из-за использования `@variables` или временных таблиц. | Минимизируйте использование пользовательских переменных в сессии приложения. Проверьте `stats_mysql_query_digest` для поиска медленных запросов. |
| `Connection refused` (клиент не может подключиться) | ProxySQL не запущен или слушает другой интерфейс/порт. | Проверьте статус службы: `systemctl status proxysql`. Проверьте `mysql-interface` в `global_variables`. |
| Запросы идут не в ту группу хостов | Неправильный приоритет правил или отсутствие `apply=1`. | Проверьте `rule_id` правил: они применяются по убыванию. Убедитесь, что специфичные правила имеют более высокий `rule_id`, чем общие. |
| `Access denied for user` (ошибка подключения к БД) | Неверные credentials в `mysql_users` или пользователь не создан на сервере БД. | Проверьте таблицу `mysql_users`. Убедитесь, что пользователь создан на всех серверах MySQL/MariaDB. |
| Соединения с серверами БД не устанавливаются | `max_connections` на сервере БД исчерпан или firewall блокирует порт. | Увеличьте `max_connections` на сервере БД. Проверьте firewall и сетевую доступность. |
| Возвращаются устаревшие данные из кэша | TTL слишком большой: автоматической инвалидации кэша при записи не существует. | Уменьшите `cache_ttl` для динамических данных либо не кэшируйте их. Для часто меняющихся данных используйте приложение, а не кэш ProxySQL. |
| Orchestrator не обновляет ProxySQL | Неверная конфигурация секции `ProxySQL` или несовпадение hostgroup. | Проверьте секцию `ProxySQL` в конфигурации Orchestrator: `ProxySQLAdminAddress`, `ProxySQLAdminPort`, `ProxySQLAdminUser`, `ProxySQLAdminPassword`, `ProxySQLWriterHostgroup`, `ProxySQLReaderHostgroup`. |
| Высокое потребление памяти ProxySQL | Большое количество правил, серверов или активных соединений. | Оптимизируйте количество правил. Используйте `mysql-max_connections` для ограничения. Проверьте `stats_mysql_global` для анализа использования. |

---

## ProxySQL vs MaxScale: Сравнение для SRE

| Характеристика | ProxySQL | MariaDB MaxScale |
| :--- | :--- | :--- |
| **Лицензия** | GPL (полностью бесплатно) | BSL (платно при >3 узлах БД) |
| **Фокус** | MySQL, Percona, MariaDB | Глубокая интеграция с MariaDB |
| **Конфигурация** | SQL-интерфейс (runtime) | Файлы .cnf или REST API |
| **Failover** | Требует внешних утилит (Orchestrator) | Нативный (автоматический Failover/Switchover) |
| **Кэширование** | Продвинутое (Query Cache) | Базовое |
| **Масштабирование** | Идеально для огромного числа соединений | Лучше всего для Galera Cluster |
| **Пулинг соединений** | Продвинутый (Multiplexing) | Базовый |
| **Поддержка версий** | MySQL 5.5+, MariaDB 10.0+ | MariaDB Server 10.5+ |
| **Интеграция с Orchestrator** | Нативная (секция `ProxySQL` в конфигурации) | Нет (использует свой Failover) |

---

## Дополнительная информация

### Тематические файлы раздела
- **[HA и ProxySQL Cluster](./proxysql_ha_cluster.md)** — Cluster, синхронизация конфигурации, деплой и вывод из ротации.
- **[Connection Pool и Multiplexing](./proxysql_connection_pool.md)** — как ProxySQL экономит соединения и что это отключает.
- **[Failover и мониторинг репликации](./proxysql_failover.md)** — hostgroups, `SHUNNED`, лаг, Galera и Group Replication.
- **[Query Rules и Query Cache](./proxysql_query_rules.md)** — движок правил, цепочки правил, firewall, кэш.
- **[Транзакции и prepared statements](./proxysql_transactions.md)** — autocommit, pinning, бинарный протокол.
- **[Мониторинг](./proxysql_monitoring.md)** — встроенный exporter, stats-таблицы, алертинг.
- **[Безопасность](./proxysql_security.md)** — аудит-лог, TLS, admin-интерфейс.
- **[Конфигурация и переменные](./proxysql_configuration.md)** — `proxysql.cnf`, префиксы, `LOAD`/`SAVE`.

### См. также
- **[Обзор MariaDB MaxScale](../../MariaDB/MaxScale/maxscale_overview.md)** — альтернатива для экосистемы MariaDB.
- **[Репликация MySQL: Обзор](../replication/overview.md)** — основа для настройки групп хостов.
- **[Мониторинг баз данных](../monitoring.md)** — интеграция метрик ProxySQL в Prometheus.
- **[Orchestrator: Управление топологией](../orchestrator.md)** — автоматизация failover и интеграция с ProxySQL.
- **[Keepalived: Обзор](../../../Networking/ServicesAndTools/keepalived_overview.md)** — VRRP/VIP для отказоустойчивости на уровне прокси.
- **[Connection Pooling](../../../Networking/Concepts/connection_pooling.md)** — общие принципы пулинга соединений.
