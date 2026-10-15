# Мониторинг PostgreSQL в Zabbix

> **Актуально для:** Zabbix 7.0 LTS / 7.4, шаблон «PostgreSQL by Zabbix agent 2» (PostgreSQL 10–17). Освещён также переход с шаблонов Zabbix 5.x.

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

### Контекст DevOps/SRE/Sysadmin

Метрики шаблона покрывают не только «живость» СУБД, но и ключевые эксплуатационные риски PostgreSQL, поэтому они напрямую используются для SLI/SLO, capacity planning и runbook-автоматизации:

* **Доступность (Availability):** `pgsql.ping` и `pgsql.uptime` — базовый SLI. Триггер `Service is down` (High) — точка запуска runbook (проверка `pg_hba.conf`, листенеров, места на диске). Событие `Service has been restarted` ловит незапланированный рестарт.
* **Репликация и RPO:** `pgsql.replication.process.*_lag` (write/flush/replay lag) и `pgsql.replication.lag.sec` — SLI для SLO на отставание standby. Рост replay lag — сигнал о нехватке I/O или CPU на реплике; разрыв потока — риск роста RPO и повод для failover.
* **Защита от wraparound:** `pgsql.oldest.xid` (триггер `Oldest xid is too big` при возрасте > 18 000 000) и `pgsql.frozenxid.prc_before_stop` — критичный для долгоживущих кластеров сигнал. Приближение к лимиту XID без успешного `VACUUM FREEZE` ведёт к остановке записи, поэтому это приоритетный алерт, а не «фон».
* **Насыщение (Saturation):** `pgsql.connections.sum.total_pct` — доля занятых соединений от `max_connections`. Для SRE это golden-signal насыщения пула: рост `waiting` и `idle_in_transaction` указывает на блокировки и утечки соединений (часто перед пулером вроде PgBouncer).
* **Capacity planning:** `pgsql.db.size`, `pgsql.wal.count`/`pgsql.wal.write`, `pgsql.archive.*` — тренды роста данных и WAL/архива. Ускоряющийся рост WAL или файлов, ожидающих архивации, предсказывает исчерпание диска и сбой бэкапов.
* **Целостность данных (Durability):** `pgsql.dbstat.sum.checksum_failures.rate` (PG 12+) — подтверждённые повреждения страниц; `pgsql.dbstat.sum.conflicts.rate` — конфликты горячего резерва, приводящие к отмене запросов на standby.
* **Change management:** пороги триггеров задаются макросами и вместе с шаблоном версионируются в Git; плановые работы (обновление, `VACUUM FULL`, переключение) закрываются через Zabbix Maintenance, чтобы не порождать шум.
* **Связь с пулером:** при работе через PgBouncer метрики самого пулера (`cl_waiting`, `sv_active`, `sv_idle`) сопоставляются с `pgsql.connections.sum.waiting` — см. **[Эксплуатация и мониторинг PgBouncer](../Databases/PostgreSQL/Operations/pgbouncer_operations.md)**.

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
   zabbix_agent2 -t 'pgsql.ping["tcp://127.0.0.1:5432","zbx_monitor","password","postgres"]'
   # → pgsql.ping[...] [u|1]   (1 = соединение установлено, 0 = ошибка)
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
3. Если используется Named Session, значения макросов `{$PG.USER}`, `{$PG.PASSWORD}`, `{$PG.DATABASE}` берутся из конфигурации агента, поэтому в веб-интерфейсе их можно оставить пустыми.
4. Укажите пароль в макросе `{$PG.PASSWORD}` для способа с макро-параметрами.

> Примечание о версиях: в шаблоне «PostgreSQL by Zabbix agent 2» для Zabbix 5.4 и ранее строка подключения задавалась макросом `{$PG.URI}`; начиная с Zabbix 6.0 он заменён на `{$PG.CONNSTRING.AGENT2}`. Формат ключей элементов данных также изменился — в актуальных шаблонах передаются четыре параметра (`connString`, `user`, `password`, `database`), поэтому при переезде со старых версий значения макросов и ключи необходимо перенести, иначе элементы данных уйдут в статус `Unsupported`.

### Макросы шаблона (актуальные для 7.0/7.4)

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
| `pgsql.locks` (`pg_locks`) | Количество и типы блокировок (accessshare, rowexclusive, ...) | Рост общего числа блокировок в базе; выявление ожидающих блокировок. |
| `pgsql.dbstat` (`pg_stat_database`) | Transactions (Commit/s, Rollback/s), строки вставлено/обновлено/удалено, deadlocks, recovery conflicts | Аномальный всплеск откатов транзакций (Rollbacks); deadlocks (High), recovery conflicts. |
| `pgsql.bgwriter` (`pg_stat_bgwriter`) | Buffer hit/miss ratio, checkpoint metrics | Низкий hit rate (нехватка `shared_buffers`). |
| `pgsql.replication.process*` (`pg_stat_replication`) | Streaming lag (write/flush/replay), число standby | Превышение допустимого отставания, разрыв репликации. |
| `pgsql.queries` (`pg_stat_statements`) | Суммарное и максимальное время выполнения запросов по базам | Слишком много медленных запросов (`Too many slow queries`); требует расширения `pg_stat_statements`. |
| `pgsql.wal.stat`, `pgsql.archive` | Размер WAL, скорость записи, число файлов к архивации, ошибки архивации | Риск переполнения диска WAL-файлами; сбой `archive_command` (`failed_trying_to_archive`). |
| `pgsql.oldest.xid`, `pgsql.frozenxid` | Возраст самого старого XID, доля до autovacuum/stop | Триггер «Oldest xid is too big» (предупреждение о wraparound); `VACUUM FREEZE is required`. |
| `pgsql.autovacuum.count` | Количество воркеров `autovacuum` | Контроль работы автоочистки: обвал числа воркеров указывает на сбой autovacuum или нехватку ресурсов. |
| `pgsql.ping`, `pgsql.uptime` | Живость соединения, время работы инстанса | Триггер `Service is down` (High), `Service has been restarted`. |

---

## Визуализация и наблюдаемость

* **Zabbix Dashboards:** Шаблон Agent 2 "из коробки" генерирует дашборды для хоста, визуализирующие throughput (TPS), кэш и блокировки.
* **Интеграция:** Использование Zabbix API для вывода метрик в Grafana описано в **[Источники данных в Grafana](../Grafana/grafana_datasources.md)**.
* **LLD-правила** шаблона: `database discovery` и `replication discovery` лучше всего видны в разделе **Discovery rules** при создании элементов данных (см. **[Низкоуровневое обнаружение (LLD)](./low_level_discovery.md)**).

---

## Устранение неисправностей

### Типичные симптомы

| Симптом | Вероятная причина | Решение |
|---|---|---|
| Все элементы данных шаблона в статусе `Unsupported`, в логе агента `cannot execute PostgreSQL plugin` | Плагин не загружен: не установлен пакет `zabbix-agent2-plugin-postgresql` или не указан `Plugins.PostgreSQL.System.Path` | Установите пакет, проверьте путь к бинарнику плагина, перезапустите `zabbix-agent2` |
| `pgsql.ping` возвращает 0, триггер `Service is down` | СУБД недоступна, неверный URI/сессия, нет записи в `pg_hba.conf`, неверный метод аутентификации | Проверьте `pg_isready`, содержимое `pg_hba.conf`, доступность порта |
| `permission denied for relation pg_stat_...` | Пользователь мониторинга без роли `pg_monitor` | `GRANT pg_monitor TO zbx_monitor;` (роль должна быть выдана с `INHERIT`) |
| Элементы группы «Queries» / `pgsql.queries` в статусе `Unsupported` | Не установлено расширение `pg_stat_statements` | См. Шаг 1: `shared_preload_libraries` + рестарт + `CREATE EXTENSION pg_stat_statements;` в целевых БД |
| LLD `replication discovery` не создаёт объекты | Нет активных WAL-отправителей (нет подключённых standby) либо фильтр `{$PG.LLD.FILTER.APPLICATION}` отсекает все `application_name` | Проверьте `SELECT * FROM pg_stat_replication;`, скорректируйте фильтр |
| LLD `database discovery` не создаёт БД | Фильтр `{$PG.LLD.FILTER.DBNAME}` или исключение шаблонных БД | По умолчанию `.+`; шаблонные `template0`/`template1` и БД, запрещающие подключение, исключаются автоматически |
| Ошибка TLS: `x509: certificate is valid for ..., not ...` | Агент проверяет SAN сертификата, а не CN; либо не используется Named Session | Выпустите сертификат с нужным SAN; для TLS обязательна Named Session с параметрами `TLSConnect`/`TLSCAFile` |
| При работе через PgBouncer: `prepared statement "..." already exists` | В transaction pooling prepared statements теряют контекст сессии | Укажите `Plugins.PostgreSQL.Sessions.<name>.CacheMode=describe` |
| `too many connections` на стороне СУБД | Исчерпан `max_connections`, утечка соединений, несколько агентов без пулинга | Проверьте `pgsql.connections.sum.*`, включите/проверьте пулинг (`KeepAlive`), используйте PgBouncer |
| Триггер `Too many slow queries` не срабатывает, хотя запросы медленные | Не задан `{$PG.QUERY_ETIME.MAX.WARN}` или мал `{$PG.SLOW_QUERIES.MAX.WARN}` | Настройте пороги под профиль нагрузки |

### Быстрая диагностика

```bash
# 1. Проверить, что плагин загрузился и ключи зарегистрированы
zabbix_agent2 -p | grep pgsql.
# → pgsql.ping[...], pgsql.version[...] и др.

# 2. Тестовый вызов элемента данных (на хосте агента)
zabbix_agent2 -t 'pgsql.ping["tcp://127.0.0.1:5432","zbx_monitor","password","postgres"]'
# → pgsql.ping[...] [u|1]   (1 = успех, 0 = нет подключения)

# 3. Проверка версии СУБД через агент
zabbix_agent2 -t 'pgsql.version["tcp://127.0.0.1:5432","zbx_monitor","password","postgres"]'
# → pgsql.version[...] [s|16.4]

# 4. Проверка с Zabbix Server/Proxy (для активного агента используйте zabbix_get с ключом)
zabbix_get -s 127.0.0.1 -k 'pgsql.ping["tcp://127.0.0.1:5432","zbx_monitor","password","postgres"]'
# → 1

# 5. Доступность СУБД напрямую
pg_isready -h 127.0.0.1 -p 5432
# → 127.0.0.1:5432 - accepting connections

# 6. Логи агента (ошибки плагина, подключения, TLS)
journalctl -u zabbix-agent2 -n 100
# → при Unsupported: причина в строках с "postgresql" / "cannot"
```

> Если элемент данных успешно проверяется через `zabbix_agent2 -t`, но в веб-интерфейсе он `Unsupported`, причина, как правило, в макросах хоста (несовпадение имени сессии, пароль, фильтры LLD), а не в самом плагине.

---

## Лучшие практики

### Безопасность

* **Наименьшие привилегии:** выделенный пользователь `zbx_monitor` с ролью `pg_monitor` (`INHERIT`), никогда — суперпользователь `postgres`.
* **Named Sessions:** храните URI, логин, пароль и TLS-материалы в конфигурационном файле плагина, а не в макросах веб-интерфейса. Ограничьте доступ: `chmod 600 /etc/zabbix/zabbix_agent2.d/plugins.d/*.conf`.
* **TLS:** для шифрованного соединения обязательна Named Session. Агент проверяет SAN сертификата, поэтому сертификат СУБД должен содержать имя/адрес, к которому подключается агент.
* **`pg_hba.conf`:** разрешайте подключение пользователя мониторинга только с адреса агента/прокси, используя `scram-sha-256` (`md5`/`trust` — только для локальной отладки).
* **Секреты:** пароль в макросе можно хранить в Vault (Secret user macros, Zabbix 5.2+), а не в открытом виде.

### Производительность

* Шаблон уже построен по модели **Master / Dependent Items**: тяжёлые выборки из `pg_stat_*` выполняются одним запросом, остальные метрики извлекаются предобработкой JSONPath. Не заменяйте их отдельными item-ами с собственными запросами.
* Для статических метрик оставляйте предобработку `Discard unchanged with heartbeat` (в шаблоне так сделано для `pgsql.version`, `pgsql.config.hash`, `pgsql.ping`).
* Не уменьшайте интервалы ниже значений шаблона: тяжёлые запросы (`pgsql.wal.stat` — 5m, `pgsql.db.size` — 5m, discovery — 1h) не стоит опрашивать каждую минуту.
* За пулером соединений держите `CacheMode=describe`, чтобы не накапливать prepared statements в transaction pooling.
* Кастомные SQL-запросы (`pgsql.custom.query`, по умолчанию item отключён) делайте «дешёвыми»: без полного сканирования больших таблиц и без блокировок.

### Надёжность

* Разворачивайте мониторинг через Named Sessions с уникальным именем на каждый инстанс — один агент может обслуживать несколько СУБД.
* Для плановых работ (обновление, `VACUUM FULL`, switchover) используйте **Maintenance** и **Problem Suppression**, чтобы не порождать ложные инциденты.
* Версионируйте шаблон и значения порогов в Git; изменения порогов проводите через процедуру управления изменениями.
* Перед применением новых элементов данных в production проверяйте их на staging через `zabbix_agent2 -t`.

### Очистка и откат

```bash
# 1. Отвязать шаблон от хоста в веб-интерфейсе (Data collection → Hosts → Templates)
# 2. Удалить конфигурацию плагина
sudo rm /etc/zabbix/zabbix_agent2.d/plugins.d/postgresql.conf
# 3. (Опционально) удалить пакет плагина
sudo apt remove zabbix-agent2-plugin-postgresql   # Debian/Ubuntu
sudo dnf remove zabbix-agent2-plugin-postgresql   # RHEL/Rocky/Alma
sudo systemctl restart zabbix-agent2
```

На стороне СУБД при полном выводе из эксплуатации: `DROP EXTENSION pg_stat_statements;` и `DROP USER zbx_monitor;` (отзыв роли `pg_monitor`).

### Пограничные случаи

* **`pg_stat_statements`:** расширение подключается через `shared_preload_libraries` и создаётся **в каждой БД отдельно**; без него элементы группы «Queries» уходят в `Unsupported` — это ожидаемое поведение, а не сбой конфигурации.
* **`pgsql.dbstat.sum.checksum_failures.rate`:** доступно начиная с PostgreSQL 12 и возвращает `NULL`, если контрольные суммы страниц (`data_checksums`) не включены.
* **`pgsql.bgwriter.buffers_backend.rate` / `buffers_backend_fsync.rate`:** доступны только в PostgreSQL версий ниже 17; в PG 17+ соответствующая статистика перенесена.
* **Именование сессии:** значение макроса `{$PG.CONNSTRING.AGENT2}` чувствительно к регистру и должно точно совпадать с `Plugins.PostgreSQL.Sessions.<SessionName>.*`.
* **Пакет плагина:** на Debian/Ubuntu — `zabbix-agent2-plugin-postgresql`, на RHEL/Rocky/Alma — одноимённый пакет; при сборке из исходников путь к плагину задаётся через `Plugins.PostgreSQL.System.Path`.

---

## Дополнительная информация

* **Архитектура:** Обзор внутреннего устройства СУБД — **[PostgreSQL: Обзор](../Databases/PostgreSQL/overview.md)**.
* **Глубокая аналитика:** Полная наблюдаемость (логи, распределенные трассировки, PgBouncer) — **[Full-Stack Observability для PostgreSQL](../Databases/PostgreSQL/Operations/observability.md)**.
* **Тюнинг:** Решение проблем с производительностью на уровне СУБД — **[Performance Tuning](../Databases/PostgreSQL/Operations/performance_tuning.md)**.
* **Общие методы мониторинга СУБД** — **[Мониторинг Баз Данных с помощью Zabbix](./zabbix_database_monitoring.md)**.