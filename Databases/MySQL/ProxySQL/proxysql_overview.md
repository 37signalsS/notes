# ProxySQL: Обзор и использование с MySQL/MariaDB

## Определения

*   **ProxySQL** — высокопроизводительный, открытый прокси-сервер для протокола MySQL. Обладает глубоким пониманием SQL-запросов и обеспечивает интеллектуальную маршрутизацию, пулинг соединений и кэширование. Работает на уровне L7 (Application Layer), в отличие от L4-балансировщиков, анализируя содержимое каждого SQL-запроса для принятия решения о маршрутизации.
*   **Hostgroup (Группа хостов)** — логическое объединение серверов БД в ProxySQL. Обычно разделяются на `writer` (для записи) и `reader` (для чтения). Каждый сервер может принадлежать нескольким группам одновременно.
*   **Query Rule (Правило запроса)** — условие (регулярное выражение, ключевое слово, digest или клиентский IP), на основе которого ProxySQL решает, в какую `hostgroup` направить запрос, кэшировать ли результат или блокировать запрос.
*   **Admin Interface** — встроенный интерфейс управления на базе SQLite, доступный по порту 6032 по умолчанию. Позволяет изменять конфигурацию в рантайме без перезапуска прокси. Поддерживает SQL-синтаксис для управления серверами, правилами, пользователями и мониторингом.
*   **Monitor** — внутренний модуль ProxySQL, который отслеживает здоровье серверов БД (connectivity, replication lag, read_only). Автоматически помечает недоступные серверы как `OFFLINE` или `SHUNNED`.
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

**Быстрый откат:** Если новая конфигурация привела к проблемам, достаточно выполнить `LOAD MYSQL SERVERS TO RUNTIME` из DISK-уровня, чтобы вернуть предыдущее состояние.

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
baseurl = https://repo.proxysql.com/ProxySQL/centos/9/x86_64
gpgkey = https://repo.proxysql.com/ProxySQL/repo_pub_key
gpgcheck = 1
enabled = 1
EOF

sudo dnf install -y proxysql
```

**Debian/Ubuntu:**

```bash
# Добавление репозитория ProxySQL
curl -sS https://repo.proxysql.com/ProxySQL/repo_pub_key | sudo tee /etc/apt/trusted.gpg.d/proxysql-keyring.gpg
echo "deb https://repo.proxysql.com/ProxySQL/$(lsb_release -cs) $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/proxysql.list

sudo apt-get update
sudo apt-get install -y proxysql
```

**Docker (для тестирования):**

```bash
docker run -d \
  --name proxysql \
  -p 6033:6033 \
  -p 6032:6032 \
  proxysql/proxysql:latest
```

### Проверка установки

```bash
# Проверка версии
proxysql --version
# → ProxySQL version 2.x.x, codename ...

# Проверка статуса службы
systemctl status proxysql
# → active (running)

# Просмотр логов
tail -f /var/lib/proxysql/proxysql.log
```

### Создание служебного пользователя в MySQL/MariaDB

ProxySQL требует отдельного пользователя для подключения к узлам БД. Этот пользователь используется монитором и роутером.

```sql
-- Выполните на каждом узле MySQL/MariaDB
CREATE USER 'proxysql_user'@'%' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
GRANT SELECT, PROCESS, REPLICATION CLIENT, RELOAD, SUPER ON *.* TO 'proxysql_user'@'%';
FLUSH PRIVILEGES;
```

**Объяснение привилегий:**
- `SELECT, PROCESS` — мониторинг состояния сервера (`SHOW STATUS`, `SHOW PROCESSLIST`).
- `REPLICATION CLIENT` — проверка статуса репликации (`SHOW REPLICA STATUS`).
- `RELOAD` — перезагрузка данных (`FLUSH LOGS`).
- `SUPER` — управление переменными (для `read_only` и т.д.).

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
- `apply` — `1` =停止 обработку further rules после совпадения, `0` = продолжить проверку.

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

Встроенное кэширование результатов запросов для снижения нагрузки на БД.

```sql
-- Включение кэширования
UPDATE global_variables SET variable_value='256'
WHERE variable_name='mysql-server_capabilities';

-- Настройка TTL кэша (в миллисекундах)
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, cache_ttl, apply)
VALUES (20, 1, '^SELECT .* FROM products WHERE category_id = .*', 30000, 1);

-- Кэширование результатов запросов к справочнику (TTL 5 минут)
INSERT INTO mysql_query_rules (rule_id, active, match_pattern, cache_ttl, apply)
VALUES (21, 1, '^SELECT .* FROM reference_data.*', 300000, 1);

LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

**Объяснение:**
- `cache_ttl` — время жизни кэша в миллисекундах. `0` = кэширование отключено.
- Кэш автоматически инвалидируется при записи в связанные таблицы (на уровне digest).
- Запросы с волатильными функциями (`NOW()`, `RAND()`, `UUID()`) не кэшируются.
- Кэш разделяется между всеми потоками ProxySQL.

**Проверка статистики кэша:**

```sql
SELECT * FROM stats_mysql_query_digest WHERE cache_hit_count > 0;
```

### 4. Интеграция с Orchestrator: Нативная поддержка

С 2026 года Orchestrator поддерживает нативную интеграцию с ProxySQL (**Hook-less integration**) без использования внешних скриптов. Orchestrator может напрямую обновлять Hostgroups в ProxySQL при failover.

#### Конфигурация Orchestrator

```json
{
  "ProxySQLHostgroupsMapping": {
    "WriterHostgroup": 10,
    "ReaderHostgroup": 20,
    "Default": 10
  },
  "PostMasterFailoverProcesses": [
    "proxysql-admin --update-server-list --group=10 --host={successorHost}"
  ],
  "PostFailoverProcesses": [
    "proxysql-admin --reload-config"
  ]
}
```

#### Настройка ProxySQL для работы с Orchestrator

```sql
-- Группы хостов должны соответствовать конфигурации Orchestrator
-- Writer (мастер) — группа 10
-- Reader (реплики) — группа 20

-- Orchestrator будет автоматически обновлять таблицу mysql_servers
-- при изменении топологии (failover, switchover)

-- Проверка текущей конфигурации
SELECT hostgroup_id, hostname, port, status FROM mysql_servers;
```

**Как это работает:**
1. Orchestrator обнаруживает падение мастера.
2. Определяет наиболее подходящую реплику для повышения.
3. Выполняет failover на уровне MySQL (повышает реплику).
4. Нативно обновляет ProxySQL: переносит новый мастер в группу 10 (writer), остальные реплики — в группу 20 (reader).
5. ProxySQL мгновенно начинает маршрутизировать запись на новый мастер.

**Важно:** Для корректной работы необходим GTID-репликация. Orchestrator не будет повышать реплику с большим лагом или без GTID.

### 5. Мониторинг через Prometheus

ProxySQL предоставляет встроенный HTTP-сервер для экспозиции метрик. Для сбора метрик ProxySQL рекомендуется использовать **proxysql-exporter** (на базе prometheus/client_golang).

#### Включение встроенного мониторинга

```sql
-- Включение статистики
UPDATE global_variables SET variable_value='true'
WHERE variable_name='mysql-eventslog_enabled';

-- Интервал обновления статистики (в миллисекундах)
UPDATE global_variables SET variable_value='2000'
WHERE variable_name='mysql-stats_update_delay';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

#### Настройка Prometheus scrape

```yaml
scrape_configs:
  - job_name: 'proxysql'
    static_configs:
      - targets: ['proxysql-host:6033']
    metrics_path: '/metrics'
    # proxysql-exporter слушает на отдельном порту
    # Пример: proxysql-exporter --web.listen-address=":42004"
```

#### Ключевые метрики для мониторинга

| Метрика | Описание | Типичный порог |
| :--- | :--- | :--- |
| `proxysql_connection_pool_status` | Статус пула соединений (0=каLK, 1=active) | Все соединения должны быть в статусе OK |
| `proxysql_queries_total` | Общее количество запросов | Мониторинг распределения по hostgroup |
| `proxysql_query_duration_seconds` | Время выполнения запросов | p99 > 100ms = проблема |
| `proxysql_backend_query_duration_seconds` | Задержка запросов к бэкенд-серверам | Рост = проблемы на стороне БД |
| `proxysql_cache_hit_ratio` | Коэффициент попаданий в кэш | < 0.5 = кэш неэффективен |
| `proxysql_connection_poolConnOK` | Успешные подключения к бэкендам | Рост = проблемы с сетью |
| `proxysql_connection_poolConnERR` | Ошибки подключения к бэкендам | > 0 = проверьте доступность серверов |
| `proxysql_mysql_monitor_theme_up` | Доступность серверов (1=up, 0=down) | 0 = сервер недоступен |

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

ProxySQL предоставляет丰富的 набор таблиц для управления и мониторинга:

#### Таблицы конфигурации

| Таблица | Назначение |
| :--- | :--- |
| `mysql_servers` | Серверы БД и их принадлежность к группам |
| `mysql_users` | Пользователи ProxySQL (для подключения приложений) |
| `mysql_query_rules` | Правила маршрутизации запросов |
| `mysql_server_hostgroup` | Маппинг серверов на группы хостов |
| `global_variables` | Глобальные переменные конфигурации |
| `mysql_replication_hostgroup` | Автоматическое определение master/slave для групп |

#### Таблицы статистики

| Таблица | Назначение |
| :--- | :--- |
| `stats_mysql_query_digest` | Статистика запросов по digest (количество, время, группа) |
| `stats_mysql_connection_pool` | Статистика пула соединений по серверам |
| `stats_mysql_backend` | Статистика по бэкенд-серверам |
| `stats_mysql_global` | Глобальные счетчики ProxySQL |

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
-- Настройка автоматического переключения групп
INSERT INTO mysql_replication_hostgroups (writer_hostgroup, reader_hostgroup, check_type)
VALUES (10, 20, 'read_only');

LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

**Как это работает:**
- ProxySQL опрашивает все серверы в группе writer (10) и reader (20).
- Если сервер в группе writer имеет `read_only=ON`, он автоматически перемещается в группу reader.
- Если сервер в группе reader имеет `read_only=OFF`, он автоматически перемещается в группу writer.
- Это обеспечивает автоматическую маршрутизацию при `switchover` (плановом переключении).

---

## Best Practices

### Архитектурные рекомендации

1.  **Высокая доступность прокси:** Никогда не используйте один инстанс ProxySQL. Разворачивайте минимум два узла в связке с **Keepalived (VRRP)** для плавающего VIP. Это исключает single point of failure на уровне прокси.
2.  **Изоляция ресурсов:** Размещайте ProxySQL на отдельных виртуальных машинах или контейнерах. При высокой нагрузке ProxySQL потребляет значительные ресурсы CPU и памяти.
3.  **GTID-репликация:** Используйте GTID для корректной работы автоматического определения топологии и интеграции с Orchestrator.

### Конфигурация

4.  **`mysql-monitor_connect_interval`:** Стандартное значение — 2000ms. Для критичных систем можно уменьшить до 1000ms, но это увеличивает нагрузку на серверы. Не рекомендуется ставить менее 500ms.
5.  **`mysql-monitor_ping_interval`:** Интервал пинга серверов. Рекомендуется 1000-2000ms.
6.  **`max_connections` на серверах:** Задавайте `max_connections` на сервере БД выше, чем сумма `max_connections` всех прокси, чтобы не исчерпать лимит.
7.  **`default_hostgroup`:** Всегда задавайте `default_hostgroup` для пользователей, чтобы избежать маршрутизации по умолчанию на writer-группу.
8.  **Приоритет правил:** Правила применяются по возрастанию `rule_id`. Специфичные правила (например, `SELECT FOR UPDATE`) должны иметь более низкий `rule_id`, чем общие правила (`SELECT`).

### Безопасность

9.  **Смена пароля Admin:** По умолчанию пароль Admin-интерфейса — `admin`. Обязательно смените его в продакшене.
10. **Ограничение доступа:** Привяжите Admin-интерфейс к конкретному IP (`admin-mysql_ifaces` в `global_variables`).
11. **Шифрование соединений:** Включите SSL/TLS для соединений между ProxySQL и клиентами, а также между ProxySQL и серверами БД.

### Мониторинг и алертинг

12. **Настройте алерты:** Мониторьте `proxysql_backend_query_duration_seconds` (задержка запросов) и `proxysql_connection_poolConnERR` (ошибки подключения).
13. **Ротация логов:** Настройте ротацию логов ProxySQL для предотвращения заполнения диска.
14. **Регулярно проверяйте `stats_mysql_connection_pool`:** Убедитесь, что все серверы в статусе OK.

---

## Граничные случаи и ограничения

### Известные ограничения

1.  **Транзакции и Read/Write Split:** Если транзакция начинается с `SELECT` (автоматическое чтение на реплике), а затем выполняется `UPDATE`, ProxySQL перенаправит `UPDATE` на мастер. Однако, если соединение уже привязано к реплике через Multiplexing, `UPDATE` может завершиться ошибкой. Используйте `SELECT ... FOR UPDATE` для гарантии направления на мастер.
2.  **Временные таблицы:** Временные таблицы видны только в пределах одной сессии. При переключении соединения между серверами временные таблицы теряются. ProxySQL отключает Multiplexing для соединений с временными таблицами.
3.  **Пользовательские переменные:** Переменные типа `@variable` не маршрутизируются и могут привести к некорректному поведению при переключении серверов. Минимизируйте их использование.
4.  **Prepared Statements:** В некоторых сценариях prepared statements могут работать некорректно при переключении между мастером и репликой. ProxySQL требует установленного флага `MYSQL_FORWARD_STMT` для поддержки prepared statements через прокси.
5.  **Глобальные блокировки:** `LOCK TABLES`, `FLUSH TABLES WITH READ LOCK` могут конфликтовать с работой роутера и вызывать зависания.
6.  **Одновременные транзакции:** ProxySQL не поддерживает маршрутизацию внутри одной транзакции на несколько серверов. Все операции в рамках одной транзакции направляются на один сервер.

### Нестандартные сценарии

*   **Смешанные MySQL + MariaDB:** ProxySQL поддерживает оба движка, но некоторые функции (например, GTID) могут работать по-разному. Рекомендуется использовать однородный стек.
*   **Каскадная репликация:** ProxySQL не поддерживает проксирование каскадной репликации (Replica → Replica). Все реплики должны быть подключены напрямую к мастеру.
*   **Большое количество баз данных:** При большом количестве баз данных необходимо настраивать правила маршрутизации по регулярным выражениям для конкретных схем.

---

## Устранение неполадок (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Error 1105: ProxySQL Error: no viable nodes in hostgroup` | Все серверы в группе помечены как `OFFLINE` или `SHUNNED`. | Проверьте таблицу `runtime_mysql_servers` и логи здоровья (таблица `monitor.mysql_server_connect_log`). Убедитесь, что мониторинг работает корректно. |
| Запросы не кэшируются | Отсутствие правила с `cache_ttl` или запрос содержит волатильные функции (NOW, RAND). | Добавьте правило с `cache_ttl > 0` для конкретного `digest`. Проверьте, что запрос не содержит волатильных функций. |
| Высокий Latency | Отключен Multiplexing из-за использования `@variables` или временных таблиц. | Минимизируйте использование пользовательских переменных в сессии приложения. Проверьте `stats_mysql_query_digest` для поиска медленных запросов. |
| `Connection refused` (клиент не может подключиться) | ProxySQL не запущен или слушает другой интерфейс/порт. | Проверьте статус службы: `systemctl status proxysql`. Проверьте `mysql-interface` в `global_variables`. |
| Запросы идут не в ту группу хостов | Неправильный приоритет правил или отсутствие `apply=1`. | Проверьте `rule_id` правил: они применяются по возрастанию. Убедитесь, что специфичные правила имеют более низкий `rule_id`, чем общие. |
| `Access denied for user` (ошибка подключения к БД) | Неверные credentials в `mysql_users` или пользователь не создан на сервере БД. | Проверьте таблицу `mysql_users`. Убедитесь, что пользователь создан на всех серверах MySQL/MariaDB. |
| Соединения с серверами БД не устанавливаются | `max_connections` на сервере БД исчерпан или firewall блокирует порт. | Увеличьте `max_connections` на сервере БД. Проверьте firewall и сетевую доступность. |
| Запросы кэшируются некорректно | Кэш не инвалидируется при записи или TTL слишком большой. | Проверьте, что ProxySQL отслеживает digest для инвалидации кэша. Уменьшите `cache_ttl` для динамических данных. |
| Orchestrator не обновляет ProxySQL | Отсутствует нативная интеграция или неверная конфигурация групп. | Убедитесь, что `ProxySQLNativeIntegration=true` в конфигурации Orchestrator. Проверьте соответствие `WriterHostgroup`/`ReaderHostgroup`. |
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
| **Интеграция с Orchestrator** | Нативная (с 2026 года) | Нет (использует свой Failover) |

---

## Дополнительная информация

### См. также
- **[Обзор MariaDB MaxScale](../../MariaDB/MaxScale/maxscale_overview.md)** — альтернатива для экосистемы MariaDB.
- **[Репликация MySQL: Обзор](../replication/overview.md)** — основа для настройки групп хостов.
- **[Мониторинг баз данных](../monitoring.md)** — интеграция метрик ProxySQL в Prometheus.
- **[Orchestrator: Управление топологией](../orchestrator.md)** — автоматизация failover и интеграция с ProxySQL.
