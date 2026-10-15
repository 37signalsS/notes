# Zabbix — установка и настройка

> Данная заметка описывает развёртывание Zabbix Server, Proxy и Agent 2 в production-среде.
> Сведения актуальны для **Zabbix 7.4** (текущая стандартная ветка) и **Zabbix 7.0 LTS** (основная долгосрочная ветка).
> **Zabbix 8.0 LTS** на момент сверки не выпущен: доступен кандидат в релиз **8.0.0rc1 (1 октября 2026)**, выпуск GA запланирован на Q4 2026 (по roadmap — ноябрь 2026). Команды и параметры, специфичные для 8.0, отмечены по тексту явно и приведены по предрелизным данным.

---

## Определения

* **Zabbix Server** — центральный процесс мониторинга, принимающий данные от агентов, прокси и внешних систем; выполняет вычисление триггеров и хранение метрик.
* **Zabbix Agent 2** — современный агент сбора метрик на целевом хосте; написан на Go, поддерживает многопоточность и загружаемые плагины (PostgreSQL, MySQL и др.).
* **Zabbix Proxy** — промежуточный компонент для распределённого сбора данных (удалённые локации, сегменты сети); позволяет снизить нагрузку на основной сервер.
* **Zabbix Trapper** — элемент данных типа `Trapper`, принимающий значения по модели Push (через `zabbix_sender` или JSON-RPC API).
* **NVPS (New Values Per Second)** — количество новых значений, записываемых в базу данных за секунду; ключевой метрический показатель производительности мониторинга.
* **Очередь (Zabbix Queue)** — список элементов данных, чей опрос запаздывает относительно запланированного интервала; индикатор нехватки процессов сбора.

---

## Основные концепции

### Архитектура серверного стека

Для функционирования Zabbix Server необходимы следующие компоненты:

* **Операционная система:** Linux (Ubuntu 24.04/26.04 LTS, RHEL 9/10, Rocky Linux 9/10, AlmaLinux 9/10)
* **СУБД:** PostgreSQL (рекомендуется с TimescaleDB) или MySQL/MariaDB
* **Веб-сервер:** Nginx или Apache (для работы веб-интерфейса)
* **PHP:** серверный язык программирования (Zabbix 8.0 — **8.2.0–8.5.X**, минимум поднят с 8.0 до 8.2; Zabbix 7.4 — **8.0.0–8.5.X**; Zabbix 7.0 — **8.0.0–8.5.X**)
* **Zabbix Frontend:** графический интерфейс управления

### Выбор компонентов и SRE-перспектива

При выборе конфигурации SRE учитывают следующие аспекты:

* **Нагрузка на NVPS:** основной фактор выбора СУБД и конфигурации кэшей. PostgreSQL + TimescaleDB — стандарт для высоконагруженных систем (>5000 NVPS).
* **Сетевые сегменты:** для удалённых локаций используется Zabbix Proxy, снижающий нагрузку на WAN-каналы.
* **Горизонтальное масштабирование:** Zabbix Server поддерживает нативный HA-режим (с версии 6.0), а Proxy Groups (с версии 7.0) обеспечивают отказоустойчивость и балансировку на уровне прокси.
* **Снижение стоимости:** использование Zabbix Agent 2 с плагинами позволяет исключить установку дополнительных утилит (ODBC, SNMP-трапы) на целевом хосте.

### Версионная матрица (на октябрь 2026)

| Версия | Статус | Дата выпуска | Конец поддержки (Full) | Конец поддержки (Limited) |
| :--- | :--- | :--- | :--- | :--- |
| **Zabbix 8.0** | LTS (запланирована) | Q4 2026 | Q4 2029 | Q4 2031 |
| **Zabbix 7.4** | Standard (текущая) | 30 июня 2025 | до выхода 8.0 LTS | Q1 2027 |
| **Zabbix 7.0** | LTS | 4 июня 2024 | 30 июня 2027 | 30 июня 2029 |
| Zabbix 7.2 | Standard (EOL) | 10 декабря 2024 | 30 июня 2025 | 31 декабря 2025 |

> **Рекомендация:** для новых инсталляций использовать Zabbix 7.4 (текущая стандартная ветка). **Zabbix 8.0 LTS** ожидается в Q4 2026 — после выхода финальной версии миграция станет приоритетной.

---

## Практические сценарии

### Сценарий 1. Установка Zabbix Server на Ubuntu 24.04/26.04 (PostgreSQL + TimescaleDB)

Данная конфигурация является стандартом для высоконагруженных систем. Подробности технологии: **[Обзор TimescaleDB](../Databases/timescaledb.md)**.

#### 1. Предпосылки

* **Жёсткий диск:** не менее 20 ГБ свободного места (10 ГБ под ОС, 10 ГБ под БД и логи)
* **Память:** не менее 4 ГБ RAM (8 ГБ для >5000 NVPS)
* **Процессор:** 2 ядра (4 ядра для >10 000 хостов)
* **Сеть:** порт 80/443 (Frontend), 10050 (Agent), 10051 (Server/Proxy), 10052 (Java Gateway), 10053 (Web Service)

#### 2. Добавление официального репозитория

```bash
wget https://repo.zabbix.com/zabbix/8.0/release/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest+ubuntu24.04_all.deb
sudo dpkg -i zabbix-release_latest+ubuntu24.04_all.deb
sudo apt update
```

Для Zabbix 7.0 замените `8.0` на `7.0` в URL.

Для Ubuntu 26.04 используйте `zabbix-release_latest+ubuntu26.04_all.deb`.

#### 3. Установка PostgreSQL и TimescaleDB

```bash
sudo apt install -y postgresql postgresql-contrib timescaledb-2-postgresql-16
# Оптимизация PostgreSQL под TimescaleDB
sudo timescaledb-tune --quiet --yes
sudo systemctl restart postgresql
```

#### 4. Установка пакетов Zabbix

```bash
sudo apt install -y zabbix-server-pgsql zabbix-frontend-php zabbix-nginx-conf zabbix-sql-scripts zabbix-agent2
```

Для Zabbix 7.0 также установите `zabbix-agent2-plugin-postgresql` для мониторинга СУБД через плагин.

#### 5. Инициализация базы данных

```bash
sudo -u postgres psql -c "CREATE USER zabbix WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE zabbix OWNER zabbix;"
# Активация TimescaleDB
sudo -u postgres psql -d zabbix -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

#### 6. Импорт начальной схемы и активация гипертаблиц

Сценарий рассчитан на **Zabbix 8.0**, где каталог SQL-скриптов — `/usr/share/zabbix/sql-scripts/`:

```bash
zcat /usr/share/zabbix/sql-scripts/postgresql/server.sql.gz | sudo -u zabbix psql zabbix
cat /usr/share/zabbix/sql-scripts/postgresql/timescaledb/schema.sql | sudo -u zabbix psql zabbix
```

Для **Zabbix 7.0/7.4** каталог — `/usr/share/zabbix-sql-scripts/`:

```bash
zcat /usr/share/zabbix-sql-scripts/postgresql/server.sql.gz | sudo -u zabbix psql zabbix
cat /usr/share/zabbix-sql-scripts/postgresql/timescaledb/schema.sql | sudo -u zabbix psql zabbix
```

> Скрипт `postgresql/timescaledb.sql` переименован в `postgresql/timescaledb/schema.sql` начиная с Zabbix 7.0.0.

#### 7. Конфигурация Zabbix Server

В файле `/etc/zabbix/zabbix_server.conf` укажите пароль:

```ini
DBPassword=your_password
```

Минимальные обязательные параметры для SRE:

```ini
# Стартовые значения для 2000+ хостов (отрегулируйте по нагрузке)
CacheSize=128M
HistoryCacheSize=256M
ValueCacheSize=64M
StartDBSyncers=4
```

#### 8. Настройка Nginx и PHP

В файле `/etc/zabbix/nginx.conf` раскомментируйте директивы `listen` и `server_name`.

Перезапустите сервисы:

```bash
sudo systemctl restart zabbix-server zabbix-agent2 nginx php8.3-fpm
sudo systemctl enable zabbix-server zabbix-agent2 nginx php8.3-fpm
```

> Имя сервиса PHP-FPM зависит от версии PHP в дистрибутиве: Ubuntu 24.04 поставляет PHP 8.3 (`php8.3-fpm`), Ubuntu 26.04 — PHP 8.5 (`php8.5-fpm`). Zabbix 8.0 требует PHP 8.2.0–8.5.X.

#### 9. Завершение настройки через веб-интерфейс

Перейдите по адресу `http://<IP_сервера>` и выполните шаги мастера установки:

1. **Проверка предпосылок:** мастер проверяет готовность PHP, СУБД и прав на файлы.
2. **Подключение к базе данных:** укажите тип, адрес (`localhost`), порт, базу (`zabbix`), пользователя (`zabbix`) и пароль.
3. **Сведения о сервере:** укажите hostname и порт.
4. **Сводка и установка:** нажмите **Install** и дождитесь завершения.
5. **Вход:** по умолчанию логин `Admin`, пароль `zabbix`. **Обязательно** смените пароль сразу после первого входа.

#### 10. Проверка установки

```bash
# Сервер запущен и находится в состоянии running
sudo systemctl status zabbix-server
# → Active: active (running)

# В логе нет ошибок, upgrade схемы БД завершён
sudo grep -E "Starting Zabbix Server|database upgrade" /var/log/zabbix/zabbix_server.log
# → ... Starting Zabbix Server. Zabbix 8.0.x ...
# → ... database upgrade fully completed ...

# Схема импортирована: список таблиц в схеме public не пуст
sudo -u zabbix psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" zabbix
# → ненулевое число таблиц
```

#### Альтернатива: MySQL / MariaDB вместо PostgreSQL

Zabbix 8.0 поддерживает MySQL 8.4.0–9.7.X (движок InnoDB обязателен). Вместо пакетов PostgreSQL устанавливается `zabbix-server-mysql`, а схема импортируется из каталога `mysql/`:

```bash
sudo apt install -y zabbix-server-mysql zabbix-frontend-php zabbix-nginx-conf zabbix-sql-scripts zabbix-agent2

# Для импорта функций требуется разрешить создание функций
sudo mysql -e "SET GLOBAL log_bin_trust_function_creators = 1;"
sudo -u zabbix mysql -e "CREATE DATABASE zabbix CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;"
zcat /usr/share/zabbix/sql-scripts/mysql/server.sql.gz | sudo -u zabbix mysql --default-character-set=utf8mb4 zabbix
sudo mysql -e "SET GLOBAL log_bin_trust_function_creators = 0;"
```

> Для MySQL/MariaDB настоятельно рекомендуется кодировка `utf8mb4` с коллацией `utf8mb4_bin`. TimescaleDB — расширение PostgreSQL, с MySQL он не используется. В `zabbix_server.conf` при этом задаётся `DBPassword`, а тип БД выбирается на шаге подключения в веб-мастере.

---

### Сценарий 2. Установка Zabbix Server на RHEL / Rocky Linux / AlmaLinux 9/10

Конфигурация для dnf-based дистрибутивов семейства RHEL. Команды актуальны для **Zabbix 8.0 LTS** на RHEL 9/10 и его производных.

#### 1. Добавление официального репозитория

```bash
# Для RHEL 9
sudo rpm -Uvh https://repo.zabbix.com/zabbix/8.0/rhel/9/x86_64/zabbix-release-latest.el9.noarch.rpm
# Для RHEL 10
sudo rpm -Uvh https://repo.zabbix.com/zabbix/8.0/rhel/10/x86_64/zabbix-release-latest.el10.noarch.rpm
sudo dnf clean all
sudo dnf -y update
```

Для Zabbix 7.0 замените `8.0` на `7.0`.

#### 2. Установка PostgreSQL и пакетов Zabbix

```bash
sudo dnf install -y epel-release postgresql-server postgresql-server-devel
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
sudo dnf install -y zabbix-server-pgsql zabbix-web-pgsql zabbix-nginx-conf zabbix-sql-scripts zabbix-agent2
```

Для TimescaleDB установите пакет `timescaledb-2-postgresql-<версия-PG>` из официального репозитория Timescale.

#### 3. Инициализация базы данных и импорт схемы

```bash
sudo -u postgres psql -c "CREATE USER zabbix WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE zabbix OWNER zabbix;"
sudo zcat /usr/share/zabbix/sql-scripts/postgresql/server.sql.gz | sudo -u zabbix psql zabbix
```

#### 4. Конфигурация сервера и SELinux

В файле `/etc/zabbix/zabbix_server.conf` укажите пароль:

```ini
DBPassword=your_password
```

В RHEL-системах важно настроить SELinux:

```bash
# Разрешить серверу слушать сетевые порты
sudo setsebool -P httpd_can_connect_zabbix on
sudo setsebool -P httpd_can_network_connect_db on
# Открыть порты в firewall
sudo firewall-cmd --permanent --add-port=10051/tcp
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --permanent --add-port=443/tcp
sudo firewall-cmd --reload
```

#### 5. Настройка Nginx и запуск

```bash
sudo systemctl restart zabbix-server zabbix-agent2 nginx php-fpm
sudo systemctl enable zabbix-server zabbix-agent2 nginx php-fpm
```

Дальнейшая настройка через веб-интерфейс идентична описанной выше (раздел Ubuntu).

---

### Сценарий 3. Установка Zabbix Agent 2 на отдельный хост (monitored host)

Установка агента на целевые серверы — базовый сценарий мониторинга. Агент не требует сервера и Frontend, достаточно пакетов самого агента.

#### Ubuntu / Debian

```bash
wget https://repo.zabbix.com/zabbix/8.0/release/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest+ubuntu24.04_all.deb
sudo dpkg -i zabbix-release_latest+ubuntu24.04_all.deb
sudo apt update
sudo apt install -y zabbix-agent2
```

Для Zabbix 7.0 замените `8.0` на `7.0`.

#### RHEL / Rocky / AlmaLinux

```bash
# Для RHEL 9
sudo rpm -Uvh https://repo.zabbix.com/zabbix/8.0/rhel/9/x86_64/zabbix-release-latest.el9.noarch.rpm
# Для RHEL 10
sudo rpm -Uvh https://repo.zabbix.com/zabbix/8.0/rhel/10/x86_64/zabbix-release-latest.el10.noarch.rpm
sudo dnf install -y zabbix-agent2
```

Для Zabbix 7.0 замените `8.0` на `7.0`.

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

### Сценарий 4. Развертывание Zabbix Proxy с SQLite3

Прокси используется для мониторинга удалённых локаций и распределения нагрузки. SQLite3 рекомендуется для небольших прокси, так как не требует настройки полноценной СУБД.

#### 1. Установка

```bash
sudo apt install -y zabbix-proxy-sqlite3 zabbix-sql-scripts
```

Для RHEL-подобных систем:

```bash
sudo dnf install -y zabbix-proxy-sqlite3 zabbix-sql-scripts
```

#### 2. Выбор базы данных и режима буферизации прокси

Прокси **всегда** использует отдельную базу данных (SQLite3, MySQL или PostgreSQL) — параметр `DBName` обязателен. Встроенную in-memory БД (`:memory:`) использовать нельзя: многопроцессная архитектура прокси это не поддерживает.

* **SQLite3** — рекомендуется для небольших и средних прокси, не требует отдельной СУБД.
* **PostgreSQL / MySQL** — для высоконагруженных прокси и больших объёмов истории.

Независимо от выбранной СУБД, в Zabbix 7.0+ доступен **memory buffer** — буферизация истории, discovery-данных и autoregistration в оперативной памяти до отправки на сервер (параметр `ProxyBufferMode`):

* `disk` — данные хранятся в БД и оттуда выгружаются (значение по умолчанию для существующих установок);
* `memory` — данные хранятся в памяти; при нехватке памяти старые данные отбрасываются, при остановке буфер теряется;
* `hybrid` — в норме работает как `memory`, но при переполнении или превышении возраста данные сбрасываются в БД; при остановке буфер сбрасывается в БД. Применяется ко всем новым установкам с Zabbix 7.0.

Для режимов `memory`/`hybrid` обязателен параметр `ProxyMemoryBufferSize`; параметр `ProxyMemoryBufferAge` допустим только для `hybrid`. Подробнее: **[Определения и основные концепции](./definitions_and_concepts.md#распределенный-мониторинг-proxy)**.

#### 3. Настройка (`/etc/zabbix/zabbix_proxy.conf`)

Для прокси на SQLite:

```ini
Server=192.168.1.100  # IP основного Zabbix Server
Hostname=Branch-Proxy # Должно совпадать с именем в веб-интерфейсе
DBName=/var/lib/zabbix/zabbix_proxy.db
ProxyBufferMode=hybrid    # disk | memory | hybrid
ProxyMemoryBufferSize=16M # обязателен для memory/hybrid
```

> `ProxyMode` (не путать с `ProxyBufferMode`) задаёт режим работы прокси: `0` — активный, `1` — пассивный.

##### Активный и пассивный режим прокси

`ProxyMode` определяет, **кто инициирует соединение между прокси и сервером**:

| Режим | `ProxyMode` | Кто инициирует | Порт | Когда применять |
|---|---|---|---|---|
| Активный | `0` (по умолчанию) | Прокси → Server | исходящий на 10051 | Прокси за NAT/firewall, где сервер не может достучаться до прокси |
| Пассивный | `1` | Server → Proxy | входящий 10051 на прокси | Когда прокси доступен серверу напрямую |

В активном режиме прокси сам подключается к серверу, получает конфигурацию и отправляет данные. В пассивном — сервер обращается к прокси по `Proxy`/`Server`-адресу. Выбор режима задаётся при создании прокси в веб-интерфейсе (`Administration → Proxies`) и **должен совпадать** с `ProxyMode` в конфиге, иначе прокси не зарегистрируется.

> Не путайте три параметра: `ProxyMode` (активный/пассивный), `ProxyBufferMode` (`disk`/`memory`/`hybrid` — где буферизуются данные) и `Hostname` (имя прокси, совпадающее с именем в UI).

Для прокси на PostgreSQL дополнительно указывается адрес СУБД:

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

Прокси можно объединять в группы для обеспечения **отказоустойчивости и балансировки нагрузки**: если один прокси в группе недоступен, его хосты автоматически переключаются на другой доступный прокси. Добавление в группу не требует настройки на стороне самого прокси — группа настраивается только в веб-интерфейсе (`Administration → Proxies → Create proxy group`).

---

### Сценарий 5. Высокая доступность (High Availability)

Нативный режим HA для сервера доступен начиная с Zabbix 6.0. Кластер автоматически выбирает активную ноду (Active), остальные находятся в состоянии Standby и без ручного вмешательства принимают нагрузку при сбое активной.

1. Установите несколько узлов Zabbix Server, подключенных к **одной общей БД** (PostgreSQL/MySQL). Все узлы должны иметь одинаковую версию Zabbix и конфигурацию.
2. В `zabbix_server.conf` каждого узла укажите уникальное имя узла в параметре `HANodeName` и, при необходимости, адрес обмена `HANodeAddress` (по умолчанию узлы автоматически обмениваются адресами).
3. При развёртывании нескольких узлов Frontend их необходимо проксировать через внешний балансировщик (Nginx/HAProxy), так как автоматического failover для Frontend нет.
4. Серверы автоматически создадут кластер. Статус можно проверить командой:

```bash
zabbix_server -R ha_status
# → Output: 1 active and 1 standby nodes (or similar), leading node: node-1, 192.168.1.100:10051
```

**Требования HA:**

* Единая БД — все узлы читают/пишут в одну СУБД (репликация БД для HA отключена/нежелательна).
* Синхронность времени узлов (NTP).
* Для полноценной отказоустойчивости Frontend использовать внешний балансировщик нагрузки.

---

### Сценарий 6. Настройка безопасности и шифрования (PSK)

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

* **Connections to host:** PSK
* **Connections from host:** PSK
* **PSK identity:** PSK_001
* **PSK:** (содержимое сгенерированного файла)

---

## Операции и команды

### Основные команды управления сервисами

| Действие | Команда |
| :--- | :--- |
| Перезапуск сервера | `sudo systemctl restart zabbix-server` |
| Перезапуск агента | `sudo systemctl restart zabbix-agent2` |
| Перезапуск прокси | `sudo systemctl restart zabbix-proxy` |
| Статус сервера | `sudo systemctl status zabbix-server` |
| Автозагрузка сервера | `sudo systemctl enable zabbix-server` |
| Проверка конфигурации | `zabbix_server -R config_cache_reload` |

### Управление работающим сервером (Runtime Control)

| Команда | Описание |
| :--- | :--- |
| `zabbix_server -R config_cache_reload` | Принудительно обновить кэш конфигурации |
| `zabbix_server -R ha_status` | Вывести статус кластера HA |
| `zabbix_server -R log_level_increase='<тип>'` | Повысить уровень логирования для типа процесса |
| `zabbix_server -R log_level_decrease='<тип>'` | Понизить уровень логирования для типа процесса |
| `zabbix_server -R diaginfo=<секция>` | Собрать диагностику секции в лог |
| `zabbix_server -R housekeeper_execute` | Запустить Housekeeper вне расписания |
| `zabbix_server -R secrets_reload` | Перезагрузить секреты из Vault |
| `zabbix_server -R history_cache_clear=<target>` | Очистить кэш истории для элемента |

### Управление базой данных (PostgreSQL)

| Действие | Команда |
| :--- | :--- |
| Создание пользователя | `sudo -u postgres psql -c "CREATE USER zabbix WITH PASSWORD 'pass';"` |
| Создание базы | `sudo -u postgres psql -c "CREATE DATABASE zabbix OWNER zabbix;"` |
| Импорт схемы | `zcat /usr/share/zabbix/sql-scripts/postgresql/server.sql.gz \| sudo -u zabbix psql zabbix` |
| Активация TimescaleDB | `sudo -u postgres psql -d zabbix -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"` |
| Проверка таблиц | `sudo -u zabbix psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" zabbix` |

### Управление агентами

| Действие | Команда |
| :--- | :--- |
| Тест пассивного агента | `zabbix_get -s 127.0.0.1 -p 10050 -k agent.ping` |
| Тест элемента агента | `zabbix_agent2 -t system.uptime` |
| Отправка trapper-значения | `zabbix_sender -z <server> -s <hostname> -k <key> -o <value>` |

### Отправка данных через zabbix_sender

```bash
zabbix_sender -z 192.168.1.100 -s myserver -k system.cpu.load -o 2.5
# → Response from "192.168.1.100:10051": "processed: 1; failed: 0; total: 1; seconds spent: 0.000045"
```

---

## Устранение неисправностей

### Типичные проблемы при установке

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Zabbix server is running: No` | Ошибка в конфигурации, нет подключения к БД | Проверить `/etc/zabbix/zabbix_server.conf` и лог `/var/log/zabbix/zabbix_server.log` |
| `current database version` mismatch | Схема БД не импортирована или устарела | Переимпортировать `server.sql.gz` |
| Frontend недоступен | Nginx не запущен или неправильный `server_name` | Проверить `systemctl status nginx` и `/etc/zabbix/nginx.conf` |
| Агент не соединяется с сервером | Неправильный `Server=` или брандмауэр | Проверить `/etc/zabbix/zabbix_agent2.conf` и порт 10051 |
| `Queue` растёт | Нехватка поллеров | Увеличить `StartPollers` и `StartAgentPollers` |
| `Gaps` на графиках | Переполнение History Cache | Увеличить `HistoryCacheSize`, проверить IOPS БД |

### Диагностика через логи

* **Zabbix Server:** `/var/log/zabbix/zabbix_server.log`
* **Zabbix Proxy:** `/var/log/zabbix/zabbix_proxy.log`
* **Zabbix Agent:** `/var/log/zabbix/zabbix_agent2.log`
* **Nginx:** `/var/log/nginx/error.log`
* **PHP-FPM:** `/var/log/php8.3-fpm.log` (путь зависит от версии PHP, например `php8.5-fpm.log` на Ubuntu 26.04)

### Диагностика через внутренние метрики

Внутренние метрики сервера (очередь, NVPS, утилизация кэшей) отображаются в веб-интерфейсе: **Reports → System information** (в том числе «Required server performance, new values per second»), а также через self-monitoring хоста самого сервера в **Monitoring → Latest data**.

Для удалённого опроса внутренних метрик другого экземпляра Zabbix служат элементы `zabbix[stats,<ip>,<port>]` (прямой опрос) и `zabbix.stats[<ip>,<port>]` (через агент). Такой запрос принимается только от адресов, перечисленных в параметре `StatsAllowedIP` на целевом экземпляре (по умолчанию `127.0.0.1`). Удалённая очередь: `zabbix[stats,<ip>,<port>,queue,<from>,<to>]`.

```bash
# Проверка пассивного агента
zabbix_get -s 127.0.0.1 -p 10050 -k agent.ping
# → 1

# Очередь: элементы, отставшие минимум на 10 минут (zabbix[queue,<from>,<to>], from по умолчанию 6s)
zabbix_get -s 127.0.0.1 -p 10051 -k "zabbix[queue,10m]"
# → целое число (количество отставших элементов)

# Требуемая производительность сервера, новых значений/сек (NVPS)
zabbix_get -s 127.0.0.1 -p 10051 -k "zabbix[requiredperformance]"
# → число с плавающей точкой

# Статус HA-кластера (результат записывается в лог сервера)
zabbix_server -R ha_status
```

### Устранение проблем с PostgreSQL

* **Аутентификация scram-sha-256:** на RHEL-подобных системах по умолчанию используется `ident`; измените на `scram-sha-256` или `md5` в `pg_hba.conf`.
* **Оптимизация соединений:** при большом числе History Syncers используйте PgBouncer для пула соединений.
* **Сжатие TimescaleDB:** включите компрессию данных старше 7 дней для снижения IOPS.

---

## Лучшие практики

### Production-checklist SRE/Sysadmin

1. **Бэкапы:**
   * Бэкап БД (pg_dump / pg_basebackup) — ежедневно, хранить 7–30 дней.
   * Бэкап `/etc/zabbix/` — после каждого изменения конфигурации.
   * Тест восстановления бэкапа — ежемесячно.
2. **Безопасность:**
   * Использовать PSK или сертификаты TLS для шифрования трафика.
   * Запретить прямой доступ к порту 10051 из интернета.
   * Сменить пароль Admin после установки.
3. **Производительность:**
   * Начинать с значений по умолчанию для кэшей и увеличивать только при стабильной утилизации >80%.
   * Использовать TimescaleDB компрессию для систем с >10000 хостов.
   * Асинхронные pollers (Zabbix 7.0+) — использовать для Agent/HTTP/SNMP.
4. **Апрувы:**
   * Изменения конфигурации Zabbix Server/Proxy в production через change-management процесс.
   * Версионный контроль `/etc/zabbix/` через Git.
5. **Мониторинг мониторинга:**
   * Подключить `Template App Zabbix Server` к самому серверу для отслеживания очередей, NVPS и кэшей.
   * Подключить `Template App Zabbix Proxy` к каждому прокси.

### Рекомендации по именованию

* **Hostnames:** использовать FQDN (например, `zbx-srv-01.example.com`).
* **Пароли:** использовать сложные пароли, хранить в Vault (HashiCorp Vault или аналогичные системы).
* **Макросы:** использовать префиксы для изоляции переменных (например, `{$MYSQL.PORT}` вместо `{$PORT}`).

### Удаление и очистка

```bash
# Остановить и отключить сервисы
sudo systemctl disable --now zabbix-server zabbix-agent2 zabbix-proxy nginx php8.3-fpm

# Удалить пакеты и репозиторий (Debian/Ubuntu)
sudo apt purge -y zabbix-server-pgsql zabbix-frontend-php zabbix-nginx-conf zabbix-sql-scripts zabbix-agent2 zabbix-release
sudo apt autoremove -y

# Удалить конфигурацию, логи и данные
sudo rm -rf /etc/zabbix /var/log/zabbix /var/lib/zabbix /usr/share/zabbix

# Удалить базу данных и пользователя
sudo -u postgres psql -c "DROP DATABASE zabbix;"
sudo -u postgres psql -c "DROP USER zabbix;"
```

> На RHEL-подобных системах пакеты удаляются через `dnf remove` (пакет репозитория — `zabbix-release.noarch`). Данные из `/var/lib/zabbix` и база данных удаляются безвозвратно — убедитесь, что есть актуальный бэкап.

---

## Дополнительная информация

### Миграция с Zabbix 7.0 LTS на Zabbix 8.0 LTS

1. **Остановка сервисов:**

   ```bash
   sudo systemctl stop zabbix-server zabbix-agent2 zabbix-proxy
   ```

2. **Бэкап БД и конфигурации:**

   ```bash
   mkdir /opt/zabbix-backup/
   cp /etc/zabbix/zabbix_server.conf /opt/zabbix-backup/
   cp -R /usr/share/zabbix/ /opt/zabbix-backup/
   ```

3. **Обновление репозитория:**

   ```bash
   # Ubuntu
   wget https://repo.zabbix.com/zabbix/8.0/release/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest+ubuntu24.04_all.deb
   sudo dpkg -i zabbix-release_latest+ubuntu24.04_all.deb
   # RHEL
   sudo rpm -Uvh https://repo.zabbix.com/zabbix/8.0/rhel/9/x86_64/zabbix-release-latest.el9.noarch.rpm
   ```

4. **Обновление пакетов:**

   ```bash
   # Ubuntu
   sudo apt update && sudo apt install -y zabbix-server-pgsql zabbix-agent2
   # RHEL
   sudo dnf install -y zabbix-server-pgsql zabbix-agent2
   ```

5. **Миграция БД:** запустить скрипты миграции согласно [заметам о миграции Zabbix](https://www.zabbix.com/documentation/8.0/en/manual/installation/upgrade).

### См. также

* **[Определения и основные концепции](./definitions_and_concepts.md)** — описание базовых компонентов и моделей сбора данных.
* **[Внутреннее устройство и процессы](./additional_info.md)** — архитектурное описание демонов и параметры конфигурации.
* **[Прокси и распределённый мониторинг](./zabbix_proxy.md)** — настройка proxy, ProxyGroups и HA.
* **[Обновление и резервное копирование](./zabbix_upgrade_and_backup.md)** — апгрейд major-версий, миграция БД, backup/restore.
* **[Плагины Zabbix Agent 2](./zabbix_agent_plugins.md)** — встроенные и загружаемые плагины агента.
* **[Режимы работы агентов и авторегистрация](./zabbix_agent_checks.md)** — активные/пассивные проверки, буфер, массовый онбординг.
* **[Аутентификация и права](./zabbix_authentication_and_rbac.md)** — LDAP/SAML/MFA, роли, API-токены, синхронизация с шифрованием.
* **[API и автоматизация](./zabbix_api_automation.md)** — Monitoring as Code, экспорт/импорт конфигурации.
* **[Мониторинг PostgreSQL](./zabbix_postgresql_monitoring.md)** — настройка мониторинга СУБД через Zabbix Agent 2.
* **[Лучшие практики настройки](./zabbix_best_practices.md)** — рекомендации по триггерам, шаблонам и оповещениям.
* **[Тюнинг и производительность](./zabbix_troubleshooting_and_performance_tuning.md)** — анализ узких мест, работа с кэшами и масштабирование воркеров.
