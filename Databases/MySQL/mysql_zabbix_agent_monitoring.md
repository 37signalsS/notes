# Мониторинг MySQL с помощью Zabbix Agent

## 1. Конфигурация Zabbix Agent

Zabbix Agent работает на сервере, где расположена база данных MySQL.

### 1.1. Основной конфигурационный файл `zabbix_agentd.conf`

В файле `zabbix_agentd.conf` (обычно расположенном в `/etc/zabbix/` или `/etc/zabbix/zabbix_agentd.d/`) убедитесь, что настроены следующие параметры:

*   `Server`: IP-адрес или DNS-имя Zabbix Server и/или Zabbix Proxy, которые могут запрашивать метрики. Например: `Server=192.168.1.100` (для пассивного режима).
*   `ServerActive`: IP-адрес или DNS-имя Zabbix Server для активных проверок. Например: `ServerActive=192.168.1.100`.
*   `Hostname`: Уникальное имя хоста, соответствующее имени хоста в Zabbix Frontend. Например: `Hostname=MyMySQLServer`.

### 1.2. Добавление пользовательских параметров (`UserParameter`) для MySQL

**Лучшая практика:** Рекомендуется создавать отдельные файлы конфигурации для пользовательских параметров в директории `zabbix_agentd.d/` (например, `/etc/zabbix/zabbix_agentd.d/mysql.conf`). Это позволяет избежать разрастания основного конфигурационного файла `zabbix_agentd.conf`, упрощает управление и отключение отдельных модулей мониторинга, а также способствует более организованному хранению настроек для различных сервисов.

Пример файла `/etc/zabbix/zabbix_agentd.d/mysql.conf`:

```conf
# Файл: /etc/zabbix/zabbix_agentd.d/mysql.conf
# Пример UserParameter для MySQL. Фактические параметры могут отличаться
# в зависимости от используемого шаблона Zabbix.

# Пример пинга MySQL
UserParameter=mysql.ping,mysqladmin -u"$1" -p"$2" ping | grep -c alive

# Пример получения статусной переменной
UserParameter=mysql.status[*],echo "show global status where Variable_name='$1';" | mysql -N -u"$2" -p"$3" | awk '{print $2}'

# Пример получения размеров базы данных
UserParameter=mysql.size[*],echo "SELECT sum(data_length+index_length) FROM information_schema.tables WHERE table_schema='$1';" | mysql -N -u"$2" -p"$3"

# ... и другие параметры, необходимые для шаблона "MySQL by Zabbix agent"
```
Эти `UserParameter` определяют, как Zabbix Agent будет получать специфические метрики MySQL, выполняя команды `mysqladmin` или запросы `mysql`.

После внесения изменений перезапустите Zabbix Agent:
```bash
sudo systemctl restart zabbix-agent
```

## 2. Создание Пользователя MySQL для Мониторинга

Для того чтобы Zabbix Agent мог получать метрики из MySQL, ему нужен специальный пользователь с ограниченными правами.

```sql
CREATE USER 'zabbix_monitor'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT REPLICATION CLIENT ON *.* TO 'zabbix_monitor'@'localhost';
GRANT PROCESS ON *.* TO 'zabbix_monitor'@'localhost';
GRANT SHOW DATABASES ON *.* TO 'zabbix_monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'zabbix_monitor'@'localhost';
GRANT SELECT ON sys.* TO 'zabbix_monitor'@'localhost';
FLUSH PRIVILEGES;
```
*   **`zabbix_monitor`**: Имя пользователя для мониторинга.
*   **`localhost`**: Указывает, что пользователь может подключаться только с локального хоста, где запущен Zabbix Agent.
*   **`your_secure_password`**: Замените на надежный пароль.
*   **`REPLICATION CLIENT`, `PROCESS`, `SHOW DATABASES`, `SELECT ON performance_schema.*`, `SELECT ON sys.*`**: Необходимые привилегии для сбора широкого спектра метрик состояния, информации о процессах, репликации и базах данных.

## 3. Настройка Конфигурационного Файла `my.cnf` для Пользователя Zabbix

Чтобы Zabbix Agent мог подключаться к MySQL без интерактивного запроса пароля, создайте файл `my.cnf` в домашней директории пользователя `zabbix` (пользователь, от которого работает Zabbix Agent).

### 3.1. Определение домашней директории пользователя `zabbix`

```bash
grep zabbix /etc/passwd
```
Обычно это `/var/lib/zabbix` или `/home/zabbix`. Если домашняя директория не существует, создайте ее:
```bash
sudo mkdir -p /var/lib/zabbix
sudo chown zabbix:zabbix /var/lib/zabbix
```

### 3.2. Создание файла `.my.cnf`

Создайте файл `.my.cnf` в домашней директории пользователя `zabbix` (например, `/var/lib/zabbix/.my.cnf`):
```ini
[client]
user=zabbix_monitor
password=your_secure_password
```
Замените `your_secure_password` на тот, который вы использовали при создании пользователя `zabbix_monitor`.

### 3.3. Настройка прав доступа к `.my.cnf`

Крайне важно установить правильные права доступа, чтобы только пользователь `zabbix` мог читать этот файл:
```bash
sudo chown zabbix:zabbix /var/lib/zabbix/.my.cnf
sudo chmod 600 /var/lib/zabbix/.my.cnf
```
Это гарантирует, что файл с учетными данными будет доступен только Zabbix Agent'у.

## 4. Добавление Хоста и Шаблона в Zabbix Frontend

1.  **Добавьте хост** в Zabbix Frontend, используя имя хоста, которое вы указали в `zabbix_agentd.conf` (`Hostname`).
2.  **Привяжите шаблон** `MySQL by Zabbix agent` к созданному хосту.
    *   Перейдите в `Configuration` -> `Hosts`.
    *   Выберите ваш хост MySQL.
    *   В разделе `Templates` найдите и выберите `MySQL by Zabbix agent`.
    *   Сохраните изменения.

## 5. Проверка Собранных Данных

После настройки и привязки шаблона Zabbix Server начнет собирать метрики. Вы можете проверить их статус:
*   Перейдите в `Monitoring` -> `Latest data`.
*   Выберите ваш хост MySQL и нажмите `Apply`.
*   Вы должны увидеть список собранных метрик MySQL.
*   Например, метрики `MySQL.ping`, `MySQL.status.variables`, `MySQL.size` и другие, определенные в шаблоне.

В случае проблем проверьте логи Zabbix Agent (`/var/log/zabbix/zabbix_agentd.log`) и Zabbix Server (`/var/log/zabbix/zabbix_server.log`) на наличие ошибок.
Также можно вручную проверить работу `UserParameter` с помощью `zabbix_get`:
```bash
zabbix_get -s <IP_адрес_MySQL_сервера> -k "mysql.ping[zabbix_monitor,your_secure_password]"
```
Если возвращается `1`, пинг успешен.

## 6. Настройка Триггеров и Оповещений

Шаблон `MySQL by Zabbix agent` содержит предопределенные триггеры для общих проблем MySQL. Рекомендуется просмотреть и настроить эти триггеры, а также соответствующие действия (actions) для оповещений:
*   **Тонкая настройка триггеров:** Отредактируйте пороги и выражения триггеров, чтобы они соответствовали специфике вашей инфраструктуры и избегали ложных срабатываний.
*   **Действия (Actions):** Настройте отправку оповещений по электронной почте, в Telegram или другие каналы при срабатывании триггеров. Подробности настройки оповещений см. в документе `Zabbix/zabbix_database_monitoring.md`.
*   **Зависимости:** Используйте зависимости между триггерами, чтобы уменьшить количество оповещений при возникновении корневой проблемы.
