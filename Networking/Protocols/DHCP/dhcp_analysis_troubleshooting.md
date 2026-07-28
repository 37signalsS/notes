# Диагностика и анализ трафика DHCP

> **Надёжность: 10/10** (SSoT + Web Verification)
> **Актуальность: 2026-07** (Статус: Актуально)

## Определения

**Анализ трафика DHCP (Dynamic Host Configuration Protocol)** — процесс перехвата и декодирования пакетов протокола для выявления ошибок в конфигурации, сетевых задержек или несанкционированных действий (Rogue DHCP).

**Диагностика (troubleshooting) DHCP** — систематический процесс поиска причин отказа в выдаче IP-адресов, от физического уровня до прикладного.

**APIPA (Automatic Private IP Addressing)** — механизм самоназначения адреса из сети `169.254.0.0/16` (IPv4) или `fe80::/10` (IPv6 Link-Local), когда DHCP-сервер недоступен.

## Сравнение процессов DORA (v4) и SARR (v6)

Для эффективной диагностики необходимо понимать различия в хендшейках протоколов:

| Этап | DHCPv4 (DORA) | DHCPv6 (SARR) | Транспорт |
| :--- | :--- | :--- | :--- |
| **1. Поиск** | **D**iscover (Broadcast) | **S**olicit (Multicast `ff02::1:2`) | UDP 67/68 (v4), 547/546 (v6) |
| **2. Ответ** | **O**ffer (Unicast/Broadcast) | **A**dvertise (Unicast) | - |
| **3. Запрос** | **R**equest (Broadcast) | **R**equest (Multicast) | - |
| **4. Финал** | **A**cknowledge (Unicast) | **R**eply (Unicast) | - |

> **Примечание:** В IPv6 шлюз по умолчанию не передаётся через DHCP, а получается через **Router Advertisements (RA)**.

## Практические сценарии диагностики

### Анализ на стороне клиента

#### Генерация трафика (Force Renew)
| ОС | Команда |
| :--- | :--- |
| **Windows** | `ipconfig /release` && `ipconfig /renew` |
| **Linux (dhclient)** | `sudo dhclient -r` && `sudo dhclient -v eth0` |
| **Linux (NetworkManager)** | `nmcli con up <con_name>` |

#### Проверка Multicast (IPv6)
Если клиент IPv6 не получает адрес, проверьте подписку на группы:
```bash
ip -6 maddr show eth0
# Должен присутствовать ff02::1:2
```

### Анализ на стороне сервера и Relay Agent

#### Поиск в системных журналах
Наиболее частая ошибка — **Pool Exhaustion** (исчерпание пула).
```bash
# Просмотр логов в реальном времени
journalctl -u isc-dhcp-server -f | grep "no free leases"
```

#### Проверка базы данных аренды
```bash
# IPv4
cat /var/lib/dhcp/dhcpd.leases
# IPv6
cat /var/lib/dhcp/dhcpd6.leases
```

### Анализ трафика (tcpdump & Wireshark)

#### Рекомендуемые фильтры tcpdump
```bash
# Захват IPv4 DHCP (порты 67, 68)
sudo tcpdump -i eth0 -n udp port 67 or port 68 -vv

# Захват IPv6 DHCP (порты 546, 547)
sudo tcpdump -i eth0 -n udp port 546 or port 547 -vv

# Фильтрация по конкретному MAC (chaddr) в IPv4
sudo tcpdump -i eth0 -vv -n "udp port 67 and ether host aa:bb:cc:dd:ee:ff"
```

#### Поля для анализа в Wireshark
- **`giaddr` (Relay Agent IP):** Если пакет пришёл через ретранслятор, это поле должно содержать IP интерфейса ретранслятора. Если оно пустое (`0.0.0.0`), сервер будет искать пул в своей локальной сети.
- **`Option 53` (Message Type):** Тип сообщения (Discover, Request и т.д.).
- **`Option 82` (Relay Agent Information):** Проверьте наличие `Circuit-ID` и `Remote-ID`, если используется сегрегация портов.

## Продвинутые инструменты диагностики

### Nmap DHCP Discover
Позволяет проверить наличие серверов в сети без смены IP-адреса системы.
```bash
# Поиск IPv4 серверов (broadcast)
sudo nmap --script broadcast-dhcp-discover

# Поиск IPv6 серверов (multicast)
sudo nmap --script broadcast-dhcp6-discover
```

### dhcpcd (Test Mode)
Позволяет выполнить запрос и вывести полученные опции без применения настроек к интерфейсу.
```bash
dhcpcd -T eth0
```

## Типичные проблемы и методы решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **APIPA (169.254.x.x)** | Нет ответа от сервера | `tcpdump` на сервере: приходят ли запросы? | Проверить L2-связность, Firewall (UDP 67/547). |
| **No Free Leases** | Пул исчерпан | `grep "no free leases" /var/log/syslog` | Увеличить `range` или уменьшить `lease-time`. |
| **Конфликт IP** | Статический IP в пуле | `DHCPDECLINE` в трафике клиента | Включить `ping-check` на сервере перед выдачей. |
| **Неверный шлюз (v6)** | Проблема в RA | `tcpdump icmp6` (тип 134) | Проверить конфигурацию `radvd` или маршрутизатора. |

## Дополнительная информация

- [DHCP — Обзор протокола](./dhcp_overview.md) — базовые концепции и хендшейки.
- [Время аренды и типы сообщений](./dhcp_lease_time.md) — детальный разбор таймеров и типов пакетов.
- [Безопасность DHCP](./dhcp_security.md) — защита от Rogue DHCP и атак истощения.
- [Настройка ISC DHCP Relay](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_relay.md) — практическая диагностика ретрансляции.
