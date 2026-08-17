# Мониторинг MySQL: Zabbix, Prometheus и PMM

## Определения

**Мониторинг MySQL** — процесс непрерывного сбора и анализа метрик производительности, состояния здоровья и безопасности сервера БД. В современных реализациях (2026 г.) мониторинг перешел от простого опроса статусных переменных к глубокому анализу событий через **Performance Schema** и **InnoDB Metrics**.

**Zabbix Agent 2** — агент на Go с нативным плагином `MySQL`. Поддерживает постоянные соединения (**Connection Pooling**), параллельные проверки и механизм **Named Sessions**, что критично для высоконагруженных СУБД.

**mysqld_exporter** — специализированный сервис для сбора метрик MySQL в формате Prometheus. Работает по модели Pull, экспортируя данные о состоянии движка, репликации и схемах.

**PMM (Percona Monitoring and Management)** — комплексная платформа мониторинга с открытым исходным кодом, объединяющая Prometheus, Grafana и инструменты глубокого анализа запросов (QAN).

**Master / Dependent Items** — архитектурный подход в Zabbix (6.0+), при котором один "мастер-элемент" получает массив данных (JSON), а "зависимые элементы" извлекают метрики без повторных запросов к БД.

**LLD (Low Level Discovery)** — механизм автоматического обнаружения объектов: баз данных, табличных пространств, каналов репликации и пользовательских метрик.

---

## Базовые концепции

### 1. Сравнение методов мониторинга (2026)

| Характеристика | Classic Agent (Legacy) | Zabbix Agent 2 (Standard) | Prometheus / PMM |
| :--- | :--- | :--- | :--- |
| **Механизм** | `UserParameter` + Shell | Native Go Plugin | Exporter (Scrape model) |
| **Соединения** | Новое на каждый запрос | **Connection Pool** | Persistent / Pool |
| **Формат данных** | Одиночные значения | **JSON (Master Item)** | Time-series / OpenTelemetry |
| **Диагностика** | Базовая | Хорошая (LLD) | **Отличная (QAN/Trace)** |
| **Репликация** | Скрипты (Master/Slave) | Нативная (Source/Replica) | Нативная (Full metrics) |

### 2. Источники данных в MySQL

*   **Status Variables (`SHOW GLOBAL STATUS`):** Основной источник счетчиков (запросы, трафик, кэши).
*   **Performance Schema (P_S):** Инструментарий для анализа внутренних событий.
    *   `events_statements_summary_by_digest`: анализ групп SQL-запросов и их нагрузки.
    *   `table_io_waits_summary_by_index_usage`: выявление неиспользуемых индексов.
*   **Information Schema:** Метаданные о схемах, таблицах и правах.
*   **InnoDB Metrics:** Таблица `information_schema.innodb_metrics`. Содержит детальные счетчики движка InnoDB (адаптивные хэш-индексы, транзакции). Многие метрики требуют включения: `SET GLOBAL innodb_monitor_enable = 'module_name'`.
*   **Error Log:** Анализ критических ошибок (Corruption, CrashLoop).

### 3. Современная терминология
Используется терминология **Source** (Источник) и **Replica** (Реплика).
*   Метрики источника: бинарные логи, GTID, активные потоки дампа.
*   Метрики реплики: `Seconds_Behind_Source`, статус потоков I/O и SQL.

---

## Практические сценарии

### 1. Подготовка СУБД (Создание пользователя)

Для любого инструмента мониторинга требуется пользователь с ограниченными правами.

```sql
-- Создание пользователя (MySQL 8.x / 9.x / MariaDB)
CREATE USER 'monitor'@'localhost' IDENTIFIED BY 'your_secure_password' WITH MAX_USER_CONNECTIONS 3;

-- Базовые права и доступ к Performance Schema
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'monitor'@'localhost';
GRANT SELECT ON sys.* TO 'monitor'@'localhost';

-- Для MariaDB 10.5+ (обязательно для мониторинга репликации)
GRANT SLAVE MONITOR ON *.* TO 'monitor'@'localhost';

FLUSH PRIVILEGES;
```

### 2. Настройка Zabbix Agent 2 (Рекомендуется)

#### Конфигурация Named Sessions
В `/etc/zabbix/zabbix_agent2.d/plugins.d/mysql.conf`:
```ini
Plugins.Mysql.Sessions.ProdDB.Uri=tcp://localhost:3306
Plugins.Mysql.Sessions.ProdDB.User=monitor
Plugins.Mysql.Sessions.ProdDB.Password=your_secure_password
Plugins.Mysql.KeepAlive=300
```

#### Настройка в Zabbix Web
1. Прилинкуйте шаблон **MySQL by Zabbix agent 2**.
2. Установите макрос `{$MYSQL.DSN}` в `ProdDB`.

### 3. Настройка Prometheus (mysqld_exporter)

#### Конфигурация аутентификации
Создайте файл `/etc/mysqld_exporter/.my.cnf`:
```ini
[client]
user=monitor
password=your_secure_password
```

#### Запуск через Systemd
```bash
# /etc/systemd/system/mysqld_exporter.service
[Service]
ExecStart=/usr/local/bin/mysqld_exporter \
  --config.my-cnf=/etc/mysqld_exporter/.my.cnf \
  --collect.info_schema.innodb_metrics \
  --collect.perf_schema.tableiowaits
Restart=always
```

### 4. Настройка Classic Zabbix Agent (Legacy)

#### Конфигурация UserParameter
Файл `/etc/zabbix/zabbix_agentd.d/mysql.conf`:
```conf
UserParameter=mysql.ping,mysqladmin --defaults-extra-file=/var/lib/zabbix/.my.cnf ping | grep -c alive
UserParameter=mysql.status[*],mysql --defaults-extra-file=/var/lib/zabbix/.my.cnf -N -e "show global status where Variable_name='$1';" | awk '{print $2}'
UserParameter=mysql.innodb[*],mysql --defaults-extra-file=/var/lib/zabbix/.my.cnf -N -e "SELECT count FROM information_schema.innodb_metrics WHERE name='$1';"
```

#### Безопасная аутентификация (.my.cnf)
```bash
cat <<EOF > /var/lib/zabbix/.my.cnf
[client]
user=monitor
password=your_secure_password
EOF
chown zabbix:zabbix /var/lib/zabbix/.my.cnf
chmod 600 /var/lib/zabbix/.my.cnf
```

### 5. Использование Percona PMM

1. **Установка клиента:** `curl -fsSL https://www.percona.com/get/pmm | bash`
2. **Регистрация:** `pmm-admin config --server-url=https://admin:admin@pmm.local`
3. **Добавление MySQL:** `pmm-admin add mysql --username=monitor --password=your_secure_password --query-source=perfschema`

### 6. Проверка и отладка

```bash
# Проверка Agent 2
zabbix_get -s 127.0.0.1 -k mysql.ping[ProdDB]

# Проверка получения JSON (Master Item)
zabbix_get -s 127.0.0.1 -k mysql.get_status_variables[ProdDB]
```

---

## Дополнительная информация

### Мониторинг Slow Queries (Медленные запросы)

1.  **Конфигурация MySQL:**
    ```ini
    slow_query_log = 1
    slow_query_log_file = /var/log/mysql/slow.log
    long_query_time = 0.1 # 100 мс
    log_slow_extra = ON  # MySQL 8.0.14+
    ```
    *   **Микросекундная точность:** В современных версиях (MySQL 5.1+, MariaDB) `long_query_time` поддерживает дробные значения (например, `0.001` для 1 мс). В legacy-версиях поддерживались только целые секунды.
2.  **Анализ:**
    *   Zabbix: отслеживает `Slow_queries` (счетчик).
    *   PMM: инструмент **Query Analytics (QAN)** визуализирует планы выполнения и находит "самые тяжелые" запросы.

### Ключевые метрики для алертинга (SRE Guide)

*   **`Threads_connected`**: Рост сигнализирует об утечках в приложении или "зависании" запросов.
*   **`Max_used_connections`**: Лимит `max_connections` должен иметь запас 20-30%.
*   **`Innodb_buffer_pool_wait_free`**: Если > 0, Buffer Pool переполнен, запись тормозит (нужен тюнинг памяти).
*   **`Seconds_Behind_Source`**: Основной алерт для репликации. Лаг > 60с требует вмешательства.
*   **`Innodb_row_lock_time_avg`**: Рост среднего времени блокировки указывает на неоптимальные транзакции.

### См. также

- **[Обзор MySQL и форков](./overview.md)** — архитектура InnoDB и Redo/Undo Log.
- **[Zabbix: Мониторинг баз данных](../../Zabbix/zabbix_database_monitoring.md)** — общие принципы Zabbix.
- **[Prometheus: mysqld_exporter](https://github.com/prometheus/mysqld_exporter)** — официальная документация.
- **[Конфигурация параметров my.cnf](./configuration.md)** — детали настройки Performance Schema.
