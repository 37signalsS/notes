# Zabbix — мониторинг баз данных

## Определения

**Мониторинг СУБД (Система Управления Базами Данных) в Zabbix** — процесс сбора, анализа и визуализации метрик производительности, доступности и состояния баз данных. Цель — своевременное выявление проблем, оптимизация производительности и обеспечение непрерывной работы СУБД.

**Уровни мониторинга СУБД:**

- **Инфраструктурный:** CPU (Центральное процессорное устройство), оперативная память, дисковая подсистема (I/O), сеть на сервере БД.
- **Экземпляр БД (Instance):** внутренние метрики СУБД (кэширование, блокировки, статус репликации, пулы соединений, свободное место в табличных пространствах).
- **SQL-производительность:** выявление медленных запросов (Slow Queries), анализ работы оптимизатора.
- **Сессии:** мониторинг активных соединений и транзакций.

**Zabbix Agent 2 Plugin** — нативный модуль Zabbix Agent 2 (написанный на Go), который подключается к СУБД напрямую по протоколу самой базы данных и возвращает метрики через встроенные ключи (например, `mysql.ping`, `pgsql.dbstat`, `redis.info`). Обеспечивает пулинг соединений (Connection Pooling), исключая накладные расходы на создание TCP-сессий для каждой проверки.

**ODBC (Open Database Connectivity)** — универсальный стандарт подключения к СУБД, позволяющий Zabbix Server или Zabbix Proxy выполнять SQL-запросы к базе данных без установки агента на целевой сервер (Agentless). Сбор выполняет процесс `odbc poller`.

**Master / Dependent Items** — архитектурный подход, при котором один «мастер-элемент» (Master Item) выполняет единственный SQL-запрос, возвращающий большой JSON, а зависимые элементы (Dependent Items) с помощью предобработки (JSONPath/Regex) извлекают из него отдельные метрики без повторных запросов к СУБД.

**Named Sessions (Именованные сессии)** — механизм безопасной конфигурации Zabbix Agent 2, при котором параметры подключения (URI, логин, пароль, TLS-сертификаты) хранятся локально в конфигурационном файле агента под уникальным именем, а не передаются в открытом виде через веб-интерфейс Zabbix.

---

## Основные концепции

### Подходы к мониторингу в современных версиях Zabbix (7.0+)

Эффективный мониторинг СУБД в Zabbix строится на принципах минимизации нагрузки на базу данных и безопасности подключения.

1. **Master / Dependent Items:** Вместо того чтобы выполнять 100 запросов для получения 100 метрик, Zabbix выполняет один SQL-запрос, который возвращает большой JSON (Master Item). Затем зависимые элементы (Dependent Items) с помощью JSONPath извлекают нужные значения. Это кардинально снижает нагрузку на БД.
2. **Троттлинг (Throttling):** Использование шага `Discard unchanged with heartbeat` в предобработке для статических метрик (например, версии СУБД), чтобы не забивать историю Zabbix избыточными данными.
3. **Безопасность (Named Sessions):** Хранение учетных данных для подключения к БД не в макросах веб-интерфейса в открытом виде, а в защищенном конфигурационном файле агента.

### Выбор метода сбора данных

Для мониторинга баз данных в Zabbix применяются три основных метода.

#### 1. Zabbix Agent 2 (Нативные плагины) — *Рекомендуемый метод*
Версия агента на языке Go с нативными плагинами для СУБД.
- **Преимущества:** Поддерживает постоянные соединения (Connection Pooling), что исключает накладные расходы на создание TCP-сессий для каждой проверки. Максимальная производительность и безопасность. Многие шаблоны построены на Master/Dependent Items и LLD, что дополнительно снижает нагрузку.
- **Типы плагинов:**
  - **Встроенные (Built-in):** MySQL, Oracle, Redis — входят в пакет Zabbix Agent 2, дополнительная установка не требуется.
  - **Загружаемые (Loadable) — требуют отдельной установки:** PostgreSQL, MSSQL, MongoDB. На Linux устанавливаются отдельными пакетами, например:
    ```bash
    sudo apt install zabbix-agent2-plugin-postgresql zabbix-agent2-plugin-mssql zabbix-agent2-plugin-mongodb
    # → пакеты плагинов устанавливаются отдельно от самого агента
    ```
    (для RHEL-подобных систем — `dnf install zabbix-agent2-plugin-postgresql` и т.д.)
- **Примеры:** [Мониторинг PostgreSQL](./zabbix_postgresql_monitoring.md), [Мониторинг MySQL](../Databases/MySQL/monitoring.md).

#### 2. ODBC (Open Database Connectivity)
Универсальный драйвер для прямого подключения Zabbix Server или Zabbix Proxy к СУБД по сети (Agentless).
- **Применение:** Мониторинг управляемых облачных баз данных (AWS RDS, Yandex Managed Databases), где невозможна установка агента, либо выполнение сложных кастомных SQL-запросов.
- **Преимущества:** Не требует установки ПО на целевой сервер. Готовые шаблоны из коробки (`MariaDB by ODBC`, `MySQL by ODBC`, `MSSQL by ODBC`, `Oracle by ODBC`, `PostgreSQL by ODBC`, `Percona by ODBC`).
- **Best Practice:** **Всегда** запускайте ODBC-проверки через Zabbix Proxy. Если ODBC-драйвер зависнет (что случается при сетевых сбоях), он заблокирует процесс поллера. Прокси изолирует Zabbix Server от таких проблем. Рекомендуется использовать MariaDB ODBC Connector даже для MySQL.
- Подробная пошаговая настройка — в разделе [Практические сценарии](#одbc-пошаговая-настройка).

#### 3. UserParameter (Внешние скрипты) — *Устаревший метод (Legacy)*
Использование кастомных bash/python скриптов, вызываемых классическим Zabbix Agent.
- **Недостатки:** Низкая производительность (для каждой метрики порождается новый процесс ОС и создается новое подключение к БД). Следует избегать в новых инсталляциях.

---

## Практические сценарии

### Выбор подхода по типу СУБД

| СУБД | Рекомендуемый подход | Обоснование / Документация |
| :--- | :--- | :--- |
| **PostgreSQL** | Zabbix Agent 2 (loadable plugin) | Нативная поддержка, низкая нагрузка. [Настройка PostgreSQL](./zabbix_postgresql_monitoring.md) |
| **MySQL / MariaDB / Percona** | Zabbix Agent 2 (built-in plugin) | Нативная поддержка, пулинг соединений. [Настройка MySQL](../Databases/MySQL/monitoring.md) |
| **Oracle** | Zabbix Agent 2 (built-in plugin) или ODBC | Нативный плагин Oracle присутствует «из коробки»; ODBC — классический Agentless-вариант с шаблоном `Oracle by ODBC`. |
| **MSSQL (SQL Server)** | Zabbix Agent 2 (loadable plugin) или ODBC | Плагин `mssql` требует отдельной установки; ODBC-шаблон `MSSQL by ODBC` покрывает метрики без агента на хосте. |
| **MongoDB** | Zabbix Agent 2 (loadable plugin) или HTTP Agent | Плагин `mongodb` требует отдельной установки; альтернатива — REST API через HTTP-агент. |
| **Redis** | Zabbix Agent 2 (built-in plugin) | Нативная поддержка (`redis.info`, `redis.ping`, `redis.slowlog.count`). |
| **Managed DB (Облако)** | ODBC | Доступ к ОС закрыт провайдером. Идеальный сценарий для ODBC. |

### ODBC: пошаговая настройка

ODBC-компоненты (unixODBC и драйверы) устанавливаются на **Zabbix Server или Zabbix Proxy**, который выполняет проверки, а не на мониторируемый хост БД.

#### Шаг 1. Установка unixODBC и драйвера

```bash
# Дебиан/Убунту
sudo apt install unixodbc
sudo apt install odbc-mariadb          # драйвер MariaDB (рекомендуется даже для MySQL)
sudo apt install odbc-postgresql       # драйвер PostgreSQL

# RHEL/Rocky/Alma
sudo dnf install unixODBC unixODBC-devel mariadb-connector-odbc postgresql-odbc
```

Рекомендуемая таблица пакетов драйверов:

| СУБД | Пакет (Debian/Ubuntu) | Пакет (RHEL/Rocky/Alma) |
| :--- | :--- | :--- |
| MySQL / MariaDB | `odbc-mariadb` | `mariadb-connector-odbc` |
| PostgreSQL | `odbc-postgresql` | `psqlodbc` |
| SQL Server | `msodbcsql18` | `msodbcsql18` |
| SQL Server (Open Source) | `tdsodbc` (FreeTDS) | `freetds-odbc` |

#### Шаг 2. Настройка `/etc/odbcinst.ini` (реестр драйверов)

Регистрирует установленные драйверы под символическими именами. Путь `Driver` должен указывать на установленный `.so`-файл:

```ini
[MariaDB]
Description = MariaDB ODBC Driver
Driver = /usr/lib64/libmaodbc.so

[PostgreSQL]
Description = PostgreSQL ODBC Driver
Driver = /usr/lib64/psqlodbc.so
```

Проверка реестра драйверов:

```bash
odbcinst -q -d
# → MariaDB
# → PostgreSQL
# → ... (список зарегистрированных драйверов)
```

#### Шаг 3. Настройка `/etc/odbc.ini` (определение DSN)

Каждая секция в квадратных скобках — это DSN (Data Source Name), на который ссылаются элементы данных Zabbix:

```ini
[InventoryDB]
Description = Production Inventory Database
Driver = MariaDB
Server = 192.168.1.50
Port = 3306
Database = shop_db
User = zbx_monitor
Password = secure_password
```

> **Безопасность:** файл `/etc/odbc.ini` содержит учетные данные. Немедленно ограничьте права доступа: `sudo chmod 600 /etc/odbc.ini`.

#### Шаг 4. Проверка подключения через `isql`

До настройки элементов данных Zabbix обязательно протестируйте DSN напрямую:

```bash
isql InventoryDB
# → +---------------------------------------+
# → | Connected!                            |
# → | sql-statement                         |
# → +---------------------------------------+
# → SQL>
```

#### Шаг 5. Настройка поллеров

Параметр `StartODBCPollers` в `zabbix_server.conf` (или `zabbix_proxy.conf`) управляет количеством процессов `odbc poller`, выполняющих ODBC-проверки:

```bash
StartODBCPollers=5
```

Рекомендации по масштабированию: начинайте с 3–5 поллеров для небольших инсталляций и следите за процентом занятости ODBC-поллеров во внутренних метриках Zabbix. Слишком малое число приводит к очередям и статусу `Unsupported`; слишком большое — к перегрузке СУБД одновременными соединениями. Если поллеры постоянно заняты из-за медленных запросов, сначала оптимизируйте SQL-запрос, а не увеличивайте число поллеров.

#### Шаг 6. Создание элементов данных в веб-интерфейсе

Тип элемента — **Database monitor**, ключи ODBC:

| Ключ | Назначение |
| :--- | :--- |
| `db.odbc.select[<описание>,<DSN>,<connect_string>]` | Возвращает одно значение (первая колонка первой строки результата SQL). |
| `db.odbc.get[<описание>,<DSN>,<connect_string>]` | Возвращает множество строк/колонок в JSON (идеален как Master Item). |
| `db.odbc.discovery[<описание>,<DSN>,<connect_string>]` | Возвращает данные для низкоуровневого обнаружения (LLD). |

Пример элемента данных:

| Параметр | Значение |
| :--- | :--- |
| Тип | Database monitor |
| Ключ | `db.odbc.select[pgsql_active,PostgreSQL-Zabbix]` |
| SQL query | `SELECT count(*) FROM pg_stat_activity;` |

Альтернативный способ — привязка готового шаблона (`MySQL by ODBC`, `PostgreSQL by ODBC` и т.д.), в котором макрос `{$MYSQL.DSN}` / `{$PG.DSN}` указывает на имя настроенного DSN.

### Рекомендации по безопасности и правам доступа

**Никогда не используйте суперпользователя (`root` / `postgres`) для мониторинга.**
Для Zabbix необходимо создавать выделенного пользователя с правами "только для чтения".

Пример минимальных прав для **MySQL/MariaDB**:
```sql
CREATE USER 'zbx_monitor'@'127.0.0.1' IDENTIFIED BY 'secure_password';
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'zbx_monitor'@'127.0.0.1';
-- Для MariaDB 10.5+ дополнительно (для метрик репликации):
GRANT SLAVE MONITOR ON *.* TO 'zbx_monitor'@'127.0.0.1';
FLUSH PRIVILEGES;
```

При использовании **Zabbix Agent 2**, настраивайте `Named Sessions` в файле конфигурации плагина (например, `/etc/zabbix/zabbix_agent2.d/plugins.d/mysql.conf`):
```ini
Plugins.Mysql.Sessions.ProdDB.Uri=tcp://127.0.0.1:3306
Plugins.Mysql.Sessions.ProdDB.User=zbx_monitor
Plugins.Mysql.Sessions.ProdDB.Password=secure_password
```
Затем в веб-интерфейсе Zabbix в макрос `{$MYSQL.DSN}` вписывается только имя сессии: `ProdDB`.

---

## Дополнительная информация

### Связанные темы

- **[Определения и концепции Zabbix](./definitions_and_concepts.md)** — общая архитектура Zabbix.
- **[Низкоуровневое обнаружение (LLD)](./low_level_discovery.md)** — автоматизация поиска баз данных, табличных пространств и слотов репликации.
- **[Тюнинг и диагностика Zabbix](./zabbix_troubleshooting_and_performance_tuning.md)** — оптимизация производительности поллеров при мониторинге тяжелых баз данных.
