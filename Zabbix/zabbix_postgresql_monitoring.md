# Мониторинг PostgreSQL в Zabbix

## Определения

**Zabbix Agent 2 PostgreSQL Plugin** — специализированный загружаемый модуль (loadable plugin) для Zabbix Agent 2, обеспечивающий сбор метрик PostgreSQL через нативные системные представления (`pg_stat_*`). Начиная с версий Zabbix 6.0.10 / 6.2.4 / 6.4 плагин вынесен из основного бинарника агента в отдельный пакет `zabbix-agent2-plugin-postgresql` (или собирается из исходников).

**Low-Level Discovery (LLD) для PostgreSQL** — механизм автоматического обнаружения баз данных и слотов репликации, позволяющий динамически создавать элементы данных (Items) и триггеры без ручной настройки каждой сущности. Реализуется правилами `pgsql.db.discovery` (базы данных) и `pgsql.replication.process.discovery` (репликация).

**Named Sessions (Именованные сессии)** — механизм конфигурации Zabbix Agent 2, при котором параметры подключения (URI, логин, пароль, TLS-сертификаты) хранятся локально в конфигурационном файле плагина под уникальным именем. Обязательны для TLS-шифрованного подключения и удобны для мониторинга нескольких инстансов СУБД одним агентом.

**pg_monitor** — встроенная роль (предопределенная) PostgreSQL, предоставляющая права на чтение статистических представлений `pg_stat_*`, `pg_statio_*` и связанных функций. Назначается выделенному пользователю для мониторинга вместо выдачи прав суперпользователя.

**Connection Pooling** — постоянное соединение агента с СУБД, удерживаемое между опросами метрик, что существенно снижает нагрузку по сравнению с созданием нового подключения на каждый запрос (как в ODBC-подходе).

**Named Session + CacheMode** — параметр именованной сессии, задающий способ выполнения подготовленных запросов. Режим `describe` необходимо использовать при работе через пулеры соединений (PgBouncer).

---

## Основные концепции

Мониторинг PostgreSQL в Zabbix (6.0.10+/7.x/8.x) строится исключительно на **Zabbix Agent 2** со специализированным плагином. Этот подход обеспечивает глубокий мониторинг и высокую производительность благодаря постоянному пулингу соединений (Connection Pooling). Сравнение с альтернативными методами (ODBC, UserParameter) — в **[Мониторинг Баз Данных с помощью Zabbix](./zabbix_database_monitoring.md)**.

Ключевые механизмы шаблона:

* **Низкоуровневое обнаружение (LLD):**
  * **Database discovery** (`pgsql.db.discovery`) — автоматическое обнаружение баз данных (исключая шаблонные и запрещающие подключение); в момент создания новой БД система автоматически начинает собирать её метрики.
  * **Replication discovery** (`pgsql.replication.process.discovery`) — обнаружение `application_name` WAL-отправителей и мониторинг отставания потоковой репликации (write / flush / replay lag).
  * Фильтры LLD задаются макросами `{$PG.LLD.FILTER.DBNAME}` и `{$PG.LLD.FILTER.APPLICATION}` (по умолчанию `.+` — обнаруживать все).
* **Учётные данные:** Базовый способ — указуются макросы шаблона (`{$PG.USER}`, `{$PG.PASSWORD}`, `{$PG.DATABASE}`). **Named Sessions** обязателен, если требуется SSL/TLS-шифрование соединения, а также рекомендован при мониторинге нескольких инстансов СУБД на одном агенте — пароли и сертификаты остаются в локальном файле агента и не передаются в открытом виде в веб-интерфейс Zabbix.

---

## Практические сценарии

### Шаг 1. Подготовка СУБД PostgreSQL

1. **Создание выделенного пользователя для мониторинга:**
   Никогда не используйте суперпользователя (`postgres`).
   ```sql
   CREATE USER zbx_monitor WITH PASSWORD 'your_secure_password' INHERIT;
   -- Предоставление системной роли для чтения статистики (PostgreSQL 10+)
   GRANT pg_monitor TO zbx_monitor;
   ```
   Официальный шаблон тестируется на PostgreSQL 10–17.

2. **Включение `pg_stat_statements` (Обязательно для метрик запросов):**
   * В файле `postgresql.conf` добавьте: `shared_preload_libraries = 'pg_stat_statements'`
   * Перезагрузите сервис PostgreSQL.
   * Выполните `CREATE EXTENSION pg_stat_statements;` в целевых базах данных.

3. **Настройка доступов в `pg_hba.conf`:**
   Разрешите агенту подключаться локально или по сети:
   ```text
   # TYPE  DATABASE        USER            ADDRESS                 METHOD
   host    all             zbx_monitor     127.0.0.1/32            scram-sha-256
   host    all             zbx_monitor     ::1/128                 scram-sha-256
   # Для Unix-сокетов:
   local   all             zbx_monitor                             scram-sha-256
   ```

### Шаг 2. Установка и настройка плагина (Zabbix Agent 2)

1. **Установка пакета:**
   Плагин устанавливается отдельно от самого агента:
   ```bash
   # Дебиан/Убунту
   sudo apt install zabbix-agent2-plugin-postgresql

   # RHEL / Rocky / AlmaLinux
   sudo dnf install zabbix-agent2-plugin-postgresql
   ```
   Проверка загрузки плагина:
   ```bash
   zabbix_agent2 -t pgsql.ping["tcp://127.0.0.1:5432","zbx_monitor","password","postgres"]
   # → {"status":"up"}
   ```

2. **Настройка макросов (простейший способ, один инстанс):**
   Параметры подключения можно передавать напрямую через макросы шаблона
   (см. раздел «Макросы» ниже) — этот способ не требует правки конфигурации агента.

3. **Настройка Named Sessions (рекомендуется для TLS и нескольких инстансов):**
   Отредактируйте конфигурационный файл плагина (обычно `/etc/zabbix/zabbix_agent2.d/plugins.d/postgresql.conf` или отдельный файл в `/etc/zabbix/zabbix_agent2.d/`).
   *Важно: Имя сессии чувствительно к регистру и должно точно совпадать со значением макроса в шаблоне.*

   ```ini
   # Пример 1: Подключение через локальный Unix-сокет (Максимальная производительность)
   Plugins.PostgreSQL.Sessions.ProdDB.Uri=unix:/var/run/postgresql/.s.PGSQL.5432
   Plugins.PostgreSQL.Sessions.ProdDB.User=zbx_monitor
   Plugins.PostgreSQL.Sessions.ProdDB.Password=your_secure_password

   # Пример 2: Подключение по сети с TLS (обязательно Named Session для TLS)
   Plugins.PostgreSQL.Sessions.RemoteDB.Uri=tcp://10.0.0.5:5432
   Plugins.PostgreSQL.Sessions.RemoteDB.User=zbx_monitor
   Plugins.PostgreSQL.Sessions.RemoteDB.Password=your_secure_password
   Plugins.PostgreSQL.Sessions.RemoteDB.TLSConnect=verify_full
   Plugins.PostgreSQL.Sessions.RemoteDB.TLSCAFile=/etc/zabbix/certs/ca.crt

   # Настройка для работы через PgBouncer (избегает конфликта Prepared Statements)
   # Plugins.PostgreSQL.Sessions.ProdDB.CacheMode=describe
   ```
   Перезапустите агента: `sudo systemctl restart zabbix-agent2`.

   Если шифрование не требуется и инстанс один, Named Session может ссылаться на значения по умолчанию плагина (`Plugins.PostgreSQL.Default.*`).

### Шаг 3. Настройка в веб-интерфейсе Zabbix

1. Привяжите к хосту официальный шаблон **PostgreSQL by Zabbix agent 2**.
2. В макросах хоста укажите в `{$PG.CONNSTRING.AGENT2}` либо строку подключения URI, либо имя настроенной сессии, например: `ProdDB`.
3. Если используется Named Session, поля макросов `{$PG.USER}`, `{$PG.PASSWORD}`, `{$PG.DATABASE}` он принимает из конфигурации агента и могут быть оставлены пустыми.
4. Укажите пароль в макро `{$PG.PASSWORD}` для способа с макро-параметрами.

> Примечание о версиях: в шаблонах Zabbix 6.x использовались макросы `{$PG.CONNSTRING}` и `{$PG.URI}`. В актуальных шаблонах 7.4/x и 8.x используется `{$PG.CONNSTRING.AGENT2}`; при переезде со старых версий макросы необходимо перенести.

### Макросы шаблона (актуальные для 7.4/8.0)

| Макрос | Описание | По умолчанию |
|---|---|---|
| `{$PG.CONNSTRING.AGENT2}` | URI (например, `tcp://host:5432`) или имя именованной сессии | `tcp://localhost:5432` |
| `{$PG.USER}` | Пользователь PostgreSQL | `zbx_monitor` |
| `{$PG.PASSWORD}` | Пароль пользователя PostgreSQL | — |
| `{$PG.DATABASE}` | База данных по умолчанию для подключения | `postgres` |
| `{$PG.LLD.FILTER.DBNAME}` | Фильтр обнаруживаемых баз данных | `.+` |
| `{$PG.LLD.FILTER.APPLICATION}` | Фильтр обнаруживаемых приложений (репликация) | `.+` |
| `{$PG.DEADLOCKS.MAX.WARN}` | Порог deadlock для триггера | `0` |
| `{$PG.CONN_TOTAL_PCT.MAX.WARN}` | Максимальный процент занятых подключений | `90` |
| `{$PG.CONFLICTS.MAX.WARN}` | Порог recovery conflicts для триггера | `0` |
| `{$PG.QUERY_ETIME.MAX.WARN}` | Лимит времени выполнения для подсчёта медленных запросов | `30` |
| `{$PG.SLOW_QUERIES.MAX.WARN}` | Порог количества медленных запросов для триггера | `5` |

### Кастомные запросы (Custom queries)

Плагин поддерживает выполнение произвольных SQL-запросов из `.sql`-файлов. Для включения задайте в конфигурации плагина:

```ini
Plugins.PostgreSQL.CustomQueriesPath=/etc/zabbix/custom-queries/postgreSQL
Plugins.PostgreSQL.CustomQueriesEnabled=true
```

Элемент данных шаблона `pgsql.custom.query` принимает имя файла запроса и возвращает результат по одному из поддерживаемых контрактов (один скаляр, несколько строк, JSON). Определите свой шаблон на основе примера.

### Мониторинг PgBouncer и пулов соединений

При работе через пулер соединений (PgBouncer) в режиме transaction pooling подготовленные выражения (prepared statements) теряют контекст сессии. В этом случае для именованной сессии необходимо указать `CacheMode=describe`, чтобы агент использовал анонимный prepared-описание без создания постоянных выражений на сервере.

---

## Ключевые метрики и триггеры (Архитектура)

| Системное представление / ключ | Отслеживаемые метрики | Срабатывающие триггеры |
|---|---|---|
| `pgsql.connections` (`pg_stat_activity`) | Активные, `idle`, `waiting`, `idle_in_transaction` соединения | Рост числа ожидающих соединений (блокировки, нехватка пула). `total_pct` (доля от `max_connections`) |
| `pgsql.locks` (`pg_locks`) | Количество и типы блокировок (accessshare, rowexclusive...) | Обнаружение `Deadlocks` и `Recovery Conflicts`. |
| `pgsql.dbstat` (`pg_stat_database`) | Transactions (Commit/s, Rollback/s), Rows вставлено/обновлено/удалено | Аномальный всплеск откатов транзакций (Rollbacks). |
| `pgsql.bgwriter` (`pg_stat_bgwriter`) | Buffer hit/miss ratio, checkpoint metrics | Низкий hit rate (нехватка `shared_buffers`). |
| `pgsql.replication.process*` (`pg_stat_replication`) | Streaming lag (write/flush/replay), число standby | Превышение допустимого отставания, разрыв репликации. |
| `pgsql.queries`, `pgsql.dbstat` (`pg_stat_statements`) | Самые медленные и частые SQL-запросы | Слишком много медленных запросов (`Too Many Slow Queries`). |
| `pgsql.wal.stat`, `pgsql.archive` | Размер WAL, скорость записи, архивная логика | Остановка `autovacuum`, риск переполнения диска WAL-файлами. |
| `pgsql.oldest.xid` | Возраст самого старого XID | Триггер «Oldest xid is too big» (предупреждение о wraparound). |
| `pgsql.autovacuum.count` | Количество воркеров `autovacuum` | Наблюдение за улавливанием ломов. |
| `pgsql.ping`, `pgsql.uptime` | Живость соединения, время работы инстанса | Триггер `Service is down` (High), `Service has been restarted`. |

---

## Визуализация и наблюдаемость

* **Zabbix Dashboards:** Шаблон Agent 2 "из коробки" генерирует дашборды для хоста, визуализирующие throughput (TPS), кэш и блокировки.
* **Интеграция:** Использование Zabbix API для вывода метрик в Grafana описано в **[Источники данных в Grafana](../Grafana/grafana_datasources.md)**.
* **LLD-правила** шаблона: `database discovery` и `replication discovery` лучше всего видны в разделе **Discovery rules** при создании элементов данных (см. **[Низкоуровневое обнаружение (LLD)](./low_level_discovery.md)**).

## Дополнительная информация

* **Архитектура:** Обзор внутреннего устройства СУБД — **[PostgreSQL: Обзор](../Databases/PostgreSQL/overview.md)**.
* **Глубокая аналитика:** Полная наблюдаемость (логи, распределенные трассировки, PgBouncer) — **[Full-Stack Observability для PostgreSQL](../Databases/PostgreSQL/Operations/observability.md)**.
* **Тюнинг:** Решение проблем с производительностью на уровне СУБД — **[Performance Tuning](../Databases/PostgreSQL/Operations/performance_tuning.md)**.
* **Общие методы мониторинга СУБД** — **[Мониторинг Баз Данных с помощью Zabbix](./zabbix_database_monitoring.md)**.