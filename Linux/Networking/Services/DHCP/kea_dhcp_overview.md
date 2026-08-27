# Kea DHCP: Архитектура и настройка

---

## Определения

**Kea DHCP** — современная высокопроизводительная реализация DHCP-сервера, разработанная ISC как замена устаревшего ISC DHCP. Поддерживает DHCPv4, DHCPv6 и DHCPv4-over-DHCPv6.

**Control Agent (CA)** — встроенный HTTP(S)-сервер, предоставляющий REST API для управления Kea DHCP в реальном времени (просмотр аренд, перезагрузка конфигурации, управление подсетями).

**Hook-библиотеки (Hooks)** — плагины, расширяющие функционал Kea: classified responses, Flex ID, RADIUS, MySQL/PostgreSQL backend, DHCPv4 over DHCPv6. Подключаются через массив `"hooks-libraries"` в конфигурации.

**kea-lfc (Lease File Cleanup)** — фоновая утилита для периодической компактификации и очистки файла аренд (memfile), предотвращающая неконтролируемый рост.

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

### Модульность Kea: Hook-библиотеки

Функционал Kea расширяется через подключаемые модули:

| Hook-библиотека | Назначение | Типичное использование |
| :--- | :--- | :--- |
| `libdhcp_mysql` | Хранение аренд в MySQL | Масштабирование, интеграция с IPAM |
| `libdhcp_postgresql` | Хранение аренд в PostgreSQL | Альтернатива MySQL |
| `libdhcp_flex_id` | Гибкая идентификация клиентов | По MAC, Client-ID, Option 82 |
| `libdhcp_class_cmds` | Управление классами через API | Динамическое переключение классов |
| `libdhcp_radius` | Интеграция с RADIUS | 802.1X, динамические VLAN |
| `libdhcp_stat_cmds` | Экспорт статистики | Мониторинг, Prometheus |
| `libdhcp_ha` | High Availability (глобальный HA) | Active-Standby через MySQL |

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
```

---

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

- **[ISC DHCP: Обзор архитектуры](./isc_dhcp_server_overview.md)** — компоненты унаследованного ISC DHCP.
- **[ISC DHCP: Базовая настройка](./isc_dhcp_server_basic_config.md)** — структура и опции `dhcpd.conf`.
- **[ISC DHCP → Kea: Миграция](./kea_dhcp_migration.md)** — пошаговое руководство по переходу.
- **[ISC DHCP: Проверка и мониторинг](./isc_dhcp_server_verification.md)** — диагностика ISC DHCP.
- **[Обзор DHCP](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** — теория DORA/SARR.
- **[Безопасность DHCP](../../../../Networking/Protocols/DHCP/dhcp_security.md)** — DHCP Snooping и защита.
- **[Мониторинг и наблюдаемость DHCP](../../../../Networking/Protocols/DHCP/dhcp_monitoring_observability.md)** — Prometheus, Grafana, SIEM.
- **RFC 8415** — Dynamic Host Configuration Protocol for IPv6 (Kea → RFC-compliant).
- **[Kea DHCP Documentation](https://kea.readthedocs.io/)** — официальная документация ISC.
