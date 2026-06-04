# Мониторинг PostgreSQL в Zabbix

## Определения

**Zabbix Agent 2 PostgreSQL Plugin** — специализированный модуль для Zabbix Agent 2, обеспечивающий сбор метрик PostgreSQL через нативные системные представления (`pg_stat_*`). Входит в отдельный пакет `zabbix-agent2-plugin-postgresql`.

**Low-Level Discovery (LLD) для PostgreSQL** — механизм автоматического обнаружения баз данных, слотов репликации и табличных пространств, позволяющий динамически создавать элементы данных без ручной настройки каждой сущности.

## Базовые концепции

Мониторинг PostgreSQL в Zabbix строится на **Zabbix Agent 2** со специализированным плагином. Этот подход обеспечивает глубокий мониторинг и высокую производительность благодаря готовым шаблонам и нативному подключению к БД. Сравнение с альтернативными методами (ODBC, UserParameter, Mamonsu) — в **[Мониторинг Баз Данных с помощью Zabbix](./zabbix_database_monitoring.md)**.

Ключевые механизмы шаблона для PostgreSQL:

* **Низкоуровневое обнаружение (LLD — Low-Level Discovery):**
  * **Автоматическое обнаружение баз данных** — при создании новой БД Zabbix автоматически начинает собирать метрики.
  * **Обнаружение слотов репликации** — мониторинг состояния и отставания реплик.
* **Макросы:**
  * Гибкая настройка параметров подключения без изменения конфигурации агента: `{$PG.DSN}` (DSN — Data Source Name), `{$PG.USER}`, `{$PG.PASSWORD}`.

## Практические сценарии

### Настройка PostgreSQL для мониторинга

1. **Создание пользователя для мониторинга:**

    ```sql
    CREATE USER zabbix_monitor WITH PASSWORD 'your_secure_password';
    ALTER USER zabbix_monitor SET search_path TO '"$user", public, pg_catalog';
    GRANT pg_monitor TO zabbix_monitor;
    ```

    Роль `pg_monitor` предоставляет минимально необходимые права для чтения системных представлений статистики.

2. **Конфигурация `pg_hba.conf`:**

    ```
    # TYPE  DATABASE        USER            ADDRESS                 METHOD
    host    all             zabbix_monitor  127.0.0.1/32            scram-sha-256
    host    all             zabbix_monitor  <zabbix_server_ip>/32   scram-sha-256
    ```

3. **Включение `pg_stat_statements` (рекомендуется):**
    * Добавьте `pg_stat_statements` в `shared_preload_libraries` в `postgresql.conf`.
    * Перезагрузите сервис PostgreSQL.
    * Выполните `CREATE EXTENSION pg_stat_statements;` в каждой базе.

### Установка плагина PostgreSQL для Zabbix Agent 2

Плагин не входит в базовую поставку Zabbix Agent 2 и требует отдельной установки:

* Установите пакет `zabbix-agent2-plugin-postgresql` из официальных репозиториев Zabbix.
* Без установленного плагина ключи элементов данных PostgreSQL будут отмечены как «не поддерживаются».

### Ключевые метрики и триггеры

| Представление | Метрики | Триггеры |
|---|---|---|
| `pg_stat_activity` | Активные, idle, waiting соединения | Рост waiting (блокировки), пики active |
| `pg_locks` | Количество и типы блокировок | Deadlocks, Recovery Conflicts |
| `pg_stat_database` | Commit/s, Rollback/s | Аномальный рост откатов |
| `pg_stat_bgwriter` | Buffer hit/miss ratio | Низкий hit rate (нехватка shared_buffers) |
| `pg_stat_replication` | Streaming lag по WAL (Write Ahead Log) | Значительное отставание, остановка репликации |
| `pg_stat_statements` | Медленные и частые запросы | Too Many Slow Queries |
| Автовакуум / WAL | Статистика vacuum, рост WAL | Остановка autovacuum, неконтролируемый рост WAL |

### Визуализация данных

* **Встроенные дашборды Zabbix** — шаблоны Zabbix Agent 2 включают предустановленные виджеты и графики.
* **Grafana** — интеграция через [плагин Zabbix](https://grafana.com/grafana/plugins/alexanderzobnin-zabbix-app/) по Zabbix API.

## Дополнительная информация

Архитектура PostgreSQL — [PostgreSQL: Обзор](../Databases/PostgreSQL/overview.md). Полная наблюдаемость (метрики + логи + трассировки вне Zabbix) — [Full-Stack Observability для PostgreSQL](../Databases/PostgreSQL/Operations/observability.md). Тюнинг производительности PostgreSQL — [Performance Tuning](../Databases/PostgreSQL/Operations/performance_tuning.md).
