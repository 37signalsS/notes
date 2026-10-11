# ProxySQL: Конфигурация и переменные

**Актуально для:** ProxySQL 3.0.x (Stable) / 3.1.x (Innovative)

Текущий релиз на август 2026: 3.0.11 (Stable) и 3.1.11 (Innovative). Существует также линейка 4.0.x (Plugin Chassis / AI Tier) — её команды (MySQL X Protocol, MCP/GenAI) в 3.0.x/3.1.x отсутствуют и здесь не рассматриваются.

## Определения

| Термин | Значение |
| :--- | :--- |
| **`proxysql.cnf`** | Файл конфигурации; полностью читается только при первом запуске, при `--initial` или через `LOAD ... FROM CONFIG` |
| **`main` (Memory)** | Оперативная БД конфигурации в Admin-интерфейсе; именно сюда попадают SQL-изменения |
| **`disk`** | Схема Admin-интерфейса — персистентная зеркальная копия `main` (файл `proxysql.db`) |
| **Runtime** | Действующее состояние в памяти рабочих потоков; читается через `runtime_`-таблицы |
| **`LOAD ... TO RUNTIME`** | Применение изменений из `main` к работающему процессу |
| **`SAVE ... TO DISK`** | Сохранение состояния из `main` в `disk` (переживёт перезапуск) |
| **`LOAD ... FROM DISK`** | Загрузка состояния из `disk` в `main` |
| **`LOAD ... FROM CONFIG`** | Перечитывание значений из `proxysql.cnf` в `main` |
| **Dynamic** | Переменная, применяемая без перезапуска процесса |
| **`--initial`** | Флаг принудительного пересоздания БД из `proxysql.cnf` |

## Теоретический блок

### Четыре слоя состояния

Это центральная концепция, неверное понимание которой приводит к большинству проблем. ProxySQL использует **четыре** слоя, а не три: SQL-изменения попадают в отдельный слой `main` (Memory), а не на диск.

| Слой | Где хранится | Как изменяется | Переживает перезапуск |
| :--- | :--- | :--- | :--- |
| **Config File** | `proxysql.cnf` | Текстовый редактор | Да, но читается не при каждом старте |
| **Disk** | `proxysql.db` (SQLite) | Только `SAVE ... TO DISK` | Да |
| **Memory (`main`)** | Оперативная SQLite | SQL: `INSERT`/`UPDATE`/`DELETE`, `SET` | **Нет** |
| **Runtime** | Память рабочих потоков | Только `LOAD ... TO RUNTIME` | Нет |

**Критическое следствие:** изменение, сделанное через SQL, попадает **только в Memory**. Для применения к работающему процессу требуется `LOAD ... TO RUNTIME`, для сохранения между перезапусками — `SAVE ... TO DISK`. Это справедливо и для `UPDATE global_variables`, и для `SET` — оба варианта пишут только в Memory.

Типичная ошибка: администратор правит `proxysql.cnf`, не видит изменений и перезапускает службу — но при наличии `proxysql.db` файл `.cnf` вообще не читается (см. следующий раздел), а если ранее конфигурация сохранялась через `SAVE`, она берётся из базы, а не из файла.

### Поведение при запуске

При старте ProxySQL читает `proxysql.cnf` **только для определения `datadir`**, а дальше действует по наличию базы:

1. **База `proxysql.db` найдена** (обычный рестарт): файл `.cnf` **не парсится**. Memory загружается из Disk, затем применяется в Runtime. Правки `.cnf` между рестартами не действуют.
2. **База не найдена, `.cnf` есть** (первый запуск): `.cnf` парсится → загружается в Memory → сохраняется в Disk → применяется в Runtime.
3. **Флаг `--initial`**: существующая база переименовывается, создаётся новая из `.cnf` (по сценарию 2).

Отсюда практическое правило: после первого запуска `.cnf` — это механизм bootstrap, а не рабочий способ хранения конфигурации. Внести изменения из `.cnf` в работающий экземпляр можно командой `LOAD <MODULE> FROM CONFIG`.

### Цикл правильного внесения изменений

```
1. UPDATE/INSERT/DELETE или SET  →  попадает в Memory (main)
2. LOAD ... TO RUNTIME           →  применение к работающему процессу
3. SAVE ... TO DISK              →  фиксация в Disk (персистентность)
4. проверка результата           →  SELECT из runtime_таблицы и/или disk-схемы
```

Шаг 3 обязателен для **любой** правки, сделанной через SQL — и через `UPDATE`, и через `SET`: оба способа пишут только в Memory. Без `SAVE ... TO DISK` изменение пропадёт при перезапуске.

### Группы переменных и команды загрузки

Переменные в `global_variables` группируются по префиксу, и каждая группа применяется своей командой:

| Группа | Примеры переменных | Команда загрузки |
| :--- | :--- | :--- |
| **Admin** (`admin-`) | `admin-admin_credentials`, `admin-mysql_ifaces`, `admin-restapi_enabled` | `LOAD ADMIN VARIABLES TO RUNTIME` |
| **MySQL** (`mysql-`) | `mysql-threads`, `mysql-max_connections`, `mysql-monitor_ping_interval` | `LOAD MYSQL VARIABLES TO RUNTIME` |
| **PostgreSQL** (`pgsql-`, с 3.0) | `pgsql-threads` | `LOAD PGSQL VARIABLES TO RUNTIME` |
| **Cluster** (`admin-cluster_*`) | `admin-cluster_username`, `admin-cluster_check_interval_ms` | `LOAD ADMIN VARIABLES TO RUNTIME` |

> **Частая ошибка:** изменение `admin-restapi_enabled` с последующим `LOAD MYSQL VARIABLES TO RUNTIME` **не сработает** — переменная относится к группе Admin.

### Префиксы и форма имён переменных

Префикс имени переменной определяет её область: `mysql-` — модуль MySQL, `admin-` — Admin-интерфейс и Cluster, `pgsql-` — модуль PostgreSQL (3.0+). Префиксы таблиц (`mysql_servers`, `mysql_query_rules`) — это имена таблиц, а не префиксы переменных; не путайте их.

Имена записываются **с дефисом** и в SQL, и в выводе `SHOW VARIABLES`: `mysql-max_connections`. В `proxysql.cnf` префикс задаётся именем секции (`mysql_variables=`), а переменная записывается без него (`max_connections=10000`).

```sql
-- Чтение значения
SELECT variable_value FROM global_variables WHERE variable_name = 'mysql-max_connections';
# → 10000

-- Чтение через SHOW (имя с дефисом)
SHOW VARIABLES LIKE 'mysql-max_connections';

-- Изменение (попадает в Memory)
UPDATE global_variables SET variable_value = '4000'
WHERE variable_name = 'mysql-max_connections';
LOAD MYSQL VARIABLES TO RUNTIME;

-- Проверка применения
SELECT variable_value FROM runtime_global_variables WHERE variable_name = 'mysql-max_connections';
# → 4000
```

### Файл `proxysql.cnf`

Файл состоит из секций. Основные:

```ini
datadir="/var/lib/proxysql"
errorlog="/var/lib/proxysql/proxysql.log"

admin_variables=
{
    admin_credentials="admin:admin"
    mysql_ifaces="0.0.0.0:6032"
}

mysql_variables=
{
    threads=4
    max_connections=10000
    interfaces="0.0.0.0:6033"
    default_query_timeout=86400000
}
```

**`SAVE ... TO DISK` не перезаписывает `.cnf`** — оно пишет в SQLite-файл `proxysql.db`. Файл конфигурации остаётся в том виде, в каком его оставили, и с течением времени расходится с реальным состоянием Disk. Это нормально: после первого запуска источник истины — база, а не файл.

**Что не следует помещать в `.cnf`:** список серверов, пользователей и правил. Эти данные живут в таблицах `mysql_servers`, `mysql_users`, `mysql_query_rules`, а не в файле.

**Экспорт текущей конфигурации в формат файла** (с 3.0.10): команда `SAVE CONFIG` выполняет round-trip конфигурации (правила быстрого роутинга, firewall-таблицы, SSL-параметры серверов, атрибуты hostgroup) в формат `.cnf`; `SELECT CONFIG FILE` возвращает содержимое. Полезно для воспроизводимой конфигурации и бэкапов.

### Команды `LOAD` и `SAVE`

Команды перемещают конфигурацию между слоями. Полная матрица для каждого модуля (`MYSQL SERVERS`, `MYSQL USERS`, `MYSQL QUERY RULES`, `MYSQL VARIABLES`, `ADMIN VARIABLES`, `PROXYSQL SERVERS`, `SCHEDULER`, `RESTAPI`):

| Команда | Направление | Алиасы |
| :--- | :--- | :--- |
| `LOAD <MODULE> TO RUNTIME` | Memory → Runtime | `FROM MEMORY`, `FROM MEM`, `TO RUN` |
| `SAVE <MODULE> TO MEMORY` | Runtime → Memory | `FROM RUNTIME`, `FROM RUN`, `TO MEM` |
| `LOAD <MODULE> TO MEMORY` | Disk → Memory | `FROM DISK`, `TO MEM` |
| `SAVE <MODULE> TO DISK` | Memory → Disk | `FROM MEMORY`, `FROM MEM` |
| `LOAD <MODULE> FROM CONFIG` | Config File → Memory | — |

Короткие формы: `MEM` вместо `MEMORY`, `RUN` вместо `RUNTIME` (например, `LOAD MYSQL SERVERS TO RUN` ≡ `LOAD MYSQL SERVERS TO RUNTIME`).

Примеры типовых операций:

| Задача | Команды |
| :--- | :--- |
| Применить серверы после правки `mysql_servers` | `LOAD MYSQL SERVERS TO RUNTIME` |
| Сохранить серверы | `SAVE MYSQL SERVERS TO DISK` |
| Перечитать серверы из базы в Memory | `LOAD MYSQL SERVERS FROM DISK` |
| Перечитать переменные из `.cnf` | `LOAD MYSQL VARIABLES FROM CONFIG` |
| Применить список узлов Cluster | `LOAD PROXYSQL SERVERS TO RUNTIME` |
| Зафиксировать runtime-состояние в Memory | `SAVE MYSQL SERVERS TO MEMORY` |

**Критично:** формы `LOAD ... TO DISK` **не существует** — запись на диск выполняется только через `SAVE ... TO DISK`. `LOAD ... FROM DISK` читает базу **в Memory**, но **не в Runtime** — после него обычно требуется `LOAD ... TO RUNTIME`. `SAVE ... TO MEMORY` (`FROM RUNTIME`) полезен, когда нужно отразить текущее runtime-состояние в редактируемых таблицах, например после автообнаружения серверов Group Replication.

### Динамические и статические переменные

Почти все переменные динамические. **Только три переменные нельзя изменить на лету** — они применяются только при старте процесса: `mysql-interfaces`, `mysql-threads` и `mysql-stacksize`. Для их изменения есть два пути: правка `.cnf` + `--initial`/отсутствие базы, либо команда `PROXYSQL RESTART` — она перезапускает основной процесс без участия systemd и сохраняет текущий статус, что быстрее полного рестарта службы.

**Обратная связь при загрузке (с 3.0.10).** `LOAD ... VARIABLES TO RUNTIME` возвращает в OK-пакете сводку:

```
Records: <records> Updated: <updated> Rejected: <rejected> Unknown: <unknown>
```

где `Records` — число просмотренных строк, `Updated` — принято в Runtime, `Rejected` — известные переменные с непрошедшими валидацию значениями, `Unknown` — имена, не поддерживаемые этой версией. Отклонённое значение **не активируется**: ProxySQL восстанавливает в таблице конфигурации текущее корректное значение, а неизвестные строки удаляются из Memory-таблицы. Команда может вернуть OK при ненулевых `Rejected`/`Unknown`, поэтому автоматизация должна анализировать сводку, а не только статус OK.

**Практический подход:** после изменения проверяйте значение в runtime-таблице и сводку `Records/Updated/Rejected/Unknown`. Если значение осталось прежним, а сводка показывает `Rejected` — значение не прошло валидацию (выход за допустимый диапазон); если переменная относится к числу трёх статических — требуется `PROXYSQL RESTART`.

```sql
-- Проверка, что изменение действительно применилось
SELECT variable_value FROM runtime_global_variables
WHERE variable_name = 'mysql-max_connections';
# → 4000
```

## Практический блок

### Предварительные требования

Установленный ProxySQL (установка и системные требования — в [ProxySQL: Обзор](./proxysql_overview.md)), доступ к Admin-интерфейсу на порту `6032` и учётные данные из `admin-admin_credentials` (по умолчанию `admin:admin`). Все операции ниже выполняются через Admin-интерфейс или shell на хосте с ProxySQL.

### Начальная инициализация

```bash
# Первый запуск: базы нет, конфигурация читается из proxysql.cnf
# и сохраняется в proxysql.db
systemctl start proxysql
systemctl status proxysql
# → Active: active (running)

# Проверка портов
ss -lntp | grep -E '6032|6033'
# → LISTEN 0 128 0.0.0.0:6032 0.0.0.0:* users:(("proxysql",pid=4711,fd=7))
# → LISTEN 0 128 0.0.0.0:6033 0.0.0.0:* users:(("proxysql",pid=4711,fd=8))

# Проверка созданной базы
ls -la /var/lib/proxysql/
# → -rw-r--r-- 1 proxysql proxysql 20480 Sep 27 17:40 proxysql.db
```

**Пересоздание базы из файла конфигурации.** Флаг `--initial` **переименовывает существующую базу** и создаёт новую из `.cnf` — это деструктивная операция, а не «создать, если не существует». Перед ней сделайте бэкап:

```bash
# Через systemd (рекомендуемый способ)
systemctl stop proxysql
cp /var/lib/proxysql/proxysql.db /var/lib/proxysql/proxysql.db.bak
systemctl start proxysql-initial
# → база proxysql.db пересоздана из /etc/proxysql/proxysql.cnf

# Эквивалент через init-скрипт
service proxysql initial

# Или напрямую флагом
proxysql --initial -c /etc/proxysql/proxysql.cnf
```

### Правильное внесение изменений

```sql
-- 1. Внести изменение (попадает в Memory)
UPDATE global_variables SET variable_value = '4000'
WHERE variable_name = 'mysql-max_connections';

-- 2. Применить к процессу
LOAD MYSQL VARIABLES TO RUNTIME;
# → Query OK, ... Records: 184 Updated: 181 Rejected: 0 Unknown: 0

-- 3. Проверить результат в Runtime
SELECT variable_name, variable_value
FROM runtime_global_variables
WHERE variable_name = 'mysql-max_connections';
# → variable_name        | variable_value
# → mysql-max_connections | 4000

-- 4. Зафиксировать на диске (без этого изменение пропадёт при рестарте)
SAVE MYSQL VARIABLES TO DISK;

-- 5. Убедиться, что в Disk то же значение
SELECT variable_value FROM disk.global_variables
WHERE variable_name = 'mysql-max_connections';
# → 4000
```

### Работа через `SET`

Admin-интерфейс поддерживает `SET` как сокращение для `UPDATE`:

```sql
SET mysql-max_connections=4000;
# → Variable 'mysql-max_connections' set to 4000
```

**Отличие от `UPDATE` — только синтаксическое.** Внутренне `SET variable=value` транслируется в `UPDATE global_variables SET variable_value=<value> WHERE variable_name='<variable>'`, то есть пишет **только в Memory**. После `SET` обязательны те же два шага: `LOAD ... TO RUNTIME` для применения и `SAVE ... TO DISK` для персистентности.

Ограничения `SET`: переменная `mysql-init_connect` не задаётся через `SET` (только `UPDATE global_variables`); неизвестное имя переменной возвращает ошибку `ERROR: Unknown global variable`.

```sql
-- Полный цикл через SET
SET mysql-max_connections=4000;
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

### Массовое изменение переменных

```sql
-- Обзор перед изменением
SELECT variable_name, variable_value
FROM global_variables
WHERE variable_name LIKE 'mysql-monitor%';
```

```sql
-- Применение пакета изменений
UPDATE global_variables SET variable_value = '5000'
WHERE variable_name = 'mysql-monitor_connect_interval';

UPDATE global_variables SET variable_value = '2000'
WHERE variable_name = 'mysql-monitor_ping_interval';

UPDATE global_variables SET variable_value = 'mon'
WHERE variable_name = 'mysql-monitor_username';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

**Проверка:**

```sql
SELECT variable_name, variable_value FROM global_variables
WHERE variable_name IN ('mysql-monitor_connect_interval',
                        'mysql-monitor_ping_interval',
                        'mysql-monitor_username');
# → variable_name                  | variable_value
# → mysql-monitor_connect_interval | 5000
# → mysql-monitor_ping_interval    | 2000
# → mysql-monitor_username         | mon
```

### Экспорт и импорт конфигурации

**Экспорт переменных:**

```bash
# Дамп всех переменных в виде команд SET
mysql -h 127.0.0.1 -P 6032 -u admin -p -N -e \
  "SELECT CONCAT('SET ', variable_name, '=', variable_value, ';')
   FROM global_variables
   WHERE variable_value NOT IN ('NULL', '')
     AND variable_name NOT LIKE 'admin-cluster_password'
     AND variable_name NOT LIKE '%password%';" \
  > /tmp/proxysql_vars.sql
# → файл с командами SET
```

> **Осторожно:** дамп содержит секреты, если не исключить пароли. Исключение в примере выше намеренное. Полученный файл следует защитить правами и удалить после использования.

**Импорт на новый узел:**

```bash
# Применение переменных к новому экземпляру
mysql -h 127.0.0.1 -P 6032 -u admin -p < /tmp/proxysql_vars.sql
# → SET mysql-max_connections=4000
# → SET mysql-monitor_connect_interval=5000

LOAD MYSQL VARIABLES TO RUNTIME;
LOAD ADMIN VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
SAVE ADMIN VARIABLES TO DISK;

rm -f /tmp/proxysql_vars.sql
```

**Экспорт таблиц конфигурации:**

```sql
-- Дамп серверов
SELECT * FROM mysql_servers;
SELECT * FROM mysql_users;
SELECT * FROM mysql_query_rules;
SELECT * FROM mysql_replication_hostgroups;
SELECT * FROM proxysql_servers;
```

Для полного round-trip конфигурации в формат `.cnf` (с 3.0.10) используйте `SAVE CONFIG` / `SELECT CONFIG FILE` — они сохраняют firewall-таблицы, правила быстрого роутинга и SSL-параметры серверов.

### Контроль изменений: Memory, Disk, Runtime

Три схемы Admin-интерфейса (`main`, `disk`, `runtime_`-таблицы) позволяют точно локализовать расхождение. Поскольку все они — присоединённые SQLite-базы, их можно сравнивать одним запросом:

```sql
-- 1. Внесено в Memory, но НЕ применено к Runtime
SELECT m.variable_name, m.variable_value AS memory_value,
       r.variable_value AS runtime_value
FROM global_variables m
JOIN runtime_global_variables r USING (variable_name)
WHERE m.variable_value != r.variable_value;
# → variable_name              | memory_value | runtime_value
# → mysql-max_connections      | 4000         | 10000

-- 2. Внесено в Memory, но НЕ сохранено на Disk (пропадёт при рестарте)
SELECT m.variable_name, m.variable_value AS memory_value,
       d.variable_value AS disk_value
FROM global_variables m
JOIN disk.global_variables d USING (variable_name)
WHERE m.variable_value != d.variable_value;

-- 3. Расхождение Runtime и Disk
SELECT r.variable_name, r.variable_value AS runtime_value,
       d.variable_value AS disk_value
FROM runtime_global_variables r
JOIN disk.global_variables d USING (variable_name)
WHERE r.variable_value != d.variable_value;
```

**Значение запроса 2:** переменная работает со значением `4000`, но после перезапуска станет `2048` — изменение не сохранено. Выполните `SAVE ... TO DISK`.

**Checksum-модули.** Таблица `runtime_checksums_values` показывает локальные checksum модулей — по ним Cluster-синхронизация обнаруживает изменения:

```sql
SELECT name, version, epoch, checksum FROM runtime_checksums_values ORDER BY name;
# → name               | version | epoch     | checksum
# → mysql_query_rules  | 5       | 1503442167| 0xD3BD702F8E759B1E
# → mysql_servers      | 1       | 1503440533| 0x6F8CEF0F4BD6456E
```

`version` инкрементируется при каждом `LOAD ... TO RUNTIME` модуля, `epoch` — время загрузки, `checksum` — контрольная сумма структуры. Для сверки с узлами Cluster служит `stats_proxysql_servers_checksums` (подробнее — в [ProxySQL: HA и ProxySQL Cluster](./proxysql_ha_cluster.md)). Проверить согласованность слоёв модуля можно командой `CHECKSUM`:

```sql
CHECKSUM MYSQL SERVERS;
CHECKSUM MEMORY MYSQL SERVERS;
CHECKSUM DISK MYSQL SERVERS;
```

### Атомарная замена состава hostgroup

Таблицы `mysql_servers` и `mysql_server_hostgroup` — разные вещи: последней **не существует**. Состав hostgroup хранится в `mysql_servers` (столбец `hostgroup_id`; первичный ключ — `(hostgroup_id, hostname, port)`). Замена состава группы атомарна на этапе `LOAD ... TO RUNTIME`: до этой команды правки живут только в Memory, а применяются разом:

```sql
-- 1. Подготовить новый состав группы в Memory
DELETE FROM mysql_servers WHERE hostgroup_id = 20;
INSERT INTO mysql_servers (hostgroup_id, hostname, port, status, weight, max_connections)
VALUES (20, 'db-replica-3', 3306, 'ONLINE', 1, 1000),
       (20, 'db-replica-4', 3306, 'ONLINE', 1, 1000);

-- 2. Применить атомарно
LOAD MYSQL SERVERS TO RUNTIME;

-- 3. Зафиксировать
SAVE MYSQL SERVERS TO DISK;

-- 4. Проверить результат
SELECT hostgroup_id, hostname, port, status FROM runtime_mysql_servers
WHERE hostgroup_id = 20;
# → hostgroup_id | hostname      | port | status
# → 20           | db-replica-3  | 3306 | ONLINE
# → 20           | db-replica-4  | 3306 | ONLINE
```

Столбцы `mysql_servers`: `hostgroup_id`, `hostname`, `port`, `status` (`ONLINE`, `SHUNNED`, `OFFLINE_SOFT`, `OFFLINE_HARD`), `weight`, `compression`, `max_connections` (по умолчанию `1000`), `max_replication_lag`, `use_ssl`, `max_latency_ms`, `comment`. Статусы `SHUNNED`/`OFFLINE_*` назначает монитор; пользовательские правки обычно оставляют `ONLINE`.

### Откат к предыдущему состоянию

```sql
-- Возврат runtime-состояния к текущему состоянию Memory
-- (отмена неприменённых или применённых, но не сохранённых правок)
LOAD MYSQL VARIABLES TO RUNTIME;
LOAD MYSQL SERVERS TO RUNTIME;
LOAD MYSQL USERS TO RUNTIME;
LOAD MYSQL QUERY RULES TO RUNTIME;
LOAD ADMIN VARIABLES TO RUNTIME;
```

```sql
-- Возврат Memory к состоянию на диске.
-- Отменяет все изменения, внесённые после последнего SAVE ... TO DISK
LOAD MYSQL VARIABLES FROM DISK;
LOAD MYSQL SERVERS FROM DISK;
LOAD MYSQL USERS FROM DISK;
LOAD MYSQL QUERY RULES FROM DISK;
-- после этого примените результат:
LOAD MYSQL VARIABLES TO RUNTIME;
LOAD MYSQL SERVERS TO RUNTIME;
LOAD MYSQL USERS TO RUNTIME;
LOAD MYSQL QUERY RULES TO RUNTIME;
```

```sql
-- Возврат Disk к состоянию из файла конфигурации.
-- ВНИМАНИЕ: значения, накопленные через SAVE, будут затёрты
LOAD MYSQL VARIABLES FROM CONFIG;
LOAD MYSQL SERVERS FROM CONFIG;
SAVE MYSQL VARIABLES TO DISK;
SAVE MYSQL SERVERS TO DISK;
```

Полный сброс к `.cnf` (с переименованием текущей базы): `proxysql --initial` / `systemctl start proxysql-initial` — см. «Начальная инициализация».

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | --- | :--- |
| Изменение через SQL не действует | Не выполнен `LOAD ... TO RUNTIME` | Выполните `LOAD` для соответствующей группы |
| Настройка пропала после перезапуска | Не выполнен `SAVE ... TO DISK` | Выполните `SAVE`; проверьте расхождение Memory/Disk |
| Правки `.cnf` не применяются | При наличии `proxysql.db` файл не читается | Внесите через SQL либо `LOAD ... FROM CONFIG`; полная переинициализация — `--initial` |
| `LOAD ADMIN` не применил `mysql-` переменную | Неверная группа переменных | Admin-переменные применяются `LOAD ADMIN`, MySQL — `LOAD MYSQL` |
| `LOAD ... FROM DISK` не применило правку | Перепутано направление | `FROM DISK` — Disk → Memory; для применения к процессу добавьте `LOAD ... TO RUNTIME` |
| `LOAD ... TO DISK` — ошибка | Такой формы не существует | Запись на диск — только `SAVE ... TO DISK` |
| Переменная не меняется, сводка показывает `Rejected` | Значение не проходит валидацию | Проверьте допустимый диапазон переменной; старое значение восстановлено автоматически |
| `mysql-interfaces`/`mysql-threads` не меняется | Переменная статическая | Требуется `PROXYSQL RESTART` или правка `.cnf` + `--initial` |
| Значение в Runtime отличается от Memory | Изменение не применено | `LOAD ... TO RUNTIME` |
| Значение в Memory отличается от Disk | Изменение не сохранено | `SAVE ... TO DISK` |
| Cluster перезаписал локальные правки | Изменение внесено на Satellite Node | Вносите изменения только на Core Node |
| Admin-доступ потерян после правки | Неверные `admin-admin_credentials` или `admin-mysql_ifaces` | Исправьте `.cnf` по SSH, перезапустите с `--initial` или `proxysql-initial` |
| Узел Cluster не синхронизируется | Неверные `admin-cluster_username`/`password` | Проверьте доступность admin-порта и учётные данные |
| `proxysql --initial` «не сработал» | Флаг переименовывает старую базу, а не проверяет её наличие | Старая база переименована — восстановите из бэкапа при необходимости |

### Обслуживание и очистка

```bash
# Бэкап базы данных ProxySQL перед изменениями.
# Для консистентности останавливайте службу перед копированием файла
systemctl stop proxysql
cp /var/lib/proxysql/proxysql.db /var/lib/proxysql/proxysql.db.bak
systemctl start proxysql
# → бэкап создан

# Восстановление
systemctl stop proxysql
cp /var/lib/proxysql/proxysql.db.bak /var/lib/proxysql/proxysql.db
systemctl start proxysql
# → ProxySQL запущен с восстановленной конфигурацией
```

```sql
-- Очистка устаревших переменных: сначала посмотреть, затем удалять
SELECT variable_name FROM global_variables
WHERE variable_value = '' OR variable_value = 'NULL'
ORDER BY variable_name;
```

**Процедура безопасного изменения конфигурации:**

```sql
-- 1. Зафиксировать текущее состояние
SAVE MYSQL VARIABLES TO DISK;
SAVE ADMIN VARIABLES TO DISK;
SAVE MYSQL SERVERS TO DISK;
SAVE MYSQL USERS TO DISK;
SAVE MYSQL QUERY RULES TO DISK;

-- 2. Внести изменение (в Memory)
UPDATE global_variables SET variable_value = '4000'
WHERE variable_name = 'mysql-max_connections';

-- 3. Применить и проверить
LOAD MYSQL VARIABLES TO RUNTIME;
SELECT variable_value FROM runtime_global_variables
WHERE variable_name = 'mysql-max_connections';

-- 4. Зафиксировать на диске
SAVE MYSQL VARIABLES TO DISK;

-- 5. При сбое — возврат к сохранённому состоянию
-- LOAD MYSQL VARIABLES FROM DISK;
-- LOAD MYSQL VARIABLES TO RUNTIME;
```

```bash
# Ротация логов: расположение задаёт переменная errorlog
# (в пакете по умолчанию — /var/lib/proxysql/proxysql.log)
ls -la /var/lib/proxysql/proxysql.log

# Ротация через Admin-интерфейс
mysql -h 127.0.0.1 -P 6032 -u admin -p -e "PROXYSQL FLUSH LOGS;"
```

## Дополнительная информация

### См. также
- **[ProxySQL: Обзор](./proxysql_overview.md)** — архитектура, установка и системные требования.
- **[ProxySQL: Безопасность](./proxysql_security.md)** — учётные данные, TLS, аудит.
- **[ProxySQL: HA и ProxySQL Cluster](./proxysql_ha_cluster.md)** — синхронизация конфигурации, checksum-сверка.
- **[ProxySQL: Failover и мониторинг репликации](./proxysql_failover.md)** — hostgroups и монитор.
- **[ProxySQL: Мониторинг](./proxysql_monitoring.md)** — метрики и применение изменений.
- **[ProxySQL: Connection Pool](./proxysql_connection_pool.md)** — переменные пула и multiplexing.

### Официальная документация
- [Multi-Layer Configuration System](https://proxysql.com/documentation/main-runtime/multi-layer-configuration) — теория четырёх слоёв.
- [Admin Commands](https://proxysql.com/documentation/the-admin-schemas/admin-commands/) — полный список LOAD/SAVE-команд и алиасов.
- [The Admin Schemas](https://proxysql.com/documentation/the-admin-schemas/) — схемы `main`, `disk`, `stats`, `monitor`.
- [Disk Admin Database](https://proxysql.com/documentation/the-admin-schemas/disk) — персистентные таблицы.
- [Global Variables](https://proxysql.com/documentation/global-variables/) — механика `UPDATE`/`SET`.
- [MySQL Variables](https://proxysql.com/documentation/global-variables/mysql-variables/) — справочник переменных и дефолтов.
- [Admin Variables](https://proxysql.com/documentation/global-variables/admin-variables/) — переменные Admin-интерфейса.
- [The ProxySQL Configuration File](https://proxysql.com/documentation/configuration-file) — формат `.cnf`.
- [Main Runtime MySQL Tables](https://proxysql.com/documentation/main-runtime/mysql-tables/) — таблицы конфигурации.
