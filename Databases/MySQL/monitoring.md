# Мониторинг MySQL: Zabbix, Prometheus и PMM

## Определения

**Мониторинг MySQL** — процесс непрерывного сбора и анализа метрик производительности, состояния здоровья и безопасности сервера БД. В современных реализациях (2026 г.) мониторинг перешел от простого опроса статусных переменных к анализу событий через **Performance Schema** и **InnoDB Metrics**.

**Zabbix Agent 2** — агент на Go с нативным плагином `MySQL`. Поддерживает постоянные соединения (Connection Pooling), параллельные проверки и механизм **Named Sessions**.

**Master / Dependent Items** — архитектурный подход в Zabbix (начиная с 6.0+), при котором один "мастер-элемент" получает массив данных (обычно JSON), а "зависимые элементы" извлекают из него конкретные метрики без повторных запросов к БД.

**LLD (Low Level Discovery)** — механизм автоматического обнаружения объектов мониторинга: баз данных, табличных пространств, каналов репликации и дисков.

---

## Базовые концепции

### 1. Сравнение методов мониторинга

| Характеристика | Classic Agent (Legacy) | Zabbix Agent 2 (Standard) | Prometheus / PMM |
| :--- | :--- | :--- | :--- |
| **Механизм** | `UserParameter` + Shell | Native Go Plugin | Exporter (Scrape model) |
| **Соединения** | Новое на каждый запрос | **Connection Pool** | Persistent / Pool |
| **Формат данных** | Одиночные значения | **JSON (Master Item)** | Time-series / OpenTelemetry |
| **Репликация** | Скрипты (Master/Slave) | Нативная (Source/Replica) | Нативная (Full metrics) |

### 2. Источники данных в MySQL

*   **Status Variables (`SHOW GLOBAL STATUS`):** Основной источник счетчиков (запросы, трафик, кэши).
*   **Performance Schema:** Глубокая аналитика. Таблица `events_statements_summary_by_digest` позволяет мониторить производительность конкретных групп SQL-запросов.
*   **Information Schema:** Метаданные о схемах и таблицах.
*   **InnoDB Metrics:** Таблица `information_schema.innodb_metrics`. Содержит сотни детальных счетчиков движка InnoDB (адаптивные хэш-индексы, очистка страниц, транзакции), многие из которых нужно включать отдельно (`SET GLOBAL innodb_monitor_enable = '...'`).

### 3. Современная терминология
В мониторинге 2026 года принята терминология **Source** (Источник) и **Replica** (Реплика).
*   Метрики источника: бинарные логи, GTID, активные потоки дампа.
*   Метрики реплики: `Seconds_Behind_Source`, статус потоков I/O и SQL, ошибки репликации.

---

## Практические сценарии

### 1. Подготовка СУБД (Создание пользователя)

Для мониторинга необходим пользователь с правами доступа к системным таблицам и статусу репликации.

```sql
-- Создание пользователя (для MySQL 8.x / 9.x)
CREATE USER 'zbx_monitor'@'localhost' IDENTIFIED BY 'your_secure_password';

-- Базовые права и доступ к Performance Schema
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'zbx_monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'zbx_monitor'@'localhost';

-- Для MariaDB 10.5+ (обязательно для мониторинга репликации)
GRANT SLAVE MONITOR ON *.* TO 'zbx_monitor'@'localhost';

FLUSH PRIVILEGES;
```

### 2. Настройка Zabbix Agent 2 (Рекомендуется)

#### Конфигурация Named Sessions
Вместо хранения паролей в макросах Zabbix, параметры подключения описываются в `/etc/zabbix/zabbix_agent2.d/plugins.d/mysql.conf`:

```ini
# Сессия "ProdDB" для подключения к локальному экземпляру
Plugins.Mysql.Sessions.ProdDB.Uri=tcp://localhost:3306
Plugins.Mysql.Sessions.ProdDB.User=zbx_monitor
Plugins.Mysql.Sessions.ProdDB.Password=your_secure_password

# Опционально: таймаут и пулинг
Plugins.Mysql.Timeout=5
Plugins.Mysql.KeepAlive=300
```

#### Настройка в Zabbix Web
1. Прилинкуйте шаблон **MySQL by Zabbix agent 2**.
2. В макросе `{$MYSQL.DSN}` укажите имя сессии: `ProdDB`.
3. Шаблон автоматически запустит **LLD** для обнаружения баз данных и статуса репликации.

### 3. Настройка Classic Zabbix Agent (Legacy)

#### Конфигурация UserParameter
Создайте файл `/etc/zabbix/zabbix_agentd.d/mysql.conf`:

```conf
# Проверка ping (0 - недоступен, 1 - доступен)
UserParameter=mysql.ping,mysqladmin --defaults-extra-file=/var/lib/zabbix/.my.cnf ping | grep -c alive

# Сбор глобальных переменных (требует имя переменной как аргумент)
# Пример использования: mysql.status[Queries]
UserParameter=mysql.status[*],mysql --defaults-extra-file=/var/lib/zabbix/.my.cnf -N -e "show global status where Variable_name='$1';" | awk '{print $2}'

# Сбор метрик InnoDB (требует имя метрики)
UserParameter=mysql.innodb[*],mysql --defaults-extra-file=/var/lib/zabbix/.my.cnf -N -e "SELECT count FROM information_schema.innodb_metrics WHERE name='$1';"
```

#### Настройка файла .my.cnf
Для безопасной аутентификации классического агента:

```bash
# Создать файл /var/lib/zabbix/.my.cnf
cat <<EOF > /var/lib/zabbix/.my.cnf
[client]
user=zbx_monitor
password=your_secure_password
EOF

# Установить владельца и права (только чтение владельцем)
chown zabbix:zabbix /var/lib/zabbix/.my.cnf
chmod 600 /var/lib/zabbix/.my.cnf
```

### 4. Проверка и отладка

Для проверки получения данных используйте `zabbix_get` с сервера Zabbix или прокси:

```bash
# Проверка Agent 2 (через Named Session)
zabbix_get -s 192.168.1.10 -k mysql.ping[ProdDB]
# -> 1

# Проверка Master Item (возвращает JSON со всеми метриками)
zabbix_get -s 192.168.1.10 -k mysql.get_status_variables[ProdDB]
# -> {"Aborted_clients":"0","Aborted_connects":"3", ...}
```

---

## Дополнительная информация

### Мониторинг Slow Queries (Медленные запросы)

1.  **На уровне MySQL:** Включите логирование медленных запросов в `my.cnf`:
    ```ini
    slow_query_log = 1
    slow_query_log_file = /var/log/mysql/slow.log
    # Минимальное время выполнения запроса для попадания в лог (в секундах)
    long_query_time = 2.0
    ```
    *   **Важно (Единицы измерения):** В современных версиях (MySQL 5.1+, MariaDB) `long_query_time` поддерживает микросекундную точность (например, `0.001` для 1 мс). В очень старых версиях (legacy) значение задавалось только в целых секундах, что делало невозможным отладку запросов, которые должны выполняться быстрее секунды, но тормозят до 500-800 мс.
2.  **В Zabbix:** Метрика `mysql.status[Slow_queries]` отслеживает только *количество* таких запросов с момента запуска сервера.
3.  **В PMM (Рекомендуется):** Используйте **Query Analytics (QAN)**. PMM парсит `slow.log` или опрашивает `performance_schema.events_statements_summary_by_digest`, предоставляя визуализацию планов выполнения и распределения нагрузки по времени.


### Ключевые метрики для алертинга

*   **`Threads_connected`**: Рост может указывать на утечку соединений в приложении.
*   **`Max_used_connections`**: Если приближается к `max_connections`, новые пользователи не смогут подключиться.
*   **`Innodb_buffer_pool_wait_free`**: Если > 0, Buffer Pool переполнен, и операции записи ждут освобождения страниц (критично для I/O).
*   **`Seconds_Behind_Source`**: Основной индикатор лага репликации.

### См. также

- **[Обзор MySQL и форков](./overview.md)** — архитектура Redo/Undo Log.
- **[Zabbix: Мониторинг баз данных](../../Zabbix/zabbix_database_monitoring.md)** — общие принципы Master/Dependent элементов.
- **[Prometheus: mysqld_exporter](https://github.com/prometheus/mysqld_exporter)** — глубокий мониторинг в облачных средах.
