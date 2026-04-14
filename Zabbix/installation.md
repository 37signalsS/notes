# Zabbix: Установка и настройка

> **Примечание:** В примерах ниже используется Zabbix 7.0 LTS. Для актуальных версий проверьте официальные репозитории на [zabbix.com](https://www.zabbix.com/download).
>
> Архитектура и концепции Zabbix: **[Определения и основные концепции](./definitions_and_concepts.md)**.

---

## Определения

* **Zabbix Server** — центральное ядро системы мониторинга, собирающее, хранящее и анализирующее данные.
* **Zabbix Agent** — программа, устанавливаемая на хосты для сбора метрик (classic на C, Agent 2 на Go).
* **Zabbix Trapper** — тип элемента данных, принимающий push-данные через утилиту `zabbix_sender` (подробнее: [дополнительная информация](./additional_info.md#практические-сценарии)).

---

## Основные концепции

### Компоненты стека Zabbix Server

Для работы Zabbix Server требуются:

* **Веб-сервер:** Apache или Nginx
* **СУБД:** MySQL/MariaDB или PostgreSQL
* **PHP:** с расширениями `php-cgi`, `php-mbstring`, `php-gd`, `php-xml`, `php-mysql`, `php-bcmath`, `php-ldap`, `php-json`
* **Zabbix Frontend:** веб-интерфейс управления

### Компоненты Zabbix Agent

Агент состоит из:

* Демона `zabbix-agent` (classic) или `zabbix-agent2` (Go)
* Конфигурационного файла `/etc/zabbix/zabbix_agentd.conf`
* Каталогов дополнительных конфигураций `/etc/zabbix/zabbix_agentd.conf.d/`

Режимы работы описаны в разделе [модели сбора данных](./definitions_and_concepts.md#модель-pull-vs-push).

---

## Практические сценарии

### Установка Zabbix Server на Ubuntu

#### 1. Установка зависимостей (Apache, MariaDB, PHP)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y apache2 mariadb-server mariadb-client php php-cgi php-mbstring php-gd php-xml php-mysql php-bcmath php-ldap php-json
```

#### 2. Добавление репозитория Zabbix

```bash
# Для Zabbix 7.0 LTS
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_7.0-4+ubuntu22.04_all.deb
sudo dpkg -i zabbix-release_7.0-4+ubuntu22.04_all.deb
sudo apt update
```

#### 3. Установка компонентов Zabbix

```bash
sudo apt install -y zabbix-server-mysql zabbix-frontend-php zabbix-apache-conf zabbix-sql-scripts zabbix-agent
```

#### 4. Создание и настройка базы данных

```sql
-- Вход в консоль MariaDB: sudo mysql -uroot -p
CREATE DATABASE zabbix CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'zabbix'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON zabbix.* TO 'zabbix'@'localhost';
FLUSH PRIVILEGES;
quit;
```

#### 5. Импорт начальной схемы данных

```bash
zcat /usr/share/zabbix-sql-scripts/mysql/server.sql.gz | sudo mysql -uzabbix -p zabbix
```

#### 6. Конфигурация Zabbix Server и PHP

* В `/etc/zabbix/zabbix_server.conf` указать `DBPassword=your_password`
* В `/etc/php/8.1/apache2/php.ini` задать `date.timezone = Europe/Moscow`

#### 7. Запуск служб

```bash
sudo systemctl restart zabbix-server zabbix-agent apache2
sudo systemctl enable zabbix-server zabbix-agent apache2
```

#### 8. Завершение установки через веб-интерфейс

1. Открыть `http://<IP-адрес_сервера>/zabbix`
2. Следовать шагам мастера, указав пароль от БД
3. Стандартные учётные данные: `Admin` / `zabbix`

---

### Установка Zabbix Agent на Ubuntu

#### 1. Установка агента

```bash
sudo apt update
sudo apt install zabbix-agent
```

#### 2. Настройка агента

Отредактировать `/etc/zabbix/zabbix_agentd.conf`:

```ini
# IP-адрес Zabbix-сервера (пассивные проверки)
Server=192.168.1.100

# IP-адрес для активных проверок
ServerActive=192.168.1.100

# Имя хоста (должно совпадать с именем в веб-интерфейсе Zabbix)
Hostname=MyUbuntuServer
```

#### 3. Запуск службы и настройка файрвола

```bash
sudo systemctl restart zabbix-agent
sudo systemctl enable zabbix-agent
sudo ufw allow from 192.168.1.100 to any port 10050 proto tcp
```

После установки агента хост добавляется в веб-интерфейсе Zabbix вручную или автоматически через [обнаружение хостов](./definitions_and_concepts.md#обнаружение-хостов-network-discovery).

---

### Отправка данных через zabbix_sender

Утилита `zabbix_sender` используется для push-отправки метрик на Zabbix Server (trapper-элементы):

```bash
zabbix_sender -z <zabbix_server_ip> -p 10051 -s <hostname> -k <item_key> -o <value>
```

| Параметр | Описание |
|----------|----------|
| `-z` | IP-адрес Zabbix-сервера |
| `-s` | Имя хоста (должно точно совпадать с именем в Zabbix) |
| `-k` | Ключ trapper-элемента |
| `-o` | Отправляемое значение |

Практический пример batch-отправки: [LLD с zabbix_sender](./additional_info.md#пример-настройки-lld-с-zabbix_sender).

---

### Настройка SNMP-мониторинга

При создании хоста в Zabbix добавляется интерфейс типа **SNMP** с параметрами:

* **SNMP version:** `2` (наиболее распространён)
* **SNMP community:** строка-пароль (например, `public`), совпадающая с настроенной на устройстве

Подробнее: [SNMP](./definitions_and_concepts.md).

---

### Автоматическое добавление хостов

Пример: настроив [правило обнаружения](./definitions_and_concepts.md#обнаружение-хостов-network-discovery) для сети `192.168.1.0/24` и [действие](./definitions_and_concepts.md#обнаружение-хостов-network-discovery), реагирующее на значение `Linux` от проверки `system.uname`, новые Linux-серверы с установленным агентом автоматически добавляются в группу `Linux servers` с шаблоном `Linux by Zabbix agent`.

---

## Дополнительная информация

### Версии и поддержка

| Версия | Тип | Дата выхода | Поддержка до |
|--------|-----|-------------|--------------|
| Zabbix 7.0 | LTS | Июнь 2024 | Июнь 2029 |
| Zabbix 7.4 | Stable | Октябрь 2025 | Октябрь 2026 |
| Zabbix 8.0 | LTS (план) | 2026 | — |

### Связанные документы

* **[Мониторинг MySQL](../Databases/MySQL/monitoring.md)** — настройка UserParameter для MySQL
* **[Мониторинг PostgreSQL](./zabbix_postgresql_monitoring.md)** — мониторинг через Zabbix Agent 2
* **[Мониторинг БД](./zabbix_database_monitoring.md)** — общие подходы к мониторингу СУБД
* **[Лучшие практики](./zabbix_best_practices.md)** — рекомендации по настройке триггеров и оповещений
