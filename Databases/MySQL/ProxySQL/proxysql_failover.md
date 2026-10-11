# ProxySQL: Failover и мониторинг репликации

**Актуально для:** ProxySQL 3.0.x

## Определения

| Термин | Значение |
| :--- | :--- |
| **`mysql_replication_hostgroups`** | Таблица для **асинхронной репликации**: задаёт пары hostgroups для автоматического определения writer/reader. Колонки: `writer_hostgroup`, `reader_hostgroup`, `check_type`, `comment` |
| **`check_type`** | Метод определения роли сервера. Допустимые значения в 3.0.11: `innodb_read_only`, `super_read_only`, `read_only\|innodb_read_only`, `read_only&innodb_read_only` |
| **`mysql_galera_hostgroups`** | Отдельная таблица для Galera. Колонки: `writer_hostgroup`, `backup_writer_hostgroup`, `reader_hostgroup`, `offline_hostgroup`, `active`, `max_writers`, `writer_is_also_reader`, `max_transactions_behind`, `comment` |
| **`mysql_group_replication_hostgroups`** | Отдельная таблица для Group Replication. Схема идентична `mysql_galera_hostgroups` |
| **SHUNNED** | Временное состояние соединения пула, при котором сервер исключён из роутинга после серии неудачных проверок |
| **Replication Lag** | Отставание реплики от primary; измеряется через `SHOW REPLICA STATUS` на самом бэкенде |
| **`max_replication_lag`** | Порог допустимого отставания **в секундах**. Это колонка таблицы `mysql_servers` (на каждый сервер), а не колонка `mysql_replication_hostgroups` |
| **`max_transactions_behind`** | Порог отставания в транзакциях; применяется только в `mysql_galera_hostgroups` и `mysql_group_replication_hostgroups` |
| **Heartbeat** | Периодическая запись в таблицу базы данных, позволяющая измерить лаг без доступа к репликационным протоколам |
| **Switchover** | Плановое переключение ролей primary/replica |
| **Failover** | Аварийное переключение ролей с автоматическим выбором нового primary |

## Теоретический блок

### Главное ограничение: автоматического failover в ProxySQL нет

Это наиболее часто неверно понимаемый момент. ProxySQL **не умеет сам повышать реплику до primary**.

В актуальных версиях отсутствуют переменные `mysql-failover`, `mysql-servers_new_hostgroup_id`, `mysql-replication_wait_timeout` и `mysql-monitor_failover_*`, которые присутствовали в ProxySQL 1.x. Их отсутствие означает:

> ProxySQL умеет **реагировать** на изменение ролей, но **не выполняет** само переключение ролей.

Распределение ответственности:

| Задача | Кто выполняет |
| :--- | :--- |
| Повысить реплику до primary | Внешний инструмент: Orchestrator, MHA, Patroni, ручное `FAILOVER` |
| Определить, кто теперь writer | ProxySQL: монитор через `read_only` |
| Перенести сервер в hostgroup writer | ProxySQL: `mysql_replication_hostgroups` |
| Исключить неисправный сервер | ProxySQL: SHUNNED или статус в `mysql_servers` |
| Обновить hostgroups после failover | Orchestrator (нативная секция `ProxySQL`) |

Это разделение ответственности осознанное: выбор кандидата на повышение — задача с пониманием семантики данных, которую прокси-уровень решать не должен.

### Механизм `mysql_replication_hostgroups`

Таблица задаёт **пары** hostgroups. ProxySQL опрашивает серверы в обеих группах и меняет их членство по результатам.

Схема таблицы в 3.0.11 — всего четыре колонки:

```sql
-- Актуальная схема (include/ProxySQL_Admin_Tables_Definitions.h)
-- writer_hostgroup INT NOT NULL PRIMARY KEY
-- reader_hostgroup INT NOT NULL (reader_hostgroup <> writer_hostgroup AND reader_hostgroup > 0)
-- check_type VARCHAR WITH CHECK (... допустимые значения ...)
-- comment VARCHAR
```

Пороги лага **не являются колонками этой таблицы**. Допустимые значения `check_type` заданы CHECK-ограничением на уровне схемы, и в 3.0.11 их ровно четыре:

| `check_type` | Условие «сервер является writer» |
| :--- | :--- |
| `super_read_only` | `super_read_only = OFF` |
| `innodb_read_only` | `innodb_read_only = OFF` |
| `read_only\|innodb_read_only` | хотя бы одна из переменных равна `OFF` |
| `read_only&innodb_read_only` | обе переменные равны `OFF` |

> **Важно для 3.0.x:** CHECK-ограничение схемы допускает все пять значений, и `read_only` — не исключение. Он является **значением по умолчанию** (`DEFAULT 'read_only'`) и полностью рабочий в 3.0.x. Если вы переносите конфигурацию с 2.x — заменять его **не требуется**. Единственное различие: в 3.0.x схема строго типизирована, и значение `read_only` (как и любое другее) должно указываться явно; CHECK-ограничение отклонит опечатки и несуществующие значения, но корректный `read_only` проходит. Для MySQL 8.0+ предпочтительнее `super_read_only` — он является надмножеством `read_only` и учитывает обе переменные одновременно.

```sql
INSERT INTO mysql_replication_hostgroups (writer_hostgroup, reader_hostgroup, check_type)
VALUES
  (10, 20, 'super_read_only'),
  (30, 40, 'super_read_only');
```

**Логика обработки:** сервер из writer-группы, у которого переменная из `check_type` равна `ON`, переносится в reader-группу. Сервер из reader-группы с `OFF` переносится в writer-группу. Это обеспечивает смену маршрутизации при switchover **без** внешних инструментов — но только если смену ролей уже выполнил кто-то другой.

### Порог лага: `mysql_servers.max_replication_lag`

Порог допустимого отставания задаётся **per-server** в таблице `mysql_servers`, а не в `mysql_replication_hostgroups`:

```sql
UPDATE mysql_servers SET max_replication_lag = 30
WHERE hostgroup_id = 20 AND hostname = 'replica-1.example.com';

LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

| Колонка `mysql_servers` | Единица | Смысл |
| :--- | :--- | :--- |
| `max_replication_lag` | Секунды | Если лаг сервера превышает порог, сервер не переносится в writer-группу даже при `read_only = OFF` |
| `max_transactions_behind` | Транзакции | Аналогичный порог, но только для Galera/GR (в `mysql_galera_hostgroups` / `mysql_group_replication_hostgroups`) |
| `max_latency_ms` | Миллисекунды | Порог задержки пинга до сервера |
| `max_connections` | Соединения | Максимум соединений пула к этому серверу |

Значение `0` означает «порог не задан, лаг не проверяется». Если лаг проверять нужно, monitor-юзеру требуется привилегия `REPLICATION CLIENT`.

> **ProxySQL не отдаёт фактический лаг через admin-команды и метрики.** Ни одна команда `SHOW` и ни одна Prometheus-метрика лага не содержат. Но значение, измеренное монитором, сохраняется в колонке `repl_lag` журнала `monitor.mysql_server_replication_lag_log` — см. [Как прочитать измеренный лаг](#как-прочитать-измеренный-лаг). Для постоянного мониторинга лага правильнее опрашивать бэкенд напрямую.

### Монитор: что и как он проверяет

Monitor — отдельный модуль, выполняющий фоновые проверки по расписанию.

| Переменная | По умолчанию | Смысл |
| :--- | :--- | :--- |
| `mysql-monitor_connect_interval` | `120000` | Интервал проверки доступности, мс |
| `mysql-monitor_connect_timeout` | `200` | Таймаут установки соединения, мс |
| `mysql-monitor_ping_interval` | `8000` | Интервал ping-проверки, мс |
| `mysql-monitor_ping_max_failures` | `3` | Число неудач до исключения сервера |
| `mysql-monitor_ping_timeout` | `1000` | Таймаут ping, мс |
| `mysql-monitor_read_only_interval` | `1000` | Интервал проверки `read_only`, мс |
| `mysql-monitor_read_only_timeout` | `800` | Таймаут проверки `read_only`, мс |
| `mysql-monitor_replication_lag_interval` | `10000` | Интервал проверки лага, мс |
| `mysql-monitor_replication_lag_timeout` | `1000` | Таймаут проверки лага, мс |
| `mysql-monitor_history` | `600000` | Глубина истории проверок, мс (600000 мс = 60 секунд) |
| `mysql-monitor_writer_is_also_reader` | `true` | Считать ли writer'а также reader'ом |
| `mysql-monitor_wait_timeout` | `true` | Учитывать ли `wait_timeout` при проверке соединения |
| `mysql-monitor_replication_lag_count` | `1` | Сколько подряд проверок лага с превышением порога должно быть, чтобы сервер был SHUNNED (3.0.x) |
| `mysql-monitor_replication_lag_use_percona_heartbeat` | *(пусто)* | Если задано (например, `percona.heartbeat`), лаг измеряется по таблице pt-heartbeat вместо `SHOW REPLICA STATUS` |
| `mysql-monitor_read_only_max_timeout_count` | `3` | Сколько подряд таймаутов проверки `read_only` должно быть, чтобы считать сервер `read_only=1` (3.0.x) |
| `mysql-monitor_threads_max` | `128` | Максимум потоков пула монитора |
| `mysql-monitor_threads_min` | `8` | Минимум потоков пула монитора |

**Значения по умолчанию противоречат интуиции:** `connect_interval = 120000` означает, что недоступность сервера может быть не замечена **до двух минут**. Для критичных систем это слишком долго. Аналогично `mysql-monitor_history = 600000` (60 секунд) — история проверок хранится всего на минуту, после чего старые записи удаляются.

### Учётные данные монитора

Отдельный пользователь в переменных `mysql-monitor_username` / `mysql-monitor_password`.

**Ограничение ProxySQL: пользователь монитора не может быть указан в таблице `mysql_users`.** Это разные роли — монитор подключается сам, а `mysql_users` описывает клиентов, которым ProxySQL проксирует соединения.

Минимальные привилегии:

```sql
CREATE USER 'monitor'@'%' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
GRANT USAGE ON *.* TO 'monitor'@'%';

-- Требуется только при мониторинге лага репликации
GRANT REPLICATION CLIENT ON *.* TO 'monitor'@'%';
FLUSH PRIVILEGES;
```

### SHUNNED: состояние соединения пула

SHUNNED — это **не** статус сервера в `mysql_servers`, а состояние отдельных соединений пула.

**Механика:** при `mysql-monitor_ping_max_failures` неудачных проверках подряд монитор переводит соединения пула к этому серверу в `SHUNNED`. Они исключаются из роутинга, но **не удаляются** — при восстановлении доступности возвращаются в работу.

| Параметр | По умолчанию | Смысл |
| :--- | :--- | :--- |
| `mysql-shun_on_failures` | `5` | Число неудачных попыток соединения до перевода в SHUNNED |
| `mysql-shun_recovery_time_sec` | `10` | Пауза перед попыткой восстановления, секунды |
| `mysql-unshun_algorithm` | `0` | Стратегия выхода из SHUNNED |

**Переопределение для конкретного сервера задаётся не глобальными переменными, а колонками таблицы `mysql_servers`:** `max_connections`, `max_replication_lag`, `max_latency_ms`, `weight`, `compression`, `use_ssl`, `gtid_port`. Переменных вида `mysql-server_max_connections_timeout` или `mysql-server_shun_recovery_time_sec` в 3.0.11 нет — если встретили их в руководстве, это устаревшая схема.

**Значение `mysql-shun_on_failures` по умолчанию — `5`, а не `3`:** порог из `ping_max_failures` применяется к ping-проверкам, а `shun_on_failures` — к неудачным попыткам соединения. Это разные счётчики.

**`mysql-unshun_algorithm`:** `0` — попытка восстановления через равные интервалы; `1` — экспоненциально увеличивающиеся интервалы (меньше нагрузки на действительно упавший сервер). Для нагруженных систем разумно значение `1`.

### Проверка лага репликации

Есть два принципиально разных способа, и это важное различие.

#### Способ 1: через `SHOW REPLICA STATUS`

Monitor подключается к серверу и выполняет `SHOW REPLICA STATUS`, читая `Seconds_Behind_Source`. Требует привилегии `REPLICATION CLIENT`.

**Ограничения:**
- блокирует операции репликационного потока на время проверки;
- нагружает сервер при частом интервале;
- **`Seconds_Behind_Source` может показывать `NULL`**, если поток репликации остановлен или работает в параллельном режиме без корректного отчёта.

Значение `NULL` по умолчанию трактуется как `mysql-monitor_slave_lag_when_null` (по умолчанию `60` секунд).

#### Способ 2: через heartbeat-таблицу

На сервере создаётся таблица, в которую с заданной периодичностью пишется строка. Приложение или сам бэкенд обновляет её; монитор измеряет задержку по `NOW()`.

```sql
CREATE TABLE heartbeat (
  id INT NOT NULL PRIMARY KEY,
  ts BIGINT NOT NULL
) ENGINE=InnoDB;

CREATE USER 'hbwriter'@'%' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
GRANT INSERT, UPDATE ON heartbeatdb.heartbeat TO 'hbwriter'@'%';

-- Автоматическая запись каждые 1 секунду
CREATE EVENT ev_hb ON SCHEDULE EVERY 1 SECOND DO
  UPDATE heartbeat SET ts = UNIX_TIMESTAMP() WHERE id = 1;
```

**Преимущество:** измеряется реальная задержка данных, а не состояние репликационного протокола. Работает при параллельной репликации.

**Недостаток:** требует настройки на каждом сервере и работает только для схем, проходящих через heartbeat.

### Galera Cluster

В 3.0.x Galera настраивается **отдельной таблицей** `mysql_galera_hostgroups`, а не через `check_type` в `mysql_replication_hostgroups`. Колонки `check_type` и `max_wsrep_lag` в схеме 3.0.11 отсутствуют.

```sql
INSERT INTO mysql_galera_hostgroups
  (writer_hostgroup, backup_writer_hostgroup, reader_hostgroup,
   offline_hostgroup, active, max_writers,
   writer_is_also_reader, max_transactions_behind, comment)
VALUES
  (10, 11, 20, 30, 1, 1, 1, 5, 'galera prod');
```

| Колонка | Смысл |
| :--- | :--- |
| `writer_hostgroup` | Hostgroup для текущего writer |
| `backup_writer_hostgroup` | Hostgroup для второго кандидата в writer |
| `reader_hostgroup` | Hostgroup для read-only нод |
| `offline_hostgroup` | Hostgroup для нод, исключённых из кластера |
| `active` | Включает ли механизм работу этой записи (`1`/`0`) |
| `max_writers` | Сколько нод одновременно считаются writer |
| `writer_is_also_reader` | Считать ли writer также доступной для чтения (`1`/`0`) |
| `max_transactions_behind` | Допустимое отставание в транзакциях |

Монитор определяет состояние ноды по переменным `wsrep_*`:

| Переменная | Смысл |
| :--- | :--- |
| `wsrep_local_state_comment` | Состояние ноды (`Primary`, `Synced`, `Donor/Desynced`, `Joiner`) |
| `wsrep_ready` | Готова ли нода принимать трафик |
| `wsrep_cluster_status` | Статус кластера в целом |
| `wsrep_local_recv_queue_avg` | Средняя длина приёмной очереди |

Ноды в состояниях `Desynced`/`Donor` или с `wsrep_ready = OFF` автоматически уходят в `offline_hostgroup`, то есть в состояние `SHUNNED` применительно к соединениям пула. Именно поэтому в Galera-схеме есть `offline_hostgroup`, а в схеме асинхронной репликации (`mysql_replication_hostgroups`) его нет: там при потере связи сервер просто исключается из роутинга по неудачным пингам.

### Group Replication

Group Replication использует **собственную таблицу** `mysql_group_replication_hostgroups` со схемой, идентичной `mysql_galera_hostgroups` (те же девять колонок). Это позволяет задавать `max_writers > 1` — то есть мульти-primary на уровне кластера, что для асинхронной репликации через `mysql_replication_hostgroups` невозможно.

```sql
INSERT INTO mysql_group_replication_hostgroups
  (writer_hostgroup, backup_writer_hostgroup, reader_hostgroup,
   offline_hostgroup, active, max_writers,
   writer_is_also_reader, max_transactions_behind, comment)
VALUES
  (10, 11, 20, 30, 1, 1, 1, 5, 'GR single-primary');
```

Роль ноды определяется явно, а не через `read_only`:

| Переменная | Смысл |
| :--- | :--- |
| `group_replication_primary_role` | Роль ноды: `PRIMARY` или `SECONDARY` |
| `group_replication_local_member_state` | Состояние ноды в группе (`ONLINE`, `RECOVERING`, `OFFLINE` и т.д.) |
| `group_replication_members` | Состав группы |
| `group_replication_transactions_behind` | Отставание в транзакциях (для `max_transactions_behind`) |

**Мульти-primary (`max_writers > 1`):** при значении больше 1 ProxySQL распределяет записи по нескольким writer-hostgroups. Это нужно учитывать при проектировании: конфликтующие транзакции разрешаются средствами самой Group Replication (сертификаты), а ProxySQL лишь маршрутизирует. Практически мульти-primary в MySQL применяют редко, и перед его включением следует прочитать ограничения дедлоков и когерентности в документации Group Replication.

### Интеграция с Orchestrator

Orchestrator выполняет MySQL-failover и сообщает ProxySQL об изменившейся топологии через нативную секцию `ProxySQL`.

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

**GTID не обязателен:** Orchestrator поддерживает GTID, pseudo-GTID и file-based репликацию.

Полная настройка — в [ProxySQL: Обзор](./proxysql_overview.md), механизм синхронизации между узлами — в [ProxySQL: HA и ProxySQL Cluster](./proxysql_ha_cluster.md).

## Практический блок

### Базовая настройка read/write split с контролем лага

**Предусловия:**
- primary в hostgroup `10`, реплики в hostgroup `20`;
- пользователь монитора создан и имеет `REPLICATION CLIENT`;
- `max_replication_lag` задан осмысленно.

```sql
-- 1. Пользователь монитора
UPDATE global_variables SET variable_value = 'monitor'
WHERE variable_name = 'mysql-monitor_username';

UPDATE global_variables SET variable_value = 'СЛОЖНЫЙ_ПАРОЛЬ'
WHERE variable_name = 'mysql-monitor_password';

-- 2. Более частые проверки, чем по умолчанию
UPDATE global_variables SET variable_value = '10000'
WHERE variable_name = 'mysql-monitor_connect_interval';

UPDATE global_variables SET variable_value = '2000'
WHERE variable_name = 'mysql-monitor_ping_interval';

UPDATE global_variables SET variable_value = '5000'
WHERE variable_name = 'mysql-monitor_replication_lag_interval';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;

-- 3. Пары hostgroups + порог лага на каждом сервере
INSERT INTO mysql_replication_hostgroups (writer_hostgroup, reader_hostgroup, check_type)
VALUES (10, 20, 'super_read_only');

UPDATE mysql_servers SET max_replication_lag = 30
WHERE hostgroup_id = 20 AND hostname = 'replica-1.example.com';

LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;

-- 4. Пользователи
INSERT INTO mysql_users (username, default_hostgroup, transaction_persistent)
VALUES ('app_reader', 20, 0),
       ('app_writer', 10, 0);
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

**Проверка:**

```sql
-- Пары hostgroups в runtime: только 4 колонки, порога лага здесь нет
SELECT writer_hostgroup, reader_hostgroup, check_type, comment
FROM runtime_mysql_replication_hostgroups;
# → writer_hostgroup | reader_hostgroup | check_type | comment
# → 10               | 20                | super_read_only |

-- Порог лага живёт в mysql_servers
SELECT hostgroup_id, hostname, max_replication_lag, max_latency_ms
FROM runtime_mysql_servers
WHERE hostgroup_id IN (10, 20);
# → hostgroup_id | hostname            | max_replication_lag | max_latency_ms
# → 20           | replica-1.example.com | 30                  | 500
```

> **Проверить фактический лаг через ProxySQL нельзя** — он используется только для сравнения с порогом. Запрос идёт напрямую на бэкенд:
>
> ```sql
> -- на самом replica, а не через admin-интерфейс ProxySQL
> SHOW REPLICA STATUS\G
> -- MySQL 5.7 / MariaDB:
> -- SHOW SLAVE STATUS\G
> ```

### Проверка состояния серверов

```sql
-- Текущий статус серверов
SELECT hostgroup_id, hostname, port, status, max_connections, weight
FROM runtime_mysql_servers ORDER BY hostgroup_id;
# → hostgroup_id | hostname      | port | status   | max_connections | weight
# → 10           | db-primary-1  | 3306 | ONLINE   | 500             | 1000
# → 20           | db-replica-1  | 3306 | ONLINE   | 400             | 1000
# → 20           | db-replica-2  | 3306 | ONLINE   | 400             | 1000

-- Состояние соединений пула: кто SHUNNED
SELECT hostgroup, srv_host, srv_port, status, ConnUsed, ConnFree, ConnERR
FROM stats_mysql_connection_pool ORDER BY hostgroup, srv_host;
# → hostgroup | srv_host     | status  | ConnUsed | ConnFree | ConnERR
# → 20        | db-replica-1 | ONLINE  | 198      | 2        | 0
# → 20        | db-replica-2 | SHUNNED | 0        | 0        | 0
```

### Диагностика через логи монитора

Monitor ведёт собственный журнал, независимый от основного лога ProxySQL:

```sql
-- Журнал подключений монитора
SELECT time_start_us, endpoint, success, err, srv_addr, srv_port,
       (time_start_us - time_start) / 1000000 AS duration_sec
FROM monitor.mysql_server_connect_log
ORDER BY time_start_us DESC
LIMIT 20;
# → time_start_us | endpoint        | success | err  | srv_addr      | srv_port
# → 1772841600000000 | 127.0.0.1:6032 | 1       | 0   | 10.0.1.21    | 3306
# → 1772841599000000 | 127.0.0.1:6032 | 0       | 110 | 10.0.1.22    | 3306
# → time_start_us | endpoint        | success | err  | srv_addr      | srv_port
# → 1772841598000000 | 127.0.0.1:6032 | 1       | 0   | 10.0.1.21    | 3306

-- Жournal ping-проверок
SELECT time_start_us, hostname, port, ping_success_time_us, ping_error
FROM monitor.mysql_server_ping_log
ORDER BY time_start_us DESC
LIMIT 20;

-- Журнал проверок read_only
SELECT time_start_us, hostname, port, read_only, error
FROM monitor.mysql_server_read_only_log
ORDER BY time_start_us DESC
LIMIT 20;
# → hostname  | port | read_only
# → 10.0.1.21 | 3306 | 0
# → 10.0.1.22 | 3306 | 1
```

**Код `110` в колонке `error` — истечение таймаута.** Если он повторяется для конкретного сервера, проблема в сетевой доступности или перегрузке бэкенда.

#### Схемы monitor-логов

Приведены по `include/MySQL_Monitor.hpp` (ProxySQL 3.0.11). База данных — `monitor`.

| Таблица | Колонки |
| :--- | :--- |
| `mysql_server_connect_log` | `hostname`, `port`, `time_start_us`, `connect_success_time_us`, `connect_error` |
| `mysql_server_ping_log` | `hostname`, `port`, `time_start_us`, `ping_success_time_us`, `ping_error` |
| `mysql_server_read_only_log` | `hostname`, `port`, `time_start_us`, `success_time_us`, `read_only`, `error` |
| `mysql_server_replication_lag_log` | `hostname`, `port`, `time_start_us`, `success_time_us`, **`repl_lag`**, `error` |
| `mysql_server_galera_log` | `hostname`, `port`, `time_start_us`, `success_time_us`, `viable_candidate`, `read_only`, `transactions_behind`, `error` |
| `mysql_server_group_replication_log` | то же, что `mysql_server_galera_log` |

Три особенности, которые регулярно приводят к ошибкам в запросах:

1. Идентификаторы сервера — это `hostname` и `port`, а не `srv_addr`/`srv_port`.
2. Результат проверки лежит в колонке `error`; пустая строка означает успех, а не отсутствие данных.
3. Время — в **микросекундах** (`time_start_us`). Для секунд делите на 1000000 либо используйте `datetime(time_start_us / 1000000, 'unixepoch')`.

#### Как прочитать измеренный лаг

ProxySQL **измеряет** лаг и сохраняет его в колонке `repl_lag` журнала `mysql_server_replication_lag_log`. Он не отдаёт лаг через admin-команду `SHOW` и не экспортирует его метрикой, но значение доступно:

```sql
-- Лаг, измеренный при последней проверке каждого сервера
SELECT l.hostname, l.port, l.repl_lag,
       datetime(l.time_start_us / 1000000, 'unixepoch') AS checked_at
FROM monitor.mysql_server_replication_lag_log AS l
INNER JOIN (
  SELECT hostname, port, MAX(time_start_us) AS max_ts
  FROM monitor.mysql_server_replication_lag_log
  GROUP BY hostname, port
) AS latest
  ON latest.hostname = l.hostname
 AND latest.port = l.port
 AND latest.max_ts = l.time_start_us
ORDER BY l.hostname;
# → hostname  | port | repl_lag | checked_at
# → 10.0.1.21 | 3306 |        0 | 2026-10-03 14:20:11
# → 10.0.1.22 | 3306 |        3 | 2026-10-03 14:20:11
```

Ограничения этого способа: журнал пополняется только при `max_replication_lag > 0` (иначе проверка не выполняется вовсе), а старые записи удаляются по мере роста. Для регулярного мониторинга лага надёжнее опрашивать бэкенд напрямую через `SHOW REPLICA STATUS`.

### Ручной switchover

```sql
-- 1. Проверить текущее состояние
SELECT hostgroup_id, hostname, status FROM mysql_servers ORDER BY hostgroup_id;

-- 2. Убрать primary из роутинга записи заранее —
--    иначе клиенты продолжат писать в отключаемый узел
UPDATE mysql_servers SET status = 'OFFLINE_SOFT'
WHERE hostgroup_id = 10;
LOAD MYSQL SERVERS TO RUNTIME;

-- 3. Дождаться обнуления используемых соединений
SELECT hostgroup, srv_host, status, ConnUsed, ConnFree
FROM stats_mysql_connection_pool
WHERE hostgroup = 10;
# → status       | ConnUsed | ConnFree
# → OFFLINE_SOFT | 0        | 0

-- 4. Выполнить switchover на уровне MySQL:
--    STOP REPLICA IO_THREAD; STOP REPLICA SQL_THREAD;
--    RESET REPLICA ALL;
--    CHANGE MASTER TO ...;
--    START REPLICA;

-- 5. Вернуть узел в writer-группу
UPDATE mysql_servers SET status = 'ONLINE'
WHERE hostgroup_id = 10;
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

**Шаг 2 обязателен.** Если пропустить его, приложение продолжит писать на primary, который уже не является primary, и потеряет данные.

**Полезные команды на бэкенде для оценки лага:**

```sql
SHOW REPLICA STATUS\G
SELECT
  time_start_us, endpoint, success, err, srv_addr, srv_port, gtid_uuid
FROM monitor.mysql_replication_lag_log
ORDER BY time_start_us DESC LIMIT 10;
```

### Диагностика SHUNNED

```sql
-- 1. Кто в SHUNNED
SELECT hostgroup, srv_host, status FROM stats_mysql_connection_pool
WHERE status = 'shunned';

-- 2. Причина: смотреть журнал пинга
SELECT srv_addr, err, count(*) AS failures
FROM monitor.mysql_server_ping_log
WHERE success = 0
GROUP BY srv_addr, err
ORDER BY failures DESC;
# → srv_addr  | err | failures
# → 10.0.1.22 | 110 | 15

-- 3. Проверить параметры SHUNNED
SELECT variable_name, variable_value FROM global_variables
WHERE variable_name IN ('mysql-shun_on_failures',
                        'mysql-shun_recovery_time_sec',
                        'mysql-unshun_algorithm');
# → variable_name                | variable_value
# → mysql-shun_on_failures       | 5
# → mysql-shun_recovery_time_sec | 10
# → mysql-unshun_algorithm       | 0
```

### Ручной вывод сервера из SHUNNED

```bash
# Проверить фактическую доступность бэкенда с узла ProxySQL
mysql -h 10.0.1.22 -P 3306 -u monitor -p -e "SELECT 1"
# → 1
```

```sql
-- Если бэкенд доступен, но остаётся SHUNNED — сбросить состояние соединений
UPDATE mysql_servers SET status = 'ONLINE'
WHERE hostname = 'db-replica-2' AND port = 3306;
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

### Установка heartbeat для точного измерения лага

```sql
-- 1. На каждом бэкенде
CREATE DATABASE IF NOT EXISTS heartbeatdb;
CREATE TABLE heartbeatdb.heartbeat (
  id INT NOT NULL PRIMARY KEY,
  ts BIGINT NOT NULL
) ENGINE=InnoDB;

-- 2. Пользователь для записи heartbeat
CREATE USER 'hbwriter'@'%' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
GRANT INSERT, UPDATE ON heartbeatdb.heartbeat TO 'hbwriter'@'%';
FLUSH PRIVILEGES;

-- 3. Автоматическая запись каждую секунду
CREATE EVENT ev_hb ON SCHEDULE EVERY 1 SECOND DO
  UPDATE heartbeatdb.heartbeat SET ts = UNIX_TIMESTAMP() WHERE id = 1;
```

```sql
-- 4. На ProxySQL: регистрация heartbeat-пользователя
INSERT INTO mysql_users (username, default_hostgroup, transaction_persistent)
VALUES ('hbwriter', 0, 0);
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

**Проверка отставания вручную:**

```sql
-- Текущее время
SELECT UNIX_TIMESTAMP() AS now_ts;

-- Время последней записи heartbeat на каждом сервере
SELECT id, ts FROM heartbeatdb.heartbeat;
# → id | ts
# → 1  | 1772841600
```

Разница между этими значениями — задержка репликации в секундах.

### Galera: настройка hostgroups

```sql
-- Galera настраивается отдельной таблицей, без check_type
INSERT INTO mysql_galera_hostgroups
  (writer_hostgroup, backup_writer_hostgroup, reader_hostgroup,
   offline_hostgroup, active, max_writers,
   writer_is_also_reader, max_transactions_behind, comment)
VALUES (10, 11, 20, 30, 1, 1, 1, 5, 'galera prod');

LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

**Проверка состояния нод Galera на бэкенде:**

```sql
SHOW STATUS LIKE 'wsrep_local_state_comment';
# → Variable_name                      | Value
# → wsrep_local_state_comment          | Synced

SHOW STATUS LIKE 'wsrep_ready';
# → Value
# → ON

SHOW STATUS LIKE 'wsrep_local_recv_queue_avg';
# → Value
# → 0.000
```

```sql
-- Со стороны ProxySQL
SELECT hostgroup_id, hostname, status FROM mysql_servers ORDER BY hostname;
```

**Нода в состоянии `Desynced` или `Joiner` будет исключена из роутинга** автоматически, что предотвращает отправку запросов на ноду, формально находящуюся в кластере, но не готовую обслуживать трафик.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Failover не происходит | ProxySQL не повышает реплики сам | Разверните Orchestrator или аналог; см. [Orchestrator](../orchestrator.md) |
| После switchover трафик идёт на старый primary | `read_only` не изменился или монитор проверяет редко | Проверьте `mysql_server_read_only_log`, уменьшите `mysql-monitor_read_only_interval` |
| Ошибки **9001/9002** («Max connect timeout/failure while reaching hostgroup») | Все серверы SHUNNED или OFFLINE | Проверьте `stats_mysql_connection_pool` и журнал пинга |
| Лаг всегда `NULL` | Параллельная репликация или остановленный поток | Используйте heartbeat-метод вместо `SHOW REPLICA STATUS` |
| Реплика не уходит в writer при `read_only=OFF` | Превышен `max_replication_lag` | Проверьте фактический лаг; увеличьте порог или устраните отставание |
| Монитор не может подключиться, `err=1045` | Неверные учётные данные монитора | Проверьте `mysql-monitor_username`/`mysql-monitor_password` и привилегии |
| Монитор подключается, `err=1142` | Не хватает `REPLICATION CLIENT` | Выдайте привилегию пользователю монитора |
| Сервер постоянно уходит в SHUNNED | Слишком короткий `mysql-shun_recovery_time_sec` при медленном восстановлении | Увеличьте время восстановления |
| Сервер раскрывается (unshun) в одном hostgroup, но остаётся SHUNNED в остальных | `mysql-unshun_algorithm = 0` (дефолт): раскрываются только серверы из hostgroup, обрабатывающего трафик | `mysql-unshun_algorithm = 1` — при восстановлении в одном hostgroup сервер раскрывается сразу во всех |
| Клиенты получают read-only ошибку | Запрос ушёл на реплику внутри транзакции | Назначьте пользователя на writer с `transaction_persistent = 1` |
| Монитор создаёт большую нагрузку | Слишком частые интервалы проверок | Увеличьте интервалы до разумных значений |

### Обслуживание и очистка

```sql
-- Очистка журналов монитора (они растут постоянно)
TRUNCATE TABLE monitor.mysql_server_connect_log;
TRUNCATE TABLE monitor.mysql_server_ping_log;
TRUNCATE TABLE monitor.mysql_server_read_only_log;
TRUNCATE TABLE monitor.mysql_replication_lag_log;

-- Уменьшение глубины истории монитора
UPDATE global_variables SET variable_value = '300000'
WHERE variable_name = 'mysql-monitor_history';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

> **Важно:** `TRUNCATE` на таблицах `monitor.*` удаляет историю, по которой обычно разбирают инциденты. Планируйте очистку по расписанию с сохранением данных за нужный период.

```sql
-- Удаление правил hostgroups при выводе из эксплуатации
DELETE FROM mysql_replication_hostgroups
WHERE writer_hostgroup = 50 AND reader_hostgroup = 60;
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;

-- Отключение автоматического определения ролей
-- (например, при переводе primary в постоянный writer)
DELETE FROM mysql_replication_hostgroups;
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

## Лучшие практики

1.  **Не рассчитывайте на встроенный failover.** ProxySQL не повышает реплику до primary. Внешний инструмент (Orchestrator, MHA, Patroni) — обязательный компонент HA-инфраструктуры. Настраивайте его до того, как понадобится аварийное переключение.
2.  **Снижайте интервалы монитора по умолчанию.** `mysql-monitor_connect_interval = 120000` (2 минуты) — окно недоступности для критичных систем. Типичное значение — `2000–5000` мс. Учитывайте, что каждая проверка создаёт соединение с бэкендом.
3.  **Задавайте `max_replication_lag` осмысленно.** Значение `0` отключает проверку лага. Для production-репликов задайте порог, соответствующий вашему RPO (например, 30 секунд), и следите за тем, что при превышении сервер уходит в SHUNNED.
4.  **Используйте `super_read_only` вместо `read_only`.** В MySQL 8.0+ `super_read_only` является надмножеством `read_only` и защищает даже пользователей с `SUPER`. Это исключает сценарий, когда администратор случайно записал на реплику.
5.  **Монитор должен быть отдельным пользователем.** Учётные данные монитора задаются в `mysql-monitor_username` / `mysql-monitor_password` и **не могут** быть указаны в `mysql_users`. Не пытайтесь использовать одного пользователя для приложений и монитора.
6.  **Для точного измерения лага — heartbeat.** `SHOW REPLICA STATUS` блокирует репликационный поток и может возвращать `NULL` при параллельной репликации. Для критичных систем установите heartbeat-таблицу или используйте `pt-heartbeat` через `mysql-monitor_replication_lag_use_percona_heartbeat`.
7.  **Планируйте очистку монитор-логов.** Таблицы `monitor.*` растут постоянно. `TRUNCATE` удаляет историю, по которой разбирают инциденты. Очищайте по расписанию с сохранением данных за нужный период или увеличивайте `mysql-monitor_history`.
8.  **Проверяйте `mysql-unshun_algorithm`.** Значение `1` (экспоненциальные интервалы) предпочтительнее для нагруженных систем — оно снижает нагрузку на упавший сервер при попытках восстановления.
9.  **Тестируйте switchover вручную.** Шаг с `OFFLINE_SOFT` before switchover критичен — без него приложение продолжит писать на отключаемый узел. Проверяйте этот сценарий регулярно.
10. **Для Galera/Group Replication задавайте `max_writers` осознанно.** Мульти-primary (`max_writers > 1`) требует понимания ограничений дедлоков и когерентности. По умолчанию `max_writers = 1` — single-primary, что проще и безопаснее.

## Дополнительная информация

### См. также
- **[ProxySQL: Обзор](./proxysql_overview.md)** — архитектура и базовая настройка.
- **[ProxySQL: HA и ProxySQL Cluster](./proxysql_ha_cluster.md)** — Cluster, Keepalived, вывод узлов из ротации.
- **[ProxySQL: Connection Pool и Multiplexing](./proxysql_connection_pool.md)** — поведение пула при исключении сервера.
- **[Orchestrator: Управление топологией](../orchestrator.md)** — автоматизация failover.
- **[Репликация MySQL: Обзор](../replication/overview.md)** — топология, GTID, задержка.
- **[Высокая доступность MySQL](../high_availability.md)** — общие схемы обеспечения доступности.

### Официальная документация
- [Monitor Variables](https://proxysql.com/documentation/global-variables/mysql-monitor-variables/)
- [MySQL Variables](https://proxysql.com/documentation/global-variables/mysql-variables/)
- [Replication Failover and Recovery](https://proxysql.com/documentation/replication-failover-and-recovery/)