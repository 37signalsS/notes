# Kea DHCP: Миграция с ISC DHCP

---

## Определения

**Миграция DHCP** — процесс перехода с ISC DHCP (`dhcpd`) на Kea DHCP (`kea-dhcp4`) с сохранением работоспособности сервиса и данных аренды.

**Конвертация конфигурации** — ручной или автоматический процесс преобразования `dhcpd.conf` (иерархический текст) в `kea-dhcp4.conf` (JSON-формат) с учётом различий в синтаксисе.

**Rollback** — процедура отката к предыдущему состоянию (ISC DHCP) в случае проблем после миграции.

**Параллельная работа (Dual-Run)** — режим, при котором ISC и Kea работают одновременно на разных серверах, разделяя одну сеть.

---

## Основные концепции

### Стратегии миграции

| Стратегия | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Big-Bang** | Один сервер,ISC → Kea за 1 перезапуск | Просто, быстро | Риск простоя |
| **Параллельная работа** | ISC (primary) + Kea (secondary) одновременно | Нулевой пройм, откат за секунду | Требует 2 сервера |
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
- `class`/`subclass` с регулярными выражениями → Kea `client-classes` с不同的 синтаксисом
- `failover peer` → Kea HA hooks (полностью другой механизм)
- `option-82` processing → hooks `libdhcp_class_cmds` или `libdhcp_flex_id`
- `ddns-update-style interim` → Kea DDNS hooks
- `deny/allow unknown-clients` → Kea `client-classification`

**НЕ конвертируется (нет аналога):**
- `omshell` → Используйте REST API
- `dnsmasq` → Kea не имеет встроенного DNS; используйтеBIND9 отдельно
- `filename` для PXE → Используйте `boot-file-name` в option-data

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

# 4. Убедитесь, что Kea установлен на тот же интерфейс
ip -4 addr show | grep -E "inet 10\."
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

```bash
# ISC DHCP хранит leases в текстовом формате
# Kea может импортировать ISC-leases через kea-admin

# 1. Конвертация dhcpd.leases → kea-leases4.csv
# Формат ISC: "lease 10.0.10.25 { ... }"
# Формат Kea: CSV (ip, hw_address, client_id, valid_lifetime, ...)
# Ручной скрипт (пример):
python3 - << 'EOF'
import re
with open('/var/lib/dhcp/dhcpd.leases') as f:
    content = f.read()
leases = re.findall(r'lease (\S+) \{[^}]+\}', content)
print(f"Найдено {len(leases)} ISC-аренд")
# → Для реальной миграции используйте kea-admin lease-migrate или REST API
EOF

# 2. Через REST API Kea (после запуска)
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "lease4-get-all"}' | jq '.arguments.leases | length'

# 3. Импорт через MySQL (если используется MySQL backend)
# INSERT INTO lease4 (address, hwaddr, client_id, ...)
# SELECT ... FROM isc_dhcp_leases;
```

### Пошаговая миграция: параллельный режим

```bash
# === Фаза 1: Подготовка ===
# На сервере Kea (второй сервер):
sudo systemctl stop isc-dhcp-server
# Скопировать конфиг ISC, сконвертировать в Kea-формат
# Запустить Kea на том же IP, что и ISC-primary

# === Фаза 2: Тестирование ===
# Kea работает на secondary,ISC на primary
# Проверить: выдает ли Kea адреса из своего пула
sudo tcpdump -i eth0 -n udp port 67 -c 20
# → Ожидаем DISCOVER/OFFER/REQUEST/ACK от Kea

# === Фаза 3: Swap ===
# ПеревестиISC-сервер в standby
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
```

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

# 7. Старый lease-файл ISC архивирован
ls -la /backup/dhcpd.leases-*

# 8. Firewall:Kea слушает UDP 67
ss -nlup | grep :67
```

---

## Дополнительная информация

### Типичные ошибки при миграции

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Kea не запускается | JSON-синтаксис невалиден | `kea-dhcp4 -t` покажет строку с ошибкой |
| Клиенты не получают адреса | Интерфейс не указан или неверен | `"interfaces": ["eth0"]` — проверить `ip link` |
| Опции не применяются | Имя опции неверно (ISC vs Kea) | Используйте `kea-lfc -L` для списка опций |
| Lease не записывается | Права на `/var/lib/kea/` | `chown -R kea:kea /var/lib/kea/` |
| DHCP Snooping падает | Kea использует другой формат Option 82 | Проверьте `check-option-82` в hooks |
| Failover не работает | ISC Failover ≠ Kea HA | Kea HA требует MySQL backend и hooks |

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — полный обзор Kea.
- **[ISC DHCP: Обзор архитектуры](./isc_dhcp_server_overview.md)** — компоненты ISC DHCP.
- **[ISC DHCP: Базовая настройка](./isc_dhcp_server_basic_config.md)** — структура `dhcpd.conf`.
- **[ISC DHCP: Failover](./isc_dhcp_server_failover.md)** — ISC-проприетарный Failover.
- **[Обзор DHCP](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** — теория DORA/SARR.
- **[Время аренды](../../../../Networking/Protocols/DHCP/dhcp_lease_time.md)** — таймеры и типы сообщений.
- **[Kea DHCP Documentation — Migration Guide](https://kea.readthedocs.io/en/latest/advanced.html#upgrading-from-isc-dhcp-to-kea)** — официальное руководство ISC.
