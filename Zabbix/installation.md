# Zabbix — установка и настройка

> **Примечание:** В примерах ниже используется Zabbix 7.0 LTS. Для получения актуальной информации и загрузки дистрибутивов рекомендуется обращаться к [официальному сайту Zabbix](https://www.zabbix.com/download).

---

## Определения

Основные архитектурные компоненты (Server, Proxy, Agent, Trapper) и терминология подробно описаны в разделе **[Определения и основные концепции](./definitions_and_concepts.md)**.

---

## Основные концепции

### Компоненты серверного стека

Для функционирования Zabbix Server необходимы следующие компоненты:

*   **Веб-сервер:** Nginx или Apache (используется для работы веб-интерфейса).
*   **СУБД:** PostgreSQL (рекомендуется с TimescaleDB) или MySQL/MariaDB.
*   **PHP:** серверный язык программирования (версии 8.0+ для Zabbix 7.0).
*   **Zabbix Frontend:** графический интерфейс управления.

### Выбор агента

*   **Zabbix Agent 2:** Рекомендуется для новых инсталляций. Написан на Go, поддерживает многопоточность и плагины (Docker, PostgreSQL, MySQL и др.).
*   **Zabbix Agent (Classic):** Написан на C, потребляет меньше памяти. Используется в legacy-системах или на устройствах с ограниченными ресурсами.

Сравнение режимов работы доступно в разделе **[Модели сбора данных](./definitions_and_concepts.md#модель-pull-vs-push)**.

---

## Практические сценарии

### Установка Zabbix Server на Ubuntu 24.04 (PostgreSQL + TimescaleDB)

Данная конфигурация является стандартом для высоконагруженных систем. Подробности технологии: **[Обзор TimescaleDB](../Databases/timescaledb.md)**.

#### 1. Добавление официального репозитория

```bash
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_7.0-4+ubuntu24.04_all.deb
sudo dpkg -i zabbix-release_7.0-4+ubuntu24.04_all.deb
sudo apt update
```

#### 2. Установка PostgreSQL и TimescaleDB

```bash
sudo apt install -y postgresql postgresql-contrib timescaledb-2-postgresql-16
# Оптимизация PostgreSQL под TimescaleDB
sudo timescaledb-tune --quiet --yes
sudo systemctl restart postgresql
```

#### 3. Установка пакетов Zabbix

```bash
sudo apt install -y zabbix-server-pgsql zabbix-frontend-php zabbix-nginx-conf zabbix-sql-scripts zabbix-agent2
```

#### 4. Инициализация базы данных

```bash
sudo -u postgres psql -c "CREATE USER zabbix WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE zabbix OWNER zabbix;"
# Активация TimescaleDB
sudo -u postgres psql -d zabbix -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

Импорт начальной схемы и активация гипертаблиц:
```bash
zcat /usr/share/zabbix-sql-scripts/postgresql/server.sql.gz | sudo -u zabbix psql zabbix
cat /usr/share/zabbix-sql-scripts/postgresql/timescaledb.sql | sudo -u zabbix psql zabbix
```

#### 5. Конфигурация Zabbix Server

В файле `/etc/zabbix/zabbix_server.conf` укажите пароль:
`DBPassword=your_password`

#### 6. Настройка Nginx и PHP

В файле `/etc/zabbix/nginx.conf` раскомментируйте директивы `listen` и `server_name`.
Перезапустите сервисы:
```bash
sudo systemctl restart zabbix-server zabbix-agent2 nginx php8.3-fpm
sudo systemctl enable zabbix-server zabbix-agent2 nginx php8.3-fpm
```

Завершите настройку через веб-интерфейс: `http://<IP_сервера>` (Admin / zabbix).

---

### Развертывание через Docker Compose

Быстрый способ запуска всего стека в изолированных контейнерах.

```yaml
version: '3.8'
services:
  zabbix-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: zabbix
      POSTGRES_PASSWORD: zabbix_password
      POSTGRES_DB: zabbix
    volumes:
      - ./zbx_db_data:/var/lib/postgresql/data
  
  zabbix-server:
    image: zabbix/zabbix-server-pgsql:7.0-ubuntu-latest
    ports:
      - "10051:10051"
    environment:
      DB_SERVER_HOST: zabbix-db
      POSTGRES_USER: zabbix
      POSTGRES_PASSWORD: zabbix_password
    depends_on:
      - zabbix-db

  zabbix-web:
    image: zabbix/zabbix-web-nginx-pgsql:7.0-ubuntu-latest
    ports:
      - "8080:8080"
    environment:
      ZBX_SERVER_HOST: zabbix-server
      DB_SERVER_HOST: zabbix-db
      POSTGRES_USER: zabbix
      POSTGRES_PASSWORD: zabbix_password
    depends_on:
      - zabbix-server
```

---

### Установка и настройка Zabbix Proxy

Используется для мониторинга удаленных локаций и распределения нагрузки.

#### 1. Установка (с использованием SQLite3)

SQLite3 рекомендуется для небольших прокси, так как не требует настройки полноценной СУБД.
```bash
sudo apt install -y zabbix-proxy-sqlite3 zabbix-sql-scripts
```

#### 2. Настройка (`/etc/zabbix/zabbix_proxy.conf`)

```ini
Server=192.168.1.100  # IP основного Zabbix Server
Hostname=Branch-Proxy # Должно совпадать с именем в веб-интерфейсе
DBName=/var/lib/zabbix/zabbix_proxy.db
```

---

### Настройка безопасности и шифрования (PSK)

Для защиты трафика между агентом и сервером используйте Pre-Shared Keys.

#### 1. Генерация ключа

```bash
openssl rand -hex 32 | sudo tee /etc/zabbix/zabbix_agent2.psk
```

#### 2. Настройка агента (`/etc/zabbix/zabbix_agent2.conf`)

```ini
TLSConnect=psk
TLSAccept=psk
TLSPSKIdentity=PSK_001
TLSPSKFile=/etc/zabbix/zabbix_agent2.psk
```

#### 3. Настройка в веб-интерфейсе

В свойствах хоста на вкладке **Encryption**:
*   **Connections to host:** PSK.
*   **Connections from host:** PSK.
*   **PSK identity:** PSK_001.
*   **PSK:** (содержимое сгенерированного файла).

---

### Высокая доступность (High Availability)

Zabbix 6.0+ поддерживает нативный режим HA для сервера.

1.  Установите несколько узлов Zabbix Server, подключенных к одной БД.
2.  В `zabbix_server.conf` каждого узла укажите уникальное имя в параметре `HANodeName`.
3.  Серверы автоматически создадут кластер. Статус можно проверить командой:
    `zabbix_server -R ha_status`

---

### Настройка SNMP-мониторинга

Для устройств без возможности установки агента:

1.  Установите утилиты SNMP: `sudo apt install snmp snmp-mibs-downloader`.
2.  На целевом устройстве включите SNMP (v2c или v3).
3.  В Zabbix создайте хост с интерфейсом **SNMP** и укажите **Community string** (например, `public`).

Подробнее: **[SNMP в Zabbix](./definitions_and_concepts.md#определения)**.

---

### Автоматическое обнаружение хостов (Network Discovery)

Пример настройки автоматического добавления Linux-серверов:

1.  **Discovery rule:** задается диапазон сети (например, `192.168.1.0/24`) и проверка (например, `system.uname` через Zabbix Agent).
2.  **Action:** настраивается реакция. Если результат проверки содержит `Linux`, хост добавляется в группу `Linux servers` и к нему привязывается шаблон `Linux by Zabbix agent`.

Концептуальное описание механизма: **[Обнаружение хостов](./definitions_and_concepts.md#автоматизация-через-discovery)**.

---

### Отправка данных через zabbix_sender

Используется для передачи метрик в trapper-элементы:

```bash
zabbix_sender -z <server_ip> -s <hostname> -k <item_key> -o <value>
# → Response from "192.168.1.100:10051": "processed: 1; failed: 0; total: 1; seconds spent: 0.000045"
```

---

## Дополнительная информация

### Жизненный цикл версий (на июль 2026)

| Версия | Статус | Конец поддержки (Full) | Конец поддержки (Limited) |
| :--- | :--- | :--- | :--- |
| **Zabbix 7.0** | **LTS** | Июнь 2029 | Июнь 2031 |
| Zabbix 7.4 | Stable | Октябрь 2026 | — |
| Zabbix 8.0 | LTS | Ожидается в Q4 2026 | — |

### См. также

* **[Мониторинг СУБД](./zabbix_database_monitoring.md)** — общие подходы к мониторингу баз данных.
* **[Мониторинг PostgreSQL](./zabbix_postgresql_monitoring.md)** — настройка мониторинга через Zabbix Agent 2.
* **[Тюнинг производительности](./zabbix_troubleshooting_and_performance_tuning.md)** — оптимизация Zabbix и БД.
* **[Лучшие практики](./zabbix_best_practices.md)** — рекомендации по настройке триггеров.
