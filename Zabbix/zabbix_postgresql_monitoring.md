# Мониторинг PostgreSQL в Zabbix

## Определения

**Zabbix Agent 2 PostgreSQL Plugin** — специализированный загружаемый модуль (loadable plugin) для Zabbix Agent 2, обеспечивающий сбор метрик PostgreSQL через нативные системные представления (`pg_stat_*`). Начиная с последних версий, плагин вынесен в отдельный пакет `zabbix-agent2-plugin-postgresql`.

**Low-Level Discovery (LLD) для PostgreSQL** — механизм автоматического обнаружения баз данных, слотов репликации и табличных пространств, позволяющий динамически создавать элементы данных (Items) и триггеры без ручной настройки каждой сущности.

**Named Sessions (Именованные сессии)** — механизм безопасной конфигурации Zabbix Agent 2, при котором параметры подключения (URI, логин, пароль, TLS-сертификаты) хранятся локально в конфигурационном файле агента под уникальным именем, а не передаются в открытом виде через веб-интерфейс Zabbix.

---

## Базовые концепции

Мониторинг PostgreSQL в Zabbix 7.0+ строится исключительно на **Zabbix Agent 2** со специализированным плагином. Этот подход обеспечивает глубокий мониторинг и высокую производительность благодаря пулингу соединений (Connection Pooling). Сравнение с альтернативными методами (ODBC) — в **[Мониторинг Баз Данных с помощью Zabbix](./zabbix_database_monitoring.md)**.

Ключевые механизмы шаблона:

* **Низкоуровневое обнаружение (LLD):**
  * **Автоматическое обнаружение баз данных** — при создании новой БД система автоматически начинает собирать её метрики.
  * **Обнаружение слотов репликации** — мониторинг состояния и отставания потоковой репликации.
* **Изоляция учетных данных:** Передача логинов и паролей через макросы (`{$PG.USER}`) в современных инсталляциях является *устаревшей практикой (Legacy)*. Стандартом является использование **Named Sessions**.

---

## Практические сценарии

### Шаг 1. Подготовка СУБД PostgreSQL

1. **Создание выделенного пользователя для мониторинга:**
   Никогда не используйте суперпользователя (`postgres`).
   ```sql
   CREATE USER zbx_monitor WITH PASSWORD 'your_secure_password';
   -- Предоставление системной роли для чтения статистики (PostgreSQL 10+)
   GRANT pg_monitor TO zbx_monitor;
   ```

2. **Включение `pg_stat_statements` (Обязательно для метрик запросов):**
   * В файле `postgresql.conf` добавьте: `shared_preload_libraries = 'pg_stat_statements'`
   * Перезагрузите сервис PostgreSQL.
   * Выполните `CREATE EXTENSION pg_stat_statements;` в целевых базах данных.

3. **Настройка доступов в `pg_hba.conf`:**
   Разрешите агенту подключаться локально или по сети:
   ```text
   # TYPE  DATABASE        USER            ADDRESS                 METHOD
   host    all             zbx_monitor     127.0.0.1/32            scram-sha-256
   # Для Unix-сокетов:
   local   all             zbx_monitor                             scram-sha-256
   ```

### Шаг 2. Установка и настройка плагина (Zabbix Agent 2)

1. **Установка пакета:**
   Плагин устанавливается отдельно от самого агента:
   ```bash
   sudo apt install zabbix-agent2-plugin-postgresql
   ```

2. **Настройка Named Sessions (Best Practice):**
   Отредактируйте конфигурационный файл плагина (обычно `/etc/zabbix/zabbix_agent2.d/plugins.d/postgresql.conf`).
   *Важно: Имя сессии чувствительно к регистру и должно начинаться с заглавной буквы.*

   ```ini
   # Пример 1: Подключение через локальный Unix-сокет (Максимальная производительность)
   Plugins.PostgreSQL.Sessions.ProdDB.Uri=unix:/var/run/postgresql/.s.PGSQL.5432
   Plugins.PostgreSQL.Sessions.ProdDB.User=zbx_monitor
   Plugins.PostgreSQL.Sessions.ProdDB.Password=your_secure_password

   # Пример 2: Подключение по сети с TLS (обязательно Named Session)
   Plugins.PostgreSQL.Sessions.RemoteDB.Uri=tcp://10.0.0.5:5432
   Plugins.PostgreSQL.Sessions.RemoteDB.User=zbx_monitor
   Plugins.PostgreSQL.Sessions.RemoteDB.Password=your_secure_password
   Plugins.PostgreSQL.Sessions.RemoteDB.TLSConnect=verify_full
   Plugins.PostgreSQL.Sessions.RemoteDB.TLSCAFile=/etc/zabbix/certs/ca.crt
   
   # Настройка для работы через PgBouncer (избегает конфликта Prepared Statements)
   # Plugins.PostgreSQL.Sessions.ProdDB.CacheMode=describe
   ```
   Перезапустите агента: `sudo systemctl restart zabbix-agent2`.

### Шаг 3. Настройка в веб-интерфейсе Zabbix

1. Привяжите к хосту официальный шаблон **PostgreSQL by Zabbix agent 2**.
2. В макросах хоста укажите в `{$PG.CONNSTRING}` (или `{$PG.URI}`) имя настроенной сессии: `ProdDB`.
3. Поля макросов пароля и пользователя оставьте пустыми — агент возьмет их из локального конфигурационного файла.

---

## Ключевые метрики и триггеры (Архитектура)

| Системное представление | Отслеживаемые метрики | Срабатывающие триггеры |
|---|---|---|
| `pg_stat_activity` | Активные, `idle`, `waiting` соединения | Рост числа ожидающих соединений (блокировки, нехватка пула). |
| `pg_locks` | Количество и типы блокировок | Обнаружение `Deadlocks` и `Recovery Conflicts`. |
| `pg_stat_database` | Transactions (Commit/s, Rollback/s) | Аномальный всплеск откатов транзакций (Rollbacks). |
| `pg_stat_bgwriter` | Buffer hit/miss ratio, checkpoint metrics | Низкий hit rate (нехватка `shared_buffers`). |
| `pg_stat_replication` | Streaming lag (отставание реплики) | Превышение допустимого отставания, разрыв репликации. |
| `pg_stat_statements` | Самые медленные и частые SQL-запросы | Слишком много медленных запросов (`Too Many Slow Queries`). |
| Системные каталоги | Статистика `autovacuum`, размер WAL | Остановка `autovacuum`, риск переполнения диска WAL-файлами. |

---

## Визуализация и наблюдаемость

* **Zabbix Dashboards:** Шаблон Agent 2 "из коробки" генерирует дашборды для хоста, визуализирующие throughput (TPS), кэш и блокировки.
* **Интеграция:** Использование Zabbix API для вывода метрик в Grafana описано в **[Источники данных в Grafana](../Grafana/grafana_datasources.md)**.

## Дополнительная информация

* **Архитектура:** Обзор внутреннего устройства СУБД — **[PostgreSQL: Обзор](../Databases/PostgreSQL/overview.md)**. 
* **Глубокая аналитика:** Полная наблюдаемость (логи, распределенные трассировки, PgBouncer) — **[Full-Stack Observability для PostgreSQL](../Databases/PostgreSQL/Operations/observability.md)**. 
* **Тюнинг:** Решение проблем с производительностью на уровне СУБД — **[Performance Tuning](../Databases/PostgreSQL/Operations/performance_tuning.md)**.