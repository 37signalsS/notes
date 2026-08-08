# Zabbix — установка и настройка

> **Примечание:** В примерах ниже используется Zabbix 7.0 LTS — актуальная долгосрочная версия (на август 2026). Ожидается выход Zabbix 8.0 LTS в Q3 2026 (сентябрь). Для получения актуальной информации и загрузки дистрибутивов рекомендуется обращаться к [официальному сайту Zabbix](https://www.zabbix.com/download).

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

Сравнение режимов работы доступно в разделе **[Модели сбора данных](./definitions_and_concepts.md#модели-сбора-данных)**.

---

## Практические сценарии

### Установка Zabbix Server на Ubuntu 24.04 (PostgreSQL + TimescaleDB)

Данная конфигурация является стандартом для высоконагруженных систем. Подробности технологии: **[Обзор TimescaleDB](../Databases/timescaledb.md)**.

#### 1. Добавление официального репозитория

```bash
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest+ubuntu24.04_all.deb
sudo dpkg -i zabbix-release_latest+ubuntu24.04_all.deb
sudo apt update
```

> Алиас `latest` в имени пакета всегда ссылается на актуальную версию пакета репозитория (актуальная на август 2026: `zabbix-release_7.0-5+ubuntu24.04_all.deb`), поэтому нет необходимости вручную обновлять номер версии.

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

#### 7. Завершение настройки через веб-интерфейс

Перейдите по адресу `http://<IP_сервера>` и выполните шаги мастера установки:

1.  **Регистрация:** при необходимости укажите имя сети и загрузите файл конфигурации Zabbix.
2.  **Проверка предпосылок:** мастер проверяет готовность PHP, СУБД и прав на файлы. Убедитесь, что нет красных пунктов.
3.  **Подключение к базе данных:** укажите **Database type**, адрес (`localhost`), порт, а также `DB name` (`zabbix`), `User` (`zabbix`) и `Password` — те же значения, что и в `zabbix_server.conf`.
4.  **Сведения о сервере (Zabbix server details):** укажите hostname сервера и, опционально, порт.
5.  **Сводка и установка:** нажмите **Install** и дождитесь завершения.
6.  **Вход:** по умолчанию логин `Admin`, пароль `zabbix`, **обязательно** смените пароль сразу после первого входа (профиль пользователя — change password).

---

### Установка Zabbix Server на RHEL / Rocky Linux / AlmaLinux 9

Альтернативная конфигурация для дистрибутивов семейства RHEL (dnf-based). Команды актуальны для **Zabbix 7.0 LTS** на RHEL 9 и его производных.

#### 1. Добавление официального репозитория

```bash
sudo rpm -Uvh https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/zabbix-release-7.0-5.el9.noarch.rpm
sudo dnf clean all
sudo dnf -y update
```

> Внимание: номер сборки пакета репозитория (`zabbix-release-7.0-5`) изменяется при обновлениях. Проверяйте актуальную версию на [странице загрузки Zabbix](https://www.zabbix.com/download).

#### 2. Установка PostgreSQL и пакетов Zabbix

```bash
sudo dnf install -y epel-release postgresql-server postgresql-server-devel
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
sudo dnf install -y zabbix-server-pgsql zabbix-web-pgsql zabbix-nginx-conf zabbix-sql-scripts zabbix-agent2
```

Для TimescaleDB (рекомендуется на больших инсталляциях см. **[Обзор TimescaleDB](../Databases/timescaledb.md)**) установите пакет `timescaledb-2-postgresql-<версия-PG>` из официального репозитория Timescale.

#### 3. Инициализация базы данных и импорт схемы

```bash
sudo -u postgres psql -c "CREATE USER zabbix WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE zabbix OWNER zabbix;"
```

Импорт начальной схемы:
```bash
sudo zcat /usr/share/zabbix-sql-scripts/postgresql/server.sql.gz | sudo -u zabbix psql zabbix
```

#### 4. Конфигурация сервера и SELinux

В файле `/etc/zabbix/zabbix_server.conf` укажите пароль:
`DBPassword=your_password`

В RHEL-системах важно настроить SELinux:

```bash
# Разрешить серверу слушать сетевые порты
sudo setsebool -P zabbix_can_network 1
# Открыть порты в firewall (основной порт Zabbix Server — 10051)
sudo firewall-cmd --permanent --add-port=10051/tcp
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --reload
```

#### 5. Настройка Nginx и запуск

```bash
sudo systemctl restart zabbix-server zabbix-agent2 nginx php-fpm
sudo systemctl enable zabbix-server zabbix-agent2 nginx php-fpm
```

Дальнейшая настройка через веб-интерфейс идентична описанной выше (раздел Ubuntu).

---

### Установка Zabbix Agent 2 на отдельный хост (monitored host)

Установка агента на целевые серверы — базовый сценарий мониторинга. Агент не требует сервера и Frontend, достаточно пакетов самого агента.

#### Ubuntu / Debian

```bash
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest+ubuntu24.04_all.deb
sudo dpkg -i zabbix-release_latest+ubuntu24.04_all.deb
sudo apt update
sudo apt install -y zabbix-agent2
```

#### RHEL / Rocky / AlmaLinux

```bash
sudo rpm -Uvh https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/zabbix-release-7.0-5.el9.noarch.rpm
sudo dnf install -y zabbix-agent2
```

#### Настройка агента

Основной конфигурационный файл — `/etc/zabbix/zabbix_agent2.conf`. Минимальные обязательные параметры для связи с сервером (или прокси):

```ini
Server=192.168.1.100          # IP Zabbix Server или Proxy для пассивных проверок (Pull)
ServerActive=192.168.1.100    # IP Zabbix Server или Proxy для активных проверок (Push)
Hostname=имя_хоста           # Должно совпадать с именем хоста в веб-интерфейсе Zabbix
```

Запуск и автозагрузка:
```bash
sudo systemctl enable --now zabbix-agent2
sudo systemctl status zabbix-agent2
```

> Проверка работоспособности пассивного агента: `zabbix_get -s 127.0.0.1 -p 10050 -k agent.ping` (пакет `zabbix-get`). Активные проверки приходят на сервер обычно в течение 1-й минуты.

---

### Развертывание через Docker Compose

Быстрый способ запуска всего стека в изолированных контейнерах. Конфигурация использует кворк Compose для **Zabbix 7.0 LTS** и PostgreSQL 16.

> **Примечание:** в Docker Compose v2 поле `version:` является устаревшим и может быть опущено. Теги образов вида `7.0-ubuntu-latest` обновляются по мере выхода патчей (на август 2026 — `7.0.29`).

```yaml
services:
  zabbix-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: zabbix
      POSTGRES_PASSWORD: zabbix_password
      POSTGRES_DB: zabbix
    volumes:
      - ./zbx_db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U zabbix"]
      interval: 10s
      timeout: 5s
      retries: 5

  zabbix-server:
    image: zabbix/zabbix-server-pgsql:7.0-ubuntu-latest
    ports:
      - "10051:10051"
    environment:
      DB_SERVER_HOST: zabbix-db
      POSTGRES_USER: zabbix
      POSTGRES_PASSWORD: zabbix_password
      ZBX_ENABLE_SNMP_TRAPS: "true"
      # Имя хоста сервера для корректной работы Java Gateway
      ZBX_HOSTNAME: zabbix-server
      ZBX_JAVAGATEWAY: zabbix-java-gateway
    depends_on:
      zabbix-db:
        condition: service_healthy

  zabbix-web:
    image: zabbix/zabbix-web-nginx-pgsql:7.0-ubuntu-latest
    ports:
      - "8080:8080"
    environment:
      ZBX_SERVER_HOST: zabbix-server
      DB_SERVER_HOST: zabbix-db
      POSTGRES_USER: zabbix
      POSTGRES_PASSWORD: zabbix_password
      ZBX_SERVER_NAME: Zabbix Docker
    depends_on:
      zabbix-server:
        condition: service_started

  zabbix-java-gateway:
    image: zabbix/zabbix-java-gateway:7.0-ubuntu-latest
    ports:
      - "10052:10052"

  zabbix-agent:
    image: zabbix/zabbix-agent2:7.0-ubuntu-latest
    environment:
      ZBX_HOSTNAME: "zabbix-agent"
      ZBX_SERVER_HOST: zabbix-server
      ZBX_ACTIVESERVERS: zabbix-server
    depends_on:
      zabbix-server:
        condition: service_started
```

> Java Gateway (порт `10052`) обязателен при мониторинге Java-приложений (JMX), однако его запуск не является строго необходимым для базового мониторинга и его можно удалить из файла.

---

### Установка и настройка Zabbix Proxy

Используется для мониторинга удаленных локаций и распределения нагрузки.

#### 1. Установка (с использованием SQLite3)

SQLite3 рекомендуется для небольших прокси, так как не требует настройки полноценной СУБД.
```bash
sudo apt install -y zabbix-proxy-sqlite3 zabbix-sql-scripts
```

#### 2. Выбор бэкенда прокси

Прокси может хранить конфигурацию и буфер в одной из трех СУБД:

*   **SQLite3** — рекомендуется для небольших и средних прокси, не требует отдельной СУБД (пакет `zabbix-proxy-sqlite3`).
*   **PostgreSQL / MySQL** — для высоконагруженных прокси и больших объемов истории (пакеты `zabbix-proxy-pgsql` / `zabbix-proxy-mysql`), при этом прокси используется собственная БД, а не база основного сервера.
*   **Memory Buffer (in-memory)** — с версии 7.0 прокси может работать вообще без локальной СУБД, храня буфер в памяти (параметр `ProxyMode=0` + `DBName=` без указания пути). Подробнее в **[Определения и основные концепции](./definitions_and_concepts.md#распределенный-мониторинг-proxy)**.

#### 3. Настройка (`/etc/zabbix/zabbix_proxy.conf`)

Для прокси на SQLite:

```ini
Server=192.168.1.100  # IP основного Zabbix Server
Hostname=Branch-Proxy # Должно совпадать с именем в веб-интерфейсе
DBName=/var/lib/zabbix/zabbix_proxy.db
```

Для прокси на PostgreSQL (пакет `zabbix-proxy-pgsql`) дополнительно указывается адрес СУБД:

```ini
Server=192.168.1.100
Hostname=Branch-Proxy
DBName=zabbix_proxy
DBUser=zabbix
DBPassword=secret
DBHost=127.0.0.1
```

Запуск и регистрация:

```bash
sudo systemctl enable --now zabbix-proxy
# → Результат: прокси регистрируется на сервере и появляется в конфигурации Frontend
```

#### 4. Proxy Groups (с версии 7.0)

Прокси можно объединять в группы для обеспечения **отказоустойчивости и балансировки нагрузки**: если один прокси в группе недоступен, его хосты автоматически переключаются на другой доступный прокси группы. Добавление в группу не требует настройки на стороне самого прокси — группа настраивается только в веб-интерфейсе (`Administration → Proxies → Create proxy group`).

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

Zabbix 6.0+ поддерживает нативный режим HA для сервера. Кластер автоматически выбирает активную ноду (Active), остальные находятся в состоянии Standby и без ручного вмешательства принимают нагрузку при сбое активной.

1.  Установите несколько узлов Zabbix Server, подключенных к **одной общей БД** (PostgreSQL/MySQL). Все узлы должны иметь одинаковую версию Zabbix и конфигурацию.
2.  В `zabbix_server.conf` каждого узла укажите уникальное имя узла в параметре `HANodeName` и, при необходимости, адрес обмена `HANodeAddress` (по умолчанию узлы автоматически обмениваются адресами).
3.  При развертывании нескольких узлов Frontend их необходимо проксировать через внешний балансировщик (Nginx/HAProxy), так как автоматического failover для Frontend нет.
4.  Серверы автоматически создадут кластер. Статус можно проверить командой:
    `zabbix_server -R ha_status`

Пример вывода:
```
# → Output: 1 active and 1 standby nodes (or similar), leading node: node-1, 192.168.1.100:10051
```

**Требования HA:**
*   Единая БД — все узлы читают/пишут в одну СУБД (репликация БД для HA отключена/нежелательна).
*   Синхронность времени узлов (NTP).
*   Для полноценной отказоустойчивости самого Frontend использовать внешний балансировщик нагрузки.

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

Концептуальное описание механизма: **[Обнаружение хостов](./definitions_and_concepts.md#автоматизация-масштабирования)**.

---

### Отправка данных через zabbix_sender

Используется для передачи метрик в trapper-элементы:

```bash
zabbix_sender -z <server_ip> -s <hostname> -k <item_key> -o <value>
# → Response from "192.168.1.100:10051": "processed: 1; failed: 0; total: 1; seconds spent: 0.000045"
```

---

## Дополнительная информация

### Жизненный цикл версий (на август 2026)

Данные сверены с официальной [политикой жизненного цикла Zabbix](https://www.zabbix.com/life_cycle_and_release_policy) и [endoflife.date](https://endoflife.date/zabbix). LTS-версии поддерживаются 5 лет: 3 года полной поддержки + 2 года ограниченной (критические исправления).

| Версия | Статус | Дата выпуска | Конец поддержки (Full) | Конец поддержки (Limited) |
| :--- | :--- | :--- | :--- | :--- |
| **Zabbix 8.0** | **LTS (анонс)** | Q3 2026 (сентябрь 2026) | Q3 2029 | Q3 2031 |
| **Zabbix 7.0** | **LTS (текущая, до 7.0.29)** | 4 июня 2024 | **30 июня 2027** | **30 июня 2029** |
| Zabbix 7.4 | Standard | 30 июня 2025 | 30 сентября 2026 (до выхода 8.0) | 30 сентября 2026 |
| Zabbix 7.2 | Standard (EOL) | 10 декабря 2024 | 30 июня 2025 | 31 декабря 2025 |

> **Рекомендация:** для производственных сред использовать Zabbix 7.0 LTS. Версия 7.4 завершает поддержку в сентябре 2026 — миграция обязательна до этой даты. После выхода Zabbix 8.0 LTS (Q3 2026) следует планировать переход на новую LTS-ветку.

### См. также

* **[Мониторинг СУБД](./zabbix_database_monitoring.md)** — общие подходы к мониторингу баз данных.
* **[Мониторинг PostgreSQL](./zabbix_postgresql_monitoring.md)** — настройка мониторинга через Zabbix Agent 2.
* **[Тюнинг производительности](./zabbix_troubleshooting_and_performance_tuning.md)** — оптимизация Zabbix и БД.
* **[Лучшие практики](./zabbix_best_practices.md)** — рекомендации по настройке триггеров.
