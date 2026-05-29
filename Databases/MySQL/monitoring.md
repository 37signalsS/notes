# Мониторинг MySQL с помощью Zabbix Agent

## Определения

**Мониторинг MySQL** — процесс сбора, анализа и визуализации метрик производительности и состояния сервера БД (Базы Данных) для обеспечения стабильности, доступности и быстродействия системы.

**Zabbix Agent** — программное обеспечение (агент), устанавливаемое на наблюдаемом хосте для сбора локальных данных и их отправки на Zabbix Server.

**UserParameter** — директива в конфигурационном файле Zabbix Agent, предназначенная для определения пользовательских метрик. Позволяет агенту выполнять произвольные команды или скрипты операционной системы и возвращать результат их выполнения как значение метрики.

## Основные концепции

### Принцип работы

1. **Zabbix Server** запрашивает у **Zabbix Agent** значение конкретного элемента данных (item), например `mysql.ping`.
2. **Zabbix Agent** сопоставляет запрос с соответствующей директивой `UserParameter` в своей конфигурации.
3. Агент выполняет команду, указанную в `UserParameter` (например, `mysqladmin ping`).
4. Результат выполнения команды возвращается на **Zabbix Server** и сохраняется в базе данных мониторинга.

### Аутентификация и безопасность

Для получения метрик Zabbix Agent должен подключаться к MySQL. Для обеспечения безопасности и исключения хранения паролей в открытом виде в конфигурационных файлах или скриптах применяется следующий подход:

1. **Выделенный пользователь MySQL**: Создается учетная запись с минимально необходимым набором привилегий только для чтения системных статусов.
2. **Файл конфигурации клиента (`.my.cnf`)**: В домашней директории системного пользователя, от имени которого запущен Zabbix Agent (обычно `zabbix`), создается файл с учетными данными в секции `[client]`.
3. **Разграничение прав доступа**: На файл `.my.cnf` устанавливаются строгие права доступа (`chmod 600`), разрешающие чтение только владельцу файла.

Утилиты `mysql` и `mysqladmin` при запуске автоматически считывают учетные данные из этого файла, что позволяет не указывать пароль в строке команды.

## Практические сценарии

### Настройка мониторинга MySQL через Zabbix Agent

#### 1. Конфигурация Zabbix Agent

Создайте файл `/etc/zabbix/zabbix_agentd.d/mysql.conf` со следующим содержимым:

```conf
# Проверка доступности MySQL
UserParameter=mysql.ping,mysqladmin ping | grep -c alive

# Сбор глобальных статусных переменных
UserParameter=mysql.status[*],echo "show global status where Variable_name='$1';" | mysql -N | awk '{print $2}'

# Получение размера конкретной базы данных
UserParameter=mysql.size[*],echo "SELECT sum(data_length+index_length) FROM information_schema.tables WHERE table_schema='$1';" | mysql -N
```

После внесения изменений перезапустите агент:

```bash
sudo systemctl restart zabbix-agent
# -> (команда не возвращает вывод при успехе)
```

#### 2. Подготовка пользователя в MySQL

Выполните следующие команды в консоли MySQL для создания пользователя мониторинга:

```sql
CREATE USER 'zabbix_monitor'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES ON *.* TO 'zabbix_monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'zabbix_monitor'@'localhost';
FLUSH PRIVILEGES;
-- -> Query OK, 0 rows affected
```

#### 3. Настройка файла аутентификации (.my.cnf)

Определите домашнюю директорию пользователя `zabbix` и создайте там файл конфигурации:

```bash
grep zabbix /etc/passwd
# -> zabbix:x:111:115::/var/lib/zabbix:/usr/sbin/nologin

# Создание файла (путь /var/lib/zabbix/.my.cnf)
cat <<EOF | sudo tee /var/lib/zabbix/.my.cnf
[client]
user=zabbix_monitor
password=your_secure_password
EOF

# Установка прав доступа
sudo chown zabbix:zabbix /var/lib/zabbix/.my.cnf
sudo chmod 600 /var/lib/zabbix/.my.cnf
```

#### 4. Проверка работоспособности

Проверьте возможность подключения к MySQL от имени пользователя `zabbix`:

```bash
sudo -u zabbix mysqladmin ping
# -> mysqld is alive
```

Если получен ответ `mysqld is alive`, конфигурация выполнена верно.

#### 5. Подключение шаблона в Zabbix

1. В веб-интерфейсе Zabbix перейдите в раздел **Configuration** (Конфигурация) → **Hosts** (Узлы сети).
2. Выберите нужный хост или создайте новый.
3. На вкладке **Templates** (Шаблоны) добавьте стандартный шаблон `MySQL by Zabbix agent`.
4. Сохраните изменения и проверьте поступление данных в разделе **Monitoring** (Мониторинг) → **Latest data** (Последние данные).

## Дополнительная информация

**Ключевые метрики для мониторинга:**

- **Доступность**: `mysql.ping` (состояние сервиса).
- **Производительность**:
  - `Slow_queries` (количество медленных запросов).
  - `Threads_connected` (количество активных соединений).
  - **Innodb Buffer Pool Hit Rate**: эффективность использования оперативной памяти для кэширования данных.
- **Репликация**:
  - `Slave_running` (статус потоков репликации).
  - `Seconds_behind_master` (отставание от мастера в секундах).

**Альтернативные методы:**

- [Использование Prometheus mysqld_exporter](../../Prometheus/Exporters/other_exporters.md).
- [Percona Monitoring and Management (PMM)](./overview.md) — специализированное решение для глубокого анализа производительности.
