# Zabbix — мониторинг баз данных

> **Актуальность:** материал сверен по состоянию на сентябрь 2026 г. Основная долгосрочная ветка — **Zabbix 7.0 LTS** (обновления до 30 июня 2027, ограниченная поддержка до 30 июня 2029). Текущая стандартная ветка — **Zabbix 8.0 LTS** (выпущена в сентябре 2026 г., поддержка до Q3 2029, ограниченная поддержка до Q3 2031). Особенности конкретных версий отмечены по тексту.

---

## Определения

**Мониторинг СУБД (Database Monitoring)** — процесс сбора, анализа и визуализации метрик производительности, доступности и состояния баз данных. Цель — своевременное выявление проблем, оптимизация производительности и обеспечение непрерывной работы СУБД.

**Уровни мониторинга СУБД:**
- **Инфраструктурный:** CPU, оперативная память, дисковая подсистема (I/O), сеть на сервере БД.
- **Экземпляр БД (Instance):** внутренние метрики СУБД (кэширование, блокировки, статус репликации, пулы соединений, свободное место в табличных пространствах).
- **SQL-производительность:** выявление медленных запросов (Slow Queries), анализ работы оптимизатора.
- **Сессии:** мониторинг активных соединений и транзакций.

**Zabbix Agent 2 Plugin** — нативный модуль Zabbix Agent 2 (написанный на Go), который подключается к СУБД напрямую по протоколу самой базы данных и возвращает метрики через встроенные ключи (например, `mysql.ping`, `pgsql.dbstat`, `redis.info`). Обеспечивает пулинг соединений (Connection Pooling), исключая накладные расходы на создание TCP-сессий для каждой проверки.

**ODBC (Open Database Connectivity)** — универсальный стандарт подключения к СУБД, позволяющий Zabbix Server или Zabbix Proxy выполнять SQL-запросы к базе данных без установки агента на целевой сервер (Agentless). Сбор выполняет процесс `odbc poller`.

**Master / Dependent Items** — архитектурный подход, при котором один «мастер-элемент» (Master Item) выполняет единственный SQL-запрос, возвращающий большой JSON, а зависимые элементы (Dependent Items) с помощью предобработки (JSONPath/Regex) извлекают из него отдельные метрики без повторных запросов к СУБД.

**Named Sessions (Именованные сессии)** — механизм безопасной конфигурации Zabbix Agent 2, при котором параметры подключения (URI, логин, пароль, TLS-сертификаты) хранятся локально в конфигурационном файле агента под уникальным именем, а не передаются в открытом виде через веб-интерфейс Zabbix.

**Connection Pooling** — механизм поддержания постоянного соединения с СУБД между опросами метрик, исключающий накладные расходы на создание новой TCP-сессии для каждого запроса. Встроен в нативные плагины Zabbix Agent 2. В контексте ODBC (классический драйвер) Connection Pooling отсутствует — каждому опросу соответствует новое подключение.

**ODBC Poller** — специализированный синхронный процесс Zabbix Server/Proxy, выполняющий ODBC-проверки. Изолирован от основных пассивных поллеров; при зависании ODBC-драйвера блокируется только `odbc poller`, а не весь сервер. Управляется параметром `StartODBCPollers`.

**unixODBC** — открытая реализация стандарта ODBC для Linux/Unix, предоставляющая драйверный менеджер и утилиты (`odbcinst`, `isql`) для регистрации драйверов и проверки подключений.

---

## Основные концепции

### Архитектура сбора данных

Мониторинг СУБД в Zabbix строится на трех уровнях, взаимодействующих через каналы сбора данных:

```
┌─────────────────────────────────────────────────────────────────┐
│                      Zabbix Frontend                            │
│                  (Визуализация, SLA, Alerts)                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────▼──────────────────────┐
              │     Zabbix Server / Proxy           │
              │  ┌─────────────┬──────────────┐     │
              │  │   Cache     │  Queue       │     │
              │  └──────┬──────┴──────┬──────┘     │
              │         │             │            │
              │  ┌──────▼──────┐ ┌──▼─────────┐   │
              │  │  Poller     │ │ ODBC Poller│   │
              │  │  (Agent 2)  │ │  (ODBC)    │   │
              │  └──────┬──────┘ └──┬─────────┘   │
              └────────┼───────────┼─────────────┘
                       │           │
          ┌────────────▼──┐  ┌────▼──────────────────┐
          │ Zabbix Agent 2│  │  ODBC Driver          │
          │  (Plugin)     │  │  (unixODBC)           │
          └────────────┬──┘  └────┬──────────────────┘
                       │          │
          ┌────────────▼──┐  ┌────▼──────────────────┐
          │  PostgreSQL   │  │  MySQL/MariaDB        │
          │  MySQL        │  │  Oracle               │
          │  Redis        │  │  MSSQL                │
          │  MongoDB      │  │  ...                  │
          └───────────────┘  └───────────────────────┘
```

1. **Zabbix Agent 2 (нативный плагин):** агент на Go с постоянным соединением (Connection Pooling) к СУБД. Выполняет опросы по команде Server/Proxy, возвращает JSON-метрики. Минимальная нагрузка на БД, рекомендован для всех новых инсталляций.
2. **ODBC Poller:** отдельный синхронный процесс Server/Proxy, выполняющий SQL-запросы через ODBC-драйвер. Подходит для Agentless-сценариев (установка агента невозможна) и кастомных SQL-запросов. Не поддерживает Connection Pooling.
3. **HTTP Agent:** альтернативный метод для СУБД с REST API (MongoDB, Cassandra). Выполняет HTTP-запросы напрямую с Server/Proxy, возвращает JSON/XML.

### Принципы эффективного мониторинга

1. **Master / Dependent Items:** Один SQL-запрос (Master Item) возвращает JSON с множеством метрик. Dependent Items с предобработкой JSONPath извлекают отдельные значения. Это снижает нагрузку на БД в 10–100 раз.
2. **Троттлинг (Throttling):** Использование шага `Discard unchanged with heartbeat` в предобработке для статических метрик (версия СУБД, параметры конфигурации), чтобы не забивать историю Zabbix избыточными данными.
3. **Безопасность (Named Sessions):** Хранение учетных данных не в макросах веб-интерфейса, а в защищенном конфигурационном файле агента. Обязательно при использовании TLS.
4. **Принцип наименьших привилегий:** выделенный пользователь мониторинга с правами только на чтение (REPLICATION CLIENT, PROCESS, SHOW DATABASES). Никогда не используйте суперпользователя.

### Выбор метода сбора данных

| Метод | Подключение | Connection Pooling | Платформы | Когда использовать |
| :--- | :--- | :---: | :--- | :--- |
| **Zabbix Agent 2 Plugin** | Прямой TCP | Да | PostgreSQL, MySQL/MariaDB/Percona, Oracle, MSSQL, MongoDB, Redis | Новые инсталляции, максимальная производительность |
| **ODBC** | Через драйвер | Нет | Все СУБД с ODBC-драйвером | Agentless, облачные БД, кастомные SQL |
| **HTTP Agent** | REST API | Н/A | MongoDB, Cassandra, Couchbase | СУБД с HTTP-интерфейсом |
| **UserParameter** | Кастомный скрипт | Нет | Любая | Устаревший метод, legacy |

### Выбор подхода по типу СУБД

| СУБД | Рекомендуемый подход | Альтернатива | Документация |
| :--- | :--- | :--- | :--- |
| **PostgreSQL** | Zabbix Agent 2 (loadable plugin) | ODBC | [zabbix_postgresql_monitoring.md](./zabbix_postgresql_monitoring.md) |
| **MySQL / MariaDB / Percona** | Zabbix Agent 2 (built-in plugin) | ODBC | [../Databases/MySQL/monitoring.md](../Databases/MySQL/monitoring.md) |
| **Oracle** | Zabbix Agent 2 (built-in plugin) | ODBC (`Oracle by ODBC`) | — |
| **MSSQL (SQL Server)** | Zabbix Agent 2 (loadable plugin) | ODBC (`MSSQL by ODBC`) | — |
| **MongoDB** | Zabbix Agent 2 (loadable plugin) | HTTP Agent | — |
| **Redis** | Zabbix Agent 2 (built-in plugin) | — | — |
| **Cassandra / ScyllaDB** | HTTP Agent / UserParameter | ODBC (ограниченно) | [../Databases/cassandra-scylladb/monitoring.md](../Databases/cassandra-scylladb/monitoring.md) |

### DevOps/SRE/Sysadmin контекст

Мониторинг баз данных — критический компонент наблюдаемости (Observability) инфраструктуры:

* **Four Golden Signals для БД:** SRE применяют метрики Zabbix для оценки Latency (время отклика запросов), Traffic (количество запросов/сек), Errors (ошибки подключения, deadlocks), Saturation (загрузка CPU, I/O, пул соединений). Zabbix триггеры на эти сигналы интегрируются с Alertmanager.
* **SLO/SLI для баз данных:** Zabbix SLA (8.0+) на основе тегов триггеров позволяет отслеживать Uptime СУБД, процент успешных транзакций и время отклика репликации. SRE используют эти данные для расчета SLI и оценки SLO.
* **Change Management:** все изменения в конфигурации мониторинга БД (пороги, шаблоны) проходят через процедуры управления изменениями. Версионный контроль шаблонов в Git обеспечивает аудит и откат.
* **Capacity Planning:** метрики роста БД (размер табличных пространств, количество соединений) используются для планированияCapacity. Zabbix графики трендов позволяют прогнозировать исчерпание диска или памяти.
* **Runbook Automation:** Actions в Zabbix могут выполнять скрипты автоматического восстановления при срабатывании триггеров БД (например, перезапуск репликации, очистка кэша, масштабирование пула соединений через API оркестратора).
* **Post-mortem Analysis:** события мониторинга БД сохраняются с полным контекстом (значения метрик, временные метки, теги). Это позволяет проводить постмортем-анализ инцидентов и выявлять системные причины падений.
* **Compliance и аудит:** мониторинг СУБД интегрируется с требованиями compliance (PCI DSS, GDPR, SOC 2). Zabbix обеспечивает сбор метрик безопасности (успешные/неуспешные подключения, изменения конфигурации) и хранение истории для аудита.
* **Интеграция с ITSM:** оповещения по падению БД интегрируются с Jira, GLPI, ServiceNow. При срабатывании триггера автоматически создается инцидент с приоритетом на основе серьезности (Severity).

---

## Практические сценарии

### Метод 1: Zabbix Agent 2 с нативным плагином (Рекомендуемый)

Нативный плагин обеспечивает максимальную производительность благодаря Connection Pooling и прямому доступу к системным представлениям СУБД.

#### Шаг 1. Подготовка СУБД (Создание пользователя)

Никогда не используйте суперпользователя (`root`, `postgres`, `sa`) для мониторинга. Создайте выделенного пользователя с правами только на чтение.

**PostgreSQL:**
```sql
CREATE USER zbx_monitor WITH PASSWORD 'your_secure_password' INHERIT;
GRANT pg_monitor TO zbx_monitor;
-- Или минимальные права:
GRANT USAGE ON SCHEMA public TO zbx_monitor;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO zbx_monitor;
FLUSH PRIVILEGES;
```

**MySQL / MariaDB:**
```sql
CREATE USER 'zbx_monitor'@'127.0.0.1' IDENTIFIED BY 'your_secure_password';
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'zbx_monitor'@'127.0.0.1';
-- Для MariaDB 10.5+ (репликация):
GRANT SLAVE MONITOR ON *.* TO 'zbx_monitor'@'127.0.0.1';
FLUSH PRIVILEGES;
```

**MSSQL:**
```sql
CREATE LOGIN zbx_monitor WITH PASSWORD = 'your_secure_password';
CREATE USER zbx_monitor FOR LOGIN zbx_monitor;
GRANT VIEW SERVER STATE TO zbx_monitor;
GRANT VIEW ANY DEFINITION TO zbx_monitor;
```

#### Шаг 2. Установка Zabbix Agent 2 и плагинов

**Ubuntu 24.04 / Zabbix 8.0:**
```bash
wget https://repo.zabbix.com/zabbix/8.0/release/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest+ubuntu24.04_all.deb
dpkg -i zabbix-release_latest+ubuntu24.04_all.deb
apt update
apt install zabbix-agent2 zabbix-agent2-plugin-*
systemctl restart zabbix-agent2
systemctl enable zabbix-agent2
```

**RHEL 9 / Rocky 9 / Zabbix 8.0:**
```bash
dnf install zabbix-release
dnf install zabbix-agent2 zabbix-agent2-plugin-postgresql zabbix-agent2-plugin-mongodb zabbix-agent2-plugin-mssql
systemctl restart zabbix-agent2
systemctl enable zabbix-agent2
```

Встроенные плагины (MySQL, Redis, Oracle) входят в пакет `zabbix-agent2` и не требуют отдельной установки.

#### Шаг 3. Настройка Named Sessions

Named Sessions хранят учетные данные локально в конфигурационном файле агента, предотвращая передачу паролей через веб-интерфейс Zabbix.

**Конфигурация для MySQL (файл `/etc/zabbix/zabbix_agent2.d/plugins.d/mysql.conf`):**
```ini
Plugins.Mysql.Sessions.ProdDB.Uri=tcp://127.0.0.1:3306
Plugins.Mysql.Sessions.ProdDB.User=zbx_monitor
Plugins.Mysql.Sessions.ProdDB.Password=your_secure_password
Plugins.Mysql.KeepAlive=300
```

**Конфигурация для PostgreSQL (файл `/etc/zabbix/zabbix_agent2.d/plugins.d/postgresql.conf`):**
```ini
Plugins.Pg.Sessions.ProdDB.Uri=tcp://127.0.0.1:5432
Plugins.Pg.Sessions.ProdDB.User=zbx_monitor
Plugins.Pg.Sessions.ProdDB.Password=your_secure_password
Plugins.Pg.KeepAlive=300
```

**Для нескольких инстансов на одном агенте:**
```ini
Plugins.Pg.Sessions.PrimaryDB.Uri=tcp://10.0.0.1:5432
Plugins.Pg.Sessions.PrimaryDB.User=zbx_monitor
Plugins.Pg.Sessions.PrimaryDB.Password=password1

Plugins.Pg.Sessions.ReplicaDB.Uri=tcp://10.0.0.2:5432
Plugins.Pg.Sessions.ReplicaDB.User=zbx_monitor
Plugins.Pg.Sessions.ReplicaDB.Password=password2
```

В веб-интерфейсе Zabbix в макрос `{$PG.DSN}` вписывается только имя сессии: `ProdDB`.

#### Шаг 4. Настройка элементов данных и Master/Dependent Items

**Master Item (собирает JSON одним запросом):**
- **Type:** `Zabbix agent (active)`
- **Key:** `pgsql.get[{$PG.DSN}]` или `mysql.get_status[{$MYSQL.DSN}]`
- **Type of information:** `JSON`
- **Update interval:** `1m`

**Dependent Items (извлекают метрики из JSON):**
- **Type:** `Dependent item`
- **Master item:** выберите Master Item
- **Preprocessing:** `JSONPath` → `$.connections.active`

Примеры зависимых элементов:
| Имя элемента | JSONPath | Type of information |
| :--- | :--- | :--- |
| Connections active | `$.connections.active` | Numeric (unsigned) |
| Transactions per second | `$.tps` | Numeric (float) |
| Cache hit ratio | `$.cache.hit_ratio` | Numeric (float) |
| Replication lag | `$.replication.lag` | Numeric (unsigned) |

#### Шаг 5. Валидация подключения

```bash
# Проверка работы агента
zabbix_get -s 127.0.0.1 -k "pgsql.ping[ProdDB]"
# → 1 (успешное подключение)

# Проверка получения JSON (Master Item)
zabbix_get -s 127.0.0.1 -k "pgsql.get[ProdDB]"
# → {"connections":{"active":5,"total":1200},...}

# Проверка конкретной метрики
zabbix_get -s 127.0.0.1 -k "pgsql.stat[ProdDB,datid]"
# → 16384 (OID базы данных)
```

### Метод 2: ODBC (Agentless)

Метод без установки агента на целевой сервер. Используется для облачных БД, кастомных SQL-запросов и ситуаций, где установка ПО невозможна.

#### Шаг 1. Установка unixODBC и драйвера

```bash
# Debian/Ubuntu
sudo apt install unixodbc
sudo apt install odbc-mariadb          # драйвер MariaDB (рекомендуется даже для MySQL)
sudo apt install odbc-postgresql       # драйвер PostgreSQL

# RHEL/Rocky/Alma
sudo dnf install unixODBC unixODBC-devel mariadb-connector-odbc postgresql-odbc
```

**Таблица пакетов драйверов:**

| СУБД | Пакет (Debian/Ubuntu) | Пакет (RHEL/Rocky/Alma) |
| :--- | :--- | :--- |
| MySQL / MariaDB | `odbc-mariadb` | `mariadb-connector-odbc` |
| PostgreSQL | `odbc-postgresql` | `psqlodbc` |
| SQL Server | `msodbcsql18` | `msodbcsql18` |
| SQL Server (FreeTDS) | `tdsodbc` | `freetds-odbc` |

#### Шаг 2. Настройка `/etc/odbcinst.ini` (реестр драйверов)

```ini
[MariaDB]
Description = MariaDB ODBC Driver
Driver = /usr/lib64/libmaodbc.so

[PostgreSQL]
Description = PostgreSQL ODBC Driver
Driver = /usr/lib64/psqlodbc.so
```

Проверка:
```bash
odbcinst -q -d
# → MariaDB
# → PostgreSQL
```

#### Шаг 3. Настройка `/etc/odbc.ini` (DSN)

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

> **Безопасность:** `sudo chmod 600 /etc/odbc.ini` — файл содержит учетные данные.

#### Шаг 4. Проверка подключения через `isql`

```bash
isql InventoryDB
# → +---------------------------------------+
# → | Connected!                            |
# → | sql-statement                         |
# → +---------------------------------------+
# → SQL>
```

#### Шаг 5. Настройка поллеров

```bash
# В zabbix_server.conf или zabbix_proxy.conf:
StartODBCPollers=5
```

Рекомендации: начинайте с 3–5 поллеров. Слишком малое число приводит к очередям и статусу `Unsupported`; слишком большое — к перегрузке СУБД. Если поллеры заняты из-за медленных запросов, сначала оптимизируйте SQL.

#### Шаг 6. Создание элементов данных

| Ключ | Назначение |
| :--- | :--- |
| `db.odbc.select[<описание>,<DSN>,<connect_string>]` | Возвращает одно значение (первая колонка первой строки). |
| `db.odbc.get[<описание>,<DSN>,<connect_string>]` | Возвращает множество строк/колонок в JSON (идеален как Master Item). |
| `db.odbc.discovery[<описание>,<DSN>,<connect_string>]` | Возвращает данные для LLD. |

Пример:
- **Type:** `Database monitor`
- **Key:** `db.odbc.select[pgsql_active,PostgreSQL-Zabbix]`
- **SQL query:** `SELECT count(*) FROM pg_stat_activity;`

Готовые шаблоны: `MySQL by ODBC`, `PostgreSQL by ODBC`, `MSSQL by ODBC` и др.

> **Best Practice:** всегда запускайте ODBC-проверки через Zabbix Proxy. Прокси изолирует Server от зависаний ODBC-драйвера.

### Метод 3: UserParameter (Внешние скрипты — Legacy)

Используется для специфической логики, не реализуемой через плагины или ODBC. Устаревший метод.

```bash
# В /etc/zabbix/zabbix_agentd.conf:
UserParameter=db.custom.query,/opt/scripts/custom_db_check.sh
```

Недостатки: новый процесс ОС на каждую метрику, новое подключение к БД, низкая производительность.

---

## Операции и команды

### Валидация подключения Zabbix Agent 2

```bash
# Проверка доступности агента
zabbix_get -s <host_agent> -k "agent.ping"
# → 1 (агент доступен)

# Проверка подключения к СУБД (PostgreSQL)
zabbix_get -s <host_agent> -k "pgsql.ping[{$PG.DSN}]"
# → 1 (подключение успешно) или 0 (ошибка)

# Проверка подключения к СУБД (MySQL)
zabbix_get -s <host_agent> -k "mysql.ping[{$MYSQL.DSN}]"
# → 1 (подключение успешно)
```

### Валидация ODBC

```bash
# Проверка DSN
isql <DSN_NAME>
# → Connected!

# Проверка элемента данных ODBC
zabbix_get -s <host_proxy> -k "db.odbc.select[check,<DSN>]"
# → значение или ошибка
```

### Валидация Master/Dependent Items

```bash
# Получение JSON от Master Item
zabbix_get -s <host_agent> -k "pgsql.get[{$PG.DSN}]"
# → {"connections":{"active":5,...},...}

# Проверка конкретной метрики из Dependent Item
zabbix_get -s <host_agent> -k "pgsql.stat[{$PG.DSN},datid]"
# → 16384
```

### Управление конфигурацией

```bash
# Проверка загруженных плагинов Agent 2
zabbix_agent2 -t plugins
# → mysql, postgresql, mongodb, ...

# Перезагрузка конфигурации агента
systemctl reload zabbix-agent2
# → (без вывода при успехе)

# Проверка ODBC-драйверов
odbcinst -q -d
# → MariaDB
# → PostgreSQL

# Проверка DSN
odbcinst -q -s
# → InventoryDB
```

### Мониторинг очереди и производительности

```bash
# Проверка очереди на опрос (включая ODBC)
zabbix_get -s 127.0.0.1 -k "zabbix[queue,5m]"
# → количество элементов с опозданием опроса за 5 минут

# Проверка занятости ODBC-поллеров
zabbix_get -s 127.0.0.1 -k "zabbix[process,odbc poller,avg,busy]"
# → средняя занятость процесса в %

# Проверка занятости обычных поллеров
zabbix_get -s 127.0.0.1 -k "zabbix[process,poller,avg,busy]"
# → средняя занятость процесса в %
```

### Runtime Control

```bash
# Повысить уровень логирования для диагностики
zabbix_server -R log_level_increase='odbc poller'
# → Debug level 4 для всех ODBC-поллеров

# Возврат к стандартному уровню
zabbix_server -R log_level_decrease='odbc poller'
```

---

## Устранение неисправностей

### Типичные симптомы

| Симптом | Вероятная причина |
| :--- | :--- |
| **Master Item в статусе Unsupported** | Неверный DSN/URI, учетные данные неверны, СУБД недоступна, плагин Agent 2 не установлен. |
| **ODBC элемент Unsupported** | DSN не настроен, драйвер ODBC не установлен, `StartODBCPollers=0`, сетевой доступ к БД закрыт. |
| **Dependent Item возвращает пустое значение** | Неверный JSONPath, Master Item возвращает невалидный JSON, данные отсутствуют в ответе. |
| **Высокая нагрузка на БД от мониторинга** | Отсутствует Master/Dependent Items (много отдельных запросов), слишком маленький интервал опроса, нет троттлинга. |
| **"Too many connections" на БД** | Connection Pooling не работает (UserParameter), слишком много хостов с ODBC-проверками, лимит `max_connections` исчерпан. |
| **Пароли в открытом виде в веб-интерфейсе** | Не настроены Named Sessions, учетные данные передаются через макросы веб-интерфейса. |
| **ODBC поллер зависает** | Сетевой сбой, драйвер ODBC не поддерживает таймаут, `StartODBCPollers` слишком большое. |

### Быстрая диагностика

1. **Проверьте доступность СУБД:**
   ```bash
   # PostgreSQL
   pg_isready -h 127.0.0.1 -p 5432
   # → 127.0.0.1:5432 - accepting connections

   # MySQL
   mysqladmin ping -h 127.0.0.1 -u zbx_monitor -p
   # → mysqld is alive
   ```

2. **Проверьте подключение Agent 2:**
   ```bash
   zabbix_get -s 127.0.0.1 -k "pgsql.ping[ProdDB]"
   # → 1 (успех) или 0 (ошибка)
   ```

3. **Проверьте ODBC:**
   ```bash
   odbcinst -q -d
   # → список драйверов (должен содержать нужный драйвер)

   isql <DSN_NAME>
   # → Connected! (успех) или ошибка
   ```

4. **Проверьте логи:**
   ```bash
   # Логи Zabbix Agent 2
   journalctl -u zabbix-agent2 -n 50
   # → ошибки плагинов, подключения

   # Логи Zabbix Server (ODBC ошибки)
   tail -100 /var/log/zabbix/zabbix_server.log | grep -i odbc
   # → ошибки драйверов, таймауты
   ```

5. **Диагностика очереди:**
   ```bash
   zabbix_get -s 127.0.0.1 -k "zabbix[queue,5m]"
   # → >0 означает проблемы с опросом
   ```

### Распространенные проблемы

| Проблема | Причины | Решение |
| :--- | :--- | :--- |
| **Master Item Unsupported** | Неверный DSN, пароль, СУБД остановлена | Проверьте конфигурацию Named Sessions, доступность СУБД |
| **ODBC зависает** | Драйвер без таймаута, сетевой сбой | Запускайте через Proxy, увеличьте `StartODBCPollers` с осторожностью |
| **"Too many connections"** | Connection Pooling отключен, много ODBC-проверок | Перейдите на Agent 2, ограничьте число ODBC-проверок |
| **Пустые Dependent Items** | Неверный JSONPath, Master Item возвращает null | Проверьте JSONPath в тестировании, убедитесь что Master Item возвращает данные |
| **Пароли в веб-интерфейсе** | Named Sessions не настроены | Настройте Named Sessions в конфигурационном файле агента |
| **Высокая нагрузка на БД** | Много отдельных запросов, маленький интервал | Используйте Master/Dependent Items, увеличьте интервал опроса |

Для глубокой диагностики смотрите разделы:
- **[Мониторинг PostgreSQL в Zabbix](./zabbix_postgresql_monitoring.md)** — специфичные для PostgreSQL проблемы и решения
- **[Тюнинг и производительность Zabbix](./zabbix_troubleshooting_and_performance_tuning.md)** — оптимизация поллеров и кэшей
- **[Лучшие практики настройки Zabbix](./zabbix_best_practices.md)** — шаблоны, триггеры, тегирование

---

## Лучшие практики

### Безопасность

* **Никогда не используйте суперпользователя** (`root`, `postgres`, `sa`, `SYSDBA`) для мониторинга. Создайте выделенного пользователя с минимально необходимыми правами (REPLICATION CLIENT, PROCESS, SHOW DATABASES, SELECT на системные схемы).
* **Используйте Named Sessions** для хранения учетных данных локально в конфигурационном файле агента, а не в макросах веб-интерфейса Zabbix.
* **Включите TLS/SSL** для соединения между агентом и СУБД. Named Sessions поддерживают указание TLS-сертификатов.
* **Ограничьте права доступа к конфигурационным файлам:** `chmod 600 /etc/zabbix/zabbix_agent2.d/plugins.d/*.conf`.
* **Храните пароли в Vault** при использовании макросов Zabbix. Zabbix 8.0 поддерживает секреты в Vault для макросов.
* **Ограничьте сетевой доступ:** пользователь мониторинга должен подключаться только с IP-адреса Zabbix Agent/Proxy.

### Производительность

* **Используйте Master/Dependent Items** для снижения нагрузки на БД. Один запрос вместо десятков.
* **Применяйте троттлинг** для статических метрик: `Discard unchanged with heartbeat` в предобработке.
* **Начинайте с значений по умолчанию** для интервалов опроса (60s) и увеличивайте только при необходимости.
* **Мониторьте занятость поллеров:** `zabbix[process,poller,avg,busy]` и `zabbix[process,odbc poller,avg,busy]`. При устойчивой загрузке выше 75% — масштабируйте.
* **Используйте Connection Pooling** (Zabbix Agent 2) вместо ODBC, где возможно. ODBC создает новое подключение на каждый запрос.
* **Для ODBC всегда используйте Zabbix Proxy** — изоляция от зависаний драйвера.

### Надежность

* **Мониторьте доступность СУБД отдельно:** создайте хост для каждой критической СУБД с элементами `db.ping` или `pgsql.ping` и триггерами на `last()=0`.
* **Настраивайте гистерезис для триггеров БД:** используйте отдельное Recovery Expression для предотвращения дребезга при временных сбоях.
* **Используйте Problem Suppression** для плановых работ на СУБД (обновление, бэкапы).
* **Настраивайте Maintenance** для плановых остановок СУБД.
* **Версионируйте шаблоны в Git:** изменения в порогах и конфигурации проходят через процедуры управления изменениями.
* **Тестируйте триггеры в staging** перед применением в production.

### Масштабирование

* **Используйте Zabbix Proxy Groups** (Zabbix 8.0) для распределения сбора данных при большом числе СУБД.
* **Разделите поллеры по типам:** ODBC-поллеры отдельно от обычных пассивных проверок.
* **При большом числе СУБД (>100)** используйте несколько Zabbix Proxy, каждый со своим набором проверок.

---

## Дополнительная информация

### См. также

* **[Определения и концепции Zabbix](./definitions_and_concepts.md)** — архитектурный обзор системы и базовые термины.
* **[Мониторинг PostgreSQL в Zabbix](./zabbix_postgresql_monitoring.md)** — детальная настройка мониторинга PostgreSQL.
* **[Мониторинг MySQL: Zabbix, Prometheus и PMM](../Databases/MySQL/monitoring.md)** — детальная настройка мониторинга MySQL/MariaDB.
* **[Низкоуровневое обнаружение (LLD)](./low_level_discovery.md)** — автоматизация поиска баз данных, табличных пространств и слотов репликации.
* **[Тюнинг и производительность Zabbix](./zabbix_troubleshooting_and_performance_tuning.md)** — оптимизация инфраструктуры мониторинга.

### Источники и ссылки

* Официальная документация Zabbix 8.0: [https://www.zabbix.com/documentation/8.0/en/manual](https://www.zabbix.com/documentation/8.0/en/manual)
* Release Notes Zabbix 8.0 LTS: [https://www.zabbix.com/rn/rn8.0.0](https://www.zabbix.com/rn/rn8.0.0)
* Roadmap Zabbix: [https://www.zabbix.com/roadmap](https://www.zabbix.com/roadmap)
