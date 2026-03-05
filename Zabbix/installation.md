# Zabbix: Установка и настройка

> **Примечание:** В примерах ниже используется Zabbix 7.0 LTS. Для актуальных версий проверьте официальные репозитории на [zabbix.com](https://www.zabbix.com/download).

---

## Установка Zabbix Server (на Ubuntu)

### 1. Установка необходимых компонентов (Apache, MariaDB, PHP)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y apache2 mariadb-server mariadb-client php php-cgi php-mbstring php-gd php-xml php-mysql php-bcmath php-ldap php-json
```

### 2. Добавление репозитория Zabbix

```bash
# Для Zabbix 7.0 LTS
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_7.0-4+ubuntu22.04_all.deb
sudo dpkg -i zabbix-release_7.0-4+ubuntu22.04_all.deb
sudo apt update
```

### 3. Установка компонентов Zabbix

```bash
sudo apt install -y zabbix-server-mysql zabbix-frontend-php zabbix-apache-conf zabbix-sql-scripts zabbix-agent
```

### 4. Создание и настройка базы данных

```sql
-- Входим в консоль MariaDB: sudo mysql -uroot -p
CREATE DATABASE zabbix CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

# Создаем пользователя и задаем пароль (замените 'your_password' на надежный пароль)
CREATE USER 'zabbix'@'localhost' IDENTIFIED BY 'your_password';

# Выдаем привилегии
GRANT ALL PRIVILEGES ON zabbix.* TO 'zabbix'@'localhost';

# Выходим
FLUSH PRIVILEGES;
quit;
```

### 5. Импорт начальной схемы данных

```bash
# Импортируем схему в созданную БД. Система запросит пароль пользователя 'zabbix'.
zcat /usr/share/zabbix-sql-scripts/mysql/server.sql.gz | sudo mysql -uzabbix -p zabbix
```

### 6. Конфигурация Zabbix Server и PHP

* В файле `/etc/zabbix/zabbix_server.conf` укажите пароль `DBPassword`.
* В файле `/etc/php/8.1/apache2/php.ini` задайте свой часовой пояс `date.timezone`.

### 7. Запуск служб

```bash
sudo systemctl restart zabbix-server zabbix-agent apache2
sudo systemctl enable zabbix-server zabbix-agent apache2
```

### 8. Завершение установки через веб-интерфейс

* Откройте `http://<IP-адрес_сервера>/zabbix`.
* Следуйте шагам мастера установки, указав пароль от БД.
* Стандартные учетные данные для входа: `Admin` / `zabbix`.

---

## Установка Zabbix Agent (на Ubuntu)

### 1. Добавление репозитория Zabbix и установка

```bash
# Репозиторий добавляется так же, как для сервера
sudo apt update
sudo apt install zabbix-agent
```

### 2. Настройка агента

Отредактируйте `/etc/zabbix/zabbix_agentd.conf`:

```ini
# IP-адрес вашего Zabbix-сервера
Server=192.168.1.100

# Для активных проверок
ServerActive=192.168.1.100

# Имя хоста (должно совпадать с именем в веб-интерфейсе Zabbix)
Hostname=MyUbuntuServer
```

### 3. Запуск службы и настройка файрвола

```bash
sudo systemctl restart zabbix-agent
sudo systemctl enable zabbix-agent
# Разрешите входящие подключения на порт 10050/tcp от Zabbix-сервера
sudo ufw allow from 192.168.1.100 to any port 10050 proto tcp
```

> **См. также:**
>
> * **[Мониторинг MySQL с помощью Zabbix Agent](../Databases/MySQL/monitoring.md)** — практический пример настройки UserParameter для MySQL
> * **[Мониторинг PostgreSQL с помощью Zabbix Agent 2](./zabbix_postgresql_monitoring.md)** — современный подход к мониторингу PostgreSQL

После этого не забудьте добавить хост в веб-интерфейсе Zabbix.

---

## Отправка данных с помощью zabbix_sender

```bash
zabbix_sender -z <zabbix_server_ip> -p 10051 -s <hostname> -k <item_key> -o <value>
```

* `-z`: IP-адрес Zabbix-сервера.
* `-s`: Имя хоста в Zabbix (должно точно совпадать).
* `-k`: Ключ `trapper`-элемента.
* `-o`: Отправляемое значение.

---

## Настройка SNMP-мониторинга

1. При создании хоста в Zabbix добавляется интерфейс типа **SNMP**.
2. Указывается IP-адрес или DNS-имя устройства.
3. Задаются параметры SNMP:
   * **SNMP version:** Чаще всего `2`.
   * **SNMP community:** Строка-пароль (например, `public`), которая должна совпадать с настроенной на устройстве.

---

## Пример автоматического добавления хоста

Настроив правило обнаружения для сети `192.168.1.0/24` и действие, которое реагирует на значение `Linux` от проверки `system.uname`, новые Linux-серверы с установленным агентом будут автоматически добавляться в Zabbix в группу `Linux servers` и ставиться на мониторинг с шаблоном `Linux by Zabbix agent`.

---

## Ссылки

* **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
* **[Мониторинг БД](./zabbix_database_monitoring.md)** — мониторинг СУБД
* **[Best Practices](./zabbix_best_practices.md)** — лучшие практики
