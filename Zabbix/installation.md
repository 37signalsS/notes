# Zabbix — установка и настройка

> **Примечание:** В примерах ниже используется Zabbix 7.0 LTS. Для получения актуальной информации о версиях и загрузки дистрибутивов рекомендуется обращаться к [официальному сайту Zabbix](https://www.zabbix.com/download).

---

## Определения

Основные архитектурные компоненты и терминология (Server, Proxy, Agent, Trapper, SNMP) подробно описаны в разделе **[Определения и основные концепции](./definitions_and_concepts.md)**.

---

## Основные концепции

### Компоненты серверного стека

Для функционирования Zabbix Server необходимы следующие программные компоненты:

* **Веб-сервер:** Apache или Nginx (используется для работы веб-интерфейса).
* **СУБД:** MySQL, MariaDB или PostgreSQL (хранение истории, трендов и конфигурации).
* **PHP:** серверный язык программирования с набором расширений (`php-cgi`, `php-mbstring`, `php-gd`, `php-xml`, `php-mysql` или `php-pgsql`, `php-bcmath`, `php-ldap`, `php-json`).
* **Zabbix Frontend:** графический интерфейс управления.

### Состав Zabbix Agent

Агент включает в себя:

* Бинарный файл демона (`zabbix_agentd` или `zabbix_agent2`).
* Основной файл конфигурации: `/etc/zabbix/zabbix_agentd.conf`.
* Директорию для подключаемых пользовательских конфигураций: `/etc/zabbix/zabbix_agentd.conf.d/`.

Сравнение режимов работы агента доступно в разделе **[Модели сбора данных](./definitions_and_concepts.md#модель-pull-vs-push)**.

---

## Практические сценарии

### Установка Zabbix Server на Ubuntu (MySQL/MariaDB)

#### 1. Установка зависимостей

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y apache2 mariadb-server mariadb-client php php-cgi php-mbstring php-gd php-xml php-mysql php-bcmath php-ldap php-json
```

#### 2. Добавление официального репозитория

```bash
# Пример для Zabbix 7.0 LTS на Ubuntu 22.04
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_7.0-4+ubuntu22.04_all.deb
sudo dpkg -i zabbix-release_7.0-4+ubuntu22.04_all.deb
sudo apt update
```

#### 3. Установка компонентов Zabbix

```bash
sudo apt install -y zabbix-server-mysql zabbix-frontend-php zabbix-apache-conf zabbix-sql-scripts zabbix-agent
```

#### 4. Настройка базы данных

```sql
-- Вход: sudo mysql -uroot -p
CREATE DATABASE zabbix CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'zabbix'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON zabbix.* TO 'zabbix'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

#### 5. Импорт начальной схемы

```bash
zcat /usr/share/zabbix-sql-scripts/mysql/server.sql.gz | sudo mysql -uzabbix -p zabbix
```

#### 6. Конфигурация сервера и PHP

* В `/etc/zabbix/zabbix_server.conf` установите: `DBPassword=your_password`.
* В `/etc/php/8.1/apache2/php.ini` укажите часовой пояс: `date.timezone = Europe/Moscow`.

#### 7. Запуск сервисов

```bash
sudo systemctl restart zabbix-server zabbix-agent apache2
sudo systemctl enable zabbix-server zabbix-agent apache2
```

Завершите установку через веб-интерфейс: `http://<IP_сервера>/zabbix` (учетные данные по умолчанию: `Admin` / `zabbix`).

---

### Установка Zabbix Server с PostgreSQL и TimescaleDB

Данная конфигурация рекомендуется для высоконагруженных инсталляций. Подробности технологии: **[Обзор TimescaleDB](../Databases/timescaledb.md)**.

#### 1. Установка PostgreSQL и TimescaleDB

```bash
sudo apt install postgresql postgresql-contrib timescaledb-2-postgresql-16
```

В файле `/etc/postgresql/16/main/postgresql.conf` необходимо добавить:
`shared_preload_libraries = 'timescaledb'`

#### 2. Установка пакетов Zabbix

```bash
sudo apt install zabbix-server-pgsql zabbix-frontend-php php8.1-pgsql zabbix-apache-conf zabbix-sql-scripts zabbix-agent
```

#### 3. Инициализация БД и расширения

```bash
sudo -u postgres psql
```

```sql
CREATE USER zabbix WITH PASSWORD 'zabbix';
CREATE DATABASE zabbix OWNER zabbix;
\c zabbix
CREATE EXTENSION IF NOT EXISTS timescaledb;
\q
```

#### 4. Импорт данных и активация гипертаблиц

```bash
zcat /usr/share/zabbix-sql-scripts/postgresql/server.sql.gz | sudo -u zabbix psql zabbix
cat /usr/share/zabbix-sql-scripts/postgresql/timescaledb.sql | sudo -u zabbix psql zabbix
```

---

### Установка и настройка Zabbix Agent

#### 1. Установка

```bash
sudo apt update && sudo apt install zabbix-agent
```

#### 2. Настройка (`/etc/zabbix/zabbix_agentd.conf`)

```ini
Server=192.168.1.100       # Адрес сервера для пассивных проверок
ServerActive=192.168.1.100 # Адрес сервера для активных проверок
Hostname=TargetServer      # Имя хоста, должно совпадать с именем в веб-интерфейсе
```

#### 3. Запуск и настройка сетевого доступа

```bash
sudo systemctl restart zabbix-agent
sudo systemctl enable zabbix-agent
sudo ufw allow from 192.168.1.100 to any port 10050 proto tcp
```

---

### Отправка данных через zabbix_sender

Используется для передачи метрик в trapper-элементы:

```bash
zabbix_sender -z <server_ip> -p 10051 -s <hostname> -k <item_key> -o <value>
```

| Параметр | Описание |
| :--- | :--- |
| `-z` | IP-адрес или DNS-имя Zabbix Server. |
| `-s` | Имя хоста в системе мониторинга. |
| `-k` | Ключ элемента данных типа Zabbix trapper. |
| `-o` | Значение метрики. |

---

### Настройка SNMP-мониторинга

Для мониторинга сетевых устройств без агента:

1. На устройстве настраивается SNMP-агент (community string, версия).
2. В Zabbix создается хост с интерфейсом типа **SNMP**.
3. Указываются параметры:
    * **SNMP version:** 2 (рекомендуется для большинства случаев).
    * **SNMP community:** пароль доступа (например, `public`).

Подробнее о протоколе: **[SNMP в Zabbix](./definitions_and_concepts.md#определения)**.

---

### Автоматическое обнаружение хостов (Network Discovery)

Пример настройки автоматического добавления Linux-серверов:

1. **Discovery rule:** задается диапазон сети (например, `192.168.1.0/24`) и проверка (например, `system.uname` через Zabbix Agent).
2. **Action:** настраивается реакция. Если результат проверки содержит `Linux`, хост добавляется в группу `Linux servers` и к нему привязывается шаблон `Linux by Zabbix agent`.

Концептуальное описание механизма: **[Обнаружение хостов](./definitions_and_concepts.md#обнаружение-хостов-network-discovery)**.

---

## Дополнительная информация

### Жизненный цикл версий

| Версия | Тип | Поддержка |
| :--- | :--- | :--- |
| Zabbix 7.0 | LTS | до июня 2029 года |
| Zabbix 7.4 | Stable | до октября 2026 года |

### См. также

* **[Мониторинг СУБД](./zabbix_database_monitoring.md)** — общие подходы к мониторингу баз данных.
* **[Мониторинг PostgreSQL](./zabbix_postgresql_monitoring.md)** — настройка мониторинга через Zabbix Agent 2.
* **[Лучшие практики](./zabbix_best_practices.md)** — рекомендации по настройке триггеров и оптимизации.
