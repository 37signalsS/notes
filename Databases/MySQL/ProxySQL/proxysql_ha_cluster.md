# ProxySQL: HA и ProxySQL Cluster

**Актуально для:** ProxySQL 3.0.x

## Определения

| Термин | Значение |
| :--- | :--- |
| **Core Node** | Узел ProxySQL Cluster, авторитетный источник конфигурации. Именно Core Node принимает изменения конфигурации |
| **Satellite Node** | Узел ProxySQL Cluster, который периодически опрашивает Core Node и применяет полученную конфигурацию. Не принимает изменения конфигурации |
| **ProxySQL Cluster** | Механизм репликации конфигурации между несколькими инстансами ProxySQL |
| **Checksum** | Хеш-сумма состояния конфигурационного модуля; используется для обнаружения расхождений между узлами |
| **VIP** | Плавающий виртуальный IP-адрес, передаваемый между узлами протоколом VRRP |
| **`OFFLINE_SOFT`** | Статус сервера, при котором ProxySQL не принимает новые соединения к нему, но сохраняет уже установленные |
| **`OFFLINE_HARD`** | Статус сервера, при котором ProxySQL закрывает и новые, и существующие соединения к нему |
| **Satellite Pull** | Модель синхронизации, при которой Satellite Node сам опрашивает Core Node по расписанию (push-модели нет) |

## Теоретический блок

### Зачем нужны два независимых механизма

Отказоустойчивость ProxySQL решается двумя задачами, которые не следует смешивать:

- **Синхронизация конфигурации** — все узлы должны иметь одинаковые правила роутинга, пользователей и серверов. За это отвечает **ProxySQL Cluster**.
- **Отказоустойчивость точки входа** — приложение должно обращаться к адресу, который всегда доступен. За это отвечает **Keepalived** (VRRP/VIP).

Эти механизмы независимы: можно синхронизировать конфигурацию без VIP (и наоборот), но в продакшене обычно применяют оба.

### Модель Cluster: pull, а не push

ProxySQL Cluster построен на модели **pull**. Core Node ничего не рассылает — Satellite Node сам периодически подключается к Core Node и сверяет checksum. Это определяет два практических следствия:

1. **Изменения вносятся только на Core Node.** Правка на Satellite Node не распространится на остальные узлы и будет перезаписана при следующей синхронизации.
2. **Обнаружение недоступности Core Node занимает период `admin-cluster_check_interval_ms`.** Синхронизация не мгновенная.

Опрос: Satellite подключается, запрашивает checksum каждого синхронизируемого модуля и сравнивает его со своим. При расхождении модуль запрашивается целиком и применяется.

### Что синхронизируется

ProxySQL Cluster не синхронизирует всё подряд. Синхронизируются только определённые модули:

| Модуль | Таблица |
| :--- | :--- |
| Global Variables (admin + MySQL) | `global_variables` |
| MySQL Servers | `mysql_servers` (в т.ч. SSL-параметры) |
| MySQL Users | `mysql_users` |
| Query Rules | `mysql_query_rules` |
| ProxySQL Servers | `proxysql_servers` (список узлов кластера) |

> **Важно:** статистика (`stats_*`), runtime-состояние соединений и данные в памяти **не** синхронизируются. Каждый узел ведёт свой счётчик соединений. Это ожидаемо: метрики на узлах будут различаться, и это не расхождение конфигурации.

### Контроль расхождений

| Переменная | Назначение |
| :--- | :--- |
| `admin-cluster_mysql_servers_diffs_before_sync` | Порог расхождений модуля серверов, после которого выполняется принудительная синхронизация |
| `admin-cluster_mysql_users_diffs_before_sync` | Аналогично для пользователей |
| `admin-cluster_mysql_query_rules_diffs_before_sync` | Аналогично для правил |
| `admin-cluster_global_variables_diffs_before_sync` | Аналогично для MySQL-переменных |
| `admin-cluster_admin_variables_diffs_before_sync` | Аналогично для Admin-переменных |
| `admin-cluster_proxysql_servers_diffs_before_sync` | Аналогично для списка узлов |

Принцип: при малом количестве различий Cluster применяет инкрементальные изменения, при большом — полную перезагрузку модуля. Пороговые значения по умолчанию одинаковы для всех модулей — `3`.

### Gate-переменные: отключение синхронизации отдельных модулей

Каждый синхронизируемый модуль можно отключить независимо через gate-переменную `admin-checksum_*`. Отключение gate заставляет соответствующий `diffs_before_sync` равняться `0`, то есть синхронизация модуля прекращается.

| Gate-переменная | По умолчанию | Синхронизируемый модуль |
| :--- | :--- | :--- |
| `admin-checksum_mysql_servers` | `true` | MySQL Servers |
| `admin-checksum_mysql_users` | `true` | MySQL Users |
| `admin-checksum_mysql_query_rules` | `true` | Query Rules |
| `admin-checksum_mysql_variables` | `true` | MySQL Variables (включая monitor) |
| `admin-checksum_admin_variables` | `true` | Admin Variables |
| `admin-checksum_proxysql_servers` | `true` | Список узлов кластера |

**Практическое применение:** если на узле задаются индивидуальные admin-параметры (адреса/порты интерфейсов, `admin-mysql_ifaces`, `admin-restapi_port`), которые не должны синхронизироваться — отключите `admin-checksum_admin_variables = false`. Это предотвращает перезапись локальных настроек данными Core Node.

### Стратегия синхронизации серверов

Критично для эксплуатации: **таблица `mysql_servers` не всегда является источником истины.**

| `admin-cluster_mysql_servers_sync_algorithm` | Поведение |
| :--- | :--- |
| `1` (по умолчанию) | Синхронизируются **и** runtime, **и** диск (`mysql_servers_v2`). Безопасно |
| `2` | Синхронизируется только диск-состояние (`mysql_servers_v2`) |
| `3` | Автоопределение: выбор алгоритма по признаку запуска `-M` |

Значение `1` выбрано по умолчанию не случайно: оно корректно работает в любом случае. Значение `2` применяют осознанно, когда runtime-состояние на Satellite не должно перезаписывать диск.

### Особые случаи и ограничения

| Ситуация | Поведение / Ограничение |
| :--- | :--- |
| **Параллельная синхронизация** | `proxysql_servers` содержит **только Core Nodes**. Добавление Satellite Node в этот список не превращает его в Core Node — Satellite остаётся пассивным. |
| **Сетевой раздел (network partition)** | При потере связи с Core Node Satellite продолжает работать с локальной конфигурацией. При восстановлении связи — синхронизация. Старая конфигурация на Satellite может быть утеряна, если `save_to_disk = false`. |
| **Изменения на Satellite Node** | Любой вносимый на Satellite Node (`UPDATE`, `INSERT`) перезаписывается при следующей синхронизации с Core Node. Это не ошибка — ожидаемое поведение. |
| **Разные версии ProxySQL** | Синхронизация требует одинаковой major-версии. Mix версий 2.x и 3.0.x приводит к неопределённости: формат checksum и структура таблиц могут различаться. |
| **Bootstrap-режим** | При запуске с `-M` ProxySQL игнорирует локальную конфигурацию и загружает её из `proxysql_servers` (диск). Это полезно для первоначального развёртывания, но требует, чтобы `proxysql_servers` был заполнен на всех узлах. |
| **`proxysql_servers` и `admin-admin_credentials`** | Учётные данные синхронизации (`admin-cluster_username`/`admin-cluster_password`) должны присутствовать в `admin-admin_credentials` **каждого** узла. Если на Core Node они заданы, а на Satellite — нет, синхронизация не начнётся. |
| **`admin-checksum_*` и `diffs_before_sync = 0`** | Отключение gate-переменной принудительно устанавливает соответствующий `diffs_before_sync` в `0`. Это не просто отключает синхронизацию — она прекращается полностью, даже если checksum различаются. |
| **`admin-cluster_mysql_servers_sync_algorithm = 3`** | Автоопределение: при запуске без `-M` выбирается алгоритм `1`, с `-M` — `2`. Изменение алгоритма сбрасывает cluster-checksum, поэтому выбранная конфигурация оценивается сразу. |
| **Счётчики соединений** | `stats_*` и runtime-состояние соединений **не** синхронизируются. Каждый узел ведёт счётчик независимо. Сравнивайте только checksum конфигурации, а не метрики. |
| **Рестарт Core Node** | При-temporarily unavailable Core Node Satellite продолжает работать, но не получает обновления. После возврата Core Node его конфигурация может быть старше, если изменения вносились на Satellite. |
| **VIP и VRRP** | VRRP не обеспечивает прозрачное переподключение. При переключении VIP уже открытые соединения разрываются; приложения должны иметь retry-логику. Подробнее — в [Keepalived: Обзор](../../../Networking/ServicesAndTools/keepalived_overview.md). |
| **`OFFLINE_SOFT` и long-lived connections** | Если клиент удерживает соединение и не выпускает его из пула, существующие соединения могут не закрыться неограниченно долго. Наблюдайте за `stats_mysql_connection_pool` и при необходимости переходите к `OFFLINE_HARD`. |
| **`OFFLINE_SOFT` и failover** | `OFFLINE_SOFT` не повышает реплику до primary. Используйте его только для планового вывода узла из ротации. |

## Практический блок

### Развёртывание кластера из двух узлов

**Предусловия:**
- Оба узла на одной версии ProxySQL (для версии 3.0.x — одинаковый patch-уровень).
- Взаимная сетевая доступность по admin-порту `6032`.
- Узлы видны друг другу по адресу, который будет использоваться в `proxysql_servers` (не по `localhost`).
- Основной пользователь admin-интерфейса отличается от пользователя синхронизации.

#### Шаг 1. Синхронизация конфигурации Cluster

```sql
-- Выполняется на КАЖДОМ узле, включая Core Node.
-- Узлы перечисляют друг друга.

-- Очистить возможный прошлый состав
DELETE FROM proxysql_servers;

-- Добавить все узлы кластера, включая текущий.
-- hostname:port должен резолвиться и быть доступен.
INSERT INTO proxysql_servers (hostname, port, weight, comment) VALUES
  ('proxysql-1.example.com', 6032, 1.0, 'Core Node'),
  ('proxysql-2.example.com', 6032, 1.0, 'Satellite Node');

LOAD PROXYSQL SERVERS TO RUNTIME;
SAVE PROXYSQL SERVERS TO DISK;
```

#### Шаг 2. Учётные данные и интервалы

```sql
-- Пользователь, от имени которого Satellite подключается к Core Node.
-- Учётные данные admin-интерфейса задаются в admin_variables, а не в global_variables.
UPDATE global_variables SET variable_value = 'cluster_sync_user'
WHERE variable_name = 'admin-cluster_username';

UPDATE global_variables SET variable_value = 'СЛОЖНЫЙ_ПАРОЛЬ'
WHERE variable_name = 'admin-cluster_password';

-- Интервал проверки checksum с парами узлов, мс. По умолчанию 1000.
UPDATE global_variables SET variable_value = '1000'
WHERE variable_name = 'admin-cluster_check_interval_ms';

-- Через сколько проверок checksum выполняется детальная проверка (SHOW MYSQL STATUS).
-- По умолчанию 10.
UPDATE global_variables SET variable_value = '10'
WHERE variable_name = 'admin-cluster_check_status_frequency';

-- Синхронизировать ли admin-параметры (адреса/порты интерфейсов).
-- По умолчанию включено (true), но обычно эти параметры задаются индивидуально на каждом узле,
-- потому что у Core Node и Satellite Node могут быть разные адреса и порты.
-- Отключается через gate-переменную admin-checksum_admin_variables = false.
UPDATE global_variables SET variable_value = 'false'
WHERE variable_name = 'admin-checksum_admin_variables';

LOAD ADMIN VARIABLES TO RUNTIME;
SAVE ADMIN VARIABLES TO DISK;
```

#### Шаг 3. Автоматическое сохранение на диск

```sql
-- По умолчанию true: изменения, пришедшие через Cluster,
-- автоматически сохраняются на диск Satellite Node.
UPDATE global_variables SET variable_value = 'true'
WHERE variable_name = 'admin-cluster_mysql_servers_save_to_disk';

LOAD ADMIN VARIABLES TO RUNTIME;
SAVE ADMIN VARIABLES TO DISK;
```

#### Шаг 4. Проверка синхронизации

```sql
-- Статус синхронизации по каждому узлу кластера.
-- Столбец checksum_ok показывает, совпадает ли состояние узла с Core Node.
SELECT hostgroup_id, hostname, port, weight, status, comment
FROM stats_proxysql_servers_checksums;
# → hostname           | port | status  | comment
# → proxysql-1.example.com | 6032 | ONLINE  | Core Node
# → proxysql-2.example.com | 6032 | ONLINE  | Satellite Node

-- Локальные checksum модулей для сравнения с Core Node
SELECT checksum FROM runtime_checksums_values;
# → checksum
# → 1482381...

-- Сверка состава серверов между узлами
SELECT hostgroup_id, hostname, port, status FROM mysql_servers;
```

> **Диагностика:** если `checksum` узлов не совпадает, синхронизации нет. Проверяйте сетевую доступность к admin-порту Core Node и корректность `admin-cluster_username`/`admin-cluster_password`. Подробнее — в [ProxySQL: Конфигурация и переменные](./proxysql_configuration.md).

### Keepalived и VIP

Общие принципы VRRP, конфигурация `keepalived.conf` и работа с плавающим IP описаны в [Keepalived: Обзор](../../../Networking/ServicesAndTools/keepalived_overview.md). Здесь — только специфика ProxySQL.

**Проблема, которую решает VIP:** приложения не должны знать, на каком из узлов находится активный ProxySQL. VIP абстрагирует узлы за одним адресом.

**Критичное требование — `real_ip_address`.** ProxySQL использует IP-адрес источника соединения для применения query rules (колонка `client_addr`). Без корректного `real_ip_address` все соединения через VIP будут выглядеть как соединения с адреса Keepalived, и правила вида `client_addr = '10.0.0.5'` перестанут работать.

```bash
# Разрешить ProxySQL видеть реальный IP клиента вместо VIP
net.ipv4.conf.all.forwarding=1
net.ipv4.conf.default.forwarding=1
```

**Проверка после внедрения VIP:**

```sql
-- Значение cli_host из соединения должно совпадать с IP клиента, а не с VIP
SELECT SessionID, user, cli_host, cli_port, hostgroup
FROM stats_mysql_processlist
LIMIT 10;
```

**Поведение при потере активного узла:**

| Свойство | Значение |
| :--- | :--- |
| Новое соединение | Устанавливается через новый VIP-держатель после прохождения `ad_int` |
| Уже открытые соединения | **Разрываются.** Приложение обязано само переподключиться |
| Потеря данных | Возможна при обрыве транзакции на старте failover |

Это фундаментальное ограничение VRRP-подхода: он не обеспечивает прозрачное переподключение. Приложения должны иметь встроенный retry с backoff. Обоснование и альтернативы — в [Keepalived: Обзор](../../../Networking/ServicesAndTools/keepalived_overview.md).

### Вывод узла из ротации перед обслуживанием

**Сценарий:** плановое обслуживание узла — обновление, перезагрузка. Планировать это через failover нельзя: при `read_only=ON` он объявит узел writer'ом, что приведёт к неверной маршрутизации.

Правильная последовательность — сначала исключить сервер из роутинга, затем обслуживать:

```sql
-- 1. Перевести сервер в OFFLINE_SOFT: новые соединения не создаются,
--    существующие продолжают работать. Это даёт время на завершение
--    длительных операций без разрыва клиентских сессий.
UPDATE mysql_servers SET status = 'OFFLINE_SOFT'
WHERE hostname = 'db-writer-1' AND port = 3306;
LOAD MYSQL SERVERS TO RUNTIME;

-- 2. Убедиться, что новые соединения не создаются,
--    а существующие постепенно завершаются
SELECT hostgroup, srv_host, status, ConnUsed, ConnFree
FROM stats_mysql_connection_pool
WHERE srv_host = 'db-writer-1';
# → status       | ConnUsed | ConnFree
# → OFFLINE_SOFT | 2        | 5

-- 3. Теперь безопасно обслуживать узел

-- 4. Возврат в работу
UPDATE mysql_servers SET status = 'ONLINE'
WHERE hostname = 'db-writer-1' AND port = 3306;
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

**Выбор между `OFFLINE_SOFT` и `OFFLINE_HARD`:**

| Статус | Новые соединения | Существующие соединения | Когда применять |
| :--- | :--- | :--- | :--- |
| `ONLINE` | Разрешены | Работают | Штатный режим |
| `OFFLINE_SOFT` | Не создаются | Продолжают работают | Плановое обслуживание с сохранением сессий |
| `OFFLINE_HARD` | Не создаются | Закрываются немедленно | Аварийное исключение сервера |
| `SHUNNED` | Не создаются | Сужествующие закрываются при завершении | Автоматическая реакция монитора |

> **Ограничение `OFFLINE_SOFT`.** Если клиент удерживает соединение и не выпускает его из пула, существующие соединения могут не закрыться неограниченно долго. Наблюдайте за `stats_mysql_connection_pool` и при необходимости переходите к `OFFLINE_HARD`.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Checksum узлов не совпадает | Satellite не может подключиться к Core Node | Проверьте доступность admin-порта Core Node и корректность `admin-cluster_username`/`admin-cluster_password` |
| Изменения не распространяются | Изменение внесено на Satellite Node | Вносите все изменения конфигурации **только** на Core Node |
| Конфигурация «откатывается» | Satellite перезаписал локальную правку данными Core Node | Это ожидаемое поведение. Перенесите правку на Core Node |
| После рестарта Satellite вернулась старая конфигурация | `admin-cluster_*_save_to_disk = false`, изменения не сохранены | Установите `admin-cluster_mysql_servers_save_to_disk = true` либо выполните `SAVE ... TO DISK` вручную |
| Правила по `client_addr` не работают | Не настроен `real_ip_address`, виден VIP | Включите `net.ipv4.conf.all.forwarding=1` и проверьте `client_host` |
| Правило сработало не для того клиента | Проверьте `client_addr` в конфигурации правила | См. [ProxySQL: Query Rules](./proxysql_query_rules.md) |
| Метрики узлов не совпадают | Счётчики соединений не синхронизируются по Cluster | Это нормально. Сравнивайте конфигурацию через checksum, а не метрики |
| При рестарте сервера приложений не подключаются | VIP не передался, Keepalived не запущен | Проверьте `systemctl status keepalived` и логи; убедитесь, что VIP не занят |

### Обслуживание и очистка

```bash
# Ротация и очистка логов ProxySQL
ls -la /var/log/proxysql/
# → proxysql.log

# Удаление неиспользуемых digest (см. также документ по мониторингу)
```

```sql
-- Очистка накопленной статистики по digest
DELETE FROM stats_mysql_query_digest;
SELECT purge_cached_errors, purge_max_errors,
       purge_check_interval_min, purge_pct
FROM runtime_global_variables
WHERE variable_name LIKE 'mysql%';
# → purge_cached_errors | purge_max_errors | purge_check_interval_min | purge_pct
# → 1                   | 100             | 10                     | 99.5
```

Очистку статистики следует выполнять по расписанию, если база используется долго: таблица `stats_mysql_query_digest` растёт вместе с числом уникальных запросов. В 3.0.x автоматической очистки нет — она выполняется административной командой `PURGE TABLE stats_mysql_query_digest TO <unix_timestamp>`, удаляющей записи по значению `last_seen`. Переменных `mysql-purge_*` в этой версии не существует. Подробнее — в [ProxySQL: Мониторинг](./proxysql_monitoring.md#очистка-статистики-запросов).

## Дополнительная информация

### См. также
- **[ProxySQL: Обзор](./proxysql_overview.md)** — архитектура, модули, базовая настройка.
- **[ProxySQL: Failover и мониторинг репликации](./proxysql_failover.md)** — `read_only`-мониторинг, `SHUNNED`, лаг репликации.
- **[ProxySQL: Конфигурация и переменные](./proxysql_configuration.md)** — синтаксис переменных, `LOAD`/`SAVE`, `proxysql.cnf`.
- **[Keepalived: Обзор](../../../Networking/ServicesAndTools/keepalived_overview.md)** — VRRP, VIP, ограничения подхода.
- **[Репликация MySQL: Обзор](../replication/overview.md)** — топология и задержка репликации.
- **[Orchestrator: Управление топологией](../orchestrator.md)** — автоматизация failover и обновления hostgroups.

### Официальная документация
- [ProxySQL Cluster](https://proxysql.com/documentation/proxysql-cluster/)
- [Admin Cluster Variables](https://proxysql.com/documentation/proxysql-cluster/cluster-variables)
- [ProxySQL Cluster Stats Tables](https://proxysql.com/documentation/the-admin-schemas/stats/stats-proxysql-cluster)