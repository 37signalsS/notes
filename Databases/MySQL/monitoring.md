# Мониторинг MySQL с помощью Zabbix Agent

## Определения

**Мониторинг MySQL** — это процесс сбора, анализа и визуализации метрик производительности и состояния сервера базы данных для обеспечения его стабильности, доступности и быстродействия.

**Zabbix Agent** — сервис, который устанавливается на наблюдаемом хосте (в данном случае, на сервере с MySQL) для сбора локальных данных и их отправки на Zabbix Server.

**UserParameter** — директива в конфигурации Zabbix Agent, которая позволяет определять пользовательские метрики. С ее помощью можно заставить агент выполнять локальные команды или скрипты и отправлять их вывод как значение метрики.

## Базовые концепции

### Принцип работы

1. **Zabbix Server** запрашивает у **Zabbix Agent** значение определенного элемента данных (item), например, `mysql.ping`.
2. **Zabbix Agent** находит соответствующий `UserParameter`, определенный в его конфигурации (например, `UserParameter=mysql.ping,...`).
3. Агент выполняет указанную в `UserParameter` команду (например, `mysqladmin ping`).
4. Результат выполнения команды возвращается на **Zabbix Server** как значение элемента данных.

### Аутентификация и безопасность

Для получения метрик Zabbix Agent должен подключаться к MySQL. Чтобы избежать хранения паролей в открытом виде внутри скриптов или `UserParameter`, используется безопасный подход:

1. **Создание выделенного пользователя MySQL**: В MySQL создается пользователь с минимально необходимыми привилегиями только для чтения статусов и метрик (например, `zabbix_monitor`).
2. **Использование `~/.my.cnf`**: В домашней директории пользователя, от имени которого работает Zabbix Agent (обычно `zabbix`), создается файл `.my.cnf`. В этом файле в секции `[client]` указываются имя пользователя и пароль.
3. **Безопасные права доступа**: На файл `.my.cnf` устанавливаются строгие права (`chmod 600`), чтобы его мог читать только владелец — пользователь `zabbix`.

Таким образом, утилиты `mysql` и `mysqladmin`, вызываемые агентом, автоматически используют учетные данные из этого файла, не требуя их явного указания в команде.

## Практические сценарии

### Пошаговая настройка мониторинга MySQL с помощью Zabbix Agent

#### 1. Настройка Zabbix Agent (`UserParameter`)

Рекомендуется создавать отдельный файл конфигурации для MySQL в `/etc/zabbix/zabbix_agentd.d/mysql.conf`.

**Пример файла `/etc/zabbix/zabbix_agentd.d/mysql.conf`:**

```conf
# В этом файле UserParameter'ы определены без учетных данных, 
# так как предполагается использование ~/.my.cnf

# Пинг MySQL
UserParameter=mysql.ping,mysqladmin ping | grep -c alive

# Получение статусной переменной
UserParameter=mysql.status[*],echo "show global status where Variable_name='$1';" | mysql -N | awk '{print $2}'

# Получение размеров базы данных
UserParameter=mysql.size[*],echo "SELECT sum(data_length+index_length) FROM information_schema.tables WHERE table_schema='$1';" | mysql -N
```

После создания/изменения файла перезапустите Zabbix Agent:

```bash
sudo systemctl restart zabbix-agent
```

#### 2. Создание пользователя MySQL для мониторинга

Выполните следующий SQL-запрос на вашем MySQL сервере:

```sql
CREATE USER 'zabbix_monitor'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES ON *.* TO 'zabbix_monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'zabbix_monitor'@'localhost';
FLUSH PRIVILEGES;
```

> Замените `your_secure_password` на надежный пароль.

#### 3. Настройка аутентификации агента (`.my.cnf`)

Определите домашнюю директорию пользователя `zabbix` и создайте в ней файл `.my.cnf`.

1. **Найти домашнюю директорию:**

    ```bash
    grep zabbix /etc/passwd
    ```

    Обычно это `/var/lib/zabbix`.

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

1. Перейдите в `Configuration` -> `Hosts` и создайте новый хост.
2. Укажите `Hostname`, соответствующий значению в `zabbix_agentd.conf`.
3. На вкладке `Templates` привяжите шаблон `MySQL by Zabbix agent`.

#### 5. Проверка и отладка

- **Latest Data**: Перейдите в `Monitoring` -> `Latest data`, выберите ваш хост и проверьте поступление новых метрик от MySQL.
- **Логи**: В случае проблем изучите логи Zabbix Agent (`/var/log/zabbix/zabbix_agentd.log`).
- **Ручная проверка**: Используйте `zabbix_get` с Zabbix Server для проверки конкретного ключа:

    ```bash
    # Проверка выполняется от имени пользователя zabbix на сервере с агентом
    sudo -u zabbix mysqladmin ping 
    # Если команда успешна, значит .my.cnf настроен верно.
    ```

#### 6. Настройка оповещений

Стандартный шаблон уже содержит триггеры. Просмотрите их в `Configuration` -> `Hosts` -> `Triggers` вашего хоста и при необходимости адаптируйте пороги срабатывания под ваши нужды. Настройте действия (`Actions`) для отправки уведомлений.

## Дополнительная информация

### Ключевые метрики для мониторинга

- **Доступность**: `mysql.ping` (сервер отвечает).
- **Производительность**:
  - `mysql.status[Slow_queries]`: Количество медленных запросов.
  - `mysql.status[Threads_connected]`: Текущее количество подключений.
  - `mysql.status[Innodb_buffer_pool_read_requests]` и `mysql.status[Innodb_buffer_pool_reads]`: Соотношение этих метрик показывает эффективность buffer pool (hit rate).
- **Репликация**:
  - `mysql.status[Slave_running]`: Состояние потоков репликации (`ON`/`OFF`).
  - `mysql.status[Seconds_behind_master]`: Отставание реплики от мастера в секундах.

### Альтернативные системы мониторинга

- **Prometheus + mysqld_exporter**: Популярный стек для сбора метрик, где `mysqld_exporter` выступает в роли сборщика, а Prometheus — в роли хранилища временных рядов.
- **Percona Monitoring and Management (PMM)**: Комплексное решение для мониторинга MySQL, включающее в себя готовые дашборды и инструменты для глубокого анализа производительности.
