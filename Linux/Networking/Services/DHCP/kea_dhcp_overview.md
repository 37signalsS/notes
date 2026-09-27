# Kea DHCP: Архитектура и настройка

---

## Определения

**Kea DHCP** — современная высокопроизводительная реализация DHCP-сервера, разработанная ISC как замена устаревшего ISC DHCP. Поддерживает DHCPv4 (`kea-dhcp4`), DHCPv6 (`kea-dhcp6`) и DHCPv4-over-DHCPv6 (`kea-dhcp4` в режиме 4o6).

**Control Agent (CA)** — отдельный HTTP(S)-демон, предоставляющий REST API для управления всеми компонентами Kea в реальном времени. Является тонкимproxy-слоем: клиенты отправляют команды CA, а CA транслирует их во внутренний канал управления соответствующего демона. Поддерживает базовую аутентификацию и TLS.

**Hook-библиотеки (Hooks)** — плагины, расширяющие функционал Kea. Загружаются в адресное пространство демона и имеют доступ к внутренним структурам данных (leases, subnet, client classification). Подключаются через массив `"hooks-libraries"` в конфигурации. Критически важны для production: без `libdhcp_mysql.so`/`libdhcp_postgresql.so` невозможен глобальный HA.

**kea-lfc (Lease File Cleanup)** — фоновая утилита для периодической компактификации и очистки файла аренд (memfile). Устраняет фрагментацию и «просадки» производительности при росте файла аренд. Запускается автоматически по `lfc-interval` или вручную.

**kea-admin** — CLI-утилита для административных операций: инициализация схемы БД, миграция leases, экспорт/импорт статистики. Работает через контрольный канал с локальным CA.

**kea-dhcp6** — демон DHCPv6. Использует те же hooks-библиотеки и БД, что и `kea-dhcp4`, но с отдельной конфигурацией (`kea-dhcp6.conf`). Использует DUID/IAID вместо MAC-адресов.

**kea-dhcp-ddns** — отдельный демон динамического обновления DNS. В отличие от ISC DHCP (встроенный DDNS), Kea вынес его в отдельный процесс для масштабирования. Поддерживает RFC 2136 (TSIG/GSS-TSIG).

**DHCPv4-over-DHCPv6 (4o6)** — механизм туннелизации DHCPv4-запросов через DHCPv6-канал (RFC 3411). Позволяет использовать единую инфраструктуру ретрансляции для обеих версий протокола. В Kea поддерживается через hook `libdhcp_4o6.so`.

---

## Основные концепции

### Архитектура Kea vs ISC DHCP

| Параметр | ISC DHCP (`dhcpd`) | Kea DHCP (`kea-dhcp4`) |
| :--- | :--- | :--- |
| **Потоки** | Однопоточный | Многопоточный |
| **Хранение lease** | Текстовый файл (`dhcpd.leases`) | memfile (JSON), **MySQL**, **PostgreSQL**, **Cassandra** |
| **Управление** | OMAPI (устарел) | **REST API** (JSON/HTTP) |
| **Конфигурация** | Иерархический текст (`dhcpd.conf`) | JSON (`kea-dhcp4.conf`) |
| **Расширяемость** | Вшитый функционал | Hook-библиотеки (плагины) |
| **Логирование** | syslog | syslog + structured logging (DEBUG 0-99) |
| **Мониторинг** | Внешние скрипты/exporter | Нативный REST API + Prometheus endpoint |
| **Failover** | ISC-проприетарный (TCP 647) | Глобальный HA (MySQL backend) или load-balancing |
| **Обновление leases** | fsync на каждый ACK | Batch-запись (произвольный интервал) |

### Архитектура Kea: Демоны и взаимодействие

Kea имеет **модульную postfix-подобную архитектуру**: каждый компонент — отдельный демон, взаимодействующий через внутренний канал управления и общую базу данных аренд. Это позволяет горизонтально масштабировать отдельные функции (например, DDNS отдельно от DHCPv4).

| Демон | Назначение | Порт/Транспорт |
| :--- | :--- | :--- |
| `kea-dhcp4` | DHCPv4-сервер (обработка Discover/Offer/Request/ACK) | UDP 67/68 (raw sockets) |
| `kea-dhcp6` | DHCPv6-сервер (Solicit/Advertise/Request/Reply) | UDP 546/547 |
| `kea-ctrl-agent` | REST API-шлюз (JSON/HTTP) для управления | TCP 8000 (по умолчанию) |
| `kea-dhcp-ddns` | Динамическое обновление DNS (DDNS) | Внутренний канал с DNS-сервером |
| `kea-lfc` | Фоновая очистка и компактификация lease-файла | Нет (запускается по расписанию) |
| `kea-netconf` | NETCONF-агент для управления конфигурацией (опционально) | TCP 830 (NETCONF) |
| `kea-admin` | CLI-утилита для администрирования (миграция leases, schema init) | Локальный Unix socket / TCP |

**Принцип работы:**
1. Демоны DHPC (`kea-dhcp4`/`kea-dhcp6`) получают пакеты от клиентов через сырые сокеты.
2. После выделения/освобождения адреса демон пишет в общий `lease-database` (memfile или СУБД).
3. `kea-ctrl-agent` слушает HTTP-порт и трансформирует REST-запросы во внутренние команды, передавая их демонам через Unix domain socket (или TCP).
4. `kea-dhcp-ddns` (если загружен соответствующий hook или запущен отдельно) слушает изменения в БД аренд и инициирует DNS-обновления.

**Важно для SRE:** В высоконагруженных средах рекомендуется разделять `kea-dhcp4` и `kea-dhcp-ddns` на разные хосты. DDNS-демон может быть единой точкой для обновлений зон как DHCPv4, так и DHCPv6.

### Модульность Kea: Hook-библиотеки

Функционал Kea расширяется через подключаемые модули. Каждая библиотека — это `.so`/`.dll` файл, загружаемый демоном при старте. Hooks могут перехватывать события пакетного цикла (pkt4-receive, pkt4-send и т.д.), управлять арендами или добавлять команды в REST API.

| Hook-библиотека | Назначение | Типичное использование |
| :--- | :--- | :--- |
| `libdhcp_mysql` | Хранение аренд в MySQL | Масштабирование, интеграция с IPAM |
| `libdhcp_postgresql` | Хранение аренд в PostgreSQL | Альтернатива MySQL |
| `libdhcp_flex_id` | Гибкая идентификация клиентов | По MAC, Client-ID, Option 82 |
| `libdhcp_class_cmds` | Управление классами через API | Динамическое переключение классов |
| `libdhcp_radius` | Интеграция с RADIUS | 802.1X, динамические VLAN |
| `libdhcp_stat_cmds` | Экспорт статистики | Мониторинг, Prometheus |
| `libdhcp_ha` | High Availability (глобальный HA) | Active-Standby через MySQL |
| `libdhcp_4o6` | DHCPv4-over-DHCPv6 | Туннелизация DHCPv4 через DHCPv6-ретранслятор |
| `libdhcp_lease_cmds` | Управление арендами через API | bulk-операции, purge-expired |
| `libdhcp_subnet_cmds` | Управление подсетями через API | Динамическое добавление подсетей без перезагрузки |

**Установка hooks из исходников (если пакет не содержит библиотеку):**

```bash
# 1. Скачать исходники Kea (версия должна совпадать с установленной)
KEA_VERSION=2.6.1
wget https://downloads.isc.org/isc/kea/${KEA_VERSION}/kea-${KEA_VERSION}.tar.gz
tar xzf kea-${KEA_VERSION}.tar.gz
cd kea-${KEA_VERSION}

# 2. Собрать с поддержкой нужного бэкенда
./configure \
  --prefix=/usr \
  --with-mysql \
  --with-postgresql \
  --enable-hooks

make -j$(nproc)
sudo make install

# 3. Проверить установку hooks
ls -la /usr/lib/kea/hooks/
# → libdhcp_mysql.so, libdhcp_postgresql.so, libdhcp_ha.so, ...

# 4. Добавить в kea-dhcp4.conf
```

**Параметры hooks в конфигурации:**

```json
"hooks-libraries": [
    {
        "library": "/usr/lib/kea/hooks/libdhcp_mysql.so",
        "parameters": {
            "mysql": {
                "host": "10.0.0.100",
                "port": 3306,
                "user": "kea",
                "password": "secret",
                "database": "kea"
            }
        }
    },
    {
        "library": "/usr/lib/kea/hooks/libdhcp_ha.so",
        "parameters": {
            "high-availability": [
                {
                    "name": "dhcp-ha",
                    "this-server-name": "server-1",
                    "mode": "hot-standby"
                }
            ]
        }
    }
]
```

**Важно:** Порядок загрузки hooks важен. `libdhcp_mysql` должен быть загружен ДО `libdhcp_ha`, так как HA зависит от соединения с БД.

### REST API Kea: ключевые операции

```bash
# Просмотр всех конфигураций
curl -s http://localhost:8000/ | jq

# Просмотр аренд для подсети 10.0.10.0/24
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "lease4-get", "args": {"subnet-id": 1}}' | jq

# Поиск аренды по MAC
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "lease4-get-by-hw-address", "args": {"hw-address": "00:50:56:b1:22:33"}}' | jq

# Перезагрузка конфигурации (без перезапуска сервиса)
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "config-reload"}' | jq

# Статистика
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# Управление классом через API
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "class-add", "arguments": {"client-classes": [{"name": "voip", "test": "option[60].text == \'Polycom\'"}]}}' | jq

# Очистка expired leases
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-del", "arguments": {"type": "all", "state": "expired"}}' | jq
```

**Аутентификация и TLS (Production):**

```json
// kea-ctrl-agent.conf
{
    "Control-agent": {
        "http-host": "0.0.0.0",
        "http-port": 8000,
        "trust-anchor": "/etc/kea/kea-root-ca.pem",
        "cert-file": "/etc/kea/kea-server-cert.pem",
        "key-file": "/etc/kea/kea-server-key.pem",
        "cert-required": true,
        "authentication": {
            "type": "basic",
            "realm": "Kea Management",
            "users": [
                {
                    "user": "admin",
                    "password": "strong_password_hash"
                }
            ]
        },
        "hooks-libraries": [
            {
                "library": "/usr/lib/kea/hooks/libdhcp_cb_cmds.so"
            }
        ]
    }
}
```

### Логирование Kea

Kea поддерживает структурированное логирование с детализацией до уровня пакетов. В отличие от syslog, встроенный логгер позволяет задавать отдельные параметры для каждого демона и даже для hook-библиотек.

```json
// kea-dhcp4.conf — секция loggers
{
    "Dhcp4": {
        "loggers": [
            {
                "name": "kea-dhcp4",
                "severity": "INFO",
                "debuglevel": 0,
                "output-options": [
                    {
                        "output": "/var/log/kea/kea-dhcp4.log",
                        "pattern": "%d{%Y-%m-%d %H:%M:%S.%q} %-5p %c - %m\n"
                    },
                    {
                        "output": "stdout",
                        "pattern": "%-5p %m\n"
                    }
                ],
                "flush": true,
                "maxsize": 104857600,
                "maxver": 8
            },
            {
                "name": "libdhcp_mysql.so",
                "severity": "DEBUG",
                "debuglevel": 99,
                "output-options": [
                    {
                        "output": "/var/log/kea/kea-mysql-hook.log",
                        "pattern": "%d{%Y-%m-%d %H:%M:%S.%q} %-5p %c - %m\n"
                    }
                ]
            }
        ]
    }
}
```

| Параметр | Диапазон / Значение | Назначение |
| :--- | :--- | :--- |
| `severity` | FATAL, ERROR, WARN, INFO, DEBUG | Уровень журналирования |
| `debuglevel` | 0–99 | Детализация debug-сообщений (0 = минимальная) |
| `output` | Файл, `stdout`, `stderr`, syslog | Куда направлять логи |
| `pattern` | strftime-подобный шаблон | Формат строки лога |
| `flush` | true/false | Сбрасывать буфер на диск после каждой записи |
| `maxsize` | Байты | Ротация: максимальный размер файла |
| `maxver` | Число | Количество архивных файлов при ротации |

**Ротация логов через logrotate:**

```bash
# /etc/logrotate.d/kea
/var/log/kea/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 kea kea
    postrotate
        systemctl reload kea-dhcp4 kea-dhcp6 kea-ctrl-agent
    endscript
}
```

### Классификация клиентов (Client Classification)

Kea позволяет динамически классифицировать DHCP-запросы и применять к ним разные пулы адресов, опции и политики. В отличие от ISC DHCP (где classification задаётся через `class` с фиксированными выражениями), Kea классифицирует **каждый запрос независимо** на основе настраиваемых выражений.

**Механизм работы:**
1. При получении пакета Kea последовательно оценивает все `client-classes` в порядке объявления.
2. Каждый класс имеет `test` — выражение на языке пакетных выражений Kea (аналогично BPF).
3. Если выражение истинно — пакет помечается как принадлежащий классу.
4. Классы можно использовать для фильтрации пулов (`client-class` в пуле), назначения опций или гибкой идентификации (`flex-id` hook).

**Примеры классификации:**

```json
{
    "Dhcp4": {
        "client-classes": [
            {
                "name": "voip-phones",
                "test": "option[60].text == 'Polycom'",
                "option-data": [
                    {
                        "name": "routers",
                        "data": "10.0.10.10"
                    }
                ]
            },
            {
                "name": "printers",
                "test": "substring(option[60].text, 0, 15) == 'HP JetDirect'",
                "option-data": [
                    {
                        "name": "domain-name-servers",
                        "data": "10.0.0.20"
                    }
                ]
            },
            {
                "name": "ip-cameras",
                "test": "option[82].option[1].text == 'VLAN30'",
                "option-data": [],
                "next-server": "10.0.0.200"
            }
        ],
        "subnet4": [
            {
                "id": 1,
                "subnet": "10.0.10.0/24",
                "pools": [
                    {
                        "pool": "10.0.10.50 - 10.0.10.99",
                        "client-class": "voip-phones"
                    },
                    {
                        "pool": "10.0.10.100 - 10.0.10.150",
                        "client-class": "printers"
                    },
                    {
                        "pool": "10.0.10.200 - 10.0.10.250"
                    }
                ]
            }
        ]
    }
}
```

**Динамическое управление классами через REST API:**

```bash
# Добавить класс без перезагрузки конфигурации
curl -s -X POST http://localhost:8000/ \
  -d '{
    "command": "class-add",
    "arguments": {
        "client-classes": [
            {
                "name": "temp-devices",
                "test": "option[60].text == \'TemporaryDevice\'",
                "option-data": [{"name": "domain-name-servers", "data": "8.8.8.8"}]
            }
        ]
    }
  }' | jq

# Удалить класс
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "class-del", "arguments": {"client-classes": [{"name": "temp-devices"}]}}' | jq
```

### Жизненный цикл аренды (Lease Lifecycle)

Kea поддерживает полный цикл управления арендами через REST API:

```bash
# Получить аренду по IP
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-get", "arguments": {"ip-address": "10.0.10.100"}}' | jq

# Обновить срок аренды (продлить)
curl -s -X POST http://localhost:8000/ \
  -d '{
    "command": "lease4-update",
    "arguments": {
        "ip-address": "10.0.10.100",
        "subnet-id": 1,
        "valid-lft": 172800
    }
  }' | jq

# Удалить конкретную аренду
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-del", "arguments": {"ip-address": "10.0.10.100"}}' | jq

# Пакетная очистка expired/abandoned
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-del", "arguments": {"state": "expired"}}' | jq

# Экспорт всех аренд (для бэкапа)
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease4-get-all"}' | jq '.arguments.leases' > /backup/kea-leases4-$(date +%Y%m%d).json
```

**Состояния аренды (binding state):**
- `default` (active) — активная аренда, адрес выдан клиенту.
- `expired` — срок аренды истёк, адрес может быть перевыдан.
- `released` — клиент явно освободил адрес (DHCPRELEASE).
- `abandoned` — конфликт IP (DHCPDECLINE), адрес блокирован на `abandoned-lease-time`.

### Хранение аренд в СУБД (MySQL/PostgreSQL)

Использование memfile подходит для небольших сетей (до 10 000 аренд). Для enterprise-сред с HA и высоконагруженными кластерами требуется СУБД.

**MySQL backend — инициализация схемы:**

```bash
# 1. Создать БД и пользователя
mysql -u root -p << 'EOF'
CREATE DATABASE kea CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE USER 'kea'@'%' IDentified BY 'strong_password';
GRANT ALL PRIVILEGES ON kea.* TO 'kea'@'%';
FLUSH PRIVILEGES;
EOF

# 2. Инициализировать схему через kea-admin
kea-admin db-init mysql -u kea -p strong_password -n kea -h 10.0.0.100

# 3. Проверить таблицы
mysql -u kea -p -e "USE kea; SHOW TABLES;"
# → lease4, lease6, dhcp4_options, dhcp6_options, ...

# 4. Проверить конфигурацию Kea
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf
```

**Пример конфигурации с MySQL backend:**

```json
{
    "Dhcp4": {
        "lease-database": {
            "type": "mysql",
            "host": "10.0.0.100",
            "port": 3306,
            "user": "kea",
            "password": "strong_password",
            "database": "kea",
            "connect-timeout": 5,
            "max-reconnect-tries": 3,
            "reconnect-wait-time": 3000
        },
        "hooks-libraries": [
            {
                "library": "/usr/lib/kea/hooks/libdhcp_mysql.so",
                "parameters": {
                    "mysql": {
                        "host": "10.0.0.100",
                        "port": 3306,
                        "user": "kea",
                        "password": "strong_password",
                        "database": "kea"
                    }
                }
            }
        ]
    }
}
```

**PostgreSQL backend:**

```bash
# Инициализация схемы
sudo -u postgres psql -c "CREATE DATABASE kea;"
sudo -u postgres psql -d kea -c "CREATE USER kea WITH PASSWORD 'strong_password';"
sudo -u postgres psql -d kea -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO kea;"

kea-admin db-init pgsql -u kea -p strong_password -n kea -h 10.0.0.100
```

**Таблица `lease4` (ключевые поля):**
| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `address` | INT(10) UNSIGNED | IP-адрес в виде целого числа (INET_ATON) |
| `hwaddr` | VARBINARY(20) | MAC-адрес клиента |
| `client_id` | VARBINARY(128) | Client Identifier (опция 61) |
| `valid_lifetime` | INT(10) | Оставшийся срок аренды (секунды) |
| `expire` | BIGINT(20) UNSIGNED | Время истечения (Unix timestamp) |
| `subnet_id` | INT(10) | ID подсети |
| `state` | INT(10) | Состояние аренды (active, expired, released, abandoned) |
| `hostname` | VARCHAR(255) | Имя хоста (из Option 12 или резервации) |
| `user_context` | JSON | Произвольные метаданные (например, `{"ipam": {"ref": "123"}}`) |

**Структура хранения для Kea HA:**
При использовании HA оба сервера подключаются к одной и той же БД. Kea использует optimistic locking через `state` и `expire` для предотвращения гонок при одновременном обновлении аренды.

## Практические сценарии

### Установка Kea DHCP

**Debian / Ubuntu:**

```bash
# ISC Kea официальный репозиторий
sudo apt install -y curl gnupg
curl -1sLf 'https://dl.cloudsmith.io/public/isc/kea-2-6/gpg.E4CC7D577956AD8C.key' | sudo gpg --dearmor -o /usr/share/keyrings/isc-kea.gpg
echo "deb [signed-by=/usr/share/keyrings/isc-kea.gpg] https://dl.cloudsmith.io/public/isc/kea-2-6/deb/ubuntu $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/isc-kea.list
sudo apt update

# DHCPv4 сервер + Control Agent
sudo apt install -y kea-dhcp4-server kea-ctrl-agent

# (Опционально) MySQL backend
sudo apt install -y libmysqlclient-dev
# После установки:kea-dhcp4 -> собрать с --with-mysql
```

**RHEL / Rocky / AlmaLinux:**

```bash
# ISC Kea репозиторий
sudo curl -o /etc/yum.repos.d/isc-kea.repo https://dl.cloudsmith.io/public/isc/kea-2-6/config/redhat/isc-kea.repo
sudo dnf install -y kea kea-libs

# Control Agent (отдельный пакет)
sudo dnf install -y kea-ctrl-agent
```

### Базовая конфигурация kea-dhcp4.conf

```json
{
    "Dhcp4": {
        "interfaces-config": {
            "interfaces": ["eth0"],
            "dhcp-sockets": "raw"
        },
        "lease-database": {
            "type": "memfile",
            "persist": true,
            "name": "/var/lib/kea/kea-leases4.csv",
            "lfc-interval": 3600
        },
        "valid-lifetime": 86400,
        "renew-timer": 43200,
        "rebind-timer": 75600,
        "authoritative": true,
        "loggers": [
            {
                "name": "kea-dhcp4",
                "output-options": [
                    {
                        "output": "stdout",
                        "pattern": "%-5p %m\n"
                    }
                ],
                "severity": "INFO"
            }
        ],
        "subnet4": [
            {
                "id": 1,
                "subnet": "10.0.10.0/24",
                "pools": [
                    {
                        "pool": "10.0.10.100 - 10.0.10.200"
                    }
                ],
                "option-data": [
                    {
                        "name": "routers",
                        "data": "10.0.10.1"
                    },
                    {
                        "name": "domain-name-servers",
                        "data": "10.0.0.10, 10.0.0.11"
                    },
                    {
                        "name": "domain-name",
                        "data": "corp.example.com"
                    }
                ]
            }
        ],
        "reservations": [
            {
                "hw-address": "00:50:56:b1:22:33",
                "ip-address": "10.0.10.50",
                "hostname": "srv-db-01"
            }
        ]
    }
}
```

**Конфигурация DHCPv6 (kea-dhcp6.conf):**

```json
{
    "Dhcp6": {
        "interfaces-config": {
            "interfaces": ["eth0"]
        },
        "lease-database": {
            "type": "memfile",
            "persist": true,
            "name": "/var/lib/kea/kea-leases6.csv",
            "lfc-interval": 3600
        },
        "valid-lifetime": 86400,
        "renew-timer": 43200,
        "rebind-timer": 75600,
        "subnet6": [
            {
                "id": 1,
                "subnet": "2001:db8:1::/64",
                "pools": [
                    {
                        "pool": "2001:db8:1::100 - 2001:db8:1::200"
                    }
                ],
                "option-data": [
                    {
                        "name": "dns-servers",
                        "data": "2001:db8::1, 2001:db8::2"
                    },
                    {
                        "name": "domain-search",
                        "data": "corp.example.com"
                    }
                ],
                "reservations": [
                    {
                        "duid": "00:01:00:01:2a:3b:4c:5d:6e:7f",
                        "ip-addresses": ["2001:db8:1::50"],
                        "hostname": "srv-db-01"
                    }
                ]
            }
        ]
    }
}
```

**Конфигурация DHCPv4-over-DHCPv6 (4o6):**

```json
{
    "Dhcp4": {
        "interfaces-config": {
            "interfaces": ["eth0"],
            "dhcp-sockets": "raw"
        },
        "dhcp4o6-port": 0,
        "lease-database": {
            "type": "memfile",
            "name": "/var/lib/kea/kea-leases4.csv",
            "persist": true
        },
        "subnet4": [
            {
                "id": 1,
                "subnet": "10.0.10.0/24",
                "pools": [
                    {
                        "pool": "10.0.10.100 - 10.0.10.200"
                    }
                ]
            }
        ],
        "hooks-libraries": [
            {
                "library": "/usr/lib/kea/hooks/libdhcp_4o6.so",
                "parameters": {
                    "dhcp4o6-ports": [0, 0]
                }
            }
        ]
    }
}
```

Примечание: `dhcp4o6-port: 0` означает, что `kea-dhcp4` не слушает порт 547 самостоятельно, а принимает DHCPv4-пакеты через туннель от `kea-dhcp6`, который слушает порт 547.

### Конфигурация Control Agent (kea-ctrl-agent.conf)

Control Agent служит единой точкой входа для REST API. Отделяет демоны DHCP от внешнего мира и позволяет централизованно управлять аутентификацией и TLS.

```json
{
    "Control-agent": {
        "http-host": "0.0.0.0",
        "http-port": 8000,
        "trust-anchor": "/etc/kea/kea-root-ca.pem",
        "cert-file": "/etc/kea/kea-server-cert.pem",
        "key-file": "/etc/kea/kea-server-key.pem",
        "cert-required": true,
        "authentication": {
            "type": "basic",
            "realm": "Kea Management",
            "users": [
                {
                    "user": "admin",
                    "password": "sha256$rounds=10000$salt$hash"
                }
            ]
        },
        "hooks-libraries": [
            {
                "library": "/usr/lib/kea/hooks/libdhcp_cb_cmds.so"
            }
        ]
    }
}
```

**Стандартный systemd unit (`/etc/systemd/system/kea-ctrl-agent.service`):**

```ini
[Unit]
Description=ISC Kea Control Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/sbin/kea-ctrl-agent -c /etc/kea/kea-ctrl-agent.conf
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### Валидация и запуск

```bash
# Проверка синтаксиса конфигурации
sudo kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf
# →廪 Ok или перечень ошибок

# Проверка синтаксиса Control Agent
sudo kea-ctrl-agent -t -c /etc/kea/kea-ctrl-agent.conf

# Перезапуск сервисов
sudo systemctl restart kea-dhcp4
sudo systemctl restart kea-ctrl-agent

# Статус
sudo systemctl status kea-dhcp4
sudo systemctl status kea-ctrl-agent
```

### Высокая доступность (HA) в Kea

ISC DHCP использует проприетарный Failover-протокол (TCP 647). Kea DHCP предлагает **глобальный HA** через общий бэкенд БД:

**Active-Standby через MySQL:**

```json
{
    "Dhcp4": {
        "hooks-libraries": [
            {
                "library": "/usr/lib/kea/hooks/libdhcp_mysql.so",
                "parameters": {
                    "mysql": {
                        "host": "10.0.0.100",
                        "port": 3306,
                        "user": "kea",
                        "password": "secret",
                        "database": "kea"
                    }
                }
            },
            {
                "library": "/usr/lib/kea/hooks/libdhcp_ha.so",
                "parameters": {
                    "high-availability": [
                        {
                            "name": "dhcp-ha",
                            "this-server-name": "server-1",
                            "mode": "hot-standby",
                            "heartbeat-rate": 10000,
                            "max-heartbeat-delay": 30000,
                            "max-unacked-updates": 10,
                            "peers": [
                                {
                                    "name": "server-2",
                                    "url": "http://10.0.0.11:8000/"
                                }
                            ],
                            "sync-timeout": 5000,
                            "send-updates": true,
                            "max-bulk-lease-db-queries": 0,
                            "max-bulk-lease-db-queries-rate": 0
                        }
                    ]
                }
            }
        ]
    }
}
```

**Режимы HA Kea:**

| Режим | Описание | Использование |
| :--- | :--- | :--- |
| `load-balancing` | Оба сервера обрабатывают запросы, балансировка по MAC | Основной режим |
| `hot-standby` | Primary обрабатывает, Secondary候補 | Критичные сети |
| `passive-standby` | Primary обрабатывает, Secondary только получает обновления | Резерв |

### Производительность и масштабирование

**interfaces-config — тонкая настройка сокетов:**

```json
"interfaces-config": {
    "interfaces": ["eth0", "eth1"],
    "dhcp-sockets": "raw",
    "out-of-lease-checking": false,
    "re-capture-service-name": "kea-dhcp4"
}
```

| Параметр | Значение | Назначение |
| :--- | :--- | :--- |
| `dhcp-sockets` | `raw`, `udp`, `fallback-udp` | `raw` — максимальная производительность (требует root). `fallback-udp` — для совместимости с AppArmor/SELinux. |
| `out-of-lease-checking` | true/false | Проверять, что выданный IP не belongs к другому интерфейсу (защита от misconfiguration). |
| `user` / `group` | Строка | Пользователь/группа для запуска (в связке с `dhcp-sockets: raw`). |

**Потоки и CPU:**

Kea автоматически распределяет обработку пакетов по доступным CPU-ядрам. Для привязки к конкретным ядрам используйте `cpu affinity` в systemd:

```ini
# /etc/systemd/system/kea-dhcp4.service.d/override.conf
[Service]
CPUAffinity=0,1,2,3
```

**Bulk lease-запросы:**

Для сценариев, где нужно массово обновить или удалить leases (например, при ротации подсети), используйте bulk-режим через REST API:

```bash
# Удалить все leases для подсети 10.0.10.0/24
curl -s -X POST http://localhost:8000/ \
  -d '{
    "command": "lease4-del",
    "arguments": {
        "subnet-id": 1,
        "state": "all"
    }
  }' | jq

# Bulk-update: изменить TTL для всех leases
curl -s -X POST http://localhost:8000/ \
  -d '{
    "command": "lease4-update",
    "arguments": {
        "subnet-id": 1,
        "valid-lft": 3600
    }
  }' | jq
```

**kea-lfc — фоновая компактификация:**

```bash
# Ручной запуск LFC (сжимает lease-файл, удаляет expired)
sudo kea-lfc -4 -c /etc/kea/kea-lfc4.conf

# Проверить результат
ls -la /var/lib/kea/kea-leases4.csv
# → Файл уменьшен, только active/released/abandoned
```

**Рекомендации по масштабированию:**
- До 10 000 активных leases: memfile + LFC interval 3600s.
- 10 000–100 000 leases: memfile с LFC interval 600s или MySQL single-node.
- 100 000+ leases: MySQL/PostgreSQL с connection pooling + HA pair.

### Динамическое обновление DNS (DDNS) в Kea

В Kea DDNS может работать через hook (`libdhcp_ddns.so`) или отдельный демон `kea-dhcp-ddns`. Отдельный демон предпочтительнее для централизованного управления зонами.

**Конфигурация DDNS hook (в kea-dhcp4.conf):**

```json
{
    "Dhcp4": {
        "hooks-libraries": [
            {
                "library": "/usr/lib/kea/hooks/libdhcp_ddns.so",
                "parameters": {
                    "enable-ddns": true,
                    "ddns-domains": [
                        {
                            "name": "corp.example.com.",
                            "key-name": "ddns-key",
                            "dns-servers": ["10.0.0.10"]
                        }
                    ]
                }
            }
        ]
    }
}
```

**Конфигурация TSIG-ключа (в BIND9 named.conf):**

```bash
key "ddns-key" {
    algorithm hmac-sha256;
    secret "base64_encoded_secret==";
};

zone "corp.example.com" {
    type master;
    file "db.corp.example.com";
    allow-update { key "ddns-key"; };
};
```

**Динамическое управление DDNS через REST API:**

```bash
# Включить DDNS для конкретного lease
curl -s -X POST http://localhost:8000/ \
  -d '{
    "command": "dhcp-ddns-update",
    "arguments": {
        "ip-address": "10.0.10.100",
        "ddns-domain-name": "srv-db-01.corp.example.com."
    }
  }' | jq
```

### Безопасность Kea (Sysadmin/SRE)

**Firewall (nftables / iptables):**

```bash
# Разрешить DHCP (UDP 67/68) и Control Agent (TCP 8000 только из management-сети)
nft add rule inet filter input udp dport {67,68} accept
nft add rule inet filter input tcp dport 8000 ip saddr 10.0.0.0/24 accept

# Запретить остальные входящие соединения на этих портах извне
nft add rule inet filter input udp dport {67,68} drop
nft add rule inet filter input tcp dport 8000 drop
```

**SELinux (RHEL/Rocky):**

```bash
# Проверить контекст
ls -la /usr/sbin/kea-dhcp4
# → -rwxr-xr-x. root root system_u:object_r:dhcp_exec_t:s0 kea-dhcp4

# Если порт 8000 заблокирован SELinux
sudo semanage port -a -t http_port_t -p tcp 8000

# Разрешить демону чтение конфигурации
sudo restorecon -Rv /etc/kea/
```

**AppArmor (Ubuntu/Debian):**

```bash
# Проверить статус AppArmor для Kea
sudo aa-status | grep kea

# Если профиль блокирует raw sockets
sudo aa-complain /usr/sbin/kea-dhcp4
# Или настроить /etc/apparmor.d/usr.sbin.kea-dhcp4 с allow raw
```

### Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `kea-dhcp4` не запускается | Конфигурация невалидна | `kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf` покажет строку ошибки |
| `Permission denied` на UDP 67/68 | Raw sockets требуют root | Запускать от root с `user`/`group` в конфиге, или использовать `udp` socket type |
| Клиенты не получают адреса | Интерфейс неверен или down | `ip link show eth0`, проверить `interfaces-config` |
| Hook библиотека не загружается | Путь к `.so` неверен или права | `ls -la /usr/lib/kea/hooks/libdhcp_*.so`, проверить `hooks-libraries` |
| `config-reload` возвращает ошибку | Синтаксис JSON невалиден | Проверить через `kea-dhcp4 -t` |
| HA не синхронизируется | Разная версия Kea на peers | Версии Kea должны совпадать на обоих серверах |
| MySQL connection refused | БД недоступна | `mysql -h 10.0.0.100 -u kea -p`, проверить `connect-timeout` |
| Логи не пишутся в файл | Нет прав на директорию | `chown -R kea:kea /var/log/kea/` |
| DHCP Snooping падает | Option 82 не проверяется | Включить `check-option-82` в hooks или корректно обработать в classification |
| `kea-lfc` зависает | Файл leases заблокирован другим процессом | Остановить `kea-dhcp4` перед ручным запуском `kea-lfc` |

**Диагностика через journalctl:**

```bash
# Просмотр логов Kea в реальном времени
journalctl -u kea-dhcp4 -f

# Фильтрация по ошибкам
journalctl -u kea-dhcp4 --since "1 hour ago" | grep -iE "error|fail|drop|NACK"

# Просмотр ошибок инициализации hook'ов
journalctl -u kea-dhcp4 | grep -i "hooks"
```

### Рекомендации для production

1. **Валидация перед любым изменением:** Никогда не перезапускайте `kea-dhcp4` без предварительного `kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf`. Ошибка в конфигурации остановит выдачу адресов во всей сети.
2. **Backup lease-файла и конфигурации:**
   ```bash
   # Критические артефакты для бэкапа
   /etc/kea/kea-dhcp4.conf
   /var/lib/kea/kea-leases4.csv
   /var/lib/kea/kea-leases6.csv
   ```
3. **Безопасность:** Используйте TLS и базовую аутентификацию на Control Agent. Не открывайте порт 8000 в интернет. Ограничьте доступ management-сетью.
4. **Мониторинг:** Интегрируйте с Prometheus (через `kea-exporter` или `libdhcp_stat_cmds`). Следите за `dhcp_leases_active / dhcp_leases_total > 0.8`.
5. **Failover:** Для критичных сетей используйте HA pair с MySQL backend и регулярно проверяйте состояние через `statistic-get` (см. раздел HA).
6. **Обновление конфигурации:** Используйте `config-reload` вместо `systemctl restart` во время рабочего дня. Это сохраняет все активные аренды в памяти.
7. **Логи:** В production используйте файловый вывод с ротацией (logrotate). `stdout` только для контейнеров.
8. **SELinux/AppArmor:** При использовании raw sockets убедитесь, что политики МББ разрешают работу Kea на портах 67/68.

## Сетевые сценарии

### PXE-загрузка через Kea

Kea поддерживает PXE-загрузку через опции `next-server` (Option 66) и `boot-file-name` (Option 67):

```json
{
    "subnet4": [{
        "pools": [{"pool": "10.0.10.100 - 10.0.10.200"}],
        "option-data": [
            {"name": "next-server", "data": "10.0.0.200"},
            {"name": "boot-file-name", "data": "pxelinux.0"}
        ]
    }]
}
```

Для UEFI-клиентов используйте client classification:

```json
{
    "client-classes": [
        {
            "name": "uefi-clients",
            "test": "option[93].hex & 0x100",
            "option-data": [{"name": "boot-file-name", "data": "grubx64.efi"}]
        },
        {
            "name": "bios-clients",
            "test": "not (option[93].hex & 0x100)",
            "option-data": [{"name": "boot-file-name", "data": "pxelinux.0"}]
        }
    ]
}
```

### VLAN и DHCP Relay

DHCP Relay (ip helper) пересылает broadcast-запросы между подсетями. Kea определяет подсеть клиента по полю `giaddr` (Gateway IP Address) в DHCP-пакете.

**Конфигурация relay на Cisco:**
```
interface Vlan10
 ip helper-address 10.0.0.10
interface Vlan20
 ip helper-address 10.0.0.10
```

**Конфигурация Kea для нескольких подсетей:**
```json
{
    "subnet4": [
        {"id": 1, "subnet": "10.0.10.0/24", "pools": [{"pool": "10.0.10.100 - 10.0.10.200"}]},
        {"id": 2, "subnet": "10.0.20.0/24", "pools": [{"pool": "10.0.20.100 - 10.0.20.200"}]}
    ]
}
```

Kea автоматически сопоставляет `giaddr` с нужной подсетью. Подробности — [DHCP Relay](../../../../Networking/Protocols/DHCP/dhcp_relay.md).

### DHCP Snooping и Option 82

DHCP Snooping — L2-механизм коммутатора, предотвращающий rogue DHCP-серверы. Kea работает с Option 82 через hook `libdhcp_flex_id`:

```json
{
    "hooks-libraries": [{
        "library": "/usr/lib/kea/hooks/libdhcp_flex_id.so",
        "parameters": {
            "identifier-expression": "relay[0].option[82].hex"
        }
    }]
}
```

Влияние миграции ISC → Kea на сеть:
- DHCP Scooping bindings остаются на коммутаторах (не зависят от сервера)
- DAI (Dynamic ARP Inspection) продолжает работать без изменений
- IP Source Guard требует обновления только при смене IP сервера

---

## Масштабирование и производительность

### Batch-запись lease

ISC DHCP делает fsync на каждый ACK — это создаёт bottleneck при высокой нагрузке. Kea использует batch-запись: изменения накапливаются в памяти и записываются на диск с настраиваемым интервалом.

Преимущества:
- Снижение IOPS на диск (критично для HDD)
- Увеличение throughput в 10-100 раз
- Настраиваемый интервал через `lfc-interval`

В production с HA через MySQL batch-запись не влияет на надёжность, так как БД обеспечивает durability.

### Рекомендации по масштабированию

| Пулы адресов | Рекомендуемый backend |
|:--- |:--- |
| <10 000 leases | memfile + LFC interval 3600s |
| 10 000–100 000 | memfile + LFC 600s или MySQL single-node |
| 100 000+ | MySQL/PostgreSQL + connection pooling + HA pair |

Для 100K+ leases — только MySQL/PostgreSQL backend. Memfile не масштабируется.

### CPU affinity

Для привязки `kea-dhcp4` к конкретным ядрам:

```ini
# /etc/systemd/system/kea-dhcp4.service.d/override.conf
[Service]
CPUAffinity=0,1,2,3
```

---

## DHCPv6 (kea-dhcp6)

### Основы DHCPv6

DHCPv6 (RFC 8415) — протокол получения IPv6-адресов и параметров сети. В отличие от DHCPv4, DHCPv6 не использует MAC-адреса для идентификации, а работает через **DUID** (DHCP Unique Identifier) и **IAID** (Identity Association Identifier).

**Режимы DHCPv6:**

| Режим | Описание | Использование |
| :--- | :--- | :--- |
| **Stateful** | Сервер выдает адрес и параметры сети | Централизованное управление адресами |
| **Stateless** | Адрес через SLAAC, параметры (DNS, домен) через DHCPv6 | DHCPv6-only для опций |
| **Prefix Delegation (PD)** | Сервер выдает префикс (/56, /48) клиенту | Роутеры, CPE |

### Конфигурация kea-dhcp6

**Файл `/etc/kea/kea-dhcp6.conf`:**

```json
{
    "Dhcp6": {
        "interfaces-config": {
            "interfaces": ["eth0"],
            "service-sockets": [
                {
                    "socket-type": "raw",
                    "socket-name": "kea-dhcp6-raw"
                }
            ]
        },
        "lease-database": {
            "type": "memfile",
            "persist": true,
            "name": "/var/lib/kea/kea-leases6.csv",
            "lfc-interval": 3600
        },
        "server-id": {
            "type": "EN",
            "value": "00:11:22:33:44:55:66"
        },
        "preferred-lifetime": 3600,
        "valid-lifetime": 7200,
        "renew-timer": 1800,
        "rebind-timer": 3600,
        "subnet6": [
            {
                "id": 1,
                "subnet": "fd00:1::/64",
                "pools": [
                    {
                        "pool": "fd00:1::100 - fd00:1::ffff"
                    }
                ],
                "interface": "eth0",
                "option-data": [
                    {
                        "name": "dns-servers",
                        "data": "fd00::1, 2001:4860:4860::8888"
                    },
                    {
                        "name": "domain-search",
                        "data": "example.com, corp.local"
                    }
                ],
                "relay": {
                    "ip-addresses": ["fd00::1"]
                }
            }
        ],
        "option-data": [
            {
                "name": "dns-servers",
                "data": "fd00::1"
            }
        ],
        "client-classes": [
            {
                "name": "voip-v6",
                "test": "option[16].hex == 'Polycom'",
                "option-data": [
                    {
                        "name": "dns-servers",
                        "data": "fd00::100"
                    }
                ]
            }
        ],
        "loggers": [
            {
                "name": "kea-dhcp6",
                "severity": "INFO",
                "output-options": [
                    {
                        "output": "/var/log/kea/kea-dhcp6.log"
                    }
                ]
            }
        ]
    }
}
```

### Key DHCPv6 Options

| Опция | Код | Описание | Пример |
| :--- | :--- | :--- | :--- |
| **DNS-Servers** | 23 | Адреса DNS-серверов | `fd00::1` |
| **Domain-Search** | 24 | Домены поиска | `example.com` |
| **NTP-Servers** | 56 | Адреса NTP | `fd00::10` |
| **SIP-Servers** | 21 | SIP-серверы | `sip.example.com` |
| **TFTP-Server** | 32 | TFTP-сервер | `fd00::20` |
| **Boot-File-Param** | 59 | Параметры загрузки | `/pxelinux.0` |

### Prefix Delegation (PD)

PD позволяет DHCPv6-серверу выдать клиенту-роутеру префикс (обычно /56 или /48) для раздачи адресов внутри подсети:

```json
{
    "Dhcp6": {
        "subnet6": [
            {
                "id": 2,
                "subnet": "fd00:2::/48",
                "pd-pools": [
                    {
                        "prefix": "fd00:2::",
                        "prefix-len": 48,
                        "delegated-len": 56
                    }
                ],
                "interface": "eth1"
            }
        ]
    }
}
```

**Результат:** Клиент (роутер) получает префикс `fd00:2:XX::/64` (где XX — делегированный диапазон) и раздает адреса через SLAAC или DHCPv6 внутри этой подсети.

### Запуск kea-dhcp6

```bash
# Проверка конфигурации
kea-dhcp6 -t -c /etc/kea/kea-dhcp6.conf

# Запуск (systemd)
sudo systemctl enable --now kea-dhcp6

# Проверка статуса
sudo systemctl status kea-dhcp6

# Просмотр логов
sudo journalctl -u kea-dhcp6 -f

# Просмотр DHCPv6 аренд через REST API
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "lease6-get", "args": {"subnet-id": 1}}' | jq

# Просмотр DUID клиента
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "lease6-get-by-duid", "args": {"duid": "00:01:00:01:..."}}' | jq
```

### DHCPv6 Relay

Для работы kea-dhcp6 в сети с VLAN-сегментацией используется DHCPv6-ретранслятор (relay). На каждом VLAN-интерфейсе настраивается relay, направляющий DHCPv6-запросы на сервер:

```bash
# Установка kea-dhcp-relay
sudo apt install kea-dhcp-relay -y

# Конфигурация (/etc/kea/kea-dhcp-relay.conf)
{
    "DhcpRelay": {
        "interfaces": ["eth0.100", "eth0.200"],
        "server": ["fd00::1:547"]
    }
}

# Запуск
sudo systemctl enable --now kea-dhcp-relay
```

### Диагностика DHCPv6

```bash
# Проверка RA на клиенте
rdisc6 eth0

# Ручной запрос DHCPv6 через низкоуровневый инструмент
sudo dhclient -6 -v eth0

# Перехват DHCPv6-трафика
sudo tcpdump -i eth0 -n "udp port 546 or udp port 547" -vv

# Проверка DUID клиента
cat /var/lib/NetworkManager/internal-*.lease | grep duid

# Проверка systemd-networkd DHCPv6
networkctl status
resolvectl status
```

### Типичные ошибки DHCPv6

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Клиент не получает адрес | RA с M-flag не отправляются | Проверить `radvd.conf`, `AdvManagedFlag on` |
| Клиент получает только link-local | kea-dhcp6 не слушает UDP 546/547 | `ss -6 -ulnp | grep 546` |
| DNS не работает | Опция 23 (dns-servers) не настроена | Добавить `"name": "dns-servers"` в option-data |
| PD не работает | Клиент не запрашивает IA_PD | Проверить `dhclient -6 -P -N eth0` |
| Relay не пересылает | Интерфейс relay не в том VLAN | `tcpdump -i eth0.100 udp port 547` |

---

## Дополнительная информация

### Шпаргалка миграции конфигов ISC → Kea

| ISC dhcpd.conf | Kea kea-dhcp4.conf |
| :--- | :--- |
| `subnet 10.0.10.0 netmask 255.255.255.0 { ... }` | `"subnet4": [{"subnet": "10.0.10.0/24", ...}]` |
| `range 10.0.10.100 10.0.10.200;` | `"pools": [{"pool": "10.0.10.100 - 10.0.10.200"}]` |
| `option routers 10.0.10.1;` | `"option-data": [{"name": "routers", "data": "10.0.10.1"}]` |
| `option domain-name-servers 10.0.0.10;` | `"option-data": [{"name": "domain-name-servers", "data": "10.0.0.10"}]` |
| `default-lease-time 86400;` | `"valid-lifetime": 86400` |
| `max-lease-time 172800;` | `"max-valid-lifetime": 172800` |
| `fixed-address 10.0.10.50;` | `"ip-address": "10.0.10.50"` (в reservations) |
| `hardware ethernet 00:50:56:b1:22:33;` | `"hw-address": "00:50:56:b1:22:33"` |
| `allow members of "voip";` | Используйте `client-classes` |

### Связанные разделы

#### Kea DHCP
- **[Kea DHCP: Миграция с ISC](./kea_dhcp_migration.md)** — пошаговое руководство по переходу.
- **[Kea DHCP: Управление через Ansible](./kea_ansible_management.md)** — IaC для Kea.
- **[Kea DHCP: Production Operations](./kea_production_operations.md)** — day-2 ops, мониторинг, troubleshooting.
- **[Kea DHCP: Безопасность и Hardening](./kea_security_hardening.md)** — TLS, SELinux, firewall, DHCP Snooping.
- **[Kea DHCP: Docker/Podman](./kea_docker_deployment.md)** — контейнерное развертывание.

#### ISC DHCP (legacy)
- **[ISC DHCP: Обзор архитектуры](./isc_dhcp_server_overview.md)** — компоненты унаследованного ISC DHCP.
- **[ISC DHCP: Базовая настройка](./isc_dhcp_server_basic_config.md)** — структура и опции `dhcpd.conf`.
- **[ISC DHCP: Failover](./isc_dhcp_server_failover.md)** — ISC-проприетарный Failover.
- **[ISC DHCP: Проверка и мониторинг](./isc_dhcp_server_verification.md)** — диагностика ISC DHCP.

#### DHCP протокол
- **[DHCP-клиенты Linux](./dhcp_clients_comparison.md)** — dhclient vs NetworkManager vs systemd-networkd.
- **[DHCP: Инциденты и playbook'и](./dhcp_incident_playbook.md)** — реальные сценарии и пошаговые инструкции.
- **[Обзор DHCP](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** — теория DORA/SARR.
- **[Время аренды](../../../../Networking/Protocols/DHCP/dhcp_lease_time.md)** — таймеры T1/T2 и брокеные аренды.
- **[DHCP Relay](../../../../Networking/Protocols/DHCP/dhcp_relay.md)** — ретрансляция между подсетями.
- **[Безопасность DHCP](../../../../Networking/Protocols/DHCP/dhcp_security.md)** — DHCP Snooping и защита.
- **[Мониторинг и наблюдаемость DHCP](../../../../Networking/Protocols/DHCP/dhcp_monitoring_observability.md)** — Prometheus, Grafana, SIEM.
- **[Диагностика DHCP](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)** — tcpdump, Wireshark, анализ логов.

#### Внешние ресурсы
- **RFC 8415** — Dynamic Host Configuration Protocol for IPv6 (Kea → RFC-compliant).
- **[Kea DHCP Documentation](https://kea.readthedocs.io/)** — официальная документация ISC Kea.
