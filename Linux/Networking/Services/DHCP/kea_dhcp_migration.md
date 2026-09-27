# Kea DHCP: Миграция с ISC DHCP

---

## Определения

**Миграция DHCP** — процесс перехода с ISC DHCP (`dhcpd`) на Kea DHCP (`kea-dhcp4`) с сохранением работоспособности сервиса и данных аренды.

**Конвертация конфигурации** — ручной или автоматический процесс преобразования `dhcpd.conf` (иерархический текст) в `kea-dhcp4.conf` (JSON-формат) с учётом различий в синтаксисе.

**Rollback** — процедура отката к предыдущему состоянию (ISC DHCP) в случае проблем после миграции.

**Параллельная работа (Dual-Run)** — режим, при котором ISC и Kea работают одновременно на разных серверах, разделяя одну сеть.

---

## Основные концепции

### Почему миграция критична

ISC DHCP официально достиг стадии **EOL (End of Life)** в 2022 году. Для новых инсталляций и долгосрочной эксплуатации в 2026 году переход на Kea DHCP является рекомендуемым. Kea предоставляет:
- Многопоточную архитектуру (производительность на многоядерных системах)
- Нативный REST API для управления и мониторинга
- Hook-библиотеки для расширения функционала (MySQL, PostgreSQL, RADIUS, HA)
- Глобальный HA через общую базу данных аренд

### Стратегии миграции

| Стратегия | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Big-Bang** | Один сервер, ISC → Kea за 1 перезапуск | Просто, быстро | Риск простоя |
| **Параллельная работа** | ISC (primary) + Kea (secondary) одновременно | Нулевой простой, откат за секунду | Требует 2 сервера |
| **Фазовая** | Kea на новой подсети, затем миграция остальных | Минимальный риск | Долго, сложно |

**Рекомендация для прода:** Стратегия **Параллельная работа** — ISC обрабатывает основной трафик, Kea запускается как secondary. После проверки — swap ролей.

### Что конвертируется, а что — нет

**Конвертируется автоматически:**
- Subnets и pools
- Option-data (routers, DNS, domain-name)
- Reservations (fixed-address, hw-address)
- Timers (valid-lifetime, renew-timer, rebind-timer)
- Authoritative directive
- Classes (с ограничениями)

**Требует ручной конвертации:**
- `class`/`subclass` с регулярными выражениями → Kea `client-classes` с другим синтаксисом
- `failover peer` → Kea HA hooks (полностью другой механизм)
- `option-82` processing → hooks `libdhcp_class_cmds` или `libdhcp_flex_id`
- `ddns-update-style interim` → Kea DDNS hooks
- `deny/allow unknown-clients` → Kea `client-classification`

**НЕ конвертируется (нет аналога):**
- `omshell` → Используйте REST API
- `dnsmasq` → Kea не имеет встроенного DNS; используйте BIND9 отдельно
- `filename` для PXE → Используйте `boot-file-name` в option-data

### Форматы хранения аренд: ISC vs Kea

| Характеристика | ISC DHCP | Kea DHCP |
| :--- | :--- | :--- |
| **Формат файла** | Текстовый, блоки `lease { ... }` | CSV (memfile) или SQL (MySQL/PostgreSQL) |
| **Синхронизация записи** | fsync на каждый ACK (медленно) | Batch-запись (произвольный интервал) |
| **Масштабируемость** | До ~5 000 активных аренд | До миллионов (с СУБД) |
| **Читаемость** | Любой текстовый редактор | CSV: текстовый; SQL: структурированный |

**Пример формата ISC DHCP (`dhcpd.leases`):**
```text
lease 10.0.10.25 {
  starts 1 2026/07/20 12:00:00;
  ends 2 2026/07/21 12:00:00;
  cltt 1 2026/07/20 11:55:00;
  binding state active;
  next binding state free;
  hardware ethernet 00:50:56:b1:22:33;
  uid "\001\000PV\261\"3";
  client-hostname "srv-db-01";
}
```

**Пример формата Kea DHCP (`kea-leases4.csv`, memfile):**
```csv
address,hwaddr,client_id,valid_lifetime,expire,subnet_id,state,hostname
10.0.10.25,00:50:56:b1:22:33,,86400,1753272000,1,0,srv-db-01
```

**Состояния аренды (binding state) в Kea:**
- `0` (default/active) — активная аренда
- `1` (expired) — срок истёк
- `2` (released) — клиент освободил
- `3` (abandoned) — конфликт IP

### Совместимость версий

| ISC DHCP | Рекомендуемый Kea | Примечание |
| :--- | :--- | :--- |
| 4.4.x | 2.4.x или 2.6.x | Полная совместимость конфигурации |
| 4.2.x | 2.2.x или 2.4.x | Проверьте deprecated-параметры |
| 4.1.x и старше | 2.0.x+ | Требуется ручная чистка конфигурации |

### Автоматическая конвертация: `kea-confconv`

ISC Kea поставляет утилиту `kea-confconv` для автоматической конвертации `dhcpd.conf` в `kea-dhcp4.conf`:

```bash
# 1. Установка (часто входит в пакет kea-dhcp4-server)
sudo apt install -y kea-dhcp4-server

# 2. Конвертация
kea-confconv -4 -i /etc/dhcp/dhcpd.conf -o /tmp/kea-dhcp4.conf

# 3. Проверка результата
cat /tmp/kea-dhcp4.conf | jq '.' > /dev/null && echo "JSON valid" || echo "JSON invalid"
```

**Ограничения `kea-confconv`:**
- Не конвертирует `failover peer` → требуется ручная настройка HA hooks
- Не конвертирует сложные `class` с regex → требуется ручная проверка `client-classes`
- Не конвертирует `ddns-update-style` → требуется ручная настройка DDNS hook
- Всегда требует ручной ревью и доработки

### JSON-синтаксис: типичные ошибки

| Ошибка ISC | Некорректный JSON | Корректный JSON |
| :--- | :--- | :--- |
| Отсутствие запятых | `"routers": "10.0.10.1" "domain-name-servers": "10.0.0.10"` | `"routers": "10.0.10.1", "domain-name-servers": "10.0.0.10"` |
| Завершающая запятая | `"data": "10.0.10.1",` (в конце блока) | `"data": "10.0.10.1"` (без запятой) |
| Неэкосированные ключи | `{ Dhcp4: { ... } }` | `{ "Dhcp4": { ... } }` |
| Одиночные кавычки | `'option[60].text'` | `"option[60].text"` |
| Комментарии | `// комментарий` | `/* комментарий */` или удалить |
| trailing comma | `"pools": [...],` | `"pools": [...]` (в конце объекта) |

**Валидация JSON:**
```bash
# Проверка синтаксиса
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf
jq . /etc/kea/kea-dhcp4.conf > /dev/null && echo "Valid JSON" || echo "Invalid JSON"
```

---

## Практические сценарии

### Подготовка к миграции

```bash
# 1. Сделайте бэкап ISC DHCP
sudo systemctl stop isc-dhcp-server
sudo cp -r /etc/dhcp /backup/isc-dhcp-conf-$(date +%Y%m%d)
sudo cp /var/lib/dhcp/dhcpd.leases /backup/dhcpd.leases-$(date +%Y%m%d)

# 2. Проверьте синтаксис текущего конфига
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf

# 3. Установите Kea (если ещё не установлен)
sudo apt install -y kea-dhcp4-server kea-ctrl-agent

# 4. Определите интерфейсы, на которых работает DHCP
ip -4 addr show | grep -E "inet "
```

### Ручная конвертация dhcpd.conf → kea-dhcp4.conf

**ISC dhcpd.conf (исходный):**

```text
authoritative;
default-lease-time 86400;
max-lease-time 172800;
option domain-name-servers 10.0.0.10, 10.0.0.11;
option domain-name "corp.example.com";
log-facility local7;

class "voip-phones" {
    match if option vendor-class-identifier = "Polycom";
}

subnet 10.0.10.0 netmask 255.255.255.0 {
    option routers 10.0.10.1;
    option subnet-mask 255.255.255.0;
    option broadcast-address 10.0.10.255;
    pool {
        allow members of "voip-phones";
        range 10.0.10.50 10.0.10.99;
    }
    pool {
        range 10.0.10.100 10.0.10.200;
    }
}

host srv-db-01 {
    hardware ethernet 00:50:56:b1:22:33;
    fixed-address 10.0.10.50;
}
```

**Kea kea-dhcp4.conf (результат):**

```json
{
    "Dhcp4": {
        "authoritative": true,
        "valid-lifetime": 86400,
        "max-valid-lifetime": 172800,
        "renew-timer": 43200,
        "rebind-timer": 75600,
        "interfaces-config": {
            "interfaces": ["eth0"]
        },
        "lease-database": {
            "type": "memfile",
            "persist": true,
            "name": "/var/lib/kea/kea-leases4.csv"
        },
        "option-data": [
            {
                "name": "domain-name-servers",
                "data": "10.0.0.10, 10.0.0.11"
            },
            {
                "name": "domain-name",
                "data": "corp.example.com"
            }
        ],
        "client-classes": [
            {
                "name": "voip-phones",
                "test": "option[60].text == 'Polycom'"
            }
        ],
        "subnet4": [
            {
                "id": 1,
                "subnet": "10.0.10.0/24",
                "option-data": [
                    {
                        "name": "routers",
                        "data": "10.0.10.1"
                    },
                    {
                        "name": "subnet-mask",
                        "data": "255.255.255.0"
                    },
                    {
                        "name": "broadcast-address",
                        "data": "10.0.10.255"
                    }
                ],
                "pools": [
                    {
                        "pool": "10.0.10.50 - 10.0.10.99",
                        "client-class": "voip-phones"
                    },
                    {
                        "pool": "10.0.10.100 - 10.0.10.200"
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
        ]
    }
}
```

### Миграция базы данных аренд

**Вариант 1: Через REST API (рекомендуется для малых/средних сетей)**

```bash
# 1. Запустите Kea с пустым lease-файлом
sudo systemctl start kea-dhcp4

# 2. Экспортируйте все ISC-аренды через REST API Kea
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "lease4-get-all"}' | jq '.arguments.leases | length'
# → 0 (изначально)

# 3. Импортируйте leases через REST API
# Пример: добавление аренды
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "command": "lease4-add",
    "arguments": {
      "ip-address": "10.0.10.25",
      "hw-address": "00:50:56:b1:22:33",
      "valid-lft": 86400,
      "subnet-id": 1,
      "hostname": "srv-db-01"
    }
  }' | jq

# 4. Или массовый импорт через Python-скрипт
python3 - << 'EOF'
import requests, json, csv

# Чтение dhcpd.leases (упрощённый парсер)
import re
with open('/var/lib/dhcp/dhcpd.leases') as f:
    content = f.read()

leases = re.findall(r'lease (\S+) \{([^}]+)\}', content, re.DOTALL)
print(f"Найдено {len(leases)} ISC-аренд")

KEA_API = "http://localhost:8000"
for ip, block in leases:
    hw = re.search(r'hardware ethernet (\S+);', block)
    hostname = re.search(r'client-hostname "([^"]+)"', block)
    state = re.search(r'binding state (\S+);', block)
    
    if hw and state and state.group(1) == 'active':
        payload = {
            "command": "lease4-add",
            "arguments": {
                "ip-address": ip,
                "hw-address": hw.group(1),
                "valid-lft": 86400,
                "subnet-id": 1
            }
        }
        if hostname:
            payload["arguments"]["hostname"] = hostname.group(1)
        r = requests.post(KEA_API, json=payload, timeout=5)
        print(f"{ip}: {r.status_code}")
EOF
```

**Вариант 2: Через MySQL backend (для enterprise-сред)**

```bash
# 1. Инициализируйте схему Kea MySQL
kea-admin db-init mysql -u kea -p strong_password -n kea -h 10.0.0.100

# 2. Перенесите leases из ISC в MySQL
# Упрощённый ETL (Python):
python3 - << 'EOF'
import pymysql, re

ISC_DB = pymysql.connect(host="localhost", user="root", password="", database="kea")
KEA_DB = pymysql.connect(host="10.0.0.100", user="kea", password="strong_password", database="kea")

with open('/var/lib/dhcp/dhcpd.leases') as f:
    content = f.read()

leases = re.findall(r'lease (\S+) \{([^}]+)\}', content, re.DOTALL)
with KEA_DB.cursor() as cur:
    for ip, block in leases:
        hw = re.search(r'hardware ethernet (\S+);', block)
        state = re.search(r'binding state (\S+);', block)
        if hw and state and state.group(1) == 'active':
            cur.execute("""
                INSERT INTO lease4 (address, hwaddr, valid_lifetime, expire, subnet_id, state)
                VALUES (INET_ATON(%s), %s, 86400, UNIX_TIMESTAMP()+86400, 1, 0)
                ON DUPLICATE KEY UPDATE address=address
            """, (ip, hw.group(1).encode()))
KEA_DB.commit()
print(f"Импортировано {len(leases)} аренд")
EOF
```

### Пошаговая миграция: параллельный режим

```bash
# === Фаза 1: Подготовка ===
# На сервере Kea (второй сервер):
sudo systemctl stop isc-dhcp-server
# Скопировать конфиг ISC, сконвертировать в Kea-формат
# Запустить Kea на том же IP, что и ISC-primary

# === Фаза 2: Тестирование ===
# Kea работает на secondary, ISC на primary
# Проверить: выдает ли Kea адреса из своего пула
sudo tcpdump -i eth0 -n udp port 67 -c 20
# → Ожидаем DISCOVER/OFFER/REQUEST/ACK от Kea

# Проверка статистики через REST API
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# === Фаза 3: Swap ===
# Перевести ISC-сервер в standby
sudo systemctl stop isc-dhcp-server
# Kea берёт на себя 100% нагрузки
sudo systemctl start kea-dhcp4
# Проверить: все клиенты получают адреса
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# === Фаза 4: Удаление ISC ===
sudo apt remove -y isc-dhcp-server
# Бэкап: /backup/isc-dhcp-conf-$(date +%Y%m%d)
```

### Тестирование клиентов после миграции

```bash
# На клиенте Linux (NetworkManager):
sudo dhclient -r && sudo dhclient -v eth0
# → Ожидаем: DHCPDISCOVER → DHCPOFFER → DHCPREQUEST → DHCPACK

# Проверка lease-файла клиента:
cat /var/lib/dhcp/dhclient.leases | grep -E "fixed-address|dhcp-lease-time|renew|rebind"
# → fixed-address 10.0.10.100;
# → dhcp-lease-time 86400;
# → renew 4 2026/08/27 06:00:00;
# → rebind 4 2026/08/27 18:48:00;

# Проверка на Windows:
ipconfig /all
# → Lease Obtained, Lease Expires, DHCP Server

# Проверка на Cisco:
show dhcp lease
# → State: SELECTING, BOUND, etc.
```

### Rollback: откат к ISC DHCP

```bash
# 1. Остановить Kea
sudo systemctl stop kea-dhcp4

# 2. Восстановить ISC DHCP конфиг
sudo cp -r /backup/isc-dhcp-conf-YYYYMMDD/* /etc/dhcp/

# 3. Проверить синтаксис ISC
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf

# 4. Запустить ISC DHCP
sudo systemctl start isc-dhcp-server

# 5. Проверить
sudo tcpdump -i eth0 -n udp port 67 -c 10
# → Ожидаем DHCPDISCOVER от клиентов

# 6. Восстановить lease-файл (если необходимо)
sudo cp /backup/dhcpd.leases-YYYYMMDD /var/lib/dhcp/dhcpd.leases
sudo systemctl restart isc-dhcp-server
```

### Триггеры для Rollback

| Метрика | Критический порог | Действие |
| :--- | :--- | :--- |
| **DHCPACK rate** | < 80% от baseline за 5 минут | Rollback |
| **Pool exhaustion** | > 95% utilisation | Rollback или масштабирование пула |
| **DHCPNAK rate** | > 5% от ACK rate | Rollback, проблема в конфигурации |
| **Latency DORA** | OFFER не приходит в течение 2 секунд после DISCOVER | Rollback |
| **Client complaints** | > 3 обращения в 10 минут | Rollback |

**Никогда не делайте Big-Bang миграцию в production.** Параллельный режим позволяет мгновенно откатиться при проблемах. Перед миграцией убедитесь, что:
- Бэкап ISC-конфигурации и leases сделан и проверен
- Rollback процедура задокументирована и протестирована
- Все стейкхолдеры уведомлены о окне миграции

### Чеклист после миграции

```bash
# 1. Конфигурация валидна
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf

# 2. Сервис запущен
systemctl status kea-dhcp4 kea-ctrl-agent

# 3. REST API отвечает
curl -s http://localhost:8000/ | jq '.[] | .Dhcp4' | head -5

# 4. Клиенты получают адреса
sudo tcpdump -i eth0 -n udp port 67 -c 20 | grep -E "DHCPACK|DHCPOFFER"

# 5. Логи без ошибок
journalctl -u kea-dhcp4 --since "5 min ago" | grep -iE "error|fail|drop"

# 6. Lease-файл создаётся
ls -la /var/lib/kea/kea-leases4.csv
wc -l /var/lib/kea/kea-leases4.csv

# 7. Статистика пула
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# 8. Firewall: Kea слушает UDP 67
ss -nlup | grep :67
```

---

## Дополнительная информация

### Миграция HA: ISC Failover → Kea HA

ISC DHCP использует проприетарный Failover-протокол (TCP 647). Kea требует MySQL/PostgreSQL backend для глобального HA.

**Этапы миграции HA:**
1. Создайте общую MySQL-инстанцию для обоих серверов Kea
2. Инициализируйте схему через `kea-admin db-init mysql`
3. Перенесите конфигурацию ISC Failover в Kea HA hook
4. Настройте `hot-standby` или `load-balancing` режим
5. Протестируйте отказ одного узла

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
                        "password": "strong_password",
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
                            ]
                        }
                    ]
                }
            }
        ]
    }
}
```

### Влияние на DHCP Snooping и VLAN

При переходе на Kea:
- **DHCP Snooping** bindings остаются на коммутаторах (не зависят от типа сервера)
- **Option 82** должна корректно обрабатываться через `libdhcp_flex_id` или `libdhcp_class_cmds`
- **DAI (Dynamic ARP Inspection)** продолжает работать без изменений
- **IP Source Guard** требует обновления bindings только если изменился IP-адрес сервера

### Мониторинг во время миграции

```bash
# Запустите параллельный мониторинг ISC и Kea
# ISC: парсинг логов
tail -f /var/log/syslog | grep --line-buffered isc-dhcp-server | grep -E "DHCPACK|DHCPOFFER|DHCPDISCOVER" &

# Kea: REST API polling
watch -n 5 'curl -s -X POST http://localhost:8000/ -d "{\"command\": \"statistic-get\", \"args\": {\"name\": \"subnet[1].assigned-addresses\"}}" | jq'

# Сравнение rate выдачи адресов
# ISC:
grep "DHCPACK" /var/log/syslog | tail -100 | wc -l
# Kea:
journalctl -u kea-dhcp4 --since "5 min ago" | grep -c "DHCPACK"
```

### Типичные ошибки при миграции

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Kea не запускается | JSON-синтаксис невалиден | `kea-dhcp4 -t` покажет строку с ошибкой |
| Клиенты не получают адреса | Интерфейс не указан или неверен | `"interfaces": ["eth0"]` — проверить `ip link` |
| Опции не применяются | Имя опции неверно (ISC vs Kea) | Используйте `kea-lfc -L` для списка опций |
| Lease не записывается | Права на `/var/lib/kea/` | `chown -R kea:kea /var/lib/kea/` |
| DHCP Snooping падает | Kea использует другой формат Option 82 | Проверьте `check-option-82` в hooks |
| Failover не работает | ISC Failover ≠ Kea HA | Kea HA требует MySQL backend и hooks |
| `kea-confconv` падает | Неподдерживаемая директива в ISC | Ручная конвертация для сложных блоков |
| Abandoned leases не переносятся | Формат состояния отличается | Используйте REST API `lease4-add` с явным указанием state |

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — полный обзор Kea.
- **[ISC DHCP: Обзор архитектуры](./isc_dhcp_server_overview.md)** — компоненты ISC DHCP.
- **[ISC DHCP: Базовая настройка](./isc_dhcp_server_basic_config.md)** — структура `dhcpd.conf`.
- **[ISC DHCP: Failover](./isc_dhcp_server_failover.md)** — ISC-проприетарный Failover.
- **[Kea DHCP: Production Operations](./kea_production_operations.md)** — day-2 ops, troubleshooting.
- **[Kea DHCP: Безопасность и Hardening](./kea_security_hardening.md)** — TLS, SELinux, firewall.
- **[Обзор DHCP](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** — теория DORA/SARR.
- **[Время аренды](../../../../Networking/Protocols/DHCP/dhcp_lease_time.md)** — таймеры и типы сообщений.
- **[Мониторинг DHCP](../../../../Networking/Protocols/DHCP/dhcp_monitoring_observability.md)** — Prometheus, Grafana, SIEM.
- **[Kea DHCP Documentation — Migration Guide](https://kea.readthedocs.io/en/latest/advanced.html#upgrading-from-isc-dhcp-to-kea)** — официальное руководство ISC.
