# Мониторинг MySQL с помощью Zabbix Agent

## Определения

**Мониторинг MySQL** — сбор, анализ и визуализация метрик производительности и состояния сервера БД для обеспечения стабильности, доступности и быстродействия.

**Zabbix Agent** — сервис на наблюдаемом хосте для сбора локальных данных и отправки на Zabbix Server.

**UserParameter** — директива в конфигурации Zabbix Agent для определения пользовательских метрик. Позволяет агенту выполнять команды/скрипты и возвращать их вывод как значение метрики.

## Базовые концепции

### Принцип работы

1. **Zabbix Server** запрашивает у **Zabbix Agent** значение элемента данных (item), например `mysql.ping`.
2. **Zabbix Agent** находит соответствующий `UserParameter` в конфигурации.
3. Агент выполняет команду из `UserParameter` (например `mysqladmin ping`).
4. Результат возвращается на **Zabbix Server** как значение элемента данных.

### Аутентификация и безопасность

Для получения метрик Zabbix Agent подключается к MySQL. Чтобы избежать хранения паролей в скриптах или `UserParameter`, используется безопасный подход:

1. **Выделенный пользователь MySQL**: Пользователь с минимальными привилегиями только для чтения статусов (например `zabbix_monitor`).
2. **Файл `~/.my.cnf`**: В домашней директории пользователя `zabbix` создается файл с учетными данными в секции `[client]`.
3. **Безопасные права**: На файл устанавливаются права `chmod 600` — доступ только владельцу.

Утилиты `mysql` и `mysqladmin` автоматически используют учетные данные из файла без явного указания в команде.

## Практические сценарии

### Пошаговая настройка мониторинга MySQL с помощью Zabbix Agent

#### 1. Настройка Zabbix Agent (`UserParameter`)

Создайте файл конфигурации `/etc/zabbix/zabbix_agentd.d/mysql.conf`:

```conf
# UserParameter без учетных данных (используется ~/.my.cnf)

# Пинг MySQL
UserParameter=mysql.ping,mysqladmin ping | grep -c alive

# Статусная переменная
UserParameter=mysql.status[*],echo "show global status where Variable_name='$1';" | mysql -N | awk '{print $2}'

# Размер базы данных
UserParameter=mysql.size[*],echo "SELECT sum(data_length+index_length) FROM information_schema.tables WHERE table_schema='$1';" | mysql -N
```

Перезапустите Zabbix Agent:

```bash
sudo systemctl restart zabbix-agent
```

#### 2. Создание пользователя MySQL для мониторинга

```sql
CREATE USER 'zabbix_monitor'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES ON *.* TO 'zabbix_monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'zabbix_monitor'@'localhost';
FLUSH PRIVILEGES;
```

> Замените `your_secure_password` на надежный пароль.

#### 3. Настройка аутентификации агента (`.my.cnf`)

1. **Найти домашнюю директорию:**

    ```bash
    grep zabbix /etc/passwd
    ```

    Обычно `/var/lib/zabbix`.

2. **Создать файл `/var/lib/zabbix/.my.cnf`:**

    ```ini
    [client]
    user=zabbix_monitor
    password=your_secure_password
    ```

3. **Установить безопасные права:**

    ```bash
    sudo chown zabbix:zabbix /var/lib/zabbix/.my.cnf
    sudo chmod 600 /var/lib/zabbix/.my.cnf
    ```

#### 4. Настройка в веб-интерфейсе Zabbix

1. Перейдите в `Configuration` → `Hosts`, создайте хост.
2. Укажите `Hostname`, соответствующий значению в `zabbix_agentd.conf`.
3. На вкладке `Templates` привяжите шаблон `MySQL by Zabbix agent`.

#### 5. Проверка и отладка

- **Latest Data**: `Monitoring` → `Latest data` — проверьте поступление метрик.
- **Логи**: При проблемах изучите `/var/log/zabbix/zabbix_agentd.log`.
- **Ручная проверка**:

    ```bash
    # Проверка от имени пользователя zabbix
    sudo -u zabbix mysqladmin ping
    # Если успешно — .my.cnf настроен верно
    ```

#### 6. Настройка оповещений

Шаблон содержит триггеры. Проверьте их в `Configuration` → `Hosts` → `Triggers`, адаптируйте пороги. Настройте `Actions` для отправки уведомлений.

## Дополнительная информация

**Ключевые метрики:**

- **Доступность**: `mysql.ping`
- **Производительность**: `mysql.status[Slow_queries]`, `mysql.status[Threads_connected]`, соотношение `Innodb_buffer_pool_read_requests` / `Innodb_buffer_pool_reads` (hit rate).
- **Репликация**: `mysql.status[Slave_running]` (ON/OFF), `mysql.status[Seconds_behind_master]`.

**Альтернативные системы:** Prometheus + [mysqld_exporter](../../Prometheus/Exporters/other_exporters.md), [Percona Monitoring and Management (PMM)](../../Databases/MySQL/overview.md).
